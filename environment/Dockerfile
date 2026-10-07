FROM python:3.12-slim
WORKDIR /app
COPY environment/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY environment /app/environment
CMD ["uvicorn", "environment.orders:app", "--host", "0.0.0.0", "--port", "8000"]
