
"""Persistent conversation state for Outlook request management.

Purpose:
- Store request drafts across separate email messages.
- Keep conversations from different senders isolated.
- Prevent the same incoming message from being processed twice.
- Preserve pending request details after Python restarts.

This module does not send emails, invoke agents, or modify requests.db.
"""

import json
import sqlite3

from contextlib import contextmanager
from pathlib import Path


# Email conversation state is kept in its own SQLite database.
# The existing IT request database remains unchanged.
DEFAULT_DATABASE = Path(__file__).with_name("email_threads.db")


class EmailThreadStore:
    """Manage persistent Outlook conversation state."""

    def __init__(self, path=DEFAULT_DATABASE):
        """Initialize the storage database and required tables."""

        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        with self._connection() as conn:

            # Each sender has an independent state within a conversation.
            # This prevents details from one sender being attached
            # automatically to another sender's request.
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    mailbox TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    sender_email TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,

                    PRIMARY KEY (
                        mailbox,
                        conversation_id,
                        sender_email
                    )
                );

                CREATE TABLE IF NOT EXISTS received_messages (
                    mailbox TEXT NOT NULL,
                    message_key TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    sender_email TEXT NOT NULL,

                    status TEXT NOT NULL
                        CHECK (status IN ('CLAIMED', 'PROCESSED')),

                    claimed_at TEXT NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,

                    processed_at TEXT,

                    PRIMARY KEY (mailbox, message_key)
                );
                """
            )

    @contextmanager
    def _connection(self):
        """Commit successful transactions and roll back failures."""

        conn = sqlite3.connect(self.path, timeout=10)

        try:
            yield conn
            conn.commit()

        except Exception:
            conn.rollback()
            raise

        finally:
            conn.close()

    @staticmethod
    def _identifiers(mailbox, conversation_id, sender_email):
        """Validate conversation identifiers before database access."""

        values = (mailbox, conversation_id, sender_email)

        if not all(
            isinstance(value, str) and value.strip()
            for value in values
        ):
            raise ValueError(
                "Mailbox, conversation ID, and sender are required."
            )

        # Email addresses are normalized for consistent matching.
        # Graph conversation IDs are preserved exactly.
        return (
            mailbox.strip().casefold(),
            conversation_id.strip(),
            sender_email.strip().casefold(),
        )

    def claim_message(
        self,
        mailbox,
        conversation_id,
        sender_email,
        message_key,
    ):
        """Reserve an incoming message for processing.

        Returns False if this message has already been claimed
        or processed.

        An uncertain processing attempt is not retried
        automatically, preventing unintended repeated actions.
        """

        mailbox, conversation_id, sender_email = (
            self._identifiers(
                mailbox,
                conversation_id,
                sender_email,
            )
        )

        if (
            not isinstance(message_key, str)
            or not message_key.strip()
        ):
            raise ValueError(
                "A stable incoming message identifier is required."
            )

        with self._connection() as conn:

            # Reserve the write transaction before checking.
            # This reduces the risk of two local workers
            # claiming the same message simultaneously.
            conn.execute("BEGIN IMMEDIATE")

            existing = conn.execute(
                """
                SELECT 1
                FROM received_messages
                WHERE mailbox = ?
                  AND message_key = ?
                """,
                (mailbox, message_key),
            ).fetchone()

            if existing:
                return False

            # CLAIMED means this message must not be processed
            # a second time without explicit recovery.
            conn.execute(
                """
                INSERT INTO received_messages
                (
                    mailbox,
                    message_key,
                    conversation_id,
                    sender_email,
                    status
                )
                VALUES (?, ?, ?, ?, 'CLAIMED')
                """,
                (
                    mailbox,
                    message_key,
                    conversation_id,
                    sender_email,
                ),
            )

            return True

    def load_state(
        self,
        mailbox,
        conversation_id,
        sender_email,
    ):
        """Retrieve the previously saved conversation state."""

        identifiers = self._identifiers(
            mailbox,
            conversation_id,
            sender_email,
        )

        with self._connection() as conn:

            result = conn.execute(
                """
                SELECT state_json
                FROM conversations
                WHERE mailbox = ?
                  AND conversation_id = ?
                  AND sender_email = ?
                """,
                identifiers,
            ).fetchone()

        # None indicates a new conversation.
        # The orchestrator will initialize new_state().
        if result is None:
            return None

        state = json.loads(result[0])

        if not isinstance(state, dict):
            raise ValueError(
                "Saved conversation state has an invalid format."
            )

        return state

    def complete_message(
        self,
        mailbox,
        conversation_id,
        sender_email,
        message_key,
        state,
    ):
        """Save updated conversation state and mark processing complete.

        Both changes are committed in one SQLite transaction.

        This operation does not send an email or execute
        an IT request database function.
        """

        mailbox, conversation_id, sender_email = (
            self._identifiers(
                mailbox,
                conversation_id,
                sender_email,
            )
        )

        if not isinstance(state, dict):
            raise ValueError(
                "Conversation state must be a dictionary."
            )

        # Serialize before starting the transaction so invalid
        # state cannot cause a partial database update.
        serialized = json.dumps(
            state,
            ensure_ascii=False,
        )

        with self._connection() as conn:

            conn.execute("BEGIN IMMEDIATE")

            # Only the message previously claimed for this
            # exact sender and thread can be completed.
            record = conn.execute(
                """
                SELECT conversation_id, sender_email, status
                FROM received_messages
                WHERE mailbox = ?
                  AND message_key = ?
                """,
                (mailbox, message_key),
            ).fetchone()

            if record != (
                conversation_id,
                sender_email,
                "CLAIMED",
            ):
                raise RuntimeError(
                    "Message is not claimed for this sender/thread."
                )

            # Insert the new conversation or replace its saved state.
            conn.execute(
                """
                INSERT INTO conversations
                (
                    mailbox,
                    conversation_id,
                    sender_email,
                    state_json
                )
                VALUES (?, ?, ?, ?)

                ON CONFLICT (
                    mailbox,
                    conversation_id,
                    sender_email
                )

                DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    mailbox,
                    conversation_id,
                    sender_email,
                    serialized,
                ),
            )

            # Mark processing complete only after the state
            # has been successfully written.
            conn.execute(
                """
                UPDATE received_messages
                SET status = 'PROCESSED',
                    processed_at = CURRENT_TIMESTAMP
                WHERE mailbox = ?
                  AND message_key = ?
                """,
                (mailbox, message_key),
            )

    def message_status(self, mailbox, message_key):
        """Return CLAIMED, PROCESSED, or None for diagnostics."""

        if (
            not isinstance(mailbox, str)
            or not isinstance(message_key, str)
        ):
            raise ValueError(
                "Mailbox and message key must be strings."
            )

        with self._connection() as conn:

            result = conn.execute(
                """
                SELECT status
                FROM received_messages
                WHERE mailbox = ?
                  AND message_key = ?
                """,
                (
                    mailbox.strip().casefold(),
                    message_key,
                ),
            ).fetchone()

        return result[0] if result else None
    