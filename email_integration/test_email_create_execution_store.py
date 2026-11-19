
"""Offline regression tests for the email CREATE execution ledger.

Each test uses a temporary SQLite database.
No Outlook messages are sent, no Foundry agents are invoked,
and no actual IT requests are created.
"""

import sqlite3
import tempfile
import time
import unittest

from pathlib import Path

# Reuse the existing confirmation and execution storage modules.
from email_approval_store import EmailApprovalStore
from email_create_execution_store import EmailCreateExecutionStore
# Ensure SQLite connections are explicitly closed after test operations.
from contextlib import closing


class CreateExecutionStoreTests(unittest.TestCase):
    """Verify that CREATE execution safeguards prevent unsafe retries."""

    def setUp(self):
        """Create an isolated temporary database for each test."""

        # Each test receives its own temporary directory.
        # This prevents changes to the real email_threads.db.
        self.folder = tempfile.TemporaryDirectory()

        self.path = Path(self.folder.name) / "email_threads.db"

        # Initialize confirmation storage and the execution ledger.
        # Both use the same temporary database for this test.
        self.approvals = EmailApprovalStore(self.path)
        self.executions = EmailCreateExecutionStore(self.path)

        # Define a fictional request with all mandatory fields.
        self.draft = {
            "requester_name": "Demo Self-Service User",
            "requester_email": "demo@outlook.com",
            "title": "Ergonomic keyboard for workstation",
            "description": "Request ergonomic keyboard",
            "request_type": "IT Equipment",
            "priority": "Medium",
        }

    def tearDown(self):
        """Delete the temporary database after each test."""

        self.folder.cleanup()

    def confirmed_proposal(self, draft=None):
        """Simulate a valid confirmed request without sending emails."""

        # Save a proposal using a fictional email conversation.
        proposal_id = self.approvals.prepare(
            "demo@outlook.com",
            "thread-01",
            "demo@outlook.com",
            "source-01",
            draft if draft is not None else self.draft,
        )

        # Simulate Microsoft Graph accepting the confirmation email.
        # This does not make any real Graph API call.
        self.approvals.mark_presented(
            proposal_id,
            202,
        )

        # Simulate a newer message confirming the frozen draft.
        # The confirmation does not authorize database creation.
        self.approvals.record_reply(
            proposal_id,
            "demo@outlook.com",
            "thread-01",
            "demo@outlook.com",
            "reply-01",
            "CONFIRM",
            time.time() + 1,
        )

        return proposal_id

    def test_unpresented_proposal_is_blocked(self):
        """An unsent proposal must not reserve a CREATE attempt."""

        proposal_id = self.approvals.prepare(
            "demo@outlook.com",
            "thread-01",
            "demo@outlook.com",
            "source-01",
            self.draft,
        )

        # PREPARED is not enough to permit execution.
        with self.assertRaises(RuntimeError):
            self.executions.claim_for_create(proposal_id)

        # No execution entry should have been created.
        self.assertIsNone(
            self.executions.get(proposal_id)
        )

    def test_presented_without_confirmation_is_blocked(self):
        """Sending a proposal does not count as user confirmation."""

        proposal_id = self.approvals.prepare(
            "demo@outlook.com",
            "thread-01",
            "demo@outlook.com",
            "source-01",
            self.draft,
        )

        # Simulate Graph accepting the outgoing confirmation.
        self.approvals.mark_presented(proposal_id, 202)

        # The recipient has not confirmed the draft.
        # CREATE must remain blocked.
        with self.assertRaises(RuntimeError):
            self.executions.claim_for_create(proposal_id)

    def test_on_behalf_of_request_is_blocked(self):
        """Requests for another identity must not pass demo execution."""

        # Change only the requester address.
        # The sender remains demo@outlook.com.
        other_draft = dict(
            self.draft,
            requester_email="other@example.com",
        )

        proposal_id = self.confirmed_proposal(other_draft)

        # Confirming a request for another person does not
        # establish authority to submit it on their behalf.
        with self.assertRaises(RuntimeError):
            self.executions.claim_for_create(proposal_id)

    def test_one_claim_only_even_after_restart(self):
        """Restarting Python must not permit a duplicate CREATE attempt."""

        proposal_id = self.confirmed_proposal()

        # Reserve the one permitted execution attempt.
        attempt_id = self.executions.claim_for_create(
            proposal_id
        )

        self.assertTrue(attempt_id)

        # Create a new store instance to simulate restarting Python.
        restarted = EmailCreateExecutionStore(self.path)

        # The existing durable claim must block a second attempt.
        with self.assertRaises(RuntimeError):
            restarted.claim_for_create(proposal_id)

        self.assertEqual(
            restarted.get(proposal_id)["status"],
            "CLAIMED",
        )

    def test_success_records_request_id_and_blocks_retry(self):
        """A successful attempt must record its result only once."""

        proposal_id = self.confirmed_proposal()

        attempt_id = self.executions.claim_for_create(
            proposal_id
        )

        # Record a simulated request ID.
        # Nothing is inserted into the actual requests.db.
        self.executions.mark_created(
            proposal_id,
            attempt_id,
            "REQ-EXAMPLE-01",
        )

        record = self.executions.get(proposal_id)

        # Verify that success and the returned ID were saved.
        self.assertEqual(record["status"], "CREATED")
        self.assertEqual(
            record["created_request_id"],
            "REQ-EXAMPLE-01",
        )

        # The same proposal must not create another request.
        with self.assertRaises(RuntimeError):
            self.executions.claim_for_create(proposal_id)

        # An already completed attempt cannot be finalized again.
        with self.assertRaises(RuntimeError):
            self.executions.mark_created(
                proposal_id,
                attempt_id,
                "REQ-EXAMPLE-02",
            )

    def test_uncertain_result_fails_closed(self):
        """An uncertain CREATE outcome must not trigger an automatic retry."""

        proposal_id = self.confirmed_proposal()

        attempt_id = self.executions.claim_for_create(
            proposal_id
        )

        # Simulate an operation whose final result is unknown.
        self.executions.mark_needs_review(
            proposal_id,
            attempt_id,
            "Operation response uncertain",
        )

        record = self.executions.get(proposal_id)

        self.assertEqual(
            record["status"],
            "NEEDS_REVIEW",
        )

        # Another attempt must not start automatically.
        with self.assertRaises(RuntimeError):
            self.executions.claim_for_create(proposal_id)

        # The ordinary finalization path must not silently
        # change an uncertain outcome into success.
        with self.assertRaises(RuntimeError):
            self.executions.mark_created(
                proposal_id,
                attempt_id,
                "REQ-LATE",
            )

    
    def test_expired_confirmation_fails_closed(self):
        """An expired confirmation must not reserve CREATE execution."""

        # Create a simulated confirmed proposal in the temporary
        # test database. No real email or IT request is involved.
        proposal_id = self.confirmed_proposal()

        # Open the temporary SQLite database using closing().
        # Unlike SQLite's transaction context manager alone,
        # closing() explicitly releases the database connection.
        # This prevents Windows from locking the file during cleanup.
        with closing(sqlite3.connect(self.path)) as conn:

            # Commit the simulated expiry change before
            # the database connection is closed.
            with conn:

                # Set the proposal's expiry to one second
                # in the past to simulate an expired confirmation.
                conn.execute(
                    """
                    UPDATE email_create_confirmations
                    SET expires_at = ?
                    WHERE proposal_id = ?
                    """,
                    (
                        time.time() - 1,
                        proposal_id,
                    ),
                )

        # The database connection is now fully closed.

        # Verify that the execution ledger refuses to reserve
        # a CREATE attempt for the expired confirmation.
        with self.assertRaises(RuntimeError):
            self.executions.claim_for_create(
                proposal_id
            )

        # Confirm that no CREATE execution claim was recorded.
        self.assertIsNone(
            self.executions.get(proposal_id)
        )


    def test_wrong_attempt_cannot_finalize(self):
        """Only the recorded execution attempt can be finalized."""

        proposal_id = self.confirmed_proposal()

        # Reserve the legitimate execution attempt.
        self.executions.claim_for_create(proposal_id)

        # A different attempt identifier must not record success.
        with self.assertRaises(RuntimeError):
            self.executions.mark_created(
                proposal_id,
                "wrong-attempt",
                "REQ-EXAMPLE",
            )

        # The original attempt must remain reserved.
        self.assertEqual(
            self.executions.get(proposal_id)["status"],
            "CLAIMED",
        )


# Execute the tests when this file is run directly.
if __name__ == "__main__":
    unittest.main(verbosity=2)
