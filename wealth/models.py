from django.db import models, transaction
from django.core.exceptions import ValidationError
from .validation import validate_account, validate_balance, validate_minor
from django.db.models.functions import Lower
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _

ASSETS = [
    ("cash", _("Cash")),
    ("credit_card", _("Credit card")),
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


class FinancialQuerySet(models.QuerySet):
    """Validate ORM writes, including paths that normally bypass Model.save()."""
    @transaction.atomic
    def update(self, **kwargs):
        objects = list(self.select_for_update())
        for obj in objects:
            for key, value in kwargs.items():
                if hasattr(value, 'resolve_expression'):
                    raise ValidationError(_("Financial updates require explicit values."))
                setattr(obj, key, value)
            obj.save(update_fields=list(kwargs))
        return len(objects)

    @transaction.atomic
    def bulk_create(self, objs, **kwargs):
        objs = list(objs)
        if kwargs.get('ignore_conflicts') or kwargs.get('update_conflicts'):
            raise ValidationError(_("Financial writes cannot ignore or overwrite conflicts."))
        for obj in objs:
            obj.full_clean()
        return super().bulk_create(objs, **kwargs)

    @transaction.atomic
    def bulk_update(self, objs, fields, **kwargs):
        objs = list(objs)
        for obj in objs:
            obj.save(update_fields=fields)
        return len(objs)


class FinancialModel(models.Model):
    objects = FinancialQuerySet.as_manager()

    class Meta:
        abstract = True

    def clean_fields(self, exclude=None):
        errors = {}
        for field in self._meta.fields:
            if isinstance(field, models.BigIntegerField) and field.name not in (exclude or ()):
                try:
                    validate_minor(getattr(self, field.name))
                except ValidationError as exc:
                    errors[field.name] = exc.messages
        if errors:
            raise ValidationError(errors)
        super().clean_fields(exclude=exclude)

    @transaction.atomic
    def save(self, *args, **kwargs):
        # Validate before Django's integer fields can coerce fractional inputs.
        # A partial update must validate the record that will actually persist,
        # rather than unrelated unsaved attributes on the caller's instance.
        candidate = self
        fields = kwargs.get('update_fields')
        if fields is not None and self.pk:
            candidate = type(self).objects.get(pk=self.pk)
            for name in fields:
                field = self._meta.get_field(name)
                setattr(candidate, field.attname, getattr(self, field.attname))
        for field in candidate._meta.fields:
            if field.is_relation and field.is_cached(candidate):
                field.delete_cached_value(candidate)
        candidate.full_clean()
        if candidate is not self:
            return super(FinancialModel, candidate).save(*args, **kwargs)
        return super().save(*args, **kwargs)


class Entity(FinancialModel):
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

    def clean(self):
        super().clean()
        if self.pk and self.kind != 'private' and self.account_set.filter(joint=True).exists():
            raise ValidationError({'kind': _("Only a private bank account can be shared.")})

    def __str__(self):
        return self.name


class Account(FinancialModel):
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

    def clean(self):
        super().clean()
        owner_kind = Entity.objects.filter(pk=self.entity_id).values_list("kind", flat=True).first()
        validate_account(self, owner_kind)
        if self.pk:
            for value in self.valuations.values_list('amount_minor', flat=True):
                try:
                    validate_balance(self.kind, self.asset_class, value)
                except ValidationError as exc:
                    raise ValidationError({'kind': exc.messages}) from exc

    class Meta:
        ordering = [Lower("name"), "pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(joint=False) | models.Q(kind='bank'), name='joint_bank_only'),
            models.CheckConstraint(condition=models.Q(closed_on__gte=models.F('started_on')) | models.Q(closed_on=None) | models.Q(started_on=None), name='account_closure_order'),
            models.CheckConstraint(condition=models.Q(matures_on__gte=models.F('started_on')) | models.Q(matures_on=None) | models.Q(started_on=None), name='account_maturity_order'),
        ]

    def __str__(self):
        return self.name


class Snapshot(FinancialModel):
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
        constraints = [
            models.CheckConstraint(condition=models.Q(ab_bps__gte=0, ab_bps__lte=10000), name='snapshot_ab_range'),
            models.CheckConstraint(condition=models.Q(vpb_bps__gte=0, vpb_bps__lte=10000), name='snapshot_vpb_range'),
        ]

    def __str__(self):
        return str(self.date)


class Valuation(FinancialModel):
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

    def clean(self):
        super().clean()
        account = Account.objects.filter(pk=self.account_id).first() if self.account_id else None
        if account:
            try:
                validate_balance(account.kind, account.asset_class, self.amount_minor)
            except ValidationError as exc:
                raise ValidationError({'amount_minor': exc.messages}) from exc

    def __str__(self):
        return f"{self.account} — {self.snapshot}"


class Position(FinancialModel):
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


class TaxAdjustment(FinancialModel):
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
