from django.urls import path

from .views import (
    ArticleIngestView,
    ArticleUserStateView,
    FeedListView,
    FeedReorderView,
    FetchMetadataView,
)

urlpatterns = [
    path("feeds/", FeedListView.as_view(), name="feed-list"),
    path("feeds/reorder/", FeedReorderView.as_view(), name="feed-reorder"),
    path("articles/ingest/", ArticleIngestView.as_view(), name="article-ingest"),
    path(
        "articles/<int:article_id>/state/",
        ArticleUserStateView.as_view(),
        name="article-user-state",
    ),
    path(
        "bookmarks/fetch-metadata/", FetchMetadataView.as_view(), name="fetch-metadata"
    ),
]
