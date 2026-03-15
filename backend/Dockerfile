FROM python:3.12-slim

WORKDIR /app

# Copy backend files
COPY backend/pyproject.toml .
COPY backend/scanner/ scanner/
COPY backend/payloads/ payloads/
COPY backend/main.py .

# Install dependencies
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" anthropic websockets python-dotenv httpx stagehand

# Expose port
EXPOSE 8000

# Railway sets PORT env var
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
