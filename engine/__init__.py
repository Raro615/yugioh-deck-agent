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
- **Phase 2-I** — 일반 소환 (``summon_rules.py`` · ``normal_summon.py``).
  **이 프로젝트에서 처음으로 ``VALID`` 가 나오는 행위다.** 절차 판정은
  ``assess_normal_summon`` 한 곳에 있고, 실행은
  ``NormalSummonHandler`` 가 ``ActionExecutor`` 에 등록되어 한다.
  제물이 필요한 몬스터와 효과 몬스터는 ``UNKNOWN`` 이다 — 룰북이
  "most Effect Monsters (unless they have a specific restriction)" 라고
  말하는 그 제약을 아직 읽지 못한다. 소환권은 카드 효과의 "1턴에 1번" 과
  **다른 표**(``RuleUsageRegistry``)에 적는다.
  ``docs/phase2i-normal-summon.md`` 참고.
- **Phase 2-J** — 사건 파이프라인 (``event_pipeline.py``).
  판이 바뀐 결과(``StateDelta``)를 **관찰 가능한 사건**으로 옮겨 기존
  수집기(2-F-3-A)에 넣는다. ``MonsterSummoned`` · ``PhaseChanged`` 가
  드디어 ``TimingPoint`` 를 갖는다. 실행기는 이 파일을 **모른다** —
  상태를 바꾸는 일과 사건을 관찰하는 일을 붙이지 않는다. 체인도 효과도
  여기서 일어나지 않는다. ``docs/phase2j-event-pipeline.md`` 참고.
- **Phase 2-K** — 효과 구현 목록 (``effect/library.py``).
  실행기 · 체인 · 사건 통로는 2-D-2 · 2-F-2 · 2-J 에 이미 있었지만
  **엔진이 들고 있는 효과 정의가 하나도 없었다.** 이 목록이 그 자리다 —
  손으로 쓰고, 근거가 된 Lua 파일과 그 줄을 함께 들고 다닌다.
  실행되는 것(욕망의 항아리)과 **실행할 수 없는 것**(블랙홀)을 둘 다
  싣는다 — 빼 버리면 "왜 못 하는가" 가 사라진다.
  ``docs/phase2k-effect-execution.md`` 참고.
- **Phase 2-L** — Operation 계층 (``effect/operation.py``).
  판을 바꾸는 일이 셋이다: ``DRAW`` · ``CHANGE_LIFE`` · ``MOVE``.
  ``MOVE`` 는 **게임 의미가 없는 저수준 이동**이다 — ``REASON_*`` 을 하나도
  주장하지 않고, 실제 카드의 효과가 될 수 없다 (``LibraryEntry`` 가
  거부한다). 파괴 · 묘지로 보내기 · 버리기 · 릴리스 · 제외는 각자
  자기 의미를 들고 다니는 ``CardOperation`` 이고, ``MOVE`` 는 그것들이
  앞으로 공유할 바닥일 뿐이다 (ADR-002).
  ``docs/phase2l-operation-layer.md`` 참고.
- **Phase 2-M** — 의미 계층 (``effect/semantics.py``).
  ``DESTROY`` · ``SEND_TO_GRAVE`` · ``DISCARD`` 가 전부 묘지로 가면서도
  **서로 다른 일로 기록된다** (ADR-002). 파괴는 **판정을 받아야만**
  실행된다 — ``DestructionRuling`` 이 내성과 대체 효과에 답하지 못하면
  ``UNCHECKED_RULES`` 로 멈추고 판은 그대로다. **``UNKNOWN`` 은 허가가
  아니다**; 보지 않았다고 적어 두는 것만으로는 내성을 가진 카드가
  파괴되는 것을 막지 못한다.
  ``docs/phase2m-semantic-effects.md`` 참고.
- **Phase 2-N** — 대상 선택 (``effect/targeting.py``).
  ``TargetSpec`` 이 말한 규칙에 **고른 카드가 맞는지** 판정한다 —
  ``LEGAL`` · ``ILLEGAL`` · ``UNKNOWN`` 셋이 끝까지 갈리고, 가려진 정보
  때문에 모르는 것은 ``UNKNOWN`` 으로 남는다. 후보 찾기는 Phase 2-C 의
  ``CandidateResolver`` 를 그대로 쓴다. 의미 계층을 **모른다** — 같은
  규칙이 파괴에도 보내기에도 쓰인다. ``docs/phase2n-target-selection.md``
  참고.
- **Phase 2-O** — 대상 지정 효과의 통합 (``effect/library.py`` 의
  싸이크론). 2-M 의 의미 · 2-N 의 대상 · 2-J 의 사건 통로를 **실제 카드
  하나로** 이어 붙인다: ``c5318639.lua`` 의 ``SelectTarget`` 이
  ``TargetSpec.targeting`` 이 되고 ``Duel.Destroy`` 가
  ``CardOperation.destroy`` 가 된다. 새 계층은 없다 — 새로 생긴 것은
  ``IsSpellTrap`` 조건 하나뿐이고, 그것도 ``s.filter`` 를 그대로 옮긴
  것이다. 무엇을 고를지는 **엔진이 정하지 않는다**; 부르는 쪽이 값으로
  준다.

  경로가 **둘**이고, 둘을 합치지 않는다. 실제 카드는 대상 판정을 통과한 뒤
  ``UNCHECKED_RULES`` 에서 멈춘다 — 파괴 내성 · 대체 효과에 답할 계층이
  없기 때문이고, 그 자리를 "이 카드는 파괴될 수 있다" 는 선언으로 메우면
  저장소가 공식 근거 없이 재정을 주장하게 된다. 판정을 명시적으로 받는
  것은 **아무 카드의 의미도 주장하지 않는 synthetic 정의**뿐이고, 그쪽만
  묘지 · Delta · 사건까지 간다. 이렇게 나눠야 "실제 카드 규칙을 모른다" 와
  "대상 효과 실행 기반이 고장났다" 가 구분된다.
  ``docs/phase2o-targeted-effect.md`` 참고.
- **Phase 2-P** — 실행 시나리오 검증 (``tests/engine/
  test_effect_scenarios.py``). **엔진 코드를 바꾸지 않는 단계다** — 지금까지
  쌓인 경로가 대상 효과 · 비대상 효과 · ``MOVE`` 에서 같은 약속을 지키는지
  확인한다. 비대상 효과(욕망의 항아리 · 은혜의 단비)는 **실제 카드가 끝까지
  간다** — 파괴가 아니라 받을 판정이 없기 때문이다. 아홉 가지 실패가 전부
  판을 건드리지 않고, 그중 **여덟 개**의 답으로 갈린다: "애초에 부적법한
  대상" 과 "고른 뒤 자리를 떠난 대상" 이 아직 같은 답이다
  (STRUCTURAL-53). ``docs/phase2p-effect-scenarios.md`` 참고.
- **Phase 2-Q** — 효과 발동 (``activation.py``).
  ``ACTIVATE_EFFECT`` 를 **체인 링크 하나**로 바꾼다. 이 모듈이 하는 일은
  넷뿐이다: 발동할 수 있는지 판정하고, 비용을 치르고(Phase 2-E 의
  ``CostPayer`` 그대로), ``ChainLink`` 를 만들고, 체인에 쌓는다.

  **``EffectExecutor`` 를 가져오지도 않는다.** 발동이 곧 해결이면 체인이
  존재할 이유가 없다 — 카드가 움직이는 것은 ``ChainResolver`` 가 링크를
  풀 때뿐이다. 순서도 규칙이다: 읽기만 하는 검사를 **전부** 끝내고 체인이
  링크를 받을 수 있는지까지 확인한 뒤에야 비용을 치른다. 치른 뒤에 거절당하면
  되돌릴 방법이 없기 때문이다 (ADR-008).

  허가는 **밖에서** 온다. ``ActionValidator`` 는 오늘 ``ACTIVATE_EFFECT``
  에 ``UNKNOWN`` 을 돌려주므로(발동 타이밍 계층이 없다), 명시적인 ``VALID``
  를 건네지 않으면 ``UNAUTHORIZED`` 다 — ``UNKNOWN`` 을 허가로 바꾸지
  않는다. ``docs/phase2q-effect-activation.md`` 참고.
- **Phase 2-R** — 체인 응답 루프 (``response.py``).
  ``Chain`` 과 ``PriorityState`` 를 **나란히 담기만** 하는
  :class:`~engine.response.ResponseState` 하나로 "지금 누가 체인에 무엇을
  더할 차례인가" 를 표현한다. 어느 쪽에도 새 칸을 만들지 않았다 —
  Phase 2-F-2 가 "둘을 잇는 것은 이후 단계의 몫" 이라고 남겨 둔 자리다.

  응답은 ``PASS`` 와 ``ACTIVATE_EFFECT`` 둘뿐이다. 패스는 **효과가 아니라**
  우선권만 옮기고, 발동은 Phase 2-Q 의 ``EffectActivator`` 를 그대로
  부른다. 거절은 차례를 빼앗지 않는다. 양쪽이 연속으로 패스하면
  ``ResponseStep.RESOLVE`` 이고, 그때만 기존 ``ChainResolver`` 로 넘어가
  **LIFO** 로 풀린다.

  **트리거와 합치지 않는다.** 하나의 사건 때문에 여럿이 동시에 후보가 되는
  것(2-F-3)과 우선권을 쥔 한 사람이 하나를 얹는 것은 다른 개념이고, 이
  모듈은 ``engine.trigger*`` 를 import 하지 않는다.
  ``docs/phase2r-chain-response.md`` 참고.

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
