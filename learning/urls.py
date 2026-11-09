from django.urls import path

from . import ai_views, views

urlpatterns = [
    path("plan/build/", views.plan_build, name="plan_build"),
    path("plan/", views.plan, name="plan"),
    path("plan/finished/", views.plan_finish, name="plan_finish"),
    path("plan/items/<int:item_id>/status/", views.plan_item_status, name="plan_item_status"),
    path("plan/items/<int:item_id>/move-on/", views.plan_item_shaky, name="plan_item_shaky"),
    path("plan/pace/", views.plan_pace, name="plan_pace"),
    path("plan/report/", views.plan_report, name="plan_report"),
    path("plan/retry/", ai_views.plan_retry, name="ai_plan_retry"),
    path("plan/lessons/<str:key>/", ai_views.lesson, name="ai_lesson"),
    path("plan/lessons/<str:key>/check/", ai_views.check, name="ai_lesson_check"),
    path("plan/lessons/<str:key>/rewrite/", ai_views.rewrite, name="ai_lesson_rewrite"),
    path("plan/lessons/<str:key>/move-on/", ai_views.move_on, name="ai_lesson_move_on"),
    path("plan/lessons/<str:key>/status/", ai_views.status, name="ai_lesson_status"),
    path("plan/lessons/<str:key>/rate/", ai_views.rate, name="ai_lesson_rate"),
    path("plan/lessons/<str:key>/set-up/", ai_views.setup_done, name="ai_setup_done"),
    path("plan/lessons/<str:key>/update-lessons/", ai_views.update_lessons, name="ai_update_lessons"),
    path("learn/<slug:track>/setup/", views.setup_guide, name="setup_guide"),
    path("learn/<slug:topic>/", views.lesson, name="lesson"),
    path("learn/<slug:topic>/practice/", views.practice, name="practice"),
    path("learn/<slug:topic>/quiz/", views.quiz, name="quiz"),
    path("learn/<slug:topic>/quiz/result/", views.quiz_result, name="quiz_result"),
]
