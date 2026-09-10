# Alternativa de deploy (Railway, Fly.io, Google Cloud Run, qualquer host Docker)
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=5000 VOLTGUARD_DB_DIR=/data MQTT_BROKER=broker.hivemq.com
RUN mkdir -p /data
EXPOSE 5000
CMD gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 120
