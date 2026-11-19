
import os
import json

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential

# Import the existing database functions.
from database import get_request, update_request


# Retrieve the Foundry project endpoint.
PROJECT_ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]

# Identify the existing Operations Agent.
AGENT_NAME = "request-operations-agent"

# Define the fictional request used for testing.
TEST_REQUEST_ID = "REQ-16D05137784242119874173392E2B301"

# Define the approved modification.
NEW_PRIORITY = "High"

# Identify the expected owner of the fictional test record.
EXPECTED_EMAIL = "taylor@example.com"


# Retrieve the request before modification.
existing_request = get_request(TEST_REQUEST_ID)

# Stop if the request does not exist.
if "error" in existing_request:
    raise RuntimeError(existing_request["error"])

# Confirm that the expected fictional record was retrieved.
if existing_request["requester_email"] != EXPECTED_EMAIL:
    raise RuntimeError("Unexpected request owner. Test stopped.")

# Prevent changes to requests in terminal lifecycle states.
if existing_request["status"] != "Submitted":
    raise RuntimeError(
        "The request is not in the expected Submitted state."
    )

# Prevent repeated execution after a successful update.
if existing_request["priority"] == NEW_PRIORITY:
    print("Request already has the target priority.")
    raise SystemExit(0)

# Display the existing priority.
print("Current priority:", existing_request["priority"])

# Require explicit approval before modifying the database.
confirmation = input(
    "Type UPDATE to approve this fictional priority change: "
)

if confirmation != "UPDATE":
    print("Test cancelled. No changes made.")
    raise SystemExit(0)


# Define the exact arguments approved for the function call.
approved_arguments = {
    "request_id": TEST_REQUEST_ID,
    "title": None,
    "description": None,
    "priority": NEW_PRIORITY
}


# Connect to the existing Microsoft Foundry project.
with AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=AzureCliCredential()
) as project:

    # Obtain the client for the existing Operations Agent.
    with project.get_openai_client(
        agent_name=AGENT_NAME
    ) as client:

        # Request the approved modification through the agent.
        response = client.responses.create(
            input=(
                "An approved integration test must update the "
                "priority of an existing fictional request. "
                "Call update_request exactly once with these "
                f"arguments: {json.dumps(approved_arguments)}. "
                "Do not change any other fields."
            )
        )

        # Extract function calls requested by the agent.
        function_calls = [
            item for item in response.output
            if item.type == "function_call"
        ]

        # Require exactly one update function call.
        if (
            len(function_calls) != 1
            or function_calls[0].name != "update_request"
        ):
            print("Expected update function call not received.")
            print("Agent response:", response.output_text)
            raise SystemExit(1)

        call = function_calls[0]
        print("Requested function:", call.name)

        # Parse the arguments provided by the agent.
        arguments = json.loads(call.arguments)

        # Reject any unapproved changes to the arguments.
        if arguments != approved_arguments:
            print("Function arguments differ from approved values.")
            print("No changes made.")
            raise SystemExit(1)

        # Execute the actual Python update function.
        result = update_request(**arguments)

        print("Database update result:", result)

        # Stop if the database rejected the modification.
        if "error" in result:
            raise RuntimeError(result["error"])

        # Retrieve the request again to verify the stored values.
        updated_request = get_request(TEST_REQUEST_ID)

        print("Updated priority:", updated_request["priority"])
        print("Request status:", updated_request["status"])

        # Verify that only the approved change was applied.
        if (
            updated_request["priority"] != NEW_PRIORITY
            or updated_request["status"] != "Submitted"
            or updated_request["title"] != existing_request["title"]
            or updated_request["description"] != existing_request["description"]
        ):
            raise RuntimeError(
                "Database verification failed. Review the record."
            )

        # Return the actual operation result to the agent.
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

        # Display the final response from the Operations Agent.
        print("\nFinal Operations Agent response:")
        print(final_response.output_text)
