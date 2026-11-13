"""How AI lesson text looks on the page: colored code, short paragraphs, code words that stand out.

The AI only marks code words with backticks and names each example's language. The coloring
and layout happen here, so they cost no tokens and look the same in every lesson. Everything
is escaped before any markup is added, so lesson text can never inject HTML.
"""

import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.util import ClassNotFound

from learning.lessons import blocks

register = template.Library()

FORMATTER = HtmlFormatter(nowrap=True)
# HTML tags written in a sentence without backticks, after escaping: &lt;p&gt;, &lt;/ul&gt;, &lt;!DOCTYPE html&gt;
BARE_TAG = re.compile(r"&lt;/?!?[a-zA-Z][a-zA-Z0-9]*(?: [^&]{0,30})?&gt;")


@register.filter
def panel_language(language, code=""):
    """The coding panel's runner for a track slug or code language: {{ track.slug|panel_language:code }}."""
    from learning.code_panel import panel_language as pick

    return pick(language, code or "")


@register.filter
def can_run(language, code=""):
    """Whether to offer "Try this code" for an example in this language."""
    from learning.code_panel import can_run as check

    return check(language, code or "")


@register.filter
def highlight_code(code, lang):
    """Code colored like an editor. Unknown languages are shown plain."""
    try:
        lexer = get_lexer_by_name(lang or "text")
    except ClassNotFound:
        lexer = TextLexer()
    return mark_safe(highlight(code or "", lexer, FORMATTER).rstrip("\n"))


# Things to click or choose, written **like this**: bold, in the normal text color (code has the color).
UI_ITEM = re.compile(r"\*\*(.+?)\*\*")
# Keyboard shortcuts such as Ctrl+S, Cmd+Shift+X or Alt+F4, shown as key caps.
SHORTCUT = re.compile(r"\b(?:Ctrl|Cmd|Alt|Option|Shift)(?:\+(?:Ctrl|Cmd|Alt|Option|Shift|[A-Z0-9]|F\d{1,2}|Enter|Tab))+\b")


def _keys(match):
    return "+".join(f"<kbd>{key}</kbd>" for key in match.group(0).split("+"))


def _prose(escaped):
    """Marks in ordinary words: HTML tags as code, **items** to click in bold, shortcuts as keys."""
    escaped = BARE_TAG.sub(lambda m: f'<code class="inline-code">{m.group(0)}</code>', escaped)
    escaped = UI_ITEM.sub(r'<strong class="ui-item">\1</strong>', escaped)
    return SHORTCUT.sub(_keys, escaped)


@register.filter
def inline_code(text):
    """A sentence with its code words bold and colored, things to click in bold, and shortcuts as keys."""
    parts = str(text or "").split("`")
    if len(parts) % 2 == 0:  # An unclosed backtick: show it as typed rather than guess.
        parts = [str(text or "")]
    html = []
    for i, part in enumerate(parts):
        if i % 2:
            html.append(f'<code class="inline-code">{escape(part)}</code>')
        else:
            html.append(_prose(str(escape(part))))
    return mark_safe("".join(html))


@register.filter
def paragraphs(text):
    """Short paragraphs and lists, each with its code words marked.

    Long ones are split here too, not only when a lesson is saved, so lessons written
    before the split existed read the same after a refresh.
    """
    html = []
    for kind, content in blocks(text):
        if kind == "p":
            html.append(f"<p>{inline_code(content)}</p>")
        else:
            items = "".join(f"<li>{inline_code(item)}</li>" for item in content)
            html.append(f'<{kind} class="lesson-list">{items}</{kind}>')
    return mark_safe("".join(html))
