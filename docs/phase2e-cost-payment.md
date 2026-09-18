# Phase 2-E — CostPayment

기준 커밋: `dc7489f` (Phase 2-D-3)

비용이 **처음으로 실제로 치러진다.** 지금까지 `engine/cost/` 는 청구서를
읽고 후보를 세기만 했다.

```
CostGroup + PaymentContext + GameState
    ↓  CostPayer.pay()
GameState 변경  +  CostPaymentResult(payments, deltas)
    ↓
EventJournal (COST_PAYMENT)
```

---

## 1. 작업 전 검수 결과

### 기존 Cost 구조

`engine/cost/model.py` — `CostSemantics` 7종 (`RELEASE` · `DISCARD` ·
`BANISH` · `SEND_TO_GRAVE` · `DETACH` · `PAY_LIFE` · `UNKNOWN`, **`DESTROY`
없음**) · `Cost` 기반 · `CardCost` · `LifeCost` · `UnimplementedCost` ·
`CostGroup` (AND). 전부 불변이고 **아무것도 치르지 않는다.**

### 기존 Selection 구조

`ChoiceSpec`(요구) → `CandidateResolver`(관측) → `CandidateSet`(eligible /
undecided / reasons) → `Selection`(결과) → `SelectionValidator`(검사).

### 기존 mutation primitive

`GameState.move` · `GameState.draw` · `PlayerState.change_life`. Phase 2-D-2
의 `EffectExecutor` 가 `DESTINATION` / `DESTINATION_OWNER` /
`destination_player()` 로 목적지와 주인을 정한다.

### 이미 있던 payment 구조

**없었다.** `CostPayment` 라는 이름은 문서와 주석에만 있었고 (`Cost ≠
CostPayment` 라는 구분으로), 구현은 어디에도 없었다. 그래서 새로 만들었다.

### 새 CostPayment 구조

| 파일 | 담는 것 |
|---|---|
| `engine/cost/receipt.py` | `CostPayment` — 영수증 (값 객체) |
| `engine/payment.py` | `CostPayer` · `CostPaymentResult` · `PaymentContext` · `CostSelection` · `PaymentStatus` |
| `engine/effect/journal.py` | `EventKind` · `JournalEvent` · `CostPaymentEvent` 추가 |

---

## 2. 청구서와 영수증

```
Cost          무엇을 내놓아야 하는가     청구서   engine/cost/model.py
CostPayment   실제로 무엇을 내놓았는가   영수증   engine/cost/receipt.py
```

`Cost` · `ChoiceSpec` · `Selection` 은 **어느 것도 판을 바꾸지 않는다.**
바꾸는 것은 `CostPayer` 하나뿐이고, 테스트가 그 부재를 직접 확인한다
(`test_a_cost_object_never_changes_the_board`).

비용 정의에 `InstanceId` 를 박지 않는다 — 박으면 그 정의는 한 판에서 한
번밖에 못 쓴다. 고른 카드는 `PaymentContext` 에 있다.

### 왜 `engine/cost/` 안이 아닌가

지불은 **변경**이고, 변경을 적으려면 `engine.effect.delta` 와
`engine.effect.journal` 이 필요하다. 그런데 `engine.effect` 는
`engine.cost` 를 이미 읽는다 (`TargetSpec` 이 `ChoiceSpec` 을 쓴다).
지불기를 `engine/cost/` 안에 넣으면 두 패키지가 서로를 읽게 되므로, 둘
**위에** 뒀다. `engine/validation.py` 를 따로 뺀 것과 같은 이유다.

영수증(`CostPayment`)은 값 객체일 뿐이라 `engine/cost/` 안에 남을 수 있고,
그래서 `journal.py` 가 그것을 읽을 수 있다.

---

## 3. 세 결과를 구분한다

| | 답하는 질문 |
|---|---|
| `ValidationResult` | 치를 수 **있는가** |
| `CostPaymentResult` | 실제로 **치렀는가** |
| `EffectResult` | 효과를 실제로 **해결했는가** |

합치지 않는다. 합치면 "낼 수 있다" 가 "냈다" 로 읽히는 길이 생긴다.
`CostPaymentResult.__bool__` 은 `TypeError` 를 던진다.

---

## 4. 지원하는 비용

| `CostSemantics` | 하는 일 | Delta |
|---|---|---|
| `DISCARD` | 패 → **주인의** 묘지 | `ZoneMoved(operation=DISCARD)` |
| `RELEASE` | 필드 → **주인의** 묘지 | `ZoneMoved(operation=RELEASE)` |
| `PAY_LIFE` | 라이프 감소 | `LifeChanged(before, after)` |

### 지원하지 않는 비용

`UNSUPPORTED_COST` 를 돌려주고 `missing` 에 무엇이 없는지 적는다. **지어내지
않는다.**

| | 이유 |
|---|---|
| `BANISH` | 비용으로서의 제외 (Phase 2-F~) |
| `SEND_TO_GRAVE` | 덱에서 보내는 경우 포함 |
| `DETACH` | 엑시즈 소재 모델이 없다 (Phase 3~) |
| `UnimplementedCost` | 표현되지 않은 비용 — `rule` 을 그대로 `missing` 에 |

**제물 바치기(TRIBUTE)** 는 소환 절차와 얽혀 있어 만들지 않았다. `CostSemantics`
에 `TRIBUTE` 를 새로 넣지도 않았다 — 소환이 없는데 이름만 만들면 모양을
미리 못박게 된다. 오늘 그것을 정직하게 표현하는 방법은
`UnimplementedCost("제물 바치기 (소환 절차)")` 이고, 테스트가 그 경로를
확인한다.

`CostSemantics.RELEASE` 는 지원한다. 그것은 **비용으로서의 릴리스**이고,
소환 절차의 제물과 다른 것이다.

---

## 5. CostGroup — AND 이므로 중간까지 내지 않는다

`CostGroup` 은 AND 관계다. 앞의 비용을 내고 뒤에서 막히면 **낸 것이 그냥
사라진다.** 되돌리기가 없으므로 (ADR-008), 되돌릴 일이 생기지 않도록 만든다.

```
1. preflight   묶음 전체 — 지원 여부 · 치를 수 있는가 · 고른 것이 맞는가 ·
               고른 카드가 실제로 그 자리에 있는가 · 카드마다 목적지의 주인
               (판을 읽기만 한다)
2. 지불        확정된 것을 순서대로
```

하나라도 걸리면 **아무것도 내지 않는다.** 두 방향을 모두 테스트가 고정한다.

- 버릴 수는 있지만 라이프가 모자람 → 카드도 그대로
- 라이프는 충분하지만 선택이 틀림 → 라이프도 그대로

### 선택은 자리 번호로 잇는다

```python
CostGroup((LifeCost(500), CardCost.discard(1)))
CostSelection(index=1, selection=Selection.of(card))   # 1번 비용에 붙는다
```

"고를 것이 있는 비용만 순서대로" 세는 방식을 쓰지 않는다 — 중간에 비용
하나가 끼거나 빠지면 선택이 조용히 다른 비용에 붙는다. 대상 계층이
`TargetRef` 라는 이름으로 잇는 것과 같은 이유다 (Phase 2-D-1 fix).

---

## 6. CostValidator 재사용

새 비용 규칙을 지불기 안에서 다시 구현하지 않았다.

```
CostValidator.validate(cost, ctx)          치를 수 있는가
SelectionValidator.validate(spec, sel)     고른 것이 맞는가
        ↓ 둘 다 VALID 일 때만
CostPayer._apply(...)                      실제로 치른다
```

`INVALID` → `CANNOT_PAY`, `UNKNOWN` → `UNKNOWN` 으로 코드·이유·notes 를
그대로 옮긴다. 지불기가 따로 판정하는 것은 **관측과 판이 어긋난 경우**의
마지막 방어뿐이다 (고른 카드가 실제로 그 존에 있는가).

---

## 7. UNKNOWN — "일단 지불" 로 바꾸지 않는다

| 판정 | 결과 | 판 |
|---|---|---|
| `VALID` | (통과) | 바뀐다 |
| `INVALID` | `CANNOT_PAY` | 그대로 |
| `UNKNOWN` | `UNKNOWN` | 그대로 |

`CANNOT_PAY` 와 `UNKNOWN` 을 **합치지 않는다.** "못 낸다" 와 "모르겠다" 는
다른 답이다.

검증은 `GameStateView.from_state(state, viewer=payer)` 로 한다. 관측을 통해
판을 고치지 않고, 상대의 가려진 카드를 비용으로 고르면 지불되지 않는다.

---

## 8. 주인 · 컨트롤러 · InstanceId

Hotfix 의 `destination = owner` 가 **비용 경로에도** 그대로 적용된다.
지불기는 실행기와 **같은 표**(`DESTINATION` · `destination_player`)를 쓰므로
비용과 효과가 목적지에서 갈릴 수 없다.

```
owner=P1, controller=P0 인 카드를 비용으로 릴리스:

ZoneMoved(operation=RELEASE, from_player=0, to_player=1)
→ P1 의 묘지. owner 는 바뀌지 않는다.
```

출발지는 **옮기기 전에** 읽고, 옮긴 뒤 카드가 그 자리에 있는지 확인한다.
아니면 `PaymentError` → `EXECUTION_ERROR`.

---

## 9. StateDelta · EventJournal

비용 지불도 Delta 를 만든다. **의미는 목적지로 뭉개지지 않는다.**

```
DISCARD  → ZoneMoved(operation=DISCARD,  reasons=("DISCARD","EFFECT"))
RELEASE  → ZoneMoved(operation=RELEASE,  reasons=("RELEASE",))
                     ↑ 둘 다 묘지로 가지만 서로 다른 사건이다
```

`EventKind` 가 기록에서 둘을 가른다.

```
EventKind.EFFECT        EffectEvent(applied=..., deltas=...)
EventKind.COST_PAYMENT  CostPaymentEvent(payments=..., deltas=...)
```

`EffectEvent` 를 그대로 쓰지 않았다 — 담는 것부터 다르다 (`applied` vs
`payments`). 하나의 타입에 두 payload 를 넣으면 읽는 쪽이 언제나 둘 다
확인해야 한다. 둘은 `JournalEvent` 를 공유하고 `sequence` 를 나눠 쓴다.
`journal.of_kind(EventKind.COST_PAYMENT)` 로 갈라 볼 수 있다.

`CostPaymentEvent.effect_ref` 는 **없을 수 있다.** 비용은 대개 어떤 효과의
발동 비용이지만 그 연결(ActionExecutor)은 아직 만들지 않았다. 모르는 것을
지어내지 않는다.

**실패한 지불은 기록하지 않는다.** 빈 묶음도 기록하지 않는다 — 바꾼 것이
없으면 역사도 없다.

---

## 10. EffectExecutor 와 잇지 않았다

```
Action → CostPayment → EffectExecutor      ← 이 파이프라인은 만들지 않았다
```

`CostPayer` 의 독립 실행만 구현했다. `EffectExecutor` 는 여전히
`ResolutionContext.cost_selections` 를 읽지 않는다 (STRUCTURAL-11 그대로).
연결은 `ActionExecutor` 가 생기는 다음 단계의 일이다.

---

## 11. 비용과 효과의 경계

```
"이 카드를 버리고 발동한다"        → CostPayment   / DISCARD
해결 중 "카드 1장을 묘지로 보낸다"  → Effect        / SEND_TO_GRAVE
```

문구가 비슷하다고 합치지 않는다. 합치면 "비용으로 버려졌을 때" 트리거를
영영 구분할 수 없다.

---

## 12. 만들지 않은 것

CostPayment 와 효과의 동시 처리 · ActionExecutor · Chain · Trigger ·
Timing · Priority · Summon · Battle · AI · rollback/transaction ·
replacement effects · once-per-turn 제약 · 덱에서 보내는 비용 ·
DISCARD RANDOM · 0 LP 승리 판정 · damage.

`change_life` 는 라이프를 깎을 뿐 승패를 판정하지 않는다 — 전부 지불해서
0 이 되어도 `state.result` 는 `None` 이다.

---

## 13. 테스트

`tests/engine/test_cost_payment.py` — 47개.

| 묶음 | 보는 것 |
|---|---|
| 단일 비용 | 버리기 · 선택 없음 · 빈 패 · 필드 카드 · 없는 카드 · 라이프 · 라이프 부족 · 전액 지불 · 릴리스 · 상대 카드 |
| CostGroup | 순서대로 지불 · **라이프 부족 시 카드도 그대로** · **선택 실패 시 라이프도 그대로** · 자리 번호 연결 · 빈 묶음 |
| State · Journal | 해시 변화 · `COST_PAYMENT` 로 기록 · 5가지 실패에서 판·기록 불변 · `bool()` 거부 · 실패 결과에 기록 못 붙임 |
| Identity | identity 보존 · **주인의 묘지** · 장수 보존 |
| Delta | `DISCARD` ≠ `SEND_TO_GRAVE` · `RELEASE` ≠ `SEND_TO_GRAVE` · before/after · 영수증 1 · 변화 N |
| UNKNOWN | 판정 불가 → 지불 없음 · 가려진 카드 → 지불 없음 · 정보 미유출 |
| Unsupported | 제물 · 제외 · 덱送り · 소재 제거 · 지원 집합 고정 |
| Determinism | 같은 입력 → 같은 결과·기록 · JSON 직렬화 · journal 선택적 |
| 경계 | 관측 거부 · `Cost` 는 판을 못 바꿈 · 정의에 `InstanceId` 없음 |

전체 회귀: **1210 passed, 4 skipped** (Phase 2-D-3 기준 1163 + 47).
기존 테스트는 하나도 삭제·수정하지 않았다.
