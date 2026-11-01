from django.conf import settings
from django.shortcuts import redirect, render

from .models import get_profile


def home(request):
    profile = get_profile(request.user)
    if not profile.onboarded:
        return redirect("welcome")
    return redirect("plan")


def welcome(request):
    return render(request, "accounts/welcome.html", {"ai_daily_limit": settings.AI_DAILY_LIMIT})
