#!/bin/sh
set -e

echo "Waiting for PostgreSQL at ${POSTGRES_HOST:-postgres}:${POSTGRES_PORT:-5432}..."
until python -c "
import os, socket
s = socket.socket()
s.settimeout(2)
try:
    s.connect((os.environ.get('POSTGRES_HOST', 'postgres'), int(os.environ.get('POSTGRES_PORT', '5432'))))
except OSError:
    raise SystemExit(1)
" 2>/dev/null; do
    sleep 1
done

echo "Applying migrations..."
python manage.py migrate --noinput

exec "$@"
