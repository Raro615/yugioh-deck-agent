# Phase 2-V — Effect Operation Integration

기준 커밋: `8b14b18` (Phase 2-U Effect-driven Special Summon Integration)

```
EffectDefinition.operations
    ↓
EffectExecutor.execute
    ↓  _plan_operation ─┐
    │                   ├─ OPERATION_HANDLERS[kind]  ← 표 **하나**
    ↓  _apply ──────────┘
GameState 변경  +  StateDelta
    ↓  EventReader
ObservedEvent → TimingEvent                          (Phase 2-J)
```

**새 operation 을 많이 구현한 단계가 아니다.** 이미 있던 열한 가지가
DESTROY · MOVE · SPECIAL_SUMMON · DRAW · CHANGE_LIFE 로 서로 다른 계층을
쓰면서도 **하나의 계약**을 지키는지 보고, 지키지 못하게 만들던 구조를
고쳤다.

---

## 1. 변경 파일

| 파일 | 변경 |
|---|---|
| `engine/effect/executor.py` | dispatch 를 `OPERATION_HANDLERS` 표 하나로 통합 · 종류별 계획기/수행기 분리 · `SUPPORTED` 를 표에서 세움 |
| `tests/engine/test_operation_integration.py` | 신규 — 80개 |
| `docs/phase2v-operation-integration.md` · `engine/__init__.py` | 문서 |

**새 모듈 0개. 새 ValidationCode 0개. 새 OperationKind 0개. 새 실제 카드
0장.** 이 단계에서 추가된 실행 능력은 없다 — 표만 하나가 되었다.

---

## 2. 기존 abstraction 조사 (§1 · §2)

먼저 "이미 있는 것" 을 세었다. 새로 만들 이유가 있는지 보기 위해서다.

| 이미 있던 것 | 어디서 | 이번에 |
|---|---|---|
| `OperationKind` (12) · `Operation` 계층 | Phase 2-L | 그대로 |
| `DESTINATION` · `DESTINATION_OWNER` · `destination_player` | Phase 2-L · 2-M | 그대로 |
| `REASON_NAMES` (의미 → 이유) | Phase 2-L | 그대로 |
| 계획-후-적용 (`_Step` → `_apply`) | Phase 2-D-2 | 그대로 |
| `AppliedOperation` · `StateDelta` · `EffectResult` | Phase 2-K | 그대로 |
| 관문 (`RULE_GATED` · `GATING_RULES` · `MISSING_GATE`) | Phase 2-M · 2-U | 그대로 |
| `TargetResolver` · `CandidateSet` | Phase 2-N | 그대로 |
| `SummonProcedure` | Phase 2-T | 그대로 |
| `EventReader` · `ObservedEvent` | Phase 2-J | 그대로 |
| `EventJournal` | Phase 2-D-3 | 그대로 |

**결론: 새 abstraction 은 필요하지 않았다.** 필요한 것은 있던 것을 **한
군데에서** 고르게 만드는 일이었다.

### Operation taxonomy (§2)

`OperationKind` 12개 중 실행 가능한 것은 **11개**, 실행되지 않는 것은
`UNKNOWN` 하나다.

| 갈래 | 종류 | 쓰는 계층 |
|---|---|---|
| 수치 | `draw` | `GameState.draw` |
| 수치 | `change_life` | `PlayerState.change_life` |
| 의미 있는 이동 | `destroy` · `send_to_grave` · `banish` · `release` · `discard` · `return_to_hand` · `return_to_deck` | `GameState.move` + `DESTINATION` |
| 의미 없는 이동 | `move` | `GameState.move` (목적지를 조작이 들고 있다) |
| 소환 | `special_summon` | `SummonProcedure` (Phase 2-T) |
| 표현 못 한 것 | `unknown` | **없음** — `UNSUPPORTED_REASON` 에만 있다 |

---

## 3. 발견한 문제 — dispatch 가 둘이었다 (§3)

Phase 2-V 이전의 `EffectExecutor` 는 **같은 일을 두 번, 서로 다른 것으로**
갈랐다.

| | 무엇으로 갈랐는가 |
|---|---|
| `_plan_operation` | `isinstance(operation, DrawOperation)` … — **클래스** |
| `_apply` | `operation.kind is OperationKind.DRAW` … — **종류** |

둘 다 동작했다. 문제는 **새 일을 더할 때 한 곳만 고쳐도 조용히 지나간다**는
것이다.

- 계획만 더하면 → 계획은 통과하고 `_apply` 가 끝까지 내려가
  `_apply_card_movement` 의 `DESTINATION[kind]` 에서 `KeyError` 로 터진다.
  **판을 이미 건드린 뒤**일 수도 있다 (여러 일 중 둘째부터).
- 수행만 더하면 → `SUPPORTED` 와 어긋난다. `SUPPORTED` 는 **손으로 적은
  집합**이었으므로 어느 쪽과도 자동으로 맞지 않았다.

즉 "이 실행기가 무엇을 할 줄 아는가" 를 말하는 자리가 **셋**이었다
(`SUPPORTED` · `_plan_operation` · `_apply`).

### 고친 모양

```python
OPERATION_HANDLERS: dict[OperationKind, OperationHandler] = { ... }
SUPPORTED = frozenset(OPERATION_HANDLERS)
```

`OperationHandler` 는 `(plan, apply, note)` 한 쌍이다. **표에 줄을 더하는
것이 "이 일을 할 줄 안다" 는 유일한 선언이다.** 계획만 더하거나 수행만
더하는 일이 불가능해졌다 — 한 값 안에 둘이 같이 있기 때문이다.

`_plan_operation` 과 `_apply` 는 각각 **표를 찾아 넘기는 세 줄**로 줄었다.
남은 `if` 하나는 "표에 없다" 는 실패 처리이지 종류별 분기가 아니다.

### 거대한 `if/elif` 도 아니다

종류별 코드는 **이름 있는 계획기/수행기**로 흩어졌다.

| 계획기 | 수행기 | 맡는 종류 |
|---|---|---|
| `_plan_draw` | `_apply_draw` | `draw` |
| `_plan_life_change` | `_apply_life_change` | `change_life` |
| `_plan_summon_operation` | `_apply_special_summon` | `special_summon` |
| `_plan_card_operation` | `_apply_card_movement` | `move` + 의미 있는 이동 7가지 |

여덟 종류의 카드 이동이 **한 쌍을 나눠 쓴다.** 의미는 `kind` 가 들고
다니고 (`DESTINATION` · `REASON_NAMES`), 코드가 갈라지지 않는다 — ADR-002
("파괴 ≠ 묘지로 보내기") 는 코드 분기가 아니라 **값의 차이**로 유지된다.

### 표를 `kind` 로 키잡아도 되는 이유

`_plan_draw` 는 `operation.count` 를 읽는다. 표는 `kind` 로 찾는데 어떻게
`DrawOperation` 임을 아는가? **조작이 스스로 자기 종류를 제한하기**
때문이다 — `CardOperation(OperationKind.DRAW, ...)` 는 생성 시점에
`ValueError` 다. 종류와 부류가 1:1 이다.

이것은 가정이 아니라 **단언**이다:
`test_a_each_kind_has_exactly_one_operation_class` 가 `OperationKind` 전체를
돌며 확인한다.

---

## 4. 공통 실행 계약 (§4)

여섯 갈래(`draw` · `change_life` · `destroy` · `send_to_grave` · `move` ·
`special_summon`)에 **같은 단언**을 건다.

| 성공하면 | 확인 |
|---|---|
| `status` | `RESOLVED` |
| `applied` | 비어 있지 않다 · `kind` 와 `reason_names` 가 조작과 같다 |
| `deltas` | 비어 있지 않다 · 판을 **읽어서** 적는다 |
| `changed_state` | `True` · `state_hash()` 가 달라진다 |
| Event pipeline | `EventReader` 가 읽는다 · 전부 `is_observable` · `event_id` 있음 |
| Journal | `EventJournal` 에 정확히 하나 |

| 실패하면 | 확인 |
|---|---|
| `applied` | `()` |
| `deltas` | `()` |
| `state_hash()` | **불변** |

일이 달라도 약속은 하나다. 이것이 이 단계의 요점이다.

---

## 5 ~ 8. 종류별로 무너진 것이 없는지

### DESTROY (§5)

- 판정기 없으면 **여전히 멈춘다** (`UNCHECKED_RULES`, 판 불변).
  실제 카드의 파괴 재정을 지어내지 않는다 (Phase 2-O).
- `AppliedOperation.reason_names` 에 `DESTROY` 가 남는다 — `SendToGrave` 와
  기록이 다르다.
- 관문 목록의 모양은 그대로 (`RULE_GATED == {DESTROY, SPECIAL_SUMMON}`).

### MOVE (§6)

- `HAND → GRAVE` · `MZONE → HAND` · `GRAVE → REMOVED` 세 경로 그대로.
- **이유를 주장하지 않는다** — `REASON_NAMES[MOVE] == ()`. 같은 자리로
  옮겨도 `discard` 와 기록이 다르다는 것을 나란히 확인한다.
- 목적지는 표가 아니라 **조작**이 들고 있다. `_apply_card_movement` 의
  그 한 줄이 MOVE 와 나머지의 유일한 차이다.

### SPECIAL_SUMMON (§7)

- 판정기 없으면 **여전히 멈춘다** (`UNCHECKED_RULES`).
- `ZoneMoved` 가 아니라 `MonsterSummoned` 를 남긴다 — `TimingPoint` 도
  `MONSTER_SUMMONED` 다. "몬스터 존으로 옮겼다" 와 "특수 소환되었다" 가
  한 기록이 되지 않는다.
- 놓는 일은 Phase 2-T 의 `SPECIAL_SUMMON_PROCEDURE` 가 한다. **두 번째
  소환 실행기가 없다** — `engine/` 전체에서 `Summon` 을 이름에 가진
  executor 클래스를 세어 확인한다.

### DRAW / LP (§8)

- `GameState.draw` · `PlayerState.change_life` 를 **그대로** 부른다.
- 덱보다 많이 뽑으라 하면 **한 장도 뽑지 않는다** (`INSUFFICIENT_CARDS`).
  `GameState.draw` 는 있는 만큼만 옮기는 primitive 라서, 그대로 부르면
  "3장 드로우" 가 조용히 1장이 된다.
- **`DrawEngine` · `LifePointEngine` · `DamageEngine` 을 만들지 않았다.**
  `engine/` 전체에 그런 이름의 클래스가 없음을 확인한다.

---

## 9 · 11 · 18. 경계

| 지키는 경계 | 확인 |
|---|---|
| `OperationKind` ≠ `PlayerActionKind` (ADR-001) | 값이 같아도 다른 enum · 같은 값이 아니다 |
| 실행기가 체인 · 응답 · 우선권 · 트리거를 부르지 않는다 (§11) | AST — `engine.chain` · `engine.trigger` · `engine.response` · `engine.priority` · `engine.event_pipeline` import 없음, `ChainResolver` · `ResponseLoop` · `PriorityResolver` · `TriggerCollector` 사용 없음 |
| 실행기가 스스로 고르지 않는다 (§10) | AST — `choose` · `select_` · `score` · `policy` 이름의 함수 없음 · `random` 없음 |
| 새 실행 architecture 없음 (§18) | AST — `engine/` 전체에 `*Bus` 클래스 없음 · `EffectExecutor` 는 한 곳에만 정의 |

Event pipeline(§12)도 새로 만들지 않았다 — 여섯 갈래가 전부 기존
`EventReader` 를 지난다.

---

## 10. Target / Selection

실행기는 `TargetResolver` 에게 **묻기만** 한다. 고르는 것은 밖이다.

- 고른 것이 후보가 아니면 → `INVALID_TARGET` / `CANDIDATE_NOT_ELIGIBLE`
- 관측 밖이면 → `UNCHECKED_TARGET` / `HIDDEN_CARD`
- 출발 자리가 어긋나면 → `INVALID_TARGET` / `SOURCE_WRONG_ZONE`

순서가 규칙이다: **대상이 적법한가 → 해도 되는가(관문) → 어디에
놓는가.** 전부 판에 손대기 전이다.

---

## 12. 실제 카드 end-to-end (§13 · §17)

실제 카드는 **발동 → 체인 → 해결**의 기존 경로를 지난다. 실행기를 직접
부르지 않는다.

| 카드 | 경로 | 결과 |
|---|---|---|
| 욕망의 항아리 (55144522) | `DRAW` | `ACTIVATED` → `RESOLVED` → 패 +2 → `CARD_DRAWN` × 2 |
| 은혜의 단비 (66719324) | `CHANGE_LIFE` × 2 | `ACTIVATED` → `RESOLVED` → 양쪽 LP +1000 |
| 싸이크론 (5318639) | `DESTROY` | `ACTIVATED` → **`UNCHECKED_RULES`** → 판 불변 |

세 카드가 **서로 다른 수행기 세 개**를 지난다 (`len(set(...apply)) == 3`).
같은 실행기, 같은 계약, 다른 계층.

싸이크론이 멈추는 것은 결함이 아니다 — 실제 카드의 파괴 재정을 임의로
`confirmed` 처리하지 않는다는 Phase 2-O 의 결론이 그대로다.

### MOVE · SPECIAL_SUMMON 은 실제 카드가 없다 (정직한 결과)

- `MOVE` 는 **설계상** 실제 카드가 될 수 없다. 의미를 주장하지 않는
  이동이므로 `LibraryEntry` 가 거부한다.
- `SPECIAL_SUMMON` 은 소환 조건 계층이 없어서 실행 가능한 카드가 아직
  없다 (STRUCTURAL-64). 죽은 자의 소생(83764718)은 목록에 있지만
  `executable=False` 다.

이 사실을 **테스트가 고정한다** — 실행 가능한 카드가 쓰는 종류는 정확히
`{DRAW, CHANGE_LIFE, DESTROY}` 셋뿐이다. 늘어나면 테스트가 깨지고, 그때
이 문단을 고친다.

---

## 13. 실패 행렬 (§14)

열한 갈래 전부 `applied == ()` · `deltas == ()` · `state_hash()` 불변.

| 갈래 | status | code |
|---|---|---|
| 부적법한 대상 | `INVALID_TARGET` | `CANDIDATE_NOT_ELIGIBLE` |
| 모르는 대상 (상대 패) | `UNCHECKED_TARGET` | `HIDDEN_CARD` |
| 없는 카드 | `UNCHECKED_TARGET` | `HIDDEN_CARD` |
| 떠난 대상 (고른 뒤 이동) | `INVALID_TARGET` | `CANDIDATE_NOT_ELIGIBLE` |
| 못 하는 일 (`UNKNOWN`) | `UNSUPPORTED_OPERATION` | `RULE_NOT_IMPLEMENTED` |
| `TEXT_DERIVED` | `FORBIDDEN` | `RULE_NOT_IMPLEMENTED` |
| 구현 등록 없음 | `NOT_IMPLEMENTED` | `RULE_NOT_IMPLEMENTED` |
| 파괴 규칙 미상 | `UNCHECKED_RULES` | `RULE_NOT_IMPLEMENTED` |
| 소환 규칙 미상 | `UNCHECKED_RULES` | `RULE_NOT_IMPLEMENTED` |
| 출발 자리 어긋남 | `INVALID_TARGET` | `SOURCE_WRONG_ZONE` |
| 다른 효과의 문맥 | `INVALID_CONTEXT` | `EFFECT_REF_CARD_MISMATCH` |

**열한 갈래가 여덟 답으로 갈린다.** 겹치는 두 쌍은 겹치는 것이 맞다.

- **없는 카드 ≡ 모르는 대상** — 관측 경계 밖의 카드는 *없는 것*과 *안
  보이는 것*을 구분할 수 없다. 구분하면 숨은 정보가 샌다 (§16). 이것은
  결함이 아니라 `UNVERIFIED ≠ WRONG` 의 실행 시점 형태다.
- **떠난 대상 ≡ 부적법한 대상** — 자리를 떠난 카드는 더 이상 후보가
  아니다. 둘 다 "고른 것이 후보가 아니다" 라는 같은 사실이다.

나머지 아홉이 서로 다른 답이라는 것도 테스트가 고정한다
(`len(set(answers.values())) == 8`). 뭉개지면 깨진다.

### 앞의 일이 취소된다

여러 일 중 뒤의 것이 막히면 **앞의 것도 일어나지 않는다.** 계획이
**전부** 끝난 뒤에야 적용이 시작되기 때문이다 — 새 rollback 을 만들지
않았다 (ADR-008 그대로).

---

## 14. Determinism · Hidden information (§15 · §16)

| 보는 것 | 확인 |
|---|---|
| 같은 입력 → 같은 결과 | 여섯 갈래 전부 `canonical_state()` 동일 |
| 같은 입력 → 같은 판 | 여섯 갈래 전부 `state_hash()` 동일 |
| Event ID | 내용에서 나온다 — 두 판에서 같다 |
| 복제 독립성 | 복제본에서 실행해도 원본 불변 |
| 거절 결과 | 상대 카드의 `card_id` 를 담지 않는다 |
| 관측 경계 | 관측은 항상 **결정하는 자리**의 눈으로 만든다 (AST — `viewer=` 인자가 `*.controller` 뿐) |

---

## 15. 구현하지 않은 것 (§18 · §19)

이번 단계에서 **새로 만들지 않은 것**: `DrawEngine` · `LifePointEngine` ·
`DamageEngine` · `OperationRegistry` 를 대신하는 두 번째 실행기 · 새
`EventBus` · 새 `Chain` · 새 `TargetResolver` · 새 `SummonProcedure`.

여전히 표현할 수 없는 것: 전투 · 데미지 · 무효화 · 위치 지정 · 표시 형식
고르기 · 덱에서의 검색 · 소환 조건 판정 · 카드 조종권 이동 · 장착 · 카운터.
전부 `UNKNOWN` / `RULE_NOT_IMPLEMENTED` / `NOT_IMPLEMENTED` 로 남아 있다.

---

## 16. 새 TODO

- **STRUCTURAL-66 (신규)** — 실행 가능한 실제 카드가 쓰는 종류는 아직
  `{DRAW, CHANGE_LIFE, DESTROY}` 셋뿐이다. `MOVE` 는 설계상 실제 카드가
  될 수 없고, `SPECIAL_SUMMON` 은 STRUCTURAL-64 에 막혀 있다. 나머지
  여섯 가지 의미 있는 이동(`banish` · `release` · `discard` ·
  `return_to_hand` · `return_to_deck`)은 **synthetic 으로만** 검증되어
  있다 — 경로는 같지만 실제 카드로 지난 적은 없다.
- **STRUCTURAL-48 (계속)** — 보내기 · 버리기 · 되돌리기에는 관문이 없다.
  파괴와 특수 소환만 "해도 되는가" 를 묻는다.
- **STRUCTURAL-64 · 65 · 61 · 62 · 63 (계속)** — 소환 조건 계층 없음 ·
  대상 미지정 검색 없음 · 표시 형식 고르기 없음 · 소환법 이름 없음 ·
  출발 자리가 `{HAND, GRAVE}` 뿐.
- 15 · 34 · 41 · 45 ~ 60 — 변동 없음.

---

## 17. 기존 테스트 수정 (정직한 보고)

**삭제 0건. 수정 0건.** 기존 2222개가 손대지 않은 채로 전부 통과한다.

dispatch 를 표로 바꾼 것은 **행동을 바꾸지 않는 재구성**이었고, 그것이
기존 테스트가 하나도 깨지지 않았다는 사실로 확인된다. 새 테스트 80개는
전부 추가다.

---

## 18. 테스트

`tests/engine/test_operation_integration.py` — **80개**, 전부 통과.

| 묶음 | 수 | 보는 것 |
|---|---|---|
| A. Operation taxonomy | 5 | 표가 유일한 출처 · 종류와 부류가 1:1 · `UNKNOWN` 은 실행되지 않는다 |
| B. Dispatch | 5 | `isinstance` 사슬 없음 · 두 쪽이 같은 표 · 이동 여덟이 한 쌍 |
| C. 공통 실행 계약 | 24 | 여섯 갈래 × (성공 계약 · 기록 · event pipeline · journal) |
| D. DESTROY | 3 | 관문 유지 · 파괴로 기록 |
| E. MOVE | 5 | 세 경로 · 이유 주장 없음 · 파괴와 다름 |
| F. SPECIAL_SUMMON | 3 | 관문 유지 · 소환 사건 · 두 번째 실행기 없음 |
| G. DRAW / LP | 4 | 기존 primitive · 덱 부족 시 0장 · 새 엔진 없음 |
| H. 실제 카드 | 5 | 세 카드 · 세 경로 · MOVE/소환은 아직 없음 |
| I. 실패 행렬 | 2 | 열한 갈래 판 불변 · 앞선 일도 취소 |
| J. 결정론 · 정보 | 20 | 여섯 갈래 × (결정론 · event id · 복제) + 정체 유출 · 관측 경계 |
| K. 경계 | 4 | ADR-001 · 흐름 계층 미호출 · 중복 architecture 없음 · 스스로 고르지 않음 |

전체 회귀: **2302 passed, 4 skipped** (직전 2222 + 80).
