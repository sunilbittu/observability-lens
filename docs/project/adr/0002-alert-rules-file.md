# ADR 0002: Alert rules in a file, alert state in ClickHouse

!!! warning "Status: prototype"
    Accepted on 2026-11-27 as a stopgap. To be replaced when Postgres is
    added in Phase 2. Applies to: `dev`.

## Context

The alert engine needs rules and it needs to remember when each rule last
fired. The target design stores rules, state, a notification outbox and an
audit log in Postgres. Postgres is not part of the stack yet, and adding it
would delay verifying that alerting works end to end.

Two shortcuts are ruled out: keeping cooldowns only in memory, because a
restart would re-fire every breaching rule, and keeping state in a local JSON
file.

## Decision

- Rules live in `deploy/alerts/rules.toml`, mounted read-only. They are
  configuration, loaded and validated at startup.
- State lives in ClickHouse, in a tracemelt-owned table `alert_events`. The
  engine writes a `fired` row before it attempts a webhook and reads the
  latest `fired` row to apply the cooldown.
- The engine uses its own ClickHouse user, which can read telemetry and can
  only insert into `alert_events`.

## Consequences

- Cooldowns survive a restart. Checked on 2026-11-27: after a restart, three
  rules that had fired reported `cooling_down`.
- A crash between the `fired` row and the webhook loses that notification.
  It is not sent twice.
- Rules cannot be created or deleted from the UI, edits are not audited, and
  a change needs a restart.
- There is no lock, so only one engine instance may run.
- Webhooks are attempted once. There is no outbox.

## Alternatives rejected

- **Add Postgres now.** Correct for Phase 2, more than Phase 0 needs.
- **Rules in a ClickHouse table.** ClickHouse is a poor fit for rows that are
  edited and deleted, and it would be replaced anyway.
