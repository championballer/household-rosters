from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("health/", views.health, name="health"),
    path("api/dashboard/", views.dashboard_api, name="dashboard_api"),
    path("identity/", views.identity, name="identity"),
    path("identity/forget/", views.forget_identity, name="forget_identity"),
    path("members/", views.members, name="members"),
    path("members/<int:member_id>/edit/", views.member_edit, name="member_edit"),
    path("members/<int:member_id>/<str:action>/", views.member_status, name="member_status"),
    path("rosters/new/", views.roster_new, name="roster_new"),
    path("rosters/<int:roster_id>/", views.roster_detail, name="roster_detail"),
    path("rosters/<int:roster_id>/edit/", views.roster_edit, name="roster_edit"),
    path("rosters/<int:roster_id>/complete/", views.turn_action, {"action": "complete"}, name="roster_complete"),
    path("rosters/<int:roster_id>/substitute/", views.turn_action, {"action": "substitute"}, name="roster_substitute"),
    path("rosters/<int:roster_id>/skip/", views.turn_action, {"action": "skip"}, name="roster_skip"),
    path("rosters/<int:roster_id>/undo/", views.undo, name="roster_undo"),
    path("rosters/<int:roster_id>/current/", views.change_turn, name="roster_current"),
    path("rosters/<int:roster_id>/archive/", views.roster_status, {"action": "archive"}, name="roster_archive"),
    path("rosters/<int:roster_id>/restore/", views.roster_status, {"action": "restore"}, name="roster_restore"),
    path("rosters/<int:roster_id>/history/", views.history, name="roster_history"),
    path("rosters/<int:roster_id>/history.csv", views.history_csv, name="roster_history_csv"),
    path("archived/", views.archived, name="archived"),
]
