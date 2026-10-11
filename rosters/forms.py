import uuid
from django import forms
from .models import Member


class RequestForm(forms.Form):
    version = forms.IntegerField(min_value=0, required=False, widget=forms.HiddenInput)
    request_id = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput)


class IdentityForm(forms.Form):
    member = forms.ModelChoiceField(queryset=Member.objects.none(), label="I am")
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["member"].queryset = Member.objects.filter(is_active=True).order_by("name")


class MemberForm(RequestForm):
    name = forms.CharField(max_length=80, label="Name")
    def clean_name(self):
        return " ".join(self.cleaned_data["name"].split())


class MemberEditForm(MemberForm):
    pass


class MemberActionForm(RequestForm):
    pass


class RosterForm(RequestForm):
    name = forms.CharField(max_length=120)
    description = forms.CharField(max_length=2000, required=False, widget=forms.Textarea(attrs={"rows": 2}))
    participants = forms.ModelMultipleChoiceField(queryset=Member.objects.none(), required=False)
    participant_order = forms.CharField(required=False, widget=forms.HiddenInput)
    starter = forms.ModelChoiceField(queryset=Member.objects.none(), required=False)

    def __init__(self, *args, **kwargs):
        roster = kwargs.pop("roster", None)
        super().__init__(*args, **kwargs)
        active = Member.objects.filter(is_active=True).order_by("name")
        self.fields["participants"].queryset = active
        self.fields["participants"].widget = forms.CheckboxSelectMultiple()
        self.fields["starter"].queryset = active
        self.fields["starter"].required = False
        if roster:
            self.fields["version"].initial = roster.version
            self.initial.setdefault("name", roster.name)
            self.initial.setdefault("description", roster.description)
            current = roster.current_participant
            saved_order = [p.member_id for p in roster.participants.order_by("position", "id") if p.is_enabled and p.member.is_active]
            self.fields["participants"].initial = saved_order
            members = list(active)
            by_id = {member.pk: member for member in members}
            ordered_members = [by_id.pop(mid) for mid in saved_order if mid in by_id]
            ordered_members.extend(sorted(by_id.values(), key=lambda member: member.name.casefold()))
            self.fields["participants"].choices = [(member.pk, member.name) for member in ordered_members]
            self.fields["starter"].initial = current.member_id if current else None
            self.roster = roster
        else:
            self.roster = None

    def clean(self):
        cleaned = super().clean()
        participants = cleaned.get("participants", [])
        starter = cleaned.get("starter")
        if starter and starter not in participants:
            self.add_error("starter", "Starting person must be included in the roster.")
        raw_order = cleaned.get("participant_order", "")
        if raw_order:
            try:
                ordered = [int(value) for value in raw_order.split(",") if value]
            except ValueError:
                ordered = []
            selected = {member.pk for member in participants}
            if len(ordered) != len(set(ordered)) or set(ordered) != selected:
                self.add_error("participant_order", "Participant order does not match the selected people.")
            else:
                cleaned["ordered_ids"] = ordered
        else:
            cleaned["ordered_ids"] = [member.pk for member in participants]
        return cleaned


class TurnActionForm(RequestForm):
    pass


class SkipForm(RequestForm):
    confirmed = forms.BooleanField(required=True, label="I confirm this turn should be skipped")


class SubstituteForm(RequestForm):
    completed_by = forms.ModelChoiceField(queryset=Member.objects.none(), label="Who completed it?")
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["completed_by"].queryset = Member.objects.filter(is_active=True).order_by("name")


class CurrentForm(RequestForm):
    participant = forms.IntegerField(min_value=1)
    confirmed = forms.BooleanField(required=True, label="I confirm changing whose turn it is")


class ConfirmForm(RequestForm):
    confirmed = forms.BooleanField(required=True, label="I understand this changes the roster")
