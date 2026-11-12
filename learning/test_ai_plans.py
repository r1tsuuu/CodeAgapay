from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import get_profile
from assistant.models import AIUsage
from content.models import SetupStep, Topic
from diagnose.views import _build_plan

from . import ai_plan
from .lessons import parse_lesson
from .models import GeneratedLesson, LearningPlan, LessonProgress, PlanOutline
from .outline import parse_outline
from .test_lessons import SPEC, lesson_reply
from .test_outline import AI_ON, OutlineContentMixin, reply as outline_reply

AI_PLANS = {**AI_ON, "AI_PLANS": True, "AI_LESSON_DAILY_LIMIT": 3}


class AIPlanMixin(OutlineContentMixin):
    def make_plan(self, setup_chosen=True):
        self.make_learner()
        self.outline = PlanOutline.objects.create(
            learner=self.profile, data=parse_outline(outline_reply(), self.profile)[0],
            prompt_version="outline-2", is_active=True, setup_choice="main" if setup_chosen else "",
        )
        if setup_chosen:  # Setup is required first; most tests start after it.
            LessonProgress.objects.create(outline=self.outline, key="S1", status="done")
        self.client.force_login(self.user)

    def write(self, key="L1", **reply):
        data = parse_lesson(lesson_reply(**reply), SPEC)[0]
        return GeneratedLesson.objects.create(outline=self.outline, key=key, title=key, data=data,
                                              prompt_version="lesson-6")

    def lesson_url(self, key="L1", name="ai_lesson"):
        return reverse(name, args=[key])


class GradeCheckTests(TestCase):
    check = parse_lesson(lesson_reply(), SPEC)[0]["check"]  # mc (answer 0), blank ("p"), self

    def test_graded_questions_count_and_self_checks_dont(self):
        score = ai_plan.grade_check(self.check, ["0", "  P ", "anything"])
        self.assertEqual((score["correct"], score["total"], score["passed"], score["band"]), (2, 2, True, "perfect"))
        self.assertIsNone(score["results"][2]["correct"])

    def test_bands_match_the_curated_quiz(self):
        self.assertEqual(ai_plan.grade_check(self.check, ["1", "p", ""])["band"], "almost")  # 1 of 2 = 50%
        self.assertEqual(ai_plan.grade_check(self.check, ["1", "x", ""])["band"], "low")
        self.assertFalse(ai_plan.grade_check(self.check, ["", "", ""])["passed"])


@override_settings(**AI_PLANS)
class OnboardingTests(AIPlanMixin, TestCase):
    def setUp(self):
        self.make_learner()

    def test_paths_without_curated_topics_can_be_started(self):
        self.assertTrue(self.path.is_available())
        with self.settings(AI_PLANS=False):
            self.assertFalse(self.path.is_available())

    def test_the_outline_becomes_the_plan(self):
        with mock.patch("learning.outline.ask_model_json", return_value=outline_reply()), \
                mock.patch("learning.tailoring.ask_model_json") as tailor:
            self.assertTrue(_build_plan(self.profile, "an event page"))
        tailor.assert_not_called()  # One AI call, not two.
        outline = PlanOutline.objects.get()
        self.assertTrue(outline.is_active)
        self.client.force_login(self.user)
        page = self.client.get(reverse("plan"))
        self.assertTemplateUsed(page, "learning/ai_plan.html")
        self.assertContains(page, "Module 1 of 2: First steps")
        self.assertContains(page, reverse("ai_lesson", args=["L1"]))

    def test_changing_answers_replaces_the_plan(self):
        with mock.patch("learning.outline.ask_model_json", return_value=outline_reply()):
            _build_plan(self.profile, "an event page")
            _build_plan(self.profile, "a game")
        self.assertEqual(PlanOutline.objects.filter(is_active=True).count(), 1)
        self.assertEqual(PlanOutline.objects.count(), 2)

    def test_without_the_ai_and_without_topics_the_learner_can_retry(self):
        with mock.patch("learning.outline.ask_model_json", return_value=None):
            self.assertIsNone(_build_plan(self.profile, "an event page"))
        self.client.force_login(self.user)
        self.assertTemplateUsed(self.client.get(reverse("plan")), "learning/ai_plan_retry.html")
        with mock.patch("learning.outline.ask_model_json", return_value=outline_reply()):
            self.client.post(reverse("ai_plan_retry"))
        self.assertTrue(PlanOutline.objects.get().is_active)

    def test_without_the_ai_curated_topics_still_give_a_plan(self):
        Topic.objects.create(track=self.html, title="Page structure", slug="html-structure")
        with mock.patch("learning.outline.ask_model_json", return_value=None):
            self.assertFalse(_build_plan(self.profile, "an event page"))
        self.assertTrue(LearningPlan.objects.filter(learner=self.profile, is_active=True).exists())

    @override_settings(AI_PLANS=False)
    def test_off_means_the_curated_plan(self):
        Topic.objects.create(track=self.html, title="Page structure", slug="html-structure")
        with mock.patch("learning.outline.ask_model_json") as outline, \
                mock.patch("learning.tailoring.ask_model_json", return_value=None):
            _build_plan(self.profile, "an event page")
        outline.assert_not_called()
        self.assertFalse(PlanOutline.objects.exists())


@override_settings(**AI_PLANS)
class LessonPageTests(AIPlanMixin, TestCase):
    def setUp(self):
        self.make_plan()

    def test_first_open_shows_writing_then_writes_once(self):
        page = self.client.get(self.lesson_url())
        self.assertTemplateUsed(page, "learning/ai_lesson_writing.html")
        self.assertContains(page, 'http-equiv="refresh"')
        with mock.patch("learning.lessons.ask_model_json", return_value=lesson_reply()) as ask:
            self.assertRedirects(self.client.get(self.lesson_url() + "?write=1"), self.lesson_url())
            page = self.client.get(self.lesson_url())
            self.client.get(self.lesson_url() + "?write=1")  # A second ?write=1 doesn't write again.
        self.assertEqual(ask.call_count, 1)
        self.assertTemplateUsed(page, "learning/ai_lesson.html")
        self.assertContains(page, "Every web page starts as HTML.")
        self.assertContains(page, '<span class="nt">h1</span>')  # Code is colored...
        self.assertNotContains(page, "<h1>Hi")  # ...and escaped, never rendered.
        self.assertEqual(LessonProgress.objects.get(key="L1").status, "in_progress")
        self.assertEqual(AIUsage.objects.get().lessons_used, 1)

    def test_daily_lesson_limit(self):
        AIUsage.objects.create(learner=self.profile, date=timezone.localdate(), lessons_used=3)
        with mock.patch("learning.lessons.ask_model_json") as ask:
            page = self.client.get(self.lesson_url() + "?write=1")
        ask.assert_not_called()
        self.assertContains(page, "written tomorrow")

    def test_when_the_ai_fails_the_lesson_is_given_back(self):
        with mock.patch("learning.lessons.ask_model_json", return_value=None):
            page = self.client.get(self.lesson_url() + "?write=1")
        self.assertContains(page, "couldn't write this lesson")
        self.assertEqual(AIUsage.objects.get().lessons_used, 0)

    def test_unknown_lesson_or_no_plan_is_404(self):
        self.assertEqual(self.client.get(self.lesson_url("L99")).status_code, 404)
        self.client.force_login(get_user_model().objects.create_user("ben"))
        self.assertEqual(self.client.get(self.lesson_url()).status_code, 404)

    def test_warm_up_comes_from_the_previous_lesson_missed_first(self):
        self.write("L1")
        self.write("L2")
        LessonProgress.objects.create(outline=self.outline, key="L1", status="done",
                                      last_answers=["0", "x", ""], last_correct=[True, False, None])
        page = self.client.get(self.lesson_url("L2"))
        warm = page.context["warm_up"]
        self.assertEqual([w["question"]["type"] for w in warm], ["blank", "mc"])  # The missed blank first.
        self.assertContains(page, "Warm-up from the last lesson")


@override_settings(**AI_PLANS)
class CheckTests(AIPlanMixin, TestCase):
    def setUp(self):
        self.make_plan()
        self.written = self.write()

    def answer(self, *answers, key="L1"):
        data = {f"q{i}": a for i, a in enumerate(answers)}
        return self.client.post(self.lesson_url(key, "ai_lesson_check"), data)

    def test_a_pass_marks_the_lesson_done_and_shows_the_next(self):
        self.answer("0", "p", "It labels text")
        progress = LessonProgress.objects.get(key="L1")
        self.assertEqual((progress.status, progress.tries), ("done", 1))
        page = self.client.get(self.lesson_url())
        self.assertContains(page, reverse("ai_lesson", args=["L2"]))
        plan = self.client.get(reverse("plan"))
        self.assertEqual(plan.context["next_lesson"]["key"], "L2")
        self.assertEqual(plan.context["done_count"], 2)  # Setup and L1.

    def test_a_miss_keeps_the_answers_hidden_and_offers_a_rewrite(self):
        self.answer("1", "x")
        page = self.client.get(self.lesson_url())
        self.assertContains(page, "Explain it another way")
        self.assertNotContains(page, "Answer: <code>p</code>")  # They can still retry.
        self.assertNotContains(page, "Move on for now")

    def test_two_misses_offer_moving_on(self):
        self.answer("1", "x")
        self.answer("1", "x")
        self.assertContains(self.client.get(self.lesson_url()), "Move on for now")
        self.client.post(self.lesson_url(name="ai_lesson_move_on"))
        progress = LessonProgress.objects.get(key="L1")
        self.assertEqual((progress.status, progress.shaky), ("skipped", True))

    def test_rewrite_teaches_what_was_missed_with_new_questions(self):
        self.answer("1", "x")
        with mock.patch("learning.lessons.ask_model_json", return_value=lesson_reply(why="Another way")) as ask:
            self.client.post(self.lesson_url(name="ai_lesson_rewrite"))
        sent = ask.call_args.args[0][1]["content"]
        self.assertIn("Struggled with: Which tag is the biggest heading?; Paragraph text goes inside <___> tags.", sent)
        current = GeneratedLesson.objects.get(is_current=True)
        self.assertEqual((current.version, current.data["why"]), (2, "Another way"))
        progress = LessonProgress.objects.get(key="L1")
        self.assertEqual((progress.tries, progress.last_answers), (0, []))  # A clean slate for new questions.

    def test_rewrite_respects_the_daily_limit(self):
        AIUsage.objects.create(learner=self.profile, date=timezone.localdate(), lessons_used=3)
        with mock.patch("learning.lessons.ask_model_json") as ask:
            self.client.post(self.lesson_url(name="ai_lesson_rewrite"))
        ask.assert_not_called()

    def test_thumbs_down_flags_the_lesson_for_review(self):
        self.client.post(self.lesson_url(name="ai_lesson_rate"), {"helpful": "no", "note": "Used words it never explained"})
        self.written.refresh_from_db()
        self.assertTrue(self.written.flagged)
        self.assertIn("Learner: not helpful: Used words it never explained", self.written.flags)
        self.assertEqual(LessonProgress.objects.get(key="L1").rating, -1)

    def test_mark_done_skip_and_undo_from_the_plan(self):
        url = self.lesson_url(name="ai_lesson_status")
        self.client.post(url, {"status": "skipped"})
        self.assertEqual(LessonProgress.objects.get(key="L1").status, "skipped")
        self.client.post(url, {"status": "todo"})
        self.assertEqual(LessonProgress.objects.get(key="L1").status, "todo")
        self.client.post(url, {"status": "in_progress"})  # Not allowed from the plan page.
        self.assertEqual(LessonProgress.objects.get(key="L1").status, "todo")

    def test_glossary_shows_on_the_plan(self):
        self.assertContains(self.client.get(reverse("plan")), "Glossary: 2 terms so far")


@override_settings(**AI_PLANS)
class SetupLessonTests(AIPlanMixin, TestCase):
    """Every AI plan opens with setup options; one must be chosen before any lesson opens."""

    SETUP_REPLY = {
        "why": "You need a place to write.", "explain": "An editor and one folder keep every lesson in one place.",
        "try": {"prompt": "Open `index.html` in your browser and see Hi."},
        "setup": {"main": ["Download VS Code from code.visualstudio.com", "Make a folder in Documents",
                           "Open it with File, Open Folder", "Create `index.html`", "Save with Ctrl+S"],
                  "alternative": ["Open codepen.io", "Start a new Pen", "Type <h1>Hi</h1> in the HTML box"]},
        "resources": [], "check": [],
    }

    def setUp(self):
        self.make_plan(setup_chosen=False)

    def write_setup(self):
        with mock.patch("learning.lessons.ask_model_json", return_value=self.SETUP_REPLY) as ask:
            self.client.get(self.lesson_url("S1") + "?write=1")
        return ask.call_args.args[0][1]["content"] if ask.call_args else ""

    def curate(self):
        SetupStep.objects.create(track=self.html, title="Install VS Code", body="From code.visualstudio.com.", order=1)
        SetupStep.objects.create(track=self.html, title="Make a my-site folder", body="Open it in VS Code.", order=2)

    def test_lessons_stay_locked_until_a_setup_is_chosen(self):
        self.assertEqual(self.client.get(reverse("plan")).context["next_lesson"]["key"], "S1")
        self.assertContains(self.client.get(reverse("plan")), "Choose your setup to unlock your lessons")
        with mock.patch("learning.lessons.ask_model_json") as ask:
            self.assertRedirects(self.client.get(self.lesson_url("L1") + "?write=1"), self.lesson_url("S1"),
                                 fetch_redirect_response=False)
            self.client.post(self.lesson_url("L1", "ai_lesson_check"), {"q0": "0"})
            self.client.post(self.lesson_url("L1", "ai_lesson_status"), {"status": "done"})
            self.client.post(self.lesson_url("S1", "ai_lesson_status"), {"status": "done"})  # No skipping setup.
        ask.assert_not_called()
        self.assertFalse(LessonProgress.objects.exists())

    def test_without_a_curated_guide_vs_code_is_recommended(self):
        sent = self.write_setup()
        self.assertIn("Main way: VS Code. No-install way: CodePen. Project folder: codeagapay-event-page.", sent)
        page = self.client.get(self.lesson_url("S1"))
        self.assertEqual([(o["way"], o["recommended"]) for o in page.context["setup_info"]["options"]],
                         [("main", True), ("alternative", False)])
        self.assertContains(page, "codeagapay-event-page")
        self.assertContains(page, "I set up with: VS Code, step by step")
        self.assertContains(page, "I set up with: No install: CodePen")

    def test_a_curated_guide_is_the_recommended_first_option(self):
        self.curate()
        self.write_setup()
        page = self.client.get(self.lesson_url("S1"))
        self.assertEqual([(o["way"], o["recommended"]) for o in page.context["setup_info"]["options"]],
                         [("curated", True), ("main", False), ("alternative", False)])
        self.assertContains(page, "Option 1: The CodeAgapay setup guide")
        self.assertContains(page, "Make a my-site folder")

    def test_each_choice_carries_into_later_lessons(self):
        from .lessons import spec_from_outline
        self.curate()
        self.write_setup()
        for way, expected in [
            ("curated", "the CodeAgapay setup guide (Install VS Code: From code.visualstudio.com.; Make a my-site folder"),
            ("main", "VS Code, with every file in the project folder codeagapay-event-page"),
            ("alternative", "CodePen in the browser (no project folder)"),
        ]:
            self.client.post(self.lesson_url("S1", "ai_setup_done"), {"way": way})
            self.outline.refresh_from_db()
            self.assertEqual(self.outline.setup_choice, way)
            self.assertTrue(spec_from_outline(self.outline, "L1").setup.startswith(expected))
        self.assertEqual(self.client.get(reverse("plan")).context["next_lesson"]["key"], "L1")
        with mock.patch("learning.lessons.ask_model_json", return_value=lesson_reply()) as ask:
            self.client.get(self.lesson_url("L1") + "?write=1")
        self.assertIn("Learner's setup: CodePen in the browser", ask.call_args.args[0][1]["content"])

    def test_a_setup_lesson_saved_with_questions_still_offers_the_choice(self):
        data = parse_lesson(lesson_reply(), SPEC)[0]  # An older setup lesson: it has check questions.
        GeneratedLesson.objects.create(outline=self.outline, key="S1", title="Get ready", data=data,
                                       prompt_version="lesson-8")
        page = self.client.get(self.lesson_url("S1"))
        self.assertContains(page, "I set up with: VS Code, step by step")
        self.assertNotContains(page, "Check your understanding")

    def test_check_questions_are_dropped_from_new_setup_lessons(self):
        reply = {**self.SETUP_REPLY, "check": lesson_reply()["check"]}
        with mock.patch("learning.lessons.ask_model_json", return_value=reply):
            self.client.get(self.lesson_url("S1") + "?write=1")
        self.assertEqual(GeneratedLesson.objects.get(key="S1").data["check"], [])

    def test_an_unknown_choice_is_refused(self):
        self.client.post(self.lesson_url("S1", "ai_setup_done"), {"way": "curated"})  # No curated guide here.
        self.outline.refresh_from_db()
        self.assertEqual(self.outline.setup_choice, "")

    def test_when_the_ai_fails_the_curated_guide_still_works(self):
        self.curate()
        with mock.patch("learning.lessons.ask_model_json", return_value=None):
            page = self.client.get(self.lesson_url("S1") + "?write=1")
        self.assertContains(page, "I set up with the CodeAgapay guide")
        self.client.post(self.lesson_url("S1", "ai_setup_done"), {"way": "curated"})
        self.outline.refresh_from_db()
        self.assertEqual(self.outline.setup_choice, "curated")

    def test_a_setup_lesson_without_enough_steps_is_unusable_when_there_is_no_built_in_guide(self):
        from .lessons import LessonSpec, parse_lesson as parse
        thin = {**self.SETUP_REPLY, "setup": {"main": ["Make a file"]}}
        no_guide = LessonSpec(key="S1", title="Get ready", kind="setup", setup="Main way: VS Code. Project folder: x.")
        self.assertIsNone(parse(thin, no_guide)[0])
        built_in = LessonSpec(key="S1", title="Get ready", kind="setup",
                              setup="Main way: VS Code. The app shows the install steps for both ways.")
        self.assertIsNotNone(parse(thin, built_in)[0])

    def test_built_in_guides_show_full_steps_with_official_links(self):
        self.write_setup()
        page = self.client.get(self.lesson_url("S1"))
        self.assertContains(page, 'href="https://code.visualstudio.com/download"')
        self.assertContains(page, "Live Server")
        self.assertContains(page, '<strong class="ui-item">Open Folder</strong>')
        self.assertContains(page, '<strong class="ui-item">Yes, I trust the authors</strong>')
        self.assertContains(page, '<code class="inline-code">codeagapay-event-page</code>')
        self.assertContains(page, '<strong class="ui-item">Open Recent</strong>')
        self.assertContains(page, 'href="https://codepen.io"')  # The no-install way, too.
        self.assertGreaterEqual(len(page.context["setup_info"]["main_steps"]), 8)

    def test_the_ai_is_told_not_to_write_built_in_steps(self):
        self.assertIn("The app shows the install steps for both ways, so leave out", self.write_setup())


class SetupGuideTests(TestCase):
    def test_each_tool_has_a_complete_guide(self):
        from .setup_guides import guide
        python = " ".join(step["text"] for step in guide("python", "main", "codeagapay-x"))
        for words in ["Add python.exe to PATH", "`Python` (by Microsoft)", "`codeagapay-x`", "`hello.py`", "Run"]:
            self.assertIn(words, python)
        self.assertIn("https://www.python.org/downloads/", [s["link"] for s in guide("python", "main", "x")])
        self.assertIn("Extension Pack for Java", " ".join(s["text"] for s in guide("java", "main", "x")))
        self.assertIn("https://colab.research.google.com", [s["link"] for s in guide("python", "alternative", "x")])
        self.assertEqual(guide("sql", "main", "x"), [])  # No built-in guide: the AI writes the steps.


class LessonFormatTests(TestCase):
    def render(self, template_text, **context):
        from django.template import Context, Template
        return Template("{% load lesson_format %}" + template_text).render(Context(context))

    def test_code_is_colored_and_still_escaped(self):
        html = self.render("{{ code|highlight_code:'html' }}", code='<h1 class="x">Hi</h1>')
        self.assertIn('<span class="nt">h1</span>', html)  # The tag name, colored.
        self.assertIn('<span class="na">class</span>', html)  # The attribute, colored differently.
        self.assertNotIn("<h1", html)  # Escaped, never rendered.
        python = self.render("{{ code|highlight_code:'python' }}", code="for x in range(3):\n    print(x)")
        self.assertIn('<span class="k">for</span>', python)
        self.assertIn("&lt;", self.render("{{ code|highlight_code:'nonsense' }}", code="<b>"))  # unknown: plain

    def test_code_words_in_sentences_stand_out(self):
        html = self.render("{{ text|inline_code }}", text="Use `print()` or the <p> tag, not <script>alert(1)</script>.")
        self.assertIn('<code class="inline-code">print()</code>', html)
        self.assertIn('<code class="inline-code">&lt;p&gt;</code>', html)
        self.assertNotIn("<script>", html)  # Never rendered, only shown.
        self.assertIn("5 &lt; 6", self.render("{{ text|inline_code }}", text="5 < 6 and 7 > 2"))  # Not a tag.
        self.assertEqual(self.render("{{ text|inline_code }}", text="an ` alone"), "an ` alone")

    def test_lists_show_as_bullets_or_numbered_steps(self):
        text = "A page has two sections:\n- `<head>`: about the page\n- <body>: what you see\n\nSteps:\n1. Open it\n2. Save it"
        html = self.render("{{ text|paragraphs }}", text=text)
        self.assertEqual(html, (
            '<p>A page has two sections:</p><ul class="lesson-list">'
            '<li><code class="inline-code">&lt;head&gt;</code>: about the page</li>'
            '<li><code class="inline-code">&lt;body&gt;</code>: what you see</li></ul>'
            '<p>Steps:</p><ol class="lesson-list"><li>Open it</li><li>Save it</li></ol>'
        ))

    def test_long_paragraphs_saved_earlier_are_split_on_display(self):
        long = " ".join(f"Sentence {i} explains one more small thing about tags." for i in range(1, 13))
        html = self.render("{{ text|paragraphs }}", text=long)
        self.assertGreater(html.count("<p>"), 1)

    def test_paragraphs(self):
        html = self.render("{{ text|paragraphs }}", text="One `a`.\n\nTwo.")
        self.assertEqual(html, '<p>One <code class="inline-code">a</code>.</p><p>Two.</p>')


@override_settings(**AI_PLANS)
class ChangeSetupTests(AIPlanMixin, TestCase):
    """Learners can change their setup mid-plan, and choose to update lessons already written."""

    def setUp(self):
        self.make_plan()  # Set up with VS Code ("main").
        with mock.patch("learning.lessons.ask_model_json", return_value=SetupLessonTests.SETUP_REPLY):
            self.client.get(self.lesson_url("S1") + "?write=1")
        with mock.patch("learning.lessons.ask_model_json", return_value=lesson_reply()):
            self.client.get(self.lesson_url("L1") + "?write=1")
        self.client.post(self.lesson_url("L1", "ai_lesson_check"), {"q0": "0", "q1": "p"})  # Passed.

    def switch(self, way="alternative"):
        return self.client.post(self.lesson_url("S1", "ai_setup_done"), {"way": way})

    def test_the_plan_offers_to_change_setup(self):
        self.assertContains(self.client.get(reverse("plan")), "Change setup method")
        page = self.client.get(self.lesson_url("S1"))
        self.assertContains(page, "Switch to: No install: CodePen")
        self.assertNotContains(page, "Switch to: VS Code")  # Not the one they already use.

    def test_switching_offers_to_update_lessons_with_a_usage_warning(self):
        response = self.switch()
        self.assertRedirects(response, self.lesson_url("S1") + "#update", fetch_redirect_response=False)
        self.outline.refresh_from_db()
        self.assertEqual(self.outline.setup_choice, "alternative")
        page = self.client.get(self.lesson_url("S1"))
        self.assertEqual(page.context["outdated_count"], 1)  # L1 was written for VS Code; L2 isn't written yet.
        self.assertContains(page, "This uses your daily lessons.")
        self.assertContains(page, "one of your 1 new lesson left today")  # Limit 3, two used.
        self.assertContains(page, "Update my lessons")

    def test_updating_rewrites_each_lesson_when_opened_and_keeps_progress(self):
        self.switch()
        self.client.post(self.lesson_url("S1", "ai_update_lessons"))
        page = self.client.get(self.lesson_url("L1"))
        self.assertContains(page, "Updating this lesson for your new setup")
        with mock.patch("learning.lessons.ask_model_json", return_value=lesson_reply(why="Now in CodePen")) as ask:
            self.client.get(self.lesson_url("L1") + "?write=1")
            self.client.get(self.lesson_url("L1"))  # Already updated: no second rewrite.
        self.assertEqual(ask.call_count, 1)
        self.assertIn("Learner's setup: CodePen in the browser", ask.call_args.args[0][1]["content"])
        current = GeneratedLesson.objects.get(key="L1", is_current=True)
        self.assertEqual((current.version, current.data["why"]), (2, "Now in CodePen"))
        self.assertEqual(LessonProgress.objects.get(key="L1").status, "done")  # Still passed.
        self.assertEqual(AIUsage.objects.get().lessons_used, 3)

    def test_without_lessons_left_the_old_version_still_shows(self):
        self.switch()
        self.client.post(self.lesson_url("S1", "ai_update_lessons"))
        AIUsage.objects.update(lessons_used=3)
        with mock.patch("learning.lessons.ask_model_json") as ask:
            page = self.client.get(self.lesson_url("L1"), follow=True)
        ask.assert_not_called()
        self.assertTemplateUsed(page, "learning/ai_lesson.html")
        self.assertContains(page, "still shows your old setup")

    def test_keeping_them_rewrites_nothing(self):
        self.switch()
        with mock.patch("learning.lessons.ask_model_json") as ask:
            self.assertTemplateUsed(self.client.get(self.lesson_url("L1")), "learning/ai_lesson.html")
        ask.assert_not_called()

    def test_switching_again_asks_again(self):
        self.switch()
        self.client.post(self.lesson_url("S1", "ai_update_lessons"))
        self.switch("main")
        self.outline.refresh_from_db()
        self.assertFalse(self.outline.update_for_setup)
        self.assertEqual(self.client.get(self.lesson_url("S1")).context["outdated_count"], 0)  # L1 matches VS Code again.


class DeviceGuideTests(TestCase):
    """Setup steps follow the learner's computer."""

    def text(self, track, device, way="main"):
        from .setup_guides import guide
        return " ".join(step["text"] for step in guide(track, way, "codeagapay-x", device))

    def test_mac_gets_mac_shortcuts_finder_and_python3(self):
        mac = self.text("python", "mac")
        for words in ["Cmd+S", "Cmd+Shift+X", "Finder", "drag **Visual Studio Code** into your **Applications**", "`python3 hello.py`"]:
            self.assertIn(words, mac)
        for words in ["Ctrl+", "File Explorer", "PATH"]:
            self.assertNotIn(words, mac)  # Nothing that only applies to Windows.

    def test_windows_gets_windows_steps(self):
        windows = self.text("python", "windows")
        for words in ["Ctrl+S", "File Explorer", "Add python.exe to PATH", "`python hello.py`"]:
            self.assertIn(words, windows)
        self.assertNotIn("Cmd", windows)

    def test_linux_checks_for_python_first(self):
        self.assertIn("`python3 --version`", self.text("python", "linux"))
        self.assertIn(".deb package", self.text("html", "linux"))

    def test_unknown_computer_mentions_both(self):
        self.assertIn("Ctrl+S (Cmd+S on a Mac)", self.text("html", ""))


@override_settings(**AI_PLANS)
class DeviceSetupTests(AIPlanMixin, TestCase):
    def setUp(self):
        self.make_plan(setup_chosen=False)

    def use(self, device):
        self.profile.device = device
        self.profile.save()

    def test_on_a_phone_the_no_install_way_is_recommended(self):
        from .outline import setup_lesson, setup_options
        self.use("phone")
        options = setup_options(setup_lesson(self.outline))
        self.assertEqual([(o["way"], o["recommended"]) for o in options], [("main", False), ("alternative", True)])
        self.assertEqual(options[0]["note"], "Needs a Windows, Mac or Linux computer.")

    def test_the_curated_guide_stays_recommended_even_on_a_phone(self):
        from .outline import setup_lesson, setup_options
        SetupStep.objects.create(track=self.html, title="Install VS Code", body="...")
        self.use("chromebook")
        options = setup_options(setup_lesson(self.outline))
        self.assertEqual([(o["way"], o["recommended"]) for o in options],
                         [("curated", True), ("main", False), ("alternative", False)])
        self.assertTrue(options[0]["note"])  # But it says it needs a computer.

    def test_lessons_and_the_setup_page_follow_the_computer(self):
        self.use("mac")
        with mock.patch("learning.lessons.ask_model_json", return_value=SetupLessonTests.SETUP_REPLY) as ask:
            self.client.get(self.lesson_url("S1") + "?write=1")
        self.assertIn("Computer: A Mac", ask.call_args.args[0][1]["content"])
        self.assertContains(self.client.get(self.lesson_url("S1")), "<kbd>Cmd</kbd>+<kbd>S</kbd>")


class ClickAndKeyFormatTests(TestCase):
    def render(self, text):
        from django.template import Context, Template
        return Template("{% load lesson_format %}{{ text|inline_code }}").render(Context({"text": text}))

    def test_things_to_click_are_bold_and_shortcuts_are_keys(self):
        html = self.render("Turn on **File** → **Auto Save**, then press Ctrl+Shift+X (Cmd+Shift+X on a Mac).")
        self.assertIn('<strong class="ui-item">File</strong> → <strong class="ui-item">Auto Save</strong>', html)
        self.assertIn("<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>X</kbd>", html)
        self.assertIn("<kbd>Cmd</kbd>+<kbd>Shift</kbd>+<kbd>X</kbd>", html)

    def test_marks_inside_code_stay_as_typed(self):
        html = self.render("Type `x = 2 ** 3` and `**kwargs`, not **Ctrl+C** in code.")
        self.assertIn('<code class="inline-code">x = 2 ** 3</code>', html)
        self.assertIn('<code class="inline-code">**kwargs</code>', html)
        self.assertIn('<strong class="ui-item"><kbd>Ctrl</kbd>+<kbd>C</kbd></strong>', html)

    def test_still_escaped(self):
        self.assertNotIn("<script>", self.render("**<script>alert(1)</script>**"))

    def test_ordinary_words_are_left_alone(self):
        self.assertEqual(self.render("Shift your focus, then Save it."), "Shift your focus, then Save it.")


@override_settings(**AI_PLANS)
class PlanFormattingTests(AIPlanMixin, TestCase):
    def test_plan_lists_and_text_use_the_lesson_style(self):
        self.make_plan()
        data = self.outline.data
        data["modules"][0]["goal"] = "Use **File** → **Open Folder** and the <body> tag"
        data["project"]["done_when"] = ["Saved with Ctrl+S"]
        self.outline.save()
        page = self.client.get(reverse("plan")).content.decode()
        self.assertIn('<strong class="ui-item">File</strong>', page)
        self.assertIn('<code class="inline-code">&lt;body&gt;</code>', page)
        self.assertIn("<kbd>Ctrl</kbd>+<kbd>S</kbd>", page)
        # Stuck tips, project steps, done-when checks and assumptions are all lesson-style lists.
        self.assertGreaterEqual(page.count('class="lesson-list"'), 5)


@override_settings(**AI_PLANS)
class SetupLayoutTests(AIPlanMixin, TestCase):
    def test_setup_page_order(self):
        self.make_plan(setup_chosen=False)
        with mock.patch("learning.lessons.ask_model_json", return_value=SetupLessonTests.SETUP_REPLY):
            self.client.get(self.lesson_url("S1") + "?write=1")
        page = self.client.get(self.lesson_url("S1")).content.decode()
        order = [page.index(text) for text in [
            "Choose how you want to set up", "Option 1:", "Check it works", "I set up with:", "Go deeper",
            "Was this lesson helpful?"]]
        self.assertEqual(order, sorted(order))
        self.assertNotIn("Check your understanding", page)


class TryStepsTests(TestCase):
    def text(self, *args):
        from .setup_guides import try_steps
        return " ".join(step["text"] for step in try_steps(*args))

    def test_vs_code_steps_name_the_file_and_match_the_computer(self):
        steps = self.text("main", "html", "about.html", "codeagapay-x", "mac")
        for words in ["**Open Recent** → `codeagapay-x`", "name it `about.html`", "Cmd+S", "**Open with Live Server**"]:
            self.assertIn(words, steps)
        self.assertIn("**Run**", self.text("main", "python", "grades.py", "x", "windows"))

    def test_the_teams_guide_opens_pages_in_the_browser(self):
        steps = self.text("curated", "html", "", "x", "windows")
        self.assertIn("`practice.html`", steps)  # No file from the AI: a sensible default.
        self.assertIn("double-click `practice.html` in File Explorer", steps)
        self.assertNotIn("Live Server", steps)

    def test_no_install_ways_say_which_box_or_cell(self):
        self.assertIn("**CSS** box", self.text("alternative", "css", "style.css", "x", ""))
        self.assertIn("**+ Code**", self.text("alternative", "python", "", "x", ""))
        self.assertEqual(self.text("alternative", "sql", "", "x", ""), "")  # Nothing reliable to say.


@override_settings(**AI_PLANS)
class TryItPageTests(AIPlanMixin, TestCase):
    def setUp(self):
        self.make_plan()  # Set up with VS Code.

    def write_l1(self, **task):
        reply = lesson_reply(**{"try": {"prompt": "Add an About heading.", "file": "about.html",
                                        "answer": "<h1>About</h1>", **task}})
        with mock.patch("learning.lessons.ask_model_json", return_value=reply) as ask:
            self.client.get(self.lesson_url("L1") + "?write=1")
        return ask

    def test_beginners_get_the_steps_open(self):
        ask = self.write_l1()
        self.assertIn("Name the one file the task uses", ask.call_args.args[0][0]["content"])
        page = self.client.get(self.lesson_url("L1"))
        self.assertContains(page, '<details class="plan-item-details" open>\n    <summary>How to try it in your setup')
        self.assertContains(page, "name it <code class=\"inline-code\">about.html</code>")
        self.assertContains(page, "Want to run an example yourself?")

    def test_others_get_a_collapsed_reminder(self):
        self.outline.data["level"] = "intermediate"
        self.outline.save()
        self.write_l1()
        page = self.client.get(self.lesson_url("L1"))
        self.assertContains(page, "Need a reminder of how to try it?")
        self.assertNotContains(page, "Want to run an example yourself?")

    def test_unsafe_file_names_are_dropped(self):
        self.write_l1(file="../my folder/x.html")
        self.assertEqual(GeneratedLesson.objects.get(key="L1").data["try_it"]["file"], "")


class DraftLessonSetupTests(TestCase):
    @override_settings(**AI_ON)
    def test_draft_lesson_can_pretend_a_setup_and_computer(self):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        reply = lesson_reply(**{"try": {"prompt": "Add a heading.", "file": "about.html"}})
        with mock.patch("learning.lessons.ask_model_json", return_value=reply) as ask:
            call_command("draft_lesson", "--title", "Headings", "--track", "HTML", "--setup", "main",
                         "--device", "mac", "--folder", "codeagapay-test", stdout=out)
        sent = ask.call_args.args[0][1]["content"]
        self.assertIn("Learner's setup: VS Code, with every file in the project folder codeagapay-test", sent)
        self.assertIn("Computer: A Mac", sent)
        self.assertIn("How to try it, as the page shows it (file from the AI: about.html)", out.getvalue())
        self.assertIn("Cmd+S", out.getvalue())


@override_settings(**AI_PLANS)
class SetupCollapsedTests(AIPlanMixin, TestCase):
    def test_every_option_starts_collapsed_with_a_summary(self):
        self.make_plan(setup_chosen=False)
        with mock.patch("learning.lessons.ask_model_json", return_value=SetupLessonTests.SETUP_REPLY):
            self.client.get(self.lesson_url("S1") + "?write=1")
        page = self.client.get(self.lesson_url("S1")).content.decode()
        self.assertEqual(page.count('<details class="plan-week plan-week-setup">'), 2)
        self.assertNotIn('<details class="plan-week plan-week-setup" open>', page)
        self.assertIn("Nothing to install, so it works on a phone", page)
        self.assertIn("Tap an option to see its steps.", page)


@override_settings(**AI_PLANS)
class AILessonHelpTests(AIPlanMixin, TestCase):
    """The Agapay help panel on AI lessons: hints grounded in the lesson, never its answers."""

    def setUp(self):
        self.make_plan()
        self.write()  # L1: key terms tag and element; check: mc (answer h1), blank (answer p), self.

    def ask(self, **data):
        import json
        body = {"lesson": "L1", "question": "I'm stuck", "hint_level": 1, **data}
        with mock.patch("assistant.service.call_provider", return_value="Look at the closing tag.") as call:
            response = self.client.post(reverse("help_ask"), json.dumps(body), content_type="application/json")
        return response.json(), call

    def test_the_lesson_page_has_the_panel(self):
        page = self.client.get(self.lesson_url())
        self.assertContains(page, 'data-lesson="L1"')
        self.assertContains(page, "Helping with: Tags")

    def test_hints_use_the_lessons_own_content(self):
        reply, call = self.ask()
        self.assertEqual((reply["mode"], reply["reply"]), ("ai", "Look at the closing tag."))
        system = call.call_args.args[1][0]["content"]
        self.assertIn("Topic: Tags (HTML)", system)
        self.assertIn("tag: A label in angle brackets.", system)  # Key terms.
        self.assertIn("HTML marks up text as headings and paragraphs.", system)  # The explanation.
        self.assertIn("Never give the full solution", system)
        self.assertEqual(reply["resources"][0]["url"], "https://developer.mozilla.org/en-US/docs/Web/HTML")

    def test_why_is_this_wrong_never_sends_the_answer(self):
        self.client.post(self.lesson_url(name="ai_lesson_check"), {"q0": "1", "q1": "x"})
        page = self.client.get(self.lesson_url())
        self.assertContains(page, 'data-quiz-item="0" data-answer="h6"')  # The chosen option's words.
        reply, call = self.ask(screen="quiz", quiz_item_id="1", learner_answer="x")
        user = call.call_args.args[1][1]["content"]
        self.assertIn("I'm on this quiz question: Paragraph text goes inside <___> tags.", user)
        self.assertIn("My answer so far: x", user)
        sent = call.call_args.args[1][0]["content"] + user
        self.assertNotIn("Paragraphs use p.", sent)  # The question's explanation stays on the server.

    def test_another_learners_lesson_is_not_reachable(self):
        self.client.force_login(get_user_model().objects.create_user("ben"))
        reply, call = self.ask()
        call.assert_not_called()
        self.assertEqual(reply["reply"], "Open a topic first, then ask your question.")

    def test_without_ai_the_lesson_terms_and_links_still_help(self):
        AIUsage.objects.create(learner=self.profile, date=timezone.localdate(), messages_used=99)
        reply, call = self.ask()
        call.assert_not_called()
        self.assertEqual(reply["mode"], "fallback")
        self.assertEqual(reply["tips"][0], "tag: A label in angle brackets.")


@override_settings(**AI_PLANS)
class AIReminderTests(AIPlanMixin, TestCase):
    def setUp(self):
        self.make_plan()
        self.profile.email_reminders = True
        self.profile.save()
        self.user.email = "ana@example.com"
        self.user.save()
        week_ago = timezone.now() - timezone.timedelta(days=8)
        PlanOutline.objects.filter(pk=self.outline.pk).update(created_at=week_ago)
        LessonProgress.objects.filter(outline=self.outline).update(updated_at=week_ago)
        get_user_model().objects.filter(pk=self.user.pk).update(last_login=week_ago)

    def reminder(self):
        from .reminders import reminder_for
        return reminder_for(get_profile(get_user_model().objects.get(pk=self.user.pk)))

    def test_a_quiet_learner_is_reminded_of_their_next_ai_lesson(self):
        reminder = self.reminder()
        self.assertEqual((reminder.action.title, reminder.action.url), ("Tags", reverse("ai_lesson", args=["L1"])))

    def test_lesson_progress_counts_as_activity(self):
        LessonProgress.objects.create(outline=self.outline, key="L1", status="in_progress")
        self.assertIsNone(self.reminder())

    def test_without_a_setup_the_reminder_asks_to_choose_one(self):
        PlanOutline.objects.filter(pk=self.outline.pk).update(setup_choice="")
        LessonProgress.objects.filter(key="S1").delete()
        self.assertEqual(self.reminder().action.title, "Choose your setup")

    def test_a_finished_plan_gets_no_reminder(self):
        for key in ["L1", "L2", "L3", "L4", "L5"]:
            LessonProgress.objects.create(outline=self.outline, key=key, status="done")
        LessonProgress.objects.update(updated_at=timezone.now() - timezone.timedelta(days=8))
        self.assertIsNone(self.reminder())


@override_settings(**AI_PLANS)
class AIFinishTests(AIPlanMixin, TestCase):
    def setUp(self):
        self.make_plan()

    def test_finish_page_waits_for_the_last_lesson(self):
        self.assertRedirects(self.client.get(reverse("plan_finish")), reverse("plan"))

    def test_finish_page_shows_what_was_done_and_what_comes_next(self):
        self.write("L1")
        for key, status, shaky in [("L1", "done", False), ("L2", "done", False), ("L3", "skipped", True),
                                   ("L4", "skipped", False), ("L5", "done", False)]:
            LessonProgress.objects.create(outline=self.outline, key=key, status=status, shaky=shaky)
        plan = self.client.get(reverse("plan"))
        self.assertContains(plan, "See what you finished")
        page = self.client.get(reverse("plan_finish"))
        self.assertTemplateUsed(page, "learning/ai_finish.html")
        self.assertEqual([x["key"] for x in page.context["done"]], ["L1", "L2", "L5"])
        self.assertEqual([x["key"] for x in page.context["moved_on"]], ["L3"])
        self.assertEqual([x["key"] for x in page.context["skipped"]], ["L4"])
        self.assertContains(page, "Forms")  # The AI's "after this plan" suggestions.
        self.assertContains(page, "Your glossary: 2 terms")
        self.assertContains(page, "Congratulations, ")
        self.assertContains(page, "Certificate of completion")

    def test_skipping_every_lesson_still_opens_the_finish_page(self):
        # The plan page says "Plan finished" once nothing is left, so its button must lead somewhere.
        for key in ["L1", "L2", "L3", "L4", "L5"]:
            LessonProgress.objects.create(outline=self.outline, key=key, status="skipped")
        self.assertContains(self.client.get(reverse("plan")), reverse("plan_finish"))
        page = self.client.get(reverse("plan_finish"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "no certificate yet")
        self.assertNotContains(page, "Certificate of completion")


@override_settings(**AI_PLANS)
class AIProfileTests(AIPlanMixin, TestCase):
    def setUp(self):
        self.make_plan()

    def test_profile_shows_ai_plan_progress_and_setup_method(self):
        LessonProgress.objects.create(outline=self.outline, key="L1", status="done", tries=1)
        LessonProgress.objects.create(outline=self.outline, key="L2", status="in_progress")
        page = self.client.get(reverse("profile"))
        lessons = [x for x in ai_plan.lessons_in_order(self.outline) if x["kind"] != "setup"]
        self.assertEqual(page.context["progress"]["total"], len(lessons))
        self.assertContains(page, f"1 topic done out of {len(lessons)}")
        self.assertContains(page, "1 quiz passed")
        self.assertContains(page, f"Continue “{lessons[1]['title']}”")
        self.assertContains(page, reverse("ai_lesson", args=[lessons[0]["key"]]))
        self.assertContains(page, "VS Code, step by step")


@override_settings(**{**AI_PLANS, "AI_PLANS": False})
class EarlyAccessTests(AIPlanMixin, TestCase):
    """With AI_PLANS off for everyone, learners given early access still get AI plans."""

    def setUp(self):
        self.make_learner()
        Topic.objects.create(track=self.html, title="Page structure", slug="html-structure")
        self.client.force_login(self.user)

    def build(self):
        with mock.patch("learning.outline.ask_model_json", return_value=outline_reply()), \
                mock.patch("learning.tailoring.ask_model_json", return_value=None):
            return _build_plan(self.profile, "an event page")

    def test_without_early_access_its_the_curated_plan(self):
        self.assertFalse(self.build())
        self.assertFalse(PlanOutline.objects.exists())
        self.assertTemplateUsed(self.client.get(reverse("plan")), "learning/plan.html")

    def test_with_early_access_its_an_ai_plan(self):
        self.profile.ai_plans_early = True
        self.profile.save()
        self.assertTrue(self.build())
        self.assertTemplateUsed(self.client.get(reverse("plan")), "learning/ai_plan.html")

    def test_paths_without_topics_are_offered_only_to_early_learners(self):
        from diagnose import onboarding
        Topic.objects.all().delete()
        with onboarding.cached_paths(False):
            self.assertEqual(onboarding.available_paths(), [])
        with onboarding.cached_paths(True):
            self.assertEqual(onboarding.available_paths(), [self.path])

    def test_admin_actions_turn_it_on_and_off(self):
        admin_user = get_user_model().objects.create_superuser("curator", "c@example.com", "pw")
        self.client.force_login(admin_user)
        url = reverse("admin:accounts_learnerprofile_changelist")
        self.client.post(url, {"action": "give_ai_plans_early", "_selected_action": [self.profile.pk]})
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.ai_plans_early)
        self.client.post(url, {"action": "take_ai_plans_early", "_selected_action": [self.profile.pk]})
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.ai_plans_early)


@override_settings(**AI_PLANS)
class EnglishLessonsTests(AIPlanMixin, TestCase):
    """Lessons are always English; only the Need help panel answers in Taglish."""

    def setUp(self):
        self.make_plan()
        self.profile.goal_text = "Make a website: gusto ko po gumawa ng page para sa org namin"
        self.profile.save()

    def test_a_taglish_goal_still_gets_an_english_lesson(self):
        with mock.patch("learning.lessons.ask_model_json", return_value=lesson_reply()) as ask:
            self.client.get(self.lesson_url("L1") + "?write=1")
        system, user = (m["content"] for m in ask.call_args.args[0])
        self.assertNotIn("Taglish", user)
        self.assertIn("Write in plain English", system)

    def test_need_help_still_answers_in_taglish(self):
        import json
        self.write()
        body = {"lesson": "L1", "question": "bakit hindi gumagana yung tag ko?", "hint_level": 1}
        with mock.patch("assistant.service.call_provider", return_value="Tingnan mo yung closing tag.") as call:
            self.client.post(reverse("help_ask"), json.dumps(body), content_type="application/json")
        system, user = (m["content"] for m in call.call_args.args[1])
        self.assertIn("reply in Taglish", system)
        self.assertIn("(I wrote in Taglish. Please reply in Taglish too.)", user)

    def test_practice_feedback_is_in_english(self):
        from types import SimpleNamespace
        from assistant.service import build_practice_messages
        task = SimpleNamespace(topic=SimpleNamespace(title="Tags", track=SimpleNamespace(name="HTML"), summary=""),
                               prompt="Write a heading.", checklist=["Uses h1"], sample_answer="<h1>Hi</h1>")
        system = build_practice_messages(task, "gusto ko po ng heading")[0]["content"]
        self.assertIn("Reply in plain English, even if the learner wrote in Taglish", system)
