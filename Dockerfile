FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY uv.lock ./
COPY bibcleaner ./bibcleaner
COPY providers ./providers

RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "bibcleaner.web_api:app", "--host", "0.0.0.0", "--port", "8000"]
