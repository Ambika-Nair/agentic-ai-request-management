
"""Run a live, read-only preflight for email-driven CREATE.

This script verifies:
- The exact proposal was confirmed and is still valid.
- The signed-in mailbox matches the requester's identity.
- The confirmation reply exists in Sent Items.
- The saved request draft matches its frozen proposal.
- No previous CREATE execution attempt exists.
- Fresh duplicate screening finds no potential duplicates.

The script does NOT claim an execution attempt, create an IT
request, modify requests.db, or send any Outlook message.
"""

import json
import os
import sys
import time

from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential


# Allow imports from the main request-management project.
# The existing agents and business logic remain unchanged.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# Reuse the existing Operations Agent duplicate-screening workflow.
from chat_prototype import duplicate_matches

# Reuse the existing confirmation and execution-ledger stores.
from email_approval_store import EmailApprovalStore
from email_create_execution_store import EmailCreateExecutionStore

# Reuse the existing deterministic demo authorization rules.
from email_authorization import (
    assess_demo_create_eligibility,
    verify_confirmation_in_sent_items,
)

# Reuse request completeness and field validation.
from email_operations_preview import load_reviewable_draft

# Reuse the mailbox identity check from earlier Outlook tests.
from email_thread_preview import test_mailbox

# Reuse Microsoft Graph authentication and account lookup.
from outlook_connect import (
    authenticate,
    get_account_info,
)


def validate_confirmation(proposal):
    """Check confirmation state and expiry before further processing."""

    # A missing or malformed proposal must never proceed.
    if not isinstance(proposal, dict):
        raise RuntimeError(
            "The confirmation proposal was not found."
        )

    # Only an explicitly confirmed proposal can be evaluated.
    if proposal.get("status") != (
        "CONFIRMED_PENDING_AUTHORIZATION"
    ):
        raise RuntimeError(
            "The proposal is not confirmed and awaiting authorization."
        )

    # Require evidence that a confirmation email was presented
    # and a specific subsequent reply was recorded.
    if (
        proposal.get("presented_at") is None
        or not proposal.get("reply_message_key")
    ):
        raise RuntimeError(
            "The proposal is missing confirmation evidence."
        )

    # Preserve the current conservative execution policy:
    # do not start execution after the stored deadline.
    expires_at = proposal.get("expires_at")

    if (
        not isinstance(expires_at, (int, float))
        or time.time() >= expires_at
    ):
        raise RuntimeError(
            "The proposal deadline has passed. "
            "A fresh confirmation is required."
        )

    # Ensure the frozen request details are available.
    if not isinstance(proposal.get("draft"), dict):
        raise RuntimeError(
            "The frozen request draft is invalid."
        )


def verify_live_authorization(token, proposal):
    """Evaluate the current account using Microsoft Graph evidence."""

    # Verify that the mailbox belongs to the signed-in account.
    # This also enforces the configured self-email test restriction.
    mailbox = test_mailbox(token)

    # Fetch identity information from the authenticated Graph session.
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
            "Microsoft Graph returned no authenticated account address."
        )

    # Verify the exact recorded confirmation reply in Sent Items.
    # The recipient email typed in the request body is not
    # sufficient evidence of authorization.
    reply_verified = verify_confirmation_in_sent_items(
        token,
        proposal,
    )

    # Reuse the existing self-service demo authorization policy.
    eligible, explanation = assess_demo_create_eligibility(
        proposal,
        account_addresses,
        reply_verified,
    )

    print("\nAuthorization result:")
    print("Confirmation reply verified:", reply_verified)
    print("Demo eligible:", eligible)
    print("Explanation:", explanation)

    # Failure must stop the workflow before invoking agents.
    if not eligible:
        raise RuntimeError(
            "Live authorization checks did not pass."
        )

    return mailbox


def verify_saved_draft(token, mailbox, frozen_draft):
    """Reject request changes made after confirmation."""

    # Load the completed draft using the same validation
    # already tested in the email Operations preview.
    saved_draft = load_reviewable_draft(
        token,
        mailbox,
    )

    # Any change to the draft requires a new confirmation.
    # The frozen proposal is the authoritative write candidate.
    if saved_draft != frozen_draft:
        raise RuntimeError(
            "The current email draft differs from "
            "the confirmed frozen proposal."
        )

    return saved_draft


def main():
    """Run all CREATE preflight checks without performing a write."""

    # Require the configuration used throughout the Outlook tests.
    for variable in (
        "OUTLOOK_CLIENT_ID",
        "OUTLOOK_TEST_RECIPIENT",
        "OUTLOOK_CONFIRMATION_PROPOSAL_ID",
        "FOUNDRY_PROJECT_ENDPOINT",
    ):
        if not os.getenv(variable):
            raise RuntimeError(
                f"Missing environment variable: {variable}"
            )

    proposal_id = os.environ[
        "OUTLOOK_CONFIRMATION_PROPOSAL_ID"
    ].strip()

    # Load the immutable confirmation record.
    approvals = EmailApprovalStore()
    proposal = approvals.get(proposal_id)

    print("\nChecking confirmed proposal...")

    validate_confirmation(proposal)

    print("Confirmation state and deadline: VALID")

    # Check whether any CREATE attempt has already been reserved.
    # The execution store may initialize its ledger table in
    # email_threads.db, but this preview does not claim an attempt.
    executions = EmailCreateExecutionStore()

    existing_attempt = executions.get(proposal_id)

    if existing_attempt is not None:
        raise RuntimeError(
            "A CREATE execution attempt already exists "
            f"with status {existing_attempt['status']}. "
            "A second attempt is blocked."
        )

    print("Previous CREATE execution attempts: NONE")

    # Authenticate through Microsoft Graph.
    print("\nOpening Microsoft sign-in...")

    token = authenticate()

    # Recheck authorization against the actual Outlook account.
    mailbox = verify_live_authorization(
        token,
        proposal,
    )

    # Verify that the mutable saved draft still matches
    # the exact request details the user confirmed.
    draft = verify_saved_draft(
        token,
        mailbox,
        proposal["draft"],
    )

    print("\nConfirmed CREATE request:")

    print(
        json.dumps(
            draft,
            indent=2,
            ensure_ascii=False,
        )
    )

    print("\nRunning fresh read-only duplicate screening...")

    # Connect to the existing Communication and Operations Agents.
    # No additional Foundry agent or parallel business logic
    # is introduced by this email adapter.
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

            # The existing function retrieves active records
            # through the Operations Agent and applies
            # semantic duplicate comparison.
            matches = duplicate_matches(
                draft,
                comm,
                ops,
            )

    # Invalid or unavailable duplicate-screening results
    # must block the workflow rather than be treated as clear.
    if not isinstance(matches, list):
        raise RuntimeError(
            "Duplicate screening returned an invalid result."
        )

    if matches:

        print("\nPREFLIGHT BLOCKED: Potential duplicates found.")

        for match in matches:
            print(
                "-",
                match.get("request_id"),
                match.get("title"),
            )

        print("No CREATE attempt was reserved.")
        return

    print(
        "Duplicate screening: No potential duplicates "
        "identified among the active records checked."
    )

    # All checks passed. This is a readiness result only.
    # There is deliberately no call to claim_for_create()
    # and no call to create_request_auto().
    print("\n" + "=" * 48)
    print("PREFLIGHT RESULT: READY FOR CONTROLLED CREATE")
    print("=" * 48)

    print("Proposal ID:", proposal_id)
    print("Requester:", draft["requester_email"])
    print("Request title:", draft["title"])
    print("Priority:", draft["priority"])

    print("\nNo execution attempt was claimed.")
    print("No Outlook email was sent.")
    print("No IT request was created or modified.")


if __name__ == "__main__":
    main()
