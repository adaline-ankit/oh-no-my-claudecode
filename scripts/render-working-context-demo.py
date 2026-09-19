# /// script
# requires-python = ">=3.11"
# dependencies = ["Pillow>=11,<13"]
# ///
"""Render share cards from the real demo JSON; does not run an agent.

uv run scripts/render-working-context-demo.py /tmp/working-context-demo.json \
    --output-dir docs/assets
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CHECKS = {
    "real_prompt_hook_delivered_context",
    "unchanged_context_suppressed",
    "dirty_source_with_same_mtime_withdrawn",
    "stale_claim_absent",
    "constraints_restored",
    "next_step_restored",
    "sessions_isolated",
    "budget_respected",
}
BG = "#0b101a"
PANEL = "#141d2c"
TEXT = "#edf3fd"
MUTED = "#a2b1c6"
GREEN = "#80ebbb"
ORANGE = "#ffbc7d"


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in (
        "/System/Library/Fonts/Menlo.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "C:/Windows/Fonts/consola.ttf",
    ):
        if Path(name).is_file():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default(size=size)


def frame(
    step: int, title: str, subtitle: str, lines: list[tuple[str, str]], badge: str
) -> Image.Image:
    canvas = Image.new("RGB", (1280, 720), BG)
    draw = ImageDraw.Draw(canvas)
    draw.text((64, 38), "ONMC / ADAPTIVE WORKING CONTEXT", font=font(21), fill=GREEN)
    draw.text((64, 98), title, font=font(42), fill=TEXT)
    draw.text((64, 161), subtitle, font=font(21), fill=MUTED)
    draw.rounded_rectangle((64, 225, 1216, 556), radius=20, fill=PANEL)
    for i, color in enumerate(("#ff7b80", "#ffcd78", GREEN)):
        draw.ellipse((91 + i * 23, 249, 102 + i * 23, 260), fill=color)
    draw.text((181, 244), "REAL DEMO RESULTS / NO MODEL CALLS", font=font(17), fill=MUTED)
    for i, (line, color) in enumerate(lines):
        draw.text((94, 304 + i * 48), line, font=font(25), fill=color)
    draw.text((64, 589), badge, font=font(24), fill=GREEN)
    draw.text((64, 656), "Keep the task. Refresh the evidence.", font=font(20), fill=MUTED)
    draw.text(
        (64, 689),
        "github.com/adaline-ankit/oh-no-my-claudecode",
        font=font(14),
        fill=MUTED,
    )
    for i in range(4):
        draw.rounded_rectangle(
            (1040 + i * 45, 660, 1070 + i * 45, 666),
            radius=3,
            fill=GREEN if i == step else PANEL,
        )
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("docs/assets"))
    args = parser.parse_args()
    result = json.loads(args.results.read_text(encoding="utf-8"))
    checks = result.get("checks", {})
    if (
        result.get("kind") != "functional_demo_no_model_calls"
        or result.get("passed") is not True
        or not all(checks.get(key) is True for key in CHECKS)
        or result.get("injected_chars", {}).get("repeat") != 0
        or "Cache TTL is 30 seconds." not in result.get("before", "")
        or "Cache TTL is 30 seconds." in result.get("after", "")
        or {"id": "cache-ttl", "reason": "source_changed"} not in result.get("excluded_after", [])
    ):
        raise SystemExit("Demo evidence missing or failed; refusing to render passing claims.")
    frames = [
        frame(
            0,
            "Memory meets the current source.",
            "A task starts with eligible evidence.",
            [
                ("Goal: Fix cache expiration.", TEXT),
                ("Constraint: Preserve the public cache API.", TEXT),
                ("Memory: Cache TTL is 30 seconds.", GREEN),
                ("Source: cache.py / content unchanged", MUTED),
            ],
            "01 / Recall from actual Git + SQLite state",
        ),
        frame(
            1,
            "The file changed. The claim expires.",
            "Dirty edit. Same timestamp. Different content.",
            [
                ("cache.py: TTL_SECONDS = 30 -> 60", TEXT),
                ("File timestamp: unchanged", MUTED),
                ("WITHDRAWN: cache-ttl / source_changed", ORANGE),
                ("Old TTL claim absent from fresh packet.", GREEN),
            ],
            "02 / Content hashes catch the stale source",
        ),
        frame(
            2,
            "The task survives the refresh.",
            "Reload local working state. Restore the current packet.",
            [
                ("Goal: Fix cache expiration.", TEXT),
                ("Constraint: Preserve the public cache API.", GREEN),
                ("Next step: Run cache regression tests.", GREEN),
                ("Other session: separate goal and notes.", MUTED),
            ],
            "03 / Restore the goal, constraints, and next step",
        ),
        frame(
            3,
            "Same context? Zero extra characters.",
            "Unchanged packets stay quiet. Full refresh remains explicit.",
            [
                ("Repeated packet: 0 injected characters", GREEN),
                ("Stale source claim: withdrawn", ORANGE),
                ("Session state: restored and isolated", TEXT),
                ("Functional demo: 8 / 8 checks passed", GREEN),
            ],
            "04 / Advisory context. No coding-accuracy claim.",
        ),
    ]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = args.output_dir / "working-context-demo"
    frames[1].save(stem.with_suffix(".png"), optimize=True)
    frames[0].save(
        stem.with_suffix(".gif"),
        save_all=True,
        append_images=frames[1:],
        duration=[3500, 4500, 4000, 4500],
        loop=0,
        optimize=True,
    )
    destination = stem.with_suffix(".json")
    if args.results.resolve() != destination.resolve():
        shutil.copyfile(args.results, destination)
    print(f"Rendered {stem}.gif, .png, .json from 8 passing demo checks.")


if __name__ == "__main__":
    main()
