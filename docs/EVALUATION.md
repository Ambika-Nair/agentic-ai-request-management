# Evaluation Report — Agentic AI Enterprise Request Management System

**Last updated:** November 18, 2026  
**System:** Two-agent IT request-management prototype using Microsoft Foundry, GPT-5 Mini, Python, SQLite, Microsoft Graph API, and Foundry File Search  
**Environment:** Local Python 3.12 application with Microsoft Foundry agents  
**Test data:** Fictional IT request records and controlled Outlook demonstration data

---

## 1. Executive Summary

This report documents the functional testing and evaluation of the Agentic AI Enterprise Request Management System.

The project was evaluated through two primary workflows:

1. **Terminal-based conversational request management:** CREATE, UPDATE, GET, CANCEL, LIST, semantic duplicate detection, and policy question answering.
2. **Outlook email-based request creation:** Email intake, conversation tracking, field extraction, confirmation, restricted self-service authorization, duplicate screening, Operations Agent execution, and SQLite verification.

### Key Results

| Evaluation area | Result |
|---|---|
| Original orchestration regression tests | 8/8 passed |
| Terminal end-to-end request lifecycle | Passed |
| Semantic duplicate detection | Demonstrated on selected scenarios |
| Policy question answering | Expected answer returned |
| Outlook email intake and draft persistence | Passed |
| Email confirmation and reply interpretation | Passed |
| Restricted demo authorization | Positive and negative scenarios passed |
| Email CREATE execution-ledger tests | 8/8 passed |
| Outlook-to-SQLite CREATE | Passed |
| Independent SQLite verification | Passed |

**Overall outcome:** The system successfully demonstrated natural-language IT request management through two interaction channels, using two Microsoft Foundry agents and Python-controlled database execution.

These findings establish a working local prototype. They do not establish production readiness, measured model accuracy, or guaranteed reliability under concurrent use.

---

## 2. Evaluation Objectives

The evaluation focused on determining whether the prototype could:

1. Interpret natural-language IT requests accurately enough to complete the tested scenarios.
2. Extract and retain structured information across multiple interactions.
3. Draft suitable request titles and identify categories.
4. Identify missing mandatory information before submission.
5. Detect potentially duplicate requests using semantic comparisons.
6. Require confirmation before database modifications.
7. Select appropriate operational tools through the Operations Agent.
8. Execute database operations using validated Python functions.
9. Retrieve saved records to verify completed operations.
10. Extend the existing architecture to an Outlook email channel.
11. Persist email conversation and confirmation state across application executions.
12. Prevent automatic repeated CREATE attempts after an uncertain execution outcome.

The evaluation used both offline regression tests and live integration demonstrations.

---

## 3. Test Environment

### Technology Stack

| Component | Configuration |
|---|---|
| AI platform | Microsoft Foundry |
| Model | GPT-5 Mini |
| Communication Agent | `request-communication-agent` |
| Operations Agent | `request-operations-agent` |
| Orchestration | Python 3.12 |
| Request database | SQLite — `requests.db` |
| Email state database | SQLite — `email_threads.db` |
| Email integration | Microsoft Graph API |
| Email authentication | MSAL with delegated permissions |
| Azure authentication | Azure CLI |
| Knowledge retrieval | Foundry File Search |
| Testing framework | Python `unittest` |
| Development environment | VS Code and Anaconda |

### Agent Responsibilities

**Request Communication Agent**

Handles intent understanding, information extraction, request drafting, follow-up interpretation, semantic comparisons, confirmation interpretation, and policy question answering.

**Request Operations Agent**

Selects registered operational functions, including CREATE, GET, LIST, UPDATE, and CANCEL.

**Python Orchestration**

Maintains workflow state, validates outputs and approved operations, enforces application safeguards, executes local database functions, and verifies results.

The AI agents do not directly execute arbitrary SQL queries.

---

## 4. Automated Orchestration Regression Testing

**Evaluation date:** November 9, 2026

Eight offline regression tests were executed against the original terminal-based orchestration logic.

The tests used simulated model and tool responses to validate application behavior.

### Test Results

| Test | Outcome | Behavior evaluated |
|---|---|---|
| `test_decline_cannot_write` | Pass | A declined operation cannot trigger a database write |
| `test_duplicate_lookup_fails_closed` | Pass | Failed duplicate screening cannot authorize creation |
| `test_echoed_fields_do_not_invalidate_approval` | Pass | Unchanged fields do not cause unnecessary confirmation loops |
| `test_email_status_lookup_uses_all_records` | Pass | Request lookup uses retrieved records rather than stale context |
| `test_explicit_request_id_takes_precedence` | Pass | Explicit request IDs take precedence over previous context |
| `test_old_request_not_silently_reused` | Pass | An unrelated earlier request ID is not silently reused |
| `test_title_and_other_fields_survive_followups` | Pass | Request information is preserved across follow-up interactions |
| `test_unpresented_proposal_cannot_write` | Pass | Database writes are blocked before required confirmation |

**Result: 8 tests passed.**

### Interpretation

The regression tests demonstrate that the orchestration layer can enforce the tested application rules under simulated agent responses.

These tests do not measure the accuracy of GPT-5 Mini across an independent evaluation dataset.

They also do not establish reliability under adversarial input, concurrent database operations, or production traffic.

---

## 5. Terminal End-to-End Functional Testing

**Evaluation date:** November 9, 2026

A complete request lifecycle was tested using a fictional USB-C docking-station request.

### Test Request

**Request:** USB-C docking station for Portfolio Demo Tester  
**Request ID:** `REQ-04F5BD75A3EB4F5497936DB08EF98D90`

### Test Sequence

| Step | Operation | Observed result | Verdict |
|---|---|---|---|
| 1 | CREATE | Request created with Submitted status and Low priority | Pass |
| 2 | UPDATE | Priority changed from Low to High following confirmation | Pass |
| 3 | GET | Retrieved status Submitted and priority High | Pass |
| 4 | CANCEL | Request status changed to Cancelled following confirmation | Pass |
| 5 | GET after cancellation | Retrieved status Cancelled and priority High | Pass |
| 6 | LIST | Cancelled request returned in request history | Pass |
| 7 | Policy Q&A | Expected policy requirements returned | Answer correct; retrieval trace not verified |

### Key Observations

The workflow demonstrated that the system could use natural-language instructions to select and execute different request-management operations.

The Operations Agent selected registered functions while Python executed the corresponding SQLite operations.

Database records were retrieved after modifications to verify actual saved values.

The demonstration also showed that cancelled records remained available for read-only history lookup.

### Observed Timestamps

The recorded demonstration included:

- Creation: `2026-11-09 19:28:40`
- Priority update: `2026-11-09 19:32:14`
- Cancellation: `2026-11-09 19:35:56`

These are database-generated timestamps. Their timezone was not established in the recorded output.

**Overall result: Terminal request lifecycle passed.**

---

## 6. Semantic Duplicate Detection Evaluation

The project uses semantic comparisons to identify requests that may refer to the same resource even when different wording is used.

### Example Scenario

Existing request:

> "Power BI Desktop access"

New request:

> "I need permission to use Power BI."

The application retrieves relevant active requests associated with the supplied requester email.

The Communication Agent compares the requested resource and intended outcome.

Supported classifications include:

- `DUPLICATE`
- `POSSIBLE_DUPLICATE`
- `DISTINCT`

### Observed Results

Selected demonstrations showed that the system could detect potentially equivalent Power BI requests despite differences in wording.

The orchestration layer prevented duplicate or unresolved possible-duplicate submissions in the tested scenarios.

### Limitations

Semantic duplicate detection was not evaluated against a large, independently labeled dataset.

Precision, recall, and false-positive rates were not calculated.

The duplicate-checking mechanism also does not guarantee prevention of concurrent duplicate submissions.

**Result: Semantic duplicate detection demonstrated in selected scenarios.**

---

## 7. Policy Question Answering Evaluation

The Communication Agent was configured with Microsoft Foundry File Search and a fictional IT policy knowledge source.

**Policy ID:** `IT-POL-042`

### Test Question

> "What approvals are required for Power BI Desktop access?"

### Expected Answer

- Requester's manager approval.
- Data Governance Team approval.
- Documented business justification.

### Observed Result

The Communication Agent returned the expected policy requirements.

The answer was consistent with the fictional policy.

However, the recorded terminal output did not independently establish whether File Search was invoked for that specific question.

### Evaluation Conclusion

The test supports a claim that the agent returned the expected policy answer.

It does not establish measured retrieval accuracy, citation quality, or verified grounding across multiple policy questions.

**Result: Answer correctness demonstrated; retrieval trace remains unverified.**

---

## 8. Outlook Email Integration Evaluation

**Evaluation date:** November 18, 2026

The Outlook integration was evaluated using a controlled self-service CREATE scenario.

### Test Scenario

A requester submitted an email requesting an ergonomic keyboard for a workstation.

The request was processed through the existing Request Communication Agent and Request Operations Agent.

### 8.1 Email Intake and Information Extraction

The original email included the request description, category, requester name, and priority.

The Communication Agent extracted:

| Field | Extracted value |
|---|---|
| Requester name | Demo Self-Service User |
| Title | Ergonomic keyboard for workstation |
| Description | Please create a request for an ergonomic keyboard for my workstation. |
| Request type | IT Equipment |
| Priority | Medium |
| Requester email | Initially missing |

The missing requester email prevented the application from preparing a complete confirmation.

**Result: Passed — incomplete request correctly identified.**

### 8.2 Multi-Turn Email Conversation

The requester provided the missing email address in a reply to the original Outlook conversation.

The application processed the new message while preserving previously extracted information.

The saved draft was updated without requiring the original fields to be supplied again.

The resulting request contained all mandatory information.

**Observed output:**

`Missing fields: None`

**Result: Passed — draft persistence and follow-up processing demonstrated.**

### 8.3 Email Confirmation Preparation

Once the request was complete, the system performed read-only duplicate screening.

The screening returned no potential duplicates among the active records checked.

A frozen confirmation proposal was created and stored in `email_threads.db`.

**Proposal reference:** `62c552…32c79` (abbreviated)

The proposal contained the exact request details submitted for confirmation.

**Result: Passed — confirmation proposal successfully prepared.**

### 8.4 Confirmation Email Sending

The confirmation email was sent through Microsoft Graph after explicit terminal approval.

**Observed result:**

- Microsoft Graph returned HTTP 202.
- Confirmation status changed to `PRESENTED`.
- No IT request database write occurred at this stage.

The confirmation workflow uses a validity period of 72 hours after presentation.

HTTP 202 confirms that Graph accepted the sending operation; it does not independently prove final delivery. Delivery was checked separately during the demonstration.

**Result: Passed — confirmation send accepted and proposal state updated.**

### 8.5 Confirmation Reply Interpretation

The requester replied directly to the confirmation email.

**Reply:**

> "Yes, the request details are correct as shown."

The Communication Agent interpreted the reply as:

`CONFIRM`

The decision was explicitly recorded in the confirmation store.

**Observed proposal status:**

`CONFIRMED_PENDING_AUTHORIZATION`

The confirmation did not directly create the IT request.

**Result: Passed — explicit email confirmation correctly interpreted and recorded.**

---

## 9. Authorization Evaluation

The email integration was tested with both negative and positive self-service scenarios.

### 9.1 Negative Authorization Test

In an earlier demonstration, the supplied requester email did not match the authenticated Outlook account.

The authorization check returned:

`BLOCKED`

The application rejected the request for the controlled self-service scenario.

No database write occurred.

**Result: Passed — mismatched requester identity blocked.**

### 9.2 Positive Authorization Test

The ergonomic-keyboard request used the same email address as the authenticated Outlook account.

The application verified that:

- The proposal had been confirmed.
- The supplied requester matched the authenticated mailbox.
- The confirmation reply was found in Sent Items.
- The request met the restricted self-service demonstration rules.

**Observed result:**

`DEMO-ELIGIBLE`

The diagnostic explicitly stated that no database write had been authorized or executed.

**Result: Passed — self-service demo eligibility established.**

### Authorization Limitations

These checks are appropriate for the controlled portfolio demonstration.

They do not establish enterprise authorization, organizational roles, or authority to submit requests on another person's behalf.

---

## 10. Email CREATE Execution-Ledger Testing

**Evaluation date:** November 18, 2026

The execution ledger was implemented to prevent automatic repeated CREATE operations for the same confirmed proposal.

The ledger uses persistent SQLite storage.

### Execution States

| Status | Description |
|---|---|
| `CLAIMED` | A CREATE execution attempt has been reserved |
| `CREATED` | A request was successfully verified and recorded |
| `NEEDS_REVIEW` | An execution outcome is uncertain |

### Automated Tests

| Test | Result |
|---|---|
| Unpresented proposal is blocked | Pass |
| Presented proposal without confirmation is blocked | Pass |
| On-behalf-of request is blocked | Pass |
| Repeated CREATE claim is blocked after restart | Pass |
| Successful CREATE result is recorded and retry blocked | Pass |
| Uncertain execution result fails closed | Pass |
| Expired confirmation is blocked | Pass |
| Incorrect execution attempt cannot finalize | Pass |

**Result: 8/8 tests passed.**

### Interpretation

These tests demonstrate that the execution ledger enforces the tested state transitions and prevents repeated claims for the same proposal.

The implementation does not guarantee exactly-once execution across both SQLite databases.

An interrupted operation may leave its result uncertain and require manual reconciliation.

---

## 11. Outlook-to-SQLite CREATE Integration Test

**Evaluation date:** November 18, 2026

This was the final integration test of the supervised Outlook CREATE workflow.

### Test Conditions

Before execution, the application confirmed:

- Valid proposal state and deadline.
- No previous execution attempt.
- Matching Outlook requester and authenticated account.
- Verified confirmation reply.
- Unchanged frozen request details.
- No potential duplicates among the active records checked.

The preflight returned:

`READY FOR CONTROLLED CREATE`

No database record was created during preflight.

### Execution

The controlled CREATE script displayed the confirmed request details.

The operator explicitly entered:

`CREATE`

The Operations Agent selected the registered `create_request_auto` function.

Python validated the requested operation and executed the local SQLite function.

The application retrieved the newly created record and checked its stored values against the frozen request.

### Observed Result

**Terminal output:**

```text
SUCCESS: IT request created and verified.
Request ID: REQ-26D3B0ED311A4F3CA528A96E44000A9E
Status: Submitted
Title: Ergonomic keyboard for workstation
Execution ledger: CREATED
```

### Independent Database Verification

The saved request was retrieved separately using `database.get_request()`.

The returned record contained:

| Field | Verified value |
|---|---|
| Request ID | `REQ-26D3…00A9E` |
| Requester name | Demo Self-Service User |
| Request title | Ergonomic keyboard for workstation |
| Description | Please create a request for an ergonomic keyboard for my workstation. |
| Request type | IT Equipment |
| Priority | Medium |
| Status | Submitted |
| Created timestamp | 2026-11-18 18:11:51 |
| Updated timestamp | 2026-11-18 18:11:51 |

The requester email in the persisted record also matched the confirmed draft; the personal address is intentionally omitted from this public-facing report.

The saved record matched the approved request details.

The execution ledger was marked `CREATED`.

**Final result: PASS — supervised Outlook-to-SQLite CREATE completed and independently verified.**

### Scope of the Result

This demonstration establishes that the tested Outlook CREATE workflow works end to end.

It does not establish unattended email processing or automated email-based UPDATE and CANCEL functionality.

The final database write required separate terminal approval.

---

## 12. Additional Observations

### Requester Information Extraction

An earlier terminal demonstration showed the agent requesting a full name more than once.

This indicates a conversational usability issue that could be improved through additional extraction and context-retention evaluation.

### Structured Agent Output

A malformed structured response caused a JSON decoding error in an earlier development test.

The application was subsequently designed to distinguish retryable read-only reasoning errors from uncertain database-write outcomes.

Write operations should never be repeated automatically solely because an agent response or acknowledgment failed.

### Email Conversation Persistence

The Outlook demonstration showed that the application could process an initial request and a later reply while retaining the previously collected request fields.

This was an important integration outcome because the individual Python scripts run as separate processes.

### Duplicate Screening Scope

The email workflow screened active requests associated with the supplied requester email.

No potential duplicates were identified for the ergonomic-keyboard request within that checked scope.

The result does not imply that every organizational request or possible duplicate was searched.

---

## 13. Known Limitations

| Area | Limitation |
|---|---|
| Enterprise authentication | Personal Outlook mailbox verification is not organizational authorization |
| Terminal identity | A typed requester email does not prove identity |
| Email automation | The current workflow is supervised, not continuously running |
| Email operations | CREATE demonstrated; email-based UPDATE/CANCEL not implemented end to end |
| Database design | Two local SQLite databases without a single atomic execution transaction |
| Concurrency | Duplicate checks and subsequent writes can race |
| LLM accuracy | No comprehensive labeled evaluation dataset |
| Semantic duplicates | Limited selected-scenario testing |
| RAG observability | File Search invocation not verified in the recorded policy test |
| Security testing | No comprehensive adversarial testing reported |
| Deployment | Local application rather than hosted production service |
| Monitoring | No production observability or SLA measurements |
| Priority handling | Legacy terminal code contains a Medium fallback; email execution validates supplied priority |

The project should not be presented as production-ready or as providing guaranteed duplicate prevention.

---

## 14. Future Evaluation Recommendations

Future evaluation could include:

- A labeled dataset of request-intent and field-extraction examples.
- Precision and recall measurements for semantic duplicate detection.
- Multi-turn conversations involving corrections and interruptions.
- Automated verification of Foundry File Search retrieval traces.
- Robustness testing for malformed agent responses.
- Concurrent CREATE execution tests.
- Security and prompt-injection testing.
- Role-based access-control validation.
- Recovery testing for interrupted database operations.
- Evaluation of a continuously running email-processing service.

These activities would support further development but are not required to establish the completed local demonstration.

---

## 15. Final Evaluation Conclusion

The Agentic AI Enterprise Request Management System successfully demonstrated the use of two Microsoft Foundry agents for conversational request handling and structured operational workflows.

The original terminal application completed a verified CREATE, UPDATE, GET, CANCEL, and LIST lifecycle.

The Outlook integration successfully extended the system to email-based request intake and demonstrated:

- Multi-turn request information collection.
- Persistent email conversation state.
- AI-generated structured request drafts.
- Explicit confirmation interpretation.
- Restricted self-service authorization checks.
- Semantic duplicate screening.
- Durable CREATE execution tracking.
- Operations Agent function calling.
- Python-controlled database execution.
- Independent SQLite verification.

The November 18, 2026 test confirmed that an Outlook request could be converted into a persisted IT request with status `Submitted`.

The evaluation supports the conclusion that the system is a **functional, supervised multi-agent portfolio prototype** with clearly separated responsibilities for conversational reasoning, operational tool selection, and controlled execution.

Further authentication, transactional safeguards, evaluation, and deployment work would be necessary for production use.