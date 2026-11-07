"""Reminder emails for learners who have gone quiet.

A reminder goes out after REMIND_AFTER_DAYS with no activity and repeats at that gap,
but stops after MAX_UNANSWERED until the learner comes back. Run by `send_reminders`.
"""

from dataclasses import dataclass

from django.conf import settings
from django.core.mail import EmailMessage
from django.db.models import Max
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from accounts.models import LearnerProfile

from . import journey
from .models import PracticeSubmission, QuizAttempt
from .planner import active_plan

REMIND_AFTER_DAYS = 7
MAX_UNANSWERED = 3


@dataclass
class Reminder:
    profile: LearnerProfile
    action: journey.NextAction
    unanswered: int


def candidates():
    return (
        LearnerProfile.objects.filter(email_reminders=True, onboarded=True, user__is_active=True)
        .exclude(user__email="").select_related("user")
    )


def last_activity(profile, plan):
    """The latest sign of the learner: plan start, login, finished topic, quiz or practice."""
    times = [
        plan.created_at,
        profile.user.last_login,
        plan.items.aggregate(last=Max("completed_at"))["last"],
        QuizAttempt.objects.filter(learner=profile).aggregate(last=Max("created_at"))["last"],
        PracticeSubmission.objects.filter(learner=profile).aggregate(last=Max("created_at"))["last"],
    ]
    return max(t for t in times if t)


def reminder_for(profile, now=None):
    """The reminder this learner is due, or None."""
    now = now or timezone.now()
    plan = active_plan(profile)
    if plan is None:
        return None
    activity = last_activity(profile, plan)
    sent = profile.last_reminder_at
    came_back = sent is None or activity > sent
    unanswered = 0 if came_back else profile.reminders_unanswered
    if unanswered >= MAX_UNANSWERED:
        return None
    quiet_since = activity if came_back else sent
    if now - quiet_since < timezone.timedelta(days=REMIND_AFTER_DAYS):
        return None
    items = list(plan.items.select_related("topic").order_by("order"))
    action = journey.next_action(profile, plan, items, journey.due_reviews(profile, plan))
    if action is None or action.kind == "project":
        return None  # Nothing left that a nudge helps with.
    return Reminder(profile, action, unanswered)


def build_email(reminder):
    profile = reminder.profile
    unsubscribe_url = settings.SITE_URL + reverse("unsubscribe", args=[profile.unsubscribe_key])
    body = render_to_string("email/reminder.txt", {
        "name": profile.user.first_name or "there",
        "action": reminder.action,
        "plan_url": settings.SITE_URL + reverse("plan"),
        "settings_url": settings.SITE_URL + reverse("account_settings"),
        "unsubscribe_url": unsubscribe_url,
    })
    return EmailMessage(
        subject=f"Your next step: {reminder.action.title}",
        body=body,
        to=[profile.user.email],
        headers={
            "List-Unsubscribe": f"<{unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    )


def send(reminder, now=None):
    """Send, then record it. A failed send raises and records nothing, so the next run retries."""
    build_email(reminder).send()
    profile = reminder.profile
    profile.last_reminder_at = now or timezone.now()
    profile.reminders_unanswered = reminder.unanswered + 1
    profile.save(update_fields=["last_reminder_at", "reminders_unanswered"])
