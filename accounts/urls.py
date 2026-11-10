from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("welcome/", views.welcome, name="welcome"),
    path("profile/", views.profile_page, name="profile"),
    path("profile/icon/", views.profile_icon, name="profile_icon"),
    path("profile/details/", views.profile_details, name="profile_details"),
    path("profile/setup/", views.profile_setup, name="profile_setup"),
    path("profile/delete/", views.delete_account, name="delete_account"),
    path("settings/", views.account_settings, name="account_settings"),
    path("settings/reminders/", views.reminder_choice, name="reminder_choice"),
    path("unsubscribe/<uuid:key>/", views.unsubscribe, name="unsubscribe"),
]
