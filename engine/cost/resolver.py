"""
후보 찾기 — 관측에서 고를 수 있는 것을 센다.

    GameStateView + ChoiceSpec  ->  CandidateSet

**판을 바꾸지 않는다.** 세기만 한다.

정보 경계
---------
관측에 실린 것만 본다. 상대의 패와 덱은 애초에 관측에 없으므로 후보에
들어갈 수 없고, 뒷면 카드는 자리와 컨트롤러만 보인다.

그래서 후보가 **셋으로 갈린다.** 조건이 카드 정의를 요구하는데 뒷면이면
그 카드는 후보일 수도, 아닐 수도 있다. ``undecided`` 가 그것이다 —
세어서도, 버려서도 안 된다.

순서
----
``(컨트롤러, PLAYER_ZONES 순, sequence, instance_id)`` 로 정렬한다.
딕셔너리나 집합의 순회 순서에 의존하지 않으므로, 같은 관측이면 언제나 같은
목록이 나온다.
"""

from __future__ import annotations

import dataclasses

from engine.condition import ConditionContext, ConditionEvaluator, ConditionResult
from engine.cost.choice import CandidateSet, ChoiceSpec
from engine.game_state_view import CardView, GameStateView
from engine.ids import InstanceId
from engine.vocabulary import PLAYER_ZONES

#: 존의 정렬 순서. ``PLAYER_ZONES`` 의 선언 순서를 그대로 쓴다.
_ZONE_ORDER: dict = {zone: index for index, zone in enumerate(PLAYER_ZONES)}


def _sort_key(card: CardView) -> tuple:
    """후보 정렬 키. 값 타입만으로 이루어진다."""
    return (
        card.controller,
        _ZONE_ORDER.get(card.zone, len(_ZONE_ORDER)),
        card.sequence,
        card.instance_id.value if card.instance_id is not None else -1,
    )


class CandidateResolver:
    """
    관측에서 후보를 찾는다. **아무것도 바꾸지 않는다.**

    :class:`~engine.condition.ConditionEvaluator` 를 그대로 쓴다 — 후보를
    거르는 규칙 평가기를 따로 만들지 않는다.
    """

    __slots__ = ("_view", "_evaluator")

    def __init__(self, view: GameStateView):
        if not isinstance(view, GameStateView):
            raise TypeError(
                "CandidateResolver 는 GameStateView 만 받습니다. GameState 를 "
                "직접 넘기면 상대의 패와 덱이 후보에 섞입니다."
            )
        self._view = view
        self._evaluator = ConditionEvaluator(view)

    @property
    def view(self) -> GameStateView:
        return self._view

    def resolve(self, spec: ChoiceSpec, context: ConditionContext) -> CandidateSet:
        """``spec`` 이 말하는 후보를 관측에서 찾는다."""
        source = spec.source
        owners = (
            (source.owner.resolve(context),)
            if source.owner is not None
            else (0, 1)
        )

        visible: list[CardView] = []
        unchecked: list[str] = []
        for player_id in owners:
            player = self._view.player(player_id)
            for zone in source.zones:
                zone_view = player.zone(zone)
                if zone_view.concealed:
                    # 내용이 통째로 가려진 존이다. 장수는 알지만 어느 카드가
                    # 조건을 만족하는지는 알 수 없고, 지목할 수도 없다.
                    #
                    # **조용히 건너뛰지 않는다.** 건너뛰고 빈 목록을 돌려주면
                    # "후보가 없다" 와 "못 봤다" 가 같은 답이 되고, 그것이
                    # 모르는 것을 거짓으로 접는 일이다 (STRUCTURAL-15).
                    if zone_view.size:
                        unchecked.append(
                            f"P{player_id} {zone.value} {zone_view.size}장"
                        )
                    continue
                for card in zone_view.cards:
                    if card is None or card.instance_id is None:
                        continue
                    if source.exclude_source and card.instance_id == context.source:
                        # "이 카드 이외의" — 발동한 카드는 후보가 아니다.
                        continue
                    visible.append(card)

        visible.sort(key=_sort_key)
        missed = tuple(sorted(unchecked))

        if source.require is None:
            return CandidateSet(
                eligible=tuple(
                    card.instance_id for card in visible if card.instance_id
                ),
                unchecked=missed,
            )

        eligible: list[InstanceId] = []
        undecided: list[InstanceId] = []
        reasons: list[str] = []
        for card in visible:
            instance = card.instance_id
            assert instance is not None  # 위에서 걸렀다
            # 후보마다 문맥의 source 를 그 카드로 바꿔서 판정한다.
            per_card = dataclasses.replace(context, source=instance)
            verdict = self._evaluator.evaluate(source.require, per_card)
            if verdict.result is ConditionResult.TRUE:
                eligible.append(instance)
            elif verdict.result is ConditionResult.UNKNOWN:
                undecided.append(instance)
                why = "; ".join(verdict.unknown_reasons) or verdict.description
                reasons.append(f"{instance}: {why}")

        return CandidateSet(
            eligible=tuple(eligible),
            undecided=tuple(undecided),
            reasons=tuple(reasons),
            unchecked=missed,
        )

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<CandidateResolver {self._view}>"


__all__ = ["CandidateResolver"]
