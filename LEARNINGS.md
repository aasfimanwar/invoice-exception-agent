# Learnings

What broke and how it was fixed. One entry per problem, newest first.

Template:

## YYYY-MM-DD short title
- Symptom:
- Cause:
- Fix:
- Commit / run id:

## 2026-11-23 Name similarity was not symmetric
- Symptom: a generator test found two supplier names scoring above the 80 cutoff in one argument order but below it in the other.
- Cause: `difflib.SequenceMatcher.ratio()` can differ between (a, b) and (b, a), so a supplier name match could depend on which side was the invoice.
- Fix: `name_similarity` sorts the two normalised names before comparing, and a test checks symmetry over every pair in the supplier pool. The dataset was regenerated.
- Commit / run id: pending first commit of Phase 1 slice 3.

## 2026-11-23 First generated dataset made automation impossible
- Symptom: 271 of 280 invoices were above the 2,500 GBP auto-approve limit, so almost every approval needed a human and the gate would have hidden any benefit of the agent.
- Cause: uniform quantity (20 to 500) and unit price (2 to 400) per line gives invoice values in the tens of thousands.
- Fix: line values are log-uniform from 30 to 10,000 GBP. Now 79 approvals, of which 34 can be automated. A test fails if fewer than 10 can.
- Commit / run id: pending first commit of Phase 1 slice 3.

## 2026-11-22 A mutation check found an untested limit
- Symptom: changing the auto-approve limit from 2,500 to 2,400 left every engine test green.
- Cause: no test sat on that boundary.
- Fix: added a boundary test at exactly 2,500.00 and 2,500.01 GBP.
- Commit / run id: commit for the policy engine (feat: domain models and deterministic policy engine).
