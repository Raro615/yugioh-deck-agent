# Phase 2-L — Operation Layer

기준 커밋: `09418bf` (Phase 2-K)

```
EffectDefinition
    ↓  operations
Operation                       무엇을 한다는 **의미**
    ↓  EffectExecutor._plan()   계획 — 판을 읽기만 한다
    ↓  EffectExecutor._apply()  여기서만 판이 바뀐다
GameState 변경  +  StateDelta
    ↓  EventReader              (2-J)
ObservedEvent → TimingEvent
```

---

## 1. 작업 전 검수 — 무엇이 이미 있었는가

| 이미 있던 것 | 상태 |
|---|---|
| `DrawOperation` → `state.draw()` → `CardDrawn` | **완성.** 덱 부족 사전 확인까지 |
| `LifeChangeOperation` → `player.change_life()` → `LifeChanged` | **완성.** 실제 변화량을 적는다 |
| `CardOperation` (`SEND_TO_GRAVE` · `BANISH` · `RELEASE` · `DISCARD` · `RETURN_TO_HAND` · `RETURN_TO_DECK`) → `state.move()` → `ZoneMoved` | **완성** |
| `DESTROY` | **일부러 없다** — 파괴 내성 · 대체 · 트리거가 없다 |
| `REASON_NAMES` · `DESTINATION` · `DESTINATION_OWNER` | 완성 |

§3 이 요구한 네 가지 이동은 **이미 전부 실행 가능했다.**

| 요구 | 이미 있던 길 |
|---|---|
| HAND → GRAVEYARD | `SEND_TO_GRAVE` · `DISCARD` |
| HAND → DECK | `RETURN_TO_DECK` |
| GRAVEYARD → HAND | `RETURN_TO_HAND` |
| FIELD → GRAVEYARD | `SEND_TO_GRAVE` · `RELEASE` |

없던 것은 **"목적지를 직접 말하는, 의미 없는 이동"** 하나였다. 그것만
만들었다.

---

## 2. `MoveOperation` — 의미가 **없다**는 것을 구조로 말한다

```python
MoveOperation(destination=Zone.GRAVE, target_ref=PRIMARY, to_owner=True)
```

| | 무엇을 말하는가 |
|---|---|
| `CardOperation` | **무슨 일인가.** 목적지는 그 의미가 정한다 (파괴 → 묘지) |
| `MoveOperation` | **어디로 가는가.** 무슨 일인지는 말하지 않는다 |

의미가 없다는 것을 네 가지로 못박았다.

1. **`REASON_NAMES[MOVE] == ()`** — `REASON_EFFECT` 조차 주장하지 않는다.
   여기에 이유를 적는 순간 트리거 계층이 이것을 "효과로 묘지에 갔다" 로
   읽는다.
2. **`CARD_OPERATION_KINDS` 에 없다** — 의미를 주장하는 조작들의 집합 밖이다.
3. **`DESTINATION_OWNER` 표에 없다** — `destination_player(MOVE, …)` 는
   `KeyError` 다. 의미가 없으므로 "이 일은 주인에게 간다" 는 규칙 자체가
   없고, 조작이 `to_owner` 로 직접 말한다.
4. **실제 카드의 효과가 될 수 없다** — `LibraryEntry.__post_init__` 이
   `executable=True` 인 정의에 `MOVE` 가 들어 있으면 거부한다.

네 번째가 핵심이다. `MOVE` 는 "쉬우니까 이걸로 「어리석은 매장」을 만들자"
가 **구조적으로 불가능**하다. 그것이 없으면 ADR-002 는 시간 문제로 무너진다.

갈 수 있는 곳은 `MOVABLE_DESTINATIONS` (`GRAVE` · `REMOVED` · `HAND` ·
`DECK`) 뿐이다. 전부 칸이 없는 순서 존이라 계획을 통과한 이동이 적용 중에
거부되지 않는다. **필드로는 옮기지 않는다** — 칸 선택과 표시 형식은 소환
절차의 일이다 (Phase 2-I).

그럼 `MOVE` 는 무엇에 쓰는가: 앞으로 생길 파괴 · 보내기 계층이 **공유할
바닥**이고, 의미 계층이 아직 없는 일을 정직하게 옮기는 자리다.

---

## 3. 실행기에 더한 것 — 세 줄

`executor.py` 의 변경은 최소다.

| 자리 | 변경 |
|---|---|
| `SUPPORTED` | `MOVE` 추가 |
| `_plan_operation` | `isinstance(operation, (CardOperation, MoveOperation))` |
| `_plan_card_operation` | 주인을 표가 아니라 `to_owner` 에서 읽는다 |
| `_apply` | 목적지를 표가 아니라 `operation.destination` 에서 읽는다 |
| `destination_player` | `MOVE` 를 받으면 **거부한다** (위 §2-3) |

계획-후-적용 · Delta 생성 · Journal 기록은 **하나도 바꾸지 않았다.**

---

## 4. 실제로 판을 바꾸는 코드 (코드 기준 확인)

| 일 | 변경 호출 | Delta |
|---|---|---|
| `DRAW` | `executor.py:578` `state.draw(step.player, step.amount)` | `CardDrawn` |
| `CHANGE_LIFE` | `executor.py:600` `player.change_life(step.amount)` | `LifeChanged` |
| `MOVE` · 의미 있는 이동 | `executor.py:618` `state.move(card, destination, to_player=…)` | `ZoneMoved` |

실측(테스트):
`HAND → GRAVE` 이동 뒤 `#0 P0/HAND → P0/GRAVE (move)`, `reason_names == ()`,
owner · controller · instance_id 그대로.

---

## 5. 실제 카드 — 은혜의 단비

```lua
-- c66719324.lua
function s.operation(e,tp,eg,ep,ev,re,r,rp)
    Duel.Recover(tp,1000,REASON_EFFECT)
    Duel.Recover(1-tp,1000,REASON_EFFECT)
end
```

조건도 비용도 대상도 없고 두 줄 다 상수다. →

```python
operations=(
    LifeChangeOperation(delta=1000, who=PlayerRef.CONTROLLER),
    LifeChangeOperation(delta=1000, who=PlayerRef.OPPONENT),
)
```

**두 개의 일로 적는다.** 한 줄로 합치면 "누가 얼마를 회복했는가" 가 뭉개지고,
나중에 한쪽만 막는 효과를 표현할 수 없다.

실측: 8000/8000 → 9000/9000, `LifeChanged` 두 개, 체인을 거쳐도 같다.

### `MOVE` 를 쓰는 실제 카드는 없다

§16 은 "실제 카드 효과 하나 이상이 새 Operation 을 사용" 하라고 했고,
`LifeChangeOperation` 이 그것이다. `MOVE` 를 쓰는 카드는 **일부러 없다** —
실제 카드의 이동은 전부 파괴 · 보내기 · 버리기 · 릴리스 · 제외 중
하나이고, 그것을 `MOVE` 로 적는 것이 바로 이 단계가 막으려는 일이다.

---

## 6. 실패 안전성

새 롤백 프레임워크를 만들지 않았다. 계획 단계가 **적용 전에** 전부 확인한다.

| 실패 | 확인 시점 | 결과 |
|---|---|---|
| 덱이 모자람 | 계획 | `INSUFFICIENT_CARDS`, 한 장도 안 뽑음 |
| 고른 카드 없음 | 계획 | `INVALID_TARGET` |
| 판에 없는 카드 | 계획 | `CANDIDATE_NOT_FOUND` |
| 갈 수 없는 존 | **생성 시점** | `MoveOperation` 이 만들어지지 않는다 |
| 출처 금지 | 권위 확인 | `FORBIDDEN` |
| 구현 없음 | 권위 확인 | 실행 안 함 |

**일 하나가 실패하면 나머지도 하지 않는다.** 라이프 변경 → 드로우(실패) →
이동 순서로 적어도 라이프가 먼저 깎이지 않는다 — 계획이 통째로 실패한다
(테스트로 확인).

---

## 7. 결정론 · 관측 경계

- 같은 판 + 같은 일들 → 같은 해시. 복제본에서 해도 원본은 그대로.
- 묘지는 순서 존이라 맨 뒤에 쌓인다. **자리를 고르지 않는다.**
- 변화 기록에 상대의 가려진 카드 정체가 들어가지 않는다.
- `operation.execute(state)` 를 만들지 않았다 — 일은 의미이고, 상태 조작은
  실행기 하나의 책임이다 (테스트가 `execute` · `apply` 속성이 없음을 확인).

---

## 8. 사건 통로

세 가지 일이 전부 2-J 의 통로로 들어간다.

```
DrawOperation      → CardDrawn   → TimingPoint.CARD_DRAWN
LifeChangeOperation→ LifeChanged → TimingPoint.LIFE_CHANGED
MoveOperation      → ZoneMoved   → TimingPoint.CARD_MOVED (operation=MOVE)
```

새 `EventKind` 도, 새 Delta 타입도, EventBus 도 만들지 않았다. `MOVE` 로
생긴 사건은 `reason_names` 가 비어 있어서 트리거 선언의 `operations` 필터에
걸리지 않는다 — **조용히 틀리는 대신 눈에 보이게 비어 있다.**

---

## 9. 구현하지 않은 것

§19 가 금지한 것 전부. 특히:

- 파괴 · 보내기 · 버리기 · 릴리스 · 제외 · 되돌리기의 **완전한 규칙**
- 데미지 처리 (효과 데미지 ≠ 효과로 라이프가 준다)
- 라이프 0 의 승패 처리
- 대상 선택 계층
- 롤백 · 전역 Event ID · 자동 체인

---

## 10. 새로 발견된 것

- **🟠 STRUCTURAL-45** — `MOVE` 로 생긴 사건은 어떤 트리거도 반응할 수 없다
  (`reason_names` 가 비어 있고 `TriggerSpec.operations` 필터가 걸러 낸다).
  의도한 성질이지만, 의미 계층이 생기기 전까지 `MOVE` 로 옮긴 카드는
  트리거 관점에서 **없던 일**이다. 실제 카드가 `MOVE` 를 쓸 수 없으므로
  지금은 해가 없다.
- Phase 2-K 의 DETAIL(출처 금지 시 `code` 가 `RULE_NOT_IMPLEMENTED`) 그대로.

---

## 11. 앞으로 만들면 좋은 것

1. **파괴 의미** — 내성 · 대체 · "파괴되었을 때". `MOVE` 가 그 바닥이 된다.
2. **대상 선택 계층** — 목록을 늘리는 데 가장 먼저 필요하다.
3. **데미지 처리** — "효과 데미지" 와 "라이프가 준다" 를 나누는 계층.
