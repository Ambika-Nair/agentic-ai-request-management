
"""Send one GPT-5 Mini-generated acknowledgment as an Outlook reply.

This controlled test replies only to an email sent by the signed-in
mailbox. It never invokes the Operations Agent or modifies SQLite.
"""

import hashlib
import json
import os
import sys

from pathlib import Path
from urllib.parse import quote

import msal
import requests

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential


# Make the existing root-level chatbot functions importable
# from this email_integration subfolder.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# Reuse the Communication Agent functions already developed.
from chat_prototype import (
    new_state,
    plan_turn,
    understand_create,
)

# Reuse the working email retrieval and AI response functions.
from email_agent_preview import (
    TEST_SUBJECT,
    generate_reply_preview,
    get_test_email,
    graph_read,
)

# Reuse Microsoft Graph configuration and account lookup.
from outlook_connect import (
    AUTHORITY,
    GRAPH_BASE_URL,
    get_account_info,
)


# Reading the original message and sending a reply require
# both delegated mailbox permissions.
SCOPES = [
    "User.Read",
    "Mail.Read",
    "Mail.Send",
]

# Keep a local record of test reply attempts.
# This prevents accidentally sending the same acknowledgment twice.
ATTEMPT_LOG = Path(__file__).with_name(
    ".outlook_reply_attempts.json"
)


def authenticate():
    """Authenticate the personal Outlook account for read/send access."""

    # Obtain the Entra app registration identifier from CMD.
    client_id = os.getenv("OUTLOOK_CLIENT_ID")

    if not client_id:
        raise RuntimeError(
            "OUTLOOK_CLIENT_ID is not configured."
        )

    # The consumers authority supports personal Microsoft accounts.
    # No client secret or mailbox password is stored.
    app = msal.PublicClientApplication(
        client_id,
        authority=AUTHORITY,
    )

    # Request the permissions required for both retrieving
    # the original message and sending its reply.
    result = app.acquire_token_interactive(
        scopes=SCOPES,
    )

    if "access_token" not in result:
        raise RuntimeError(
            "Outlook authentication failed: "
            + str(result.get("error", "unknown"))
        )

    return result["access_token"]


def verify_self_reply(token, message):
    """Confirm the email reply cannot be sent to another mailbox.

    Microsoft Graph uses Reply-To when one is specified.
    Both From and Reply-To are therefore checked.
    """

    # Retrieve the identity of the account that authenticated.
    account = get_account_info(token)

    account_addresses = {
        address.strip().casefold()
        for address in (
            account.get("mail"),
            account.get("userPrincipalName"),
        )
        if isinstance(address, str) and address.strip()
    }

    # The permitted destination must be configured explicitly.
    expected = (
        os.getenv("OUTLOOK_TEST_RECIPIENT") or ""
    ).strip().casefold()

    if not expected or expected not in account_addresses:
        raise RuntimeError(
            "OUTLOOK_TEST_RECIPIENT must match "
            "the signed-in Outlook mailbox."
        )

    # Retrieve Reply-To separately because the existing
    # email preview reader does not request that field.
    message_id = quote(
        message["id"],
        safe="",
    )

    details = graph_read(
        token,
        f"/me/messages/{message_id}",
        params={
            "$select": "subject,from,replyTo",
        },
    )

    # Only the original Adobe Acrobat test message is permitted.
    if details.get("subject") != TEST_SUBJECT:
        raise RuntimeError(
            "Unexpected original email subject."
        )

    # Confirm the email originated from the test mailbox.
    sender = (
        (
            (details.get("from") or {})
            .get("emailAddress") or {}
        ).get("address") or ""
    ).casefold()

    if sender != expected:
        raise RuntimeError(
            "This test can only reply to a message "
            "sent by the signed-in mailbox."
        )

    # A Reply-To header may redirect the reply to a
    # different address. Reject every destination except
    # the permitted test mailbox.
    reply_to = details.get("replyTo") or []

    if not isinstance(reply_to, list):
        raise RuntimeError(
            "Unexpected Reply-To format."
        )

    if reply_to:

        destinations = [
            (
                (item.get("emailAddress") or {})
                .get("address") or ""
            ).casefold()
            for item in reply_to
            if isinstance(item, dict)
        ]

    else:
        destinations = [sender]

    if destinations != [expected]:
        raise RuntimeError(
            "Reply-To does not match the test mailbox."
        )

    return expected


def read_attempt_log():
    """Load previously attempted replies from a local JSON file."""

    if not ATTEMPT_LOG.exists():
        return {}

    data = json.loads(
        ATTEMPT_LOG.read_text(encoding="utf-8")
    )

    # A corrupted ledger must not silently permit duplicate sends.
    if not isinstance(data, dict):
        raise RuntimeError(
            "The reply-attempt ledger is invalid."
        )

    return data


def save_attempt_log(data):
    """Save the reply-attempt ledger using a temporary file."""

    # Replace the file after fully writing the new content.
    # This reduces the chance of leaving a partial JSON file.
    temporary = ATTEMPT_LOG.with_suffix(".tmp")

    temporary.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8",
    )

    temporary.replace(ATTEMPT_LOG)


def main():
    """Interpret one test email and send its reply after confirmation."""

    # Verify that the existing Foundry endpoint is configured.
    if not os.getenv("FOUNDRY_PROJECT_ENDPOINT"):
        raise RuntimeError(
            "FOUNDRY_PROJECT_ENDPOINT is not configured."
        )

    print("Opening Microsoft sign-in...")

    token = authenticate()

    print("Microsoft authentication succeeded.")

    # Reuse the working reader to locate the exact test email.
    email = get_test_email(token)

    if not email:
        print(
            f"No matching email found for {TEST_SUBJECT!r}."
        )
        return

    # Reject any reply that could leave the test mailbox.
    recipient = verify_self_reply(
        token,
        email,
    )

    # Confirm the original email body is plain text.
    message_body = email.get("body") or {}
    content = message_body.get("content")

    if str(
        message_body.get("contentType", "")
    ).lower() != "text":
        raise RuntimeError(
            "Expected a plain-text email body."
        )

    if (
        not isinstance(content, str)
        or not content.strip()
        or len(content) > 4000
    ):
        raise RuntimeError(
            "The test email body is missing or too long."
        )

    # Convert the original email to the same text format
    # used successfully during the earlier preview.
    input_text = (
        f"Email subject: {email['subject']}\n"
        f"Email message:\n{content}"
    )

    state = new_state()

    # Connect only to the existing Communication Agent.
    # No Operations Agent or database function is invoked.
    with AIProjectClient(
        endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        credential=AzureCliCredential(),
    ) as project:

        with project.get_openai_client(
            agent_name="request-communication-agent"
        ) as comm:

            # GPT-5 Mini interprets the email intent.
            plan = plan_turn(
                comm,
                input_text,
                state,
            )

            if plan.get("intent") != "CREATE":
                raise RuntimeError(
                    "The test email was not classified as CREATE."
                )

            # GPT-5 Mini extracts request information and
            # generates a title using existing project logic.
            state["flow"] = "CREATE"

            draft = understand_create(
                comm,
                state,
                input_text,
                plan,
            )

            # Identify required information without assigning
            # defaults for requester identity or priority.
            required = (
                "title",
                "request_type",
                "priority",
                "requester_name",
                "requester_email",
            )

            missing = [
                key
                for key in required
                if not draft.get(key)
            ]

            # GPT-5 Mini generates the acknowledgment body.
            # The existing function prohibits claiming that
            # any database operation has occurred.
            reply = generate_reply_preview(
                comm,
                draft,
                missing,
            )

    # Create a stable fingerprint for this specific message.
    # The raw Graph message ID is not stored in the ledger.
    fingerprint = hashlib.sha256(
        email["id"].encode("utf-8")
    ).hexdigest()

    attempts = read_attempt_log()

    # Prevent a repeated run from accidentally sending
    # another reply to the same original message.
    if fingerprint in attempts:
        print(
            "A reply attempt is already recorded for "
            "this test email. Nothing was sent."
        )
        return

    # Show the exact AI-generated reply before sending it.
    print("\n--- AI-GENERATED REPLY PREVIEW ---")
    print("Reply destination:", recipient)
    print("Original subject:", email["subject"])
    print()
    print(reply)
    print("--- END PREVIEW ---")

    print(
        "\nNo request will be created, updated, "
        "or cancelled in SQLite."
    )

    # Sending remains under explicit human control.
    confirmation = input(
        "Type SEND to send this reply, "
        "or anything else to cancel: "
    ).strip()

    if confirmation != "SEND":
        print("Cancelled. No email was sent.")
        return

    # Record the attempt BEFORE making the network call.
    # If the network times out, rerunning cannot blindly
    # resend a reply that might already have been accepted.
    attempts[fingerprint] = "attempted"

    save_attempt_log(attempts)

    # Use Graph's reply endpoint to respond to the original
    # message, rather than composing an unrelated new email.
    try:

        response = requests.post(
            (
                f"{GRAPH_BASE_URL}/me/messages/"
                f"{quote(email['id'], safe='')}/reply"
            ),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            # Graph accepts the reply text in the comment field.
            json={
                "comment": reply,
            },
            timeout=30,
        )

    except requests.RequestException as error:

        # A timeout does not prove that sending failed.
        # Do not retry automatically.
        print(
            "Send outcome uncertain: "
            f"{type(error).__name__}"
        )

        print(
            "Check Outlook Sent Items before "
            "attempting any further action."
        )

        return

    if response.status_code == 202:

        # Update the local ledger after Graph accepts the reply.
        attempts = read_attempt_log()

        attempts[fingerprint] = "accepted"

        save_attempt_log(attempts)

        print(
            "\nMicrosoft Graph accepted "
            "the AI-generated reply."
        )

        print("HTTP status: 202 Accepted")

        print(
            "Check Outlook Inbox and Sent Items "
            "to confirm delivery."
        )

    else:

        print(
            "\nMicrosoft Graph did not accept the reply."
        )

        print("HTTP status:", response.status_code)

        # Limit diagnostic output to avoid exposing
        # unnecessarily large service responses.
        print(
            "Diagnostic:",
            response.text[:300],
        )

        print(
            "The attempt remains recorded to prevent "
            "an unsafe automatic resend."
        )


if __name__ == "__main__":
    main()
