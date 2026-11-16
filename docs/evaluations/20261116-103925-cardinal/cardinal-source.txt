"""Bind fixed Cardinal schemas to lazy email workflows and future tools."""

import json
from threading import RLock

from cs329z_hw1 import data
from cs329z_hw1.cardinal import CARDINAL_TOOLS, cardinal_spec
from cs329z_hw1.pipelines.bm25 import BM25Index


_LOCK = RLock()
_ARCHIVES: dict = {}


def _archive(needs_index=False):
    # Key by source path so distinct archives never reuse another file's index.
    key = data.EMAILS_PATH.resolve()
    with _LOCK:
        if key not in _ARCHIVES:
            emails = data.load_emails()
            _ARCHIVES[key] = {"emails": emails, "by_id": {e["id"]: e for e in emails}, "index": None}
        archive = _ARCHIVES[key]
        if needs_index and archive["index"] is None:
            archive["index"] = BM25Index([data.email_text(e) for e in archive["emails"]])
        return archive


def _pending(name):
    def unavailable(**kwargs):
        raise NotImplementedError(f"{name} is registered but not implemented yet; it is completed in a later problem.")
    return cardinal_spec(name, "Not available yet; registered for a later problem. Do not call this tool.", unavailable)


def build_cardinal_tools(lm, config):
    """Construct specs without loading data or building an index."""
    aux_lm = config.aux_lm if config.aux_lm is not None else lm

    def search(query, k=5):
        archive = _archive(needs_index=True)
        return [archive["emails"][i] for i, _ in archive["index"].search(query, k)]

    def search_emails(query, k=5):
        return json.dumps([
            {"id": e["id"], "date": e["date"], "subject": e["subject"],
             "snippet": e["body"][:400], "snippet_truncated": len(e["body"]) > 400}
            for e in search(query, k)
        ], ensure_ascii=False)

    def read_email(email_id):
        email = _archive()["by_id"].get(email_id)
        if email is None:
            raise LookupError(f"Unknown email ID: {email_id}")
        return json.dumps(email, ensure_ascii=False)

    def email_qa(question):
        from cs329z_hw1.adapters import run_email_qa
        return json.dumps(run_email_qa(question, search, aux_lm), ensure_ascii=False)

    def daily_digest(date):
        from cs329z_hw1.adapters import run_daily_digest
        return run_daily_digest(data.emails_on(date), aux_lm)

    available = {
        "search_emails": cardinal_spec("search_emails", "Search the 2001 email archive by BM25 keywords. Returns JSON email IDs, dates, subjects and up to 400 body characters; use read_email for full evidence. No matches returns [].", search_emails),
        "read_email": cardinal_spec("read_email", "Read one complete archive email as JSON by its ID from search results; unknown IDs return a tool error.", read_email),
        "email_qa": cardinal_spec("email_qa", "Answer a factual question over the email archive with up to three retrieval hops. Returns JSON answer and supporting email IDs; null means no supported answer found.", email_qa),
        "daily_digest": cardinal_spec("daily_digest", "Generate an English digest for one UTC archive date YYYY-MM-DD. Classifies that day's emails concurrently, omits ignore mail and summarizes urgent threads first in at most 300 words.", daily_digest),
    }
    return [available[name] if name in available else _pending(name) for name in CARDINAL_TOOLS]


def supplement_tools(tools, config):
    """Explicit lists gain only configured interaction/memory tools, once."""
    result = list(tools)
    names = {tool.name for tool in result}
    required = (["ask_user"] if config.user is not None else [])
    if config.memory_dir is not None:
        required.extend(["remember", "recall"])
    for name in required:
        if name not in names:
            result.append(_pending(name))
            names.add(name)
    return result
