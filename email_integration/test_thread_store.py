
"""Offline tests for persistent email conversation state.

These tests use a temporary SQLite database.
No Azure, Microsoft Graph, or IT request operations are executed.
"""

import tempfile
import unittest

from pathlib import Path
from thread_store import EmailThreadStore


class EmailThreadStoreTests(unittest.TestCase):

    def setUp(self):
        """Create a temporary database for each test."""

        self.folder = tempfile.TemporaryDirectory()

        self.path = (
            Path(self.folder.name) / "test_threads.db"
        )

        self.store = EmailThreadStore(self.path)

        # Fictional identifiers for a single email conversation.
        self.mailbox = "demo@outlook.com"
        self.sender = "demo@outlook.com"
        self.conversation = "conversation-001"

    def tearDown(self):
        """Delete temporary test data."""

        self.folder.cleanup()

    def test_new_thread_has_no_previous_state(self):
        """A new conversation must start without another draft."""

        state = self.store.load_state(
            self.mailbox,
            self.conversation,
            self.sender,
        )

        self.assertIsNone(state)

    def test_state_survives_restart_and_followup(self):
        """A second email continues the existing request draft."""

        # First email: request Adobe Acrobat access.
        self.assertTrue(
            self.store.claim_message(
                self.mailbox,
                self.conversation,
                self.sender,
                "message-001",
            )
        )

        draft = {
            "flow": "CREATE",
            "draft": {
                "title": "Adobe Acrobat Pro access",
            },
        }

        self.store.complete_message(
            self.mailbox,
            self.conversation,
            self.sender,
            "message-001",
            draft,
        )

        # Simulate restarting the Python application.
        restarted = EmailThreadStore(self.path)

        restored = restarted.load_state(
            self.mailbox,
            self.conversation,
            self.sender,
        )

        self.assertEqual(
            restored["draft"]["title"],
            "Adobe Acrobat Pro access",
        )

        # Second email: user supplies a priority.
        self.assertTrue(
            restarted.claim_message(
                self.mailbox,
                self.conversation,
                self.sender,
                "message-002",
            )
        )

        restored["draft"]["priority"] = "High"

        restarted.complete_message(
            self.mailbox,
            self.conversation,
            self.sender,
            "message-002",
            restored,
        )

        # Both fields must now be available.
        final = restarted.load_state(
            self.mailbox,
            self.conversation,
            self.sender,
        )

        self.assertEqual(
            final["draft"]["title"],
            "Adobe Acrobat Pro access",
        )

        self.assertEqual(
            final["draft"]["priority"],
            "High",
        )

    def test_same_message_cannot_be_processed_twice(self):
        """Duplicate inbound messages must not start a second action."""

        self.assertTrue(
            self.store.claim_message(
                self.mailbox,
                self.conversation,
                self.sender,
                "message-003",
            )
        )

        # The same message is already reserved.
        self.assertFalse(
            self.store.claim_message(
                self.mailbox,
                self.conversation,
                self.sender,
                "message-003",
            )
        )

        self.store.complete_message(
            self.mailbox,
            self.conversation,
            self.sender,
            "message-003",
            {"draft": {}},
        )

        # Even after completion, processing it again is rejected.
        self.assertFalse(
            self.store.claim_message(
                self.mailbox,
                self.conversation,
                self.sender,
                "message-003",
            )
        )

        self.assertEqual(
            self.store.message_status(
                self.mailbox,
                "message-003",
            ),
            "PROCESSED",
        )

    def test_different_conversations_are_isolated(self):
        """A different email conversation must not inherit this draft."""

        self.store.claim_message(
            self.mailbox,
            self.conversation,
            self.sender,
            "message-004",
        )

        self.store.complete_message(
            self.mailbox,
            self.conversation,
            self.sender,
            "message-004",
            {
                "draft": {
                    "requester_name": "Demo A",
                }
            },
        )

        # Another thread starts without the existing draft.
        self.assertIsNone(
            self.store.load_state(
                self.mailbox,
                "different-conversation",
                self.sender,
            )
        )

        # A different sender cannot load the first sender's state.
        self.assertIsNone(
            self.store.load_state(
                self.mailbox,
                self.conversation,
                "other@example.com",
            )
        )

    def test_cannot_complete_unclaimed_message(self):
        """Unrecognized messages cannot update conversation state."""

        with self.assertRaises(RuntimeError):

            self.store.complete_message(
                self.mailbox,
                self.conversation,
                self.sender,
                "missing-message",
                {},
            )

    def test_failed_processing_keeps_claim(self):
        """An interrupted message requires review before retrying."""

        self.store.claim_message(
            self.mailbox,
            self.conversation,
            self.sender,
            "message-005",
        )

        self.assertEqual(
            self.store.message_status(
                self.mailbox,
                "message-005",
            ),
            "CLAIMED",
        )

        self.assertFalse(
            self.store.claim_message(
                self.mailbox,
                self.conversation,
                self.sender,
                "message-005",
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
