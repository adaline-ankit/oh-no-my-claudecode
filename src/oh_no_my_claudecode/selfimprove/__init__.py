"""After-turn learning review — propose memory updates for human approval.

``onmc selfimprove`` scans a transcript or session text for durable learnings
(user corrections, repeated preferences, confirmed conventions) and emits
candidate memory proposals staged into the memstage approval queue.

Pure stdlib — no LLM calls, no network, no new dependencies.
"""
