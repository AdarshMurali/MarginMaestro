FROM python:3.11-slim-bookworm AS builder

WORKDIR /build

# unixodbc-dev + build-essential: pyodbc may need to compile against ODBC
# headers if no prebuilt wheel matches this platform. msodbcsql18 itself
# (the actual driver, not just the Python binding) is also needed here so
# `pip install .[db,...]` can complete any driver-dependent build/import
# checks -- and again in the final stage, since it's a separate filesystem.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gnupg build-essential unixodbc-dev \
    && curl -sSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -sSL https://packages.microsoft.com/config/debian/12/prod.list | tee /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml ./
COPY src ./src

# db: SQLAlchemy/pyodbc for the orchestrator's positions/collateral/reference-rate
# reads. llm: LangGraph/OpenAI for the orchestrator + CSA-RAG agent. streaming:
# confluent-kafka (not used by the API directly yet, but agents.orchestrator
# transitively imports streaming.event_agent for latest_close_before, which
# imports streaming.market_feed -> yfinance, hence `data` too). rag: chromadb
# for the CSA-RAG agent's retriever, which transitively imports
# rag.s3_upload -> boto3 (aws extra), even though the API never calls it.
# notify: slack-sdk for the Communication Agent (MM-41).
RUN pip install --no-cache-dir ".[db,llm,streaming,rag,aws,data,notify]"


FROM python:3.11-slim-bookworm

# Runtime needs the actual ODBC driver (msodbcsql18) + unixodbc runtime libs --
# pyodbc dynamically loads these at connection time, not at import time.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gnupg unixodbc \
    && curl -sSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -sSL https://packages.microsoft.com/config/debian/12/prod.list | tee /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && apt-get purge -y --auto-remove curl gnupg \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash appuser

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
