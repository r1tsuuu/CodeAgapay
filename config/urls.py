from django.contrib import admin
from django.urls import include, path

from content import review

urlpatterns = [
    # Before admin.site.urls, so admin's catch-all doesn't take these.
    path("admin/review/", review.queue, name="review_queue"),
    path("admin/review/<str:kind>/<int:pk>/approve/", review.approve, name="review_approve"),
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("", include("accounts.urls")),
    path("", include("diagnose.urls")),
    path("", include("learning.urls")),
    path("", include("assistant.urls")),
]
