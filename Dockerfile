FROM node:22-bookworm-slim AS node-runtime
FROM python:3.12-slim-bookworm
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY requirements.txt requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c requirements-lock.txt
COPY . .
ENV HOST=0.0.0.0 PORT=3000
ENV PYTHON_PATH=/usr/local/bin/python CERTIFICATE_FONT=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf
EXPOSE 3000
CMD ["python", "-m", "backend"]
