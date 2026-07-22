async function connectWhep(videoId, whepUrl) {
  const video = document.getElementById(videoId || "preview");
  if (!video || !whepUrl) return null;

  const pc = new RTCPeerConnection({
    iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
  });

  pc.addTransceiver("video", { direction: "recvonly" });

  const previewStream = new MediaStream();

  function syncPreview() {
    video.srcObject = previewStream;
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
      if (track.kind !== "video") return;
      if (!previewStream.getTracks().some((t) => t.id === track.id)) {
        previewStream.addTrack(track);
      }
      syncPreview();
      gotVideo = true;
      window.clearTimeout(timer);
      resolve();
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
    window.setTimeout(startPreview, 5000);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  startPreview();
});
