FROM node:22-bookworm-slim AS node-runtime
FROM python:3.12-slim-bookworm
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY requirements.txt requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c requirements-lock.txt
RUN groupadd --gid 10001 edentica && useradd --uid 10001 --gid edentica --create-home edentica
COPY --chown=edentica:edentica backend ./backend
COPY --chown=edentica:edentica public ./public
COPY --chown=edentica:edentica src ./src
COPY --chown=edentica:edentica scripts ./scripts
COPY --chown=edentica:edentica templates ./templates
COPY --chown=edentica:edentica package.json ./
RUN mkdir -p /app/data /app/output && chown -R edentica:edentica /app/data /app/output
ENV HOST=0.0.0.0 PORT=3000 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
ENV PYTHON_PATH=/usr/local/bin/python CERTIFICATE_FONT=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf
EXPOSE 3000
USER edentica
CMD ["python", "-m", "backend"]
