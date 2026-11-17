import json
from typing import Any

import streamlit as st
from pydantic import ValidationError
from src.agent.guardrails import GuardrailViolation, apply_guardrails
from src.schemas import AlarmPayload, IncidentNotificationDraft
from src.telemetry_db import get_circuit_details

st.title("Guardrail lab")
st.caption(
    "No LLM here. Edit a draft the way a misbehaving model might emit it and watch two layers react: "
    "Pydantic schema validation, then the deterministic tenant-isolation and SLA gate."
)

CIRCUIT_ID = "IEPL-9021-LAX-TYO"
circuit = get_circuit_details(CIRCUIT_ID)
if circuit is None:
    st.error(f"Demo circuit {CIRCUIT_ID} is missing from the telemetry catalog.")
    st.stop()
max_min = circuit["contracted_sla_hours"] * 60

BASE: dict[str, Any] = {
    "incident_id": "INC-LAB-1",
    "client_name": circuit["client_name"],
    "circuit_id": CIRCUIT_ID,
    "severity": "P1_CRITICAL",
    "root_cause_category": "Physical Fiber Cut",
    "mitigation_action_taken": "Dispatched a splicing crew",
    "estimated_restoration_time": "Updates follow the scheduled cadence.",
    "next_update_window_minutes": 60,
    "notification_email_body": "Dear customer, we are working on your circuit.",
}
PRESETS: dict[str, dict[str, Any]] = {
    "Clean draft": {},
    "Cross-tenant leak": {"client_name": "Stripe Cloud Platform"},
    "Wrong circuit": {"circuit_id": "DIA-4410-SFO-JFK"},
    "SLA breach (9999 min)": {"next_update_window_minutes": 9999},
    "Zero-minute window": {"next_update_window_minutes": 0},
    "Unknown severity": {"severity": "catastrophic"},
}

st.markdown(
    f"**Ground truth:** `{CIRCUIT_ID}` belongs to **{circuit['client_name']}**, "
    f"{circuit['client_tier']}, contracted SLA {circuit['contracted_sla_hours']} h "
    f"(update window must be <= {max_min} min)."
)

preset = st.segmented_control("Failure preset", list(PRESETS), default="Clean draft", key="preset")
fields = {**BASE, **PRESETS.get(preset or "Clean draft", {})}
# Reset widget state when the preset changes so the form reflects it.
if st.session_state.get("_applied") != preset:
    for k, v in fields.items():
        st.session_state[f"f_{k}"] = v
    st.session_state["_applied"] = preset

left, right = st.columns(2, gap="large")
with left:
    st.subheader("Model output (editable)")
    edited: dict[str, Any] = {
        "incident_id": st.text_input("incident_id", key="f_incident_id"),
        "client_name": st.text_input("client_name", key="f_client_name"),
        "circuit_id": st.text_input("circuit_id", key="f_circuit_id"),
        "severity": st.text_input("severity", key="f_severity"),
        "root_cause_category": st.text_input("root_cause_category", key="f_root_cause_category"),
        "mitigation_action_taken": st.text_input("mitigation_action_taken", key="f_mitigation_action_taken"),
        "estimated_restoration_time": st.text_input(
            "estimated_restoration_time", key="f_estimated_restoration_time"
        ),
        "next_update_window_minutes": st.number_input(
            "next_update_window_minutes", step=1, key="f_next_update_window_minutes"
        ),
        "notification_email_body": st.text_area(
            "notification_email_body", key="f_notification_email_body", height=100
        ),
    }

with right:
    st.subheader("Verdict")
    # Layer 1: Pydantic schema
    st.markdown("**Layer 1 · Pydantic schema**")
    try:
        draft = IncidentNotificationDraft(**edited)
    except ValidationError as exc:
        st.badge("Rejected", icon=":material/close:", color="red")
        for err in exc.errors():
            st.error(f"`{'.'.join(map(str, err['loc']))}`: {err['msg']}", icon=":material/block:")
        st.caption(
            "In production, Instructor feeds this error back to the model and retries (max_retries=2)."
        )
        st.stop()
    st.badge("Valid", icon=":material/check:", color="green")
    if draft.severity != str(edited["severity"]).strip().upper():
        st.warning(
            f"Severity `{edited['severity']}` is not an allowed level; the validator coerced it to "
            f"`{draft.severity}` (fail-safe default).",
            icon=":material/warning:",
        )

    # Layer 2: deterministic guardrails
    st.markdown("**Layer 2 · Deterministic gate**")
    alarm = AlarmPayload(
        incident_id=draft.incident_id,
        circuit_id=CIRCUIT_ID,
        alarm_type="FIBER_CUT",
        raw_symptom="OTDR indicates a fiber break",
        detected_at="2026-11-17T00:00:00Z",
    )
    try:
        out, checks = apply_guardrails(draft.model_copy(), alarm, circuit)
    except GuardrailViolation as exc:
        st.badge("Blocked (fail closed)", icon=":material/close:", color="red")
        st.error(str(exc))
        st.caption("No customer email is released. A human operator takes over.")
    else:
        st.badge("Tenant isolation passed", icon=":material/check:", color="green")
        if checks["auto_remediated"]:
            st.badge("SLA auto-remediated", icon=":material/warning:", color="orange")
            st.warning(
                f"Window clamped from {draft.next_update_window_minutes} to "
                f"{out.next_update_window_minutes} min (SLA limit)."
            )
        else:
            st.badge("SLA compliant", icon=":material/check:", color="green")
        st.caption("Released to the operator for human review.")

with st.expander("Pydantic output contract (JSON Schema)"):
    st.json(IncidentNotificationDraft.model_json_schema(), expanded=False)
with st.expander("Validated payload"):
    st.code(json.dumps(draft.model_dump(), indent=2), language="json")
