# Phase 2-B-1 — Condition System

**기준 커밋:** `8859cc7` → 이 문서의 구현
**범위:** 조건을 **표현하고 평가**한다. 조건에 따라 무엇을 하지는 않는다.

```
GameState
    ↓  GameStateView.from_state(state, viewer)   ← Phase 2-A, 읽기 전용 스냅숏
GameStateView
    ↓  ConditionEvaluator(view)
Condition + ConditionContext
    ↓  evaluate()
ConditionVerdict(TRUE | FALSE | UNKNOWN, 근거)
    ✗  실행 없음 — Phase 2-C 이후
```

---

## 1. 구현 전 확인한 것

| 확인 대상 | 결과 |
|---|---|
| `analysis` 에 조건 트리가 있는가 | **있다** — `ConditionNode` (AND/OR/NOT/LEAF) |
| 그것이 평가를 하는가 | **아니다.** `analysis` 전체에 평가기가 없다 |
| `engine` 에 조건이 있는가 | 없었다 |
| `engine` → `analysis` 의존 한도 | `LimitScope` **하나** (Contract H) |

### 재사용 판단

`analysis.ConditionNode` 를 **가져오지 않았다.** 목적과 모양이 둘 다 다르다.

| | `analysis.ConditionNode` | `engine.condition.Condition` |
|---|---|---|
| 정체 | **Lua 를 읽은 기록** | **실행용 조건** |
| 가변성 | 가변 (`@dataclass(slots=True)`) | 불변 (`frozen=True`) |
| 원문 | `raw` 에 Lua 원문 보존 | 없음 |
| 평가 | **없음** | `evaluate(view, context)` |
| 가지/잎 | 한 타입이 겸함 (`BoolOp.LEAF`) | 서로 다른 클래스 |

`BoolOp` 에 `LEAF` 멤버가 있는 것 자체가 그 타입이 기록용임을 보여준다 —
가지와 잎을 한 dataclass 가 겸하기 때문이다. 엔진에서는 `And` / `Or` / `Not`
과 술어가 각각 다른 클래스이므로 그 멤버가 필요 없다.

둘을 한 타입으로 합치면 **"스크립트에 무엇이라 적혀 있는가" 와 "지금 판에서
그것이 참인가" 가 섞인다.** 전자는 카드 데이터의 성질이고 후자는 듀얼 한 판의
성질이다.

Contract H (`engine` 은 `analysis` 에서 `LimitScope` 만 가져온다) 는
**그대로 유지된다.** 이번 작업에서 새 의존이 하나도 늘지 않았다.

> **Phase 2-B-2 의 할 일:** `ConditionNode` → `Condition` 컴파일러. 방향은
> 한쪽이다 — 분석이 실행을 낳지, 실행이 분석을 바꾸지 않는다.

---

## 2. ConditionResult

```
TRUE     현재 정보만으로 참이라고 확정할 수 있다
FALSE    현재 정보만으로 거짓이라고 확정할 수 있다
UNKNOWN  판정할 수 없다 — 거짓이 아니다
```

`UNKNOWN` 의 원인은 두 가지이고 둘 다 정당하다.

1. **정보가 가려져 있다** — 상대 패 · 덱 · 뒷면 카드
2. **판정할 규칙이 아직 없다** — 체인 · 트리거 · 타이밍 · 소환 절차

### 파이썬 진리값을 구조로 막았다

```python
if result:                  # TypeError
if result or fallback:      # TypeError
not result                  # TypeError

if result is ConditionResult.TRUE:   # 좋다
if result.is_true:                   # 좋다
```

`__bool__` 이 값을 돌려주지 않고 **예외를 던진다.** 그리고 `ConditionResult`
는 `str` 을 상속하지 **않는다** — 상속했다면 `bool(UNKNOWN)` 이 빈 문자열이
아니라서 **참**이 되고, "모른다" 가 조용히 "그렇다" 로 바뀐다.

`ConditionVerdict` 도 같은 이유로 `__bool__` 이 막혀 있다.

---

## 3. 삼치 논리

설계 문서 §8 의 표를 그대로 구현했다. 파이썬 `and` / `or` / `not` 을 쓰지
않고 `logical_and` / `logical_or` / `logical_not` 으로 명시한다.

| AND | TRUE | FALSE | UNKNOWN |
|---|---|---|---|
| **TRUE** | TRUE | FALSE | UNKNOWN |
| **FALSE** | FALSE | FALSE | **FALSE** |
| **UNKNOWN** | UNKNOWN | **FALSE** | UNKNOWN |

| OR | TRUE | FALSE | UNKNOWN |
|---|---|---|---|
| **TRUE** | TRUE | TRUE | **TRUE** |
| **FALSE** | TRUE | FALSE | UNKNOWN |
| **UNKNOWN** | **TRUE** | UNKNOWN | UNKNOWN |

| NOT | |
|---|---|
| TRUE | FALSE |
| FALSE | TRUE |
| UNKNOWN | **UNKNOWN** |

### 단락 평가가 UNKNOWN 을 구제한다

굵게 표시한 네 칸이 핵심이다.

- `FALSE AND UNKNOWN = FALSE` — 하나가 확실히 거짓이면 나머지를 몰라도 전체가 거짓
- `TRUE OR UNKNOWN = TRUE` — 하나가 확실히 참이면 마찬가지

이것이 없으면 조건 하나만 미해석이어도 트리 전체가 `UNKNOWN` 이 된다.
설계 문서가 "OR 노드가 1,413개" 라고 적어 둔 이유다.

`all_of` / `any_of` 는 **뒤를 보지 않는다.** 확정되는 순간 순회를 멈춘다.

### 빈 묶음

```
And(())  →  TRUE     조건이 없으면 막을 것이 없다
Or(())   →  FALSE    참인 선택지가 없다
```

---

## 4. Condition 구조

전부 **frozen dataclass** 다. 만든 뒤 고칠 수 없고, 고치려면 새로 만든다.

```
Condition
 ├ Always(value)                      상수. 테스트·자리표시
 ├ UnimplementedRule(rule)            언제나 UNKNOWN + 무엇이 없는지
 │
 ├ And(children)   Or(children)   Not(child)
 │
 └ 상태 술어 — GameStateView 만 읽는다
    ├ PhaseIs(phases)
    ├ IsTurnPlayer(who)
    ├ LifePointsAtLeast(who, amount)
    ├ ZoneCountAtLeast(who, zone, count)
    ├ ZoneHasFreeSlot(who, zone)
    ├ CardIsInZone(zone, who, instance?)
    └ CardIsFaceUp(instance?)
```

**유희왕의 모든 조건을 구현하려 하지 않았다.** 목표는 표현 · 평가 ·
`UNKNOWN` 전파의 기반이고, 술어는 그 기반이 실제로 동작하는지 보일 만큼만
만들었다.

### 술어가 이 정도인 이유

관측(`GameStateView`)은 **카드 정의를 노출하지 않는다.** `CardView` 에는
`card_id` 는 있지만 레벨 · 속성 · 종족 · ATK 는 없다 — 그것을 읽으려면
`CardRepository` 가 필요하고, Phase 2-A 는 일부러 그것을 관측에서 뺐다.

그래서 "레벨 4 이상 몬스터가 있는가" 같은 술어는 **지금 만들 수 없다.**
억지로 만들면 관측의 경계를 뚫거나 값을 지어내게 된다. 그 술어는 카드 정의
접근 방식을 정한 뒤에 만든다 (아래 🟠 STRUCTURAL-1).

---

## 5. ConditionContext

```python
ConditionContext(
    player,                  # 필수 — "자신" 이 누구인가
    source=None,             # 묻고 있는 카드
    effect_ref=None,         # 판정 중인 효과
    targets=(),              # 이미 정해진 대상들
)
```

전부 Phase 1 · 2-A 의 **안정적인 식별자**다 (`InstanceId`, `EffectRef`,
`int`). 파이썬 객체 참조는 담지 않는다 — 담으면 문맥이 특정 `GameState` 에
묶이고 직렬화도 replay 도 불가능해진다.

`PlayerRef` 는 **문맥 상대적**이다 (`CONTROLLER` / `OPPONENT`). 절대 번호를
조건에 적어 넣으면 같은 조건을 양쪽이 쓸 수 없다.

### 지금 담지 않는 것

체인 문맥 · 직전 이벤트 · 발동 이유. **아직 그 시스템이 없기 때문이다.**
자리만 만들어 두면 모양을 미리 못박게 되므로, 그런 정보가 필요한 조건은
`UnimplementedRule` 로 `UNKNOWN` 을 돌려준다.

### 문맥이 비어 있으면

예외도, 임의의 참/거짓도 아니다. **`UNKNOWN` 이다.**

```python
CardIsInZone(Zone.MZONE).evaluate(view, ConditionContext(player=0))
# → UNKNOWN, 이유: "문맥에 source 가 없어 어느 카드인지 알 수 없음"
```

---

## 6. GameStateView 경계

`ConditionEvaluator` 는 **`GameStateView` 만 받는다.** `GameState` 를 넘기면
`TypeError` 다 — 받으면 `move()` · `change_life()` 가 손에 닿고, 조건이 판을
바꿀 수 있게 된다.

세 겹으로 막았다.

1. **생성자 타입 검사** — `ConditionEvaluator(state)` 는 `TypeError`
2. **import 검사 (테스트)** — `engine/condition/` 이 `game_state` 를 가져오지 않는지 AST 로 확인
3. **관측 자체가 불변** — frozen dataclass + tuple 이라 만질 것이 없다

### 안 보인다 ≠ 없다

```python
hidden = state.player(1).hand[0].instance_id          # 상대 패
CardIsInZone(Zone.GRAVE, PlayerRef.OPPONENT, hidden)  # "묘지에 있는가?"
# viewer=0 →  UNKNOWN     (FALSE 가 아니다)
# viewer=1 →  FALSE       (패에 있는 것이 보인다)
```

상대 패에 있는 카드를 두고 "묘지에 없다" 고 단정할 수 없다. 관측에서 카드를
찾지 못하면 `UNKNOWN` 이다. **같은 조건이라도 보는 사람이 다르면 답이 다를
수 있다** — 정보 은닉이 조건 계층까지 이어진다는 뜻이다.

### 장수는 가려진 존에서도 확정된다

```python
view.opponent.hand.concealed   # True  — 내용은 모른다
view.opponent.hand.size        # 4     — 장수는 정확하다
ZoneCountAtLeast(PlayerRef.OPPONENT, Zone.HAND, 4)   # TRUE, UNKNOWN 아님
```

실제 대전에서도 상대 패의 장수는 보인다. 모르는 것은 *무엇이* 있는가이지
*몇 장*이 아니다.

---

## 7. 결정론

- 모든 조건이 `canonical_state()` 와 `to_dict()` 를 제공한다
- 값은 정수 · 문자열 · 불리언 · `None` 뿐이다 (테스트가 재귀적으로 확인)
- `id()` · 메모리 주소 · `repr` · `random` · 현재 시각에 의존하지 않는다
- 자식 순서를 **유지한다** — 평탄화하거나 정렬하지 않는다
- `PYTHONHASHSEED` 를 바꿔 다른 프로세스에서 돌려도 같은 값이다

Phase 2-A 의 `PlayerAction.canonical_state()` / `to_dict()` 와 같은 규약이다.

---

## 8. 상태를 바꾸지 않는다

평가 전후로 다음이 전부 같다.

- `state.state_hash()`
- `state.allocator.next_value`
- `len(state.uses)`
- `state.turn.canonical_state()`
- 모든 존의 장수

`UNKNOWN` 일 때 근거를 모으는 두 번째 순회도 함께 확인한다.

---

## 9. 이번 단계에서 구현하지 않은 것

Action 실행 · `ActionValidator` 전체 · Effect · `EffectRegistry` · Chain ·
Trigger · 타이밍 · 소환 절차 · 릴리스 선택 · 공격 · 데미지 · 승패 판정 ·
`StateDelta` · `EventJournal` · `ActionGenerator` · AI · 카드별 조건 ·
`TEXT_DERIVED` 실행.

`ConditionEvaluator` 는 Action 을 실행하지 않고 `GameState` 를 받지도 않는다.
