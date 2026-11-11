from django.db import migrations

from apps.core.db import rls_disable_sql, rls_policy_sql

VIEW = "brite_has_capability('administrative_configuration', 'view') OR (client_id IS NOT NULL AND brite_has_capability('client_operational_data', 'view'))"
EDIT = "brite_has_capability('administrative_configuration', 'edit') OR (client_id IS NOT NULL AND brite_has_capability('client_operational_data', 'edit'))"


class Migration(migrations.Migration):
    dependencies = [("drive", "0001_initial"), ("core", "0001_rls_functions")]
    operations = [
        migrations.RunSQL(
            "\n".join(rls_policy_sql("drive_drivefolder", select=VIEW, insert=EDIT, update=EDIT, delete="false")),
            "\n".join(rls_disable_sql("drive_drivefolder")),
        )
    ]
