FROM python:3.12-slim

# uv: the package manager used in this project (copied from its official image)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"

# Install dependencies first, so this layer is cached until the lock file changes
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# Then add the source and install the project itself
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# Train the glucose forecast on synthetic patients (seconds), so the image ships the model.
# The report goes to /tmp: the one in docs/forecast/ is the reviewed copy.
RUN python -m glucobalance.forecast --model-out /app/models/forecast.joblib --report /tmp/forecast-report.md
ENV GBA_FORECAST_MODEL_PATH=/app/models/forecast.joblib

EXPOSE 8000
# Bring the database schema up to date, then start the app
CMD ["sh", "-c", "alembic upgrade head && uvicorn glucobalance.main:app --host 0.0.0.0 --port 8000"]
