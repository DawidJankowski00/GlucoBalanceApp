# 0002. SQLAlchemy 2, Alembic and a repository layer for persistence

- Status: accepted
- Date: 2026-10-09

## Context

GBA stores glucose, insulin, carbs, sites, reminders and settings. It runs on PostgreSQL in Docker and in production, and on in-memory SQLite in tests and CI. The schema will grow with every stage, and real users must keep their data across upgrades. Times come from phones, CGM servers and a simulator in different timezones.

## Decision

- **SQLAlchemy 2 ORM** with typed `Mapped[...]` columns, so mypy strict checks database code too.
- **Alembic** migrations, generated from the models and reviewed by hand. A test upgrades a fresh database and fails if the migrations and models differ. The Docker image runs `alembic upgrade head` on start.
- **Repository classes** (`glucobalance.repositories`) are the only place that builds queries. They flush but never commit; the caller owns the transaction.
- **Rules in the database:** check constraints (positive values, target range order), a unique (user, source, time) key on readings so imports are idempotent, and `ON DELETE CASCADE` from users.
- **Units and time:** glucose is stored as whole mg/dL; every timestamp goes through a `UTCDateTime` column type that rejects naive datetimes and always returns UTC.
- **Choices as text:** enums are stored as readable strings (`native_enum=False`), so adding a value needs no PostgreSQL `ALTER TYPE`.

## Consequences

- Tests run fast on SQLite while production uses PostgreSQL; the migration test and a manual PostgreSQL run cover the differences.
- Every model change needs a migration (`alembic revision --autogenerate`), which the test enforces.
- Routes, analytics and the assistant depend on repository methods, not SQL, so they are easy to test with fakes.

## Alternatives considered

- **SQLModel:** less code, but thinner typing and documentation for relationships and migrations.
- **Raw SQL or SQLAlchemy Core only:** full control, but more mapping code and no relationships.
- **`Base.metadata.create_all()` without migrations:** fine for a prototype, but cannot upgrade an existing database without losing data.
