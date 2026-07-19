# syntax=docker/dockerfile:1.7
# AxData API image. Build from the AxData repository root.
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ARG APT_MIRROR=mirrors.aliyun.com
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    AXDATA_DATA_DIR=/var/lib/axdata/data \
    AXDATA_METADATA_DB=/var/lib/axdata/metadata/axdata.sqlite \
    AXDATA_API_HOST=0.0.0.0 \
    AXDATA_API_PORT=8666

WORKDIR /app

# lxml may need libxml2/libxslt at runtime; curl is used by the health check.
RUN sed -i "s|deb.debian.org|${APT_MIRROR}|g; s|security.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install --no-install-recommends -y curl libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Install third-party dependencies in cacheable layers. Application source changes
# after these layers no longer cause pandas/pyarrow/FastAPI to be downloaded again.
COPY pyproject.toml /app/
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --upgrade pip \
    && python -m pip install --prefer-binary .

COPY libs/axdata_core /app/libs/axdata_core
COPY packages/axdata-source-tdx /app/packages/axdata-source-tdx
COPY packages/axdata-source-tdx-ext /app/packages/axdata-source-tdx-ext
COPY packages/axdata-source-tencent /app/packages/axdata-source-tencent
COPY packages/axdata-source-cninfo /app/packages/axdata-source-cninfo
COPY packages/axdata-sdk /app/packages/axdata-sdk

# Install the API dependencies and every Provider bundled in this repository.
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --prefer-binary ./libs/axdata_core \
    && python -m pip install ./packages/axdata-source-tdx \
    && python -m pip install ./packages/axdata-source-tdx-ext \
    && python -m pip install ./packages/axdata-source-tencent \
    && python -m pip install ./packages/axdata-source-cninfo \
    && python -m pip install ./packages/axdata-sdk

COPY . /app

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
