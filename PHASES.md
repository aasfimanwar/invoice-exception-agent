# Phases and approval log

I review and approve each phase. After every phase: summary, test and eval results, peak memory,
open risks. Do not start the next phase before approval.

| # | Phase | Acceptance | Status | Approved on |
|---|---|---|---|---|
| 0 | Requirements, taxonomy, policy document, ADRs | approved | drafted, awaiting approval | |
| 1 | Synthetic data generator, mock APIs, labelled eval set | suite committed | not started | |
| 2 | Single-agent baseline with eval | baseline report | not started | |
| 3 | Multi-agent graph with checkpointing and tracing | tests pass | not started | |
| 4 | Confidence scoring and escalation threshold | calibration report | not started | |
| 5 | Approval UI and audit trail | demo works | not started | |
| 6 | Ablations: single vs multi-agent, with/without verifier | table with CIs | not started | |
| 7 | MCP integration (wrapper inside this repo) | parity with direct tools | not started | |
| 8 | Security tests, docs, CLAIMS.md | README complete | not started | |

Full eval runs happen only at the end of Phases 2, 4 and 6, with prompts and tool schemas frozen.
