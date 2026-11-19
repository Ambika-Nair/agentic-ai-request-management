
import os
import json

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential


# Read the existing Microsoft Foundry project endpoint.
PROJECT_ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]

# Identify the existing Communication Agent.
AGENT_NAME = "request-communication-agent"

# Define the supported request-management intents.
VALID_INTENTS = {
    "CREATE_REQUEST",
    "MODIFY_REQUEST",
    "CANCEL_REQUEST",
    "CHECK_STATUS"
}


# Accept a fictional request message from the terminal.
user_message = input("Enter a request message: ").strip()

# Reject empty input before invoking the agent.
if not user_message:
    raise ValueError("A request message is required.")


# Connect to the existing Foundry project.
with AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=AzureCliCredential()
) as project:

    # Access the existing Communication Agent.
    with project.get_openai_client(
        agent_name=AGENT_NAME
    ) as client:

        # Request structured intent classification only.
        # No database tools are executed in this script.
        # response = client.responses.create(
        #     input=(
        #         "Classify the following request-management message.\n"
        #         f"User message: {user_message}\n\n"
        #         "Return ONLY a JSON object with these fields:\n"
        #         "- intent: CREATE_REQUEST, MODIFY_REQUEST, "
        #         "CANCEL_REQUEST, or CHECK_STATUS\n"
        #         "- request_id: the provided request ID, or null\n"
        #         "- details: an object containing explicitly provided "
        #         "request information\n"
        #         "- missing_information: a list of details needed "
        #         "to complete the requested operation\n\n"
        #         "Do not invent information, retrieve records, "
        #         "execute operations, or ask for confirmation. "
        #         "Use null for unknown values."
        #     )
        # )

    
# Request structured classification using the current backend schema.
# Policy-specific requirements must not be invented.
        response = client.responses.create(
            input=(
            "Classify the following request-management message.\n"
            f"User message: {user_message}\n\n"

            "Return ONLY a valid JSON object with these fields:\n"
            "- intent\n"
            "- request_id\n"
            "- details\n"
            "- missing_information\n\n"

            "Supported intents: CREATE_REQUEST, MODIFY_REQUEST, "
            "CANCEL_REQUEST, CHECK_STATUS.\n\n"

            "For CREATE_REQUEST, the current backend requires:\n"
            "- requester_name\n"
            "- requester_email\n"
            "- title\n"
            "- request_type\n\n"

            "Description is optional. Priority defaults to Medium "
            "if not explicitly provided.\n\n"

            "A title may be derived from information explicitly "
            "provided in the user's message. "
            "For example, a Power BI Desktop software access request "
            "may have the title 'Power BI Desktop access request'.\n\n"

            "List only genuinely missing fields required by the "
            "current backend to process the requested operation.\n"

            "Do not assume that device details, approvals, cost centres, "
            "start dates, or supporting documents are mandatory unless "
            "an applicable policy explicitly establishes that requirement.\n\n"

            "For MODIFY_REQUEST and CANCEL_REQUEST, require a request ID "
            "and the details of the requested action where applicable.\n"

            "For CHECK_STATUS, require a request ID.\n\n"

            "Do not invent user identity, database records, "
            "policy requirements, or request IDs.\n"

            "Do not execute database operations or ask for confirmation. "
            "Use null for unknown values."
        )
    )


        # Display the original structured response.
        print("\nCommunication Agent response:")
        print(response.output_text)

        # Parse the response as JSON.
        try:
            classification = json.loads(response.output_text)
        except json.JSONDecodeError:
            raise RuntimeError(
                "Communication Agent did not return valid JSON."
            )

        # Validate the intent against supported operations.
        intent = classification.get("intent")

        if intent not in VALID_INTENTS:
            raise RuntimeError(
                f"Unsupported or unexpected intent: {intent}"
            )

        # Display the validated intent.
        print("\nValidated intent:", intent)

        # Display the extracted request details.
        print("Extracted details:", classification.get("details"))

        # Display information still required.
        print(
            "Missing information:",
            classification.get("missing_information")
        )
