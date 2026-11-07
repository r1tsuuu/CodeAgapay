from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from learning.planner import active_plan, repace_plan

from .forms import SettingsForm
from .models import LearnerProfile, get_profile


def home(request):
    profile = get_profile(request.user)
    if not profile.onboarded:
        return redirect("welcome")
    return redirect("plan")


def welcome(request):
    return render(request, "accounts/welcome.html", {"ai_daily_limit": settings.AI_DAILY_LIMIT})


def account_settings(request):
    profile = get_profile(request.user)
    if not profile.onboarded:
        return redirect("welcome")
    old_hours = profile.hours_per_week
    form = SettingsForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.instance.reminders_asked = True
        form.save()
        current = active_plan(profile)
        if current is not None and profile.hours_per_week != old_hours:
            repace_plan(current, profile.hours_per_week)
        messages.success(request, "Your settings are saved.")
        return redirect("account_settings")
    return render(request, "accounts/settings.html", {"form": form})


@require_POST
def reminder_choice(request):
    """The learner's answer to the one-time question on the plan page."""
    profile = get_profile(request.user)
    profile.email_reminders = request.POST.get("choice") == "yes"
    profile.reminders_asked = True
    profile.save(update_fields=["email_reminders", "reminders_asked"])
    if profile.email_reminders:
        messages.success(request, "Reminders are on. You can change this in Settings.")
    return redirect("plan")


@login_not_required
@csrf_exempt  # The secret key in the link is the proof, and mail apps post here without a session.
def unsubscribe(request, key):
    """Works without logging in. GET only asks, because mail scanners open links in emails."""
    profile = get_object_or_404(LearnerProfile, unsubscribe_key=key)
    if request.method == "POST":
        profile.email_reminders = False
        profile.save(update_fields=["email_reminders"])
    return render(request, "accounts/unsubscribe.html", {"done": not profile.email_reminders})
