FROM python:3.13-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && groupadd --system --gid 10001 stageradar \
    && useradd --system --uid 10001 --gid 10001 --no-create-home stageradar \
    && install -d -m 0700 -o stageradar -g stageradar /data

COPY stageradar stageradar
COPY migrations migrations
COPY scripts/init.sh scripts/init.sh

USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "stageradar.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers"]
