FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src:/app

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY sql ./sql
COPY tests ./tests
COPY pytest.ini .
COPY data ./data

EXPOSE 8000
CMD ["uvicorn", "tva.api:app", "--host", "0.0.0.0", "--port", "8000"]
