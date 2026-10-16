"""Importer for the documented example CSV layout. No source file is retained."""

import csv, hashlib, io, re
from datetime import datetime, date
from decimal import Decimal
from django.core.exceptions import ValidationError
from .validation import to_minor, validate_balance
from django.db import transaction
from django.utils.translation import gettext as _
from .models import Entity, Account, Snapshot, Valuation, TaxAdjustment, ImportRecord


def euro(text, *, kind=None, asset_class=None):
    text = text.strip()
    if not text:
        return None
    # Explicit Dutch source syntax: optional euro prefix/sign, correctly grouped
    # thousands and a comma fraction. Never strip arbitrary punctuation/spaces.
    if re.match(r"[+-]€", text):
        text = '€' + text[0] + text[2:].lstrip(' \u00a0')
    match = re.fullmatch(r"(?:€[ \u00a0]*)?([+-]?)([0-9]+|[0-9]{1,3}(?:\.[0-9]{3})+)(?:,([0-9]+))?", text)
    if not match:
        raise ValueError(_("Invalid amount in the CSV."))
    value = Decimal(match[1] + match[2].replace('.', '') + '.' + (match[3] or '0'))
    try:
        if kind is not None:
            validate_balance(kind, asset_class, value)
        return to_minor(value)
    except ValidationError as exc:
        raise ValueError('; '.join(exc.messages)) from exc


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
    ignored = []
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
        elif label:
            ignored.append({"label": label, "line": line})
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

    def value(label, index, kind=None, asset_class=None):
        row = totalrow if label == 'Totaal' else labels.get(label, [])
        try:
            return euro(row[index], kind=kind, asset_class=asset_class) if index < len(row) else None
        except ValueError as exc:
            line = seen[("structure", "Totaal")] if label == 'Totaal' else seen[("label", label)]
            raise ValueError(_(
                'CSV row %(row)s (%(label)s), date %(date)s: %(error)s'
            ) % {'row': line, 'label': label, 'date': dict(columns)[index], 'error': exc}) from exc

    observations = []
    for idx, when in columns:
        amounts = {m[0]: value(m[0], idx, m[2], m[3]) for m in MAPPING}
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
        total = value("Totaal", idx)
        computed = sum(v for v in amounts.values() if v is not None) + sum(
            taxvalues.values()
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
                "balance_count": sum(v is not None for v in amounts.values()),
                "computed_total": computed,
                "difference": computed - total if total is not None else None,
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
        "recognized": [{"label": label, "line": seen[("label", label)]} for label in labels],
        "missing": [m[0] for m in MAPPING if m[0] not in labels],
        "optional_missing": sorted(consumed - {m[0] for m in MAPPING} - labels.keys()),
        "ignored": ignored,
    }


# Every mapped account row identifies the supported layout, even if all its
# historical cells are blank. Basis, tax and liquidity rows are optional.
CONSULTANCY_CLOSED_ON = date(2025, 1, 1)
ENTITY_KINDS = [
    ("Private", "private"), ("Consultancy", "sole"),
    ("Holding", "company"), ("Operating Company", "company"),
]


def preflight_overview(parsed):
    """Read-only compatibility result, refreshed inside the apply transaction."""
    errors = []
    if parsed["missing"]:
        errors.append(_("Missing required Overview account rows: %(rows)s") % {
            "rows": ", ".join(parsed["missing"])})
    observations = parsed["observations"]
    if not observations:
        errors.append(_("No recognized account observations found."))
    for obs in observations:
        if not any(v is not None for v in obs["amounts"].values()):
            errors.append(_("%(date)s: No recognized account observations found.") % {"date": obs["date"]})
        if obs["source_total"] is None:
            errors.append(_("%(date)s: Source total is missing.") % {"date": obs["date"]})
        elif abs(obs["difference"]) > 200:
            errors.append(_("%(date)s: Detail differs from the source total by more than EUR 2. Correct the Overview before importing.") % {"date": obs["date"]})
    if ImportRecord.objects.filter(digest=parsed["digest"]).exists():
        errors.append(_("This file has already been imported."))
    if Snapshot.objects.filter(date__in=[o["date"] for o in observations]).exists():
        errors.append(_("Some dates already exist. Existing observations will not be overwritten."))
    entities = {e.name: e for e in Entity.objects.filter(name__in=[n for n, _ in ENTITY_KINDS]).select_related("parent")}
    for name, kind in ENTITY_KINDS:
        entity = entities.get(name)
        expected_parent = "Holding" if name == "Operating Company" else None
        if entity and (entity.kind != kind or
                       (entity.parent.name if entity.parent else None) != expected_parent):
            errors.append(_("Owner configuration conflicts with import: %(name)s") % {"name": name})
    accounts = {a.name: a for a in Account.objects.select_related("entity").filter(name__in=[m[0] for m in MAPPING])}
    for label, owner, kind, asset, liquid, pension in MAPPING:
        account = accounts.get(label)
        dates = [o["date"] for o in observations if o["amounts"][label] is not None]
        # New consultancy defaults must also include every actual observation.
        closed = (account.closed_on if account else
                  CONSULTANCY_CLOSED_ON if owner == "Consultancy" else None)
        fields = []
        if account:
            try:
                account.full_clean()
            except ValidationError as exc:
                fields.extend(exc.messages)
            expected = {"entity": owner, "kind": kind, "asset_class": asset,
                        "liquid": liquid, "pension": pension, "joint": False, "currency": "EUR"}
            for field, value in expected.items():
                actual = account.entity.name if field == "entity" else getattr(account, field)
                if actual != value:
                    fields.append(str(Account._meta.get_field(field).verbose_name))
            if account.started_on and any(d < account.started_on for d in dates):
                fields.append(str(Account._meta.get_field("started_on").verbose_name))
        if closed and any(d >= closed for d in dates):
            fields.append(str(Account._meta.get_field("closed_on").verbose_name))
        if fields:
            errors.append(_("Account configuration conflicts with import: %(name)s") % {"name": label} + ": " + ", ".join(fields))
    return {**parsed, "errors": errors, "compatible": not errors}


def import_overview(parsed):
    try:
        return _import_overview(parsed)
    except ValidationError as exc:
        raise ValueError('; '.join(exc.messages)) from exc


@transaction.atomic
def _import_overview(parsed):
    checked = preflight_overview(parsed)
    if checked["errors"]:
        raise ValueError("\n".join(checked["errors"]))
    entities = {}
    for name, kind in ENTITY_KINDS:
        entities[name], created = Entity.objects.get_or_create(
            name=name, defaults={"kind": kind}
        )
        if created and name == "Operating Company":
            entities[name].parent = entities["Holding"]
            entities[name].save(update_fields=["parent"])
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
            defaults["closed_on"] = CONSULTANCY_CLOSED_ON
        account, created = Account.objects.get_or_create(name=label, defaults=defaults)
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
