
import os
import json
import re

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential
from database import get_request


# Configure the existing Foundry project and agents.
PROJECT_ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
COMM_AGENT = "request-communication-agent"
OPS_AGENT = "request-operations-agent"

# # Define a fictional status inquiry for the integration test.
# USER_MESSAGE = "Check the status of request REQ-A15FFE97."


# Accept a status inquiry entered through the terminal.
# The current prototype supports read-only CHECK_STATUS requests only.
USER_MESSAGE = input(
    "Enter a request status inquiry: "
).strip()

# Reject empty messages before invoking either Foundry agent.
if not USER_MESSAGE:
    raise ValueError("A request message is required.")

# Display the message being processed.
print("\nProcessing request:", USER_MESSAGE)


# Connect to the existing Foundry project.
with AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=AzureCliCredential()
) as project:

    # STEP 1: Ask the Communication Agent to classify the request.
    with project.get_openai_client(
        agent_name=COMM_AGENT
    ) as comm_client:

        communication_response = comm_client.responses.create(
            input=(
                "Classify the following user message for a "
                "read-only integration test.\n"
                f"User message: {USER_MESSAGE}\n\n"
                "Return ONLY a JSON object containing exactly "
                "two fields: intent and request_id. "
                "Use CHECK_STATUS as the intent for a status inquiry. "
                "Do not retrieve data, ask for confirmation, "
                "or add explanatory text."
            )
        )

        # Display the proposed structured handoff.
        handoff_text = communication_response.output_text.strip()
        print("Communication Agent handoff:")
        print(handoff_text)

        # Reject malformed JSON instead of guessing the intent.
        try:
            handoff = json.loads(handoff_text)
        except json.JSONDecodeError:
            raise RuntimeError(
                "The Communication Agent did not return valid JSON."
            )

        # Validate the expected handoff fields.
        if (
            not isinstance(handoff, dict)
            or set(handoff) != {"intent", "request_id"}
            or handoff["intent"] != "CHECK_STATUS"
        ):
            raise RuntimeError("Unexpected handoff structure or intent.")

        # Extract the request ID from the original test message.
        # This independently checks the ID supplied by the agent.
        match = re.search(
            r"\bREQ-[A-Z0-9]+\b",
            USER_MESSAGE,
            re.IGNORECASE
        )

        if not match:
            raise RuntimeError("No request ID found in the test message.")

        expected_id = match.group(0).upper()

        if handoff["request_id"] != expected_id:
            raise RuntimeError("Handoff request ID mismatch.")

        print("\nHandoff validation passed.")

    # STEP 2: Send the validated handoff to the Operations Agent.
    with project.get_openai_client(
        agent_name=OPS_AGENT
    ) as ops_client:

        operations_response = ops_client.responses.create(
            input=(
                "Execute this validated read-only request using "
                "the registered get_request tool:\n"
                f"{json.dumps(handoff)}\n"
                "Do not request any other operation."
            )
        )

        # Collect function calls requested by the Operations Agent.
        function_calls = [
            item for item in operations_response.output
            if item.type == "function_call"
        ]

        # Require exactly one database lookup.
        if (
            len(function_calls) != 1
            or function_calls[0].name != "get_request"
        ):
            print("Operations response:", operations_response.output_text)
            raise RuntimeError("Expected get_request call not received.")

        call = function_calls[0]
        arguments = json.loads(call.arguments)

        # Reject unexpected or modified function arguments.
        if arguments != {"request_id": expected_id}:
            raise RuntimeError("Unexpected database lookup arguments.")

        print("\nOperations Agent called:", call.name)

        # STEP 3: Execute the real SQLite lookup.
        database_result = get_request(expected_id)

        # Limit the shared result to fields required for status lookup.
        if "error" in database_result:
            verified_result = {
                "outcome": "NOT_FOUND",
                "request_id": expected_id,
                "message": database_result["error"]
            }
        else:
            verified_result = {
                "outcome": "SUCCESS",
                "request_id": database_result["request_id"],
                "status": database_result["status"]
            }

        print("Verified SQLite result:", verified_result)

        # Return the real database result to the Operations Agent.
        operations_final = ops_client.responses.create(
            input=[
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(verified_result)
                }
            ],
            previous_response_id=operations_response.id
        )

        print("\nOperations Agent response:")
        print(operations_final.output_text)

    # STEP 4: Let the Communication Agent communicate the result.
    # Only verified status information is supplied to this agent.
    with project.get_openai_client(
        agent_name=COMM_AGENT
    ) as comm_client:

        final_response = comm_client.responses.create(
            input=(
                "The Operations Agent completed a read-only lookup. "
                "The following result was verified against the database:\n"
                f"{json.dumps(verified_result)}\n\n"
                "Communicate the result to the user in one or two "
                "clear sentences. Do not ask for confirmation, "
                "invent details, or claim that another lookup is needed."
            )
        )

        print("\nFinal Communication Agent response:")
        print(final_response.output_text)
