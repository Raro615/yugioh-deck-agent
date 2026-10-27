"""
Simulation — **후보 하나를 실제 엔진으로 해 보는 자리** (Phase 3-C).

    Original Duel
         │  clone()
         ├──→ Fork A ──apply(A)──→ GameStateView(viewer)
         ├──→ Fork B ──apply(B)──→ GameStateView(viewer)
         └──→ Fork C ──apply(C)──→ GameStateView(viewer)

가장 중요한 불변조건
--------------------
**SEARCH MUST NEVER CHANGE THE REAL GAME.**

그래서 되감지 않는다. 원본에 적용한 뒤 되돌리는 방식은 "되돌리기가 완전
한가" 를 영원히 증명해야 하는 빚을 지는데, :meth:`GameState.clone` 은 그
빚이 없다 — 원본을 **건드리지 않으므로** 되돌릴 것이 없다 (§10).

난수원을 함께 쓰지 않는다
-------------------------
``GameState`` 에는 복제가 둘 있고, 하나는 **써서는 안 된다.**

``project()``   난수원을 원본과 **함께 쓴다.** 효과 해결의 계획 단계를
                위한 것이고(Phase 2-AH), 탐색에 쓰면 시뮬레이션이 꺼낸
                난수가 진짜 판의 좌표를 밀어 버린다 — 같은 seed 로 다시
                돌렸을 때 다른 판이 된다.
``clone()``     난수원을 **꺼낸 횟수까지 복제한다.** 탐색이 쓸 것은 이쪽이다.

측정으로 확인했다: 사본에서 셔플하면 사본의 ``draws`` 만 올라가고 원본은
그대로다. ``project()`` 로 같은 일을 하면 **원본의 ``draws`` 가 올라간다.**

가짜 실행기를 만들지 않는다
---------------------------
``fake_apply`` · ``simple_apply`` · ``estimated_apply`` 를 두지 않는다
(§15). 사본에 적용하는 것은 진짜 :meth:`Duel.apply` 이고, 그래서
시뮬레이션이 본 미래는 **그 수를 진짜로 두었을 때의 미래와 같다.** 다르면
AI 는 있지도 않은 미래를 보고 판단한다.

내다본 결과로 넘기는 것은 **관측뿐이다**
----------------------------------------
:class:`SimulationResult` 는 사본의 ``GameState`` 를 들고 있지 않다.
들고 있으면 탐색 정책이 그것을 통해 상대 패를 읽을 수 있고, 그러면
"시뮬레이션을 갖고 있다" 는 이유로 관측 경계가 사라진다 (§18). 사본은
관측을 뜬 뒤 버려진다.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum

from engine.action import PlayerAction, PlayerActionKind
from engine.duel import Duel, DuelStep, LegalActions
from engine.spell_activation import duel_components
from engine.game_state_view import GameStateView
from engine.validation import ValidationCode, unknown_codes


class SimulationError(RuntimeError):
    """시뮬레이터를 잘못 쓸 때."""


class SimulationStatus(str, Enum):
    """
    후보 하나를 해 본 결과가 **어떻게 끝났는가.**

    실패를 한 칸으로 뭉치지 않는다 (§17). "허가된 후보가 아니다" 와
    "규칙이 아직 없다" 와 "예외가 났다" 는 전부 다른 사실이고, 어느 것도
    **자동으로 최악의 점수가 되지 않는다.**
    """

    SUPPORTED = "supported"
    """엔진이 적용했다. 미래 상태를 볼 수 있다."""
    NOT_A_CANDIDATE = "not_a_candidate"
    """지금 허가된 후보가 아니다. 탐색이 만들어 낸 수라는 뜻이다 (§16 · §47)."""
    UNKNOWN = "unknown"
    """규칙이 아직 없다. **모른다는 것이지 나쁘다는 것이 아니다** (§17 · §28)."""
    REFUSED = "refused"
    """엔진이 규칙에 따라 거절했다."""
    ERROR = "error"
    """실행 중 예외가 났다. 숨기지 않는다."""

    @property
    def gives_a_future(self) -> bool:
        """미래 상태를 볼 수 있는가."""
        return self is SimulationStatus.SUPPORTED


#: 엔진이 "판단을 확정할 수 없다" 고 말하는 코드들. 이것을 거절과 섞지 않는다.
#:
#: **엔진에서 파생한다** (Phase 3-E-40). 전에는 이 자리에 다섯 멤버를 손으로
#: 적어 두었고, 그래서 ``engine.validation`` 이 묶음 주석으로 말하던 것과
#: 어긋났다 — ``HIDDEN_CARD`` 와 ``PRIORITY_STATE_STALE`` 이 빠져 있었다
#: (Phase 3-E-39 가 측정). 같은 뜻을 두 곳에서 관리하면 반드시 어긋나므로
#: 사본을 없애고 :func:`~engine.validation.unknown_codes` 하나만 읽는다.
#:
#: 이 계층이 정하는 것은 **그 다음 한 걸음뿐이다** — 모름이면
#: :attr:`SimulationStatus.UNKNOWN`, 아니면 :attr:`SimulationStatus.REFUSED`.
#: 어느 코드가 모름인지는 엔진이 정한다.
_UNKNOWN_CODES: frozenset[ValidationCode] = unknown_codes()


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """
    후보 하나를 해 본 결과. **사본의 판을 들고 있지 않다.**

    :attr:`future` 는 그 수를 둔 **뒤의 관측**이고, 보는 사람은
    :attr:`viewer` 다. 성공하지 못했으면 ``None`` 이다 — 없는 미래를
    꾸며 내지 않는다.
    """

    action: PlayerAction
    status: SimulationStatus
    viewer: int
    reason: str = ""
    code: "ValidationCode | None" = None
    future: "GameStateView | None" = None
    unsupported: tuple[str, ...] = ()
    """
    그 미래의 **다음 자리**에서 지원하지 않아 후보가 되지 못한 것들
    (Phase 6-AB 최종 보완 ④).

    🔴 **이것이 비어 있지 않으면 그 미래는 끝까지 검증된 것이 아니다.**
    :attr:`SimulationStatus.SUPPORTED` 는 "엔진이 이 행동을 적용했다" 는
    뜻이고 "그 뒤에 할 수 있는 것을 다 안다" 는 뜻이 아니다. 두 사실을
    한 칸으로 들고 있으면 탐색이 **지원 범위의 경계를 판의 사실로**
    읽는다 — 미지원 때문에 후보가 적은 미래가 "조용한 판" 으로 보인다.

    규칙이 막은 보류는 여기 오지 않는다 (``LegalActions.unsupported()``).
    """

    @property
    def fully_supported(self) -> bool:
        """
        미래가 있고 **그 자리에 미지원 보류가 없는가.**

        🔴 점수를 매기는 쪽이 "완전히 검증된 미래" 를 말하려면 이 칸을
        봐야 한다. :attr:`status` 만 보면 경계를 못 본다.
        """
        return self.status.gives_a_future and not self.unsupported

    def __post_init__(self) -> None:
        if self.status.gives_a_future and self.future is None:
            raise SimulationError(
                "적용에 성공했는데 미래 관측이 없습니다 — 둘은 함께 옵니다."
            )
        if not self.status.gives_a_future and self.future is not None:
            raise SimulationError(
                f"{self.status.value} 인데 미래 관측이 있습니다 — "
                "실패한 시뮬레이션의 미래를 꾸며 내지 않습니다."
            )
        if self.unsupported and not self.status.gives_a_future:
            #: 🔴 미래가 없으면 "그 미래의 다음 자리" 도 없다. 이 칸이
            #: 채워져 있다면 어디선가 다른 자리의 보류를 옮겨 적은 것이다.
            raise SimulationError(
                f"{self.status.value} 인데 미래의 미지원 사유가 있습니다 — "
                "없는 미래의 경계를 적지 않습니다."
            )

    def describe_ko(self) -> str:  # pragma: no cover - 표시용
        return f"{self.action} → {self.status.value}" + (
            f" ({self.reason})" if self.reason else ""
        )


@dataclass
class Simulator:
    """
    듀얼 하나에 묶여, **후보를 해 보고 관측만 돌려주는** 좁은 창.

    탐색 정책이 :class:`Duel` 을 직접 들지 않는 이유가 이 클래스다. 정책이
    듀얼을 들면 ``apply`` 로 진짜 판을 바꿀 수 있고, ``state`` 로 상대 패를
    읽을 수 있다. 이 창은 둘 다 **줄 수 없는 모양**이다 —
    :meth:`simulate` 가 돌려주는 것은 관측과 상태 하나뿐이다.

    :attr:`simulations` 는 몇 번 해 봤는지의 셈이다. 판단에 쓰지 않는다.
    """

    duel: Duel
    simulations: int = 0
    _forks: int = 0

    # ------------------------------------------------------------------
    # 읽기 — 진짜 판을 바꾸지 않는 것들만
    # ------------------------------------------------------------------
    def legal_actions(self, seat: int) -> LegalActions:
        return self.duel.legal_actions(seat)

    def view(self, seat: int) -> GameStateView:
        return self.duel.view(seat)

    def state_hash(self) -> str:
        """
        지금 판의 지문. **되돌려 읽을 수 없는 요약**이므로 흔적에 남겨도
        가려진 정보가 새지 않는다 (§31).
        """
        return self.duel.state.state_hash()

    def random_draws(self) -> int:
        """
        진짜 판의 난수원이 **몇 번 꺼냈는가.** 재현의 좌표다.

        탐색이 끝난 뒤 이 값이 그대로여야 한다 (§13 · §14).
        """
        return self.duel.state.randomness.draws

    @property
    def turn_number(self) -> int:
        return self.duel.state.turn.turn_number

    @property
    def phase(self):
        return self.duel.state.turn.phase

    # ------------------------------------------------------------------
    # 포크
    # ------------------------------------------------------------------
    def _fork(self) -> Duel:
        """
        **판만 복제하고 나머지는 그대로 쓴다. 단 기록은 떼어 낸다.**

        ``priority`` 는 frozen 이라 공유해도 바뀌지 않는다. 수행기 등록부는
        듀얼마다 달라지는 상태를 들지 않으므로 공유하는 것이 오히려 옳다 —
        그래야 사본이 **진짜와 같은 규칙**으로 돈다 (§15).

        🔴 **기록만은 공유하면 안 된다** (Phase 6-B). ``_executor`` ·
        ``_activator`` · ``_resolver`` 가 journal 을 들게 된 뒤로는, 그대로
        공유하면 **사본에서 돌린 전개가 진짜 듀얼의 기록에 남는다.** 사본은
        버려지는데 기록은 남으므로, 그 기록은 실제 판과 **모순된다** —
        "기록된 상태 변경은 실제 적용된 상태와 모순되지 않는다" 가 깨진다.

        그래서 사본은 **자기 기록**으로 바꿔 끼운다.

        🔴 **Phase 6-AB 가 "기록하지 않는 한 벌" 을 "물려받은 기록" 으로
        바꿨다.** 그 전까지는 ``journal=False`` 였고, 그래서 사본이 **과거
        사건을 잃었다** — 유발 후보는 기록된 사건에서 나오므로 (Phase 6-Z)
        사본의 ``legal_actions`` 가 원본과 **다른 답**을 냈다. 실측::

            원본 후보 5 (유발 있음)   사본 후보 4 (유발 없음)

        미래를 재는 일에 역사가 필요하지 않다는 그때의 판단이 **틀렸다** —
        지금 무엇을 발동할 수 있는가가 역사에 달려 있다.

        🔴 **6-B 의 요구는 그대로 지킨다.** 사본은 부모의 기록 **객체**를
        쓰지 않는다: 부모의 사건들을 씨앗으로 받은 **새 ``EventJournal``**
        이고 (``EventJournal(events=…)`` 가 그 생성자다), 사본의 전개는 그
        새 객체에만 쌓인다. 그래서 사본의 역사가 진짜 듀얼의 기록에 남지
        않는다.

        🔴 **형제 분기도 섞이지 않는다.** 포크마다 새 객체를 만들고, 씨앗으로
        넘기는 ``JournalEvent`` 들은 불변(frozen)이므로 공유해도 한쪽의
        전개가 다른 쪽에 보이지 않는다.

        ``consumed_events`` · ``timing_floor`` 는 값(``frozenset`` · ``int``)
        이므로 ``dataclasses.replace`` 가 그대로 값으로 가져간다 — 사본의
        소비가 부모의 목록을 늘리지 않는다 (Phase 6-AA ``test_d04``).
        """
        self._forks += 1
        return dataclasses.replace(
            self.duel,
            state=self.duel.state.clone(),
            **duel_components(
                **self._forked_journal(),
                chooser=self._forked_chooser(),
            ),
        )

    def _forked_journal(self) -> dict:
        """
        ``duel_components`` 에게 **기록을 어떻게 만들라** 고 하는 말 (6-AB).

        부모의 사건을 씨앗으로 넘긴다 — ``seed_events`` 가 그것으로 **새
        ``EventJournal``** 을 만든다.

        🔴 **여기서 ``EventJournal`` 을 만들지 않는다.** "듀얼 하나에 기록
        하나" 를 지키려면 기록을 만드는 자리가 하나여야 하고 (production
        전수로 세는 감사가 있다:
        ``tests/test_result_actor_provenance_design_audit.py::test_09``), 그
        자리는 ``engine.spell_activation.duel_components`` 다. 처음에는 이
        함수가 직접 만들었고, 그 감사가 **설계대로 잡았다.**

        부모가 기록하지 않는 듀얼이면 (``journal is None``) 사본도 기록하지
        않는다 — 없는 역사를 지어내지 않는다.
        """
        parent = self.duel.journal
        if parent is None:
            return {"journal": False}
        return {"seed_events": tuple(parent)}

    def _forked_chooser(self):
        """
        부모와 **같은 정책**으로 해결 시점 선택을 하는 것 (Phase 6-AB).

        사본은 실행기 한 벌을 새로 만들므로 (``duel_components``) 이 자리를
        채우지 않으면 **사본 안에서만** 해결 시점 선택이 거절된다. 실측한
        증상 — 사본에서 발동은 되는데 해결이::

            아직 고르지 않은 대상이 있습니다: @primary

        로 멈췄다. 그러면 "해결할 수 있는 효과" 가 원본과 사본에서 달라지고,
        미래의 값이 규칙이 아니라 배선을 재게 된다.

        🔴 **고르는 사람을 지어내지 않는다.** 부모에게 없으면 사본도 없다 —
        그 듀얼에서는 아직 정해지지 않은 선택이 실제로 거절되는 것이 맞다.

        🔴 **고르는 사람이 ``forked()`` 를 주지 않으면 쓰지 않는다**
        (6-AB 보완이 고친 자리). 6-AB 는 그런 고르는 사람을 **그대로
        공유했고**, 그 근거는 "모양이 ``choose(request)`` 하나뿐이니 기록을
        가졌는지 알 방법이 없다" 였다. 🔴 **그 추론이 거꾸로였다** — 알 수
        없으면 공유가 아니라 **보류**가 안전한 쪽이다. 실측한 증상: 상태
        있는 정책으로 ``simulate`` 를 한 번 돌리자 부모 정책의 호출 수가
        0 → 1 이 됐다. 사본이 미래를 **재기만** 해야 하는데 부모를 밀었다.

        그래서 지금은:

        - ``forked()`` 가 있으면 그것이 준 것을 쓴다
          (:meth:`integration.autonomy.PolicyChooser.forked` — 같은 정책 ·
          빈 기록. 그쪽도 정책이 ``forked()`` 를 주지 않으면 ``None`` 이다).
        - 없거나 ``None`` 을 주면 **사본에 고르는 사람이 없다.** 그러면 아직
          정해지지 않은 선택이 사본 안에서 거절되고, 그 거절은 결과에 보인다.
          조용히 오염시키는 것보다 보이는 거절이 낫다.
        """
        resolver = self.duel._resolver
        executor = getattr(resolver, "executor", None)
        chooser = getattr(executor, "chooser", None)
        if chooser is None:
            return None
        forked = getattr(chooser, "forked", None)
        if not callable(forked):
            return None
        return forked()

    @staticmethod
    def _settle_forced_passes(fork: Duel) -> "DuelStep | None":
        """
        **고를 것이 없는 응답 창을 사본에서 닫는다** (Phase 3-E-11).

        발동은 상대에게 응답 기회를 연다 (RULE-CHAIN-001). 그 기회에서
        **패스밖에 할 수 없다면 패스는 고르는 일이 아니다** — 드로우가
        행위 목록에 없는 것과 같은 이유다 (``Duel.advance`` 의 설명).

        그래서 사본에서 그 걸음을 대신 밟는다. 깊이를 늘리는 것이 아니다:
        상대의 **선택을 예측하지 않는다.** 선택할 것이 하나라도 있으면
        **즉시 멈춘다** — 그 자리가 진짜 결정 지점이고, 거기까지가 깊이 1 이다.

        이것을 하지 않으면 깊이 1 의 미래가 **체인 도중**의 위치가 된다.
        그 위치는 아무도 고르는 자리가 아니고, 그것을 재면 대상이 다른 두
        발동이 같은 점수를 받는다 (Phase 3-E-4 가 세운 구분이 사라진다).
        """
        last: "DuelStep | None" = None
        guard = 0
        while fork.priority.is_open and guard < 8:
            guard += 1
            legal = fork.legal_actions()
            passes = [
                a for a in legal.allowed if a.kind is PlayerActionKind.PASS
            ]
            if not passes or len(passes) != len(legal.allowed):
                # 고를 것이 있다 — 그것은 결정이므로 여기서 멈춘다.
                break
            last = fork.apply(passes[0])
            if not last.accepted:
                break
        return last

    def simulate(self, action: PlayerAction, *, viewer: int) -> SimulationResult:
        """
        후보 하나를 사본에서 해 본다. **진짜 판은 건드리지 않는다.**

        ``viewer`` 는 미래를 **누구의 눈으로 볼 것인가**다. 두는 사람과
        보는 사람이 다를 수 있으므로 따로 받는다.
        """
        if not isinstance(action, PlayerAction):
            raise SimulationError(
                f"PlayerAction 이 필요합니다: {type(action).__name__}"
            )
        if viewer not in (0, 1):
            raise SimulationError(f"보는 자리는 0 또는 1 입니다: {viewer}")

        self.simulations += 1

        # **후보 목록에 있는지 먼저 본다.** 엔진의 ``apply`` 도 다시 보지만,
        # 거기서는 "허가된 후보가 아니다" 가 "규칙이 없다" 와 같은 코드로
        # 나와서 둘을 가를 수 없다 (§16 · §47).
        legal = self.duel.legal_actions(action.actor)
        if action not in legal.allowed:
            return SimulationResult(
                action=action,
                status=SimulationStatus.NOT_A_CANDIDATE,
                viewer=viewer,
                reason="지금 허가된 후보가 아닙니다 — 탐색은 후보만 해 봅니다.",
            )

        fork = self._fork()
        try:
            step: DuelStep = fork.apply(action)
        except Exception as error:  # noqa: BLE001 - 숨기지 않고 상태로 남긴다
            return SimulationResult(
                action=action,
                status=SimulationStatus.ERROR,
                viewer=viewer,
                reason=f"{type(error).__name__}: {error}",
            )

        if step.accepted:
            settled = self._settle_forced_passes(fork)
            #: 🔴 **그 미래의 경계를 함께 돌려준다** (6-AB 최종 보완 ④).
            #: 사본의 다음 자리에서 **지원하지 않아 오르지 못한** 후보가
            #: 있으면 그 미래는 끝까지 검증된 것이 아니다. 사본은 버려지므로
            #: 지금 읽지 않으면 그 사실이 영영 밖으로 나가지 않는다.
            return SimulationResult(
                action=action,
                status=SimulationStatus.SUPPORTED,
                viewer=viewer,
                reason=settled.reason if settled is not None else step.reason,
                code=step.code,
                # 사본은 여기서 버려진다. 넘어가는 것은 관측뿐이다.
                future=fork.view(viewer),
                unsupported=tuple(
                    f"{held.kind.value} [{held.missing}]: {held.reason}"
                    for held in fork.legal_actions(fork.to_act).unsupported()
                ),
            )

        status = (
            SimulationStatus.UNKNOWN
            if step.code in _UNKNOWN_CODES
            else SimulationStatus.REFUSED
        )
        return SimulationResult(
            action=action,
            status=status,
            viewer=viewer,
            reason=step.reason,
            code=step.code,
        )

    def fork_after(self, action: PlayerAction) -> "Simulator | None":
        """
        그 수를 둔 **사본에 묶인 새 시뮬레이터**. 깊이를 늘릴 자리다.

        Phase 3-C 의 :class:`~agent.search.SearchPolicy` 는 ``depth=1`` 만
        지원하므로 **이것을 부르지 않는다.** 그래도 두는 이유는 깊이를
        늘리는 일이 "구조를 새로 만드는 일" 이 아님을 보이기 위해서다 —
        depth-2 는 이 메서드를 한 번 더 부르는 것이고, 그때도 정책에게
        가는 것은 여전히 관측뿐이다.

        적용에 실패하면 ``None`` 이다. 실패한 미래를 이어 가지 않는다.
        """
        fork = self._fork()
        try:
            step = fork.apply(action)
        except Exception:  # noqa: BLE001
            return None
        if not step.accepted:
            return None
        return Simulator(duel=fork)

    def __repr__(self) -> str:  # pragma: no cover - 표시용
        return f"<Simulator 시뮬레이션 {self.simulations}회 포크 {self._forks}회>"


__all__ = [
    "SimulationError",
    "SimulationStatus",
    "SimulationResult",
    "Simulator",
]
