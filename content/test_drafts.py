import json
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import CommandError, call_command
from django.test import TestCase

from .models import ProjectIdea, QuizItem, Resource, SetupStep, Topic, Track

DRAFTS = Path(settings.BASE_DIR) / "content" / "drafts"


def load(name, *args):
    out = StringIO()
    call_command("load_drafts", str(DRAFTS / name), *args, stdout=out, stderr=StringIO())
    return out.getvalue()


class TrackDraftTests(TestCase):
    def setUp(self):
        self.html = Track.objects.create(name="HTML", slug="html", is_active=False)
        self.css = Track.objects.create(name="CSS", slug="css", is_active=False)

    def test_html_and_css_files_load_and_pass_validation(self):
        for name, track in (("html.json", self.html), ("css.json", self.css)):
            load(name)
            topics = list(track.topics.order_by("order"))
            self.assertEqual(len(topics), 5)
            self.assertTrue(track.setup_steps.exists())
            self.assertTrue(track.project_ideas.exists())
            for topic in topics:
                self.assertEqual(topic.quiz_items.count(), 4, topic)
                self.assertEqual(topic.skill_questions.count(), 2, topic)
                self.assertEqual(topic.tips.count(), 2, topic)
                self.assertEqual(topic.resources.count(), 2, topic)
                self.assertFalse(topic.intro_approved)

    def test_each_topic_needs_the_one_before(self):
        load("html.json")
        topics = list(self.html.topics.order_by("order"))
        self.assertEqual(topics[0].prerequisites.count(), 0)
        for before, after in zip(topics, topics[1:]):
            self.assertEqual(list(after.prerequisites.all()), [before])

    def test_correct_answers_are_not_always_in_one_position(self):
        for name in ("html.json", "css.json"):
            data = json.loads((DRAFTS / name).read_text(encoding="utf-8"))
            positions = {q["correct_index"] for t in data["topics"] for q in t["skill_questions"]}
            self.assertEqual(positions, {0, 1, 2, 3})

    def test_loading_twice_adds_nothing(self):
        load("html.json")
        counts = [m.objects.count() for m in (Topic, Resource, SetupStep, ProjectIdea, QuizItem)]
        load("html.json")
        self.assertEqual(counts, [m.objects.count() for m in (Topic, Resource, SetupStep, ProjectIdea, QuizItem)])

    def test_keeps_a_curators_existing_setup_steps(self):
        SetupStep.objects.create(track=self.html, order=1, title="Curated", body="b")
        load("html.json")
        self.assertEqual(list(self.html.setup_steps.values_list("title", flat=True)), ["Curated"])

    def test_continues_after_a_curators_existing_topic(self):
        existing = Topic.objects.create(track=self.html, title="Page structure", slug="curated", order=1)
        load("html.json")
        self.assertEqual(self.html.topics.count(), 5)
        self.assertEqual(self.html.topics.get(title="Text and headings").prerequisites.get(), existing)

    def test_refuses_a_live_track_and_saves_nothing(self):
        self.html.is_active = True
        self.html.save()
        with self.assertRaisesMessage(CommandError, "is live"):
            load("html.json")
        self.assertEqual(Topic.objects.count(), 0)

    def test_stops_on_a_missing_track(self):
        self.html.delete()
        with self.assertRaisesMessage(CommandError, "No track"):
            load("html.json")


class PythonQuizDraftTests(TestCase):
    def setUp(self):
        self.track = Track.objects.create(name="Python", slug="python")
        data = json.loads((DRAFTS / "python_quiz.json").read_text(encoding="utf-8"))
        self.slugs = [item["topic"] for item in data["quiz_items"]]
        for order, slug in enumerate(self.slugs, 1):
            Topic.objects.create(track=self.track, title=slug, slug=slug, order=order)

    def test_python_is_live_so_it_needs_the_flag(self):
        with self.assertRaisesMessage(CommandError, "is live"):
            load("python_quiz.json")
        self.assertEqual(QuizItem.objects.count(), 0)

    def test_adds_one_question_per_topic_only_once(self):
        load("python_quiz.json", "--allow-active-track")
        load("python_quiz.json", "--allow-active-track")
        for topic in self.track.topics.all():
            self.assertEqual(topic.quiz_items.count(), 1)

    def test_skips_a_topic_that_was_renamed(self):
        Topic.objects.filter(slug=self.slugs[0]).update(slug="renamed")
        load("python_quiz.json", "--allow-active-track")
        self.assertEqual(QuizItem.objects.count(), len(self.slugs) - 1)
