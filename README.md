# Civic Track

A beginner-friendly community-service and assignment tracker built with Python, Flask, SQLite, HTML, CSS, and browser JavaScript.

## Run locally

1. Install Python 3.10 or newer.
2. From this folder, install Flask: `py -m pip install -r requirements.txt`
3. Start the app: `py app.py`
4. Open `http://127.0.0.1:5000` in your browser and create a demo account.

The app creates `data/civic_track.db` automatically. Use fictional names, contact details, photos, and signatures in a demo.

## Run with Docker Compose

1. Install Docker Desktop and make sure its engine is running.
2. From this folder, run `docker compose up --build -d`.
3. Open `http://localhost:5000`. To use another host port, set `CIVIC_TRACK_PORT` before starting Compose (for example, `$env:CIVIC_TRACK_PORT=8080` in PowerShell).
4. Stop the container with `docker compose down`. The `data` folder, including the database and session-signing key, remains on the host.

The Compose service publishes the app on the computer's network interfaces for trusted LAN access. Use firewall rules to restrict access to trusted devices, and do not configure router port forwarding or expose this prototype to the public internet.

## Access from another computer on the same Wi-Fi

1. Start Civic Track on the computer that holds the project with `py app.py`; keep that window open.
2. Find that computer's IPv4 address with `ipconfig` (look under the connected Wi-Fi adapter).
3. On another computer connected to the same trusted Wi-Fi, open `http://<computer-ip>:5000` (for example, `http://192.168.1.25:5000`).
4. If Windows Firewall blocks the connection, allow Python/Civic Track only on a trusted private network. Do not expose port 5000 to public networks or configure router port forwarding.

All visitors use the same local demo account and database, so they can see and change the same records. Use fictional demo information only. This is for a trusted local network, not public hosting.

## Desktop, Android, and iOS

Civic Track is a responsive, installable Progressive Web App (PWA). On desktop or Android, use the browser's **Install app** button or the browser menu's install option. On iPhone or iPad, open the site in Safari, tap **Share**, then **Add to Home Screen**.

Installation and service-worker support require a secure HTTPS website, except when testing on the same device at `localhost`. To install it on a phone, first host the app on an HTTPS address that the phone can reach; `127.0.0.1` on your computer is not the phone's address. This Flask prototype does not configure public hosting or HTTPS certificates.

The PWA caches its app shell so the interface can reopen offline, but sign-in, saved records, reports, and other data actions still require a running server and network connection. It is not an App Store or Google Play native package.

## Features

- Welcome, sign-up, log-in, password reset, and password change flows. Passwords are hashed. Email/SMS verification codes are simulated and shown in the app; no code is actually delivered.
- Stay signed in on the same browser for up to 14 days of inactivity. Activity refreshes the session expiration; the signing key persists in `data/session_secret.key` across app restarts.
- Profile details and photo, school/organization affiliations, a local reference signature vault, and account/data deletion.
- Volunteer-hour entries with optional advisor details and photo evidence; date-range goals, progress rings, impact estimate, milestone progress, and achievement badges.
- Assignment/task list with completion, on-time reporting, due-date highlighting, and optional study reminders.
- Monthly calendar, period-filtered dashboard and printable reports, badge printing, and printable resume draft.
- Color, text-size, dashboard period, notification, and daily reminder preferences.
- Browser notifications for badges and reminders when the app is open and the user has granted permission.
- Mobile-friendly layouts and a refresh/troubleshoot action.
- Installable PWA manifest, iOS home-screen metadata and icon, install instructions, and a cached offline app shell.
- Bitter is the default, self-hosted font and is included in the offline app-shell cache.
- The supplied Dream Team logo is used across the site, browser icon, profile avatar fallback, notifications, and install icons.

## Demo limitations

This is a single local demo profile, not a cloud or multi-user service. It does not deliver email/SMS codes or provide reliable background notifications. Study and daily reminders can fire only while the app is open. The signature vault and uploaded images are stored in the local SQLite database, not encrypted; do not save real signatures, verification documents, or sensitive personal information. Resume and report outputs are drafts based on user-entered, unverified data. The impact calculator is an illustrative estimate using the rate chosen in Settings, not an official valuation.

## Tests

Run the backend workflow tests with `py -m unittest discover -s tests -v`.
