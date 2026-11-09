from django.conf import settings
from django.db import models
from django.db.models import Q


class LearningPlan(models.Model):
    learner = models.ForeignKey(
        "accounts.LearnerProfile", on_delete=models.CASCADE, related_name="plans"
    )
    track = models.ForeignKey("content.Track", on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["learner", "track"],
                condition=Q(is_active=True),
                name="one_active_plan_per_track",
            )
        ]

    def __str__(self):
        return f"{self.learner.user} · {self.track}{'' if self.is_active else ' (old)'}"

    def progress_percent(self):
        """Share of non-skipped items that are done. Computed, never stored."""
        statuses = list(self.items.values_list("status", flat=True))
        counted = [s for s in statuses if s != PlanItem.Status.SKIPPED]
        if not counted:
            return 100 if statuses else 0
        done = sum(1 for s in counted if s == PlanItem.Status.DONE)
        return round(done * 100 / len(counted))


class PlanItem(models.Model):
    class Status(models.TextChoices):
        TODO = "todo", "To do"
        IN_PROGRESS = "in_progress", "In progress"
        DONE = "done", "Done"
        SKIPPED = "skipped", "Skipped"

    plan = models.ForeignKey(LearningPlan, on_delete=models.CASCADE, related_name="items")
    topic = models.ForeignKey("content.Topic", on_delete=models.CASCADE, related_name="+")
    order = models.PositiveIntegerField()
    week = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TODO)
    completed_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(
        max_length=300, blank=True, help_text="Why this topic is in the plan (from the AI intake)."
    )
    shaky = models.BooleanField(
        default=False, help_text="Moved on after missing the quiz twice; comes back as a review."
    )

    class Meta:
        ordering = ["plan", "order"]

    def __str__(self):
        return f"Week {self.week}: {self.topic.title} ({self.get_status_display()})"


class PlanProject(models.Model):
    """A small culminating project tied to the learner's goal and plan."""

    class Source(models.TextChoices):
        AI = "ai", "AI"
        TEMPLATE = "template", "Template"

    plan = models.OneToOneField(LearningPlan, on_delete=models.CASCADE, related_name="project")
    title = models.CharField(max_length=200)
    description = models.TextField()
    milestones = models.JSONField(default=list, help_text='List of {"week": n, "text": "..."}.')
    done_when = models.JSONField(default=list, help_text="Checklist of strings.")
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.TEMPLATE)
    idea = models.ForeignKey(
        "content.ProjectIdea", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="The curated idea this project was adapted from, if any.",
    )

    def __str__(self):
        return self.title


class QuizAttempt(models.Model):
    learner = models.ForeignKey(
        "accounts.LearnerProfile", on_delete=models.CASCADE, related_name="quiz_attempts"
    )
    quiz_item = models.ForeignKey("content.QuizItem", on_delete=models.CASCADE, related_name="+")
    answer = models.CharField(max_length=500, blank=True)
    is_correct = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.learner.user} · {self.quiz_item} · {'right' if self.is_correct else 'wrong'}"


class PracticeSubmission(models.Model):
    """A learner's answer to a practice task and the feedback they got. Never graded."""

    class Mode(models.TextChoices):
        AI = "ai", "AI hints"
        FALLBACK = "fallback", "Checklist (AI off or out of messages)"

    learner = models.ForeignKey(
        "accounts.LearnerProfile", on_delete=models.CASCADE, related_name="practice_submissions"
    )
    task = models.ForeignKey("content.PracticeTask", on_delete=models.CASCADE, related_name="+")
    answer = models.TextField(max_length=4000)
    feedback = models.TextField(blank=True)
    mode = models.CharField(max_length=20, choices=Mode.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.learner.user} · {self.task}"


class PlanFeedback(models.Model):
    """A learner's report that something in their plan looks wrong, for curators to check."""

    learner = models.ForeignKey(
        "accounts.LearnerProfile", on_delete=models.CASCADE, related_name="plan_feedback"
    )
    plan = models.ForeignKey(LearningPlan, on_delete=models.CASCADE, related_name="feedback")
    text = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "plan feedback"

    def __str__(self):
        return self.text[:60]


class AIRecord(models.Model):
    """What every AI-written plan part keeps: the checked reply, what produced it, and its review.

    Reviewed afterwards in admin, not approved first (docs/plan-framework.md, section 11).
    """

    class Review(models.TextChoices):
        NOT_REVIEWED = "not_reviewed", "Not reviewed"
        OK = "ok", "OK"
        PROBLEM = "problem", "Problem"

    data = models.JSONField(help_text="The checked reply, as the app uses it.")
    repairs = models.JSONField(default=list, blank=True, help_text="What the code fixed in the AI's reply.")
    prompt_version = models.CharField(max_length=40)
    model = models.CharField(max_length=100, blank=True)
    prompt_tokens = models.PositiveIntegerField(null=True, blank=True)
    completion_tokens = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    review = models.CharField(max_length=20, choices=Review.choices, default=Review.NOT_REVIEWED)
    review_notes = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]


class PlanOutline(AIRecord):
    """An AI-written plan outline (docs/plan-framework.md, section 5), kept for review in admin.

    Learners don't see outlines yet: they arrive with lesson generation. Until then the
    team reviews them here to tune the prompt (framework section 11).
    """

    learner = models.ForeignKey(
        "accounts.LearnerProfile", on_delete=models.CASCADE, related_name="plan_outlines"
    )
    plan = models.ForeignKey(
        LearningPlan, on_delete=models.SET_NULL, null=True, blank=True, related_name="outlines",
        help_text="The plan the learner got at the same time, if any.",
    )
    is_active = models.BooleanField(
        default=False, help_text="The learner's plan (AI plans on). Shadow-mode outlines stay inactive."
    )
    setup_choice = models.CharField(
        max_length=20, blank=True,
        choices=[("curated", "CodeAgapay setup guide"), ("main", "VS Code, step by step"), ("alternative", "No-install way")],
        help_text="The setup option the learner chose. Required before any lesson opens; later lessons follow it.",
    )
    update_for_setup = models.BooleanField(
        default=False,
        help_text="After a setup change, the learner asked to rewrite lessons for it: each is rewritten when next opened.",
    )

    class Meta(AIRecord.Meta):
        constraints = [
            models.UniqueConstraint(fields=["learner"], condition=Q(is_active=True), name="one_active_outline")
        ]

    def __str__(self):
        return f"Outline for {self.learner.user} ({self.created_at:%Y-%m-%d})"


class GeneratedLesson(AIRecord):
    """One AI-written lesson of an outline (framework section 6), written when first opened.

    Regenerating (after a low score, or from admin) adds a new version and keeps the old
    ones for review; only the current version is shown.
    """

    outline = models.ForeignKey(PlanOutline, on_delete=models.CASCADE, related_name="lessons")
    key = models.CharField(max_length=10, help_text='The outline lesson it writes, e.g. "L3".')
    title = models.CharField(max_length=150)
    version = models.PositiveIntegerField(default=1)
    is_current = models.BooleanField(default=True)
    flags = models.JSONField(
        default=list, blank=True, help_text="Problems found automatically, for a person to check."
    )
    flagged = models.BooleanField(default=False, help_text="Has flags. Kept as a field so admin can filter on it.")

    class Meta(AIRecord.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["outline", "key"], condition=Q(is_current=True), name="one_current_lesson_per_key",
            )
        ]

    def __str__(self):
        return f"{self.key} {self.title} (v{self.version})"

    def save(self, *args, **kwargs):
        self.flagged = bool(self.flags)
        super().save(*args, **kwargs)


class LessonProgress(models.Model):
    """A learner's progress on one lesson of their AI plan (framework sections 7 and 8)."""

    class Status(models.TextChoices):
        TODO = "todo", "To do"
        IN_PROGRESS = "in_progress", "In progress"
        DONE = "done", "Done"
        SKIPPED = "skipped", "Skipped"

    outline = models.ForeignKey(PlanOutline, on_delete=models.CASCADE, related_name="progress")
    key = models.CharField(max_length=10)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TODO)
    shaky = models.BooleanField(default=False, help_text="Moved on after missing the check twice.")
    tries = models.PositiveIntegerField(default=0, help_text="Check attempts on the current version.")
    last_answers = models.JSONField(default=list, blank=True, help_text="The latest check answers, in order.")
    last_correct = models.JSONField(default=list, blank=True, help_text="Which of those were right.")
    rating = models.SmallIntegerField(default=0, help_text="1 helpful, -1 not helpful, 0 not rated.")
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["outline", "key"], name="one_progress_per_lesson")]

    def __str__(self):
        return f"{self.outline.learner.user} · {self.key} · {self.get_status_display()}"
