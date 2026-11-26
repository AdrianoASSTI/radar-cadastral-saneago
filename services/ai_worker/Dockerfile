# Contexto de build: ./services. Imagem compartilhada pelo worker de IA e pelos experimentos.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Sao_Paulo \
    OMP_NUM_THREADS=1 \
    YOLO_OFFLINE=1 \
    YOLO_CONFIG_DIR=/tmp/ultralytics \
    MPLCONFIGDIR=/tmp/matplotlib

# libGL/glib: exigidos pelo OpenCV puxado como dependência do Ultralytics
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# PyTorch SÓ CPU: ~1,5 GB menor que a versão com CUDA (roda em notebook sem GPU)
RUN pip install --no-cache-dir torch==2.15.0 torchvision==0.29.2 --index-url https://download.pytorch.org/whl/cpu

COPY ai_worker/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY comum /opt/comum
RUN pip install --no-cache-dir /opt/comum

COPY ai_worker/app ./app
COPY ai_worker/modelos ./modelos

RUN useradd --create-home --uid 10001 radar && mkdir -p /data/imagens /data/quarentena /data/acervo /models /tmp/ultralytics \
    && chown -R radar /data /models /tmp/ultralytics
USER radar

CMD ["python", "-m", "app.worker"]
