function setNested(obj, path, value) {
  const parts = path.split(".");
  let cur = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    cur[parts[i]] = cur[parts[i]] || {};
    cur = cur[parts[i]];
  }
  const key = parts[parts.length - 1];
  if (typeof value === "boolean") {
    cur[key] = value;
  } else if (value === "true" || value === "false") {
    cur[key] = value === "true";
  } else if (!Number.isNaN(Number(value)) && value !== "") {
    cur[key] = Number(value);
  } else {
    cur[key] = value;
  }
}

let videoDevices = [];
let audioDevices = [];

function option(value, label, selected) {
  const opt = document.createElement("option");
  opt.value = value;
  opt.textContent = label;
  if (selected) opt.selected = true;
  return opt;
}

function currentVideoDevice() {
  const select = document.getElementById("video-device-select");
  const custom = document.getElementById("video-device-custom");
  if (select?.value === "__custom__") {
    return custom?.value?.trim() || "/dev/video0";
  }
  return select?.value || custom?.value?.trim() || "/dev/video0";
}

function findVideoDevice(path) {
  return videoDevices.find((d) => d.device === path);
}

function populateFormatOptions(devicePath, selectedFormat) {
  const formatSelect = document.getElementById("video-format-select");
  if (!formatSelect) return;
  formatSelect.innerHTML = "";
  formatSelect.appendChild(option("", "Auto-detect", !selectedFormat));

  const dev = findVideoDevice(devicePath);
  if (!dev) return;

  for (const fmt of dev.formats) {
    formatSelect.appendChild(option(fmt.format, fmt.format.toUpperCase(), fmt.format === selectedFormat));
  }
}

function populateResolutionOptions(devicePath, selectedFormat, selectedWidth, selectedHeight) {
  const resSelect = document.getElementById("video-resolution-select");
  if (!resSelect) return;
  resSelect.innerHTML = "";
  resSelect.appendChild(option("", "Custom (use width/height fields)", false));

  const dev = findVideoDevice(devicePath);
  const fmt = dev?.formats.find((f) => f.format === selectedFormat);
  if (!fmt) return;

  for (const res of fmt.resolutions) {
    const value = `${res.width}x${res.height}`;
    const selected = res.width === Number(selectedWidth) && res.height === Number(selectedHeight);
    resSelect.appendChild(option(value, value, selected));
  }
}

function populateFpsOptions(devicePath, selectedFormat, selectedWidth, selectedHeight, selectedFps) {
  const fpsSelect = document.getElementById("video-fps-select");
  if (!fpsSelect) return;
  fpsSelect.innerHTML = "";
  fpsSelect.appendChild(option("", "Custom (use FPS field)", false));

  const dev = findVideoDevice(devicePath);
  const fmt = dev?.formats.find((f) => f.format === selectedFormat);
  const res = fmt?.resolutions.find(
    (r) => r.width === Number(selectedWidth) && r.height === Number(selectedHeight)
  );
  if (!res) return;

  for (const fps of res.fps) {
    fpsSelect.appendChild(option(String(fps), `${fps} fps`, Number(fps) === Number(selectedFps)));
  }
}

function syncVideoModeDropdowns() {
  const devicePath = currentVideoDevice();
  const formatSelect = document.getElementById("video-format-select");
  const resSelect = document.getElementById("video-resolution-select");
  const fpsSelect = document.getElementById("video-fps-select");
  const widthInput = document.querySelector('input[name="capture.width"]');
  const heightInput = document.querySelector('input[name="capture.height"]');
  const fpsInput = document.querySelector('input[name="capture.fps"]');
  const formatInput = document.querySelector('input[name="capture.video_format"]');

  const selectedFormat = formatSelect?.value || formatInput?.value || "";
  const selectedWidth = widthInput?.value;
  const selectedHeight = heightInput?.value;
  const selectedFps = fpsInput?.value;

  populateFormatOptions(devicePath, selectedFormat);
  populateResolutionOptions(devicePath, selectedFormat, selectedWidth, selectedHeight);
  populateFpsOptions(devicePath, selectedFormat, selectedWidth, selectedHeight, selectedFps);
}

function applyResolutionSelection(value) {
  const widthInput = document.querySelector('input[name="capture.width"]');
  const heightInput = document.querySelector('input[name="capture.height"]');
  if (!value || !widthInput || !heightInput) return;
  const [w, h] = value.split("x").map(Number);
  if (w && h) {
    widthInput.value = w;
    heightInput.value = h;
    syncVideoModeDropdowns();
  }
}

function applyFpsSelection(value) {
  const fpsInput = document.querySelector('input[name="capture.fps"]');
  if (!value || !fpsInput) return;
  fpsInput.value = value;
}

function applyFormatSelection(value) {
  const formatInput = document.querySelector('input[name="capture.video_format"]');
  if (formatInput) formatInput.value = value;
  syncVideoModeDropdowns();
}

async function readJson(resp) {
  const contentType = resp.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    const text = await resp.text();
    throw new Error(text.slice(0, 120) || `HTTP ${resp.status}`);
  }
  return resp.json();
}

async function loadDeviceLists() {
  const msg = document.getElementById("settings-msg");
  try {
    const [videoResp, audioResp] = await Promise.all([
      fetch("/api/devices/video", { credentials: "same-origin" }),
      fetch("/api/devices/audio", { credentials: "same-origin" }),
    ]);
    const videoData = await readJson(videoResp);
    const audioData = await readJson(audioResp);

    videoDevices = videoData.devices || [];
    audioDevices = audioData.devices || [{ alsa: "default", name: "System default" }];

    const customInput = document.getElementById("video-device-custom");
    const currentVideo = customInput?.value?.trim() || "/dev/video0";

    if (!videoDevices.length && currentVideo) {
      try {
        const probeResp = await fetch(
          `/api/devices/video/probe?device=${encodeURIComponent(currentVideo)}`,
          { credentials: "same-origin" }
        );
        const probeData = await readJson(probeResp);
        if (probeData.device) {
          videoDevices = [probeData.device];
        }
      } catch {
        // keep empty list; user can still type a custom path
      }
    }

    const videoSelect = document.getElementById("video-device-select");
    const audioSelect = document.getElementById("audio-device-select");
    const customInput = document.getElementById("video-device-custom");
    const currentVideo = customInput?.value?.trim() || "/dev/video0";
    const currentAudio = document.querySelector('input[name="capture.audio_device"]')?.value || "default";

    if (videoSelect) {
      videoSelect.innerHTML = "";
      for (const dev of videoDevices) {
        videoSelect.appendChild(
          option(dev.device, `${dev.name} (${dev.device})`, dev.device === currentVideo)
        );
      }
      videoSelect.appendChild(option("__custom__", "Custom path…", !findVideoDevice(currentVideo)));
      if (findVideoDevice(currentVideo)) {
        videoSelect.value = currentVideo;
      } else {
        videoSelect.value = "__custom__";
      }
    }

    if (audioSelect) {
      audioSelect.innerHTML = "";
      for (const dev of audioDevices) {
        audioSelect.appendChild(option(dev.alsa, dev.name, dev.alsa === currentAudio));
      }
      if (!audioDevices.some((d) => d.alsa === currentAudio)) {
        audioSelect.appendChild(option(currentAudio, `${currentAudio} (custom)`, true));
      }
      audioSelect.value = currentAudio;
    }

    syncVideoModeDropdowns();
    const errors = [videoData.error, audioData.error].filter(Boolean);
    if (msg) {
      msg.textContent = errors.length
        ? `Scan partial: ${errors.join("; ")}`
        : `Found ${videoDevices.length} camera(s), ${audioDevices.length} audio device(s).`;
    }
  } catch (err) {
    if (msg) msg.textContent = `Device scan failed: ${err.message || err}`;
    syncVideoModeDropdowns();
  }
}

document.getElementById("btn-rescan-devices")?.addEventListener("click", loadDeviceLists);

document.getElementById("video-device-select")?.addEventListener("change", (ev) => {
  const custom = document.getElementById("video-device-custom");
  const isCustom = ev.target.value === "__custom__";
  if (custom) {
    custom.style.display = isCustom ? "block" : "none";
    if (!isCustom) custom.value = ev.target.value;
  }
  syncVideoModeDropdowns();
});

document.getElementById("video-format-select")?.addEventListener("change", (ev) => {
  applyFormatSelection(ev.target.value);
});

document.getElementById("video-resolution-select")?.addEventListener("change", (ev) => {
  applyResolutionSelection(ev.target.value);
});

document.getElementById("video-fps-select")?.addEventListener("change", (ev) => {
  applyFpsSelection(ev.target.value);
});

document.getElementById("audio-device-select")?.addEventListener("change", (ev) => {
  const input = document.querySelector('input[name="capture.audio_device"]');
  if (input) input.value = ev.target.value;
});

document.getElementById("btn-test-mic")?.addEventListener("click", async () => {
  const msg = document.getElementById("audio-test-msg");
  const device = document.getElementById("audio-device-select")?.value
    || document.querySelector('input[name="capture.audio_device"]')?.value
    || "default";
  if (msg) msg.textContent = "Testing mic (2s)…";
  try {
    const resp = await fetch("/api/devices/audio/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ device }),
    });
    const data = await readJson(resp);
    if (!resp.ok || !data.ok) {
      throw new Error(data.error || "Mic test failed");
    }
    if (msg) {
      msg.textContent = `${data.message} (mean ${data.mean_volume_db ?? "?"} dB, max ${data.max_volume_db ?? "?"} dB)`;
    }
  } catch (err) {
    if (msg) msg.textContent = String(err.message || err);
  }
});

document.getElementById("settings-form")?.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target;
  const payload = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === "checkbox") {
      setNested(payload, el.name, el.checked);
    } else if (el.type !== "submit" && el.type !== "button") {
      setNested(payload, el.name, el.value);
    }
  }

  const videoSelect = document.getElementById("video-device-select");
  if (videoSelect) {
    const device = currentVideoDevice();
    payload.capture = payload.capture || {};
    payload.capture.video_device = device;
  }

  const formatSelect = document.getElementById("video-format-select");
  if (formatSelect) {
    payload.capture = payload.capture || {};
    payload.capture.video_format = formatSelect.value;
  }

  const audioSelect = document.getElementById("audio-device-select");
  if (audioSelect?.value) {
    payload.capture = payload.capture || {};
    payload.capture.audio_device = audioSelect.value;
  }

  const resp = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const msg = document.getElementById("settings-msg");
  if (resp.ok) {
    msg.textContent = "Saved. Capture restarted with new settings.";
  } else {
    const data = await resp.json().catch(() => ({}));
    msg.textContent = data.error || "Save failed.";
  }
});

document.addEventListener("DOMContentLoaded", loadDeviceLists);
