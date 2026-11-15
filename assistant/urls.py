from django.urls import path

from . import views

urlpatterns = [
    path("help/ask/", views.ask, name="help_ask"),
    path("help/feedback/", views.feedback, name="help_feedback"),
]
