"""BM25 ranking over term postings, without scanning unrelated documents."""

from collections import Counter, defaultdict
import heapq
import math

from cs329z_hw1.tokenizer import tokenize


class BM25Index:
    """Build once, then share read-only statistics across independent searches."""

    K1 = 1.5
    B = 0.75

    def __init__(self, docs: list[str]):
        self.postings: dict[str, list[tuple[int, int]]] = {}
        self.doc_lengths: list[int] = []
        for doc_id, text in enumerate(docs):
            tokens = tokenize(text)
            self.doc_lengths.append(len(tokens))
            for term, frequency in Counter(tokens).items():
                self.postings.setdefault(term, []).append((doc_id, frequency))

        self.num_docs = len(self.doc_lengths)
        self.avgdl = sum(self.doc_lengths) / self.num_docs if self.num_docs else 0.0
        self.idf = {
            term: math.log(1 + (self.num_docs - len(entries) + 0.5) / (len(entries) + 0.5))
            for term, entries in self.postings.items()
        }

    def search(self, query: str, k: int) -> list[tuple[int, float]]:
        if k <= 0 or self.avgdl == 0:
            return []

        scores: dict[int, float] = defaultdict(float)
        # Stable term order also makes floating-point accumulation reproducible.
        for term in sorted(set(tokenize(query))):
            entries = self.postings.get(term)
            if not entries:
                continue
            idf = self.idf[term]
            for doc_id, frequency in entries:
                norm = self.K1 * (1 - self.B + self.B * self.doc_lengths[doc_id] / self.avgdl)
                scores[doc_id] += idf * frequency * (self.K1 + 1) / (frequency + norm)

        return heapq.nsmallest(k, scores.items(), key=lambda pair: (-pair[1], pair[0]))
