import altair as alt
import pandas as pd
import streamlit as st

from common import load_faithfulness_report

st.title("Eval dashboard")
st.caption(
    "Offline LLM-as-judge results from DeepEval on the end-to-end agent "
    "(retrieval, then gpt-4o-mini draft, then guardrails). Numbers are read from "
    "`evals/faithfulness_results.json`, not recomputed in this page."
)

report = load_faithfulness_report()
if report is None:
    st.warning("No `evals/faithfulness_results.json`. Run `python -m evals.faithfulness_eval`.")
    st.stop()

summary, rows, thr = report["summary"], report["scenarios"], report["threshold"]
df = pd.DataFrame(rows)
n = report["scenario_count"]

with st.container(horizontal=True):
    st.metric(
        "Faithfulness (mean)",
        f"{summary['faithfulness_mean']:.2f}",
        f"min {summary['faithfulness_min']:.2f}",
        border=True,
        delta_color="off",
    )
    st.metric(
        "Factual alignment (mean)",
        f"{summary['hallucination_mean']:.2f}",
        f"min {summary['hallucination_min']:.2f}",
        border=True,
        delta_color="off",
    )
    st.metric("Retrieval correct", f"{summary['retrieval_correct']}/{n}", border=True)
    st.metric("Guardrails passed", f"{summary['guardrails_passed']}/{n}", border=True)

st.caption(
    f"Judge `{report['judge_model']}` · pass threshold {thr} · abstain T={report['retrieval_abstain_threshold']} · "
    f"measured {report['measured_at']}"
)

tab_scores, tab_fail, tab_retr = st.tabs(["Scores by scenario", "Failure analysis", "Retrieval ablation"])

with tab_scores:
    long = df.melt(
        id_vars=["alarm_type"],
        value_vars=["faithfulness", "hallucination"],
        var_name="metric",
        value_name="score",
    ).replace({"faithfulness": "Faithfulness", "hallucination": "Factual alignment"})
    bars = (
        alt.Chart(long)
        .mark_bar()
        .encode(
            x=alt.X("alarm_type:N", title=None, sort=None),
            xOffset="metric:N",
            y=alt.Y("score:Q", scale=alt.Scale(domain=[0, 1]), title="Score"),
            color=alt.Color("metric:N", title=None),
            tooltip=["alarm_type", "metric", "score"],
        )
    )
    rule = alt.Chart(pd.DataFrame({"t": [thr]})).mark_rule(strokeDash=[6, 4], color="red").encode(y="t:Q")
    st.altair_chart(
        bars + rule,
        alt=f"Grouped bars of faithfulness and factual alignment per scenario with a pass line at {thr}",
    )

    table = pd.DataFrame(
        {
            "Scenario": df["alarm_type"],
            "Cited SOP": df["cited_files"].map(lambda f: f[0] if f else "abstained"),
            "Retrieval": df["retrieval_correct"].map({True: "correct", False: "wrong"}),
            "Faithfulness": df["faithfulness"],
            "Faith. gate": df["faithfulness"].ge(thr).map({True: "pass", False: "below"}),
            "Alignment": df["hallucination"],
            "Align. gate": df["hallucination"].ge(thr).map({True: "pass", False: "below"}),
            "Guardrails": (df["tenant_isolation_passed"] & df["sla_compliance_passed"]).map(
                {True: "pass", False: "FAIL"}
            ),
        }
    )
    st.dataframe(table, hide_index=True, alt="Per-scenario eval scores and gate results")
    below = int((df["faithfulness"] < thr).sum() + (df["hallucination"] < thr).sum())
    st.info(
        f"{below} of {2 * n} metric scores sit below the {thr} threshold. "
        "Retrieval and guardrails are clean; the misses are generation drift (next tab)."
    )

with tab_fail:
    st.caption("Judge reasons verbatim. These are the findings to fix next, not hidden by the mean.")
    for r in rows:
        cited = r["cited_files"][0] if r["cited_files"] else "abstained"
        with st.expander(
            f"{r['alarm_type']} · faithfulness {r['faithfulness']:.2f} · alignment {r['hallucination']:.2f} · `{cited}`"
        ):
            st.markdown(f"**Faithfulness:** {r['faithfulness_reason']}")
            st.markdown(f"**Factual alignment:** {r['hallucination_reason']}")
            st.caption(f"Next update window after guardrail: {r['next_update_window_minutes']} min")
    st.caption(
        "DeepEval's HallucinationMetric penalises omitted facts as contradictions, "
        "so faithfulness is treated as the headline metric."
    )

with tab_retr:
    st.caption("45-case golden set (35 positive, 10 negative). Source: `evals/results.md`, dated entries.")
    ablation = pd.DataFrame(
        [
            ("2026-10-21", "Whole-doc + aliases, k=2", 0.771, 0.914, 0.843),
            ("2026-10-22", "+ header chunks, parent SOP", 0.800, 0.971, 0.886),
            ("2026-10-23", "+ BM25 / RRF fusion", 0.771, 0.971, 0.871),
            ("2026-10-24", "+ MiniLM rerank, abstain T=0.5", 0.857, 0.971, 0.914),
        ],
        columns=["Date", "Stage", "hit@1", "hit@2", "MRR"],
    )
    st.line_chart(ablation, x="Stage", y=["hit@1", "hit@2", "MRR"], alt="Retrieval metrics by pipeline stage")
    st.dataframe(ablation, hide_index=True, alt="Retrieval ablation table")
    st.caption(
        "RRF alone lowered hit@1 (0.800 to 0.771); the rerank stage recovered it. At T=0.5 all ten negatives abstain."
    )
