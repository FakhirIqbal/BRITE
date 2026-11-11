from rest_framework import serializers

from apps.audit.models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    origin_event_summary = serializers.SerializerMethodField()

    class Meta:
        model = AuditEvent
        fields = [
            "id", "occurred_at", "event_type", "action", "summary", "reason", "stream", "entity_type",
            "entity_id", "entity_label", "client_id", "subject_user_id", "changes", "actor", "actor_label",
            "actor_type", "origin_event", "origin_event_summary", "flags", "prev_hash", "hash",
        ]
        read_only_fields = fields

    def get_origin_event_summary(self, obj):
        if obj.origin_event_id and obj.origin_event:
            return f"{obj.origin_event.actor_label} · {obj.origin_event.summary}"
        return None
