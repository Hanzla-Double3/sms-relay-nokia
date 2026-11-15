FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY relay ./relay
RUN chmod -R a+rX /app/relay && pip install --no-cache-dir --require-hashes -r requirements.lock && pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home relay && mkdir /app/data && chown relay:relay /app/data
USER relay
EXPOSE 8080
CMD ["uvicorn", "relay.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--ws-max-size", "16384", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "*"]
