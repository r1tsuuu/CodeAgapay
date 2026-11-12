from django.contrib import admin

from .forms import PracticeTaskForm, ProjectIdeaForm, QuizItemForm, SkillQuestionForm, TopicForm
from .models import (
    Path, PathTrack, PracticeTask, ProjectIdea, QuizItem, Resource, SetupStep, SkillQuestion, Tip, Topic, Track,
)


class SetupStepInline(admin.StackedInline):
    model = SetupStep
    extra = 0


class ProjectIdeaInline(admin.StackedInline):
    model = ProjectIdea
    form = ProjectIdeaForm
    extra = 0


class TopicInline(admin.TabularInline):
    model = Topic
    fields = ["title", "order", "estimated_minutes"]
    show_change_link = True
    extra = 0


@admin.register(Track)
class TrackAdmin(admin.ModelAdmin):
    list_display = ["name", "order", "is_active"]
    list_editable = ["order", "is_active"]
    prepopulated_fields = {"slug": ["name"]}
    fields = ["name", "slug", "description", "order", "is_active", "setup_check"]
    inlines = [TopicInline, SetupStepInline, ProjectIdeaInline]


class ResourceInline(admin.TabularInline):
    model = Resource
    fields = ["title", "url", "kind", "estimated_minutes", "order", "is_active", "link_status", "last_checked"]
    readonly_fields = ["link_status", "last_checked"]
    extra = 0


class TipInline(admin.TabularInline):
    model = Tip
    extra = 0


class SkillQuestionInline(admin.StackedInline):
    model = SkillQuestion
    form = SkillQuestionForm
    extra = 0


class QuizItemInline(admin.StackedInline):
    model = QuizItem
    form = QuizItemForm
    extra = 0


class PracticeTaskInline(admin.StackedInline):
    model = PracticeTask
    form = PracticeTaskForm
    extra = 0


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    form = TopicForm
    list_display = ["title", "track", "order", "estimated_minutes", "intro_approved"]
    list_editable = ["order", "estimated_minutes", "intro_approved"]
    actions = ["approve_intros", "hide_intros"]

    @admin.action(description="Approve intro (learners see it)")
    def approve_intros(self, request, queryset):
        count = queryset.update(intro_approved=True)
        self.message_user(request, f"Approved {count} intro{'s' if count != 1 else ''}.")

    @admin.action(description="Hide intro")
    def hide_intros(self, request, queryset):
        count = queryset.update(intro_approved=False)
        self.message_user(request, f"Hid {count} intro{'s' if count != 1 else ''}.")
    list_filter = ["track", "intro_approved"]
    search_fields = ["title", "summary"]
    prepopulated_fields = {"slug": ["title"]}
    filter_horizontal = ["prerequisites"]
    inlines = [ResourceInline, TipInline, PracticeTaskInline, SkillQuestionInline, QuizItemInline]


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ["title", "topic", "kind", "is_active", "link_status", "link_note", "last_checked"]
    list_filter = ["link_status", "kind", "is_active", "topic__track"]
    search_fields = ["title", "url"]
    readonly_fields = ["link_status", "link_note", "failed_checks", "last_checked"]


@admin.register(SkillQuestion)
class SkillQuestionAdmin(admin.ModelAdmin):
    form = SkillQuestionForm
    list_display = ["__str__", "topic", "order"]
    list_filter = ["topic__track"]


@admin.register(QuizItem)
class QuizItemAdmin(admin.ModelAdmin):
    form = QuizItemForm
    list_display = ["__str__", "topic"]
    list_filter = ["topic__track"]


@admin.register(PracticeTask)
class PracticeTaskAdmin(admin.ModelAdmin):
    form = PracticeTaskForm
    list_display = ["__str__", "topic", "approved"]
    list_editable = ["approved"]
    list_filter = ["approved", "topic__track"]
    actions = ["approve_tasks", "hide_tasks"]

    @admin.action(description="Approve (learners see it)")
    def approve_tasks(self, request, queryset):
        count = queryset.update(approved=True)
        self.message_user(request, f"Approved {count} task{'s' if count != 1 else ''}.")

    @admin.action(description="Hide")
    def hide_tasks(self, request, queryset):
        count = queryset.update(approved=False)
        self.message_user(request, f"Hid {count} task{'s' if count != 1 else ''}.")


@admin.register(SetupStep)
class SetupStepAdmin(admin.ModelAdmin):
    list_display = ["title", "track", "order"]
    list_filter = ["track"]


class PathTrackInline(admin.TabularInline):
    model = PathTrack
    extra = 0


@admin.register(Path)
class PathAdmin(admin.ModelAdmin):
    list_display = ["title", "tagline", "order", "is_active"]
    list_editable = ["order", "is_active"]
    prepopulated_fields = {"slug": ["title"]}
    inlines = [PathTrackInline]


@admin.register(ProjectIdea)
class ProjectIdeaAdmin(admin.ModelAdmin):
    form = ProjectIdeaForm
    list_display = ["title", "track", "order", "is_active"]
    list_filter = ["track", "is_active"]


admin.site.register(Tip)
admin.site.site_header = "CodeAgapay content admin"
admin.site.site_title = "CodeAgapay admin"

# The admin home page links to the review queue, with how many drafts wait there.
admin.site.index_template = "admin/codeagapay_index.html"
_default_index = admin.site.index


def _index(request, extra_context=None):
    from .review import waiting_count

    return _default_index(request, {**(extra_context or {}), "review_waiting": waiting_count()})


admin.site.index = _index
