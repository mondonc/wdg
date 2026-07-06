FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Admin static files, baked into the image (whitenoise serves them).
# WDG_DEBUG=1 only relaxes the SECRET_KEY requirement for this build step.
RUN WDG_DEBUG=1 python manage.py collectstatic --noinput

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
# Workers scale via the standard WEB_CONCURRENCY env (gunicorn default: 1).
CMD ["gunicorn", "wdg_server.wsgi:application", "--bind", "0.0.0.0:8000"]
