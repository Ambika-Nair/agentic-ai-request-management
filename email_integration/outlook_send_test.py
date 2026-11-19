
"""Send one controlled test email using Microsoft Graph.

Purpose:
- Authenticate the existing personal Outlook account.
- Request delegated Mail.Send permission.
- Verify that the recipient is the signed-in mailbox.
- Display the exact message before sending.
- Require explicit terminal confirmation.

Safety:
- Only sends to the authenticated mailbox.
- Does not process incoming request emails.
- Does not invoke Foundry agents.
- Does not modify SQLite.
- Never automatically retries a send attempt.
"""

import os

import msal
import requests

from outlook_connect import (
    AUTHORITY,
    GRAPH_BASE_URL,
    get_account_info,
)


# Only permissions needed for identifying the account
# and sending this test message are requested.
SCOPES = [
    "User.Read",
    "Mail.Send",
]


def authenticate_for_sending():
    """Get a delegated Microsoft Graph access token.

    The existing Entra application registration is reused.
    No client secret or mailbox password is stored in Python.
    """

    # Read the registered application's public client ID
    # from the current CMD environment.
    client_id = os.getenv("OUTLOOK_CLIENT_ID")

    if not client_id:
        raise RuntimeError(
            "OUTLOOK_CLIENT_ID is not configured."
        )

    # Personal Microsoft accounts use the consumers authority.
    app = msal.PublicClientApplication(
        client_id=client_id,
        authority=AUTHORITY,
    )

    print("Opening Microsoft sign-in...")

    # Interactive login requests permission to send email.
    # Microsoft may display an additional consent screen.
    result = app.acquire_token_interactive(
        scopes=SCOPES,
    )

    if "access_token" not in result:
        raise RuntimeError(
            "Authentication failed: "
            + str(result.get("error", "unknown error"))
        )

    print("Microsoft authentication succeeded.")

    return result["access_token"]


def get_verified_recipient(token):
    """Restrict test delivery to the authenticated Outlook mailbox.

    The application must not send test emails to arbitrary
    recipients before the email workflow has been validated.
    """

    # Retrieve signed-in account details directly from Graph.
    account = get_account_info(token)

    # Some Microsoft accounts use userPrincipalName when
    # the mail property is unavailable.
    account_addresses = [
        address.strip().casefold()
        for address in (
            account.get("mail"),
            account.get("userPrincipalName"),
        )
        if isinstance(address, str) and address.strip()
    ]

    # The expected recipient must be configured by the tester.
    expected_recipient = (
        os.getenv("OUTLOOK_TEST_RECIPIENT") or ""
    ).strip().casefold()

    if not expected_recipient:
        raise RuntimeError(
            "OUTLOOK_TEST_RECIPIENT is not configured."
        )

    # Prevent accidental sending from an unexpected account.
    if expected_recipient not in account_addresses:
        raise RuntimeError(
            "The configured test recipient does not match "
            "the authenticated Microsoft account."
        )

    return expected_recipient


def send_test_email(token, recipient):
    """Send one plain-text email after explicit confirmation."""

    # This fixed diagnostic message tests Graph delivery only.
    # The Communication Agent will generate message content
    # in the next integration stage.
    subject = "[ERM-TEST] Outlook sending connectivity"

    body = (
        "Hello,\n\n"
        "This is a controlled email delivery test for the "
        "Agentic AI Enterprise Request Management project.\n\n"
        "The message was sent through Microsoft Graph "
        "using delegated Outlook permissions.\n\n"
        "No IT request was created, updated, or cancelled.\n"
        "No SQLite database operation was performed.\n\n"
        "Request Management Test"
    )

    # Construct a Graph sendMail request using the
    # signed-in Outlook account as the sender.
    payload = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "Text",
                "content": body,
            },
            "toRecipients": [
                {
                    "emailAddress": {
                        "address": recipient,
                    }
                }
            ],
        },
        # Graph saves a copy to Sent Items by default.
        "saveToSentItems": True,
    }

    # Show the exact recipient and message before sending.
    print("\n--- OUTGOING EMAIL PREVIEW ---")
    print("To:", recipient)
    print("Subject:", subject)
    print()
    print(body)
    print("--- END PREVIEW ---")

    print(
        "\nThis action will send one real email "
        "to your own Outlook mailbox."
    )

    # A deliberate confirmation prevents accidental sending.
    confirmation = input(
        "Type SEND to continue, or anything else to cancel: "
    ).strip()

    if confirmation != "SEND":
        print("Sending cancelled. No email was sent.")
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Microsoft Graph executes the send request.
    # Never retry automatically after a timeout or unknown error,
    # since the message could already have been accepted.
    try:
        response = requests.post(
            f"{GRAPH_BASE_URL}/me/sendMail",
            headers=headers,
            json=payload,
            timeout=30,
        )
    except requests.RequestException as error:
        print(
            "The send outcome is uncertain. "
            "Check Outlook Sent Items before attempting again."
        )
        print("Technical error:", type(error).__name__)
        return

    # HTTP 202 means Graph accepted the request for processing.
    # Actual delivery must still be checked in Outlook.
    if response.status_code == 202:
        print("\nMicrosoft Graph accepted the send request.")
        print("HTTP status: 202 Accepted")
        print(
            "Check Outlook Sent Items and Inbox "
            "to verify delivery."
        )

    else:
        print("\nMicrosoft Graph did not accept the request.")
        print("HTTP status:", response.status_code)

        # Show a limited diagnostic without printing access tokens.
        print(
            "Error details:",
            response.text[:500],
        )


def main():
    """Authenticate, validate the mailbox, and run the test."""

    # Sign in through Microsoft's interactive browser flow.
    token = authenticate_for_sending()

    # Confirm that the configured destination is the
    # same mailbox that authenticated successfully.
    recipient = get_verified_recipient(token)

    # Send only after displaying the message and receiving SEND.
    send_test_email(token, recipient)


if __name__ == "__main__":
    main()
