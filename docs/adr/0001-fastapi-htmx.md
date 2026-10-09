# 0001. FastAPI + HTMX instead of a React front end

- Status: accepted
- Date: 2026-10-09

## Context

GBA needs a phone-friendly UI (installable as a PWA) with forms, charts and a body map. It is a solo, Python-focused project that should cost nothing to run.

## Decision

Build the UI server-side with FastAPI, Jinja2 templates and HTMX, styled with Tailwind, and served as a PWA.

## Consequences

- One language and one deployable app; no separate JavaScript build or API-versioning layer.
- Forms and partial page updates are simple; rich client-side interactivity (the body map, charts) uses small amounts of JavaScript or SVG.
- Fewer front-end skills are showcased, in exchange for a smaller, easier-to-understand codebase.

## Alternatives considered

- **React (or similar SPA) with a JSON API:** more flexible UI but doubles the tooling and moves effort away from the Python/AI focus of the project.
