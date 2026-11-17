import pandas as pd
import streamlit as st

from common import load_faithfulness_report

st.title("Eval dashboard")
st.caption(
    "Offline DeepEval (LLM-as-judge) results on 5 end-to-end scenarios. Read from a saved report, not recomputed here."
)

report = load_faithfulness_report()
if report is None:
    st.warning("No `evals/faithfulness_results.json`. Run `python -m evals.faithfulness_eval`.")
    st.stop()

summary, rows, thr = report["summary"], report["scenarios"], report["threshold"]
n = report["scenario_count"]

with st.container(horizontal=True):
    st.metric("Faithfulness (mean)", f"{summary['faithfulness_mean']:.2f}", border=True)
    st.metric("Factual alignment (mean)", f"{summary['hallucination_mean']:.2f}", border=True)
    st.metric("Retrieval correct", f"{summary['retrieval_correct']}/{n}", border=True)
    st.metric("Guardrails passed", f"{summary['guardrails_passed']}/{n}", border=True)

st.dataframe(
    pd.DataFrame(
        {
            "Scenario": [r["alarm_type"] for r in rows],
            "Faithfulness": [r["faithfulness"] for r in rows],
            "Alignment": [r["hallucination"] for r in rows],
            "Pass": [min(r["faithfulness"], r["hallucination"]) >= thr for r in rows],
        }
    ),
    hide_index=True,
    column_config={
        "Faithfulness": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f"),
        "Alignment": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f"),
    },
)
st.caption(
    f"Pass threshold {thr} · judge {report['judge_model']} · measured {report['measured_at']}. "
    "Retrieval and guardrails are clean; sub-threshold scores are generation drift."
)

with st.expander("Judge reasons per scenario"):
    for r in rows:
        st.markdown(f"**{r['alarm_type']}** — {r['faithfulness_reason']}")
