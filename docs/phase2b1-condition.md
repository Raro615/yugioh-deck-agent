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
 ├ 상태 술어 — GameStateView 만 읽는다
 │  ├ PhaseIs(phases)
 │  ├ IsTurnPlayer(who)
 │  ├ LifePointsAtLeast(who, amount)
 │  ├ ZoneCountAtLeast(who, zone, count)
 │  ├ ZoneHasFreeSlot(who, zone)
 │  ├ CardIsInZone(zone, who, instance?)
 │  └ CardIsFaceUp(instance?)
 │
 └ 카드 정의 술어 — CardView.definition 만 읽는다
    ├ IsMonster(instance?)
    ├ LevelAtLeast(level, instance?)
    ├ AttackAtLeast(amount, instance?)
    └ AttributeIs(attribute, instance?)
```

**유희왕의 모든 조건을 구현하려 하지 않았다.** 목표는 표현 · 평가 ·
`UNKNOWN` 전파의 기반이고, 술어는 그 기반이 실제로 동작하는지 보일 만큼만
만들었다.

### 카드 정의는 관측이 실어 준다 (STRUCTURAL-1 해결)

조건이 "레벨 4 이상인가" 를 물으려면 카드 정의가 필요하다. 그렇다고
`ConditionEvaluator` 가 `CardRepository` 를 들면 안 된다 — 저장소는
**전체 카드**를 알고 있으므로, 그것을 쥔 코드는 상대의 뒷면 카드도 조회할
수 있게 된다.

그래서 정의도 관측을 통해서만 온다.

```
Card (가변, 저장소 소유)
   ↓  CardDefinitionView.of(card)      값 복사. 참조를 들고 있지 않는다
CardDefinitionView (frozen)
   ↓  CardView.definition               정체가 공개된 카드에만 붙는다
Condition
```

`CardDefinitionView` 가 담는 것은 전부 `Card` 에 **실제로 있는** 값이거나
`Card` 가 이미 계산해 주는 파생값이다. 없는 값을 지어내지 않는다.

| 담는 것 | |
|---|---|
| 원본 마스크 | `type_mask` · `attribute_mask` · `race_mask` · `link_marker_mask` |
| 수치 | `level` · `atk` · `defense` · 펜듈럼 스케일 |
| 파생 | `is_monster` · `is_spell` · `is_trap` · `is_xyz` · `is_link` · `is_pendulum` · `is_extra_deck` |
| 파생 | `monster_level` · `rank` · `link_rating` · `attribute_name` · `race_name` · `type_names` · `setcodes` |

담지 않는 것: `script` · `provenance` · `sources` · `desc` · `strings`.
조건 평가에 필요 없고, 엔진 내부 구현을 관측에 묶는다.

#### 가려진 카드에는 정의가 붙지 않는다

```python
card = foe_view.find(set_card)
card.card_id     # None
card.definition  # None      ← 실어 주지 않는다
```

레벨 · 속성 · 공격력만 보고도 어느 카드인지 거의 특정할 수 있으므로,
`card_id` 를 숨기면서 정의를 실으면 숨기는 의미가 없다.

#### 세 가지 "모른다" 를 구분한다

전부 `UNKNOWN` 이지만 원인이 다르고, 이유 문자열이 이를 구분한다.

| 상황 | 이유 |
|---|---|
| 관측에 카드가 없다 | `... 가 관측에 보이지 않음 (가려진 존)` |
| 뒷면이라 정체를 모른다 | `... 는 뒷면이라 정체를 모름` |
| 저장소가 없어 정의를 못 읽는다 | `... 의 카드 정의를 조회할 수 없음 (저장소 없음)` |

#### 없는 값과 정해지지 않은 값

`cards.cdb` 는 두 가지 음수를 쓴다. **합치면 안 된다.**

| 값 | 뜻 | 조건의 답 |
|---|---|---|
| `STAT_NONE` (-1) | 수치가 **없다** (링크 몬스터의 수비력, 실측 499장) | `FALSE` — 없는 것은 확정된 사실 |
| `STAT_QUESTION` (-2) | **물음표** (실측 ATK 90장 · DEF 60장) | `UNKNOWN` — 값이 정해져 있지 않다 |

`?` 공격력은 **카드가 완전히 공개되어 있는데도** 모르는 경우다. 정보 은닉과
다른 종류의 `UNKNOWN` 이고, 필드 위의 실제 수치를 알려면 지속 효과 계층
(Phase 8)이 필요하다.

#### 마법 · 함정의 `atk` 는 읽지 않는다

`AttackAtLeast` 는 `is_monster` 를 **먼저** 본다. 값만 보면 안 되는 이유가
실측으로 있다.

```
마법 · 함정 4,967장이 atk 를 저장한다
  그중 4,919장은 0
  그런데 23장은 0 이 아니다   ← 버제스토마 레안코일리아(1200) 등
```

발동하면 몬스터가 되는 함정이 그때의 수치를 들고 있기 때문이다. 값만 보면
모든 마법 · 함정이 "공격력 0 이상" 으로 참이 되고, 함정 몬스터는 **함정인
채로** 공격력을 갖게 된다. (필드에서 실제로 몬스터가 되는 것은 규칙의
문제이고, 그 계층은 아직 없다.)

레벨은 같은 문제가 없다 — `Card.monster_level` 이 이미 비몬스터에 `None` 을
돌려준다. 그래서 랭크 4 엑시즈에 대해 `LevelAtLeast(4)` 는 `FALSE` 다.
**랭크는 레벨이 아니다.**

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

## 9. `ConditionEvaluator` 는 저장소를 들지 않는다

경계를 코드와 테스트 양쪽에서 고정했다.

- `engine/condition/` 은 `core` 를 **전혀** import 하지 않는다 (AST 검사)
- `engine/game_state_view.py` 도 런타임에 `core` 를 가져오지 않는다.
  `STAT_NONE` 을 다시 적어 두고, `core.constants.STAT_NONE` 과 어긋나지
  않는지 테스트가 지킨다
- `Card` 는 가변이고 전역 공유이므로 **값을 복사해서** 얼린다.
  관측을 만드는 것만으로 카드 정의가 바뀌지 않는지 테스트가 확인한다

---

## 10. 이번 단계에서 구현하지 않은 것

Action 실행 · `ActionValidator` 전체 · Effect · `EffectRegistry` · Chain ·
Trigger · 타이밍 · 소환 절차 · 릴리스 선택 · 공격 · 데미지 · 승패 판정 ·
`StateDelta` · `EventJournal` · `ActionGenerator` · AI · 카드별 조건 ·
`TEXT_DERIVED` 실행.

`ConditionEvaluator` 는 Action 을 실행하지 않고 `GameState` 를 받지도 않는다.
