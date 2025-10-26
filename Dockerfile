FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (git for backups)
RUN apt-get update && apt-get install -y \
    git \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY *.py .
COPY templates templates/
COPY workers workers/
COPY scripts scripts/
COPY ml ml/
COPY migrations migrations/

# Make scripts executable
RUN chmod +x scripts/*.sh || true

# Create backup directory
RUN mkdir -p /app/backups

# Expose ports
EXPOSE 9900 9901 9902 9903 9905

# Run the server
CMD ["python", "app.py"]
