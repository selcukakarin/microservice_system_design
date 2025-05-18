FROM python:3.10-slim-bullseye

RUN apt-get update \
  && apt-get install -y --no-install-recommends --no-install-suggests \
  build-essential ffmpeg \
  && pip install --no-cache-dir --upgrade pip

WORKDIR /app
COPY ./requirements.txt /app
RUN pip install --no-cache-dir --requirement /app/requirements.txt
COPY . /app

# Ortam değişkenlerini tanımla (varsayılan değerler)
ENV MONGODB_HOST=mongodb \
    MONGODB_PORT=27017 \
    RABBITMQ_HOST=rabbitmq \
    VIDEO_QUEUE=video \
    MP3_QUEUE=mp3 \
    PYTHONUNBUFFERED=1 \
    LOG_LEVEL=INFO


CMD ["python3", "consumer.py"]
