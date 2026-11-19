
import os

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential

project_endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"]

with AIProjectClient(
    endpoint=project_endpoint,
    credential=AzureCliCredential(),
    allow_preview=True
) as project_client:

    with project_client.get_openai_client(
        agent_name="request-operations-agent"
    ) as openai_client:

        response = openai_client.responses.create(
            input=(
                "Briefly explain your role in one sentence. "
                "Do not claim to have accessed a database or used tools."
            )
        )

        print("Operations Agent response:")
        print(response.output_text)
