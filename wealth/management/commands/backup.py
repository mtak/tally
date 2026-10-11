import sqlite3
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create a consistent SQLite backup using the online backup API."

    def add_arguments(self, parser):
        parser.add_argument("destination")

    def handle(self, *args, **options):
        path = Path(options["destination"])
        if path.exists():
            raise CommandError("Destination already exists.")
        path.parent.mkdir(parents=True, exist_ok=True)
        with (
            sqlite3.connect(settings.DATABASES["default"]["NAME"]) as source,
            sqlite3.connect(path) as dest,
        ):
            source.backup(dest)
        path.chmod(0o600)
        self.stdout.write("Backup created.")
