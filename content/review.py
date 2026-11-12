"""The review queue in admin: every AI draft waiting for a person, on one page.

Topic intros and practice tasks are drafted by AI and stay hidden from learners until a
curator approves them (content/drafting.py). Before this page, a curator had to open each
topic or task and tick a box. Here they read each draft as the learner would see it and
approve it with one click, or open it in admin to fix it first.

AI-written plan lessons are reviewed afterwards, not approved first (docs/plan-framework.md,
section 11), so this page only counts the ones that need a look and links to them.
"""

from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from learning.models import GeneratedLesson, LessonProgress

from .models import PracticeTask, Topic


def waiting_intros():
    return Topic.objects.filter(intro_approved=False).exclude(explanation="").select_related("track")


def waiting_tasks():
    return PracticeTask.objects.filter(approved=False).select_related("topic__track")


def lessons_to_check():
    """Current AI lessons not reviewed yet that were flagged automatically or rated unhelpful."""
    current = GeneratedLesson.objects.filter(is_current=True, review=GeneratedLesson.Review.NOT_REVIEWED)
    disliked = set(LessonProgress.objects.filter(rating=-1).values_list("outline_id", "key"))
    disliked_ids = [
        pk for pk, outline_id, key in current.values_list("pk", "outline_id", "key") if (outline_id, key) in disliked
    ]
    return current.filter(flagged=True) | current.filter(pk__in=disliked_ids)


def waiting_count():
    return waiting_intros().count() + waiting_tasks().count()


@staff_member_required
def queue(request):
    lessons = lessons_to_check()
    return render(request, "admin/review_queue.html", {
        **admin.site.each_context(request),
        "title": "Review queue",
        "intros": waiting_intros(),
        "tasks": waiting_tasks(),
        "lesson_count": lessons.count(),
        "lessons_url": reverse("admin:learning_generatedlesson_changelist")
        + f"?review__exact={GeneratedLesson.Review.NOT_REVIEWED}&is_current__exact=1",
    })


@staff_member_required
@require_POST
def approve(request, kind, pk):
    if kind == "intro":
        topic = get_object_or_404(Topic, pk=pk)
        topic.intro_approved = True
        topic.save(update_fields=["intro_approved"])
        messages.success(request, f"Approved the intro for {topic.title}. Learners can see it now.")
    elif kind == "task":
        task = get_object_or_404(PracticeTask.objects.select_related("topic"), pk=pk)
        task.approved = True
        task.save(update_fields=["approved"])
        messages.success(request, f"Approved the practice task for {task.topic.title}. Learners can see it now.")
    else:
        return redirect("review_queue")
    return redirect("review_queue")
