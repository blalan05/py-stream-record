async function postForm(url, data = {}) {
  const body = new URLSearchParams(data);
  const resp = await fetch(url, { method: "POST", body, credentials: "same-origin" });
  const contentType = resp.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    if (resp.redirected || resp.url.includes("/login")) {
      throw new Error("Session expired — log in again.");
    }
    throw new Error(`Unexpected response (${resp.status})`);
  }
  const payload = await resp.json();
  if (!resp.ok) {
    throw new Error(payload.error || resp.statusText);
  }
  return payload;
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
let lastStreamBytes = null;
let lastStreamTimestamp = null;

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

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function formatBitrate(bps) {
  if (bps == null || Number.isNaN(bps) || bps <= 0) return "—";
  if (bps >= 1_000_000) return `${(bps / 1_000_000).toFixed(1)} Mbps`;
  return `${Math.round(bps / 1000)} kbps`;
}

function formatUptime(readyTime) {
  if (!readyTime) return "—";
  const start = new Date(readyTime).getTime();
  if (Number.isNaN(start)) return "—";
  const seconds = Math.max(0, Math.floor((Date.now() - start) / 1000));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function updateStreamStats(stream) {
  if (!stream) return;
  setText("stream-viewers", String(stream.readers ?? 0));
  setText("stream-uptime", stream.ready ? formatUptime(stream.ready_time) : "—");
  const trackLabels = (stream.tracks || [])
    .map((t) => `${t.type || "?"}${t.codec ? ` (${t.codec})` : ""}`)
    .join(", ");
  setText("stream-tracks", trackLabels || "—");

  const bytes = stream.bytes_received ?? 0;
  const now = Date.now() / 1000;
  if (lastStreamBytes != null && lastStreamTimestamp != null && bytes >= lastStreamBytes) {
    const deltaBytes = bytes - lastStreamBytes;
    const deltaTime = now - lastStreamTimestamp;
    if (deltaTime > 0) {
      setText("stream-bitrate", formatBitrate((deltaBytes * 8) / deltaTime));
    }
  } else if (!stream.ready) {
    setText("stream-bitrate", "—");
  }
  lastStreamBytes = bytes;
  lastStreamTimestamp = now;
}

async function refreshHealth() {
  try {
    const resp = await fetch("/api/health");
    if (!resp.ok) return;
    const h = await resp.json();
    setText("stream-ready", h.stream_ready ? "Ready" : "Waiting");
    setText("capture-status", h.capture.running ? "Running" : "Stopped");
    updateStreamStats(h.stream);
    setText("disk-free", `${h.disk.free_gb} GB`);
    setText("cpu-temp", h.cpu_temp_c ?? "N/A");
    setText("sync-pending", h.sync.pending_count);
    updateRecordStatus(h.recording);

    const previewStatus = document.getElementById("preview-status");
    if (previewStatus && h.capture?.audio_enabled && h.stream_ready && !h.stream_has_audio) {
      const device = h.capture.effective_audio_device || h.capture.audio_device || "default";
      previewStatus.textContent =
        `Audio enabled but stream has no audio track — device ${device}. ` +
        "Save Settings with plughw device, or test mic with audio disabled first.";
      previewStatus.style.color = "#f88";
    } else if (previewStatus && !h.stream_ready && h.capture.last_error) {
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

function setRecordButtonsBusy(busy) {
  for (const id of ["btn-start", "btn-start-show", "btn-stop"]) {
    const btn = document.getElementById(id);
    if (btn) btn.disabled = busy;
  }
}

document.getElementById("btn-start")?.addEventListener("click", async () => {
  setRecordButtonsBusy(true);
  try {
    const data = await postForm("/api/recording/start", { show_name: showName() });
    updateRecordStatus(data);
  } catch (e) {
    alert(e.message || String(e));
  } finally {
    setRecordButtonsBusy(false);
  }
});

document.getElementById("btn-stop")?.addEventListener("click", async () => {
  setRecordButtonsBusy(true);
  try {
    const data = await postForm("/api/recording/stop");
    updateRecordStatus(data);
  } catch (e) {
    alert(e.message || String(e));
  } finally {
    setRecordButtonsBusy(false);
  }
});

document.getElementById("btn-start-show")?.addEventListener("click", async () => {
  const preset = document.getElementById("preset-select")?.value || "";
  setRecordButtonsBusy(true);
  try {
    const body = new URLSearchParams({ show_name: showName(), preset });
    const resp = await fetch("/api/start-show", {
      method: "POST",
      body,
      credentials: "same-origin",
    });
    const contentType = resp.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) {
      throw new Error("Session expired — log in again.");
    }
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Start show failed");
    updateRecordStatus(data.recording);
    alert("Show started — stream verified and recording.");
  } catch (e) {
    alert(e.message || String(e));
  } finally {
    setRecordButtonsBusy(false);
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
