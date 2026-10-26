FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:<версия> /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

COPY data ./data

ENV PATH="/app/.venv/bin:$PATH"

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "yapiko_test_assignment.main:app", "--host", "0.0.0.0", "--port", "8000"]