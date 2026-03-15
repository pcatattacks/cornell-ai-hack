FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml .
COPY scanner/ scanner/
COPY payloads/ payloads/
COPY main.py .
COPY .env.example .

RUN pip install --no-cache-dir fastapi "uvicorn[standard]" playwright anthropic websockets python-dotenv httpx stagehand

# Expose port
EXPOSE 8000

# Start the server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
