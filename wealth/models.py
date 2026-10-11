from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _

ASSETS = [
    ("cash", _("Cash")),
    ("deposit", _("Term deposits")),
    ("equities", _("Equities")),
    ("bonds", _("Bonds")),
    ("property", _("Real estate")),
    ("loan", _("Loans")),
    ("other", _("Other")),
]
KINDS = [
    ("bank", _("Bank account")),
    ("broker", _("Investment account")),
    ("claim", _("Interest-bearing claim")),
    ("property", _("Property")),
    ("mortgage", _("Mortgage")),
]


class Entity(models.Model):
    name = models.CharField(_("Name"), max_length=120, unique=True)
    kind = models.CharField(
        _("Owner type"),
        max_length=12,
        choices=[
            ("private", _("Private")),
            ("sole", _("Sole proprietorship")),
            ("company", _("Company")),
        ],
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        verbose_name=_("Parent company"),
    )

    def __str__(self):
        return self.name


class Account(models.Model):
    name = models.CharField(_("Name"), max_length=160, unique=True)
    entity = models.ForeignKey(
        Entity, on_delete=models.PROTECT, verbose_name=_("Owner")
    )
    kind = models.CharField(
        _("Account type"), max_length=12, choices=KINDS, default="bank"
    )
    asset_class = models.CharField(
        _("Asset class"), max_length=12, choices=ASSETS, default="cash"
    )
    liquid = models.BooleanField(_("Liquid"), default=True)
    pension = models.BooleanField(_("Pension"), default=False)
    joint = models.BooleanField(_("Joint account (50%)"), default=False)
    currency = models.CharField(_("Currency"), max_length=3, default="EUR")
    closed_on = models.DateField(_("Closed on"), null=True, blank=True)
    rate_bps = models.PositiveIntegerField(default=0)
    started_on = models.DateField(_("Start date"), null=True, blank=True)
    matures_on = models.DateField(_("Maturity date"), null=True, blank=True)
    notes = models.TextField(_("Notes"), blank=True)

    class Meta:
        ordering = ["entity_id", "id"]

    def __str__(self):
        return self.name


class Snapshot(models.Model):
    date = models.DateField(_("Valuation date"), unique=True)
    complete = models.BooleanField(default=False)
    ab_bps = models.PositiveIntegerField(
        default=2690, validators=[MaxValueValidator(10000)]
    )
    vpb_bps = models.PositiveIntegerField(
        default=1900, validators=[MaxValueValidator(10000)]
    )
    notes = models.TextField(_("Notes"), blank=True)
    imported = models.BooleanField(default=False)
    source_total_minor = models.BigIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["date"]

    def __str__(self):
        return str(self.date)


class Valuation(models.Model):
    snapshot = models.ForeignKey(
        Snapshot, on_delete=models.CASCADE, related_name="valuations"
    )
    account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="valuations"
    )
    amount_minor = models.BigIntegerField()
    basis_minor = models.BigIntegerField(null=True, blank=True)
    net_deposits_minor = models.BigIntegerField(null=True, blank=True)
    inflow_minor = models.BigIntegerField(
        null=True, blank=True, validators=[MinValueValidator(0)]
    )
    outflow_minor = models.BigIntegerField(
        null=True, blank=True, validators=[MinValueValidator(0)]
    )
    interest_minor = models.BigIntegerField(null=True, blank=True)
    flow_mode = models.CharField(max_length=12, default="period", choices=[
        ("period", _("Period totals")), ("cumulative", _("Cumulative totals")),
    ])
    flow_start_date = models.DateField(null=True, blank=True)
    flow_end_date = models.DateField(null=True, blank=True)
    cumulative_inflow_minor = models.BigIntegerField(null=True, blank=True, validators=[MinValueValidator(0)])
    cumulative_outflow_minor = models.BigIntegerField(null=True, blank=True, validators=[MinValueValidator(0)])
    cumulative_start_date = models.DateField(null=True, blank=True)
    cumulative_baseline_date = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "account"], name="unique_account_snapshot"
            )
        ]

    def __str__(self):
        return f"{self.account} — {self.snapshot}"


class Position(models.Model):
    valuation = models.ForeignKey(
        Valuation, on_delete=models.CASCADE, related_name="positions"
    )
    name = models.CharField(_("Name"), max_length=160)
    asset_class = models.CharField(
        _("Asset class"), max_length=12, choices=ASSETS, default="equities"
    )
    value_minor = models.BigIntegerField(validators=[MinValueValidator(0)])
    isin = models.CharField("ISIN", max_length=12, blank=True)
    ticker = models.CharField(_("Ticker"), max_length=32, blank=True)
    exchange = models.CharField(_("Exchange"), max_length=40, blank=True)
    currency = models.CharField(_("Currency"), max_length=3, default="EUR")
    # Exact decimal strings, never SQLite REAL. Optional future quote inputs.
    quantity = models.CharField(max_length=40, blank=True)
    price = models.CharField(max_length=40, blank=True)
    price_source = models.CharField(max_length=120, blank=True)
    priced_at = models.DateTimeField(null=True, blank=True)


class TaxAdjustment(models.Model):
    snapshot = models.ForeignKey(
        Snapshot, on_delete=models.CASCADE, related_name="tax_adjustments"
    )
    kind = models.CharField(
        max_length=16,
        choices=[
            ("bank_ab", "Bank AB"),
            ("broker_vpb", "Broker VPB"),
            ("broker_ab", "Broker AB"),
        ],
    )
    amount_minor = models.BigIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "kind"], name="unique_snapshot_tax"
            )
        ]


class ImportRecord(models.Model):
    digest = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    warnings = models.JSONField(default=list)
