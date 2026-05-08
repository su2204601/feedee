from django.contrib import admin
from import_export import fields, resources
from import_export.admin import ExportActionModelAdmin, ImportExportModelAdmin
from import_export.widgets import ForeignKeyWidget, ManyToManyWidget

from .models import (
    Article,
    ArticleUserState,
    Bookmark,
    BookmarkCategory,
    BookmarkUserState,
    Category,
    ExtractionTask,
    Feed,
    Tag,
    UserProfile,
)


# ── Resources (Import/Export) ─────────────────────────────


class FeedResource(resources.ModelResource):
    class Meta:
        model = Feed
        fields = (
            "id",
            "name",
            "url",
            "category",
            "is_active",
            "fetch_interval_minutes",
            "display_order",
        )
        export_order = fields


class ArticleResource(resources.ModelResource):
    feed_name = fields.Field(
        column_name="feed_name",
        attribute="feed",
        widget=ForeignKeyWidget(Feed, field="name"),
    )

    class Meta:
        model = Article
        fields = (
            "id",
            "feed_name",
            "title",
            "link",
            "image_url",
            "published_at",
            "created_at",
            "content_source",
            "extraction_status",
        )
        export_order = fields


class BookmarkResource(resources.ModelResource):
    tags = fields.Field(
        column_name="tags",
        attribute="tags",
        widget=ManyToManyWidget(Tag, field="name", separator=","),
    )

    class Meta:
        model = Bookmark
        fields = (
            "id",
            "title",
            "url",
            "description",
            "user__username",
            "category__name",
            "tags",
            "created_at",
        )
        export_order = fields


class TagResource(resources.ModelResource):
    class Meta:
        model = Tag
        fields = ("id", "name", "slug", "user__username", "color")
        export_order = fields


# ── Admin Classes ────────────────────────────────────────


@admin.register(Category)
class CategoryAdmin(ImportExportModelAdmin):
    list_display = ("full_path_display", "user", "parent", "content_type", "color", "display_order")
    list_filter = ("content_type", "user", "parent")
    search_fields = ("name",)
    list_editable = ("display_order",)
    ordering = ("display_order", "name")

    @admin.display(description="カテゴリ", ordering="name")
    def full_path_display(self, obj):
        return obj.full_path


@admin.register(Feed)
class FeedAdmin(ImportExportModelAdmin):
    resource_class = FeedResource
    list_display = (
        "name",
        "url_short",
        "category",
        "is_active",
        "consecutive_failures",
        "last_fetched_at",
        "fetch_interval_minutes",
        "display_order",
    )
    list_filter = ("is_active", "category", "consecutive_failures")
    search_fields = ("name", "url")
    list_editable = ("is_active", "display_order", "fetch_interval_minutes")
    ordering = ("display_order", "name")
    readonly_fields = (
        "etag",
        "last_modified",
        "last_fetched_at",
        "last_success_at",
        "last_error",
        "consecutive_failures",
        "next_fetch_at",
    )
    fieldsets = (
        (None, {"fields": ("name", "url", "category", "category_v2", "display_order")}),
        ("取得設定", {"fields": ("is_active", "is_public", "fetch_interval_minutes")}),
        (
            "取得ステータス",
            {
                "classes": ("collapse",),
                "fields": (
                    "etag",
                    "last_modified",
                    "last_fetched_at",
                    "last_success_at",
                    "next_fetch_at",
                    "consecutive_failures",
                    "last_error",
                ),
            },
        ),
    )

    @admin.display(description="URL")
    def url_short(self, obj):
        return obj.url[:60] + "…" if len(obj.url) > 60 else obj.url


@admin.register(Article)
class ArticleAdmin(ExportActionModelAdmin):
    resource_class = ArticleResource
    list_display = (
        "title_short",
        "feed",
        "content_source",
        "extraction_status",
        "published_at",
        "created_at",
    )
    list_filter = (
        "feed",
        "content_source",
        "extraction_status",
        "published_at",
        "created_at",
    )
    search_fields = ("title", "link", "guid", "feed__name")
    date_hierarchy = "published_at"
    readonly_fields = ("hash", "normalized_link", "created_at")
    raw_id_fields = ("feed",)
    fieldsets = (
        (None, {"fields": ("feed", "title", "link", "guid")}),
        ("コンテンツ", {"fields": ("summary", "content", "image_url")}),
        (
            "抽出情報",
            {
                "fields": (
                    "content_source",
                    "extraction_status",
                    "extracted_at",
                ),
            },
        ),
        (
            "メタデータ",
            {
                "classes": ("collapse",),
                "fields": ("hash", "normalized_link", "published_at", "created_at"),
            },
        ),
    )

    @admin.display(description="タイトル")
    def title_short(self, obj):
        return obj.title[:80] + "…" if len(obj.title) > 80 else obj.title


@admin.register(ArticleUserState)
class ArticleUserStateAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "article_title",
        "is_read",
        "is_read_later",
        "is_favorite",
        "updated_at",
    )
    list_filter = ("is_read", "is_read_later", "is_favorite", "user")
    search_fields = ("user__username", "article__title")
    raw_id_fields = ("user", "article")
    date_hierarchy = "updated_at"

    @admin.display(description="記事")
    def article_title(self, obj):
        return obj.article.title[:60] if obj.article else "—"


@admin.register(BookmarkUserState)
class BookmarkUserStateAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "bookmark_title",
        "is_pinned",
        "is_favorite",
        "is_read_later",
        "is_read",
        "updated_at",
    )
    list_filter = ("is_pinned", "is_favorite", "is_read_later", "is_read", "user")
    search_fields = ("user__username", "bookmark__title")
    raw_id_fields = ("user", "bookmark")
    date_hierarchy = "updated_at"

    @admin.display(description="ブックマーク")
    def bookmark_title(self, obj):
        return obj.bookmark.title[:60] if obj.bookmark else "—"


@admin.register(ExtractionTask)
class ExtractionTaskAdmin(admin.ModelAdmin):
    list_display = (
        "article",
        "status",
        "retry_count",
        "created_at",
        "completed_at",
    )
    list_filter = ("status",)
    search_fields = ("article__title",)
    readonly_fields = ("created_at", "updated_at", "started_at", "completed_at")
    raw_id_fields = ("article",)


@admin.register(Tag)
class TagAdmin(ImportExportModelAdmin):
    resource_class = TagResource
    list_display = ("name", "slug", "user", "color", "bookmark_count")
    search_fields = ("name", "slug", "user__username")
    list_filter = ("user",)

    def get_queryset(self, request):
        from django.db.models import Count

        qs = super().get_queryset(request)
        return qs.annotate(_bookmark_count=Count("bookmarks"))

    @admin.display(description="ブックマーク数", ordering="_bookmark_count")
    def bookmark_count(self, obj):
        return obj._bookmark_count


@admin.register(BookmarkCategory)
class BookmarkCategoryAdmin(ImportExportModelAdmin):
    list_display = ("full_path_display", "user", "parent", "color", "display_order", "bookmark_count")
    list_filter = ("user", "parent")
    search_fields = ("name", "user__username")
    list_editable = ("display_order",)

    @admin.display(description="カテゴリ", ordering="name")
    def full_path_display(self, obj):
        return obj.full_path

    def get_queryset(self, request):
        from django.db.models import Count

        qs = super().get_queryset(request)
        return qs.annotate(_bookmark_count=Count("bookmarks"))

    @admin.display(description="ブックマーク数", ordering="_bookmark_count")
    def bookmark_count(self, obj):
        return obj._bookmark_count


@admin.register(Bookmark)
class BookmarkAdmin(ImportExportModelAdmin):
    resource_class = BookmarkResource
    list_display = (
        "title_short",
        "url_short",
        "user",
        "category",
        "tag_list",
        "created_at",
    )
    list_filter = ("user", "category", "created_at")
    search_fields = ("title", "url", "description", "user__username")
    date_hierarchy = "created_at"
    raw_id_fields = ("user", "source_article")
    filter_horizontal = ("tags",)
    readonly_fields = ("normalized_url", "hash", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("user", "title", "url", "description", "thumbnail_url")}),
        (
            "分類",
            {"fields": ("category", "category_v2", "tags")},
        ),
        (
            "関連",
            {
                "classes": ("collapse",),
                "fields": ("source_article",),
            },
        ),
        (
            "メタデータ",
            {
                "classes": ("collapse",),
                "fields": ("normalized_url", "hash", "created_at", "updated_at"),
            },
        ),
    )

    @admin.display(description="タイトル")
    def title_short(self, obj):
        return obj.title[:60] + "…" if len(obj.title) > 60 else obj.title

    @admin.display(description="URL")
    def url_short(self, obj):
        return obj.url[:50] + "…" if len(obj.url) > 50 else obj.url

    @admin.display(description="タグ")
    def tag_list(self, obj):
        return ", ".join(t.name for t in obj.tags.all()[:5])


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "default_sort",
        "default_display_mode",
        "theme_preference",
        "items_per_page",
    )
    list_filter = ("default_sort", "theme_preference", "default_display_mode")
    search_fields = ("user__username",)
