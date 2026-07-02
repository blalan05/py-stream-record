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
