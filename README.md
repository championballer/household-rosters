# Household Rosters

A small Django app for on-demand household responsibilities. Each roster rotates to its next participant when someone records a completion. Dates are used only in the audit history; they never choose whose turn it is.

## Current status

The application, SQLite persistence, history, export, and Mac launch/backup templates are present. The app has been used on the household network. Run the test and deployment checks below after future changes.

## Stack

- Python 3.10 or newer, Django 5.2 LTS, SQLite
- Django templates, local CSS and small vanilla JavaScript file
- Waitress WSGI server, WhiteNoise static asset serving
- SQLite database in `data/household.sqlite3` (override with `HOUSEHOLD_DATA_DIR`)
- Verified backups in `backups/` (override with `HOUSEHOLD_BACKUP_DIR`)

No internet connection is needed while using the running app. The setup needs access to install the pinned Python packages once.

## macOS first-time setup

From Terminal:

```sh
cd /path/to/household-rosters
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
```

Edit `.env`. Put the computer's local IP and local hostname in `HOUSEHOLD_ALLOWED_HOSTS`, for example:

```sh
HOUSEHOLD_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.42,mac-name.local
HOUSEHOLD_BIND_IP=192.168.1.42
HOUSEHOLD_TIME_ZONE=Australia/Sydney
HOUSEHOLD_DEBUG=0
```

Find the current Wi-Fi IP with `ipconfig getifaddr en0`. Reserve that address in the router so the household bookmark remains stable. `.env` is shell syntax and is ignored by Git. The app creates a persistent random secret in `data/secret-key` when one is not supplied.

Make scripts executable, apply migrations, create a first database backup, then start the app:

```sh
chmod +x scripts/start.sh scripts/backup.sh
mkdir -p logs
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
scripts/backup.sh
scripts/start.sh
```

Open `http://localhost:8000` on the host. Flatmates use `http://192.168.1.42:8000` (replace with the host's actual IP). The app listens on localhost and the reserved home-network IPv4 address at port 8000. Allow incoming connections on that port in the Mac firewall if prompted. Do not set router port forwarding. Guest Wi-Fi isolation may block device-to-device access.

The first visit opens the identity selector. Open **People** before selecting a name and add the first household member. The bootstrap member is created without an actor identity; after that, select your name in each browser. Names are self-selected and are not password-verified.

## Start and stop on macOS

Run `scripts/start.sh` from Terminal to serve the app. Stop it with Ctrl-C. Data is stored independently in `data/household.sqlite3`, so stopping the process or restarting the computer does not remove rosters or history. The machine must be awake and the server running for other devices to connect.

The supplied LaunchAgent starts the server when this Mac user logs in and keeps it running. It does not start before login. After setup and once the application has been installed and checked, install the templates:

```sh
mkdir -p "$HOME/Library/LaunchAgents"
cp scripts/launchd/com.householdrosters.server.plist "$HOME/Library/LaunchAgents/"
cp scripts/launchd/com.householdrosters.backup.plist "$HOME/Library/LaunchAgents/"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.householdrosters.server.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.householdrosters.backup.plist"
```

To stop/unload, use `launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.householdrosters.server.plist"` (and the backup plist as needed). Logs are in `logs/`.

## Ubuntu laptop setup

Install the app under your Ubuntu user account. The supplied systemd user units expect the checkout at `~/household-rosters`; edit their `WorkingDirectory` and `ExecStart` values if you choose another location.

```sh
sudo apt update
sudo apt install git python3 python3-venv sqlite3
git clone <GitHub-repository-URL> ~/household-rosters
cd ~/household-rosters
umask 077
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
mkdir -m 700 -p data
```

Edit `.env` so `HOUSEHOLD_BIND_IP` is the Ubuntu laptop's reserved LAN IPv4 address and `HOUSEHOLD_ALLOWED_HOSTS` includes that same address plus `localhost,127.0.0.1`. Keep `HOUSEHOLD_DEBUG=0`. Do not copy the Mac `.env` without changing its IP settings.

If you want to move your existing rosters, run `scripts/backup.sh` on the Mac and securely transfer the newest verified `backups/household-*.sqlite3` file to `~/household-rosters/data/household.sqlite3` on Ubuntu **before starting the Ubuntu server**. Set that file to mode 600 with `chmod 600 data/household.sqlite3`. GitHub does not contain the database, `.env`, or the private `data/secret-key`. A fresh secret key on Ubuntu will require browsers to choose their names again; roster data and history remain intact. Do not run both hosts as separate active copies of the same household database.

Finish setup and test it manually:

```sh
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py check
.venv/bin/python manage.py test
scripts/backup.sh
scripts/start.sh
```

Open `http://<Ubuntu-LAN-IP>:8000` from another household device. Stop the manual server with Ctrl-C before installing the service. The user service starts on login; `enable-linger` also starts it at boot and keeps it running after logout:

```sh
mkdir -p ~/.config/systemd/user
cp scripts/systemd/* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now household-rosters.service household-rosters-backup.timer
sudo loginctl enable-linger "$USER"
systemctl --user status household-rosters.service
```

The backup timer runs daily at 03:15 and catches up after downtime. Use `journalctl --user -u household-rosters.service -n 50 --no-pager` to inspect startup errors. If Ubuntu's firewall is enabled, allow TCP port 8000 only from your home LAN. Keep router port forwarding disabled and copy verified backups to another device occasionally.

## Database and backups

The backup command uses SQLite's online backup API, checks `PRAGMA integrity_check`, and only then atomically publishes a timestamped backup. It retains the newest 14 verified files. A failed backup does not prune older copies.

Create a backup manually with `scripts/backup.sh`. The LaunchAgent schedules one at 3:15 am and also runs once when loaded. For protection against disk loss, periodically copy a verified backup to a different physical device or storage location.

To restore a backup:

1. Stop the app/LaunchAgent.
2. Make a backup of the current `data/household.sqlite3` before replacing it.
3. Check the chosen backup with `sqlite3 path/to/backup.sqlite3 'PRAGMA integrity_check;'`; it should print `ok`.
4. Copy it to a temporary file under `data/`, then atomically rename that file to `household.sqlite3`.
5. Only while the app is stopped, remove stale `household.sqlite3-wal` and `household.sqlite3-shm` sidecars if present.
6. Start the app and check roster turns and histories.

Before upgrading code or dependencies, stop the service and make a verified backup. Then install dependencies, run `manage.py migrate`, collect static files, and start the service again. Migrations update the existing database in place; they do not seed demo household data.

## Useful commands

```sh
.venv/bin/python manage.py check
.venv/bin/python manage.py check --deploy
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py backup_database
```

For a disposable local development server only, run `.venv/bin/python manage.py runserver`; do not use it for household hosting. For the household server use the supplied Waitress script.

## Behavior notes

- Completion advances one position and wraps around. A one-person roster stays on that person.
- Substitute completion records who did the work but advances from the assigned person's position.
- A skip advances the position and records no completer. It requires explicit confirmation.
- Undo is available for the latest completion or skip only. It adds a correction event and keeps the original history entry.
- Roster history includes timestamps, action, actor, completer, assigned person, next person, and before/after snapshots. Timestamps are displayed in `Australia/Sydney` by default.
- Renaming/deactivating a person preserves prior names in snapshots. Deactivated participants remain linked to their rosters for history.
- A stale roster form receives a conflict instead of advancing an already changed turn. Repeated request IDs are idempotent.
- CSV history export quotes CSV fields and prefixes spreadsheet formula characters, including after leading whitespace, to reduce formula injection risk.
- Access is intended for a trusted home Wi-Fi network. Everyone who can reach it can manage rosters. The selected name is declared, not authenticated.

## Network access and security

The server binds to localhost and the reserved home-network IPv4 address. `HOUSEHOLD_ALLOWED_HOSTS` validates HTTP host names; it is not a network access rule. Anyone whose device can connect to port 8000 can read roster/history pages, select any household identity, and change rosters. The app does not provide a filesystem browser, but the server process runs under the host OS user, so a software vulnerability would put that account at risk.

Keep port 8000 out of UniFi port forwarding rules, use the trusted household network, and keep Django/Waitress/WhiteNoise updated. The app uses plain HTTP, so do not expose it to the public internet or carry it across an untrusted network. The Mac firewall can be enabled in System Settings > Network > Firewall; allow the Python server when prompted so household devices can still connect. The unused Django admin URL is not mounted.

App-side protections include parameterized Django ORM queries, escaped template output, CSRF checks on changes, explicit Host validation, a restrictive Content Security Policy, clickjacking and MIME-sniffing headers, bounded form/input sizes, and CSV formula escaping. Waitress limits request bodies to 128 KiB and headers to 16 KiB. Changes to `scripts/start.sh` and Python code take effect after stopping and restarting the running server. The `check --deploy` command reports HTTPS/HSTS/secure-cookie warnings because this setup deliberately serves local HTTP; enabling those options without HTTPS would break household access.

Write requests are limited to 30 POSTs per device IP within a rolling 60-second window. Excess requests receive HTTP 429 with a `Retry-After` header; normal page views and the dashboard's read polling are unaffected. The limiter uses Waitress's direct peer address, ignores `X-Forwarded-For`, and keeps bounded in-memory counters that reset when the server restarts. It reduces rapid repeated changes, but it is not a substitute for access control or network-level denial-of-service protection.

These controls do not authenticate people. Any device able to reach port 8000 can select any displayed household name and change rosters. The history records the selected name, not a verified identity. For stronger access control, the app would need an authentication feature or a private network layer, and protecting traffic from other network users would require HTTPS.

## Implementation notes

See [the handoff implementation plan](plans/implementation-plan.md) for full domain rules and acceptance scenarios. The project does not contain generated test fixtures or seeded members/rosters.
