const state = { registry: null, status: null };
const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const res = await fetch(path, { headers: {"Content-Type":"application/json"}, ...options });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

function activeProvider() {
  return state.registry.providers.find(p => p.id === $("providerSelect").value) || state.registry.providers[0];
}

function syncModels() {
  const provider = activeProvider();
  $("modelSelect").innerHTML = provider.models.map(m => `<option value="${m.id}">${m.label}</option>`).join("");
  const preferred = provider.models.find(m => m.id === state.registry.default_model) || provider.models[0];
  $("modelSelect").value = preferred.id;
  syncModelDisplay();
}

function syncModelDisplay() {
  const provider = activeProvider();
  const model = provider.models.find(m => m.id === $("modelSelect").value) || provider.models[0];
  $("modelPill").textContent = model.label;
  $("routeModel").textContent = model.label;
  if (model.default_effort) $("effortSelect").value = model.default_effort;
}

function renderModelCards() {
  const enabled = state.registry.providers.filter(p => p.enabled);
  $("modelCards").innerHTML = enabled.flatMap(p => p.models.map(m => `
    <div class="model-card">
      <header><strong>${m.label}</strong><span class="badge neutral">${m.tier}</span></header>
      <p>${m.recommended_for}</p><code>${m.id}</code>
    </div>`)).join("");
}

function renderStatus() {
  const s = state.status;
  const set = (id, text, good) => { const el=$(id); el.textContent=text; el.className=good?"good":"bad"; };
  set("hermesStatus", s.hermes.available ? `Ready${s.hermes.version ? ` · ${s.hermes.version}` : ""}` : "Not found", s.hermes.available);
  set("claudeStatus", s.anthropic.configured ? "Credential detected" : "Use Hermes auth / API key", s.anthropic.configured);
  set("jevStatus", s.jev.configured ? "Configured" : "Not configured", s.jev.configured);
  $("runBtn").disabled = !s.hermes.available;
  $("healthDot").className = `dot ${s.hermes.available ? "ok" : "warn"}`;
  $("healthText").textContent = s.hermes.available ? "Hermes runtime ready" : "Preview mode available";
}

async function preview() {
  const prompt = $("taskInput").value.trim();
  if (!prompt) return showOutput("Enter a task first.");
  $("routeStatus").textContent = "Preview";
  const data = await api("/api/preview", {method:"POST", body:JSON.stringify({
    prompt, provider:$("providerSelect").value, model:$("modelSelect").value,
    reasoning_effort:$("effortSelect").value, workspace:$("workspaceInput").value.trim()
  })});
  showOutput(JSON.stringify(data, null, 2));
}

async function run() {
  const prompt = $("taskInput").value.trim();
  if (!prompt) return showOutput("Enter a task first.");
  $("routeStatus").textContent = "Running";
  $("runBtn").disabled = true;
  showOutput("Running through Hermes + Claude…\n");
  try {
    const data = await api("/api/run", {method:"POST", body:JSON.stringify({
      prompt, provider:$("providerSelect").value, model:$("modelSelect").value,
      reasoning_effort:$("effortSelect").value, workspace:$("workspaceInput").value.trim(), safe_mode:true
    })});
    $("routeStatus").textContent = data.ok ? "Complete" : "Failed";
    showOutput(data.output || JSON.stringify(data, null, 2));
  } catch (err) {
    $("routeStatus").textContent = "Failed";
    showOutput(`ERROR\n${err.message}`);
  } finally {
    $("runBtn").disabled = !state.status?.hermes?.available;
  }
}

function showOutput(text) { $("output").textContent = text; }

function wireNavigation() {
  document.querySelectorAll(".nav-item").forEach(btn => btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach(x => x.classList.remove("active"));
    document.querySelectorAll(".view").forEach(x => x.classList.remove("active-view"));
    btn.classList.add("active");
    document.getElementById(btn.dataset.view).classList.add("active-view");
  }));
}

async function init() {
  wireNavigation();
  state.registry = await api("/api/models");
  $("providerSelect").innerHTML = state.registry.providers.filter(p => p.enabled).map(p => `<option value="${p.id}">${p.label}</option>`).join("");
  $("providerSelect").value = state.registry.default_provider;
  syncModels();
  renderModelCards();
  state.status = await api("/api/status");
  renderStatus();
  $("providerSelect").addEventListener("change", syncModels);
  $("modelSelect").addEventListener("change", syncModelDisplay);
  $("previewBtn").addEventListener("click", () => preview().catch(e => showOutput(e.message)));
  $("runBtn").addEventListener("click", run);
  $("clearBtn").addEventListener("click", () => {
    showOutput("No run yet. Preview a route or execute a task.");
    $("routeStatus").textContent = "Idle";
  });
}

init().catch(err => showOutput(`Console failed to initialise: ${err.message}`));
