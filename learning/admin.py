from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from .models import LearningPlan, PlanFeedback, PlanItem, PlanOutline, PracticeSubmission, QuizAttempt


class PlanItemInline(admin.TabularInline):
    model = PlanItem
    extra = 0
    fields = ["order", "week", "topic", "status", "shaky", "completed_at"]


@admin.register(LearningPlan)
class LearningPlanAdmin(admin.ModelAdmin):
    list_display = ["learner", "track", "created_at", "is_active"]
    list_filter = ["track", "is_active"]
    inlines = [PlanItemInline]


@admin.register(QuizAttempt)
class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = ["learner", "quiz_item", "answer", "is_correct", "created_at"]
    list_filter = ["is_correct", "quiz_item__topic__track"]


@admin.register(PlanFeedback)
class PlanFeedbackAdmin(admin.ModelAdmin):
    list_display = ["text", "plan", "created_at", "resolved"]
    list_editable = ["resolved"]
    list_filter = ["resolved"]


@admin.register(PracticeSubmission)
class PracticeSubmissionAdmin(admin.ModelAdmin):
    list_display = ["learner", "task", "mode", "created_at"]
    list_filter = ["mode", "task__topic__track"]
    readonly_fields = ["learner", "task", "answer", "feedback", "mode", "created_at"]


class RandomSampleFilter(admin.SimpleListFilter):
    """The weekly review's random sample (framework section 11). A new sample on each load."""

    title = "sample"
    parameter_name = "sample"

    def lookups(self, request, model_admin):
        return [("10", "10 random")]

    def queryset(self, request, queryset):
        if self.value() == "10":
            ids = list(queryset.order_by("?").values_list("pk", flat=True)[:10])
            return queryset.filter(pk__in=ids)
        return queryset


@admin.register(PlanOutline)
class PlanOutlineAdmin(admin.ModelAdmin):
    list_display = ["learner", "created_at", "lesson_count", "repair_count", "tokens", "prompt_version", "review"]
    list_filter = ["review", "prompt_version", RandomSampleFilter]
    search_fields = ["learner__user__username", "learner__user__email"]
    readonly_fields = [
        "learner", "plan", "created_at", "prompt_version", "model", "prompt_tokens", "completion_tokens",
        "repairs", "outline", "reviewed_by", "reviewed_at",
    ]
    fields = [
        "review", "review_notes", "reviewed_by", "reviewed_at", "outline", "repairs",
        "learner", "plan", "created_at", "prompt_version", "model", "prompt_tokens", "completion_tokens",
    ]
    actions = ["mark_ok", "mark_problem"]

    @admin.display(description="Lessons")
    def lesson_count(self, obj):
        return obj.data.get("lessons_total")

    @admin.display(description="Repairs")
    def repair_count(self, obj):
        return len(obj.repairs)

    @admin.display(description="Tokens in / out")
    def tokens(self, obj):
        return f"{obj.prompt_tokens or '?'} / {obj.completion_tokens or '?'}"

    @admin.display(description="Outline")
    def outline(self, obj):
        """The outline as a reviewer reads it, not raw JSON."""
        data = obj.data
        head = format_html(
            "<p><b>Goal:</b> {}<br><b>Level:</b> {} · {} lessons · {} hours · {} weeks</p>"
            "<p><b>Assumptions:</b> {}</p><p><b>Conflict:</b> {}</p>",
            data.get("goal", ""), data.get("level", ""), data.get("lessons_total", 0),
            round(data.get("minutes_total", 0) / 60, 1), data.get("weeks_total", 0),
            "; ".join(data.get("assumptions", [])), data.get("conflict") or "none",
        )
        modules = format_html_join("", "<p><b>{}: {}</b><br><i>{}</i><br>{}<br>Milestone: {}</p>", (
            (m["progress"], m["title"], m.get("goal", ""),
             format_html_join(format_html("<br>"), "{} · week {} · {} min · {}{} — {}", (
                 (lesson["key"], lesson["week"], lesson["minutes"], lesson["kind"],
                  f" (needs {', '.join(lesson['needs'])})" if lesson["needs"] else "", lesson["title"])
                 for lesson in m["lessons"]
             )),
             m.get("milestone") or "none")
            for m in data.get("modules", [])
        ))
        project = data.get("project") or {}
        steps = format_html_join(format_html("<br>"), "Week {}: {}", (
            (step.get("week"), step.get("text")) for step in project.get("milestones", [])
        ))
        return head + modules + format_html(
            "<p><b>Project:</b> {}<br>{}<br>{}<br>Done when: {}</p><p><b>Next steps:</b> {}</p>",
            project.get("title", ""), project.get("description", ""), steps,
            "; ".join(project.get("done_when", [])), "; ".join(data.get("next_steps", [])),
        )

    def _mark(self, request, queryset, review):
        count = queryset.update(review=review, reviewed_by=request.user, reviewed_at=timezone.now())
        self.message_user(request, f"Marked {count} outline{'s' if count != 1 else ''} {review.label}.", messages.SUCCESS)

    @admin.action(description="Mark OK")
    def mark_ok(self, request, queryset):
        self._mark(request, queryset, PlanOutline.Review.OK)

    @admin.action(description="Mark problem (add a note on each)")
    def mark_problem(self, request, queryset):
        self._mark(request, queryset, PlanOutline.Review.PROBLEM)

    def save_model(self, request, obj, form, change):
        if "review" in form.changed_data:
            obj.reviewed_by, obj.reviewed_at = request.user, timezone.now()
        super().save_model(request, obj, form, change)

    def has_add_permission(self, request):
        return False
