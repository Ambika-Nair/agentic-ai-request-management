# Demo Walkthrough — Agentic AI Enterprise Request Management System

**Project:** Agentic AI Enterprise Request Management System  
**Technology:** Microsoft Foundry, GPT-5 Mini, Python, SQLite, Microsoft Graph API, Outlook, Function Calling, and RAG  
**Demonstration duration:** Approximately 5–6 minutes  
**Last updated:** November 18, 2026

---

## 1. Demonstration Objective

This walkthrough demonstrates how a two-agent AI system can manage IT requests through natural-language conversations and Outlook email.

The objective is to demonstrate:

- Natural-language request understanding.
- Multi-agent orchestration.
- Request drafting and missing-information collection.
- Email conversation management.
- Semantic duplicate detection.
- Explicit confirmation and controlled authorization.
- AI-driven operational tool selection.
- Python-controlled database execution.
- Independent verification of saved request records.

The demonstration uses existing test results and screenshots to avoid unnecessary new Foundry API calls or database writes.

The system is a **functional local portfolio prototype**, not a production-deployed service desk.

---

## 2. Demonstration Preparation

Before starting the presentation, prepare the following:

| Item | What to display |
|---|---|
| Architecture diagram | Overall system architecture |
| Microsoft Foundry | The two configured GPT-5 Mini agents |
| Communication Agent | Instructions and relevant configuration |
| Operations Agent | Five registered function tools |
| Outlook intake | Original ergonomic-keyboard email and follow-up |
| Confirmation | Frozen request details and confirmation reply |
| Authorization | Successful `DEMO-ELIGIBLE` output |
| CREATE execution | Successful terminal output |
| SQLite verification | Saved request with `Submitted` status |
| Terminal workflow | Previous CREATE, UPDATE, GET, CANCEL, LIST demonstration |

Use recorded screenshots wherever possible.

Do not rerun the completed ergonomic-keyboard CREATE operation. Its execution ledger already records the request as `CREATED`.

Remove personal email addresses, authentication details, Azure subscription information, access tokens, and other private configuration values from screenshots.

---

## 3. Demonstration Flow

### Part 1 — Project Introduction (0:00–0:40)

**What to show:** Project README or architecture diagram.

**Suggested explanation:**

"I built an AI-powered IT request-management system using Microsoft Foundry and two GPT-5 Mini agents.

The idea was to make it easier to handle requests that arrive in natural language, without relying entirely on predefined forms or rigid workflows.

The system can understand a request, collect missing information, check whether a similar request already exists, and perform database operations after validation and confirmation.

I initially built a terminal-based application supporting CREATE, UPDATE, GET, CANCEL, and LIST operations. I then extended the same architecture to Outlook, allowing users to submit requests through email.

The key design principle is that AI agents handle reasoning and operational tool selection, while Python controls validations and database execution."

### Part 2 — Explain the Multi-Agent Architecture (0:40–1:30)

**What to show:** Architecture diagram and the two agents in Microsoft Foundry.

**Suggested explanation:**

"The system has two agents with clearly separated responsibilities.

The first is the Request Communication Agent. It handles natural-language understanding, intent classification, drafting request titles, extracting information, interpreting confirmations, semantic duplicate comparison, and policy-related questions.

The second is the Request Operations Agent. It is responsible for selecting the appropriate registered database function.

There are five supported functions: create, get, list, update, and cancel.

Python acts as the orchestration and validation layer. It ensures that the selected operation and arguments are valid before executing the corresponding SQLite function.

This keeps the reasoning layer separate from the actual database operations."

**Architecture summary:**

```text
User (Terminal / Outlook)
          |
          v
   Python Orchestration
          |
      +---+---+
      |       |
      v       v
Communication   Operations
   Agent          Agent
      |             |
      v             v
 Policy RAG     Function Selection
                    |
                    v
             Python Validation
                    |
                    v
                SQLite DB
```

For Outlook, Microsoft Graph handles mailbox access, while a separate SQLite database stores conversation drafts, confirmation proposals, and execution records.

**Important distinction:** This is Python-mediated two-agent orchestration, not a native Agent-to-Agent protocol.

---

### Part 3 — Demonstrate Outlook Request Intake (1:30–2:15)

**What to show:** Original Outlook email and request draft extracted by the Communication Agent.

**Test request:**

> "Please create a request for an ergonomic keyboard for my workstation."

**Suggested explanation:**

"I tested the email integration using an ergonomic-keyboard request sent through Outlook.

The application retrieved the message using Microsoft Graph API and passed the content to the Communication Agent.

The agent extracted the request title, description, category, requester name, and priority.

It identified that the requester email was missing, so the draft remained incomplete.

I then provided the missing email address in a reply within the same Outlook conversation.

The application retained the information from the original message and updated the saved draft without asking for the earlier fields again."

**Extracted request:**

| Field | Value |
|---|---|
| Requester name | Demo Self-Service User |
| Title | Ergonomic keyboard for workstation |
| Description | Please create a request for an ergonomic keyboard for my workstation. |
| Request type | IT Equipment |
| Priority | Medium |
| Requester email | Provided in follow-up |

**Verification evidence:**

```text
Missing fields: None

Preview completed.
No outgoing email was sent and the request database was not modified.
```

**What this demonstrates:**

The Communication Agent extracts information from unstructured email while the application maintains request context across multiple messages and Python executions.

---

### Part 4 — Confirmation, Authorization, and Duplicate Screening (2:15–3:05)

**What to show:** Confirmation preview, interpreted confirmation reply, and authorization diagnostic.

**Suggested explanation:**

"Once all mandatory details were available, the system performed duplicate screening against relevant active records.

The Communication Agent assessed whether the request was semantically similar to an existing request. In this case, no potential duplicates were identified among the records checked.

The application then prepared a frozen confirmation proposal containing the exact request details.

I sent that confirmation through Outlook and replied to confirm that the information was correct.

The Communication Agent interpreted the reply as CONFIRM.

However, the system did not immediately create the request. It first verified the authenticated Outlook account and confirmed that the reply came from the expected self-service requester."

**Confirmation reply:**

> "Yes, the request details are correct as shown."

**Communication Agent interpretation:**

```json
{
  "decision": "CONFIRM",
  "reason": "The reply explicitly agrees that the request details are correct."
}
```

The exact reason text may vary between model responses.

**Confirmation status:**

```text
CONFIRMED_PENDING_AUTHORIZATION
```

**Authorization result:**

```text
Confirmation reply verified: True
Demo eligible: True

Result: DEMO-ELIGIBLE
```

The self-service demonstration also included a negative test where the requester email differed from the authenticated account.

That scenario was correctly blocked.

**What this demonstrates:**

The system separates user confirmation, identity checks, and authorization to execute a database operation.

The current identity checks are limited to the controlled self-service demonstration. They are not equivalent to enterprise role-based authorization.

---

### Part 5 — Operations Agent CREATE Execution (3:05–4:00)

**What to show:** Successful CREATE execution output and independent SQLite verification.

**Suggested explanation:**

"After the request passed the confirmation, authorization, and duplicate checks, I ran the controlled CREATE execution.

The application presented the final request details and required explicit terminal approval.

After approval, it reserved an execution attempt in the ledger.

The Operations Agent selected the registered create_request_auto function, and Python validated the arguments before executing the local database function.

Once the request was created, Python retrieved the record from SQLite and checked that the stored details matched the confirmed request.

The execution ledger was then marked CREATED."

**Execution evidence:**

```text
SUCCESS: IT request created and verified.

Request ID: REQ-26D3B0ED311A4F3CA528A96E44000A9E

Status: Submitted

Title: Ergonomic keyboard for workstation

Execution ledger: CREATED
```

**Independent SQLite verification:**

The saved request was retrieved using the existing `get_request()` database function.

| Field | Verified value |
|---|---|
| Request ID | REQ-26D3…00A9E |
| Requester name | Demo Self-Service User |
| Request type | IT Equipment |
| Title | Ergonomic keyboard for workstation |
| Priority | Medium |
| Status | Submitted |
| Created at | 2026-11-18 18:11:51 |

The personal requester email is omitted from public presentation materials.

**What this demonstrates:**

The request was not simply acknowledged by the AI agent. It was actually created, persisted in SQLite, and independently verified.

The final database write required explicit terminal approval. The Outlook integration does not automatically execute CREATE when a confirmation email is received.

---

### Part 6 — Demonstrate the Terminal Request Lifecycle (4:00–4:45)

**What to show:** Previous successful terminal-based lifecycle test.

**Suggested explanation:**

"Before extending the application to Outlook, I built and tested the request-management workflow through a terminal interface.

That interface supports creating requests, updating their details, retrieving status, cancelling requests, and listing existing records.

For example, I tested a fictional USB-C docking-station request.

The application created the request with Low priority, updated it to High after confirmation, retrieved its current status, cancelled it, and verified that the saved status was Cancelled.

The same two Foundry agents and Python database functions support these operations."

**Verified terminal test:**

| Operation | Result |
|---|---|
| CREATE | Submitted with Low priority |
| UPDATE | Priority changed from Low to High |
| GET | Submitted, High priority |
| CANCEL | Status changed to Cancelled |
| GET after cancellation | Cancelled, High priority |
| LIST | Cancelled record returned |

**Additional functionality:**

The Communication Agent is connected to Foundry File Search to support answers based on a fictional IT policy.

In the recorded test, the agent returned the expected approval requirements for Power BI Desktop access.

The recorded terminal answer did not independently verify the File Search invocation, so this is presented as a successful policy-answer scenario rather than a measured retrieval evaluation.

---

### Part 7 — Reliability, Testing, and Limitations (4:45–5:30)

**What to show:** Evaluation Report or execution-ledger test results.

**Suggested explanation:**

"One important consideration was preventing accidental duplicate request creation.

For the email workflow, I implemented a durable execution ledger that records when a CREATE attempt is reserved, completed, or requires review.

If the application stops after an attempt begins, it cannot simply retry the same proposal and risk creating another record.

I also ran offline regression tests for the original orchestration logic and the execution ledger. Both reported eight passing tests.

The current system is a local functional prototype. To make it production-ready, I would strengthen enterprise authentication, transactional execution controls, monitoring, and broader evaluation of the agents."

**Testing summary:**

| Test area | Result |
|---|---|
| Original orchestration tests | 8/8 passed |
| Terminal request lifecycle | Passed |
| Email draft persistence | Passed |
| Email confirmation | Passed |
| Restricted demo authorization | Passed |
| Email execution-ledger tests | 8/8 passed |
| Outlook-to-SQLite CREATE | Passed |
| Independent database verification | Passed |

**Known limitations:**

- Supervised Outlook CREATE rather than continuous inbox automation.
- No end-to-end Outlook UPDATE or CANCEL workflow.
- Demo-level identity verification rather than enterprise authorization.
- Local SQLite storage rather than a production database.
- No atomic exactly-once guarantee across both SQLite databases.
- Limited formal testing of model accuracy and semantic duplicate detection.
- No comprehensive production observability or security evaluation.

---

## 4. Key Technical Design Decisions

### Why use two agents instead of one?

The system separates natural-language reasoning from operational tool selection.

The Communication Agent focuses on understanding requests and interacting with users.

The Operations Agent focuses on selecting registered database functions.

Python coordinates both agents and applies deterministic validation before database execution.

This separation makes the system easier to understand, test, and extend to other communication channels.

### Why not let the AI agents directly execute SQL?

LLMs can produce incorrect or unexpected outputs.

Allowing unrestricted database execution would introduce unnecessary operational risk.

Instead, the Operations Agent selects a registered function and Python validates its name and arguments.

The local database function performs the operation, and the saved record is retrieved for verification.

### Why use Microsoft Graph for Outlook?

Microsoft Graph provides an API for accessing Outlook messages and sending replies using authenticated delegated permissions.

It allows the system to retrieve email conversations and associate messages with saved request drafts.

This makes it possible to extend the terminal application into an email-based workflow without introducing a separate set of AI agents.

### Why use a separate email state database?

Email conversations require different information from operational IT request records.

`email_threads.db` stores conversation state, processed-message information, confirmation proposals, and execution attempts.

`requests.db` stores the actual IT request records.

Separating these responsibilities keeps the workflow state distinct from operational records.

### Why use an execution ledger?

A database operation can succeed even when the application fails before recording its result.

Automatically repeating CREATE could produce a duplicate request.

The execution ledger reserves an attempt before execution and blocks automatic reuse of the same confirmed proposal.

If the outcome is uncertain, the operation must be reconciled manually rather than blindly retried.

### Why use RAG?

Request records and organizational policy knowledge have different responsibilities.

SQLite stores request records and status information.

Foundry File Search provides access to the configured fictional policy source.

This allows the Communication Agent to answer policy questions without treating policy documents as the source of live operational data.

---

## 5. Common Interview Questions and Answers

### Q1. What problem were you trying to solve?

"I wanted to explore how AI agents could simplify IT request management when requests arrive as unstructured messages.

Instead of requiring users to enter every field into a rigid form, the system extracts information, asks for missing details, and prepares a structured request.

The operational actions are still controlled through validated Python functions."

### Q2. Why did you use Microsoft Foundry?

"I wanted practical experience building and coordinating AI agents rather than using a single LLM prompt.

Microsoft Foundry provided the environment for deploying the GPT-5 Mini agents, configuring their instructions and tools, and connecting policy knowledge.

I used Python to integrate the agents with operational functions and Outlook."

### Q3. How do the two agents communicate?

"Python orchestrates the workflow between them.

The Communication Agent handles language understanding and semantic reasoning.

The Operations Agent selects the registered operational function when the workflow is ready for an action.

Python validates the selected function and executes the corresponding local implementation.

This is Python-mediated orchestration, not a native Agent-to-Agent protocol."

### Q4. How do you prevent hallucinations?

"I don't treat model responses as authoritative database results.

The Operations Agent can select only registered functions, and Python validates the function name and arguments.

After an operation, the application retrieves the actual database record to verify the result.

For policy questions, the Communication Agent has access to a configured File Search knowledge source. Broader grounding evaluations would still be needed for production use."

### Q5. How does duplicate detection work?

"The application retrieves active requests associated with the requester.

The Communication Agent compares the intended resource and outcome, rather than relying only on matching titles.

Python checks the comparison results and blocks duplicate or unresolved possible-duplicate submissions.

It is a safeguard for the tested workflow, not a universal guarantee under concurrent execution."

### Q6. How do you handle missing information in an email?

"The Communication Agent extracts the available fields and identifies missing information.

The draft is stored against the email conversation.

When the requester provides additional information in a later reply, the application updates the existing draft without discarding previously collected details.

I tested this with the ergonomic-keyboard request, where the requester email was provided in a follow-up."

### Q7. How do you authorize email requests?

"For this portfolio demonstration, I used a restricted self-service approach.

The application verifies the authenticated Outlook account, the requester email, and the recorded confirmation reply.

The CREATE operation also requires explicit terminal approval.

This is suitable for demonstrating the workflow, but enterprise use would require stronger identity and role-based authorization."

### Q8. What happens if CREATE succeeds but the application crashes?

"The application saves a durable execution claim before the CREATE operation.

If the application restarts and finds an existing claim, it does not automatically repeat the operation.

A verified successful operation is marked CREATED. An uncertain outcome requires reconciliation.

Because the execution ledger and request database are separate, this is not a full atomic exactly-once guarantee."

### Q9. What was the most important technical challenge?

"One challenge was maintaining the right separation between AI reasoning and operational execution.

I wanted the agents to handle understanding, semantic comparison, and tool selection, without allowing model outputs to directly control database writes.

Another challenge was maintaining request state across Outlook replies and separate script executions.

I addressed that by using persistent email conversation storage, confirmation records, and a dedicated execution ledger."

### Q10. What would you improve next?

"I would focus on production authentication and authorization, a more scalable database, reliable event-driven email processing, and better monitoring.

I would also evaluate the agents on a larger dataset for field extraction, semantic duplicate detection, and policy-answer grounding.

The current project demonstrates the end-to-end architecture and working integration, but those improvements would be necessary before an enterprise deployment."

---

## 6. Demonstration Evidence Checklist

Before presenting or publishing the project, verify that the following evidence is available.

- [ ] Architecture diagram showing the two agents and both interaction channels.
- [ ] Screenshot of the Communication Agent in Microsoft Foundry.
- [ ] Screenshot of the Operations Agent and its five registered functions.
- [ ] Original Outlook request and follow-up information.
- [ ] Completed structured request draft.
- [ ] Confirmation proposal and confirmation reply interpretation.
- [ ] `DEMO-ELIGIBLE` authorization result.
- [ ] Successful CREATE execution output.
- [ ] SQLite record showing `Submitted` status.
- [ ] Execution ledger showing `CREATED`.
- [ ] Original terminal request lifecycle test evidence.
- [ ] All personal information and credentials removed from public screenshots.

Do not repeat the already-completed ergonomic-keyboard CREATE operation just to produce additional screenshots.

---

## 7. Final Project Summary

The Agentic AI Enterprise Request Management System demonstrates how two Microsoft Foundry agents can support conversational request-management workflows across terminal and Outlook interfaces.

The Communication Agent handles language understanding, request drafting, follow-up interpretation, semantic comparisons, and policy questions.

The Operations Agent selects registered database functions.

Python coordinates the workflow, applies validation and authorization rules, executes local database functions, and verifies persisted results.

The project successfully demonstrated:

- A complete terminal-based CREATE, UPDATE, GET, CANCEL, and LIST lifecycle.
- Outlook email intake and multi-turn request drafting.
- Confirmation and restricted self-service authorization.
- Semantic duplicate screening.
- Supervised CREATE execution through the Operations Agent.
- Durable execution tracking.
- Independent SQLite verification.

**The main outcome is a working end-to-end multi-agent prototype that connects conversational AI reasoning to controlled operational execution.**

The system is suitable for demonstrating agent orchestration, LLM function calling, workflow design, state management, and AI application integration in a technical interview or portfolio review.