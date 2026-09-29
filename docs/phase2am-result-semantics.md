# Phase 2-AM — Operation Outcome Semantics & Execution Integration

기준 커밋: `9f82bd8` (Phase 2-AL) · 2919 passed / 4 skipped
→ 이번 단계: **2929 passed / 4 skipped**

한 줄 결론: **새 모델을 만들지 않았다.** 감사로 여덟 질문에 답하고,
감사가 찾아낸 **진짜 결함 하나**(적혀만 있고 막지 않던 불변)를 타입으로
옮겼다. STRUCTURAL-100 은 "바꾸지 않는다" 로 닫는다 — 근거와 함께.

> 명세가 §3 중간에서 잘려 들어왔다 (§0 목적 · §1 Q1~Q8 · §2 기존 구조
> 우선 · §3 흐름 추적까지 받았다). 받은 범위는 전부 답했고, 완료 보고서
> 형식은 앞 단계들의 것을 따랐다.

---

## 1. 실측 — 엔진이 **실제로 만드는** 결과는 다섯 가지뿐

말로 답하지 않았다. `ExecutionValues.with_result` 를 가로채
`tests/engine` 전체를 돌려 **778건**을 모았다.

| 시도 | 처리 | outcome | 파생 | 건수 | 무엇 |
|---|---|---|---|---:|---|
| n | n | `unknown` | 완료 | 333 | 묘지로 · 버리기 · 파괴 (종류별 미확인 규칙) |
| n | n | `succeeded` | 완료 | 289 | 되돌리기 · 드로우 |
| — | — | `succeeded` | | 111 | 라이프 증감 · 셔플 (**장수가 없는 일**) |
| n | m<n | `unknown` | 부분 | 20 | "가능한 만큼" |
| — | — | `not_applied` | | 15 | 조건이 거짓이라 건너뜀 |

(나머지 조합은 시험이 손으로 만든 것이다.)

**`did_nothing` 이 참인 적: 0건.**

---

## 2. 여덟 질문에 대한 답 (§1)

### Q1 — `OperationResult` 만으로 충분한가 · Q3 — `OperationOutcome` 이 따로 필요한가

**충분하고, 따로 필요하다.** 두 칸이 **서로 파생되지 않는 두 사실**을 든다.

```
outcome          규칙대로 되었는가      ← 장수와 독립
affected_count   몇 장을 다뤘는가       ← 0장도 정상적인 성공
attempted_count  몇 장을 하려 했는가    ← 부분 적용은 이 둘의 관계
```

`affected_count == 0` 을 실패로 접는 코드가 **하나도 없다**는 것을 AST
시험이 지킨다. 합치면 "최대 2장까지 고르는데 0장을 골랐다" 가 실패가
된다.

### Q2 — `OperationResult` 와 `EffectResult` 의 차이

| | 답하는 것 | 사는 곳 | 수명 |
|---|---|---|---|
| `OperationResult` | **조작 하나**가 무엇을 얼마나 했는가 | `ExecutionValues` | 이 해결 안에서만 |
| `EffectResult` | **효과 하나**의 해결이 어떻게 끝났는가 | 실행기의 반환 | 밖으로 나간다 |

실패는 **효과 단위**의 사실이므로 `ResolutionStatus` 가 답한다. 그래서
조작 쪽에 `FAILED` 가 **없다** — 계획이 막히면 효과 전체가 거절되고 그
조작의 결과는 애초에 남지 않는다.

### Q4 — 여섯 상태를 표현할 수 있는가

| 물은 것 | 표현 | 실측 |
|---|---|---|
| 성공 | `SUCCEEDED` | ✔ 289 + 111 |
| 실패 | **조작에는 없다** → `ResolutionStatus` | (설계) |
| 부분 성공 | `is_partial` (시도와 처리의 관계, 저장하지 않는다) | ✔ 21 |
| 실행되지 않음 | `NOT_APPLIED` | ✔ 15 |
| 조건 불충족 | `NOT_APPLIED` — **같은 값이 맞다** | ✔ 15 |
| UNKNOWN | `UNKNOWN` | ✔ 353 |

"실행되지 않음" 과 "조건 불충족" 이 같은 값인 것은 뭉갠 것이 아니다 —
이 엔진에서 조작이 일어나지 않는 길은 **조건이 거짓인 것 하나뿐**이고,
그 외의 길은 전부 효과 전체를 거절한다.

### Q5 — "하지 않았다" 와 "했는데 0장" 을 구분하는가

**구분한다. 그리고 이번에 타입이 그것을 지키게 했다** — §3.

```
하지 않았다   NOT_APPLIED · 장수 없음(None) · was_applied=False
했는데 0장     SUCCEEDED   · affected=0      · was_applied=True
```

읽는 쪽에서도 갈린다: `ResultLookup` 이 `NOT_APPLIED` 를 **값 없음**으로
답하고, **0 으로 답하지 않는다**.

### Q6 — UNKNOWN 과 실패를 구분하는가

**다른 계층이 답한다.** `OperationOutcome.UNKNOWN` 은 "일어났지만 규칙대로
였는지 모른다" 이고, 실패는 `ResolutionStatus.*` 다. `OperationOutcome` 에
`FAILED` 가 없다는 것이 그 구분의 형태다.

### Q7 — `ResultRef` 는 어느 칸을 가리켜야 하는가

**카드가 정한다.** 2-AJ 가 공식 재정으로 확인한 결론이 그대로 답이다 —
같은 계열 7장 중 여섯은 `AFFECTED_COUNT`("덱에 넣은 매수"), 교란작전만
`ATTEMPTED_COUNT`("원래의 패의 수")다.

성패는 **수가 아니다.** `value_of(SUCCEEDED)` 는 `KeyError` 이고,
성패를 조건으로 쓰려면 `OperationRequirement` 로 적어야 한다 — 그쪽은
`ResultField.SUCCEEDED` 가 아닌 것을 거부한다. 두 길이 섞이지 않는다.

### Q8 — 2-AH 의 Deferred 구조와 충돌하는가

**충돌하지 않는다. 다른 축이다.**

```
ResultAvailability   NOT_YET · NOT_APPLIED · NO_FIELD · AVAILABLE   ← 수가 있는가
OperationOutcome     SUCCEEDED · NOT_APPLIED · UNKNOWN              ← 규칙대로였는가
```

겹치는 이름은 `NOT_APPLIED` 하나인데, 그것은 같은 사실을 두 축이 각자
말하는 것이다 (하지 않은 일에는 읽을 수도 없다).

**규칙을 다 보지 못한 일의 수는 그대로 읽힌다** — 일어나기는 했으므로 그
수는 진짜다. 그것을 막아야 하는 카드는 `OperationRequirement` 로 **스스로
적는다.** 엔진이 대신 정하지 않는다.

---

## 3. 감사가 찾은 것 — 적혀만 있고 막지 않던 불변

`OperationOutcome.NOT_APPLIED` 의 문서는 이렇게 말한다.

> 건너뛴 일에는 장수가 **없다.** 0 이 아니다.

**타입은 그것을 막지 않았다.**

```python
OperationResult(0, affected_count=0, attempted_count=0,
                outcome=OperationOutcome.NOT_APPLIED)
#   was_applied  → False    "하지 않았다"
#   is_complete  → True     "전부 했다"          ← 모순
```

실측 15건이 모두 규칙을 지키고 있었으므로 **버그가 난 적은 없다.** 그래도
막는다 — 이 프로젝트가 `RuleFact` 에 `UNKNOWN` 을 못 담게 하고(2-AK),
`EffectDefinition` 이 앞을 가리키지 않는 참조를 만들 때 막는 것(2-AH)과
같은 자리다.

같이 막은 것 하나 더: **처리한 수 > 시도한 수.** 나온 적은 없지만 나오면
`is_partial` 도 `is_complete` 도 거짓인 **이름 없는 상태**가 된다.

### 덤 — 떠 있던 docstring

```python
attempted_count: "int | None" = None
"""**하려고 한** 수 …"""
"""규칙대로 되었는가 …"""     ← 주인 없는 문자열
```

칸 순서가 바뀔 때 함께 옮겨지지 않아 `outcome` 에는 설명이 **없고**
`attempted_count` 에는 남의 설명이 붙어 있었다. 제자리로 옮겼다.

---

## 4. STRUCTURAL-100 — 바꾸지 않는다 (근거)

> 사각지대(2-AL 이 만든 `RulingVerdict.unchecked`)가 조작의 **성패**를
> 바꿔야 하는가?

**아니다.** 2-AL 에서는 "근거를 모으기 전에 내릴 결정이 아니다" 로
미뤘고, 이번에 근거를 세웠다.

바꾸면 **일관성이 깨진다.** "숨은 카드가 막았을 수 있다" 는 의심은 관문이
있는 조작만의 것이 아니다 — 지속 효과 계층이 **아예 없으므로**
(STRUCTURAL-76) 드로우도 라이프 증감도 똑같이 의심스럽다. 관문이 있는
조작만 `UNKNOWN` 으로 표시하면 그 칸의 뜻이 이렇게 된다:

> "확인 못 했다. 단, 우리가 확인 못 한 **다른 것들은 빼고**."

그래서 두 칸을 이렇게 나눈다.

| 칸 | 답하는 질문 |
|---|---|
| `OperationOutcome.UNKNOWN` | 이 조작이 주장한 의미의 규칙 중 엔진이 **아예 옮기지 못한 것**이 있다 (**모델링 범위**) |
| `EffectResult.unchecked_rules` | 이 **실행**이 보지 못한 것 전부 (위 + 판정 한 번의 사각지대) |

부수 효과도 이 선택이 맞다고 말한다. `_check_requirements` 는 앞선 일이
`UNKNOWN` 이면 **효과 전체를 거절한다.** 사각지대로 성패를 뒤집으면,
패에 카드가 있다는 이유만으로 멀쩡한 효과가 멈춘다.

시험이 이 경계를 못박는다 — 성패를 정하는 자리(`_Step.result`)는
**종류별 표 하나만** 보고 `blind` 를 보지 않는다.

---

## 5. 코드 변경

| 파일 | 변경 | 왜 |
|---|---|---|
| `engine/execution.py` | `OperationResult.__post_init__` (NOT_APPLIED 는 장수를 못 든다 · 처리 ≤ 시도) · `outcome` docstring 제자리로 | §3 |

**그것뿐이다.** 새 모델도, 새 필드도, 새 계층도 만들지 않았다.

기존 테스트 수정 **1건** (삭제 0건):

`test_operation_result.py::test_c_count_is_never_read_as_success_in_the_engine`
— **잘못된 가정은 "둘을 함께 언급하면 위반" 이었다.** 그 방식은 **방향을
보지 못한다**. 새 `__post_init__` 은 둘을 함께 언급하지만 하는 일이
정반대다 — 성패를 **읽어서** 장수를 거절한다.

막아야 하는 방향은 **장수 → 성패** 하나이므로, 검사를 그쪽으로 좁혔다:
`OperationOutcome` 이 **값으로 쓰이는** 함수(성패를 만드는 함수)만 장수를
보지 못한다. 비교로만 쓰는 함수는 성패를 읽을 뿐이다.

**약해지지 않았다는 것을 확인했다** — 위반 함수를 일부러 넣어 보니 그대로
잡는다.

```python
def _violation(result) -> OperationOutcome:
    if result.affected_count == 0:
        return OperationOutcome.NOT_APPLIED    # → 시험 실패 ✔
```

---

## 6. 판정 계층이 실행 경로에서 안전한가 (§0)

| 물은 것 | 확인 |
|---|---|
| 관문 없는 카드에 영향이 있는가 | **없다.** 판정기를 만들지도 않는다 (호출 0회, 판 해시 동일) |
| 여러 번 돌리면 같은가 | **같다.** 판정기가 판마다 새로 만들어져도 결정론적이다 |
| 기본값으로 켜지는가 | **아니다** (2-AL, ADR-006) |

---

## 7. 테스트

- New tests: **10** (`test_operation_result.py` §H 8개 · `test_operation_ruling.py` §H 2개)
- Passed **2929** / Failed 0 / Skipped 4 / Regression **0**

| 무엇을 | 시험 |
|---|---|
| 엔진이 만드는 다섯 모양 | `test_h_the_engine_only_ever_makes_five_kinds_of_result` |
| `did_nothing` 은 도달 불가 | `test_h_did_nothing_is_a_state_the_engine_never_reaches` |
| 건너뛴 일은 장수를 못 든다 | `test_h_a_skipped_operation_may_not_carry_counts` |
| 시도보다 더 할 수 없다 | `test_h_you_cannot_do_more_than_you_tried` |
| Q8 — 두 축은 충돌하지 않는다 | `test_h_an_unknown_operation_still_has_a_real_count` |
| Q7 — 성패는 수가 아니다 | `test_h_success_is_not_a_number_and_a_number_is_not_success` |
| Q6 — `FAILED` 가 없는 이유 | `test_h_there_is_no_failed_outcome_and_that_is_the_point` |
| **STRUCTURAL-100 의 경계** | `test_h_a_blind_spot_does_not_make_the_outcome_unknown` |
| 관문 없는 카드는 영향 없음 | `test_h_an_ungated_effect_is_untouched_by_the_ruling_layer` |
| 반복해도 같은 판 | `test_h_the_layer_is_deterministic_across_repeated_runs` |

---

## 8. TODO

- **STRUCTURAL-100 — 해결 (바꾸지 않는 것으로).** 근거는 §4. 경계를
  시험이 못박으므로 다음 사람이 조용히 뒤집을 수 없다.
- **STRUCTURAL-101 (신규 · 🟢)** — **`did_nothing` 은 도달할 수 없다.**
  구분 자체는 옳지만 지금 엔진은 그 상태를 만들지 못한다 (실측 0/778).
  "가능한 만큼" 에서 전부 거절되면 계획이 **실패**하기 때문이다. 없애지
  않는다 — 나중에 부분 적용이 넓어지면 필요해진다.
- **STRUCTURAL-76 (지속 효과 계층) — 그대로.** §4 의 근거가 여기서 나온다.
- **ADR-006 — 그대로 부분 해결.**
- **97 · 95 · 93 · 90 · 87 · 86 · 83 — 그대로 둔다.**
- 71 · 74 · 75 · 77 · 78 — **하나도 건드리지 않았다.**

---

## 9. 판정

| 등급 | 건수 | 내용 |
|---|---:|---|
| 🔴 BLOCKER | **0** | |
| 🟠 STRUCTURAL | 0 신규 (100 해결) | |
| 🟡 DETAIL | 0 신규 | |
| 🟢 COSMETIC | 1 신규 | 101 (`did_nothing` 도달 불가) |

---

## 10. 이번에 하지 않은 것 (§2)

**새 개념을 하나도 만들지 않았다.** `OperationOutcome` 을 새 모델로
키우지도, `SelectionResult` · `ChoiceResult` · `RandomResult` 같은 이름을
새로 만들지도 않았다 — 찾아보니 그 역할은 이미 `Selection` ·
`DeclaredNumber` · `RandomOutcome` 이 맡고 있다.

Duel Engine 재설계 · EffectExecutor 재작성 · 새 Graph Engine · 새 EventBus ·
새 Expression Language · 새 Rule Engine · AI 의사결정 · 카드 이름별
hardcoded rule · 테스트 삭제 · 규칙 추측 — 하나도 하지 않았다.

**새 카드를 한 장도 등재하지 않았다.**

**다음 Phase 는 시작하지 않았다.**
