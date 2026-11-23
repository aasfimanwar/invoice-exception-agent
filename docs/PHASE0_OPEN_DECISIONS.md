# Phase 0: decisions

Phase 0 was approved by Aasfi on 2026-11-22, on the condition that everything stays on free tiers
even if it takes longer (ADR-011).

- [x] Gemini limits read from AI Studio and recorded in docs/QUOTAS.md.
- [x] Groq limits read from the organisation Limits page and recorded in docs/QUOTAS.md.
- [x] Budget rule: per-calendar-day cap of about 50% of the binding limit, runs resume next day (ADR-006).
- [x] Model plan: LITE Gemini 3.1 Flash Lite; FULL Gemma 4 31B if the probe passes, else Gemini 3.5 Flash Lite plus embedder and reranker (ADR-003).
- [x] Groq alternate: gpt-oss-120b, single-agent only, stratified 30-case subset (ADR-004).
- [x] Policy parameters and rules accepted as in policy/policy.yaml v1.0.0.
- [x] Repo created and noreply email set.

Still to do before Phase 2:
- [ ] Confirm the GitHub Actions run is green (jobs `checks` and `secrets`).
- [ ] Put API keys in the local `.env` (never committed).
- [ ] Run the model capability probe (tool calling, structured JSON, oversized request behaviour).
- [ ] Confirm the Langfuse Hobby limits in the Langfuse console.
