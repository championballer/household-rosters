import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create and verify a consistent SQLite backup, retaining the newest 14."

    def handle(self, *args, **options):
        source = Path(settings.DATABASES["default"]["NAME"])
        backup_dir = Path(os.environ.get("HOUSEHOLD_BACKUP_DIR") or settings.BASE_DIR / "backups").expanduser().resolve()
        if not source.is_file():
            raise CommandError(f"Database does not exist: {source}")
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        final = backup_dir / f"household-{stamp}.sqlite3"
        fd, temporary_name = tempfile.mkstemp(prefix=".backup-", suffix=".tmp", dir=backup_dir)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            with sqlite3.connect(source, timeout=10) as src, sqlite3.connect(temporary) as dst:
                src.backup(dst)
            with sqlite3.connect(temporary) as check:
                result = check.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise CommandError("SQLite integrity check failed; the previous backups were kept.")
            os.replace(temporary, final)
            backups = sorted(backup_dir.glob("household-*.sqlite3"), reverse=True)
            for stale in backups[14:]:
                stale.unlink()
        finally:
            temporary.unlink(missing_ok=True)
        self.stdout.write(self.style.SUCCESS(f"Verified database backup created: {final.name}"))
