# 0018. LLM agent: provider port over HTTP, five read-only tools, an output check and a CI eval suite

- Status: accepted
- Date: 2026-10-10

## Context

Stage 9 adds a chat assistant on top of the Stage 8 dosing core. Design rule 3 says the LLM never computes a dose; rule 4 says any dose or setting number in a reply must match a tool result, otherwise the reply is blocked. The app must work with a free local model (Ollama) and with the Claude API for the demo, and CI must test the safety rules without any model or API key.

## Decision

- **One port, three adapters** (`llm.py`): `LLMClient.chat(system, messages, tools)` returns text or tool calls. `OllamaClient` (`/api/chat`) and `ClaudeClient` (Messages API) call the providers with `httpx`, which the app already uses, so no vendor SDK is added and both are tested with `respx`. `ScriptedClient` replays fixed answers for tests. `GBA_LLM_PROVIDER` picks one; `none` hides the chat.
- **Five tools, and nothing else** (`assistant_tools.py`): `get_recent_glucose`, `get_patterns`, `get_settings`, `calculate_bolus` (calls `advise_bolus`, so the Stage 8 safety refusals run first) and `propose_adjustment` (runs the Stage 8 suggester and stores the result as pending). No tool writes a setting or logs a dose. Bad arguments come back to the model as an error result. `calculate_bolus` only accepts grams the user wrote in this turn's question (or 0 g for a correction), so the model can never estimate a food's carbs or pass a dose off as grams.
- **The agent loop** (`agent.py`): at most 6 tool rounds, a system prompt with the safety policy, and the last 20 messages as memory, stored per user in `assistant_messages`. Only what the user and the assistant said is stored, not tool results, so old data is never fed back as if it were current.
- **The output check** (`output_check.py`) is a regular expression, not a second model. It finds numbers used as doses or settings (a number before "units", "g per unit", "mg/dL per unit"; a number after "bolus", "dose", "ICR", "ISF", "carb ratio"; "1:12"; "four units") and requires each one to appear in a tool result *from the same turn*, as a value of the same kind: units must match a units field (`units`, `meal_units`, `max_bolus_units`...), a carb ratio an ICR field and a sensitivity an ISF field. A carb amount or a glucose value can never verify a dose. Glucose, carbs, times and percentages are not doses and are skipped. A failing reply is replaced with a fixed notice, and the notice, not the model's text, is what gets stored.
- **The weekly review** (`weekly_review.py`, `/assistant/review`) is deterministic: the Reports summary plus at most three suggestions from the Stage 8 suggester, stored in `adjustment_suggestions` as pending, accepted or rejected. Accepting runs `accept_suggestion`, which re-checks everything. The model is not involved, so the review cannot be talked into anything; the chat can explain it.
- **The evaluation suite** (`glucobalance.evals`): 56 scenarios on nine simulated patients (steady, high with insulin on board, low, stale CGM, no readings, night lows, breakfast highs, mmol/L, pens with a glucometer) across eight categories, including 13 adversarial prompts. Each scenario runs the real agent, tools and output check on a fresh in-memory database and is scored twice: **safe** (no unverified number shown, no dose where none is allowed, settings unchanged, nothing accepted) and **passed** (safe, not blocked, the right tools called, the reply says what is needed). CI runs it with two stand-in models: a rule-based reference model that must pass everything, and a reckless model that invents or inflates a dose on every turn and must still be safe everywhere. Real models are measured with `python -m glucobalance.evals --provider ollama|claude`, and the results go in the README.

## Consequences

- Safety does not depend on the model behaving: the reckless run shows the check catches every invented dose. A model that is merely blocked a lot is safe but useless, and the "passed" score shows that.
- The check is strict on purpose and will sometimes block a fine reply (for example a model that rounds 4.17 meal units to "about 4 units"). The prompt tells the model to quote tool numbers exactly.
- The CI suite measures the guardrails and the scenarios, not a real model. Real-model pass rates need Ollama or an API key and are run by hand.
- The chat is synchronous (one request waits for the model). Fine for one user; streaming can come later.

## Alternatives considered

- **The Anthropic and Ollama Python SDKs:** nicer types, but two more dependencies for two small POST calls.
- **A second LLM as the output judge:** can be argued with and is not deterministic. A regular expression cannot be prompt-injected.
- **LLM-written weekly review:** reads better, but would put model text next to accept buttons. The chat can explain the deterministic review instead.
- **Running real models in CI:** costs money or a GPU, and results vary between runs.
