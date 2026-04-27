from __future__ import annotations

from rca_engine.config import Settings
from rca_engine.storage.composite import CompositeStorage
from rca_engine.storage.jsonl import JsonlStore
from rca_engine.storage.neo4j import Neo4jGraphStore
from rca_engine.storage.postgres import PostgresStore


def build_storage(settings: Settings) -> CompositeStorage:
    jsonl = JsonlStore(settings.output_dir)
    postgres = PostgresStore(settings.postgres_dsn) if settings.postgres_dsn else None
    graph = (
        Neo4jGraphStore(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
        )
        if settings.neo4j_uri
        else None
    )
    return CompositeStorage(jsonl=jsonl, postgres=postgres, graph=graph)
