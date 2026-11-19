
"""Store email CREATE confirmations without executing database writes.

A proposal is bound to an exact request draft and Outlook conversation.
This module does not call Foundry agents, send emails, or modify requests.db.
"""

import hashlib
import json
import sqlite3
import time
import uuid

from contextlib import contextmanager
from pathlib import Path

# Reuse the existing email_threads.db location.
from thread_store import DEFAULT_DATABASE


# A creation proposal is not prepared until every required
# request field has been collected by the Communication Agent.
REQUIRED_FIELDS = (
    "requester_name",
    "requester_email",
    "title",
    "request_type",
    "priority",
)


class EmailApprovalStore:
    """Maintain persistent, immutable email confirmation proposals."""

    def __init__(self, path=DEFAULT_DATABASE):
        """Create the approval table without changing existing tables."""

        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        with self._connection() as conn:

            # Store one proposal per approval attempt.
            # The request details are snapshotted as JSON so
            # later draft changes cannot silently alter approval.
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS email_create_confirmations (
                    proposal_id TEXT PRIMARY KEY,
                    mailbox TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    sender_email TEXT NOT NULL,
                    source_message_key TEXT NOT NULL,
                    draft_json TEXT NOT NULL,
                    draft_sha256 TEXT NOT NULL,

                    status TEXT NOT NULL CHECK (
                        status IN (
                            'PREPARED',
                            'PRESENTED',
                            'CONFIRMED_PENDING_AUTHORIZATION',
                            'DECLINED',
                            'INVALIDATED',
                            'EXPIRED'
                        )
                    ),

                    prepared_at REAL NOT NULL,
                    presented_at REAL,
                    expires_at REAL NOT NULL,
                    reply_message_key TEXT
                );

                CREATE UNIQUE INDEX IF NOT EXISTS
                    one_active_email_create_confirmation
                ON email_create_confirmations (
                    mailbox,
                    conversation_id,
                    sender_email
                )
                WHERE status IN (
                    'PREPARED',
                    'PRESENTED',
                    'CONFIRMED_PENDING_AUTHORIZATION'
                );

                CREATE UNIQUE INDEX IF NOT EXISTS
                    one_confirmation_per_reply
                ON email_create_confirmations (
                    mailbox,
                    reply_message_key
                )
                WHERE reply_message_key IS NOT NULL;
                """
            )

    @contextmanager
    def _connection(self):
        """Commit successful changes and roll back failed transactions."""

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
    def _required_text(value, label):
        """Reject empty identifiers before they reach the database."""

        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"{label} must be a non-empty string."
            )

        return value.strip()

    def prepare(
        self,
        mailbox,
        conversation_id,
        sender_email,
        source_message_key,
        draft,
        ttl_hours=72, # Default confirmation validity: 72 hours (3 days).

    ):
        """Prepare a CREATE confirmation without sending or approving it."""

        # Normalize email addresses, but preserve Graph identifiers.
        mailbox = self._required_text(
            mailbox, "mailbox"
        ).casefold()

        conversation_id = self._required_text(
            conversation_id, "conversation_id"
        )

        sender_email = self._required_text(
            sender_email, "sender_email"
        ).casefold()

        source_message_key = self._required_text(
            source_message_key, "source_message_key"
        )

        # Require a complete draft.
        # Missing information must be requested by the agent,
        # not assigned using Python defaults.
        if not isinstance(draft, dict) or any(
            not isinstance(draft.get(field), str)
            or not draft[field].strip()
            for field in REQUIRED_FIELDS
        ):
            raise ValueError(
                "Draft is missing required CREATE fields."
            )

        # Limit the validity period of a confirmation.
        if (
            not isinstance(ttl_hours, (int, float))
            or not 0 < ttl_hours <= 72
        ):
            raise ValueError(
                "ttl_hours must be between 0 and 72."
            )

        # Serialize the exact proposed values.
        # A hash identifies whether a subsequent proposal
        # contains the same request information.
        draft_json = json.dumps(
            draft,
            sort_keys=True,
            ensure_ascii=False,
        )

        digest = hashlib.sha256(
            draft_json.encode("utf-8")
        ).hexdigest()

        now = time.time()

        with self._connection() as conn:

            # Lock the transaction to avoid competing proposals.
            conn.execute("BEGIN IMMEDIATE")

            # Previously expired proposals must not block
            # a new confirmation attempt.
            conn.execute(
                """
                UPDATE email_create_confirmations
                SET status = 'EXPIRED'
                WHERE expires_at <= ?
                  AND status IN (
                      'PREPARED',
                      'PRESENTED',
                      'CONFIRMED_PENDING_AUTHORIZATION'
                  )
                """,
                (now,),
            )

            # Only one active CREATE confirmation is permitted
            # for a sender within a conversation.
            active = conn.execute(
                """
                SELECT
                    proposal_id,
                    source_message_key,
                    draft_sha256
                FROM email_create_confirmations
                WHERE mailbox = ?
                  AND conversation_id = ?
                  AND sender_email = ?
                  AND status IN (
                      'PREPARED',
                      'PRESENTED',
                      'CONFIRMED_PENDING_AUTHORIZATION'
                  )
                """,
                (
                    mailbox,
                    conversation_id,
                    sender_email,
                ),
            ).fetchone()

            if active is not None:

                # Repeated preparation of the exact same proposal
                # returns the existing identifier.
                if (
                    active[1] == source_message_key
                    and active[2] == digest
                ):
                    return active[0]

                # A changed draft requires the previous proposal
                # to be invalidated explicitly.
                raise RuntimeError(
                    "A different active confirmation exists. "
                    "Invalidate it before preparing a revised draft."
                )

            # Generate an unpredictable identifier for this proposal.
            proposal_id = uuid.uuid4().hex

            conn.execute(
                """
                INSERT INTO email_create_confirmations (
                    proposal_id,
                    mailbox,
                    conversation_id,
                    sender_email,
                    source_message_key,
                    draft_json,
                    draft_sha256,
                    status,
                    prepared_at,
                    expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'PREPARED', ?, ?)
                """,
                (
                    proposal_id,
                    mailbox,
                    conversation_id,
                    sender_email,
                    source_message_key,
                    draft_json,
                    digest,
                    now,
                    now + ttl_hours * 3600,
                ),
            )

            return proposal_id

    
    def mark_presented(self, proposal_id, graph_status_code):
        """Mark a confirmation as presented after Graph accepts the email.

        The full validity period starts at presentation, rather than
        when the draft was originally prepared.
        """

        # Require a valid proposal identifier.
        proposal_id = self._required_text(
            proposal_id,
            "proposal_id",
        )

        # Only Graph HTTP 202 is accepted as evidence that
        # Microsoft Graph accepted the confirmation for sending.
        if graph_status_code != 202:
            raise ValueError(
                "Confirmation was not accepted by Graph (HTTP 202)."
            )

        now = time.time()

        with self._connection() as conn:

            # Lock the transaction while changing confirmation state.
            conn.execute("BEGIN IMMEDIATE")

            # Preserve the original configured validity duration:
            # expires_at - prepared_at.
            #
            # Shift that duration to start from the presentation time.
            # For a new 72-hour proposal, expiry becomes approximately
            # 72 hours after Graph accepts the outgoing email.
            #
            # Expired or previously presented proposals cannot be
            # presented again or retroactively extended.
            result = conn.execute(
                """
                UPDATE email_create_confirmations

                SET status = 'PRESENTED',
                    presented_at = ?,
                    expires_at = ? + (expires_at - prepared_at)

                WHERE proposal_id = ?
                AND status = 'PREPARED'
                AND expires_at > ?
                """,
                (
                    now,
                    now,
                    proposal_id,
                    now,
                ),
            )

            # Reject unknown, expired, or already presented proposals.
            if result.rowcount != 1:
                raise RuntimeError(
                    "Proposal is missing, expired, "
                    "or already presented."
                )


    def record_reply(
        self,
        proposal_id,
        mailbox,
        conversation_id,
        sender_email,
        reply_message_key,
        decision,
        reply_received_at,
    ):
        """Record an interpreted confirmation without authorizing a write.

        The Communication Agent must classify the reply separately.
        An ambiguous reply must not invoke this method.
        """

        proposal_id = self._required_text(
            proposal_id, "proposal_id"
        )

        mailbox = self._required_text(
            mailbox, "mailbox"
        ).casefold()

        conversation_id = self._required_text(
            conversation_id, "conversation_id"
        )

        sender_email = self._required_text(
            sender_email, "sender_email"
        ).casefold()

        reply_message_key = self._required_text(
            reply_message_key, "reply_message_key"
        )

        # Python checks the structured decision supplied by
        # the agent; it does not interpret conversational wording.
        if decision not in ("CONFIRM", "DECLINE"):
            raise ValueError(
                "Decision must be CONFIRM or DECLINE."
            )

        if not isinstance(reply_received_at, (int, float)):
            raise ValueError(
                "Reply timestamp must be a Unix timestamp."
            )

        now = time.time()

        with self._connection() as conn:

            conn.execute("BEGIN IMMEDIATE")

            row = conn.execute(
                """
                SELECT
                    mailbox,
                    conversation_id,
                    sender_email,
                    source_message_key,
                    status,
                    presented_at,
                    expires_at
                FROM email_create_confirmations
                WHERE proposal_id = ?
                """,
                (proposal_id,),
            ).fetchone()

            if row is None:
                raise RuntimeError(
                    "Unknown confirmation proposal."
                )

            (
                stored_mailbox,
                stored_conversation,
                stored_sender,
                source_message_key,
                status,
                presented_at,
                expires_at,
            ) = row

            # A confirmation must belong to the exact same
            # mailbox, conversation, and sender.
            if (
                stored_mailbox,
                stored_conversation,
                stored_sender,
            ) != (
                mailbox,
                conversation_id,
                sender_email,
            ):
                raise RuntimeError(
                    "Confirmation belongs to a different "
                    "mailbox, thread, or sender."
                )

            # A prepared-but-not-presented proposal cannot
            # accept approval from any incoming email.
            if status != "PRESENTED" or presented_at is None:
                raise RuntimeError(
                    "Confirmation was not presented "
                    "or was already resolved."
                )

            if now >= expires_at:
                raise RuntimeError(
                    "Confirmation expired; prepare a new proposal."
                )

            # An earlier email cannot be treated as a reply
            # to a confirmation sent later.
            if (
                reply_message_key == source_message_key
                or reply_received_at <= presented_at
            ):
                raise RuntimeError(
                    "Reply must be a newer, distinct message "
                    "received after presentation."
                )

            # Confirmation means the draft was accepted by the
            # participant. It does NOT mean authorization passed.
            new_status = (
                "CONFIRMED_PENDING_AUTHORIZATION"
                if decision == "CONFIRM"
                else "DECLINED"
            )

            conn.execute(
                """
                UPDATE email_create_confirmations
                SET status = ?,
                    reply_message_key = ?
                WHERE proposal_id = ?
                """,
                (
                    new_status,
                    reply_message_key,
                    proposal_id,
                ),
            )

            return new_status

    def invalidate(self, proposal_id):
        """Invalidate an old proposal when the request details change."""

        proposal_id = self._required_text(
            proposal_id, "proposal_id"
        )

        with self._connection() as conn:

            changed = conn.execute(
                """
                UPDATE email_create_confirmations
                SET status = 'INVALIDATED'
                WHERE proposal_id = ?
                  AND status IN ('PREPARED', 'PRESENTED')
                """,
                (proposal_id,),
            )

            if changed.rowcount != 1:
                raise RuntimeError(
                    "Proposal cannot be invalidated "
                    "in its current state."
                )

    def get(self, proposal_id):
        """Retrieve a saved proposal for inspection or testing."""

        proposal_id = self._required_text(
            proposal_id, "proposal_id"
        )

        with self._connection() as conn:

            row = conn.execute(
                """
                SELECT
                    status,
                    draft_json,
                    mailbox,
                    conversation_id,
                    sender_email,
                    source_message_key,
                    presented_at,
                    expires_at,
                    reply_message_key
                FROM email_create_confirmations
                WHERE proposal_id = ?
                """,
                (proposal_id,),
            ).fetchone()

        if row is None:
            return None

        # Return the exact saved draft, not the currently
        # editable conversation draft.
        return {
            "status": row[0],
            "draft": json.loads(row[1]),
            "mailbox": row[2],
            "conversation_id": row[3],
            "sender_email": row[4],
            "source_message_key": row[5],
            "presented_at": row[6],
            "expires_at": row[7],
            "reply_message_key": row[8],
        }
