
"""Send one frozen CREATE confirmation in the controlled Outlook test thread.

Only the email confirmation state can change. This script never runs a
request CREATE, UPDATE, CANCEL, or other database write operation.
"""

import hashlib
import json
import os
import sys
import time

from pathlib import Path
from urllib.parse import quote

import requests

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential


# Locate the main enterprise-request-management project directory.
# This script resides inside the email_integration subfolder,
# while chat_prototype.py is located one directory above it.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Add the project root to Python's module search path.
# This allows the email integration script to import and reuse
# the existing chatbot logic without duplicating its functions.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# Reuse the existing duplicate detection and Operations Agent logic.
from chat_prototype import duplicate_matches

from email_approval_store import EmailApprovalStore

from email_operations_preview import load_reviewable_draft

from email_thread_preview import (
    AUTOMATED_REPLY_MARKER,
    test_mailbox,
)

from outlook_connect import GRAPH_BASE_URL

from prepare_email_confirmation_preview import (
    compose_confirmation,
    select_processed_source,
)

from send_thread_ack_test import (
    authenticate,
    validate_reply_destination,
)

from thread_store import EmailThreadStore


# A separate send ledger ensures that the same proposal cannot
# accidentally trigger multiple confirmation emails.
ATTEMPT_LOG = Path(__file__).with_name(
    ".confirmation_send_attempts.json"
)


def read_attempts():
    """Load persistent sending attempts; invalid state fails closed."""

    if not ATTEMPT_LOG.exists():
        return {}

    data = json.loads(
        ATTEMPT_LOG.read_text(encoding="utf-8")
    )

    # A damaged ledger must not silently permit another send.
    if not isinstance(data, dict):
        raise RuntimeError(
            "Confirmation attempt ledger is invalid."
        )

    return data


def save_attempts(attempts):
    """Save sending state before issuing a Graph send request."""

    # Write to a temporary file first to reduce partial writes.
    temporary = ATTEMPT_LOG.with_suffix(".tmp")

    temporary.write_text(
        json.dumps(attempts, indent=2),
        encoding="utf-8",
    )

    # Replace the previous ledger after writing is complete.
    temporary.replace(ATTEMPT_LOG)


def main():
    """Validate a frozen proposal and send after explicit confirmation."""

    # Require the same configuration used in earlier Outlook tests.
    required_variables = (
        "OUTLOOK_CLIENT_ID",
        "OUTLOOK_TEST_RECIPIENT",
        "OUTLOOK_DEMO_REQUESTER_EMAIL",
        "FOUNDRY_PROJECT_ENDPOINT",
        "OUTLOOK_CONFIRMATION_PROPOSAL_ID",
    )

    for key in required_variables:
        if not os.getenv(key):
            raise RuntimeError(
                f"Missing environment variable: {key}"
            )

    proposal_id = os.environ[
        "OUTLOOK_CONFIRMATION_PROPOSAL_ID"
    ].strip()

    # Load the immutable proposal prepared during the last step.
    approvals = EmailApprovalStore()

    snapshot = approvals.get(proposal_id)

    # Only PREPARED proposals can be sent for the first time.
    if not snapshot or snapshot["status"] != "PREPARED":
        raise RuntimeError(
            "Proposal is missing or is not PREPARED."
        )

    # Expired proposals must never be presented as valid.
    if time.time() >= snapshot["expires_at"]:
        raise RuntimeError(
            "Proposal has expired. Prepare a new proposal."
        )

    print("Opening Microsoft sign-in...")

    # Reuse the existing authentication helper that requests
    # delegated Graph Mail.Read and Mail.Send permissions.
    token = authenticate()

    # Verify the signed-in account matches the configured mailbox.
    mailbox = test_mailbox(token)

    # The saved proposal must belong to the same mailbox and sender.
    if (
        snapshot["mailbox"] != mailbox
        or snapshot["sender_email"] != mailbox
    ):
        raise RuntimeError(
            "Proposal does not belong to the test mailbox."
        )

    # Check the Outlook thread for any newer unprocessed message.
    # An updated requester instruction would make the proposal stale.
    source = select_processed_source(
        token,
        mailbox,
        EmailThreadStore(),
    )

    # Bind sending to the same conversation and source message
    # used when the immutable proposal was prepared.
    if (
        source["conversationId"] != snapshot["conversation_id"]
        or source["internetMessageId"]
        != snapshot["source_message_key"]
    ):
        raise RuntimeError(
            "A newer requester message or different thread was found. "
            "Update the draft and prepare a new confirmation."
        )

    # Verify From and Reply-To directly through Microsoft Graph.
    # This test must never reply to an external mailbox.
    validate_reply_destination(
        token,
        source,
        mailbox,
    )

    # Compare the current saved draft to the frozen proposal.
    # A modification requires a new confirmation snapshot.
    current_draft = load_reviewable_draft(
        token,
        mailbox,
    )

    if current_draft != snapshot["draft"]:
        raise RuntimeError(
            "Saved draft differs from the frozen proposal."
        )

    # Restrict the demonstration to the previously configured
    # fictional requester identity.
    # This is a test safeguard, not identity verification.
    demo_requester = os.environ[
        "OUTLOOK_DEMO_REQUESTER_EMAIL"
    ].strip().casefold()

    if (
        snapshot["draft"]["requester_email"]
        .strip().casefold()
        != demo_requester
    ):
        raise RuntimeError(
            "Proposal does not match the fictional demo requester."
        )

    # Build a stable ledger key without saving the raw proposal ID.
    attempt_key = hashlib.sha256(
        proposal_id.encode("utf-8")
    ).hexdigest()

    attempts = read_attempts()

    # Prevent duplicate sends after both successful and
    # uncertain previous attempts.
    if attempt_key in attempts:
        print(
            "A sending attempt already exists for this proposal."
        )
        print("No additional email was sent.")
        return

    print("\nRerunning the read-only duplicate check...")

    # Connect to the same two Foundry agents used by the chatbot.
    with AIProjectClient(
        endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        credential=AzureCliCredential(),
    ) as project:

        with (
            project.get_openai_client(
                agent_name="request-communication-agent"
            ) as comm,
            project.get_openai_client(
                agent_name="request-operations-agent"
            ) as ops,
        ):

            # Reuse the existing Operations Agent and semantic
            # duplicate detection before presenting the proposal.
            matches = duplicate_matches(
                snapshot["draft"],
                comm,
                ops,
            )

            if not isinstance(matches, list):
                raise RuntimeError(
                    "Duplicate screening returned invalid results."
                )

            # Any potential match blocks sending this confirmation.
            if matches:
                print(
                    "Potential duplicates found. "
                    "Confirmation was not sent."
                )

                for match in matches:
                    print(
                        "-",
                        match.get("request_id"),
                        match.get("title"),
                    )

                return

            # The original preview text was not stored.
            # Regenerate the email using the same frozen snapshot.
            # The user will inspect this exact version before sending.
            body = compose_confirmation(
                comm,
                snapshot["draft"],
                proposal_id,
            )

    # Include the proposal reference for the next email stage.
    # The temporary marker allows the existing reader to
    # recognize and skip this application-generated message.
    outgoing_body = (
        body.rstrip()
        + f"\n\nProposal reference: {proposal_id}"
        + f"\n\n{AUTOMATED_REPLY_MARKER}"
    )

    print("\n--- CONFIRMATION EMAIL PREVIEW ---")
    print("To:", mailbox)
    print("Replying to:", source["subject"])
    print()
    print(outgoing_body)
    print("--- END PREVIEW ---")

    print(
        "\nNo IT request will be created, updated, "
        "or cancelled by this script."
    )

    # Require deliberate approval before sending a real email.
    confirmation = input(
        "Type SEND to send this confirmation: "
    ).strip()

    if confirmation != "SEND":
        print(
            "Cancelled. No email was sent or presented."
        )
        return

    # Save ATTEMPTED before making the network request.
    # A timeout could occur after Graph accepts the email.
    attempts[attempt_key] = "ATTEMPTED"

    save_attempts(attempts)

    # Reply within the existing Outlook conversation.
    # The request body contains only the generated text.
    try:

        response = requests.post(
            (
                f"{GRAPH_BASE_URL}/me/messages/"
                f"{quote(source['id'], safe='')}/reply"
            ),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "comment": outgoing_body,
            },
            timeout=30,
        )

    except requests.RequestException as error:

        # A network error does not prove sending failed.
        # Never resend automatically when the outcome is uncertain.
        print(
            "Send outcome uncertain:",
            type(error).__name__,
        )

        print(
            "Inspect Outlook before any manual recovery."
        )

        return

    if response.status_code != 202:

        # Retain the attempt record pending manual investigation.
        print(
            "Graph did not accept the reply:",
            response.status_code,
        )

        print(
            "The attempt remains blocked until reviewed."
        )

        return

    # Graph has accepted the email.
    # Transition PREPARED -> PRESENTED in the approval database.
    try:

        approvals.mark_presented(
            proposal_id,
            response.status_code,
        )

    except Exception as error:

        # If the database transition fails after sending,
        # preserve the blocked attempt rather than sending again.
        print(
            "Graph accepted the email, "
            "but the state transition failed."
        )

        print(
            "Inspect the proposal and mailbox. "
            "Do not resend automatically."
        )

        print("Error:", type(error).__name__)

        return

    # Record Graph acceptance in the local sending ledger.
    # The existing ATTEMPTED entry still blocks duplicates
    # if this optional diagnostic update fails.
    try:

        attempts[attempt_key] = "ACCEPTED_BY_GRAPH"

        save_attempts(attempts)

    except OSError:

        print(
            "Warning: Proposal was presented, "
            "but the sending ledger update failed."
        )

    print("\nGraph accepted the confirmation: HTTP 202.")

    print(
        "Proposal status:",
        approvals.get(proposal_id)["status"],
    )

    print(
        "Check Outlook for delivery. "
        "No request database write occurred."
    )


if __name__ == "__main__":
    main()
