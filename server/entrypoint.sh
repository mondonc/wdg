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

# With several control-plane instances on one database, exactly one runs the
# migrations (the dedicated one-shot service); replicas set WDG_MIGRATE=0 and
# start once the schema is ready.
if [ "${WDG_MIGRATE:-1}" = "1" ]; then
    echo "Applying migrations..."
    python manage.py migrate --noinput
fi

exec "$@"
