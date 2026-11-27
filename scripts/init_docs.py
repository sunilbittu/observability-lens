#!/usr/bin/env python3
"""Bootstrap otelens documentation skeleton and Wave 1 pages."""

from __future__ import annotations

import argparse
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

STATUS_META = {
    "stable": {
        "admonition": "note",
        "text": "Implemented and tested within the stated version range.",
    },
    "prototype": {
        "admonition": "warning",
        "text": (
            "Code or design exists but has not been verified end-to-end. "
            "Expect breakage. Commands and fields may change."
        ),
    },
    "planned": {
        "admonition": "info",
        "text": (
            "Design only. No working implementation yet. "
            "Do not rely on this page for current behavior."
        ),
    },
    "deprecated": {
        "admonition": "danger",
        "text": "Deprecated. Follow the linked migration path.",
    },
}

MODE_OUTLINE = {
    "tutorial": [
        "Goal",
        "Prerequisites",
        "Steps",
        "Verify",
        "Next steps",
    ],
    "how-to": [
        "Goal",
        "Prerequisites",
        "Steps",
        "Verify",
        "Rollback",
        "Related",
    ],
    "reference": [
        "Applies to",
        "Fields",
        "Limits",
        "Examples",
        "Errors",
        "Related",
    ],
    "explanation": [
        "Context",
        "Model",
        "Trade-offs",
        "Guarantees",
        "Related",
    ],
    "project": [
        "Purpose",
        "Current state",
        "Next actions",
        "Related",
    ],
}

# path, title, status, mode, purpose
PAGES = [
    ("index.md", "otelens documentation", "prototype", "explanation", "Documentation landing page."),
    ("getting-started/quickstart.md", "Quickstart", "prototype", "tutorial", "See telemetry in the UI within five minutes."),
    ("getting-started/first-app.md", "Instrument your first app", "prototype", "tutorial", "Send traces, logs, metrics, and events from a real app."),
    ("getting-started/first-alert.md", "Create your first alert", "prototype", "tutorial", "Create a threshold alert and notify a webhook."),
    ("getting-started/ui-tour.md", "UI tour", "prototype", "tutorial", "Learn every tab in the otelens UI."),
    ("getting-started/installation/docker-compose.md", "Install with Docker Compose", "prototype", "how-to", "Run the single-node prototype stack."),
    ("getting-started/installation/kubernetes.md", "Install on Kubernetes", "planned", "how-to", "Deploy otelens and collectors on Kubernetes."),
    ("getting-started/installation/air-gapped.md", "Air-gapped installation", "planned", "how-to", "Install without internet access."),
    ("getting-started/installation/production-checklist.md", "Production checklist", "planned", "reference", "Checklist before production use."),

    ("concepts/melt.md", "The MELT model", "prototype", "explanation", "Metrics, events, logs, and traces in otelens."),
    ("concepts/architecture.md", "Architecture", "prototype", "explanation", "Current single-node architecture and boundaries."),
    ("concepts/data-model.md", "Data model", "prototype", "explanation", "Tables, attribute contracts, and schema ownership."),
    ("concepts/events-as-logs.md", "Events as logs", "prototype", "explanation", "Why events are tagged log records."),
    ("concepts/opentelemetry-primer.md", "OpenTelemetry primer", "stable", "explanation", "OTLP, resources, attributes, and context basics."),
    ("concepts/cardinality.md", "Cardinality", "stable", "explanation", "Why label and attribute cardinality matters."),
    ("concepts/sampling.md", "Sampling", "planned", "explanation", "Head, tail, and error-preserving sampling strategy."),
    ("concepts/guarantees.md", "Guarantees", "prototype", "explanation", "Durability, ordering, and loss semantics."),

    ("instrumentation/overview.md", "Instrumentation overview", "prototype", "explanation", "How apps send telemetry to otelens."),
    ("instrumentation/nodejs.md", "Node.js instrumentation", "prototype", "how-to", "Instrument Node.js services."),
    ("instrumentation/python.md", "Python instrumentation", "prototype", "how-to", "Instrument Python services."),
    ("instrumentation/java.md", "Java instrumentation", "planned", "how-to", "Instrument Java services."),
    ("instrumentation/dotnet.md", ".NET instrumentation", "planned", "how-to", "Instrument .NET services."),
    ("instrumentation/go.md", "Go instrumentation", "planned", "how-to", "Instrument Go services."),
    ("instrumentation/browser-rum.md", "Browser RUM", "planned", "how-to", "Collect browser real-user monitoring."),
    ("instrumentation/mobile.md", "Mobile instrumentation", "planned", "how-to", "Collect mobile telemetry."),
    ("instrumentation/sdk-reference/nodejs-api.md", "Node.js SDK API", "prototype", "reference", "otelens Node SDK API reference."),
    ("instrumentation/sdk-reference/python-api.md", "Python SDK API", "prototype", "reference", "otelens Python SDK API reference."),
    ("instrumentation/custom-events.md", "Custom events", "prototype", "how-to", "Emit business events."),
    ("instrumentation/custom-metrics.md", "Custom metrics", "prototype", "how-to", "Emit counters, gauges, and histograms."),
    ("instrumentation/logs-and-correlation.md", "Logs and correlation", "prototype", "how-to", "Send logs and correlate them with traces."),
    ("instrumentation/context-propagation.md", "Context propagation", "prototype", "how-to", "Propagate trace context across HTTP and queues."),
    ("instrumentation/pii-and-redaction.md", "PII and redaction", "planned", "how-to", "Prevent sensitive data entering telemetry."),
    ("instrumentation/performance-and-fail-open.md", "Performance and fail-open", "planned", "explanation", "SDK overhead and failure behavior."),
    ("instrumentation/troubleshooting-sdk.md", "SDK troubleshooting", "prototype", "how-to", "Debug missing or broken SDK telemetry."),

    ("collection/overview.md", "Collection overview", "prototype", "explanation", "Collector role and deployment shapes."),
    ("collection/configuration-reference.md", "Collector configuration reference", "prototype", "reference", "Collector config fields used by otelens."),
    ("collection/pipelines.md", "Pipelines", "prototype", "explanation", "Receivers, processors, exporters, and connectors."),
    ("collection/receivers.md", "Receivers", "prototype", "reference", "OTLP, filelog, hostmetrics, kubeletstats, Prometheus, and more."),
    ("collection/processors.md", "Processors", "prototype", "reference", "Batching, memory limits, redaction, filtering, and enrichment."),
    ("collection/exporters.md", "Exporters", "prototype", "reference", "ClickHouse exporter configuration and behavior."),
    ("collection/connectors.md", "Connectors", "planned", "reference", "spanmetrics and count connectors."),
    ("collection/deployment-patterns.md", "Deployment patterns", "planned", "explanation", "Agent, gateway, and DaemonSet patterns."),
    ("collection/scaling.md", "Scaling collectors", "planned", "how-to", "Scale ingestion and avoid backpressure."),

    ("infrastructure/hosts.md", "Host metrics", "planned", "how-to", "Collect CPU, memory, disk, and network metrics."),
    ("infrastructure/docker.md", "Docker metrics", "planned", "how-to", "Collect container metrics."),
    ("infrastructure/kubernetes.md", "Kubernetes metrics", "planned", "how-to", "Collect node, pod, container, and cluster metrics."),
    ("infrastructure/gpus/nvidia.md", "NVIDIA GPU metrics", "planned", "how-to", "Collect DCGM GPU metrics."),
    ("infrastructure/gpus/amd.md", "AMD GPU metrics", "planned", "how-to", "Collect ROCm GPU metrics."),
    ("infrastructure/gpus/intel.md", "Intel GPU metrics", "planned", "how-to", "Collect Intel XPU metrics."),
    ("infrastructure/databases.md", "Database metrics", "planned", "how-to", "Collect database performance metrics."),
    ("infrastructure/queues.md", "Queue metrics", "planned", "how-to", "Collect queue depth and consumer lag."),
    ("infrastructure/cloud.md", "Cloud metrics", "planned", "how-to", "Collect managed cloud service metrics."),
    ("infrastructure/metric-names.md", "Infrastructure metric names", "planned", "reference", "Common infrastructure metric names."),

    ("using-otelens/traces.md", "Traces", "prototype", "how-to", "Inspect trace lists and waterfalls."),
    ("using-otelens/logs.md", "Logs", "prototype", "how-to", "Search logs and jump to traces."),
    ("using-otelens/metrics.md", "Metrics", "prototype", "how-to", "Chart metrics."),
    ("using-otelens/events.md", "Events", "prototype", "how-to", "Inspect business events."),
    ("using-otelens/dashboards.md", "Dashboards", "prototype", "how-to", "Use and build dashboards."),
    ("using-otelens/search-and-query.md", "Search and query", "prototype", "reference", "Current search and query capabilities."),
    ("using-otelens/incident-workflow.md", "Incident workflow", "prototype", "how-to", "Use otelens during an incident."),

    ("alerting/overview.md", "Alerting overview", "prototype", "explanation", "How alert evaluation works."),
    ("alerting/rule-reference.md", "Alert rule reference", "prototype", "reference", "Rule fields, signals, comparators, windows, cooldowns."),
    ("alerting/notifications.md", "Notifications", "prototype", "how-to", "Send alert notifications to webhooks and Slack."),
    ("alerting/presets.md", "Alert presets", "prototype", "reference", "Useful starter alert rules."),
    ("alerting/limitations.md", "Alerting limitations", "prototype", "explanation", "Current alerting gaps and risks."),
    ("alerting/roadmap.md", "Alerting roadmap", "planned", "project", "Planned alerting improvements."),

    ("api/rest-reference.md", "REST API reference", "prototype", "reference", "HTTP API endpoints."),
    ("api/authentication.md", "API authentication", "planned", "reference", "Authentication and authorization model."),
    ("api/limits-and-quotas.md", "API limits and quotas", "planned", "reference", "Rate limits, query limits, and quotas."),
    ("api/examples.md", "API examples", "prototype", "how-to", "Query otelens programmatically."),

    ("storage/clickhouse-schema.md", "ClickHouse schema", "prototype", "reference", "Telemetry and alert tables."),
    ("storage/retention-and-ttl.md", "Retention and TTL", "planned", "how-to", "Configure retention and TTL."),
    ("storage/sizing-and-capacity.md", "Sizing and capacity", "planned", "reference", "Estimate CPU, memory, disk, and ingest capacity."),
    ("storage/downsampling.md", "Downsampling", "planned", "explanation", "Long-term metric rollups."),
    ("storage/backup-restore.md", "Backup and restore", "planned", "how-to", "Back up and restore ClickHouse and config."),

    ("operations/hardening.md", "Hardening", "planned", "how-to", "Secure and durable deployment checklist."),
    ("operations/security-model.md", "Security model", "planned", "explanation", "Trust boundaries, threats, and controls."),
    ("operations/auth-and-rbac.md", "Auth and RBAC", "planned", "explanation", "OIDC, roles, service accounts, and audit."),
    ("operations/multi-tenancy.md", "Multi-tenancy", "planned", "explanation", "Tenant isolation and quotas."),
    ("operations/upgrades-and-migrations.md", "Upgrades and migrations", "planned", "how-to", "Upgrade otelens, collector, and schema safely."),
    ("operations/monitoring-otelens.md", "Monitoring otelens", "planned", "how-to", "Observe the observability stack."),
    ("operations/ha-and-scaling.md", "HA and scaling", "planned", "explanation", "High availability architecture."),
    ("operations/performance-tuning.md", "Performance tuning", "planned", "how-to", "Tune collector, ClickHouse, and queries."),
    ("operations/runbooks/clickhouse-down.md", "Runbook: ClickHouse down", "planned", "how-to", "Respond to ClickHouse outage."),
    ("operations/runbooks/disk-full.md", "Runbook: disk full", "planned", "how-to", "Respond to disk pressure."),
    ("operations/runbooks/ingest-lag.md", "Runbook: ingest lag", "planned", "how-to", "Respond to ingestion backlog."),
    ("operations/runbooks/alert-storm.md", "Runbook: alert storm", "planned", "how-to", "Respond to duplicate or noisy alerts."),
    ("operations/runbooks/slow-queries.md", "Runbook: slow queries", "planned", "how-to", "Respond to expensive queries."),

    ("troubleshooting/no-data.md", "No data in the UI", "prototype", "how-to", "Diagnose missing telemetry."),
    ("troubleshooting/collector-errors.md", "Collector errors", "prototype", "reference", "Common collector errors and fixes."),
    ("troubleshooting/clickhouse-errors.md", "ClickHouse errors", "prototype", "reference", "Common ClickHouse errors and fixes."),
    ("troubleshooting/ui-errors.md", "UI errors", "prototype", "reference", "Common UI and API errors."),
    ("troubleshooting/faq.md", "FAQ", "prototype", "reference", "Frequently asked questions."),

    ("migrating/from-grafana-lgtm.md", "Migrating from Grafana LGTM", "planned", "how-to", "Move from Loki/Grafana/Tempo/Mimir."),
    ("migrating/from-signoz.md", "Migrating from SigNoz", "planned", "how-to", "Move from SigNoz."),
    ("migrating/from-datadog.md", "Migrating from Datadog", "planned", "how-to", "Move from Datadog."),
    ("migrating/from-elk.md", "Migrating from ELK", "planned", "how-to", "Move from Elasticsearch/Logstash/Kibana."),

    ("reference/env-vars.md", "Environment variables", "prototype", "reference", "Environment variables used by otelens."),
    ("reference/cli.md", "CLI reference", "planned", "reference", "otelens CLI commands."),
    ("reference/ports.md", "Ports", "prototype", "reference", "Network ports used by otelens."),
    ("reference/glossary.md", "Glossary", "stable", "reference", "Terms and acronyms."),
    ("reference/error-codes.md", "Error codes", "planned", "reference", "Structured error codes."),
    ("reference/version-support.md", "Version support", "prototype", "reference", "Versioning and support policy."),

    ("project/roadmap.md", "Roadmap", "prototype", "project", "Development priorities."),
    ("project/changelog.md", "Changelog", "prototype", "project", "Release notes."),
    ("project/comparison.md", "Comparison", "planned", "explanation", "Compare with other observability stacks."),
    ("project/contributing.md", "Contributing", "planned", "project", "How to contribute."),
    ("project/development-setup.md", "Development setup", "prototype", "how-to", "Set up a local development environment."),
    ("project/governance.md", "Governance", "planned", "project", "Project decision-making and maintainers."),
    ("project/security-policy.md", "Security policy", "planned", "project", "How to report vulnerabilities."),
    ("project/license.md", "License", "stable", "project", "Apache-2.0 license information."),
    ("project/architecture-decisions/index.md", "Architecture decisions", "prototype", "project", "ADR index."),
    ("project/architecture-decisions/adr-0001-clickhouse.md", "ADR-0001: ClickHouse", "prototype", "project", "Use ClickHouse as telemetry store."),
    ("project/architecture-decisions/adr-0002-events-as-logs.md", "ADR-0002: Events as logs", "prototype", "project", "Model events as tagged logs."),
    ("project/architecture-decisions/adr-0003-otlp-only.md", "ADR-0003: OTLP-only ingest", "prototype", "project", "Use OTLP rather than a proprietary protocol."),
    ("project/architecture-decisions/adr-0004-schema-ownership.md", "ADR-0004: Schema ownership", "prototype", "project", "Exporter owns telemetry schema."),
    ("project/architecture-decisions/adr-0005-thin-sdks.md", "ADR-0005: Thin SDKs", "prototype", "project", "Wrap upstream OTel SDKs."),
    ("project/architecture-decisions/adr-0006-auth-oidc.md", "ADR-0006: OIDC auth", "planned", "project", "Use OIDC proxy rather than bespoke identity."),
]

WAVE1 = {}

WAVE1["README.md"] = dedent("""\
# otelens

OpenTelemetry-native observability: **metrics, events, logs, and traces** in one place.

> **Status: prototype.** This project is under active development and has not been
> verified end-to-end. APIs, configuration, and schema will change. Not production-ready.

## What it is

otelens is a self-hosted observability platform built on standard components:

- **OpenTelemetry Collector** for ingestion over OTLP gRPC/HTTP
- **ClickHouse** for storage
- **Query API + web UI** for traces, logs, metrics, events, and dashboards
- **Alert engine** with webhook/Slack notifications

No proprietary agent or protocol. If it speaks OTLP, it can send data to otelens.

## Quickstart

```bash
git clone https://github.com/YOUR_ORG/otelens
cd otelens
docker compose --profile demo up -d --build