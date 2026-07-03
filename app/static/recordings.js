let clipStart = null;
let clipEnd = null;
let currentPlayPath = null;

const modal = document.getElementById("player-modal");
const playerVideo = document.getElementById("player-video");

function formatTime(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function openPlayer(path, name) {
  currentPlayPath = path;
  clipStart = null;
  clipEnd = null;
  document.getElementById("clip-start").textContent = "—";
  document.getElementById("clip-end").textContent = "—";
  document.getElementById("clip-name").value = "";
  document.getElementById("clip-msg").textContent = "";
  document.getElementById("player-title").textContent = name || "Recording";
  playerVideo.src = `/api/recordings/play?path=${encodeURIComponent(path)}`;
  modal?.classList.add("open");
}

function closePlayer() {
  modal?.classList.remove("open");
  if (playerVideo) {
    playerVideo.pause();
    playerVideo.removeAttribute("src");
    playerVideo.load();
  }
  currentPlayPath = null;
}

document.getElementById("btn-close-player")?.addEventListener("click", closePlayer);
modal?.addEventListener("click", (ev) => {
  if (ev.target === modal) closePlayer();
});

document.querySelectorAll(".play-one").forEach((btn) => {
  btn.addEventListener("click", () => {
    openPlayer(btn.dataset.path, btn.dataset.name);
  });
});

document.getElementById("btn-clip-start")?.addEventListener("click", () => {
  clipStart = playerVideo?.currentTime ?? 0;
  document.getElementById("clip-start").textContent = formatTime(clipStart);
});

document.getElementById("btn-clip-end")?.addEventListener("click", () => {
  clipEnd = playerVideo?.currentTime ?? 0;
  document.getElementById("clip-end").textContent = formatTime(clipEnd);
});

document.getElementById("btn-create-clip")?.addEventListener("click", async () => {
  const msg = document.getElementById("clip-msg");
  const name = document.getElementById("clip-name")?.value?.trim();
  if (!currentPlayPath) return;
  if (clipStart == null || clipEnd == null) {
    if (msg) msg.textContent = "Set start and end times first.";
    return;
  }
  if (!name) {
    if (msg) msg.textContent = "Enter a clip name.";
    return;
  }
  try {
    const resp = await fetch("/api/recordings/clip", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        path: currentPlayPath,
        start_s: clipStart,
        end_s: clipEnd,
        name,
      }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Clip failed");
    if (msg) msg.textContent = `Created ${data.name}`;
    location.reload();
  } catch (err) {
    if (msg) msg.textContent = String(err.message || err);
  }
});

document.querySelectorAll(".delete-clip").forEach((btn) => {
  btn.addEventListener("click", async () => {
    if (!confirm("Delete this clip?")) return;
    const resp = await fetch(`/api/recordings/clip?path=${encodeURIComponent(btn.dataset.path)}`, {
      method: "DELETE",
    });
    if (resp.ok) location.reload();
  });
});

document.getElementById("btn-sync-all")?.addEventListener("click", async () => {
  const resp = await fetch("/api/sync/run", { method: "POST" });
  const data = await resp.json();
  alert(`Sync finished (${data.length} files processed)`);
  location.reload();
});

document.querySelectorAll(".sync-one").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const path = btn.dataset.path;
    const body = new URLSearchParams({ path });
    await fetch("/api/sync/file", { method: "POST", body });
    location.reload();
  });
});
