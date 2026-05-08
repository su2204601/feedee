from urllib.parse import urlsplit

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm as DjangoPasswordChangeForm,
    UserCreationForm,
)

from .models import Bookmark, BookmarkCategory, Feed, Tag, UserProfile
from .utils import discover_feed_url

User = get_user_model()

_INPUT_CLASS = (
    "w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm "
    "placeholder-gray-400 focus:border-brand-500 focus:ring-2 focus:ring-brand-100 "
    "focus:outline-none transition-colors"
)


class FeedCreateForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].required = False
        self.fields["name"].widget.attrs["placeholder"] = "Feed name (optional)"
        self.fields["url"].widget.attrs["placeholder"] = (
            "https://example.com or https://example.com/feed.xml"
        )
        self.discovered_feed_url = ""
        self.discovered_title = ""
        self.discovery_used = False
        self.discovery_error = ""
        self.discovery_error_detail = ""

    def clean_url(self):
        raw_url = (self.cleaned_data.get("url") or "").strip()
        discovered = discover_feed_url(raw_url)
        feed_url = (discovered.get("feed_url") or "").strip()
        self.discovered_feed_url = feed_url
        self.discovered_title = (discovered.get("title") or "").strip()
        self.discovery_used = bool(feed_url and feed_url != raw_url)
        self.discovery_error = discovered.get("error", "")
        self.discovery_error_detail = discovered.get("error_detail", "")

        if not feed_url:
            error_msg = self.discovery_error_detail or "Could not find an RSS or Atom feed at that URL."
            raise forms.ValidationError(error_msg)

        # Check if this feed URL already exists
        if Feed.objects.filter(url=feed_url).exists():
            raise forms.ValidationError(
                f"This feed is already subscribed. The discovered feed URL ({feed_url}) is already in your feed list."
            )

        return feed_url

    def clean(self):
        cleaned = super().clean()
        name = (cleaned.get("name") or "").strip()
        if not name:
            fallback_name = (
                self.discovered_title
                or urlsplit(self.discovered_feed_url or cleaned.get("url") or "").netloc
            )
            if fallback_name:
                cleaned["name"] = fallback_name
        return cleaned

    class Meta:
        model = Feed
        fields = ["name", "url", "category"]
        labels = {
            "category": "Group",
        }
        widgets = {
            "name": forms.TextInput(
                attrs={"class": _INPUT_CLASS, "placeholder": "Feed name"}
            ),
            "url": forms.URLInput(
                attrs={
                    "class": _INPUT_CLASS,
                    "placeholder": "https://example.com/rss.xml",
                }
            ),
            "category": forms.TextInput(
                attrs={"class": _INPUT_CLASS, "placeholder": "Group (optional)"}
            ),
        }


class FeedUpdateForm(forms.ModelForm):
    class Meta:
        model = Feed
        fields = ["name", "url", "category", "is_active"]
        labels = {
            "category": "Group",
        }
        widgets = {
            "name": forms.TextInput(attrs={"class": _INPUT_CLASS}),
            "url": forms.URLInput(attrs={"class": _INPUT_CLASS}),
            "category": forms.TextInput(
                attrs={"class": _INPUT_CLASS, "placeholder": "Ungrouped"}
            ),
            "is_active": forms.CheckboxInput(
                attrs={
                    "class": "h-4 w-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500",
                }
            ),
        }


class TagForm(forms.ModelForm):
    class Meta:
        model = Tag
        fields = ["name", "color"]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": _INPUT_CLASS, "placeholder": "Tag name"}
            ),
            "color": forms.HiddenInput(
                attrs={"x-model": "selectedColor"}
            ),
        }


class BookmarkForm(forms.ModelForm):
    tag_names = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": _INPUT_CLASS,
                "placeholder": "tag1, tag2, tag3",
            }
        ),
    )

    class Meta:
        model = Bookmark
        fields = ["url", "title", "description", "category"]
        widgets = {
            "url": forms.URLInput(
                attrs={
                    "class": _INPUT_CLASS,
                    "placeholder": "https://example.com",
                    "id": "bookmark-url",
                }
            ),
            "title": forms.TextInput(
                attrs={
                    "class": _INPUT_CLASS,
                    "placeholder": "Page title",
                    "id": "bookmark-title",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": _INPUT_CLASS,
                    "placeholder": "Description (optional)",
                    "rows": 3,
                    "id": "bookmark-description",
                }
            ),
            "category": forms.Select(
                attrs={
                    "class": _INPUT_CLASS,
                    "id": "bookmark-category",
                }
            ),
        }


class BookmarkCategoryForm(forms.ModelForm):
    class Meta:
        model = BookmarkCategory
        fields = ["name", "description", "color", "parent"]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": _INPUT_CLASS, "placeholder": "Category name"}
            ),
            "description": forms.Textarea(
                attrs={
                    "class": _INPUT_CLASS,
                    "placeholder": "Description (optional)",
                    "rows": 2,
                }
            ),
            "color": forms.HiddenInput(
                attrs={"x-model": "selectedColor"}
            ),
            "parent": forms.Select(
                attrs={"class": _INPUT_CLASS}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parent"].required = False
        self.fields["parent"].empty_label = "None (Top level)"
        # Exclude self and descendants from parent choices to prevent circular references
        if self.instance.pk:
            def get_descendants(cat):
                descendants = []
                for child in BookmarkCategory.objects.filter(parent=cat):
                    descendants.append(child.pk)
                    descendants.extend(get_descendants(child))
                return descendants
            exclude_ids = [self.instance.pk] + get_descendants(self.instance)
            self.fields["parent"].queryset = BookmarkCategory.objects.filter(
                user=self.instance.user
            ).exclude(pk__in=exclude_ids)


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = [
            "default_sort",
            "items_per_page",
            "theme_preference",
            "default_display_mode",
        ]
        widgets = {
            "default_sort": forms.Select(
                attrs={
                    "class": _INPUT_CLASS,
                }
            ),
            "items_per_page": forms.NumberInput(
                attrs={
                    "class": _INPUT_CLASS,
                    "min": "5",
                    "max": "100",
                }
            ),
            "theme_preference": forms.Select(
                attrs={
                    "class": _INPUT_CLASS,
                }
            ),
            "default_display_mode": forms.Select(
                attrs={
                    "class": _INPUT_CLASS,
                }
            ),
        }


class EmailLoginForm(AuthenticationForm):
    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(
            attrs={
                "class": _INPUT_CLASS,
                "placeholder": "you@example.com",
                "autofocus": True,
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password"].widget.attrs.update(
            {
                "class": _INPUT_CLASS,
                "placeholder": "Password",
            }
        )


class SignUpForm(UserCreationForm):
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(
            attrs={
                "class": _INPUT_CLASS,
                "placeholder": "you@example.com",
                "autofocus": True,
            }
        ),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].widget.attrs.update(
            {
                "class": _INPUT_CLASS,
                "placeholder": "Create a password",
            }
        )
        self.fields["password2"].widget.attrs.update(
            {
                "class": _INPUT_CLASS,
                "placeholder": "Confirm your password",
            }
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.username = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class StyledPasswordChangeForm(DjangoPasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = _INPUT_CLASS
