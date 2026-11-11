"""
Permanent Client ID sequence, database-level read-only enforcement for closed
episodes, and row-level security on the client domain.
"""
from django.db import migrations

from apps.core.db import rls_disable_sql, rls_policy_sql

SEQUENCE_SQL = "CREATE SEQUENCE IF NOT EXISTS client_system_id_seq START WITH 1 INCREMENT BY 1 NO CYCLE;"
SEQUENCE_REVERSE = "DROP SEQUENCE IF EXISTS client_system_id_seq;"

READONLY_SQL = """
CREATE OR REPLACE FUNCTION brite_episode_readonly_guard()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.state = 'closed' THEN
        RAISE EXCEPTION 'Episode % is closed and read-only for active work', OLD.number USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS clients_serviceepisode_readonly ON clients_serviceepisode;
CREATE TRIGGER clients_serviceepisode_readonly
    BEFORE UPDATE OR DELETE ON clients_serviceepisode
    FOR EACH ROW EXECUTE FUNCTION brite_episode_readonly_guard();

CREATE OR REPLACE FUNCTION brite_workstream_readonly_guard()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE episode_state text;
BEGIN
    SELECT state INTO episode_state FROM clients_serviceepisode WHERE id = COALESCE(NEW.episode_id, OLD.episode_id);
    IF episode_state = 'closed' THEN
        RAISE EXCEPTION 'The episode is closed and its workstreams are read-only' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS clients_workstream_readonly ON clients_workstream;
CREATE TRIGGER clients_workstream_readonly
    BEFORE INSERT OR UPDATE OR DELETE ON clients_workstream
    FOR EACH ROW EXECUTE FUNCTION brite_workstream_readonly_guard();

-- No hard deletes anywhere in the client domain.
CREATE OR REPLACE FUNCTION brite_no_delete()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Records are never deleted (%). Close or archive instead.', TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
END;
$$;
DROP TRIGGER IF EXISTS clients_client_no_delete ON clients_client;
CREATE TRIGGER clients_client_no_delete BEFORE DELETE ON clients_client FOR EACH ROW EXECUTE FUNCTION brite_no_delete();
"""
READONLY_REVERSE = """
DROP TRIGGER IF EXISTS clients_client_no_delete ON clients_client;
DROP TRIGGER IF EXISTS clients_workstream_readonly ON clients_workstream;
DROP TRIGGER IF EXISTS clients_serviceepisode_readonly ON clients_serviceepisode;
DROP FUNCTION IF EXISTS brite_no_delete();
DROP FUNCTION IF EXISTS brite_workstream_readonly_guard();
DROP FUNCTION IF EXISTS brite_episode_readonly_guard();
"""

VIEW = "brite_has_capability('client_operational_data', 'view')"
EDIT = "brite_has_capability('client_operational_data', 'edit')"
NEVER = "false"


def policies(table):
    return rls_policy_sql(table, select=VIEW, insert=EDIT, update=EDIT, delete=NEVER)


class Migration(migrations.Migration):
    dependencies = [("clients", "0001_initial"), ("core", "0001_rls_functions")]
    operations = [
        migrations.RunSQL(SEQUENCE_SQL, SEQUENCE_REVERSE),
        migrations.RunSQL(READONLY_SQL, READONLY_REVERSE),
        migrations.RunSQL(
            "\n".join(policies("clients_client") + policies("clients_serviceepisode") + policies("clients_workstream")),
            "\n".join(rls_disable_sql("clients_client") + rls_disable_sql("clients_serviceepisode") + rls_disable_sql("clients_workstream")),
        ),
    ]
