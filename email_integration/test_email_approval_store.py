
"""Offline tests for email confirmation persistence and safety.

Each test uses a temporary SQLite database.
No emails are sent and no request operations are executed.
"""

import tempfile
import time
import unittest

from pathlib import Path
from email_approval_store import EmailApprovalStore


class ApprovalTests(unittest.TestCase):

    def setUp(self):
        """Create an isolated database and fictional test request."""

        self.temp = tempfile.TemporaryDirectory()

        self.store = EmailApprovalStore(
            Path(self.temp.name) / "email_threads.db"
        )

        self.draft = {
            "title": "Adobe Acrobat access",
            "request_type": "Software Access",
            "priority": "High",
            "requester_name": "Portfolio Demo",
            "requester_email": "portfolio.demo@example.com",
        }

        self.args = (
            "demo@outlook.com",
            "thread-01",
            "demo@outlook.com",
            "original-01",
        )

    def tearDown(self):
        """Remove all temporary test data."""

        self.temp.cleanup()

    def test_prepared_not_approved(self):
        """A prepared proposal cannot accept a confirmation."""

        proposal = self.store.prepare(
            *self.args, self.draft
        )

        self.assertEqual(
            self.store.get(proposal)["status"],
            "PREPARED",
        )

        with self.assertRaises(RuntimeError):
            self.store.record_reply(
                proposal,
                *self.args[:3],
                "reply-01",
                "CONFIRM",
                time.time() + 1,
            )

    def test_confirm_only_after_presented_newer_reply(self):
        """A valid reply records confirmation but not authorization."""

        proposal = self.store.prepare(
            *self.args, self.draft
        )

        # Simulate Graph accepting the outgoing confirmation.
        self.store.mark_presented(proposal, 202)

        status = self.store.record_reply(
            proposal,
            *self.args[:3],
            "reply-01",
            "CONFIRM",
            time.time() + 2,
        )

        self.assertEqual(
            status,
            "CONFIRMED_PENDING_AUTHORIZATION",
        )

    def test_reject_wrong_sender_or_thread(self):
        """Other senders and conversations cannot approve this draft."""

        proposal = self.store.prepare(
            *self.args, self.draft
        )

        self.store.mark_presented(proposal, 202)

        with self.assertRaises(RuntimeError):
            self.store.record_reply(
                proposal,
                self.args[0],
                "another-thread",
                self.args[2],
                "reply-01",
                "CONFIRM",
                time.time() + 2,
            )

        with self.assertRaises(RuntimeError):
            self.store.record_reply(
                proposal,
                self.args[0],
                self.args[1],
                "other@example.com",
                "reply-02",
                "CONFIRM",
                time.time() + 2,
            )

    def test_reject_old_reply_and_source_message(self):
        """An old message cannot become a new confirmation."""

        proposal = self.store.prepare(
            *self.args, self.draft
        )

        self.store.mark_presented(proposal, 202)

        with self.assertRaises(RuntimeError):
            self.store.record_reply(
                proposal,
                *self.args[:3],
                self.args[3],
                "CONFIRM",
                time.time() + 2,
            )

        with self.assertRaises(RuntimeError):
            self.store.record_reply(
                proposal,
                *self.args[:3],
                "old-reply",
                "CONFIRM",
                time.time() - 30,
            )

    def test_repeat_proposal_and_decision_blocked(self):
        """Duplicate proposals and confirmation replies are rejected."""

        proposal = self.store.prepare(
            *self.args, self.draft
        )

        # Repeated preparation returns the same proposal.
        self.assertEqual(
            self.store.prepare(*self.args, self.draft),
            proposal,
        )

        # A second source message cannot silently replace it.
        with self.assertRaises(RuntimeError):
            self.store.prepare(
                *self.args[:3],
                "another-source",
                self.draft,
            )

        self.store.mark_presented(proposal, 202)

        self.store.record_reply(
            proposal,
            *self.args[:3],
            "reply-01",
            "CONFIRM",
            time.time() + 2,
        )

        # Replaying the same confirmation is rejected.
        with self.assertRaises(RuntimeError):
            self.store.record_reply(
                proposal,
                *self.args[:3],
                "reply-01",
                "CONFIRM",
                time.time() + 3,
            )

    def test_decline_and_invalid_decision(self):
        """Ambiguous decisions are rejected; declines remain declines."""

        proposal = self.store.prepare(
            *self.args, self.draft
        )

        self.store.mark_presented(proposal, 202)

        with self.assertRaises(ValueError):
            self.store.record_reply(
                proposal,
                *self.args[:3],
                "reply-01",
                "MAYBE",
                time.time() + 2,
            )

        status = self.store.record_reply(
            proposal,
            *self.args[:3],
            "reply-01",
            "DECLINE",
            time.time() + 2,
        )

        self.assertEqual(status, "DECLINED")

    def test_invalidated_old_proposal_cannot_confirm(self):
        """Changing the request requires a new proposal."""

        proposal = self.store.prepare(
            *self.args, self.draft
        )

        self.store.mark_presented(proposal, 202)
        self.store.invalidate(proposal)

        changed_draft = dict(
            self.draft,
            priority="Medium",
        )

        new_proposal = self.store.prepare(
            *self.args[:3],
            "new-source",
            changed_draft,
        )

        self.assertNotEqual(
            proposal,
            new_proposal,
        )

        with self.assertRaises(RuntimeError):
            self.store.record_reply(
                proposal,
                *self.args[:3],
                "reply-01",
                "CONFIRM",
                time.time() + 2,
            )

    def test_reject_incomplete_draft(self):
        """No confirmation proposal is prepared without required fields."""

        incomplete = dict(self.draft)
        incomplete.pop("priority")

        with self.assertRaises(ValueError):
            self.store.prepare(
                *self.args,
                incomplete,
            )

    
    def test_confirmation_valid_for_72_hours_after_presentation(self):
        """Verify that the full confirmation period begins at presentation."""

        # Prepare a proposal with the default 72-hour validity.
        proposal = self.store.prepare(
            *self.args,
            self.draft,
        )

        # Simulate Microsoft Graph accepting the outgoing email.
        self.store.mark_presented(
            proposal,
            202,
        )

        # Read the persisted proposal after presentation.
        snapshot = self.store.get(proposal)

        self.assertEqual(
            snapshot["status"],
            "PRESENTED",
        )

        # The allowed response window must be 72 hours
        # from the time the email was presented.
        validity_seconds = (
            snapshot["expires_at"] - snapshot["presented_at"]
        )

        self.assertAlmostEqual(
            validity_seconds,
            72 * 60 * 60,
            delta=1,
        )



if __name__ == "__main__":
    unittest.main(verbosity=2)
