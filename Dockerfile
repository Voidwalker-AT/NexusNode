# ==============================================================================
# NexusNode Mobile Server Appliance — Production Dockerfile
# Engineered for high-efficiency, bounded memory workloads (Vault, Media, AI)
# ==============================================================================

FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NEXUS_HOST=0.0.0.0 \
    NEXUS_PORT=5000 \
    NEXUS_STORAGE_DIR=/app/storage_vault \
    NEXUS_EMERGENCY_LOG=/app/logs/emergency_fallback.log

# Install required runtime system packages: FFmpeg, curl (for healthcheck), procps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    procps \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user and group
RUN groupadd -g 1000 nexus && \
    useradd -u 1000 -g nexus -s /bin/bash -m nexus

WORKDIR /app

# Install Python dependencies first for caching efficiency
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Create storage and log directories with proper permissions
RUN mkdir -p /app/storage_vault /app/logs && \
    chown -R nexus:nexus /app

# Copy application source code
COPY --chown=nexus:nexus . /app/

# Ensure runtime directories are owned by nexus user
RUN chown -R nexus:nexus /app/storage_vault /app/logs

# Switch to non-root user
USER nexus

# Expose primary WSGI server port
EXPOSE 5000

# Container healthcheck testing /api/health
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/api/health || exit 1

# Production Entrypoint
CMD ["python", "app.py"]
