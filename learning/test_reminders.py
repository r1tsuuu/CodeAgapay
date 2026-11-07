from datetime import timedelta
from io import StringIO
from smtplib import SMTPException
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import get_profile
from content.models import QuizItem, Topic, Track

from . import reminders
from .models import LearningPlan, PlanItem, PlanProject, QuizAttempt
from .planner import build_plan, set_item_status

email_on = override_settings(EMAIL_HOST="smtp.test", SITE_URL="https://example.test")


def days_ago(days):
    return timezone.now() - timedelta(days=days)


class ReminderMixin:
    def setUp(self):
        self.track = Track.objects.create(name="Python", slug="python")
        self.topic = Topic.objects.create(track=self.track, title="Loops & lists", slug="loops", order=1)
        self.user = get_user_model().objects.create_user("ana", "ana@example.com", first_name="Ana")
        self.profile = get_profile(self.user)
        self.profile.track = self.track
        self.profile.onboarded = True
        self.profile.email_reminders = True
        self.profile.save()
        self.plan = build_plan(self.profile)
        self.go_quiet(10)

    def go_quiet(self, days):
        LearningPlan.objects.filter(pk=self.plan.pk).update(created_at=days_ago(days))

    def run_command(self, *args):
        out = StringIO()
        call_command("send_reminders", *args, stdout=out, stderr=StringIO())
        self.profile.refresh_from_db()
        return out.getvalue()


@email_on
class WhoGetsAReminderTests(ReminderMixin, TestCase):
    def test_quiet_learner_gets_one(self):
        self.run_command()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(self.profile.reminders_unanswered, 1)
        self.assertIsNotNone(self.profile.last_reminder_at)

    def test_recent_plan_gets_none(self):
        self.go_quiet(3)
        self.run_command()
        self.assertEqual(mail.outbox, [])

    def test_recent_quiz_attempt_counts_as_active(self):
        item = QuizItem.objects.create(topic=self.topic, prompt="___", accepted_answers=["a"])
        QuizAttempt.objects.create(learner=self.profile, quiz_item=item, answer="a", is_correct=True)
        self.run_command()
        self.assertEqual(mail.outbox, [])

    def test_recent_login_counts_as_active(self):
        self.user.last_login = days_ago(1)
        self.user.save()
        self.run_command()
        self.assertEqual(mail.outbox, [])

    def test_learner_who_turned_reminders_off_gets_none(self):
        self.profile.email_reminders = False
        self.profile.save()
        self.run_command()
        self.assertEqual(mail.outbox, [])

    def test_learner_without_an_email_gets_none(self):
        self.user.email = ""
        self.user.save()
        self.run_command()
        self.assertEqual(mail.outbox, [])

    def test_deactivated_user_gets_none(self):
        self.user.is_active = False
        self.user.save()
        self.run_command()
        self.assertEqual(mail.outbox, [])

    def test_learner_without_a_plan_gets_none(self):
        self.plan.delete()
        self.run_command()
        self.assertEqual(mail.outbox, [])

    def test_finished_plan_gets_none(self):
        set_item_status(self.plan.items.get(), PlanItem.Status.DONE)
        PlanItem.objects.update(completed_at=days_ago(9))
        self.run_command()
        self.assertEqual(mail.outbox, [])

    def test_finished_plan_with_a_project_gets_none(self):
        PlanProject.objects.create(plan=self.plan, title="Game", description="d")
        set_item_status(self.plan.items.get(), PlanItem.Status.DONE)
        PlanItem.objects.update(completed_at=days_ago(9))
        self.run_command()
        self.assertEqual(mail.outbox, [])


@email_on
class ReminderPacingTests(ReminderMixin, TestCase):
    def sent(self, days, unanswered):
        self.profile.last_reminder_at = days_ago(days)
        self.profile.reminders_unanswered = unanswered
        self.profile.save()

    def test_running_twice_sends_once(self):
        self.run_command()
        self.run_command()
        self.assertEqual(len(mail.outbox), 1)

    def test_waits_a_week_between_reminders(self):
        self.sent(days=3, unanswered=1)
        self.run_command()
        self.assertEqual(mail.outbox, [])

    def test_sends_again_after_a_week(self):
        self.sent(days=8, unanswered=1)
        self.run_command()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(self.profile.reminders_unanswered, 2)

    def test_stops_after_three_unanswered(self):
        self.go_quiet(60)
        self.sent(days=30, unanswered=reminders.MAX_UNANSWERED)
        self.run_command()
        self.assertEqual(mail.outbox, [])

    def test_coming_back_starts_the_count_again(self):
        self.go_quiet(60)
        self.sent(days=30, unanswered=reminders.MAX_UNANSWERED)
        self.user.last_login = days_ago(8)
        self.user.save()
        self.run_command()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(self.profile.reminders_unanswered, 1)


@email_on
class ReminderEmailTests(ReminderMixin, TestCase):
    def test_says_the_next_step_and_links_to_the_site(self):
        self.run_command()
        message = mail.outbox[0]
        self.assertEqual(message.to, ["ana@example.com"])
        self.assertEqual(message.subject, "Your next step: Loops & lists")
        self.assertIn("Hi Ana,", message.body)
        self.assertIn("Loops & lists", message.body)  # Plain text, so no &amp;
        self.assertIn("https://example.test/plan/", message.body)

    def test_unsubscribe_link_is_in_the_body_and_headers(self):
        self.run_command()
        message = mail.outbox[0]
        url = "https://example.test" + reverse("unsubscribe", args=[self.profile.unsubscribe_key])
        self.assertIn(url, message.body)
        self.assertEqual(message.extra_headers["List-Unsubscribe"], f"<{url}>")
        self.assertEqual(message.extra_headers["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")


@email_on
class SendRemindersCommandTests(ReminderMixin, TestCase):
    def test_dry_run_sends_and_saves_nothing(self):
        output = self.run_command("--dry-run")
        self.assertIn("Would send to ana@example.com", output)
        self.assertEqual(mail.outbox, [])
        self.assertIsNone(self.profile.last_reminder_at)

    @override_settings(EMAIL_HOST="")
    def test_refuses_to_run_without_email_settings(self):
        with self.assertRaisesMessage(CommandError, "EMAIL_HOST"):
            self.run_command()
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.last_reminder_at)

    @override_settings(EMAIL_HOST="")
    def test_dry_run_works_without_email_settings(self):
        self.assertIn("Would send", self.run_command("--dry-run"))

    def test_a_failed_send_is_retried_next_time(self):
        with patch("django.core.mail.EmailMessage.send", side_effect=SMTPException("nope")):
            with self.assertRaises(CommandError):
                self.run_command()
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.last_reminder_at)
        self.run_command()
        self.assertEqual(len(mail.outbox), 1)
