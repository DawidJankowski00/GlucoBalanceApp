# 0005. One service writes settings and logs every change

- Status: accepted
- Date: 2026-10-09

## Context

Settings (targets, ICR and ISF blocks, maximum bolus) drive dosing numbers, and the safety rules require every change to be logged with who, when, old value, new value and source. Two screens edit them (the onboarding wizard and the settings page), and later the assistant will propose changes the user accepts.

## Decision

- All writes go through `settings_service.apply_settings`, which validates first and then saves.
- It writes one `settings_changes` row per field that actually changed: user, changed-by user, time (UTC), field, old value, new value and a source (`onboarding`, `user`, `assistant_suggestion`). Time blocks are logged as one readable text value. An unchanged field logs nothing.
- Values are stored as text so one table covers every kind of setting. Old and new values are never rewritten.
- Validation bounds (for example a low target of 54 to 140 mg/dL, an action time of 2 to 8 hours, a maximum bolus of at most 50 units) live in one function, so the wizard and the settings page cannot disagree.
- Feature flags come from a single pure function, `features.feature_flags`, which every screen and reminder asks instead of reading the raw switches.

## Consequences

- The history page is a plain query, and later stages (the review period, assistant suggestions) reuse the same log.
- Text values lose type information, which is acceptable because the log is for people to read and for audit, not for computing.
- Validation bounds are a product decision; widen them with a new ADR if a clinician needs values outside them.

## Alternatives considered

- **Database triggers or ORM events:** record changes automatically, but cannot know who made them or through which source.
- **Keep only the latest settings:** simpler, but breaks the "log every change" safety rule.
