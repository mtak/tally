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


def broker_tax_covered(basis, overrides):
    """Snapshot-wide historical deductions can cover unknown broker bases."""
    return basis is not None or {"broker_vpb", "broker_ab"} <= overrides.keys()


def report(snapshot, include_home=True, include_pension=True, net=True):
    accounts = list(
        Account.objects.select_related("entity")
        .filter(Q(closed_on__isnull=True) | Q(closed_on__gt=snapshot.date))
        .filter(Q(started_on__isnull=True) | Q(started_on__lte=snapshot.date))
    )
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
    investments = 0
    interest = 0
    property_change = 0
    for row in after["rows"]:
        account = row["account"]
        v = row["valuation"]
        old = prior.get(account.pk)
        # Only attribute when both observations and the flow interval match this bridge.
        if (
            not old
            or v.snapshot.date != snapshot.date
            or old["valuation"].snapshot.date != previous.date
        ):
            continue
        if (
            account.kind == "broker"
            and row["performance"]
            and row["performance"]["since"] == previous.date
        ):
            investments += owned(account, row["performance"]["result"])
        elif account.kind in ("bank", "claim") and v.interest_minor is not None:
            interest += owned(account, v.interest_minor)
        elif account.kind == "property":
            property_change += row["amount"] - old["amount"]
    tax_change = after["tax_total"] - before["tax_total"]
    change = after["total"] - before["total"]
    residual = change - investments - interest - property_change - tax_change
    parts = [
        (_("Investment results"), investments),
        (_("Interest"), interest),
        (_("Property revaluation"), property_change),
        (_("Tax assumption change"), tax_change),
        (_("Other / unexplained"), residual),
    ]
    labels = [p[0] for p in parts]
    values = [p[1] for p in parts]
    return {
        "before": previous,
        "after": snapshot,
        "opening": before["total"],
        "closing": after["total"],
        "parts": [{"label": label, "amount": amount} for label, amount in parts],
        "chart": {"labels": labels, "values": [v / 100 for v in values]},
    }
