# Phase 2-F-3-B — 최소 Trigger eligibility layer

기준 커밋: `9ba262b` (Phase 2-F-3-A)

```
TriggerCandidate                      (2-F-3-A: 타이밍 + 조건까지)
    ↓  TriggerEligibilityJudge.judge(candidate, spec, event)
TriggerEligibility                    관문별 판정 + 아직 보지 않은 규칙
    ↓  (다음 단계)
Action → CostPayment → ChainLink
```

---

## 1. 작업 전 검수 — 새 타입을 만들기 전에

| 기존 타입 | 이번 단계에 쓸 수 있는가 |
|---|---|
| `TriggerStatus` | **그대로 재사용.** ELIGIBLE/INELIGIBLE/UNKNOWN/FORBIDDEN 이 그대로 맞는다 (§2 요구) |
| `ValidationResult` / `ActionValidity` / `ValidationCode` | **그대로 재사용.** 관문 하나의 판정을 담는 데 정확히 맞는다 |
| `ConditionEvaluator` / `ConditionResult.all_of` | **그대로 재사용.** 새 조건 엔진을 만들지 않았다 |
| `execution_availability()` | **그대로 재사용.** 출처 금지 우선 순서까지 재사용 |
| `CostValidator` | **그대로 재사용.** "치를 수 있는가" 는 이미 있다 |
| `TimingPoint` / `TimingEvent` / `TriggerSpec` / `TriggerCandidate` / `TriggerCollection` | **그대로.** 수집 계층은 건드리지 않았다 |
| `PriorityState` / `ChainLink` / `EventJournal` / `StateDelta` | **쓰지 않는다.** 경계 유지가 이 단계의 요구다 |

**기존 타입으로 표현할 수 없던 것은 하나뿐이었다**: "여러 관문의 판정을
따로 들고 있으면서 하나의 상태로 접은 결과". 그것만 새로 만들었다.

새 `ValidationCode` 는 **1개**(`EXECUTION_FORBIDDEN`)만 추가했다. 나머지는
`SOURCE_WRONG_ZONE` · `HIDDEN_CARD` · `INFORMATION_UNAVAILABLE` ·
`INSUFFICIENT_LIFE` · `COST_NOT_IMPLEMENTED` · `RULE_NOT_IMPLEMENTED` · `OK`
로 전부 재사용했다.

---

## 2. 핵심 설계 — 관문을 따로 두고 합친다

하나의 불리언으로 뭉개면 "무엇 때문에 안 되는가" 가 사라지고, 앞으로 규칙이
들어올 자리도 없어진다. 그래서 관문마다 이름과 판정을 따로 둔다.

| `EligibilityGate` | 묻는 것 | 근거 |
|---|---|---|
| `EVENT_RELATION` | 이 사건에 반응하는가 | `TriggerSpec.matches` |
| `ACTIVATION_ZONE` | 지금 있는 자리에서 발동할 수 있는가 | `TriggerSpec.activates_from` (신규 필드) |
| `TRIGGER_CONDITION` | 조건이 참인가 | `ConditionEvaluator` |
| `EXECUTION_AUTHORITY` | 출처·구현이 허용하는가 | `execution_availability()` |
| `COST_FEASIBILITY` | 비용을 **치를 수 있는가** | `CostValidator` |

**하나가 막혀도 나머지를 계속 본다** — 무엇이 막혔는지 전부 알아야 다음
단계가 판단할 수 있다. 테스트가 "자리 관문이 막혔는데 비용 관문도 판정되어
있다" 를 확인한다.

### 접는 순서가 곧 원칙이다

```
1. 출처 금지가 하나라도 → FORBIDDEN   (다른 관문이 전부 통과해도, ADR-004)
2. 확실한 거부가 있으면 → INELIGIBLE
3. 판정 불가가 있으면   → UNKNOWN     (거부로도 통과로도 접지 않는다)
4. 전부 통과           → ELIGIBLE
```

`GateVerdict.passed` 는 **`VALID` 일 때만** 참이다 — `UNKNOWN` 이 통과로
새지 않는다.

---

## 3. §3 의 네 질문에 답한다

| 요구 | 어디서 답하는가 |
|---|---|
| 현재 이벤트가 어떤 timing point 인가 | `TimingEvent.point` (2-F-3-A) |
| 그 이벤트에 반응할 수 있는 trigger 인가 | `EVENT_RELATION` 관문 |
| 아직 판단할 정보가 부족한가 | `UNKNOWN` + 관문별 `notes` + `unchecked_rules` |
| 명백히 발동 불가능한가 | `INELIGIBLE` + `blocking` 관문 목록 |

---

## 4. `ELIGIBLE` 이 "규칙상 발동 가능" 이 아니다

`UNCHECKED_RULES` 가 **목록으로 남아 있는 것**이 이 단계의 정직한 상태다.

```python
UNCHECKED_RULES = (
    "timing window (놓친 타이밍 · 열린 타이밍)",
    "WHEN/IF 처리 규칙",
    "spell speed",
    "activation limit (턴 1회 · 카드명 제약)",
    "SEGOC 및 동시 트리거 순서",
    "chain 삽입 가능성 및 체인 상한",
)
```

모든 `TriggerEligibility` 가 이 목록을 그대로 실어 나르므로, `ELIGIBLE` 을
받은 쪽도 **무엇을 아직 안 봤는지** 알 수 있다. `fully_checked` 는 지금
언제나 거짓이고, 참이 되는 날 타이밍 계층이 완성된 것이다.

`may_activate` 의 docstring이 이것을 못박는다: "지금까지 본 관문을 전부
통과했다" 까지만 뜻한다.

---

## 5. 새 필드 하나 — `TriggerSpec.activates_from`

2-F-3-A 에서는 덱 맨 밑의 카드와 필드의 카드가 **똑같이** 후보가 되었다.
그것은 분명히 과하게 허용하는 것이었고, 데이터로 선언할 수 있는 종류의
사실이므로 필드로 넣었다.

```python
TriggerSpec(..., activates_from=frozenset({Zone.MZONE}))
```

`None` 이면 `ACTIVATION_ZONE` 관문이 **`UNKNOWN`** 이다 — 적지 않은 것을
"어디서든 발동 가능" 으로 읽지 않는다. 카드가 관측에 보이지 않으면
`UNKNOWN`(`HIDDEN_CARD`) 이고, **"보이지 않는다 = 없다 = FALSE" 로 처리하지
않는다.**

---

## 6. 강제/임의 · WHEN/IF

`TriggerRequirement`(MANDATORY/OPTIONAL/UNKNOWN) 와
`TriggerWording`(WHEN/IF/UNKNOWN) 는 `TriggerEligibility` 의 속성으로 **실려
나가되 판정에 끼어들지 않는다.** 네 조합(강제/임의 × 때/경우)이 모두 같은
판정을 내는지 테스트가 확인한다.

불리언 하나로 뭉개지 않았으므로 SEGOC 와 trigger ordering 이 나중에 쓸 수
있다. 그 정렬 규칙 자체는 만들지 않았고, 모듈에 `SEGOC` · `order_triggers` ·
`SpellSpeed` 가 없으며 `missed` 라는 단어도 없다.

---

## 7. 수집 상태와 판정 상태는 다를 수 있다

```
candidate.status      타이밍 + 조건까지 알아낸 것        (2-F-3-A)
eligibility.status    자리 · 권위 · 비용까지 합친 것     (2-F-3-B)
```

둘은 **다를 수 있고, 그 차이가 정보다.** 조건은 참이지만 구현이 등록되어
있지 않으면 `candidate.status == ELIGIBLE` 인데
`eligibility.status == UNKNOWN` 이다. 테스트가 이 차이를 직접 고정하고,
`TriggerCandidate.status` 의 docstring 에 "여기만 보고 발동할 수 있다고 읽지
말라" 를 적었다 (이번 단계에서 2-F-3-A 파일에 넣은 유일한 설명 변경).

---

## 8. 경계

| 하지 않는 것 | 확인 방법 |
|---|---|
| 비용 지불 | `CostPayer` 를 import 하지 않는다 (AST 검사). 비용 검증 전후 LP·`state_hash` 동일 |
| 체인 삽입 | `engine.chain` 미import. `Chain().push(eligibility)` · `push(candidate)` 둘 다 `TypeError` |
| 우선권 변경 | `engine.priority` 미import |
| `ChainResolver` · `PriorityResolver` · `EffectExecutor` 수정 | 파일 변경 0 |

판을 바꾸지 않는다: 판 · 기록 · 체인 · 우선권 · 라이프 · 모든
`CardInstance` 의 `(instance_id, zone, controller, owner)` 가 판정 전후
동일한지 한 테스트가 전부 확인한다.

---

## 9. 이번 단계에서 구현된 규칙

- 사건 관계 판정 (선언된 시점 · 이동 의미 · 존 필터)
- 발동 자리 판정 (선언된 경우에만)
- 조건 판정 (선언된 조건 + 정의의 `activation`, 삼치 논리)
- 실행 권위 판정 (`TEXT_DERIVED` 금지 · 구현 미등록 · 미검증)
- 비용 가능성 판정 (지불 없음)
- 위 다섯을 `FORBIDDEN > INELIGIBLE > UNKNOWN > ELIGIBLE` 로 접기

## 10. 의도적으로 미구현한 규칙

`UNCHECKED_RULES` 의 6개 — timing window · 놓친 타이밍 · WHEN/IF 처리 ·
spell speed · activation limit(턴 1회) · SEGOC/동시 트리거 순서 · 체인 삽입
가능성.

그리고: `Chain.push` 자동 호출 · 자동 트리거 체인 삽입 · ActionExecutor ·
Summon · Battle · Damage · Turn progression · 승패 판정 · AI ·
search/planning · 카드 데이터로부터의 트리거 자동 생성.

---

## 11. 테스트

`tests/engine/test_trigger_eligibility.py` — 34개.

| 묶음 | 보는 것 |
|---|---|
| 관문 분리·접기 | 5개 관문 모두 보고됨 · 막혀도 나머지 계속 판정 · `passed` 는 VALID 만 · **접는 순서 4단계** · 관문 중복 거부 |
| 상태 | ELIGIBLE · **ELIGIBLE ≠ 규칙 전부 확인** · 잘못된 자리 · 거짓 조건 · 판정 불가 조건 · **미선언 자리 → UNKNOWN** · `TEXT_DERIVED` → FORBIDDEN(다른 관문 통과에도) · 구현 미등록 → UNKNOWN · 미검증 → UNKNOWN · 정의 없음 → 3관문 UNKNOWN · 반응 안 하는 사건 |
| 비용 | 치를 수 있음(치르지 않음, LP·해시 불변) · 부족 → INELIGIBLE · 표현 불가 → UNKNOWN · **지불기 미import(AST)** |
| 강제/임의·WHEN/IF | 4조합이 같은 판정 · 실려 나감 · SEGOC/missed 밀반입 없음 |
| 가려진 정보 | 안 보이는 카드 → UNKNOWN(`HIDDEN_CARD`) · 못 읽는 정의 조건 → UNKNOWN · raw `GameState` 거부 · 후보/선언 불일치 거부 |
| Mutation safety | 판·기록·체인·우선권·LP·인스턴스 전부 불변 · 체인 접근 불가 · 불변 객체 · `clone()` 독립 |
| 결정론 | 같은 입력 → 같은 판정 · 평문 직렬화 · **`PYTHONHASHSEED` 3종 별도 프로세스** · **수집 상태 ≠ 판정 상태** |

전체 회귀: **1397 passed, 4 skipped** (2-F-3-A 기준 1363 + 34).

기존 테스트 **삭제 0건**, **수정 1건**: `test_triggers_pay_no_costs` 가
`"CostPayer" not in source` 라는 **문자열 검색**을 쓰고 있었는데, 이번에
설명문이 그 이름을 언급하게 되어(쓰지 않는다는 설명) 깨졌다. AST 로 실제
import 와 호출을 검사하도록 **강화**했다 — 약화가 아니다.
