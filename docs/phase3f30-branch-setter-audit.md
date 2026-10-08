# Phase 3-F-30 — Lua 분기 내부 설정자(`SetCategory` / `SetTargetRange`) 누적·분기 의미 감사

**최종 판정: D. REPRESENTATION_LIMITATION**

**production 수정 없음.**

---

## 1. 실제 HEAD / Base

지시서의 SHA 를 참고값으로 받고 `git log` / `git show` / `git rev-parse` 로 직접 확인했다.
**세 개 모두 일치한다.**

| 항목 | 지시서 | 실측 | 결과 |
|---|---|---|---|
| 작업 시작 HEAD | `ea7173c` | `ea7173c0c49fe561e995a5a49343990ce8d793ba` | 일치 |
| 3-F-29 작업 | `8403b60` | `8403b60` *fix Clone sibling contamination* (1 file, +122 −21) | 일치 |
| 3-F-29 테스트 | `6216f77` | `6216f77` *update Clone contamination audit tests* (5 files, +1594 −21) | 일치 |
| 3-F-29 보고서 | `ea7173c` | `ea7173c` *document Clone sibling contamination audit* (711줄) | 일치 |
| branch | — | `claude/pensive-goodall-te1egy` | 지정 branch |
| `origin/claude/...` | — | `ea7173c` — **HEAD 와 동일 (동기화됨)** | — |
| worktree | — | **clean** | — |

기존 commit 은 rewrite 하지 않았다.

---

## 2. 문제 재현

지시서 §2 의 다섯 형태(A~E)를 **실제 parser 로** 돌렸다. 예상으로 답하지 않았다.

| | Lua | parser 결과 (`categories`) |
|---|---|---|
| **A** | `if c then SetCategory(DRAW) else SetCategory(DESTROY) end` | `['DRAW', 'DESTROY']` |
| **B** | `if c then SetTargetRange(MZONE,0) else SetTargetRange(GRAVE,0) end` | `['MZONE', 'GRAVE']` |
| **C** | `if c then SetCategory(DRAW) SetCategory(DESTROY) end` | `['DRAW', 'DESTROY']` |
| **D** | `if c then SetCategory(DRAW) else SetCategory(DRAW) end` | `['DRAW']` |
| **E** | `if c then SetCategory(DRAW) end  SetCategory(DESTROY)` | `['DRAW', 'DESTROY']` |
| 대조 | `SetCategory(DRAW)  SetCategory(DESTROY)` (순차) | `['DRAW', 'DESTROY']` |
| 대조 | `SetCategory(DRAW+DESTROY)` (한 호출) | `['DRAW', 'DESTROY']` |
| 추가 | `elseif` 3분기 | `['DRAW', 'DESTROY', 'TOHAND']` |
| 추가 | 중첩 `if` | `['DRAW', 'DESTROY']` |
| 추가 | `Clone` + 분기 | 부모 `['DRAW']` / 자식 `['DESTROY', 'TOHAND']` |

🔴 **A · C · E · 순차 · 한 호출 OR 이 전부 동일한 `EffectSpec` 을 만든다.**
다섯 가지 서로 다른 Lua 의미가 하나로 접힌다 (`test_18` 이 동등성으로 고정).

**D 는 합쳐도 결과가 옳다** — 양쪽이 같은 값이므로 손실이 없다.

`Clone` + 분기에서는 3-F-29 의 규칙대로 **첫 호출이 물려받은 `DRAW` 를 덮어쓰고**, 그 다음
분기 값이 더해진다 (`test_32`).

---

## 3. parser 경로

```
c*.lua
  → sources/lua_loader.py::parse_lua_source
      _RE_BLOCK_COMMENT 로 --[[ ]] 제거            (3-F-28)
      _RE_CREATE_EFFECT / _RE_CLONE_EFFECT + _is_card_effect 로 블록 탐지 (3-F-28)
      _RE_SETTER 로 모든 `var:SetX(` 수집
      (위치, 종류, 페이로드) 를 **events.sort(key=lambda e: e[0])** — byte offset 정렬
      bindings: dict[str, EffectSpec] 에 순서대로 재생
         "Type"         -> 3-F-27/29 의 inherited 추적 (첫 호출 덮어쓰기)
         "Code"         -> 대입 (3-E-18)
         "Range"/"TargetRange"/"Category"/"Property"
                        -> _write_list (3-F-29: Clone 상속이면 덮어쓰기, 아니면 더하기)
  → LuaScriptInfo.effects: list[EffectSpec]
  → core/card_repository.py (Card.script)
  → analysis/effect_analyzer.py::_collect_handlers (같은 정규식을 import — 3-F-28)
  → core/card_search.py · app/main.py
```

### 3.1 지시서 §4 의 체크리스트 — 실제 코드 기준

| 확인 항목 | 실제 |
|---|---|
| `SetCategory` 추출 | `_RE_SETTER` (`lua_loader.py:50`) 로 호출 위치를 찾고 `_RE_CATEGORY` (`:57`) 로 인자에서 `CATEGORY_*` 를 긁는다 |
| `SetTargetRange` 추출 | 같은 방식, `_RE_LOCATION` (`:56`) |
| `SetRange` / `SetProperty` | 같은 방식, `_RE_LOCATION` / `_RE_EFFECT_FLAG` (`:60`) |
| 여러 호출의 결합 방식 | `_write_list` (`:196`) — `Clone` 이 물려준 칸이면 **첫 호출이 덮어쓰고**, 그 밖에는 **더한다** |
| 마지막 값이 승리하는가 | **아니다** (목록 칸). `code` · `count_limit` 만 대입이다 |
| union/list 인가 | **list** — `_strip_prefix` 로 중복만 제거하고 **등장 순서를 유지**한다 |
| 첫 값만 유지하는가 | 아니다 |
| 호출 순서 보존 | **값의 순서는 보존**된다. 호출이 **몇 번**이었는지는 보존되지 않는다 |
| 🔴 **if/else AST 를 인식하는가** | **전혀 아니다** |
| 🔴 **단순 문자열/regex 인가** | **regex 다** |
| 🔴 **AST 를 어디까지 보존하는가** | **전혀 보존하지 않는다** |

### 3.2 분기 비인식을 코드로 고정했다 (`test_19`)

* `sources/lua_loader.py` 가 `luaparser` · `lupa` · `slpp` · `ast` 중 **아무것도 import
  하지 않는다.**
* 모듈에 `_RE_IF` · `_RE_BRANCH` · `_RE_ELSE` 같은 이름이 **없다.**
* 이벤트 정렬이 `events.sort(key=lambda e: e[0])` — **byte offset** 뿐이다.
* `parse_lua_source` 본문에 `elseif` · `branch_path` · `exclusive(` 가 **없다.**
* `analysis/effect_analyzer.py` 의 `_function_spans` 는 **함수 단위**이고 분기 단위가 아니다.

즉 **분기를 보지 못하는 것은 버그가 아니라 설계**다.

---

## 4. 분기 vs 순차 vs 누적

지시서 §3 이 요구한 세 가지를 **별도로** 분류했다. 파서는 셋을 구분하지 못하지만,
**정보 자체는 Lua 원문에 있다** — 이 Phase 가 감사용 측정 도구를 테스트 안에 만들어
셋을 실제로 갈라냈다 (`test_18` 이 그 구분을 함께 고정한다).

| | 뜻 | 실행 | parser |
|---|---|---|---|
| ① **분기** | `if`/`elseif`/`else` 중 하나만 실행 | 하나 | 전부 합침 |
| ② **순차** | 같은 실행 경로에서 여러 번 호출 | 전부 | 전부 합침 |
| ③ **누적** | 이전 호출 값이 다음 호출과 결합 | — | `_write_list` 가 더한다 (`Clone` 상속 첫 호출만 예외) |

🔴 **①과 ②를 같게 취급하면 안 된다** — 그래서 corpus 를 셋으로 나눠 셌다 (§6).

측정 도구는 Lua 블록 키워드(`if`/`then`/`elseif`/`else`/`end`/`for`/`while`/`do`/
`function`/`repeat`/`until`)를 토큰으로 추적해 각 위치의 **분기 경로**를 만든다.
주석·문자열은 **같은 길이의 공백**으로 치환해 offset 을 보존하고, `for`/`while` 뒤의 `do`
는 블록을 새로 열지 않도록 처리했다. 두 알려진 카드(`c52445243` · `c62784717`)의 분기
구조로 **검증한 뒤** 전수에 적용했다.

---

## 5. EffectSpec 표현력 감사

`EffectSpec` 의 칸은 **9개**다 — `index` · `effect_types` · `code` · `ranges` ·
`target_ranges` · `categories` · `properties` · `count_limit` · `cloned_from`.
🔴 **"조건" 을 담을 칸이 하나도 없다** (`test_17` 이 `condition`/`branch`/`when`/`guard`
같은 이름이 없음을 고정).

| 의미 | 판정 | 근거 |
|---|---|---|
| 단일 category | **REPRESENTABLE** | `categories == ['DRAW']` |
| 여러 category 의 집합 | **REPRESENTABLE** | `SetCategory(A+B)` → `['A','B']` |
| 조건별 category | 🔴 **NOT_REPRESENTABLE** | 조건부와 무조건이 **같은 spec** 을 만든다 (`test_20`) |
| 조건별 target range | 🔴 **NOT_REPRESENTABLE** | 같음 |
| 조건별 property | 🔴 **NOT_REPRESENTABLE** | 같음 |
| 순차 setter (횟수·순서) | 🔴 **NOT_REPRESENTABLE** | `SetProperty(A+B)` 와 `SetProperty(A); SetProperty(B)` 가 같다 |
| 분기별 setter | 🔴 **NOT_REPRESENTABLE** | ①과 ②가 구분되지 않는다 |
| 읽을 수 없는 인자 | **UNKNOWN 으로 남는다** | 3-F-29 가 "단정하지 않는다" 로 고정 — 분기 안이어도 물려받은 값을 지우지 않는다 (`test_20`) |

🔴 **"합쳐졌으니 의미도 합쳐졌다" 고 가정하지 않았다.** 위 표는 "합쳐진 결과" 가 아니라
**두 프로그램이 구분되지 않는다는 동등성**으로 증명했다.

---

## 6. corpus 통계 (현재 HEAD 전수)

### 6.1 설정자 호출 총수

묶인 블록에 귀속된 호출만, 블록 주석 제거 후.

| 설정자 | 호출 총수 |
|---|---|
| `SetCategory` | **14,254** |
| `SetTargetRange` | **3,417** |
| `SetRange` | **13,695** |
| `SetProperty` | **16,430** |

### 6.2 🔴 `if` 분기 **안**에 있는 호출 — 그리고 그 블록은 어디서 생성되는가

**이것이 이 Phase 의 결정적 측정이다.**

| 설정자 | `if` 안 | **같은 분기 안에서 블록 생성** | 🔴 **조건부 수정** | 그중 상수 읽음 |
|---|---|---|---|---|
| `SetCategory` | 91 (0.6%) | 91 | **0** | 0 |
| `SetTargetRange` | 274 (8.0%) | 272 | **2** | **0** |
| `SetRange` | 381 (2.8%) | 381 | **0** | 0 |
| `SetProperty` | 1,956 (11.9%) | 1,956 | **0** | 0 |
| **합계** | **2,702** | **2,700** | **2** | **0** |

읽는 법:

* **"같은 분기 안에서 블록 생성" 2,700건** — 블록 자체가 그 분기에서만 만들어진다. 즉
  설정자는 **그 블록에 대해 무조건**이고, 파서가 **옳다.** 이것이 압도적 다수다.
* **"조건부 수정" 2건** — 블록은 분기 밖에서 생성되고 설정자만 분기 안에 있다. 파서가
  "항상 적용" 으로 단정하는 유일한 모양이다. 🔴 그런데 **둘 다 읽을 수 있는 상수를 하나도
  내지 않는다** (`c62784717` 의 `SetTargetRange(1,0)` · `(0,1)` — 플레이어 대상 형식이라
  `LOCATION_*` 이 없다). **실제로 잃는 값이 0 이다.**

### 6.3 같은 블록·같은 설정자가 2회 이상

| 설정자 | 2회 이상 블록 | 배타 분기 | 분기 밖+안 | 같은 경로 순차 |
|---|---|---|---|---|
| `SetCategory` | 10 | **1** | 0 | 9 |
| `SetTargetRange` | 1 | **1** | 0 | 0 |
| `SetRange` | **0** | 0 | 0 | 0 |
| `SetProperty` | 7 | **0** | 0 | 7 |

🔴 **배타 분기 병합은 corpus 전체에 2블록**이고, 그중 **값이 서로 다른 것은 1블록**이다.

* `c62784717` `SetTargetRange` — 두 값 모두 상수를 못 읽어 **합쳐도 같다** (무해).
* `c52445243` `SetCategory` — 유일하게 다른 값이 합쳐진다. **단, §7.2 참고.**

`SetRange` 는 2회 이상 블록이 **0개**다 — 분기 문제가 존재할 수 없다.

### 6.4 같은 경로 순차 16건의 정체

`SetCategory` 9건 중 **8건**이 `SetCategory(aux.Stringid(id,n))` + 진짜 `SetCategory` 의
쌍이다 — `SetDescription` 을 쓸 자리에 쓴 **스크립트 오타**로 보이고, 첫 호출이 상수를
하나도 내지 않으므로 **파서 결과에는 영향이 없다**. 3-F-29 §22 가 이미 위험으로 적어 두었다.
`SetProperty` 7건은 3-F-29 §7.5 가 분석한 그 7건이다 (관용구 3 · 오타 1 · 독립 1 · 동일값 1 · 읽기 불가 1).

---

## 7. 실제 사례 (12장)

| # | 카드 | Lua 모양 | parser 결과 | 분류 |
|---|---|---|---|---|
| 1 | `c52445243` | `s.matcheck` 의 `if #g>2` / `elseif #g==2` → `SetCategory` 3회 (배타) | `ord=2` 에 `['DESTROY','DRAW']` | 🔴 **parser 귀속 오류** (§7.2) · production 영향 없음 |
| 2 | `c62784717` | `s.coinop` 의 `if`/`else` → `SetTargetRange(1,0)`/`(0,1)` | 해당 블록 `target_ranges == []` | **표현 한계 · 손실 0** |
| 3 | `c44887817` | `local e2=e1:Clone(e1)` | `SetCode` 1건이 앞 블록으로 | 🔴 **parser 귀속 오류** · 영향 없음 |
| 4 | `c4997565` | `local e2=Effect.Clone(e1)` | `SetCode` 1건이 앞 블록으로 | 🔴 **parser 귀속 오류** · 영향 없음 |
| 5 | `c12954226` | `SetCategory(aux.Stringid(id,1))` + 진짜 호출 | `['DAMAGE','RECOVER']` | **정상** (첫 호출이 0개) |
| 6 | `c55484152` | 같은 오타 쌍 | `['SPECIAL_SUMMON']` | **정상** |
| 7 | `c71948047` | 같은 오타 쌍 | `['ATKCHANGE','DEFCHANGE']` | **정상** |
| 8 | `c73244186` | 같은 오타 쌍 | `['DRAW']` | **정상** |
| 9 | `c74577599` | 같은 오타 쌍 | `['SPECIAL_SUMMON']` | **정상** |
| 10 | `c75294187` | 같은 오타 쌍 | `['DESTROY','REMOVE']` | **정상** |
| 11 | `c83670388` | 같은 오타 쌍 | `['DAMAGE']` | **정상** |
| 12 | `c93723936` | 같은 오타 쌍 | `['DISABLE','SPECIAL_SUMMON']` | **정상** |
| 13 | `c324483` | 3-F-27/29 의 `Clone` 카드 | `e2.effect_types == ['QUICK_O']` | **정상 · 회귀 없음** |

### 7.1 지시서 §7 의 A~E

| | 질문 | 답 |
|---|---|---|
| **A** | parser 가 분기 때문에 잘못된 값을 합치는 사례가 있는가? | **있다. corpus 전체에 2블록**이고 값이 다른 것은 1블록이다. 그 1블록은 §7.2 의 귀속 오류 위에 있다 |
| **B** | 서로 다른 실행 경로가 하나의 spec 으로 collapse 되는가? | **그렇다. 구조적으로 항상 그렇다.** 단 corpus 에서 실제로 값이 손실되는 경우는 위 2블록뿐이고, 조건부 수정 2건은 상수를 못 읽어 손실이 0이다 |
| **C** | 동일 의미의 호출을 parser 가 다르게 오인하는가? | 🔴 **있다 — §7.2.** 가려진 재바인딩 25곳 중 5건의 설정자가 **다른 블록**에 붙는다 |
| **D** | 본질이 `SetCategory`/`SetTargetRange` 자체인가, 분기 구조 미표현인가? | 🔴 **후자다.** 네 설정자 전부 같게 동작하고 (`test_10`~`test_13`), `SetRange` 는 2회 블록이 0개다. 설정자별 문제가 아니라 **`EffectSpec` 에 조건 칸이 없는 것**이 본질이다 |
| **E** | Engine 에서 실제 행동을 잘못 만들 수 있는가? | **아니다 — §8** |

### 7.2 🔴 별개 발견 — 가려진 재바인딩으로 인한 귀속 오류

`CreateEffect` 도 `Clone()` 도 아닌 RHS 로 **기존 블록 변수를 다시 묶는** 자리가
**25곳** 있다. 파서는 재바인딩을 보지 않으므로 그 뒤의 `e1:SetX` 가 **직전 `create`
블록**에 붙는다. 그렇게 잘못 귀속되는 설정자는 **5건 / 3장**이다 (`test_23`).

| 카드 | 원문 | 잘못 귀속되는 것 |
|---|---|---|
| `c52445243` | `local e1=e:GetLabelObject()` | `SetCategory` 3건 |
| `c44887817` | `local e2=e1:Clone(e1)` — `Clone()` 의 **빈 괄호**를 요구하는 정규식이 못 잡는다 | `SetCode` 1건 |
| `c4997565` | `local e2=Effect.Clone(e1)` — **다른 API 형태** | `SetCode` 1건 |

재바인딩 RHS 상위: `aux.createContinuousLizardCh…` 9 · `e:GetLabelObject` 5 ·
`reglevel` 3 · `Duel.IsPlayerAffectedByEffect` 2 · `aux.AddNormalSummonProcedure` 2 등.

🔴 **이것은 분기 문제가 아니라 3-F-28 의 블록 탐지 계열**이고, `c52445243` 의 "분기 병합"
도 실은 이 귀속 오류 **위에서** 일어난다 — `s.matcheck` 의 `e1` 은 의미상
`initial_effect` 의 `ordinal 0` 인데 파서는 `s.effop` 에서 생성된 `ordinal 2` 에 붙인다.

---

## 8. production 영향

지시서 §7 의 계층을 **AST 로 전수** 확인했다. "engine/ 에 같은 이름이 있다" 만으로
판단하지 않고 **base 식별자까지** 봤다 (`test_24`).

| 계층 | 네 칸을 읽는가 |
|---|---|
| `EffectDefinition` | **아니다** (칸 10개에 없다) |
| `TriggerSpec` · `ChainLink` · `EffectActivator` · `ChainResolver` | **아니다** |
| `legal_actions` · `apply` | **아니다** |
| `GameStateView` / `CardDefinitionView` | **아니다** — 26칸에 `effect_count` 만 있다 |
| `Search` (`core/card_search.py`) | 🔴 **읽는다** — 아래 §8.1 |
| `AI` (`agent/`) | **아니다** |

`engine/` · `agent/` 에서 `EffectSpec` 고유 칸(`effect_types` · `target_ranges` ·
`cloned_from` · `count_limit`)과 `categories` · `properties` · `ranges` 접근이 **0건**이다.

🔴 **정정** — `code` 와 `index` 는 **다른 클래스에도 흔한 이름**이라 "0건" 을 요구하면
틀린다. `engine/` 에 `.code` 접근이 62건(`verdict` · `result` · `requirement` · `payment`
· `gate` 등), `.index` 접근이 24건(`engine/action_target.py` 의 **존 번호**) 있고 전부
`EffectSpec` 이 아니다. 3-F-28 에서 `code` 로 같은 실수를 했고, 이번에 `index` 로
**반복했다가** 재측정해 고쳤다 (§11.2).

### 8.1 Search 가 읽는 두 경로 — 하나는 면역, 하나는 측정으로 불변

| 경로 | 코드 | 귀속 오류 민감도 |
|---|---|---|
| **필터** | `card_search.py:316` → `Card.has_effect_category` (`card_model.py:412`) | 🟢 **면역** |
| **순위** | `card_search.py:393` `sum(1 for e in card.effects if e.has_category(category))` | 🟠 **민감하지만 실측 불변** |

**필터가 면역인 이유**: `has_effect_category` 가 블록별 `categories` **또는** 파일 전체
`LuaScriptInfo.categories` 를 본다. corpus 전체에서 **"블록에만 있고 파일 전체 목록에는
없는 category" 가 0건**이므로, 블록 귀속이 틀려도 필터 결과가 바뀌지 않는다 (`test_25`).

**순위가 실측 불변인 이유**: 블록 **수**를 세므로 민감하다. 그러나 귀속이 틀린 3장
**전부** 각 category 를 **정확히 한 블록**이 갖는다 — 올바른 귀속에서도 1이므로 **점수가
같다** (`test_26`).

| 카드 | 블록별 category 보유 수 |
|---|---|
| `c52445243` | `DESTROY` 1 · `DRAW` 1 |
| `c44887817` | `SPECIAL_SUMMON` 1 |
| `c4997565` | `SPECIAL_SUMMON` 1 · `DISABLE` 1 |

---

## 9. Engine / AI 영향

**없다.** Engine V1 freeze 유지.

| 항목 | 결과 |
|---|---|
| production 변경 | **없음** (`test_27` — diff 에 `.py` production 파일 0개) |
| Engine 변경 | **없음** |
| AI/Search 변경 | **없음** |
| `state_hash` | **불변** (`test_28`) |
| RNG | **불변** (`test_28`) |
| hidden-information | **불변** — `CardDefinitionView` 26칸 (`test_30`) |
| digest | **불변** — 6판 611결정 (`test_29`) |
| `EffectRef` / `ordinal` | **불변** — 블록 34,681 · 16개 정의 전부 (`test_31`) |
| 파서 캐시 서명 | **`v7` 그대로** — 파서를 바꾸지 않았으므로 올리지 않는다 (`test_33`) |
| 3-F-29 `Clone` 결과 | **유지** — 다섯 칸 총계 동일 (`test_32`) |

---

## 10. 수정 내용

🔴 **production 을 수정하지 않았다.**

지시서 §8 은 다섯 조건을 **모두** 만족할 때만 수정을 허용한다.

| 조건 | 충족? | 근거 |
|---|---|---|
| ① 실제 parser bug 가 재현된다 | **일부 충족** | 분기 병합 2블록 · 귀속 오류 5건이 재현된다 |
| ② 의도한 parser contract 를 위반한다 | **일부 충족** | 분기 병합은 **설계대로**(§3.2)이므로 위반이 아니다. 귀속 오류는 `_RE_CLONE_EFFECT` 의 의도 위반이다 |
| ③ **production downstream 에 실제 영향을 준다** | 🔴 **충족하지 않는다** | §8 — Engine/AI 0, 검색 필터 면역, 검색 순위 실측 불변 |
| ④ 최소 수정으로 의미 보존 가능 | 분기: **아니다** (새 모델 필요) · 귀속: 가능 | |
| ⑤ API / Engine V1 freeze 유지 | 분기: **아니다** · 귀속: 가능 | |

③이 충족되지 않으므로 **수정하지 않는다.** 특히 지시서가 금지한 다음을 하지 않았다 —
조건부 AST 를 새 `EffectGraph` 로 만들기 · Lua interpreter · 새 expression language ·
`EffectSpec` 구조 변경 · Engine 수정 · AI/Search 수정 · 새 public enum · 공식 룰 추론 ·
**모든 setter 를 무조건 "마지막 값" 으로 바꾸기** · **모든 setter 를 무조건 union 으로 바꾸기.**

이 Phase 의 산출물은 **코드 변경이 아니라 확정된 사실**이다 — 파서가 무엇을 표현할 수 있고
무엇을 잃는지, 그리고 그 손실이 현재 **정확히 얼마인지**(조건부 수정 2건 중 상수 읽는 것
0건 · 배타 병합 2블록 중 값 다른 것 1블록).

---

## 11. 테스트 결과

### 11.1 신규

`tests/test_branch_setter_audit.py` — **33개**. 지시서 §11 의 16개 항목을 전부 덮고
17개를 더했다.

| §11 요구 | 테스트 |
|---|---|
| 단일 setter | `test_01` |
| 동일 setter 반복 | `test_02` |
| 다른 값 setter 반복 | `test_03` |
| if/else 서로 다른 값 | `test_04` |
| if/else 동일 값 | `test_05` |
| 분기 내부 2회 호출 | `test_06` |
| 분기 밖 + 분기 안 | `test_07` |
| nested if | `test_08` |
| elseif | `test_09` |
| `SetCategory`/`SetTargetRange`/`SetRange`/`SetProperty` | `test_10`~`test_13` (parametrize) |
| 실제 Lua snippet | `test_14` (`c52445243`) · `test_15` (`c62784717`) |
| parser output 안정성 | `test_16` |
| 기존 `EffectSpec` invariant | `test_17` · `test_31` |
| Engine consumer 없음 확인 | `test_24`~`test_27` |

추가분: `test_18` (다섯 형태 동등성) · `test_19` (Lua AST 부재) · `test_20` (표현력 표) ·
`test_21` (조건부 수정 전수) · `test_22` (배타 병합 전수) · `test_23` (귀속 오류 전수) ·
`test_25`/`test_26` (검색 두 경로) · `test_28`~`test_33` (불변 조건).

### 11.2 🔴 내가 만든 실수 하나

`test_24` 에서 `index` 를 "`engine/` 에 0건이어야 하는 칸" 으로 넣었다. **틀렸다** —
`engine/action_target.py` 의 `self.index` 는 **존 번호**이고 24건 있다. 3-F-28 에서
`code` 로 같은 실수를 했는데 **이번에 `index` 로 반복했다.** 재측정해서 `code` 와 함께
**base 식별자를 보고 판별**하도록 고쳤다.

교훈: **이름이 겹치는 칸은 "0건" 을 요구하면 안 된다.** `EffectSpec` 고유 칸
(`effect_types` · `target_ranges` · `cloned_from` · `count_limit`)만 0건을 요구할 수 있다.

### 11.3 기존 테스트

**갱신 0건.** 이 Phase 는 production 을 바꾸지 않았으므로 기존 기대값이 하나도 움직이지
않았다. 삭제 0 · skip 추가 0 · assertion 약화 0.

### 11.4 전체 회귀

현재 HEAD 에서 전체 pytest 를 실행했다 (`python -m pytest -q -p no:randomly`).

```
4877 passed, 4 skipped in 1199.29s (0:19:59)
```

| 기준 | 결과 |
|---|---|
| 3-F-29 baseline | 4,844 passed / 4 skipped |
| 이번 Phase | **4,877 passed / 4 skipped** |
| 차이 | **+33** = 신규 테스트 33개 그대로 |
| 예상하지 않은 failure | **0** |
| 삭제 | **0** |
| skip 추가 | **0** (4개 그대로) |
| threshold 완화 | **0** |
| 기존 테스트 갱신 | **0** — production 을 바꾸지 않았으므로 기대값이 하나도 움직이지 않았다 |
| `state_hash` · RNG · digest · hidden-info | 🟢 §9 |
| Search / AI | 🟢 §8 · §9 |
| Engine V1 freeze | 🟢 §9 |

🔴 **기존 테스트가 한 건도 깨지지 않은 것 자체가 "production 무변경" 의 증거다.**
3-F-27 · 3-F-28 · 3-F-29 는 전부 파서를 고쳤기 때문에 캐시 서명과 corpus 총계 핀이
움직였고, 이번에는 그런 갱신이 **0건**이다.

---

## 12. 최종 판정

**D. REPRESENTATION_LIMITATION**

`EffectSpec` 에 **조건을 담을 칸이 없고**, 파서는 설계상 Lua AST 를 보지 않는다. 그래서
"조건 A 면 X, 조건 B 면 Y" 는 **표현할 수 없다** — 분기 · 분기 내 순차 · 분기 밖+안 ·
순차 · 한 호출 OR 의 **다섯 가지가 같은 spec** 이 된다 (§2 · §5 · `test_18`).

🔴 **"분기별 의미를 표현하지 못한다" 와 "parser 가 잘못된 값을 만든다" 를 같은 것으로
취급하지 않았다.** 후자를 전수로 쟀고, 결과는 다음과 같다.

* 조건부 수정 **2건**, 그중 상수를 읽는 것 **0건** → **실제 값 손실 0**
* 배타 분기 병합 **2블록**, 값이 다른 것 **1블록** → 그 1블록은 §7.2 의 귀속 오류 위에 있다
* `if` 안의 호출 2,702건 중 **2,700건은 파서가 옳다** (블록이 그 분기에서만 생성된다)

**A 가 아니다** — 분기 병합은 설계대로이고(§3.2), 유일한 값 손실 1블록은 분기가 아니라
귀속 오류가 원인이다.
**B 가 아니다** — Engine/AI 가 네 칸을 **한 번도 읽지 않고**, 검색 필터는 면역이며 검색
순위는 실측 불변이다(§8).
**C 가 아니다** — 이 Phase 는 새 분류 데이터를 만들지 않았다.
**E 가 아니다** — 귀속 오류 5건은 **실제 parser bug** 다. "버그 없음" 이라고 적으면 거짓이다.

🔴 즉 **분기 쪽은 D(표현 한계), 귀속 쪽은 실제 버그이지만 production 영향이 없어
수정 조건 ③을 충족하지 못한다.** 둘을 섞지 않고 §13 에 나눠 적었다.

---

## 13. 남은 구조적 위험

### 13.1 이 Phase 에서 새로 발견

| # | 위험 | severity | 재현 | production 영향 | Engine 영향 | 왜 지금 안 고치는가 |
|---|---|---|---|---|---|---|
| N1 | **가려진 재바인딩으로 인한 설정자 귀속 오류** — 25곳 중 5건/3장 | 🟠 중 | **예** (`test_23`) | **없음** (§8) | 없음 | 지시서 §8 조건 ③ 미충족. 또한 `e:GetLabelObject()` 는 **dataflow 없이 해소할 수 없다** — 추측해서 구조화하지 않는다 |
| N2 | `_RE_CLONE_EFFECT` 가 `Clone()` 의 **빈 괄호**를 요구해 `e1:Clone(e1)` · `Effect.Clone(e1)` 을 놓친다 (2장) | 🟡 하 | **예** (`test_23`) | **없음** | 없음 | N1 과 같은 이유. 3-F-28 계열이므로 그 범위에서 다루는 것이 맞다 |
| N3 | **분기별 의미를 표현할 칸이 없다** — 조건부 수정 2건 | 🟡 하 | **예** (`test_21`) | **없음** (상수 읽음 0건) | 없음 | 새 모델이 필요하고 지시서가 `EffectGraph`·Lua interpreter 를 금지한다. 손실이 실측 0 이다 |
| N4 | **배타 분기 값 병합** — 2블록 (값 다른 것 1) | 🟡 하 | **예** (`test_22`) | **없음** | 없음 | 설계상 그렇고, 유일한 값 손실은 N1 이 원인이다 |

### 13.2 기존 위험 (유지)

| # | 위험 | 출처 | 상태 |
|---|---|---|---|
| E1 | 네 설정자의 Lua API 의미가 문서화되지 않음 (대입 vs OR). 반대 독립 증거 1건 | 3-F-29 §22 | **유지** |
| E2 | 목록 칸에 "모른다" 를 표현할 값이 없다 | 3-F-29 §22 | **유지** |
| E3 | 한 블록의 두 번째 이후 호출은 더하기 그대로 | 3-F-29 §22 | **유지** |
| E4 | 캐시 서명에 파서 버전이 없다 (세 Phase 연속 수동) | 3-F-27~29 | **유지** (`v7`) |
| E5 | 보조 함수가 만드는 effect 를 파서가 모른다 (`Fusion.CreateSummonEff` 45 · `Ritual.CreateProc` 20 등) | 3-F-28 §22 | **유지** · N1 과 **같은 뿌리** |
| E6 | `EffectSpec.index` 가 유일하지 않다 | 3-F-28 §22 | **유지** |
| E7 | `SetCategory(aux.Stringid(...))` 8건 — `SetDescription` 오타로 보인다 | 3-F-29 §22 | **유지** · 이번에 8건으로 **정확히** 셌다 (§6.4) |

---

## 14. 다음 Phase 후보 1개

**Phase 3-F-31 — 변수 재바인딩 추적 감사 (`local e* = <비-CreateEffect>` 와 미인식 Clone 형태)**

이 Phase 의 **N1 · N2** 와 3-F-28 의 **E5** 가 **하나의 뿌리**다 — 파서가 변수 → 블록
바인딩을 `Effect.CreateEffect` 와 `X:Clone()` **두 형태로만** 갱신한다. 그래서

* `local e1=e:GetLabelObject()` (5곳) — 다른 블록을 가리키는데 갱신되지 않는다
* `local e2=e1:Clone(e1)` · `local e2=Effect.Clone(e1)` (2곳) — 클론인데 못 잡는다
* `local e3=Ritual.CreateProc(...)` · `Fusion.CreateSummonEff(...)` (70곳) — 블록인데 못 잡는다

가 전부 같은 기제에서 나온다. 범위가 좁고(`lua_loader` 의 이벤트 수집 한 군데), corpus
전수 측정이 가능하며, engine 이 그 칸들을 읽지 않는다는 것도 이미 확정되어 있다.
먼저 **"25곳 중 몇 곳이 실제로 다른 블록을 가리키는가"** 를 재어야 하고, `GetLabelObject`
처럼 dataflow 없이 해소할 수 없는 것은 **추측해서 구조화하지 않고 UNKNOWN 으로 남기는**
것도 정당한 결론이다.
