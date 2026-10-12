"""Signed saved-state checks for valuation forms (not full revision history)."""
import hashlib
import json

from django.core import signing
from django.core.serializers.json import DjangoJSONEncoder

from .models import Account, Entity, Snapshot

SALT = "valuation-editor"


def version(snapshot):
    state = {
        "snapshot": Snapshot.objects.filter(pk=snapshot.pk).values().get(),
        "valuations": list(snapshot.valuations.order_by("pk").values()),
        "positions": list(snapshot.valuations.order_by("pk").values(
            "pk", "positions__pk", "positions__value_minor")),
        "tax": list(snapshot.tax_adjustments.order_by("pk").values()),
        "accounts": list(Account.objects.order_by("pk").values(
            "id", "name", "entity_id", "entity__name", "entity__kind", "kind", "joint",
            "asset_class", "liquid", "pension", "currency", "started_on", "closed_on")),
    }
    encoded = json.dumps(state, cls=DjangoJSONEncoder, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def read_token(token):
    try:
        return signing.loads(token, salt=SALT)
    except signing.BadSignature:
        return None


def make_token(snapshot, digest, accounts):
    # Send the digest and original row labels/configuration, never financial values.
    return signing.dumps({
        "pk": snapshot.pk, "date": snapshot.date.isoformat(), "version": digest,
        "accounts": [{"pk": a.pk, "name": a.name, "kind": a.kind, "joint": a.joint,
                      "asset_class": a.asset_class, "entity_name": a.entity.name,
                      "entity_kind": a.entity.kind} for a in accounts],
    }, salt=SALT)


def original_accounts(payload):
    # Preserve submitted rows even when accounts were added, removed or reclassified.
    return [Account(
        pk=a["pk"], name=a["name"], kind=a["kind"], joint=a["joint"],
        asset_class=a["asset_class"],
        entity=Entity(name=a["entity_name"], kind=a["entity_kind"]),
    ) for a in payload["accounts"]]
