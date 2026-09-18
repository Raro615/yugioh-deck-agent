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
- **Phase 2-B-2** — Action 을 판정하는 계층 (``action_validation.py``).
  관측만 읽고 확실한 위반을 잡아내되, 아직 **어떤 행위도 허가하지 않는다**.
  ``docs/phase2b2-action-validator.md`` 참고.
- **Phase 2-C** — 비용과 선택 (``cost/``). 후보를 세고 선택을 검사하되
  **아무것도 치르지 않고 아무것도 고르지 않는다**.
  ``docs/phase2c-cost-choice.md`` 참고.
- **Phase 2-D-1** — 효과 모델과 해결 계약 (``effect/``). 효과가 무엇을
  요구하고 무엇을 하는지 정의하되 **실행하지 않는다**.
  ``docs/phase2d1-effect-model.md`` 참고.
- **Phase 2-D-2** — 효과 실행 (``effect/executor.py``).
  :class:`~engine.effect.executor.EffectExecutor` 가 **효과가 판을 바꾸는
  유일한 문**이다. 등록된 구현이 있고, 출처가 허용하고, 조건이 참이고,
  대상이 다 풀렸을 때만 바꾼다. 파괴는 아직 실행하지 않는다 —
  파괴 내성 · 파괴 대체 · 파괴 트리거가 없기 때문이다.
  ``docs/phase2d2-effect-execution.md`` 참고.
- **Phase 2-D-3** — 상태 변화의 기록 (``effect/delta.py``,
  ``effect/journal.py``). 실행이 판을 바꾸면 그 변화를
  :class:`~engine.effect.delta.StateDelta` 로 남기고
  :class:`~engine.effect.journal.EventJournal` 에 사건으로 적는다.
  **기록은 판을 바꾸지 않는다** — 되돌리기도 재생도 아직 없다 (ADR-008).
  ``docs/phase2d3-delta-journal.md`` 참고.
- **Phase 2-E** — 비용 지불 (``payment.py``).
  :class:`~engine.payment.CostPayer` 가 **비용이 판을 바꾸는 유일한 문**이다.
  묶음 전체를 먼저 확인하고 (AND 관계이므로 중간까지만 내놓지 않는다),
  버리기 · 릴리스 · 라이프 지불만 치른다. 나머지는 지어내지 않고
  ``UNSUPPORTED_COST`` 다. ``docs/phase2e-cost-payment.md`` 참고.
- **Phase 2-F-1** — 우선권과 응답 기회 (``priority.py``).
  "지금 누가 다음 선택을 할 차례인가" 만 표현한다. 그 사람이 **무엇을** 할
  수 있는지는 답하지 않는다 — 체인 · 트리거 · 타이밍 · 스펠 스피드는 전부
  이후 단계다. ``docs/phase2f1-priority.md`` 참고.
- **Phase 2-F-2** — 체인 (``chain.py``). ``ChainLink`` 가 쌓이고 **역순으로**
  해결된다. 효과를 적용하는 것은 여전히 ``EffectExecutor`` 뿐이고, 체인은
  "무엇을 언제" 만 정한다. 트리거 · 타이밍 · 스펠 스피드는 아직 없다.
  ``docs/phase2f2-chain.md`` 참고.
- **Phase 2-F-3-A** — 타이밍과 트리거의 후보 수집 (``trigger.py``).
  ``StateDelta`` · ``JournalEvent`` → ``TimingEvent`` → ``TriggerCandidate``.
  **후보 발견과 체인에 넣기를 분리한다** — ``ELIGIBLE`` 은 "타이밍이 맞고
  조건이 참" 일 뿐이고 발동 합법성은 보지 않는다. 볼 수 없는 곳은
  ``unchecked`` 로 남긴다. ``docs/phase2f3a-trigger.md`` 참고.
- **Phase 2-F-3-B** — 트리거 발동 가능성 판정 (``trigger.py`` 의
  ``TriggerEligibilityJudge``). 사건 관계 · 발동 자리 · 조건 · 실행 권위 ·
  비용 가능성을 **관문별로** 따로 판정하고 합친다. 비용을 치르지 않고
  체인에 넣지도 않으며, **아직 보지 않은 규칙을 ``unchecked_rules`` 로
  남긴다**. ``docs/phase2f3b-trigger-eligibility.md`` 참고.
- **Phase 2-F-3-C** — 체인에 넣기 전의 정리와 순서 (``trigger_order.py``).
  ``ELIGIBLE`` 만 컨트롤러별로 묶고, ``UNKNOWN`` 은 제외가 아니라 **따로**
  보존한다. 순서는 재현 가능할 뿐 **규칙상의 순서가 아니며**
  (``is_rule_ordered`` 는 언제나 거짓), 정할 수 없는 것은
  ``unresolved_rules`` 로 남긴다. ``docs/phase2f3c-trigger-order.md`` 참고.
- **Phase 2-F-3-D** — 트리거와 체인을 잇는 통합 (``trigger_chain.py``).
  정리된 후보를 ``ChainLink`` 로 **만들 수 있을 때만** 만든다 — 대상 선택과
  비용 영수증이 없으면 빈 값으로 채우지 않고 삽입 불가로 남긴다. 체인에
  넣는 것과 **해결하는 것은 따로**이고, 여기서는 아무것도 실행하지 않는다.
  ``docs/phase2f3d-trigger-chain.md`` 참고.
- **Phase 2-F-4** — 타이밍 창과 우선권의 통합 (``timing.py``).
  ``TimingWindow`` 가 사건 · 턴 · 우선권 · 체인을 한 스냅숏으로 묶고,
  ``TimingCoordinator`` 가 앞 계층을 **부르기만** 한다. 체인을 해결하지도
  효과를 실행하지도 않고, **우선권을 돌리지 않고 확인만 한다** — 누구에게
  넘어가는가는 아직 규칙이 없다. ``docs/phase2f4-timing-priority.md`` 참고.
- **Phase 2-G** — Action 실행의 입구 (``action_execution.py``).
  ``ActionExecutor`` 는 **검증하지 않고** 검증 결과를 확인만 한다 —
  ``ValidationResult.permits_execution`` 이 참일 때만 손으로 등록된
  ``ActionHandler`` 에게 넘긴다. 규칙 계층이 아직 ``VALID`` 를 내주지
  않으므로 **오늘 실행되는 Action 은 하나도 없다**; ``UNKNOWN`` 을 허가로
  바꾸지 않는 것이 이 계층의 존재 이유다. 소환 · 전투 · 턴 진행은
  여기 들어오지 않고 각자의 Executor 로 간다.
  ``docs/phase2g-action-executor.md`` 참고.
- **Phase 2-H** — 게임 시간의 진행 (``turn_progression.py``).
  ``TurnProgressor`` 가 ``TURN_PHASE_ORDER`` 위에서 다음 자리를 계산하고,
  엔드 페이즈에서는 **다음 턴의 첫 페이즈**로 넘긴다 (턴 번호 · 턴
  플레이어가 함께 바뀐다). ``VALID`` 는 "진행 순서와 맞다" 는 뜻일 뿐이고,
  보지 않은 규칙은 ``UNRESOLVED_PROGRESSION_RULES`` 로 함께 남는다.
  **우선권을 건드리지 않고**, 트리거도 만들지 않는다 — 남기는 것은
  ``PhaseChanged`` 하나다. ``docs/phase2h-turn-progression.md`` 참고.

판정 어휘(``validation.py``)는 Action 검증과 비용 검증이 함께 쓴다.
비용 지불(``payment.py``)은 ``cost`` 와 ``effect`` **위에** 있다 — 지불은
변경이고, 변경을 적으려면 ``effect.delta`` 가 필요한데 ``effect`` 가 이미
``cost`` 를 읽기 때문이다.

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
  에 자리만 있고 **앞으로도 채우지 않는다.** ``EventJournal`` (Phase 2-D-3),
  ``PriorityState`` (2-F-1), ``Chain`` (2-F-2) 은 모두 판 **밖**에 산다 —
  전부 판의 *모양*이 아니라 흐름의 위치이고, ``state_hash()`` 에 섞으면
  "같은 판은 경로와 무관하게 같은 해시" 가 깨진다. ``pending`` 은 이벤트
  대기열이 생길 때 다시 본다.
- **횟수 제한 판정** — :class:`~engine.state.use_registry.UseRegistry` 는 횟수를
  세기만 한다. "몇 번까지 허용인가" 는 Phase 4 다.
- **사용 횟수 · 턴 플래그의 초기화 시점** — ``UseRegistry.clear()`` 와
  ``TurnState.begin_next_turn()`` 은 있지만, 언제 부를지는 정하지 않았다.
  Phase 2-H 가 턴을 넘기면서도 **아무것도 지우지 않는다** — 무엇이 언제
  지워지는가는 규칙이고, 규칙 없이 지우면 되돌릴 수 없다. 지워야 할 것의
  목록만 ``turn_progression.TURN_BOUNDARY_RESETS`` 에 남아 있다.
- **``AppliedEffect``** — 일시 효과를 보관만 하고 해석하지 않는다. Phase 8.
"""
