from collections import OrderedDict

from django.db.models import Count, Q

from .models import Article, ArticleUserState, Feed


def _category_label(value):
    cleaned = (value or "").strip()
    return cleaned if cleaned else "Uncategorized"


def sidebar_feeds(request):
    """Provide feed list with unread counts for the global sidebar."""
    feeds = Feed.objects.filter(is_active=True).order_by("display_order", "name")

    read_article_ids = set()
    total_unread = 0
    total_read_later = 0
    total_favorites = 0

    if request.user.is_authenticated:
        user_states = ArticleUserState.objects.filter(user=request.user)
        read_article_ids = set(
            user_states.filter(is_read=True).values_list("article_id", flat=True)
        )
        total_read_later = user_states.filter(is_read_later=True).count()
        total_favorites = user_states.filter(is_favorite=True).count()

    feed_list = []
    grouped = OrderedDict()
    for feed in feeds:
        article_count = Article.objects.filter(feed=feed).count()
        unread = (
            article_count
            - Article.objects.filter(feed=feed, id__in=read_article_ids).count()
            if read_article_ids
            else article_count
        )
        total_unread += unread

        feed_data = {
            "id": feed.id,
            "name": feed.name,
            "category": _category_label(feed.category),
            "unread_count": unread,
        }
        feed_list.append(feed_data)

        key = feed_data["category"]
        grouped.setdefault(key, []).append(feed_data)

    sidebar_groups = [{"name": name, "feeds": items} for name, items in grouped.items()]

    return {
        "sidebar_feeds": feed_list,
        "sidebar_groups": sidebar_groups,
        "sidebar_total_unread": total_unread,
        "sidebar_total_read_later": total_read_later,
        "sidebar_total_favorites": total_favorites,
    }
