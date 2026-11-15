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
from types import SimpleNamespace

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

# Only the help panel (Need help) may answer in Taglish; lessons, plans and feedback are in English.
HELP_LANGUAGE_RULES = (
    "- Match the learner's language. If their message has any Tagalog words, reply in Taglish\n"
    "  (everyday Tagalog mixed with English, the way they wrote). Otherwise reply in English.\n"
    "- Plain text only: no markdown, no backticks, no asterisks, no headings."
)
ENGLISH_RULES = (
    "- Reply in plain English, even if the learner wrote in Taglish or Tagalog.\n"
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
    1: "Give a direction: one guiding question that points the learner toward the idea they are missing.",
    2: "Give a strategy: the approach or concept they need, in plain words, without solving their problem.",
    3: "Give a worked pattern: a short, similar but different example, then let them apply it themselves.",
}

# What the learner asked Agapay to do (the panel's buttons). "hint" steps through HINT_LEVELS.
# "Adjust my plan" and "Suggest a next project" are not here: the panel answers them from the
# plan and the curated project ideas, with no AI, and plan changes need the learner to confirm.
ACTIONS = {
    "hint": None,
    "explain": "Explain the concept they ask about in plain words, with one tiny example. Don't solve their task.",
    "debug": (
        "Help them debug. Read their code and error, say in words where to look and why, and ask what they "
        "expect that line to do. Don't write the fixed code."
    ),
    "check": (
        "Check their understanding: ask one short question about this topic, wait for their answer, and "
        "don't give the answer in the same message."
    ),
    "breakdown": "Break their task into 3 to 5 small steps they can do in order. Describe each step; don't write the code.",
    "solution": (
        "They explicitly asked for the full solution after trying the hints. Explain a complete solution step "
        "by step, saying why each part works, so they understand it rather than copy it."
    ),
}
ACTION_LABELS = {
    "hint": "Hint", "explain": "Explanation", "debug": "Debugging help", "check": "Check your understanding",
    "breakdown": "Steps", "solution": "Worked solution",
}

# Fallbacks when the AI is off, busy or out of messages: curated troubleshooting prompts per action.
FALLBACK_PROMPTS = {
    "hint": "Reread the task and say out loud what it asks for. Which part do you already know how to do?",
    "explain": "Open the first resource below and find the topic's key words. Try writing each one in your own words.",
    "debug": (
        "Read the last line of the error first: it names the problem. Then find the line number it points to, "
        "and check that line and the one above it for a missing bracket, colon, quote or typo."
    ),
    "check": "Close the resources and try to write a tiny example of this topic from memory. Then compare.",
    "breakdown": (
        "Write the task as a list: what goes in, what should come out, and the steps in between. "
        "Do the smallest step first and run it before adding the next."
    ),
    "solution": "Look at the worked examples in the resources below; they show the full pattern step by step.",
}

# How Agapay explains (LearnerProfile.explain_language). Blank: match the learner's message.
LANGUAGE_RULES = {
    "en": "- Reply in plain English.",
    "fil": "- Reply in Filipino (Tagalog). Keep code and technical words like loop or variable in English.",
    "taglish": "- Reply in Taglish: everyday Tagalog mixed with English, the way Filipino students talk.",
}
LOCAL_EXAMPLES = (
    "- When you give an example, use everyday Filipino contexts when they fit: a student org's members, "
    "a barangay event sign-up, a sari-sari store's stock, a class survey."
)
EXPERIENCE_NOTES = {
    "none": "They have never coded before.",
    "a_little": "They have followed tutorials or a class.",
    "comfortable": "They have built something small on their own.",
}
MAX_CODE_LENGTH = 2000
MAX_ERROR_LENGTH = 500


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
class StudyTopic:
    """What the learner is studying when it isn't a curated Topic: an AI-written lesson.

    Hints are grounded in the lesson's own content (notes), the same way curated hints use
    the topic's summary and tips.
    """

    title: str
    language: str
    summary: str = ""
    notes: str = ""  # Key terms and the start of the explanation.
    help_tips: list = field(default_factory=list)
    help_resources: list = field(default_factory=list)  # [{"title": ..., "url": ...}]

    @property
    def track(self):
        return SimpleNamespace(name=self.language)


@dataclass
class HelpRequest:
    topic: object
    question: str
    hint_level: int = 1
    screen: str = "plan"
    quiz_item: object = None
    learner_answer: str = ""
    hint_style: str = ""  # LearnerProfile.HintStyle value: what helps this learner when stuck.
    action: str = "hint"  # A key of ACTIONS.
    code: str = ""  # Their code, for debugging (at most MAX_CODE_LENGTH).
    error: str = ""  # The error message they got (at most MAX_ERROR_LENGTH).
    language: str = ""  # LearnerProfile.ExplainLanguage value, or blank to match their message.
    experience: str = ""  # LearnerProfile.Experience value.


@dataclass
class HelpReply:
    mode: str
    reply: str
    hint_level: int
    remaining_today: int
    tips: list = field(default_factory=list)
    resources: list = field(default_factory=list)
    action: str = "hint"

    def as_dict(self):
        return {
            "action": self.action,
            "mode": self.mode,
            "reply": self.reply,
            "hint_level": self.hint_level,
            "remaining_today": self.remaining_today,
            "tips": self.tips,
            "resources": self.resources,
        }


def topic_tips(topic):
    if isinstance(topic, StudyTopic):
        return list(topic.help_tips)
    return [tip.text for tip in topic.tips.all()]


def topic_resources(topic):
    if isinstance(topic, StudyTopic):
        return list(topic.help_resources)
    return [{"title": r.title, "url": r.url} for r in topic.resources.filter(is_active=True)]


def build_messages(request):
    """The chat messages sent to the model.

    Bounded on purpose: the topic or lesson, the learner's level and language, their question, and
    optionally their code, error or quiz answer. No name, email, account history or quiz answers.
    """
    topic = request.topic
    tips = "\n".join(f"- {t}" for t in topic_tips(topic)) or "- (none)"
    resources = "\n".join(f"- {r['title']}" for r in topic_resources(topic)) or "- (none)"
    style = f"- {HINT_STYLES[request.hint_style]} Still follow the hint level.\n" if request.hint_style in HINT_STYLES else ""
    # An AI-written lesson brings its own key terms and explanation, so hints match what it taught.
    notes = f"Lesson notes:\n{topic.notes}\n" if getattr(topic, "notes", "") else ""
    system = (
        "You are a patient tutor helping a beginner programmer.\n"
        f"Topic: {topic.title} ({topic.track.name}).\n"
        f"Topic summary: {topic.summary or '(none)'}\n"
        f"{notes}"
        f"Tips from our team:\n{tips}\n"
        f"Resources the learner has:\n{resources}\n\n"
        "Rules:\n"
        "- Stay on this topic. Use only the ideas above and basic programming knowledge.\n"
        f"{_task_rule(request)}"
        f"{style}"
        f"- {EXPERIENCE_NOTES.get(request.experience, 'Assume they are a beginner.')}\n"
        f"- Keep the reply under {200 if request.action == 'solution' else 120} words.\n"
        "- If the question is not about programming, gently steer back to the topic.\n"
        f"{LOCAL_EXAMPLES}\n"
        f"{_language_rules(request.language)}"
    )
    note = "" if request.language in LANGUAGE_RULES else language_note(request.question)
    user = f"My question: {request.question}{note}"
    if request.action == "debug" and (request.code or request.error):
        user = (f"My code:\n{request.code or '(none)'}\n"
                f"The error I get:\n{request.error or '(no error, but wrong output)'}\n{user}")
    if request.screen == "quiz" and request.quiz_item is not None:
        # The prompt only. accepted_answers never leave the server.
        user = (
            f"I'm on this quiz question: {request.quiz_item.prompt}\n"
            f"My answer so far: {request.learner_answer or '(blank)'}\n{user}"
        )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _task_rule(request):
    """The rule for what the learner asked for. Quiz answers are never given, whatever the action."""
    never = "- Never give the exact answer to a quiz blank.\n"
    if request.action == "hint" or request.action not in ACTIONS:
        return (f"{never}- Never give the full solution.\n"
                f"- This is hint level {request.hint_level} of 3. {HINT_LEVELS[request.hint_level]}\n")
    if request.action == "solution":
        return f"{never}- {ACTIONS['solution']}\n"
    return f"{never}- Never give the full solution.\n- {ACTIONS[request.action]}\n"


def _language_rules(language):
    if language in LANGUAGE_RULES:
        return f"{LANGUAGE_RULES[language]}\n- Plain text only: no markdown, no backticks, no asterisks, no headings."
    return HELP_LANGUAGE_RULES


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
    reply = f"{reason} {FALLBACK_PROMPTS.get(request.action, FALLBACK_PROMPTS['hint'])}"
    if request.screen == "quiz" and request.quiz_item is not None and request.quiz_item.hint:
        reply = f"{reply} Hint for this blank: {request.quiz_item.hint}"
    return HelpReply(
        action=request.action,
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
        f"{ENGLISH_RULES}"
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
    if request.action not in ACTIONS:
        request.action = "hint"
    if request.action == "solution" and request.screen == "quiz":
        # A full solution on a quiz would hand over the answer: the strongest hint instead.
        request.action, request.hint_level = "hint", 3
    if not providers():
        return fallback(request, learner, "The AI helper is off right now. These tips and links should help.")
    if not reserve_message(learner):
        return fallback(request, learner, "You've used all your AI messages for today. These tips and links should help.")

    text = ask_model(build_messages(request))
    if text is None:
        release_message(learner)
        return fallback(request, learner, "The AI helper is busy right now. These tips and links should help.")

    return HelpReply(
        action=request.action,
        mode="ai",
        reply=text,
        hint_level=request.hint_level,
        remaining_today=remaining_today(learner),
        tips=topic_tips(request.topic),
        resources=topic_resources(request.topic),
    )
