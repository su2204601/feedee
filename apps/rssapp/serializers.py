from rest_framework import serializers

from .models import ArticleUserState, BookmarkCategory, Feed, UserProfile


class FeedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feed
        fields = [
            "id",
            "name",
            "url",
            "category",
            "display_order",
            "is_active",
            "etag",
            "last_modified",
            "next_fetch_at",
            "fetch_interval_minutes",
            "last_fetched_at",
            "last_success_at",
            "consecutive_failures",
        ]


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
    image_url = serializers.URLField(
        max_length=2048, required=False, allow_blank=True, allow_null=True
    )
    published_at = serializers.DateTimeField(required=False, allow_null=True)


class ArticleUserStateSerializer(serializers.ModelSerializer):
    article = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = ArticleUserState
        fields = ["article", "is_favorite", "is_read_later", "is_read", "updated_at"]
        read_only_fields = ["article", "updated_at"]


class FeedFetchStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["success", "not_modified", "error"])
    http_status = serializers.IntegerField(required=False, min_value=100, max_value=599)
    error = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    etag = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    last_modified = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )
    item_count = serializers.IntegerField(required=False, min_value=0, default=0)


class FetchMetadataSerializer(serializers.Serializer):
    url = serializers.URLField(max_length=2048)


class BookmarkCategorySerializer(serializers.ModelSerializer):
    bookmark_count = serializers.SerializerMethodField()

    class Meta:
        model = BookmarkCategory
        fields = [
            "id",
            "name",
            "description",
            "color",
            "display_order",
            "bookmark_count",
        ]

    def get_bookmark_count(self, obj):
        return obj.bookmarks.count()


class BookmarkletCreateSerializer(serializers.Serializer):
    """Lightweight serializer for bookmarklet POST requests."""

    url = serializers.URLField(max_length=2048)
    title = serializers.CharField(max_length=500, allow_blank=True, required=False)
    description = serializers.CharField(allow_blank=True, required=False)
    tags = serializers.CharField(
        allow_blank=True,
        required=False,
        help_text="Comma-separated tag names",
    )
    category_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_url(self, value):
        """Ensure URL is valid and not already bookmarked."""
        return value.strip()


class DisplayModePreferenceSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(
        choices=[choice[0] for choice in UserProfile.DISPLAY_MODE_CHOICES]
    )
