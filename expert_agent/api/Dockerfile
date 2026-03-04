FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

# 기본은 Redis Streams consumer 워커 (entrypoint에서 ingest 1회 후 consumer 실행)
CMD ["./entrypoint.sh"]
