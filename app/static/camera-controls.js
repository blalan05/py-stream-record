const GROUP_LABELS = {
  exposure: "Exposure",
  white_balance: "White balance",
  focus_zoom: "Focus & zoom",
  image: "Image",
  other: "Other",
};

let controlState = { byName: {}, groups: {} };
let applyTimer = null;

async function fetchV4l2Controls() {
  const resp = await fetch("/api/camera/controls");
  if (resp.status === 401) {
    throw new Error("Log in on the dashboard to adjust camera controls.");
  }
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.error || resp.statusText);
  }
  return resp.json();
}

async function applyV4l2Controls(controls) {
  const resp = await fetch("/api/camera/controls", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ controls }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data.error || (data.errors || []).join("; ") || resp.statusText);
  }
  if (data.controls) {
    indexControls(data);
    syncControlInputs(data.controls);
  }
  return data;
}

function indexControls(data) {
  controlState.byName = {};
  for (const ctrl of data.controls || []) {
    controlState.byName[ctrl.name] = ctrl;
  }
  controlState.groups = data.groups || {};
}

function syncControlInputs(controls) {
  for (const ctrl of controls) {
    const el = document.querySelector(`[data-v4l2-name="${ctrl.name}"]`);
    if (!el) continue;
    if (el.type === "checkbox") {
      el.checked = Boolean(ctrl.value);
    } else {
      el.value = ctrl.value;
    }
    el.disabled = Boolean(ctrl.inactive);
    const hint = el.closest(".v4l2-control")?.querySelector(".v4l2-hint");
    if (hint) {
      hint.textContent = ctrl.inactive ? "Enable manual mode first" : "";
    }
  }
}

function renderControl(ctrl) {
  const wrap = document.createElement("div");
  wrap.className = "v4l2-control";
  const label = document.createElement("label");
  label.textContent = ctrl.label || ctrl.name.replace(/_/g, " ");

  if (ctrl.type === "bool") {
    const row = document.createElement("label");
    row.className = "v4l2-bool";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.dataset.v4l2Name = ctrl.name;
    input.checked = Boolean(ctrl.value);
    input.disabled = Boolean(ctrl.inactive);
    row.appendChild(input);
    row.append(" ", label.textContent);
    wrap.appendChild(row);
  } else if (ctrl.min !== undefined && ctrl.max !== undefined) {
    label.textContent += ` (${ctrl.min}–${ctrl.max})`;
    wrap.appendChild(label);
    const input = document.createElement("input");
    input.type = ctrl.max - ctrl.min > 20 ? "range" : "number";
    input.dataset.v4l2Name = ctrl.name;
    input.min = ctrl.min;
    input.max = ctrl.max;
    input.step = ctrl.step || 1;
    input.value = ctrl.value ?? ctrl.default ?? ctrl.min;
    input.disabled = Boolean(ctrl.inactive);
    wrap.appendChild(input);
  } else {
    wrap.appendChild(label);
    const input = document.createElement("input");
    input.type = "number";
    input.dataset.v4l2Name = ctrl.name;
    input.value = ctrl.value ?? ctrl.default ?? 0;
    input.disabled = Boolean(ctrl.inactive);
    wrap.appendChild(input);
  }

  const hint = document.createElement("div");
  hint.className = "v4l2-hint muted";
  if (ctrl.inactive) hint.textContent = "Enable manual mode first";
  wrap.appendChild(hint);
  return wrap;
}

function queueApply(name, value) {
  window.clearTimeout(applyTimer);
  applyTimer = window.setTimeout(async () => {
    try {
      await applyV4l2Controls({ [name]: value });
    } catch (err) {
      console.error(err);
      const status = document.getElementById("v4l2-status");
      if (status) status.textContent = String(err.message || err);
    }
  }, 120);
}

function bindControlInputs(root) {
  root.querySelectorAll("[data-v4l2-name]").forEach((el) => {
    const event = el.type === "checkbox" ? "change" : "input";
    el.addEventListener(event, () => {
      const value = el.type === "checkbox" ? (el.checked ? 1 : 0) : Number(el.value);
      queueApply(el.dataset.v4l2Name, value);
    });
  });
}

function renderV4l2Controls(container, data) {
  container.innerHTML = "";
  indexControls(data);
  const order = ["exposure", "white_balance", "focus_zoom", "image", "other"];
  for (const groupKey of order) {
    const names = controlState.groups[groupKey];
    if (!names?.length) continue;
    const section = document.createElement("div");
    section.className = "v4l2-group";
    const heading = document.createElement("h4");
    heading.textContent = GROUP_LABELS[groupKey] || groupKey;
    section.appendChild(heading);
    for (const name of names) {
      const ctrl = controlState.byName[name];
      if (ctrl) section.appendChild(renderControl(ctrl));
    }
    container.appendChild(section);
  }
  bindControlInputs(container);
}

function collectV4l2Values(root) {
  const values = {};
  root.querySelectorAll("[data-v4l2-name]").forEach((el) => {
    values[el.dataset.v4l2Name] = el.type === "checkbox" ? (el.checked ? 1 : 0) : Number(el.value);
  });
  return values;
}

async function initV4l2CameraPanel(options = {}) {
  const container = document.getElementById(options.containerId || "v4l2-controls");
  const status = document.getElementById(options.statusId || "v4l2-status");
  if (!container) return;

  try {
    const data = await fetchV4l2Controls();
    if (!data.available) {
      container.innerHTML = `<p class="muted">${data.error || "V4L2 controls unavailable"}</p>`;
      return;
    }
    renderV4l2Controls(container, data);
    if (status) status.textContent = `Device ${data.device} — changes apply live`;
  } catch (err) {
    container.innerHTML = `<p class="error">${err.message || err}</p>`;
  }

  document.getElementById(options.refreshId || "btn-v4l2-refresh")?.addEventListener("click", async () => {
    const data = await fetchV4l2Controls();
    renderV4l2Controls(container, data);
    if (status) status.textContent = "Controls refreshed";
  });

  return {
    getValues: () => collectV4l2Values(container),
    applyPreset: async (values) => applyV4l2Controls(values),
    refresh: async () => {
      const data = await fetchV4l2Controls();
      renderV4l2Controls(container, data);
    },
  };
}

window.initV4l2CameraPanel = initV4l2CameraPanel;
window.applyV4l2Controls = applyV4l2Controls;
window.collectV4l2Values = collectV4l2Values;
