"""Reasons to come back: a weekly streak and milestone badges.

Nothing here is stored. Both are worked out from what the learner already did (quiz
attempts, practice answers, finished topics and lessons), so they always agree with the
plan and profile pages, and there's nothing to keep in sync.

A week runs Monday to Sunday. The streak counts weeks in a row with any learning in them.
It stays alive until the end of this week, so it doesn't break on a Monday morning before
the learner has had a chance to study.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Max
from django.utils import timezone

from . import ai_plan
from .models import LessonProgress, PlanItem, PracticeSubmission, QuizAttempt
from .planner import active_plan
from .profile import summary

STREAK_BADGE_WEEKS = 3


def _week_start(day):
    return day - timedelta(days=day.weekday())


def active_days(profile):
    """Every day the learner did something: a quiz, a practice answer, a lesson opened or finished."""
    stamps = [
        *QuizAttempt.objects.filter(learner=profile).values_list("created_at", flat=True),
        *PracticeSubmission.objects.filter(learner=profile).values_list("created_at", flat=True),
        *PlanItem.objects.filter(plan__learner=profile, completed_at__isnull=False).values_list("completed_at", flat=True),
        *LessonProgress.objects.filter(outline__learner=profile).values_list("updated_at", flat=True),
    ]
    return {timezone.localdate(stamp) for stamp in stamps}


@dataclass
class Streak:
    weeks: int  # Weeks in a row, up to this week (or last week, if nothing yet this week).
    this_week: bool  # Already learned something this week.
    best: int  # Longest run ever.

    @property
    def at_risk(self):
        """A streak that ends unless they learn something before Sunday."""
        return self.weeks > 0 and not self.this_week


def weekly_streak(profile, today=None):
    weeks = {_week_start(day) for day in active_days(profile)}
    this = _week_start(today or timezone.localdate())
    start = this if this in weeks else this - timedelta(weeks=1)
    count = 0
    while start in weeks:
        count += 1
        start -= timedelta(weeks=1)
    best = run = 0
    previous = None
    for week in sorted(weeks):
        run = run + 1 if previous is not None and week - previous == timedelta(weeks=1) else 1
        best = max(best, run)
        previous = week
    return Streak(weeks=count, this_week=this in weeks, best=best)


def _module_done(profile):
    """A whole module (AI plan) or plan week (curated plan) finished, with at least one lesson done."""
    if profile.gets_ai_plans() and (outline := ai_plan.active_outline(profile)) is not None:
        progress = ai_plan.progress_by_key(outline)
        for module in outline.data.get("modules", []):
            statuses = [progress[x["key"]].status if x["key"] in progress else None for x in module["lessons"]]
            if statuses and all(ai_plan.is_finished(s) for s in statuses) and LessonProgress.Status.DONE in statuses:
                return True
        return False
    plan = active_plan(profile)
    if plan is None:
        return False
    weeks = {}
    for week, status in plan.items.values_list("week", "status"):
        weeks.setdefault(week, []).append(status)
    return any(
        PlanItem.Status.DONE in statuses
        and all(s in (PlanItem.Status.DONE, PlanItem.Status.SKIPPED) for s in statuses)
        for statuses in weeks.values()
    )


def badges(profile, progress=None, streak=None):
    """The milestone badges, earned or not, in the order a learner usually gets them."""
    progress = progress if progress is not None else summary(profile)
    streak = streak if streak is not None else weekly_streak(profile)
    done = progress["done"] if progress else 0
    finished = bool(progress) and progress["total"] > 0 and progress["percent"] == 100
    return [
        {"key": "first-lesson", "title": "First step", "text": "Finish your first lesson.",
         "mascot": "star-pink", "earned": done >= 1},
        {"key": "first-quiz", "title": "Quiz passed", "text": "Pass your first quiz.",
         "mascot": "oval-teal", "earned": bool(progress) and progress["checks_passed"] >= 1},
        {"key": "module", "title": "Module done", "text": "Finish every lesson in one module.",
         "mascot": "flower-orange", "earned": _module_done(profile)},
        {"key": "halfway", "title": "Halfway there", "text": "Get half of your plan done.",
         "mascot": "flower-teal", "earned": bool(progress) and progress["total"] > 0 and progress["percent"] >= 50},
        {"key": "streak", "title": f"{STREAK_BADGE_WEEKS} weeks in a row",
         "text": f"Learn something {STREAK_BADGE_WEEKS} weeks in a row.",
         "mascot": "star-yellow", "earned": streak.best >= STREAK_BADGE_WEEKS},
        {"key": "finished", "title": "Plan finished", "text": "Finish your whole plan.",
         "mascot": "flower-yellow", "earned": finished},
    ]


def finished_on(profile):
    """The day the learner finished the last lesson of their plan, or today if we can't tell."""
    if profile.gets_ai_plans() and (outline := ai_plan.active_outline(profile)) is not None:
        last = outline.progress.aggregate(last=Max("completed_at"))["last"]
    else:
        plan = active_plan(profile)
        last = plan.items.aggregate(last=Max("completed_at"))["last"] if plan else None
    return timezone.localdate(last) if last else timezone.localdate()
