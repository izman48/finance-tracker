# Remote MCP server (streamable HTTP). Runs as its own container — it only
# talks to the REST API, so it carries none of the API's dependencies.

FROM python:3.12-slim AS runtime
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py config.py auth.py api_client.py ./
RUN useradd --create-home --shell /bin/bash appuser
USER appuser
ENV MCP_TRANSPORT=http \
    PYTHONUNBUFFERED=1
EXPOSE 8001
CMD ["python", "server.py"]

# Test image: the runtime plus pytest and the tests. Never deployed.
FROM runtime AS test
USER root
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY conftest.py pytest.ini ./
COPY tests ./tests
USER appuser
CMD ["pytest", "-q"]
