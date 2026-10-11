# Household Rosters: implementation handoff

Status: ready to implement. This document is a plan, not an existing implementation.
Project directory: `/Users/shivkumar/Projects/household-rosters`
Target host: the user's Mac. Clients: household phones and laptops on the same Wi-Fi.

## 1. Product contract

Build a small, locally hosted web app for shared household responsibilities. Users create any number of named rosters, choose participants and their order, and see whose turn is next. A completion advances the roster immediately. There are no scheduled dates, deadlines, recurring jobs, or overdue tasks.

Required first-release behavior:

- Create, rename, describe, archive, and restore rosters.
- Add, rename, deactivate, and reactivate household members.
- Choose a different ordered participant list for each roster.
- Select the current participant explicitly when configuring a roster.
- Complete, skip, record a substitute completion, and undo the latest eligible action.
- Show a mobile-friendly dashboard and history per roster.
- Persist everything across app and computer restarts.
- Prevent duplicate submissions and simultaneous actions from advancing a turn twice.
- Run on the household LAN with automatic startup and database backups.
- Export each roster's history to CSV.

Do not add calendars, notifications, cloud hosting, native mobile apps, or individual account registration in this release. Normal household use requires selecting a name, not a password. This is declared attribution, not verified identity. Everyone with access can manage rosters. A trusted household LAN is the deployment assumption.

## 2. Technology and project layout

Use Python, a supported Django release (prefer Django 5.2 LTS with the latest compatible patch at implementation time), SQLite, Django templates, custom CSS, and small amounts of browser JavaScript. Use Waitress as the application server and WhiteNoise for static files. Check supported Python versions in official documentation before pinning dependencies. Record exact resolved dependency versions in a lock or pinned requirements file.

Use Django's test runner. Avoid a separate frontend build system, external CDN assets, WebSockets, Redis, and a separate database server.

Suggested layout:

```text
household-rosters/
  manage.py
  requirements.txt
  .gitignore
  .env.example
  README.md
  config/
    settings.py
    urls.py
    wsgi.py
  rosters/
    models.py
    forms.py
    services.py
    views.py
    urls.py
    migrations/
    tests/
    management/commands/backup_database.py
  templates/
    base.html
    rosters/...
  static/
    css/app.css
    js/app.js
  scripts/
    start.sh
    backup.sh
    launchd/...
  data/                       # ignored by Git
    household.sqlite3
  backups/                    # ignored by Git
  logs/                       # ignored by Git
  staticfiles/                # generated; ignored by Git
  plans/implementation-plan.md
```

Resolve paths from the project root, never from the process working directory. Permit `HOUSEHOLD_DATA_DIR` to override the default data directory. Git-ignore `.venv/`, secrets, databases including journal/WAL files, backups, logs, generated static files, and Python caches.

## 3. Data model

Use database constraints as well as form validation. Avoid hard deletion through the UI.

### Member

- `id`: primary key.
- `name`: required trimmed display name, maximum 80 characters.
- `is_active`: boolean, default true.
- `created_at`, `updated_at`.
- Disallow case-insensitive duplicate names across active and inactive members so the selector is unambiguous. Implement a consistent normalized name key with a unique constraint; document the normalization.

### Roster

- `id`, `name` (required, maximum 120 characters), `description` (optional).
- `is_archived`: boolean, default false.
- `current_participant`: nullable FK to RosterParticipant.
- `version`: nonnegative integer, default 0, incremented on every successful roster mutation.
- `created_at`, `updated_at`.

The circular relationship can be added in a subsequent migration. Service validation must ensure that the current participant belongs to this roster and is enabled and active. `current_participant` is null precisely when there are no eligible participants. A paused roster has no completion/skip buttons.

### RosterParticipant

- `id`, `roster` FK, `member` FK, `position` integer, `is_enabled` boolean.
- Unique constraint on `(roster, member)`.
- Sort eligible participants by `position`, then ID as a deterministic fallback.
- Eligibility: `is_enabled` and member `is_active`.
- Retain disabled rows to preserve historical references. Re-adding a member re-enables their existing row.
- Use consecutive positions when saving an order. A unique position constraint is optional; if added, implement collision-safe reordering.

### AuditEvent

- `id`, `roster` FK, `event_type`, `occurred_at`.
- `actor` nullable Member FK plus `actor_name_snapshot`.
- `completed_by` nullable Member FK plus `completed_by_name_snapshot`.
- `assigned_member` nullable Member FK plus name snapshot.
- `next_member` nullable Member FK plus name snapshot.
- `version_before`, `version_after`.
- `before_state`, `after_state`: JSON snapshots of roster name, description, archive state, ordered enabled member IDs/names, and current participant ID/member name.
- `request_id`: globally unique UUID for idempotency.
- `reverses_event`: nullable FK to AuditEvent for undo events.
- Optional short `note` with a length limit.

Event types: CREATE, EDIT, PARTICIPANTS_CHANGED, CURRENT_CHANGED, COMPLETE, SUBSTITUTE_COMPLETE, SKIP, UNDO, ARCHIVE, RESTORE, MEMBER_DEACTIVATED, MEMBER_REACTIVATED, MEMBER_RENAMED.

Audit events are append-only through the application. Snapshot names make old entries readable after renames. No edit/delete endpoint for events. This is application history, not a tamper-proof security log.

Use a separate `MemberAuditEvent` model for household-wide member creation/rename/deactivation/reactivation, with actor snapshot, timestamp, unique request ID, and before/after JSON. Changes affecting an enrolled member also append a roster event to each affected roster in the same transaction. This preserves per-roster history even when only a name changes.

## 4. Exact rotation and edit rules

Define these in `services.py`, not separately in views or templates.

1. Eligible order `[A, B, C]`, current A: complete -> B; B -> C; C -> A.
2. One eligible participant: completion records history and leaves the same person current.
3. No eligible participants: current null; display 'Add participants to start'.
4. Ordinary completion: assigned person and actual completer are the current member. Actor is the selected identity submitting the action; it can differ from the assigned person.
5. Substitute completion: user explicitly chooses actual completer from active household members. Advance from the assigned person's position, regardless of actual completer's position. Example: assigned A, actual C, order `[A,B,C]` -> next B.
6. Skip: advance exactly like completion; record actor and assigned member, with no actual completer. Require a confirmation screen or explicit confirmation dialog.
7. Reordering preserves the current participant if still eligible. New members join at the end unless a full order is explicitly submitted.
8. Removing/deactivating the current participant chooses the first still-eligible participant encountered after them in the OLD circular order. If none of the old participants survive but new ones are added, choose the first in the new order. If no one remains, set null.
9. Removing someone else preserves the current participant.
10. On a new roster choose the submitted starter, or first participant if unspecified. Reject a starter outside the roster.
11. Reactivation/re-enabling does not displace an existing current participant. If the roster was paused, select the first eligible participant in its current order.
12. Archive blocks complete/skip/edit participant actions. Restore preserves the pointer, normalizing it if needed. Display archived rosters separately.
13. Explicit 'Change whose turn it is' accepts an eligible participant, requires confirmation, increments version, and records an event.
14. Undo is allowed only for the latest roster event, only if it is COMPLETE, SUBSTITUTE_COMPLETE, or SKIP, and only if the event has not already been reversed. Restore its prior current participant and append UNDO. Validate that this participant remains eligible. Any intervening edit blocks undo. Do not support undoing undo or arbitrary historical rollback in v1.

Use UTC storage (`USE_TZ=True`) and `Australia/Sydney` as default display timezone, configurable through environment settings. Timestamps never influence turn selection.

## 5. Transactions, stale pages, and idempotency

SQLite does not implement row locking through `select_for_update()`. Do not rely on it for correctness.

All mutation forms contain the displayed roster version and a freshly generated request UUID. Preserve that UUID when retrying an uncertain request. Client-side disabling of a button helps usability but is not the concurrency guarantee.

Implement mutations using an optimistic compare-and-swap inside `transaction.atomic()`:

1. Validate input shape and selected active actor.
2. Check whether the request UUID already has a committed event. If so, return the original result after verifying it belongs to the same operation/roster; reuse for a different action is an error.
3. Begin transaction. Make the first database operation a conditional write to the roster: update its version from submitted V to V+1 only where ID matches and version equals V.
4. If no row changed, roll back. Check idempotency again outside the transaction, because another request may just have committed. Otherwise return HTTP 409 with 'This roster changed. Refresh and try again.' Do not automatically complete the newly current person's turn.
5. After obtaining the write lock, read the roster and participant state, validate the operation, update its pointer/other fields, and append the event with both snapshots.
6. Commit before returning success. An invalid operation must roll back the version increment too.

For member mutations, acquire SQLite's writer lock with a conditional version update on the member (add a Member version field) as the first operation. Then modify affected rosters and append their events within that same transaction. Roster creation can begin with an insert; duplicate submissions need idempotency handling through the unique event request ID and rollback. Ensure caught IntegrityError exceptions are handled outside the failed atomic block.

Configure a bounded SQLite busy timeout. Handle lock contention with a friendly retry response; preserve the request ID. Do not catch every exception and report success. Test rollback behavior and actual independent database connections.

## 6. Screens and routes

Use Django forms and normal POST/redirect/GET for mutations. Never mutate through GET. CSRF protection stays enabled.

Suggested routes:

- `/`: dashboard of active rosters, current person, short upcoming order, completion action.
- `/identity/`: choose household identity; remember ID in Django session.
- `/members/`: list and create members.
- `/members/<id>/edit/`, `/deactivate/`, `/reactivate/`: management screens/actions.
- `/rosters/new/`: name, description, ordered members, optional starter.
- `/rosters/<id>/`: full roster, actions, recent activity.
- `/rosters/<id>/edit/`: edit metadata and participants together as one audited mutation.
- `/rosters/<id>/complete/`, `/substitute/`, `/skip/`, `/undo/`, `/current/`: POST mutation endpoints (GET may render a confirmation form).
- `/rosters/<id>/archive/`, `/restore/`: POST actions.
- `/rosters/<id>/history/`: paginated history.
- `/rosters/<id>/history.csv`: CSV download.
- `/archived/`: archived rosters.
- `/api/dashboard/`: read-only JSON of versions and current people for polling.
- `/health/`: minimal status response; do not expose paths, secrets, or database contents.

Require an active selected identity before management or completion actions. If the selected person becomes inactive, prompt for a new selection. The identity selector should be visible in the page header.

Frontend requirements:

- Work at 360px width, with readable text and large touch targets.
- Use labels, semantic buttons, visible keyboard focus, accessible status messages.
- Provide up/down buttons for ordering; drag-and-drop is optional.
- Show assigned person explicitly before confirmation and next person after success.
- History shows action, time, actor, actual completer, assigned person, and next person as appropriate.
- Poll dashboard every 10 seconds while the tab is visible and on focus. If a displayed roster changes, refresh its version/request token or ask the user to refresh before submitting. Do not replace unsaved edit forms.
- Explain connection loss without claiming an action failed if its result is uncertain. Retry with the same request UUID.
- Load fonts, scripts, and styles locally. Core actions must still work without JavaScript.

CSV: export ordered events with stable column names, ISO 8601 timestamp and timezone, IDs, action, actor/completer/assigned/next snapshots, note, and reversed event ID. Escape fields starting with spreadsheet formula prefixes so user-entered names cannot become spreadsheet formulas. Add tests for commas, quotes, newlines, and Unicode.

## 7. Implementation phases and checks

Execute these in order. Keep each phase reviewable. Update a progress checklist in the README or a separate progress file; do not claim a phase passes until its checks run.

### Phase A — Scaffold and persistence

1. Create virtual environment, dependencies, Django project and app.
2. Configure persistent database path, timezone, templates, static files and environment settings.
3. Add `.gitignore` and `.env.example` with placeholders only.
4. Add a base page, health endpoint and README setup commands.
5. Run Django system checks and migrations. Create a record, stop/restart, and confirm it remains.

### Phase B — Schema

1. Implement models, constraints and migrations described above.
2. Add model/form validation for names and eligibility.
3. Add tests for duplicate normalized member names, duplicate roster membership, retained history, and timestamps.
4. Verify migrations apply cleanly to an empty database and a database from Phase A.

### Phase C — Domain services

1. Implement a single helper for eligible order and successor selection.
2. Implement create/edit/current/archive/restore and member operations.
3. Implement complete/substitute/skip/undo.
4. Add snapshots and transaction/idempotency handling to every mutation.
5. Test the full rules in Section 4 before building action views.

### Phase D — Management UI

1. Implement identity selection and active-identity checks.
2. Build member list/forms and roster create/edit forms.
3. Build reorder controls and starter selection.
4. Add explicit confirmation for deactivation/archive/current changes.
5. Verify server-side rejection of forged invalid participants and stale versions.

### Phase E — Daily-use UI and history

1. Build dashboard and roster detail page.
2. Wire completion, substitute, skip and undo forms to services.
3. Add polling and connection/status feedback.
4. Build paginated history and CSV export.
5. Test at mobile width, keyboard navigation, and without JavaScript.

### Phase F — Hosting and backups

1. Configure Waitress, WhiteNoise and collected static files.
2. Set DEBUG false; configure SECRET_KEY from a persistent local secret file/environment and explicit allowed hosts.
3. Listen on `0.0.0.0:8000` for LAN access. Browser URLs use the host's actual IP, not `0.0.0.0`.
4. Use standard CSRF behavior; add trusted origins only if required, using exact origins. Never disable CSRF to make LAN access work.
5. Add executable startup/backup scripts with absolute paths, strict error handling, and no printed secrets.
6. Supply macOS LaunchAgent templates with the real virtualenv interpreter, working directory and writable log paths. Document that LaunchAgents start on user login, not before login; computer sleep still makes the app unavailable.
7. Reserve the computer's IP in the router, document local firewall access, and validate from a second Wi-Fi device. Do not configure router port forwarding.
8. Implement backup command using Python `sqlite3.Connection.backup()` to a temporary file, verify backup integrity, then atomically rename to a timestamped file. Do not blindly copy an open database file.
9. Run backup on app setup and daily via launchd (no in-app scheduling required). Keep 14 successful daily backups; prune only after a new verified backup succeeds.
10. Document restore: stop app, back up current database, verify chosen backup, restore file, remove stale journal/WAL sidecars only while app is stopped, fix permissions if needed, restart, verify current turns and history.

Templates and scripts are safe to create as part of implementation. Installing/enabling background services should be done when actual app checks pass and the user has authorized running the completed app. Document all commands so deployment remains reproducible.

### Phase G — Acceptance and handoff

1. Run required automated checks below.
2. Complete manual household workflow below.
3. Document exact installed versions, commands, URLs, database location, backups and operational limits.
4. Report completed scope, test evidence, and any checks that require access to the user's router or a second device.

## 8. Required automated validation

Use meaningful service and HTTP tests; avoid tests that only mirror private implementation details.

- `[A,B,C]` full cycle and repeated cycles; one and zero participants.
- Substitute completion advances from assigned participant.
- Skip and eligible undo restore expected pointer and retain all events.
- Undo rejected after any intervening roster event or prior undo.
- Current/noncurrent removal, wraparound removal, all removed, new additions, reorder, and reactivation.
- Archive rejects mutation; restore normalizes pointer correctly.
- Rename leaves historical name snapshots intact; affected rosters receive audit entries.
- Repeating the same request UUID yields one event and one advancement.
- Different request UUIDs with the same submitted version yield one success and one conflict.
- Genuine concurrent requests on independent connections against a temporary FILE-backed SQLite database. Use TransactionTestCase or an isolated integration harness; an in-memory database and ordinary TestCase alone are insufficient evidence.
- Simulated failure after pointer update causes rollback of pointer, version and event together.
- Stale member-management requests cannot overwrite newer edits.
- Mutating GET requests rejected; CSRF enforced; invalid actor/participant rejected.
- CSV escaping and pagination; database restart persistence and backup/restore integrity.

Run `python manage.py check`, `python manage.py test`, migrations, and `collectstatic`. Run `check --deploy` and assess its output for local HTTP deployment: secure-cookie/HSTS/HTTPS settings must match the actual transport, not be enabled mechanically and break LAN HTTP.

## 9. Manual acceptance scenario

1. Add Shiv, Alex, and Sam.
2. Create 'Clear the bin', order Shiv -> Alex -> Sam, starter Shiv.
3. Create 'Dishwasher', order Sam -> Shiv, starter Sam.
4. Complete bin as Shiv: next Alex; dishwasher unchanged.
5. Record bin substitute completion by Sam while Alex is assigned: next Sam.
6. Undo: bin returns to Alex; history retains substitute event and correction.
7. Complete bin simultaneously from two stale browser tabs: one advancement only; the other tab receives conflict or the original result for a duplicate request.
8. Deactivate the current bin member and confirm the documented successor rule.
9. Restart application; verify rosters, members, current turns and histories.
10. Create backup, restore to an isolated test database, and compare data.
11. Open app on a phone on the same Wi-Fi; complete a task and observe dashboard refresh on another device.
12. Disconnect internet while keeping local Wi-Fi; confirm pages and actions still work.

## 10. Completion criteria and known limits

First release is complete when all required features and automated checks pass, startup and backup instructions are reproducible, and the manual workflow is verified wherever device access permits. Explicitly report unverified external steps instead of claiming success.

SQLite is appropriate for household traffic. Data survives process restarts; disk failure still requires a backup on another device or storage location. A backup on the same disk protects against many app/user mistakes but not loss of that disk. The host must be awake, running the app, and reachable on the LAN. Guest-network device isolation can prevent access. Identity selection records an asserted name, not authenticated identity. These are operational characteristics, not extra features to implement in v1.

## 11. Instructions for the implementing agent

- Read this plan completely, inspect the project and any applicable AGENTS.md before editing, and preserve existing user work.
- Treat the chosen stack and product scope as settled. Resolve routine details using this plan; do not repeatedly ask for confirmation.
- Implement sequentially through the phases, keeping domain rules in services and testing them before wiring the UI.
- Do not use Django's development server as the final household hosting setup.
- Do not seed fake members or rosters into the real persistent database. Demo/test data belongs in isolated databases.
- Do not claim SQLite row locks exist or substitute button disabling for transaction protection.
- Do not expose the app to the public internet or introduce external runtime dependencies.
- Never overwrite the persistent database during installation, migration, startup or upgrade. Take a verified backup before upgrades.
- Keep secrets and personal data out of Git, logs and test outputs.
- At handoff, provide the runnable app, setup/operation documentation, validation results and a clear statement of anything still unverified.

## 12. Reference documentation

Recheck version-specific details against official sources when implementing:

- Django 5.2 documentation: https://docs.djangoproject.com/en/5.2/
- SQLite and Django: https://docs.djangoproject.com/en/5.2/ref/databases/#sqlite-notes
- Django transactions: https://docs.djangoproject.com/en/5.2/topics/db/transactions/
- Django deployment checklist: https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/
- Waitress: https://docs.pylonsproject.org/projects/waitress/en/stable/
- WhiteNoise with Django: https://whitenoise.readthedocs.io/en/stable/django.html
- Python SQLite backup API: https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup
