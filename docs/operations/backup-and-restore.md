# Back up and restore

!!! warning "Status: prototype"
    Verified on 2026-11-27: a backup of 46,330 rows was restored into a
    scratch database and read back. Restoring over a live database has not
    been tested. Applies to: `dev`.

## Take a backup

```bash
scripts/backup.sh
```

Expected output:

```text
wrote backups/tracemelt-20261127T182618Z.zip (2.0M)
```

The archive holds every table in the telemetry database, including
`alert_events`. It is written inside the ClickHouse data volume, copied to
`./backups/` on the host and then removed from the volume. `./backups/` is
ignored by git.

The archive is a password-protected zip. The password is
`TRACEMELT_BACKUP_PASSWORD` in `.env`. Store the archives and `.env` in
different places: an archive without the password cannot be restored, and
the two together expose the data. Treat the zip password as a deterrent, not
as strong encryption, and encrypt the archive again before sending it
somewhere you do not control.

## Test that a backup restores

```bash
scripts/restore-test.sh backups/tracemelt-20261127T182618Z.zip
```

Expected output, with your own row counts:

```text
PASS  restore with a wrong password is refused (refused)
PASS  restore completed (1)
rows restored (live count in brackets):
  otel_logs: 14156 (14156)
  otel_traces: 29682 (29682)
  otel_metrics_gauge: 2316 (2316)
  otel_metrics_sum: 104 (104)
  alert_events: 72 (72)
PASS  restored logs are not empty (1)
PASS  restored traces are not empty (1)
PASS  a restored log record reads back (1)
PASS  a restored trace reads back by id (1)
restore test: all checks passed
```

The script restores into a scratch database called
`tracemelt_restore_check`, checks it and drops it. The live data is not
touched. The restored counts are at or below the live counts, because the
live tables keep growing.

Run this after every backup you intend to rely on. A backup that has not been
restored is not known to work.

## Restore after losing the data

This procedure has not been tested end to end. It is the same `RESTORE`
statement the test uses, pointed at the real database.

1. Stop the services that write: `docker compose stop collector alerts`.
   The collector's senders will retry; anything they give up on is lost.
2. Copy the archive in:
   `docker compose cp backups/NAME.zip clickhouse:/var/lib/clickhouse/backups/restore.zip`
3. Open a client: `docker compose exec clickhouse clickhouse-client --user "$TRACEMELT_CLICKHOUSE_USER" --password`
4. If the database still exists and you want to replace it:
   `DROP DATABASE otel SYNC`
5. `RESTORE DATABASE otel FROM File('/var/lib/clickhouse/backups/restore.zip') SETTINGS password = 'THE_BACKUP_PASSWORD'`
6. Start everything: `docker compose up -d`.

## Limitations

- **No schedule.** Nothing runs backups for you. Use cron or a timer on the
  host.
- **No retention.** Old archives in `./backups/` are never deleted.
- **Full backups only.** Every run copies everything, and the copy sits on
  the data volume until it has been moved out, so the volume needs that much
  free space.
- **Not shipped off the host.** A backup on the same machine does not survive
  losing the machine.
- **The collector queue is not backed up.** Data waiting in it during a
  restore is delivered afterwards, or lost if the queue volume is lost too.
- **Data newer than the backup is lost** on restore. Telemetry also expires
  after `TRACEMELT_RETENTION`, so an old backup restores into tables that
  will soon delete those rows.

## Related

- [Configuration reference](../reference/configuration.md)
- [Self-observability and data handling](self-observability.md)
