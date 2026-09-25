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
- **Phase 2-S** — 발동 타이밍 · 스펠 스피드 (``activation_timing.py``).
  응답 루프에 **관문 하나**가 더 생겼다: 우선권 → **스펠 스피드** → 발동.
  표는 지어내지 않았다 — ``data/rules/structured/`` 의 공식 룰북 구조화
  (``RULE-CHAIN-003`` ~ ``006``)에서 왔고, 엔진의 사본이 원본과 어긋나면
  테스트가 깨진다. ``engine`` 은 ``rules`` 를 import 하지 않는다.

  응수 가능 여부는 **숫자 비교가 아니라 표**다. ``>=`` 로 대신하면
  "스펠 스피드 1 이 1 에 응수할 수 있다" 가 되어 버린다. ``SpellSpeed`` 에
  ``UNKNOWN`` 멤버를 두지 않은 것도 같은 이유다 — 모르는 것이 숫자처럼
  행동하면 안 된다.

  **몬스터 효과의 속도는 모른다.** 기동이면 1, 유발즉시면 2 인데 그 분류를
  읽는 계층이 없다. 추측하지 않고 ``UNKNOWN`` 으로 두며, ``UNKNOWN`` 은
  허가가 아니므로 체인에 얹히지 않는다. 통과(``VALID``)도 "발동해도 된다"
  가 아니다 — 보지 않은 규칙이 결과에 함께 실려 나간다.
  ``docs/phase2s-activation-timing.md`` 참고.
- **Phase 2-T** — 특수 소환 (``summon.py`` · ``special_summon.py``).
  특수 소환이라는 **상태 변화가 지나갈 공통 길**을 낸다. 소환법을 구현한
  것이 아니다 — "이 카드를 특수 소환할 수 있는가" 는 카드마다 다르고, 그
  조건을 읽는 계층이 없으므로 ``ActionValidator`` 는 언제나 ``UNKNOWN`` 을
  돌려준다.

  일반 소환과 **같은 코드**를 쓴다. 자리 찾기 · 빈 칸 찾기 · 이동 · 착지
  확인은 :class:`~engine.summon.SummonProcedure` 하나이고, 다른 것만 값으로
  적는다 — 출발 자리 · ``SummonKind`` · **소환권**. 마지막 것은 공통 파일에
  아예 없다: ``special_summon.py`` 에 ``RuleUsageRegistry`` 라는 이름이
  나오지 않으므로, 특수 소환이 일반 소환권을 먹는 일이 **구조적으로**
  불가능하다.

  사건은 ``MonsterSummoned(summon=SPECIAL)`` 하나로 남기고 거기서 멈춘다 —
  트리거 수집도 체인도 이 계층의 일이 아니다. 어떤 특수 소환법인가는
  말하지 않는다: 융합 · 싱크로 · 엑시즈 · 링크는 각자의 절차가 생길 때
  이름을 갖는다 (STRUCTURAL-62).
  ``docs/phase2t-special-summon.md`` 참고.
- **Phase 2-U** — 효과에 의한 특수 소환 (``effect/operation.py`` 의
  ``SpecialSummonOperation``). 효과 해결이 Phase 2-T 의 소환 절차를 **그대로**
  부른다 — 플레이어가 선언한 소환과 같은 코드로 같은 자리에 놓이고, 다른
  것은 기록뿐이다 (``reason_names`` 에 ``SPSUMMON`` · ``EFFECT``).

  ``CardOperation`` 이 **아니다.** 저쪽은 목적지가 표로 정해지지만 소환은
  칸과 표시 형식이 필요하고 남기는 변화도 ``MonsterSummoned`` 다. 같은 표에
  넣으면 "몬스터 존으로 옮겼다" 와 "특수 소환되었다" 가 한 기록이 된다.
  ``PlayerActionKind.SPECIAL_SUMMON`` 과도 다른 어휘다 (ADR-001).

  **관문이 있다.** "이 카드를 특수 소환할 수 있는가" 는 카드마다 다르고
  (소생 제한 · 정규 소환 여부 · 턴 1회), 그 계층이 없으므로 기본
  ``UnknownSummonRuling`` 으로는 **어떤 특수 소환도 일어나지 않는다**
  (``UNCHECKED_RULES``). Phase 2-M 의 파괴 관문과 같은 구조다.

  죽은 자의 소생(83764718)을 목록에 실었다 — ``executable=False`` 로.
  모양은 맞지만 후보 조건이 ``IsCanBeSpecialSummoned`` 라 추측 없이는
  옮길 수 없다. ``docs/phase2u-effect-special-summon.md`` 참고.

- **Phase 2-V** — 일 실행의 통합 (``effect/executor.py`` 의
  ``OPERATION_HANDLERS``). 새 일을 더하지 않았다. 대신 **dispatch 를
  하나로** 만들었다.

  예전에는 계획이 ``isinstance`` 로, 적용이 ``kind`` 로 갈라져 있었고
  ``SUPPORTED`` 는 손으로 적은 세 번째 목록이었다. "이 실행기가 무엇을 할
  줄 아는가" 를 말하는 자리가 셋이었으므로, 새 일을 더할 때 한 곳만 고쳐도
  조용히 지나갔다 — 그리고 그 실수는 **판을 이미 건드린 뒤**에 드러났다.

  이제 ``OperationHandler(plan, apply, note)`` 한 쌍을 표에 넣는 것이 그
  선언의 **전부**이고, ``SUPPORTED`` 도 그 표에서 센다. ``_plan_operation``
  과 ``_apply`` 는 표를 찾아 넘기는 세 줄이다.

  종류별 코드는 거대한 ``if/elif`` 가 아니라 이름 있는 계획기/수행기로
  흩어져 있다. 카드 이동 여덟 가지(``move`` + 의미 있는 이동 일곱)는
  **한 쌍을 나눠 쓴다** — 의미는 ``kind`` 가 들고 다니고(``DESTINATION`` ·
  ``REASON_NAMES``) 코드가 갈라지지 않는다. ADR-002("파괴 ≠ 묘지로
  보내기")는 분기가 아니라 **값의 차이**로 유지된다.

  표를 ``kind`` 로 키잡아도 되는 이유는 **조작이 스스로 자기 종류를
  제한하기** 때문이다 — ``CardOperation(OperationKind.DRAW, ...)`` 는 생성
  시점에 ``ValueError`` 다. 종류와 부류가 1:1 이라는 것을 테스트가
  ``OperationKind`` 전체에 대해 확인한다.

  **행동은 달라지지 않았다.** 기존 테스트 2222개가 하나도 수정되지 않은
  채로 통과한다. ``docs/phase2v-operation-integration.md`` 참고.

- **Phase 2-W** — 실제 카드 실행 범위 (``effect/library.py``).
  **엔진 코드를 바꾸지 않았다.** 지금까지 쌓인 경로가 실제 카드에서도
  같은 경계를 지키는지만 본다.

  공식 스크립트 12,702개를 실제로 읽어서 걸렀다. 판을 바꾸는 호출이 전부
  옮길 수 있는 것인 카드가 1,377장 남았고, 거기서 **후보 조건이 판정
  가능한 것**만 다시 골랐다. 가르는 선은 언제나 같은 술어다 —
  ``Card.IsAbleToHand`` · ``IsAbleToRemove`` · ``IsAbleToDeck`` ·
  ``IsCanBeSpecialSummoned``. 전부 **규칙 관문**이고 이 엔진에 그 계층이
  없으므로, 없는 채로 실행하면 추측이 된다.

  그래서 실제 카드 다섯 장이 더해지고 (치료의 신 다이안 켓 84257639 ·
  욕망의 선물 5915629 · 갑부 고블린 70368879 · 육신보살 15103313 ·
  벌금 92595643) 실행 가능한 실제 카드가 여덟 장이 되었다. ``DRAW`` ·
  ``CHANGE_LIFE`` 에 더해 ``SEND_TO_GRAVE`` 와 ``DISCARD`` 가 처음으로
  실제 카드로 실행된다.

  **두 장은 일부러 실행하지 않는 채로 실었다** — 강제 탈출 장치
  (94192409, ``IsAbleToHand``)와 로스트 (24623598, ``IsAbleToRemove``).
  ``BANISH`` 와 ``RETURN_TO_HAND`` 가 실제 카드로 검증되지 않은 까닭을
  코드 안에 남겨 두기 위해서다. 목록에서 빼면 "왜 못 하는가" 가 사라진다
  (블랙홀 · 죽은 자의 소생과 같은 자리).

  조사가 STRUCTURAL-48 의 **크기**를 재 주었다: RETURN_TO_HAND 후보
  81장 중 80장, BANISH 14장 전부, SPECIAL_SUMMON 67장 전부가 같은 관문에
  막혀 있다 (STRUCTURAL-68).

  실제 카드 테스트는 ``@pytest.mark.real_card`` 로 synthetic 과 갈라져
  있다 — 앞은 카드의 *의미*를 주장하고 뒤는 경로의 *모양*을 시험하므로,
  하나가 다른 하나를 대체하지 않는다.
  ``docs/phase2w-real-card-execution.md`` 참고.

- **Phase 2-X** — 묘지로 보내기 · 버리기의 **규칙 관문**
  (``effect/semantics.py`` 의 ``MovementRuling``). Phase 2-W 가 지목한
  관문 계층의 부재 중 이 둘을 메운다.

  먼저 ``c*.lua`` 12,702개를 다시 읽었다. 지시서가 예로 든 이름 중
  ``IsAbleToDiscard`` · ``IsCanBeGrave`` · ``IsCanBeDiscarded`` 는
  **코퍼스에 없다** (0장). 실제로 쓰이는 것은 ``Card.IsAbleToGrave``
  (544장)와 ``Card.IsDiscardable`` (537장)이고, **둘은 다른 질문**이다 —
  한쪽만 쓰는 카드가 각각 518장 · 511장이고, ``c26400609.lua`` 는 한
  줄에서 둘을 함께 묻는다.

  그래서 ``MovementRuling`` 의 메서드가 **둘**이고
  (``may_be_sent_to_grave`` · ``may_be_discarded``),
  ``DeclaredMovementRuling`` 의 집합이 **넷**이다 — "묘지로는 보낼 수
  있지만 버릴 수 있는지는 모른다" 를 적을 수 있어야 한다.
  ``RuleQuestion`` 이 네 질문(A 묘지 · B 버리기 · C 대상 지정 · D 수행
  가능성)을 갈라 놓고, 아직 아무도 묻지 않는 C 는 ``UNASKED_QUESTIONS``
  에 **적어 둔다** — 빈 칸은 "없다" 로 읽히기 때문이다.

  **관문을 종류로 걸지 않았다.** 파괴와 특수 소환은 언제나 판정을 받지만
  (``RULE_GATED``), 묘지로 보내기는 카드마다 다르다 — 육신보살
  (15103313)의 후보 조건은 ``nil`` 이고 어리석은 매장(81439173)은
  ``IsAbleToGrave`` 다. 같은 ``Duel.SendtoGrave`` 인데 한쪽은 묻고 한쪽은
  묻지 않는다. 종류로 걸었다면 이미 실행되던 두 장이 멈췄을 것이다 —
  스크립트가 묻지 않는 것을 엔진이 묻는 것도 추측이다. 선언은
  ``CardOperation.gated`` 한 칸이고 기본값은 거짓이다.

  **실제 카드는 여전히 실행되지 않는다. 이유가 관문이 아니다.**
  ``IsAbleToGrave`` 를 선언하면서 이 엔진이 닿는 카드 15장이 **전부**
  덱이나 엑스트라 덱에서 보내는데, 덱은 관측 모델에서 ``HIDDEN`` 이다.
  "자신의 덱을 본다" 는 동작이 없다 (STRUCTURAL-69). 어리석은 매장은
  그래서 ``UNCHECKED_TARGET`` / ``HIDDEN_CARD`` 로 멈추고, **무엇이 막고
  있는지 정확히 지목한다** — Phase 2-W 에서는 표현조차 못 하던 카드다.
  ``IsDiscardable`` 쪽은 닿는 카드가 **0장**이라 실제 카드를 붙이지
  못했다. 없는 것을 있는 척 만들지 않았다.

  기존 엔진 테스트는 **한 건도 고치지 않았다.**
  ``docs/phase2x-rule-gate-grave-discard.md`` 참고.

- **Phase 2-Y** — 관측 경계와 관문의 분리 (``game_state_view.py`` 의
  ``looked_at``). STRUCTURAL-69 를 해결한다.

  **세 가지를 합치지 않는다.** 엔진이 아는 것(``GameState``) · 그 사람이
  보는 것(``GameStateView``) · 규칙 판정에 필요한 것(효과의 후보 규칙).
  엔진은 자기 덱의 카드를 언제나 알지만, 기본 관측은 모른다 — **그것이
  맞다.**

  문제는 한 칸이었다. ``_zone_view`` 가 자리 이름만 보고 공개 범위를
  정했고, "이 효과는 자기 덱을 들여다본다" 를 말할 자리가 없었다.
  기본값이 틀린 것이 아니다 — 룰북이 예외를 명시한다: "If a card effect
  requires you to reveal cards from your Deck, **or look through it**,
  shuffle it and put it back in this space afterwards."

  그래서 고친 것은 **기본 공개 범위가 아니라 표현력**이다.
  ``from_state(..., looked_at=)`` 이고, 기본값은 비어 있으며, 비면 예전과
  한 글자도 다르지 않다. 자리 이름은 효과가 말한다 —
  ``CandidateSource.zones``/``owner``/``chooser`` 를 읽을 뿐 추론하지
  않는다. 남의 자리는 **어떤 값을 넘겨도** 열리지 않는다:
  ``container.owner == viewer`` 가 같은 줄에 있고, 그 방어는 한 곳에만
  있다.

  결과는 **두 UNKNOWN 이 갈린 것**이다. 어리석은 매장(81439173)이 이제
  발동을 통과해 **관문까지 가고**, 거기서 ``UNCHECKED_RULES`` 로 멈춘다 —
  ``Card.IsAbleToGrave`` 의 내용은 여전히 모르고 추측하지 않는다. 그리고
  덱이 보이므로 "고른 것이 몬스터가 아니다" 를 **규칙으로 거절할 수**
  있게 되었다 (예전에는 전부 ``HIDDEN_CARD`` 로 뭉개졌다).

  **실행되는 실제 카드 수는 8장 그대로다.** 늘리려면 관문의 내용을
  추측해야 하고, 그것이 이 프로젝트가 하지 않기로 한 일이다. 바뀐 것은
  **막히는 이유**이고, 그것이 다음에 무엇을 해야 하는지를 가리킨다.
  ``docs/phase2y-observation-boundary.md`` 참고.

- **Phase 2-Z** — 재현 가능한 무작위 (``randomness.py``).

  두 원칙이 전부다. **랜덤이어도 재현 가능해야 하고**, **게임 규칙의
  랜덤과 AI 의 랜덤은 다른 계층이다.**

  ``GameState`` 는 이미 주입된 seed 와 ``random.Random`` 을 들고 있었고
  (STRUCTURAL-53), 복제도 상태째 하고 있었다. 없던 것은 넷이다 — 꺼낸
  횟수(재현 좌표) · 결과를 적을 값 · 규칙이 쓸 API · 두 RNG 의 경계.

  :class:`~engine.randomness.RandomSource` 가 그 자리다. **카드를 보지
  않는다** — 원시 연산이 돌려주는 것은 자리 번호와 순열뿐이고, 정체를
  붙이는 일은 부르는 쪽이 한다. 그래서 난수원을 통해 숨은 정보가 샐 수
  없다. 정체가 붙은 :class:`~engine.randomness.RandomOutcome` 은
  **엔진 내부 기록**이고, 밖으로 나가는 문은 ``public_summary()`` 로
  따로 있다 ("4장 중 1장" 만 말한다).

  ``RandomPurpose`` 에 ``AI_*`` 가 **없다.** 한 열거형에 섞으면 같은
  난수원을 쓰게 되고, AI 가 한 번 더 생각했다는 이유로 듀얼의 결과가
  달라진다.

  ``OperationKind.SHUFFLE`` 이 기존 표에 **한 줄** 늘었다. 난수는
  **계획 단계에서** 꺼낸다 — 적용 중에 꺼내면 "계획을 전부 확인한 뒤에
  적용한다" 가 깨지고, 뒤가 막혔을 때 난수원만 소비된 채로 남는다.
  ``ZoneShuffled`` 는 **결과 순서를 적지 않는다**: 섞은 뒤의 덱 순서는
  아무도 모르는 것이 규칙이다.

  **난수원은 ``state_hash()`` 에 들어가지 않는다.** ``chain`` ·
  ``journal`` · 우선권을 뺀 것과 같은 이유다 — 난수원의 위치는 판의
  모양이 아니라 흐름의 위치이고, 넣으면 판이 똑같은데 몇 번 뽑았느냐로
  해시가 달라진다. 대신 ``RandomSource.canonical_state()`` 가 따로 있고,
  객체 주소가 아니라 ``getstate()`` 의 내용에서 나온다.

  동전(실제 카드 30장) · 주사위(57장)는 **일부러 만들지 않았다.**
  ``docs/phase2z-deterministic-randomness.md`` 참고.

- **Phase 2-AA** — 동적 관측 권한 (``observation.py`` ·
  ``observation_grant.py``). 효과가 **정보를 볼 권한**을 준다.

  Phase 2-Y 의 ``looked_at`` 은 "이 판정을 위해 **자기** 자리를 잠깐
  들여다본다" 였다. 이번 것은 다르다 — "이 효과가 살아 있는 동안 **남의**
  자리가 보인다". 둘은 대체하지 않고 **함께 있는다**: 최종 공개 범위는
  *기본 공개 범위 + 권한 + 일시적 열람* 이다.

  근거는 공식 데이터다. ``EFFECT_PUBLIC`` (``constant.lua:492``)을 쓰는
  실제 카드가 20장이고, 그중 마인드 온 에어(66690411)의 모양이 선언에
  그대로 온다 — ``SetRange(LOCATION_MZONE)`` → ``active_zones``,
  ``SetTargetRange(0, LOCATION_HAND)`` → ``subject=OPPONENT``.

  **권한을 저장하지 않는다.** ``derive_policy`` 가 언제나 지금 판에서 다시
  계산하고, 세 관문(카드가 판에 있는가 · 그 자리에 있는가 · 조건이
  참인가)을 전부 통과해야 살아 있다. 그래서 **지우는 코드가 없다** —
  카드가 사라지면 애초에 계산되지 않는다. 껐다 켜는 상태가 없으면 어긋날
  수도 없다. 조건이 ``UNKNOWN`` 이면 권한은 **생기지 않는다.**

  ``REVEAL_HAND`` 와 ``INSPECT_FACE_DOWN`` 을 **합치지 않는다.** 상대의
  뒷면 카드를 확인했다고 그 카드가 모두에게 공개되지는 않는다 —
  ``CardInstance`` 를 바꾸지 않고 **그 관측에서만** 드러내므로, 권한 없는
  viewer 에게는 여전히 가려져 있다.

  **파일이 둘인 이유는 계층이 둘이기 때문이다.** 관측이 권한의 *값*을
  읽어야 하는데, 권한이 살아 있는지 판정하려면 조건 평가기가 필요하고
  조건 평가기는 거꾸로 관측을 읽는다. 값을 아래(``observation.py``),
  계산을 위(``observation_grant.py``)에 둬서 그 고리를 푼다.

  **카드 이름을 보지 않는다.** 관측 계층에 카드 번호도 이름도 없고, AST
  로 그것을 확인한다. 요청받은 마인드 스캔(34298391)은 이 저장소에
  **스크립트가 없어서** 실행 권위를 가질 수 없고, 그 조건("'툰' 카드가
  자신 필드나 묘지에 존재")도 아키타입 조건이 없어 ``UNKNOWN`` 이다 —
  그래서 권한이 켜지지 않는다. 추측해서 켜지 않는 것이 결과다.
  ``docs/phase2aa-observation-permission.md`` 참고.

- **Phase 2-AB** — 무작위 선택 (``effect/target.py`` ·
  ``effect/executor.py``). Phase 2-Z 의 재현 가능한 난수를 **실제 효과**에
  잇는다 (STRUCTURAL-73 해결).

  ``TargetRequirement`` 에 ``RANDOM`` 이 붙었다. 앞의 셋(``NONE`` ·
  ``TARGETING`` · ``CHOOSING``)은 전부 "누가 고르는가" 가 있었고, 고르는
  사람은 후보를 **봐야** 한다. 무작위에는 고르는 사람이 없다 — 그래서
  ``RandomSelectionSpec`` 에는 ``chooser`` 칸이 **없고**, 넣지 않는 것이
  이 단계의 요점이다. 두면 "무작위인데 누가 고른다" 가 되어 구분이
  이름만 남는다.

      "상대 패에서 1장을 고른다"      → CHOOSING (고르는 사람이 본다)
      "상대 패에서 무작위로 1장"      → RANDOM   (아무도 보지 않는다)

  **후보는 자리 주인의 눈으로 센다.** 컨트롤러의 관측으로 상대 패를
  세면 0장이 나오고, 그러면 뒤쪽 문장을 영원히 실행할 수 없다. 세는
  주체가 플레이어가 아니라 **엔진**이기 때문에 정당하고, 그 관측은
  ``_authoritative_candidates`` 밖으로 나가지 않는다 (반환하지도,
  ``self`` 에 붙이지도 않는다 — AST 로 확인한다).

  **``RANDOM_SELECT`` 조작을 만들지 않았다.** 고르는 것은 상태 변경이
  아니고, ``OperationKind`` 는 예외 없이 "판이 어떻게 바뀌는가" 였다
  (ADR-002 가 그 위에 선다). 무작위는 *누가 대상이 되는가*의 문제이므로
  대상 계층에 탄다. 고른 뒤 옮기는 것은 기존 ``CardOperation`` 이다.

  난수는 **계획 단계**에서 꺼낸다(셔플과 같은 자리). 뒤의 조작이 계획에서
  막히면 적용은 한 줄도 시작되지 않지만 ``draws`` 는 이미 늘어 있다 —
  감추지 않는다. 같은 seed 면 같은 자리에서 같은 답이 나오므로 재현은
  깨지지 않는다. 후보를 다 세지 못했으면 **아예 꺼내지 않는다**: 몇 개
  중에서 고르는지 모르는 채로 돌리면 확률이 틀린다.

  실제 카드는 무정의 말살(73148972)이다 — ``SelectTarget`` 과
  ``RandomSelect`` 가 **한 카드 안에 나란히** 있어서 이 구분을 검증하기에
  이보다 나은 카드가 없다. ``RandomSelect`` 를 쓰는 실제 카드는 142장이고,
  그중 호출 자리에 존이 그대로 적힌 것은 24건뿐이라 나머지는 **추측해서
  옮기지 않았다.** ``docs/phase2ab-random-selection.md`` 참고.

- **Phase 2-AC** — 선택 수와 후보의 분리 (``effect/target.py`` ·
  ``effect/executor.py``). **후보와 수는 다른 질문이다.**

      무엇을 고를 수 있는가  →  CandidateSource · CandidateResolver
      몇 개를 고르는가       →  SelectionCount

  한쪽이 다른 쪽을 읽기 시작하면 "후보를 세다가 수가 정해지는" 코드가
  생기고, 그러면 확률이 어디서 정해졌는지 추적할 수 없다. 그래서 후보를
  세는 자리에 장수를 **넘기지 않고**, ``RandomSelectionSpec`` 에서
  ``minimum``/``maximum`` 을 **지웠다** — 장수를 두 이름으로 부르지
  않는다. AST 로 양쪽을 확인한다.

  ``SelectionCount`` 는 셋을 가른다. ``FIXED`` 는 적힌 숫자,
  ``DERIVED`` 는 자리 장수의 덧셈과 뺄셈, ``UNKNOWN`` 은 **계산할 수
  없다**. 마지막을 숫자로 접지 않는다 — 1 로 접으면 틀린 규칙이 되고
  0 으로 접으면 효과가 조용히 사라진다.

  근거는 센 값이다. ``RandomSelect`` 호출 **142건(141장)** 중 12건이
  고정 수가 아니고, 그 12건의 수는 자리 장수 산술(4) · 플레이어 선언(4) ·
  앞선 조작의 결과(3) · 체인 파라미터(1)에서 온다. 이 엔진이 판에서
  계산할 수 있는 것은 **첫 줄 하나뿐**이므로 나머지 셋은 ``UNKNOWN``
  이다. ``DERIVED`` 를 표현식 언어로 만들지 않은 것도 같은 이유다 —
  실제 카드 넷이 요구하는 모양이 딱 그만큼이다.

  **모르는 후보를 조용히 빼지 않는다.** 넷 중 하나가 후보인지 모르는
  채로 셋에서 고르면 1/4 이 1/3 이 된다 — 다른 규칙이다. 전부 모르는
  것과 일부만 모르는 것은 **다른 문장**으로 답한다. 그리고 ``UNKNOWN``
  (규칙을 판정할 수 없다)과 ``HIDDEN`` (그 자리를 못 봤다)은 끝까지
  다른 사실이다.

  "모자라면 있는 대로" 는 **규칙이 아니라 카드의 선언**이다
  (``Shortfall.TAKE_ALL``). 공식 텍스트 두 장이 그 처리를 자기 텍스트에
  적어 두었기 때문이다 ("or their entire hand, if less than 2").
  실제 카드의 "최대 N장" 은 이것과 **다르다** — 플레이어가 수를 선언한
  뒤 그만큼 무작위로 고르는 것이므로, 그 계층이 없는 지금은
  ``UNKNOWN`` 이다.

  실제 카드는 의적의 입문서(69091732)를 더했다. 새로 보여 주는 것은
  **발동 조건이 상대 패의 장수**라는 점이다 — 장수는 규칙이 아는
  사실이고 정체는 아니다. 동적 수를 쓰는 실제 카드는 **하나도 등재하지
  못했다**: 12장 전부가 다른 계층을 요구한다.
  ``docs/phase2ac-selection-count.md`` 참고.

- **Phase 2-AD** — 선언한 수와 앞선 결과 (``execution.py``). 효과를
  **실행하는 동안에만** 사는 값들이다 (STRUCTURAL-81 · 82 해결).

  네 가지를 뭉개지 않는다. 고른 카드(``Selection``) · 무작위로 고른
  카드(``RandomSelectionSpec``) · **사람이 선언한 수**(``DeclaredNumber``) ·
  **판이 정한 결과 수**(``OperationResult``). 앞의 둘은 "무엇을" 이고
  뒤의 둘은 "얼마나" 이며, 뒤의 둘끼리도 정한 주체가 다르다. 그래서
  ``CountKind`` 에 갈래가 둘 늘었다 (``DECLARED`` · ``FROM_RESULT``) —
  하나로 합쳐 "참조" 라고 부르면 그 구분이 이름에서 사라진다.

  **선언할 수 있는 수는 목록이다.** 공식 스크립트의
  ``Duel.AnnounceNumber(tp, ...)`` 가 고를 수 있는 수를 하나하나
  나열하므로, ``NumberDomain`` 도 목록이고 ``between(1,3)`` 은 줄임말이다.
  ``PENDING`` 을 대신 정해 주지도, ``INVALID`` 를 가까운 수로 고쳐 주지도
  않는다 — 그 순간 규칙을 만든 것은 플레이어가 아니라 실행기다.

  선언하는 사람은 ``ChoiceSpec.chooser`` 와 **같은** ``PlayerRef`` 다.
  그래서 컨트롤러가 아닌 사람이 선언하는 것을 적을 수 있다 — 부작용?
  (30922149)에서 1~3 을 정하는 것은 뽑는 쪽, 즉 상대다.

  앞선 결과는 **번호로** 가리킨다. ``ResultRef(operation_index, field)``
  이고, 정의가 만들어질 때 그 번호가 **자기보다 앞인지** 검사한다.
  "마지막 결과" 같은 암묵적 지시를 두지 않는 이유는, 자동으로 집어 오면
  정의에 일을 하나 끼워 넣는 순간 조용히 다른 수가 되기 때문이다. 없는
  결과를 0 으로 때우지도 않는다.

  칸은 ``AFFECTED_COUNT`` 하나뿐이다. ``SUCCEEDED`` 를 **일부러 만들지
  않았다** — 계획이 전부 끝난 뒤에야 적용이 시작되므로 앞의 조작이
  실패하면 뒤는 아예 시작되지 않고, "앞이 성공했는가" 를 물을 순간이
  존재하지 않는다.

  **``EventJournal`` 을 뒤지지 않는다.** 저널은 역사이고 실행 문맥은 지금
  해결의 중간 결과다. 역사를 뒤져 수를 짐작하면 같은 효과가 두 번 돌았을
  때 어느 것을 읽었는지 알 수 없다. 그리고 이 값들은 **판이 아니다** —
  ``state_hash`` 는 한 줄도 바뀌지 않았다.

  실제 카드는 **0장 등재했다.** 가장 가까운 부작용?(30922149)조차 세 줄
  중 마지막(``Recover(tp, dr*2000)``)이 막힌다 — 라이프 증감의 양이 아직
  고정 수만 받기 때문이다. 적을 수 있다는 것과 실행할 수 있다는 것을
  섞지 않는다. ``docs/phase2ad-execution-context.md`` 참고.

- **Phase 2-AE** — 성패와 처리량, 그리고 판에서 만들어지는 값
  (``execution.py``). STRUCTURAL-84 · 85.

  **``affected_count == 0`` 은 실패가 아니다.** "최대 2장까지" 에서
  0장을 고른 것은 규칙대로 된 일이고, 대상 계층은 Phase 2-N 부터 그것을
  적법하다고 판정해 왔다. 그런데 실행기가 거절하고 있었다 — 두 계층이
  서로 다른 말을 했고, 실행기 쪽이 장수를 성패로 읽고 있었다. 이제
  판단 기준은 장수가 아니라 **규칙이 무엇을 요구했는가**다.

  ``OperationOutcome`` 에 ``FAILED`` 가 **없다.** 계획에서 막힌 조작은
  결과를 남기지 않기 때문이다 (효과 전체가 거절된다). 실패는 조작이
  아니라 효과 단위의 사실이고 ``ResolutionStatus`` 가 이미 답한다.

  Phase 2-AD 는 성패 칸을 일부러 만들지 않았다. "언제나 참" 이라는
  이유였고, 그 판단은 **절반만 맞았다** — ``FAILED`` 는 정말 생기지
  않지만 ``UNKNOWN`` 은 생긴다. 묘지로 보내면서 "묘지로 보내는 것을 막는
  효과" 를 보지 않았다면, 카드는 움직였어도 규칙대로였다고 주장할 수
  없다. 성패는 **지어내지 않고** Phase 2-M 의 미확인 규칙 표에서 읽는다.

  성패는 **수가 아니다.** ``value_of(SUCCEEDED)`` 는 거부하고,
  ``OperationRequirement`` 로만 가리킨다. 그 조건은 조작이 아니라
  **정의**가 들고 있다 — 조작들 사이의 순서 관계이지 조작이 하는 일이
  아니기 때문이다. 앞이 ``UNKNOWN`` 이면 **건너뛰지 않고 전체를
  거절한다**: 부분 적용이 없고, 모르는 것 위에 다음 일을 쌓지 않는다.

  ``DerivedNumberDomain`` 은 **판에서 만들어지는 선언 도메인**이다.
  모양은 하나다 — ``step`` 의 배수를 ``bound`` 까지. ``BoardQuantity``
  가 읽는 것은 자리 장수와 라이프 둘뿐이고, 실제 카드가 목록을 만들 때
  쓰는 것이 그 둘이다. **수식 언어가 아니다.** 도메인과 계산값은 다른
  개념이며 한 곳에서 만난다 — 목록의 **끝**이 계산값이다.

  값의 출처 다섯(상수 · 판 · 선언 · 앞선 결과 · 모름)은 **이미 다
  있었다** (``SelectionCount``). 그래서 새 Value 시스템을 만들지 않았고,
  대신 ``CountOutcome``/``ResolvedCount`` 를
  ``ValueOutcome``/``ResolvedValue`` 로 이름을 넓혀 이 계층으로 옮겼다 —
  장수도 매수도 도메인도 같은 어휘로 답하기 때문이다.

  ``table.unpack`` 46건 중 **2건은 애초에 상수**였다 (식스 센스의
  ``for i=1,6 do t[i]=i end``). 있다고 모두 계산 문제가 아니다.
  실제 카드는 **0장 등재했다** — 성공 여부를 쓰는 91곳은 "앞은 남기고
  뒤만 빼는" 부분 적용을 요구하고, 그것이 없다.
  ``docs/phase2ae-operation-result.md`` 참고.

- **Phase 2-AF** — 일부만 되는 일, 그리고 값이 되는지 보는 일
  (``execution.py`` · ``effect/operation.py``). STRUCTURAL-88 · 89.

  **대상별 결과를 저장하지 않는다.** 실제 카드 91곳을 "무엇을 묻는가" 로
  다시 세어 보니 90곳이 **"몇 개 됐는가" 만** 묻는다 — 어느 대상이
  됐는지는 묻지 않는다. 그래서 필요한 것은 수 두 개였다:
  ``attempted_count`` 와 ``affected_count``. ``failed_count`` 는 그 둘의
  차이이므로 저장하지 않고, ``PARTIAL`` 이라는 상태도 만들지 않았다 —
  완결성은 파생되고, 성패(``OperationOutcome``)와는 다른 축이다.

  **일부만 하는 것은 카드가 선언한다.** 공식 영문 텍스트 **203장**이
  "as many … as possible" 을 적어 두었다 (몬스터 100 · 마법 52 ·
  함정 51). 적어 두지 않은 카드는 이 길을 타지 않는다 — "하나라도 못
  하면 전부 안 한다" 도 "되는 것만 한다" 도 엔진이 정할 일이 아니다.
  Phase 2-X 가 관문을, 2-AC 가 부족 처리를 카드가 선언하게 한 것과 같은
  발견이다. 규칙서에서 "나머지는 파괴된다" 를 **찾지 못했으므로**
  (0건) 그 일반 규칙을 심지 않았다.

  **모르는 것은 건너뛰지 않는다.** 건너뛰려면 카드의 선언과 규칙의
  **거절**이 동시에 있어야 한다. 관문이 ``UNKNOWN`` 이면 선언이 있어도
  전부 멈춘다 — 모르는 것을 건너뛰면 그 카드가 처리됐어야 하는지를
  엔진이 정하는 것이 된다. 막힌 카드의 ``InstanceId`` 도 결과에 남기지
  않는다 (가려진 카드의 정체가 샐 길이 된다).

  ``ValueDomain`` 은 **이미 정해진 값이 되는지** 본다. 갈래는 셋뿐이고
  (``AT_LEAST_ONE`` · ``BOUNDED`` · ``RULE_UNRESOLVED``) corpus 에 없는
  종류는 만들지 않았다. ``RULE_UNRESOLVED`` 가 핵심이다 — "적을 수는
  있지만 판정할 수 없다" 를 적을 수 있어야, 그런 카드가 조건 없이
  통과하지 않는다.

  세 도메인이 서로 다른 것이다: ``NumberDomain`` 은 **고르기 전**,
  ``ValueDomain`` 은 값이 나온 **뒤**, ``SelectionCount`` 는 **몇
  개인가**. 그리고 세 가지 모름도 다르다 — 값을 못 구한 것, 값은 있는데
  되는지 모르는 것, 넘어서 안 되는 것.

  ``table.unpack`` 을 다시 읽어 보니 넷은 **정렬**이었고 여섯은 **산술
  뿐**이었다. 있다고 모두 계산 문제가 아니다. 실제 카드는 **0장
  등재했다** — 파괴 판정기가 없어 어떤 파괴도 일어나지 않기 때문이고,
  부분 적용을 만들었다고 그 벽이 사라지지 않는다.
  ``docs/phase2af-partial-outcome.md`` 참고.

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
