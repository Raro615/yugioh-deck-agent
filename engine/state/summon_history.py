"""
**이 카드가 소환 절차를 거쳤는가** — 소생 제한이 묻는 한 가지 (Phase 6-BJ).

    ``c48835607.lua`` 의 ``s.initial_effect`` 첫 줄::

        Link.AddProcedure(c,nil,2,2,s.lcheck)
        c:EnableReviveLimit()          -- ← 이 표가 생긴 이유

왜 필요했는가
-------------
룰북 ``RULE-SUMMON-014`` 는 엑스트라 덱 몬스터 · 의식 · 특수 소환 몬스터를
**"정규 소환을 거친 뒤에만"** 효과로 특수 소환할 수 있다고 말한다
(전문은 :data:`~engine.effect.ruling.REVIVAL_LIMIT_TYPE_NAMES` 의 설명에
있다). 6-AQ 는 그 질문을 **읽을 자리가 없다**고 적고 ``UNKNOWN`` 을
돌려주었다 — :data:`~engine.effect.ruling.SUMMON_HISTORY_RULE` 이 그
이름이다.

그래서 묘지의 링크 몬스터는 **정규 링크 소환으로 그 자리에 간 경우에도**
되살릴 수 없었다. 오르페골 갈라테아i ③ 이 바로 그 효과이고
(「자신 묘지에서 다른 "오르페골" 카드 1장을 제외하고, 이 카드를 특수
소환한다」), 그것이 6-BJ 가 막힌 지점이었다.

이 표가 그 사실 하나를 적는다
-----------------------------
적는 것은 **"이 개체가 어떤 소환 절차로 필드에 놓였는가"** 뿐이다. 쓰는
자리는 한 곳이다 — :meth:`~engine.summon.SummonProcedure.place` 가 착지를
확인한 **뒤**에 적는다. 그래서 일반 소환 · 특수 소환 · 링크 소환이 전부
같은 한 줄을 지나고, 소환이 실패하면 (``verify`` 가 던진다) 기록도 남지
않는다.

🔴 **판정하지 않는다.** 어떤 소환법이 「정규 소환」 인지는 이 표의 질문이
아니다 — 그 지식은 :data:`~engine.effect.delta.PROCEDURE_SUMMON_KINDS` 한
곳에 있고, 읽는 쪽은 :meth:`~engine.effect.ruling.BoardRuling.
explain_special_summon` 이다. 여기는 **일어난 일**만 적는다.

🔴 **지우지 않는다 — 그리고 그것이 좁은 범위다.** 공식 구현
(``STATUS_PROC_COMPLETE``)은 카드가 엑스트라 덱으로 **되돌아가면** 그
표시를 잃는다. 이 저장소에는 엑스트라 덱을 목적지로 하는 조작이 **없고**
(``MISSING_EXTRA_DECK_DESTINATION`` — Phase 6-M), 덱으로 되돌리는 효과도
엑스트라 덱 몬스터를 거절한다. 즉 지워야 하는 사건이 **일어날 수 없다.**
그 조작이 생기는 날 이 표에 ``forget`` 이 필요하다는 것을 여기 적어 둔다 —
그때 고치지 않으면 엑스트라 덱으로 돌아갔다 묘지로 간 카드가 조용히
소생 가능해진다.

🔴 **정규 표현(``canonical_state``)에 넣지 않았다.** 넣으면 같은 판이
경로에 따라 다른 해시를 갖게 되는가 — 아니다, 반대로 **다른 판이 같은
해시로 합쳐지는지**가 질문이다. 그러려면 "같은 개체가 같은 자리에 있는데
한쪽은 절차 소환을 거쳤고 한쪽은 아닌" 두 판이 있어야 하고, 지금 등재된
조작으로는 그 판을 만들 수 없다: 엑스트라 덱 몬스터가 묘지에 있는 길은
**링크 소환 뒤 소재가 되는 것** 하나뿐이고 (엑스트라 덱에서 묘지로 보내는
조작이 없다), 메인 덱 몬스터의 이력은 소생 제한 판정을 바꾸지 않는다
(:func:`~engine.effect.ruling.revival_limit_applies` 가 ``FALSE``).
엑스트라 덱에서 묘지로 보내는 조작이 생기면 **그때 정규 표현에 들어가야
한다** — 그 조건을 여기 적어 둔다.
"""

from __future__ import annotations

from engine.ids import InstanceId

#: 한 개체의 이력 — ``(instance_id 값, 소환법 이름들)``.
#:
#: 소환법을 **이름(문자열)으로** 적는다. :class:`~engine.effect.delta.
#: SummonKind` 는 ``str`` 열거형이므로 값이 그대로 이름이고, 이 모듈이
#: 효과 계층을 가져오지 않아도 된다 (``engine.state`` 는 아래 계층이다).
SummonHistoryEntry = tuple[int, tuple[str, ...]]


class SummonHistoryRegistry:
    """
    **이 듀얼에서** 각 개체가 거친 소환 절차들.

        registry.record(instance, "link")
        registry.kinds(instance)        # ("link",)

    기록이 없으면 빈 튜플이다. 🔴 **거기서 빈 튜플은 "이 듀얼에서 소환된
    적이 없다" 는 사실이고, "모른다" 가 아니다** — 소환은 공개된 자리에서
    일어나고 쓰는 자리가 절차 하나이므로, 기록이 없는 것이 곧 하지 않은
    것이다 (``RuleUsageRegistry`` · ``SummonUsageRegistry`` 와 같은 규약).

    🔴 **그 사실이 「정규 소환을 거쳤다」 와 같은 말은 아니다.** 듀얼이
    시작될 때 이미 묘지에 있던 카드는 이 듀얼에서 소환된 적이 없고, 그
    카드가 **그전에** 정규 소환을 거쳤는지는 이 표가 알 수 없다. 그래서
    읽는 쪽은 기록이 **있을 때만** 확정 답을 내고, 없으면 ``UNKNOWN`` 을
    유지한다 (ADR-006).
    """

    __slots__ = ("_kinds",)

    def __init__(self) -> None:
        self._kinds: dict[int, tuple[str, ...]] = {}

    # ------------------------------------------------------------------
    @staticmethod
    def _key(instance: "InstanceId | int") -> int:
        return int(getattr(instance, "value", instance))

    def record(self, instance: "InstanceId | int", kind) -> None:
        """
        그 개체가 ``kind`` 소환법으로 필드에 놓였다.

        같은 소환법을 두 번 거쳐도 **두 번 적는다** — 횟수를 세는 표가
        아니지만 (그쪽은 ``SummonUsageRegistry`` 다) 일어난 일을 줄이지도
        않는다.
        """
        name = str(getattr(kind, "value", kind))
        key = self._key(instance)
        self._kinds[key] = self._kinds.get(key, ()) + (name,)

    def kinds(self, instance: "InstanceId | int") -> tuple[str, ...]:
        """그 개체가 거친 소환법 이름들. 기록이 없으면 ``()``."""
        return self._kinds.get(self._key(instance), ())

    def entries(self) -> tuple[SummonHistoryEntry, ...]:
        """관측에 실을 값. 개체 번호 순서로 정렬한다."""
        return tuple(
            (key, kinds) for key, kinds in sorted(self._kinds.items())
        )

    def clone(self) -> "SummonHistoryRegistry":
        """
        🔴 **탐색이 판을 복제한다** — 이 표가 따라가지 않으면 복제된 가지에서
        정규 링크 소환이 없던 일이 되고, 묘지의 링크 몬스터가 되살아나지
        않는다.
        """
        copy = SummonHistoryRegistry()
        copy._kinds = dict(self._kinds)
        return copy

    def canonical_state(self) -> tuple:
        """
        🔴 **지금 이 값을 ``GameState.canonical_state`` 가 읽지 않는다.**
        이유는 모듈 머리말에 있다 (만들 수 없는 판을 가르는 값이므로 해시를
        흔들지 않는다). 메서드를 둔 것은 그 조건이 깨지는 날
        **한 줄로 넣을 수 있게** 하기 위해서다.
        """
        return ("summon_history", self.entries())

    def describe_ko(self) -> str:
        if not self._kinds:
            return "소환 이력 없음"
        return " · ".join(
            f"#{key}: {'/'.join(kinds)}" for key, kinds in self.entries()
        )

    def __len__(self) -> int:
        return len(self._kinds)

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<SummonHistoryRegistry {self.describe_ko()}>"


__all__ = ["SummonHistoryEntry", "SummonHistoryRegistry"]
