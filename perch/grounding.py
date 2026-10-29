"""Validator layer 2: a small grounding model checks each sentence against its cited records.

Default MiniCheck-RoBERTa-Large (MIT), on CPU in the request path. Called through
transformers directly, matching the MiniCheck package's inference code (GitHub
Liyan06/MiniCheck, commit b58b9fa, read 2026-10-28): input is
document + eos_token + claim, truncated at 512 tokens; softmax over two labels,
index 1 = supported; documents split into sentence chunks of about 400 tokens and
the claim takes its best chunk; supported when the probability exceeds 0.5.
An unsupported sentence is flagged, not regenerated (SPEC section 8).
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

DEFAULT_MODEL = "lytang/MiniCheck-RoBERTa-Large"
THRESHOLD = 0.5
CHUNK_TOKENS = 400


@dataclass
class SentenceCheck:
    sentence: str
    support: float
    supported: bool


def split_sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


class Grounder(ABC):
    name: str

    @abstractmethod
    def support(self, document: str, claims: list[str]) -> list[float]:
        """Probability each claim is supported by the document."""

    def check(self, document: str, text: str) -> list[SentenceCheck]:
        sents = split_sentences(text)
        probs = self.support(document, sents) if sents else []
        return [SentenceCheck(s, p, p > THRESHOLD) for s, p in zip(sents, probs, strict=True)]


class FakeGrounder(Grounder):
    """Share of a claim's content words found in the document."""

    name = "fake-overlap"

    def support(self, document: str, claims: list[str]) -> list[float]:
        doc = set(re.findall(r"[a-z]{4,}", document.lower()))
        out = []
        for c in claims:
            words = set(re.findall(r"[a-z]{4,}", c.lower()))
            out.append(len(words & doc) / len(words) if words else 1.0)
        return out


class MiniCheckGrounder(Grounder):
    def __init__(self, model: str = DEFAULT_MODEL, device: str = "cpu", batch_size: int = 8
                 ) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(model, use_fast=True)
        self.model = AutoModelForSequenceClassification.from_pretrained(model, num_labels=2)
        self.model.to(device).eval()
        self.device = device
        self.batch_size = batch_size
        self.name = model

    def chunks(self, document: str) -> list[str]:
        out, cur, n = [], [], 0
        for s in split_sentences(document.replace("\n", " ")) or [document]:
            k = len(self.tok(s, add_special_tokens=False)["input_ids"])
            if cur and n + k > CHUNK_TOKENS:
                out.append(" ".join(cur))
                cur, n = [], 0
            cur.append(s)
            n += k
        if cur:
            out.append(" ".join(cur))
        return out

    def support(self, document: str, claims: list[str]) -> list[float]:
        chunks = self.chunks(document)
        pairs = [(i, c + self.tok.eos_token + claim) for i, claim in enumerate(claims)
                 for c in chunks]
        best = [0.0] * len(claims)
        with self.torch.no_grad():
            for start in range(0, len(pairs), self.batch_size):
                batch = pairs[start:start + self.batch_size]
                enc = self.tok([t for _, t in batch], max_length=512, truncation=True,
                               padding=True, return_tensors="pt").to(self.device)
                probs = self.torch.softmax(self.model(**enc).logits, dim=-1)[:, 1].tolist()
                for (i, _), p in zip(batch, probs, strict=True):
                    best[i] = max(best[i], float(p))
        return best
