"""Pages for a learner's AI-written plan (AI_PLANS on). Curated plans keep their own views.

The plan page shows the outline's modules and lessons. A lesson is written the first time
it's opened: the page first shows "writing your lesson" and reloads itself, so the learner
sees something during the AI call. Checks are graded in code; after a miss the learner can
ask for the lesson explained another way, and after two misses move on.
"""

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import get_profile
from assistant.service import (
    ai_available, daily_limit, lessons_left_today, release_lesson, remaining_today, reserve_intake, reserve_lesson,
)

from content.models import Track

from . import ai_plan, setup_guides
from .lessons import current_lesson, glossary, lesson_for, regenerate_lesson
from .models import GeneratedLesson, LessonProgress
from .outline import SETUP_KEY, generate_outline, setup_lesson, setup_options


def _outline_and_lesson(request, key):
    """The learner's active AI plan and one of its outline lessons, or 404."""
    profile = get_profile(request.user)
    outline = ai_plan.active_outline(profile)
    if outline is None:
        raise Http404("No AI plan")
    by_key = {x["key"]: x for x in ai_plan.lessons_in_order(outline)}
    if key not in by_key:
        raise Http404("No such lesson")
    return profile, outline, by_key[key]


def _given(question, result):
    """The learner's answer as they'd read it: the chosen option's words for multiple choice."""
    if result is None:
        return ""
    answer = str(result["answer"])
    if question["type"] == "mc" and answer.isdigit() and int(answer) < len(question["choices"]):
        return question["choices"][int(answer)]
    return answer


def _locked(outline, item):
    """Lessons stay locked until the learner chooses a setup option, so every lesson knows their setup."""
    return item["kind"] != "setup" and not outline.setup_choice and setup_lesson(outline) is not None


def _to_setup(request):
    messages.info(request, "Choose how you'll set up first. Your lessons follow the way you pick.")
    return redirect("ai_lesson", key=SETUP_KEY)


def _help(profile, outline, key):
    """What the Agapay panel needs on an AI lesson (templates/partials/help_panel.html)."""
    topic = ai_plan.help_topic(outline, key)
    return {
        "help_screen": "lesson", "help_lesson": key, "help_title": topic.title if topic else "",
        "help_remaining": remaining_today(profile), "help_limit": daily_limit(),
        "help_tips": topic.help_tips if topic else [], "help_resources": topic.help_resources if topic else [],
    }


def _try_steps(outline, lesson):
    """How to try this lesson's task in the learner's setup (setup_guides.try_steps)."""
    setup = setup_lesson(outline)
    if setup is None or not outline.setup_choice:
        return []
    return setup_guides.try_steps(outline.setup_choice, lesson.get("lang", ""), lesson.get("try_it", {}).get("file", ""),
                                  setup["folder"], setup.get("device", ""))


def _setup_info(outline, item):
    """What the setup page shows: the options, and the curated guide's steps when there is one."""
    track = Track.objects.get(pk=item["track_id"])
    written = current_lesson(outline, item["key"])
    ai_steps = (written.data.get("setup") or {}) if written else {}

    def steps(way):
        # Built-in guides first (tested, with official links); the AI's steps only for tracks without one.
        return setup_guides.guide(track.slug, way, item["folder"], item.get("device", "")) or [
            {"text": text, "link": "", "link_text": ""} for text in ai_steps.get(way, [])]
    return {**item, "options": setup_options(item), "curated_steps": list(track.setup_steps.all()),
            "setup_check": track.setup_check, "main_steps": steps("main"), "alternative_steps": steps("alternative")}


def plan(request, profile, outline):
    """The AI plan page. Called by learning.views.plan when the learner's plan is AI-written."""
    progress = ai_plan.progress_by_key(outline)
    modules = []
    for module in outline.data.get("modules", []):
        lessons = [{**x, "progress": progress.get(x["key"])} for x in module["lessons"]]
        done = sum(1 for x in lessons if x["progress"] and ai_plan.is_finished(x["progress"].status))
        modules.append({**module, "lessons": lessons, "done": done, "finished": done == len(lessons)})
    setup = setup_lesson(outline)
    if setup:
        setup = {**setup, "progress": progress.get(setup["key"])}
    setup_done = bool(setup and setup["progress"] and ai_plan.is_finished(setup["progress"].status))
    total = sum(len(m["lessons"]) for m in modules) + (1 if setup else 0)
    done = sum(m["done"] for m in modules) + (1 if setup_done else 0)
    upcoming = ai_plan.next_lesson(outline, progress)
    project = outline.data.get("project") or {}
    return render(request, "learning/ai_plan.html", {
        "profile": profile,
        "outline": outline,
        "data": outline.data,
        "modules": modules,
        "progress": round(done * 100 / total) if total else 0,
        "done_count": done,
        "total": total,
        "next_lesson": upcoming,
        "finished": ai_plan.plan_finished(outline),
        "current_module": next((m["number"] for m in modules if not m["finished"]), None),
        "project": project,
        "setup_lesson": setup,
        "setup_ready": bool(outline.setup_choice) or not setup,
        "glossary": glossary(outline),
    })


def finish(request, profile, outline):
    """The AI plan's finish page. Called by learning.views.plan_finish."""
    if not ai_plan.plan_finished(outline):
        return redirect("plan")
    return render(request, "learning/ai_finish.html", {
        "profile": profile,
        "data": outline.data,
        "project": outline.data.get("project") or {},
        "glossary": glossary(outline),
        **ai_plan.finish_summary(outline),
    })


@require_POST
def plan_retry(request):
    """Try writing the AI plan again after it failed at the end of onboarding."""
    profile = get_profile(request.user)
    if ai_plan.active_outline(profile) is not None:
        return redirect("plan")
    if not (ai_available() and reserve_intake(profile)):
        messages.error(request, "We can't write plans right now. Please try again tomorrow.")
        return redirect("plan")
    outline = generate_outline(profile, profile.goal_text)
    if outline is None:
        messages.error(request, "That didn't work either. Please try again in a few minutes.")
        return redirect("plan")
    ai_plan.activate(outline)
    messages.success(request, "Your plan is ready. Start with the first lesson below.")
    return redirect("plan")


def lesson(request, key):
    profile, outline, item = _outline_and_lesson(request, key)
    if _locked(outline, item):
        return _to_setup(request)
    setup_info = _setup_info(outline, item) if item["kind"] == "setup" else None
    written = current_lesson(outline, key)
    if written is not None and ai_plan.needs_update(outline, written):
        written = _update_for_setup(request, profile, outline, key, item, written)
        if not isinstance(written, GeneratedLesson):
            return written  # The "updating your lesson" page, or a redirect after the rewrite.
    if written is None:
        page = {"item": item, "setup_info": setup_info}
        if request.GET.get("write") != "1":
            # Show "writing your lesson" at once; the page reloads with ?write=1 to do the AI call.
            return render(request, "learning/ai_lesson_writing.html", page)
        if not reserve_lesson(profile):
            return render(request, "learning/ai_lesson_writing.html", {**page, "failed": "limit"})
        written = lesson_for(outline, key)
        if written is None:
            release_lesson(profile)
            return render(request, "learning/ai_lesson_writing.html", {**page, "failed": "ai"})
        return redirect("ai_lesson", key=key)

    progress = ai_plan.progress_for(outline, key)
    ai_plan.start(progress)
    # Setup ends with choosing a setup, never a quiz (older setup lessons were saved with questions).
    check = [] if item["kind"] == "setup" else written.data.get("check", [])
    score = ai_plan.grade_check(check, progress.last_answers) if progress.last_answers else None
    keys = [x["key"] for x in ai_plan.lessons_in_order(outline)]
    position = keys.index(key)
    module = next((m for m in outline.data["modules"] if any(x["key"] == key for x in m["lessons"])),
                  {"progress": "Setup", "title": "Get ready"})
    warm_up = [{"question": q, "answer": ai_plan.answer_text(q)} for q in ai_plan.warm_up(outline, key)]
    return render(request, "learning/ai_lesson.html", {
        "item": item,
        "module": module,
        "lesson": written.data,
        "written": written,
        "progress": progress,
        "warm_up": warm_up,
        "score": score,
        # Each question with its number (the form field is q<number>) and, after a try, its result.
        "questions": [{"q": q, "n": i, "result": score["results"][i] if score else None,
                       "answer": ai_plan.answer_text(q), "given": _given(q, score["results"][i] if score else None)}
                      for i, q in enumerate(check)],
        "can_move_on": score is not None and not score["passed"] and progress.tries >= ai_plan.MOVE_ON_AFTER
        and progress.status != LessonProgress.Status.DONE,
        "next_key": keys[position + 1] if position + 1 < len(keys) else None,
        "setup_info": setup_info,
        "outline": outline,
        "beginner": outline.data.get("level", "beginner") == "beginner",
        "try_steps": [] if setup_info else _try_steps(outline, written.data),
        "outdated_count": len(ai_plan.outdated_lessons(outline)) if setup_info and outline.setup_choice else 0,
        "lessons_left": lessons_left_today(profile),
        "lesson_number": position + 1,
        **_help(profile, outline, key),
        "lesson_total": len(keys),
    })


def _update_for_setup(request, profile, outline, key, item, written):
    """Rewrite a lesson for the learner's new setup when they open it (they asked for this).

    Done one lesson at a time, on open, because rewriting every lesson at once would be many
    slow AI calls in one request. Without lessons left today, or when the AI fails, the old
    version still shows, so the learner is never blocked.
    """
    if request.GET.get("write") != "1":
        if lessons_left_today(profile):
            return render(request, "learning/ai_lesson_writing.html", {"item": item, "updating": True})
        messages.info(request, "This lesson still shows your old setup. It will be updated when you have new lessons tomorrow.")
        return written
    if not reserve_lesson(profile):
        messages.info(request, "This lesson still shows your old setup. It will be updated when you have new lessons tomorrow.")
        return written
    if regenerate_lesson(outline, key) is None:
        release_lesson(profile)
        messages.error(request, "We couldn't update this lesson just now, so it shows your old setup. Try again later.")
        return written
    ai_plan.fresh_version(ai_plan.progress_for(outline, key))
    messages.success(request, "Updated for your new setup.")
    return redirect("ai_lesson", key=key)


@require_POST
def check(request, key):
    profile, outline, item = _outline_and_lesson(request, key)
    if _locked(outline, item):
        return _to_setup(request)
    written = current_lesson(outline, key)
    if written is None:
        return redirect("ai_lesson", key=key)
    questions = written.data.get("check", [])
    answers = [request.POST.get(f"q{i}", "").strip()[:200] for i in range(len(questions))]
    score = ai_plan.grade_check(questions, answers)
    ai_plan.record_check(ai_plan.progress_for(outline, key), answers, score)
    if score["passed"]:
        messages.success(request, f"You got {score['correct']} of {score['total']}. {item['title']} is done!")
    else:
        messages.error(request, f"You got {score['correct']} of {score['total']}. You need 70% to pass.")
    return redirect(f"{reverse('ai_lesson', args=[key])}#check")


@require_POST
def rewrite(request, key):
    """Explain it another way: a new version of the lesson, aimed at what the learner missed."""
    profile, outline, item = _outline_and_lesson(request, key)
    if _locked(outline, item):
        return _to_setup(request)
    written = current_lesson(outline, key)
    progress = ai_plan.progress_for(outline, key)
    if written is None or not reserve_lesson(profile):
        messages.error(request, "You've used today's new lessons. Try the resources below, or come back tomorrow.")
        return redirect("ai_lesson", key=key)
    if regenerate_lesson(outline, key, ai_plan.struggled_with(written, progress)) is None:
        release_lesson(profile)
        messages.error(request, "We couldn't rewrite it just now. Please try again in a few minutes.")
        return redirect("ai_lesson", key=key)
    ai_plan.fresh_version(progress)
    messages.success(request, "Here it is, explained another way, with new questions.")
    return redirect("ai_lesson", key=key)


@require_POST
def move_on(request, key):
    _, outline, item = _outline_and_lesson(request, key)
    if _locked(outline, item):
        return _to_setup(request)
    ai_plan.move_on(ai_plan.progress_for(outline, key))
    messages.success(request, f"Moved on. {item['title']} is marked to review later.")
    return redirect("plan")


@require_POST
def setup_done(request, key):
    """The end of the setup lesson: which way the learner set up. Later lessons follow it."""
    _, outline, item = _outline_and_lesson(request, key)
    if item["kind"] != "setup":
        raise Http404("Not a setup lesson")
    options = {o["way"]: o for o in setup_options(item)}
    choice = request.POST.get("way")
    if choice not in options:
        messages.error(request, "Pick one of the setup options.")
        return redirect("ai_lesson", key=key)
    changed = bool(outline.setup_choice) and outline.setup_choice != choice
    outline.setup_choice = choice
    outline.update_for_setup = False  # A new setup means a new decision about updating lessons.
    outline.save(update_fields=["setup_choice", "update_for_setup"])
    progress = ai_plan.progress_for(outline, key)
    progress.status, progress.completed_at = LessonProgress.Status.DONE, progress.completed_at or timezone.now()
    progress.save(update_fields=["status", "completed_at", "updated_at"])
    messages.success(request, f"You're set up: {options[choice]['name']}. New lessons will follow it.")
    if changed and ai_plan.outdated_lessons(outline):
        return redirect(f"{reverse('ai_lesson', args=[key])}#update")  # Offer to update the lessons already written.
    return redirect("plan")


@require_POST
def update_lessons(request, key):
    """Rewrite lessons already written for the old setup, each the next time it's opened."""
    _, outline, item = _outline_and_lesson(request, key)
    if item["kind"] != "setup" or not outline.setup_choice:
        raise Http404("Not a setup lesson")
    count = len(ai_plan.outdated_lessons(outline))
    outline.update_for_setup = True
    outline.save(update_fields=["update_for_setup"])
    messages.success(request, f"{count} lesson{'s' if count != 1 else ''} will be rewritten for your new setup, "
                              "each the next time you open it.")
    return redirect("plan")


STATUSES = {LessonProgress.Status.DONE, LessonProgress.Status.SKIPPED, LessonProgress.Status.TODO}


@require_POST
def status(request, key):
    """Mark done, skip, or undo from the plan page. Setup is finished only by choosing an option."""
    _, outline, item = _outline_and_lesson(request, key)
    if item["kind"] == "setup":
        return redirect("ai_lesson", key=key)
    if _locked(outline, item):
        return _to_setup(request)
    value = request.POST.get("status")
    if value not in STATUSES:
        messages.error(request, "That status isn't allowed.")
        return redirect("plan")
    progress = ai_plan.progress_for(outline, key)
    progress.status, progress.shaky = value, False
    progress.completed_at = None if value == LessonProgress.Status.TODO else progress.completed_at
    progress.save(update_fields=["status", "shaky", "completed_at", "updated_at"])
    return redirect("plan")


@require_POST
def rate(request, key):
    """Thumbs up or down. Down flags the lesson for the weekly review (framework section 11)."""
    _, outline, _ = _outline_and_lesson(request, key)
    written = current_lesson(outline, key)
    helpful = request.POST.get("helpful") == "yes"
    progress = ai_plan.progress_for(outline, key)
    progress.rating = 1 if helpful else -1
    progress.save(update_fields=["rating", "updated_at"])
    note = " ".join(request.POST.get("note", "").split())[:300]
    if written is not None and not helpful:
        written.flags = [*written.flags, f"Learner: not helpful{': ' + note if note else ''}"]
        written.save(update_fields=["flags", "flagged"])
    messages.success(request, "Thanks! That helps us improve the lessons.")
    return redirect(f"{reverse('ai_lesson', args=[key])}#feedback")
