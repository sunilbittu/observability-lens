'use strict';
// Runs the real SDK with in-memory exporters and checks what would be sent.
const test = require('node:test');
const assert = require('node:assert/strict');
const api = require('@opentelemetry/api');
const { InMemorySpanExporter } = require('@opentelemetry/sdk-trace');
const { InMemoryLogRecordExporter } = require('@opentelemetry/sdk-logs');
const { InMemoryMetricExporter, PeriodicExportingMetricReader, AggregationTemporality } = require('@opentelemetry/sdk-metrics');
const tracemelt = require('../index');

// The in-memory exporters empty themselves on shutdown. These keep what they were given,
// so the test can shut down for real and then look at what was flushed.
const keep = (Base, ...args) => new (class extends Base { shutdown() { return Promise.resolve(); } })(...args);
const trace = keep(InMemorySpanExporter);
const log = keep(InMemoryLogRecordExporter);
const metric = keep(InMemoryMetricExporter, AggregationTemporality.CUMULATIVE);
const metricReader = new PeriodicExportingMetricReader({ exporter: metric, exportIntervalMillis: 3600000 });

const originalLog = console.log;

test('contract', async (t) => {
  assert.equal(tracemelt.init({ endpoint: 'http://unused:4318', serviceName: 'contract', _exporters: { trace, log, metricReader } }), true);
  assert.equal(tracemelt.init({ endpoint: 'http://other:4318' }), true, 'a second init is ignored');
  assert.equal(console.log, originalLog, 'console is not patched unless captureConsole is set');

  let traceId;
  api.trace.getTracer('test').startActiveSpan('checkout', (span) => {
    traceId = span.spanContext().traceId;
    tracemelt.event('order.placed', { product: 'kettle', quantity: 2, value_cents: 2598, order_id: 12345, user_id: 'u-1', nested: { a: 1 } });
    span.end();
  });
  tracemelt.event('order.placed', { quantity: 1, value_cents: 1000 });
  tracemelt.count('requests');
  tracemelt.count('requests', 4, { route: '/x' });
  tracemelt.gauge('queue.depth', 7);
  tracemelt.gauge('temperature', -3.5);
  tracemelt.timing('latency', 12.5);

  // None of these may throw or record anything.
  for (const bad of [undefined, null, NaN, Infinity, '5', {}, [], () => 1]) {
    tracemelt.count('bad.count', bad === undefined ? NaN : bad);
    tracemelt.gauge('bad.gauge', bad);
    tracemelt.timing('bad.timing', bad);
  }
  tracemelt.count('requests', -1);
  tracemelt.timing('latency', -5);
  for (const name of [undefined, null, '', 'has space', 42, {}, 'x'.repeat(500)]) {
    tracemelt.count(name); tracemelt.gauge(name, 1); tracemelt.timing(name, 1); tracemelt.event(name, { a: 1 });
  }
  tracemelt.event('weird.attrs', 'not an object');
  tracemelt.event('weird.attrs', null);

  await tracemelt.shutdown();

  await t.test('events are log records with the tracemelt tags', () => {
    const records = log.getFinishedLogRecords().filter((r) => r.body === 'order.placed');
    assert.equal(records.length, 2);
    const first = records[0];
    assert.equal(first.attributes['tracemelt.event'], 'true');
    assert.equal(first.attributes['event.name'], 'order.placed');
    assert.equal(first.severityText, 'INFO');
    assert.deepEqual([first.attributes.product, first.attributes.quantity, first.attributes.user_id], ['kettle', 2, 'u-1']);
    assert.equal('nested' in first.attributes, false, 'non-primitive attributes are dropped');
  });

  await t.test('an event emitted inside a span carries its trace id', () => {
    const first = log.getFinishedLogRecords().find((r) => r.body === 'order.placed');
    assert.equal(first.spanContext.traceId, traceId);
    assert.equal(trace.getFinishedSpans().length, 1);
  });

  const points = new Map();
  for (const batch of metric.getMetrics()) for (const scope of batch.scopeMetrics) for (const m of scope.metrics) {
    points.set(m.descriptor.name, m.dataPoints);
  }
  const value = (name, match = () => true) => points.get(name).filter((p) => match(p.attributes)).map((p) => p.value);

  await t.test('events are counted by name', () => {
    assert.deepEqual(value('tracemelt.events', (a) => a['event.name'] === 'order.placed'), [2]);
  });

  await t.test('numeric attributes are summed, identifiers are not', () => {
    assert.deepEqual(value('tracemelt.event.order.placed.quantity'), [3]);
    assert.deepEqual(value('tracemelt.event.order.placed.value_cents'), [3598]);
    assert.equal(points.has('tracemelt.event.order.placed.order_id'), false);
    assert.equal(points.has('tracemelt.event.order.placed.user_id'), false);
  });

  await t.test('count, gauge and timing record without declaring instruments', () => {
    assert.deepEqual(value('requests', (a) => !a.route), [1]);
    assert.deepEqual(value('requests', (a) => a.route === '/x'), [4]);
    assert.deepEqual(value('queue.depth'), [7]);
    assert.deepEqual(value('temperature'), [-3.5]);
    const [latency] = points.get('latency');
    assert.deepEqual([latency.value.count, latency.value.sum], [1, 12.5]);
  });

  await t.test('bad values and bad names recorded nothing', () => {
    for (const name of ['bad.count', 'bad.gauge', 'bad.timing']) assert.equal(points.has(name), false, name);
    assert.equal([...points.keys()].some((k) => k.includes(' ')), false);
  });

  await t.test('after shutdown every call is a quiet no-op', async () => {
    tracemelt.count('requests'); tracemelt.event('order.placed'); tracemelt.gauge('g', 1); tracemelt.timing('t', 1);
    await tracemelt.shutdown();
    assert.equal(tracemelt.isEnabled(), false);
  });
});
