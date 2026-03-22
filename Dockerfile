# --- Stage 1: Build Frontend ---
FROM node:20-slim AS frontend-builder
WORKDIR /build
COPY web_dashboard/package*.json ./web_dashboard/
RUN cd web_dashboard && npm install
COPY web_dashboard/ ./web_dashboard/
RUN cd web_dashboard && npm run build

# --- Stage 2: Final Image ---
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=.

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    libpq-dev \
    gcc \
    curl \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy built frontend assets from Stage 1
COPY --from=frontend-builder /build/web_dashboard/dist ./web_dashboard/dist

# Metadata
LABEL maintainer="Antigravity OSINT Team"
LABEL version="MVP-v28-Unified"

# Default command
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
