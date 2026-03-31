# Purpose: Build a compact runtime image for the API and worker containers.
# Input/Output: Docker copies requirements and application code into the image.
# Invariants: The same image is reused for both API and worker to keep deployments simple.
# Debug: Rebuild with `docker compose build --no-cache` if dependency changes are not visible.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tests ./tests

RUN mkdir -p /data

EXPOSE 8000

CMD ["python", "-m", "app.unraid_main"]
