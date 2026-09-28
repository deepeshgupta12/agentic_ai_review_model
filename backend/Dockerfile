# Backend image for api, worker, scheduler and db-setup (Step 03.3).
# Built from the repository root so contracts/, seed/, prompts/ and evals/ are included.
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.2 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH

WORKDIR /srv/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
RUN uv sync --frozen --no-dev

COPY contracts /srv/contracts
COPY seed /srv/seed
COPY prompts /srv/prompts
COPY evals /srv/evals

RUN useradd --system --uid 10001 --no-create-home app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
