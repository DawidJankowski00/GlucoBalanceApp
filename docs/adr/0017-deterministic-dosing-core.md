# 0017. Dosing core: linear IOB, nearest-step bolus, safety refusals and capped suggestions

- Status: accepted
- Date: 2026-10-10

## Context

Stage 8 makes every dosing number the app can show come from plain, tested Python (design rules 3 and 4). Stage 9's LLM agent will only call these functions; it never computes a dose. The rules must be simple enough to check by hand and conservative where they have to guess.

## Decision

- **Insulin on board is linear** (`iob.py`): a rapid bolus or correction counts in full when taken and falls in a straight line to 0 at the insulin action time. Basal (long-acting, or pump basal) is left out, because the settings already account for it. Doses in the future are ignored.
- **The bolus** (`bolus.py`) is `carbs / ICR + max(0, (glucose - target) / ISF) - IOB`, floored at 0, rounded to the **nearest** dose step (a half step rounds up), then held at the max bolus rounded down to a whole step. A glucose under the target never shrinks the meal part: a low is refused before the calculator runs. The result keeps the unrounded parts so the user can see the sum.
- **The correction target** is the middle of the target range, rounded down (70 to 180 gives 125). It is conservative compared with a lower target, and needs no new setting yet.
- **Safety refusals** (`dosing_safety.py`) run before any number: no settings, no reading, a reading more than 15 minutes old (the same limit as the CGM stale alert), or a reading under 70 mg/dL. Each refusal has a reason the user can read, and no number is shown with it.
- **Adjustment suggestions** (`adjustments.py`) map the Stage 7 findings to one setting each: night lows raise the ISF of the block in force at 03:00, high fasting values lower it, and highs after breakfast lower the ICR of the block in force at breakfast (median peak time less two hours, on the local clock). A change is at most 10% of the current value, rounded towards no change (ICR to 0.1 g, ISF to 1 mg/dL), and stays within the settings page limits.
- **Lows win.** A block with a night-low pattern never gets a change that means more insulin.
- **One change per setting per review period:** a block's ICR or ISF that changed in the last 7 days, by anyone, gets no suggestion. The change log stores the whole block list as text, so it is compared block by block.
- **Suggestions only propose.** `accept_suggestion` re-checks the current value, the cap and the 7-day rule, then saves through `apply_settings` with the source `assistant_suggestion`.

## Consequences

- Linear IOB overstates insulin on board in the first hour and understates it near the end. With nearest-step rounding this is the usual trade-off of simple pump calculators; a curved model can replace `insulin_on_board` without touching its callers.
- Nearest-step rounding can round up by half a step (0.25 units on a 0.5 step). The max bolus still always holds.
- Night lows and fasting highs are often basal problems, which the app does not model; the suggestion's reason says so and points to the clinic.
- Onboarding counts as a change, so a new user gets no suggestions for their first week.

## Alternatives considered

- **A curved (exponential) IOB model:** closer to real insulin action, but harder to check by hand; left for later.
- **Always rounding down:** safer against overdosing but systematically underdoses on a 1-unit pen step. Nearest step with the cap was chosen.
- **A separate correction target setting:** more flexible; it can be added later without changing the calculator.
- **Letting the LLM pick the size of an adjustment:** rejected by design rule 3.
