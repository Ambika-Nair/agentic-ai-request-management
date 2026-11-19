
import os

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    PromptAgentDefinition,
    FunctionTool
)
from azure.identity import AzureCliCredential


# Read the existing Microsoft Foundry project endpoint.
PROJECT_ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]

# Identify the existing Request Operations Agent.
AGENT_NAME = "request-operations-agent"


# Define the function tool for creating a database request.
create_request_tool = FunctionTool(
    name="create_request_auto",
    description=(
        "Create a new request in the request-management database. "
        "Use only when all required request details are available "
        "and the user has confirmed that the request should be created. "
        "The backend generates the unique request ID."
    ),
    parameters={
        "type": "object",
        "properties": {
            "requester_name": {
                "type": "string",
                "description": "Name of the requester."
            },
            "requester_email": {
                "type": "string",
                "description": "Email address of the requester."
            },
            "title": {
                "type": "string",
                "description": "Short title of the request."
            },
            "description": {
                "type": "string",
                "description": "Detailed description of the request."
            },
            "request_type": {
                "type": "string",
                "description": "Category of the request."
            },
            "priority": {
                "type": "string",
                "enum": ["Low", "Medium", "High", "Critical"],
                "description": "Priority assigned to the request."
            }
        },
        "required": [
            "requester_name",
            "requester_email",
            "title",
            "description",
            "request_type",
            "priority"
        ],
        "additionalProperties": False
    },
    strict=True
)


# Connect to the existing Foundry project.
with AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=AzureCliCredential()
) as project:

    # Retrieve all versions of the Operations Agent.
    versions = list(
        project.agents.list_versions(agent_name=AGENT_NAME)
    )

    # Identify the latest agent version.
    latest = max(
        versions,
        key=lambda version: int(version.version)
    )

    # Retrieve the existing tools from the latest version.
    existing_tools = list(latest.definition.tools or [])

    # Extract existing function tool names.
    existing_names = {
        getattr(tool, "name", None)
        for tool in existing_tools
    }

    # Prevent registration if the required lookup tool is missing.
    if "get_request" not in existing_names:
        raise RuntimeError(
            "The get_request tool was not found. "
            "No changes have been made."
        )

    # Prevent duplicate registration of the creation tool.
    if "create_request_auto" in existing_names:
        raise RuntimeError(
            "The create_request_auto tool already exists. "
            "No changes have been made."
        )

    # Preserve existing tools and append the new function tool.
    updated_tools = existing_tools + [create_request_tool]

    # Preserve the existing model and agent instructions.
    updated_definition = PromptAgentDefinition(
        model=latest.definition.model,
        instructions=latest.definition.instructions,
        tools=updated_tools
    )

    # Create a new version of the existing Operations Agent.
    updated_agent = project.agents.create_version(
        agent_name=AGENT_NAME,
        definition=updated_definition
    )

    # Display the resulting agent configuration.
    print("Agent:", updated_agent.name)
    print("New version:", updated_agent.version)
    print("Model:", updated_agent.definition.model)
    print("Configured tools:")

    # Print each registered tool for verification.
    for tool in updated_agent.definition.tools:
        print("-", getattr(tool, "name", "Unknown tool"))
