"""
Database-level access enforcement helpers.

The API layer decides what a user may do; Postgres row-level security
policies check the same capability set again, so no route (or stray query)
can bypass the role model. The per-transaction settings below are what the
policies read via current_setting('app.*', true). When they are absent the
policies evaluate to NULL and access is denied (fail closed).
"""
from __future__ import annotations

from django.db import connection

from apps.core.context import ActorContext

CAPABILITY_SETTING = "app.capabilities"
USER_SETTING = "app.user_id"
BYPASS_SETTING = "app.bypass_rls"
ACTOR_TYPE_SETTING = "app.actor_type"


def encode_capabilities(capabilities: dict[str, str]) -> str:
    """Encode as ',cap:level,' so policies can use a plain LIKE match."""
    parts = [f"{cap}:{level}" for cap, level in sorted(capabilities.items()) if level in {"view", "edit"}]
    return "," + ",".join(parts) + "," if parts else ","


def apply_db_context(ctx: ActorContext) -> None:
    """SET LOCAL the context for the current transaction (no-op outside one)."""
    if not connection.in_atomic_block:
        # Nothing to attach the settings to; the caller must open a transaction.
        return
    with connection.cursor() as cur:
        cur.execute(
            "SELECT set_config(%s, %s, true), set_config(%s, %s, true), set_config(%s, %s, true), set_config(%s, %s, true)",
            [
                CAPABILITY_SETTING, encode_capabilities(ctx.capabilities),
                USER_SETTING, str(ctx.user_id or ""),
                BYPASS_SETTING, "on" if ctx.bypass_rls else "off",
                ACTOR_TYPE_SETTING, ctx.actor_type,
            ],
        )


# SQL fragments reused by app migrations that install policies.
HAS_CAPABILITY_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION brite_has_capability(cap text, level text)
RETURNS boolean
LANGUAGE sql STABLE
AS $$
    SELECT CASE
        WHEN current_setting('app.bypass_rls', true) = 'on' THEN true
        WHEN level = 'view' THEN
            coalesce(current_setting('app.capabilities', true), '') LIKE '%,' || cap || ':view,%'
            OR coalesce(current_setting('app.capabilities', true), '') LIKE '%,' || cap || ':edit,%'
        WHEN level = 'edit' THEN
            coalesce(current_setting('app.capabilities', true), '') LIKE '%,' || cap || ':edit,%'
        ELSE false
    END;
$$;
"""

CURRENT_USER_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION brite_current_user_id()
RETURNS bigint
LANGUAGE sql STABLE
AS $$
    SELECT CASE
        WHEN coalesce(current_setting('app.user_id', true), '') = '' THEN NULL
        ELSE current_setting('app.user_id', true)::bigint
    END;
$$;
"""


def rls_policy_sql(table: str, *, select: str, insert: str | None = None, update: str | None = None, delete: str | None = None) -> list[str]:
    """Build the SQL that enables + forces RLS on a table with the given policies."""
    statements = [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
        f"DROP POLICY IF EXISTS {table}_select ON {table};",
        f"CREATE POLICY {table}_select ON {table} FOR SELECT USING ({select});",
    ]
    if insert is not None:
        statements += [
            f"DROP POLICY IF EXISTS {table}_insert ON {table};",
            f"CREATE POLICY {table}_insert ON {table} FOR INSERT WITH CHECK ({insert});",
        ]
    if update is not None:
        statements += [
            f"DROP POLICY IF EXISTS {table}_update ON {table};",
            f"CREATE POLICY {table}_update ON {table} FOR UPDATE USING ({update}) WITH CHECK ({update});",
        ]
    if delete is not None:
        statements += [
            f"DROP POLICY IF EXISTS {table}_delete ON {table};",
            f"CREATE POLICY {table}_delete ON {table} FOR DELETE USING ({delete});",
        ]
    return statements


def rls_disable_sql(table: str) -> list[str]:
    return [
        f"DROP POLICY IF EXISTS {table}_select ON {table};",
        f"DROP POLICY IF EXISTS {table}_insert ON {table};",
        f"DROP POLICY IF EXISTS {table}_update ON {table};",
        f"DROP POLICY IF EXISTS {table}_delete ON {table};",
        f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;",
        f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;",
    ]
