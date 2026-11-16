"""Structural Markdown chunks with original source positions and bounded reads."""
import re

from cs329z_hw1.pipelines.bm25 import BM25Index
from cs329z_hw1.tokenizer import tokenize
from cs329z_hw1.tokens import count_tokens


def category(doc_id):
    groups = {
        'hr': ('people', 'parental', 'pto', 'benefits', 'employee', 'remote', 'onboarding'),
        'finance': ('expense', 'finance'),
        'engineering': ('engineering', 'firmware', 'architecture', 'oncall', 'it-security'),
        'product': ('gridlens', 'project'),
    }
    return next((name for name, prefixes in groups.items() if doc_id.startswith(prefixes)), 'general')


class DocumentIndex:
    def __init__(self, docs):
        self.docs = {d['doc_id']: dict(d) for d in docs}
        self.chunks = []
        for doc in docs:
            lines = doc['text'].splitlines(keepends=True)
            section = doc['title']
            start = offset = 0
            block = []

            def flush():
                if block:
                    self.chunks.append({'doc_id': doc['doc_id'], 'section': section,
                                        'offset': start, 'text': ''.join(block)})
                    block.clear()

            for line in lines:
                heading = re.match(r'^#{1,6}\s+(.+)', line)
                if heading:
                    flush()
                    section = heading.group(1).strip()
                if block and (sum(map(len, block)) + len(line) > 2000):
                    flush()
                if not block:
                    start = offset
                # Long paragraphs are split only in the retrieval index;
                # read() always preserves whole original lines.
                if len(line) > 2000:
                    flush()
                    for match in re.finditer(r'\S+(?:\s+|$)', line):
                        if block and sum(map(len, block)) + len(match.group()) > 2000:
                            flush()
                        if not block:
                            start = offset + match.start()
                        block.append(match.group())
                else:
                    block.append(line)
                offset += len(line)
                if not line.strip() and sum(map(len, block)) >= 800:
                    flush()
            flush()
        self.bm25 = BM25Index([c['text'] for c in self.chunks])

    def search(self, query, k=5):
        terms = set(tokenize(query))
        results = []
        if k <= 0:
            return results
        seen = set()
        ranked = self.bm25.search(query, len(self.chunks))
        # Reserve pointers to explicitly labelled update/memo documents when
        # their TITLE shares a query term. Do not infer newer facts or dates:
        # the model still needs to compare effective dates against the task.
        updates = []
        update_docs = set()
        for i, _ in ranked:
            doc = self.docs[self.chunks[i]['doc_id']]
            if (re.search(r'\b(announcement|memo|update)\b', doc['title'], re.I)
                    and terms.intersection(tokenize(doc['title']))
                    and doc['doc_id'] not in update_docs):
                updates.append((i, 0))
                update_docs.add(doc['doc_id'])
        order = ranked[:1] + updates[:2] + ranked[1:]
        visited_chunks = set()
        for i, _ in order:
            if i in visited_chunks:
                continue
            visited_chunks.add(i)
            chunk = self.chunks[i]
            doc = self.docs[chunk['doc_id']]
            text = doc['text']
            hit = next((m for m in re.finditer(r'[a-z0-9]+', chunk['text'].lower()) if m.group() in terms), None)
            anchor = chunk['offset'] + (hit.start() if hit else 0)
            # Quote a contiguous original passage around the matching term.
            begin = max(0, anchor - 100)
            if begin:
                boundary = re.search(r'\s', text[begin:anchor])
                begin = begin + boundary.end() if boundary else anchor
            end = min(len(text), begin + 600)
            if end < len(text):
                boundary = text.rfind(' ', anchor, end)
                if boundary > anchor:
                    end = boundary
            raw = text[begin:end]
            begin += len(raw) - len(raw.lstrip())
            snippet = raw.strip()
            end = begin + len(snippet)
            start_line = text.count('\n', 0, begin) + 1
            end_line = text.count('\n', 0, max(begin, end - 1)) + 1
            position = (doc['doc_id'], begin, end)
            if position in seen:
                continue
            seen.add(position)
            results.append({'doc_id': doc['doc_id'], 'title': doc['title'], 'snippet': snippet,
                            'document_kind': 'update_or_memo' if re.search(r'\b(announcement|memo|update)\b', doc['title'], re.I) else 'document',
                            'category': category(doc['doc_id']), 'section': chunk['section'],
                            'start_line': start_line, 'end_line': end_line})
            if len(results) >= k:
                break
        return results

    def read(self, doc_id, start_line=1):
        if doc_id not in self.docs:
            raise LookupError(f'Unknown document: {doc_id}')
        lines = self.docs[doc_id]['text'].splitlines()
        if not 1 <= start_line <= len(lines):
            raise ValueError('start_line outside document')
        chosen = []
        for line in lines[start_line - 1:]:
            candidate = '\n'.join(chosen + [line])
            if count_tokens(candidate) > 1500:
                break
            if chosen and count_tokens(candidate) > 800:
                break
            chosen.append(line)
            if count_tokens(candidate) >= 800:
                break
        if not chosen:
            raise ValueError('A single source line exceeds the 1500-token window')
        return {'doc_id': doc_id, 'start_line': start_line, 'end_line': start_line + len(chosen) - 1,
                'total_lines': len(lines), 'text': '\n'.join(chosen)}
