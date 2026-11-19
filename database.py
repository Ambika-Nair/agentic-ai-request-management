import re
import sqlite3
from pathlib import Path

##Storing the database in the project folder.
DATABASE_PATH = Path(__file__).parent / "requests.db"


def create_database():
    """Creates the request database and its table if needed."""

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS requests (
                request_id TEXT PRIMARY KEY,
                requester_name TEXT NOT NULL,
                requester_email TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                request_type TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'Medium',
                status TEXT NOT NULL DEFAULT 'Submitted',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

    print(f"Database ready: {DATABASE_PATH}")


def create_request(request_id, requester_name, requester_email, title, description, request_type, priority="Medium"):
   
    """Saves a new request to the database.""" 

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("""
            INSERT INTO requests (request_id, requester_name, requester_email, title, description, request_type, priority)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (request_id, requester_name, requester_email, title, description, request_type, priority))


    return {"request_id": request_id, "status": "Submitted", "message": "Request created successfully."}



def get_request(request_id):
    """Retrieve a request by its ID."""

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row

        row = connection.execute(
            "SELECT * FROM requests WHERE request_id = ?", (request_id,)
        ).fetchone()

        if row is None:
            return {"error": f"No request found with ID {request_id}"}
        return dict(row)


def update_request(request_id, title = None, description = None, priority=None):
    """Update selected fields of an existing request."""

    ## Check whether the request exists
    existing_request = get_request(request_id)

    if "error" in existing_request:
        return existing_request

     # Prevent modifications to requests in terminal lifecycle states.
    # These requests cannot be changed through the normal update process.
    restricted_statuses = {"Cancelled", "Completed", "Rejected"}

    if existing_request["status"] in restricted_statuses:
        return {
            "outcome": "INVALID_STATE",
            "request_id": request_id,
            "error": (
                "Request cannot be modified because its current "
                f"status is {existing_request['status']}."
            )
        }

    ## Validate the priority value if provided
    allowed_priorities = ["Low", "Medium", "High", "Critical"]

    if priority is not None and priority not in allowed_priorities:
        return {"error": f"Invalid priority value."}

    ## Keep existing values for fields n0ot being changed
    new_title = title if title is not None else existing_request["title"]
    new_description = (description if description is not None else existing_request["description"])
    new_priority = (priority if priority is not None else existing_request["priority"])

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("""
            UPDATE requests
            SET title = ?, description = ?, priority = ?, updated_at = CURRENT_TIMESTAMP
            WHERE request_id = ?
        """, (new_title, new_description, new_priority, request_id))

    return {"request_id":request_id, "status": "Updated", "message":"Request updated successfully."}


def cancel_request(request_id):
    """Cancel an existing request without deleting its record."""

    existing_request = get_request(request_id)

    if "error" in existing_request:
        return existing_request

    # Prevent cancelling the same request twice
    if existing_request["status"] == "Cancelled":
        return {
            "request_id": request_id,
            "message": "This request is already cancelled."
        }

    # Prevent cancelling completed or rejected requests
    if existing_request["status"] in ["Completed", "Rejected"]:
        return {
            "error": "This request can no longer be cancelled."
        }

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("""
            UPDATE requests
            SET status = 'Cancelled',
                updated_at = CURRENT_TIMESTAMP
            WHERE request_id = ?
        """, (request_id,))

    return {
        "request_id": request_id,
        "status": "Cancelled",
        "message": "Request cancelled successfully."
    }

 
def create_request_auto(
    requester_name,
    requester_email,
    title,
    description,
    request_type,
    priority="Medium"
):
    """Validate request details and create a unique request ID."""

    import uuid

    # Define the allowed priority values.
    allowed_priorities = {"Low", "Medium", "High", "Critical"}

    # Validate required text fields.
    required_fields = {
        "requester_name": requester_name,
        "requester_email": requester_email,
        "title": title,
        "request_type": request_type
    }

    for field_name, value in required_fields.items():
        if not isinstance(value, str) or not value.strip():
            return {
                "outcome": "VALIDATION_ERROR",
                "error": f"{field_name} is required."
            }

    # Validate the optional description.
    if description is not None and not isinstance(description, str):
        return {
            "outcome": "VALIDATION_ERROR",
            "error": "Description must be text."
        }

    # Reject unsupported priority values.
    if priority not in allowed_priorities:
        return {
            "outcome": "VALIDATION_ERROR",
            "error": "Priority must be Low, Medium, High, or Critical."
        }

    # Check for an active request involving the same requester and resource.
    # A matching active request must not be submitted a second time.
    duplicate_matches = find_possible_duplicates(
        requester_email=requester_email,
        title=title,
        request_type=request_type
    )

    # Reject duplicate creation at the backend level.
    # This also protects callers that bypass the chat application.
    if duplicate_matches:
        return {
            "outcome": "DUPLICATE_REQUEST",
            "error": (
                "An active request for this resource already exists."
            ),
            "existing_requests": duplicate_matches
        }

    # Generate a unique request identifier.
    # The full UUID significantly reduces collision probability.
    request_id = "REQ-" + uuid.uuid4().hex.upper()

    # Save the validated request using the existing function.
    return create_request(
        request_id=request_id,
        requester_name=requester_name.strip(),
        requester_email=requester_email.strip(),
        title=title.strip(),
        description=description,
        request_type=request_type.strip(),
        priority=priority
    )


# Statuses that do not block a new request.
INACTIVE_STATUSES = {
    "cancelled",
    "completed",
    "rejected"
}

# Common words that do not identify a specific application or resource.
RESOURCE_STOP_WORDS = {
    "a", "an", "the", "for", "to", "of", "my",
    "need", "want", "please", "new", "request",
    "access", "installation", "install", "installed",
    "software", "application", "system", "license",
    "with", "priority", "high", "medium", "low",
    "critical"
}


def normalize_resource(title):
    """Extract identifying words from a request title."""

    # Ignore capitalization and punctuation.
    words = re.findall(r"[a-z0-9]+", title.casefold())

    # Remove generic request words.
    resource_words = {
        word
        for word in words
        if word not in RESOURCE_STOP_WORDS
    }

    return resource_words


def normalize_category(request_type):
    """Standardize common software request categories."""

    # Compare category names without capitalization differences.
    category = request_type.strip().casefold()

    # Recognize the common software-access categories.
    software_categories = {
        "software access",
        "software installation",
        "power bi desktop access",
        "power bi access"
    }

    if category in software_categories:
        return "software access"

    return category


def find_possible_duplicates(requester_email, title, request_type):
    """Find similar active requests for the supplied email address."""

    # Validate the information required for duplicate checking.
    values = [requester_email, title, request_type]

    if any(
        not isinstance(value, str) or not value.strip()
        for value in values
    ):
        return []

    # Normalize the submitted request information.
    email = requester_email.strip().casefold()
    resource = normalize_resource(title)
    category = normalize_category(request_type)

    # Avoid matching requests without an identifiable resource.
    if not resource:
        return []

    # Retrieve existing requests associated with the same email.
    # Email matching is not an authentication mechanism.
    with sqlite3.connect(DATABASE_PATH) as connection:

        connection.row_factory = sqlite3.Row

        rows = connection.execute(
            """
            SELECT
                request_id,
                title,
                request_type,
                priority,
                status
            FROM requests
            WHERE LOWER(TRIM(requester_email)) = ?
            """,
            (email,)
        ).fetchall()

    matches = []

    for row in rows:

        # Exclude completed, rejected, and cancelled requests.
        if row["status"].strip().casefold() in INACTIVE_STATUSES:
            continue

        # Avoid comparing unrelated request categories.
        if normalize_category(row["request_type"]) != category:
            continue

        # Compare the resource names in the request titles.
        existing_resource = normalize_resource(row["title"])

        if not existing_resource:
            continue

        # Calculate token overlap between the two resource names.
        common_words = resource.intersection(existing_resource)

        similarity = (
            2 * len(common_words)
            / (len(resource) + len(existing_resource))
        )

        # Exact resource matches are strong duplicate candidates.
        if resource == existing_resource:
            match_type = "POSSIBLE_DUPLICATE"

        # Substantially overlapping names require review.
        elif len(common_words) >= 2 and similarity >= 0.75:
            match_type = "SIMILAR_REQUEST"

        else:
            continue

        # Return only information needed for the warning.
        matches.append({
            "request_id": row["request_id"],
            "title": row["title"],
            "priority": row["priority"],
            "status": row["status"],
            "match_type": match_type
        })

    return matches



def list_requests_by_email(requester_email, open_only=True, priority=None):
    """Retrieve requests associated with an email address."""

    # Validate the supplied email.
    if not isinstance(requester_email, str) or not requester_email.strip():
        return {
            "outcome": "VALIDATION_ERROR",
            "error": "A requester email address is required."
        }

    # Validate the open-only filter.
    if not isinstance(open_only, bool):
        return {
            "outcome": "VALIDATION_ERROR",
            "error": "open_only must be true or false."
        }

    # Validate the optional priority filter.
    allowed_priorities = {"Low", "Medium", "High", "Critical"}

    if priority is not None and priority not in allowed_priorities:
        return {
            "outcome": "VALIDATION_ERROR",
            "error": "Invalid priority filter."
        }

    # Match email addresses without case or surrounding whitespace differences.
    email = requester_email.strip().casefold()

    query = """
        SELECT
            request_id,
            title,
            request_type,
            description,
            priority,
            status,
            created_at,
            updated_at
        FROM requests
        WHERE LOWER(TRIM(requester_email)) = ?
    """

    parameters = [email]

    # Exclude terminal lifecycle statuses when requesting open records.
    if open_only:
        query += """
            AND LOWER(TRIM(status)) NOT IN (
                'cancelled', 'completed', 'rejected'
            )
        """

    # Apply an optional priority filter.
    if priority is not None:
        query += " AND priority = ?"
        parameters.append(priority)

    # Return the newest records first.
    query += " ORDER BY created_at DESC, request_id DESC"

    # Execute a parameterized, read-only SQLite query.
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row

        rows = connection.execute(
            query,
            parameters
        ).fetchall()

    requests = [dict(row) for row in rows]

    return {
        "outcome": "SUCCESS",
        "requester_email": email,
        "open_only": open_only,
        "priority": priority,
        "count": len(requests),
        "requests": requests
    }


if __name__ == "__main__":
    
    # Ensure the database structure exists.
    create_database()


    ## Creating a request
    # result = create_request(
    #     request_id="REQ-001",
    #     requester_name="Alex Morgan",
    #     requester_email="alex@example.com",
    #     title="Laptop Replacement",
    #     description="My laptop battery is no longer charging.",
    #     request_type="IT Equipment",
    #     priority="Medium"
    # )

    # get_request_result = get_request("REQ-001")


    ## Updating a request
    ## Test modification of an already cancelled request.
    ## The database should reject this modification.
    update_request_result = update_request(
        request_id="REQ-001",
        priority="Critical"
    )

    # Display the operation result.
    print("Update test result:", update_request_result)

    # Retrieve the record to verify that its values remain unchanged.
    saved_request = get_request("REQ-001")

    print("Current status:", saved_request["status"])
    print("Current priority:", saved_request["priority"])

    ## Cancelling a request
    # cancel_request_result = cancel_request("REQ-001")
    # print("Cancellation result:", cancel_request_result)

    # cancelled_request = get_request("REQ-001")
    # print("Request after cancellation:", cancelled_request)


    # Test validation using an unsupported priority.
    # This test must not create a database record.
    # auto_request_result = create_request_auto(
    #     requester_name="Test Employee",
    #     requester_email="test@example.com",
    #     title="Software Access",
    #     description="Requesting access to an application.",
    #     request_type="Software Access",
    #     priority="Urgent"
    # )

    # # Display the validation result.
    # print("Validation test:", auto_request_result)