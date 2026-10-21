# Scheduler image: all packages, no dev tools. Configs are baked in but can be mounted over.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true

RUN pip install "poetry>=2,<3"

WORKDIR /app
COPY pyproject.toml poetry.lock poetry.toml ./
COPY packages ./packages
RUN poetry install --without dev

COPY configs ./configs
ENV PATH="/app/.venv/bin:$PATH"

# Bring the schema up to date, then run the scheduler until stopped (SIGTERM is handled).
CMD ["sh", "-c", "synodtrade-db upgrade && exec synodtrade-scheduler run --configs /app/configs"]
