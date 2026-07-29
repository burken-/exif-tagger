# ============================================================================
# exif-tagger – Multi-stage build for web dashboard service
# Stage 1: Build Python dependencies (fast, cached)
# Stage 2: Install system tools + runtime image
# ============================================================================

FROM python:3.12-alpine AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# Final image – minimal Alpine with exiftool for XPTags support
FROM python:3.12-alpine

WORKDIR /app

# Install exiftool via apk (pre-built, avoids CPAN test failures)
RUN apk add --no-cache perl exiftool

# Copy Python dependencies from builder stage
COPY --from=builder /install /usr/local

# Copy application source and install as package so imports resolve
COPY src/ ./src/
COPY webui/ ./webui/
COPY config.yaml.example ./config.yaml.example
COPY pyproject.toml .

RUN pip install -e . --no-cache-dir && \
    mkdir -p /data/images /app/data /app/config

# Expose dashboard port
EXPOSE 8080

# Run FastAPI server via uvicorn
ENTRYPOINT ["uvicorn", "src.exif_tagger.server:app", "--host", "0.0.0.0", "--port", "8080"]
