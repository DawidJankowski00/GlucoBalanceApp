# 0010. Site blocks, preference weights and one rotation per purpose

- Status: accepted
- Date: 2026-10-09

## Context

Stage 4 suggests the next site for pump and pen users. The ranking itself is a pure function (`rotation.rank_sites`, written by the owner). Something has to decide which rotations a user keeps, how a site becomes unavailable, how preferences are stored and how the ranking gets its inputs.

## Decision

- **One rotation per purpose.** A pump user keeps one rotation (`infusion_set`); a pen user keeps two (`rapid_injection`, `long_injection`). `purposes_for()` reads this from the feature flags, so the pump/pens rule stays in `features.py`. Logging a purpose that does not match the user's mode is refused.
- **Blocks are rows with an optional end** (`site_blocks`: `blocked_at`, `until`, `reason`). `until = NULL` is permanent. A block is in force when `blocked_at <= now < until`. Unblocking sets `until` to now instead of deleting, so the history stays. Blocking a site again ends the current block and starts a new one. A block covers every purpose: a bruise is a bruise for any insulin.
- **Weights** (`site_preferences`, one row per user and site, 0 to 2, default 1 when no row) multiply the ranking score. 0 means avoid, and the ranking leaves the site out.
- **The service gathers, the function decides.** `site_service.site_states()` turns last uses, blocks at `now` and weights into `SiteState` values; `rank_sites()` never touches the database or the clock.
- **Rest period and set change interval are settings** (`site_rest_days`, default 14; `set_change_days`, default 3). Days until the next set change round up, so half a day left shows as 1 day.
- **Skipping is a page parameter** (`?skip_<purpose>=n`), not stored: the user can step through the ranked list without changing anything.

## Consequences

- The ranking can be tested with plain values, and the service with an in-memory database.
- The rest period and set change interval cannot be changed on the settings page yet; they use the defaults until that form is extended.
- A site removed from the body map would still be referenced by old blocks and uses; the map only grows for now.

## Alternatives considered

- **A `blocked` flag on a per-user site row:** simpler, but loses the end date and the history.
- **Deleting a block to unblock:** loses when and why a site was unavailable, which is useful when linking highs to overused areas.
