# Phase 3-E-37 — `ValidationCode` 거부 코드 의미 정밀 감사

**최종 판정: D. EXISTING_CODE_CAN_FIX**

**production diff = 0.** `engine/` · `agent/` · `core/` · `analysis/` ·
`sources/` 를 한 글자도 바꾸지 않았고, **새 `ValidationCode` 를 만들지 않았다.**

---

## 1. Phase / Base / 실제 HEAD

| 항목 | 값 |
|---|---|
| Phase | 3-E-37 (AUDIT-ONLY) |
| 브랜치 | `claude/pensive-goodall-te1egy` |
| 감사 시작 HEAD | **`279d785`** — "Phase 3-E-36 보고서: 고의 위반 12건 + test_20 의 실제 구멍 수정 (AUDIT-ONLY)" |
| 그 직전 | `2abf797` Phase 3-E-36 · `d842535` Phase 3-E-35 보고서 |
| 작업 트리 | 깨끗함 (`git status --porcelain` 비어 있음) |
| 3-E-36 보고서 | `docs/phase3e36-rule-not-implemented-code-audit.md` (49,314 B) |
| 3-E-36 감사 테스트 | `tests/test_rule_not_implemented_code_audit.py` (26개) |
| `d842535..HEAD` production diff | **0** |

프롬프트의 commit 을 믿지 않고 저장소에서 확인했다. `reset`/`checkout` 하지
않았다.

## 2. BLOCKER

**없다.** 감사를 끝까지 수행했고, 새 semantic mismatch(M3)를 발견했지만
**고치지 않고** 정확한 위치와 결과를 기록했다 (§0 · §19 · §27).

이번에도 **틀린 전제와 내 과거 측정 오류 넷**을 발견해 고쳤다.

1. **"48개 rejection usage" 는 틀린 수다.** 48 은 **`ValidationCode` 멤버
   수**이고 사용처 수가 아니다. 거부를 **만드는** 자리는 **58곳**이다 (§5).
2. **3-E-36 의 모양 분류에 한 칸 오차가 있었다.** 거기서 `MEMBERSHIP` 2곳
   으로 센 것(`action_validation.py:865` · `executor.py:1735`)은 **감싸는
   튜플의 줄 번호**였고, 코드가 실제로 적힌 줄(876 · 1737)은 **생성**이다.
   줄 기준으로 다시 세면 생성 58 · 멤버십 1 이고, 합은 69 로 같다.
3. **3-E-36 이 `engine/trigger.py:1318` 을 잘못 분류했다.** "A. 진짜
   미구현" 으로 적었는데, 실제로는 **`ActionValidity.INVALID` 관문에 붙은
   "모른다" 코드**다 — 이번 Phase 의 M3 다 (§8).
4. **3-E-36 의 "`invalid()` 에 이 코드를 넣는 호출 0건" 은 리터럴에만
   참이었다.** `_check_requirements` 가 `requirement.code` 를
   `ValidationResult.invalid(...)` 로 **간접 전달**한다 (§10).
5. **`ValidationResult` 에는 `value` 와 `ordering_key` 가 없다.** 프롬프트
   §13 이 그 둘을 함께 적지만, 그것은 `SearchCandidate` 의 것이다.
   `ValidationResult` 는 다섯 칸이다 (§10).

## 3. Engine 변경 여부

```
$ git diff --stat 279d785..HEAD -- engine/ agent/ core/ analysis/ sources/
(출력 없음)
```

더한 파일은 둘뿐이다.

- `tests/test_validation_code_rejection_semantics_audit.py` (새 파일, 31개 테스트)
- `docs/phase3e37-validation-code-rejection-semantics-audit.md` (이 문서)

기존 테스트를 삭제·수정하지 않았다. `skip` 을 더하지 않았고 assertion 을
약하게 바꾸지 않았다. **새 enum 멤버를 하나도 만들지 않았고 코드 선택을 한
줄도 바꾸지 않았다.**

## 4. `ValidationCode` 전체 enum

**48개 멤버 · 생성 총 251회 · 생성 0회 멤버 0개.** 죽은 멤버가 없다.

### 결정적 사실 1 — enum 이 **섹션 주석으로 validity 를 선언한다**

```python
class ValidationCode(str, Enum):
    OK = "ok"
    # --- 구조 (INVALID) ---            11개
    # --- 판 위의 사실 (INVALID) ---     12개
    # --- 모른다 (UNKNOWN) ---           5개   ← RULE_NOT_IMPLEMENTED 가 여기
    # --- 비용 · 선택 (Phase 2-C) ---     8개
    # --- 효과 실행 (Phase 2-D-2) ---     2개
    # --- 우선권 · 응답 기회 (Phase 2-F-1) --- 5개  ← EXECUTION_FORBIDDEN 이 여기
    # --- 일반 소환 (Phase 2-I) ---       2개
    # --- 발동 타이밍 · 스펠 스피드 (Phase 2-S) --- 2개
```

합이 `1 + 47 = 48` 이다. **이 Phase 의 측정 기준은 내 의견이 아니라 이
선언이다.**

`# --- 모른다 (UNKNOWN) ---` 묶음 5개: `HIDDEN_CARD` ·
`INFORMATION_UNAVAILABLE` · `CARD_DEFINITION_UNAVAILABLE` ·
`EFFECT_LIST_UNRELIABLE` · **`RULE_NOT_IMPLEMENTED`**.

### 결정적 사실 2 — **45개 코드는 한 번도 비교되지 않는다**

| | 수 |
|---|---:|
| 멤버 총수 | 48 |
| `.code` 를 **판단 입력으로** 비교할 때 등장하는 멤버 | **3** (`OK` · `RULE_NOT_IMPLEMENTED` · `EXECUTION_FORBIDDEN`) |
| `_UNKNOWN_CODES` 집합으로 간접 읽히는 멤버 | 5 |
| 어느 쪽으로도 읽히지 않는 멤버 | **≥ 40** |

> **코드는 거의 전부 보고용이고, 결정은 `status`/`validity` 가 쥐고 있다.**

이것이 "오분류가 판정을 바꾸지 않는" **구조적** 이유이고, 동시에 "새 enum 이
필요하지 않다" 의 근거다 (§19 · §20).

### 멤버별 요약 (생성 횟수 상위)

| 멤버 | 선언 묶음 | 생성 | 비교 |
|---|---|---:|---:|
| `RULE_NOT_IMPLEMENTED` | 모른다 (UNKNOWN) | 62 | **1** |
| `OK` | (묶음 밖) | 32 | **1** |
| `INFORMATION_UNAVAILABLE` | 모른다 (UNKNOWN) | 13 | 0 |
| `TOO_FEW_SELECTED` | 비용 · 선택 | 11 | 0 |
| `WRONG_PHASE` | 판 위의 사실 (INVALID) | 9 | 0 |
| `NOT_TURN_PLAYER` · `SOURCE_NOT_CONTROLLED` · `SOURCE_WRONG_ZONE` | 판 위의 사실 (INVALID) | 7 each | 0 |
| `CANDIDATE_NOT_ELIGIBLE` · `COST_NOT_IMPLEMENTED` | 비용 · 선택 | 7 each | 0 |
| `EXECUTION_FORBIDDEN` | 우선권 · 응답 기회 | 4 | **1** |
| … (나머지 38개) | — | 1~6 | 0 |

## 5. `RULE_NOT_IMPLEMENTED` 실제 occurrence 수

**프롬프트의 "48개 rejection usage" 는 enum 크기였다.** 다시 셌다.

| 단계 | 수 |
|---|---:|
| 문자열 등장 (`engine/` + `agent/`) | 75 |
| − 주석 · docstring | −6 |
| **코드 등장** | **69** (3-E-36 과 일치) |
| − `code` 필드 기본값 | −8 |
| − enum 정의 | −1 |
| − 집합 멤버십 (`_UNKNOWN_CODES`) | −1 |
| − 비교 (`_undecided_code`) | −1 |
| **= 거부를 만드는 자리** | **58** |

3-E-36 과의 차이는 §2-2 에 적은 한 칸 오차뿐이고, 합(69)은 같다.

### 파일별 거부 생성 58곳

| 파일 | 수 |
|---|---:|
| `engine/effect/executor.py` | 22 |
| `engine/trigger.py` | 9 |
| `engine/activation.py` | 6 |
| `engine/action_validation.py` | 5 |
| `engine/effect/resolution.py` | 4 |
| `engine/duel.py` | 3 |
| `engine/action_execution.py` · `engine/trigger_chain.py` · `engine/turn_progression.py` | 2 each |
| `engine/activation_timing.py` · `engine/payment.py` · `engine/response.py` | 1 each |

## 6. 58개 rejection usage 전수조사

각 자리의 **짝지은 validity/status** 를 생성자별로 읽었다
(`ValidationResult.unknown` → validity, `_fail`/`_gate` → 첫·둘째 인자,
`TriggerCandidate` → `status=`, `DuelStep` → `accepted`, `Requirement` →
조건이 `FALSE` 일 때의 간접 경로).

| 짝지은 validity/status | 수 | 선언 묶음과 맞는가 |
|---|---:|---|
| `ActionValidity.UNKNOWN` | 11 | **맞다** |
| `ResolutionStatus.UNSUPPORTED_OPERATION` | 8 | **맞다** (미구현) |
| `ResolutionStatus.INVALID_CONTEXT` | 4 | **어긋난다** |
| `accepted=False` (`DuelStep`) | 3 | 판정 불가 (validity 없음) |
| `ResolutionStatus.NOT_IMPLEMENTED` | 3 | **맞다** |
| `Requirement` 간접 (`FALSE` → `INVALID`) | 3 | **닫혀 있다** (§10) |
| `ResolutionStatus.INVALID_OPERATION` | 2 | **어긋난다** |
| `ResolutionStatus.UNCHECKED_RULES` | 2 | **맞다** |
| `ResolutionStatus.FORBIDDEN` | 2 | **어긋난다 (M2)** |
| `ResolutionStatus.UNKNOWN` | 2 | **맞다** |
| `TriggerStatus.UNKNOWN` | 2 | **맞다** |
| `TriggerChainEntry(eligibility)` | 2 | 전달 (판정 없음) |
| `ActionStatus.UNSUPPORTED_ACTION` | 1 | **맞다** |
| `ActionStatus.EXECUTION_ERROR` | 1 | **어긋난다** (방어) |
| `ActivationStatus.NOT_IMPLEMENTED` | 1 | **맞다** |
| `ActivationStatus.INVALID_ACTION` | 1 | **어긋난다** |
| `ActivationStatus.CHAIN_REFUSED` | 1 | **어긋난다** |
| `ActivationStatus` (`_AVAILABILITY_REFUSAL` 표 경유) | 1 | **어긋난다 (M2)** |
| `ActivationStatus.CONDITION_FALSE` | 1 | **어긋난다 (M1)** |
| `ActivationStatus.CONDITION_UNKNOWN` | 1 | **맞다** |
| `ResolutionStatus.EXECUTION_ERROR` | 1 | **어긋난다** (방어) |
| `ResolutionStatus.CONDITION_FALSE` | 1 | **어긋난다 (M1)** |
| `ResolutionStatus.CONDITION_UNKNOWN` | 1 | **맞다** |
| `PaymentStatus.EXECUTION_ERROR` | 1 | **어긋난다** (방어) |
| `ResponseOutcome.REFUSED` | 1 | **어긋난다** |
| **`ActionValidity.INVALID`** (`trigger.py:1318`) | **1** | **어긋난다 (M3 — 새로 찾았다)** |
| **합** | **58** | |

### §25 가 요구한 분류 표

| 분류 | 개수 | production | 기존 code 로 해결 | 새 code 필요 |
|---|---:|---:|---:|---:|
| A. RULE_NOT_IMPLEMENTED (정말 미구현) | 30 | 30 | — (이미 맞다) | 0 |
| B. CONDITION_FALSE (M1) | 2 | **2** | **2** (`CANDIDATE_NOT_ELIGIBLE`) | 0 |
| C. EXECUTION_FORBIDDEN (M2) | 3 | 2 (+1 dormant) | **3** (`EXECUTION_FORBIDDEN`) | 0 |
| D. CANDIDATE_NOT_ELIGIBLE (M3) | 1 | 0 (dormant 파이프라인) | **1** (`CANDIDATE_NOT_ELIGIBLE`) | 0 |
| E. INFORMATION_UNAVAILABLE | 0 | 0 | — (올바르게 갈라져 있다) | 0 |
| F. CARD_DEFINITION_UNAVAILABLE | 0 | 0 | — | 0 |
| G. COST_NOT_PAYABLE | 0 | 0 | — (`engine/cost/` 는 이 코드를 안 쓴다) | 0 |
| H · I. TARGET 관련 | 0 | 0 | — (`targeting.py` 는 이 코드를 안 쓴다) | 0 |
| J. ACTION_NOT_ALLOWED (`duel.py:686` 등) | 3 | 3 | **아니다** (맞는 멤버 없음) | **0** (§12) |
| 구조 오류 (`INVALID_CONTEXT`/`INVALID_OPERATION`/`INVALID_ACTION`/`CHAIN_REFUSED`) | 8 | 8 | **아니다** | **0** (§12) |
| 엔진 예외 (`EXECUTION_ERROR` ×3) | 3 | 방어 경로 | **아니다** | **0** (§12) |
| `ResponseOutcome.REFUSED` | 1 | 1 | **아니다** | **0** (§12) |
| K. DORMANT (`UnimplementedResolver` 4 · `duel:931`) | 5 | 0 | — | 0 |
| 전달 · 간접 (`TriggerChainEntry` 2 · `Requirement` 3) | 5 | 5 | — | 0 |
| **합** | **58** | | | **0** |

**`M. NEW_CODE_CANDIDATE` = 0개.** 근거는 §12 (§19 의 조건 검증).

## 7. M1 — `condition_false`

### 실측

```
Always(ConditionResult.FALSE)
  → 발동: status=condition_false   code=rule_not_implemented   missing=None
  → 해결: status=condition_false   code=rule_not_implemented
```

### §6 이 요구한 A/B/C 분류 → **CASE A**

| Case | 설명 | 해당? |
|---|---|---|
| **A** | 규칙이 구현되어 있고 조건 평가 결과가 `FALSE` → 코드가 명백히 부적절 | **그렇다** |
| B | 규칙 일부가 미구현되어 `FALSE` 처럼 보이는 구조 | 아니다 — `ConditionEvaluator` 가 끝까지 평가해 `FALSE` 를 **확정**했다 |
| C | 내부 코드이고 consumer 가 코드를 읽지 않는다 | **부분적으로 그렇다** — 그래서 안전하다 (§11 · §14) |

> **"조건 거짓" 과 "규칙 미구현" 은 동시에 성립할 수 없다.** 전자는
> 평가기가 끝까지 보고 확정한 사실이고, 후자는 평가할 규칙이 없다는
> 뜻이다. `ConditionEvaluator` 가 `FALSE` 를 돌려준 자리에서는 규칙이
> **있었다.**

그리고 정직하게 적어 둘 부분 — 그 자리는 `missing_rule` 을 **적지 않는다**.
즉 코드만 거칠고 나머지 칸은 맞다.

### 두 자리

| 위치 | 함수 | 상태 |
|---|---|---|
| `engine/activation.py:670` | `EffectActivator._check_condition` | `ActivationStatus.CONDITION_FALSE` |
| `engine/effect/executor.py:980` | `EffectExecutor._check_condition` | `ResolutionStatus.CONDITION_FALSE` |

두 계층이 **같은 태도**를 유지하도록 3-E-26 이 맞춰 두었으므로, 한쪽만
고치면 `tests/test_validation_code_consistency.py::test_07` 이 깨진다.

## 8. M2 — 출처 금지, 그리고 **M3 (새로 찾았다)**

### M2 — `TEXT_DERIVED` 출처 금지

§7 이 요구한 다섯 갈래 중 **B(규칙상 이 source 에서는 실행할 수 없음)** 이다.
정확히는 "이 **근거**로는 실행하지 않는다" — `EffectProvenance.TEXT_DERIVED`,
ADR-004.

| 위치 | 상태 | 도달 |
|---|---|---|
| `engine/activation.py:637` (`_AVAILABILITY_REFUSAL` 표 경유) | `ActivationStatus.FORBIDDEN` | **도달** |
| `engine/effect/executor.py:921` | `ResolutionStatus.FORBIDDEN` | **도달** |
| `engine/effect/resolution.py:500` | `ResolutionStatus.FORBIDDEN` | **미도달** (`UnimplementedResolver` production 생성 0곳) |

**정확한 코드가 이미 있고, 그 멤버가 바로 이 경우를 위해 쓰여 있다.**

```python
EXECUTION_FORBIDDEN = "execution_forbidden"
"""
출처가 실행을 금지한다 (``TEXT_DERIVED``, ADR-004).

``INVALID`` 중에서도 **따로 구분한다** — "조건이 거짓" 과 "이 근거로는
절대 실행하지 않는다" 는 전혀 다른 말이고, 후자는 판이 바뀌어도
달라지지 않는다.
"""
```

즉 M2 는 "맞는 코드가 없어서" 생긴 것이 **아니다.**

**`SOURCE_FORBIDDEN` 과 혼동하지 않는다.** 그 멤버는 **구조 (INVALID)**
묶음이고 "행위에 `source` 를 적으면 안 되는데 적었다" 는 뜻이다
(`action_validation.py:201` 한 자리에서만 나온다). provenance 와 무관하다.

### M3 — `_event_relation` 이 `INVALID` 관문에 "모른다" 코드를 붙인다

**3-E-36 이 이 자리를 "A. 진짜 미구현" 으로 분류했는데 틀렸다.**

```python
# engine/trigger.py:1315
return _gate(
    EligibilityGate.EVENT_RELATION,
    ActionValidity.INVALID,                  # ← 확실한 거부
    ValidationCode.RULE_NOT_IMPLEMENTED,     # ← "이 엔진이 못 한다"
    f"이 선언은 {event.point.value} 사건에 반응하지 않습니다.",
)
```

"이 선언은 그 사건에 반응하지 않는다" 는 **확실하고 올바른 거부**다 —
`TriggerSpec` 이 그 사건을 보고 있지 않다는 사실이고, 엔진이 못 하는 것이
아니다.

**그리고 이것은 purpose-built guard 를 무력화한다.** `_refusal_code` 는
바로 이 일을 막기 위해 쓰여 있다.

```python
def _refusal_code(eligibility) -> ValidationCode:
    """
    **확실한 거부**의 대표 코드. 거부를 일으킨 관문에서만 가져온다.

    ``INVALID`` 관문만 본다. … 자리가 틀려서 막힌 후보에
    ``RULE_NOT_IMPLEMENTED`` 를 적으면 "엔진이 못 한다" 와 "규칙이 막았다" 가
    **다시 섞인다** …
    """
    for verdict in eligibility.blocking:
        if verdict.validity is ActionValidity.INVALID:
            return verdict.code          # ← M3 가 여기로 올라간다
    return ValidationCode.CANDIDATE_NOT_ELIGIBLE   # ← 정확한 코드가 기본값이다
```

실측:

```
_event_relation 이 막은 결과:
   관문=event_relation       validity=invalid  code=rule_not_implemented
   관문=execution_authority  validity=unknown  code=rule_not_implemented
_refusal_code 가 고른 코드: rule_not_implemented
```

> **함수의 기본값(`CANDIDATE_NOT_ELIGIBLE`)이 정확한 답이다.** 저장소가
> 답을 이미 알고 있는데, 한 관문이 그 앞에서 다른 코드를 올려 놓는다.

**다만 `_undecided_code` 는 멀쩡하다** — `validity is UNKNOWN` 인 관문만
걸러 보기 때문이다. 같은 파일의 두 함수가 **다르게 방어하고**, 필터로
막는 쪽만 안전하다.

### M3 의 도달 여부

**dormant 다.** `TriggerSpec(...)` production 생성이 **0곳**이므로 트리거
파이프라인 전체가 아직 돌지 않는다 (3-E-29/31/34/35/36 이 반복 측정).
게다가 `judge_all` 은 수집기가 **이미 사건을 맞춘** 후보만 넘기므로,
파이프라인이 켜져도 `_event_relation` 의 `INVALID` 분기는 `judge()` 를
직접 부를 때만 닿는다.

## 9. status / code 관계

§14 의 여섯 질문에 답한다.

| # | 질문 | 답 |
|---|---|---|
| 1 | `status` 가 최종 판정인가 | **그렇다** — `permits_execution` · `activated` · `gives_a_future` 가 전부 상태만 본다 |
| 2 | `code` 는 원인인가 | **그렇다** |
| 3 | `code` 가 최종 판정을 override 하는가 | **아니다** — `permits_execution` 의 본문에 `code` 가 없다 (AST 확인) |
| 4 | consumer 가 `status` 만 보는가 | 대부분 그렇다 |
| 5 | consumer 가 `code` 도 보는가 | **넷만** 본다 (§11), 그리고 멤버 48개 중 3개만 비교된다 |
| 6 | `status` + `code` 조합이 semantic 을 완성하는가 | **그렇다** — 그리고 `reason`·`missing_rule`·`notes` 가 더 붙는다 |

### `condition_false + RULE_NOT_IMPLEMENTED` 는 정확히 무슨 뜻인가

> **"판정은 '조건이 거짓이라 거부' 이고, 이유 칸에는 '이 엔진이 아직 못
> 한다' 가 적혀 있다."**

두 문장이 서로 모순이다. 읽는 쪽이 **상태를 믿으면 맞고 코드를 믿으면
틀린다.** 지금은 거의 모든 읽는 쪽이 상태를 믿으므로 틀린 결론이 나오지
않는다.

## 10. `ValidationResult` 계약

**다섯 칸이다.** 프롬프트 §13 이 적은 `value`·`ordering_key` 는 이 타입에
**없다** — `SearchCandidate` 의 것이다.

| 칸 | 타입 | 무엇을 전달하는가 |
|---|---|---|
| `validity` | `ActionValidity` | **최종 판정** (VALID / INVALID / UNKNOWN) |
| `code` | `ValidationCode` | 안정적인 **이유 코드** (기계가 분기하라고 있다) |
| `reason` | `str` | 사람이 읽는 문장 |
| `missing_rule` | `str \| None` | 어느 규칙 계층이 없는가 (`unknown()` 만 받는다) |
| `notes` | `tuple[str, ...]` | 부수 관찰. **판정을 바꾸지 않는다** |

> **"코드 하나가 모든 거부 사유를 표현해야 하는 구조인가?" → 아니다.**
> 다섯 칸이 함께 의미를 완성하고, 그중 결정은 `validity` 하나가 쥔다.

### 새로 찾은 간접 경로 (3-E-36 의 "0건" 정밀화)

```python
# engine/action_validation.py  _check_requirements
if verdict.result is ConditionResult.FALSE:
    return ValidationResult.invalid(requirement.code, requirement.detail)
```

`requirement.code` 가 **`invalid()` 로 그대로 간다.** 이 코드를 든
`Requirement` 가 **3개** 있으므로 구조적으로는 `INVALID +
RULE_NOT_IMPLEMENTED` 가 가능하다.

**그런데 닫혀 있다** — 셋의 조건이 모두 `FALSE` 를 내지 않는다.

| `Requirement` | 조건 | `FALSE` 를 내는가 |
|---|---|---|
| `action_validation.py:573` | `UnimplementedRule(...)` | **아니다** (언제나 `UNKNOWN`) |
| `action_validation.py:582` | `UnimplementedRule(...)` | **아니다** |
| `action_validation.py:876` | `_NormalSpellActivation` | **아니다** — 소스가 "이 조건은 `FALSE` 를 **돌려주지 않는다**" 고 적는다 |

> **타입이 막는 것이 아니라 조건의 성질이 막는다.** 네 번째 `Requirement`
> 가 생기면 그때 열린다. `test_18` 이 셋의 수와 성질을 함께 고정한다.

## 11. GateVerdict 영향

```
ValidationResult → GateVerdict → TriggerEligibility → TriggerChainEntry
```

| 독자 | 읽는 것 | M1 | M2 | M3 |
|---|---|---|---|---|
| `GateVerdict.forbids` (`trigger.py:1079`) | `EXECUTION_FORBIDDEN` | 영향 없음 | **영향 없음** — 발동·해결 결과는 `GateVerdict` 가 아니다 | 영향 없음 (`EVENT_RELATION` 은 `forbids` 가 아니다) |
| `_refusal_code` (`trigger_chain.py:547`) | 첫 `INVALID` 관문의 코드 | 영향 없음 | 영향 없음 | **영향 있음** — 거부를 "미구현" 으로 올린다 |
| `_undecided_code` (`trigger_chain.py:563`) | `UNKNOWN` 관문만 | 영향 없음 | 영향 없음 | **영향 없음** (필터가 막는다) |
| `agent/simulation.py:284` | `_UNKNOWN_CODES` | **영향 있음** (라벨) | **영향 있음** (라벨) | dormant |

`legal_actions` → `PlayerAction` 흐름에서 이 코드는 **allowed 를 만들지
않는다.** `RULE_NOT_IMPLEMENTED` 가 붙은 결과는 전부 `withheld` 거나 거절
이고, `permits_execution` 이 거짓이다.

> **M1·M2 는 behavior-preserving 하다.** M3 는 **dormant 파이프라인 안에서
> behavior-affecting** 하다 — 보고되는 코드가 달라진다. 다만
> `ChainInsertion` 은 어느 쪽이든 거부이므로 **삽입 결과는 같다.**

## 12. Trigger vs Action/Resolution 비교 — §17 의 표

| Semantic | Trigger 계층 | Action/Resolution 계층 | 동일 semantic 인가 |
|---|---|---|---|
| **조건 거짓** | `INELIGIBLE` + **`CANDIDATE_NOT_ELIGIBLE`** | `CONDITION_FALSE` + **`RULE_NOT_IMPLEMENTED`** | **같은 사실, 다른 코드 (M1)** |
| **출처 금지** | `FORBIDDEN` + **`EXECUTION_FORBIDDEN`** | `FORBIDDEN` + **`RULE_NOT_IMPLEMENTED`** | **같은 사실, 다른 코드 (M2)** |
| 규칙 미구현 | `UNKNOWN` + `RULE_NOT_IMPLEMENTED` | `NOT_IMPLEMENTED`/`UNSUPPORTED_OPERATION` + 같은 코드 | **같다** |
| 정보 부족 | `UNKNOWN` + `INFORMATION_UNAVAILABLE` | `CONDITION_UNKNOWN` + 같은 코드 | **같다** |
| 대상 부적합 | (대상 관문 없음) | `INVALID_TARGET` + `TOO_FEW_SELECTED`/`CANDIDATE_NOT_ELIGIBLE` | 비교 대상 없음 |
| **사건 불일치** | `INVALID` + **`RULE_NOT_IMPLEMENTED` (M3)** | (해당 개념 없음) | **트리거 계층 안의 불일치** |

> **3-E-26 이 트리거 계층의 두 자리를 고쳤지만, 세 번째 자리(M3)를 놓쳤고
> 발동·해결 계층에는 손대지 않았다.** 이번 Phase 가 그 셋을 한 표에 모았다.

## 13. Effect / Cost / Target

| 영역 | 이 코드 | 선언 묶음과 어긋난 수 |
|---|---:|---:|
| `engine/effect/executor.py` | 22 | **9** (`INVALID_CONTEXT` 4 · `INVALID_OPERATION` 2 · `FORBIDDEN` · `CONDITION_FALSE` · `EXECUTION_ERROR`) |
| `engine/effect/resolution.py` | 4 | 1 (dormant) |
| `engine/effect/targeting.py` | **0** | — (`CANDIDATE_NOT_ELIGIBLE` 을 쓴다) |
| `engine/cost/` 전체 | **0** | — (`COST_NOT_IMPLEMENTED` 를 쓴다) |
| `engine/payment.py` | 1 | 1 (예외, 방어) |

**비용과 대상 계층이 가장 깔끔하다.** 자기 코드를 가지고 있고 이 코드를
빌리지 않는다.

그리고 어긋난 9곳에서 **상태 이름이 코드보다 정확하다** —
`ResolutionStatus` 에는 `INVALID_CONTEXT` · `EXECUTION_ERROR` ·
`UNSUPPORTED_OPERATION` 이 **있고** `ValidationCode` 에는 **없다**. 그것이
"새 코드가 필요 없다" 의 핵심 근거다: **정확한 사실이 이미 다른 칸에 있다.**

## 14. Simulation / AI

```
engine → DuelStep.code → agent/simulation.py:284  step.code in _UNKNOWN_CODES
      → SimulationStatus.UNKNOWN  (code 는 SimulationResult.code 에 보존)
      → agent/search.py:311  status is not SUPPORTED → value=None
      → ordering_key() = (1, 0, 0, canonical_state)
```

| 항목 | 확인 |
|---|---|
| `_UNKNOWN_CODES` 멤버 | 5개 — `RULE_NOT_IMPLEMENTED` · `COST_NOT_IMPLEMENTED` · `INFORMATION_UNAVAILABLE` · `CARD_DEFINITION_UNAVAILABLE` · `EFFECT_LIST_UNRELIABLE` |
| 거부 코드가 들어 있는가 | **아니다** — `CANDIDATE_NOT_ELIGIBLE` · `EXECUTION_FORBIDDEN` · `OK` 모두 없다 |
| `RULE_NOT_IMPLEMENTED → UNKNOWN` | **그렇다** |
| `RULE_NOT_IMPLEMENTED → LOSS` | **아니다** |
| `RULE_NOT_IMPLEMENTED → score 0` | **아니다** — `value=None` |
| `UNKNOWN` 과 `REFUSED` 의 `ordering_key` | **같다** `(1, 0, 0, …)` |
| 원래 코드 보존 | **보존** (`SimulationResult.code`) |
| `agent/` 의 이 코드 등장 | **1곳** |

> **M1·M2 가 고쳐지면 그 수들이 `UNKNOWN` 에서 `REFUSED` 로 옮겨 간다.**
> 선택은 그대로이고 **보고가 정확해진다.** 그것이 고칠 가치의 전부이자
> 고치지 않아도 되는 이유다.

## 15. Hidden information

**`hidden information → RULE_NOT_IMPLEMENTED` 변환은 없다.**

| 사실 | 코드 | 묶음 |
|---|---|---|
| 가리킨 카드가 관측에 없다 | `HIDDEN_CARD` | 모른다 (UNKNOWN) |
| 조건이 관측 밖을 묻는다 | `INFORMATION_UNAVAILABLE` | 모른다 (UNKNOWN) |
| 카드 정의를 못 읽는다 | `CARD_DEFINITION_UNAVAILABLE` | 모른다 (UNKNOWN) |
| 효과 목록을 믿을 수 없다 | `EFFECT_LIST_UNRELIABLE` | 모른다 (UNKNOWN) |

네 코드가 모두 `RULE_NOT_IMPLEMENTED` 와 **다른 멤버**이고 같은 묶음에
있다. 실측에서 `IsMonster(InstanceId(9999))` 는
`INFORMATION_UNAVAILABLE` + `unchecked=('#9999 가 관측에 보이지 않음 (가려진
존)',)` 를 낸다. **58개 중 가려진 정보를 이 코드로 가린 자리는 0곳이다.**

## 16. 실제 카드 corpus — §19 의 10개 이상

| # | 범주 | 상황 | 위치 | status | code | 실제 semantic | 분류 |
|---|---|---|---|---|---|---|---|
| 1 | 일반 소환 | 제물이 필요한 몬스터 | `action_validation:301` | `UNKNOWN` | 이 코드 | 제물 절차 없음 | **A** |
| 2 | 일반 소환 | 엑스트라 덱 · 의식 · 토큰 | `_NormalSummonProcedure` → `FALSE` | `INVALID` | `CANNOT_NORMAL_SUMMON` | 규칙이 금지 | **정확** |
| 3 | 일반 소환 | 소환권 이미 씀 | — | `INVALID` | `NORMAL_SUMMON_ALREADY_USED` | 규칙이 금지 | **정확** |
| 4 | 특수 소환 | 카드별 소환 조건 | `action_validation:582` | `UNKNOWN` | 이 코드 | 절차 계층 없음 | **A** |
| 5 | 특수 소환 | 목록에 없는 행위 | `duel:686` | `accepted=False` | 이 코드 | "지금 후보가 아니다" | **J\*** |
| 6 | 마법 | 통상 마법 아님 | `action_validation:876` | `UNKNOWN` | 이 코드 (닿지 않음) | 타이밍 계층 없음 | **I** |
| 7 | 마법 | 페이즈가 아니다 | — | `INVALID` | `WRONG_PHASE` | 규칙이 금지 | **정확** |
| 8 | 함정 | 세트한 턴 | — | `INVALID` | `SET_THIS_TURN` | 규칙이 금지 | **정확** |
| 9 | 함정 | 함정 발동 타이밍 | `activation_timing:519` | `UNKNOWN` | 이 코드 **또는** `INFORMATION_UNAVAILABLE` | 올바르게 가른다 | **I** |
| 10 | 몬스터 효과 | 기동/유발 분류 없음 | 같음 | `UNKNOWN` | 같음 | 같음 | **I** |
| 11 | 발동 | **조건이 거짓** | `activation:670` | `CONDITION_FALSE` | 이 코드 | 확실한 거부 | **M1** |
| 12 | 발동 | 출처 금지 | `activation:637` | `FORBIDDEN` | 이 코드 | 근거가 금지 | **M2** |
| 13 | 해결 | **조건이 거짓** | `executor:980` | `CONDITION_FALSE` | 이 코드 | 확실한 거부 | **M1** |
| 14 | 해결 | 출처 금지 | `executor:921` | `FORBIDDEN` | 이 코드 | 근거가 금지 | **M2** |
| 15 | 해결 | 조작 종류 미지원 | `executor` 8곳 | `UNSUPPORTED_OPERATION` | 이 코드 | 진짜 미구현 | **A** |
| 16 | 비용 | 후보 없음 | `cost/` | — | `NO_CANDIDATES` | 치를 것이 없다 | **정확** |
| 17 | 비용 | 표현 못 하는 비용 | `cost/validation.py` | `UNKNOWN` | `COST_NOT_IMPLEMENTED` | 미구현 (전용 코드) | **정확** |
| 18 | 대상 | 고른 카드가 후보 아님 | `targeting.py` | `INVALID` | `CANDIDATE_NOT_ELIGIBLE` | 부적격 | **정확** |
| 19 | 대상 | 덜 골랐다 | `targeting.py` | `INVALID` | `TOO_FEW_SELECTED` | 수가 안 맞다 | **정확** |
| 20 | source restriction | `source` 를 적으면 안 되는데 적었다 | `action_validation:201` | `INVALID` | `SOURCE_FORBIDDEN` | 구조 오류 | **정확** |
| 21 | condition | 관측 밖을 묻는 조건 | `activation:686` | `CONDITION_UNKNOWN` | `INFORMATION_UNAVAILABLE` | 정보 없음 | **정확** |
| 22 | trigger | **사건 불일치** | `trigger:1318` | `INVALID` | 이 코드 | 확실한 거부 | **M3** |
| 23 | effect resolution | 문맥 불일치 | `executor` 4곳 | `INVALID_CONTEXT` | 이 코드 | 구조 오류 | **J\*** |

## 17. Safety invariant — §20 열두 항목

| # | invariant | 결과 |
|---|---|---|
| 1 | `CONDITION_FALSE` → 이 코드 **자동 변환** 없음 | **없다** — 변환 함수가 아니라 **처음부터의 선택**이다 (M1) |
| 2 | `INFORMATION_UNAVAILABLE` → 이 코드 자동 변환 없음 | **없다** — 다섯 자리가 `missing_rules()` 로 가른다 |
| 3 | `EXECUTION_FORBIDDEN` → 이 코드 자동 변환 없음 | **없다** — 같은 이유로 선택이다 (M2) |
| 4 | `CANDIDATE_NOT_ELIGIBLE` → 이 코드 자동 변환 없음 | **없다** — M1/M3 는 선택이다 |
| 5 | 이 코드 → `FALSE` 자동 변환 없음 | **없다** |
| 6 | 이 코드 → `LOSS` 자동 변환 없음 | **없다** |
| 7 | 이 코드 → `VALID` 자동 변환 없음 | **없다** — `permits_execution` 이 `validity` 만 본다 |
| 8 | 이 코드 → `ELIGIBLE` 자동 변환 없음 | **없다** — 트리거 적격은 `OK` 다 |
| 9 | hidden information → 이 코드 변환 없음 | **없다** (§15) |
| 10 | simulation 이 임의로 0점 처리하지 않음 | **없다** — `value=None` |
| 11 | `GateVerdict` 가 이 코드를 `FORBIDDEN` 으로 바꾸지 않음 | **없다** — `forbids` 가 `EXECUTION_FORBIDDEN` 만 본다 |
| 12 | 트리거 계층과 Action 계층의 의미가 **충돌하지 않음** | **충돌하지 않지만 불일치한다** — 두 코드를 함께 읽는 consumer 가 없으므로 충돌로 번지지 않는다 |

**열두 항목 모두 "자동 변환" 은 없다.** 1·3·4·12 는 "변환이 아니라 선택" 으로
정직하게 적었다.

## 18. 테스트

`tests/test_validation_code_rejection_semantics_audit.py` — **31개, 전부 통과**
(skip 0).

| # | 범주 | 무엇을 고정하는가 |
|---|---|---|
| 01 | **A** enum inventory | 48개 · 생성 0회 멤버 0개 |
| 02 | A | **섹션 주석 선언** 8묶음 · `모른다 (UNKNOWN)` 5개 · 금지선 문장 |
| 03 | **B** 사용처 수 | **58 ≠ 48** · 69와의 차이 정확히 11 |
| 04 | B · §14 | **45개 코드가 한 번도 비교되지 않는다** |
| 05 | **C · W** M1 | 발동 계층 negative test (`condition_false` + 이 코드) |
| 06 | C · W | 해결 계층 쌍 |
| 07 | **L** 계층 비교 | 트리거는 같은 사실에 `CANDIDATE_NOT_ELIGIBLE` 을 쓴다 |
| 08 | **D · X** M2 | 발동·해결 negative test |
| 09 | **F** | `EXECUTION_FORBIDDEN` 의 docstring 이 M2 를 위해 쓰여 있다 |
| 10 | D | `SOURCE_FORBIDDEN` 과 혼동하지 않는다 (한 자리뿐) |
| 11 | **M3** | `_event_relation` 이 `INVALID` 관문에 이 코드를 붙인다 |
| 12 | **M3** | `_refusal_code` 가 자기 docstring 을 어기게 된다 (실측) |
| 13 | M3 | `_undecided_code` 는 필터로 막혀 멀쩡하다 |
| 14 | **E** | `CANDIDATE_NOT_ELIGIBLE` 은 비용 묶음 · `CONDITION_FALSE` 멤버는 **없다** |
| 15 | **G** | `INFORMATION_UNAVAILABLE` 분리 유지 |
| 16 | **H** | `status` 가 판정 · `code` 가 원인 (`permits_execution` AST) |
| 17 | **I** | `ValidationResult` 는 **5칸** · `value`/`ordering_key` 는 없다 |
| 18 | I · §9 | `invalid()` 로 가는 **간접 경로**가 있으나 조건의 성질이 막는다 |
| 19 | **J** | `GateVerdict.forbids` 가 `EXECUTION_FORBIDDEN` 만 읽는다 |
| 20 | **K** | `ActionValidator` 가 선언된 묶음을 지킨다 (실제 카드) |
| 21 | **M** | 효과 계층이 가장 많이 어긋난다 · 상태 이름이 코드보다 정확하다 |
| 22 | **N · O** | 비용 · 대상 계층은 자기 코드를 쓴다 |
| 23 | **P · Q** | `_UNKNOWN_CODES` 5개 · 거부 코드 0개 |
| 24 | Q | `UNKNOWN != 0 != LOSS` · `REFUSED` 와 같은 순위 |
| 25 | **R** | hidden information 변환 없음 |
| 26 | **S · T** | M1·M2 는 `DuelStep` 까지 · M3 는 dormant (`TriggerSpec` 생성 0곳) |
| 27 | **U** | 세 불일치 모두 **기존 코드로 표현된다** |
| 28 | **V** | **새 코드 후보 0개** — §12 의 조건 3·4·6 이 빠진다 |
| 29 | §20 | safety invariant 열두 항목 |
| 30 | §19 | 실제 카드 한 판 — 코드가 여러 묶음에서 나온다 |
| 31 | **Y** | 3-E-24~36 regression + enum 크기 그대로 |

### 고의 위반 검증

주장이 정말 잡히는지 확인하려고 production 에 결함을 **일부러** 넣고 테스트가
잡는지 보았다. 전부 되돌렸다 (commit 뒤에 실행했으므로 작업 트리로 복구를
검증할 수 있다).

| 주입 | 잡은 테스트 |
|---|---|
| A. enum 의 섹션 주석을 지운다 | `test_02` |
| B. 새 `ValidationCode` 멤버를 더한다 (48 → 49) | `test_01` · `test_02` · `test_14` |
| C. 쓰이지 않는 멤버를 더한다 | `test_01` |
| D. 거부 생성 자리를 하나 더한다 (58 → 59) | `test_03` |
| E. **M1 을 고친다** (발동 계층) | `test_05` · `test_07` |
| F. **M1 을 고친다** (해결 계층) | `test_06` · `test_21` |
| G. **M2 를 고친다** (해결 계층) | `test_08` · `test_09` · `test_21` |
| H. **M3 를 고친다** (사건 불일치) | `test_11` · `test_12` |
| I. `_refusal_code` 가 `UNKNOWN` 관문까지 보게 한다 | `test_13` |
| J. `permits_execution` 이 `code` 도 본다 | `test_16` |
| K. `ValidationResult` 에 `value` 칸을 더한다 | `test_17` |
| L. `_UNKNOWN_CODES` 에 거부 코드를 더한다 | `test_23` · `test_04` |
| M. `targeting.py` 가 이 코드를 쓴다 | `test_22` |
| N. `SOURCE_FORBIDDEN` 을 한 자리 더 쓴다 | `test_10` |
| O-1. `Requirement` 의 조건을 `FALSE` 를 내는 것으로 **바꿔치기한다** | `test_18` |
| O-2. 네 번째 `Requirement` 를 **더한다** | `test_18` · `test_03` |

**열여섯 가지 모두 잡혔다.** E~H 가 특히 중요하다 — **고치는 방향**도
잡히므로, 다음 Phase 가 M1·M2·M3 를 고치면 이 테스트들이 먼저 깨져서
"보고서의 측정이 낡았다" 고 알려 준다. 그것이 §21 이 "그 테스트들을 고친
뒤의 사실로 갱신하고 왜 갱신하는지 적는다" 를 미리 요구하는 이유다.

### 주입이 찾아낸 `test_18` 의 실제 구멍 (고쳤다)

O 를 처음 넣었을 때 **잡히지 않았다.** `test_18` 이 이 코드를 든
`Requirement` 의 **개수만** 세고 있었기 때문이다.

```python
# 틀린 방법 — 고쳤다
carriers.append(node.lineno)
assert len(carriers) == REQUIREMENT_CARRIERS   # 3
```

내가 주입한 것은 한 carrier 의 **조건을 바꿔치기**한 것이었다
(`UnimplementedRule(...)` → `FALSE` 를 낼 수 있는 조건). 개수는 3 그대로이고
테스트는 통과한다. 그런데 §10 의 결론("간접 경로가 **조건의 성질로** 닫혀
있다")은 **각 carrier 의 조건**에 걸려 있으므로, 개수만 세는 것은 그 결론을
지키지 못한다.

carrier 를 **조건 종류와 함께** 세도록 고쳤다.

```python
kinds = sorted(kind for _, kind in carriers)
assert kinds == ["UnimplementedRule", "UnimplementedRule", "scope"]
```

그리고 `_NormalSpellActivation.evaluate` 의 본문에 `ConditionResult.FALSE`
가 없다는 것까지 AST 로 확인하도록 더했다. 고친 뒤 O 를 둘로 나눠
(O-1 바꿔치기 · O-2 네 번째 추가) 넣었고 둘 다 잡혔다.

### 회귀

| | 전 (3-E-36 완료 시점) | 후 |
|---|---|---|
| 통과 | 3,819 | 3,850 |
| 건너뜀 | 4 | 4 |
| 실패 | 0 | 0 |

## 19. 신규 Structural ID 여부

**신규 STRUCTURAL ID 를 만들지 않았다.** §23 의 여섯 조건을 확인했다.

| 조건 | 충족? |
|---|---|
| 1. 실제 production path | **M1·M2 는 그렇다.** M3 는 dormant |
| 2. 현재 contract 로 안전하게 표현 불가 | **아니다** — 셋 다 기존 코드로 표현된다 (`test_27`) |
| 3. consumer 가 의미 차이를 실제로 필요로 함 | **아니다** — 45개 코드가 한 번도 읽히지 않고, 읽는 넷 중 어느 것도 이 차이를 필요로 하지 않는다 |
| 4. 기존 ADR/TODO 로 설명되지 않음 | **아니다** — 3-E-26 이 같은 문제를 설명하고 두 자리를 고친 기록이 있다 |
| 5. 단순 naming 문제가 아님 | **절반** — 코드 **선택**의 문제이고 enum 설계 문제는 아니다 |
| 6. 다음 engine 단계에서 구조적 결정 필요 | **아니다** — 세 줄 치환이면 끝난다 |

2·3·4·6 이 불충족이므로 신규 ID 후보가 아니다.

### 기록만 남긴다 (신규 ID 아님)

| 표시 | 위치 | 현재 | 정확한 기존 코드 | 고치는 비용 |
|---|---|---|---|---|
| **M1** | `engine/activation.py:670` | `CONDITION_FALSE` + 이 코드 | `CANDIDATE_NOT_ELIGIBLE` | **1줄** |
| **M1** | `engine/effect/executor.py:980` | `CONDITION_FALSE` + 이 코드 | `CANDIDATE_NOT_ELIGIBLE` | **1줄** |
| **M2** | `engine/activation.py:637` (`_AVAILABILITY_REFUSAL` 표) | `FORBIDDEN` + 이 코드 | `EXECUTION_FORBIDDEN` | **표를 갈라야 한다** — `FORBIDDEN_SOURCE` 와 `UNVERIFIED`/`NOT_IMPLEMENTED` 가 한 줄을 공유한다 |
| **M2** | `engine/effect/executor.py:921` | `FORBIDDEN` + 이 코드 | `EXECUTION_FORBIDDEN` | **1줄** |
| **M2** | `engine/effect/resolution.py:500` (dormant) | 같음 | `EXECUTION_FORBIDDEN` | **1줄** |
| **M3** | `engine/trigger.py:1318` | `INVALID` + 이 코드 | `CANDIDATE_NOT_ELIGIBLE` (`_refusal_code` 의 기본값) | **1줄** |
| J\* | 구조 오류 8곳 · 멤버십 1곳 · 응답 거절 1곳 · 예외 3곳 | 이 코드 | **맞는 멤버 없음** | enum 변경 — **지금 하지 않는다** |

## 20. Final Decision — **D. EXISTING_CODE_CAN_FIX**

다른 후보를 고르지 않은 이유를 먼저 적는다.

- **A. ALL_CODES_SEMANTICALLY_SATISFACTORY 가 아니다.** 58곳 중 16곳이
  enum 이 **스스로 선언한 묶음**과 어긋나고, 그중 셋(M1·M2·M3)은 정확한
  코드가 **이미 있는데도** 쓰지 않는다.
- **B. MISCLASSIFIED_BUT_SAFE 는 3-E-36 의 판정이고, 이번에는 한 걸음 더
  나아간다.** 3-E-36 은 "오분류가 있지만 안전하다" 까지 말했다. 이번
  Phase 는 **"그 오분류 전부가 기존 코드로 고쳐진다"** 를 측정했고, 새
  발견(M3)과 그것이 purpose-built guard 를 무력화한다는 사실을 더했다.
  B 로 적으면 그 진전을 숨긴다.
- **C. M1_M2_SEMANTIC_GAP_BUT_SAFE 가 아니다.** M1·M2 **둘만** 이라고
  적으면 **M3 를 숨긴다.** 그리고 M3 는 "safe" 라고만 적을 수 없다 —
  `_refusal_code` 가 자기 docstring 이 금지한 코드를 올리게 되므로
  dormant 파이프라인 안에서 **보고가 틀린다.**
- **E. NEW_CODE_REQUIRED 가 아니다.** `NEW_CODE_CANDIDATE` 가 **0개**다.
  §12 의 일곱 조건 중 3(「status 만으로도 의미를 잃는다」) · 4(「consumer
  가 그 차이를 필요로 한다」) · 6(「기존 ADR/TODO 로 설명 안 됨」)이
  빠진다. 코드가 없는 10곳도 **상태 이름이 정확하고**(`INVALID_CONTEXT` ·
  `EXECUTION_ERROR`) **아무도 코드를 읽지 않는다.**
- **F. PRODUCTION_BUG 가 아니다.** Gate 결과도 Action 결과도 Simulation
  **선택**도 바뀌지 않는다. `validity`/`status` 가 모든 자리에서 정확하고,
  `UNKNOWN` 과 `REFUSED` 의 `ordering_key` 가 같다. M3 가 바꾸는 것은
  **보고되는 코드 한 칸**이고 `ChainInsertion` 은 어느 쪽이든 거부다.
- **G. UNKNOWN 이 아니다.** 48개 멤버 전부와 58개 사용처 전부를 AST 로
  수집하고, M1·M2·M3 를 **실제로 돌려** 확인했다. §26 의 열두 질문에 모두
  답했다.

**D 를 고르는 근거는 셋이다.**

1. **세 불일치 모두 기존 `ValidationCode` 로 정확히 표현된다.**
   M1·M3 → `CANDIDATE_NOT_ELIGIBLE`(저장소가 이미 쓰고, `_refusal_code` 의
   **기본값**이다), M2 → `EXECUTION_FORBIDDEN`(docstring 이 **이 경우를
   위해** 쓰여 있다). 추측이 아니라 저장소의 기존 선택이다.
2. **새 enum 이 필요한 semantic 이 하나도 없다.** 45개 코드가 한 번도
   읽히지 않고, 코드가 없는 10곳은 상태가 정확한 사실을 들고 있다.
   `ValidationResult` 다섯 칸이 함께 의미를 완성하므로 코드 하나가 모든
   거부 사유를 짊어질 필요가 없다.
3. **그러나 정리는 별도 phase 가 맞다.** M1 은 1줄 ×2, M3 는 1줄, M2 는
   `_AVAILABILITY_REFUSAL` 표를 갈라야 한다. 그리고 고치면
   `agent/simulation.py` 의 집계가 `UNKNOWN` → `REFUSED` 로 옮겨 가므로
   **AI 보고가 달라진다** — 그 영향을 함께 보고 결정할 일이다.

**그리고 이번 Phase 는 고치지 않았다** (§0 · §27).

### §25 가 요구한 첫 번째 표

| semantic | 실제 상황 | 현재 code | 더 정확한 표현 | production 영향 |
|---|---|---|---|---|
| **조건 거짓** | `ConditionEvaluator` 가 끝까지 평가해 `FALSE` 확정 | `RULE_NOT_IMPLEMENTED` (발동 1 · 해결 1) | **`CANDIDATE_NOT_ELIGIBLE`** (트리거 계층이 이미 쓴다) | **없다** — 상태가 정확하고 순위가 같다. AI 보고 라벨만 거칠다 |
| **출처 금지** | `TEXT_DERIVED` provenance, ADR-004 | `RULE_NOT_IMPLEMENTED` (발동 1 · 해결 1 · dormant 1) | **`EXECUTION_FORBIDDEN`** (docstring 이 이 경우를 위해 쓰여 있다) | **없다** — `GateVerdict.forbids` 는 다른 타입만 본다 |
| **규칙 미구현** | 규칙 계층이 없다 (30곳) | `RULE_NOT_IMPLEMENTED` | **같다 — 정확하다** | 정상 |
| **정보 부족** | 관측 밖 · 가려진 카드 · 못 읽는 정의 | `INFORMATION_UNAVAILABLE` · `HIDDEN_CARD` · `CARD_DEFINITION_UNAVAILABLE` | **같다 — 정확하다** (`IfExp` 5곳이 가른다) | 정상 |
| **후보 부적격** | 고른 카드가 후보 조건 불만족 | `CANDIDATE_NOT_ELIGIBLE` (대상 · 비용 계층) | **같다 — 정확하다** | 정상 |
| **대상 부적합** | 수가 안 맞다 · 관측에 없다 | `TOO_FEW_SELECTED` · `CANDIDATE_NOT_FOUND` 등 | **같다 — 정확하다** | 정상 |
| (추가) **사건 불일치** | 선언이 그 사건을 보지 않는다 | `RULE_NOT_IMPLEMENTED` (M3) | **`CANDIDATE_NOT_ELIGIBLE`** | **dormant** — 켜지면 `_refusal_code` 가 틀린 코드를 올린다 |
| (추가) **구조 오류** | 문맥·인덱스·체인 불일치 (8곳) | `RULE_NOT_IMPLEMENTED` | **맞는 멤버 없음** — 상태(`INVALID_CONTEXT`)가 정확하다 | 없다 |
| (추가) **엔진 예외** | `except Exception` (3곳, 방어) | `RULE_NOT_IMPLEMENTED` | **맞는 멤버 없음** — 상태(`EXECUTION_ERROR`)가 정확하다 | 없다 (방어 경로) |

---

## 21. Next Phase Candidate (하나만 제안한다)

**Phase 3-E-38 — M1·M2·M3 코드 선택 교정 (MINIMAL FIX) + `_UNKNOWN_CODES` 영향 측정**

이 Phase 가 "기존 코드로 고쳐진다" 를 확정했고, 고칠 자리 **다섯 줄**과
한 표(`_AVAILABILITY_REFUSAL`)를 정확히 지목했다. 다음 Phase 는 그것을
실제로 고치고, **`agent/simulation.py` 의 집계가 어떻게 달라지는지**를
함께 측정한다 — 고치면 확실한 거부가 `SimulationStatus.UNKNOWN` 에서
`REFUSED` 로 옮겨 가므로, `_UNKNOWN_CODES` 가 지금 세는 수가 바뀐다.

범위를 미리 좁혀 둔다.

- 고칠 것: `activation.py:670` · `executor.py:980` (→ `CANDIDATE_NOT_ELIGIBLE`) ·
  `executor.py:921` · `resolution.py:500` (→ `EXECUTION_FORBIDDEN`) ·
  `trigger.py:1318` (→ `CANDIDATE_NOT_ELIGIBLE`)
- 판단이 필요한 것: `activation.py:637` 의 `_AVAILABILITY_REFUSAL` 표를
  갈라야 하는가
- 하지 않을 것: **새 enum 멤버**, J\* 10곳, `_UNKNOWN_CODES` 의 멤버 변경
- 반드시 할 것: 3-E-36 `test_05`/`test_10`/`test_11` 과 3-E-37
  `test_05`~`test_12` 가 **고치면 깨지도록** 만들어 두었으므로, 그
  테스트들을 **고친 뒤의 사실로 갱신**하고 왜 갱신하는지 보고서에 적는다

AUDIT 이 아니라 **MINIMAL FIX** phase 다. 그래서 이번 Phase 에서 하지
않고 제안으로 남긴다.

---

## §26 — 최종 질문 열두 개에 대한 답

### Q1. M1(`condition_false` → `RULE_NOT_IMPLEMENTED`)은 실제 production 에서 발생하는가?

**발생한다.** production 발동기·해결기를 그대로 불러 확인했다.

```
Always(ConditionResult.FALSE) → status=condition_false, code=rule_not_implemented
```

두 자리다 — `engine/activation.py:670` (`EffectActivator._check_condition`) ·
`engine/effect/executor.py:980` (`EffectExecutor._check_condition`).

### Q2. 발생한다면 실제 판정 결과에 영향을 주는가?

**주지 않는다.** `status` 가 정확한 사실(`CONDITION_FALSE`)을 들고 있고,
결정을 내리는 모든 자리가 상태를 본다 (`permits_execution` 의 본문에
`code` 가 없다). AI 쪽에서도 `UNKNOWN` 과 `REFUSED` 의 `ordering_key` 가
같아 **선택이 바뀌지 않는다.**

달라지는 것은 하나다 — `SearchCandidate.status` 라벨이
`UNKNOWN`(모른다)으로 보고된다. 실제로는 `REFUSED`(거부)다.

### Q3. M2(source forbidden → `RULE_NOT_IMPLEMENTED`)은 실제 production 에서 발생하는가?

**발생한다.** 세 자리 중 둘이 live 다.

| 위치 | 도달 |
|---|---|
| `engine/activation.py:637` (`_AVAILABILITY_REFUSAL` 경유) | **도달** |
| `engine/effect/executor.py:921` | **도달** |
| `engine/effect/resolution.py:500` | 미도달 (`UnimplementedResolver` production 생성 0곳) |

실측: `EffectProvenance.text_derived(...)` 정의 → `status=forbidden`,
`code=rule_not_implemented`.

### Q4. 발생한다면 기존 `EXECUTION_FORBIDDEN` 으로 정확히 표현 가능한가?

**가능하다 — 그 멤버가 바로 이 경우를 위해 만들어졌다.**

> `EXECUTION_FORBIDDEN` : "출처가 실행을 금지한다 (`TEXT_DERIVED`,
> ADR-004). `INVALID` 중에서도 **따로 구분한다** …"

트리거 계층은 이미 그것을 쓴다 (3-E-26). `SOURCE_FORBIDDEN` 과 혼동하지
않는다 — 그쪽은 **구조 (INVALID)** 묶음이고 "행위에 `source` 를 적으면 안
되는데 적었다" 는 뜻이며, `action_validation.py:201` 한 자리에서만 나온다.

### Q5. `RULE_NOT_IMPLEMENTED` 48개 rejection usage 중 실제 semantic mismatch 는 몇 개인가?

**전제를 먼저 고친다 — 48 은 `ValidationCode` 멤버 수이고 사용처 수가
아니다. 거부를 만드는 자리는 58곳이다.**

| | 수 |
|---|---:|
| 거부 생성 사용처 | **58** |
| enum 이 선언한 묶음과 **어긋나는** 것 | **16** |
| 그중 **정확한 기존 코드가 있는** 것 | **3가지 · 6자리** (M1 ×2 · M2 ×3 · M3 ×1) |
| 그중 **맞는 멤버가 없는** 것 | **10** (구조 오류 8 · 멤버십 1 · 응답 거절 1) + 예외 3 |
| 묶음과 **맞는** 것 | **30 + 12** (A 30 · 전달·간접·방어 12) |

### Q6. 그중 production 에 도달하는 것은 몇 개인가?

| 분류 | 자리 수 | 도달 |
|---|---:|---|
| M1 | 2 | **2 도달** |
| M2 | 3 | **2 도달** · 1 dormant |
| M3 | 1 | **0 도달** (트리거 파이프라인 dormant — `TriggerSpec` production 생성 0곳) |
| 구조 오류 · 멤버십 · 응답 거절 | 10 | **10 도달** |
| 엔진 예외 | 3 | 0 (방어 경로, `pragma: no cover`) |
| **어긋난 16곳 중 도달** | | **14** |

### Q7. 현재 `ValidationCode` enum 으로 충분한가?

**충분하다 — 단, "충분" 의 기준이 `status` 와 함께 읽는 것이기 때문이다.**

- 48개 멤버가 모두 쓰이고 죽은 멤버가 없다.
- 세 불일치 모두 기존 멤버로 표현된다.
- 코드가 없는 10곳은 **상태 이름이 정확하다** (`INVALID_CONTEXT` ·
  `EXECUTION_ERROR` · `UNSUPPORTED_OPERATION` — 셋 다 `ResolutionStatus` 에
  있고 `ValidationCode` 에 없다).
- **45개 멤버가 한 번도 읽히지 않는다** — 코드의 역할이 보고이므로, 보고를
  더 정확히 하려고 멤버를 늘리는 것은 비용이 이득보다 크다.

### Q8. 새 `ValidationCode` 가 실제로 필요한 semantic 이 있는가?

**없다.** §12 의 일곱 조건을 모두 통과하는 후보가 **0개**다. 빠지는 조건은
언제나 같은 셋이다.

- 조건 3 「`status` 만으로도 의미를 잃는다」 → **거짓.** 상태가 들고 있다.
- 조건 4 「consumer 가 그 차이를 필요로 한다」 → **거짓.** 45개가 안 읽힌다.
- 조건 6 「기존 ADR/TODO 로 설명 안 됨」 → **거짓.** 3-E-26 이 설명한다.

### Q9. 새 enum 이 필요하다면 정확히 어떤 semantic 인가? (만들지는 않는다)

**필요하지 않다고 판정했다.** 다만 "만약 나중에 코드만으로 보고를 완성하고
싶어진다면" 어떤 semantic 이 비어 있는지는 적어 둔다 — **설계 제안이 아니라
빈칸의 기록**이다.

| 비어 있는 semantic | 지금 어디에 적혀 있는가 | 몇 자리 |
|---|---|---|
| "발동 조건이 거짓이다" (후보 선택과 무관) | `ActivationStatus.CONDITION_FALSE` · `ResolutionStatus.CONDITION_FALSE` | 2 |
| "문맥이 서로 어긋난다" (구조 오류) | `ResolutionStatus.INVALID_CONTEXT` · `INVALID_OPERATION` | 6 |
| "실행 중 예외가 났다" | `*Status.EXECUTION_ERROR` | 3 |
| "지금 허가된 후보 목록에 없다" | `DuelStep.accepted=False` | 1 |
| "이 실행기가 그 조작을 다루지 못한다" | `ResolutionStatus.UNSUPPORTED_OPERATION` | 8 |

다섯 모두 **상태 쪽에 정확한 이름이 이미 있다.** 그래서 비어 있는 것은
`ValidationCode` 쪽 어휘뿐이고, 그 빈칸이 지금 아무 결정도 막지 않는다.

### Q10. AI/Search/Simulation 에 영향이 있는가?

**선택에는 없다. 집계와 라벨에는 있다.**

- 없는 것: 불법 수를 고르지 않고, 점수가 바뀌지 않고, 순위가 바뀌지 않는다
  (`UNKNOWN`/`REFUSED` 의 `ordering_key` 동일). `RULE_NOT_IMPLEMENTED !=
  LOSS != 0` 유지. 원래 코드는 `SimulationResult.code` 에 보존된다.
- 있는 것: `_UNKNOWN_CODES` 가 `RULE_NOT_IMPLEMENTED` 를 품고 있으므로
  **확실한 거부가 `SimulationStatus.UNKNOWN` 으로 집계된다.** 개발자가
  `SearchDecision` 흔적을 읽을 때 "모른다" 와 "안 된다" 를 구분하지 못한다.
  M1·M2 를 고치면 그 수가 `REFUSED` 로 옮겨 간다 — **다음 Phase 가 함께
  측정해야 하는 영향이다.**

### Q11. 지금 production 수정이 필요한가?

**필요하지 않다.** 판정 0건 변경, 안전 invariant 열두 항목 유지, 새 enum
불필요, `GateVerdict`/`legal_actions`/`Duel.apply` 결과 모두 동일.

그래도 적어 둔다 — M1(2줄) · M2(executor 1줄 + resolution 1줄) · M3(1줄)
은 **다섯 줄짜리 치환**이고, 3-E-26 이 트리거 계층에서 한 것과 같은 종류의
변경이다. `activation.py:637` 만 `_AVAILABILITY_REFUSAL` 표를 갈라야 하므로
더 크다.

**이번 Phase 에서는 하나도 하지 않았다** (§0 · §27).

### Q12. 다음 단계는 — 추가 audit / 기존 code 정리 / 새 enum 설계 audit / 실제 implementation 중 무엇인가?

**기존 code 정리다** (§21 의 Phase 3-E-38).

| 후보 | 판단 |
|---|---|
| 추가 audit | **아니다.** 48개 멤버와 58개 사용처를 전수로 봤고, 남은 질문이 "고칠 것인가" 뿐이다 |
| **기존 code 정리** | **그렇다.** 다섯 줄 + 표 하나. 고칠 자리와 고칠 코드가 모두 확정되어 있다 |
| 새 enum 설계 audit | **아니다.** 새 멤버가 필요한 semantic 이 0개다 (Q8) |
| 실제 implementation (특수 소환 절차 · 제물 · 타이밍) | **그 뒤다.** 코드 어휘가 정리되지 않은 상태에서 규칙을 더하면 거친 코드가 더 늘어난다 — 3-E-36 이 같은 결론을 냈고 이번 Phase 가 확정했다 |

순서를 못 박아 둔다.

1. **Phase 3-E-38** — M1·M2·M3 코드 선택 교정 + `_UNKNOWN_CODES` 집계 영향
   측정. **MINIMAL FIX**, 새 enum 금지.
2. 그 뒤 J\* 10곳을 다시 본다 — 고친 뒤에도 거친 코드가 남아 있는 것이
   **보기에 불편한 수준인지 실제 보고를 막는 수준인지**는 1번 뒤에 판단이
   쉬워진다.
3. 그 다음이 실제 규칙 구현이다.

**이 Phase 는 여기서 멈춘다. 다음 Phase 는 임의로 진행하지 않는다.**
