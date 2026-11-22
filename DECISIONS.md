# Decisions (ADR log)

Format: context, decision, rejected alternatives, consequences. Status is `proposed`
until Aasfi approves Phase 0.

---

## ADR-001: One machine-readable policy file is the source of truth

**Status:** proposed

**Context:** Labels, the written policy and the runtime gate must never disagree.

**Decision:** `policy/policy.yaml` holds parameters, named predicates, ordered rules and global controls. Predicates are implemented once in a pure-Python policy engine. The generator labels cases with it, the gate enforces it at runtime, and `docs/POLICY.md` is rendered from it. CI fails if POLICY.md drifts.

**Rejected:** (a) a hand-written policy document plus separate constants in code (drift); (b) policy only in prompts (not testable, not enforceable); (c) a full rules DSL (over-engineered for this scope).

**Consequences:** The gate and the labels share code, so an engine bug would affect both. Mitigation: golden unit tests per rule and the hand-labelled audit subset (ADR-002).

## ADR-002: Labels come from the generator, audited by hand labels

**Status:** proposed

**Decision:** The 250-300 case set is labelled by the policy engine from the injected exception. Aasfi hand-labels 60 stratified cases as an audit and calibration subset. Generator-versus-hand agreement is reported as a label-quality metric. Split is stratified 70/30 by primary type and clear-versus-ambiguous. The test split stays locked until the final report.

**Rejected:** (a) hand-labelling only the 60 and evaluating on about 18 test cases (confidence intervals too wide); (b) LLM-assigned labels (circular).

**Consequences:** Ambiguous and messy cases must be generated deliberately, or generator labels will look better than reality. Disagreements with hand labels are logged in LEARNINGS.md.

## ADR-003: LITE and FULL model profiles

**Status:** proposed

**Decision:** LITE is small hosted models with BM25-only policy retrieval. FULL is larger hosted models, plus an optional local bge-small embedder and MiniLM reranker only if it measurably helps. Results are reported in separate tables, with exact model names, versions and run dates in RESULTS.md.

**Rejected:** local LLMs (8 GB RAM, no usable GPU); mixing profiles in one table.

**Consequences:** Free-tier model availability can change. Profiles are defined by role, not by a model name hard-coded in this ADR.

## ADR-004: Provider roles and judge independence

**Status:** proposed

**Decision:** Gemini is the primary system under test. Groq is the second provider and an alternate system under test in an ablation. The judge is always from a different model family than the system under test in that run. Roles are pinned per run, failover is disabled during eval runs, and roles are recorded in run metadata. Programmatic graders (decision, tool calls, policy violations) come first; a judge scores only free-text rationale quality.

**Rejected:** judge-for-everything (cost, quota, self-preference bias); automatic failover mid-eval (contaminates the comparison).

**Consequences:** The judge family for a Gemini run is a Groq-hosted model; for a Groq run it is a Gemini model. Judge calls count against quota.

## ADR-005: Record and replay for every LLM call

**Status:** proposed

**Decision:** All LLM calls go through one provider interface. Each request is hashed over provider, model, full messages, tool schemas and decoding parameters. CI replays recordings and fails on a miss with "re-record required". Replay runs do not export traces.

**Rejected:** live calls in CI (quota, flakiness); keying on prompt text only (misses schema and parameter changes).

**Consequences:** Any prompt, schema or parameter change invalidates recordings, so prompts and schemas are frozen before milestone runs (ADR-006).

## ADR-006: Free-tier budget rules and quota snapshot

**Status:** proposed

**Decision:** A single eval run may use at most about 25% of the smallest daily limit of any provider it uses. Development uses a 30-case dev subset. Full runs happen only at the end of Phases 2, 4 and 6, with prompts and schemas frozen. Runs checkpoint and resume the next day. Requests per day are tracked against the limits below. Only synthetic data is allowed, because free tiers may use inputs to improve products.

Quota snapshot (checked 2026-11-16; secondary sources, must be confirmed in each provider console):
- Groq free plan, sample limits for gpt-oss-120b and one Qwen model: 30 requests/min, 1,000 requests/day, 8,000 tokens/min, 200,000 tokens/day, applied per organisation.
- Langfuse Cloud Hobby: 50,000 units per month, 30 days data access, 2 users. Units are traces plus observations plus scores.
- Gemini free tier: **unverified**. Sources disagree and Google's page says per-model values are shown in AI Studio. Aasfi to supply the AI Studio limits table before Phase 1 starts.

**Open issue:** Groq's token cap (200,000/day) binds long before its request cap, so "25% of the daily limit" must be applied to the binding dimension. That means a Groq eval run over the test split is a multi-day job. Decision requested from Aasfi.

**Rejected:** relying on one provider's unpublished numbers; unlimited dev runs against the full set.

## ADR-007: Tool layer is a typed interface; MCP wrapper is built in this repo

**Status:** proposed

**Decision:** Tools are typed Python callables with JSON schemas whose names, descriptions and input schemas are MCP-compatible. Phase 7 builds a thin MCP wrapper inside this repo with parity tests against the direct tools. The Project 4 servers do not exist and are not a dependency.

**Rejected:** depending on unbuilt Project 4 servers; MCP-first from Phase 1 (adds a process and memory cost on an 8 GB machine before it is needed).

**Consequences:** If a separate MCP project exists by Phase 7, Aasfi will say so and this ADR is revisited.

## ADR-008: Deterministic write gate

**Status:** proposed

**Decision:** Write tools cannot be called except through a gate implemented in code, using the policy engine (G-1 to G-7). Idempotency keys come from case id, action and payload hash. Supplier-provided text is data and never reaches outbound messages except as structured fields.

**Rejected:** prompt-only safety; a gate that trusts the model's own claim of policy approval.

## ADR-009: Observability and state

**Status:** proposed

**Decision:** OpenTelemetry spans exported to Langfuse Cloud Hobby; SQLite checkpointer for LangGraph state. Trace export is on for live milestone runs and off for replay and routine dev runs, to stay inside 50,000 units per month.

**Rejected:** self-hosted Langfuse (memory on an 8 GB machine); Postgres checkpointer (extra service).

## ADR-010: Cost metric is notional list price

**Status:** proposed

**Decision:** Cost per resolved case is token counts multiplied by published list prices. The price table and its date are stored in RESULTS.md. It is labelled "notional cost at list price", since actual spend is zero.

**Rejected:** reporting zero cost; estimating tokens instead of using counted ones.
