import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create a consistent SQLite backup using the online backup API."

    def add_arguments(self, parser):
        parser.add_argument("destination")

    def handle(self, *args, **options):
        path = Path(options["destination"])
        temporary = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # A private sibling permits atomic, no-clobber publication on this filesystem.
            fd, name = tempfile.mkstemp(prefix=".tally-backup-", dir=path.parent)
            temporary = Path(name)
            os.close(fd)
            source_uri = Path(settings.DATABASES["default"]["NAME"]).resolve().as_uri()
            with (
                closing(sqlite3.connect(source_uri + "?mode=ro", uri=True)) as source,
                closing(sqlite3.connect(temporary)) as dest,
            ):
                source.backup(dest)
            # link() fails for every existing destination, including dangling symlinks.
            os.link(temporary, path)
        except FileExistsError as exc:
            raise CommandError("Destination already exists.") from exc
        except (OSError, sqlite3.Error) as exc:
            raise CommandError(f"Backup failed: {exc}") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.stdout.write("Backup created.")
