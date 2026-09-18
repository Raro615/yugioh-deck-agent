# Phase 2-F-3-A — Timing / Trigger 최소 구조와 후보 수집

기준 커밋: `11c8223` (Phase 2-F-2)

```
GameState 변화 (StateDelta · JournalEvent)
    ↓  TimingEvent.from_delta / from_journal_event / timing_events
TimingEvent            무슨 일이 일어났는가
    ↓  TriggerCollector(view, registry, definitions).collect(event)
TriggerCollection      후보들 + 확인하지 못한 곳
    ↓  (다음 단계)
Action → CostPayment → ChainLink
```

이 단계가 만드는 것은 **후보 수집**까지다.

---

## 1. 작업 전 검수 결과

| 읽은 것 | 확인한 사실 |
|---|---|
| `engine/effect/delta.py` | `ZoneMoved`(operation 포함) · `CardDrawn` · `LifeChanged` — 트리거 입력이 될 재료가 이미 있다 |
| `engine/effect/journal.py` | `EffectEvent` · `CostPaymentEvent`, `EventKind` 로 이미 갈려 있다 |
| `engine/condition/evaluator.py` | `ConditionEvaluator(view).evaluate() → ConditionVerdict(result, description, unknown_reasons)` |
| `engine/condition/result.py` | `all_of` · `logical_and` — 삼치 논리 접기가 이미 있다 |
| `engine/effect/definition.py` | `EffectDefinitionSource`(2-F-2) · `provenance.is_forbidden` |
| `engine/game_state_view.py` | 가려진 `CardView` 는 `card_id=None`, 가려진 `ZoneView` 는 `cards=()` + `concealed=True` + `size` |
| `engine/priority.py`, `engine/chain.py` | 서로를 모르고, 둘 다 판 밖에 산다 |

**트리거 구조는 없었다.** 조건 평가기 · Delta · Journal · 정의 등록소를
전부 그대로 재사용했고, `EventJournal` 은 **한 줄도 바꾸지 않았다.**

---

## 2. 핵심 설계 — 후보 발견과 체인에 넣기를 분리한다

`TriggerCandidate` 는 `ChainLink` 를 상속하지 않고, `Chain.push` 에 넣으면
`TypeError` 다. 사이에 Action 과 비용 지불이 있다.

```
TriggerCandidate → (Action) → CostPayer.pay() → ChainLink
        ↑                                           ↑
   여기까지가 이번 단계                        Phase 2-F-2
```

`engine/trigger.py` 는 `engine.priority` 도 `engine.chain` 도
`engine.payment` 도 **import 하지 않는다** (테스트가 소스를 읽어 확인).

---

## 3. `TimingPoint` — 지금 만들어 낼 수 있는 시점만

| | 어디서 오는가 |
|---|---|
| `CARD_MOVED` | `ZoneMoved` |
| `CARD_DRAWN` | `CardDrawn` |
| `LIFE_CHANGED` | `LifeChanged` |
| `EFFECT_RESOLVED` | `EffectEvent` |
| `COST_PAID` | `CostPaymentEvent` |
| `UNIMPLEMENTED` | 계층이 없는 것 — 이유를 반드시 적는다 |

### `SUMMONED` / `BATTLE_EVENT` 를 넣지 않았다

요청의 §4 는 예시로 들었지만, **소환 · 전투 계층이 아예 없다.** 어떤 경로로도
생길 수 없는 시점 이름을 지금 못박으면 그 계층이 들어올 때 실제 모양과
어긋난다. §4 가 허용한 대로 `UNIMPLEMENTED` 로 정직하게 남긴다.

```python
TimingEvent.unimplemented("일반 소환 (소환 계층 없음)", actor=0)
```

이유 없이 `UNIMPLEMENTED` 를 쓰면 `TriggerError` 다.

### Delta 를 다시 펼쳐 적지 않는다

`TimingEvent` 는 `delta` 를 **참조로** 들고 `instance` · `operation` ·
`from_zone` · `to_zone` 을 속성으로 꺼낸다. Delta 가 이미 "어느 카드가 ·
어디에서 · 어디로 · 무슨 의미로" 를 들고 있으므로 옮겨 적으면 두 곳이
어긋날 수 있다.

`timing_events(journal_event)` 는 **변화들 → 사건 자체** 순으로 낸다. 카드는
해결 중에 움직이고 해결 완료는 그 뒤다. 이 순서가 규칙이라고 주장하지 않는다.

---

## 4. `TriggerCandidate`

```python
TriggerCandidate(point, effect_ref, source, controller,
                 status, requirement, wording, code, reason, notes)
```

- `identity` = `(point, card_id, ordinal, source, controller)` — 정수·문자열뿐
- `EffectRef` 가 identity. `EffectSpec.index`("e1") 미사용
- `GameState` · `GameStateView` · `CardInstance` 를 담지 않는다 (테스트가 필드
  타입을 직접 확인)
- 비용도 체인 번호도 없다 — `payments` · `sequence` · `chain` 이 없다

### `TriggerStatus`

| | 뜻 |
|---|---|
| `ELIGIBLE` | 타이밍이 맞고 조건이 참 |
| `INELIGIBLE` | 조건이 **확실히** 거짓 |
| `UNKNOWN` | 판정할 수 없다 |
| `FORBIDDEN` | 출처가 실행을 금지한다 (ADR-004) |

`is_candidate` 는 **`ELIGIBLE` 일 때만 참**이다 —
`if status is not INELIGIBLE:` 같은 코드로 `UNKNOWN` / `FORBIDDEN` 이 허가로
새어 나가지 못한다.

> **`ELIGIBLE` 은 "발동할 수 있다" 가 아니다.** 스펠 스피드 · 타이밍 윈도우 ·
> 놓친 타이밍 · 턴 1회 제약 · 비용 · 발동 합법성은 하나도 보지 않았다.
> `reason` 에 "발동 합법성은 따로 판정해야 합니다" 가 들어 있고 테스트가 그
> 문구를 확인한다.

### 강제/임의 · WHEN/IF

`TriggerRequirement`(MANDATORY/OPTIONAL/UNKNOWN) 와
`TriggerWording`(WHEN/IF/UNKNOWN) 는 **담기만 한다.** 둘 다 `status` 를 바꾸지
않고, `missed` 라는 단어가 소스에 없다 — 타이밍 윈도우가 없으면 놓친 타이밍을
판정할 근거가 없다.

---

## 5. Condition 연결

새 조건 엔진을 만들지 않았다. `ConditionEvaluator` 를 그대로 쓴다.

```
spec.condition  +  definition.activation
        ↓  ConditionResult.all_of(...)
TRUE → ELIGIBLE / FALSE → INELIGIBLE / UNKNOWN → UNKNOWN
```

`spec.condition` 이 `None` 이어도 정의의 `activation` 이 있으면 그것을 본다 —
**적지 않은 조건을 참으로 치지 않기 위해서다.** `FALSE` 가 `UNKNOWN` 을 이기는
것은 조건 계층의 삼치 논리 그대로다.

정의를 찾을 수 없으면 `UNKNOWN` 이다 (`notes` 에 "정의 미등록"). "조건이
없으니 후보" 로 넘기지 않는다.

`ConditionVerdict.unknown_reasons` 가 `candidate.notes` 로 그대로 흐른다.

---

## 6. Priority / Chain / Cost 경계

| 경계 | 지키는 방법 |
|---|---|
| 우선권 | `engine.priority` 미import. `PriorityState` 에 `triggers`/`collect` 없음 |
| 체인 | `engine.chain` 미import. `Chain().push(candidate)` → `TypeError` |
| 비용 | `engine.payment` 미import. `CostPayer` 라는 이름이 소스에 없음 |

트리거가 우선권을 돌리지 않고, 우선권이 후보를 만들지 않는다.

### 순서는 결정론적이지만 규칙 순서가 아니다

후보는 `identity` 순으로 정렬된다 — **등록 순서에 의존하지 않기 위해서다.**
선언을 거꾸로 등록해도 같은 결과가 나오는지 테스트가 확인한다.

> 이것은 SEGOC 도 발동 순서도 아니다. 모듈에 `segoc` · `order_triggers` 같은
> 것이 없고, 실제 순서 규칙은 다음 단계의 몫이다.

---

## 7. 가려진 정보

**이 단계에서 가장 조심한 곳이다.** 상대의 패 · 덱 · 뒷면 카드에도 트리거가
있을 수 있다. 관측에 안 보인다고 "후보 없음" 이라 답하면 `UNKNOWN` 을
`FALSE` 로 접는 것이다 — Phase 2-E 에서 STRUCTURAL-15 로 기록한 바로 그 실수다.

그래서 `TriggerCollection` 이 두 가지를 따로 낸다.

```python
collection.candidates   # 확인한 결과
collection.unchecked    # ('P1 HAND 2장', 'P0 DECK 2장', 'P1 SZONE #7 뒷면', …)
collection.fully_checked  # False — 이 목록은 완전하지 않다
```

가려진 카드는 `card_id` 가 없어서 후보가 되지 않고, 그 카드의 `instance_id`
도 후보 목록에 나오지 않는다. 관측자를 바꾸면 보이는 것이 달라진다는 것도
테스트가 확인한다 (`viewer=0` 은 1장, `viewer=1` 은 2장).

자기 덱도 `unchecked` 에 들어간다 — 덱은 주인에게도 가려져 있고, 그것이 규칙
이다.

---

## 8. TEXT_DERIVED 경계

출처 금지가 **조건보다 먼저** 검사된다. 조건이 참이어도 `FORBIDDEN` 이고,
`INELIGIBLE` 과 합치지 않는다 — "조건이 거짓" 과 "이 근거로는 절대 실행하지
않는다" 는 전혀 다른 말이다 (ADR-004).

---

## 9. 구현하지 않은 것

SEGOC · trigger ordering · WHEN/IF 완전 규칙 · 강제/임의 완전 판정 ·
놓친 타이밍 · 데미지 스텝 타이밍 · 스펠 스피드 · 우선권 자동 전환 ·
트리거 자동 체인 삽입 · ActionExecutor · Summon · Battle · Damage ·
Turn progression · 승패 판정 · AI · search/planning ·
모든 카드의 트리거 자동 생성 (STRUCTURAL-7 · -21 그대로) ·
`TEXT_DERIVED` 실행 허용.

`priority.py` · `chain.py` · `payment.py` · `effect/` · `condition/` ·
`game_state.py` 는 **한 줄도 바꾸지 않았다.**

---

## 10. 테스트

`tests/engine/test_trigger.py` — 48개.

| 묶음 | 보는 것 |
|---|---|
| TimingPoint · TimingEvent | Delta 3종 매핑 · 목적지가 같아도 다른 사건 · Journal 사건 · **변화→해결 순서** · 비용 ≠ 효과 · **소환/전투를 지어내지 않음** · 모르는 Delta 거부 · 불변 |
| TriggerCandidate | 효과·인스턴스·컨트롤러 · `EffectRef` 사용 · identity 안정성 · 판/인스턴스 미보유 · 불변 |
| 상태 | ELIGIBLE · **ELIGIBLE ≠ 발동 가능** · INELIGIBLE · **UNKNOWN ≠ INELIGIBLE** · 허가 누출 차단 · FALSE > UNKNOWN · 강제/임의 · WHEN/IF |
| Condition | 평가기 재사용 · 정의의 activation · 정의 미등록 → UNKNOWN · 정의 못 읽음 → UNKNOWN |
| 수집 | 여러 후보 · 선언 필터 · 잘못된 필터 거부 · **등록 순서 무관** · 사건별 분리 · 미등록 |
| 가려진 정보 | **가려진 존 → unchecked** · 뒷면 카드 · 가려진 카드는 후보 안 됨 · 관측자별 차이 |
| TEXT_DERIVED | FORBIDDEN ≠ INELIGIBLE · LUA_VERIFIED 는 통과 |
| Mutation safety | 판·기록·체인·우선권·인스턴스 전부 불변 · raw `GameState` 거부 · 변경 수단 부재 · `clone()` 독립 · **후보가 ChainLink 가 되지 않음** · 우선권 무관 · 비용 무관 |
| 결정론 | 같은 입력 → 같은 후보 · 평문 직렬화(frozenset 정렬) · **`PYTHONHASHSEED` 3종 별도 프로세스** · **실제 실행기가 낸 Delta 로 연결** |

전체 회귀: **1363 passed, 4 skipped** (Phase 2-F-2 기준 1315 + 48).
