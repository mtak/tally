import json
import os
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Create or display a persistent development login (DEBUG only)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Development logins require DEBUG enabled.")

        path = settings.DATA_DIR / ".dev-login.json"
        users = get_user_model().objects
        if path.exists():
            try:
                credentials = json.loads(path.read_text())
                username = credentials["username"]
                password = credentials["password"]
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise CommandError("Cannot read the saved development login.") from exc
            user = users.filter(username=username).first()
            if user is None or not user.is_active or not user.check_password(password):
                raise CommandError(
                    "The saved development login no longer works. "
                    "Use createsuperuser to create a login; existing passwords are not reset."
                )
        else:
            username = "tally-dev"
            if users.filter(username=username).exists():
                raise CommandError(
                    "User tally-dev already exists without saved credentials. "
                    "Use createsuperuser to create a login; existing passwords are not reset."
                )
            password = secrets.token_urlsafe(24)
            credentials = {"username": username, "password": password}
            # Keep the plaintext password in the private instance volume, outside Git.
            # Exclusive creation also prevents concurrent runs from overwriting it.
            try:
                with transaction.atomic():
                    with open(path, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
                        try:
                            users.create_superuser(username=username, password=password)
                            json.dump(credentials, output)
                        except Exception:
                            path.unlink()
                            raise
            except OSError as exc:
                raise CommandError("Cannot save the development login.") from exc

        self.stdout.write(f"Username: {username}")
        self.stdout.write(f"Password: {password}")
