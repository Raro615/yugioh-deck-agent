# Phase 3-F-31 — Lua 변수 재바인딩 / Effect 객체 추적 감사

**최종 판정: A. CONFIRMED_VARIABLE_BINDING_BUG** — 최소 수정함.

---

## 1. 실제 HEAD / BASE

`git log` / `git show` / `git rev-parse` 로 직접 확인했다. **두 개 모두 일치한다.**

| 항목 | 지시서 | 실측 | 결과 |
|---|---|---|---|
| 작업 시작 HEAD | `7bd0747` | `7bd0747c13b81311bf1be10202dfcc3f057b3478` | 일치 |
| 3-F-30 작업 | `ac39230` | `ac39230` *audit branch setter semantics* (1 file, +1196) | 일치 |
| 3-F-30 보고서 | `7bd0747` | `7bd0747` *document branch setter audit* (485줄) | 일치 |
| branch | — | `claude/pensive-goodall-te1egy` | 지정 branch |
| `origin/claude/...` | — | `7bd0747` — **HEAD 와 동일 (동기화됨)** | — |
| worktree | — | **clean** | — |

기존 commit 은 rewrite 하지 않았다.

---

## 2. 문제 재현

지시서 §2 의 A~H 를 **실제 parser 로** 돌렸다. 예상으로 답하지 않았다.

| | Lua | 수정 **전** | 수정 **후** |
|---|---|---|---|
| **A** | `local e1=CreateEffect(c)` + `e1:SetCode(A)` | ord 0 `code=A` | 같음 |
| **B** | `e2=e1` 뒤 `e2:SetCode(A)` | ord 0 `code=None` — **버려짐** | 같음 |
| **B2** | `local e2=e1` 뒤 `e2:SetCode(A)` | 같음 — **버려짐** | 같음 |
| **C** | `local e2=e1:Clone()` | ord 0·1 각자 제 code | 같음 |
| **D** | `e1=e1:Clone()` | ord 1 신규, 부모 ord 0 — **정확** | 같음 |
| **E** | `e1=e2` 뒤 `e1:SetCode(A)` | 🔴 **ord 0 에 붙는다 (틀림)** | **버려짐** |
| **F** | `e1=some_other_value` 뒤 setter | 🔴 **ord 0 에 붙는다 (틀림)** | **버려짐** |
| **G** | `local e2=Ritual.CreateProc(...)` | 블록 없음 · setter **버려짐** | 같음 |
| **H** | `local x=e1:GetLabelObject()` | 블록 없음 · setter **버려짐** | 같음 |
| **H2** | `local e1=e:GetLabelObject()` (이미 묶인 이름) | 🔴 **옛 ``e1`` 블록에 붙는다 (틀림)** | **버려짐** |

🔴 **핵심 질문의 답**: 수정 전 파서는 setter receiver 가 **실제로 어느 Effect 를
가리키는지 보존하지 못했다.** E · F · H2 에서 **옛 바인딩**에 붙었다.

그리고 **"버려짐" 과 "틀림" 은 전혀 다른 결과다** — 전자는 값을 만들지 않고, 후자는
**엉뚱한 블록에 틀린 값을 만든다.**

---

## 3. parser 경로

```
c*.lua
  → sources/lua_loader.py::parse_lua_source
      _RE_BLOCK_COMMENT 로 --[[ ]] 제거                   (3-F-28)
      _RE_CREATE_EFFECT / _RE_CLONE_EFFECT + _is_card_effect (3-F-28)
      🔴 _RE_REBIND — 파서가 모르는 대입                   (3-F-31, 이 Phase)
      _RE_SETTER 로 모든 `var:SetX(` 수집
      events.sort(key=lambda e: (e[0], _EVENT_ORDER[e[1]]))  ← byte offset + 동순위
      bindings: dict[str, EffectSpec] 에 순서대로 재생
         create / clone -> 새 EffectSpec, bindings[var] 교체, effects 에 append
         🔴 rebind     -> bindings.pop(var) · inherited.pop(var)   (이 Phase)
         set           -> bindings[var] 의 칸에 쓴다. **없으면 조용히 버린다**
  → LuaScriptInfo.effects → EffectRef(card_id, ordinal)
  → analysis/effect_analyzer.py (같은 정규식을 import — 3-F-28)
  → core/card_search.py · app/main.py
```

### 3.1 지시서 §4 체크리스트 — 실제 코드 기준

| 확인 항목 | 실제 |
|---|---|
| 변수명을 어떻게 저장하는가 | `bindings: dict[str, EffectSpec]` — **이름 → spec 객체**. `EffectSpec.index` 에 이름이 복사되지만 **식별자가 아니다** |
| 변수 → `EffectRef` 매핑이 있는가 | **없다.** `bindings` 는 spec 객체를 들고, `ordinal` 은 `effects` 리스트의 위치로만 결정된다 |
| `Clone` 시 부모를 어떻게 찾는가 | `bindings.get(src)` — **그 시점의** 바인딩. 못 찾으면 빈 spec |
| 재바인딩 시 기존 매핑을 덮는가 | `create`/`clone` 은 **덮는다** (6,345 + 457곳). 🔴 그 밖의 대입은 **덮지 않았다** → 이 Phase 가 **푼다** |
| scope 를 구분하는가 | **아니다.** `local` 유무는 `_is_card_effect` 의 판정 재료일 뿐 scope 추적이 아니다 |
| 함수 반환값을 Effect 로 인정하는 기준 | **`Effect.CreateEffect` / `Effect.GlobalEffect` / `X:Clone()` 세 형태뿐**이다 |
| `GetLabelObject` 를 Effect 로 오인할 수 있는가 | 🔴 **오인하지 않지만**, 같은 이름의 **옛 바인딩**을 계속 썼다 (이 Phase 가 고쳤다) |
| 보조 함수 생성 Effect 식별 | **하지 않는다** (221곳 — §6) |
| 동일 변수 재사용 처리 | `create`/`clone` 이면 새 블록, 그 밖이면 **이제 바인딩을 푼다** |

---

## 4. alias / clone / rebinding / shadowing 구분

지시서 §3 의 다섯 가지를 **별도로** 확인했다.

| | 형태 | Lua 의미 | 수정 전 parser | 수정 후 parser | corpus |
|---|---|---|---|---|---|
| ① | **alias** `e2 = e1` | 동일 객체 | setter **버림** | 같음 | 🔴 **0건** |
| ② | **clone** `e2 = e1:Clone()` | 새 객체 | 새 블록 · 부모 연결 | 같음 | 2,827 |
| ③ | **rebinding** `e1 = e2` | 가리키는 객체 변경 | 🔴 **옛 블록에 붙임** | **푼다** | — |
| ④ | **shadowing** `local e1` 재선언 | scope 에 따라 다름 | scope 미인식 | 같음 (안전한 쪽) | 25 |
| ⑤ | **non-effect rebinding** `e1 = value` | receiver 의미 변경 | 🔴 **옛 블록에 붙임** | **푼다** | — |

🔴 **①이 corpus 에 0건인 것은 측정된 사실이다.** 단일 변수를 RHS 로 갖는 대입이
**579건** 있지만 RHS 가 **파서가 묶은 Effect 변수인 것은 하나도 없다** — 전부 `nil`
223 · `true` 101 · `false` 82 · `LOCATION_*` 같은 값이고, LHS 는 `g` 96 · `loc` 47 ·
`tc` 38 · `op` 32 처럼 Group/카드/플레이어 변수다. 그래서 §3 ① 의 위험은 **이 corpus
에 존재하지 않는다**.

---

## 5. 변수 추적 방식 — setter receiver 전수

설정자 호출 **121,636건**을 셋으로 갈랐다.

| | 수 (수정 후) | 뜻 |
|---|---|---|
| **추적됨** | **120,301** | receiver 가 `create`/`clone` 으로 묶인 블록이다 |
| 🔴 **잘못 귀속** | **0** (수정 전 **5**) | receiver 가 **옛 바인딩**을 가리켰다 — **실제 버그** |
| **버려짐** | **1,335** (수정 전 1,330) | receiver 가 묶인 적이 없다 — **틀린 값을 만들지 않는다** |

### 5.1 버려지는 1,335건의 정체

| 변수 | 수 | 왜 |
|---|---|---|
| `e` | **661** | 🔴 **함수 매개변수** — `function s.operation(e,tp,...)`. 런타임에 전달되는 효과이고 파서가 어느 블록인지 알 **방법이 없다**. **UNKNOWN by design** |
| `ge1` · `ge2` · `de` 등 | 523 | 파서가 **일부러** 건너뛴 생성 — 듀얼 전역·다른 카드 효과 (3-F-28). **올바르게** 버려진다 |
| 보조 함수 결과 | 101 | `Ritual.CreateProc` 등 (3-F-28 E5) |
| 전역 `Clone` | 29 | `local ge2=ge1:Clone()` (3-F-28) |
| 그 밖 | 21 | `clone_other` 3 · 기타 9 · 이 Phase 가 되살린 5 등 |

🔴 **"추적할 수 없다"(1,335)와 "잘못 추적한다"(5)를 같은 것으로 취급하지 않았다.**

---

## 6. corpus 통계 (현재 HEAD 전수)

| 항목 | 수 |
|---|---|
| 스크립트 | 12,702 |
| 효과 블록 | **34,681** (3-F-28~30 과 같다) |
| `Effect.CreateEffect\|GlobalEffect` 호출 자리 | **32,157** |
| `Clone` 호출 자리 (`:Clone(` + `Effect.Clone(`) | **2,831** |
| 그중 파서가 인정하는 `X:Clone()` 대입 | 2,827 |
| `GetLabelObject(` 호출 | **2,200** |
| Effect 보조 함수 호출 | **221** (변수에 배정 154) |
| └ `Fusion.CreateSummonEff` | 84 |
| └ `aux.AddNormalSummonProcedure` | 56 |
| └ `Spirit.AddProcedure` | 41 |
| └ `Ritual.CreateProc` | 23 |
| └ `Ritual.AddProcGreater` | 15 |
| └ `aux.CreateWitchcrafterReplace` | 2 |
| 다중 대입으로 Effect 를 받는 자리 | **3** (`local sme,soe=Spirit.AddProcedure(...)`) |
| 단일 변수 RHS 대입 | 579 — 🔴 **Effect alias 는 0건** |
| 이미 묶인 변수에 **다시 `create`** | **6,345** — 정상 처리 |
| 이미 묶인 변수에 **다시 `clone`** | **457** — 정상 처리 |
| 🔴 이미 묶인 변수를 **파서가 모르는 RHS** 로 덮음 | **25** |
| └ 그 뒤 설정자가 실제로 붙던 것 | **5** (나머지 20은 setter 가 따라오지 않는다) |

🔴 **25 는 3-F-30 이 센 "shadowing rebinds 25" 와 같다** — 서로 다른 방법으로 측정해
교차 검증됐다.

> **3-F-28 과의 숫자 차이**: 3-F-28 은 보조 함수를 `Fusion.CreateSummonEff 45 ·
> Ritual.CreateProc 20 · Ritual.AddProcGreater 5` 로 적었다. 이 Phase 의 84 / 23 / 15
> 는 **모든 호출 자리**를 센 것이고 3-F-28 은 `local e* = Helper(...)` 형태만 셌다.
> 모순이 아니라 **세는 대상이 다르다** — 숨기지 않고 적는다.

---

## 7. EffectRef / ordinal 검증

지시서 §7 의 다섯 항목을 전수로 확인했다. **전부 불변이다** (`test_24`~`test_26`).

| 확인 | 결과 |
|---|---|
| `ordinal` 이 실제 Lua 생성 순서와 일치하는가 | 🟢 **12,702 스크립트 / 34,681 블록 전부 일치.** 이벤트 순서에서 `(index, cloned_from)` 열을 다시 유도해 파서 출력과 비교했고 **불일치 0건** |
| 재바인딩 때문에 `ordinal` 이 잘못 이동하는가 | 🟢 **아니다.** 블록은 **append 만** 되고 재정렬·교체가 없다 |
| `Clone` 이 새 `ordinal` 을 잘못 만드는가 | 🟢 **아니다.** `Clone` 하나당 블록 하나다 |
| 기존 `EffectRef` 가 다른 Effect 를 가리키게 되는가 | 🟢 **아니다.** 이 Phase 는 블록을 더하거나 빼지 않았다 (34,681 그대로) |
| `CreateEffect` 이후 setter 순서가 `EffectRef` 에 영향을 주는가 | 🟢 **아니다.** setter 는 **값**만 쓴다 |

🔴 3-F-28 이 확정한 ordinal invariant 를 **깨지 않았다.** 그래서 판정은 **B 가 아니다.**

---

## 8. 실제 사례 (§6 분류)

| # | 카드 | 원문 | 분류 | 수정 전 → 후 |
|---|---|---|---|---|
| 1 | `c52445243` | `local e1=e:GetLabelObject()` | 🔴 **D (잘못 추적)** | ord 2 `categories=['DESTROY','DRAW']` → **`[]`** |
| 2 | `c44887817` | `local e2=e1:Clone(e1)` | 🔴 **D** | ord 1 `code='EFFECT_CANNOT_MSET'` → **`None`** (Lua 에 자기 `SetCode` 가 **없다**) |
| 3 | `c4997565` | `local e2=Effect.Clone(e1)` | 🔴 **D** | ord 1 `code='EFFECT_DISABLE_EFFECT'` → **`'EVENT_CHAINING'`** (제 값 **복원**) |
| 4 | `c25415052` | `local sme,soe=Spirit.AddProcedure(c,...)` | **G (UNKNOWN)** | setter 버려짐 (변화 없음) |
| 5 | `c44877690` | 같은 형태 | **G** | 같음 |
| 6 | `c52900000` | 같은 형태 | **G** | 같음 |
| 7 | 전역 효과 ~195장 | `local ge1=Effect.CreateEffect(c)` + `Duel.RegisterEffect` | **I (artifact)** | setter 523건 버려짐 — **올바르다** |
| 8 | `Ritual.CreateProc` 23곳 | 보조 함수 | **G** | 블록 없음 |
| 9 | `Fusion.CreateSummonEff` 84곳 | 보조 함수 | **G** | 블록 없음 |
| 10 | 모든 핸들러의 `e` | `function s.op(e,tp,...)` | **G (UNKNOWN by design)** | setter 661건 버려짐 |
| 11 | `c69526976` | `--e1:SetProperty(...)` (주석) | 🔴 **F (Effect 아닌 것을 추적)** | **고치지 않음** — §13 N2 |
| 12 | `c324483` | 3-F-27/29 의 `Clone` 카드 | **B (정상 clone)** | 변화 없음 |

§6 분류 집계: **A** 0 · **B** 2,827 · **C** 6,802 (6,345 + 457) · 🔴 **D** 5 →
**0** · **E** 0 · **F** 2 (주석, 범위 밖) · **G** 1,330 · **H** 0 · **I** 523.

---

## 9. downstream 영향

지시서 §8 의 계층을 **AST 로 전수** 확인했다. `.code` 같은 이름이 있다는 이유로
판단하지 않고 **base 식별자까지** 봤다 (`test_28`).

| 계층 | `EffectSpec`/`EffectRef`/`ordinal` 을 읽는가 |
|---|---|
| `EffectDefinition` · `TriggerSpec` · `ChainLink` | **아니다** |
| `EffectActivator` · `ChainResolver` | **아니다** |
| `legal_actions` · `apply` | **아니다** |
| `GameStateView` / `CardDefinitionView` | **아니다** — 26칸에 `effect_count` 만 |
| `Search` (`core/card_search.py`) | 🔴 **읽는다** — §9.2 |
| `AI` (`agent/`) | **아니다** |
| 🔴 **`analysis/effect_analyzer.py`** | 🔴 **읽는다** — §9.1 |

`engine/` · `agent/` 에서 `effect_types` · `target_ranges` · `cloned_from` ·
`count_limit` · `categories` · `properties` · `ranges` 접근이 **0건**이다.
`code` 62건과 `index` 24건은 전부 `verdict` · `result` · 존 번호 등 **다른 것**이다.

### 9.1 🔴 분석 결과가 실제로 고쳐졌다 — 수정 조건 ③

`analysis/effect_analyzer.py` 가 `spec.categories` · `spec.code` 를 소비해
`EffectAnalysis` 를 만든다. 세 카드의 분석 결과가 바뀐다 (`test_29`).

* `c4997565` — `EFFECT_DISABLE_EFFECT` → **`EVENT_CHAINING`**. 🔴 그 블록은
  `c:RegisterEffect(e2,...)` 로 **등록된 효과**이고, 유발 사건이 틀렸으면 분석이 틀린다.
* `c44887817` — `EFFECT_CANNOT_MSET` → **`None`**. 없던 값이 사라졌다.
* `c52445243` — 엉뚱한 category 두 개가 사라졌다.

### 9.2 Search — 필터는 불변, 순위는 한 카드에서 바뀐다

| 경로 | 영향 |
|---|---|
| **필터** (`has_effect_category`) | 🟢 **불변** — 블록별 `categories` **또는** 파일 전체 `LuaScriptInfo.categories` 를 보고, 후자에 `DESTROY`·`DRAW` 가 **남아 있다** |
| **순위** (`sum(1 for e in card.effects if ...)`) | 🟠 `c52445243` 의 `DESTROY`/`DRAW` 질의 점수가 **1 → 0** |

🔴 **3-F-30 의 "순위 실측 불변" 은 이 Phase 로 더 이상 참이 아니다.** 그 테스트
(`branch_setter::test_26`)를 갱신하고 이유를 적었다. 그것이 **올바른 방향**이다 —
그 블록은 그 category 를 갖지 않는다. 카드는 필터로 **여전히 검색된다.**

---

## 10. 수정 내용

**수정했다.** 지시서 §9 의 여섯 조건을 **모두** 만족한다.

| 조건 | 충족 | 근거 |
|---|---|---|
| ① 실제 parser bug 재현 | ✅ | §2 의 E·F·H2, §8 의 5건 (`test_20`) |
| ② 현재 parser contract 위반 | ✅ | production 주석이 *"새 `CreateEffect` 를 만나면 바인딩을 교체한다"* 고 적는다 — 계약은 "변수 → **지금**의 효과" 이고, 다른 대입에서 무효화하지 않은 것이 위반이다 |
| ③ downstream **또는 분석 결과**에 실제 영향 | ✅ | §9.1 — `EffectAnalysis` 3장이 고쳐진다. 등록된 효과의 유발 사건 복원 포함 |
| ④ 최소 수정 가능 | ✅ | 정규식 하나 + `pop` 두 줄. 영향 **정확히 3 스크립트 / 3칸** |
| ⑤ `EffectSpec` API 유지 | ✅ | 9칸 그대로 |
| ⑥ Engine V1 freeze 유지 | ✅ | `engine/` 0줄 |

### 10.1 `sources/lua_loader.py` — 한 파일

```python
_RE_REBIND = re.compile(
    r"(?:(?<=^)|(?<=[;\s\)])) *(?:local\s+)?"
    r"([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)"
    r"\s*=(?!=)"
    r"(?!\s*(?:Effect\.(?:CreateEffect|GlobalEffect)\s*\("
    r"|[A-Za-z_]\w*\s*:\s*Clone\s*\(\s*\)))",
    re.M,
)

_EVENT_ORDER = {"create": 0, "clone": 0, "rebind": 1, "set": 2}

# parse_lua_source 안
for m in _RE_REBIND.finditer(body):
    events.append((m.start(), "rebind", m.group(1)))
events.sort(key=lambda e: (e[0], _EVENT_ORDER[e[1]]))
...
if kind == "rebind":
    for name in payload.split(","):
        bindings.pop(name.strip(), None)
        inherited.pop(name.strip(), None)
```

* **음의 선읽기로 파서가 아는 두 형태를 제외**한다 — 그 자리는 `create`/`clone`
  이벤트가 이미 처리하므로 같은 위치에서 충돌하지 않는다.
* 다중 대입(`local sme,soe=...`)도 왼쪽 이름 **전부**를 푼다.
* `_signature` `v7` → **`v8`**.

### 10.2 🔴 Lua dataflow 를 구현하지 않았다

이 규칙은 **"이 변수가 더 이상 *아는* 효과를 가리키지 않는다"** 만 판단하고, 무엇을
가리키는지는 **추측하지 않는다.** Phase 3-E-18 이 `code` 에서 *"읽지 못한 것은
`None`(모른다)"* 으로 되돌린 것과 같은 원칙이다 — **틀린 값을 만드는 것보다 모른다고
말하는 것이 맞다.**

지시서 §9 가 금지한 것을 하나도 만들지 않았다 (`test_35`): 범용 dataflow engine ·
Lua interpreter · CFG · expression language · graph engine · `EffectSpec` 대규모 변경 ·
Engine 변경 · AI/Search 변경 · public API 변경. 새 이름은 **private 둘**
(`_RE_REBIND` · `_EVENT_ORDER`) 뿐이고 `luaparser`·`lupa`·`networkx`·`ast` 를
import 하지 않는다.

### 10.3 corpus diff

수정 전 파서 모듈과 수정 후 파서로 12,702 스크립트를 각각 파싱해 `EffectSpec` 9칸과
`LuaScriptInfo` 10칸을 전수 비교했다.

| | 결과 |
|---|---|
| `effects` 가 바뀐 스크립트 | **3** (`c4997565` · `c44887817` · `c52445243`) |
| 바뀐 칸 | `code` 2 · `categories` 1 |
| 블록 수 | **34,681 → 34,681** (변화 0) |
| `ordinal` / `index` 순서 | **0개** 바뀜 |
| `LuaScriptInfo` 의 다른 10칸 | **변화 0** |
| `effect_types` · `ranges` · `target_ranges` · `properties` · `cloned_from` 총계 | **그대로** |
| `categories` 총계 | 20,505 → **20,503** |
| `code` 있는 블록 | 30,127 → **30,126** |
| `EVENT_*` code | 16,382 → **16,383** (제 값 복원) |

🔴 **예상하지 못한 변화는 없다.** 세 칸 모두 §8 의 세 카드에서 나오고 각각 원인을 확인했다.

---

## 11. 테스트

### 11.1 신규

`tests/test_variable_rebinding_audit.py` — **35개**. 지시서 §10 의 17개 항목을 전부
덮고 18개를 더했다.

| §10 요구 | 테스트 |
|---|---|
| CreateEffect binding | `test_01` |
| alias | `test_02` · `test_34` |
| Clone | `test_03` |
| Clone rebinding | `test_04` · `test_26` |
| 기존 변수 재바인딩 | `test_05` |
| non-effect rebinding | `test_06` |
| shadowing 후보 | `test_11` |
| 보조 Effect 생성 함수 | `test_07` · `test_10` · `test_22` |
| GetLabelObject | `test_08` · `test_09` |
| setter receiver 추적 | `test_13` · `test_14` · `test_20` |
| EffectRef | `test_25` |
| ordinal | `test_24` · `test_26` |
| 여러 Effect 가 섞인 경우 | `test_12` |
| 실제 Lua snippet | `test_17` · `test_18` · `test_19` |
| 실제 corpus 사례 | `test_15` · `test_16` · `test_20` |
| UNKNOWN 처리 | `test_14` · `test_21` |
| downstream non-impact | `test_27`~`test_33` · `test_35` |

### 11.2 기존 테스트 갱신 — 19개 (삭제 0 · skip 추가 0 · 완화 0)

| # | 테스트 | 전 → 후 | 왜 |
|---|---|---|---|
| 1~6 | 캐시 서명 6곳 (`setcode_provenance::test_19` · `settype_clone::test_22` · `create_effect_ordinal::test_19/20/21` · `clone_sibling::test_25/26/27` · `branch_setter::test_33`) | `v7` → **`v8`** | 🔴 3-E-18 의 가드가 **네 Phase 연속** 설계대로 걸렸다. `v4`~`v7` 로 되돌아가지 않았음도 함께 못 박았다 |
| 7 | `branch_setter::test_14` | ord 2 `['DESTROY','DRAW']` → **`[]`** | 🔴 그 테스트 docstring 이 *"그 블록은 애초에 그 설정자의 블록이 아니다"* 라고 적어 둔 것을 이 Phase 가 고쳤다 |
| 8 | `branch_setter::test_19` | `events.sort(key=lambda e: e[0])` → 두 번째 키 추가 | 주장("정렬 기준이 byte offset")은 그대로. 첫 키가 여전히 `e[0]` 임을 함께 확인 |
| 9 | `branch_setter::test_26` | "순위 실측 불변" → **한 카드에서 바뀐다** | 🔴 §9.2 — 숨기지 않고 적고, 필터는 여전히 맞는다는 것을 **추가로** 고정했다 |
| 10 | `branch_setter::test_32` | `categories` 20,505 → **20,503** | 설계된 신호 |
| 11 | `clone_sibling::test_39` | `categories` 20,505 → **20,503** | 같음 |
| 12 | `settype_clone::test_34` | `CATEGORIES_TOTAL` −2 · `CODE_TOTAL` 30,127 → **30,126** | 같음 |
| 13 | `event_free_chain_semantic::test_25` | `IGNITION` 의 `None` 4,119 → **4,120** | 🔴 `c44887817` 의 없던 code 가 사라졌다. 그 테스트의 결론("'없다' 를 생략으로 적는다")이 **또 한 번 선명해졌다** |
| 14 | `special_summon::test_15` | `code` 있는 블록 30,085 → **30,084** | 같음 |
| 15 | `trigger_condition_separation::test_03` | 30,085 → **30,084** · `EVENT_*` 16,382 → **16,383** | 🔴 `c4997565` 의 `EVENT_CHAINING` 복원으로 `EVENT_*` 가 **늘었다** |
| 16~18 | `_changed_files()` helper 3곳 (`create_effect_ordinal` · `clone_sibling` · `branch_setter`) | worktree diff 제거 | 🔴 **§11.3 — 내가 만든 설계 결함** |
| 19 | `create_effect_ordinal::test_21` | 심는 서명 `v6` → `v7` | "**직전 버전**의 캐시가 거부되는가" 를 보는 테스트이므로 파서가 `v8` 이 된 지금은 `v7` 을 심어야 같은 것을 측정한다 |

### 11.3 🔴 내가 만든 실수 둘

**(1) `_changed_files()` 의 Phase 간 누출.** 3-F-28 에서 만들고 3-F-29 · 3-F-30 이
복사한 helper 가 `git diff --name-only <phase_commit>` (= **worktree** vs 그 commit)
을 더하고 있었다. 그러면 **다음 Phase 가 worktree 에서 production 을 고치는 동안**
그 변경이 옛 Phase 의 diff 로 **새어 들어온다.** 실제로 이 Phase 가
`sources/lua_loader.py` 를 고치자 3-F-30 의 `test_27`("production 변경 0") 이 그렇게
깨졌다. Phase commit 이 있으면 **commit 범위만** 보도록 **세 파일 모두** 고쳤다.

**(2) 측정 기준 혼동.** 설정자 호출 총수를 처음에 **121,634** 로 적었다. 문자열·줄
주석까지 지운 본문에서 센 것이고, production 은 줄 주석을 **남긴다** (3-F-28 이 헤더
카드명을 그것으로 읽는다). 정확한 수는 **121,636** 이고 차이 2건은 `c69526976` 의
**주석 처리된 설정자**다. 재측정해 고치고 그 2건을 `test_23` 으로 고정했다.

### 11.4 전체 회귀

현재 HEAD 에서 전체 pytest 를 실행했다 (`python -m pytest -q -p no:randomly`).

```
4912 passed, 4 skipped in 1564.03s (0:26:04)
```

| 기준 | 결과 |
|---|---|
| 3-F-30 baseline | 4,877 passed / 4 skipped |
| 이번 Phase | **4,912 passed / 4 skipped** |
| 차이 | **+35** = 신규 테스트 35개 그대로 |
| 예상하지 않은 failure | **0** |
| 삭제 | **0** |
| skip 추가 | **0** (4개 그대로) |
| 검증 기준 완화 | **0** — §11.2 의 19건은 전부 이유를 적고 기대값을 **정확한 새 값**으로 옮긴 것이고, `branch_setter::test_19`·`test_26` 과 캐시 가드 6곳은 **더 강해졌다** |
| `state_hash` · RNG · digest · hidden-info | 🟢 §9 · `test_31` · `test_32` |
| `EffectRef` / `ordinal` | 🟢 §7 — 12,702 스크립트 전부 |
| Engine V1 freeze | 🟢 `engine/` 0줄 |

중간 과정도 그대로 적어 둔다 — 수정 직후 1차 전체 회귀는 **19 failed / 4,858 passed**
였다. 캐시 서명 6곳 · corpus 총계 6곳 · 3-F-30 의 네 테스트 · `_changed_files()` 누출
1곳 · 내 핀 2곳이고, 전부 §11.2 에 이유와 함께 적었다.

---

## 12. 최종 판정

**A. CONFIRMED_VARIABLE_BINDING_BUG**

파서는 `bindings` 를 "변수 → **지금** 그 변수가 가리키는 효과" 로 쓴다고 **스스로 적어
놓고**, 그 갱신을 `Effect.CreateEffect` 와 `X:Clone()` **두 형태에서만** 했다. Lua 가
같은 변수에 다른 것을 대입하면 **옛 매핑이 남아** 그 뒤 설정자가 **엉뚱한 블록에
붙었다** — corpus 전수로 **5건 / 3장**, 그중 하나는 **등록된 효과의 유발 사건을
덮었다**(`c4997565`).

* **B 가 아니다** — `ordinal` invariant 는 12,702 스크립트 전부에서 **성립한다** (§7).
* **C 가 아니다** — `engine/`·`agent/` 는 이 칸들을 **읽지 않는다**. 실제 영향은
  `analysis` 와 검색 **순위**(한 카드)이고, duel 동작은 바뀌지 않는다 (§9).
* **D 가 아니다** — 새 분류 데이터를 만들지 않았다.
* **E 가 아니다** — 표현력 한계가 아니라 **파서가 틀린 값을 만들고 있었다.**
  (표현 한계는 3-F-30 의 판정이고 그것과 구분된다.)
* **F 가 아니다** — 1,335건은 UNKNOWN by design 이지만, **5건은 그렇지 않았다.**
  둘을 섞으면 실제 버그를 가린다.
* **G 가 아니다** — 버그가 **있었고** 재현했다.

---

## 13. 남은 구조적 위험

### 13.1 이 Phase 에서 새로 발견

| # | 위험 | severity | 재현 | production | Engine | AI/Search | 왜 지금 안 고치는가 |
|---|---|---|---|---|---|---|---|
| N1 | **보조 함수 생성 Effect 를 블록으로 보지 않는다** — 221곳(배정 154) · 다중 대입 3곳 | 🟠 중 | ✅ `test_07` · `test_10` · `test_22` | 설정자 101건 버려짐 | 없음 | 없음 | 블록을 추가하면 **`ordinal` 이 밀려 downstream `EffectRef` 가 바뀐다** (3-F-28 규모). 어떤 효과를 몇 개 만드는지는 **보조 함수 본문을 읽어야 알 수 있고** 그것은 dataflow 다 — 금지 사항 |
| N2 | **주석 처리된 설정자가 적용된다** — `c69526976` 2건 | 🟡 하 | ✅ `test_23` | 그 카드 1장의 `properties`·`ranges` | 없음 | 없음 | 줄 주석을 지우면 3-F-28 이 **헤더에서 카드명을 읽는 경로가 깨진다**. 이 Phase 의 범위(변수 재바인딩)가 아니다 |
| N3 | **`GetLabelObject` 가 가리키는 블록을 알 수 없다** — 2,200 호출 | 🟡 하 | ✅ `test_08` · `test_09` | 설정자가 버려진다 (전에는 **틀렸다**) | 없음 | 없음 | 해소에 dataflow 가 필요하다. 지금은 **UNKNOWN** 으로 남겨 **틀린 값을 만들지 않는다** — 그것이 올바른 상태다 |
| N4 | **`local e2=e1:Clone(e1)` · `Effect.Clone(e1)` 을 clone 으로 보지 않는다** — 3곳 | 🟡 하 | ✅ `test_18` · `test_19` | 블록 2개가 없다 | 없음 | 없음 | 인정하면 **블록이 늘어 `ordinal` 이 밀린다**. 지금은 설정자를 버려 **오염만 제거**했다. N1 과 같은 범위에서 함께 다루는 것이 맞다 |
| N5 | **함수 매개변수 `e` 의 설정자 661건** | 🟢 정보 | ✅ `test_14` | 버려진다 | 없음 | 없음 | **원리적으로 불가능**하다 — 런타임 값이다. UNKNOWN by design |

### 13.2 기존 위험 (유지)

| # | 위험 | 출처 | 상태 |
|---|---|---|---|
| E1 | 네 설정자의 Lua API 의미가 문서화되지 않음 (대입 vs OR) | 3-F-29 | **유지** |
| E2 | 목록 칸에 "모른다" 를 표현할 값이 없다 | 3-F-29 | **유지** |
| E3 | 한 블록의 두 번째 이후 setter 는 더하기 | 3-F-29 | **유지** |
| E4 | 캐시 서명에 파서 버전이 없다 | 3-F-27~29 | **유지** — 네 Phase 연속 수동 (`v8`) |
| E5 | 보조 함수 생성 effect | 3-F-28 | 🔴 **N1 로 승격** — 이 Phase 가 정확히 셌다 |
| E6 | `EffectSpec.index` 가 유일하지 않다 | 3-F-28 | **유지** |
| E7 | `SetCategory(aux.Stringid(...))` 8건 | 3-F-29 | **유지** |
| E8 | **분기별 의미를 표현할 칸이 없다** — 조건부 수정 2건 | 3-F-30 | **유지** |
| E9 | 배타 분기 값 병합 2블록 | 3-F-30 | **유지** — 🔴 그중 `c52445243` 은 **이 Phase 가 원인을 제거했다** |

---

## 14. 다음 Phase 후보 1개

**Phase 3-F-32 — 보조 함수 생성 Effect 와 미인식 `Clone` 형태 감사 (N1 + N4 + E5)**

이 Phase 가 **같은 뿌리**로 확정한 셋을 함께 다룬다 — 파서가 블록을 **세 형태**
(`Effect.CreateEffect` · `Effect.GlobalEffect` · `X:Clone()`)로만 인정한다.

* `Fusion.CreateSummonEff` 84 · `aux.AddNormalSummonProcedure` 56 ·
  `Spirit.AddProcedure` 41 · `Ritual.CreateProc` 23 · `Ritual.AddProcGreater` 15 ·
  `aux.CreateWitchcrafterReplace` 2 = **221곳**, 변수에 배정 **154곳**
* 다중 대입으로 Effect 둘을 받는 **3곳**
* `e1:Clone(e1)` · `Effect.Clone(e1)` **3곳**

🔴 **먼저 재야 할 것**: 이 자리들을 블록으로 인정하면 **`ordinal` 이 몇 장에서 밀리고
어떤 `EffectRef` 가 바뀌는지**. 3-F-28 이 그 작업의 방법론을 이미 세웠다 (전수 diff ·
16개 정의 검증 · 캐시 서명). 보조 함수가 **몇 개의** 효과를 만드는지는 그 함수 본문을
읽어야 알 수 있고 그것은 dataflow 이므로, **세는 것조차 불가능하다고 판단되면
UNKNOWN 으로 남기고 기록만 하는 것도 정당한 결론**이다.
