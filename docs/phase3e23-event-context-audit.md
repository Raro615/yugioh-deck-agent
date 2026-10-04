# Phase 3-E-23 — Event → TriggerCandidate Connectivity / Event Context Propagation Audit

## 1. HEAD / Base

| | |
|---|---|
| Base (지시) | `de1ea00` |
| 실제 HEAD | `de1ea00` — Phase 3-E-22 (동일) |
| Working tree | clean · `git diff --stat` 비어 있음 |
| Branch | `claude/pensive-goodall-te1egy` |

## 2. BLOCKER / Engine 변경

**BLOCKER: NO** · **Engine 변경: NO** (production diff 0줄). 추가한 것은
`tests/test_event_context_audit.py` (12개)와 이 문서.

## 3. 핵심 결론

> **문맥을 전달할 통로가 끊긴 것이 아니다. 사건을 묻는 술어가 아직 없다.**
>
> `ConditionContext` 에 `event` 를 더해도 **읽을 코드가 0개**다 — 엔진의 조건
> 어휘(15개 + 규칙 관문 8개)는 전부 "지금 판" 만 묻는다. 그러므로 순서는
> ① 술어 → ② 문맥 → ③ 전달 이고, 지금까지 ③만 이야기해 왔다.

그리고 좋은 소식이 하나 있다: **사건 문맥의 원자료는 이미 `StateDelta` 에 있다.**
`ZoneMoved.source_zone` 이 곧 `previous_location` 이고 `ZoneMoved.movement`
(`OperationKind`)가 곧 "왜 움직였는가" 다. 지금 버려지는 것은 그 delta 를
**사건으로 묶어 전달하는 호출**이다 (3-E-20 · 3-E-22).

### 지시문 §1 의 두 전제 정정

| 지시문 | 실제 (측정) |
|---|---|
| 9. "`TimingEvent.sequence` 가 있으나 전달되지 않는다" | **`TimingEvent` 에 `sequence` 가 없다.** 필드는 `point · delta · effect_ref · actor · note` 다. `sequence` 는 **저널 쪽**(`EffectEvent` · `CostPaymentEvent`)에 있다 (3-E-22 `test_04` 가 고정) |
| 10. "`ConditionContext.event` 를 추가해도 …" | **그 필드는 아직 없다.** 필드는 `player · source · effect_ref · targets` 넷이다 — 그리고 §3 의 결론대로, 더해도 읽을 술어가 없다 |

## 4. Event Data Flow

| 단계 | 객체/함수 | production 존재 | Event 정보 | 다음 단계 전달 | 판정 |
|---|---|---|---|---|---|
| 사건 발생 | `GameState.move` · `draw` · `TurnProgressor.advance` · `EffectExecutor` | **있다** | 판이 실제로 바뀐다 | delta 로 | CONNECTED |
| Delta | `ZoneMoved` · `CardDrawn` · `ZoneShuffled` · `LifeChanged` · `PhaseChanged` · `MonsterSummoned` | **있다** | **이동 이유 · 출발/도착 존 · 주체 · 소환 종류** | `EffectResult.deltas` / `ProgressionResult.deltas` | CONNECTED |
| Timing point | `TimingEvent.from_delta` · `timing_for` · `timing_events` | 코드는 있다 | delta 를 그대로 참조 | — | **MISSING** (production 호출 0) |
| Trigger collection | `TriggerCollector.collect` | 코드는 있다 | `event` 를 받지만 `point` 만 본다 | 후보로 | **DORMANT** |
| Candidate 생성 | `TriggerCollector._judge` | 코드는 있다 | **사건의 주체를 보지 않는다** | — | DORMANT · 정보 손실 |
| Condition 평가 | `ConditionEvaluator` + 조건 어휘 23개 | **있다** | **사건 없음** (`ConditionContext` 4칸) | — | **MISSING** |
| Ordering | `TriggerOrdering` | 코드는 있다 | `event` 보존 | — | DORMANT |
| PlayerAction 변환 | — | **없다** | — | — | **MISSING** (3-E-22) |

## 5. Event Types Audit

`StateDelta` 의 구체 타입 **6개**와 그 필드:

| Delta | 필드 | 사건 문맥으로서의 값 |
|---|---|---|
| `ZoneMoved` | `movement`(`OperationKind`) · `card` · `source_player` · `source_zone` · `destination_player` · `destination_zone` | **"왜"(파괴/묘지로/제외/되돌리기…) + 직전 위치 + 주체** — 유발 판정의 핵심 |
| `CardDrawn` | `player` · `card` | 드로우 사건 |
| `ZoneShuffled` | `player` · `zone` · `size` · `draw` | 셔플 (STRUCTURAL-74 로 `UNIMPLEMENTED` 처리) |
| `LifeChanged` | `player` · `before` · `after` | LP 변화량 |
| `PhaseChanged` | `from_turn` · `from_player` · `from_phase` · `to_turn` · `to_player` · `to_phase` | 페이즈 전이 (3-E-19 · 3-E-20) |
| `MonsterSummoned` | `summon` · `card` · `player` · `owner` · `from_zone` · `to_zone` · `to_index` · `position` | 소환 종류 + 출발 존 |

`JournalEvent` 계열 **2개**(`EffectEvent` · `CostPaymentEvent`)는
`sequence` · `effect_ref` · `actor` · `deltas` · `applied`/`payments` 를 갖는다 —
**사건 번호는 여기에만 있다.**

없는 것: **체인 상대 효과**(`re`)와 **체인 정보**(`ev`)를 담는 delta/사건이
없다. 체인은 `Chain`/`ChainLink` 로 따로 있고 사건 쪽과 연결되어 있지 않다.

## 6. Minimum Event Context — corpus 가 말한다

측정 방법: **기존 분석기**(`EffectAnalyzer` → `PredicateAnalyzer`)로 전 corpus
12,504장을 돌려 조건 leaf 를 `EvalReadiness` 로 분류했다. 새 정규식을 쓰지 않았다.

조건 트리가 있는 효과 블록 **9,630개** · leaf **20,547개**:

| readiness | 수 | 비율 |
|---|---|---|
| **NEEDS_CONTEXT** | **8,511** | **41.42%** |
| EVALUABLE | 6,684 | 32.53% |
| UNKNOWN | 5,352 | 26.05% |

`NEEDS_CONTEXT` 를 요구하는 술어 (카드 **4,104장**):

| 술어 | 수 | 요구하는 정보 | 현재 존재 | production 전달 | 없으면 |
|---|---|---|---|---|---|
| `group_exists` | 1,330 | 사건 묶음 `eg` | delta 여럿 (묶는 번호 없음) | **아니다** | UNKNOWN |
| `battle` | 1,154 | 공격자/공격 대상 | **없다** (전투 계층 미완) | 아니다 | UNKNOWN |
| `player_comparison` | 990 | `rp`(이유의 주체) · `tp` | `tp` 있음 · `rp` **없음** | 아니다 | UNKNOWN |
| `chain_effect_type` | 962 | 체인 상대 효과 `re` | `Chain`/`ChainLink` 에 일부 | 아니다 | UNKNOWN |
| `event_reason` | 928 | `REASON_*` | **`ZoneMoved.movement`** | 아니다 | UNKNOWN |
| `chain_state` | 785 | `ev` · 체인 정보 | 부분 (`Chain`) | 아니다 | UNKNOWN |
| **`previous_location`** | **758** | 직전 위치 | **`CardInstance.previous`** · `ZoneMoved.source_zone` | 아니다 | UNKNOWN |
| `flag_effect` | 325 | 카드에 걸린 표식 | `status_flags`/`temporary_effects` 자리 | 아니다 | UNKNOWN |
| `card_status` | 324 | 카드 상태 비트 | 부분 | 아니다 | UNKNOWN |
| `previous_controller` | 314 | 직전 컨트롤러 | **있다** (`previous`) | 아니다 | UNKNOWN |
| `group_contains` | 248 | 묶음 포함 여부 | 위와 같다 | 아니다 | UNKNOWN |
| `previous_position` | 202 | 직전 표시 형식 | **있다** (`previous`) | 아니다 | UNKNOWN |
| `summon_type` | 111 | 소환 종류 | **`MonsterSummoned.summon`** | 아니다 | UNKNOWN |
| `player_affected` | 80 | 플레이어에 걸린 효과 | 없다 | 아니다 | UNKNOWN |

**주체 분포가 결론을 말해 준다** — 필요한 최소 문맥은 추측이 아니라 **EDOPro 의
효과 콜백 서명 `(e,tp,eg,ep,ev,re,r,rp)`** 그대로다:

| 주체 | 수 | 대표 |
|---|---|---|
| `self` (`c` · `e:GetHandler()`) | 3,054 | `event_reason` 858 · `previous_location` 752 · `previous_controller` 289 |
| `duel` (`Duel.*`) | 1,788 | `battle` 892 · `chain_state` 771 |
| `event_group` (`eg`) | 1,291 | `eg:IsExists` 1,082 · `eg:IsContains` 209 |
| `player` (`rp`/`tp` 비교) | 990 | `rp==tp` |
| `chain_effect` (`re`) | 945 | `re:IsTrapEffect()` |
| `local` | 424 | 지역 변수 — 주체를 확정할 수 없다 |
| `chain_card` (`re:GetHandler()`) | 19 | |

**필수 / 선택 / 불필요** (지금 Trigger 를 이을 때 기준):

* **필수** — ① 사건 종류(`point`, 이미 있다) ② **사건 주체**(`card`) ③ **이유**
  (`movement`) ④ **직전 위치**(`source_zone` 또는 `previous`) ⑤ **사건 번호**
  (delta 들을 한 사건으로 묶는 것 — `EffectEvent.sequence` 가 그 자리다)
* **선택** — 소환 종류 · LP 변화량 · 페이즈 전이의 출발/도착
* **지금은 불필요** — `re`/`ev`(체인 상대 효과·체인 정보)와 `battle`:
  **그 계층 자체가 아직 없다.** 억지로 자리를 만들면 모양이 어긋난다
  (`TimingPoint` 가 전투·데미지를 미리 못박지 않은 것과 같은 이유).

## 7. previous_location 집중 감사

| 질문 | 답 |
|---|---|
| 1. 실제 Condition 이 요구하는가 | **그렇다 — leaf 758건** (분석기로 재현, `test_09`) |
| 2. parser 가 추출하는가 | 원문 `IsPreviousLocation(...)` 을 조건 문자열로 보존한다 |
| 3. analysis 가 표현하는가 | **그렇다** — `PredicateKind.PREVIOUS_LOCATION` + `NEEDS_CONTEXT` |
| 4. engine 이 생성하는가 | **그렇다** — `CardInstance.previous` 가 `place`/`set_position`/`set_controller` 에서 **자동으로** 채워진다 (`remember_previous=True` 가 기본값, `test_03` 이 실제 듀얼에서 확인) |
| 5. Event/Delta 가 보존하는가 | **그렇다** — `ZoneMoved.source_zone` |
| 6. `TriggerCandidate` 까지 전달 가능한가 | **아니다** — 읽는 술어도, 넘기는 호출도 없다 |
| 7. 현재 위치만으로 복원 가능한가 | **아니다.** 다만 **직전 한 단계는 상태에 이미 있다** |
| 8. 복원 불가능하면 Event Context 가 필수인가 | **"왜" 와 "두 단계 전" 에 대해서는 필수다** |

세 가지를 정확히 갈라야 한다.

1. **지금 어디 있는가** — `CardInstance.zone`. 있다.
2. **직전에 어디 있었는가** — `CardInstance.previous.location`. **있다. 그리고
   `canonical_state` 에 들어가므로 이미 판의 모양이다** (`test_05`). 즉 "역사는
   판의 모양이 아니다"(3-E-22 §9)는 **사건의 역사(journal)** 에 대한 말이고,
   "마지막 상태" 는 이미 모양으로 간주되고 있다.
3. **왜 움직였는가 · 두 단계 전** — **없다.** `previous` 는 한 칸이므로 두 번
   움직이면 첫 위치가 지워지고(`test_06`), `CardInstance` 에 reason 칸이 없어서
   ADR-002 가 가른 "파괴" 와 "묘지로 보내기" 를 상태만으로 구분할 수 없다.

읽는 코드는 **하나도 없다** (`test_04`: `engine/` 에서 `.previous` 를 읽는 자리는
그것을 쓰는 `card_instance.py` 뿐). 즉 758건의 요구에 대해 **데이터는 있고
소비자가 없다.**

## 8. Event Identity

| 질문 | 답 |
|---|---|
| 1. 모든 Event 에 `sequence` 가 붙는가 | **아니다** — `EffectEvent` · `CostPaymentEvent` 에만 있다 |
| 2. `TimingEvent` 에 붙는가 | **아니다** (필드 5개에 없다) |
| 3. 같은 `point` 의 여러 사건을 구분할 수 있는가 | 후보 단독으로는 **불가** (3-E-22 `test_05`). 컬렉션이 `delta` 를 들고 있을 때만 구분된다 |
| 4. `EffectResult` 와 이동 사건을 구분할 수 있는가 | **타입으로는 구분된다** (`EffectEvent` vs `ZoneMoved`) |
| 5. 한 사건이 여러 Operation 을 포함하면 | `EffectEvent.deltas` 가 묶지만 **production 에서 저널이 비어 있다** |
| 6. `clone()` 에서 `sequence` 는 | 저널이 `GameState` 밖에 있으므로 **복제 대상이 아니다**. 반면 `previous` 는 복제된다 (`test_07`) |
| 7. replay/결정론에서 안정적인가 | `sequence` 는 무작위·시각을 쓰지 않으므로 **구조적으로 안정적**이다 (저널 모듈이 그렇게 적어 두었다) |

→ **UUID 가 필요하다는 결론이 아니다.** 이미 있는 `sequence`(구조적 번호)로
충분하고, 문제는 그 번호가 **트리거 쪽으로 오지 않는다**는 것뿐이다.

## 9. ConditionContext.event

```
사건 발생        CONNECTED   (delta 가 실제로 만들어진다)
→ 문맥 구성      MISSING     (ConditionContext 에 event 칸이 없다 · 넘기는 호출 0)
→ 문맥 전달      MISSING     (같은 이유)
→ 조건 평가      MISSING     (사건을 묻는 술어가 0개 — 어휘 15개 + 관문 8개 전부 판만 본다)
→ 적격성         DORMANT     (TriggerEligibilityJudge 는 있으나 불리지 않는다)
```

production 의 `ConditionContext(...)` 생성 자리를 전부 AST 로 모아 키워드를
합집합으로 봤다 — **`player` · `source` · `effect_ref` · `targets` 네 개뿐이고
`event` 는 없다** (`test_02`). 조건들이 문맥에서 읽는 속성도 같은 네 개뿐이며,
`getattr(context, "event", …)` 같은 우회도 없다 (`test_01`).

## 10. Trigger Corpus 분류

| 분류 | 수 (leaf) | 비율 |
|---|---|---|
| A 현재 state 만으로 판정 가능 | 6,684 | 32.53% |
| B·C·D 사건 / 직전 상태 / 체인·순서가 있어야 판정 가능 | **8,511** | **41.42%** |
| E 현재 데이터만으로 의미 판정 불가 | 5,352 | 26.05% |

B·C·D 의 내부 분해는 §6 의 표와 같다 (직전 상태 1,274 · 사건 묶음 1,578 ·
이유·주체 1,918 · 체인 1,726 · 전투 1,154 · 소환 종류 111 …).

## 11. EVENT_FREE_CHAIN 재검증

`EVENT_FREE_CHAIN` 은 **유발 사건이 아니다.** 등록된 효과 16개는 전부
`EVENT_FREE_CHAIN` 이고, 그 `activation` 조건은 `ZoneCountAtLeast` · `And` ·
없음뿐 — **전부 판만 본다** (`test_11`). 그래서 지금 실행되는 발동은 사건 문맥을
**요구하지 않고**, 사건 전달이 없어도 현재 실행이 틀리지 않는다.

3-E-17 의 결론 그대로 쓴다: `EVENT_FREE_CHAIN` 은 "유발 조건이 없다" 를 말하는
**값**이고 (`None` 이 아니다), 사건 의존 조건과 혼동하지 않는다. 이번 감사에서도
그 둘이 섞인 자리는 없었다.

## 12. Ownership 후보 재평가

| 후보 | lifetime | clone | simulation | replay | hidden info | 결정론 | 판정 |
|---|---|---|---|---|---|---|---|
| **A `GameState`** | 판과 같다 | 공짜 | 공짜 | 좋다 | 관측과 분리 필요 | 좋다 | **부분적으로 이미 그렇다** — `previous` 가 `canonical_state` 에 있다. 그러나 **사건의 역사(journal)** 는 "앞으로도 넣지 않는다" 가 결정되어 있다 |
| **B `Duel` runtime flow** | 흐름과 같다 | 값 공유 (불변이어야 한다) | 사본이 값으로 가져간다 | 약하다 | 판 밖이라 안전 | 불변이면 좋다 | **후보 1** (3-E-22 의 결론) |
| **C Timing/Event context** | 사건 하나 | 명시적 | 명시적 | 좋다 | 안전 | 좋다 | **후보 2 — 의미가 가장 맞다** (`TimingWindow`) |
| **D Chain context** | 체인과 같다 | 체인과 함께 | 함께 | 보통 | 안전 | 좋다 | **부적합** (후보는 체인 **전**에 생긴다) |
| **E Trigger pending 전용 구조** | 직접 관리 | 직접 | 직접 | 직접 | 안전 | 직접 | 보류 (새 subsystem) |
| **F Event journal** | 듀얼 전체 | `GameState` 밖 | **사본에 안 따라간다** | **가장 좋다** | 안전 | 좋다 | **사건 번호의 자리**로는 맞다. 후보 보관소로는 과하다 |

**Search 사본이 사건 문맥을 함께 복제해야 하는가 → 그렇다.** 근거: `previous` 는
이미 `GameState.clone()` 으로 복제되어 사본에서도 같은 1단계를 보는데
(`test_07`), 저널은 `GameState` 밖이라 복제되지 않는다. 사건 의존 조건을 사본이
다르게 평가하면 깊이 1 의 점수가 실제와 갈린다.

## 13. Search / Simulation

**agent/ 변경 없음.** 요구사항만 기록한다.

| 질문 | 답 |
|---|---|
| 1. 원본의 사건 문맥을 복제해야 하는가 | **그렇다** (위 근거) |
| 2. Search 가 새 사건을 만들어도 되는가 | **안 된다.** 사건은 판을 바꾼 결과이고, 사본은 `apply()` 를 통해서만 판을 바꾼다 |
| 3. 과거 사건이 사라지면 `legal_actions()` 결과가 달라질 수 있는가 | **그렇다** — 사건 의존 유발이 연결된 뒤에는 |
| 4. Search ON/OFF 로 유발 결과가 달라질 수 있는가 | **문맥을 복제하지 않으면 그렇다.** 그래서 1번이 요구사항이다 |

## 14. Hidden Information

**누출 없음 · `GameStateView` 변경 없음** (`test_12`).

* 관측에 `previous` · `event` · `journal` · `trigger` 라는 필드가 **없다**
  (`result_reason` 은 듀얼 **결과**의 이유이고 사건이 아니다).
* 그래서 사건 문맥을 쓰려면 둘 중 하나를 골라야 한다 — ① 관측을 넓힌다
  ② 판을 들고 있는 쪽이 **값으로** 넘긴다 (ADR-007 · `_set_this_turn` 선례).
  **이 Phase 는 고르지 않는다.**
* 주의할 것 하나: 상대의 **패에서** 묘지로 간 카드의 직전 위치는 공개 정보일 수
  있지만, 상대 패 **안에서의** 이동은 아니다. 사건 문맥을 관측에 넣는 길을 고르면
  이 구분을 먼저 해야 한다 — 지금은 그 문제를 만들지 않았다.

## 15. Production Boundary

```
State mutation    CONNECTED
→ Delta           CONNECTED
→ TimingEvent     MISSING    (변환 함수는 있고 production 호출이 0)
→ TriggerCollector DORMANT   (부르는 모듈이 unreachable)
→ TriggerCandidate DORMANT
→ ConditionContext MISSING   (event 칸이 없다)
→ Condition 평가   MISSING   (사건을 묻는 술어가 0개)
→ PlayerAction     MISSING   (3-E-22)
```

## 16. Structural Classification

| 질문 | 판정 |
|---|---|
| A. production Trigger 가 없어서 단순 미래 작업인가 | **부분적으로 그렇다** — 지금 틀리는 실행이 없다 |
| B. Trigger 를 연결하려면 Event Context ownership 이 반드시 필요한가 | **그렇다** (사건 의존 leaf 41%) |
| C. Event Context 가 존재하는데 propagation 만 끊겼는가 | **아니다 — 이것이 이번 Phase 의 교정이다.** 원자료(delta)는 있지만 **읽을 술어가 0개**다. propagation 만의 문제가 아니다 |
| D. Event identity 가 부족해서 새 구조가 필수인가 | **아니다.** `sequence`(구조적 번호)로 충분하고 UUID 는 필요하지 않다 |
| E. `previous_location` 때문에 현재 state 기반 재구성이 불가능한가 | **직전 1단계는 가능하다** (이미 상태에 있다). **"왜" 와 두 단계 전은 불가능하다** |
| F. 기존 STRUCTURAL-31 / `UNRESOLVED_ORDER_RULES` 에 포함되는가 | **포함된다** — 31 은 "대상·비용을 채울 계층", 순서 목록은 SEGOC 쪽이다. **사건 문맥은 둘 중 어느 것도 아니다** |

### 신규 STRUCTURAL ID — 만들지 않는다

§16 의 네 조건 중 **2번(향후 Trigger production 연결의 필수 조건)** 은 만족하고
**3번(ownership/architecture 문제)** 도 만족하지만, **1번**이 미묘하고 **4번**이
성립하지 않는다:

* 1번(기존 TODO 미커버) — 사건 문맥 자체는 STRUCTURAL-31 도 `UNRESOLVED_ORDER_RULES`
  도 덮지 않는다. 그러나 `UnimplementedRule` 과
  `engine/condition/__init__.py`·`model.py` 가 "체인 · 트리거 · 타이밍 조건은
  시스템 자체가 없다" 를 이미 **구조로** 표현하고 있다 (그 조건은 언제나
  `UNKNOWN` 이고 `missing_rules` 로 이름을 남긴다).
* 4번(현재 구조에서 자연스럽게 해결 불가) — **성립하지 않는다.** 필요한 값이
  이미 `ZoneMoved`(이유 · 출발 존) · `CardInstance.previous`(직전 상태) ·
  `EffectEvent.sequence`(사건 번호)에 있고, 전달 방식의 선례도
  `_set_this_turn`(ADR-007)에 있다. 새 subsystem 없이도 이을 수 있는 모양이다.

→ **신규 STRUCTURAL 없음.** 대신 이 문서에 **구조 결정 하나**를 남긴다:

> **사건을 묻는 조건 술어를 먼저 만든다.** `ConditionContext` 에 `event` 를
> 더하는 것은 그 다음이고, 전달은 마지막이다. 반대 순서로 하면 읽는 사람이 없는
> 필드가 먼저 생긴다 (ADR-006 의 "등록되지 않은 것은 UNKNOWN" 과 같은 규율).

## 17. 기존 TODO

| ID | 상태 |
|---|---|
| STRUCTURAL-31 / -32 / -33 | 유지 |
| STRUCTURAL-34 / -124 / -128 / -131 / -133 | 유지 — unaffected |
| STRUCTURAL-134 · SET_ACTIVATION_MISSING | RESOLVED 유지 |
| SET_ACTIVATION_TIMING · SET_ACTIVATION_EXECUTION · SET_CARD_EFFECT_EXECUTION | 유지 |
| AFTER_CHAIN_RULE · UNRESOLVED_PROGRESSION_RULES · UNRESOLVED_ORDER_RULES | 유지 |

## 18. Tests

신규 `tests/test_event_context_audit.py` — **12개**.

| # | 검증 |
|---|---|
| 01 | 조건 어휘 15개 + 관문 8개가 전부 판만 묻는다 · `getattr` 우회도 없다 |
| 02 | `ConditionContext` 에 `event` 칸이 없고 넘기는 호출도 없다 (생성 자리 전수) |
| 03 | `previous` 가 실제 듀얼에서 자동으로 기록된다 |
| 04 | 그 값을 읽는 production 코드가 없다 |
| 05 | 직전 상태가 `canonical_state` 에 들어간다 (= 이미 판의 모양) |
| 06 | 한 단계만 남고 "왜" 는 처음부터 없다 |
| 07 | 사본이 그 한 단계를 함께 복제한다 |
| 08 | 조건 leaf 의 41% 가 `NEEDS_CONTEXT` (하한 고정) |
| 09 | `previous_location` 758건 재현 |
| 10 | 필요한 문맥이 EDOPro 콜백 서명과 일치 (주체 분포) |
| 11 | `EVENT_FREE_CHAIN` 은 사건 의존이 아니다 |
| 12 | 관측에 직전 상태 · 사건이 없다 |

고의 위반 5건 — 전부 잡혔다:

| | 위반 | 잡은 테스트 |
|---|---|---|
| A | 조건 어휘에 `PreviousLocationIs` 를 더한다 | 01 |
| B | `ConditionContext` 에 `event` 를 더한다 | 02 |
| C | 조건이 `getattr(context, "event")` 로 읽는다 | 01 (처음엔 **놓쳤고**, `getattr` 검사를 더해 잡았다) |
| D | 관측(`CardView`)에 `previous_location` 을 노출한다 | 12 |
| E | `remember_previous` 기본값을 끈다 | 06 |

(C 를 처음 놓친 것은 내 테스트의 빈틈이었다 — AST 가 `ast.Attribute` 만 보고
`getattr` 를 보지 않았다. 고쳐서 다시 확인했다.)

전체: **3617 passed · 4 skipped · 0 failed · 377s.**
Regression **0** · 신규 12 · 수정 **0** · 삭제 **0** · skip 증가 **0**.

## 19. 최종 판정

**B. AUDIT-ONLY / FUTURE ARCHITECTURE GAP.**

`C` 가 아닌 이유: 사건 의존 조건을 **잘못 평가하는 production 경로가 없다** —
등록된 16개 효과의 조건은 전부 판만 보고, 사건 의존 술어는 아예 존재하지 않는다.
`D`(BLOCKER)도 아니다 — 현재 엔진과 AI 는 정상 동작한다.

## 20. 다음 Phase 후보 — 정확히 하나

> **사건 의존 조건을 `UnimplementedRule` 로 **정직하게 표시**할 수 있는지의 감사.**
>
> 이번 감사의 결론은 "술어가 먼저" 다. 그런데 술어를 만들기 전에 확인할 것이
> 하나 있다: 엔진은 이미 "판정할 규칙이 없다" 를 말하는 수단
> (`UnimplementedRule` — 언제나 `UNKNOWN`, `missing_rules` 에 이름을 남긴다)을
> 갖고 있고, **등록된 16개 효과에는 그런 조건이 하나도 없다.** 그러면
> 질문은 이것이다 — 사건 의존 조건을 가진 카드를 **정의로 등록하려고 하면**
> 지금 구조가 그 사실을 `UNKNOWN` 으로 **정확히** 표현하는가, 아니면 조용히
> `ELIGIBLE`/`VALID` 로 통과시키는가?
>
> (3-E-22 의 `test_06` 이 트리거 쪽에서 **거짓 `ELIGIBLE`** 을 이미 하나
> 실측했다. 같은 일이 `EFFECT_LIBRARY` 등록 경로에서도 일어나는지 — 즉
> "조건을 적지 않은 정의" 와 "사건이 없어서 판정 못 하는 정의" 가 구분되는지를
> 재는 것이 다음 한 걸음이다. 그것이 확인되면 사건 술어를 **안전하게** 하나씩
> 추가할 수 있다.)

다음 Phase 는 지시 없이 진행하지 않는다.
