from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Q
from django.utils.translation import gettext as _
from .models import Account, Snapshot, Valuation, ASSETS


def rounded(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rate(amount, bps):
    return rounded(Decimal(amount) * Decimal(bps) / 10000)


def owned(account, amount):
    return rounded(Decimal(amount) / 2) if account.joint else amount


def cumulative_result(valuation):
    """Total gain/loss from the full account value and signed inception net deposits."""
    if valuation is None or valuation.net_deposits_minor is None:
        return None
    return valuation.amount_minor - valuation.net_deposits_minor


def performance(valuation):
    """Period result between consecutive observations; no estimated return percentage."""
    if valuation.net_deposits_minor is None:
        return None
    previous = Valuation.objects.filter(
        account=valuation.account, snapshot__complete=True,
        snapshot__date__lt=valuation.snapshot.date,
    ).select_related("snapshot").order_by("-snapshot__date").first()
    if previous is None or previous.net_deposits_minor is None:
        return None
    net = valuation.net_deposits_minor - previous.net_deposits_minor
    return {
        "result": valuation.amount_minor - previous.amount_minor - net,
        "net_deposits": net,
        "since": previous.snapshot.date,
        "days": (valuation.snapshot.date - previous.snapshot.date).days,
    }


def investment_history(account, through):
    """Full, gross account observations; never synthesize carried or draft points."""
    rows = [
        {"date": v.snapshot.date, "amount": v.amount_minor,
         "net_deposits": v.net_deposits_minor, "cumulative_result": cumulative_result(v)}
        for v in Valuation.objects.filter(
            account=account, snapshot__complete=True, snapshot__date__lte=through,
        ).select_related("snapshot").order_by("snapshot__date")
    ]
    return {
        "rows": rows,
        "chart": {
            "dates": [row["date"].isoformat() for row in rows],
            "unknown_label": _("Net deposits unknown"),
            "series": [
                {"name": label, "data": [row[key] for row in rows]}
                for key, label in (
                    ("amount", _("Account value")),
                    ("net_deposits", _("Net deposits since opening (EUR)")),
                    ("cumulative_result", _("Result since opening")),
                )
            ],
        },
    }


def broker_tax_covered(basis, overrides):
    """Snapshot-wide historical deductions can cover unknown broker bases."""
    return basis is not None or {"broker_vpb", "broker_ab"} <= overrides.keys()


def active_accounts(snapshot):
    """Accounts in scope on this valuation date, including aggregate closures."""
    return (
        Account.objects.select_related("entity")
        .filter(Q(closed_on__isnull=True) | Q(closed_on__gt=snapshot.date))
        .filter(Q(started_on__isnull=True) | Q(started_on__lte=snapshot.date))
    )


def maturity_calendar(snapshot):
    """Indicative gross release of positive claim balances; no repayment inference."""
    accounts = list(active_accounts(snapshot).filter(kind="claim"))
    latest = {
        v.account_id: v for v in Valuation.objects.filter(
            account__in=accounts, snapshot__complete=True,
            snapshot__date__lte=snapshot.date,
        ).select_related("snapshot").order_by("snapshot__date")
    }
    sections = {key: [] for key in ("scheduled", "overdue", "unknown", "missing", "nonpositive")}
    quarters = defaultdict(lambda: {"private": 0, "business": 0})
    rows = []
    for account in accounts:
        valuation = latest.get(account.pk)
        amount = owned(account, valuation.amount_minor) if valuation else None
        group = "private" if account.entity.kind == "private" else "business"
        end = account.matures_on
        status = (
            "missing" if amount is None else
            "nonpositive" if amount <= 0 else
            "unknown" if end is None else
            "overdue" if end < snapshot.date else "scheduled"
        )
        row = {"account": account, "amount": amount, "valuation": valuation,
               "stale": bool(valuation and valuation.snapshot.date != snapshot.date),
               "group": group, "status": status}
        rows.append(row)
        sections[status].append(row)
        if status == "scheduled":
            quarters[(end.year, (end.month - 1) // 3 + 1)][group] += amount
    quarterly = [
        {"label": _("Q%(quarter)s %(year)s") % {"quarter": quarter, "year": year},
         **values, "total": sum(values.values())}
        for (year, quarter), values in sorted(quarters.items())
    ]
    labels = {"private": _("Private"), "business": _("Business")}
    statuses = {
        "scheduled": _("Scheduled maturities"), "overdue": _("Past maturity — needs attention"),
        "unknown": _("Maturity date unknown"), "missing": _("Balance unknown"),
        "nonpositive": _("No positive balance"),
    }
    return {
        "rows": rows, "quarters": quarterly,
        "sections": [{"key": key, "label": statuses[key], "rows": items}
                     for key, items in sections.items() if items],
        "chart": {
            "quarters": quarterly, "groups": labels,
            "labels": {"balance": _("Your balance"), "observed": _("Observation date"),
                       "start": _("Start date"), "end": _("Maturity date"),
                       "unknown": _("Unknown"), "carried": _("Carried forward")},
            "rows": [
                {"name": r["account"].name, "owner": r["account"].entity.name,
                 "group": r["group"], "amount": r["amount"], "stale": r["stale"],
                 "status": str(statuses[r["status"]]),
                 "observed": r["valuation"].snapshot.date.isoformat() if r["valuation"] else None,
                 "start": r["account"].started_on.isoformat() if r["account"].started_on else None,
                 "end": r["account"].matures_on.isoformat() if r["account"].matures_on else None}
                for r in rows
            ],
        },
    }


def report(snapshot, include_home=True, include_pension=True, net=True):
    accounts = list(active_accounts(snapshot))
    available = (
        Valuation.objects.filter(snapshot__date__lte=snapshot.date)
        .filter(Q(snapshot__complete=True) | Q(snapshot=snapshot))
        .select_related("account__entity", "snapshot")
        .order_by("snapshot__date")
    )
    latest = {v.account_id: v for v in available}
    groups = dict.fromkeys(["private", "home", "business", "pension"], 0)
    assets = defaultdict(int)
    liquidity = {"liquid": 0, "illiquid": 0}
    boxes = {"1": 0, "2": 0, "3": 0}
    rows = []
    missing = []
    stale = []
    warnings = []
    bank_base = 0
    broker_vpb = 0
    broker_ab = 0
    overrides = {t.kind: t.amount_minor for t in snapshot.tax_adjustments.all()}
    unknown_broker_tax = False
    for account in accounts:
        is_home = account.kind in ("property", "mortgage")
        if (is_home and not include_home) or (account.pension and not include_pension):
            continue
        v = latest.get(account.pk)
        if v is None:
            missing.append(account.name)
            continue
        amount = owned(account, v.amount_minor)
        group = (
            "home"
            if is_home
            else "pension"
            if account.pension
            else "business"
            if account.entity.kind != "private"
            else "private"
        )
        groups[group] += amount
        liquid_key = "liquid" if account.liquid and not account.pension else "illiquid"
        liquidity[liquid_key] += amount
        box = (
            "1"
            if is_home or account.pension
            else "2"
            if account.entity.kind == "company"
            else "3"
            if account.entity.kind == "private"
            else None
        )
        if box:
            boxes[box] += amount
        if v.snapshot.date != snapshot.date:
            stale.append(account.name)
        # Account classification is authoritative; archived positions are ignored.
        if account.kind != "mortgage":
            assets[account.asset_class] += amount
        if account.entity.kind == "company":
            if account.kind == "broker":
                if v.basis_minor is None:
                    unknown_broker_tax = True
                    if not broker_tax_covered(v.basis_minor, overrides):
                        warnings.append(_("Missing tax basis: ") + account.name)
                else:
                    correction = -rate(
                        amount - owned(account, v.basis_minor), snapshot.vpb_bps
                    )
                    broker_vpb += correction
                    broker_ab -= rate(amount + correction, snapshot.ab_bps)
            else:
                bank_base += amount
        rows.append(
            {
                "account": account,
                "valuation": v,
                "amount": amount,
                "stale": v.snapshot.date != snapshot.date,
                "performance": performance(v) if account.kind == "broker" else None,
                "cumulative_result": cumulative_result(v) if account.kind == "broker" else None,
            }
        )
    tax = {
        "bank_ab": -rate(bank_base, snapshot.ab_bps),
        "broker_vpb": None if unknown_broker_tax else broker_vpb,
        "broker_ab": None if unknown_broker_tax else broker_ab,
    }
    tax.update(overrides)
    tax_complete = all(value is not None for value in tax.values())
    tax_total = (sum(tax.values()) if tax_complete else None) if net else 0
    gross_total = sum(groups.values())
    groups["business"] = groups["business"] + tax_total if tax_total is not None else None
    # Show tax deduction as a separate liquidity bridge, not an arbitrary allocation.
    gross_liquidity = liquidity.copy()
    boxes["2"] = boxes["2"] + tax_total if tax_total is not None else None
    total = gross_total + tax_total if tax_total is not None else None
    property_value = sum(r["amount"] for r in rows if r["account"].kind == "property")
    mortgage_debt = -sum(r["amount"] for r in rows if r["account"].kind == "mortgage")
    ltmv = Decimal(mortgage_debt) / property_value * 100 if property_value > 0 else None
    return {
        "snapshot": snapshot,
        "total": total,
        "gross_total": gross_total,
        "tax_complete": tax_complete,
        "groups": groups,
        "assets": dict(assets),
        "liquidity": gross_liquidity,
        "boxes": boxes,
        "rows": rows,
        "missing": missing,
        "stale": stale,
        "warnings": warnings,
        "tax": tax,
        "tax_total": tax_total,
        "net": net,
        "historical_tax": bool(overrides),
        "ltmv": ltmv,
        "source_difference": total - snapshot.source_total_minor
        if snapshot.source_total_minor is not None
        and include_home
        and include_pension
        and net
        and total is not None
        else None,
    }


def asset_mix(summary):
    """Gross allocation, matching the positive category totals in the asset pie.

    Retain exact cents and Decimal percentages until presentation. Debts and
    liquidation corrections never contribute to this denominator.
    """
    amounts = {key: max(summary["assets"].get(key, 0), 0) for key, _ in ASSETS}
    total = sum(amounts.values())
    return {
        "snapshot": summary["snapshot"],
        "total": total,
        "missing": summary["missing"],
        "categories": [
            {
                "key": key,
                "name": str(label),
                "amount": amounts[key],
                "percentage": Decimal(amounts[key]) * 100 / total if total else None,
                "observations": [
                    row for row in summary["rows"]
                    if row["account"].kind != "mortgage"
                    and row["account"].asset_class == key
                ],
            }
            for key, label in ASSETS
        ],
    }


def movement(snapshot):
    previous = (
        Snapshot.objects.filter(complete=True, date__lt=snapshot.date)
        .order_by("-date")
        .first()
    )
    if not previous:
        return None
    before = report(previous)
    after = report(snapshot)
    if before["total"] is None or after["total"] is None:
        return {
            "before": previous,
            "after": snapshot,
            "incomplete": True,
            "warnings": list(dict.fromkeys(before["warnings"] + after["warnings"])),
        }
    prior = {r["account"].pk: r for r in before["rows"]}
    current = {r["account"].pk: r for r in after["rows"]}
    details = {key: [] for key in ("investments", "interest", "property", "tax", "residual")}
    for account_id in prior.keys() | current.keys():
        old = prior.get(account_id)
        row = current.get(account_id)
        account = (row or old)["account"]
        opening = old["amount"] if old else 0
        closing = row["amount"] if row else 0
        delta = closing - opening
        item = {
            "account": account,
            "label": account.name,
            "opening": opening if old else None,
            "closing": closing if row else None,
            "opening_date": old["valuation"].snapshot.date if old else None,
            "closing_date": row["valuation"].snapshot.date if row else None,
        }
        matched = (
            old and row
            and old["valuation"].snapshot.date == previous.date
            and row["valuation"].snapshot.date == snapshot.date
        )
        attributed = 0
        reason = _("Balance change after recorded interest; cause not recorded.")
        if not old:
            reason = _("Account newly included; no opening value in this comparison.")
        elif not row:
            reason = _("Account no longer included; no closing value in this comparison.")
        elif not matched:
            reason = _("Observation dates do not match this period; older values are carried forward.")
        elif account.kind == "broker":
            perf = row["performance"]
            if perf and perf["since"] == previous.date:
                attributed = owned(account, perf["result"])
                details["investments"].append({**item, "amount": attributed,
                    "reason": _("Value change minus change in net deposits.")})
                reason = _("Net deposits or withdrawals; these are not investment results.")
            elif old["valuation"].net_deposits_minor is None or row["valuation"].net_deposits_minor is None:
                reason = _("Net deposits unknown at one or both observation dates.")
            else:
                reason = _("Investment observation period does not match this comparison; result remains unexplained.")
        elif account.kind in ("bank", "claim"):
            interest = row["valuation"].interest_minor
            if interest is not None:
                attributed = owned(account, interest)
                details["interest"].append({**item, "amount": attributed,
                    "reason": _("Recorded interest for this period.")})
            else:
                reason = _("No interest recorded; cause of balance change not recorded.")
        elif account.kind == "property":
            attributed = delta
            details["property"].append({**item, "amount": attributed,
                "reason": _("Change in estimated property value.")})
        elif account.kind == "mortgage":
            reason = _("Mortgage balance change, including principal repayments.")
        remainder = delta - attributed
        if remainder or not matched or (account.kind == "broker" and not row["performance"]):
            details["residual"].append({**item, "amount": remainder, "reason": reason})

    # Tax adjustments are snapshot-wide, especially imported corrections. Do not
    # invent an account allocation that cannot be recovered from the stored data.
    for key, label in [
        ("bank_ab", _("AB on bank balances")),
        ("broker_vpb", _("VPB on investment gains")),
        ("broker_ab", _("AB after VPB")),
    ]:
        opening = before["tax"][key]
        closing = after["tax"][key]
        details["tax"].append({
            "label": label, "opening": opening, "closing": closing,
            "amount": closing - opening,
            "reason": _("Portfolio-level tax correction; not allocated to individual accounts."),
        })
    parts = []
    for key, label in [
        ("investments", _("Investment results")),
        ("interest", _("Interest")),
        ("property", _("Property revaluation")),
        ("tax", _("Tax correction change")),
        ("residual", _("Other / unexplained")),
    ]:
        rows = details[key]
        if key != "tax":
            rows = sorted(rows, key=lambda item: (item["label"].lower(), item["account"].pk))
        parts.append({"key": key, "label": label, "amount": sum(r["amount"] for r in rows), "details": rows})
    labels = [p["label"] for p in parts]
    values = [p["amount"] for p in parts]
    return {
        "before": previous,
        "after": snapshot,
        "opening": before["total"],
        "closing": after["total"],
        "parts": parts,
        "chart": {"labels": labels, "values": [v / 100 for v in values],
                  "detail_ids": ["movement-" + p["key"] for p in parts]},
    }
