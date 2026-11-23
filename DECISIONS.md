# Decisions (ADR log)

Format: context, decision, rejected alternatives, consequences. Status was `proposed` until Aasfi approved Phase 0 on 2026-11-22.

---

## ADR-001: One machine-readable policy file is the source of truth

**Status:** accepted 2026-11-22

**Context:** Labels, the written policy and the runtime gate must never disagree.

**Decision:** `policy/policy.yaml` holds parameters, named predicates, ordered rules and global controls. Predicates are implemented once in a pure-Python policy engine. The generator labels cases with it, the gate enforces it at runtime, and `docs/POLICY.md` is rendered from it. CI fails if POLICY.md drifts.

**Rejected:** (a) a hand-written policy document plus separate constants in code (drift); (b) policy only in prompts (not testable, not enforceable); (c) a full rules DSL (over-engineered for this scope).

**Consequences:** The gate and the labels share code, so an engine bug would affect both. Mitigation: golden unit tests per rule and the hand-labelled audit subset (ADR-002).

## ADR-002: Labels come from the generator, audited by hand labels

**Status:** accepted 2026-11-22

**Decision:** The 250-300 case set is labelled by the policy engine from the injected exception. Aasfi hand-labels 60 stratified cases as an audit and calibration subset. Generator-versus-hand agreement is reported as a label-quality metric. Split is stratified 70/30 by primary type and clear-versus-ambiguous. The test split stays locked until the final report.

**Rejected:** (a) hand-labelling only the 60 and evaluating on about 18 test cases (confidence intervals too wide); (b) LLM-assigned labels (circular).

**Consequences:** Ambiguous and messy cases must be generated deliberately, or generator labels will look better than reality. Disagreements with hand labels are logged in LEARNINGS.md.

## ADR-003: LITE and FULL model profiles

**Status:** accepted 2026-11-22

**Decision:** LITE is small hosted models with BM25-only policy retrieval. FULL is larger hosted models, plus an optional local bge-small embedder and MiniLM reranker only if it measurably helps. Results are reported in separate tables, with exact model names, versions and run dates in RESULTS.md.

**Rejected:** local LLMs (8 GB RAM, no usable GPU); mixing profiles in one table.

**Model plan (accepted 2026-11-22, read from the consoles; see docs/QUOTAS.md):** LITE uses Gemini 3.1 Flash Lite. FULL uses Gemma 4 31B if a capability probe shows it handles tool calling and structured JSON; otherwise Gemini 3.5 Flash Lite plus the optional embedder and reranker. Exact names, versions and dates go in RESULTS.md. No model is adopted until the probe passes.

**Consequences:** Free-tier model availability can change. Profiles are defined by role, with the current model plan recorded here and in QUOTAS.md.

## ADR-004: Provider roles and judge independence

**Status:** accepted 2026-11-22

**Decision:** Gemini is the primary system under test. Groq is the second provider and an alternate system under test in an ablation. The judge is always from a different model family than the system under test in that run. Roles are pinned per run, failover is disabled during eval runs, and roles are recorded in run metadata. Programmatic graders (decision, tool calls, policy violations) come first; a judge scores only free-text rationale quality.

**Rejected:** judge-for-everything (cost, quota, self-preference bias); automatic failover mid-eval (contaminates the comparison).

**Scope (accepted 2026-11-22):** When Gemini or Gemma is under test, the judge is Groq `openai/gpt-oss-120b`, run only on the 60 hand-labelled cases. The Groq alternate system under test is `gpt-oss-120b`, single-agent only, on a stratified 30-case subset, spread over several days. When Groq is under test, the judge is a Gemini Flash-Lite model.

**Consequences:** Judge calls count against quota. Groq requests must stay well under about 6K tokens because of its 8K tokens-per-minute limit.

## ADR-005: Record and replay for every LLM call

**Status:** accepted 2026-11-22

**Decision:** All LLM calls go through one provider interface. Each request is hashed over provider, model, full messages, tool schemas and decoding parameters. CI replays recordings and fails on a miss with "re-record required". Replay runs do not export traces.

**Rejected:** live calls in CI (quota, flakiness); keying on prompt text only (misses schema and parameter changes).

**Consequences:** Any prompt, schema or parameter change invalidates recordings, so prompts and schemas are frozen before milestone runs (ADR-006).

## ADR-006: Free-tier budget rules and quota snapshot

**Status:** accepted 2026-11-22 (revised from the original per-run 25% cap)

**Context:** The consoles show tight free limits. A per-run cap of 25% of the smallest daily limit would allow only a handful of cases per run. Because of record/replay (ADR-005), each case is paid for once per configuration and later runs are free.

**Decision:** Quota use is capped per calendar day, not per run: at most about 50% of the binding daily limit (requests or tokens) of any provider per day. Recording runs checkpoint and resume the next day until every case is recorded. Development uses a 30-case dev subset. Full runs happen only at the end of Phases 2, 4 and 6, with prompts and schemas frozen. Requests per day are tracked in docs/QUOTAS.md. Only synthetic data is allowed, because free tiers may use inputs to improve products.

Quota snapshot (read from the consoles on 2026-11-22, details in docs/QUOTAS.md):
- Gemini free tier: 3.1 and 3.5 Flash Lite allow 15 requests/min, 250K tokens/min, 500 requests/day. Flash-class models allow 20 requests/day. Gemma 4 26B and 31B allow 30 requests/min, 16K tokens/min, 14.4K requests/day. Pro models have no free allowance.
- Groq free plan: gpt-oss-120b, gpt-oss-20b and qwen3.8-27b allow 30 requests/min, 1K requests/day, 8K tokens/min, 200K tokens/day.
- Langfuse Cloud Hobby: 50,000 units per month (secondary sources, to confirm in the console).

**Rejected:** a per-run 25% cap (cannot complete an evaluation); relying on unpublished numbers.

**Consequences:** Full recordings take several calendar days per configuration. Limits can change without notice, so each milestone run re-reads them.

## ADR-007: Tool layer is a typed interface; MCP wrapper is built in this repo

**Status:** accepted 2026-11-22

**Decision:** Tools are typed Python callables with JSON schemas whose names, descriptions and input schemas are MCP-compatible. Phase 7 builds a thin MCP wrapper inside this repo with parity tests against the direct tools. The Project 4 servers do not exist and are not a dependency.

**Rejected:** depending on unbuilt Project 4 servers; MCP-first from Phase 1 (adds a process and memory cost on an 8 GB machine before it is needed).

**Consequences:** If a separate MCP project exists by Phase 7, Aasfi will say so and this ADR is revisited.

## ADR-008: Deterministic write gate

**Status:** accepted 2026-11-22

**Decision:** Write tools cannot be called except through a gate implemented in code, using the policy engine (G-1 to G-7). Idempotency keys come from case id, action and payload hash. Supplier-provided text is data and never reaches outbound messages except as structured fields.

**Rejected:** prompt-only safety; a gate that trusts the model's own claim of policy approval.

## ADR-009: Observability and state

**Status:** accepted 2026-11-22

**Decision:** OpenTelemetry spans exported to Langfuse Cloud Hobby; SQLite checkpointer for LangGraph state. Trace export is on for live milestone runs and off for replay and routine dev runs, to stay inside 50,000 units per month.

**Rejected:** self-hosted Langfuse (memory on an 8 GB machine); Postgres checkpointer (extra service).

## ADR-010: Cost metric is notional list price

**Status:** accepted 2026-11-22

**Decision:** Cost per resolved case is token counts multiplied by published list prices. The price table and its date are stored in RESULTS.md. It is labelled "notional cost at list price", since actual spend is zero.

**Rejected:** reporting zero cost; estimating tokens instead of using counted ones.

---

## ADR-011: Free tier only, time over money

**Status:** accepted 2026-11-22

**Context:** Aasfi approved the plan on the condition that everything stays on free tiers, even if it takes longer.

**Decision:** No paid plan, billing setup or card-required step is used at any point. The "Set up billing" and "Upgrade" options on Google AI Studio and Groq are never used. If the work cannot be completed within free limits, the order of response is: spread recording over more days, shrink the number of ablation arms, shrink the generated case count, and only then ask Aasfi whether to change scope. Money is never the answer.

**Rejected:** paid tiers for speed; credits that require a card.

**Consequences:** Calendar time is the main cost. The README states plainly that results describe small free-tier models.

---

## ADR-012: Cases are structured JSON only (no PDF or OCR)

**Status:** accepted 2026-11-22

**Context:** Real invoices arrive as PDFs and images. Handling them needs OCR or a vision model, which is outside the brief and would use free-tier quota that the evaluation needs.

**Decision:** Every case, invoice, purchase order, receipt and supplier record is structured JSON. The only free text is `supplier_note` on invoices and a vague `system_message` on cases. Supplier text is data and is never treated as an instruction (G-5), which is what the Phase 8 injection tests use.

**Rejected:** generating PDFs and running OCR; image-based invoices; a vision-model extraction stage.

**Consequences:** The system is evaluated on reasoning, tool use and policy, not on document extraction. The README states this limitation.

## ADR-013: Hand-labelling happens before Phase 4

**Status:** accepted 2026-11-22

**Context:** Nothing in Phases 2 and 3 depends on the 60 hand labels. Confidence calibration (Phase 4) does.

**Decision:** Aasfi hand-labels the 60 stratified audit cases after Phase 3 and before Phase 4 starts. Until then, results in Phases 2 and 3 use generator labels only and make no calibration claims. The hand-label kit (labelling sheet with generator labels hidden, plus an agreement script) is built in Phase 1 so it is ready.

**Rejected:** labelling at the end of Phase 1 (delays Phase 2 for no benefit); labelling after Phase 4 (calibration would be unaudited).

**Consequences:** Generator-versus-hand agreement is reported when it becomes available. Phase 2 and 3 reports say so explicitly.

## ADR-014: Policy engine design

**Status:** accepted 2026-11-22

**Context:** ADR-001 requires one implementation of every predicate, shared by the generator labels and the runtime write gate.

**Decision:** `policy_engine.py` implements the 28 predicates in one registry. Construction fails if the registry and `policy/policy.yaml` differ. Money is `Decimal` with half-up rounding to pence; no floats. Name similarity uses the standard library (`difflib`) so there is no extra dependency. The engine resolves a case from its declared issue types: it applies the precedence order, makes a bank-detail mismatch primary (G-3), takes the first matching rule, and derives urgency, approver tier, human-approval need, expected clauses and required tools. `policy.yaml` gained data-only fields for the tool lists and required tools per type (version 1.0.1; no rule changed).

**Rejected:** a rules DSL; float arithmetic; a fuzzy-matching library (rapidfuzz) for one threshold.

**Consequences, found while testing:**
- The fallback rules MP-9, DU-9 and QM-9 cannot fire, because earlier rules already cover every case. Only SD-9 and PD-9 are reachable policy gaps, and PM has no fallback.
- No rule produced the `missing_evidence` ambiguity kind. Resolved by ADR-015.
- Multi-line interpretations were made explicit: a partial-delivery invoice "matches received" when every invoiced line equals its received quantity and at least one line is partial; "full order while partial" is the same with ordered quantity.

## ADR-015: missing_evidence rules

**Status:** accepted 2026-11-22 (requested by Aasfi)

**Context:** ADR-014 found that nothing produced the `missing_evidence` ambiguity kind. A case whose supplier record cannot be read must not be decided automatically, because the bank and VAT checks cannot run.

**Decision:** Two predicates and nine rules were added (policy version 1.1.0). `supplier_record_unavailable` (record missing or flagged unreadable) is the first rule of every exception type: `PM-E1`, `MP-E1`, `DU-E1`, `SD-E1`, `QM-E1`, `PD-E1`. `po_record_unavailable` (the PO the invoice cites cannot be found) is the second rule of the types that need a PO: `PM-E2`, `QM-E2`, `PD-E2`. All escalate with ambiguity `missing_evidence`. An unreadable supplier record can never trigger the bank-mismatch override (G-3), because it cannot be verified.

**Rejected:** dropping the kind; a code-only guard with no rule id (the rule would be invisible to the evaluation and to retrieval).

**Consequences:** `QM-9` (invoice lines that match no PO line) is a reachable policy gap. Known remaining gap: a price-mismatch case whose invoice lines match no PO line falls through to `PM-6` (request correction) because price mismatch has no policy-gap fallback. Logged for review, not changed.

## ADR-016: Seeded generator, verified against the final world

**Status:** accepted 2026-11-23

**Context:** ADR-002 needs about 280 labelled cases whose labels cannot drift from the policy, with deliberate messiness and about 20% ambiguity.

**Decision:** `generator.py` builds each case from a randomised base (supplier, PO, receipts, invoice) and a recipe aimed at one policy rule. Labels come only from the policy engine. All cases share one world, so after assembly every case is re-resolved against the final world, and any case whose rule no longer matches its intent is redrawn until the set is stable. Everything is deterministic for a given seed (default 20260122). The case mix is a rule-level table (`TARGETS`) that covers every reachable rule, with 23% ambiguous cases. Roughly 1 in 5 numeric edge cases sit exactly on a tolerance or window boundary (tag `boundary_case`). Agent-visible cases (`cases.jsonl`) and labels (`labels.jsonl`) are separate files, and the manifest records SHA-256 hashes so a test fails if the committed data no longer matches the generator and the policy version.

**Rejected:** hand-written fixtures (too few, biased toward what I thought of); generating labels from recipes (would not catch engine bugs); one world per case (hides cross-case interference that real data has).

**Consequences:** Labels and gate share the engine (ADR-001), so the 60 hand labels (ADR-013) are the independent check. Synthetic realism is limited: structured fields only (ADR-012), one currency, one VAT rate. Case values are log-uniform from 30 to 10,000 GBP per line; about half of invoices exceed the auto-approve limit.
