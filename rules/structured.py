"""
구조화된 규칙.

원문(:mod:`rules.rule_model`) 위에 얹는 **기계가 읽는 층**이다. 세 가지 규칙을
지킨다.

1. 모든 항목은 :class:`~rules.rule_model.RuleRef` 로 자기 근거를 가리킨다.
   근거 없는 항목은 만들지 않는다.
2. 룰북이 말하지 않은 값은 ``None`` 으로 두고 ``not_stated`` 에 이름을 적는다.
   **빈칸을 그럴듯한 값으로 메우지 않는다.**
3. 여기 있는 값은 원문을 **대체하지 않는다.** 구현이 애매하면 ``rules`` 가
   가리키는 원문으로 돌아간다.

:mod:`engine` 을 import 하지 않는다. 의존 방향은 Rules -> Engine 이고 그 반대가
아니다. 그래서 존/페이즈 이름은 그냥 문자열로 두고, 엔진 어휘와의 연결은
:mod:`rules.concept_map` 이 담당한다.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from rules.rule_model import RuleRef

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STRUCTURED_DIR = PROJECT_ROOT / "data" / "rules" / "structured"


@dataclass(frozen=True, slots=True)
class Grounded:
    """근거를 갖는 구조화 항목의 공통 부분."""

    rules: tuple[RuleRef, ...] = ()
    """이 항목이 나온 원문 절."""
    not_stated: tuple[str, ...] = ()
    """룰북이 말하지 않아 비워 둔 필드 이름."""
    notes: str = ""
    """원문을 그대로 옮긴 짧은 인용 또는 주의. 해석을 적는 자리가 아니다."""

    def cites(self, rule_id: str) -> bool:
        return any(ref.rule_id == rule_id for ref in self.rules)


@dataclass(frozen=True, slots=True)
class PhaseRule(Grounded):
    """턴 안의 한 페이즈."""

    name: str = ""
    """룰북의 페이즈 이름. 예: "Main Phase 1"."""
    engine_phase: str | None = None
    """:mod:`engine.vocabulary` 의 ``Phase`` 이름. 없으면 ``None``."""
    order: int = 0
    main_actions: tuple[str, ...] = ()
    other_actions: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    first_turn_restriction: str | None = None


@dataclass(frozen=True, slots=True)
class ZoneRule(Grounded):
    """존 하나의 규칙."""

    name: str = ""
    engine_zone: str | None = None
    capacity: int | None = None
    """넣을 수 있는 최대 장수. 룰북이 말하지 않으면 ``None``."""
    visibility: str | None = None
    """``public`` / ``private`` / ``owner_only`` / ``count_public``."""
    ordering: str | None = None
    """``fixed`` (순서를 바꾸면 안 됨) / ``none``."""
    default_face: str | None = None
    movement: tuple[str, ...] = ()
    counts_toward: str | None = None


@dataclass(frozen=True, slots=True)
class SpellSpeedRule(Grounded):
    """스펠 스피드 한 단계."""

    speed: int = 0
    card_types: tuple[str, ...] = ()
    can_respond_to: tuple[int, ...] = ()
    """이 스피드로 응수할 수 있는 상대 스피드."""


@dataclass(frozen=True, slots=True)
class ChainRule(Grounded):
    """체인 형성과 해결."""

    activation_order: str = ""
    resolution_order: str = ""
    response_requirement: str = ""
    cannot_chain_to: tuple[str, ...] = ()
    simultaneous_order: tuple[str, ...] = ()
    spell_speeds: tuple[SpellSpeedRule, ...] = ()


@dataclass(frozen=True, slots=True)
class SummonRule(Grounded):
    """소환법 하나."""

    summon_type: str = ""
    engine_summon_type: str | None = None
    """:mod:`engine.vocabulary` 의 ``SUMMON_TYPE_*`` 이름. 대응이 없으면 ``None``."""
    is_special_summon: bool | None = None
    once_per_turn: bool | None = None
    procedure: tuple[str, ...] = ()
    restrictions: tuple[str, ...] = ()
    default_positions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EffectTypeRule(Grounded):
    """효과 분류 하나."""

    name: str = ""
    spell_speed: int | None = None
    activation_timing: str | None = None
    has_activation: bool | None = None


@dataclass(frozen=True, slots=True)
class WinConditionRule(Grounded):
    """승리 조건 하나."""

    condition: str = ""
    applies_to: str = "opponent"


@dataclass(slots=True)
class StructuredRules:
    """구조화 규칙 묶음 하나 (문서 한 권에 대응)."""

    doc_id: str
    schema_version: int = 1
    phases: list[PhaseRule] = field(default_factory=list)
    zones: list[ZoneRule] = field(default_factory=list)
    chain: ChainRule | None = None
    summons: list[SummonRule] = field(default_factory=list)
    effect_types: list[EffectTypeRule] = field(default_factory=list)
    win_conditions: list[WinConditionRule] = field(default_factory=list)

    # --- 조회 -----------------------------------------------------------
    def phase(self, name: str) -> PhaseRule | None:
        return next((p for p in self.phases if p.name == name), None)

    def zone(self, name: str) -> ZoneRule | None:
        return next((z for z in self.zones if z.name == name), None)

    def summon(self, summon_type: str) -> SummonRule | None:
        return next((s for s in self.summons if s.summon_type == summon_type), None)

    def effect_type(self, name: str) -> EffectTypeRule | None:
        return next((e for e in self.effect_types if e.name == name), None)

    def turn_order(self) -> list[str]:
        return [p.name for p in sorted(self.phases, key=lambda p: p.order)]

    def __iter__(self) -> Iterator[Grounded]:
        yield from self.phases
        yield from self.zones
        if self.chain is not None:
            yield self.chain
            yield from self.chain.spell_speeds
        yield from self.summons
        yield from self.effect_types
        yield from self.win_conditions

    def referenced_rule_ids(self) -> set[str]:
        return {ref.rule_id for item in self for ref in item.rules}


# ----------------------------------------------------------------------
# 적재
# ----------------------------------------------------------------------
def _common(raw: dict) -> dict:
    return dict(
        rules=tuple(RuleRef(r) for r in raw.get("rules", ())),
        not_stated=tuple(raw.get("not_stated", ())),
        notes=raw.get("notes", ""),
    )


def _phase(raw: dict) -> PhaseRule:
    return PhaseRule(
        name=raw["name"],
        engine_phase=raw.get("engine_phase"),
        order=raw["order"],
        main_actions=tuple(raw.get("main_actions", ())),
        other_actions=tuple(raw.get("other_actions", ())),
        steps=tuple(raw.get("steps", ())),
        first_turn_restriction=raw.get("first_turn_restriction"),
        **_common(raw),
    )


def _zone(raw: dict) -> ZoneRule:
    return ZoneRule(
        name=raw["name"],
        engine_zone=raw.get("engine_zone"),
        capacity=raw.get("capacity"),
        visibility=raw.get("visibility"),
        ordering=raw.get("ordering"),
        default_face=raw.get("default_face"),
        movement=tuple(raw.get("movement", ())),
        counts_toward=raw.get("counts_toward"),
        **_common(raw),
    )


def _spell_speed(raw: dict) -> SpellSpeedRule:
    return SpellSpeedRule(
        speed=raw["speed"],
        card_types=tuple(raw.get("card_types", ())),
        can_respond_to=tuple(raw.get("can_respond_to", ())),
        **_common(raw),
    )


def _chain(raw: dict) -> ChainRule:
    return ChainRule(
        activation_order=raw.get("activation_order", ""),
        resolution_order=raw.get("resolution_order", ""),
        response_requirement=raw.get("response_requirement", ""),
        cannot_chain_to=tuple(raw.get("cannot_chain_to", ())),
        simultaneous_order=tuple(raw.get("simultaneous_order", ())),
        spell_speeds=tuple(_spell_speed(s) for s in raw.get("spell_speeds", ())),
        **_common(raw),
    )


def _summon(raw: dict) -> SummonRule:
    return SummonRule(
        summon_type=raw["summon_type"],
        engine_summon_type=raw.get("engine_summon_type"),
        is_special_summon=raw.get("is_special_summon"),
        once_per_turn=raw.get("once_per_turn"),
        procedure=tuple(raw.get("procedure", ())),
        restrictions=tuple(raw.get("restrictions", ())),
        default_positions=tuple(raw.get("default_positions", ())),
        **_common(raw),
    )


def _effect_type(raw: dict) -> EffectTypeRule:
    return EffectTypeRule(
        name=raw["name"],
        spell_speed=raw.get("spell_speed"),
        activation_timing=raw.get("activation_timing"),
        has_activation=raw.get("has_activation"),
        **_common(raw),
    )


def _win(raw: dict) -> WinConditionRule:
    return WinConditionRule(
        condition=raw["condition"],
        applies_to=raw.get("applies_to", "opponent"),
        **_common(raw),
    )


def load_structured(path: str | os.PathLike[str]) -> StructuredRules:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise ValueError(f"모르는 schema_version: {raw.get('schema_version')!r}")
    return StructuredRules(
        doc_id=raw["doc_id"],
        schema_version=raw["schema_version"],
        phases=[_phase(p) for p in raw.get("phases", ())],
        zones=[_zone(z) for z in raw.get("zones", ())],
        chain=_chain(raw["chain"]) if raw.get("chain") else None,
        summons=[_summon(s) for s in raw.get("summons", ())],
        effect_types=[_effect_type(e) for e in raw.get("effect_types", ())],
        win_conditions=[_win(w) for w in raw.get("win_conditions", ())],
    )


def load_all(
    structured_dir: str | os.PathLike[str] | None = None,
) -> list[StructuredRules]:
    directory = Path(structured_dir or DEFAULT_STRUCTURED_DIR)
    if not directory.is_dir():
        return []
    return [load_structured(path) for path in sorted(directory.glob("*.json"))]
