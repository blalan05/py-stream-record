async function connectWhep(videoId, whepUrl) {
  const video = document.getElementById(videoId || "preview");
  if (!video || !whepUrl) return;

  const pc = new RTCPeerConnection({
    iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
  });

  pc.addTransceiver("video", { direction: "recvonly" });
  pc.addTransceiver("audio", { direction: "recvonly" });

  pc.ontrack = (ev) => {
    if (!video.srcObject) {
      video.srcObject = ev.streams[0];
    }
  };

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);

  const resp = await fetch(whepUrl, {
    method: "POST",
    headers: { "Content-Type": "application/sdp" },
    body: offer.sdp,
  });

  if (!resp.ok) {
    console.error("WHEP failed", resp.status, await resp.text());
    return;
  }

  const answer = await resp.text();
  await pc.setRemoteDescription({ type: "answer", sdp: answer });
  return pc;
}

document.addEventListener("DOMContentLoaded", () => {
  const url = window.THEATER_WHEP_URL;
  const vid = window.THEATER_VIDEO_ID || "preview";
  if (url) {
    connectWhep(vid, url).catch((err) => console.error("WebRTC connect error", err));
  }
});
