FROM python:3.11-slim

WORKDIR /app

# Install Docker CLI (for scaling services)
RUN apt-get update && apt-get install -y \
    curl \
    && curl -fsSL https://get.docker.com | sh \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code explicitly
COPY scaler.py /app/scaler.py
COPY nginx_manager.py /app/nginx_manager.py

# Verify files are copied (for debugging)
RUN ls -la /app/

# Run the scaler
CMD ["python", "/app/scaler.py"]
