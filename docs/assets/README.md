# Working-context demo assets

These assets render the output of the real functional demo. They are not a
recording of a Claude session and contain no model calls or coding-accuracy claim.

- `working-context-demo.gif`: four frames, 16.5 seconds, 1280 × 720.
- `working-context-demo.png`: static source-withdrawal card.
- `working-context-demo.json`: captured demo checks and actual before/after packets.

From an installed source checkout:

```bash
python scripts/demo-working-context.py --output /tmp/working-context-demo.json
uv run --no-project scripts/render-working-context-demo.py /tmp/working-context-demo.json \
  --output-dir docs/assets
```

The renderer refuses results with missing/failed required checks. Pillow runs in
an isolated script environment; it is not an ONMC runtime dependency. Font choice
can vary by platform. Generated note IDs and observed timing vary between demo
runs; the committed JSON is one captured run, not a performance benchmark.

For performance measurements, use the separate
[working-context benchmark protocol](../benchmarks/working-context.md).
