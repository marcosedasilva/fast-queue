FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY services/queue-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY libs/ /app/libs/

COPY services/queue-service/src/ /app/src/

COPY services/queue-service/firebase.json /app/firebase.json

ENV PYTHONPATH=/app

CMD uvicorn src.main:app --host 0.0.0.0 --port $PORT