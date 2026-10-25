# blue agent — Droid SDK service. Owner: Dev M (contents) / Dev Ad (base shape).
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/root/.local/bin:/root/.factory/bin:${PATH}"
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates git && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv
# Droid CLI. VERIFY this install line against docs.factory.com on first build and record the
# working command in contracts/CHANGELOG.md (Findings). The SDK needs `droid` on PATH.
# Blue runs live (#157): a missing CLI must fail the build, not ship silently (a cached fallback layer once
# shipped blue without the SDK while red had it).
RUN curl -fsSL https://app.factory.ai/cli | sh && command -v droid
WORKDIR /app
COPY agentkit/ /app/agentkit/
COPY blue/pyproject.toml /app/blue/pyproject.toml
RUN cd /app/blue && uv pip install --system -e "../agentkit[droid]" && python -c "import droid_sdk"
COPY blue/ /app/blue/
RUN cd /app/blue && uv pip install --system -e . && python -c "import droid_sdk"
WORKDIR /app/blue
EXPOSE 8003
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8003"]
