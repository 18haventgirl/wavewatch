FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv/guanlan
COPY backend/requirements.lock.txt /tmp/requirements.lock.txt
RUN pip install --no-cache-dir -r /tmp/requirements.lock.txt \
    && useradd --create-home --uid 10001 guanlan
COPY backend backend
COPY app/__init__.py app/collectors.py app/
COPY config config
USER guanlan
CMD ["uvicorn", "backend.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8842", "--no-access-log"]
