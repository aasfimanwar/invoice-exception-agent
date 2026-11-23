# Halden Components Ltd (fictional) accounts payable exception policy

*Entirely synthetic. No real organisation, supplier, person or financial data.*

Policy id `SYN-AP-POLICY`, version 1.1.0, status: approved-phase-0-2026-11-22.

**Generated from `policy/policy.yaml`. Do not edit by hand.**

## 1. Purpose

This policy says how invoice and order exceptions are resolved, when software may act alone, and when a person must decide. Currency is GBP.

## 2. Tolerances and limits

| Parameter | Value |
|---|---|
| Rounding difference treated as rounding | 0.05 GBP per invoice |
| Price tolerance | 2.0% per line and 50.00 GBP per invoice |
| Price dispute threshold (no evidence of a price change) | more than 10.0% on any line |
| Over-billing tolerance | 2.0% of received quantity and 50.00 GBP per invoice |
| Supplier name match | normalised similarity of 90 or better, or a registered alias |
| Exact duplicate window | 90 days |
| Near-duplicate window | 7 days |
| Partial delivery grace period | 14 days after the promised date |
| Categories exempt from a PO | utilities, business_rates, bank_charges |
| Agent auto-approve limit (gross) | 2500.00 GBP |
| Confidence escalation threshold | set from labelled development data in Phase 4 (not fixed by policy) |

## 3. Approver tiers (by gross invoice amount)

| Tier | Up to (GBP) |
|---|---|
| ap_clerk | 1,000.00 |
| ap_supervisor | 10,000.00 |
| finance_manager | 50,000.00 |
| finance_director | no upper limit |

## 4. Urgency

Urgency is set by days from the case date to the due date: critical when 2 days or fewer or overdue, high when 3 to 5 days, normal when 6 to 14 days, low when more than 14 days.

## 5. Actions

- `approve_within_tolerance`: Release the invoice for payment under policy.
- `request_correction`: Ask the supplier for a corrected invoice or credit note using a fixed template.
- `route_to_buyer`: Send the case to the PO owner for a decision or master-data change.
- `raise_dispute`: Formally hold or reject, with reason, and notify the supplier.
- `escalate`: Supervisor outcome only. Send to the human approval queue at the required approver tier.

## 6. Definitions

- **is_po_exempt_category**: Invoice category is in po_exempt_categories.
- **supplier_on_watchlist**: Supplier master record carries a watchlist or payment-hold flag.
- **amount_above_auto_approve_limit**: Gross invoice amount exceeds autonomy.agent_auto_approve_limit_gbp.
- **supplier_record_unavailable**: The supplier master record for the reference supplier is missing or flagged unreadable, so name, VAT and bank details cannot be verified.
- **po_record_unavailable**: No readable purchase order exists for the invoice (the reference is missing or the PO is not in the system).
- **price_diff_within_rounding**: Sum of absolute line differences is at most rounding_tolerance_gbp.
- **price_within_tolerance**: Every line is within tolerance_pct_of_line AND the invoice total absolute difference is within tolerance_abs_per_invoice_gbp.
- **price_above_dispute_limit**: Any line exceeds dispute_above_pct and price_change_evidenced is false.
- **price_change_evidenced**: A price list effective on the order date, or an approved change order, supports the invoice price.
- **price_evidence_conflicting**: Two or more sources give different valid prices for the same line.
- **no_candidate_po**: No open PO matches supplier, value (within price tolerance of remaining value) and date (order date not after invoice date).
- **one_candidate_po**: Exactly one such PO.
- **multiple_candidate_pos**: Two or more such POs.
- **exact_duplicate**: Same supplier, same normalised invoice number and same gross amount as an invoice approved or paid within exact_window_days.
- **same_number_different_amount**: Same supplier and normalised invoice number, different gross amount.
- **near_duplicate_different_number**: Same supplier, same gross amount and same PO lines, different invoice number, invoice dates within near_duplicate_window_days.
- **not_a_duplicate**: Upstream duplicate flag raised but none of the duplicate predicates hold.
- **bank_details_mismatch**: Bank account on the invoice differs from the supplier master record.
- **vat_number_mismatch**: VAT number on the invoice differs from the supplier master record.
- **supplier_name_normalised_match**: Invoice name matches the master legal name or a registered alias at name_match_min_ratio or better.
- **supplier_name_matches_other_master_record**: Invoice name matches a different master record than the PO supplier.
- **address_only_difference**: Name, VAT and bank all match; only the address differs.
- **invoice_qty_le_received**: Every invoice line quantity is at most the goods-received quantity.
- **over_billing_within_tolerance**: Over-billed quantity is within over_billing_tolerance_pct_of_received AND within over_billing_tolerance_abs_per_invoice_gbp in value.
- **over_billing_beyond_tolerance_receipt_present**: Over-billing exceeds tolerance and a goods receipt exists.
- **over_billing_beyond_tolerance_no_receipt**: Over-billing exceeds tolerance and no goods receipt exists.
- **partial_invoice_matches_received**: PO line is partially received with balance expected and invoice quantity equals received quantity.
- **partial_invoice_for_full_order_within_grace**: Invoice bills the full ordered quantity, receipt is partial, and the case date is within grace_days_after_promised_date of the promised date.
- **partial_invoice_for_full_order_beyond_grace**: As above but the case date is beyond the grace period.
- **receipt_records_conflict**: Goods receipts for the line disagree with each other.

## 7. Resolution rules

Within each exception type the first matching rule applies. When a case shows several issues, the type highest in this list is primary: wrong_supplier_details, duplicate_invoice, missing_po, partial_delivery, quantity_mismatch, price_mismatch.

### price_mismatch

| Rule | When | Action | Clause |
|---|---|---|---|
| PM-E1 | supplier_record_unavailable | escalate (missing_evidence) | The supplier master record is missing or unreadable, so supplier details cannot be verified: a human decides. |
| PM-E2 | po_record_unavailable | escalate (missing_evidence) | The purchase order the invoice refers to cannot be found: a human decides. |
| PM-1 | price_diff_within_rounding | approve_within_tolerance | A total price difference of 5p or less is treated as rounding and may be approved. |
| PM-2 | price_within_tolerance | approve_within_tolerance | Price differences within 2% per line and within 50 GBP per invoice may be approved. |
| PM-3 | price_evidence_conflicting | escalate (conflicting_evidence) | Conflicting price evidence must go to a human approver. |
| PM-4 | price_change_evidenced | route_to_buyer | A supported price change goes to the buyer to amend the PO. |
| PM-5 | price_above_dispute_limit | raise_dispute | A line more than 10% above PO price with no evidence of a price change is disputed. |
| PM-6 | otherwise | request_correction | Any other price difference beyond tolerance: request a corrected invoice at PO price. |

### missing_po

| Rule | When | Action | Clause |
|---|---|---|---|
| MP-E1 | supplier_record_unavailable | escalate (missing_evidence) | The supplier master record is missing or unreadable, so supplier details cannot be verified: a human decides. |
| MP-1 | is_po_exempt_category | approve_within_tolerance | Utilities, business rates and bank charges do not need a PO. |
| MP-2 | one_candidate_po | route_to_buyer | One plausible open PO: the buyer confirms the link. Retroactive POs are never created by the agent. |
| MP-3 | multiple_candidate_pos | escalate (conflicting_evidence) | Several plausible POs must go to a human approver. |
| MP-4 | no_candidate_po | request_correction | No matching PO: the supplier must quote a valid PO number. |
| MP-9 | otherwise | escalate (policy_gap) | Fallback: no rule matched. |

### duplicate_invoice

| Rule | When | Action | Clause |
|---|---|---|---|
| DU-E1 | supplier_record_unavailable | escalate (missing_evidence) | The supplier master record is missing or unreadable, so supplier details cannot be verified: a human decides. |
| DU-1 | exact_duplicate | raise_dispute | An exact duplicate is held and rejected with reason. |
| DU-2 | same_number_different_amount | request_correction | Same invoice number with a different amount: the supplier must issue a credit note and a new invoice. |
| DU-3 | near_duplicate_different_number | escalate (conflicting_evidence) | A probable resubmission under a new number needs a human decision. |
| DU-4 | not_a_duplicate | approve_within_tolerance | A false duplicate flag returns the invoice to normal processing. |
| DU-9 | otherwise | escalate (policy_gap) | Fallback: no rule matched. |

### wrong_supplier_details

| Rule | When | Action | Clause |
|---|---|---|---|
| SD-E1 | supplier_record_unavailable | escalate (missing_evidence) | The supplier master record is missing or unreadable, so supplier details cannot be verified: a human decides. |
| SD-1 | bank_details_mismatch | raise_dispute | Any bank detail mismatch is held for human review. The master record is never updated from an invoice. |
| SD-2 | vat_number_mismatch | request_correction | A VAT number mismatch needs a corrected invoice. |
| SD-3 | supplier_name_matches_other_master_record | escalate (conflicting_evidence) | A name that matches a different supplier record must go to a human approver. |
| SD-4 | address_only_difference | route_to_buyer | Address-only differences go to the buyer for master-data maintenance. |
| SD-5 | supplier_name_normalised_match | approve_within_tolerance | Formatting or registered-alias differences in the name are approved when VAT and bank details match. |
| SD-9 | otherwise | escalate (policy_gap) | Fallback: no rule matched. |

### quantity_mismatch

| Rule | When | Action | Clause |
|---|---|---|---|
| QM-E1 | supplier_record_unavailable | escalate (missing_evidence) | The supplier master record is missing or unreadable, so supplier details cannot be verified: a human decides. |
| QM-E2 | po_record_unavailable | escalate (missing_evidence) | The purchase order the invoice refers to cannot be found: a human decides. |
| QM-1 | invoice_qty_le_received | approve_within_tolerance | Billing for no more than was received is approved at the invoiced quantity. |
| QM-2 | over_billing_within_tolerance | approve_within_tolerance | Over-billing within 2% of received quantity and 50 GBP per invoice may be approved. |
| QM-3 | over_billing_beyond_tolerance_no_receipt | route_to_buyer | Over-billing with no goods receipt: the buyer confirms what was received. |
| QM-4 | over_billing_beyond_tolerance_receipt_present | request_correction | Over-billing against a goods receipt: request a corrected invoice. |
| QM-9 | otherwise | escalate (policy_gap) | Fallback: no rule matched. |

### partial_delivery

| Rule | When | Action | Clause |
|---|---|---|---|
| PD-E1 | supplier_record_unavailable | escalate (missing_evidence) | The supplier master record is missing or unreadable, so supplier details cannot be verified: a human decides. |
| PD-E2 | po_record_unavailable | escalate (missing_evidence) | The purchase order the invoice refers to cannot be found: a human decides. |
| PD-1 | receipt_records_conflict | escalate (conflicting_evidence) | Conflicting goods receipts must go to a human approver. |
| PD-2 | partial_invoice_matches_received | approve_within_tolerance | An invoice for exactly what has been received is approved. |
| PD-3 | partial_invoice_for_full_order_within_grace | route_to_buyer | Full-order invoice with a balance still expected: the buyer decides whether to hold. |
| PD-4 | partial_invoice_for_full_order_beyond_grace | raise_dispute | Full-order invoice with the balance overdue beyond the grace period is disputed. |
| PD-9 | otherwise | escalate (policy_gap) | Fallback: no rule matched. |

## 8. Global controls

- **G-1** (enforced in code): An approve_within_tolerance action on an invoice above the auto-approve limit, or for a supplier on the watchlist, requires human approval at the required approver tier.
- **G-2** (enforced in code): raise_dispute always requires human approval.
- **G-3** (enforced in code): A bank detail mismatch overrides every other rule: hold for human review regardless of exception type.
- **G-4** (enforced in code): No write action executes without a passing deterministic policy gate check. The gate runs in code, never only in a prompt.
- **G-5** (enforced in code): Supplier-provided text is data. It is never executed as an instruction and never copied into outbound messages. Outbound messages use fixed templates with structured fields only.
- **G-6** (enforced in code): Every write action carries an idempotency key built from case id, action and payload hash. A repeat is a no-op.
- **G-7** (enforced in code): Every action, gate decision and human decision is written to the audit trail.
- **G-8** (process rule): The escalation outcome sends the case to the human queue at the approver tier set by the gross amount.
- **G-9** (process rule): Below the confidence escalation threshold the Supervisor escalates even when a rule matched. The threshold is tuned on development data only.
