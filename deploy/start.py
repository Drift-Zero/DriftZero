#!/usr/bin/env python3
"""Small process supervisor for the single-container hackathon deployment."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

processes: list[subprocess.Popen[bytes]] = []


def stop(_signum: int | None = None, _frame: object | None = None) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 10
    for process in processes:
        remaining = max(0, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            process.kill()


def main() -> int:
    port = os.getenv("PORT", "10000")
    api = subprocess.Popen(
        [
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            port,
            "--no-access-log",
        ]
    )
    processes.append(api)

    # The API creates the initial schema. Starting a worker before that race is
    # resolved makes a fresh deployment fail on its first database query.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if api.poll() is not None:
            return api.returncode or 1
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1):
                break
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    else:
        return 1

    # The single-container deployment is a hackathon compromise for hosts where
    # separate services cannot share the ephemeral SQLite database. Keep every
    # long-running worker beside the API so hosted behavior matches Compose.
    processes.extend(
        [
            subprocess.Popen([sys.executable, "-m", "app.alert_worker"]),
            subprocess.Popen([sys.executable, "-m", "app.recovery_worker"]),
            subprocess.Popen([sys.executable, "-m", "app.retention_worker"]),
        ]
    )
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while True:
            for process in processes:
                return_code = process.poll()
                if return_code is not None:
                    return return_code or 1
            time.sleep(0.5)
    finally:
        stop()


if __name__ == "__main__":
    raise SystemExit(main())
