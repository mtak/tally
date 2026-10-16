from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("preferences/money/", views.money_preference, name="money_preference"),
    path("accounts/", views.accounts, name="accounts"),
    path("accounts/new/", views.account_edit, name="account_add"),
    path("accounts/<int:pk>/", views.account_edit, name="account_edit"),
    path("accounts/<int:pk>/history/", views.account_history, name="account_history"),
    path("owners/new/", views.entity_add, name="entity_add"),
    path("valuations/", views.snapshots, name="snapshots"),
    path("valuations/new/", views.snapshot_add, name="snapshot_add"),
    path("valuations/<int:pk>/", views.snapshot_edit, name="snapshot_edit"),
    path("valuations/<int:pk>/delete/", views.snapshot_delete, name="snapshot_delete"),
    path("import/", views.imports, name="imports"),
    path("export/", views.export, name="export"),
    path("analysis/", views.analysis, name="analysis"),
    path("maturities/", views.maturities, name="maturities"),
]
