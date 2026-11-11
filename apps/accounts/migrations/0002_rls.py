"""Row-level security for users, group mapping, defaults, exceptions and owners."""
from django.db import migrations

from apps.core.db import rls_disable_sql, rls_policy_sql

SIGNED_IN = "brite_current_user_id() IS NOT NULL OR current_setting('app.bypass_rls', true) = 'on'"
ADMIN_VIEW = "brite_has_capability('administrative_configuration', 'view')"
ADMIN_EDIT = "brite_has_capability('administrative_configuration', 'edit')"
OWN_USER = "user_id = brite_current_user_id()"
NEVER = "false"

TABLES = [
    ("accounts_user", {"select": SIGNED_IN, "insert": ADMIN_EDIT, "update": f"{ADMIN_EDIT} OR id = brite_current_user_id()", "delete": NEVER}),
    ("accounts_workspacegroupmapping", {"select": SIGNED_IN, "insert": ADMIN_EDIT, "update": ADMIN_EDIT, "delete": NEVER}),
    ("accounts_workspacegroupmembership", {"select": f"{OWN_USER} OR {ADMIN_VIEW}", "insert": ADMIN_EDIT, "update": ADMIN_EDIT, "delete": NEVER}),
    ("accounts_rolecapabilitydefault", {"select": SIGNED_IN, "insert": ADMIN_EDIT, "update": ADMIN_EDIT, "delete": NEVER}),
    ("accounts_individualexception", {"select": f"{OWN_USER} OR {ADMIN_VIEW}", "insert": ADMIN_EDIT, "update": ADMIN_EDIT, "delete": NEVER}),
    ("accounts_systemowner", {"select": SIGNED_IN, "insert": ADMIN_EDIT, "update": ADMIN_EDIT, "delete": NEVER}),
]


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial"), ("core", "0001_rls_functions")]
    operations = [
        migrations.RunSQL(
            "\n".join(stmt for table, spec in TABLES for stmt in rls_policy_sql(table, **spec)),
            "\n".join(stmt for table, _ in TABLES for stmt in rls_disable_sql(table)),
        )
    ]
