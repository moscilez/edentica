FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c requirements-lock.txt
RUN groupadd --gid 10001 edentica && useradd --uid 10001 --gid edentica --create-home edentica
COPY --chown=edentica:edentica backend ./backend
COPY --chown=edentica:edentica public/program-studio.html public/program-studio.js public/program-studio.css public/program-editor.js public/workspace.js public/usage.js public/workspace.css public/brand.png public/brand.svg public/favicon.png public/favicon.svg public/favicon.ico ./public/
COPY --chown=edentica:edentica scripts/extract-material.py ./scripts/
COPY --chown=edentica:edentica templates ./templates
RUN mkdir -p /app/data /app/output && chown -R edentica:edentica /app/data /app/output
ENV HOST=0.0.0.0 PORT=3000 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
ENV PYTHON_PATH=/usr/local/bin/python CERTIFICATE_FONT=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf
EXPOSE 3000
USER edentica
CMD ["python", "-m", "backend"]

FROM runtime AS test
USER root
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt -c requirements-lock.txt
COPY --chown=edentica:edentica tests_python ./tests_python
COPY --chown=edentica:edentica scripts/migrate-postgres.py ./scripts/migrate-postgres.py
USER edentica
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests_python"]
