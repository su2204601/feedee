from django.db import models
from django.conf import settings
from django.utils.text import slugify
import bleach


class Feed(models.Model):
    name = models.CharField(max_length=255)
    url = models.URLField(unique=True)
    category = models.CharField(max_length=100, blank=True, default="")
    display_order = models.PositiveIntegerField(default=0, db_index=True)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return f"{self.name} ({self.url})"


class Article(models.Model):
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
        "a": ["href", "title", "target", "rel"],
        "img": ["src", "alt", "title", "width", "height"],
        "table": ["border", "cellpadding", "cellspacing"],
        "*": ["class"],  # Allow class on any tag
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
    image_url = models.URLField(max_length=2048, blank=True, default="")
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]

    def save(self, *args, **kwargs):
        """Sanitize HTML content before saving."""
        if self.content:
            self.content = bleach.clean(
                self.content,
                tags=Article.ALLOWED_TAGS,
                attributes=Article.ALLOWED_ATTRIBUTES,
                strip=True,
            )
        if self.summary:
            self.summary = bleach.clean(
                self.summary,
                tags=Article.ALLOWED_TAGS,
                attributes=Article.ALLOWED_ATTRIBUTES,
                strip=True,
            )
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
    is_favorite = models.BooleanField(default=False)
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

    def __str__(self) -> str:
        return f"state(user={self.user_id}, article={self.article_id})"


class Tag(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tags",
    )
    color = models.CharField(max_length=7, default="#3B82F6")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "slug"], name="uniq_user_tag_slug"),
        ]
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class Bookmark(models.Model):
    url = models.URLField(max_length=2048)
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
    tags = models.ManyToManyField(Tag, blank=True, related_name="bookmarks")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "url"], name="uniq_user_bookmark_url"
            ),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title
