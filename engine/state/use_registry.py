"""
사용 횟수 레지스트리.

"1턴에 1번" 이 무엇을 기준으로 하는지에 따라 실제 제약이 완전히 달라진다.
``analysis`` 가 이미 세 가지로 구분하고 있으므로(:class:`LimitScope`) 그것을
그대로 쓴다.

===============  ======================  =================================
스코프            Lua                     키
===============  ======================  =================================
PER_CARD         ``SetCountLimit(1)``    ``(player, instance_id)``
PER_CARD_NAME    ``SetCountLimit(1,id)`` ``(player, card_id)``
PER_EFFECT       ``SetCountLimit(1,..)`` ``(player, card_id, ordinal)``
===============  ======================  =================================

**세 칸을 합치지 않는다.** 키가 다르므로 한 곳에 뭉뚱그리면 "이 카드 한 장"과
"이 카드명 전체"가 같은 제약이 되어 버린다.

효과를 가리킬 때는 :class:`~engine.ids.EffectRef` 를 쓴다. ``EffectSpec.index``
(Lua 변수명 ``e1``)는 한 카드 안에서 중복되므로 (실측 4,883장) 키가 될 수 없다.

리셋 시점
---------
Phase 1 은 **언제 지워지는가를 정하지 않는다.** :meth:`UseRegistry.clear` 를
제공할 뿐이고, 턴이 넘어갈 때 부르는 것은 턴 진행 규칙이라 Phase 4 의 몫이다.
실제 유희왕에서 세 스코프의 리셋 시점이 모두 "턴 종료 시"인 것은 맞지만,
그 규칙을 여기에 넣으면 Phase 1 이 규칙을 담게 된다.
"""

from __future__ import annotations

from dataclasses import dataclass

#: 🔴 **``LimitScope`` 는 여기서 다시 내보낸다** (Phase 6-AC).
#:
#: :mod:`engine.effect` 는 ``analysis`` 와 ``core`` 를 **가져오지 않는다**
#: (``test_the_effect_package_borrows_nothing_from_analysis_or_core`` 가 AST
#: 로 고정한다). 그런데 효과 정의가 사용 제한을 들고 있어야 하고
#: (``EffectDefinition.use_limit``), 그 제한의 범위 어휘는 ``analysis`` 가
#: 이미 적어 두었다 — 같은 열거형을 engine 쪽에 한 벌 더 만들면 둘이
#: 갈라진다.
#:
#: 그래서 **이 모듈이 경계가 된다.** 여기는 ``engine.state`` 이고 처음부터
#: 그 어휘를 읽어 왔으므로 (아래 import 가 Phase 1 의 것이다), 효과 계층은
#: ``engine.state.use_registry`` 에서 받아 간다.
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


@dataclass(frozen=True, slots=True)
class UseLimit:
    """
    **확인된** 1턴 사용 제한 하나 (Phase 6-AC).

    ``SetCountLimit(times, scope)`` 를 손으로 옮긴 값이다. :class:`UseRegistry`
    가 **횟수를 세기만** 하고 판정하지 않으므로 (모듈 머리말), "몇 번까지
    인가" 를 들고 있는 자리가 필요했다. 그 자리를 효과 정의 쪽에 둔 이유는
    하나다 — 제한은 **그 카드 텍스트의 일부**이고 판의 성질이 아니다.

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
            return UseRegistry.card_key(player, instance_id)
        if self.scope is LimitScope.PER_CARD_NAME:
            return UseRegistry.card_name_key(player, effect_ref.card_id)
        return UseRegistry.effect_key(player, effect_ref)

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


class UseRegistry:
    """
    스코프별 사용 횟수.

    설계 문서는 ``set`` 세 개로 적었지만 여기서는 **횟수 카운터**다. 실측상
    ``SetCountLimit(2..4, ...)`` 를 쓰는 효과가 53건 있어서 "썼다/안 썼다"로는
    표현되지 않는다. "몇 번까지 허용인가" 를 판정하는 것은 Phase 4 이고,
    여기서는 횟수만 기록한다.
    """

    __slots__ = ("per_card", "per_card_name", "per_effect")

    def __init__(
        self,
        per_card: dict[PerCardKey, int] | None = None,
        per_card_name: dict[PerCardNameKey, int] | None = None,
        per_effect: dict[PerEffectKey, int] | None = None,
    ):
        self.per_card: dict[PerCardKey, int] = dict(per_card or {})
        self.per_card_name: dict[PerCardNameKey, int] = dict(per_card_name or {})
        self.per_effect: dict[PerEffectKey, int] = dict(per_effect or {})

    # ------------------------------------------------------------------
    # 키 만들기 — 전부 정수 튜플이라 결정론적이다
    # ------------------------------------------------------------------
    @staticmethod
    def card_key(player: int, instance_id: InstanceId) -> PerCardKey:
        return (player, instance_id.value)

    @staticmethod
    def card_name_key(player: int, card_id: int) -> PerCardNameKey:
        return (player, card_id)

    @staticmethod
    def effect_key(player: int, effect_ref: EffectRef) -> PerEffectKey:
        return (player, effect_ref.card_id, effect_ref.ordinal)

    def _table(self, scope: LimitScope) -> dict:
        try:
            return {
                LimitScope.PER_CARD: self.per_card,
                LimitScope.PER_CARD_NAME: self.per_card_name,
                LimitScope.PER_EFFECT: self.per_effect,
            }[scope]
        except KeyError:
            raise ValueError(f"기록할 수 없는 스코프입니다: {scope}") from None

    # ------------------------------------------------------------------
    # 기록 · 조회
    # ------------------------------------------------------------------
    def mark_used(self, scope: LimitScope, key: UseKey, times: int = 1) -> int:
        """사용했다고 기록하고 누적 횟수를 돌려준다."""
        table = self._table(scope)
        table[key] = table.get(key, 0) + times
        return table[key]

    def has_used(self, scope: LimitScope, key: UseKey) -> bool:
        return self.count(scope, key) > 0

    def count(self, scope: LimitScope, key: UseKey) -> int:
        return self._table(scope).get(key, 0)

    def clear(self, scope: LimitScope | None = None, key: UseKey | None = None) -> None:
        """
        지운다. 인자가 없으면 전부.

        **언제 불러야 하는지는 Phase 1 이 정하지 않는다** (모듈 설명 참고).
        """
        if scope is None:
            self.per_card.clear()
            self.per_card_name.clear()
            self.per_effect.clear()
            return
        table = self._table(scope)
        if key is None:
            table.clear()
        else:
            table.pop(key, None)

    # --- 스코프별 편의 -------------------------------------------------
    def mark_card_used(
        self, player: int, instance_id: InstanceId, times: int = 1
    ) -> int:
        return self.mark_used(
            LimitScope.PER_CARD, self.card_key(player, instance_id), times
        )

    def mark_card_name_used(self, player: int, card_id: int, times: int = 1) -> int:
        return self.mark_used(
            LimitScope.PER_CARD_NAME, self.card_name_key(player, card_id), times
        )

    def mark_effect_used(
        self, player: int, effect_ref: EffectRef, times: int = 1
    ) -> int:
        return self.mark_used(
            LimitScope.PER_EFFECT, self.effect_key(player, effect_ref), times
        )

    def card_used(self, player: int, instance_id: InstanceId) -> bool:
        return self.has_used(LimitScope.PER_CARD, self.card_key(player, instance_id))

    def card_name_used(self, player: int, card_id: int) -> bool:
        return self.has_used(
            LimitScope.PER_CARD_NAME, self.card_name_key(player, card_id)
        )

    def effect_used(self, player: int, effect_ref: EffectRef) -> bool:
        return self.has_used(
            LimitScope.PER_EFFECT, self.effect_key(player, effect_ref)
        )

    # ------------------------------------------------------------------
    # 복제 · 직렬화
    # ------------------------------------------------------------------
    def clone(self) -> "UseRegistry":
        return UseRegistry(
            per_card=self.per_card,
            per_card_name=self.per_card_name,
            per_effect=self.per_effect,
        )

    def canonical_state(self, instance_key=None) -> tuple:
        """
        키가 전부 정수 튜플이라 정렬만 하면 결정론적이다.

        다만 ``per_card`` 의 키에는 ``instance_id`` 가 들어 있어서, 그대로
        쓰면 **인스턴스가 만들어진 순서**가 해시에 새어 들어간다.
        ``instance_key`` 를 주면 그 함수로 자리 번호를 받아 바꿔 넣는다
        (:meth:`~engine.state.game_state.GameState.instance_numbering`).

        지연 번호 할당이 결정론적이도록, 바꾸기 **전에** 원래 값으로 한 번
        정렬한 뒤 넘긴다.
        """
        per_card: tuple[tuple[PerCardKey, int], ...] = tuple(
            sorted(self.per_card.items())
        )
        if instance_key is not None:
            per_card = tuple(
                sorted(
                    ((player, instance_key(InstanceId(value))), count)
                    for (player, value), count in per_card
                )
            )
        return (
            per_card,
            tuple(sorted(self.per_card_name.items())),
            tuple(sorted(self.per_effect.items())),
        )

    def __len__(self) -> int:
        return len(self.per_card) + len(self.per_card_name) + len(self.per_effect)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, UseRegistry)
            and other.canonical_state() == self.canonical_state()
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return (
            f"<UseRegistry card={len(self.per_card)} "
            f"name={len(self.per_card_name)} effect={len(self.per_effect)}>"
        )
