# Phase 3-E-34 — `engine/` 전역 `Condition | None` 계약 정합성 감사

**최종 판정: B. SEMANTICALLY_DIFFERENT_BUT_SAFE**

**production diff = 0.** `engine/` · `agent/` · `core/` · `analysis/` ·
`sources/` 를 한 글자도 바꾸지 않았다.

---

## 1. Phase / Base / 실제 HEAD

| 항목 | 값 |
|---|---|
| Phase | 3-E-34 (AUDIT-ONLY) |
| 브랜치 | `claude/pensive-goodall-te1egy` |
| 감사 시작 HEAD | **`c87f3e4`** — "Phase 3-E-33 보고서: 고의 위반 8건 결과 + G 의 한계 명시 (AUDIT-ONLY)" |
| 그 직전 | `7fbbb4c` Phase 3-E-33 · `214ddc0` Phase 3-E-32 보고서 |
| 작업 트리 | 깨끗함 (`git status --porcelain` 비어 있음) |
| Phase 3-E-33 보고서 | `docs/phase3e33-effectdefinition-activation-audit.md` 존재 (32,052 B) |
| 3-E-33 감사 테스트 | `tests/test_effectdefinition_activation_audit.py` 존재 (15개) |
| `214ddc0..HEAD` production diff | **0** |

프롬프트가 적은 commit 을 믿지 않고 저장소에서 확인했다. `reset`/`checkout`
하지 않았다.

## 2. BLOCKER

**없다.** 감사를 끝까지 수행했고, production 변경이 필요한 자리를 발견했어도
고치지 않고 이 문서에 적었다 (§19 · §20).

측정 중에 두 번 **내 가정이 틀렸다**는 것을 발견해 고쳤다. 둘 다 숫자로
드러났고 보고서에 반영했다.

1. `engine/` 을 `rglob("engine/**/*.py")` 로 훑으면 `tests/engine/` 까지
   잡힌다. 분모가 오염되므로 `engine` 패키지만 보도록 고쳤다 (파일 65개).
2. `notes=("정의 미등록",)` 는 2곳이 아니라 **4곳**이다 (`trigger.py` 의
   942 · 1391 · 1461 · 1500). 처음 센 2곳은 조건 관문 둘뿐이고, 나머지 둘은
   다른 관문이 같은 쪽지를 쓴다.
3. `None` 검사 수를 처음에 **36곳**으로 적었는데, 그것도 1번과 같은 오염
   때문이었다. `engine/` 패키지만 보면 **27곳**이다 (`is None` 4 ·
   `is not None` 23). 지금 보고서의 수는 고친 쪽이고, `test_01` 이 그 수를
   고정한다.

## 3. Engine 변경 여부

```
$ git diff --stat c87f3e4..HEAD -- engine/ agent/ core/ analysis/ sources/
(출력 없음)
```

더한 파일은 둘뿐이다.

- `tests/test_engine_condition_none_contract_audit.py` (새 파일, 17개 테스트)
- `docs/phase3e34-engine-condition-none-contract-audit.md` (이 문서)

기존 테스트를 삭제·수정하지 않았다. `skip` 을 더하지 않았고 assertion 을
약하게 바꾸지 않았다. 새 enum · 새 `Condition` 클래스 · 새 필드를 만들지
않았다.

## 4. 전체 `Condition | None` corpus

`engine/` 의 `*.py` **65개 파일 전수**를 AST 로 훑었다 (문자열 검색이면
주석과 docstring 의 같은 글자가 섞인다).

### 4-1. `Condition | None` 필드 — **정확히 5곳**

| # | 위치 | 소속 | 필드 |
|---|---|---|---|
| 1 | `engine/cost/choice.py:38` | `CandidateSource` | `require` |
| 2 | `engine/cost/model.py:119` | `CardCost` | `require` |
| 3 | `engine/effect/definition.py:250` | `EffectDefinition` | `activation` |
| 4 | `engine/observation_grant.py:88` | `ObservationGrant` | `condition` |
| 5 | `engine/trigger.py:454` | `TriggerSpec` | `condition` |

다섯 **모두** 주석이 정확히 `Condition | None` 이고 기본값이 `None` 이다 —
즉 적지 않으면 `None` 이다. `Optional[...]` 표기는 `engine/` 에 **하나도
없다** (전부 PEP 604 `|`).

`engine/cost/model.py` 에는 같은 `require` 를 받는 팩토리 매개변수가 4개 더
있다 (`release` · `discard` · `banish` · `send_to_grave`, 159/178/197/216행).
전부 #2 로 들어간다.

### 4-2. `Condition` 을 **반드시** 받는 자리 — 4곳

| 위치 | 소속 | 필드 | 주석 |
|---|---|---|---|
| `engine/action_validation.py:108` | `Requirement` | `condition` | `Condition` (기본값 없음) |
| `engine/condition/model.py:177` | `And` | `children` | `tuple[Condition, ...]` |
| `engine/condition/model.py:225` | `Or` | `children` | `tuple[Condition, ...]` |
| `engine/condition/model.py:267` | `Not` | `child` | `Condition` |

**`Requirement` 가 가장 중요하다.** 조건이 없으면 `None` 을 넣는 것이 아니라
**`Requirement` 자체를 만들지 않는다** (`requirements` 튜플이 비어 있다).
부재를 `None` 없이 적는 설계가 이미 저장소 안에 있다는 뜻이다 — §20 Q4 의
답이 여기 있다.

### 4-3. 이름만 같고 `Condition` 이 아닌 자리

| 위치 | 주석 | `None` 의 뜻 |
|---|---|---|
| `engine/action_validation.py:254` `validate(context=...)` | `ConditionContext \| None` | **아직 안 건넸다** → `context_for(action)` 로 만든다 |
| `engine/activation.py` 지역 `condition` (`_check` 안) | `ActivationResult \| None` | **막는 것이 없다** (통과) |
| `engine/effect/executor.py` 지역 `condition` | `EffectResult \| None` | **막는 것이 없다** (통과) |
| `engine/response.py:222` `ResponseResult.activation` | `ActivationResult \| None` | **발동 계층까지 가지 않았다** |
| `engine/summon_rules.py:89` `SummonAssessment.tributes_required` | `int \| None` | (조건과 무관 — 이름 걸림) |

**이름으로 계약을 읽으면 틀린다.** `condition` 이라는 이름의 `None` 이 한
파일 안에서 "조건을 적지 않았다" 와 "막는 것이 없다" 두 뜻으로 쓰인다 —
다만 타입이 다르므로 섞일 수 없다.

### 4-4. `is None` / `is not None` 검사 전수

조건·요구·발동 이름에 대한 `None` 검사는 `engine/` 에서 **27곳**이다
(`is None` **4** · `is not None` **23**). 그리고 `condition or ...` ·
`condition and ...` · `not condition` 같은 **참/거짓 축약은 한 곳도 없다**
(0곳). 전부 `is None` / `is not None` 명시형이다 — `Condition` 객체의
참/거짓에 기대는 자리가 없다. `Optional[...]` 표기도 `engine/` 전체에 **0곳**이다.

`is None` 네 곳이 곧 "`None` 을 특별히 처리하는 자리" 다.

| 위치 | 하는 일 |
|---|---|
| `engine/activation.py:658` | `definition.activation is None` → 통과 |
| `engine/effect/executor.py:968` | 같음 |
| `engine/cost/resolver.py:109` | `source.require is None` → 보이는 카드 전부 후보 |
| `engine/response.py:239` | `self.activation is None` → 링크 없음 검사 (조건 아님) |

## 5. 계층별 `None` 의미 — **필수 표**

| 위치 | 타입 | `None` 의미 | `Condition` 의미 | `UNKNOWN` 가능 | 실제 consumer | 판정 |
|---|---|---|---|---|---|---|
| `CandidateSource.require` | `Condition \| None` | **추가 필터 없음** (문서화 안 됨) | 후보마다 따로 판정하는 필터 | 예 → `undecided` | `cost/resolver.py:109` | **A. NO_CONDITION** |
| `CardCost.require` | `Condition \| None` | **추가 필터 없음** (문서화 안 됨) | 같음 (`choice_spec()` 로 #1 에 전달) | 예 | `CardCost.choice_spec()` → #1 | **A. NO_CONDITION** |
| `EffectDefinition.activation` | `Condition \| None` | docstring: **"적지 않았다"** / 실행: 통과 | 발동 조건 | 예 → `CONDITION_UNKNOWN` | `activation.py:658` · `executor.py:968` · `trigger.py` ×2 | **A. NO_CONDITION** (실효) + 문서 불일치 |
| `ObservationGrant.condition` | `Condition \| None` | docstring: **"조건이 없다"** | 권한이 살아 있는 조건 | 예 → 권한 없음 | `observation_grant.py:163` (`derive_policy`) | **A. NO_CONDITION** |
| `TriggerSpec.condition` | `Condition \| None` | docstring: **"적지 않았다"**, 그래서 정의의 `activation` 도 함께 본다 | 타이밍 뒤의 추가 조건 | 예 → `TriggerStatus.UNKNOWN` | `trigger.py:931` · `trigger.py:1382` | **A. NO_CONDITION** (등록 관문이 보완) |
| `ActionValidator.validate(context=)` | `ConditionContext \| None` | **아직 공급되지 않았다** | 조건 평가 문맥 | 해당 없음 | `action_validation.py:264` | **C. NOT_PROVIDED_YET** |
| `_check` / `_check_condition` 반환 | `ActivationResult \| None` | **막는 것이 없다** | 막은 결과 | 해당 없음 | `activation.py:536` · `executor.py:559` | **D. NOT_APPLICABLE** |
| `ResponseResult.activation` | `ActivationResult \| None` | **발동 계층까지 가지 않았다** | 발동 결과 | 해당 없음 | `response.py:239~303` | **E. OPTIONAL_METADATA** |
| `ActivationCondition.tree` (analysis) | `ConditionNode \| None` | **읽어내지 못했거나 조건 함수가 없다** (유무는 `has_condition_function`) | 읽어낸 조건 트리 | 해당 없음 | `effect_analyzer.py:495` | **A/B 분리됨** |
| `Requirement.condition` | `Condition` (**Optional 아님**) | — (`None` 을 넣을 수 없다) | 반드시 참이어야 하는 사실 | 예 → 보류 | `action_validation.py:_check_requirements` | **해당 없음 — 부재를 부재로 적는다** |

**`G. AMBIGUOUS` 로 분류한 자리는 없다.** 두 `require` 는 docstring 이
`None` 을 말하지 않지만, 읽는 곳이 `cost/resolver.py:109` **한 곳**이고 그
동작이 명확하므로 코드로 결정할 수 있다. 문서가 없는 것과 의미를 결정할 수
없는 것은 다른 사실이다.

**`H. CONTRACT_BUG` 으로 분류한 자리도 없다.** 근거는 §14 · §20 이다.

## 6. `EffectDefinition.activation`

### 선언 · 기본값

```python
# engine/effect/definition.py:250
    activation: Condition | None = None
    """발동 조건. ``None`` 이면 **조건이 없다는 뜻이 아니라 적지 않았다는 뜻**이다."""
```

### 생성 · 복사 · serialization

- **생성**: `engine/effect/library.py` 가 **손으로** 적는다 (컴파일러 없음,
  STRUCTURAL-7). 등재 16개 중 `activation` 이 있는 것은 8개 (3-E-33 측정).
- **복사**: `frozen=True, slots=True` dataclass 이므로 `dataclasses.replace`
  가 참조를 그대로 옮긴다 — 조건 객체가 복제되지 않으므로 의미가 바뀔 자리가
  없다.
- **serialization**: `canonical_state()` 의 **4번째 자리**(index 3)와
  `to_dict()` 의 `"activation"` 키. 둘 다 `None` 이면 `None` / 키 부재로
  적는다 — "조건이 거짓" 과 구분된다.

### 실제 consumer 4곳

| consumer | `activation is None` 이면 | 그 앞의 관문 |
|---|---|---|
| `EffectActivator._check_condition` (`activation.py:658`) | `return None` → **통과** | `definition is None` → `NOT_IMPLEMENTED`, `_check_authority` (ADR-004) |
| `EffectExecutor._check_condition` (`executor.py:968`) | `return None` → **통과** | `_check_authority` (`ExecutionAvailability.EXECUTABLE` 필수), `_check_supported` |
| `TriggerCollector._judge` (`trigger.py:931`) | `spec.condition` 과 **함께** 모아서 비면 — 정의 미등록이면 `UNKNOWN`, 등록되어 있으면 `ELIGIBLE` | 출처 금지(`EXECUTION_FORBIDDEN`) |
| `TriggerEligibilityJudge._trigger_condition` (`trigger.py:1382`) | 위와 **같은 논리** (`GateVerdict` 로 적는다) | 같음 |

### 핵심 — docstring 과 실행의 관계

`activation.py` 의 `_check_condition` docstring 은 이렇게 적는다.

> ``None`` 은 **"조건이 없다" 가 아니라 "적지 않았다"** 이므로 넘어간다
> — 실행기와 같은 태도이고, 여기서 다르게 읽으면 같은 정의가 두 곳에서
> 다른 뜻이 된다.

즉 **의미를 알고 통과시킨다.** 사고가 아니라 **문서화된 결정**이다. 그리고
그 결정이 안전한 까닭은 조건 칸이 아니라 **다른 관문**에 있다.

> 완전성은 **필드별로** 보증되지 않고 **등재 시점에** 보증된다.

`EffectImplementationRegistry` 에 등록되고 `provenance` 가 금지가 아니어야
`_check_condition` 까지 온다. 그래서 `activation=None` 은 실제로는
**"사람이 이 효과를 실행 가능하다고 등재하면서 조건이 없다고 단언한 것"** 을
의미한다. 3-E-33 이 측정한 "`SetCondition` 이 있으면서 `activation=None` 인
등재 효과는 0개" 가 그 단언이 지켜지고 있다는 증거다.

**남는 위험**: 그 단언을 데이터가 아니라 **사람의 주의**가 지킨다.
`UnimplementedRule` 로 적으라는 탈출구가 `activation` 의 docstring 에는
적혀 있지 않다 (`ObservationGrant` 쪽에만 있다). 등재 16개 중
`UnimplementedRule` 은 **0개**다.

## 7. `ObservationGrant.condition`

```python
# engine/observation_grant.py:88
    condition: Condition | None = None
    """
    언제 살아 있는가 (``SetCondition``).

    ``None`` 은 **"조건이 없다"** 는 뜻이다 — 원본에 ``SetCondition`` 이
    없으면 조건이 없는 것이 사실이다. 옮기지 못한 조건은 ``None`` 이
    아니라 :class:`~engine.condition.UnimplementedRule` 로 적어야
    ``UNKNOWN`` 이 되고, 그러면 권한이 생기지 않는다.
    """
```

세 질문에 답한다.

- **"관측 조건이 없음" 인가** → **예.** `derive_policy` 가 `condition is
  None` 이면 조건 평가를 건너뛰고 세 번째 관문을 통과시킨다.
- **"아직 조건이 제공되지 않음" 인가** → **아니다.** docstring 이 그 경우를
  `UnimplementedRule` 로 적으라고 명시한다.
- **"조건 평가가 필요하지 않음" 인가** → 결과적으로 그렇지만, 그것은 "조건이
  없다" 의 결과다.

**`EffectDefinition.activation` 과 같은 타입을 쓴다고 같은 의미라고 보지
않았다.** 실제로 **반대**다. 그리고 그 차이가 자의적이지 않은 이유가 있다.

> `ObservationGrant` 에는 **정의 등록 관문도 출처 금지 관문도 없다.**

`derive_policy` 의 관문은 세 개뿐이다 — holder 가 판에 있는가 · 그 자리에
있는가 · 조건이 참인가. 그래서 "적지 않았다" 를 막아 줄 다른 관문이 없고,
계약이 그 부담을 **스스로** 져야 한다. 그래서 `UnimplementedRule` 을
명시적으로 요구한다. **계약이 다른 것이 아니라, 계층의 관문 구조가 달라서
계약이 달라야 하는 것이다.**

**그리고 이 계층은 production 에서 dormant 다.** `ObservationGrant(...)`
생성처는 AST 전수로 **5곳 전부 `tests/`** 이고 (`test_observation_permission.py`
132·144·228 · `test_random_selection.py:658` · `test_selection_count.py:602`),
`derive_policy` 를 부르는 production 코드도 **0곳**이다.

## 8. Activation 계층

`EffectActivator.activate` → `_check` 의 관문 순서. **순서가 규칙이다.**

| 순서 | 관문 | 실패 상태 | `Condition` 관련 |
|---|---|---|---|
| 1 | `_check_shape` | `INVALID_ACTION` · `CHAIN_REFUSED` | — |
| 2 | `_verdict(...).permits_execution` | `UNAUTHORIZED` | 발동 타이밍 계층 |
| 3 | `definition is None` | `NOT_IMPLEMENTED` + `RULE_NOT_IMPLEMENTED`, `missing="effect definition"` | **"적지 않았다" 를 여기서 막는다** |
| 4 | `definition.effect_ref != action.effect_ref` | `INVALID_CONTEXT` | — |
| 5 | `_check_authority` | `FORBIDDEN` · `UNVERIFIED` · `NOT_IMPLEMENTED` | ADR-004 · ADR-006 |
| 6 | **`_check_condition`** | `CONDITION_FALSE` · `CONDITION_UNKNOWN` | **여기서 처음 `activation` 을 읽는다** |
| 7 | `_check_targets` | `INVALID_TARGET` · `UNCHECKED_TARGET` | — |
| 8 | 비용 지불 | `COST_UNPAYABLE` · `COST_UNKNOWN` | `CardCost.require` |

호출 관계 기록 (§8 요구 형식):

```
EffectActivator.activate
 → EffectActivator._check
 → EffectActivator._check_condition(state, definition, action, chain, verdict)
 → condition argument: definition.activation
 → None 가능: 예 (기본값)
 → None 의 의미: "적지 않았다" (docstring) / 실행은 **통과**
 → 결과: None 반환 = 막는 것 없음

EffectActivator._check_condition
 → ConditionEvaluator(view).evaluate(definition.activation, context)
 → condition argument: Condition (None 아님 — 위에서 걸렀다)
 → UNKNOWN 이면 definition.activation.missing_rules(view, context) 로 까닭을 되묻는다
 → 결과: RULE_NOT_IMPLEMENTED / INFORMATION_UNAVAILABLE (상태는 둘 다 CONDITION_UNKNOWN)
```

`activation.py:658` 의 `None` 전달 경로를 다시 검증했다 — **3-E-33 의 기록이
맞다.** 그리고 3번 관문이 6번보다 **먼저**라는 것이 새로 확인된 사실이다
(소스 위치로 확인: `"definition is None"` 의 인덱스 < `"if
definition.activation is None:"` 의 인덱스).

`ConditionEvaluator` 는 `None` 을 받지 않는다 — `evaluate(None, ...)` 는
예외를 낸다. 즉 "`None` 을 평가해서 참이 나온다" 는 경로가 **구조적으로
없다.**

## 9. Effect Executor

`EffectExecutor.execute` → `_check_authority` → `_check_supported` →
**`_check_condition`** → 대상 → 선언 → 계획.

세 경우가 **서로 다른 결과**를 낸다 (테스트로 고정).

| 경우 | 결과 | 코드 |
|---|---|---|
| `activation is None` | **통과** (`return None`) | — |
| 조건이 `FALSE` | `ResolutionStatus.CONDITION_FALSE` | `RULE_NOT_IMPLEMENTED` |
| 조건이 `UNKNOWN` (규칙 없음) | `ResolutionStatus.CONDITION_UNKNOWN` | `RULE_NOT_IMPLEMENTED` |
| 조건이 `UNKNOWN` (정보 없음) | `ResolutionStatus.CONDITION_UNKNOWN` | `INFORMATION_UNAVAILABLE` |

§9 가 찾으라고 한 위험 패턴을 하나씩 확인했다.

| 위험 패턴 | 있는가 | 근거 |
|---|---|---|
| `None` → `TRUE` | **아니다** | 평가기를 부르지 않는다. `ConditionResult.TRUE` 가 만들어지지 않는다 |
| `None` → `FALSE` | **아니다** | `test_09` — `None` 과 `Always(FALSE)` 가 다른 상태를 낸다 |
| `None` → skip | **예** | `return None` — 그리고 그것이 문서화된 결정이다 |
| `None` → execute | **예, 단 관문 뒤에서만** | 등재 + 출처 + 구현 등록을 모두 통과한 뒤다 |
| `None` → `UNKNOWN` | **아니다** | `test_08` — `ACTIVATED` 다 |

**발동기와 실행기가 완전히 같은 태도다.** 한쪽만 고치면
`tests/test_validation_code_consistency.py::test_07` 이 깨진다 (3-E-26 이
세운 고정).

## 10. Trigger 계층

| 요소 | `Condition` 관련 | `None` 처리 |
|---|---|---|
| `TriggerSpec.condition` | `Condition \| None` | docstring: "적지 않았다" |
| `TriggerCollector._judge` | `[spec.condition, definition.activation]` 에서 `None` 제거 | 둘 다 없고 **정의도 없으면** `UNKNOWN` + `RULE_NOT_IMPLEMENTED` + `notes=("정의 미등록",)`; 정의가 **있으면** `ELIGIBLE` + `OK` |
| `TriggerEligibilityJudge._trigger_condition` | 같음 | 같음 (`GateVerdict` 로) |
| `TriggerChainIntegrator` | 조건을 직접 읽지 않는다 | — |
| `TriggerCandidate` | 조건 필드 없음 — 판정 결과만 들고 있다 | — |

**트리거 계층이 다섯 자리 중 가장 조심스럽다.** 두 조건을 `all_of` 로 합치고
(`FALSE` 가 `UNKNOWN` 을 이긴다), 조건이 비었을 때 **정의 등록 여부**를
다시 묻는다. 즉 `None` 을 "조건 없음" 으로 읽되, **그 읽기가 정당한 경우만**
그렇게 읽는다.

`missing_rules` · `RULE_NOT_IMPLEMENTED` · `INFORMATION_UNAVAILABLE` 의 관계는
3-E-26/27 이 세운 대로다 — 조건이 스스로 까닭을 말하고, 판정 계층이 추측하지
않는다.

**이 Phase 는 trigger pipeline 을 연결하지 않았다.** `TriggerSpec` 은
production 에서 여전히 0개 생성된다 (3-E-29 · 3-E-31 측정).

## 11. Cost 계층

| 요소 | `Condition` 관련 | `None` 의미 |
|---|---|---|
| `CandidateSource.require` | `Condition \| None` | **추가 필터 없음** |
| `CardCost.require` | `Condition \| None` | 같음 — `choice_spec()` 로 위에 전달 |
| `CardCost.release/discard/banish/send_to_grave(require=...)` | 매개변수 | 기본값 `None` |
| `CandidateResolver.resolve` | `source.require is None` → 보이는 카드 전부 `eligible` | **A. NO_CONDITION** |
| `CostPaymentContext` / `PaymentContext` | `Condition` 필드 없음 | — |

세 가지를 구분하는지 확인했고, **구분한다.**

| 사실 | 표현 | 결과 (`new_state()` 양쪽 MZONE 1장씩) |
|---|---|---|
| cost condition 없음 | `require=None` | `eligible` 2 · `undecided` 0 |
| cost condition 거짓 | `require=Always(FALSE)` | `eligible` 0 · `undecided` 0 |
| cost condition 모름 | `require=UnimplementedRule(...)` | `eligible` 0 · **`undecided` 2** + `reasons` |
| cost context 없음 | 해당 없음 | `ConditionContext` 는 필수 인자다 |

`CandidateSet` 의 docstring 이 왜 그렇게 갈라야 하는지까지 적는다 —
"``undecided`` 를 ``eligible`` 에 넣으면 못 치를 비용을 치를 수 있다고 하게
되고, 버리면 치를 수 있는 비용을 못 치른다고 하게 된다."

**다만 `require` 두 자리는 `None` 의 뜻을 docstring 에 적지 않는다.**
`exclude_source` 는 바로 아래에서 "적지 않은 것을 '뺀다' 로 읽으면 안 되기
때문" 이라고 기본값의 뜻까지 적는데, `require` 는 적지 않는다. 같은
dataclass 안에서 한 필드만 그 설명을 갖고 있다.

## 12. Action validation 계층

| 요소 | `None` 관련 | 의미 |
|---|---|---|
| `ActionValidator.validate(action, context=None)` | `ConditionContext \| None` | **C. NOT_PROVIDED_YET** — `ctx = context if context is not None else self.context_for(action)` |
| `Requirement.condition` | `Condition` (**필수**) | 조건이 없으면 `Requirement` 를 만들지 않는다 |
| `_check_requirements(...) -> ValidationResult \| None` | `None` = **통과** | **D. NOT_APPLICABLE** (결과 채널) |
| `GateVerdict` (trigger 쪽) | `Condition` 필드 없음 | 판정만 들고 있다 |

§12 이 요구한 여섯 구분이 **전부 다른 값으로** 표현된다.

| 사실 | 표현 |
|---|---|
| condition 없음 | `requirements` 가 비어 있다 / 조건 칸이 `None` |
| 조건 거짓 | `ConditionResult.FALSE` → `ValidationResult.invalid(requirement.code, ...)` |
| 정보 없음 | `UNKNOWN` + `missing_rules` 없음 → `INFORMATION_UNAVAILABLE` |
| 규칙 미구현 | `UNKNOWN` + `missing_rules` 있음 → `RULE_NOT_IMPLEMENTED` + `missing_rule` |
| 실행 금지 | `EXECUTION_FORBIDDEN` (provenance 관문) |
| 후보 아님 | `CANDIDATE_NOT_ELIGIBLE` |

3-E-24~29 가 세운 네 구분이 그대로 유지된다 (`test_16` 이 고정).

## 13. Analysis / Core 와의 경계

`engine` 이 쓰는 `Condition` 의 출처를 확인했다.

| 계층 | "조건 없음" 을 어떻게 적는가 | Optional 인가 |
|---|---|---|
| `analysis/effect_model.py` `EffectAnalysis.activation` | `ActivationCondition` 객체가 **항상** 있고, 유무는 `has_condition_function: bool` | **아니다** (`default_factory`) |
| `analysis/effect_model.py` `ActivationCondition.tree` | `ConditionNode \| None` — "읽어내지 못했다" 는 `raw` · `unparsed` 로 남는다 | 예, 그러나 유무와 **다른 칸** |
| `core/` | `Condition` 을 쓰지 않는다 | — |
| `sources/` | `EffectSpec` 에 조건 칸이 없다 (3-E-33) | — |
| `rules/` | `WinConditionRule` 은 이름만 겹친다 | — |

**`analysis` 가 가장 깔끔하다.** 유무(`has_condition_function`)와
내용(`tree`)을 **두 칸**에 적어 두었기 때문에 "원본에 없다" 와 "있는데 못
읽었다" 가 섞이지 않는다. `engine` 쪽 한 칸은 그 두 사실을 겸한다.

**그러나 engine 으로 오면서 의미가 사라지지는 않는다.** `engine.condition` 에
`UnimplementedRule` 이 있어서 "있는데 못 옮겼다" 를 `UNKNOWN` 으로 적을 수
있다. 즉 **표현력은 이미 충분하고, 쓰이지 않고 있을 뿐이다** (등재 16개 중
`UnimplementedRule` 0개).

여기서 production 변경은 하지 않았다.

## 14. `None` propagation

### 흐름 표 (§14 요구 형식)

| Source | Field | Consumer | `None` 의미 | `Condition` 의미 | `UNKNOWN` 가능 | 계약 |
|---|---|---|---|---|---|---|
| `library.py` (손 등재) | `EffectDefinition.activation` | `EffectActivator._check_condition` | 통과 (등재 단언) | 발동 조건 | 예 | **MATCH** |
| 같음 | 같음 | `EffectExecutor._check_condition` | 통과 (같은 태도) | 같음 | 예 | **MATCH** |
| 같음 | 같음 | `TriggerCollector._judge` | 등록되어 있으면 `ELIGIBLE`, 없으면 `UNKNOWN` | 같음 | 예 | **MATCH** (더 보수적) |
| 같음 | 같음 | `TriggerEligibilityJudge._trigger_condition` | 같음 | 같음 | 예 | **MATCH** |
| (테스트만) | `TriggerSpec.condition` | 위 두 트리거 자리 | 정의의 `activation` 과 **합쳐서** 읽는다 | 타이밍 뒤 조건 | 예 | **MATCH** |
| `library.py` | `CardCost.require` | `CardCost.choice_spec()` → `CandidateSource.require` | 필터 없음 | 후보 필터 | 예 | **MATCH** |
| 같음 | `CandidateSource.require` | `CandidateResolver.resolve` | 전부 `eligible` | 같음 | 예 → `undecided` | **MATCH** |
| (**production 생성 0**) | `ObservationGrant.condition` | `derive_policy` | 조건 없음 | 권한 생존 조건 | 예 → 권한 없음 | **계약 다름 · 경로 없음** |
| 호출자 | `validate(context=)` | `ActionValidator.validate` | 아직 안 건넸다 | 평가 문맥 | 해당 없음 | **MATCH** |
| `_check_condition` | 반환값 | `_check` | 막는 것 없음 | 막은 결과 | 해당 없음 | **MATCH** |

### §15 — `A → B → C` 로 의미가 바뀌는 자리가 있는가

**없다.** 같은 `activation=None` 하나를 네 consumer 에 전부 넣고 돌려 보았다
(`test_15`).

- 정의가 **등록되어 있으면**: 발동 `ACTIVATED` · 해결 통과 · 트리거
  `ELIGIBLE` ×3. **넷이 같은 뜻으로 읽는다.**
- 정의가 **없으면**: 트리거 `UNKNOWN` ×3 + `notes=("정의 미등록",)`.
  조건 칸의 뜻이 바뀐 것이 아니라 **다른 관문이 막은 것**이다.

그리고 세 번째 계층(`ObservationGrant`)은 계약이 반대지만 **같은 경로에
들어오지 않는다** — 생성처가 production 에 0곳이다.

> **"None 이 여러 군데 쓰인다" 는 것 자체는 문제로 판정하지 않았다.**
> 의미가 실제로 충돌하는 경로를 찾았고, 없었다.

## 15. `UNKNOWN` / `FALSE` / `NO_CONDITION` 구분 — **필수 표**

| 의미 | 현재 표현 | 안전 여부 |
|---|---|---|
| **조건 없음** | 조건 칸 `None`, 또는 `Requirement` 를 만들지 않음 | **조건부로 안전** — 등재 관문(`EffectImplementationRegistry` + `provenance`)이 뒤를 받칠 때만. `ObservationGrant` 는 관문이 없어 계약이 직접 받친다 |
| **조건 거짓** | `Always(ConditionResult.FALSE)` → `CONDITION_FALSE` · `ActionValidity.INVALID` · `eligible` 제외 | **안전** — `UNKNOWN` 과 다른 칸 |
| **정보 없음** | `UNKNOWN` + `missing_rules()` 가 빈 튜플 → `INFORMATION_UNAVAILABLE` | **안전** — 조건 자신이 까닭을 말한다 |
| **규칙 미구현** | `UnimplementedRule(...)` → `UNKNOWN` + `missing_rules()` 비어 있지 않음 → `RULE_NOT_IMPLEMENTED` | **안전하지만 쓰이지 않는다** — 등재 16개 중 0개 |
| **아직 context 없음** | `ConditionContext \| None = None` (`validate` 한 자리) | **안전** — 타입이 달라 조건 칸과 섞일 수 없다 |
| **실행 금지** | `EffectProvenance.is_forbidden` → `EXECUTION_FORBIDDEN` / `FORBIDDEN` | **안전** — 조건 계층 밖의 관문이다 (ADR-004) |

`ConditionResult` 는 `TRUE` · `FALSE` · `UNKNOWN` **세 개뿐**이고,
`ActionValidity` 도 `VALID` · `INVALID` · `UNKNOWN` 세 개뿐이다. 네 번째
상태(`NOT_WRITTEN` 같은 것)는 **없다** — 이번 Phase 가 만들지 않았다는 것을
`test_16` 이 고정한다.

## 16. Hidden Information

조건이 비공개 정보를 요구하는 경우를 확인했다.

- `IsMonster(InstanceId(9999))` 처럼 관측에 없는 카드를 묻는 조건은
  `UNKNOWN` + `INFORMATION_UNAVAILABLE` 이다. **`FALSE` 가 아니다.**
- `ActionValidator` 는 가려진 카드를 가리키면 `HIDDEN_CARD` + `UNKNOWN` 이다.
- `CandidateResolver` 는 통째로 가려진 존을 `unchecked` 에 적고, 거기 후보가
  없다고 말하지 않는다. `undecided` 와 **다른 칸**이다.
- `derive_policy` 는 조건을 holder 컨트롤러의 **기본 관측**으로 판정한다 —
  권한을 적용한 관측으로 판정하면 "권한이 있어서 조건이 참이고 조건이 참이라
  권한이 있다" 가 된다.

§17 이 묻는 두 불변식을 확인했다.

- `UNKNOWN != FALSE` → **유지** (`test_06` · `test_07`)
- `None != UNKNOWN` → **유지** (`test_08` — `activation=None` 은 `ACTIVATED`)

**정보가 없다고 `None` 을 `UNKNOWN` 으로 자동 변환하는 구조는 없다.**
`None` 이면 평가기를 **부르지 않으므로** 변환할 자리 자체가 없다. 거꾸로
`UNKNOWN` 을 `None` 으로 접는 자리도 없다 (`is None` / `is not None` 명시형
36곳 전수 확인, 참/거짓 축약 0곳).

이번 Phase 에서 수정하지 않았다.

## 17. AI / Search 영향

**없다.**

| 항목 | 확인 |
|---|---|
| `GameStateView` | 건드리지 않았다. 감사 테스트도 `from_state(..., viewer=...)` 를 그대로 지난다 |
| `legal_actions` | 건드리지 않았다 |
| candidate generation | `CandidateResolver` 를 **읽기만** 했다 |
| Search ranking · Evaluation · Simulation | `agent/` 수정 0. 그리고 `agent/` 의 어느 파일도 다섯 조건 칸을 읽지 않는다 (`test_17`, AST) |
| `clone` · RNG isolation | 셔플하지 않는 기존 `new_state()` 를 쓴다. 판 상태를 바꾸는 테스트가 없다 |
| hidden information | §16 |

`agent/` 파일을 수정하지 않았다.

## 18. Tests

`tests/test_engine_condition_none_contract_audit.py` — **17개, 전부 통과.**

| # | 무엇을 고정하는가 | §16 요구 |
|---|---|---|
| 01 | `engine/` 65파일의 `Condition \| None` 필드가 **정확히 5곳**이고 전부 기본값 `None` · `Optional[]` 0곳 · 참/거짓 축약 0곳 · `None` 검사 27곳 | §4 |
| 02 | 부재를 `None` 없이 적는 설계가 2개 있다 (`Requirement` · `EffectAnalysis.activation`) | §20 Q4 |
| 03 | 5곳 중 3곳만 `None` 의 뜻을 적는다 | §5 |
| 04 | **비용 계층: `None` = 필터 없음** · `FALSE`/`UNKNOWN` 과 세 결과가 다르다 | **Test 1** |
| 05 | **`validate(context=None)` = 아직 안 건넸다** (`context_for` 와 같은 결과) | **Test 2** |
| 06 | `UNKNOWN` 이 네 계층에서 그대로 유지되고 까닭까지 갈린다 | **Test 3** |
| 07 | `FALSE` 가 `UNKNOWN` 과 다른 칸이다 (관측 권한은 `TRUE` 만 허가) | **Test 4** |
| 08 | `None` → `UNKNOWN` 변환이 없다 | **Test 5** |
| 09 | `None` → `FALSE` 변환이 없다 | **Test 6** |
| 10 | 같은 `Condition` 객체가 다섯 자리에서 같은 `canonical_state` 를 낸다 | **Test 7** |
| 11 | `activation` 과 `ObservationGrant.condition` 의 계약이 **반대**이고 `TriggerSpec` 은 앞쪽 편이다 | **Test 8** |
| 12 | 네 consumer 가 모두 **정의 등록 관문 뒤에서** `None` 을 읽는다 — 관문 순서를 **AST 호출 순서**로 확인 (+ 미등록은 실제로 막힌다) | **Test 9** |
| 13 | 같은 이름이 `Condition` 이 아닌 자리 3곳 | §4-3 |
| 14 | `ObservationGrant` 는 production 생성 **0곳** · `derive_policy` 호출 **0곳** | §20 |
| 15 | 같은 `None` 이 한 경로에서 두 뜻으로 읽히지 **않는다** | §15 |
| 16 | 3-E-24~33 의 네 구분 + `ConditionResult`/`ActionValidity` 가 여전히 3개 | **Test 10** |
| 17 | `agent/` 는 조건 칸을 읽지 않는다 | §18 |

### 고의 위반 검증

주장이 정말 잡히는지 확인하려고 production 에 결함을 **일부러** 넣고 테스트가
잡는지 보았다. 전부 되돌렸다 (commit 뒤에 실행했으므로 작업 트리로 복구를
검증할 수 있다).

| 주입 | 잡은 테스트 |
|---|---|
| A. 여섯 번째 `Condition \| None` 필드를 더한다 | `test_01` |
| B. `Requirement.condition` 을 Optional 로 바꾼다 | `test_02` |
| C. 비용 계층이 `require=None` 을 "후보 없음" 으로 읽는다 | `test_04` |
| D. 비용 계층이 `UNKNOWN` 후보를 `eligible` 로 넣는다 | `test_04` |
| E. 관측 권한이 `UNKNOWN` 을 허가로 읽는다 | `test_06` |
| F. `ObservationGrant` 의 `None` 계약을 `activation` 쪽으로 베낀다 | `test_11` |
| G. 발동기가 **출처 금지 관문보다 조건을 먼저** 본다 (실제 재배치) | `test_12` |
| G2. 발동기가 **정의 등록 관문을 조건 뒤로** 옮긴다 | `test_12` |
| H. 트리거가 정의 미등록을 `ELIGIBLE` 로 읽는다 | `test_15` |
| I. `agent/search.py` 가 `definition.activation` 을 읽는다 | `test_17` |
| J. `ConditionResult` 에 네 번째 상태를 더한다 | `test_16` |

열한 가지 모두 잡혔고, 작업 트리는 전부 되돌아갔다.

### 주입이 찾아낸 `test_12` 의 실제 구멍 (고쳤다)

G 를 처음에 **주석 한 줄**로 넣었더니 잡히지 않았다. 주석은 동작을 바꾸지
않으므로 당연한 결과지만, 왜 잡히지 않았는지 들여다보다가 `test_12` 자체의
결함을 찾았다.

처음 `test_12` 는 관문 순서를 **소스 문자열 위치**로 재고 있었다.

```python
# 틀린 방법 — 고쳤다
assert activation_source.index("definition is None") < activation_source.index(
    "if definition.activation is None:"
)
```

`_check` 와 `_check_condition` 은 **다른 메서드**이므로, 관문을 실제로 뒤로
옮겨도 두 메서드 본문의 글자 순서는 그대로다. 즉 이 단정은 **재배치를 잡지
못한다.**

`_statement_order()` 헬퍼를 더해 **호출 순서를 AST 로** 읽도록 고쳤다.

```python
assert _statement_order("engine/activation.py", "_check") == (
    "definition-none-gate", "_check_authority", "_check_condition", "_check_targets",
)
assert _statement_order("engine/effect/executor.py", "_plan") == (
    "_check_authority", "_check_supported", "_check_condition",
)
```

고친 뒤 G 를 **진짜 재배치**로 다시 넣었고 (`_check_condition` 을
`_check_authority` 앞으로 옮김), G2 (정의 등록 관문 무력화) 까지 더해 둘 다
잡히는 것을 확인했다.

고치는 과정에서 또 하나를 바로잡았다 — 실행기의 관문 호출은 `execute` 가
아니라 **`_plan`** 안에 있다 (`executor.py:532`). 함수 이름을 추측하지 않고
AST 로 확인했다.

### 회귀

| | 전 (3-E-33 완료 시점) | 후 |
|---|---|---|
| 통과 | 3,759 | 3,776 |
| 건너뜀 | 4 | 4 |
| 실패 | 0 | 0 |

## 19. Structural TODO

**신규 STRUCTURAL ID 를 만들지 않았다.** §20 의 네 조건을 하나씩 확인했다.

| 조건 | 충족? |
|---|---|
| 1. 서로 다른 계층이 동일한 값을 서로 다른 의미로 사용한다 | **예** — `activation`("적지 않았다") vs `ObservationGrant.condition`("조건이 없다") |
| 2. 실제 production path 에서 그 값이 전달된다 | **아니다** — `ObservationGrant` 생성처가 production 에 0곳 |
| 3. 현재 의미 충돌이 실제 동작에 영향을 줄 가능성이 있다 | **아니다** — 두 값이 만나는 경로가 없다 |
| 4. 기존 TODO 로 설명되지 않는다 | **아니다** — STRUCTURAL-7(컴파일러 없음)이 "등재가 손으로 이루어진다" 를 이미 설명한다 |

1번만 충족되고 2·3·4 가 충족되지 않으므로 **신규 ID 후보가 아니다.**

다음은 §20 이 "신규 ID 가 아니다" 라고 못 박은 것들이고, 이번에 발견한 것이
전부 여기 들어간다.

- `None` 이 다섯 자리에서 쓰인다 → 단순 다수 사용
- `require` 두 자리의 docstring 에 `None` 설명이 없다 → docstring 부족
- `ObservationGrant` 가 dormant 다 → dormant path
- `UnimplementedRule` 이 등재에서 0번 쓰인다 → 아직 구현되지 않은 사용
- `activation` 의 출처 구분이 없다 → 3-E-33 이 이미 기록 (STRUCTURAL-7)

**기록만 남긴다 (신규 ID 아님)**:

> `engine/effect/definition.py:251` 의 `activation` 계약은 **등재자에게 주는
> 경고**이고, `engine/activation.py:652` 의 consumer 계약은 **"그래도
> 통과시킨다"** 다. 둘이 같은 문장을 쓰지 않으므로, 읽는 사람이 둘 다 읽어야
> 전체 그림이 된다. `activation` 쪽에 `ObservationGrant` 처럼
> "옮기지 못한 조건은 `UnimplementedRule` 로 적는다" 한 줄이 있으면 그
> 왕복이 사라진다. **production diff 1~2줄짜리 문서 변경이고, 어느 쪽
> 계약을 정본으로 삼을지는 사람이 고를 일이다.**

## 20. Final Decision — **B. SEMANTICALLY_DIFFERENT_BUT_SAFE**

다른 후보를 고르지 않은 이유를 먼저 적는다.

- **A. CONTRACTS_CONSISTENT 가 아니다.** 다섯 자리의 `None` 뜻이 **같지
  않다.** `EffectDefinition.activation` · `TriggerSpec.condition` 은
  "적지 않았다", `ObservationGrant.condition` 은 "조건이 없다", 두 `require`
  는 **아무것도 적지 않는다**. "일관적이다" 고 쓰면 이 차이를 숨긴다.
- **C. AMBIGUOUS_CONTRACT 가 아니다.** 다섯 자리 **전부** 읽는 코드가
  확정되어 있고 결과가 측정된다. `require` 두 자리는 docstring 이 없지만
  읽는 곳이 `cost/resolver.py:109` 한 곳이고 동작이 명확하다 — **문서가
  없는 것과 의미를 결정할 수 없는 것은 다른 사실이다.** `G. AMBIGUOUS` 로
  분류한 자리가 0곳이다.
- **D. CONTRACT_CONFLICT 가 아니다.** caller 와 callee 가 같은 `None` 을
  다르게 읽는 자리를 찾지 못했다. 같은 `activation=None` 을 네 consumer 에
  전부 넣어 보았고 **넷이 같은 뜻으로 읽는다** (`test_15`). 계약이 반대인
  `ObservationGrant` 는 production 에서 **한 번도 생성되지 않는다**
  (`test_14`) — 두 값이 만나는 경로가 없다.
- **E. INFORMATION_LOSS 가 아니다.** `analysis` 가 유무와 내용을 두 칸에
  적고, `engine` 에 `UnimplementedRule` 이 있어 "있는데 못 옮겼다" 를
  `UNKNOWN` 으로 적을 수 있다. 표현력이 사라지는 자리가 없다. 3-E-33 이
  측정한 "`SetCondition` 이 있으면서 `activation=None` 인 등재 효과 0개" 도
  그대로다.
- **F. UNKNOWN 이 아니다.** `engine/` 65파일을 AST 로 전수 주사했고, 다섯
  자리 전부의 consumer 를 production 으로 불러 결과를 고정했다. §3 의 여덟
  질문에 모두 답했다.

**B 를 고르는 근거는 셋이다.**

1. **계층마다 `None` 의 뜻이 다르고, 그 차이에 이유가 있다.**
   `ObservationGrant` 에는 정의 등록 관문도 출처 금지 관문도 없다
   (`derive_policy` 의 관문은 셋뿐이다). 그래서 "적지 않았다" 를 막아 줄
   다른 자리가 없고 계약이 직접 `UnimplementedRule` 을 요구한다. 반대로
   `EffectDefinition.activation` 은 등재 관문 **뒤에** 있으므로 통과시켜도
   된다. **계약이 자의적으로 갈린 것이 아니라 관문 구조가 달라서 갈려야 하는
   것이다.**
2. **경계에서 안전하게 쓰인다.** 네 consumer 가 같은 뜻으로 읽고, 정의가
   없으면 조건 칸을 보기도 전에 `RULE_NOT_IMPLEMENTED` 로 막힌다
   (`test_12` 가 실제로 돌려 확인). `ConditionEvaluator` 는 `None` 을 받지
   않으므로 "`None` 을 평가해 참이 나온다" 는 경로가 **구조적으로 없다**.
   `UNKNOWN` → `FALSE` · `None` → `UNKNOWN` · `None` → `FALSE` 변환이 전부
   없다.
3. **표현 수단이 이미 다 있고, 부재를 `None` 없이 적는 설계도 이미 있다.**
   `Requirement` 는 조건이 없으면 레코드를 만들지 않고,
   `EffectAnalysis.activation` 은 유무를 별도 칸에 적는다. 즉 새 enum 이
   필요하다는 결론이 **데이터로 뒷받침되지 않는다.**

**남는 약점은 전부 문서 쪽이다.** `require` 두 자리에 `None` 설명이 없고,
`activation` 쪽에 `UnimplementedRule` 탈출구가 적혀 있지 않다. 둘 다 지금
틀린 판정을 내지 않으므로 이번 Phase 에서 고치지 않는다 (§0 · §19).

---

## 21. Next Phase Candidate (하나만 제안한다)

**Phase 3-E-35 — `UnimplementedRule` 미사용 감사: 등재 16개가 "옮기지 못한 조건" 을 어떻게 적고 있는가**

3-E-33/34 가 같은 공백을 두 번 가리켰다 — `UnimplementedRule` 은 모든
계층에서 쓸 수 있게 준비되어 있는데 `engine/effect/library.py` 의 등재
효과에서 **0번** 쓰인다. 그렇다면 지금 등재된 13개 실행 가능 효과에서
"원본 Lua 에 있는데 옮기지 않은 조건" 이 **정말 없는가**, 아니면 있는데
`None` 과 주석으로 처리되어 있는가를 Lua 원문과 대조해 전수 확인한다.

AUDIT-ONLY 로 시작한다. 결과가 "정말 없다" 면 B 의 안전성이 데이터로
확정되고, "있다" 면 그것은 3-E-33 이 `test_11` 로 고정한 "유실 0개" 를
뒤집는 발견이므로 그때 production 변경을 따로 판단한다.

---

## §24 — 최종 질문 다섯 개에 대한 답

### Q1. `engine/` 전체에서 `Condition | None` 의 의미는 일관적인가?

**아니다 — 문서상으로는 셋으로 갈린다. 그러나 읽는 쪽의 동작은 하나다.**

- `EffectDefinition.activation` · `TriggerSpec.condition` → "적지 않았다"
- `ObservationGrant.condition` → "조건이 없다"
- `CandidateSource.require` · `CardCost.require` → **아무것도 적지 않음**

그런데 다섯 자리의 **실제 읽기**는 전부 "조건 평가를 건너뛴다" 다. 즉
동작은 일관적이고 **문장이 일관적이지 않다.** 그리고 그 불일치는 §20 의
1번 근거대로 **관문 구조의 차이에서 온 것**이므로, 문장을 억지로 하나로
합치면 오히려 `ObservationGrant` 의 안전 장치를 지우게 된다.

### Q2. 같은 `None` 이 서로 다른 의미로 사용되는 실제 production 계약 충돌이 존재하는가?

**존재하지 않는다.** 두 가지로 확인했다.

1. 같은 `EffectDefinition.activation=None` 하나를 네 consumer (발동기 ·
   실행기 · `TriggerCollector` · `TriggerEligibilityJudge`) 에 전부 넣었고,
   정의가 등록된 경우 **넷이 같은 뜻으로** 읽는다. 등록되지 않은 경우
   트리거가 `UNKNOWN` 인데, 그것은 조건 칸의 뜻이 바뀐 것이 아니라
   **"정의 미등록" 이라는 다른 사실**을 적은 것이다.
2. 계약이 반대인 `ObservationGrant` 는 **production 에서 생성되지 않는다**
   — 생성처 5곳 전부 `tests/`, `derive_policy` 호출처 0곳. §20 의 2·3번
   조건이 충족되지 않으므로 계약 충돌(`H. CONTRACT_BUG`)로 분류하지 않았다.

### Q3. `EffectDefinition.activation` 과 `ObservationGrant.condition` 의 `None` 의미를 현재 구조에서 안전하게 구분할 수 있는가?

**구분할 수 있다 — 두 값이 **같은 함수에 들어오지 않기 때문**이다.**

- 타입이 같지만 **들어가는 dataclass 가 다르고**, 읽는 함수가 완전히 다르다
  (`EffectActivator._check_condition` vs `derive_policy`). 한 값을 다른
  함수에 넘길 경로가 없다.
- `ObservationGrant` 쪽은 계약이 `UnimplementedRule` 을 **명시적으로**
  요구하므로, 그 계층 안에서 "없다" 와 "안 적었다" 가 갈린다.
- `EffectDefinition` 쪽은 **등재 관문**이 그 역할을 한다.

**안전한 구분을 더 분명히 하려면** `activation` 의 docstring 에
`ObservationGrant` 와 같은 한 줄 — "옮기지 못한 조건은 `UnimplementedRule`
로 적는다" — 을 더하면 된다. 구조 변경이 아니라 문장 추가다. 이번 Phase 는
하지 않았다.

### Q4. `None` 을 명시적인 enum/state 로 바꿔야 할 필요가 실제로 입증되었는가?

**입증되지 않았다.** 세 가지 근거가 모두 반대 방향을 가리킨다.

1. **표현 수단이 이미 충분하다.** `None`(조건 없음) ·
   `UnimplementedRule`(규칙 없어 모름) · 관측 밖을 묻는 조건(정보 없어 모름) ·
   `Always(FALSE)`(거짓) 네 가지가 각각 **다른 결과**를 낸다. 새 상태가
   메우는 빈칸이 없다.
2. **부재를 `None` 없이 적는 더 나은 설계가 이미 저장소에 있다.**
   `Requirement` 는 레코드를 만들지 않고, `EffectAnalysis.activation` 은
   유무를 별도 bool 에 적는다. 즉 **enum 이 아니라 모델링**이 답이고, 그
   답도 이미 두 번 쓰였다.
3. **새 enum 은 비용이 크다.** `ConditionResult` 에 네 번째 멤버를 더하면
   `all_of` · `ConditionEvaluator` · 발동 · 해결 · 트리거 · 비용 · 검증 일곱
   계층이 모두 그 값을 처리해야 한다. 지금 틀린 판정이 하나도 없는 상태에서
   그 비용을 치를 근거가 없다.

필요가 입증되는 조건을 적어 둔다 — **"`SetCondition` 이 있는데 `activation`
이 `None` 인 등재 효과" 가 하나라도 나오면** 등재 관문이 그 역할을 못 한다는
뜻이므로 그때 다시 묻는다. 지금은 0개다 (3-E-33 `test_11`, 이번 Phase 에서도
유지).

### Q5. 다음 단계는 production 수정인가, 아니면 추가 audit 인가?

**추가 audit 이다.**

production 수정이 지금 필요하지 않은 이유: 틀린 판정이 0개, 계약 충돌이 0개,
표현력 부족이 0개. 남은 것은 문장 두 군데이고, 어느 계약을 정본으로 삼을지는
설계 결정이다.

순서는 이렇다.

1. **Phase 3-E-35 (§21)** — 등재 13개 실행 가능 효과를 Lua 원문과 대조해
   "옮기지 않은 조건" 이 정말 없는지 전수 확인. 이것이 B 판정의 안전성을
   받치는 유일한 가정이다.
2. 그 결과가 "없다" 면 → `activation` docstring 에
   `UnimplementedRule` 한 줄 + `require` 두 자리에 `None` 설명 한 줄.
   **production diff 3~4줄짜리 문서 변경**이고 동작은 바뀌지 않는다.
3. 그 결과가 "있다" 면 → 해당 효과의 `activation` 을 `None` 에서
   `UnimplementedRule` 로 바꾼다. 그것은 동작 변경이므로(발동이 막힌다)
   별도 Phase 로 판단한다.
4. **`None` → enum 치환은 지금 하지 않는다.** Q4 의 조건이 충족될 때
   다시 묻는다.

**이 Phase 는 여기서 멈춘다. 다음 Phase 는 임의로 진행하지 않는다.**
