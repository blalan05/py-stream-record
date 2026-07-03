from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.auth import install_session_middleware, is_authenticated, login, logout, require_auth
from app.camera import (
    apply_preset,
    delete_preset,
    get_camera_settings,
    get_editable_settings,
    list_presets,
    save_editable_settings,
    save_preset,
    update_camera_settings,
)
from app.capture import capture_manager
from app.config import get_config, reload_config
from app.recorder import recorder
from app.scheduler import add_schedule_entry, delete_schedule_entry, list_schedule, start_scheduler, stop_scheduler
from app.sync import list_recordings, sync_file, sync_pending_local, sync_status
from app.system import check_disk_guard, health_snapshot, public_whep_url, stream_ready
from app.v4l2_controls import apply_v4l2_controls, control_groups, list_v4l2_controls, set_v4l2_control
from app.watchdog import watchdog

log = logging.getLogger(__name__)

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    reload_config()
    cfg = get_config()
    Path(cfg["recording"]["local_dir"]).mkdir(parents=True, exist_ok=True)
    try:
        capture_manager.start()
    except Exception:
        log.exception("Initial capture start failed (dev machine?)")
    start_scheduler()
    watchdog.start()
    if cfg["sync"].get("mode") == "interval":
        asyncio.create_task(_sync_loop(cfg["sync"].get("interval_minutes", 30)))
    yield
    watchdog.stop()
    stop_scheduler()
    capture_manager.stop()
    if recorder.is_recording:
        recorder.stop()


async def _sync_loop(minutes: int) -> None:
    while True:
        await asyncio.sleep(max(60, minutes * 60))
        sync_pending_local()


app = FastAPI(title="Theater Stream + Record", lifespan=lifespan)
install_session_middleware(app)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


def _ctx(request: Request, **extra: Any) -> dict[str, Any]:
    cfg = get_config()
    return {
        "request": request,
        "cfg": cfg,
        "whep_url": public_whep_url(request),
        "authenticated": is_authenticated(request),
        **extra,
    }


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", _ctx(request))


@app.post("/login")
async def login_post(request: Request, pin: str = Form(...)):
    if login(request, pin):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", _ctx(request, error="Invalid PIN"))


@app.post("/logout")
async def logout_post(request: Request):
    logout(request)
    return RedirectResponse("/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if redirect := require_auth(request):
        return redirect
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        _ctx(
            request,
            health=health_snapshot(),
            presets=list_presets(),
            camera=get_camera_settings(),
            capture_source=get_config()["capture"].get("source", "csi"),
        ),
    )


@app.get("/monitor", response_class=HTMLResponse)
async def monitor(request: Request):
    cfg = get_config()
    if not cfg["app"].get("public_monitor", True) and not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request,
        "monitor.html",
        _ctx(request, capture_source=get_config()["capture"].get("source", "csi")),
    )


@app.get("/recordings", response_class=HTMLResponse)
async def recordings_page(request: Request):
    if redirect := require_auth(request):
        return redirect
    return templates.TemplateResponse(
        request,
        "recordings.html",
        _ctx(request, recordings=list_recordings(), sync=sync_status()),
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    if redirect := require_auth(request):
        return redirect
    return templates.TemplateResponse(
        request,
        "settings.html",
        _ctx(request, settings=get_editable_settings()),
    )


@app.get("/schedule", response_class=HTMLResponse)
async def schedule_page(request: Request):
    if redirect := require_auth(request):
        return redirect
    return templates.TemplateResponse(
        request,
        "schedule.html",
        _ctx(request, schedule=list_schedule()),
    )


# --- API ---


@app.get("/api/health")
async def api_health():
    return health_snapshot()


@app.post("/api/recording/start")
async def api_recording_start(request: Request, show_name: str = Form("")):
    if redirect := require_auth(request):
        return redirect
    try:
        return recorder.start(show_name or None)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/api/recording/stop")
async def api_recording_stop(request: Request):
    if redirect := require_auth(request):
        return redirect
    return recorder.stop()


@app.post("/api/start-show")
async def api_start_show(
    request: Request,
    show_name: str = Form(""),
    preset: str = Form(""),
):
    if redirect := require_auth(request):
        return redirect
    if preset:
        try:
            result = apply_preset(preset)
            if result.get("kind") == "csi":
                capture_manager.restart()
        except KeyError:
            return JSONResponse({"error": f"Unknown preset: {preset}"}, status_code=400)

    for _ in range(20):
        if stream_ready():
            break
        await asyncio.sleep(0.5)
    else:
        return JSONResponse({"error": "Stream not ready"}, status_code=503)

    guard = check_disk_guard()
    if not guard["ok"]:
        return JSONResponse({"error": guard["message"]}, status_code=400)

    try:
        status = recorder.start(show_name or None)
        return {"ok": True, "recording": status, "stream_ready": True}
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/api/capture/restart")
async def api_capture_restart(request: Request):
    if redirect := require_auth(request):
        return redirect
    capture_manager.restart()
    return capture_manager.status()


@app.post("/api/camera")
async def api_camera_update(request: Request):
    if redirect := require_auth(request):
        return redirect
    data = await request.json()
    settings = update_camera_settings(data)
    capture_manager.restart()
    return settings


@app.get("/api/camera/controls")
async def api_camera_controls(request: Request):
    if redirect := require_auth(request):
        return redirect
    info = list_v4l2_controls()
    if info.get("available"):
        info["groups"] = control_groups(info["controls"])
    info["note"] = (
        "USB/V4L2 controls from the driver. CSI Pi camera uses rpicam settings on /api/camera instead."
        if get_config()["capture"].get("source") == "usb"
        else "Pi CSI camera — use /api/camera for exposure/AWB/focus."
    )
    return info


@app.post("/api/camera/controls")
async def api_camera_controls_set(request: Request):
    if redirect := require_auth(request):
        return redirect
    data = await request.json()
    if "controls" in data and isinstance(data["controls"], dict):
        result = apply_v4l2_controls(data["controls"])
        if not result.get("ok"):
            return JSONResponse(result, status_code=400)
        return result
    name = data.get("name")
    if not name:
        return JSONResponse({"error": "name or controls required"}, status_code=400)
    result = set_v4l2_control(name, data.get("value", 0))
    if not result.get("ok"):
        return JSONResponse(result, status_code=400)
    return result


@app.get("/api/presets")
async def api_presets_list():
    return list_presets()


@app.post("/api/presets")
async def api_presets_save(request: Request):
    if redirect := require_auth(request):
        return redirect
    data = await request.json()
    return save_preset(
        data["name"],
        camera=data.get("camera"),
        v4l2=data.get("v4l2"),
    )


@app.post("/api/presets/apply")
async def api_presets_apply(request: Request):
    if redirect := require_auth(request):
        return redirect
    data = await request.json()
    result = apply_preset(data["name"])
    if result.get("kind") == "csi":
        capture_manager.restart()
    return result


@app.delete("/api/presets/{name}")
async def api_presets_delete(name: str, request: Request):
    if redirect := require_auth(request):
        return redirect
    return delete_preset(name)


@app.post("/api/settings")
async def api_settings_save(request: Request):
    if redirect := require_auth(request):
        return redirect
    data = await request.json()
    saved = save_editable_settings(data)
    capture_manager.restart()
    return saved


@app.get("/api/recordings")
async def api_recordings():
    return list_recordings()


@app.get("/api/recordings/download")
async def api_recordings_download(path: str, request: Request):
    if redirect := require_auth(request):
        return redirect
    file_path = Path(path)
    cfg = get_config()
    local_root = Path(cfg["recording"]["local_dir"]).resolve()
    resolved = file_path.resolve()
    if local_root not in resolved.parents and resolved != local_root:
        return JSONResponse({"error": "Invalid path"}, status_code=400)
    if not resolved.exists():
        return JSONResponse({"error": "Not found"}, status_code=404)
    return FileResponse(resolved, filename=resolved.name)


@app.post("/api/sync/run")
async def api_sync_run(request: Request):
    if redirect := require_auth(request):
        return redirect
    return sync_pending_local()


@app.post("/api/sync/file")
async def api_sync_file(request: Request, path: str = Form(...)):
    if redirect := require_auth(request):
        return redirect
    return sync_file(path)


@app.get("/api/schedule")
async def api_schedule_list():
    return list_schedule()


@app.post("/api/schedule")
async def api_schedule_add(
    request: Request,
    show_name: str = Form(...),
    start_at: str = Form(...),
    stop_at: str = Form(...),
):
    if redirect := require_auth(request):
        return redirect
    return add_schedule_entry(show_name, start_at, stop_at)


@app.delete("/api/schedule/{entry_id}")
async def api_schedule_delete(entry_id: str, request: Request):
    if redirect := require_auth(request):
        return redirect
    return delete_schedule_entry(entry_id)


@app.get("/api/watchdog/events")
async def api_watchdog_events(request: Request):
    if redirect := require_auth(request):
        return redirect
    return watchdog.recent_events()
