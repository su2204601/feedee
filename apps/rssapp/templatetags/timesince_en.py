from django import template
from django.utils import timezone
from django.utils.timesince import timesince
from django.utils.translation import override

register = template.Library()


@register.filter
def timesince_en(value):
    """timesince that always outputs in English regardless of LANGUAGE_CODE."""
    if value is None:
        return ""
    with override("en"):
        return timesince(value, timezone.now())
