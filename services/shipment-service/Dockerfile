FROM python:3.11-slim

WORKDIR /app

COPY services/shipment-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/shipment-service/app ./app
COPY shared ./shared

EXPOSE 8004

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]
