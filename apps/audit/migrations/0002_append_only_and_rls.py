"""
Make the audit table append-only at the database and apply row-level security.
UPDATE, DELETE and TRUNCATE are refused by trigger for every database role
that is not a superuser; policies decide who may read which events.
"""
from django.db import migrations

from apps.core.db import rls_disable_sql, rls_policy_sql

APPEND_ONLY_SQL = """
CREATE OR REPLACE FUNCTION brite_audit_append_only()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Audit history is append-only: % on audit_auditevent is not permitted', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$;
DROP TRIGGER IF EXISTS audit_auditevent_append_only ON audit_auditevent;
CREATE TRIGGER audit_auditevent_append_only
    BEFORE UPDATE OR DELETE ON audit_auditevent
    FOR EACH ROW EXECUTE FUNCTION brite_audit_append_only();
DROP TRIGGER IF EXISTS audit_auditevent_no_truncate ON audit_auditevent;
CREATE TRIGGER audit_auditevent_no_truncate
    BEFORE TRUNCATE ON audit_auditevent
    FOR EACH STATEMENT EXECUTE FUNCTION brite_audit_append_only();
"""

APPEND_ONLY_REVERSE = """
DROP TRIGGER IF EXISTS audit_auditevent_append_only ON audit_auditevent;
DROP TRIGGER IF EXISTS audit_auditevent_no_truncate ON audit_auditevent;
DROP FUNCTION IF EXISTS brite_audit_append_only();
"""

SELECT_POLICY = (
    "brite_has_capability('audit_history', 'view') "
    "OR (client_id IS NOT NULL AND brite_has_capability('client_operational_data', 'view')) "
    "OR (subject_user_id IS NOT NULL AND subject_user_id = brite_current_user_id())"
)
INSERT_POLICY = "brite_current_user_id() IS NOT NULL OR current_setting('app.bypass_rls', true) = 'on'"


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial"), ("core", "0001_rls_functions")]
    operations = [
        migrations.RunSQL(APPEND_ONLY_SQL, APPEND_ONLY_REVERSE),
        migrations.RunSQL(
            "\n".join(rls_policy_sql("audit_auditevent", select=SELECT_POLICY, insert=INSERT_POLICY)),
            "\n".join(rls_disable_sql("audit_auditevent")),
        ),
    ]
