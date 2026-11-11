from rest_framework import serializers

from apps.configuration.models import StatusOption, StatusSet


class StatusOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = StatusOption
        fields = ["id", "code", "label", "tone", "sort_order", "is_active", "is_terminal", "version", "updated_at", "updated_by_label"]
        read_only_fields = ["id", "updated_at", "updated_by_label"]


class StatusSetSerializer(serializers.ModelSerializer):
    options = StatusOptionSerializer(many=True, read_only=True)

    class Meta:
        model = StatusSet
        fields = ["id", "key", "name", "description", "reference", "sort_order", "options", "version", "updated_at", "updated_by_label"]
        read_only_fields = ["id", "key", "updated_at", "updated_by_label"]
