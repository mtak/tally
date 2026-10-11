import csv
from decimal import Decimal
from datetime import date
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.forms import formset_factory
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from .models import Account, Entity, Snapshot, Valuation, Position, ASSETS
from .forms import (
    AccountForm,
    EntityForm,
    SnapshotForm,
    ValuationForm,
    PositionForm,
    ImportForm,
    minor,
)
from .services import report, performance, movement
from .importer import parse_overview, import_overview


@login_required
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
    current = report(selected, **flags) if selected else None
    chart = {}
    previous = None
    change = None
    if current:
        history = [report(s, **flags) for s in snapshots if s.date <= selected.date]
        annual = {}
        for r in history:
            annual[r["snapshot"].date.year] = r
        if len(history) > 1:
            previous = history[-2]
            change = current["total"] - previous["total"]
        chart = {
            "years": [str(y) for y in annual],
            "series": [
                {
                    "name": label,
                    "data": [r["groups"][key] / 100 for r in annual.values()],
                }
                for key, label in [
                    ("private", _("Private")),
                    ("home", _("Home equity")),
                    ("business", _("Business")),
                    ("pension", _("Pension")),
                ]
            ],
            "assets": [
                {"name": str(dict(ASSETS).get(k, k)), "value": v / 100}
                for k, v in current["assets"].items()
                if v > 0
            ],
            "liquidity": [
                {"name": _("Liquid"), "value": current["liquidity"]["liquid"] / 100},
                {
                    "name": _("Illiquid"),
                    "value": current["liquidity"]["illiquid"] / 100,
                },
            ],
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
            "previous": previous,
            "change": change,
            "drafts": Snapshot.objects.filter(complete=False),
        },
    )


@login_required
def accounts(request):
    return render(
        request,
        "wealth/accounts.html",
        {
            "accounts": Account.objects.select_related("entity").all(),
            "entities": Entity.objects.all(),
        },
    )


@login_required
def account_edit(request, pk=None):
    obj = get_object_or_404(Account, pk=pk) if pk else None
    form = AccountForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Account saved."))
        return redirect("accounts")
    return render(
        request,
        "wealth/form.html",
        {
            "form": form,
            "title": _("Edit account") if obj else _("Add account"),
            "back": "accounts",
        },
    )


@login_required
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


@login_required
def snapshots(request):
    return render(
        request,
        "wealth/snapshots.html",
        {"snapshots": Snapshot.objects.order_by("-date")},
    )


@login_required
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


@login_required
def snapshot_edit(request, pk):
    s = get_object_or_404(Snapshot, pk=pk)
    accounts = list(
        Account.objects.select_related("entity")
        .filter(Q(closed_on__isnull=True) | Q(closed_on__gt=s.date))
        .filter(Q(started_on__isnull=True) | Q(started_on__lte=s.date))
    )
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
                ("inflow_minor", "inflow"),
                ("outflow_minor", "outflow"),
                ("interest_minor", "interest"),
            ]:
                amount = getattr(v, field)
                row[key] = None if amount is None else Decimal(amount) / 100
        initial.append(row)
    FormSet = formset_factory(ValuationForm, extra=0, max_num=500, validate_max=True)
    formset = FormSet(request.POST or None, initial=initial)
    if request.method == "POST" and formset.is_valid():
        ids = [f.cleaned_data.get("account_id") for f in formset]
        if len(ids) != len(set(ids)) or set(ids) != {a.pk for a in accounts}:
            return HttpResponseBadRequest("Invalid accounts")
        valid = True
        for form, a in zip(formset, accounts):
            if form.cleaned_data["account_id"] != a.pk:
                return HttpResponseBadRequest("Invalid order")
            value = form.cleaned_data.get("amount")
            if value is not None and (
                (a.kind == "mortgage" and value > 0)
                or (a.kind != "mortgage" and value < 0)
            ):
                form.add_error(
                    "amount",
                    _(
                        "Use a negative balance for a mortgage and a nonnegative balance for assets."
                    ),
                )
                valid = False
            if (
                request.POST.get("action") == "complete"
                and not s.imported
                and a.entity.kind == "company"
                and a.kind == "broker"
                and value is not None
                and form.cleaned_data.get("basis") is None
            ):
                form.add_error(
                    "basis",
                    _("Enter a tax basis before publishing this company account."),
                )
                valid = False
            if (
                value is None
                and existing.get(a.pk)
                and existing[a.pk].positions.exists()
            ):
                form.add_error(
                    "amount", _("Remove the positions before clearing this value.")
                )
                valid = False
        if valid:
            with transaction.atomic():
                for f in formset:
                    d = f.cleaned_data
                    if d["amount"] is None:
                        s.valuations.filter(account_id=d["account_id"]).delete()
                    else:
                        Valuation.objects.update_or_create(
                            snapshot=s,
                            account_id=d["account_id"],
                            defaults={
                                "amount_minor": minor(d["amount"]),
                                "basis_minor": minor(d["basis"]),
                                "inflow_minor": minor(d["inflow"]),
                                "outflow_minor": minor(d["outflow"]),
                                "interest_minor": minor(d["interest"]),
                            },
                        )
                s.complete = request.POST.get("action") == "complete"
                s.save(update_fields=["complete"])
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
        }
        for a, f in zip(accounts, formset)
    ]
    return render(
        request,
        "wealth/snapshot_edit.html",
        {"snapshot": s, "formset": formset, "entries": entries, "summary": report(s)},
    )


@login_required
def positions(request, pk, position_pk=None):
    v = get_object_or_404(
        Valuation.objects.select_related("account", "snapshot"),
        pk=pk,
        account__kind="broker",
    )
    position = (
        get_object_or_404(Position, pk=position_pk, valuation=v)
        if position_pk
        else None
    )
    initial = {"value": Decimal(position.value_minor) / 100} if position else None
    form = PositionForm(request.POST or None, instance=position, initial=initial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(False)
        obj.valuation = v
        obj.save()
        return redirect("positions", pk=v.pk)
    positions = list(v.positions.all())
    return render(
        request,
        "wealth/positions.html",
        {
            "valuation": v,
            "positions": positions,
            "form": form,
            "difference": v.amount_minor - sum(p.value_minor for p in positions),
            "editing": bool(position),
        },
    )


@login_required
@require_POST
def position_delete(request, pk):
    p = get_object_or_404(Position, pk=pk)
    v = p.valuation_id
    p.delete()
    return redirect("positions", pk=v)


@login_required
def imports(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    preview = None
    if request.method == "POST" and form.is_valid():
        try:
            preview = parse_overview(form.cleaned_data["file"].read())
            if form.cleaned_data["confirm"]:
                count = import_overview(preview)
                messages.success(
                    request, _("Historical observations imported: ") + str(count)
                )
                return redirect("dashboard")
        except ValueError as exc:
            form.add_error(None, str(exc))
    return render(request, "wealth/import.html", {"form": form, "preview": preview})


@login_required
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
            ]
        )
    return response


@login_required
def analysis(request):
    completed = list(Snapshot.objects.filter(complete=True))
    selected = next(
        (s for s in completed if str(s.pk) == request.GET.get("at")),
        completed[-1] if completed else None,
    )
    summary = report(selected) if selected else None
    results = []
    if summary:
        for row in summary["rows"]:
            if row["account"].kind == "broker":
                results.append(
                    {
                        "name": row["account"].name,
                        "date": row["valuation"].snapshot.date,
                        "performance": row["performance"],
                    }
                )
    return render(
        request,
        "wealth/analysis.html",
        {
            "snapshots": completed,
            "selected": selected,
            "results": results,
            "summary": summary,
            "movement": movement(selected) if selected else None,
        },
    )
