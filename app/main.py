import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app import config, db, notifier, poller

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("spacenotifier")

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
POLL_JOB_ID = "poller"

scheduler = BackgroundScheduler(timezone="UTC")


def _install_poll_job() -> None:
    interval = config.poll_minutes()
    scheduler.add_job(
        poller.poll_and_schedule,
        trigger=IntervalTrigger(minutes=interval),
        id=POLL_JOB_ID,
        replace_existing=True,
        args=[scheduler],
        misfire_grace_time=300,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    scheduler.start()
    _install_poll_job()
    # Immediate poll on startup so the UI has data right away.
    try:
        poller.poll_and_schedule(scheduler)
    except Exception:
        log.exception("initial poll failed")
    log.info("spacenotifier started")
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)


def _render(request: Request, flash: str | None = None, flash_kind: str = "ok"):
    return TEMPLATES.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "ntfy_topic": config.ntfy_topic(),
            "lead_minutes": config.lead_minutes(),
            "poll_minutes": config.poll_minutes(),
            "enabled": config.enabled(),
            "launches": db.list_launches(),
            "now_utc": datetime.now(timezone.utc).isoformat(),
            "flash": flash,
            "flash_kind": flash_kind,
        },
    )


@app.get("/")
def index(request: Request):
    return _render(request)


@app.post("/settings")
def save_settings(
    request: Request,
    ntfy_topic: str = Form(""),
    lead_minutes: int = Form(15),
    poll_minutes: int = Form(15),
    enabled: str = Form(None),
):
    old_poll = config.poll_minutes()
    config.set_("ntfy_topic", ntfy_topic.strip())
    config.set_("lead_minutes", str(max(1, min(240, lead_minutes))))
    config.set_("poll_minutes", str(max(1, min(120, poll_minutes))))
    config.set_("enabled", "1" if enabled == "1" else "0")
    if config.poll_minutes() != old_poll:
        _install_poll_job()
    return RedirectResponse(url="/", status_code=303)


@app.post("/test")
def send_test(request: Request):
    try:
        notifier.send_test()
        return _render(request, flash="Test notification sent.", flash_kind="ok")
    except Exception as exc:
        log.exception("test notification failed")
        return _render(request, flash=f"Test failed: {exc}", flash_kind="err")


@app.post("/admin/poll")
def admin_poll(request: Request):
    try:
        n = poller.poll_and_schedule(scheduler)
        return _render(request, flash=f"Polled. {n} launch(es) scheduled.", flash_kind="ok")
    except Exception as exc:
        log.exception("manual poll failed")
        return _render(request, flash=f"Poll failed: {exc}", flash_kind="err")


@app.post("/admin/cleanup")
def admin_cleanup(request: Request):
    try:
        n = db.delete_past_launches()
        return _render(request, flash=f"Removed {n} past launch row(s).", flash_kind="ok")
    except Exception as exc:
        log.exception("cleanup failed")
        return _render(request, flash=f"Cleanup failed: {exc}", flash_kind="err")


@app.get("/admin/jobs")
def admin_jobs():
    return {
        "jobs": [
            {
                "id": j.id,
                "next_run_time": j.next_run_time.isoformat() if j.next_run_time else None,
                "trigger": str(j.trigger),
            }
            for j in scheduler.get_jobs()
        ]
    }


@app.get("/healthz")
def healthz():
    return {"ok": True}
