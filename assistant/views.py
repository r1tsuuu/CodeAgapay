import json

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from accounts.models import get_profile
from content.models import QuizItem, Topic
from learning import ai_plan

from .service import HelpRequest, ask as ask_service, remaining_today

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
    """POST JSON {topic or lesson, question, hint_level, screen, quiz_item_id, learner_answer}. Always 200.

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

    help_request = HelpRequest(
        topic=topic,
        question=str(data.get("question") or "").strip()[:MAX_QUESTION_LENGTH] or "I'm stuck. Where do I start?",
        hint_level=hint_level,
        screen=screen,
        quiz_item=quiz_item,
        learner_answer=str(data.get("learner_answer") or "")[:MAX_QUESTION_LENGTH],
        hint_style=learner.hint_style,
    )
    return JsonResponse(ask_service(learner, help_request).as_dict())


@staff_member_required
def test_page(request):
    """A bare page for trying the AI service before the help panel (M8) exists."""
    topics = Topic.objects.filter(track__is_active=True).select_related("track")
    return render(request, "assistant/test_page.html", {"topics": topics})
