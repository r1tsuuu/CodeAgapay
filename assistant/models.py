from django.db import models


class HelpFeedback(models.Model):
    """A thumbs up or down on an Agapay reply, or a reported problem. Never stores the question or reply."""

    class Rating(models.IntegerChoices):
        UP = 1, "Helpful"
        DOWN = -1, "Not helpful"
        REPORT = 0, "Reported a problem"

    learner = models.ForeignKey("accounts.LearnerProfile", on_delete=models.CASCADE, related_name="help_feedback")
    where = models.CharField(max_length=210, help_text="The topic slug, or the AI lesson key.")
    action = models.CharField(max_length=20)
    mode = models.CharField(max_length=10, help_text="ai or fallback")
    rating = models.SmallIntegerField(choices=Rating.choices)
    note = models.CharField(max_length=500, blank=True, help_text="What the learner says went wrong (reports only).")
    created_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "help feedback"

    def __str__(self):
        return f"{self.get_rating_display()} · {self.action} · {self.where}"


class AIUsage(models.Model):
    """A learner's AI use on one day. Never stores question or chat text."""

    learner = models.ForeignKey(
        "accounts.LearnerProfile", on_delete=models.CASCADE, related_name="ai_usage"
    )
    date = models.DateField()
    messages_used = models.PositiveIntegerField(default=0)
    intakes_used = models.PositiveIntegerField(
        default=0, help_text="Plan conversations started (the AI intake on /start/)."
    )
    lessons_used = models.PositiveIntegerField(
        default=0, help_text="AI-written lessons, first versions and rewrites."
    )

    class Meta:
        verbose_name_plural = "AI usage"
        constraints = [
            models.UniqueConstraint(fields=["learner", "date"], name="one_usage_row_per_day")
        ]

    def __str__(self):
        return f"{self.learner.user} · {self.date} · {self.messages_used}"
