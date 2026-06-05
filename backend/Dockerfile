# Multi-stage build for production backend
# Stage 1: Build dependencies
FROM python:3.12-slim AS builder

# Use Aliyun Debian mirror for faster downloads in China
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|http://deb.debian.org|http://mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null || true

# Install build tools and system deps (ffmpeg from apt)
# Retry up to 5 times for flaky networks
RUN for i in 1 2 3 4 5; do \
        apt-get update && \
        apt-get install -y --no-install-recommends \
            fonts-noto-cjk \
            ffmpeg \
            curl \
        && rm -rf /var/lib/apt/lists/* \
        && break || sleep 10; \
    done && (command -v ffmpeg && command -v curl) || (echo "ERROR: Required packages not installed after retries" && false)

# Verify ffmpeg installation
RUN ffprobe -version

# Install Python dependencies
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.12-slim AS runtime

# Copy system deps from builder
COPY --from=builder /usr/share/fonts /usr/share/fonts
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages

# Use Aliyun mirror for runtime deps too
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|http://deb.debian.org|http://mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null || true

# Install runtime system deps
# ffmpeg installed via apt (not copied) to pull in all shared libraries
# libgl1 replaces libgl1-mesa-glx in Debian Trixie
RUN for i in 1 2 3 4 5; do \
        apt-get update && \
        apt-get install -y --no-install-recommends \
            ffmpeg \
            libgl1 \
            libglib2.0-0 \
            libsm6 \
            libxext6 \
            libxrender-dev \
            libfontconfig1 \
            curl \
        && rm -rf /var/lib/apt/lists/* \
        && break || sleep 10; \
    done && (command -v ffmpeg && command -v ffprobe && command -v curl) || (echo "ERROR: Required packages not installed after retries" && false)

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app
COPY --chown=appuser:appuser . .

# Create data directory with write permissions
RUN mkdir -p /app/data && chown -R appuser:appuser /app/data

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=20s \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
