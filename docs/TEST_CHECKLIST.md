
# Test Checklist — Agentic AI Enterprise Request Management

## Project Information

Project: Agentic AI Enterprise Request Management System

Platform: Microsoft Foundry

Models: GPT-5 Mini

Backend: Python and SQLite

Final smoke-test date: November 9, 2026

Test data: Fictional

---

## 1. Automated Regression Tests

Command:

```cmd
python -m unittest test_regression.py -v
```

### Completed Results

- [x] Declined request cannot trigger database write.
- [x] Failed duplicate lookup blocks creation.
- [x] Unchanged fields do not invalidate approval.
- [x] Email-based status lookup uses fresh records.
- [x] Explicit request ID takes precedence.
- [x] Unrelated previous request ID is not silently reused.
- [x] Draft fields survive follow-up messages.
- [x] Unpresented proposals cannot trigger database writes.

**Result: 8/8 tests passed.**

---

## 2. Live End-to-End Tests

### Test Record

Requester: Portfolio Demo

Email: portfolio.demo.smoke2026@example.com

Resource: USB-C docking station

Request ID:

`REQ-04F5BD75A3EB4F5497936DB08EF98D90`

### Completed Scenarios

- [x] CREATE request with explicit approval.
- [x] Generate and store a request ID.
- [x] Classify the request as IT Equipment.
- [x] Preserve selected Low priority.
- [x] UPDATE priority from Low to High.
- [x] Require explicit approval for UPDATE.
- [x] GET request and verify High priority.
- [x] CANCEL request after explicit approval.
- [x] GET request and verify Cancelled status.
- [x] LIST requests including cancelled records.
- [x] Return the correct Power BI policy requirements.

**Result: Expected lifecycle outcomes observed.**

Policy answer was correct; File Search execution during the final test still needs separate trace verification.

---

## 3. Previously Tested Behaviors

- [x] Agent generates a request title from natural language.
- [x] Missing priority is requested rather than defaulted.
- [x] Request fields remain available across follow-up turns.
- [x] User can revise priority before submission.
- [x] User can decline request creation.
- [x] Semantic duplicate check identifies a possible Power BI duplicate.
- [x] Request status can be retrieved using an email and resource description.
- [x] Request status can be retrieved using an exact request ID.
- [x] Historical listing includes closed records.
- [x] Natural conversation ending does not undo previous actions.

---

## 4. Known Issues and Limitations

- [ ] Improve repeated requester-name clarification.
- [ ] Capture File Search traces for the policy Q&A test.
- [ ] Evaluate semantic duplicate accuracy with a labeled dataset.
- [ ] Expand tests for malformed agent output.
- [ ] Expand adversarial and prompt-injection tests.
- [ ] Add real identity authentication.
- [ ] Add record-level authorization.
- [ ] Add stronger concurrency and transactional safeguards.
- [ ] Add production-grade audit logging and monitoring.

Unchecked items represent future improvements, not completed tests.

---

## 5. Regression Checklist for Future Changes

After modifying the application, verify:

1. CREATE with missing priority.
2. CREATE with all required details.
3. User revision before confirmation.
4. Explicit approval.
5. Rejected or declined submission.
6. UPDATE an active request.
7. GET the updated record.
8. CANCEL with confirmation.
9. GET a cancelled record.
10. Attempt to modify a closed request.
11. LIST all records for a fictional email.
12. Named-resource status lookup by email.
13. Semantic duplicate blocking.
14. RAG question answering with retrieval trace.
15. Malformed structured response recovery.

For live tests, use fictional data and avoid creating unnecessary duplicate records.

---

## 6. Safety Checks

- [x] Ordinary writes require explicit confirmation.
- [x] Read-only GET and LIST do not require write-style confirmation.
- [x] Database results are verified after successful writes.
- [x] No automatic retry of uncertain database writes.
- [x] Duplicate-check failure blocks creation.
- [x] Closed requests are protected from ordinary modifications.

### Production Requirements Not Yet Implemented

- [ ] Enforced authenticated identity.
- [ ] Record-level access control.
- [ ] Transactional prevention of concurrent duplicates.
- [ ] Comprehensive audit logging.
- [ ] Deployment monitoring.
- [ ] Formal security testing.

---

## 7. Final Assessment

The request-management prototype passed eight automated orchestration tests and demonstrated the complete selected live request lifecycle.

The results support presenting it as a functioning local multi-agent AI portfolio project.

They do not establish production readiness, enterprise authorization, or guaranteed model accuracy.
