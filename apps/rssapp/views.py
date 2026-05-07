import json
import logging
import os
import subprocess
import xml.etree.ElementTree as ET
from datetime import timedelta
from urllib.parse import quote_plus, urlencode, urlparse

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Case, Count, Exists, IntegerField, OuterRef, Q, Value, When
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .forms import (
    BookmarkForm,
    BookmarkCategoryForm,
    FeedCreateForm,
    FeedUpdateForm,
    SignUpForm,
    StyledPasswordChangeForm,
    TagForm,
    UserProfileForm,
)
from .models import (
    Article,
    ArticleUserState,
    Bookmark,
    BookmarkUserState,
    BookmarkCategory,
    Feed,
    Tag,
    UserProfile,
)
from .serializers import (
    ArticleIngestSerializer,
    ArticleUserStateSerializer,
    DisplayModePreferenceSerializer,
    FeedFetchStatusSerializer,
    FeedReorderSerializer,
    FeedSerializer,
    FetchMetadataSerializer,
)
from .utils import (
    extract_article_content,
    fetch_url_metadata,
    generate_article_hash,
    normalize_url,
)

logger = logging.getLogger(__name__)

DISPLAY_MODES = {"list", "compact", "card"}


def _resolve_display_mode(request):
    requested_mode = (request.GET.get("mode") or "").strip().lower()
    profile_mode = "compact"

    if request.user.is_authenticated:
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile_mode = profile.default_display_mode or "compact"
        if requested_mode in DISPLAY_MODES and requested_mode != profile_mode:
            profile.default_display_mode = requested_mode
            profile.save(update_fields=["default_display_mode"])
            return requested_mode

    if requested_mode in DISPLAY_MODES:
        return requested_mode
    if profile_mode in DISPLAY_MODES:
        return profile_mode
    return "compact"


class FeedListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = FeedSerializer
    pagination_class = None

    def get_queryset(self):
        now = timezone.now()
        return (
            Feed.objects.filter(is_active=True)
            .filter(Q(next_fetch_at__isnull=True) | Q(next_fetch_at__lte=now))
            .order_by("display_order", "id")
        )


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


def _update_feed_fetch_state(
    feed,
    *,
    status: str,
    item_count: int = 0,
    error: str = "",
    etag: str = "",
    last_modified: str = "",
):
    now = timezone.now()
    feed.last_fetched_at = now

    if etag:
        feed.etag = etag
    if last_modified:
        feed.last_modified = last_modified

    if status in {"success", "not_modified"}:
        feed.last_success_at = now
        feed.last_error = ""
        feed.consecutive_failures = 0

        if status == "success" and item_count > 0:
            next_interval = max(15, min(feed.fetch_interval_minutes, 60))
        elif status == "not_modified":
            next_interval = min(max(feed.fetch_interval_minutes, 30) * 2, 240)
        else:
            next_interval = min(max(feed.fetch_interval_minutes, 30), 120)

        feed.fetch_interval_minutes = next_interval
        feed.next_fetch_at = now + timedelta(minutes=next_interval)
    else:
        feed.consecutive_failures += 1
        feed.last_error = (error or "Fetch failed").strip()
        next_interval = min(60 * max(feed.consecutive_failures, 1), 240)
        feed.fetch_interval_minutes = next_interval
        feed.next_fetch_at = now + timedelta(minutes=next_interval)
        if feed.consecutive_failures >= 5:
            feed.is_active = False

    feed.save(
        update_fields=[
            "last_fetched_at",
            "last_success_at",
            "last_error",
            "consecutive_failures",
            "etag",
            "last_modified",
            "next_fetch_at",
            "fetch_interval_minutes",
            "is_active",
        ]
    )


class FeedFetchStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, feed_id):
        feed = get_object_or_404(Feed, id=feed_id)
        serializer = FeedFetchStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        _update_feed_fetch_state(
            feed,
            status=serializer.validated_data["status"],
            item_count=serializer.validated_data.get("item_count", 0),
            error=serializer.validated_data.get("error") or "",
            etag=serializer.validated_data.get("etag") or "",
            last_modified=serializer.validated_data.get("last_modified") or "",
        )

        return Response(
            {
                "ok": True,
                "next_fetch_at": feed.next_fetch_at,
                "consecutive_failures": feed.consecutive_failures,
                "is_active": feed.is_active,
            },
            status=status.HTTP_200_OK,
        )


class ArticleIngestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ArticleIngestSerializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)

        created_count = 0
        skipped_count = 0
        batch_size = len(serializer.validated_data)
        sync_extraction_limit = max(
            int(getattr(settings, "FULL_TEXT_EXTRACTION_SYNC_LIMIT", 1) or 0),
            0,
        )
        extraction_enabled = getattr(settings, "FULL_TEXT_EXTRACTION_ENABLED", True)
        allow_inline_extraction = (
            extraction_enabled and batch_size <= sync_extraction_limit
        )

        if extraction_enabled and batch_size > sync_extraction_limit:
            logger.info(
                "Queueing full-text extraction for ingest batch of %d articles (limit=%d)",
                batch_size,
                sync_extraction_limit,
            )

        for item in serializer.validated_data:
            normalized_link = normalize_url(item["link"])
            article_hash = generate_article_hash(
                title=item["title"],
                normalized_link=normalized_link,
                guid=item.get("guid"),
            )
            summary = item.get("summary") or ""
            content = item.get("content") or ""
            content_source = "feed" if content else ("summary" if summary else "empty")
            extraction_status = "provided" if content else "pending"
            extracted_at = None

            existing_article = Article.objects.filter(hash=article_hash).first()
            if not content and existing_article and existing_article.content:
                content = existing_article.content
                content_source = existing_article.content_source or "extracted"
                extraction_status = existing_article.extraction_status or "success"
                extracted_at = existing_article.extracted_at
            elif not content and allow_inline_extraction:
                extraction = extract_article_content(item["link"])
                extracted_content = extraction.get("content") or ""
                extraction_status = extraction.get("status") or "failed"
                if extracted_content:
                    content = extracted_content
                    content_source = extraction.get("source") or "extracted"
                    extracted_at = timezone.now()
                else:
                    content_source = "summary" if summary else "empty"
                    extraction_status = "skipped"

            try:
                article, created = Article.objects.update_or_create(
                    hash=article_hash,
                    defaults={
                        "feed": item.get("feed"),
                        "title": item["title"],
                        "link": item["link"],
                        "normalized_link": normalized_link,
                        "guid": item.get("guid") or None,
                        "summary": summary,
                        "content": content,
                        "content_source": content_source,
                        "extraction_status": extraction_status,
                        "extracted_at": extracted_at,
                        "image_url": item.get("image_url") or "",
                        "published_at": item.get("published_at"),
                    },
                )
                if created:
                    created_count += 1
                else:
                    skipped_count += 1

                # Queue extraction if content is missing and extraction is enabled
                if (
                    extraction_enabled
                    and not content
                    and extraction_status == "pending"
                ):
                    from apps.rssapp.models import ExtractionTask

                    ExtractionTask.objects.get_or_create(
                        article=article,
                        defaults={"status": "pending"},
                    )

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


class DisplayModePreferenceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        return Response(
            {"mode": profile.default_display_mode}, status=status.HTTP_200_OK
        )

    def patch(self, request):
        serializer = DisplayModePreferenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile.default_display_mode = serializer.validated_data["mode"]
        profile.save(update_fields=["default_display_mode"])
        return Response(
            {"mode": profile.default_display_mode}, status=status.HTTP_200_OK
        )


def _category_label(value):
    from .utils import category_label

    return category_label(value)


def run_rss_worker():
    """
    Execute the RSS worker asynchronously in the background.
    Logs any errors but does not block the request.
    """
    try:
        worker_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "bin",
            "rss-worker",
        )
        if os.path.exists(worker_script):
            subprocess.Popen(
                [worker_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            logger.info("RSS worker started in background")
        else:
            logger.warning(f"RSS worker script not found at {worker_script}")
    except Exception as e:
        logger.error(f"Failed to start RSS worker: {e}")


def _build_opml_document(feeds):
    root = ET.Element("opml", version="2.0", title="Feedee Subscriptions")
    head = ET.SubElement(root, "head")
    ET.SubElement(head, "title").text = "Feedee Subscriptions"
    body = ET.SubElement(root, "body")

    category_nodes = {}
    for feed in feeds:
        category = (feed.category or "").strip()
        parent = body
        if category:
            parent = category_nodes.get(category)
            if parent is None:
                parent = ET.SubElement(body, "outline", text=category, title=category)
                category_nodes[category] = parent
        ET.SubElement(
            parent,
            "outline",
            text=feed.name,
            title=feed.name,
            type="rss",
            xmlUrl=feed.url,
            category=category,
        )

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _iter_opml_feed_entries(node, inherited_category=""):
    xml_url = (node.attrib.get("xmlUrl") or node.attrib.get("xmlurl") or "").strip()
    if xml_url:
        yield {
            "name": (
                node.attrib.get("title") or node.attrib.get("text") or xml_url
            ).strip(),
            "url": xml_url,
            "category": inherited_category.strip(),
        }
        return

    current_category = (
        node.attrib.get("title") or node.attrib.get("text") or inherited_category
    )
    for child in node.findall("outline"):
        yield from _iter_opml_feed_entries(child, current_category)


@login_required
def export_opml_view(request):
    feeds = Feed.objects.all().order_by("category", "display_order", "id")
    xml_bytes = _build_opml_document(feeds)
    response = HttpResponse(xml_bytes, content_type="application/xml")
    response["Content-Disposition"] = 'attachment; filename="feedee.opml"'
    return response


@login_required
def import_opml_view(request):
    if request.method != "POST":
        return redirect("settings-feeds")

    upload = request.FILES.get("opml_file")
    if not upload:
        messages.error(request, "Please choose an OPML file to import.")
        return redirect("settings-feeds")

    try:
        root = ET.fromstring(upload.read())
    except ET.ParseError:
        messages.error(request, "The uploaded OPML file could not be parsed.")
        return redirect("settings-feeds")

    existing_urls = {
        normalize_url(url): url for url in Feed.objects.values_list("url", flat=True)
    }
    imported = 0
    skipped = 0
    next_order = (
        Feed.objects.order_by("-display_order").first().display_order
        if Feed.objects.exists()
        else 0
    )

    for outline in root.findall("./body/outline"):
        for entry in _iter_opml_feed_entries(outline):
            normalized = normalize_url(entry["url"])
            if normalized in existing_urls:
                skipped += 1
                continue

            next_order += 1
            Feed.objects.create(
                name=entry["name"] or urlparse(entry["url"]).netloc,
                url=entry["url"],
                category=(entry["category"] or "").strip(),
                display_order=next_order,
            )
            existing_urls[normalized] = entry["url"]
            imported += 1

    messages.success(
        request,
        f"Imported {imported} feed{'s' if imported != 1 else ''}. Skipped {skipped} duplicate{'s' if skipped != 1 else ''}.",
    )
    if imported:
        run_rss_worker()
    return redirect("settings-feeds")


def register_view(request):
    if request.user.is_authenticated:
        return redirect("homepage")

    next_url = request.POST.get("next") or request.GET.get("next", "")

    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            UserProfile.objects.get_or_create(user=user)
            login(request, user, backend="apps.rssapp.backends.EmailBackend")
            messages.success(request, "Account created. Welcome to Feedee.")

            if next_url and url_has_allowed_host_and_scheme(
                next_url, allowed_hosts={request.get_host()}
            ):
                return redirect(next_url)
            return redirect("homepage")
    else:
        form = SignUpForm()

    return render(request, "auth/register.html", {"form": form, "next": next_url})


def _build_article_list_context(request, base_qs, feed_name_fn=None):
    """
    Shared logic for dashboard and feed-article views.
    Returns (article_cards, page_obj, context_dict).
    feed_name_fn: callable(article) -> str, defaults to article.feed.name.
    """
    # Load user preferences
    items_per_page = 20
    profile_sort = "published_desc"
    if request.user.is_authenticated:
        profile = getattr(request.user, "profile", None)
        if profile:
            items_per_page = profile.items_per_page
            profile_sort = profile.default_sort

    sort_mode = request.GET.get("sort", "").strip()
    if sort_mode not in {"latest", "oldest", "smart"}:
        sort_mode = "oldest" if profile_sort == "published_asc" else "latest"

    query = request.GET.get("q", "").strip()
    state_filter = request.GET.get("state", "all").strip()
    if state_filter not in {"all", "unread", "read-later"}:
        state_filter = "all"

    articles_qs = base_qs
    if query:
        articles_qs = articles_qs.filter(
            Q(title__icontains=query)
            | Q(summary__icontains=query)
            | Q(content__icontains=query)
        )

    all_count = base_qs.count()
    read_later_count = 0
    unread_count = all_count
    read_count = 0

    if request.user.is_authenticated:
        user_states = ArticleUserState.objects.filter(
            user=request.user, article__in=base_qs
        )
        read_later_count = user_states.filter(is_read_later=True).count()
        read_count = user_states.filter(is_read=True).count()

        if state_filter == "read-later":
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
    elif state_filter == "read-later":
        articles_qs = articles_qs.none()

    if sort_mode == "smart" and request.user.is_authenticated:
        state_base = ArticleUserState.objects.filter(
            user=request.user, article=OuterRef("pk")
        )
        articles_qs = (
            articles_qs.annotate(
                state_is_read=Exists(state_base.filter(is_read=True)),
                state_is_read_later=Exists(state_base.filter(is_read_later=True)),
            )
            .annotate(
                smart_bucket=Case(
                    When(
                        state_is_read=False,
                        state_is_read_later=True,
                        then=Value(0),
                    ),
                    When(state_is_read=False, then=Value(1)),
                    default=Value(2),
                    output_field=IntegerField(),
                )
            )
            .order_by(
                "smart_bucket",
                "-state_is_read_later",
                "-published_at",
                "-created_at",
            )
        )
    elif sort_mode == "oldest":
        articles_qs = articles_qs.order_by("published_at", "created_at")
    else:
        articles_qs = articles_qs.order_by("-published_at", "-created_at")

    paginator = Paginator(articles_qs, items_per_page)
    page_obj = paginator.get_page(request.GET.get("page"))
    display_mode = _resolve_display_mode(request)

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
        "sort_mode": sort_mode,
        "sort_links": [
            {"key": "latest", "label": "Latest"},
            {"key": "oldest", "label": "Oldest"},
            {"key": "smart", "label": "Smart"},
        ],
        "state_filter_links": [
            {"key": "all", "label": "All", "count": all_count},
            {"key": "unread", "label": "Unread", "count": unread_count},
            {"key": "read-later", "label": "Read Later", "count": read_later_count},
        ],
        "read_count": read_count,
        "display_mode": display_mode,
        "display_mode_links": [
            {"key": "list", "label": "List"},
            {"key": "compact", "label": "Compact"},
            {"key": "card", "label": "Card"},
        ],
    }
    return context


def dashboard_view(request):
    base_qs = Article.objects.filter(feed__isnull=False).select_related("feed")
    context = _build_article_list_context(request, base_qs)
    context.update({"current_page": "dashboard", "breadcrumbs": []})
    return render(request, "rss/dashboard.html", context)


def homepage_view(request):
    """Legacy endpoint for old homepage template."""
    return redirect("homepage")


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
@login_required
def settings_view(request, tab="feeds"):
    """Unified settings page with tabs: feeds, tags, categories, account."""
    valid_tabs = ["feeds", "tags", "categories", "account"]
    if tab not in valid_tabs:
        return redirect("settings-unified", permanent=False)

    context = {"current_page": "settings", "active_tab": tab}

    # ── Feeds Tab ──────────────────────────────────────
    if tab == "feeds":
        if request.method == "POST":
            form = FeedCreateForm(request.POST)
            if form.is_valid():
                try:
                    new_feed = form.save(commit=False)
                    max_order = (
                        Feed.objects.order_by("-display_order")
                        .values_list("display_order", flat=True)
                        .first()
                    )
                    new_feed.display_order = (max_order or 0) + 1
                    new_feed.save()
                    run_rss_worker()
                    if getattr(form, "discovery_used", False):
                        messages.success(
                            request,
                            f"✓ Feed added: {new_feed.name}. Automatically discovered feed URL from the website. Articles will appear shortly.",
                        )
                    else:
                        messages.success(
                            request,
                            f"✓ Feed added: {new_feed.name}. Fetching articles in the background...",
                        )
                    return redirect("/settings/feeds/")
                except IntegrityError:
                    messages.error(request, "This feed URL is already subscribed.")
            else:
                for field_errors in form.errors.values():
                    for error in field_errors:
                        messages.error(request, error)

                # Log discovery errors for debugging
                if hasattr(form, 'discovery_error') and form.discovery_error:
                    logger.warning(
                        f"Feed discovery failed: {form.discovery_error} - URL: {request.POST.get('url', 'N/A')}"
                    )
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

    # ── Categories Tab ─────────────────────────────────
    elif tab == "categories":
        if request.method == "POST":
            form = BookmarkCategoryForm(request.POST)
            if form.is_valid():
                category = form.save(commit=False)
                category.user = request.user
                try:
                    category.save()
                    messages.success(request, f'Category "{category.name}" created.')
                    return redirect("/settings/categories/")
                except IntegrityError:
                    messages.error(request, "A category with this name already exists.")
        else:
            form = BookmarkCategoryForm()

        categories = (
            BookmarkCategory.objects.filter(user=request.user)
            .annotate(bookmark_count=Count("bookmarks"))
            .order_by("display_order", "name")
        )
        category_rows = [
            {
                "category": cat,
                "form": BookmarkCategoryForm(instance=cat, prefix=f"cat-{cat.id}"),
            }
            for cat in categories
        ]
        context.update(
            {
                "category_form": form,
                "categories": categories,
                "category_rows": category_rows,
            }
        )

    # ── Tags Tab ───────────────────────────────────────
    elif tab == "tags":
        if request.method == "POST":
            form = TagForm(request.POST)
            if form.is_valid():
                tag = form.save(commit=False)
                tag.user = request.user
                try:
                    tag.save()
                    messages.success(request, f'Tag "{tag.name}" created.')
                    return redirect("/settings/tags/")
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

    # ── Account Tab ────────────────────────────────────
    elif tab == "account":
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile_form = UserProfileForm(instance=profile)
        password_form = StyledPasswordChangeForm(request.user)

        if request.method == "POST":
            action = request.POST.get("form_action", "")
            if action == "profile":
                profile_payload = request.POST.copy()
                for field in UserProfileForm.Meta.fields:
                    if field not in profile_payload:
                        profile_payload[field] = getattr(profile, field)

                profile_form = UserProfileForm(profile_payload, instance=profile)
                if profile_form.is_valid():
                    profile_form.save()
                    messages.success(request, "Preferences saved.")
                    return redirect("/settings/account/")
            elif action == "password":
                password_form = StyledPasswordChangeForm(request.user, request.POST)
                if password_form.is_valid():
                    password_form.save()
                    from django.contrib.auth import update_session_auth_hash

                    update_session_auth_hash(request, password_form.user)
                    messages.success(request, "Password changed.")
                    return redirect("/settings/account/")

        context.update({"profile_form": profile_form, "password_form": password_form})

    return render(request, "rss/settings.html", context)


@login_required
def rss_settings_view(request):
    context = {"current_page": "settings", "active_tab": "feeds"}

    if request.method == "POST":
        form = FeedCreateForm(request.POST)
        if form.is_valid():
            try:
                new_feed = form.save(commit=False)
                max_order = (
                    Feed.objects.order_by("-display_order")
                    .values_list("display_order", flat=True)
                    .first()
                )
                new_feed.display_order = (max_order or 0) + 1
                new_feed.save()
                run_rss_worker()
                if getattr(form, "discovery_used", False):
                    messages.success(
                        request,
                        f"✓ Feed added: {new_feed.name}. Automatically discovered feed URL from the website. Articles will appear shortly.",
                    )
                else:
                    messages.success(
                        request,
                        f"✓ Feed added: {new_feed.name}. Fetching articles in the background...",
                    )
                return redirect("settings-feeds")
            except IntegrityError:
                messages.error(request, "This feed URL is already subscribed.")
        else:
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)

            # Log discovery errors for debugging
            if hasattr(form, 'discovery_error') and form.discovery_error:
                logger.warning(
                    f"Feed discovery failed: {form.discovery_error} - URL: {request.POST.get('url', 'N/A')}"
                )
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
    return render(request, "rss/settings_rss.html", context)


@login_required
def bookmark_settings_view(request, tab="categories"):
    if tab not in ("categories", "tags"):
        tab = "categories"

    context = {"current_page": "settings", "active_tab": tab}

    if tab == "categories":
        if request.method == "POST":
            form = BookmarkCategoryForm(request.POST)
            if form.is_valid():
                category = form.save(commit=False)
                category.user = request.user
                try:
                    category.save()
                    messages.success(request, f'Category "{category.name}" created.')
                    return redirect("settings-categories")
                except IntegrityError:
                    messages.error(request, "A category with this name already exists.")
        else:
            form = BookmarkCategoryForm()

        categories = (
            BookmarkCategory.objects.filter(user=request.user)
            .annotate(bookmark_count=Count("bookmarks"))
            .order_by("display_order", "name")
        )
        category_rows = [
            {
                "category": cat,
                "form": BookmarkCategoryForm(instance=cat, prefix=f"cat-{cat.id}"),
            }
            for cat in categories
        ]
        context.update(
            {
                "category_form": form,
                "categories": categories,
                "category_rows": category_rows,
            }
        )
    else:
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

    return render(request, "rss/settings_bookmarks.html", context)


@login_required
def account_settings_view(request):
    context = {"current_page": "settings", "active_tab": "account"}

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    profile_form = UserProfileForm(instance=profile)
    password_form = StyledPasswordChangeForm(request.user)

    if request.method == "POST":
        action = request.POST.get("form_action", "")
        if action == "profile":
            profile_payload = request.POST.copy()
            for field in UserProfileForm.Meta.fields:
                if field not in profile_payload:
                    profile_payload[field] = getattr(profile, field)

            profile_form = UserProfileForm(profile_payload, instance=profile)
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
    return render(request, "rss/settings_account.html", context)


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
            "is_read_later": state.is_read_later if state else False,
            "is_read": state.is_read if state else False,
            "prev_article": prev_article,
            "next_article": next_article,
            "current_page": "reader",
            "current_feed_id": article.feed.id if article.feed else None,
        },
    )


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


def article_state_toggle_view(request, article_id, state_field):
    if request.method != "POST":
        return redirect("feeds-page")

    redirect_params = {}
    q = request.POST.get("q", "").strip()
    page = request.POST.get("page", "").strip()
    state = request.POST.get("state", "all").strip()
    mode = request.POST.get("mode", "").strip()
    next_url = request.POST.get("next", "").strip()
    if q:
        redirect_params["q"] = q
    if page:
        redirect_params["page"] = page
    if state and state != "all":
        redirect_params["state"] = state
    if mode in DISPLAY_MODES:
        redirect_params["mode"] = mode

    redirect_url = reverse("feeds-page")
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts=None):
        redirect_url = next_url
    if redirect_params:
        redirect_url = f"{redirect_url}?{urlencode(redirect_params)}"

    if not request.user.is_authenticated:
        messages.error(request, "Please log in to update article state.")
        return redirect(redirect_url)

    allowed_fields = {"is_read_later", "is_read"}
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


def bookmark_state_toggle_view(request, bookmark_id, state_field):
    if request.method != "POST":
        return redirect("bookmarks-page")

    next_url = request.POST.get("next", "").strip()
    redirect_url = reverse("bookmarks-page")
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts=None):
        redirect_url = next_url

    if not request.user.is_authenticated:
        messages.error(request, "Please log in to update bookmark state.")
        return redirect(redirect_url)

    allowed_fields = {"is_read_later", "is_read", "is_pinned"}
    if state_field not in allowed_fields:
        messages.error(request, "Invalid bookmark state action.")
        return redirect(redirect_url)

    bookmark = get_object_or_404(Bookmark, id=bookmark_id, user=request.user)
    state, _ = BookmarkUserState.objects.get_or_create(
        user=request.user, bookmark=bookmark
    )
    current_value = getattr(state, state_field)
    setattr(state, state_field, not current_value)
    state.save(update_fields=[state_field, "updated_at"])

    return redirect(redirect_url)


def mark_all_read_view(request):
    if request.method != "POST":
        return redirect("feeds-page")

    if not request.user.is_authenticated:
        messages.error(request, "Please log in to mark articles as read.")
        return redirect("feeds-page")

    feed_id = request.POST.get("feed_id", "").strip()
    selected_category = request.POST.get("category", "").strip()
    state_filter = request.POST.get("state", "all").strip()
    query = request.POST.get("q", "").strip()
    mode = request.POST.get("mode", "").strip()

    articles_qs = Article.objects.filter(feed__isnull=False)
    redirect_url = reverse("feeds-page")
    redirect_params = {}

    if feed_id:
        feed = get_object_or_404(Feed, id=feed_id)
        articles_qs = articles_qs.filter(feed=feed)
        redirect_url = reverse("feed-articles", args=[feed.id])
    elif selected_category:
        articles_qs = articles_qs.filter(feed__category=selected_category)
        redirect_params["category"] = selected_category

    if query:
        articles_qs = articles_qs.filter(title__icontains=query)
        redirect_params["q"] = query

    if state_filter == "unread":
        articles_qs = articles_qs.exclude(
            user_states__user=request.user, user_states__is_read=True
        )
        redirect_params["state"] = state_filter

    if mode in DISPLAY_MODES:
        redirect_params["mode"] = mode

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
    if redirect_params:
        return redirect(f"{redirect_url}?{urlencode(redirect_params)}")
    return redirect(redirect_url)


# ── Fetch Metadata API ──────────────────────────────────


class FetchMetadataView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = FetchMetadataSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        metadata = fetch_url_metadata(serializer.validated_data["url"])
        return Response(metadata, status=status.HTTP_200_OK)


class BookmarkletCreateView(APIView):
    """
    Lightweight API endpoint for bookmarklet requests.
    Accepts token or session authentication.
    POST /api/bookmarklet/create/ with JSON payload:
    {
        "url": "https://example.com",
        "title": "Example (optional)",
        "description": "Optional description",
        "tags": "tag1,tag2",
        "category_id": 1 (optional)
    }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .serializers import BookmarkletCreateSerializer
        from .utils import normalize_url, generate_bookmark_hash

        user = request.user
        serializer = BookmarkletCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        url = serializer.validated_data["url"]
        title = serializer.validated_data.get("title", "").strip()
        description = serializer.validated_data.get("description", "").strip()
        tags_str = serializer.validated_data.get("tags", "").strip()
        category_id = serializer.validated_data.get("category_id")

        # Auto-fetch metadata if title is missing
        if not title:
            metadata = fetch_url_metadata(url)
            title = metadata.get("title") or urlparse(url).netloc

        # Compute normalized URL and hash
        normalized_url = normalize_url(url)
        hash_value = generate_bookmark_hash(normalized_url) if normalized_url else ""

        # Check for existing bookmark
        existing = Bookmark.objects.filter(user=user, url=url).first()
        if existing:
            return Response(
                {
                    "ok": False,
                    "error": "Bookmark already exists",
                    "bookmark_id": existing.id,
                },
                status=status.HTTP_409_CONFLICT,
            )

        try:
            # Create bookmark
            bookmark = Bookmark.objects.create(
                user=user,
                url=url,
                normalized_url=normalized_url,
                hash=hash_value,
                title=title[:500],
                description=description,
            )

            # Set category if provided
            if category_id:
                try:
                    # Try new unified Category model
                    from .models import Category

                    category = Category.objects.get(id=category_id, user=user)
                    bookmark.category_v2 = category
                    bookmark.save(update_fields=["category_v2"])
                except Category.DoesNotExist:
                    pass

            # Add tags if provided
            if tags_str:
                tag_names = [t.strip() for t in tags_str.split(",") if t.strip()]
                for tag_name in tag_names:
                    slug = slugify(tag_name, allow_unicode=True)
                    tag, _ = Tag.objects.get_or_create(
                        user=user,
                        slug=slug,
                        defaults={"name": tag_name},
                    )
                    bookmark.tags.add(tag)

            return Response(
                {
                    "ok": True,
                    "bookmark_id": bookmark.id,
                    "message": "Bookmark created successfully",
                },
                status=status.HTTP_201_CREATED,
            )

        except IntegrityError:
            return Response(
                {
                    "ok": False,
                    "error": "Bookmark creation failed (uniqueness violation)",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.error("Bookmarklet creation error", exc_info=True)
            return Response(
                {"ok": False, "error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )


@login_required
def bookmarklet_view(request):
    """Display bookmarklet installation instructions and code."""
    api_url = request.build_absolute_uri(reverse("bookmarklet-create"))
    user_token = None

    # Try to get or create user token for API auth
    if request.user.is_authenticated:
        from rest_framework.authtoken.models import Token

        try:
            token = Token.objects.get(user=request.user)
            user_token = token.key
        except Token.DoesNotExist:
            # Token will be created on first API use with session auth
            pass

    # Generate bookmarklet code (uses current session or token if available)
    bookmarklet_code = f"""
javascript:(function(){{
  var url = window.location.href;
  var title = document.title;
  var selection = window.getSelection().toString();
  
  var data = {{
    url: url,
    title: title,
    description: selection || 'Saved from: ' + url
  }};
  
  fetch('{api_url}', {{
    method: 'POST',
    headers: {{
      'Content-Type': 'application/json',
      {f"'Authorization': 'Token {user_token}'," if user_token else "'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]')?.value || '',"}
    }},
    body: JSON.stringify(data),
    credentials: 'include'
  }})
  .then(r => r.json())
  .then(d => {{
    if (d.ok) {{
      alert('Bookmark saved!');
    }} else {{
      alert('Error: ' + (d.error || 'Unknown error'));
    }}
  }})
  .catch(e => alert('Error saving bookmark: ' + e));
}})();
""".strip()

    context = {
        "bookmarklet_code": bookmarklet_code,
        "api_url": api_url,
        "user_token": user_token,
    }
    return render(request, "bookmarks/bookmarklet_install.html", context)


# ── Bookmark views ──────────────────────────────────────


@login_required
def bookmark_list_view(request):
    query = request.GET.get("q", "").strip()
    tag_slug = request.GET.get("tag", "").strip()
    category_id = request.GET.get("category", "").strip()

    bookmarks_qs = Bookmark.objects.filter(user=request.user).prefetch_related("tags")
    if query:
        bookmarks_qs = bookmarks_qs.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(url__icontains=query)
        )
    if tag_slug:
        bookmarks_qs = bookmarks_qs.filter(tags__slug=tag_slug)
    if category_id:
        try:
            cat_id = int(category_id)
            bookmarks_qs = bookmarks_qs.filter(category_id=cat_id)
        except (ValueError, TypeError):
            pass

    tags = Tag.objects.filter(user=request.user).annotate(
        bookmark_count=Count("bookmarks")
    )
    categories = (
        BookmarkCategory.objects.filter(user=request.user)
        .annotate(bookmark_count=Count("bookmarks"))
        .order_by("display_order")
    )

    paginator = Paginator(bookmarks_qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    bookmark_ids = [b.id for b in page_obj.object_list]
    state_by_bookmark_id = {}
    if bookmark_ids:
        state_by_bookmark_id = {
            s.bookmark_id: s
            for s in BookmarkUserState.objects.filter(
                user=request.user, bookmark_id__in=bookmark_ids
            )
        }

    bookmark_cards = []
    for bm in page_obj.object_list:
        domain = urlparse(bm.url).netloc
        state = state_by_bookmark_id.get(bm.id)
        bookmark_cards.append(
            {
                "id": bm.id,
                "url": bm.url,
                "primary_url": bm.url,
                "open_in_new_tab": True,
                "title": bm.title,
                "description": bm.description,
                "thumbnail_url": bm.thumbnail_url,
                "domain": domain,
                "tags": list(bm.tags.all()),
                "category": bm.category,
                "created_at": bm.created_at,
                "is_pinned": state.is_pinned if state else False,
                "is_read_later": state.is_read_later if state else False,
                "is_read": state.is_read if state else False,
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
            "categories": categories,
            "selected_category_id": category_id,
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
    next_url = (
        request.POST.get("next", "").strip() or request.GET.get("next", "").strip()
    )

    if request.method == "POST":
        form = BookmarkForm(request.POST)
        if form.is_valid():
            bookmark = form.save(commit=False)
            bookmark.user = request.user
            # Store thumbnail from hidden field
            bookmark.thumbnail_url = request.POST.get("thumbnail_url", "")
            try:
                bookmark.save()
                _save_bookmark_tags(
                    bookmark, form.cleaned_data.get("tag_names", ""), request.user
                )
                messages.success(request, "Bookmark added.")
                if next_url and url_has_allowed_host_and_scheme(
                    next_url, allowed_hosts={request.get_host()}
                ):
                    return redirect(next_url)
                return redirect("bookmarks-page")
            except IntegrityError:
                messages.error(request, "This URL is already bookmarked.")
    else:
        initial = {}
        preset_category_id = request.GET.get("category", "").strip()
        if preset_category_id:
            category = BookmarkCategory.objects.filter(
                user=request.user, id=preset_category_id
            ).first()
            if category:
                initial["category"] = category
        form = BookmarkForm(initial=initial)

    # Restrict category queryset to user's categories
    form.fields["category"].queryset = BookmarkCategory.objects.filter(
        user=request.user
    ).order_by("display_order")
    form.fields["category"].empty_label = "Uncategorized"

    existing_tags = Tag.objects.filter(user=request.user).order_by("name")
    bookmark_categories = BookmarkCategory.objects.filter(user=request.user).order_by(
        "display_order"
    )
    return render(
        request,
        "bookmarks/bookmark_form.html",
        {
            "form": form,
            "existing_tags": existing_tags,
            "bookmark_categories": bookmark_categories,
            "edit_mode": False,
            "next_url": next_url,
            "current_page": "bookmarks",
        },
    )


@login_required
def bookmark_edit_view(request, bookmark_id):
    bookmark = get_object_or_404(Bookmark, id=bookmark_id, user=request.user)
    next_url = (
        request.POST.get("next", "").strip() or request.GET.get("next", "").strip()
    )

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
            if next_url and url_has_allowed_host_and_scheme(
                next_url, allowed_hosts={request.get_host()}
            ):
                return redirect(next_url)
            return redirect("bookmarks-page")
    else:
        tag_names = ", ".join(t.name for t in bookmark.tags.all())
        form = BookmarkForm(instance=bookmark, initial={"tag_names": tag_names})

    # Restrict category queryset to user's categories
    form.fields["category"].queryset = BookmarkCategory.objects.filter(
        user=request.user
    ).order_by("display_order")
    form.fields["category"].empty_label = "Uncategorized"

    existing_tags = Tag.objects.filter(user=request.user).order_by("name")
    bookmark_categories = BookmarkCategory.objects.filter(user=request.user).order_by(
        "display_order"
    )
    return render(
        request,
        "bookmarks/bookmark_form.html",
        {
            "form": form,
            "bookmark": bookmark,
            "existing_tags": existing_tags,
            "bookmark_categories": bookmark_categories,
            "edit_mode": True,
            "next_url": next_url,
            "current_page": "bookmarks",
        },
    )


@login_required
def bookmark_delete_view(request, bookmark_id):
    if request.method != "POST":
        return redirect("bookmarks-page")

    next_url = request.POST.get("next", "").strip()
    bookmark = get_object_or_404(Bookmark, id=bookmark_id, user=request.user)
    bookmark.delete()
    messages.success(request, "Bookmark deleted.")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}
    ):
        return redirect(next_url)
    return redirect("bookmarks-page")


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

    # Restrict category queryset to user's categories
    form.fields["category"].queryset = BookmarkCategory.objects.filter(
        user=request.user
    ).order_by("display_order")
    form.fields["category"].empty_label = "Uncategorized"

    existing_tags = Tag.objects.filter(user=request.user).order_by("name")
    bookmark_categories = BookmarkCategory.objects.filter(user=request.user).order_by(
        "display_order"
    )
    return render(
        request,
        "bookmarks/bookmark_form.html",
        {
            "form": form,
            "existing_tags": existing_tags,
            "bookmark_categories": bookmark_categories,
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


# ── Bookmark Category views ─────────────────────────────


@login_required
def bookmark_category_list_view(request):
    return redirect("settings-categories")


@login_required
def bookmark_category_update_view(request, category_id):
    if request.method != "POST":
        return redirect("settings-categories")

    category = get_object_or_404(BookmarkCategory, id=category_id, user=request.user)

    if request.POST.get("action") == "delete":
        name = category.name
        # Set bookmarks in this category to None (uncategorized)
        category.bookmarks.update(category=None)
        category.delete()
        messages.success(request, f"Deleted category: {name}")
        return redirect("settings-categories")

    form = BookmarkCategoryForm(
        request.POST, instance=category, prefix=f"cat-{category.id}"
    )
    if form.is_valid():
        c = form.save(commit=False)
        c.user = request.user
        c.save()
        messages.success(request, f"Updated category: {c.name}")
    else:
        messages.error(request, "Could not update category.")

    return redirect("settings-categories")


@login_required
def bookmark_category_reorder_view(request):
    """API endpoint to reorder bookmark categories via AJAX."""
    if request.method != "POST":
        return redirect("settings-categories")

    try:
        import json

        data = json.loads(request.body)
        category_ids = data.get("category_ids", [])

        for order, cat_id in enumerate(category_ids):
            BookmarkCategory.objects.filter(id=int(cat_id), user=request.user).update(
                display_order=order
            )

        return Response({"status": "ok"}, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Failed to reorder bookmark categories: {e}")
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


# ── Helper functions for shared views ────────────────────────


def _get_read_later_articles(user):
    """Get articles marked as read_later"""
    return (
        ArticleUserState.objects.filter(
            user=user, article__isnull=False, is_read_later=True
        )
        .select_related("article__feed")
        .order_by("-article__published_at")
    )


def _get_favorites_articles(user):
    """Deprecated: favorites removed. Returns empty queryset."""
    return ArticleUserState.objects.none()


def _get_dashboard_statistics(user):
    """Gather statistics for dashboard"""
    feed_count = Feed.objects.count()
    bookmark_count = Bookmark.objects.filter(user=user).count()
    bookmark_category_count = BookmarkCategory.objects.filter(user=user).count()

    unread_articles = ArticleUserState.objects.filter(user=user, is_read=False).count()
    read_later_count = ArticleUserState.objects.filter(
        user=user, is_read_later=True
    ).count()

    return {
        "feed_count": feed_count,
        "bookmark_count": bookmark_count,
        "bookmark_category_count": bookmark_category_count,
        "unread_articles": unread_articles,
        "read_later_count": read_later_count,
    }


# ── New page views ──────────────────────────────────────────


@login_required
def main_dashboard_view(request):
    """Bookmark-centric home dashboard with RSS flow preview."""
    user = request.user

    # ── Bookmark data ──────────────────────────────────────
    pinned_states = (
        BookmarkUserState.objects.filter(user=user, is_pinned=True)
        .select_related("bookmark__category")
        .prefetch_related("bookmark__tags")
        .order_by("-updated_at")
    )
    pinned_bookmarks = []
    for s in pinned_states:
        bm = s.bookmark
        from urllib.parse import urlparse as _urlparse

        domain = _urlparse(bm.url).netloc
        pinned_bookmarks.append(
            {
                "id": bm.id,
                "url": bm.url,
                "primary_url": bm.url,
                "open_in_new_tab": True,
                "title": bm.title,
                "description": bm.description,
                "domain": domain,
                "category": bm.category,
                "tags": list(bm.tags.all()),
            }
        )

    recent_bookmarks_qs = (
        Bookmark.objects.filter(user=user)
        .select_related("category")
        .prefetch_related("tags")
        .order_by("-created_at")[:10]
    )
    bookmark_ids = [b.id for b in recent_bookmarks_qs]
    bm_states = {
        s.bookmark_id: s
        for s in BookmarkUserState.objects.filter(
            user=user, bookmark_id__in=bookmark_ids
        )
    }
    recent_bookmarks = []
    for bm in recent_bookmarks_qs:
        from urllib.parse import urlparse as _urlparse

        domain = _urlparse(bm.url).netloc
        state = bm_states.get(bm.id)
        recent_bookmarks.append(
            {
                "id": bm.id,
                "url": bm.url,
                "primary_url": bm.url,
                "open_in_new_tab": True,
                "title": bm.title,
                "description": bm.description,
                "domain": domain,
                "category": bm.category,
                "tags": list(bm.tags.all()),
                "created_at": bm.created_at,
                "is_pinned": state.is_pinned if state else False,
                "is_read_later": state.is_read_later if state else False,
            }
        )

    total_bookmarks = Bookmark.objects.filter(user=user).count()
    total_categories = BookmarkCategory.objects.filter(user=user).count()
    read_later_count = BookmarkUserState.objects.filter(
        user=user, is_read_later=True
    ).count()
    pinned_count = len(pinned_bookmarks)

    bookmark_stats = {
        "total": total_bookmarks,
        "pinned": pinned_count,
        "read_later": read_later_count,
        "categories": total_categories,
    }

    # ── RSS flow preview ───────────────────────────────────
    unread_articles_qs = (
        Article.objects.filter(feed__isnull=False)
        .exclude(user_states__user=user, user_states__is_read=True)
        .select_related("feed")
        .distinct()
        .order_by("-published_at")
    )
    total_unread = unread_articles_qs.count()
    flow_articles = []
    for article in unread_articles_qs[:5]:
        from urllib.parse import urlparse as _urlparse

        flow_articles.append(
            {
                "id": article.id,
                "title": article.title,
                "feed_name": article.feed.name if article.feed else "",
                "published_at": article.published_at,
                "link": article.link,
            }
        )

    context = {
        "current_page": "home",
        "pinned_bookmarks": pinned_bookmarks,
        "recent_bookmarks": recent_bookmarks,
        "bookmark_stats": bookmark_stats,
        "flow_articles": flow_articles,
        "total_unread": total_unread,
    }
    return render(request, "dashboard/homepage.html", context)


@login_required
def overview_dashboard_view(request):
    """Statistics overview dashboard at /overview/."""
    stats = _get_dashboard_statistics(request.user)

    recent_articles = (
        Article.objects.filter(feed__isnull=False)
        .exclude(user_states__user=request.user, user_states__is_read=True)
        .select_related("feed")
        .distinct()
        .order_by("-published_at")[:5]
    )

    recent_bookmarks = (
        Bookmark.objects.filter(user=request.user)
        .select_related("category")
        .order_by("-created_at")[:5]
    )

    context = {
        "current_page": "overview",
        "stats": stats,
        "recent_articles": recent_articles,
        "recent_bookmarks": recent_bookmarks,
    }
    return render(request, "dashboard/main_dashboard.html", context)


@login_required
def feeds_page_view(request):
    """Feed-focused page with feed list and categories"""
    base_qs = Article.objects.filter(feed__isnull=False).select_related("feed")

    feed_categories = Feed.objects.values_list("category", flat=True).distinct()
    feed_categories = sorted([c for c in feed_categories if c])

    selected_category = request.GET.get("category", "").strip()
    if selected_category:
        base_qs = base_qs.filter(feed__category=selected_category)

    context = _build_article_list_context(request, base_qs)
    article_count = context.get("article_count", 0)
    page_title = f'Feeds in "{selected_category}"' if selected_category else "All Feeds"
    page_subtitle = f"{article_count} article{'s' if article_count != 1 else ''}"
    context.update(
        {
            "current_page": "feeds",
            "feed_categories": feed_categories,
            "selected_category": selected_category,
            "page_title": page_title,
            "page_subtitle": page_subtitle,
        }
    )
    return render(request, "rss/feeds_page.html", context)


@login_required
def bookmarks_page_view(request):
    """Bookmark-focused page"""
    query = request.GET.get("q", "").strip()
    tag_slug = request.GET.get("tag", "").strip()
    category_id = request.GET.get("category", "").strip()
    bookmark_flag = request.GET.get("flag", "all").strip()
    if bookmark_flag not in {"all", "pinned", "read-later", "read"}:
        bookmark_flag = "all"
    layout_mode = request.GET.get("layout", "classic").strip()
    if layout_mode not in {"classic", "collections"}:
        layout_mode = "classic"

    sort_mode = request.GET.get("sort", "latest").strip()
    if sort_mode not in {"latest", "oldest", "title-asc", "title-desc"}:
        sort_mode = "latest"

    bookmarks_qs = Bookmark.objects.filter(user=request.user).prefetch_related("tags")
    if query:
        bookmarks_qs = bookmarks_qs.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(url__icontains=query)
        )
    if tag_slug:
        bookmarks_qs = bookmarks_qs.filter(tags__slug=tag_slug)
    if category_id:
        try:
            cat_id = int(category_id)
            bookmarks_qs = bookmarks_qs.filter(category_id=cat_id)
        except (ValueError, TypeError):
            pass
    if bookmark_flag != "all":
        state_filters = {"user": request.user}
        if bookmark_flag == "pinned":
            state_filters["is_pinned"] = True
        elif bookmark_flag == "read-later":
            state_filters["is_read_later"] = True
        elif bookmark_flag == "read":
            state_filters["is_read"] = True

        bookmarks_qs = bookmarks_qs.filter(
            id__in=BookmarkUserState.objects.filter(**state_filters).values(
                "bookmark_id"
            )
        )

    if sort_mode == "oldest":
        bookmarks_qs = bookmarks_qs.order_by("created_at")
    elif sort_mode == "title-asc":
        bookmarks_qs = bookmarks_qs.order_by("title", "-created_at")
    elif sort_mode == "title-desc":
        bookmarks_qs = bookmarks_qs.order_by("-title", "-created_at")
    else:
        bookmarks_qs = bookmarks_qs.order_by("-created_at")

    tags = Tag.objects.filter(user=request.user).annotate(
        bookmark_count=Count("bookmarks")
    )
    categories = (
        BookmarkCategory.objects.filter(user=request.user)
        .annotate(bookmark_count=Count("bookmarks"))
        .order_by("display_order")
    )

    display_mode = _resolve_display_mode(request)

    if layout_mode == "collections":
        bookmarks_for_display = list(
            bookmarks_qs.select_related("category").prefetch_related("tags")
        )
        page_obj = None
    else:
        paginator = Paginator(bookmarks_qs, 20)
        page_obj = paginator.get_page(request.GET.get("page"))
        bookmarks_for_display = list(page_obj.object_list)

    bookmark_ids = [b.id for b in bookmarks_for_display]
    state_by_bookmark_id = {}
    if bookmark_ids:
        state_by_bookmark_id = {
            s.bookmark_id: s
            for s in BookmarkUserState.objects.filter(
                user=request.user, bookmark_id__in=bookmark_ids
            )
        }

    def _bookmark_card(bm):
        domain = urlparse(bm.url).netloc
        state = state_by_bookmark_id.get(bm.id)
        return {
            "id": bm.id,
            "url": bm.url,
            "primary_url": bm.url,
            "open_in_new_tab": True,
            "title": bm.title,
            "description": bm.description,
            "thumbnail_url": bm.thumbnail_url,
            "domain": domain,
            "tags": list(bm.tags.all()),
            "category": bm.category,
            "created_at": bm.created_at,
            "is_pinned": state.is_pinned if state else False,
            "is_read_later": state.is_read_later if state else False,
            "is_read": state.is_read if state else False,
        }

    bookmark_cards = []
    bookmark_collections = []
    if layout_mode == "collections":
        grouped = {}
        for bm in bookmarks_for_display:
            key = bm.category_id or 0
            grouped.setdefault(key, []).append(_bookmark_card(bm))

        for category in categories:
            cards = grouped.pop(category.id, [])
            if not cards:
                continue
            bookmark_collections.append(
                {
                    "key": str(category.id),
                    "name": category.name,
                    "color": category.color,
                    "count": len(cards),
                    "add_url": f"{reverse('bookmark-add')}?category={category.id}&next={quote_plus(request.get_full_path())}",
                    "bookmarks": cards,
                }
            )

        uncategorized_cards = grouped.pop(0, [])
        if uncategorized_cards:
            bookmark_collections.append(
                {
                    "key": "0",
                    "name": "Uncategorized",
                    "color": "#94a3b8",
                    "count": len(uncategorized_cards),
                    "add_url": f"{reverse('bookmark-add')}?next={quote_plus(request.get_full_path())}",
                    "bookmarks": uncategorized_cards,
                }
            )
    else:
        for bm in bookmarks_for_display:
            bookmark_cards.append(_bookmark_card(bm))

    context = {
        "current_page": "bookmarks",
        "bookmark_cards": bookmark_cards,
        "page_obj": page_obj,
        "bookmark_count": bookmarks_qs.count(),
        "query": query,
        "tag_slug": tag_slug,
        "tags": tags,
        "categories": categories,
        "selected_category_id": category_id,
        "bookmark_flag": bookmark_flag,
        "layout_mode": layout_mode,
        "layout_mode_links": [
            {"key": "classic", "label": "Classic"},
            {"key": "collections", "label": "Collections"},
        ],
        "display_mode": display_mode,
        "sort_mode": sort_mode,
        "display_mode_links": [
            {"key": "list", "label": "List"},
            {"key": "compact", "label": "Compact"},
            {"key": "card", "label": "Card"},
        ],
        "sort_links": [
            {"key": "latest", "label": "Latest"},
            {"key": "oldest", "label": "Oldest"},
            {"key": "title-asc", "label": "Title A-Z"},
            {"key": "title-desc", "label": "Title Z-A"},
        ],
        "add_bookmark_url": f"{reverse('bookmark-add')}?next={quote_plus(request.get_full_path())}",
        "bookmark_collections": bookmark_collections,
    }

    if category_id:
        selected_category = BookmarkCategory.objects.filter(
            user=request.user, id=category_id
        ).first()
        context["selected_category_name"] = (
            selected_category.name if selected_category else category_id
        )
        context["page_title"] = (
            f'Bookmarks in "{selected_category.name}"'
            if selected_category
            else "Bookmarks"
        )
    else:
        context["selected_category_name"] = ""
        if bookmark_flag == "pinned":
            context["page_title"] = "Pinned Bookmarks"
        elif bookmark_flag == "read-later":
            context["page_title"] = "Read later Bookmarks"
        elif bookmark_flag == "read":
            context["page_title"] = "Read Bookmarks"
        else:
            context["page_title"] = "All Bookmarks"
    context["page_subtitle"] = (
        f"{context['bookmark_count']} bookmark"
        f"{'s' if context['bookmark_count'] != 1 else ''}"
    )

    return render(request, "bookmarks/bookmarks_page.html", context)


@login_required
def read_later_view(request):
    """Legacy endpoint: redirect read-later to feeds filter."""
    params = request.GET.copy()
    params["state"] = "read-later"
    query = params.urlencode()
    return redirect(
        f"{reverse('feeds-page')}?{query}" if query else reverse("feeds-page")
    )


@login_required
def favorites_view(request):
    """Favorites removed. Redirect to read-later feed filter."""
    return redirect(f"{reverse('feeds-page')}?state=read-later")


@login_required
def saved_view(request):
    """Read-later queue: RSS articles + bookmarks marked as read_later."""
    base_qs = Article.objects.filter(feed__isnull=False).select_related("feed")
    # Inject state=read-later so _build_article_list_context filters correctly
    orig_get = request.GET
    request.GET = request.GET.copy()
    request.GET["state"] = "read-later"
    context = _build_article_list_context(request, base_qs)
    request.GET = orig_get

    bookmark_states_rl = BookmarkUserState.objects.filter(
        user=request.user, is_read_later=True
    )
    bookmarks_qs = Bookmark.objects.filter(
        user=request.user,
        id__in=bookmark_states_rl.values("bookmark_id"),
    ).prefetch_related("tags")

    query = (request.GET.get("q") or "").strip()
    if query:
        bookmarks_qs = bookmarks_qs.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(url__icontains=query)
        )

    sort_mode = context.get("sort_mode", "latest")
    if sort_mode == "oldest":
        bookmarks_qs = bookmarks_qs.order_by("created_at")
    else:
        bookmarks_qs = bookmarks_qs.order_by("-created_at")

    bookmark_read_later_count = bookmark_states_rl.count()

    bookmark_cards = []
    for bm in bookmarks_qs[:20]:
        domain = urlparse(bm.url).netloc
        bookmark_cards.append(
            {
                "id": bm.id,
                "url": bm.url,
                "primary_url": bm.url,
                "open_in_new_tab": True,
                "title": bm.title,
                "description": bm.description,
                "thumbnail_url": bm.thumbnail_url,
                "domain": domain,
                "tags": list(bm.tags.all()),
                "category": bm.category,
                "created_at": bm.created_at,
            }
        )

    counts = {item["key"]: item["count"] for item in context["state_filter_links"]}
    total_read_later = counts.get("read-later", 0) + bookmark_read_later_count
    context.update(
        {
            "current_page": "saved",
            "saved_state": "read-later",
            "saved_total": total_read_later,
            "page_title": "Read Later",
            "page_subtitle": (
                f"{total_read_later} item{'s' if total_read_later != 1 else ''} saved for later"
            ),
            "bookmark_cards": bookmark_cards,
            "bookmark_saved_count": bookmarks_qs.count(),
            "state_filter_links": [],
            "sort_links": [
                {"key": "latest", "label": "Latest"},
                {"key": "oldest", "label": "Oldest"},
            ],
        }
    )
    return render(request, "shared/saved.html", context)


# ── Article → Bookmark one-click save ──────────────────────


@login_required
def save_article_as_bookmark_view(request, article_id):
    """One-click save: convert an RSS article into a permanent Bookmark."""
    if request.method != "POST":
        return redirect("feeds-page")

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    article = get_object_or_404(Article, id=article_id)

    # Idempotent: return existing bookmark if URL already saved
    existing = Bookmark.objects.filter(user=request.user, url=article.link).first()
    if existing:
        if is_ajax:
            return JsonResponse(
                {"ok": True, "bookmark_id": existing.id, "already_saved": True}
            )
        messages.info(request, "Already saved to bookmarks.")
        return redirect("bookmarks-page")

    bookmark = Bookmark(
        user=request.user,
        url=article.link,
        title=article.title,
        description=(article.summary or ""),
        thumbnail_url=(article.image_url or ""),
    )
    try:
        bookmark.save()
    except IntegrityError:
        # Race condition: another request saved it first
        existing = Bookmark.objects.filter(user=request.user, url=article.link).first()
        if is_ajax:
            return JsonResponse(
                {
                    "ok": True,
                    "bookmark_id": existing.id if existing else None,
                    "already_saved": True,
                }
            )
        messages.info(request, "Already saved to bookmarks.")
        return redirect("bookmarks-page")

    if is_ajax:
        return JsonResponse(
            {"ok": True, "bookmark_id": bookmark.id, "already_saved": False}
        )

    messages.success(request, "Saved to bookmarks.")
    return redirect("bookmarks-page")
