"""
**발동 시점에 지정한 대상과 그 효과 사이의 관계** (Phase 6-AQ 후속).

    ``local tc=Duel.GetFirstTarget()``
    ``if tc and tc:IsRelateToEffect(e) then … end``   -- c21441617.lua 의 s.spop

왜 ``InstanceId`` 로는 안 되는가
--------------------------------
``InstanceId`` 는 **듀얼 한 판 동안 영구한 개체 식별자**다 — 카드가 자리를
옮겨도 번호는 그대로이고, 그것이 그 번호의 뜻이다
(:mod:`engine.ids` — "한 번 쓴 번호는 재사용하지 않는다").

그래서 "지금 묘지에 있는 그 번호의 카드" 와 "**발동 때 지정한** 그 카드" 는
다른 질문이다. 6-AQ 는 앞쪽만 보았고, 그 결과 묘지를 떠났다 **돌아온**
대상을 같은 대상으로 읽어 소생시켰다 (보고서 §4.2 의 실측).

이 표가 뒤쪽을 적는다 — **관계 토큰**이다. 발동 시점에 "이 효과가 이 카드를
지정했다" 를 적고, 그 카드가 **존 종류를 바꾸는 이동**을 하면 그 기록을
``intact=False`` 로 끊는다. 돌아와도 되살아나지 않는다.

🔴 **무엇이 관계를 끊는가 — 적용 범위를 좁게 적는다**
-----------------------------------------------------
끊는 것은 **존 종류가 바뀌는 이동 하나**다
(:meth:`~engine.state.game_state.GameState.move` 가 부른다).

================================================  ==========
묘지 → 패 · 묘지 → 덱 · 묘지 → 제외 · 필드 → 묘지   🔴 **끊는다**
같은 존 안의 순서 변경 · 섞기 (``reorder``)         끊지 않는다
표시 형식 변경 (``set_position``)                   끊지 않는다
================================================  ==========

근거는 EDOPro 의 ``Card::clear_relate_effect()`` 가 **위치 변경**에서
불린다는 것이고, 표시 형식과 컨트롤 변경은 그 자리가 아니다. 이 저장소에는
컨트롤만 바꾸는 primitive 가 **없으므로** (실측: ``GameState`` 에
``take_control`` 류가 없다) 그 갈래는 지금 구현할 것이 없다.

🔴 **모든 카드의 ``IsRelateToEffect`` 를 구현한 것이 아니다.** 옮긴 것은
"지정한 뒤 그 카드가 존을 떠났는가" 하나이고, 체인 무효화 · 효과 무효화 ·
같은 체인 안의 다른 효과가 만드는 관계는 이 표에 없다. STRUCTURAL-50 은
**부분 해결**이다.

🔴 **끊긴 기록이 상태 해시에 들어간다.** 들어가지 않으면 "관계가 살아 있는
판" 과 "끊긴 판" 이 탐색의 중복 제거에서 같은 상태로 합쳐지고, 한쪽에서만
일어나는 소환이 다른 쪽 경로로 보고된다
(:meth:`~engine.state.game_state.GameState.canonical_state`).

🔴 **살아 있는 기록은 넣지 않는다 — 그쪽은 체인의 사실이다.** 대상을
지정하는 효과가 체인에 오를 때 기록이 생기고 그 링크가 해결되면 지워지므로
(:meth:`TargetRelationRegistry.forget`), 살아 있는 기록은 "이 판에 해결을
기다리는 대상 지정 링크가 있다" 와 같은 말이다. 체인 자체는 정규 표현에서
**일부러 빠져 있다** (같은 판이 경로에 따라 다른 해시를 갖지 않도록 —
Phase 2-D-3 · 2-F-1 · 2-F-2). 그래서 기본값을 따라 빼고, 해결 결과를
가르는 **단절**만 싣는다. 덕분에 기존 판의 해시는 — 대상 지정 효과가
해결을 기다리는 판까지 포함해서 — **한 글자도 달라지지 않았다** (실측:
``tests/engine`` 의 체인 보류 판 해시 8곳이 그대로다).
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.ids import EffectRef, InstanceId

#: ``(source_instance, card_id, ordinal, target_instance)``
#:
#: 🔴 **열쇠에 발동한 카드가 들어간다.** 같은 카드명 두 장이 각각 같은 효과를
#: 발동할 수 있으므로 (``EffectRef`` 만으로는 둘이 겹친다), 어느 **개체**가
#: 발동한 것인지까지 적어야 한 링크의 관계가 다른 링크의 것과 섞이지 않는다.
#: 발동한 카드가 없는 효과(필드를 떠난 뒤 해결 등)는 ``-1`` 로 적는다.
TargetRelationKey = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class TargetRelation:
    """효과 하나가 대상 하나를 지정했다는 기록."""

    source: InstanceId | None
    """발동한 카드. 없을 수 있다 (``ResolutionContext.source`` 와 같은 규약)."""
    card_id: int
    ordinal: int
    target: InstanceId
    intact: bool = True
    """🔴 **끊긴 뒤에 되살아나지 않는다** — 그것이 이 칸의 전부다."""

    def __post_init__(self) -> None:
        if self.card_id <= 0:
            raise ValueError(f"카드 ID 는 양수입니다: {self.card_id}")
        if self.ordinal < 0:
            raise ValueError(f"ordinal 은 0 이상입니다: {self.ordinal}")

    @property
    def key(self) -> TargetRelationKey:
        return (
            self.source.value if self.source is not None else -1,
            self.card_id,
            self.ordinal,
            self.target.value,
        )

    @property
    def effect_ref(self) -> EffectRef:
        return EffectRef(self.card_id, self.ordinal)

    def broken(self) -> "TargetRelation":
        """관계를 끊은 **새 기록**. 원본은 바꾸지 않는다 (불변)."""
        return TargetRelation(
            source=self.source,
            card_id=self.card_id,
            ordinal=self.ordinal,
            target=self.target,
            intact=False,
        )

    def canonical_state(self, instance_key=None) -> tuple:
        """
        해시용 정규 표현. ``instance_key`` 는 :class:`~engine.ids.InstanceId`
        를 **자리 기반 번호**로 바꾸는 함수다 (:meth:`~engine.state.
        game_state.GameState.instance_numbering`) — 넘기면 발급 순서가 해시에
        새지 않는다. 다른 상태 표들과 같은 규약이다.
        """
        key = instance_key if instance_key is not None else (lambda i: i.value)
        return (
            key(self.source) if self.source is not None else -1,
            self.card_id,
            self.ordinal,
            key(self.target),
            self.intact,
        )

    def to_dict(self) -> dict:
        return {
            "source": self.source.value if self.source is not None else None,
            "effect_ref": {"card_id": self.card_id, "ordinal": self.ordinal},
            "target": self.target.value,
            "intact": self.intact,
        }

    def describe_ko(self) -> str:
        said = "유지" if self.intact else "🔴 끊겼다"
        where = f"#{self.source.value}" if self.source is not None else "출처 없음"
        return (
            f"[{self.card_id}]:e[{self.ordinal}]({where}) → "
            f"#{self.target.value}: {said}"
        )

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


class TargetRelationRegistry:
    """
    발동 시점에 지정된 대상 관계들. **적고 끊기만 한다.**

    🔴 **판정하지 않는다.** "그래서 이 조작을 해도 되는가" 는 실행기가
    :meth:`status` 의 세 값을 읽고 정한다 (다른 상태 표들과 같은 태도).
    """

    __slots__ = ("records",)

    def __init__(
        self, records: "dict[TargetRelationKey, TargetRelation] | None" = None
    ):
        self.records: dict[TargetRelationKey, TargetRelation] = dict(records or {})

    # ------------------------------------------------------------------
    def note(
        self,
        source: "InstanceId | None",
        effect_ref: EffectRef,
        targets: "tuple[InstanceId, ...]",
    ) -> tuple[TargetRelation, ...]:
        """
        "이 효과가 이 카드들을 지정했다" 를 적는다.

        🔴 **같은 열쇠를 다시 적으면 관계가 되살아난다** — 그래서 부르는
        자리는 **발동 시점 하나**다 (:class:`~engine.activation.
        EffectActivator`). 해결 중에 부르면 끊긴 관계를 엔진이 복구하는
        길이 생긴다.
        """
        added: list[TargetRelation] = []
        for target in targets:
            relation = TargetRelation(
                source=source,
                card_id=effect_ref.card_id,
                ordinal=effect_ref.ordinal,
                target=target,
            )
            self.records[relation.key] = relation
            added.append(relation)
        return tuple(added)

    def break_for(self, target: InstanceId) -> tuple[TargetRelation, ...]:
        """
        그 카드를 가리키는 **모든** 관계를 끊는다. 끊긴 것들을 돌려준다.

        🔴 **기록을 지우지 않고 끊는다.** 지우면 :meth:`status` 가 "기록이
        없다"(모름)와 "끊겼다"(확정)를 구별할 수 없고, 그러면 실행기가 둘을
        같은 답으로 처리한다.
        """
        broken: list[TargetRelation] = []
        for key, relation in list(self.records.items()):
            if key[3] != target.value or not relation.intact:
                continue
            self.records[key] = relation.broken()
            broken.append(self.records[key])
        return tuple(broken)

    def status(
        self,
        source: "InstanceId | None",
        effect_ref: EffectRef,
        target: InstanceId,
    ) -> "bool | None":
        """
        그 관계가 아직 살아 있는가. **세 값이다.**

        - ``True`` — 지정했고 그 뒤로 존을 떠나지 않았다.
        - ``False`` — 지정했지만 **끊겼다.**
        - ``None`` — **기록이 없다.** "끊겼다" 가 아니라 **모른다**다.
        """
        key = (
            source.value if source is not None else -1,
            effect_ref.card_id,
            effect_ref.ordinal,
            target.value,
        )
        relation = self.records.get(key)
        return None if relation is None else relation.intact

    def forget(
        self, source: "InstanceId | None", effect_ref: EffectRef
    ) -> tuple[TargetRelation, ...]:
        """
        그 링크의 기록 전부를 지운다. 지운 것들을 돌려준다.

        🔴 **해결이 끝난 뒤 부른다.** 남겨 두면 같은 카드가 같은 효과를 다시
        발동할 때(다음 턴 등) 지난 번 관계가 보이고, 판의 정규 표현에도
        쓸모없는 기록이 쌓인다.
        """
        gone: list[TargetRelation] = []
        want = (
            source.value if source is not None else -1,
            effect_ref.card_id,
            effect_ref.ordinal,
        )
        for key in list(self.records):
            if key[:3] == want:
                gone.append(self.records.pop(key))
        return tuple(gone)

    def entries(self) -> tuple[TargetRelation, ...]:
        """적힌 관계 전부. 정렬되어 있다."""
        return tuple(relation for _, relation in sorted(self.records.items()))

    def clear(self) -> None:
        self.records.clear()

    # ------------------------------------------------------------------
    def clone(self) -> "TargetRelationRegistry":
        """
        🔴 **사본은 따로 적는다.** 한 탐색 분기에서 대상이 묘지를 떠나
        관계가 끊겼다고 다른 분기의 관계까지 끊기면, 그 분기에서는 일어나야
        하는 소생이 조용히 사라진다.
        """
        return TargetRelationRegistry(self.records)

    def canonical_state(
        self, instance_key=None, *, only_broken: bool = False
    ) -> tuple:
        """
        적힌 관계. **열쇠가 아니라 정규 표현을 정렬한다** — 자리 기반
        번호로 바꾸면 발급 순서와 정렬 순서가 어긋날 수 있다.

        🔴 ``only_broken=True`` 면 **끊긴 기록만** 싣는다. 판의 정규 표현이
        쓰는 쪽이고, 왜 그렇게 좁히는지는
        :meth:`~engine.state.game_state.GameState.canonical_state` 가 적는다.
        """
        chosen = [
            relation
            for relation in self.records.values()
            if not only_broken or not relation.intact
        ]
        return tuple(
            sorted(relation.canonical_state(instance_key) for relation in chosen)
        )

    def to_dict(self) -> dict:
        return {
            ":".join(str(part) for part in key): relation.to_dict()
            for key, relation in sorted(self.records.items())
        }

    def describe_ko(self) -> str:
        if not self.records:
            return "지정된 대상 관계 없음"
        return "지정된 대상 관계: " + " · ".join(
            relation.describe_ko() for relation in self.entries()
        )

    def __len__(self) -> int:
        return len(self.records)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TargetRelationRegistry):
            return NotImplemented
        return self.records == other.records

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<TargetRelationRegistry {len(self.records)}건>"


__all__ = [
    "TargetRelation",
    "TargetRelationKey",
    "TargetRelationRegistry",
]
