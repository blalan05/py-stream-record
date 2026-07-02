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

document.getElementById("settings-form")?.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target;
  const payload = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === "checkbox") {
      setNested(payload, el.name, el.checked);
    } else if (el.type !== "submit") {
      setNested(payload, el.name, el.value);
    }
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
    msg.textContent = "Save failed.";
  }
});
