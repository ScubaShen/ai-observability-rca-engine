from __future__ import annotations

from rca_engine.models import KnowledgeMatch
from rca_engine.rag.llm import LLMProvider


class LLMReranker:
    """Optional deep-path reranker.

    The production path can attach a model-backed implementation here. The
    default behavior is conservative: if the provider is unavailable or the
    model output cannot be trusted, preserve deterministic ranking.
    """

    def __init__(self, provider: LLMProvider, enabled: bool = False) -> None:
        self.provider = provider
        self.enabled = enabled

    def rerank(self, question: str, matches: list[KnowledgeMatch], top_k: int = 8) -> list[KnowledgeMatch]:
        if not self.enabled or not self.provider.available() or len(matches) < 2:
            return matches
        result = self.provider.complete(
            question=(
                "Rerank the evidence for this RCA question. Return the best supporting "
                f"citation numbers only. Question: {question}"
            ),
            context=matches[:top_k],
        )
        if not result or not result.structured:
            return matches
        order = result.structured.get("supporting_citations") or []
        if not isinstance(order, list):
            return matches
        ordered: list[KnowledgeMatch] = []
        seen: set[int] = set()
        for raw_index in order:
            try:
                index = int(raw_index) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(matches) and index not in seen:
                seen.add(index)
                ordered.append(
                    matches[index].model_copy(
                        update={
                            "recall_sources": sorted(set([*matches[index].recall_sources, "llm_rerank"]))
                        }
                    )
                )
        ordered.extend(match for index, match in enumerate(matches) if index not in seen)
        return ordered
