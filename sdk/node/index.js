'use strict';

// tracemelt for Node.js. Status: prototype.
// A thin layer over the OpenTelemetry SDK: it wires OTLP export to a tracemelt collector
// and adds four one-line helpers. Every public function is fail-open: it returns
// normally whatever goes wrong, and telemetry problems never reach the application.

const { resolve } = require('./lib/config');
const safe = require('./lib/safe');

const MAX_INSTRUMENTS = 500;      // distinct metric names this process may create
// The export timeout also bounds how long an unreachable collector can keep the process alive
// after shutdown() has returned, because upstream retries are not cancelled by shutdown.
const QUEUE = { maxQueueSize: 2048, maxExportBatchSize: 512, scheduledDelayMillis: 5000, exportTimeoutMillis: 5000 };
const METRIC_INTERVAL_MS = 30000;
const SHUTDOWN_TIMEOUT_MS = 5000;

const state = { started: false, enabled: false, sdk: null, api: null, meter: null, logger: null, instruments: new Map(), warned: new Set(), debug: false, restoreConsole: null };

function warn(key, message) {
  if (state.warned.has(key)) return;
  state.warned.add(key);
  try { process.stderr.write(`tracemelt: ${message}\n`); } catch { /* nothing left to do */ }
}

function guard(fn) {
  return function guarded(...args) {
    try { return fn(...args); } catch (err) {
      if (state.debug) warn(`error:${fn.name}`, `${fn.name} failed: ${err && err.message}`);
      return undefined;
    }
  };
}

function init(options) {
  if (state.started) return state.enabled;
  state.started = true;
  const config = resolve(options);
  state.debug = config.debug;
  if (!config.enabled) {
    warn('disabled', `telemetry is off: ${config.reason}`);
    return false;
  }

  const api = require('@opentelemetry/api');
  const { NodeSDK } = require('@opentelemetry/sdk-node');
  const { resourceFromAttributes } = require('@opentelemetry/resources');
  const { BatchSpanProcessor } = require('@opentelemetry/sdk-trace');
  const { BatchLogRecordProcessor } = require('@opentelemetry/sdk-logs');
  const { PeriodicExportingMetricReader } = require('@opentelemetry/sdk-metrics');

  if (config.debug) api.diag.setLogger(new api.DiagConsoleLogger(), api.DiagLogLevel.WARN);

  const test = (options && options._exporters) || null;   // tests inject in-memory exporters
  let exporters = test;
  if (!exporters) {
    const { OTLPTraceExporter } = require('@opentelemetry/exporter-trace-otlp-proto');
    const { OTLPMetricExporter } = require('@opentelemetry/exporter-metrics-otlp-proto');
    const { OTLPLogExporter } = require('@opentelemetry/exporter-logs-otlp-proto');
    const common = { headers: config.headers, timeoutMillis: QUEUE.exportTimeoutMillis };
    exporters = {
      trace: new OTLPTraceExporter({ ...common, url: `${config.endpoint}/v1/traces` }),
      metric: new OTLPMetricExporter({ ...common, url: `${config.endpoint}/v1/metrics` }),
      log: new OTLPLogExporter({ ...common, url: `${config.endpoint}/v1/logs` }),
    };
  }
  const queue = { ...QUEUE, ...((options && options._queue) || {}) };

  let instrumentations = [];
  if (config.autoInstrument && !test) {
    const { getNodeAutoInstrumentations } = require('@opentelemetry/auto-instrumentations-node');
    // File system spans are far too many to be useful by default.
    instrumentations = [getNodeAutoInstrumentations({ '@opentelemetry/instrumentation-fs': { enabled: false } })];
  }

  const sdk = new NodeSDK({
    resource: resourceFromAttributes({ 'service.name': config.serviceName }),
    spanProcessors: [new BatchSpanProcessor({ exporter: exporters.trace, ...queue })],
    logRecordProcessors: [new BatchLogRecordProcessor({ exporter: exporters.log, ...queue })],
    metricReaders: [exporters.metricReader || new PeriodicExportingMetricReader({
      exporter: exporters.metric, exportIntervalMillis: METRIC_INTERVAL_MS, exportTimeoutMillis: QUEUE.exportTimeoutMillis })],
    instrumentations,
  });
  sdk.start();

  state.sdk = sdk;
  state.api = api;
  state.meter = api.metrics.getMeter('tracemelt');
  state.logger = api.logs.getLogger('tracemelt');
  state.enabled = true;

  if (config.captureConsole) captureConsole();
  // Best-effort flush when the event loop drains. No signal handlers are installed,
  // because adding one would change how the application exits.
  process.once('beforeExit', () => { shutdown(); });
  return true;
}

function instrument(kind, name) {
  const key = `${kind}:${name}`;
  let found = state.instruments.get(key);
  if (found) return found;
  if (state.instruments.size >= MAX_INSTRUMENTS) {
    warn('instruments', `more than ${MAX_INSTRUMENTS} metric names, new ones are dropped`);
    return null;
  }
  if (kind === 'counter') found = state.meter.createCounter(name);
  else if (kind === 'gauge') found = state.meter.createGauge(name);
  else found = state.meter.createHistogram(name, { unit: 'ms' });
  state.instruments.set(key, found);
  return found;
}

function record(kind, name, value, attrs) {
  if (!state.enabled) return;
  if (!safe.validName(name)) return warn(`name:${String(name).slice(0, 40)}`, 'metric name rejected, see the SDK reference for the allowed form');
  if (typeof value !== 'number' || !Number.isFinite(value)) return;
  if (kind !== 'gauge' && value < 0) return;
  const target = instrument(kind, name);
  if (!target) return;
  const clean = safe.attributes(attrs);
  if (kind === 'counter') target.add(value, clean); else target.record(value, clean);
}

/** Adds to a counter. `count('orders')` adds 1. Negative values are ignored. */
function count(name, value = 1, attrs) { record('counter', name, value, attrs); }

/** Records the current value of something that goes up and down. */
function gauge(name, value, attrs) { record('gauge', name, value, attrs); }

/** Records a duration in milliseconds. */
function timing(name, milliseconds, attrs) { record('histogram', name, milliseconds, attrs); }

/**
 * Emits a business event as a log record tagged for tracemelt, and counts it.
 * Numeric attributes are treated as measurements and summed, unless the key looks
 * like an identifier. Pass identifiers as strings.
 */
function event(name, attrs) {
  if (!state.enabled) return;
  if (!safe.validName(name)) return warn(`event:${String(name).slice(0, 40)}`, 'event name rejected, see the SDK reference for the allowed form');
  const clean = safe.attributes(attrs);
  state.logger.emit({
    severityNumber: state.api.SeverityNumber.INFO,
    severityText: 'INFO',
    body: name,
    attributes: { ...clean, 'tracemelt.event': 'true', 'event.name': name },
  });
  const counter = instrument('counter', 'tracemelt.events');
  if (counter) counter.add(1, { 'event.name': name });
  for (const [key, value] of safe.summable(clean)) {
    const sum = instrument('counter', `tracemelt.event.${name}.${key}`);
    if (sum) sum.add(value);
  }
}

function captureConsole() {
  const levels = { log: ['INFO', 9], info: ['INFO', 9], warn: ['WARN', 13], error: ['ERROR', 17] };
  const originals = {};
  let busy = false;
  for (const [method, [text, number]] of Object.entries(levels)) {
    const original = console[method];
    originals[method] = original;
    console[method] = function patched(...args) {
      if (!busy && state.enabled) {
        busy = true;                      // a logger that prints must not loop back in here
        try {
          const body = args.map((a) => (typeof a === 'string' ? a : safeString(a))).join(' ').slice(0, 8192);
          state.logger.emit({ severityNumber: number, severityText: text, body });
        } catch { /* never let capture break console output */ }
        busy = false;
      }
      return original.apply(this, args);
    };
  }
  state.restoreConsole = () => { for (const [method, original] of Object.entries(originals)) console[method] = original; };
}

function safeString(value) {
  try { return value instanceof Error ? String(value.stack || value) : JSON.stringify(value); } catch { return String(value); }
}

/** Flushes what is queued and stops. Resolves within `timeoutMillis` whatever happens. */
function shutdown(timeoutMillis = SHUTDOWN_TIMEOUT_MS) {
  if (!state.enabled || !state.sdk) return Promise.resolve();
  const sdk = state.sdk;
  state.enabled = false;
  state.sdk = null;
  if (state.restoreConsole) { try { state.restoreConsole(); } catch { /* ignore */ } }
  let timer;
  const limit = new Promise((done) => { timer = setTimeout(done, Math.max(0, Number(timeoutMillis) || 0)); if (timer.unref) timer.unref(); });
  let work;
  try { work = Promise.resolve(sdk.shutdown()).catch(() => {}); } catch { work = Promise.resolve(); }
  return Promise.race([work, limit]).then(() => { clearTimeout(timer); });
}

module.exports = {
  init: guard(init),
  count: guard(count),
  gauge: guard(gauge),
  timing: guard(timing),
  event: guard(event),
  shutdown: (timeoutMillis) => { try { return shutdown(timeoutMillis); } catch { return Promise.resolve(); } },
  isEnabled: () => state.enabled,
};
