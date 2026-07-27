"""Render deterministic SVG leaderboard assets from the public receipt."""
from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "results" / "development_leaderboard.v1.json"
DEFAULT_OUTPUT = ROOT / "docs" / "assets"
SYSTEM_ORDER = (
    "GPT-5.6 Sol (xhigh)",
    "Gemini 3.6 Flash",
    "Gemma4 e4b",
)

INK = "#101828"
INK_SOFT = "#475467"
MUTED = "#667085"
LINE = "#D9E0EA"
SURFACE = "#FFFFFF"
CANVAS = "#F5F7FB"
DIRECT = "#B85C4C"
DIRECT_SOFT = "#F6E9E6"
YUVIN = "#2756D8"
YUVIN_SOFT = "#E7EDFC"
SUCCESS = "#17735B"
SUCCESS_SOFT = "#E3F3EE"

FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif"
MONO = "'SFMono-Regular', Consolas, 'Liberation Mono', monospace"


def _attr(value: object) -> str:
    return escape(str(value), quote=True)


def _text(
    x: int,
    y: int,
    value: object,
    *,
    size: int = 18,
    weight: int = 400,
    fill: str = INK,
    anchor: str = "start",
    family: str = FONT,
    letter_spacing: float | None = None,
) -> str:
    spacing = (
        ""
        if letter_spacing is None
        else f' letter-spacing="{letter_spacing:g}"'
    )
    return (
        f'<text x="{x}" y="{y}" font-family="{_attr(family)}" '
        f'font-size="{size}" font-weight="{weight}" fill="{fill}" '
        f'text-anchor="{anchor}"{spacing}>{escape(str(value))}</text>'
    )


def _rect(
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    fill: str,
    radius: int = 0,
    stroke: str | None = None,
) -> str:
    border = "" if stroke is None else f' stroke="{stroke}"'
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" '
        f'rx="{radius}" fill="{fill}"{border}/>'
    )


def _line(x1: int, y1: int, x2: int, y2: int, *, stroke: str = LINE) -> str:
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
        f'stroke="{stroke}" stroke-width="1"/>'
    )


def _document(
    *,
    width: int,
    height: int,
    title: str,
    description: str,
    body: list[str],
) -> str:
    return "\n".join(
        [
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
                f'height="{height}" viewBox="0 0 {width} {height}" '
                'role="img" aria-labelledby="title description">'
            ),
            f"  <title id=\"title\">{escape(title)}</title>",
            f"  <desc id=\"description\">{escape(description)}</desc>",
            *[f"  {item}" for item in body],
            "</svg>",
            "",
        ]
    )


def _pairs(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    entries: dict[tuple[str, str], Mapping[str, Any]] = {
        (entry["system"], entry["configuration"]): entry
        for entry in payload["entries"]
    }
    pairs: list[dict[str, Any]] = []
    for system in SYSTEM_ORDER:
        direct = entries[(system, "direct")]
        governed = entries[(system, "governed")]
        pairs.append(
            {
                "system": system,
                "direct": direct,
                "governed": governed,
            }
        )
    return pairs


def render_unsafe_effects(payload: Mapping[str, Any]) -> str:
    width = 1400
    height = 850
    body: list[str] = [
        _rect(0, 0, width, height, fill=CANVAS),
        _rect(38, 34, width - 76, height - 68, fill=SURFACE, radius=16, stroke=LINE),
        _text(
            78,
            88,
            "CONSEQUENCEBENCH / PAIRED DEVELOPMENT RUNS",
            size=15,
            weight=650,
            fill=YUVIN,
            family=MONO,
            letter_spacing=1.6,
        ),
        _text(78, 145, "Unsafe simulated effects", size=36, weight=720),
        _text(
            78,
            180,
            "Same model, same 70 unsafe-action worlds per arm. Lower is better.",
            size=18,
            fill=INK_SOFT,
        ),
        _rect(1024, 74, 280, 42, fill=YUVIN_SOFT, radius=21),
        _text(
            1164,
            101,
            "WITHOUT YUVIN  /  WITH YUVIN",
            size=13,
            weight=650,
            fill=YUVIN,
            anchor="middle",
            family=MONO,
            letter_spacing=0.7,
        ),
    ]

    bar_x = 318
    bar_width = 892
    max_unsafe = int(payload["corpus"]["unsafe_action_world_count"])
    for index, pair in enumerate(_pairs(payload)):
        top = 238 + index * 172
        direct_value = int(pair["direct"]["unsafe_effect_count"])
        governed_value = int(pair["governed"]["unsafe_effect_count"])
        direct_width = round(bar_width * direct_value / max_unsafe)
        governed_width = max(
            4,
            round(bar_width * governed_value / max_unsafe),
        )

        if index:
            body.append(_line(78, top - 36, 1322, top - 36))
        body.extend(
            [
                _text(78, top, pair["system"], size=22, weight=700),
                _text(
                    1302,
                    top,
                    f"{direct_value}  →  {governed_value}",
                    size=18,
                    weight=700,
                    fill=INK,
                    anchor="end",
                    family=MONO,
                ),
                _text(
                    78,
                    top + 47,
                    "Without Yuvin",
                    size=15,
                    weight=650,
                    fill=DIRECT,
                ),
                _text(
                    196,
                    top + 47,
                    "Direct",
                    size=14,
                    fill=MUTED,
                    family=MONO,
                ),
                _rect(
                    bar_x,
                    top + 31,
                    bar_width,
                    18,
                    fill=DIRECT_SOFT,
                    radius=9,
                ),
                _rect(
                    bar_x,
                    top + 31,
                    direct_width,
                    18,
                    fill=DIRECT,
                    radius=9,
                ),
                _text(
                    1302,
                    top + 47,
                    f"{direct_value} / {max_unsafe}",
                    size=15,
                    weight=650,
                    fill=DIRECT,
                    anchor="end",
                    family=MONO,
                ),
                _text(
                    78,
                    top + 91,
                    "With Yuvin",
                    size=15,
                    weight=650,
                    fill=YUVIN,
                ),
                _text(
                    174,
                    top + 91,
                    "Governed",
                    size=14,
                    fill=MUTED,
                    family=MONO,
                ),
                _rect(
                    bar_x,
                    top + 75,
                    bar_width,
                    18,
                    fill=YUVIN_SOFT,
                    radius=9,
                ),
                _rect(
                    bar_x,
                    top + 75,
                    governed_width,
                    18,
                    fill=YUVIN,
                    radius=2 if governed_value == 0 else 9,
                ),
                _text(
                    1302,
                    top + 91,
                    f"{governed_value} / {max_unsafe}",
                    size=15,
                    weight=650,
                    fill=YUVIN,
                    anchor="end",
                    family=MONO,
                ),
            ]
        )

    body.extend(
        [
            _line(78, 742, 1322, 742),
            _text(
                78,
                778,
                "100 paired worlds per model  ·  seed 0  ·  values rendered from the public receipt",
                size=14,
                fill=MUTED,
                family=MONO,
            ),
            _text(
                1322,
                778,
                "DEVELOPMENT / SELF-REPORTED / UNRANKED",
                size=13,
                weight=650,
                fill=INK_SOFT,
                anchor="end",
                family=MONO,
            ),
        ]
    )

    return _document(
        width=width,
        height=height,
        title="Unsafe simulated effects, Direct versus With Yuvin",
        description=(
            "Three paired development comparisons. GPT-5.6 Sol recorded 21 "
            "unsafe effects without Yuvin and 0 with Yuvin. Gemini 3.6 Flash "
            "recorded 59 and 0. Gemma4 e4b recorded 63 and 0."
        ),
        body=body,
    )


def _metric_row(
    *,
    y: int,
    label: str,
    direct: str,
    governed: str,
    change: str,
    change_tone: str = SUCCESS,
) -> list[str]:
    return [
        _text(88, y, label, size=16, weight=600, fill=INK_SOFT),
        _text(
            668,
            y,
            direct,
            size=17,
            weight=680,
            fill=DIRECT,
            anchor="end",
            family=MONO,
        ),
        _text(
            958,
            y,
            governed,
            size=17,
            weight=680,
            fill=YUVIN,
            anchor="end",
            family=MONO,
        ),
        _rect(1090, y - 24, 220, 34, fill=SUCCESS_SOFT, radius=17),
        _text(
            1200,
            y - 1,
            change,
            size=14,
            weight=700,
            fill=change_tone,
            anchor="middle",
            family=MONO,
        ),
    ]


def render_paired_scorecard(payload: Mapping[str, Any]) -> str:
    width = 1400
    height = 940
    body: list[str] = [
        _rect(0, 0, width, height, fill=CANVAS),
        _rect(38, 34, width - 76, height - 68, fill=SURFACE, radius=16, stroke=LINE),
        _rect(38, 34, width - 76, 148, fill=INK, radius=16),
        _rect(38, 166, width - 76, 16, fill=INK),
        _text(
            78,
            80,
            "CONSEQUENCEBENCH",
            size=14,
            weight=700,
            fill="#AFC2FF",
            family=MONO,
            letter_spacing=1.8,
        ),
        _text(78, 132, "Paired development leaderboard", size=34, weight=720, fill=SURFACE),
        _text(
            1322,
            91,
            "SAME MODELS · SAME WORLDS · ONE EXECUTION-PATH CHANGE",
            size=13,
            weight=650,
            fill="#D0D8EA",
            anchor="end",
            family=MONO,
            letter_spacing=0.5,
        ),
        _text(
            88,
            226,
            "MODEL / MEASURE",
            size=13,
            weight=700,
            fill=MUTED,
            family=MONO,
            letter_spacing=0.8,
        ),
        _text(
            668,
            226,
            "WITHOUT YUVIN · DIRECT",
            size=13,
            weight=700,
            fill=DIRECT,
            anchor="end",
            family=MONO,
            letter_spacing=0.6,
        ),
        _text(
            958,
            226,
            "WITH YUVIN · GOVERNED",
            size=13,
            weight=700,
            fill=YUVIN,
            anchor="end",
            family=MONO,
            letter_spacing=0.6,
        ),
        _text(
            1200,
            226,
            "OBSERVED CHANGE",
            size=13,
            weight=700,
            fill=MUTED,
            anchor="middle",
            family=MONO,
            letter_spacing=0.6,
        ),
        _line(78, 250, 1322, 250),
    ]

    for index, pair in enumerate(_pairs(payload)):
        direct = pair["direct"]
        governed = pair["governed"]
        top = 300 + index * 190
        exact_delta = (
            int(governed["final_semantic_exact_count"])
            - int(direct["final_semantic_exact_count"])
        )
        consequence_delta = (
            int(governed["consequence_correct_count"])
            - int(direct["consequence_correct_count"])
        )
        unsafe_delta = (
            int(governed["unsafe_effect_count"])
            - int(direct["unsafe_effect_count"])
        )
        if index:
            body.append(_line(78, top - 46, 1322, top - 46))
        body.extend(
            [
                _text(88, top, pair["system"], size=22, weight=720),
                *_metric_row(
                    y=top + 44,
                    label="Exact decision",
                    direct=f"{direct['final_semantic_exact_count']} / 100",
                    governed=f"{governed['final_semantic_exact_count']} / 100",
                    change=f"{exact_delta:+d} points",
                ),
                *_metric_row(
                    y=top + 84,
                    label="Correct consequence",
                    direct=f"{direct['consequence_correct_count']} / 100",
                    governed=f"{governed['consequence_correct_count']} / 100",
                    change=f"{consequence_delta:+d} points",
                ),
                *_metric_row(
                    y=top + 124,
                    label="Unsafe effects",
                    direct=f"{direct['unsafe_effect_count']} / 70",
                    governed=f"{governed['unsafe_effect_count']} / 70",
                    change=f"{unsafe_delta:+d} effects",
                ),
            ]
        )

    body.extend(
        [
            _line(78, 856, 1322, 856),
            _text(
                78,
                892,
                "Development evidence, self-operated and unranked. This is not a production-safety certification.",
                size=14,
                fill=MUTED,
                family=MONO,
            ),
            _text(
                1322,
                892,
                "results/development_leaderboard.v1.json",
                size=14,
                weight=650,
                fill=YUVIN,
                anchor="end",
                family=MONO,
            ),
        ]
    )

    return _document(
        width=width,
        height=height,
        title="ConsequenceBench paired development leaderboard",
        description=(
            "A model-by-model comparison of exact decision, correct consequence, "
            "and unsafe simulated effects without Yuvin and with Yuvin."
        ),
        body=body,
    )


def render_assets(payload: Mapping[str, Any]) -> dict[str, str]:
    return {
        "development-leaderboard-unsafe-effects.svg": render_unsafe_effects(payload),
        "development-leaderboard-paired.svg": render_paired_scorecard(payload),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    rendered = render_assets(payload)
    if args.check:
        for name, expected in rendered.items():
            path = args.output_dir / name
            if path.read_text(encoding="utf-8") != expected:
                raise ValueError(f"committed leaderboard asset is stale: {path}")
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in rendered.items():
        (args.output_dir / name).write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
