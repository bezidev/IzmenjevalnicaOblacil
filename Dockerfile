FROM python:3.13-alpine

WORKDIR /app
COPY . /app
RUN apk update && apk add git build-base tzdata && pip install -r requirements.txt
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
