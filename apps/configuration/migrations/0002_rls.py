from django.db import migrations

from apps.core.db import rls_disable_sql, rls_policy_sql

SIGNED_IN = "brite_current_user_id() IS NOT NULL OR current_setting('app.bypass_rls', true) = 'on'"
ADMIN_EDIT = "brite_has_capability('administrative_configuration', 'edit')"
TABLES = ["configuration_statusset", "configuration_statusoption"]


class Migration(migrations.Migration):
    dependencies = [("configuration", "0001_initial"), ("core", "0001_rls_functions")]
    operations = [
        migrations.RunSQL(
            "\n".join(stmt for t in TABLES for stmt in rls_policy_sql(t, select=SIGNED_IN, insert=ADMIN_EDIT, update=ADMIN_EDIT, delete="false")),
            "\n".join(stmt for t in TABLES for stmt in rls_disable_sql(t)),
        )
    ]
