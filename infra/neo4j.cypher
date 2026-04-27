create constraint incident_id_unique if not exists
for (i:Incident)
require i.incident_id is unique;

create constraint service_name_env_unique if not exists
for (s:Service)
require (s.name, s.env) is unique;

create constraint event_id_unique if not exists
for (e:Event)
require e.event_id is unique;

create constraint root_cause_id_unique if not exists
for (r:RootCause)
require r.hypothesis_id is unique;

create constraint graph_node_id_unique if not exists
for (n:GraphNode)
require n.id is unique;

create constraint dependency_name_unique if not exists
for (d:Dependency)
require d.name is unique;

// Relationship types used by the RCA engine:
// (:Incident)-[:AFFECTS]->(:Service)
// (:Incident)-[:HAS_EVIDENCE]->(:Event)
// (:Incident)-[:HAS_ROOT_CAUSE]->(:RootCause)
// (:GraphNode)-[:CAUSED_BY|CORRELATED_WITH]->(:GraphNode)
// (:Service)-[:DEPENDS_ON]->(:Dependency)
