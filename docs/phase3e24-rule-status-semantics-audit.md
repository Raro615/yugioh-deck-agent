# Phase 3-E-24 — UnimplementedRule / Event-Dependent Condition Semantics Audit

## 1. HEAD / Base

| | |
|---|---|
| Base (지시) | `dbfb4e9` |
| 실제 HEAD | `dbfb4e9` — Phase 3-E-23 (동일) |
| Working tree | clean |
| Branch | `claude/pensive-goodall-te1egy` |

## 2. BLOCKER / Engine 변경

**BLOCKER: NO** · **Engine 변경: NO** (production diff 0줄). 추가한 것은
`tests/test_rule_status_semantics_audit.py` (13개)와 이 문서.

## 3. 핵심 결론

> **네 의미는 이미 구조로 갈려 있다. 그리고 production 경로는 그것을 정확히
> 지킨다.** 느슨한 자리는 **잠든 트리거 계층 두 곳**이고, 둘 다 기존 구조로
> 표현할 수 있으므로 **새 enum 도 새 STRUCTURAL ID 도 필요하지 않다.**

의미를 담는 것은 **하나의 enum 이 아니라 두 축**이다.

```
ValidationResult
  validity      VALID · INVALID · UNKNOWN        ← 허가인가
  code          48개                              ← 왜인가
  missing_rule  "없는 규칙 계층의 이름"            ← 무엇이 없는가
  notes         조건 계층이 남긴 말 그대로
```

그래서 다섯 문장이 각각 이렇게 적힌다.

| 문장 | 현재 표현 |
|---|---|
| "이 조건은 참이다" | `VALID` |
| "이 조건은 거짓이다" | `INVALID` + 요구별 코드 (`NOT_TURN_PLAYER` · `ZONE_FULL` …) |
| "규칙은 있지만 지금 필요한 정보가 없다" | `UNKNOWN` + `INFORMATION_UNAVAILABLE` (가려진 카드면 `HIDDEN_CARD`) |
| "정보는 있지만 판정 구현이 없다" | `UNKNOWN` + `RULE_NOT_IMPLEMENTED` + `missing_rule` |
| "이 근거로는 실행하지 않는다 (정책)" | `INVALID` + **`EXECUTION_FORBIDDEN`** (ADR-004) |

**구조가 혼동을 막는다**: `ValidationResult.invalid()` 는 `missing_rule` 을
**받지 못한다.** "규칙이 없다" 를 "규칙 위반" 으로 옮겨 적으려면 그 정보를
버려야 하고, 그러면 호출자가 즉시 깨진다 (고의 위반 B 가 실제로 그렇게 잡혔다).

## 4. 현재 상태 표현 감사

| 상태 | 정의된 의미 | 실제 사용 위치 | 호출자가 구분하는가 | 문제 |
|---|---|---|---|---|
| `ActionValidity.VALID` | 허가 | 전 production | — | 없음 |
| `ActionValidity.INVALID` | 확실한 거부 | `is ActionValidity.INVALID` 비교가 여러 곳 | **그렇다** | 없음 |
| `ActionValidity.UNKNOWN` | 판정 불가 | `legal_actions` 는 `withheld` 로 보낸다 | **그렇다** — `is not VALID`(허가 아님)와 `is UNKNOWN`(모름)을 따로 쓴다 | 없음 |
| `ValidationCode.RULE_NOT_IMPLEMENTED` | (docstring 없음) | **62곳** — 최다 | 부분적 | **여러 의미가 섞인다** (아래) |
| `ValidationCode.INFORMATION_UNAVAILABLE` | "요구를 판정할 정보가 없다" | 11곳 | 그렇다 | 없음 |
| `ValidationCode.HIDDEN_CARD` | "관측에 없다 — **없다는 뜻이 아니다**" | 2곳 | 그렇다 | 없음 |
| `ValidationCode.EXECUTION_FORBIDDEN` | "출처가 실행을 금지한다 (ADR-004)" | `GateVerdict.forbids` 가 이것으로 판단 | 그렇다 | 없음 |
| `ValidationCode.CANDIDATE_NOT_ELIGIBLE` | 후보가 적격이 아니다 | 4곳 | 그렇다 | **쓸 자리에서 안 쓴다** (아래) |
| `ConditionResult` TRUE/FALSE/UNKNOWN | 3값 Kleene | 조건 계층 전체 | **그렇다** (`all_of`/`any_of`) | 없음 |
| `TriggerStatus` ELIGIBLE/INELIGIBLE/UNKNOWN/FORBIDDEN | 후보의 상태 | 잠든 계층 | **그렇다** (`is_candidate` 는 ELIGIBLE 만) | 없음 |
| `EvalReadiness` EVALUABLE/NEEDS_CONTEXT/UNKNOWN | 분석 계층의 평가 가능성 | `analysis/` | 그렇다 | 없음 — **구현 여부를 말하지 않는다** (의도) |
| `ExecutionAvailability` executable/no_implementation/forbidden_source/unverified/unknown | 이 엔진 빌드가 실행할 수 있는가 (ADR-006) | `engine/effect/library.py` | 그렇다 | 문서(ADR-006)의 이름과 코드의 이름이 다르다 — 🟢 |
| `AnalysisStatus` lua_verified/text_derived/no_effect/unavailable/unknown | 데이터가 어디서 왔는가 | `core/provenance.py` | 그렇다 | 없음 |
| `UNRESOLVED_*` 목록 | 아직 보지 않은 규칙의 **이름들** | `turn_progression` · `trigger_order` | 그렇다 | 없음 |

같은 enum 이 서로 다른 의미로 쓰이는 자리는 **`RULE_NOT_IMPLEMENTED` 하나**다.
62곳의 문구를 읽으면 최소 네 뜻이 섞여 있다.

1. **진짜 미구현** — "들여다본 덱을 섞을 수 없습니다", "{index}번 조작을 수행할 수 없습니다"
2. **정책적 금지** — "공식 텍스트에서 유추한 효과는 실행하지 않습니다 (ADR-004)"
   → 더 맞는 코드가 있다 (`EXECUTION_FORBIDDEN`)
3. **등록되지 않음 (ADR-006)** — "정의가 등록되어 있지 않아 조건을 확인할 수 없습니다"
4. **조건이 거짓** — **"조건이 거짓입니다: …"** → 더 맞는 코드가 있다 (`CANDIDATE_NOT_ELIGIBLE`)

2·4 는 **잠든 트리거 계층에서만** 나타나고, `status` 쪽은 (`FORBIDDEN` ·
`INELIGIBLE`) **맞게 적힌다.** 즉 **판정은 틀리지 않고 이유만 틀린다.**

## 5. Condition Evaluation Flow

```
EffectSpec                 Lua 에서 읽은 기계적 명세
  → EffectDefinition       손으로 등록한 정의 (activation: Condition | None)
  → Condition (23개)       전부 "지금 판" 만 묻는다 (3-E-23)
  → ConditionContext       player · source · effect_ref · targets
  → ConditionEvaluator     TRUE / FALSE / UNKNOWN + unknown_reasons + missing_rules
  → ActionValidator._check_requirements
        FALSE                     → invalid(요구별 코드)
        UNKNOWN + 규칙 이름 있음   → unknown(RULE_NOT_IMPLEMENTED, missing_rule=…)
        UNKNOWN + 이름 없음       → unknown(INFORMATION_UNAVAILABLE)
  → ValidationResult       legal_actions 가 allowed / withheld 로 가른다
```

그 갈림이 코드에 주석으로 적혀 있다 — **"'정보가 없어서' 와 '규칙이 없어서' 는
다른 사실이다. 조건 자신이 안다 — 검증기가 추측하지 않는다."**

실측으로도 확인했다 (`test_03`): 실제 듀얼의 `ACTIVATE_CARD` 는
`validity=UNKNOWN` · `code=RULE_NOT_IMPLEMENTED` · `missing_rule` 이 채워진 채
돌아오고, `legal_actions().allowed` 에는 **없고** `withheld` 에 `missing` 과 함께
남는다.

## 6. Event-Dependent Condition Corpus

3-E-23 의 측정을 그대로 쓴다 (조건 트리가 있는 효과 블록 9,630 · leaf 20,547).
§5 의 7분류를 **두 축**으로 나눠 적는다 — 하나로 섞으면 중복 집계가 된다.

### 축 1 — 분석 계층이 말하는 것 (`EvalReadiness`)

| 분류 | 수 | 비율 |
|---|---|---|
| **A** STATE_ONLY (= `EVALUABLE`) | 6,684 | 32.53% |
| **B·C·D** 문맥 필요 (= `NEEDS_CONTEXT`) | 8,511 | 41.42% |
| **F** UNKNOWN_DATA (= `UNKNOWN`, 안전하게 해석 불가) | 5,352 | 26.05% |

B·C·D 의 내부 (중복 없이):

| | 술어 | 수 |
|---|---|---|
| **B** EVENT_CONTEXT_REQUIRED | `event_reason` 928 · `group_exists` 1,330 · `group_contains` 248 · `summon_type` 111 | **2,617** |
| **C** PREVIOUS_STATE_REQUIRED | `previous_location` 758 · `previous_controller` 314 · `previous_position` 202 | **1,274** |
| **D** TIMING/CHAIN_REQUIRED | `chain_effect_type` 962 · `chain_state` 785 · `battle` 1,154 | **2,901** |
| (그 밖) | `player_comparison` 990 · `flag_effect` 325 · `card_status` 324 · `player_affected` 80 | 1,719 |

### 축 2 — 엔진이 말할 수 있는 것

| 분류 | 현재 |
|---|---|
| **E** RULE_MISSING (엔진에 그 술어가 없다) | **B·C·D 전부** — 조건 어휘 23개 중 사건을 묻는 것이 0개 (3-E-23) |
| **G** HIDDEN_INFORMATION | 코드로 **따로** 있다 (`HIDDEN_CARD` · `INFORMATION_UNAVAILABLE`) · 후보 수집은 `unchecked` 로 남긴다 |

→ **E 와 B·C·D 는 같은 사실의 두 면이다** (데이터는 요구하고 엔진에는 술어가
없다). 그래서 "E 가 몇 건" 을 따로 세지 않고 이렇게 적는다.

## 7. UnimplementedRule 후보 — 기존 구조로 충분한가

| 질문 | 답 |
|---|---|
| 1. "규칙은 있는데 엔진에 구현이 없음" 을 표현할 수단이 있는가 | **있다** — `UnimplementedRule`(언제나 `UNKNOWN` + `missing_rules`) · `ValidationCode.RULE_NOT_IMPLEMENTED` + `missing_rule` · `ExecutionAvailability.NO_IMPLEMENTATION` |
| 2. 공식 근거는 있는데 실행 구현이 없는 경우 | `LibraryEntry.executable=False` + `note`("무엇이 없어서인지 적어야 합니다" — 생성자가 강제한다) |
| 3. 규칙 자체가 없는 경우와 구현만 없는 경우를 구분하는가 | **구분한다** — 전자는 `rules/concept_map.py` 의 `ConceptSupport` 와 `UNRESOLVED_*` 목록, 후자는 위 1번 |
| 4. `UNVERIFIED` 와 `UNIMPLEMENTED` 를 구분해야 하는가 | **이미 구분되어 있다** — `ExecutionAvailability.unverified`(근거 미검증, ADR-004) vs `no_implementation`(구현 없음) |
| 5. `UNKNOWN` 으로 뭉개는 사례가 있는가 | **production 에는 없다.** 잠든 트리거 계층의 `code` 선택 두 곳만 부정확하다 (§4) |

→ **새 enum 을 만들지 않는다.** 필요한 어휘가 전부 있다.

## 8. Official Rule vs Implementation — 네 축

| ① 규칙 | ② 데이터 | ③ 문맥 | ④ 구현 | 현재 표현 | 실제 사례 |
|---|---|---|---|---|---|
| 있음 | 있음 | **없음** | 있음 | `UNKNOWN` + `INFORMATION_UNAVAILABLE` | 가려진 카드를 가리킨 요구 |
| 있음 | 있음 | 있음 | **없음** | `UNKNOWN` + `RULE_NOT_IMPLEMENTED` + `missing_rule` | `ACTIVATE_CARD` 의 남은 적법성 |
| **없음** | 있음 | 있음 | 없음 | `UNRESOLVED_*` 목록 + `ConceptSupport` | SEGOC · 놓친 타이밍 (3-E-21: 룰북에 문장이 없다) |
| 있음 | **없음** | — | — | `CARD_DEFINITION_UNAVAILABLE` · `EFFECT_LIST_UNRELIABLE` · `AnalysisStatus.UNAVAILABLE` | 정의를 못 읽음 · `effect_count==0` |
| 있음 | 있음 | 있음 | 있음 (단 **근거 금지**) | `INVALID` + `EXECUTION_FORBIDDEN` | `TEXT_DERIVED` (ADR-004) |

네 축이 **서로 다른 계층**에 산다는 점이 중요하다 — ADR-006 이 그 이유를 적어
두었다: "같은 카드 데이터를 쓰는 두 엔진 빌드가 서로 다른 답을 내야 하므로,
카드 데이터에 저장하면 반드시 어긋난다."

## 9. Trigger Eligibility 영향

§9 가 제안한 "안전한 원칙" 은 **이미 구현되어 있다** (`TriggerEligibility.fold`,
`test_06`):

```
FORBIDDEN  >  INELIGIBLE  >  UNKNOWN  >  ELIGIBLE
```

코드의 주석이 그대로 그 원칙이다 — "판정 불가가 있으면 `UNKNOWN` — **거부보다
약하고 통과보다 약하다.** 모르는 것을 거짓으로도 참으로도 접지 않는다."

그리고 `TriggerStatus.is_candidate` 는 `ELIGIBLE` 일 때만 참이다 (`test_07`) —
`if status is not INELIGIBLE:` 같은 코드로 `UNKNOWN`·`FORBIDDEN` 이 허가로
새지 않는다.

### 발견된 느슨한 자리 둘 (둘 다 dormant · production 영향 없음)

**① `code` 가 `status` 와 어긋난다** (`test_08`)

```python
if combined is ConditionResult.FALSE:
    return TriggerCandidate(..., status=TriggerStatus.INELIGIBLE,
                            code=ValidationCode.RULE_NOT_IMPLEMENTED,   # ← 거짓인데 "미구현"
                            reason=f"조건이 거짓입니다: {described}")
```

금지 쪽도 같다 — `status=FORBIDDEN` 인데 `code=RULE_NOT_IMPLEMENTED` 다. 그런데
**금지를 알아보는 쪽은 코드로 판단한다** (`GateVerdict.forbids` ↔
`EXECUTION_FORBIDDEN`). 두 계층이 같은 사실을 서로 다른 코드로 말한다.

**② "조건이 없다" 와 "확인하지 못했다" 가 생성자 인자로 갈린다** (`test_09`)

| 호출 | 결과 |
|---|---|
| `TriggerCollector(view, registry)` | `ELIGIBLE` + `OK` — "타이밍이 맞고 걸린 조건이 없습니다" |
| `TriggerCollector(view, registry, definition_registry())` | `UNKNOWN` + `RULE_NOT_IMPLEMENTED` — "정의가 등록되어 있지 않아 조건을 확인할 수 없습니다" |

같은 선언 · 같은 사건인데 **`definitions` 를 주었는지에 따라 허가와 모름이
갈린다.** 방향이 위험한 쪽(모름 → 허가)이다. 선언 자신의 설명은 이미 올바른
원칙을 적어 두었다 — "`None` 이면 **조건이 없다는 뜻이 아니라 적지 않았다는
뜻**이다."

**남기는 계약**: 잠든 계층을 연결할 때 **production 에서
`TriggerCollector` 를 만들 때 `definitions` 를 반드시 넘긴다** (또는 그 인자를
필수로 바꾼다 — 그것이 미래의 최소 수정이다). 이 Phase 는 바꾸지 않았다.

## 10. ActionValidator 영향

**변경 없음. 그리고 변경할 이유가 없다** — §5 의 세 길이 이미 정확하다.

§8 의 세 경우에 대한 판정:

| Case | 지금 무엇이 나오는가 | 그것이 맞는가 |
|---|---|---|
| A "발동 가능하지만 Event Context 가 없다" | `UNKNOWN` + `INFORMATION_UNAVAILABLE` (또는 조건이 `UnimplementedRule` 이면 `RULE_NOT_IMPLEMENTED`) | **맞다** |
| B "공식 규칙은 있는데 Validator 가 구현하지 않았다" | `UNKNOWN` + `RULE_NOT_IMPLEMENTED` + `missing_rule` | **맞다** |
| C "공식 규칙 자체가 등록되지 않았다" | 같은 모양(`UNKNOWN` + `RULE_NOT_IMPLEMENTED`)이고 `missing_rule` 의 **문자열**로만 구분된다 | **지금은 충분하다.** 둘 다 "허가 아님 · 금지 아님" 이고, 구분이 필요해지는 것은 진척 추적이지 판정이 아니다 |

→ `VALID` 는 어느 경우에도 **아니다.** `INVALID` 도 아니다. **`UNKNOWN` 이
가장 안전하고, 현재 코드가 그것을 지킨다.**

## 11. Search 영향

**변경 없음** (`test_13`).

* UNKNOWN 판정을 받은 행위는 `legal_actions().allowed` 에 **들어오지 않으므로**
  순위에 오르지 않는다. 사본은 `allowed` 밖의 행위를 `NOT_A_CANDIDATE` 로 돌린다.
* 평가는 UNKNOWN 을 **0점으로 접지 않는다** — `ExclusionCategory.UNKNOWN` 과
  `partial`("`UNKNOWN` 이 하나라도 있는가")로 **표시**한다 (Phase 3-E-7 · 3-E-8).
* 시뮬레이션에는 `SimulationStatus.UNKNOWN` · `REFUSED` · `NOT_A_CANDIDATE` 가
  따로 있다 — "모름" 과 "거부" 와 "후보 아님" 을 섞지 않는다.

## 12. Hidden Information

**누출 없음 · `GameStateView` 변경 없음.** `HIDDEN_CARD` 가 "관측에 없다 —
**없다는 뜻이 아니다**" 를 스스로 적어 두었고 `RULE_NOT_IMPLEMENTED` 와 다른
값이며 쓰이는 파일도 다르다 (`test_12`). 후보 수집은 가려진 자리를
`unchecked` 로 남긴다 (3-E-20).

## 13. Tests

신규 `tests/test_rule_status_semantics_audit.py` — **13개**.

| # | 검증 |
|---|---|
| 01 | 허가(3값)와 이유(48코드)가 따로 있다 · `invalid()` 는 `missing_rule` 을 **받지 못한다** |
| 02 | 검증기가 거짓/모름/미구현의 세 길을 가른다 |
| 03 | 실제 듀얼에서 UNKNOWN 이 `withheld` 로 가고 `missing_rule` 이 채워진다 |
| 04 | 3값 논리 — `FALSE` 가 `UNKNOWN` 을 이기고, 빈 묶음 규약 |
| 05 | `UnimplementedRule` 은 언제나 UNKNOWN + 이름을 남긴다 · `Always` 와 다르다 |
| 06 | `fold` 가 FORBIDDEN > INELIGIBLE > UNKNOWN > ELIGIBLE |
| 07 | `is_candidate` 는 ELIGIBLE 만 |
| 08 | **발견 ①** — 조건 거짓에 `RULE_NOT_IMPLEMENTED` · 금지도 같은 코드 |
| 09 | **발견 ②** — `definitions` 유무로 ELIGIBLE/UNKNOWN 이 갈린다 |
| 10 | `ExecutionAvailability` 가 "규칙 있음 · 구현 없음" 을 이미 말한다 |
| 11 | 분석 계층은 `needs_context` 까지만 말한다 (계층 책임 경계) |
| 12 | 가려진 정보와 미구현이 다른 코드다 |
| 13 | 탐색은 UNKNOWN 을 0점으로 접지 않는다 |

고의 위반 5건 — **전부 잡혔다** (B 는 두 번째 시도에서):

| | 위반 | 잡은 테스트 |
|---|---|---|
| A | `all_of` 가 UNKNOWN 을 거짓으로 접는다 | 04 |
| B | 검증기가 모름을 금지로 바꾼다 | 03 — **첫 시도는 놓쳤다** (내가 패치한 분기가 그 행위의 경로가 아니었다). 실제 경로를 패치하니 `invalid()` 가 `missing_rule` 을 거부해 **구조가 먼저 막았다** |
| C | `is_candidate` 가 UNKNOWN 을 허가로 센다 | 07 |
| D | `fold` 에서 금지가 덮이지 않는다 | 06 |
| E | 정의 미등록을 ELIGIBLE 로 바꾼다 | 09 |

전체: **3630 passed · 4 skipped · 0 failed · 391s.**
Regression **0** · 신규 13 · 수정 **0** · 삭제 **0** · skip 증가 **0**.

## 14. 신규 STRUCTURAL

**신규 STRUCTURAL 없음.**

§16 의 다섯 조건으로 따진 결과 — 발견 ①②에 대해:

| 조건 | 충족 | 근거 |
|---|---|---|
| 1. 기존 TODO 로 해결되지 않는다 | 그렇다 | 어느 TODO 도 이 두 자리를 적지 않았다 |
| 2. **구조적으로 표현할 수 없다** | **아니다** | `CANDIDATE_NOT_ELIGIBLE` · `EXECUTION_FORBIDDEN` 이 이미 있고, `definitions` 를 넘기면 `UNKNOWN` 이 나온다 |
| 3. 향후 연결에 필수다 | 그렇다 | 연결할 때 반드시 고쳐야 한다 |
| 4. 단순 구현 부족이 아니다 | 그렇다 | 의미 문제다 |
| 5. **기존 semantics 로 안전하게 표현할 수 없다** | **아니다** | 위 2번과 같다 |

→ 조건 2·5 불성립 → **감사 소견 + 연결 계약**으로 남긴다 (🟠 성격이지만 ID 없음).

## 15. 기존 TODO

| ID | 상태 |
|---|---|
| STRUCTURAL-31 / -32 / -33 | 유지 |
| STRUCTURAL-34 / -124 / -128 / -131 / -133 | 유지 — unaffected |
| STRUCTURAL-134 · SET_ACTIVATION_MISSING | RESOLVED 유지 |
| SET_ACTIVATION_TIMING · SET_ACTIVATION_EXECUTION · SET_CARD_EFFECT_EXECUTION | 유지 |
| AFTER_CHAIN_RULE · UNRESOLVED_PROGRESSION_RULES · UNRESOLVED_ORDER_RULES | 유지 |
| 🟢 ADR-006 문서의 `ExecutionAvailability` 이름이 코드와 다르다 | **새로 기록** (COSMETIC — 의미는 같은 축) |

## 16. 최종 판정

**B. AUDIT-ONLY / FUTURE ARCHITECTURE GAP.**

`C`(STRUCTURAL ISSUE)가 아닌 이유: 상태 표현이 **구조적으로** 혼동하고 있지
않다. production 경로는 네 의미를 정확히 지키고, 흐트러진 두 자리는 잠든 계층의
`code` 선택과 생성자 기본값이며 **기존 어휘로 고칠 수 있다.**

## 17. 다음 Phase 후보 — 정확히 하나

> **`LibraryEntry` 등록 관문의 감사 — "사건 의존 조건을 가진 카드를 등록하려
> 하면 지금 구조가 막는가, 통과시키는가?"**
>
> 이번 Phase 가 확인한 것은 **표현 수단이 충분하다**는 것이다. 그러면 다음
> 질문은 그 수단이 **강제되는가**다. `LibraryEntry.__post_init__` 은 이미
> "실행하지 않는 효과에는 **무엇이 없어서인지** 적어야 합니다" 를 **예외로
> 강제**하고, `EffectDefinition` 에는 유발 칸이 없다 (3-E-21). 그러면 사건
> 의존 조건을 가진 카드를 `executable=True` 로 등록하려 할 때:
>
> * 조건을 `None` 으로 두면 — "조건이 없다" 로 읽혀 **조용히 통과**하는가?
>   (`all_of([])` 가 `TRUE` 이므로 그럴 수 있다.)
> * `UnimplementedRule` 을 적으면 — 발동 후보에서 `UNKNOWN` 으로 정확히
>   빠지는가? (그러면 그 카드는 등록해도 **절대 발동되지 않는다** — 그것이
>   맞는 상태인가?)
>
> 이 둘을 실측해야 사건 술어를 **안전하게** 하나씩 추가할 수 있다. 등록 관문이
> 조용히 통과시킨다면 그것은 dormant 가 아니라 **production 경로의 구멍**이다.

다음 Phase 는 지시 없이 진행하지 않는다.
