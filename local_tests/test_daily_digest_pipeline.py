"""Check aggregation and concurrency independently of model quality."""
import copy
import json
from threading import Barrier

from cs329z_hw1 import adapters


def email(number, thread):
    return {"id": str(number), "thread_id": thread, "date": f"2001-06-01T0{number}:00:00Z",
            "subject": f"Topic {number}", "body": f"Evidence {number}", "to": [], "from": "a"}


def test_filter_group_promote_and_preserve_evidence(monkeypatch):
    messages = [email(2, "same"), email(1, "same"), email(3, "same"),
                email(4, "other"), email(5, ""), email(6, "")]
    before = copy.deepcopy(messages)
    categories = {"1": "urgent", "2": "normal", "3": "ignore", "4": "unknown",
                  "5": "normal", "6": "normal"}
    barrier = Barrier(len(messages))

    def classify(message, lm):
        barrier.wait(timeout=5)  # Serial classification cannot complete this test.
        return {"category": categories[message["id"]], "reason": "Reason"}

    monkeypatch.setattr(adapters, "run_priority", classify)
    calls = []
    long_reply = "word " * 400

    def lm(prompt):
        calls.append(prompt)
        return long_reply

    assert adapters.run_daily_digest(messages, lm) == long_reply  # No post-hoc truncation.
    assert len(calls) == 1
    assert [m["role"] for m in calls[0]] == ["system", "user"]
    groups = json.loads(calls[0][1]["content"])
    assert len(groups["urgent_emails"]) == 1
    urgent = groups["urgent_emails"][0]["emails"]
    assert [item["email"]["id"] for item in urgent] == ["1", "2"]
    assert len(groups["normal_emails"]) == 3
    unknown = groups["normal_emails"][0]["emails"][0]
    assert unknown["category"] == "normal"
    assert "Evidence 3" not in calls[0][1]["content"]
    assert messages == before


def test_empty_and_all_ignore_skip_generation(monkeypatch):
    calls = []

    def lm(prompt):
        calls.append(prompt)
        raise AssertionError("No summary call should be made")

    assert adapters.run_daily_digest([], lm).strip()
    monkeypatch.setattr(adapters, "run_priority", lambda email, lm: {"category": "ignore"})
    assert adapters.run_daily_digest([email(1, "one")], lm).strip()
    assert calls == []
