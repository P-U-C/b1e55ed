# Multi-stage build for b1e55ed
FROM python:3.12-slim AS builder

# Install uv
RUN pip install --no-cache-dir uv

# Copy project files
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY engine ./engine
COPY api ./api
COPY dashboard ./dashboard
COPY README.md LICENSE ./

# Build wheel
RUN uv build

# Runtime image
FROM python:3.12-slim

# Install runtime dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    sqlite3 \
    curl \
    ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Create app user
RUN useradd -m -s /bin/bash b1e55ed

# Install uv
RUN pip install --no-cache-dir uv

# Copy wheel from builder
COPY --from=builder /app/dist/*.whl /tmp/

# Install package
RUN uv pip install --system /tmp/*.whl && rm /tmp/*.whl

# Copy config files
COPY config /app/config
COPY scripts /app/scripts

# Create data and log directories
RUN mkdir -p /data /logs && \
    chown -R b1e55ed:b1e55ed /data /logs /app

# Switch to app user
USER b1e55ed
WORKDIR /app

# Expose ports
EXPOSE 5050 5051

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5050/health || exit 1

# Default command (override in docker-compose)
CMD ["b1e55ed", "--help"]
