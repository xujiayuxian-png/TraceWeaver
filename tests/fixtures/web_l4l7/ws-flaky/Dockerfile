FROM python:3.12-alpine

RUN pip install --no-cache-dir 'websockets==12.0'

COPY server.py /app/server.py
WORKDIR /app

EXPOSE 8080
CMD ["python", "/app/server.py"]
