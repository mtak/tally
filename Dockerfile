FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN groupadd --gid 10001 tally && useradd --uid 10001 --gid tally --create-home tally
COPY . .
RUN mkdir -p /data /backups && chown tally:tally /data /backups
RUN python manage.py collectstatic --noinput
ARG TALLY_GIT_COMMIT=""
ENV TALLY_GIT_COMMIT=${TALLY_GIT_COMMIT}
LABEL org.opencontainers.image.revision=${TALLY_GIT_COMMIT}
ENV TALLY_DATA_DIR=/data
USER tally
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 1 --threads 4 --access-logfile -"]
