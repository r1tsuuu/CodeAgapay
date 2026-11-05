from django.contrib import admin

from .models import LearningPlan, PlanFeedback, PlanItem, PracticeSubmission, QuizAttempt


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
