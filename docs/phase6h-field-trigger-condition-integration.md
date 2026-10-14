# Phase 6-H — FIELD TRIGGER 사건 주체 조건 해석 및 실행 경로 준비

작업 브랜치: `claude/pensive-goodall-te1egy`
선행: [6-E](phase6e-trigger-analysis-candidate-integration.md) ·
[6-F](phase6f-trigger-event-subject-validation.md) ·
[6-G](phase6g-trigger-activation-location.md)

이 단계가 한 일은 두 가지다.

1. `FIELD` 등록 784건의 **Lua 조건 함수**에서 사건 주체 관계를 하나 읽어
   기존 판정 계층에 연결했다 — **80건**이 이제 확정적으로 **거부**된다.
2. §10 이 요구한 **최소 수직 시나리오를 실제로 찾아 검증했다.** 지어낸
   delta 없이, 실제 카드의 실제 실행이 만든 사건에서 6-F 의 주체 축과 6-G 의
   위치 축이 **동시에 통과**하는 경로가 존재한다.

새 듀얼 엔진도, 새 트리거 엔진도, 새 Lua 인터프리터도 만들지 않았다.

---

## 1. FIELD 등록 784건의 실제 구조와 조건 분포

측정은 전부 전수 조사다 (카드 전체 → `EffectAnalyzer` → `compile_trigger_spec`).

### 1.1 축의 출발점

| 항목 | 수 |
|---|---|
| 컴파일된 TRIGGER 등록 전체 | 4,173 |
| `SELF` (등록 범위 `SINGLE`) | 3,389 |
| **주체 미확정 (`FIELD`)** | **784** |
| 영역 선언이 있는 등록 | 816 |

6-G 가 남긴 그림은 **두 축이 거의 상보적**이라는 것이었다 — `FIELD` 784건은
전부 영역 선언을 갖고 주체를 모르고, `SELF` 3,389건은 주체를 알고 대부분
영역을 모른다.

### 1.2 조건 함수를 읽을 수 있는가 (`FIELD` 784건)

| 범주 | 수 |
|---|---|
| 조건 인자가 **이름**이고 같은 파일에서 본문을 찾았다 | 655 |
| 조건 인자가 **인라인 함수**다 (본문이 인자 자체) | 40 |
| **본문을 얻을 수 있다 (합계)** | **695** |
| `SetCondition` 이 없다 | 73 |
| 인자가 식이거나 다른 파일의 함수다 (`aux.*` 등) | 15 |
| 이름은 있는데 본문을 못 찾았다 | 1 |
| **본문을 얻을 수 없다 (합계)** | **89** |

### 1.3 조건 본문의 어휘 (주체 관계에 관한 것만)

| 호출 | 수 | 무엇을 묻는가 |
|---|---|---|
| `eg:IsExists(필터,1,e:GetHandler(),tp)` | 379 | 그룹에 **무엇이 있는가** (소유자는 예외 인자) |
| **`eg:IsContains(e:GetHandler())`** | **84** | **그룹이 소유자를 품는가** ← 이 축 |
| `eg:GetFirst()` | 28 | 그룹의 첫 장을 꺼낸다 |
| `IsPreviousLocation` | 10 | 이동 **전** 자리 (6-G 의 축) |
| `IsControler` | 9 | 컨트롤러 |

주체와 소유자를 **직접 맞춰 보는** 호출은 `eg:IsContains(e:GetHandler())`
하나뿐이고, 그래서 이번 단계가 읽은 것도 그것 하나다.

### 1.4 그 84건의 **구문 자리** (전수 분류)

| 자리 | 수 | 뜻 |
|---|---|---|
| `not …` + `and` (필요조건) | 75 | 주체 ≠ 이 카드 |
| `if … then return false end` (조기 반환) | 5 | 주체 ≠ 이 카드 |
| **거부 방향 합계** | **80** | **컴파일한다** |
| 긍정 자리 + `#eg==N` | 4 | 그룹 크기 단정 — **주장하지 않는다** |
| `or` 안에 있다 | 0 | — |
| 같은 본문에 둘 이상 | 0 | — |

- 거부 방향 **80건 · 카드 64장** · 사건은 `monster_summoned` 58 ·
  `card_moved` 22 — **둘 다 엔진이 지원하는 시점**이다.
- 80건 전부 영역 선언을 갖고 있으므로, **두 축이 모두 데이터로 정해진
  등록이 31 → 111 로 늘었다** (단, 새로 늘어난 80 은 통과가 아니라 거부
  방향이다 — §7).

### 1.5 공식 원문 대조 (표본)

| 카드 | 공식 원문 | Lua |
|---|---|---|
| DDD 질풍왕 알렉산더 (987311) | 「이 카드가 몬스터 존에 존재하고 자신 필드에 **이 카드 이외의** "DD" 몬스터가 일반 소환 / 특수 소환되었을 경우」 | `return not eg:IsContains(e:GetHandler()) and eg:IsExists(s.cfilter,1,nil,tp)` |
| 토폴로직 폭탄 드래곤 (5821478) | 「이 카드가 이미 몬스터 존에 존재하는 상태에서, **이 카드 이외의** 몬스터가 …」 | `if eg:IsContains(e:GetHandler()) then return false end` |
| 초고대 티라노 (6849042) | 「이 카드가 몬스터 존에 존재하고, **자신 묘지에서** 공룡족 몬스터가 특수 소환되었을 때」 | `return not eg:IsContains(e:GetHandler()) and …` |
| 요위 (33393090) | 「**이 카드 1장만이** 일반 소환 / 반전 소환 / 특수 소환에 성공했을 경우」 | `return #eg==1 and eg:IsContains(e:GetHandler())` ← **주장하지 않음** |

공식 데이터베이스(`https://www.db.yugioh-card.com/yugiohdb/`) 원문을 그대로
인용했다. 원문을 손으로 번역하지 않았다.

---

## 2. 기존 Lua 조건 분석 지원 범위

### 2.1 두 파서가 조건을 보는 깊이가 다르다

| 계층 | `SetCondition` 을 읽는가 | 본문을 읽는가 |
|---|---|---|
| `sources/lua_loader.py` | ❌ — 설정자 디스패치가 `Type` · `Code` · `Range` · `TargetRange` · `Category` · `Property` · `CountLimit` **일곱 개**만 처리한다 | ❌ |
| `analysis/effect_analyzer.py` | ✅ — `_RE_SETTER` 가 `Cost` · `Condition` · `Target` · `Operation` 네 개를 모은다 | ✅ — `_collect_functions` 가 함수명 → 본문 사전을 만든다 |

`EffectSpec` (로더의 모델, 9칸) 에는 조건에 관한 칸이 없고,
`EffectAnalysis` (분석기의 모델) 에는 `has_condition` · `condition_raw` 가
**이미 있었다.**

### 2.2 그래서 무엇이 바뀌었는가

`condition_raw` 는 **기록되기만 하고 해석되지 않았다.** 이번 단계가 더한 것은
그 원문에서 주체 관계 한 가지를 읽는 **해석기**이고, 데이터 수집 경로는
하나도 새로 만들지 않았다.

### 2.3 이 축에서 지원하지 않는 Lua 표현

- `aux.*` 등 **다른 파일의 함수** — 본문을 얻을 수 없다 (15건). 이름만으로
  뜻을 추측하지 않는다.
- `eg:IsExists(…)` · `eg:GetFirst()` — "그룹에 무엇이 있는가" 이고 주체
  관계가 아니다.
- `#eg==N` — 그룹 **크기** 단정. 엔진의 사건이 크기를 들고 있지 않다 (§7).

---

## 3. 사건 주체 관계를 해석하지 못한 근본 원인

**조사 중에 내 첫 결론이 틀렸고, 코드로 다시 확인해 바로잡았다.**

처음 찾은 원인은 "`sources/lua_loader.py` 가 `SetCondition` 을 전혀 읽지
않는다" 였다. 그것은 사실이지만 **근본 원인이 아니었다.** 그 결론대로
갔다면 로더 수정 + `LuaScriptInfo` 평행 목록 + `CACHE_PREFIX` 범프 + 핀이
걸린 기존 테스트 수정이 필요했고, 그것은 §3-15 · §13 이 "사용자 승인을
기다린다" 고 한 범위의 변경이었다.

코드를 더 읽어 보니 **분석 계층이 이미 `SetCondition` 을 읽고 있었다**
(`_collect_handlers` 가 로더와 **같은 바인딩 규칙**으로 모으고,
`_analyze_effect` 가 `condition_raw` 로 기록한다). 진짜 원인은 훨씬 좁다.

> **원문은 기록되어 있었고, 그것을 해석하는 코드가 없었다.**
> 그리고 `compile_trigger_spec` 에 그 정보를 넘기는 인자가 없었다.

그래서 이번 단계의 변경은 로더 · `EffectSpec` · 캐시 서명을 **건드리지
않는다** (§13 의 범위 제한 준수). 3-F-36/37 이 금지한 `EffectSpec` API 변경도
일어나지 않았다.

---

## 4. 채택한 최소 구현 방식 및 대안 비교

| 대안 | 변경 범위 | 판단 |
|---|---|---|
| **A. 분석 계층이 해석하고, 컴파일러가 원시값으로 받는다** | 4파일 · +231/−3 | **채택** |
| B. 로더가 조건 함수 식별자를 기록하고 `LuaScriptInfo` 평행 목록에 싣는다 | 로더 + 모델 + 캐시 서명 + 핀 걸린 기존 테스트 | 기각 — §13 범위 밖, 승인 필요 |
| C. 조건 AST 에 새 노드를 만들어 `ConditionEvaluator` 가 평가한다 | 조건 모델 + 직렬화 + 평가기 | 기각 — **조건은 사건을 볼 수 없다** (`ConditionContext` 에 사건 칸이 없다). 6-F 가 같은 이유로 조건에서 주체를 뺐다 |
| D. 784건을 일괄 `ANY` 로 변환한다 | 1줄 | 기각 — §3-5 가 금지하고, 6-E 가 재현한 거짓 양성이 바로 그것이다 |

A 가 ADR-007 을 지킨다. `engine` 은 `analysis` 에서 `LimitScope` 하나만
가져오고, 이번에도 이름을 가져오지 않았다 — 주장은 **문자열**로 건너간다
(`"not_handler"`). 그 대가로 두 어휘가 갈라질 수 있으므로 `test_01` 이
`NOT_HANDLER_CLAIM == EventSubjectClaim.NOT_HANDLER.value` 를 고정한다
(6-F 가 `EVENT_SUBJECT_RULE == SUBJECT_MISSING_RULE` 로 한 것과 같다).

---

## 5. 변경한 파일과 함수

| 파일 | 증감 | 무엇 |
|---|---|---|
| `analysis/effect_model.py` | +31 | `EventSubjectClaim` (값 1개) · `EffectAnalysis.event_subject_claim` |
| `analysis/effect_analyzer.py` | +101 | `_RE_EVENT_GROUP_HAS_HANDLER` 등 패턴 4개 · `_condition_body` · `_event_subject_claim` · `_analyze_effect` 에서 호출 |
| `engine/trigger.py` | +63/−3 | `TriggerSubject.OTHER` · `GROUP_MEMBERSHIP_RULE` · `subject_relation` 의 두 분기 |
| `engine/trigger_compiler.py` | +30 | `NOT_HANDLER_CLAIM` · `compile_trigger_spec(event_subject_claim=…)` |
| `tests/engine/test_trigger_event_subject.py` | +8/−1 | 기존 핀 하나 (§14 에 이유) |
| `tests/engine/test_trigger_event_subject_condition.py` | +935 | 신규 22개 테스트 |

**새 AST 노드를 만들지 않았다** (§6 의 관문 — 기존 노드로 표현할 수 없는
이유를 찾기 전에, 이 축이 **조건이 아니라 사건 관계**라는 것이 6-F 에서 이미
정해져 있었다). 조건 직렬화 · 평가기 · 불확실성 전파는 손대지 않았다.

### 5.1 핵심 코드

```python
# analysis — 구문 자리로 판정한다 (세 조건 전부 요구)
hits = _RE_EVENT_GROUP_HAS_HANDLER.findall(flat)
if len(hits) != 1 or " or " in flat:
    return None
if _RE_NEGATED_TAIL.search(before):                       # not …
    return EventSubjectClaim.NOT_HANDLER
if _RE_IF_TAIL.search(before) and _RE_RETURN_FALSE.match(after):   # 조기 반환
    return EventSubjectClaim.NOT_HANDLER
return None                                                # 긍정은 주장 안 함

# engine/trigger_compiler — 선언을 덮지 않는다
subject = TriggerSubject.SELF if SELF_SCOPE_DECLARATION in kinds else None
if subject is None and event_subject_claim == NOT_HANDLER_CLAIM:
    subject = TriggerSubject.OTHER

# engine/trigger — 거부만 하고 통과시키지 못한다
if subject == source:
    if spec.subject is TriggerSubject.OTHER:
        return ValidationResult.invalid(ValidationCode.CANDIDATE_NOT_ELIGIBLE, …)
    return ValidationResult.valid(…)
if spec.subject is TriggerSubject.OTHER:
    return ValidationResult.unknown(
        ValidationCode.RULE_NOT_IMPLEMENTED, …,
        missing_rule=GROUP_MEMBERSHIP_RULE, notes=(GROUP_MEMBERSHIP_RULE,))
```

### 5.2 판정기 · 수집기는 **고치지 않았다**

6-F 가 이미 맞춰 둔 자리가 그대로 받는다.

- `TriggerEligibilityJudge._event_relation` — 낼 수 있는 `(validity, code)`
  짝 **네 개**가 이미 리터럴로 적혀 있고, `OTHER` 의 세 답이 그 안에 전부
  들어간다 (`VALID` 는 나오지 않는다). 3-E-44 의 R-3 규율이 유지된다.
- `TriggerCollector._judge` — `relation_result is FALSE` 를 **정의 미등록
  분기보다 앞에서** 처리한다 (6-F 가 고친 순서). `OTHER` 의 확정 거부가 그
  경로를 그대로 탄다.

---

## 6. 새로 지원하는 사건 주체 관계

**하나다.** 「사건 그룹에 이 카드가 들어 있으면 조건이 거짓이다」
(= 공식 원문의 「이 카드 **이외의** …」).

| 선언 | 사건의 주체 | 답 | 코드 |
|---|---|---|---|
| `OTHER` | **이 카드** | `INVALID` | `CANDIDATE_NOT_ELIGIBLE` (확정 거부) |
| `OTHER` | 다른 카드 | `UNKNOWN` | `RULE_NOT_IMPLEMENTED` + `GROUP_MEMBERSHIP_RULE` |
| `OTHER` | 없음 (라이프 · 페이즈) | `UNKNOWN` | `INFORMATION_UNAVAILABLE` |

🔴 **이 축은 통과시키지 못한다.** `not eg:IsContains(handler)` 가 묻는 것은
"그룹에 이 카드가 들어 있는가" 인데, 엔진의 사건은 주체 **한 장**만 들고
있다. 주체가 이 카드면 그룹에 들어 있는 것이 확정되니 거짓이 확정되지만,
주체가 다른 카드일 때 "이 카드도 그 사건에 함께 포함되었는가" 는 물을 데가
없다. 거기서 `VALID` 를 내면 그것이 §16-6 이 금지한 거짓 승격이다.

`test_15` 가 그 비대칭을 **격자 전체**(사건 3 × 후보 2 = 6칸)로 고정하고,
값까지 적어 둔다 — "`VALID` 가 없다" 만 보면 모든 칸이 `UNKNOWN` 으로
뭉개져도 통과하기 때문이다.

---

## 7. 미지원 관계 및 UNKNOWN 유지 범위

| 범주 | 수 | 왜 |
|---|---|---|
| `FIELD` 등록 중 조건 본문을 못 읽는다 | 89 | `SetCondition` 없음 73 · 다른 파일 함수 15 · 본문 못 찾음 1 |
| 본문은 읽었으나 주체 관계를 말하지 않는다 | 611 | `eg:IsExists` 등 — 다른 질문이다 |
| 호출은 있으나 **주장하지 않는다** | 4 | 긍정 자리 + `#eg==N` (§8) |
| **`FIELD` 중 여전히 주체 미확정** | **704** | 위 셋의 합 |

§6 이 열거한 다른 관계 — 사건 카드의 **유형** · **카드군** · **컨트롤러** ·
"하나라도 만족하는가" — 는 **구현하지 않았다.** §6 이 "모두를 구현해야 하는
것은 아니다. 실제 데이터에서 구조적으로 안전하게 표현 가능한 최소
부분집합만 구현한다" 고 적은 그대로다. 그 관계들은 `eg:IsExists(필터,…)` 의
**필터 함수**에 들어 있고, 필터를 읽는 것은 조건 함수 본문을 한 단계 더
들어가는 일이라 이번 범위 밖이다.

---

## 8. 단일·복수 카드 사건 처리 결과

§7 의 여섯 경우를 측정 결과에 대응시킨다.

| 경우 | 이번 단계의 처리 |
|---|---|
| 1. 사건 카드가 한 장 | 엔진의 기본형. `TimingEvent.instance` 가 그 한 장이다 |
| 2. 그룹에 여러 카드 | **엔진이 표현하지 못한다.** 사건 모델을 재설계하지 않았다 |
| 3. 소유자가 그룹에 포함 | 주체 == 소유자인 경우만 확정 — `OTHER` 가 **거부**한다 |
| 4. 소유자가 그룹에 **불포함** | 확인할 수 없다 → `GROUP_MEMBERSHIP_RULE` 로 `UNKNOWN` 보류 |
| 5. 일부만 조건 만족 | 표현할 수 없다 → `UNKNOWN` |
| 6. 그룹 정보 자체가 없다 | `INFORMATION_UNAVAILABLE` — 단일 카드 사건으로 **취급하지 않는다** |

긍정 자리 4건이 이 문제의 얼굴이다.

| 카드 | Lua | 뜻 | 처리 |
|---|---|---|---|
| 요위 (33393090) e[0] · e[2] | `#eg==1 and eg:IsContains(handler)` | 「이 카드 1장만이」 | 보류 |
| 극성령 알비스 (27024795) e[0] | `#eg==1 and …` | 「이 카드만이 제외되었을 경우」 | 보류 |
| 토템 파이브 (56346071) e[0] | `#eg==5 and …` | 「**이 카드를 포함하는 5장**의 몬스터가 동시에」 | 보류 |

요위 · 알비스는 "주체 = 이 카드" 와 **같은 뜻**이지만, 그 뜻을 쓰려면
`#eg==1` 을 참으로 확인해야 하고 엔진은 그룹 크기를 들고 있지 않다. 토템
파이브는 복수 카드 사건 자체다. 셋 다 `UNKNOWN` 으로 둔 것이 §7 의
"안전하게 표현할 수 없다면 해당 범주는 UNKNOWN 으로 보류한다" 다.

이 한계는 **STRUCTURAL-35** (복수 카드 사건) 의 이 축에서의 얼굴이고,
`test_20` 이 "사건이 주체 한 장만 들고 있다" 를 구조 핀으로 잠근다 —
나중에 사건이 그룹을 들게 되면 그 테스트가 먼저 깨지고, 그때 `OTHER` 의
모름이 답으로 바뀔 수 있다. 그 전에는 바꿀 근거가 없다.

---

## 9. 기르수 및 FIELD 대표 사례 결과

### 9.1 잭나이츠 오르페골 기르수 (69811710) — **이번 범위가 아니다**

§9 가 "기르수가 이번 단계의 FIELD 분석 범위에 해당하지 않는다면 억지로
포함시키지 않는다" 고 했고, 측정 결과가 그 경우다.

| 블록 | 등록 | 조건 함수 | 컴파일 결과 |
|---|---|---|---|
| e[0] | `SINGLE`+`TRIGGER_O` `EVENT_SUMMON_SUCCESS`, `SetRange` **없음** | 없음 | `subject=SELF` `point=monster_summoned` `activates_from=None` |
| e[1] | `SINGLE`+`TRIGGER_O` `EVENT_SPSUMMON_SUCCESS`, `SetRange` 없음 | 없음 | 같음 |
| e[2] | `IGNITION` (트리거 아님) | 인라인 있음 | 등록 아님 |

- **주체는 6-F 가 이미 답했다** (`SINGLE` → `SELF`). `FIELD` 가 아니므로
  이번 단계가 기르수에 더한 것은 **없다.**
- 조건 함수가 있는 블록은 e[2] 하나뿐이고 그것은 기동 효과다.

### 9.2 기르수의 UNKNOWN 이 나오는 **정확한** 자리 (실측)

자기 자신의 특수 소환 사건에서 다섯 관문:

| 관문 | 결과 | 이유 |
|---|---|---|
| `event_relation` | **VALID / OK** | 「사건의 주체가 이 카드입니다 (#40)」 |
| `activation_zone` | UNKNOWN / `RULE_NOT_IMPLEMENTED` | 「발동할 수 있는 자리가 선언되지 않았습니다」 |
| `trigger_condition` | UNKNOWN / `RULE_NOT_IMPLEMENTED` | 「e[1] 의 정의가 없어」 |
| `execution_authority` | UNKNOWN / `RULE_NOT_IMPLEMENTED` | 같음 |
| `cost_feasibility` | UNKNOWN / `RULE_NOT_IMPLEMENTED` | 같음 |

미검사 규칙 6개: timing window · WHEN/IF 처리 · spell speed · activation
limit · SEGOC · chain 삽입.

**실제 엔진 실행을 위해 부족한 선행 기능** (§9-8):

1. e[0]/e[1] 의 `EffectDefinition` — `EFFECT_LIBRARY` 에 없다.
2. `SetRange` 가 없는 등록의 발동 위치를 **규칙으로** 정하는 계층. 공식
   원문 「이 카드가 특수 소환에 성공했을 경우」 는 자리를 말하지 않는다 —
   몬스터 존이 규칙상 당연한 것이라 Lua 도 적지 않는다. 6-G 가 "적지 않은
   것을 '어디서든' 으로 읽지 않는다" 를 지켰으므로 여기는 `UNKNOWN` 이다.
3. 링크 소환 절차 (엔진에 없다).

**기르수의 자동 효과 발동은 구현하지 않았다** (§9 의 금지).

### 9.3 FIELD 대표 사례 — 기르수를 쓰지 않았다

`test_02` 알렉산더(987311) · `test_03` 토폴로직 폭탄 드래곤(5821478) ·
`test_04` 요위(33393090). 전부 **공식 원문이 그 관계를 말하는** 서로 다른
카드이고, 측정으로 골랐다 (production 코드에 카드 ID 분기는 없다 — §6 금지
준수).

---

## 10. 실제 실행으로 이어질 최소 시나리오 선정 결과

### 10.1 먼저 막힌 길들 (측정)

| 후보 | 왜 막혔는가 |
|---|---|
| 두 관문(주체 `SELF` + 위치) 통과 등록 **31건** · 카드 26장 | 그중 `EFFECT_LIBRARY` 에 실행 구현이 있는 것 **0건** |
| `EFFECT_LIBRARY` 16건 | **16건 전부 마법의 `ACTIVATE` 효과** — `compile_trigger_spec` 이 전부 `None` (트리거가 아니다) |
| 31건 중 엔진이 일반 소환을 판정할 수 있는 카드 10건 | `legal_actions` 가 소환 행동을 **0건** 제시한다 (어드밴스 소환 절차가 없다 — 가능한 행동이 `end_phase` 뿐) |
| 드로우 페이즈의 드로우 | `Duel.advance` 가 `state.draw` 를 직접 부르고 **`CardDrawn` delta 를 내지 않는다** → 사건이 생기지 않는다 |

### 10.2 그런데 **길이 하나 있었다**

`EffectExecutor` 는 **드로우 효과를 실행할 때** 뽑힌 장마다 `CardDrawn` 을
낸다. 그리고 `EFFECT_LIBRARY` 의 욕망의 항아리(55144522)는
`executable=True` 다.

**수호신관 마하드 (71703785)** — 공식 원문 「①: **이 카드를 드로우했을 때**,
이 카드를 상대에게 보여주고 발동할 수 있다」. 등록이
`SINGLE`(→`SELF`) · `EVENT_DRAW`(→`card_drawn`) · `SetRange(HAND)`
(→ 발동 위치 `HAND`) 라서 **두 축이 동시에 답을 갖는다.**

§10 의 선정 기준 8개 대조:

| 기준 | 결과 |
|---|---|
| 1. Lua 등록 정보 존재 | ✅ e[0] `EVENT_DRAW` |
| 2. 사건 종류 지원 | ✅ `card_drawn` |
| 3. 주체 관계 확인 가능 | ✅ `SELF` |
| 4. 발동 위치 확인 가능 | ✅ `HAND` |
| 5. 필요한 행동 실행 가능 | ✅ 욕망의 항아리 발동 · 해결 |
| 6. `EffectDefinition`/실행 구현 존재 | ✅ (사건을 만드는 쪽) |
| 7. 추가 규칙 적음 | ✅ 체인 1개, 대상 없음 |
| 8. 카드 전용 하드코딩 불필요 | ✅ |

### 10.3 실제로 끝까지 갔다 (`test_22`, 지어낸 delta 0개)

```
GameState (덱 맨 위 = 마하드 ×10, 마법 존 = 욕망의 항아리)
    ↓  EffectActivator → Chain → ChainResolver → EffectExecutor   ← 실제 실행
CardDrawn(card=#0) · CardDrawn(card=#1)                            ← 실제 delta
    ↓  EventReader → TriggerCollector
TriggerCandidate(71703785:e[0], source=#0)
    ↓  TriggerEligibilityJudge
```

| 관문 | #0 의 드로우에서 #0 | #0 의 드로우에서 #1 |
|---|---|---|
| `event_relation` | **VALID / OK** ← 6-F | **INVALID** (다른 사본) |
| `activation_zone` | **VALID / OK** ← 6-G | VALID |
| `trigger_condition` | UNKNOWN | UNKNOWN |
| `execution_authority` | UNKNOWN | UNKNOWN |
| `cost_feasibility` | UNKNOWN | UNKNOWN |
| **전체** | **UNKNOWN** (승격 아님) | **INELIGIBLE** |

**6-F 의 주체 축과 6-G 의 위치 축이 실제 엔진 사건에서 동시에 통과한
첫 사례다.** 그리고 같은 카드 ID 의 다른 사본이 **확정 거부**되는 것까지
실제 사건에서 확인된다 — 6-F 가 세운 인스턴스 구분이 산다.

### 10.4 다음 단계에 필요한 기능 (§10 의 마지막 항목)

남은 세 관문이 **같은 한 가지**를 가리킨다 — `EffectRef(71703785, 0)` 의
`EffectDefinition` 이 없다. 그것이 생기면 `trigger_condition` ·
`execution_authority` · `cost_feasibility` 가 동시에 답을 갖는다. 그 다음이
미검사 규칙 6개(타이밍 창 · WHEN/IF · spell speed · 턴 1회 · SEGOC · 체인
삽입)다.

**효과 자동 발동과 해결은 구현하지 않았다** (§10 의 금지).

---

## 11. 구현 전후 정확성 지표

§11 의 12개 항목. 측정할 수 없는 값은 비워 두지 않고 **왜 측정할 수 없는지**
적었다.

| # | 항목 | 전 | 후 |
|---|---|---|---|
| 1 | FIELD 등록 전체 | 784 | 784 |
| 2 | 조건 함수 본문을 읽을 수 있는 FIELD 등록 | 695 | 695 |
| 3 | 사건 주체 관계를 식별할 수 있는 등록 | 3,389 (`SELF`) | **3,469** (`SELF` 3,389 + `OTHER` 80) |
| 4 | 확실하게 **거짓**으로 판단할 수 있는 사례 | `SELF` 의 "주체 다름" 뿐 | **+ `OTHER` 의 "주체가 이 카드" 80건** |
| 5 | 확실하게 **참**으로 판단할 수 있는 조건 | `SELF` 의 "주체 같음" | **변화 없음** (`OTHER` 는 통과시키지 못한다) |
| 6 | UNKNOWN 으로 보존한 등록 | 784 | **704** |
| 7 | 미지원 Lua 조건 구조 | — | 89 (본문 못 읽음) + 4 (긍정 자리) |
| 8 | 복수 카드 사건 관련 등록 | — | 84 (`OTHER` 80 의 모름 방향 + 긍정 4) |
| 9 | 잘못된 ELIGIBLE 승격 | 0 | **0** (`test_15` 격자 · `test_19` 실제 판 전수) |
| 10 | 6-F 사건 주체 회귀 | 19 passed | **19 passed** (핀 1개 갱신 — §14) |
| 11 | 6-G 발동 위치 회귀 | 18 passed | **18 passed** · 영역 선언 **816 불변** |
| 12 | 실제 실행 경로까지 연결 가능한 대표 사례 | 0 (측정) | **1** (마하드 — §10) |

**조건 AST 컴파일 성공이 발동 가능이나 실행 성공을 뜻하지 않는다.** §10 의
표가 그것을 그대로 보여준다 — 두 관문이 통과해도 전체는 `UNKNOWN` 이다.

전수 조사와 표본 검증의 구분: §1 · §11 의 수는 전부 **전수**(카드 전체)이고,
§1.5 의 원문 대조는 **표본**이다.

---

## 12. Phase 6-F 및 6-G 회귀 테스트 결과

| 파일 | 결과 |
|---|---|
| `tests/engine/test_trigger_event_subject.py` (6-F) | 19 passed |
| `tests/engine/test_trigger_activation_location.py` (6-G) | 18 passed |
| `tests/engine/test_trigger_compiler.py` (6-E) | 46 passed · 센서스 `zones == 816` 유지 |

6-F 의 `fold` 와 후보 상태 처리는 **고치지 않았고**, `OTHER` 가 그 경로를
그대로 탄다 (§5.2). `test_17`·`test_18`·`test_19` 가 수집기와 판정기의 답이
어긋나지 않는 것을 실제 판에서 확인한다.

---

## 13. EventJournal 과 Engine V1 호환성

- `PlayerAction` 계약 · `Duel` · `GameState` · `EventJournal` 을 **하나도
  고치지 않았다.** `git diff` 가 그 파일들을 담고 있지 않다.
- `test_22` 는 실제 `EffectActivator` → `Chain` → `ChainResolver` →
  `EffectExecutor` → `EventReader` 를 지난다. 그 경로의 결과가 바뀌지
  않았으므로 호환성은 "주장" 이 아니라 **그 테스트가 지나간 사실**이다.
- `TriggerSpec.to_dict()` 는 `subject` 를 값(`"other"`)으로 싣는다 —
  6-F 가 만든 직렬화 자리를 그대로 쓰고 새 칸을 만들지 않았다.

---

## 14. 타깃·통합·최종 회귀 테스트 결과

### 14.1 명령과 수

| 단계 | 명령 | 결과 |
|---|---|---|
| 1단계 타깃 | `pytest tests/engine/test_trigger_event_subject_condition.py -q -p no:randomly` | **22 passed** · 26.0s |
| 2단계 통합 | `pytest tests/engine -q -p no:randomly` | (§14.4) |
| 3단계 회귀 | `pytest <tests/*.py 4분할> -q -p no:randomly` | (§14.4) |

### 14.2 기존 테스트를 고친 자리 — **하나**

`tests/engine/test_trigger_event_subject.py::test_01_the_axis_has_three_states_not_two`
의 `assert [m.value for m in TriggerSubject] == ["self", "any"]` 를
`["self", "other", "any"]` 로 고쳤다.

**왜 기존 테스트가 틀린 전제를 갖고 있었는가** — 틀린 전제가 아니었다.
6-F 시점에 축의 값은 **실제로 둘**이었고 그 테스트는 사실을 적고 있었다.
6-H 가 값을 하나 늘렸으므로 그 목록이 더 이상 사실이 아니게 된 것이다.
고친 것은 **목록 한 줄뿐**이고, 그 테스트가 지키는 단정("`None` 은 `ANY` 가
아니다", `SELF` 의 세 답) 은 **하나도 약화하지 않았다.** 삭제 · skip 추가 ·
assertion 약화 · threshold 완화 없음.

### 14.3 변이 테스트 — 내 코드를 10가지로 틀리게 만들었다

| 변이 | 잡은 테스트 |
|---|---|
| M1 `or` 보호를 뺀다 | `test_05` |
| M2 중복 보호를 뺀다 (`!= 1` → `< 1`) | `test_06` |
| M3 패턴을 `eg:IsContains` 로 느슨하게 | `test_03` |
| M3b 그룹 변수명을 `\w+` 로 넓힌다 | `test_07` |
| M4 긍정 자리도 주장한다 | `test_04` |
| M5 주체가 다르면 통과시킨다 | `test_14` |
| M6 주체가 이 카드여도 통과시킨다 | `test_13` |
| M7 두 모름에 같은 이름을 쓴다 | `test_14` |
| M8 조건이 선언을 덮는다 | `test_10` |
| M9 아무 주장이나 받는다 | `test_11` |

🔴 **첫 실행에서 둘이 살아남았고, 그것이 내 테스트와 내 코드를 각각
고치게 했다.**

- **M2 가 살아남은 것은 내 테스트가 약했다.** `test_06` 의 입력이 앞의
  호출을 `if … then return true` 로 두어서, 중복 보호를 지워도 **다른
  보호가 막고 있었다.** 입력을 "앞의 것만 보면 `not` 이 붙어 있어
  `NOT_HANDLER` 로 읽히지만 실제 뜻은 반대" 인 모양으로 바꿨다.
- **M3(원래 형태) 가 살아남은 것은 내 코드에 죽은 줄이 있었다.** 함수
  선언부를 떼는 전처리를 탐사 스크립트에서 그대로 옮겨 왔는데, 이름이 전부
  붙은 패턴은 **선언부에 나타날 수 없으므로** 그 전처리가 아무 일도 하지
  않았다. 전처리를 **지웠고**(전수 측정이 80/64/0/54 그대로임을 확인), 그
  자리를 지키는 일은 `test_07` 의 **패턴 정적 핀**으로 옮겼다.

변이를 적용한 상태로 다른 테스트를 돌리지 않았다 (6-G 에서 저지른 실수 —
"섞인 실행은 아무것도 증명하지 않는다"). 매 변이마다 적용 → 해당 파일만
실행 → 복원이고, 마지막에 `git status` 로 복원을 확인했다.

### 14.4 최종 회귀

🔴 **첫 회귀 실행에서 실패 6건이 나왔고, 그중 하나는 테스트도 코드도 아니라
내 실행 명령이 원인이었다.**

| 실패 | 원인 | 처리 |
|---|---|---|
| `test_discord_bot.py::test_08_the_token_value_never_reaches_the_log` | **내가 붙인 `python3 -I` 플래그.** 격리 모드는 user site-packages 를 `sys.path` 에서 빼고, `discord.py` 의 의존성 `idna` 가 거기에 있다 (`/root/.local/lib/python3.11/site-packages`). `bot.main()` 이 import 실패로 2 를 돌려줬다 | **고치지 않았다.** 같은 테스트를 `-I` 없이 돌려 **61 passed** 를 확인하고, 최종 회귀를 `-I` 없이 다시 돌렸다 |
| `test_rule_not_implemented_code_audit::test_02` | 문자열 센서스 82 → 84 | 핀 갱신 (§14.5) |
| `test_unimplemented_rule_semantics_audit::test_03` | 같은 센서스 | 핀 갱신 |
| `test_validation_code_rejection_semantics_audit::test_03` · `test_31` | 거부 생성 56 → 57 · 코드 자리 69 → 70 | 핀 갱신 |
| `test_trigger_pipeline_dormant_audit::test_01` · `test_25` | `engine/trigger.py` 줄 수 1999 → 2059 · 실행 줄 806 → 813 · 합 3036 → 3096 | 핀 갱신 |

**`-I` 에 대해**: 그 플래그는 "내려받은 믿을 수 없는 파일을 다루는 스크립트"
를 위한 것이고, 이 저장소 자신의 테스트 묶음에는 해당되지 않는다. 플래그가
만든 실패를 "코드 문제" 로 보고했다면 거짓 보고였다. 명령을 고쳤다.

### 14.5 센서스 핀 다섯 — 무엇이 왜 움직였는가

내 변경이 `engine/trigger.py` 에 `RULE_NOT_IMPLEMENTED` 를 **둘** 더했다.

| 자리 | 종류 | 무엇 |
|---|---|---|
| `engine/trigger.py:829` | **코드** | `OTHER` 인데 주체가 다른 카드 → `GROUP_MEMBERSHIP_RULE` |
| `engine/trigger.py:743` | **산문** | 그 상수 위의 주석 (왜 이 코드인가) |

| 핀 | 전 | 후 |
|---|---|---|
| `STRING_OCCURRENCES` | 82 | **84** |
| `CODE_OCCURRENCES` | 69 | **70** |
| `PROSE_OCCURRENCES` | 13 | **14** (새 자리 743 · 네 자리가 +60 밀림) |
| `RULE_NOT_IMPLEMENTED_MENTIONS` | 82 | **84** |
| `REJECTION_PRODUCTIONS` | 56 | **57** |
| `engine/trigger.py` 줄 수 | 1,999 | **2,059** |
| 같은 파일, 문자열 벗긴 줄 수 | 806 | **813** |
| 세 모듈 줄 수 합 | 3,036 | **3,096** |

**assertion 을 약화하거나 threshold 를 완화한 것이 하나도 없다.** 전부
"지금 몇 개인가" 를 세는 핀이고, 센 값이 달라졌으므로 값을 갱신하면서 **왜
달라졌는지를 주석으로 남겼다** (그 핀들이 요구하는 형식). `strings - code
== prose == 14` 같은 **관계식**은 그대로 성립한다 — 관계가 깨지지 않은 것이
변경이 축 하나에만 닿았다는 증거다.

🔴 `test_25_this_phase_changed_no_production_file` 의 "문자열 벗긴 줄 수"
핀이 **주석이 아니라 실행 코드 7줄이 늘었다는 사실을 정확히 잡았다.**
그 핀을 둔 이유가 그것이고, 숫자만 갱신하지 않고 **늘어난 7줄이 dormant 를
깨지 않는 이유**(거부 하나 · 모름 하나를 더할 뿐 통과를 내는 자리는 늘지
않았다)를 같은 자리에 적었다.

### 14.6 최종 회귀 — 측정값

명령: `python3 -m pytest <대상> -q -p no:randomly --no-header --tb=line`
(`-I` **없이**)

| 대상 | 통과 | 건너뜀 | 실패 | 시간 |
|---|---|---|---|---|
| `tests/*.py` chunk0 (25파일) | 678 | 0 | 0 | 19:43 |
| `tests/*.py` chunk1 (22파일) | 557 | 0 | 0 | 10:49 |
| `tests/*.py` chunk2 (23파일) | 576 | 0 | 0 | 11:43 |
| `tests/*.py` chunk3 (22파일) | 466 | 0 | 0 | 06:31 |
| `tests/engine` | 3,035 | 0 | 0 | 04:21 |
| `tests/agent` + `tests/rules` + `tests/rulings` | 529 | 4 | 0 | 03:32 |
| **합계** | **5,841** | **4** | **0** | 56:39 |

4분할은 `split -n l/4` 로 나누고 `diff` 로 **빠짐·중복 없음**을 확인했다
(92파일 = 25+22+23+22).

6-G 가 보고한 5,819 passed · 4 skipped 와 비교하면 **+22** 이고, 그것이
이번에 더한 테스트 수와 **정확히 같다.** 기존 테스트를 하나도 잃지 않았다는
뜻이다.

---

## 15. 남아 있는 구조적 차단 문제

| # | 문제 | 지금의 모습 | 왜 이번 단계에서 풀지 않았는가 |
|---|---|---|---|
| 1 | **복수 카드 사건** (STRUCTURAL-35) | `TimingEvent` 가 주체 한 장만 들고 있다 | 사건 모델 전면 재설계가 필요하다 (§13 금지). `OTHER` 의 모름과 긍정 4건이 그 얼굴이고, `test_20` 이 구조 핀을 둔다 |
| 2 | **`compile_trigger_spec` 의 production 호출자가 0곳이다** | 컴파일러와 `EventPipeline` 모두 테스트에서만 닿는다 (`TriggerRegistry` 를 만드는 production 자리도 0곳) | 수직 통합의 **가장 큰 한 칸**이고 설계가 먼저다 (§16) |
| 3 | **TRIGGER 의 `EffectDefinition` 이 0건** | `EFFECT_LIBRARY` 16건 전부 마법의 `ACTIVATE` | ADR-006 이 손 등록을 요구하고, §13 이 "신규 카드 효과 대량 구현" 을 금지한다 |
| 4 | **`SetRange` 없는 등록의 발동 위치** | `activates_from=None` → 자리 관문 `UNKNOWN` (기르수가 그 예) | 규칙으로 메워야 한다 ("몬스터 효과는 몬스터 존에서") — 규칙 계층의 일이고 데이터로 읽을 수 없다 |
| 5 | **어드밴스 · 특수 소환 절차** | `assess_normal_summon` 이 `NEEDS_TRIBUTE` 를 돌려주는데 `legal_actions` 가 소환 행동을 **0건** 제시한다 | §13 이 "특수 소환 절차 추가" 를 금지한다 |
| 6 | **드로우 페이즈의 드로우가 사건을 만들지 않는다** | `Duel.advance` 가 `state.draw` 를 직접 부르고 `CardDrawn` delta 를 내지 않는다 | 사건 생성 경로 변경이 필요하고, §10 의 시나리오는 **효과 드로우**로 우회할 수 있었다 |
| 7 | **조건 본문의 필터 함수** | `eg:IsExists(필터,…)` 의 필터를 읽지 않는다 (379건) | §6 의 "최소 부분집합" 범위 밖. 유형 · 카드군 · 컨트롤러 관계가 전부 거기 있다 |
| 8 | **미검사 규칙 6개** | 타이밍 창 · WHEN/IF · spell speed · 턴 1회 · SEGOC · 체인 삽입 | `UNCHECKED_RULES` 가 이미 그 목록을 들고 있다 — 숨기지 않았다 |

---

## 16. 다음 단계의 최소 실행 통합 선행 조건

§10 이 찾아낸 경로가 다음 단계를 가리킨다. **순서가 있다.**

1. **`EffectRef(71703785, 0)` (마하드 ①) 의 `EffectDefinition` 을 손으로
   등록한다** (ADR-006 · ADR-004 의 출처 검증을 지나서). 그것 하나로 남은
   세 관문(`trigger_condition` · `execution_authority` ·
   `cost_feasibility`) 이 동시에 답을 갖는다. 효과 내용은 「이 카드를 패에서
   특수 소환한다」 — 특수 소환 절차가 §13 금지에 걸리므로 **발동 가능성
   판정까지**가 다음 단계의 경계다.
2. **`TriggerRegistry` 를 카드 데이터에서 만드는 production 자리를 하나
   만든다.** 지금 0곳이고 (`test_13`), 그것이 없으면 컴파일러가 아무리
   정확해도 실제 듀얼에 닿지 않는다. 입력은 이미 전부 있다 —
   `compile_trigger_spec` 에 넘길 네 값이 `EffectAnalysis` 에 있다.
3. **`Duel` 이 사건을 트리거 계층에 넘기는 자리.** `EventPipeline` 은 있고
   production 호출자가 없다. 2 와 3 이 **수직 통합의 본체**다.
4. 그 다음이 **타이밍 창** 이다 — 「~했을 때」(WHEN) 와 「~했을 경우」(IF) 의
   구분, 놓친 타이밍. `UNCHECKED_RULES` 의 첫 두 항목이고, 이것 없이는
   "발동 가능" 을 말할 수 없다.

🔴 **1 → 2 → 3 의 순서를 바꾸면 안 된다.** 2 와 3 을 먼저 하면 정의가 없는
4,173건이 전부 `UNKNOWN` 후보로 실제 듀얼에 들어오고, 그 모름을 어디서
막을지가 다시 문제가 된다. 정의가 하나라도 있는 상태에서 연결하면 **그
하나로 경로 전체를 검증**할 수 있다 — `test_22` 가 이미 그 형태다.

---

## 17. Git 커밋 및 푸시 결과

브랜치: `claude/pensive-goodall-te1egy` (기존 커밋 rewrite · amend · force
push 없음 · 새 브랜치 없음 · PR 없음)

| 커밋 | 내용 |
|---|---|
| `778d9dd` | 조건 함수가 적어 둔 "이 카드 이외" 를 읽는다 (production 4파일) |
| `ed1409c` | 테스트 22개 신규 + 움직인 핀 여섯 |
| (이 보고서) | `docs/phase6h-field-trigger-condition-integration.md` |

푸시: `f47e6c5..ed1409c` → `origin/claude/pensive-goodall-te1egy` (성공),
그리고 이 보고서 커밋.

---

## 부록 — 이번 단계에서 하지 않은 것 (§13 대조)

Engine V1 재설계 · `PlayerAction` 계약 변경 · 새 Lua 인터프리터 · 신규 카드
효과 대량 구현 · 모든 `FIELD` 등록 지원 (80/784) · 모든 트리거 자동 발동 ·
체인·타이밍 재설계 · 특수 소환 절차 · Discord 명령어 · 콤보 플래너 연결 ·
금지·제한 리스트 · Duel Simulator · EDOPro · AI 전략 추론 · 기존 Lua 파일
이동·삭제 · 카드 데이터 재생성 · 관련 없는 구조적 TODO 수정 — **하나도 하지
않았다.**

카드 ID · 카드명 하드코딩: production 코드에 **없다.** 테스트의 대표 사례
상수는 측정으로 고른 것이고, 그 카드들의 Lua 내용을 분기로 옮겨 적은 자리는
없다 (§6 금지 준수).

**다음 Phase 는 자동으로 시작하지 않는다.** 사용자 검토를 기다린다.
