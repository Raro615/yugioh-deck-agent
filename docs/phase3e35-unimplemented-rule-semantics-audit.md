# Phase 3-E-35 — `UnimplementedRule` 의미 · 사용처 전수 감사

**최종 판정: A. CORRECT_RULE_NOT_IMPLEMENTED_SEMANTICS**
(부수적으로 `UnimplementedRule` **자체는** 사실상 **C. 조건부 도달**이다 — §13)

**production diff = 0.** `engine/` · `agent/` · `core/` · `analysis/` ·
`sources/` 를 한 글자도 바꾸지 않았다.

---

## 1. Phase / Base / 실제 HEAD

| 항목 | 값 |
|---|---|
| Phase | 3-E-35 (AUDIT-ONLY) |
| 브랜치 | `claude/pensive-goodall-te1egy` |
| 감사 시작 HEAD | **`1804fe5`** — "Phase 3-E-34 보고서: 고의 위반 11건 + test_12 의 실제 구멍 수정 (AUDIT-ONLY)" |
| 그 직전 | `f0e466a` Phase 3-E-34 · `c87f3e4` Phase 3-E-33 보고서 |
| 작업 트리 | 깨끗함 (`git status --porcelain` 비어 있음) |
| 3-E-34 보고서 | `docs/phase3e34-engine-condition-none-contract-audit.md` (46,196 B) |
| 3-E-34 감사 테스트 | `tests/test_engine_condition_none_contract_audit.py` (17개) |
| `c87f3e4..HEAD` production diff | **0** |

프롬프트의 commit 을 믿지 않고 저장소에서 확인했다. `reset`/`checkout` 하지
않았다.

## 2. BLOCKER

**없다.** 감사를 끝까지 수행했고, production 변경이 필요해 보이는 자리를
발견했어도 고치지 않고 기록했다 (§18 · §19).

측정 중에 **내 가정 세 개가 틀렸다**는 것을 발견해 고쳤다. 세 번 모두
숫자나 실행 결과가 먼저 말했다.

1. **§8 의 전제가 틀렸다.** 프롬프트는 "`library.py` 에서
   `UnimplementedRule` 이 왜 존재하는가" 를 묻지만 **하나도 없다** (0개).
   그래서 §8 은 "왜 있는가" 대신 **"왜 없는가, 그리고 그것이 문제인가"** 에
   답한다 (§10).
2. **`ActivationResult.missing` 은 `missing_rules()` 가 아니다.**
   `engine/activation.py:690` 이 `unknown_reasons` 를 넣으므로, 정보 부족
   쪽에도 문장이 들어 있다 (`'#9999 가 관측에 보이지 않음 (가려진 존)'`).
   처음에 "정보 부족 쪽은 `missing` 이 `None`" 이라고 썼다가 테스트가 잡았다.
   코드를 가르는 근거는 `missing` 이 아니라 **`missing_rules()`** 다.
3. **내 probe 의 import 순서가 순환 import 를 일으켰다** —
   `engine.special_summon` 을 `engine.effect` 보다 먼저 불렀다. production
   버그가 아니라 probe 의 문제이고, probe 를 고쳤다.

## 3. Engine 변경 여부

```
$ git diff --stat 1804fe5..HEAD -- engine/ agent/ core/ analysis/ sources/
(출력 없음)
```

더한 파일은 둘뿐이다.

- `tests/test_unimplemented_rule_semantics_audit.py` (새 파일, 17개 테스트)
- `docs/phase3e35-unimplemented-rule-semantics-audit.md` (이 문서)

기존 테스트를 삭제·수정하지 않았다. `skip` 을 더하지 않았고 assertion 을
약하게 바꾸지 않았다. 새 enum · 새 `Condition` 클래스 · 새 필드를 만들지
않았다. **미구현 규칙을 하나도 구현하지 않았다.**

## 4. `UnimplementedRule` 정의

```python
# engine/condition/model.py:131
@dataclass(frozen=True, slots=True)
class UnimplementedRule(Condition):
    """
    **아직 판정할 규칙이 없다.** 언제나 ``UNKNOWN`` 이다.

    체인 · 트리거 · 타이밍 · 소환 절차처럼 시스템 자체가 없는 조건을
    솔직하게 표현한다. ``rule`` 에 무엇이 없는지 적어서, 나중에 어느 단계가
    이 조건을 살릴 수 있는지 추적할 수 있게 한다.
    """

    rule: str
    """없는 규칙 계층의 이름. 예: ``"chain (Phase 2-F)"``."""
```

| 항목 | 값 |
|---|---|
| 종류 | `Condition` 하위 클래스. **enum 도 예외도 아니다** |
| 필드 | `rule: str` **하나.** 기본값 없음 → 이름 없이 만들 수 없다 |
| 불변성 | `frozen=True, slots=True` |
| 등식 | `rule` 문자열 하나로 정해진다 |
| `evaluate()` | 본문이 `return ConditionResult.UNKNOWN` **한 줄**. 판을 **보지 않는다** (`evaluate(None, None)` 도 `UNKNOWN`) |
| `missing_rules()` | `(self.rule,)` |
| `unknown_reasons()` | `(f"규칙 미구현: {self.rule}",)` |
| `canonical_state()` | `("unimplemented", self.rule)` |
| `to_dict()` | `{"kind": "unimplemented", "rule": self.rule}` |
| `describe_ko()` | `f"판정 불가({self.rule})"` |

**보존하는 정보는 문자열 하나뿐이다.** rule id · source · context · 카드
번호 · Phase 번호를 담는 칸이 **없다**. 그래서 §5 가 묻는 "규칙이 없다" 와
"규칙이 있지만 구현되지 않았다" 를 **구조적으로 구분하지 않는다** — 둘을 같은
문자열에 적는다. 다만 실제로 쓰인 두 문자열은 모두 후자다 (§14).

### 기본 계약 — 이것이 진짜 semantic 이다

```python
# engine/condition/model.py:82  Condition.missing_rules
    """
    ``UNKNOWN`` 의 원인이 **없는 규칙 계층**이라면 그 이름들.

    비어 있으면 "정보가 없어서 모른다" 는 뜻이다. 둘은 다른 사실이고,
    앞의 것은 판이 바뀌면 풀리지만 뒤의 것은 코드가 생겨야 풀린다.
    """
    return ()
```

**`UnimplementedRule` 은 이 기본값을 뒤집는 가장 단순한 구현**이다. 그래서
`Always(ConditionResult.UNKNOWN)` 과 비교하면 차이가 선명하다 — 둘 다
`UNKNOWN` 이지만 전자만 규칙 이름을 낸다. `Always` 의 docstring 이 직접
그렇게 적는다: "``UNKNOWN`` 을 넣을 수도 있지만, 그럴 때는 대개
:class:`UnimplementedRule` 이 더 정확하다 — 이유를 함께 남기기 때문이다."

## 5. `RULE_NOT_IMPLEMENTED` 관계

§6 의 네 선택지 중 답은 **C + B 의 혼합**이다.

> **계층이 다르다.** `UnimplementedRule` 은 **조건 객체**이고
> `RULE_NOT_IMPLEMENTED` 는 **판정 코드**다. 그리고 전자는 후자를 만드는
> **여러 방법 중 하나**일 뿐이며, 실제로는 **가장 드물게 쓰이는** 방법이다.

측정이 그것을 못 박는다.

| 항목 | 수 |
|---|---|
| `RULE_NOT_IMPLEMENTED` 가 production (`engine/` + `agent/`) 에 등장 | **75곳** (16파일) |
| `UnimplementedRule(...)` production 생성 | **2곳** (1파일, 같은 함수) |
| 비율 | 생성 1건당 코드 등장 **37.5건** |

파일별 `RULE_NOT_IMPLEMENTED` 등장: `effect/executor.py` 22 · `trigger.py` 11 ·
`activation.py` 7 · `trigger_chain.py` 6 · `effect/resolution.py` 5 ·
`action_validation.py` 5 · `validation.py` 3 · `duel.py` 3 ·
`action_execution.py` 3 · `turn_progression.py` 2 · `response.py` 2 ·
`payment.py` 2 · `special_summon.py` 1 · `chain.py` 1 ·
`activation_timing.py` 1 · `agent/simulation.py` 1.

### 실제 call path

`UnimplementedRule` 을 **지나는** 경로:

```
ActionValidator.requirements(special_summon)
  → Requirement(UnimplementedRule("special-summon-condition (카드마다 다르다)"),
                ValidationCode.RULE_NOT_IMPLEMENTED, detail)
  → ActionValidator._check_requirements
  → evaluate() = UNKNOWN
  → condition.missing_rules(view, context) = ("special-summon-condition ...",)
  → ValidationResult.unknown(RULE_NOT_IMPLEMENTED, ..., missing_rule=rules[0],
                             notes=pending)
  → ActionExecutor._refuse → ActionStatus.UNKNOWN_ACTION (missing=verdict.missing_rule)
```

`UnimplementedRule` 을 **지나지 않는** 경로 — 같은 코드가 나온다:

```
# 1. 종류별 "마지막 한 걸음이 없다"  (action_validation.py:304)
ActionValidator.validate(...)  모든 요구 통과
  → action.kind not in _COMPLETE_RULES
  → ValidationResult.unknown(RULE_NOT_IMPLEMENTED,
                             missing_rule=_MISSING_RULE[action.kind])
     예: activate_card → 'activation-timing (Phase 2-C/2-F)'

# 2. 커스텀 조건이 조건부로 규칙 이름을 낸다  (action_validation.py:1445 · 1502)
_NormalSpellActivation.missing_rules / _NormalSummonProcedure.missing_rules
  → _check_requirements 가 같은 방식으로 RULE_NOT_IMPLEMENTED 를 고른다

# 3. 발동 · 해결 계층  (activation.py:681 · executor.py:986)
definition.activation.missing_rules(...) 가 비어 있지 않으면 RULE_NOT_IMPLEMENTED

# 4. 목록 멤버십 거절  (duel.py:686)
Duel.apply(action) 에서 action not in legal.allowed
  → DuelStep(accepted=False, code=RULE_NOT_IMPLEMENTED,
             "... 는 지금 허가된 행위가 아닙니다.")

# 5. 문자열 상수를 그대로 적는 자리 (UnimplementedRule 없음)
action_validation.py:420 'shared-library effect parsing (ADR-006)'
activation_timing.py:523 · cost/validation.py:61 · priority.py:517
summon_rules.py:190 'tribute-summon (제물 선택 · 릴리스)' · :204
turn_progression.py:476 · :555
```

**5번째 경로(`duel.py:686`)는 가장 느슨한 사용이다.** 거기서
`RULE_NOT_IMPLEMENTED` 는 "목록에 없다" 를 뜻하고, 진짜 이유는 페이즈가
아닐 수도, 내 턴이 아닐 수도, 규칙이 없을 수도 있다. 다만 그 자리는
**허가를 주지 않고 판도 바꾸지 않으므로** 안전 쪽으로 틀린다 (§16). 기록만
남긴다 — §18 의 신규 ID 조건을 충족하지 않는다.

## 6. `missing_rule` / `missing_rules` 관계

§7 이 "네 가지를 하나로 취급하면 안 된다" 고 한 그대로다. **타입이 전부
다르다.** 그리고 측정하다 **다섯 번째**를 찾았다.

| # | 이름 | 무엇인가 | 타입 | 무엇을 담는가 |
|---|---|---|---|---|
| 1 | `UnimplementedRule` | **클래스** (`Condition` 하위) | — | `rule: str` |
| 2 | `Condition.missing_rules()` | **메서드 (프로토콜)** | `tuple[str, ...]` | 없는 규칙 계층 이름들. **비어 있으면 "정보가 없어서"** |
| 3 | `ValidationResult.missing_rule` | **필드** | `str \| None` | 규칙 이름 **하나** (`rules[0]`) |
| 4 | `ValidationCode.RULE_NOT_IMPLEMENTED` | **enum 멤버** | — | 판정 코드 |
| 5 | `ActivationResult.missing` / `EffectResult.missing` | **필드** | `str \| None` | **`unknown_reasons` 를 이어 붙인 것** — 규칙 이름이 아니다 |

### §24 가 요구한 첫 번째 표 — 표현별 정리

| 표현 | 의미 | 생성 위치 | 소비 위치 | production 도달 | `UNKNOWN` 과 관계 | 최종 판정 |
|---|---|---|---|---|---|---|
| `UnimplementedRule` (클래스) | 판정할 규칙 계층이 없다. **무조건** | `action_validation.py:570` · `:581` (production 2곳) | `_check_requirements` → `missing_rules()` | **조건부** — `ActionValidator` 직접 호출 시 | 언제나 `UNKNOWN` **(부분집합)** | **정확 — CASE A** |
| `Condition.missing_rules()` (기본) | "정보가 없어서 모른다" | `condition/model.py:82` | 다섯 곳 (`activation` · `executor` · `action_validation` · `trigger` ×2) | **도달 — 매번** | `UNKNOWN` 의 **까닭 판별자** | **정확** |
| `_NormalSummonProcedure.missing_rules()` | 제물·소환제약 계층이 없다. **조건부** | `action_validation.py:1502` | `_check_requirements` | **도달 — `legal_actions` 마다** | `UNKNOWN` 일 때만 비지 않는다 | **정확 — CASE A** |
| `_NormalSpellActivation.missing_rules()` | 발동 타이밍 계층이 없다. **조건부** | `action_validation.py:1445` | 같음 | **도달 — 매번** | 같음 | **정확 — CASE A** |
| `ValidationResult.missing_rule` (필드) | 규칙 이름 **하나** (`rules[0]`) | `unknown()` 생성자만 받는다 | `ActionExecutor` · `Duel` · `payment` · `response` 등 | **도달** | `UNKNOWN` 전용 — `invalid()` 에는 자리가 없다 | **정확** |
| `ActivationResult.missing` / `EffectResult.missing` (필드) | **`unknown_reasons` 를 이어 붙인 것** | `activation.py:690` · `executor.py:993` | 호출자 · 보고 | **도달** | 두 까닭 **모두** 채워진다 | **이름이 혼동을 부른다** (§18 기록 2) |
| `ValidationCode.RULE_NOT_IMPLEMENTED` (enum) | 판정 코드 | **75곳** (16파일) | `agent/simulation.py` `_UNKNOWN_CODES` 등 | **도달 — 매번** | `UNKNOWN` 안에서만 나온다 | **대부분 정확, `duel.py:686` 은 느슨** |
| `UnimplementedCost` (클래스) | 표현할 수 없는 비용 | **production 0곳** | `CostValidator.validate` (live) | **미도달** | `COST_NOT_IMPLEMENTED` (다른 코드) | **dormant A** |
| `SummonAssessment.missing_rule` (필드) | 소환 판정의 규칙 이름 | `summon_rules.py:190` · `:204` (문자열) | `_NormalSummonProcedure.missing_rules` | **도달** | `UNDETERMINED`/`NEEDS_TRIBUTE` 에서만 | **정확 — CASE A** |

5번이 새로 찾은 혼동 지점이다. `engine/activation.py:690` 은
`missing="; ".join(evaluated.unknown_reasons) or None` 이므로, **정보 부족
쪽에도 `missing` 이 채워진다**. 즉 `ValidationResult.missing_rule` 과
`ActivationResult.missing` 은 **이름이 비슷하고 담는 것이 다르다.**

> **코드를 가르는 근거는 어느 `missing` 도 아니라 `missing_rules()` 다.**
> `activation.py:681` · `executor.py:986` · `action_validation.py:346` ·
> `trigger.py:993` · `trigger.py:1432` 다섯 곳 모두 그 메서드를 직접 부른다.

그리고 비용 계층에는 **다른 이름의 형제**가 있다.

| 형제 | 코드 | production 생성 |
|---|---|---|
| `UnimplementedRule` (조건) | `RULE_NOT_IMPLEMENTED` | 2곳 |
| `UnimplementedCost` (비용) | **`COST_NOT_IMPLEMENTED`** | **0곳** |
| `SummonAssessment.missing_rule` (소환 판정) | `RULE_NOT_IMPLEMENTED` | 2곳 (문자열 리터럴) |

### `missing_rules()` 를 구현하는 production 클래스 — 7개

| 위치 | 클래스 | 돌려주는 것 |
|---|---|---|
| `engine/condition/model.py:82` | `Condition` (기본) | `()` |
| `engine/condition/model.py:151` | `UnimplementedRule` | `(self.rule,)` — **무조건** |
| `engine/condition/model.py:195` | `And` | 자식들의 합집합 (결과가 `UNKNOWN` 일 때만) |
| `engine/condition/model.py:243` | `Or` | 같음 |
| `engine/condition/model.py:275` | `Not` | 자식의 것 그대로 |
| `engine/action_validation.py:1445` | `_NormalSpellActivation` | **조건부** — 범위 밖 항목의 규칙 이름들 |
| `engine/action_validation.py:1502` | `_NormalSummonProcedure` | **조건부** — `assess_normal_summon(...).missing_rule` |

**이것이 이 Phase 의 가장 중요한 발견이다.** `missing_rules()` 는
`UnimplementedRule` 의 전유물이 아니라 **프로토콜**이고, 두 production
조건이 그것을 **조건부**로 구현한다. `UnimplementedRule` 은 무조건
`UNKNOWN` 이라 그렇게 할 수 없다.

## 7. `UNKNOWN` 관계

§10 이 묻는 관계는 이렇게 정리된다.

| 사실 | 표현 | `evaluate()` | `missing_rules()` | 코드 |
|---|---|---|---|---|
| 규칙을 알지만 **정보가 없다** | 관측 밖을 묻는 조건 (예: `IsMonster(InstanceId(9999))`) | `UNKNOWN` | `()` | `INFORMATION_UNAVAILABLE` |
| **규칙 자체가 없다** | `UnimplementedRule("...")` | `UNKNOWN` | `(rule,)` | `RULE_NOT_IMPLEMENTED` |
| 이유 없이 모른다 | `Always(ConditionResult.UNKNOWN)` | `UNKNOWN` | `()` | `INFORMATION_UNAVAILABLE` |

즉 **`UnimplementedRule` ⊂ `UNKNOWN`** 이고, `UNKNOWN` 안에서 까닭만 갈린다.
**상태는 한 칸도 움직이지 않는다.**

### §10 이 찾으라고 한 네 가지 잘못된 변환 — **하나도 없다**

| 변환 | 존재하는가 | 근거 |
|---|---|---|
| `RULE_NOT_IMPLEMENTED` → `UNKNOWN` | **해당 없음** (애초에 `UNKNOWN` 안의 코드다) | 상태와 코드가 다른 축이다 |
| `UNKNOWN` → `RULE_NOT_IMPLEMENTED` | **아니다** — 조건에게 되묻는다 | `missing_rules()` 가 비면 `INFORMATION_UNAVAILABLE` |
| `UNKNOWN` → `FALSE` | **없다** | `test_07` · 3-E-24~34 가 반복 고정 |
| `RULE_NOT_IMPLEMENTED` → `FALSE` | **없다** | `ValidationResult.invalid(...)` 에 그 코드를 넣는 production 호출이 **0건** (AST 전수, `test_16`) |

그리고 구조가 그것을 막는다 — `ValidationResult` 의 생성자 중
**`unknown()` 만** `missing_rule` 매개변수를 받는다. `invalid()` · `valid()`
에는 규칙 이름을 적을 자리가 **없다**.

## 8. `INFORMATION_UNAVAILABLE` 관계

§11 이 요구한 구분이 **한 줄의 코드**로 이루어진다.

```python
# engine/activation.py:681 (실행기 executor.py:986 도 같은 모양)
unimplemented = definition.activation.missing_rules(view, context)
return self._fail(
    ActivationStatus.CONDITION_UNKNOWN,          # ← 상태는 그대로
    ...
    ValidationCode.RULE_NOT_IMPLEMENTED
    if unimplemented
    else ValidationCode.INFORMATION_UNAVAILABLE,  # ← 코드만 갈린다
    ...
)
```

```python
# engine/action_validation.py:346 — 같은 방법
rules = requirement.condition.missing_rules(self._view, context)
if missing is None and rules:
    missing = rules[0]
...
if missing is not None:
    return ValidationResult.unknown(RULE_NOT_IMPLEMENTED, ..., missing_rule=missing, notes=pending)
return ValidationResult.unknown(INFORMATION_UNAVAILABLE, ..., notes=pending)
```

**검증기가 추측하지 않는다 — 조건 자신이 안다.** 주석이 그렇게 적는다:
"'정보가 없어서' 와 '규칙이 없어서' 는 다른 사실이다. 조건 자신이 안다 —
검증기가 추측하지 않는다."

실측으로 확인했다 (`test_06`).

| 입력 | 상태 | 코드 |
|---|---|---|
| `UnimplementedRule("없는 규칙")` | `CONDITION_UNKNOWN` | `RULE_NOT_IMPLEMENTED` |
| `IsMonster(InstanceId(9999))` | `CONDITION_UNKNOWN` | `INFORMATION_UNAVAILABLE` |

발동기와 해결기가 **같은 답**을 낸다 (3-E-26 이 세운 고정).

**주의 — 한 군데서 둘이 합쳐진다.** `agent/simulation.py` 의
`_UNKNOWN_CODES` 는 두 코드를 모두 `SimulationStatus.UNKNOWN` 으로 보낸다
(§15). 그것은 유실이 아니라 계층에 맞는 축약이다 — 원래 코드가
`SimulationResult.code` 에 그대로 남는다.

## 9. `INVALID` / `EXECUTION_FORBIDDEN` 관계

§12 가 요구한 구분을 실행으로 확인했다.

| 상황 | 결과 | 코드 | 누가 정하는가 |
|---|---|---|---|
| 규칙이 금지한다 | `INVALID` | 요구별 코드 (예: `SOURCE_WRONG_CARD_TYPE`) | 조건이 `FALSE` |
| 규칙을 구현하지 않았다 | `UNKNOWN` | `RULE_NOT_IMPLEMENTED` | `missing_rules()` 가 비어 있지 않다 |
| 이 **근거로는** 실행하지 않는다 (ADR-004) | `FORBIDDEN` | `EXECUTION_FORBIDDEN` | `provenance.is_forbidden` |
| 후보가 아니다 | `INELIGIBLE` | `CANDIDATE_NOT_ELIGIBLE` | 트리거 조건이 `FALSE` |

세 쌍 모두 **다른 enum 멤버**이고 변환 경로가 없다.

### `FALSE` 가 `UNKNOWN` 을 이긴다 — 실측

몬스터가 아닌 카드로 특수 소환을 물으면 요구 목록에 `IsMonster`(FALSE)와
`UnimplementedRule` ×1~2가 **함께** 들어 있다. 결과는
`INVALID` + `SOURCE_WRONG_CARD_TYPE` 이고 **`missing_rule` 은 `None`** 이다
(`test_08`).

> **미구현이 확실한 거부를 덮지 않는다.** 그리고 거부에는 규칙 이름을 적지
> 않는다 — 모르는 것이 아니기 때문이다.

출처 금지도 **조건보다 먼저** 막는다 (3-E-34 가 고정한 관문 순서). 조건이
`UnimplementedRule` 이어도 `TEXT_DERIVED` 정의는 `CONDITION_UNKNOWN` 이
아니라 `FORBIDDEN`/`UNVERIFIED`/`NOT_IMPLEMENTED` 로 막힌다 (`test_09`).

## 10. `library.py` 조사

**§8 의 전제가 틀렸다. `engine/effect/library.py` 에는 `UnimplementedRule`
이 하나도 없다 (문자열 등장 0회).**

§8 의 여섯 질문에 그 사실로 답한다.

| # | 질문 | 답 |
|---|---|---|
| 1 | `library.py` 에서 `UnimplementedRule` 이 왜 존재하는가 | **존재하지 않는다** (0개) |
| 2 | 해당 effect 가 engine execution 에 들어가는가 | 해당 없음 |
| 3 | "아직 실행할 수 없다" 는 metadata 인가 | 해당 없음 — 그 역할은 `EffectProvenance` 와 `EffectImplementationRegistry` 가 한다 |
| 4 | Lua 원문에 규칙 정보가 있는가 | 있다 (3-E-33: `SetCondition` 12,437 블록) |
| 5 | analysis 단계가 보존하는가 | 보존한다 (`ActivationCondition.has_condition_function` / `raw` / `unparsed`) |
| 6 | execution layer 가 읽는가 | **읽지 않는다** — `analysis` → `EffectDefinition` 컴파일러가 없다 (STRUCTURAL-7) |

등재 16개 중 `activation` 이 있는 것은 8개이고 **여덟 개 전부 판정 가능한
조건**이다 — `missing_rules()` 가 모두 빈 튜플이다 (`test_13`).

이것은 3-E-33 (`UnimplementedRule` 0개) 과 3-E-34 (같은 측정) 가 두 번
가리킨 공백이고, 이 Phase 가 그것을 확정한다.

> **"옮기지 못한 조건을 `UNKNOWN` 으로 적는 수단" 이 있는데 쓰이지 않는다.**
> `ObservationGrant.condition` 의 docstring 은 그렇게 적으라고 명시하는데
> (3-E-34 §7), 등재 효과 쪽에는 그 문장이 없고 실제로 쓰이지도 않는다.

**그러나 그것이 지금 결함인가 — 아니다.** 3-E-33 `test_11` 이 측정한 대로
`SetCondition` 이 있으면서 `activation=None` 인 등재 효과는 **0개**다. 즉
"옮기지 못한 조건" 이 **아직 하나도 없다.** `UnimplementedRule` 이 비어 있는
것은 **빈칸이 아니라 쓸 일이 없었다는 뜻**이다. 등재가 16개에서 늘어나면
그때 쓰일 자리다.

## 11. Lua corpus 대조

§9 의 세 CASE 로 production 의 두 생성처와 두 커스텀 조건을 분류했다.

| 사례 | 출처 | Lua 쪽 사실 | CASE |
|---|---|---|---|
| `special-summon-condition (카드마다 다르다)` | `action_validation.py:581` | Lua 에 카드별 특수 소환 절차가 **있다** (`s.spcon` · `s.sprocedure` 등). 엔진에 그 계층이 없다 | **A** — 진짜 `RULE_NOT_IMPLEMENTED` |
| `special summon from {zone} (Phase 2-T 범위 밖)` | `action_validation.py:570` | `SPECIAL_SUMMON_FROM_ZONES = {HAND, GRAVE}` 뿐이고, 덱·제외·엑스트라에서 나오는 특수 소환은 **실제로 있다** | **A** |
| `tribute-summon (제물 선택 · 릴리스)` | `_NormalSummonProcedure` → `summon_rules.py:190` | 레벨 5+ 는 제물이 필요하다 (RULE-SUMMON-011). 치르는 절차가 없다 | **A** |
| `summoning-condition (카드 텍스트의 소환 제약)` | 같음 → `summon_rules.py:204` | 효과 몬스터는 카드 자신의 제약이 있을 수 있다 | **A** |
| `monster-activation-timing (...)` | `_NormalSpellActivation` | 기동/유발/플립/유발즉시 분류가 엔진의 카드 정의에 없다 | **A** |
| `trap-activation-timing (...)` | 같음 | 함정의 유발 조건을 효과마다 구분할 수 없다 — "`SetCode(EVENT_*)` 가 `EffectDefinition` 에 없다" | **A** (3-E-31/32 가 측정한 그 경계) |
| 엑스트라 덱 · 의식 · 토큰의 일반 소환 | `_NormalSummonProcedure` → `FALSE` | 규칙이 **금지한다** | **CASE B 아님 — 거부다.** `missing_rules()` 가 빈 튜플 |
| 관측 밖 카드를 묻는 조건 | `IsMonster(InstanceId(9999))` | 정보가 없다 | **B** → `INFORMATION_UNAVAILABLE` |

**측정된 모든 `UnimplementedRule`/`missing_rules` 사례가 CASE A 다.** CASE B
는 `missing_rules()` 가 빈 튜플이 되어 다른 코드로 가고, CASE C (규칙은
있는데 현재 문맥에서 판정 불가) 는 `_NormalSummonProcedure` 의 `UNDETERMINED`
갈래가 담당하며 거기서도 `missing_rule` 유무로 다시 갈린다.

> **이름만 보고 판정하지 않았다.** `_NormalSummonProcedure` 가 같은
> `UNKNOWN` 안에서 "제물 절차가 없어서" (규칙 이름 있음) 와 "카드 정의를 못
> 읽어서" (빈 튜플) 를 가르는 것을 실제로 돌려 확인했다 (`test_14`).

## 12. Production reachability

§13 이 요구한 경로를 하나씩 확인했다.

| 단계 | `UnimplementedRule` 을 생성/소비하는가 |
|---|---|
| `Duel.legal_actions()` | **생성 안 함.** `SPECIAL_SUMMON` 을 allowed 에도 withheld 에도 넣지 않는다 (실측) |
| `Duel.apply(action)` | **조건까지 가지 않는다.** `action not in legal.allowed` 멤버십 관문이 먼저 거절한다 (`RULE_NOT_IMPLEMENTED`, 판 변화 없음) |
| `ActionValidator.requirements()` | **생성한다** — `_special_summon` 이 두 개를 넣는다 |
| `ActionValidator.validate()` | **소비한다** — `UNKNOWN` + `RULE_NOT_IMPLEMENTED` + `missing_rule` |
| `ActionExecutor` | `verdict.missing_rule` 을 읽어 `ActionStatus.UNKNOWN_ACTION` 으로 전한다. **`EXECUTED` 가 되지 않는다** |
| `EffectActivator` | `definition.activation.missing_rules()` 를 부른다. 등재 효과에 `UnimplementedRule` 이 없으므로 **지금은 타지 않는다** |
| `EffectExecutor` | 같음 |
| `TriggerCollector` / `TriggerEligibilityJudge` | `condition.missing_rules()` 를 부른다. `TriggerSpec` 이 production 에서 0개 생성되므로 **타지 않는다** (3-E-29/31/34) |
| `Chain` | 조건을 직접 읽지 않는다 |
| `Simulator` | 코드만 본다 (`_UNKNOWN_CODES`). 조건 객체를 보지 않는다 |

### 실측 (`test_10` · `test_11`)

```
MZONE 앞면 몬스터로 SPECIAL_SUMMON 을 물으면:
   요구 목록 = ControllerIs · IsMonster · ZoneHasFreeSlot
             + UnimplementedRule('special summon from MZONE (Phase 2-T 범위 밖)')
             + UnimplementedRule('special-summon-condition (카드마다 다르다)')
   → validity = unknown
   → code     = rule_not_implemented
   → missing_rule = 'special summon from MZONE (Phase 2-T 범위 밖)'   (= rules[0])
   → notes    = 2개 — **두 까닭이 모두 남는다**
   → permits_execution = False
```

```
Duel.legal_actions():
   allowed  = {end_phase}            ← SPECIAL_SUMMON 없음
   withheld = {activate_card}        ← SPECIAL_SUMMON 없음
Duel.apply(special_summon):
   accepted = False
   code     = rule_not_implemented
   reason   = 'special_summon 는 지금 허가된 행위가 아닙니다.'   ← 멤버십 거절
   state_hash 변화 = 없음
```

**정보 유실이 없다**: `missing_rule` 에는 첫 번째 규칙만 들어가지만
`notes` 에 **두 까닭이 전부** 남는다 (`UnimplementedRule.unknown_reasons` 가
`"규칙 미구현: {rule}"` 을 내므로 규칙 이름까지 보존된다). 그래서
**F. INFORMATION_LOSS 가 아니다.**

## 13. Dormant path

§14 의 여섯 갈래로 분류한다.

| 대상 | 분류 | 근거 |
|---|---|---|
| `UnimplementedRule` **클래스** | **F. 실제 production 에서 조건부로 도달 가능** | `ActionValidator` 는 production 클래스이고 실제로 생성·소비한다. 다만 그 입력(`SPECIAL_SUMMON` 행위)을 만드는 production 호출자가 없다 |
| `UnimplementedRule` 의 **두 생성처** | **A. 아직 연결하지 않은 미래 기능** | 특수 소환 절차 계층(Phase 2-T 범위 밖)이 생기면 살아난다 |
| `UnimplementedCost` | **A. 아직 연결하지 않은 미래 기능** | production 생성 **0곳**, 그러나 소비자 `CostValidator.validate` 는 live 이고 `COST_NOT_IMPLEMENTED` 를 돌려준다 |
| `TriggerSpec.condition` 의 `missing_rules` 경로 | **A** | 트리거 파이프라인 전체가 dormant (3-E-29/31) |
| `EffectDefinition.activation` 의 `missing_rules` 경로 | **F** | 코드는 live 이고 매 발동마다 불릴 수 있다. 다만 등재 효과에 `UnimplementedRule` 이 없어 지금은 결과가 항상 빈 튜플이다 |
| `library.py` 의 `UnimplementedRule` | **없음** | 0개 (§10) |

**dead code 는 하나도 없다.** `D. dead code` 로 분류한 항목이 0개이고,
`C. 테스트 전용` 도 0개다 (`UnimplementedCost` 는 생성이 테스트 전용이지만
소비자가 production 이므로 A 다).

## 14. 실제 사례 10개 이상 — **필수 표**

| # | 사례 | source | rule | 생성 위치 | consumer | production 도달 | 의미 | 판정 |
|---|---|---|---|---|---|---|---|---|
| 1 | 특수 소환 조건 | `UnimplementedRule` | `special-summon-condition (카드마다 다르다)` | `action_validation.py:581` | `_check_requirements` → `ValidationResult.unknown` | **조건부 (검증기 직접 호출)** | 카드별 절차 계층이 없다 | **CASE A** |
| 2 | 범위 밖 자리에서의 특수 소환 | `UnimplementedRule` | `special summon from MZONE (Phase 2-T 범위 밖)` | `action_validation.py:570` | 같음 | 같음 | `SPECIAL_SUMMON_FROM_ZONES` 가 `{HAND, GRAVE}` 뿐 | **CASE A** |
| 3 | 제물 소환 | `_NormalSummonProcedure.missing_rules` | `tribute-summon (제물 선택 · 릴리스)` | `summon_rules.py:190` (문자열) | `_check_requirements` | **도달 — `legal_actions` 가 매번 탄다** | 제물 치르는 절차가 없다 | **CASE A** |
| 4 | 효과 몬스터의 자기 제약 | 같음 | `summoning-condition (카드 텍스트의 소환 제약)` | `summon_rules.py:204` | 같음 | 같음 | 카드 텍스트 제약을 못 읽는다 | **CASE A** |
| 5 | 몬스터 효과 발동 타이밍 | `_NormalSpellActivation.missing_rules` | `monster-activation-timing (...)` | `action_validation.py` `UNRESOLVED_TIMING_RULES` | 같음 | **도달** | 기동/유발/플립 분류가 없다 | **CASE A** |
| 6 | 함정 발동 타이밍 | 같음 | `trap-activation-timing (... SetCode(EVENT_*) 가 EffectDefinition 에 없다)` | 같음 | 같음 | **도달** | 3-E-31/32 가 측정한 경계 | **CASE A** |
| 7 | 종류별 마지막 한 걸음 | `_MISSING_RULE` 표 | `activation-timing (Phase 2-C/2-F)` | `action_validation.py:304` | `ValidationResult.unknown` | **도달 — `activate_card` 가 매번** | `UnimplementedRule` **없이** 같은 코드 | **CASE A** |
| 8 | 공유 라이브러리 효과 파싱 | 문자열 리터럴 | `shared-library effect parsing (ADR-006)` | `action_validation.py:420` | 같음 | **도달** | `UnimplementedRule` 없음 | **CASE A** |
| 9 | 우선권 동기화 | 문자열 리터럴 | `priority state synchronisation (Phase 2-F-2~)` | `priority.py:517` | `ValidationResult.unknown` | **도달** | `UnimplementedRule` 없음 | **CASE A** |
| 10 | 페이즈 건너뛰기 | 문자열 리터럴 | `페이즈 건너뛰기 (메인1 → 엔드 등)` | `turn_progression.py:555` | 같음 | **도달** | `UnimplementedRule` 없음 | **CASE A** |
| 11 | 배틀/데미지 스텝 진행 | 문자열 리터럴 | `배틀 스텝 · 데미지 스텝 안의 진행` | `turn_progression.py:476` | 같음 | **도달** | `UnimplementedRule` 없음 | **CASE A** |
| 12 | 엑시즈 소재 제거 등 | `UnimplementedCost` | (테스트에서만: `xyz material detach` 등) | **production 0곳** | `CostValidator.validate` (live) | **미도달** | 비용 모델이 담지 못한다 | **dormant A** |
| 13 | 엑스트라 덱 · 의식 · 토큰 일반 소환 | `_NormalSummonProcedure` | **없음** (빈 튜플) | — | `_check_requirements` | **도달** | 규칙이 **금지한다** | **거부 — CASE A 아님** |
| 14 | 관측 밖 카드를 묻는 조건 | `IsMonster(InstanceId(9999))` | **없음** (빈 튜플) | — | `EffectActivator._check_condition` | **도달** | 정보가 없다 | **CASE B** → `INFORMATION_UNAVAILABLE` |
| 15 | 목록에 없는 행위 | 하드코딩 코드 | **없음** | `duel.py:686` | `DuelStep` | **도달 — 매번** | "허가된 행위가 아니다" | **느슨한 사용 (§5)** |

**사례 7~11 과 15 가 핵심이다** — `RULE_NOT_IMPLEMENTED` 의 실제 production
흐름은 대부분 `UnimplementedRule` 을 **거치지 않는다.**

## 15. AI / Search 영향

**없다. `agent/` 를 수정하지 않았고, `agent/` 는 `UnimplementedRule` 을 이름조차 읽지 않는다** (문자열 0회, `test_15`).

전달 경로는 **코드 하나**다.

```
engine → DuelStep.code (ValidationCode)
      → agent/simulation.py:283  step.code in _UNKNOWN_CODES
      → SimulationStatus.UNKNOWN   (code 는 SimulationResult.code 에 보존)
      → agent/search.py:311       status is not SUPPORTED → value=None
      → SearchCandidate.ordering_key() = (1, 0, 0, canonical_state)
```

| 항목 | 확인 |
|---|---|
| `_UNKNOWN_CODES` | `RULE_NOT_IMPLEMENTED` · `COST_NOT_IMPLEMENTED` · `INFORMATION_UNAVAILABLE` · `CARD_DEFINITION_UNAVAILABLE` · `EFFECT_LIST_UNRELIABLE` **5개**. `EXECUTION_FORBIDDEN` · `CANDIDATE_NOT_ELIGIBLE` · `OK` 는 **들어 있지 않다** (거절과 섞지 않는다) |
| 두 코드가 한 상태로 합쳐지는가 | **합쳐진다** (`RULE_NOT_IMPLEMENTED` · `INFORMATION_UNAVAILABLE` → `UNKNOWN`). 둘 다 "미래를 볼 수 없다" 이므로 계층에 맞는 축약이다 |
| 사실이 사라지는가 | **아니다** — `SimulationResult.code` 가 원래 코드를 그대로 들고 있다 |
| `UNKNOWN != 0` | **유지** — `SearchCandidate.value is None`, `comparable is False` |
| `UNKNOWN != LOSS` | **유지** — `ordering_key()[0] == 1` 로 **뒤로 보낼 뿐**이고, docstring 이 "``UNKNOWN`` 은 나쁜 것이 아니라 견줄 수 없는 것이므로 뒤로 간다" 고 적는다 |
| 미래를 꾸며 내는가 | **아니다** — `gives_a_future is False` 이고 `future is not None` 이면 `SimulationError` 를 던진다 |
| `GameStateView` · `clone` · RNG · hidden information | 건드리지 않았다. 감사 테스트는 셔플하지 않는 판을 쓴다 |

## 16. Safety invariant — §18 여덟 항목

| # | invariant | 결과 | 근거 |
|---|---|---|---|
| 1 | `UNKNOWN` 을 `FALSE` 로 만들지 않는다 | **지켜진다** | `test_07` · 3-E-24~34 |
| 2 | `RULE_NOT_IMPLEMENTED` 를 `FALSE` 로 만들지 않는다 | **지켜진다** | `ValidationResult.invalid(...)` 에 그 코드를 넣는 production 호출 **0건** (AST 전수) · `invalid()` 는 `missing_rule` 을 받지 않는다 |
| 3 | `INFORMATION_UNAVAILABLE` 을 `RULE_NOT_IMPLEMENTED` 로 만들지 않는다 | **지켜진다** | 다섯 곳 모두 `missing_rules()` 에게 되묻는다. 추측하지 않는다 |
| 4 | `RULE_NOT_IMPLEMENTED` 를 `EXECUTION_FORBIDDEN` 으로 만들지 않는다 | **지켜진다** | 다른 enum 멤버 · 출처 금지는 조건보다 **앞선** 관문 |
| 5 | 미구현 때문에 임의로 **성공**하지 않는다 | **지켜진다** | `permits_execution` 은 `VALID` 일 때만 참. `ActionExecutor` 는 `UNKNOWN_ACTION` 을 돌려주고 판을 바꾸지 않는다 |
| 6 | 미구현 때문에 임의로 **실패**하지 않는다 | **지켜진다** | `FALSE` 가 `UNKNOWN` 을 이기고, 그 역은 없다 (`test_08`) |
| 7 | 숨은 정보를 추측해 해결하지 않는다 | **지켜진다** | 관측 밖은 `INFORMATION_UNAVAILABLE` · `HIDDEN_CARD` · `unchecked` 로 남는다 |
| 8 | simulation 이 임의로 0점/패배로 바꾸지 않는다 | **지켜진다** | `value=None` · `ordering_key()[0]==1` (§15) |

구조적 방어가 셋 더 있다 — `ValidationResult.__bool__` ·
`ActivationResult.__bool__` · `SummonAssessment.__bool__` 가 모두
`TypeError` 를 던진다. "모른다" 가 조용히 허가로 읽히는 것을 **타입 수준에서**
막는다.

## 17. Tests

`tests/test_unimplemented_rule_semantics_audit.py` — **17개, 전부 통과** (skip 0).

| # | 무엇을 고정하는가 | §20 요구 |
|---|---|---|
| 01 | `UnimplementedRule` 의 정의·필드·불변성·무조건 `UNKNOWN` | **Test 1** |
| 02 | `Condition.missing_rules()` 기본값 계약 · `Always(UNKNOWN)` 과의 차이 | Test 1 |
| 03 | 코드 등장 **75곳** vs 생성 **2곳** — 둘은 같은 개념이 아니다 | **Test 2** |
| 04 | 이름이 비슷한 **네 가지 + 비용/소환 형제**가 전부 다른 타입 | **Test 3** |
| 05 | `missing_rules()` override **7개** · `UnimplementedRule` 은 무조건 (AST) | Test 3 |
| 06 | `RULE_NOT_IMPLEMENTED` vs `INFORMATION_UNAVAILABLE` 실측 + `ActivationResult.missing` 이 **다른 칸**임 | **Test 4·5** |
| 07 | `UNKNOWN` 이 `FALSE` 도 허가도 되지 않고 판을 바꾸지 않는다 | §18 1·2·5·6 |
| 08 | **`FALSE` 가 `UNKNOWN` 을 이긴다** (실제 카드) | **Test 6** |
| 09 | 출처 금지는 조건보다 **앞선** 관문 | **Test 7** |
| 10 | 두 생성처가 **둘 다** 요구 목록에 들어오고 `notes` 에 두 까닭이 남는다 | **Test 8** |
| 11 | `legal_actions` 는 `SPECIAL_SUMMON` 을 만들지 않고 `apply` 는 멤버십으로 거절한다 | **Test 9** |
| 12 | `UnimplementedCost` 는 생성 0 · 소비자는 live (dormant 종류 구분) | Test 9 |
| 13 | **`library.py` 에 0개** · 등재 `activation` 8개 전부 판정 가능 | **Test 10** |
| 14 | 두 커스텀 조건이 **조건부로** 규칙 이름을 내고, 거부에는 내지 않는다 | **Test 11** |
| 15 | AI 경계에서 두 코드가 합쳐지지만 `code` 는 보존 · `UNKNOWN != 0 != LOSS` · `agent/` 는 이름조차 안 읽는다 | **Test 12** |
| 16 | 잘못된 변환 **0건** (AST) · `invalid()` 는 `missing_rule` 을 받지 않는다 | §10 · §18 |
| 17 | 3-E-24~34 의 구분 + enum 크기 그대로 | **§21** |

### 고의 위반 검증

(아래 §17-A 에 결과를 적는다.)

### 회귀

| | 전 (3-E-34 완료 시점) | 후 |
|---|---|---|
| 통과 | 3,776 | 3,793 |
| 건너뜀 | 4 | 4 |
| 실패 | 0 | 0 |

## 18. Structural TODO

**신규 STRUCTURAL ID 를 만들지 않았다.** §22 의 다섯 조건을 하나씩 확인했다.

| 조건 | 충족? |
|---|---|
| 1. 서로 다른 계층이 `UnimplementedRule` 을 **서로 다른 의미로** 해석한다 | **아니다** — 해석하는 계층이 사실상 하나다 (`_check_requirements`). 발동·해결·트리거는 같은 방식(`missing_rules()`)으로 읽는다 |
| 2. 실제 production path 에서 값이 전달된다 | **조건부** — `ActionValidator` 를 직접 부를 때만 |
| 3. 의미 충돌이 실제 동작에 영향을 줄 가능성 | **아니다** — 충돌을 찾지 못했다 |
| 4. 기존 TODO/ADR 로 설명되지 않는다 | **아니다** — Phase 2-T 범위, STRUCTURAL-7(컴파일러 없음), ADR-006 이 각각 설명한다 |
| 5. 단순히 미래 구현이 필요한 문제가 아니다 | **아니다** — 전부 미래 구현 문제다 (CASE A) |

1~5 가 **모두 불충족**이므로 신규 ID 후보가 아니다.

**기록만 남긴다 (신규 ID 아님)** — 셋 다 문서/이름 수준이다.

1. **`duel.py:686` 의 `RULE_NOT_IMPLEMENTED` 는 "목록에 없다" 를 뜻한다.**
   진짜 이유(페이즈 · 턴 · 미구현)를 구분하지 않는 catch-all 이다. 허가를
   주지 않고 판도 바꾸지 않으므로 안전 쪽으로 틀리지만, 사람이 디버깅할 때
   오해할 수 있다.
2. **`ActivationResult.missing` 과 `ValidationResult.missing_rule` 이 이름이
   비슷하고 담는 것이 다르다** (전자는 `unknown_reasons`, 후자는
   `missing_rules`). 내가 실제로 한 번 틀렸다 (§2-2).
3. **`EffectDefinition.activation` 쪽 docstring 에는
   `UnimplementedRule` 탈출구가 적혀 있지 않다** (3-E-34 가 이미 기록).
   `library.py` 에 0개인 것과 같은 자리다.

## 19. Final Decision — **A. CORRECT_RULE_NOT_IMPLEMENTED_SEMANTICS**

다른 후보를 고르지 않은 이유를 먼저 적는다.

- **B. DIFFERENT_BUT_SAFE 가 아니다.** 계층별로 의미가 **다르지 않다.**
  `UnimplementedRule` 을 읽는 모든 자리가 같은 프로토콜(`missing_rules()`)을
  같은 방식으로 쓰고, 같은 결론(`UNKNOWN` + `RULE_NOT_IMPLEMENTED`)에
  도달한다. 3-E-34 와 달리 **반대로 적힌 계약이 없다.**
- **C. DORMANT_ONLY 가 아니다.** `UnimplementedRule` **클래스 자체**는
  조건부 도달이지만(`legal_actions` 가 그 입력을 만들지 않는다), 그것이
  구현하는 **semantic** 은 production 에서 매번 쓰인다 —
  `_NormalSummonProcedure` · `_NormalSpellActivation` · `_MISSING_RULE` 표가
  `legal_actions` 호출마다 같은 구분을 수행한다. "도달하지 않으니 논할 것이
  없다" 고 적으면 그 사실을 숨긴다.
- **D. FALSE_POSITIVE_CLASSIFICATION 이 아니다.** 측정한 모든 사례가
  **CASE A** 다 — Lua/룰북에는 규칙이 있고 엔진에 계층이 없다. 구현 가능한
  규칙을 뭉갠 사례를 **하나도 찾지 못했다.** 반대 증거가 오히려 있다:
  `_NormalSummonProcedure` 는 **판정할 수 있으면 판정한다** (`ORDINARY` →
  `TRUE`, `FORBIDDEN` → `FALSE`) 고, 모를 때만 규칙 이름을 낸다. 그리고
  거부일 때 `missing_rules()` 가 **빈 튜플**이다.
- **E. SEMANTIC_CONFLICT 가 아니다.** 같은 값을 다르게 해석하는 자리를
  찾지 못했다 (§18 조건 1 불충족).
- **F. INFORMATION_LOSS 가 아니다.** 까닭이 둘이면 `missing_rule` 에 첫
  번째가 들어가고 **`notes` 에 전부** 남는다 (`test_10` 이 2개를 확인).
  AI 경계에서도 `SimulationResult.code` 가 원래 코드를 보존한다.
- **G. UNKNOWN 이 아니다.** 생성처·소비처·전달 경로를 AST 로 전수 수집하고,
  **실제로 돌려** 결과를 확인했다. §3 의 열 질문에 모두 답했다 (아래).

**A 를 고르는 근거는 셋이다.**

1. **`UnimplementedRule` 의 계약이 코드와 정확히 일치한다.** docstring 이
   "아직 판정할 규칙이 없다. 언제나 `UNKNOWN` 이다" 라고 적고, `evaluate()`
   가 한 줄로 그것을 한다. 과장도 축소도 없다.
2. **그 semantic 이 계층을 지나며 보존된다.** `UNKNOWN` 안에서 까닭만
   갈리고 상태는 움직이지 않는다. §18 의 여덟 invariant 가 **전부**
   지켜지고, 잘못된 변환이 **0건**이다.
3. **분류가 정직하다.** 측정된 사례가 모두 CASE A 이고, 판정할 수 있는
   것은 판정한다. `UnimplementedRule` 이 쓰이지 않는 자리(`library.py`,
   `UnimplementedCost`)는 **뭉갠 것이 아니라 아직 필요가 없었던 것**이다.

### §3 의 열 질문에 대한 답

| # | 질문 | 답 |
|---|---|---|
| 1 | "규칙 자체가 구현되어 있지 않음" 인가 | **그렇다.** 그것이 정확한 뜻이다 |
| 2 | 현재 context 에서 판정할 수 없다는 뜻인가 | **아니다.** context 를 **보지 않는다** (`evaluate(None, None)` 도 `UNKNOWN`). 문맥 의존은 `_NormalSummonProcedure` 같은 조건부 구현이 맡는다 |
| 3 | 정보가 부족하다는 뜻인가 | **아니다.** 그것은 `missing_rules()` 가 **빈** `UNKNOWN` 이고 `INFORMATION_UNAVAILABLE` 로 간다 |
| 4 | 특정 조건을 지원하지 않는다는 뜻인가 | **규칙 계층**을 지원하지 않는다는 뜻이다. `rule` 문자열이 그 계층 이름이다 |
| 5 | 해당 effect/card 가 지원되지 않는다는 뜻인가 | **아니다.** 그 역할은 `EffectProvenance` · `EffectImplementationRegistry` · `UNSUPPORTED_REASON` 이 맡는다 |
| 6 | parser/analysis 가 보존하는 metadata 인가 | **아니다.** `engine.condition` 전용이고 `analysis` 에는 없다 (`analysis` 쪽은 `ActivationCondition.unparsed` / `raw`) |
| 7 | 실제 engine execution 에서 발생할 수 있는 결과인가 | **발생할 수 있다** — `ActionValidator` 경로. 다만 `legal_actions`/`apply` 는 그 입력을 만들지 않는다 |
| 8 | `UNKNOWN` 과의 관계 | **부분집합**이다. `UnimplementedRule` ⇒ `UNKNOWN`, 역은 거짓 |
| 9 | `INFORMATION_UNAVAILABLE` 과의 관계 | **같은 `UNKNOWN` 의 다른 까닭.** `missing_rules()` 유무가 둘을 가른다 |
| 10 | `INVALID` / `EXECUTION_FORBIDDEN` 과의 차이 | `INVALID` 는 규칙이 금지(조건 `FALSE`), `EXECUTION_FORBIDDEN` 은 근거가 금지(ADR-004). 셋 다 **다른 enum 멤버**이고 변환 경로가 없다 |

### §24 가 요구한 두 번째 표

| 상황 | 현재 결과 | 올바른 의미 | 안전 여부 |
|---|---|---|---|
| 규칙 자체 미구현 | `UNKNOWN` + `RULE_NOT_IMPLEMENTED` + `missing_rule` | `RULE_NOT_IMPLEMENTED` | **안전** — `permits_execution` 거짓, 판 변화 없음 |
| 정보 부족 | `UNKNOWN` + `INFORMATION_UNAVAILABLE` (+ `unchecked`) | `INFORMATION_UNAVAILABLE` / `UNKNOWN` | **안전** — 규칙 이름을 지어내지 않는다 |
| 조건 거짓 | `INVALID` + 요구별 코드, `missing_rule` 은 `None` | `FALSE` | **안전** — `FALSE` 가 `UNKNOWN` 을 이긴다 |
| 실행 금지 | `FORBIDDEN` + `EXECUTION_FORBIDDEN` | `EXECUTION_FORBIDDEN` | **안전** — 조건보다 **앞선** 관문 |
| 잘못된 후보 | `INELIGIBLE` + `CANDIDATE_NOT_ELIGIBLE` | `CANDIDATE_NOT_ELIGIBLE` | **안전** — 3-E-26 이 `RULE_NOT_IMPLEMENTED` 에서 분리 |
| (추가) 목록에 없는 행위 | `accepted=False` + `RULE_NOT_IMPLEMENTED` | 더 정확히는 "지금 후보가 아니다" | **안전하지만 코드가 느슨하다** (§18 기록 1) |

---

## 20. Next Phase Candidate (하나만 제안한다)

**Phase 3-E-36 — `ValidationCode.RULE_NOT_IMPLEMENTED` 75곳 사용처 정밀 감사**

이 Phase 가 `UnimplementedRule` **클래스**는 정확하다고 확정했다. 남은
질문은 그 **코드** 쪽이다 — 75곳 중 `duel.py:686` 처럼 "미구현" 이 아닌
사실에 붙은 자리가 몇 곳인지 전수 분류한다. 특히 `effect/executor.py` 의
22곳과 `trigger.py` 의 11곳이 전부 진짜 미구현을 뜻하는지, 아니면
`CANDIDATE_NOT_ELIGIBLE` · `INFORMATION_UNAVAILABLE` ·
`UNSUPPORTED_OPERATION` 중 하나가 더 정확한 자리가 섞여 있는지 본다.

AUDIT-ONLY 로 시작한다. 3-E-26 이 그런 자리 셋을 이미 고쳤으므로
(`_judge` 조건 거짓 → `CANDIDATE_NOT_ELIGIBLE` 등) **같은 종류의 남은
자리가 있는지**를 묻는 것이고, 발견하면 고치지 않고 목록으로 보고한다.

---

## §25 — 최종 질문 일곱 개에 대한 답

### Q1. `UnimplementedRule` 은 현재 architecture 에서 정확한 semantic 인가?

**정확하다.** docstring("아직 판정할 규칙이 없다. 언제나 `UNKNOWN` 이다")과
구현(`return ConditionResult.UNKNOWN` 한 줄)이 일치하고, `missing_rules()` 가
그 사실을 소비자에게 전달한다. 과장하지도 축소하지도 않는다.

한 가지 한계는 적어 둔다 — **보존하는 정보가 문자열 하나뿐**이고,
"규칙이 없다" 와 "규칙이 있지만 구현되지 않았다" 를 구조적으로 구분하지
않는다. 실제로 쓰인 두 문자열은 모두 후자이고 문자열 안에 Phase 번호까지
적혀 있어 지금은 충분하다.

### Q2. `RULE_NOT_IMPLEMENTED` 와 `UNKNOWN` 이 실제로 안전하게 분리되어 있는가?

**분리되어 있다 — 다른 축이기 때문이다.** `UNKNOWN` 은 **상태**
(`ConditionResult` · `ActionValidity`)이고 `RULE_NOT_IMPLEMENTED` 는
**코드**(`ValidationCode`)다. 분리라기보다 **포함 관계**다:
`RULE_NOT_IMPLEMENTED` 는 언제나 `UNKNOWN` 안에서만 나오고, 그 역은 아니다.

안전한 이유는 구조적이다 — `ValidationResult.unknown()` 만 `missing_rule` 을
받고, `invalid()` · `valid()` 에는 그 자리가 **없다**. 그래서
"미구현을 거부로 적는" 코드를 쓰려면 생성자를 바꿔야 한다.

### Q3. `INFORMATION_UNAVAILABLE` 과 `RULE_NOT_IMPLEMENTED` 가 실제 production 에서 혼동되는가?

**engine 안에서는 혼동되지 않는다. AI 경계에서 한 상태로 합쳐지되 사실은 보존된다.**

- engine: 다섯 곳(`activation.py:681` · `executor.py:986` ·
  `action_validation.py:346` · `trigger.py:993` · `trigger.py:1432`) 모두
  `missing_rules()` 에게 **되묻는다.** 검증기가 추측하지 않는다.
- agent: `_UNKNOWN_CODES` 가 둘을 `SimulationStatus.UNKNOWN` 으로 보낸다.
  **그 계층에서는 같은 질문("미래를 볼 수 있는가")에 같은 답이므로 축약이
  맞다**, 그리고 `SimulationResult.code` 가 원래 코드를 들고 있으므로
  필요하면 다시 갈 수 있다.

한 가지 이름 혼동은 실재한다 — `ActivationResult.missing` 은
`unknown_reasons` 를 담아서 **두 경우 모두** 채워진다. 코드를 가르는 근거가
아니므로 판정에 영향은 없지만, 사람이 오해할 수 있다 (내가 한 번 틀렸다).

### Q4. 실행 가능한 카드가 잘못해서 `UnimplementedRule` 로 분류된 사례가 있는가?

**없다.** 세 방향으로 확인했다.

1. **`library.py` 에 `UnimplementedRule` 이 0개**이고, 등재 `activation`
   8개는 전부 판정 가능한 조건이다 (`missing_rules()` 가 모두 빈 튜플).
   즉 등재된 13개 실행 가능 효과 중 미구현으로 분류된 것이 **0개**다.
2. production 의 두 생성처는 **`SPECIAL_SUMMON` 전용**이고, 그 종류는
   `legal_actions` 가 아예 만들지 않으므로 실행 가능한 카드의 발동 경로를
   건드리지 않는다.
3. 두 커스텀 조건은 **판정할 수 있으면 판정한다** — `ORDINARY` → `TRUE`,
   `FORBIDDEN` → `FALSE`, 모를 때만 규칙 이름. 거부에 규칙 이름을 붙이지
   않는 것을 실측했다.

### Q5. `UnimplementedRule` 이 실제 `PlayerAction` / `legal_actions` / Search / Simulation 에 영향을 주는가?

**클래스 자체는 주지 않는다. 그것이 구현하는 semantic 은 매번 영향을 준다.**

- `PlayerAction`: 영향 없음. 행위는 조건을 들고 있지 않다.
- `legal_actions`: `SPECIAL_SUMMON` 을 만들지 않으므로 **두 생성처를 타지
  않는다.** 그러나 `_NormalSummonProcedure` ·`_NormalSpellActivation` ·
  `_MISSING_RULE` 표가 **매 호출마다** 같은 구분을 수행하고, 그 결과가
  `withheld` 와 "허가 안 남" 판정을 만든다.
- Search / Simulation: `ValidationCode` **하나만** 넘어간다. 조건 객체는
  경계를 넘지 않는다. `UNKNOWN` 후보는 점수가 `None` 이고 뒤로 가되
  **후보에서 빠지지 않는다.**

### Q6. `UnimplementedRule` 관련 production 수정이 지금 필요한가?

**필요하지 않다.** 틀린 판정 0건, 계약 충돌 0건, false positive 0건,
잘못된 변환 0건, 안전 invariant 8/8 유지.

§18 에 기록한 셋은 전부 **문서/이름** 수준이고, 그중 둘(`duel.py:686` 의
느슨한 코드, `missing` vs `missing_rule` 이름)은 **고치면 동작이 바뀌거나
호환이 깨질 수 있어** 혼자 판단할 일이 아니다. 나머지 하나(`activation`
docstring 에 `UnimplementedRule` 한 줄)는 3-E-34 가 이미 같은 결론으로
기록해 두었다.

### Q7. 다음 Phase 는 무엇이어야 하는가?

**§20 의 Phase 3-E-36 — `RULE_NOT_IMPLEMENTED` 75곳 사용처 정밀 감사.**

이유: 이 Phase 가 "클래스는 정확하다" 를 확정했고, 동시에 **그 코드의
거의 전부가 클래스를 거치지 않는다** 는 것을 측정했다. 그러면 다음 질문은
자연히 "그 75곳이 전부 진짜 미구현을 뜻하는가" 다. 3-E-26 이 그런 자리 셋을
이미 고친 전례가 있으므로, 같은 종류의 남은 자리를 전수로 세는 것이 다음
걸음이다. AUDIT-ONLY 로 시작하고, 발견해도 고치지 않는다.

**이 Phase 는 여기서 멈춘다. 다음 Phase 는 임의로 진행하지 않는다.**
