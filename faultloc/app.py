"""Read-only dashboard for cached benchmark results."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse


LOCALIZER_ORDER = (
    "l0_random",
    "l1_stack",
    "l2_bm25",
    "l4_hybrid",
    "a5_test_calls",
    "a6_router",
    "a7_clean_bm25",
    "l3_dense",
)

ABSOLUTE_PROJECT_PATH = re.compile(
    r"(?<![\w.-])(?:/[^\s/:]+)+/(?=(?:target|faultloc|tests|data|results)/)"
)


def _portable_paths(value: Any) -> Any:
    """Remove machine-specific project prefixes from public cached evidence."""
    if isinstance(value, str):
        return ABSOLUTE_PROJECT_PATH.sub("", value)
    if isinstance(value, list):
        return [_portable_paths(item) for item in value]
    if isinstance(value, dict):
        return {key: _portable_paths(item) for key, item in value.items()}
    return value


class DashboardData:
    """Load immutable dashboard data once at process startup."""

    def __init__(self, root: Path) -> None:
        results_path = root / "results" / "results.json"
        cases_path = root / "data" / "cases.jsonl"
        if not results_path.is_file() or not cases_path.is_file():
            raise RuntimeError(
                "Cached benchmark data is missing. Run `python -m faultloc harvest` "
                "and `python -m faultloc eval` first."
            )

        self.results: dict[str, Any] = json.loads(results_path.read_text())
        evaluated_ids = {
            row["case_id"]
            for localizer in self.results["localizers"].values()
            for row in localizer["cases"]
        }
        self.cases = {
            case["case_id"]: case
            for line in cases_path.read_text().splitlines()
            if (case := json.loads(line))["case_id"] in evaluated_ids
        }
        self.ranks = {
            case_id: {
                name: next(
                    row for row in localizer["cases"] if row["case_id"] == case_id
                )
                for name, localizer in self.results["localizers"].items()
            }
            for case_id in self.cases
        }

    def public_results(self) -> dict[str, Any]:
        payload = {key: value for key, value in self.results.items() if key != "localizers"}
        payload["localizers"] = {
            name: {
                "metrics": value["metrics"],
                "breakdowns": value["breakdowns"],
            }
            for name, value in self.results["localizers"].items()
        }
        payload["localizer_order"] = [
            name for name in LOCALIZER_ORDER if name in payload["localizers"]
        ]
        return payload

    def case_summaries(self) -> list[dict[str, Any]]:
        return [
            {
                "case_id": case["case_id"],
                "file": case["file"],
                "function_qualified_name": case["function_qualified_name"],
                "operator": case["operator"],
                "exception_type": case["exception_type"],
                "split": case["split"],
            }
            for case in sorted(self.cases.values(), key=lambda item: item["case_id"])
        ]

    def case_detail(self, case_id: str) -> dict[str, Any]:
        try:
            case = self.cases[case_id]
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Case not found") from error
        return _portable_paths({**case, "localizer_results": self.ranks[case_id]})


def create_app(root: Path | None = None) -> FastAPI:
    project_root = root or Path(__file__).resolve().parents[1]
    data = DashboardData(project_root)
    dashboard = FastAPI(
        title="Fault-localization benchmark",
        description="Cached development-set benchmark results",
        version="0.1.0",
    )

    @dashboard.get("/", response_class=HTMLResponse, include_in_schema=False)
    def home() -> str:
        return DASHBOARD_HTML

    @dashboard.get("/healthz", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @dashboard.get("/api/results")
    def results() -> dict[str, Any]:
        return data.public_results()

    @dashboard.get("/api/cases")
    def cases() -> list[dict[str, Any]]:
        return data.case_summaries()

    @dashboard.get("/api/cases/{case_id}")
    def case(case_id: str) -> dict[str, Any]:
        return data.case_detail(case_id)

    return dashboard


DASHBOARD_HTML = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <link rel="icon" href="data:,">
  <title>Fault localization benchmark</title>
  <style>
    :root { --ink:#17221c; --muted:#66716b; --paper:#f4f1e9; --card:#fffdf8;
      --line:#d9d5c9; --green:#176b4a; --green2:#dcecdf; --amber:#a55a18;
      --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
    * { box-sizing:border-box; }
    body { margin:0; color:var(--ink); background:var(--paper); font:15px/1.5 Inter,system-ui,sans-serif; }
    header { padding:34px max(24px,calc((100vw - 1180px)/2)) 72px; background:#18392c; color:#f8f5eb; }
    header p { max-width:720px; margin:8px 0 0; color:#cddbd3; font-size:17px; }
    nav { display:flex; justify-content:space-between; align-items:center; margin-bottom:38px; }
    nav strong { font:700 15px Georgia,serif; }
    nav div { display:flex; flex-wrap:wrap; gap:18px; }
    nav a { color:#dce8e0; text-decoration:none; font-size:13px; }
    nav a:hover { color:white; text-decoration:underline; }
    h1 { margin:0; font:700 clamp(30px,5vw,52px)/1.05 Georgia,serif; letter-spacing:-.03em; }
    h2 { margin:0 0 16px; font:700 25px/1.2 Georgia,serif; }
    h3 { margin:0 0 10px; font-size:14px; text-transform:uppercase; letter-spacing:.08em; }
    main { max-width:1180px; margin:auto; padding:26px 24px 60px; }
    .facts { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-top:-50px; }
    .fact,.panel { background:var(--card); border:1px solid var(--line); border-radius:10px; box-shadow:0 6px 20px #1f35290d; }
    .fact { padding:19px; }
    .fact b { display:block; font:700 28px/1.1 Georgia,serif; color:var(--green); }
    .fact span { color:var(--muted); font-size:13px; }
    .finding { display:flex; align-items:center; gap:16px; padding:18px 20px; margin-top:18px; border-radius:10px; background:#dcecdf; border:1px solid #bbd5c2; }
    .finding-kicker { flex:0 0 auto; padding:4px 9px; border-radius:20px; background:var(--green); color:white; font-size:11px; font-weight:800; text-transform:uppercase; letter-spacing:.06em; }
    .finding p { margin:0; font-size:16px; }
    .panel { padding:22px; margin-top:18px; overflow:hidden; }
    .section-head { display:flex; justify-content:space-between; align-items:end; gap:20px; }
    .section-head p { margin:0 0 16px; color:var(--muted); }
    .scroll { overflow-x:auto; margin:0 -22px; }
    table { width:100%; border-collapse:collapse; min-width:900px; font-variant-numeric:tabular-nums; }
    th,td { padding:12px 14px; border-top:1px solid var(--line); text-align:right; white-space:nowrap; }
    th:first-child,td:first-child { text-align:left; padding-left:22px; }
    th:last-child,td:last-child { padding-right:22px; }
    th { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.06em; }
    tbody tr:hover { background:#f6f5ef; }
    tbody tr.winner { background:var(--green2); }
    .method { font-weight:700; }
    .tag { display:inline-block; margin-left:7px; padding:2px 7px; border-radius:20px; background:var(--green); color:white; font-size:10px; text-transform:uppercase; letter-spacing:.04em; }
    .tag.reverted { color:#7a4518; background:#f5dfc7; }
    .ci { display:block; color:var(--muted); font-size:11px; font-weight:400; }
    .table-note { margin:17px 0 0; color:var(--muted); font-size:13px; }
    .break-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:12px; }
    .break-card { padding:15px; border:1px solid var(--line); border-radius:8px; }
    .break-card b { font-size:20px; }
    .break-card p { margin:3px 0 0; color:var(--muted); }
    details.rare { margin-top:14px; border-top:1px solid var(--line); padding-top:12px; }
    details summary { color:var(--green); cursor:pointer; font-weight:700; }
    .rare-list { display:grid; grid-template-columns:repeat(2,1fr); gap:8px 24px; margin-top:12px; }
    .rare-row { display:flex; justify-content:space-between; gap:16px; padding:7px 0; border-bottom:1px solid var(--line); font-size:13px; }
    label { display:block; margin-bottom:7px; color:var(--muted); font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.05em; }
    select,input { width:100%; padding:11px 12px; border:1px solid #bdb9ae; border-radius:7px; background:white; color:var(--ink); font:inherit; }
    .filters { display:grid; grid-template-columns:1fr 2fr; gap:12px; }
    .case-meta { display:flex; flex-wrap:wrap; gap:8px; margin:18px 0 13px; }
    .pill { padding:5px 9px; border-radius:5px; background:#ece9df; font:12px var(--mono); }
    .rank-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin-bottom:18px; }
    .rank { padding:12px; border:1px solid var(--line); border-radius:7px; }
    .rank.winner { background:var(--green2); border-color:#bbd5c2; }
    .rank b { display:block; font-size:20px; }
    .rank span { display:block; color:var(--muted); font-size:11px; }
    .code-grid { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
    pre { margin:0; padding:16px; overflow:auto; max-height:440px; border-radius:7px; background:#14231d; color:#e8eee8; font:12px/1.55 var(--mono); white-space:pre-wrap; }
    .diff { color:#dceadf; }
    .diff-add { display:block; color:#8ee3ae; background:#173c2d; }
    .diff-del { display:block; color:#ffaaa2; background:#40231f; }
    .diff-line { display:block; min-height:1.55em; }
    .raw-output { margin-top:12px; }
    .raw-output pre { margin-top:8px; }
    .method-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:16px; }
    .method-step { padding-right:16px; border-right:1px solid var(--line); }
    .method-step:last-child { border:0; }
    .method-step b { display:block; color:var(--green); margin-bottom:4px; }
    .links { display:flex; flex-wrap:wrap; gap:10px; margin-top:18px; }
    .links a { padding:7px 10px; border:1px solid var(--line); border-radius:6px; color:var(--green); text-decoration:none; font-weight:700; font-size:12px; }
    .empty { color:var(--muted); padding:22px 0; }
    .foot { color:var(--muted); font-size:12px; margin-top:18px; }
    @media (max-width:900px) { .rank-grid { grid-template-columns:repeat(2,1fr); } }
    @media (max-width:760px) { .facts { grid-template-columns:1fr 1fr; } .filters,.code-grid,.break-grid,.rare-list,.method-grid { grid-template-columns:1fr; } .finding { align-items:flex-start; flex-direction:column; } .method-step { border-right:0; border-bottom:1px solid var(--line); padding:0 0 12px; } header { padding-bottom:70px; } nav { align-items:flex-start; gap:18px; } }
  </style>
</head>
<body>
  <header>
    <nav><strong>WHERE'S THE BUG?</strong><div><a href="#leaderboard-panel">Results</a><a href="#breakdown-panel">Breakdown</a><a href="#case-panel">Cases</a><a href="#methodology">Method</a><a href="https://github.com/Advait0801/wheres-the-bug" target="_blank" rel="noreferrer">GitHub ↗</a></div></nav>
    <h1>Fault localization,<br>measured.</h1><p id="cache-copy">A deterministic mutation benchmark over toolz 1.1.0. Results load from a checked-in cache—no evaluation runs on page load.</p>
  </header>
  <main>
    <section class="facts" id="facts"><div class="fact"><b>—</b><span>loading</span></div></section>
    <section class="finding" id="finding"><span class="finding-kicker">Development finding</span><p>Loading the measured result…</p></section>
    <section class="panel" id="leaderboard-panel">
      <div class="section-head"><div><h2>Leaderboard</h2><p>Bootstrap 95% confidence intervals; higher is better except rank, tokens, and latency.</p></div></div>
      <div class="scroll"><table><thead><tr><th>Localizer</th><th>Top-1</th><th>Top-5</th><th>MRR</th><th>Mean rank</th><th>Median rank</th><th>Median tokens</th><th>p50 ms</th><th>p95 ms</th></tr></thead><tbody id="leaderboard"></tbody></table></div>
      <p class="table-note" id="winner-note"></p>
    </section>
    <section class="panel" id="breakdown-panel">
      <div class="section-head"><div><h2>Error-type breakdown</h2><p id="break-label">Winner performance by exception family.</p></div></div>
      <div class="break-grid" id="breakdown"></div>
      <div id="rare-breakdown"></div>
    </section>
    <section class="panel" id="case-panel">
      <div class="section-head"><div><h2>Case explorer</h2><p>Inspect the exact patch, failure evidence, and rank from every localizer.</p></div></div>
      <div class="filters"><div><label for="search">Filter cases</label><input id="search" placeholder="function, file, operator…"></div><div><label for="case-select" id="case-label">Evaluated case</label><select id="case-select"></select></div></div>
      <div id="case-view" class="empty">Loading cases…</div>
    </section>
    <section class="panel" id="methodology">
      <div class="section-head"><div><h2>Exact labels, by construction</h2><p>No bug locations were hand-labelled.</p></div></div>
      <div class="method-grid"><div class="method-step"><b>1 · Mutate</b>Apply exactly one deterministic AST change to one known function.</div><div class="method-step"><b>2 · Observe</b>Run the complete test suite and retain mutations that produce a failure.</div><div class="method-step"><b>3 · Measure</b>Rank every library function; the mutated function is the exact answer.</div></div>
      <div class="links"><a href="https://github.com/Advait0801/wheres-the-bug#readme" target="_blank" rel="noreferrer">Read the methodology ↗</a><a href="https://github.com/Advait0801/wheres-the-bug/blob/main/EXPERIMENTS.md" target="_blank" rel="noreferrer">Experiment log ↗</a><a href="/docs">API documentation</a></div>
    </section>
    <p class="foot" id="split-note">The test split remains sealed until the final one-shot evaluation.</p>
  </main>
<script>
const labels={l0_random:'L0 · Random',l1_stack:'L1 · Stack',l2_bm25:'L2 · BM25',l3_dense:'L3 · Dense',l4_hybrid:'L4 · Hybrid',a5_test_calls:'A5 · Test calls',a6_router:'A6 · Router',a7_clean_bm25:'A7 · Clean BM25'};
let results, cases=[], visible=[];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const metric=(m,kind)=>{let n=m.estimate,lo=m.ci_low,hi=m.ci_high; const f=kind==='pct'?x=>(100*x).toFixed(1)+'%':kind==='rank'?x=>x.toFixed(1):kind==='ms'?x=>x.toFixed(Math.abs(x)<1?4:2):x=>x.toFixed(2); return `<b>${f(n)}</b><span class="ci">${f(lo)}–${f(hi)}</span>`};
const splitLabel=split=>split==='dev'?'development':split==='test'?'held-out test':split;
const breakCard=([name,x])=>`<div class="break-card"><h3>${esc(name)}</h3><b>${(100*x.metrics.top_1.estimate).toFixed(1)}% Top-1</b><p>${x.cases} cases · MRR ${x.metrics.mrr.estimate.toFixed(3)} · median rank ${x.metrics.median_rank.estimate.toFixed(0)}</p></div>`;
function renderResults(){
  const split=splitLabel(results.split);
  document.getElementById('facts').innerHTML=`<div class="fact"><b>${results.case_count}</b><span>${split} cases</span></div><div class="fact"><b>${results.candidate_count}</b><span>candidate functions</span></div><div class="fact"><b>${results.bootstrap.resamples.toLocaleString()}</b><span>bootstrap resamples</span></div><div class="fact"><b>${results.split}</b><span>evaluated split</span></div>`;
  document.getElementById('cache-copy').textContent=`A deterministic mutation benchmark over toolz 1.1.0. Results load from the checked-in ${split}-set cache—no evaluation runs on page load.`;
  document.getElementById('case-label').textContent=`${split} case`;
  document.getElementById('split-note').textContent=results.split==='dev'?'The test split remains sealed until the final one-shot evaluation.':'Final results shown on the held-out test split; development data was used for all technique selection.';
  const body=document.getElementById('leaderboard'); body.innerHTML='';
  for(const name of results.localizer_order){const m=results.localizers[name].metrics,tr=document.createElement('tr'); if(name==='a6_router')tr.className='winner'; const tag=name==='a6_router'?'<span class="tag">winner</span>':name==='a7_clean_bm25'?'<span class="tag reverted">reverted</span>':''; tr.innerHTML=`<td class="method">${esc(labels[name]||name)}${tag}</td><td>${metric(m.top_1,'pct')}</td><td>${metric(m.top_5,'pct')}</td><td>${metric(m.mrr)}</td><td>${metric(m.mean_rank,'rank')}</td><td>${metric(m.median_rank,'rank')}</td><td>${metric(m.median_tokens_to_hit,'rank')}</td><td>${metric(m.p50_latency_ms,'ms')}</td><td>${metric(m.p95_latency_ms,'ms')}</td>`; body.appendChild(tr);}
  const winner=results.localizers.a6_router||results.localizers[results.localizer_order[0]];
  const baseline=results.localizers.l2_bm25;
  if(results.localizers.a6_router&&baseline){const wm=winner.metrics,bm=baseline.metrics,gain=100*(wm.top_1.estimate-bm.top_1.estimate); document.getElementById('finding').innerHTML=`<span class="finding-kicker">${esc(split)} finding</span><p><strong>Exception-aware routing finds the buggy function first in ${(100*wm.top_1.estimate).toFixed(1)}% of cases</strong>, versus ${(100*bm.top_1.estimate).toFixed(1)}% for BM25—a ${gain.toFixed(1)} percentage-point gain.</p>`; document.getElementById('winner-note').textContent=`A6 is highlighted for the strongest Top-1 and MRR, median rank ${wm.median_rank.estimate.toFixed(0)}, and ${wm.median_tokens_to_hit.estimate.toFixed(0)} median tokens-to-hit. Its higher mean rank reflects a smaller tail of difficult cases.`;}
  const groups=Object.entries(winner.breakdowns.exception_type).sort((a,b)=>b[1].cases-a[1].cases), common=groups.filter(([,x])=>x.cases>=5), rare=groups.filter(([,x])=>x.cases<5);
  document.getElementById('breakdown').innerHTML=common.map(breakCard).join('');
  document.getElementById('rare-breakdown').innerHTML=rare.length?`<details class="rare"><summary>Show ${rare.length} low-sample error types (fewer than 5 cases)</summary><div class="rare-list">${rare.map(([name,x])=>`<div class="rare-row"><span>${esc(name)} · n=${x.cases}</span><strong>${(100*x.metrics.top_1.estimate).toFixed(1)}% Top-1</strong></div>`).join('')}</div></details>`:'';
}
function optionText(c){return `${c.function_qualified_name} · ${c.operator} · ${c.exception_type}`}
function renderOptions(keep){const select=document.getElementById('case-select'); visible=cases.filter(c=>optionText(c).toLowerCase().includes(document.getElementById('search').value.toLowerCase())||c.file.toLowerCase().includes(document.getElementById('search').value.toLowerCase())); select.innerHTML=visible.map(c=>`<option value="${esc(c.case_id)}">${esc(optionText(c))}</option>`).join(''); if(keep&&visible.some(c=>c.case_id===keep))select.value=keep; if(visible.length)loadCase(select.value); else document.getElementById('case-view').innerHTML='<p class="empty">No matching cases.</p>';}
function diffHtml(text){return text.split('\n').map(line=>{const cls=line.startsWith('+')&&!line.startsWith('+++')?'diff-add':line.startsWith('-')&&!line.startsWith('---')?'diff-del':'diff-line'; return `<span class="${cls}">${esc(line)}</span>`;}).join('');}
function focusedFailure(text){const marker=text.indexOf('=== FAILURES'); return marker>=0?text.slice(marker):text;}
async function loadCase(id){const c=await fetch('/api/cases/'+encodeURIComponent(id)).then(r=>r.json()); const ranks=results.localizer_order.filter(n=>c.localizer_results[n]).sort((a,b)=>c.localizer_results[a].rank-c.localizer_results[b].rank); const tests=c.failing_tests.map(t=>t.source).join('\n\n'); document.getElementById('case-view').innerHTML=`<div class="case-meta"><span class="pill">${esc(c.case_id)}</span><span class="pill">${esc(c.file)}:${c.line_start}</span><span class="pill">${esc(c.operator)}</span><span class="pill">${esc(c.exception_type)}</span></div><div class="rank-grid">${ranks.map(n=>`<div class="rank ${n==='a6_router'?'winner':''}"><b>#${c.localizer_results[n].rank.toFixed(0)}</b><span>${esc(labels[n]||n)}</span><span>${c.localizer_results[n].tokens_to_hit.toFixed(0)} tokens-to-hit</span></div>`).join('')}</div><div class="code-grid"><div><h3>Mutation diff</h3><pre class="diff">${diffHtml(c.diff)}</pre></div><div><h3>Failing test</h3><pre>${esc(tests)}</pre></div><div style="grid-column:1/-1"><h3>Failure evidence</h3><pre>${esc(focusedFailure(c.traceback_text))}</pre><details class="raw-output"><summary>Show full raw pytest output</summary><pre>${esc(c.traceback_text)}</pre></details></div></div>`;}
Promise.all([fetch('/api/results').then(r=>r.json()),fetch('/api/cases').then(r=>r.json())]).then(([r,c])=>{results=r;cases=c;renderResults();renderOptions();});
document.getElementById('search').addEventListener('input',()=>renderOptions(document.getElementById('case-select').value));
document.getElementById('case-select').addEventListener('change',e=>loadCase(e.target.value));
</script>
</body></html>'''


app = create_app()
