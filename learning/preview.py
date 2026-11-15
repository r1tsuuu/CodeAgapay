"""A plan preview for visitors who haven't signed in, one per goal.

Built by the same rules as a real plan (`planner.order_topics` and `assign_weeks`) from the
curated topics, for a beginner at a typical pace, so the preview never promises what the
planner wouldn't give. Nothing here calls the AI.
"""

from dataclasses import dataclass, field
from urllib.parse import urlparse

from content.models import Topic

from .planner import assign_weeks, estimate_weeks, order_topics

PREVIEW_HOURS = 4  # "3–5 hours a week", the middle answer in onboarding.

# Friendly names for the sites curators link to most. Anything else shows its domain.
SOURCE_NAMES = {
    "developer.mozilla.org": "MDN Web Docs",
    "freecodecamp.org": "freeCodeCamp",
    "w3schools.com": "W3Schools",
    "docs.python.org": "Python docs",
    "dev.java": "Java docs (dev.java)",
    "docs.oracle.com": "Java docs (Oracle)",
    "sqlbolt.com": "SQLBolt",
    "sqlite.org": "SQLite docs",
    "javascript.info": "javascript.info",
    "web.dev": "web.dev",
    "code.visualstudio.com": "VS Code docs",
    "git-scm.com": "Git docs",
    "docs.github.com": "GitHub Docs",
    "realpython.com": "Real Python",
}


def source_name(url):
    host = (urlparse(url).hostname or "").removeprefix("www.")
    return SOURCE_NAMES.get(host, host)


@dataclass
class PlanPreview:
    slug: str
    title: str
    tagline: str
    language: str
    language_reason: str
    weeks_low: int
    weeks_high: int
    topic_count: int
    project_title: str = ""
    project_brief: str = ""
    first_milestone: str = ""
    week_one: list = field(default_factory=list)  # [{"title", "minutes", "summary"}]
    sources: list = field(default_factory=list)
    checkable: list = field(default_factory=list)  # Topic titles the quick check can skip.
    sample: dict = field(default_factory=dict)  # One topic of week 1, for "A week in your plan".


def build(path, hours=PREVIEW_HOURS):
    tracks = path.active_tracks()
    if not tracks:
        # No curated topics yet (AI plans can still start it): name the language, promise nothing else.
        first = path.first_track()
        if first is None:
            return None
        return PlanPreview(slug=path.slug, title=path.title, tagline=path.tagline, language=first.name,
                           language_reason=path.language_reason, weeks_low=0, weeks_high=0, topic_count=0)
    rank = {t.pk: i for i, t in enumerate(tracks)}
    topics = list(
        Topic.objects.filter(track__in=tracks)
        .select_related("track")
        .prefetch_related("prerequisites", "resources", "skill_questions", "practice_tasks", "tips")
    )
    prereqs = {t.pk: {p.pk for p in t.prerequisites.all()} for t in topics}
    ordered = order_topics(topics, prereqs, rank)
    weeks = assign_weeks(ordered, hours)
    first_week = [t for t, w in zip(ordered, weeks) if w == 1]
    low, high = estimate_weeks(sum(t.estimated_minutes for t in ordered), hours)

    sources = []
    for topic in ordered:
        for resource in topic.resources.all():
            if resource.is_active and (name := source_name(resource.url)) not in sources:
                sources.append(name)

    idea = next((i for t in tracks for i in t.project_ideas.filter(is_active=True).order_by("order", "pk")), None)
    first = first_week[0] if first_week else None
    resource = next((r for r in first.resources.all() if r.is_active), None) if first else None
    task = next((p for p in first.practice_tasks.all() if p.approved), None) if first else None
    tip = next(iter(first.tips.all()), None) if first else None
    return PlanPreview(
        slug=path.slug, title=path.title, tagline=path.tagline,
        language=tracks[0].name, language_reason=path.language_reason,
        weeks_low=low, weeks_high=high, topic_count=len(ordered),
        project_title=idea.title if idea else "",
        project_brief=idea.brief if idea else "",
        # Week 1's milestone: what the last topic of the week lets them do.
        first_milestone=next((t.summary for t in reversed(first_week) if t.summary), ""),
        week_one=[{"title": t.title, "minutes": t.estimated_minutes, "summary": t.summary} for t in first_week],
        sources=sources[:5],
        checkable=[t.title for t in ordered if t.skill_questions.all()][:4],
        sample={
            "topic": first.title, "summary": first.summary, "minutes": first.estimated_minutes,
            "resource": resource.title if resource else "", "resource_source": source_name(resource.url) if resource else "",
            "resource_minutes": resource.estimated_minutes if resource else 0,
            "task": task.prompt if task else "", "tip": tip.text if tip else "",
        } if first else {},
    )


def previews(paths):
    return [p for p in (build(path) for path in paths) if p is not None]
