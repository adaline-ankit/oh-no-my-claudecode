"""OpenAI-compatible local proxy for onmc LLM providers.

Exposes onmc's configured LLM provider as a standard OpenAI ChatCompletions
endpoint so external tools (Codex / Aider / Cline / Continue) can point at
``http://localhost:8760/v1`` and use whatever backend onmc is configured with.

Usage::

    onmc proxy serve [--port 8760] [--host 127.0.0.1]

The proxy handles:
- ``POST /v1/chat/completions`` — OpenAI ChatCompletions request → onmc provider
- ``GET /v1/models`` — Returns the configured model as a synthetic model list

Pure stdlib (``http.server`` + ``json``).  No new pip dependency.
"""

from oh_no_my_claudecode.proxy.server import (
    ProxyServer,
    make_handler,
    to_openai_error,
    to_openai_models_response,
    to_openai_response,
    to_provider_request,
)

__all__ = [
    "ProxyServer",
    "make_handler",
    "to_openai_error",
    "to_openai_models_response",
    "to_openai_response",
    "to_provider_request",
]
