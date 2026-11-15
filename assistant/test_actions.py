"""Agapay's focused actions, explanation language, bounded context, fallbacks and feedback."""

import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import get_profile
from content.models import QuizItem, Tip, Topic, Track

from . import service
from .models import AIUsage, HelpFeedback


@override_settings(GROQ_API_KEY="test", AI_DAILY_LIMIT=5)
class ActionTests(TestCase):
    def setUp(self):
        track = Track.objects.create(name="Python", slug="python")
        self.topic = Topic.objects.create(track=track, title="Loops", slug="loops", summary="Repeat things.")
        Tip.objects.create(topic=self.topic, text="Count where range starts.")
        self.item = QuizItem.objects.create(topic=self.topic, prompt="for i in ___(5):", accepted_answers=["range"])
        self.user = get_user_model().objects.create_user("ana", "ana@example.com", first_name="Ana")
        self.profile = get_profile(self.user)
        self.profile.experience = "none"
        self.profile.save()
        self.client.force_login(self.user)

    def post(self, payload):
        payload = {"topic": "loops", **payload}
        return self.client.post(reverse("help_ask"), json.dumps(payload), content_type="application/json")

    def sent(self, call):
        return "\n".join(m["content"] for m in call.call_args[0][1])

    @mock.patch("assistant.service.call_provider", return_value="Look at line 1.")
    def test_debug_sends_code_and_error_within_limits(self, call):
        data = self.post({"action": "debug", "question": "why", "code": "x" * 5000, "error": "E" * 900}).json()
        self.assertEqual(data["action"], "debug")
        prompt = self.sent(call)
        self.assertIn("x" * service.MAX_CODE_LENGTH, prompt)
        self.assertNotIn("x" * (service.MAX_CODE_LENGTH + 1), prompt)
        self.assertNotIn("E" * (service.MAX_ERROR_LENGTH + 1), prompt)
        self.assertIn("Don't write the fixed code", prompt)

    @mock.patch("assistant.service.call_provider", return_value="ok")
    def test_context_is_bounded_to_topic_level_and_language(self, call):
        self.post({"action": "explain", "question": "what is a loop", "language": "fil"})
        prompt = self.sent(call)
        self.assertIn("Loops", prompt)
        self.assertIn("never coded before", prompt)
        self.assertIn("Reply in Filipino", prompt)
        self.assertIn("sari-sari store", prompt)
        for private in ("ana@example.com", "Ana", "range"):  # identity and the quiz answer
            self.assertNotIn(private, prompt.replace("range starts", ""))

    @mock.patch("assistant.service.call_provider", return_value="ok")
    def test_chosen_language_is_saved_and_reused(self, call):
        self.post({"question": "hi", "language": "taglish"})
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.explain_language, "taglish")
        self.post({"question": "again"})
        self.assertIn("Reply in Taglish", self.sent(call))

    @mock.patch("assistant.service.call_provider", return_value="ok")
    def test_unknown_action_and_language_are_ignored(self, call):
        data = self.post({"action": "rm -rf", "question": "hi", "language": "klingon"}).json()
        self.assertEqual(data["action"], "hint")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.explain_language, "")

    @mock.patch("assistant.service.call_provider", return_value="ok")
    def test_hints_never_give_the_solution(self, call):
        self.post({"question": "stuck", "hint_level": 3})
        self.assertIn("Never give the full solution", self.sent(call))

    @mock.patch("assistant.service.call_provider", return_value="Step 1 ...")
    def test_solution_only_when_asked_and_never_on_a_quiz(self, call):
        self.post({"action": "solution", "question": "print 1 to 5"})
        self.assertIn("explicitly asked for the full solution", self.sent(call))
        data = self.post({"action": "solution", "screen": "quiz", "quiz_item_id": self.item.pk, "question": "?"}).json()
        self.assertEqual((data["action"], data["hint_level"]), ("hint", 3))
        self.assertIn("Never give the full solution", self.sent(call))

    @mock.patch("assistant.service.call_provider", return_value="ok")
    def test_every_action_counts_against_the_daily_cap(self, call):
        for action in ("hint", "explain", "debug", "check", "breakdown"):
            self.post({"action": action, "question": "q"})
        self.assertEqual(AIUsage.objects.get(learner=self.profile).messages_used, 5)
        data = self.post({"action": "explain", "question": "q"}).json()
        self.assertEqual(data["mode"], "fallback")
        self.assertEqual(call.call_count, 5)

    @mock.patch("assistant.service.call_provider", side_effect=RuntimeError("down"))
    def test_provider_failure_gives_the_actions_curated_prompt(self, call):
        with self.assertLogs("assistant.service", "WARNING"):
            data = self.post({"action": "debug", "question": "q"}).json()
        self.assertEqual(data["mode"], "fallback")
        self.assertIn("Read the last line of the error", data["reply"])
        self.assertEqual(data["tips"], ["Count where range starts."])
        self.assertEqual(AIUsage.objects.get(learner=self.profile).messages_used, 0)

    def test_feedback_is_saved_without_question_text(self):
        url = reverse("help_feedback")
        ok = self.client.post(url, json.dumps({"where": "loops", "action": "hint", "mode": "ai", "rating": -1}),
                              content_type="application/json")
        self.assertEqual(ok.json(), {"ok": True})
        self.client.post(url, json.dumps({"where": "loops", "action": "x", "mode": "ai", "rating": 0, "note": " wrong  answer "}),
                         content_type="application/json")
        report = HelpFeedback.objects.get(rating=0)
        self.assertEqual((report.note, report.action, report.learner), ("wrong answer", "hint", self.profile))
        empty = self.client.post(url, json.dumps({"rating": 0}), content_type="application/json")
        self.assertEqual(empty.status_code, 400)
        bad = self.client.post(url, json.dumps({"rating": 7}), content_type="application/json")
        self.assertEqual(bad.status_code, 400)

    def test_panel_offers_actions_and_plan_changes_need_a_button(self):
        response = self.client.get(reverse("lesson", args=["loops"]))
        for label in ("Explain this concept", "Give me a hint", "Help me debug", "Check my understanding",
                      "Break this task down"):
            self.assertContains(response, label)


class LocalProviderTests(TestCase):
    """An optional model on this machine (Ollama, LM Studio), tried after Groq and Cloudflare."""

    def test_off_unless_configured(self):
        self.assertNotIn("local", [p.name for p in service.providers()])

    @override_settings(GROQ_API_KEY="g", LOCAL_AI_URL="http://localhost:11434/v1/", LOCAL_AI_MODEL="qwen2.5:7b",
                       LOCAL_AI_TIMEOUT=45)
    def test_tried_last_with_its_own_timeout(self):
        order = service.providers()
        self.assertEqual(order[-1].name, "local")
        self.assertEqual(order[-1].base_url, "http://localhost:11434/v1")
        self.assertEqual(order[-1].timeout, 45)
        self.assertEqual(order[-1].api_key, "local")

    @override_settings(GROQ_API_KEY="g", LOCAL_AI_URL="http://localhost:11434/v1", LOCAL_AI_MODEL="qwen2.5:7b")
    def test_answers_when_groq_fails(self):
        def call(provider, messages, **kwargs):
            if provider.name == "groq":
                raise RuntimeError("quota")
            self.assertEqual(kwargs["timeout"], provider.timeout)
            return "A local hint."

        with mock.patch("assistant.service.call_provider", side_effect=call), \
                self.assertLogs("assistant.service", "WARNING"):
            self.assertEqual(service.ask_model([{"role": "user", "content": "hi"}]), "A local hint.")

    @override_settings(LOCAL_AI_URL="http://localhost:11434/v1", LOCAL_AI_MODEL="qwen2.5:7b")
    def test_local_only_still_counts_against_the_daily_cap(self):
        profile = get_profile(get_user_model().objects.create_user("ben"))
        with override_settings(AI_DAILY_LIMIT=1), \
                mock.patch("assistant.service.call_provider", return_value="hint"):
            track = Track.objects.create(name="Python", slug="py")
            topic = Topic.objects.create(track=track, title="Loops", slug="py-loops")
            first = service.ask(profile, service.HelpRequest(topic=topic, question="?"))
            second = service.ask(profile, service.HelpRequest(topic=topic, question="?"))
        self.assertEqual((first.mode, second.mode), ("ai", "fallback"))
