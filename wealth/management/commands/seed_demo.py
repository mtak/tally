from datetime import date
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from wealth.models import Entity, Account, Snapshot, Valuation


class Command(BaseCommand):
    help = "Create fictional demo data in an empty database. Does not create a login."

    @transaction.atomic
    def handle(self, *args, **options):
        if Snapshot.objects.exists() or Account.objects.exists():
            raise CommandError("Demo requires an empty portfolio.")
        private = Entity.objects.create(name="Personal", kind="private")
        holding = Entity.objects.create(name="Example Holding", kind="company")
        specs = [
            ("Everyday account", private, "bank", "cash", True, False, False, 840000),
            ("Joint account", private, "bank", "cash", True, False, True, 1200000),
            ("Savings", private, "bank", "cash", True, False, False, 3200000),
            (
                "Investment portfolio",
                private,
                "broker",
                "equities",
                True,
                False,
                False,
                9600000,
            ),
            (
                "Fixed-term deposit",
                private,
                "claim",
                "deposit",
                False,
                False,
                False,
                4000000,
            ),
            ("Home", private, "property", "property", False, False, False, 62000000),
            (
                "Mortgage",
                private,
                "mortgage",
                "property",
                False,
                False,
                False,
                -28000000,
            ),
            (
                "Pension portfolio",
                private,
                "broker",
                "equities",
                False,
                True,
                False,
                7400000,
            ),
            ("Business savings", holding, "bank", "cash", True, False, False, 6800000),
            (
                "Business portfolio",
                holding,
                "broker",
                "equities",
                True,
                False,
                False,
                15500000,
            ),
        ]
        accounts = []
        for name, entity, kind, asset, liquid, pension, joint, amount in specs:
            a = Account.objects.create(
                name=name,
                entity=entity,
                kind=kind,
                asset_class=asset,
                liquid=liquid,
                pension=pension,
                joint=joint,
                rate_bps=325 if kind == "claim" else 0,
                matures_on=date(2027, 3, 1) if kind == "claim" else None,
            )
            accounts.append((a, amount))
        for year in range(2022, 2027):
            s = Snapshot.objects.create(
                date=date(year, 1, 1),
                complete=True,
                notes="Fictional demonstration data",
            )
            factor = 70 + (year - 2022) * 7
            for a, amount in accounts:
                value = (
                    amount
                    if a.kind in ("mortgage", "claim")
                    else amount * factor // 100
                )
                v = Valuation.objects.create(
                    snapshot=s,
                    account=a,
                    amount_minor=value,
                    basis_minor=10000000
                    if a.entity == holding and a.kind == "broker"
                    else None,
                    net_deposits_minor=amount + (year - 2022) * 200000 if a.kind == "broker" else None,
                )
        self.stdout.write("Fictional demo created.")
