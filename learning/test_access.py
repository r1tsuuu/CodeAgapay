"""No learner can read or change another learner's data, and progress survives plan changes."""

import tempfile
import uuid
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import get_profile
from assistant import service
from content.models import Track
from content.test_curriculum import tiny, write
from diagnose.models import TopicMastery

from .models import PlanFeedback, PlanItem
from .planner import active_plan, build_plan, repace_plan, set_item_status


class TwoLearners(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        write(tiny(), directory.name)
        call_command("import_curriculum", dir=directory.name, stdout=StringIO())
        track = Track.objects.get(slug="python")
        self.ana, self.ben = (self.learner(name, track) for name in ("ana", "ben"))
        self.ana_plan, self.ben_plan = build_plan(self.ana), build_plan(self.ben)
        self.ana_item = self.ana_plan.items.first()
        self.client.force_login(self.ben.user)

    def learner(self, name, track):
        profile = get_profile(get_user_model().objects.create_user(name, f"{name}@example.com"))
        profile.track, profile.hours_per_week, profile.onboarded = track, 3, True
        profile.save()
        return profile


class CrossUserTests(TwoLearners):
    def test_cannot_change_another_learners_plan_item(self):
        response = self.client.post(reverse("plan_item_status", args=[self.ana_item.pk]), {"status": "done"})
        self.assertEqual(response.status_code, 404)
        self.ana_item.refresh_from_db()
        self.assertEqual(self.ana_item.status, PlanItem.Status.TODO)
        self.assertFalse(TopicMastery.objects.filter(learner=self.ana).exists())

    def test_cannot_move_on_from_another_learners_item(self):
        response = self.client.post(reverse("plan_item_shaky", args=[self.ana_item.pk]))
        self.assertEqual(response.status_code, 404)
        self.ana_item.refresh_from_db()
        self.assertFalse(self.ana_item.shaky)

    def test_cannot_defer_another_learners_item(self):
        response = self.client.post(reverse("plan_item_defer", args=[self.ana_item.pk]))
        self.assertEqual(response.status_code, 404)

    def test_plan_page_shows_only_my_plan(self):
        response = self.client.get(reverse("plan"))
        self.assertEqual(response.context["plan"], self.ben_plan)

    def test_report_goes_on_my_own_plan(self):
        self.client.post(reverse("plan_report"), {"text": "A link is broken"})
        self.assertEqual(PlanFeedback.objects.get().plan, self.ben_plan)

    def test_pace_change_touches_only_my_plan(self):
        before = list(self.ana_plan.items.values_list("week", flat=True))
        self.client.post(reverse("plan_pace"), {"hours": "1"})
        self.assertEqual(list(self.ana_plan.items.values_list("week", flat=True)), before)

    def test_unknown_unsubscribe_key_is_404(self):
        self.client.logout()
        self.assertEqual(self.client.post(reverse("unsubscribe", args=[uuid.uuid4()])).status_code, 404)

    def test_ai_lesson_keys_resolve_only_in_my_own_plan(self):
        # Ben has no AI plan; a key from someone else's plan must not open anything.
        with override_settings(AI_PLANS=True):
            self.assertEqual(self.client.get(reverse("ai_lesson", args=["L1"])).status_code, 404)

    def test_help_for_a_lesson_key_never_reads_another_plan(self):
        with mock.patch("learning.ai_plan.active_outline", return_value=None) as outline:
            data = self.client.post(reverse("help_ask"), {"lesson": "L1", "question": "?"},
                                    content_type="application/json").json()
        outline.assert_called_once_with(self.ben)
        self.assertEqual(data["mode"], "fallback")

    def test_ai_usage_is_counted_per_learner(self):
        with override_settings(AI_DAILY_LIMIT=1):
            self.assertTrue(service.reserve_message(self.ben))
            self.assertFalse(service.reserve_message(self.ben))
            self.assertTrue(service.reserve_message(self.ana))


class ProgressPersistenceTests(TwoLearners):
    def test_done_items_survive_a_pace_change(self):
        set_item_status(self.ana_item, PlanItem.Status.DONE)
        repace_plan(self.ana_plan, 1)
        self.ana_item.refresh_from_db()
        self.assertEqual(self.ana_item.status, PlanItem.Status.DONE)

    def test_a_rebuilt_plan_skips_topics_already_done(self):
        set_item_status(self.ana_item, PlanItem.Status.DONE)
        rebuilt = build_plan(self.ana)
        self.assertNotIn(self.ana_item.topic, [i.topic for i in rebuilt.items.all()])
        self.assertEqual(active_plan(self.ana), rebuilt)
        self.ana_plan.refresh_from_db()
        self.assertFalse(self.ana_plan.is_active)
        self.assertTrue(self.ana_plan.items.filter(status=PlanItem.Status.DONE).exists())

    def test_progress_comes_from_statuses(self):
        self.assertEqual(self.ana_plan.progress_percent(), 0)
        set_item_status(self.ana_item, PlanItem.Status.DONE)
        self.assertEqual(self.ana_plan.progress_percent(), 50)


class FlexibilityTests(TwoLearners):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.ana.user)
        self.vars_item, self.loops_item = self.ana_plan.items.order_by("order")

    def test_later_is_refused_when_a_later_topic_needs_it(self):
        self.client.post(reverse("plan_item_defer", args=[self.vars_item.pk]))
        self.vars_item.refresh_from_db()
        self.assertEqual(self.vars_item.order, 1)

    def test_later_moves_a_topic_to_the_end_and_respreads_weeks(self):
        self.loops_item.topic.prerequisites.clear()
        self.client.post(reverse("plan_item_defer", args=[self.vars_item.pk]))
        order = list(self.ana_plan.items.order_by("order").values_list("topic__slug", flat=True))
        self.assertEqual(order, ["py-loops", "py-vars"])

    def test_done_items_cannot_be_deferred(self):
        set_item_status(self.loops_item, PlanItem.Status.DONE)
        self.assertEqual(self.client.post(reverse("plan_item_defer", args=[self.loops_item.pk])).status_code, 404)

    def test_pause_stops_reminders_and_keeps_the_streak_safe(self):
        from learning import reminders, rewards

        self.ana.email_reminders = True
        self.ana.save()
        self.assertIn(self.ana, reminders.candidates())
        self.client.post(reverse("plan_pause"), {"action": "pause"})
        self.ana.refresh_from_db()
        self.assertIsNotNone(self.ana.paused_at)
        self.assertNotIn(self.ana, reminders.candidates())
        self.assertFalse(rewards.weekly_streak(self.ana).at_risk)
        self.assertContains(self.client.get(reverse("plan")), "Your plan is paused")
        self.client.post(reverse("plan_pause"), {"action": "resume"})
        self.ana.refresh_from_db()
        self.assertIsNone(self.ana.paused_at)

    def test_a_paused_week_does_not_break_the_streak(self):
        from datetime import timedelta

        from django.utils import timezone

        from learning import rewards
        from learning.models import QuizAttempt

        today = timezone.localdate()
        two_weeks_ago = timezone.now() - timedelta(weeks=2)
        attempt = QuizAttempt.objects.create(
            learner=self.ana, quiz_item=self.vars_item.topic.quiz_items.first(), answer="=", is_correct=True)
        QuizAttempt.objects.filter(pk=attempt.pk).update(created_at=two_weeks_ago)
        self.assertEqual(rewards.weekly_streak(self.ana, today).weeks, 0)
        self.ana.paused_at = two_weeks_ago + timedelta(days=1)
        self.ana.save()
        self.assertEqual(rewards.weekly_streak(self.ana, today).weeks, 1)
