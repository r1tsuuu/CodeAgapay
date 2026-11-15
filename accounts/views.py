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


@login_not_required
def home(request):
    if not request.user.is_authenticated:
        return landing(request)
    profile = get_profile(request.user)
    if not profile.onboarded:
        return redirect("welcome")
    return redirect("plan")


HERO_GOALS = ("website", "automation", "data")


def landing(request):
    """The front page for visitors who aren't signed in. Paths and tracks are the live ones, never a fixed list.

    `?goal=<path>` picks the previewed goal, so the goal picker works without JavaScript.
    """
    from content.models import Track
    from diagnose.onboarding import available_paths
    from learning import preview

    previews = preview.previews(available_paths())
    slugs = [p.slug for p in previews]
    goal = request.GET.get("goal", "")
    selected = goal if goal in slugs else (slugs[0] if slugs else "")
    hero = [p for p in previews if p.slug in HERO_GOALS] or previews[:3]
    hero_slugs = [p.slug for p in hero]
    sample = next((p for p in previews if p.sample), None)
    all_sources = []
    for p in previews:
        all_sources += [s for s in p.sources if s not in all_sources]
    from content.models import Resource, Topic

    live = Track.objects.filter(is_active=True)
    stats = {
        "languages": live.count(),
        "topics": Topic.objects.filter(track__in=live).count(),
        "links": Resource.objects.filter(topic__track__in=live, is_active=True).count(),
    }
    return render(request, "accounts/landing.html", {
        "stats": stats if stats["topics"] else None,
        "previews": previews,
        "selected": selected,
        "hero_previews": hero,
        "hero_selected": goal if goal in hero_slugs else (hero_slugs[0] if hero_slugs else ""),
        "sample": sample.sample if sample else None,
        "sample_path": sample.title if sample else "",
        "all_sources": all_sources[:6],
        "tracks": Track.objects.filter(is_active=True),
        "ai_daily_limit": settings.AI_DAILY_LIMIT,
    })


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
    from learning import rewards

    progress = learning_profile.summary(profile)
    streak = rewards.weekly_streak(profile)
    return render(request, "accounts/profile.html", {
        "profile": profile,
        "progress": progress,
        "streak": streak,
        "badges": rewards.badges(profile, progress, streak),
        "target_date": learning_profile.target_date(profile),
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
