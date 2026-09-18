# Phase 2-F-3-C — 체인 삽입 전 Trigger Ordering 최소 계층

기준 커밋: `07f8f3f` (Phase 2-F-3-B)

```
TriggerEligibility 여럿              (F-3-B 의 판정)
    ↓  TriggerOrderer(view).order(event, eligibilities)
TriggerOrdering
    ├ groups            컨트롤러별 묶음 (강제 / 임의 / 미확인)
    ├ unordered         UNKNOWN — 순서화 대상이 아니지만 버리지도 않는다
    ├ excluded          INELIGIBLE · FORBIDDEN
    └ unresolved_rules  아직 정할 수 없는 순서 규칙 5개
    ↓  (F-3-D)
ChainLink
```

---

## 1. 작업 전 검수

| 요청의 이름 | 실제 | 조치 |
|---|---|---|
| `TriggerPoint` | **없다.** 실제 타입은 `TimingPoint` | 별칭을 만들지 않고 실제 이름을 그대로 썼다 |
| `TimingEvent` · `TriggerSpec` · `TriggerCandidate` · `TriggerCollection` · `TriggerStatus` · `TriggerEligibility` · `EligibilityGate` | 전부 있다 | 그대로 재사용 |
| `GameStateView` | 있다 | 턴 플레이어를 읽는 **유일한** 출처로 사용 |
| `EventJournal` · `StateDelta` · `PriorityState` · `ChainLink` · `Chain` | 있다 | **쓰지 않는다** — 경계 유지가 이 단계의 요구다 |

기존 타입으로 표현할 수 없던 것은 **"판정 여럿을 컨트롤러별로 묶고, 강제/
임의를 나눠 담고, 아직 정할 수 없는 순서 규칙을 함께 실어 나르는 결과"**
하나뿐이었다. 그것만 만들었고 `ValidationCode` 는 **하나도 추가하지 않았다.**

`trigger.py` 가 이미 1,443줄이라 새 모듈 `engine/trigger_order.py` 로 나눴다
(`priority.py` · `chain.py` · `payment.py` 와 같은 선례).

---

## 2. 무엇이 순서화 대상인가

| 판정 | 어디로 | 왜 |
|---|---|---|
| `ELIGIBLE` | `groups` | 순서화 대상 |
| `UNKNOWN` | **`unordered`** | 승격도 제외도 하지 않는다 |
| `INELIGIBLE` | `excluded` | 확실히 빠진다 |
| `FORBIDDEN` | `excluded` | `TEXT_DERIVED` 가 실행 경로로 새지 않는다 |

**`UNKNOWN` 을 `excluded` 에 넣지 않는 것이 핵심이다.** 모르는 것을 "확실히
안 된다" 와 같은 통에 담으면 그 구분이 사라진다. 테스트가 세 통의 합이
입력과 정확히 같은 집합인지도 확인한다 — 조용히 사라지는 후보가 없다.

---

## 3. 새 구조

```python
PlayerRole            TURN_PLAYER / NON_TURN_PLAYER
OrderingBasis         CANONICAL   (is_rule_order 는 언제나 거짓)
TriggerGroup          controller · role · mandatory · optional · undetermined
TriggerOrdering       event · turn_player · basis · groups · unordered
                      · excluded · unresolved_rules
TriggerOrderer(view)  order(event, eligibilities) -> TriggerOrdering
UNRESOLVED_ORDER_RULES
```

전부 frozen dataclass 이고, 밖으로 나가는 것은 전부 tuple 이다.

---

## 4. Ordering 규칙 — 여기서 실제로 정한 것

1. **묶음은 컨트롤러별**로 나눈다. 한 묶음에 다른 사람의 트리거가 들어가면
   생성 단계에서 거부한다.
2. **묶음 순서는 자리 번호 순** (P0 → P1).
3. 각 묶음 안에서 **강제 · 임의 · 미확인을 따로** 담는다.
4. 각 통은 `TriggerCandidate.identity` 순으로 정렬한다 — 정수와 문자열뿐
   이라 `PYTHONHASHSEED` 에 영향받지 않는다.
5. 입력 순서는 결과에 **새어 나가지 않는다.**

### 순서가 규칙을 사칭하지 않는다

가장 조심한 곳이다. 실제 SEGOC 는 **턴 플레이어 묶음이 먼저**이고 강제/임의
에도 규칙이 있다. 그것을 지금 못박으면 틀린 채로 굳는다. 그래서

- 묶음을 **자리 번호 순**으로 낸다 (턴 플레이어 순이 **아니다**)
- 각 묶음이 `role` 로 턴 플레이어인지 알려주므로, SEGOC 가 들어오는 날
  **이 모듈을 고치지 않고** 재정렬만 하면 된다
- `canonical_sequence` 는 강제 → 임의 → 미확인으로 잇지만, docstring 과
  테스트가 그것이 **읽기 편하라고 정한 자리 순서**임을 못박는다
- `is_rule_ordered` 는 **언제나 거짓**이다

```python
UNRESOLVED_ORDER_RULES = (
    "SEGOC (동시 발동 트리거의 규칙상 순서)",
    "턴 플레이어 / 비턴 플레이어 묶음의 순서",
    "강제 트리거와 임의 트리거의 우선순위",
    "같은 플레이어의 여러 트리거를 그 사람이 고르는 순서",
    "trigger placement (체인 어느 자리에 놓이는가)",
)
```

모든 결과가 이 목록을 실어 나르므로, 순서를 받은 쪽도 **무엇이 아직 안
정해졌는지** 안다.

---

## 5. 컨트롤러 · 턴 플레이어 · 우선권

세 개념을 섞지 않는다.

| | 무엇 | 어디 |
|---|---|---|
| `candidate.controller` | 트리거를 가진 사람 | F-3-A |
| `ordering.turn_player` / `group.role` | 누구 턴인가 | 여기 (관측에서 읽음) |
| `PriorityHolder` | 누구 차례인가 | Phase 2-F-1, **읽지도 않는다** |

턴 플레이어가 P1 일 때 P0 묶음의 `role` 이 `NON_TURN_PLAYER` 인지, 그리고
묶음 순서는 여전히 P0 → P1 인지를 테스트가 함께 확인한다.

---

## 6. 의도적으로 미구현한 규칙

`UNRESOLVED_ORDER_RULES` 의 5개 전부, 그리고:

`Chain.push` / `Chain.activate` 자동 호출 · `ChainResolver.resolve` ·
`PriorityResolver` · 자동 체인 삽입 · ActionExecutor · 실제 카드 효과 실행 ·
Summon · Battle · Damage · Turn progression · AI decision/search.

모듈에 `sort_by_segoc` · `apply_segoc` · `SpellSpeed` · `place_on_chain` 이
없고 `missed` 라는 단어도 없다 (테스트가 확인).

---

## 7. Chain · Priority 와의 경계

`engine/trigger_order.py` 는 **`engine.chain` · `engine.priority` ·
`engine.payment` · `analysis` 를 import 하지 않는다** (AST 로 확인).

`Chain().push(...)` 에 `TriggerOrdering` · `TriggerEligibility` ·
`TriggerCandidate` 를 넣으면 셋 다 `TypeError` 다.

결과는 불변 값 객체 하나이고, `identities` · `group_for` ·
`canonical_sequence` 로 F-3-D 가 `ChainLink` 를 만들 수 있다.

---

## 8. Mutation safety

`TriggerOrderer` 는 `GameStateView` 만 받고 `GameState` 를 넘기면
`TypeError` 다. 한 테스트가 네 가지 판정 상태 전부와 4개 후보 묶음을 정리한
뒤 다음이 전부 그대로인지 확인한다.

- `state_hash()`
- `journal_hash()`
- `Chain.canonical_state()`
- 모든 `CardInstance` 의 `(instance_id, zone, controller, owner)`

---

## 9. 테스트

`tests/engine/test_trigger_order.py` — 30개.

| 묶음 | 보는 것 |
|---|---|
| 대상 선별 | ELIGIBLE 만 · INELIGIBLE 제외 · FORBIDDEN 제외 · **UNKNOWN 따로 보존** · 모든 후보가 정확히 한 통에 |
| 강제/임의 | 세 통 분리 · 불리언으로 안 뭉갬 · **"강제가 먼저" 를 주장하지 않음** |
| 컨트롤러/턴 | 둘이 다른 질문 · **묶음 순서는 자리 순(규칙 순 아님)** · 남의 트리거 거부 · 우선권 미접촉 |
| identity | 정리 후에도 보존 · **두 카드가 같은 `e1` 을 써도 충돌 없음** · 같은 카드 두 자리 |
| 결정론 | 입력 순서 무관(3가지 순서) · 통마다 정렬 · 같은 입력 같은 결과 · 평문 직렬화 · **`PYTHONHASHSEED` 3종 별도 프로세스** |
| SEGOC 경계 | 규칙 순서 사칭 안 함 · SEGOC 기계 밀반입 없음 |
| Mutation · 체인 | 판·기록·체인·인스턴스 불변 · **체인 접근 불가** · raw `GameState` 거부 · 불변 결과 · 다른 사건 판정 거부 · `clone()` 독립 |
| 통합 | **수집(F-3-A) → 판정(F-3-B) → 정리(F-3-C)** 를 실제로 흘려 확인 |

전체 회귀: **1427 passed, 4 skipped** (F-3-B 기준 1397 + 30).
기존 테스트는 **하나도 삭제·수정하지 않았다.**
