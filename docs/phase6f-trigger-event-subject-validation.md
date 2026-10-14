# Phase 6-F — 갈라테아 TRIGGER 사건 주체 식별 및 발동 조건 검증 연결

작업 브랜치: `claude/pensive-goodall-te1egy`
선행: 6-A(실행 경로) · 6-B(EventJournal) · 6-C(아키타입 조건) · 6-D(카드군 컴파일러) · 6-E(TRIGGER 컴파일러)

---

## 0. 먼저 — 6-E 의 수치 하나가 범위를 잘못 잡고 있었다

지시서 §2 가 "이전 보고서의 숫자와 구조는 현재 코드에서 재확인한다" 고 했고,
재어 보니 하나가 틀렸다.

`engine/trigger_compiler.py` 의 주석은 이렇게 적고 있었다.

```
SINGLE   "이 카드가" 표기 있음 2,259 · 없음  69   (97.0%)
FIELD                     있음   273 · 없음 288   (48.7%)
```

이것은 **트리거 블록 전부**(8,052) 를 센 값이다. 그런데 주체가 문제가 되는
것은 **옮길 수 있는 사건 코드를 가진 블록**뿐이다 — 나머지 3,693 개는 애초에
선언이 만들어지지 않으므로 주체를 물을 자리가 없다. 그 4,201 개로 다시 세면

| 범위 | 「이 카드」 표기 있음 | 없음 | 비율 |
|---|---|---|---|
| `SINGLE` | **3,402** | **8** | **99.8%** |
| `FIELD` | 710 | 81 | 89.8% |

6-E 는 97.0% 를 보고 "근거가 한쪽뿐" 이라고 판단해 `SINGLE` 도 쓰지 않았다.
그 판단은 **그 수치에 대해서는 옳았다.** 범위를 좁히면 수치가 달라지고,
결론도 달라진다.

---

## 1. 기존 사건 주체와 카드 인스턴스 전달 구조

🔴 **놀랍게도 양쪽에 이미 다 있었다.** 없던 것은 **비교하는 코드**였다.

| 무엇 | 어디 | 값 |
|---|---|---|
| 사건의 주체 | `TimingEvent.instance` | `InstanceId \| None` |
| 트리거를 가진 카드 | `TriggerCandidate.source` | `InstanceId` — *"정의가 아니라 판 위의 그 카드다"* |
| 효과의 신원 | `TriggerSpec.effect_ref` | `EffectRef(card_id, ordinal)` — **정의** 식별자 |

`engine/ids.py` 가 그 구분을 모듈 설명에 적어 두었다 — `InstanceId` 는
"카드 한 장. 같은 카드명 3장을 서로 구분한다", `EffectRef` 는 "효과 하나".
**선언은 정의를 가리키고 후보는 인스턴스를 가리킨다.**

`TimingEvent.instance` 가 세 사건군 전부에서 값을 돌려주는 것을 실측했다.

```
MonsterSummoned  -> instance = #7   | summon = normal
ZoneMoved        -> instance = #9   | to_zone = GRAVE
CardDrawn        -> instance = #3
LifeChanged      -> instance = None
UNIMPLEMENTED    -> instance = None
```

🔴 그래서 **사건 모델에 새 칸을 하나도 더하지 않았다** (지시서 §14 의 요구:
"새로운 모델이나 필드를 추가할 경우 그 필요성과 기존 모델 재사용이
불가능한 이유를 설명한다"). 재사용이 가능했고, 재사용했다.

### 복수 카드가 동시에 움직이는 경우 (§4-A-5)

`EventJournal` 은 행위 하나에 변화 여럿을 싣고, `timing_events()` 가
**변화마다 사건을 하나씩** 만든다 — *"하나도 빠뜨리지 않는다. 옮길 이름이
없는 변화도 자리를 지킨다."* 그래서 주체는 사건마다 **한 장**이고, 묶음을
펼치는 코드를 쓸 필요가 없었다. 6-F 가 그 구조에 얹히기만 한다.

---

## 2. `EVENT_SUBJECT_RULE` 이 `UNKNOWN` 이었던 원인

근본 원인은 "주체 정보가 없어서" 가 **아니다.**

```python
# engine/condition/context.py
class ConditionContext:
    player: int
    source: InstanceId | None = None
    effect_ref: EffectRef | None = None
    targets: tuple[InstanceId, ...] = ()
```

🔴 **`ConditionContext` 에 사건을 담을 칸이 없다.** 조건은
`ConditionEvaluator(view)` 가 **판 위의 사실**을 묻는 것이고 구조적으로
사건을 보지 못한다. 6-E 는 "이 사건이 이 카드의 사건인가" 를
`condition=UnimplementedRule(EVENT_SUBJECT_RULE)` 로 실어 보냈는데, 그것은
**자리를 빌린 것**이었다 — 어떤 조건 술어도 그 질문에 답할 수 없는 자리에
질문을 둔 셈이다.

빌린 이유는 있었다. 조건은 **두 계층이 모두 보는 유일한 칸**이었다.
`TriggerCollector._judge` 와 `TriggerEligibilityJudge._trigger_condition` 이
각각 `spec.condition` 을 평가하므로, 조건에 넣으면 한 번 적고 양쪽을 막을 수
있었다.

---

## 3. 기존 `TriggerEligibilityJudge` 의 실제 평가 범위

관문 다섯 개를 **순서대로 전부** 본다 (하나가 막혀도 나머지를 계속 본다).

| 관문 | 무엇을 보는가 | 6-F 이전 |
|---|---|---|
| `EVENT_RELATION` | `spec.matches(event)` — 시점 · operations · zones · summons | 주체는 **보지 않았다** |
| `ACTIVATION_ZONE` | `spec.activates_from` 에 현재 자리가 드는가 | 미선언이면 `UNKNOWN` |
| `TRIGGER_CONDITION` | `spec.condition` + `definition.activation` | 조건 평가기 재사용 |
| `EXECUTION_AUTHORITY` | 출처 · 등록된 구현 (ADR-004 · ADR-006) | — |
| `COST_FEASIBILITY` | 비용을 **치를 수 있는가** (치르지 않는다) | — |

`UNKNOWN` 과 `INELIGIBLE` 의 구분은 `fold` 가 결정한다 — **금지 → 거부 →
모름 → 통과** 순이고, *"모르는 것을 거짓으로도 참으로도 접지 않는다."*

### 🔴 그리고 여기서 가장 중요한 사실을 찾았다

```python
@classmethod
def fold(cls, candidate, gates):
    if any(verdict.forbids for verdict in gates): ...
    elif any(verdict.validity is ActionValidity.INVALID for verdict in gates): ...
```

**`fold` 는 관문만 보고 `candidate.status` 를 보지 않는다.**

그러므로 수집기에서만 주체를 막으면 **판정기가 다시 `ELIGIBLE` 로
승격시킨다.** 지시서 §16-6 이 금지한 바로 그것이다. 이것이 6-F 가 두 계층을
모두 고쳐야 했던 이유이고, 조사 없이 수집기만 고쳤다면 조용히 틀렸을
자리다.

---

## 4. 채택한 최소 수정 방식과 대안

### 검토한 네 설계

| 설계 | 내용 | 판단 |
|---|---|---|
| A | `ConditionContext` 에 사건을 담는 칸을 더하고 조건 술어로 쓴다 | 🔴 조건 계층(`ActionValidator` · `EffectActivator` 가 함께 쓴다) 의 공개 계약을 넓힌다. 그리고 **계층 구분이 틀린다** — 조건은 판 위의 사실이고 주체는 사건의 성질이다 |
| B | 수집기에서만 막는다 | 🔴 `fold` 가 후보 상태를 보지 않으므로 **판정기가 다시 승격시킨다** (§3) |
| C | 판정기 관문에서만 막는다 | 🔴 수집기의 후보가 `ELIGIBLE` 로 남는다. 지시서 §16-3 은 **후보** 차단을 요구한다 |
| **D ✅** | **선언에 축을 두고, 두 계층이 같은 함수를 부른다** | `summons`(6-E) 와 같은 모양. 조건 계층을 건드리지 않는다 |

### 채택한 것

```python
class TriggerSubject(str, Enum):
    SELF = "self"   # 사건의 주체가 이 카드 인스턴스여야 한다
    ANY  = "any"    # 어느 카드의 사건이든 — 등록한 쪽이 단정한다
# None            = 적지 않았다 → UNKNOWN

def subject_relation(spec, event, source) -> ValidationResult: ...
```

🔴 **값이 둘인데 상태는 셋이다.** `None` 을 `ANY` 로 읽지 않는 것이 이 축의
핵심이고, 그것이 6-E 가 재현해서 잡은 거짓 양성(기르수가 페더맨의 소환에
후보가 되었다) 을 막는다. 이 저장소가 `activates_from` 에서 이미 내린
결론과 같다 — *"적지 않은 것을 '어디서든 발동 가능' 으로 읽지 않는다."*

반면 `summons` · `operations` · `from_zones` 는 `None` 을 "전부" 로 읽는다.
그 셋은 **사건의 모양**을 거르는 필터이고 거르지 않는 것이 뜻이 되지만,
주체는 **관계**이므로 "모르는 관계" 와 "제약 없는 관계" 가 다른 사실이다.

### 🔴 새 모델을 하나도 만들지 않았다

`subject_relation` 이 돌려주는 것은 **기존 `ValidationResult`** 다.
`validity` · `code` · `reason` · `missing_rule` · `notes` 가 필요한 그대로
있었고, 관문이 받는 타입도 그것이다. 세 갈래를 담을 새 dataclass 를 만들려다
멈추고 기존 어휘를 썼다.

### 3-F-8 의 설계 C 를 그대로 따랐다

`_event_relation` 은 `(spec, event)` 였다. 3-F-8 §5 가 세 설계를 비교해
**"필요한 최소"(설계 C)** 를 권하면서 그 최소를 `controller` 라고 적었는데,
그때는 주체 질문이 올라와 있지 않았다. 주체를 맞춰 보려면 필요한 것은
`source`(인스턴스) 하나이므로 `(spec, event, source)` 가 되었다 — **후보
전체를 넘기지 않았다.**

---

## 5. 변경 파일 및 함수

| 파일 | 변경 | 줄 |
|---|---|---|
| `engine/trigger.py` | `TriggerSubject` · `SUBJECT_AWARE_POINTS` · `TriggerSpec.subject` · `subject_relation` · `_CONDITION_OF_VALIDITY` · `TriggerCollector._from_relation` · `_judge` · `_event_relation` | +260 / −15 |
| `engine/trigger_compiler.py` | `SELF_SCOPE_DECLARATION` · `ANY_SCOPE_DECLARATION` · `SINGLE→SELF` 컴파일 · 조건 자리 반환 | +54 / −12 |
| `tests/engine/test_trigger_event_subject.py` | **신규** 19개 | +893 |
| `tests/engine/test_trigger_compiler.py` | 6-E 의 두 시험을 **강해진 사실**로 (§12) | +54 / −20 |
| `tests/engine/test_trigger.py` | 숨은 전제 4자리 | +33 / −3 |
| `tests/engine/test_timing_priority.py` · `test_trigger_chain.py` · `test_trigger_eligibility.py` · `test_trigger_order.py` · `test_chain_response.py` | 숨은 전제 (공유 빌더 3 + 개별 4) | +39 / −1 |
| `tests/` 최상위 **19개 감사 파일** | 밖에서 난 핀 (§12) | +497 / −93 |

`data/` · `c*.lua` · `analysis/` · `core/` · `engine/duel.py` ·
`engine/effect/journal.py` · `engine/condition/` · `agent/` · `app/` ·
`rules/` · `rulings/` · `sources/` 는 **한 줄도** 바뀌지 않았다.

### 🔴 `UnimplementedRule` import 가 사라졌다

컴파일러가 더 이상 조건을 만들지 않으므로 그 import 를 지웠다. **모름이
사라진 것이 아니라 제자리로 갔다** — `subject_relation` 이 같은
`missing_rule` 문자열(`EVENT_SUBJECT_RULE`) 을 그대로 쓴다. 같은 사실에
이름을 둘 붙이면 로드맵 추적이 갈라지므로 6-E 가 지은 이름을 재사용했다.

---

## 6. 사건 주체 판정 로직의 지원 범위

### 무엇을 근거로 `SELF` 를 적는가 — 근거 두 줄

**근거 1 · 공식 원문** (권위 있는 원천). §0 의 표가 그것이고, 🔴 **`SINGLE`
에서 표기가 없는 8건을 한 장씩 읽었다 — 진짜 반례는 0건이다.**

| 카드 | 표기가 없는 이유 | 실제 주체 |
|---|---|---|
| Shuttleroid 10449150 · Cockroach Knight 33413638 · Hourglass of Courage 43530283 · Big Inflate Dragon 91337277 | 한국어 원문이 없어 영문만 있다 → 「이 카드」 **문자열**이 없을 뿐 | "**this card**" = 자신 |
| 다크 제로이드 90980792 | 「**이 몬스터가** 일반 소환…」 — 다른 낱말 | 자신 |
| 심판자－볼테니스 20951752 | 「**이 방법으로** 특수 소환에 성공했을 경우」 | 자신 |
| 질풍조인 죠 81896370 | 주체 생략 | 자신 |

귀속이 1:1 로 보장되는 표본(효과 블록이 **하나**뿐인 카드 285장) 으로 다시
재도 반례는 0건이었다. 🔴 그 과정에서 **내 분류기가 한 번 틀렸다**:
「이 카드 이외」를 주체 불일치로 셌는데 전부 **비용·대상**을 가리키는
말이었다 (베어루크티 「패에서 **이 카드 이외의** 레벨 7 이상 몬스터를
릴리스하고 … **이 카드를** 특수 소환한다」). 13건이 반례로 보였고 전부
자신이었다.

**근거 2 · Lua 구조** (텍스트와 **독립**). `FIELD` 트리거는 사건 묶음 `eg`
에서 "어느 카드의 사건인가" 를 스크립트가 직접 골라야 한다.

| 범위 | 카드 | `eg` 로 사건 카드를 골라내는 스크립트 |
|---|---|---|
| `SINGLE` | 2,570 | **72 (2.8%)** |
| `FIELD` | 528 | **205 (38.8%)** — 14배 |

두 줄이 모두 같은 방향을 가리킨다. 🔴 그래도 이것은 **측정된 상관**이고
EDOPro 코어 동작의 증명이 아니다 — 그 코어는 이 저장소에 없다. 그래서
**틀렸을 때의 방향**을 확인했다: `SINGLE` 의 뜻이 어디선가 다르면 멀쩡한
후보가 `INELIGIBLE` 로 빠진다(거짓 음성). 지시서 §11 이 둘 중 받아들이기로
한 쪽이고, 반대 방향(거짓 양성) 은 이 축이 만들어 낼 수 없다 — `None` 을
통과로 읽지 않기 때문이다.

### 전수 수치 (지시서 §11-1 · §11-2)

| 항목 | 선언 | 카드 |
|---|---|---|
| **주체 확인 가능** (`SELF`) | **3,389** | 2,665 |
| **주체 불명** (미선언) | **784** | 636 |
| 합계 | 4,173 | — |

**81.2%** 다. 합계 4,173 은 6-E 의 컴파일 수와 **같다** — 지원 범위가 늘었고
줄어든 것은 없다.

| 시점 | `SELF` | 미선언 |
|---|---|---|
| `monster_summoned` | 2,328 | 561 |
| `card_moved` | 1,051 | 206 |
| `card_drawn` | 10 | 17 |

🔴 **컴파일러는 `ANY` 를 한 번도 쓰지 않는다** — 전수 검사로 단정했다
(`test_07`). `FIELD` 가 "어느 카드든" 인지 "이 카드" 인지 Lua 등록만으로는
가려낼 수 없으므로, 그 값은 손으로 등록하는 쪽(ADR-006) 만 쓴다.

### 지시서 §5 의 다섯 문장은 어디까지 갈라지는가

| 문장 | 6-F 가 가르는가 |
|---|---|
| 1. "이 카드가 일반 소환에 성공했을 때" | ✅ `subject=SELF` + `summons={NORMAL}` |
| 2. "몬스터가 일반 소환에 성공했을 때" | ⚠️ `FIELD` 등록이면 **미선언 → UNKNOWN**. 2번이라고 단정하지 않는다 |
| 3. "자신이 몬스터를 특수 소환했을 때" | ❌ **"자신" 을 가르지 못한다** — `actor` 축은 손대지 않았다 (§7) |
| 4. "카드가 묘지로 보내졌을 때" | ⚠️ 2번과 같다 |
| 5. "이 카드가 묘지로 보내졌을 때" | ✅ `subject=SELF` + `to_zones={GRAVE}` |

**카드 텍스트를 읽는 새 문자열 추론기는 만들지 않았다** (§5 의 금지). 공식
원문은 **시험에서 근거를 재는 데만** 썼고 프로덕션은 `declared_types` 만
읽는다.

---

## 7. 발동 위치 및 이전/현재 상태 판정 범위

| 항목 | 상태 |
|---|---|
| 발동 위치 **선언됨** (`activates_from`) | **816** 선언 |
| 발동 위치 **미선언** | **3,357** → `ACTIVATION_ZONE` 관문이 `UNKNOWN` |
| 현재 자리 확인 | 기존 `_activation_zone` 이 관측에서 읽는다 (6-F 가 건드리지 않았다) |
| 이동 **전** 자리 | `ZoneMoved.from_zone` · `TriggerSpec.from_zones` (6-E) |
| 이동 **후** 자리 | `ZoneMoved.to_zone` · `TriggerSpec.to_zones` (6-E) |
| 컨트롤러 | `TriggerCandidate.controller` — 실려 나가지만 **주체 판정에 쓰지 않는다** |
| 턴 플레이어 · 우선권 | ❌ 미검증 (`UNCHECKED_RULES`) |

🔴 **`actor` 축은 손대지 않았다.** 3-F-8 이 측정해 둔 대로
`TimingEvent.actor` 는 **사건군마다 다른 것을 가리킨다** (소환·드로우는
"행한 사람", 라이프는 "당한 쪽", 이동은 "도착지 주인"). 그 어긋남은 주체
문제의 **상류**이고 입력 경계와 별개다. 그것을 고치지 않고 "자신이 특수
소환했을 때" 를 판정하면 틀린다 — 그래서 §6 의 3번을 ❌ 로 남겼다.

---

## 8. 기르수 거짓 양성 회귀 결과

실제 `Duel.apply` 가 만든 journal 기록으로 확인했다 (지어낸 사건이 아니다).
기르수를 필드에 두고 **페더맨을 실제로 일반 소환한** 판이다.

| | 6-E | **6-F** |
|---|---|---|
| 수집기 (definitions 없음) | `UNKNOWN` / `RULE_NOT_IMPLEMENTED` | **`INELIGIBLE` / `CANDIDATE_NOT_ELIGIBLE`** |
| 수집기 (definitions 있음) | `UNKNOWN` | **`INELIGIBLE`** |
| 판정기 `EVENT_RELATION` | `VALID` / `OK` | **`INVALID` / `CANDIDATE_NOT_ELIGIBLE`** |
| `may_activate` | `False` | `False` |

```
사건의 주체는 #0 이고 이 카드는 #40 입니다 — 이 등록은 자기 자신의 사건에만 반응합니다.
```

**"모른다" 가 "주체가 다르다" 로 승격되었다.** 그리고 기르수 **자신**의
소환에서는 주체 관문을 통과한다(`test_12`) — 차단만 하고 아무것도 통과시키지
못하면 축이 일을 하지 않는 것이므로, 통과와 거부를 **둘 다** 확인했다.

🔴 **기르수 전용 하드코딩은 없다.** 카드 ID 는 시험에만 나오고, 프로덕션은
`declared_types` 의 문자열만 읽는다.

---

## 9. 동일 카드명 복수 인스턴스 테스트

포키 드라코(8175346) 를 골랐다 — **효과 블록이 하나**뿐이고 그 하나가
`SINGLE+TRIGGER_O`·`EVENT_SUMMON_SUCCESS` 이며 공식 원문이 「**이 카드가**
일반 소환에 성공했을 때」 이므로 **원문과 등록이 1:1 로 귀속된다.**

같은 카드 2장을 필드에 두고(덱에 같은 카드가 있어 패에도 사본이 생긴다)
한 장만 소환했을 때:

```
필드의 두 사본: A=#40 B=#41    (보이는 사본은 모두 7장)

A 가 소환됨 (사건 주체 = #40)
  source=#40  수집기=eligible    판정기=unknown   EVENT_RELATION=valid/ok    may_activate=False
  source=#41  수집기=ineligible  판정기=ineligible EVENT_RELATION=invalid/… 
  source=#0…#4 (패) 전부 ineligible

B 가 소환됨 (사건 주체 = #41)
  source=#41  수집기=eligible    판정기=unknown
  나머지 6장 전부 ineligible
```

- 통과하는 것은 **정확히 하나**이고 그것이 사건의 주체다.
- A 와 B 의 답이 **정확히 뒤바뀐다** (`test_09`) — 둘이 같은 답을 받으면
  인스턴스를 구분하지 못하는 것이다.
- 🔴 통과한 하나도 `may_activate=False` 다. `ACTIVATION_ZONE` ·
  `EXECUTION_AUTHORITY` · `COST_FEASIBILITY` 가 막고 있고, 미검증 규칙이
  여전히 6개다.

### 영역 이동 후 식별 정보의 유효성 (§6)

`InstanceId` 의 계약이 이미 답한다 — *"한 번 쓴 번호는 재사용하지 않는다
(카드가 존을 옮겨도 번호는 그대로)."* 그래서 이동 뒤에도 같은 번호로
비교할 수 있고, **`GameState` 를 재설계하지 않았다** (§6 의 금지).

---

## 10. UNKNOWN 전파 및 거짓 양성 검증

### 진리표를 전수로 돌렸다 (`test_17`)

세 `subject` × 세 사건 모양 = 9칸. `VALID` 가 나오는 칸은 **정확히 넷**이다.

| `subject` | 주체=나 | 주체=남 | 주체=없음 |
|---|---|---|---|
| `None` | UNKNOWN | UNKNOWN | UNKNOWN |
| `SELF` | **VALID** | **INVALID** | UNKNOWN |
| `ANY` | **VALID** | **VALID** | **VALID** |

- `None` 은 **어느 사건에서도 통과하지 않는다** — 잘못된 TRUE 승격 **0건**.
- 거부가 나오는 칸도 하나뿐이다 — 모름을 거부로 접지 않는다.

🔴 **이 진리표가 내 기대값을 잡았다.** 처음에 통과 칸을 **셋**으로 적고
`("ANY","주체=없음")` 을 빼 두었다. 따져 보니 `ANY` 가 옳다 — 그 값은
"주체에 제약을 걸지 않는다" 는 **단정**이므로 읽을 것이 없고, `UNKNOWN` 으로
적으면 **알 것이 없는 자리를 모른다고** 말하는 셈이다. 그래서 함수가 아니라
내 기대값을 고쳤고, 그 칸이 실제 파이프라인에서는 **도달 불가**임을
(`SUBJECT_AWARE_POINTS` 가 생성을 거부하거나 `matches` 가 먼저 걸러낸다)
함께 단정해 시험을 더 강하게 만들었다.

### 두 `UNKNOWN` 을 가른다 (`test_02`)

| 무엇을 모르는가 | 코드 | 어떻게 풀리는가 |
|---|---|---|
| 선언이 주체를 적지 않았다 | `RULE_NOT_IMPLEMENTED` + `missing_rule` | **코드가 생겨야** 풀린다 |
| 사건이 카드를 가리키지 않는다 · 후보 인스턴스를 모른다 | `INFORMATION_UNAVAILABLE` | **판이 바뀌면** 풀린다 |

3-E-27 이 세운 규율 그대로이고, 섞으면 로드맵이 거짓이 된다.

### And/Or/Not 의미론 보존 (§7)

주체 결과를 `ConditionResult.all_of([relation, *조건들])` 로 **조건과 같은
결합**에 넣는다. `FALSE` 는 `FALSE` 로, `UNKNOWN` 은 `UNKNOWN` 으로 접히므로
모름이 통과로 새지 않는다. 변환은 분기가 아니라 **표**(`_CONDITION_OF_VALIDITY`)
로 두었고, 표가 `ActionValidity` 전부를 덮는지 `test_18` 이 잠근다 —
분기로 쓰면 한 갈래를 빠뜨려도 조용히 통과한다.

### 🔴 구현 중에 내 코드가 한 번 어긋났다

처음에는 "정의 미등록" 가지를 주체보다 **먼저** 보았다. 그래서 정의 출처를
넘기면 수집기가 `UNKNOWN`("조건을 확인할 수 없습니다") 을, 판정기가
`INELIGIBLE` 을 돌려주었다 — **확정된 사실이 모름에 덮였다.** `fold` 의
순서(금지 → 거부 → 모름 → 통과) 와 같게 고쳤고, `test_14` 가 두 경로의
답이 같은지 직접 단정한다.

### 한 구현, 두 호출 자리 (`test_19`)

`subject_relation` 의 정의는 **하나**이고 부르는 production 자리는
`_judge` · `_event_relation` **둘**임을 AST 로 고정했다. 두 벌로 짜면
갈라지고, 갈라지면 §3 의 승격 문제가 돌아온다.

---

## 11. 기존 `TRIGGER_O` / `TRIGGER_F` 구분 유지 여부

`TRIGGER_DECLARATION_TYPES` 는 그대로 `frozenset({"TRIGGER_O","TRIGGER_F"})`
이고, 6-F 는 **접미사의 뜻을 읽지 않았다** — 3-F-26 의 판단(근거 없음) 을
유지한다. `TriggerRequirement` 는 여전히 `UNKNOWN` 으로 실려 나간다.

🔴 범위(`SINGLE`/`FIELD`) 를 쓰는 것은 **다른 종류의 판단**이다. 강제/임의는
이름 말고는 근거가 없었지만, 범위는 §6 의 두 측정이 받쳐 준다.

§9 의 금지 목록은 하나도 건드리지 않았다 — 강제 효과 자동 발동 · 임의 효과
자동 선택 · SEGOC 변경 · 체인 링크 자동 생성 · 우선권 갱신 · 효과 해결 확대
**전부 없다.**

---

## 12. EventJournal 과 Engine V1 회귀 결과

- `test_15`: 주체 검증 전후로 `state_hash()` · `repr(rng)` ·
  journal 의 `canonical_state()` 전부 **같다.**
- `engine/duel.py` 와 `engine/effect/journal.py` 는 **한 줄도** 바뀌지 않았다.
- `EventJournal` 을 규칙의 진실 원천으로 바꾸지 않았다 (§3-4) — 읽기만 한다.
- `UNCHECKED_RULES` 6개 **그대로**. 주체는 이제 보므로 그 목록에 들어가지
  않는다 (`test_16`).

### 🔴 밖에서 난 핀 — **48개 · 26개 파일**

프로덕션은 두 파일인데 감사가 넓게 발화했다. 숨기지 않고 적는다.

| 원인 | 핀 | 무엇을 했나 |
|---|---|---|
| **① 숨은 전제** — 손으로 만든 선언이 *"어느 카드의 사건이든"* 을 암묵 가정 | **29** | 입력에 `subject=ANY` 를 **적었다**. 단정은 하나도 바꾸지 않았다 |
| **② `TriggerSpec` 칸 10 → 11** · `canonical_state` 길이 | **9** | 측정값으로 옮기고 3-F 9 → 6-E 10 → 6-F 11 의 내력을 적었다 |
| **③ `_event_relation` 서명** `(spec, event)` → `(spec, event, source)` | **4** | 3-F-8 이 **권한 설계 C** 다 (아래) |
| **④ `engine/trigger.py` 줄 수 · `RULE_NOT_IMPLEMENTED` 등장 80 → 81 · 산문 줄 번호** | **4** | 측정값 |
| **⑤ `UnimplementedRule` 생성 4 → 3** · 컴파일러 자리 2 → 1 | **2** | 🔴 **이 수가 처음으로 줄었다** (아래) |

①이 가장 많다. 그 시험들은 *"어느 카드의 사건이든 반응한다"* 를
**암묵적으로** 가정하고 있었고, 그 전제가 **참이어야** 시험이 뜻을 갖는다.
예컨대 `test_two_copies_of_one_card_make_two_distinct_links` 는 사본 둘이
**둘 다** 링크가 되는 구조적 성질을 보는 시험이므로, 주체가 `SELF` 라면
애초에 성립할 수 없는 단정이다. `ANY` 를 적어서 그 시험이 보려던 것을
그대로 남겼다. **일괄 치환하지 않았다** — `test_trigger.py` 에는
`TriggerSpec(` 자리가 40개인데 실패한 4개만 고쳤다.

세 묶음은 ①의 특별한 경우다. `test_trigger_unknown_reason` ·
`test_a_hidden_fact_makes_the_candidate_unknown_for_a_different_reason` ·
`test_dormant_live_gate_equivalence` 는 **두 `UNKNOWN` 을 가르거나 두
계층이 같은 답을 내는지** 보는 시험인데, 주체를 적지 않으면 주체의
`RULE_NOT_IMPLEMENTED` 가 섞여 들어와 **그 구분 자체를 볼 수 없게 된다.**
전제를 적어서 **보려던 것만 남겼다.**

### 🔴 3-F-8 이 권한 설계를 6-F 가 실행했다 (③)

`test_event_relation_input_boundary_audit` (3-F-8) 은 세 설계를 비교해
**설계 C** `(spec, event, 필요한 최소)` 를 권하면서 그 "최소" 를
`controller` 라고 적었다. 그때는 **주체 질문이 올라와 있지 않았다.** 사건의
주체를 맞춰 보려면 필요한 것은 플레이어가 아니라 **그 카드 한 장**이므로
`source` 가 되었다.

설계 B(후보 전체) 를 고르지 않았다는 것을 그 감사가 다시 단정한다 —
`assert call[0] == "self._event_relation(spec, event, candidate.source),"` 와
`assert "candidate," not in call[0]`.

### 🔴 `UnimplementedRule` 생성 수가 **처음으로 줄었다** (⑤)

`test_unimplemented_rule_semantics_audit` 는 *"`RULE_NOT_IMPLEMENTED` 와
`UnimplementedRule` 은 같은 개념이 아니다"* 를 고정한다. 그 수는 2(3-E) →
3(6-D) → 4(6-E) 로만 늘어 왔는데, **6-F 에서 4 → 3 이 되었다.**

6-E 가 조건 자리를 빌렸고 6-F 가 돌려주었기 때문이다. 모름이 사라진 것이
아니라 `ValidationResult.missing_rule` 로 **제자리로 갔다.** 그 감사가
지키던 구분이 **실제로 분리 가능하다는 것**을 이 숫자가 보여 준다.

### 🔴 3-F-5 의 "중심 발견" 나머지 절반

`test_14_the_dormant_gate_answers_valid_for_all_three` 는 이렇게 적고
있었다 — *"세 경우 모두 `VALID/OK` 를 낸다. 내 일반 소환에도 **확신 있는
승인**이 난다. 이것이 '구조가 일부만 있다' 보다 나쁜 상태인 이유다:
**틀린 답이 `UNKNOWN` 으로 표시되지 않는다.**"*

이제 표시된다. 그래서 이름을
`test_14_the_dormant_gate_now_answers_honestly_instead_of_valid` 로 바꾸고,
주체를 **적으면** 인스턴스별로 갈리는 것까지 더해 단정했다. 🔴 기존 단정이
틀린 가정을 갖고 있던 것이 아니라 — **그 단정이 요구한 수정이 일어났다.**

`test_13` 도 6-E 에서 `..._can_now_say_special_but_still_not_whose` 로
바꾼 것을 다시
`..._can_now_say_special_and_which_card_but_not_which_player` 로 바꿨다.
③이 **두 축**이었기 때문이다 — "어느 카드" 는 6-F 가 답하고 "누구의
소환"(`actor`) 은 아직 못 본다.

### 🔴 감사가 내 프로덕션 코드를 고치게 만들었다

처음 구현은 관문에서 `subject_relation` 이 돌려준 `validity`/`code` 를
**그대로 전달**했다 — 한 줄로 끝난다. 그런데 두 감사가 발화했다
(`test_event_relation_minimal_fix::test_13` ·
`test_dormant_live_gate_equivalence::test_30`): 이 관문이 낼 수 있는
`(validity, code)` 짝 전부를 **구문으로 읽어** `CODE_VALIDITY` 와 맞추는
것이 3-E-44 의 R-3 규율이고, 계산된 값을 전달하면 그 검사가 불가능해진다.

**감사를 약하게 만들지 않고 코드를 고쳤다** — 네 갈래를 리터럴로 적었다.
그 증거는 `test_30` 의 `event_gate` **짝 집합이 한 짝도 늘지 않았다**는
것이다 (`_gate` 호출 수만 19 → 22). 판정은 여전히 `subject_relation` 이
결정하고, 관문은 그 세 답을 옮겨 적는다.

### 6-E 의 두 시험은 "강해진 사실" 로 고쳤다

`test_f_no_candidate_is_ever_promoted_to_activatable` 과
`test_f_the_same_holds_without_a_definition_source` 는 `UNKNOWN` 을
단정하고 있었다. 그것이 **6-E 가 알 수 있는 전부**였다.

🔴 **기존 단정이 틀린 가정을 갖고 있던 것이 아니다** — 모름이 **확정된
거부로 승격**되었다. 그래서 두 시험의 **핵심 불변(`is_candidate is False`)
은 한 글자도 바꾸지 않고** 그대로 두고, 까닭만 정확하게 적었으며, 단정을
오히려 늘렸다 (주체와 후보 양쪽 인스턴스가 이유에 적히는지, 두 경로의 답이
글자까지 같은지).

---

## 13. 타깃 · 통합 · 최종 회귀 테스트 결과

지시서 §12 의 3단계를 그대로 따랐고, **같은 대규모 묶음을 반복 실행하지
않았다.**

### 1단계 — 타깃

```
pytest tests/engine/test_trigger_event_subject.py -p no:randomly -q
→ 19 passed in 36.09s
```

### 2단계 — 관련 통합

```
pytest tests/engine -p no:randomly -q
→ 2,995 passed in 253.97s   (신규 19개 포함; 기존 2,976 전부 유지)
```

🔴 처음 실행에서 **35개가 실패했다.** 전부 §12 의 "숨은 전제" 이고, 두
단계로 줄였다 — 공유 빌더 3자리를 고쳐 22개가 통과하고, 남은 13개를 개별로
읽어 고쳤다. **일괄 치환하지 않았다**: `test_trigger.py` 에는
`TriggerSpec(` 자리가 40개인데 실패한 것은 4개뿐이어서, 나머지 36개는
건드리지 않았다.

### 3단계 — 필요한 범위의 회귀

프로덕션 변경이 `engine/` 공유 계약(`TriggerSpec` · 관문 서명) 에 닿으므로
`tests/*.py` 전부가 필요한 범위다. 전체를 한 번에 돌리면 백그라운드
상한(30분) 에 걸려 죽고 **죽은 실행은 아무것도 증명하지 않는다** (6-B §9).
그래서 91개 파일을 **4묶음**으로 나누고 하위 디렉터리를 따로 돌렸다.

| 범위 | 파일 | 결과 | 시간 |
|---|---|---|---|
| `tests/engine` | — | **2,995 passed** | 4분 14초 |
| `tests/agent` + `tests/rules` + `tests/rulings` | — | **529 passed · 4 skipped** | 6분 12초 |
| 묶음 0 | 23 | **614 passed** | 21분 45초 |
| 묶음 1 | 23 | **587 passed** | 10분 56초 |
| 묶음 2 | 23 | **559 passed** | 18분 24초 |
| 묶음 3 | 22 | **517 passed** | 21분 27초 |
| **합계** | **91 + 하위** | 🔴 **5,801 passed · 4 skipped · 0 failed** | — |

전부 `-p no:randomly` (순서 고정).

🔴 **묶음을 두 번 돌렸고 그 까닭을 적는다.** 1차 실행에서 47개가 실패했고
(묶음 0 에 7 · 1 에 17 · 2 에 18 · 3 에 5, 하위 디렉터리 0) 전부 §12 의 핀
이동이었다. 그것을 고치는 **도중에** 두 감사가 내 프로덕션 코드를 고치게
만들었고 (§12 의 마지막 절), 그 수정이 `RULE_NOT_IMPLEMENTED` 등장 수와
`_gate` 자리 수를 **다시** 움직였다. 그래서 1차 실행의 수치는 고친 파일에
대해 낡은 것이 되었다.

고친 파일만 단독으로 돌려 통과를 확인한 뒤(93 passed), **묶음 전체를 한 번
더** 돌려 위 수치를 얻었다. 🔴 **추정하지 않았다** — "낡은 실패 하나를
빼면 587" 이라고 적는 대신 587 을 실제로 측정했다.

### 변이 시험 — 내 코드가 틀렸을 때 잡히는가

프로덕션을 한 자리씩 망가뜨리고 돌렸다 (타깃 + 6-E 컴파일러 + 기존 트리거
시험 = 148개).

| 변이 | 결과 |
|---|---|
| M1 `None` 을 통과로 읽는다 | **5 failed** |
| M2 주체가 달라도 통과시킨다 | **8 failed** |
| M3 수집기가 주체를 보지 않는다 | **8 failed** |
| M4 판정기 관문이 주체를 보지 않는다 | **5 failed** |
| M5 컴파일러가 `FIELD` 에도 `SELF` 를 적는다 | **4 failed** |
| M6 컴파일러가 `SELF` 를 아예 적지 않는다 | **9 failed** |
| M7 확정된 거부를 모름 뒤로 미룬다 | **4 failed** |
| M8 사건 주체 대신 후보 인스턴스를 쓴다 | **9 failed** |
| M9 두 `UNKNOWN` 을 한 코드로 뭉갠다 | **1 failed** |
| M10 주체를 걸 수 있는 시점 제한을 없앤다 | **2 failed** |

🔴 **10종 전부 검출되었다.** 특히 M3 와 M4 가 **각각** 잡힌다는 것이
중요하다 — 두 계층 중 하나만 고쳤을 때를 재현한 것이고, 그래야 §3 의
승격 문제가 돌아오지 않는다는 보장이 생긴다.

### 🔴 최종 상태

**5,801 passed · 4 skipped · 0 failed.** 남은 실패가 없으므로 완료로
선언한다 (지시서 §12: *"최종 회귀 테스트 실패가 남아 있으면 완료로
선언하지 않는다"*).

삭제한 테스트 0개 · 추가한 skip 0개 · 약화한 단정 0개 · 낮춘 threshold
0개. 바꾼 것은 **측정값**과 **입력에 숨어 있던 전제**이고, 각 자리에 왜
기존 단정이 당시엔 맞았는지와 무엇이 움직였는지를 주석으로 적었다.

---

## 14. 추가로 발견한 구조적 차단 요인

### 🔴 B-1. 엔진이 **효과 몬스터를 일반 소환하지 못한다**

```
assess_normal_summon(포키 드라코)
→ undetermined: 효과 몬스터는 카드 자신의 제약이 있을 수 있습니다 …
   이 엔진은 그 제약을 아직 읽지 못합니다.
```

`legal_actions` 는 `VALID` 만 제시하므로 **효과 몬스터는 일반 소환 행동으로
나오지 않는다.** 그런데 `SINGLE` 트리거를 가진 카드는 **전부 효과 몬스터**다
(통상 몬스터에는 효과가 없다). 특수 소환 경로도 같은 이유로 제시되지 않았다
(108장을 시험해 보았고 전부 `end_phase` 만 나왔다).

**영향**: "그 카드 **자신**이 소환되는" 사건을 실제 `Duel.apply` 로 만들 수
없다. 그래서 거짓 양성 방향(다른 카드의 소환) 은 실제 사건으로 확인하고,
참 방향은 **실제 `GameState` 의 실제 인스턴스**로 delta 를 만들어 확인했다 —
지어낸 것은 **그 delta 를 만든 행동 하나**뿐이고 인스턴스 · 관측 · 수집기 ·
판정기는 전부 실제다. 숨기지 않고 시험 파일 머리말에도 적었다.

이것을 6-F 에서 고치지 않았다. 지시서 §13 이 "특수 소환 절차 추가" 를
금지하고, 일반 소환을 효과 몬스터까지 넓히는 것은 카드별 제약을 읽는
규칙 계층이 필요한 **별도의 큰 작업**이다.

### 🟠 B-2. 분석기가 원본 파서보다 블록을 적게 돌려준다

컴파일되는 `SINGLE` 블록을 원본 파싱으로 세면 **3,410**, 분석기 경로로
세면 **3,389** 다 (21블록 · 21장 차이). 예: 가가가 걸(3606728) 은
`card.script.effects` 가 6개인데 `analyze().effects` 는 2개다.

프로덕션 경로는 분석기이므로 §6 의 수치는 **3,389** 를 쓴다. 이 차이는
6-F 가 만든 것이 아니고, 지시서 §13 이 "기존 데이터 파이프라인 재구축" 을
금지하므로 **기록만 남긴다.**

### 🟠 B-3. `TimingEvent.actor` 가 사건군마다 다른 것을 가리킨다

3-F-8 이 이미 측정해 둔 것이고 (§7), 그래서 "자신이 몬스터를 특수 소환했을
때" 를 아직 가를 수 없다. 6-F 는 이 축을 **건드리지 않았다** — 주체 문제의
상류이고 별개의 작업이다.

### 🟡 B-4. `FIELD` 784 선언은 여전히 모름

89.8% 가 「이 카드」 를 쓰지만 81건이 쓰지 않으므로 **동전 던지기가 아니라
치우친 동전**이다. 치우친 것을 근거로 쓰면 81건을 틀리게 막는다. Lua 조건
함수 본문(`eg:IsContains(e:GetHandler())` 유무) 을 블록 단위로 읽을 수
있으면 갈라질 가능성이 있지만, 그것은 파서 계층의 작업이다.

---

## 15. Phase 6-G 의 권장 선행 조건

우선순위 순이다.

1. 🔴 **발동 위치 선언을 넓힌다.** 지금 `activates_from` 이 선언된 것은
   816/4,173 (19.6%) 이고, 나머지 3,357 은 `ACTIVATION_ZONE` 이 `UNKNOWN`
   이라서 **주체가 맞아도 `ELIGIBLE` 이 되지 않는다.** 6-F 가 주체를
   풀었으므로 이제 이것이 가장 많이 막는 관문이다. `SetRange` 인자를 읽는
   폭을 측정하는 것이 먼저다.
2. **`TimingEvent.actor` 의 사건군별 어긋남을 정리한다** (B-3). 그것이
   §6 의 3번("자신이 …") 을 여는 유일한 길이다.
3. **`EffectDefinition` 과 컴파일된 선언을 잇는다.** 지금 둘은 이어져 있지
   않고(6-E `test_10`), 그래서 `EXECUTION_AUTHORITY` 가 전부 `UNKNOWN` 이다.
4. **효과 몬스터 소환 절차** (B-1) — 범위가 크므로 별도 Phase 가 맞다.

6-G 에서 **하지 말 것**: 미지원 사건 코드 3,693건을 넓히는 것 (6-E 가 측정한
대로 엔진이 그 사건을 만들어 내지 못한다), 그리고 `FIELD` 784건을 추측으로
메우는 것 (B-4).

---

## 16. Git 커밋 및 푸시 결과

### 변경 파일 — 프로덕션 2 · 테스트 27 · 문서 1

| 구분 | 파일 | 줄 |
|---|---|---|
| 프로덕션 | `engine/trigger.py` | +275 / −15 |
| 프로덕션 | `engine/trigger_compiler.py` | +66 / −12 |
| 테스트 (신규) | `tests/engine/test_trigger_event_subject.py` | +893 |
| 테스트 (핀 이동) | `tests/engine/` 7개 + `tests/` 최상위 19개 | +623 / −119 |
| 문서 (신규) | `docs/phase6f-trigger-event-subject-validation.md` | 이 파일 |

🔴 **바뀌지 않은 것을 명시한다.** `data/` · `script/c*.lua` · `analysis/` ·
`core/` · `engine/duel.py` · `engine/effect/journal.py` ·
**`engine/condition/`** · `agent/` · `app/` · `rules/` · `rulings/` ·
`sources/` 는 **한 줄도** 바뀌지 않았다. 기존 Lua 카드 파일을 지우거나
옮기지 않았고, 카드 데이터를 재생성하지 않았다.

`engine/condition/` 이 그대로인 것이 §4 설계 A 를 고르지 않은 증거다 —
조건 계층의 공개 계약을 넓히지 않고 사건 관계 쪽에 축을 두었다.

### 커밋 — 3개, 브랜치 `claude/pensive-goodall-te1egy`

| 커밋 | 내용 |
|---|---|
| `6008ed9` | 프로덕션 — 주체 축 · 두 계층 연결 · `SINGLE→SELF` 컴파일 |
| `9fa3edc` | 테스트 — 신규 19개 + 밖에서 난 핀 48개 |
| (이 파일의 커밋) | 보고서 |

기존 커밋을 rewrite·amend 하지 않았고, force push 하지 않았으며, 새 브랜치나
PR 을 만들지 않았다.

### 🔴 다음 단계

**Phase 6-G 는 자동으로 시작하지 않는다.** 지시서 §15 의 요구대로 이
단계에서 멈추고 사용자 검토를 기다린다.

이 단계가 끝낸 것은 **"지원되는 사건의 주체를 정확히 식별하고, 주체가 다른
거짓 후보를 차단하는 것"** 까지다. 통과한 후보도 **발동 가능이 아니다** —
자리(`activates_from` 미선언 3,357) · 실행 권위 · 비용이 전부 `UNKNOWN` 이고
미검증 규칙 6개가 그대로 실려 나간다. 갈라테아는 이 단계 뒤에도 유발 효과를
**자동으로 발동시키지 못한다.**
