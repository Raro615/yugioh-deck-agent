"""
토큰의 **생명주기** (Phase 6-AF) — 만들어지고, 필드에만 있고, 떠나면 사라진다.

    CreateTokenOperation            효과가 "토큰을 만든다" 고 적는다
        ↓  EffectExecutor._plan_create_token    놓을 칸 · 금지 · 정의 확인
        ↓  EffectExecutor._apply_create_token
    create_token(...)               ← 이 파일 (판을 바꾸는 유일한 자리)
    GameState 변경 + TokenCreated + MonsterSummoned(SPECIAL, from_zone=None)

    LinkSummonExecutor.apply        소재가 필드를 떠난다
        ↓  vanish_token(...)        ← 이 파일
    GameState 변경 + TokenVanished  (**묘지로 보내지 않는다**)

🔴 **토큰을 "덱에서 꺼낸 일반 카드" 처럼 다루지 않는다**
--------------------------------------------------------
세 가지가 다르다.

1. **출발 자리가 없다.** 토큰은 덱 · 패 · 엑스트라 덱에 없다. 그래서
   :class:`~engine.summon.SummonProcedure` 를 쓸 수 없다 — 그 절차의
   ``plan_for`` 는 "그 카드가 ``from_zones`` 에 있는가" 를 먼저 묻고, 토큰은
   어디에도 없으므로 언제나 거절된다. 대신 이 파일이 **만들면서 놓는다.**
2. **덱 · 패의 장수가 변하지 않는다.** 그 사실을 :func:`create_token` 이
   놓은 뒤에 **실제로 확인한다** (확인하지 않으면 "변하지 않았다" 는 주장이
   된다).
3. **떠나면 소멸한다.** 공식 규칙이 토큰을 묘지에 남기지 않는다. 그래서
   :func:`vanish_token` 은 ``GameState.move`` 를 부르지 않고 존에서 **빼낸
   뒤 버린다** — 묘지 · 패 · 덱에 남지 않는다.

🔴 **기르수 전용 상태 엔진이 아니다.** 이 파일에 카드 ID 분기가 없다.
:data:`TOKEN_RULES` 는 "그 토큰의 공식 데이터가 무엇인가" 를 적은 표이고,
어느 효과가 그것을 쓰는지는 :mod:`engine.effect.library` 가 적는다.

무엇을 지원하지 않는가 — **이름으로 막는다**
--------------------------------------------
:data:`TOKEN_OPERATION_BLIND_SPOTS` 가 그 목록이고,
:func:`token_operation_refusal` 이 **그 조작을 실제로 거절한다.** 조용히
통과시키지 않는 것이 이 Phase 의 규율이다 (ADR-006).
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.effect.delta import (
    MonsterSummoned,
    SummonKind,
    TokenCreated,
    TokenVanished,
)
from engine.ids import InstanceId
from engine.vocabulary import Position, Zone


class TokenError(ValueError):
    """토큰 조작을 **수행할 수 없다.** 판에 손대기 전에 던진다."""


#: 토큰이 놓이는 자리. 토큰은 **메인 몬스터 존에만** 놓인다 (공식 규칙 —
#: 엑스트라 몬스터 존은 엑스트라 덱에서 나온 몬스터의 자리다).
TOKEN_ZONE: Zone = Zone.MZONE

#: 토큰이 **있을 수 있는** 자리. 여기 밖으로 나가면 소멸한다.
TOKEN_FIELD_ZONES: frozenset[Zone] = frozenset({Zone.MZONE, Zone.EMZONE})


# ======================================================================
# 지원하지 않는 토큰 조작 — **이름으로 막는다**
# ======================================================================

#: 토큰을 **덱 · 패 · 엑스트라 덱으로** 보내려는 조작.
TOKEN_TO_MAIN_DECK_RULE: str = (
    "token-to-deck-or-hand (토큰을 덱 · 패로 되돌리는 처리 — 공식 규칙은 "
    "토큰을 그 자리에 들이지 않고 소멸시키지만, 그 경로를 아직 옮기지 "
    "못했다)"
)

#: 토큰을 **엑시즈 소재 · 장착**처럼 다른 카드 아래에 두려는 조작.
TOKEN_AS_OVERLAY_RULE: str = (
    "token-as-overlay-or-equip (토큰을 엑시즈 소재 · 장착 카드로 두는 처리 "
    "— 공식 규칙은 그때도 토큰을 소멸시키지만, 그 경로를 아직 옮기지 "
    "못했다)"
)

#: 🔴 **언제나 못 보는 것.** 판정을 바꾸지 않고 적어만 둔다.
TOKEN_OPERATION_BLIND_SPOTS: tuple[str, ...] = (
    f"{TOKEN_TO_MAIN_DECK_RULE} 를 확인하지 않았습니다.",
    f"{TOKEN_AS_OVERLAY_RULE} 를 확인하지 않았습니다.",
    "토큰에 걸리는 「토큰을 특수 소환할 수 없다」 류의 카드명 · 종류 "
    "범위 제약을 확인하지 않았습니다 — 그 제약을 적는 계층이 없습니다.",
)

#: 토큰을 들일 수 **없는** 자리. :func:`token_operation_refusal` 이 본다.
TOKEN_FORBIDDEN_ZONES: dict[Zone, str] = {
    Zone.DECK: TOKEN_TO_MAIN_DECK_RULE,
    Zone.HAND: TOKEN_TO_MAIN_DECK_RULE,
    Zone.EXTRA: TOKEN_TO_MAIN_DECK_RULE,
    Zone.OVERLAY: TOKEN_AS_OVERLAY_RULE,
}


def token_operation_refusal(destination: Zone) -> "str | None":
    """
    토큰을 그 자리로 보내는 조작을 **거절해야 하는가.**

    거절할 이유가 있으면 **없는 규칙의 이름**을 돌려주고, 없으면 ``None``.

    🔴 묘지 · 제외는 여기 없다. 그 자리로 "보내는" 처리는 규칙상 일어나고
    (토큰도 파괴되고 릴리스된다), 결과가 **소멸**이라는 것이 다르다 —
    그것은 :func:`vanish_token` 이 수행하므로 거절할 것이 아니다.
    """
    return TOKEN_FORBIDDEN_ZONES.get(destination)


# ======================================================================
# 손으로 읽은 토큰 데이터
# ======================================================================


@dataclass(frozen=True, slots=True)
class TokenRule:
    """
    토큰 한 종류의 **공식 데이터**. 근거를 함께 들고 다닌다.

    :class:`~engine.link_rules.LinkMaterialRule` 과 같은 규율이다 — 근거
    없이 적힌 값은 검증된 데이터가 아니라 추측이다.

    🔴 **여기 적은 값이 판정에 쓰이지 않는다.** 판정에 쓰이는 것은
    ``CardInstance.definition`` 이 ``cards.cdb`` 에서 읽는 값이고, 이 표는
    그것과 **대조하는 기준**이다 (:func:`verify_token_definition`). 두 벌을
    두는 이유: 데이터가 바뀌면 조용히 다른 토큰이 나오는 것을 막는다.
    """

    card_id: int
    name_en: str
    constant: str
    """``TOKEN_*`` 상수 이름. 값은 상수 파일에서 읽는다."""
    setcodes: tuple[int, ...]
    race_name: str
    attribute_name: str
    level: int
    atk: int
    defense: int
    source: str
    """어느 파일의 어느 줄에서 읽었는가. **비울 수 없다.**"""

    def __post_init__(self) -> None:
        if self.card_id <= 0:
            raise ValueError(f"카드 ID 는 양수입니다: {self.card_id}")
        if not self.constant.strip() or not self.source.strip():
            raise ValueError(
                f"{self.card_id}: 상수 이름과 근거를 적어야 합니다 — 근거 "
                "없는 토큰 데이터는 추측입니다."
            )

    def describe_ko(self) -> str:
        codes = " · ".join(f"0x{c:x}" for c in self.setcodes)
        return (
            f"{self.name_en} (레벨 {self.level} · {self.attribute_name} · "
            f"{self.race_name} · {self.atk}/{self.defense} · 카드군 {codes})"
        )

    def canonical_state(self) -> tuple:
        return (
            self.card_id,
            self.setcodes,
            self.race_name,
            self.attribute_name,
            self.level,
            self.atk,
            self.defense,
        )


#: 공식 데이터를 **읽은** 토큰들. 여기 없는 토큰은 만들 수 없다 (ADR-006).
TOKEN_RULES: tuple[TokenRule, ...] = (
    #: 성유물 토큰 — ``TOKEN_WORLD_LEGACY``.
    #:
    #: 🔴 **같은 이름의 다른 ID 가 있다.** ``cards.cdb`` 에 "World Legacy
    #: Token" 이 69811711 로도 들어 있고 (실측), 그 번호는 기르수의 ID +1
    #: 이어서 "기르수가 만드는 토큰" 으로 **잘못 짚기 쉽다.** 상수 파일이
    #: 가리키는 것은 46647145 다 — 이름이 아니라 상수를 따른다.
    TokenRule(
        card_id=46647145,
        name_en="World Legacy Token",
        constant="TOKEN_WORLD_LEGACY",
        setcodes=(0xFE,),
        race_name="MACHINE",
        attribute_name="DARK",
        level=1,
        atk=0,
        defense=0,
        source=(
            "data/constants/card_counter_constants.lua 의 "
            "TOKEN_WORLD_LEGACY=46647145 와 data/cards.cdb 의 46647145 "
            "(setcode=254=0xfe · type=16401=MONSTER|NORMAL|TOKEN · atk=0 · "
            "def=0 · level=1 · race=32=MACHINE · attribute=32=DARK). "
            "ProjectIgnis/CardScripts 에 official/c46647145.lua 가 없다 "
            "(실측 HTTP 404) — 토큰에는 카드 텍스트가 없다."
        ),
    ),
)

_RULES_BY_CARD: dict[int, TokenRule] = {rule.card_id: rule for rule in TOKEN_RULES}
if len(_RULES_BY_CARD) != len(TOKEN_RULES):  # pragma: no cover - 방어
    raise ValueError("같은 토큰을 두 줄로 적었습니다.")


def token_rule_for(card_id: "int | None") -> "TokenRule | None":
    """그 토큰의 공식 데이터. **적히지 않았으면 ``None``** (ADR-006)."""
    if card_id is None:
        return None
    return _RULES_BY_CARD.get(card_id)


def verify_token_definition(rule: TokenRule, definition) -> "str | None":
    """
    카드 데이터가 표와 **같은가.** 어긋나면 사람이 읽는 한 줄, 같으면 ``None``.

    정의를 읽을 수 없으면 그것도 어긋남으로 적는다 — 무엇을 만드는지 모르는
    채로 개체를 놓지 않는다.
    """
    if definition is None:
        return f"{rule.card_id} 의 카드 정의를 읽을 수 없습니다."
    checks = (
        ("토큰 여부", True, bool(getattr(definition, "is_token", False))),
        ("카드군", rule.setcodes, tuple(definition.setcodes)),
        ("종족", rule.race_name, definition.race_name),
        ("속성", rule.attribute_name, definition.attribute_name),
        ("레벨", rule.level, definition.level),
        ("공격력", rule.atk, definition.atk),
        ("수비력", rule.defense, definition.defense),
    )
    for label, expected, found in checks:
        if expected != found:
            return (
                f"{rule.card_id} 의 {label} 이 표와 다릅니다 "
                f"(표 {expected!r} · 데이터 {found!r})."
            )
    return None


# ======================================================================
# 판정 — 토큰인가
# ======================================================================
def is_token(card) -> "bool | None":
    """
    그 개체가 토큰인가. **읽을 수 없으면 ``None``** 이다.

    🔴 ``None`` 과 ``False`` 를 ``if not`` 으로 합치지 않는다 — "정의를 못
    읽었다" 와 "토큰이 아니다" 는 다른 사실이고, 앞의 것을 뒤의 것으로
    읽으면 소멸해야 할 토큰이 묘지에 남는다.
    """
    if card is None:
        return None
    try:
        definition = card.definition
    except (RuntimeError, KeyError):
        return None
    if definition is None:
        return None
    return bool(getattr(definition, "is_token", False))


# ======================================================================
# 만들기 — 여기서만 판이 바뀐다
# ======================================================================


@dataclass(frozen=True, slots=True)
class TokenPlan:
    """
    토큰 하나를 **어디에 어떻게** 놓을 것인가. 아직 아무것도 만들지 않았다.

    :class:`~engine.summon.SummonPlacement` 와 같은 자리의 값이고, 다른 것은
    :attr:`card` 가 **없다**는 점이다 — 개체는 적용 단계에서 생긴다.
    """

    rule: TokenRule
    owner: int
    """토큰의 주인. **놓이는 쪽**이다 (토큰은 덱에서 오지 않는다)."""
    controller: int
    summoner: int
    """그 효과를 해결한 플레이어. :attr:`owner` 와 다를 수 있다."""
    slot: int
    position: Position
    creator: "InstanceId | None" = None
    creator_card_id: "int | None" = None

    def __post_init__(self) -> None:
        for name in ("owner", "controller", "summoner"):
            if getattr(self, name) not in (0, 1):
                raise ValueError(
                    f"{name} 는 0 또는 1 입니다: {getattr(self, name)}"
                )
        if self.slot < 0:
            raise ValueError(f"칸 번호는 음수일 수 없습니다: {self.slot}")

    def canonical_state(self) -> tuple:
        return (
            self.rule.card_id,
            self.owner,
            self.controller,
            self.summoner,
            self.slot,
            self.position.value,
        )

    def describe_ko(self) -> str:
        return (
            f"P{self.summoner} 가 {self.rule.name_en} 을 P{self.controller} 의 "
            f"{TOKEN_ZONE.value}[{self.slot}] 에 {self.position.value} 로"
        )


def plan_token(
    state,
    rule: TokenRule,
    *,
    controller: int,
    summoner: int,
    position: Position,
    creator: "InstanceId | None" = None,
    creator_card_id: "int | None" = None,
    taken: "dict[int, set[int]] | None" = None,
) -> TokenPlan:
    """
    놓을 칸을 정한다. **판을 바꾸지 않는다.**

    ``taken`` 은 "같은 처리에서 이미 예약한 칸" 이다 — 한 해결이 토큰 두
    장을 만들 때 두 번째가 첫 번째의 칸을 다시 고르지 않게 한다 (판은 아직
    바뀌지 않았으므로 판만 보면 같은 칸이 비어 있다).

    **칸을 고르지 않는다** — 가장 작은 빈 칸을 쓴다 (STRUCTURAL-41). 그것이
    규칙이어서가 아니라 고르는 계층이 아직 없어서이고, 다른 소환 절차가
    쓰는 방식을 그대로 쓴다.
    """
    if controller not in (0, 1) or summoner not in (0, 1):
        raise TokenError(f"플레이어는 0 또는 1 입니다: {controller} / {summoner}")
    reserved = set((taken or {}).get(controller, ()))
    free = [
        index
        for index in state.zone(controller, TOKEN_ZONE).free_slots()
        if index not in reserved
    ]
    if not free:
        raise TokenError(
            f"P{controller} 의 {TOKEN_ZONE.value} 에 빈 칸이 없습니다."
        )
    return TokenPlan(
        rule=rule,
        #: 🔴 **놓이는 쪽이 주인이다.** 토큰은 어느 덱에서도 오지 않으므로
        #: "원래 주인" 이라는 것이 없고, 공식 규칙은 그것을 그 필드의
        #: 플레이어의 것으로 다룬다.
        owner=controller,
        controller=controller,
        summoner=summoner,
        slot=free[0],
        position=position,
        creator=creator,
        creator_card_id=creator_card_id,
    )


def create_token(
    state, plan: TokenPlan
) -> "tuple[object, TokenCreated, MonsterSummoned]":
    """
    계획대로 개체를 **만들어 놓고** 두 변화를 돌려준다.

    순서가 뜻을 가진다 — 덱 · 패의 장수를 **먼저** 읽고, 놓은 뒤에 다시
    읽어 **변하지 않았음을 확인한다.** 확인하지 않으면 "토큰은 덱에서 오지
    않는다" 는 주장이 되고, 주장은 사실이 아니다.
    """
    before = _counts(state)
    instance = state.create_instance(
        plan.rule.card_id,
        owner=plan.owner,
        zone=TOKEN_ZONE,
        position=plan.position,
        index=plan.slot,
    )
    if plan.controller != plan.owner:  # pragma: no cover - 지금 경로는 같다
        instance.set_controller(plan.controller, remember_previous=False)

    landed = state.zone(plan.controller, TOKEN_ZONE).slot(plan.slot)
    if landed is not instance:
        raise TokenError(
            f"토큰이 {TOKEN_ZONE.value}[{plan.slot}] 에 놓이지 않았습니다."
        )
    if instance.position is not plan.position:  # pragma: no cover - 방어
        raise TokenError(f"토큰의 표시 형식이 {instance.position} 입니다.")
    after = _counts(state)
    if before != after:  # pragma: no cover - 방어선
        raise TokenError(
            "토큰을 만들었는데 덱 · 패 · 엑스트라 덱의 장수가 달라졌습니다: "
            f"{before} → {after}. 토큰은 어느 자리에서도 오지 않습니다."
        )

    created = TokenCreated(
        card=instance.instance_id,
        card_id=plan.rule.card_id,
        owner=plan.owner,
        controller=plan.controller,
        summoner=plan.summoner,
        creator=plan.creator,
        creator_card_id=plan.creator_card_id,
    )
    summoned = MonsterSummoned(
        #: 🔴 **특수 소환이다** (공식 스크립트의 ``SpecialSummonStep``).
        summon=SummonKind.SPECIAL,
        card=instance.instance_id,
        #: 🔴 ``MonsterSummoned.player`` 는 **컨트롤러**다 (그쪽 칸의 설명 —
        #: "소환한 사람. 소환된 몬스터의 컨트롤러다"). 토큰에서는 그 둘이
        #: 갈릴 수 있으므로 (``SpecialSummonStep(tk2,0,tp,1-tp,…)``),
        #: **해결한 플레이어는 여기 적지 않고** :class:`TokenCreated` 의
        #: ``summoner`` 가 들고 있다. 한 칸에 두 사실을 담지 않는다.
        player=plan.controller,
        owner=plan.owner,
        #: 🔴 **어느 자리에서도 오지 않았다** (``MonsterSummoned.from_zone``).
        from_zone=None,
        to_zone=TOKEN_ZONE,
        to_index=plan.slot,
        position=plan.position,
    )
    return instance, created, summoned


def vanish_token(state, instance: InstanceId, reason: str = "") -> TokenVanished:
    """
    토큰을 필드에서 빼내 **소멸시킨다.** 어느 존에도 넣지 않는다.

    🔴 ``GameState.move`` 를 부르지 않는다. 그 함수는 **목적지가 있는**
    이동이고, 토큰의 소멸에는 목적지가 없다 — 묘지로 보낸 뒤 지우면 그
    사이에 묘지에 있었다는 사실이 판에 남는다 (그리고 그 사실을 읽는
    계층이 생기면 거짓 유발이 된다).
    """
    card = state.find_instance(instance)
    if card is None:
        raise TokenError(f"{instance} 를 이 판에서 찾을 수 없습니다.")
    token = is_token(card)
    if token is None:
        raise TokenError(
            f"{instance} 의 카드 정의를 읽을 수 없어 토큰인지 알 수 없습니다 "
            "— 모르는 개체를 소멸시키지 않습니다."
        )
    if not token:
        raise TokenError(f"{instance} 는 토큰이 아닙니다.")
    container = state.locate(instance)
    if container is None or container.zone not in TOKEN_FIELD_ZONES:
        where = container.zone.value if container is not None else "어디에도"
        raise TokenError(
            f"{instance} 가 필드에 없습니다 (현재 {where}) — 필드를 떠나는 "
            "것이 소멸의 조건입니다."
        )
    from_zone = container.zone
    owner, controller = card.owner, card.controller
    container.remove(card)
    if state.find_instance(instance) is not None:  # pragma: no cover - 방어선
        raise TokenError(
            f"{instance} 가 아직 판에 남아 있습니다 — 토큰은 어느 존에도 "
            "남지 않습니다."
        )
    return TokenVanished(
        card=instance,
        card_id=card.card_id,
        owner=owner,
        controller=controller,
        from_zone=from_zone,
        reason=reason,
    )


def _counts(state) -> tuple[tuple[int, int, int], ...]:
    """덱 · 패 · 엑스트라 덱의 장수. :func:`create_token` 이 대조한다."""
    return tuple(
        (
            len(state.zone(player, Zone.DECK)),
            len(state.zone(player, Zone.HAND)),
            len(state.zone(player, Zone.EXTRA)),
        )
        for player in (0, 1)
    )


__all__ = [
    "TOKEN_AS_OVERLAY_RULE",
    "TOKEN_FIELD_ZONES",
    "TOKEN_FORBIDDEN_ZONES",
    "TOKEN_OPERATION_BLIND_SPOTS",
    "TOKEN_RULES",
    "TOKEN_TO_MAIN_DECK_RULE",
    "TOKEN_ZONE",
    "TokenError",
    "TokenPlan",
    "TokenRule",
    "create_token",
    "is_token",
    "plan_token",
    "token_operation_refusal",
    "token_rule_for",
    "vanish_token",
    "verify_token_definition",
]
