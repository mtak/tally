from django.contrib import admin
from .models import Entity, Account, Snapshot, Valuation, TaxAdjustment

for model in (Entity, Account, Snapshot, Valuation, TaxAdjustment):
    admin.site.register(model)
