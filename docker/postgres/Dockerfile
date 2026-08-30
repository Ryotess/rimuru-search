FROM postgres:18-bookworm@sha256:1c59e2c3c818eaa0f0628f695b36e7c9e362d6b219b36a54a32df645cbd7e1af AS pg_textsearch_builder

ARG POSTGRES_MAJOR=18
ARG PG_TEXTSEARCH_VERSION=1.2.0
ARG PG_TEXTSEARCH_SHA256=f2f0121e38ede58e92d00f12b9ee514aff654917ccaa5938a263ac4fa12d6b11

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        postgresql-server-dev-${POSTGRES_MAJOR} \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN curl --fail --location --show-error \
        "https://github.com/timescale/pg_textsearch/archive/refs/tags/v${PG_TEXTSEARCH_VERSION}.tar.gz" \
        --output pg_textsearch.tar.gz \
    && echo "${PG_TEXTSEARCH_SHA256}  pg_textsearch.tar.gz" | sha256sum --check - \
    && tar --extract --gzip --file pg_textsearch.tar.gz \
    && make -C "pg_textsearch-${PG_TEXTSEARCH_VERSION}" \
        PG_CONFIG="/usr/lib/postgresql/${POSTGRES_MAJOR}/bin/pg_config" \
    && make -C "pg_textsearch-${PG_TEXTSEARCH_VERSION}" \
        PG_CONFIG="/usr/lib/postgresql/${POSTGRES_MAJOR}/bin/pg_config" \
        DESTDIR=/extension-root install

FROM pgvector/pgvector:pg18@sha256:2ba9ca5f2e7daa0f0e7723cba1ee9167bab54efd3640516a44ac1a928dd67e7a

COPY --from=pg_textsearch_builder /extension-root/ /
