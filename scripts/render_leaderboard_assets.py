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


def _ranked_entries(
    payload: Mapping[str, Any],
    configuration: str,
) -> list[Mapping[str, Any]]:
    return sorted(
        (
            entry
            for entry in payload["entries"]
            if entry["configuration"] == configuration
        ),
        key=lambda entry: (
            not entry["safety_gate_passed"],
            -entry["final_semantic_exact_count"],
            -entry["consequence_correct_count"],
            entry["system"],
        ),
    )


def _ranking_panel(
    *,
    x: int,
    title: str,
    mode: str,
    gate_summary: str,
    accent: str,
    accent_soft: str,
    entries: list[Mapping[str, Any]],
) -> list[str]:
    panel_width = 598
    body = [
        _rect(x, 214, panel_width, 102, fill=accent_soft, radius=14),
        _text(x + 24, 250, title, size=15, weight=720, fill=accent),
        _text(x + 24, 288, mode, size=26, weight=740),
        _text(
            x + panel_width - 24,
            250,
            gate_summary,
            size=13,
            weight=680,
            fill=accent,
            anchor="end",
            family=MONO,
        ),
        _text(
            x + 82,
            356,
            "MODEL",
            size=12,
            weight=700,
            fill=MUTED,
            family=MONO,
            letter_spacing=0.8,
        ),
        _text(
            x + 300,
            356,
            "EXACT",
            size=12,
            weight=700,
            fill=MUTED,
            anchor="middle",
            family=MONO,
            letter_spacing=0.6,
        ),
        _text(
            x + 435,
            356,
            "CORRECT STATE",
            size=12,
            weight=700,
            fill=MUTED,
            anchor="middle",
            family=MONO,
            letter_spacing=0.4,
        ),
        _text(
            x + 548,
            356,
            "UNSAFE",
            size=12,
            weight=700,
            fill=MUTED,
            anchor="end",
            family=MONO,
            letter_spacing=0.6,
        ),
        _line(x + 20, 376, x + panel_width - 20, 376),
    ]

    for index, entry in enumerate(entries):
        row_top = 402 + index * 166
        if index:
            body.append(
                _line(
                    x + 20,
                    row_top - 24,
                    x + panel_width - 20,
                    row_top - 24,
                )
            )
        body.extend(
            [
                _text(
                    x + 24,
                    row_top + 55,
                    f"{index + 1:02d}",
                    size=30,
                    weight=760,
                    fill=accent,
                    family=MONO,
                ),
                _text(
                    x + 82,
                    row_top + 56,
                    entry["system"],
                    size=18,
                    weight=720,
                ),
                _text(
                    x + 300,
                    row_top + 56,
                    f"{entry['final_semantic_exact_count']}/100",
                    size=17,
                    weight=720,
                    fill=accent,
                    anchor="middle",
                    family=MONO,
                ),
                _text(
                    x + 435,
                    row_top + 56,
                    f"{entry['consequence_correct_count']}/100",
                    size=17,
                    weight=720,
                    fill=accent,
                    anchor="middle",
                    family=MONO,
                ),
                _text(
                    x + 548,
                    row_top + 56,
                    f"{entry['unsafe_effect_count']}/70",
                    size=17,
                    weight=720,
                    fill=accent,
                    anchor="end",
                    family=MONO,
                ),
            ]
        )
    return body


def render_ranked_leaderboards(payload: Mapping[str, Any]) -> str:
    width = 1400
    height = 980
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
        _text(78, 145, "Rankings by execution path", size=38, weight=740),
        _text(
            78,
            180,
            "Same models and 100 worlds. Direct execution and governed execution are ranked separately.",
            size=18,
            fill=INK_SOFT,
        ),
        *_ranking_panel(
            x=78,
            title="WITHOUT YUVIN",
            mode="Direct connector path",
            gate_summary="0 / 3 PASSED SAFETY GATE",
            accent=DIRECT,
            accent_soft=DIRECT_SOFT,
            entries=_ranked_entries(payload, "direct"),
        ),
        *_ranking_panel(
            x=724,
            title="WITH YUVIN",
            mode="Governed execution",
            gate_summary="3 / 3 PASSED SAFETY GATE",
            accent=YUVIN,
            accent_soft=YUVIN_SOFT,
            entries=_ranked_entries(payload, "governed"),
        ),
        _line(78, 888, 1322, 888),
        _text(
            78,
            924,
            "Ranking rule: safety-gate pass, then exact decision, then correct consequence.",
            size=14,
            fill=MUTED,
            family=MONO,
        ),
        _text(
            1322,
            924,
            "INTERNAL DEVELOPMENT COMPARISON  ·  OFFICIAL MODEL APIs",
            size=13,
            weight=650,
            fill=INK_SOFT,
            anchor="end",
            family=MONO,
        ),
    ]

    return _document(
        width=width,
        height=height,
        title="ConsequenceBench rankings without Yuvin and with Yuvin",
        description=(
            "Two complete three-model development rankings. Without Yuvin, "
            "GPT-5.6 Sol ranks first, Gemini 3.6 Flash second, and Gemma4 e4b "
            "third. With Yuvin, the same order is shown with all models "
            "recording zero unsafe simulated effects."
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
                "Internal development comparison using official model APIs. Not a production-safety certification.",
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
    ranked = render_ranked_leaderboards(payload)
    return {
        "development-leaderboard-ranked.svg": ranked,
        "development-leaderboard-unsafe-effects.svg": ranked,
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
