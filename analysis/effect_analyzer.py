"""
Lua 카드 스크립트 심층 분석기.

:mod:`sources.lua_loader` 는 효과 블록의 뼈대(종류/발동 위치/분류)를 뽑는다.
여기서는 그 블록에 걸린 **핸들러 함수까지 따라 들어가** 비용·대상·처리를 읽는다.

    e1:SetCost(Cost.SelfBanish)      -> 비용: 자신을 제외
    e1:SetTarget(s.sptg)             -> s.sptg 안의 Duel.SelectTarget(...)
      -> s.spfilter 안의 IsSetCard(SET_ORCUST)  -> 대상 조건
    e1:SetOperation(s.spop)          -> s.spop 안의 Duel.SpecialSummon(...)

읽어내지 못한 호출은 버리지 않고 ``unparsed`` 에 원문으로 남긴다.
이 모듈은 검색 계층을 건드리지 않으며, 읽기 전용으로 동작한다.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from analysis.condition_parser import LuaConditionParser
from analysis.predicate_analyzer import PredicateAnalyzer
from analysis.effect_model import (
    ACTION_DESTINATION,
    ActionKind,
    ActivationCondition,
    ActivationLimit,
    ActivationRequirement,
    BoolOp,
    ConditionKind,
    ConditionNode,
    LimitScope,
    CardAnalysis,
    CardConstraint,
    CostKind,
    EffectAction,
    EffectAnalysis,
    EffectCost,
    EffectSelection,
)
from core import constants as C
from core.card_model import Card
from sources.lua_loader import _extract_call_args

# --- Lua 패턴 -------------------------------------------------------------
_RE_FUNCTION_DEF = re.compile(r"function\s+s\.(\w+)\s*\(")
_RE_SETTER = re.compile(r"\b(e\w*)\s*:\s*Set(Cost|Condition|Target|Operation)\s*\(")
_RE_CREATE_EFFECT = re.compile(
    r"\blocal\s+(e\w*)\s*=\s*Effect\.(?:CreateEffect|GlobalEffect)\s*\("
)
_RE_CLONE_EFFECT = re.compile(r"\blocal\s+(e\w*)\s*=\s*(e\w*)\s*:\s*Clone\s*\(\s*\)")
_RE_HANDLER_NAME = re.compile(r"^\s*(?:s\.)?(\w+(?:\.\w+)*)\s*$")
_RE_DUEL_CALL = re.compile(r"\bDuel\.(\w+)\s*\(")
_RE_LOCATION = re.compile(r"\bLOCATION_(\w+)")

# 비용 헬퍼 -> 비용 종류
_COST_HELPERS: dict[str, CostKind] = {
    "Cost.SelfBanish": CostKind.SELF_BANISH,
    "Cost.SelfDiscard": CostKind.SELF_DISCARD,
    "Cost.SelfDiscardToGrave": CostKind.SELF_DISCARD,
    "Cost.SelfTribute": CostKind.SELF_TRIBUTE,
    "Cost.SelfToGrave": CostKind.SELF_TO_GRAVE,
    "Cost.SelfToDeck": CostKind.SELF_TO_DECK,
    "Cost.SelfToHand": CostKind.SELF_TO_HAND,
    "Cost.SelfToExtra": CostKind.SELF_TO_EXTRA,
    "Cost.SelfReveal": CostKind.SELF_REVEAL,
    "Cost.Detach": CostKind.DETACH,
    "Cost.Discard": CostKind.DISCARD,
    "Cost.PayLP": CostKind.PAY_LP,
}

# 비용 함수 안의 Duel 호출 -> 비용 종류
_COST_CALLS: dict[str, CostKind] = {
    "DiscardHand": CostKind.DISCARD,
    "SendtoGrave": CostKind.SEND_DECK_TO_GRAVE,
    "Release": CostKind.RELEASE,
    "PayLPCost": CostKind.PAY_LP,
    "Remove": CostKind.BANISH,
    "DiscardDeck": CostKind.SEND_DECK_TO_GRAVE,
    "RemoveCounter": CostKind.REMOVE_COUNTER,
    "SendtoDeck": CostKind.TO_DECK,
    "SendtoHand": CostKind.RETURN_TO_HAND,
}

# 자원을 소모하지 않는 비용 함수에서만 나타나는 호출.
# 이런 것만 있으면 '읽지 못함'이 아니라 '비용 없음'이다.
_DECLARATORY_COST_CALLS = frozenset(
    {"RegisterEffect", "Hint", "GetActivityCount", "GetCustomActivityCount",
     "GetFlagEffect", "RegisterFlagEffect", "ConfirmCards"}
)

# 비용 헬퍼 중 자원을 소모하지 않는 것
_DECLARATORY_COST_HELPERS = ("aux.RemainFieldCost",)

# 처리 함수 안의 Duel 호출 -> 액션
_ACTION_CALLS: dict[str, ActionKind] = {
    "SpecialSummon": ActionKind.SPECIAL_SUMMON,
    "SpecialSummonStep": ActionKind.SPECIAL_SUMMON,
    "SpecialSummonRule": ActionKind.SPECIAL_SUMMON,
    "Summon": ActionKind.NORMAL_SUMMON,
    "SendtoHand": ActionKind.TO_HAND,
    "SendtoGrave": ActionKind.TO_GRAVE,
    "SendtoDeck": ActionKind.TO_DECK,
    "Remove": ActionKind.BANISH,
    "Destroy": ActionKind.DESTROY,
    "Draw": ActionKind.DRAW,
    "DiscardHand": ActionKind.DISCARD,
    "Release": ActionKind.RELEASE,
    "NegateEffect": ActionKind.NEGATE,
    "NegateActivation": ActionKind.NEGATE,
    "Damage": ActionKind.DAMAGE,
    "Recover": ActionKind.RECOVER,
    "ChangePosition": ActionKind.POSITION,
    "Equip": ActionKind.EQUIP,
    "GetControl": ActionKind.CONTROL,
}

# 카드를 고르는 호출: (이름, 필터 인자 위치)
_SELECT_CALLS = (
    "SelectTarget",
    "SelectMatchingCard",
    "IsExistingTarget",
    "IsExistingMatchingCard",
    "GetMatchingGroup",
)

# 구조화 대상이 아닌 보조 호출 (잡음으로 남기지 않는다)
_IGNORED_CALLS = frozenset(
    {
        "Hint", "SetOperationInfo", "SetPossibleOperationInfo", "GetLocationCount",
        "GetFirstTarget", "GetChainInfo", "BreakEffect", "RegisterEffect",
        "ConfirmCards", "GetFieldGroupCount", "IsPlayerAffectedByEffect",
        "IsTurnPlayer", "GetTurnPlayer", "GetCurrentPhase", "GetAttacker",
        "GetAttackTarget", "SetTargetPlayer", "SetTargetParam", "SelectYesNo",
        "ShuffleDeck", "ShuffleHand", "SetChainLimit", "GetTargetCount",
        "GetOperatedGroup", "IsBattlePhase", "IsMainPhase", "GetFlagEffect",
        "RegisterFlagEffect", "GetFieldCard", "IsExistingMatchingCard",
    }
)

# 조건 함수의 Duel 호출 -> 조건 종류
_CONDITION_CALLS: dict[str, ConditionKind] = {
    "IsExistingMatchingCard": ConditionKind.REQUIRES_CARD,
    "IsExistingTarget": ConditionKind.REQUIRES_CARD,
    "GetLocationCount": ConditionKind.ZONE_AVAILABLE,
    "GetFieldGroupCount": ConditionKind.CARD_COUNT,
    "GetMatchingGroupCount": ConditionKind.CARD_COUNT,
    "IsTurnPlayer": ConditionKind.TURN_PLAYER,
    "GetTurnPlayer": ConditionKind.TURN_PLAYER,
    "IsMainPhase": ConditionKind.PHASE,
    "IsBattlePhase": ConditionKind.PHASE,
    "IsPhase": ConditionKind.PHASE,
    "GetCurrentPhase": ConditionKind.PHASE,
    "IsDamageStep": ConditionKind.PHASE,
    "GetLP": ConditionKind.LIFE_POINTS,
    "IsChainNegatable": ConditionKind.CHAIN,
    "IsChainDisablable": ConditionKind.CHAIN,
    "GetCurrentChain": ConditionKind.CHAIN,
    "GetChainInfo": ConditionKind.CHAIN,
    "GetAttacker": ConditionKind.BATTLE,
    "GetAttackTarget": ConditionKind.BATTLE,
    "IsPlayerAffectedByEffect": ConditionKind.PLAYER_AFFECTED,
    "IsPlayerCanDraw": ConditionKind.CARD_COUNT,
    "IsPlayerCanSpecialSummonMonster": ConditionKind.ZONE_AVAILABLE,
}

# 조건 함수에서 무시할 보조 호출 (미구조화로 기록하지 않는다)
_CONDITION_IGNORED = frozenset({"Hint", "GetFlagEffect", "GetHandler"})

_RE_FACEUP_FILTER = re.compile(r"aux\.FaceupFilter\s*\(")
_RE_CALL_WITH_POS = re.compile(r"\bDuel\.(\w+)\s*\(")
# 조건 함수는 Duel 호출 없이 카드/효과 객체의 술어만 쓰는 경우가 흔하다.
# (re:IsTrapEffect(), eg:IsExists(...), rc:IsSetCard(...) 등)
_RE_OBJECT_PREDICATE = re.compile(r"[\w)]\s*[:.](Is\w+|Get\w+|Exists)\s*\(")

# 카드 조건 술어
_RE_IS_RACE = re.compile(r"IsRace\s*\(\s*([^)]*)\)")
_RE_IS_ATTRIBUTE = re.compile(r"IsAttribute\s*\(\s*([^)]*)\)")
_RE_IS_TYPE = re.compile(r"IsType\s*\(\s*([^)]*)\)")
_RE_IS_SETCARD = re.compile(r"IsSetCard\s*\(\s*([^)]*)\)")
_RE_IS_LEVEL = re.compile(r"IsLevel\s*\(\s*(\d+)")
_RE_IS_LEVEL_BELOW = re.compile(r"IsLevelBelow\s*\(\s*(\d+)")
_RE_IS_LEVEL_ABOVE = re.compile(r"IsLevelAbove\s*\(\s*(\d+)")
_RE_IS_CODE = re.compile(r"(not\s+)?\w+:IsCode\s*\(\s*([^)]*)\)")
_RE_RACE_CONST = re.compile(r"\bRACE_(\w+)")
_RE_ATTR_CONST = re.compile(r"\bATTRIBUTE_(\w+)")
_RE_TYPE_CONST = re.compile(r"\bTYPE_(\w+)")
_RE_SET_CONST = re.compile(r"\bSET_(\w+)")
# aux.FaceupFilter(Card.IsSetCard,SET_X) 처럼 술어와 인자가 쉼표로 이어지는 형태
_RE_PRED_COMMA = re.compile(
    r"Card\.Is(SetCard|Race|Attribute|Type|Code|Level)\s*,\s*([A-Za-z0-9_|+,\s]+)"
)


class EffectAnalyzer:
    """카드 스크립트를 :class:`CardAnalysis` 로 구조화한다."""

    def __init__(self, repository, script_dir: str | os.PathLike[str] | None = None):
        self.repository = repository
        self.script_dir = Path(
            script_dir
            or getattr(repository, "script_dir", None)
            or Path(__file__).resolve().parent.parent
        )
        self._cache: dict[int, CardAnalysis] = {}
        self.predicates = PredicateAnalyzer(
            constants=getattr(repository, "constants", None)
        )

    # ------------------------------------------------------------------
    def analyze(self, card: Card | None) -> CardAnalysis:
        if card is None:
            return CardAnalysis(card_id=0)
        cached = self._cache.get(card.id)
        if cached is not None:
            return cached

        analysis = self._analyze_card(card)
        self._cache[card.id] = analysis
        return analysis

    # ------------------------------------------------------------------
    def _analyze_card(self, card: Card) -> CardAnalysis:
        setcodes = [
            (self.repository.constants.setcode_name(code) or hex(code)).removeprefix(
                "SET_"
            )
            for code in card.setcodes
        ]
        analysis = CardAnalysis(
            card_id=card.id,
            has_script=card.script is not None,
            listed_card_codes=list(card.script.listed_names) if card.script else [],
            listed_series=list(card.script.listed_series) if card.script else [],
            setcodes=setcodes,
        )
        if card.script is None:
            return analysis

        source = self._read_source(card.script.file_name)
        if source is None:
            return analysis

        functions = self._collect_functions(source)
        spans = self._function_spans(source)
        entries = self._collect_handlers(source, spans)

        for position, spec in enumerate(card.script.effects):
            entry = entries[position] if position < len(entries) else {}
            effect = self._analyze_effect(
                spec, entry.get("handlers", {}), functions, analysis
            )
            effect.is_registered = entry.get("function") == "initial_effect"
            if effect.is_registered:
                analysis.effects.append(effect)
            else:
                analysis.resolution_effects.append(effect)
        return analysis

    @staticmethod
    def _function_spans(source: str) -> list[tuple[int, int, str]]:
        """(시작, 끝, 함수명) 목록. 효과가 어느 함수 안에서 만들어졌는지 판단한다."""
        matches = list(_RE_FUNCTION_DEF.finditer(source))
        spans: list[tuple[int, int, str]] = []
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(source)
            spans.append((match.start(), end, match.group(1)))
        return spans

    @staticmethod
    def _enclosing_function(position: int, spans) -> str | None:
        for start, end, name in spans:
            if start <= position < end:
                return name
        return None

    def _read_source(self, file_name: str) -> str | None:
        path = self.script_dir / file_name
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    # ------------------------------------------------------------------
    @staticmethod
    def _collect_functions(source: str) -> dict[str, str]:
        """``function s.name(...)`` 본문을 이름으로 찾을 수 있게 모은다."""
        bodies: dict[str, str] = {}
        matches = list(_RE_FUNCTION_DEF.finditer(source))
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(source)
            bodies[match.group(1)] = source[match.start() : end]
        return bodies

    @classmethod
    def _collect_handlers(cls, source: str, spans) -> list[dict]:
        """
        효과 변수별로 SetCost/SetCondition/SetTarget/SetOperation 인자를 모은다.

        :mod:`sources.lua_loader` 와 같은 방식으로 변수 바인딩을 추적한다.
        Clone 은 부모의 핸들러를 물려받은 뒤 일부만 덮어쓴다.
        """
        events: list[tuple[int, str, str]] = []
        for m in _RE_CREATE_EFFECT.finditer(source):
            events.append((m.start(), "create", m.group(1)))
        for m in _RE_CLONE_EFFECT.finditer(source):
            events.append((m.start(), "clone", f"{m.group(1)}={m.group(2)}"))
        for m in _RE_SETTER.finditer(source):
            events.append(
                (m.start(), "set", f"{m.group(1)}|{m.group(2)}|{m.end() - 1}")
            )
        events.sort(key=lambda e: e[0])

        bindings: dict[str, dict[str, str]] = {}
        order: list[dict] = []
        for pos, kind, payload in events:
            if kind == "create":
                handlers: dict[str, str] = {}
                bindings[payload] = handlers
                order.append(
                    {
                        "handlers": handlers,
                        "function": cls._enclosing_function(pos, spans),
                    }
                )
            elif kind == "clone":
                dst, src = payload.split("=", 1)
                handlers = dict(bindings.get(src, {}))
                bindings[dst] = handlers
                order.append(
                    {
                        "handlers": handlers,
                        "function": cls._enclosing_function(pos, spans),
                    }
                )
            else:
                var, setter, idx = payload.split("|", 2)
                target = bindings.get(var)
                if target is not None:
                    target[setter] = _extract_call_args(source, int(idx)).strip()

        # lua_loader 와 같은 순서로 효과 블록이 만들어지므로 순번으로 짝짓는다.
        return order

    # ------------------------------------------------------------------
    def _analyze_effect(self, spec, handlers, functions, analysis):
        effect = EffectAnalysis(
            index=spec.index,
            raw=spec,
            effect_types=list(spec.effect_types),
            activation_locations=list(spec.ranges),
            categories=list(spec.categories),
            targets_card="CARD_TARGET" in spec.properties,
            count_limit_raw=spec.count_limit,
        )
        if spec.code and spec.code.startswith("EVENT_"):
            effect.trigger_event = spec.code
        elif spec.code:
            effect.effect_code = spec.code
            effect.is_summon_procedure = spec.code in (
                "EFFECT_SPSUMMON_PROC",
                "EFFECT_SPSUMMON_PROC_G",
            )

        effect.activation = self._analyze_activation(spec, handlers, functions)
        effect.once_per_turn = effect.activation.limit.count == 1
        condition = handlers.get("Condition")
        if condition:
            effect.has_condition = True
            effect.condition_raw = condition

        cost = handlers.get("Cost")
        if cost:
            effect.costs.extend(self._analyze_cost(cost, functions))

        bodies = [
            functions.get(self._handler_name(handlers[key]), "")
            for key in ("Target", "Operation")
            if handlers.get(key)
        ]
        combined = "\n".join(b for b in bodies if b)
        if combined:
            effect.selection = self._analyze_selection(combined, functions)
            effect.actions.extend(
                self._analyze_actions(combined, functions, effect.selection)
            )
            effect.unparsed.extend(self._unparsed_calls(combined))
            analysis.unparsed_calls.extend(effect.unparsed)
        return effect


    # ------------------------------------------------------------------
    @staticmethod
    def _split_top_level(text: str) -> list[str]:
        """괄호 깊이를 보며 최상위 쉼표로만 인자를 나눈다."""
        parts: list[str] = []
        depth = 0
        current: list[str] = []
        for ch in text:
            if ch in "({[":
                depth += 1
            elif ch in ")}]":
                depth -= 1
            if ch == "," and depth == 0:
                parts.append("".join(current).strip())
                current = []
                continue
            current.append(ch)
        if current:
            parts.append("".join(current).strip())
        return parts

    def _constraint_from_argument(self, argument: str, functions) -> CardConstraint:
        """
        필터 인자에서 카드 조건을 읽는다.

        이름 있는 함수(``s.spfilter``)면 그 본문을, 인라인 표현
        (``aux.FaceupFilter(Card.IsSetCard,SET_ORCUST)``)이면 표현 자체를 본다.
        """
        name = self._handler_name(argument)
        if name and name in functions:
            return self._analyze_constraint(functions[name])
        return self._analyze_constraint(argument)

    def _analyze_limit(self, raw: str | None) -> ActivationLimit:
        """
        ``SetCountLimit`` 인자에서 제한 횟수와 범위를 읽는다.

        범위가 다르면 실제 제약이 완전히 달라진다.
            SetCountLimit(1)          이 카드 1장 기준
            SetCountLimit(1,id)       이 카드명 기준
            SetCountLimit(1,{id,1})   이 카드명의 그 효과 기준
        """
        if not raw:
            return ActivationLimit()
        args = self._split_top_level(raw)
        if not args:
            return ActivationLimit(raw=raw, scope=LimitScope.UNKNOWN)
        count = int(args[0]) if args[0].isdigit() else None
        if len(args) == 1:
            scope = LimitScope.PER_CARD
        elif args[1].startswith("{"):
            scope = LimitScope.PER_EFFECT
        elif args[1] in ("id", "s.id"):
            scope = LimitScope.PER_CARD_NAME
        else:
            scope = LimitScope.UNKNOWN
        return ActivationLimit(count=count, scope=scope, raw=raw)

    def _analyze_activation(self, spec, handlers, functions) -> ActivationCondition:
        """발동 위치와 조건 함수를 합쳐 발동 조건을 만든다."""
        activation = ActivationCondition(
            locations=list(spec.ranges),
            limit=self._analyze_limit(spec.count_limit),
        )
        if spec.code and spec.code.startswith("EVENT_"):
            activation.trigger_event = spec.code

        raw = handlers.get("Condition")
        if not raw:
            return activation
        activation.has_condition_function = True
        activation.raw = raw

        name = self._handler_name(raw)
        body = functions.get(name or "", "")
        source = body or raw

        # 논리 구조를 먼저 세우고, 평면 목록은 트리 leaf 에서 유도한다.
        # 둘을 따로 만들면 어긋난다.
        parser = LuaConditionParser(
            classify_leaf=lambda text: self._classify_leaf(text, functions),
            analyze_predicate=self.predicates.analyze,
        )
        tree = parser.parse_function(source) if body else None
        if tree is not None:
            activation.tree = self._prune(tree)

        if activation.tree is not None:
            # NOT 아래에 있는 leaf 는 평면 목록에서도 negated 로 표시한다.
            # 평면 목록만 쓰는 기존 코드가 의미를 잃지 않게 하기 위해서다.
            self._mark_negation(activation.tree, False)
            activation.requirements.extend(
                leaf.requirement
                for leaf in activation.tree.leaves()
                if leaf.requirement is not None
            )
        else:
            activation.requirements.extend(
                self._parse_requirements(source, functions)
            )
        activation.unparsed.extend(self._condition_unparsed(source))

        if not activation.requirements and not activation.unparsed:
            # 조건이 분명히 있는데 아무것도 읽지 못한 경우. 조용히 넘어가면
            # "조건 없음"과 구분되지 않으므로 핸들러 자체를 흔적으로 남긴다.
            activation.unparsed.append(raw.strip()[:60])
        return activation

    def _classify_leaf(self, text: str, functions):
        """
        조건식의 leaf 하나를 :class:`ActivationRequirement` 로 분류한다.

        분류하지 못하면 ``None`` 을 돌려주고, 트리는 원문만 가진 leaf 로 남긴다.
        논리 구조는 보존하되 의미를 지어내지 않기 위해서다.
        """
        found = self._parse_requirements(text, functions)
        if not found:
            return None
        requirement = found[0]
        # 부정은 트리의 NOT 노드가 표현한다. leaf 안에서 중복으로 뒤집지 않는다.
        requirement.negated = False
        return requirement

    @classmethod
    def _mark_negation(cls, node: ConditionNode, negated: bool) -> None:
        """NOT 을 몇 번 거쳤는지에 따라 leaf 의 negated 를 채운다."""
        if node.op is BoolOp.LEAF:
            if node.requirement is not None:
                node.requirement.negated = negated
            if node.predicate is not None:
                node.predicate.negated = negated
            return
        flip = negated != (node.op is BoolOp.NOT)
        for child in node.children:
            cls._mark_negation(child, flip)

    @staticmethod
    def _prune(node: ConditionNode) -> ConditionNode:
        """
        아무것도 분류하지 못한 가지를 정리한다.

        구조만 남고 leaf 가 전부 미분류인 가지는 그대로 두되(원문 보존),
        자식이 하나뿐인 AND/OR 는 접어서 트리를 읽기 쉽게 만든다.
        """
        if node.op is BoolOp.LEAF:
            return node
        node.children = [EffectAnalyzer._prune(c) for c in node.children]
        if node.op in (BoolOp.AND, BoolOp.OR):
            # AND(A, AND(B, C)) 는 AND(A, B, C) 와 같다. 같은 연산자가 겹쳐 있으면
            # 접어야 "이 AND 안에 OR 가지가 있는가" 를 한 단계에서 볼 수 있다.
            merged: list[ConditionNode] = []
            for child in node.children:
                if child.op is node.op:
                    merged.extend(child.children)
                else:
                    merged.append(child)
            node.children = merged
            if len(node.children) == 1:
                return node.children[0]
        return node

    def _parse_requirements(self, body: str, functions):
        """조건 함수의 Duel 호출을 상태 요구로 바꾼다."""
        requirements: list[ActivationRequirement] = []
        for match in _RE_CALL_WITH_POS.finditer(body):
            name = match.group(1)
            kind = _CONDITION_CALLS.get(name)
            if kind is None:
                continue
            args_text = _extract_call_args(body, match.end() - 1)
            args = self._split_top_level(args_text)
            # ``not`` 을 놓치면 조건의 의미가 정반대가 된다.
            prefix = body[max(0, match.start() - 6) : match.start()]
            negated = bool(re.search(r"\bnot\s*$", prefix))

            requirement = ActivationRequirement(
                kind=kind,
                negated=negated,
                raw=f"Duel.{name}({args_text.strip()[:110]})",
            )
            if kind is ConditionKind.REQUIRES_CARD and len(args) >= 5:
                self._fill_card_requirement(requirement, args, functions)
            elif kind in (ConditionKind.ZONE_AVAILABLE, ConditionKind.CARD_COUNT):
                requirement.locations = _dedupe(_RE_LOCATION.findall(args_text))
                requirement.player = self._player_from(args[0] if args else "")
            requirements.append(requirement)
        return requirements

    def _fill_card_requirement(self, requirement, args, functions) -> None:
        """
        ``IsExistingMatchingCard(filter, player, selfloc, opploc, count, ...)``
        의 인자 위치에서 위치·소유자·매수·카드 조건을 읽는다.
        """
        self_locations = _dedupe(_RE_LOCATION.findall(args[2]))
        opponent_locations = _dedupe(_RE_LOCATION.findall(args[3]))
        requirement.locations = self_locations or opponent_locations
        if self_locations and opponent_locations:
            requirement.player = "both"
        elif opponent_locations:
            requirement.player = "opponent"
        elif self_locations:
            requirement.player = "self"
        if args[4].isdigit():
            requirement.min_count = int(args[4])
        requirement.faceup = bool(_RE_FACEUP_FILTER.search(args[0]))
        requirement.constraint = self._constraint_from_argument(args[0], functions)

    @staticmethod
    def _player_from(argument: str) -> str | None:
        text = argument.strip()
        if text == "tp":
            return "self"
        if "1-tp" in text:
            return "opponent"
        return None

    @staticmethod
    def _condition_unparsed(body: str) -> list[str]:
        """
        조건 함수에서 구조화하지 못한 부분. 추측하지 않고 이름만 남긴다.

        Duel 호출뿐 아니라 객체 술어(``re:IsTrapEffect()``)도 기록한다.
        그러지 않으면 Duel 호출이 없는 조건 함수가 아무 흔적도 남기지 못해,
        "조건이 없다"와 "조건을 못 읽었다"가 구분되지 않는다.
        """
        found: list[str] = []
        for match in _RE_CALL_WITH_POS.finditer(body):
            name = match.group(1)
            if name in _CONDITION_CALLS or name in _CONDITION_IGNORED:
                continue
            entry = f"Duel.{name}"
            if entry not in found:
                found.append(entry)
        for match in _RE_OBJECT_PREDICATE.finditer(body):
            entry = match.group(1)
            # 이미 구조화한 Duel 호출이 점 표기로 다시 잡히지 않게 한다.
            if entry in _CONDITION_CALLS or entry in _CONDITION_IGNORED:
                continue
            if entry in found:
                continue
            found.append(entry)
        return found

    # ------------------------------------------------------------------
    @staticmethod
    def _handler_name(argument: str) -> str | None:
        """``s.sptg`` 같은 인자에서 함수 이름만 뽑는다."""
        match = _RE_HANDLER_NAME.match(argument or "")
        if not match:
            return None
        return match.group(1).split(".")[-1]

    def _analyze_cost(self, argument: str, functions) -> list[EffectCost]:
        helper = argument.strip()
        for name, kind in _COST_HELPERS.items():
            if helper.startswith(name):
                return [EffectCost(kind=kind, raw=name)]
        for name in _DECLARATORY_COST_HELPERS:
            if helper.startswith(name):
                return [EffectCost(kind=CostKind.NONE, raw=name)]

        body = functions.get(self._handler_name(helper) or "", "")
        if not body:
            # 비용이 걸려 있다는 사실만 확인된다. 내용은 추측하지 않는다.
            return [EffectCost(kind=CostKind.UNKNOWN, raw=helper)]

        found: list[EffectCost] = []
        calls = set()
        for match in _RE_DUEL_CALL.finditer(body):
            name = match.group(1)
            calls.add(name)
            kind = _COST_CALLS.get(name)
            if kind and not any(c.kind is kind for c in found):
                found.append(EffectCost(kind=kind, raw=f"Duel.{name}"))
        if found:
            return found

        # 자원을 쓰지 않는 비용 함수(표식만 남기거나 제약을 거는 경우)는
        # '읽지 못함'이 아니라 '비용 없음'이다. 둘을 섞으면 안 된다.
        if not calls or calls <= _DECLARATORY_COST_CALLS:
            return [EffectCost(kind=CostKind.NONE, raw=helper)]
        return [EffectCost(kind=CostKind.UNKNOWN, raw=helper)]

    # ------------------------------------------------------------------
    def _analyze_selection(self, body: str, functions) -> EffectSelection | None:
        """카드를 고르는 호출에서 위치·조건·개수를 읽는다."""
        for match in _RE_DUEL_CALL.finditer(body):
            name = match.group(1)
            if name not in _SELECT_CALLS:
                continue
            args = _extract_call_args(body, match.end() - 1)
            locations = _dedupe(_RE_LOCATION.findall(args))
            if not locations:
                continue
            filter_name = None
            for token in args.split(","):
                candidate = self._handler_name(token)
                if candidate and candidate in functions:
                    filter_name = candidate
                    break
            constraint = (
                self._analyze_constraint(functions[filter_name])
                if filter_name
                else CardConstraint()
            )
            counts = re.findall(r",\s*(\d+)\s*,\s*(\d+)\s*,", args)
            min_count = int(counts[0][0]) if counts else None
            max_count = int(counts[0][1]) if counts else None
            return EffectSelection(
                locations=locations,
                constraint=constraint,
                min_count=min_count,
                max_count=max_count,
                raw=f"Duel.{name}({args.strip()[:120]})",
            )
        return None

    @staticmethod
    def _analyze_constraint(body: str) -> CardConstraint:
        """필터 함수의 ``Card.Is*`` 호출에서 카드 조건을 읽는다."""
        constraint = CardConstraint()
        for args in _RE_IS_RACE.findall(body):
            for name in _RE_RACE_CONST.findall(args):
                bit = getattr(C, f"RACE_{name}", None)
                if bit and bit not in constraint.races:
                    constraint.races.append(bit)
        for args in _RE_IS_ATTRIBUTE.findall(body):
            for name in _RE_ATTR_CONST.findall(args):
                bit = getattr(C, f"ATTRIBUTE_{name}", None)
                if bit and bit not in constraint.attributes:
                    constraint.attributes.append(bit)
        for args in _RE_IS_TYPE.findall(body):
            for name in _RE_TYPE_CONST.findall(args):
                if name not in constraint.card_types:
                    constraint.card_types.append(name)
        for args in _RE_IS_SETCARD.findall(body):
            for name in _RE_SET_CONST.findall(args):
                if name not in constraint.setcodes:
                    constraint.setcodes.append(name)
        for value in _RE_IS_LEVEL.findall(body):
            level = int(value)
            if level not in constraint.levels:
                constraint.levels.append(level)
        below = _RE_IS_LEVEL_BELOW.findall(body)
        if below:
            constraint.level_max = min(int(v) for v in below)
        above = _RE_IS_LEVEL_ABOVE.findall(body)
        if above:
            constraint.level_min = max(int(v) for v in above)
        # aux.FaceupFilter(Card.IsSetCard,SET_X) 처럼 술어와 인자가 쉼표로 이어지는 형태
        for predicate, args in _RE_PRED_COMMA.findall(body):
            if predicate == "SetCard":
                for name in _RE_SET_CONST.findall(args):
                    if name not in constraint.setcodes:
                        constraint.setcodes.append(name)
            elif predicate == "Race":
                for name in _RE_RACE_CONST.findall(args):
                    bit = getattr(C, f"RACE_{name}", None)
                    if bit and bit not in constraint.races:
                        constraint.races.append(bit)
            elif predicate == "Attribute":
                for name in _RE_ATTR_CONST.findall(args):
                    bit = getattr(C, f"ATTRIBUTE_{name}", None)
                    if bit and bit not in constraint.attributes:
                        constraint.attributes.append(bit)
            elif predicate == "Type":
                for name in _RE_TYPE_CONST.findall(args):
                    if name not in constraint.card_types:
                        constraint.card_types.append(name)
            elif predicate == "Level":
                for value in re.findall(r"\b(\d{1,2})\b", args):
                    level = int(value)
                    if level not in constraint.levels:
                        constraint.levels.append(level)

        for negated, args in _RE_IS_CODE.findall(body):
            codes = [int(v) for v in re.findall(r"\b(\d{4,})\b", args)]
            target = (
                constraint.excluded_card_codes
                if negated
                else constraint.card_codes
            )
            for code in codes:
                if code not in target:
                    target.append(code)
        return constraint

    # ------------------------------------------------------------------
    def _analyze_actions(
        self, body: str, functions, selection: EffectSelection | None
    ) -> list[EffectAction]:
        actions: list[EffectAction] = []
        seen: set[ActionKind] = set()
        for match in _RE_DUEL_CALL.finditer(body):
            kind = _ACTION_CALLS.get(match.group(1))
            if kind is None or kind in seen:
                continue
            seen.add(kind)
            args = _extract_call_args(body, match.end() - 1)
            locations = _dedupe(_RE_LOCATION.findall(args))
            if not locations and selection is not None:
                # 고른 카드를 그대로 처리하는 경우가 흔하다.
                locations = list(selection.locations)
            actions.append(
                EffectAction(
                    kind=kind,
                    from_locations=locations,
                    to_location=ACTION_DESTINATION.get(kind),
                    constraint=selection.constraint if selection else None,
                    raw=f"Duel.{match.group(1)}",
                )
            )
        return actions

    @staticmethod
    def _unparsed_calls(body: str) -> list[str]:
        """구조화하지 못한 Duel 호출. 추측하지 않고 이름만 남긴다."""
        found: list[str] = []
        for match in _RE_DUEL_CALL.finditer(body):
            name = match.group(1)
            if (
                name in _ACTION_CALLS
                or name in _SELECT_CALLS
                or name in _IGNORED_CALLS
                or name in _COST_CALLS
            ):
                continue
            entry = f"Duel.{name}"
            if entry not in found:
                found.append(entry)
        return found


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out
