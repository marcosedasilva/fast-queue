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