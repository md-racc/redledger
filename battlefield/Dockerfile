# battlefield — also runs mock agents via a different command. Owner: Dev Ad.
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_SYSTEM_PYTHON=1
RUN pip install --no-cache-dir uv
WORKDIR /app

COPY agentkit/ /app/agentkit/
COPY battlefield/pyproject.toml /app/battlefield/pyproject.toml
RUN cd /app/battlefield && uv pip install --system -e ../agentkit && uv pip install --system -e . 2>/dev/null || true

COPY battlefield/ /app/battlefield/
COPY contracts/schema.sql /app/battlefield/db/schema.sql
COPY contracts/ext/ /app/battlefield/db/ext/
RUN cd /app/battlefield && uv pip install --system -e .

WORKDIR /app/battlefield
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
