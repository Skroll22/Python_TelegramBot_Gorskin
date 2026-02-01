#!/bin/sh
set -e

echo "=== Checking Python environment ==="
python check_python.py
echo "==================================="

echo "Waiting for database..."
while ! nc -z postgres 5432; do
  sleep 0.5
done
echo "Database is ready!"

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"