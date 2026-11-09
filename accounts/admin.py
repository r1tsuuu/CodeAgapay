from django.contrib import admin, messages

from .models import LearnerProfile


@admin.register(LearnerProfile)
class LearnerProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "track", "experience", "hours_per_week", "onboarded", "email_reminders", "ai_plans_early"]
    list_filter = ["track", "onboarded", "experience", "ai_plans_early"]
    search_fields = ["user__email"]
    actions = ["give_ai_plans_early", "take_ai_plans_early"]

    @admin.action(description="Give AI plans early (they get one the next time they build a plan)")
    def give_ai_plans_early(self, request, queryset):
        count = queryset.update(ai_plans_early=True)
        self.message_user(request, f"{count} learner{'s' if count != 1 else ''} will get AI plans early.", messages.SUCCESS)

    @admin.action(description="Take away early AI plans (back to curated plans)")
    def take_ai_plans_early(self, request, queryset):
        count = queryset.update(ai_plans_early=False)
        self.message_user(request, f"{count} learner{'s' if count != 1 else ''} back on curated plans.", messages.SUCCESS)
