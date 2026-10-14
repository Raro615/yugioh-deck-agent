# Phase 6-E — 카드 효과 TRIGGER 분석 및 발동 후보 생성 기반 구축

> 요약: **분석 계층은 TRIGGER 를 0건이 아니라 7,868블록 읽고 있었다** (§2 가
> 그 오해를 정정한다). 없던 것은 그것을 엔진의 시점 어휘로 옮기는
> 컴파일러 하나이고, 그것이 `TriggerRegistry` 가 스스로 적어 둔
> **STRUCTURAL-7** 이다. 그 한 자리를 만들었다 — 7,868 중 **4,173블록
> (카드 3,191장)** 이 `TriggerSpec` 이 되고, 실제 듀얼의 일반 소환이
> 실제 후보를 만든다.
>
> 🔴 **그러나 어떤 후보도 `ELIGIBLE` 이 아니다.** "이 사건이 **이 카드의**
> 사건인가" 를 아직 판정할 수 없고, 그 사실을 조건으로 함께 실어 보내
> 판정이 `UNKNOWN` 에서 멈추게 했다. 그 조건을 빼면 **페더맨의 소환에
> 기르수가 발동 가능으로 나온다** — 실제로 재현해서 확인했다.

---

## 0. 🔴 선행 진술 둘을 정정한다

지시서 §2 가 Phase 6-D 의 결과로 두 가지를 적었다. 현재 코드에서 재확인한
결과 둘 다 범위가 다르다.

### ① "`TRIGGER` 형태의 동적 효과 블록은 0건으로 보고됐다"

6-D 보고서가 적은 것은 **`EFFECT_LIBRARY` 안에서 0개**였다 (§13 표:
*"등재가 16개 · `TRIGGER_O` 모양 정의 0개 — 수정 위치 `EFFECT_LIBRARY`"*).
그것은 **손으로 적은 엔진 효과 정의**의 수이고, 분석 계층과 무관하다.

분석 계층을 전수로 재면 이렇다.

| | 블록 |
|---|---:|
| 효과 블록 전체 | 26,352 |
| **`TRIGGER_O`** | **6,002** |
| **`TRIGGER_F`** | **1,866** |
| 합계 (카드 **5,729장**) | **7,868** |

사건 코드도 거의 다 읽혀 있다 — `EVENT_SPSUMMON_SUCCESS` 1,796 ·
`EVENT_SUMMON_SUCCESS` 1,093 · `EVENT_TO_GRAVE` 1,027 · `EVENT_PHASE` 722 …
코드가 `None` 인 블록은 **71개**뿐이다.

🔴 **그러므로 "TRIGGER 0건" 은 분석 문제가 아니었다.** 원인은 §2 가 짚는다.

### ② "`raw_predicates` 를 저장할 필드가 없어 분석 근거가 보존되지 않는다"

필드는 **원래부터 있었다** (`analysis/effect_model.py:119`). 없던 것은 **그
칸에 쓰는 자리**였고 (저장소 전체에 0곳), Phase 6-D 가 카드군 호출에 한해
그것을 만들었다. §9 가 이번 단계와의 관련성을 재서 답한다.

---

## 1. 기존 TRIGGER 정보의 원본 데이터 및 전달 경로

```
c*.lua  (12,968개)
   │  e1:SetType(EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O)
   │  e1:SetCode(EVENT_SUMMON_SUCCESS)
   │  e1:SetRange(LOCATION_MZONE)
   ▼  sources/lua_loader.py  (접두어를 떼어 저장)
core.card_model.EffectSpec
   ├ effect_types : list[str]   ["SINGLE", "TRIGGER_O"]
   ├ code         : str | None  "EVENT_SUMMON_SUCCESS"
   └ ranges       : list[str]   ["MZONE"]
   ▼  analysis/effect_analyzer.py
CardAnalysis.effects[*].effect_types / .raw.code / .raw.ranges
   ▼  🔴 Phase 6-D 까지 여기서 끊겨 있었다 (STRUCTURAL-7)
engine.trigger_compiler.compile_trigger_spec        ← **이번 단계**
   ▼
engine.trigger.TriggerSpec  →  TriggerRegistry
   ▼
                        ┌─ engine.duel.Duel.apply (실제 실행)
                        ▼
                  EventJournal (ACTION · EFFECT · COST_PAYMENT)
                        ▼  engine.event_pipeline.EventReader
                  ObservedEvent (TimingEvent + EventContext)
                        ▼  engine.trigger.TriggerCollector
                  TriggerCandidate
                        ▼  engine.trigger.TriggerEligibilityJudge
                  TriggerEligibility (관문 5개 + unchecked_rules 6개)
```

**아래 다섯 계층은 전부 이미 있었다.** 이번 단계가 더한 것은 화살표 하나다.

---

## 2. `TRIGGER` 0건의 정확한 원인

🔴 **컴파일러가 없었다.** 거절하거나 누락하는 자리가 있었던 것이 아니다.

두 자리가 그 사실을 **스스로 적어** 두었다.

```python
# engine/trigger.py — TriggerSpec
"""카드 데이터에서 자동 생성하지 않는다 (STRUCTURAL-7 · -21 그대로).
손으로 등록하고, 등록되지 않은 카드는 후보가 나오지 않는다 — 그것이
지금의 사실이다."""

# engine/trigger.py — TriggerRegistry
"""**자동 생성이 아니다.** 카드 데이터에서 트리거를 뽑아내는 컴파일러는
아직 없고 (STRUCTURAL-7) …"""
```

Phase 3-E-31 이 그 경계를 표로 정리해 두었고, 거기서 `EffectDefinition` 의
사건 정보를 **INTENTIONALLY DROPPED (컴파일러 없음 · STRUCTURAL-7)** 로
분류했다. 즉 데이터가 없어서가 아니라 **옮기지 않아서** 0이었다.

### 두 어휘의 크기가 다르다 — 그것이 옮기기 어려운 진짜 이유

| | 종류 |
|---|---:|
| Lua `EVENT_*` (`EffectSpec.code`) | **70** |
| 엔진 `TimingPoint` | **8** (그중 하나는 `UNIMPLEMENTED`) |

`TimingPoint` 는 Lua 의 사본이 아니라 `StateDelta` / `JournalEvent` 에서
파생된 어휘이고, **엔진이 실제로 만들어 내는 변화만** 이름을 갖는다
(3-E-31 이 `DERIVED (다른 어휘)` 로 분류). 그래서 옮길 수 있는 코드가 적다.

---

## 3. 기존 `EventJournal` 과 실제 게임 사건 경로의 관계

### 🔴 두 개념을 억지로 같다고 보지 않았다 — **볼 필요도 없었다**

지시서 §6 이 "감사·관찰용 journal 이 타이밍 의미론을 제공하지 않으면 두
개념을 억지로 동일시하지 말라" 고 했다. 재 보니 **이미 분리되어 있고 이미
연결되어 있다.**

- `EventJournal` 의 세 사건(`ACTION`·`EFFECT`·`COST_PAYMENT`)은 모두
  `.deltas` 와 `.actor` 를 들고 있다.
- `EventReader.read(result, actor=…)` 는 **`.deltas` 를 들고 있는 것이면
  무엇이든** 받는다 (그 docstring 이 일곱 종류를 나열한다).
- 그래서 journal 기록을 그대로 넘기면 `ObservedEvent` 가 나온다. **새 사건
  공급 경로를 만들지 않았다.**
- 타이밍 의미론은 journal 이 아니라 `TimingEvent` 가 들고 있다. journal 은
  "무엇이 달라졌는가" 를, `TimingEvent` 는 "그것이 어떤 시점인가" 를 적는다.

### 엔진이 **실제로** 만들어 내는 시점 (실측)

실제 듀얼 59수(journal 52사건)를 돌려 `timing_events()` 로 펼쳤다.

```
  79  unimplemented      ← 40은 행위 자체, 39는 옮길 이름이 없는 delta
  24  card_drawn
  12  effect_resolved
   1  monster_summoned
```

`card_moved` 는 그 판에 없었다. 어리석은 매장을 따로 해결해 확인했다 —
`ZoneMoved(send_to_grave, DECK→GRAVE)` → **`card_moved`**.

`unimplemented` 79의 내역도 재 두었다: 행위 이름 40건
(`activate_effect` 24 · `set_spell_trap` 15 · `normal_summon` 1 — Phase 6-B
가 "행위 자체에는 공식 시점이 없다" 고 정한 그대로)과 delta 39건
(`CardSet` 15 · `SpellRevealed` 12 · `SpellRetired` 12).

---

## 4. 채택한 구현 방식과 대안 비교

### 옮길 수 있는 사건 코드 — **일곱 줄**

| Lua `EVENT_*` | `TimingPoint` | 거는 것 | 블록 |
|---|---|---|---:|
| `EVENT_SUMMON_SUCCESS` | `MONSTER_SUMMONED` | `summons={NORMAL}` | 1,093 |
| `EVENT_SPSUMMON_SUCCESS` | `MONSTER_SUMMONED` | `summons={SPECIAL}` | 1,796 |
| `EVENT_TO_GRAVE` | `CARD_MOVED` | `to_zones={GRAVE}` | 1,027 |
| `EVENT_REMOVE` | `CARD_MOVED` | `to_zones={REMOVED}` | 152 |
| `EVENT_TO_HAND` | `CARD_MOVED` | `to_zones={HAND}` | 60 |
| `EVENT_TO_DECK` | `CARD_MOVED` | `to_zones={DECK}` | 18 |
| `EVENT_DRAW` | `CARD_DRAWN` | — | 27 |

### 옮기지 않은 것 — 40종 3,693블록

| 코드 | 블록 | 왜 |
|---|---:|---|
| `EVENT_PHASE` | 722 | 🔴 **파서가 한정자를 버린다.** 3-E-18 측정: 단독으로 쓰인 블록이 **0개**이고 (1,326블록 전부 `+PHASE_END` 같은 한정자가 붙는다) 파서는 첫 이름만 남긴다. 즉 "어느 페이즈인지 모른다" 다. `PHASE_CHANGED` 로 옮기면 엔드 페이즈 카드가 **모든** 페이즈 전환에서 후보가 된다 |
| `FLIP` (코드 없음) | 69 | 뒤집기 계층이 없다 (§6) |
| `EVENT_DESTROYED` | 539 | 파괴 판정 계층이 없다 |
| 전투 관련 4종 | 982 | 전투·데미지 스텝 계층이 없다 |
| `EVENT_LEAVE_FIELD` | 151 | "필드를 떠났다" 는 도착지로 판정할 수 없다 (ADR-002) |
| 그 밖 | 1,230 | |

### 대안 비교

| 대안 | 왜 택하지 않았나 |
|---|---|
| **A. `EFFECT_LIBRARY` 에 `TRIGGER_O` 정의를 손으로 1개 적는다** (6-D 가 권한 것) | 🔴 **카드 하나를 위한 구조가 된다.** 같은 모양이 7,868블록 있는데 손으로 적으면 다음 장도 손으로 적어야 한다. 지시서 §3-5 (카드별 하드코딩 금지) · §14-10 |
| **B. `EventJournal` 에 사건 종류를 더해 Lua `EVENT_*` 를 그대로 싣는다** | 🔴 Phase 6-B 의 기록 의미론을 바꾼다 (§3-9 · §13). 그리고 journal 은 "무엇이 달라졌는가" 를 적는 자리이지 Lua 어휘를 보관하는 자리가 아니다 |
| **C. `TimingPoint` 에 Lua 코드 70종을 다 더한다** | 🔴 **엔진이 만들어 내지 못하는 시점 이름**이 62개 생긴다. `TimingPoint` 의 docstring 이 그것을 금지한다 — *"어떤 경로로도 생길 수 없는 이름을 미리 못박으면 나중에 실제 모양과 어긋난다"* |
| **D. 새 트리거 수집기·정렬기를 만든다** | 🔴 §3-4. 다섯 계층이 이미 있고 `EventPipeline` 이 조립까지 해 둔다 |
| **E. ✅ 사건 코드 → 시점 변환 하나만 만든다** | 아래 계층을 그대로 쓴다. 옮길 수 없는 코드는 **옮기지 않는다** |

### `Duel` 에 배선하지 않았다

`event_pipeline.py` 의 머리말이 그 이유를 적어 두었다 — *"실행기는 이 파일을
**모른다.** 상태를 바꾸는 일과 사건을 관찰하는 일이 한 함수에 있으면 관찰을
끄거나 관찰자를 바꿀 방법이 없어진다. 실행이 끝난 뒤 그 결과를 여기에
넘기는 것은 바깥쪽의 일이다."*

그대로 따랐다. `duel.py` 는 여전히 "trigger" 라는 말을 **한 번도 쓰지
않고**, `TriggerRegistry` 를 만드는 production 자리도 **0곳**이다. 누가 어떤
선언을 등록할지는 부르는 쪽이 정한다.

---

## 5. 변경한 파일 및 함수

| 파일 | 변경 | 줄 |
|---|---|---|
| `engine/trigger_compiler.py` | **신규** — `compile_trigger_spec` · `EVENT_TIMING` · `TriggerCompilation` · `TriggerCompilationStatus` | +405 |
| `engine/trigger.py` | `TimingEvent.summon` 프로퍼티 · `TriggerSpec.summons` 칸 (+검사·`matches`·직렬화) | +50 / −2 |
| `tests/engine/test_trigger_compiler.py` | **신규** 회귀 테스트 46개 | +898 |

🔴 **프로덕션은 두 파일뿐이다.** 그런데 **감사 18개 파일 · 핀 32개**가
발화했다 — 이 저장소가 "트리거 선언 계층은 휴면이고 필드가 아홉 개다" 를
**열여덟 곳에 걸쳐** 고정해 두었기 때문이다. 그 넓이를 숨기지 않고 적는다.

> 🔴 **이 절의 숫자를 한 번 틀리게 적었다.** 처음에 "10개 파일 · 핀 19개" 로
> 적었는데, 그때 이미 표에 적힌 핀만 세어도 **12개 파일 · 21개**였다 — 표를
> 보고 센 것이 아니라 기억으로 적었기 때문이다. 그리고 그 뒤 전체 회귀가
> **여섯 파일 · 열한 개**를 더 찾아냈다 (`test_event_free_chain_semantics_audit`
> · `test_event_relation_input_boundary_audit` ·
> `test_event_phase_semantics_audit` ·
> `test_effectdefinition_trigger_boundary_audit` ·
> `test_actor_relation_boundary_audit` ·
> `test_duelstep_withheld_validation_audit`). 지금 숫자는 `git diff --numstat` 과
> 아래 표를 직접 센 값이다.

| 감사 파일 | 움직인 핀 | 줄 |
|---|---|---|
| `test_trigger_spec_declaration_audit.py` | 🔴 `test_01`·`test_03`·`test_11`·`test_12`·`test_19` — **필드 9→10, 모듈 1→2** | +110 / −35 |
| `test_special_summon_event_foundation_audit.py` | 🔴 `test_07`·`test_13` — **3-F-5 의 "중심 발견" 절반이 뒤집혔다** | +73 / −29 |
| `test_trigger_pipeline_dormant_audit.py` | `test_01`·`test_05`·`test_13`·`test_25` — 줄수 3건 + `TriggerSpec` 생성 0→1 | +53 / −11 |
| `test_unimplemented_rule_semantics_audit.py` | `test_03` — 생성 3→4 · 등장 79→80 · 🔴 문자열 검사를 구문 검사로 | +34 / −10 |
| `test_rule_not_implemented_code_audit.py` | `test_02` — 문자열 79→80 · 산문 자리 12→13 · 줄번호 +48 | +17 / −6 |
| `test_event_relation_minimal_fix.py` | `test_15` — `matches` 의 조기 반환 4→5 | +14 / −4 |
| `test_validation_code_unknown_policy.py` | `test_28` — `TriggerSpec` 생성 자리 | +13 / −1 |
| `test_trigger_connectivity_audit.py` | `test_02`·`test_04` — importer·생성자 | +11 / −1 |
| `test_validation_code_minimal_fix.py` | `test_09` — 같음 | +9 / −1 |
| `test_validation_code_rejection_semantics_audit.py` | `test_26` — 같음 | +6 / −1 |
| `test_trigger_condition_separation_audit.py` | `test_02` — 필드 목록 | +4 / −0 |
| `test_engine_condition_none_contract_audit.py` | `test_01` — `engine/` 파일 수 67→68 | +5 / −1 |
| 🔴 `test_event_phase_semantics_audit.py` | `test_10`·`test_12`·`test_17` — **`EVENT_PHASE` 글자 금지를 구문 금지로** (아래) | +139 / −9 |
| 🔴 `test_effectdefinition_trigger_boundary_audit.py` | `test_10`·`test_16` — 생성 0→1, **단정을 "정의 쪽과 이어진 자리가 0" 으로 옮김** | +38 / −6 |
| `test_event_free_chain_semantics_audit.py` | `test_11`·`test_12` — 생성 0→1 · 필드 9→10 | +29 / −5 |
| `test_event_relation_input_boundary_audit.py` | `test_19`·`test_20` — `canonical_state` 길이 9→10 · 필드 9→10 | +14 / −2 |
| `test_actor_relation_boundary_audit.py` | `test_19` — 필드 9→10 | +3 / −2 |
| 🔴 `test_duelstep_withheld_validation_audit.py` | `test_18` — **"M3 휴면" 의 두 사실이 한 목록에 섞여 있었다** (아래) | +43 / −4 |

**32개 전부 고정값 이동이고 프로덕션 결함은 0건이다.** 측정으로 센 분류:

| 무엇이 움직였나 | 핀 |
|---|---|
| `TriggerSpec` 필드 수 **9 → 10** (`summons`) · `canonical_state` 길이 | **6** |
| `TriggerSpec` 생성 production 자리 **0 → 1** (또는 모듈 1 → 2) | **6** |
| `RULE_NOT_IMPLEMENTED` 등장 79 → 80 · 산문 자리 12 → 13 · 줄번호 이동 | 3 |
| 🔴 **글자 검사를 구문 검사로 고친 것** (`EffectSpec` 이름 · `EVENT_PHASE` · `RULE_NOT_IMPLEMENTED`) | 4 |
| 그 밖 (조기 반환 4→5 · `engine/` 파일 수 67→68 · 3-F-5 의 중심 발견 절반 · 필드 목록 등) | 13 |

그중 **"이 칸이 없다 · 이 자리가 0곳이다" 를 적어 둔 공백의 기록**이 12개다
(위 표의 첫 두 줄). 이번 단계가 그 공백을 메웠으므로 뒤집혔다. 분류는
**주된 원인** 기준이다 — `test_18` 처럼 한 핀이 두 범주에 걸치는 경우
(생성 자리 이동 + 글자 검사를 구문 검사로) 는 중복해서 세지 않았다.

### 🔴 `test_18` — "선언을 만든다" 와 "배선되어 있다" 가 한 줄에 섞여 있었다

3-E-38/39 의 `test_18_m3_is_still_dormant_and_cannot_reach_either_boundary` 는
이렇게 적혀 있었다.

```python
node.func.id in ("TriggerSpec", "TriggerRegistry")   # 두 이름을 한 목록에
...
assert built == []
```

6-E 뒤 실측 오류:

```
AssertionError: assert ['engine/trigger_compiler.py:377'] == []
```

**이것은 회귀가 아니다.** M3 가 경계에 닿으려면 선언이 **등록되어 듀얼
루프에 실려야** 하는데, 그 두 조건은 그대로다 — 직접 센 값:

| 무엇 | 6-E 뒤 |
|---|---|
| `TriggerSpec()` production 생성 | `engine/trigger_compiler.py:377` **1곳** |
| `TriggerRegistry()` production 생성 | **0곳** |
| `engine/duel.py` 의 `"trigger"` 글자 | **0회** |

그때는 두 수가 **둘 다 0** 이었기 때문에 한 목록으로 묶어도 결론이 같았다.
6-E 가 한쪽만 1 로 옮기자 묶음이 더 이상 성립하지 않는다. 그래서 목록을
**둘로 나눴다** — 휴면성을 결정하는 쪽(`registries`)은 `== []` 를 **그대로
유지**하고, 선언 쪽만 측정값을 적는다. 그리고 **약해지지 않도록** 컴파일러가
`TriggerRegistry` · `TriggerCollector` · `TriggerEligibilityJudge` ·
`EventPipeline` · `engine.duel` 을 **AST 이름 노드로 한 번도 참조하지 않음**을
더해 단정했다 (이것도 처음 글자 검사로 적었다가 그 파일 머리말의 **계층
그림**에 발화했다 — 산문은 호출이 아니다).

🔴 **기능을 끄지 않았고 기대값을 임의로 바꾸지 않았다.** 지시서 §12 의
"테스트를 수정해서 통과시키지 말라" 는 요구에 대한 이 절의 답은: 바꾼 것은
**0 이었던 두 수를 한 칸에 적어 둔 표현**이고, 0 이어야 하는 쪽은 0 으로
남겼다는 것이다.

### 🔴 `EVENT_PHASE` — 이름을 바꿀 수 없는 경우

`declared_types` 는 **내** 이름이었으므로 바꿨다. 그런데
`test_event_phase_semantics_audit` 의 세 핀은 `EVENT_PHASE` 라는 **글자가
`engine/` · `agent/` 에 한 번도 없다** 를 고정하고 있었고, 이것은 공식 상수
자신의 이름이므로 바꿀 수가 없다.

내 컴파일러는 그 이름을 **읽지 않는다.** 그 이름이 등장하는 자리는
*"`EVENT_PHASE` 는 한정자가 파서에서 사라지므로 어느 페이즈인지 알 수 없다 —
그래서 옮기지 않는다"* 를 적은 **docstring** 하나다. 즉 그 감사가 금지하려던
것(값을 읽는 코드 · 나중에 쓰려고 비워 둔 자리)의 **정반대**다.

선택은 둘뿐이었다 — **거부 이유를 지우거나**, **감사가 산문과 코드를
구분하게 하거나**. 뒤를 골랐다. 이 저장소가 3-E-44 부터 지켜 온 규칙이
그것이다 (글자가 아니라 AST 를 센다). `code_mentions()` 를 그 파일에 넣고
주석 · docstring 을 제외했으며, **세는 쪽이 멀쩡한지 고의 위반 4건으로
확인**했다:

```python
assert code_mentions(probe, 'x = EVENT_PHASE\n',      "EVENT_PHASE") == [1]
assert code_mentions(probe, 'x = T["EVENT_PHASE"]\n', "EVENT_PHASE") == [1]
assert code_mentions(probe, '# EVENT_PHASE\n',        "EVENT_PHASE") == []
assert code_mentions(probe, '"""EVENT_PHASE"""\n',    "EVENT_PHASE") == []
```

그리고 **약해지지 않도록 동작 단정을 더했다** — `EVENT_PHASE` ·
`EVENT_PHASE_START` 를 실제로 컴파일러에 넣어 `EVENT_UNSUPPORTED` 가
나오고 `spec is None` 이며 이유 문구에 `Phase` 가 섞이지 않음을 확인한다.
`test_12` 도 같은 방식으로 **표에 페이즈 사건이 없다 · 어떤 시점도
`PHASE_CHANGED` 가 아니다**를 더해, 생성 자리가 0 에서 1 로 늘어난 뒤에도
`PHASE_CHANGED` 선언 경로가 없다는 원래 결론을 그대로 지킨다.

🔴 이 과정에서 **내가 쓴 단정 두 개가 틀렸다.** `TURN_PHASE_ORDER` 를
금지 목록에 넣었는데 `engine/state/turn.py` 가 턴 진행에 정당하게 쓰는
상수였고(5자리), `engine/effect` 를 통째로 금지했는데 컴파일러가
`engine.effect.delta.SummonKind` 를 — **사건 쪽 primitive 를** — 가져온다.
둘 다 금지 대상을 좁혀서 고쳤고 까닭을 테스트 주석에 남겼다.

### 🔴 여덟 감사가 이름 하나를 잡았다 — 그래서 이름을 바꿨다

처음 구현은 컴파일러의 인자를 `effect_types` 로 두었다. 여덟 개 감사가
발화했다 — 여러 Phase 가 *"엔진은 `EffectSpec` 의 칸을 읽지 않는다"* 를
**이름으로** 고정해 두었기 때문이다 (`test_settype_clone_contamination_audit`
의 `test_27` · `test_variable_rebinding_audit` 의 `test_28` ·
`test_loader_analyzer_binding_consistency` 의 `test_37` 등).

내 코드는 `EffectSpec` 을 **읽지 않는다** — 문자열만 받는다. 그러나 그
감사들이 지키려는 것이 바로 이 모듈이 지키려는 것이므로, **감사에 예외를
파는 대신 이름을 바꿨다** (`declared_types`). 바꾸고 나니 호출부가 더
정직해졌다 — 변환은 **부르는 쪽**이 한다는 것이 한 줄에 드러난다.

```python
compile_trigger_spec(ref, declared_types=spec.effect_types, …)
```

ADR-007 때와 같은 결론이다 (6-D §4): **지뢰선이 옳으면 설계를 고친다.**

`data/` · `c*.lua` · `analysis/` · `duel.py` · `journal.py` 는 **한 줄도
바뀌지 않았다.**

### 🔴 `TriggerSpec.summons` 를 더한 이유 — 거짓 양성 하나

Lua 는 일반 소환과 특수 소환을 **다른 사건으로** 등록한다
(`EVENT_SUMMON_SUCCESS` 1,093 · `EVENT_SPSUMMON_SUCCESS` 1,796). 엔진에는
`TimingPoint.MONSTER_SUMMONED` **하나**뿐이고 어떤 소환인지는
`MonsterSummoned.summon` 이 말한다. 구분을 적지 않으면 **"일반 소환했을 때"
카드가 특수 소환에도 후보가 된다.**

`operations` 와 같은 칸에 넣지 않았다 — 그쪽은 **효과가 하는 일**의 어휘이고
소환은 거기 들어가지 않는다 (`MonsterSummoned` 의 docstring 이 그 범주
오류를 경고한다).

---

## 6. TRIGGER 정보 추출 및 분류 결과

```
효과 블록 전체                      26,352
  트리거 등록이 아닌 블록            18,484
  트리거 등록 블록                    7,868
    ↳ 옮겼다 (compiled)              4,173   카드 3,191장
    ↳ 사건 미지원 (unsupported)      3,693   카드 3,279장
         그중 FLIP                      69
    ↳ 사건 코드 미독 (unread)             2   카드     2장
```

옮긴 선언의 시점: `monster_summoned` **2,889** · `card_moved` **1,257** ·
`card_drawn` **27**. 발동 자리(`activates_from`)까지 적힌 선언 **816**.

### 🔴 `FLIP` — 조사 중에 내 상태 이름이 틀렸던 것을 잡았다

사건 코드가 `None` 인 블록 71개를 Lua 로 되짚었다.

| | 블록 |
|---|---:|
| `SetCode` 를 **아예 부르지 않고** `FLIP` 을 가진 블록 | **57** |
| `SetCode` 를 불렀지만 인자를 못 읽고 `FLIP` 도 가진 블록 | **12** |
| `FLIP` 없이 인자를 못 읽은 블록 | **2** |

**69개가 `FLIP`** 이고, 뒤집혔을 때가 유발 시점이므로 **코드가 없는 것이
정상**이다 (섀도르 비스트 3717252 의 `e1`:
`SetType(SINGLE+FLIP+TRIGGER_O)` 뒤에 `SetCode` 가 없다).

처음 구현은 그 69개를 "못 읽었다" 로 적었다. 그러면 **"파서를 고치면
풀린다"** 로 읽히는데 실제로는 **뒤집기 계층이 생겨야** 풀린다. 그래서
`EVENT_UNSUPPORTED` 로 옮기고 이유에 그 사실을 적었다. 남은 **2개**가 진짜
미독이고, 둘 다 3-E-18 이 `None` 으로 되돌린 Clone 사례다 (요정용 고대
4179255 · EM 스카이 매지션 73734821).

`FLIP` 과 옮길 수 있는 코드를 **함께** 가진 블록은 **0개**이므로 이 분기가
멀쩡한 선언을 가로채지 않는다 (전수 확인).

### 🔴 강제 / 임의를 채우지 않았다

`TRIGGER_O` → 임의, `TRIGGER_F` → 강제 로 옮기고 싶어진다. **하지 않았다.**

Phase 3-F-26 이 그 뜻풀이를 **근거 없음**으로 기록했다 — 공식 자료에 그
이름이 0회이고, production 에서 접미사를 해석하는 자리가 0곳이다. 이번
단계가 공식 한국어 원문으로 다시 재 봤고 그 판정을 **뒤집지 못했다**.

```
TRIGGER_O   임의 표기만 3,625   강제 표기만    4   (99.9%)
TRIGGER_F   강제 표기만   394   임의 표기만   45   (89.7%)
```

`TRIGGER_F` 의 10%가 어긋난다. 그래서 `requirement` 와 `wording` 은 둘 다
`UNKNOWN` 이다 — "확인되지 않았다" 를 뜻하는 값이고 그것이 지금의 사실이다
(지시서 §10-D 의 "**구분이 가능하다면**" 에 대한 답).

같은 감사가 **지지한** 것은 하나다: `TRIGGER_O`/`TRIGGER_F` 가 **데이터
분류**라는 것. 그 분류만 쓴다 — "이 블록이 사건에 반응하는 등록이다".

---

## 7. 사건과 발동 후보 연결 결과

실제 듀얼로 끝까지 돌렸다. 기르수를 필드에 두고 **페더맨을 실제로 일반
소환**한 뒤, journal 기록을 `EventPipeline` 에 그대로 넘겼다.

```
등록한 선언 2 (기르수 ordinal 0 = 일반, ordinal 1 = 특수)
Duel.apply(normal_summon) → accepted
journal → EventReader → TriggerCollector
  후보 1개: card=69811710 ordinal=0 status=unknown
            code=RULE_NOT_IMPLEMENTED
```

확인한 것:

1. **실제 사건만 후보를 만든다.** 드로우만 일어난 판에서는 후보 0개.
2. **일반 소환 하나로 특수 소환 선언이 발화하지 않는다** — ordinal 1 은
   후보가 되지 않았다 (`summons` 필터).
3. **사건별로 따로 남는다** — `event_id` 가 서로 다르고 중복이 없다.
4. **한 사건에 여러 효과가 반응하면 각각 따로 식별된다** (`effect_ref` 의
   `ordinal` 이 다르다).
5. **판이 바뀌지 않는다** — `state_hash()` 와 journal 길이가 그대로다.

---

## 8. 발동 후보와 실제 발동 가능 판정의 구분 방식

### 새 열거형을 만들지 않았다 (§7)

기존 타입이 네 단계를 이미 표현한다.

| 지시서의 개념 | 기존 타입 | 이번 단계의 결과 |
|---|---|---|
| 사건·등록이 확인된 후보 | `TriggerCandidate` | 만들어진다 |
| 추가 조건 검사가 필요 | `TriggerStatus.UNKNOWN` + `TriggerCandidate.notes` | 🔴 **모든 후보가 여기** |
| 미지원·해석 불가 | `TriggerCompilationStatus.EVENT_UNSUPPORTED` / `EVENT_UNREAD` | 3,695블록 |
| 실제 발동 가능 | `TriggerEligibility` (관문 5개) + `UNCHECKED_RULES` 6개 | **아직 없다** |

`TriggerStatus.is_candidate` 가 `ELIGIBLE` 에만 참이므로
`if status is not INELIGIBLE:` 같은 코드로 허가가 새어 나가지 않는다.

### 🔴 어떤 후보도 `ELIGIBLE` 이 되지 않는다 — 그리고 그것이 이 단계의 핵심

`TriggerCollector` 는 선언의 카드가 **보이는 사본마다** 후보를 만들고,
사건의 카드와 비교하지 않는다. 즉 기르수가 필드에 있으면 **다른 몬스터가
소환돼도** 후보가 된다.

Lua 는 그것을 적용 범위로 가른다 (`SINGLE` 5,255 · `FIELD` 2,611 트리거
블록). 공식 원문으로 그 축을 메울 수 있는지 재 봤다.

```
SINGLE   "이 카드가" 표기 있음 2,259 · 없음  69   (97.0%)
FIELD                     있음   273 · 없음 288   (48.7%)
```

🔴 **`FIELD` 는 동전 던지기다.** 3-F-26 이 `_O`/`_F` 접미사를 같은 이유로
"근거 없음" 으로 기록했으므로, 일관성상 이것도 메우지 않는다.

**대신 그 사실을 조건으로 적어서 내보낸다.**

```python
condition=UnimplementedRule(
    "trigger-event-subject (이 사건이 이 카드의 사건인가)"
)
```

그러면 판정이 `UNKNOWN` 에서 멈추고 (`RULE_NOT_IMPLEMENTED`)
`missing_rules` 가 무엇이 없는지 말해 준다.

**이것을 빼면 실제로 거짓 양성이 난다.** 처음 구현이 그랬고, 정의 출처를
넘기지 않은 경로에서 **페더맨의 소환에 기르수가 `ELIGIBLE`
(`is_candidate=True`)** 로 나왔다. 재현해서 확인하고 고쳤으며, 그 반례를
테스트로 고정했다 (`test_f_the_same_holds_without_a_definition_source`).

---

## 9. `raw_predicates` 관련 처리 결과

**이번 단계와 관련이 없다.** 재서 확인했다.

| 지시서 §9 의 질문 | 답 |
|---|---|
| 어떤 조건 정보가 소실되는가 | 카드군 호출의 인자 (6-D 가 처리) |
| 그것이 발동 **사건**이나 발동 **조건**과 관련되는가 | 🔴 **아니다.** 트리거 정보는 `effect_types` · `code` · `ranges` 세 칸에서 오고 `raw_predicates` 를 거치지 않는다 |
| 트리거 경로에서 실제로 소실되는 것이 있는가 | 사건 코드 미독 **2블록**뿐이고, 그것은 `EVENT_UNREAD` 라는 **별도 상태로 보존**된다 |
| 그 2블록이 `raw_predicates` 에 흔적을 남기는가 | **0건** (전수 확인) |
| 기존 모델의 다른 필드로 보존 가능한가 | `card.script.trigger_events` 가 있지만 3-E-31 이 **DERIVED (권위 없음)** 로 분류했다 — 파일 전체 정규식이라 "어느 효과에 붙었는지 모른다". 쓰면 추측이 된다 |

**새 필드를 만들지 않았다.** 정보가 부족한 2블록은 후보를 만들지 않는다.

---

## 10. 기르수 등록 정보 및 후보 생성 검증 결과

| 항목 | 결과 |
|---|---|
| Lua 등록 정보 | `e1: SetType(SINGLE+TRIGGER_O)` · `SetCode(EVENT_SUMMON_SUCCESS)` · `SetProperty(EFFECT_FLAG_DELAY)` · `SetCountLimit(1,id)` |
| | `e2 = e1:Clone()` · `SetCode(EVENT_SPSUMMON_SUCCESS)` |
| | `e3: SetType(IGNITION)` · `SetRange(LOCATION_MZONE)` — **트리거가 아니다** |
| 컴파일 결과 | **2개** — ordinal 0 → `MONSTER_SUMMONED` + `summons={NORMAL}` / ordinal 1 → `+{SPECIAL}` |
| `e3` | `None` (트리거 등록이 아니므로 결과 객체를 만들지 않는다) |
| 실제 후보 생성 | ✅ 페더맨의 일반 소환에서 **ordinal 0 만** 후보가 된다 |
| 후보 상태 | 🔴 **`UNKNOWN` / `RULE_NOT_IMPLEMENTED`** — `ELIGIBLE` 아님 |
| 확인된 부분 | 사건 종류 · 등록 사건 · 소환 종류 구분 |
| **미확인 부분** | ① 이 사건이 **이 카드의** 사건인가 ② 발동 자리 (`e1` 에 `SetRange` 가 없다) ③ 1턴 1회 (`SetCountLimit`) ④ `EFFECT_FLAG_DELAY` ⑤ 효과 본문 (`EFFECT_LIBRARY` 미등재) ⑥ 스펠 스피드 ⑦ 체인 삽입 |
| 일반 소환 판정 | `UNDETERMINED` **그대로** (6-C 와 동일, 이번 범위 아님) |

기르수 전용 분기는 **없다.** 테스트가 쓰는 것은 효과 타입 이름과 사건
코드뿐이고, 카드 ID 는 "어느 카드로 쟀는지" 를 적는 데만 쓴다.

---

## 11. 구현 전후 지원 범위 및 정확성 지표

| 지표 | 구현 전 | 구현 후 |
|---|---:|---:|
| 1. `TRIGGER` 로 분류된 효과 등록 | 7,868 (분석 계층) · **0** (엔진) | **7,868** (엔진이 받는다) |
| 2. 사건 코드까지 확인된 `TRIGGER` | 7,797 (분석) · **0** (엔진) | **4,173** 옮김 + 3,624 미지원 |
| 3. 발동 영역까지 확인된 `TRIGGER` | **0** | **816** |
| 4. 발동 후보로 만들 수 있는 등록 | **0** | **4,173** (카드 3,191장) |
| 5. 조건 미확인으로 보류한 등록 | — | **4,173 전부** (사건 주체 미판정) |
| 6. 잘못 분류한 효과 | — | **0** — `ACTIVATE`·`IGNITION`·지속 블록 18,484개 전수 확인, 하나도 트리거가 되지 않았다 |
| 7. 실제 지원되는 사건 종류 | 0 | **7** (코드) → **3** (시점) |
| 8. 실행 검증까지 완료된 사례 | 0 | **0** — `EFFECT_LIBRARY` 등재 16개 그대로 |

### 🔴 더 많이 찾은 것이 성공 지표가 아니다

- **양방향 전수 확인.** 트리거가 **아닌** 블록 18,484개 중 컴파일되는 것이
  0개이고, 컴파일된 7,868개는 **전부** 트리거 타입을 실제로 갖고 있다.
- **`FLIP` 69개 전부**가 옮겨지지 않는다 (전수).
- **지표 8이 0이다.** 후보가 나온다는 것과 효과가 실행된다는 것은 다른
  말이고, 등재는 **16개 그대로**다.
- **지표 5가 4,173 전부다.** 즉 "옮겼다" 가 "발동 가능" 을 뜻하지 않는다.

---

## 12. 추가한 테스트와 회귀 테스트 결과

신규 `tests/engine/test_trigger_compiler.py` — **46개 전부 통과** (3:16).

| 묶음 | 개수 | 무엇을 지키는가 |
|---|---:|---|
| A. 등록 정보 추출 | 3 | 트리거가 아니면 `None` · 두 종류 다 받는다 · 🔴 접미사를 강제/임의로 읽지 않는다 |
| B. 사건 코드 → 시점 | 12 | 일곱 줄 · 지어낸 시점 0 · `EVENT_PHASE` 거부 · `FLIP` 은 미지원 · 미독은 2블록 |
| C. 소환 구분 | 4 | 🔴 일반 ↔ 특수 교차 반례 · 시점 밖에서는 못 건다 · 소환은 `operation` 과 다른 표 |
| D. 도착지 사건 | 3 | 의미로 좁히지 않는다 · 드로우와 안 겹친다 |
| E. 발동 자리 | 3 | 적힌 것만 · 안 적으면 `None` · 🔴 하나라도 못 옮기면 전부 버린다 |
| F. 실제 사건 연결 | 6 | 실제 듀얼 · 특수 선언 불발화 · 🔴 **승격 없음** · 정의 출처 없어도 같다 · 무관한 사건 0 · 실제 묘지 이동 |
| G. 중복·순서·복수 | 4 | 사건별 분리 · 효과별 분리 · 중복 등록 거부 · 같은 입력 같은 선언 |
| H. 기존 엔진 호환 | 3 | 판 불변 · 🔴 `duel.py` 미배선 · ADR-007 |
| I. 전수 측정 | 3 | 세 묶음 수치 · `FLIP` 69 전부 |
| J. 오분류 | 3 | 🔴 양방향 전수 + 레지스트리 누출 방지 |

### 변이 시험 9종 — 전부 잡힘

| 변이 | 결과 |
|---|---|
| M1 소환 구분 삭제 (일반/특수 합침) | 5 failed |
| M2 🔴 사건 주체 조건 삭제 (거짓 양성 복귀) | 1 failed |
| M3 `EVENT_PHASE` → `PHASE_CHANGED` | 4 failed |
| M4 못 옮기는 range 를 버리고 나머지만 쓴다 | 1 failed |
| M5 접미사로 강제/임의를 채운다 | 1 failed |
| M6 트리거가 아닌 블록도 받아들인다 | 4 failed |
| M7 옮기지 못한 등록도 등록 가능으로 | 9 failed |
| M8 `matches` 가 `summons` 를 보지 않는다 | 4 failed |
| M9 도착지 필터 삭제 | 5 failed |

### 전체 회귀

🔴 **실측값이다.** 전체를 한 번에 돌리면 백그라운드 상한(30분) 에 걸려 죽고
**죽은 실행은 아무것도 증명하지 않는다** (6-B §9 에서 배운 것). 그래서
`tests/*.py` 91개 파일을 **4묶음**으로 나누고 하위 디렉터리를 따로 돌렸다.
묶음 분할에 누락·중복이 없음을 `diff` 로 확인했다 (91 = 23+23+23+22).

| 범위 | 파일 | 결과 | 시간 |
|---|---|---|---|
| `tests/engine` + `tests/agent` + `tests/rules` + `tests/rulings` | — | **3,505 passed · 4 skipped** | 10분 09초 |
| 묶음 0 | 23 | **614 passed** | 20분 41초 |
| 묶음 1 | 23 | **587 passed** | 11분 05초 |
| 묶음 2 | 23 | **559 passed** | 17분 05초 |
| 묶음 3 | 22 | **517 passed** | 22분 14초 |
| **합계** | **91 + 하위** | 🔴 **5,782 passed · 4 skipped · 0 failed** | — |

전부 `-p no:randomly` 로 돌렸다 (순서 고정).

🔴 **처음 실행에서는 실패가 12건 났고, 전부 §5 의 핀 이동이었다** (묶음 0 에
2 · 묶음 1 에 6 · 묶음 2 에 4 · 묶음 3 과 하위 디렉터리는 0). 그 12건은
**새 핀 11개 + 이미 센 핀 1개의 재발화**다 — `test_rule_not_implemented_code_audit`
의 `test_02` 는 6-E 안에서 두 번 발화했다 (한 번은 등장 수 79→80, 한 번은
FLIP 재분류로 그 산문 줄이 143→152 로 밀려서). 핀 총계가 21+11 = **32** 인데
실패가 12건인 이유가 그것이다.

고친 뒤 **영향을 받은 묶음만** 다시 돌려 위 수치를 얻었다. 묶음 3 과 하위
디렉터리는 수정 이후 변경된 파일을 담고 있지 않아 재실행하지 않았다 —
`git status` 로 확인한 사실이고, 돌리지 않은 것을 돌렸다고 적지 않는다.

🔴 **그중 2건은 내가 처음에 직접 보지 못했다.** `| tail -5` 로 잘라 받았기
때문에 묶음 1 에서 `6 failed` 라는 총계는 보이는데 `FAILED` 줄은 **4개만**
찍혔다. 총계와 이름 목록이 어긋나 있었다는 것이 단서였고, 해당 파일들을
단독 실행해서 나머지 둘(`test_event_free_chain_semantics_audit::test_11` ·
`test_duelstep_withheld_validation_audit::test_18`) 을 찾았다. **출력을 자른
실행은 실패 목록을 증명하지 않는다** — 다음부터 `tail` 을 늘린다.

🔴 그리고 그 둘 중 `test_18` 은 **사용자가 먼저 발견했다.** 내가 묶음을
다시 돌리려 할 때 중단시키고 "대규모 묶음을 반복 실행하지 말고 실패한
테스트만 단독 실행해서 원인을 조사하라" 고 지시했다. 그 지시가 맞았다 —
단독 실행은 1.45초였고, 묶음 재실행은 11분이었다.

### 🔴 내가 쓴 단정 중 세 개가 틀렸다 (전부 "금지 범위를 너무 넓게 잡음")

핀을 고치면서 **내가 새로 쓴** 단정 세 개가 발화했다. 숨기지 않고 적는다.

| 내가 쓴 단정 | 왜 틀렸나 | 어떻게 고쳤나 |
|---|---|---|
| `"engine.effect" not in compiler` | 컴파일러가 `engine.effect.delta.SummonKind` 를 가져온다 — **사건 쪽 primitive** 이고 정의 계층이 아니다 | 금지를 `engine.effect.definition` · `engine.effect.library` 로 좁혔다 |
| `code_mentions(…, "TURN_PHASE_ORDER") == []` | `engine/state/turn.py` 가 턴 진행에 **정당하게** 쓰는 상수다 (5자리) | 금지 대상은 "사건 코드에서 그 목록을 되돌려 주는 변환" 이고, 사건 코드 자체가 코드 자리에 0회이므로 그 줄을 지웠다 |
| `"TriggerRegistry" not in compiler` (글자) | 그 파일 **머리말의 계층 그림**이 그 이름을 그린다 — 산문은 호출이 아니다 | AST 의 이름 노드만 센다 (3-E-44 규칙) + `"TriggerSpec" in used` 로 세는 쪽을 역검증 |

세 번째가 이번 단계에서 **같은 교훈이 네 번째로 나온 자리**다 —
`declared_types` · `EVENT_PHASE` · `RULE_NOT_IMPLEMENTED` 에 이어서. **글자로
금지하면 거부 이유를 적은 산문까지 위반으로 보인다.**

### 밖에서 난 핀 32개

§5 의 표가 전부다 — 18개 파일 · 핀 32개이고 **프로덕션 결함은 0건**이다.
그중 특히 적어 둘 둘 (세 번째인 `EVENT_PHASE` 는 §5 에 적었다):

#### 🔴 3-F-5 의 "중심 발견" 절반이 뒤집혔다

`test_13_a_declaration_cannot_say_special_nor_whose` 는 Phase 3-F-5 가
**이 Phase 의 중심 발견**이라고 적은 것이다 — 선언이 특수 소환을 가리킬
수 없고, 그래서 `matches` 가 "내 일반 소환 · 내 특수 소환 · 상대의 특수
소환" 을 전부 같은 것으로 보며, *"적을 수가 없으므로 그 정직한 길에 닿지
못하고 `VALID/OK` 가 난다"*.

6-E 가 **소환 종류 축을 고쳤다** (`summons`). `actor` 축과 "어느 카드의
사건인가" 는 **그대로 못 본다** — 다만 그 사실을 조건으로 적었으므로
3-F-5 가 지적한 `VALID/OK` 는 더 이상 나오지 않는다. **판정이 생겨서가
아니라 모른다고 말하게 되어서**다. 테스트 이름을
`test_13_a_declaration_can_now_say_special_but_still_not_whose` 로 바꿔
그 구분을 적었다.

#### 🔴 `test_19` 가 설계대로 나를 잡았다

3-F-6 은 *"필드 하나를 더해서 해결되지 않는다"* 고 적으면서 필드 수를
**9로 박아** 두었다 — 아무도 몰래 더하지 못하게. 6-E 가 정확히 하나를
더했고 그 핀이 잡았다. 그래서 테스트 이름을
`test_19_that_phase_added_no_field_but_phase_6e_added_exactly_one` 로 바꾸고,
**3-F-6 의 그 문장이 여전히 맞다**는 것(더한 하나로 해결된 것은 종류뿐)을
함께 적었다.

**테스트 통과가 모든 카드의 유발 효과를 지원한다는 뜻이 아니다.** 지원되는
것은 "사건 종류와 등록을 비교해 후보를 만드는 것" 까지이고, 그 후보는
**하나도 발동 가능이 아니다.**

---

## 13. 기존 Engine V1 및 EventJournal 호환성

| 요소 | 영향 |
|---|---|
| `engine/duel.py` | **없음.** "trigger" 라는 말이 한 번도 없다 (`test_12` · `test_h_the_compiler_never_touches_the_duel_or_the_journal`) |
| `EventJournal` (6-B) | **없음.** `journal.py` · `action_execution.py` · `spell_activation.py` · `agent/simulation.py` 를 한 줄도 건드리지 않았다 |
| 기록 의미론 | **없음.** 후보 수집은 journal 을 **읽기만** 한다 — `state_hash()` 와 journal 길이가 불변임을 테스트가 고정 |
| 기존 행동 결과 | **없음.** `Duel.apply` 경로에 손대지 않았다 |
| 트리거 계층 다섯 | **휴면 그대로.** `timing` · `event_pipeline` 을 import 하는 production 파일이 **여전히 0곳**이고 `Duel` 폐쇄 밖이다 |
| ADR-007 | **그대로.** 컴파일러가 `analysis` · `core` · `sources` 를 import 하지 않는다 (문자열과 숫자만 받는다) |
| `analysis` · `data` · `c*.lua` | **없음.** 한 줄도 바뀌지 않았다 |

```
$ python3 -m pytest tests/engine/test_event_journal_integration.py -p no:randomly -q
14 passed
```

---

## 14. 발견했지만 수정하지 않은 문제

| | 문제 | 측정 | 왜 안 했나 |
|---|---|---|---|
| 1 | 🔴 **"이 사건이 이 카드의 사건인가" 를 판정할 수 없다** | `SINGLE` 5,255 · `FIELD` 2,611 블록. 원문 상관: 97.0% / **48.7%** | 메울 근거가 `FIELD` 쪽에 없다 (동전 던지기). 조건으로 적어 `UNKNOWN` 에서 멈추게 했다 — **6-F 의 1번 과제** |
| 2 | `EVENT_PHASE` 의 한정자가 버려진다 | 1,326블록이 한 값으로 | 파서 변경이고 이번 범위 밖 (3-E-18 이 이미 기록) |
| 3 | 뒤집기(`FLIP`) 계층이 없다 | 69블록 | 소환 계층 작업 |
| 4 | 파괴 · 전투 계층이 없다 | 1,521블록 | 같음 |
| 5 | 강제/임의를 가릴 근거가 없다 | `TRIGGER_F` 의 10%가 어긋남 | 3-F-26 의 판정 유지 |
| 6 | `EFFECT_LIBRARY` 등재 16개 | 트리거 정의 0개 | §13 금지 (개별 카드 효과 대량 추가) |
| 7 | `TriggerRegistry` 를 채우는 production 자리가 없다 | 0곳 | 누가 등록할지는 다음 단계의 설계 문제 |
| 8 | 6-D 의 미해결 카드군 3종 · `by_setcode` 의미론 | — | 트리거 연결을 막지 않는다 (§13 대로 별도 추적) |

---

## 15. Phase 6-F 의 권장 작업 범위와 선행 조건

### 🔴 1번 과제 — **사건 주체 판정** (이번 단계가 만든 유일한 차단 요인)

후보가 `ELIGIBLE` 이 되려면 "이 사건이 이 카드의 사건인가" 를 판정해야
한다. 지금은 `UnimplementedRule` 이 그 자리를 지키고 있다.

**선행 조건**: 그 축을 메울 **근거**가 필요하다. 세 가지 후보를 재 두었다.

1. `EFFECT_TYPE_SINGLE` / `FIELD` — 원문 상관 97.0% / 48.7%. `SINGLE` 쪽은
   쓸 만하지만 `FIELD` 쪽이 근거가 없다.
2. Lua 필터 함수의 `e:GetHandler()` 비교 — 구조적 근거이고 파서 작업이
   필요하다.
3. 공식 원문의 「이 카드가」 — 한국어 텍스트 파싱이고 6-C 가 같은 종류의
   추론을 거부한 선례가 있다.

🔴 **셋 중 어느 것도 지금 확정할 수 없다.** 6-F 가 먼저 **근거를 고르는
조사**를 하고, 그 다음에 판정을 만드는 순서를 권한다.

### 2번 — 그 다음에야 의미가 있는 것들

- `EFFECT_LIBRARY` 에 `TRIGGER_O` 정의 1개 (이제 선언은 자동으로 나온다).
- 발동 자리 관문 — 선언 816개가 이미 `activates_from` 을 들고 있다.
- 1턴 1회 (`SetCountLimit`) — `UseRegistry` 와 `LimitScope` 가 이미 있다.

### 하지 말 것

후보가 나왔다는 이유로 체인에 넣거나, 강제/임의를 접미사로 채우거나,
`EVENT_PHASE` 를 `PHASE_CHANGED` 로 옮기는 것. 셋 다 이번 단계가 측정으로
거부한 것들이고, 변이 시험이 그 셋을 모두 잡는다.

🔴 **Phase 6-F 를 자동으로 시작하지 않는다.** 사용자 검토를 기다린다.

---

## 16. 변경 파일, 커밋 및 푸시 결과

### 변경 파일 — 프로덕션 2 · 테스트 19 · 문서 1

| 구분 | 파일 | 줄 |
|---|---|---|
| 프로덕션 (신규) | `engine/trigger_compiler.py` | +405 |
| 프로덕션 (수정) | `engine/trigger.py` | +50 / −2 |
| 테스트 (신규) | `tests/engine/test_trigger_compiler.py` | +898 |
| 테스트 (핀 이동) | 감사 **18개 파일** — §5 의 표 | +620 / −130 |
| 문서 (신규) | `docs/phase6e-trigger-analysis-candidate-integration.md` | 이 파일 |

🔴 **바뀌지 않은 것을 명시한다.** `data/` · `script/c*.lua` · `analysis/` ·
`engine/duel.py` · `engine/journal.py` · `core/` · `agent/` · `app/` ·
`rules/` · `rulings/` · `sources/` 는 **한 줄도** 바뀌지 않았다. 기존 Lua
카드 파일을 지우거나 옮기지 않았고, 카드 데이터를 재생성하지 않았다.

### 커밋 — 3개, 브랜치 `claude/pensive-goodall-te1egy`

| 커밋 | 내용 |
|---|---|
| `076fd5c` | 프로덕션 — 사건 코드 → 시점 컴파일러 · `summons` 축 |
| `d38442b` | 테스트 — 신규 46개 + 밖에서 난 핀 32개 |
| (이 파일의 커밋) | 보고서 |

기존 커밋을 rewrite·amend 하지 않았고, force push 하지 않았으며, 새 브랜치나
PR 을 만들지 않았다. 지정된 작업 브랜치에만 푸시한다.

### 🔴 다음 단계

**Phase 6-F 는 자동으로 시작하지 않는다.** 지시서 §15 의 요구대로 이 단계에서
멈춘다.

이 단계가 끝낸 것은 **"실제 사건과 효과의 등록 정보를 연결해 신뢰할 수 있는
발동 후보를 만드는 것"** 까지다. 그리고 그 후보는 **하나도 발동 가능이
아니다** — 모든 컴파일된 선언이 `UnimplementedRule(EVENT_SUBJECT_RULE)` 를
달고 있어서 "이 사건이 이 카드의 사건인가" 에 `UNKNOWN` 으로 답한다.
갈라테아는 이 단계 뒤에도 유발 효과를 **자동으로 발동시키지 못하고**, 그
사실을 숨기지 않고 말한다.

---

## 결론 — 다음 단계가 활용할 수 있는 인터페이스

```python
from engine.trigger_compiler import (
    compile_trigger_spec,        # 등록 정보 → TriggerSpec (또는 미지원 결과)
    EVENT_TIMING,                # 옮길 수 있는 사건 코드 7개
    TriggerCompilationStatus,    # compiled / unsupported / unread
)
from engine.trigger import TriggerRegistry, TriggerSpec, TriggerStatus
from engine.event_pipeline import EventPipeline   # journal → 후보
```

- 카드 데이터에서 **선언이 자동으로 나온다** (4,173개). 손으로 적지 않는다.
- 옮길 수 없는 사건은 **옮기지 않고 그 이유를 말한다** (3,695개).
- 일반 소환과 특수 소환이 **갈린다.**
- 🔴 **어떤 후보도 발동 가능이 아니다.** 그것이 지금 확인된 사실의 전부다.
- 기존 듀얼 결과와 `EventJournal` 기록은 **바뀌지 않았다.**

갈라테아가 무엇을 할 수 있는지 추측하지 않았다. 옮긴 4,173개는 "이 사건에
반응한다고 카드가 적어 두었다" 는 사실이고, 그 사건이 **그 카드의** 일인지는
아직 아무도 확인하지 않았다 — 그 사실도 함께 적어서 내보낸다.
