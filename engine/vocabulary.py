"""
엔진 어휘 — ``ScriptConstants`` 를 Zone / Position / Phase / Reason 으로 노출한다.

**새 게임 상수를 정의하지 않는다.** EDOPro 엔진 상수 988개는 이미
``data/constants/constant.lua`` 에서 :class:`~sources.script_constants.ScriptConstants`
로 적재되고, ``analysis/`` 는 그 이름을 접두사 없이 쓴다
(``SetRange(LOCATION_HAND)`` -> ``ranges=['HAND']``).

따라서 이 모듈이 하는 일은 셋뿐이다.

1. 접두사별로 묶어서 이름 <-> 값 조회를 제공한다 (:class:`ConstantGroup`).
2. 엔진이 반드시 구분해야 하는 축(존 / 표시 형식 / 페이즈 / **효과 분류**)만
   Enum 으로 고정한다.
   Enum 멤버의 **값은 이름 문자열**이고, 게임 수치는 언제나 ``ScriptConstants``
   에서 읽는다. 수치를 이 파일에 적어두면 그 순간 두 번째 상수 체계가 된다.
3. 적재된 상수가 엔진이 기대하는 이름을 전부 갖고 있는지 검증한다
   (:meth:`EngineVocabulary.missing_names`).

``LOCATION_REASON_*`` 은 이름만 ``LOCATION_`` 으로 시작할 뿐 존이 아니라
이동 사유 플래그다. 존 어휘에서 제외한다.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Iterator

from sources.script_constants import ScriptConstants

# 이름만 LOCATION_ 으로 시작하는 비(非)존 상수.
_LOCATION_NON_ZONE_PREFIX = "LOCATION_REASON_"


class Zone(str, Enum):
    """
    카드가 있을 수 있는 위치.

    멤버 값은 ``analysis`` 가 내놓는 문자열과 정확히 같다
    (``EffectSpec.ranges`` 의 원소). 게임 수치는
    :meth:`EngineVocabulary.zone_value` 로 ``LOCATION_*`` 에서 읽는다.
    """

    DECK = "DECK"
    HAND = "HAND"
    MZONE = "MZONE"
    """메인 몬스터 존 5칸."""
    EMZONE = "EMZONE"
    """
    엑스트라 몬스터 존. **메인 몬스터 존과 다른 존이다.**

    엑스트라 덱에서 나온 몬스터가 놓이는 자리이고, 메인 몬스터 존 5칸 제한에
    포함되지 않는다. 같은 존으로 취급하면 "필드에 몬스터 6장" 같은 상태를
    표현할 수 없고, 칸 제약을 다룰 Phase 4 에서 되돌릴 수 없는 혼선이 생긴다.
    """
    SZONE = "SZONE"
    GRAVE = "GRAVE"
    REMOVED = "REMOVED"
    EXTRA = "EXTRA"
    FZONE = "FZONE"
    PZONE = "PZONE"
    OVERLAY = "OVERLAY"
    """엑시즈 소재. 플레이어 존 목록에는 들어가지 않는다 (소재는 숙주가 들고 있다)."""

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


PLAYER_ZONES: tuple[Zone, ...] = (
    Zone.DECK,
    Zone.HAND,
    Zone.EXTRA,
    Zone.MZONE,
    Zone.EMZONE,
    Zone.SZONE,
    Zone.GRAVE,
    Zone.REMOVED,
    Zone.FZONE,
    Zone.PZONE,
)
"""플레이어마다 하나씩 갖는 존. :class:`~engine.state.player.PlayerState` 가 쓴다."""


class ZoneKind(str, Enum):
    """존이 카드를 어떻게 담는가."""

    ORDERED = "ordered"
    """순서가 의미를 갖고 칸 번호가 없다 (덱 · 패 · 묘지 · 제외)."""
    SLOTTED = "slotted"
    """
    칸이 고정된 필드 존 (몬스터 존 · 마법함정 존 · 필드 존 · 펜듈럼 존 · EMZ).

    가운데 칸이 비어도 양옆이 밀려나지 않는다. Phase 1 은 칸을 **표현만** 하고
    "여기에 놓을 수 있는가" 는 판정하지 않는다 (Phase 4).
    """


class ZoneVisibility(str, Enum):
    """누가 내용을 볼 수 있는가. 향후 정보 은닉(information set)의 토대."""

    PUBLIC = "public"
    """양쪽 모두 내용을 안다 (묘지 · 필드의 앞면 카드)."""
    OWNER_ONLY = "owner_only"
    """소유자만 내용을 안다 (엑스트라 덱 · 패)."""
    HIDDEN = "hidden"
    """아무도 내용을 모른다 (덱). 장수만 공개다."""


#: 존별 칸 수. ``None`` 이면 제한 없음.
#: 룰북 근거는 ``rules/`` 의 ``RULE-ZONE-001`` 이다. 여기서는 표현만 하고
#: 넘치는지는 판정하지 않는다.
ZONE_CAPACITY: dict[Zone, int | None] = {
    Zone.DECK: None,
    Zone.HAND: None,
    Zone.EXTRA: 15,
    Zone.MZONE: 5,
    Zone.EMZONE: 1,
    Zone.SZONE: 5,
    Zone.GRAVE: None,
    Zone.REMOVED: None,
    Zone.FZONE: 1,
    Zone.PZONE: 2,
    Zone.OVERLAY: None,
}

ZONE_KIND: dict[Zone, ZoneKind] = {
    Zone.DECK: ZoneKind.ORDERED,
    Zone.HAND: ZoneKind.ORDERED,
    Zone.EXTRA: ZoneKind.ORDERED,
    Zone.GRAVE: ZoneKind.ORDERED,
    Zone.REMOVED: ZoneKind.ORDERED,
    Zone.OVERLAY: ZoneKind.ORDERED,
    Zone.MZONE: ZoneKind.SLOTTED,
    Zone.EMZONE: ZoneKind.SLOTTED,
    Zone.SZONE: ZoneKind.SLOTTED,
    Zone.FZONE: ZoneKind.SLOTTED,
    Zone.PZONE: ZoneKind.SLOTTED,
}

#: 존 자체의 공개 범위. 개별 카드의 앞면/뒷면은
#: :class:`~engine.state.card_instance.CardInstance.position` 이 따로 정한다.
ZONE_VISIBILITY: dict[Zone, ZoneVisibility] = {
    Zone.DECK: ZoneVisibility.HIDDEN,
    Zone.HAND: ZoneVisibility.OWNER_ONLY,
    Zone.EXTRA: ZoneVisibility.OWNER_ONLY,
    Zone.GRAVE: ZoneVisibility.PUBLIC,
    Zone.REMOVED: ZoneVisibility.PUBLIC,
    Zone.MZONE: ZoneVisibility.PUBLIC,
    Zone.EMZONE: ZoneVisibility.PUBLIC,
    Zone.SZONE: ZoneVisibility.PUBLIC,
    Zone.FZONE: ZoneVisibility.PUBLIC,
    Zone.PZONE: ZoneVisibility.PUBLIC,
    Zone.OVERLAY: ZoneVisibility.PUBLIC,
}


def zone_kind(zone: Zone) -> ZoneKind:
    return ZONE_KIND[zone]


def zone_capacity(zone: Zone) -> int | None:
    return ZONE_CAPACITY[zone]


def zone_visibility(zone: Zone) -> ZoneVisibility:
    return ZONE_VISIBILITY[zone]


class Position(str, Enum):
    """표시 형식. ``POS_*`` 의 이름 그대로."""

    FACEUP_ATTACK = "FACEUP_ATTACK"
    FACEDOWN_ATTACK = "FACEDOWN_ATTACK"
    FACEUP_DEFENSE = "FACEUP_DEFENSE"
    FACEDOWN_DEFENSE = "FACEDOWN_DEFENSE"
    FACEUP = "FACEUP"
    FACEDOWN = "FACEDOWN"
    ATTACK = "ATTACK"
    DEFENSE = "DEFENSE"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


class Phase(str, Enum):
    """페이즈. ``PHASE_*`` 의 이름 그대로."""

    DRAW = "DRAW"
    STANDBY = "STANDBY"
    MAIN1 = "MAIN1"
    BATTLE_START = "BATTLE_START"
    BATTLE_STEP = "BATTLE_STEP"
    DAMAGE = "DAMAGE"
    DAMAGE_CAL = "DAMAGE_CAL"
    BATTLE = "BATTLE"
    MAIN2 = "MAIN2"
    END = "END"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


class ActivationKind(str, Enum):
    """
    **효과가 어떻게 발동하는가.** 카드 종류가 아니다 (ADR-001 과 같은 구분).

    네 멤버가 공식 룰북의 효과 분류 **그대로**다
    (``data/rules/structured/sd-rulebook-en-v10.json`` 의 ``effect_types``).

    ==============  ==================  =============  ==================
    이 열거형        룰북의 분류          스펠 스피드     근거
    ==============  ==================  =============  ==================
    ``IGNITION``    Ignition Effect     1              RULE-EFFECT-002
    ``TRIGGER``     Trigger Effect      1              RULE-EFFECT-004
    ``FLIP``        Flip Effect         1              RULE-EFFECT-005
    ``QUICK``       Quick Effect        2              RULE-EFFECT-003
    ==============  ==================  =============  ==================

    ``engine`` 은 ``rules`` 를 import 하지 않고 **테스트가 대조한다** —
    ``engine/activation_timing.py`` 의 스펠 스피드 표와 같은 약속이다.

    **왜 이 축이 필요한가.** 몬스터 효과의 발동을 막아 온 이유가
    ``engine/action_validation.py`` 의 ``MONSTER_ACTIVATION_MISSING`` ·
    ``engine/activation_timing.py`` 의 ``MONSTER_CLASSIFICATION_MISSING`` 두
    문장이고, 둘 다 **"기동 · 유발 · 플립 · 유발즉시 분류가 없다"** 고 적는다.
    이 열거형이 그 빠진 분류다 — 새 어휘를 지어낸 것이 아니라, 빠졌다고
    적혀 있던 자리에 **룰북의 이름**을 넣은 것이다.

    🔴 **EDOPro 의 ``_O`` / ``_F`` 접미사를 축에 넣지 않았다.** 공식
    스크립트는 유발과 유발 즉시를 각각 둘로 더 가르지만, 그 접미사의 뜻은
    **이 저장소의 공식 자료에 근거가 없다** (Phase 3-E-31 이 *(임의)* ·
    *(강제)* 로 적었고 3-F-31 이 그 뜻풀이에 근거가 없음을 측정했다 —
    ``tests/test_effect_type_quick_audit.py`` 의 ``test_29`` · ``test_32``).
    근거 없는 구분을 축에 넣으면 그 뜻풀이가 **엔진의 규칙처럼** 굳는다.
    그래서 ``SetType(EFFECT_TYPE_TRIGGER_O)`` 도 ``TRIGGER_F`` 도 손으로
    옮길 때 :attr:`TRIGGER` 하나가 되고, **엔진은 어느 쪽이었는지 모른다.**
    강제 · 임의 축은 ``engine/trigger.py`` 의 ``TriggerRequirement`` 에
    **따로** 있고 그쪽은 ``TriggerSpec`` 이 근거를 들고 온다.

    🔴 **지속 효과(Continuous Effect)는 여기 없다.** 룰북이 그 분류에
    ``has_activation: false`` 라고 적는다 (RULE-EFFECT-001) — 발동하지 않는
    것에 "어떻게 발동하는가" 를 붙이면 그 자체가 거짓이 된다.

    🔴 **마법 · 함정의 발동(``EFFECT_TYPE_ACTIVATE``)도 여기 없다.** 그
    발동은 카드 종류로 이미 판정되고 있고 (RULE-SPELLTRAP-001 계열), 같은
    질문에 답하는 자리를 둘로 만들면 둘이 갈라진다.

    🔴 ``None`` 은 **"분류가 없는 효과" 가 아니라 "적지 않았다"** 다
    (``EffectDefinition.activation`` 과 같은 태도). 적지 않은 것을 어느
    분류로도 읽지 않는다.
    """

    IGNITION = "IGNITION"
    """기동 효과. 자신 메인 페이즈에 **선언만으로** 발동한다 (RULE-EFFECT-002)."""
    TRIGGER = "TRIGGER"
    """유발 효과. 정해진 시점이 오면 발동한다 (RULE-EFFECT-004)."""
    FLIP = "FLIP"
    """플립 효과. 뒷면이 앞면이 될 때다 (RULE-EFFECT-005)."""
    QUICK = "QUICK"
    """유발 즉시 효과. 룰북이 발동 시점을 **적지 않는다** (RULE-EFFECT-003)."""

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.value


TURN_PHASE_ORDER: tuple[Phase, ...] = (
    Phase.DRAW,
    Phase.STANDBY,
    Phase.MAIN1,
    Phase.BATTLE,
    Phase.MAIN2,
    Phase.END,
)
"""턴이 지나는 페이즈 순서. 배틀 페이즈 내부 스텝은 Phase 1 범위 밖이다."""


class ConstantGroup:
    """
    ``ScriptConstants`` 한 접두사 묶음의 읽기 전용 view.

    ``REASON_COST`` 는 ``group.value('COST')`` 또는 ``group.COST`` 로 읽는다.
    접두사를 붙여 불러도 (``'REASON_COST'``) 같은 값을 준다.
    """

    __slots__ = ("prefix", "_by_name", "_by_value")

    def __init__(self, prefix: str, values: dict[str, int]):
        self.prefix = prefix
        self._by_name: dict[str, int] = dict(values)
        # 같은 값에 이름이 여럿이면 먼저 들어온 이름을 대표로 둔다.
        self._by_value: dict[int, str] = {}
        for name, value in self._by_name.items():
            self._by_value.setdefault(value, name)

    def value(self, name: str) -> int | None:
        """``'COST'`` 또는 ``'REASON_COST'`` -> 값. 없으면 ``None``."""
        key = name.upper()
        if key.startswith(self.prefix):
            key = key[len(self.prefix):]
        return self._by_name.get(key)

    def name(self, value: int) -> str | None:
        """값 -> 접두사 없는 이름."""
        return self._by_value.get(value)

    def names(self) -> list[str]:
        return sorted(self._by_name)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and self.value(name) is not None

    def __iter__(self) -> Iterator[tuple[str, int]]:
        return iter(sorted(self._by_name.items()))

    def __len__(self) -> int:
        return len(self._by_name)

    def __getattr__(self, name: str) -> int:
        if name.startswith("_"):
            raise AttributeError(name)
        value = self._by_name.get(name)
        if value is None:
            raise AttributeError(
                f"{self.prefix}{name} 상수가 없습니다. "
                f"data/constants/constant.lua 가 적재되었는지 확인하세요."
            )
        return value

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<ConstantGroup {self.prefix}* n={len(self._by_name)}>"


class EngineVocabulary:
    """
    엔진이 쓰는 어휘 전체. ``ScriptConstants`` 를 감싸기만 하고 값을 만들지 않는다.
    """

    __slots__ = (
        "constants",
        "locations",
        "positions",
        "phases",
        "reasons",
        "statuses",
        "summon_types",
        "archetypes",
    )

    def __init__(self, constants: ScriptConstants):
        self.constants = constants
        others = constants.others
        self.locations = ConstantGroup(
            "LOCATION_",
            {
                name[len("LOCATION_"):]: value
                for name, value in others.items()
                if name.startswith("LOCATION_")
                and not name.startswith(_LOCATION_NON_ZONE_PREFIX)
            },
        )
        self.positions = ConstantGroup(
            "POS_",
            {
                name[len("POS_"):]: value
                for name, value in others.items()
                if name.startswith("POS_")
            },
        )
        self.phases = ConstantGroup(
            "PHASE_",
            {
                name[len("PHASE_"):]: value
                for name, value in others.items()
                if name.startswith("PHASE_")
            },
        )
        self.reasons = ConstantGroup(
            "REASON_",
            {
                name[len("REASON_"):]: value
                for name, value in others.items()
                if name.startswith("REASON_")
            },
        )
        self.statuses = ConstantGroup(
            "STATUS_",
            {
                name[len("STATUS_"):]: value
                for name, value in others.items()
                if name.startswith("STATUS_")
            },
        )
        self.summon_types = ConstantGroup(
            "SUMMON_TYPE_",
            {
                name[len("SUMMON_TYPE_"):]: value
                for name, value in others.items()
                if name.startswith("SUMMON_TYPE_")
            },
        )
        #: 카드군(아키타입) 이름 → 숫자 코드 (Phase 6-D).
        #:
        #: 🔴 **``others`` 가 아니라 ``constants.setcodes`` 에서 온다.**
        #: ``ScriptConstants`` 가 ``SET_*`` 를 처음부터 따로 모아 두기
        #: 때문이고, 그래서 Phase 6-C 까지 이 묶음만 비어 있었다.
        #: 값을 **만들지 않는다** — 다른 묶음들과 똑같이 감싸기만 한다.
        self.archetypes = ConstantGroup(
            "SET_",
            {
                name[len("SET_"):]: value
                for name, value in constants.setcodes.items()
                if name.startswith("SET_")
            },
        )

    # --- 적재 ---------------------------------------------------------
    @classmethod
    def load(
        cls, constant_dir: str | os.PathLike[str] | None = None
    ) -> EngineVocabulary:
        return cls(ScriptConstants.load(constant_dir))

    # --- 조회 ---------------------------------------------------------
    def zone_value(self, zone: Zone | str) -> int | None:
        """:class:`Zone` -> ``LOCATION_*`` 수치."""
        return self.locations.value(zone.value if isinstance(zone, Zone) else zone)

    def zone_from_value(self, value: int) -> Zone | None:
        name = self.locations.name(value)
        try:
            return Zone(name) if name is not None else None
        except ValueError:
            return None

    def position_value(self, position: Position | str) -> int | None:
        return self.positions.value(
            position.value if isinstance(position, Position) else position
        )

    def phase_value(self, phase: Phase | str) -> int | None:
        return self.phases.value(phase.value if isinstance(phase, Phase) else phase)

    def status_mask(self, *names: str) -> int:
        """``STATUS_*`` 이름들을 비트마스크로 합친다. 모르는 이름은 무시하지 않는다."""
        mask = 0
        for name in names:
            value = self.statuses.value(name)
            if value is None:
                raise KeyError(f"STATUS_{name.upper()} 상수가 없습니다.")
            mask |= value
        return mask

    # --- 검증 ---------------------------------------------------------
    def missing_names(self) -> list[str]:
        """
        :class:`Zone` / :class:`Position` / :class:`Phase` 멤버 중 적재된 상수에
        대응이 없는 것. 상수 파일이 없거나 오래되면 비어 있지 않게 된다.
        """
        missing: list[str] = []
        for zone in Zone:
            if self.zone_value(zone) is None:
                missing.append(f"LOCATION_{zone.value}")
        for position in Position:
            if self.position_value(position) is None:
                missing.append(f"POS_{position.value}")
        for phase in Phase:
            if self.phase_value(phase) is None:
                missing.append(f"PHASE_{phase.value}")
        return missing

    def __bool__(self) -> bool:
        return bool(self.locations) and bool(self.phases)

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return (
            f"<EngineVocabulary locations={len(self.locations)} "
            f"positions={len(self.positions)} phases={len(self.phases)} "
            f"reasons={len(self.reasons)} statuses={len(self.statuses)} "
            f"archetypes={len(self.archetypes)}>"
        )


_DEFAULT: EngineVocabulary | None = None


def default_vocabulary() -> EngineVocabulary:
    """기본 상수 디렉터리로 한 번만 적재해 재사용한다."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = EngineVocabulary.load()
    return _DEFAULT
