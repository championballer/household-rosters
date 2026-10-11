"""Transactional roster rules. Views should call these functions, never edit turns directly."""
import uuid
from dataclasses import dataclass

from django.db import IntegrityError, OperationalError, transaction
from django.db.models import F
from django.utils import timezone

from .models import AuditEvent, Member, MemberAuditEvent, Roster, RosterParticipant, normalize_name


class Conflict(Exception):
    pass


class InvalidAction(Exception):
    pass


@dataclass
class MutationResult:
    event: AuditEvent
    replayed: bool = False


def create_member(request_id, actor, name):
    existing = MemberAuditEvent.objects.filter(request_id=request_id).first()
    if existing:
        if existing.event_type != "MEMBER_CREATED":
            raise InvalidAction("That request identifier was already used.")
        return existing.member
    try:
        with transaction.atomic():
            member = Member.objects.create(name=name.strip())
            MemberAuditEvent.objects.create(
                event_type="MEMBER_CREATED", member=member, member_name_snapshot=member.name,
                actor_name_snapshot=actor.name if actor else "", request_id=request_id,
                before_state={}, after_state={"name": member.name, "is_active": True},
            )
        return member
    except IntegrityError:
        existing = MemberAuditEvent.objects.filter(request_id=request_id, event_type="MEMBER_CREATED").first()
        if existing:
            return existing.member
        raise


def eligible(roster):
    return list(roster.participants.select_related("member").filter(is_enabled=True, member__is_active=True).order_by("position", "id"))


def state(roster):
    participants = list(roster.participants.select_related("member").order_by("position", "id"))
    current = roster.current_participant
    return {
        "name": roster.name, "description": roster.description, "is_archived": roster.is_archived,
        "participants": [{"id": p.id, "member_id": p.member_id, "member_name": p.member.name,
                           "position": p.position, "is_enabled": p.is_enabled} for p in participants],
        "current_participant_id": current.id if current else None,
        "current_member_id": current.member_id if current else None,
        "current_member_name": current.member.name if current else None,
    }


def _snapshot_member(member):
    if isinstance(member, RosterParticipant):
        member = member.member
    return member.name if member else ""


def _event(roster, event_type, actor, before, version_before, request_id, *, completed_by=None,
           assigned=None, next_person=None, note="", reverses=None):
    if isinstance(assigned, RosterParticipant):
        assigned = assigned.member
    if isinstance(next_person, RosterParticipant):
        next_person = next_person.member
    return AuditEvent.objects.create(
        roster=roster, event_type=event_type, actor=actor, actor_name_snapshot=_snapshot_member(actor),
        completed_by=completed_by, completed_by_name_snapshot=_snapshot_member(completed_by),
        assigned_member=assigned, assigned_member_name_snapshot=_snapshot_member(assigned),
        next_member=next_person, next_member_name_snapshot=_snapshot_member(next_person),
        before_state=before, after_state=state(roster), version_before=version_before,
        version_after=roster.version, request_id=request_id, note=note, reverses_event=reverses,
    )


def _existing(roster_id, request_id):
    if not request_id:
        return None
    return AuditEvent.objects.filter(request_id=request_id).first()


def mutate(roster_id, expected_version, request_id, actor, event_type, operation, *, note=""):
    """CAS version before reads/writes; the conditional update obtains SQLite's writer lock."""
    existing = _existing(roster_id, request_id)
    if existing:
        if existing.roster_id != roster_id or existing.event_type != event_type:
            raise InvalidAction("That request identifier was already used for another action.")
        return MutationResult(existing, True)
    try:
        with transaction.atomic():
            changed = Roster.objects.filter(pk=roster_id, version=expected_version).update(version=F("version") + 1)
            if changed != 1:
                raise Conflict("This roster changed. Refresh and try again.")
            roster = Roster.objects.get(pk=roster_id)
            version_before = expected_version
            before = state(roster)
            roster.version = expected_version + 1
            metadata = operation(roster)
            roster.updated_at = timezone.now()
            roster.save()
            event = _event(roster, event_type, actor, before, version_before, request_id,
                           note=note, **metadata)
            return MutationResult(event)
    except Conflict:
        existing = _existing(roster_id, request_id)
        if existing and existing.event_type == event_type:
            return MutationResult(existing, True)
        raise
    except OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            raise Conflict("The database is busy. Retry this action shortly.") from exc
        raise

def _active_actor(actor):
    if not actor or not actor.is_active:
        raise InvalidAction("Choose an active household member first.")


def _current(roster):
    participants = eligible(roster)
    current = roster.current_participant
    if not participants:
        if current:
            raise InvalidAction("This roster has no eligible participants. Refresh it.")
        return participants, None
    if not current or current not in participants:
        raise InvalidAction("This roster needs a starting person. Edit the roster first.")
    return participants, current


def _next(participants, current):
    if not participants:
        return None
    index = next((i for i, p in enumerate(participants) if p.pk == current.pk), None)
    if index is None:
        raise InvalidAction("The current person is no longer eligible. Refresh the roster.")
    return participants[(index + 1) % len(participants)]


def perform_turn(roster_id, expected_version, request_id, actor, action, actual_member=None):
    _active_actor(actor)
    event_type = {"complete": "COMPLETE", "substitute": "SUBSTITUTE_COMPLETE", "skip": "SKIP"}.get(action)
    if not event_type:
        raise InvalidAction("Unknown turn action.")

    def operation(roster):
        if roster.is_archived:
            raise InvalidAction("Archived rosters cannot be changed.")
        participants, assigned_link = _current(roster)
        if not assigned_link:
            raise InvalidAction("Add participants before completing this roster.")
        if action == "substitute":
            if not actual_member or not actual_member.is_active:
                raise InvalidAction("Choose who actually completed this responsibility.")
            completed = actual_member
        elif action == "complete":
            completed = assigned_link.member
        else:
            completed = None
        successor = _next(participants, assigned_link)
        roster.current_participant = successor
        return {"assigned": assigned_link.member, "completed_by": completed, "next_person": successor}

    return mutate(roster_id, expected_version, request_id, actor, event_type, operation)


def change_current(roster_id, expected_version, request_id, actor, participant_id):
    _active_actor(actor)
    def operation(roster):
        if roster.is_archived:
            raise InvalidAction("Archived rosters cannot be changed.")
        target = next((p for p in eligible(roster) if p.pk == participant_id), None)
        if not target:
            raise InvalidAction("Choose an eligible participant in this roster.")
        roster.current_participant = target
        return {"assigned": target, "next_person": target}
    return mutate(roster_id, expected_version, request_id, actor, "CURRENT_CHANGED", operation)


def edit_roster(roster_id, expected_version, request_id, actor, *, name, description, participant_ids):
    _active_actor(actor)
    def operation(roster):
        if roster.is_archived:
            raise InvalidAction("Archived rosters cannot be edited.")
        old_order = list(roster.participants.select_related("member").order_by("position", "id"))
        old_ids = [p.pk for p in old_order if p.is_enabled and p.member.is_active]
        old_current = roster.current_participant
        ids = list(dict.fromkeys(int(x) for x in participant_ids))
        members = {m.pk: m for m in Member.objects.filter(pk__in=ids, is_active=True)}
        if len(members) != len(ids):
            raise InvalidAction("All participants must be active household members.")
        roster.name = name.strip()
        roster.description = description.strip()
        existing = {p.member_id: p for p in old_order}
        links = []
        for pos, member_id in enumerate(ids):
            link = existing.get(member_id)
            if link:
                link.is_enabled = True
                link.position = pos
                link.save(update_fields=("is_enabled", "position"))
            else:
                link = RosterParticipant.objects.create(roster=roster, member=members[member_id], position=pos)
            links.append(link)
        for link in old_order:
            if link.member_id not in ids and link.is_enabled:
                link.is_enabled = False
                link.save(update_fields=("is_enabled",))
        new_current = next((p for p in links if old_current and p.pk == old_current.pk), None)
        if not new_current and links:
            if old_current and old_current.pk in old_ids:
                start = old_ids.index(old_current.pk)
                for offset in range(1, len(old_ids) + 1):
                    candidate_id = old_ids[(start + offset) % len(old_ids)]
                    new_current = next((p for p in links if p.pk == candidate_id), None)
                    if new_current:
                        break
            if not new_current:
                new_current = links[0]
        roster.current_participant = new_current
        return {"assigned": new_current.member if new_current else None, "next_person": new_current.member if new_current else None}
    return mutate(roster_id, expected_version, request_id, actor, "PARTICIPANTS_CHANGED", operation)


def create_roster(request_id, actor, name, description, member_ids, starter_id=None):
    _active_actor(actor)
    existing = AuditEvent.objects.filter(request_id=request_id).first()
    if existing:
        if existing.event_type != "CREATE":
            raise InvalidAction("That request identifier was already used.")
        return existing.roster
    try:
        with transaction.atomic():
            roster = Roster.objects.create(name=name.strip(), description=description.strip())
            ids = list(dict.fromkeys(int(i) for i in member_ids))
            members = {m.pk: m for m in Member.objects.filter(pk__in=ids, is_active=True)}
            if len(members) != len(ids):
                raise InvalidAction("All participants must be active household members.")
            links = [RosterParticipant.objects.create(roster=roster, member=members[mid], position=i) for i, mid in enumerate(ids)]
            chosen = next((p for p in links if p.member_id == starter_id), links[0] if links else None)
            if starter_id and not chosen:
                raise InvalidAction("Starting person must be in this roster.")
            roster.current_participant = chosen
            roster.version = 1
            roster.save()
            _event(roster, "CREATE", actor, {"name": "", "participants": [], "current_participant_id": None}, 0, request_id,
                   assigned=chosen.member if chosen else None, next_person=chosen.member if chosen else None)
        return roster
    except IntegrityError:
        existing = AuditEvent.objects.filter(request_id=request_id, event_type="CREATE").first()
        if existing:
            return existing.roster
        raise


def archive_roster(roster_id, expected_version, request_id, actor, archived=True):
    _active_actor(actor)
    event_type = "ARCHIVE" if archived else "RESTORE"
    def operation(roster):
        roster.is_archived = archived
        links = eligible(roster)
        if roster.current_participant not in links:
            roster.current_participant = links[0] if links else None
        current = roster.current_participant
        return {"assigned": current.member if current else None, "next_person": current.member if current else None}
    return mutate(roster_id, expected_version, request_id, actor, event_type, operation)


def undo_latest(roster_id, expected_version, request_id, actor):
    _active_actor(actor)
    latest = AuditEvent.objects.filter(roster_id=roster_id).order_by("-occurred_at", "-id").first()
    if not latest or latest.event_type not in ("COMPLETE", "SUBSTITUTE_COMPLETE", "SKIP"):
        raise InvalidAction("Only the latest completion or skip can be undone.")
    if latest.corrections.exists():
        raise InvalidAction("That action has already been undone.")
    target_id = latest.before_state.get("current_participant_id")
    def operation(roster):
        if roster.is_archived:
            raise InvalidAction("Archived rosters cannot be changed.")
        if AuditEvent.objects.filter(roster=roster).order_by("-occurred_at", "-id").first().pk != latest.pk:
            raise InvalidAction("A newer roster action prevents undo.")
        target = next((p for p in eligible(roster) if p.pk == target_id), None)
        if not target:
            raise InvalidAction("The previous person is no longer eligible, so this action cannot be undone.")
        roster.current_participant = target
        return {"assigned": latest.assigned_member, "next_person": target.member, "reverses": latest}
    return mutate(roster_id, expected_version, request_id, actor, "UNDO", operation)


def member_change(member_id, expected_version, request_id, actor, action, *, name=None):
    _active_actor(actor)
    existing = MemberAuditEvent.objects.filter(request_id=request_id).first()
    if existing:
        expected_type = {"rename": "MEMBER_RENAMED", "deactivate": "MEMBER_DEACTIVATED", "reactivate": "MEMBER_REACTIVATED"}.get(action)
        if existing.member_id != member_id or existing.event_type != expected_type:
            raise InvalidAction("That request identifier was already used.")
        return existing
    try:
        with transaction.atomic():
            changed = Member.objects.filter(pk=member_id, version=expected_version).update(version=F("version") + 1)
            if changed != 1:
                raise Conflict("This member changed. Refresh and try again.")
            member = Member.objects.get(pk=member_id)
            before_member = {"name": member.name, "is_active": member.is_active}
            affected = list(RosterParticipant.objects.filter(member=member).select_related("roster").order_by("roster_id"))
            roster_before = {link.roster_id: (state(link.roster), link.roster.version) for link in affected}
            if action == "rename":
                clean = " ".join((name or "").split())
                if not clean:
                    raise InvalidAction("Enter a name.")
                member.name = clean
                member.normalized_name = normalize_name(clean)
                event_type = "MEMBER_RENAMED"
            elif action in ("deactivate", "reactivate"):
                member.is_active = action == "reactivate"
                event_type = "MEMBER_REACTIVATED" if member.is_active else "MEMBER_DEACTIVATED"
            else:
                raise InvalidAction("Unknown member action.")
            member.save()
            after_member = {"name": member.name, "is_active": member.is_active}
            member_event = MemberAuditEvent.objects.create(
                event_type=event_type, member=member, member_name_snapshot=member.name,
                actor_name_snapshot=actor.name, request_id=request_id,
                before_state=before_member, after_state=after_member,
            )
            for link in affected:
                roster = Roster.objects.get(pk=link.roster_id)
                old_state, old_version = roster_before[link.roster_id]
                roster.version += 1
                if action == "deactivate" and roster.current_participant_id == link.pk:
                    old_order = [p for p in roster.participants.select_related("member").order_by("position", "id") if p.is_enabled and p.member.is_active]
                    previous_ids = [p["id"] for p in old_state["participants"] if p["is_enabled"]]
                    start = previous_ids.index(link.pk) if link.pk in previous_ids else -1
                    candidate = None
                    for offset in range(1, len(previous_ids) + 1):
                        wanted = previous_ids[(start + offset) % len(previous_ids)]
                        candidate = next((p for p in old_order if p.pk == wanted), None)
                        if candidate:
                            break
                    roster.current_participant = candidate
                elif action == "reactivate" and roster.current_participant_id is None:
                    roster.current_participant = next(iter(eligible(roster)), None)
                roster.save()
                current = roster.current_participant
                _event(roster, event_type, actor, old_state, old_version, uuid.uuid4(),
                       assigned=link.member, next_person=current.member if current else None,
                       note="Household member updated")
            return member_event
    except Conflict:
        existing = MemberAuditEvent.objects.filter(request_id=request_id).first()
        expected_type = {"rename": "MEMBER_RENAMED", "deactivate": "MEMBER_DEACTIVATED", "reactivate": "MEMBER_REACTIVATED"}.get(action)
        if existing and existing.member_id == member_id and existing.event_type == expected_type:
            return existing
        raise
    except OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            raise Conflict("The database is busy. Retry this action shortly.") from exc
        raise
