
"""Execute one confirmed email request through the existing Operations Agent.

The script checks authorization, duplicates, and the execution ledger
before creating an IT request. Automatic retries are disabled.
"""

import os
import sys
import json
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential

# Allow imports from the main project folder.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from email_create_preflight import (
    validate_confirmation,
    verify_live_authorization,
    verify_saved_draft,
    duplicate_matches,
)
from email_approval_store import EmailApprovalStore
from email_create_execution_store import EmailCreateExecutionStore
from outlook_connect import authenticate
# from chat_prototype import call_ops_tool
from database import create_request_auto, get_request


def call_ops_tool(ops_client, tool_name, approved_args, executor):
    """Invoke the existing Operations Agent and execute its validated tool."""

    # Ask the Operations Agent to select exactly the approved function.
    response = ops_client.responses.create(
        input=(
            "Use the registered function tool exactly once. "
            "Do not change the supplied arguments.\n"
            f"Function: {tool_name}\n"
            f"Arguments: {json.dumps(approved_args)}"
        )
    )

    # Require exactly one matching function call.
    calls = [
        item for item in response.output
        if item.type == "function_call"
    ]

    if len(calls) != 1 or calls[0].name != tool_name:
        raise RuntimeError("Unexpected Operations Agent tool call.")

    call = calls[0]

    # Refuse any changes to the confirmed request details.
    arguments = json.loads(call.arguments)

    if not isinstance(arguments, dict) or arguments != approved_args:
        raise RuntimeError("Operations Agent changed approved arguments.")

    # Execute the existing SQLite function exactly once.
    result = executor(**approved_args)

    # Return the actual database result to the Operations Agent.
    # Any failure after execution is treated as an uncertain outcome
    # by the surrounding execution ledger.
    ops_client.responses.create(
        input=[{
            "type": "function_call_output",
            "call_id": call.call_id,
            "output": json.dumps(result),
        }],
        previous_response_id=response.id,
    )

    return result


def main():
    """Validate and execute exactly one confirmed CREATE request."""

    proposal_id = os.environ["OUTLOOK_CONFIRMATION_PROPOSAL_ID"]
    endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"]

    approvals = EmailApprovalStore()
    executions = EmailCreateExecutionStore()

    # Refuse repeated execution, including attempts interrupted earlier.
    if executions.get(proposal_id):
        raise RuntimeError("This proposal already has an execution attempt.")

    # Validate the frozen confirmation and actual Outlook identity.
    proposal = approvals.get(proposal_id)
    validate_confirmation(proposal)

    token = authenticate()
    mailbox = verify_live_authorization(token, proposal)
    draft = verify_saved_draft(token, mailbox, proposal["draft"])

    # Validate all fields before passing arguments to the Operations Agent.
    required = (
        "requester_name", "requester_email", "title",
        "description", "request_type", "priority"
    )

    if set(draft) != set(required):
        raise RuntimeError("Unexpected or missing CREATE fields.")

    if any(
        not isinstance(draft[key], str)
        or (key != "description" and not draft[key].strip())
        for key in required
    ):
        raise RuntimeError("The confirmed request contains invalid fields.")

    if draft["priority"] not in ("Low", "Medium", "High", "Critical"):
        raise RuntimeError("Invalid priority.")

    print("\nConfirmed request:")
    print(json.dumps(draft, indent=2))

    # Require explicit local approval before a database write.
    decision = input("\nType CREATE to submit this request: ").strip()

    if decision != "CREATE":
        print("Cancelled. No request was created.")
        return

    with AIProjectClient(
        endpoint=endpoint,
        credential=AzureCliCredential()
    ) as project:

        with (
            project.get_openai_client(
                agent_name="request-communication-agent"
            ) as comm,
            project.get_openai_client(
                agent_name="request-operations-agent"
            ) as ops,
        ):

            # Refuse expired or modified confirmations.
            latest = approvals.get(proposal_id)
            validate_confirmation(latest)

            if latest["draft"] != draft:
                raise RuntimeError("The confirmed proposal changed.")

            # Recheck duplicates immediately before execution.
            matches = duplicate_matches(draft, comm, ops)

            if not isinstance(matches, list) or matches:
                raise RuntimeError(
                    "Duplicate screening failed or found potential duplicates."
                )

            # Persist the single permitted execution attempt.
            attempt_id = executions.claim_for_create(proposal_id)

            try:
                # Invoke the existing Operations Agent and its registered tool.
                result = call_ops_tool(
                    ops,
                    "create_request_auto",
                    draft,
                    create_request_auto,
                )

                if not isinstance(result, dict):
                    raise RuntimeError("Invalid CREATE result.")

                request_id = result.get("request_id")

                if not isinstance(request_id, str) or not request_id:
                    raise RuntimeError("No created request ID returned.")

                # Read SQLite again and verify the actual saved values.
                record = get_request(request_id)

                if not isinstance(record, dict) or record.get("error"):
                    raise RuntimeError("Created request could not be verified.")

                if record.get("request_id") != request_id:
                    raise RuntimeError("Request ID verification failed.")

                for key in required:
                    actual = record.get(key)
                    expected = draft[key]

                    if key == "requester_email":
                        valid = (
                            isinstance(actual, str)
                            and actual.strip().casefold()
                            == expected.strip().casefold()
                        )
                    else:
                        valid = actual == expected

                    if not valid:
                        raise RuntimeError(
                            f"Saved request differs from confirmation: {key}"
                        )

                if not isinstance(record.get("status"), str) or not record["status"]:
                    raise RuntimeError("Saved request has no valid status.")

            except Exception as error:
                # An uncertain write must never be retried automatically.
                try:
                    executions.mark_needs_review(
                        proposal_id,
                        attempt_id,
                        "CREATE result requires manual verification"
                    )
                except Exception:
                    # CLAIMED also prevents another automatic attempt.
                    pass

                raise RuntimeError(
                    "CREATE outcome uncertain. Check the database and ledger. "
                    "Do not run CREATE again for this proposal."
                ) from error

            # A ledger failure leaves the claim in place; do not retry CREATE.
            executions.mark_created(
                proposal_id,
                attempt_id,
                request_id
            )

            print("\nSUCCESS: IT request created and verified.")
            print("Request ID:", request_id)
            print("Status:", record["status"])
            print("Title:", record["title"])
            print("Execution ledger: CREATED")


if __name__ == "__main__":
    main()
