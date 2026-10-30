"""
엔진 조건 — 표현과 평가.

``GameStateView`` 를 읽고 ``TRUE`` / ``FALSE`` / ``UNKNOWN`` 을 돌려준다.
**상태를 바꾸지 않는다.** 조건은 질문이지 명령이 아니다.

analysis 의 조건 트리와 무엇이 다른가
--------------------------------------
``analysis.effect_model.ConditionNode`` 도 AND/OR/NOT 트리를 담지만, 그것은
**Lua 스크립트를 읽은 기록**이다. 가변 dataclass 이고 ``raw`` 원문과
``predicate`` 분류를 들고 있으며, 평가 메서드가 없다 (실제로 ``analysis``
전체에 평가기가 없다).

여기의 조건은 **실행용**이다. 불변이고, 원문을 들고 있지 않고, 관측을 받아
값을 돌려준다. 둘을 한 타입으로 합치면 "스크립트가 무엇이라고 적혀 있는가"
와 "지금 판에서 그것이 참인가" 가 섞인다.

그래서 ``analysis`` 에서 아무것도 가져오지 않는다. ``analysis.BoolOp`` 에는
``LEAF`` 멤버가 있는데, 그것은 ``ConditionNode`` 하나가 가지와 잎을 겸하기
때문이다. 엔진에서는 가지와 잎이 서로 다른 클래스이므로 그 멤버가 필요 없다.

Phase 2-B-2 에서 ``ConditionNode`` → :class:`Condition` 컴파일러를 만들 수
있다. 그때도 방향은 한쪽이다 — 분석이 실행을 낳지, 실행이 분석을 바꾸지
않는다.

없는 규칙을 지어내지 않는다
---------------------------
체인 · 트리거 · 타이밍 · 소환 절차가 아직 없다. 그런 정보가 필요한 조건은
:class:`UnimplementedRule` 로 ``UNKNOWN`` 을 돌려주고 **무엇이 없어서
모르는지**를 함께 남긴다. "모르지만 아마 참" 은 만들지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from engine.archetype import matches_setcode, validate_setcode
from engine.condition.context import ConditionContext, PlayerRef
from engine.condition.result import ConditionResult
from engine.ids import InstanceId
from engine.vocabulary import Phase, Zone

if TYPE_CHECKING:  # pragma: no cover - 타입 검사 전용
    from engine.game_state_view import CardDefinitionView, GameStateView


@dataclass(frozen=True, slots=True)
class Condition:
    """
    조건 하나. **불변**이고, 관측을 읽어 결과를 돌려준다.

    하위 클래스는 :meth:`evaluate` 와 :meth:`canonical_state` 를 채운다.
    """

    def evaluate(
        self, view: "GameStateView", context: ConditionContext
    ) -> ConditionResult:
        raise NotImplementedError  # pragma: no cover - 추상

    def canonical_state(self) -> tuple:
        raise NotImplementedError  # pragma: no cover - 추상

    def describe_ko(self) -> str:
        raise NotImplementedError  # pragma: no cover - 추상

    # ------------------------------------------------------------------
    # 왜 모르는가
    # ------------------------------------------------------------------
    def unknown_reasons(
        self, view: "GameStateView", context: ConditionContext
    ) -> tuple[str, ...]:
        """
        이 조건이 ``UNKNOWN`` 인 **이유**들. 확정된 조건이면 빈 튜플.

        가지 노드는 자식 중 실제로 결과를 좌우한 쪽만 모은다. ``FALSE AND
        UNKNOWN`` 은 이미 ``FALSE`` 이므로 이유가 없다.
        """
        if self.evaluate(view, context) is not ConditionResult.UNKNOWN:
            return ()
        return (self.describe_ko(),)

    def missing_rules(
        self, view: "GameStateView", context: ConditionContext
    ) -> tuple[str, ...]:
        """
        ``UNKNOWN`` 의 원인이 **없는 규칙 계층**이라면 그 이름들.

        비어 있으면 "정보가 없어서 모른다" 는 뜻이다. 둘은 다른 사실이고,
        앞의 것은 판이 바뀌면 풀리지만 뒤의 것은 코드가 생겨야 풀린다.
        """
        return ()

    def refusal_reasons(
        self, view: "GameStateView", context: ConditionContext
    ) -> tuple[str, ...]:
        """
        이 조건이 ``FALSE`` 인 **구체적인 이유**들 (Phase 6-AC).

        :meth:`unknown_reasons` 와 **대칭**이다. 모름에 이유를 남기면서
        거짓에는 남기지 않을 이유가 없고, 남기지 않으면 부르는 쪽이
        ``Requirement.detail`` 의 **한 문장**밖에 전할 수 없다 — 그 문장은
        종류를 말하지만 *어느 소재가 왜* 는 말하지 못한다 (실측: 소재 조건
        위반 네 가지가 모두 같은 한 줄로 보고되었다).

        🔴 **기본값이 빈 튜플이고, 그것이 기존 동작이다.** 이 값을 채우지
        않는 조건의 거절 문장은 한 글자도 바뀌지 않는다.
        """
        return ()

    def to_dict(self) -> dict:
        """JSON 으로 바로 나갈 수 있는 형태."""
        raise NotImplementedError  # pragma: no cover - 추상

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


# ======================================================================
# 상수
# ======================================================================


@dataclass(frozen=True, slots=True)
class Always(Condition):
    """
    언제나 같은 값을 돌려준다. 테스트와 자리표시에 쓴다.

    ``UNKNOWN`` 을 넣을 수도 있지만, 그럴 때는 대개
    :class:`UnimplementedRule` 이 더 정확하다 — 이유를 함께 남기기 때문이다.
    """

    value: ConditionResult = ConditionResult.TRUE

    def evaluate(self, view, context) -> ConditionResult:
        return self.value

    def canonical_state(self) -> tuple:
        return ("always", self.value.value)

    def to_dict(self) -> dict:
        return {"kind": "always", "value": self.value.value}

    def describe_ko(self) -> str:
        return {"true": "항상 참", "false": "항상 거짓", "unknown": "항상 모름"}[
            self.value.value
        ]


@dataclass(frozen=True, slots=True)
class UnimplementedRule(Condition):
    """
    **아직 판정할 규칙이 없다.** 언제나 ``UNKNOWN`` 이다.

    체인 · 트리거 · 타이밍 · 소환 절차처럼 시스템 자체가 없는 조건을
    솔직하게 표현한다. ``rule`` 에 무엇이 없는지 적어서, 나중에 어느 단계가
    이 조건을 살릴 수 있는지 추적할 수 있게 한다.
    """

    rule: str
    """없는 규칙 계층의 이름. 예: ``"chain (Phase 2-F)"``."""

    def evaluate(self, view, context) -> ConditionResult:
        return ConditionResult.UNKNOWN

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        return (f"규칙 미구현: {self.rule}",)

    def missing_rules(self, view, context) -> tuple[str, ...]:
        return (self.rule,)

    def canonical_state(self) -> tuple:
        return ("unimplemented", self.rule)

    def to_dict(self) -> dict:
        return {"kind": "unimplemented", "rule": self.rule}

    def describe_ko(self) -> str:
        return f"판정 불가({self.rule})"


# ======================================================================
# 논리 결합
# ======================================================================


@dataclass(frozen=True, slots=True)
class And(Condition):
    """
    전부 참인가. 자식이 없으면 ``TRUE`` (막을 것이 없다).

    ``FALSE`` 가 하나라도 있으면 나머지를 몰라도 ``FALSE`` 다.
    """

    children: tuple[Condition, ...]

    def __post_init__(self) -> None:
        _require_tuple(self.children, "And")

    def evaluate(self, view, context) -> ConditionResult:
        return ConditionResult.all_of(
            child.evaluate(view, context) for child in self.children
        )

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        if self.evaluate(view, context) is not ConditionResult.UNKNOWN:
            return ()
        reasons: list[str] = []
        for child in self.children:
            reasons.extend(child.unknown_reasons(view, context))
        return tuple(reasons)

    def missing_rules(self, view, context) -> tuple[str, ...]:
        if self.evaluate(view, context) is not ConditionResult.UNKNOWN:
            return ()
        rules: list[str] = []
        for child in self.children:
            rules.extend(child.missing_rules(view, context))
        return tuple(rules)

    def canonical_state(self) -> tuple:
        return ("and", tuple(c.canonical_state() for c in self.children))

    def to_dict(self) -> dict:
        return {"kind": "and", "children": [c.to_dict() for c in self.children]}

    def describe_ko(self) -> str:
        if not self.children:
            return "(조건 없음)"
        return "(" + " 그리고 ".join(c.describe_ko() for c in self.children) + ")"


@dataclass(frozen=True, slots=True)
class Or(Condition):
    """
    하나라도 참인가. 자식이 없으면 ``FALSE`` (참인 선택지가 없다).

    **단락 평가가 ``UNKNOWN`` 을 구제한다.** 하나가 확실히 참이면 나머지를
    몰라도 전체가 참이다. 이것이 없으면 조건 하나만 미해석이어도 트리 전체가
    ``UNKNOWN`` 이 된다.
    """

    children: tuple[Condition, ...]

    def __post_init__(self) -> None:
        _require_tuple(self.children, "Or")

    def evaluate(self, view, context) -> ConditionResult:
        return ConditionResult.any_of(
            child.evaluate(view, context) for child in self.children
        )

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        if self.evaluate(view, context) is not ConditionResult.UNKNOWN:
            return ()
        reasons: list[str] = []
        for child in self.children:
            reasons.extend(child.unknown_reasons(view, context))
        return tuple(reasons)

    def missing_rules(self, view, context) -> tuple[str, ...]:
        if self.evaluate(view, context) is not ConditionResult.UNKNOWN:
            return ()
        rules: list[str] = []
        for child in self.children:
            rules.extend(child.missing_rules(view, context))
        return tuple(rules)

    def canonical_state(self) -> tuple:
        return ("or", tuple(c.canonical_state() for c in self.children))

    def to_dict(self) -> dict:
        return {"kind": "or", "children": [c.to_dict() for c in self.children]}

    def describe_ko(self) -> str:
        if not self.children:
            return "(선택지 없음)"
        return "(" + " 또는 ".join(c.describe_ko() for c in self.children) + ")"


@dataclass(frozen=True, slots=True)
class Not(Condition):
    """부정. ``UNKNOWN`` 은 부정해도 ``UNKNOWN`` 이다."""

    child: Condition

    def evaluate(self, view, context) -> ConditionResult:
        return self.child.evaluate(view, context).logical_not()

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        return self.child.unknown_reasons(view, context)

    def missing_rules(self, view, context) -> tuple[str, ...]:
        return self.child.missing_rules(view, context)

    def canonical_state(self) -> tuple:
        return ("not", self.child.canonical_state())

    def to_dict(self) -> dict:
        return {"kind": "not", "child": self.child.to_dict()}

    def describe_ko(self) -> str:
        return f"아님({self.child.describe_ko()})"


def _require_tuple(children: object, name: str) -> None:
    if not isinstance(children, tuple):
        raise TypeError(
            f"{name}.children 은 tuple 이어야 합니다 — 조건은 불변입니다."
        )


# ======================================================================
# 상태 술어 — GameStateView 만 읽는다
# ======================================================================


@dataclass(frozen=True, slots=True)
class PhaseIs(Condition):
    """지금 페이즈가 이 중 하나인가. 페이즈는 언제나 공개다."""

    phases: tuple[Phase, ...]

    def __post_init__(self) -> None:
        _require_tuple(self.phases, "PhaseIs")
        if not self.phases:
            raise ValueError("PhaseIs 에는 페이즈가 최소 하나 필요합니다.")

    def evaluate(self, view, context) -> ConditionResult:
        return ConditionResult.from_bool(view.phase in self.phases)

    def canonical_state(self) -> tuple:
        return ("phase_is", tuple(p.value for p in self.phases))

    def to_dict(self) -> dict:
        return {"kind": "phase_is", "phases": [p.value for p in self.phases]}

    def describe_ko(self) -> str:
        return f"페이즈가 {'/'.join(p.value for p in self.phases)}"


@dataclass(frozen=True, slots=True)
class IsTurnPlayer(Condition):
    """이 사람의 턴인가. 턴 플레이어는 언제나 공개다."""

    who: PlayerRef = PlayerRef.CONTROLLER

    def evaluate(self, view, context) -> ConditionResult:
        return ConditionResult.from_bool(view.turn_player == self.who.resolve(context))

    def canonical_state(self) -> tuple:
        return ("is_turn_player", self.who.value)

    def to_dict(self) -> dict:
        return {"kind": "is_turn_player", "who": self.who.value}

    def describe_ko(self) -> str:
        return f"{self.who} 턴"


@dataclass(frozen=True, slots=True)
class LifePointsAtLeast(Condition):
    """라이프가 이 값 이상인가. 양쪽 라이프는 언제나 공개다."""

    who: PlayerRef
    amount: int

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError(f"라이프는 음수일 수 없습니다: {self.amount}")

    def evaluate(self, view, context) -> ConditionResult:
        player = view.player(self.who.resolve(context))
        return ConditionResult.from_bool(player.life_points >= self.amount)

    def canonical_state(self) -> tuple:
        return ("life_points_at_least", self.who.value, self.amount)

    def to_dict(self) -> dict:
        return {
            "kind": "life_points_at_least",
            "who": self.who.value,
            "amount": self.amount,
        }

    def describe_ko(self) -> str:
        return f"{self.who} LP {self.amount} 이상"


@dataclass(frozen=True, slots=True)
class ZoneCountAtLeast(Condition):
    """
    그 존에 카드가 이 수 이상 있는가.

    **가려진 존에서도 확정할 수 있다.** 장수는 상대 패에서도 공개이기
    때문이다 (``ZoneView.size`` 는 언제나 정확하다). 알 수 없는 것은
    *무엇이* 있는가이지 *몇 장*이 아니다.

    ``excluding_source`` — **묻는 카드 자신을 세지 않는다** (Phase 3-E-13)
    ------------------------------------------------------------------
    공식 스크립트가 이 예외를 ``Duel.IsExistingMatchingCard`` 의 마지막
    인자로 적는다.

        c22589918.lua (리로드) —
            ``Duel.IsExistingMatchingCard(
                Card.IsAbleToDeck, tp, LOCATION_HAND, 0, 1, e:GetHandler())``

    마지막 ``e:GetHandler()`` 가 **제외 카드**다. 즉 "패에 1장 이상" 이
    아니라 "**이 카드 말고** 패에 1장 이상" 이다.

    왜 기본값이 ``False`` 인가: 카드마다 다르다. 같은 ``ZoneCountAtLeast`` 를
    쓰는 욕망의 항아리의 조건은 자기 **덱**을 세므로 자신이 들어갈 일이
    없고, 거기에 예외를 걸면 카드가 적지 않은 것을 더하게 된다. 예외는
    **스크립트가 적어 둔 카드에만** 켠다 (Phase 2-X 의 태도와 같다).

    왜 이 필드가 필요했는가 — **STRUCTURAL-134**
    --------------------------------------------
    예외를 빼먹은 조건은 **카드가 패를 떠나기 전과 후에 답이 달라진다.**
    발동한 마법은 필드에 놓이면서 패를 떠나므로 (RULE-SPELLTRAP-002), 같은
    조건을 배치 전에 묻느냐 배치 후에 묻느냐로 답이 뒤집혔다. 뒤집히는
    조건은 **조건이 자기 자신을 셀지 말지 적지 않았다**는 뜻이고, 그것이
    STRUCTURAL-134 의 실제 내용이었다.

    ``source`` 를 **모르면 ``UNKNOWN``** 이다. 예외를 걸어 둔 조건에서 제외할
    카드를 모르면 세는 수를 모르는 것이고, 모르는 것을 참으로 읽지 않는다.
    """

    who: PlayerRef
    zone: Zone
    count: int = 1
    excluding_source: bool = False

    def __post_init__(self) -> None:
        if self.count < 0:
            raise ValueError(f"장수는 음수일 수 없습니다: {self.count}")

    def evaluate(self, view, context) -> ConditionResult:
        player = self.who.resolve(context)
        size = view.player(player).zone(self.zone).size
        if self.excluding_source:
            if context.source is None:
                # 제외할 카드를 가리키지 않았다 — 세는 수를 모른다.
                return ConditionResult.UNKNOWN
            card = view.find(context.source)
            if card is None:
                # 묻는 카드가 보이지 않는다. 세는 수를 모른다.
                return ConditionResult.UNKNOWN
            if card.zone is self.zone and card.controller == player:
                size -= 1
        return ConditionResult.from_bool(size >= self.count)

    def canonical_state(self) -> tuple:
        base = ("zone_count_at_least", self.who.value, self.zone.value, self.count)
        # 예외를 걸지 않은 조건의 정규 표현은 **그대로 둔다** — 켜지 않은
        # 카드의 직렬화가 이 필드 때문에 달라지면 안 된다.
        return base + ("excluding_source",) if self.excluding_source else base

    def to_dict(self) -> dict:
        data = {
            "kind": "zone_count_at_least",
            "who": self.who.value,
            "zone": self.zone.value,
            "count": self.count,
        }
        if self.excluding_source:
            data["excluding_source"] = True
        return data

    def describe_ko(self) -> str:
        if self.excluding_source:
            return f"{self.who} {self.zone.value} 에 이 카드 말고 {self.count}장 이상"
        return f"{self.who} {self.zone.value} 에 {self.count}장 이상"


@dataclass(frozen=True, slots=True)
class SpecialSummonPermitted(Condition):
    """
    지금 **특수 소환을 할 수 있는가** (Phase 6-AD). 소환되는 카드와 무관하다.

    판정은 :func:`~engine.summon_restriction.assess_special_summon_permission`
    하나가 한다 — :class:`~engine.action_validation._LinkMaterialsLegal` 이
    ``assess_link_materials`` 에게 묻는 것과 **같은 자리**이고 같은 이유다.

    🔴 **쓰는 자리가 둘이다** (Phase 6-AD).

    1. 링크 소환 후보의 요구 (``engine.action_validation._link_summon``) —
       링크 소환은 특수 소환이므로 금지된 판에서 허가되지 않는다.
    2. 특수 소환하는 효과의 **발동 조건** (``engine.effect.library`` 의
       「성유물－『성장』」 ②) — 공식 스크립트가 발동 조건에
       ``IsCanBeSpecialSummoned`` 를 함께 적으므로, 그 확인을 해결
       단계로만 미루면 발동 조건 검증이 빠진다.

    그래서 이 조건이 공용 어휘에 있다 — 두 자리가 **같은 판정**을 써야
    하고, 효과 정의 계층은 ``engine.action_validation`` 을 읽지 않는다.

    🔴 **이 조건이 답하는 것은 판 하나다.** "그 카드를 특수 소환할 수
    있는가" (소환 조건 · 소생 제한)는 **다른 질문**이고, 그것은
    ``RuleQuestion.MAY_BE_SPECIAL_SUMMONED`` 로 후보마다 물어진다. 둘을
    합치지 않는다.

    세 갈래가 그대로 보존된다.

    - ``ALLOWED`` → ``TRUE``
    - ``FORBIDDEN`` → ``FALSE`` (확인된 금지 — ``INVALID`` 가 된다)
    - ``UNDETERMINED`` → ``UNKNOWN`` (+ 없는 규칙 이름)

    🔴 **왜 소재 요구보다 먼저 적는가.** :meth:`ActionValidator.
    _check_requirements` 는 ``FALSE`` 를 만나면 그 자리에서 돌려주고
    ``UNKNOWN`` 은 모아 둔다. 그래서 이 요구를 앞에 두면 **확인된 금지는
    소재의 모름보다 먼저** 답하고 (규칙이 답한 것이 먼저다), **모르는
    금지는 소재의 확정 위반을 가리지 않는다** (뒤의 ``FALSE`` 가 이긴다).
    두 순서를 바꾸면 그 두 성질이 모두 깨진다.
    """

    def evaluate(self, view, context) -> ConditionResult:
        assessment = self._assess(view, context)
        if assessment.allowed:
            return ConditionResult.TRUE
        if assessment.forbidden:
            return ConditionResult.FALSE
        return ConditionResult.UNKNOWN

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        assessment = self._assess(view, context)
        if assessment.allowed or assessment.forbidden:
            return ()
        return (assessment.reason,)

    def missing_rules(self, view, context) -> tuple[str, ...]:
        assessment = self._assess(view, context)
        rule = assessment.missing_rule
        return (rule,) if rule and not assessment.forbidden else ()

    def refusal_reasons(self, view, context) -> tuple[str, ...]:
        assessment = self._assess(view, context)
        return (assessment.reason,) if assessment.forbidden else ()

    def _assess(self, view, context):
        #: 🔴 **순수 판정 모듈이다** — 등록소도 효과 계층도 읽지 않는다
        #: (그쪽 머리말의 import 약속). 지연 import 로 적는 이유는 이
        #: 모듈이 **조건 어휘**이기 때문이다 — 어휘가 판정 표를 모듈
        #: 머리에서 끌어오면 어휘를 읽는 모든 자리가 그 표를 함께 읽는다.
        from engine.summon_restriction import assess_special_summon_permission

        return assess_special_summon_permission(view, context.player)

    def canonical_state(self) -> tuple:
        return ("special_summon_permitted",)

    def to_dict(self) -> dict:
        return {"kind": "special_summon_permitted"}

    def describe_ko(self) -> str:
        return "특수 소환이 금지되지 않았다"


@dataclass(frozen=True, slots=True)
class ZoneHasFreeSlot(Condition):
    """칸 방식 존에 빈 칸이 있는가. 필드는 공개이므로 확정된다."""

    who: PlayerRef
    zone: Zone

    def evaluate(self, view, context) -> ConditionResult:
        zone_view = view.player(self.who.resolve(context)).zone(self.zone)
        capacity = zone_view.capacity
        if capacity is None:
            # 칸 수가 없는 존은 언제나 자리가 있다.
            return ConditionResult.TRUE
        return ConditionResult.from_bool(zone_view.size < capacity)

    def canonical_state(self) -> tuple:
        return ("zone_has_free_slot", self.who.value, self.zone.value)

    def to_dict(self) -> dict:
        return {
            "kind": "zone_has_free_slot",
            "who": self.who.value,
            "zone": self.zone.value,
        }

    def describe_ko(self) -> str:
        return f"{self.who} {self.zone.value} 에 빈 칸"


@dataclass(frozen=True, slots=True)
class CardIsInZone(Condition):
    """
    그 카드가 이 존에 있는가.

    ``instance`` 가 ``None`` 이면 문맥의 ``source`` 를 본다. 문맥에 그것도
    없으면 **``UNKNOWN``** 이다 — 예외를 던지지도, 거짓으로 접지도 않는다.

    보이지 않는 카드도 ``UNKNOWN`` 이다. **"안 보인다" 와 "없다" 는 다르다.**
    상대 패에 있는 카드를 두고 "묘지에 없다" 고 단정할 수는 없다.
    """

    zone: Zone
    who: PlayerRef = PlayerRef.CONTROLLER
    instance: InstanceId | None = None

    def evaluate(self, view, context) -> ConditionResult:
        target = self.instance if self.instance is not None else context.source
        if target is None:
            return ConditionResult.UNKNOWN
        card = view.find(target)
        if card is None:
            # 관측에 없다. 다른 존에 숨어 있을 수도, 아예 없을 수도 있다.
            return ConditionResult.UNKNOWN
        owner = self.who.resolve(context)
        return ConditionResult.from_bool(
            card.zone is self.zone and card.controller == owner
        )

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        target = self.instance if self.instance is not None else context.source
        if target is None:
            return ("문맥에 source 가 없어 어느 카드인지 알 수 없음",)
        if view.find(target) is None:
            return (f"{target} 가 관측에 보이지 않음 (가려진 존)",)
        return ()

    def canonical_state(self) -> tuple:
        return (
            "card_is_in_zone",
            self.zone.value,
            self.who.value,
            self.instance.value if self.instance is not None else None,
        )

    def to_dict(self) -> dict:
        data: dict = {
            "kind": "card_is_in_zone",
            "zone": self.zone.value,
            "who": self.who.value,
        }
        if self.instance is not None:
            data["instance"] = self.instance.value
        return data

    def describe_ko(self) -> str:
        which = str(self.instance) if self.instance is not None else "자신"
        return f"{which} 가 {self.who} {self.zone.value} 에 있음"


@dataclass(frozen=True, slots=True)
class CardIsFaceUp(Condition):
    """
    그 카드가 앞면인가.

    보이지 않으면 ``UNKNOWN`` 이다. 상대의 세트 카드는 자리는 보여도
    앞면/뒷면 판정은 할 수 있지만 (``CardView.face_up``), 애초에 관측에
    없는 카드는 판정할 수 없다.
    """

    instance: InstanceId | None = None

    def evaluate(self, view, context) -> ConditionResult:
        target = self.instance if self.instance is not None else context.source
        if target is None:
            return ConditionResult.UNKNOWN
        card = view.find(target)
        if card is None:
            return ConditionResult.UNKNOWN
        return ConditionResult.from_bool(card.face_up)

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        target = self.instance if self.instance is not None else context.source
        if target is None:
            return ("문맥에 source 가 없어 어느 카드인지 알 수 없음",)
        if view.find(target) is None:
            return (f"{target} 가 관측에 보이지 않음 (가려진 존)",)
        return ()

    def canonical_state(self) -> tuple:
        return (
            "card_is_face_up",
            self.instance.value if self.instance is not None else None,
        )

    def to_dict(self) -> dict:
        data: dict = {"kind": "card_is_face_up"}
        if self.instance is not None:
            data["instance"] = self.instance.value
        return data

    def describe_ko(self) -> str:
        which = str(self.instance) if self.instance is not None else "자신"
        return f"{which} 가 앞면"


# ======================================================================
# 카드 정의 술어 — 관측이 실어 준 스냅숏만 읽는다
# ======================================================================
#
# ``CardRepository`` 를 들지 않는다. 저장소는 **전체 카드**를 알고 있으므로,
# 그것을 쥔 코드는 상대의 뒷면 카드도 조회할 수 있게 된다. 정의는 오직
# ``CardView.definition`` 으로만 들어오고, 그것은 정체가 공개된 카드에만
# 붙어 있다.

#: 정의를 못 읽는 세 가지 경우와 그 이유.
_NO_CARD = "문맥에 source 가 없어 어느 카드인지 알 수 없음"
_NOT_VISIBLE = "{card} 가 관측에 보이지 않음 (가려진 존)"
_FACE_DOWN = "{card} 는 뒷면이라 정체를 모름"
_NO_DEFINITION = "{card} 의 카드 정의를 조회할 수 없음 (저장소 없음)"


def _resolve_definition(
    view: "GameStateView",
    context: ConditionContext,
    instance: InstanceId | None,
) -> tuple["CardDefinitionView | None", str]:
    """
    카드 정의를 찾는다. 못 찾으면 ``(None, 이유)``.

    세 가지 실패를 **구분해서** 알려준다. 전부 ``UNKNOWN`` 으로 이어지지만,
    부르는 쪽이 "왜 모르는가" 를 알아야 다음 단계를 정할 수 있다.
    """
    target = instance if instance is not None else context.source
    if target is None:
        return None, _NO_CARD
    card = view.find(target)
    if card is None:
        return None, _NOT_VISIBLE.format(card=target)
    if not card.is_identified:
        return None, _FACE_DOWN.format(card=target)
    if card.definition is None:
        return None, _NO_DEFINITION.format(card=target)
    return card.definition, ""


@dataclass(frozen=True, slots=True)
class IsMonster(Condition):
    """
    그 카드가 몬스터인가.

    ``instance`` 가 ``None`` 이면 문맥의 ``source`` 를 본다.
    정의를 못 읽으면 ``UNKNOWN`` 이다 — 거짓이 아니다.
    """

    instance: InstanceId | None = None

    def evaluate(self, view, context) -> ConditionResult:
        definition, _ = _resolve_definition(view, context, self.instance)
        if definition is None:
            return ConditionResult.UNKNOWN
        return ConditionResult.from_bool(definition.is_monster)

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        _, reason = _resolve_definition(view, context, self.instance)
        return (reason,) if reason else ()

    def canonical_state(self) -> tuple:
        return ("is_monster", self.instance.value if self.instance else None)

    def to_dict(self) -> dict:
        data: dict = {"kind": "is_monster"}
        if self.instance is not None:
            data["instance"] = self.instance.value
        return data

    def describe_ko(self) -> str:
        which = str(self.instance) if self.instance is not None else "자신"
        return f"{which} 가 몬스터"


@dataclass(frozen=True, slots=True)
class IsSpellTrap(Condition):
    """
    그 카드가 **마법 또는 함정**인가.

    스크립트의 ``c:IsSpellTrap()`` 을 그대로 옮긴 것이다.
    :class:`NotMonster` 와 값이 같아 보이지만 **같은 질문이 아니다** —
    저쪽은 "몬스터가 아니다" 이고 이쪽은 "마법이거나 함정이다" 다. 토큰처럼
    셋 중 어디에도 안 들어가는 것이 생기면 두 답이 갈린다. 원문이
    ``IsSpellTrap`` 이라고 적혀 있으므로 그대로 적는다.

    정의를 못 읽으면 ``UNKNOWN`` 이다 — 거짓이 아니다.
    """

    instance: InstanceId | None = None

    def evaluate(self, view, context) -> ConditionResult:
        definition, _ = _resolve_definition(view, context, self.instance)
        if definition is None:
            return ConditionResult.UNKNOWN
        return ConditionResult.from_bool(definition.is_spell or definition.is_trap)

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        _, reason = _resolve_definition(view, context, self.instance)
        return (reason,) if reason else ()

    def canonical_state(self) -> tuple:
        return ("is_spell_trap", self.instance.value if self.instance else None)

    def to_dict(self) -> dict:
        data: dict = {"kind": "is_spell_trap"}
        if self.instance is not None:
            data["instance"] = self.instance.value
        return data

    def describe_ko(self) -> str:
        which = str(self.instance) if self.instance is not None else "자신"
        return f"{which} 가 마법 / 함정"


@dataclass(frozen=True, slots=True)
class LevelAtLeast(Condition):
    """
    레벨이 이 값 이상인가.

    **엑시즈와 링크 몬스터는 ``FALSE`` 다.** 랭크와 링크 수는 레벨이 아니고,
    "레벨이 없다" 는 것은 확정된 사실이므로 ``UNKNOWN`` 이 아니다.
    마법 · 함정도 같은 이유로 ``FALSE`` 다.
    """

    level: int
    instance: InstanceId | None = None

    def __post_init__(self) -> None:
        if self.level < 0:
            raise ValueError(f"레벨은 음수일 수 없습니다: {self.level}")

    def evaluate(self, view, context) -> ConditionResult:
        definition, _ = _resolve_definition(view, context, self.instance)
        if definition is None:
            return ConditionResult.UNKNOWN
        level = definition.monster_level
        if level is None:
            # 레벨을 갖지 않는 카드다. 모르는 것이 아니라 없는 것이다.
            return ConditionResult.FALSE
        return ConditionResult.from_bool(level >= self.level)

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        _, reason = _resolve_definition(view, context, self.instance)
        return (reason,) if reason else ()

    def canonical_state(self) -> tuple:
        return (
            "level_at_least",
            self.level,
            self.instance.value if self.instance else None,
        )

    def to_dict(self) -> dict:
        data: dict = {"kind": "level_at_least", "level": self.level}
        if self.instance is not None:
            data["instance"] = self.instance.value
        return data

    def describe_ko(self) -> str:
        which = str(self.instance) if self.instance is not None else "자신"
        return f"{which} 레벨 {self.level} 이상"


@dataclass(frozen=True, slots=True)
class AttackAtLeast(Condition):
    """
    공격력이 이 값 이상인가.

    **``?`` 공격력은 ``UNKNOWN`` 이다** (실측 90장). 정의상 수치가 정해져
    있지 않으므로 "2000 이상인가" 는 참도 거짓도 아니다. 필드 위의 실제
    공격력을 알려면 지속 효과 계층이 있어야 하고, 그것은 Phase 8 이다.

    **몬스터가 아니면 ``FALSE``** 다. 공격력이 없는 것은 확정된 사실이다.

    이 검사를 ``atk`` 값만 보고 대신할 수 없다. ``cards.cdb`` 는 마법 · 함정
    4,967장에 ``atk`` 를 저장하는데, 4,919장은 0 이고 **23장은 0 이 아니다** —
    버제스토마 레안코일리아(1200) 처럼 발동하면 몬스터가 되는 함정이 몬스터
    수치를 들고 있기 때문이다. 값만 보면 함정이 "공격력 0 이상" 으로 참이 되고,
    함정 몬스터는 함정인 채로 공격력을 갖게 된다.

    (함정 몬스터가 필드에서 실제로 몬스터가 되는 것은 규칙의 문제이고,
    그 규칙 계층은 아직 없다.)

    수치가 **없는** 몬스터(링크 몬스터의 수비력)도 ``FALSE`` 다.
    """

    amount: int
    instance: InstanceId | None = None

    def evaluate(self, view, context) -> ConditionResult:
        definition, _ = _resolve_definition(view, context, self.instance)
        if definition is None:
            return ConditionResult.UNKNOWN
        if not definition.is_monster:
            # 저장된 atk 값이 무엇이든 이 카드에는 공격력이 없다.
            return ConditionResult.FALSE
        if definition.atk_is_question:
            return ConditionResult.UNKNOWN
        if not definition.has_atk:
            return ConditionResult.FALSE
        return ConditionResult.from_bool(definition.atk >= self.amount)

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        definition, reason = _resolve_definition(view, context, self.instance)
        if reason:
            return (reason,)
        assert definition is not None
        if definition.is_monster and definition.atk_is_question:
            return (f"{definition.name} 의 공격력이 ? 라 수치로 정해져 있지 않음",)
        return ()

    def canonical_state(self) -> tuple:
        return (
            "attack_at_least",
            self.amount,
            self.instance.value if self.instance else None,
        )

    def to_dict(self) -> dict:
        data: dict = {"kind": "attack_at_least", "amount": self.amount}
        if self.instance is not None:
            data["instance"] = self.instance.value
        return data

    def describe_ko(self) -> str:
        which = str(self.instance) if self.instance is not None else "자신"
        return f"{which} 공격력 {self.amount} 이상"


@dataclass(frozen=True, slots=True)
class AttributeIs(Condition):
    """
    속성이 이것인가. 이름은 ``EARTH`` · ``DARK`` 처럼 EDOPro 상수 이름을 쓴다.

    몬스터가 아니면 속성이 없으므로 ``FALSE`` 다.
    """

    attribute: str
    instance: InstanceId | None = None

    def __post_init__(self) -> None:
        if not self.attribute:
            raise ValueError("속성 이름이 비어 있습니다.")
        # 대소문자로 같은 조건이 두 표현을 갖지 않도록 정규화한다.
        object.__setattr__(self, "attribute", self.attribute.upper())

    def evaluate(self, view, context) -> ConditionResult:
        definition, _ = _resolve_definition(view, context, self.instance)
        if definition is None:
            return ConditionResult.UNKNOWN
        if definition.attribute_name is None:
            return ConditionResult.FALSE
        return ConditionResult.from_bool(definition.attribute_name == self.attribute)

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        _, reason = _resolve_definition(view, context, self.instance)
        return (reason,) if reason else ()

    def canonical_state(self) -> tuple:
        return (
            "attribute_is",
            self.attribute,
            self.instance.value if self.instance else None,
        )

    def to_dict(self) -> dict:
        data: dict = {"kind": "attribute_is", "attribute": self.attribute}
        if self.instance is not None:
            data["instance"] = self.instance.value
        return data

    def describe_ko(self) -> str:
        which = str(self.instance) if self.instance is not None else "자신"
        return f"{which} 속성이 {self.attribute}"


@dataclass(frozen=True, slots=True)
class IsSetCard(Condition):
    """
    그 카드가 이 **카드군(아키타입)** 중 하나에 속하는가 (STRUCTURAL-77).

    스크립트의 ``c:IsSetCard({SET_ORCUST, SET_WORLD_LEGACY})`` 를 그대로
    옮긴 것이다 — **목록 중 하나라도** 맞으면 참이다. 기르수(69811710)의
    ``s.tgfilter`` 가 바로 그 모양이고, 그래서 코드 하나가 아니라 묶음을
    받는다.

    판정 규칙은 :func:`~engine.archetype.matches_setcode` 한 곳에 있다.
    하위 12비트는 같아야 하고 질의한 상위 4비트는 카드 쪽에 **포함**되어야
    한다 — 「엘리멘틀 히어로」 카드는 「히어로」 카드지만 그 역은 아니다.
    근거 측정은 그 모듈의 설명에 있다.

    세 답이 **서로 다른 사실**이다
    ------------------------------
    - ``TRUE`` — 카드가 그 코드를 갖고 있다.
    - ``FALSE`` — 갖고 있지 않다. 코드를 하나도 안 가진 카드도 여기다.
      카드 14,127장 중 **6,221장(44.0%)** 이 어느 카드군에도 속하지 않고,
      그것은 ``cards.cdb`` 가 적어 둔 **사실**이므로 ``UNKNOWN`` 이 아니다.
    - ``UNKNOWN`` — **카드 정의를 못 읽었다.** 상대의 뒷면 카드 ·
      가려진 존 · 문맥에 ``source`` 가 없는 경우뿐이다
      (:func:`_resolve_definition` 의 세 갈래).

    🔴 **효과로 더해진 카드군은 보지 않는다.** 카드 자신의 텍스트가
    「룰상 "X" 카드로도 취급한다」 라고 말하는 경우는 ``cards.cdb`` 가 이미
    코드로 갖고 있다 (미라클 엑스클루더 30875635 → ``0x3008``). 그러나
    **다른 카드의 지속 효과**가 카드군을 더하는 경우는 지속 효과 계층이
    없어서 (STRUCTURAL-76) 판 어디에도 적히지 않는다. 적히는 자리가 생길
    때까지 이 조건이 보는 것은 정의뿐이고, 그때 ``UNKNOWN`` 을 더 돌려줄
    것이 아니라 **더해진 코드를 함께 넘겨야** 한다.
    """

    setcodes: tuple[int, ...]
    """
    물어볼 카드군 코드들. **적힌 순서를 그대로 둔다** — 스크립트가
    ``{SET_ORCUST, SET_WORLD_LEGACY}`` 라고 적은 순서가 설명
    (:meth:`describe_ko`)과 표현(:meth:`canonical_state`)에 그대로 남는다.
    정렬하면 「"오르페골" 또는 "성유물"」 이라는 원문의 순서를 잃는다.
    """
    instance: InstanceId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.setcodes, tuple):
            raise TypeError(
                "setcodes 는 tuple 이어야 합니다 — 조건은 불변입니다."
            )
        if not self.setcodes:
            raise ValueError(
                "카드군 코드가 최소 하나 필요합니다. 빈 목록은 '아무 카드군도'"
                " 가 되어 언제나 거짓인 조건이 됩니다."
            )
        for code in self.setcodes:
            validate_setcode(code)

    def evaluate(self, view, context) -> ConditionResult:
        definition, _ = _resolve_definition(view, context, self.instance)
        if definition is None:
            return ConditionResult.UNKNOWN
        return ConditionResult.from_bool(
            any(
                matches_setcode(definition.setcodes, code)
                for code in self.setcodes
            )
        )

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        _, reason = _resolve_definition(view, context, self.instance)
        return (reason,) if reason else ()

    def canonical_state(self) -> tuple:
        return (
            "is_set_card",
            self.setcodes,
            self.instance.value if self.instance else None,
        )

    def to_dict(self) -> dict:
        data: dict = {
            "kind": "is_set_card",
            "setcodes": [f"0x{code:x}" for code in self.setcodes],
        }
        if self.instance is not None:
            data["instance"] = self.instance.value
        return data

    def describe_ko(self) -> str:
        which = str(self.instance) if self.instance is not None else "자신"
        codes = " / ".join(f"0x{code:x}" for code in self.setcodes)
        return f"{which} 가 카드군 {codes} 에 속함"


@dataclass(frozen=True, slots=True)
class ArchetypeUnresolved(Condition):
    """
    **카드군 이름을 숫자 코드로 바꿀 수 없었다.** 언제나 ``UNKNOWN`` 이다.

    스크립트가 ``IsSetCard(SET_CENTURION)`` 이라고 적었는데 이 저장소의
    ``data/constants/archetype_setcode_constants.lua`` 에 그 상수가 없는
    경우다 (실측 3개 이름 · 50회). 그럴 때 할 수 있는 정직한 답은 하나뿐이다
    — **모른다.** 이름이 비슷한 다른 상수로 바꿔 끼우거나, 그 카드들이
    공통으로 들고 있는 코드를 역산해서 채우는 것은 **추측**이다.

    🔴 왜 :class:`UnimplementedRule` 이 아닌가 — **모르는 이유가 세 번째
    종류다**
    ----------------------------------------------------------------------
    이 계층은 원래 "모른다" 를 둘로 갈라 두었다.

    =========================  ===========================================
    ``unknown_reasons`` 만      **정보가 없어서** 모른다 — 판이 바뀌면 풀린다
                               (뒷면 카드가 뒤집히면 알 수 있다)
    ``missing_rules`` 도        **규칙 계층이 없어서** 모른다 — 코드가
                               생겨야 풀린다
    =========================  ===========================================

    카드군 이름이 상수 표에 없는 것은 **둘 다 아니다.** 판이 바뀌어도
    풀리지 않고, 코드를 더 써도 풀리지 않는다. **데이터를 갱신해야** 풀린다.
    그래서 :meth:`missing_rules` 는 **빈 튜플**이다 — 없는 규칙 계층을
    찾아 헤매게 만들지 않는다.

    어떻게 쓰이는가
    ---------------
    :func:`~engine.archetype_bridge.compile_archetype_condition` 이 목록
    일부만 해결했을 때 ``Or`` 의 한쪽에 이것을 둔다. 3치 논리가 나머지를
    맡는다.

        Or(IsSetCard((0x11b,)), ArchetypeUnresolved("CENTURION"))

        오르페골 카드      → TRUE   (해결된 쪽이 맞췄으므로 확정이다)
        그 밖의 카드       → UNKNOWN (센츄리온일 수도 있고, 알 수 없다)

    **거짓이 되지 않는다는 점이 핵심이다.** 해결하지 못한 이름을 조용히
    버리면 센츄리온 카드가 ``FALSE`` 로 판정되고, 그것은 모르는 것을
    거짓으로 접는 일이다.
    """

    name: str
    """읽은 그대로의 카드군 이름 (``SET_`` 접두사 **없이**). 출처 보존용."""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError(
                "해결하지 못한 카드군 이름을 적어야 합니다. 비워 두면 "
                "'무엇을 모르는지' 가 사라집니다."
            )

    def evaluate(self, view, context) -> ConditionResult:
        return ConditionResult.UNKNOWN

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        return (
            f"카드군 이름 SET_{self.name} 에 대응하는 숫자 코드를 "
            "상수 표에서 찾을 수 없음",
        )

    def missing_rules(self, view, context) -> tuple[str, ...]:
        """**빈 튜플이다.** 없는 것은 규칙이 아니라 데이터다 (위 설명)."""
        return ()

    def canonical_state(self) -> tuple:
        return ("archetype_unresolved", self.name)

    def to_dict(self) -> dict:
        return {"kind": "archetype_unresolved", "name": self.name}

    def describe_ko(self) -> str:
        return f"카드군 SET_{self.name} 을 숫자 코드로 바꿀 수 없음"


# ======================================================================
# 자리 · 컨트롤러 술어
# ======================================================================
#
# 검증 계층(Phase 2-B-2)이 먼저 쓰기 시작했고, 비용 · 선택 계층(Phase 2-C)이
# 후보를 거를 때도 같은 것을 쓴다. 두 곳에서 각자 만들면 같은 질문에 서로
# 다른 답이 나올 수 있으므로 조건 계층에 둔다.


@dataclass(frozen=True, slots=True)
class ControllerIs(Condition):
    """
    그 카드를 이 사람이 쥐고 있는가.

    ``controller`` 는 관측에 언제나 실려 있다 — 뒷면 카드도 자리와 주인은
    보인다. 그래서 **정체를 몰라도** 판정할 수 있다.
    """

    who: PlayerRef
    instance: InstanceId | None = None

    def evaluate(self, view, context) -> ConditionResult:
        target = self.instance if self.instance is not None else context.source
        if target is None:
            return ConditionResult.UNKNOWN
        card = view.find(target)
        if card is None:
            return ConditionResult.UNKNOWN
        return ConditionResult.from_bool(card.controller == self.who.resolve(context))

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        target = self.instance if self.instance is not None else context.source
        if target is None:
            return ("문맥에 source 가 없어 어느 카드인지 알 수 없음",)
        if view.find(target) is None:
            return (f"{target} 가 관측에 보이지 않음 (가려진 존)",)
        return ()

    def canonical_state(self) -> tuple:
        return (
            "controller_is",
            self.who.value,
            self.instance.value if self.instance is not None else None,
        )

    def to_dict(self) -> dict:
        data: dict = {"kind": "controller_is", "who": self.who.value}
        if self.instance is not None:
            data["instance"] = self.instance.value
        return data

    def describe_ko(self) -> str:
        which = str(self.instance) if self.instance is not None else "자신"
        return f"{which} 를 {self.who} 가 쥐고 있음"


@dataclass(frozen=True, slots=True)
class InAnyZone(Condition):
    """
    그 카드가 이 존들 중 하나에 있는가. 컨트롤러는 따지지 않는다.

    :class:`CardIsInZone` 은 존 하나와 주인을 함께 묻는다. 이쪽은 "필드
    위에 있는가" 처럼 **여러 존 중 하나**를 물을 때 쓴다.
    """

    zones: frozenset[Zone]
    instance: InstanceId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.zones, frozenset):
            raise TypeError("zones 는 frozenset 이어야 합니다 — 조건은 불변입니다.")
        if not self.zones:
            raise ValueError("InAnyZone 에는 존이 최소 하나 필요합니다.")

    def evaluate(self, view, context) -> ConditionResult:
        target = self.instance if self.instance is not None else context.source
        if target is None:
            return ConditionResult.UNKNOWN
        card = view.find(target)
        if card is None:
            return ConditionResult.UNKNOWN
        return ConditionResult.from_bool(card.zone in self.zones)

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        target = self.instance if self.instance is not None else context.source
        if target is None:
            return ("문맥에 source 가 없어 어느 카드인지 알 수 없음",)
        if view.find(target) is None:
            return (f"{target} 가 관측에 보이지 않음 (가려진 존)",)
        return ()

    def canonical_state(self) -> tuple:
        return (
            "in_any_zone",
            tuple(sorted(z.value for z in self.zones)),
            self.instance.value if self.instance is not None else None,
        )

    def to_dict(self) -> dict:
        data: dict = {
            "kind": "in_any_zone",
            "zones": sorted(z.value for z in self.zones),
        }
        if self.instance is not None:
            data["instance"] = self.instance.value
        return data

    def describe_ko(self) -> str:
        which = str(self.instance) if self.instance is not None else "자신"
        return f"{which} 가 {'/'.join(sorted(z.value for z in self.zones))} 에 있음"


@dataclass(frozen=True, slots=True)
class NotMonster(Condition):
    """
    몬스터가 **아닌가**.

    ``Not(IsMonster(...))`` 와 값이 같지만, 이유와 설명을 붙이기 쉬워
    따로 둔다. 정의를 못 읽으면 ``UNKNOWN`` 인 것도 그대로다.
    """

    instance: InstanceId | None = None

    def evaluate(self, view, context) -> ConditionResult:
        return IsMonster(self.instance).evaluate(view, context).logical_not()

    def unknown_reasons(self, view, context) -> tuple[str, ...]:
        return IsMonster(self.instance).unknown_reasons(view, context)

    def canonical_state(self) -> tuple:
        return ("not_monster", self.instance.value if self.instance else None)

    def to_dict(self) -> dict:
        data: dict = {"kind": "not_monster"}
        if self.instance is not None:
            data["instance"] = self.instance.value
        return data

    def describe_ko(self) -> str:
        which = str(self.instance) if self.instance is not None else "자신"
        return f"{which} 가 몬스터가 아님"
