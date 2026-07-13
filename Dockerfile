# ============================================================================
# exif-tagger – Multi-stage build
# Stage 1: Build Python dependencies (fast, cached)
# Stage 2: Install system tools (exiftool for XPTags support)
# ============================================================================

FROM python:3.12-alpine AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# Final image – minimal Alpine with exiftool installed via CPAN
FROM alpine:3.19

# Install perl (required for cpan) and basic tools, then exiftool
RUN apk add --no-cache \
    perl \
    perl-dev \
    build-base \
  && cpan -i Image::ExifTool \
  && rm -rf ~/.cpan /root/.cpan

WORKDIR /app

# Copy Python dependencies from builder stage
COPY --from=builder /install /usr/local

# Copy application source
COPY src/ ./src/
COPY config.yaml.example ./config.yaml.example

ENTRYPOINT ["python", "-m", "exif_tagger"]
CMD []
