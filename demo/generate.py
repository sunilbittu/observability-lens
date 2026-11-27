"""tracemelt demo workload. Status: prototype.

Emits a small shop (storefront -> inventory, payments) as OTLP/HTTP JSON so the
stack has traces, correlated logs, events and gauges to show. Standard library
only. Payments degrades for 3 minutes out of every 12 so there are errors to find.
"""

import json
import os
import random
import secrets
import time
import urllib.request

ENDPOINT = os.environ["TRACEMELT_ENDPOINT"].rstrip("/")
TOKEN = os.environ["TRACEMELT_INGEST_TOKEN"]
MS = 1_000_000

PRODUCTS = ["kettle", "desk-lamp", "notebook", "backpack", "headphones"]


def attrs(d):
    out = []
    for k, v in d.items():
        if isinstance(v, bool):
            out.append({"key": k, "value": {"boolValue": v}})
        elif isinstance(v, int):
            out.append({"key": k, "value": {"intValue": str(v)}})
        elif isinstance(v, float):
            out.append({"key": k, "value": {"doubleValue": v}})
        else:
            out.append({"key": k, "value": {"stringValue": str(v)}})
    return out


def resource(service):
    return {"attributes": attrs({"service.name": service, "deployment.environment": "demo"})}


def post(path, body):
    req = urllib.request.Request(
        ENDPOINT + path, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + TOKEN})
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except Exception as exc:  # the demo must outlive a collector restart
        print("send failed:", exc, flush=True)


class Batch:
    def __init__(self):
        self.spans, self.logs = {}, {}

    def span(self, service, trace_id, name, kind, start, dur_ms, parent="", error=None, **a):
        span_id = secrets.token_hex(8)
        s = {"traceId": trace_id, "spanId": span_id, "name": name, "kind": kind,
             "startTimeUnixNano": str(start), "endTimeUnixNano": str(start + int(dur_ms * MS)),
             "attributes": attrs(a)}
        if parent:
            s["parentSpanId"] = parent
        if error:
            s["status"] = {"code": 2, "message": error}
        self.spans.setdefault(service, []).append(s)
        return span_id

    def log(self, service, ts, severity, body, trace_id="", span_id="", **a):
        rec = {"timeUnixNano": str(ts), "severityText": severity,
               "severityNumber": {"INFO": 9, "WARN": 13, "ERROR": 17}[severity],
               "body": {"stringValue": body}, "attributes": attrs(a)}
        if trace_id:
            rec["traceId"], rec["spanId"] = trace_id, span_id
        self.logs.setdefault(service, []).append(rec)

    def flush(self):
        if self.spans:
            post("/v1/traces", {"resourceSpans": [
                {"resource": resource(s), "scopeSpans": [{"scope": {"name": "demo"}, "spans": v}]}
                for s, v in self.spans.items()]})
        if self.logs:
            post("/v1/logs", {"resourceLogs": [
                {"resource": resource(s), "scopeLogs": [{"scope": {"name": "demo"}, "logRecords": v}]}
                for s, v in self.logs.items()]})


def degraded():
    return int(time.time()) % 720 < 180


def browse(b):
    t, now = secrets.token_hex(16), time.time_ns()
    q = random.uniform(4, 18)
    total = q + random.uniform(3, 9)
    root = b.span("storefront", t, "GET /products", 2, now, total, **{"http.request.method": "GET", "http.route": "/products", "http.response.status_code": 200})
    b.span("storefront", t, "SELECT products", 3, now + 2 * MS, q, root, **{"db.system": "postgresql", "db.operation.name": "SELECT"})
    b.log("storefront", now + int(total * MS), "INFO", "listed products", t, root, count=random.randint(8, 40))


def checkout(b):
    t, now = secrets.token_hex(16), time.time_ns()
    product, qty = random.choice(PRODUCTS), random.randint(1, 3)
    cents = qty * random.choice([1299, 2499, 4999, 12999])
    slow = degraded()
    inv = random.uniform(15, 45)
    pay = random.uniform(900, 2600) if slow else random.uniform(60, 180)
    failed = random.random() < (0.45 if slow else 0.02)
    total = 8 + inv + 6 + pay + 5
    err = "payment provider timeout" if failed else None

    root = b.span("storefront", t, "POST /checkout", 2, now, total, error=err, **{"http.request.method": "POST", "http.route": "/checkout", "http.response.status_code": 502 if failed else 200})
    c1 = b.span("storefront", t, "POST inventory/reserve", 3, now + 8 * MS, inv, root, **{"http.request.method": "POST", "server.address": "inventory"})
    s1 = b.span("inventory", t, "POST /reserve", 2, now + 10 * MS, inv - 4, c1, **{"http.route": "/reserve", "http.response.status_code": 200})
    b.span("inventory", t, "UPDATE stock", 3, now + 13 * MS, inv - 12, s1, **{"db.system": "postgresql", "db.operation.name": "UPDATE"})
    p0 = now + int((8 + inv + 6) * MS)
    c2 = b.span("storefront", t, "POST payments/charge", 3, p0, pay, root, error=err, **{"http.request.method": "POST", "server.address": "payments"})
    s2 = b.span("payments", t, "POST /charge", 2, p0 + 2 * MS, pay - 4, c2, error=err, **{"http.route": "/charge", "http.response.status_code": 504 if failed else 200})
    b.span("payments", t, "provider.authorize", 3, p0 + 6 * MS, pay - 12, s2, error=err, **{"peer.service": "card-provider"})

    b.log("inventory", now + 14 * MS, "INFO", f"reserved {qty} x {product}", t, s1, product=product, quantity=qty)
    end = now + int(total * MS)
    if failed:
        b.log("payments", p0 + int((pay - 6) * MS), "ERROR", "card provider did not answer in time", t, s2, **{"provider.latency_ms": int(pay)})
        b.log("storefront", end, "ERROR", "checkout failed: payment provider timeout", t, root, product=product)
        b.log("storefront", end, "INFO", "order.failed", t, root, **{"tracemelt.event": "true", "event.name": "order.failed", "reason": "payment_timeout", "value_cents": cents, "currency": "USD"})
    else:
        if slow:
            b.log("payments", p0 + int((pay - 6) * MS), "WARN", "card provider slow", t, s2, **{"provider.latency_ms": int(pay)})
        b.log("storefront", end, "INFO", "checkout complete", t, root, product=product)
        b.log("storefront", end, "INFO", "order.placed", t, root, **{"tracemelt.event": "true", "event.name": "order.placed", "product": product, "quantity": qty, "value_cents": cents, "currency": "USD"})


def gauges():
    now = str(time.time_ns())
    slow = degraded()
    rm = []
    for service, mem, queue in (("storefront", 210, 3), ("inventory", 150, 2), ("payments", 180, 40 if slow else 4)):
        def g(name, unit, value):
            return {"name": name, "unit": unit, "gauge": {"dataPoints": [{"timeUnixNano": now, "asDouble": value}]}}
        rm.append({"resource": resource(service), "scopeMetrics": [{"scope": {"name": "demo"}, "metrics": [
            g("process.memory.usage", "MiB", mem + random.uniform(-12, 12)),
            g("queue.depth", "{items}", max(0.0, queue + random.uniform(-2, queue * 0.4 + 2))),
        ]}]})
    post("/v1/metrics", {"resourceMetrics": rm})


def main():
    print("demo workload sending to", ENDPOINT, flush=True)
    last_gauge = 0.0
    while True:
        b = Batch()
        for _ in range(random.randint(1, 3)):
            (checkout if random.random() < 0.4 else browse)(b)
        b.flush()
        if time.time() - last_gauge >= 10:
            gauges()
            last_gauge = time.time()
        time.sleep(1)


if __name__ == "__main__":
    main()
