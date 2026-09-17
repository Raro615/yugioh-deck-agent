"""
조건 leaf 원문 -> :class:`ConditionPredicate`.

Lua 술어를 이름으로 매핑하되, **이름만 보고 게임 의미를 추측하지 않는다.**
표에 없는 술어는 UNKNOWN 으로 두고 원문만 남긴다.

주체 판정도 EDOPro 가 콜백 서명으로 보장하는 이름에서만 한다.
``(e,tp,eg,ep,ev,re,r,rp)`` 와 핸들러 ``c`` 가 그것이고, 그 밖의 지역 변수는
:attr:`PredicateSubject.LOCAL` 로 둔다. 다만 ``local rc=re:GetHandler()`` 처럼
대입을 따라갈 수 있는 경우는 조건식 파서가 미리 치환해 주므로 그대로 읽힌다.
"""

from __future__ import annotations

import re

from analysis.effect_model import CardConstraint
from analysis.predicate_model import (
    READINESS_BY_KIND,
    ConditionPredicate,
    EvalReadiness,
    PredicateKind,
    PredicateSubject,
)
from core import constants as C

# --- 술어 이름 -> 종류 -------------------------------------------------
# 실제 스크립트에 나타난 빈도 순으로 확인한 것만 싣는다.
_PREDICATES: dict[str, PredicateKind] = {
    # 카드 성질
    "IsSetCard": PredicateKind.CARD_PROPERTY,
    "IsRace": PredicateKind.CARD_PROPERTY,
    "IsAttribute": PredicateKind.CARD_PROPERTY,
    "IsType": PredicateKind.CARD_PROPERTY,
    "IsCode": PredicateKind.CARD_PROPERTY,
    "IsLevel": PredicateKind.CARD_PROPERTY,
    "IsLevelBelow": PredicateKind.CARD_PROPERTY,
    "IsLevelAbove": PredicateKind.CARD_PROPERTY,
    "GetLevel": PredicateKind.CARD_PROPERTY,
    "GetAttack": PredicateKind.CARD_PROPERTY,
    "GetDefense": PredicateKind.CARD_PROPERTY,
    "IsMonster": PredicateKind.CARD_PROPERTY,
    "IsSpellTrap": PredicateKind.CARD_PROPERTY,
    "IsSpell": PredicateKind.CARD_PROPERTY,
    "IsTrap": PredicateKind.CARD_PROPERTY,
    # 위치 / 표시형식 / 주인
    "IsLocation": PredicateKind.CARD_LOCATION,
    "IsFaceup": PredicateKind.CARD_POSITION,
    "IsFacedown": PredicateKind.CARD_POSITION,
    "IsPosition": PredicateKind.CARD_POSITION,
    "IsControler": PredicateKind.CARD_CONTROLLER,
    # 직전 상태
    "IsPreviousLocation": PredicateKind.PREVIOUS_LOCATION,
    "IsPreviousPosition": PredicateKind.PREVIOUS_POSITION,
    "IsPreviousControler": PredicateKind.PREVIOUS_CONTROLLER,
    # 존재 / 수량
    "IsExistingMatchingCard": PredicateKind.CARD_EXISTS,
    "IsExistingTarget": PredicateKind.CARD_EXISTS,
    "IsExists": PredicateKind.GROUP_EXISTS,
    "IsContains": PredicateKind.GROUP_CONTAINS,
    "GetLocationCount": PredicateKind.ZONE_COUNT,
    "GetFieldGroupCount": PredicateKind.CARD_COUNT,
    "GetMatchingGroupCount": PredicateKind.CARD_COUNT,
    "FilterCount": PredicateKind.CARD_COUNT,
    "GetCount": PredicateKind.CARD_COUNT,
    # 턴 진행
    "IsTurnPlayer": PredicateKind.TURN_PLAYER,
    "IsMainPhase": PredicateKind.PHASE,
    "IsBattlePhase": PredicateKind.PHASE,
    "IsDamageStep": PredicateKind.PHASE,
    "IsPhase": PredicateKind.PHASE,
    "GetCurrentPhase": PredicateKind.PHASE,
    "IsAbleToEnterBP": PredicateKind.PHASE,
    "GetLP": PredicateKind.LIFE_POINTS,
    "IsEnvironment": PredicateKind.FIELD_SPELL,
    # 체인 / 이벤트 문맥
    "IsMonsterEffect": PredicateKind.CHAIN_EFFECT_TYPE,
    "IsSpellEffect": PredicateKind.CHAIN_EFFECT_TYPE,
    "IsTrapEffect": PredicateKind.CHAIN_EFFECT_TYPE,
    "IsSpellTrapEffect": PredicateKind.CHAIN_EFFECT_TYPE,
    "IsHasType": PredicateKind.CHAIN_EFFECT_TYPE,
    "IsHasProperty": PredicateKind.CHAIN_EFFECT_TYPE,
    "IsActivated": PredicateKind.CHAIN_EFFECT_TYPE,
    "IsChainNegatable": PredicateKind.CHAIN_STATE,
    "IsChainDisablable": PredicateKind.CHAIN_STATE,
    "GetCurrentChain": PredicateKind.CHAIN_STATE,
    "GetChainInfo": PredicateKind.CHAIN_STATE,
    "IsReason": PredicateKind.EVENT_REASON,
    "IsRelateToBattle": PredicateKind.BATTLE,
    "IsRelateToEffect": PredicateKind.CHAIN_STATE,
    "GetAttacker": PredicateKind.BATTLE,
    "GetAttackTarget": PredicateKind.BATTLE,
    "IsStatus": PredicateKind.CARD_STATUS,
    "GetFlagEffect": PredicateKind.FLAG_EFFECT,
    "GetSummonType": PredicateKind.SUMMON_TYPE,
    "IsSummonType": PredicateKind.SUMMON_TYPE,
    "IsPlayerAffectedByEffect": PredicateKind.PLAYER_AFFECTED,
}

# 엔진이 의미를 보장하는 이름만 주체로 인정한다.
_SUBJECTS: dict[str, PredicateSubject] = {
    "c": PredicateSubject.SELF,
    "e": PredicateSubject.EFFECT,
    "eg": PredicateSubject.EVENT_GROUP,
    "re": PredicateSubject.CHAIN_EFFECT,
    "Duel": PredicateSubject.DUEL,
    "tp": PredicateSubject.PLAYER,
    "rp": PredicateSubject.PLAYER,
    "ep": PredicateSubject.PLAYER,
}

_RE_CALL = re.compile(r"(?P<obj>[\w)]+)\s*[:.]\s*(?P<name>\w+)\s*\(")
_RE_COMPARISON = re.compile(r"(?P<op>[<>]=?|[=~]=)\s*(?P<value>-?\d+)")
_RE_LOCATION = re.compile(r"\bLOCATION_(\w+)")
_RE_RACE = re.compile(r"\bRACE_(\w+)")
_RE_ATTR = re.compile(r"\bATTRIBUTE_(\w+)")
_RE_TYPE = re.compile(r"\bTYPE_(\w+)")
_RE_SET = re.compile(r"\bSET_(\w+)")
_RE_CARD_CONST = re.compile(r"\bCARD_\w+")
_RE_NUMBER = re.compile(r"\b(\d{4,})\b")
# ``e:GetHandler()`` 와 ``re:GetHandler()`` 는 주체를 바꾼다.
_RE_HANDLER_OF = re.compile(r"\b(\w+)\s*:\s*GetHandler\s*\(\s*\)")
# ``rp==tp`` / ``ep~=1-tp`` — 엔진이 넘겨준 플레이어끼리의 비교.
# 이름이 콜백 서명으로 보장되므로 추측이 아니다.
_RE_PLAYER_COMPARISON = re.compile(
    r"^\(*\s*(?P<left>tp|rp|ep|p)\s*(?P<op>[=~]=)\s*(?P<neg>1\s*-\s*)?"
    r"(?P<right>tp|rp|ep|p)\s*\)*$"
)


class PredicateAnalyzer:
    """조건 leaf 원문을 술어로 해석한다."""

    def __init__(self, constants=None):
        self.constants = constants

    # ------------------------------------------------------------------
    def analyze(self, raw: str) -> ConditionPredicate:
        text = (raw or "").strip()
        predicate = ConditionPredicate(raw=text)
        if not text:
            return predicate

        match = self._primary_call(text)
        if match is None:
            player = self._player_comparison(text)
            if player is not None:
                return player
            # 술어가 없는 비교식이나 벌거벗은 식별자. 의미를 지어내지 않는다.
            return predicate

        name = match.group("name")
        kind = _PREDICATES.get(name)
        if kind is None:
            return predicate

        predicate.kind = kind
        predicate.readiness = READINESS_BY_KIND.get(kind, EvalReadiness.UNKNOWN)
        predicate.subject = self._subject_of(text, match)
        self._fill_arguments(predicate, text, name)
        return predicate

    @staticmethod
    def _player_comparison(text: str) -> ConditionPredicate | None:
        """
        ``rp==tp`` 같은 비교를 구조화한다.

        ``1-tp`` 는 상대를 뜻하므로 같음/다름과 조합해 자신인지 상대인지 정한다.
        누가 발동했는지(``rp``, ``ep``)는 체인 문맥이 있어야 정해지므로
        평가 가능이 아니라 문맥 필요로 둔다.
        """
        match = _RE_PLAYER_COMPARISON.match(text.strip())
        if match is None:
            return None
        equal = match.group("op") == "=="
        opponent_side = match.group("neg") is not None
        return ConditionPredicate(
            kind=PredicateKind.PLAYER_COMPARISON,
            readiness=READINESS_BY_KIND[PredicateKind.PLAYER_COMPARISON],
            subject=PredicateSubject.PLAYER,
            player="opponent" if equal == opponent_side else "self",
            comparison=match.group("op"),
            raw=text.strip(),
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _primary_call(text: str):
        """
        leaf 를 대표하는 호출을 고른다.

        ``e:GetHandler():IsLocation(...)`` 처럼 이어진 호출에서는 마지막이
        실제 질문이므로, 표에 있는 술어 중 가장 나중 것을 쓴다.
        """
        chosen = None
        for match in _RE_CALL.finditer(text):
            if match.group("name") in _PREDICATES:
                chosen = match
        return chosen

    @staticmethod
    def _subject_of(text: str, match) -> PredicateSubject:
        obj = match.group("obj")
        if obj.endswith(")"):
            # ``X:GetHandler():Is...`` 형태. 앞의 X 가 주체를 결정한다.
            # 지역 변수를 치환하면 괄호가 겹쳐 ``))`` 로도 나타난다.
            handler = _RE_HANDLER_OF.search(text[: match.start() + len(obj)])
            if handler:
                owner = handler.group(1)
                if owner == "re":
                    return PredicateSubject.CHAIN_CARD
                if owner == "e":
                    return PredicateSubject.SELF
            return PredicateSubject.LOCAL
        return _SUBJECTS.get(obj, PredicateSubject.LOCAL)

    # ------------------------------------------------------------------
    def _fill_arguments(self, predicate, text: str, name: str) -> None:
        """인자에서 카드 조건·위치·수량을 읽는다."""
        predicate.locations = _dedupe(_RE_LOCATION.findall(text))

        comparison = _RE_COMPARISON.search(text)
        if comparison:
            predicate.comparison = comparison.group("op")
            predicate.value = int(comparison.group("value"))

        constraint = self._constraint_from(text, name, predicate)
        if constraint is not None and not constraint.is_empty():
            predicate.constraint = constraint

    def _constraint_from(self, text: str, name: str, predicate) -> CardConstraint | None:
        constraint = CardConstraint()
        for value in _RE_SET.findall(text):
            if value not in constraint.setcodes:
                constraint.setcodes.append(value)
        for value in _RE_RACE.findall(text):
            bit = getattr(C, f"RACE_{value}", None)
            if bit and bit not in constraint.races:
                constraint.races.append(bit)
        for value in _RE_ATTR.findall(text):
            bit = getattr(C, f"ATTRIBUTE_{value}", None)
            if bit and bit not in constraint.attributes:
                constraint.attributes.append(bit)
        for value in _RE_TYPE.findall(text):
            if value not in constraint.card_types:
                constraint.card_types.append(value)

        # 카드 ID 는 숫자 그대로이거나 CARD_* 상수로 적힌다.
        for value in _RE_NUMBER.findall(text):
            code = int(value)
            if code not in constraint.card_codes:
                constraint.card_codes.append(code)
        if self.constants is not None:
            for token in _RE_CARD_CONST.findall(text):
                code = self.constants.card_id(token)
                if code and code not in constraint.card_codes:
                    constraint.card_codes.append(code)

        # 레벨 비교는 범위로 옮긴다. 추측이 아니라 산술이다.
        if name in ("GetLevel", "IsLevel", "IsLevelBelow", "IsLevelAbove"):
            self._apply_level(constraint, name, predicate)
        return constraint

    @staticmethod
    def _apply_level(constraint: CardConstraint, name: str, predicate) -> None:
        value = predicate.value
        if name == "IsLevelBelow" or (name == "GetLevel" and predicate.comparison == "<="):
            if value is not None:
                constraint.level_max = value
            return
        if name == "IsLevelAbove" or (name == "GetLevel" and predicate.comparison == ">="):
            if value is not None:
                constraint.level_min = value
            return
        if predicate.comparison == ">" and value is not None:
            constraint.level_min = value + 1
        elif predicate.comparison == "<" and value is not None:
            constraint.level_max = value - 1
        elif predicate.comparison == "==" and value is not None:
            constraint.levels.append(value)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out
