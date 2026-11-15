from django.contrib import admin

from .models import AIUsage, HelpFeedback


@admin.register(AIUsage)
class AIUsageAdmin(admin.ModelAdmin):
    list_display = ["learner", "date", "messages_used", "intakes_used", "lessons_used"]
    list_filter = ["date"]


@admin.register(HelpFeedback)
class HelpFeedbackAdmin(admin.ModelAdmin):
    """Thumbs and reports on Agapay replies. Filter on Not helpful or Reported, check the topic, tick Resolved."""

    list_display = ["created_at", "rating", "action", "mode", "where", "note", "resolved"]
    list_filter = ["rating", "action", "mode", "resolved"]
    list_editable = ["resolved"]
    readonly_fields = ["learner", "where", "action", "mode", "rating", "note", "created_at"]
