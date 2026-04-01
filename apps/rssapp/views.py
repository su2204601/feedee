import logging
import os
import subprocess
from urllib.parse import urlencode, urlparse

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .forms import (
    BookmarkForm,
    FeedCreateForm,
    FeedUpdateForm,
    SignupForm,
    StyledPasswordChangeForm,
    TagForm,
    UserProfileForm,
)
from .models import Article, ArticleUserState, Bookmark, Feed, Tag, UserProfile
from .serializers import (
    ArticleIngestSerializer,
    ArticleUserStateSerializer,
    FeedReorderSerializer,
    FeedSerializer,
    FetchMetadataSerializer,
)
from .utils import fetch_feed_title, fetch_url_metadata, generate_article_hash, normalize_url

logger = logging.getLogger(__name__)


class FeedListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    queryset = Feed.objects.filter(is_active=True).order_by("display_order", "id")
    serializer_class = FeedSerializer
    pagination_class = None


class FeedReorderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = FeedReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        feed_ids = serializer.validated_data["feed_ids"]
        existing_ids = set(Feed.objects.values_list("id", flat=True))
        requested_ids = list(dict.fromkeys(feed_ids))

        if (
            len(requested_ids) != len(existing_ids)
            or set(requested_ids) != existing_ids
        ):
            return Response(
                {
                    "ok": False,
                    "detail": "feed_ids must contain every existing feed exactly once.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            for order, feed_id in enumerate(requested_ids, start=1):
                Feed.objects.filter(id=feed_id).update(display_order=order)

        return Response({"ok": True}, status=status.HTTP_200_OK)


class ArticleIngestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ArticleIngestSerializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)

        created_count = 0
        skipped_count = 0

        for item in serializer.validated_data:
            normalized_link = normalize_url(item["link"])
            article_hash = generate_article_hash(
                title=item["title"],
                normalized_link=normalized_link,
                guid=item.get("guid"),
            )

            try:
                _, created = Article.objects.update_or_create(
                    hash=article_hash,
                    defaults={
                        "feed": item.get("feed"),
                        "title": item["title"],
                        "link": item["link"],
                        "normalized_link": normalized_link,
                        "guid": item.get("guid") or None,
                        "summary": item.get("summary") or "",
                        "content": item.get("content") or "",
                        "image_url": item.get("image_url") or "",
                        "published_at": item.get("published_at"),
                    },
                )
                if created:
                    created_count += 1
                else:
                    skipped_count += 1
            except IntegrityError:
                # UNIQUE violation is expected for already-ingested items.
                skipped_count += 1

        return Response(
            {
                "ok": True,
                "received": len(serializer.validated_data),
                "created": created_count,
                "skipped": skipped_count,
            },
            status=status.HTTP_200_OK,
        )


class ArticleUserStateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, article_id):
        article = get_object_or_404(Article, id=article_id)
        state = ArticleUserState.objects.filter(
            user=request.user, article=article
        ).first()
        if not state:
            return Response(
                {
                    "article": article.id,
                    "is_favorite": False,
                    "is_read_later": False,
                    "is_read": False,
                    "updated_at": None,
                },
                status=status.HTTP_200_OK,
            )

        serializer = ArticleUserStateSerializer(state)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, article_id):
        article = get_object_or_404(Article, id=article_id)
        state, _ = ArticleUserState.objects.get_or_create(
            user=request.user, article=article
        )
        serializer = ArticleUserStateSerializer(state, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


def _category_label(value):
    from .utils import category_label

    return category_label(value)


def run_rss_worker():
    """
    Execute the RSS worker asynchronously in the background.
    Logs any errors but does not block the request.
    """
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        worker_script = os.path.join(project_root, "bin", "rss-worker")
        if os.path.exists(worker_script):
            subprocess.Popen(
                [worker_script],
                cwd=project_root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            logger.info("RSS worker started in background")
        else:
            logger.warning(f"RSS worker script not found at {worker_script}")
    except Exception as e:
        logger.error(f"Failed to start RSS worker: {e}")


@login_required
def refresh_feeds_view(request):
    if request.method == "POST":
        run_rss_worker()
        messages.success(
            request,
            "Feed refresh started — new articles will appear shortly.",
        )
    return redirect("settings-feeds")


def _build_article_list_context(request, base_qs, feed_name_fn=None):
    """
    Shared logic for dashboard and feed-article views.
    Returns (article_cards, page_obj, context_dict).
    feed_name_fn: callable(article) -> str, defaults to article.feed.name.
    """
    # Load user preferences
    items_per_page = 20
    if request.user.is_authenticated:
        profile = getattr(request.user, "profile", None)
        if profile:
            items_per_page = profile.items_per_page
            if profile.default_sort == "published_asc":
                base_qs = base_qs.order_by("published_at", "created_at")

    query = request.GET.get("q", "").strip()
    state_filter = request.GET.get("state", "all").strip()
    if state_filter not in {"all", "unread", "read-later", "favorites"}:
        state_filter = "all"

    articles_qs = base_qs
    if query:
        articles_qs = articles_qs.filter(title__icontains=query)

    all_count = base_qs.count()
    favorites_count = 0
    read_later_count = 0
    unread_count = all_count
    read_count = 0

    if request.user.is_authenticated:
        user_states = ArticleUserState.objects.filter(
            user=request.user, article__in=base_qs
        )
        favorites_count = user_states.filter(is_favorite=True).count()
        read_later_count = user_states.filter(is_read_later=True).count()
        read_count = user_states.filter(is_read=True).count()

        if state_filter == "favorites":
            articles_qs = articles_qs.filter(
                user_states__user=request.user, user_states__is_favorite=True
            )
        elif state_filter == "read-later":
            articles_qs = articles_qs.filter(
                user_states__user=request.user, user_states__is_read_later=True
            )
        elif state_filter == "unread":
            articles_qs = articles_qs.exclude(
                user_states__user=request.user, user_states__is_read=True
            )

        unread_count = (
            articles_qs.count()
            if state_filter == "unread"
            else base_qs.exclude(
                user_states__user=request.user, user_states__is_read=True
            ).count()
        )
    elif state_filter in {"favorites", "read-later"}:
        articles_qs = articles_qs.none()

    paginator = Paginator(articles_qs, items_per_page)
    page_obj = paginator.get_page(request.GET.get("page"))

    article_ids = [a.id for a in page_obj.object_list]
    state_by_article_id = {}
    if request.user.is_authenticated and article_ids:
        state_by_article_id = {
            s.article_id: s
            for s in ArticleUserState.objects.filter(
                user=request.user, article_id__in=article_ids
            )
        }

    if feed_name_fn is None:
        feed_name_fn = lambda a: a.feed.name if a.feed else ""

    article_cards = []
    for article in page_obj.object_list:
        domain = urlparse(article.link).netloc
        state = state_by_article_id.get(article.id)
        article_cards.append(
            {
                "id": article.id,
                "title": article.title,
                "link": article.link,
                "domain": domain,
                "feed_name": feed_name_fn(article),
                "summary": article.summary or "",
                "image_url": article.image_url or "",
                "published_at": article.published_at,
                "created_at": article.created_at,
                "is_favorite": state.is_favorite if state else False,
                "is_read_later": state.is_read_later if state else False,
                "is_read": state.is_read if state else False,
            }
        )

    context = {
        "article_cards": article_cards,
        "page_obj": page_obj,
        "article_count": paginator.count,
        "query": query,
        "state_filter": state_filter,
        "state_filter_links": [
            {"key": "all", "label": "All", "count": all_count},
            {"key": "unread", "label": "Unread", "count": unread_count},
            {"key": "read-later", "label": "Read Later", "count": read_later_count},
            {"key": "favorites", "label": "Favorites", "count": favorites_count},
        ],
        "read_count": read_count,
    }
    return context


def signup_view(request):
    if request.user.is_authenticated:
        return redirect("rss-dashboard")

    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            User = get_user_model()
            email = form.cleaned_data["email"]
            user = User.objects.create_user(
                username=email,
                email=email,
                password=form.cleaned_data["password"],
            )
            login(request, user, backend="apps.rssapp.backends.EmailBackend")
            messages.success(request, "Account created successfully.")
            return redirect("rss-dashboard")
    else:
        form = SignupForm()

    return render(request, "auth/signup.html", {"form": form})


@login_required
def dashboard_view(request):
    base_qs = Article.objects.filter(feed__isnull=False).select_related("feed")
    context = _build_article_list_context(request, base_qs)
    context.update({"current_page": "dashboard", "breadcrumbs": []})
    return render(request, "rss/dashboard.html", context)


@login_required
def feed_settings_view(request):
    """Legacy view — redirects to unified settings."""
    return redirect("settings-feeds")


@login_required
def feed_update_view(request, feed_id):
    if request.method != "POST":
        return redirect("settings-feeds")

    feed = get_object_or_404(Feed, id=feed_id)

    # Delete action
    if request.POST.get("action") == "delete":
        name = feed.name
        feed.delete()
        messages.success(request, f"Deleted feed: {name}")
        return redirect("settings-feeds")

    form = FeedUpdateForm(request.POST, instance=feed, prefix=f"feed-{feed.id}")
    if form.is_valid():
        form.save()
        messages.success(request, f"Updated feed: {feed.name}")
    else:
        messages.error(request, "Could not update feed settings.")

    return redirect("settings-feeds")


@login_required
def settings_view(request, tab="feeds"):
    valid_tabs = ("feeds", "tags", "account")
    if tab not in valid_tabs:
        tab = "feeds"

    context = {"current_page": "settings", "active_tab": tab}

    if tab == "feeds":
        if request.method == "POST":
            form = FeedCreateForm(request.POST)
            if form.is_valid():
                try:
                    new_feed = form.save(commit=False)
                    if not new_feed.name:
                        new_feed.name = fetch_feed_title(new_feed.url) or urlparse(new_feed.url).netloc
                    max_order = (
                        Feed.objects.order_by("-display_order")
                        .values_list("display_order", flat=True)
                        .first()
                    )
                    new_feed.display_order = (max_order or 0) + 1
                    new_feed.save()
                    run_rss_worker()
                    messages.success(
                        request,
                        "Feed added. Articles are being fetched in the background — they'll appear shortly.",
                    )
                    return redirect("settings-feeds")
                except IntegrityError:
                    messages.error(request, "This feed URL is already subscribed.")
        else:
            form = FeedCreateForm()

        feeds = (
            Feed.objects.all()
            .annotate(article_count=Count("articles"))
            .order_by("display_order", "id")
        )
        feed_rows = [
            {
                "feed": feed,
                "form": FeedUpdateForm(instance=feed, prefix=f"feed-{feed.id}"),
            }
            for feed in feeds
        ]
        context.update({"feed_form": form, "feeds": feeds, "feed_rows": feed_rows})

    elif tab == "tags":
        if request.method == "POST":
            form = TagForm(request.POST)
            if form.is_valid():
                tag = form.save(commit=False)
                tag.user = request.user
                try:
                    tag.save()
                    messages.success(request, f'Tag "{tag.name}" created.')
                    return redirect("settings-tags")
                except IntegrityError:
                    messages.error(request, "A tag with this name already exists.")
        else:
            form = TagForm()

        tags = Tag.objects.filter(user=request.user).annotate(
            bookmark_count=Count("bookmarks")
        )
        tag_rows = [
            {"tag": tag, "form": TagForm(instance=tag, prefix=f"tag-{tag.id}")}
            for tag in tags
        ]
        context.update({"tag_form": form, "tags": tags, "tag_rows": tag_rows})

    elif tab == "account":
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile_form = UserProfileForm(instance=profile)
        password_form = StyledPasswordChangeForm(request.user)

        if request.method == "POST":
            action = request.POST.get("form_action", "")
            if action == "profile":
                profile_form = UserProfileForm(request.POST, instance=profile)
                if profile_form.is_valid():
                    profile_form.save()
                    messages.success(request, "Preferences saved.")
                    return redirect("settings-account")
            elif action == "password":
                password_form = StyledPasswordChangeForm(request.user, request.POST)
                if password_form.is_valid():
                    password_form.save()
                    from django.contrib.auth import update_session_auth_hash

                    update_session_auth_hash(request, password_form.user)
                    messages.success(request, "Password changed.")
                    return redirect("settings-account")

        context.update({"profile_form": profile_form, "password_form": password_form})

    return render(request, "rss/settings.html", context)


@login_required
def reader_view(request, article_id):
    article = get_object_or_404(Article.objects.select_related("feed"), id=article_id)
    state = None
    if request.user.is_authenticated:
        state = ArticleUserState.objects.filter(
            user=request.user, article=article
        ).first()
        # Auto-mark as read
        if not state:
            state = ArticleUserState.objects.create(
                user=request.user, article=article, is_read=True
            )
        elif not state.is_read:
            state.is_read = True
            state.save(update_fields=["is_read", "updated_at"])

    # Prev / Next navigation within the same feed (newer = prev, older = next)
    prev_article = None
    next_article = None
    if article.feed:
        qs = Article.objects.filter(feed=article.feed).exclude(id=article.id)
        if article.published_at is not None:
            # Newer article (prev): published later, or same time but higher id
            prev_article = (
                qs.filter(
                    Q(published_at__gt=article.published_at)
                    | Q(published_at=article.published_at, id__gt=article.id)
                )
                .order_by("published_at", "id")
                .values("id")
                .first()
            )
            # Older article (next): published earlier, or same time but lower id
            next_article = (
                qs.filter(
                    Q(published_at__lt=article.published_at)
                    | Q(published_at=article.published_at, id__lt=article.id)
                )
                .order_by("-published_at", "-id")
                .values("id")
                .first()
            )
        else:
            # Fallback to id-based ordering when published_at is not set
            prev_article = (
                qs.filter(id__gt=article.id).order_by("id").values("id").first()
            )
            next_article = (
                qs.filter(id__lt=article.id).order_by("-id").values("id").first()
            )

    return render(
        request,
        "rss/reader_view.html",
        {
            "article": article,
            "is_favorite": state.is_favorite if state else False,
            "is_read_later": state.is_read_later if state else False,
            "is_read": state.is_read if state else False,
            "prev_article": prev_article,
            "next_article": next_article,
            "current_page": "reader",
            "current_feed_id": article.feed.id if article.feed else None,
        },
    )


@login_required
def feed_articles_view(request, feed_id):
    feed = get_object_or_404(Feed, id=feed_id)
    base_qs = Article.objects.filter(feed=feed)
    context = _build_article_list_context(
        request, base_qs, feed_name_fn=lambda a: feed.name
    )
    context.update(
        {
            "feed": feed,
            "current_page": "feed-articles",
            "current_feed_id": feed.id,
        }
    )
    return render(request, "rss/feed_articles.html", context)


@login_required
def article_state_toggle_view(request, article_id, state_field):
    if request.method != "POST":
        return redirect("rss-dashboard")

    redirect_params = {}
    q = request.POST.get("q", "").strip()
    page = request.POST.get("page", "").strip()
    state = request.POST.get("state", "all").strip()
    next_url = request.POST.get("next", "").strip()
    if q:
        redirect_params["q"] = q
    if page:
        redirect_params["page"] = page
    if state and state != "all":
        redirect_params["state"] = state

    redirect_url = reverse("rss-dashboard")
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts=None):
        redirect_url = next_url
    if redirect_params:
        redirect_url = f"{redirect_url}?{urlencode(redirect_params)}"

    allowed_fields = {"is_favorite", "is_read_later", "is_read"}
    if state_field not in allowed_fields:
        messages.error(request, "Invalid state action.")
        return redirect(redirect_url)

    article = get_object_or_404(Article, id=article_id)
    state, _ = ArticleUserState.objects.get_or_create(
        user=request.user, article=article
    )
    current_value = getattr(state, state_field)
    setattr(state, state_field, not current_value)
    state.save(update_fields=[state_field, "updated_at"])

    return redirect(redirect_url)


@login_required
def mark_all_read_view(request):
    if request.method != "POST":
        return redirect("rss-dashboard")

    feed_id = request.POST.get("feed_id", "").strip()
    state_filter = request.POST.get("state", "all").strip()
    query = request.POST.get("q", "").strip()

    articles_qs = Article.objects.filter(feed__isnull=False)
    redirect_url = reverse("rss-dashboard")

    if feed_id:
        feed = get_object_or_404(Feed, id=feed_id)
        articles_qs = articles_qs.filter(feed=feed)
        redirect_url = reverse("feed-articles", args=[feed.id])

    if query:
        articles_qs = articles_qs.filter(title__icontains=query)

    if state_filter == "unread":
        articles_qs = articles_qs.exclude(
            user_states__user=request.user, user_states__is_read=True
        )

    with transaction.atomic():
        article_ids = list(articles_qs.values_list("id", flat=True))
        existing_ids = set(
            ArticleUserState.objects.filter(
                user=request.user, article_id__in=article_ids
            ).values_list("article_id", flat=True)
        )
        ArticleUserState.objects.filter(
            user=request.user, article_id__in=existing_ids
        ).update(is_read=True)
        new_states = [
            ArticleUserState(user=request.user, article_id=aid, is_read=True)
            for aid in article_ids
            if aid not in existing_ids
        ]
        if new_states:
            ArticleUserState.objects.bulk_create(new_states)

    messages.success(request, "All articles marked as read.")
    return redirect(redirect_url)


# ── Fetch Metadata API ──────────────────────────────────


class FetchMetadataView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = FetchMetadataSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        metadata = fetch_url_metadata(serializer.validated_data["url"])
        return Response(metadata, status=status.HTTP_200_OK)


class FetchFeedTitleView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        url = request.data.get("url", "").strip()
        if not url:
            return Response({"title": ""}, status=status.HTTP_400_BAD_REQUEST)
        title = fetch_feed_title(url)
        return Response({"title": title}, status=status.HTTP_200_OK)


# ── Bookmark views ──────────────────────────────────────


@login_required
def bookmark_list_view(request):

    query = request.GET.get("q", "").strip()
    tag_slug = request.GET.get("tag", "").strip()

    bookmarks_qs = Bookmark.objects.filter(user=request.user).prefetch_related("tags")
    if query:
        bookmarks_qs = bookmarks_qs.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(url__icontains=query)
        )
    if tag_slug:
        bookmarks_qs = bookmarks_qs.filter(tags__slug=tag_slug)

    tags = Tag.objects.filter(user=request.user).annotate(
        bookmark_count=Count("bookmarks")
    )

    paginator = Paginator(bookmarks_qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    bookmark_cards = []
    for bm in page_obj.object_list:
        domain = urlparse(bm.url).netloc
        bookmark_cards.append(
            {
                "id": bm.id,
                "url": bm.url,
                "title": bm.title,
                "description": bm.description,
                "thumbnail_url": bm.thumbnail_url,
                "domain": domain,
                "tags": list(bm.tags.all()),
                "created_at": bm.created_at,
                "source_article_id": bm.source_article_id,
            }
        )

    return render(
        request,
        "bookmarks/bookmark_list.html",
        {
            "bookmark_cards": bookmark_cards,
            "page_obj": page_obj,
            "bookmark_count": bookmarks_qs.count(),
            "query": query,
            "tag_slug": tag_slug,
            "tags": tags,
            "current_page": "bookmarks",
        },
    )


def _save_bookmark_tags(bookmark, tag_names_str, user):
    """Parse comma-separated tag names, create missing tags, then set on bookmark."""
    tag_names = [name.strip() for name in tag_names_str.split(",") if name.strip()]
    tags = []
    for name in tag_names:
        from django.utils.text import slugify

        slug = slugify(name, allow_unicode=True)
        tag, _ = Tag.objects.get_or_create(
            user=user, slug=slug, defaults={"name": name}
        )
        tags.append(tag)
    bookmark.tags.set(tags)


@login_required
def bookmark_add_view(request):

    if request.method == "POST":
        form = BookmarkForm(request.POST)
        if form.is_valid():
            bookmark = form.save(commit=False)
            bookmark.user = request.user
            # Store thumbnail from hidden field
            bookmark.thumbnail_url = request.POST.get("thumbnail_url", "")
            # Auto-fetch title if not provided
            if not bookmark.title.strip():
                from .utils import fetch_url_metadata
                meta = fetch_url_metadata(bookmark.url)
                bookmark.title = meta.get("title", "") or bookmark.url
                if not bookmark.description.strip() and meta.get("description"):
                    bookmark.description = meta["description"]
                if not bookmark.thumbnail_url and meta.get("thumbnail_url"):
                    bookmark.thumbnail_url = meta["thumbnail_url"]
            # Link to source article if provided
            source_id = request.POST.get("source_article_id", "").strip()
            if source_id:
                try:
                    article = get_object_or_404(Article, id=int(source_id))
                    bookmark.source_article = article
                except (ValueError, TypeError):
                    pass
            try:
                bookmark.save()
                _save_bookmark_tags(
                    bookmark, form.cleaned_data.get("tag_names", ""), request.user
                )
                messages.success(request, "Bookmark added.")
                return redirect("bookmark-list")
            except IntegrityError:
                messages.error(request, "This URL is already bookmarked.")
    else:
        form = BookmarkForm()

    existing_tags = Tag.objects.filter(user=request.user).order_by("name")
    return render(
        request,
        "bookmarks/bookmark_form.html",
        {
            "form": form,
            "existing_tags": existing_tags,
            "edit_mode": False,
            "current_page": "bookmarks",
        },
    )


@login_required
def bookmark_edit_view(request, bookmark_id):

    bookmark = get_object_or_404(Bookmark, id=bookmark_id, user=request.user)

    if request.method == "POST":
        form = BookmarkForm(request.POST, instance=bookmark)
        if form.is_valid():
            bm = form.save(commit=False)
            bm.thumbnail_url = request.POST.get("thumbnail_url", bookmark.thumbnail_url)
            bm.save()
            _save_bookmark_tags(
                bm, form.cleaned_data.get("tag_names", ""), request.user
            )
            messages.success(request, "Bookmark updated.")
            return redirect("bookmark-list")
    else:
        tag_names = ", ".join(t.name for t in bookmark.tags.all())
        form = BookmarkForm(instance=bookmark, initial={"tag_names": tag_names})

    existing_tags = Tag.objects.filter(user=request.user).order_by("name")
    return render(
        request,
        "bookmarks/bookmark_form.html",
        {
            "form": form,
            "bookmark": bookmark,
            "existing_tags": existing_tags,
            "edit_mode": True,
            "current_page": "bookmarks",
        },
    )


@login_required
def bookmark_delete_view(request, bookmark_id):
    if request.method != "POST":
        return redirect("bookmark-list")
    bookmark = get_object_or_404(Bookmark, id=bookmark_id, user=request.user)
    bookmark.delete()
    messages.success(request, "Bookmark deleted.")
    return redirect("bookmark-list")


@login_required
def bookmark_from_article_view(request, article_id):
    """Pre-fill bookmark form from an RSS article."""

    article = get_object_or_404(Article, id=article_id)

    # If already bookmarked, redirect to edit
    existing = Bookmark.objects.filter(user=request.user, url=article.link).first()
    if existing:
        messages.info(request, "This article is already bookmarked.")
        return redirect("bookmark-edit", bookmark_id=existing.id)

    form = BookmarkForm(
        initial={
            "url": article.link,
            "title": article.title,
            "description": article.summary or "",
        }
    )

    existing_tags = Tag.objects.filter(user=request.user).order_by("name")
    return render(
        request,
        "bookmarks/bookmark_form.html",
        {
            "form": form,
            "source_article_id": article.id,
            "existing_tags": existing_tags,
            "edit_mode": False,
            "current_page": "bookmarks",
        },
    )


# ── Tag views ───────────────────────────────────────────


@login_required
def tag_list_view(request):

    if request.method == "POST":
        form = TagForm(request.POST)
        if form.is_valid():
            tag = form.save(commit=False)
            tag.user = request.user
            try:
                tag.save()
                messages.success(request, f'Tag "{tag.name}" created.')
                return redirect("tag-list")
            except IntegrityError:
                messages.error(request, "A tag with this name already exists.")
    else:
        form = TagForm()

    tags = Tag.objects.filter(user=request.user).annotate(
        bookmark_count=Count("bookmarks")
    )

    tag_rows = [
        {"tag": tag, "form": TagForm(instance=tag, prefix=f"tag-{tag.id}")}
        for tag in tags
    ]

    return render(
        request,
        "bookmarks/tag_list.html",
        {
            "tag_form": form,
            "tags": tags,
            "tag_rows": tag_rows,
            "current_page": "tag-settings",
        },
    )


@login_required
def tag_update_view(request, tag_id):
    if request.method != "POST":
        return redirect("settings-tags")

    tag = get_object_or_404(Tag, id=tag_id, user=request.user)

    if request.POST.get("action") == "delete":
        name = tag.name
        tag.delete()
        messages.success(request, f"Deleted tag: {name}")
        return redirect("settings-tags")

    form = TagForm(request.POST, instance=tag, prefix=f"tag-{tag.id}")
    if form.is_valid():
        t = form.save(commit=False)
        t.user = request.user
        t.save()
        messages.success(request, f"Updated tag: {t.name}")
    else:
        messages.error(request, "Could not update tag.")

    return redirect("settings-tags")
