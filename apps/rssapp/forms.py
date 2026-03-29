from django import forms

from .models import Bookmark, Feed, Tag

_INPUT_CLASS = (
    "w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm "
    "placeholder-gray-400 focus:border-brand-500 focus:ring-2 focus:ring-brand-100 "
    "focus:outline-none transition-colors"
)


class FeedCreateForm(forms.ModelForm):
    class Meta:
        model = Feed
        fields = ["name", "url", "category"]
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
                attrs={"class": _INPUT_CLASS, "placeholder": "Category (optional)"}
            ),
        }


class FeedUpdateForm(forms.ModelForm):
    class Meta:
        model = Feed
        fields = ["name", "url", "category", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": _INPUT_CLASS}),
            "url": forms.URLInput(attrs={"class": _INPUT_CLASS}),
            "category": forms.TextInput(
                attrs={"class": _INPUT_CLASS, "placeholder": "Uncategorized"}
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
            "color": forms.TextInput(
                attrs={
                    "class": "h-9 w-14 rounded-lg border border-gray-200 cursor-pointer",
                    "type": "color",
                }
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
        fields = ["url", "title", "description"]
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
        }
