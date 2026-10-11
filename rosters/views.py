import csv
from functools import wraps

from django.contrib import messages
from django.db import IntegrityError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from .forms import (ConfirmForm, CurrentForm, IdentityForm, MemberEditForm,
                    MemberForm, RosterForm, SubstituteForm, TurnActionForm)
from .models import Member, Roster
from .services import (Conflict, InvalidAction, archive_roster, change_current,
                      create_member, create_roster, edit_roster, member_change, perform_turn, undo_latest)


def selected_member(request):
    member_id = request.session.get("household_member_id")
    if not member_id:
        return None
    return Member.objects.filter(pk=member_id, is_active=True).first()


def require_identity(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not selected_member(request):
            messages.info(request, "Choose your name before continuing.")
            return redirect("identity")
        return view(request, *args, **kwargs)
    return wrapped


def _error(request, exc):
    messages.error(request, str(exc))


def _form_version(form, roster):
    version = form.cleaned_data.get("version")
    if version is None:
        raise Conflict("This page is out of date. Refresh and try again.")
    return version


@require_GET
def dashboard(request):
    active = Roster.objects.filter(is_archived=False).prefetch_related("participants__member").order_by("name")
    return render(request, "rosters/dashboard.html", {"rosters": active, "identity": selected_member(request)})


@require_GET
def health(request):
    return JsonResponse({"status": "ok"})


@require_GET
def dashboard_api(request):
    result = []
    for roster in Roster.objects.filter(is_archived=False).select_related("current_participant__member").order_by("id"):
        result.append({"id": roster.id, "version": roster.version,
                       "current": roster.current_participant.member.name if roster.current_participant else None})
    return JsonResponse({"rosters": result})


def identity(request):
    if request.method == "POST":
        form = IdentityForm(request.POST)
        if form.is_valid():
            request.session["household_member_id"] = form.cleaned_data["member"].pk
            messages.success(request, f"You are set as {form.cleaned_data['member'].name}.")
            destination = request.GET.get("next", "")
            if destination and url_has_allowed_host_and_scheme(destination, allowed_hosts={request.get_host()}):
                return redirect(destination)
            return redirect("dashboard")
    else:
        form = IdentityForm()
    return render(request, "rosters/identity.html", {"form": form, "has_members": Member.objects.filter(is_active=True).exists()})


@require_POST
def forget_identity(request):
    request.session.pop("household_member_id", None)
    return redirect("identity")


def members(request):
    if not selected_member(request) and Member.objects.filter(is_active=True).exists():
        messages.info(request, "Choose your name before continuing.")
        return redirect("identity")
    form = MemberForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        name = form.cleaned_data["name"]
        try:
            member = create_member(form.cleaned_data["request_id"], selected_member(request), name)
            messages.success(request, f"Added {member.name}.")
            return redirect("members")
        except IntegrityError:
            form.add_error("name", "A household member with this name already exists.")
    return render(request, "rosters/members.html", {"members": Member.objects.order_by("name"), "form": form})


@require_identity
def member_edit(request, member_id):
    member = get_object_or_404(Member, pk=member_id)
    form = MemberEditForm(request.POST or None, initial={"version": member.version})
    if request.method == "POST" and form.is_valid():
        try:
            member_change(member.pk, form.cleaned_data["version"], form.cleaned_data["request_id"],
                          selected_member(request), "rename", name=form.cleaned_data["name"])
            messages.success(request, "Member name updated.")
            return redirect("members")
        except (Conflict, InvalidAction, IntegrityError) as exc:
            _error(request, exc if not isinstance(exc, IntegrityError) else InvalidAction("That name is already in use."))
    return render(request, "rosters/member_edit.html", {"member": member, "form": form})


@require_identity
def member_status(request, member_id, action):
    member = get_object_or_404(Member, pk=member_id)
    if action not in ("deactivate", "reactivate"):
        return redirect("members")
    if request.method == "POST":
        form = ConfirmForm(request.POST)
        if form.is_valid():
            try:
                member_change(member.pk, form.cleaned_data["version"], form.cleaned_data["request_id"],
                              selected_member(request), action)
                messages.success(request, f"{member.name} {action}d." if action == "deactivate" else f"{member.name} reactivated.")
                return redirect("members")
            except (Conflict, InvalidAction) as exc:
                _error(request, exc)
    else:
        form = ConfirmForm(initial={"version": member.version})
    return render(request, "rosters/confirm.html", {"form": form, "title": f"{action.title()} {member.name}?",
                    "description": "This also updates any roster where this person is included.",
                    "back_url": reverse("members")})


@require_identity
def roster_new(request):
    form = RosterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            roster = create_roster(form.cleaned_data["request_id"], selected_member(request),
                form.cleaned_data["name"], form.cleaned_data["description"], form.cleaned_data["ordered_ids"],
                form.cleaned_data["starter"].pk if form.cleaned_data["starter"] else None)
            messages.success(request, "Roster created.")
            return redirect("roster_detail", roster_id=roster.pk)
        except (Conflict, InvalidAction, IntegrityError) as exc:
            _error(request, exc if not isinstance(exc, IntegrityError) else InvalidAction("Could not create this roster."))
    return render(request, "rosters/roster_form.html", {"form": form, "title": "Create a roster"})


@require_identity
def roster_edit(request, roster_id):
    roster = get_object_or_404(Roster, pk=roster_id, is_archived=False)
    form = RosterForm(request.POST or None, roster=roster, initial={"version": roster.version})
    if request.method == "POST" and form.is_valid():
        try:
            result = edit_roster(roster.pk, _form_version(form, roster), form.cleaned_data["request_id"],
                selected_member(request), name=form.cleaned_data["name"], description=form.cleaned_data["description"],
                participant_ids=form.cleaned_data["ordered_ids"])
            messages.success(request, "Roster updated.")
            return redirect("roster_detail", roster_id=roster.pk)
        except (Conflict, InvalidAction, IntegrityError) as exc:
            _error(request, exc if not isinstance(exc, IntegrityError) else InvalidAction("A roster participant could not be saved."))
    return render(request, "rosters/roster_form.html", {"form": form, "title": "Edit roster", "roster": roster})


@require_GET
def roster_detail(request, roster_id):
    roster = get_object_or_404(Roster.objects.prefetch_related("participants__member"), pk=roster_id)
    participants = list(roster.participants.filter(is_enabled=True, member__is_active=True).select_related("member").order_by("position", "id"))
    events = roster.events.all()[:12]
    return render(request, "rosters/detail.html", {"roster": roster, "participants": participants,
        "events": events, "identity": selected_member(request), "can_undo": bool(events and events[0].event_type in ("COMPLETE", "SUBSTITUTE_COMPLETE", "SKIP") and not events[0].corrections.exists())})


@require_GET
def history(request, roster_id):
    roster = get_object_or_404(Roster, pk=roster_id)
    events = roster.events.all()
    raw_page = request.GET.get("page", "1")
    page = max(1, int(raw_page)) if len(raw_page) <= 9 and raw_page.isascii() and raw_page.isdecimal() else 1
    per_page = 30
    count = events.count()
    pages = max(1, (count + per_page - 1) // per_page)
    page = min(page, pages)
    items = events[(page - 1) * per_page:page * per_page]
    return render(request, "rosters/history.html", {"roster": roster, "events": items, "page": page, "pages": pages})


def _csv_safe(value):
    value = "" if value is None else str(value)
    if value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


@require_GET
def history_csv(request, roster_id):
    roster = get_object_or_404(Roster, pk=roster_id)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="roster-{roster.pk}-history.csv"'
    writer = csv.writer(response)
    writer.writerow(["event_id", "timestamp", "action", "actor", "completed_by", "assigned_to", "next_person", "note", "reverses_event_id"])
    for event in roster.events.order_by("occurred_at", "id"):
        writer.writerow([event.pk, event.occurred_at.isoformat(), event.event_type,
            _csv_safe(event.actor_name_snapshot), _csv_safe(event.completed_by_name_snapshot),
            _csv_safe(event.assigned_member_name_snapshot), _csv_safe(event.next_member_name_snapshot),
            _csv_safe(event.note), event.reverses_event_id or ""])
    return response


@require_GET
def archived(request):
    return render(request, "rosters/archived.html", {"rosters": Roster.objects.filter(is_archived=True).order_by("name"), "identity": selected_member(request)})


@require_identity
def turn_action(request, roster_id, action):
    roster = get_object_or_404(Roster, pk=roster_id)
    from .forms import SkipForm
    form_class = SubstituteForm if action == "substitute" else (SkipForm if action == "skip" else TurnActionForm)
    if request.method == "POST":
        form = form_class(request.POST)
        if form.is_valid():
            try:
                actual = form.cleaned_data.get("completed_by")
                perform_turn(roster.pk, form.cleaned_data["version"], form.cleaned_data["request_id"],
                             selected_member(request), action, actual)
                messages.success(request, "Turn completed." if action != "skip" else "Turn skipped.")
                return redirect("roster_detail", roster_id=roster.pk)
            except (Conflict, InvalidAction) as exc:
                _error(request, exc)
    else:
        form = form_class(initial={"version": roster.version})
    return render(request, "rosters/action.html", {"form": form, "roster": roster, "action": action,
        "title": {"complete": "Mark as done", "substitute": "Record someone else completing it", "skip": "Skip this turn"}[action]})


@require_identity
def undo(request, roster_id):
    roster = get_object_or_404(Roster, pk=roster_id)
    if request.method == "POST":
        form = ConfirmForm(request.POST)
        if form.is_valid():
            try:
                undo_latest(roster.pk, form.cleaned_data["version"], form.cleaned_data["request_id"], selected_member(request))
                messages.success(request, "Latest turn action undone. The history keeps both entries.")
                return redirect("roster_detail", roster_id=roster.pk)
            except (Conflict, InvalidAction) as exc:
                _error(request, exc)
    else:
        form = ConfirmForm(initial={"version": roster.version})
    return render(request, "rosters/confirm.html", {"form": form, "title": "Undo the latest turn?",
        "description": "This restores the previous person and adds a correction to history.",
        "back_url": reverse("roster_detail", args=[roster.pk])})


@require_identity
def change_turn(request, roster_id):
    roster = get_object_or_404(Roster, pk=roster_id)
    if request.method == "POST":
        form = CurrentForm(request.POST)
        if form.is_valid():
            try:
                change_current(roster.pk, form.cleaned_data["version"], form.cleaned_data["request_id"],
                    selected_member(request), form.cleaned_data["participant"])
                messages.success(request, "Current turn updated.")
                return redirect("roster_detail", roster_id=roster.pk)
            except (Conflict, InvalidAction) as exc:
                _error(request, exc)
    else:
        form = CurrentForm(initial={"version": roster.version})
    return render(request, "rosters/current.html", {"form": form, "roster": roster,
        "participants": roster.participants.filter(is_enabled=True, member__is_active=True).select_related("member")})


@require_identity
def roster_status(request, roster_id, action):
    roster = get_object_or_404(Roster, pk=roster_id)
    archived_state = action == "archive"
    if request.method == "POST":
        form = ConfirmForm(request.POST)
        if form.is_valid():
            try:
                archive_roster(roster.pk, form.cleaned_data["version"], form.cleaned_data["request_id"],
                               selected_member(request), archived_state)
                messages.success(request, "Roster archived." if archived_state else "Roster restored.")
                return redirect("roster_detail", roster_id=roster.pk)
            except (Conflict, InvalidAction) as exc:
                _error(request, exc)
    else:
        form = ConfirmForm(initial={"version": roster.version})
    return render(request, "rosters/confirm.html", {"form": form, "title": f"{action.title()} {roster.name}?",
        "description": "This roster's history will be retained.",
        "back_url": reverse("roster_detail", args=[roster.pk])})
