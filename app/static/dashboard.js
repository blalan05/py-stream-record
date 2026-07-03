async function postForm(url, data = {}) {
  const body = new URLSearchParams(data);
  const resp = await fetch(url, { method: "POST", body });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.error || resp.statusText);
  }
  return resp.json();
}

async function postJson(url, data) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.error || (err.errors || []).join("; ") || resp.statusText);
  }
  return resp.json();
}

const isUsbCamera = () => window.THEATER_CAPTURE_SOURCE === "usb";
let v4l2Panel = null;

function showName() {
  return document.getElementById("show-name").value.trim();
}

function updateRecBadge(recording) {
  const badge = document.getElementById("rec-badge");
  if (!badge) return;
  badge.classList.toggle("active", recording);
  badge.textContent = recording ? "● REC" : "○ IDLE";
}

function updateRecordStatus(data) {
  const el = document.getElementById("record-status");
  if (!el) return;
  if (data.recording) {
    el.innerHTML = `Recording <strong>${data.show_name}</strong> (${data.elapsed_seconds}s)`;
  } else {
    el.textContent = "Not recording";
  }
  updateRecBadge(data.recording);
}

async function refreshHealth() {
  try {
    const resp = await fetch("/api/health");
    if (!resp.ok) return;
    const h = await resp.json();
    document.getElementById("stream-ready")?.textContent = h.stream_ready ? "Ready" : "Waiting";
    document.getElementById("capture-status")?.textContent = h.capture.running ? "Running" : "Stopped";
    document.getElementById("disk-free")?.textContent = `${h.disk.free_gb} GB`;
    document.getElementById("cpu-temp")?.textContent = h.cpu_temp_c ?? "N/A";
    document.getElementById("sync-pending")?.textContent = h.sync.pending_count;
    updateRecordStatus(h.recording);

    const previewStatus = document.getElementById("preview-status");
    if (previewStatus && !h.stream_ready && h.capture.last_error) {
      previewStatus.textContent = `Capture error: ${h.capture.last_error.slice(0, 200)}`;
      previewStatus.style.color = "#f88";
    } else if (previewStatus && !h.stream_ready && !previewStatus.textContent.startsWith("Connecting")) {
      previewStatus.textContent = "Waiting for stream from capture…";
      previewStatus.style.color = "";
    }
  } catch (err) {
    console.warn("Health refresh failed", err);
  }
}

function csiCameraPayload() {
  return {
    exposure_lock: document.getElementById("exposure-lock").checked,
    awb_lock: document.getElementById("awb-lock").checked,
    shutter_us: Number(document.getElementById("shutter").value),
    gain: Number(document.getElementById("gain").value),
    lens_position: Number(document.getElementById("lens").value),
    af_mode: Number(document.getElementById("lens").value) > 0 ? "manual" : "continuous",
  };
}

document.getElementById("btn-start")?.addEventListener("click", async () => {
  try {
    const data = await postForm("/api/recording/start", { show_name: showName() });
    updateRecordStatus(data);
  } catch (e) {
    alert(e.message);
  }
});

document.getElementById("btn-stop")?.addEventListener("click", async () => {
  const data = await postForm("/api/recording/stop");
  updateRecordStatus(data);
});

document.getElementById("btn-start-show")?.addEventListener("click", async () => {
  const preset = document.getElementById("preset-select")?.value || "";
  try {
    const body = new URLSearchParams({ show_name: showName(), preset });
    const resp = await fetch("/api/start-show", { method: "POST", body });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Start show failed");
    updateRecordStatus(data.recording);
    alert("Show started — stream verified and recording.");
  } catch (e) {
    alert(e.message);
  }
});

document.getElementById("btn-camera-save")?.addEventListener("click", async () => {
  const payload = csiCameraPayload();
  await postJson("/api/camera", payload);
  alert("Camera settings applied (capture restarted).");
});

document.getElementById("btn-preset-apply")?.addEventListener("click", async () => {
  const name = document.getElementById("preset-select").value;
  if (!name) return alert("Select a preset");
  const result = await postJson("/api/presets/apply", { name });
  if (isUsbCamera() && result.controls) {
    await v4l2Panel?.refresh?.();
  } else {
    location.reload();
  }
});

document.getElementById("btn-preset-save")?.addEventListener("click", async () => {
  const name = document.getElementById("preset-name").value.trim();
  if (!name) return alert("Enter a preset name");
  const payload = { name };
  if (isUsbCamera()) {
    const root = document.getElementById("v4l2-controls");
    payload.v4l2 = root ? collectV4l2Values(root) : {};
  } else {
    payload.camera = csiCameraPayload();
  }
  await postJson("/api/presets", payload);
  alert("Preset saved");
  location.reload();
});

document.addEventListener("DOMContentLoaded", async () => {
  refreshHealth();
  if (isUsbCamera()) {
    v4l2Panel = await initV4l2CameraPanel();
  }
});

setInterval(refreshHealth, 5000);
