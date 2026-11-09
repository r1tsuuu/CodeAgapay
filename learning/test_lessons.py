from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from .lessons import (
    LessonSpec, allowed_link, build_messages, generate_lesson, glossary, lesson_for, parse_lesson,
    regenerate_lesson, spec_from_outline, warm_up,
)
from .models import GeneratedLesson, PlanOutline
from .outline import load_prompt, parse_outline
from .test_outline import AI_ON, OutlineContentMixin, reply as outline_reply

SPEC = LessonSpec(key="L2", title="Your first HTML page", can="Make a page", tracks="HTML, CSS", path="Make a website")


def lesson_reply(**extra):
    """A model reply in the shape the lesson prompt asks for."""
    data = {
        "why": "Every web page starts as HTML.",
        "terms": [{"term": "tag", "def": "A label in angle brackets."}, {"term": "element", "def": "A tag and its content."}],
        "explain": "HTML marks up text as headings and paragraphs.\n\nTags come in pairs.",
        "examples": [
            {"lang": "html", "code": "<h1>Hi</h1>", "output": "A big heading", "note": "h1 is the biggest"},
            {"lang": "html", "code": "<p>Event on Friday</p>", "output": "A paragraph", "note": "For the event page"},
        ],
        "try": {"prompt": "Change the heading to your org's name.", "starter": "<h1>Hi</h1>",
                "answer": "<h1>CompSAt</h1>", "checks": ["Uses h1"]},
        "resources": [{"name": "MDN Web Docs", "role": "primary", "url": "https://developer.mozilla.org/en-US/docs/Web/HTML",
                       "search": "html basics"}],
        "check": [
            {"type": "mc", "skill": "recall", "q": "Which tag is the biggest heading?", "choices": ["h1", "h6"],
             "correct": 0, "why": "h1 is level 1."},
            {"type": "blank", "skill": "apply", "q": "Paragraph text goes inside <___> tags.", "accept": ["p"], "why": "Paragraphs use p."},
            {"type": "self", "skill": "explain", "q": "What does a tag do?", "sample": "It labels content.",
             "why": "Tags give text meaning."},
        ],
    }
    data.update(extra)
    return data


class PromptTests(TestCase):
    def test_prompt_file_has_a_version(self):
        system, version = load_prompt("lesson")
        self.assertEqual(version, load_prompt("lesson")[1])
        self.assertTrue(version.startswith("lesson-"))
        self.assertIn("Return only a JSON object", system)

    def test_system_prompt_is_fixed_and_the_request_is_short(self):
        mine = build_messages(SPEC)[0]
        theirs = build_messages(LessonSpec(key="L9", title="Loops", level="intermediate", taglish=True))[0]
        self.assertEqual(mine[0], theirs[0])
        self.assertIn("Limits: 1 main idea, up to 3 key terms", mine[1]["content"])
        self.assertIn("Earlier lessons: none, this is the first.", mine[1]["content"])
        self.assertIn("up to 5 key terms", theirs[1]["content"])
        self.assertIn("Language: Taglish", theirs[1]["content"])
        self.assertLess(len(mine[1]["content"]), 400)

    def test_recap_and_struggle_change_the_request(self):
        spec = LessonSpec(key="L3", title="Lists", kind="recap", struggled=["indexes start at 0"])
        user = build_messages(spec)[0][1]["content"]
        self.assertIn("This is a recap", user)
        self.assertIn("Struggled with: indexes start at 0. Teach it a different way.", user)


class ParseLessonTests(TestCase):
    def test_a_good_reply_keeps_its_parts(self):
        lesson, repairs, flags = parse_lesson(lesson_reply(), SPEC)
        self.assertEqual((repairs, flags), ([], []))
        self.assertEqual(lesson["lang"], "html")
        self.assertEqual(lesson["explanation"], "HTML marks up text as headings and paragraphs.\n\nTags come in pairs.")
        self.assertEqual([q["type"] for q in lesson["check"]], ["mc", "blank", "self"])
        self.assertEqual(lesson["check"][0]["correct"], 0)
        self.assertEqual(lesson["resources"][0]["role"], "primary")

    def test_code_keeps_its_indentation(self):
        examples = [{"lang": "python", "code": "for x in range(2):\n    print(x)", "output": "0\n1"}]
        task = {"prompt": "Count to 3.", "answer": "for x in range(3):\n    print(x)"}
        lesson, _, flags = parse_lesson(lesson_reply(examples=examples, **{"try": task}), SPEC)
        self.assertEqual(lesson["examples"][0]["code"], "for x in range(2):\n    print(x)")
        self.assertEqual(flags, [])

    def test_invisible_characters_become_spaces_in_text_and_code(self):
        zwsp, nb_hyphen = chr(0x200B), chr(0x2011)
        data = lesson_reply(why=f"Solves the need{zwsp}for a page.", examples=[
            {"lang": "html", "code": f"<!--your{zwsp}code -->\n<title>Clean{nb_hyphen}Up</title>   ", "output": ""}])
        lesson, _, _ = parse_lesson(data, SPEC)
        self.assertEqual(lesson["why"], "Solves the need for a page.")
        self.assertEqual(lesson["examples"][0]["code"], "<!--your code -->\n<title>Clean-Up</title>")

    def test_placeholder_example_is_dropped_and_cannot_relabel_the_lesson(self):
        # Seen live: the model copied "python" from the prompt's shape into an HTML lesson.
        examples = [{"lang": "python", "code": "# hindi applicable sa HTML lesson", "note": "skip"}] + \
            lesson_reply()["examples"]
        lesson, repairs, flags = parse_lesson(lesson_reply(examples=examples), SPEC)
        self.assertEqual(lesson["lang"], "html")
        self.assertEqual(len(lesson["examples"]), 2)
        self.assertIn("Dropped example 1: only comments", repairs)
        self.assertEqual(flags, [])  # the HTML answer is no longer checked as Python

    def test_majority_language_wins(self):
        examples = [{"lang": "css", "code": "h1 { color: red; }"}] + lesson_reply()["examples"]
        lesson, _, _ = parse_lesson(lesson_reply(examples=examples), SPEC)
        self.assertEqual(lesson["lang"], "html")

    def test_real_css_that_starts_like_a_comment_is_kept(self):
        examples = [{"lang": "css", "code": "#header { color: red; }"}, {"lang": "css", "code": ":root { --main: red; }"}]
        lesson, repairs, _ = parse_lesson(lesson_reply(examples=examples), SPEC)
        self.assertEqual(len(lesson["examples"]), 2)
        self.assertEqual(repairs, [])

    def test_missing_space_after_a_full_stop_is_fixed_in_prose_only(self):
        task = {"prompt": "Use a list for the activities.I-save it as page.html, Python 3.13.",
                "answer": "<p>end.Start</p>"}
        lesson, _, _ = parse_lesson(lesson_reply(**{"try": task}), SPEC)
        self.assertEqual(lesson["try_it"]["prompt"], "Use a list for the activities. I-save it as page.html, Python 3.13.")
        self.assertEqual(lesson["try_it"]["sample_answer"], "<p>end.Start</p>")  # code is never changed

    def test_html_tags_the_lesson_never_explains_are_flagged(self):
        # Seen live: a page-structure lesson slipped in <meta charset> without a word about it.
        examples = [{"lang": "html", "code": '<html><head><title>Hi</title><meta charset="UTF-8"></head>'
                                             "<body><h1>Hi</h1><p>Text</p><ul><li>One</li></ul></body></html>"}]
        data = lesson_reply(examples=examples, explain="A page has headings, paragraphs and a list.")
        _, _, flags = parse_lesson(data, SPEC)
        # html/head/body/title are the skeleton; h1, p, ul and li are explained by name.
        self.assertEqual(flags, ["Examples or the task use tags the lesson doesn't explain: <meta>"])

    def test_tags_in_the_task_are_checked_too(self):
        # Seen live: the task asked for a <p> the page-structure lesson never mentioned.
        task = {"prompt": "Make a page.", "answer": "<html><body><p>I love coding.</p></body></html>"}
        data = lesson_reply(**{"try": task}, explain="Every page has a head and a body. Headings name sections.")
        _, _, flags = parse_lesson(data, SPEC)
        self.assertEqual(flags, ["Examples or the task use tags the lesson doesn't explain: <p>"])

    def test_tags_from_earlier_lessons_count_as_explained(self):
        examples = [{"lang": "html", "code": "<form><button>Send</button></form>"}]
        spec = LessonSpec(key="L4", title="Forms", earlier=["Buttons"])
        task = {"prompt": "Add a second button.", "answer": "<form><button>Send</button><button>Clear</button></form>"}
        data = lesson_reply(examples=examples, explain="A form collects answers.", **{"try": task})
        _, _, flags = parse_lesson(data, spec)
        self.assertEqual(flags, [])

    def test_html_tag_answers_accept_both_spellings(self):
        check = [lesson_reply()["check"][0],
                 {"type": "blank", "q": "Heading level 2 ay isusulat bilang ___", "accept": ["<h2>"]},
                 {"type": "blank", "q": "A list item uses the ___ tag", "accept": ["li"]},
                 {"type": "blank", "q": "Paragraph text goes inside <___> tags", "accept": ["p"]},
                 {"type": "blank", "q": "A loop over a list uses ___", "accept": ["for"]}]
        lesson, _, _ = parse_lesson(lesson_reply(check=check), SPEC)
        answers = [q.get("accepted_answers") for q in lesson["check"][1:]]
        self.assertEqual(answers, [["<h2>", "h2"], ["li", "<li>"], ["p"], ["for"]])

    def test_a_blank_that_shows_its_answer_is_flagged(self):
        check = [lesson_reply()["check"][0],
                 {"type": "blank", "q": "To make a main title, use the ___ tag (e.g., <h1>)", "accept": ["h1"]},
                 {"type": "blank", "q": "Headings go from h1 to ___", "accept": ["h6"]}]
        _, _, flags = parse_lesson(lesson_reply(check=check), SPEC)
        self.assertEqual(flags, ["Check 2: the question shows its own answer"])  # h6 isn't shown, so 3 is fine

    def test_extra_key_terms_are_cut_to_the_level(self):
        terms = [{"term": f"t{i}", "def": "d"} for i in range(5)]
        lesson, repairs, _ = parse_lesson(lesson_reply(terms=terms), SPEC)
        self.assertEqual(len(lesson["key_terms"]), 3)
        self.assertIn("5 key terms cut to 3", repairs)

    def test_ungradable_questions_are_dropped(self):
        check = lesson_reply()["check"] + [
            {"type": "mc", "q": "Pick one", "choices": ["a", "a"], "correct": 0},
            {"type": "blank", "q": "No blank here", "accept": ["x"]},
            {"type": "essay", "q": "Write"},
            {"type": "mc", "q": "Past the cap of 6", "choices": ["a", "b"], "correct": 0},
        ]
        lesson, repairs, _ = parse_lesson(lesson_reply(check=check), SPEC)
        self.assertEqual(len(lesson["check"]), 3)
        self.assertEqual(repairs, ["Dropped check question 4: choices or answer unusable",
                                   "Dropped check question 5: no ___ or no accepted answers",
                                   "Dropped check question 6: unknown type 'essay'"])

    def test_wrong_answer_index_is_dropped(self):
        check = lesson_reply()["check"] + [{"type": "mc", "q": "Pick", "choices": ["a", "b"], "correct": 5}]
        _, repairs, _ = parse_lesson(lesson_reply(check=check), SPEC)
        self.assertEqual(repairs, ["Dropped check question 4: choices or answer unusable"])

    def test_fewer_than_two_gradable_questions_is_unusable(self):
        check = [lesson_reply()["check"][0], lesson_reply()["check"][2]]
        lesson, repairs, _ = parse_lesson(lesson_reply(check=check), SPEC)
        self.assertIsNone(lesson)
        self.assertIn("Unusable: missing 2 gradable check questions", repairs)

    def test_missing_example_and_task_are_unusable(self):
        lesson, repairs, _ = parse_lesson(lesson_reply(examples=[], **{"try": {}}), SPEC)
        self.assertIsNone(lesson)
        self.assertEqual(repairs[-1], "Unusable: missing an example, a task")

    def test_long_blank_answers_are_flagged(self):
        check = [lesson_reply()["check"][0],
                 {"type": "blank", "q": "A tag ___", "accept": ["labels the content of a page"]}]
        _, _, flags = parse_lesson(lesson_reply(check=check), SPEC)
        self.assertIn("Check 2: a blank's answer is long, so learners may type it differently", flags)

    def test_invalid_python_is_flagged_not_run(self):
        examples = [{"lang": "python", "code": "print('hi'", "output": "hi"}]
        task = {"prompt": "Print your name.", "answer": "print(name"}
        with mock.patch("builtins.exec") as run:
            lesson, _, flags = parse_lesson(lesson_reply(examples=examples, **{"try": task}), SPEC)
        run.assert_not_called()
        self.assertTrue(lesson)  # Still shown: a person decides.
        self.assertTrue(any(f.startswith("Example 1 is not valid Python") for f in flags))
        self.assertTrue(any(f.startswith("Task answer is not valid Python") for f in flags))

    def test_html_is_not_checked_as_python(self):
        _, _, flags = parse_lesson(lesson_reply(), SPEC)
        self.assertEqual(flags, [])


class ResourceTests(TestCase):
    def test_allowed_list(self):
        self.assertTrue(allowed_link("https://developer.mozilla.org/en-US/docs/Web/HTML"))
        self.assertTrue(allowed_link("https://www.w3schools.com/html/"))
        self.assertTrue(allowed_link("https://docs.python.org/3/tutorial/"))
        self.assertTrue(allowed_link("https://www.kaggle.com/learn/python"))
        self.assertFalse(allowed_link("https://www.kaggle.com/competitions"))
        self.assertFalse(allowed_link("http://developer.mozilla.org/"))  # https only
        self.assertFalse(allowed_link("https://www.youtube.com/watch?v=x"))  # by channel and search phrase only
        self.assertFalse(allowed_link("https://mozilla.org.evil.example/"))
        self.assertFalse(allowed_link("https://made-up-tutorials.com/html"))

    def test_links_off_the_list_become_search_phrases(self):
        resources = [
            {"name": "Some blog", "role": "optional", "url": "https://made-up.com/x", "search": "html tags"},
            {"name": "MDN Web Docs", "role": "optional", "url": "https://fake.example/mdn", "search": "html tags"},
            {"name": "W3Schools", "role": "primary", "url": "", "search": "html intro"},
        ]
        lesson, repairs, _ = parse_lesson(lesson_reply(resources=resources), SPEC)
        blog, mdn, w3 = lesson["resources"]
        self.assertEqual(blog["url"], "")
        self.assertEqual(mdn["url"], "https://developer.mozilla.org/en-US/search?q=html+tags")
        self.assertEqual([x["role"] for x in lesson["resources"]], ["optional", "optional", "primary"])
        self.assertIn("Dropped a link not on the allowed list: made-up.com", repairs)

    def test_no_resources_gets_a_default_by_language(self):
        lesson, repairs, _ = parse_lesson(lesson_reply(resources=[]), SPEC)
        self.assertEqual(lesson["resources"][0]["name"], "MDN Web Docs")
        self.assertEqual(lesson["resources"][0]["role"], "primary")
        self.assertIn("No usable resources; added MDN Web Docs", repairs)


@override_settings(**AI_ON)
class GenerateLessonTests(OutlineContentMixin, TestCase):
    def setUp(self):
        self.make_learner()
        self.profile.hint_style = "example"
        self.profile.save()
        self.outline = PlanOutline.objects.create(
            learner=self.profile, data=parse_outline(outline_reply(), self.profile)[0], prompt_version="outline-2",
        )

    def fake_ask(self, *replies):
        replies = list(replies)

        def ask(messages, max_tokens, usage):
            usage.update(model="openai/gpt-oss-120b", prompt_tokens=500, completion_tokens=1200)
            return replies.pop(0)
        return mock.patch("learning.lessons.ask_model_json", side_effect=ask)

    def test_spec_comes_from_the_outline(self):
        spec = spec_from_outline(self.outline, "L3", struggled=["  linking pages "])
        self.assertEqual((spec.title, spec.minutes, spec.level), ("Links", 25, "beginner"))
        self.assertEqual(spec.earlier, ["Tags", "Headings"])
        self.assertEqual(spec.needs, ["Headings"])
        self.assertEqual(spec.project, "Event page")
        self.assertEqual(spec.tracks, "HTML, CSS")
        self.assertEqual(spec.learns_from, "an example i can learn from")
        self.assertEqual(spec.struggled, ["linking pages"])
        with self.assertRaises(KeyError):
            spec_from_outline(self.outline, "L99")

    def test_first_open_writes_and_saves_then_reuses(self):
        with self.fake_ask(lesson_reply()) as ask:
            first = lesson_for(self.outline, "L1")
            again = lesson_for(self.outline, "L1")
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual((first.version, first.is_current, first.prompt_version), (1, True, load_prompt("lesson")[1]))
        self.assertEqual((first.prompt_tokens, first.completion_tokens), (500, 1200))

    def test_regenerating_keeps_the_old_version(self):
        with self.fake_ask(lesson_reply(), lesson_reply(why="Another way")) as ask:
            lesson_for(self.outline, "L1")
            new = regenerate_lesson(self.outline, "L1", struggled=["closing tags"])
        self.assertIn("Struggled with: closing tags", ask.call_args.args[0][1]["content"])
        versions = list(GeneratedLesson.objects.filter(key="L1").order_by("version").values_list("version", "is_current"))
        self.assertEqual(versions, [(1, False), (2, True)])
        self.assertEqual(lesson_for(self.outline, "L1").pk, new.pk)

    def test_asks_once_more_only_when_unusable(self):
        with self.fake_ask({"why": "no parts"}, lesson_reply()) as ask:
            lesson = lesson_for(self.outline, "L1")
        self.assertEqual(ask.call_count, 2)
        self.assertEqual(lesson.completion_tokens, 2400)
        # The retry, and why the tokens doubled, shows in review.
        self.assertTrue(lesson.repairs[0].startswith("Asked again: the first reply was unusable (Unusable: missing"))

    def test_gives_up_without_saving(self):
        with mock.patch("learning.lessons.ask_model_json", return_value=None) as ask:
            self.assertIsNone(lesson_for(self.outline, "L1"))
        self.assertEqual(ask.call_count, 1)
        self.assertFalse(GeneratedLesson.objects.exists())

    def test_flags_are_saved_and_filterable(self):
        examples = [{"lang": "python", "code": "print(", "output": ""}]
        with self.fake_ask(lesson_reply(examples=examples)):
            lesson = lesson_for(self.outline, "L1")
        self.assertTrue(GeneratedLesson.objects.get(pk=lesson.pk).flagged)

    def test_saving_needs_an_outline(self):
        with self.fake_ask(lesson_reply()), self.assertRaises(ValueError):
            generate_lesson(SPEC)

    def test_glossary_and_warm_up_cost_no_tokens(self):
        with self.fake_ask(lesson_reply(), lesson_reply(terms=[{"term": "Tag", "def": "dup"},
                                                              {"term": "link", "def": "Goes elsewhere."}])):
            lesson_for(self.outline, "L1")
            lesson_for(self.outline, "L2")
        with mock.patch("learning.lessons.ask_model_json") as ask:
            terms = [t["term"] for t in glossary(self.outline)]
            questions = warm_up(self.outline, "L2")
        ask.assert_not_called()
        self.assertEqual(terms, ["tag", "element", "link"])  # in lesson order, no repeats
        self.assertEqual([q["type"] for q in questions], ["mc", "blank"])  # graded ones from L1
        self.assertEqual(warm_up(self.outline, "L1"), [])  # nothing before the first lesson
        self.assertEqual(warm_up(self.outline, "L4"), [])  # L3 not written yet


class LessonAdminTests(OutlineContentMixin, TestCase):
    def setUp(self):
        self.make_learner()
        self.outline = PlanOutline.objects.create(
            learner=self.profile, data=parse_outline(outline_reply(), self.profile)[0], prompt_version="outline-2",
        )
        data = parse_lesson(lesson_reply(), SPEC)[0]
        self.lesson = GeneratedLesson.objects.create(
            outline=self.outline, key="L1", title="Tags", data=data, prompt_version="lesson-1", flags=["Check me"],
        )
        self.admin = get_user_model().objects.create_superuser("curator", "c@example.com", "pw")
        self.client.force_login(self.admin)

    def test_review_page_shows_the_lesson_with_answers(self):
        page = self.client.get(reverse("admin:learning_generatedlesson_change", args=[self.lesson.pk]))
        self.assertContains(page, "Every web page starts as HTML.")
        self.assertContains(page, "&lt;h1&gt;Hi&lt;/h1&gt;")  # code is escaped, never rendered
        self.assertContains(page, "Which tag is the biggest heading? → h1")
        self.assertContains(page, "Check me")

    def test_list_filters_flagged_lessons(self):
        page = self.client.get(reverse("admin:learning_generatedlesson_changelist"), {"flagged__exact": "1"})
        self.assertContains(page, "Tags")

    @override_settings(**AI_ON)
    def test_regenerate_action_makes_a_new_version(self):
        with mock.patch("learning.lessons.ask_model_json", return_value=lesson_reply()):
            self.client.post(reverse("admin:learning_generatedlesson_changelist"),
                             {"action": "regenerate", "_selected_action": [self.lesson.pk]})
        self.assertEqual(GeneratedLesson.objects.get(is_current=True).version, 2)

    def test_regenerate_refuses_too_many_at_once(self):
        for key in ["L2", "L3", "L4", "L5", "L6"]:
            GeneratedLesson.objects.create(outline=self.outline, key=key, title=key, data={}, prompt_version="lesson-1")
        with mock.patch("learning.admin.regenerate_lesson") as regenerate:
            self.client.post(reverse("admin:learning_generatedlesson_changelist"),
                             {"action": "regenerate", "_selected_action": list(
                                 GeneratedLesson.objects.values_list("pk", flat=True))})
        regenerate.assert_not_called()


class DraftLessonCommandTests(OutlineContentMixin, TestCase):
    def setUp(self):
        self.make_learner()

    def test_show_prompt_for_a_typed_in_lesson(self):
        out = StringIO()
        call_command("draft_lesson", "--title", "Lists", "--earlier", "Variables|Loops", "--taglish",
                     "--show-prompt", stdout=out)
        self.assertIn("Earlier lessons: Variables, Loops", out.getvalue())
        self.assertIn("Language: Taglish", out.getvalue())

    @override_settings(**AI_ON)
    def test_raw_shows_hidden_characters_before_cleaning(self):
        out = StringIO()
        reply = lesson_reply(why="lahat ng" + chr(0x200B) + "code")
        with mock.patch("learning.lessons.ask_model_json", return_value=reply):
            call_command("draft_lesson", "--title", "Lists", "--raw", stdout=out)
        self.assertIn("lahat ng\\u200bcode", out.getvalue())  # before checks
        self.assertIn("lahat ng code", out.getvalue())  # after checks

    @override_settings(**AI_ON)
    def test_drafts_from_an_outline_and_saves(self):
        outline = PlanOutline.objects.create(
            learner=self.profile, data=parse_outline(outline_reply(), self.profile)[0], prompt_version="outline-2",
        )
        out = StringIO()
        with mock.patch("learning.lessons.ask_model_json", return_value=lesson_reply()):
            call_command("draft_lesson", "--outline", str(outline.pk), "--lesson", "L2", "--save", stdout=out)
        self.assertIn("saved as version 1", out.getvalue())
        self.assertEqual(GeneratedLesson.objects.get().title, "Headings")
