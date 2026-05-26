import logging
from datetime import datetime, timedelta, timezone

import httpx
from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.date import DateTrigger

from app import config, db, notifier

log = logging.getLogger(__name__)

LL2_URL = "https://ll.thespacedevs.com/2.2.0/launch/upcoming/"
LL2_PARAMS = {
    "search": "SpaceX",
    "limit": 20,
}

JOB_PREFIX = "launch:"


def _is_vandenberg(pad_location_name: str | None) -> bool:
    return bool(pad_location_name) and "vandenberg" in pad_location_name.lower()


def _is_spacex(lsp_name: str | None) -> bool:
    return bool(lsp_name) and "spacex" in lsp_name.lower()


def fetch_upcoming() -> list[dict]:
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(LL2_URL, params=LL2_PARAMS)
        resp.raise_for_status()
        data = resp.json()
    return data.get("results", [])


def poll_and_schedule(scheduler: BaseScheduler) -> int:
    """Fetch upcoming launches, upsert into DB, (re)schedule notifications.

    Returns the number of launches that ended up scheduled.
    """
    try:
        results = fetch_upcoming()
    except Exception:
        log.exception("LL2 fetch failed")
        return 0

    relevant = []
    for launch in results:
        lsp = (launch.get("launch_service_provider") or {}).get("name")
        pad = launch.get("pad") or {}
        loc_name = (pad.get("location") or {}).get("name")
        if _is_spacex(lsp) and _is_vandenberg(loc_name):
            relevant.append(launch)

    log.info("LL2 returned %d launches, %d matched Vandenberg+SpaceX",
             len(results), len(relevant))

    scheduled = 0
    for launch in relevant:
        launch_id = launch["id"]
        name = launch.get("name") or "Unknown mission"
        net = launch.get("net")
        status = (launch.get("status") or {}).get("name")
        if not net:
            continue
        db.upsert_launch(launch_id, name, net, status)
        if _schedule_one(scheduler, launch_id, name, net):
            scheduled += 1
    return scheduled


def _schedule_one(scheduler: BaseScheduler, launch_id: str, name: str, net_utc: str) -> bool:
    job_id = f"{JOB_PREFIX}{launch_id}"
    lead = config.lead_minutes()
    try:
        net_dt = datetime.fromisoformat(net_utc.replace("Z", "+00:00"))
    except ValueError:
        log.warning("could not parse net %r for launch %s", net_utc, launch_id)
        return False

    now = datetime.now(timezone.utc)
    fire_at = net_dt - timedelta(minutes=lead)
    if fire_at <= now:
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
        # Catch-up: T-lead has passed but T-0 hasn't, and we haven't notified yet.
        # Covers the case where LL2 publishes a tight NET inside the lead window
        # or flickers to a NET that nukes the existing schedule.
        if now < net_dt and not db.is_notified(launch_id):
            log.info("catch-up notify %s (T-%dmin was %s, net %s)",
                     launch_id, lead, fire_at.isoformat(), net_utc)
            notifier.notify_launch(launch_id, name, net_utc)
        return False

    scheduler.add_job(
        notifier.notify_launch,
        trigger=DateTrigger(run_date=fire_at),
        id=job_id,
        replace_existing=True,
        args=[launch_id, name, net_utc],
        misfire_grace_time=300,
    )
    log.info("scheduled %s for %s (T-%d min before %s)",
             job_id, fire_at.isoformat(), lead, net_utc)
    return True
