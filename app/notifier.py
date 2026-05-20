import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from app import config, db

log = logging.getLogger(__name__)

NTFY_BASE = "https://ntfy.sh"
LOCAL_TZ = ZoneInfo("America/Los_Angeles")


def _post(topic: str, title: str, body: str, tags: str = "rocket", priority: str = "high") -> None:
    url = f"{NTFY_BASE}/{topic}"
    headers = {
        "Title": title,
        "Tags": tags,
        "Priority": priority,
    }
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(url, content=body.encode("utf-8"), headers=headers)
        resp.raise_for_status()


def send_test() -> None:
    topic = config.ntfy_topic()
    if not topic:
        raise ValueError("ntfy topic is not configured")
    _post(
        topic,
        title="SpaceNotifier test",
        body="If you can read this, your ntfy subscription is working.",
        tags="white_check_mark",
        priority="default",
    )


def notify_launch(launch_id: str, name: str, net_utc: str) -> None:
    if not config.enabled():
        log.info("notifications disabled, skipping launch %s", launch_id)
        return
    topic = config.ntfy_topic()
    if not topic:
        log.warning("no ntfy topic set; cannot notify launch %s", launch_id)
        return
    try:
        net_dt = datetime.fromisoformat(net_utc.replace("Z", "+00:00"))
        local = net_dt.astimezone(LOCAL_TZ).strftime("%-I:%M %p %Z")
        utc = net_dt.strftime("%H:%M UTC")
    except Exception:
        local = net_utc
        utc = net_utc
    lead = config.lead_minutes()
    try:
        _post(
            topic,
            title=f"SpaceX Vandenberg — T-{lead} min",
            body=f"{name} lifts off at {local} ({utc})",
        )
        db.mark_notified(launch_id)
        log.info("notified launch %s (%s)", launch_id, name)
    except Exception:
        log.exception("failed to notify launch %s", launch_id)
