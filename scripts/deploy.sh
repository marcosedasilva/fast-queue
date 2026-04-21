#!/bin/bash

PROJECT_ID="fast-queue-493301"
REGION="southamerica-east1"
REPO_URL="$REGION-docker.pkg.dev/$PROJECT_ID/fast-queue"
VPC_CONNECTOR="fast-queue-vpc-final"

IP_DB="10.26.224.3"
IP_VM_INFRA="10.158.0.3"

DB_URL="postgresql+asyncpg://postgres:uHLiQ%260%23%28%24_G%2B*oG@$IP_DB:5432/fast_queue_db"
ORIGINS="https://fastq.site;https://fast-queue-493301.web.app"

echo "🚀 Iniciando Deploy do Ecossistema Fast Queue..."

gcloud auth configure-docker $REGION-docker.pkg.dev --quiet

# --- QUEUE SERVICE ---
echo "📦 Construindo Queue Service..."
docker build -t $REPO_URL/queue-service:v1 -f services/queue-service/Dockerfile .
docker push $REPO_URL/queue-service:v1
gcloud run deploy queue-service \
  --image $REPO_URL/queue-service:v1 \
  --region $REGION \
  --vpc-connector $VPC_CONNECTOR \
  --vpc-egress private-ranges-only \
  --set-env-vars "DATABASE_URL=$DB_URL,REDIS_URL=redis://$IP_VM_INFRA:6379,KAFKA_SERVER=$IP_VM_INFRA:9092,ALLOWED_ORIGINS=$ORIGINS,FIREBASE_ADMIN_SDK_PATH=/app/firebase.json,ENV=production" \
  --allow-unauthenticated --quiet

# --- PAYMENT SERVICE ---
echo "📦 Construindo Payment Service..."
docker build -t $REPO_URL/payment-service:v1 -f services/payment-service/Dockerfile .
docker push $REPO_URL/payment-service:v1
gcloud run deploy payment-service \
  --image $REPO_URL/payment-service:v1 \
  --region $REGION \
  --vpc-connector $VPC_CONNECTOR \
  --vpc-egress private-ranges-only \
  --set-env-vars "DATABASE_URL=$DB_URL,KAFKA_SERVER=$IP_VM_INFRA:9092,ALLOWED_ORIGINS=$ORIGINS,ENV=production" \
  --allow-unauthenticated --quiet

# --- SEARCH SERVICE ---
echo "📦 Construindo Search Service..."
docker build -t $REPO_URL/search-service:v1 -f services/search-service/Dockerfile .
docker push $REPO_URL/search-service:v1
gcloud run deploy search-service \
  --image $REPO_URL/search-service:v1 \
  --region $REGION \
  --vpc-connector $VPC_CONNECTOR \
  --vpc-egress private-ranges-only \
  --set-env-vars "ELASTICSEARCH_URL=http://$IP_VM_INFRA:9200,KAFKA_SERVER=$IP_VM_INFRA:9092,ALLOWED_ORIGINS=$ORIGINS,ENV=production" \
  --allow-unauthenticated --quiet

echo "✅ DEPLOY FINALIZADO COM SUCESSO!"