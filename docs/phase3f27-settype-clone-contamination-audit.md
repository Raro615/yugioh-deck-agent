# Phase 3-F-27 — Lua `SetType` 누적/`Clone` 오염 감사 및 최소 수정

> **실제 parser correctness 수정.** 3-F-24 ~ 3-F-26 과 달리 이번에는
> production 코드를 고쳤다 — `sources/lua_loader.py` 한 곳.

---

## 1. 실제 HEAD / Base — `git` 으로 검증

| 항목 | 지정값 | 실제 확인 | 결과 |
|---|---|---|---|
| 3-F-26 작업 commit | `228b7e0` | `228b7e0` Phase 3-F-26: audit EFFECT_TYPE_QUICK_0 semantics | ✅ |
| 3-F-26 테스트 수정 commit | `a9ea4cc` | `a9ea4cc` Phase 3-F-26: fix two audit tests broken by the docstring change | ✅ |
| 3-F-26 보고서 commit | `9b34c20` | `9b34c20` Phase 3-F-26: document EFFECT_TYPE_QUICK_0 audit | ✅ |
| 작업 시작 HEAD | — | `9b34c20` | ✅ |
| worktree | — | `git status --short` 출력 없음 · `git diff --stat` 없음 | ✅ clean |
| `origin` 동기 | — | `HEAD == origin/claude/pensive-goodall-te1egy` | ✅ |

기존 commit rewrite 없음.

---

## 2. 문제 재현 — **코드를 고치기 전에**

사양서가 요구한 최소 사례를 실제 `parse_lua_source` 경로로 돌렸다.

### 재현 ①

```lua
local e1=Effect.CreateEffect(c)
e1:SetType(EFFECT_TYPE_IGNITION)
local e2=e1:Clone()
e2:SetType(EFFECT_TYPE_QUICK_O)
```

| 측정 | 수정 전 | 수정 후 |
|---|---|---|
| `e1.effect_types` | `['IGNITION']` | `['IGNITION']` |
| `e2.effect_types` | 🔴 **`['IGNITION', 'QUICK_O']`** | ✅ `['QUICK_O']` |
| `e2.cloned_from` | `'e1'` | `'e1'` |
| `e1`/`e2` 블록 수 | 2 | 2 |
| `index` | `e1` · `e2` | 변화 없음 |
| `id(e1)` vs `id(e2)` | **다름** | 다름 |
| `id(e1.effect_types)` vs `id(e2.effect_types)` | **다름** | 다름 |

### 재현 ② — 3단 `Clone`

```lua
e1:SetType(IGNITION) → e2=e1:Clone(); e2:SetType(QUICK_O) → e3=e2:Clone(); e3:SetType(TRIGGER_F)
```

| 블록 | 수정 전 | 수정 후 |
|---|---|---|
| `e1` | `['IGNITION']` | `['IGNITION']` |
| `e2` | `['IGNITION', 'QUICK_O']` | `['QUICK_O']` |
| `e3` | 🔴 **`['IGNITION', 'QUICK_O', 'TRIGGER_F']`** | ✅ `['TRIGGER_F']` |

세 개는 **상호배타 발동 분류**다 (3-F-26 이 측정). 한 블록에 셋이 들어가는 것은
어떤 카드도 적지 않는다.

### 대조군 — 바뀌지 않아야 하는 것들

| 사례 | 수정 전 | 수정 후 |
|---|---|---|
| `Clone` 후 `SetType` **없음** | `e2 = ['IGNITION']` | 같음 ✅ |
| 한 호출 OR `SetType(FIELD+TRIGGER_O)` | `['FIELD','TRIGGER_O']` | 같음 ✅ |
| `Clone` **없이** `SetType` 두 번 | `['IGNITION','QUICK_O']` | 같음 ✅ |
| 부모를 자식이 **다시 적음** | `['SINGLE','TRIGGER_O']` | 같음 ✅ |

> 🔴 **마지막 대조군이 중요하다.** `Clone` 이 없어도 같은 변수에 `SetType` 을 두 번
> 부르면 **같은 누적이 재현된다.** 그러므로 이것은 "Clone 오염" 이 아니라
> **설정자 누적**이다 — 판정 B 의 근거다.

---

## 3. parser 경로 — 실제 코드

```
c<id>.lua (원문)
  ↓  sources/lua_loader.LuaScriptSource.iter_script_files
  ↓  sources/lua_loader.parse_lua_source(card_id, file_name, source)
        · _RE_CREATE_EFFECT  → "create" 이벤트   (🔴 `local` 을 요구한다)
        · _RE_CLONE_EFFECT   → "clone"  이벤트
        · _RE_SETTER         → "set"    이벤트
        · 위치(offset)로 정렬해 **한 번에** 훑는다
        · bindings: dict[변수명, EffectSpec]
  ↓  core.card_model.EffectSpec   (index · effect_types · code · ranges …)
  ↓  core.card_model.LuaScriptInfo.effects
  ↓  core.card_repository.CardRepository._attach_scripts  →  Card.script
  ↓  analysis.effect_analyzer   →  EffectAnalysis.effect_types
  ↓  core.card_search.has_effect_code  (검색 필터)
  ✗ engine 으로 가는 간선이 없다 (3-F-26 이 확정)
```

### `effect_types` 라는 이름이 **어디에 있는가**

| 객체 | `effect_types` | 비고 |
|---|---|---|
| parser 내부 상태 | ❌ 별도 객체 없음 | `EffectSpec` 을 **직접** 채운다. Lua 객체를 모사하는 중간 표현이 없다 |
| `core.card_model.EffectSpec` | ✅ **있다** (9칸 중 하나) | 이 Phase 가 고친 값이 담기는 곳 |
| `analysis.effect_model.EffectAnalysis` | ✅ 있다 (19칸) | `EffectSpec` 에서 복사 |
| `rules.structured.StructuredRules` | ✅ 있다 | 🔴 **공식 룰북의 효과 종류 5종** — 이름만 같다 |
| `engine.effect.definition.EffectDefinition` | ❌ **없다** (10칸) | 3-F-26 이 확정 |
| `engine.trigger.TriggerSpec` | ❌ 없다 | |
| `engine.game_state_view.CardDefinitionView` | ❌ 없다 (26칸) | engine 은 **볼 수조차 없다** |

> **parser 내부 type state ≠ `EffectSpec` ≠ `EffectDefinition`** — 가운데 것만
> 존재하고, 이 Phase 는 그것만 건드렸다.

---

## 4. `Clone` / `SetType` 구현 분석

### `Clone` 분기 (수정 전후 동일)

```python
elif kind == "clone":
    dst, src = payload.split("=", 1)
    parent = bindings.get(src)
    spec = EffectSpec(index=dst, cloned_from=src)
    if parent is not None:
        # Clone() 은 원본 속성을 물려받은 뒤 일부만 덮어쓴다.
        spec.effect_types = list(parent.effect_types)   # ← 새 리스트
        spec.code = parent.code
        spec.ranges = list(parent.ranges)
        ...
```

### `SetType` 분기 (수정 전)

```python
if setter == "Type":
    spec.effect_types = _strip_prefix(
        spec.effect_types + _RE_EFFECT_TYPE.findall(args)   # ← 🔴 더하기
    )
```

### `SetCode` 분기 — **같은 위험을 이미 고쳐 두었다**

`"Code"` 분기에는 Phase 3-E-18 의 수정이 주석까지 달려 있다.

> *"여기서 **앞 값을 그대로 두면 안 된다.** `Clone` 은 부모의 `code` 를
> 물려받으므로, 물려받은 값이 남은 채 스크립트가 분명히 덮어쓴 코드를 계속
> 주장하게 된다 … 읽지 못한 것은 **모른다**(`None`)로 되돌린다."*

`"Type"` 분기에는 그 처리가 **없었다.** 같은 결함 유형이 한 칸에서는 고쳐지고
다른 칸에서는 남아 있었다.

---

## 5. mutable state / aliasing 분석 — §4 의 A~G

| 질문 | 답 | 근거 |
|---|---|---|
| **A.** `Clone` 자체가 얕은 복사인가? | **아니다** | 리스트 다섯 칸을 전부 `list(...)` 로 새로 만든다 |
| **B.** type container 가 공유되는가? | **아니다** | `id(e1.effect_types) != id(e2.effect_types)`. corpus 전수로 **34,680블록 × 5칸 = 173,400개 컨테이너가 모두 서로 다른 객체**다 (`test_20`) |
| **C.** `SetType` 이 교체하는가? | **아니었다** | 더하기였다 |
| **D.** `SetType` 이 더하는가? | **그렇다** | `spec.effect_types + findall(args)` |
| **E.** `Clone` 후 `SetType` 이 **원본까지** 바꾸는가? | **아니다** | `e1` 은 `['IGNITION']` 그대로. 사후에 자식 리스트를 건드려도 부모가 따라오지 않는다 (`test_05`) |
| **F.** parser 가 `Clone` 과 별도로 잘못 누적하는가? | **그렇다** | `Clone` 없이 `SetType` 두 번만으로 재현된다 (`test_09`) |
| **G.** 🔴 **Lua 의미 vs parser 내부 표현 — 어느 쪽인가?** | **parser 내부 표현** | 아래 |

### G 의 근거 — **저장소 내부 증거만** 쓴다

EDOPro `SetType` API 의 정확한 의미는 이 저장소에 문서화돼 있지 않다. 그래서
Lua 의미를 추측하지 않고 corpus 로만 판단했다.

| 근거 | 측정값 |
|---|---|
| ① 누적이 **상호배타 조합**을 만드는 블록 | 77건 중 **76건** (적용 범위 25 · 발동 분류 51) |
| ② 그 조합을 **한 `SetType` 호출**에 적는 카드 | **31,933건 중 0건** |
| ③ 부모 플래그를 유지하는 유일한 블록이 그것을 **다시 적는다** | `c4928565` `e4` — `SINGLE+TRIGGER_O` 를 그대로 재기재 |
| ④ 같은 위험을 `code` 는 3-E-18 이 **이미 고쳤다** | `"Code"` 분기의 주석 |

②가 결정적이다. 적용 범위(`SINGLE`/`FIELD`/`EQUIP`)와 발동 분류
(`ACTIVATE`/`IGNITION`/`TRIGGER_O`/`QUICK_O`/`TRIGGER_F`/`QUICK_F`/`CONTINUOUS`)는
각각 **한 블록에 하나만** 온다 — 그것이 corpus 전수의 모양이다. 누적은 그 모양을
깨뜨린다.

③도 강하다. 더하기라면 자식이 부모 플래그를 **다시 적을 이유가 없다.**

---

## 6. 실제 corpus 통계 — 현재 HEAD 에서 재측정

3-F-26 의 숫자를 베껴 쓰지 않고 다시 계산했다.

| 측정 | 값 |
|---|---|
| 전체 스크립트 | **12,702** |
| 전체 효과 블록 | **34,680** |
| `SetType` 호출 수 | **31,933** |
| `Clone` 호출 수 | **2,744** |
| `Clone` 직후 자기 `SetType` 이 있는 블록 | **77** |
| 같은 블록에 `SetType` 2회 이상 | **1** |
| 🔴 교체 규칙과 결과가 달라지는 블록 | **78** / 스크립트 **75** |
| 그중 `QUICK_O` 관련 | **46** (전부 `Clone` 유래) |

### 78 의 원인 분해

| 원인 | 블록 |
|---|---|
| `Clone` 상속 + 자기 `SetType` 1회 | **76** |
| `Clone` 상속 + 자기 `SetType` **0회** (부모가 오염돼 **연쇄**) | **1** |
| 🔴 `Clone` **아님** + `SetType` 2회 | **1** (`c9839115`) |

> 🔴 **false positive 1건.** 마지막 1건은 **다른 원인**이다 — `c9839115.lua:78` 이
> `local` **없이** `e1=Effect.CreateEffect(c)` 로 대입하고, `_RE_CREATE_EFFECT` 가
> `local` 을 요구하므로 파서가 **새 블록으로 보지 않는다.** 그래서 그 뒤
> 설정자가 **이전 바인딩으로 흘러든다.**
>
> 그 블록에서 production 의 `effect_types` 는 `['SINGLE','TRIGGER_O']` 인데
> **우연히 맞다** (흘러든 `SetType(SINGLE)` 이 이미 있던 `SINGLE` 과 합쳐졌다).
> 실제로 틀린 것은 `code` 다 — `EVENT_SPSUMMON_SUCCESS` 가
> `EFFECT_UPDATE_ATTACK` 으로 덮였다.
>
> **"교체를 항상" 하면 이 블록에서 `TRIGGER_O` 를 잃는다.** 그래서 수정을
> `Clone` 유래로 **한정**했다 (§12).
>
> 같은 유형의 `local` 없는 대입은 corpus 에 **217곳 / 195파일** 있다.

### §6 의 다섯 유형 — 실제 사례와 함께

| 유형 | 설명 | 블록 수 | 실제 사례 |
|---|---|---|---|
| **A / E** | 같은 블록에 **한 호출로** 여러 type 지정 (정상) | **9,627** | `SINGLE+TRIGGER_O` 3,405 · `FIELD+TRIGGER_O` 1,866 · `CONTINUOUS+FIELD` 1,494 |
| **B** | `Clone` 이 부모 type 을 **정상 상속** (자기 `SetType` 없음) | **2,667** | `c39015` `e2`←`e1` = `['SINGLE']` |
| **C** | 🔴 `Clone` 한 블록에 새 type 을 적는데 **부모 type 이 남음** | **76** | `c324483` `e2`: `['IGNITION','QUICK_O']` |
| **D** | 🔴 parser 가 **이전 블록의 state 를 공유** (다른 원인) | **1** (+ 217 잠재) | `c9839115` `e1` — `local` 없는 `CreateEffect` |
| **E** | 실제 Lua 에서 명시적으로 여러 type | A 와 같다 | 위 |

---

## 7. 실제 `Clone` + `SetType` 사례 — **77건 전수 분류**

### QUICK_O 관련 46건 중 상위 26건

| # | script | 블록 | 상속 | 자식 `SetType` | before | after | 오염 |
|---|---|---|---|---|---|---|---|
| 1 | `c324483` | `e2`←`e1` | IGNITION | QUICK_O | `['IGNITION','QUICK_O']` | `['QUICK_O']` | ✅ 제거 |
| 2 | `c3134857` | `e4`←`e3` | IGNITION | QUICK_O | 〃 | `['QUICK_O']` | ✅ |
| 3 | `c4055337` | `e3`←`e2` | IGNITION | QUICK_O | 〃 | `['QUICK_O']` | ✅ |
| 4 | `c6351147` | `e2`←`e1` | **ACTIVATE** | QUICK_O | `['ACTIVATE','QUICK_O']` | `['QUICK_O']` | ✅ |
| 5 | `c6637331` | `e2`←`e1` | IGNITION | QUICK_O | 〃 | `['QUICK_O']` | ✅ |
| 6 | `c9212051` | `e2`←`e1` | ACTIVATE | QUICK_O | 〃 | `['QUICK_O']` | ✅ |
| 7 | `c10131855` | `e3`←`e2` | ACTIVATE | QUICK_O | 〃 | `['QUICK_O']` | ✅ |
| 8 | `c11646785` | `e3`←`e2` | IGNITION | QUICK_O | 〃 | `['QUICK_O']` | ✅ |
| 9 | `c12219047` | `e2`←`e1` | IGNITION | QUICK_O | 〃 | `['QUICK_O']` | ✅ |
| 10 | `c16428514` | `e3`←`e2` | IGNITION | QUICK_O | 〃 | `['QUICK_O']` | ✅ |
| 11 | `c20248754` | `e2`←`e1` | IGNITION | QUICK_O | 〃 | `['QUICK_O']` | ✅ |
| 12 | `c21441617` | `e2`←`e1` | IGNITION | QUICK_O | 〃 | `['QUICK_O']` | ✅ |
| 13 | `c23672629` | `e2`←`e1` | IGNITION | QUICK_O | 〃 | `['QUICK_O']` | ✅ |
| 14 | `c23756165` | `e2`←`e1` | IGNITION | QUICK_O | 〃 | `['QUICK_O']` | ✅ |
| 15 | `c24434049` | `e2`←`e1` | IGNITION | QUICK_O | 〃 | `['QUICK_O']` | ✅ |
| 16 | `c27541563` | `e3`←`e2` | ACTIVATE | QUICK_O | 〃 | `['QUICK_O']` | ✅ |
| 17 | `c29925614` | `e3`←`e2` | IGNITION | QUICK_O | 〃 | `['QUICK_O']` | ✅ |
| 18 | `c30741503` | `e3`←`e2` | IGNITION | QUICK_O | 〃 | `['QUICK_O']` | ✅ |
| 19 | `c33779875` | `e2`←`e1` | IGNITION | QUICK_O | 〃 | `['QUICK_O']` | ✅ |
| 20 | `c33854624` | `e2`←`e1` | IGNITION | QUICK_O | 〃 | `['QUICK_O']` | ✅ |
| 21 | `c34976176` | `e2`←`e1` | IGNITION | QUICK_O | 〃 | `['QUICK_O']` | ✅ |
| 22 | `c37706769` | `e2`←`e1` | IGNITION | QUICK_O | 〃 | `['QUICK_O']` | ✅ |
| 23 | `c38694052` | `e2`←`e1` | IGNITION | QUICK_O | 〃 | `['QUICK_O']` | ✅ |
| 24 | `c48835607` | `e3a`←`e3` | IGNITION | QUICK_O | 〃 | `['QUICK_O']` | ✅ |
| 25 | `c48835607` | `e4a`←`e4` | IGNITION | QUICK_O | 〃 | `['QUICK_O']` | ✅ |
| 26 | `c50140163` | `e2`←`e1` | IGNITION | QUICK_O | 〃 | `['QUICK_O']` | ✅ |

### QUICK_O 가 **아닌** 31건 — **전수**

| # | script | 블록 | 상속 | 자식 `SetType` | before | after |
|---|---|---|---|---|---|---|
| 1 | `c4928565` | `e4`←`e2` | SINGLE+TRIGGER_O | **SINGLE+TRIGGER_O** | `['SINGLE','TRIGGER_O']` | 🔴 **같음** — 부모를 다시 적었다 |
| 2 | `c13708888` | `e2`←`e1` | SINGLE+TRIGGER_O | FIELD+TRIGGER_O | `['SINGLE','TRIGGER_O','FIELD']` | `['FIELD','TRIGGER_O']` |
| 3 | `c20003027` | `e3`←`e1` | FIELD+TRIGGER_O | SINGLE+TRIGGER_O | `['FIELD','TRIGGER_O','SINGLE']` | `['SINGLE','TRIGGER_O']` |
| 4 | `c24087580` | `e4`←`e3` | SINGLE+TRIGGER_O | FIELD+TRIGGER_O | 〃 | `['FIELD','TRIGGER_O']` |
| 5 | `c28226490` | `e2`←`e1` | SINGLE+TRIGGER_O | FIELD+TRIGGER_O | 〃 | `['FIELD','TRIGGER_O']` |
| 6 | `c30037118` | `e2`←`e1` | SINGLE+TRIGGER_O | FIELD+TRIGGER_O | 〃 | `['FIELD','TRIGGER_O']` |
| 7 | `c30907810` | `e8`←`e6` | CONTINUOUS+FIELD | CONTINUOUS+SINGLE | `['FIELD','CONTINUOUS','SINGLE']` | `['SINGLE','CONTINUOUS']` |
| 8 | `c32909498` | `e4`←`e3` | SINGLE+TRIGGER_O | FIELD+TRIGGER_O | 〃 | `['FIELD','TRIGGER_O']` |
| 9 | `c39373426` | `e2`←`e1` | ACTIVATE | FIELD+TRIGGER_O | `['ACTIVATE','FIELD','TRIGGER_O']` | `['FIELD','TRIGGER_O']` |
| 10 | `c41867019` | `e3`←`e2` | ACTIVATE | FIELD+TRIGGER_O | 〃 | `['FIELD','TRIGGER_O']` |
| 11 | `c44632120` | `e2`←`e1` | SINGLE+TRIGGER_O | FIELD+TRIGGER_O | 〃 | `['FIELD','TRIGGER_O']` |
| 12 | `c47195442` | `e3`←`e2` | SINGLE+TRIGGER_F | FIELD+TRIGGER_F | `['SINGLE','TRIGGER_F','FIELD']` | `['FIELD','TRIGGER_F']` |
| 13 | `c49131917` | `e3`←`e2` | IGNITION | SINGLE+TRIGGER_O | `['IGNITION','SINGLE','TRIGGER_O']` | `['SINGLE','TRIGGER_O']` |
| 14 | `c49658464` | `e3`←`e2` | FIELD+TRIGGER_F | SINGLE+TRIGGER_F | 〃 | `['SINGLE','TRIGGER_F']` |
| 15 | `c56401775` | `e3`←`e1` | FIELD+TRIGGER_O | SINGLE+TRIGGER_O | 〃 | `['SINGLE','TRIGGER_O']` |
| 16 | `c57523313` | `e3`←`e1` | FIELD+TRIGGER_O | SINGLE+TRIGGER_O | 〃 | `['SINGLE','TRIGGER_O']` |
| 17 | `c59160188` | `e8`←`e6` | CONTINUOUS+FIELD | CONTINUOUS+SINGLE | 〃 | `['SINGLE','CONTINUOUS']` |
| 18 | `c61557074` | `e6`←`e5` | FIELD | SINGLE | `['FIELD','SINGLE']` | `['SINGLE']` |
| 19 | `c61681816` | `e2`←`e1` | SINGLE | FIELD | `['SINGLE','FIELD']` | `['FIELD']` |
| 20 | `c62849088` | `e4`←`e2` | FIELD+TRIGGER_O | SINGLE+TRIGGER_O | 〃 | `['SINGLE','TRIGGER_O']` |
| 21 | `c63259351` | `e2`←`e1` | SINGLE | FIELD | `['SINGLE','FIELD']` | `['FIELD']` |
| 22 | `c65326118` | `e3`←`e1` | SINGLE+TRIGGER_O | FIELD+TRIGGER_O | 〃 | `['FIELD','TRIGGER_O']` |
| 23 | `c68304193` | `e4`←`e3` | SINGLE+TRIGGER_O | FIELD+TRIGGER_O | 〃 | `['FIELD','TRIGGER_O']` |
| 24 | `c71036835` | `e2`←`e1` | SINGLE+TRIGGER_O | FIELD+TRIGGER_O | 〃 | `['FIELD','TRIGGER_O']` |
| 25 | `c81019803` | `e4`←`e2` | FIELD+TRIGGER_O | SINGLE+TRIGGER_O | 〃 | `['SINGLE','TRIGGER_O']` |
| 26 | `c83589191` | `e2`←`e1` | ACTIVATE | IGNITION | `['ACTIVATE','IGNITION']` | `['IGNITION']` |
| 27 | `c92530005` | `e3`←`e2` | IGNITION | FIELD+TRIGGER_O | `['IGNITION','FIELD','TRIGGER_O']` | `['FIELD','TRIGGER_O']` |
| 28 | `c93018428` | `e3`←`e1` | FIELD+TRIGGER_O | SINGLE+TRIGGER_O | 〃 | `['SINGLE','TRIGGER_O']` |
| 29 | `c94392192` | `e4`←`e3` | SINGLE+TRIGGER_O | FIELD+TRIGGER_O | 〃 | `['FIELD','TRIGGER_O']` |
| 30 | `c97692972` | `e4`←`e3` | SINGLE+TRIGGER_O | FIELD+TRIGGER_O | 〃 | `['FIELD','TRIGGER_O']` |
| 31 | `c98416533` | `e3`←`e1` | FIELD+TRIGGER_O | SINGLE+TRIGGER_O | 〃 | `['SINGLE','TRIGGER_O']` |

> 🔴 31건 중 **대부분이 적용 범위 교체**(`SINGLE`↔`FIELD`)다. 누적하면
> `SINGLE` 과 `FIELD` 가 **같은 블록에 공존**하는데, 그 조합은 한 `SetType`
> 호출에서 **0건**이다. 데이터가 그 자체로 모순을 가리킨다.

---

## 8. `QUICK_O` 영향 — §13

| 측정 | 수정 전 | 수정 후 |
|---|---|---|
| `QUICK_O` 블록 | **1,875** | **1,875** (같음) |
| `QUICK_O` 스크립트 | **1,712** | **1,712** (같음) |
| `QUICK_O` 보유 카드 | **1,781** | **1,781** (같음) |
| `('QUICK_O',)` 단독 | 1,821 | **1,867** |
| `('IGNITION','QUICK_O')` | 41 | **0** |
| `('ACTIVATE','QUICK_O')` | 5 | **0** |
| `('FIELD','QUICK_O')` | 4 | 4 (보존) |
| `('QUICK_O','XMATERIAL')` | 4 | 4 (보존) |
| 🔴 오염으로 `QUICK_O` 가 잘못 **추가**된 블록 | — | **0** |
| 🔴 오염으로 `QUICK_O` 가 **누락**된 블록 | — | **0** |

> **`QUICK_O` 자체는 추가되지도 사라지지도 않았다.** 누적은 플래그를
> **더하기만** 했으므로 `QUICK_O` 의 유무는 영향받지 않았다. 사라진 것은
> **잘못 물려받은 동반 플래그**뿐이다.

그래서 3-F-26 의 통계가 그대로 성립한다 — `QUICK_O` 카드의 공식 스펠 스피드
분포도 **1 → 13 · 2 → 414 · 3 → 16 · 미정 → 1,338** 로 변하지 않았다
(`test_24`). **3-F-26 의 `C. DATA_CLASSIFICATION_ONLY` 판정은 유지된다.**

---

## 9. `code` 와의 분리 — §8

이번 대상은 `SetType` · `Clone` · effect type state 뿐이다. `code` semantic 은
건드리지 않았다. 다만 사양서가 요구한 대로 **같은 parser state 를 공유하는지**는
조사했다.

| 항목 | 결과 |
|---|---|
| `code` 와 `effect_types` 가 같은 저장소를 쓰는가 | **아니다** — `EffectSpec` 의 **다른 칸**이고 설정자 분기도 다르다 (`"Code"` vs `"Type"`) |
| 같은 **위험**을 공유하는가 | **그렇다** — 둘 다 `Clone` 이 물려주고, 자기 설정자가 그 위에 온다 |
| `code` 는 어떻게 되어 있었나 | Phase **3-E-18** 이 이미 고쳤다. 읽지 못한 `SetCode` 뒤에 부모 값이 남는 블록 3개를 찾아 `None` 으로 되돌렸다 |
| 이 Phase 가 `code` 를 바꿨는가 | **아니다** — corpus 전수에서 `code` 총계 **30,126 불변**, 변경 블록 **0** (`test_34`) |
| `EVENT_FREE_CHAIN` 의미 | 3-F-25 의 **`C. LUA_INTERNAL_TAG`** 유지. 의미를 건드리지 않았다 |

🔴 다만 `c9839115` 에서는 **`code` 가 실제로 오염돼 있다** —
`EVENT_SPSUMMON_SUCCESS` → `EFFECT_UPDATE_ATTACK`. 원인은 `Clone` 이 아니라
`local` 없는 `CreateEffect` 이고, 이 Phase 의 범위가 아니다 (§6 · §20).

---

## 10. parser authoritative boundary — §9

| 수준 | 이 저장소에서 | 이번에 고친 범위 |
|---|---|---|
| **A. raw extraction** | `EffectSpec` — Lua 원문에 적힌 상수 **이름을 그대로** 담는다 (접두사 포함 문자열) | ✅ **여기만** |
| **B. normalized analysis** | `EffectAnalysis` — `trigger_event` · `effect_code` 등으로 **나눠 담는다** | ✗ |
| **C. semantic interpretation** | `engine/activation_timing.py` 의 `SpellSpeed` 등 | ✗ |

이 Phase 의 목표는 **A 수준의 정확성 하나**였다:

> *"Lua 에서 effect 1 과 effect 2 의 type 이 다르면 parser 에서도 다르게 보인다."*

공식 규칙 의미를 새로 부여하지 않았다 — `QUICK_O` → 스펠 스피드,
`EVENT_FREE_CHAIN` → Free Chain 같은 매핑을 만들지 않았고, parser 코드에
특정 플래그 이름이 **분기 조건으로 등장하지 않는다** (`test_25`).

---

## 11. 수정 설계 — §10

### 왜 이것이 Lua semantics 를 보존하는 **최소 수정**인가

1. **고치는 대상이 하나다.** `Clone` 이 물려준 목록이 자식의 명시적 `SetType` 을
   살아남는 것 — 그 한 가지다.
2. **`Clone` 유래로 한정한다.** `Clone` 이 아닌 경우의 "`SetType` 두 번" 의미는
   이 Phase 가 정하지 않는다. corpus 에 1건뿐이고 **그 1건은 다른 원인**
   (`local` 없는 `CreateEffect`)이므로, 거기까지 바꾸면 `c9839115` 의
   `TRIGGER_O` 를 **잃는다** (§6 · §12 의 C 분류 0건이 그 증거).
3. **첫 `SetType` 만 덮어쓴다.** 두 번째 이후는 기존 동작을 그대로 둔다 — 건드릴
   근거가 없는 동작은 건드리지 않는다.
4. **상속 자체는 보존한다.** `Clone` 후 자기 `SetType` 이 없으면 부모 type 이
   그대로 남는다 (2,667블록 — `test_17`).
5. **새 추상화가 없다.** `parse_lua_source` 안의 **함수 지역 dict** 하나뿐이다.
   새 enum · 새 public field · 새 클래스 · 새 모듈이 없다.
6. **`code` 의 선례를 그대로 따른다.** 같은 함수의 `"Code"` 분기가 같은 이유로
   같은 일을 한다 (3-E-18).

### 🔴 캐시 signature 를 **함께** 올려야 한다

`LuaScriptSource._signature()` 는 `f"v4:{파일수}:{최신mtime}"` 였다 — **파서
버전이 들어 있지 않다.** 그래서 파서를 고쳐도 스크립트 파일이 바뀌지 않으면
signature 가 같고, `load_cached` 가 **옛 캐시를 그대로 돌려준다.**

실험으로 확인했다 — 수정 전 캐시(`data/cache/lua_scripts.json`)는
`c324483` `e2` 를 `['IGNITION','QUICK_O']` 로 들고 있었고 signature 가 일치했다.
**signature 상승이 없으면 이 수정은 보이지 않는다.** `v4` → `v5` 로 올렸다.

---

## 12. 수정 내용 — §13

### `sources/lua_loader.py` — 세 곳 + signature

```python
# ① bindings 옆에 "물려받은 것인가" 지도를 둔다
inherited_types: dict[str, bool] = {}

# ② create — 자기 것으로 시작한다
inherited_types[var] = False

# ③ clone — 물려받았다고 표시한다
inherited_types[dst] = bool(spec.effect_types)

# ④ Type 설정자 — 물려받은 목록이면 덮어쓴다
if setter == "Type":
    found = _RE_EFFECT_TYPE.findall(args)
    if inherited_types.get(var):
        spec.effect_types = _strip_prefix(found)      # ← 교체
        inherited_types[var] = False
    else:
        spec.effect_types = _strip_prefix(spec.effect_types + found)   # ← 기존대로

# ⑤ signature
return f"v5:{count}:{newest:.0f}"
```

판단 근거는 **주석으로 코드 안에 남겼다** (측정값과 실제 카드 포함).

### `core/card_model.py` — docstring 만

`EffectSpec.effect_types` 의 설명이 3-F-26 시점의 **결함 기록**이었다. 고쳐진
뒤의 서술로 갱신하고, **아직 남은 형제 칸 결함과 `local` 없는 `CreateEffect`
문제**를 적었다. 문자열 리터럴을 벗긴 AST 가 base 와 **동일**하다.

### 변경 범위

| 파일 | 실행 코드 | 비고 |
|---|---|---|
| `sources/lua_loader.py` | ✅ **고쳤다** | 이번 Phase 의 대상 |
| `core/card_model.py` | ✗ docstring 만 | AST 동일 |
| `engine/**` · `agent/**` | ✗ **0 파일** | Engine V1 freeze 유지 |
| `EffectDefinition` · `EffectSpec` 의 칸 | ✗ 변경 없음 | 9칸 · 10칸 그대로 |

---

## 13. 수정 전/후 corpus diff — §19

**가장 중요한 검증.** 전체 34,680블록을 수정 전 스냅숏과 하나씩 비교했다.

| 분류 | 블록 |
|---|---|
| **A. 오염 제거** | **77** (스크립트 74) |
| **B. 정상 결과 유지** | **34,603** |
| **🔴 C. 예상하지 못한 변경** | **0** |
| **D. parser bug 가 아닌 실제 Lua semantics 차이** | **0** |
| `effect_types` **가 아닌 칸**이 바뀐 블록 | **0** |

### A 의 세부 — 제거된 플래그

| 플래그 | 제거된 블록 |
|---|---|
| `IGNITION` | **43** |
| `SINGLE` | **15** |
| `FIELD` | **11** |
| `ACTIVATE` | **8** |
| 합계 | **77** |

**77건 전부**가 상호배타 조합을 해소한다. 플래그가 **새로 생긴 블록은 0건**이고,
`Clone` 이 아닌 블록이 바뀐 것도 **0건**이다.

### 🔴 수정 후에도 교체 규칙과 다른 블록 — **1건**

`c9839115` `e1`: production `['SINGLE','TRIGGER_O']` vs 교체 규칙 `['SINGLE']`.

이것은 **의도한 결과**다. 그 블록은 `Clone` 이 아니고, `local` 없는
`CreateEffect` 가 흘린 `SetType(SINGLE)` 이 합쳐진 것이다. 교체를 **항상**
적용하면 **`TRIGGER_O` 를 잃는다** — 즉 교체-항상 규칙이 그 1건에서 **틀리다.**
수정을 `Clone` 유래로 한정한 이유가 바로 이것이다.

### 수정 후 모순 조합

corpus 전체에서 상호배타 조합을 가진 블록 **0건** (`test_33`). 수정 전에는
`Clone`+`SetType` 77블록 중 **76블록**이 모순이었다.

---

## 14. 실제 카드 검증 — §12

| # | 카드 | Lua | parser before | parser after | expected |
|---|---|---|---|---|---|
| 1 | `c324483` `e2` | `e1:SetType(IGNITION)` → `Clone` → `e2:SetType(QUICK_O)` | `['IGNITION','QUICK_O']` | **`['QUICK_O']`** | `['QUICK_O']` ✅ |
| 2 | `c6351147` `e2` | `ACTIVATE` → `Clone` → `QUICK_O` | `['ACTIVATE','QUICK_O']` | **`['QUICK_O']`** | ✅ |
| 3 | `c13708888` `e2` | `SINGLE+TRIGGER_O` → `Clone` → `FIELD+TRIGGER_O` | `['SINGLE','TRIGGER_O','FIELD']` | **`['FIELD','TRIGGER_O']`** | ✅ |
| 4 | `c20003027` `e3` | `FIELD+TRIGGER_O` → `Clone` → `SINGLE+TRIGGER_O` | `['FIELD','TRIGGER_O','SINGLE']` | **`['SINGLE','TRIGGER_O']`** | ✅ |
| 5 | `c47195442` `e3` | `SINGLE+TRIGGER_F` → `Clone` → `FIELD+TRIGGER_F` | `['SINGLE','TRIGGER_F','FIELD']` | **`['FIELD','TRIGGER_F']`** | ✅ |
| 6 | `c4928565` `e4` | `SINGLE+TRIGGER_O` → `Clone` → **같은 값 재기재** | `['SINGLE','TRIGGER_O']` | `['SINGLE','TRIGGER_O']` | **변화 없음** ✅ |
| 7 | `c39015` `e2` | `Clone` 후 `SetType` **없음** | `['SINGLE']` | `['SINGLE']` | **변화 없음** ✅ |
| 8 | `c102380` `e2` | `Clone` 후 `SetType` 없음 | `['FIELD']` | `['FIELD']` | **변화 없음** ✅ |
| 9 | `c176392` | 한 호출 OR `CONTINUOUS+FIELD` · `FIELD+TRIGGER_O` | 그대로 | 그대로 | **변화 없음** ✅ |
| 10 | `c759393` (화령사 히타) | `SINGLE+FLIP` | `['SINGLE','FLIP']` | 그대로 | **변화 없음** ✅ |
| 11 | `c48835607` `e3a`·`e4a` | **두 블록** 모두 `IGNITION`→`Clone`→`QUICK_O` | 둘 다 오염 | 둘 다 **`['QUICK_O']`** | ✅ |
| 12 | 🔴 `c9839115` `e1` | `local` **없는** `CreateEffect` | `['SINGLE','TRIGGER_O']` | 그대로 | **손대지 않았다** (범위 밖) |

---

## 15. `activation_timing` / Engine 영향 — §14

3-F-26 이 확정한 것이 **그대로 유지되는지** 다시 측정했다.

| 대상 | 판정 | 근거 |
|---|---|---|
| `EffectDefinition.effect_types` | **없다** (10칸) | `test_25` |
| `engine/**` 코드에 `effect_types` 등장 | **0회** (문자열 제거 AST) | `test_27` |
| `agent/**` 코드에 `effect_types` 등장 | **0회** | `test_27` |
| `CardDefinitionView` 에 그 칸 | **없다** (26칸) | `test_31` |
| `Duel.legal_actions()` | **DOES NOT READ** | `test_27` |
| `Duel.apply()` · `_activation_gate` | **DOES NOT READ** | `test_27` |
| `EffectActivator` · `ChainLink` · `ChainResolver` · `TriggerCandidate` | **DOES NOT READ** | 3-F-26 `test_19`~`test_25` 가 그대로 통과 |
| `activation_timing.classify_spell_speed` | `type_names` 등 **카드 종류만** 읽는다 | 3-F-26 `test_11` |

> 🔴 **그러므로 이 수정은 duel 실행 동작을 바꿀 수 없다.** engine 은 그 값을
> 읽지 않고 **볼 수조차 없다.** 영향은 **검색 필터(`core/card_search.py`)와
> 분석 출력 · CLI 표시**에 국한된다 — 그리고 그 영향은 "오염된 조합이 더 이상
> 검색에 걸리지 않는다" 는 **정확성 개선**이다.

---

## 16. AI / Search 영향 — §14

| 대상 | 판정 |
|---|---|
| Search candidate generation | **DOES NOT READ** |
| `RuleBasedPolicy` · 평가 · 휴리스틱 | **DOES NOT READ** |
| `GameStateView` / `CardDefinitionView` | 칸 자체가 **없다** |
| 검색/AI digest (6판 611결정) | **불변** (`test_32`) |

**AI/Search 변경 0.** 그리고 digest 불변이 "파서 데이터 수정이 duel 동작을
바꾸지 않는다" 의 **행동 증거**다.

---

## 17. `state_hash` / RNG / digest / hidden-info — §15

| 항목 | 결과 | 근거 |
|---|---|---|
| `state_hash` | ✅ 불변 | `test_30` — 같은 seed 동일, 다른 seed 상이 |
| RNG | ✅ 불변 | `test_30` — 뽑은 값 8개 비교 |
| replay/search digest | ✅ 불변 | `test_32` — 611결정 |
| hidden-information | ✅ 불변 | `test_31` — `CardDefinitionView` 26칸 그대로 |
| `GameStateView` | ✅ 불변 | 변경 0 파일 |
| Search | ✅ 불변 | `test_32` |
| AI | ✅ 불변 | `agent/` 변경 0 |
| Engine V1 freeze | ✅ 유지 | `engine/` 변경 **0 파일** |

---

## 18. 테스트 결과 — §16 · §17

### 신규 38개 — `tests/test_settype_clone_contamination_audit.py`

| # | 무엇을 재는가 | §16 항목 |
|---|---|---|
| 01 | 기본 `SetType` | 1 |
| 02 | `Clone` 만 — 상속 | 2 |
| 03 | 🔴 `Clone` + `SetType` — **교체** | 3 |
| 04 | 두 자식의 type 격리 | 4 |
| 05 | 🔴 원본 불변 + 컨테이너 독립 (상속만 하는 쌍까지) | 5 · 20 |
| 06 | 2단 `Clone` | 6 |
| 07 | 🔴 3단 `Clone` | 7 |
| 08 | 한 호출 OR 보존 | 8 · 14 |
| 09 | `Clone` 없는 복수 `SetType` — 기존 동작 유지 | 9 |
| 10 | `Clone` 후 `SetType` 2회 — 첫 번째만 교체 | 9 |
| 11 | 🔴 `local` 없는 `CreateEffect` — 범위 밖 버그 | 15 |
| 12 | 🔴 누적이 만드는 모순 77/76 (25 · 51) | 15 |
| 13 | 🔴 그 조합이 한 호출에 **0/31,933** | 15 |
| 14 | 🔴 부모를 유지하는 유일한 블록이 **다시 적는다** | 14 |
| 15 | `code` 는 3-E-18 이 이미 고쳤다 | — |
| 16 | 실제 `Clone` 카드 5장 (parametrize) | 10 · 11 · 16 |
| 17 | 상속만 하는 2,667블록 불변 + 실제 카드 2장 | 12 · 13 |
| 18 | 한 호출 OR · `FLIP` 카드 불변 | 13 · 14 |
| 19 | 🔴 **corpus diff — 다른 블록이 단 1개**이고 `Clone` 아님 | 30 |
| 20 | 🔴 173,400개 컨테이너가 **모두 다른 객체** | 20 |
| 21 | 파싱 determinism | 21 |
| 22 | 🔴 캐시 signature `v5` | — |
| 23 | 🔴 `QUICK_O` 블록·스크립트 수 **불변** | 16 |
| 24 | 🔴 공식 SS 분포 13/414/16 **불변** | 16 |
| 25 | 의미를 새로 부여하지 않았다 (새 enum/클래스 0) | — |
| 26 | production 변경이 파서 + docstring 뿐 | — |
| 27 | engine/agent 가 여전히 읽지 않는다 | 29 |
| 28 | 블록 수 · `index` · `cloned_from` 불변 | 17 · 18 |
| 29 | 🔴 형제 칸에 **같은 결함이 남아 있다** (12 · 9 · 24 · 19) | — |
| 30 | `state_hash` · RNG 불변 | 22 · 23 |
| 31 | hidden-info · `GameStateView` 불변 | 25 · 26 |
| 32 | digest 불변 (611결정) | 24 · 27 · 28 |
| 33 | 🔴 모순 조합 **0블록** | 19 |
| 34 | 🔴 형제 칸 corpus 총계 불변 | 19 |

실제 카드 **12장** 이상 사용 (§14 표).

### 🔴 기존 테스트 1개를 갱신했다 — 약화 아님

`tests/test_effect_type_quick_audit.py::test_07` (3-F-26 작) 이 깨졌다.
**결함이 고쳐졌기 때문**이다 — 그 테스트는 `accumulated[("IGNITION","QUICK_O")] == 41`
처럼 **결함의 존재**를 못 박고 있었다.

틀린 가정이 아니라 **고쳐진 사실**이므로, 단정을 "결함이 있다" 에서 **"결함이
사라졌고 정상 조합은 보존된다"** 로 바꿨다. 강도는 **올라갔다**:

* `accumulated == replaced` — QUICK_O 블록에서 두 규칙이 **완전히 일치**
* `differing == 1` 이고 그 1건이 **`Clone` 이 아니다**
* `FIELD+QUICK_O` 4 · `QUICK_O+XMATERIAL` 4 가 **양쪽 모두** 보존

`test_31` 도 함께 갱신했다 (`core/card_model.py` docstring 문구를 검증하므로).
**삭제 0 · skip 추가 0 · assertion 약화 0.**

### 전체 회귀

```
PHASE3F27_REGRESSION_PLACEHOLDER
```

### 🔴 고의 위반 주입 10건 — 전부 검출

2개 파일을 md5 로 백업하고 하나씩 심었다 되돌렸다. 각 주입은 **먼저 `import`
로 유효성을 확인**했다.

| # | 심은 위반 | 걸린 테스트 |
|---|---|---|
| 1 | 🔴 **수정을 되돌린다** (다시 더하기로) | `test_03` 외 **15개** |
| 2 | `Clone` 분기가 상속 표시를 하지 않는다 | `test_03` 외 15개 |
| 3 | 🔴 **항상** 교체한다 (더하기를 없앤다) | `test_07` `test_09` `test_10` `test_11` `test_19` `test_33` |
| 4 | 상속 표시를 내리지 않는다 (두 번째도 교체) | `test_10` |
| 5 | 🔴 signature 를 `v4` 로 되돌린다 | `test_22` |
| 6 | `Clone` 이 리스트를 **공유한다** (진짜 aliasing) | `test_05` `test_20` |
| 7 | 교체가 아니라 비우기만 한다 | `test_03` 외 12개 |
| 8 | 한 호출 OR 를 첫 플래그만 읽는다 | `test_08` 외 11개 |
| 9 | `card_model` 의 갱신된 docstring 을 되돌린다 | `test_31` |
| 10 | `Clone` 분기가 `categories` 를 복사하지 않는다 | `test_34` |

마지막 복원을 **md5 로 확인**했다 (2/2 OK).

#### 🔴 probe 를 세 번 빗맞혔고, 그 중 하나는 **진짜 공백**이었다

| 빗맞힌 주입 | 왜 안 걸렸나 | 조치 |
|---|---|---|
| `create` 분기가 상속 표시를 `True` 로 | **no-op 이었다** — 새 블록의 목록은 비어 있어 교체와 더하기가 같다. 나쁜 probe | 과녁을 "**항상** 교체" 로 바꿔 다시 주입 → `test_09` 가 잡았다 |
| `Clone` 이 리스트를 공유 | 교체가 **새 리스트**를 돌려주므로 공유가 그 자리에서 끊긴다. `test_05` 가 보던 쌍에서는 드러나지 않았다 | 🔴 `test_05` 를 **보강** — `SetType` 이 **없는** 상속 쌍의 컨테이너 독립성까지 본다 |
| `categories` 복사 삭제 | `test_29` 는 **Lua 원문**을 다시 걸어 세므로 production 을 보지 않는다 | 🔴 **진짜 공백** — `test_34` 를 **새로 추가**해 형제 칸의 production 총계를 고정했다 |

> **"주입이 걸리지 않았다" 를 "테스트가 약하다" 로 바로 읽지 않는다.** 먼저
> probe 가 주장한 일을 실제로 했는지 확인한다. 셋 중 둘은 나쁜 probe 였고
> 하나는 실제 공백이었다.

---

## 19. 최종 판정 — §21

> ## **B. CONFIRMED_PARSER_ACCUMULATION_BUG**
>
> `Clone` aliasing 은 아니지만 parser 가 effect type 을 잘못 누적했다.

### 왜 A 가 아닌가

`A. CONFIRMED_PARSER_CLONE_CONTAMINATION` 은 *"`Clone` 된 mutable state 를
**공유**하여"* 를 주장한다. **공유는 없었다** — `Clone` 분기가 `list(...)` 로
새 리스트를 만들고, corpus 전수에서 **173,400개 컨테이너가 모두 서로 다른
객체**다 (`test_20`). 자식의 변경이 부모에 닿지도 않는다 (`test_05`).

### 왜 C 가 아닌가

`C. LUA_SEMANTICS_MISREAD` 는 *"parser 문제가 아니라 Lua semantics 를 잘못
해석한 것"* 이다. parser 가 **스스로 모순된 출력**을 냈다 — 한 `SetType` 호출에
**0번** 나타나는 조합을 77블록 중 76블록에서 만들었다. Lua 의미를 알지 못해도
그 출력이 틀렸다고 말할 수 있다.

### 왜 D 가 아닌가

`D. FALSE_POSITIVE` 가 아니다. 다만 🔴 **78건 중 1건은 false positive 였다** —
`c9839115` 는 `Clone` 이 아니라 `local` 없는 `CreateEffect` 가 원인이고, 교체를
항상 적용하면 그 블록에서 **`TRIGGER_O` 를 잃는다.** 그래서 수정을 `Clone`
유래로 한정했고, 결과적으로 **77건만** 바뀌었다.

### A/B 이므로 **최소 수정했다**

`sources/lua_loader.py` 한 곳 + 캐시 signature. 실행 코드로 치면 약 6줄이다.

---

## 20. 남은 구조적 위험

| 등급 | 내용 | 측정값 |
|---|---|---|
| 🔴 | **`local` 없는 `CreateEffect` 가 설정자를 흘린다.** 파서가 새 블록으로 보지 않아 **이전 바인딩**에 설정자가 쌓인다. `c9839115` 에서 `code` 가 실제로 오염돼 있다 (`EVENT_SPSUMMON_SUCCESS` → `EFFECT_UPDATE_ATTACK`) | **217곳 / 195파일** |
| 🔴 | **형제 칸에 같은 누적 결함이 남아 있다.** `Clone` 뒤 자기 설정자를 부르면서 부모 값을 다시 적지 않은 블록 | `categories` **24** · `properties` **19** · `ranges` **12** · `target_ranges` **9** |
| 🟠 | **캐시 signature 가 파서 버전을 담지 않는 구조 자체**는 그대로다. 이번에는 `v4`→`v5` 로 올렸지만, 다음에 파서를 고치는 사람이 **올리는 것을 잊으면 조용히 옛 결과가 쓰인다.** `test_22` 가 `v5` 를 못 박아 "바꿀 때 알아차리게" 만든 것이 유일한 방어다 | — |
| 🟠 | **`EffectSpec.index` 가 고유하지 않다** (3-F-25 측정: 4,795 스크립트 / 6,802 중복). 이 Phase 에서도 두 번 걸렸다 — `next(...)` 로 부모를 찾으려다 엉뚱한 블록을 집었다 | — |
| 🟡 | **`Clone` 이 아닌 "`SetType` 두 번" 의 의미는 미확정이다.** corpus 에 1건뿐이고 그 1건은 다른 원인이므로 판단 근거가 없어 **그대로 두었다** | 1블록 |
| 🟢 | `effect_types` 가 engine 에 닿지 않는 것은 **미지원 경계**이고, 그래서 이 수정이 duel 동작을 바꿀 수 없다 | 등장 0회 |

---

## 21. 다음 Phase 후보 (최대 1개)

> **`local` 없는 `Effect.CreateEffect` 누락 감사 및 최소 수정
> (조사 + 범위 확인 후 수정)**

이유는 이 Phase 의 측정에서 바로 따라온다.

- 🔴 **이것이 지금 남은 유일한 "틀린 데이터" 다.** 형제 칸 누적(§20 두 번째)도
  실재하지만 **원인과 수정이 이번 것과 동일**하므로 기계적이다. 반면 이쪽은
  **블록이 아예 사라지는** 문제라 성격이 다르다 — `c9839115` 는 효과 블록이
  둘로 보여야 하는데 둘뿐이고, 그중 하나의 `code` 가 **다른 효과의 값**을
  들고 있다.
- **규모가 측정돼 있다** — `local` 없는 대입 **217곳 / 195파일**. 전체
  `CreateEffect` 대입 32,152 중 0.67%.
- **이번 Phase 가 그 경계를 이미 테스트로 못 박아 두었다** (`test_11` ·
  `test_19` ·`test_33`). 수정하면 그 테스트들이 바로 반응한다.
- **조사가 먼저 필요한 이유**: 정규식에서 `local` 을 떼면 **대입이 아닌 비교나
  다른 패턴**까지 잡을 수 있고, 블록 수가 늘면 `EffectRef(card_id, n)` 의
  `n` 이 밀려 **`engine/effect/library.py` 의 등재 16개가 다른 효과를 가리킬
  수 있다.** 그 영향 범위를 먼저 재야 한다 — 이번처럼 "고치면 끝" 이 아니다.
- **Engine V1 freeze 와의 관계가 이번과 다르다.** 이번 수정은 `effect_types`
  만 바꿨고 engine 이 그것을 읽지 않아 안전했다. 블록 **개수**가 바뀌면
  `effect_count` 와 `EffectRef.ordinal` 이 바뀌므로 **engine 이 보는 값이
  바뀐다.** 그래서 조사 단계에서 멈출 수도 있다.

**이번 Phase 에서 고치지 않은 이유**: §18 이 범위를
*"Lua Clone + SetType effect type isolation"* 으로 한정했고, 위의 영향 범위를
재지 않은 채 블록 경계를 바꾸면 무엇을 잃는지 알 수 없다.
