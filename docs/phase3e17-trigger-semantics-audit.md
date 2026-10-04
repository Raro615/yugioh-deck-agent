# Phase 3-E-17 — 유발 조건의 의미가 어디까지 보존되는가 (감사)

- 실제 HEAD / Base: `88db9ec` (Phase 3-E-16)
- 판정: **B — AUDIT ONLY.** semantic collapse 는 **실재하고 측정됐다** (162장).
  그런데 지금 어떤 판정도 그 값을 읽지 않으므로 **잘못된 동작은 없다.**
- Production 변경: **설명 세 곳** (§14 의 첫 번째 허용 — 측정된 의미와 어긋나는
  문구). 동작 변화 0.

---

## §4 — Data Flow: 유발 정보가 어디까지 가는가

| Layer | Structure | Trigger/Event 정보 | 보존 | 의미 |
|---|---|---|---|---|
| 공식 Lua | `cXXXXXXXX.lua` | `e1:SetCode(EVENT_*)` | — | 원본 |
| Parser | `sources/lua_loader.py` | 효과별 `spec.code` **+** 파일 전체 `info.trigger_events` | **O (부분)** | 이름을 댈 수 있는 인자만 |
| Core | `core.card_model.EffectSpec.code` | `"EVENT_…"` / `"EFFECT_…"` / `None` | **O** | **효과별 — 유일하게 정확한 자리** |
| Core | `core.card_model.LuaScriptInfo.trigger_events` | `["EVENT_…", …]` | O | **파일 전체 정규식 — 유발 목록이 아니다** |
| Analysis | `analysis.effect_model.EffectAnalysis.trigger_event` | 같은 값 | O | `SetCode` 가 `EVENT_*` 면 그 값 |
| **EffectDefinition** | `engine.effect.definition` | **없다** | **X** | 필드 자체가 없다 |
| Engine | `activation_timing` · `action_validation` · `activation` | **읽지 않는다** | X | AST 로 확인 |

### Q4 의 전제가 틀렸다 — **변환이 없다**

> "EffectDefinition 으로 변환되는 순간 trigger information 이 사라지는가?"

`EffectDefinition(` 을 만드는 자리는 repository 전체에서 **하나**다 —
`engine/effect/library.py` 의 16건이고 **전부 손으로 적은 것**이다 (ADR-006).
`engine` 은 효과 쪽에서 `analysis` 를 import 하지 않는다.

그래서 "pipeline 이 값을 흘린다" 가 아니라 **"전사한 사람이 그 값을 적지
않았다"** 다. 고칠 자리가 전혀 다르다 — 파서도 analysis 도 아니라 **전사
규칙**이다.

---

## §5 — 네 상태 중 무엇이 구분되는가

| 상태 | 현재 표현 | 어디서 구분되나 | 의미 |
|---|---|---|---|
| **A** 실제 trigger 없음 | `code == "EVENT_FREE_CHAIN"` | core / analysis | **명시적으로 적혀 있다** |
| **B** trigger 존재 | 다른 `EVENT_*` (69종) | core / analysis | 어떤 사건인지까지 안다 |
| **C** trigger unknown | — | **없다** | `None` 에 흡수 |
| **D** trigger 미기록 | — | **없다** | `None` 에 흡수 |
| (해당 없음) | `code is None` (SetCode 부재) | — | C · D 와 같은 값 |
| (유발이 아님) | `EFFECT_*` | core / analysis | 지속 · 적용 효과 |

**A 와 B 는 구분된다. C 와 D 는 구분되지 않는다.**
그리고 `EffectDefinition` 층에서는 **넷 다 구분되지 않는다** (필드가 없으므로).

### 비대칭이 같은 모듈 안에 있다

`analysis.effect_model.ActivationCondition` 은 `has_condition_function` ·
`unparsed` · `raw` 를 갖고 있다 — **조건** 쪽은 "있었는데 읽어내지 못했다" 를
말할 수 있다. 유발 쪽(`trigger_event`)에는 그 짝이 **없다.** 고쳐야 할 날
어디를 보면 되는지를 이 비대칭이 가리킨다.

---

## §6 — `EVENT_FREE_CHAIN` 의 정확한 의미

**유발 이벤트가 아니다.** 그런데 **구문으로는 구분되지 않는다.**

```
data/constants/constant.lua
    EVENT_FREE_CHAIN      = 1002
    EVENT_CHAINING        = 1027
    EVENT_DESTROYED       = 1029
    EVENT_SUMMON_SUCCESS  = 1100
```

같은 `EVENT_*` 이름, 같은 번호대. `code.startswith("EVENT_")` 로는 못 가른다.

**가르는 것은 함께 쓰인 `EFFECT_TYPE_*`** 이고, 전수 측정이 깔끔하게 나뉜다.

| | 함께 쓰인 `EFFECT_TYPE_*` |
|---|---|
| `EVENT_FREE_CHAIN` (4,909 블록) | ACTIVATE 3638 · QUICK_O 1256 · IGNITION 58 · FIELD 3 · CONTINUOUS 1 — **TRIGGER_O · TRIGGER_F 0건** |
| 다른 `EVENT_*` (11,474 블록) | SINGLE 6024 · **TRIGGER_O 6019** · FIELD 4181 · CONTINUOUS 2201 · **TRIGGER_F 1963** · ACTIVATE 663 |

앞쪽은 **플레이어가 고르는** 발동이고, 뒤쪽은 **무언가가 일어나서** 걸리는
효과다. 그래서 `EVENT_FREE_CHAIN` 은 "유발 조건이 없다" 를 적은 **활성화 범주
표시**다.

> **Phase 3-E-16 의 표현을 바로잡는다.** 그 보고서는 `EVENT_FREE_CHAIN` 을
> "유발 조건 없음" 이라고 적었다. **결론은 맞지만 근거가 부족했다** — 그때는
> 이름만 보고 말했고, §6 이 경고한 바로 그 혼동을 할 수 있는 상태였다. 지금은
> 공존 분포로 측정했다.

---

## §7 — 실제 corpus (효과 블록 34,631개 · 스크립트 있는 카드 12,504장)

| per-effect `SetCode` | 블록 수 | 비율 | 뜻 |
|---|---|---|---|
| `EFFECT_*` | 13,704 | 39.57% | 유발이 아니다 (지속 · 적용) |
| 다른 `EVENT_*` | 11,474 | 33.13% | **유발 있음** (69종) |
| `EVENT_FREE_CHAIN` | 4,909 | 14.18% | **유발 없음 (명시)** |
| `None` | 4,544 | 13.12% | **애매한 통** |

대표 사례:

| Card | Effect | 원본 | `spec.code` | 판정 |
|---|---|---|---|---|
| 욕망의 항아리 55144522 | e1 | `SetCode(EVENT_FREE_CHAIN)` + ACTIVATE | `EVENT_FREE_CHAIN` | **A** |
| 불사무사의 애도 3461403 | e4 | `SetCode(EVENT_PHASE+PHASE_END)` + FIELD,TRIGGER_O | `EVENT_PHASE` | **B** |
| 불사무사의 애도 3461403 | e2 | `SetCode(EFFECT_CHANGE_RACE)` | `EFFECT_CHANGE_RACE` | 유발 아님 |
| **언데드 월드 4064256** | e5 | **`SetCode(id)` 가 있다** | **`None`** | **D (미기록)** |
| **플레이트 크래셔 114932** | e1 | **`SetCode` 자체가 없다** | **`None`** | 해당 없음 |

---

## §8 — Semantic Collapse: **YES, 그리고 측정됐다**

`code is None` 의 정체를 원문과 대조했다 (카드 단위).

| | 카드 수 |
|---|---|
| 전부 읽었다 | 8,551 |
| `SetCode` 자체가 없는 효과가 있다 (해당 없음) | 3,791 |
| **`SetCode` 가 있는데 못 읽은 것이 있다 (D)** | **162** |

읽지 못하는 모양: `SetCode(id)` (카드 자신의 커스텀 이벤트) ·
`SetCode(1082946)` (숫자 setcode) 등. 파서는 `EVENT_*` → `EFFECT_*` 순으로
찾고 둘 다 아니면 **아무것도 적지 않는다** — "없었다" 와 같은 값이 된다.

**실제 문제인가: 지금은 NO.** 아래 §9 가 이유다. 그러나 `code is None` 을
"유발 조건이 없다" 로 읽기 시작하는 날 **162장이 조용히 틀린다.**

---

## §9 — Engine 영향: 지금은 필요하지 않다

등재된 **16개 효과 전부**가 `EVENT_FREE_CHAIN` + `EFFECT_TYPE_ACTIVATE` 다.
유발 이벤트를 쓰는 효과가 **한 건도 없다.**

```
55144522 욕망의 항아리   EVENT_FREE_CHAIN  ACTIVATE
 5318639 싸이크론        EVENT_FREE_CHAIN  ACTIVATE
 5915629 욕망의 선물     EVENT_FREE_CHAIN  ACTIVATE
 …                      (16/16 동일)
```

그래서 collapse 가 **어떤 판정에도 쓰이지 않는다.** `_OUT_OF_SCOPE_TYPES` 가
함정 전체를 막고 있고(Phase 3-E-16), 엔진은 유발 필드를 읽지도 않는다.

→ **ENGINE CHANGE = NO.** 유발 효과가 하나라도 등재되는 날 `test_09` 가 깨지고,
그때 다시 읽어야 한다.

---

## §17 — 질문에 대한 답

| | 답 |
|---|---|
| Q1 "유발 없음" 과 "유발 정보 없음" 을 구분할 수 있는가 | **부분적으로.** "없음"(`EVENT_FREE_CHAIN`)은 구분된다. "정보 없음"과 "해당 없음"은 **구분되지 않는다** |
| Q2 실제 corpus 에서 문제가 되는가 | **162장**에서 값이 거짓말을 한다. 다만 지금 읽는 곳이 없다 |
| Q3 Engine 이 지금 알아야 하는가 | **아니다** — 등재 16개 전부 `EVENT_FREE_CHAIN` |
| Q4 EffectDefinition schema 변경이 필요한가 | **지금은 아니다** |
| Q5 필요하다면 어느 계층인가 | **파서**("읽지 못했다" 를 적을 자리) 와 **전사 규칙**(`library.py`). `EffectDefinition` 은 그 다음이다 |
| Q6 지금 해결하지 않아도 되는 이유 | 읽는 곳이 없어 틀린 동작이 없고, 고치려면 파서 schema 와 전사 16건을 함께 손대야 한다 — Phase 하나의 몫이다 |

---

## §10~§13 — 경계와 불변

| | 결과 |
|---|---|
| `GameStateView` 변경 | **0** (`CardDefinitionView` · `GameStateView` 에 유발 필드 없음) |
| Hidden info leak | **0** — 상대 세트 카드는 정체도 정의도 `None` |
| Evaluation 변경 | **0** (`agent/` 에 유발 관련 이름 0건) |
| Search ranking / candidate | **0** — 이 Phase 는 판정에 쓰이는 값을 건드리지 않았다 |
| STRUCTURAL-34 | 건드리지 않았다 |
| `SET_ACTIVATION_*` TODO | 자동 해결하지 않았다 |

---

## §19 — 성능

전체 테스트 **365s → 343s** (신규 14개를 더했는데도 줄었다 — 측정 편차 범위이고
regression 이 아니다). 파서 · analysis · 정의 생성 경로는 한 줄도 바뀌지 않았다
(설명만 바뀌었다).

---

## §14 — Production 변경: 설명 세 곳

측정된 의미와 어긋나 **거짓 추론을 허용하던** 문구만 고쳤다. 동작 변화 0.

| 파일 | 고친 설명 |
|---|---|
| `core/card_model.py` `EffectSpec.code` | `None` 이 "부재" 와 "읽지 못함" **둘**을 뜻한다는 것, 그래서 "유발 없음" 을 뜻하는 값은 `None` 이 아니라 `"EVENT_FREE_CHAIN"` 이라는 것 |
| `core/card_model.py` `LuaScriptInfo.trigger_events` | **유발 목록이 아니다** — 파일 전체 정규식이고 `EVENT_FREE_CHAIN` 도 섞인다 |
| `analysis/effect_model.py` `EffectAnalysis.trigger_event` | `is not None` 을 "유발 효과다" 로 읽지 말 것, `None` 이 세 가지의 합이라는 것, 조건 쪽과의 비대칭 |

---

## §15 · §16 — 테스트

### 전체

```
3528 passed, 4 skipped in 343.40s
```

기준선 3514 + 신규 14 = 3528. 실패 0 · 삭제 0 · skip 증가 0.

신규 `tests/test_trigger_semantics_audit.py` — **14개**

1. `EVENT_FREE_CHAIN` 이 구문으로는 유발 이벤트와 구분되지 않는다 (공식 상수에서 읽는다)
2. 그런데 `TRIGGER_O` · `TRIGGER_F` 와 **한 번도** 같이 쓰이지 않는다 (전수)
3. 원본에서 A 와 B 는 구분된다
4. **`None` 이 D 와 "해당 없음" 을 합친다** (두 실제 카드로)
5. **파서를 직접 돌려** 그 이유를 고정한다 (캐시를 우회한다)
6. `trigger_events` 는 유발 목록이 아니다
7. 실제 카드에서 섞인다
8. **변환기가 없다** — `EffectDefinition(` 은 한 곳, 엔진은 읽지 않는다 (AST)
9. **등재 16개 전부 `EVENT_FREE_CHAIN`** — 지금 필요하지 않다
10. 조건 쪽은 "못 읽었다" 를 말할 수 있고 유발 쪽은 못 한다 (비대칭)
11. **§16-C** `EVENT_FREE_CHAIN` 을 유발로 읽으면 16개 전부가 못 쓰게 된다
12. **§16-A · B** "정보 없음" → "유발 없음" 변환이 production 에 없다
13. **§16-D** 유발 메타데이터가 관측으로 나가지 않는다
14. 평가 · 탐색이 이 값을 읽지 않는다

### 고의 위반 4건 — 전부 잡힘

| 위반 | 잡은 시험 |
|---|---|
| A 읽지 못한 `SetCode` 를 `EVENT_FREE_CHAIN` 으로 메꾼다 | `test_05` — **처음엔 못 잡았다** |
| B analysis 가 `not trigger_event` 를 "유발 없음" 으로 쓴다 | `test_12` |
| C 엔진이 유발 필드를 읽기 시작한다 | `test_08` |
| D 관측에 유발 메타데이터를 노출한다 | `test_13` |

**A 를 처음에 아무 테스트도 잡지 못했다.** `CardRepository` 가 `data/cache` 에
파싱 결과를 캐시하므로, 캐시된 카드로 재면 **파서가 바뀌어도 테스트가 알지
못한다.** 그래서 `test_05` 를 `parse_lua_source` 를 직접 부르는 쪽으로 다시
썼고, 재주입해서 잡았다. 숨기지 않고 적는다 — 리포지토리를 거치는 테스트는
파서 변경을 감시하지 못한다.

### 수정 · 삭제 · skip

- 수정한 기존 테스트: **0**
- 삭제: **0** · skip 증가: **0** · assertion 약화: **0**

---

## §13 — STRUCTURAL 상태

34 유지 · 124 유지 · 128 유지 · 131 유지 · 133 유지 · 134 RESOLVED 유지 ·
`SET_ACTIVATION_MISSING` RESOLVED 유지.

| | 상태 |
|---|---|
| `SET_ACTIVATION_TIMING` | 열려 있음 (기회를 여는 자리 — STRUCTURAL-34 나머지) |
| `SET_ACTIVATION_EXECUTION` | 함정에 대해서는 이미 있음 (Phase 3-E-16) |
| `SET_CARD_EFFECT_EXECUTION` | 열려 있음 (조작 관문 · 다리의 다중 선택) |

---

## §14 — 신규 문제

**새 STRUCTURAL ID 를 만들지 않았다.** "미래에 필요할 것 같다" 는 이유로는
만들지 않는다는 §18 을 따랐다 — 지금 틀린 동작이 없다.

기록만 남긴다.

1. **파서가 "읽지 못한 `SetCode`" 를 적지 않는다** — 162장. 증거는 §8 과
   `test_04` · `test_05`. 지금 해결하지 않은 이유: 읽는 곳이 없어 틀린 동작이
   없고, 고치려면 `EffectSpec` 의 모양을 바꿔야 한다 (조건 쪽의
   `unparsed` · `raw` 와 같은 짝을 유발 쪽에도 두는 일).
2. **`trigger_events` 라는 이름이 내용과 다르다** — 이름을 바꾸는 것은 공개
   필드 변경이므로 §14 가 허용하지 않는다. 설명으로 막아 두었다.

---

## §15 — 다음 Phase 후보 (하나)

**파서가 "SetCode 를 읽지 못했다" 를 적게 하는 일** — 조건 쪽이 이미 하고 있는
것을 유발 쪽에도 두는, 대칭을 맞추는 변경이다.

이번 감사가 범위를 좁혀 두었다.

- 고칠 자리는 **`sources/lua_loader.py` 의 `elif setter == "Code":` 분기 하나**와
  `EffectSpec` 의 필드 하나다. `EffectDefinition` 은 **건드리지 않는다** —
  엔진이 그 값을 읽지 않으므로 지금 추가할 이유가 없다.
- 본보기가 있다: `ActivationCondition` 의 `has_condition_function` · `unparsed` ·
  `raw`. 같은 모양으로 적으면 새 개념을 만들지 않는다.
- 측정 대상이 정해져 있다: **162장**. 고친 뒤 그 수가 0 이 되는 것이 아니라,
  "읽지 못했다" 로 **분류되는** 것이 성공이다 — 읽어내는 것은 다른 일이다.

첫 질문: **`SetCode(id)` 와 `SetCode(1082946)` 를 "읽지 못했다" 로 묶을지,
아니면 "카드 자신의 커스텀 이벤트" 와 "숫자 setcode" 로 나눌지.** 전자는
정직하고 후자는 더 쓸모 있지만 EDOPro 의 의미를 더 많이 전사해야 한다. 그
선택이 그 Phase 의 범위를 정한다.
