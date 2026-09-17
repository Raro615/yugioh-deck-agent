"""
효과 분석 데이터 모델.

검색 계층(:mod:`core.card_search`)은 "이 카드가 조건에 맞는가"를 판단한다.
이 계층은 한 단계 더 들어가 "이 효과가 무엇을, 어디에서, 어디로, 어떤 비용으로
옮기는가"를 구조화한다. 나중에 콤보를 탐색하려면 이 전이 정보가 필요하다.

설계 원칙
---------
1. **기존 Lua 파싱 결과를 재사용한다.** :class:`~core.card_model.EffectSpec` 이
   이미 효과 블록 단위로 묶어 둔 정보를 출발점으로 쓴다.
2. **추론하지 않는다.** 스크립트에서 읽어낼 수 없는 것은 비워 두거나
   ``unparsed`` 에 원문 그대로 남긴다. 그럴듯한 값을 지어내지 않는다.
3. **원본을 버리지 않는다.** 모든 분석 결과는 ``raw`` 로 원래 효과 블록을 가리킨다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from core.card_model import EffectSpec


class ActionKind(str, Enum):
    """효과가 실제로 하는 일. Lua 의 ``Duel.*`` 호출에서 유도한다."""

    SPECIAL_SUMMON = "special_summon"
    NORMAL_SUMMON = "normal_summon"
    TO_HAND = "to_hand"
    """패로 보낸다. 덱에서 가져오면 서치가 된다."""
    TO_GRAVE = "to_grave"
    TO_DECK = "to_deck"
    BANISH = "banish"
    DESTROY = "destroy"
    DRAW = "draw"
    DISCARD = "discard"
    RELEASE = "release"
    NEGATE = "negate"
    DAMAGE = "damage"
    RECOVER = "recover"
    POSITION = "position"
    EQUIP = "equip"
    TOKEN = "token"
    CONTROL = "control"
    ATK_DEF_CHANGE = "atk_def_change"
    UNKNOWN = "unknown"
    """무엇을 하는지 구조화하지 못했다. ``raw`` 에 원문이 남는다."""


#: 액션이 카드를 어디로 옮기는지. 이동이 아니면 ``None``.
ACTION_DESTINATION: dict[ActionKind, str | None] = {
    ActionKind.SPECIAL_SUMMON: "MZONE",
    ActionKind.NORMAL_SUMMON: "MZONE",
    ActionKind.TO_HAND: "HAND",
    ActionKind.TO_GRAVE: "GRAVE",
    ActionKind.TO_DECK: "DECK",
    ActionKind.BANISH: "REMOVED",
    ActionKind.DESTROY: "GRAVE",
    ActionKind.DRAW: "HAND",
    ActionKind.DISCARD: "GRAVE",
    ActionKind.RELEASE: "GRAVE",
    ActionKind.EQUIP: "SZONE",
    ActionKind.TOKEN: "MZONE",
}


class CostKind(str, Enum):
    """발동 비용."""

    SELF_BANISH = "self_banish"
    SELF_DISCARD = "self_discard"
    SELF_TRIBUTE = "self_tribute"
    SELF_TO_GRAVE = "self_to_grave"
    SELF_TO_DECK = "self_to_deck"
    SELF_TO_HAND = "self_to_hand"
    SELF_TO_EXTRA = "self_to_extra"
    SELF_REVEAL = "self_reveal"
    DETACH = "detach"
    """엑시즈 소재를 뗀다."""
    DISCARD = "discard"
    RELEASE = "release"
    PAY_LP = "pay_lp"
    SEND_DECK_TO_GRAVE = "send_deck_to_grave"
    BANISH = "banish"
    TO_DECK = "to_deck"
    RETURN_TO_HAND = "return_to_hand"
    """자신 필드의 카드를 패로 되돌린다."""
    REMOVE_COUNTER = "remove_counter"
    NONE = "none"
    """비용 함수는 있으나 자원을 소모하지 않는다 (표식만 남기거나 제약을 건다).
    '읽지 못함'과 구분하기 위해 따로 둔다."""
    UNKNOWN = "unknown"
    """비용이 있다는 것만 알고 내용은 구조화하지 못했다."""


@dataclass(slots=True)
class CardConstraint:
    """
    '어떤 카드'인지를 나타내는 조건. Lua 필터 함수의 ``Card.Is*`` 호출에서 읽는다.

    모든 필드는 선택적이다. 읽어내지 못한 조건은 :attr:`raw_predicates` 에
    원문 그대로 남는다.
    """

    races: list[int] = field(default_factory=list)
    attributes: list[int] = field(default_factory=list)
    levels: list[int] = field(default_factory=list)
    level_max: int | None = None
    level_min: int | None = None
    card_types: list[str] = field(default_factory=list)
    """TYPE_* 상수 이름 (접두사 제외). 예: ['MONSTER', 'TUNER']"""
    setcodes: list[str] = field(default_factory=list)
    """SET_* 카드군 이름 (접두사 제외). 예: ['ORCUST']"""
    card_codes: list[int] = field(default_factory=list)
    """특정 카드 ID 지정."""
    excluded_card_codes: list[int] = field(default_factory=list)
    """``not c:IsCode(id)`` 처럼 제외되는 카드 ID."""
    raw_predicates: list[str] = field(default_factory=list)
    """구조화하지 못한 조건 원문."""

    def is_empty(self) -> bool:
        return not any(
            (
                self.races,
                self.attributes,
                self.levels,
                self.level_max is not None,
                self.level_min is not None,
                self.card_types,
                self.setcodes,
                self.card_codes,
            )
        )

    def describe_ko(self) -> str:
        from core import constants as C

        parts: list[str] = []
        for bit in self.races:
            parts.append(f"{C.RACE_KO.get(bit, '?')}족")
        for bit in self.attributes:
            parts.append(f"{C.ATTRIBUTE_KO.get(bit, '?')}속성")
        if self.levels:
            parts.append("레벨 " + "/".join(str(v) for v in self.levels))
        if self.level_max is not None:
            parts.append(f"레벨 {self.level_max} 이하")
        if self.level_min is not None:
            parts.append(f"레벨 {self.level_min} 이상")
        for name in self.setcodes:
            parts.append(f"{name} 카드군")
        for code in self.card_codes:
            parts.append(f"카드 {code}")
        parts.extend(self.card_types)
        return ", ".join(parts) if parts else "(조건 미상)"


class ConditionKind(str, Enum):
    """발동 조건의 종류. Lua 조건 함수의 호출에서 유도한다."""

    REQUIRES_CARD = "requires_card"
    """특정 조건의 카드가 어떤 위치에 존재해야 한다."""
    ZONE_AVAILABLE = "zone_available"
    """몬스터 존 등에 빈 자리가 있어야 한다."""
    CARD_COUNT = "card_count"
    """패/덱/필드의 매수 조건."""
    TURN_PLAYER = "turn_player"
    """자신 턴 / 상대 턴."""
    PHASE = "phase"
    LIFE_POINTS = "life_points"
    CHAIN = "chain"
    """체인 상태 (무효화 가능 여부, 체인 위치 등)."""
    BATTLE = "battle"
    """공격 선언·전투 관련."""
    PLAYER_AFFECTED = "player_affected"
    """플레이어가 특정 효과의 영향을 받고 있는지."""
    UNKNOWN = "unknown"


class LimitScope(str, Enum):
    """
    발동 제한의 범위. "1턴에 1번"이 무엇을 기준으로 하는지에 따라 실제 제약이
    완전히 달라지므로 구분한다.
    """

    NONE = "none"
    PER_CARD = "per_card"
    """``SetCountLimit(1)`` — 이 카드 1장 기준."""
    PER_CARD_NAME = "per_card_name"
    """``SetCountLimit(1,id)`` — 같은 이름의 카드 전체 기준."""
    PER_EFFECT = "per_effect"
    """``SetCountLimit(1,{id,n})`` — 그 카드명의 특정 효과 기준."""
    UNKNOWN = "unknown"


class BoolOp(str, Enum):
    """조건 트리의 노드 종류."""

    AND = "and"
    OR = "or"
    NOT = "not"
    LEAF = "leaf"


@dataclass(slots=True)
class ConditionNode:
    """
    조건식의 논리 구조를 담는 트리.

    OR 를 AND 로 평탄화하면 "둘 중 하나면 된다"가 "둘 다 필요하다"로 바뀐다.
    콤보 탐색이 성립하지 않는 경로를 성립한다고 보게 되므로 구조를 보존한다.

    leaf 는 :class:`ActivationRequirement` 를 가지되, 분류하지 못한 leaf 는
    ``requirement=None`` 으로 두고 :attr:`raw` 에 원문만 남긴다. 논리 구조는
    살리면서 의미는 지어내지 않기 위해서다.
    """

    op: BoolOp
    children: list["ConditionNode"] = field(default_factory=list)
    requirement: "ActivationRequirement | None" = None
    """굵은 분류(ConditionKind). 평면 목록과 호환을 위해 유지한다."""
    predicate: "object | None" = None
    """leaf 의 세부 의미 (:class:`~analysis.predicate_model.ConditionPredicate`).
    해석하지 못한 leaf 에도 UNKNOWN 술어가 붙어 원문이 보존된다."""
    raw: str = ""

    @property
    def is_alternative(self) -> bool:
        """이 노드의 자식들이 '둘 중 하나'인가 (AND 가 아니라 OR 인가)."""
        return self.op is BoolOp.OR

    def leaves(self) -> list["ConditionNode"]:
        """트리의 모든 leaf 를 왼쪽부터 순서대로."""
        if self.op is BoolOp.LEAF:
            return [self]
        found: list[ConditionNode] = []
        for child in self.children:
            found.extend(child.leaves())
        return found

    def depth(self) -> int:
        if not self.children:
            return 1
        return 1 + max(child.depth() for child in self.children)

    def count_ops(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        stack = [self]
        while stack:
            node = stack.pop()
            counts[node.op.value] = counts.get(node.op.value, 0) + 1
            stack.extend(node.children)
        return counts

    @property
    def is_structured(self) -> bool:
        """leaf 를 하나라도 분류했는가."""
        return any(leaf.requirement is not None for leaf in self.leaves())

    def describe_ko(self) -> str:
        if self.op is BoolOp.LEAF:
            if self.requirement is not None:
                # 부정은 상위 NOT 노드가 표현한다. 여기서 또 붙이면 중복된다.
                return self.requirement.describe_ko(include_negation=False)
            kind = getattr(getattr(self.predicate, "kind", None), "value", None)
            if kind and kind != "unknown":
                return self.predicate.describe_ko().removeprefix("아님: ")
            return f"?({self.raw.strip()[:40]})"
        if self.op is BoolOp.NOT:
            inner = self.children[0].describe_ko() if self.children else "?"
            return f"아님({inner})"
        joiner = " 또는 " if self.op is BoolOp.OR else " 그리고 "
        parts = [child.describe_ko() for child in self.children]
        return "(" + joiner.join(parts) + ")"


@dataclass(slots=True)
class ActivationLimit:
    count: int | None = None
    scope: LimitScope = LimitScope.NONE
    raw: str | None = None

    def describe_ko(self) -> str:
        if self.count is None:
            return "제한 없음"
        labels = {
            LimitScope.PER_CARD: "이 카드",
            LimitScope.PER_CARD_NAME: "이 카드명",
            LimitScope.PER_EFFECT: "이 효과",
            LimitScope.UNKNOWN: "범위 미상",
        }
        return f"{labels.get(self.scope, '')} 1턴 {self.count}회"


@dataclass(slots=True)
class ActivationRequirement:
    """발동에 필요한 상태 하나."""

    kind: ConditionKind
    locations: list[str] = field(default_factory=list)
    player: str | None = None
    """'self' | 'opponent' | 'both'"""
    min_count: int | None = None
    faceup: bool = False
    negated: bool = False
    """``not ...`` 으로 감싸인 조건. 놓치면 의미가 정반대가 된다."""
    constraint: CardConstraint | None = None
    raw: str = ""

    def describe_ko(self, include_negation: bool = True) -> str:
        """
        Args:
            include_negation: 거짓이면 부정 표시를 빼고 조건 내용만 쓴다.
                조건 트리에서는 NOT 노드가 부정을 표현하므로, leaf 가 다시
                부정을 붙이면 "아님(아니어야 함: ...)" 처럼 두 번 나온다.
        """
        who = {"self": "자신", "opponent": "상대", "both": "양쪽"}.get(
            self.player or "", ""
        )
        where = "/".join(self.locations)
        negated = self.negated and include_negation
        if self.kind is ConditionKind.REQUIRES_CARD:
            what = self.constraint.describe_ko() if self.constraint else "카드"
            face = "앞면 " if self.faceup else ""
            text = f"{who} {where}에 {face}{what} {self.min_count or 1}장"
            return ("없어야 함: " if negated else "필요: ") + text.strip()
        label = self.kind.value
        return ("아니어야 함: " if negated else "") + f"{label} {where}".strip()


@dataclass(slots=True)
class ActivationCondition:
    """
    효과를 언제 발동할 수 있는가.

    발동 위치는 스크립트의 ``SetRange`` 에서, 나머지 상태 조건은
    ``SetCondition`` 함수에서 읽는다. 조건 함수가 있는데 읽어내지 못하면
    :attr:`unparsed` 에 호출 이름이 남고 :attr:`raw` 에 원문이 남는다.
    """

    locations: list[str] = field(default_factory=list)
    """발동 가능한 위치 (LOCATION_* 접두사 제외)."""
    trigger_event: str | None = None
    tree: ConditionNode | None = None
    """조건식의 논리 구조. 조건 함수가 없으면 ``None``."""
    requirements: list[ActivationRequirement] = field(default_factory=list)
    """트리 leaf 에서 유도한 평면 목록. 논리 관계는 담기지 않는다."""
    limit: ActivationLimit = field(default_factory=ActivationLimit)
    has_condition_function: bool = False
    raw: str | None = None
    """SetCondition 인자 원문."""
    unparsed: list[str] = field(default_factory=list)

    @property
    def is_structured(self) -> bool:
        """조건 함수가 있고, 그 내용을 하나라도 읽어냈는가."""
        return bool(self.requirements)

    def describe_ko(self) -> str:
        parts: list[str] = []
        if self.locations:
            parts.append("/".join(self.locations) + "에서")
        if self.trigger_event:
            parts.append(self.trigger_event)
        if self.tree is not None:
            # 트리 전문은 따로 보여준다. 여기서는 모양만 요약한다.
            counts = self.tree.count_ops()
            shape = " ".join(
                f"{op.upper()}×{counts[op]}"
                for op in ("and", "or", "not")
                if counts.get(op)
            )
            leaves = self.tree.leaves()
            evaluable = sum(
                1
                for leaf in leaves
                if getattr(getattr(leaf.predicate, "readiness", None), "value", None)
                == "evaluable"
            )
            context = sum(
                1
                for leaf in leaves
                if getattr(getattr(leaf.predicate, "readiness", None), "value", None)
                == "needs_context"
            )
            summary = f"조건 {shape}" if shape else "조건 단일"
            parts.append(
                f"{summary} (leaf {len(leaves)}: 평가가능 {evaluable} "
                f"/ 문맥필요 {context} / 미해석 {len(leaves) - evaluable - context})"
            )
        else:
            parts.extend(r.describe_ko() for r in self.requirements)
            if self.has_condition_function:
                parts.append("조건 있음(미구조화)")
        if self.limit.count is not None:
            parts.append(self.limit.describe_ko())
        return " · ".join(parts) if parts else "(조건 없음)"


@dataclass(slots=True)
class PipelineStage:
    """효과 처리 순서의 한 단계. 조건 → 비용 → 선택 → 처리."""

    stage: str
    summary: str
    structured: bool


@dataclass(slots=True)
class EffectCost:
    kind: CostKind
    raw: str
    """Lua 원문 (``Cost.SelfBanish``, 함수 이름 등)."""
    constraint: CardConstraint | None = None


@dataclass(slots=True)
class EffectSelection:
    """
    효과가 고르는 카드. 대상 지정(target)일 수도, 단순 선택일 수도 있다.

    유희왕 규칙에서 '대상으로 한다'와 '고른다'는 다르므로 구분한다.
    대상 지정 여부는 :attr:`EffectAnalysis.targets_card` 가 가진다.
    """

    locations: list[str] = field(default_factory=list)
    """LOCATION_* 이름 (접두사 제외). 어디에서 고르는가."""
    constraint: CardConstraint = field(default_factory=CardConstraint)
    min_count: int | None = None
    max_count: int | None = None
    raw: str = ""


@dataclass(slots=True)
class EffectAction:
    """효과가 일으키는 하나의 처리."""

    kind: ActionKind
    from_locations: list[str] = field(default_factory=list)
    to_location: str | None = None
    constraint: CardConstraint | None = None
    raw: str = ""
    """유도 근거가 된 Lua 호출."""


@dataclass(slots=True)
class EffectAnalysis:
    """효과 블록 하나의 구조화 결과."""

    index: str
    raw: EffectSpec
    """원본 효과 블록. 분석이 놓친 정보는 여기에 그대로 있다."""

    effect_types: list[str] = field(default_factory=list)
    trigger_event: str | None = None
    """SetCode 가 EVENT_* 이면 그 값. 아니면 ``None``."""
    effect_code: str | None = None
    """SetCode 가 EFFECT_* 이면 그 값."""
    activation_locations: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)

    # --- 1단계: 발동 조건 ---
    activation: ActivationCondition = field(default_factory=ActivationCondition)

    targets_card: bool = False
    """EFFECT_FLAG_CARD_TARGET — 규칙상 '대상으로 지정'한다."""
    once_per_turn: bool = False
    count_limit_raw: str | None = None
    has_condition: bool = False
    """SetCondition 이 걸려 있는가 (내용은 별도)."""
    condition_raw: str | None = None

    costs: list[EffectCost] = field(default_factory=list)
    selection: EffectSelection | None = None
    actions: list[EffectAction] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)
    """구조화하지 못한 Lua 호출 원문."""

    is_summon_procedure: bool = False
    """소환 절차(EFFECT_SPSUMMON_PROC 등). 발동하는 효과가 아니다."""
    is_registered: bool = True
    """``s.initial_effect`` 에서 카드에 등록된 효과인가.

    처리 함수 안에서 만들어지는 효과(예: "이 턴 어둠 속성 이외를 특수 소환할 수
    없다")는 카드가 가진 효과가 아니라 해결 중에 적용되는 제약이다. 콤보 탐색이
    "이 카드가 무엇을 할 수 있는가"를 볼 때 섞이면 안 되므로 따로 둔다."""

    def has_action(self, kind: ActionKind) -> bool:
        return any(a.kind is kind for a in self.actions)

    def pipeline(self) -> list[PipelineStage]:
        """
        효과를 처리 순서대로 펼친다: 발동 조건 → 비용 → 선택 → 처리.

        콤보 탐색은 이 순서대로 "쓸 수 있는가 → 무엇을 내야 하는가 →
        무엇을 고르는가 → 무엇이 일어나는가"를 묻게 된다.
        """
        cost_summary = (
            ", ".join(f"{c.kind.value}" for c in self.costs) if self.costs else "없음"
        )
        if self.selection:
            where = "/".join(self.selection.locations) or "?"
            selection_summary = f"{where} 의 {self.selection.constraint.describe_ko()}"
        else:
            selection_summary = "없음"
        action_summary = (
            " / ".join(
                f"{a.kind.value}→{a.to_location or '?'}" for a in self.actions
            )
            if self.actions
            else "없음"
        )
        return [
            PipelineStage(
                "activation",
                self.activation.describe_ko(),
                self.activation.is_structured or not self.activation.has_condition_function,
            ),
            PipelineStage(
                "cost",
                cost_summary,
                all(c.kind is not CostKind.UNKNOWN for c in self.costs),
            ),
            PipelineStage("selection", selection_summary, self.selection is not None),
            PipelineStage("action", action_summary, bool(self.actions)),
        ]

    def describe_ko(self) -> str:
        bits: list[str] = []
        if self.activation_locations:
            bits.append("/".join(self.activation_locations) + "에서")
        if self.costs:
            bits.append("비용 " + "/".join(c.kind.value for c in self.costs))
        if self.selection and self.selection.locations:
            where = "/".join(self.selection.locations)
            bits.append(f"{where}의 {self.selection.constraint.describe_ko()} 선택")
        for action in self.actions:
            label = action.kind.value
            if action.to_location:
                label += f"→{action.to_location}"
            bits.append(label)
        if self.once_per_turn:
            bits.append("턴 1회")
        return " · ".join(bits) if bits else "(구조화 안 됨)"


@dataclass(slots=True)
class CardAnalysis:
    """카드 한 장의 분석 결과."""

    card_id: int
    has_script: bool = False
    effects: list[EffectAnalysis] = field(default_factory=list)
    """카드에 등록된 효과."""
    resolution_effects: list[EffectAnalysis] = field(default_factory=list)
    """효과 처리 중에 생성되는 효과(적용 제약 등)."""
    listed_card_codes: list[int] = field(default_factory=list)
    """카드 텍스트가 이름으로 지명하는 카드 ID."""
    listed_series: list[str] = field(default_factory=list)
    """카드 텍스트가 지명하는 카드군."""
    setcodes: list[str] = field(default_factory=list)
    """공식 DB 기준 소속 카드군 (지명과 구분된다)."""
    unparsed_calls: list[str] = field(default_factory=list)
    """어떤 효과에도 붙이지 못한 Lua 호출."""

    def coverage(self) -> dict[str, float]:
        """
        분석이 얼마나 구조화했는지.

        비율은 '해당 요소를 가진 효과' 를 분모로 한다. 비용이 없는 효과까지
        분모에 넣으면 비용 구조화율이 실제보다 낮게 보인다.
        """
        total = len(self.effects)
        with_actions = sum(1 for e in self.effects if e.actions)
        with_costs = sum(1 for e in self.effects if e.costs)
        with_selection = sum(1 for e in self.effects if e.selection)
        has_condition = sum(
            1 for e in self.effects if e.activation.has_condition_function
        )
        condition_structured = sum(
            1 for e in self.effects if e.activation.is_structured
        )
        cost_structured = sum(
            1
            for e in self.effects
            if e.costs and all(c.kind is not CostKind.UNKNOWN for c in e.costs)
        )
        leaf_total = leaf_evaluable = leaf_context = leaf_unknown = 0
        for effect in self.effects:
            tree = effect.activation.tree
            if tree is None:
                continue
            for leaf in tree.leaves():
                leaf_total += 1
                readiness = getattr(leaf.predicate, "readiness", None)
                value = getattr(readiness, "value", None)
                if value == "evaluable":
                    leaf_evaluable += 1
                elif value == "needs_context":
                    leaf_context += 1
                else:
                    leaf_unknown += 1
        return {
            "leaf_total": leaf_total,
            "leaf_evaluable": leaf_evaluable,
            "leaf_needs_context": leaf_context,
            "leaf_unknown": leaf_unknown,
            "has_condition": has_condition,
            "condition_structured": condition_structured,
            "condition_ratio": (
                condition_structured / has_condition if has_condition else 0.0
            ),
            "cost_structured": cost_structured,
            "cost_ratio": (cost_structured / with_costs) if with_costs else 0.0,
            "effects": total,
            "with_actions": with_actions,
            "with_costs": with_costs,
            "with_selection": with_selection,
            "resolution_effects": len(self.resolution_effects),
            "unparsed_calls": len(self.unparsed_calls),
            "action_ratio": (with_actions / total) if total else 0.0,
        }
