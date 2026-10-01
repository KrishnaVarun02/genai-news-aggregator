FROM python:3.13.5-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.11.18 /uv /uvx /bin/
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
COPY src ./src
ARG WITH_DOCUMENTS=false
RUN if [ "$WITH_DOCUMENTS" = "true" ]; then uv sync --locked --no-dev --extra documents; else uv sync --locked --no-dev; fi
COPY config ./config
RUN mkdir -p /app/data /app/previews
CMD ["uv", "run", "--no-sync", "news", "run", "--mode", "fixture"]
