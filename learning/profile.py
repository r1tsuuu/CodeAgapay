"""The learner's progress for the profile page, from whichever plan they have (curated or AI-written).

Built from the same records as the plan and finish pages, so the numbers always agree with them.
"""

import math
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from diagnose.models import TopicMastery

from . import ai_plan, journey
from .models import LessonProgress, PlanItem
from .planner import active_plan


def _weeks(since):
    return max(math.ceil((timezone.now() - since).days / 7), 1)


def _curated(profile, plan):
    items = list(plan.items.select_related("topic").order_by("order"))
    done = [i for i in items if i.status == PlanItem.Status.DONE]
    counted = [i for i in items if i.status != PlanItem.Status.SKIPPED]
    reviews = journey.due_reviews(profile, plan)
    return {
        "percent": plan.progress_percent(),
        "done": len(done),
        "total": len(counted),
        "checks_passed": TopicMastery.objects.filter(
            learner=profile, topic__in=[i.topic for i in done], source=TopicMastery.Source.QUIZ
        ).count(),
        "weeks": _weeks(plan.created_at),
        "next": journey.next_action(profile, plan, items, reviews),
        "items": [
            {"title": i.topic.title, "status": i.status, "shaky": i.shaky,
             "url": reverse("lesson", args=[i.topic.slug])}
            for i in items
        ],
    }


def _ai(outline):
    progress = ai_plan.progress_by_key(outline)
    lessons = [x for x in ai_plan.lessons_in_order(outline) if x["kind"] != "setup"]
    statuses = {x["key"]: progress[x["key"]] for x in lessons if x["key"] in progress}
    done = [k for k, p in statuses.items() if p.status == LessonProgress.Status.DONE]
    counted = [x for x in lessons if not (x["key"] in statuses and statuses[x["key"]].status == LessonProgress.Status.SKIPPED)]
    return {
        "percent": round(len(done) * 100 / len(counted)) if counted else 100,
        "done": len(done),
        "total": len(counted),
        # A lesson is done by passing its check, so a done lesson with tries is a passed check.
        "checks_passed": sum(1 for k in done if statuses[k].tries),
        "weeks": _weeks(outline.created_at),
        "next": ai_plan.next_action(outline),
        "items": [
            {"title": x["title"],
             "status": statuses[x["key"]].status if x["key"] in statuses else LessonProgress.Status.TODO,
             "shaky": x["key"] in statuses and statuses[x["key"]].shaky,
             "url": reverse("ai_lesson", args=[x["key"]])}
            for x in lessons
        ],
    }


def summary(profile):
    """Progress on the learner's plan, or None when they don't have one yet."""
    if profile.gets_ai_plans() and (outline := ai_plan.active_outline(profile)) is not None:
        return _ai(outline)
    plan = active_plan(profile)
    return _curated(profile, plan) if plan is not None else None


def plan_started(profile):
    """The day the learner's current plan started, or None without a plan.

    Their target date is kept as weeks from this day (target_weeks), as onboarding asks it.
    """
    if profile.pk is None:
        return None
    if profile.gets_ai_plans() and (outline := ai_plan.active_outline(profile)) is not None:
        return timezone.localdate(outline.created_at)
    plan = active_plan(profile)
    return timezone.localdate(plan.created_at) if plan is not None else None


def target_date(profile):
    """The date the learner is aiming for, or None when they didn't give one."""
    if not profile.target_weeks:
        return None
    return (plan_started(profile) or timezone.localdate()) + timedelta(weeks=profile.target_weeks)


def setup_method(profile):
    """How the learner writes code on their AI plan, e.g. "VS Code, step by step", or ""."""
    if profile.gets_ai_plans() and (outline := ai_plan.active_outline(profile)) is not None:
        return outline.get_setup_choice_display() if outline.setup_choice else ""
    return ""
