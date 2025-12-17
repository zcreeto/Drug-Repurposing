import streamlit as st
import asyncio
import pathlib
import json
from typing import Dict, Any, List, Tuple
import pandas as pd
try:
    import plotly.express as px
    _HAVE_PLOTLY = True
except Exception:
    _HAVE_PLOTLY = False

from agents.master import run_master
from agents.report_agent import generate_pdf_report

# -----------------------------
# Page Config
# -----------------------------
st.set_page_config(
    page_title="AEO",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -----------------------------
# Premium CSS (Streamlit UI polish)
# -----------------------------
CUSTOM_CSS = """
<style>
.block-container { padding-top: 1.25rem; padding-bottom: 2rem; }

.aeo-hero {
  border-radius: 18px;
  padding: 18px 18px;
  background: linear-gradient(135deg, rgba(19, 31, 55, 0.95), rgba(24, 43, 78, 0.92));
  border: 1px solid rgba(255,255,255,0.08);
  box-shadow: 0 10px 30px rgba(0,0,0,0.22);
}
.aeo-hero h1 { margin: 0; font-size: 1.55rem; }
.aeo-hero p { margin: 0.25rem 0 0 0; opacity: 0.9; }

.pill {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  border: 1px solid rgba(255,255,255,0.12);
  background: rgba(255,255,255,0.06);
  margin-right: 8px;
}

.kpi {
  border-radius: 16px;
  padding: 14px 14px;
  border: 1px solid rgba(255,255,255,0.10);
  background: rgba(255,255,255,0.04);
}
.kpi .label { font-size: 12px; opacity: 0.85; margin-bottom: 6px; }
.kpi .value { font-size: 22px; font-weight: 700; line-height: 1.2; }
.kpi .sub { font-size: 12px; opacity: 0.75; margin-top: 4px; }

.section-title {
  font-size: 1.05rem;
  font-weight: 700;
  margin: 0.2rem 0 0.6rem 0;
}

.badge-live, .badge-mock, .badge-failed, .badge-partial, .badge-unk {
  border-radius: 12px;
  padding: 10px 12px;
  border: 1px solid rgba(255,255,255,0.12);
  background: rgba(255,255,255,0.04);
}
.badge-live { border-left: 6px solid rgba(0, 210, 120, 0.85); }
.badge-mock { border-left: 6px solid rgba(255, 185, 0, 0.90); }
.badge-failed { border-left: 6px solid rgba(255, 70, 70, 0.90); }
.badge-partial { border-left: 6px solid rgba(255, 140, 0, 0.90); }
.badge-unk { border-left: 6px solid rgba(160, 160, 160, 0.70); }
.badge-title { font-weight: 700; margin-bottom: 2px; }
.badge-sub { font-size: 12px; opacity: 0.8; }

.small-card {
  border-radius: 14px;
  padding: 12px 12px;
  border: 1px solid rgba(255,255,255,0.10);
  background: rgba(255,255,255,0.03);
}
.small-card h4 { margin: 0 0 6px 0; font-size: 14px; }
.small-card p { margin: 0; font-size: 13px; opacity: 0.9; }

.exec-brief {
  border-radius: 16px;
  padding: 14px 14px;
  border: 1px solid rgba(255,255,255,0.10);
  background: rgba(255,255,255,0.03);
}
.exec-brief h3 { margin: 0 0 10px 0; font-size: 16px; }
.exec-brief .row { margin: 6px 0; }
.exec-brief .k { font-weight: 700; }
.exec-brief .v { opacity: 0.92; }

table { border-radius: 12px; overflow: hidden; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# -----------------------------
# Helpers
# -----------------------------
def _status_meta(agent_out: Dict[str, Any]):
    status = str((agent_out or {}).get("status", "UNKNOWN")).upper()
    warnings = (agent_out or {}).get("warnings", []) or []
    meta = (agent_out or {}).get("meta", {}) or {}
    cache_hit = bool(meta.get("cache", False))
    return status, warnings, meta, cache_hit

def render_status_badge(agent_out: Dict[str, Any]):
    status, warnings, meta, cache_hit = _status_meta(agent_out)

    if status == "LIVE":
        cls = "badge-live"
        title = "✅ LIVE" + (" (cache)" if cache_hit else "")
        sub = "Primary sources successful"
    elif status == "MOCK":
        cls = "badge-mock"
        title = "🟡 MOCK fallback"
        sub = "Stable demo mode / fallback used"
    elif status == "FAILED":
        cls = "badge-failed"
        title = "🔴 FAILED"
        sub = "Agent failed (fallback unsuccessful)"
    elif status == "PARTIAL":
        cls = "badge-partial"
        title = "🟠 PARTIAL"
        sub = "Some sources missing / partial evidence"
    else:
        cls = "badge-unk"
        title = f"ℹ️ {status}"
        sub = "Status not reported"

    warn_txt = " | ".join([str(w) for w in warnings[:3]]) if warnings else ""

    st.markdown(
        f"""
        <div class="{cls}">
          <div class="badge-title">{title}</div>
          <div class="badge-sub">{sub}{(" · " + warn_txt) if warn_txt else ""}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

def make_table_dicts(columns: List[str], rows: List[list]):
    if not columns or not rows:
        return None
    out = []
    for r in rows:
        try:
            out.append(dict(zip(columns, r)))
        except Exception:
            pass
    return out

def compute_run_health(agent_outputs: Dict[str, Any]):
    live = sum(1 for _, v in agent_outputs.items() if str((v or {}).get("status", "")).upper() == "LIVE")
    mock = sum(1 for _, v in agent_outputs.items() if str((v or {}).get("status", "")).upper() == "MOCK")
    failed = sum(1 for _, v in agent_outputs.items() if str((v or {}).get("status", "")).upper() == "FAILED")
    partial = sum(1 for _, v in agent_outputs.items() if str((v or {}).get("status", "")).upper() == "PARTIAL")
    return live, mock, failed, partial

def big_decision_banner(final_decision: str, score: int):
    final_decision = (final_decision or "HOLD").upper()
    if final_decision == "GO":
        st.success(f"✅ FINAL DECISION: GO  •  Opportunity Score: {score}/100")
    elif final_decision in ["NO-GO", "NOGO", "NO_GO"]:
        st.error(f"❌ FINAL DECISION: NO-GO  •  Opportunity Score: {score}/100")
    else:
        st.warning(f"⚠️ FINAL DECISION: HOLD  •  Opportunity Score: {score}/100")

def get_conf_score(agent_out: Dict[str, Any]) -> int:
    conf_score = (agent_out or {}).get("confidence_score", None)
    if conf_score is None:
        conf_score = (agent_out or {}).get("confidence", 0)
    try:
        v = float(conf_score)
        if v <= 1.0:
            v *= 100.0
        return int(round(v))
    except Exception:
        return 0

def extract_top_snippets(agent_outputs: Dict[str, Any], max_items: int = 10) -> List[Dict[str, str]]:
    snippets = []
    for k, out in agent_outputs.items():
        agent_name = (out or {}).get("agent_name", k)
        status = str((out or {}).get("status", "UNKNOWN")).upper()
        conf = get_conf_score(out)

        bullets = (out or {}).get("summary_bullets", []) or []
        if bullets:
            for b in bullets[:2]:
                snippets.append({"agent": agent_name, "status": status, "confidence": str(conf), "text": str(b)})
        else:
            s = str((out or {}).get("summary", "")).strip()
            if s:
                snippets.append({"agent": agent_name, "status": status, "confidence": str(conf), "text": s[:180] + ("..." if len(s) > 180 else "")})

    def rank_key(x):
        status = x["status"]
        status_rank = 0 if status == "LIVE" else (1 if status == "MOCK" else 2)
        return (status_rank, -int(x["confidence"]))

    snippets.sort(key=rank_key)
    return snippets[:max_items]

def filter_agents(agent_items: List[Tuple[str, Dict[str, Any]]], search: str, status_filter: str):
    search = (search or "").strip().lower()
    status_filter = (status_filter or "ALL").upper()

    filtered = []
    for k, out in agent_items:
        name = str((out or {}).get("agent_name", k)).lower()
        status = str((out or {}).get("status", "UNKNOWN")).upper()
        if status_filter != "ALL" and status != status_filter:
            continue
        if search and (search not in name) and (search not in k.lower()):
            continue
        filtered.append((k, out))
    return filtered

def build_exec_brief(result: Dict[str, Any]) -> str:
    case = result.get("run_meta", {}).get("case", {}) or {}
    ranking = result.get("ranking", []) or []
    top = ranking[0] if ranking else {}
    gates = result.get("decision_gates", {}) or {}

    decision = str(gates.get("final", "HOLD")).upper()
    score = top.get("score", "N/A")
    title = top.get("title", "Top opportunity not available")

    next_steps = (result.get("product_story", {}) or {}).get("next_steps", []) or []
    next_steps_txt = "\n".join([f"- {x}" for x in next_steps[:4]]) if next_steps else "- Define next experimental + regulatory steps"

    brief = f"""AEO Executive Brief

Case:
- Query: {case.get("query","")}
- Molecule: {case.get("molecule","")}
- Target disease: {case.get("disease","")}
- Geography: {case.get("geography","")}
- Innovation angle: {case.get("innovation_angle","")}

Top Opportunity:
- {title}

Decision:
- Final: {decision}
- Opportunity score: {score}/100

Key Gate Rationale:
- Gate A: {gates.get("gate_a_rationale","N/A")}
- Gate B (Trials): {gates.get("gate_b_trials","N/A")}
- Gate C (IP): {gates.get("gate_c_ip","N/A")}

Recommended Next Steps:
{next_steps_txt}
"""
    return brief

# -----------------------------
# Header
# -----------------------------
st.markdown(
        """
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;">
            <div style="flex:1">
                <h1 style="margin:0;">AEO – Agentic Evidence Orchestrator</h1>
                <div style="margin-top:6px;color:var(--secondary-text-color,#6b7280);">Orchestrate agentic evidence discovery for rapid go/hold/no-go decisions.</div>
            </div>
            <div style="display:flex;gap:8px;align-items:center">
                <div class="pill" style="font-size:12px;padding:6px 10px;">Agentic AI</div>
                <div class="pill" style="font-size:12px;padding:6px 10px;">GO/HOLD/NO-GO</div>
                <div class="pill" style="font-size:12px;padding:6px 10px;">PDF Export</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
)


# -----------------------------
# Sidebar (inputs moved here for a compact demo UI)
# -----------------------------
with st.sidebar:
    st.header("Run Settings")
    mode = st.selectbox("Mode", ["mock", "live"], index=0)

    st.markdown("---")
    st.caption("Research prompt & inputs")
    query = st.text_input("Prompt (molecule / disease / research question)", "Metformin repurposing in oncology")
    molecule = st.text_input("Molecule (optional)", "Metformin")
    disease = st.text_input("Target disease (optional)", "Oncology")
    geo = st.selectbox("Geography", ["US/India", "US", "EU", "India"])
    angle = st.selectbox("Innovation angle", ["New indication", "New formulation", "New population"]) 

    st.markdown("")
    start_btn = st.button("Run Evidence Discovery", use_container_width=True)

    st.markdown("---")
    st.caption("Quick Demo Cases")
    demo_case_1 = st.button("Demo: Metformin → Oncology", use_container_width=True)
    demo_case_2 = st.button("Demo: Atorvastatin → Alzheimer’s", use_container_width=True)

    st.markdown("---")
    st.caption("Demo Controls")
    reset_run = st.button("♻️ Reset Run (Clear Output)", use_container_width=True)

# -----------------------------
# Session State
# -----------------------------
if "result" not in st.session_state:
    st.session_state.result = None

if reset_run:
    st.session_state.result = None
    st.rerun()

# Inputs are now placed in the sidebar to create a compact demo UX
if demo_case_1:
    query = "Metformin repurposing in oncology"
    molecule = "Metformin"
    disease = "Oncology"
    geo = "US/India"
    angle = "New indication"
    start_btn = True
    mode = "mock"

if demo_case_2:
    query = "Atorvastatin repurposing in Alzheimer’s disease"
    molecule = "Atorvastatin"
    disease = "Alzheimer’s disease"
    geo = "US/India"
    angle = "New indication"
    start_btn = True
    mode = "mock"

# -----------------------------
# Run (safe wrapper)
# -----------------------------
if start_btn:
    case = {
        "query": query.strip(),
        "molecule": molecule.strip(),
        "disease": disease.strip(),
        "geography": geo,
        "innovation_angle": angle
    }

    progress = st.progress(0)
    status_text = st.empty()

    status_text.text("Master Agent planning tasks...")
    progress.progress(20)

    status_text.text("Worker agents running in parallel...")
    progress.progress(45)

    try:
        with st.spinner("Orchestrating agents in parallel..."):
            st.session_state.result = asyncio.run(run_master(case, mode=mode))
    except Exception as e:
        st.session_state.result = None
        st.error(f"Run failed: {e}")
        st.stop()

    status_text.text("Synthesizing evidence → decision gates → ranking...")
    progress.progress(85)

    status_text.text("Run complete")
    progress.progress(100)

# -----------------------------
# Outputs
# -----------------------------
result = st.session_state.result

if result:
    agent_outputs = result.get("agent_outputs", {})
    live, mock, failed, partial = compute_run_health(agent_outputs)

    tabs = st.tabs(["Results", "Evidence Panels", "Report & Archive"])

    # -----------------
    # Results tab
    # -----------------
    with tabs[0]:
        st.markdown('<div style="display:flex;gap:12px;align-items:center;justify-content:space-between">', unsafe_allow_html=True)
        # status badge
        render_status_badge({"status": result.get("run_meta", {}).get("mode", "UNKNOWN").upper()})
        st.markdown('</div>', unsafe_allow_html=True)

        # compute summary metrics
        try:
            top_score = int(result.get("ranking", [{}])[0].get("score", 0))
        except Exception:
            top_score = 0

        # evidence count (use normalized evidence_items where available)
        evidence_items = 0
        for _, out in agent_outputs.items():
            evidence_items += len((out or {}).get("evidence_items", []) or [])

        # average confidence
        avg_conf = 0
        try:
            conf_vals = [get_conf_score(v) for v in agent_outputs.values()]
            avg_conf = int(round(sum(conf_vals) / max(1, len(conf_vals))))
        except Exception:
            avg_conf = 0

        runtime = result.get("run_meta", {}).get("elapsed_seconds") or result.get("run_meta", {}).get("runtime_seconds") or result.get("run_meta", {}).get("runtime") or "N/A"

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Total Score", f"{top_score}/100")
        with m2:
            st.metric("Evidence Items", f"{evidence_items}")
        with m3:
            st.metric("Confidence", f"{avg_conf}/100")
        with m4:
            st.metric("Runtime", f"{runtime}")

        st.divider()

        # Charts: Agent health donut + confidence bar
        agent_health = result.get("run_meta", {}).get("agent_health") or {}
        if not agent_health:
            # fallback: compute
            lh, lm, lf, lp = compute_run_health(agent_outputs)
            agent_health = {"LIVE": lh, "MOCK": lm, "FAILED": lf, "PARTIAL": lp}

        cols_chart = st.columns([1, 1])
        with cols_chart[0]:
            if _HAVE_PLOTLY:
                dfh = pd.DataFrame([{"status": k, "count": v} for k, v in agent_health.items()])
                fig = px.pie(dfh, names="status", values="count", hole=0.5, title="Agent Health")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.write("Agent Health:")
                st.table(agent_health)

        with cols_chart[1]:
            # confidence by agent
            try:
                rows = []
                for k, v in agent_outputs.items():
                    rows.append({"agent": (v or {}).get("agent_name", k), "confidence": int((v or {}).get("confidence", 0))})
                dfc = pd.DataFrame(rows)
                if _HAVE_PLOTLY and not dfc.empty:
                    fig2 = px.bar(dfc, x="agent", y="confidence", title="Confidence by Agent")
                    st.plotly_chart(fig2, use_container_width=True)
                else:
                    st.table(dfc)
            except Exception:
                st.write("Confidence data not available")

        # Ranking table (ranked candidates)
        st.subheader("Opportunity Ranking")
        ranking_rows = []
        for r in result.get("ranking", []):
            ranking_rows.append({
                "Rank": r.get("rank"),
                "Opportunity": r.get("title"),
                "Score": r.get("score"),
                "Decision": r.get("decision")
            })
        st.table(ranking_rows)

    # -----------------
    # Evidence Panels tab
    # -----------------
    with tabs[1]:
        st.subheader("Evidence Panels")
        st.caption("Browse clinical, literature, safety, patents, market and repurposing evidence.")

        panel_names = ["Clinical", "Literature", "Safety", "Patents", "Market", "Repurposing"]
        panels = st.tabs(panel_names)

        # mapping of agent keys to panel index
        map_keys = {
            "trials": "Clinical",
            "literature": "Literature",
            "safety": "Safety",
            "patents": "Patents",
            "market": "Market",
            "repurposing": "Repurposing",
        }

        # group agents by panel
        grouped = {p: [] for p in panel_names}
        for k, out in agent_outputs.items():
            panel = map_keys.get(k, None)
            if panel and panel in grouped:
                grouped[panel].append((k, out))

        # render each panel
        for i, panel in enumerate(panel_names):
            with panels[i]:
                agents = grouped.get(panel, [])
                if not agents:
                    st.info(f"No items for {panel}")
                    continue
                for key, aout in agents:
                    title = (aout or {}).get("agent_name", key)
                    st.markdown(f"### {title}")
                    # filters
                    min_conf = st.slider(f"Min confidence for {title}", 0, 100, 0, key=f"conf_{key}")
                    status_filter = st.selectbox(f"Status filter for {title}", ["ALL", "LIVE", "MOCK", "PARTIAL", "FAILED"], index=0, key=f"status_{key}")

                    ev_items = (aout or {}).get("evidence_items") or (aout or {}).get("evidence") or []
                    # normalize to list of dicts
                    rows = []
                    for idx, ev in enumerate(ev_items):
                        title_ev = ev.get("title") or ev.get("event") or ev.get("source") or str(ev)
                        snippet = ev.get("snippet") or ev.get("text") or ""
                        url = ev.get("url") or ev.get("link") or ""
                        rows.append({"idx": idx, "title": title_ev, "snippet": snippet, "url": url})

                    if not rows:
                        st.info("No evidence items for this agent.")
                        continue

                    df = pd.DataFrame(rows)
                    st.dataframe(df)

                    # drill-down selection
                    sel = st.selectbox(f"Select evidence row to inspect ({title})", options=df["idx"].tolist(), key=f"sel_{key}")
                    detail = df[df["idx"] == sel].to_dict(orient="records")
                    if detail:
                        d = detail[0]
                        st.markdown(f"**Title:** {d.get('title')}\n\n**Snippet:** {d.get('snippet')}\n\n**URL:** {d.get('url')}")

    # -----------------
    # Report & Archive tab
    # -----------------
    with tabs[2]:
        st.subheader("Report & Archive")
        st.markdown("Generate and download artifacts from this run, or inspect past runs.")

        col1, col2 = st.columns([1, 1])
        with col1:
            run_json_bytes = json.dumps(result, indent=2).encode("utf-8")
            st.download_button(
                "⬇️ Download Run JSON",
                data=run_json_bytes,
                file_name=f"{result['run_meta']['run_id']}.json",
                mime="application/json",
                use_container_width=True,
            )
        with col2:
            if st.button("⬇️ Download Executive Brief (TXT)"):
                exec_brief = build_exec_brief(result)
                st.download_button("Download Brief", data=exec_brief.encode("utf-8"), file_name="executive_brief.txt", mime="text/plain")

        st.markdown("---")
        # PDF generation
        if st.button("Generate Evidence PDF"):
            try:
                with st.spinner("Generating PDF report..."):
                    pdf_path = generate_pdf_report(result)
                st.success(f"📄 PDF created: {pdf_path}")
                pdf_bytes = pathlib.Path(pdf_path).read_bytes()
                st.download_button(label="⬇️ Download PDF Report", data=pdf_bytes, file_name=pathlib.Path(pdf_path).name, mime="application/pdf", use_container_width=True)
            except Exception as e:
                st.error(f"PDF generation failed: {e}")

        st.markdown("---")
        # Past runs (audit trail)
        try:
            runs_dir = pathlib.Path("outputs/runs")
            runs = []
            if runs_dir.exists() and runs_dir.is_dir():
                for p in sorted(runs_dir.glob("*.json"), reverse=True):
                    try:
                        jd = json.loads(p.read_text(encoding="utf-8"))
                        runs.append({"run_id": jd.get("run_meta", {}).get("run_id", p.name), "case": jd.get("run_meta", {}).get("case", {}), "file": p.name})
                    except Exception:
                        runs.append({"run_id": p.name, "case": {}, "file": p.name})
            if runs:
                st.markdown("**Past Runs (Audit Trail)**")
                st.table(runs[:20])
            else:
                st.info("No past runs found in outputs/runs")
        except Exception as e:
            st.warning(f"Could not load past runs: {e}")

else:
    st.warning("Run the system using **Run Evidence Discovery** (sidebar) to view outputs.")
