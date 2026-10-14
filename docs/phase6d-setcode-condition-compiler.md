# Phase 6-D — 카드군 조건 컴파일러 연결 및 IsSetCard 판정 개선

> 요약: Phase 6-C 가 조건(`IsSetCard`)을 만들고 **그것을 채우는 코드는 일부러
> 두지 않았다** (쓰는 자리가 없었으므로). 이번 단계가 그 자리를 만들었다 —
> `analysis` 가 읽어 둔 **이름** 507개 중 **504개**가 숫자 코드가 되고, 조건
> **8,565개**가 엔진 조건으로 옮겨진다 (이전 **0개**). 남은 3개 이름은
> **추측하지 않고 `UNKNOWN` 으로 유지한다.**
>
> 🔴 가장 중요한 결과는 통과한 수가 아니다. ① 못 옮긴 이름을 **버리지 않아서**
> 그 카드군의 카드가 `FALSE` 가 되지 않는다 ② 615개 카드군 전수 검사에서
> **거짓 양성 0건** ③ 조사 중에 **조용히 사라지던 카드군 요구 18건**을
> 찾아서 `UNKNOWN` 으로 드러냈다 ④ 검색용 `by_setcode()` 의 계약은
> **건드리지 않았다.**

---

## 1. 기존 카드군 정보의 전체 전달 경로

```
data/cards.cdb   datas.setcode (64비트 = 16비트 × 4)
    │  sources/official_db.py::unpack_setcodes
    ▼
core.card_model.Card.setcodes : list[int]          ← 숫자. 카드가 속한 카드군
    │
    ├─▶ core.card_repository
    │     ._by_setcode : dict[int, list[int]]      ← **정확 일치** 색인
    │     .by_setcode(code) / .archetype(key)      ← 검색 · 덱 빌더가 쓴다
    │
    ├─▶ engine.game_state_view.CardDefinitionView.setcodes : tuple[int, ...]
    │     │  engine.condition.IsSetCard  (Phase 6-C)
    │     ▼  engine.archetype.matches_setcode       ← 판정 규칙 한 곳
    │        TRUE / FALSE / UNKNOWN
    │
    └─▶ analysis.effect_analyzer
          ├ CardAnalysis.setcodes : list[str]      ← 카드 **자신**의 카드군 (이름)
          └ CardConstraint.setcodes : list[str]    ← 필터가 **요구**하는 카드군
                │                                     (이름, SET_ 접두사 제외)
                ▼  🔴 Phase 6-C 까지 여기서 끊겨 있었다
          engine.archetype_compiler.compile_archetype_condition   ← **이번 단계**
                │  engine.vocabulary.EngineVocabulary.archetypes
                ▼  (data/constants/archetype_setcode_constants.lua)
          engine.condition.IsSetCard / ArchetypeUnresolved / UnimplementedRule
                ▼
          CandidateSource(require=…) → CandidateResolver
                ▼
          eligible / undecided / unchecked
```

### 🔴 이름이 같은 **다른 칸** 셋을 구분한다

| 칸 | 타입 | 뜻 |
|---|---|---|
| `Card.setcodes` | `list[int]` | 이 카드가 **속한** 카드군 (숫자) |
| `CardAnalysis.setcodes` | `list[str]` | 같은 것을 **이름으로** 적은 것 |
| `CardConstraint.setcodes` | `list[str]` | 필터가 **요구하는** 카드군 (이름) |

컴파일러의 입력은 **세 번째**다. 첫째는 판정의 대상이고, 둘째는 표시용이다.

---

## 2. `CardConstraint.setcodes` 와 `IsSetCard` 의 실제 데이터 계약

```python
# analysis/effect_model.py:113
setcodes: list[str]      # SET_* 카드군 이름 (접두사 제외). 예: ['ORCUST']

# engine/condition/model.py — IsSetCard (Phase 6-C)
setcodes: tuple[int, ...]  # 숫자 코드. 예: (0x11b,)
```

**가변 list[str] ↔ 불변 tuple[int].** 둘 사이에 공통 타입이 없고, 그래서
연결이 끊겨 있었다.

전수 측정 (`c*.lua` 12,968개):

| | 수치 |
|---|---:|
| `IsSetCard` 호출 | **7,451** |
| ↳ `SET_` 이름 하나 | 7,300 |
| ↳ `SET_` 이름 여럿 (`{A,B}`) | 139 |
| ↳ 인자가 **런타임 변수** | **12** |
| ↳ 숫자 코드(`0x…`) 리터럴 | **0** |
| ↳ `+` · `\|` 로 코드를 **결합** | **0** |
| 카드군 요구가 있는 `CardConstraint` | **8,633** |
| 카드군 조건을 가진 카드 | **3,499** |
| 서로 다른 카드군 이름 | **507** |

🔴 **숫자 리터럴이 0개이고 비트 결합이 0개**라는 것이 두 가지를 말해 준다.
① 분석기의 `SET_(\w+)` 정규식이 숫자 때문에 놓치는 것은 없다. ②
`IsSetCard({A,B})` 의 목록은 **순수한 OR** 이고, 한 인자 안에서 코드를 합치는
의미론은 실제 데이터에 **없다**. Phase 6-C 가 "하나라도 맞으면 참" 으로
구현한 것이 맞았다.

---

## 3. 기존 카드군 변환이 실패한 정확한 원인

**변환 코드가 아예 없었다.** 거절하거나 누락하는 자리가 있었던 것이 아니다.

Phase 6-C 보고서가 그 사실을 세 가지로 재서 고정해 두었고
(`test_c_nothing_turns_an_archetype_name_into_a_condition`), 이번 단계가 그
셋 중 둘을 뒤집었다.

| 6-C 가 고정한 사실 | 6-D 결과 |
|---|---|
| 표에는 이름이 다 있다 (`ScriptConstants.setcode("ORCUST") == 0x11b`) | **그대로** |
| `EngineVocabulary` 가 `SET_` 묶음을 내보내지 **않는다** | 🔴 **뒤집힘** — `archetypes` 묶음 추가 (615개) |
| production 에 `IsSetCard` 를 **만드는 자리가 없다** | 🔴 **뒤집힘** — 딱 한 곳 (`engine/archetype_compiler.py`) |

`EngineVocabulary` 만 비어 있던 이유도 측정으로 확인했다 —
`ScriptConstants` 가 `SET_*` 를 `others` 와 **따로** 모아 두는데
(`script_constants.py:104-108`), `EngineVocabulary` 의 묶음들은 전부
`others` 에서만 만들어진다. 그래서 다른 다섯 묶음은 채워지고 카드군만
빠졌다.

---

## 4. 채택한 최소 연결 방식과 대안 비교

### 🔴 첫 구현이 ADR-007 지뢰선을 밟았다 — 그리고 그것이 옳았다

처음에는 `engine/archetype_bridge.py` 를 만들고 `CardConstraint` 를
`TYPE_CHECKING` 으로만 가져왔다. 런타임에는 아무것도 새지 않는다. 그런데
`tests/engine/test_phase2_contracts.py::test_contract_h_engine_borrows_exactly_
one_symbol_from_analysis` 가 발화했다.

```
engine 이 analysis 에서 ['CardConstraint', 'LimitScope'] 를 가져옵니다.
ADR-007 은 LimitScope 하나만 허용합니다.
```

그 테스트의 docstring 이 이유를 적어 두었다 — *"이 목록이 늘어나면 분석
데이터가 실행 경로로 새어 들어오고 있다는 신호다. 늘리려면 ADR-007 을 먼저
고쳐야 한다."* 그래서 ADR-007 을 고치지 않고 설계를 바꿨다.

| 대안 | 장점 | 왜 택하지 않았나 |
|---|---|---|
| **A. `engine/` 안의 다리가 `CardConstraint` 를 받는다** | 호출이 한 줄 (`compile(constraint)`) | 🔴 ADR-007 을 수정해야 하고, 다음 사람이 같은 자리에 **두 번째** 분석 타입을 들여올 명분이 생긴다 |
| **B. `analysis/` 에 둔다** | 입력 타입이 자기 집 | 🔴 `analysis → engine` 역방향 의존. "분석이 실행을 낳지, 실행이 분석을 바꾸지 않는다" 를 깬다 |
| **C. 새 최상위 패키지** | 양쪽 다 받을 수 있다 | 패키지 하나를 모듈 하나 때문에 만든다. §12 "변경을 위한 변경" |
| **D. ✅ 문자열과 숫자만 받는다** | ADR-007 **그대로**, 역의존 없음, 새 패키지 없음 | 호출이 두 줄이 된다 (아래) |

채택한 D의 호출 모양:

```python
from engine.archetype_compiler import (
    compile_archetype_condition, unread_archetype_calls,
)

compile_archetype_condition(
    constraint.setcodes,
    unread=unread_archetype_calls(constraint.raw_predicates),
)
```

`engine` 이 `analysis` 에서 가져오는 이름은 여전히 `LimitScope` **하나**다
(신규 테스트 `test_f_the_engine_still_borrows_exactly_one_symbol_from_analysis`
가 고정).

### 결과 객체가 `Optional` 이 아닌 이유

카드군 요구가 없으면 `compile_archetype_condition` 이 **`None`** 을 돌려주고,
결과 객체를 **만들지 않는다.** `ArchetypeCompilation.condition` 은 그래서
`Condition` 이고 `Condition | None` 이 아니다.

근거는 이 저장소의 감사 하나가 이미 적어 둔 것이다 — Phase 3-E-34 는
`engine/` 의 `Condition | None` 칸 5곳이 **서로 다른 뜻**을 갖는다는 것을
재고, §7 에서 *"부재를 `None` 없이 적는 설계가 이미 두 개 있다"* 고 적었다
(`Requirement.condition` 은 조건이 없으면 `Requirement` 자체를 안 만든다).
같은 선택을 했고, 그 감사의 `CONDITION_OPTIONAL_FIELDS` 는 **5곳 그대로**이며
`CONDITION_REQUIRED_FIELDS` 가 4 → 5곳이 되었다.

---

## 5. 변경한 파일 및 함수

| 파일 | 변경 | 줄 |
|---|---|---|
| `engine/archetype_compiler.py` | **신규** — `compile_archetype_condition` · `unread_archetype_calls` · `ArchetypeCompilation` | +247 |
| `engine/condition/model.py` | `ArchetypeUnresolved` 조건 추가 | +77 / −0 |
| `engine/condition/__init__.py` | 재노출 | +2 / −0 |
| `engine/vocabulary.py` | `EngineVocabulary.archetypes` 묶음 (615개) | +17 / −1 |
| `analysis/effect_analyzer.py` | `_record_unread` — 읽지 못한 `IsSetCard` 의 흔적 | +29 / −2 |
| `tests/engine/test_archetype_compiler.py` | **신규** 회귀 테스트 40개 | +767 |
| `tests/engine/test_archetype_condition.py` | 🔴 6-C 가 심은 지뢰선 `test_c` 를 새 사실로 교체 | +31 / −23 |
| `tests/test_engine_condition_none_contract_audit.py` | 파일 수 66→67 · 비-Optional 집합 4→5 | +12 / −1 |
| `tests/test_event_context_audit.py` | 조건 어휘 인구조사 (자리표시자 쪽) | +15 / −2 |
| `tests/test_unimplemented_rule_semantics_audit.py` | 생성 2→3 · override 7→8 · 🔴 **배수는 유지** | +54 / −7 |

`data/` 는 **한 바이트도 바뀌지 않았다.** Lua 파일도 그대로다.

---

## 6. 카드군 이름과 숫자 코드의 매핑 근거

**근거는 단 하나다** — `data/constants/archetype_setcode_constants.lua`.
Project Ignis CardScripts 의 상수 정의이고, 카드 스크립트가 `IsSetCard` 에
넘기는 바로 그 이름이다. `ScriptConstants` 가 읽어 두었고
`EngineVocabulary.archetypes` 가 **감싸기만** 한다.

| | 수치 |
|---|---:|
| `SET_*` 상수 | **615** |
| 카드가 실제로 들고 있는 서로 다른 코드 | 615 |
| ↳ 상수 이름이 있는 코드 | 605 |
| ↳ 이름이 **없는** 코드 | **10** |
| 한 코드에 이름이 **둘**인 묶음 | **1** (`SET_POLYMERIZATION` = `SET_FUSION` = `0x46`) |
| 스크립트가 쓰는 이름 507개 중 해결 | **504** |
| ↳ 미해결 | **3** (`CENTURION` · `DRAGONTAIL` · `DIABELLESTARR`) |

### 🔴 미해결 3개를 추측으로 채우지 않았다

그 세 이름을 쓰는 카드들은 **코드를 들고 있다** — 센츄리온 카드는 `0x19b`,
드래곤테일은 `0x1c0`, 디아벨스타는 `0x204` 다. 그러니 "그 이름을 쓰는
스크립트의 카드들이 공통으로 들고 있는 코드" 를 역산해서 채울 수 **있었다.**

하지 않았다. 지시서 §3-4 · §5 가 금지하는 바로 그 추측이고, 역산이 맞는지
확인할 **공식 근거가 없다.** 상수 파일이 그 카드군보다 오래된 스냅숏인 것이
원인이므로, 풀리는 방법은 **데이터 갱신** 하나다 (§13 TODO).

### 🔴 역조회로 이름을 정규화하지 않는다

`ConstantGroup` 은 한 코드에 이름이 여럿이면 먼저 들어온 하나만 대표로
들고 있다. 그런 묶음이 실제로 **하나 있으므로**, 역조회로 정규화하면
`SET_POLYMERIZATION` 이 `SET_FUSION` 으로 바뀐다. 컴파일러는 접두사만 떼고
**스크립트가 적은 이름을 그대로** 남긴다.

---

## 7. `IsSetCard` 의미론과 `by_setcode()` 의 차이

🔴 **둘은 다른 질문이고, 같은 답을 강요하지 않았다.**

```
by_setcode(code)    정확 일치 — code in card.setcodes
IsSetCard(code)     하위 12비트 일치 + 질의한 상위 4비트 포함
```

전수 측정 (615개 카드군 × 14,127장):

| | 수치 |
|---|---:|
| `IsSetCard` 가 더 넓은 카드군 | **78 / 615** |
| ↳ 그 78개의 합계 | **1,880 → 3,008장 (+1,128)** |
| 차이가 없는 카드군 | 537 |
| **base 가 다른데 걸린 사례 (거짓 양성)** | **0** |
| 정확 일치가 포함관계를 벗어난 사례 | **0** |

가장 크게 벌어지는 자리:

```
SET_HERO                by_setcode    6 → IsSetCard  159  (+153)
SET_GLADIATOR                        6 →             53  (+47)
SET_ROID                            33 →             77  (+44)
SET_DD                              31 →             69  (+38)
SET_SYNCHRO                         39 →             76  (+37)
```

**검색의 의미론은 바꾸지 않았다.** `by_setcode` 는 여전히 정확 일치이고,
`/search` · `/deck` 의 출력이 달라지지 않는다 (Phase 6-C 보고서 §12 가
기록한 TODO 는 그대로 열려 있다). 신규 테스트
`test_f_by_setcode_still_means_exact_match` 가 **두 수를 함께** 고정한다 —
`SET_HERO` 로 `by_setcode` 는 6장, `IsSetCard` 는 159장.

---

## 8. 지원하게 된 조건과 여전히 지원하지 않는 조건

### 지원

- **카드군 이름 → 숫자 코드 → `IsSetCard`** (504개 이름).
- **목록 조건** `IsSetCard({A,B})` → 코드 여럿을 가진 `IsSetCard` 하나.
- **계층 조건** — `SET_HERO` 로 물으면 엘리멘틀/데스티니 히어로가 걸린다.
- **복합 소속** — 한 카드가 카드군 여럿에 속할 때 각각 정확히 답한다.
- **부분 해결** — `Or(IsSetCard(해결), ArchetypeUnresolved(미해결))`.
- **3치 전파** — `And` · `Or` · `Not` 에서 `UNKNOWN` 이 접히지 않는다.
- **후보 거르기** — `CandidateSource.require` 에 그대로 들어간다.

### 지원하지 않음 (측정된 범위)

| 조건 | 수 | 왜 |
|---|---:|---|
| 상수 표에 없는 이름 | 조건 47 + 부분 3 · 이름 3 | 데이터 갱신이 필요하다 → `ArchetypeUnresolved` |
| 인자가 런타임 변수인 호출 | 조건 18 · 카드 6장 | Lua 분석이 변수를 따라가야 한다 → `UnimplementedRule` |
| `CardConstraint` 의 **나머지 축** | — | 종족 · 속성 · 레벨 · 카드 종류 · 카드 ID. 각자 조건이 필요하고 이번 범위가 아니다 |
| 효과로 **더해지는** 카드군 | — | 지속 효과 계층이 없다 (STRUCTURAL-76) |

🔴 **이 함수의 결과를 "이 필터를 전부 옮겼다" 로 읽으면 안 된다.** 옮긴
것은 **카드군 한 축**이고, 모듈 설명에 그 경계를 적어 두었다.

---

## 9. `STRUCTURAL-77` 관련 전후 측정

| 측정 항목 | 구현 전 | 구현 후 |
|---|---:|---:|
| 엔진 조건으로 **옮긴** 카드군 조건 | **0** | **8,565** (완전) + **3** (부분) |
| 옮기지 못한 조건 — 코드 없음 | 8,615 (전부) | **47** |
| 옮기지 못한 조건 — 이름 미독 | **0** (흔적조차 없었다) | **18** |
| 카드군 요구가 없는 조건 | 16,963 | 16,963 |
| 해결된 서로 다른 이름 | 0 | **504 / 507** |
| 카드군 조건을 가진 카드 | 3,494 | **3,499** |
| 🔴 거짓 양성 (다른 base 가 걸림) | — | **0 / 615 카드군 전수** |

### 🔴 "0 → 18" 이 **나빠진 것이 아니다**

구현 전의 0 은 "그런 조건이 없다" 가 아니라 **"흔적조차 남지 않았다"** 였다.
`IsSetCard(setcode)` 처럼 인자가 런타임 변수면 분석기가 이름을 하나도 못
읽고, `setcodes == []` 과 `raw_predicates == []` 로 끝났다. 그러면 그 조건은
**"카드군 요구가 없다"** 와 **구별되지 않고**, 그 필터를 쓰는 쪽이 **모든
카드를 통과시킨다.** 거짓 양성의 교과서적 사례다.

`analysis/effect_analyzer.py::_record_unread` 가 그것을 드러냈다.
`CardConstraint.raw_predicates` 의 docstring 이 원래 *"읽어내지 못한 조건은
raw_predicates 에 원문 그대로 남는다"* 라고 적어 두었는데, **그 칸에 쓰는
자리가 저장소 전체에 하나도 없었다** (grep 결과 선언 한 줄과 설명 두 줄
뿐). 카드군 조건에 한해 그 계약을 지켰다 — 다른 술어까지 채우는 것은 이번
범위가 아니다 (§13 TODO).

### 차단 사례가 줄었다는 주장은 하지 않는다

Phase 6-C 가 `Card.IsSetCard` 를 커버리지 분류의 병목에서 이미 뺐고
(368 → 516장), 그 수는 이번 단계에서 **움직이지 않는다.** 이번 단계가 바꾼
것은 "담을 수 있다" 가 아니라 **"손으로 적지 않고도 옮길 수 있다"** 다.
등재(`EFFECT_LIBRARY`)는 **16개 그대로**이고, 신규 테스트가 그것도 고정한다.

---

## 10. 오르페골 대표 시나리오 테스트 결과

| 항목 | 결과 |
|---|---|
| CDB 숫자 코드 | `SET_ORCUST = 0x11b` (상수 표와 일치) |
| 기르수(69811710)의 소속 | `(0x11b, 0x10c)` = 오르페골 **+ 잭나이츠** |
| 롱기르수(76145142) | `(0x11b,)` = 오르페골만 |
| 이름 → 조건 | `["ORCUST"]` → `IsSetCard((0x11b,))`, `is_complete = True` |
| 속하는 카드 | 기르수 `TRUE` · 롱기르수 `TRUE` |
| 속하지 않는 카드 | 페더맨 `FALSE` · 라바 골렘 `FALSE` |
| 둘째 카드군 | 기르수 `MEKK_KNIGHT` `TRUE` / 롱기르수 `FALSE` (거짓 양성 아님) |
| 속하지 않는 카드군 | 기르수 `WORLD_LEGACY` **`FALSE`** — ①이 **찾는** 카드군이지 속한 카드군이 아니다 |
| 기르수 ①의 실제 필터 | `IsSetCard({SET_ORCUST,SET_WORLD_LEGACY})` → `IsSetCard((0x11b, 0xfe))`, 완전 해결 |
| 후보 거르기 | `require=` 에 넣으면 패에서 기르수 · 롱기르수만 `eligible` |
| 데이터 누락 시 | `["ORCUST","CENTURION"]` → 기르수 `TRUE`, **페더맨 `UNKNOWN`** (`FALSE` 아님) |

특정 오르페골 카드만 통과하는 분기는 **없다.** 테스트가 쓰는 것은 이름과
상수 표뿐이고, 카드 ID 는 "어느 카드로 쟀는지" 를 적는 데만 쓴다.

---

## 11. 데이터 호환성과 EventJournal 회귀

| 요소 | 영향 |
|---|---|
| `data/cards.cdb` · `data/ko/` · `data/constants/` | **없음.** 읽기만 한다 |
| `c*.lua` 12,968개 | **없음.** 파서(`sources/lua_loader.py`)를 건드리지 않았다 |
| Lua 파싱 캐시 서명 | **올릴 이유가 없다** — `lua_loader` 가 그대로다 |
| 카드 효과 분석 결과 | `CardConstraint.raw_predicates` 에 **18건**이 새로 남는다. `setcodes` · `races` · `attributes` · `levels` · `card_types` 는 **불변** |
| 증분 업데이트 파이프라인 | **없음.** 새 필드 0개 |
| CDB · Lua 부분 가용성 | **유지.** 상수 파일이 없으면 `archetypes` 가 빈 묶음이 되고, 모든 이름이 `ArchetypeUnresolved` 가 된다 — 조용히 참이 되지 않는다 (테스트가 빈 표로 그 경로를 재현한다) |
| 카드 검색 · 덱 빌더 | **없음.** `by_setcode` 계약 불변 |
| **EventJournal (Phase 6-B)** | **없음.** `journal.py` · `action_execution.py` · `spell_activation.py` · `duel.py` · `agent/simulation.py` 를 한 줄도 건드리지 않았다. 조건은 판을 **읽기만** 하므로 기록할 변화를 만들지 않는다 (`test_h_compiling_and_evaluating_do_not_touch_the_board` 가 `state_hash()` 불변을 고정) |

```
$ python3 -m pytest tests/engine/test_event_journal_integration.py -p no:randomly -q
14 passed
```

---

## 12. 전체 관련 테스트 통과 · 실패 · 건너뜀 수

| 범위 | 명령 | 결과 |
|---|---|---|
| 엔진 전체 | `pytest tests/engine -p no:randomly -q` | ✅ **2,930 passed** (1:26) |
| ↳ 이번 Phase 이전 | 같은 명령 | 2,890 passed |
| 신규 컴파일러 | `pytest tests/engine/test_archetype_compiler.py` | ✅ **40 passed** |
| 6-C 카드군 모델 회귀 | `pytest tests/engine/test_archetype_condition.py` | ✅ 48 passed (`test_c` 교체 후) |
| EventJournal (6-B) | `pytest tests/engine/test_event_journal_integration.py` | ✅ 14 passed |
| `agent`+`rules`+`rulings` | `pytest tests/agent tests/rules tests/rulings` | ✅ **529 passed, 4 skipped** (5:04) |
| 묶음 0 (23파일) | `pytest <23 files>` | ✅ **614 passed** (17:21) |
| 묶음 1 (23파일) | 1차 2 failed → 고친 뒤 | ✅ **587 passed** (7:51) |
| 묶음 2 (23파일) | — | ✅ **559 passed** (14:28) |
| 묶음 3 (22파일) | 1차 3 failed → 고친 뒤 | ✅ **517 passed** (15:37) |

**최종 실패 0건 · 건너뜀 4건** (`tests/rulings` 의 네트워크 의존 테스트,
이번 Phase 와 무관하며 수가 변하지 않았다).

차이 **+40** 은 전부 신규 파일이다 — 삭제 0건 · skip 추가 0건 ·
assertion 약화 0건.

### 밖에서 난 5건은 전부 고정값 이동 (프로덕션 결함 0건)

| 파일 | 테스트 | 움직인 고정값 | 왜 |
|---|---|---|---|
| `test_engine_condition_none_contract_audit.py` | `test_01` | `engine/` 파일 수 66 → **67** | `archetype_compiler.py` 추가 |
| 같음 | `test_02` | 비-`Optional` `Condition` 칸 4 → **5** | 🔴 이 감사가 §7 에서 권한 선례를 따른 결과. `CONDITION_OPTIONAL_FIELDS` 는 **5곳 그대로** |
| `test_event_context_audit.py` | `test_01` | 조건 어휘 인구조사 | `ArchetypeUnresolved` 는 관측을 읽지 않으므로 **자리표시자** 쪽에 센다 |
| `test_unimplemented_rule_semantics_audit.py` | `test_03` | production `UnimplementedRule` 생성 2 → **3** | 읽지 못한 호출에 붙인다 |
| 같음 | `test_05` | `missing_rules` override 7 → **8** | 🔴 **반대 방향의 override** — 규칙 이름을 *내지 않기 위해* 재정의한다 |

### 🔴 `test_03` 의 배수(30)를 **낮추지 않았다**

그 테스트에는 `assert mentions > 30 * PRODUCTION_CONSTRUCTION_COUNT` 가 있고,
생성이 2 → 3 이 되자 `79 > 90` 이 거짓이 되었다. 배수를 25 로 내리는 것이
가장 쉬운 길이었지만 그것은 **threshold 완화**다.

대신 그 비율이 **무엇을 재고 있었는지**를 보았다. 재던 것은 "검증 코드를
내는 자리" 대비 "그 코드의 등장" 이고, 그 모집단은 여전히
`action_validation.py` 의 **두 곳**이다. 이번에 더한 셋째는 **다른 종류**다 —
후보를 거르는 조건에 들어가고 `Requirement` 가 되지 않으므로
`RULE_NOT_IMPLEMENTED` 라는 검증 코드를 **만들지 않는다** (그 파일에 그
이름이 아예 없다는 것을 테스트가 함께 확인한다). 그래서 **배수는 원래
모집단에 그대로 걸고**, 셋째는 따로 센다.

**테스트 통과가 게임 규칙의 완전성을 뜻하지 않는다.** 이 수들은 "이름을
코드로 옮길 수 있고 옮기지 못한 것을 옮기지 못했다고 말한다" 를 확인할
뿐이고, 그 조건을 쓰는 효과가 **실행된다는 뜻이 아니다** (등재 16개 그대로).

### 변이 시험 10종 — 전부 잡힘

| 변이 | 결과 |
|---|---|
| M1 미해결 이름을 **조용히 버린다** | 7 failed |
| M2 읽지 못한 호출을 무시한다 | 3 failed |
| M3 `Or` 대신 `And` 로 묶는다 | 6 failed |
| M4 미해결 이름에 **비슷한 이름의 코드**를 준다 (추측) | 12 failed |
| M5 `ArchetypeUnresolved` 를 `FALSE` 로 | 5 failed |
| M6 `ArchetypeUnresolved` 가 `missing_rules` 를 주장 | 2 failed |
| M7 `archetypes` 를 `others` 에서 찾는다 (출처 혼동) | 18 failed |
| M8 분석기의 흔적 기록을 되돌린다 | 🔴 **처음엔 0 failed** → 시험 보강 후 **2 failed** |
| M9 접두사를 떼지 않는다 | 1 failed |

### 🔴 M8 이 내 시험의 구멍을 찾았다

처음 40개 시험은 `raw_predicates` 를 **손으로 채워** 넣었다. 그래서
`analysis/effect_analyzer.py::_record_unread` 를 통째로 지워도 **전부
통과했다.** 손으로 만든 입력은 컴파일러를 시험하지만, **그 입력이 실제로
생기는지는 시험하지 않는다.**

실제 카드로 가는 시험 3개를 더했다 — `c58811192`(성령수기 키문팔코스)의
`IsSetCard(setcode)` 와 `c81878201`(어비스팅－트리아이나)의
`IsSetCard(s.listed_series)` 가 흔적을 남기는지, 그리고 기르수처럼 이름을
제대로 읽은 블록에는 **흔적이 남지 않는지**(과잉 기록 방지)까지 본다.

### 🔴 내가 쓴 단정 두 개도 틀렸다

1. `And(IsSetCard(WORLD_LEGACY), 부분조건)` 을 `UNKNOWN` 으로 적었다.
   페더맨은 「성유물」이 **아닌 것이 확정**이므로 `And` 의 한쪽이 `FALSE` 이고
   결과는 `FALSE` 다. 바로 위 주석이 그렇게 적혀 있었는데 단정이 반대였다.
2. "이름 순서가 다르면 다른 표현" 이라고 적었다. 컴파일러는 해결된 코드를
   `IsSetCard` **하나로 모으므로** `["CENTURION","ORCUST"]` 와
   `["ORCUST","CENTURION"]` 은 같은 표현이 된다. 그것이 맞는 동작이고
   (`Or` 는 교환 가능하다), 보존되는 것은 **묶음 안의 순서**다.

---

## 13. 남아 있는 구조적 차단 문제

| | 문제 | 측정 | 수정 위치 |
|---|---|---|---|
| 1 | **상수 파일이 오래된 스냅숏** | 이름 3개 · 조건 50개 | `data/constants/archetype_setcode_constants.lua` 갱신. 🔴 데이터 변경이므로 이번 범위 밖 |
| 2 | **Lua 분석이 변수 인자를 못 따라간다** | 호출 12개 · 카드 9장 | `analysis/effect_analyzer.py` — `s.listed_series` 는 `card.script.listed_series` 로 풀 수 있다 (3건) |
| 3 | **`raw_predicates` 가 카드군 말고는 비어 있다** | 선언만 있고 쓰는 자리가 카드군 하나 | 다른 술어도 같은 계약을 지켜야 한다 |
| 4 | 🔴 **`CardAnalysis.setcodes` 가 이름과 hex 를 섞는다** | 코드 10개에 이름이 없어 **48장**이 `"0x14d"` 같은 문자열을 받는다 | `analysis/effect_analyzer.py:272` — 타입으로 구분되지 않는다 |
| 5 | **`by_setcode()` 가 정확 일치** | 78개 카드군 · +1,128장 차이 | `core/card_repository.py:166·478`. 🔴 `/search`·`/deck` 출력이 바뀌므로 **승인 대기** (6-C 보고서 §12) |
| 6 | **효과로 더해지는 카드군을 표현할 수 없다** | — | 지속 효과 계층 (STRUCTURAL-76) |
| 7 | **`CardConstraint` 의 나머지 축에 컴파일러가 없다** | 종족 · 속성 · 레벨 · 종류 · 카드 ID | 같은 모양으로 다섯 개 더 |
| 8 | **등재가 16개** · `TRIGGER_O` 모양 정의 0개 | — | `EFFECT_LIBRARY` |
| 9 | 기르수 일반 소환 `UNDETERMINED` · 제물/특수 소환 절차 없음 | — | 6-C 보고서 §12 그대로 |

---

## 14. Phase 6-E 에서 우선 해결할 항목

🔴 **이제 선행 조건이 없다.** 6-B(기록) · 6-C(조건) · 6-D(컴파일러)가 모두
끝났으므로, 다음 단계는 **등재** 하나다.

### 권장 범위 — `TRIGGER_O` 효과 정의의 첫 사례

1. **목표**: `EFFECT_LIBRARY` 에 `TRIGGER_O` 모양 정의 **1개**. 16/16 이
   `ACTIVATE` 이므로 **모양 자체가 처음**이다.
2. **실제 카드**: 기르수 ① — `EVENT_SUMMON_SUCCESS` 에 반응해 덱에서
   `IsSetCard((0x11b, 0xfe))` 를 만족하는 1장을 묘지로. 🔴 **그 필터를 이제
   손으로 적지 않아도 된다** — 이것이 이번 단계의 결과다.
3. **선행 위험**: 몬스터 효과 스펠 스피드가 `UNKNOWN` 이다
   (`activation_timing.py:33-69` 의 입도 불일치 — `speed_of_link` 가
   `effect_ref` 를 들고 있는데 버리고 카드 단위로 묻는다). 그 한 줄을 6-E 의
   선행 과제로 분리할 가치가 있다.
4. **완료 판정**: 등재된 유발 효과가 ① 사건에 반응해 후보가 되고 ② 조건이
   `FALSE` 면 후보가 **안 되고** ③ `UNKNOWN` 이면 체인에 **안 올라가고**
   그 이유가 기록으로 남는다.
5. **함께 할 만한 작은 것**: 위 §13-2 의 `s.listed_series` 3건은 데이터가
   이미 있으므로 추측 없이 풀 수 있다.

🔴 **Phase 6-E 를 자동으로 시작하지 않는다.** 사용자 검토를 기다린다.

---

## 15. Git 커밋 및 푸시 결과

브랜치 `claude/pensive-goodall-te1egy` 에만 올렸다. 기존 커밋을 amend ·
rewrite · force push 하지 않았다.

| 커밋 | 내용 |
|---|---|
| `4231800` | 프로덕션 — `archetype_compiler.py` · `ArchetypeUnresolved` · `EngineVocabulary.archetypes` · `_record_unread` |
| `b86e43c` | 회귀 테스트 40개 + 움직인 고정값 5건 |
| (아래) | 이 보고서 |

---

## 결론 — 다음 단계가 활용할 수 있는 인터페이스

```python
from engine.archetype_compiler import (
    compile_archetype_condition,   # 이름 목록 → 조건 (또는 None)
    unread_archetype_calls,        # 읽지 못한 호출 골라내기
)
from engine.condition import IsSetCard, ArchetypeUnresolved, And, Or, Not
from engine.vocabulary import default_vocabulary   # .archetypes (615개)
```

- 이름을 **옮길 수 있고**, 옮기지 못한 것이 무엇인지 **말할 수 있다.**
- 옮기지 못한 것은 **거짓이 되지 않는다** — 그것이 이 단계의 핵심이다.
- 거짓 양성이 **0건**임을 615개 카드군 전수로 확인했다.
- 검색의 의미론은 **그대로**다.
- 🔴 **아직 못 하는 것**: 상수 표에 없는 이름 3개 · 변수 인자 12건 ·
  나머지 조건 축 다섯 · 효과로 더해지는 카드군 · 유발 효과 등재.

카드군 조건을 더 많이 통과시킨 것이 아니라, **근거가 있는 것만 통과시키고
나머지를 "모른다" 로 남겼다.**
