FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir ".[server]"
EXPOSE 8123
CMD ["python", "-c", "import uvicorn; from orion.server import app; uvicorn.run(app, host='0.0.0.0', port=8123)"]
