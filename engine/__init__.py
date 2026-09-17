"""
Duel Engine.

``docs/duel-engine-design.md`` 의 설계를 구현한다. 현재는 Phase 1 —
규칙 판정 없이 듀얼 **상태**만 정확하게 표현하는 데이터 계층이다.

이 패키지는 ``core/`` 와 ``analysis/`` 를 **읽기만 한다.** 카드 정의는
:class:`~core.card_repository.CardRepository` 가 소유하고, 엔진은
:class:`~engine.state.card_instance.CardInstance` 로 듀얼 중의 상태만
따로 갖는다.


Phase 1 에서 의도적으로 만들지 않은 것 (TODO)
--------------------------------------------

구현 중에 "이게 필요해 보인다" 고 느낀 지점들. 각각 해당 Phase 에서 다룬다.

- **칸(slot) 모델** — 지금 ``MZONE`` / ``SZONE`` 은 빈 칸을 남기지 않는 순서
  컨테이너다. "3번 칸이 비었다", "존이 꽉 찼다" 는 Phase 4 의 칸 제약과 함께
  들어온다.
- **이동에 따른 이벤트** — ``move_card`` 는 ``previous`` 만 남기고 이벤트를
  만들지 않는다. ``GameEvent`` / ``EventJournal`` 은 Phase 2 다.
- **``chain`` / ``pending`` / ``journal``** — :class:`~engine.state.game_state.GameState`
  에 자리만 있다. 내용이 생기면 ``clone()`` 과 ``canonical_state()`` 양쪽에
  함께 넣어야 한다.
- **횟수 제한 판정** — :class:`~engine.state.player.UseRegistry` 는 횟수를
  세기만 한다. "몇 번까지 허용인가" 는 Phase 4 다.
- **턴 종료 시 초기화 호출** — ``PlayerState.reset_for_turn()`` 과
  ``TurnState.begin_next_turn()`` 은 있지만, 언제 부를지는 정하지 않았다.
  턴 진행 규칙은 Phase 4 의 타이밍 계층이다.
- **``AppliedEffect``** — 일시 효과를 보관만 하고 해석하지 않는다. Phase 8.
"""
