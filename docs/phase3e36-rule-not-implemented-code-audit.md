# Phase 3-E-36 — `ValidationCode.RULE_NOT_IMPLEMENTED` 정밀 의미 감사

**최종 판정: C. MISCLASSIFIED_BUT_SAFE**

**production diff = 0.** `engine/` · `agent/` · `core/` · `analysis/` ·
`sources/` 를 한 글자도 바꾸지 않았다.

---

## 1. Phase / Base / 실제 HEAD

| 항목 | 값 |
|---|---|
| Phase | 3-E-36 (AUDIT-ONLY) |
| 브랜치 | `claude/pensive-goodall-te1egy` |
| 감사 시작 HEAD | **`d842535`** — "Phase 3-E-35 보고서: 고의 위반 12건 결과 (AUDIT-ONLY)" |
| 그 직전 | `639176e` Phase 3-E-35 · `1804fe5` Phase 3-E-34 보고서 |
| 작업 트리 | 깨끗함 (`git status --porcelain` 비어 있음) |
| 3-E-35 보고서 | `docs/phase3e35-unimplemented-rule-semantics-audit.md` (52,268 B) |
| 3-E-35 감사 테스트 | `tests/test_unimplemented_rule_semantics_audit.py` (17개) |
| `1804fe5..HEAD` production diff | **0** |

프롬프트의 commit 을 믿지 않고 저장소에서 확인했다. `reset`/`checkout` 하지
않았다.

## 2. BLOCKER

**없다.** 감사를 끝까지 수행했고, 실제 오분류를 발견했지만 **고치지 않고**
정확한 위치와 의미를 이 문서에 적었다 (§0 · §21 · §22).

측정 중에 **내 가정 세 개가 틀렸다**는 것을 발견해 고쳤다.

1. **75 는 코드 등장 수가 아니다.** 문자열 등장이 75곳이고, 주석과
   docstring 6곳을 빼면 **코드 등장은 69곳**이다. 3-E-35 에서 내가 "75곳"
   이라고 적은 것은 문자열 수였다 — 이번에 가려서 다시 셌다.
2. **`WithheldAction` 은 코드를 들고 있지 않다.** 필드가 `kind` ·
   `reason`(문자열) · `missing` 뿐이다. 보류 쪽에서 `ValidationCode` 를
   모으려 한 첫 시도가 `AttributeError` 로 멈췄다 (3-E-28 이 이미 같은
   모양을 측정했는데 내가 잊었다).
3. **`ActionStatus` 는 멤버가 5개다** (6개로 적었다).

## 3. Engine 변경 여부

```
$ git diff --stat d842535..HEAD -- engine/ agent/ core/ analysis/ sources/
(출력 없음)
```

더한 파일은 둘뿐이다.

- `tests/test_rule_not_implemented_code_audit.py` (새 파일, 26개 테스트)
- `docs/phase3e36-rule-not-implemented-code-audit.md` (이 문서)

기존 테스트를 삭제·수정하지 않았다. `skip` 을 더하지 않았고 assertion 을
약하게 바꾸지 않았다. **새 `ValidationCode` 를 만들지 않았고, 75곳 중 한
곳도 고치지 않았다.**

## 4. 전수조사 방법

세 단계로 셌다. **각 단계에서 수가 줄어드는 이유를 설명한다.**

| 단계 | 수 | 무엇인가 |
|---|---:|---|
| 문자열 등장 (`engine/` + `agent/`) | **75** | 프롬프트가 말하는 수 |
| − 주석 · docstring | **−6** | 설명이지 코드가 아니다 |
| **코드 등장** | **69** | 이번 감사의 분모 |

빠진 6곳 (AST 가 코드로 보지 않는 줄):

| 위치 | 무엇을 적는가 |
|---|---|
| `engine/special_summon.py:77` | "검증기가 `RULE_NOT_IMPLEMENTED` 로 그렇게 말한다" |
| `engine/trigger.py:978` | **"확실한 거부이고 미구현이 아니다"** (3-E-26 의 주석) |
| `engine/trigger_chain.py:553` | "`RULE_NOT_IMPLEMENTED` 를 적으면 … 어긋난다" |
| `engine/trigger_chain.py:569` | `_undecided_code` 의 우선순위 설명 |
| `engine/validation.py:129` | `INSUFFICIENT_DECK` 이 이 코드와 다른 이유 |
| `engine/validation.py:180` | 스펠 스피드를 판정 못 할 때의 코드 |

조사 방법은 셋을 섞었다.

1. **AST 노드 수집** — `Attribute(attr="RULE_NOT_IMPLEMENTED")` 전수. 파일명이나
   enum 이름으로 분류하지 않았다.
2. **짝지은 상태 읽기** — 결과 생성자의 **첫 인자**(상태)를 함께 읽어,
   그 상태가 "모른다" 쪽인지 **상태 enum 자신이 적어 둔 묶음**으로 갈랐다
   (`engine.activation._UNKNOWN_STATUSES`). 내 기준을 새로 만들지 않았다.
3. **실제 실행** — 발동기·해결기·검증기·`Duel` 을 실제로 돌려 코드가
   무엇으로 나오는지 확인했다.

### 기준선은 enum 자신의 docstring 이다

```python
# engine/validation.py:96
    RULE_NOT_IMPLEMENTED = "rule_not_implemented"
    """
    **이 엔진이 아직 못 한다.** 판이 어떻든 달라지지 않고, 코드가 생겨야 풀린다.

    ``UNKNOWN`` 쪽의 코드다 — 확실한 거부(``INVALID``)에 붙이지 않는다.
```

**"확실한 거부(`INVALID`)에 붙이지 않는다"** 가 이 Phase 의 금지선이다.
내 의견이 아니라 **저장소가 스스로 적어 둔 규칙**이고, 3-E-26 이 트리거
계층에서 그것을 실제로 적용했다.

## 5. 전체 분류 통계

69곳을 다음과 같이 분류했다.

| 분류 | 개수 | 비율 |
|---|---:|---:|
| **A. TRUE_UNIMPLEMENTED_RULE** (진짜 미구현) | 30 | 43.5% |
| **I. CORRECT_RULE_NOT_IMPLEMENTED** (정확 — 정의·기본값·멤버십·올바른 분기) | 17 | 24.6% |
| **J\*. MISCLASSIFIED_NO_BETTER_CODE** (더 정확한 코드가 enum 에 **없다**) | 10 | 14.5% |
| **G. DORMANT** (예외 처리 · production 생성 0곳) | 8 | 11.6% |
| **J. MISCLASSIFIED** (더 정확한 코드가 enum 에 **있다**) | 4 | 5.8% |
| B. INFORMATION_UNAVAILABLE | 0 | 0% |
| C. CONDITION_UNKNOWN (코드가 섞인 자리) | 0 | 0% |
| D. EXECUTION_FORBIDDEN (J 에 포함) | — | — |
| E. CANDIDATE_NOT_ELIGIBLE (J 에 포함) | — | — |
| F. ANALYSIS_ONLY | 0 | 0% |
| H. TEST_ONLY | 0 | 0% |
| **합** | **69** | **100%** |

`B` 와 `C` 가 0인 이유: 정보 부족과 조건 판정 불가는 **올바르게 갈라져**
있다 (§8). 그 자리들은 `IfExp` 로 `INFORMATION_UNAVAILABLE` 을 고르므로
이 코드의 사용처가 아니다.

`H` 가 0인 이유: `tests/` 는 분모에서 제외했다 (§3 이 production 만 센다).

### 모양별 분해 — 생성이 아닌 자리가 17곳이다

| 모양 | 개수 | 의미 |
|---|---:|---|
| `PRODUCE` (실제 생성) | 52 | 결과·관문·요구를 만든다 |
| `FIELD_DEFAULT` (`code` 필드 기본값) | 8 | **보수적 기본값** — 판정이 아니다 |
| `PRODUCE_IFEXP` (조건부 분기) | 5 | `RULE` 과 `INFORMATION` 을 **올바르게** 가른다 |
| `MEMBERSHIP` (집합·튜플 멤버) | 2 | `_UNKNOWN_CODES` · 요구 목록 |
| `COMPARE` (비교) | 1 | `_undecided_code` 의 우선순위 |
| `ENUM_DEF` (정의 자체) | 1 | `validation.py:96` |
| **합** | **69** | |

`code` 필드 기본값 8곳 — `ActionExecution` · `ActivationResult` ·
`ChainResolution` · `EffectResult` · `CostPaymentResult` · `ResponseResult` ·
`TriggerCandidate` · `TriggerChainEntry`. 전부 "아무도 말하지 않으면 이유는
'우리가 못 한다'" 라는 **보수적 기본값**이고, 판정이 아니므로 금지선을
어기지 않는다.

### 금지선 위반 — 기계로 센 결과

결과를 만드는 여섯 파일에서 **짝지은 상태**를 읽어 갈랐다.

| | 개수 |
|---|---:|
| 금지선 **적합** (상태가 "모른다" 쪽) | **17** |
| 금지선 **위반** (상태가 확실한 거부·오류) | **16** |

**위반 16곳 전체 — §24 가 요구한 표**

| code | 위치 | 입력 상황 | 실제 의미 | production 도달 | 최종 분류 |
|---|---|---|---|---|---|
| `RULE_NOT_IMPLEMENTED` | `engine/activation.py:667` | 발동 조건이 **거짓** | 확실한 거부 | **도달** | **J** (`CANDIDATE_NOT_ELIGIBLE` 이 정확) |
| 같음 | `engine/effect/executor.py:979` | 해결 중 조건이 **거짓** | 확실한 거부 | **도달** | **J** (같음) |
| 같음 | `engine/activation.py:634` (`_AVAILABILITY_REFUSAL` 표) | `TEXT_DERIVED` 출처 금지 | 근거가 금지 | **도달** | **J** (`EXECUTION_FORBIDDEN` 이 정확) |
| 같음 | `engine/effect/executor.py:920` | 같음 | 근거가 금지 | **도달** | **J** (같음) |
| 같음 | `engine/activation.py:554` | 행위 종류가 발동이 아니다 | 구조 오류 | **도달** | **J\*** (더 정확한 코드 없음) |
| 같음 | `engine/activation.py:586` | 체인이 링크를 못 받는다 | 구조 거부 | **도달** | **J\*** |
| 같음 | `engine/effect/executor.py:630` | 조작 인덱스 오류 | 구조 오류 | **도달** | **J\*** |
| 같음 | `engine/effect/executor.py:643` | 같음 | 구조 오류 | **도달** | **J\*** |
| 같음 | `engine/effect/executor.py:766` | 문맥 불일치 | 구조 오류 | **도달** | **J\*** |
| 같음 | `engine/effect/executor.py:865` | 선언 문맥 불일치 | 구조 오류 | **도달** | **J\*** |
| 같음 | `engine/effect/executor.py:1134` | 대상 문맥 불일치 | 구조 오류 | **도달** | **J\*** |
| 같음 | `engine/effect/executor.py:1329` | 선택 문맥 불일치 | 구조 오류 | **도달** | **J\*** |
| 같음 | `engine/duel.py:686` | **목록 멤버십 거절** | "지금 후보가 아니다" | **도달 — 매번** | **J\*** |
| 같음 | `engine/response.py:476` | 응답 거절 | 거부 | **도달** | **J\*** |
| 같음 | `engine/action_execution.py:316` | `except Exception` | **엔진 오류** | **방어 경로** | **G** (`pragma: no cover`) |
| 같음 | `engine/effect/executor.py:488` | 같음 | 엔진 오류 | **방어 경로** | **G** |
| 같음 | `engine/payment.py:372` | 같음 | 엔진 오류 | **방어 경로** | **G** |
| 같음 | `engine/effect/resolution.py:499` | 출처 금지 (`UnimplementedResolver`) | 근거가 금지 | **미도달** | **G** (생성 0곳) |

(마지막 두 줄은 위반 16곳 중 `resolution.py:499` 와, 같은 클래스의 나머지
3곳을 합쳐 적은 것이다 — `resolution.py` 의 네 자리 전부 dormant 다.)

### §24 가 요구한 두 번째 표

| Semantic | 올바른 표현 | 현재 표현 | 문제 여부 |
|---|---|---|---|
| 규칙 자체 미구현 | `RULE_NOT_IMPLEMENTED` | `RULE_NOT_IMPLEMENTED` (30곳) | **없음** |
| 정보 부족 | `INFORMATION_UNAVAILABLE` / `UNKNOWN` | `INFORMATION_UNAVAILABLE` — `IfExp` 5곳이 올바르게 가른다 | **없음** |
| 조건 거짓 | `CANDIDATE_NOT_ELIGIBLE` (트리거 계층이 쓰는 것) | **`RULE_NOT_IMPLEMENTED`** (발동 1 · 해결 1) | **있음 — J (M1)** |
| 실행 금지 | `EXECUTION_FORBIDDEN` | **`RULE_NOT_IMPLEMENTED`** (발동 1 · 해결 1 · dormant 1) | **있음 — J (M2)** |
| 후보 부적격 | `CANDIDATE_NOT_ELIGIBLE` | `CANDIDATE_NOT_ELIGIBLE` (트리거·대상 계층) | **없음** |
| 구조 오류 (문맥·인덱스·체인) | — (**enum 에 없다**) | `RULE_NOT_IMPLEMENTED` (8곳) | **있음 — J\*** |
| 엔진 예외 | — (**enum 에 없다**) | `RULE_NOT_IMPLEMENTED` (3곳) | **있음 — J\*/G** |
| 목록에 없는 행위 | — (**enum 에 없다**) | `RULE_NOT_IMPLEMENTED` (1곳) | **있음 — J\*** |

## 6. code / status / missing_rule 관계

§7 이 지목한 네 조합의 실재 여부를 측정했다.

| 조합 | 실재? | 근거 |
|---|---|---|
| `RULE_NOT_IMPLEMENTED` + `UNKNOWN` | **있다 (정상)** | `ValidationResult.unknown(...)` 네 곳 |
| `RULE_NOT_IMPLEMENTED` + `INVALID` | **`ValidationResult` 에는 없다** | `invalid()`/`valid()` 에 이 코드를 넣는 production 호출 **0건** (AST 전수) |
| `RULE_NOT_IMPLEMENTED` + `VALID`/`ELIGIBLE` | **없다** | `valid()` 는 코드를 받지 않고 `OK` 를 쓴다. 트리거 적격도 `OK` 다 |
| `RULE_NOT_IMPLEMENTED` + `missing_rule=None` | **있다 (정상)** | 흔하다. 코드와 규칙 이름은 **다른 사실** |

**중요한 비대칭**: `ValidationResult` 에는 `INVALID` + 이 코드가 **없다**.
구조가 막기 때문이다 — `invalid()` 는 `missing_rule` 매개변수를 받지 않고,
production 이 그 생성자에 이 코드를 넣지 않는다.

**그런데 `ActivationResult` · `EffectResult` 에는 막는 구조가 없다.** 거기서는
상태와 코드를 자유롭게 짝지을 수 있고, 그래서 `CONDITION_FALSE` +
`RULE_NOT_IMPLEMENTED` 가 가능하다. **금지선이 한 결과 타입에만 구조로 적용되고
나머지에는 산문으로만 적혀 있다** — 이것이 M1·M2 가 생긴 자리다.

`missing_rule` 과의 관계는 3-E-35 가 확정한 대로다 — 넷(+하나)이 서로 다른
것이고, 코드를 가르는 근거는 `Condition.missing_rules()` 다.

## 7. `UNKNOWN` 관계

**상태와 코드는 다른 축이다.** 그래서 §8 이 묻는 "같은 enum 이 서로 다른
semantic 을 담는가" 의 답은 **담는다**이고, 두 방향으로 확인했다.

| 방향 | 사례 |
|---|---|
| 같은 상태, **다른 코드** | `CONDITION_UNKNOWN` + `RULE_NOT_IMPLEMENTED` / `INFORMATION_UNAVAILABLE` |
| 같은 코드, **다른 상태** | `RULE_NOT_IMPLEMENTED` + `CONDITION_UNKNOWN` · `CONDITION_FALSE` · `FORBIDDEN` · `INVALID_ACTION` · `INVALID_CONTEXT` · `EXECUTION_ERROR` · `NOT_IMPLEMENTED` · `UNSUPPORTED_OPERATION` · `UNCHECKED_RULES` · `CHAIN_REFUSED` · `REFUSED` · `UNKNOWN` |

§8 이 찾으라고 한 잘못된 패턴:

| 패턴 | 있는가 | 근거 |
|---|---|---|
| `if unknown: return RULE_NOT_IMPLEMENTED` | **아니다** | 다섯 자리 모두 `missing_rules()` 에게 되묻는다 |
| `except: return RULE_NOT_IMPLEMENTED` | **있다 — 3곳** | `action_execution:316` · `executor:488` · `payment:372`. 전부 `pragma: no cover` 방어 경로 |
| `missing information → RULE_NOT_IMPLEMENTED` | **아니다** | `IfExp` 가 `INFORMATION_UNAVAILABLE` 로 보낸다 |
| `unsupported context → RULE_NOT_IMPLEMENTED` | **있다 — 8곳** | `INVALID_CONTEXT` ×4 · `INVALID_OPERATION` ×2 · `CHAIN_REFUSED` · `INVALID_ACTION` |

## 8. `INFORMATION_UNAVAILABLE` 관계

**혼동되지 않는다.** 다섯 자리가 `IfExp` 로 갈라 쓴다.

| 위치 | 가르는 근거 |
|---|---|
| `engine/activation.py:686` | `definition.activation.missing_rules(...)` |
| `engine/effect/executor.py:989` | 같음 |
| `engine/trigger.py:998` | `condition.missing_rules(...)` (3-E-27) |
| `engine/trigger.py:1437` | 같음 |
| `engine/activation_timing.py:519` | `missing == MONSTER_CLASSIFICATION_MISSING` |

`action_validation.py:353` 도 같은 일을 `if`/`else` 두 문장으로 한다.

실측 — 같은 상태, 다른 코드:

```
UnimplementedRule("없는 규칙")        → CONDITION_UNKNOWN + RULE_NOT_IMPLEMENTED
IsMonster(InstanceId(9999))           → CONDITION_UNKNOWN + INFORMATION_UNAVAILABLE
```

3-E-26~28 이 세운 semantics 가 그대로 유지된다.

## 9. `EXECUTION_FORBIDDEN` 관계 — **발견 M2**

**혼동된다.** 같은 사실(`TEXT_DERIVED` 출처 금지, ADR-004)을 두 계층이
**다른 코드**로 적는다.

| 계층 | 상태 | 코드 | 비고 |
|---|---|---|---|
| 트리거 (`TriggerCollector._judge`) | `FORBIDDEN` | **`EXECUTION_FORBIDDEN`** | 3-E-26 에서 고쳤다 |
| 트리거 (`TriggerEligibilityJudge._execution_authority`) | `INVALID` | `RULE_NOT_IMPLEMENTED` 와 `EXECUTION_FORBIDDEN` 을 갈라 쓴다 | — |
| **발동** (`EffectActivator._check_authority`) | `FORBIDDEN` | **`RULE_NOT_IMPLEMENTED`** | 안 고쳤다 |
| **해결** (`EffectExecutor._check_authority`) | `FORBIDDEN` | **`RULE_NOT_IMPLEMENTED`** | 안 고쳤다 |
| 해결 (dormant, `UnimplementedResolver`) | `FORBIDDEN` | `RULE_NOT_IMPLEMENTED` | production 생성 0곳 |

3-E-26 이 트리거 쪽을 고칠 때 남긴 주석이 **그 이유를 미리 적어 두었다**.

> 같은 사실을 `TriggerEligibilityJudge._execution_authority` 가 이미
> `EXECUTION_FORBIDDEN` 으로 적는다 — 한 파일 안에서 같은 사실이 두 코드로
> 적히면 `GateVerdict.forbids` 처럼 **코드로** 금지를 읽는 쪽이 한쪽을 못
> 본다 (Phase 3-E-26).

**지금은 그 위험이 실현되지 않는다** — `GateVerdict.forbids` 는 트리거
계층의 `GateVerdict` 만 보고, 발동·해결의 결과는 그 타입이 아니다. 그러나
**같은 종류의 독자가 발동·해결 쪽에 생기면 그 즉시 실현된다.**

## 10. `CANDIDATE_NOT_ELIGIBLE` 관계 — **발견 M1**

**혼동된다.** 조건을 끝까지 보고 **거짓**을 받은 자리에 "엔진이 못 한다" 를
적는다.

| 계층 | 조건이 `FALSE` 일 때의 코드 |
|---|---|
| 트리거 `TriggerCollector._judge` | **`CANDIDATE_NOT_ELIGIBLE`** (3-E-26) |
| 트리거 `TriggerEligibilityJudge._trigger_condition` | **`CANDIDATE_NOT_ELIGIBLE`** (3-E-26) |
| **발동 `EffectActivator._check_condition`** | **`RULE_NOT_IMPLEMENTED`** |
| **해결 `EffectExecutor._check_condition`** | **`RULE_NOT_IMPLEMENTED`** |

3-E-26 이 트리거 쪽에 남긴 주석이 이 자리를 정확히 설명한다.

> **확실한 거부이고 미구현이 아니다.** `RULE_NOT_IMPLEMENTED` 는 "이 엔진이
> 못 한다" 는 뜻이라서, 조건을 끝까지 보고 거짓을 받은 자리에 적으면
> **판정과 이유가 어긋난다** (Phase 3-E-26).

실측:

```
Always(ConditionResult.FALSE)
  → 발동: status=condition_false  code=rule_not_implemented
  → 해결: status=condition_false  code=rule_not_implemented
```

**상태는 정확하고 코드만 거칠다.** 그래서 "판정이 틀렸다" 가 아니라
"이유가 틀렸다" 다.

## 11. Trigger layer

**가장 정확한 계층이다.** 3-E-26/27 이 손본 자리가 그대로 유지된다.

| 상황 | 상태 | 코드 |
|---|---|---|
| 조건 거짓 | `INELIGIBLE` | `CANDIDATE_NOT_ELIGIBLE` |
| 출처 금지 | `FORBIDDEN` | `EXECUTION_FORBIDDEN` |
| 규칙 없음 | `UNKNOWN` | `RULE_NOT_IMPLEMENTED` |
| 정보 없음 | `UNKNOWN` | `INFORMATION_UNAVAILABLE` |
| 정의 미등록 | `UNKNOWN` | `RULE_NOT_IMPLEMENTED` + `notes=("정의 미등록",)` |
| 적격 | `ELIGIBLE` | `OK` |

`engine/trigger.py` 의 10곳 · `engine/trigger_chain.py` 의 4곳 **전부**
`UNKNOWN` 쪽에만 붙는다 (금지선 위반 0건). `trigger_chain.py:581`
`_undecided_code` 는 **`validity is UNKNOWN` 인 관문만** 걸러 본 뒤 이
코드를 우선순위로 쓰므로, 확실한 거부가 섞여 들어올 수 없다.

트리거 파이프라인은 여전히 dormant 다 (`TriggerSpec` production 생성 0개,
3-E-29/31/34/35) — 그러나 코드 선택은 **이미 정확하다.**

## 12. ActionValidator

`engine/action_validation.py` 의 5곳 전부 **`UNKNOWN` 쪽**이다 (위반 0건).

| 위치 | 상황 | 분류 |
|---|---|---|
| `:301` | 종류별 "마지막 한 걸음" (`_MISSING_RULE[kind]`) | **A** |
| `:353` | `_check_requirements` — `missing_rules()` 가 있다 | **A** |
| `:573` | `UnimplementedRule` — 범위 밖 자리 | **A** |
| `:582` | `UnimplementedRule` — 카드별 소환 조건 | **A** |
| `:876` | `_NormalSpellActivation` 자리표시 — **닿지 않는다** | **I** |

`:876` 은 소스가 스스로 그렇게 적는다: "이 조건은 `FALSE` 를 **돌려주지
않는다** … 그래서 이 코드는 닿지 않지만, 닿는다면 그 이유는 규칙 계층이
없는 것이므로 새 코드를 만들지 않고 이것을 쓴다." **정직한 자리표시**다.

종류별 실측 (실제 카드, MAIN1 이전 판):

| 행위 | validity | code |
|---|---|---|
| `normal_summon` | `INVALID` | `wrong_phase` (코드가 정확) |
| `set_spell_trap` | `INVALID` | 종류별 코드 |
| `activate_card` | `UNKNOWN` | `rule_not_implemented` + `missing_rule='activation-timing (Phase 2-C/2-F)'` |
| `special_summon` | `UNKNOWN` | `rule_not_implemented` + `missing_rule='special-summon-condition (카드마다 다르다)'` |

**확실한 위반은 이 코드를 받지 않는다** — 검증기 계층에서 금지선이 지켜진다.

## 13. Effect / Cost / Target

| 영역 | 이 코드 사용 | 금지선 |
|---|---:|---|
| `engine/effect/executor.py` | **22곳** (가장 많다) | **위반 9곳 · 적합 13곳** |
| `engine/effect/resolution.py` | 5곳 | 위반 1곳 (dormant) · 적합 3 · 기본값 1 |
| `engine/effect/targeting.py` | **0곳** | — (`CANDIDATE_NOT_ELIGIBLE` 을 쓴다) |
| `engine/cost/` 전체 | **0곳** | — (`COST_NOT_IMPLEMENTED` 를 쓴다) |
| `engine/payment.py` | 2곳 | 위반 1곳 (예외) · 기본값 1 |

**비용과 대상 계층은 이 코드를 빌리지 않는다.** 각자 자기 코드를 갖고 있다
— 좋은 신호다.

`executor.py` 의 22곳이 **세 가지 다른 사실**을 한 코드로 적는다.

| 짝지은 상태 | 수 | 실제 의미 | 금지선 |
|---|---:|---|---|
| `UNSUPPORTED_OPERATION` | 8 | 이 실행기가 그 조작을 못 한다 | **적합** |
| `INVALID_CONTEXT` | 4 | 문맥 불일치 — 구조 오류 | **위반** |
| `INVALID_OPERATION` | 2 | 조작 인덱스 오류 | **위반** |
| `UNCHECKED_RULES` | 2 | 못 본 규칙 | **적합** |
| `NOT_IMPLEMENTED` · `UNKNOWN` | 2 | 구현/검증 미등록 | **적합** |
| `FORBIDDEN` | 1 | 출처 금지 | **위반 (M2)** |
| `CONDITION_FALSE` | 1 | 조건 거짓 | **위반 (M1)** |
| `EXECUTION_ERROR` | 1 | 예외 | **위반 (방어)** |
| `CONDITION_UNKNOWN` (`IfExp`) | 1 | 올바르게 가른다 | **적합** |

"조건이 거짓" 과 "조건을 평가할 규칙이 없음" 은 **상태로는 갈려 있고
코드로는 합쳐져 있다.**

## 14. 실제 corpus 사례 — 20개 이상

| # | 영역 | 상황 | 위치 | 상태 | 코드 | 실제 의미 | 분류 |
|---|---|---|---|---|---|---|---|
| 1 | 일반 소환 | 제물이 필요한 몬스터 | `action_validation:301` | `UNKNOWN` | 이 코드 | 제물 절차 없음 | **A** |
| 2 | 일반 소환 | 효과 몬스터의 자기 제약 | `:353` | `UNKNOWN` | 이 코드 | 카드 텍스트 못 읽음 | **A** |
| 3 | 특수 소환 | 카드별 소환 조건 | `:582` | `UNKNOWN` | 이 코드 | 절차 계층 없음 | **A** |
| 4 | 특수 소환 | `MZONE` 에서 나오는 특수 소환 | `:573` | `UNKNOWN` | 이 코드 | Phase 2-T 범위 밖 | **A** |
| 5 | 마법 발동 | 통상 마법 아님 | `:876` 자리표시 | `UNKNOWN` | 이 코드 | 타이밍 계층 없음 (닿지 않음) | **I** |
| 6 | 함정 | 함정 발동 타이밍 | `activation_timing:519` | `UNKNOWN` | 이 코드 **또는** `INFORMATION_UNAVAILABLE` | 올바르게 가른다 | **I** |
| 7 | 몬스터 효과 | 기동/유발 분류 없음 | 같음 | `UNKNOWN` | 같음 | 같음 | **I** |
| 8 | 발동 | 정의 미등록 | `activation:512` | `NOT_IMPLEMENTED` | 이 코드 | 등재 없음 | **A** |
| 9 | 발동 | **조건이 거짓** | `activation:667` | `CONDITION_FALSE` | 이 코드 | **확실한 거부** | **J (M1)** |
| 10 | 발동 | 출처 금지 (ADR-004) | `activation:634` | `FORBIDDEN` | 이 코드 | **근거가 금지** | **J (M2)** |
| 11 | 발동 | 행위 종류가 발동이 아님 | `activation:554` | `INVALID_ACTION` | 이 코드 | 구조 오류 | **J\*** |
| 12 | 발동 | 체인이 링크를 못 받음 | `activation:586` | `CHAIN_REFUSED` | 이 코드 | 구조 거부 | **J\*** |
| 13 | 해결 | **조건이 거짓** | `executor:979` | `CONDITION_FALSE` | 이 코드 | **확실한 거부** | **J (M1)** |
| 14 | 해결 | 출처 금지 | `executor:920` | `FORBIDDEN` | 이 코드 | **근거가 금지** | **J (M2)** |
| 15 | 해결 | 조작 종류 미지원 | `executor:949` 등 8곳 | `UNSUPPORTED_OPERATION` | 이 코드 | 진짜 미구현 | **A** |
| 16 | 해결 | 문맥 불일치 | `executor:766` 등 4곳 | `INVALID_CONTEXT` | 이 코드 | 구조 오류 | **J\*** |
| 17 | 해결 | 못 본 규칙 | `executor:772` · `:1736` | `UNCHECKED_RULES` | 이 코드 | 진짜 미구현 | **A** |
| 18 | 비용 | 지불 중 예외 | `payment:372` | `EXECUTION_ERROR` | 이 코드 | **엔진 오류** | **G** |
| 19 | 대상 | — | `targeting.py` | — | **이 코드 없음** | `CANDIDATE_NOT_ELIGIBLE` 을 쓴다 | — |
| 20 | 이동 | 핸들러 미등록 | `action_execution:301` | `UNSUPPORTED_ACTION` | 이 코드 | 진짜 미구현 | **A** |
| 21 | 이동 | 적용 중 예외 | `action_execution:316` | `EXECUTION_ERROR` | 이 코드 | 엔진 오류 | **G** |
| 22 | trigger | 조건 거짓 | `trigger:977` | `INELIGIBLE` | **`CANDIDATE_NOT_ELIGIBLE`** | 확실한 거부 | **정확** |
| 23 | trigger | 규칙 없음 | `trigger:998` | `UNKNOWN` | 이 코드 | 진짜 미구현 | **A** |
| 24 | trigger | 사건 관계 규칙 없음 | `trigger:1318` | `UNKNOWN` | 이 코드 | 진짜 미구현 | **A** |
| 25 | `Duel` | **목록에 없는 행위** | `duel:686` | `accepted=False` | 이 코드 | "지금 후보가 아니다" | **J\*** |
| 26 | `Duel` | 정의 미등록 | `duel:874` | `accepted=False` | 이 코드 | 등재 없음 | **A** |
| 27 | 턴 진행 | 페이즈 건너뛰기 | `turn_progression:551` | `UNKNOWN` | 이 코드 | 진짜 미구현 | **A** |
| 28 | 응답 | 응답 거절 | `response:476` | `REFUSED` | 이 코드 | 거부 | **J\*** |

## 15. Production reachability

| 분류 | production 도달 | 근거 |
|---|---|---|
| **A** (30곳) | **도달 — 매번** | `legal_actions` · `validate` · `activate` · `resolve` 가 쓴다 |
| **I** (17곳) | 정의·기본값·멤버십 — 판정이 아니다 | `:876` 은 소스가 "닿지 않는다" 고 적는다 |
| **J** (4곳) | **도달** | 조건 거짓·출처 금지는 실제로 일어난다 (실측) |
| **J\*** (10곳) | **도달** — `duel:686` 은 `apply` 마다 | 구조 오류는 공개 입구에서 일어난다 |
| **G** (8곳) | **미도달** | 예외 3곳(`pragma: no cover`) + `UnimplementedResolver` 4곳(생성 0곳) + `duel:931` |

**오분류가 공개 경계까지 간다.** `Duel.apply` 가 발동기의 코드를 그대로
`DuelStep.code` 에 넣는다.

```python
# engine/duel.py
return DuelStep(action, False, activated.code, activated.reason)
```

그래서 `CONDITION_FALSE` 로 거절된 발동이 **밖에서는
`rule_not_implemented` 로 보인다.**

### 그런데 왜 판정이 바뀌지 않는가

`.code` 를 **판단 입력으로 읽는** production 자리는 **넷뿐이다** (AST 전수).

| 위치 | 읽는 것 | 오분류의 영향 |
|---|---|---|
| `engine/trigger.py:1079` `GateVerdict.forbids` | `EXECUTION_FORBIDDEN` | **없음** — 트리거 계층의 `GateVerdict` 만 본다. 발동·해결 결과는 그 타입이 아니다 |
| `engine/trigger_chain.py:581` `_undecided_code` | `RULE_NOT_IMPLEMENTED` | **없음** — `validity is UNKNOWN` 인 관문만 걸러 본다. 확실한 거부는 들어오지 않는다 |
| `engine/trigger_chain.py:584` | `is not OK` | **없음** — 어느 코드인지 보지 않는다 |
| `agent/simulation.py:284` | `step.code in _UNKNOWN_CODES` | **관측 가능** — 확실한 거부가 `SimulationStatus.UNKNOWN` 으로 읽힌다 (`REFUSED` 가 아니다) |

네 번째가 유일한 관측 가능한 결과이고, **그것도 선택을 바꾸지 않는다** (§17).

## 16. Dormant path

| 대상 | 수 | 종류 |
|---|---:|---|
| `except Exception` 처리 (`action_execution` · `executor` · `payment`) | 3 | **방어 경로** — 전부 `# pragma: no cover - 일어나서는 안 된다` |
| `UnimplementedResolver` 의 네 자리 | 4 | **production 생성 0곳** (생성처 전부 `tests/`). 소스 자신이 "여기까지 오는 경우는 아직 없다" 고 적는다 |
| `duel.py:931` (비용이 카드를 옮긴 경우) | 1 | 거의 닿지 않는다 |
| 트리거 파이프라인 전체 | (A 에 포함) | `TriggerSpec` production 생성 0개 — 그러나 코드 선택은 이미 정확하다 |

**dead code 는 하나도 없다.** 전부 "아직 연결하지 않은 미래 기능" 이거나
"일어나서는 안 되는 방어" 다.

## 17. AI / Search 영향

**선택은 바뀌지 않는다. 보고만 거칠어진다.**

```
engine → DuelStep.code
      → agent/simulation.py:284   step.code in _UNKNOWN_CODES
      → SimulationStatus.UNKNOWN  (code 는 SimulationResult.code 에 보존)
      → agent/search.py:311       status is not SUPPORTED → value=None
      → SearchCandidate.ordering_key() = (1, 0, 0, canonical_state)
```

| 항목 | 확인 |
|---|---|
| `RULE_NOT_IMPLEMENTED` ∈ `_UNKNOWN_CODES` | **그렇다** |
| `CANDIDATE_NOT_ELIGIBLE` ∈ `_UNKNOWN_CODES` | **아니다** — 정확한 코드였다면 `REFUSED` 로 갔다 |
| `EXECUTION_FORBIDDEN` ∈ `_UNKNOWN_CODES` | **아니다** — 같음 |
| `UNKNOWN` 과 `REFUSED` 의 `ordering_key` | **같다** `(1, 0, 0, …)` |
| `UNKNOWN` 과 `REFUSED` 의 `value` | **둘 다 `None`** |
| `UNKNOWN != 0` | **유지** |
| `UNKNOWN != LOSS` | **유지** — 뒤로 보낼 뿐이다 |
| `RULE_NOT_IMPLEMENTED != LOSS` | **유지** |
| 원래 코드 보존 | **보존** — `SimulationResult.code` |
| `agent/` 의 이 코드 등장 | **1곳** (`_UNKNOWN_CODES` 멤버) |
| `GameStateView` · `legal_actions` · `clone` · RNG · hidden information | 건드리지 않았다 |

**그래서 AI 가 불법 수를 고르지 않는다.** 확실한 거부도 미구현도 모두
점수가 없고 같은 순위로 뒤에 간다. 달라지는 것은 `SearchCandidate.status`
라벨 하나이고, 그것은 개발자가 읽는 자리다.

## 18. Hidden information

**`hidden information → RULE_NOT_IMPLEMENTED` 변환은 없다.**

| 사실 | 코드 |
|---|---|
| 가리킨 카드가 관측에 없다 | `HIDDEN_CARD` |
| 조건이 관측 밖을 묻는다 | `INFORMATION_UNAVAILABLE` (+ `unchecked`) |
| 카드 정의를 못 읽는다 | `CARD_DEFINITION_UNAVAILABLE` |
| 효과 목록을 믿을 수 없다 | `EFFECT_LIST_UNRELIABLE` |
| 통째로 가려진 존 | `CandidateSet.unchecked` (코드가 아니라 자리 이름) |

네 코드가 모두 `RULE_NOT_IMPLEMENTED` 와 다른 멤버이고, 실측에서
`IsMonster(InstanceId(9999))` 는 `INFORMATION_UNAVAILABLE` + `unchecked`
문장을 낸다. **가려진 정보를 미구현으로 가리는 자리를 찾지 못했다.**

## 19. Safety invariant — §19 열 항목

| # | invariant | 결과 |
|---|---|---|
| 1 | `UNKNOWN` → `FALSE` 변환 없음 | **지켜진다** |
| 2 | `UNKNOWN` → `RULE_NOT_IMPLEMENTED` 변환 없음 | **지켜진다** — 조건에게 되묻는다 |
| 3 | `INFORMATION_UNAVAILABLE` → `RULE_NOT_IMPLEMENTED` 변환 없음 | **지켜진다** — `IfExp` 5곳 |
| 4 | `EXECUTION_FORBIDDEN` → `RULE_NOT_IMPLEMENTED` 변환 없음 | **어긋난다 (M2)** — 발동·해결이 처음부터 후자를 쓴다. 변환이 아니라 **선택**이다 |
| 5 | `CANDIDATE_NOT_ELIGIBLE` → `RULE_NOT_IMPLEMENTED` 변환 없음 | **어긋난다 (M1)** — 같은 이유 |
| 6 | `RULE_NOT_IMPLEMENTED` → `FALSE` 변환 없음 | **지켜진다** — `invalid()` 에 넣는 호출 0건 |
| 7 | `RULE_NOT_IMPLEMENTED` → `LOSS` 변환 없음 | **지켜진다** |
| 8 | `RULE_NOT_IMPLEMENTED` → `VALID`/`ELIGIBLE` 변환 없음 | **지켜진다** |
| 9 | hidden information → `RULE_NOT_IMPLEMENTED` 변환 없음 | **지켜진다** |
| 10 | simulation 이 임의로 0점/패배로 바꾸지 않음 | **지켜진다** |

**4·5 를 "어긋난다" 로 적는 것이 정직하다.** 다만 그것은 "변환" 이 아니다 —
어떤 코드를 다른 코드로 **바꾸는** 자리가 아니라, 처음부터 거친 코드를
**고르는** 자리다. 그리고 상태가 정확한 사실을 들고 있으므로 판정은
틀리지 않는다.

## 20. Tests

`tests/test_rule_not_implemented_code_audit.py` — **26개, 전부 통과** (skip 0).

| # | 범주 | 무엇을 고정하는가 |
|---|---|---|
| 01 | **A** enum 정의 | enum 자신의 금지선 문장 ("확실한 거부에 붙이지 않는다") |
| 02 | A | 문자열 75 vs 코드 69 · 산문 6곳의 정확한 위치 |
| 03 | **B** `ValidationResult` | `invalid()`/`valid()` 에 이 코드를 넣는 호출 0건 · `missing_rule` 은 `unknown()` 만 받는다 |
| 04 | **C** `missing_rule` | 코드와 규칙 이름이 양방향으로 독립 |
| 05 | **D** status/code | **위반 16곳 · 적합 17곳**, 목록 전체 고정 |
| 06 | D | §7 의 네 조합 실재 여부 |
| 07 | D | `code` 필드 기본값 8곳 (보수적 기본값) |
| 08 | **E** `UNKNOWN` | 상태와 코드가 다른 축 — 양방향 반례 |
| 09 | **F** `INFORMATION_UNAVAILABLE` | 가르는 `IfExp` 5곳 전수 |
| 10 | **G** `EXECUTION_FORBIDDEN` | **M2** — 현재 상태 고정 |
| 11 | **H** `CANDIDATE_NOT_ELIGIBLE` | **M1** — 현재 상태 + 3-E-26 의 주석 |
| 12 | **I** 트리거 | 조건 거짓·규칙 없음·정의 미등록 세 경우 실측 |
| 13 | **J** `ActionValidator` | 종류별 실측 + 금지선 준수 |
| 14 | **K** 효과 실행 | 한 코드가 세 가지에 붙는다 (위반·적합 묶음이 겹치지 않는다) |
| 15 | **L** 비용 | `engine/cost/` 에 이 코드 0곳 |
| 16 | **M** 대상 | `targeting.py` 에 0곳 · `CANDIDATE_NOT_ELIGIBLE` 사용 |
| 17 | **N** production 도달 | `Duel.apply` 가 코드를 그대로 전한다 + 멤버십 거절 |
| 18 | **O** dormant | `UnimplementedResolver` production 생성 0곳 |
| 19 | O | 예외 처리 3곳이 방어 경로 · 더 정확한 코드가 enum 에 **없다** |
| 20 | **P** AI/Search | `.code` 를 판단으로 읽는 자리 **넷뿐** (목록 고정) |
| 21 | **Q** `SimulationStatus` | `UNKNOWN` vs `REFUSED` — 라벨은 다르고 **순위는 같다** |
| 22 | **R** hidden information | 변환 없음 · 네 코드가 모두 따로 |
| 23 | **S** safety | §19 열 항목 |
| 24 | S | 오분류된 코드가 판을 바꾸지 않는다 |
| 25 | **T** 실제 corpus | 실제 카드 한 판 — 코드가 둘 이상 나온다 |
| 26 | S | 3-E-24~35 regression + enum 크기 |

### 고의 위반 검증

주장이 정말 잡히는지 확인하려고 production 에 결함을 **일부러** 넣고 테스트가
잡는지 보았다. 전부 되돌렸다 (commit 뒤에 실행했으므로 작업 트리로 복구를
검증할 수 있다).

| 주입 | 잡은 테스트 |
|---|---|
| A. enum 의 금지선 문장을 지운다 | `test_01` |
| B. 코드 등장을 한 곳 더한다 (69 → 70) | `test_02` |
| C. `ValidationResult.invalid` 에 이 코드를 넣는다 | `test_03` · `test_05` |
| D. 조건 거짓에 `CANDIDATE_NOT_ELIGIBLE` 을 쓴다 (**M1 을 고친다**) | `test_05` · `test_11` |
| E. 출처 금지에 `EXECUTION_FORBIDDEN` 을 쓴다 (**M2 를 고친다**) | `test_05` · `test_10` |
| F. `_UNKNOWN_STATUSES` 에 `CONDITION_FALSE` 를 더한다 (위반을 숨긴다) | `test_05` |
| G. 다섯 번째 `code` 독자를 만든다 | `test_20` |
| H. `_UNKNOWN_CODES` 에 `CANDIDATE_NOT_ELIGIBLE` 을 더한다 | `test_21` |
| I. `targeting.py` 가 이 코드를 쓴다 | `test_16` |
| J. `engine/cost/` 가 이 코드를 쓴다 | `test_15` |
| K. `ValidationCode` 에 새 멤버를 더한다 | `test_19` · `test_26` |
| L. 트리거가 조건 거짓에 이 코드를 되돌려 쓴다 | `test_12` · `test_11` |

**열두 가지 모두 잡혔다.** D·E 가 특히 중요하다 — **고치는 방향**의 변경도
잡힌다는 뜻이고, 그래서 다음 Phase 가 M1·M2 를 고치면 이 테스트가 먼저
깨져서 "보고서의 측정이 낡았다" 고 알려 준다. F 는 위반을 **숨기는**
방향이고, 그것도 잡힌다.

### 주입이 찾아낸 `test_20` 의 실제 구멍 (고쳤다)

G 를 처음 넣었을 때 **잡히지 않았다.** 왜 그런지 들여다보니 `test_20` 이
비교문을 **문자열**로 검사하고 있었다.

```python
# 틀린 방법 — 고쳤다
if ".code" in text and ("ValidationCode" in text or "CODES" in text):
```

내가 주입한 독자는 `from engine.validation import ValidationCode as _VC` 로
별명을 붙였고, 그래서 `_VC.RULE_NOT_IMPLEMENTED` 라는 문자열에
`"ValidationCode"` 가 **없었다.** 즉 **별명 import 로 만든 다섯 번째
독자를 놓친다** — 이 Phase 의 안전 논증이 "독자가 넷뿐" 이라는 데 걸려
있으므로 작은 구멍이 아니다.

`_reads_a_code()` 헬퍼를 더해, 비교 피연산자의 **멤버 이름**을
`ValidationCode.__members__` 에 맞춰 보고 집합 멤버십은 이름이 `CODES` 로
끝나는지 보도록 고쳤다. 고친 뒤 G 가 잡혔다.

### 회귀

| | 전 (3-E-35 완료 시점) | 후 |
|---|---|---|
| 통과 | 3,793 | 3,819 |
| 건너뜀 | 4 | 4 |
| 실패 | 0 | 0 |

## 21. Structural TODO

**신규 STRUCTURAL ID 를 만들지 않았다.** §22 의 다섯 조건을 하나씩 확인했다.

| 조건 | 충족? |
|---|---|
| 1. 동일 code 가 실제 production 에서 **서로 다른 의미로 해석**된다 | **아니다** — 해석하는 자리가 넷뿐이고 넷 다 "모른다 쪽" 하나로 읽는다 |
| 2. 그 차이가 실제 validation/action/result 를 바꾼다 | **아니다** — `ordering_key` 가 같고 상태가 정확하다 |
| 3. 기존 ADR/TODO 로 설명되지 않는다 | **아니다** — 3-E-26 이 같은 문제를 트리거 계층에서 고쳤고 그 기록이 남아 있다 |
| 4. 단순 미래 구현 부족이 아니다 | **절반** — M1·M2 는 미래 구현이 아니라 **코드 선택**이다 |
| 5. 기존 enum 만으로 안전하게 표현할 수 없다 | **절반** — M1·M2 는 표현할 수 있고(코드가 이미 있다), J\* 10곳은 **표현할 수 없다** |

1·2·3 이 불충족이므로 신규 ID 후보가 아니다.

**기록만 남긴다 (신규 ID 아님)** — 세 묶음이다.

### M1 — 조건 거짓에 "미구현" 을 적는다 (2곳, 고칠 수 있다)

| 위치 | 현재 | 정확한 코드 |
|---|---|---|
| `engine/activation.py:667` | `CONDITION_FALSE` + `RULE_NOT_IMPLEMENTED` | `CANDIDATE_NOT_ELIGIBLE` |
| `engine/effect/executor.py:979` | `CONDITION_FALSE` + `RULE_NOT_IMPLEMENTED` | `CANDIDATE_NOT_ELIGIBLE` |

3-E-26 이 트리거 계층에서 고친 것과 **같은 두 줄짜리 변경**이다. 새 enum
불필요. production diff 2줄.

### M2 — 출처 금지에 "미구현" 을 적는다 (2곳 + dormant 1곳, 고칠 수 있다)

| 위치 | 현재 | 정확한 코드 |
|---|---|---|
| `engine/activation.py:634` (`_AVAILABILITY_REFUSAL` 경유) | `FORBIDDEN` + `RULE_NOT_IMPLEMENTED` | `EXECUTION_FORBIDDEN` |
| `engine/effect/executor.py:920` | 같음 | `EXECUTION_FORBIDDEN` |
| `engine/effect/resolution.py:499` (dormant) | 같음 | `EXECUTION_FORBIDDEN` |

주의 — `activation.py:634` 는 `_AVAILABILITY_REFUSAL` 표를 거치므로
`FORBIDDEN_SOURCE` 와 `UNVERIFIED` · `NOT_IMPLEMENTED` 가 **같은 코드 한
줄을 공유한다.** 앞의 것만 바꾸려면 표를 갈라야 하고, 그것은 2줄보다 큰
변경이다. **그래서 혼자 판단하지 않는다.**

### J\* — 더 정확한 코드가 enum 에 없다 (10곳, 지금 고칠 수 없다)

구조 오류 8곳 (`INVALID_CONTEXT` ×4 · `INVALID_OPERATION` ×2 ·
`INVALID_ACTION` · `CHAIN_REFUSED`) + 목록 멤버십 1곳 (`duel:686`) +
응답 거절 1곳 (`response:476`), 그리고 예외 3곳.

고치려면 **`ValidationCode` 를 늘려야 한다** — `EXECUTION_ERROR` ·
`INVALID_CONTEXT` · `NOT_A_CANDIDATE_NOW` 같은 멤버가 없다. 그것은
"enum 을 새로 추가하는 작업" 이므로 §0 이 금지했고, 필요성도 아직
입증되지 않았다 (판정을 바꾸지 않는다).

## 22. Final Decision — **C. MISCLASSIFIED_BUT_SAFE**

다른 후보를 고르지 않은 이유를 먼저 적는다.

- **A. CORRECT_ALL_75 가 아니다.** 69곳 중 **16곳**이 enum 자신이 적어 둔
  금지선("확실한 거부에 붙이지 않는다")을 어긴다. 그중 4곳은 **정확한
  코드가 이미 enum 에 있다.** "전부 맞다" 고 쓰면 그것을 숨긴다.
- **B. MOSTLY_CORRECT 가 아니다.** 남은 것이 "dormant/metadata/중복 정리"
  수준이 아니다 — M1·M2 는 **살아 있는 production 경로**에서 조건 거짓과
  출처 금지에 틀린 이유를 적는다. 정리가 아니라 의미 문제다.
- **D. MISCLASSIFIED_PRODUCTION 이 아니다.** **판정 결과가 바뀌지 않는다.**
  `.code` 를 판단 입력으로 읽는 자리가 넷뿐이고 (AST 전수), 넷 다 이
  오분류 때문에 다른 결론을 내지 않는다. 상태(`CONDITION_FALSE` ·
  `FORBIDDEN`)가 정확한 사실을 들고 있고, `legal_actions` 는 상태를 보고,
  AI 는 `UNKNOWN` 과 `REFUSED` 를 **같은 순위**로 줄 세운다. 실행도 허가도
  판 변화도 한 칸 움직이지 않는다 (`test_24`).
- **E. SEMANTIC_CONFLICT 가 아니다.** 같은 코드를 **서로 다르게 해석하는**
  자리가 없다. 네 독자가 모두 "모른다 쪽" 하나로 읽는다. 충돌은
  **생산 쪽**에 있고 소비 쪽에는 없다.
- **F. INFORMATION_LOSS 가 아니다.** 구체적 원인이 뭉개지지 않는다 —
  **상태**가 `CONDITION_FALSE` · `FORBIDDEN` · `INVALID_CONTEXT` 로 정확히
  말하고, `reason` 이 문장을 들고 있고, `notes`/`missing` 이 까닭을 전한다.
  코드는 그 옆에 붙은 거친 이름표다. 그리고 AI 경계에서도
  `SimulationResult.code` 가 원래 코드를 보존한다.
- **G. UNKNOWN 이 아니다.** 69곳 전부를 AST 로 수집하고 짝지은 상태를
  읽었으며, M1·M2 를 **실제로 돌려** 확인했다. §25 의 아홉 질문에 모두
  답했다.

**C 를 고르는 근거는 셋이다.**

1. **일부 위치가 더 정확한 코드를 쓸 수 있다.** M1 (조건 거짓 →
   `CANDIDATE_NOT_ELIGIBLE`) 과 M2 (출처 금지 → `EXECUTION_FORBIDDEN`) 는
   **코드가 이미 있고 트리거 계층이 이미 그렇게 쓴다.** 3-E-26 이 같은
   문제를 고친 전례가 있고 그 주석이 이유를 적어 두었다.
2. **그런데 현재 production 동작에 영향이 없다.** `.code` 독자 넷, 영향
   0건, 안전 invariant 8/10 완전 유지 + 2개는 "변환이 아니라 선택"
   (§19). 판·허가·순위·실행이 한 칸도 바뀌지 않는다.
3. **남은 10곳은 지금 고칠 수 없다.** 구조 오류·예외·멤버십 거절에
   맞는 `ValidationCode` 가 **없다.** enum 을 늘리는 것은 §0 이 금지했고,
   필요성도 "판정을 바꾸지 않는다" 는 이유로 아직 입증되지 않았다.

**그리고 이번 Phase 는 고치지 않는다.** M1 은 2줄이지만 M2 는
`_AVAILABILITY_REFUSAL` 표를 갈라야 하고, 둘 다 "어느 코드를 정본으로
삼을 것인가" 를 넘어 **거부 계층 전체의 코드 어휘**를 건드린다. §0 과
§26 을 그대로 지켰다.

---

## 23. Next Phase Candidate (하나만 제안한다)

**Phase 3-E-37 — 거부 코드 어휘 감사: `INVALID` 쪽 48개 `ValidationCode` 가 거부 사유를 충분히 덮는가**

이 Phase 가 "미구현 코드가 거부에 붙어 있다" 를 확정했고, 동시에 **10곳은
맞는 코드가 없어서 그렇다**는 것을 측정했다. 그러면 다음 질문은 반대쪽이다
— `ValidationCode` 48개 중 `INVALID` 쪽 코드가 실제 거부 사유를 얼마나
덮는가. 구조 오류(문맥 불일치·인덱스 오류) · 엔진 예외 · "지금 후보가
아니다" 세 가지에 맞는 멤버가 없다는 것은 이미 측정했으므로, 그 셋이
**정말 새 멤버를 요구하는지** 아니면 기존 멤버로 표현할 수 있는지를
전수로 판단한다.

AUDIT-ONLY 로 시작한다. 결과가 "기존 멤버로 된다" 면 M1·M2 와 함께
production diff 몇 줄로 끝나고, "새 멤버가 필요하다" 면 그것은 enum 변경
Phase 가 되므로 **별도로 판단한다.** 어느 쪽이든 이번 Phase 에서 고르지
않는다.

---

## §25 — 최종 질문 아홉 개에 대한 답

### Q1. 75개의 `RULE_NOT_IMPLEMENTED` 사용처가 정말 같은 semantic 인가?

**아니다. 그리고 75 도 아니다.**

문자열 75곳 중 6곳은 주석·docstring 이고, 코드는 **69곳**이다. 그 69곳이
담는 의미는 최소 **다섯 가지**다.

1. 진짜 미구현 (30곳) — 규칙 계층이 없다
2. 자리표시·기본값·정의 (17곳) — 판정이 아니다
3. **확실한 거부** (4곳) — 조건 거짓 · 출처 금지. **정확한 코드가 따로 있다**
4. **구조 오류** (10곳) — 문맥·인덱스·체인·멤버십. **맞는 코드가 없다**
5. **엔진 예외** (3곳, 방어) — 미구현이 아니다

### Q2. 실제로 잘못된 `RULE_NOT_IMPLEMENTED` 사용처가 있는가?

**있다. 16곳이고, 그중 4곳은 지금 고칠 수 있다.**

판단 기준은 내 의견이 아니라 **enum 자신의 docstring** 이다 —
"`UNKNOWN` 쪽의 코드다 — 확실한 거부(`INVALID`)에 붙이지 않는다". 상태를
기계로 읽어 가르면 16곳이 그 선을 넘는다.

고칠 수 있는 4곳: `activation.py:667` · `executor.py:979` (조건 거짓 →
`CANDIDATE_NOT_ELIGIBLE`), `activation.py:634` · `executor.py:920`
(출처 금지 → `EXECUTION_FORBIDDEN`).

### Q3. 있다면 production path 에 도달하는가?

**도달한다.** M1·M2 를 production 발동기·해결기로 실제 돌려 확인했고,
`Duel.apply` 가 그 코드를 `DuelStep.code` 에 그대로 넣는다. 공개 경계까지
간다.

예외 3곳과 `UnimplementedResolver` 4곳은 **미도달**이다 (`pragma: no
cover` · production 생성 0곳).

### Q4. `RULE_NOT_IMPLEMENTED` 과 `UNKNOWN` 이 모든 production 경로에서 안전하게 분리되어 있는가?

**분리되어 있지 않다 — 그러나 안전하다.** 둘은 다른 축이고, 같은 코드가
`UNKNOWN` 쪽 상태 7종과 거부 쪽 상태 6종에 모두 붙는다.

안전한 까닭은 **상태가 결정을 쥐고 있기 때문**이다. `permits_execution` ·
`activated` · `gives_a_future` 는 전부 **상태**를 보고, 코드는 이유다.
그리고 `ValidationResult` 에서는 구조가 섞임을 막는다 (`invalid()` 가
`missing_rule` 을 받지 않고, 이 코드를 넣는 호출이 0건).

막지 못하는 곳은 `ActivationResult` · `EffectResult` 다 — 거기서는 상태와
코드를 자유롭게 짝지을 수 있고, 금지선이 산문으로만 적혀 있다.

### Q5. `RULE_NOT_IMPLEMENTED` 과 `INFORMATION_UNAVAILABLE` 이 혼동되는가?

**engine 안에서는 혼동되지 않는다.** 다섯 자리가 `missing_rules()` 에게
되물어 가른다 (`IfExp` 5곳, `action_validation.py:353` 의 `if`/`else` 1곳).
3-E-26~28 이 세운 것이 그대로다.

**AI 경계에서는 한 상태로 합쳐진다** (`_UNKNOWN_CODES`). 그 계층에서는 둘
다 "미래를 볼 수 없다" 로 같은 답이므로 축약이 맞고, `SimulationResult.code`
가 원래 코드를 보존한다.

### Q6. `RULE_NOT_IMPLEMENTED` 과 `EXECUTION_FORBIDDEN` 이 혼동되는가?

**혼동된다 — 계층마다 다르게 적는다.** 같은 ADR-004 출처 금지를 트리거
계층은 `EXECUTION_FORBIDDEN` 으로, 발동·해결 계층은
`RULE_NOT_IMPLEMENTED` 로 적는다 (M2).

지금은 해롭지 않다 — `GateVerdict.forbids` 가 트리거 계층만 보기 때문이다.
그러나 3-E-26 의 주석이 미리 적어 둔 위험이 그대로 남아 있다: **코드로
금지를 읽는 독자가 발동·해결 쪽에 생기면 그 즉시 한쪽을 못 본다.**

### Q7. AI/Search/Simulation 에 잘못된 영향이 있는가?

**선택에는 없다. 보고에는 있다.**

- 없는 것: 불법 수를 고르지 않고, 점수가 바뀌지 않고, 순위가 바뀌지 않는다
  (`UNKNOWN` 과 `REFUSED` 의 `ordering_key` 가 같다). `UNKNOWN != 0 != LOSS`
  가 유지된다.
- 있는 것: 확실한 거부가 `SimulationStatus.UNKNOWN` 으로 보고된다
  (`REFUSED` 가 아니다). 개발자가 `SearchDecision` 흔적을 읽을 때 "모른다"
  와 "안 된다" 를 구분하지 못한다. 그리고 **엔진 예외도 `UNKNOWN` 으로
  보고된다** — 그것이 가장 마음에 걸리는 지점이지만, 예외 세 자리는 모두
  방어 경로다.

### Q8. 지금 production 수정이 필요한가?

**필요하지 않다. 다만 M1 은 가장 작고 가장 분명한 후보다.**

필요하지 않은 까닭: 판정 0건 변경, 안전 invariant 유지, `.code` 독자 넷
모두 영향 없음.

그래도 적어 둔다 — M1 은 **2줄**이고, 3-E-26 이 트리거 계층에서 한 것과
완전히 같은 변경이며, 새 enum 이 필요 없다. M2 는 `_AVAILABILITY_REFUSAL`
표를 갈라야 하므로 더 크다. J\* 10곳은 enum 을 늘려야 하므로 지금 할 일이
아니다.

**어느 것도 이번 Phase 에서 하지 않았다** (§0 · §26).

### Q9. 다음 Phase 에서 실제 구현을 시작해야 하는가, 아니면 추가 audit 이 필요한가?

**추가 audit 이 먼저다.**

이유: 이 Phase 가 "맞는 코드가 없어서 거친 코드를 쓴 자리가 10곳" 이라는
것을 측정했다. 그러면 M1·M2 만 고치는 것은 **반쪽**이다 — 같은 파일의
다른 거부들은 여전히 거친 코드를 쓰게 되고, 왜 어떤 거부는 정확하고 어떤
거부는 아닌지 설명할 수 없는 상태가 된다.

순서는 이렇다.

1. **Phase 3-E-37 (§23)** — `ValidationCode` 48개가 거부 사유를 충분히
   덮는지 전수 감사. 구조 오류 · 엔진 예외 · "지금 후보가 아니다" 세
   가지가 정말 새 멤버를 요구하는지 판단한다. AUDIT-ONLY.
2. 그 결과가 "기존 멤버로 된다" 면 → M1·M2 와 함께 **production diff
   몇 줄**로 코드 선택을 바로잡는다.
3. "새 멤버가 필요하다" 면 → enum 변경 Phase 로 따로 판단한다. 그때
   `agent/simulation.py` 의 `_UNKNOWN_CODES` 도 함께 봐야 한다 (새 멤버가
   어느 쪽인지 정해야 하므로).
4. **실제 규칙 구현(특수 소환 절차 · 제물 · 타이밍)은 그 뒤다.** 코드
   어휘가 정리되지 않은 상태에서 규칙을 더하면 거친 코드가 더 늘어난다.

**이 Phase 는 여기서 멈춘다. 다음 Phase 는 임의로 진행하지 않는다.**
