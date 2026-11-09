"""AI hint service.

Grounded only in the current topic's tips and resource titles. Hints step up
through three levels and never give full solutions. Groq is tried first, then
Cloudflare Workers AI. When the daily cap is hit or both providers fail, the
learner gets the topic's tips and links instead, so the app works with the AI off.

Never sent to the model: accepted quiz answers, names, emails.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from openai import OpenAI, RateLimitError

from .models import AIUsage

logger = logging.getLogger(__name__)

MAX_TOKENS = 300
TIMEOUT_SECONDS = 20  # One hint call.
# Plans and lessons run inside a page request, which the server ends after 60 seconds
# (gunicorn.conf.py). All their AI calls together get a budget below that: each call waits at
# most the time left, and no new call starts without enough time to finish.
MIN_CALL_SECONDS = 8
# A rate-limited request is retried once if the provider asks us to wait this long or less.
# Longer waits would hold the page too long, so the next model is tried instead.
MAX_RETRY_WAIT_SECONDS = 3

HINT_STYLES = {
    "think": "They like hints that make them think, so lean on questions.",
    "explain": "They like clear explanations, so be plain and direct about the concept.",
    "example": "They learn from examples, so include a short, different example when you can.",
}

LANGUAGE_RULES = (
    "- Match the learner's language. If their message has any Tagalog words, reply in Taglish\n"
    "  (everyday Tagalog mixed with English, the way they wrote). Otherwise reply in English.\n"
    "- Plain text only: no markdown, no backticks, no asterisks, no headings."
)

# Common Tagalog words. Two or more in a message means the learner wrote in Taglish.
TAGALOG_WORDS = {
    "ako", "ano", "bakit", "ba", "di", "hindi", "ito", "iyan", "kasi", "ko", "lang", "mo", "naman",
    "nga", "paano", "po", "sa", "siya", "talaga", "tapos", "wala", "yung", "kung", "pero", "gawin",
}


def language_note(text):
    """An explicit instruction when the learner wrote in Taglish; models often reply in English otherwise."""
    words = set(re.findall(r"[a-z]+", text.lower()))
    if len(words & TAGALOG_WORDS) >= 2:
        return "\n\n(I wrote in Taglish. Please reply in Taglish too.)"
    return ""


HINT_LEVELS = {
    1: "Ask one guiding question that points the learner toward the idea they are missing.",
    2: "Explain the concept the learner needs, in plain words, without solving their problem.",
    3: "Show a short, similar but different example, then let the learner apply it themselves.",
}


@dataclass
class Provider:
    name: str
    api_key: str
    base_url: str
    model: str


def providers(purpose="hint"):
    """Configured providers in the order they are tried. Missing keys mean the provider is off.

    Hints use a small fast model; planning (intake, tailoring) uses a larger one.
    On Groq the two models also have separate rate limits, which spreads the free quota,
    so planning falls back to the small model when the large one is busy.
    """
    result = []
    if settings.GROQ_API_KEY:
        groq = "https://api.groq.com/openai/v1"
        models = [settings.GROQ_MODEL]
        if purpose == "plan" and settings.GROQ_PLAN_MODEL != settings.GROQ_MODEL:
            models = [settings.GROQ_PLAN_MODEL, settings.GROQ_MODEL]
        result.extend(Provider("groq", settings.GROQ_API_KEY, groq, model) for model in models)
    if settings.CF_ACCOUNT_ID and settings.CF_API_TOKEN:
        result.append(Provider(
            "cloudflare", settings.CF_API_TOKEN,
            f"https://api.cloudflare.com/client/v4/accounts/{settings.CF_ACCOUNT_ID}/ai/v1",
            settings.CF_MODEL,
        ))
    return result


@dataclass
class HelpRequest:
    topic: object
    question: str
    hint_level: int = 1
    screen: str = "plan"
    quiz_item: object = None
    learner_answer: str = ""
    hint_style: str = ""  # LearnerProfile.HintStyle value: what helps this learner when stuck.


@dataclass
class HelpReply:
    mode: str
    reply: str
    hint_level: int
    remaining_today: int
    tips: list = field(default_factory=list)
    resources: list = field(default_factory=list)

    def as_dict(self):
        return {
            "mode": self.mode,
            "reply": self.reply,
            "hint_level": self.hint_level,
            "remaining_today": self.remaining_today,
            "tips": self.tips,
            "resources": self.resources,
        }


def topic_tips(topic):
    return [tip.text for tip in topic.tips.all()]


def topic_resources(topic):
    return [{"title": r.title, "url": r.url} for r in topic.resources.filter(is_active=True)]


def build_messages(request):
    """The chat messages sent to the model. Only topic content and the learner's own words."""
    topic = request.topic
    tips = "\n".join(f"- {t}" for t in topic_tips(topic)) or "- (none)"
    resources = "\n".join(f"- {r['title']}" for r in topic_resources(topic)) or "- (none)"
    style = f"- {HINT_STYLES[request.hint_style]} Still follow the hint level.\n" if request.hint_style in HINT_STYLES else ""
    system = (
        "You are a patient tutor helping a beginner programmer.\n"
        f"Topic: {topic.title} ({topic.track.name}).\n"
        f"Topic summary: {topic.summary or '(none)'}\n"
        f"Tips from our team:\n{tips}\n"
        f"Resources the learner has:\n{resources}\n\n"
        "Rules:\n"
        "- Stay on this topic. Use only the ideas above and basic programming knowledge.\n"
        "- Never give the full solution or the exact answer to a quiz blank.\n"
        f"- This is hint level {request.hint_level} of 3. {HINT_LEVELS[request.hint_level]}\n"
        f"{style}"
        "- Keep the reply under 120 words.\n"
        "- If the question is not about programming, gently steer back to the topic.\n"
        f"{LANGUAGE_RULES}"
    )
    user = f"My question: {request.question}{language_note(request.question)}"
    if request.screen == "quiz" and request.quiz_item is not None:
        # The prompt only. accepted_answers never leave the server.
        user = (
            f"I'm on this quiz blank: {request.quiz_item.prompt}\n"
            f"My answer so far: {request.learner_answer or '(blank)'}\n{user}"
        )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def call_provider(provider, messages, max_tokens=MAX_TOKENS, json_mode=False, reasoning="low", usage=None,
                  timeout=TIMEOUT_SECONDS):
    """One chat call. With `usage` (a dict), records the model and token counts there."""
    client = OpenAI(api_key=provider.api_key, base_url=provider.base_url,
                    timeout=timeout, max_retries=0)
    extra = {}
    # gpt-oss models think before answering; keep that short so it fits in max_tokens.
    if provider.model.startswith("openai/gpt-oss"):
        extra["reasoning_effort"] = reasoning
    if json_mode and provider.name == "groq":
        extra["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(
        model=provider.model, messages=messages, max_tokens=max_tokens, temperature=0.4, **extra,
    )
    if usage is not None:
        counts = getattr(response, "usage", None)
        usage.update(
            model=provider.model,
            prompt_tokens=getattr(counts, "prompt_tokens", None),
            completion_tokens=getattr(counts, "completion_tokens", None),
        )
    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise ValueError("empty reply")
    return text


def _retry_after(error):
    """Seconds the provider asked us to wait after a rate limit, or None if not given."""
    response = getattr(error, "response", None)
    try:
        return float(response.headers.get("retry-after"))
    except (AttributeError, TypeError, ValueError):
        return None


def call_with_retry(provider, messages, deadline=None, **kwargs):
    """call_provider, retried once after a short rate-limit wait (only if the deadline allows it)."""
    try:
        return call_provider(provider, messages, **kwargs)
    except RateLimitError as error:
        wait = _retry_after(error)
        if wait is None or wait > MAX_RETRY_WAIT_SECONDS:
            raise
        if deadline is not None and deadline - time.monotonic() - wait < MIN_CALL_SECONDS:
            raise
        time.sleep(wait)
        if deadline is not None:
            kwargs["timeout"] = min(kwargs.get("timeout", TIMEOUT_SECONDS), deadline - time.monotonic())
        return call_provider(provider, messages, **kwargs)


def clean_reply(text):
    """Strip markdown the page would show as raw symbols: backticks, bold stars, heading marks."""
    text = re.sub(r"`+", "", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    return re.sub(r"(?m)^#+\s*", "", text).strip()


def ask_model(messages):
    """Try each provider in order. Returns the cleaned reply text, or None if all fail."""
    for provider in providers():
        try:
            return clean_reply(call_with_retry(provider, messages))
        except Exception:  # Any provider error means "try the next one".
            logger.warning("AI provider %s failed", provider.name, exc_info=True)
    return None


def parse_json_object(text):
    """Parse a JSON object from a model reply, tolerating code fences or text around it."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("reply is not a JSON object")
    return data


def _failed_generation(error):
    """The text a model produced when Groq rejected it as invalid JSON, if any."""
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        details = body.get("error", body)
        if isinstance(details, dict):
            return str(details.get("failed_generation") or "")
    return ""


def ask_model_json(messages, max_tokens=1500, text_ok=False, usage=None, deadline=None):
    """Like ask_model, but with the planning model and a parsed JSON object back.

    A provider that replies with broken JSON counts as failed, so the next one is tried.
    With `text_ok`, a plain-text reply is returned as {"reply": text} instead (used by
    the intake chat, where a plain follow-up question is still useful).
    With `usage` (a dict), records the model and token counts of the call that answered.
    `deadline` (a time.monotonic() value) bounds all the calls; without one, they get
    AI_REQUEST_BUDGET seconds from now. A provider is skipped once too little time is left.
    Returns None if all fail.
    """
    if deadline is None:
        deadline = time.monotonic() + settings.AI_REQUEST_BUDGET
    for provider in providers(purpose="plan"):
        left = deadline - time.monotonic()
        if left < MIN_CALL_SECONDS:
            logger.warning("AI time budget used up before trying %s (%s)", provider.name, provider.model)
            break
        try:
            text = call_with_retry(provider, messages, max_tokens=max_tokens, json_mode=True, usage=usage,
                                   timeout=min(settings.AI_PLAN_CALL_TIMEOUT, left), deadline=deadline)
        except Exception as error:
            text = _failed_generation(error)
            if not text:
                logger.warning("AI provider %s (%s) failed (json)", provider.name, provider.model, exc_info=True)
                continue
        try:
            return parse_json_object(text)
        except ValueError:
            if text_ok and text.strip() and "{" not in text:
                return {"reply": text.strip(), "done": False, "profile": None}
            logger.warning("AI provider %s (%s) returned unusable JSON", provider.name, provider.model)
    return None


def ai_available():
    return bool(providers())


def daily_limit():
    return settings.AI_DAILY_LIMIT


def remaining_today(learner):
    usage = AIUsage.objects.filter(learner=learner, date=timezone.localdate()).first()
    return max(daily_limit() - (usage.messages_used if usage else 0), 0)


def reserve_message(learner):
    """Count one message against today's cap. Returns False if the cap is already reached."""
    with transaction.atomic():
        usage, _ = AIUsage.objects.get_or_create(learner=learner, date=timezone.localdate())
        usage = AIUsage.objects.select_for_update().get(pk=usage.pk)
        if usage.messages_used >= daily_limit():
            return False
        usage.messages_used = F("messages_used") + 1
        usage.save(update_fields=["messages_used"])
    return True


def release_message(learner):
    """Give back a reserved message when no provider answered."""
    AIUsage.objects.filter(
        learner=learner, date=timezone.localdate(), messages_used__gt=0
    ).update(messages_used=F("messages_used") - 1)


def reserve_intake(learner):
    """Count one plan conversation against today's cap. Returns False if the cap is reached."""
    with transaction.atomic():
        usage, _ = AIUsage.objects.get_or_create(learner=learner, date=timezone.localdate())
        usage = AIUsage.objects.select_for_update().get(pk=usage.pk)
        if usage.intakes_used >= settings.AI_INTAKE_DAILY_LIMIT:
            return False
        usage.intakes_used = F("intakes_used") + 1
        usage.save(update_fields=["intakes_used"])
    return True


def reserve_lesson(learner):
    """Count one AI-written lesson against today's cap. Returns False if the cap is reached."""
    with transaction.atomic():
        usage, _ = AIUsage.objects.get_or_create(learner=learner, date=timezone.localdate())
        usage = AIUsage.objects.select_for_update().get(pk=usage.pk)
        if usage.lessons_used >= settings.AI_LESSON_DAILY_LIMIT:
            return False
        usage.lessons_used = F("lessons_used") + 1
        usage.save(update_fields=["lessons_used"])
    return True


def release_lesson(learner):
    """Give back a reserved lesson when the AI couldn't write it."""
    AIUsage.objects.filter(
        learner=learner, date=timezone.localdate(), lessons_used__gt=0
    ).update(lessons_used=F("lessons_used") - 1)


def lessons_left_today(learner):
    usage = AIUsage.objects.filter(learner=learner, date=timezone.localdate()).first()
    return max(settings.AI_LESSON_DAILY_LIMIT - (usage.lessons_used if usage else 0), 0)


def intakes_left_today(learner):
    usage = AIUsage.objects.filter(learner=learner, date=timezone.localdate()).first()
    return max(settings.AI_INTAKE_DAILY_LIMIT - (usage.intakes_used if usage else 0), 0)


def fallback(request, learner, reason):
    reply = reason
    if request.screen == "quiz" and request.quiz_item is not None and request.quiz_item.hint:
        reply = f"{reason} Hint for this blank: {request.quiz_item.hint}"
    return HelpReply(
        mode="fallback",
        reply=reply,
        hint_level=request.hint_level,
        remaining_today=remaining_today(learner),
        tips=topic_tips(request.topic),
        resources=topic_resources(request.topic),
    )


@dataclass
class PracticeFeedback:
    mode: str  # "ai" or "fallback"
    text: str


def build_practice_messages(task, answer, hint_style=""):
    """Feedback on a practice answer. The task and its checklist only: the sample answer never leaves."""
    topic = task.topic
    checks = "\n".join(f"- {c}" for c in task.checklist) or "- (none)"
    style = f"- {HINT_STYLES[hint_style]}\n" if hint_style in HINT_STYLES else ""
    system = (
        "You are a patient tutor giving feedback on a beginner programmer's practice answer.\n"
        f"Topic: {topic.title} ({topic.track.name}).\n"
        f"The task: {task.prompt}\n"
        f"A good answer:\n{checks}\n\n"
        "Rules:\n"
        "- First look for bugs that break the program: a loop that never stops, an error it would\n"
        "  raise, or wrong output. Mention those before anything else.\n"
        "- Say one thing they did well, if anything.\n"
        "- Then give at most 3 short hints, each pointing at a line or idea in their answer and\n"
        "  asking what it does, so they find the fix themselves.\n"
        "- Never write code: not the corrected code, not a fixed line, not a call with the right\n"
        "  arguments. Describe the idea in words instead.\n"
        "- If it already meets every check, say so and suggest one small way to stretch it.\n"
        f"{style}"
        "- Keep it under 120 words.\n"
        f"{LANGUAGE_RULES}"
    )
    user = f"My answer:\n{answer}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def practice_feedback(learner, task, answer):
    """AI hints on a practice answer, counted against the daily cap; the checklist when AI is unavailable."""
    if not providers():
        return PracticeFeedback("fallback", "The AI helper is off right now. Check your answer against the list below.")
    if not reserve_message(learner):
        return PracticeFeedback("fallback", "You've used all your AI messages for today. Check your answer against the list below; they reset tomorrow.")
    text = ask_model(build_practice_messages(task, answer, learner.hint_style))
    if text is None:
        release_message(learner)
        return PracticeFeedback("fallback", "The AI helper is busy right now. Check your answer against the list below.")
    return PracticeFeedback("ai", text)


def ask(learner, request):
    """Answer a help request with an AI hint, or fall back to the topic's tips and links."""
    if not providers():
        return fallback(request, learner, "The AI helper is off right now. These tips and links should help.")
    if not reserve_message(learner):
        return fallback(request, learner, "You've used all your AI messages for today. These tips and links should help.")

    text = ask_model(build_messages(request))
    if text is None:
        release_message(learner)
        return fallback(request, learner, "The AI helper is busy right now. These tips and links should help.")

    return HelpReply(
        mode="ai",
        reply=text,
        hint_level=request.hint_level,
        remaining_today=remaining_today(learner),
        tips=topic_tips(request.topic),
        resources=topic_resources(request.topic),
    )
