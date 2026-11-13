"""The coding panel on Practice and lesson examples, and the practice tasks migration (content 0012)."""

import importlib

from django.apps import apps
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from content.models import PracticeTask, Topic, Track

from .code_panel import can_run, panel_language
from .planner import build_plan
from .tests import PlanTestMixin

practice_tasks = importlib.import_module("content.migrations.0012_practice_tasks")


class PanelLanguageTests(SimpleTestCase):
    def test_tracks_map_to_runners(self):
        self.assertEqual(panel_language("python"), "python")
        self.assertEqual(panel_language("sql"), "sql")
        self.assertEqual(panel_language("css"), "html")
        self.assertEqual(panel_language("java"), "java")
        self.assertEqual(panel_language("ruby"), "")

    def test_javascript_that_is_a_page_runs_as_html(self):
        self.assertEqual(panel_language("javascript", "console.log(1)"), "javascript")
        self.assertEqual(panel_language("javascript", "  <button>Hi</button><script></script>"), "html")

    def test_java_cant_run_in_the_browser(self):
        self.assertFalse(can_run("java"))
        self.assertTrue(can_run("css"))
        self.assertTrue(can_run("python"))


class PracticePanelTests(PlanTestMixin, TestCase):
    def setUp(self):
        self.make_learner()
        self.client.force_login(self.user)
        build_plan(self.profile)
        self.topic = self.topics[0]
        PracticeTask.objects.create(
            topic=self.topic, prompt="Print 1 to 3.", starter_code="for i in range(3):\n    pass",
            sample_answer="for i in range(1, 4):\n    print(i)", checklist=["Prints 3 lines"], approved=True,
        )

    def test_practice_has_an_editor_with_the_starter_code(self):
        page = self.client.get(reverse("practice", args=[self.topic.slug]))
        self.assertContains(page, 'data-code-panel data-language="python"')
        self.assertContains(page, "for i in range(3):")
        self.assertContains(page, 'name="answer"')
        self.assertContains(page, "data-code-run")
        self.assertContains(page, "js/code_panel.js")
        self.assertContains(page, "js/python_worker.js")

    def test_the_editor_still_sends_the_answer(self):
        self.client.post(reverse("practice", args=[self.topic.slug]), {"answer": "print(1)"})
        page = self.client.get(reverse("practice", args=[self.topic.slug]))
        self.assertContains(page, "print(1)")

    def test_java_practice_has_no_run_button(self):
        java = Track.objects.create(name="Java", slug="java")
        topic = Topic.objects.create(track=java, title="Loops", slug="java-loops", order=1)
        PracticeTask.objects.create(topic=topic, prompt="Loop.", sample_answer="x", checklist=["y"], approved=True)
        page = self.client.get(reverse("practice", args=["java-loops"]))
        self.assertContains(page, 'data-language="java"')
        self.assertNotContains(page, "data-code-run")
        self.assertContains(page, "run it in VS Code")

    def test_lesson_examples_offer_try_this_code(self):
        self.topic.intro_approved = True
        self.topic.why_it_matters = "Why."
        self.topic.explanation = "How."
        self.topic.example = 'print("hi")'
        self.topic.save()
        page = self.client.get(reverse("lesson", args=[self.topic.slug]))
        self.assertContains(page, "Try this code")
        self.assertContains(page, 'data-language="python"')


class PracticeTasksMigrationTests(TestCase):
    def test_adds_approved_tasks_and_keeps_existing_ones(self):
        track = Track.objects.create(name="SQL", slug="sql")
        select = Topic.objects.create(track=track, title="Reading data with SELECT", slug="sql-reading-data-with-select", order=1)
        where = Topic.objects.create(track=track, title="Filtering with WHERE", slug="sql-filtering-with-where", order=2)
        PracticeTask.objects.create(topic=where, prompt="Mine", sample_answer="x", checklist=["y"], approved=True)
        practice_tasks.load(apps, None)
        practice_tasks.load(apps, None)
        self.assertEqual(select.practice_tasks.get().approved, True)
        self.assertIn("title and author", select.practice_tasks.get().prompt)
        self.assertEqual(list(where.practice_tasks.values_list("prompt", flat=True)), ["Mine"])
        for task in PracticeTask.objects.all():
            task.full_clean()
