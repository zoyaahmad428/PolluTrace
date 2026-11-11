/* PolluTrace console.
   Reads the JSON API in server.py and renders six views. No build step, no dependencies. */

const $ = (sel, root = document) => root.querySelector(sel);
const view = $("#view");

/* ------------------------------------------------------------------ utils */
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const pct = (x, d = 1) => (x === null || x === undefined || x === "") ? "–" : `${(x * 100).toFixed(d)}%`;
const num = (x, d = 1) => (x === null || x === undefined || x === "") ? "–" : Number(x).toFixed(d);
const int = (x) => (x === null || x === undefined || x === "") ? "–" : Math.round(Number(x)).toLocaleString();

async function api(path, opts) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({ error: `${r.status} ${r.statusText}` }));
  if (!r.ok) throw new Error(body.error || `Request failed (${r.status})`);
  return body;
}

/** A fully qualified Java test, with the package dimmed and the method picked out. */
function tn(t, opts = {}) {
  if (!t || !t.full) return `<span class="tn">–</span>`;
  const pkg = t.pkg && !opts.short ? `<span class="pkg">${esc(t.pkg)}.</span>` : "";
  return `<span class="tn" title="${esc(t.full)}">${pkg}${esc(t.cls)}<span class="m">${esc(t.method)}</span></span>`;
}

function chip(outcome) {
  if (!outcome) return `<span class="chip">–</span>`;
  return `<span class="chip ${esc(outcome)}">${esc(outcome.replace(/_/g, " "))}</span>`;
}

/** A measure bar in a fixed track, so bars in different rows are comparable at a glance. */
function bar(value, max, cls = "") {
  const w = max > 0 ? Math.max(1.5, (value / max) * 100) : 0;
  return `<span class="track"><span class="bar ${cls}" style="width:${w.toFixed(1)}%"></span></span>`;
}

/** The motif: a test order as a row of slots, with the polluter and the victim marked. */
function strip(len, polluterPos, animate = false) {
  if (!len) return "";
  const cap = Math.min(len, 64);
  const slots = [];
  for (let i = 0; i < cap; i++) {
    const real = Math.round((i / cap) * len);
    let cls = "slot";
    if (polluterPos !== null && polluterPos !== undefined && real === Math.round(polluterPos)) cls += " polluter";
    else if (i === cap - 1) cls += " victim";
    else if (polluterPos !== null && real > polluterPos) cls += " between";
    const delay = animate ? ` style="animation-delay:${(i * 14)}ms"` : "";
    slots.push(`<span class="${cls}"${delay}></span>`);
  }
  return `<div class="strip${animate ? " animate" : ""}" role="img"
    aria-label="Test order of ${len} tests; the polluter runs at position ${polluterPos ?? "unknown"} and the victim runs last and fails.">${slots.join("")}</div>`;
}

const stripLegend = (len, pos) => `<div class="strip-legend">
  <span><span class="key other"></span>${len} tests in the failing order</span>
  <span><span class="key polluter"></span>polluter at position ${pos ?? "–"}</span>
  <span><span class="key dirty"></span>running in a dirty JVM</span>
  <span><span class="key victim"></span>victim, runs last and fails</span>
</div>`;

function table(cols, rows, opts = {}) {
  const head = cols.map((c) => `<th class="${c.num ? "num" : ""}">${esc(c.label)}</th>`).join("");
  const body = rows.map((r) => {
    const attrs = r._attrs || "";
    const tds = cols.map((c) => `<td class="${c.num ? "num" : ""}">${r[c.key] ?? ""}</td>`).join("");
    return `<tr class="${r._cls || ""}" ${attrs}>${tds}</tr>`;
  }).join("");
  return `<div class="table-scroll panel"><table>
    ${opts.caption ? `<caption>${opts.caption}</caption>` : ""}
    <thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function sheet(title, html) {
  $("#sheet-title").textContent = title;
  $("#sheet-body").innerHTML = html;
  $("#sheet").hidden = false;
  $("#sheet .close").focus();
}
$("#sheet").addEventListener("click", (e) => {
  if (e.target.id === "sheet" || e.target.hasAttribute("data-close")) $("#sheet").hidden = true;
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#sheet").hidden = true; });

/* --------------------------------------------------------------- overview */
async function overview() {
  const d = await api("/api/overview");
  const h = d.headline;
  const hero = d.hero;
  const maxFix = Math.max(...d.systems.map((s) => s.fix_rate || 0));

  const heroPanel = hero ? `<section class="panel strip-wrap">
    <p class="verdict">Run ${tn(hero.polluter, { short: true })} ${hero.distance} tests earlier in the same JVM,
      and ${tn(hero.victim, { short: true })} fails — on a clean checkout of ${esc(hero.project)}, with nothing
      about the victim changed. PolluTrace finds the test that did it, names the state it left behind, and
      patches it.</p>
    ${strip(hero.order_len, hero.polluter_position, true)}
    ${stripLegend(hero.order_len, hero.polluter_position)}
    <div class="headline">
      <div><b>${h.fixed}/${h.victims}</b><span>victims repaired</span></div>
      <div><b>${pct(h.fix_rate, 0)}</b><span>fix rate</span></div>
      <div><b>${h.false_fixes}</b><span>patches that fail in another order</span></div>
      <div><b>${h.weak_false_fixes}</b><span>the same, judged the way earlier tools judge</span></div>
    </div>
  </section>` : `<section class="notice">No results yet. Run <code>python run_phase2.py</code> first.</section>`;

  const gapCards = `<section>
    <div class="section-head"><h2>The three gaps</h2>
      <p>Each one is a thing the base paper's pipeline cannot do, and a component here that tries to.</p></div>
    <div class="gap-grid">${d.gaps.map((g) => `
      <article class="gap" data-status="${esc(g.status)}">
        <span class="gid">${esc(g.gap)}</span>
        <h3>${esc(g.title)}</h3>
        <p>${esc(g.claim)}</p>
        <div class="ev"><div>${esc(g.evidence)}</div><div>${esc(g.second)}</div>
          <div><span class="chip ${g.status === "Addressed" ? "fixed" : g.status === "Not addressed" ? "compile_error" : ""}">${esc(g.status)}</span></div>
        </div>
      </article>`).join("")}</div>
  </section>`;

  const rows = d.systems.map((s) => ({
    _cls: s.key === "PolluTrace" ? "highlight" : "",
    system: `<b>${esc(s.label)}</b><br><span style="font-size:.78rem;color:var(--muted)">${esc(s.note)}</span>`,
    victims: int(s.victims),
    fixed: int(s.fixed),
    rate: `${pct(s.fix_rate)}${bar(s.fix_rate, maxFix)}`,
    precision: pct(s.precision),
    ff: `${pct(s.false_fix_rate)}${s.false_fix_rate ? bar(s.false_fix_rate, 0.2, "fail") : ""}`,
    outcomes: Object.entries(s.outcomes).filter(([, n]) => n)
      .map(([o, n]) => `${chip(o)}&nbsp;${n}`).join(" "),
  }));
  const main = `<section>
    <div class="section-head"><h2>Every system on the same 12 victims</h2>
      <p>Fix rate counts victims repaired. Precision counts repairs among the victims a system patched at all.
         A false fix passes the failing order but fails a randomized one.</p></div>
    ${table([
      { key: "system", label: "System" }, { key: "victims", label: "Victims", num: true },
      { key: "fixed", label: "Fixed", num: true }, { key: "rate", label: "Fix rate", num: true },
      { key: "precision", label: "Precision", num: true }, { key: "ff", label: "False-fix rate", num: true },
      { key: "outcomes", label: "Outcomes" },
    ], rows)}
  </section>`;

  const paired = `<section>
    <div class="section-head"><h2>Is the difference real?</h2>
      <p>Per victim, paired, two-sided exact sign test against PolluTrace. With 12 victims and one run,
         only a large gap could reach significance — none does.</p></div>
    ${table([
      { key: "against", label: "PolluTrace vs" }, { key: "better", label: "PolluTrace better", num: true },
      { key: "worse", label: "Other better", num: true }, { key: "ties", label: "Ties", num: true },
      { key: "p", label: "p", num: true },
    ], d.paired.map((p) => ({
      against: esc(p.label), better: p.better, worse: p.worse, ties: p.ties,
      p: `${num(p.p, 3)}${p.p < 0.05 ? "" : ""}`,
    })))}
  </section>`;

  view.innerHTML = heroPanel + gapCards + main + paired;
}

/* ---------------------------------------------------------------- victims */
async function victims() {
  const d = await api("/api/victims");
  const sys = d.systems;
  const rows = d.victims.map((v) => ({
    _cls: "clickable", _attrs: `data-victim="${esc(v.id)}"`,
    id: `<b>${esc(v.id)}</b>`,
    project: esc(v.project),
    victim: tn(v.victim),
    polluter: tn(v.confirmed_polluter),
    order: v.order.len ? `${v.order.len}<br><span style="font-size:.72rem;color:var(--faint)">pos ${v.order.polluter_position ?? "–"}</span>` : "–",
    ...Object.fromEntries(sys.map((s) => [s.key, chip(v.outcomes[s.key])])),
  }));
  const cols = [
    { key: "id", label: "Id" }, { key: "project", label: "Project" },
    { key: "victim", label: "Victim test" }, { key: "polluter", label: "Known polluter" },
    { key: "order", label: "Order", num: true },
    ...sys.map((s) => ({ key: s.key, label: s.key.replace(/_.*/, "") })),
  ];
  view.innerHTML = `<section>
    <div class="section-head"><h1>Victims</h1>
      <p>The 15 order-dependent tests in the evaluation subset. 12 were attempted by every system; the three
         WildFly victims never produced a runnable failing order. Open one to see what each system did.</p></div>
    <p><input type="search" id="vfilter" placeholder="Filter by id, project or test name" aria-label="Filter victims"></p>
    <div id="vtable">${table(cols, rows)}</div>
  </section>`;

  $("#vfilter").addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase();
    $("#vtable").querySelectorAll("tbody tr").forEach((tr) => {
      tr.style.display = tr.textContent.toLowerCase().includes(q) ? "" : "none";
    });
  });
  $("#vtable").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-victim]");
    if (tr) location.hash = `#/victims/${tr.dataset.victim}`;
  });
}

async function victimDetail(id) {
  const d = await api(`/api/victims/${encodeURIComponent(id)}`);
  const fo = d.failing_order;
  const order = fo.order || [];

  const systems = d.systems.map((s) => {
    const sm = s.summary || {};
    const loc = sm.localization || {};
    const sd = sm.state_diff || {};
    const usage = sm.usage || {};
    const body = [];

    if (sm.polluter) {
      body.push(`<h4>Polluter</h4><p>${tn({ full: sm.polluter, ...splitName(sm.polluter) })}
        <span style="color:var(--muted);font-size:.83rem">
        — found in ${int(loc.runs)} order run${loc.runs === 1 ? "" : "s"}${loc.rank_of_found ? `, ranked #${loc.rank_of_found} before any test ran` : ""}.</span></p>`);
    } else if (s.outcome) {
      body.push(`<h4>Polluter</h4><p style="color:var(--muted)">No polluter search in this configuration, or none found.</p>`);
    }

    if (sd.changes && sd.changes.length) {
      body.push(`<h4>What the polluter left behind</h4>
        ${table([{ key: "k", label: "Static field or property" }, { key: "b", label: "Clean JVM" }, { key: "a", label: "After the polluter" }],
          sd.changes.map((c) => ({ k: `<code class="tn">${esc(c.key)}</code>`, b: `<code class="tn">${esc(c.before)}</code>`, a: `<code class="tn">${esc(c.after)}</code>` })))}
        <p style="font-size:.8rem;color:var(--muted);margin-top:.4rem">
          ${int(sd.n_changed)} of ${int(sd.n_fields)} snapshotted entries differ.</p>`);
    } else if (sd.n_fields) {
      body.push(`<h4>What the polluter left behind</h4>
        <p style="color:var(--muted)">Nothing changed in the ${int(sd.n_fields)} static fields and properties that were
        snapshotted. The pollution is somewhere this diff does not reach — a thread-local, or instance state.</p>`);
    }

    (sm.attempts || []).forEach((a) => {
      const checks = Object.entries(a.checks || {}).map(([k, v]) => {
        if (k === "random_orders" && typeof v === "object") {
          const ok = (v.fails || 0) === 0;
          return `<li class="${ok ? "ok" : "no"}"><span class="mark">${ok ? "✓" : "✗"}</span>
            <span>${v.n_run} randomized orders: ${v.fails || 0} failed${v.budget_hit ? " (time cap hit)" : ""}</span></li>`;
        }
        const ok = String(v).toUpperCase() === "PASS" || v === "ok" || v === true;
        return `<li class="${ok ? "ok" : "no"}"><span class="mark">${ok ? "✓" : "✗"}</span>
          <span>${esc(k.replace(/_/g, " "))}: ${esc(String(v))}</span></li>`;
      }).join("");
      body.push(`<h4>Attempt ${a.attempt} — patched the ${esc(a.target || "test")},
        verdict ${esc(a.verdict || "–")}</h4>
        ${a.reason ? `<p style="font-size:.86rem;color:var(--muted)">${esc(a.reason)}</p>` : ""}
        ${checks ? `<ul class="checks">${checks}</ul>` : ""}
        ${(a.reasons || []).length ? `<p style="font-size:.84rem;color:var(--fail)">Rejected: ${esc(a.reasons.join("; "))}</p>` : ""}`);
    });

    (sm.patch_files || []).forEach((p, i) => {
      body.push(`<h4>Patch</h4><p><button class="ghost" data-patch="${s.experiment}|${s.key}|${s.run}|${d.id}|${i}">
        View ${esc(p.name)} (${int(p.chars)} characters)</button></p>`);
    });

    const fin = sm.final_orders || {};
    if (fin.n_run) {
      body.push(`<h4>Final check, independent of the validator</h4>
        <p style="font-size:.86rem">${fin.n_run} randomized orders over a pool of ${fin.pool_size} tests:
        <b>${fin.passes} passed, ${fin.fails} failed</b>${fin.budget_hit ? " (time cap hit)" : ""}.</p>`);
    }
    if (usage.llm_calls !== undefined) {
      body.push(`<h4>Cost of this run</h4><p style="font-size:.86rem;color:var(--muted)">
        ${usage.llm_calls} LLM calls · ${int(usage.prompt_tokens)} in / ${int(usage.completion_tokens)} out tokens ·
        ${usage.test_runs} order runs · ${int(usage.test_executions)} test executions · ${num(usage.wall_secs)} s</p>`);
    }
    if (s.has_trajectory) {
      body.push(`<p><a href="#/traces/${s.experiment}/${s.key}/${s.run}/${d.id}">See every step this run took →</a></p>`);
    }

    return `<details class="sys" ${s.key === "PolluTrace" ? "open" : ""}>
      <summary>${chip(s.outcome)} ${esc(s.label)}
        <span class="grow">${sm.iterations ? `${sm.iterations} repair iteration${sm.iterations === 1 ? "" : "s"} · ` : ""}${esc(sm.stop_reason || "")}</span>
      </summary>
      <div class="sys-body">${body.join("") || `<p style="color:var(--muted)">No dossier was saved for this run.</p>`}</div>
    </details>`;
  }).join("");

  view.innerHTML = `<section>
    <button class="back" data-back>← All victims</button>
    <h1>${esc(d.id)} · ${esc(d.project)}</h1>
    <div class="meta">
      <span>victim <b>${esc(d.victim.cls)}#${esc(d.victim.method)}</b></span>
      <span>module <b>${esc(d.module === "." ? "root" : d.module)}</b></span>
      <span>commit <b>${esc((d.sha || "").slice(0, 10))}</b></span>
      ${d.project_url ? `<span><a href="${esc(d.project_url)}" target="_blank" rel="noopener">repository ↗</a></span>` : ""}
    </div>

    <div class="panel strip-wrap" style="margin-bottom:1.6rem">
      ${strip(order.length, fo.polluter_position, true)}
      ${stripLegend(order.length, fo.polluter_position)}
      <p style="margin-top:.9rem;font-size:.9rem">
        In this order ${tn(d.confirmed_polluter, { short: true })} runs at position ${fo.polluter_position ?? "–"},
        and ${fo.polluter_position === null || fo.polluter_position === undefined
              ? order.length - 1 : order.length - 1 - fo.polluter_position} tests later
        ${tn(d.victim, { short: true })} fails.
        IDoFT lists ${d.known_polluters.length} known polluter${d.known_polluters.length === 1 ? "" : "s"} for it;
        the agents never see them.</p>
      ${fo.trace ? `<details><summary style="cursor:pointer;font-size:.85rem;color:var(--accent)">Stack trace</summary>
        <pre class="code trace">${esc(fo.trace.slice(0, 4000))}</pre></details>` : ""}
    </div>

    <h2 style="margin-bottom:.7rem">What each system did</h2>
    ${systems || `<p class="empty">No system has run this victim.</p>`}
  </section>`;

  view.addEventListener("click", async (e) => {
    if (e.target.hasAttribute("data-back")) { location.hash = "#/victims"; return; }
    const pb = e.target.closest("[data-patch]");
    if (pb) {
      const [exp, sysKey, run, vid, i] = pb.dataset.patch.split("|");
      try {
        const p = await api(`/api/patch/${exp}/${sysKey}/${run}/${vid}?i=${i}`);
        sheet(p.name, `<p style="font-size:.82rem;color:var(--muted)">${esc(p.path)}</p>
          <pre class="code" style="max-height:none">${esc(p.source)}</pre>`);
      } catch (err) { sheet("Patch", `<p class="notice error">${esc(err.message)}</p>`); }
    }
  }, { once: false });
}

function splitName(full) {
  const [cls, method] = String(full).split("#");
  const i = cls.lastIndexOf(".");
  return { pkg: i > 0 ? cls.slice(0, i) : "", cls: i > 0 ? cls.slice(i + 1) : cls, method: method || "" };
}

/* ------------------------------------------------------------------- gaps */
async function gaps() {
  const d = await api("/api/gaps");
  const g1 = d.g1.strategies, g2 = d.g2, g3 = d.g3;
  const maxRuns = Math.max(...g1.map((s) => s.mean_runs));

  const g1table = table([
    { key: "s", label: "Strategy" }, { key: "trials", label: "Trials", num: true },
    { key: "correct", label: "Found a known polluter", num: true },
    { key: "runs", label: "Order runs", num: true }, { key: "execs", label: "Test executions", num: true },
    { key: "rank", label: "Known polluter ranked top-1 / top-5", num: true },
  ], g1.map((s) => ({
    _cls: s.strategy === "ranked_llm" ? "highlight" : "",
    s: `<b>${esc(s.strategy.replace(/_/g, " "))}</b>`,
    trials: s.trials, correct: `${s.correct}/${s.trials}`,
    runs: `${num(s.mean_runs)}${bar(s.mean_runs, maxRuns, s.strategy.startsWith("ranked") ? "" : "grey")}`,
    execs: num(s.mean_execs, 0),
    rank: s.has_ranking ? `${s.top1} / ${s.top5}` : "–",
  })));

  const g2rows = (g2 ? g2.rows : []).map((r) => ({
    _cls: "clickable", _attrs: `data-victim="${esc(r.id)}"`,
    id: `<b>${esc(r.id)}</b>`, victim: tn(r.victim),
    fields: int(r.n_fields), changed: r.n_changed ? `<b>${r.n_changed}</b>` : "0",
    points: r.points ? `<span class="chip fixed">yes</span>` : `<span class="chip">no</span>`,
    top: r.top_changes ? `<code class="tn">${esc(r.top_changes.slice(0, 90))}</code>` : "–",
  }));

  const g3mut = table([
    { key: "m", label: "Seeded bad patch" }, { key: "a", label: "Applicable", num: true },
    { key: "w", label: "Weak validator rejects", num: true }, { key: "s", label: "Strict validator rejects", num: true },
  ], g3.mutants.map((m) => ({
    m: esc(m.mutant.replace(/_/g, " ")), a: m.applicable,
    w: `${m.weak}/${m.applicable}${bar(m.weak, m.applicable, "grey")}`,
    s: `${m.strict}/${m.applicable}${bar(m.strict, m.applicable)}`,
  })));

  view.innerHTML = `<section>
    <div class="section-head"><h1>Gaps</h1>
      <p>Three measurements, one per gap, each isolating a single component against the alternative
         the base paper's pipeline uses.</p></div>
  </section>

  <section>
    <div class="section-head"><h2>G1 · Finding the polluter</h2>
      <p>Same failing orders, same budget, five search strategies. Ranking by shared static state and then
         confirming by execution gets there in roughly a tenth of the order runs that trying each test takes.</p></div>
    ${g1table}
    <p style="font-size:.82rem;color:var(--muted);margin-top:.5rem">
      Bisection finds a polluter in every trial because it searches the order itself; the ranked strategies miss
      one victim where the pollution is not visible in static state.
      <button class="ghost" data-g1rows>Per-trial numbers</button></p>
  </section>

  <section>
    <div class="section-head"><h2>G2 · Evidence of what was polluted</h2>
      <p>Two fresh JVMs — one clean, one after the polluter — compared field by field.</p></div>
    ${g2 ? `<div class="headline" style="border:0;margin-bottom:1rem">
      <div><b>${g2.ok}/${g2.total}</b><span>diffs computed</span></div>
      <div><b>${g2.with_change}</b><span>show a changed field</span></div>
      <div><b>${g2.points_at_victim}</b><span>change state the victim touches</span></div>
      <div><b>${int(g2.median_fields)}</b><span>fields snapshotted, median</span></div>
    </div>
    ${table([{ key: "id", label: "Id" }, { key: "victim", label: "Victim" }, { key: "fields", label: "Fields", num: true },
             { key: "changed", label: "Changed", num: true }, { key: "points", label: "Victim's own state" },
             { key: "top", label: "Largest change" }], g2rows)}
    <p style="font-size:.82rem;color:var(--muted);margin-top:.5rem">
      This is the gap that stayed open: the diff names a field for most victims, but removing it from the repair
      prompt changed no outcome. What the diff cannot see — thread-locals and instance state — is where the
      remaining failures live.</p>` : `<p class="empty">No G2 results yet.</p>`}
  </section>

  <section>
    <div class="section-head"><h2>G3 · Deciding a patch is real</h2>
      <p>Patches were deliberately broken in four ways, then offered to both validators. The weak validator is
         the acceptance rule most prior tools use: the victim passes the order that exposed it, once.</p></div>
    ${g3mut}
    <p style="font-size:.85rem;margin-top:.8rem">Across ${g3.sweep_total} patch${g3.sweep_total === 1 ? "" : "es"} that
      a weak validator accepted but randomized orders later broke, ${g3.caught[1]} was caught by the very first
      random order — so the cost of catching it is one extra run, not a hundred.</p>
  </section>`;

  $("#view").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-victim]");
    if (tr) { location.hash = `#/victims/${tr.dataset.victim}`; return; }
    if (e.target.hasAttribute("data-g1rows")) {
      sheet("Localization, every trial", table([
        { key: "id", label: "Id" }, { key: "s", label: "Strategy" }, { key: "c", label: "Known polluter" },
        { key: "r", label: "Runs", num: true }, { key: "x", label: "Executions", num: true },
        { key: "k", label: "Rank", num: true }, { key: "t", label: "Seconds", num: true },
      ], d.g1.rows.map((r) => ({
        id: esc(r.id), s: esc(r.strategy.replace(/_/g, " ")),
        c: r.correct ? `<span class="chip fixed">yes</span>` : `<span class="chip">no</span>`,
        r: r.runs, x: r.execs, k: r.rank || "–", t: num(r.secs),
      }))));
    }
  });
}

/* ------------------------------------------------------------------- cost */
async function cost() {
  const d = await api("/api/efficiency");
  const s = d.systems;
  const maxCalls = Math.max(...s.map((x) => x.llm_calls));
  const maxExec = Math.max(...s.map((x) => x.test_executions));
  const maxUsd = Math.max(...s.map((x) => x.usd));
  view.innerHTML = `<section>
    <div class="section-head"><h1>Cost</h1>
      <p>Per victim, over the ${s[0] ? s[0].runs : 1} run${s[0] && s[0].runs === 1 ? "" : "s"} recorded.
         Grounding every decision in a test execution is what PolluTrace spends its budget on.</p></div>
    ${table([
      { key: "sys", label: "System" }, { key: "calls", label: "LLM calls", num: true },
      { key: "tok", label: "Tokens in / out", num: true }, { key: "usd", label: "US$", num: true },
      { key: "runs", label: "Order runs", num: true }, { key: "exec", label: "Test executions", num: true },
      { key: "secs", label: "Agent seconds", num: true }, { key: "stable", label: "Same outcome every run", num: true },
      { key: "fix", label: "Fix rate", num: true },
    ], s.map((x) => ({
      _cls: x.key === "PolluTrace" ? "highlight" : "",
      sys: `<b>${esc(x.label)}</b>`,
      calls: `${num(x.llm_calls)}${bar(x.llm_calls, maxCalls)}`,
      tok: `${int(x.prompt_tokens)} / ${int(x.completion_tokens)}`,
      usd: `$${num(x.usd, 4)}${bar(x.usd, maxUsd, "grey")}`,
      runs: num(x.test_runs), exec: `${num(x.test_executions, 0)}${bar(x.test_executions, maxExec, "grey")}`,
      secs: num(x.agent_secs, 0), stable: esc(x.same_outcome_all_runs), fix: esc(x.fix_rate),
    })))}
    <p style="font-size:.84rem;color:var(--muted);margin-top:.7rem">
      Priced at $${d.price.usd_in} per million input tokens and $${d.price.usd_out} per million output tokens.
      The whole evaluation cost well under a dollar; the real budget is wall-clock time in the JVM.
      The weak validator (A3) is cheap for the same reason it is unsafe — it stops after one order.</p>
  </section>`;
}

/* ----------------------------------------------------------------- traces */
const AGENT_WORDS = {
  supervisor: "supervisor", localizer: "localizer", statediff: "state diff",
  repair: "repair", validator: "validator", harness: "harness",
};

function describeStep(s) {
  const d = [];
  let title = s.kind.replace(/_/g, " ");
  if (s.kind === "tool_call" && s.tool === "run_order") {
    const fails = Object.entries(s.statuses || {});
    title = `ran ${s.n_tests} test${s.n_tests === 1 ? "" : "s"}`;
    d.push(fails.length
      ? `${fails.map(([t, v]) => `<code>${esc(t.split("#").pop())}</code> ${esc(v)}`).join(", ")} · ${num(s.secs)} s`
      : `all passed · ${num(s.secs)} s`);
    if (s.purpose) d.push(esc(s.purpose));
  } else if (s.kind === "tool_call" && s.tool === "compile") {
    title = s.ok ? "compiled" : "compile failed";
    if (s.errors) d.push(`<code>${esc(String(s.errors).slice(0, 220))}</code>`);
  } else if (s.kind === "llm_call") {
    title = `asked the model — ${esc(s.purpose || "")}`;
    d.push(`${int(s.prompt_tokens)} in / ${int(s.completion_tokens)} out tokens · ${num(s.secs)} s · ${esc(s.model || "")}`);
  } else if (s.kind === "plan") {
    if (s.strategy) { title = `plan: ${esc(s.strategy.replace(/_/g, " "))} search`; d.push(`${s.prefix_len} candidate tests, budget ${s.budget} runs`); }
    else if (s.config) { title = "plan: run the pipeline"; d.push(`config ${esc(s.config.name)} · failing order of ${s.failing_order_len} tests`); }
    else if (s.polluter) { title = "plan: snapshot the JVM"; d.push(`${s.n_classes} classes around the polluter`); }
    else if (s.attempt) { title = `plan: repair attempt ${s.attempt}`; d.push(`${(s.polluters || []).length} polluter(s)${s.with_diff ? ", with the state diff" : ", no state diff"}`); }
    else if (s.mode) { title = `plan: ${esc(s.mode)} validation`; d.push(`${s.n_loop} randomized orders`); }
  } else if (s.kind === "observation") {
    title = `observed: ${esc(s.what || "")}`;
    if (s.changes && s.changes.length) d.push(s.changes.slice(0, 3).map((c) => `<code>${esc(c.key)}</code>`).join(", "));
    else if (s.what === "state diff") d.push("nothing changed in the snapshotted fields");
    if (s.top) d.push(s.top.slice(0, 3).map((t) => `<code>${esc(String(t[0]).split("#").pop())}</code> ${t[1]}`).join(", "));
  } else if (s.kind === "decision") {
    title = `decided: ${esc(s.what || s.verdict || "")}`;
    if (s.verdict) { title = `verdict ${esc(s.verdict)}`; if (s.mode) d.push(`mode ${esc(s.mode)}`); }
    if (s.polluter) d.push(`<code>${esc(String(s.polluter).split("#").pop())}</code> after ${s.runs} run(s)`);
    if (s.target) d.push(`patch the ${esc(s.target)}${s.reason ? ` — ${esc(String(s.reason).slice(0, 200))}` : ""}`);
    if (s.reasons && s.reasons.length) d.push(esc(s.reasons.join("; ")));
    if (s.reason && !s.target) d.push(esc(String(s.reason).slice(0, 200)));
  } else if (s.kind === "error") {
    title = `error: ${esc(s.what || "")}`;
    d.push(`<code>${esc(String(s.error || "").slice(0, 300))}</code>`);
  }
  return { title, detail: d.join(" · ") };
}

function stepList(steps) {
  if (!steps.length) return `<p class="empty">Nothing logged yet.</p>`;
  return `<ul class="steps">${steps.map((s) => {
    const { title, detail } = describeStep(s);
    return `<li>
      <span class="t">${num(s.t)}s</span>
      <span class="who ${esc(s.agent)}">${esc(AGENT_WORDS[s.agent] || s.agent)}</span>
      <span class="what"><b>${title}</b>${detail ? `<span class="det">${detail}</span>` : ""}</span>
    </li>`;
  }).join("")}</ul>`;
}

let traceIndex = null;
async function traces(parts) {
  if (!traceIndex) traceIndex = await api("/api/trajectories");
  const exps = Object.keys(traceIndex);
  if (!exps.length) { view.innerHTML = `<p class="empty">No trajectories have been recorded yet.</p>`; return; }

  let [exp, sysKey, run, vid] = parts;
  if (!exp || !traceIndex[exp]) exp = traceIndex.E3 ? "E3" : exps[0];
  const systemsOf = traceIndex[exp];
  if (!sysKey || !systemsOf[sysKey]) sysKey = Object.keys(systemsOf)[0];
  const runsOf = systemsOf[sysKey];
  if (!run || !runsOf[run]) run = Object.keys(runsOf)[0];
  const vids = runsOf[run];
  if (!vid || !vids.includes(vid)) vid = vids[0];

  const opt = (list, cur) => list.map((x) => `<option value="${esc(x)}" ${x === cur ? "selected" : ""}>${esc(x)}</option>`).join("");
  const t = await api(`/api/trajectory/${exp}/${sysKey}/${run}/${vid}`);

  view.innerHTML = `<section>
    <div class="section-head"><h1>Traces</h1>
      <p>Every plan, tool call, observation and decision the agents recorded, exactly as written to
         <code class="tn">logs/trajectories/</code> while the run happened.</p></div>
    <div class="controls" style="margin-bottom:1.2rem">
      <label class="field">Experiment<select id="t-exp">${opt(exps, exp)}</select></label>
      <label class="field">System<select id="t-sys">${opt(Object.keys(systemsOf), sysKey)}</select></label>
      <label class="field">Run<select id="t-run">${opt(Object.keys(runsOf), run)}</select></label>
      <label class="field">Victim<select id="t-vid">${opt(vids, vid)}</select></label>
    </div>
    <div class="panel panel-pad">
      <p style="font-size:.85rem;color:var(--muted);margin-bottom:.8rem">
        ${t.total} steps over ${num(t.elapsed)} seconds · ${t.agents.map((a) => `<span class="who ${esc(a)}">${esc(AGENT_WORDS[a] || a)}</span>`).join(" ")}
      </p>
      ${stepList(t.steps)}
      ${t.total > t.steps.length ? `<p style="font-size:.82rem;color:var(--muted);margin-top:.6rem">Showing the first ${t.steps.length} of ${t.total} steps.</p>` : ""}
    </div>
  </section>`;

  const go = () => {
    location.hash = `#/traces/${$("#t-exp").value}/${$("#t-sys").value}/${$("#t-run").value}/${$("#t-vid").value}`;
  };
  $("#t-exp").addEventListener("change", () => { location.hash = `#/traces/${$("#t-exp").value}`; });
  $("#t-sys").addEventListener("change", () => { location.hash = `#/traces/${$("#t-exp").value}/${$("#t-sys").value}`; });
  $("#t-run").addEventListener("change", go);
  $("#t-vid").addEventListener("change", go);
}

/* -------------------------------------------------------------------- run */
let pollTimer = null;
async function runView() {
  clearInterval(pollTimer);
  const d = await api("/api/runs");
  const h = d.health;
  const vics = (await api("/api/victims")).victims;

  const blocked = !h.can_run;
  const notice = blocked ? `<div class="notice">
      <b>This machine cannot start a run yet.</b>
      <ul>${h.blockers.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>
      <p style="margin:.5rem 0 0;font-size:.84rem">Everything else in the console works — it reads results that are
      already saved. Set the four things above up on the laptop that has the project checkouts.</p>
    </div>` : `<div class="notice" style="border-left-color:var(--pass);background:var(--pass-soft)">
      <b>Ready.</b> ${h.projects_ready} project checkout${h.projects_ready === 1 ? "" : "s"} built,
      JDK 8/11/17 and OrderRunner in place, model ${esc(h.llm_model)}.
      A run uses real LLM calls and real test executions on this machine.</div>`;

  view.innerHTML = `<section>
    <div class="section-head"><h1>Run</h1>
      <p>Put one victim through one configuration and watch the agents work. Results land under
         <code class="tn">results/WEB/</code>, so nothing here can disturb the numbers the paper reports.</p></div>
    ${notice}
    <div class="panel panel-pad" style="margin:1.2rem 0">
      <div class="controls">
        <label class="field">Victim<select id="r-vic">
          ${vics.map((v) => `<option value="${esc(v.id)}">${esc(v.id)} — ${esc(v.project)} · ${esc(v.victim.cls)}#${esc(v.victim.method)}</option>`).join("")}
        </select></label>
        <label class="field">Configuration<select id="r-sys">
          ${d.systems.map((s) => `<option value="${esc(s.key)}" title="${esc(s.note)}">${esc(s.label)}</option>`).join("")}
        </select></label>
        <label class="field">Final randomized orders<input type="number" id="r-n" value="20" min="1" max="100" style="min-width:6rem"></label>
        <button class="go" id="r-go" ${blocked ? "disabled" : ""}>Start the run</button>
      </div>
      <p id="r-note" style="font-size:.82rem;color:var(--muted);margin:.7rem 0 0"></p>
    </div>
    <div id="r-live"></div>
  </section>`;

  const note = $("#r-note");
  $("#r-sys").addEventListener("change", (e) => {
    const s = d.systems.find((x) => x.key === e.target.value);
    note.textContent = s ? s.note : "";
  });
  $("#r-sys").dispatchEvent(new Event("change"));

  $("#r-go").addEventListener("click", async () => {
    $("#r-go").disabled = true;
    try {
      const rec = await api("/api/runs", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          victim_id: $("#r-vic").value, system: $("#r-sys").value,
          n_final: Number($("#r-n").value) || 20,
        }),
      });
      watch(rec.id);
    } catch (err) {
      $("#r-live").innerHTML = `<div class="notice error">${esc(err.message)}</div>`;
      $("#r-go").disabled = blocked;
    }
  });

  if (d.runs.length) {
    $("#r-live").innerHTML = `<h2 style="margin-bottom:.6rem">Earlier runs</h2>
      ${table([{ key: "id", label: "Run" }, { key: "v", label: "Victim" }, { key: "s", label: "Configuration" },
               { key: "st", label: "State" }, { key: "e", label: "Seconds", num: true }],
        d.runs.map((r) => ({ _cls: "clickable", _attrs: `data-run="${esc(r.id)}"`,
          id: esc(r.id), v: esc(r.victim_id), s: esc(r.system),
          st: `<span class="run-state ${esc(r.state)}">${esc(r.state)}</span>`, e: num(r.elapsed) })))}`;
    $("#r-live").addEventListener("click", (e) => {
      const tr = e.target.closest("tr[data-run]");
      if (tr) watch(tr.dataset.run);
    });
  }
}

function watch(rid) {
  const live = $("#r-live");
  const tick = async () => {
    let r;
    try { r = await api(`/api/runs/${rid}`); } catch { clearInterval(pollTimer); return; }
    const steps = r.trajectory.steps || [];
    const result = r.result;
    live.innerHTML = `
      <div class="panel panel-pad" style="margin-bottom:1rem">
        <div style="display:flex;align-items:baseline;gap:.9rem;flex-wrap:wrap">
          <h2>${esc(r.victim_id)} · ${esc(r.system)}</h2>
          <span class="run-state ${esc(r.state)}">${esc(r.state)}</span>
          <span style="color:var(--muted);font-size:.85rem">${num(r.elapsed)} s · ${r.trajectory.total} steps</span>
          <span style="flex:1"></span>
          ${r.state === "running" ? `<button class="ghost" id="r-stop">Stop this run</button>` : ""}
        </div>
        ${result ? `<p style="margin:.8rem 0 0">Outcome ${chip(result.outcome)} ·
          ${result.llm_calls} LLM calls · ${int(result.test_executions)} test executions ·
          ${num(result.agent_secs)} s${result.polluter_found ? ` · polluter <code class="tn">${esc(String(result.polluter_found).split("#").pop())}</code>` : ""}
          ${result.outcome === "fixed" ? ` · <a href="#/victims/${esc(r.victim_id)}">compare with the saved runs →</a>` : ""}</p>` : ""}
      </div>
      <div class="split">
        <div class="panel panel-pad">
          <h3 style="margin-bottom:.6rem">Agent steps</h3>
          ${stepList(steps.slice(-40))}
        </div>
        <div class="panel panel-pad">
          <h3 style="margin-bottom:.6rem">Console</h3>
          <pre class="console">${esc((r.output || []).slice(-60).join("\n")) || "waiting for the first line…"}</pre>
          <p style="font-size:.78rem;color:var(--muted);margin:.6rem 0 0">
            results/WEB/${esc(r.system)}/run${r.run}.csv</p>
        </div>
      </div>`;
    const stop = $("#r-stop");
    if (stop) stop.addEventListener("click", async () => {
      await api(`/api/runs/${rid}/stop`, { method: "POST" });
    });
    if (r.state !== "running") {
      clearInterval(pollTimer);
      const go = $("#r-go");
      if (go) go.disabled = false;
    }
  };
  clearInterval(pollTimer);
  tick();
  pollTimer = setInterval(tick, 1500);
}

/* ----------------------------------------------------------------- router */
const ROUTES = {
  overview, victims, gaps, cost, traces, run: runView,
};

async function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const name = parts[0] || "overview";
  const fn = ROUTES[name] || overview;
  document.querySelectorAll(".rail-list a").forEach((a) => {
    a.toggleAttribute("aria-current", a.dataset.view === name);
    if (a.dataset.view === name) a.setAttribute("aria-current", "page");
  });
  if (name !== "run") clearInterval(pollTimer);
  view.innerHTML = `<p class="loading">Loading…</p>`;
  try {
    if (name === "victims" && parts[1]) await victimDetail(parts[1]);
    else if (name === "traces") await traces(parts.slice(1));
    else await fn(parts.slice(1));
  } catch (err) {
    view.innerHTML = `<div class="notice error"><b>Could not load this view.</b>
      <p style="margin:.4rem 0 0">${esc(err.message)}</p></div>`;
  }
  window.scrollTo(0, 0);
}

async function envBadge() {
  try {
    const h = await api("/api/health");
    $("#env-dot").className = `dot ${h.can_run ? "ready" : "blocked"}`;
    $("#env-text").textContent = h.can_run
      ? `ready to run · ${h.projects_ready} projects`
      : "reading saved results";
    $("#env-text").title = h.can_run ? "" : h.blockers.join("\n");
  } catch {
    $("#env-dot").className = "dot blocked";
    $("#env-text").textContent = "server not reachable";
  }
}

window.addEventListener("hashchange", route);
route();
envBadge();
