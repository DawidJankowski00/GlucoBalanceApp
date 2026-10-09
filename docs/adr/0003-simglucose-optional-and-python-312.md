# 0003. simglucose as an optional dependency group, and Python pinned to 3.12

- Status: accepted
- Date: 2026-10-09

## Context

Demo data and later the CGM simulator adapter come from simglucose (UVA/Padova T1D simulator). It is unmaintained: it imports the old `gym` package, which needs `distutils` and `pkg_resources`. It fails on Python 3.14 and on setuptools 70 or newer. It also pulls in pandas, matplotlib and gym, and simulates about 12 seconds per day.

## Decision

- Pin the project to Python 3.12 with a committed `.python-version`, matching CI and the Docker image.
- Put simglucose (with `setuptools<70`) in an optional `sim` dependency group: `uv run --group sim python -m glucobalance.seed`.
- Keep the simulator behind `glucobalance.seed.simulate()`; everything that turns its output into app data is plain Python tested with fake data, so tests, CI and the Docker image never install it.

## Consequences

- CI and the app image stay small and fast.
- Seeding 30 days takes about 6 minutes.
- If simglucose stops installing, only the seed script (and later the simulator adapter) is affected; a small built-in simulator could replace it behind the same function.
- The basal-bolus controller is close to ideal (time in range near 100%), so demo data is cleaner than real life.

## Alternatives considered

- **A built-in simple simulator:** no fragile dependency, but less realistic and more code to own.
- **simglucose as a normal dependency:** would put gym and matplotlib in the app image and break on newer Python.
