# Phase 2-AE — Effect Result & Computed Value Core

기준 커밋: `3a73be0` (Phase 2-AD) · 2678 passed / 4 skipped

```
Operation
  → OperationResult
      ├── outcome          규칙대로 되었는가   ← 이번에 생긴 칸
      └── affected_count   몇 장을 다뤘는가
  → ResultRef / OperationRequirement    **명시적으로** 가리킨다
  → 후속 Operation

DeclaredNumberSpec
  → DerivedNumberDomain    판에서 목록을 만든다  ← 이번에 생긴 것
  → NumberDomain
```

한 줄 목표: **성패와 처리량을 가르고, 판에서 만들어지는 값을 명시적으로
적되, 그것을 판과 혼동하지 않는다.**

STRUCTURAL-84 · 85 를 다룬다.

---

## 1. 변경 파일 (§31-2)

| 파일 | 변경 |
|---|---|
| `engine/execution.py` | `ValueOutcome`·`ResolvedValue` **이사**(이름 확장) · `OperationOutcome` · `ResultField.SUCCEEDED` · `OperationRequirement` · `QuantitySource` · `BoardQuantity` · `DerivedNumberDomain` · `ResolvedDomain` · `ExecutionValues.outcome_of` |
| `engine/effect/target.py` | `CountOutcome`·`ResolvedCount` 를 execution 계층에서 가져다 쓴다 |
| `engine/effect/definition.py` | `requirements` 필드 · `_check_requirements` · `requirements_for` |
| `engine/effect/executor.py` | `_check_requirements` · `_read_quantity` · 계산되는 도메인 · **0장도 성공** · `_Step.result` 가 성패를 낸다 |
| `tests/engine/test_operation_result.py` | **신규** — 34 함수 / 38 케이스 |
| `test_execution_context.py` 외 3개 | 단언 갱신 (§23) |
| `docs/phase2ae-operation-result.md` · `engine/__init__.py` | 문서 |

**새 모듈 0개.** 새 EventBus · RandomEngine · ReplayEngine · Expression
Engine · Lua interpreter 0개.

---

## 2. STRUCTURAL-84 조사 — 91곳이 무엇을 하는가 (§3 · §24)

조작의 반환값을 받아 **성공 여부처럼** 읽는 자리를 전부 세었다.

| 모양 | 건 | 예 |
|---|---:|---|
| A 나머지를 그만둔다 (`if ct==0 then return end`) | 27 | 11167052 · 13210191 · 14198496 |
| B 성공했을 때만 뒤를 한다 (`if ct~=0 then …`) | 39 | 10875327 · 16272453 · 16310544 |
| C 다른 조건과 함께 본다 (`if ct>0 and c:IsFaceup() …`) | 25 | 33282498 · 34022290 |

**셋 다 "장수를 성패로 읽는" 모양이다.** Lua 에서는 그것이 편하지만
규칙에서는 다른 질문이고, 그 둘을 가르는 것이 이 단계의 절반이다.

그리고 셋 다 **조건부 계속**이다 — 앞의 일은 남기고 뒤의 일만 뺀다.
이 실행기에는 그 "부분 적용" 이 없다. 그래서 **의존은 적을 수 있게
했지만 건너뛰지는 못한다** (§5 · STRUCTURAL-88).

---

## 3. 성패는 장수가 아니다 (§2 · §4 · §7)

`OperationResult` 에 칸이 하나 늘었다.

```python
OperationResult(operation_index=0, affected_count=0, outcome=SUCCEEDED)
```

네 경우를 §7 이 물었다. 이 엔진의 답은 이렇다.

| | 언제 일어나는가 |
|---|---|
| `SUCCEEDED` · count ≥ 1 | 드로우 1장 등, 주장한 규칙을 전부 본 일 |
| `SUCCEEDED` · count = 0 | **"최대 2장까지" 에서 0장을 골랐다** |
| `UNKNOWN` · count ≥ 1 | 묘지로 보냈지만 "막는 효과" 를 보지 못했다 |
| `FAILED` | **일어나지 않는다** (아래) |

### `affected_count == 0` 은 실패가 아니다 — 그리고 그것이 버그였다

`ChoiceSpec(minimum=0)` 은 Phase 2-N 부터 있었고, 대상 계층은 빈 선택을
**적법하다고 판정**한다 (`test_an_optional_target_accepts_nothing_at_all`).
그런데 실행기는 그것을 `TOO_FEW_SELECTED` 로 거절하고 있었다. 두 계층이
서로 다른 말을 하고 있었고, 실행기 쪽이 **0장을 실패로 읽고** 있었다.

이제 고른 장수가 0이어도 그 규칙이 0장을 허용하면 그대로 진행한다.
한 장 이상을 요구하는 규칙에서는 여전히 거절한다 — 판단 기준은 장수가
아니라 **규칙이 무엇을 요구했는가**다.

### `FAILED` 를 만들지 않았다

계획이 전부 끝난 뒤에야 적용이 시작되므로, **계획에서 막힌 조작은 결과를
남기지 않는다** — 효과 전체가 거절되고 아무 일도 일어나지 않기 때문이다.
"실패한 조작의 결과" 라는 것이 존재할 수 없다.

실패는 조작이 아니라 **효과 단위**의 사실이고 `ResolutionStatus` 가 이미
답한다 (§4 가 "새로운 SuccessResult 시스템을 만들지 말라" 고 한 그대로).
여기 `FAILED` 를 두면 언제나 거짓인 값이 생기고, 그것을 읽은 쪽은 규칙을
지켰다고 믿게 된다.

### Phase 2-AD 의 판단은 절반만 맞았다

2-AD 는 `SUCCEEDED` 칸을 **일부러 만들지 않았다.** "앞이 실패하면 뒤는
시작조차 하지 않으므로 성패는 언제나 참" 이라는 이유였다.

앞부분은 지금도 맞다. 틀린 것은 뒷부분이다 — **`UNKNOWN` 은 생긴다.**
규칙을 다 보지 못한 채 일어난 조작이 있고, 그 위에 다음 일을 쌓아도
되는지는 다른 질문이다. 그 테스트를 고친 이유를 §12 에 적었다.

### 성패는 어디서 오는가

**지어내지 않았다.** Phase 2-M 이 이미 의미별로 "보지 않은 규칙" 을 적어
두었고 (`UNCHECKED_SEMANTIC_RULES`), 그 표가 비어 있으면 `SUCCEEDED`,
비어 있지 않으면 `UNKNOWN` 이다.

```
DRAW · MOVE · CHANGE_LIFE · SHUFFLE          → SUCCEEDED (주장하는 의미가 없다)
SEND_TO_GRAVE · DISCARD · DESTROY · SPECIAL_SUMMON → UNKNOWN
```

**보수적으로 잡는다.** 미확인 규칙 중에는 성패와 무관한 것도 있지만
(예: "'파괴되었을 때' 유발 효과"), 그것을 갈라 읽으려면 규칙을 새로
판정해야 한다. 모르는 쪽으로 기울이는 것이 이 프로젝트의 기본값이다.

---

## 4. 성패를 가리키는 법 (§6)

성패는 **수가 아니다.** 그래서 장수를 묻는 자리에 쓸 수 없고, 전용
자리로만 가리킨다.

```python
EffectDefinition(
    operations=(destroy, draw),
    requirements=(OperationRequirement(1, ResultRef(0, SUCCEEDED)),),
)
```

- `OperationResult.value_of(SUCCEEDED)` 는 **거부한다** (`KeyError`).
- `OperationRequirement` 는 `AFFECTED_COUNT` 를 **거부한다** — "수를
  조건처럼 읽는 것" 이 바로 이 단계가 막으려는 일이다.
- 가리켜지는 조작은 **반드시 앞**이어야 한다 (정의를 만들 때 검사).
  Phase 2-AD 가 수에 대해 세운 규칙과 같다.

조건을 조작이 아니라 **정의**가 들고 있는 이유: 이것은 조작이 *하는
일*이 아니라 조작들 **사이의 순서 관계**다. 조작에 붙이면 같은 조작을
다른 정의에서 다시 쓸 때 남의 번호를 들고 다니게 된다.

### 앞이 `UNKNOWN` 이면 전체를 거절한다

건너뛰지 않는다. 부분 적용이 없기 때문이고, 무엇보다 **모르는 것 위에
다음 일을 쌓지 않기** 때문이다 (`UNKNOWN` 은 허가가 아니다).

```
1번 조작은 0번 조작이 규칙대로 되었어야 하는데, 그 조작이 주장한 규칙을
다 보지 못했습니다. 모르는 것 위에 다음 일을 쌓지 않습니다.
```

그래서 "묘지로 보낸 뒤 뽑는다" 는 지금 **거절된다**. 카드는 움직일 수
있었지만 그것이 규칙대로였는지 모르는 채로 다음 일을 하지 않는다. 이것이
지금 이 엔진의 정직한 상태다.

---

## 5. STRUCTURAL-85 조사 — `table.unpack` 46건 (§13 · §24)

`Duel.AnnounceNumber` 호출 60건의 **도메인이 어디서 오는가**를 세었다.

| 도메인의 출처 | 건 | 지금 |
|---|---:|---|
| A 리터럴 목록 (`1,2,3`) | 13 | **이미 됐다** (2-AD) |
| G 리터럴 범위를 `for` 로 만든 것 | 2 | **이미 됐다** — `table.unpack` 이지만 상수다 |
| F 산술 (`t[i]=i*1000`, 라이프의 배수) | 9 | **이번에 된다** |
| C 값마다 규칙 판정이 필요 (`IsPlayerCanDiscardDeckAsCost(tp,i)`) | 24 | UNKNOWN |
| D 앞선 결과의 값 목록 (주사위 눈) | 2 | 범위 밖 |
| E 그 밖 | 10 | 범위 밖 |

**`table.unpack` 이 있다고 모두 계산 문제가 아니다** (§13 의 경고).
식스 센스(3280747)의 `for i=1,6 do t[i]=i end` 은 상수 목록이고, 2-AD 의
`NumberDomain` 으로 이미 적을 수 있었다. 46건 중 **2건이 그런 경우**였다.

---

## 6. 만든 것 — `DerivedNumberDomain` (§8 · §9 · §12)

모양은 **하나**다. `step` 의 배수를 `bound` 를 넘지 않을 때까지.

```python
# 광명의 벽 17078030 — for i=1,math.floor(lp/1000) do t[i]=i*1000 end
DerivedNumberDomain(BoardQuantity(LIFE_POINTS), step=1000)
    → {1000, 2000, …}

# 상대 패 장수까지
DerivedNumberDomain(BoardQuantity(ZONE_COUNT, OPPONENT, HAND))
    → {1, 2, 3, 4}
```

`BoardQuantity` 가 읽는 것은 둘뿐이다 — **자리 장수**와 **라이프**.
실제 카드가 목록을 만들 때 쓰는 것이 이 둘이기 때문이고, 더 필요해지면
그때 근거를 들고 온다. **수식 언어가 아니다.**

### §12 의 물음 — 도메인과 계산값은 같은 개념인가

**다른 개념이고, 한 곳에서 만난다.**

```
도메인   고를 수 있는 수들의 목록     ← 사람이 그중 하나를 고른다
계산값   수 하나                  ← 그 목록의 **끝**이 계산값이다
```

그래서 `NumberDomain` 을 모든 계산에 재사용하지 않았고, `SelectionCount`
를 도메인으로 쓰지도 않았다. `DerivedNumberDomain` 은 `NumberDomain` 과
**다른 타입**이다 — 합치면 "목록이 적혀 있는데 비어 있다" 와 "아직 안
만들었다" 가 같은 값이 된다.

### 값의 출처 다섯 (§10)

**이미 다 있었다.** `SelectionCount` 가 그것이다.

| 출처 | 어디 | 언제 |
|---|---|---|
| 상수 | `SelectionCount.fixed` | 2-AC |
| 판에서 (자리 장수의 덧셈·뺄셈) | `SelectionCount.derived` | 2-AC |
| 선언한 수 | `SelectionCount.from_declaration` | 2-AD |
| 앞선 결과 | `SelectionCount.from_result` | 2-AD |
| 모름 | `SelectionCount.unknown` | 2-AC |

그래서 **새 Value 시스템을 만들지 않았다** (§10 이 먼저 확인하라고 한
것). 이번에 더한 것은 이 다섯을 쓰는 **자리 하나**(도메인의 끝)와, 판에서
읽는 양에 **라이프**가 더해진 것뿐이다.

### 값을 물어본 결과 (§11)

`CountOutcome` / `ResolvedCount` 를 `ValueOutcome` / `ResolvedValue` 로
**이름을 넓혀 execution 계층으로 옮겼다.** 2-AC 에서 태어날 때는 답하는
것이 "고를 장수" 뿐이었는데, 지금은 드로우 매수도 도메인도 같은 어휘로
답한다. 어휘를 하나 더 만들지 않기 위한 이동이다 (§11 이 "기존 vocabulary
를 재사용하라" 고 한 것).

```
RESOLVED   값이 있다
UNKNOWN    계산할 수 없다        ← 0 으로 바꾸지 않는다
INVALID    계산식이나 결과가 규칙상 틀렸다
```

`FORBIDDEN` 은 **여기 없다.** 출처 금지는 값의 문제가 아니라 효과의
문제이고 `ResolutionStatus.FORBIDDEN` 이 한 계층 위에서 답한다 (2-AC ·
2-AD 와 같은 결론).

빈 목록을 만들지 않는다 — 고를 것이 하나도 없으면 그것은 선언이 아니라
**조건**이고, 조건은 발동 단계가 답할 일이다 (`INVALID`).

---

## 7. 경계 (§14 · §16 · §17 · §18 · §19 · §20)

| 경계 | 어떻게 지키는가 |
|---|---|
| 실행값 ≠ 판 | `engine/execution.py` 가 `GameState` 를 import 하지도 이름을 쓰지도 않는다 (AST) |
| 선택 ≠ 값 | 선언은 문맥으로 들어오고, 값 계층은 **이름으로 읽을 뿐** 고르지 않는다 |
| 무작위 ≠ 값 계산 | `randomness.py` 에 `SelectionCount`·`BoardQuantity`·`OperationResult` 라는 이름이 없다 (AST) |
| 값 계산 ≠ 난수 소비 | 도메인을 만들어도 `draws` 가 늘지 않는다 |
| 결과 ≠ 사건 | 저널에 `outcome`·`affected_count` 가 적히지 않는다 |
| 장수 ≠ 정체 | 상대 패의 **장수**로 도메인을 만들어도 그 패는 가려져 있다 |

**복제 독립**은 따로 지킬 것이 없다 — 실행값은 판에 붙어 있지 않고
`execute()` 한 번 안에서만 산다 (2-AD 와 같다).

**`state_hash` 는 한 줄도 바꾸지 않았다.** 값을 만들어도, 성패를
기록해도 해시가 움직이지 않는다. 실제로 카드가 움직였을 때만 움직인다.

---

## 8. 실패 안전성 (§21)

| 어디서 막혔나 | 판 | 난수 |
|---|---|---|
| 도메인을 만들 수 없다 (`UNKNOWN`) | 그대로 | 꺼내지 않았다 |
| 도메인이 비었다 (`INVALID`) | 그대로 | 꺼내지 않았다 |
| 선언이 `PENDING` · `INVALID` | 그대로 | 꺼내지 않았다 |
| 앞선 결과가 없다 · 수가 아니다 | 그대로 | 꺼내지 않았다 |
| 앞선 조작의 성패가 `UNKNOWN` | 그대로 | **앞의 일을 계획하며 꺼냈다** |
| 값이 `UNKNOWN` 인 조작이 뒤에 있다 | 그대로 | 앞에서 꺼낸 만큼 |

마지막 두 줄은 Phase 2-AB 부터의 사실이다 — 계획 중에 꺼낸 난수는
감추지 않고, 같은 seed 면 같은 자리에서 같은 답이 나오므로 재현은
깨지지 않는다.

---

## 9. 실제 카드 (§25)

**0장 등재했다.** 세 종류를 모두 찾아보고, 모두 다른 계층에서 막혔다.

| 요구 | 가장 가까운 카드 | 막히는 곳 |
|---|---|---|
| 성공 여부 사용 | 91곳 (10875327 등) | **부분 적용이 없다** — 건너뛸 수 없다 |
| 계산값 사용 | 광명의 벽 17078030 | 지불한 값을 지속 효과로 기억하는 계층이 없다 |
| 앞선 결과 참조 | 부작용? 30922149 (2-AD) | 라이프 증감의 양이 고정 수뿐 |

세 모양 전부를 **테스트에 적어 두었다.** 적을 수 있다는 것과 실행할 수
있다는 것은 다른 말이고, 그 둘을 섞지 않는다.

---

## 10. 테스트 (§28)

`tests/engine/test_operation_result.py` — **34 함수 / 38 케이스**, 전부 통과.

| 절 | 무엇을 붙잡는가 |
|---|---|
| A · B · C | 규칙을 다 본 일은 성공 · **0장도 성공** · 한 장 이상을 요구하면 여전히 거절 · 실패한 조작은 결과를 안 남긴다 · 장수를 성패로 읽는 코드가 없다 (AST) |
| D · E | 규칙을 못 본 일은 `UNKNOWN` · 성패를 명시적으로 가리킨다 · `UNKNOWN` 이면 전체 거절 · 성패는 수가 아니다 |
| F · G | 장수 참조 · **0도 수다** (0장 드로우는 거절) · 앞만 가리킨다 · 없는 결과는 `UNKNOWN` |
| H ~ L | 다섯 출처가 모두 적힌다 · 판에서 도메인을 만든다 · 만든 도메인이 실제로 선언을 묶는다 · 못 만들면 `UNKNOWN` · 빈 목록은 `INVALID` |
| M · N · O | 선택은 값이 되지만 값 계층이 고르지는 않는다 · 무작위가 고른 장수가 이어진다 · 난수원은 계산하지 않는다 (AST) · 값 계산에 난수 0 |
| P ~ T | 복제 독립 · 값 실패에도 판 그대로 · 장수를 읽어도 패는 안 열린다 · 저널엔 변화만 · 0장은 사건도 안 남긴다 · 해시 그대로 |
| U | 성공 확인 카드 · 광명의 벽 · 식스 센스의 **모양만** 적히고 카드는 등재되지 않았다 |

---

## 11. 회귀

```
2716 passed, 4 skipped in 37.70s     (기준선 2678 + 38)
```

---

## 12. 기존 테스트 수정 (§26 · §31-23)

**삭제 0건.** 수정 4건이고, 셋은 이름 이동, 하나는 **가정이 바뀐 것**이다.

1. `test_execution_context.py::test_i_there_is_no_succeeded_field_on_purpose`
   → `test_i_a_failed_operation_still_leaves_no_result`.
   기존 가정은 "성패 칸이 필요 없다 — 언제나 참이니까" 였고, 그 근거의
   앞부분("실패한 조작은 결과를 안 남긴다")은 **지금도 맞다.** 틀린 것은
   뒷부분이다 — `UNKNOWN` 이 생긴다. 그래서 여전히 참인 것을 단언하도록
   바꿨다: `FAILED` 가 없다는 것과, 실패한 조작이 결과를 남기지 않는다는
   것. **단언이 하나 늘었다.**
2~4. `test_selection_count.py` · `test_execution_context.py` ·
   `test_effect_model.py` 의 `CountOutcome`/`ResolvedCount` 이름을
   `ValueOutcome`/`ResolvedValue` 로 맞췄다. 검사 내용은 그대로다.

---

## 13. TODO (§31-24)

- **STRUCTURAL-84 — 해결(성패와 장수 분리).** 성패가 따로 있고, 0장을
  실패로 읽지 않으며, 의존을 명시적으로 적는다. 다만 **건너뛰기는 못
  한다** — 아래 88 이 그것이다.
- **STRUCTURAL-85 — 부분 해결.** 도메인 60건 중 15건은 이미 됐고 9건이
  이번에 됐다. 24건은 **값마다 규칙 판정**이 필요해서 `UNKNOWN` 이다
  (아래 89).
- **STRUCTURAL-88 (신규 · 🟠)** — **부분 적용이 없다.** "앞은 남기고 뒤만
  빼는" 조건부 계속을 표현할 수 없다. 실제 카드 91곳이 그 모양이고,
  이것 없이는 성공 여부를 쓰는 카드를 등재할 수 없다. 어느 쪽이 옳은지는
  규칙 문제이므로 공식 근거 없이 정하지 않는다.
- **STRUCTURAL-89 (신규 · 🟠)** — **값마다 규칙을 판정하는 도메인이
  없다.** `for i=1,#g do if <조건(i)> then insert end` 모양 24건.
  조건 계층이 "수 i 에 대해" 답할 수 있어야 한다.
- **STRUCTURAL-90 (신규 · 🟢)** — `SelectionCount` 라는 이름이 이제
  좁다. 고를 장수만이 아니라 드로우 매수와 도메인의 끝까지 답한다.
  **이번에 바꾸지 않았다** — 65곳을 건드리는 순수한 이름 변경이고,
  동작이 달라지지 않으므로 별도로 다루는 편이 안전하다.
- **STRUCTURAL-83 · 86 · 87 — 그대로 둔다** (§27 의 지시).
- 71 · 74 · 75 · 76 · 77 · 78 — **하나도 건드리지 않았다.**

---

## 14. 판정 (§30)

| 등급 | 건수 | 내용 |
|---|---:|---|
| 🔴 BLOCKER | **0** | |
| 🟠 STRUCTURAL | 2 신규 | 88 (부분 적용) · 89 (값마다 판정하는 도메인) |
| 🟡 DETAIL | 0 신규 | |
| 🟢 COSMETIC | 1 신규 | 90 (`SelectionCount` 이름) |

§30 이 허용하지 않는다고 한 아홉 가지 — `affected_count == 0` 을 실패로
읽기, 성패를 장수로 추론, `UNKNOWN` 을 0 이나 거짓으로 변환, 암묵적
마지막 결과, 투기적 수식 엔진, 정보 누출, 판에 실행값 저장, 선언에서 난수
소비 — 는 **하나도 하지 않았고**, 각각을 테스트가 막는다.

---

## 15. 이번에 하지 않은 것 (§27)

AI · 덱 빌더 · 조건 엔진 재작성 · 아키타입 · 융합 조건 · 지속 효과 전체 ·
SEGOC · 범용 수식 언어 · Lua interpreter · 새 EventBus · 새 RandomEngine ·
새 ReplayEngine · `table.unpack` 46건 전부 · 성공 확인 카드 자동 실행 ·
STRUCTURAL-83 · 86 · 87.

**다음 Phase 는 시작하지 않았다.**
