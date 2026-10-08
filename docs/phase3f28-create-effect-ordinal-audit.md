# Phase 3-F-28 — `local` 없는 `Effect.CreateEffect` 누락 감사 및 `EffectRef`/`ordinal` 경계 검증

**판정: A. CONFIRMED_CREATE_EFFECT_OMISSION + C. CONFIRMED_DOWNSTREAM_REFERENCE_BUG**

---

## 1. 실제 HEAD / Base

지시서의 SHA 를 참고값으로 받고 `git log` 로 직접 확인했다. **세 개 모두 일치한다.**

| 항목 | 지시서 | 실측 | 결과 |
|---|---|---|---|
| 3-F-27 작업 commit | `c8fd8af` | `c8fd8af` *Phase 3-F-27: fix SetType Clone contamination* (4 files, +1290 −40) | 일치 |
| 3-F-27 테스트 commit | `d9b0268` | `d9b0268` *… update four audit tests …* (5 files, +771 −17) | 일치 |
| 3-F-27 보고서 commit | `f6ae73f` | `f6ae73f` *… document SetType Clone contamination audit* | 일치 |
| HEAD | — | `f6ae73fa3ae283837ea9ebea74735f742a1a3a31` | = 보고서 commit |
| branch | `claude/pensive-goodall-te1egy` | 같음 | 일치 |
| `origin/claude/pensive-goodall-te1egy` | — | `f6ae73f` | HEAD 와 같음 |
| worktree | — | 작업 시작 시점에 clean | — |

---

## 2. 문제 재현

3-F-27 이 "범위 밖" 으로 적어 둔 것이 출발점이었다.

> `local` 없는 `e1=Effect.CreateEffect(c)` 가 **217곳 / 195파일** 있고, 파서가 그것을
> 새 블록으로 보지 않아 **설정자가 이전 바인딩으로 흘러든다.**

최소 사례로 재현했다. 같은 Lua 를 파서에 그대로 먹인다.

```lua
local e1=Effect.CreateEffect(c)
e1:SetType(EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O)
e1:SetCode(EVENT_SPSUMMON_SUCCESS)
c:RegisterEffect(e1)
e1=Effect.CreateEffect(c)          -- ← local 이 없다
e1:SetType(EFFECT_TYPE_SINGLE)
e1:SetCode(EFFECT_UPDATE_ATTACK)
c:RegisterEffect(e1)
```

| | 블록 수 | `ordinal` 0 의 `code` |
|---|---|---|
| 수정 전 | **1** | `EFFECT_UPDATE_ATTACK` ← 두 번째 블록의 값이 **덮어썼다** |
| 수정 후 | **2** | `EVENT_SPSUMMON_SUCCESS` |

재현 테스트: `test_05_local_and_non_local_do_not_merge` · `test_07_create_effect_with_setcode`.

🔴 이것이 3-E-18 이 `test_setcode_provenance_audit.py::test_17` 에 *"3번은 전 corpus 에서
1장이다 … 고치는 Phase 는 이 테스트를 **의도적으로** 갱신해야 하고, 그 이유를 보고서에
적어야 한다"* 라고 남겨 둔 바로 그 건이고, 3-F-27 에서 production ↔ 교체 규칙이 corpus
전체에서 아직 다른 **1블록**의 원인이기도 했다.

---

## 3. `local` / non-`local` Lua semantics

**지시서의 요구대로, "`local` 이 없으므로 잘못된 Lua" 라고 가정하지 않았다.**

Lua 에서 `local x = …` 는 지역 변수를, `x = …` 는 **전역 변수**를 만든다. 둘 다 문법적으로
정상이고, 둘 다 뒤따르는 `x:SetCode(…)` 가 **같은 객체**를 가리킨다. 즉:

- **`local` 이 없다는 것 자체는 파서에게 문제가 되지 않는다.** 객체는 그 자리에 있다.
- 문제는 **파서가 `local` 을 탐지 조건으로 요구했다**는 것이다.

| 지시서 §5 분류 | 이 저장소의 실제 |
|---|---|
| A. `local` 없어도 전역 변수에 Effect 가 정상 저장 | **그렇다.** Lua 의미상 당연하다 |
| B. `local` 없어도 바로 다음 setter 가 동일 객체를 참조 | **그렇다** (`c9839115` 가 그 모양) |
| C. `local` 없어도 이후 `Clone` 이 정상 작동 | corpus 에 사례 **0건** (non-`local` clone 1건은 Group clone) |
| D. `local` 없어 기존 변수/effect 를 덮어씀 | **Lua 수준에서는 아니다** — 같은 이름의 **새 객체**다 |
| E. `local` 없어서 이전 effect 와 실제로 혼합됨 | **Lua 에서는 아니다. 파서에서 그랬다** (§2) |
| F. 파서가 `local` 의 존재를 effect 발견 조건으로 사용 | **그렇다 — 이것이 원인이다** |
| G. 파서가 `local` 과 무관하게 `CreateEffect` 호출 자체를 추적 가능 | **그렇다. 그러나 그러면 안 된다** (§5) |

---

## 4. parser 경로

```
c*.lua
  → sources/lua_loader.py::parse_lua_source
      _RE_CREATE_EFFECT / _RE_CLONE_EFFECT / _RE_SETTER 로 (위치, 종류, 페이로드)
      이벤트를 모아 byte offset 으로 정렬 → bindings: dict[str, EffectSpec] 재생
  → LuaScriptInfo.effects: list[EffectSpec]
  → core/card_repository.py (Card.script)
  → engine/ids.py::EffectRef(card_id, ordinal) = effects 안의 0-기반 위치
```

병렬로 하나 더 있다. **이것이 §C 의 downstream 문제다.**

```
c*.lua
  → analysis/effect_analyzer.py::EffectAnalyzer._collect_handlers
      (자기 모듈에 따로 복사한 _RE_CREATE_EFFECT / _RE_CLONE_EFFECT / _RE_SETTER)
  → _analyze_card: entries[position] ↔ card.script.effects[position] 을 **순번으로 짝짓는다**
```

production 주석이 그 계약을 명시한다 — *"lua_loader 와 같은 순서로 효과 블록이
만들어지므로 순번으로 짝짓는다."*

---

## 5. `CreateEffect` 탐지 방식

### 5.1 수정 전

```python
_RE_CREATE_EFFECT = re.compile(r"\blocal\s+(e\w*)\s*=\s*Effect\.(?:CreateEffect|GlobalEffect)\s*\(")
_RE_CLONE_EFFECT  = re.compile(r"\blocal\s+(e\w*)\s*=\s*(e\w*)\s*:\s*Clone\s*\(\s*\)")
_RE_SETTER        = re.compile(r"\b(e\w*)\s*:\s*Set(\w+)\s*\(")
```

`local` **과** `e` 로 시작하는 변수명을 **둘 다 요구한다.** 지시서 §4 의 *"`local` 이
있어야만 effect 로 인정한다 라는 가정이 코드 어디에 존재하는지 확인하라"* 에 대한 답은
**이 세 정규식**이고, 그 밖에는 어디에도 없다 (`engine/` · `agent/` · `core/` 에 `local`
을 보는 코드는 없다).

### 5.2 🔴 그 요구는 **버그가 아니라 대리 지표**였다

`local` 요구를 걷어내는 것이 "고치는 것" 처럼 보인다. **전수로 측정해 보니 틀렸다.**

그 요구가 걸러 내는 자리를 전부 분류했다 (`test_34`).

| 세지 않는 자리 | 수 | 등록 대상 | 이 카드의 효과인가 |
|---|---|---|---|
| `CreateEffect` (`local ge1=…` 등) | 216 | `Duel.RegisterEffect` | **아니다** — 듀얼 전역 |
| `X=Y:Clone()` (`local ge2=ge1:Clone()`) | 29 | `Duel.RegisterEffect` | **아니다** — 듀얼 전역 |
| `CreateEffect` (`local` 있음, 이름 `e` 아님) | 3 | `tc:` / `token:RegisterEffect` | **아니다** — 다른 카드 |
| `CreateEffect` (`local` 없음) | 1 | `tc:RegisterEffect` (`c5795980` `e3`) | **아니다** — 다른 카드 |
| **합계** | **249** | | **249곳 전부 아니다** |

즉 `local` + `e*` 관례는 **"이 카드의 효과" 의 대리 지표**이고, 249곳에서 **249곳 모두
옳다.** 세면 그만큼 `ordinal` 이 틀어진다.

그래서 이 Phase 는 **관례를 버리지 않았다** (`test_35`). `_is_card_effect` 가 관례를
**먼저** 보고, 통과하지 못한 자리에서만 `c:RegisterEffect(var)` 라는 **명시적 증거**를 본다.

### 5.3 🔴 그런데도 **두 곳**은 진짜 누락이었다 → 판정 **A**

관례가 놓친 자리 중 둘은 `c:RegisterEffect(var)` 로 **이 카드에** 등록된다.

| 카드 | 모양 | 왜 놓쳤나 |
|---|---|---|
| `c9839115` 월롱룡 바그나와 | `e1=Effect.CreateEffect(c)` | `local` 이 없다 |
| `c74506079` | `local ae=Effect.CreateEffect(c)` | 변수명이 `e` 로 시작하지 않는다 |

### 5.4 🔴 그리고 **블록 주석**을 세고 있었다

`c9409625` 는 `--[[ untested version of Fluo's destruction count … --]]` 안에 효과 블록
하나를 적어 둔다. Lua 는 실행하지 않는다. 파서는 **세고 있었다.**

---

## 6. ordinal 생성 방식

`EffectRef.ordinal` 은 `card.script.effects` 안의 **0-기반 위치**이고 (`engine/ids.py`),
그 목록은 §4 의 이벤트 재생 순서다. 그러므로:

> **`CreateEffect` 하나를 놓치면 그 뒤의 모든 `ordinal` 이 1씩 당겨진다.**

이것이 §19-14 테스트가 **구성으로** 보여주는 것이다. 같은 Lua 에 수정 전 규칙과 수정 후
파서를 돌린다.

| | 블록 | `e2` 의 `ordinal` |
|---|---|---|
| 수정 전 규칙 | `['e1', 'e2']` | **1** |
| 수정 후 파서 | `['e1', 'ae', 'e2']` | **2** |

`EffectRef(card, 2)` 가 수정 전에는 **아무것도 가리키지 않았고**, 수정 후에는 `e2` 를
가리킨다. 이것이 "단순 통계 변화" 가 아닌 이유다.

---

## 7. EffectRef 연결

`EffectRef(card_id, ordinal)` 설계를 **그대로 유지했다** (`test_23`).

- `EffectRef` 는 `(card_id, ordinal)` 두 칸짜리 `frozen=True` dataclass 그대로다.
- 새 `EffectID` 체계 · UUID · object identity · Lua 변수명 식별자 — **하나도 도입하지 않았다.**
  `engine/ids.py` 에 `import uuid` · `uuid4` · `id(self)` · `EffectId` 가 0회다.
- `EffectSpec.index` (Lua 변수명) 는 `EffectRef` 의 칸이 **아니다.** 실제로 `c74506079` ·
  `c9839115` 처럼 **같은 `index` 가 여러 블록에 나온다** — 그래서 `index` 는 식별자가 될 수 없다.

---

## 8. 전체 corpus 통계 (현재 HEAD 재측정)

블록 주석을 지운 본문 기준. 전부 `test_33` · `test_34` 가 고정한다.

| 항목 | 수 |
|---|---|
| 스크립트 파일 | 12,702 |
| `Effect.CreateEffect\|GlobalEffect` 호출 자리 | **32,157** |
| └ 그중 변수에 배정되지 않는 자리 | **0** |
| `X = Y:Clone()` 자리 | 2,827 |
| └ 부모가 Effect 인 것 | **2,773** |
| └ 부모가 Group 인 것 (`g1` 26 · `rg1` 20 · `tg` 2 …) | 54 |
| 파서 블록 (수정 후) | **34,681** = create 31,937 + clone 2,744 |
| 파서 블록 (수정 전) | 34,680 |
| 파서가 일부러 세지 않는 자리 | **249** (create 220 + clone 29) |
| 그 자리를 가진 스크립트 | 197 |

### 8.1 🔴 3-F-27 의 "217곳 / 195파일" 정정

그 숫자는 **`local` 이 없는 자리** 가 아니라 `_RE_CREATE_EFFECT` 가 세지 않는 자리 **전체**
였다. 이 Phase 가 셋으로 분해했다 (`test_15`).

| 분해 | 수 |
|---|---|
| `CreateEffect` 에 **`local` 이 진짜 없다** | **2** (`c9839115` `e1` · `c5795980` `e3`) |
| `Clone` 에 `local` 이 없다 | **1** (`c42237854` `tg=…:Clone()` — Group clone) |
| `local` 은 **있고** 변수명이 `e` 로 시작하지 않는다 | **220** (`ge1` 180 · `ge2` 17 · `de` 10 · `ge` 5 · `ge3` 4 · `ae` 2 · `geff` 1 · `ge2a` 1 · `ge4` 1) |

즉 **"`local` 누락" 은 사실상 2건이고, 나머지는 변수명 관례 문제였다.**

### 8.2 실제 사례 ≥20 (지시서 §8 표)

| script | `CreateEffect` 형태 | parser 인식 | ordinal | EffectRef | 이후 setter | 정상/문제 |
|---|---|---|---|---|---|---|
| `c9839115` | `e1=…(c)` (**`local` 없음**) | 🔴 전: 없음 / 후: 있음 | 후 2 (신규) | 후 `(9839115,2)` | `SetType`·`SetCode`·`SetValue`·`SetReset` | **문제 → 고쳤다** |
| `c74506079` | `local ae=…(c)` (**이름 `e` 아님**) | 🔴 전: 없음 / 후: 있음 | 후 1 (신규, 뒤 3개 밀림) | 후 `(74506079,1)` | `SetType`·`SetCode`·`SetValue` | **문제 → 고쳤다** |
| `c9409625` | `local e2=…(c)` **주석 안** | 🔴 전: 있음 / 후: 없음 | 전 2 → 삭제 | 전 `(9409625,2)` | `SetType`·`SetCode`·`SetRange`·`SetProperty`·`SetCountLimit` | **문제 → 고쳤다** |
| `c5795980` | `e3=…(…)` (**`local` 없음**) | 세지 않음 | — | — | `tc:RegisterEffect(e3)` | **정상** (다른 카드) |
| `c42237854` | `tg=g:Clone()` (**`local` 없음**) | 세지 않음 | — | — | Group — effect 아님 | **정상** |
| `c10113611` | `local ge1=…(c)` | 세지 않음 | — | — | `Duel.RegisterEffect(ge1,…)` | **정상** (전역) |
| `c10497636` | `local ge1=…(c)` | 세지 않음 | — | — | `Duel.RegisterEffect` | **정상** (전역) |
| `c12275533` | `local ge1=…` + `ge2=ge1:Clone()` + `ge3=ge1:Clone()` | 세지 않음 (3곳) | — | — | `Duel.RegisterEffect` ×3 | **정상** (전역 · 여러 Clone) |
| `c12958919` | `local ge1=…(c)` | 세지 않음 | — | — | `Duel.RegisterEffect` | **정상** |
| `c13076804` | `local ge1=…(c)` | 세지 않음 | — | — | `Duel.RegisterEffect` | **정상** |
| `c13224603` | `local ge1` + `ge2=ge1:Clone()` | 세지 않음 (2곳) | — | — | `Duel.RegisterEffect` | **정상** |
| `c13567610` | `local ge1=…(c)` | 세지 않음 | — | — | `Duel.RegisterEffect` | **정상** |
| `c13764602` | `local ge1=…(c)` | 세지 않음 | — | — | `Duel.RegisterEffect` | **정상** |
| `c14318794` | `local ge1=…(c)` | 세지 않음 | — | — | `Duel.RegisterEffect` | **정상** |
| `c15216188` | `local ge1=…(c)` | 세지 않음 | — | — | `Duel.RegisterEffect` | **정상** |
| `c16832845` | `local ge1=…(c)` | 세지 않음 | — | — | `Duel.RegisterEffect` | **정상** |
| `c18114794` | `local ge1` · `ge2` · `ge3` (**여러 CreateEffect**) | 세지 않음 (3곳) | — | — | `Duel.RegisterEffect` ×3 | **정상** |
| `c98645731` | `local ge1`~`ge4` + `ge2a=ge2:Clone()` | 세지 않음 (5곳) | — | — | `Duel.RegisterEffect` | **정상** |
| `c1764972` | `local de=…(c)` (이름 `e` 아님) | 세지 않음 | — | — | `Duel.RegisterEffect` | **정상** |
| `c24207889` | `local ge=…(c)` | 세지 않음 | — | — | `Duel.RegisterEffect` | **정상** |
| `c6992184` | `local geff=…(c)` | 세지 않음 | — | — | `Duel.RegisterEffect` | **정상** |
| `c87880531` | `local ae=…(c)` | 세지 않음 | — | — | `tc:RegisterEffect(ae)` | **정상** (다른 카드) |
| `c84544192` | `local ge1=…(c)` (ordinal 0 자리) | 세지 않음 | — | — | `Duel.RegisterEffect` | **정상** (전역) |
| `c39114494` | `local e3=Ritual.CreateProc({…})` | 세지 않음 (`CreateEffect` 아님) | — | — | `e4=e3:Clone()` 이 부모를 못 찾는다 | 🟠 **별개 한계** (§22) |

**`local` / non-`local` 혼합 · 같은 변수명 재사용 · `initial_effect` 등록 · 등록되지 않는
temporary effect** 는 `c9839115` (혼합 + `e1` 재사용 + `initial_effect` 밖) 와
`c74506079` (`e1` 세 번 재사용, 전부 해결 함수 안) 가 그대로 그 유형이다.

### 8.3 지시서 §6 A~H 분류와 실제 수

지시서는 각 분류에 사례 10개 이상을 요구한다. **실제 모집단이 그보다 작은 분류가 있으므로
없는 사례를 만들지 않고 실제 수를 적는다.** (`test_34` 의 docstring 에 같은 내용이 있다.)

| 분류 | 수 | 근거 |
|---|---|---|
| A. `local` 없음 + parser 정상 인식 | **1** (`c9839115`) — 이름 문제까지 합치면 2 | 수정 후 |
| B. A + ordinal 정상 | **1** (같은 건) — 합 2 | `test_11` · `test_16` |
| C. `local` 없음 + parser 가 놓침 | 수정 **전 2** / **후 0** | §5.3 |
| D. 발견되지만 ordinal 이 틀림 | **0** | `test_11` · `test_16` |
| E. 기존 effect 와 잘못 연결 | 수정 **전 1** (`c9839115` `code` 흘림) / **후 0** | §2 |
| F. 이후 setter/Clone 추적 실패 | **0** (`test_13` 의 1건은 보조 함수가 원인) | §22 |
| G. Lua semantics 상 특별 | **249** (전역 245 · 다른 카드 4) — **모집단의 전부** | §5.2 |
| H. false positive | 3-F-27 의 "217곳" 추정 | §8.1 |

---

## 9. 실제 사례 (전체 블록 덤프)

### `c9839115` — 귀속 오류가 사라졌다

| ordinal | 전: index / code | 후: index / code |
|---|---|---|
| 0 | `e0` / `EFFECT_MATERIAL_CHECK` | `e0` / `EFFECT_MATERIAL_CHECK` |
| 1 | `e1` / 🔴 `EFFECT_UPDATE_ATTACK` | `e1` / 🟢 `EVENT_SPSUMMON_SUCCESS` |
| 2 | — | `e1` / `EFFECT_UPDATE_ATTACK` (신규) |

`effect_types` 는 전후 모두 `['SINGLE','TRIGGER_O']` 와 `['SINGLE']` 이다. 🔴 수정 전에는
두 번째 블록의 `SetType(EFFECT_TYPE_SINGLE)` 이 앞 블록의 `['SINGLE','TRIGGER_O']` 에
**우연히 흡수되어 같은 집합**이었다 (3-F-27 `test_33` 의 경고가 그것).

### `c74506079` — 뒤 세 블록이 1씩 밀렸다

| 전 ordinal | 후 ordinal | index / code / categories |
|---|---|---|
| 0 | 0 | `e2` / `EFFECT_MATERIAL_CHECK` / — |
| — | **1** | `ae` / `EFFECT_SET_ATTACK` / — (신규) |
| 1 | **2** | `e1` / `None` / `SPECIAL_SUMMON` |
| 2 | **3** | `e1` / `None` / `TOGRAVE` |
| 3 | **4** | `e1` / `None` / `DRAW` |

세 `e1` 블록은 `index` 가 같고 `categories` 로만 구별된다 — **`index` 가 식별자가 될 수
없다는 또 하나의 증거**다.

### `c9409625` — 주석 안의 블록이 사라지고 뒤 둘이 당겨졌다

| 전 ordinal | 후 ordinal | index / code |
|---|---|---|
| 0 | 0 | `e1` / `EVENT_FREE_CHAIN` |
| 1 | 1 | `e2` / `EFFECT_DESTROY_REPLACE` |
| 2 | **삭제** | `e2` / `EFFECT_INDESTRUCTABLE_COUNT` ← 🔴 `--[[ … --]]` 안 |
| 3 | **2** | `e3` / `EVENT_FREE_CHAIN` |
| 4 | **3** | `e4` / `EVENT_FREE_CHAIN` |

---

## 10. 16개 EffectDefinition 검증

`EFFECT_LIBRARY` 는 16개다. **전부 검사했고 하나도 영향받지 않았다** (`test_17`).

| 확인 | 결과 |
|---|---|
| 블록 수 | 16장 **전부 1개** |
| `effect_ref.ordinal` | 16장 **전부 0** |
| `ref.resolve(card)` | 16장 **전부 성공** |
| `resolve().code` | 16장 **전부 `EVENT_FREE_CHAIN`** |
| `effect_refs(card)` | 16장 **전부 `[EffectRef(id, 0)]`** |
| 수정 전/후 블록 전체 비교 | 16장 **전부 완전히 동일** |
| 스크립트에 블록 주석(`--[[`) | 16장 **전부 없음** |
| 스크립트에 `local` 없는 / `e` 아닌 `CreateEffect` | 16장 **전부 없음** |

`{9839115, 74506079, 9409625}` ∩ `{등록된 16장}` = **∅**.

그래서 `EffectDefinition → TriggerSpec → ChainLink → EffectRef` 경로에
**이 수정이 닿지 않는다.** 지시서 §9 의 *"반대로 production execution 과 전혀 연결되지
않는다면 그 사실을 명확히 기록하라"* 에 해당한다 — **연결되지 않는다.**

---

## 11. cache 영향

`LuaScriptSource._signature()` 는 `f"v{N}:{스크립트 수}:{최신 mtime}"` 이다. **파서 버전이
들어 있지 않다.** 스크립트 파일이 바뀌지 않으면 서명이 같으므로, 고친 파서가 **옛 캐시를
계속 읽는다.**

- 3-E-18 이 설치한 `test_setcode_provenance_audit.py::test_19` 가 **설계대로 걸렸다.**
  3-F-27 (`v4`→`v5`) 에 이어 **두 번째**다.
- `v5` → **`v6`** 으로 올렸다. `data/cache/lua_scripts.json` 을 새 서명으로 다시 썼다.
- `test_19` (round-trip) · `test_20` (접두사) · `test_21` (stale 거부) 가 고정한다.
  `test_21` 은 `v5` 서명과 **거짓 내용**을 심어 놓고 그것이 무시되는지 본다.

🔴 지시서의 *"parser cache 전체 architecture 를 재설계하지 마라"* 를 지켰다 — 접두사
한 글자만 올렸다.

---

## 12. 수정 여부

**수정했다.** 판정이 A (실제 누락) + C (downstream 참조) 이고, 지시서가 A~D 면 최소 수정을
지시한다.

---

## 13. 수정 내용

### 13.1 `sources/lua_loader.py`

```python
_RE_BLOCK_COMMENT = re.compile(r"--\[\[.*?(?:--\]\]|\]\])", re.S)

_RE_CREATE_EFFECT = re.compile(
    r"(?:\b(local)\s+)?([A-Za-z_]\w*)\s*=\s*Effect\.(?:CreateEffect|GlobalEffect)\s*\("
)
_RE_CLONE_EFFECT = re.compile(
    r"(?:\b(local)\s+)?([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\s*:\s*Clone\s*\(\s*\)"
)
_RE_SETTER = re.compile(r"\b([A-Za-z_]\w*)\s*:\s*Set(\w+)\s*\(")

def _registers_on_card(source, var):
    pattern = r"(?<![\w.])c\s*:\s*RegisterEffect\s*\(\s*" + re.escape(var) + r"\b"
    return re.search(pattern, source) is not None

def _is_card_effect(source, local, var, parent):
    if local and var.startswith("e") and (parent is None or parent.startswith("e")):
        return True                      # 기존 관례 — 그대로 유지
    return _registers_on_card(source, var)   # 놓친 자리만 명시적 증거로 보강
```

`parse_lua_source` 안에서:

- `body = _RE_BLOCK_COMMENT.sub("", source)` 를 먼저 만들고 **탐지와 설정자 인자 추출을
  전부 `body` 기준으로** 한다. 헤더의 카드명은 그 **전에 원문**에서 읽고, 줄 주석(`--`)은
  남긴다 (`test_31`).
- `_extract_call_args(body, …)` — 🔴 `source` 로 쓰면 주석을 지운 만큼 offset 이 밀린다.
- 파일 전체 긁기(`functions` · `trigger_events` · `locations` · `categories` ·
  `effect_codes` · `listed_names` · `listed_series`) 는 **일부러 `source` 를 그대로 쓴다.**
  그 값들은 설계상 블록에 귀속되지 않는 "스크립트에 등장한 상수" 목록이고, 바꾸면 블록
  주석이 있는 스크립트의 숫자가 움직인다 — 이 Phase 의 범위가 아니다. production 주석에
  그렇게 적어 두었고 `test_33` 이 그 주석을 확인한다.
- `_signature` `v5` → `v6`.

### 13.2 `analysis/effect_analyzer.py`

```python
from sources.lua_loader import (
    _extract_call_args, _is_card_effect,
    _RE_BLOCK_COMMENT, _RE_CLONE_EFFECT, _RE_CREATE_EFFECT,
)
_RE_SETTER = re.compile(r"\b([A-Za-z_]\w*)\s*:\s*Set(Cost|Condition|Target|Operation)\s*\(")
```

탐지 정규식을 **자기 모듈에서 지우고 로더에서 import** 한다. `_collect_handlers` 가 같은
블록 주석 제거와 `_is_card_effect` 판정을 쓰고, 주석을 지웠으면 **함수 구간도 지운 본문에서
다시 잡는다** (그러지 않으면 `_enclosing_function` 이 엉뚱한 함수를 돌려주고
`is_registered` 가 틀어진다). `_RE_SETTER` 는 설정자 **종류만** 좁게 남긴다 — 이 모듈이
쓰는 네 개뿐이다.

### 13.3 하지 않은 것

- 새 abstraction · 새 enum · 새 public API — **없다.** `lua_loader` 의 public 이름은
  `parse_lua_source` · `LuaScriptSource` 둘 그대로다 (`test_36`).
- `EffectSpec` (9칸) · `EffectDefinition` (10칸) · `LuaScriptInfo` — **칸 변화 없다.**
- **Lua 파일 일괄 수정 — 하지 않았다.** `c9839115` 의 `local` 없는 줄이 원문에 그대로 있다.
- `SetType` · `QUICK_O` · `EVENT_FREE_CHAIN` 의 의미 — **재정의하지 않았다.**
- `engine/` · `agent/` — **한 글자도 바꾸지 않았다.**

---

## 14. 수정 전/후 corpus diff

12,702 스크립트를 **수정 전 파서 모듈과 수정 후 파서로 각각 파싱해** `EffectSpec` 9칸과
`LuaScriptInfo` 10칸을 전수 비교했다.

| 지시서 §12 분류 | 결과 |
|---|---|
| A. 새롭게 발견된 effect | **2** (`c9839115` ord 2 · `c74506079` ord 1) |
| B. 기존 effect 의 ordinal 변화 | **5블록** — `c74506079` 3개 (+1) · `c9409625` 2개 (−1) |
| C. EffectRef 변화 | 위 5블록. 🔴 등록된 16개 중 **0개** |
| D. 정상 결과 유지 | **12,699 스크립트** 완전 동일 |
| E. 예상하지 못한 변화 | **0** — `effects` 외의 **어떤 칸도** 바뀌지 않았다 |
| F. 실제 Lua semantics 차이 | **1** (`c9409625` 의 주석 블록 — Lua 가 실행하지 않는다) |

| 총계 | 전 | 후 |
|---|---|---|
| 블록 | 34,680 | **34,681** |
| `code` 있는 블록 | 30,126 | **30,127** |
| `ranges` 합 | 15,076 | **15,075** |
| `properties` 합 | 23,909 | **23,907** |
| `count_limit` 합 | 11,188 | **11,187** |
| `target_ranges` · `categories` · `cloned_from` 합 | 2,072 · 20,534 · 2,744 | **그대로** |
| `effect_types` 중 `SINGLE` | 14,731 | **14,732** |
| 그 밖의 모든 플래그 | | **그대로** |

code 종류별 변화는 **셋뿐**이다.

| code | 전 | 후 |
|---|---|---|
| `EFFECT_INDESTRUCTABLE_COUNT` | 95 | 94 |
| `EFFECT_SET_ATTACK` | 93 | 94 |
| `EVENT_SPSUMMON_SUCCESS` | 2,117 | 2,118 |

🔴 **ordinal 이 변한 카드는 세 장이고 전부 추적했다** (§9). `ordinal` 0 이 바뀐 카드는
**0장**이다.

### 14.1 Invariant 1~7

| | 내용 | 결과 | 테스트 |
|---|---|---|---|
| 1 | Lua 생성 순서 = parser ordinal | 🟢 | `test_04` · `test_11` |
| 2 | `CreateEffect` 하나당 effect 하나 | 🟢 | `test_02` · `test_05` |
| 3 | 중간 effect 누락 없음 | 🟠 **1건 예외** (`c39114494`, 보조 함수) | `test_13` |
| 4 | 누락으로 ordinal 이 밀리지 않음 | 🟢 | `test_14` · `test_16` |
| 5 | `EffectRef(card_id, n)` = n번째 | 🟢 | `test_12` |
| 6 | Clone / CreateEffect 식별 규칙 충돌 없음 | 🟢 | `test_08` · `test_09` |
| 7 | `initial_effect` 관계 유지 | 🟢 | `test_10` |

---

## 15. 실제 카드 검증

| 카드 | 확인 |
|---|---|
| `c9839115` 월롱룡 바그나와 | 3블록 · `ordinal` 0/1/2 전부 `resolve()` 성공 · `code` 가 각자 제 값 |
| `c74506079` | 5블록 · `effect_refs` = `[0,1,2,3,4]` · 세 `e1` 이 `categories` 로 구별 |
| `c9409625` | 4블록 · 주석 안 코드가 `effects` 에 없고 `effect_codes` 에는 남아 있다 |
| `c5795980` | `e3` 가 `local` 없이 있지만 `tc:` 에 등록 → **여전히 세지 않는다** |
| `c84544192` | `local ge1` 이 `ordinal` 0 자리에 있지만 전역 → 세지 않는 것이 맞다 |
| 등록된 16장 | §10 — 전부 전후 동일 |
| 전역 효과 표본 15장 | `Duel.RegisterEffect` → 전부 세지 않음 |

---

## 16. production 영향

production diff 는 **두 파일**뿐이다 (`test_36`).

| 파일 | 성격 |
|---|---|
| `sources/lua_loader.py` | 블록 탐지 · 주석 제거 · 캐시 서명 |
| `analysis/effect_analyzer.py` | 같은 탐지를 로더에서 import (§13.2) |

`analysis` 쪽 출력 변화도 **같은 3스크립트뿐**이다 (`_collect_handlers` 전수 비교).

---

## 17. Engine 영향

**없다.** Engine V1 freeze 유지.

- `engine/` 이 diff 에 **없다** (`test_30`).
- `engine/` · `agent/` 가 `EffectSpec` 고유 칸(`effect_types` · `cloned_from` ·
  `count_limit` · `target_ranges`)을 **0회** 읽는다.
- `CardDefinitionView` 26칸에 블록 내용 칸이 **없고** `effect_count` 만 있다.

🔴 **정정** — 처음에는 테스트에 *"`code` 도 `engine/` 에 0회"* 라고 적었다. **틀렸다.**
`engine/` 에 `.code` 속성 접근이 **59곳** 있고, 그것들은 `EffectSpec.code` 가 아니라
거부 사유 코드 등 **다른 것의 `code`** 다. 이름이 겹친다는 것은 사용의 증거가 아니므로
`EffectSpec` 에서만 오는 이름으로 다시 측정했다. 테스트 docstring 에도 적어 두었다.

---

## 18. AI / Search 영향

**없다.**

- `agent/` 전체가 diff 에 **없다** (`test_29`).
- `core/card_search.py` · `core/query_parser.py` · `core/card_repository.py` ·
  `agent/search.py` 가 diff 에 **없다** (`test_28`).
- 6판 **611결정** digest 불변 (`test_26`). 기대값을 손으로 적지 않고, 다른 테스트 파일이
  이미 고정해 둔 값을 AST 로 읽어 **가장 많이 고정된 것**을 쓴다 (7개 이상 요구).

---

## 19. state_hash / RNG / digest / hidden-info

| 항목 | 결과 | 테스트 |
|---|---|---|
| `state_hash` | 같은 seed 동일 · 다른 seed 상이 | `test_24` |
| RNG | 같은 seed 에서 난수열 12개 동일 | `test_25` |
| digest | 6판 611결정 동일 | `test_26` |
| hidden-info | `CardDefinitionView` 26칸, 블록 내용 칸 0 | `test_27` |

---

## 20. 테스트 결과

### 20.1 신규

`tests/test_create_effect_ordinal_audit.py` — **36개**. 지시서 §19 의 1~30 을 전부 덮고
6개를 더했다 (주석 제거 · analyzer 정합 · corpus diff · 건너뛴 자리 전수 분류 ·
`local` 관례 유지 · production 범위).

### 20.2 기존 테스트 갱신 — 18개

삭제 0 · skip 추가 0 · assertion 약화 0. **왜 기존 기대값이 움직였는지** 를 전부
해당 테스트의 주석/docstring 에 적었다.

| # | 테스트 | 전 → 후 | 왜 |
|---|---|---|---|
| 1 | `effect_type_quick::test_07` | `differing` 1 → **0** | 🔴 남아 있던 그 1건이 바로 이 Phase 가 고친 것. **결론이 강해졌다** (누적 ↔ 교체가 corpus 전체에서 일치) |
| 2 | `effect_type_quick::test_08` | 0 → 189 (복구) | 🔴 **헬퍼 결함** — 테스트의 `replace_rule` 이 production 정규식을 **그룹 번호로** 읽는데, `local` 포획 그룹이 생겨 번호가 밀려 문자열 `"local"` 을 변수명으로 집고 있었다 |
| 3 | `effect_type_quick::test_09` | `SINGLE` 14,731 → **14,732** | 새로 세는 두 블록이 `SINGLE`, 사라진 한 블록도 `SINGLE` (+2 −1) |
| 4 | `effectdefinition_activation::test_01` | `TOTAL_BLOCKS` 34,631 → **34,632**, `(False,False)` 11,626 → **11,627** | 블록 +1. 나머지 세 범주와 `WITH_*` · `FREE_CHAIN_*` 은 **그대로** |
| 5 | `effectdefinition_activation::test_06` | 1,419 → 1,419 (복구) | 🔴 **정합 결함** — `analysis` 가 로더와 어긋나 핸들러가 밀렸다. §13.2 로 복구 |
| 6 | `event_context::test_08` | 6,684 → 6,684 (복구) | 같은 원인 |
| 7 | `event_free_chain_semantic::test_01` | 34,680 → **34,681** | 블록 +1. `EVENT_FREE_CHAIN` 블록 4,914 는 **그대로** |
| 8 | `event_free_chain_semantics::test_03` | TRAP 블록 4,745 → **4,744** | `c9409625` (함정) 이 주석 안 블록 하나를 잃었다 |
| 9 | `event_phase_semantics::test_06~09` | 0 → 복구 | 🔴 **헬퍼 결함** — #2 와 같은 그룹 번호 문제 |
| 10 | `setcode_provenance::test_17` | 🔴 "덮어쓰기가 남아 있다" → **"고쳐졌다"** | 🔴 그 docstring 이 *"고치는 Phase 는 이 테스트를 의도적으로 갱신해야 한다"* 고 적어 둔 그 갱신 |
| 11 | `setcode_provenance::test_19` | `v5` → **`v6`** | 🔴 **설계대로 걸렸다** — 파서를 고쳤으므로 접두사가 올라야 한다 |
| 12 | `settype_clone::test_12~14` | 복구 | 🔴 **헬퍼 결함** (`walk_replace_rule`) |
| 13 | `settype_clone::test_13` | `SetType` 호출 31,933 → **32,153** | `_RE_SETTER` 변수명 범위 확대. **위반 수는 둘 다 0 그대로** — 표본이 커졌을 뿐 |
| 14 | `settype_clone::test_19` | `differing` 1 → **0**, 34,680 → **34,681** | #1 과 같은 이유. **결론이 강해졌다** |
| 15 | `settype_clone::test_20` · `test_28` · `test_34` | `34,680` → **`34,681`** (×3) | 블록 +1 |
| 16 | `settype_clone::test_22` | `v5` → **`v6`** | #11 과 같은 이유 |
| 17 | `settype_clone::test_33` | `e1` 블록 1개(흘린 값) → **2개(각자 제 값)** | 🔴 흘림 자체가 사라졌다. **모순 0건이라는 주장은 그대로이고 강해졌다** |
| 18 | `settype_clone::*_TOTAL` | `ranges` −1 · `properties` −2 · `count_limit` −1 · `code` +1 | §14 의 내역 그대로 |
| 19 | `special_summon_event_foundation::test_15` | 34,631→34,632 · 30,084→30,085 · SUMMON 5,979→**5,980** · `EVENT_SPSUMMON_SUCCESS` 2,114→**2,115** | 🔴 흘러들었던 유발 코드가 제 블록으로 돌아왔다 |
| 20 | `trigger_condition_separation::test_03` | 34,631→34,632 · 30,084→30,085 · `EVENT_*` 16,381→**16,382** | 같은 이유. `EVENT_*` 종류 70 은 그대로 |

🔴 **갱신 중 네 건은 "숫자가 움직인 것" 이 아니라 "테스트가 깨진 것"** 이었다 (#2 · #5 ·
#6 · #9 · #12). 두 종류가 섞여 있었다.

- **헬퍼의 그룹 번호 결합** — 테스트 세 파일이 production 정규식을 `match.group(1)` 로
  읽고 있었다. 정규식에 그룹을 추가하면 **조용히 깨진다.** 그룹 번호를 맞추고, 더불어
  production 과 **같은 흐름**이 되도록 블록 주석 제거와 `_is_card_effect` 판정도 함께
  반영했다.
- **`analysis` 정합** — §13.2 의 C 판정 그 자체다. 이 두 테스트(#5 · #6)가 **그 버그를
  잡아냈다.**

### 20.2.1 🔴 내 실수 하나 — 네 번째 commit 이 생긴 이유

신규 테스트의 `_changed_files()` 를 **"이 파일을 추가한 commit 과 그 부모"** 로 잡았다.
이 Phase 는 작업 · 테스트 · 보고서를 **나눠 커밋**하므로 그 범위에는 작업 commit 의
production 변경이 들어오지 않는다 — `test_36` 이 빈 집합을 받았다. `test_28` · `test_29`
· `test_30` 은 "없음" 을 보는 쪽이라 **통과해서 가려졌다.**

제목이 `Phase 3-F-28:` 으로 시작하는 commit 들을 찾아 *가장 오래된 것의 부모 → 가장 최근
것* 을 범위로 쓰도록 바꿨고, `기존 commit rewrite 금지` 에 따라 amend 하지 않고 **네 번째
commit** (`Phase 3-F-28: anchor the audit diff range to the Phase commits`) 으로 남겼다.
`HEAD` 를 쓰지 않으므로 다음 Phase 가 production 을 건드려도 깨지지 않는다.

교훈: **"없음" 을 보는 테스트는 측정 범위가 비어 있어도 통과한다.** 범위를 만드는 코드는
"무엇이 있어야 한다" 를 보는 테스트로 같이 검증해야 한다.

### 20.3 전체 회귀

현재 HEAD 에서 전체 pytest 를 실행했다 (`python -m pytest -q -p no:randomly`).

```
4802 passed, 4 skipped in 795.83s (0:13:15)
```

| 기준 | 결과 |
|---|---|
| 3-F-27 baseline | 4,766 passed / 4 skipped |
| 이번 Phase | **4,802 passed / 4 skipped** |
| 차이 | **+36** = 신규 테스트 36개 그대로 |
| 예상하지 않은 failure | **0** |
| 삭제 | **0** |
| skip 추가 | **0** (4개 그대로 — `requires_official_db` 계열) |
| assertion 약화 | **0** (§20.2 의 18건은 전부 "숫자가 왜 움직였는지" 를 적고 기대값을 **정확한 새 값**으로 옮긴 것이고, 4건은 **더 강해졌다**) |
| 기존 정상 EffectRef 유지 | 🟢 등록된 16개 전부 동일 (§10) · 12,699 스크립트 완전 동일 (§14) |
| `state_hash` · RNG · digest · hidden-info | 🟢 §19 |
| Search / AI | 🟢 §18 |
| Engine V1 freeze | 🟢 §17 |

중간 과정도 그대로 적어 둔다 — 수정 직후 1차 전체 회귀는 **27 failed / 4,739 passed**
였다. 그중 9개는 헬퍼의 그룹 번호 결합, 2개는 `analysis` 정합 결함, 16개는 실제 숫자
이동이었다 (§20.2).

---

## 21. 최종 판정

**A. CONFIRMED_CREATE_EFFECT_OMISSION** — `local` 없는 / 이름이 `e` 로 시작하지 않는
`CreateEffect` 중 **이 카드에 등록되는 2건**이 실제로 누락됐다. 하나는 설정자가 앞 블록으로
흘러들어 `code` 를 덮었고(`c9839115`), 하나는 블록이 아예 없어 뒤 세 블록의 `ordinal` 이
밀려 있었다(`c74506079`).

**+ C. CONFIRMED_DOWNSTREAM_REFERENCE_BUG** — `analysis/effect_analyzer.py` 가 같은 탐지
규칙을 **따로 복사해** 갖고 있어서, 로더만 고치면 블록 순번 짝짓기가 어긋난다. 우연히
일치하던 두 복사본이 수정 직후 **3개 스크립트에서 갈라졌고**, 기존 테스트 두 개가 그것을
잡아냈다.

**B 가 아니다** — 발견된 블록의 `ordinal` 이 틀린 경우는 **0건**이다 (D 분류 0).
**D 가 아니다** — stale cache 는 **동반 문제**였고 유일한 문제가 아니었다.
**E/F 가 아니다** — `local` 없는 `CreateEffect` 자체는 Lua 상 정상이지만, 파서가 그것을
**발견 조건으로 요구한 것**이 실제 누락을 만들었다.

지시서의 `A/B/C/D 라면 필요한 범위에서 최소 수정한다` 에 따라 **두 파일만** 고쳤다.

---

## 22. 남은 구조적 위험

1. 🟠 **보조 함수가 만드는 effect 를 파서가 모른다.** `Fusion.CreateSummonEff` 45곳 ·
   `Ritual.CreateProc` 20곳 · `Ritual.AddProcGreater` 5곳. 그래서 `c39114494` 의
   `e4=e3:Clone()` 이 **부모를 못 찾는다** (Invariant 3 의 유일한 예외).
   `local` 과 무관한 **별개의 한계**이고 이 Phase 의 범위 밖이므로 **추측해서 구조화하지
   않고 숫자로 고정만 했다** (`test_13`).
2. 🟠 **`c:RegisterEffect` 는 텍스트 증거다.** 조건 분기 안에서만 등록되는 효과도 "등록
   된다" 로 읽는다. 지금 그렇게 보강되는 블록이 **둘**이라 영향이 없지만, 스크립트가
   늘어나면 재검토가 필요하다.
3. 🟠 **파일 전체 긁기 7칸이 여전히 블록 주석을 본다** (`effect_codes` 등). 설계상
   "스크립트에 등장한 상수" 라 의도적이지만, 그 칸을 "이 카드가 실제로 쓰는 코드" 로
   읽는 소비자가 생기면 틀린다. production 주석에 적어 두었다.
4. 🟠 **캐시 서명에 파서 버전이 여전히 없다.** 두 Phase 연속으로 손으로 올렸다
   (`v4`→`v5`→`v6`). `test_setcode_provenance_audit::test_19` 가 지키고 있지만,
   근본적으로는 파서 코드 해시를 서명에 넣는 것이 맞다.
5. 🟠 **`EffectSpec.index` 가 유일하지 않다.** `c74506079` 는 `e1` 이 세 번, `c9839115` 는
   두 번 나온다. `index` 로 블록을 찾는 코드는 전부 틀린다 — 3-F-27 에서 실제로 한 번
   당했다.
6. 🟠 **3-F-27 이 적어 둔 형제 칸 결함이 그대로다** — `categories` 24 · `properties` 19 ·
   `target_ranges` 9 · `ranges` 12 블록에서 `Clone` 이 물려준 값과 자기 값이 누적된다.

---

## 23. Commit

| commit | 내용 |
|---|---|
| `32936b0` | `Phase 3-F-28: fix CreateEffect ordinal tracking` — `sources/lua_loader.py` · `analysis/effect_analyzer.py` |
| `771b30e` | `Phase 3-F-28: update CreateEffect audit tests` — 신규 36개 + 기존 18개 갱신 |
| `c0724ef` | `Phase 3-F-28: anchor the audit diff range to the Phase commits` — §20.2.1 의 내 실수 수정 |
| (이 문서) | `Phase 3-F-28: document CreateEffect ordinal audit` |

기존 commit 은 rewrite 하지 않았다.

---

## 24. 다음 Phase 후보 1개

**Phase 3-F-29 — `Clone` 의 형제 칸 누적 감사 및 최소 수정**
(`categories` · `properties` · `target_ranges` · `ranges`)

3-F-27 이 `effect_types` 에서 확인하고 고친 **같은 유형의 결함**이 네 칸에 그대로 남아 있고
(총 64블록), 3-F-27 의 `test_29` 가 그것을 숫자로 고정해 두었다. `effect_types` 때와 똑같이
"한 호출 안에서 그 조합을 적는 카드가 있는가" 를 corpus 로 물어 **교체인지 누적인지**를
저장소 내부 증거만으로 판정할 수 있다. 범위가 좁고(파서 한 함수), 영향 범위를 전수
비교로 닫을 수 있고, engine 이 그 네 칸을 읽지 않는다는 것도 이미 확인되어 있다.
