from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from wealth.importer import parse_overview, preflight_overview, import_overview


class Command(BaseCommand):
    help = "Preview or import a Google Sheets Overview CSV. Does not retain the file."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        if not settings.TALLY_IMPORT_HISTORY_ENABLED:
            raise CommandError("Import history is disabled by TALLY_IMPORT_HISTORY_ENABLED.")
        try:
            p = preflight_overview(parse_overview(Path(options["path"]).read_bytes()))
            for row in p["recognized"]:
                self.stdout.write(f"Recognized: {row['label']} (row {row['line']})")
            for label in p["missing"]:
                self.stdout.write(f"Missing: {label}")
            for row in p["ignored"]:
                self.stdout.write(f"Ignored: {row['label']} (row {row['line']})")
            for obs in p["observations"]:
                self.stdout.write(f"{obs['date']}: source={obs['source_total']} detail={obs['computed_total']} difference={obs['difference']} (EUR cents)")
            if p["errors"]:
                raise ValueError("\n".join(p["errors"]))
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
