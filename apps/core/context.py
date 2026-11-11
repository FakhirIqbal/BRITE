"""
Per-request actor context.

Every write records *who* acted and *what kind* of actor it was
(human / system / scheduled). The context is held in a contextvar so
services deep in the call stack can read it without passing the request.
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass, field


class ActorType:
    HUMAN = "human"
    SYSTEM = "system"
    SCHEDULED = "scheduled"
    CHOICES = [(HUMAN, "Human"), (SYSTEM, "System"), (SCHEDULED, "Scheduled")]


@dataclass
class ActorContext:
    user_id: int | None = None
    actor_type: str = ActorType.SYSTEM
    actor_label: str = "System"
    capabilities: dict[str, str] = field(default_factory=dict)  # capability -> none|view|edit
    roles: list[str] = field(default_factory=list)
    bypass_rls: bool = False
    origin_event_id: int | None = None  # the human event that caused an automated action
    request_id: str = ""
    user: object = None  # the User instance when known (avoids re-fetching per write)
    access_detail: dict | None = None  # effective_access_detail() result for this request


_current: contextvars.ContextVar[ActorContext | None] = contextvars.ContextVar("brite_actor", default=None)


def get_actor() -> ActorContext:
    ctx = _current.get()
    if ctx is None:
        return ActorContext()
    return ctx


def set_actor(ctx: ActorContext) -> contextvars.Token:
    return _current.set(ctx)


def reset_actor(token: contextvars.Token) -> None:
    _current.reset(token)


@contextmanager
def actor_scope(ctx: ActorContext):
    token = set_actor(ctx)
    try:
        yield ctx
    finally:
        reset_actor(token)


@contextmanager
def system_actor(label: str = "System", scheduled: bool = False, origin_event_id: int | None = None):
    """Run code as the system (or a scheduled job). Used by seeds, syncs and jobs."""
    ctx = ActorContext(
        user_id=None,
        actor_type=ActorType.SCHEDULED if scheduled else ActorType.SYSTEM,
        actor_label=label,
        bypass_rls=True,
        origin_event_id=origin_event_id,
    )
    with actor_scope(ctx):
        from apps.core.db import apply_db_context

        apply_db_context(ctx)
        yield ctx
