from __future__ import annotations

import os
import uuid
from typing import Any

import requests
import streamlit as st

API_BASE_URL = os.getenv("RCA_API_BASE_URL", "http://localhost:8000").rstrip("/")


st.set_page_config(
    page_title="RCA Console",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    st.title("RCA Console")
    st.caption("Incident analysis, RCA reasoning, runbooks, graph context, and copilot.")

    page = st.sidebar.radio(
        "View",
        [
            "Dashboard",
            "Incident Detail",
            "Graph",
            "Agent Report",
            "Runbooks",
            "Copilot",
            "Postmortem",
            "RAG Evaluation",
            "Storage Health",
        ],
    )
    st.sidebar.text_input("API Base URL", value=API_BASE_URL, key="api_base_url")

    if page == "Dashboard":
        dashboard()
    elif page == "Incident Detail":
        incident_detail()
    elif page == "Graph":
        graph_view()
    elif page == "Agent Report":
        agent_report()
    elif page == "Runbooks":
        runbooks()
    elif page == "Copilot":
        copilot()
    elif page == "Postmortem":
        postmortem()
    elif page == "RAG Evaluation":
        rag_evaluation()
    elif page == "Storage Health":
        storage_health()


def dashboard() -> None:
    health = api_get("/health")
    rca_results = api_get("/rca/latest", {"limit": 20}).get("items", [])
    agent_reports = api_get("/agents/reports/latest", {"limit": 20}).get("items", [])

    left, middle, right, far_right = st.columns(4)
    left.metric("RCA Results", len(rca_results))
    middle.metric("Agent Reports", len(agent_reports))
    right.metric("API", health.get("status", "unknown"))
    far_right.metric("Service", health.get("service", "unknown"))

    st.subheader("Latest RCA Results")
    st.dataframe(_compact_rca_rows(rca_results), use_container_width=True, hide_index=True)

    st.subheader("Latest Agent Reports")
    st.dataframe(_compact_report_rows(agent_reports), use_container_width=True, hide_index=True)


def incident_detail() -> None:
    incident_id = incident_selector()
    if not incident_id:
        st.info("No incident selected.")
        return
    result = api_get(f"/rca/{incident_id}")
    report = safe_api_get(f"/agents/reports/{incident_id}")

    st.subheader(result.get("summary", incident_id))
    cols = st.columns(4)
    cols[0].metric("Service", result.get("service", "unknown"))
    cols[1].metric("Env", result.get("env", "unknown"))
    cols[2].metric("Severity", result.get("severity", "unknown"))
    cols[3].metric("Confidence", f"{result.get('confidence', 0):.2f}")

    overview, timeline, evidence, raw = st.tabs(["Overview", "Timeline", "Evidence", "Raw JSON"])
    with overview:
        st.markdown("#### Root Causes")
        for root in result.get("root_causes", []):
            st.write(f"**{root.get('title')}**")
            st.caption(f"{root.get('category')} | confidence={root.get('confidence')}")
            st.write(root.get("description"))
        st.markdown("#### Recommended Actions")
        for action in result.get("recommended_actions", []):
            st.write(f"- {action}")
        if report:
            st.markdown("#### Notification Draft")
            st.info(report.get("notification_draft", ""))

    with timeline:
        st.dataframe(result.get("timeline", []), use_container_width=True, hide_index=True)

    with evidence:
        st.dataframe(result.get("evidence", []), use_container_width=True, hide_index=True)

    with raw:
        st.json(result)


def graph_view() -> None:
    incident_id = incident_selector()
    if not incident_id:
        st.info("No incident selected.")
        return
    graph = api_get(f"/incidents/{incident_id}/graph")
    st.subheader(f"Incident Graph: {incident_id}")
    left, right = st.columns(2)
    with left:
        st.markdown("#### Nodes")
        st.dataframe(graph.get("nodes", []), use_container_width=True, hide_index=True)
    with right:
        st.markdown("#### Relationships")
        st.dataframe(graph.get("relationships", []), use_container_width=True, hide_index=True)
    st.markdown("#### Raw Graph")
    st.json(graph)


def agent_report() -> None:
    incident_id = incident_selector()
    if not incident_id:
        st.info("No incident selected.")
        return
    report = api_get(f"/agents/reports/{incident_id}")
    st.subheader(report.get("summary", incident_id))
    st.info(report.get("notification_draft", ""))

    findings, runbook_tab, followups, raw = st.tabs(["Findings", "Runbooks", "Follow-ups", "Raw JSON"])
    with findings:
        st.dataframe(report.get("agent_findings", []), use_container_width=True, hide_index=True)
    with runbook_tab:
        for item in report.get("runbook_recommendations", []):
            st.write(f"**{item.get('title')}**")
            st.caption(f"{item.get('match_reason')} | confidence={item.get('confidence')}")
            for step in item.get("steps", []):
                st.write(f"- {step}")
    with followups:
        for question in report.get("follow_up_questions", []):
            st.write(f"- {question}")
    with raw:
        st.json(report)


def runbooks() -> None:
    items = api_get("/runbooks").get("items", [])
    st.subheader("Runbook Library")
    st.dataframe(
        [
            {
                "runbook_id": item.get("runbook_id"),
                "title": item.get("title"),
                "categories": ", ".join(item.get("categories", [])),
                "keywords": ", ".join(item.get("keywords", [])),
            }
            for item in items
        ],
        use_container_width=True,
        hide_index=True,
    )
    selected = st.selectbox("Runbook", [item.get("runbook_id") for item in items] or [])
    if selected:
        st.json(api_get(f"/runbooks/{selected}"))


def copilot() -> None:
    st.subheader("RCA Copilot")
    incident_id = st.text_input("Incident ID (optional)", value=selected_incident_id())
    question = st.text_area("Question", value="What is the most likely root cause and which runbook should I follow?")
    mode = st.radio("Mode", ["auto", "fast", "deep"], horizontal=True)
    if st.button("Ask Copilot", type="primary"):
        payload = {"question": question, "incident_id": incident_id or None, "limit": 8, "mode": mode}
        response = api_post("/copilot/chat", payload)
        st.session_state["last_copilot_response"] = response
        cols = st.columns(4)
        cols[0].metric("Confidence", f"{response.get('confidence', 0):.2f}")
        cols[1].metric("Path", response.get("response_path", "unknown"))
        cols[2].metric("Latency", f"{response.get('latency_ms', 0)} ms")
        cols[3].metric("Cache", "hit" if response.get("cache_hit") else "miss")
        st.text_area("Answer", value=response.get("answer", ""), height=280)
        st.markdown("#### Verification")
        st.json(response.get("verification", {}))
        st.markdown("#### Citations")
        st.dataframe(response.get("citations", []), use_container_width=True, hide_index=True)
        st.markdown("#### Matches")
        st.dataframe(response.get("matches", []), use_container_width=True, hide_index=True)
        st.markdown("#### Suggested Follow-ups")
        for item in response.get("suggested_followups", []):
            st.write(f"- {item}")

    response = st.session_state.get("last_copilot_response")
    if response:
        st.markdown("#### Feedback")
        feedback_rating = st.selectbox("Rating", ["useful", "not_useful", "incorrect", "unsafe", "other"])
        feedback_comment = st.text_input("Comment")
        if st.button("Send Feedback"):
            api_post(
                "/copilot/feedback",
                {
                    "feedback_id": str(uuid.uuid4()),
                    "incident_id": response.get("incident_id"),
                    "rating": feedback_rating,
                    "comment": feedback_comment or None,
                },
            )
            st.success("Feedback saved.")

    st.markdown("#### Knowledge Search")
    query = st.text_input("Search query", value="application exception latency")
    if st.button("Search Knowledge"):
        matches = api_get("/knowledge/search", {"q": query, "incident_id": incident_id or None, "limit": 10})
        st.caption(f"Intent: {matches.get('intent', 'unknown')}")
        st.dataframe(matches.get("items", []), use_container_width=True, hide_index=True)


def postmortem() -> None:
    incident_id = incident_selector()
    if not incident_id:
        st.info("No incident selected.")
        return
    st.subheader("Postmortem Draft")
    if st.button("Generate Draft", type="primary"):
        draft = api_get(f"/incidents/{incident_id}/postmortem-draft")
        st.session_state["postmortem_draft"] = draft
    if st.button("Promote to Historical Incident"):
        promoted = api_post(f"/incidents/{incident_id}/promote-historical", {})
        st.success(f"Promoted: {promoted.get('historical_incident_id')}")
    draft = st.session_state.get("postmortem_draft")
    if not draft:
        st.info("Generate a draft from RCA evidence and agent report context.")
        return
    st.write(f"### {draft.get('title')}")
    st.write("#### Summary")
    st.write(draft.get("summary"))
    st.write("#### Impact")
    st.write(draft.get("impact"))
    st.write("#### Root Cause")
    st.write(draft.get("root_cause"))
    st.write("#### Timeline")
    for item in draft.get("timeline", []):
        st.write(f"- {item}")
    st.write("#### Manual Follow-ups")
    for item in draft.get("manual_followups", []):
        st.write(f"- {item}")
    st.write("#### Citations")
    st.dataframe(draft.get("citations", []), use_container_width=True, hide_index=True)


def rag_evaluation() -> None:
    st.subheader("RAG Evaluation")
    left, right = st.columns([1, 3])
    with left:
        if st.button("Reindex RAG Documents"):
            st.json(api_post("/rag/reindex?limit=200", {}))
    data = api_get("/rag/evaluations", {"limit": 100})
    st.markdown("#### Metrics")
    st.json(data.get("metrics", {}))
    st.markdown("#### Query Traces")
    st.dataframe(data.get("traces", []), use_container_width=True, hide_index=True)
    st.markdown("#### Feedback")
    st.dataframe(data.get("feedback", []), use_container_width=True, hide_index=True)


def storage_health() -> None:
    st.subheader("Storage Health")
    st.json(api_get("/storage/health"))


def incident_selector() -> str:
    incidents = api_get("/rca/latest", {"limit": 50}).get("items", [])
    options = [item.get("incident_id") for item in incidents if item.get("incident_id")]
    default = selected_incident_id()
    if default and default not in options:
        options.insert(0, default)
    if not options:
        return ""
    selected = st.sidebar.selectbox("Incident", options)
    st.session_state["incident_id"] = selected
    return selected


def selected_incident_id() -> str:
    return str(st.session_state.get("incident_id", ""))


def api_base() -> str:
    return str(st.session_state.get("api_base_url", API_BASE_URL)).rstrip("/")


def api_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(f"{api_base()}{path}", params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def safe_api_get(path: str) -> dict[str, Any] | None:
    try:
        return api_get(path)
    except requests.RequestException:
        return None


def api_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(f"{api_base()}{path}", json=payload, timeout=20)
    response.raise_for_status()
    return response.json()


def _compact_rca_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "incident_id": item.get("incident_id"),
            "service": item.get("service"),
            "env": item.get("env"),
            "severity": item.get("severity"),
            "confidence": item.get("confidence"),
            "summary": item.get("summary"),
        }
        for item in items
    ]


def _compact_report_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "incident_id": item.get("incident_id"),
            "service": item.get("service"),
            "severity": item.get("severity"),
            "findings": len(item.get("agent_findings", [])),
            "runbooks": len(item.get("runbook_recommendations", [])),
            "summary": item.get("summary"),
        }
        for item in items
    ]


if __name__ == "__main__":
    main()
