
"""Evaluate authorization eligibility for a confirmed Outlook CREATE request.

This module implements a restrictive, self-service DEMO policy.

Requirements:
- The confirmation must be saved and linked to a reply.
- The proposal must belong to the authenticated Outlook account.
- The requester must be the authenticated Outlook account.
- The confirmation reply must appear in that account's Sent Items.

This is a read-only diagnostic. Passing these checks does NOT
authorize production use or execute an Operations Agent function.
"""

import os

from email_approval_store import EmailApprovalStore
from email_agent_preview import graph_read
from outlook_connect import (
    authenticate,
    get_account_info,
)


# Limit the diagnostic search to recent sent messages.
# Missing evidence causes a denial, not an assumption of success.
MAX_SENT_MESSAGES = 100


def normalize_email(value):
    """Normalize an email address for consistent comparisons."""

    if not isinstance(value, str):
        return ""

    return value.strip().casefold()


def assess_demo_create_eligibility(
    proposal,
    authenticated_addresses,
    reply_verified_in_sent_items,
):
    """Evaluate the deterministic self-service demo rules.

    Returns:
        tuple: (eligible: bool, explanation: str)

    This function does not invoke agents or perform database writes.
    """

    # A missing or invalid proposal must never pass the guard.
    if not isinstance(proposal, dict):
        return False, "Confirmation proposal is missing or invalid."

    # The Communication Agent's confirmation must have been
    # recorded before authorization can be considered.
    if proposal.get("status") != (
        "CONFIRMED_PENDING_AUTHORIZATION"
    ):
        return False, (
            "The request does not have a recorded confirmation "
            "awaiting authorization."
        )

    # A confirmation must be associated with a specific
    # incoming reply message, not merely a conversation.
    if not proposal.get("reply_message_key"):
        return False, (
            "No verified confirmation reply is linked to the proposal."
        )

    # Validate the minimum stored identifiers.
    if not proposal.get("conversation_id"):
        return False, "The Outlook conversation identifier is missing."

    mailbox = normalize_email(proposal.get("mailbox"))
    sender = normalize_email(proposal.get("sender_email"))

    if not mailbox or not sender:
        return False, "Mailbox or sender identity is missing."

    # The stored sender must be the test mailbox.
    # Requests on behalf of another identity are not enabled.
    if sender != mailbox:
        return False, (
            "The confirmation sender differs from the mailbox."
        )

    # Compare the stored mailbox to actual signed-in account
    # addresses returned by Microsoft Graph.
    valid_accounts = {
        normalize_email(address)
        for address in authenticated_addresses
        if normalize_email(address)
    }

    if mailbox not in valid_accounts:
        return False, (
            "The proposal does not belong to "
            "the authenticated Microsoft account."
        )

    # Examine the immutable draft from the approval store.
    draft = proposal.get("draft")

    if not isinstance(draft, dict):
        return False, "The frozen request draft is invalid."

    requester = normalize_email(
        draft.get("requester_email")
    )

    if not requester:
        return False, "The draft has no requester email."

    # For the initial demo, only requests for the signed-in
    # account itself are eligible.
    #
    # A separate delegation mechanism would be required
    # to allow requests on another person's behalf.
    if requester != mailbox:
        return False, (
            "Requester identity does not match the "
            "authenticated Outlook mailbox. "
            "On-behalf-of submission is not enabled."
        )

    # The incoming From field alone is not sufficient.
    # For this controlled self-email demonstration, also require
    # a matching message in the signed-in account's Sent Items.
    if reply_verified_in_sent_items is not True:
        return False, (
            "The confirmation reply was not verified "
            "in the authenticated account's Sent Items."
        )

    # This is demo eligibility, NOT permission to perform
    # a database write. Additional execution-time controls
    # will be added in the next stage.
    return True, (
        "The confirmation meets the controlled self-service "
        "demo eligibility rules. No write has been authorized "
        "or executed."
    )


def verify_confirmation_in_sent_items(
    token,
    proposal,
):
    """Look for the exact confirmation reply in Outlook Sent Items."""

    # Only the reply recorded by EmailApprovalStore is relevant.
    expected_message = proposal.get("reply_message_key")
    expected_thread = proposal.get("conversation_id")
    expected_sender = normalize_email(
        proposal.get("sender_email")
    )

    if not all((
        expected_message,
        expected_thread,
        expected_sender,
    )):
        return False

    # Read metadata from the authenticated user's Sent Items.
    # Microsoft Graph returns messages in the mailbox associated
    # with the delegated access token.
    response = graph_read(
        token,
        "/me/mailFolders/sentitems/messages",
        params={
            "$top": MAX_SENT_MESSAGES,
            "$select": (
                "internetMessageId,conversationId,"
                "from,sentDateTime"
            ),
            "$orderby": "sentDateTime desc",
        },
    )

    messages = response.get("value")

    if not isinstance(messages, list):
        raise RuntimeError(
            "Invalid Sent Items response from Microsoft Graph."
        )

    # Require an exact message ID and Outlook conversation match.
    # A matching subject or quoted proposal ID is not enough.
    matches = [
        item
        for item in messages
        if (
            item.get("internetMessageId") == expected_message
            and item.get("conversationId") == expected_thread
        )
    ]

    # Missing or duplicate evidence fails closed.
    if len(matches) != 1:
        return False

    # Confirm the sent message originated from the test mailbox.
    sent_from = normalize_email(
        (
            (matches[0].get("from") or {})
            .get("emailAddress") or {}
        ).get("address")
    )

    return sent_from == expected_sender


def main():
    """Inspect the current confirmation without executing a request."""

    proposal_id = (
        os.getenv("OUTLOOK_CONFIRMATION_PROPOSAL_ID") or ""
    ).strip()

    if not proposal_id:
        raise RuntimeError(
            "OUTLOOK_CONFIRMATION_PROPOSAL_ID is missing."
        )

    # Load the frozen proposal from the existing SQLite store.
    # This is independent of requests.db.
    proposal = EmailApprovalStore().get(proposal_id)

    if not proposal:
        raise RuntimeError(
            "The confirmation proposal could not be found."
        )

    print("\nProposal:", proposal_id)
    print("Confirmation status:", proposal["status"])

    # No further checks are needed if the confirmation
    # is not in the expected state.
    if proposal["status"] != (
        "CONFIRMED_PENDING_AUTHORIZATION"
    ):
        print(
            "BLOCKED: The proposal is not ready "
            "for authorization evaluation."
        )
        return

    print("\nOpening Microsoft sign-in...")

    # Use the existing MSAL authentication flow.
    token = authenticate()

    # Retrieve the authenticated identity directly from Graph.
    account = get_account_info(token)

    account_addresses = [
        value
        for value in (
            account.get("mail"),
            account.get("userPrincipalName"),
        )
        if isinstance(value, str) and value.strip()
    ]

    if not account_addresses:
        raise RuntimeError(
            "Microsoft Graph returned no usable account identity."
        )

    # Independently check whether the confirmed reply was sent
    # by the same authenticated mailbox in this test.
    reply_verified = verify_confirmation_in_sent_items(
        token,
        proposal,
    )

    # Evaluate the restricted demo authorization policy.
    eligible, reason = assess_demo_create_eligibility(
        proposal,
        account_addresses,
        reply_verified,
    )

    print("\n--- AUTHORIZATION DIAGNOSTIC ---")
    print(
        "Requester:",
        proposal["draft"].get("requester_email"),
    )
    print(
        "Authenticated account:",
        account_addresses[0],
    )
    print(
        "Confirmation reply found in Sent Items:",
        reply_verified,
    )

    print(
        "Result:",
        "DEMO-ELIGIBLE" if eligible else "BLOCKED",
    )
    print("Reason:", reason)
    print("--- END DIAGNOSTIC ---")

    # Important: no action is performed, even if eligible.
    print(
        "\nREAD-ONLY: No Operations Agent tool was invoked. "
        "No IT request was created or modified."
    )


if __name__ == "__main__":
    main()
