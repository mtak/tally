from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from wealth.importer import parse_overview, import_overview


class Command(BaseCommand):
    help = "Preview or import a Google Sheets Overview CSV. Does not retain the file."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        try:
            p = parse_overview(Path(options["path"]).read_bytes())
            for warning in p["warnings"]:
                self.stdout.write(warning)
            if options["apply"]:
                self.stdout.write(f"Imported {import_overview(p)} observations.")
            else:
                self.stdout.write(
                    f"Preview: {len(p['observations'])} observations. Add --apply to import."
                )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
