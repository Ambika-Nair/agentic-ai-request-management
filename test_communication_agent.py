
import os

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential


# Load the existing Microsoft Foundry project endpoint.
PROJECT_ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]

# Identify the existing Communication Agent.
AGENT_NAME = "request-communication-agent"

# Define a fictional user message for intent identification.
# No database operations should be performed during this test.
USER_MESSAGE = (
    "Can you check the status of request REQ-A15FFE97?"
)


# Connect to the existing Microsoft Foundry project.
with AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=AzureCliCredential()
) as project:

    # Obtain a client for the existing Communication Agent.
    with project.get_openai_client(
        agent_name=AGENT_NAME
    ) as client:

        # Test message understanding without invoking database tools.
        response = client.responses.create(
            input=(
                f"User message: {USER_MESSAGE}\n\n"
                "Identify the user's intent and request ID. "
                "Do not claim that the database was accessed "
                "or that the request status was retrieved."
            )
        )

        # Display the Communication Agent's response.
        print("Communication Agent response:")
        print(response.output_text)
