const API = "/api/v1";

const state = { modelId: null, planId: null, recoveryState: null };
const element = (id) => document.getElementById(id);

function setConnection(online, text) {
  const wrapper = element("connection-dot").parentElement;
  wrapper.className = `connection ${online ? "online" : "offline"}`;
  element("connection-text").textContent = text;
}

function setNotice(message, error = false) {
  element("notice").textContent = message;
  element("notice").style.color = error ? "var(--red)" : "var(--amber)";
}

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: {
      "Content-Type": "application/json",
      "X-DriftZero-Actor": "dashboard-operator",
      "X-DriftZero-Role": "operator",
      ...(options.headers || {}),
    },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
  return body;
}

function renderTrajectory(health) {
  const points = health.snapshots.map((snapshot, index) => ({
    score: snapshot.score,
    label: index === health.snapshots.length - 1 ? "now" : `-${(health.snapshots.length - 1 - index) * 30}m`,
    kind: snapshot.state,
  }));
  if (health.forecast) points.push({ score: health.forecast.predicted_score, label: "+30m", kind: "forecast" });
  element("trajectory").innerHTML = points.map((point) => `
    <div class="bar-wrap"><b>${point.score.toFixed(1)}</b><div class="bar ${point.kind}" style="height:${Math.max(point.score, 5)}%"></div><span>${point.label}</span></div>
  `).join("");
}

function render(demo) {
  const latest = demo.health.snapshots.at(-1);
  const forecast = demo.health.forecast;
  state.modelId = demo.model.id;
  state.planId = demo.recovery.id;
  state.recoveryState = demo.recovery.state;

  element("health-score").textContent = latest.score.toFixed(1);
  element("health-state").textContent = latest.state.toUpperCase();
  element("health-state").className = `status-pill ${latest.state}`;
  element("sample-note").textContent = `${latest.sample_size} requests • ${(latest.coverage * 100).toFixed(0)}% coverage • ${latest.source}`;
  element("forecast-score").textContent = forecast ? forecast.predicted_score.toFixed(1) : "--";
  element("forecast-range").textContent = forecast ? `${forecast.lower_bound.toFixed(1)}–${forecast.upper_bound.toFixed(1)} confidence range • ${forecast.direction}` : "Insufficient history";
  element("cause").textContent = demo.diagnosis.probable_cause.replaceAll("_", " ");
  element("confidence").textContent = `${(demo.diagnosis.confidence * 100).toFixed(0)}% ${demo.diagnosis.confidence_label} confidence`;
  element("recovery-state").textContent = demo.recovery.state;
  element("recovery-note").textContent = demo.recovery.simulation ? "Mock adapter; no real production action" : "Live adapter";
  element("model-name").textContent = demo.model.name;
  element("severity").textContent = demo.incident.severity;
  element("incident-state").textContent = demo.incident.state;
  element("trough").textContent = demo.incident.trough_score.toFixed(1);
  renderTrajectory(demo.health);

  element("evidence").innerHTML = demo.diagnosis.evidence.slice(0, 5).map((item) => `
    <li><b>${item.metric.replaceAll("_", " ")}</b><br>${item.summary}</li>
  `).join("");
  element("actions").innerHTML = demo.recovery.actions.map((action) => `
    <li><b>${action.title}</b> — ${action.description}</li>
  `).join("");
  updateButtons();
}

function updateButtons() {
  element("approve-button").disabled = state.recoveryState !== "recommended";
  element("execute-button").disabled = state.recoveryState !== "approved";
}

async function resetDemo() {
  setNotice("Seeding deterministic CampusGPT degradation…");
  toggleBusy(true);
  try {
    const demo = await request("/demo/reset", { method: "POST" });
    render(demo);
    setConnection(true, "API online");
    setNotice("Demo reset: health degraded from 92 to 61.");
  } catch (error) {
    setConnection(false, "API unavailable");
    setNotice(error.message, true);
  } finally { toggleBusy(false); updateButtons(); }
}

async function approve() {
  setNotice("Recording operator approval…");
  toggleBusy(true);
  try {
    const recovery = await request(`/recovery/${state.planId}/approve`, { method: "POST", body: JSON.stringify({ actor: "dashboard-operator" }) });
    state.recoveryState = recovery.state;
    element("recovery-state").textContent = recovery.state;
    setNotice("Playbook approved. Execution is now enabled.");
  } catch (error) { setNotice(error.message, true); }
  finally { toggleBusy(false); updateButtons(); }
}

async function execute() {
  setNotice("Queueing simulated recovery for the worker…");
  toggleBusy(true);
  try {
    let command = await request(`/recovery/${state.planId}/execute`, {
      method: "POST",
      body: JSON.stringify({ actor: "dashboard-operator", idempotency_key: `dashboard-${state.planId}` }),
    });
    setNotice("Recovery queued. Waiting for worker verification…");
    const deadline = Date.now() + 30000;
    while (!["succeeded", "failed"].includes(command.state) && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 500));
      command = await request(`/recovery-commands/${command.id}`);
    }
    if (command.state !== "succeeded") throw new Error(command.error || "Recovery worker timed out");
    const recovery = await request(`/recovery/${state.planId}`);
    state.recoveryState = recovery.state;
    const [health, incidents, diagnosis] = await Promise.all([
      request(`/models/${state.modelId}/health`),
      request(`/models/${state.modelId}/incidents`),
      request(`/models/${state.modelId}/diagnoses/latest`),
    ]);
    element("recovery-state").textContent = recovery.state;
    element("health-score").textContent = health.snapshots.at(-1).score.toFixed(1);
    element("health-state").textContent = health.snapshots.at(-1).state.toUpperCase();
    element("health-state").className = `status-pill ${health.snapshots.at(-1).state}`;
    element("incident-state").textContent = incidents[0]?.state || "resolved";
    element("confidence").textContent = `${(diagnosis.confidence * 100).toFixed(0)}% ${diagnosis.confidence_label} confidence • ${diagnosis.status}`;
    renderTrajectory(health);
    setNotice(`Recovery verified: health restored to ${health.snapshots.at(-1).score.toFixed(1)}.`);
  } catch (error) { setNotice(error.message, true); }
  finally { toggleBusy(false); updateButtons(); }
}

function toggleBusy(busy) {
  element("reset-button").disabled = busy;
  if (busy) {
    element("approve-button").disabled = true;
    element("execute-button").disabled = true;
  }
}

element("reset-button").addEventListener("click", resetDemo);
element("approve-button").addEventListener("click", approve);
element("execute-button").addEventListener("click", execute);
resetDemo();
