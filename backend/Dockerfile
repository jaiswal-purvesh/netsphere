FROM docker.io/library/python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libpq5 curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd --system --uid 10001 --no-create-home netsphere && chown -R netsphere /app
USER netsphere

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
