# 0008. Food search behind an adapter, favourite meals and the hypo log

- Status: accepted
- Date: 2026-10-09

## Context

Stage 3 adds carb logging with a food search, favourite meals and a hypo log. A food database is an outside service: it can be slow, down or wrong, and tests must not call it.

## Decision

- **Open Food Facts** is the food source. The app depends on a small `FoodSource` Protocol (`search(query) -> list[Food]`), and `OpenFoodFacts` is one implementation using `httpx`. `httpx` therefore moved from the dev group to the runtime dependencies. Tests pass a fake source, or an `httpx.MockTransport`, so no test uses the network.
- **Cache:** `CachedFoodSource` wraps any source with an in-memory cache (one hour, 200 entries, oldest dropped first). Failures are never cached. The cache is per process; it is lost on restart, which is fine for a search box.
- **Failure is normal:** any network, status or format problem becomes a `FoodSearchError` with a plain message, and the page tells the user to enter the carbs by hand. Foods without a carb value are skipped. The results carry a reminder that the data can be wrong.
- **Search never fills in a number silently:** picking a food opens the normal carb form with the carbs for the chosen portion prefilled (`carbs_for_portion`). The user still checks and saves, so every entry goes through the same rules (1 to 300 g, duplicate check).
- **Favourite meals** (`FavouriteMeal`, unique name per user, at most 50) store a name and grams. "Log now" runs the normal carb checks, including the duplicate guard.
- **Hypo log** (`HypoTreatment`) records what was taken, optional carbs and a note. A treatment with carbs also creates a carb entry, so the timeline and the later IOB and carb-on-board maths see it. The nearest reading in the previous 30 minutes is linked as the low that was treated. The app only records; it does not tell the user how much to take. The page reminds them to recheck in 15 minutes, and glucagon points to emergency help.

## Consequences

- If Open Food Facts is down, only the search box is affected.
- Cached results can be up to an hour old, which is acceptable for food data.
- Switching to another food database means writing one class that satisfies `FoodSource`.

## Alternatives considered

- **Calling the API directly in the route:** simpler, but untestable offline and hard to replace.
- **A database table as cache:** survives restarts, but adds a migration and cleanup for little gain.
- **Redis:** one more service to run for a single search box.
