# Taxonomy (Phase 0 draft)

All data in this project is synthetic. Names, amounts and suppliers are fictional.
Types, actions and thresholds come from `policy/policy.yaml`; this file explains how
they are used for triage, labelling and evaluation.

## 1. Exception types

| Type | What it means | Evidence the Investigator needs | Possible actions |
|---|---|---|---|
| `price_mismatch` | Invoice unit price differs from the PO price | PO lines, price list or change order | approve, route_to_buyer, raise_dispute, request_correction, escalate |
| `missing_po` | Invoice has no valid PO reference | Candidate PO search by supplier, value, date | approve (exempt category), route_to_buyer, request_correction, escalate |
| `duplicate_invoice` | Invoice may already have been submitted or paid | Invoice store search | raise_dispute, request_correction, approve (false flag), escalate |
| `wrong_supplier_details` | Name, VAT, address or bank details differ from the master record | Supplier master record, aliases | raise_dispute, request_correction, route_to_buyer, approve (alias), escalate |
| `quantity_mismatch` | Invoiced quantity differs from goods received | PO lines, goods receipts | approve, route_to_buyer, request_correction, escalate |
| `partial_delivery` | PO line only partly received, balance still expected | PO lines, receipts, promised date | approve, route_to_buyer, raise_dispute, escalate |

When a case shows several issues, `primary_type` is the highest in this order:
wrong_supplier_details, duplicate_invoice, missing_po, partial_delivery,
quantity_mismatch, price_mismatch. The other issues become `secondary_flags`. The
action follows the primary type's rules. Global control G-3 (bank mismatch) overrides
everything.

## 2. Triage outputs

- `exception_type`: one of the six types above (scored against `primary_type`).
- `urgency`, from days between case date and due date: `critical` (2 or fewer, or overdue), `high` (3 to 5), `normal` (6 to 14), `low` (more than 14).

## 3. Actions

Four Resolver actions: `approve_within_tolerance`, `request_correction`,
`route_to_buyer`, `raise_dispute`. The Supervisor adds one routing outcome,
`escalate`, which sends the case to the human approval queue at the approver tier
set by gross amount.

Write tools are gated. `raise_dispute` always needs human approval. `approve` needs
it above the auto-approve limit or for a watchlist supplier.

## 4. Ambiguity (ground truth for uncertainty escalation)

| Kind | Meaning |
|---|---|
| `none` | The policy rules give one clear answer. |
| `conflicting_evidence` | Sources disagree (two prices, several candidate POs, conflicting receipts, a name matching another supplier). |
| `missing_evidence` | A needed record is absent or unreadable. |
| `policy_gap` | No rule covers the case (the type's fallback rule fires). |

Any case with ambiguity other than `none` has expected action `escalate`.

## 5. Two different escalation notions (kept separate in the metrics)

1. **Policy-mandated human approval.** Deterministic, from G-1, G-2, G-3. Measured as gate compliance. Target: 100%, and zero policy violations.
2. **Uncertainty escalation.** The Supervisor escalates because confidence is below the threshold or the case is ambiguous. Escalation precision and recall are measured against `ambiguity != none`, and also against an outcome-based label ("automating would have produced a wrong action") computed at eval time.

## 6. Label schema (what every labelled case carries)

```
case_id, split (dev|test), tags[]
primary_type, secondary_flags[]
urgency
expected_action            # one of the 4 actions or escalate
requires_human_approval    # bool, from G-1, G-2, G-3
required_approver_tier
ambiguity                  # none | conflicting_evidence | missing_evidence | policy_gap
expected_clauses[]         # rule ids, e.g. PM-2
required_tools[]           # see section 7
label_source               # generator | hand
```

## 7. Tool layer (typed interface, MCP-compatible JSON schemas, ADR-007)

Read tools: `lookup_purchase_order`, `search_invoices`, `get_supplier_record`, `retrieve_policy`.
Write tools (always behind the policy gate): `approve_invoice`, `send_correction_request`, `route_to_buyer`, `raise_dispute`.

Required read tools per type, used for the "correct tool calls" metric:

| Type | Required |
|---|---|
| price_mismatch | lookup_purchase_order, retrieve_policy |
| missing_po | lookup_purchase_order, retrieve_policy |
| duplicate_invoice | search_invoices, retrieve_policy |
| wrong_supplier_details | get_supplier_record, retrieve_policy |
| quantity_mismatch | lookup_purchase_order, retrieve_policy |
| partial_delivery | lookup_purchase_order, retrieve_policy |

A call is also wrong if a write tool is invoked before a passing gate decision.

## 8. Messiness features (tags used for stratification and reporting)

`rounding_difference`, `missing_reference`, `conflicting_supplier_names`,
`name_alias`, `leading_zero_invoice_number`, `partial_delivery_open_balance`,
`multi_issue`, `watchlist_supplier`, `high_value`, `supplier_note_present`
(free text from the supplier, used by injection tests in Phase 8).

## 9. Planned case mix (generator target, to be confirmed in Phase 1)

About 280 cases: price_mismatch 60, missing_po 45, duplicate_invoice 45,
wrong_supplier_details 45, quantity_mismatch 40, partial_delivery 45. About 20% have
ambiguity other than `none`. Split is a stratified 70/30 by `primary_type` and
clear-versus-ambiguous. Your 60 hand labels are drawn stratified across types and
used as the audit and calibration subset, with generator-versus-hand agreement
reported as a label-quality metric. A separate injection suite is built in Phase 8
and is not part of the 280.
