'use strict';

// Resolves settings from options, then TRACEMELT_* variables, then the standard OTEL_* ones.
// Returns { enabled: false, reason } instead of throwing when telemetry cannot be set up.

const TRUE = new Set(['1', 'true', 'yes', 'on']);
const flag = (value) => TRUE.has(String(value || '').toLowerCase());

function resolve(options = {}, env = process.env) {
  const serviceName = options.serviceName || env.TRACEMELT_SERVICE_NAME || env.OTEL_SERVICE_NAME || 'unknown_service';
  const base = {
    serviceName,
    captureConsole: options.captureConsole === undefined ? flag(env.TRACEMELT_CAPTURE_CONSOLE) : options.captureConsole === true,
    debug: options.debug === undefined ? flag(env.TRACEMELT_DEBUG) : options.debug === true,
    autoInstrument: options.autoInstrument !== false && !flag(env.TRACEMELT_NO_AUTO_INSTRUMENT),
  };
  if (options.disabled === true || flag(env.TRACEMELT_DISABLED) || flag(env.OTEL_SDK_DISABLED)) {
    return { ...base, enabled: false, reason: 'disabled by configuration' };
  }
  const raw = options.endpoint || env.TRACEMELT_ENDPOINT || env.OTEL_EXPORTER_OTLP_ENDPOINT;
  if (!raw) return { ...base, enabled: false, reason: 'no endpoint set (TRACEMELT_ENDPOINT)' };
  let url;
  try {
    url = new URL(String(raw));
  } catch {
    return { ...base, enabled: false, reason: 'endpoint is not a valid URL' };
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    return { ...base, enabled: false, reason: 'endpoint must start with http:// or https://' };
  }
  const endpoint = (url.origin + url.pathname).replace(/\/+$/, '');
  const token = options.token || env.TRACEMELT_INGEST_TOKEN;
  return { ...base, enabled: true, endpoint, headers: token ? { Authorization: `Bearer ${token}` } : {} };
}

module.exports = { resolve };
