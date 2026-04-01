FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python -c "from app.utils.certs import generate_self_signed_cert; generate_self_signed_cert('certs')"

EXPOSE 5000

ENV FLASK_ENV=production
ENV SEED_TEST_DATA=0

CMD ["sh", "-c", "python seed_test_data.py && python run.py"]
