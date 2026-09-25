# Phase 2-AG — Numeric Condition Context & Conditional Effect Flow Core

기준 커밋: `64a3457` (Phase 2-AF) · 2754 passed / 4 skipped

> **요청서가 §9 중간에서 끊겨 있었다** ("Effect B" 뒤로 §10 이후, 테스트
> 요구사항, 완료 기준, 보고서 형식이 오지 않았다). 핵심 작업(§1~§9,
> STRUCTURAL-91 · 92)은 온전했으므로 그대로 하고, 나머지는 이전 여섯
> 단계의 관례를 따랐다.

```
Operation A
  → OperationResult (attempted · affected · outcome)
  → ResultRef            명시적으로 가리킨다      (2-AD)
  → SelectionCount       값을 **구한다**          (2-AC)
  → NumericTest          값을 **견준다**          ← 이번
  → TRUE / FALSE / UNKNOWN
  → Operation B          한다 / 건너뛴다 / 전체 거절
```

한 줄 목표: **앞의 결과를 보고 뒤의 일을 할지 정하되, 모르는 채로 정하지
않는다.**

---

## 1. 변경 파일

| 파일 | 변경 |
|---|---|
| `engine/execution.py` | `Comparison` · `NumericTest` · `OperationOutcome.NOT_APPLIED` · `OperationResult.was_applied` |
| `engine/effect/definition.py` | `OperationGuard` · `EffectDefinition.guards` · `_check_guards` · `guards_for` · 조건이 읽는 선언도 "쓴 것" |
| `engine/effect/target.py` | `SelectionCount.resolve` 가 **0 을 거부하지 않는다** (아래 §6) |
| `engine/effect/executor.py` | `_check_guards` · 계획 루프의 건너뛰기 · `_resolve_number(minimum=…)` |
| `tests/engine/test_conditional_flow.py` | **신규** — 30 함수 / 36 케이스 |
| `test_execution_context.py` · `test_operation_result.py` | 단언 갱신 2건 (§12) |
| `docs/phase2ag-conditional-flow.md` · `engine/__init__.py` | 문서 |

**새 모듈 0개.** 새 EventBus · EffectEngine · Expression Language ·
Lua interpreter 0개. 판정 어휘도 새로 만들지 않았다 —
`ConditionResult`(TRUE/FALSE/UNKNOWN)를 그대로 돌려준다.

---

## 2. STRUCTURAL-92 — 실제로 필요한 비교는 둘뿐이었다 (§3)

조작의 결과를 조건으로 쓰는 자리 **97곳**의 비교 연산을 전부 세었다.

| 비교 | 건 | 묻는 것 |
|---|---:|---|
| `> 0` | 57 | 하나라도 됐는가 |
| `== 0` | 26 | 하나도 안 됐는가 |
| `~= 0` | 8 | 하나라도 됐는가 |
| `> 1` | 2 | 둘 이상인가 |
| `<= 0` | 1 | 하나도 안 됐는가 |
| `>= 2` | 1 | 둘 이상인가 |
| `>= 1` | 1 | 하나라도 됐는가 |
| `== <변수>` | 1 | **전부** 됐는가 (값끼리 견준다) |

**91곳(94%)이 0 과 견준다.** 장수는 음수가 될 수 없으므로 `> 0` ·
`~= 0` · `>= 1` 은 같은 질문이고 `== 0` · `<= 0` 도 같은 질문이다.

그래서 `AT_LEAST` 와 `AT_MOST` 둘만 만들었다. 이 둘로 **96곳**이 적힌다.

`EQUAL` · `NOT_EQUAL` · `GREATER_THAN` · `LESS_THAN` 을 **만들지
않았다** (§3 "모든 비교 연산을 speculative 하게 만들지 않는다"). 정확히
N 은 `at_least(N)` 과 `at_most(N)` 을 함께 거는 것으로 적히고, 나머지는
쓰는 카드를 못 찾았다 — 쓰지 않는 연산자를 미리 만들면 그것이 옳은지
아무도 확인하지 않는다.

남은 한 곳(`dc == ct`, 59490397)은 오른쪽이 상수가 아니라 **다른
값**이다. 1곳이므로 넓히지 않았다 (STRUCTURAL-93). 다만 **그 한 곳이
묻는 것**은 이미 적을 수 있다 — "시도한 수와 처리한 수가 같은가" 는
2-AF 의 `OperationResult.is_complete` 가 답한다.

### 값과 조건과 도메인은 셋 다 다르다 (§2)

```
affected_count = 3            값      SelectionCount
affected_count >= 1           조건    NumericTest        ← 이번
affected_count ∈ 1 이상       도메인  ValueDomain        (2-AF)
조건이 참이면 다음 일을 한다     실행 흐름 OperationGuard    ← 이번
```

`NumericTest` 는 **값을 구하지 않는다.** `ExecutionValues` 도
`GameState` 도 `ResultRef` 도 모른다는 것을 AST 로 확인한다.

---

## 3. 값의 출처는 이미 다섯이 있었다 (§4)

새로 만들지 않았다. `SelectionCount` 가 그대로 조건의 입력이 된다.

| 출처 | 어디 |
|---|---|
| 상수 | `SelectionCount.fixed` |
| 선언한 수 | `SelectionCount.from_declaration` |
| 앞선 조작의 결과 | `SelectionCount.from_result` |
| 판에서 계산 | `SelectionCount.derived` |
| 모름 | `SelectionCount.unknown` |

**암묵적으로 찾지 않는다.** "마지막 count" 는 없고, 정의를 만들 때 그
번호가 **자기보다 앞인지** 검사한다 (2-AD · 2-AE 와 같은 규칙).

---

## 4. STRUCTURAL-91 — 세 답이 세 가지 다른 일로 이어진다 (§6 · §8 · §9)

| 조건 | 무엇을 하는가 |
|---|---|
| TRUE | 한다 |
| FALSE | **건너뛴다** — 실패가 아니다. 효과는 계속된다 |
| UNKNOWN | **전체를 거절한다** |

마지막 줄이 이 단계의 요점이다. **건너뛰는 것도 결정이다.** 조건을
모르는 채로 건너뛰면 그 일을 했어야 하는지 안 했어야 하는지를 **엔진이
지어낸 것**이 된다. `UNKNOWN` 은 허가도 거절도 아니다.

corpus 의 두 모양이 모두 적힌다.

```
if ct>0 then <다음 일> end     66곳  → at_least(1)
if ct==0 then return end       27곳  → 뒤의 일마다 at_least(1) 을 건다
```

### 건너뛴 일은 자리를 지킨다

번호는 밀리지 않는다 — 뒤의 일이 **번호로** 앞을 가리키기 때문이다.
건너뛴 자리에는 `OperationOutcome.NOT_APPLIED` 가 들어간다.

**`NOT_APPLIED` 는 `FAILED` 가 아니다** (그리고 `FAILED` 는 여전히
없다). 규칙이 "하지 말라" 고 한 것을 따른 것이고, 효과는 정상 해결된다.

건너뛴 일에는 **장수가 없다.** 0 이 아니다 — "0장을 다뤘다" 와 "하지
않았다" 는 다른 사실이고, 뒤의 일이 이것을 수로 읽으려 하면 `UNKNOWN`
으로 멈춘다.

### 2-AE 와 부딪히지 않는다

2-AF 의 TODO 가 걱정한 지점이다 — "수를 조건처럼 읽는 것" 을 막아 둔
2-AE 의 결정과 부딪히지 않는가.

부딪히지 않는다. **둘은 다른 것**이고 나란히 있다.

| | 무엇을 보는가 | 아니면 |
|---|---|---|
| `OperationRequirement` (2-AE) | 앞이 **규칙대로 되었는가** | 거절 |
| `OperationGuard` (2-AG) | 앞의 **수가 조건을 만족하는가** | 건너뜀 |

2-AE 가 막은 것은 **벌거벗은 수를 참/거짓으로 읽는 것**이다. 여기서는
수를 **수로** 읽고 견주는 방법을 명시적으로 적는다.
`OperationRequirement` 는 지금도 `AFFECTED_COUNT` 를 거부한다.

---

## 5. 조건은 **계획 시점**의 판을 본다

계획이 전부 끝난 뒤에야 적용이 시작되므로(2-V), 같은 효과 안에서 앞의
일이 판을 바꾼 결과는 **판을 읽는 조건에 보이지 않는다.**

```
DrawOperation(2), DrawOperation(1)
  guard: 자신 패가 3장 이상일 때만 1번을 한다
  → 계획 시점의 패는 0장이므로 1번은 건너뛴다
```

앞의 일이 한 것을 보려면 판이 아니라 **결과**를 가리켜야 한다
(`SelectionCount.from_result`). 테스트가 두 길을 나란히 확인한다.

**감추지 않는다.** STRUCTURAL-94 로 남긴다.

---

## 6. 0 을 누가 거부하는가 (부수 발견)

조건을 붙이자마자 드러난 것이 있다. `SelectionCount.resolve` 는 계산된
수가 **0 이면 `INVALID`** 였다 (2-AC). "0장을 고르는 것은 고르지 않는
것" 이라는 이유였고, **고르라는 자리에서는 지금도 맞다.**

그런데 **조건의 입력으로는 0 이 멀쩡한 값**이다 — "하나도 없다" 가
바로 66곳이 묻는 것이다.

그래서 규칙을 **쓰는 자리로 옮겼다.**

```
SelectionCount.resolve   수를 그대로 답한다 (0 도)
_resolve_number(minimum) 고르라 · 뽑으라 → 1 이상 · 견주라 → 0 도
```

값이 **무엇인가**와 그 값이 **여기서 되는가**는 다른 질문이라는 2-AF
의 결론을 한 걸음 더 지킨 것이다. 기존 동작은 그대로다 — 계산된 0 으로
무작위 선택이나 드로우를 하려 하면 여전히 `INVALID_AMOUNT` 다.

---

## 7. 경계 (§2 · §6 · §7)

| 경계 | 어떻게 지키는가 |
|---|---|
| 값 ≠ 조건 | `NumericTest` 가 `ExecutionValues`·`GameState`·`ResultRef` 를 모른다 (AST) |
| 값 UNKNOWN ≠ 조건 FALSE | 값을 못 구하면 그 실패를 그대로 들고 나간다 — 건너뛰지 않는다 |
| 건너뜀 ≠ 실패 | `NOT_APPLIED` 는 `FAILED` 가 아니고, `FAILED` 는 여전히 없다 |
| 하지 않음 ≠ 0장 | 건너뛴 일의 수를 읽으면 `UNKNOWN` |
| 실행값 ≠ 판 | `state_hash` 는 한 줄도 바뀌지 않았다 |
| 결정 ≠ 사건 | 저널에 `guard`·`not_applied`·`at_least` 가 적히지 않는다 |
| 장수 ≠ 정체 | 상대 패의 **장수**로 조건을 걸어도 그 패는 가려져 있다 |

---

## 8. 테스트

`tests/engine/test_conditional_flow.py` — **30 함수 / 36 케이스**, 전부
통과.

| 절 | 무엇을 붙잡는가 |
|---|---|
| A | 여덟 가지 견주기 · 연산자가 둘뿐 · `NumericTest` 가 값을 안 찾는다 (AST) · 음수 피연산자 거부 |
| B · C | 참이면 한다 · **거짓이면 건너뛴다**(효과는 해결) · 두 corpus 모양 · 여러 조건은 AND · 조건 없는 조건문 거부 |
| D · E | 값이 `UNKNOWN` 이면 전체 거절 · 건너뛴 일의 수는 읽을 수 없다 · 선언이 `PENDING` 인 것과 조건이 거짓인 것은 다르다 |
| F · G | 건너뛴 일이 **자리를 지킨다**(번호가 안 밀린다) · 하지 않은 일과 0장을 다룬 일이 다르다 |
| H · I | 다섯 출처가 모두 조건의 입력 · **판은 계획 시점**을 본다(결과를 보려면 `from_result`) · 앞만 가리킨다 · `results[-1]` 이 없다 |
| J | 조건과 요구가 다른 일을 한다 · 성패는 여전히 거절이지 건너뛰기가 아니다 |
| K ~ P | 같은 판이면 같은 결정 · 복제 독립 · 건너뛴 뒤 막혀도 판 그대로 · 정체가 안 샌다 · 저널엔 일어난 일만 · 해시 그대로 |
| Q | 97곳의 비교표 · 값끼리 견주는 한 곳은 범위 밖 · **0장 등재** |

---

## 9. 회귀

```
2790 passed, 4 skipped in 39.66s     (기준선 2754 + 36)
```

---

## 10. 실제 카드

**0장 등재했다.**

조건을 적을 수 있게 됐지만, 그 조건이 보는 수를 내는 일(파괴)은 여전히
판정기가 없어 일어나지 않는다 (`UnknownDestructionRuling` — ADR-006).
2-AF 와 같은 벽이고, 조건을 만들었다고 사라지지 않는다.

검증은 **시험용 판정기**로 실제 실행에서 했다 — 셋 중 둘이 파괴되면
`>= 1` 이 참이라 뽑고, `>= 4` 면 거짓이라 뽑지 않으며(파괴는 그대로
남는다), 수를 모르면 전부 멈춘다.

---

## 11. TODO

- **STRUCTURAL-91 — 해결.** 앞의 수를 보고 뒤의 일을 할지 정할 수 있고,
  모르면 건너뛰지 않는다.
- **STRUCTURAL-92 — 해결.** 조건이 숫자를 입력으로 받는다. 값의 출처
  다섯 가지가 모두 조건에 들어간다.
- **STRUCTURAL-93 (신규 · 🟡)** — **값끼리 견주지 못한다.**
  `NumericTest` 의 오른쪽이 상수뿐이다. 실제 카드 1곳(59490397)이
  걸리고, 그 한 곳이 묻는 것은 `is_complete` 로 이미 답할 수 있다.
- **STRUCTURAL-94 (신규 · 🟠)** — **판을 읽는 조건이 앞선 일의 결과를
  보지 못한다.** 계획 시점의 판을 보기 때문이다. 결과를 가리키면 되지만,
  "앞의 일이 끝난 뒤의 판" 을 보려면 계획을 단계별로 나누는 구조가
  필요하고 그것은 plan/apply 의 근본을 건드린다.
- **STRUCTURAL-90 · 83 · 86 · 87 — 그대로 둔다.**
- 71 · 74 · 75 · 76 · 77 · 78 — **하나도 건드리지 않았다.**

---

## 12. 판정

| 등급 | 건수 | 내용 |
|---|---:|---|
| 🔴 BLOCKER | **0** | |
| 🟠 STRUCTURAL | 1 신규 | 94 (조건이 보는 판의 시점) |
| 🟡 DETAIL | 1 신규 | 93 (값끼리 견주기) |
| 🟢 COSMETIC | 0 신규 | |

`UNKNOWN` 을 참으로도 거짓으로도 0 으로도 바꾸지 않았고, 암묵적 참조를
만들지 않았으며, 판정 어휘를 새로 만들지 않았다.

### 기존 테스트 수정 (삭제 0건, 수정 2건)

1. `test_execution_context.py` · `test_operation_result.py` 의
   `OperationOutcome` 목록. `NOT_APPLIED` 가 늘었으므로 적어 두고 계속
   센다. 두 시험이 지키려던 것(**`FAILED` 가 없다**)은 그대로 단언한다 —
   건너뛴 일과 막힌 일은 다른 것이다.

---

## 13. 이번에 하지 않은 것

전체 Condition Engine 구현 · 새 EventBus · 새 EffectEngine · Expression
Language · Lua interpreter · 비교 연산자 확장 · 64건 자동 구현 ·
STRUCTURAL-83 · 86 · 87 · 90.

**다음 Phase 는 시작하지 않았다.**
