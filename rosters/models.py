import uuid
from django.core.exceptions import ValidationError
from django.db import models


def normalize_name(value):
    return " ".join((value or "").split()).casefold()


class Member(models.Model):
    name = models.CharField(max_length=80)
    normalized_name = models.CharField(max_length=240, unique=True, editable=False)
    is_active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        self.name = " ".join(self.name.split())
        if not self.name:
            raise ValidationError({"name": "Enter a name."})
        self.normalized_name = normalize_name(self.name)

    def save(self, *args, **kwargs):
        self.name = " ".join(self.name.split())
        self.normalized_name = normalize_name(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Roster(models.Model):
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_archived = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    current_participant = models.ForeignKey(
        "RosterParticipant", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="current_for_rosters",
    )

    def __str__(self):
        return self.name


class RosterParticipant(models.Model):
    roster = models.ForeignKey(Roster, on_delete=models.CASCADE, related_name="participants")
    member = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="roster_links")
    position = models.PositiveIntegerField(default=0)
    is_enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ("position", "id")
        constraints = [models.UniqueConstraint(fields=("roster", "member"), name="unique_roster_member")]

    @property
    def eligible(self):
        return self.is_enabled and self.member.is_active

    def __str__(self):
        return f"{self.member.name} ({self.roster.name})"


class AuditEvent(models.Model):
    TYPES = [(x, x.replace("_", " ").title()) for x in (
        "CREATE", "EDIT", "PARTICIPANTS_CHANGED", "CURRENT_CHANGED", "COMPLETE",
        "SUBSTITUTE_COMPLETE", "SKIP", "UNDO", "ARCHIVE", "RESTORE",
        "MEMBER_DEACTIVATED", "MEMBER_REACTIVATED", "MEMBER_RENAMED",
    )]
    roster = models.ForeignKey(Roster, on_delete=models.PROTECT, related_name="events")
    event_type = models.CharField(max_length=32, choices=TYPES)
    occurred_at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(Member, null=True, blank=True, on_delete=models.SET_NULL, related_name="acted_events")
    actor_name_snapshot = models.CharField(max_length=80, blank=True)
    completed_by = models.ForeignKey(Member, null=True, blank=True, on_delete=models.SET_NULL, related_name="completed_events")
    completed_by_name_snapshot = models.CharField(max_length=80, blank=True)
    assigned_member = models.ForeignKey(Member, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_events")
    assigned_member_name_snapshot = models.CharField(max_length=80, blank=True)
    next_member = models.ForeignKey(Member, null=True, blank=True, on_delete=models.SET_NULL, related_name="next_events")
    next_member_name_snapshot = models.CharField(max_length=80, blank=True)
    version_before = models.PositiveIntegerField(default=0)
    version_after = models.PositiveIntegerField(default=0)
    before_state = models.JSONField(default=dict)
    after_state = models.JSONField(default=dict)
    request_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    reverses_event = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="corrections")
    note = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ("-occurred_at", "-id")


class MemberAuditEvent(models.Model):
    event_type = models.CharField(max_length=32)
    member = models.ForeignKey(Member, null=True, blank=True, on_delete=models.SET_NULL, related_name="member_events")
    member_name_snapshot = models.CharField(max_length=80)
    actor_name_snapshot = models.CharField(max_length=80, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)
    request_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    before_state = models.JSONField(default=dict)
    after_state = models.JSONField(default=dict)
