
"""Durable execution ledger for email-driven CREATE requests.

Purpose:
- Reserve at most one CREATE attempt for a confirmed proposal.
- Preserve execution state across Python restarts.
- Record successful request creation or uncertain outcomes.
- Prevent automatic retries after interrupted operations.

This module does not:
- Authenticate Microsoft Graph users.
- Invoke Foundry agents.
- Create or modify IT requests.

The future execution orchestrator must perform live authorization
and duplicate screening before reserving an attempt.
"""

import hashlib
import json
import sqlite3
import time
import uuid

from contextlib import contextmanager
from pathlib import Path

# Reuse the existing email confirmation database.
# The IT request database (requests.db) remains separate.
from email_approval_store import DEFAULT_DATABASE


class EmailCreateExecutionStore:
    """Maintain one durable CREATE attempt per confirmation proposal."""

    def __init__(self, path=DEFAULT_DATABASE):
        """Initialize the execution ledger in email_threads.db."""

        self.path = Path(path)
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self._connection() as conn:

            # The proposal ID is the primary key.
            # This prevents multiple CREATE attempts for the
            # same frozen confirmation proposal.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS
                    email_create_execution_attempts (

                    proposal_id TEXT PRIMARY KEY,
                    attempt_id TEXT NOT NULL UNIQUE,
                    draft_sha256 TEXT NOT NULL,

                    status TEXT NOT NULL CHECK (
                        status IN (
                            'CLAIMED',
                            'CREATED',
                            'NEEDS_REVIEW'
                        )
                    ),

                    claimed_at REAL NOT NULL,
                    finished_at REAL,
                    created_request_id TEXT,
                    note TEXT,

                    FOREIGN KEY (proposal_id)
                        REFERENCES email_create_confirmations(
                            proposal_id
                        )
                )
                """
            )

    @contextmanager
    def _connection(self):
        """Commit successful operations and roll back failures."""

        conn = sqlite3.connect(
            self.path,
            timeout=15,
        )

        # Named columns make query results easier to validate.
        conn.row_factory = sqlite3.Row

        # Enforce the link between execution attempts and
        # existing confirmation proposals.
        conn.execute(
            "PRAGMA foreign_keys = ON"
        )

        try:
            yield conn
            conn.commit()

        except Exception:
            conn.rollback()
            raise

        finally:
            conn.close()

    @staticmethod
    def _identifier(value, name):
        """Reject missing or empty identifiers."""

        if (
            not isinstance(value, str)
            or not value.strip()
        ):
            raise ValueError(
                f"{name} must be a nonempty string."
            )

        return value.strip()

    def claim_for_create(self, proposal_id):
        """Reserve one execution attempt without creating a request.

        IMPORTANT:
        The caller must first complete live sender authorization
        and fresh duplicate screening.

        A claimed attempt cannot be retried automatically.
        """

        proposal_id = self._identifier(
            proposal_id,
            "proposal_id",
        )

        now = time.time()

        with self._connection() as conn:

            # Reserve the SQLite write lock before checking state.
            # Competing local workers cannot both claim the
            # same proposal successfully.
            conn.execute(
                "BEGIN IMMEDIATE"
            )

            # Load the original frozen approval directly
            # from persistent storage.
            proposal = conn.execute(
                """
                SELECT
                    status,
                    mailbox,
                    sender_email,
                    conversation_id,
                    reply_message_key,
                    presented_at,
                    expires_at,
                    draft_json,
                    draft_sha256

                FROM email_create_confirmations

                WHERE proposal_id = ?
                """,
                (proposal_id,),
            ).fetchone()

            if proposal is None:
                raise RuntimeError(
                    "Unknown confirmation proposal."
                )

            # The draft must already have received an
            # explicit recorded confirmation.
            #
            # For the current conservative demo policy,
            # the confirmation must also still be within
            # its original validity window.
            if (
                proposal["status"]
                != "CONFIRMED_PENDING_AUTHORIZATION"

                or not proposal["reply_message_key"]

                or proposal["presented_at"] is None

                or now >= proposal["expires_at"]
            ):
                raise RuntimeError(
                    "Proposal is not confirmed, is missing "
                    "reply evidence, or is past the "
                    "confirmation deadline."
                )

            # Verify that the frozen request details have not
            # been altered since the proposal was prepared.
            frozen_json = proposal["draft_json"]

            digest = hashlib.sha256(
                frozen_json.encode("utf-8")
            ).hexdigest()

            if digest != proposal["draft_sha256"]:
                raise RuntimeError(
                    "Frozen proposal content failed "
                    "integrity verification."
                )

            # Decode the immutable request details.
            draft = json.loads(frozen_json)

            if not isinstance(draft, dict):
                raise RuntimeError(
                    "Frozen proposal has an invalid format."
                )

            # Apply the restricted self-service demo boundary.
            #
            # Requests on another user's behalf remain blocked.
            # This comparison supplements, but does not replace,
            # Microsoft Graph identity verification.
            mailbox = (
                proposal["mailbox"] or ""
            ).strip().casefold()

            sender = (
                proposal["sender_email"] or ""
            ).strip().casefold()

            requester = draft.get(
                "requester_email"
            )

            requester = (
                requester.strip().casefold()
                if isinstance(requester, str)
                else ""
            )

            if (
                not mailbox
                or sender != mailbox
                or requester != mailbox
            ):
                raise RuntimeError(
                    "On-behalf-of creation is disabled "
                    "in this demo."
                )

            # Check whether any attempt already exists.
            #
            # CLAIMED, CREATED, and NEEDS_REVIEW all block
            # a second automatic CREATE attempt.
            existing = conn.execute(
                """
                SELECT status
                FROM email_create_execution_attempts
                WHERE proposal_id = ?
                """,
                (proposal_id,),
            ).fetchone()

            if existing:

                raise RuntimeError(
                    "CREATE attempt already recorded "
                    f"({existing['status']}); "
                    "manual reconciliation is required."
                )

            # Generate a unique execution attempt identifier.
            attempt_id = uuid.uuid4().hex

            # Save the claim before any future CREATE tool call.
            #
            # A restart after this point will find the existing
            # claim and refuse to repeat the operation.
            conn.execute(
                """
                INSERT INTO email_create_execution_attempts (
                    proposal_id,
                    attempt_id,
                    draft_sha256,
                    status,
                    claimed_at
                )

                VALUES (?, ?, ?, 'CLAIMED', ?)
                """,
                (
                    proposal_id,
                    attempt_id,
                    digest,
                    now,
                ),
            )

            return attempt_id

    def mark_created(
        self,
        proposal_id,
        attempt_id,
        request_id,
    ):
        """Record a verified successful CREATE operation.

        The future orchestrator must verify the created request
        before calling this method.
        """

        proposal_id = self._identifier(
            proposal_id,
            "proposal_id",
        )

        attempt_id = self._identifier(
            attempt_id,
            "attempt_id",
        )

        request_id = self._identifier(
            request_id,
            "request_id",
        )

        with self._connection() as conn:

            # Only the exact claimed attempt may transition
            # to CREATED, and only once.
            result = conn.execute(
                """
                UPDATE email_create_execution_attempts

                SET status = 'CREATED',
                    finished_at = ?,
                    created_request_id = ?

                WHERE proposal_id = ?
                  AND attempt_id = ?
                  AND status = 'CLAIMED'
                """,
                (
                    time.time(),
                    request_id,
                    proposal_id,
                    attempt_id,
                ),
            )

            if result.rowcount != 1:
                raise RuntimeError(
                    "Attempt cannot be marked CREATED."
                )

    def mark_needs_review(
        self,
        proposal_id,
        attempt_id,
        note,
    ):
        """Record an uncertain outcome without permitting retry."""

        proposal_id = self._identifier(
            proposal_id,
            "proposal_id",
        )

        attempt_id = self._identifier(
            attempt_id,
            "attempt_id",
        )

        note = self._identifier(
            note,
            "note",
        )

        # Keep diagnostics short and avoid saving
        # secrets, tokens, or complete exception traces.
        if len(note) > 200:
            raise ValueError(
                "Diagnostic note exceeds 200 characters."
            )

        with self._connection() as conn:

            # Only a claimed attempt can move to NEEDS_REVIEW.
            result = conn.execute(
                """
                UPDATE email_create_execution_attempts

                SET status = 'NEEDS_REVIEW',
                    finished_at = ?,
                    note = ?

                WHERE proposal_id = ?
                  AND attempt_id = ?
                  AND status = 'CLAIMED'
                """,
                (
                    time.time(),
                    note,
                    proposal_id,
                    attempt_id,
                ),
            )

            if result.rowcount != 1:
                raise RuntimeError(
                    "Attempt cannot be marked NEEDS_REVIEW."
                )

    def get(self, proposal_id):
        """Retrieve the execution record without modifying it."""

        proposal_id = self._identifier(
            proposal_id,
            "proposal_id",
        )

        with self._connection() as conn:

            result = conn.execute(
                """
                SELECT
                    proposal_id,
                    attempt_id,
                    status,
                    claimed_at,
                    finished_at,
                    created_request_id,
                    note

                FROM email_create_execution_attempts

                WHERE proposal_id = ?
                """,
                (proposal_id,),
            ).fetchone()

        return dict(result) if result else None
