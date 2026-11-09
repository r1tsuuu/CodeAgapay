"""AI-written lessons (docs/plan-framework.md, step 3 in section 2, and sections 6, 7 and 9).

A lesson is written the first time the learner opens it, from one outline lesson. As with
outlines, the code does what it can without the model: warm-ups come from the previous
lesson's saved questions, the glossary from saved key terms, and links are checked
against the allowed list. The system prompt never changes; the request is a short
description of this one lesson.

Checks on every reply:
- Graded questions must be gradable: a multiple choice with a valid answer, or a blank
  with accepted answers. Others are dropped; fewer than 2 left means unusable.
- Links stay only if their site is on the allowed list. Otherwise the URL is dropped
  and the search phrase kept (as a site search link where the site has one).
- Python code that doesn't parse is flagged for review. Code is never run.
A lesson without an example, a task or two gradable questions is asked for again, once.
"""

import ast
import re
from dataclasses import dataclass, field
from urllib.parse import quote_plus, urlparse

from django.db import transaction
from django.db.models import Max

from assistant.service import ask_model_json, language_note

from .models import GeneratedLesson
from .outline import _int, _list, _text, clean_chars, load_prompt, outline_tracks

MAX_TOKENS = 3000  # A lesson is about 1,000 to 1,800 tokens, plus room for short reasoning.
MAX_EARLIER = 12  # Earlier lesson titles sent, newest first; older ones rarely matter and cost tokens.
LANGS = {"python", "html", "css", "javascript", "sql", "java"}
SKILLS = {"recall", "apply", "explain"}

# The depth table (framework section 6), as limits sent with each request.
LIMITS = {
    "beginner": {"ideas": "1 main idea", "terms": 3, "examples": "2 examples: one simple, one real-world"},
    "intermediate": {"ideas": "1 to 2 main ideas", "terms": 5, "examples": "2 real-world examples"},
    "advanced": {"ideas": "2 to 3 main ideas", "terms": 7, "examples": "2 examples: one real-world, one edge case"},
}

# Framework section 9. A link is kept only on these sites (and, for Kaggle, only its Learn pages).
# YouTube is left out on purpose: videos are named by channel and search phrase until checked.
ALLOWED_LINKS = [
    ("developer.mozilla.org", ""), ("python.org", ""), ("w3schools.com", ""), ("freecodecamp.org", ""),
    ("theodinproject.com", ""), ("cs50.harvard.edu", ""), ("khanacademy.org", ""), ("kaggle.com", "/learn"),
    ("realpython.com", ""), ("exercism.org", ""), ("colab.research.google.com", ""), ("codepen.io", ""),
    ("nodejs.org", ""), ("code.visualstudio.com", ""), ("git-scm.com", ""), ("stackoverflow.com", ""),
]
# Sites with a search page, so a search phrase becomes a link that always works.
SEARCH_LINKS = {
    "mdn": "https://developer.mozilla.org/en-US/search?q={}",
    "python": "https://docs.python.org/3/search.html?q={}",
}
DEFAULT_SITE = {"python": "Python docs", "html": "MDN Web Docs", "css": "MDN Web Docs", "javascript": "MDN Web Docs"}


@dataclass
class LessonSpec:
    """Everything the lesson request needs, from an outline or typed in by hand (draft_lesson)."""

    key: str
    title: str
    can: str = ""
    minutes: int = 25
    kind: str = "core"
    level: str = "beginner"
    path: str = ""
    tracks: str = ""
    earlier: list = field(default_factory=list)
    needs: list = field(default_factory=list)
    project: str = ""
    learns_from: str = ""
    taglish: bool = False
    struggled: list = field(default_factory=list)


def spec_from_outline(outline, key, struggled=()):
    """The request for one lesson of a saved outline. Raises KeyError for an unknown lesson."""
    lessons = [lesson for module in outline.data.get("modules", []) for lesson in module["lessons"]]
    by_key = {lesson["key"]: lesson for lesson in lessons}
    lesson = by_key[key]
    position = lessons.index(lesson)
    learner = outline.learner
    return LessonSpec(
        key=key, title=lesson["title"], can=lesson.get("can", ""), minutes=lesson["minutes"],
        kind=lesson["kind"], level=outline.data.get("level", "beginner"),
        path=learner.path.title if learner.path_id else "Learn to code",
        tracks=", ".join(t.name for t in outline_tracks(learner)),
        earlier=[x["title"] for x in lessons[:position]][-MAX_EARLIER:],
        needs=[by_key[k]["title"] for k in lesson.get("needs", []) if k in by_key],
        project=(outline.data.get("project") or {}).get("title", ""),
        learns_from=learner.get_hint_style_display().lower() if learner.hint_style else "",
        taglish=bool(language_note(f"{learner.goal_text} {outline.data.get('goal', '')}")),
        struggled=[_text(s, 200) for s in struggled if _text(s, 200)][:5],
    )


def build_messages(spec):
    """The fixed system prompt and a short description of this lesson."""
    system, version = load_prompt("lesson")
    limits = LIMITS.get(spec.level, LIMITS["beginner"])
    if spec.kind == "recap":
        shape = "This is a recap: a 5 to 10 minute summary of something they partly know, then 3 check questions."
    else:
        shape = (f"Limits: {limits['ideas']}, up to {limits['terms']} key terms, {limits['examples']}, "
                 f"about {spec.minutes} minutes, 2 to 3 check questions.")
    lines = [
        f"Lesson {spec.key}: {spec.title} ({spec.kind})",
        f"You will be able to: {spec.can}" if spec.can else "",
        f"Path: {spec.path} ({spec.tracks})" if spec.path else "",
        f"Level: {spec.level}. {shape}",
        f"Earlier lessons: {', '.join(spec.earlier)}" if spec.earlier else "Earlier lessons: none, this is the first.",
        f"Builds on: {', '.join(spec.needs)}" if spec.needs else "",
        f"Project: {spec.project}" if spec.project else "",
        f"Learns best from: {spec.learns_from}" if spec.learns_from else "",
        "Language: Taglish" if spec.taglish else "",
        f"Struggled with: {'; '.join(spec.struggled)}. Teach it a different way." if spec.struggled else "",
    ]
    user = "\n".join(line for line in lines if line)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}], version


def _code(value, limit=1500):
    """Code keeps its line breaks and indentation; only the ends are trimmed."""
    lines = clean_chars(value or "").strip("\n").rstrip().split("\n")
    return "\n".join(line.rstrip() for line in lines)[:limit]


def _paragraphs(value, limit=2500):
    parts = [_text(p, limit) for p in str(value or "").split("\n\n")]
    return "\n\n".join(p for p in parts if p)[:limit]


def allowed_link(url):
    parts = urlparse(url)
    host = (parts.hostname or "").removeprefix("www.")
    return parts.scheme == "https" and any(
        (host == domain or host.endswith("." + domain)) and parts.path.startswith(prefix)
        for domain, prefix in ALLOWED_LINKS
    )


def search_link(name, phrase):
    name = name.lower()
    for site, pattern in SEARCH_LINKS.items():
        if site in name and phrase:
            return pattern.format(quote_plus(phrase))
    return ""


def _resources(items, spec, lang, repairs):
    resources = []
    for item in _list(items)[:5]:
        if not isinstance(item, dict) or not _text(item.get("name"), 120):
            continue
        name, search = _text(item.get("name"), 120), _text(item.get("search"), 120)
        url = str(item.get("url") or "").strip()
        if url and not allowed_link(url):
            repairs.append(f"Dropped a link not on the allowed list: {urlparse(url).hostname or url[:40]}")
            url = ""
        wanted = "primary" if _text(item.get("role"), 10).lower() == "primary" else "optional"
        resources.append({"name": name, "role": wanted, "url": url or search_link(name, search), "search": search})
    resources = resources[:3]
    if not resources:
        site = DEFAULT_SITE.get(lang, "W3Schools")
        resources = [{"name": site, "role": "primary", "url": search_link(site, spec.title), "search": spec.title}]
        repairs.append(f"No usable resources; added {site}")
    # Exactly one primary (framework section 6): the first the model marked, else the first.
    primary = next((i for i, x in enumerate(resources) if x["role"] == "primary"), 0)
    for i, resource in enumerate(resources):
        resource["role"] = "primary" if i == primary else "optional"
    return resources


# Opening tags in HTML code, and the page skeleton every lesson may use without explaining it.
HTML_TAG = re.compile(r"<([a-z][a-z0-9]*)")
BASIC_TAGS = {"html", "head", "body", "title"}
# Lessons often explain a tag by its everyday name ("paragraphs", "a list") instead of writing it.
TAG_NAMES = {
    "p": "paragraph", "h1": "heading", "h2": "heading", "h3": "heading", "h4": "heading", "h5": "heading",
    "h6": "heading", "ul": "list", "ol": "list", "li": "list", "a": "link", "img": "image", "br": "line break",
    "table": "table", "tr": "table", "td": "table", "th": "table", "form": "form", "input": "input", "button": "button",
}
TAG = re.compile(r"<\s*/?\s*([a-zA-Z][a-zA-Z0-9]*)\s*>")


def _tag_variants(accepted, prompt):
    """Accept an HTML tag with or without its brackets, so "h2" and "<h2>" both count.

    Seen live: the model accepted only "<h2>" for "heading level 2 is written as ___". When the
    blank already sits inside brackets ("<___>"), only the bare name fits, so brackets aren't added.
    """
    result = list(accepted)
    for answer in accepted:
        match = TAG.fullmatch(answer)
        if match:
            result.append(match.group(1))
        elif re.fullmatch(r"[a-zA-Z][a-zA-Z0-9]*", answer) and "tag" in prompt.lower() and "<___" not in prompt:
            result.append(f"<{answer}>")
    return list(dict.fromkeys(result))  # No repeats, first spelling first.


def _question(item, n, repairs, flags):
    """One check question in the app's shape, or None if it can't be used."""
    if not isinstance(item, dict):
        return None
    kind = str(item.get("type") or "").lower()
    prompt = _text(item.get("q"), 400)
    skill = str(item.get("skill") or "").lower()
    base = {"type": kind, "skill": skill if skill in SKILLS else "recall", "prompt": prompt,
            "explanation": _text(item.get("why"), 300)}
    if not prompt:
        reason = "no question"
    elif kind == "mc":
        choices = [_text(c, 200) for c in _list(item.get("choices")) if _text(c, 200)]
        correct = _int(item.get("correct"))
        if len(choices) >= 2 and len(set(choices)) == len(choices) and correct is not None and 0 <= correct < len(choices):
            return {**base, "choices": choices, "correct": correct}
        reason = "choices or answer unusable"
    elif kind == "blank":
        accepted = _tag_variants([_text(a, 100) for a in _list(item.get("accept")) if _text(a, 100)], prompt)
        if "___" in prompt and accepted:
            if any(len(a.split()) > 3 for a in accepted):
                flags.append(f"Check {n}: a blank's answer is long, so learners may type it differently")
            question = prompt.replace("___", " ").lower()
            if any(re.search(rf"(?<!\w){re.escape(a.lower())}(?!\w)", question) for a in accepted):
                flags.append(f"Check {n}: the question shows its own answer")
            return {**base, "accepted_answers": accepted}
        reason = "no ___ or no accepted answers"
    elif kind == "self":
        sample = _text(item.get("sample"), 600)
        if sample:
            return {**base, "sample_answer": sample}
        reason = "no sample answer"
    else:
        reason = f"unknown type {kind!r}"
    repairs.append(f"Dropped check question {n}: {reason}")
    return None


# How a comment line starts in each language. Per language, because "#" and "--" start real
# CSS ("#header { }", "--main-color: red;").
COMMENT_STARTS = {
    "python": ("#",), "javascript": ("//", "/*"), "java": ("//", "/*"), "sql": ("-- ",),
    "html": ("<!--",), "css": ("/*",),
}


def _only_comments(code, lang):
    """True for a placeholder example such as "# not applicable": every line is a comment."""
    starts = COMMENT_STARTS.get(lang)
    if not starts:
        return False
    return all(line.strip().startswith(starts) or line.strip().endswith(("*/", "-->"))
               for line in code.splitlines() if line.strip())


def _explained(tag, taught):
    """The tag, or its everyday name, appears in what the lesson (or an earlier one) teaches."""
    return bool(re.search(rf"(?<![a-z0-9]){tag}(?![a-z0-9])", taught)) or TAG_NAMES.get(tag, "@") in taught


def _syntax_problem(code):
    try:
        ast.parse(code)
    except SyntaxError as error:
        return f"line {error.lineno}: {error.msg}"
    return None


def parse_lesson(data, spec):
    """Check and repair the model's lesson. Returns (lesson or None, repairs, flags).

    Repairs are what the code fixed. Flags are what a person should look at (framework
    section 11): the code can't tell whether they are wrong, only that they might be.
    """
    repairs, flags = [], []
    limits = LIMITS.get(spec.level, LIMITS["beginner"])

    terms = [{"term": _text(t.get("term"), 80), "definition": _text(t.get("def"), 200)}
             for t in _list(data.get("terms")) if isinstance(t, dict) and _text(t.get("term"), 80) and _text(t.get("def"), 200)]
    if len(terms) > limits["terms"]:
        repairs.append(f"{len(terms)} key terms cut to {limits['terms']}")
        terms = terms[:limits["terms"]]

    examples = []
    for n, item in enumerate(_list(data.get("examples"))[:4], 1):
        if not (isinstance(item, dict) and _code(item.get("code"))):
            continue
        lang = str(item.get("lang") or "").lower()
        if _only_comments(_code(item.get("code")), lang):
            repairs.append(f"Dropped example {n}: only comments")  # e.g. "# not applicable to HTML"
            continue
        examples.append({"lang": lang if lang in LANGS else "", "code": _code(item.get("code")),
                         "output": _code(item.get("output"), 800), "note": _text(item.get("note"), 200)})
    examples = examples[:3]
    # The lesson's language is what most examples use, so one stray example can't relabel it.
    langs = [x["lang"] for x in examples if x["lang"]]
    lang = max(langs, key=langs.count) if langs else ""

    task = data.get("try") if isinstance(data.get("try"), dict) else {}
    try_it = {"prompt": _paragraphs(task.get("prompt"), 800), "starter_code": _code(task.get("starter")),
              "sample_answer": _code(task.get("answer")),
              "checklist": [_text(c, 200) for c in _list(task.get("checks"))[:4] if _text(c, 200)]}

    check = [q for n, item in enumerate(_list(data.get("check"))[:6], 1)
             if (q := _question(item, n, repairs, flags)) is not None][:5]
    graded = [q for q in check if q["type"] in ("mc", "blank")]

    missing = [name for name, ok in [
        ("an explanation", _paragraphs(data.get("explain"))), ("an example", examples),
        ("a task", try_it["prompt"]), ("2 gradable check questions", len(graded) >= 2),
    ] if not ok]
    if missing:
        repairs.append(f"Unusable: missing {', '.join(missing)}")
        return None, repairs, flags

    for n, example in enumerate(examples, 1):
        if example["lang"] == "python" and (problem := _syntax_problem(example["code"])):
            flags.append(f"Example {n} is not valid Python ({problem})")
    if lang == "python" and try_it["sample_answer"] and (problem := _syntax_problem(try_it["sample_answer"])):
        flags.append(f"Task answer is not valid Python ({problem})")
    if lang == "html":
        taught = " ".join([data.get("why") or "", data.get("explain") or "", *spec.earlier,
                           *(f"{t['term']} {t['definition']}" for t in terms)]).lower()
        code = [x["code"] for x in examples if x["lang"] == "html"] + [try_it["starter_code"], try_it["sample_answer"]]
        unexplained = sorted({tag for block in code for tag in HTML_TAG.findall(block.lower())
                              if tag not in BASIC_TAGS and not _explained(tag, taught)})
        if unexplained:
            flags.append(f"Examples or the task use tags the lesson doesn't explain: "
                         f"{', '.join('<' + t + '>' for t in unexplained)}")

    lesson = {
        "why": _text(data.get("why"), 400),
        "key_terms": terms,
        "explanation": _paragraphs(data.get("explain")),
        "examples": examples,
        "try_it": try_it,
        "resources": _resources(data.get("resources"), spec, lang, repairs),
        "check": check,
        "lang": lang,
    }
    return lesson, repairs, flags


def generate_lesson(spec, outline=None, save=True):
    """Ask the AI for one lesson, check it, and save it as the current version.

    Returns the GeneratedLesson (unsaved when save=False), or None when the AI is
    unavailable or replied with nothing usable twice. Saving needs the outline.
    """
    messages, version = build_messages(spec)
    usage = {}
    earlier_problems = []
    for _ in range(2):
        attempt = {}
        data = ask_model_json(messages, max_tokens=MAX_TOKENS, usage=attempt)
        for name in ("prompt_tokens", "completion_tokens"):
            usage[name] = (usage.get(name) or 0) + (attempt.get(name) or 0)
        usage["model"] = attempt.get("model", usage.get("model", ""))
        if data is None:
            return None  # Every provider failed; asking again would only fail again.
        lesson, repairs, flags = parse_lesson(data, spec)
        if lesson is not None:
            break
        # Kept so a retry, and its doubled token count, is explained in review.
        earlier_problems = [f"Asked again: the first reply was unusable ({repairs[-1]})"]
    else:
        return None
    repairs = earlier_problems + repairs
    record = GeneratedLesson(
        outline=outline, key=spec.key, title=spec.title, data=lesson, repairs=repairs, flags=flags,
        prompt_version=version, model=usage.get("model", ""),
        prompt_tokens=usage.get("prompt_tokens") or None, completion_tokens=usage.get("completion_tokens") or None,
    )
    record.raw = data  # The model's reply before checks, for draft_lesson --raw. Not saved.
    if save:
        if outline is None:
            raise ValueError("Saving a lesson needs its outline.")
        with transaction.atomic():
            earlier = GeneratedLesson.objects.select_for_update().filter(outline=outline, key=spec.key)
            record.version = (earlier.aggregate(n=Max("version"))["n"] or 0) + 1
            earlier.filter(is_current=True).update(is_current=False)
            record.save()
    return record


def current_lesson(outline, key):
    return GeneratedLesson.objects.filter(outline=outline, key=key, is_current=True).first()


def lesson_for(outline, key):
    """The saved lesson, or a newly written one the first time it is opened. None if the AI can't."""
    return current_lesson(outline, key) or generate_lesson(spec_from_outline(outline, key), outline)


def regenerate_lesson(outline, key, struggled=()):
    """A new version, taught differently (framework section 7, below 50%). The old one is kept for review."""
    return generate_lesson(spec_from_outline(outline, key, struggled), outline)


def glossary(outline):
    """Every key term from the outline's current lessons, in lesson order (framework section 5)."""
    order = {lesson["key"]: n for n, lesson in enumerate(
        (x for module in outline.data.get("modules", []) for x in module["lessons"]))}
    lessons = sorted(outline.lessons.filter(is_current=True), key=lambda x: order.get(x.key, len(order)))
    seen, terms = set(), []
    for lesson in lessons:
        for term in lesson.data.get("key_terms", []):
            if term["term"].lower() not in seen:
                seen.add(term["term"].lower())
                terms.append(term)
    return terms


def warm_up(outline, key):
    """Up to 2 ungraded questions from the previous lesson's check, so warm-ups cost no tokens.

    Preferring questions the learner missed comes with the lesson page, which records answers.
    """
    keys = [x["key"] for module in outline.data.get("modules", []) for x in module["lessons"]]
    if key not in keys or keys.index(key) == 0:
        return []
    previous = current_lesson(outline, keys[keys.index(key) - 1])
    if previous is None:
        return []
    return [q for q in previous.data.get("check", []) if q["type"] in ("mc", "blank")][:2]
