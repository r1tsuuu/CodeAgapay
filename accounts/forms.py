from django import forms

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
