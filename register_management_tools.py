
import os

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    PromptAgentDefinition,
    FunctionTool
)
from azure.identity import AzureCliCredential


# Read the existing Microsoft Foundry project endpoint.
PROJECT_ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]

# Identify the existing Operations Agent.
AGENT_NAME = "request-operations-agent"


# Define a tool for modifying an existing request.
# Unchanged fields must be passed as null.
update_request_tool = FunctionTool(
    name="update_request",
    description=(
        "Modify the title, description, or priority of an existing "
        "request. Use only after the requested changes have been "
        "explicitly confirmed and authorized. The backend checks "
        "whether the request can be modified."
    ),
    parameters={
        "type": "object",
        "properties": {
            "request_id": {
                "type": "string",
                "description": "Unique ID of the existing request."
            },
            "title": {
                "type": ["string", "null"],
                "description": (
                    "Updated request title, or null if unchanged."
                )
            },
            "description": {
                "type": ["string", "null"],
                "description": (
                    "Updated description, or null if unchanged."
                )
            },
            "priority": {
                "type": ["string", "null"],
                "enum": [
                    "Low", "Medium", "High", "Critical", None
                ],
                "description": (
                    "Updated priority, or null if unchanged."
                )
            }
        },
        "required": [
            "request_id",
            "title",
            "description",
            "priority"
        ],
        "additionalProperties": False
    },
    strict=True
)


# Define a tool for cancelling an existing request.
cancel_request_tool = FunctionTool(
    name="cancel_request",
    description=(
        "Cancel an existing request by changing its status "
        "to Cancelled. Use only after explicit confirmation "
        "and authorization. The backend checks the request's "
        "current lifecycle state."
    ),
    parameters={
        "type": "object",
        "properties": {
            "request_id": {
                "type": "string",
                "description": "Unique ID of the request to cancel."
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

    # Retrieve all existing Operations Agent versions.
    versions = list(
        project.agents.list_versions(agent_name=AGENT_NAME)
    )

    # Identify the latest version.
    latest = max(
        versions,
        key=lambda version: int(version.version)
    )

    # Preserve tools already configured on the agent.
    existing_tools = list(latest.definition.tools or [])

    # Extract function names for duplicate checks.
    existing_names = {
        getattr(tool, "name", None)
        for tool in existing_tools
    }

    # Confirm that the previous two tools are available.
    required_tools = {
        "get_request",
        "create_request_auto"
    }

    if not required_tools.issubset(existing_names):
        raise RuntimeError(
            "Required existing tools are missing. "
            "No changes have been made."
        )

    # Prevent duplicate tool registrations.
    new_tool_names = {
        "update_request",
        "cancel_request"
    }

    if existing_names.intersection(new_tool_names):
        raise RuntimeError(
            "One or more management tools already exist. "
            "No changes have been made."
        )

    # Append both management tools to the existing tools.
    updated_tools = existing_tools + [
        update_request_tool,
        cancel_request_tool
    ]

    # Preserve the model and saved agent instructions.
    updated_definition = PromptAgentDefinition(
        model=latest.definition.model,
        instructions=latest.definition.instructions,
        tools=updated_tools
    )

    # Create a new version of the existing agent.
    updated_agent = project.agents.create_version(
        agent_name=AGENT_NAME,
        definition=updated_definition
    )

    # Display the updated agent configuration.
    print("Agent:", updated_agent.name)
    print("New version:", updated_agent.version)
    print("Model:", updated_agent.definition.model)

    print("\nConfigured tools:")

    for tool in updated_agent.definition.tools:
        print("-", getattr(tool, "name", "Unknown tool"))

    print("\nTool registration completed successfully.")
