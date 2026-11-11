from rest_framework import serializers

from apps.accounts.models import IndividualException, RoleCapabilityDefault, SystemOwner, User, WorkspaceGroupMapping
from apps.accounts.roles import Capability, Level, Role


class UserSummarySerializer(serializers.ModelSerializer):
    initials = serializers.ReadOnlyField()

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "initials", "is_active"]


class WorkspaceGroupMappingSerializer(serializers.ModelSerializer):
    role_label = serializers.SerializerMethodField()
    member_count = serializers.ReadOnlyField()

    class Meta:
        model = WorkspaceGroupMapping
        fields = ["id", "group_email", "role", "role_label", "is_active", "member_count", "last_synced_at", "version", "updated_at", "updated_by_label"]
        read_only_fields = ["id", "member_count", "last_synced_at", "updated_at", "updated_by_label"]

    def get_role_label(self, obj):
        return Role.LABELS.get(obj.role, obj.role)


class RoleCapabilityDefaultSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoleCapabilityDefault
        fields = ["id", "role", "capability", "level", "version"]


class IndividualExceptionSerializer(serializers.ModelSerializer):
    user = UserSummarySerializer(read_only=True)
    capability_label = serializers.SerializerMethodField()
    state = serializers.ReadOnlyField()

    class Meta:
        model = IndividualException
        fields = [
            "id", "user", "capability", "capability_label", "kind", "level", "reason", "duration", "expires_on",
            "granted_by_label", "is_self_granted", "notified_owner_emails", "created_at", "removed_at", "removed_reason",
            "removed_by_label", "state",
        ]

    def get_capability_label(self, obj):
        return Capability.LABELS.get(obj.capability, obj.capability)


class ExceptionCreateSerializer(serializers.Serializer):
    capability = serializers.ChoiceField(choices=Capability.CHOICES)
    kind = serializers.ChoiceField(choices=IndividualException.KIND_CHOICES)
    level = serializers.ChoiceField(choices=Level.CHOICES, required=False, default=Level.VIEW)
    reason = serializers.CharField()
    duration = serializers.ChoiceField(choices=IndividualException.DURATION_CHOICES, default=IndividualException.DURATION_PERMANENT)
    expires_on = serializers.DateField(required=False, allow_null=True)


class SystemOwnerSerializer(serializers.ModelSerializer):
    user = UserSummarySerializer(read_only=True)

    class Meta:
        model = SystemOwner
        fields = ["id", "user", "assigned_by_label", "assigned_at", "removed_at", "removed_by_label"]
