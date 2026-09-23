# MediaMarketplace Studio server image. Build from the mediamarketplace/ directory:
#   docker build -f deploy/Dockerfile -t mms-server .
FROM rust:1.94-bookworm AS build
WORKDIR /src
COPY Cargo.toml Cargo.lock ./
COPY crates ./crates
RUN cargo build --release --locked -p mms-server

FROM debian:bookworm-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates ffmpeg \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --create-home --home-dir /var/lib/mms mms
COPY --from=build /src/target/release/mms-server /usr/local/bin/mms-server
USER mms
WORKDIR /var/lib/mms
VOLUME ["/var/lib/mms"]
ENV MMS_CONFIG=/var/lib/mms/mms.toml MMS_BIND=0.0.0.0:8090
EXPOSE 8090
ENTRYPOINT ["/usr/local/bin/mms-server"]
CMD ["serve"]
