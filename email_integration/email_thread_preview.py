
"""Preview a multi-email Outlook conversation using the existing Foundry agent.

The script:
- Reads one specifically labeled Outlook test conversation.
- Loads and saves its draft in email_threads.db.
- Uses the existing GPT-5 Mini Communication Agent.
- Prevents reprocessing the same incoming message.
- Displays an email reply preview without sending it.

No Operations Agent or requests.db write is performed.
"""

import json
import os
import sys

from pathlib import Path
from urllib.parse import quote

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential


# Make root-level project modules available to this script.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# Reuse existing agent and request-drafting functions.
from chat_prototype import (
    new_state,
    plan_turn,
    understand_create,
)

# Reuse the previously tested Outlook and reply-preview functions.
from email_agent_preview import (
    generate_reply_preview,
    graph_read,
)

from outlook_connect import (
    authenticate,
    get_account_info,
)

from thread_store import EmailThreadStore


# Use a new test subject to avoid previous email experiments.
TEST_SUBJECT = "[ERM-SELF-SERVICE-TEST] Ergonomic keyboard"

# Technical marker added to outgoing test replies.
# This prevents a self-addressed automated email from being
# interpreted as a new user instruction in the same thread.
AUTOMATED_REPLY_MARKER = "[ERM-THREAD-AUTO-REPLY]"

# Keep mailbox queries and message sizes small during testing.
MAX_INBOX_MESSAGES = 50
MAX_BODY_LENGTH = 4000

# Fields required for a complete request draft.
# No default priority is assigned.
REQUIRED_FIELDS = (
    "title",
    "request_type",
    "priority",
    "requester_name",
    "requester_email",
)


def base_subject(subject):
    """Remove email reply prefixes for test-thread filtering."""

    value = (subject or "").strip()

    # A reply normally adds "Re:" to the original subject.
    # This is mailbox routing logic, not user-intent interpretation.
    while value.casefold().startswith("re:"):
        value = value[3:].strip()

    return value.casefold()


def test_mailbox(token):
    """Verify the test account is the signed-in Outlook mailbox."""

    # Obtain the authenticated account's addresses from Graph.
    account = get_account_info(token)

    permitted = {
        value.strip().casefold()
        for value in (
            account.get("mail"),
            account.get("userPrincipalName"),
        )
        if isinstance(value, str) and value.strip()
    }

    # Restrict the experiment to the existing test mailbox.
    configured = (
        os.getenv("OUTLOOK_TEST_RECIPIENT") or ""
    ).strip().casefold()

    if not configured or configured not in permitted:
        raise RuntimeError(
            "OUTLOOK_TEST_RECIPIENT must match "
            "the signed-in Outlook mailbox."
        )

    return configured


def find_test_thread(token):
    """Retrieve the newest matching test conversation from Outlook."""

    # Read message metadata from the Inbox only.
    # Other emails will not be processed by this test.
    response = graph_read(
        token,
        "/me/mailFolders/inbox/messages",
        params={
            "$top": MAX_INBOX_MESSAGES,
            "$select": (
                "id,subject,conversationId,internetMessageId,"
                "receivedDateTime,from,isDraft"
            ),
            "$orderby": "receivedDateTime desc",
        },
    )

    messages = response.get("value")

    if not isinstance(messages, list):
        raise RuntimeError(
            "Microsoft Graph returned an invalid inbox listing."
        )

    # Find the newest original email with the exact test subject.
    starters = [
        item
        for item in messages
        if (
            item.get("subject", "").strip().casefold()
            == TEST_SUBJECT.casefold()
        )
        and item.get("conversationId")
        and not item.get("isDraft", False)
    ]

    if not starters:
        return []

    original = max(
        starters,
        key=lambda item: item.get("receivedDateTime") or "",
    )

    conversation_id = original["conversationId"]

    # Retrieve messages belonging to the same conversation.
    # Messages from different threads are excluded.
    thread = [
        item
        for item in messages
        if item.get("conversationId") == conversation_id
        and base_subject(item.get("subject")) == TEST_SUBJECT.casefold()
        and not item.get("isDraft", False)
    ]

    # Process messages chronologically so later replies can
    # use the previously saved request information.
    return sorted(
        thread,
        key=lambda item: (
            item.get("receivedDateTime") or "",
            item.get("id") or "",
        ),
    )


def fetch_unique_text(token, message_id):
    """Retrieve only the new text written in an Outlook message."""

    # Request uniqueBody explicitly.
    # The text preference avoids requiring HTML parsing.
    item = graph_read(
        token,
        f"/me/messages/{quote(message_id, safe='')}",
        params={
            "$select": (
                "id,subject,conversationId,internetMessageId,"
                "receivedDateTime,from,uniqueBody"
            ),
        },
        prefer_text=True,
    )

    unique = item.get("uniqueBody") or {}

    # Do not use the full quoted conversation as the latest
    # user message. That could incorrectly reapply old fields.
    if str(
        unique.get("contentType") or ""
    ).casefold() != "text":
        raise RuntimeError(
            "Graph did not return a plain-text uniqueBody."
        )

    content = unique.get("content")

    if not isinstance(content, str) or not content.strip():
        raise RuntimeError(
            "No unique message content was returned."
        )

    if len(content) > MAX_BODY_LENGTH:
        raise RuntimeError(
            "The new email text exceeds the preview limit."
        )

    return item, content.strip()


def sender_address(item):
    """Read the actual sender address returned by Microsoft Graph."""

    # Email addresses written inside the body are not
    # proof of the sender's real mailbox identity.
    return (
        (
            (item.get("from") or {})
            .get("emailAddress") or {}
        ).get("address") or ""
    ).strip().casefold()


def process_message(token, mailbox, item, comm, store):
    """Process one message using saved state and the Communication Agent."""

    message_id = item.get("id")
    message_key = item.get("internetMessageId")
    conversation_id = item.get("conversationId")

    # Require stable identifiers before recording message state.
    if not all(
        isinstance(value, str) and value.strip()
        for value in (
            message_id,
            message_key,
            conversation_id,
        )
    ):
        raise RuntimeError(
            "The email is missing a required message identifier."
        )

    # Skip messages that were already claimed or processed.
    # This prevents repeated runs from handling the same email.
    previous_status = store.message_status(
        mailbox,
        message_key,
    )

    if previous_status:
        print(
            f"Already {previous_status}: "
            f"{item.get('subject')}"
        )
        return

    # Fetch the current message content before claiming it.
    details, body = fetch_unique_text(
        token,
        message_id,
    )

    # Confirm Graph returned the same message and conversation.
    if details.get("conversationId") != conversation_id:
        raise RuntimeError(
            "Message conversation changed during retrieval."
        )

    if details.get("internetMessageId") != message_key:
        raise RuntimeError(
            "Message identity changed during retrieval."
        )

    # This initial experiment accepts only self-sent emails.
    # Additional senders require separate authorization design.
    if sender_address(details) != mailbox:
        raise RuntimeError(
            "Only self-sent emails are allowed in this test."
        )

    # Ignore responses generated by this application.
    # The marker is only transport metadata for the test workflow;
    # GPT-5 Mini remains responsible for natural-language reasoning.
    if AUTOMATED_REPLY_MARKER in body:
        print(
            "Skipped application-generated reply:",
            details.get("subject"),
        )
        return

    # Retrieve the existing draft, or initialize a new state.
    # This is the same state structure used by chat_prototype.py.
    state = store.load_state(
        mailbox,
        conversation_id,
        mailbox,
    ) or new_state()

    # Reserve the message before agent processing.
    # If an error occurs afterward, CLAIMED prevents an
    # unreviewed automatic retry.
    claimed = store.claim_message(
        mailbox,
        conversation_id,
        mailbox,
        message_key,
    )

    if not claimed:
        print("Message was already claimed.")
        return

    # Build the latest message input using only newly written text.
    text = (
        f"Email subject: {details['subject']}\n"
        f"Email message:\n{body}"
    )

    # Preserve the user message for conversational context.
    state["history"].append({
        "role": "user",
        "content": text,
    })

    # GPT-5 Mini decides the user's intention.
    plan = plan_turn(
        comm,
        text,
        state,
    )

    # This preview supports CREATE drafts and their follow-ups.
    # UPDATE and CANCEL are not connected to operational tools here.
    can_continue_create = (
        plan.get("intent") in {
            "CREATE",
            "CONTINUE",
            "CHAT",
        }
        and state.get("flow") in (
            None,
            "CREATE",
        )
    )

    if can_continue_create:

        # Continue the previously saved draft instead of
        # starting from empty data for every new email.
        state["flow"] = "CREATE"

        # Existing Communication Agent extracts and updates fields.
        draft = understand_create(
            comm,
            state,
            text,
            plan,
        )

        # Find missing fields without assigning defaults.
        missing = [
            field
            for field in REQUIRED_FIELDS
            if not draft.get(field)
        ]

        # The Communication Agent composes a read-only reply.
        reply = generate_reply_preview(
            comm,
            draft,
            missing,
        )

        # Save the generated response in conversation history.
        # This helps the agent understand later follow-ups.
        state["history"].append({
            "role": "assistant",
            "content": reply,
        })

        print("\nProcessed email:", details.get("subject"))

        print("\nCurrent saved draft:")
        print(
            json.dumps(
                draft,
                indent=2,
                ensure_ascii=False,
            )
        )

        print("\nMissing fields:", missing or "None")

        print("\n--- EMAIL REPLY PREVIEW (NOT SENT) ---")
        print(reply)
        print("--- END PREVIEW ---")

    else:

        # Unsupported intents cannot trigger database operations.
        print(
            "This preview does not execute intent:",
            plan.get("intent"),
        )

        print("No operational action was taken.")

    # Save the draft and mark the message PROCESSED together.
    # Both changes are committed in the thread store.
    store.complete_message(
        mailbox,
        conversation_id,
        mailbox,
        message_key,
        state,
    )


def main():
    """Read one controlled Outlook thread and process new messages."""

    # Check the environment variables established earlier.
    for key in (
        "OUTLOOK_CLIENT_ID",
        "FOUNDRY_PROJECT_ENDPOINT",
        "OUTLOOK_TEST_RECIPIENT",
    ):

        if not os.getenv(key):
            raise RuntimeError(
                f"Missing environment variable: {key}"
            )

    # Reuse the existing Outlook authentication function.
    token = authenticate()

    mailbox = test_mailbox(token)

    # Locate the specifically labeled test conversation.
    messages = find_test_thread(token)

    if not messages:
        print(
            "No matching test thread found among "
            "the most recent Inbox messages."
        )
        print("Expected subject:", TEST_SUBJECT)
        return

    # Initialize the persistent email conversation store.
    store = EmailThreadStore()

    print(
        f"\nFound {len(messages)} email message(s) "
        "in the test conversation."
    )

    # Connect only to the existing Communication Agent.
    # The Operations Agent is deliberately not used here.
    with AIProjectClient(
        endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        credential=AzureCliCredential(),
    ) as project:

        with project.get_openai_client(
            agent_name="request-communication-agent"
        ) as comm:

            for item in messages:

                try:
                    process_message(
                        token,
                        mailbox,
                        item,
                        comm,
                        store,
                    )

                except Exception as error:

                    # A CLAIMED message requires review after an error.
                    # Never reset it automatically.
                    print(
                        f"Stopped: {type(error).__name__}: {error}"
                    )

                    print(
                        "If this message was CLAIMED, "
                        "inspect its state before retrying."
                    )

                    return

    print(
        "\nPreview completed. No outgoing email was sent "
        "and the request database was not modified."
    )


if __name__ == "__main__":
    main()
