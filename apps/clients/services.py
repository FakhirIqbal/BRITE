"""Client-domain services: creation, episodes, workstream edits, closure, reactivation."""
from __future__ import annotations

from django.db import connection, transaction
from django.utils import timezone

from apps.audit.services import record_event
from apps.clients.codenames import generate_code_name
from apps.clients.models import Client, ServiceEpisode, Workstream
from apps.configuration.models import StatusOption
from apps.core.context import get_actor
from apps.core.exceptions import BusinessRuleViolation, ReadOnlyRecord
from apps.core.services import actor_label, create_versioned, save_versioned


def next_client_id() -> str:
    with connection.cursor() as cur:
        cur.execute("SELECT nextval('client_system_id_seq')")
        (value,) = cur.fetchone()
    return f"BC-{value:06d}"


def _actor_user_id():
    return get_actor().user_id


def valid_status_codes(set_key: str) -> set[str]:
    return set(StatusOption.objects.filter(status_set__key=set_key, is_active=True).values_list("code", flat=True))


def _default_workstream_owner(kind: str, creator_id: int | None):
    # The creating Client Coordinator owns Client Coordination; everything else
    # starts Unassigned and sits in the Unassigned queue for its monitoring role.
    if kind == Workstream.KIND_CLIENT_COORDINATION and creator_id:
        return creator_id
    return None


@transaction.atomic(savepoint=False)
def open_episode(client: Client, *, settings_requested: list[str] | None = None) -> ServiceEpisode:
    if client.episodes.filter(state=ServiceEpisode.STATE_OPEN).exists():
        raise BusinessRuleViolation("This client already has an active Service Episode. Close it before opening another.")
    number = (client.episodes.order_by("-number").values_list("number", flat=True).first() or 0) + 1
    episode = create_versioned(
        ServiceEpisode, summary=f"Episode {number} opened for {client.code_name}",
        client=client, number=number, settings_requested=settings_requested or [],
    )
    creator = _actor_user_id()
    label = actor_label()
    workstreams = Workstream.objects.bulk_create([
        Workstream(
            episode=episode, kind=kind, status="not_started", owner_id=_default_workstream_owner(kind, creator),
            created_by_id=creator, updated_by_id=creator, updated_by_label=label,
        )
        for kind in Workstream.KIND_ORDER
    ])
    record_event(
        episode, event_type="record_change", action="workstreams_created",
        summary=f"All six workstreams created · Episode {number} · {client.code_name}; unowned ones sit in the Unassigned queue",
        changes=[
            {"field": f"{ws.kind}.owner", "old_value": None, "new_value": label if ws.owner_id else "Unassigned"} for ws in workstreams
        ],
    )
    return episode


@transaction.atomic(savepoint=False)
def create_client(*, first_name: str, last_name: str, age_years=None, date_of_birth=None, state_market: str = "FL", settings_requested=None) -> Client:
    first_name, last_name = first_name.strip(), last_name.strip()
    if not first_name or not last_name:
        raise BusinessRuleViolation("Client first and last name are required.")
    code_name = generate_code_name(set(Client.objects.values_list("code_name", flat=True)))
    client = create_versioned(
        Client, summary=f"Client record created · {code_name}",
        client_id=next_client_id(), code_name=code_name, first_name=first_name, last_name=last_name,
        age_years=age_years, date_of_birth=date_of_birth, state_market=state_market,
    )
    open_episode(client, settings_requested=settings_requested)
    return client


def possible_duplicates(first_name: str, last_name: str, exclude_pk: int | None = None):
    """Search potential, active, closed and archived records; never merges."""
    qs = Client.objects.filter(last_name__iexact=last_name.strip())
    first = first_name.strip()
    if first:
        qs = qs.filter(first_name__istartswith=first[:3])
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs[:10]


def _ensure_open(episode: ServiceEpisode):
    if not episode.is_open:
        raise ReadOnlyRecord(f"Episode {episode.number} of {episode.client.code_name} is closed and read-only for active work.")


@transaction.atomic(savepoint=False)
def update_client(client: Client, changes: dict, *, expected_version: int | None, reason: str = "") -> Client:
    if client.is_archived:
        raise ReadOnlyRecord("This client record is archived and read-only.")
    return save_versioned(client, changes, expected_version=expected_version, summary=f"Client {client.code_name} updated", reason=reason)


@transaction.atomic(savepoint=False)
def update_workstream(ws: Workstream, changes: dict, *, expected_version: int | None, reason: str = "") -> Workstream:
    _ensure_open(ws.episode)
    if "status" in changes and changes["status"] not in valid_status_codes("workstream_status"):
        raise BusinessRuleViolation("Choose a status from the configured Workstream status set.")
    return save_versioned(
        ws, changes, expected_version=expected_version, reason=reason,
        summary=f"{Workstream.KIND_LABELS[ws.kind]} workstream updated · {ws.episode.client.code_name}",
    )


@transaction.atomic(savepoint=False)
def set_lifecycle(episode: ServiceEpisode, lifecycle: str, *, expected_version: int | None) -> ServiceEpisode:
    _ensure_open(episode)
    if lifecycle not in dict(ServiceEpisode.LIFECYCLE_CHOICES):
        raise BusinessRuleViolation("Unknown lifecycle marker.")
    return save_versioned(
        episode, {"lifecycle": lifecycle}, expected_version=expected_version,
        summary=f"Episode {episode.number} of {episode.client.code_name} lifecycle marker → {dict(ServiceEpisode.LIFECYCLE_CHOICES)[lifecycle]}",
    )


@transaction.atomic(savepoint=False)
def close_episode(episode: ServiceEpisode, *, reason_code: str, note: str, expected_version: int | None) -> ServiceEpisode:
    _ensure_open(episode)
    if reason_code not in valid_status_codes("episode_closure_reason"):
        raise BusinessRuleViolation("Choose a structured closure reason.")
    now = timezone.now()
    episode = save_versioned(
        episode,
        {"state": ServiceEpisode.STATE_CLOSED, "closed_at": now, "closed_by_label": actor_label(), "closure_reason": reason_code, "closure_note": note or ""},
        expected_version=expected_version, event_type="record_change",
        summary=f"Episode {episode.number} of {episode.client.code_name} closed · reason: {reason_code}",
        reason=note or "",
    )
    return episode


@transaction.atomic(savepoint=False)
def reactivate(client: Client) -> ServiceEpisode:
    """Open the next sequential episode; the closed one stays intact and read-only."""
    if client.is_archived:
        raise ReadOnlyRecord("This client record is archived.")
    last = client.episodes.order_by("-number").first()
    settings_requested = last.settings_requested if last else []
    episode = open_episode(client, settings_requested=settings_requested)
    record_event(
        client, event_type="record_change", action="reactivated",
        summary=f"{client.code_name} reactivated · Episode {episode.number} opened; Episode {episode.number - 1} stays closed and read-only",
    )
    return episode
