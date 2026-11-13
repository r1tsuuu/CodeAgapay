"""Mascots drawn inline, so mascots.js can reach their eyes to blink and look around.

An <img> hides the drawing's parts from the page; inlining the SVG gives the script the eyes.
"""

import re
from functools import lru_cache

from django import template
from django.contrib.staticfiles import finders
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

_SVG_OPEN = re.compile(r"<svg\b([^>]*)>")


@lru_cache(maxsize=32)
def _svg(name):
    path = finders.find(f"img/mascots/{name}.svg")
    if path is None:
        raise template.TemplateSyntaxError(f"No mascot called {name!r} in static/img/mascots/.")
    with open(path, encoding="utf-8") as f:
        svg = f.read()
    # Keep the viewBox, drop the namespace and sizes: the page sizes it and it's already in HTML.
    view_box = re.search(r'viewBox="([^"]+)"', svg).group(1)
    return _SVG_OPEN.sub(f'<svg viewBox="{view_box}" overflow="visible" focusable="false">', svg, count=1)


@register.simple_tag
def mascot(name, css_class=""):
    """A living mascot: `{% mascot "flower-yellow" "how-mascot" %}`. Decorative, so hidden from screen readers."""
    classes = f"critter {escape(css_class)}".strip()
    return mark_safe(f'<span class="{classes}" aria-hidden="true">{_svg(name)}</span>')
