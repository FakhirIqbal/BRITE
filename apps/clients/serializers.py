from rest_framework import serializers

from apps.accounts.serializers import UserSummarySerializer
from apps.clients.models import Client, ServiceEpisode, Workstream


class WorkstreamSerializer(serializers.ModelSerializer):
    kind_label = serializers.SerializerMethodField()
    owner = UserSummarySerializer(read_only=True)
    owner_id = serializers.IntegerField(read_only=True)
    is_unassigned = serializers.ReadOnlyField()
    monitor_role = serializers.SerializerMethodField()

    class Meta:
        model = Workstream
        fields = [
            "id", "kind", "kind_label", "status", "owner", "owner_id", "is_unassigned", "monitor_role", "next_action", "due_date",
            "blocker", "waiting_on", "updated_at", "updated_by_label", "version",
        ]
        read_only_fields = ["id", "kind", "updated_at", "updated_by_label"]

    def get_kind_label(self, obj):
        return Workstream.KIND_LABELS[obj.kind]

    def get_monitor_role(self, obj):
        return Workstream.KIND_MONITOR_ROLE[obj.kind]


class ServiceEpisodeSerializer(serializers.ModelSerializer):
    workstreams = WorkstreamSerializer(many=True, read_only=True)
    journey_phase = serializers.SerializerMethodField()
    journey = serializers.SerializerMethodField()

    class Meta:
        model = ServiceEpisode
        fields = [
            "id", "number", "state", "lifecycle", "opened_at", "closed_at", "closed_by_label", "closure_reason", "closure_note",
            "settings_requested", "journey_phase", "journey", "workstreams", "updated_at", "updated_by_label", "version",
        ]
        read_only_fields = fields

    def get_journey_phase(self, obj):
        return obj.derived_journey_phase()

    def get_journey(self, obj):
        return [{"code": c, "label": l} for c, l in ServiceEpisode.JOURNEY]


class ClientListSerializer(serializers.ModelSerializer):
    record_state = serializers.ReadOnlyField()
    full_name = serializers.ReadOnlyField()
    episode_count = serializers.SerializerMethodField()
    active_episode = serializers.SerializerMethodField()
    owner_label = serializers.SerializerMethodField()
    journey_label = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = [
            "id", "client_id", "code_name", "first_name", "last_name", "full_name", "age_years", "date_of_birth", "state_market",
            "record_state", "episode_count", "active_episode", "owner_label", "journey_label", "is_archived", "updated_at", "updated_by_label",
        ]

    def _active(self, obj):
        episodes = getattr(obj, "_prefetched_objects_cache", {}).get("episodes")
        if episodes is not None:
            return next((e for e in episodes if e.state == ServiceEpisode.STATE_OPEN), None)
        return obj.active_episode

    def get_episode_count(self, obj):
        episodes = getattr(obj, "_prefetched_objects_cache", {}).get("episodes")
        return len(episodes) if episodes is not None else obj.episodes.count()

    def get_active_episode(self, obj):
        ep = self._active(obj)
        return {"id": ep.id, "number": ep.number, "lifecycle": ep.lifecycle} if ep else None

    def get_owner_label(self, obj):
        ep = self._active(obj)
        if not ep:
            return None
        ws = next((w for w in ep.workstreams.all() if w.kind == Workstream.KIND_CLIENT_COORDINATION), None)
        return str(ws.owner) if ws and ws.owner else None

    def get_journey_label(self, obj):
        ep = self._active(obj)
        return dict(ServiceEpisode.JOURNEY)[ep.derived_journey_phase()] if ep else None


class ClientDetailSerializer(ClientListSerializer):
    episodes = ServiceEpisodeSerializer(many=True, read_only=True)

    class Meta(ClientListSerializer.Meta):
        fields = ClientListSerializer.Meta.fields + ["drive_folder_url", "episodes", "version", "created_at"]


class ClientCreateSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=80)
    last_name = serializers.CharField(max_length=80)
    age_years = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=120)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    state_market = serializers.ChoiceField(choices=Client.STATE_CHOICES, default="FL")
    settings_requested = serializers.ListField(child=serializers.ChoiceField(choices=["home", "school", "clinic"]), required=False, default=list)
    acknowledge_duplicates = serializers.BooleanField(required=False, default=False)


class ClientUpdateSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=80, required=False)
    last_name = serializers.CharField(max_length=80, required=False)
    age_years = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=120)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    state_market = serializers.ChoiceField(choices=Client.STATE_CHOICES, required=False)
    drive_folder_url = serializers.URLField(required=False, allow_blank=True)
    version = serializers.IntegerField()
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class WorkstreamUpdateSerializer(serializers.Serializer):
    status = serializers.CharField(max_length=60, required=False)
    owner_id = serializers.IntegerField(required=False, allow_null=True)
    next_action = serializers.CharField(max_length=300, required=False, allow_blank=True)
    due_date = serializers.DateField(required=False, allow_null=True)
    blocker = serializers.CharField(max_length=300, required=False, allow_blank=True)
    waiting_on = serializers.CharField(max_length=200, required=False, allow_blank=True)
    version = serializers.IntegerField()
    reason = serializers.CharField(required=False, allow_blank=True, default="")
