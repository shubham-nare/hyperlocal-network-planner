# Serves both the FastAPI app and the Celery worker (docker-compose.yml picks the
# command per service) -- same image, same dependencies, since the worker's tasks
# (api/tasks.py) call the identical geopandas/PuLP pipeline code the API does.
#
# NOT YET BUILT OR RUN in this environment: Docker Desktop isn't installed here (no
# admin rights / WSL2 -- see CONTEXT.md). Written to the same standard as the rest of
# this project, but unverified until Docker is available.
FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
ENV PYTHONPATH=/app/src:/app

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
