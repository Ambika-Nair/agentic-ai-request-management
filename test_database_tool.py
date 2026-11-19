
import os
import json

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential

# Import the existing database lookup function.
from database import get_request


# Load the project endpoint from the terminal environment.
PROJECT_ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]

# Identify the existing Foundry agent.
AGENT_NAME = "request-operations-agent"

# Use a fictional request already stored in SQLite.
TEST_REQUEST_ID = "REQ-DOESNOTEXIST"


# Establish an authenticated connection to Foundry.
with AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=AzureCliCredential()
) as project:

    # Create a client configured for the Operations Agent.
    with project.get_openai_client(
        agent_name=AGENT_NAME
    ) as client:

        # Ask the agent to retrieve the request using its tool.
        response = client.responses.create(
            input=(
                f"Retrieve request {TEST_REQUEST_ID} using "
                "the get_request tool. Report its actual status. "
                "Do not invent database information."
            )
        )

        # Collect function calls requested by the agent.
        function_calls = [
            item for item in response.output
            if item.type == "function_call"
        ]

        if not function_calls:
            print("No function call was requested.")
            print("Agent response:", response.output_text)

        else:
            tool_outputs = []

            # Execute each supported function call locally.
            for call in function_calls:

                print("Requested function:", call.name)

                # Reject unexpected function names.
                if call.name != "get_request":
                    raise RuntimeError(
                        f"Unsupported function: {call.name}"
                    )

                # Read the arguments supplied by the agent.
                arguments = json.loads(call.arguments)
                request_id = arguments.get("request_id")

                # Validate the required request ID.
                if not isinstance(request_id, str) or not request_id.strip():
                    result = {"error": "A valid request ID is required."}
                else:
                    # Retrieve the saved record from the local SQLite database.
                    result = get_request(request_id)

                print("Database result:", result)

                # Prepare the database result for the Foundry agent.
                tool_outputs.append({
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(result)
                })

            # Send the executed tool results back to the agent.
            final_response = client.responses.create(
                input=tool_outputs,
                previous_response_id=response.id
            )

            # Display the agent's final response.
            print("\nFinal Operations Agent response:")
            print(final_response.output_text)
