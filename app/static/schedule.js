document.getElementById("schedule-form")?.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const body = new URLSearchParams(fd);
  const resp = await fetch("/api/schedule", { method: "POST", body });
  if (!resp.ok) {
    alert("Failed to add schedule entry");
    return;
  }
  location.reload();
});

document.querySelectorAll(".delete-sched").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const id = btn.dataset.id;
    await fetch(`/api/schedule/${id}`, { method: "DELETE" });
    location.reload();
  });
});
