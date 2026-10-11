from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("accounts/", views.accounts, name="accounts"),
    path("accounts/new/", views.account_edit, name="account_add"),
    path("accounts/<int:pk>/", views.account_edit, name="account_edit"),
    path("owners/new/", views.entity_add, name="entity_add"),
    path("valuations/", views.snapshots, name="snapshots"),
    path("valuations/new/", views.snapshot_add, name="snapshot_add"),
    path("valuations/<int:pk>/", views.snapshot_edit, name="snapshot_edit"),
    path(
        "positions/<int:pk>/edit/<int:position_pk>/",
        views.positions,
        name="position_edit",
    ),
    path("positions/<int:pk>/", views.positions, name="positions"),
    path("positions/<int:pk>/delete/", views.position_delete, name="position_delete"),
    path("import/", views.imports, name="imports"),
    path("export/", views.export, name="export"),
    path("analysis/", views.analysis, name="analysis"),
]
