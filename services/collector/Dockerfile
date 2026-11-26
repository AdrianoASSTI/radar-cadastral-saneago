# Contexto de build: ./services
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=America/Sao_Paulo

WORKDIR /app
COPY collector/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY comum /opt/comum
RUN pip install --no-cache-dir /opt/comum
COPY collector/app ./app

RUN useradd --create-home --uid 10001 radar && mkdir -p /data/quarentena /data/acervo && chown -R radar /data
USER radar

CMD ["python", "-m", "app.worker"]
