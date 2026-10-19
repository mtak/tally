from django.db import migrations, models


def backfill_net_deposits(apps, schema_editor):
    Valuation = apps.get_model("wealth", "Valuation")
    observations = Valuation.objects.using(schema_editor.connection.alias)
    for value in observations.filter(account__kind="broker").select_related("account__entity", "snapshot").iterator():
        net = None
        if (value.flow_mode == "cumulative" and value.flow_end_date == value.snapshot.date
                and value.cumulative_inflow_minor is not None and value.cumulative_outflow_minor is not None
                and value.cumulative_inflow_minor >= 0 and value.cumulative_outflow_minor >= 0):
            net = value.cumulative_inflow_minor - value.cumulative_outflow_minor
        elif (value.snapshot.imported and value.account.name == "Example Brokerage Value"
                and value.account.entity.name == "Holding" and value.account.entity.kind == "company"
                and value.flow_mode == "period" and value.inflow_minor is None and value.outflow_minor is None):
            # The example importer stores its brokerage contributions row here. The documented
            # layout defines that row as inception net deposits. Do not generalize
            # this mapping to other tax bases or override explicit flow inputs.
            net = value.basis_minor
        if net is not None:
            observations.filter(pk=value.pk).update(net_deposits_minor=net)


class Migration(migrations.Migration):
    dependencies = [("wealth", "0004_valuation_cumulative_baseline_date_and_more")]
    operations = [
        migrations.AddField(model_name="valuation", name="net_deposits_minor",
                            field=models.BigIntegerField(blank=True, null=True)),
        migrations.RunPython(backfill_net_deposits, migrations.RunPython.noop),
    ]
