let audioMeterCtx = null;
let audioAnalyser = null;
let audioMeterRaf = null;
let audioPeak = 0;

function initAudioMeter(stream) {
  stopAudioMeter();
  const audioTracks = stream.getAudioTracks();
  const status = document.getElementById("audio-meter-status");
  if (!audioTracks.length) {
    if (status) status.textContent = "Waiting for audio track…";
    return;
  }

  try {
    const audioCtx = new AudioContext();
    const source = audioCtx.createMediaStreamSource(stream);
    audioAnalyser = audioCtx.createAnalyser();
    audioAnalyser.fftSize = 256;
    source.connect(audioAnalyser);
    audioMeterCtx = audioCtx;
    if (status) status.textContent = "Live";
    tickAudioMeter();
  } catch (err) {
    if (status) status.textContent = "Audio meter unavailable";
    console.warn("Audio meter init failed", err);
  }
}

function stopAudioMeter() {
  if (audioMeterRaf) {
    cancelAnimationFrame(audioMeterRaf);
    audioMeterRaf = null;
  }
  if (audioMeterCtx) {
    audioMeterCtx.close().catch(() => {});
    audioMeterCtx = null;
  }
  audioAnalyser = null;
  audioPeak = 0;
}

function tickAudioMeter() {
  if (!audioAnalyser) return;
  const data = new Uint8Array(audioAnalyser.frequencyBinCount);
  audioAnalyser.getByteFrequencyData(data);
  let sum = 0;
  for (let i = 0; i < data.length; i++) sum += data[i];
  const level = sum / (data.length * 255);
  const pct = Math.min(100, Math.round(level * 140));
  audioPeak = Math.max(audioPeak * 0.96, pct);

  const bar = document.getElementById("audio-meter-level");
  const peak = document.getElementById("audio-meter-peak");
  if (bar) bar.style.width = `${pct}%`;
  if (peak) peak.style.width = `${audioPeak}%`;

  audioMeterRaf = requestAnimationFrame(tickAudioMeter);
}

async function connectWhep(videoId, whepUrl) {
  const video = document.getElementById(videoId || "preview");
  if (!video || !whepUrl) return null;

  const pc = new RTCPeerConnection({
    iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
  });

  pc.addTransceiver("video", { direction: "recvonly" });
  pc.addTransceiver("audio", { direction: "recvonly" });

  const previewStream = new MediaStream();

  function syncPreview() {
    video.srcObject = previewStream;
    initAudioMeter(previewStream);
    video.play?.().catch(() => {});
  }

  let gotVideo = false;
  const trackPromise = new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      if (!gotVideo) {
        reject(new Error("Connected but no video track yet (is capture publishing?)"));
      }
    }, 8000);

    pc.ontrack = (ev) => {
      const track = ev.track;
      if (!previewStream.getTracks().some((t) => t.id === track.id)) {
        previewStream.addTrack(track);
      }
      syncPreview();

      if (track.kind === "video") {
        gotVideo = true;
        window.clearTimeout(timer);
        resolve();
      }
    };
  });

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);

  const resp = await fetch(whepUrl, {
    method: "POST",
    headers: { "Content-Type": "application/sdp" },
    body: offer.sdp,
  });

  if (!resp.ok) {
    const detail = await resp.text();
    pc.close();
    throw new Error(`WHEP ${resp.status}: ${detail || resp.statusText}`);
  }

  const answer = await resp.text();
  await pc.setRemoteDescription({ type: "answer", sdp: answer });
  await trackPromise;
  return pc;
}

function setPreviewStatus(message, isError = false) {
  const el = document.getElementById("preview-status");
  if (el) {
    el.textContent = message || "";
    el.style.color = isError ? "#f88" : "";
  }
}

async function startPreview() {
  const url = window.THEATER_WHEP_URL;
  const vid = window.THEATER_VIDEO_ID || "preview";
  if (!url) {
    setPreviewStatus("No WebRTC URL configured", true);
    return;
  }

  setPreviewStatus(`Connecting to ${url}…`);

  try {
    await connectWhep(vid, url);
    setPreviewStatus("");
  } catch (err) {
    console.error("WebRTC connect error", err);
    setPreviewStatus(String(err.message || err), true);
    stopAudioMeter();
    const status = document.getElementById("audio-meter-status");
    if (status) status.textContent = "No audio track";
    window.setTimeout(startPreview, 5000);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  startPreview();
});
