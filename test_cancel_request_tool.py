
import os
import json

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential

# Import the existing SQLite functions.
from database import get_request, cancel_request


# Load the Foundry project endpoint.
PROJECT_ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]

# Identify the existing Operations Agent.
AGENT_NAME = "request-operations-agent"

# Define the fictional request used for testing.
TEST_REQUEST_ID = "REQ-16D05137784242119874173392E2B301"

# Define the expected fictional requester.
EXPECTED_EMAIL = "taylor@example.com"


# Retrieve the request before cancellation.
existing_request = get_request(TEST_REQUEST_ID)

# Stop if the request does not exist.
if "error" in existing_request:
    raise RuntimeError(existing_request["error"])

# Verify that the correct fictional test record was retrieved.
if (
    existing_request["requester_email"] != EXPECTED_EMAIL
    or existing_request["title"] != "Foundry Tool Creation Test"
):
    raise RuntimeError("Unexpected test record. Operation stopped.")

# Prevent repeated cancellation after a successful test.
if existing_request["status"] == "Cancelled":
    print("Test request is already cancelled.")
    raise SystemExit(0)

# Allow this test only for a submitted request.
if existing_request["status"] != "Submitted":
    raise RuntimeError("Unexpected request lifecycle status.")

# Display the current request details.
print("Request ID:", TEST_REQUEST_ID)
print("Current status:", existing_request["status"])

# Require explicit approval before cancellation.
confirmation = input(
    "Type CANCEL to approve cancellation of this fictional request: "
)

if confirmation != "CANCEL":
    print("Test stopped. No changes made.")
    raise SystemExit(0)


# Define the exact arguments approved for cancellation.
approved_arguments = {
    "request_id": TEST_REQUEST_ID
}


# Connect to the existing Foundry project.
with AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=AzureCliCredential()
) as project:

    # Access the registered Operations Agent.
    with project.get_openai_client(
        agent_name=AGENT_NAME
    ) as client:

        # Ask the agent to select the cancellation function.
        response = client.responses.create(
            input=(
                "An explicitly approved integration test requires "
                "cancelling one fictional request. "
                "Call cancel_request exactly once with these "
                f"arguments: {json.dumps(approved_arguments)}. "
                "Do not request any other operation."
            )
        )

        # Extract function calls returned by the agent.
        function_calls = [
            item for item in response.output
            if item.type == "function_call"
        ]

        # Require exactly one cancellation function call.
        if (
            len(function_calls) != 1
            or function_calls[0].name != "cancel_request"
        ):
            print("Expected cancellation function call not received.")
            print("Agent response:", response.output_text)
            raise SystemExit(1)

        # Retrieve the function name and arguments.
        call = function_calls[0]
        arguments = json.loads(call.arguments)

        print("Requested function:", call.name)

        # Reject arguments that differ from approved values.
        if arguments != approved_arguments:
            print("Function arguments did not match approved values.")
            print("No changes made.")
            raise SystemExit(1)

        # Execute cancellation against the local SQLite database.
        result = cancel_request(**arguments)

        print("Database cancellation result:", result)

        # Confirm that the backend reported successful cancellation.
        if (
            result.get("request_id") != TEST_REQUEST_ID
            or result.get("status") != "Cancelled"
        ):
            raise RuntimeError(
                "Cancellation was not confirmed by the backend."
            )

        # Retrieve the record to verify the persisted lifecycle status.
        cancelled_request = get_request(TEST_REQUEST_ID)

        print("Verified database status:", cancelled_request["status"])

        # Confirm that the record was cancelled without deletion.
        if (
            cancelled_request["status"] != "Cancelled"
            or cancelled_request["priority"] != existing_request["priority"]
            or cancelled_request["title"] != existing_request["title"]
        ):
            raise RuntimeError(
                "Database verification failed. Review the record."
            )

        # Return the confirmed backend result to the agent.
        final_response = client.responses.create(
            input=[
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(result)
                }
            ],
            previous_response_id=response.id
        )

        # Display the final agent response.
        print("\nFinal Operations Agent response:")
        print(final_response.output_text)
