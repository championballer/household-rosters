import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(name="Member", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("name", models.CharField(max_length=80)),
            ("normalized_name", models.CharField(editable=False, max_length=240, unique=True)),
            ("is_active", models.BooleanField(default=True)),
            ("version", models.PositiveIntegerField(default=0)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
        ]),
        migrations.CreateModel(name="Roster", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("name", models.CharField(max_length=120)),
            ("description", models.TextField(blank=True)),
            ("is_archived", models.BooleanField(default=False)),
            ("version", models.PositiveIntegerField(default=0)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
        ]),
        migrations.CreateModel(name="RosterParticipant", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("position", models.PositiveIntegerField(default=0)),
            ("is_enabled", models.BooleanField(default=True)),
            ("member", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="roster_links", to="rosters.member")),
            ("roster", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="participants", to="rosters.roster")),
        ], options={"ordering": ("position", "id")}),
        migrations.AddConstraint(model_name="rosterparticipant", constraint=models.UniqueConstraint(fields=("roster", "member"), name="unique_roster_member")),
        migrations.AddField(model_name="roster", name="current_participant", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="current_for_rosters", to="rosters.rosterparticipant")),
        migrations.CreateModel(name="AuditEvent", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("event_type", models.CharField(choices=[("CREATE", "Create"), ("EDIT", "Edit"), ("PARTICIPANTS_CHANGED", "Participants Changed"), ("CURRENT_CHANGED", "Current Changed"), ("COMPLETE", "Complete"), ("SUBSTITUTE_COMPLETE", "Substitute Complete"), ("SKIP", "Skip"), ("UNDO", "Undo"), ("ARCHIVE", "Archive"), ("RESTORE", "Restore"), ("MEMBER_DEACTIVATED", "Member Deactivated"), ("MEMBER_REACTIVATED", "Member Reactivated"), ("MEMBER_RENAMED", "Member Renamed")], max_length=32)),
            ("occurred_at", models.DateTimeField(auto_now_add=True)),
            ("actor_name_snapshot", models.CharField(blank=True, max_length=80)),
            ("completed_by_name_snapshot", models.CharField(blank=True, max_length=80)),
            ("assigned_member_name_snapshot", models.CharField(blank=True, max_length=80)),
            ("next_member_name_snapshot", models.CharField(blank=True, max_length=80)),
            ("version_before", models.PositiveIntegerField(default=0)),
            ("version_after", models.PositiveIntegerField(default=0)),
            ("before_state", models.JSONField(default=dict)),
            ("after_state", models.JSONField(default=dict)),
            ("request_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
            ("note", models.CharField(blank=True, max_length=240)),
            ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="acted_events", to="rosters.member")),
            ("assigned_member", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assigned_events", to="rosters.member")),
            ("completed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="completed_events", to="rosters.member")),
            ("next_member", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="next_events", to="rosters.member")),
            ("reverses_event", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="corrections", to="rosters.auditevent")),
            ("roster", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="rosters.roster")),
        ], options={"ordering": ("-occurred_at", "-id")}),
        migrations.CreateModel(name="MemberAuditEvent", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("event_type", models.CharField(max_length=32)),
            ("member_name_snapshot", models.CharField(max_length=80)),
            ("actor_name_snapshot", models.CharField(blank=True, max_length=80)),
            ("occurred_at", models.DateTimeField(auto_now_add=True)),
            ("request_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
            ("before_state", models.JSONField(default=dict)),
            ("after_state", models.JSONField(default=dict)),
            ("member", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="member_events", to="rosters.member")),
        ]),
    ]
