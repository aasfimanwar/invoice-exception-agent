# Free-tier quotas

Keep this current. Numbers below were read from the provider consoles on 2026-11-22.
Limits can change without notice and differ by project; re-read before each milestone run.
Rule (ADR-006, under review): a run's budget is applied to the binding limit (requests or tokens).

## Gemini (Google AI Studio, Default Gemini Project, free tier, 28-day view)

Text-output models with a non-zero free limit. RPD resets at midnight Pacific.

| Model | RPM | TPM | RPD | Planned role |
|---|---|---|---|---|
| Gemini 3.1 Flash Lite | 15 | 250K | 500 | candidate LITE system under test |
| Gemini 3.5 Flash Lite | 15 | 250K | 500 | candidate LITE system under test |
| Gemini 2.5 Flash Lite | 10 | 250K | 20 | not used (20 RPD) |
| Gemini 2.5 Flash, 3 Flash, 3.6 Flash, 3.8 Flash, 4 Hydrogen | 5 | 250K | 20 | spot checks only (20 RPD) |
| Gemma 4 26B, Gemma 4 31B | 30 | 16K | 14.4K | candidate judge or FULL, tool support unverified |

Zero free limit (0 / 0 / 0): Gemini 2 Flash, Gemini 2 Flash Lite, Gemini 2.5 Pro, Gemini 3.1 Pro,
Gemini 4 Argon, Carbon and Neon. Other rows are image, audio, embedding or live models and are not
used. "Gemini Decision 1" (Decisions API, 200 RPM, 50K TPM, 10K RPD) is a different API category
and is not relied on.

Search grounding shows 1.5K RPD for older model families and 0 for Gemini 3 and newer.

## Groq (Personal organisation, Free plan, $0)

Models allowed in Default Project: openai/gpt-oss-120b, openai/gpt-oss-20b,
openai/gpt-oss-safeguard-20b, qwen/qwen3.8-27b, meta-llama/llama-prompt-guard-2-22m,
meta-llama/llama-prompt-guard-2-86m, whisper-large-v3, whisper-large-v3-turbo, and two
canopylabs/orpheus speech models. No custom project limits are set, so the organisation limits
apply.

Organisation limits for chat models, read on 2026-11-22 from console.groq.com/settings/limits
(no custom project limits are set):

| Model | RPM | RPD | TPM | TPD | Planned role |
|---|---|---|---|---|---|
| openai/gpt-oss-120b | 30 | 1K | 8K | 200K | judge, alternate system under test |
| openai/gpt-oss-20b | 30 | 1K | 8K | 200K | candidate judge |
| qwen/qwen3.8-27b | 30 | 1K | 8K | 200K | candidate judge |
| openai/gpt-oss-safeguard-20b | 3 | 1K | 2K | 200K | not used |
| meta-llama/llama-prompt-guard-2-22m and 86m | 30 | 14.4K | 15K | 500K | optional injection-detection baseline (Phase 8, needs approval) |
| allam-2-7b | 30 | 7K | 6K | 500K | not used |

The binding limits are tokens per minute (8K) and tokens per day (200K), not requests. A single
request larger than the per-minute budget is likely to be rejected, so Groq requests must stay well
under about 6K tokens. To be confirmed by the capability probe.

## Langfuse Cloud Hobby

50,000 units per month, 30 days data access, 2 users (secondary sources, confirm in the Langfuse
console). Units are traces, observations and scores. Trace export is off for replay and routine
dev runs.

## Daily usage log

| Date | Provider | Model | Requests | Tokens | Run id / purpose |
|---|---|---|---|---|---|
