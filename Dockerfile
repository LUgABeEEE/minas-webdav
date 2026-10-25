# Docker image for the MCP server. Glama (and other registries) build this to
# run introspection; credentials and certificates are mounted at runtime and
# are never baked into the image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE NOTICE ./
COPY minas_webdav ./minas_webdav

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir ".[mcp]"

# stdio transport: the container is driven by an MCP client, not a port.
ENTRYPOINT ["minas-webdav-mcp"]