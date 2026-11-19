
"""Offline regression checks for the request-management orchestrator.

No Azure calls or SQLite writes are performed by these tests.
"""

import unittest
from unittest.mock import patch

import chat_prototype as app


class AgentWorkflowTests(unittest.TestCase):

    def test_title_and_other_fields_survive_followups(self):
        """A request draft must retain fields across conversation turns."""

        state = app.new_state()

        # Simulate valid structured responses from Communication Agent.
        responses = [
            {
                "draft_title": "Adobe Acrobat Pro access",
                "title_changed": False,
                "category": "Software Access",
                "updates": {},
                "description_evidence": None,
            },
            {
                "draft_title": "Adobe Acrobat Pro access",
                "title_changed": False,
                "category": "Software Access",
                "updates": {"priority": "High"},
                "description_evidence": None,
            },
            {
                "draft_title": "Adobe Acrobat Pro access",
                "title_changed": False,
                "category": "Software Access",
                "updates": {"requester_name": "Jordan Example"},
                "description_evidence": None,
            },
        ]

        with patch.object(app, "comm_json", side_effect=responses):

            app.understand_create(
                None, state,
                "I need Adobe Acrobat Pro access", {}
            )

            self.assertEqual(
                state["draft"]["title"],
                "Adobe Acrobat Pro access"
            )

            # Priority must not be assumed.
            self.assertNotIn("priority", state["draft"])

            app.understand_create(
                None, state, "High priority", {}
            )

            app.understand_create(
                None, state,
                "Jordan Example and jordan@example.com", {}
            )

        self.assertEqual(state["draft"]["priority"], "High")
        self.assertEqual(state["draft"]["requester_name"], "Jordan Example")
        self.assertEqual(state["draft"]["requester_email"], "jordan@example.com")
        self.assertEqual(state["draft"]["title"], "Adobe Acrobat Pro access")

    def test_old_request_not_silently_reused(self):
        """A new resource lookup must not inherit an unrelated request ID."""

        state = app.new_state()
        state["selected"] = {"request_id": "REQ-OLD001"}

        plan = {
            "reference_query": "Copilot Studio access",
            "request_id": None,
        }

        request_id, reason = app.resolve_id(
            plan, state, "Check Copilot Studio status"
        )

        self.assertIsNone(request_id)
        self.assertEqual(reason, "RESOURCE_LOOKUP_REQUIRED")

    def test_explicit_request_id_takes_precedence(self):
        """An explicitly supplied ID overrides previous selection."""

        state = app.new_state()
        state["selected"] = {"request_id": "REQ-OLD001"}

        request_id, reason = app.resolve_id(
            {"reference_query": "Copilot Studio access"},
            state,
            "Show REQ-NEW002"
        )

        self.assertEqual(request_id, "REQ-NEW002")
        self.assertIsNone(reason)

    def test_echoed_fields_do_not_invalidate_approval(self):
        """Repeating unchanged fields must not cause another approval loop."""

        state = app.new_state()

        state["pending"] = {
            "operation": "CREATE",
            "arguments": {
                "title": "Adobe Acrobat Pro access",
                "priority": "High",
            },
            "presented": True,
        }

        with patch.object(app, "comm_json", return_value={
            "decision": "APPROVE",
            "corrections": {
                "title": "Adobe Acrobat Pro access"
            },
        }):

            decision, corrections, _ = app.interpret_pending(
                None, state, "Yes, looks right"
            )

        self.assertEqual(decision, "APPROVE")
        self.assertEqual(corrections, {})

    def test_decline_cannot_write(self):
        """A declined draft must never call a database operation."""

        state = app.new_state()

        state["pending"] = {
            "operation": "CREATE",
            "arguments": {"title": "Test request"},
            "presented": True,
        }

        with (
            patch.object(
                app, "interpret_pending",
                return_value=("DECLINE", {}, None)
            ),
            patch.object(app, "say", return_value=True),
            patch.object(app, "ops_execute") as execute,
        ):

            self.assertTrue(
                app.handle_pending(
                    state, None, None, "Please discard"
                )
            )

            execute.assert_not_called()

        self.assertIsNone(state["pending"])

    def test_unpresented_proposal_cannot_write(self):
        """A write cannot proceed before displaying the proposal."""

        state = app.new_state()

        state["pending"] = {
            "operation": "CREATE",
            "arguments": {"title": "Test request"},
            "presented": False,
        }

        with (
            patch.object(app, "say", return_value=True),
            patch.object(app, "ops_execute") as execute,
        ):

            self.assertTrue(
                app.handle_pending(
                    state, None, None, "Approve"
                )
            )

            execute.assert_not_called()

    def test_email_status_lookup_uses_all_records(self):
        """Resource matching must operate on fresh database results."""

        state = app.new_state()

        state["flow"] = "AWAIT_REFERENCE"
        state["operation"] = "GET"
        state["reference_query"] = "Copilot Studio access"

        records = [
            {
                "request_id": "REQ-COP1",
                "title": "Copilot Studio access",
                "status": "Submitted",
            },
            {
                "request_id": "REQ-PBI2",
                "title": "Power BI Desktop access",
                "status": "Submitted",
            },
        ]

        with (
            patch.object(
                app, "ops_execute",
                return_value={"requests": records}
            ) as listing,
            patch.object(
                app, "comm_json",
                return_value={"matching_ids": ["REQ-COP1"]}
            ),
            patch.object(app, "begin_get") as get_status,
        ):

            app.search_status_by_email(
                state, None, None, "jordan@example.com"
            )

        listing.assert_called_once_with(
            None,
            "LIST",
            {
                "requester_email": "jordan@example.com",
                "open_only": False,
            },
        )

        get_status.assert_called_once_with(
            state, None, None, "REQ-COP1"
        )

    def test_duplicate_lookup_fails_closed(self):
        """A failed duplicate check must not authorize creation."""

        with (
            patch.object(
                app, "find_possible_duplicates",
                return_value=[]
            ),
            patch.object(
                app, "ops_execute",
                return_value={"error": "Unavailable"}
            ),
        ):

            with self.assertRaises(RuntimeError):

                app.duplicate_matches(
                    {
                        "requester_email": "jordan@example.com",
                        "title": "Test",
                        "request_type": "Software Access",
                    },
                    None,
                    None,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
