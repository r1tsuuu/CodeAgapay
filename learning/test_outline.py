from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import get_profile
from content.models import Path, PathTrack, ProjectIdea, Topic, Track
from diagnose.models import TopicMastery
from diagnose.views import _build_plan

from .models import PlanOutline
from .outline import (
    MAX_LESSONS, STUCK_PATH, build_messages, generate_outline, lesson_limit, load_prompt, parse_outline,
)

AI_ON = {"GROQ_API_KEY": "test", "CF_ACCOUNT_ID": "", "CF_API_TOKEN": "", "AI_INTAKE_DAILY_LIMIT": 5}


def lesson(title, minutes=25, kind="core", needs=()):
    return {"title": title, "can": f"You will be able to {title.lower()}", "min": minutes, "kind": kind,
            "needs": list(needs)}


def reply(modules=None, **extra):
    """A model reply in the shape the outline prompt asks for."""
    modules = modules if modules is not None else [
        {"title": "First steps", "goal": "Make a page", "done": "You can now make a page",
         "lessons": [lesson("Tags"), lesson("Headings", needs=[1]), lesson("Links", needs=[2])]},
        {"title": "Style", "goal": "Make it look good", "done": "You can now style a page",
         "lessons": [lesson("Colors", needs=[1]), lesson("Boxes", needs=[4])]},
    ]
    data = {
        "goal": "An event page for my org",
        "assumptions": ["They have a laptop"],
        "conflict": "",
        "modules": modules,
        "project": {"title": "Event page", "description": "A page for the org's event.",
                    "steps": [{"module": 1, "text": "Write the page"}, {"module": 2, "text": "Style it"}],
                    "done_when": ["It opens in a browser", "It has the event date"], "idea": 0},
        "next": ["Forms"],
    }
    data.update(extra)
    return data


class OutlineContentMixin:
    def make_learner(self, hours=3, weeks=None, experience="none"):
        self.html = Track.objects.create(name="HTML", slug="html", order=1)
        self.css = Track.objects.create(name="CSS", slug="css", order=2, is_active=False)
        self.path = Path.objects.create(title="Make a website", slug="website", tagline="A page.")
        PathTrack.objects.create(path=self.path, track=self.html, order=1)
        PathTrack.objects.create(path=self.path, track=self.css, order=2)
        self.user = get_user_model().objects.create_user("ana", "ana@example.com")
        self.profile = get_profile(self.user)
        self.profile.path, self.profile.track = self.path, self.html
        self.profile.hours_per_week, self.profile.target_weeks = hours, weeks
        self.profile.experience, self.profile.goal_text = experience, "An event page for my org"
        self.profile.onboarded = True
        self.profile.save()


class PromptTests(OutlineContentMixin, TestCase):
    def setUp(self):
        self.make_learner()

    def test_prompt_file_has_a_version(self):
        system, version = load_prompt()
        self.assertEqual(version, "outline-2")
        self.assertIn("Return only a JSON object", system)
        self.assertNotIn("version:", system)

    def test_system_prompt_is_the_same_for_every_learner(self):
        # Learner details go only in the user message, so providers can cache the system prompt.
        other = get_profile(get_user_model().objects.create_user("ben"))
        other.experience = "comfortable"
        mine, _ = build_messages(self.profile, "an event page")
        theirs, _ = build_messages(other, "a game")
        self.assertEqual(mine[0], theirs[0])
        self.assertNotEqual(mine[1], theirs[1])

    def test_user_message_is_short_and_has_what_the_plan_needs(self):
        topic = Topic.objects.create(track=self.html, title="Page structure", slug="html-structure")
        TopicMastery.objects.create(learner=self.profile, topic=topic, status="demonstrated", known=True,
                                    source="skill_check")
        user = build_messages(self.profile, "an event page")[0][1]["content"]
        self.assertIn("Path: Make a website (HTML, CSS)", user)  # inactive tracks too: the AI writes the lessons
        self.assertIn("Level: beginner (lesson minutes 15-30)", user)
        self.assertIn("Lesson limit: 20", user)
        self.assertIn("Showed on the skill check (leave out): Page structure", user)
        self.assertNotIn("Taglish", user)
        self.assertLess(len(user), 600)

    def test_taglish_learner_is_flagged(self):
        user = build_messages(self.profile, "gusto ko po gumawa ng page para sa org namin")[0][1]["content"]
        self.assertIn("Language: Taglish", user)

    def test_project_ideas_are_numbered_and_short(self):
        idea = ProjectIdea(track=self.html, title="Org page", brief="x" * 400)
        user = build_messages(self.profile, "", [idea])[0][1]["content"]
        self.assertIn("1. Org page: " + "x" * 160 + "\n", user + "\n")

    def test_lesson_limit_fits_their_time(self):
        self.assertEqual(lesson_limit(self.profile, "beginner"), 20)  # no date given
        self.profile.target_weeks = 2  # 3 hours x 2 weeks = 360 minutes, about 22 minutes a lesson
        self.assertEqual(lesson_limit(self.profile, "beginner"), 16)
        self.profile.target_weeks = 1
        self.profile.hours_per_week = 1
        self.assertEqual(lesson_limit(self.profile, "beginner"), 4)  # never fewer than 4
        self.profile.target_weeks, self.profile.hours_per_week = 52, 20
        self.assertEqual(lesson_limit(self.profile, "beginner"), MAX_LESSONS)


class ParseOutlineTests(OutlineContentMixin, TestCase):
    def setUp(self):
        self.make_learner(hours=1)

    def test_code_adds_what_the_model_never_writes(self):
        outline, repairs = parse_outline(reply(), self.profile)
        self.assertEqual(repairs, [])
        first, second = outline["modules"]
        self.assertEqual(first["progress"], "Module 1 of 2")
        self.assertEqual(first["stuck_path"], STUCK_PATH)
        self.assertEqual([x["key"] for x in first["lessons"]], ["L1", "L2", "L3"])
        self.assertEqual(second["lessons"][1]["needs"], ["L4"])
        # 1 hour a week, 25-minute lessons: two lessons a week.
        self.assertEqual([x["week"] for m in outline["modules"] for x in m["lessons"]], [1, 1, 2, 2, 3])
        self.assertEqual((outline["lessons_total"], outline["minutes_total"], outline["weeks_total"]), (5, 125, 3))
        self.assertIn("Sessions of about 30 minutes (we didn't ask).", outline["assumptions"])
        # Each step ends with its module: module 1 ends in week 2, module 2 in week 3.
        self.assertEqual([s["week"] for s in outline["project"]["milestones"]], [2, 3])
        self.assertEqual(outline["project"]["milestones"][0]["topics"], ["L1", "L2", "L3"])

    def test_project_steps_follow_modules_through_splits(self):
        modules = [{"title": "Basics", "lessons": [lesson(f"B{i}") for i in range(7)]},
                   {"title": "More", "lessons": [lesson("M1")]}]
        data = reply(modules)
        data["project"]["steps"] = [{"module": 1, "text": "Start"}, {"module": 9, "text": "Lost"},
                                    {"module": 2, "text": "Finish"}]
        outline, repairs = parse_outline(data, self.profile)
        steps = outline["project"]["milestones"]
        self.assertEqual([s["text"] for s in steps], ["Start", "Finish"])
        self.assertEqual(steps[0]["topics"], [f"L{i}" for i in range(1, 8)])  # both parts of the split module
        self.assertEqual([s["week"] for s in steps], [4, 4])
        self.assertIn("Dropped project step for unknown module 9", repairs)

    def test_unicode_hyphens_become_plain(self):
        outline, _ = parse_outline(reply(goal="A sign‑up page"), self.profile)
        self.assertEqual(outline["goal"], "A sign-up page")

    def test_minutes_are_clamped_to_the_depth_table(self):
        modules = [{"title": "M", "lessons": [lesson("Long", minutes=90), lesson("Bad", minutes="soon")]}]
        outline, repairs = parse_outline(reply(modules), self.profile)
        self.assertEqual([x["minutes"] for x in outline["modules"][0]["lessons"]], [30, 22])
        self.assertIn("Lesson 1: 90 min clamped to 15-30", repairs)

    def test_needs_only_point_backwards_and_survive_dropped_lessons(self):
        modules = [{"title": "M", "lessons": [
            lesson("A", needs=[2]), {"can": "no title"}, lesson("C", needs=[1, 2, 9]), lesson("D", needs=[3]),
        ]}]
        outline, repairs = parse_outline(reply(modules), self.profile)
        lessons = outline["modules"][0]["lessons"]
        self.assertEqual([x["title"] for x in lessons], ["A", "C", "D"])
        self.assertEqual([x["needs"] for x in lessons], [[], ["L1"], ["L2"]])  # model's 3 is now L2
        self.assertIn("Dropped lesson 2: no title", repairs)

    def test_extra_lessons_are_cut_optional_first(self):
        self.profile.target_weeks = 1  # limit of 4
        modules = [{"title": "M", "lessons": [
            lesson("A"), lesson("Nice", kind="optional"), lesson("B"), lesson("C"), lesson("D"), lesson("E"),
        ]}]
        outline, repairs = parse_outline(reply(modules), self.profile)
        self.assertEqual([x["title"] for x in outline["modules"][0]["lessons"]], ["A", "B", "C", "D"])
        self.assertIn("6 lessons cut to the limit of 4", repairs)

    def test_long_modules_are_split(self):
        modules = [{"title": "Basics", "done": "You can now build", "lessons": [lesson(f"L{i}") for i in range(7)]}]
        outline, repairs = parse_outline(reply(modules), self.profile)
        self.assertEqual([m["title"] for m in outline["modules"]], ["Basics", "Basics (part 2)"])
        self.assertEqual([m["milestone"] for m in outline["modules"]], ["", "You can now build"])
        self.assertEqual(outline["modules"][1]["progress"], "Module 2 of 2")

    def test_deadline_conflict_is_worked_out_in_code(self):
        self.profile.target_weeks = 2
        outline, _ = parse_outline(reply(), self.profile)
        self.assertIn("about 3 weeks", outline["conflict"])

    def test_unusable_project_gets_a_plain_one(self):
        outline, repairs = parse_outline(reply(project={"title": "No steps"}), self.profile)
        self.assertEqual(outline["project"]["title"], "Your mini project")
        self.assertEqual(len(outline["project"]["milestones"]), 3)
        self.assertIn("Project unusable; used a plain one", repairs)

    def test_curated_idea_is_recorded(self):
        idea = ProjectIdea.objects.create(track=self.html, title="Org page", brief="A page.", done_when=["Opens"])
        data = reply()
        data["project"]["idea"] = 1
        outline, _ = parse_outline(data, self.profile, [idea])
        self.assertEqual(outline["idea"], idea.pk)

    def test_wrong_types_do_not_crash(self):
        modules = [{"title": "M", "lessons": [{"title": "A", "needs": 3, "min": None, "kind": 5}]}, "junk"]
        outline, _ = parse_outline(reply(modules, assumptions="one", next=7, project=[]), self.profile)
        self.assertEqual(outline["modules"][0]["lessons"][0]["needs"], [])
        self.assertEqual(outline["next_steps"], [])

    def test_no_usable_lessons_is_unusable(self):
        outline, repairs = parse_outline(reply([{"title": "Empty", "lessons": []}]), self.profile)
        self.assertIsNone(outline)
        self.assertEqual(repairs, ["No usable lessons"])


@override_settings(**AI_ON)
class GenerateOutlineTests(OutlineContentMixin, TestCase):
    def setUp(self):
        self.make_learner()

    def fake_ask(self, *replies):
        replies = list(replies)

        def ask(messages, max_tokens, usage):
            usage.update(model="openai/gpt-oss-120b", prompt_tokens=700, completion_tokens=900)
            return replies.pop(0)
        return mock.patch("learning.outline.ask_model_json", side_effect=ask)

    def test_saves_the_outline_with_tokens_and_version(self):
        with self.fake_ask(reply()) as ask:
            record = generate_outline(self.profile, "an event page")
        self.assertEqual(ask.call_count, 1)
        record.refresh_from_db()
        self.assertEqual((record.prompt_version, record.model), (load_prompt()[1], "openai/gpt-oss-120b"))
        self.assertEqual((record.prompt_tokens, record.completion_tokens), (700, 900))
        self.assertEqual(record.review, PlanOutline.Review.NOT_REVIEWED)

    def test_asks_once_more_only_when_nothing_is_usable(self):
        with self.fake_ask({"modules": []}, reply()) as ask:
            record = generate_outline(self.profile)
        self.assertEqual(ask.call_count, 2)
        self.assertEqual((record.prompt_tokens, record.completion_tokens), (1400, 1800))  # both calls counted
        self.assertEqual(record.repairs[0], "Asked again: the first reply had no usable lessons")

    def test_gives_up_after_two_unusable_replies(self):
        with self.fake_ask({"modules": []}, {"modules": []}) as ask:
            self.assertIsNone(generate_outline(self.profile))
        self.assertEqual(ask.call_count, 2)
        self.assertFalse(PlanOutline.objects.exists())

    def test_does_not_ask_again_when_every_provider_failed(self):
        with mock.patch("learning.outline.ask_model_json", return_value=None) as ask:
            self.assertIsNone(generate_outline(self.profile))
        self.assertEqual(ask.call_count, 1)

    def test_dry_run_saves_nothing(self):
        with self.fake_ask(reply()):
            record = generate_outline(self.profile, save=False)
        self.assertIsNone(record.pk)
        self.assertFalse(PlanOutline.objects.exists())


@override_settings(**AI_ON)
class ShadowModeTests(OutlineContentMixin, TestCase):
    def setUp(self):
        self.make_learner()
        Topic.objects.create(track=self.html, title="Page structure", slug="html-structure")
        patcher = mock.patch("learning.tailoring.ask_model_json", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_off_by_default(self):
        with mock.patch("diagnose.views.generate_outline") as generate:
            _build_plan(self.profile, "an event page")
        generate.assert_not_called()

    @override_settings(AI_OUTLINES=True)
    def test_on_saves_an_outline_next_to_the_plan(self):
        with mock.patch("learning.outline.ask_model_json", return_value=reply()):
            _build_plan(self.profile, "an event page")
        outline = PlanOutline.objects.get()
        self.assertEqual(outline.plan, self.profile.plans.get(is_active=True))

    @override_settings(AI_OUTLINES=True)
    def test_a_failing_outline_never_stops_the_plan(self):
        with mock.patch("diagnose.views.generate_outline", side_effect=RuntimeError("boom")), \
                self.assertLogs("diagnose.views", "ERROR"):
            _build_plan(self.profile, "an event page")
        self.assertTrue(self.profile.plans.filter(is_active=True).exists())


class OutlineAdminTests(OutlineContentMixin, TestCase):
    def setUp(self):
        self.make_learner()
        self.outline = PlanOutline.objects.create(
            learner=self.profile, data=parse_outline(reply(), self.profile)[0], prompt_version="outline-1",
            prompt_tokens=700, completion_tokens=900,
        )
        self.admin = get_user_model().objects.create_superuser("curator", "c@example.com", "pw")
        self.client.force_login(self.admin)

    def test_review_page_shows_the_outline_readably(self):
        page = self.client.get(reverse("admin:learning_planoutline_change", args=[self.outline.pk]))
        self.assertContains(page, "Module 1 of 2: First steps")
        self.assertContains(page, "L2 · week 1 · 25 min · core (needs L1)")
        self.assertContains(page, "Event page")

    def test_list_has_review_filters_and_a_random_sample(self):
        page = self.client.get(reverse("admin:learning_planoutline_changelist"), {"sample": "10"})
        self.assertContains(page, "700 / 900")
        self.assertContains(page, "10 random")

    def test_changing_review_on_the_form_records_the_reviewer(self):
        url = reverse("admin:learning_planoutline_change", args=[self.outline.pk])
        self.client.post(url, {"review": "problem", "review_notes": "Project uses untaught media queries"})
        self.outline.refresh_from_db()
        self.assertEqual((self.outline.review, self.outline.reviewed_by), ("problem", self.admin))
        self.assertIsNotNone(self.outline.reviewed_at)

    def test_outlines_cannot_be_added_by_hand(self):
        self.assertEqual(self.client.get(reverse("admin:learning_planoutline_add")).status_code, 403)

    def test_mark_ok_records_the_reviewer(self):
        self.client.post(reverse("admin:learning_planoutline_changelist"),
                         {"action": "mark_ok", "_selected_action": [self.outline.pk]})
        self.outline.refresh_from_db()
        self.assertEqual((self.outline.review, self.outline.reviewed_by), ("ok", self.admin))


class DraftOutlineCommandTests(OutlineContentMixin, TestCase):
    def setUp(self):
        self.make_learner()

    def test_show_prompt_needs_no_ai(self):
        out = StringIO()
        call_command("draft_outline", "--path", "website", "--weeks", "4", "--show-prompt", stdout=out)
        self.assertIn("Path: Make a website (HTML, CSS)", out.getvalue())
        self.assertIn("aiming to finish in 4 weeks", out.getvalue())

    @override_settings(**AI_ON)
    def test_drafts_for_a_learner_without_saving(self):
        out = StringIO()
        with mock.patch("learning.outline.ask_model_json", return_value=reply()):
            call_command("draft_outline", "--learner", "ana@example.com", stdout=out)
        self.assertIn("not saved", out.getvalue())
        self.assertFalse(PlanOutline.objects.exists())
