#!/bin/bash

echo "⏳ Waiting for database..."
until python3 -c "import socket; socket.create_connection(('$HOST', $PORT), timeout=1)" 2>/dev/null; do
  echo "Database not ready, waiting..."
  sleep 1
done
echo " Database is ready!"

# Navegar al directorio de Django
cd /app/core

echo "🔄 Applying migrations..."
python3 manage.py migrate --noinput

echo "📦 Collecting static files..."
python3 manage.py collectstatic --noinput --clear

echo "🚀 Starting Daphne ASGI server..."
exec "$@"