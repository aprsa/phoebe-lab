# PHOEBE Lab Docker Image

FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install phoebe-client from GitHub
RUN pip install --no-cache-dir git+https://github.com/aprsa/phoebe-client.git

# Copy and install phoebe-lab
COPY pyproject.toml README.md ./
COPY lab/ ./lab/
COPY static/ ./static/
RUN pip install --no-cache-dir .

# Expose port 80 (internal; will be mapped to external port)
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:80/ || exit 1

# Run lab
CMD ["phoebe-lab"]
