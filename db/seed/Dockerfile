FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Sao_Paulo

WORKDIR /seed
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY dados_referencia.py seed.py ./

# Usuário sem privilégios no contêiner
RUN useradd --create-home --uid 10001 seed
USER seed

CMD ["python", "seed.py"]
