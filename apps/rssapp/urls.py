from django.urls import path

from .views import (
    article_state_toggle_view,
    bookmark_add_view,
    bookmark_delete_view,
    bookmark_edit_view,
    bookmark_from_article_view,
    bookmark_list_view,
    dashboard_view,
    feed_settings_view,
    feed_update_view,
    mark_all_read_view,
    reader_view,
    feed_articles_view,
    tag_list_view,
    tag_update_view,
)

urlpatterns = [
    path("", dashboard_view, name="rss-dashboard"),
    path("feeds/settings/", feed_settings_view, name="feed-settings"),
    path("feeds/<int:feed_id>/", feed_articles_view, name="feed-articles"),
    path("feeds/<int:feed_id>/update/", feed_update_view, name="feed-update"),
    path("articles/<int:article_id>/reader/", reader_view, name="article-reader"),
    path(
        "articles/<int:article_id>/state/<str:state_field>/toggle/",
        article_state_toggle_view,
        name="article-state-toggle",
    ),
    path("mark-all-read/", mark_all_read_view, name="mark-all-read"),
    # Bookmarks
    path("bookmarks/", bookmark_list_view, name="bookmark-list"),
    path("bookmarks/add/", bookmark_add_view, name="bookmark-add"),
    path("bookmarks/<int:bookmark_id>/edit/", bookmark_edit_view, name="bookmark-edit"),
    path(
        "bookmarks/<int:bookmark_id>/delete/",
        bookmark_delete_view,
        name="bookmark-delete",
    ),
    path(
        "bookmarks/from-article/<int:article_id>/",
        bookmark_from_article_view,
        name="bookmark-from-article",
    ),
    # Tags
    path("tags/", tag_list_view, name="tag-list"),
    path("tags/<int:tag_id>/update/", tag_update_view, name="tag-update"),
]
