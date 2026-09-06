#!/usr/bin/env python3
"""Run the whole DriftZero stack on one machine.

Supervises the API, the recovery and alert workers, the operator dashboard, and the
ShopAssist chatbot, then shuts them all down together.

Each piece needs the others to be useful. Approving a recovery plan only queues a command,
so an API without the recovery worker leaves every recovery stuck in 'queued'. ShopAssist
turns every twenty chat interactions into a health snapshot, which is what gives the
dashboard something to detect. So this wires all of them to the API it just started rather
than to whatever each project's own .env file happens to name.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
SHOP_ASSIST = ROOT / "shop-assist"
WINDOWS = os.name == "nt"

processes: list[tuple[str, subprocess.Popen[bytes]]] = []


def backend_python() -> str:
    """Prefer the backend virtualenv so the API runs against its installed dependencies."""

    directory, executable = ("Scripts", "python.exe") if WINDOWS else ("bin", "python")
    candidate = BACKEND / ".venv" / directory / executable
    return str(candidate) if candidate.exists() else sys.executable


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1)
        return probe.connect_ex((host, port)) != 0


def require_free(host: str, port: int, label: str, flag: str) -> None:
    if port_is_free(host, port):
        return
    sys.exit(
        f"Port {port} ({label}) is already in use.\n"
        f"Stop whatever is listening on it, or choose another port with {flag}."
    )


def backend_environment(args: argparse.Namespace) -> dict[str, str]:
    database = args.database or f"sqlite:///{(BACKEND / 'driftzero.db').as_posix()}"
    origins = ",".join(
        f"http://{name}:{args.dashboard_port}" for name in ("127.0.0.1", "localhost")
    )
    return dict(
        os.environ,
        DRIFTZERO_DATABASE_URL=database,
        DRIFTZERO_ENVIRONMENT="development",
        # Without this the API demands a bearer token for approve and execute, and the
        # dashboard's recovery button fails with 401.
        DRIFTZERO_RECOVERY_ALLOW_LOCAL_IDENTITY="true",
        DRIFTZERO_RECOVERY_WORKER_INTERVAL_SECONDS="1",
        DRIFTZERO_ALERT_EVALUATION_INTERVAL_SECONDS="30",
        DRIFTZERO_CORS_ORIGINS=origins,
        PYTHONUNBUFFERED="1",
    )


def spawn(label: str, command: list[str], environment: dict[str, str], cwd: Path) -> subprocess.Popen[bytes]:
    print(f"  starting {label}")
    process = subprocess.Popen(command, env=environment, cwd=str(cwd))
    processes.append((label, process))
    return process


def wait_for_api(base_url: str, api: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if api.poll() is not None:
            sys.exit(f"The API exited during startup with code {api.returncode}.")
        try:
            with urllib.request.urlopen(f"{base_url}/healthz", timeout=1):
                return
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    sys.exit("The API did not become healthy within 60 seconds.")


def seed_demo(base_url: str) -> None:
    request = urllib.request.Request(
        f"{base_url}/api/v1/demo/reset",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read() or b"{}")
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"  warning: could not seed the demo scenario ({exc})")
        return
    model = payload.get("model") or {}
    print(f"  seeded the ShopAssist scenario (model {model.get('name', 'unknown')})")


def write_dashboard_environment(base_url: str) -> None:
    """The dashboard reads .env.local at startup, and it takes priority over shell variables."""

    (FRONTEND / ".env.local").write_text(
        f"VITE_API_BASE_URL={base_url}\nVITE_DEMO_MODE=false\n", encoding="utf-8"
    )


def stop(_signum: int | None = None, _frame: object | None = None) -> None:
    for label, process in reversed(processes):
        if process.poll() is None:
            print(f"  stopping {label}")
            process.terminate()
    deadline = time.monotonic() + 10
    for _, process in processes:
        try:
            process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the DriftZero stack locally.")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--dashboard-port", type=int, default=5173)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--database", help="SQLAlchemy URL (default: backend/driftzero.db)")
    parser.add_argument("--shop-assist-port", type=int, default=3000)
    parser.add_argument("--no-seed", action="store_true", help="Keep the existing database contents")
    parser.add_argument("--no-dashboard", action="store_true", help="Do not run the operator dashboard")
    parser.add_argument("--no-shop-assist", action="store_true", help="Do not run the ShopAssist chatbot")
    args = parser.parse_args()

    npm = shutil.which("npm")
    node_apps: list[tuple[str, Path, int, str]] = []
    if not args.no_dashboard:
        node_apps.append(("dashboard", FRONTEND, args.dashboard_port, "--dashboard-port"))
    if not args.no_shop_assist:
        node_apps.append(("shop-assist", SHOP_ASSIST, args.shop_assist_port, "--shop-assist-port"))
    if node_apps and npm is None:
        sys.exit("npm was not found on PATH. Install Node.js, or pass --no-dashboard --no-shop-assist.")
    for label, directory, _, _ in node_apps:
        if not (directory / "node_modules").exists():
            sys.exit(f"Install the {label} dependencies first:\n  cd {directory}\n  npm install")

    require_free(args.host, args.api_port, "API", "--api-port")
    for label, _, port, flag in node_apps:
        require_free(args.host, port, label, flag)

    python = backend_python()
    probe = subprocess.run(
        [python, "-c", "import app.main"], cwd=str(BACKEND), capture_output=True, check=False
    )
    if probe.returncode:
        sys.exit(
            f"The backend dependencies are missing. Install them first:\n"
            f"  cd {BACKEND}\n  python -m venv .venv\n  .venv/Scripts/pip install -e \".[dev]\""
        )

    base_url = f"http://{args.host}:{args.api_port}"
    environment = backend_environment(args)

    print("DriftZero local stack")
    api = spawn(
        "api",
        [
            python, "-m", "uvicorn", "app.main:app",
            "--host", args.host, "--port", str(args.api_port), "--no-access-log",
        ],
        environment,
        BACKEND,
    )
    wait_for_api(base_url, api)
    if not args.no_seed:
        seed_demo(base_url)

    # Started after the API so the schema exists before a worker runs its first query.
    spawn("recovery worker", [python, "-m", "app.recovery_worker"], environment, BACKEND)
    spawn("alert worker", [python, "-m", "app.alert_worker"], environment, BACKEND)

    urls: list[tuple[str, str]] = [("API", f"{base_url}  (OpenAPI docs at {base_url}/docs)")]
    if not args.no_dashboard and npm is not None:
        write_dashboard_environment(base_url)
        # Vite binds the "localhost" name rather than a literal address, so advertise that
        # form; both spellings are in the API's allowed CORS origins either way.
        urls.append(("dashboard", f"http://localhost:{args.dashboard_port}"))
        spawn(
            "dashboard",
            [npm, "run", "dev", "--", "--port", str(args.dashboard_port), "--strictPort"],
            dict(os.environ),
            FRONTEND,
        )
    if not args.no_shop_assist and npm is not None:
        # Next.js lets a real environment variable win over .env.local, so the chatbot's
        # telemetry reaches the API this script started rather than the file's default.
        spawn(
            "shop-assist",
            [npm, "run", "dev", "--", "--port", str(args.shop_assist_port)],
            dict(os.environ, DRIFTZERO_API_URL=base_url),
            SHOP_ASSIST,
        )
        urls.append(("shop-assist", f"http://localhost:{args.shop_assist_port}  (presenter controls at /demo)"))

    print("\nready")
    for label, url in urls:
        print(f"  {label:<12} {url}")
    print("  press Ctrl+C to stop everything\n")

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        while True:
            for label, process in processes:
                code = process.poll()
                if code is not None:
                    print(f"\n{label} exited with code {code}; shutting the stack down.")
                    return code or 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
    finally:
        stop()


if __name__ == "__main__":
    raise SystemExit(main())
