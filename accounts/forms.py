import math

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import LearnerProfile


class SettingsForm(forms.ModelForm):
    hours_per_week = forms.IntegerField(
        min_value=1, max_value=40, label="Hours a week",
        help_text="Your plan is spread over new weeks. Your progress is kept.",
    )
    hint_style = forms.ChoiceField(
        choices=LearnerProfile.HintStyle.choices, widget=forms.RadioSelect, required=False,
        label="When you're stuck, what helps most?",
    )
    email_reminders = forms.BooleanField(
        required=False, label="Email me if I've been away for a week",
        help_text="At most one a week, with your next step. We stop after three if you don't come back.",
    )

    class Meta:
        model = LearnerProfile
        fields = ["hours_per_week", "hint_style", "email_reminders"]


class LearningSetupForm(SettingsForm):
    """The profile page's Learning setup: small changes that keep the plan as it is."""

    goal_text = forms.CharField(
        required=False, max_length=300, label="Your goal",
        help_text="Your plan stays the same. For a new plan built around a new goal, use Change my answers.",
    )
    experience = forms.ChoiceField(
        choices=LearnerProfile.Experience.choices, widget=forms.RadioSelect, required=False,
        label="Coding experience",
    )
    device = forms.ChoiceField(
        choices=[("", "Not sure"), *LearnerProfile.Device.choices], widget=forms.RadioSelect, required=False,
        label="What you learn on", help_text="New lessons and setup steps use its shortcuts and app names.",
    )

    target_date = forms.DateField(
        required=False, label="Date you're aiming to finish by",
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Leave it blank for no date. Your plan stays the same; it shows whether your pace fits the date.",
    )

    class Meta(SettingsForm.Meta):
        fields = ["goal_text", "hours_per_week", "target_date", "experience", "device", "hint_style",
                  "email_reminders"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from learning.profile import plan_started, target_date

        # Plans count their date as weeks from the day the plan started (target_weeks).
        self.plan_start = plan_started(self.instance)
        self.fields["target_date"].initial = target_date(self.instance)

    def clean_target_date(self):
        day = self.cleaned_data["target_date"]
        if day is not None and day <= timezone.localdate():
            raise forms.ValidationError("Pick a date after today.")
        return day

    def save(self, commit=True):
        day = self.cleaned_data.get("target_date")
        start = self.plan_start or timezone.localdate()
        self.instance.target_weeks = max(math.ceil((day - start).days / 7), 1) if day else None
        return super().save(commit=commit)


class DetailsForm(forms.ModelForm):
    """Name (on the login account) plus the optional school and role (on the profile)."""

    first_name = forms.CharField(max_length=150, label="First name")
    last_name = forms.CharField(max_length=150, required=False, label="Last name")

    class Meta:
        model = LearnerProfile
        fields = ["school", "role"]
        labels = {"school": "School or organisation", "role": "What you do"}
        widgets = {
            "school": forms.TextInput(attrs={"placeholder": "e.g. Ateneo de Manila University"}),
            "role": forms.TextInput(attrs={"placeholder": "e.g. student"}),
        }
        help_texts = {"school": "Optional.", "role": "Optional."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user = self.instance.user
        self.fields["first_name"].initial = user.first_name
        self.fields["last_name"].initial = user.last_name
        self.order_fields(["first_name", "last_name", "school", "role"])

    def save(self, commit=True):
        profile = super().save(commit=commit)
        user = profile.user
        user.first_name = self.cleaned_data["first_name"].strip()
        user.last_name = self.cleaned_data["last_name"].strip()
        get_user_model().objects.filter(pk=user.pk).update(first_name=user.first_name, last_name=user.last_name)
        return profile


class AvatarForm(forms.ModelForm):
    avatar = forms.ChoiceField(
        choices=[("", "Your first letter"), *LearnerProfile.Avatar.choices], widget=forms.RadioSelect,
        required=False, label="Choose your icon",
    )

    class Meta:
        model = LearnerProfile
        fields = ["avatar"]
