
import os

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential

endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"]

with AIProjectClient(
    endpoint=endpoint,
    credential=AzureCliCredential()
) as project:

    versions = project.agents.list_versions(
        agent_name="request-operations-agent"
    )

    for version in versions:
        definition = version.definition

        print("Agent version:", version.version)
        print("Model:", getattr(definition, "model", "Unknown"))

        instructions = getattr(definition, "instructions", "") or ""
        print("Instructions length:", len(instructions))

        tools = getattr(definition, "tools", None) or []
        print("Number of configured tools:", len(tools))

        print("-------------------")
