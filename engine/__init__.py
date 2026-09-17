"""
Duel Engine.

``docs/duel-engine-design.md`` 의 설계를 구현한다. 현재까지:

- **Phase 1** — 규칙 판정 없이 듀얼 **상태**만 정확하게 표현하는 데이터 계층
  (``engine/state/``, ``ids.py``, ``vocabulary.py``).
- **Phase 2-A** — AI 가 *무엇을 할지* 표현하는 계층. 아직 **판을 바꾸지
  못한다** (``action.py``, ``action_target.py``, ``action_validation.py``,
  ``game_state_view.py``). ``docs/phase2a-player-action.md`` 참고.
- **Phase 2-B-1** — 조건을 표현하고 평가하는 계층 (``condition/``).
  ``TRUE`` / ``FALSE`` / ``UNKNOWN`` 삼치 논리이고, 조건은 질문이지 명령이
  아니다. ``docs/phase2b1-condition.md`` 참고.

``PlayerActionKind`` 는 ``analysis.effect_model.ActionKind`` 와 **다른
어휘**다. 전자는 고르는 주체가 고르는 행위, 후자는 효과가 하는 일이다
(ADR-001).

이 패키지는 ``core/`` 와 ``analysis/`` 를 **읽기만 한다.** 카드 정의는
:class:`~core.card_repository.CardRepository` 가 소유하고, 엔진은
:class:`~engine.state.card_instance.CardInstance` 로 듀얼 중의 상태만
따로 갖는다.


Phase 1 에서 의도적으로 만들지 않은 것 (TODO)
--------------------------------------------

구현 중에 "이게 필요해 보인다" 고 느낀 지점들. 각각 해당 Phase 에서 다룬다.

- **칸 제약의 규칙 판정** — 칸 모델 자체는 있다 (``MZONE`` 5칸 · ``EMZONE``
  1칸 · ``SZONE`` 5칸 · ``FZONE`` 1칸 · ``PZONE`` 2칸, 가운데가 비어도 밀리지
  않는다). 다만 ``ZoneFull`` 은 **표현할 수 없는 상태**를 막을 뿐이고,
  "여기에 소환해도 되는가" · "링크 마커가 가리키는 칸인가" 는 Phase 4 다.
- **이동에 따른 이벤트** — ``move_card`` 는 ``previous`` 만 남기고 이벤트를
  만들지 않는다. ``GameEvent`` / ``EventJournal`` 은 Phase 2 다.
- **``chain`` / ``pending`` / ``journal``** — :class:`~engine.state.game_state.GameState`
  에 자리만 있다. 내용이 생기면 ``clone()`` 과 ``canonical_state()`` 양쪽에
  함께 넣어야 한다.
- **횟수 제한 판정** — :class:`~engine.state.use_registry.UseRegistry` 는 횟수를
  세기만 한다. "몇 번까지 허용인가" 는 Phase 4 다.
- **사용 횟수 · 턴 플래그의 초기화 시점** — ``UseRegistry.clear()`` 와
  ``TurnState.begin_next_turn()`` 은 있지만, 언제 부를지는 정하지 않았다.
  턴 진행 규칙은 Phase 4 의 타이밍 계층이다.
- **``AppliedEffect``** — 일시 효과를 보관만 하고 해석하지 않는다. Phase 8.
"""
