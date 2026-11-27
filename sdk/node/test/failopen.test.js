'use strict';
// Runs small applications in child processes, the way a user would, against collectors that misbehave.
const test = require('node:test');
const assert = require('node:assert/strict');
const net = require('node:net');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const root = path.join(__dirname, '..');
const APP = `
  const t = require(${JSON.stringify(root)});
  const api = require(${JSON.stringify(path.join(root, 'node_modules/@opentelemetry/api'))});
  t.init();
  api.trace.getTracer('app').startActiveSpan('work', (span) => {
    t.event('order.placed', { quantity: 1 });
    span.end();
  });
  t.count('requests'); t.gauge('queue', 1); t.timing('latency', 3);
  console.log('app result: 42');
  const started = Date.now();
  t.shutdown(Number(process.env.SHUTDOWN_MS || 5000)).then(() => { console.log('shutdown ms: ' + (Date.now() - started)); });
`;

function run(env, extraArgs = []) {
  const started = Date.now();
  const result = spawnSync(process.execPath, [...extraArgs, '-e', APP], {
    env: { PATH: process.env.PATH, TRACEMELT_NO_AUTO_INSTRUMENT: 'true', ...env }, encoding: 'utf8', timeout: 30000 });
  return { ...result, ms: Date.now() - started };
}

test('the app runs with no configuration at all', () => {
  const r = run({});
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /app result: 42/);
  assert.match(r.stderr, /telemetry is off: no endpoint set/);
});

test('the app runs with an invalid endpoint', () => {
  const r = run({ TRACEMELT_ENDPOINT: 'not a url' });
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /app result: 42/);
  assert.match(r.stderr, /endpoint is not a valid URL/);
});

test('the app runs when nothing listens on the collector port', () => {
  const r = run({ TRACEMELT_ENDPOINT: 'http://127.0.0.1:1', TRACEMELT_INGEST_TOKEN: 'x', TRACEMELT_SERVICE_NAME: 'app' });
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /app result: 42/);
  assert.ok(r.ms < 8000, `took ${r.ms} ms`);
});

test('the app runs with -r tracemelt/register and an unreachable collector', () => {
  const r = run({ TRACEMELT_ENDPOINT: 'http://127.0.0.1:1', TRACEMELT_SERVICE_NAME: 'app' }, ['-r', path.join(root, 'register.js')]);
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /app result: 42/);
});

test('a collector that accepts connections and never answers cannot hold the app past the shutdown timeout', async () => {
  const sockets = [];
  const server = net.createServer((socket) => { sockets.push(socket); socket.on('error', () => {}); });
  await new Promise((done) => server.listen(0, '127.0.0.1', done));
  const { port } = server.address();
  // spawnSync would block this process's event loop, so the server could not accept; use spawn.
  const { spawn } = require('node:child_process');
  const started = Date.now();
  const child = spawn(process.execPath, ['-e', APP], {
    env: { PATH: process.env.PATH, TRACEMELT_NO_AUTO_INSTRUMENT: 'true', TRACEMELT_ENDPOINT: `http://127.0.0.1:${port}`, TRACEMELT_SERVICE_NAME: 'app', SHUTDOWN_MS: '1000' } });
  let out = '';
  child.stdout.on('data', (d) => { out += d; });
  const code = await new Promise((done) => child.on('exit', done));
  const ms = Date.now() - started;
  for (const s of sockets) s.destroy();
  await new Promise((done) => server.close(done));
  assert.equal(code, 0);
  assert.match(out, /app result: 42/);
  const waited = Number((out.match(/shutdown ms: (\d+)/) || [])[1]);
  assert.ok(waited >= 900 && waited < 2500, `shutdown waited ${waited} ms for a 1000 ms timeout`);
  assert.ok(ms < 15000, `process took ${ms} ms to exit`);
});

test('console capture is opt-in and does not swallow output', () => {
  const app = `const t = require(${JSON.stringify(root)}); t.init(); console.log('hello'); console.error('oops'); t.shutdown(200);`;
  const r = spawnSync(process.execPath, ['-e', app], {
    env: { PATH: process.env.PATH, TRACEMELT_NO_AUTO_INSTRUMENT: 'true', TRACEMELT_ENDPOINT: 'http://127.0.0.1:1', TRACEMELT_CAPTURE_CONSOLE: 'true' }, encoding: 'utf8', timeout: 30000 });
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /hello/);
  assert.match(r.stderr, /oops/);
});
