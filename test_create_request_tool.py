
import os
import json
import sqlite3

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential

# Import the existing SQLite functions and database path.
from database import (
    DATABASE_PATH,
    create_request_auto,
    get_request
)


# Retrieve the Foundry project endpoint.
PROJECT_ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]

# Identify the existing Operations Agent.
AGENT_NAME = "request-operations-agent"


# Define fictional request data for the integration test.
TEST_REQUEST = {
    "requester_name": "Taylor Example",
    "requester_email": "taylor@example.com",
    "title": "Foundry Tool Creation Test",
    "description": "Request access to Power BI Desktop for testing.",
    "request_type": "Software Access",
    "priority": "Medium"
}


# Check whether the test request already exists in SQLite.
# This prevents accidental duplicate creation on repeated runs.
with sqlite3.connect(DATABASE_PATH) as connection:
    existing = connection.execute(
        """
        SELECT request_id
        FROM requests
        WHERE requester_email = ?
          AND title = ?
        LIMIT 1
        """,
        (
            TEST_REQUEST["requester_email"],
            TEST_REQUEST["title"]
        )
    ).fetchone()

if existing:
    print("Test request already exists:", existing[0])
    raise SystemExit(0)


# Require explicit approval before performing a database insert.
confirmation = input(
    "Type CREATE(case-sensitive) to approve one fictional test request: "
)

if confirmation != "CREATE":
    print("Test cancelled. No request was created.")
    raise SystemExit(0)


# Connect to the existing Microsoft Foundry project.
with AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=AzureCliCredential()
) as project:

    # Obtain the client for the existing Operations Agent.
    with project.get_openai_client(
        agent_name=AGENT_NAME
    ) as client:

        # Send the confirmed fictional test request.
        response = client.responses.create(
            input=(
                "An explicitly approved integration test must create "
                "one fictional request using create_request_auto. "
                "Use exactly these details without modification: "
                f"{json.dumps(TEST_REQUEST)}. "
                "Do not invent a request ID."
            )
        )

        # Extract function calls requested by Foundry.
        function_calls = [
            item for item in response.output
            if item.type == "function_call"
        ]

        # Require exactly one request-creation function call.
        if (
            len(function_calls) != 1
            or function_calls[0].name != "create_request_auto"
        ):
            print("Expected creation function call was not received.")
            print("Agent response:", response.output_text)
            raise SystemExit(1)

        call = function_calls[0]

        print("Requested function:", call.name)

        # Parse the arguments provided by the agent.
        arguments = json.loads(call.arguments)

        # Reject modified, missing, or unexpected field values.
        # Only the explicitly approved fictional data is permitted.
        if arguments != TEST_REQUEST:
            print("Function arguments did not match approved data.")
            print("No request was created.")
            raise SystemExit(1)

        # Execute the registered function against local SQLite.
        result = create_request_auto(**arguments)

        print("Database creation result:", result)

        # Stop if backend validation or insertion failed.
        if not result.get("request_id"):
            print("Request creation was unsuccessful.")
            raise SystemExit(1)

        created_id = result["request_id"]

        # Retrieve the saved record to verify persistence.
        saved_request = get_request(created_id)

        print("\nVerified database record:")
        print(saved_request)

        # Return the actual backend result to the Foundry agent.
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

        # Display the response produced after the tool call.
        print("\nFinal Operations Agent response:")
        print(final_response.output_text)
