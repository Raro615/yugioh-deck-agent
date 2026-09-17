# Phase 2-B-2 — ActionValidator

**기준 커밋:** `7e838c9` → 이 문서의 구현
**범위:** Action 을 **판정**한다. 실행하지 않는다.

```
GameState
    ↓  GameStateView.from_state(state, viewer)
GameStateView
    ↓  ActionValidator(view)
PlayerAction + ConditionContext
    ↓  validate()
ValidationResult(VALID | INVALID | UNKNOWN, code, reason)
    ✗  실행 없음 — Phase 2-C 이후
```

---

## 1. 검증기가 관측을 받게 되었다

Phase 2-A 의 `ActionValidator.validate(state, action)` 는 **`GameState` 를
직접 읽었다.** 그래서 이렇게 답할 수 있었다.

```python
validator.validate(state, PlayerAction.normal_summon(0, InstanceId(42)))
# → INVALID "source #42 가 이 듀얼에 없습니다."
```

이 답이 나오려면 **상대의 패와 덱을 들여다봐야 한다.** 그리고 그 답은
정보를 흘린다 — InstanceId 를 하나씩 넣어 보면서 INVALID 가 아닌 것을 찾으면
상대 손패의 크기와 위치를 알아낼 수 있다.

그래서 검증기도 `ConditionEvaluator` 와 똑같이 **관측만** 받는다.

```python
ActionValidator(GameStateView.from_state(state, viewer=0))
ActionValidator(state)   # TypeError
```

관측에 없는 카드는 **`UNKNOWN`** 이다. 이 듀얼에 없는 것인지 가려진 존에
있는 것인지 구분할 수 없기 때문이다. 확신이 줄었지만, 그 확신은 원래
훔쳐본 것이었다.

> 이것은 Phase 2-B-1 이 남긴 STRUCTURAL-2 와 같은 문제다. 여전히 해결하지
> 않았고, 여전히 `UNKNOWN` 으로 답한다.

---

## 2. 두 층

| 층 | 메서드 | 답 |
|---|---|---|
| 구조 | `validate_structure(action)` | `VALID` / `INVALID` |
| 구조 + 판 위의 사실 | `validate(action, context=None)` | `INVALID` / `UNKNOWN` |

`validate_structure` 는 **판을 보지 않는다.** 없는 카드를 가리켜도 모양은
올바르다.

**`validate` 는 아직 `VALID` 를 내지 않는다.** 소환 절차 · 타이밍 · 체인이
없어서 마지막 한 걸음을 확인할 수 없기 때문이다. 그래도 확실한 위반은
많이 잡는다.

---

## 3. ValidationResult

```python
ValidationResult(
    validity,      # VALID | INVALID | UNKNOWN
    code,          # ValidationCode — 기계가 분기할 안정적인 이유
    reason,        # 사람이 읽을 설명
    missing_rule,  # UNKNOWN 일 때 어느 규칙 계층이 없는가
    notes,         # 조건 계층이 전한 "왜 모르는가"
)
```

설명 문구를 다듬는다고 부르는 쪽이 깨지면 안 되므로 **코드와 문구를 나눴다.**

### UNKNOWN 은 허가가 아니다

```python
if result.validity is not ValidationCode.INVALID:  # ✗ UNKNOWN 이 샌다
if result:                                          # ✗ TypeError
if result.permits_execution:                        # ✓ VALID 에만 참
```

`ValidationResult.__bool__` 은 `ConditionResult` 와 같은 이유로 예외를 던진다.

---

## 4. 이유 코드

| 분류 | 코드 |
|---|---|
| 구조 | `ACTOR_INVALID` · `SOURCE_REQUIRED` · `SOURCE_FORBIDDEN` · `EFFECT_REF_REQUIRED` · `EFFECT_REF_FORBIDDEN` · `EFFECT_REF_CARD_MISMATCH` · `EFFECT_REF_OUT_OF_RANGE` · `PHASE_REQUIRED` · `PHASE_FORBIDDEN` · `TARGET_COUNT_MISMATCH` · `TARGET_KIND_INVALID` |
| 판 위의 사실 | `DUEL_ALREADY_OVER` · `NOT_TURN_PLAYER` · `SOURCE_NOT_CONTROLLED` · `SOURCE_WRONG_ZONE` · `SOURCE_WRONG_CARD_TYPE` · `ZONE_FULL` · `WRONG_PHASE` · `TARGET_NOT_OPPONENT` · `TARGET_SELF_CONTROLLED` · `TARGET_WRONG_ZONE` · `PHASE_UNCHANGED` |
| 모른다 | `HIDDEN_CARD` · `INFORMATION_UNAVAILABLE` · `CARD_DEFINITION_UNAVAILABLE` · `EFFECT_LIST_UNRELIABLE` · `RULE_NOT_IMPLEMENTED` |

"모른다" 가 다섯 가지인 이유는 원인이 실제로 다르기 때문이다. 부르는 쪽이
다음 단계를 정하려면 **가려져서 모르는 것**과 **규칙이 없어서 모르는 것**을
구분해야 한다.

---

## 5. 종류별 요구 목록

거대한 `if/elif` 를 만들지 않으려고 종류마다 작은 함수를 두고 표로 묶었다.
각 요구는 **조건 객체**다 — 검증기가 규칙을 다시 짜지 않고 Phase 2-B-1 의
조건 계층을 쓴다.

```python
Requirement(condition, code, detail)
```

| 종류 | 지금 판정하는 것 |
|---|---|
| `NORMAL_SUMMON` · `SET_MONSTER` | 턴 플레이어 · 자기 카드 · 패에 있음 · 몬스터임 · 몬스터 존에 빈 칸 |
| `SET_SPELL_TRAP` | 턴 플레이어 · 자기 카드 · 패에 있음 · 몬스터가 아님 · 마함 존에 빈 칸 |
| `CHANGE_POSITION` | 턴 플레이어 · 자기 카드 · 몬스터 존에 있음 |
| `ATTACK` | 턴 플레이어 · **배틀 페이즈** · 자기 몬스터 · 몬스터 존 · 대상이 자신이 아님 · 대상이 상대 몬스터 존 |
| `ACTIVATE_CARD` · `ACTIVATE_EFFECT` | 자기 카드 (**턴은 묻지 않는다**) |
| `CHANGE_PHASE` · `END_PHASE` | 턴 플레이어 · 같은 페이즈로의 이동이 아님 |
| `PASS` | 없음 — 우선권 계층이 없다 |

### 발동에 턴을 묻지 않는 이유

상대 턴에 발동하는 함정과 퀵 효과가 정상이다. `IsTurnPlayer` 를 걸면
그 전부가 `INVALID` 가 된다. 타이밍과 스펠 스피드는 Phase 2-F 의 몫이다.

### FALSE 가 UNKNOWN 을 이긴다

요구를 순서대로 판정하고, `FALSE` 가 하나라도 있으면 나머지를 몰라도
`INVALID` 다. 카드 정의를 못 읽어도 "남의 카드를 소환하려 한다" 는 확실하다.
순서가 고정이므로 결과도 결정론적이다.

---

## 6. EffectRef 검증

`CardDefinitionView` 에 `effect_count` 를 더했다. **스크립트 내용을 내보내지
않고 개수만** 싣는다.

```
ordinal >= effect_count  →  INVALID (EFFECT_REF_OUT_OF_RANGE)
effect_count == 0        →  UNKNOWN (EFFECT_LIST_UNRELIABLE)
```

0 을 `INVALID` 로 하지 않는 이유가 실측으로 있다. 통상 몬스터도 0 이지만,
공유 라이브러리 팩토리(`Fusion.CreateSummonEff` 등)로 효과를 만드는 카드
**195장**도 0 이다 (ADR-006). 둘을 구분할 수 없으므로 모른다고 답한다.

한편 `TEXT_DERIVED` 806장과 `NO_EFFECT` 746장도 `effect_count == 0` 이다.
그 카드들의 효과는 `EffectRef` 로 지목할 수 없고, 따라서 `ACTIVATE_EFFECT`
가 허가를 받는 일이 **구조적으로** 없다 (Contract A).

---

## 7. 아무것도 바꾸지 않는다

검증 전후로 다음이 전부 같다.

- `state.state_hash()`
- `state.allocator.next_value`
- `state.uses.canonical_state()`
- `state.turn.canonical_state()`
- 모든 존의 장수
- **모든 `CardInstance` 의 `canonical_state()`**

특히 "검증을 위해 미리 실행해보기" 가 없는지 확인한다 — 같은 Action 을
다섯 번 검증해도 소환 횟수나 효과 사용이 기록되지 않는다.

---

## 8. 정보 은닉

- 관측에 없는 카드 → `UNKNOWN(HIDDEN_CARD)`. 정체는 물론 존재 여부도 말하지 않는다
- 뒷면 카드 → 자리와 컨트롤러는 보이므로 "남의 카드" 판정은 된다. 정체는 새지 않는다
- 같은 Action 이라도 **보는 사람이 다르면 답이 다를 수 있다**

```python
action = PlayerAction.normal_summon(1, their_hand_card)
foe.validate(action).code    # HIDDEN_CARD      — 무슨 카드인지 모른다
owner.validate(action).code  # NOT_TURN_PLAYER  — 진짜 이유를 안다
```

---

## 9. 미구현 — 의도적으로 UNKNOWN 인 영역

| 영역 | `missing_rule` |
|---|---|
| 소환 절차 · 릴리스 · 소환권 · 소환 제한 | `summon-procedure (Phase 2-G)` |
| 세트 타이밍 | `set-timing (Phase 2-G)` |
| 발동 조건 · 코스트 · 타이밍 · 스펠 스피드 | `activation-timing (Phase 2-C/2-F)` |
| 표시 형식 변경 제한 (이번 턴 소환 · 1턴 1번) | `position-change-legality (Phase 2-G)` |
| 공격 선언 · 표시 형식 · 이미 공격함 | `attack-declaration (Phase 2-G)` |
| 페이즈 전이 규칙 · 배틀 페이즈 진입 | `turn-progression (Phase 2-G)` |
| 우선권 | `priority (Phase 2-F)` |
| 공유 라이브러리 효과 파싱 | `shared-library effect parsing (ADR-006)` |

그 밖에 이번 단계에서 구현하지 않은 것: Action 실행 · Effect · EffectRegistry ·
코스트 · 선택 · 체인 · 트리거 · 전투 계산 · 데미지 · 승패 판정 ·
`StateDelta` · `EventJournal` · `ActionGenerator` · AI.

---

## 10. 경계

```
analysis.ActionKind      ≠  engine.PlayerActionKind
analysis.ConditionNode   ≠  engine.Condition
Card Definition          ≠  Card Instance
PlayerAction             ≠  Effect
ActionValidator          ≠  ActionExecutor
ConditionEvaluator       ≠  EffectExecutor
```

`engine/action_validation.py` 는 `core` 도 `analysis` 도 가져오지 않는다.
AST 검사가 지킨다.
