"""
공식 룰북 PDF -> ``data/rules/documents/<doc_id>.json`` 추출기.

이 스크립트는 **원문만** 뽑는다. 요약하지 않고, 바꿔 쓰지 않고, 룰북에 없는
문장을 만들어 넣지 않는다. 구조화 데이터는 별도 계층
(``data/rules/structured/``) 이며 여기서 만들지 않는다.

레이아웃 사실
-------------
- PDF 1 페이지 = 인쇄본 2 페이지(펼침면). 인쇄 쪽번호는
  ``2 * pdf_page - 6 + half`` 다.
- 본문 글꼴이 **올드스타일 숫자**(text figures) 라서 일부 PDF 텍스트 추출기는
  숫자 ``2`` 를 ``•`` 로 잘못 매핑한다. pypdf 로 뽑으면 "Spell Speed •",
  "Chain Link •" 처럼 **규칙의 숫자가 사라진다.** PyMuPDF 는 올바르게 뽑으므로
  이쪽을 쓰고, 추출 후에도 숫자가 살아 있는지 확인한다
  (:data:`REQUIRED_PHRASES`).

사용법::

    python -m scripts.extract_rulebook <룰북.pdf> [--out data/rules/documents]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = PROJECT_ROOT / "data" / "rules" / "documents"
DEFAULT_ID_INDEX = PROJECT_ROOT / "data" / "rules" / "index" / "rule_ids.json"

# 페이지마다 반복되는 장(chapter) 러닝 헤더. 본문이 아니다.
RUNNING_HEADERS = frozenset(
    {"Getting Started", "Game Cards", "How To Play", "Battles and Chains", "Other Rules"}
)

# 같은 시각적 행의 조각으로 볼 최대 가로 간격(pt).
FRAGMENT_GAP = 15.0
# 같은 단으로 볼 최대 x0 차이(pt).
COLUMN_GAP = 24.0
# 단 경계를 가로질러도 되는 줄의 비율 (지면 폭 제목 띠 등).
CROSSING_TOLERANCE = 0.25

# Wingdings 로 찍힌 장식용 글머리표. 사설 영역(PUA) 문자라 글자가 아니다.
_DECORATION = re.compile(r"[-]")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _match_key(text: str) -> str:
    """앵커 대조용 키. 장식 기호와 공백 차이를 무시한다 (원문은 건드리지 않는다)."""
    return _normalize(_DECORATION.sub(" ", text))


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _normalize(text).lower()).strip("-")
    return slug or "section"


class ExtractionError(RuntimeError):
    """앵커를 찾지 못했거나 원문이 손상되었을 때. 조용히 넘어가지 않는다."""


# ----------------------------------------------------------------------
# PDF -> 인쇄 페이지별 행
# ----------------------------------------------------------------------
@dataclass(slots=True)
class Line:
    printed_page: int
    pdf_page: int
    column: int
    y: float
    x: float
    text: str
    font: str
    size: float


def _dedupe_shadow(text: str) -> str:
    """
    제목은 그림자 효과 때문에 같은 문자열이 두 번 겹쳐 찍힌다.
    사이에 공백이 끼어 있을 수 있으므로 공백을 정규화해서 비교한다.
    """
    flat = _normalize(text)
    n = len(flat)
    if n % 2 == 0 and n >= 4 and flat[: n // 2] == flat[n // 2 :]:
        return flat[: n // 2]
    half = (n - 1) // 2
    if n >= 5 and n % 2 == 1 and flat[:half] == flat[half + 1 :] and flat[half] == " ":
        return flat[:half]
    return text


def _raw_lines(page, pdf_page: int) -> list[dict]:
    mid = page.rect.width / 2
    out: list[dict] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", ()):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            text = _dedupe_shadow("".join(s["text"] for s in spans).strip())
            if not text:
                continue
            x0, y0, x1, _y1 = line["bbox"]
            font = spans[0]["font"]
            size = round(max(s["size"] for s in spans), 1)
            if font.startswith("BelweStd-Bold") and size <= 6.2:
                continue  # 하단 쪽번호
            if text in RUNNING_HEADERS and size <= 7.2:
                continue  # 러닝 헤더
            out.append(
                dict(
                    half=0 if (x0 + x1) / 2 < mid else 1,
                    x0=x0,
                    x1=x1,
                    y0=y0,
                    text=text,
                    font=font,
                    size=size,
                    pdf_page=pdf_page,
                )
            )
    return out


def _drop_shadow_copies(items: list[dict]) -> list[dict]:
    """
    그림자 효과로 같은 제목이 살짝 어긋난 위치에 한 번 더 찍힌 경우를 지운다.
    한 줄 안에서 겹친 것은 :func:`_dedupe_shadow` 가, 줄이 아예 나뉜 것은 여기서.
    """
    kept: list[dict] = []
    for item in sorted(items, key=lambda i: (round(i["y0"], 1), i["x0"])):
        flat = _normalize(item["text"])
        if any(
            _normalize(other["text"]) == flat and abs(other["y0"] - item["y0"]) <= 3.0
            for other in kept
        ):
            continue
        kept.append(item)
    return kept


def _assign_columns(items: list[dict]) -> None:
    """
    나란히 놓인 단을 찾아 ``column`` 을 매긴다.

    두 단계로 판단한다.

    1. 같은 x 에서 시작하는 줄이 3개 이상이면 단 후보로 본다. 양끝맞춤 때문에
       한 번씩만 나타나는 조각의 x 는 후보가 아니다 — 이것을 거르지 않으면
       문단 하나가 가짜 단 여러 개로 쪼개진다.
    2. 후보끼리 **가로 범위가 겹치면 같은 단으로 합친다.** 진짜로 나란한 두
       단은 서로 침범하지 않는다. 가운데 정렬된 제목 띠나 들여쓴 예시 상자는
       본문 위에 겹쳐 있으므로 여기서 본문과 같은 단이 되고, 그래서 제목이
       자기 본문보다 뒤로 밀리지 않는다.
    """
    if not items:
        return
    counts: dict[float, int] = {}
    for item in items:
        key = round(item["x0"] / 2) * 2.0
        counts[key] = counts.get(key, 0) + 1
    frequent = sorted(x for x, n in counts.items() if n >= 3) or sorted(counts)
    starts: list[float] = [frequent[0]]
    for x in frequent[1:]:
        if x - starts[-1] > COLUMN_GAP:
            starts.append(x)

    def nearest(x: float) -> int:
        return min(range(len(starts)), key=lambda i: abs(starts[i] - x))

    # 후보 사이의 틈이 진짜 단 경계인지 본다. 경계를 가로지르는 줄이 거의 없으면
    # 진짜 홈통(gutter)이고, 많으면 그냥 들여쓰기나 가운데 정렬 제목이다.
    # 지면 전체를 가로지르는 제목 띠 몇 줄은 허용한다.
    labels: list[int] = [0]
    for index in range(1, len(starts)):
        boundary = starts[index] - 1.0
        crossing = sum(1 for i in items if i["x0"] < boundary < i["x1"])
        is_gutter = crossing <= max(2, len(items) * CROSSING_TOLERANCE)
        labels.append(labels[-1] + 1 if is_gutter else labels[-1])

    for item in items:
        item["column"] = labels[nearest(item["x0"])]


def _merge_fragments(items: list[dict]) -> list[dict]:
    """
    같은 단, 같은 행에서 조각난 텍스트를 합친다.

    양끝맞춤 본문은 단어 사이가 크게 벌어져 한 줄이 여러 조각으로 끊긴다.
    **같은 단** 안에서만 합치므로 나란히 놓인 두 단이 한 줄로 뒤엉키지 않는다.
    """
    merged: list[dict] = []
    for item in sorted(items, key=lambda i: (i["column"], round(i["y0"], 0), i["x0"])):
        if merged:
            prev = merged[-1]
            if (
                prev["column"] == item["column"]
                and abs(prev["y0"] - item["y0"]) <= 1.0
                and item["x0"] - prev["x1"] <= FRAGMENT_GAP
                and prev["size"] == item["size"]
            ):
                joiner = "" if prev["text"].endswith(" ") else " "
                prev["text"] = _dedupe_shadow(prev["text"] + joiner + item["text"])
                prev["x1"] = max(prev["x1"], item["x1"])
                continue
        merged.append(dict(item))
    return merged


def read_printed_pages(pdf_path: str | os.PathLike[str]) -> dict[int, list[Line]]:
    """인쇄 쪽번호 -> 읽는 순서대로 정렬된 행 목록."""
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - 환경 문제
        raise SystemExit(
            "PyMuPDF 가 필요합니다: pip install pymupdf\n"
            "(pypdf 는 이 룰북의 올드스타일 숫자를 '•' 로 잘못 읽습니다.)"
        ) from None

    document = pymupdf.open(pdf_path)
    pages: dict[int, list[Line]] = {}
    for index in range(document.page_count):
        pdf_page = index + 1
        raw = _raw_lines(document[index], pdf_page)
        for half in (0, 1):
            items = [i for i in raw if i["half"] == half]
            if not items:
                continue
            printed = 2 * pdf_page - 6 + half
            items = _drop_shadow_copies(items)
            _assign_columns(items)
            pages.setdefault(printed, []).extend(
                Line(
                    printed_page=printed,
                    pdf_page=pdf_page,
                    column=i["column"],
                    y=round(i["y0"], 1),
                    x=round(i["x0"], 1),
                    text=i["text"],
                    font=i["font"],
                    size=i["size"],
                )
                for i in _merge_fragments(items)
            )
    document.close()
    return pages


# ----------------------------------------------------------------------
# 섹션 구분
# ----------------------------------------------------------------------
# 룰북에는 기계가 읽을 목차 구조가 없다. 그래서 **룰북에 인쇄된 제목**을 앵커로
# 삼아 구간을 자른다. 아래 표에서
#
#   - ``anchor``  : 룰북에 그대로 인쇄된 제목 한 줄. 이 줄부터 다음 앵커 직전까지가
#                   그 섹션의 본문이며, 본문은 **한 글자도 고쳐 쓰지 않는다.**
#   - ``title``   : 표시용 제목. 없으면 앵커를 그대로 쓴다. 있으면 점선(leader)이나
#                   장식 기호를 덜어낸 것이고 ``title_source='editorial'`` 이 된다.
#   - ``start``   : 앵커가 본문에 없을 때(점선 제목 등) 대신 찾을 시작 줄.
#   - ``size``    : 같은 문구가 삽화에도 나올 때 글자 크기로 제목을 특정한다.
#   - ``cat``     : Rule ID 의 분류. 룰북의 장 구성을 주제별로 다시 묶은 것이다.
#
# 앵커가 그 쪽에서 정확히 한 번 나오지 않으면 추출이 실패한다(조용히 넘어가지
# 않는다). 룰북 판본이 바뀌면 여기가 먼저 깨지므로 변경을 놓치지 않는다.
SECTIONS: tuple[dict, ...] = (
    # --- 1 Getting Started ---
    dict(ch=1, level=1, cat="GAME", page=1, anchor="ABOUT THE GAME"),
    dict(ch=1, level=1, cat="DECK", page=2, anchor="Things you need to Duel"),
    dict(ch=1, level=2, cat="DECK", page=2, anchor="Deck",
         title="Deck (40 to 60 cards)",
         start="Assemble your favorite cards into a Deck that follows these rules:"),
    dict(ch=1, level=2, cat="DECK", page=2, anchor="Extra Deck",
         title="Extra Deck (0 to 15 cards)",
         start="This Deck consists of Xyz Monsters, Synchro Monsters and Fusion"),
    dict(ch=1, level=2, cat="DECK", page=2, anchor="Side Deck",
         title="Side Deck (0 to 15 cards)",
         start="This is a separate Deck of cards you can use to change your Deck"),
    dict(ch=1, level=1, cat="MISC", page=3, anchor="Additional items you may need"),
    dict(ch=1, level=1, cat="ZONE", page=4, anchor="THE GAME MAT"),
    # --- 2 Game Cards ---
    dict(ch=2, level=1, cat="CARD", page=6, anchor="HOW TO READ A CARD",
         title="Monster Cards - How to Read a Card"),
    dict(ch=2, level=1, cat="MONSTER", page=8, anchor="WHAT IS A MONSTER CARD?"),
    dict(ch=2, level=2, cat="MONSTER", page=8, anchor="<<<Normal Monsters",
         title="Normal Monsters"),
    dict(ch=2, level=2, cat="MONSTER", page=9, anchor="<<<Effect Monsters",
         title="Effect Monsters"),
    dict(ch=2, level=2, cat="EFFECT", page=9, anchor="Continuous Effect"),
    dict(ch=2, level=2, cat="EFFECT", page=10, anchor="Ignition Effect"),
    dict(ch=2, level=2, cat="EFFECT", page=10, anchor="Quick Effect"),
    dict(ch=2, level=2, cat="EFFECT", page=11, anchor="Trigger Effect"),
    dict(ch=2, level=2, cat="EFFECT", page=11, anchor="Flip Effect"),
    dict(ch=2, level=1, cat="MONSTER", page=12, anchor="LINK MONSTERS"),
    dict(ch=2, level=2, cat="SUMMON", page=13, anchor="HOW TO LINK SUMMON"),
    dict(ch=2, level=2, cat="SUMMON", page=14, anchor="LINK MONSTER BONUSES"),
    dict(ch=2, level=2, cat="MONSTER", page=15, anchor="MORE ABOUT LINK MONSTERS"),
    dict(ch=2, level=1, cat="MONSTER", page=16, anchor="PENDULUM MONSTER CARDS"),
    dict(ch=2, level=2, cat="SUMMON", page=17, anchor="HOW TO PENDULUM SUMMON"),
    dict(ch=2, level=1, cat="MONSTER", page=18, anchor="XYZ MONSTERS"),
    dict(ch=2, level=2, cat="SUMMON", page=19, anchor="HOW TO XYZ SUMMON"),
    dict(ch=2, level=1, cat="MONSTER", page=20, anchor="SYNCHRO MONSTERS"),
    dict(ch=2, level=2, cat="SUMMON", page=21, anchor="HOW TO SYNCHRO SUMMON"),
    dict(ch=2, level=1, cat="MONSTER", page=22, anchor="FUSION MONSTERS"),
    dict(ch=2, level=2, cat="SUMMON", page=22, anchor="HOW TO FUSION SUMMON"),
    dict(ch=2, level=1, cat="MONSTER", page=23, anchor="RITUAL MONSTERS"),
    dict(ch=2, level=2, cat="SUMMON", page=23, anchor="HOW TO RITUAL SUMMON"),
    dict(ch=2, level=1, cat="SUMMON", page=24, anchor="Summoning Monster Cards"),
    dict(ch=2, level=2, cat="SUMMON", page=24, anchor="Normal Summon"),
    dict(ch=2, level=2, cat="SUMMON", page=24, anchor="Normal Set"),
    dict(ch=2, level=2, cat="SUMMON", page=24, anchor="Tribute Summon"),
    dict(ch=2, level=2, cat="SUMMON", page=25, anchor="Flip Summon"),
    dict(ch=2, level=2, cat="SUMMON", page=25, anchor="Special Summon"),
    dict(ch=2, level=2, cat="SUMMON", page=25,
         anchor="Special Summon with a Card’s Effect"),
    dict(ch=2, level=1, cat="CARD", page=26, anchor="HOW TO READ A CARD",
         title="Spell & Trap Cards - How to Read a Card"),
    dict(ch=2, level=1, cat="SPELLTRAP", page=28, anchor="<<<Spell Cards",
         title="Spell Cards"),
    dict(ch=2, level=2, cat="SPELLTRAP", page=28, anchor="Normal Spell Cards"),
    dict(ch=2, level=2, cat="SPELLTRAP", page=28, anchor="Ritual Spell Cards"),
    dict(ch=2, level=2, cat="SPELLTRAP", page=29, anchor="Continuous Spell Cards"),
    dict(ch=2, level=2, cat="SPELLTRAP", page=29, anchor="Equip Spell Cards"),
    dict(ch=2, level=2, cat="SPELLTRAP", page=29, anchor="Field Spell Cards"),
    dict(ch=2, level=2, cat="SPELLTRAP", page=29, anchor="Quick-Play Spell Cards"),
    dict(ch=2, level=1, cat="SPELLTRAP", page=30, anchor="<<<  Trap Cards",
         title="Trap Cards"),
    dict(ch=2, level=2, cat="SPELLTRAP", page=30, anchor="Normal Trap Cards"),
    dict(ch=2, level=2, cat="SPELLTRAP", page=31, anchor="Continuous Trap Cards"),
    dict(ch=2, level=2, cat="SPELLTRAP", page=31, anchor="Counter Trap Cards"),
    dict(ch=2, level=2, cat="SPELLTRAP", page=31,
         anchor="The Difference between Set Spell Cards and Set Trap Cards"),
    # --- 3 How to Play ---
    dict(ch=3, level=1, cat="GAME", page=32, anchor="Let the Duel Begin!"),
    dict(ch=3, level=2, cat="GAME", page=32, anchor="How to Duel and How to Win"),
    dict(ch=3, level=2, cat="GAME", page=32, anchor="Winning a Duel"),
    dict(ch=3, level=1, cat="GAME", page=33, anchor="Preparing to Duel"),
    dict(ch=3, level=1, cat="TURN", page=34, anchor="Turn Structure"),
    dict(ch=3, level=2, cat="TURN", page=35, anchor="Draw Phase"),
    dict(ch=3, level=2, cat="TURN", page=35, anchor="Standby Phase"),
    dict(ch=3, level=2, cat="TURN", page=36, anchor="Main Phase 1"),
    dict(ch=3, level=2, cat="TURN", page=37, anchor="Battle Phase", size=9.0),
    dict(ch=3, level=3, cat="BATTLE", page=38, anchor="Start Step"),
    dict(ch=3, level=3, cat="BATTLE", page=38, anchor="Battle Step"),
    dict(ch=3, level=3, cat="BATTLE", page=38, anchor="Damage Step"),
    dict(ch=3, level=3, cat="BATTLE", page=38, anchor="End Step"),
    dict(ch=3, level=3, cat="BATTLE", page=39,
         anchor="Replay Rules during the Battle Step"),
    dict(ch=3, level=2, cat="TURN", page=40, anchor="Main Phase 2"),
    dict(ch=3, level=2, cat="TURN", page=40, anchor="End Phase"),
    # --- 4 Battles and Chains ---
    dict(ch=4, level=1, cat="BATTLE", page=41, anchor="DAMAGE STEP RULES"),
    dict(ch=4, level=2, cat="BATTLE", page=41,
         anchor="Limitations on Activating Cards"),
    dict(ch=4, level=2, cat="BATTLE", page=41, anchor="Attacking a Face-Down Card"),
    dict(ch=4, level=2, cat="BATTLE", page=41, anchor="Activation of a Flip Effect"),
    dict(ch=4, level=1, cat="BATTLE", page=42, anchor="DETERMINING DAMAGE"),
    dict(ch=4, level=2, cat="BATTLE", page=42,
         anchor="When You Attack an Attack Position Monster"),
    dict(ch=4, level=2, cat="BATTLE", page=43,
         anchor="When You Attack a Defense Position Monster"),
    dict(ch=4, level=2, cat="BATTLE", page=43,
         anchor="If Your Opponent Has No Monsters"),
    dict(ch=4, level=1, cat="CHAIN", page=44, anchor="WHAT IS A CHAIN?"),
    dict(ch=4, level=1, cat="CHAIN", page=44, anchor="SPELL SPEED"),
    dict(ch=4, level=2, cat="CHAIN", page=45, anchor="Spell Speeds"),
    dict(ch=4, level=3, cat="CHAIN", page=45, anchor="Spell Speed 1"),
    dict(ch=4, level=3, cat="CHAIN", page=45, anchor="Spell Speed 2"),
    dict(ch=4, level=3, cat="CHAIN", page=45, anchor="Spell Speed 3"),
    dict(ch=4, level=1, cat="CHAIN", page=46, anchor="How a Chain Works"),
    dict(ch=4, level=1, cat="CHAIN", page=47, anchor="EXAMPLE OF A CHAIN"),
    dict(ch=4, level=1, cat="CHAIN", page=48, anchor="TURN PLAYER’S PRIORITY"),
    # --- 5 Other Rules ---
    dict(ch=5, level=1, cat="DECK", page=49, anchor="Forbidden & Limited Cards"),
    dict(ch=5, level=1, cat="MONSTER", page=49, anchor="Monster Tokens"),
    dict(ch=5, level=1, cat="MISC", page=50, anchor="Public Knowledge"),
    dict(ch=5, level=1, cat="MISC", page=50,
         anchor="If both players conduct actions simultaneously"),
    dict(ch=5, level=1, cat="CHAIN", page=50,
         anchor="When multiple cards are activated simultaneously"),
    dict(ch=5, level=1, cat="BATTLE", page=50, anchor="0 ATK monsters"),
    dict(ch=5, level=1, cat="MISC", page=50, anchor="Rules vs. Card Effects"),
    dict(ch=5, level=1, cat="MISC", page=51, anchor="Counters"),
    dict(ch=5, level=1, cat="CHAIN", page=51,
         anchor="Actions which cannot be Chained to"),
    dict(ch=5, level=1, cat="MONSTER", page=51, anchor="Xyz Materials"),
    dict(ch=5, level=1, cat="MISC", page=51, anchor="Leaves the Field"),
)

CONTENT_PAGES = range(1, 52)
GLOSSARY_PAGES = range(52, 56)
CHAPTER_TITLES = {
    1: "Getting Started",
    2: "Game Cards",
    3: "How to Play",
    4: "Battles and Chains",
    5: "Other Rules",
    6: "Glossary",
}
CATEGORY_TITLES = {
    "GAME": "게임 목적 · 승패 · 듀얼 준비",
    "DECK": "덱 구성과 매수 제한",
    "ZONE": "필드와 존",
    "CARD": "카드 읽는 법",
    "MONSTER": "몬스터 카드 종류",
    "EFFECT": "효과 분류",
    "SUMMON": "소환법",
    "SPELLTRAP": "마법 · 함정 카드",
    "TURN": "턴과 페이즈",
    "BATTLE": "전투와 데미지",
    "CHAIN": "체인 · 스펠 스피드 · 우선권",
    "MISC": "그 밖의 규칙",
    "TERM": "용어",
}


@dataclass(slots=True)
class ExtractedSection:
    rule_id: str
    chapter: int
    level: int
    category: str
    title: str
    title_source: str
    anchor: str
    printed_pages: list[int]
    pdf_pages: list[int]
    lines: list[str]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _flatten(pages: dict[int, list[Line]], page_range) -> list[Line]:
    flat: list[Line] = []
    for printed in sorted(p for p in pages if p in page_range):
        flat.extend(pages[printed])
    return flat


def _locate(flat: list[Line], spec: dict) -> int:
    """앵커 줄의 위치. 그 쪽에서 정확히 한 번만 나와야 한다."""
    wanted = _match_key(spec.get("start") or spec["anchor"])
    hits = [
        i
        for i, line in enumerate(flat)
        if line.printed_page == spec["page"]
        and _match_key(line.text) == wanted
        and (spec.get("size") is None or abs(line.size - spec["size"]) < 0.05)
    ]
    if len(hits) != 1:
        raise ExtractionError(
            f"앵커 {wanted!r} 가 인쇄 {spec['page']}쪽에서 {len(hits)}번 발견되었습니다 "
            "(정확히 1번이어야 합니다). 룰북 판본이 바뀌었는지 확인하세요."
        )
    return hits[0]


def build_sections(pages: dict[int, list[Line]]) -> list[ExtractedSection]:
    """앵커 사이를 잘라 섹션 본문을 만든다. 본문은 원문 줄 그대로다."""
    flat = _flatten(pages, CONTENT_PAGES)
    starts = [_locate(flat, spec) for spec in SECTIONS]
    out_of_order = [
        SECTIONS[i]["anchor"] for i in range(1, len(starts)) if starts[i] <= starts[i - 1]
    ]
    if out_of_order:
        raise ExtractionError(f"섹션 순서가 읽는 순서와 어긋납니다: {out_of_order}")

    sections: list[ExtractedSection] = []
    for index, spec in enumerate(SECTIONS):
        begin = starts[index]
        end = starts[index + 1] if index + 1 < len(starts) else len(flat)
        chunk = flat[begin:end]
        sections.append(
            ExtractedSection(
                rule_id="",  # 뒤에서 부여
                chapter=spec["ch"],
                level=spec["level"],
                category=spec["cat"],
                title=spec.get("title") or spec["anchor"],
                title_source="editorial" if "title" in spec else "heading",
                anchor=spec.get("start") or spec["anchor"],
                printed_pages=sorted({line.printed_page for line in chunk}),
                pdf_pages=sorted({line.pdf_page for line in chunk}),
                lines=[line.text for line in chunk],
            )
        )
    return sections


_GLOSSARY_TERM = re.compile(r"^l\s*(?P<term>.+)$")


def build_glossary(pages: dict[int, list[Line]]) -> list[ExtractedSection]:
    """용어집. 각 항목은 ``l <용어>`` 로 시작하는 줄로 구분된다 (룰북 표기 그대로)."""
    flat = _flatten(pages, GLOSSARY_PAGES)
    entries: list[ExtractedSection] = []
    current: ExtractedSection | None = None
    for line in flat:
        match = _GLOSSARY_TERM.match(_match_key(line.text))
        if match and line.size >= 8.5:
            term = match.group("term").strip()
            current = ExtractedSection(
                rule_id="", chapter=6, level=1, category="TERM",
                title=term, title_source="heading", anchor=line.text.strip(),
                printed_pages=[line.printed_page], pdf_pages=[line.pdf_page],
                lines=[line.text],
            )
            entries.append(current)
        elif current is not None:
            current.lines.append(line.text)
            if line.printed_page not in current.printed_pages:
                current.printed_pages.append(line.printed_page)
            if line.pdf_page not in current.pdf_pages:
                current.pdf_pages.append(line.pdf_page)
    if not entries:
        raise ExtractionError("용어집 항목을 하나도 찾지 못했습니다.")
    return entries


# ----------------------------------------------------------------------
# Rule ID 부여
# ----------------------------------------------------------------------
# ``RULE-<분류>-<번호>``. 번호는 문서 순서대로 붙이되, 한 번 붙인 번호는
# ``data/rules/index/rule_ids.json`` 에 **앵커 키**(분류 + 제목 슬러그)로 적어두고
# 다음 판본에서도 같은 항목이면 그대로 재사용한다. 그래야 룰북이 개정되어
# 앞쪽에 규칙이 끼어들어도 ``RuleRef("RULE-CHAIN-001")`` 이 딴 규칙을 가리키지
# 않는다. 새 항목만 그 분류의 다음 번호를 받는다.
def assign_rule_ids(
    sections: list[ExtractedSection], registry: dict[str, str] | None = None
) -> dict[str, str]:
    registry = dict(registry or {})
    used: dict[str, int] = {}
    for rule_id in registry.values():
        category, number = rule_id.removeprefix("RULE-").rsplit("-", 1)
        used[category] = max(used.get(category, 0), int(number))

    for section in sections:
        key = f"{section.category}:{_slug(section.title)}"
        rule_id = registry.get(key)
        if rule_id is None:
            used[section.category] = used.get(section.category, 0) + 1
            rule_id = f"RULE-{section.category}-{used[section.category]:03d}"
            registry[key] = rule_id
        section.rule_id = rule_id
    return registry


def nest_sections(
    sections: list[ExtractedSection],
) -> tuple[dict[str, str | None], dict[str, list[str]]]:
    """레벨을 보고 부모-자식을 잇는다. ``(부모, 자식목록)`` 을 돌려준다."""
    children: dict[str, list[str]] = {s.rule_id: [] for s in sections}
    parents: dict[str, str | None] = {}
    stack: list[ExtractedSection] = []
    for section in sections:
        while stack and stack[-1].level >= section.level:
            stack.pop()
        parent = stack[-1].rule_id if stack else None
        parents[section.rule_id] = parent
        if parent:
            children[parent].append(section.rule_id)
        stack.append(section)
    return parents, children


# ----------------------------------------------------------------------
# 검증
# ----------------------------------------------------------------------
# 이 문구들은 본문 글꼴의 **올드스타일 숫자** 때문에 추출기가 틀리기 쉬운 자리다.
# pypdf 로 뽑으면 여기 숫자가 '•' 로 바뀌어 규칙의 의미가 사라진다.
REQUIRED_PHRASES = (
    "Spell Speed 2 or higher",
    "cannot be Chain Link 2 or higher",
    "a Spell Speed 1 or 2 effect",
    "Monsters with 2000 or less ATK",
    "Levels 2, 3, 4, 5, 6 and 7",
    "require 2 Tributes",
    "categorized into 2 groups",
    "best 2-out-of-3",
    "If there are 2 or more effects",
    "Semi-Limited cards are restricted to 2 copies",
    "moves to Main Phase 2",
)


def verify_extraction(
    sections: list[ExtractedSection], pages: dict[int, list[Line]]
) -> list[str]:
    """문제를 문자열 목록으로 돌려준다. 비어 있어야 정상이다."""
    problems: list[str] = []

    seen: dict[str, str] = {}
    for section in sections:
        if section.rule_id in seen:
            problems.append(
                f"Rule ID 중복: {section.rule_id} "
                f"({seen[section.rule_id]!r} / {section.title!r})"
            )
        seen[section.rule_id] = section.title
        if not section.lines:
            problems.append(f"{section.rule_id} 의 본문이 비어 있습니다.")
        if section.chapter != 6 and _match_key(section.lines[0]) != _match_key(
            section.anchor
        ):
            problems.append(
                f"{section.rule_id} 의 첫 줄이 제목 {section.anchor!r} 이 아닙니다: "
                f"{section.lines[0]!r}"
            )

    body = "\n".join(_normalize(s.text) for s in sections)
    for phrase in REQUIRED_PHRASES:
        if phrase not in body:
            problems.append(
                f"원문 손상 의심: {phrase!r} 가 없습니다. "
                "PDF 추출기가 올드스타일 숫자를 잘못 읽었을 수 있습니다."
            )

    expected = [
        line.text
        for printed in sorted(pages)
        if printed in CONTENT_PAGES
        for line in pages[printed]
    ]
    actual = [t for s in sections if s.chapter != 6 for t in s.lines]
    if expected != actual:
        problems.append(
            f"본문 줄이 유실/변형되었습니다 (원본 {len(expected)}줄, 섹션 {len(actual)}줄)."
        )
    return problems


# ----------------------------------------------------------------------
# 문서 조립 · 출력
# ----------------------------------------------------------------------
def file_hash(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def build_document(
    pdf_path: str | os.PathLike[str],
    doc_id: str,
    title: str,
    source: str,
    version: str,
    registry: dict[str, str] | None = None,
    retrieved_at: str | None = None,
) -> tuple[dict, dict[str, str], list[str]]:
    pages = read_printed_pages(pdf_path)
    sections = build_sections(pages) + build_glossary(pages)
    registry = assign_rule_ids(sections, registry)
    parents, children = nest_sections(sections)
    problems = verify_extraction(sections, pages)

    document = {
        "schema_version": 1,
        "document": {
            "doc_id": doc_id,
            "title": title,
            "source": source,
            "version": version,
            "language": "en",
            "retrieved_at": retrieved_at
            or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "document_hash": file_hash(pdf_path),
            "source_file": Path(pdf_path).name,
            "extractor": "scripts/extract_rulebook.py",
            "printed_page_range": [
                min(s.printed_pages[0] for s in sections),
                max(s.printed_pages[-1] for s in sections),
            ],
            "section_count": len(sections),
        },
        "sections": [
            {
                "rule_id": s.rule_id,
                "title": s.title,
                "title_source": s.title_source,
                "anchor": s.anchor,
                "category": s.category,
                "category_title": CATEGORY_TITLES[s.category],
                "chapter": s.chapter,
                "chapter_title": CHAPTER_TITLES[s.chapter],
                "level": s.level,
                "parent": parents[s.rule_id],
                "subsections": children[s.rule_id],
                "source_reference": {
                    "document": doc_id,
                    "printed_pages": s.printed_pages,
                    "pdf_pages": s.pdf_pages,
                },
                "text": s.text,
            }
            for s in sections
        ],
    }
    return document, registry, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="공식 룰북 PDF 에서 원문을 추출한다.")
    parser.add_argument("pdf", help="룰북 PDF 경로")
    parser.add_argument("--doc-id", default="sd-rulebook-en-v10")
    parser.add_argument(
        "--title", default="Yu-Gi-Oh! TRADING CARD GAME Official Rulebook"
    )
    parser.add_argument(
        "--source",
        default="Konami Digital Entertainment, Inc. — Starter Deck Rulebook (English)",
    )
    parser.add_argument("--version", default="10")
    parser.add_argument("--out", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--id-index", default=str(DEFAULT_ID_INDEX))
    parser.add_argument(
        "--retrieved-at",
        default=None,
        help="추출 시각을 고정한다 (재현성 확인용).",
    )
    args = parser.parse_args(argv)

    index_path = Path(args.id_index)
    registry = (
        json.loads(index_path.read_text(encoding="utf-8"))["ids"]
        if index_path.is_file()
        else {}
    )

    document, registry, problems = build_document(
        args.pdf, args.doc_id, args.title, args.source, args.version, registry,
        retrieved_at=args.retrieved_at,
    )
    for problem in problems:
        print(f"[문제] {problem}", file=sys.stderr)
    if problems:
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.doc_id}.json"
    out_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {"schema_version": 1, "ids": dict(sorted(registry.items()))},
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{out_path} 에 섹션 {len(document['sections'])}개를 저장했습니다.")
    print(f"{index_path} 에 Rule ID {len(registry)}개를 기록했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
