# One-shot job: lets the pinned clickhouseexporter create its own schema, then exits.
# The collector image has no shell, so its binary is copied into busybox to script that.
FROM otel/opentelemetry-collector-contrib:0.166.0 AS collector

FROM busybox:1.37.0
COPY --from=collector /otelcol-contrib /otelcol-contrib
COPY config.yaml /etc/otelcol/config.yaml
COPY run.sh /run.sh
USER 10001:10001
ENTRYPOINT ["/bin/sh", "/run.sh"]
