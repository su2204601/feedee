from django.urls import path
from django.urls import include
from django.views.generic import RedirectView

from .views import (
    account_settings_view,
    bookmark_settings_view,
    export_opml_view,
    favorites_view,
    feed_update_view,
    import_opml_view,
    main_dashboard_view,
    overview_dashboard_view,
    read_later_view,
    rss_settings_view,
    settings_view,
)

urlpatterns = [
    path(
        "",
        RedirectView.as_view(pattern_name="bookmarks-page", permanent=False),
        name="homepage",
    ),
    path("", include("apps.rss_service.public_urls")),
    path("", include("apps.bookmark_service.public_urls")),
    # Main pages
    path("overview/", overview_dashboard_view, name="overview"),
    path(
        "dashboard/",
        RedirectView.as_view(pattern_name="overview", permanent=True),
        name="main-dashboard",
    ),
    path("read-later/", read_later_view, name="read-later"),
    path("favorites/", favorites_view, name="favorites"),
    # Settings (Unified)
    path("settings/", settings_view, name="settings-unified", kwargs={"tab": "feeds"}),
    path("settings/<str:tab>/", settings_view, name="settings-unified"),
    # Legacy routes (backwards compatibility)
    path("settings/rss/", lambda request: redirect("settings-unified", tab="feeds"), name="settings-feeds"),
    path("settings/bookmarks/", lambda request: redirect("settings-unified", tab="categories"), name="settings-bookmarks"),
    path("settings/categories/", lambda request: redirect("settings-unified", tab="categories"), name="settings-categories"),
    path("settings/tags/", lambda request: redirect("settings-unified", tab="tags"), name="settings-tags"),
    path("settings/account/", lambda request: redirect("settings-unified", tab="account"), name="settings-account"),
    # Legacy redirects
    path(
        "feeds/settings/",
        RedirectView.as_view(pattern_name="settings-feeds", permanent=True),
        name="feed-settings",
    ),
    path(
        "tags/",
        RedirectView.as_view(pattern_name="settings-tags", permanent=True),
        name="tag-list",
    ),
    # Feeds (detail views)
    path("feeds/opml/export/", export_opml_view, name="feeds-opml-export"),
    path("feeds/opml/import/", import_opml_view, name="feeds-opml-import"),
    path("feeds/<int:feed_id>/update/", feed_update_view, name="feed-update"),
]
