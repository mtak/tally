import csv
from django.core.exceptions import ValidationError
from .validation import validate_balance
from decimal import Decimal
from datetime import date
from django.contrib import messages
from django.core import signing
from .auth import import_history_enabled, portfolio_access_required
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.forms import formset_factory
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST, require_http_methods
from .models import Account, Entity, Snapshot, Valuation, ASSETS
from .forms import (
    AccountForm,
    EntityForm,
    SnapshotForm,
    ValuationForm,
    ImportForm,
    minor,
)
from .services import (
    report,
    reports,
    movement,
    previous_year_baseline,
    cumulative_result,
    broker_tax_covered,
    asset_mix,
    investment_history,
    maturity_calendar,
    valuation_coverage,
)
from .importer import parse_overview, preflight_overview, import_overview
from . import editor


@portfolio_access_required
def dashboard(request):
    snapshots = list(Snapshot.objects.filter(complete=True))
    selected = None
    if snapshots:
        selected = next(
            (s for s in snapshots if str(s.pk) == request.GET.get("at")), snapshots[-1]
        )
    flags = {
        "include_home": request.GET.get("home", "1") != "0",
        "include_pension": request.GET.get("pension", "1") != "0",
        "net": request.GET.get("net", "1") != "0",
    }
    current = None
    chart = {}
    previous = None
    change = None
    mix = []
    annual = {}
    allocation = []
    liquidity = []
    if selected:
        history_snapshots = [s for s in snapshots if s.date <= selected.date]
        annual_snapshots = {}
        for snapshot in history_snapshots:
            annual_snapshots[snapshot.date.year] = snapshot
        previous_snapshot = history_snapshots[-2] if len(history_snapshots) > 1 else None
        targets = list(annual_snapshots.values())
        for snapshot in (previous_snapshot, selected):
            if snapshot and all(existing.pk != snapshot.pk for existing in targets):
                targets.append(snapshot)
        summaries = {
            summary["snapshot"].pk: summary
            for summary in reports(targets, performance_snapshots=(selected,), **flags)
        }
        current = summaries[selected.pk]
        history = [summaries[snapshot.pk] for snapshot in annual_snapshots.values()]
        annual = {summary["snapshot"].date.year: summary for summary in history}
        mix = [asset_mix(r) for r in annual.values()]
        if previous_snapshot:
            previous = summaries[previous_snapshot.pk]
            if current["total"] is not None and previous["total"] is not None:
                change = current["total"] - previous["total"]
        allocation = [
            {"name": str(dict(ASSETS).get(key, key)), "amount": amount}
            for key, amount in current["assets"].items() if amount > 0
        ]
        liquidity = [
            {"name": label, "amount": current["liquidity"][key]}
            for key, label in (("liquid", _("Liquid")), ("illiquid", _("Illiquid")))
        ]
        chart = {
            "dates": [r["snapshot"].date.isoformat() for r in annual.values()],
            "totals": [r["total"] for r in annual.values()],
            "total_label": _("Total wealth"),
            "mix": {
                "dates": [m["snapshot"].date.isoformat() for m in mix],
                "carried_label": _("Carried forward"),
                "unavailable_label": _("No gross assets available"),
                "missing_label": _("Missing observations"),
                "missing": [m["missing"] for m in mix],
                "series": [
                    {
                        "name": str(label),
                        "data": [
                            {
                                "value": m["categories"][index]["percentage"],
                                "amount": m["categories"][index]["amount"],
                                "carried_dates": sorted({
                                    row["valuation"].snapshot.date.isoformat()
                                    for row in m["categories"][index]["observations"]
                                    if row["stale"]
                                }),
                            }
                            for m in mix
                        ],
                    }
                    for index, (key, label) in enumerate(ASSETS)
                ],
            },
            "years": [str(y) for y in annual],
            "series": [
                {
                    "name": label,
                    "data": [
                        r["groups"][key] / 100 if r["total"] is not None else None
                        for r in annual.values()
                    ],
                }
                for key, label in [
                    ("private", _("Private")),
                    ("home", _("Home equity")),
                    ("business", _("Business")),
                    ("pension", _("Pension")),
                ]
            ],
            "assets": [{"name": row["name"], "value": row["amount"] / 100} for row in allocation],
            "liquidity": [{"name": row["name"], "value": row["amount"] / 100} for row in liquidity],
        }
    return render(
        request,
        "wealth/dashboard.html",
        {
            "current": current,
            "snapshots": snapshots,
            "selected": selected,
            "flags": flags,
            "chart": chart,
            "asset_mix": mix,
            "wealth_history": list(annual.values()),
            "allocation": allocation,
            "liquidity": liquidity,
            "previous": previous,
            "change": change,
            "drafts": Snapshot.objects.filter(complete=False),
        },
    )


@portfolio_access_required
def maturities(request):
    snapshots = list(Snapshot.objects.filter(complete=True).order_by("date", "pk"))
    selected = next((s for s in snapshots if str(s.pk) == request.GET.get("at")),
                    snapshots[-1] if snapshots else None)
    calendar = maturity_calendar(selected) if selected else None
    request._maturity_calendar = calendar
    return render(request, "wealth/maturities.html", {
        "snapshots": snapshots, "selected": selected,
        "calendar": calendar,
    })


@portfolio_access_required
def accounts(request):
    return render(
        request,
        "wealth/accounts.html",
        {
            "accounts": Account.objects.select_related("entity").order_by(
                Lower("entity__name"), "entity_id", Lower("name"), "pk"
            ),
            "entities": Entity.objects.all(),
        },
    )


@portfolio_access_required
@require_http_methods(["GET"])
def account_history(request, pk):
    account = get_object_or_404(Account.objects.select_related("entity"), pk=pk)
    return render(request, "wealth/account_history.html", {
        "account": account,
        "observations": account.valuations.select_related("snapshot").order_by("-snapshot__date", "-pk"),
    })


@portfolio_access_required
@transaction.atomic
def account_edit(request, pk=None):
    obj = get_object_or_404(Account, pk=pk) if pk else None
    # ModelForm validation mutates its instance; capture the persisted state first.
    original = dict(Account.objects.filter(pk=pk).values().get()) if obj else None
    form = AccountForm(request.POST if request.method == "POST" else None, instance=obj)
    impacts = []
    confirmation = ""
    if request.method == "POST" and form.is_valid():
        explanations = {
            "entity": _("Owner: changes historical ownership grouping and may change liquidation tax calculations."),
            "kind": _("Account type: changes historical tax treatment, coverage and account detail interpretation."),
            "asset_class": _("Asset class: changes historical allocation categories."),
            "joint": _("Joint ownership: applies 50% instead of 100%, or 100% instead of 50%, to historical reported balances."),
            "liquid": _("Liquid: changes historical liquidity totals."),
            "pension": _("Pension: changes historical pension totals and inclusion filters."),
            "started_on": _("Start date: can include or exclude this account from published valuations and the maturity calendar."),
            "closed_on": _("Closed on: can include or exclude this account from published valuations and the maturity calendar."),
            "matures_on": _("Maturity date: changes the maturity calendar for past valuation dates."),
        }
        if obj and obj.valuations.filter(snapshot__complete=True).exists():
            impacts = [text for name, text in explanations.items() if name in form.changed_data]
        if impacts:
            proposed = form.save(commit=False)
            state = {"original": original, "proposed": {
                field.attname: getattr(proposed, field.attname) for field in Account._meta.fields
            }}
            # Bind approval to both the reviewed values and the persisted configuration.
            state = {key: {name: str(value) for name, value in values.items()}
                     for key, values in state.items()}
            try:
                approved = signing.loads(request.POST.get("history_confirmation", ""), salt="account-history", max_age=3600) == state
            except signing.BadSignature:
                approved = False
            if not approved:
                confirmation = signing.dumps(state, salt="account-history")
        if not impacts or not confirmation:
            form.save()
            messages.success(request, _("Account saved."))
            return redirect("accounts")
    return render(
        request,
        "wealth/form.html",
        {
            "form": form,
            "account": obj,
            "title": _("Edit account") if obj else _("Add account"),
            "history_impacts": impacts, "history_confirmation": confirmation,
            "back": "accounts",
        },
    )


@portfolio_access_required
@require_POST
@transaction.atomic
def account_delete(request, pk):
    account = get_object_or_404(Account.objects.select_for_update(), pk=pk)
    observations = account.valuations.select_for_update().select_related("snapshot").prefetch_related("positions")
    blocked_dates = set()
    financial_fields = (
        "amount_minor", "basis_minor", "net_deposits_minor", "inflow_minor",
        "outflow_minor", "interest_minor", "cumulative_inflow_minor",
        "cumulative_outflow_minor",
    )
    for observation in observations:
        has_value = any(getattr(observation, field) not in (None, 0) for field in financial_fields)
        has_position_value = observation.positions.filter(value_minor__gt=0).exists()
        if has_value or has_position_value:
            blocked_dates.add(observation.snapshot.date)
    if blocked_dates:
        dates = ", ".join(d.strftime("%d-%m-%Y") for d in sorted(blocked_dates))
        messages.error(request, _("This account cannot be deleted because it has non-zero financial data on: %(dates)s.") % {"dates": dates})
        return redirect("account_edit", pk=account.pk)
    # Valuations and positions belong to this account. Snapshots and snapshot-level
    # tax adjustments may be shared by every account, so leave them intact.
    account.valuations.all().delete()
    account.delete()
    messages.success(request, _("Account deleted. Zero-value observations were removed; shared valuation records were preserved."))
    return redirect("accounts")


@portfolio_access_required
def entity_add(request):
    form = EntityForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("accounts")
    return render(
        request,
        "wealth/form.html",
        {"form": form, "title": _("Add owner"), "back": "accounts"},
    )


@portfolio_access_required
def snapshots(request):
    return render(
        request,
        "wealth/snapshots.html",
        {"snapshots": Snapshot.objects.order_by("-date")},
    )


@portfolio_access_required
def snapshot_add(request):
    form = SnapshotForm(request.POST or None, initial={"date": date.today()})
    if request.method == "POST" and form.is_valid():
        s = form.save()
        return redirect("snapshot_edit", pk=s.pk)
    return render(
        request,
        "wealth/form.html",
        {"form": form, "title": _("New valuation"), "back": "snapshots"},
    )


@portfolio_access_required
@require_http_methods(["GET", "POST"])
def snapshot_delete(request, pk):
    # Recheck draft status at submission, in the same transaction as deletion.
    with transaction.atomic():
        snapshot = get_object_or_404(Snapshot, pk=pk, complete=False)
        if request.method == "POST":
            snapshot.delete()
            messages.success(request, _("Draft deleted."))
            return redirect("snapshots")
    return render(request, "wealth/snapshot_delete.html", {"snapshot": snapshot})


@portfolio_access_required
@transaction.atomic
def snapshot_edit(request, pk):
    # SQLite IMMEDIATE transactions serialize this check with all other writers.
    token = request.POST.get("editor_version", "")
    submitted = editor.read_token(token) if request.method == "POST" else None
    s = Snapshot.objects.filter(pk=pk).first()
    deleted = s is None
    if deleted:
        if not submitted or submitted.get("pk") != pk:
            return get_object_or_404(Snapshot, pk=pk)
        s = Snapshot(pk=pk, date=date.fromisoformat(submitted["date"]))
    digest = None if deleted else editor.version(s)
    conflict = request.method == "POST" and (
        not submitted or submitted.get("pk") != pk
        or submitted.get("version") != digest or deleted
    )
    action = request.POST.get("action")
    editor_error = None
    unsafe_layout = False
    if request.method == "POST" and action not in {"draft", "complete"}:
        editor_error = _("Invalid valuation action.")
    accounts = list(
        Account.objects.select_related("entity")
        .filter(Q(closed_on__isnull=True) | Q(closed_on__gt=s.date))
        .filter(Q(started_on__isnull=True) | Q(started_on__lte=s.date))
        .order_by(Lower("entity__name"), "entity_id", Lower("name"), "pk")
    )
    if request.method != "POST":
        token = editor.make_token(s, digest, accounts)
    elif conflict and submitted and submitted.get("pk") == pk:
        accounts = editor.original_accounts(submitted)
    existing = {v.account_id: v for v in s.valuations.all()}
    prior = {}
    for v in (
        Valuation.objects.filter(snapshot__complete=True, snapshot__date__lt=s.date)
        .select_related("snapshot")
        .order_by("snapshot__date")
    ):
        prior[v.account_id] = v
    initial = []
    for a in accounts:
        v = existing.get(a.pk)
        row = {"account_id": a.pk}
        if v:
            for field, key in [
                ("amount_minor", "amount"),
                ("basis_minor", "basis"),
                ("net_deposits_minor", "net_deposits"),
                ("interest_minor", "interest"),
            ]:
                amount = getattr(v, field)
                row[key] = None if amount is None else Decimal(amount) / 100
            row["interest_period_start"] = v.interest_period_start
            row["interest_period_end"] = v.interest_period_end
        initial.append(row)
    FormSet = formset_factory(ValuationForm, extra=0, max_num=500, validate_max=True)
    formset = FormSet(request.POST if request.method == "POST" else None,
                      initial=initial, form_kwargs={"show_cents": request.show_cents, "snapshot_date": s.date})
    if request.method == "POST":
        # Validate identity/order before pairing bound inputs with account labels or
        # enabling type-specific fields. Never relabel an untrusted row's values.
        management = formset.management_form
        if not management.is_valid() or any(
            management.cleaned_data[key] != len(accounts)
            for key in ("TOTAL_FORMS", "INITIAL_FORMS")
        ):
            editor_error = _("Invalid valuation form. Reload the valuation and try again.")
            unsafe_layout = True
        else:
            ids = [request.POST.get(f"form-{i}-account_id") for i in range(len(accounts))]
            expected = [str(a.pk) for a in accounts]
            if len(set(ids)) != len(ids) or set(ids) != set(expected):
                editor_error = _("Invalid accounts. Reload the valuation and try again.")
                unsafe_layout = True
            elif ids != expected:
                editor_error = _("Invalid account order. Reload the valuation and try again.")
                unsafe_layout = True
        if unsafe_layout:
            formset = FormSet(initial=initial, form_kwargs={"show_cents": request.show_cents, "snapshot_date": s.date})
    for form, account in zip(formset, accounts):
        if account.kind != "broker":
            form.fields["net_deposits"].disabled = True
        if account.kind != "broker" or account.entity.kind != "company":
            form.fields["basis"].disabled = True
        if account.kind not in ("bank", "claim"):
            form.fields["interest"].disabled = True
            form.fields["interest_period_start"].disabled = True
            form.fields["interest_period_end"].disabled = True
    if request.method == "POST" and not conflict and not editor_error and formset.is_valid():
        valid = True
        overrides = {t.kind: t.amount_minor for t in s.tax_adjustments.all()}
        for form, a in zip(formset, accounts):
            data = form.cleaned_data
            value = data.get("amount")
            try:
                validate_balance(a.kind, a.asset_class, value)
            except ValidationError as exc:
                form.add_error("amount", exc)
                valid = False
            if (
                (s.complete or action == "complete")
                and a.entity.kind == "company"
                and a.kind == "broker"
                and (value is not None or a.pk in prior)
                and not broker_tax_covered(
                    data.get("basis") if value is not None else prior[a.pk].basis_minor,
                    overrides,
                )
            ):
                form.add_error(
                    "basis",
                    _("Enter a tax basis before publishing this company account.")
                    if value is not None
                    else _("The carried-forward company account has no tax basis. Enter its value and tax basis before publishing."),
                )
                valid = False
            if (
                value is None
                and existing.get(a.pk)
                and existing[a.pk].positions.exists()
            ):
                form.add_error(
                    "amount", _("Keep this account value to preserve its archived position data.")
                )
                valid = False
        if valid:
            with transaction.atomic():
                for f in formset:
                    d = f.cleaned_data
                    if d["amount"] is None:
                        s.valuations.filter(account_id=d["account_id"]).delete()
                    else:
                        broker = next(a for a in accounts if a.pk == d["account_id"]).kind == "broker"
                        flow_defaults = {"net_deposits_minor": minor(d["net_deposits"])} if broker else {}
                        Valuation.objects.update_or_create(
                            snapshot=s,
                            account_id=d["account_id"],
                            defaults={
                                "amount_minor": minor(d["amount"]),
                                "basis_minor": minor(d["basis"]),
                                **flow_defaults,
                                "interest_minor": minor(d["interest"]),
                                "interest_period_start": d["interest_period_start"],
                                "interest_period_end": d["interest_period_end"],
                            },
                        )
                # Publishing is one-way in the ordinary editor. A stale draft
                # submission must never demote history published in another tab.
                if action == "complete":
                    Snapshot.objects.filter(pk=s.pk).update(complete=True)
                s.refresh_from_db(fields=["complete"])
            messages.success(
                request, _("Valuation published.") if s.complete else _("Draft saved.")
            )
            return redirect("snapshot_edit", pk=s.pk)
    entries = [
        {
            "account": a,
            "form": f,
            "previous": prior.get(a.pk),
            "valuation": existing.get(a.pk),
            "cumulative_result": cumulative_result(existing.get(a.pk)),
        }
        for a, f in zip(accounts, formset)
    ]
    return render(
        request,
        "wealth/snapshot_edit.html",
        {"snapshot": s, "formset": formset, "entries": entries,
         "summary": report(s) if not deleted else None,
         "editor_version": token, "conflict": conflict, "deleted": deleted,
         "editor_error": editor_error, "unsafe_layout": unsafe_layout,
         "unsaved_inputs": request.method == "POST" and not unsafe_layout},
        status=400 if editor_error else 409 if conflict else 200,
    )


@import_history_enabled
@portfolio_access_required
def imports(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    preview = None
    if request.method == "POST" and form.is_valid():
        try:
            preview = preflight_overview(parse_overview(form.cleaned_data["file"].read()))
            if form.cleaned_data["confirm"]:
                count = import_overview(preview)
                messages.success(
                    request, _("Historical observations imported: ") + str(count)
                )
                return redirect("dashboard")
        except ValueError as exc:
            form.add_error(None, str(exc))
    return render(request, "wealth/import.html", {"form": form, "preview": preview})


@portfolio_access_required
def export(request):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="tally-valuations.csv"'
    writer = csv.writer(response)
    writer.writerow(
        [
            "date",
            "status",
            "account",
            "owner",
            "currency",
            "value_eur",
            "tax_basis_eur",
            "deposits_eur",
            "withdrawals_eur",
            "ownership",
            "flow_mode", "flow_start_date", "flow_end_date",
            "cumulative_deposits_eur", "cumulative_withdrawals_eur",
            "cumulative_start_date", "cumulative_baseline_date",
            "net_deposits_eur", "interest_eur", "interest_period_start", "interest_period_end",
        ]
    )

    def safe(value):
        text = str(value)
        return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text

    for v in Valuation.objects.select_related("snapshot", "account__entity").order_by(
        "snapshot__date", "account_id"
    ):
        vals = [
            "" if getattr(v, k) is None else str(Decimal(getattr(v, k)) / 100)
            for k in ["amount_minor", "basis_minor", "inflow_minor", "outflow_minor"]
        ]
        writer.writerow(
            [
                v.snapshot.date,
                "published" if v.snapshot.complete else "draft",
                safe(v.account.name),
                safe(v.account.entity.name),
                "EUR",
                *vals,
                "0.5" if v.account.joint else "1",
                v.flow_mode, v.flow_start_date or "", v.flow_end_date or "",
                "" if v.cumulative_inflow_minor is None else str(Decimal(v.cumulative_inflow_minor) / 100),
                "" if v.cumulative_outflow_minor is None else str(Decimal(v.cumulative_outflow_minor) / 100),
                v.cumulative_start_date or "", v.cumulative_baseline_date or "",
                "" if v.net_deposits_minor is None else str(Decimal(v.net_deposits_minor) / 100),
                "" if v.interest_minor is None else str(Decimal(v.interest_minor) / 100),
                v.interest_period_start or "", v.interest_period_end or "",
            ]
        )
    return response


@portfolio_access_required
def analysis(request):
    completed = list(Snapshot.objects.filter(complete=True))
    selected = next(
        (s for s in completed if str(s.pk) == request.GET.get("at")),
        completed[-1] if completed else None,
    )
    summary = report(selected) if selected else None
    investment_accounts = list(Account.objects.filter(kind="broker").select_related("entity"))
    selected_account = next(
        (a for a in investment_accounts if str(a.pk) == request.GET.get("account")),
        investment_accounts[0] if investment_accounts else None,
    )
    history = investment_history(selected_account, selected.date) if selected and selected_account else None
    coverage = valuation_coverage(
        [snapshot for snapshot in completed if selected and snapshot.date <= selected.date]
    )
    year_baseline = previous_year_baseline(selected) if selected else None
    results = []
    if summary:
        for row in summary["rows"]:
            if row["account"].kind == "broker":
                results.append(
                    {
                        "name": row["account"].name,
                        "date": row["valuation"].snapshot.date,
                        "amount": row["valuation"].amount_minor,
                        "net_deposits": row["valuation"].net_deposits_minor,
                        "cumulative_result": row["cumulative_result"],
                    }
                )
    return render(
        request,
        "wealth/analysis.html",
        {
            "snapshots": completed,
            "selected": selected,
            "results": results,
            "investment_accounts": investment_accounts,
            "selected_account": selected_account,
            "investment_history": history,
            "valuation_coverage": coverage,
            "summary": summary,
            "movement": movement(selected) if selected else None,
            "year_baseline": year_baseline,
            "year_movement": movement(selected, year_baseline, require_complete=True, detail_prefix="year-movement") if year_baseline else None,
        },
    )
