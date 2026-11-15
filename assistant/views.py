import json

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from accounts.models import get_profile
from content.models import QuizItem, Topic
from learning import ai_plan

from .models import HelpFeedback
from .service import (
    ACTIONS, LANGUAGE_RULES, MAX_CODE_LENGTH, MAX_ERROR_LENGTH, HelpRequest, ask as ask_service, remaining_today,
)

MAX_QUESTION_LENGTH = 500


def _no_topic_reply(learner, hint_level):
    return JsonResponse({
        "mode": "fallback",
        "reply": "Open a topic first, then ask your question.",
        "hint_level": hint_level,
        "remaining_today": remaining_today(learner),
        "tips": [],
        "resources": [],
    })


@require_POST
def ask(request):
    """POST JSON {topic or lesson, question, hint_level, screen, quiz_item_id, learner_answer,
    action, code, error, language}. Always 200.

    Every field is checked here: unknown actions become "hint", text is cut to its limit, and a
    language that isn't offered is ignored. A valid language is saved as the learner's choice.

    `topic` is a curated topic's slug; `lesson` is a lesson key of the learner's AI plan, and then
    `quiz_item_id` is the number of a question in that lesson's check.
    """
    learner = get_profile(request.user)
    try:
        data = json.loads(request.body or b"{}")
        if not isinstance(data, dict):
            raise ValueError
    except ValueError:
        data = {}

    try:
        hint_level = min(max(int(data.get("hint_level") or 1), 1), 3)
    except (TypeError, ValueError):
        hint_level = 1

    screen = "quiz" if data.get("screen") == "quiz" else str(data.get("screen") or "plan")[:20]
    item_id = str(data.get("quiz_item_id") or "")
    quiz_item = None
    lesson_key = str(data.get("lesson") or "")[:10]
    if lesson_key:
        # An AI-written lesson: only from the learner's own active plan.
        outline = ai_plan.active_outline(learner)
        topic = ai_plan.help_topic(outline, lesson_key) if outline else None
        if topic is not None and screen == "quiz" and item_id.isdigit():
            quiz_item = ai_plan.help_question(outline, lesson_key, int(item_id))
    else:
        topic = Topic.objects.select_related("track").filter(
            slug=str(data.get("topic") or ""), track__is_active=True
        ).first()
        if topic is not None and screen == "quiz" and item_id.isdigit():
            quiz_item = QuizItem.objects.filter(pk=int(item_id), topic=topic).first()
    if topic is None:
        return _no_topic_reply(learner, hint_level)

    action = str(data.get("action") or "hint")
    if action not in ACTIONS:
        action = "hint"
    language = str(data.get("language") or learner.explain_language)
    if language not in LANGUAGE_RULES:
        language = ""
    if "language" in data and language != learner.explain_language:
        learner.explain_language = language
        learner.save(update_fields=["explain_language"])

    help_request = HelpRequest(
        topic=topic,
        question=str(data.get("question") or "").strip()[:MAX_QUESTION_LENGTH] or "I'm stuck. Where do I start?",
        hint_level=hint_level,
        screen=screen,
        quiz_item=quiz_item,
        learner_answer=str(data.get("learner_answer") or "")[:MAX_QUESTION_LENGTH],
        hint_style=learner.hint_style,
        action=action,
        code=str(data.get("code") or "")[:MAX_CODE_LENGTH],
        error=str(data.get("error") or "")[:MAX_ERROR_LENGTH],
        language=language,
        experience=learner.experience,
    )
    return JsonResponse(ask_service(learner, help_request).as_dict())


@require_POST
def feedback(request):
    """POST JSON {where, action, mode, rating (1, -1, or 0 to report), note}. Stores no question or reply text."""
    learner = get_profile(request.user)
    try:
        data = json.loads(request.body or b"{}")
        rating = int(data.get("rating"))
        if not isinstance(data, dict) or rating not in (1, -1, 0):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        return JsonResponse({"ok": False}, status=400)
    note = " ".join(str(data.get("note") or "").split())[:500]
    if rating == 0 and not note:
        return JsonResponse({"ok": False, "error": "Say what went wrong."}, status=400)
    action = str(data.get("action") or "hint")
    HelpFeedback.objects.create(
        learner=learner,
        where=str(data.get("where") or "")[:210],
        action=action if action in ACTIONS else "hint",
        mode="ai" if data.get("mode") == "ai" else "fallback",
        rating=rating,
        note=note,
    )
    return JsonResponse({"ok": True})
