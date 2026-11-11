FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH" \
    FASTEMBED_CACHE_PATH=/opt/fastembed_cache
# Dependencies first so the layer is cached until pyproject.toml changes.
COPY pyproject.toml README.md ./
RUN mkdir -p src/nlagent && touch src/nlagent/__init__.py && uv sync --no-install-project
COPY . .
RUN uv sync
