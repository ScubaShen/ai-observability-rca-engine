from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass


TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_.-]+")


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
