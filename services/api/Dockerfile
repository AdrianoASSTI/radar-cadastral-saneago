# Contexto de build: ./services (para incluir o pacote compartilhado `comum`)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Sao_Paulo

WORKDIR /app

COPY api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY comum /opt/comum
RUN pip install --no-cache-dir /opt/comum

COPY api/app ./app
COPY api/scripts ./scripts
COPY api/tests ./tests

RUN useradd --create-home --uid 10001 radar
USER radar

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/saude', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
