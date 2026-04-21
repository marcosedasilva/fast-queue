FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY services/payment-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY libs/ /app/libs/

COPY services/payment-service/src/ /app/src/

ENV PYTHONPATH=/app

CMD uvicorn src.main:app --host 0.0.0.0 --port $PORT