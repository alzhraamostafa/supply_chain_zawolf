FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common ./common
COPY contracts ./contracts
COPY delivery ./delivery
COPY risk ./risk
COPY api ./api
ENV AUDIT_DB_PATH=/state/audit.db
EXPOSE 8000
CMD ["uvicorn", "api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]