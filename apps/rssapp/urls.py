from django.urls import path

from .views import (
    article_state_toggle_view,
    dashboard_view,
    feed_settings_view,
    feed_update_view,
    mark_all_read_view,
    reader_view,
    feed_articles_view,
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
]
