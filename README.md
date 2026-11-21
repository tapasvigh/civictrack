# Civic Track

Civic Track is a student, work, and day to day-friendly app for keeping community-service, school commitments, assignments, and any tasks organized. It brings volunteer-hour logging, assignments, goals, calendars, and progress reports together in one responsive interface.

## What the application does

- Records volunteer activities, hours, dates, locations, advisor details, optional photos, and school or organization affiliations.
- Tracks service-hour goals, progress, and milestone badges.
- Organizes assignments with due dates, completion status, and optional study reminders.
- Shows volunteer and assignment activity on a calendar, dashboard, and printable reports or resume draft.
- Provides a profile, appearance preferences, and browser reminders.
- Works as a responsive website and installable Progressive Web App (PWA), with an offline-cached app shell.

### Technology

- Python and Flask power the web server and JSON API.
- SQLite stores the account, preferences, and activity in `data/civic_track.db`.
- HTML, CSS, and vanilla JavaScript provide the browser interface.
- Gunicorn serves the application in the Docker Compose deployment.

### Current scope and privacy

Civic Track currently supports one account and one shared local database. Anyone who can access the same server uses that account and sees the same records; separate user accounts and cloud synchronization are not implemented.

Email and text verification codes are shown in the app rather than delivered. Browser reminders work only while the app is open and permission has been granted. Saved profile photos and signatures are stored in the local database without encryption. Reports and resumes use user-entered information that is not independently verified, and the community-value estimate is illustrative. Use fictional information and do not store sensitive personal details.

## Deployment

### Run with Docker Compose

1. Install Docker Desktop and make sure its engine is running.
2. From this folder, run:

   ```sh
   docker compose up --build -d
   ```

3. Open [http://localhost:5000](http://localhost:5000).
4. Stop the service with:

   ```sh
   docker compose down
   ```

The Compose file publishes port `5000` on the host by default. To use another host port, set `CIVIC_TRACK_PORT` before starting Compose; for example, in PowerShell:

```powershell
$env:CIVIC_TRACK_PORT = "8080"
docker compose up --build -d
```

The `./data:/app/data` volume keeps the SQLite database and session-signing key on the host across container restarts. The app creates the `data` folder and key when first started.

### Run directly with Python

1. Install Python 3.10 or newer.
2. Install dependencies:

   ```sh
   py -m pip install -r requirements.txt
   ```

3. Start the server:

   ```sh
   py app.py
   ```

4. Open [http://127.0.0.1:5000](http://127.0.0.1:5000).

The app stores its SQLite database and persistent session-signing key in `data/`.

### Access from another computer on the same Wi-Fi

Run Civic Track on the host computer, then find its IPv4 address with `ipconfig`. From another computer on the same trusted network, open `http://<host-ip>:5000` (for example, `http://192.168.1.25:5000`). If the host firewall blocks the connection, allow access only from the trusted local network. Do not configure router port forwarding.

All visitors share the same account and data. A local-network connection over HTTP is for testing and does not provide production-grade security.

### Install on desktop or mobile

The PWA can be installed from supported desktop and Android browsers. On iPhone or iPad, open the site in Safari and choose **Share → Add to Home Screen**. Service workers and installation require HTTPS, except when testing at `localhost`; a plain HTTP LAN address does not provide the secure context needed for installation. The app shell can reopen offline, but account and data actions require the server and a network connection.

### Public hosting

The included Flask/Gunicorn setup is intended for local development and trusted-network testing, not direct public deployment. The app has a single shared account and stores personal information without database encryption. Public hosting requires a production security and privacy design, HTTPS, and proper account isolation. Do not expose port `5000` directly to the public internet.

## Tests

Run the backend workflow tests with:

```sh
py -m unittest discover -s tests -v
```
