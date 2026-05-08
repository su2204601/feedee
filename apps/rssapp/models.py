from django.db import models
from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify
import nh3


class Category(models.Model):
    """Unified category model for feeds and bookmarks."""

    CONTENT_TYPE_CHOICES = [
        ("feed", "Feed"),
        ("bookmark", "Bookmark"),
        ("both", "Both"),
    ]

    COLOR_CHOICES = [
        ("#EF4444", "Red"),
        ("#F97316", "Orange"),
        ("#EAB308", "Yellow"),
        ("#22C55E", "Green"),
        ("#14B8A6", "Teal"),
        ("#3B82F6", "Blue"),
        ("#6366F1", "Indigo"),
        ("#8B5CF6", "Violet"),
        ("#EC4899", "Pink"),
        ("#6B7280", "Gray"),
        ("#78716C", "Stone"),
        ("#0EA5E9", "Sky"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="categories",
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default="")
    color = models.CharField(max_length=7, choices=COLOR_CHOICES, default="#3B82F6")
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )
    content_type = models.CharField(
        max_length=20,
        choices=CONTENT_TYPE_CHOICES,
        default="both",
        help_text="Which content types this category applies to",
    )
    display_order = models.PositiveIntegerField(default=0, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"],
                name="uniq_user_category_name",
            ),
        ]
        ordering = ["display_order", "name"]
        verbose_name = "カテゴリ"
        verbose_name_plural = "カテゴリ"

    def __str__(self) -> str:
        if self.parent:
            return f"{self.parent.name} / {self.name}"
        return self.name

    @property
    def full_path(self):
        parts = []
        node = self
        while node:
            parts.append(node.name)
            node = node.parent
        return " / ".join(reversed(parts))


class Feed(models.Model):
    name = models.CharField(max_length=255)
    url = models.URLField(unique=True)
    category = models.CharField(max_length=100, blank=True, default="")
    category_v2 = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feeds",
        help_text="New unified category (category field for backward compatibility)",
    )
    display_order = models.PositiveIntegerField(default=0, db_index=True)
    is_active = models.BooleanField(default=True)
    is_public = models.BooleanField(default=False, help_text="Whether this feed is publicly visible (for future sharing features)")
    last_fetched_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    consecutive_failures = models.PositiveIntegerField(default=0)
    etag = models.CharField(max_length=255, blank=True, default="")
    last_modified = models.CharField(max_length=255, blank=True, default="")
    next_fetch_at = models.DateTimeField(default=timezone.now, db_index=True)
    fetch_interval_minutes = models.PositiveIntegerField(default=60)

    class Meta:
        verbose_name = "フィード"
        verbose_name_plural = "フィード"

    def __str__(self) -> str:
        return f"{self.name} ({self.url})"


class Article(models.Model):
    CONTENT_SOURCE_CHOICES = [
        ("feed", "Provided by feed"),
        ("extracted", "Extracted from source article"),
        ("summary", "Summary fallback"),
        ("empty", "No readable content"),
    ]
    EXTRACTION_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("provided", "Provided by feed"),
        ("success", "Extraction succeeded"),
        ("failed", "Extraction failed"),
        ("skipped", "Extraction skipped"),
    ]

    # Allowed HTML tags for sanitized content
    ALLOWED_TAGS = {
        "p",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "a",
        "img",
        "strong",
        "em",
        "u",
        "br",
        "ul",
        "ol",
        "li",
        "blockquote",
        "code",
        "pre",
        "table",
        "tr",
        "td",
        "th",
    }

    # Allowed attributes per tag
    ALLOWED_ATTRIBUTES = {
        "a": {"href", "title", "target"},
        "img": {"src", "alt", "title", "width", "height"},
        "table": {"border", "cellpadding", "cellspacing"},
        "*": {"class"},
    }

    feed = models.ForeignKey(
        Feed,
        on_delete=models.CASCADE,
        related_name="articles",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=500)
    link = models.URLField(max_length=2048)
    normalized_link = models.URLField(max_length=2048)
    guid = models.CharField(max_length=500, null=True, blank=True, unique=True)
    hash = models.CharField(max_length=64, unique=True)
    summary = models.TextField(blank=True, default="")
    content = models.TextField(blank=True, default="")
    content_source = models.CharField(
        max_length=20,
        choices=CONTENT_SOURCE_CHOICES,
        default="summary",
    )
    extraction_status = models.CharField(
        max_length=20,
        choices=EXTRACTION_STATUS_CHOICES,
        default="pending",
    )
    extracted_at = models.DateTimeField(null=True, blank=True)
    image_url = models.URLField(max_length=2048, blank=True, default="")
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]
        verbose_name = "記事"
        verbose_name_plural = "記事"

    @staticmethod
    def _sanitize_html(html: str) -> str:
        return nh3.clean(
            html,
            tags=Article.ALLOWED_TAGS,
            attributes=Article.ALLOWED_ATTRIBUTES,
            link_rel=None,
        )

    def save(self, *args, **kwargs):
        """Sanitize HTML content before saving."""
        if self.content:
            self.content = self._sanitize_html(self.content)
        if self.summary:
            self.summary = self._sanitize_html(self.summary)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title


class ArticleUserState(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="article_states",
    )
    article = models.ForeignKey(
        Article, on_delete=models.CASCADE, related_name="user_states"
    )
    is_favorite = models.BooleanField(default=False, db_index=True)
    is_read_later = models.BooleanField(default=False)
    is_read = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "article"], name="uniq_article_user_state"
            ),
        ]
        indexes = [
            models.Index(fields=["user", "updated_at"]),
            models.Index(fields=["user", "is_read_later"]),
            models.Index(fields=["user", "is_favorite"]),
        ]
        verbose_name = "記事ユーザー状態"
        verbose_name_plural = "記事ユーザー状態"

    def __str__(self) -> str:
        return f"state(user={self.user_id}, article={self.article_id})"


class BookmarkUserState(models.Model):
    """Parallel to ArticleUserState: tracks bookmark user interactions."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bookmark_states",
    )
    bookmark = models.ForeignKey(
        "Bookmark", on_delete=models.CASCADE, related_name="user_states"
    )
    # is_pinned is distinct from favorite: pinned is for homepage placement.
    is_pinned = models.BooleanField(default=False, db_index=True)
    is_favorite = models.BooleanField(default=False, db_index=True)
    is_read_later = models.BooleanField(default=False)
    is_read = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "bookmark"], name="uniq_bookmark_user_state"
            ),
        ]
        indexes = [
            models.Index(fields=["user", "updated_at"]),
            models.Index(fields=["user", "is_read_later"]),
            models.Index(fields=["user", "is_favorite"]),
        ]
        verbose_name = "ブックマークユーザー状態"
        verbose_name_plural = "ブックマークユーザー状態"

    def __str__(self) -> str:
        return f"bookmark_state(user={self.user_id}, bookmark={self.bookmark_id})"


class ExtractionTask(models.Model):
    """Task model for asynchronous full-text article extraction."""

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("success", "Success"),
        ("failed", "Failed"),
        ("skipped", "Skipped"),
    ]

    article = models.OneToOneField(
        Article,
        on_delete=models.CASCADE,
        related_name="extraction_task",
        primary_key=True,
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
        db_index=True,
    )
    retry_count = models.PositiveIntegerField(default=0)
    max_retries = models.PositiveIntegerField(default=3)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["status", "retry_count"]),
        ]
        verbose_name = "抽出タスク"
        verbose_name_plural = "抽出タスク"

    def __str__(self) -> str:
        return f"ExtractionTask({self.article_id}, {self.status})"


class UserProfile(models.Model):
    SORT_CHOICES = [
        ("published_desc", "Newest first"),
        ("published_asc", "Oldest first"),
    ]
    THEME_CHOICES = [
        ("system", "System"),
        ("light", "Light"),
        ("dark", "Dark"),
    ]
    DISPLAY_MODE_CHOICES = [
        ("list", "List view"),
        ("compact", "Compact view"),
        ("card", "Card view"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    default_sort = models.CharField(
        max_length=20, choices=SORT_CHOICES, default="published_desc"
    )
    items_per_page = models.PositiveIntegerField(default=20)
    theme_preference = models.CharField(
        max_length=10,
        choices=THEME_CHOICES,
        default="system",
    )
    default_display_mode = models.CharField(
        max_length=20,
        choices=DISPLAY_MODE_CHOICES,
        default="compact",
        help_text="Default display mode for article and bookmark lists",
    )

    class Meta:
        verbose_name = "ユーザープロフィール"
        verbose_name_plural = "ユーザープロフィール"

    def __str__(self) -> str:
        return f"Profile({self.user.username})"


class Tag(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tags",
    )
    color = models.CharField(max_length=7, choices=Category.COLOR_CHOICES, default="#3B82F6")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "slug"], name="uniq_user_tag_slug"),
        ]
        ordering = ["name"]
        verbose_name = "タグ"
        verbose_name_plural = "タグ"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class BookmarkCategory(models.Model):
    COLOR_CHOICES = Category.COLOR_CHOICES

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bookmark_categories",
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default="")
    color = models.CharField(max_length=7, choices=Category.COLOR_CHOICES, default="#3B82F6")
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )
    display_order = models.PositiveIntegerField(default=0, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"], name="uniq_user_bookmark_category_name"
            ),
        ]
        ordering = ["display_order", "name"]
        verbose_name = "ブックマークカテゴリ"
        verbose_name_plural = "ブックマークカテゴリ"

    def __str__(self) -> str:
        if self.parent:
            return f"{self.parent.name} / {self.name}"
        return self.name

    @property
    def full_path(self):
        parts = []
        node = self
        while node:
            parts.append(node.name)
            node = node.parent
        return " / ".join(reversed(parts))


class Bookmark(models.Model):
    url = models.URLField(max_length=2048)
    normalized_url = models.URLField(
        max_length=2048,
        blank=True,
        default="",
        db_index=True,
        help_text="URL without tracking parameters for deduplication",
    )
    hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="SHA256 hash for deduplication (url-based)",
    )
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True, default="")
    thumbnail_url = models.URLField(max_length=2048, blank=True, default="")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bookmarks",
    )
    source_article = models.ForeignKey(
        Article,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bookmarks",
    )
    category = models.ForeignKey(
        BookmarkCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bookmarks",
        help_text="Legacy category field (use category_v2 for new data)",
    )
    category_v2 = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bookmarks",
        help_text="New unified category",
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="bookmarks")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "url"], name="uniq_user_bookmark_url"
            ),
            models.UniqueConstraint(
                fields=["user", "normalized_url"],
                condition=models.Q(normalized_url__gt=""),
                name="uniq_user_bookmark_normalized_url",
            ),
        ]
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "normalized_url"]),
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["user", "-created_at"]),
        ]
        verbose_name = "ブックマーク"
        verbose_name_plural = "ブックマーク"

    def save(self, *args, **kwargs):
        """Automatically compute normalized_url and hash on save."""
        from .utils import normalize_url, generate_bookmark_hash

        if not self.normalized_url and self.url:
            self.normalized_url = normalize_url(self.url)

        if not self.hash and self.normalized_url:
            self.hash = generate_bookmark_hash(self.normalized_url)

        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title
