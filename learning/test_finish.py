from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import get_profile
from content.models import Path, PathTrack, QuizItem, Topic, Track
from diagnose.models import TopicMastery
from diagnose.scoring import record_mastery

from .forms import QuizForm
from .journey import is_finished
from .models import PlanItem, PlanProject
from .planner import build_plan, move_on_shaky, set_item_status

Status = PlanItem.Status


class FinishMixin:
    def setUp(self):
        self.track = Track.objects.create(name="Python", slug="python")
        self.topics = [
            Topic.objects.create(track=self.track, title=f"Topic {i}", slug=f"topic-{i}", order=i)
            for i in (1, 2)
        ]
        self.user = get_user_model().objects.create_user("ana", "ana@example.com")
        self.profile = get_profile(self.user)
        self.profile.track = self.track
        self.profile.onboarded = True
        self.profile.hours_per_week = 3
        self.profile.save()
        self.plan = build_plan(self.profile)
        self.client.force_login(self.user)

    def finish_all(self):
        for item in self.plan.items.all():
            set_item_status(item, Status.DONE)

    def path_with(self, *tracks):
        path = Path.objects.create(title="Data", slug="data", tagline="t")
        for order, track in enumerate(tracks, 1):
            PathTrack.objects.create(path=path, track=track, order=order)
        self.profile.path = path
        self.profile.save()


class IsFinishedTests(FinishMixin, TestCase):
    def items(self):
        return list(self.plan.items.all())

    def test_not_finished_with_topics_left(self):
        set_item_status(self.items()[0], Status.DONE)
        self.assertFalse(is_finished(self.items()))

    def test_finished_when_the_rest_are_skipped(self):
        first, second = self.items()
        set_item_status(first, Status.DONE)
        set_item_status(second, Status.SKIPPED)
        self.assertTrue(is_finished(self.items()))

    def test_skipping_everything_is_not_finishing(self):
        for item in self.items():
            set_item_status(item, Status.SKIPPED)
        self.assertFalse(is_finished(self.items()))

    def test_an_empty_plan_is_not_finished(self):
        self.assertFalse(is_finished([]))


class FinishPageTests(FinishMixin, TestCase):
    def test_unfinished_plan_goes_back_to_the_plan(self):
        self.assertRedirects(self.client.get(reverse("plan_finish")), reverse("plan"))

    def test_no_plan_goes_to_the_result_page(self):
        self.plan.delete()
        response = self.client.get(reverse("plan_finish"))
        self.assertRedirects(response, reverse("result"), fetch_redirect_response=False)

    def test_shows_what_was_done(self):
        self.finish_all()
        response = self.client.get(reverse("plan_finish"))
        self.assertContains(response, "Congratulations, ")
        self.assertContains(response, "<strong class=\"finish-stat-berry\">2</strong> topics finished", html=False)
        self.assertContains(response, "Topic 1")

    def test_counts_quiz_passes_apart_from_topics_marked_done(self):
        record_mastery(
            self.profile, self.topics[0], TopicMastery.Status.DEMONSTRATED, "Quiz", TopicMastery.Source.QUIZ, force=True
        )
        self.finish_all()
        self.assertContains(self.client.get(reverse("plan_finish")), "<strong class=\"finish-stat-teal\">1</strong> quiz passed")

    def test_no_quiz_claim_when_every_topic_was_marked_by_hand(self):
        self.finish_all()
        self.assertContains(self.client.get(reverse("plan_finish")), "<strong class=\"finish-stat-teal\">0</strong> quizzes passed")

    def test_lists_skipped_topics_but_not_shaky_ones(self):
        first, second = self.plan.items.all()
        set_item_status(first, Status.DONE)
        set_item_status(second, Status.SKIPPED)
        self.assertContains(self.client.get(reverse("plan_finish")), "You skipped")
        move_on_shaky(second)
        self.assertNotContains(self.client.get(reverse("plan_finish")), "You skipped")

    def test_skipping_everything_opens_the_page_without_a_certificate(self):
        for item in self.plan.items.all():
            set_item_status(item, Status.SKIPPED)
        response = self.client.get(reverse("plan_finish"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "no certificate yet")

    def test_shows_the_project_checks(self):
        PlanProject.objects.create(plan=self.plan, title="Quiz game", description="d", done_when=["It runs."])
        self.finish_all()
        response = self.client.get(reverse("plan_finish"))
        self.assertContains(response, "Quiz game")
        self.assertContains(response, "It runs.")

    def test_coming_soon_and_newly_live_tracks(self):
        soon = Track.objects.create(name="SQL", slug="sql", is_active=False)
        self.path_with(self.track, soon)
        self.finish_all()
        response = self.client.get(reverse("plan_finish"))
        self.assertContains(response, "Coming soon on your path")
        self.assertNotContains(response, "Start SQL")

        Topic.objects.create(track=soon, title="Select", slug="select", order=1)
        soon.is_active = True
        soon.save()
        response = self.client.get(reverse("plan_finish"))
        self.assertContains(response, "Try SQL")
        self.assertNotContains(response, "Coming soon on your path")

    def test_adding_a_new_track_keeps_finished_topics_finished(self):
        new = Track.objects.create(name="SQL", slug="sql")
        Topic.objects.create(track=new, title="Select", slug="select", order=1)
        self.path_with(self.track, new)
        self.finish_all()
        self.client.post(reverse("plan_build"))
        plan = self.profile.plans.get(is_active=True)
        self.assertEqual(list(plan.items.values_list("topic__slug", flat=True)), ["select"])


class FinishLinksTests(FinishMixin, TestCase):
    def pass_quiz(self, topic):
        item = QuizItem.objects.create(topic=topic, prompt="___", accepted_answers=["yes"])
        field = QuizForm(items=[item]).fields
        return self.client.post(reverse("quiz", args=[topic.slug]), {next(iter(field)): "yes"}, follow=True)

    def test_plan_page_leads_to_the_finish_page(self):
        self.finish_all()
        response = self.client.get(reverse("plan"))
        self.assertContains(response, "You finished every topic!")
        self.assertContains(response, reverse("plan_finish"))

    def test_plan_page_has_no_finish_link_before_the_end(self):
        self.assertNotContains(self.client.get(reverse("plan")), reverse("plan_finish"))

    def test_passing_the_last_quiz_leads_to_the_finish_page(self):
        set_item_status(self.plan.items.get(topic=self.topics[0]), Status.DONE)
        response = self.pass_quiz(self.topics[1])
        self.assertContains(response, "You passed!")
        self.assertContains(response, reverse("plan_finish"))

    def test_passing_an_earlier_quiz_does_not(self):
        response = self.pass_quiz(self.topics[0])
        self.assertContains(response, "You passed!")
        self.assertNotContains(response, reverse("plan_finish"))
