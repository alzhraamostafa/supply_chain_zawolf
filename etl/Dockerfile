FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "psycopg[binary]>=3.2"
COPY loader.py load_to_postgres.py ./
CMD ["python", "load_to_postgres.py", "/data/logistic_in_cosmatic.db"]
