"""A learner's AI-written plan: which plan is theirs, what comes next, and grading lesson checks.

The plan is a PlanOutline marked active; each lesson's progress is a LessonProgress row.
Checks are graded with the same rules as curated quizzes (learning/grading.py): the same
answer matching, the same 70% pass mark compared as exact fractions, and the same bands.
"""

from django.db import transaction
from django.utils import timezone

from .grading import ALMOST_PERCENT, PASS_PERCENT, normalize
from .lessons import current_lesson
from .outline import SETUP_KEY, all_lessons, learner_setup, setup_lesson
from .models import LessonProgress, PlanOutline

# After this many misses on the same version, offer to move on (framework section 7).
MOVE_ON_AFTER = 2


def active_outline(profile):
    return PlanOutline.objects.filter(learner=profile, is_active=True).first()


@transaction.atomic
def activate(outline):
    """Make this outline the learner's plan. Their earlier AI plan, if any, steps aside."""
    PlanOutline.objects.filter(learner=outline.learner, is_active=True).exclude(pk=outline.pk).update(is_active=False)
    outline.is_active = True
    outline.save(update_fields=["is_active"])


def lessons_in_order(outline):
    return all_lessons(outline)


def progress_by_key(outline):
    return {p.key: p for p in outline.progress.all()}


def progress_for(outline, key):
    return LessonProgress.objects.get_or_create(outline=outline, key=key)[0]


def is_finished(status):
    return status in (LessonProgress.Status.DONE, LessonProgress.Status.SKIPPED)


def next_lesson(outline, progress=None):
    """The first lesson not done or skipped, or None when the plan is finished."""
    progress = progress if progress is not None else progress_by_key(outline)
    return next((lesson for lesson in lessons_in_order(outline)
                 if not (lesson["key"] in progress and is_finished(progress[lesson["key"]].status))), None)


def start(progress):
    """Opening a lesson moves it to in progress; never undoes done or skipped."""
    if progress.status == LessonProgress.Status.TODO:
        progress.status = LessonProgress.Status.IN_PROGRESS
        progress.save(update_fields=["status", "updated_at"])


def grade_check(check, answers):
    """Grade the graded questions of a lesson's check. Self-checks are shown, never counted.

    `answers` has one entry per question, in order: a choice number for multiple choice,
    text for a blank. Returns the per-question results and the score.
    """
    results = []
    for question, answer in zip(check, answers):
        if question["type"] == "mc":
            correct = str(answer) == str(question["correct"])
        elif question["type"] == "blank":
            given = normalize(answer)
            correct = any(given == normalize(a) for a in question["accepted_answers"])
        else:
            correct = None
        results.append({"question": question, "answer": answer, "correct": correct})
    graded = [r for r in results if r["correct"] is not None]
    right = sum(1 for r in graded if r["correct"])
    total = len(graded)
    passed = total > 0 and right * 100 >= PASS_PERCENT * total
    if passed:
        band = "perfect" if right == total else "passed"
    else:
        band = "almost" if right * 100 >= ALMOST_PERCENT * total else "low"
    return {"results": results, "correct": right, "total": total,
            "percent": round(right * 100 / total) if total else 0, "passed": passed, "band": band}


def record_check(progress, answers, score):
    """Save the attempt. A pass marks the lesson done."""
    progress.tries += 1
    progress.last_answers = [str(a) for a in answers]
    progress.last_correct = [r["correct"] for r in score["results"]]
    fields = ["tries", "last_answers", "last_correct", "updated_at"]
    if score["passed"]:
        progress.status, progress.completed_at, progress.shaky = LessonProgress.Status.DONE, timezone.now(), False
        fields += ["status", "completed_at", "shaky"]
    progress.save(update_fields=fields)


def struggled_with(lesson, progress):
    """The graded questions the learner missed last time, to ask for a different way of teaching."""
    check = lesson.data.get("check", [])
    return [q["prompt"] for q, ok in zip(check, progress.last_correct) if ok is False][:5]


def outdated_lessons(outline):
    """Written lessons that follow a different setup than the learner's current one."""
    current = learner_setup(outline)
    return [lesson for lesson in outline.lessons.filter(is_current=True).exclude(key=SETUP_KEY)
            if lesson.data.get("setup_used", "") != current]


def needs_update(outline, lesson):
    """The learner asked to update lessons for a new setup, and this one still follows the old setup."""
    return outline.update_for_setup and lesson.key != SETUP_KEY and lesson.data.get("setup_used", "") != learner_setup(outline)


def fresh_version(progress):
    """A rewritten lesson starts a clean slate: new questions, new tries."""
    progress.tries, progress.last_answers, progress.last_correct = 0, [], []
    progress.save(update_fields=["tries", "last_answers", "last_correct", "updated_at"])


def move_on(progress):
    """After missing the check twice: continue the plan; the lesson is marked shaky for review."""
    progress.status, progress.shaky, progress.completed_at = LessonProgress.Status.SKIPPED, True, timezone.now()
    progress.save(update_fields=["status", "shaky", "completed_at", "updated_at"])


def warm_up(outline, key):
    """Up to 2 questions from the previous lesson, the ones the learner missed first. No AI call."""
    keys = [lesson["key"] for lesson in lessons_in_order(outline)]
    if key not in keys or keys.index(key) == 0:
        return []
    previous_key = keys[keys.index(key) - 1]
    previous = current_lesson(outline, previous_key)
    if previous is None:
        return []
    progress = LessonProgress.objects.filter(outline=outline, key=previous_key).first()
    marks = progress.last_correct if progress else []
    graded = [(q, marks[i] if i < len(marks) else None) for i, q in enumerate(previous.data.get("check", []))
              if q["type"] in ("mc", "blank")]
    graded.sort(key=lambda pair: pair[1] is not False)  # Missed ones first, otherwise lesson order.
    return [q for q, _ in graded[:2]]


def answer_text(question):
    """The right answer, as shown after a check or under a warm-up."""
    if question["type"] == "mc":
        return question["choices"][question["correct"]]
    if question["type"] == "blank":
        return question["accepted_answers"][0]
    return question.get("sample_answer", "")
