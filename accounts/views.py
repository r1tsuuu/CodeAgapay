from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_not_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from learning.planner import active_plan, repace_plan

from .forms import AvatarForm, DetailsForm, LearningSetupForm, SettingsForm
from .models import LearnerProfile, get_profile


def home(request):
    profile = get_profile(request.user)
    if not profile.onboarded:
        return redirect("welcome")
    return redirect("plan")


def welcome(request):
    return render(request, "accounts/welcome.html", {"ai_daily_limit": settings.AI_DAILY_LIMIT})


def _save_setup(profile, form, old_hours):
    """Save learning-setup answers. New hours re-spread the same plan; progress is kept.

    `old_hours` is read before validation: validating copies the new answers onto the profile.
    """
    form.instance.reminders_asked = True
    form.save()
    current = active_plan(profile)
    if current is not None and profile.hours_per_week != old_hours:
        repace_plan(current, profile.hours_per_week)


def account_settings(request):
    """The old Settings page. Everything it held is on the profile page now; old links still work."""
    profile = get_profile(request.user)
    if not profile.onboarded:
        return redirect("welcome")
    if request.method == "POST":
        old_hours = profile.hours_per_week
        form = SettingsForm(request.POST, instance=profile)
        if form.is_valid():
            _save_setup(profile, form, old_hours)
            messages.success(request, "Your settings are saved.")
        else:
            return _render_profile(request, profile, setup_form=form)
    return redirect(f"{reverse('profile')}#learning-setup")


def _render_profile(request, profile, **forms):
    from learning import profile as learning_profile

    return render(request, "accounts/profile.html", {
        "profile": profile,
        "progress": learning_profile.summary(profile),
        "setup_method": learning_profile.setup_method(profile),
        "icon_form": forms.get("icon_form") or AvatarForm(instance=profile),
        "details_form": forms.get("details_form") or DetailsForm(instance=profile),
        "setup_form": forms.get("setup_form") or LearningSetupForm(instance=profile),
        # A form that failed validation opens its section, so the errors are seen.
        "open": next((name for name in ("icon_form", "details_form", "setup_form") if name in forms), ""),
    }, status=400 if forms else 200)


def profile_page(request):
    profile = get_profile(request.user)
    if not profile.onboarded:
        return redirect("welcome")
    return _render_profile(request, profile)


@require_POST
def profile_icon(request):
    profile = get_profile(request.user)
    form = AvatarForm(request.POST, instance=profile)
    if not form.is_valid():
        return _render_profile(request, profile, icon_form=form)
    form.save()
    messages.success(request, "Your icon is updated.")
    return redirect("profile")


@require_POST
def profile_details(request):
    profile = get_profile(request.user)
    form = DetailsForm(request.POST, instance=profile)
    if not form.is_valid():
        return _render_profile(request, profile, details_form=form)
    form.save()
    messages.success(request, "Your details are saved.")
    return redirect("profile")


@require_POST
def profile_setup(request):
    profile = get_profile(request.user)
    old_hours = profile.hours_per_week
    form = LearningSetupForm(request.POST, instance=profile)
    if not form.is_valid():
        return _render_profile(request, get_profile(request.user), setup_form=form)
    _save_setup(profile, form, old_hours)
    messages.success(request, "Your learning setup is saved. Your plan and progress are kept.")
    return redirect(f"{reverse('profile')}#learning-setup")


def delete_account(request):
    """Asks first (GET), then deletes the login and everything linked to it (POST)."""
    if request.method == "POST":
        if request.POST.get("confirm") != "delete":
            messages.error(request, 'Type "delete" to confirm.')
            return redirect("delete_account")
        user = request.user
        logout(request)
        user.delete()  # Cascades to the profile, plans, progress, answers and AI usage.
        messages.success(request, "Your account and data are deleted. Thanks for learning with CodeAgapay.")
        return redirect("account_login")
    return render(request, "accounts/delete_account.html")


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
