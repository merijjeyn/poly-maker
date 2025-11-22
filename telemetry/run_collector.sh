#!/bin/bash

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
  echo "Error: Docker is not running or not installed."
  exit 1
fi

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Load environment variables from .env file if it exists (check root dir as well)
if [ -f "$SCRIPT_DIR/../.env" ]; then
  export $(grep -v '^#' "$SCRIPT_DIR/../.env" | xargs)
elif [ -f "$SCRIPT_DIR/.env" ]; then
  export $(grep -v '^#' "$SCRIPT_DIR/.env" | xargs)
fi

# Check for credentials
if [ -z "$CLICKHOUSE_HOST" ] || [ -z "$CLICKHOUSE_PORT" ] || [ -z "$CLICKHOUSE_USER" ] || [ -z "$CLICKHOUSE_PASSWORD" ]; then
  echo "Error: ClickHouse credentials not found in environment variables."
  echo "Please set CLICKHOUSE_HOST, CLICKHOUSE_PORT, CLICKHOUSE_USER, and CLICKHOUSE_PASSWORD."
  exit 1
fi

echo "🚀 Starting OpenTelemetry Collector..."
docker run --rm -p 4317:4317 -p 4318:4318 \
  -v "$SCRIPT_DIR/otel-collector-config.yaml":/etc/otel-collector-config.yaml \
  -e CLICKHOUSE_HOST=$CLICKHOUSE_HOST \
  -e CLICKHOUSE_PORT=$CLICKHOUSE_PORT \
  -e CLICKHOUSE_USER=$CLICKHOUSE_USER \
  -e CLICKHOUSE_PASSWORD=$CLICKHOUSE_PASSWORD \
  otel/opentelemetry-collector-contrib:latest \
  --config=/etc/otel-collector-config.yaml
