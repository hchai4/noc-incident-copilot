from typing import Any

import streamlit as st
from pydantic import ValidationError
from src.agent.guardrails import GuardrailViolation, apply_guardrails
from src.schemas import AlarmPayload, IncidentNotificationDraft
from src.telemetry_db import get_circuit_details

st.title("Guardrail lab")
st.caption(
    "No LLM. Pick a failure preset (or edit the fields) and see schema validation plus the tenant/SLA gate react."
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

st.caption(
    f"Ground truth: `{CIRCUIT_ID}` is **{circuit['client_name']}**, update window must be <= {max_min} min."
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
        **BASE,
        "client_name": st.text_input("client_name", key="f_client_name"),
        "circuit_id": st.text_input("circuit_id", key="f_circuit_id"),
        "severity": st.text_input("severity", key="f_severity"),
        "next_update_window_minutes": st.number_input(
            "next_update_window_minutes", step=1, key="f_next_update_window_minutes"
        ),
    }

with right:
    st.subheader("Verdict")
    try:
        draft = IncidentNotificationDraft(**edited)
    except ValidationError as exc:
        st.badge("Schema rejected", icon=":material/close:", color="red")
        for err in exc.errors():
            st.error(f"`{'.'.join(map(str, err['loc']))}`: {err['msg']}", icon=":material/block:")
        st.stop()
    st.badge("Schema valid", icon=":material/check:", color="green")
    if draft.severity != str(edited["severity"]).strip().upper():
        st.warning(f"Severity coerced to `{draft.severity}` (fail-safe default).", icon=":material/warning:")

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
