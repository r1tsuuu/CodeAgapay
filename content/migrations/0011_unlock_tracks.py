"""Fill and open the HTML, CSS, JavaScript, Java and SQL tracks, which showed "Coming soon".

Loads the reviewed lesson files in content/drafts/ (topics with their intro, tips, skill-check
questions, quiz items and two links each, plus setup steps and a project idea), then switches
each track on. Render runs migrations on every deploy, so the live site fills itself.

Only adds: tracks are found by slug and topics by title, and anything already there is left
as it is. A track that doesn't exist (a fresh test database) is skipped, so this never
creates tracks. Run twice, nothing changes.
"""

import json
from pathlib import Path

from django.db import migrations
from django.utils.text import slugify

DRAFTS = Path(__file__).resolve().parent.parent / "drafts"
TRACKS = ["html", "css", "javascript", "java", "sql"]


def _minutes(value):
    try:
        return min(max(int(value), 15), 180)
    except (TypeError, ValueError):
        return 60


def load(apps, schema_editor):
    Track = apps.get_model("content", "Track")
    Topic = apps.get_model("content", "Topic")
    Resource = apps.get_model("content", "Resource")
    Tip = apps.get_model("content", "Tip")
    SkillQuestion = apps.get_model("content", "SkillQuestion")
    QuizItem = apps.get_model("content", "QuizItem")
    SetupStep = apps.get_model("content", "SetupStep")
    ProjectIdea = apps.get_model("content", "ProjectIdea")

    for slug in TRACKS:
        track = Track.objects.filter(slug=slug).first()
        path = DRAFTS / f"{slug}.json"
        if track is None or not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))

        if not SetupStep.objects.filter(track=track).exists():
            for order, step in enumerate(data.get("setup_steps", []), 1):
                SetupStep.objects.create(track=track, order=order, **step)

        for order, idea in enumerate(data.get("project_ideas", []), 1):
            if not ProjectIdea.objects.filter(track=track, title=idea["title"]).exists():
                ProjectIdea.objects.create(track=track, order=order, **idea)

        previous = Topic.objects.filter(track=track).order_by("order", "title").last()
        next_order = (previous.order if previous else 0) + 1
        for draft in data.get("topics", []):
            existing = Topic.objects.filter(track=track, title=draft["title"]).first()
            if existing is not None:
                previous = existing
                continue
            topic_slug = slugify(f"{slug}-{draft['title']}")[:200]
            if Topic.objects.filter(slug=topic_slug).exists():
                continue
            topic = Topic.objects.create(
                track=track, title=draft["title"], slug=topic_slug, order=next_order,
                summary=draft.get("summary", ""),
                why_it_matters=draft.get("why_it_matters", ""),
                key_terms=draft.get("key_terms", [])[:3],
                explanation=draft.get("explanation", "").strip(),
                example=draft.get("example", "").strip("\n"),
                example_output=draft.get("example_output", "").strip("\n"),
                estimated_minutes=_minutes(draft.get("estimated_minutes")),
                intro_approved=True,
            )
            next_order += 1
            if previous is not None:
                topic.prerequisites.add(previous)
            for i, text in enumerate(draft.get("tips", []), 1):
                Tip.objects.create(topic=topic, text=text, order=i)
            for i, q in enumerate(draft.get("skill_questions", []), 1):
                SkillQuestion.objects.create(
                    topic=topic, prompt=q["prompt"], code_snippet=q.get("code_snippet", ""),
                    choices=q["choices"], correct_index=q["correct_index"], order=i,
                )
            for q in draft.get("quiz_items", []):
                QuizItem.objects.create(
                    topic=topic, prompt=q["prompt"], accepted_answers=q["accepted_answers"],
                    hint=q.get("hint", ""), explanation=q.get("explanation", ""),
                    case_sensitive=q.get("case_sensitive", False),
                )
            for order, resource in enumerate(draft.get("resources", []), 1):
                Resource.objects.create(topic=topic, order=order, **resource)
            previous = topic

        if Topic.objects.filter(track=track).exists() and not track.is_active:
            track.is_active = True
            track.save(update_fields=["is_active"])


class Migration(migrations.Migration):
    dependencies = [("content", "0010_quiz_explanation")]

    operations = [migrations.RunPython(load, migrations.RunPython.noop)]
