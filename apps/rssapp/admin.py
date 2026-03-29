from django.contrib import admin

from .models import Article, ArticleUserState, Bookmark, Feed, Tag


@admin.register(Feed)
class FeedAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "url")
    search_fields = ("name", "url")


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("id", "feed", "title", "published_at", "created_at")
    search_fields = ("title", "link", "guid", "feed__name", "feed__url")
    list_filter = ("feed", "published_at", "created_at")


@admin.register(ArticleUserState)
class ArticleUserStateAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "article",
        "is_favorite",
        "is_read_later",
        "is_read",
        "updated_at",
    )
    list_filter = ("is_favorite", "is_read_later", "is_read", "updated_at")


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "slug", "user", "color")
    search_fields = ("name",)
    list_filter = ("user",)


@admin.register(Bookmark)
class BookmarkAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "url", "user", "created_at")
    search_fields = ("title", "url")
    list_filter = ("user", "created_at")
    search_fields = ("user__username", "user__email", "article__title", "article__link")
