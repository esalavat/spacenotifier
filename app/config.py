from app import db

DEFAULTS = {
    "ntfy_topic": "",
    "lead_minutes": "15",
    "poll_minutes": "15",
    "enabled": "1",
}


def get(key: str) -> str:
    return db.get_setting(key, DEFAULTS.get(key, "")) or ""


def set_(key: str, value: str) -> None:
    db.set_setting(key, value)


def lead_minutes() -> int:
    try:
        return max(1, int(get("lead_minutes")))
    except ValueError:
        return 15


def poll_minutes() -> int:
    try:
        return max(1, int(get("poll_minutes")))
    except ValueError:
        return 15


def enabled() -> bool:
    return get("enabled") == "1"


def ntfy_topic() -> str:
    return get("ntfy_topic").strip()
