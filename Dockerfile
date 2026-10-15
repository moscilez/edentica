FROM node:22-bookworm-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN python3 -m venv /app/venv && /app/venv/bin/pip install --no-cache-dir -r requirements.txt
COPY . .
ENV HOST=0.0.0.0 PORT=3000
ENV PYTHON_PATH=/app/venv/bin/python CERTIFICATE_FONT=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf
EXPOSE 3000
CMD ["node", "server.mjs"]
