"""Importer for the documented example CSV layout. No source file is retained."""

import csv, hashlib, io
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from django.db import transaction
from django.utils.translation import gettext as _
from .models import Entity, Account, Snapshot, Valuation, TaxAdjustment, ImportRecord


def euro(text):
    text = (
        text.strip()
        .replace("€", "")
        .replace(" ", "")
        .replace("\u00a0", "")
        .replace(".", "")
        .replace(",", ".")
    )
    if not text:
        return None
    try:
        return int((Decimal(text) * 100).quantize(Decimal("1")))
    except InvalidOperation as exc:
        raise ValueError(_("Invalid amount in the CSV.")) from exc


# Label, owner, account type, asset, liquid, pension
MAPPING = [
    ("Example Bank Private Current", "Private", "bank", "cash", True, False),
    ("Example Bank Savings", "Private", "bank", "cash", True, False),
    ("Example Bank Investments", "Private", "broker", "equities", True, False),
    ("Example Brokerage Private", "Private", "broker", "equities", True, False),
    ("Example Deposit Provider", "Private", "claim", "deposit", False, False),
    ("Personal Loan Receivable", "Private", "claim", "loan", False, False),
    ("Example Brokerage Pension", "Private", "broker", "equities", False, True),
    ("Geschatte waarde", "Private", "property", "property", False, False),
    ("Hypotheekschuld 1", "Private", "mortgage", "property", False, False),
    ("Hypotheekschuld 2", "Private", "mortgage", "property", False, False),
    ("Example Bank Business Current", "Consultancy", "bank", "cash", True, False),
    ("Example Bank Business Savings", "Consultancy", "bank", "cash", True, False),
    ("Example Bank Holding Current", "Holding", "bank", "cash", True, False),
    ("Example Bank Operating Company Current", "Operating Company", "bank", "cash", True, False),
    ("Example Bank Holding Savings", "Holding", "bank", "cash", True, False),
    ("Example Bank Operating Company Savings", "Operating Company", "bank", "cash", True, False),
    ("Example Brokerage Value", "Holding", "broker", "equities", True, False),
]


def parse_overview(content):
    try:
        rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError(_("Use a UTF-8 CSV export.")) from exc
    # Only consumed rows must be unique; repeated section/subtotal headings
    # in the agreed layout remain harmless.
    consumed = {m[0] for m in MAPPING} | {
        "Example Brokerage Contributions", "Example Bank Capital Tax", "Example Brokerage Corporate Tax", "Example Brokerage Capital Tax",
        "Liquide vermogen", "Niet-liquide vermogen",
    }
    seen = {}
    labels = {}
    header = totalrow = None
    for line, row in enumerate(rows, 1):
        structure = row[0].strip() if row else ""
        label = row[1].strip() if len(row) > 1 else ""
        keys = []
        if structure in {"Prive", "Totaal"}:
            keys.append(("structure", structure))
        if label in consumed:
            keys.append(("label", label))
        for key in keys:
            if key in seen:
                raise ValueError(_(
                    'Duplicate CSV row "%(label)s" at rows %(first)s and %(second)s.'
                ) % {"label": key[1], "first": seen[key], "second": line})
            seen[key] = line
        if structure == "Prive":
            header = row
        if structure == "Totaal":
            totalrow = row
        if label in consumed:
            labels[label] = row
    if not header:
        raise ValueError(_("The Overview header was not found."))
    columns = []
    warnings = []
    for i, label in enumerate(header[2:], 2):
        if not label.strip():
            continue
        if label.strip() == "€ 12.345":
            when = date(2025, 8, 1)
            warnings.append(_("Corrected the confirmed date header to 2025-08-01."))
        else:
            try:
                when = datetime.strptime(label.strip(), "%d-%m-%Y").date()
            except ValueError as exc:
                raise ValueError(_("Invalid date header: ") + label) from exc
        if when in [d for _, d in columns]:
            raise ValueError(_("Duplicate valuation date."))
        columns.append((i, when))
    if not columns or not totalrow:
        raise ValueError(_("No historical totals found."))

    def value(label, index):
        row = labels.get(label, [])
        return euro(row[index]) if index < len(row) else None

    observations = []
    for idx, when in columns:
        amounts = {m[0]: value(m[0], idx) for m in MAPPING}
        taxes = {
            k: value(label, idx)
            for k, label in [
                ("bank_ab", "Example Bank Capital Tax"),
                ("broker_vpb", "Example Brokerage Corporate Tax"),
                ("broker_ab", "Example Brokerage Capital Tax"),
            ]
        }
        # Absent historic deductions mean no deduction in that source scenario.
        taxvalues = {k: v or 0 for k, v in taxes.items()}
        total = euro(totalrow[idx]) if idx < len(totalrow) else None
        computed = sum(v for v in amounts.values() if v is not None) + sum(
            taxvalues.values()
        )
        if total is not None and abs(computed - total) > 200:
            warnings.append(
                str(when) + ": " + _("Source total differs from the imported detail.")
            )
        liquid = value("Liquide vermogen", idx)
        illiquid = value("Niet-liquide vermogen", idx)
        if (
            total is not None
            and liquid is not None
            and illiquid is not None
            and abs(liquid + illiquid - total) > 200
        ):
            warnings.append(
                str(when)
                + ": "
                + _(
                    "Source liquidity breakdown does not reconcile; it will be recalculated."
                )
            )
        observations.append(
            {
                "date": when,
                "amounts": amounts,
                "taxes": taxvalues,
                "basis": value("Example Brokerage Contributions", idx),
                "net_deposits": value("Example Brokerage Contributions", idx),
                "source_total": total,
            }
        )
    warnings.append(
        _(
            "CSV values are rounded to whole euros; small historical reconciliation differences can remain."
        )
    )
    warnings.append(
        _("Example Brokerage net deposits come from Example Brokerage Contributions. Net deposits for other investment accounts are unknown.")
    )
    return {
        "digest": hashlib.sha256(content).hexdigest(),
        "observations": observations,
        "warnings": warnings,
    }


@transaction.atomic
def import_overview(parsed):
    if ImportRecord.objects.filter(digest=parsed["digest"]).exists():
        raise ValueError(_("This file has already been imported."))
    dates = [o["date"] for o in parsed["observations"]]
    if Snapshot.objects.filter(date__in=dates).exists():
        raise ValueError(
            _(
                "Some dates already exist. Existing observations will not be overwritten."
            )
        )
    entities = {}
    for name, kind in [
        ("Private", "private"),
        ("Consultancy", "sole"),
        ("Holding", "company"),
        ("Operating Company", "company"),
    ]:
        entities[name], created = Entity.objects.get_or_create(
            name=name, defaults={"kind": kind}
        )
        if entities[name].kind != kind:
            raise ValueError(_("Owner configuration conflicts with import: %(name)s") % {"name": name})
    entities["Operating Company"].parent = entities["Holding"]
    entities["Operating Company"].save()
    accounts = {}
    for label, owner, kind, asset, liquid, pension in MAPPING:
        defaults = {
            "entity": entities[owner],
            "kind": kind,
            "asset_class": asset,
            "liquid": liquid,
            "pension": pension,
        }
        if owner == "Consultancy":
            defaults["closed_on"] = date(2025, 1, 1)
        account, created = Account.objects.get_or_create(name=label, defaults=defaults)
        if not created and (
            account.entity_id != entities[owner].id
            or account.kind != kind
            or account.joint
        ):
            raise ValueError(_("Account configuration conflicts with import: %(name)s") % {"name": label})
        accounts[label] = account
    Account.objects.get_or_create(
        name="Gezamenlijke rekening",
        defaults={
            "entity": entities["Private"],
            "joint": True,
            "started_on": date(2025, 8, 1),
        },
    )
    for obs in parsed["observations"]:
        s = Snapshot.objects.create(
            date=obs["date"],
            complete=True,
            imported=True,
            source_total_minor=obs["source_total"],
        )
        for label, amount in obs["amounts"].items():
            if amount is not None:
                Valuation.objects.create(
                    snapshot=s,
                    account=accounts[label],
                    amount_minor=amount,
                    basis_minor=obs["basis"] if label == "Example Brokerage Value" else None,
                    net_deposits_minor=obs["net_deposits"] if label == "Example Brokerage Value" else None,
                )
        for kind, amount in obs["taxes"].items():
            TaxAdjustment.objects.create(snapshot=s, kind=kind, amount_minor=amount)
    ImportRecord.objects.create(digest=parsed["digest"], warnings=parsed["warnings"])
    return len(parsed["observations"])
