# green agent — Droid SDK service. Owner: Dev M (contents) / Dev Ad (base shape).
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/root/.local/bin:/root/.factory/bin:${PATH}"
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates git && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv
# Droid CLI. VERIFY this install line against docs.factory.com on first build and record the
# working command in contracts/CHANGELOG.md (Findings). The SDK needs `droid` on PATH.
RUN curl -fsSL https://app.factory.ai/cli | sh || echo "WARN: droid CLI install failed; DRY_RUN still works"
WORKDIR /app
COPY agentkit/ /app/agentkit/
COPY green/pyproject.toml /app/green/pyproject.toml
RUN cd /app/green && uv pip install --system -e ../agentkit[droid] || uv pip install --system -e ../agentkit
COPY green/ /app/green/
RUN cd /app/green && uv pip install --system -e .
WORKDIR /app/green
EXPOSE 8002
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8002"]
