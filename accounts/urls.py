from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("welcome/", views.welcome, name="welcome"),
    path("settings/", views.account_settings, name="account_settings"),
    path("settings/reminders/", views.reminder_choice, name="reminder_choice"),
    path("unsubscribe/<uuid:key>/", views.unsubscribe, name="unsubscribe"),
]
