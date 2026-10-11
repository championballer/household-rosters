import uuid
from unittest.mock import patch

from django.http import HttpResponse
from django.test import Client, TestCase
from django.test.client import RequestFactory
from django.urls import reverse

from config.rate_limit import PostRateLimitMiddleware
from rosters.models import AuditEvent, Member, Roster
from rosters.services import (Conflict, create_roster, edit_roster, member_change,
                              perform_turn, undo_latest)


class RosterFlowTests(TestCase):
    def setUp(self):
        self.shiv = Member.objects.create(name="Shiv")
        self.alex = Member.objects.create(name="Alex")
        self.sam = Member.objects.create(name="Sam")
        self.roster = create_roster(uuid.uuid4(), self.shiv, "Clear the bin", "", [self.shiv.pk, self.alex.pk, self.sam.pk], self.shiv.pk)

    def current_name(self):
        self.roster.refresh_from_db()
        return self.roster.current_participant.member.name

    def test_complete_substitute_undo_and_history(self):
        first_id = uuid.uuid4()
        first = perform_turn(self.roster.pk, self.roster.version, first_id, self.shiv, "complete")
        self.assertEqual(self.current_name(), "Alex")
        replay = perform_turn(self.roster.pk, first.event.version_before, first_id, self.shiv, "complete")
        self.assertTrue(replay.replayed)
        self.assertEqual(self.current_name(), "Alex")

        substitute = perform_turn(self.roster.pk, self.roster.version, uuid.uuid4(), self.shiv, "substitute", self.sam)
        self.assertEqual(self.current_name(), "Sam")
        self.assertEqual(substitute.event.assigned_member_name_snapshot, "Alex")
        self.assertEqual(substitute.event.completed_by_name_snapshot, "Sam")
        correction = undo_latest(self.roster.pk, self.roster.version, uuid.uuid4(), self.shiv)
        self.assertEqual(self.current_name(), "Alex")
        self.assertEqual(correction.event.reverses_event_id, substitute.event.pk)
        self.assertEqual(AuditEvent.objects.filter(roster=self.roster).count(), 4)

    def test_stale_version_does_not_advance(self):
        old_version = self.roster.version
        perform_turn(self.roster.pk, old_version, uuid.uuid4(), self.shiv, "complete")
        with self.assertRaises(Conflict):
            perform_turn(self.roster.pk, old_version, uuid.uuid4(), self.alex, "complete")
        self.assertEqual(self.current_name(), "Alex")

    def test_removing_current_selects_successor_in_old_order(self):
        perform_turn(self.roster.pk, self.roster.version, uuid.uuid4(), self.shiv, "complete")
        self.assertEqual(self.current_name(), "Alex")
        edit_roster(self.roster.pk, self.roster.version, uuid.uuid4(), self.shiv,
                    name=self.roster.name, description="", participant_ids=[self.shiv.pk, self.sam.pk])
        self.assertEqual(self.current_name(), "Sam")

    def test_deactivating_current_selects_next_and_preserves_history_name(self):
        perform_turn(self.roster.pk, self.roster.version, uuid.uuid4(), self.shiv, "complete")
        member_change(self.alex.pk, self.alex.version, uuid.uuid4(), self.shiv, "deactivate")
        self.assertEqual(self.current_name(), "Sam")
        event = AuditEvent.objects.filter(roster=self.roster, event_type="COMPLETE").first()
        self.assertEqual(event.next_member_name_snapshot, "Alex")

    def test_pages_and_csv_render(self):
        client = Client()
        self.assertEqual(client.get("/admin/").status_code, 404)
        for url in (reverse("dashboard"), reverse("roster_detail", args=[self.roster.pk]),
                    reverse("roster_history", args=[self.roster.pk])):
            response = client.get(url)
            self.assertEqual(response.status_code, 200)
        response = client.get(reverse("roster_history_csv", args=[self.roster.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Clear the bin", client.get(reverse("roster_detail", args=[self.roster.pk])).content)


class FirstRunTests(TestCase):
    def test_existing_people_are_available_when_creating_a_roster(self):
        first = Member.objects.create(name="First")
        second = Member.objects.create(name="Second")
        session = self.client.session
        session["household_member_id"] = first.pk
        session.save()

        page = self.client.get(reverse("roster_new"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, f'name="participants" value="{first.pk}"')
        self.assertContains(page, f'name="participants" value="{second.pk}"')

        created = self.client.post(reverse("roster_new"), {
            "name": "Cooking", "description": "",
            "participants": [first.pk, second.pk],
            "participant_order": f"{second.pk},{first.pk}",
            "starter": second.pk, "request_id": str(uuid.uuid4()),
        })
        self.assertEqual(created.status_code, 302)
        roster = Roster.objects.get(name="Cooking")
        self.assertEqual(
            list(roster.participants.values_list("member_id", flat=True)),
            [second.pk, first.pk],
        )
        self.assertEqual(roster.current_participant.member_id, second.pk)

    def test_first_member_can_be_added_and_selected(self):
        client = Client()
        response = client.get(reverse("identity"))
        self.assertEqual(response.status_code, 200)
        added = client.post(reverse("members"), {"name": "First flatmate", "request_id": str(uuid.uuid4())})
        self.assertEqual(added.status_code, 302)
        member = Member.objects.get(name="First flatmate")
        chosen = client.post(reverse("identity"), {"member": member.pk})
        self.assertEqual(chosen.status_code, 302)
        self.assertEqual(client.get(reverse("roster_new")).status_code, 200)
        created = client.post(reverse("roster_new"), {
            "name": "Dishwasher", "description": "", "participants": [member.pk],
            "participant_order": str(member.pk), "starter": member.pk,
            "request_id": str(uuid.uuid4()),
        })
        self.assertEqual(created.status_code, 302)
        roster = Roster.objects.get(name="Dishwasher")
        self.assertEqual(client.get(reverse("roster_detail", args=[roster.pk])).status_code, 200)
        self.assertEqual(client.get(reverse("roster_complete", args=[roster.pk])).status_code, 200)
        completed = client.post(reverse("roster_complete", args=[roster.pk]), {
            "version": roster.version, "request_id": str(uuid.uuid4()),
        })
        self.assertEqual(completed.status_code, 302)
        roster.refresh_from_db()
        self.assertEqual(roster.current_participant.member_id, member.pk)
        self.assertEqual(roster.events.filter(event_type="COMPLETE").count(), 1)


class SecurityTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(name="Shiv")
        self.roster = create_roster(uuid.uuid4(), self.member, "Bin", "", [self.member.pk], self.member.pk)

    def test_untrusted_host_is_rejected_on_read_only_pages(self):
        response = Client().get(reverse("dashboard"), HTTP_HOST="untrusted.example")
        self.assertEqual(response.status_code, 400)

    def test_csrf_and_get_requests_cannot_advance_turn(self):
        client = Client(enforce_csrf_checks=True)
        session = client.session
        session["household_member_id"] = self.member.pk
        session.save()
        url = reverse("roster_complete", args=[self.roster.pk])
        self.assertEqual(client.get(url).status_code, 200)
        self.assertEqual(self.roster.events.filter(event_type="COMPLETE").count(), 0)
        response = client.post(url, {"version": self.roster.version, "request_id": str(uuid.uuid4())})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.roster.events.filter(event_type="COMPLETE").count(), 0)

    def test_user_text_is_escaped_and_content_policy_is_set(self):
        self.roster.name = '<img src=x onerror="alert(1)">'
        self.roster.save(update_fields=("name",))
        response = self.client.get(reverse("roster_detail", args=[self.roster.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"<img src=x onerror", response.content)
        self.assertIn(b"&lt;img", response.content)
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])
        self.assertEqual(response["X-Frame-Options"], "DENY")

    def test_sql_metacharacters_in_member_name_are_data(self):
        name = "X'); DROP TABLE rosters_member;--"
        session = self.client.session
        session["household_member_id"] = self.member.pk
        session.save()
        response = self.client.post(reverse("members"), {"name": name, "request_id": str(uuid.uuid4())})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Member.objects.filter(name=name).exists())
        self.assertEqual(Member.objects.count(), 2)

    def test_large_post_is_rejected(self):
        response = self.client.post(reverse("identity"), {"member": self.member.pk, "padding": "x" * 131072})
        self.assertEqual(response.status_code, 400)

    def test_oversized_history_page_and_formula_csv_are_safe(self):
        history_url = reverse("roster_history", args=[self.roster.pk])
        self.assertEqual(self.client.get(history_url, {"page": "9" * 5000}).status_code, 200)
        event = self.roster.events.first()
        event.actor_name_snapshot = "  =1+1"
        event.save(update_fields=("actor_name_snapshot",))
        csv_response = self.client.get(reverse("roster_history_csv", args=[self.roster.pk]))
        self.assertIn(b"'  =1+1", csv_response.content)

    def test_write_rate_limit_uses_peer_address_and_leaves_reads_available(self):
        url = reverse("identity")
        for attempt in range(30):
            response = self.client.post(url, {}, REMOTE_ADDR="10.0.1.22",
                                        HTTP_X_FORWARDED_FOR=f"192.0.2.{attempt + 1}")
            self.assertEqual(response.status_code, 200)
        limited = self.client.post(url, {}, REMOTE_ADDR="10.0.1.22",
                                   HTTP_X_FORWARDED_FOR="198.51.100.1")
        self.assertEqual(limited.status_code, 429)
        self.assertGreater(int(limited["Retry-After"]), 0)
        self.assertIn("script-src 'self'", limited["Content-Security-Policy"])
        self.assertEqual(limited["X-Frame-Options"], "DENY")
        self.assertEqual(self.client.get(url, REMOTE_ADDR="10.0.1.22").status_code, 200)
        self.assertEqual(self.client.post(url, {}, REMOTE_ADDR="10.0.1.23").status_code, 200)

    def test_write_rate_limit_expires_after_rolling_window(self):
        limiter = PostRateLimitMiddleware(lambda request: HttpResponse("ok"))
        request = RequestFactory().post("/identity/", REMOTE_ADDR="10.0.1.22")
        with patch("config.rate_limit.time.monotonic", return_value=100):
            for _ in range(limiter.limit):
                self.assertEqual(limiter(request).status_code, 200)
            self.assertEqual(limiter(request).status_code, 429)
        with patch("config.rate_limit.time.monotonic", return_value=160):
            self.assertEqual(limiter(request).status_code, 200)
