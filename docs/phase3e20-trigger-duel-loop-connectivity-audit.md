# Phase 3-E-20 — Trigger Specification / Duel Loop Connectivity Audit

## 1. HEAD / Base

| | |
|---|---|
| Base (지시) | `8ab2312` — Phase 3-E-19 |
| 실제 HEAD | `8ab2312` (동일) |
| Working tree | 감사 시작 시 clean |
| `git diff -- engine/ agent/ core/ analysis/ sources/` | 0줄 |
| Branch | `claude/pensive-goodall-te1egy` |

## 2. BLOCKER

**NO.**

## 3. Engine Change

**NO.** production 코드를 한 줄도 바꾸지 않았다. 추가한 것은
`tests/test_trigger_connectivity_audit.py` (15개)와 이 문서뿐이다.

## 4. Repository Audit

### 구조와 그 생성 위치

| 구조 | 정의 위치 | 만드는 곳 | production 호출 | 판을 바꾸는가 | `PlayerAction` 을 만드는가 | `ChainLink` 를 만드는가 |
|---|---|---|---|---|---|---|
| `TimingPoint` | `engine/trigger.py:85` | enum | **쓰인다** (`ActivationTiming.point`) | 아니다 | 아니다 | 아니다 |
| `TimingEvent` | `engine/trigger.py:219` | `from_delta` · `from_journal_event` · `unimplemented` | **없음** | 아니다 | 아니다 | 아니다 |
| `timing_for` / `timing_events` | `engine/trigger.py:374` · `:402` | 함수 | **없음** | 아니다 | 아니다 | 아니다 |
| `TriggerSpec` | `engine/trigger.py:425` | 손으로 등록 (ADR-006) | **0개 등록** | 아니다 | 아니다 | 아니다 |
| `TriggerRegistry` | `engine/trigger.py:535` | `register()` | **없음** | 아니다 | 아니다 | 아니다 |
| `TriggerCandidate` | `engine/trigger.py:590` | `TriggerCollector._judge` | **없음** | 아니다 | 아니다 | 아니다 |
| `TriggerCollector` | `engine/trigger.py:775` | `engine/event_pipeline.py:376` · `engine/trigger_chain.py:323` · `engine/timing.py:342` | **없음** (셋 다 잠든 계층) | 아니다 (`GameStateView` 만 받는다) | 아니다 | 아니다 |
| `TriggerEligibilityJudge` | `engine/trigger.py` 아래 | `engine/trigger_chain.py:326` | **없음** | 아니다 | 아니다 | 아니다 |
| `TriggerOrdering` | `engine/trigger_order.py` | `engine/trigger_chain.py` · `engine/timing.py` | **없음** | 아니다 | 아니다 | 아니다 |
| `TriggerChainIntegrator` | `engine/trigger_chain.py` | `engine/timing.py:298` | **없음** | 아니다 (`extend` 가 새 `Chain` 을 돌려준다) | 아니다 | **만든다** (`:441`, 잠들어 있다) |
| `TimingWindow` · `TimingCoordinator` | `engine/timing.py:85` · `:269` | — | **없음** (import 하는 모듈이 0개) | 아니다 | 아니다 | 아니다 |
| `EventPipeline` · `EventReader` | `engine/event_pipeline.py:355` · `:279` | — | **없음** (import 하는 모듈이 0개) | 아니다 | 아니다 | 아니다 |
| `EffectActivator.activate` | `engine/activation.py:449` | `engine/duel.py:901` · `engine/response.py:572` | **있다** | 비용만 (`payment.deltas`) | 아니다 (받는다) | **만든다 — 유일한 production 소유자** |

### import 그래프 (AST 측정, `test_01`·`test_02` 가 고정)

```
engine.timing          ← (아무도 import 하지 않는다)
engine.event_pipeline  ← (아무도 import 하지 않는다)
engine.trigger_chain   ← engine.timing
engine.trigger_order   ← engine.timing · engine.trigger_chain
engine.trigger         ← engine.activation_timing · engine.event_pipeline
                         · engine.timing · engine.trigger_chain · engine.trigger_order
engine.duel            ← agent.arena · agent.heuristic · agent.policy
                         · agent.runner · agent.search · agent.simulation
```

`engine.trigger` 를 import 하는 다섯 모듈 중 **넷이 잠든 계층**이고, 살아 있는
하나(`engine.activation_timing`)가 가져가는 것은 `TimingPoint` **한 이름**뿐이다
(`test_02`). 그 값은 `ActivationTiming.point` 에 실려 `canonical_state` ·
`to_dict` 에만 나타나고 **어떤 판정에도 쓰이지 않는다** (3-E-19 에서 확인).

`engine/duel.py` 에는 `trigger` 라는 글자가 아예 없다 (`test_03`).

### §2 의 열 가지 질문에 대한 답

| 질문 | 답 |
|---|---|
| 1. 어디서 만들어지는가 | 위 표 |
| 2. 누가 부르는가 | 잠든 계층끼리 서로 부른다 |
| 3. production 에서 불리는가 | **아니다** (`TimingPoint` 타입 하나 제외) |
| 4. 테스트만 부르는가 | **그렇다** — 테스트 파일 12개가 쓴다 (`test_trigger.py` 43회 등) |
| 5. `GameState` 를 바꾸는가 | 아니다. `TriggerCollector` 는 `GameState` 를 넘기면 `TypeError` 를 던진다 |
| 6. `PlayerAction` 을 만드는가 | **아니다** |
| 7. `ChainLink` 를 만드는가 | `TriggerChainIntegrator` 만, 그리고 잠들어 있다 |
| 8. `PriorityState` 에 영향을 주는가 | 아니다. `engine/trigger.py` · `trigger_order.py` · `trigger_chain.py` 는 `engine.priority` 를 import 하지 않는다 (`test_13`) |
| 9. `ResponseLoop` 에 영향을 주는가 | 아니다 (같은 근거) |
| 10. `TurnProgressor` 에 영향을 주는가 | 아니다. `TurnProgressor` 도 `engine.trigger` 를 import 하지 않는다 |

## 5. Trigger Layer Map

| 계층 | 구조 | production 소비자 | 상태 |
|---|---|---|---|
| A 원본 메타데이터 | `c*.lua` 의 `SetCode(...)` | 파서 | **exists · 읽힌다** |
| B 파싱된 메타데이터 | `EffectSpec.code` · `LuaScriptInfo.trigger_events` | 카드 **검색**(`has_effect_code`) | exists · 듀얼은 안 읽는다 |
| C 분석 표현 | `EffectAnalysis.trigger_event` · `ActivationCondition.trigger_event` | 분석/문서 | exists · 듀얼은 안 읽는다 |
| D 후보 | `TriggerCandidate` | 없음 | exists · **called only by test** |
| E 적격성 | `TriggerEligibility` · `EligibilityGate` | 없음 | exists · called only by test |
| F 정렬 | `TriggerOrdering` (SEGOC 미구현) | 없음 | exists · called only by test |
| G 플레이어 결정 / 발동 | `PlayerAction` → `EffectActivator` | **`Duel.apply`** | **called in production** — 단 입력이 트리거가 아니다 |
| H `ChainLink` | `Chain.push(link)` | `EffectActivator.activate` | **called in production** |
| I 체인 해결 | `ChainResolver` · `ResponseLoop` | `Duel._resolve_chain` | **called in production** |

**D·E·F 와 G 사이에 연결선이 없다.** G 의 입력은 언제나 사람이 고른
`PlayerAction` 이다.

## 6. Production Call Graph

```
Duel.apply(PlayerAction)
  ├ legal_actions()  … 패(소환·세트) · 공격 · 발동 · 흐름  ← 트리거는 없다
  ├ ACTIVATE_EFFECT → _activation_gate
  │     ① ActionValidator.validate
  │     ② ActivationTimingChecker.check   (chain · priority · set_this_turn)
  │     ③ EffectActivator.can_activate
  │   → EffectActivator.activate  → ChainLink  → Chain.push   (engine/activation.py:449-460)
  │   → ResponseLoop (응답 창) → ChainResolver.resolve_all → EffectResult.deltas
  │                                                            ✗ 여기서 끊긴다 ②
  └ END_PHASE → TurnProgressor.advance(state)
        → ProgressionResult(status, plan, deltas=(PhaseChanged,))   (turn_progression.py:514-516)
        → Duel._apply_end_phase 는 status · verdict 만 읽는다       ✗ 여기서 끊긴다 ①
```

끊긴 자리는 정확히 둘이고, §4 의 보기 중 **A** 에 해당한다 — "사건(재료)은
만들어지는데 수집기를 부르는 자리가 없다". **G**(사건이 아예 없다)도,
**D·E**(후보가 legal_actions 를 우회하거나 직접 체인을 만든다)도 아니다.

끊김 ①: `PhaseChanged` 는 실제로 만들어지고 `from_phase`/`to_phase` 를 다 갖고
있다. 받는 쪽이 없어서 버려진다 (`test_06` 이 `_apply_end_phase` 본문에
`deltas` 라는 글자가 없음을 고정한다).

끊김 ②: `EffectResult.deltas` 는 채워지지만 ①`EventJournal` 이 붙어 있지 않고
(`build_executor()` 의 `journal` 기본값이 `None` — `engine/effect/library.py:1157`),
②`DuelStep` 에 변화를 내보내는 칸이 없다 (`action` · `accepted` · `code` ·
`reason` · `result` 뿐). 그래서 `TimingEvent.from_journal_event` 는
production 입력이 **구조적으로 없다** — `EFFECT_RESOLVED` · `COST_PAID` 시점이
생길 수 없다 (`test_07`).

## 7. Phase Transition Trace

실제 듀얼(`Duel.start` → `END_PHASE` 반복)로 측정했다. **여섯 전이 전부
일어난다.**

| 전이 | 일어나는가 | `PhaseChanged` 생성 | 호출자에게 전달 | `TimingEvent` | 후보 |
|---|---|---|---|---|---|
| `DRAW → STANDBY` | 예 | 예 | **아니다** | 없음 | 없음 |
| `STANDBY → MAIN1` | 예 | 예 | 아니다 | 없음 | 없음 |
| `MAIN1 → BATTLE` | 예 | 예 | 아니다 | 없음 | 없음 |
| `BATTLE → MAIN2` | 예 | 예 | 아니다 | 없음 | 없음 |
| `MAIN2 → END` | 예 | 예 | 아니다 | 없음 | 없음 |
| `END → DRAW` (턴 넘김) | 예 | 예 (`changes_turn=True`) | 아니다 | 없음 | 없음 |

따라서 엔진의 현재 상태는 다음 중 **"dormant event model"** 이다:

* 페이즈 전이 사건이 있는가 — **구조로는 있다** (`PhaseChanged` delta).
* 일반 사건이 있는가 — 있다 (`StateDelta` 전부).
* 사건이 아예 없는가 — 아니다.
* 테스트에서만 쓰이는 사건인가 — `TimingEvent` 로 변환되는 것은 그렇다.
* **잠든 사건 모델인가 — 그렇다.**

(참고: 선공 첫 턴에 `MAIN1 → BATTLE` 이 허가되는 것은 이미
`UNRESOLVED_PROGRESSION_RULES` 에 적혀 있는 별개의 미해결 규칙이고, 트리거
문제가 아니다. 이 Phase 는 그것을 건드리지 않는다.)

## 8. EVENT_PHASE Relationship

| §6 의 질문 | 답 | 근거 |
|---|---|---|
| 1. `EVENT_PHASE` 가 `TriggerSpec` 으로 흘러가는가 | **아니다** | `EffectDefinition` 에 유발 칸이 없고 (`test_09`), `TriggerSpec` 은 손으로 쓰는 별도 구조다 |
| 2. `TriggerSpec` 이 `TriggerCandidate` 로 흘러가는가 | 구조로는 그렇다 (`TriggerCollector`) | 그러나 등록된 선언이 0개다 |
| 3. `TriggerCandidate` 가 `Duel` 로 흘러가는가 | **아니다** | `Duel` 은 그 이름을 모른다 |
| 4. `PHASE_END` / `PHASE_START` 의 production 소비자 | **없다** | 3-E-19 에서 확정, 이번에 재확인 |
| 5. `PHASE_CHANGED` 가 출발/도착 페이즈를 구분할 수 있는가 | **그렇다** | `PhaseChanged.from_phase` · `to_phase` (`test_06`) |
| 6. 어디에서 | `engine/effect/delta.py:383-402` → `TimingEvent(delta=...)` 가 그대로 참조한다 |
| 7. 정보가 사라지는 곳 | **선언 쪽**이다 — `TriggerSpec` 에 페이즈를 적을 필드가 없다 (3-E-19 `test_11`) |

즉 비대칭이 그대로다: **사건은 페이즈를 알고, 선언은 묻지 못하며, 둘을 만나게
하는 호출이 없다.** 그러므로 `EVENT_PHASE` 를 보존해야 할 이유는 이번에도
production 에서 나오지 않는다.

## 9. TriggerCandidate / Chain Boundary

| 질문 | 답 |
|---|---|
| 후보가 `Chain` 생성 **전에** 존재할 수 있는가 | 예. `TriggerCandidate` 는 `Chain` 을 모른다 (`ChainLink` 를 상속하지도 않는다) |
| 발동이 `ChainLink` 를 만드는가 | **그렇다 — `EffectActivator.activate`** (`engine/activation.py:449`) |
| 후보 생성이 `ChainLink` 를 만드는가 | 아니다 (`TriggerCollector` 는 후보까지만) |
| `ResponseLoop` 가 만드는가 | 아니다 — `self._activator.activate` 를 부른다 (`engine/response.py:572`) |
| `apply()` 가 만드는가 | 아니다. `engine/duel.py` 에 `ChainLink(` 가 없다 (`test_11`) |

production 에서 `ChainLink` 를 만드는 자리는 **AST 로 세어 세 파일**이다 —
`engine/activation.py`(발동), `engine/chain.py`(체인 자신의 `push` 보조),
`engine/trigger_chain.py`(잠든 계층). 소유자는 **발동 하나**다.

잠든 계층이 깨어나면 **두 번째 소유자**가 생긴다는 점은 기록해 둔다:
`TriggerChainIntegrator._entry` 는 `PlayerAction` 없이 `ChainLink` 를 만들고,
비용 지불(`payments`)과 선택(`selections`)을 담지 않는다. 그 계층은 그 사실을
스스로 적어 두었다 — 실행 입력이 없으면 `NOT_INSERTABLE` 로 거절한다
(`_missing_execution_inputs`). 지금은 **불리지 않으므로 모순이 아니다.**

## 10. Priority / Response Boundary

* `engine/trigger.py` · `trigger_order.py` · `trigger_chain.py` 는
  `engine.priority` 와 `engine.response` 를 **import 하지 않는다** (`test_13`).
* 우선권을 보는 것은 잠든 `engine/timing.py` 의 `TimingCoordinator.check_priority`
  뿐이고, 그 메서드도 "**확인만 한다. 우선권을 돌리지 않는다**" 고 적혀 있다.
* 따라서 트리거 계층은 §7 의 **B** 다 — **가능한 발동을 서술하기만 하고 응답
  기회를 열지 않는다.**

## 11. STRUCTURAL-34

**STRUCTURAL-34 unaffected.** (해소하지도, 악화시키지도 않았다.)

| 대상 | 트리거 계층의 영향 |
|---|---|
| priority holder | 없음 |
| response seat | 없음 |
| `turn_player` | 없음 |
| `legal_actions()` | 없음 — 트리거에서 오는 후보가 0건 |
| `ResponseLoop` | 없음 |
| `ActivationTimingChecker` | `TimingPoint` 타입만 공유, 판정에 쓰지 않음 |
| `Chain` | 없음 (잠든 계층만 링크를 만들 수 있다) |

"응답 창을 여는 자리" 는 3-E-11/3-E-12 가 **발동 직후**에 대해 만들었고,
`AFTER_CHAIN_RULE`(체인 해결 뒤 누구에게 우선권이 가는가)은 그대로 남아 있다
(`engine/response.py:377`). 트리거 계층이 그 책임을 주장하는 코드는 없다.

## 12. STRUCTURAL-124

**유지.** 체인 링크 2 이상은 3-E-12 가 응답 발동으로 이미 가능하게 만들었고,
그것은 `PlayerAction` 경로다. **트리거 후보는 체인에 들어갈 수 있는 상태가
아니다** — 들어가려면 `TriggerChainIntegrator` 가 불려야 하고, 그 호출이 없다.
이번 Phase 는 124 를 재판정하지 않는다 (범위를 넓히지 않는다).

## 13. Legal Action Boundary

트리거 후보는 **아무것도 되지 않는다** — `PlayerAction` 도, `legal_actions()`
항목도, 내부 발동도, 직접 `ChainLink` 도 아니다.

* `PlayerActionKind` 에 트리거용 종류가 없다 (`test_12`).
* `legal_actions` 가 후보를 만드는 자리는 넷이다 — 패(`normal_summon` ·
  `set_monster` · `set_spell_trap`) · `_attack_actions` · `_activation_actions` ·
  `_flow_actions`(`pass` · `end_phase`). 그 본문에 `trigger` 가 없다.
* 따라서 **legal_actions 를 우회하는 트리거 처리가 지금 없다.** (우회가 생기는
  것은 잠든 계층을 그대로 연결했을 때이고, 그때는 §9 의 두 번째 소유자 문제를
  먼저 풀어야 한다.)

`AI 는 PlayerAction 을 고르고 엔진이 규칙을 실행한다` 는 규율은 깨지지 않았다.

## 14. Observation Boundary

**GameStateView = 변경 없음.** 트리거 후보는 숨은 정보를 새게 하지 않는다.

* `TriggerCollector` 는 `GameStateView` 만 받는다 — `GameState` 를 주면
  `TypeError` 다 (`test_14`).
* 후보를 만들 때 **보이는 사본만** 훑는다 (`_visible_copies`). 가려진 카드는
  `card_id` 가 `None` 이라 걸리지 않는다.
* 보지 못한 자리는 `TriggerCollection.unchecked` 에 **"P1 HAND 5장"** 처럼
  남는다 — "후보가 없다" 와 "볼 수 없어서 모른다" 를 섞지 않는다. 실측으로
  확인했다 (`test_14`).
* `TriggerCandidate` 는 `EffectRef` · `InstanceId` · `controller` 같은 식별자만
  담는다. `CardInstance` 도 `GameState` 도 담지 않는다.

## 15. Evaluation / Search Impact

`agent/` 전체에 `Trigger` · `trigger` · `TimingEvent` · `TimingPoint` 가
**하나도 없다** (`test_15`, `agent/` 의 모든 `.py`).

* Evaluation = **0**
* Search = **0**
* Ranking = **0**
* Simulation = **0**

## 16. Real Card Corpus

`EFFECT_LIBRARY` 항목 **16개** (실행 가능 13 · 미실행 3). 16개 전부의
`EffectSpec.code` 가 **`EVENT_FREE_CHAIN`** 이다 (`test_10`) — 통상 마법과
함정의 "발동한다" 이고 **유발이 아니다.**

| 분류 | 건수 | 뜻 |
|---|---|---|
| A 메타데이터는 있는데 엔진이 쓰지 않는다 | **전부** (유발 metadata 1,339 블록은 3-E-19 측정) | 지금 상태 |
| B 엔진이 같은 정보를 다른 데서 쓴다 | 0 | 없음 |
| C 부분 지원 | 0 | 없음 |
| D 모순된 지원 | **0** | 이 Phase 의 핵심 결론 |
| E 실행 가능한데 막힌 유발 사례 | **0** | 등록된 유발 효과가 없다 |

즉 "유발이 필요한 등록된 카드" 가 **하나도 없다.** 유발 실행 경로를 지금
만들면 **쓸 카드가 없는 경로**가 된다. 미래 범위(future scope)다.

## 17. Tests

신규: `tests/test_trigger_connectivity_audit.py` — **15개**.

| # | 검증 |
|---|---|
| 01 | `engine.timing` · `engine.event_pipeline` 를 import 하는 모듈이 0개 |
| 02 | `engine.trigger` 가 살아 있는 경로에 닿는 것은 `TimingPoint` 하나 |
| 03 | `engine/duel.py` 에 `trigger` 라는 글자가 없다 |
| 04 | 생성자를 부르는 production 모듈은 `event_pipeline.py` 하나이고 그 모듈도 unreachable · 테스트는 12개 파일이 쓴다 |
| 05 | 여섯 전이 전부 일어나고 `DuelStep` 에 사건 칸이 없다 |
| 06 | `PhaseChanged` 는 만들어지고 `from`/`to` 를 갖는다 · `_apply_end_phase` 는 `deltas` 를 읽지 않는다 |
| 07 | production 실행기의 `journal` 이 `None` |
| 08 | 실제 발동의 변화가 호출자에게 가지 않는다 |
| 09 | `EffectDefinition` 에 유발/사건/스피드 칸이 없다 |
| 10 | `EFFECT_LIBRARY` 16개 전부 `EVENT_FREE_CHAIN` |
| 11 | `ChainLink` 를 만드는 production 세 파일 · `Duel` 은 아니다 · 실제 링크의 주인은 고른 행위다 |
| 12 | 트리거용 `PlayerActionKind` 가 없고 `legal_actions` 에도 없다 |
| 13 | 트리거 계층이 `priority`/`response` 를 import 하지 않는다 |
| 14 | 후보 수집이 가려진 카드를 못 본다 · `unchecked` 로 남긴다 · `GameState` 거부 |
| 15 | `agent/` 에 트리거가 없다 |

고의 위반 5건 — **전부 잡혔다** (넣고 → 실패 확인 → `git checkout` 되돌림):

| | 위반 | 잡은 테스트 |
|---|---|---|
| A | `engine/duel.py` 가 `engine.timing` 을 import | 01 · 03 |
| B | `_apply_end_phase` 가 `deltas` 를 읽는다 | 06 |
| C | `duel_resolver` 가 `EventJournal` 을 붙인다 | 07 |
| D | `EffectDefinition` 에 `trigger_event` 칸을 더한다 | 09 |
| E | `agent/policy.py` 가 `TriggerSpec` 를 언급한다 | 15 |

전체: **3580 passed · 4 skipped · 0 failed.**

* Regression = **0**
* 신규 = 15 · 수정 = **0** · 삭제 = **0** · skip 증가 = **0**
  (처음 작성한 두 테스트에 조건부 `skip` 이 있었는데, **씨앗과 덱을 고쳐
  실제로 발동이 나오게 만들어 없앴다** — skip 으로 덮지 않았다.)

성능: 3-E-19 362s → **371s**. 새 파일 단독 5.3초. 나머지는 관측된 실행 시간
폭(340~371s) 안이고 새 테스트의 비용이라고 주장하지 않는다.

## 18. Structural Decision

**B. AUDIT-ONLY / FUTURE ARCHITECTURE GAP.**

§13 의 네 조건으로 따진 결과:

| 조건 | 충족 | 근거 |
|---|---|---|
| 1. 기존 production 경로가 이미 그 동작을 지원한다고 주장하는가 | **아니다** | 어떤 production 코드도 트리거를 주장하지 않는다. 각 모듈이 "여기서 끝난다" 를 자기 문서에 적어 두었다 |
| 2. 그 경로가 불완전/모순인가 | 해당 없음 | 경로 자체가 연결되어 있지 않다 |
| 3. 현재 엔진의 올바른 동작을 막는가 | **아니다** | 등록된 유발 효과가 0개다 |
| 4. future scope 로 설명할 수 없는가 | **설명된다** | Trigger Engine 이 들어올 때의 일이다 |

→ **새 STRUCTURAL ID 를 만들지 않는다.** "존재하지만 불리지 않는다" 는
이 프로젝트가 의도적으로 택한 모양이다 (ADR-006: 등록되지 않은 것은 UNKNOWN;
계층은 소비자가 생길 때 잇는다).

감사 소견으로만 기록한다 (ID 없음):

1. **끊긴 자리는 두 곳이고 둘 다 "버린다" 가 아니라 "받을 칸이 없다" 다** —
   `Duel._apply_end_phase` 가 `ProgressionResult.deltas` 를 쓰지 않고,
   `DuelStep` 에 변화/사건 칸이 없다.
2. **잠든 계층이 깨어나면 `ChainLink` 소유자가 둘이 된다** —
   `TriggerChainIntegrator` 는 `PlayerAction` 없이 링크를 만든다. 이을 때 먼저
   정해야 할 것은 "유발 발동도 `PlayerAction` 인가" 다 (임의 유발은 고르는
   일이므로 그래야 할 가능성이 높지만, 이 Phase 는 정하지 않는다).
3. `EffectDefinition` 과 `TriggerSpec` 이 **서로를 모른다** — 이어 붙이려면
   정의에 유발을 적을지, 선언을 따로 둘지를 먼저 정해야 한다.

## 19. Remaining TODOs

| ID | 상태 |
|---|---|
| STRUCTURAL-34 | **유지** — unaffected (§11) |
| STRUCTURAL-124 | **유지** — 재판정하지 않았다 (§12) |
| STRUCTURAL-128 · -131 · -133 | 유지 |
| STRUCTURAL-134 | RESOLVED 유지 |
| SET_ACTIVATION_MISSING | RESOLVED 유지 |
| SET_ACTIVATION_TIMING · SET_ACTIVATION_EXECUTION · SET_CARD_EFFECT_EXECUTION | 유지 — 건드리지 않았다 |
| AFTER_CHAIN_RULE | 유지 |
| UNRESOLVED_PROGRESSION_RULES | 유지 — 목록을 수정하지 않았다 |

## 20. Next Phase Candidate

하나만 올린다.

> **잠든 계층을 **잇기 전에** 결정해야 하는 한 가지 질문의 감사 —
> "유발 효과의 발동은 `PlayerAction` 인가?"**
>
> 이번 감사가 보여 준 것은 연결선이 없다는 사실만이 아니라, **이으려면 먼저
> 소유권을 정해야 한다**는 것이다. `TriggerChainIntegrator` 는 지금
> `PlayerAction` 없이 `ChainLink` 를 만들 수 있게 생겼고, 그대로 연결하면
> `legal_actions()` 를 우회하는 두 번째 실행 경로가 생긴다. 반대로 임의 유발
> (`TriggerRequirement.OPTIONAL`)은 **고르는 일**이므로 `PlayerAction` 이어야
> 할 근거가 공식 규칙 쪽에 있다. 어느 쪽인지를 **공식 룰북과 기존 아키텍처
> 규율(ADR-002 · ADR-006 · "AI 는 PlayerAction 을 고른다")로 먼저 판정하는**
> 감사가 다음 한 걸음이다.
>
> 그 전에는 Trigger Engine 을 만들지 않는다. 지금 만들면 **쓸 카드가 0개인
> 경로**가 된다 (§16).

다음 Phase 는 지시 없이 진행하지 않는다.
