'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { resolve } = require('../lib/config');
const safe = require('../lib/safe');

test('needs an endpoint', () => {
  const c = resolve({}, {});
  assert.equal(c.enabled, false);
  assert.match(c.reason, /no endpoint/);
});

test('reads TRACEMELT_* then OTEL_* variables', () => {
  const c = resolve({}, { TRACEMELT_ENDPOINT: 'https://t.example.com/', TRACEMELT_INGEST_TOKEN: 'abc', TRACEMELT_SERVICE_NAME: 'api' });
  assert.deepEqual([c.enabled, c.endpoint, c.serviceName, c.headers.Authorization], [true, 'https://t.example.com', 'api', 'Bearer abc']);
  const o = resolve({}, { OTEL_EXPORTER_OTLP_ENDPOINT: 'http://c:4318', OTEL_SERVICE_NAME: 'web' });
  assert.deepEqual([o.enabled, o.endpoint, o.serviceName, o.headers], [true, 'http://c:4318', 'web', {}]);
});

test('options win over the environment', () => {
  const c = resolve({ endpoint: 'http://a:1', serviceName: 'x', token: 't' }, { TRACEMELT_ENDPOINT: 'http://b:2', TRACEMELT_SERVICE_NAME: 'y' });
  assert.deepEqual([c.endpoint, c.serviceName, c.headers.Authorization], ['http://a:1', 'x', 'Bearer t']);
});

for (const bad of ['not a url', 'ftp://host', 'file:///etc/passwd', '://', 'javascript:alert(1)']) {
  test(`invalid endpoint ${JSON.stringify(bad)} turns telemetry off instead of throwing`, () => {
    const c = resolve({}, { TRACEMELT_ENDPOINT: bad });
    assert.equal(c.enabled, false);
  });
}

test('console capture is off unless asked for', () => {
  assert.equal(resolve({}, { TRACEMELT_ENDPOINT: 'http://c:4318' }).captureConsole, false);
  assert.equal(resolve({}, { TRACEMELT_ENDPOINT: 'http://c:4318', TRACEMELT_CAPTURE_CONSOLE: 'true' }).captureConsole, true);
  assert.equal(resolve({ captureConsole: true }, { TRACEMELT_ENDPOINT: 'http://c:4318' }).captureConsole, true);
});

test('can be disabled', () => {
  assert.equal(resolve({}, { TRACEMELT_ENDPOINT: 'http://c:4318', TRACEMELT_DISABLED: 'true' }).enabled, false);
  assert.equal(resolve({}, { TRACEMELT_ENDPOINT: 'http://c:4318', OTEL_SDK_DISABLED: 'true' }).enabled, false);
});

test('attributes keep only primitives and are bounded', () => {
  const many = Object.fromEntries(Array.from({ length: 100 }, (_, i) => [`k${i}`, i]));
  assert.equal(Object.keys(safe.attributes(many)).length, 32);
  assert.deepEqual(safe.attributes({ s: 'x', n: 1, b: true, o: {}, a: [1], f() {}, u: undefined, nan: NaN, inf: Infinity, nul: null }), { s: 'x', n: 1, b: true });
  assert.equal(safe.attributes({ long: 'x'.repeat(5000) }).long.length, 1024);
  for (const junk of [null, undefined, 'str', 5, [1, 2]]) assert.deepEqual(safe.attributes(junk), {});
});

test('only numeric measurements are summable, never identifiers', () => {
  const keys = (o) => safe.summable(o).map(([k]) => k);
  assert.deepEqual(keys({ value_cents: 12999, quantity: 2, 'cart.items': 3 }), ['value_cents', 'quantity', 'cart.items']);
  assert.deepEqual(keys({ order_id: 12345, id: 7, 'user.id': 9, userId: 'u1', zip: 94107, status: 200, port: 8080, phone: 5551234, card_number: 4111, year: 2026, version: 3 }), []);
  assert.deepEqual(keys({ currency: 'USD', paid: true, amount: '12.50', refund: -5 }), []);
});

test('names are validated', () => {
  for (const ok of ['orders', 'order.placed', 'http.server/latency', 'a_b-c']) assert.equal(safe.validName(ok), true);
  for (const bad of ['', ' x', '1abc', 'has space', 'x'.repeat(300), 5, null, undefined, {}]) assert.equal(safe.validName(bad), false);
});
