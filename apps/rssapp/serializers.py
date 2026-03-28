from rest_framework import serializers

from .models import ArticleUserState, Feed


class FeedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feed
        fields = ["id", "name", "url", "category", "display_order", "is_active"]


class FeedReorderSerializer(serializers.Serializer):
    feed_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
    )


class ArticleIngestSerializer(serializers.Serializer):
    feed_id = serializers.PrimaryKeyRelatedField(
        queryset=Feed.objects.all(),
        source="feed",
        required=False,
        allow_null=True,
    )
    title = serializers.CharField(max_length=500)
    link = serializers.URLField(max_length=2048)
    guid = serializers.CharField(
        max_length=500, allow_blank=True, allow_null=True, required=False
    )
    summary = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    content = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    published_at = serializers.DateTimeField(required=False, allow_null=True)


class ArticleUserStateSerializer(serializers.ModelSerializer):
    article = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = ArticleUserState
        fields = ["article", "is_favorite", "is_read_later", "is_read", "updated_at"]
        read_only_fields = ["article", "updated_at"]
