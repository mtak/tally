from django.contrib import admin
from .models import Entity, Account, Snapshot, Valuation, Position, TaxAdjustment

for model in (Entity, Account, Snapshot, Valuation, Position, TaxAdjustment):
    admin.site.register(model)
