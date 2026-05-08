from collections import OrderedDict

from django.db.models import Count, Q
from django.http import HttpRequest

from .models import (
    ArticleUserState,
    Bookmark,
    BookmarkCategory,
    BookmarkUserState,
    Feed,
    Tag,
)
from .utils import category_label


def _detect_active_app(request: HttpRequest) -> str:
    """Detect active app (rss/bookmark/shared) from URL path or current_page context."""
    path = request.path
    if "bookmark" in path:
        return "bookmark"
    if (
        "feeds" in path
        or "articles" in path
        or "overview" in path
        or "read-later" in path
        or "favorites" in path
    ):
        return "rss"
    return "shared"


def sidebar_feeds(request):
    """Provide feed list with unread counts for the global sidebar."""
    user = request.user
    is_auth = user.is_authenticated

    # Single annotated query: article_count + read_count per feed
    feeds_qs = Feed.objects.filter(is_active=True).order_by("display_order", "name")
    if is_auth:
        feeds_qs = feeds_qs.annotate(
            article_count=Count("articles", distinct=True),
            read_count=Count(
                "articles",
                filter=Q(
                    articles__user_states__user=user,
                    articles__user_states__is_read=True,
                ),
                distinct=True,
            ),
        )
    else:
        feeds_qs = feeds_qs.annotate(article_count=Count("articles", distinct=True))

    total_unread = 0
    total_read_later = 0
    total_saved = 0
    total_favorites = 0

    if is_auth:
        user_states = ArticleUserState.objects.filter(user=user)
        total_read_later = user_states.filter(is_read_later=True).count()
        total_favorites = user_states.filter(is_favorite=True).count()
        total_saved = total_read_later

    feed_list = []
    grouped = OrderedDict()
    for feed in feeds_qs:
        unread = feed.article_count - getattr(feed, "read_count", 0)
        total_unread += unread

        feed_data = {
            "id": feed.id,
            "name": feed.name,
            "category": category_label(feed.category),
            "unread_count": unread,
        }
        feed_list.append(feed_data)

        key = feed_data["category"]
        grouped.setdefault(key, []).append(feed_data)

    sidebar_groups = [{"name": name, "feeds": items} for name, items in grouped.items()]

    # Bookmark / tag data for sidebar
    sidebar_tags = []
    sidebar_bookmark_categories = []
    total_bookmarks = 0
    total_bookmarks_pinned = 0
    total_bookmarks_read_later = 0
    total_bookmarks_read = 0
    total_bookmarks_favorite = 0
    if is_auth:
        total_bookmarks = Bookmark.objects.filter(user=user).count()
        bookmark_states = BookmarkUserState.objects.filter(user=user)
        total_bookmarks_pinned = bookmark_states.filter(is_pinned=True).count()
        total_bookmarks_read_later = bookmark_states.filter(is_read_later=True).count()
        total_bookmarks_read = bookmark_states.filter(is_read=True).count()
        total_bookmarks_favorite = bookmark_states.filter(is_favorite=True).count()
        sidebar_tags = list(
            Tag.objects.filter(user=user)
            .annotate(bookmark_count=Count("bookmarks", distinct=True))
            .order_by("name")
            .values("id", "name", "slug", "color", "bookmark_count")
        )
        sidebar_bookmark_categories = list(
            BookmarkCategory.objects.filter(user=user)
            .annotate(bookmark_count=Count("bookmarks", distinct=True))
            .order_by("display_order", "name")
            .values("id", "name", "color", "bookmark_count")
        )

    theme_preference = "system"
    if is_auth:
        try:
            profile = user.profile
        except Exception:
            profile = None
        if profile:
            theme_preference = profile.theme_preference or "system"

    return {
        "sidebar_feeds": feed_list,
        "sidebar_groups": sidebar_groups,
        "sidebar_total_unread": total_unread,
        "sidebar_total_read_later": total_read_later,
        "sidebar_total_favorites": total_favorites,
        "sidebar_total_saved": total_saved,
        "sidebar_tags": sidebar_tags,
        "sidebar_bookmark_categories": sidebar_bookmark_categories,
        "sidebar_total_bookmarks": total_bookmarks,
        "sidebar_total_bookmarks_pinned": total_bookmarks_pinned,
        "sidebar_total_bookmarks_read_later": total_bookmarks_read_later,
        "sidebar_total_bookmarks_read": total_bookmarks_read,
        "sidebar_total_bookmarks_favorite": total_bookmarks_favorite,
        "theme_preference": theme_preference,
        "active_app": _detect_active_app(request),
    }
