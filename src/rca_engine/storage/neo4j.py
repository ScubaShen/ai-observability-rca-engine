from __future__ import annotations

from typing import Any

from rca_engine.models import RCAResult

try:
    from neo4j import GraphDatabase
except ImportError:  # pragma: no cover - only relevant before container deps are installed.
    GraphDatabase = None


class Neo4jGraphStore:
    def __init__(self, uri: str, user: str, password: str) -> None:
        self.uri = uri
        self.user = user
        self.password = password

    def available(self) -> bool:
        return bool(self.uri and self.user and self.password and GraphDatabase is not None)

    def health(self) -> dict[str, object]:
        if not self.available():
            return {"status": "unavailable", "reason": "NEO4J_URI/user/password or neo4j driver is not configured"}
        try:
            with self._driver() as driver:
                driver.verify_connectivity()
            return {"status": "ok"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "reason": str(exc)}

    def sync_rca_result(self, result: RCAResult) -> None:
        if not self.available():
            raise RuntimeError("Neo4j is not configured")

        payload = result.model_dump(mode="json")
        with self._driver() as driver:
            with driver.session() as session:
                session.execute_write(_ensure_constraints_tx)
                session.execute_write(_sync_result_tx, payload)

    def get_incident_graph(self, incident_id: str) -> dict[str, Any]:
        if not self.available():
            raise RuntimeError("Neo4j is not configured")

        with self._driver() as driver:
            with driver.session() as session:
                return session.execute_read(_incident_graph_tx, incident_id)

    def _driver(self):
        if GraphDatabase is None:
            raise RuntimeError("neo4j driver is not installed")
        return GraphDatabase.driver(self.uri, auth=(self.user, self.password))


def _sync_result_tx(tx, result: dict[str, Any]) -> None:
    tx.run(
        """
        merge (i:Incident {incident_id: $incident_id})
        set i.service = $service,
            i.env = $env,
            i.severity = $severity,
            i.summary = $summary,
            i.confidence = $confidence,
            i.generated_at = $generated_at
        merge (s:Service {name: $service, env: $env})
        merge (i)-[:AFFECTS]->(s)
        """,
        **{
            "incident_id": result["incident_id"],
            "service": result["service"],
            "env": result["env"],
            "severity": result["severity"],
            "summary": result["summary"],
            "confidence": result["confidence"],
            "generated_at": result["generated_at"],
        },
    )

    for item in result.get("timeline", []):
        tx.run(
            """
            match (i:Incident {incident_id: $incident_id})
            merge (e:Event {event_id: $event_id})
            set e.event_type = $event_type,
                e.event_time = $event_time,
                e.service = $service,
                e.severity = $severity,
                e.summary = $summary
            merge (i)-[:HAS_EVIDENCE]->(e)
            """,
            incident_id=result["incident_id"],
            event_id=item["event_id"],
            event_type=item["event_type"],
            event_time=item["event_time"],
            service=item["service"],
            severity=item["severity"],
            summary=item["summary"],
        )

    for root in result.get("root_causes", []):
        tx.run(
            """
            match (i:Incident {incident_id: $incident_id})
            merge (r:RootCause {hypothesis_id: $hypothesis_id})
            set r.title = $title,
                r.category = $category,
                r.confidence = $confidence,
                r.description = $description
            merge (i)-[:HAS_ROOT_CAUSE]->(r)
            """,
            incident_id=result["incident_id"],
            hypothesis_id=root["hypothesis_id"],
            title=root["title"],
            category=root["category"],
            confidence=root["confidence"],
            description=root["description"],
        )

    for link in result.get("causal_links", []):
        tx.run(
            """
            match (i:Incident {incident_id: $incident_id})
            merge (source:GraphNode {id: $source_id})
            merge (target:GraphNode {id: $target_id})
            merge (i)-[:HAS_GRAPH_NODE]->(source)
            merge (i)-[:HAS_GRAPH_NODE]->(target)
            merge (source)-[rel:CAUSED_BY {relation: $relation}]->(target)
            set rel.confidence = $confidence,
                rel.reason = $reason,
                rel.link_id = $link_id
            """,
            incident_id=result["incident_id"],
            source_id=link["source_id"],
            target_id=link["target_id"],
            relation=link["relation"],
            confidence=link["confidence"],
            reason=link["reason"],
            link_id=link.get("link_id"),
        )

    for insight in result.get("dependency_insights", []):
        tx.run(
            """
            merge (s:Service {name: $source_service, env: $env})
            merge (d:Dependency {name: $target})
            merge (s)-[rel:DEPENDS_ON]->(d)
            set rel.relation = $relation,
                rel.is_suspect = $is_suspect,
                rel.summary = $summary
            """,
            source_service=insight["source_service"],
            env=result["env"],
            target=insight["target"],
            relation=insight["relation"],
            is_suspect=insight["is_suspect"],
            summary=insight["summary"],
        )


def _ensure_constraints_tx(tx) -> None:
    tx.run(
        """
        create constraint incident_id_unique if not exists
        for (i:Incident)
        require i.incident_id is unique
        """
    )
    tx.run(
        """
        create constraint event_id_unique if not exists
        for (e:Event)
        require e.event_id is unique
        """
    )
    tx.run(
        """
        create constraint root_cause_id_unique if not exists
        for (r:RootCause)
        require r.hypothesis_id is unique
        """
    )
    tx.run(
        """
        create constraint graph_node_id_unique if not exists
        for (n:GraphNode)
        require n.id is unique
        """
    )


def _incident_graph_tx(tx, incident_id: str) -> dict[str, Any]:
    direct_rows = tx.run(
        """
        match (i:Incident {incident_id: $incident_id})-[r]-(n)
        return i, r, n
        limit 500
        """,
        incident_id=incident_id,
    )
    nodes: dict[str, dict[str, Any]] = {}
    relationships: list[dict[str, Any]] = []
    for row in direct_rows:
        incident = dict(row["i"])
        node = dict(row["n"])
        rel = row["r"]
        incident_id_value = incident.get("incident_id", incident_id)
        node_id = node.get("event_id") or node.get("hypothesis_id") or node.get("name") or str(row["n"].id)
        nodes[incident_id_value] = {"id": incident_id_value, "labels": ["Incident"], "properties": incident}
        nodes[node_id] = {
            "id": node_id,
            "labels": list(row["n"].labels),
            "properties": node,
        }
        relationships.append(
            {
                "type": rel.type,
                "start": incident_id_value,
                "end": node_id,
                "properties": dict(rel),
            }
        )
    causal_rows = tx.run(
        """
        match (i:Incident {incident_id: $incident_id})
        match (i)-[:HAS_GRAPH_NODE|HAS_EVIDENCE]->(a)-[r]->(b)<-[:HAS_GRAPH_NODE|HAS_EVIDENCE]-(i)
        return a, r, b
        limit 500
        """,
        incident_id=incident_id,
    )
    for row in causal_rows:
        start_node = dict(row["a"])
        end_node = dict(row["b"])
        rel = row["r"]
        start_id = start_node.get("event_id") or start_node.get("id") or str(row["a"].id)
        end_id = end_node.get("event_id") or end_node.get("id") or str(row["b"].id)
        nodes[start_id] = {
            "id": start_id,
            "labels": list(row["a"].labels),
            "properties": start_node,
        }
        nodes[end_id] = {
            "id": end_id,
            "labels": list(row["b"].labels),
            "properties": end_node,
        }
        relationships.append(
            {
                "type": rel.type,
                "start": start_id,
                "end": end_id,
                "properties": dict(rel),
            }
        )
    return {"incident_id": incident_id, "nodes": list(nodes.values()), "relationships": relationships}
