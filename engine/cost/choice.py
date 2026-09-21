"""
선택 — "무엇을 고를 수 있고, 무엇을 골랐는가".

셋을 **절대 합치지 않는다.**

==================  ==============================================
:class:`ChoiceSpec`  무엇을 몇 장 고르라는 **요구**
:class:`CandidateSet`  지금 관측에서 **고를 수 있는 것들**
:class:`Selection`   플레이어가 **실제로 고른 것**
==================  ==============================================

후보는 관측에서 계산된 결과이고, 선택은 플레이어가 만든 결과다. 한 타입으로
합치면 "고를 수 있었다" 와 "골랐다" 가 섞이고, 검증할 대상이 사라진다.

고르는 행위 자체는 여기서 하지 않는다. 후보를 세고 선택을 검사할 뿐이다.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.condition import Condition, PlayerRef
from engine.ids import InstanceId
from engine.vocabulary import Zone


@dataclass(frozen=True, slots=True)
class CandidateSource:
    """
    후보를 **어디에서** 찾는가.

    ``owner`` 가 ``None`` 이면 양쪽 필드를 모두 본다 ("필드의 몬스터 1장" 처럼
    주인을 가리지 않는 경우).
    """

    zones: frozenset[Zone]
    owner: PlayerRef | None = PlayerRef.CONTROLLER
    require: Condition | None = None
    """후보가 추가로 만족해야 하는 조건. 후보마다 따로 판정한다."""
    exclude_source: bool = False
    """
    **발동한 카드 자신을 후보에서 뺀다.**

    "이 카드 이외의" 를 표현한다 (싸이크론의 ``chkc~=e:GetHandler()``).
    기본값이 거짓인 이유는 대부분의 효과가 자기 자신을 가리지 않기
    때문이고, 적지 않은 것을 "뺀다" 로 읽으면 안 되기 때문이다.
    """

    def __post_init__(self) -> None:
        if not isinstance(self.zones, frozenset):
            raise TypeError("zones 는 frozenset 이어야 합니다 — 명세는 불변입니다.")
        if not self.zones:
            raise ValueError("후보를 찾을 존이 최소 하나 필요합니다.")

    def looked_at_zones(self) -> frozenset[Zone]:
        """
        이 후보 규칙을 판정하려면 고르는 사람이 **자기 어느 자리를 들여다
        봐야 하는가** (Phase 2-Y).

        추론이 아니라 **이 규칙이 스스로 적어 둔 것**을 읽는다. Lua 의
        ``Duel.SelectMatchingCard(tp, filter, tp, LOCATION_DECK, 0, ...)``
        에서 "고르는 사람 ``tp``" 와 "``tp`` 의 덱" 이 그대로 여기
        ``chooser`` 와 ``zones``/``owner`` 로 와 있다.

        ``owner`` 가 :attr:`PlayerRef.OPPONENT` 면 **빈 집합**이다 — 남의
        자리에서 고르라는 규칙이 남의 자리를 볼 권리까지 주지는 않는다
        (상대 패에서 고르게 하는 효과는 공개 효과가 따로 필요하다).

        ``None`` (양쪽) 이면 자리 이름을 그대로 돌려주되, 실제로 열리는
        것은 **보는 사람 자신의 자리뿐**이다 —
        :func:`~engine.game_state_view._zone_view` 가 그것을 지킨다.
        """
        if self.owner is PlayerRef.OPPONENT:
            return frozenset()
        return self.zones

    def canonical_state(self) -> tuple:
        return (
            tuple(sorted(z.value for z in self.zones)),
            self.owner.value if self.owner is not None else None,
            self.require.canonical_state() if self.require is not None else None,
            self.exclude_source,
        )

    def to_dict(self) -> dict:
        data: dict = {"zones": sorted(z.value for z in self.zones)}
        if self.owner is not None:
            data["owner"] = self.owner.value
        if self.require is not None:
            data["require"] = self.require.to_dict()
        if self.exclude_source:
            data["exclude_source"] = True
        return data

    def describe_ko(self) -> str:
        who = str(self.owner) if self.owner is not None else "양쪽"
        where = "/".join(sorted(z.value for z in self.zones))
        what = f" ({self.require.describe_ko()})" if self.require is not None else ""
        mine = " (자신 제외)" if self.exclude_source else ""
        return f"{who} {where}{what}{mine}"


@dataclass(frozen=True, slots=True)
class ChoiceSpec:
    """
    "무엇을 몇 장 고르라" 는 **요구**. 후보도 선택도 들어 있지 않다.

    ``minimum == maximum`` 이면 정확히 그 수, ``minimum=0`` 이면 고르지 않아도
    된다 ("최대 2장까지").
    """

    source: CandidateSource
    minimum: int = 1
    maximum: int = 1
    chooser: PlayerRef = PlayerRef.CONTROLLER
    allow_duplicates: bool = False
    """
    같은 카드를 두 번 고를 수 있는가. 거의 언제나 거짓이다 — 한 장의 카드를
    두 번 릴리스할 수는 없다.
    """

    def __post_init__(self) -> None:
        if self.minimum < 0:
            raise ValueError(f"최소 장수는 음수일 수 없습니다: {self.minimum}")
        if self.maximum < self.minimum:
            raise ValueError(
                f"최대({self.maximum})가 최소({self.minimum})보다 작습니다."
            )

    def looked_at_zones(self) -> frozenset[Zone]:
        """
        고르는 사람이 들여다봐야 하는 자리들.

        **고르는 사람이 컨트롤러일 때만** 답한다. 관측은 컨트롤러의
        시점으로 만들어지므로, 상대가 고르는 효과에서 컨트롤러의 관측을
        넓히면 엉뚱한 사람이 보게 된다.
        """
        if self.chooser is not PlayerRef.CONTROLLER:
            return frozenset()
        return self.source.looked_at_zones()

    @property
    def is_optional(self) -> bool:
        """고르지 않아도 되는가."""
        return self.minimum == 0

    @property
    def is_exact(self) -> bool:
        return self.minimum == self.maximum

    def canonical_state(self) -> tuple:
        return (
            self.source.canonical_state(),
            self.minimum,
            self.maximum,
            self.chooser.value,
            self.allow_duplicates,
        )

    def to_dict(self) -> dict:
        return {
            "source": self.source.to_dict(),
            "minimum": self.minimum,
            "maximum": self.maximum,
            "chooser": self.chooser.value,
            "allow_duplicates": self.allow_duplicates,
        }

    def describe_ko(self) -> str:
        amount = (
            f"{self.minimum}장"
            if self.is_exact
            else f"{self.minimum}~{self.maximum}장"
        )
        return f"{self.source.describe_ko()} 에서 {amount} 선택"

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return self.describe_ko()


@dataclass(frozen=True, slots=True)
class CandidateSet:
    """
    지금 관측에서 **고를 수 있는 것들.** 선택이 아니다.

    셋으로 나뉜다.

    ``eligible``
        확실히 후보다.
    ``undecided``
        후보인지 **모른다.** 조건이 카드 정의를 요구하는데 뒷면이거나,
        정의를 읽을 수 없는 경우다. 세어서도 안 되고 버려서도 안 된다.
    ``reasons``
        왜 모르는지. 조건 계층이 한 말을 그대로 전한다.
    ``unchecked``
        **아예 들여다보지 못한 곳들.** 상대의 패나 덱처럼 통째로 가려진
        존이다. 거기 후보가 있는지 없는지 알 수 없으므로, 비어 있다고
        "후보가 없다" 고 말할 수 없다.

    ``undecided`` 를 ``eligible`` 에 넣으면 못 치를 비용을 치를 수 있다고
    하게 되고, 버리면 치를 수 있는 비용을 못 치른다고 하게 된다.

    ``unchecked`` 는 ``undecided`` 와 **다른 사실**이다. 저쪽은 "이 카드가
    후보인지 모른다" 이고 이쪽은 "저기를 못 봤다" 다. 가려진 존의 카드는
    지목할 수조차 없으므로 ``InstanceId`` 로 적을 수 없고, 그래서 자리
    이름만 남긴다.
    """

    eligible: tuple[InstanceId, ...] = ()
    undecided: tuple[InstanceId, ...] = ()
    reasons: tuple[str, ...] = ()
    unchecked: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("eligible", "undecided", "reasons", "unchecked"):
            if not isinstance(getattr(self, name), tuple):
                raise TypeError(f"{name} 은 tuple 이어야 합니다 — 후보는 불변입니다.")
        overlap = set(self.eligible) & set(self.undecided)
        if overlap:
            raise ValueError(
                f"같은 카드가 확정과 미확정 양쪽에 있습니다: {sorted(o.value for o in overlap)}"
            )

    @property
    def certain_count(self) -> int:
        """확실한 후보 수. **미확정은 세지 않는다.**"""
        return len(self.eligible)

    @property
    def possible_count(self) -> int:
        """가장 좋게 봐도 이만큼. 미확정이 전부 후보라고 가정한 수다."""
        return len(self.eligible) + len(self.undecided)

    @property
    def has_undecided(self) -> bool:
        return bool(self.undecided)

    @property
    def fully_checked(self) -> bool:
        """
        **볼 수 있는 곳을 전부 봤는가.**

        거짓이면 "후보가 없다" 고 말할 수 없다 — 못 본 곳에 있을 수 있다.
        """
        return not self.unchecked

    def contains(self, instance: InstanceId) -> bool:
        """확실한 후보에 들어 있는가."""
        return instance in self.eligible

    def canonical_state(self) -> tuple:
        return (
            tuple(i.value for i in self.eligible),
            tuple(i.value for i in self.undecided),
            self.reasons,
            self.unchecked,
        )

    def to_dict(self) -> dict:
        return {
            "eligible": [i.value for i in self.eligible],
            "undecided": [i.value for i in self.undecided],
            "reasons": list(self.reasons),
            "unchecked": list(self.unchecked),
        }

    def __len__(self) -> int:
        return self.certain_count

    def __iter__(self):
        return iter(self.eligible)

    def __str__(self) -> str:  # pragma: no cover - 표시용
        tail = f" +{len(self.undecided)}?" if self.undecided else ""
        return f"<CandidateSet {self.certain_count}{tail}>"


@dataclass(frozen=True, slots=True)
class Selection:
    """
    플레이어가 **실제로 고른 것.** 후보가 아니다.

    순서를 유지한다 — 고른 순서가 의미를 갖는 효과가 있고, 없더라도
    정렬하면 원래 순서를 되살릴 수 없다.
    """

    chosen: tuple[InstanceId, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.chosen, tuple):
            raise TypeError("chosen 은 tuple 이어야 합니다 — 선택은 불변입니다.")

    @classmethod
    def of(cls, *instances: InstanceId) -> "Selection":
        return cls(tuple(instances))

    @property
    def is_empty(self) -> bool:
        return not self.chosen

    @property
    def has_duplicates(self) -> bool:
        return len(set(self.chosen)) != len(self.chosen)

    def canonical_state(self) -> tuple:
        return tuple(i.value for i in self.chosen)

    def to_dict(self) -> dict:
        return {"chosen": [i.value for i in self.chosen]}

    def __len__(self) -> int:
        return len(self.chosen)

    def __iter__(self):
        return iter(self.chosen)

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return "[" + ", ".join(str(i) for i in self.chosen) + "]"


__all__ = ["CandidateSource", "ChoiceSpec", "CandidateSet", "Selection"]
