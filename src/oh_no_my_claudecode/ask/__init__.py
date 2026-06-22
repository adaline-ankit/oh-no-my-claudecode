"""Ask module — natural-language query over the repo memory brain.

``onmc ask "<question>"`` ranks and cites memories relevant to the question
(always offline-safe) and optionally synthesizes a concise answer via an LLM
when a provider is configured.

Public API
----------
compile_ask(storage, repo_root, question, *, limit, provider) -> AskResult
"""

from oh_no_my_claudecode.ask.compiler import AskResult, compile_ask

__all__ = ["AskResult", "compile_ask"]
