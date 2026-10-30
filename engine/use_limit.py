"""
확인된 1턴 사용 제한 — **값**이다 (Phase 6-AC).

🔴 **왜 이 모듈이 따로 있는가.**

제한은 그 **카드 텍스트의 일부**이고 판의 성질이 아니다. 그래서 효과 정의가
들고 있어야 한다 (``EffectDefinition.use_limit``). 처음 구현은 이 값을
:mod:`engine.state.use_registry` 에 두었는데, 그 모듈에는 **판의 상태**인
:class:`~engine.state.use_registry.UseRegistry` 도 있다. 정의 계층이 그
모듈을 가져오면 정의가 **판을 알게 된다** — 그것을 금지하는 감사가 이미
있었고 (``test_the_library_never_reaches_into_the_board``), 실제로 깨졌다.

그래서 **값과 기록을 가른다.**

* 여기(:mod:`engine.use_limit`): "몇 번까지인가" 와 "무엇을 기준으로
  세는가" — 카드 텍스트에서 옮긴 값, 그리고 세는 **열쇠의 모양**.
* :mod:`engine.state.use_registry`: "지금까지 몇 번 썼는가" — 판의 기록.

열쇠를 만드는 자리를 **여기 하나로** 둔다. 양쪽에 적으면 둘이 갈라지고,
"이 카드 1장" 과 "이 카드명 전체" 가 같은 제약이 되는 것이 바로 그 모듈
머리말이 경고하는 사고다. :class:`~engine.state.use_registry.UseRegistry` 의
``card_key`` · ``card_name_key`` · ``effect_key`` 는 **여기로 넘긴다**.

🔴 ``LimitScope`` 는 여기서 다시 내보낸다. :mod:`engine.effect` 는
``analysis`` 와 ``core`` 를 가져오지 않는다
(``test_the_effect_package_borrows_nothing_from_analysis_or_core`` 가 AST 로
고정한다). 그런데 범위 어휘는 ``analysis`` 가 이미 적어 두었고, 같은 열거형을
engine 쪽에 한 벌 더 만들면 둘이 갈라진다. 그래서 **이 모듈이 경계가 된다.**
"""

from __future__ import annotations

from dataclasses import dataclass

from analysis.effect_model import LimitScope

from engine.ids import EffectRef, InstanceId

#: 세 스코프의 키 타입.
PerCardKey = tuple[int, int]
"""``(player, instance_id.value)``"""
PerCardNameKey = tuple[int, int]
"""``(player, card_id)``"""
PerEffectKey = tuple[int, int, int]
"""``(player, card_id, ordinal)``"""

UseKey = PerCardKey | PerCardNameKey | PerEffectKey


def card_key(player: int, instance_id: InstanceId) -> PerCardKey:
    """``PER_CARD`` 의 열쇠 — **이 카드 1장** 기준."""
    return (player, instance_id.value)


def card_name_key(player: int, card_id: int) -> PerCardNameKey:
    """``PER_CARD_NAME`` 의 열쇠 — **같은 이름의 카드 전체** 기준."""
    return (player, card_id)


def effect_key(player: int, effect_ref: EffectRef) -> PerEffectKey:
    """``PER_EFFECT`` 의 열쇠 — **그 카드명의 이 효과** 기준."""
    return (player, effect_ref.card_id, effect_ref.ordinal)


@dataclass(frozen=True, slots=True)
class UseLimit:
    """
    **확인된** 1턴 사용 제한 하나 (Phase 6-AC).

    ``SetCountLimit(times, scope)`` 를 손으로 옮긴 값이다.
    :class:`~engine.state.use_registry.UseRegistry` 가 **횟수를 세기만** 하고
    판정하지 않으므로, "몇 번까지인가" 를 들고 있는 자리가 필요했다.

    🔴 **등록되지 않은 효과에는 제한이 없는 것처럼 동작한다.** 그것이 지금
    사실이고, 없는 것을 기본값으로 메꾸지 않는다 (ADR-006). 어느 정의가
    제한을 들고 있는지는 ``EffectDefinition.use_limit`` 이 ``None`` 인지로
    보면 된다.

    :attr:`scope` 에 ``NONE`` · ``UNKNOWN`` 을 담을 수 없다. "범위를
    모른다" 는 제한이 아니라 **제한을 읽지 못한 것**이고, 그것은 이 칸이
    ``None`` 인 것으로 표현된다 — :class:`~engine.effect.ruling.RuleFact` 가
    ``UNKNOWN`` 을 담지 못하는 것과 같은 규율이다.
    """

    scope: LimitScope
    times: int = 1

    def __post_init__(self) -> None:
        if self.scope in (LimitScope.NONE, LimitScope.UNKNOWN):
            raise ValueError(
                f"확인된 제한의 범위는 세 가지뿐입니다: {self.scope}. "
                "읽지 못한 제한은 표에 적지 않습니다 (None 이 그 뜻입니다)."
            )
        if self.times < 1:
            raise ValueError(f"사용 횟수는 1 이상입니다: {self.times}")

    def key_for(
        self, player: int, effect_ref: EffectRef, instance_id: InstanceId
    ) -> UseKey:
        """이 범위에서 이 발동이 세어지는 **열쇠**."""
        if self.scope is LimitScope.PER_CARD:
            return card_key(player, instance_id)
        if self.scope is LimitScope.PER_CARD_NAME:
            return card_name_key(player, effect_ref.card_id)
        return effect_key(player, effect_ref)

    def canonical_state(self) -> tuple:
        return ("use_limit", self.scope.value, self.times)

    def describe_ko(self) -> str:
        where = {
            LimitScope.PER_CARD: "이 카드 1장 기준",
            LimitScope.PER_CARD_NAME: "같은 이름의 카드 전체 기준",
            LimitScope.PER_EFFECT: "그 카드명의 이 효과 기준",
        }[self.scope]
        return f"1턴에 {self.times}번 ({where})"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


__all__ = [
    "LimitScope",
    "PerCardKey",
    "PerCardNameKey",
    "PerEffectKey",
    "UseKey",
    "UseLimit",
    "card_key",
    "card_name_key",
    "effect_key",
]
