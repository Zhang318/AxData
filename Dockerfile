# AxData API image. Build from the AxData repository root.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AXDATA_DATA_DIR=/var/lib/axdata/data \
    AXDATA_METADATA_DB=/var/lib/axdata/metadata/axdata.sqlite \
    AXDATA_API_HOST=0.0.0.0 \
    AXDATA_API_PORT=8666

WORKDIR /app

# lxml may need libxml2/libxslt at runtime; curl is used by the health check.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

# Install the API dependencies and every Provider bundled in this repository.
RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && python -m pip install ./libs/axdata_core \
    && python -m pip install ./packages/axdata-source-tdx \
    && python -m pip install ./packages/axdata-source-tdx-ext \
    && python -m pip install ./packages/axdata-source-tencent \
    && python -m pip install ./packages/axdata-source-cninfo \
    && python -m pip install ./packages/axdata-sdk

RUN useradd --create-home --uid 10001 axdata \
    && mkdir -p /var/lib/axdata/data /var/lib/axdata/metadata \
    && chown -R axdata:axdata /app /var/lib/axdata

USER axdata

VOLUME ["/var/lib/axdata"]
EXPOSE 8666

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent --show-error \
    -H "Authorization: Bearer $$AXDATA_API_TOKEN" \
    http://127.0.0.1:8666/health || exit 1

# A non-loopback listener requires authentication. Supply AXDATA_API_TOKEN at runtime.
CMD ["sh", "-c", "test -n \"$AXDATA_API_TOKEN\" || { echo 'AXDATA_API_TOKEN is required'; exit 1; }; exec python -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8666 --proxy-headers"]
