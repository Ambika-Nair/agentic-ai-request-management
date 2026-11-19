
"""Add the request-listing function to the existing Foundry agent."""

import os

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    FunctionTool,
    PromptAgentDefinition
)
from azure.identity import AzureCliCredential


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

PROJECT_ENDPOINT = os.getenv("FOUNDRY_PROJECT_ENDPOINT")

AGENT_NAME = "request-operations-agent"

NEW_TOOL_NAME = "list_requests_by_email"

REQUIRED_EXISTING_TOOLS = {
    "get_request",
    "create_request_auto",
    "update_request",
    "cancel_request"
}


# --------------------------------------------------
# NEW FUNCTION DEFINITION
# --------------------------------------------------

def build_list_tool():
    """Define the read-only request-listing tool."""

    return FunctionTool(
        name=NEW_TOOL_NAME,
        description=(
            "List requests associated with a requester email address. "
            "Can return active requests, complete request history, "
            "or requests filtered by priority."
        ),
        parameters={
            "type": "object",
            "properties": {
                "requester_email": {
                    "type": "string",
                    "description": (
                        "Email address associated with the requests."
                    )
                },
                "open_only": {
                    "type": "boolean",
                    "description": (
                        "True for active requests only. "
                        "False to include cancelled, completed, "
                        "and rejected requests."
                    )
                },
                "priority": {
                    "type": "string",
                    "enum": [
                        "Low",
                        "Medium",
                        "High",
                        "Critical"
                    ],
                    "description": (
                        "Optional priority filter."
                    )
                }
            },
            "required": [
                "requester_email",
                "open_only"
            ],
            "additionalProperties": False
        },
        strict=False
    )


# --------------------------------------------------
# PRESERVE EXISTING AGENT CONFIGURATION
# --------------------------------------------------

def build_updated_definition(existing_definition, new_tool):
    """Construct a typed prompt-agent definition with all existing tools."""

    # Preserve the model, instructions, and registered tools.
    configuration = {
        "model": existing_definition.model,
        "instructions": existing_definition.instructions,
        "tools": list(existing_definition.tools or []) + [new_tool]
    }

    # Preserve optional settings already present on the agent.
    optional_settings = [
        "temperature",
        "top_p",
        "reasoning",
        "tool_choice",
        "text",
        "structured_inputs",
        "rai_config",
        "harness",
        "skills"
    ]

    for setting in optional_settings:

        value = getattr(
            existing_definition,
            setting,
            None
        )

        if value is not None:
            configuration[setting] = value

    # Create a NEW typed object instead of using the generic copy method.
    # PromptAgentDefinition supplies the required kind="prompt" field.
    return PromptAgentDefinition(**configuration)


# --------------------------------------------------
# AGENT REGISTRATION
# --------------------------------------------------

def main():
    """Add the fifth function without replacing existing tools."""

    if not PROJECT_ENDPOINT:
        print(
            "ERROR: FOUNDRY_PROJECT_ENDPOINT is missing."
        )
        return

    with AIProjectClient(
        endpoint=PROJECT_ENDPOINT,
        credential=AzureCliCredential()
    ) as project:

        # Retrieve the available versions of the existing agent.
        versions = list(
            project.agents.list_versions(
                agent_name=AGENT_NAME
            )
        )

        numeric_versions = [
            version
            for version in versions
            if str(version.version).isdigit()
        ]

        if not numeric_versions:
            print(
                "ERROR: No numeric agent versions were found."
            )
            return

        latest = max(
            numeric_versions,
            key=lambda version: int(version.version)
        )

        print(f"Existing agent: {AGENT_NAME}")
        print(f"Existing version: {latest.version}")

        # Retrieve the complete configuration of that version.
        current = project.agents.get_version(
            agent_name=AGENT_NAME,
            agent_version=str(latest.version)
        )

        definition = current.definition

        if not isinstance(definition, PromptAgentDefinition):
            print(
                "ERROR: Existing definition is not a prompt agent."
            )
            return

        # Identify existing registered function names.
        existing_tools = list(definition.tools or [])

        existing_names = {
            tool.name
            for tool in existing_tools
            if getattr(tool, "name", None)
        }

        print(
            "Existing tools:",
            sorted(existing_names)
        )

        # Stop if a required existing function is missing.
        missing = REQUIRED_EXISTING_TOOLS - existing_names

        if missing:
            print(
                "ERROR: Required existing tools are missing:",
                sorted(missing)
            )
            print("No changes were made.")
            return

        # Avoid adding the listing tool twice.
        if NEW_TOOL_NAME in existing_names:
            print(
                "SUCCESS: The listing tool is already registered."
            )
            print("No new version is required.")
            return

        # Build a typed function definition.
        new_tool = build_list_tool()

        # Reconstruct the agent with the original configuration.
        updated_definition = build_updated_definition(
            definition,
            new_tool
        )

        # Check that the serialized payload contains the required kind.
        payload = updated_definition.as_dict()

        print(
            "New definition kind:",
            payload.get("kind")
        )

        if payload.get("kind") != "prompt":
            print(
                "ERROR: The prompt-agent kind was not serialized."
            )
            print("No changes were made.")
            return

        # Check that the full tool list is preserved.
        updated_names = {
            tool.name
            for tool in updated_definition.tools
            if getattr(tool, "name", None)
        }

        expected_names = existing_names | {NEW_TOOL_NAME}

        if updated_names != expected_names:
            print(
                "ERROR: Tool preservation check failed."
            )
            print("No changes were made.")
            return

        print(
            "Tools in proposed version:",
            sorted(updated_names)
        )

        # Publish one new version of the existing agent.
        updated = project.agents.create_version(
            agent_name=AGENT_NAME,
            definition=updated_definition
        )

        print()
        print("SUCCESS: New agent version created.")
        print(f"Agent: {updated.name}")
        print(f"Version: {updated.version}")

        # Retrieve the saved version and confirm the tools.
        verified = project.agents.get_version(
            agent_name=AGENT_NAME,
            agent_version=str(updated.version)
        )

        verified_names = {
            tool.name
            for tool in (verified.definition.tools or [])
            if getattr(tool, "name", None)
        }

        print(
            "Verified tools:",
            sorted(verified_names)
        )

        if expected_names.issubset(verified_names):
            print(
                "SUCCESS: All existing tools and the new "
                "listing tool are registered."
            )
        else:
            print(
                "WARNING: The saved tool list needs review."
            )


# --------------------------------------------------
# APPLICATION ENTRY POINT
# --------------------------------------------------

if __name__ == "__main__":
    main()
