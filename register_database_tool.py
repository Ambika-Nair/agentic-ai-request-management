
import os

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition, FunctionTool
from azure.identity import AzureCliCredential


# Retrieve the existing Foundry project endpoint.
PROJECT_ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]

# Identify the existing Operations Agent.
AGENT_NAME = "request-operations-agent"


# Define the database lookup tool and its required input.
get_request_tool = FunctionTool(
    name="get_request",
    description=(
        "Retrieve an existing request from the request-management "
        "database using its unique request ID."
    ),
    parameters={
        "type": "object",
        "properties": {
            "request_id": {
                "type": "string",
                "description": "Unique request ID, such as REQ-A15FFE97."
            }
        },
        "required": ["request_id"],
        "additionalProperties": False
    },
    strict=True
)


# Connect to the existing Microsoft Foundry project.
with AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=AzureCliCredential()
) as project:

    # Retrieve the agent's existing versions.
    versions = list(
        project.agents.list_versions(agent_name=AGENT_NAME)
    )

    # Identify the latest version.
    latest = max(versions, key=lambda version: int(version.version))

    # Prevent accidental duplicate registration.
    if latest.definition.tools:
        raise RuntimeError(
            "Latest agent version already has tools. "
            "Review its configuration before proceeding."
        )

    # Preserve the existing model and instructions.
    updated_definition = PromptAgentDefinition(
        model=latest.definition.model,
        instructions=latest.definition.instructions,
        tools=[get_request_tool]
    )

    # Create a new version with the database lookup tool.
    updated_agent = project.agents.create_version(
        agent_name=AGENT_NAME,
        definition=updated_definition
    )

    # Display the resulting configuration.
    print("Agent:", updated_agent.name)
    print("New version:", updated_agent.version)
    print("Model:", updated_agent.definition.model)
    print("Configured tools:", len(updated_agent.definition.tools))
    print("Database lookup tool registered successfully.")
