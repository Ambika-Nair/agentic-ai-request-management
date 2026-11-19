import os

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential

## Get existing Foundry Project Endpoint
project_endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"]

## Use azure account that was logged into earlier
credential = AzureCliCredential()

## Connect to existing Foundry project
with AIProjectClient(
    endpoint=project_endpoint,
    credential=credential
) as project_client:

    print("Agents found in Microsoft Foundry: ")

    for agent in project_client.agents.list():
        print("-", agent.name)

    print("Connection test completed successfully!")