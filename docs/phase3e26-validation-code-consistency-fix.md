# Phase 3-E-26 — UNKNOWN / ValidationCode 정합성 최소 수정

- Base commit: `a3ebde7` (Phase 3-E-25)
- 성격: **감사가 아니다.** 3-E-24 · 3-E-25 가 측정한 코드 정합성 문제의 최소 수정
- 결론: **수정 5곳 + docstring 1곳.** 새 enum · 새 status · 새 계층 · 새 subsystem 0개

## 1. 수정 전 측정 — 무엇이 어긋나 있었나

`ValidationCode` 는 "판정의 안정적인 이유 코드" 다. 그런데
`RULE_NOT_IMPLEMENTED` 에는 **docstring 이 없었고**, 그 자리에 최소 네 뜻이
섞여 있었다 (3-E-24 측정). 이번 Phase 가 손댄 것은 그중 **의미가 정확히 맞는
다른 코드가 이미 enum 에 있는** 자리들이다.

| 자리 | 사실 | 적혀 있던 코드 | 맞는 코드 |
|---|---|---|---|
| `TriggerCollector._judge` 조건 FALSE | 확실한 거부 | `RULE_NOT_IMPLEMENTED` | `CANDIDATE_NOT_ELIGIBLE` |
| `TriggerCollector._judge` 출처 금지 | ADR-004 금지 | `RULE_NOT_IMPLEMENTED` | `EXECUTION_FORBIDDEN` |
| `TriggerEligibilityJudge._trigger_condition` 조건 FALSE | 확실한 거부 | `RULE_NOT_IMPLEMENTED` | `CANDIDATE_NOT_ELIGIBLE` |
| `EffectActivator._check_condition` UNKNOWN | 규칙 없음 / 정보 없음 | 언제나 `INFORMATION_UNAVAILABLE` | 갈라야 한다 |
| `EffectExecutor._check_activation_condition` UNKNOWN | 같음 | 언제나 `INFORMATION_UNAVAILABLE` | 갈라야 한다 |

세 번째는 **이번에 새로 측정한 것**이다. prompt §3 이 지목한 두 자리는
수집기(`_judge`)였는데, 같은 파일의 판정 관문(`_trigger_condition`)이 **같은
문장(`"조건이 거짓입니다: …"`)으로 같은 사실을** 말하면서 같은 잘못된 코드를
쓰고 있었다. 수집기만 고치면 두 계층이 같은 거부를 다른 이유로 말하게 되므로
— 이번 Phase 가 없애려는 바로 그 상태 — 함께 고쳤다.

### 측정값 (AST 로 `ValidationCode.X` 참조를 센 것, `engine/`)

| 코드 | `a3ebde7` | 수정 후 | 차 |
|---|---|---|---|
| `RULE_NOT_IMPLEMENTED` | 66 | 65 | −3 (트리거 3곳) +2 (갈래 2곳) |
| `CANDIDATE_NOT_ELIGIBLE` | 5 | 7 | +2 |
| `EXECUTION_FORBIDDEN` | 4 | 5 | +1 |
| `INFORMATION_UNAVAILABLE` | 13 | 13 | 0 (무조건 → 갈래) |

> **내 이전 숫자를 고친다.** 3-E-24 보고서는 `RULE_NOT_IMPLEMENTED` 를
> "62곳" 이라고 적었다. AST 로 다시 세면 `a3ebde7` 에서 **66**이다. 믿을
> 숫자는 AST 쪽이다.

## 2. §3 `_judge` 판정 — 왜 `CANDIDATE_NOT_ELIGIBLE` 인가

**문자열이 비슷해서가 아니라 측정된 semantics 가 같아서다.** 이 코드는 이미
`ConditionResult.FALSE` → 확실한 거부에 쓰이고 있었다.

| 기존 자리 | 모양 |
|---|---|
| `engine/effect/targeting.py:416` | `FALSE` → `ILLEGAL` + `CANDIDATE_NOT_ELIGIBLE` ("후보 조건을 만족하지 않습니다") |
| `engine/cost/validation.py:239` | 후보 아님 → `invalid(CANDIDATE_NOT_ELIGIBLE, …)` |
| `engine/effect/executor.py:1725` | **`FALSE` → `CANDIDATE_NOT_ELIGIBLE` / `UNKNOWN` → `RULE_NOT_IMPLEMENTED`** |

마지막 자리가 결정적이다. **같은 갈림길에서 같은 두 코드를 쓰는 선례가 이미
production 에 있다.** 더해서 판정 대상의 이름 자체가 `TriggerCandidate` 이고
상태가 `TriggerStatus.INELIGIBLE` 이다 — "candidate not eligible" 이 그
두 단어다.

## 3. §4 FORBIDDEN 코드 판정 — 가장 분명한 자리

같은 파일 안에서 **같은 사실이 두 코드로 적혀 있었다.**

| 자리 | 사실 | 코드 |
|---|---|---|
| `TriggerCollector._judge` (수정 전) | `provenance.is_forbidden` | `RULE_NOT_IMPLEMENTED` |
| `TriggerEligibilityJudge._execution_authority:1440` | `FORBIDDEN_SOURCE` | `EXECUTION_FORBIDDEN` |

두 자리의 **설명 문장이 글자 그대로 같다**: `"공식 텍스트에서 유추한 효과는
실행하지 않습니다 (ADR-004)."` 같은 사실, 같은 문장, 다른 코드다.

그리고 이것은 단순한 라벨 문제가 아니다. 금지를 알아보는 **유일한 자리**가
코드로 판단한다:

```python
# engine/trigger.py:1058
@property
def forbids(self) -> bool:
    return self.result.code is ValidationCode.EXECUTION_FORBIDDEN
```

`TriggerEligibility.fold` 은 이 성질로 `FORBIDDEN` 을 가장 먼저 접는다.
수집기가 다른 코드로 적으면 **그 금지는 보이지 않는다.**

### `fold` 이 뒤집히지 않는가

뒤집히지 않는다. `fold(candidate, gates)` 는 **`gates` 만** 읽고
`candidate.code` 를 읽지 않는다 (`engine/trigger.py:1117-1125` 확인). 후보의
코드는 실려 나르는 값이다.

## 4. §5 `_check_condition` 판정 — 가를 수 있는가

**가를 수 있다.** 억지로 만든 구분이 아니라, 이 저장소가 **이미 하고 있는**
구분이다.

```python
# engine/action_validation.py:346 — 선례
rules = requirement.condition.missing_rules(self._view, context)
...
if missing is not None:
    return ValidationResult.unknown(ValidationCode.RULE_NOT_IMPLEMENTED, …, missing_rule=missing)
return ValidationResult.unknown(ValidationCode.INFORMATION_UNAVAILABLE, …)
```

`Condition.missing_rules(view, context)` 는 `UNKNOWN` 이 아닐 때 `()` 를,
`UnimplementedRule` 일 때 `(rule,)` 를 준다. `IsMonster(없는 카드)` 는 `()`
다. 즉 **기계적으로 갈린다** — 새 구조가 필요 없다.

### 왜 실행기까지 함께 고쳤는가

발동기의 docstring 이 스스로 그렇게 적는다:

> ``None`` 은 **"조건이 없다" 가 아니라 "적지 않았다"** 이므로 넘어간다 —
> **실행기와 같은 태도이고, 여기서 다르게 읽으면 같은 정의가 두 곳에서
> 다른 뜻이 된다.**

`EffectExecutor._check_activation_condition` 은 발동기와 **분기 모양까지
같다.** 한쪽만 고치면 이 약속이 깨진다 — 그것은 범위 확장이 아니라 지목된
수정의 정확성이다. `tests/test_validation_code_consistency.py::test_07` 이 두
계층의 일치를 시험으로 고정했다.

### 조건이 **거짓**일 때는 가르지 않았다

`activation.py` · `executor.py` 의 FALSE 분기도 `RULE_NOT_IMPLEMENTED` 다.
여기는 **고치지 않았다.** 까닭:

- `CANDIDATE_NOT_ELIGIBLE` 의 측정된 뜻은 "**고른 카드**가 후보 조건을
  만족하지 않는다" 다. 발동/해결 계층에는 고른 후보 카드가 없고, 판정 대상은
  효과의 발동 조건이다. 문자열이 비슷하다는 이유로 끌어오면 §4 가 금지한 바로
  그 통합이 된다.
- 48개 코드를 전부 읽었지만 "조건이 거짓" 을 말하는 코드는 **없다.** §7 이
  새 enum 을 금지한다.
- 그리고 **판정이 이미 사실을 정확히 싣는다** — `ActivationStatus.CONDITION_FALSE` ·
  `ResolutionStatus.CONDITION_FALSE` 가 그 자리다. 부르는 쪽이 보는 것은
  status 다.

→ §5 의 지시대로 **억지로 구분하지 않고 이유를 남긴다.**

## 5. §6 UNKNOWN 의미 보존 — 판정은 한 칸도 움직이지 않았다

| 불변식 | 지켜졌는가 | 근거 |
|---|---|---|
| `UNKNOWN ≠ VALID` | 그렇다 | 갈래 양쪽 모두 `CONDITION_UNKNOWN` · `ActionValidity.UNKNOWN` |
| `UNKNOWN ≠ INVALID` | 그렇다 | `test_08` 이 `CONDITION_UNKNOWN is not CONDITION_FALSE` 를 고정 |
| `UNKNOWN ≠ FALSE` | 그렇다 | 주입 F (UNKNOWN→CONDITION_FALSE) 가 3개 테스트에 걸린다 |
| `UNKNOWN ≠ 0` | 그렇다 | `agent/search.py` 가 점수를 **주지 않는다** (§8 참조) |
| 모름이 판을 바꾸지 않는다 | 그렇다 | `state_hash()` 동일 · `len(chain) == 0` 단정 |

수정 ④⑤ 는 **`UNKNOWN` 안에서 이유만** 갈랐다. 수정 ①②③ 은 `status` 가
이미 맞게 적혀 있던 자리의 `code` 만 맞췄다 (3-E-24 의 표현: "판정은 틀리지
않고 이유만 틀린다").

## 6. §7 기존 구조 우선 — 만들지 않은 것

| 금지 | 지켰는가 |
|---|---|
| 새 `ValidationCode` | 그렇다 — 48개 그대로 (`test_09`) |
| 새 Status enum | 그렇다 — `ActivationStatus` · `ResolutionStatus` · `TriggerStatus` 손대지 않았다 |
| `ValidationResult` subclass | 그렇다 |
| 새 `RuleStatus` | 그렇다 |
| 새 Gate layer | 그렇다 — 관문 5개 그대로 |
| 새 subsystem | 그렇다 |

쓴 것은 전부 **이미 있던** 것이다: `CANDIDATE_NOT_ELIGIBLE` ·
`EXECUTION_FORBIDDEN` · `Condition.missing_rules()`.

## 7. §8 production 영향 — 코드로 분기하는 자리를 전부 찾았다

처음 측정에서 나는 "`GateVerdict.forbids` 가 유일한 분기" 라고 봤다. **그것은
틀렸다** — `is ValidationCode.X` 패턴만 찾았기 때문이다. 집합 멤버십으로
분기하는 자리가 하나 더 있다:

```python
# agent/simulation.py:89
_UNKNOWN_CODES: frozenset[ValidationCode] = frozenset({
    ValidationCode.RULE_NOT_IMPLEMENTED,
    ValidationCode.COST_NOT_IMPLEMENTED,
    ValidationCode.INFORMATION_UNAVAILABLE,
    ValidationCode.CARD_DEFINITION_UNAVAILABLE,
    ValidationCode.EFFECT_LIST_UNRELIABLE,
})
# :283
status = SimulationStatus.UNKNOWN if step.code in _UNKNOWN_CODES else SimulationStatus.REFUSED
```

**이 자리가 이번 수정의 안전을 결정한다.**

| 수정 | 영향 |
|---|---|
| ④⑤ (`INFORMATION_UNAVAILABLE` ↔ `RULE_NOT_IMPLEMENTED`) | **없다.** 둘 다 `_UNKNOWN_CODES` 안이라 분류가 같다 |
| ①②③ (`CANDIDATE_NOT_ELIGIBLE` · `EXECUTION_FORBIDDEN`) | 지금은 **없다.** 트리거 계층이 잠들어 있어 `DuelStep.code` 에 닿지 않는다 |

잠들어 있다는 것은 추측이 아니라 측정이다 — `engine/duel.py` 의 import 를
AST 로 읽으면 `engine.trigger` · `engine.timing` · `engine.event_pipeline` 이
**없다** (`test_12` 가 고정).

이어지는 날에는 어떻게 되는가: 두 코드는 `_UNKNOWN_CODES` 에 없으므로
`REFUSED` 로 분류된다. **그것이 맞는 답이다** — 조건이 거짓인 것과 출처가
금지된 것은 "규칙이 아직 없다" 가 아니다. 그리고 `CANDIDATE_NOT_ELIGIBLE` 은
이미 대상/비용 계층에서 `DuelStep` 까지 올라가 `REFUSED` 로 분류되고 있으므로,
이번 수정은 트리거 계층을 **나머지와 같게** 만든다.

## 8. §9 AI / Search 영향 — 문제 없음

| 자리 | UNKNOWN 취급 |
|---|---|
| `agent/simulation.py` | `SimulationStatus.UNKNOWN` — 거절과 **섞지 않는다** (docstring: "모른다는 것이지 나쁘다는 것이 아니다") |
| `agent/search.py:45` | "`UNKNOWN` 으로 끝난 후보는 **점수가 없다.** 0 점도, 최저 점수도 아니다" |
| `agent/search.py:112` | 점수가 있는 후보가 먼저, `UNKNOWN` 은 **나쁜 것이 아니라** 모르는 것 |
| `agent/policy.py` · `runner.py` | "엔진이 `UNKNOWN` 을 허가로 바꾸지 않는 것과 같은 자리" |
| `agent/evaluation.py` | `ExclusionCategory.UNKNOWN` 과 `WITHHELD` 를 따로 둔다 |

**`UNKNOWN` 을 0점이나 `INVALID` 로 접는 자리가 없다.** 별도 Phase 후보로
기록할 것이 없다.

## 9. 바꾼 파일

| 파일 | 바꾼 것 |
|---|---|
| `engine/trigger.py` | 수정 ①②③ (코드 값 3개 + 까닭 주석) |
| `engine/activation.py` | 수정 ④ (`missing_rules` 로 갈래) |
| `engine/effect/executor.py` | 수정 ⑤ (④ 와 같은 태도) |
| `engine/validation.py` | `RULE_NOT_IMPLEMENTED` docstring |

**데이터 파일 · Lua 파일 · `data/` 아래 어느 것도 손대지 않았다.**

## 10. §10 테스트

`tests/test_validation_code_consistency.py` — **13개 추가** (행동 8 · 구조 5).

| # | 보는 것 |
|---|---|
| 01 | 조건 거짓 후보 = `INELIGIBLE` + `CANDIDATE_NOT_ELIGIBLE`, 미구현 아님 |
| 02 | 출처 금지 = `FORBIDDEN` + `EXECUTION_FORBIDDEN`, 그리고 `GateVerdict.forbids` 가 **그 코드를 알아본다** |
| 03 | 수집기와 판정 관문이 같은 거짓에 **같은 코드** |
| 04 | §6 — `UnimplementedRule` 후보는 여전히 `UNKNOWN`, 거부로 접히지 않는다 |
| 05 | 규칙 없음 → `RULE_NOT_IMPLEMENTED` + `missing` 에 규칙 이름, 판 불변 |
| 06 | 정보 없음 → `INFORMATION_UNAVAILABLE`, 판 불변 |
| 07 | **발동기와 실행기가 같은 정의에 같은 코드** (docstring 의 약속을 고정) |
| 08 | §6 — 갈래가 `UNKNOWN` 을 판정으로 바꾸지 않는다 |
| 09 | §7 — 어휘가 늘지 않았다 (`ValidationCode` 48 · `ActionValidity` 3 · `TriggerStatus` 4) |
| 10 | §8·§9 — `_UNKNOWN_CODES` 가 두 코드를 **같게** 본다 / 거부 코드는 그 집합 밖 / `UNKNOWN` 은 0점 아님 |
| 11 | **남은 `INVALID` + `RULE_NOT_IMPLEMENTED` 3곳을 자리마다 센다** |
| 12 | `engine/duel.py` 가 트리거 계층을 import 하지 않는다 (잠듦 = production 무영향) |
| 13 | `RULE_NOT_IMPLEMENTED` 의 뜻이 적혀 있고 대안 3개를 가리킨다 |

### 기존 테스트 갱신 2개 — 삭제 · skip · 약화 **없음**

**`tests/engine/test_effect_execution.py::test_an_unknown_condition_changes_nothing_and_is_not_false`**

- 잘못된 가정: "`UNKNOWN` 인 발동 조건의 코드는 언제나
  `INFORMATION_UNAVAILABLE` 이다."
- 왜 잘못인가: 이 테스트가 거는 조건은 `UnimplementedRule("체인 위의 카드
  수")` 다. 모르는 까닭은 **규칙이 없어서**이고 정보가 없어서가 아니다.
  `INFORMATION_UNAVAILABLE` 의 docstring 은 원인을 "가려진 카드 · 읽을 수
  없는 카드 정의" 로 열거한다 — 전부 정보 쪽이다. 3-E-24 가 세운
  `MISSING_RULE ≠ HIDDEN_INFORMATION` 을 이 테스트가 뭉개고 있었다.
- 어떻게 바꿨는가: `RULE_NOT_IMPLEMENTED` 를 단정하고 **`is not
  INFORMATION_UNAVAILABLE` 을 더했다.** 그리고 바로 아래
  `test_hidden_information_makes_the_condition_unknown_not_true` 에
  **없던 코드 단정을 추가**해 갈래의 반대쪽까지 잠갔다. 단정은 늘었고
  좁아졌다.

**`tests/test_rule_status_semantics_audit.py::test_08_a_false_condition_is_reported_with_the_unimplemented_code`**

- 잘못된 가정은 아니다 — 이것은 3-E-24 가 **결함이 있음을 측정한** 감사
  테스트였다. 결함이 사라졌으니 단정이 반대로 뒤집혀야 한다.
- 함수 이름은 **그대로 두었다.** 3-E-24 의 발견 ① 을 찾는 사람이 이 자리에
  닿아야 하기 때문이다. docstring 에 "이름은 측정 당시의 이름이고, 지금 하는
  일은 고친 것이 되돌아가지 않게 지키는 것" 이라고 적었다.
- 단정은 늘었다: 관문(`_trigger_condition`)까지 함께 보고,
  `RULE_NOT_IMPLEMENTED` 가 **없음**을 단정한다.

## 11. §11 회귀 + 고의 위반 검증

| 항목 | 값 |
|---|---|
| `a3ebde7` 기준선 | 3642 passed · 4 skipped |
| 수정 후 | **3655 passed · 4 skipped** (394s) |
| 차 | +13 = 새 테스트 그대로. 잃은 테스트 0 · 새 skip 0 |

고의 위반 8개를 넣고 **잡히는지** 확인했다 (전부 커밋 후 주입 → 확인 →
`git checkout` 복구).

| 주입 | 되돌린 것 | 잡혔는가 |
|---|---|---|
| A | `_judge` 거짓 → `RULE_NOT_IMPLEMENTED` | 4개 실패 ✅ |
| B | `_judge` 금지 → `RULE_NOT_IMPLEMENTED` | 2개 실패 ✅ |
| C | 관문만 되돌려 두 계층을 어긋나게 | 2개 실패 ✅ |
| D | 발동기의 갈래 제거 | 2개 실패 ✅ |
| E | 실행기만 되돌려 mirror 위반 | 2개 실패 ✅ |
| F | `UNKNOWN` → `CONDITION_FALSE` (§6 위반) | 4개 실패 ✅ |
| G | 새 자리에 `INVALID` + `RULE_NOT_IMPLEMENTED` 추가 | **처음엔 안 잡혔다** → 아래 |
| H | 남은 3곳 중 하나를 억지로 통합 | 1개 실패 ✅ |

### 주입 G 가 처음에 안 잡힌 것 — 측정 방법의 결함

`test_11` 이 `(파일, 판정)` **집합**으로 모았기 때문에, `engine/trigger.py` 에
`ActionValidity.INVALID` + `RULE_NOT_IMPLEMENTED` 자리가 **하나 더** 생겨도
이미 있던 원소에 흡수됐다. 같은 파일에 같은 모양이 하나 더 생기는 것이 바로
되돌아가는 모습인데, 그것을 놓치는 측정이었다.

`collections.Counter` 로 **자리마다 세도록** 고쳤다. 다시 주입하니 G 도 H 도
잡힌다.

## 12. §12 범위 — 하지 않은 것

- 트리거 계층의 **조건 UNKNOWN** 갈래 (`_judge` · `_trigger_condition` ·
  `TriggerChainIntegrator`) 는 가르지 않았다. 잠든 계층이고, 기존 테스트 2개
  (`test_trigger.py:388` · `test_trigger_chain.py:291`)가 현재 코드를
  고정하고 있다. → **다음 Phase 후보**
- `activation.py` · `executor.py` 의 **FALSE 분기** 는 손대지 않았다 (§4 참조).
- `agent/` 를 수정하지 않았다 (§9 — 고칠 것이 없었다).
- 트리거 실행 경로를 **만들지 않았다.** 이번 Phase 는 코드 값과 docstring
  외에 아무 동작도 추가하지 않았다.

## 13. §13 STRUCTURAL 판정 — 신규 없음

`STRUCTURAL-31 / -32 / -33 / -34 / -124 / -128 / -131 / -133` 전부 유지 ·
영향 없음.

3-E-24 가 발견 ①② 에 대해 조건 2·5(기존 semantics 로 표현 불가)가 불성립이라
STRUCTURAL ID 없이 "연결 계약" 으로 남겼다고 적었다. **이번 Phase 가 그
계약을 이행했다** — 기존 semantics 로 표현할 수 있었고, 그대로 연결했다.

남은 3곳("조건이 거짓" · "이 사건과 무관" 을 말하는 코드가 없다)도
STRUCTURAL 로 올리지 않는다: 판정(status)이 사실을 정확히 싣고 있어 **지금
해가 없고**, 새 enum 은 §7 이 금지한다. `test_11` 이 숫자로 지킨다.

## 14. §14 최종 판정

**수정 5곳 + docstring 1곳으로 끝났다. 측정된 3개 문제 중 3개 모두 처리.**

| 문제 | 판정 | 이유 |
|---|---|---|
| ① `_judge` 거짓 코드 | **고쳤다** | 같은 갈림길의 선례가 production 에 있다 |
| ② `_judge` 금지 코드 | **고쳤다** | 같은 파일 · 같은 문장 · 금지를 읽는 쪽이 코드로 판단 |
| ③ `_check_condition` UNKNOWN | **고쳤다 (+ 실행기)** | `missing_rules` 로 기계적으로 갈린다 · docstring 이 두 계층 일치를 요구 |
| (추가 측정) 관문의 거짓 코드 | **고쳤다** | ① 과 같은 사실 · 같은 문장 |
| (추가 측정) FALSE 분기 2곳 | **고치지 않았다** | 맞는 코드가 enum 에 없고 새 enum 금지 · status 가 사실을 싣는다 |

**production 동작은 바뀌지 않았다.** ①②③ 은 잠든 계층이고 (`test_12`),
④⑤ 는 `agent/simulation.py` 가 두 코드를 같게 보므로 분류가 같다 (`test_10`).
바뀐 것은 **이유를 묻는 사람이 받는 답** 이다.

## 15. 다음 Phase 후보 — **하나만** 제안한다

### 트리거 계층 조건 UNKNOWN 원인 분리 (Trigger Condition UNKNOWN Cause Split)

- 대상: `TriggerCollector._judge` · `TriggerEligibilityJudge._trigger_condition` ·
  `TriggerChainIntegrator` 의 조건 `UNKNOWN` 분기 3곳 (전부 지금
  `INFORMATION_UNAVAILABLE` 고정)
- 하는 일: 이번 Phase 가 발동/해결 계층에 적용한 `missing_rules()` 갈래를
  **같은 방식으로** 트리거 계층에 적용한다. 새 구조 없음.
- 걸리는 것: 기존 테스트 2개가 현재 코드를 고정한다
  (`tests/engine/test_trigger.py:388` · `tests/engine/test_trigger_chain.py:291`).
  둘 다 `UnimplementedRule` 을 걸어 놓고 `INFORMATION_UNAVAILABLE` 을 단정하는
  — 이번에 `test_effect_execution.py` 에서 고친 것과 **똑같은** 가정이다.
- 왜 지금이 아닌가: 이번 Phase 의 §12 범위를 넘고, 잠든 계층이어서 production
  영향이 없다. 그러나 이어지는 날 반드시 함께 맞아야 한다.
- 왜 다음인가: 이번에 세운 갈래 규칙을 **저장소 전체에 일관되게** 적용하면
  "같은 사실을 계층마다 다른 코드로 말한다" 는 문제가 끝난다.

**이 Phase 는 여기서 멈춘다. 다음 Phase 는 임의로 진행하지 않는다.**
