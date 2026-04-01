from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm as DjangoPasswordChangeForm

from .models import Bookmark, Feed, Tag, UserProfile

User = get_user_model()

_INPUT_CLASS = (
    "w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm "
    "placeholder-gray-400 focus:border-brand-500 focus:ring-2 focus:ring-brand-100 "
    "focus:outline-none transition-colors"
)

TAG_COLOR_CHOICES = [
    "#EF4444",  # Red
    "#F97316",  # Orange
    "#EAB308",  # Yellow
    "#22C55E",  # Green
    "#14B8A6",  # Teal
    "#3B82F6",  # Blue
    "#6366F1",  # Indigo
    "#8B5CF6",  # Violet
    "#EC4899",  # Pink
    "#6B7280",  # Gray
]


class ColorSwatchWidget(forms.HiddenInput):
    """Hidden input with color swatch UI rendered via custom HTML."""

    def __init__(self, colors=None, attrs=None):
        self.colors = colors or TAG_COLOR_CHOICES
        super().__init__(attrs=attrs)

    def render(self, name, value, attrs=None, renderer=None):
        from django.utils.html import format_html, mark_safe

        hidden = super().render(name, value, attrs, renderer)
        swatches = []
        for color in self.colors:
            checked = "ring-2 ring-offset-1" if value == color else ""
            swatches.append(format_html(
                '<button type="button" '
                'class="color-swatch w-7 h-7 rounded-full border-2 border-transparent '
                'hover:scale-110 transition-all cursor-pointer {checked}" '
                'data-color="{color}" '
                'style="background-color:{color};--ring-color:{color}; {ring_style}">'
                '</button>',
                color=color,
                checked=checked,
                ring_style=format_html("box-shadow:0 0 0 2px white, 0 0 0 4px {}", color) if value == color else "",
            ))
        script = format_html(
            '<script>'
            'document.querySelectorAll("[data-color][data-for=\'{name}\']").length||'
            'document.currentScript.parentElement.querySelectorAll(".color-swatch").forEach(function(b){{'
            'b.setAttribute("data-for","{name}");'
            'b.addEventListener("click",function(){{'
            'var inp=document.getElementById("{id}");'
            'inp.value=b.dataset.color;'
            'b.parentElement.querySelectorAll(".color-swatch").forEach(function(s){{'
            's.style.boxShadow="";}});'
            'b.style.boxShadow="0 0 0 2px white, 0 0 0 4px "+b.dataset.color;'
            '}});}});'
            '</script>',
            name=name,
            id=attrs.get("id", "id_" + name) if attrs else "id_" + name,
        )
        return mark_safe(
            '<div class="flex flex-wrap gap-1.5">'
            + hidden
            + "".join(str(s) for s in swatches)
            + str(script)
            + "</div>"
        )


class FeedCreateForm(forms.ModelForm):
    class Meta:
        model = Feed
        fields = ["name", "url", "category"]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": _INPUT_CLASS, "placeholder": "Auto-detected from feed", "id": "feed-name"}
            ),
            "url": forms.URLInput(
                attrs={
                    "class": _INPUT_CLASS,
                    "placeholder": "https://example.com/rss.xml",
                    "id": "feed-url",
                }
            ),
            "category": forms.TextInput(
                attrs={"class": _INPUT_CLASS, "placeholder": "Category (optional)"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].required = False


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
            "color": ColorSwatchWidget(),
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
                    "placeholder": "Auto-detected from URL",
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


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["default_sort", "items_per_page"]
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
        self.fields["password"].widget.attrs.update({
            "class": _INPUT_CLASS,
            "placeholder": "Password",
        })


class StyledPasswordChangeForm(DjangoPasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = _INPUT_CLASS


class SignupForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={
                "class": _INPUT_CLASS,
                "placeholder": "you@example.com",
                "autofocus": True,
            }
        ),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "class": _INPUT_CLASS,
                "placeholder": "Password",
            }
        ),
    )
    password_confirm = forms.CharField(
        label="Confirm password",
        widget=forms.PasswordInput(
            attrs={
                "class": _INPUT_CLASS,
                "placeholder": "Confirm password",
            }
        ),
    )

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        pw = cleaned_data.get("password")
        pw2 = cleaned_data.get("password_confirm")
        if pw and pw2 and pw != pw2:
            self.add_error("password_confirm", "Passwords do not match.")
        return cleaned_data
