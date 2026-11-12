"""Streaks, badges, the finish certificate, the target date and the quiz result's answers."""

from datetime import date, datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from content.models import PracticeTask, QuizItem, Topic

from .models import PlanItem, QuizAttempt
from .planner import build_plan
from .rewards import badges, weekly_streak
from .tests import PlanTestMixin

# A Wednesday, so "this week" started on Monday 9 November 2026.
TODAY = date(2026, 11, 11)


def at(day):
    return timezone.make_aware(datetime.combine(day, datetime.min.time().replace(hour=12)))


class StreakTests(PlanTestMixin, TestCase):
    def setUp(self):
        self.make_learner()
        self.plan = build_plan(self.profile)
        self.item = QuizItem.objects.create(topic=self.topics[0], prompt="___", accepted_answers=["x"])

    def learn_on(self, *days):
        for day in days:
            attempt = QuizAttempt.objects.create(learner=self.profile, quiz_item=self.item, answer="x", is_correct=True)
            QuizAttempt.objects.filter(pk=attempt.pk).update(created_at=at(day))

    def test_no_learning_no_streak(self):
        streak = weekly_streak(self.profile, today=TODAY)
        self.assertEqual((streak.weeks, streak.this_week, streak.best), (0, False, 0))

    def test_counts_weeks_in_a_row_up_to_this_week(self):
        self.learn_on(TODAY, TODAY - timedelta(weeks=1), TODAY - timedelta(weeks=2) + timedelta(days=2))
        streak = weekly_streak(self.profile, today=TODAY)
        self.assertEqual((streak.weeks, streak.this_week, streak.at_risk), (3, True, False))

    def test_streak_survives_until_the_week_ends(self):
        # Nothing yet this week, but last week and the one before: still a 2-week streak, at risk.
        self.learn_on(TODAY - timedelta(weeks=1), TODAY - timedelta(weeks=2))
        streak = weekly_streak(self.profile, today=TODAY)
        self.assertEqual((streak.weeks, streak.at_risk), (2, True))

    def test_a_missed_week_breaks_it_but_best_remembers(self):
        self.learn_on(TODAY, TODAY - timedelta(weeks=2), TODAY - timedelta(weeks=3), TODAY - timedelta(weeks=4))
        streak = weekly_streak(self.profile, today=TODAY)
        self.assertEqual((streak.weeks, streak.best), (1, 3))

    def test_finished_topics_count_as_learning(self):
        self.plan.items.filter(topic=self.topics[0]).update(status="done", completed_at=at(TODAY))
        self.assertEqual(weekly_streak(self.profile, today=TODAY).weeks, 1)

    def test_plan_page_shows_the_streak(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("plan")), "Start a streak")
        self.learn_on(timezone.localdate())
        self.assertContains(self.client.get(reverse("plan")), "1-week streak!")


class BadgeTests(PlanTestMixin, TestCase):
    def setUp(self):
        self.make_learner(hours=2)  # Two one-hour topics a week: weeks 1 and 2.
        self.plan = build_plan(self.profile)

    def earned(self):
        return {b["key"] for b in badges(self.profile) if b["earned"]}

    def finish(self, *numbers, quiz=False):
        for n in numbers:
            topic = self.topics[n - 1]
            PlanItem.objects.filter(plan=self.plan, topic=topic).update(status="done", completed_at=timezone.now())
            if quiz:
                item = QuizItem.objects.create(topic=topic, prompt="___", accepted_answers=["x"])
                self.client.force_login(self.user)
                self.client.post(reverse("quiz", args=[topic.slug]), {f"item_{item.pk}": "x"})

    def test_none_at_the_start(self):
        self.assertEqual(self.earned(), set())

    def test_first_lesson_and_quiz(self):
        self.finish(1, quiz=True)
        self.assertEqual(self.earned(), {"first-lesson", "first-quiz"})

    def test_a_whole_week_is_a_module_and_half_the_plan(self):
        self.finish(1, 2)
        self.assertEqual(self.earned(), {"first-lesson", "module", "halfway"})

    def test_finishing_the_plan(self):
        self.finish(1, 2, 3, 4)
        self.assertIn("finished", self.earned())

    def test_profile_shows_badges(self):
        self.finish(1)
        self.client.force_login(self.user)
        page = self.client.get(reverse("profile"))
        self.assertContains(page, "First step")
        self.assertContains(page, "Not earned yet.", count=5)


class CertificateTests(PlanTestMixin, TestCase):
    def test_finish_page_has_a_certificate_with_name_and_plan(self):
        self.make_learner()
        self.user.first_name, self.user.last_name = "Ana", "Reyes"
        self.user.save()
        plan = build_plan(self.profile)
        plan.items.update(status="done", completed_at=timezone.make_aware(datetime(2026, 11, 3, 9)))
        self.client.force_login(self.user)
        page = self.client.get(reverse("plan_finish"))
        self.assertContains(page, "Certificate of completion")
        self.assertContains(page, "Ana Reyes")
        self.assertContains(page, "Python basics")
        self.assertContains(page, "November 3, 2026")
        self.assertContains(page, "data-print")


class TargetDateTests(PlanTestMixin, TestCase):
    def setUp(self):
        self.make_learner()
        self.plan = build_plan(self.profile)
        self.client.force_login(self.user)
        self.start = timezone.localdate(self.plan.created_at)

    def save(self, day):
        return self.client.post(reverse("profile_setup"), {
            "hours_per_week": 2, "target_date": day, "goal_text": "", "experience": "", "device": "", "hint_style": "",
        })

    def test_date_becomes_weeks_from_the_plan_start(self):
        self.save((self.start + timedelta(days=20)).isoformat())
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.target_weeks, 3)
        self.assertContains(self.client.get(reverse("profile")), "Aiming to finish by:")

    def test_blank_clears_the_date(self):
        self.profile.target_weeks = 4
        self.profile.save()
        page = self.client.get(reverse("profile"))
        self.assertContains(page, (self.start + timedelta(weeks=4)).isoformat())
        self.save("")
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.target_weeks)

    def test_past_dates_are_refused(self):
        response = self.save((timezone.localdate() - timedelta(days=1)).isoformat())
        self.assertContains(response, "Pick a date after today.", status_code=400)


class QuizAnswerRevealTests(PlanTestMixin, TestCase):
    def setUp(self):
        self.make_learner()
        self.client.force_login(self.user)
        build_plan(self.profile)
        self.topic = self.topics[0]
        self.a = QuizItem.objects.create(topic=self.topic, prompt="for i in ___(5):", accepted_answers=["range"],
                                         hint="A built-in.", explanation="range(5) counts 0 to 4.")
        self.b = QuizItem.objects.create(topic=self.topic, prompt="___ x == 0:", accepted_answers=["elif"])
        self.c = QuizItem.objects.create(topic=self.topic, prompt="x ___ 1", accepted_answers=["="])

    def submit(self, a):
        self.client.post(reverse("quiz", args=[self.topic.slug]),
                         {f"item_{self.a.pk}": a, f"item_{self.b.pk}": "elif", f"item_{self.c.pk}": "x"})
        return self.client.get(reverse("quiz_result", args=[self.topic.slug]))

    def test_first_miss_keeps_the_answer_hidden(self):
        page = self.submit("list")
        self.assertContains(page, "2 to fix")
        self.assertContains(page, "Hint: A built-in.")
        self.assertNotContains(page, "for i in range(5):")

    def test_second_miss_shows_the_answer_and_why(self):
        self.submit("list")
        page = self.submit("list")
        self.assertContains(page, "The right answer")
        self.assertContains(page, "for i in range(5):")
        self.assertContains(page, "range(5) counts 0 to 4.")


class ReviewQueueTests(TestCase):
    def setUp(self):
        from content.models import Track

        track = Track.objects.create(name="Python", slug="python")
        self.topic = Topic.objects.create(track=track, title="Loops", slug="loops", order=1,
                                          explanation="Loops repeat things.")
        self.task = PracticeTask.objects.create(topic=self.topic, prompt="Print 1 to 3.", sample_answer="print(1)",
                                                checklist=["Prints numbers"])
        self.staff = get_user_model().objects.create_user("curator", is_staff=True, is_superuser=True)
        self.client.force_login(self.staff)

    def test_queue_lists_drafts_and_approves_them(self):
        page = self.client.get(reverse("review_queue"))
        self.assertContains(page, "Loops repeat things.")
        self.assertContains(page, "Print 1 to 3.")
        self.client.post(reverse("review_approve", args=["intro", self.topic.pk]))
        self.client.post(reverse("review_approve", args=["task", self.task.pk]))
        self.topic.refresh_from_db()
        self.task.refresh_from_db()
        self.assertTrue(self.topic.intro_approved)
        self.assertTrue(self.task.approved)
        self.assertContains(self.client.get(reverse("review_queue")), "No intros waiting.")

    def test_admin_home_counts_what_waits(self):
        self.assertContains(self.client.get(reverse("admin:index")), "2 AI drafts")

    def test_learners_cannot_approve(self):
        learner = get_user_model().objects.create_user("ana")
        self.client.force_login(learner)
        self.client.post(reverse("review_approve", args=["intro", self.topic.pk]))
        self.topic.refresh_from_db()
        self.assertFalse(self.topic.intro_approved)
