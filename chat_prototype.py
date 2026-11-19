
"""Agent-led request management with Microsoft Foundry, SQLite, and policy RAG.

Communication Agent owns intent, title drafting, semantic reasoning, and dialogue.
Operations Agent selects the five registered database functions.
Python validates structured decisions and executes permitted database actions.
This prototype uses fictional data; a typed email does not establish identity.
"""

import json
import os
import re

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential

from database import (
    cancel_request,
    create_request_auto,
    find_possible_duplicates,
    get_request,
    list_requests_by_email,
    update_request,
)
from semantic_duplicates import assess_duplicate_candidates

COMM_AGENT = "request-communication-agent"
OPS_AGENT = "request-operations-agent"
PRIORITIES = {v.casefold(): v for v in ("Low", "Medium", "High", "Critical")}
CATEGORIES = {"Software Access", "IT Equipment", "Other"}
CLOSED = {"cancelled", "completed", "rejected"}
ID_RE = re.compile(r"\bREQ-[A-Z0-9]+\b", re.IGNORECASE)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
FUNCTIONS = {
    "GET": ("get_request", get_request),
    "LIST": ("list_requests_by_email", list_requests_by_email),
    "CREATE": ("create_request_auto", create_request_auto),
    "UPDATE": ("update_request", update_request),
    "CANCEL": ("cancel_request", cancel_request),
}


def new_state():
    """Store workflow facts; no user-facing dialogue lives here."""
    return {
        "flow": None, "draft": {}, "selected": None, "listed": [],
        "pending": None, "list_filters": {}, "operation": None,
        "changes": {}, "history": [], "blocked_draft": None,
        "reference_query": None, "draft_turns": [],
    }


def clear_work(state):
    """Discard unfinished actions without erasing conversational history."""
    state.update({
        "flow": None, "draft": {}, "selected": None, "listed": [],
        "pending": None, "list_filters": {}, "operation": None,
        "changes": {}, "blocked_draft": None, "reference_query": None,"draft_turns": [],
    })


def parse_json(text):
    """Parse a structured model decision and reject unexpected shapes."""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I).strip()
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("Expected a JSON object from the Communication Agent")
    return result

def recent(state):
    return state["history"][-12:]

class AgentOutputFormatError(RuntimeError):
    """Raised when the Communication Agent repeatedly returns invalid JSON."""

def comm_json(comm, prompt):
    """Validate structured agent output, retrying malformed JSON once.

    Retries only Communication Agent reasoning or response generation.
    No database write is performed by this function.
    """

    last_error = None

    for attempt in range(2):

        if attempt == 0:
            current_prompt = prompt

        else:
            current_prompt = (
                "Your preceding response could not be parsed as "
                "one valid JSON object. Regenerate the answer for "
                "the original task below. Preserve its required "
                "keys, data constraints, and allowed values. "
                "Return one complete, syntactically valid JSON "
                "object, without Markdown fences or commentary.\n\n"
                + prompt
            )

        response = comm.responses.create(
            input=current_prompt
        )

        try:
            return parse_json(
                response.output_text
            )

        except ValueError as error:
            last_error = error

            if os.getenv("DEBUG_AGENT_DECISIONS") == "1":
                print(
                    "[Diagnostic: malformed Communication Agent "
                    f"JSON on attempt {attempt + 1}]"
                )

    raise AgentOutputFormatError(
        "Communication Agent returned invalid structured "
        "output after two attempts."
    ) from last_error


def say(comm, state, event, facts):
    """Ask Communication Agent to generate all ordinary dialogue."""
    prompt = (
        "You are the user-facing Request Communication Agent. "
        "Use ONLY verified facts in the event, not guesses. "
        "Respond naturally and briefly (normally 1-3 sentences); "
        "use a concise field summary for a confirmation or request list. "
        "Never show internal JSON, intent labels, or repetitive menus. "
        "Only event REVIEW_WRITE may ask the user to approve or submit a write. "
        "If event ASK_MISSING, ask for just the missing information. "
        "If event DUPLICATE_BLOCKED, no new request was submitted and creation "
        "cannot proceed just because the requester insists; offer to review "
        "the existing request or clarify genuinely different requirements. "
        "Do not offer a 'proceed anyway' option or claim the duplicate check "
        "can be overridden. If event DRAFT_DECLINED, the pending draft was "
        "discarded, not preserved. If event STATUS, use verified status only. "
        "A goodbye does not undo any earlier successful database action. "
        "Don't imply that database writes are disabled or that the application "
        "can perform an action that has no registered tool. "
        "Do not call tools in this response-composition step. "
       
        "Read-only GET and LIST operations do not require "
        "write-style confirmation. "

        "For event ASK_REQUEST_REFERENCE, ask the user to type "
        "either a request ID or a lookup email address. "

        "Do not offer lettered confirmation choices for a "
        "read-only status lookup. "

        "Do not ask the user to verbally declare authorization. "
        "Such a declaration is not authentication. "

        "Once an explicit lookup email has been provided, "
        "the orchestrator should retrieve matching records "
        "rather than repeatedly asking whether to proceed. "

        "Return ONLY JSON with a single key 'message'.\n\n"
        f"Event: {event}\nFacts: {json.dumps(facts)}\n"
        f"Recent conversation: {json.dumps(recent(state))}"
    )
    try:
        answer = comm_json(comm, prompt).get("message")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("Missing agent-generated reply")
        answer = answer.strip()
        ok = True
    except Exception as exc:
        print(f"[Technical diagnostic: communication failure ({type(exc).__name__})]")
        answer = (
            "The communication service is unavailable. "
            "Check the current request record before retrying any operation."
        )
        ok = False
    print("Assistant:", answer)
    state["history"].append({"role": "assistant", "content": answer})
    return ok


def plan_turn(comm, message, state):
    """Let Communication Agent decide user intent and action references."""
    snapshot = {
        "flow": state["flow"], "draft": state["draft"],
        "selected": state["selected"], "listed": state["listed"][:20],
        "awaited_operation": state["operation"],
        "pending": bool(state["pending"]),
        "reference_query": state["reference_query"],
    }
    prompt = (
        "You are the lead Request Communication Agent planning the next action. "
        "Do NOT call File Search or database tools in this planning step. "
        "Return ONLY JSON with keys: intent, request_id, selection_index, "
        "requester_email, reference_query, fields, changes, filters, "
        "policy_question. "
        "Allowed intents: CREATE, GET, LIST, UPDATE, CANCEL, KNOWLEDGE, "
        "CONTINUE, END, ABANDON, CHAT. "
        "fields contains requester_name, requester_email, title, description, "
        "request_type, priority; changes contains title, description, priority; "
        "filters contains open_only (boolean) and priority. "
        "For mixed questions, select the operational intent and ALSO return a "
        "standalone policy_question. For policy-only use KNOWLEDGE. "
        "A user describing a resource to request has CREATE intent even if "
        "the user does not explicitly supply a title. Draft a short specific "
        "title when possible; don't insist that the user provide title wording. "
        "Never invent a requester name/email, priority, request ID, or outcome. "
        "Priority is present only if explicitly stated as Low/Medium/High/Critical. "
        "Do not silently default to Medium or infer priority from 'urgent'. "
        "For an ongoing CREATE, interpret a reply as added fields rather than "
        "restarting unless the user clearly switches tasks. "
        "If the user cancels the current request AND asks a new question, "
        "prefer that new intent, not ABANDON. "
        "A named status request with no request ID should include a "
        "reference_query describing the resource so a lookup can be offered. "
        "Do not assume a previous lookup email is the current user's identity. "
        "Use recent context to resolve pronouns and selections. "
        "If the user withdraws an unfinished draft, use ABANDON. "
        "Only use END when the user is ending the conversation. "
        "When the user asks for the status of a named resource "
        "without providing a request ID, choose GET and provide "
        "reference_query describing that resource. "
        "Questions about cancelled, completed, rejected, historical, "
        "or previously submitted requests require a fresh LIST lookup "
        "with open_only set to false. "
        "Never conclude that no cancelled requests exist merely "
        "because a previous lookup returned only open requests. "
        "Use verified database results, not just conversation memory. "

        "Do not reuse the previously selected request ID merely "
        "because it is available in context. "

        "Use a selected request ID only when the user's latest "
        "message clearly refers to that same selected request. "
        "Return null rather than guessing.\n\n"
        f"Verified state: {json.dumps(snapshot)}\n"
        f"Recent conversation: {json.dumps(recent(state))}\n"
        f"Latest user message: {json.dumps(message)}"
    )
    plan = comm_json(comm, prompt)
    aliases = {
        "CREATE_REQUEST": "CREATE", "CHECK_STATUS": "GET",
        "MODIFY_REQUEST": "UPDATE", "CANCEL_REQUEST": "CANCEL",
        "LIST_REQUESTS": "LIST", "END_CONVERSATION": "END"
    }
    intent = str(plan.get("intent") or "CHAT").upper()
    plan["intent"] = aliases.get(intent, intent)
    if plan["intent"] not in {
        "CREATE", "GET", "LIST", "UPDATE", "CANCEL", "KNOWLEDGE",
        "CONTINUE", "END", "ABANDON", "CHAT",
    }:
        plan["intent"] = "CHAT"
    for key in ("fields", "changes", "filters"):
        if not isinstance(plan.get(key), dict):
            plan[key] = {}
    return plan



def understand_create(comm, state, message, plan):
    """Assemble a request draft using agent reasoning and grounded facts.

    Previously collected request fields are preserved.
    Only information from the current request may update those fields.
    """

    turns = state.setdefault("draft_turns", [])

    if message.strip():
        turns.append(message.strip())

    prompt = (
        "You are the Request Communication Agent. "
        "Extract information for the CURRENT request only. "
        "Do not reuse requester details from earlier completed, "
        "cancelled, or discarded requests.\n\n"

        "The existing draft is the source of truth for details "
        "already collected and accepted.\n"

        "Draft a concise professional title from the resource "
        "and outcome the user requests. "
        "Do not make the requester write an exact title when "
        "their need is already clear. "
        "Avoid adding the requester's name to the title "
        "unless needed to distinguish the request.\n"

        "Preserve an existing title unless the user explicitly "
        "changes the resource or title.\n"

        "Do not infer a requester name, email, or priority. "
        "A priority must be explicitly stated as "
        "Low, Medium, High, or Critical.\n"

        "Do not invent installation methods, license costs, "
        "approval requirements, business justifications, "
        "cost centres, or deployment instructions.\n"

        "For an optional description, supply description_evidence "
        "as an EXACT substring of the LATEST user message "
        "containing the user's stated requirement. "
        "Otherwise return null. "
        "Do not compose additional operational requirements.\n\n"

        "Return ONLY JSON with:\n"
        "- draft_title: string or null\n"
        "- title_changed: boolean\n"
        "- category: Software Access, IT Equipment, Other, or null\n"
        "- updates: object containing explicitly supplied "
        "requester_name and priority, if present\n"
        "- description_evidence: exact quoted substring or null\n\n"

        "Use only the current request messages and the draft. "
        "Do not call tools or address the user.\n\n"

        f"Current request messages: {json.dumps(turns[-10:])}\n"
        f"Existing draft: {json.dumps(state['draft'])}\n"
        f"Latest user message: {json.dumps(message)}"
    )

    extracted = comm_json(comm, prompt)

    updates = extracted.get("updates")

    if not isinstance(updates, dict):
        updates = {}

    draft = state["draft"]

    # Validate that the name was explicitly supplied in this turn.
    # An agent-inferred name from earlier conversations is rejected.
    candidate_name = updates.get("requester_name")

    if (
        isinstance(candidate_name, str)
        and candidate_name.strip()
    ):

        name = candidate_name.strip()

        if name.casefold() in message.casefold():
            draft["requester_name"] = name

    # Only an email explicitly typed during this request may be saved.
    emails = EMAIL_RE.findall(message)

    if len(emails) == 1:
        draft["requester_email"] = emails[0]

    # The agent extracts priority; Python validates explicit selection.
    candidate_priority = updates.get("priority")

    if isinstance(candidate_priority, str):

        priority = PRIORITIES.get(
            candidate_priority.strip().casefold()
        )

        if (
            priority
            and re.search(
                rf"\b{re.escape(priority)}\b",
                message,
                re.IGNORECASE
            )
        ):

            draft["priority"] = priority

    # A generated title is retained across subsequent turns.
    candidate_title = extracted.get("draft_title")

    if (
        isinstance(candidate_title, str)
        and candidate_title.strip()
    ):

        title_changed = (
            extracted.get("title_changed") is True
        )

        if (
            not draft.get("title")
            or (
                title_changed
                and bool(message.strip())
            )
        ):

            if title_changed:
                draft.pop("request_type", None)

            draft["title"] = (
                candidate_title.strip()[:160]
            )

    # Preserve only user-supplied description evidence.
    # Unsupported agent-generated provisioning details are not saved.
    evidence = extracted.get("description_evidence")

    if (
        isinstance(evidence, str)
        and evidence.strip()
    ):

        evidence = evidence.strip()

        if evidence.casefold() in message.casefold():
            draft["description"] = evidence

    # Category classification belongs to GPT-5 Mini.
    category = extracted.get("category")

    if (
        category in CATEGORIES
        and draft.get("title")
        and not draft.get("request_type")
    ):

        draft["request_type"] = category

    return draft



def interpret_pending(comm, state, message):
    """Use the agent to interpret approval, refusal, or correction."""
    pending = state["pending"]
    prompt = (
        "You are the Request Communication Agent assessing a response to a "
        "specific pending database operation. Return ONLY JSON with keys "
        "decision, corrections, policy_question. Decision is one of APPROVE, "
        "DECLINE, REVISE, QUESTION, SWITCH, END, UNCLEAR. "
        "APPROVE means clear unconditional approval of exactly the presented "
        "operation. REVISE means the user changed any detail, even if also "
        "agreeing. QUESTION is not approval. SWITCH starts a new task. "
        "Never decide from older dialogue rather than the latest user reply. "
        "corrections must contain ONLY changed fields from the latest message, "
        "not previously collected/unchanged data. For CREATE: requester_name, "
        "requester_email, title, description, request_type, priority; "
        "for UPDATE: title, description, priority. No tools, no prose.\n\n"
        f"Pending: {json.dumps(pending)}\nRecent dialogue: "
        f"{json.dumps(recent(state))}\nLatest user reply: {json.dumps(message)}"
    )
    result = comm_json(comm, prompt)
    decision = str(result.get("decision") or "UNCLEAR").upper()
    if decision not in {"APPROVE", "DECLINE", "REVISE", "QUESTION", "SWITCH", "END", "UNCLEAR"}:
        decision = "UNCLEAR"
    allowed = ({"requester_name", "requester_email", "title", "description", "request_type", "priority"}
               if pending["operation"] == "CREATE" else {"title", "description", "priority"})
    corrections = {}
    suggested = result.get("corrections")
    if isinstance(suggested, dict):
        for key, value in suggested.items():
            if key not in allowed or not isinstance(value, str) or not value.strip():
                continue
            value = value.strip()
            if key == "priority":
                value = PRIORITIES.get(value.casefold())
                if value is None:
                    continue
            if value != pending["arguments"].get(key):
                corrections[key] = value
    if decision == "APPROVE" and corrections:
        decision = "REVISE"
    if decision == "REVISE" and not corrections:
        decision = "UNCLEAR"
    if os.getenv("DEBUG_AGENT_DECISIONS") == "1":
        print(f"[Diagnostic: pending decision={decision}; corrected fields={list(corrections)}]")
    return decision, corrections, result.get("policy_question")


def retrieve_policy(comm, state, question):
    """Perform verified File Search through the existing agent."""
    prompt = (
        "Answer this IT policy question using your attached File Search tool. "
        "Invoke File Search before answering. Ground all policy facts in "
        "retrieved content; if not documented, state that clearly. "
        "Answer briefly unless an overview was explicitly requested. "
        "Do not promise actions unavailable to this system. "
        "Do not query the operational database.\n\n"
        f"Question: {question.strip()[:800]}"
    )
    response = comm.responses.create(input=prompt)
    used = any(getattr(item, "type", "") == "file_search_call" for item in response.output)
    answer = (response.output_text or "").strip()
    if used and answer:
        print("Assistant:", answer)
        state["history"].append({"role": "assistant", "content": answer})
        return True
    say(comm, state, "POLICY_SEARCH_UNVERIFIED", {"question": question, "no_policy_claims": True})
    return False


def ops_execute(ops, operation, args):
    """Let Operations Agent choose one tool; execute exact validated args."""
    tool_name, executor = FUNCTIONS[operation]
    prompt = (
        "You are the Request Operations Agent. Choose exactly one registered "
        "tool for the approved operation, using EXACTLY the approved arguments. "
        "Do not invent data or modify any argument.\n\n"
        f"Operation: {operation}\nApproved arguments: {json.dumps(args)}"
    )
    response = ops.responses.create(input=prompt)
    calls = [x for x in response.output if getattr(x, "type", "") == "function_call"]
    if len(calls) != 1 or calls[0].name != tool_name:
        raise RuntimeError("Operations Agent selected an unexpected tool")
    actual = json.loads(calls[0].arguments)
    if not isinstance(actual, dict):
        raise RuntimeError("Tool arguments must be a JSON object")
    if operation in {"LIST", "UPDATE"}:
        actual = {k: v for k, v in actual.items() if v is not None}
    if actual != args:
        raise RuntimeError("Operations Agent changed approved arguments")
    result = executor(**args)
    try:
        ops.responses.create(
            input=[{"type": "function_call_output", "call_id": calls[0].call_id,
                    "output": json.dumps(result)}],
            previous_response_id=response.id,
        )
    except Exception:
        # A write may already have succeeded; never retry automatically.
        print("[Technical diagnostic: tool acknowledgement failed; no automatic retry]")
    return result


def get_record(ops, request_id):
    return ops_execute(ops, "GET", {"request_id": request_id})


def duplicate_matches(draft, comm, ops, exclude=None):
    """Compare active records with the agent; fail closed on uncertainty."""
    exact = find_possible_duplicates(
        requester_email=draft["requester_email"],
        title=draft["title"],
        request_type=draft["request_type"],
    )
    listing = ops_execute(ops, "LIST", {
        "requester_email": draft["requester_email"], "open_only": True,
    })
    if not isinstance(listing, dict) or listing.get("error") or not isinstance(listing.get("requests"), list):
        raise RuntimeError("Active requests could not be verified")
    return assess_duplicate_candidates(
        communication_agent=comm, proposed=draft,
        active_records=listing["requests"], exact_matches=exact,
        exclude_id=exclude,
    )


def prepare_creation(state, comm, ops, message, plan):
    """Maintain a coherent draft and ask only for genuinely missing facts."""
    if state["flow"] not in {"CREATE", "DUPLICATE_REVIEW"}:
        state["draft"] = {}
    was_review = state["flow"] == "DUPLICATE_REVIEW"
    state["flow"] = "CREATE"
    understand_create(comm, state, message, plan)
    draft = state["draft"]
    required = ("title", "request_type", "priority", "requester_name", "requester_email")
    missing = next((field for field in required if not draft.get(field)), None)
    if missing:
        say(comm, state, "ASK_MISSING", {
            "missing_field": missing, "draft": draft,
            "instruction": "Only ask for this missing detail. Do not ask for approval.",
        })
        return
    if not EMAIL_RE.fullmatch(draft["requester_email"]):
        draft.pop("requester_email", None)
        say(comm, state, "ASK_MISSING", {"missing_field": "valid requester_email", "draft": draft})
        return
    if draft["request_type"] not in CATEGORIES or draft["priority"] not in PRIORITIES.values():
        raise ValueError("Unrecognized request category or priority")
    if was_review and state["blocked_draft"] == draft:
        state["flow"] = "DUPLICATE_REVIEW"
        say(comm, state, "DUPLICATE_CLARIFICATION_NEEDED", {
            "draft": draft, "candidates": state["listed"],
            "instruction": "Ask for specific access scope or purpose that differs; no override available.",
        })
        return
    matches = duplicate_matches(draft, comm, ops)
    if matches:
        state["flow"] = "DUPLICATE_REVIEW"
        state["blocked_draft"] = dict(draft)
        state["listed"] = matches[:20]
        state["selected"] = None
        say(comm, state, "DUPLICATE_BLOCKED", {
            "draft": draft, "matches": matches[:20],
            "creation_allowed": False,
            "instruction": "This is a blocked proposal, not a pending submission. "
                           "No proceed-anyway option exists. Clarification may be requested.",
        })
        return
    state["blocked_draft"] = None
    args = {
        "requester_name": draft["requester_name"],
        "requester_email": draft["requester_email"],
        "title": draft["title"],
        "description": draft.get("description") or "",
        "request_type": draft["request_type"],
        "priority": draft["priority"],
    }
    state["pending"] = {"operation": "CREATE", "arguments": args,
                        "snapshot": None, "presented": False}
    state["flow"] = "CONFIRM"
    state["pending"]["presented"] = say(comm, state, "REVIEW_WRITE", {
        "operation": "CREATE", "exact_arguments": args,
        "instruction": "Present the complete proposal and ask for explicit approval. "
                       "No database action has occurred yet.",
    })


def list_requests(state, comm, ops, email, filters):
    """List requests for an explicitly supplied lookup email."""
    if not isinstance(email, str) or not EMAIL_RE.fullmatch(email.strip()):
        state["flow"] = "LIST_EMAIL"
        state["list_filters"] = filters
        say(comm, state, "ASK_LOOKUP_EMAIL", {"filters": filters,
             "lookup_not_authentication": True})
        return
    arguments = {
        "requester_email": email.strip(),
        "open_only": filters.get("open_only") if type(filters.get("open_only")) is bool else True,
    }
    priority = filters.get("priority")
    if isinstance(priority, str) and priority.casefold() in PRIORITIES:
        arguments["priority"] = PRIORITIES[priority.casefold()]
    result = ops_execute(ops, "LIST", arguments)
    state["flow"] = None
    if result.get("error"):
        say(comm, state, "LOOKUP_FAILED", {"error": result["error"]})
        return
    rows = result.get("requests") or []
    state["listed"] = rows[:20]
    state["selected"] = None
    say(comm, state, "LIST_RESULTS", {
        "email": email, "count": len(rows), "records": rows[:20],
        "truncated": len(rows) > 20, "filters": arguments,
    })



def resolve_id(plan, state, message):
    """Resolve only explicit or agent-grounded request references.

    Do not silently reuse a previously selected record.
    """

    # An ID explicitly supplied by the requester takes precedence.
    ids = list(dict.fromkeys(
        value.upper()
        for value in ID_RE.findall(message)
    ))

    if len(ids) > 1:
        return None, "AMBIGUOUS"

    if len(ids) == 1:
        return ids[0], None

    # A named resource lookup must not silently reuse an older ID.
    reference_query = plan.get("reference_query")

    if (
        isinstance(reference_query, str)
        and reference_query.strip()
    ):
        return None, "RESOURCE_LOOKUP_REQUIRED"

    # Resolve a specific entry from a previously displayed list.
    index = plan.get("selection_index")

    if (
        type(index) is int
        and 1 <= index <= len(state["listed"])
    ):
        return state["listed"][index - 1]["request_id"], None

    # The Communication Agent may explicitly resolve a reference
    # to a record already verified in the active context.
    candidate = plan.get("request_id")

    if (
        isinstance(candidate, str)
        and ID_RE.fullmatch(candidate.strip())
    ):

        candidate = candidate.strip().upper()

        listed_ids = {
            row["request_id"].upper()
            for row in state["listed"]
        }

        if candidate in listed_ids:
            return candidate, None

        selected = state.get("selected")

        if (
            selected
            and candidate == selected["request_id"].upper()
        ):
            return candidate, None

        if state["flow"] == "AWAIT_REFERENCE":
            return candidate, None

    # Do not assume an old request is the one currently discussed.
    return None, "MISSING"



def begin_get(state, comm, ops, request_id):
    record = get_record(ops, request_id)
    state["flow"] = None
    state["reference_query"] = None
    if record.get("error"):
        state["selected"] = None
        say(comm, state, "NOT_FOUND", {"request_id": request_id, "error": record["error"]})
        return
    closed = str(record.get("status", "")).casefold() in CLOSED
    state["selected"] = None if closed else record
    say(comm, state, "STATUS", {"record": record, "closed_view_only": closed})



def search_status_by_email(state, comm, ops, email):
    """Search actual database records and use the agent to resolve the resource.

    A read-only lookup requires no submission-style confirmation.
    """

    subject = state.get("reference_query")

    if not subject:
        raise RuntimeError(
            "Missing resource description for status lookup."
        )

    # Operations Agent retrieves all statuses for the supplied email.
    result = ops_execute(
        ops,
        "LIST",
        {
            "requester_email": email,
            "open_only": False,
        },
    )

    if (
        not isinstance(result, dict)
        or result.get("error")
        or not isinstance(result.get("requests"), list)
    ):
        raise RuntimeError(
            "The Operations Agent could not verify the request list."
        )

    records = result["requests"]

    if os.getenv("DEBUG_AGENT_DECISIONS") == "1":
        print(
            "[Diagnostic: email status lookup returned "
            f"{len(records)} records; "
            f"IDs={[row.get('request_id') for row in records]}]"
        )

    # The earlier selected Power BI request is not a search result.
    # Replace the previous selection with the fresh lookup records.
    state["selected"] = None
    state["listed"] = records[:20]
    state["flow"] = None
    state["operation"] = None
    state["reference_query"] = None

    if not records:

        say(
            comm,
            state,
            "NO_RECORDS_FOR_EMAIL",
            {
                "lookup_email": email,
                "record_count": 0,
                "lookup_completed": True,
            },
        )

        return

    candidates = records[:20]

    # The Communication Agent matches the user's requested resource
    # against the actual records, rather than against old dialogue.
    prompt = (
        "You are the Request Communication Agent.\n"

        "Resolve a user's description of an existing IT request "
        "against VERIFIED database records returned by the "
        "Operations Agent.\n\n"

        "Compare the requested application, resource, purpose, "
        "and request titles semantically.\n"

        "Use only the provided database records.\n"

        "Ignore earlier selected requests and old request lists.\n"

        "Do not invent records or request IDs.\n"

        "Do not claim a request doesn't exist merely because "
        "the wording differs.\n"

        "If exactly one record clearly matches, return its ID.\n"

        "If several records could match, include their IDs.\n"

        "If none can be identified confidently, return an empty list.\n"

        "Do not call tools or generate user-facing text.\n\n"

        "Return ONLY a JSON object with:\n"
        '{"matching_ids":["REQ-..."]}\n\n'

        f"User's requested resource: {json.dumps(subject)}\n"

        f"Actual records: {json.dumps([
            {
                'request_id': row.get('request_id'),
                'title': row.get('title'),
                'description': row.get('description'),
                'status': row.get('status'),
            }
            for row in candidates
        ])}"
    )

    matched = comm_json(
        comm,
        prompt
    )

    matching_ids = matched.get("matching_ids")

    valid_ids = {
        row["request_id"]
        for row in candidates
    }

    if (
        not isinstance(matching_ids, list)
        or any(
            not isinstance(request_id, str)
            or request_id not in valid_ids
            for request_id in matching_ids
        )
    ):
        raise RuntimeError(
            "Communication Agent returned invalid request references."
        )

    matching_ids = list(
        dict.fromkeys(matching_ids)
    )

    if len(matching_ids) == 1:

        # Read the matched request again to verify its latest status.
        begin_get(
            state,
            comm,
            ops,
            matching_ids[0],
        )

        return

    possible_records = [
        row
        for row in candidates
        if row["request_id"] in matching_ids
    ]

    # If no confident match exists, don't make a false claim
    # that the record is missing from the database.
    if not possible_records:
        possible_records = candidates

    state["listed"] = possible_records

    say(
        comm,
        state,
        "REQUEST_LOOKUP_NEEDS_DISAMBIGUATION",
        {
            "requested_resource": subject,
            "lookup_email": email,
            "possible_records": possible_records,
            "records_not_examined": max(
                0,
                len(records) - len(candidates)
            ),
            "instruction": (
                "Explain that a unique match was not established. "
                "Help the user select the relevant existing request. "
                "Do not claim it does not exist."
            ),
        },
    )


def prepare_update(state, comm, ops, request_id, proposed):
    """Validate an agent-extracted modification without scripted dialogue."""
    record = get_record(ops, request_id)
    if record.get("error"):
        say(comm, state, "NOT_FOUND", {"request_id": request_id})
        return
    if str(record.get("status", "")).casefold() in CLOSED:
        state["selected"] = None
        say(comm, state, "CLOSED_BLOCK", {"record": record})
        return
    state["selected"] = record
    changes = {}
    for key in ("title", "description", "priority"):
        value = proposed.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        if key == "priority":
            value = PRIORITIES.get(value.casefold())
        if value and value != record.get(key):
            changes[key] = value
    if not changes:
        state["flow"] = "UPDATE_CHANGES"
        say(comm, state, "ASK_UPDATE_DETAILS", {
            "record": record, "editable_fields": ["title", "description", "priority"]})
        return
    if "title" in changes:
        candidates = duplicate_matches({**record, "title": changes["title"]}, comm, ops,
                                       exclude=request_id)
        if candidates:
            state["flow"] = None
            say(comm, state, "DUPLICATE_BLOCKED", {
                "matches": candidates, "creation_allowed": False, "operation": "UPDATE"})
            return
    args = {"request_id": request_id, **changes}
    state["pending"] = {"operation": "UPDATE", "arguments": args,
                        "snapshot": record, "presented": False}
    state["flow"] = "CONFIRM"
    state["pending"]["presented"] = say(comm, state, "REVIEW_WRITE", {
        "operation": "UPDATE", "before": record, "proposed_changes": changes,
        "instruction": "Require explicit approval before writing."})


def prepare_cancel(state, comm, ops, request_id):
    record = get_record(ops, request_id)
    if record.get("error"):
        say(comm, state, "NOT_FOUND", {"request_id": request_id})
        return
    if str(record.get("status", "")).casefold() in CLOSED:
        state["selected"] = None
        say(comm, state, "CLOSED_BLOCK", {"record": record})
        return
    state["selected"] = record
    state["pending"] = {"operation": "CANCEL", "arguments": {"request_id": request_id},
                        "snapshot": record, "presented": False}
    state["flow"] = "CONFIRM"
    state["pending"]["presented"] = say(comm, state, "REVIEW_WRITE", {
        "operation": "CANCEL", "record": record,
        "instruction": "Require explicit approval before cancelling."})


def execute_approved(state, comm, ops):
    """Execute a pending operation at most once, then verify SQLite state."""
    pending = state["pending"]
    state["pending"] = None
    state["flow"] = None
    operation, args = pending["operation"], pending["arguments"]
    if operation == "CREATE":
        matches = duplicate_matches(args, comm, ops)
        if matches:
            state["listed"] = matches[:20]
            state["draft"] = dict(args)
            state["blocked_draft"] = dict(args)
            state["flow"] = "DUPLICATE_REVIEW"
            say(comm, state, "DUPLICATE_BLOCKED", {
                "matches": matches[:20], "creation_allowed": False})
            return
    else:
        current = get_record(ops, args["request_id"])
        old = pending["snapshot"]
        if current.get("error") or str(current.get("status", "")).casefold() in CLOSED:
            say(comm, state, "WRITE_BLOCKED", {"current": current,
                "reason": "request missing or closed"})
            return
        if any(current.get(k) != old.get(k)
               for k in ("status", "title", "description", "priority")):
            say(comm, state, "WRITE_BLOCKED", {
                "current": current, "reason": "record changed after review"})
            return
        if operation == "UPDATE" and "title" in args:
            matches = duplicate_matches({**current, "title": args["title"]}, comm, ops,
                                        exclude=args["request_id"])
            if matches:
                say(comm, state, "DUPLICATE_BLOCKED", {
                    "matches": matches, "operation": "UPDATE"})
                return
    result = ops_execute(ops, operation, args)
    if result.get("error") or result.get("outcome") == "DUPLICATE_REQUEST":
        say(comm, state, "WRITE_REJECTED", {"operation": operation, "result": result})
        return
    request_id = result.get("request_id") if operation == "CREATE" else args["request_id"]
    if not request_id:
        say(comm, state, "WRITE_UNVERIFIED", {"operation": operation, "no_retry": True})
        return
    record = get_record(ops, request_id)
    if record.get("error"):
        say(comm, state, "WRITE_UNVERIFIED", {"operation": operation, "no_retry": True})
        return
    if operation == "CREATE":
        checks = ("requester_name", "requester_email", "title", "request_type", "priority")
        verified = all(record.get(k) == args[k] for k in checks)
    elif operation == "UPDATE":
        verified = all(record.get(k) == v for k, v in args.items() if k != "request_id")
    else:
        verified = str(record.get("status", "")).casefold() == "cancelled"
    if not verified:
        say(comm, state, "WRITE_UNVERIFIED", {
            "operation": operation, "record": record, "no_retry": True})
        return
    state["draft"] = {}
    state["blocked_draft"] = None
    state["selected"] = None if str(record.get("status", "")).casefold() in CLOSED else record
    say(comm, state, "WRITE_VERIFIED", {"operation": operation, "record": record})


def handle_pending(state, comm, ops, message):
    """Interpret pending replies before ordinary planning."""
    pending = state["pending"]
    if not pending.get("presented"):
        say(comm, state, "WRITE_BLOCKED", {"reason": "confirmation not displayed"})
        return True
    decision, corrections, question = interpret_pending(comm, state, message)
    if decision == "APPROVE":
        execute_approved(state, comm, ops)
        return True
    if decision == "DECLINE":
        clear_work(state)
        say(comm, state, "DRAFT_DECLINED", {"no_write": True})
        return True
    if decision == "REVISE":
        operation = pending["operation"]
        if operation == "CREATE":
            state["draft"] = {**pending["arguments"], **corrections}
            state["pending"] = None
            state["flow"] = "CREATE"
            prepare_creation(state, comm, ops, "", {"fields": {}})
            return True
        if operation == "UPDATE":
            request_id = pending["arguments"]["request_id"]
            proposal = {k: v for k, v in pending["arguments"].items() if k != "request_id"}
            proposal.update(corrections)
            state["pending"] = None
            state["flow"] = None
            prepare_update(state, comm, ops, request_id, proposal)
            return True
        state["pending"] = None
        state["flow"] = None
        say(comm, state, "CANCELLATION_REVIEW_AGAIN", {"no_write": True})
        return True
    if decision == "QUESTION":
        if isinstance(question, str) and question.strip():
            retrieve_policy(comm, state, question)
        else:
            say(comm, state, "ANSWER_PENDING_QUESTION", {"question": message, "pending": pending})
        return True
    if decision == "END":
        clear_work(state)
        say(comm, state, "GOODBYE", {"no_new_write_this_turn": True})
        return False
    if decision == "SWITCH":
        clear_work(state)
        return None
    say(comm, state, "CLARIFY_APPROVAL", {"pending": pending})
    return True


def handle_turn(state, comm, ops, message):
    """Use Communication Agent reasoning to orchestrate both agents."""
    state["history"].append({"role": "user", "content": message})
    if state["pending"]:
        handled = handle_pending(state, comm, ops, message)
        if handled is not None:
            return handled

            # Complete an already established, read-only status workflow
    # when the requester supplies a lookup email.
    if (
        state["flow"] == "AWAIT_REFERENCE"
        and state["operation"] == "GET"
        and state.get("reference_query")
    ):

        email_match = EMAIL_RE.search(message)

        if email_match:

            search_status_by_email(
                state,
                comm,
                ops,
                email_match.group(0),
            )

            return True
        
    plan = plan_turn(comm, message, state)
    intent = plan["intent"]
    if intent in {"END", "ABANDON"}:
        clear_work(state)
        say(comm, state, "GOODBYE" if intent == "END" else "ABANDONED", {
            "no_new_write_this_turn": True,
            "earlier_successful_writes_remain_valid": True,
        })
        return intent != "END"
    question = plan.get("policy_question")
    if intent == "KNOWLEDGE" and not question:
        question = message
    policy_answered = False
    if isinstance(question, str) and question.strip():
        policy_answered = retrieve_policy(comm, state, question)
    if intent == "KNOWLEDGE":
        return True
    if state["flow"] == "LIST_EMAIL" and intent in {"LIST", "CONTINUE", "CHAT"}:
        email_match = EMAIL_RE.search(message)
        email = email_match.group(0) if email_match else plan.get("requester_email")
        list_requests(state, comm, ops, email, state["list_filters"])
        return True
    if state["flow"] == "AWAIT_REFERENCE" and intent in {"GET", "UPDATE", "CANCEL", "LIST", "CONTINUE", "CHAT"}:
        ids = list(dict.fromkeys(x.upper() for x in ID_RE.findall(message)))
        if len(ids) == 1 and state["operation"] in {"GET", "UPDATE", "CANCEL"}:
            operation = state["operation"]
            saved_changes = state["changes"]
            state["flow"] = None
            state["operation"] = None
            state["changes"] = {}
            if operation == "GET":
                begin_get(state, comm, ops, ids[0])
            elif operation == "UPDATE":
                prepare_update(state, comm, ops, ids[0], saved_changes)
            else:
                prepare_cancel(state, comm, ops, ids[0])
            return True
        email_match = EMAIL_RE.search(message)
        if email_match and state["operation"] == "GET" and state["reference_query"]:
            search_status_by_email(state, comm, ops, email_match.group(0))
            return True
    # Starting a different task abandons an unapproved creation draft.
    if state["flow"] in {"CREATE", "DUPLICATE_REVIEW"} and intent in {"GET", "LIST", "UPDATE", "CANCEL"}:
        state["draft"] = {}
        state["blocked_draft"] = None
        state["flow"] = None
    if state["flow"] in {"CREATE", "DUPLICATE_REVIEW"} and intent in {"CREATE", "CONTINUE", "CHAT"}:
        prepare_creation(state, comm, ops, message, plan)
        return True
    if state["flow"] == "UPDATE_CHANGES" and intent in {"UPDATE", "CONTINUE", "CHAT"}:
        intent = "UPDATE"
    if intent in {"CONTINUE", "CHAT"} and state["listed"]:
        candidate, error = resolve_id(plan, state, message)
        if not error and candidate in {row["request_id"] for row in state["listed"]}:
            intent = "GET"
    if intent == "LIST":
        email_match = EMAIL_RE.search(message)
        email = email_match.group(0) if email_match else plan.get("requester_email")
        state["list_filters"] = plan["filters"]
        list_requests(state, comm, ops, email, plan["filters"])
        return True
    if intent == "CREATE":
        clear_work(state)
        state["flow"] = "CREATE"
        prepare_creation(state, comm, ops, message, plan)
        return True
    if intent in {"GET", "UPDATE", "CANCEL"}:
        request_id, error = resolve_id(plan, state, message)
        if error:
            state["flow"] = "AWAIT_REFERENCE"
            state["operation"] = intent
            state["changes"] = plan["changes"]
            state["reference_query"] = plan.get("reference_query") or message
            email_match = EMAIL_RE.search(message)
            if intent == "GET" and email_match:
                search_status_by_email(state, comm, ops, email_match.group(0))
                return True
            say(comm, state, "ASK_REQUEST_REFERENCE", {
                "requested_operation": intent, "resource_hint": state["reference_query"],
                "allowed_lookup": "request ID, or a lookup email for read-only status search",
                "no_identity_assumption": True,
            })
            return True
        if intent == "GET":
            begin_get(state, comm, ops, request_id)
        elif intent == "UPDATE":
            prepare_update(state, comm, ops, request_id, plan["changes"] or state["changes"])
        else:
            prepare_cancel(state, comm, ops, request_id)
        state["operation"] = None
        state["changes"] = {}
        return True
    if not policy_answered:
        say(comm, state, "CONVERSATION", {"user_message": message,
            "supported_operations": ["CREATE", "GET", "LIST", "UPDATE", "CANCEL", "Policy Q&A"]})
    return True


def main():
    """Start the existing two Foundry agents and process user turns."""
    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    if not endpoint:
        print("[Configuration error: FOUNDRY_PROJECT_ENDPOINT is missing]")
        return
    state = new_state()
    with AIProjectClient(endpoint=endpoint, credential=AzureCliCredential()) as project:
        with (project.get_openai_client(agent_name=COMM_AGENT) as comm,
              project.get_openai_client(agent_name=OPS_AGENT) as ops):
            say(comm, state, "SESSION_STARTED", {
                "available_capabilities": ["Create", "Check status", "List", "Update", "Cancel", "Policy Q&A"],
                "fictional_data": True, "typed_email_is_not_authentication": True,
            })
            while True:
                try:
                    message = input("\nYou: ").strip()
                except (KeyboardInterrupt, EOFError):
                    break
                if not message:
                    continue
                try:
                    if not handle_turn(state, comm, ops, message):
                        break
                
                except AgentOutputFormatError:

                    # Preserve the current draft and workflow.
                    # A structured-output error is not permission
                    # to abandon or repeat a database operation.
                    print(
                        "[Technical diagnostic: structured agent "
                        "output was invalid; workflow preserved]"
                    )

                    say(
                        comm,
                        state,
                        "AGENT_REASONING_RETRY_FAILED",
                        {
                            "workflow_preserved": True,
                            "database_write_not_authorized": True,
                            "next_step": (
                                "Ask the user to restate the "
                                "latest information or request."
                            ),
                        },
                    )

                except Exception as exc:
                    # No uncertain write is retried automatically.
                    print(f"[Technical diagnostic: {type(exc).__name__}: {exc}]")
                    clear_work(state)
                    say(comm, state, "OPERATION_ERROR", {
                        "reason": type(exc).__name__, "no_automatic_retry": True,
                    })


if __name__ == "__main__":
    main()
