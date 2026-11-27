// tracemelt UI. Status: prototype.
// No framework, no build step, no third-party requests. Every value from the API is
// written with textContent or as an attribute, never parsed as HTML.

const view = document.getElementById("view");
const bar = document.getElementById("bar");
const tabs = document.getElementById("tabs");
const slab = document.getElementById("tabs-slab");
const rangeBox = document.getElementById("range");

const RANGES = [["15m", 15], ["1h", 60], ["6h", 360], ["24h", 1440]];
const SERIES = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6"];
const SVG = "http://www.w3.org/2000/svg";

let range = Number(localStorage.getItem("tracemelt.range")) || 60;
let timer = null;      // auto-refresh for the current view
let ticker = null;     // "updated Ns ago" clock
let token = 0;         // bumps on every navigation so late responses are dropped
let serviceOrder = []; // fixed colour order: a service keeps its colour for the session

// ---------- DOM helpers ----------

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

// replaceChildren that accepts nested arrays and skips null and false.
function fill(el, ...kids) {
  el.replaceChildren(...kids.flat(Infinity).filter((k) => k != null && k !== false)
    .map((k) => (k.nodeType ? k : document.createTextNode(String(k)))));
}

function s(tag, attrs, ...kids) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v != null) el.setAttribute(k, v);
  for (const kid of kids) if (kid != null) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return el;
}

// House marks. A split drop for a failure, a wedge for a warning.
function mark(kind) {
  const svg = s("svg", { viewBox: "0 0 12 12", "aria-hidden": "true" });
  if (kind === "fail") {
    svg.append(s("path", { fill: "currentColor", d: "M6 .6 10 6.2a4.3 4.3 0 0 1-3.3 5.1L7.6 8 4.9 6.6 6.3 4 4.2 3.1Z" }),
               s("path", { fill: "currentColor", d: "M3.4 4.3 4.9 5 3.5 7.2l2.6 1.4-.8 2.7A4.3 4.3 0 0 1 2 6.2Z" }));
  } else {
    svg.append(s("path", { fill: "currentColor", d: "M6 1.2 11.2 10.6H.8ZM5.3 4.6v3h1.4v-3Zm0 3.8v1.2h1.4V8.4Z", "fill-rule": "evenodd" }));
  }
  return svg;
}

// ---------- formatting ----------

const parseTime = (t) => new Date(t.endsWith("Z") ? t : t + "Z");
const pad = (n, w = 2) => String(n).padStart(w, "0");
function clock(t, ms = false) {
  const d = parseTime(t);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}` + (ms ? `.${pad(d.getMilliseconds(), 3)}` : "");
}
function dayClock(t) {
  const d = parseTime(t);
  const today = new Date().toDateString() === d.toDateString();
  return (today ? "" : `${d.toLocaleString("en", { month: "short" })} ${d.getDate()} `) + clock(t);
}
function dur(ns) {
  if (ns >= 1e9) return `${(ns / 1e9).toFixed(2)} s`;
  if (ns >= 1e6) return `${(ns / 1e6).toFixed(ns >= 1e8 ? 0 : 1)} ms`;
  if (ns >= 1e3) return `${Math.round(ns / 1e3)} µs`;
  return `${ns} ns`;
}
const count = (n) => Number(n).toLocaleString("en");
const plural = (n, one, many) => `${count(n)} ${Number(n) === 1 ? one : many || one + "s"}`;
const rangeWords = () => ({ 15: "15 minutes", 60: "hour", 360: "6 hours", 1440: "24 hours" })[range];
function num(v) {
  const a = Math.abs(v);
  return a >= 100 ? v.toFixed(0) : a >= 10 ? v.toFixed(1) : v.toFixed(2);
}

// ---------- services and colour ----------

function colour(service) {
  let i = serviceOrder.indexOf(service);
  if (i < 0) { serviceOrder.push(service); i = serviceOrder.length - 1; }
  return i < SERIES.length ? `var(${SERIES[i]})` : "var(--s-other)";
}
function svc(service) {
  const dot = h("i");
  dot.style.setProperty("--c", colour(service));
  return h("span", { class: "svc" }, dot, service || "unknown");
}
// Key for a line series: a short stroke of the series colour, as the legend mirrors the mark.
function lineKey(service) {
  const stroke = h("i");
  stroke.style.setProperty("--c", colour(service));
  return h("span", { class: "svc key" }, stroke, service || "unknown");
}

async function primeServices() {
  const rows = await api("/services?since_minutes=1440");
  // Busiest services first, so the ones people look at get the six distinct colours.
  for (const r of rows.slice().sort((a, b) => b.spans - a.spans || a.service.localeCompare(b.service))) colour(r.service);
  return rows;
}

// ---------- API ----------

class SignedOut extends Error {}

async function api(path) {
  const res = await fetch("/api" + path, { headers: { Accept: "application/json" } });
  if (res.status === 401) throw new SignedOut();
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* keep status text */ }
    throw new Error(typeof detail === "string" ? detail : "request rejected");
  }
  return res.json();
}

const qs = (o) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) if (v !== "" && v != null && v !== false) p.set(k, v);
  return p.toString();
};

// ---------- shell ----------

function buildRange() {
  fill(rangeBox, ...RANGES.map(([label, minutes]) =>
    h("button", {
      type: "button", "aria-pressed": String(minutes === range), title: `Last ${label}`,
      onclick: () => { range = minutes; localStorage.setItem("tracemelt.range", String(minutes)); buildRange(); route(); },
    }, label)));
}

function moveSlab(name) {
  let active = null;
  for (const a of tabs.querySelectorAll("a")) {
    const on = a.dataset.view === name;
    if (on) { a.setAttribute("aria-current", "page"); active = a; } else a.removeAttribute("aria-current");
  }
  if (!active) { slab.style.width = "0"; return; }
  slab.style.width = `${active.offsetWidth}px`;
  slab.style.transform = `translateX(${active.offsetLeft}px)`;
}

function stopTimers() {
  clearInterval(timer); clearInterval(ticker);
  timer = ticker = null;
}

function freshness(sub) {
  const tick = h("span", { class: "tick" });
  let at = Date.now();
  const paint = () => { tick.textContent = `updated ${Math.max(0, Math.round((Date.now() - at) / 1000))}s ago`; };
  paint();
  sub.append(" ", tick);
  clearInterval(ticker);
  ticker = setInterval(paint, 1000);
  return () => { at = Date.now(); paint(); };
}

// Runs load() now and every 10 seconds while the tab is visible. load(first) paints the view.
function live(load) {
  const mine = token;
  const run = async (first) => {
    if (document.hidden && !first) return;
    try {
      await load(first, () => mine === token);
    } catch (err) {
      if (mine !== token) return;
      if (err instanceof SignedOut) return showSignIn();
      if (first) fill(view, h("p", { class: "notice err" }, `Could not load this view: ${err.message}.`));
    }
  };
  run(true);
  timer = setInterval(() => run(false), 10000);
}

function empty(text) {
  return h("p", { class: "notice" }, text);
}

function serviceSelect(value, onchange) {
  const sel = h("select", { name: "service", "aria-label": "Service", onchange: (e) => onchange(e.target.value) },
    h("option", { value: "" }, "All services"),
    serviceOrder.map((name) => h("option", { value: name, selected: name === value }, name)));
  return sel;
}

// ---------- overview ----------

function overview() {
  const lede = h("h1", { class: "lede figure" });
  const sub = h("p", { class: "sub" });
  const body = h("div");
  fill(view, lede, sub, body);
  let touch = null;

  live(async (first, current) => {
    if (first) await primeServices().catch(() => []);
    const [services, failed] = await Promise.all([
      api(`/services?${qs({ since_minutes: range })}`),
      api(`/traces?${qs({ since_minutes: range, errors_only: true, limit: 8 })}`),
    ]);
    if (!current()) return;

    const spans = services.reduce((a, r) => a + Number(r.spans), 0);
    const bad = services.reduce((a, r) => a + Number(r.error_spans), 0);
    if (!services.length) {
      fill(lede, `No spans in the last ${rangeWords()}.`);
      fill(sub, "Send OTLP to the collector, or start the demo workload, and this page fills in.");
      fill(body, );
    } else {
      fill(lede, `${plural(services.length, "service")}, ${plural(spans, "span")}, `,
        bad ? h("span", { class: "bad" }, `${count(bad)} failed`) : "none failed", ".");
      fill(sub, `Last ${rangeWords()}.`);
      touch = freshness(sub);
      const worst = Math.max(...services.map((r) => r.error_spans / r.spans), 0.05);   // bar scale: the worst service, at least 5%
      fill(body, 
        h("div", { class: "scroll" }, h("table", { class: "table" },
          h("thead", {}, h("tr", {}, h("th", {}, "Service"), h("th", { class: "num" }, "Spans"),
            h("th", { class: "num" }, "Failed"), h("th", {}, "Failure rate ", h("span", { class: "note" }, `bar full at ${(worst * 100).toFixed(worst < 0.1 ? 1 : 0)}%`)))),
          h("tbody", {}, services.map((r) => {
            const rate = r.error_spans / r.spans;
            const fill = h("i");
            fill.style.width = `${(rate / worst) * 100}%`;
            return h("tr", { class: "link", tabindex: "0", onclick: () => go("traces", { service: r.service }),
              onkeydown: (e) => { if (e.key === "Enter") go("traces", { service: r.service }); } },
              h("td", {}, svc(r.service)), h("td", { class: "num" }, count(r.spans)),
              h("td", { class: "num" }, count(r.error_spans)),
              h("td", {}, h("div", { class: "meter" }, h("span", {}, `${(rate * 100).toFixed(1)}%`), h("div", {}, fill))));
          })))),
        h("h2", {}, failed.length ? "Latest failed traces" : "No failed traces in this window"),
        failed.length ? traceTable(failed) : null);
    }
    if (!first && touch) touch();
  });
}

// ---------- traces ----------

function traceTable(rows) {
  const longest = Math.max(...rows.map((r) => Number(r.duration_ns)), 1);
  return h("div", { class: "scroll" }, h("table", { class: "table" },
    h("thead", {}, h("tr", {}, h("th", {}, "Started"), h("th", {}, "Entry span"), h("th", {}, "Service"),
      h("th", {}, "Duration"), h("th", { class: "num" }, "Spans"), h("th", {}, "Outcome"))),
    h("tbody", {}, rows.map((r) => {
      const fill = h("i");
      fill.style.width = `${Math.max(2, (r.duration_ns / longest) * 100)}%`;
      const bad = Number(r.error_spans) > 0;
      const open = () => go(`trace/${r.trace_id}`);
      return h("tr", { class: "link", tabindex: "0", onclick: open, onkeydown: (e) => { if (e.key === "Enter") open(); } },
        h("td", { class: "mono dim" }, dayClock(r.started_at)),
        h("td", {}, r.first_span),
        h("td", {}, svc(r.first_service)),
        h("td", {}, h("div", { class: bad ? "dur bad" : "dur" }, h("span", {}, dur(Number(r.duration_ns))), h("div", {}, fill))),
        h("td", { class: "num" }, count(r.spans)),
        h("td", {}, bad ? h("span", { class: "failed" }, mark("fail"), `${count(r.error_spans)} failed`) : h("span", { class: "dim" }, "ok")));
    }))));
}

function traces(params) {
  let service = params.get("service") || "";
  let errorsOnly = params.get("errors") === "1";
  const lede = h("h1", { class: "lede wide" }, "Traces");
  const sub = h("p", { class: "sub" });
  const tools = h("div", { class: "tools" });
  const body = h("div");
  fill(view, lede, sub, tools, body);

  const restart = () => go("traces", { service, errors: errorsOnly ? "1" : "" });
  primeServices().catch(() => []).finally(() => {
    fill(tools, 
      serviceSelect(service, (v) => { service = v; restart(); }),
      h("label", { class: "check" },
        h("input", { type: "checkbox", name: "errors", checked: errorsOnly, onchange: (e) => { errorsOnly = e.target.checked; restart(); } }),
        "Failed only"));
  });

  let touch = null;
  live(async (first, current) => {
    const rows = await api(`/traces?${qs({ since_minutes: range, limit: 100, service, errors_only: errorsOnly })}`);
    if (!current()) return;
    fill(sub, rows.length ? `${plural(rows.length, "trace")} in the last ${rangeWords()}, newest first.` : "");
    if (rows.length) touch = freshness(sub);
    fill(body, rows.length ? traceTable(rows)
      : empty(`No ${errorsOnly ? "failed " : ""}traces${service ? ` for ${service}` : ""} in the last ${rangeWords()}.`));
    if (!first && touch) touch();
  });
}

// ---------- one trace: the waterfall ----------

function orderSpans(spans) {
  const ids = new Set(spans.map((x) => x.span_id));
  const kids = new Map();
  const roots = [];
  for (const sp of spans) {
    if (sp.parent_span_id && ids.has(sp.parent_span_id)) {
      if (!kids.has(sp.parent_span_id)) kids.set(sp.parent_span_id, []);
      kids.get(sp.parent_span_id).push(sp);
    } else roots.push(sp);
  }
  const out = [];
  const walk = (sp, depth) => {
    out.push({ ...sp, depth });
    for (const k of (kids.get(sp.span_id) || []).sort((a, b) => a.t0 - b.t0)) walk(k, depth + 1);
  };
  roots.sort((a, b) => a.t0 - b.t0).forEach((r) => walk(r, 0));
  return out;
}

function attrList(obj) {
  const keys = Object.keys(obj || {}).sort();
  if (!keys.length) return h("p", {}, "No attributes.");
  return h("dl", { class: "attrs" }, keys.map((k) => [h("dt", {}, k), h("dd", {}, String(obj[k]))]));
}

async function trace(id) {
  const mine = token;
  fill(view, empty("Loading trace."));
  let spans, logs;
  try {
    await primeServices().catch(() => []);
    [spans, logs] = await Promise.all([
      api(`/traces/${id}`),
      api(`/logs?${qs({ trace_id: id, since_minutes: 10080, limit: 200 })}`),
    ]);
  } catch (err) {
    if (mine !== token) return;
    if (err instanceof SignedOut) return showSignIn();
    fill(view, h("h1", { class: "lede wide" }, "Trace not available"),
      h("p", { class: "notice err" }, `${err.message}. It may be older than the retention period.`),
      h("p", {}, h("a", { class: "jump", href: "#/traces" }, "Back to traces")));
    return;
  }
  if (mine !== token) return;

  for (const sp of spans) { sp.t0 = parseTime(sp.started_at).getTime() * 1e6; sp.d = Number(sp.duration_ns); }
  const start = Math.min(...spans.map((x) => x.t0));
  const total = Math.max(...spans.map((x) => x.t0 + x.d)) - start || 1;
  const ordered = orderSpans(spans);
  const root = ordered[0];
  const bad = spans.filter((x) => x.is_error).length;
  const services = [...new Set(spans.map((x) => x.service))];

  const rows = h("div", { class: "wf-rows" });
  let openRow = null;
  ordered.forEach((sp) => {
    const left = ((sp.t0 - start) / total) * 100;
    const width = Math.max((sp.d / total) * 100, 0.15);
    const barEl = h("div", { class: sp.is_error ? "wf-bar bad" : "wf-bar" });
    barEl.style.left = `${left}%`;
    barEl.style.width = `${width}%`;
    barEl.style.setProperty("--c", colour(sp.service));
    const dot = h("i");
    dot.style.setProperty("--c", colour(sp.service));
    const name = h("div", { class: "wf-name" }, dot, h("span", { title: `${sp.service}: ${sp.name}` }, sp.name), sp.is_error ? mark("fail") : null);
    name.style.setProperty("--depth", String(Math.min(sp.depth, 8)));

    const detail = h("div", { class: "wf-detail", hidden: true },
      sp.is_error ? h("p", { class: "bad" }, sp.status_message || "This span failed.") : null,
      h("p", {}, `${sp.service}, ${String(sp.kind).replace(/^SPAN_KIND_/i, "").toLowerCase() || "internal"} span, started ${dur(sp.t0 - start)} into the trace.`),
      attrList({ ...sp.attributes, span_id: sp.span_id }));
    const row = h("button", {
      class: "wf-row", type: "button", "aria-expanded": "false",
      "aria-label": `${sp.name}, ${sp.service}, ${dur(sp.d)}${sp.is_error ? ", failed" : ""}`,
      onclick: () => {
        const opening = detail.hidden;
        if (openRow) { openRow.row.setAttribute("aria-expanded", "false"); openRow.detail.hidden = true; }
        if (opening) { row.setAttribute("aria-expanded", "true"); detail.hidden = false; openRow = { row, detail }; } else openRow = null;
      },
    }, name, h("span", { class: "wf-d" }, dur(sp.d)), h("div", { class: "wf-lane" }, barEl));
    rows.append(row, detail);
  });

  const scale = h("div", { class: "wf-scale" }, [0, 0.25, 0.5, 0.75, 1].map((f) => {
    const t = h("span", { class: f === 1 ? "last" : null }, f === 0 ? "0" : dur(total * f));
    t.style.left = `${f * 100}%`;
    return t;
  }));

  // Time cursor: a guide that follows the pointer across the lanes, with its offset on the axis.
  const line = h("i");
  const cursor = h("div", { class: "wf-cursor", hidden: true }, line);
  const at = h("span", { class: "at", hidden: true });
  scale.append(at);
  rows.append(cursor);
  const hideCursor = () => { cursor.hidden = true; at.hidden = true; };
  rows.addEventListener("pointerleave", hideCursor);
  rows.addEventListener("pointermove", (e) => {
    if (!e.target.closest(".wf-row")) return hideCursor();
    cursor.hidden = false;
    const box = cursor.getBoundingClientRect();
    const f = (e.clientX - box.left) / box.width;
    if (f < 0 || f > 1) return hideCursor();
    line.style.left = `${f * 100}%`;
    at.hidden = false;
    at.textContent = dur(total * f);
    at.style.left = `${f * 100}%`;
    at.className = f > 0.9 ? "at flip" : "at";
    if (f < 0.06) at.style.transform = "none"; else at.style.removeProperty("transform");
  });

  fill(view, 
    h("h1", { class: "lede wide" }, root.name),
    h("p", { class: "trace-meta" },
      h("span", {}, "took ", h("b", {}, dur(total))),
      h("span", {}, h("b", {}, count(spans.length)), spans.length === 1 ? " span" : " spans", " across ", plural(services.length, "service")),
      bad ? h("span", { class: "failed" }, mark("fail"), `${count(bad)} failed`) : h("span", {}, "no failures"),
      h("span", {}, "started ", h("b", {}, dayClock(root.started_at))),
      h("span", {}, "id ", h("b", {}, id))),
    h("div", { class: "wf" }, h("div", { class: "wf-axis" }, h("div"), h("div"), scale), rows),
    h("div", { class: "legend" }, services.map(svc)),
    h("h2", {}, logs.length ? `${plural(logs.length, "log record")} from this trace` : "No log records carry this trace id"),
    logs.length ? logTable(logs.slice().reverse(), false) : null);
}

// ---------- logs and events ----------

function severity(text) {
  const level = (text || "").toUpperCase();
  const known = ["ERROR", "FATAL", "WARN", "INFO", "DEBUG", "TRACE"].includes(level);
  return h("span", { class: `sev ${known ? level : "other"}` },
    level === "ERROR" || level === "FATAL" ? mark("fail") : level === "WARN" ? mark("warn") : null, level || "none");
}

function summary(attrs, skip = []) {
  const keys = Object.keys(attrs || {}).filter((k) => !skip.includes(k)).sort();
  return h("span", { class: "kv" }, keys.map((k, i) => [i ? "  " : "", h("b", {}, `${k}=`), String(attrs[k])]));
}

function logTable(rows, withJump = true) {
  return h("div", { class: "scroll" }, h("table", { class: "table" },
    h("thead", {}, h("tr", {}, h("th", {}, "Time"), h("th", {}, "Level"), h("th", {}, "Service"), h("th", {}, "Message"),
      withJump ? h("th", {}, "") : null)),
    h("tbody", {}, rows.map((r) => h("tr", {},
      h("td", { class: "mono dim" }, withJump ? dayClock(r.timestamp) : clock(r.timestamp, true)),
      h("td", {}, severity(r.severity)),
      h("td", {}, svc(r.service)),
      h("td", { class: "body" }, r.body, Object.keys(r.attributes || {}).length ? [h("br"), summary(r.attributes)] : null),
      withJump ? h("td", { class: "act" }, r.trace_id ? h("a", { class: "jump", href: `#/trace/${r.trace_id}` }, "Open trace") : null) : null)))));
}

function logs(params) {
  let service = params.get("service") || "";
  let q = params.get("q") || "";
  const sub = h("p", { class: "sub" });
  const tools = h("div", { class: "tools" });
  const body = h("div");
  fill(view, h("h1", { class: "lede wide" }, "Logs"), sub, tools, body);

  const restart = () => go("logs", { service, q });
  const search = h("input", { type: "search", name: "q", value: q, maxlength: "200", placeholder: "Text in the message", "aria-label": "Search log messages" });
  const form = h("form", { class: "tools", onsubmit: (e) => { e.preventDefault(); q = search.value.trim(); restart(); } }, search);
  tools.replaceWith(form);
  primeServices().catch(() => []).finally(() => form.append(serviceSelect(service, (v) => { service = v; q = search.value.trim(); restart(); })));

  let touch = null;
  live(async (first, current) => {
    const rows = await api(`/logs?${qs({ since_minutes: range, limit: 200, service, q })}`);
    if (!current()) return;
    fill(sub, rows.length ? `${rows.length === 200 ? "Latest 200 records" : plural(rows.length, "record")} in the last ${rangeWords()}${q ? ` matching "${q}"` : ""}.` : "");
    if (rows.length) touch = freshness(sub);
    fill(body, rows.length ? logTable(rows) : empty(`No log records${q ? ` matching "${q}"` : ""} in the last ${rangeWords()}.`));
    if (!first && touch) touch();
  });
}

function events(params) {
  let service = params.get("service") || "";
  const sub = h("p", { class: "sub" });
  const tools = h("div", { class: "tools" });
  const body = h("div");
  fill(view, h("h1", { class: "lede wide" }, "Events"), sub, tools, body);
  primeServices().catch(() => []).finally(() =>
    fill(tools, serviceSelect(service, (v) => { service = v; go("events", { service }); })));

  let touch = null;
  live(async (first, current) => {
    const rows = await api(`/events?${qs({ since_minutes: range, limit: 200, service })}`);
    if (!current()) return;
    fill(sub, rows.length ? `${rows.length === 200 ? "Latest 200 events" : plural(rows.length, "event")} in the last ${rangeWords()}.` : "");
    if (rows.length) touch = freshness(sub);
    fill(body, rows.length ? h("div", { class: "scroll" }, h("table", { class: "table" },
      h("thead", {}, h("tr", {}, h("th", {}, "Time"), h("th", {}, "Event"), h("th", {}, "Service"), h("th", {}, "Attributes"), h("th", {}, ""))),
      h("tbody", {}, rows.map((r) => h("tr", {},
        h("td", { class: "mono dim" }, dayClock(r.timestamp)),
        h("td", { class: "mono" }, r.attributes["event.name"] || r.body),
        h("td", {}, svc(r.service)),
        h("td", {}, summary(r.attributes, ["tracemelt.event", "event.name"])),
        h("td", { class: "act" }, r.trace_id ? h("a", { class: "jump", href: `#/trace/${r.trace_id}` }, "Open trace") : null))))))
      : empty(`No events in the last ${rangeWords()}. An event is a log record with the attribute tracemelt.event set to "true".`));
    if (!first && touch) touch();
  });
}

// ---------- metrics ----------

function niceTicks(lo, hi, n = 4) {
  if (lo === hi) { lo -= 1; hi += 1; }
  const raw = (hi - lo) / n;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((m) => m >= raw);
  const a = Math.floor(lo / step) * step;
  const b = Math.ceil(hi / step) * step;
  const ticks = [];
  for (let v = a; v <= b + step / 2; v += step) ticks.push(Number(v.toFixed(10)));
  return ticks;
}

function drawChart(box, name, rows, showTable, stepSeconds) {
  const byService = new Map();
  for (const r of rows) {
    if (!byService.has(r.service)) byService.set(r.service, []);
    byService.get(r.service).push({ t: parseTime(r.bucket).getTime(), v: r.avg, min: r.min, max: r.max });
  }
  const series = [...byService.entries()].sort(([a], [b]) => a.localeCompare(b));
  const W = Math.max(box.clientWidth - 36, 320), H = 300;
  const m = { l: 52, r: 14, t: 10, b: 26 };
  const ts = rows.map((r) => parseTime(r.bucket).getTime());
  const t0 = Math.min(...ts), t1 = Math.max(...ts) === t0 ? t0 + 60000 : Math.max(...ts);
  const ticks = niceTicks(Math.min(...rows.map((r) => r.avg)), Math.max(...rows.map((r) => r.avg)));
  const y0 = ticks[0], y1 = ticks[ticks.length - 1];
  // Direct end labels only when there are few series and their ends are clear of each other.
  // Converging ends are never nudged apart: the legend and the tooltip carry identity instead.
  const endYs = series.map(([, pts]) => (1 - (pts[pts.length - 1].v - y0) / (y1 - y0)) * (H - m.t - m.b)).sort((a, b) => a - b);
  const direct = series.length >= 2 && series.length <= 4 && endYs.every((v, i) => i === 0 || v - endYs[i - 1] >= 16);
  if (direct) m.r = 104;
  const places = ticks.every((v) => Number.isInteger(v)) ? 0 : ticks.every((v) => Number.isInteger(v * 10)) ? 1 : 2;
  const x = (t) => m.l + ((t - t0) / (t1 - t0)) * (W - m.l - m.r);
  const y = (v) => m.t + (1 - (v - y0) / (y1 - y0)) * (H - m.t - m.b);

  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": `${name}, average per service over time. Use the arrow keys to read values.` });
  for (const v of ticks) {
    svg.append(s("line", { class: "grid", x1: m.l, x2: W - m.r, y1: y(v), y2: y(v) }),
      s("text", { class: "axis", x: m.l - 10, y: y(v), "text-anchor": "end", "dominant-baseline": "central" }, v.toFixed(places)));
  }
  for (let i = 0; i <= 4; i++) {
    const t = t0 + ((t1 - t0) * i) / 4;
    const d = new Date(t);
    svg.append(s("text", { class: "axis", x: x(t), y: H - 6, "text-anchor": i === 0 ? "start" : i === 4 ? "end" : "middle" }, `${pad(d.getHours())}:${pad(d.getMinutes())}`));
  }
  const ends = [];
  for (const [service, pts] of series) {
    const c = colour(service);
    // A gap of more than two buckets is missing data: the line breaks there and is never drawn across it.
    const gap = stepSeconds * 2500;
    const d = pts.map((p, i) => {
      const at = `${x(p.t).toFixed(1)} ${y(p.v).toFixed(1)}`;
      return i && p.t - pts[i - 1].t <= gap ? `L${at}` : `M${at}l0 0`;
    }).join("");
    const line = s("path", { class: "line", d });
    line.style.stroke = c;
    const last = pts[pts.length - 1];
    const end = s("circle", { class: "end", cx: x(last.t), cy: y(last.v), r: 4.5 });
    end.style.fill = c;
    svg.append(line, end);
    ends.push({ service, y: y(last.v), x: x(last.t) });
  }
  if (direct) for (const e of ends) svg.append(s("text", { class: "endlabel", x: e.x + 12, y: e.y, "dominant-baseline": "central" }, e.service));

  // hover layer: crosshair and tooltip, snapped to the nearest bucket
  const buckets = [...new Set(ts)].sort((a, b) => a - b);
  const cross = s("line", { class: "cross", y1: m.t, y2: H - m.b, visibility: "hidden" });
  const hit = s("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" });
  svg.append(cross, hit);
  const tip = h("div", { class: "tip", hidden: true });
  const hide = () => { tip.hidden = true; cross.setAttribute("visibility", "hidden"); };
  let at = buckets.length - 1;
  const show = (i) => {
    at = Math.min(Math.max(i, 0), buckets.length - 1);
    const near = buckets[at];
    const r = svg.getBoundingClientRect();
    cross.setAttribute("x1", x(near)); cross.setAttribute("x2", x(near)); cross.setAttribute("visibility", "visible");
    const d = new Date(near);
    fill(tip, h("time", {}, `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`),
      series.map(([service, pts]) => {
        const p = pts.find((q) => q.t === near);
        return p ? h("div", {}, h("b", {}, num(p.v)), lineKey(service)) : null;
      }));
    tip.hidden = false;
    const box2 = box.getBoundingClientRect();
    const tx = r.left - box2.left + (x(near) / W) * r.width;
    const flip = tx + tip.offsetWidth + 24 > box2.width;
    tip.style.transform = `translate(${flip ? tx - tip.offsetWidth - 14 : tx + 14}px, ${r.top - box2.top + 14}px)`;
  };
  hit.addEventListener("pointerleave", () => { if (document.activeElement !== svg) hide(); });
  hit.addEventListener("pointermove", (e) => {
    const r = svg.getBoundingClientRect();
    const t = t0 + ((((e.clientX - r.left) / r.width) * W - m.l) / (W - m.l - m.r)) * (t1 - t0);
    show(buckets.reduce((best, b, i) => (Math.abs(b - t) < Math.abs(buckets[best] - t) ? i : best), 0));
  });
  // Keyboard reads the same values as hover: focus the chart, then use the arrow keys.
  svg.setAttribute("tabindex", "0");
  svg.addEventListener("focus", () => show(at));
  svg.addEventListener("blur", hide);
  svg.addEventListener("keydown", (e) => {
    const move = { ArrowLeft: -1, ArrowRight: 1, Home: -buckets.length, End: buckets.length }[e.key];
    if (move) { e.preventDefault(); show(at + move); }
    if (e.key === "Escape") svg.blur();
  });

  const table = h("div", { class: "scroll" }, h("table", { class: "table" },
    h("thead", {}, h("tr", {}, h("th", {}, "Time"), h("th", {}, "Service"), h("th", { class: "num" }, "Avg"), h("th", { class: "num" }, "Min"), h("th", { class: "num" }, "Max"))),
    h("tbody", {}, rows.slice().reverse().slice(0, 300).map((r) => h("tr", {},
      h("td", { class: "mono dim" }, dayClock(r.bucket)), h("td", {}, svc(r.service)),
      h("td", { class: "num" }, num(r.avg)), h("td", { class: "num" }, num(r.min)), h("td", { class: "num" }, num(r.max)))))));

  return showTable ? [table] : [svg, tip];
}

function metrics(params) {
  let selected = params.get("name") || "";
  let asTable = false;
  let lastRows = null;
  const sub = h("p", { class: "sub" });
  const names = h("div", { class: "names" });
  const chart = h("div", { class: "chart" });
  fill(view, h("h1", { class: "lede wide" }, "Metrics"), sub, h("div", { class: "metrics" }, names, chart));

  const step = () => Math.max(10, Math.round((range * 60) / 120 / 10) * 10);
  const paint = () => {
    if (!lastRows) return;
    const toggle = h("button", { class: "quiet", type: "button", "aria-pressed": String(asTable),
      onclick: () => { asTable = !asTable; paint(); } }, asTable ? "Show chart" : "Show as table");
    const services = [...new Set(lastRows.map((r) => r.service))].sort();
    fill(chart, h("h3", {}, selected),
      h("p", { class: "unit" }, `Average per service, ${step()} second buckets.`),
      ...(lastRows.length ? drawChart(chart, selected, lastRows, asTable, step()) : [empty("No data points in this window.")]),
      h("div", { class: "chart-foot" }, h("div", { class: "legend" }, services.length > 1 && !asTable ? services.map(lineKey) : null), lastRows.length ? toggle : null));
  };
  let resize = null;
  const onResize = () => { clearTimeout(resize); resize = setTimeout(() => { if (chart.isConnected) paint(); else removeEventListener("resize", onResize); }, 150); };
  addEventListener("resize", onResize);

  let touch = null;
  live(async (first, current) => {
    await primeServices().catch(() => []);
    const list = await api(`/metrics?${qs({ since_minutes: range })}`);
    if (!current()) return;
    const gauges = list.filter((mt) => mt.chartable).map((mt) => mt.name).sort();
    const sums = list.filter((mt) => !mt.chartable).map((mt) => mt.name).sort();
    if (!gauges.includes(selected)) selected = gauges[0] || "";
    fill(names, 
      gauges.map((n) => h("button", { type: "button", "aria-pressed": String(n === selected), onclick: () => go("metrics", { name: n }) }, n)),
      sums.length ? [h("p", {}, "Stored, not chartable yet"), sums.map((n) => h("span", {}, n))] : null);
    if (!selected) {
      fill(sub, "");
      fill(chart, empty(`No gauge metrics in the last ${rangeWords()}.`));
      return;
    }
    lastRows = await api(`/metrics/gauge?${qs({ name: selected, since_minutes: range, step_seconds: step() })}`);
    if (!current()) return;
    fill(sub, `${plural(gauges.length, "gauge")} in the last ${rangeWords()}.`);
    touch = freshness(sub);
    if (first || !chart.querySelector(".tip:not([hidden])")) paint();   // do not redraw under the pointer
  });
}

// ---------- sign in ----------

function showSignIn(message) {
  stopTimers();
  token++;
  bar.hidden = true;
  const input = h("input", { type: "password", name: "token", autocomplete: "current-password", required: true,
    placeholder: "API token", "aria-label": "API token" });
  const note = h("p", { class: "notice err", role: "alert" }, message || "");
  const form = h("form", {
    onsubmit: async (e) => {
      e.preventDefault();
      note.textContent = "";
      try {
        const res = await fetch("/api/session", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token: input.value.trim() }) });
        if (res.status === 204) { input.value = ""; return start(); }
        note.textContent = res.status === 401 ? "That token was not accepted." : `Sign in failed (${res.status}).`;
      } catch { note.textContent = "The API did not answer."; }
    },
  },
  h("span", { class: "wordmark" }, "tracemelt"),
  h("p", {}, "Paste the value of TRACEMELT_API_TOKEN from the .env file of this stack."),
  h("div", { class: "row" }, input, h("button", { type: "submit" }, "Sign in")), note);
  fill(view, h("div", { class: "signin" }, form));
  input.focus();
}

// ---------- routing ----------

function go(path, params = {}) {
  const query = qs(params);
  const next = `#/${path}${query ? `?${query}` : ""}`;
  if (location.hash === next) route(); else location.hash = next;
}

function route() {
  stopTimers();
  token++;
  const [path, query] = location.hash.replace(/^#\/?/, "").split("?");
  const params = new URLSearchParams(query || "");
  const [name, arg] = path.split("/");
  bar.hidden = false;
  const tab = name === "trace" ? "traces" : name || "overview";
  moveSlab(tab);
  document.title = `${tab[0].toUpperCase()}${tab.slice(1)} · tracemelt`;
  if (name === "traces") traces(params);
  else if (name === "trace" && /^[0-9a-f]{32}$/.test(arg || "")) trace(arg);
  else if (name === "logs") logs(params);
  else if (name === "metrics") metrics(params);
  else if (name === "events") events(params);
  else overview();
}

async function start() {
  try {
    await api("/session");
  } catch (err) {
    return showSignIn(err instanceof SignedOut ? "" : "The API did not answer.");
  }
  buildRange();
  route();
  if (document.fonts) document.fonts.ready.then(() => moveSlab(tabs.querySelector('[aria-current="page"]')?.dataset.view));
}

document.getElementById("sign-out").addEventListener("click", async () => {
  await fetch("/api/session", { method: "DELETE" }).catch(() => {});
  showSignIn();
});
addEventListener("hashchange", route);
addEventListener("resize", () => moveSlab(tabs.querySelector('[aria-current="page"]')?.dataset.view));
start();
