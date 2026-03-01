FROM python:3.11-slim

WORKDIR /app

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml uv.lock ./
RUN uv sync --all-extras --no-dev

# Copy source and ontologies
COPY src/ ./src/
COPY ontology/ ./ontology/

ENV PYTHONPATH=/app/src

EXPOSE 8100

CMD ["uv", "run", "python", "-m", "ontology_server", "--http", "--host", "0.0.0.0", "--port", "8100"]
