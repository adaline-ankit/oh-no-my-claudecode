"""Memory-integrity firewall for the onmc memory store.

Scans memory entries for adversarial content before they are trusted:
- Prompt-injection patterns (ignore/disregard system instructions)
- Credential-exfiltration attempts (secrets, curl-to-URL, base64 blobs)
- SSH/backdoor patterns (authorized_keys, reverse-shell one-liners)
- Dangerous Unicode (zero-width chars, bidi overrides, tag chars)
"""
