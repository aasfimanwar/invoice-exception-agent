# Free-tier quotas

Keep this current. Confirm each number in the provider console before relying on it.
Rule (ADR-006): one eval run may use at most about 25% of the smallest daily limit of any
provider it uses, applied to the binding dimension (requests or tokens).

## Gemini (primary system under test)

Fill from Google AI Studio (rate limits table for your project). Reset time: midnight Pacific.

| Model | Free tier available | RPM | TPM | RPD | Date read |
|---|---|---|---|---|---|

## Groq (second provider, alternate system under test)

Sample limits seen for text models on 2026-11-16 via a secondary source. Confirm in the Groq
console limits page (limits apply per organisation).

| Model | RPM | RPD | TPM | TPD | Date confirmed in console |
|---|---|---|---|---|---|
| (to confirm) | 30 | 1,000 | 8,000 | 200,000 | |

## Langfuse Cloud Hobby

50,000 units per month, 30 days data access, 2 users. Units are traces, observations and scores.
Trace export is off for replay and routine dev runs.

## Daily usage log

| Date | Provider | Model | Requests | Tokens | Run id / purpose |
|---|---|---|---|---|---|
