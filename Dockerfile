FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY uv.lock ./
COPY bibcleaner ./bibcleaner

RUN uv sync --frozen --no-dev

EXPOSE 8000

# Honor $PORT (Render/Railway inject it); default 8000 for local/docker-compose.
CMD ["sh", "-c", "uv run uvicorn bibcleaner.web_api:app --host 0.0.0.0 --port ${PORT:-8000}"]
