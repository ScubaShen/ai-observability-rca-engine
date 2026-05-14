from __future__ import annotations

import hashlib
import logging
import math
import re
from dataclasses import dataclass
from typing import Protocol

import requests


logger = logging.getLogger(__name__)


TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_.-]+")


class EmbeddingProvider(Protocol):
    model_name: str

    def embed(self, text: str) -> list[float]: ...


@dataclass(frozen=True)
class HashEmbeddingProvider:
    """Deterministic offline embedding provider used until a remote model is configured."""

    dimensions: int = 1536
    model_name: str = "hash-v1"

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in _tokens(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [round(value / norm, 6) for value in vector]


@dataclass(frozen=True)
class OpenAIEmbeddingProvider:
    api_key: str
    api_url: str = "https://api.openai.com/v1/embeddings"
    model_name: str = "text-embedding-3-small"
    dimensions: int = 1536
    timeout_seconds: float = 8.0
    fallback_provider: HashEmbeddingProvider | None = None

    def embed(self, text: str) -> list[float]:
        payload: dict[str, object] = {
            "model": self.model_name,
            "input": text,
        }
        if self.dimensions:
            payload["dimensions"] = self.dimensions
        try:
            response = requests.post(
                self.api_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            values = ((data.get("data") or [{}])[0].get("embedding") or [])
            if values:
                return [float(value) for value in values]
        except Exception as exc:  # noqa: BLE001
            if self.fallback_provider:
                logger.warning("Embedding provider failed; falling back to hash-v1: %s", exc)
                return self.fallback_provider.embed(text)
            raise
        if self.fallback_provider:
            return self.fallback_provider.embed(text)
        return []


def build_embedding_provider(
    *,
    provider: str = "hash",
    api_url: str = "",
    api_key: str = "",
    model: str = "text-embedding-3-small",
    dimensions: int = 1536,
    timeout_seconds: float = 8.0,
) -> EmbeddingProvider:
    fallback = HashEmbeddingProvider(dimensions=dimensions)
    if provider.lower() == "openai" and api_key:
        return OpenAIEmbeddingProvider(
            api_key=api_key,
            api_url=api_url or "https://api.openai.com/v1/embeddings",
            model_name=model or "text-embedding-3-small",
            dimensions=dimensions,
            timeout_seconds=timeout_seconds,
            fallback_provider=fallback,
        )
    return fallback


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return round(numerator / (left_norm * right_norm), 4)


def text_for_embedding(*parts: object) -> str:
    return " ".join(str(part) for part in parts if part)


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text) if len(token) > 1]
