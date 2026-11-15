from itertools import groupby

from django.contrib import messages
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import LearnerProfile, get_profile
from assistant.service import daily_limit, practice_feedback, remaining_today
from content.models import PracticeTask, Resource, Topic, Track

from . import ai_views, journey, rewards
from .ai_plan import active_outline
from .forms import QuizForm
from .grading import PASS_PERCENT, latest_result, submit_quiz
from .models import PlanFeedback, PlanItem, PracticeSubmission, QuizAttempt
from .planner import (
    active_plan, defer_item, move_on_shaky, plan_item_for_topic, plan_tracks, repace_plan, set_item_status,
    start_item,
)
from .tailoring import build_plan_with_template


@require_POST
def plan_build(request):
    profile = get_profile(request.user)
    if not profile.onboarded or profile.track is None:
        return redirect("about_you")
    build_plan_with_template(profile)
    messages.success(request, "Your learning plan is ready.")
    return redirect("plan")


def plan(request):
    profile = get_profile(request.user)
    if profile.gets_ai_plans():
        outline = active_outline(profile)
        if outline is not None:
            return ai_views.plan(request, profile, outline)
    current = active_plan(profile)
    if current is None:
        if profile.gets_ai_plans() and profile.onboarded:
            # Onboarding finished but the AI couldn't write the plan: offer to try again.
            return render(request, "learning/ai_plan_retry.html", {"profile": profile})
        return redirect("result")
    items = list(
        current.items.select_related("topic__track")
        .prefetch_related(
            Prefetch("topic__resources", queryset=Resource.objects.filter(is_active=True)),
            "topic__tips",
            "topic__quiz_items",
            Prefetch("topic__practice_tasks", queryset=PracticeTask.objects.filter(approved=True)),
        )
        .order_by("order")
    )
    milestones = journey.milestones_by_week(current)
    # The topic finished just before this visit gets its moment on the trail (set by a status change or a quiz pass).
    just_done = request.session.pop("just_done", None)
    weeks = []
    for week, group in groupby(items, key=lambda item: item.week):
        group = list(group)
        finished = sum(1 for i in group if i.status in (PlanItem.Status.DONE, PlanItem.Status.SKIPPED))
        fresh = any(i.pk == just_done and i.status == PlanItem.Status.DONE for i in group)
        weeks.append({
            "number": week,
            "items": group,
            "milestones": milestones.get(week, []),
            # The week's milestone line: what each topic lets them do, skipped ones left out.
            "outcomes": [i.topic.summary for i in group if i.topic.summary and i.status != PlanItem.Status.SKIPPED],
            "done": finished,
            # How far the week's trail is filled, and where it grew from if a topic was just finished.
            "trail": round(finished * 100 / len(group)),
            "trail_from": round((finished - 1) * 100 / len(group)) if fresh else None,
            "just_finished": fresh and finished == len(group),
        })
    tracks = plan_tracks(profile)
    reviews = journey.due_reviews(profile, current)
    starting = journey.starting_point(profile, current)
    unchecked = journey.unchecked_topic_ids(profile, items)
    next_action = journey.next_action(profile, current, items, reviews)
    # The week to open: the one with the next topic, else the first with anything left.
    unfinished = [i for i in items if i.status in (PlanItem.Status.TODO, PlanItem.Status.IN_PROGRESS)]
    current_week = next(
        (i.week for i in unfinished if next_action and i.topic_id == next_action.topic_id),
        unfinished[0].week if unfinished else None,
    )
    return render(
        request,
        "learning/plan.html",
        {
            "plan": current,
            "profile": profile,
            "tracks": tracks,
            "setup": journey.setup_status(profile, tracks),
            "weeks": weeks,
            "progress": current.progress_percent(),
            "project": getattr(current, "project", None),
            "next_action": next_action,
            "current_week": current_week,
            "done_count": sum(1 for i in items if i.status == PlanItem.Status.DONE),
            "counted": sum(1 for i in items if i.status != PlanItem.Status.SKIPPED),
            "reviews": reviews,
            "starting": starting,
            "unchecked_count": len(unchecked),
            "unchecked": unchecked,
            "estimate": journey.estimate(profile, current, items),
            "finished": journey.is_finished(items),
            "hours_choices": [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20],
            "streak": rewards.weekly_streak(profile),
            "just_done": just_done,
        },
    )


def plan_finish(request):
    """The end of the plan: what the learner did, and where they can go from here."""
    profile = get_profile(request.user)
    if profile.gets_ai_plans() and (outline := active_outline(profile)) is not None:
        return ai_views.finish(request, profile, outline)
    current = active_plan(profile)
    if current is None:
        return redirect("result")
    items = list(current.items.select_related("topic__track").order_by("order"))
    # Open once nothing is left to do, the same moment the plan page says the plan is finished,
    # even if everything was skipped (the certificate only shows when something was done).
    if any(i.status in (PlanItem.Status.TODO, PlanItem.Status.IN_PROGRESS) for i in items) or not items:
        return redirect("plan")
    summary = journey.finish_summary(profile, current, items)
    plan_name = profile.path.title if profile.path_id else current.track.name
    if summary["new_tracks"]:
        track = summary["new_tracks"][0]
        next_step = {
            "next_title": f"Try {track.name}",
            "next_text": f"Build on what you've learned with {track.name}. It's now open on your path, "
                         "and the topics you've finished stay finished.",
            "next_url": reverse("plan_build"), "next_button": f"Start {track.name}", "next_post": True,
        }
    else:
        next_step = _new_goal_step()
    return render(
        request,
        "learning/finish.html",
        {
            "profile": profile,
            "project": getattr(current, "project", None),
            "reviews": journey.due_reviews(profile, current),
            **summary,
            "kicker": f"{profile.path.title} complete" if profile.path_id else f"{current.track.name} track complete",
            "plan_name": plan_name,
            "plan_title": profile.path.title if profile.path_id else f"{current.track.name} basics",
            "finished_on": rewards.finished_on(profile),
            **next_step,
        },
    )


def _new_goal_step():
    """The finish page's "What's next?" when there's no next track to offer: a new goal."""
    return {
        "next_title": "Pick a new goal",
        "next_text": "Ready for something different? Tell us what you want to make next, and you'll get a new plan.",
        "next_url": reverse("intake") + "?edit=1", "next_button": "Change my answers",
    }


@require_POST
def plan_pace(request):
    """Change weekly time: the same plan, spread over different weeks."""
    profile = get_profile(request.user)
    current = active_plan(profile)
    try:
        hours = min(max(int(request.POST.get("hours", "")), 1), 40)
    except ValueError:
        messages.error(request, "Pick how many hours a week.")
        return redirect("plan")
    if current is not None:
        profile.hours_per_week = hours
        profile.save(update_fields=["hours_per_week"])
        repace_plan(current, hours)
        messages.success(request, f"Your plan now fits {hours} hour{'s' if hours != 1 else ''} a week. Your progress is kept.")
    return redirect("plan")


@require_POST
def plan_report(request):
    """A learner flags something in their plan that looks wrong (AI reasons, project, links)."""
    profile = get_profile(request.user)
    current = active_plan(profile)
    text = " ".join(request.POST.get("text", "").split())[:500]
    if current is None or not text:
        messages.error(request, "Tell us what looks wrong first.")
        return redirect("plan")
    PlanFeedback.objects.create(learner=profile, plan=current, text=text)
    messages.success(request, "Thanks! The team will take a look.")
    return redirect("plan")


ALLOWED_STATUSES = {PlanItem.Status.DONE, PlanItem.Status.SKIPPED, PlanItem.Status.TODO}


@require_POST
def plan_item_status(request, item_id):
    item = get_object_or_404(
        PlanItem.objects.select_related("plan__learner", "topic"),
        pk=item_id,
        plan__learner__user=request.user,
        plan__is_active=True,
    )
    status = request.POST.get("status")
    if status not in ALLOWED_STATUSES:
        messages.error(request, "That status isn't allowed.")
        return redirect("plan")
    set_item_status(item, status)
    if status == PlanItem.Status.DONE:
        request.session["just_done"] = item.pk
    messages.success(request, f"{item.topic.title}: {item.get_status_display().lower()}.")
    return redirect("plan")


def setup_guide(request, track):
    track = get_object_or_404(Track, slug=track, is_active=True)
    profile = get_profile(request.user)
    if request.method == "POST":
        profile.setup_done.add(track)
        messages.success(request, f"{track.name} is set up. On to Week 1!")
        return redirect("plan")
    return render(
        request,
        "learning/setup_guide.html",
        {
            "track": track,
            "steps": track.setup_steps.all(),
            "done": profile.setup_done.filter(pk=track.pk).exists(),
        },
    )


def _active_topic(slug):
    return get_object_or_404(Topic.objects.select_related("track"), slug=slug, track__is_active=True)


def lesson(request, topic):
    topic = _active_topic(topic)
    profile = get_profile(request.user)
    item = plan_item_for_topic(profile, topic)
    start_item(item)
    # What to build with this topic: the project step for the week it's in.
    build_steps = journey.milestones_by_week(item.plan).get(item.week, []) if item else []
    return render(
        request,
        "learning/lesson.html",
        {
            "topic": topic,
            "item": item,
            "warm_up": journey.warm_up(profile, item),
            "build_steps": build_steps,
            "resources": topic.resources.filter(is_active=True),
            "tips": topic.tips.all(),
            "prerequisites": topic.prerequisites.all(),
            "has_quiz": topic.quiz_items.exists(),
            "has_practice": _practice_task(topic) is not None,
            **_help(profile, topic, "lesson"),
        },
    )


def _help(profile, topic, screen):
    """What the Agapay panel needs on a topic screen: messages left, tips and links for when there are
    none, and, with no AI, the plan item it can adjust and the track's curated project ideas."""
    return {
        "help_screen": screen,
        "help_remaining": remaining_today(profile),
        "help_limit": daily_limit(),
        "help_tips": topic.tips.all()[:2],
        "help_resources": topic.resources.filter(is_active=True),
        "help_item": plan_item_for_topic(profile, topic),
        "help_ideas": topic.track.project_ideas.filter(is_active=True)[:3],
        "help_language": profile.explain_language,
        "help_languages": LearnerProfile.ExplainLanguage.choices,
    }


MAX_PRACTICE_ANSWER = 4000


def _practice_task(topic):
    return topic.practice_tasks.filter(approved=True).first()


def practice(request, topic):
    """Task → the learner's answer → hint-style feedback (AI, or the checklist when AI is off)."""
    topic = _active_topic(topic)
    task = _practice_task(topic)
    profile = get_profile(request.user)
    if request.method == "POST" and task is not None:
        answer = request.POST.get("answer", "").strip()[:MAX_PRACTICE_ANSWER]
        if not answer:
            messages.error(request, "Write your answer first. Any try is fine, even a rough one.")
            return redirect("practice", topic=topic.slug)
        feedback = practice_feedback(profile, task, answer)
        PracticeSubmission.objects.create(
            learner=profile, task=task, answer=answer, feedback=feedback.text, mode=feedback.mode
        )
        return redirect(f"{reverse('practice', args=[topic.slug])}#feedback")
    latest = (
        PracticeSubmission.objects.filter(learner=profile, task=task).first() if task else None
    )
    return render(
        request,
        "learning/practice.html",
        {
            "topic": topic,
            "task": task,
            "item": plan_item_for_topic(profile, topic),
            "latest": latest,
            "revising": request.GET.get("revise") == "1",
            "has_quiz": topic.quiz_items.exists(),
            "has_practice": task is not None,
            "max_answer": MAX_PRACTICE_ANSWER,
            **_help(profile, topic, "practice"),
        },
    )


def quiz(request, topic):
    topic = _active_topic(topic)
    items = list(topic.quiz_items.all())
    form = QuizForm(request.POST or None, items=items)
    if request.method == "POST" and items and form.is_valid():
        profile = get_profile(request.user)
        result = submit_quiz(profile, topic, items, form.answers())
        if result.passed and (item := plan_item_for_topic(profile, topic)) is not None:
            request.session["just_done"] = item.pk
        if result.passed:
            messages.success(request, f"You passed with {result.percent}%! {topic.title} is done.")
        else:
            messages.error(request, f"You got {result.percent}%. You need {PASS_PERCENT}% to pass. Try again!")
        return redirect("quiz_result", topic=topic.slug)
    return render(
        request,
        "learning/quiz.html",
        {"topic": topic, "form": form, "pass_percent": PASS_PERCENT,
         "has_practice": _practice_task(topic) is not None,
         **_help(get_profile(request.user), topic, "quiz")},
    )


def _after_pass(profile):
    """Momentum after a pass: plan progress and the next step to go to."""
    current = active_plan(profile)
    if current is None:
        return {}
    items = list(current.items.select_related("topic").order_by("order"))
    return {
        "plan_progress": current.progress_percent(),
        "finished": journey.is_finished(items),
        "next_action": journey.next_action(profile, current, items, journey.due_reviews(profile, current)),
    }


def quiz_result(request, topic):
    topic = _active_topic(topic)
    profile = get_profile(request.user)
    items = list(topic.quiz_items.all())
    result = latest_result(profile, items)
    if result is None:
        return redirect("quiz", topic=topic.slug)
    # Rough count of tries: each submission saves one attempt per item.
    tries = QuizAttempt.objects.filter(learner=profile, quiz_item__in=items).count() // max(len(items), 1)
    resources = list(topic.resources.filter(is_active=True))
    item = plan_item_for_topic(profile, topic)
    struggling = not result.passed and tries >= 2
    return render(
        request,
        "learning/quiz_result.html",
        {
            "topic": topic,
            "result": result,
            "pass_percent": PASS_PERCENT,
            "has_practice": _practice_task(topic) is not None,
            **_help(profile, topic, "quiz"),
            # After a couple of misses, point back to what this topic builds on.
            "struggling": struggling,
            # Right answers show once they've passed or had two goes, so the first try is theirs to figure out.
            "reveal": result.passed or tries >= 2,
            "missed": result.total - result.correct,
            # Plan progress only means something if this topic was in the plan.
            "topic_in_plan": item is not None,
            **(_after_pass(profile) if result.passed else {}),
            "prerequisites": topic.prerequisites.filter(track__is_active=True),
            "resources": resources,
            # A different way in: the link of another type than the first (e.g. a video, not docs).
            "other_resource": next((r for r in resources[1:] if r.kind != resources[0].kind), None)
            if resources else None,
            # Two misses: let them move on instead of looping, and bring it back as a review.
            "move_on_item": item if struggling and item and item.status != PlanItem.Status.DONE and not item.shaky else None,
        },
    )


@require_POST
def plan_item_defer(request, item_id):
    """"Later": move a topic to the end of the plan, unless a later topic needs it first."""
    item = get_object_or_404(
        PlanItem.objects.select_related("plan__learner", "topic"),
        pk=item_id, plan__learner__user=request.user, plan__is_active=True,
        status__in=[PlanItem.Status.TODO, PlanItem.Status.IN_PROGRESS],
    )
    blocking = defer_item(item)
    if blocking:
        messages.error(request, f"{item.topic.title} can't wait: {', '.join(blocking)} need{'s' if len(blocking) == 1 else ''} it first.")
    else:
        messages.success(request, f"{item.topic.title} moved to the end of your plan.")
    return redirect("plan")


@require_POST
def plan_pause(request):
    """Pause or resume the plan. Pausing keeps everything; it only stops reminders and the streak clock."""
    profile = get_profile(request.user)
    if request.POST.get("action") == "resume":
        profile.paused_at = None
        messages.success(request, "Welcome back! Your plan is where you left it.")
    else:
        profile.paused_at = profile.paused_at or timezone.now()
        messages.success(request, "Your plan is paused. Nothing is lost, and no reminders go out until you resume.")
    profile.save(update_fields=["paused_at"])
    return redirect("plan")


@require_POST
def plan_item_shaky(request, item_id):
    item = get_object_or_404(
        PlanItem.objects.select_related("topic"),
        pk=item_id,
        plan__learner__user=request.user,
        plan__is_active=True,
    )
    if item.status != PlanItem.Status.DONE:
        move_on_shaky(item)
        messages.success(request, f"Moved on from {item.topic.title}. It'll come back as a short review next week.")
    return redirect("plan")
