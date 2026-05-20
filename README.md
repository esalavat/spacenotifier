# SpaceNotifier

A tiny self-hosted service that pings your phone 15 minutes before any SpaceX
launch from Vandenberg. Free end-to-end: data from
[Launch Library 2](https://thespacedevs.com/) (no API key) and push delivered
via the public [ntfy.sh](https://ntfy.sh/) server.

## How it works

1. A background scheduler polls Launch Library 2 every 15 minutes for upcoming
   SpaceX launches and keeps the Vandenberg ones in a small SQLite file.
2. Each known launch gets a one-shot timer for `T-0 minus lead_minutes`. When
   the timer fires, the service POSTs a notification to
   `https://ntfy.sh/<your-topic>`.
3. Anyone subscribed to that topic (via the ntfy phone app, web, or another
   subscriber) gets the push, even when off-network.

The web UI on `/` is the only configuration surface.

## Quick start (local)

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
SPACENOTIFIER_DB=./data/spacenotifier.db \
  uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000/>, set an ntfy topic, click "Send test
notification."

## Deploy to Proxmox

1. Create a small Debian 12 LXC (1 vCPU, 512 MB RAM, 4 GB disk is plenty).
2. Install Docker and the compose plugin.
3. Clone this repo and run:

   ```sh
   docker compose up -d --build
   ```

4. Browse to `http://<lxc-ip>/` (the compose file publishes host port **80**).
5. Pick a long random ntfy topic name, save settings.
6. On your phone: install the [ntfy app](https://ntfy.sh/), tap "+ Subscribe to
   topic," paste the same topic name.
7. Hit "Send test notification" in the web UI — you should see the push within
   seconds.

The `./data` directory holds the SQLite DB and persists across container
rebuilds. Back it up if you care about your settings.

### Security

No auth on the web UI. Keep the container on a trusted subnet and pick a long,
random ntfy topic name (anyone who knows the topic can send notifications to
your phone).

## Project layout

```
app/
  main.py          FastAPI app, lifespan, routes
  poller.py        LL2 fetch, filter, schedule
  notifier.py      ntfy POST + mark-notified
  db.py            SQLite schema and helpers
  config.py        DB-backed settings
  templates/
    settings.html  Single-page UI
Dockerfile
docker-compose.yml
requirements.txt
```

## Endpoints

- `GET  /`              — settings page
- `POST /settings`      — save settings
- `POST /test`          — send a test push to the current topic
- `POST /admin/poll`    — force an immediate poll of LL2
- `GET  /admin/jobs`    — JSON list of scheduled jobs (debugging)
- `GET  /healthz`       — liveness check
