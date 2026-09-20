"""
손으로 쓴 **효과 구현 목록** — 이 엔진이 실제로 실행할 수 있는 카드 효과.

    LibraryEntry
      ├ definition     무엇을 하는가 (EffectDefinition)
      ├ lua_file       그 의미를 어디서 읽었는가
      ├ lua_excerpt    실행 의미를 정한 **그 줄**
      └ executable     실행 구현을 등록하는가

왜 목록이 이렇게 짧은가
-----------------------
``analysis`` 의 파싱 결과를 :class:`
~engine.effect.definition.EffectDefinition` 으로 옮기는 컴파일러가 **아직
없다** (STRUCTURAL-7). 그 경계를 넘을 때 ``TEXT_DERIVED`` 차단을 다시
확인해야 하므로, 그때까지 정의는 손으로 쓴다.

14,127장 중 여기 있는 것이 전부라는 사실은 **숨길 것이 아니라 적어 둘
것**이다. 등록되지 않은 카드는 실행되지 않고, 그것이 지금의 정직한 상태다.

세 가지 상태를 구분한다 (ADR-004 · ADR-006)
-------------------------------------------
=================================  ==========================================
``TEXT_DERIVED``                    출처가 금지한다. 구현이 있어도 실행 안 함
``LUA_VERIFIED`` + 구현 없음        의미는 확인됐지만 실행할 코드가 없다
``LUA_VERIFIED`` + 등록된 구현      **이때만 실행한다**
=================================  ==========================================

이 목록은 세 번째와 두 번째를 **둘 다** 담는다. 실행할 수 없는 것을 빼
버리면 "왜 못 하는가" 가 사라지기 때문이다.

여기서 하지 않는 것
-------------------
체인을 만들지 않고, 우선권을 돌리지 않고, 트리거를 수집하지 않는다.
:class:`~engine.chain.ChainResolver` 를 만들어 주지도 않는다 — 체인 계층이
효과 계층 **위**에 있으므로, 아래에서 위를 부르면 방향이 뒤집힌다.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.condition import IsSpellTrap, PlayerRef, ZoneCountAtLeast
from engine.cost import CandidateSource, ChoiceSpec
from engine.effect.definition import (
    EffectDefinition,
    EffectDefinitionError,
    EffectDefinitionRegistry,
    EffectProvenance,
    EffectSource,
    ExecutionAvailability,
    execution_availability,
)
from engine.effect.executor import EffectExecutor, EffectImplementationRegistry
from engine.effect.journal import EventJournal
from engine.effect.operation import (
    CardOperation,
    DrawOperation,
    LifeChangeOperation,
    OperationKind,
)
from engine.effect.semantics import FIELD_ZONES, DestructionRuling
from engine.effect.target import PRIMARY_TARGET, TargetBinding, TargetSpec
from engine.ids import EffectRef
from engine.vocabulary import Zone


@dataclass(frozen=True, slots=True)
class LibraryEntry:
    """
    목록에 실린 효과 하나. **근거를 함께 들고 다닌다.**

    ``lua_excerpt`` 는 장식이 아니다 — 이 정의가 왜 그 의미인지 나중에
    누구든 원본과 대조할 수 있어야 한다. 근거 없이 적힌 정의는 검증된
    의미가 아니라 추측이다.
    """

    definition: EffectDefinition
    lua_file: str
    lua_excerpt: str
    executable: bool = False
    """실행 구현을 등록하는가. **기본값은 거짓이다** (ADR-006)."""
    note: str = ""
    """실행할 수 없다면 무엇이 없어서인가."""

    def __post_init__(self) -> None:
        provenance = self.definition.provenance
        if provenance.source is EffectSource.OFFICIAL_LUA and not self.lua_file:
            raise EffectDefinitionError(
                "공식 스크립트에서 왔다면 어느 파일인지 적어야 합니다."
            )
        if not self.executable:
            if not self.note:
                raise EffectDefinitionError(
                    "실행하지 않는 효과에는 **무엇이 없어서인지** 적어야 합니다."
                )
            return
        if provenance.is_forbidden:
            raise EffectDefinitionError(
                f"{self.effect_ref} 의 출처가 실행을 금지합니다 (ADR-004). "
                "구현을 등록할 수 없습니다."
            )
        if not provenance.verified:
            raise EffectDefinitionError(
                f"{self.effect_ref} 의 의미가 검증되지 않았습니다. "
                "검증되지 않은 것을 실행하지 않습니다."
            )
        if not self.definition.is_described:
            raise EffectDefinitionError(
                f"{self.effect_ref} 는 무엇을 하는지 적혀 있지 않은데 실행 "
                "가능으로 표시되어 있습니다. 빈 효과를 실행하면 '아무 일도 "
                "없었는데 해결됐다' 가 됩니다."
            )
        meaningless = [
            operation
            for operation in self.definition.operations
            if operation.kind is OperationKind.MOVE
        ]
        if meaningless:
            raise EffectDefinitionError(
                f"{self.effect_ref} 가 MOVE 로 적혀 있습니다. MOVE 는 **게임 "
                "의미가 없는 저수준 이동**이라 실제 카드의 효과가 될 수 "
                "없습니다 — 파괴 · 묘지로 보내기 · 버리기 · 릴리스 · 제외 · "
                "되돌리기 중 무엇인지 말해야 합니다 (ADR-002). 그 의미를 "
                "아직 옮길 수 없다면 executable=False 로 두고 이유를 "
                "적으세요."
            )

    @property
    def effect_ref(self) -> EffectRef:
        return self.definition.effect_ref

    @property
    def card_id(self) -> int:
        return self.definition.source_card_id

    def canonical_state(self) -> tuple:
        return (
            self.definition.canonical_state(),
            self.lua_file,
            self.lua_excerpt,
            self.executable,
            self.note,
        )

    def to_dict(self) -> dict:
        return {
            "definition": self.definition.to_dict(),
            "lua_file": self.lua_file,
            "lua_excerpt": self.lua_excerpt,
            "executable": self.executable,
            "note": self.note,
        }

    def describe_ko(self) -> str:
        mark = "실행 가능" if self.executable else f"실행 불가 ({self.note})"
        return f"{self.effect_ref} {mark} — {self.lua_file}"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


# ======================================================================
# 실린 효과들
# ======================================================================

POT_OF_GREED = 55144522
RAIN_OF_MERCY = 66719324
DARK_HOLE = 53129443
MYSTICAL_SPACE_TYPHOON = 5318639

#: 욕망의 항아리 — "①: 자신은 덱에서 2장 드로우한다."
#:
#: 스크립트가 애매하지 않다: ``Duel.Draw(p, d, REASON_EFFECT)`` 이고
#: ``d`` 는 ``Duel.SetTargetParam(2)`` 로 정해진 2, ``p`` 는 발동한
#: 플레이어(``tp``)다. 대상도 비용도 없다.
_POT_OF_GREED_ENTRY = LibraryEntry(
    definition=EffectDefinition(
        effect_ref=EffectRef(POT_OF_GREED, 0),
        source_card_id=POT_OF_GREED,
        operations=(DrawOperation(count=2, who=PlayerRef.CONTROLLER),),
        # ``s.target`` 의 ``Duel.IsPlayerCanDraw(tp,2)`` 중 **덱 장수 부분만**
        # 옮겼다. "드로우를 막는 효과" 는 이 엔진에 없으므로 그 부분은
        # 확인하지 않는다 — 이 조건은 필요조건이지 충분조건이 아니다.
        activation=ZoneCountAtLeast(PlayerRef.CONTROLLER, Zone.DECK, 2),
        provenance=EffectProvenance.official_lua(
            "c55144522.lua 의 s.activate 를 그대로 옮겼다."
        ),
    ),
    lua_file="c55144522.lua",
    lua_excerpt="Duel.Draw(p,d,REASON_EFFECT)  -- d = Duel.SetTargetParam(2)",
    executable=True,
)

#: 블랙홀 — "①: 필드의 몬스터를 전부 파괴한다."
#:
#: **일부러 실행하지 않는다.** 의미는 스크립트에 분명히 적혀 있지만
#: (``Duel.Destroy(sg, REASON_EFFECT)``), 옮길 수 없는 것이 둘이다.
#:
#: 1. ``OperationKind.DESTROY`` 를 실행기가 지원하지 않는다 — 파괴는 묘지로
#:    보내기와 다르고 (내성 · 대체 · "파괴되었을 때"), 그 계층이 없다.
#: 2. "필드의 몬스터 **전부**" 를 ``TargetSpec`` 이 담지 못한다
#:    (STRUCTURAL-10). 고르는 대상이 아니라 일괄 처리다.
#:
#: 그래서 하는 일을 **적지 않은 채로** 싣는다. 빼 버리면 "왜 못 하는가" 가
#: 사라진다.
_DARK_HOLE_ENTRY = LibraryEntry(
    definition=EffectDefinition(
        effect_ref=EffectRef(DARK_HOLE, 0),
        source_card_id=DARK_HOLE,
        operations=(),
        provenance=EffectProvenance.official_lua(
            "c53129443.lua 를 읽었으나 하는 일을 옮기지 못했다."
        ),
    ),
    lua_file="c53129443.lua",
    lua_excerpt="Duel.Destroy(sg,REASON_EFFECT)  -- sg = LOCATION_MZONE 전체",
    executable=False,
    note=(
        "파괴 의미(destruction semantics)와 '존 전체 일괄 처리'"
        "(STRUCTURAL-10) 가 둘 다 없다"
    ),
)

#: 은혜의 단비 — "양쪽의 플레이어는 1000 라이프 포인트를 회복한다."
#:
#: 스크립트가 두 줄이고 둘 다 상수다. 대상도 비용도 조건도 없다.
#: **두 개의 일**로 적는다 — 한 줄로 합치면 "누가 얼마를 회복했는가" 가
#: 하나로 뭉개지고, 나중에 한쪽만 막는 효과를 표현할 수 없다.
_RAIN_OF_MERCY_ENTRY = LibraryEntry(
    definition=EffectDefinition(
        effect_ref=EffectRef(RAIN_OF_MERCY, 0),
        source_card_id=RAIN_OF_MERCY,
        operations=(
            LifeChangeOperation(delta=1000, who=PlayerRef.CONTROLLER),
            LifeChangeOperation(delta=1000, who=PlayerRef.OPPONENT),
        ),
        provenance=EffectProvenance.official_lua(
            "c66719324.lua 의 s.operation 을 그대로 옮겼다."
        ),
    ),
    lua_file="c66719324.lua",
    lua_excerpt=(
        "Duel.Recover(tp,1000,REASON_EFFECT); "
        "Duel.Recover(1-tp,1000,REASON_EFFECT)"
    ),
    executable=True,
)

#: 싸이크론 — "①: 필드의 마법 / 함정 카드 1장을 대상으로 하고 발동할 수
#: 있다. 그 카드를 파괴한다."
#:
#: **이 목록에서 처음으로 대상을 지정하는 효과다.** 스크립트의 네 줄이
#: 정의의 네 부분을 그대로 정한다.
#:
#: ====================================  ==================================
#: ``EFFECT_FLAG_CARD_TARGET``            :meth:`TargetSpec.targeting`
#:                                        (고르기가 아니라 **대상 지정**)
#: ``s.filter = c:IsSpellTrap()``         ``require=IsSpellTrap()``
#: ``LOCATION_ONFIELD`` (양쪽)            ``zones=FIELD_ZONES, owner=None``
#: ``SelectTarget(..., 1, 1, ...)``       ``minimum=1, maximum=1``
#: ``..., e:GetHandler())`` (마지막 인자)  ``exclude_source=True``
#: ``Duel.Destroy(tc,REASON_EFFECT)``     ``CardOperation.destroy``
#: ====================================  ==================================
#:
#: ``tc:IsRelateToEffect(e)`` 는 **옮기지 못했다.** "대상이 발동 후에도
#: 그대로 있는가" 를 묻는 검사인데, 이 엔진에는 대상이 자리를 옮겼는지
#: 추적하는 계층이 없다 (STRUCTURAL-50). 실행 직전에
#: :class:`~engine.effect.targeting.TargetResolver` 가 다시 판정하므로 자리를
#: 벗어난 대상은 거기서 걸리지만, 그것은 ``IsRelateToEffect`` 와 **같은 검사가
#: 아니다** — 같은 자리로 돌아온 카드를 구분하지 못한다.
#:
#: ``SetHintTiming`` 과 퀵플레이 발동 타이밍은 발동 계층의 일이고 여기 없다.
#: 이 항목은 **해결될 때 무엇을 하는가**만 말한다.
_MYSTICAL_SPACE_TYPHOON_ENTRY = LibraryEntry(
    definition=EffectDefinition(
        effect_ref=EffectRef(MYSTICAL_SPACE_TYPHOON, 0),
        source_card_id=MYSTICAL_SPACE_TYPHOON,
        targets=TargetBinding.single(
            TargetSpec.targeting(
                ChoiceSpec(
                    source=CandidateSource(
                        zones=FIELD_ZONES,
                        # ``LOCATION_ONFIELD, LOCATION_ONFIELD`` — 자신과
                        # 상대 양쪽이다. 주인을 가리지 않는다.
                        owner=None,
                        require=IsSpellTrap(),
                        # ``chkc~=e:GetHandler()`` — 자기 자신은 대상이
                        # 아니다. 싸이크론도 필드의 마법 카드이므로, 이것이
                        # 없으면 자기 자신을 고를 수 있게 된다.
                        exclude_source=True,
                    ),
                    minimum=1,
                    maximum=1,
                )
            )
        ),
        operations=(CardOperation.destroy(PRIMARY_TARGET),),
        provenance=EffectProvenance.official_lua(
            "c5318639.lua 의 s.target 과 s.activate 를 옮겼다. "
            "s.activate 의 IsRelateToEffect 검사는 옮기지 못했다."
        ),
    ),
    lua_file="c5318639.lua",
    lua_excerpt=(
        "Duel.SelectTarget(tp,s.filter,tp,LOCATION_ONFIELD,LOCATION_ONFIELD,"
        "1,1,e:GetHandler()); Duel.Destroy(tc,REASON_EFFECT)  "
        "-- s.filter = c:IsSpellTrap()"
    ),
    executable=True,
)

#: 이 엔진이 들고 있는 효과 정의 전부. **이것이 전부라는 것이 사실이다.**
EFFECT_LIBRARY: tuple[LibraryEntry, ...] = (
    _POT_OF_GREED_ENTRY,
    _RAIN_OF_MERCY_ENTRY,
    _MYSTICAL_SPACE_TYPHOON_ENTRY,
    _DARK_HOLE_ENTRY,
)


# ======================================================================
# 조회 · 조립
# ======================================================================


def entry_for(
    effect_ref: EffectRef, entries: "tuple[LibraryEntry, ...]" = EFFECT_LIBRARY
) -> "LibraryEntry | None":
    """그 효과의 목록 항목. 없으면 ``None`` — 지어내지 않는다."""
    for entry in entries:
        if entry.effect_ref == effect_ref:
            return entry
    return None


def definition_registry(
    entries: "tuple[LibraryEntry, ...]" = EFFECT_LIBRARY,
) -> EffectDefinitionRegistry:
    """**모든** 항목의 정의를 담은 저장소. 실행 가능 여부와 무관하다."""
    registry = EffectDefinitionRegistry()
    for entry in entries:
        registry.register(entry.definition)
    return registry


def implementation_registry(
    entries: "tuple[LibraryEntry, ...]" = EFFECT_LIBRARY,
) -> EffectImplementationRegistry:
    """
    ``executable`` 인 항목만 담은 구현 목록.

    정의 저장소와 **다른 목록**이다 (ADR-006). 정의가 있다고 실행할 수 있는
    것이 아니다.
    """
    registry = EffectImplementationRegistry()
    for entry in entries:
        if entry.executable:
            registry.register(entry.effect_ref)
    return registry


def build_executor(
    journal: EventJournal | None = None,
    entries: "tuple[LibraryEntry, ...]" = EFFECT_LIBRARY,
    destruction: DestructionRuling | None = None,
) -> EffectExecutor:
    """
    이 목록의 구현을 아는 실행기.

    ``destruction`` 을 주지 않으면 **어떤 파괴도 일어나지 않는다.** 실행기의
    기본값이 :class:`~engine.effect.semantics.UnknownDestructionRuling` 이고,
    여기서 그것을 몰래 바꾸지 않는다 — 목록에 실렸다는 사실이 파괴 판정을
    대신하지 못한다 (Phase 2-M · STRUCTURAL-47).

    체인 해결기는 만들어 주지 않는다 — :class:`~engine.chain.ChainResolver`
    는 이 실행기와 정의 저장소를 받아 **부르는 쪽이** 만든다.
    """
    return EffectExecutor(
        lookup=implementation_registry(entries),
        journal=journal,
        destruction=destruction,
    )


def availability(
    effect_ref: EffectRef, entries: "tuple[LibraryEntry, ...]" = EFFECT_LIBRARY
) -> ExecutionAvailability:
    """
    이 목록 기준으로 그 효과를 실행할 수 있는가.

    목록에 없으면 ``NO_IMPLEMENTATION`` 이다 — "없는 카드" 와 "구현이 없는
    카드" 를 여기서 나누지 않는다. 정의 자체가 없으면 실행할 방법도 없다.
    """
    entry = entry_for(effect_ref, entries)
    if entry is None:
        return ExecutionAvailability.NO_IMPLEMENTATION
    return execution_availability(
        entry.definition, implementation_registry(entries)
    )


__all__ = [
    "LibraryEntry",
    "EFFECT_LIBRARY",
    "POT_OF_GREED",
    "RAIN_OF_MERCY",
    "DARK_HOLE",
    "MYSTICAL_SPACE_TYPHOON",
    "entry_for",
    "definition_registry",
    "implementation_registry",
    "build_executor",
    "availability",
]
