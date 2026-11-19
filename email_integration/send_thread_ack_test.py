
"""Send a saved GPT-5 Mini acknowledgment to an Outlook test thread.

This script:
- Reads the latest email in the controlled test conversation.
- Retrieves the Communication Agent's previously saved reply.
- Verifies that replying will only reach the test mailbox.
- Requires explicit SEND confirmation.
- Records sending attempts to prevent accidental repeated replies.

No Operations Agent or IT request database writes are performed.
"""

import hashlib
import json
import os

from pathlib import Path
from urllib.parse import quote

import msal
import requests

# Reuse the existing Outlook thread reader and mailbox validation.
from email_thread_preview import (
    AUTOMATED_REPLY_MARKER,
    find_test_thread,
    test_mailbox,
)

# Reuse the existing Microsoft Graph read helper.
from email_agent_preview import graph_read

# Reuse the configured Microsoft authentication authority and Graph URL.
from outlook_connect import (
    AUTHORITY,
    GRAPH_BASE_URL,
)

# Load saved conversation state from the existing thread database.
from thread_store import EmailThreadStore


# Delegated permissions required for this test.
SCOPES = [
    "User.Read",
    "Mail.Read",
    "Mail.Send",
]

# Local ledger prevents sending another acknowledgment to
# the same incoming email after a completed or uncertain send attempt.
ATTEMPT_LOG = Path(__file__).with_name(
    ".thread_reply_attempts.json"
)


def authenticate():
    """Authenticate to Outlook using the existing Entra application."""

    # Read the application identifier from the CMD environment.
    client_id = os.getenv("OUTLOOK_CLIENT_ID")

    if not client_id:
        raise RuntimeError(
            "OUTLOOK_CLIENT_ID is not configured."
        )

    # Personal Microsoft accounts use the consumers authority.
    # This is a public client; no client secret is required.
    app = msal.PublicClientApplication(
        client_id,
        authority=AUTHORITY,
    )

    # Obtain read and send permissions through interactive sign-in.
    result = app.acquire_token_interactive(
        scopes=SCOPES,
    )

    if "access_token" not in result:
        raise RuntimeError(
            "Microsoft authentication did not return an access token."
        )

    return result["access_token"]


def load_attempts():
    """Read previously recorded sending attempts."""

    if not ATTEMPT_LOG.exists():
        return {}

    attempts = json.loads(
        ATTEMPT_LOG.read_text(encoding="utf-8")
    )

    # A corrupted ledger must not silently enable duplicate sends.
    if not isinstance(attempts, dict):
        raise RuntimeError(
            "Invalid sending ledger. Inspect it before proceeding."
        )

    return attempts


def save_attempts(attempts):
    """Save sending state using a temporary file."""

    # Replace the existing file only after serialization finishes.
    temporary = ATTEMPT_LOG.with_suffix(".tmp")

    temporary.write_text(
        json.dumps(attempts, indent=2),
        encoding="utf-8",
    )

    temporary.replace(ATTEMPT_LOG)


def validate_reply_destination(token, item, mailbox):
    """Check that the reply is restricted to the test mailbox."""

    # Retrieve current message metadata directly from Graph.
    # This is more reliable than trusting older cached metadata.
    details = graph_read(
        token,
        f"/me/messages/{quote(item['id'], safe='')}",
        params={
            "$select": (
                "id,conversationId,internetMessageId,"
                "subject,from,replyTo"
            )
        },
    )

    # Ensure the retrieved message belongs to the selected conversation.
    if (
        details.get("conversationId") != item.get("conversationId")
        or details.get("internetMessageId") != item.get("internetMessageId")
    ):
        raise RuntimeError(
            "Message identity changed during validation."
        )

    # Extract the actual sender address.
    from_address = (
        (
            (details.get("from") or {})
            .get("emailAddress") or {}
        ).get("address") or ""
    ).strip().casefold()

    # This experiment permits only self-sent test messages.
    if from_address != mailbox:
        raise RuntimeError(
            "The source email was not sent by the test mailbox."
        )

    # Graph can send replies to Reply-To instead of From.
    # Reject any Reply-To destination outside the test mailbox.
    reply_to = details.get("replyTo") or []

    if not isinstance(reply_to, list):
        raise RuntimeError(
            "Unexpected Reply-To format."
        )

    addresses = [
        (
            (entry.get("emailAddress") or {})
            .get("address") or ""
        ).strip().casefold()
        for entry in reply_to
        if isinstance(entry, dict)
    ]

    if reply_to and addresses != [mailbox]:
        raise RuntimeError(
            "Reply-To is not exactly the test mailbox."
        )

    return details


def main():
    """Send one saved agent-generated reply with explicit approval."""

    print("Opening Microsoft sign-in...")

    # Authenticate using the existing Microsoft app registration.
    token = authenticate()

    # Verify the test recipient matches the authenticated mailbox.
    mailbox = test_mailbox(token)

    # Read the existing [ERM-THREAD-TEST] conversation.
    messages = find_test_thread(token)

    if not messages:
        print(
            "No test email thread found. "
            "Process a test email first."
        )
        return

    # The existing reader returns messages chronologically.
    # Only the latest email is eligible for this sending test.
    latest = messages[-1]

    store = EmailThreadStore()

    # Do not send a response to an email that has not already
    # been interpreted and persisted by the Communication Agent.
    status = store.message_status(
        mailbox,
        latest.get("internetMessageId"),
    )

    if status != "PROCESSED":
        print(
            "Latest thread message is not processed. "
            "Run email_thread_preview.py first."
        )
        return

    # Restore the conversation state saved during the preview stage.
    state = store.load_state(
        mailbox,
        latest["conversationId"],
        mailbox,
    )

    conversation_history = (
        (state or {}).get("history") or []
    )

    # The last stored assistant response contains the actual
    # GPT-5 Mini-generated acknowledgment.
    if (
        not conversation_history
        or conversation_history[-1].get("role") != "assistant"
    ):
        raise RuntimeError(
            "No saved Communication Agent reply for this thread."
        )

    reply = conversation_history[-1].get("content")

    if not isinstance(reply, str) or not reply.strip():
        raise RuntimeError(
            "The saved agent reply is empty."
        )

    # Verify the original sender and Reply-To before sending.
    validate_reply_destination(
        token,
        latest,
        mailbox,
    )

    # Append a technical marker to the test email.
    # The inbox reader will skip messages containing this marker.
    outgoing_body = (
        reply.strip()
        + "\n\n"
        + AUTOMATED_REPLY_MARKER
    )

    # Identify this incoming email without storing its raw
    # internetMessageId in the sending ledger.
    fingerprint = hashlib.sha256(
        latest["internetMessageId"].encode("utf-8")
    ).hexdigest()

    attempts = load_attempts()

    # The same source email must not receive another automatic
    # acknowledgment after any recorded send attempt.
    if fingerprint in attempts:
        print(
            "A reply attempt is already recorded "
            "for this message. No resend."
        )
        return

    # Display the exact saved AI response before sending.
    print("\n--- SAVED AI REPLY PREVIEW ---")
    print("To:", mailbox)
    print("Source subject:", latest.get("subject"))
    print()
    print(outgoing_body)
    print("--- END PREVIEW ---")

    print(
        "\nNo request database operations will run."
    )

    # Sending is only performed after explicit human approval.
    confirmation = input(
        "Type SEND to send once, "
        "or anything else to cancel: "
    ).strip()

    if confirmation != "SEND":
        print("Cancelled; no email sent.")
        return

    # Record the attempt BEFORE sending.
    # A network timeout could occur after Graph accepts the message.
    # The ledger prevents an automatic duplicate send in that situation.
    attempts[fingerprint] = "ATTEMPTED"

    save_attempts(attempts)

    # Send as a reply to the actual Outlook conversation.
    # The body was generated by the Communication Agent earlier.
    try:
        response = requests.post(
            (
                f"{GRAPH_BASE_URL}/me/messages/"
                f"{quote(latest['id'], safe='')}/reply"
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

        # An exception does not establish whether Graph sent the email.
        # Manual verification is required before another attempt.
        print(
            "Send outcome uncertain:",
            type(error).__name__,
        )

        print(
            "Check Sent Items before any manual recovery. "
            "No automatic resend."
        )

        return

    if response.status_code == 202:

        # Graph accepted the reply for sending.
        # This is not the same as confirming final delivery.
        attempts = load_attempts()

        attempts[fingerprint] = "ACCEPTED"

        save_attempts(attempts)

        print(
            "Graph accepted the reply: HTTP 202. "
            "Check Outlook for delivery."
        )

    else:
        print(
            "Graph did not return 202. HTTP status:",
            response.status_code,
        )

        print(
            "Diagnostic:",
            response.text[:300],
        )

        # Keep the existing attempt entry to prevent repeated
        # sends without first investigating the failure.
        print(
            "Attempt retained to prevent uncertain repeated sending."
        )


if __name__ == "__main__":
    main()
