'use strict';
// A collector that never answers must not make the queue grow without bound.
const test = require('node:test');
const assert = require('node:assert/strict');
const api = require('@opentelemetry/api');
const { InMemoryLogRecordExporter } = require('@opentelemetry/sdk-logs');
const { InMemoryMetricExporter, PeriodicExportingMetricReader, AggregationTemporality } = require('@opentelemetry/sdk-metrics');
const tracemelt = require('../index');

class StuckExporter {
  constructor() { this.received = 0; this.batches = 0; }
  export(spans) { this.received += spans.length; this.batches += 1; /* never calls back */ }
  shutdown() { return new Promise(() => {}); }
  forceFlush() { return new Promise(() => {}); }
}

test('a stuck exporter drops spans instead of queueing them forever', async () => {
  const stuck = new StuckExporter();
  const metricReader = new PeriodicExportingMetricReader({ exporter: new InMemoryMetricExporter(AggregationTemporality.CUMULATIVE), exportIntervalMillis: 3600000 });
  tracemelt.init({
    endpoint: 'http://unused:4318', serviceName: 'overload',
    _exporters: { trace: stuck, log: new InMemoryLogRecordExporter(), metricReader },
    _queue: { maxQueueSize: 100, maxExportBatchSize: 10, scheduledDelayMillis: 5, exportTimeoutMillis: 60000 },
  });
  const tracer = api.trace.getTracer('test');
  const before = process.memoryUsage().heapUsed;
  for (let i = 0; i < 200000; i += 1) tracer.startSpan('work').end();
  await new Promise((done) => setTimeout(done, 100));
  const grown = (process.memoryUsage().heapUsed - before) / 1e6;

  assert.ok(stuck.batches >= 1, 'the exporter was tried');
  assert.ok(stuck.received <= 10, `only one batch may be in flight, saw ${stuck.received} spans`);
  assert.ok(grown < 100, `heap grew by ${grown.toFixed(0)} MB for 200000 spans`);

  const started = Date.now();
  await tracemelt.shutdown(300);
  assert.ok(Date.now() - started < 1500, 'shutdown returns at its timeout even though the exporter never finishes');
});
