from __future__ import annotations

import html
import os
import uuid
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlencode
from typing import Any

import requests
import streamlit as st

API_BASE_URL = os.getenv("RCA_API_BASE_URL", "http://localhost:8000").rstrip("/")
PAGE_SIZE = 50


st.set_page_config(
    page_title="RCA Console",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def main() -> None:
    st.title("RCA Console")
    st.caption("Incident triage, RCA evidence, hybrid RAG, and operator-ready analysis.")

    incident_id = current_incident_id()
    if current_view() == "incident-detail" and incident_id:
        incident_detail_page(incident_id)
        return

    page = st.sidebar.selectbox(
        "View",
        [
            "Incidents",
            "Events",
            "Copilot",
            "Knowledge",
            "Admin",
        ],
    )
    with st.sidebar.expander("API", expanded=False):
        st.text_input("Base URL", value=API_BASE_URL, key="api_base_url")
        health = safe_api_get("/health")
        st.caption((health or {}).get("phase", "unavailable"))

    if page == "Incidents":
        incidents()
    elif page == "Events":
        events()
    elif page == "Copilot":
        copilot()
    elif page == "Knowledge":
        knowledge()
    elif page == "Admin":
        admin()


def incidents() -> None:
    st.subheader("Incidents")
    filters = _incident_filters()
    page_key = "incident_page"
    _reset_page_on_filter_change("incident_filters", page_key, filters)
    if st.button("Search Incidents", type="primary"):
        st.session_state[page_key] = 1
    params = {key: value for key, value in filters.items() if value}
    params["page"] = st.session_state.get(page_key, 1)
    params["page_size"] = PAGE_SIZE
    data = api_get("/incidents/search", params)
    render_incident_list(data.get("items", []))
    render_pagination(data, page_key)


def events() -> None:
    st.subheader("Events")
    filters = _event_filters()
    page_key = "event_page"
    _reset_page_on_filter_change("event_filters", page_key, filters)
    if st.button("Search Events", type="primary"):
        st.session_state[page_key] = 1
    params = {key: value for key, value in filters.items() if value}
    params["page"] = st.session_state.get(page_key, 1)
    params["page_size"] = PAGE_SIZE
    data = api_get("/events/search", params)
    st.dataframe(_compact_event_rows(data.get("items", [])), use_container_width=True, hide_index=True)
    render_pagination(data, page_key)


def incident_detail_page(incident_id: str) -> None:
    result = api_get(f"/rca/{incident_id}")
    report = safe_api_get(f"/agents/reports/{incident_id}")
    graph = safe_api_get(f"/incidents/{incident_id}/graph")

    st.markdown(f"[Back to Incidents]({_app_url()})")
    st.subheader(result.get("summary", incident_id))
    cols = st.columns(4)
    cols[0].metric("Service", result.get("service", "unknown"))
    cols[1].metric("Env", result.get("env", "unknown"))
    cols[2].metric("Severity", result.get("severity", "unknown"))
    cols[3].metric("Confidence", f"{result.get('confidence', 0):.2f}")

    overview, timeline, evidence, graph_tab, report_tab, postmortem_tab, raw = st.tabs(
        ["Overview", "Timeline", "Evidence", "Graph", "Report", "Postmortem", "Raw JSON"]
    )
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

    with graph_tab:
        if not graph:
            st.info("Graph is unavailable for this incident.")
        else:
            left, right = st.columns(2)
            with left:
                st.markdown("#### Nodes")
                st.dataframe(graph.get("nodes", []), use_container_width=True, hide_index=True)
            with right:
                st.markdown("#### Relationships")
                st.dataframe(graph.get("relationships", []), use_container_width=True, hide_index=True)

    with report_tab:
        if not report:
            st.info("Agent report is unavailable for this incident.")
        else:
            st.info(report.get("notification_draft", ""))
            findings, runbook_tab, followups = st.tabs(["Findings", "Runbooks", "Follow-ups"])
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

    with postmortem_tab:
        render_postmortem_panel(incident_id)

    with raw:
        raw_tabs = st.tabs(["RCA Result", "Agent Report", "Graph"])
        with raw_tabs[0]:
            st.json(result)
        with raw_tabs[1]:
            st.json(report or {})
        with raw_tabs[2]:
            st.json(graph or {})


def knowledge() -> None:
    st.subheader("Knowledge")
    runbooks()


def runbooks() -> None:
    items = api_get("/runbooks").get("items", [])
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
    ask, stream = st.columns([1, 1])
    if ask.button("Ask Copilot", type="primary"):
        payload = {"question": question, "incident_id": incident_id or None, "limit": 8, "mode": mode}
        response = api_post("/copilot/chat", payload)
        st.session_state["last_copilot_response"] = response
        render_copilot_response(response)
    if stream.button("Ask Copilot (Stream)"):
        payload = {"question": question, "incident_id": incident_id or None, "limit": 8, "mode": "deep"}
        try:
            response = api_post_stream("/copilot/chat/stream", payload)
        except requests.RequestException:
            response = api_post("/copilot/chat", payload)
        st.session_state["last_copilot_response"] = response
        render_copilot_response(response)

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


def render_postmortem_panel(incident_id: str) -> None:
    draft_state_key = f"postmortem_draft_{incident_id}"
    cols = st.columns([1, 1, 4])
    if cols[0].button("Generate Draft", type="primary", key=f"generate_postmortem_{incident_id}"):
        draft = api_get(f"/incidents/{incident_id}/postmortem-draft")
        st.session_state[draft_state_key] = draft
    if cols[1].button("Promote to Historical Incident", key=f"promote_postmortem_{incident_id}"):
        promoted = api_post(f"/incidents/{incident_id}/promote-historical", {})
        st.success(f"Promoted: {promoted.get('historical_incident_id')}")
    draft = st.session_state.get(draft_state_key)
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


def rag_evaluation(show_header: bool = True) -> None:
    if show_header:
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


def knowledge_search() -> None:
    st.subheader("Knowledge Search")
    incident_id = st.text_input("Incident ID (optional)", value=selected_incident_id(), key="admin_incident_id")
    query = st.text_input("Search query", value="application exception latency", key="admin_knowledge_query")
    if st.button("Search Knowledge", key="admin_knowledge_search"):
        matches = api_get("/knowledge/search", {"q": query, "incident_id": incident_id or None, "limit": 10})
        st.caption(f"Intent: {matches.get('intent', 'unknown')}")
        st.dataframe(_compact_match_rows(matches.get("items", [])), use_container_width=True, hide_index=True)


def admin() -> None:
    st.subheader("Admin")
    evaluation_tab, search_tab, storage_tab = st.tabs(["RAG Evaluation", "Knowledge Search", "Storage Health"])
    with evaluation_tab:
        rag_evaluation(show_header=False)
    with search_tab:
        knowledge_search()
    with storage_tab:
        storage_health()


def selected_incident_id() -> str:
    return current_incident_id()


def current_view() -> str:
    return str(st.query_params.get("view", ""))


def current_incident_id() -> str:
    return str(st.query_params.get("incident_id", ""))


def _app_url(params: dict[str, str] | None = None) -> str:
    if not params:
        return "./"
    return f"./?{urlencode(params)}"


def _incident_detail_url(incident_id: str) -> str:
    return _app_url({"view": "incident-detail", "incident_id": incident_id})


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


def api_post_stream(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(f"{api_base()}{path}", json=payload, timeout=30, stream=True)
    response.raise_for_status()
    metadata: dict[str, Any] = {}
    answer_chunks: list[str] = []
    current_event = ""
    for raw_line in response.iter_lines(decode_unicode=True):
        if not raw_line:
            current_event = ""
            continue
        if raw_line.startswith("event:"):
            current_event = raw_line.replace("event:", "", 1).strip()
            continue
        if not raw_line.startswith("data:"):
            continue
        data = raw_line.replace("data:", "", 1).strip()
        if current_event == "metadata":
            import json

            metadata = json.loads(data)
        elif current_event == "answer":
            answer_chunks.append(data)
    metadata["answer"] = "\n".join(answer_chunks)
    return metadata


def render_copilot_response(response: dict[str, Any]) -> None:
    cols = st.columns(4)
    cols[0].metric("Confidence", f"{response.get('confidence', 0):.2f}")
    cols[1].metric("Path", response.get("response_path", "unknown"))
    cols[2].metric("Latency", f"{response.get('latency_ms', 0)} ms")
    cols[3].metric("Cache", "hit" if response.get("cache_hit") else "miss")
    if response.get("root_cause_summary"):
        st.info(response.get("root_cause_summary"))
    st.text_area("Answer", value=response.get("answer", ""), height=280)
    if response.get("missing_evidence"):
        st.markdown("#### Missing Evidence")
        for item in response.get("missing_evidence", []):
            st.write(f"- {item}")
    if response.get("recommended_manual_runbooks"):
        st.markdown("#### Manual Runbooks")
        for item in response.get("recommended_manual_runbooks", []):
            st.write(f"- {item}")
    if response.get("confidence_rationale"):
        st.caption(response.get("confidence_rationale"))
    st.markdown("#### Verification")
    st.json(response.get("verification", {}))
    st.markdown("#### Citations")
    st.dataframe(response.get("citations", []), use_container_width=True, hide_index=True)
    st.markdown("#### Matches")
    st.dataframe(_compact_match_rows(response.get("matches", [])), use_container_width=True, hide_index=True)
    st.markdown("#### Suggested Follow-ups")
    for item in response.get("suggested_followups", []):
        st.write(f"- {item}")


def render_incident_list(items: list[dict[str, Any]]) -> None:
    rows = _compact_incident_rows(items)
    if not rows:
        st.info("No incidents found.")
        return
    header = st.columns([2.1, 1.3, 1.0, 1.8, 3.8])
    header[0].markdown("**Incident**")
    header[1].markdown("**Service**")
    header[2].markdown("**Severity**")
    header[3].markdown("**Updated**")
    header[4].markdown("**Summary**")
    for row in rows:
        cols = st.columns([2.1, 1.3, 1.0, 1.8, 3.8])
        incident_id = str(row.get("incident_id", ""))
        detail_url = _incident_detail_url(incident_id)
        cols[0].markdown(
            f'<a href="{html.escape(detail_url)}" target="_blank" rel="noopener noreferrer">'
            f"{html.escape(incident_id)}</a>",
            unsafe_allow_html=True,
        )
        cols[1].write(row.get("service", ""))
        cols[2].write(row.get("severity", ""))
        cols[3].write(str(row.get("updated_at", "")))
        cols[4].write(row.get("summary", ""))


def _incident_filters() -> dict[str, Any]:
    cols = st.columns([2, 1, 1])
    filters = {
        "q": cols[0].text_input("Search", placeholder="incident id, summary"),
        "service": cols[1].text_input("Service"),
        "severity": cols[2].selectbox("Severity", ["", "critical", "error", "warning", "info"]),
    }
    start, end = _time_range_inputs("Updated", key_prefix="incident_updated")
    filters.update({"updated_from": start, "updated_to": end})
    return filters


def _event_filters() -> dict[str, Any]:
    cols = st.columns([2, 1, 1, 1, 1])
    filters = {
        "q": cols[0].text_input("Search", placeholder="error code, span, metric, summary"),
        "service": cols[1].text_input("Service"),
        "severity": cols[2].selectbox("Severity", ["", "critical", "error", "warning", "info"]),
        "event_type": cols[3].selectbox(
            "Type",
            ["", "log.error_pattern", "metric.anomaly", "trace.slow_span", "trace.error", "deploy.change"],
        ),
        "trace_id": cols[4].text_input("Trace ID"),
    }
    start, end = _time_range_inputs("Event", key_prefix="event_time")
    filters.update({"event_time_from": start, "event_time_to": end})
    return filters


def _time_range_inputs(label: str, *, key_prefix: str) -> tuple[str | None, str | None]:
    cols = st.columns([1.4, 1, 1.4, 1])
    start_date = cols[0].date_input(f"{label} Start Date", value=None, key=f"{key_prefix}_start_date")
    start_time = cols[1].time_input(
        f"{label} Start Time",
        value=time(0, 0, 0),
        step=timedelta(minutes=1),
        key=f"{key_prefix}_start_time",
    )
    end_date = cols[2].date_input(f"{label} End Date", value=None, key=f"{key_prefix}_end_date")
    end_time = cols[3].time_input(
        f"{label} End Time",
        value=time(23, 59, 0),
        step=timedelta(minutes=1),
        key=f"{key_prefix}_end_time",
    )
    return _utc_iso(start_date, start_time), _utc_iso(end_date, end_time, end_of_minute=True)


def _utc_iso(selected_date: date | None, selected_time: time | None, *, end_of_minute: bool = False) -> str | None:
    if not selected_date:
        return None
    selected_time = selected_time or time(0, 0, 0)
    value = datetime.combine(selected_date, selected_time, tzinfo=timezone.utc)
    if end_of_minute:
        value = value.replace(second=59)
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _reset_page_on_filter_change(signature_key: str, page_key: str, filters: dict[str, Any]) -> None:
    signature = tuple(sorted((key, str(value)) for key, value in filters.items()))
    previous = st.session_state.get(signature_key)
    if previous is not None and previous != signature:
        st.session_state[page_key] = 1
    st.session_state[signature_key] = signature


def render_pagination(data: dict[str, Any], page_key: str) -> None:
    page = int(data.get("page") or st.session_state.get(page_key, 1) or 1)
    total_pages = int(data.get("total_pages") or 0)
    total = int(data.get("total") or 0)
    if total_pages and page > total_pages:
        st.session_state[page_key] = total_pages
        st.rerun()

    display_page = page if total_pages else 0
    prev_col, page_col, next_col, total_col = st.columns([1, 1.4, 1, 4])
    if prev_col.button("Previous", disabled=not data.get("has_prev"), key=f"{page_key}_prev"):
        st.session_state[page_key] = max(page - 1, 1)
        st.rerun()
    page_col.markdown(f"**Page {display_page} / {total_pages}**")
    if next_col.button("Next", disabled=not data.get("has_next"), key=f"{page_key}_next"):
        st.session_state[page_key] = page + 1
        st.rerun()
    total_col.caption(f"{total} total")


def _compact_incident_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "incident_id": item.get("incident_id"),
            "service": item.get("service"),
            "env": item.get("env"),
            "severity": item.get("severity"),
            "score": item.get("score"),
            "has_rca": item.get("has_rca"),
            "updated_at": item.get("_updated_at") or item.get("updated_at"),
            "summary": item.get("summary"),
        }
        for item in items
    ]


def _compact_event_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "event_time": item.get("event_time"),
            "event_type": item.get("event_type"),
            "service": item.get("service"),
            "env": item.get("env"),
            "severity": item.get("severity"),
            "trace_id": item.get("trace_id"),
            "summary": item.get("summary"),
            "event_id": item.get("event_id"),
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


def _compact_match_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in items:
        breakdown = item.get("score_breakdown") or {}
        rows.append(
            {
                "source": item.get("source"),
                "title": item.get("title"),
                "score": item.get("score"),
                "semantic": breakdown.get("semantic_score"),
                "keyword": breakdown.get("keyword_score"),
                "source_priority": breakdown.get("source_priority_score"),
                "recall": ", ".join(item.get("recall_sources") or []),
                "ref_id": item.get("ref_id"),
            }
        )
    return rows


if __name__ == "__main__":
    main()
