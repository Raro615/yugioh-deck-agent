"""
DuelRunner — **정책 둘에게 듀얼 한 판을 맡긴다** (Phase 3-A).

    Duel                         엔진 (Phase 2-AO, V1 FREEZE)
      ↓  view(seat) · legal_actions(seat)
    Policy.decide(view, legal)   AI
      ↓  PlayerAction
    Duel.apply(action)           엔진
      ↓
    Transcript                   무슨 일이 있었는가

러너가 하는 일은 **전달**뿐이다
-------------------------------
규칙을 만들지 않는다. 판을 읽지 않는다. 고르지도 않는다. 하는 일은 셋이다.

1. 엔진에게 "지금 누구 차례이고 무엇이 허가되는가" 를 묻는다.
2. 그 자리의 **관측**과 후보 목록만 정책에게 준다.
3. 정책이 고른 것을 **다시 확인하고** 엔진에게 넘긴다.

정책의 말은 허가가 아니다
-------------------------
3번이 요점이다. 정책이 목록에 없는 것을 돌려주면 **거절한다** — 엔진이
``UNKNOWN`` 을 허가로 바꾸지 않는 것과 같은 자리다. 거절은 조용하지 않다:
:class:`Transcript` 에 남는다.

정책이 판을 들고 다니지 않는다
------------------------------
:meth:`~engine.duel.Duel.view` 가 만든 스냅숏만 넘어간다. :class:`Duel`
도 :class:`~engine.state.game_state.GameState` 도 정책에게 가지 않으므로,
정책은 상대 패를 볼 수도 판을 바꿀 수도 없다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.action import PlayerAction
from engine.duel import Duel, DuelStep
from engine.state.game_state import DuelResult

from agent.policy import Decision, Policy


class RunnerError(RuntimeError):
    """러너를 쓰는 방법이 틀렸을 때."""


#: 한 판이 아무리 길어도 이보다 많이 가면 **멈춘 것이다.**
#:
#: 지금 고를 수 있는 행위로는 끝이 보장된다 (페이즈 넘기기는 언제나
#: 전진하고, 소환은 자리와 횟수가 유한하다). 그래도 상한을 둔다 — 보장이
#: 깨졌을 때 **영원히 도는 대신 소리를 내야** 한다.
MAX_STEPS: int = 5_000


@dataclass(frozen=True, slots=True)
class TranscriptEntry:
    """걸음 하나. **정책이 무엇을 골랐고 엔진이 무엇을 했는가.**"""

    index: int
    seat: int
    policy: str
    action: "PlayerAction | None"
    accepted: bool
    reason: str

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        what = self.action.kind.value if self.action is not None else "(없음)"
        mark = "" if self.accepted else " ✘"
        return f"{self.index:>4} P{self.seat} {self.policy}: {what}{mark}"


@dataclass(frozen=True, slots=True)
class Transcript:
    """
    한 판의 기록. **재현과 학습이 둘 다 이것을 읽는다.**

    :attr:`refusals` 가 비어 있지 않으면 정책이 규약을 어긴 것이고, 그것은
    듀얼의 사실이 아니라 **정책의 결함**이다. 그래서 따로 센다.
    """

    entries: tuple[TranscriptEntry, ...] = ()
    result: "DuelResult | None" = None
    steps: int = 0
    rule_steps: int = 0
    """고르지 않아도 일어난 일의 수 (드로우 따위)."""

    @property
    def refusals(self) -> tuple[TranscriptEntry, ...]:
        return tuple(entry for entry in self.entries if not entry.accepted)

    @property
    def finished(self) -> bool:
        return self.result is not None

    def by_seat(self, seat: int) -> tuple[TranscriptEntry, ...]:
        return tuple(entry for entry in self.entries if entry.seat == seat)

    def canonical_state(self) -> tuple:
        """
        **같은 판인가**를 비교할 수 있는 모양. 재현 시험이 이것을 쓴다.

        정책 이름은 넣지 않는다 — 같은 수를 둔 두 정책은 같은 판을 만든다.
        """
        return (
            tuple(
                (entry.seat, entry.action.canonical_state() if entry.action else None)
                for entry in self.entries
                if entry.accepted
            ),
            None if self.result is None else (self.result.winner, self.result.reason),
        )

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        end = "진행 중" if self.result is None else self.result.reason
        return f"{len(self.entries)}걸음 · 규칙 {self.rule_steps}회 · {end}"


@dataclass
class DuelRunner:
    """
    듀얼 하나를 정책 둘에게 맡겨 끝까지 돌린다.

    ``policies`` 는 자리 번호로 찾는다 — ``policies[0]`` 이 P0 의 것이다.
    """

    duel: Duel
    policies: "tuple[Policy, Policy]"
    _entries: list[TranscriptEntry] = field(default_factory=list)
    _rule_steps: int = 0

    def __post_init__(self) -> None:
        if len(self.policies) != 2:
            raise RunnerError(
                f"정책은 자리마다 하나씩 둘입니다: {len(self.policies)}개"
            )
        for seat, policy in enumerate(self.policies):
            if not hasattr(policy, "decide"):
                raise RunnerError(f"P{seat} 의 정책에 decide 가 없습니다.")

    # ------------------------------------------------------------------
    def step(self) -> "TranscriptEntry | None":
        """
        한 걸음 나아간다. 끝났거나 더 갈 수 없으면 ``None``.

        **고르지 않아도 일어나는 일이 먼저다.** 드로우가 밀려 있으면
        정책에게 묻지 않는다 — 뽑지 않겠다고 고를 수 없기 때문이다.
        """
        if self.duel.is_over:
            return None

        if self.duel.advance() is not None:
            self._rule_steps += 1
            return None

        seat = self.duel.to_act
        policy = self.policies[seat]
        legal = self.duel.legal_actions(seat)

        # **관측과 후보만 넘어간다.** Duel 도 GameState 도 가지 않는다.
        chosen = policy.decide(self.duel.view(seat), legal)

        decision = self._judge(seat, policy, legal, chosen)
        if not decision.accepted:
            return self._record(decision)

        applied: DuelStep = self.duel.apply(decision.action)
        return self._record(
            Decision(
                seat,
                policy.name,
                decision.action,
                applied.accepted,
                applied.reason,
            )
        )

    def _judge(self, seat, policy, legal, chosen) -> Decision:
        """
        정책이 고른 것을 **다시 본다.** 정책의 말은 허가가 아니다.
        """
        name = getattr(policy, "name", type(policy).__name__)
        if chosen is None:
            if legal.allowed:
                return Decision(
                    seat,
                    name,
                    None,
                    False,
                    f"고를 수 있는 것이 {len(legal.allowed)}개인데 "
                    "정책이 아무것도 고르지 않았습니다.",
                )
            return Decision(
                seat, name, None, False, "고를 수 있는 행위가 없습니다."
            )
        if not isinstance(chosen, PlayerAction):
            return Decision(
                seat, name, None, False,
                f"정책이 PlayerAction 이 아닌 것을 돌려주었습니다: "
                f"{type(chosen).__name__}",
            )
        if chosen.actor != seat:
            return Decision(
                seat, name, chosen, False,
                f"P{seat} 의 차례인데 P{chosen.actor} 의 행위를 "
                "돌려주었습니다.",
            )
        if chosen not in legal.allowed:
            return Decision(
                seat, name, chosen, False,
                f"{chosen.kind.value} 는 허가된 후보가 아닙니다.",
            )
        return Decision(seat, name, chosen, True)

    def _record(self, decision: Decision) -> TranscriptEntry:
        entry = TranscriptEntry(
            index=len(self._entries),
            seat=decision.seat,
            policy=decision.policy,
            action=decision.action,
            accepted=decision.accepted,
            reason=decision.reason,
        )
        self._entries.append(entry)
        return entry

    # ------------------------------------------------------------------
    def run(self, *, max_steps: int = MAX_STEPS) -> Transcript:
        """
        끝까지 돌린다.

        **거절이 나오면 멈춘다.** 정책이 규약을 어긴 뒤에도 계속 돌리면
        같은 거절이 끝없이 반복되고, 기록이 그것으로 채워진다.
        """
        for _ in range(max_steps):
            if self.duel.is_over:
                break
            entry = self.step()
            if entry is not None and not entry.accepted:
                break
        else:
            raise RunnerError(
                f"{max_steps}걸음 안에 끝나지 않았습니다. 정책이 전진하지 "
                "않는 수를 되풀이하고 있을 수 있습니다."
            )
        return self.transcript()

    def transcript(self) -> Transcript:
        return Transcript(
            entries=tuple(self._entries),
            result=self.duel.result,
            steps=len(self._entries),
            rule_steps=self._rule_steps,
        )


def play(
    duel: Duel, policies: "tuple[Policy, Policy]", *, max_steps: int = MAX_STEPS
) -> Transcript:
    """한 줄로 한 판. 러너를 따로 들고 있을 일이 없을 때 쓴다."""
    return DuelRunner(duel, policies).run(max_steps=max_steps)


__all__ = [
    "DuelRunner",
    "RunnerError",
    "Transcript",
    "TranscriptEntry",
    "MAX_STEPS",
    "play",
]
