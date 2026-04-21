#!/bin/bash
echo "🚀 Iniciando Limpeza Geral do Fast Queue..."

docker-compose down -v
docker-compose up -d

echo "⏳ Aguardando bancos iniciarem (60s)..."
sleep 60

docker exec -it queue-service python src/create_tables.py
docker exec -it payment-service python src/create_tables.py
curl -X DELETE "http://localhost:9200/streamers"

curl -i -X POST -H "Accept:application/json" -H "Content-Type:application/json" localhost:8083/connectors/ -d '{
  "name": "fast-queue-connector-local",
  "config": {
    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
    "database.hostname": "postgres",
    "database.port": "5432",
    "database.user": "user",
    "database.password": "password",
    "database.dbname": "fast_queue_db",
    "topic.prefix": "dbserver1",
    "table.include.list": "public.queues",
    "plugin.name": "pgoutput",
    "slot.name": "fast_queue_local_slot"
  }
}'

echo "✅ Sistema pronto e limpo!"