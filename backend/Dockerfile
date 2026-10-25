FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock.txt requirements.lock.txt
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY app app
COPY alembic alembic
COPY alembic.ini alembic.ini
RUN useradd --uid 10001 --create-home creatorops
USER creatorops
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
