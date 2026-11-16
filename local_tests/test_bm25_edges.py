"""Boundary statistics and concurrent reuse beyond the course score checks."""
from concurrent.futures import ThreadPoolExecutor
import math

import pytest

from cs329z_hw1.adapters import run_bm25_build, run_bm25_search


@pytest.mark.parametrize('docs', [[], ['', '   ', '?!']])
def test_no_tokens_in_corpus(docs):
    assert run_bm25_search(run_bm25_build(docs), 'apple', 10) == []


@pytest.mark.parametrize('k', [0, -1])
def test_nonpositive_k(k):
    assert run_bm25_search(run_bm25_build(['apple']), 'apple', k) == []


def test_empty_documents_affect_idf_and_average_length():
    docs = ['', 'apple', '']
    index = run_bm25_build(docs)
    expected = math.log(1 + 2.5 / 1.5) * 2.5 / (1 + 1.5 * (0.25 + 0.75 * 3))
    result = run_bm25_search(index, 'apple', 10)
    assert result[0][0] == 1
    assert result[0][1] == pytest.approx(expected, abs=1e-6)
    assert docs == ['', 'apple', '']


def test_queries_can_share_index_without_accumulating_old_scores():
    index = run_bm25_build(['apple banana', 'banana', '', 'apple apple'])
    queries = ['apple', 'banana', 'apple banana', 'absent'] * 8
    expected = [run_bm25_search(index, query, 10) for query in queries]
    with ThreadPoolExecutor(max_workers=8) as pool:
        actual = list(pool.map(lambda query: run_bm25_search(index, query, 10), queries))
    assert actual == expected
