
"""Read-only Outlook mailbox connectivity test using Microsoft Graph.

This module:
- Authenticates a personal Microsoft account using MSAL.
- Reads basic mailbox information.
- Retrieves the latest five inbox messages.
- Does not send, delete, or modify emails.
- Does not invoke Foundry agents or modify SQLite.
"""

import os

import msal
import requests


# Microsoft Graph configuration.
AUTHORITY = "https://login.microsoftonline.com/consumers"
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

# Request only the permissions required for reading emails.
SCOPES = [
    "User.Read",
    "Mail.Read",
]


def authenticate():
    """Authenticate the Outlook account through Microsoft's browser login."""

    client_id = os.getenv("OUTLOOK_CLIENT_ID")

    if not client_id:
        raise RuntimeError(
            "OUTLOOK_CLIENT_ID environment variable is missing."
        )

    # Public client applications use interactive authentication.
    # No client secret or mailbox password is stored in this script.
    app = msal.PublicClientApplication(
        client_id=client_id,
        authority=AUTHORITY,
    )

    print("Opening Microsoft sign-in in your browser...")

    result = app.acquire_token_interactive(
        scopes=SCOPES,
    )

    if "access_token" not in result:
        error_code = result.get("error", "unknown_error")
        raise RuntimeError(
            f"Microsoft authentication failed: {error_code}"
        )

    print("Microsoft authentication succeeded.")

    return result["access_token"]


def graph_get(access_token, endpoint, params=None):
    """Execute a read-only Microsoft Graph request."""

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    response = requests.get(
        f"{GRAPH_BASE_URL}{endpoint}",
        headers=headers,
        params=params,
        timeout=30,
    )

    # Stop rather than presenting incomplete or invalid results.
    response.raise_for_status()

    return response.json()


def get_account_info(access_token):
    """Retrieve basic information about the signed-in account."""

    return graph_get(
        access_token,
        "/me",
        params={
            "$select": "displayName,mail,userPrincipalName",
        },
    )


def get_recent_emails(access_token):
    """Fetch the latest five inbox messages without downloading full bodies."""

    response = graph_get(
        access_token,
        "/me/mailFolders/inbox/messages",
        params={
            "$top": 5,
            "$select": "id,subject,from,receivedDateTime,isRead",
            "$orderby": "receivedDateTime desc",
        },
    )

    return response.get("value", [])


def main():
    """Test a read-only connection to the user's personal Outlook mailbox."""

    access_token = authenticate()

    account = get_account_info(access_token)

    print("\nConnected Outlook account:")
    print(
        account.get("mail")
        or account.get("userPrincipalName")
        or "Account address unavailable"
    )

    messages = get_recent_emails(access_token)

    print("\nLatest inbox messages:")
    print("-" * 50)

    if not messages:
        print("Inbox contains no messages.")
        return

    for index, message in enumerate(messages, start=1):
        sender = (
            message.get("from", {})
            .get("emailAddress", {})
            .get("address", "Unknown")
        )

        subject = message.get("subject") or "(No subject)"
        received = message.get("receivedDateTime") or "Unknown"

        print(f"\nEmail {index}")
        print(f"From: {sender}")
        print(f"Subject: {subject}")
        print(f"Received: {received}")

    print("\nRead-only Outlook connectivity test completed.")
    print("No emails were sent or modified.")


if __name__ == "__main__":
    main()
