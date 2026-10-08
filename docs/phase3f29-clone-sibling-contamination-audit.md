# Phase 3-F-29 — `Clone` 형제 간 누적 감사 및 최소 수정

**판정: C. CONFIRMED_PARSER_CLONE_ACCUMULATION**

---

## 1. 실제 HEAD / Base

지시서의 SHA 를 참고값으로 받고 `git log` / `git show` 로 직접 확인했다. **네 개 모두 일치한다.**

| 항목 | 지시서 | 실측 | 결과 |
|---|---|---|---|
| 3-F-28 작업 | `32936b0` | `32936b0` *fix CreateEffect ordinal tracking* (2 files, +109 −18) | 일치 |
| 3-F-28 테스트 | `771b30e` | `771b30e` *update CreateEffect audit tests* (신규 1,288줄 + 기존 9파일) | 일치 |
| 3-F-28 diff anchor | `c0724ef` | `c0724ef` *anchor the audit diff range…* (1 file, +18 −15) | 일치 |
| 3-F-28 보고서 | `0f056df` | `0f056df` *document CreateEffect ordinal audit* (692줄) | 일치 |
| HEAD | — | `0f056df4200e829b0264990d2688e318ec358b12` | = 보고서 commit |
| branch | — | `claude/pensive-goodall-te1egy` | 지정 branch |
| `origin/claude/pensive-goodall-te1egy` | — | `0f056df` | **동기화됨** |
| worktree | — | **clean** | — |

기존 commit 은 rewrite 하지 않았다.

---

## 2. 문제 재현

지시서 §2 의 최소 사례를 **production 파서로 그대로** 돌렸다.

```lua
local e1=Effect.CreateEffect(c)
e1:SetCategory(CATEGORY_DRAW)
local e2=e1:Clone()
e2:SetCategory(CATEGORY_TOGRAVE)
local e3=e1:Clone()
e3:SetCategory(CATEGORY_DESTROY)
```

수정 **전** 결과:

| 질문 | 수정 전 | 수정 후 |
|---|---|---|
| A. `e1` 의 category | `['DRAW']` | `['DRAW']` |
| B. `e2` 의 category | 🔴 `['DRAW', 'TOGRAVE']` | `['TOGRAVE']` |
| C. `e3` 의 category | 🔴 `['DRAW', 'DESTROY']` | `['DESTROY']` |
| D. `e2` 변경이 `e3` 에 영향? | **아니다** | 아니다 |
| E. `e2` 변경이 `e1` 에 영향? | **아니다** | 아니다 |
| F. `e3` 변경이 `e2` 에 영향? | **아니다** | 아니다 |
| 가변 컨테이너 공유? | **아니다** | 아니다 |

🔴 **D · E · F 가 전부 "아니다" 다.** 지시서가 금지한 *"Clone 은 복사니까 독립적일 것"* 이라는
가정 없이 실제 경로로 확인했고, **형제 오염은 처음부터 없었다.**

실제로 틀린 것은 **B 와 C** 다 — 부모의 값이 자식의 자기 호출 **위에 남는다.**
`properties` · `ranges` · `target_ranges` 도 같은 모양이었다.

---

## 3. Clone semantics

지시서 §3 의 네 가지를 분리해서 판정했다.

| | 내용 | 판정 | 근거 |
|---|---|---|---|
| A | 부모 → Clone 정상 상속 | 🟢 **실제로 일어나고 의존된다** | Clone 자식 2,744개 중 `ranges` 1,054 · `target_ranges` 350 · `categories` 993 · `properties` 1,664 개가 물려받은 값을 갖는다. `c55948544` 의 `e2`~`e6` 은 `SetCode` 만 바꾸고 나머지를 **순수 상속**으로 쓴다 |
| B | Clone → 부모 역오염 | **없다** | `test_04` — 다섯 칸 전부 |
| C | Clone → 형제 Clone 오염 | **없다** | `test_05` — 다섯 칸 전부 |
| D | Clone 내부 가변 컨테이너 공유 | **없다** | `clone` 분기가 다섯 칸 전부 `list(parent.X)` 로 **새 객체**를 만든다. 3-F-27 `test_20` 이 2,744×5 컨테이너의 `id` 를 전수로 고정했고 유지된다 |

### 3.1 중첩 가변 구조 자체가 없다

지시서가 list · dict · set · tuple 내부 가변 객체 · nested structure 를 확인하라고 했다.
`EffectSpec` 의 타입 힌트를 전수로 보면:

* `list[str]` 다섯 개 — `effect_types` · `ranges` · `target_ranges` · `categories` · `properties`
* 스칼라 넷 — `index`(`str`) · `code`(`str | None`) · `count_limit`(`str | None`) · `cloned_from`(`str | None`)

`dict` · `set` · 중첩 `list` 는 **하나도 없다** (`test_10`). 그래서 **A · B 는 기각**이다.

---

## 4. parser 경로

```
c*.lua
  → _RE_BLOCK_COMMENT 로 주석 제거 (3-F-28)
  → _RE_CREATE_EFFECT / _RE_CLONE_EFFECT / _RE_SETTER + _is_card_effect (3-F-28)
  → (위치, 종류, 페이로드) 를 byte offset 으로 정렬해 재생
       create : 새 EffectSpec, bindings[var] 교체
       clone  : 새 EffectSpec, 부모의 다섯 목록 칸 + code + count_limit 복사
       set    : bindings[var] 의 해당 칸에 쓴다   ← 🔴 여기가 문제였다
  → LuaScriptInfo.effects → EffectRef(card_id, ordinal)
```

🔴 **Clone 탐지 · 부모 연결 · ordinal · EffectRef 는 모두 정상이다.** `clone` 분기가
`bindings.get(src)` 로 **부모**를 집고, 형제는 서로를 볼 수 없는 구조다. 문제는
**`set` 분기가 칸마다 다른 규칙을 쓰고 있었다**는 것이다.

---

## 5. Clone 구현

이 저장소에서 "Clone 구현" 은 두 층이다. 지시서가 요구한 대로 **둘을 분리해서** 판정했다.

### 5.1 runtime (EDOPro Lua) — 이 저장소 밖

`Effect:Clone()` 의 C++ 구현은 이 저장소에 **없다.** 그래서 runtime semantics 를
추측하지 않았다.

### 5.2 parser (`sources/lua_loader.py::parse_lua_source`) — 수정 전

```python
elif kind == "clone":
    spec = EffectSpec(index=dst, cloned_from=src)
    if parent is not None:
        spec.effect_types  = list(parent.effect_types)    # ← 새 list
        spec.code          = parent.code                  # ← 스칼라 대입
        spec.ranges        = list(parent.ranges)
        spec.target_ranges = list(parent.target_ranges)
        spec.categories    = list(parent.categories)
        spec.properties    = list(parent.properties)
        spec.count_limit   = parent.count_limit
```

| 확인 항목 | 결과 |
|---|---|
| shallow copy / deep copy | **직접 필드 복사** — `copy.copy` · `copy.deepcopy` **사용 0회** |
| `list(...)` | 다섯 목록 칸 **전부** |
| `dict(...)` | 없음 (dict 칸이 없다) |
| immutable field | `code` · `count_limit` · `index` · `cloned_from` — 대입 |
| mutable field | 목록 다섯 칸 — `list(...)` |
| nested mutable field | **없음** (§3.1) |
| 🔴 **모든 칸을 같은 방식으로 처리하는가** | **복사는 같다. 그 뒤 설정자 처리가 달랐다** |

🔴 **그것이 이 Phase 의 발견이다.** 복사는 다섯 칸이 똑같은데, 그 뒤 **자식의 설정자**를
처리할 때 `effect_types` 만 "첫 호출은 덮어쓴다"(3-F-27)이고 나머지 네 칸은 **더하기**였다.

```python
# effect_types — 3-F-27 이 고친 쪽
if inherited_types.get(var):
    spec.effect_types = _strip_prefix(found)      # 덮어쓴다
# 나머지 네 칸 — 그대로 더하기
spec.categories = _strip_prefix(spec.categories + _RE_CATEGORY.findall(args))
```

**"Clone 전체를 deepcopy 로 바꾸자" 같은 결론을 먼저 내리지 않았다** — aliasing 이 아예
없으므로 deepcopy 는 아무 문제도 해결하지 않는다 (`test_40` 이 `deepcopy` 가 들어오지
않았음을 고정한다).

---

## 6. mutable field 분석 (§4 표)

| field | parent→clone 상속 | clone 독립성 | sibling 독립성 | mutable container | 🔴 실제 문제 |
|---|---|---|---|---|---|
| `effect_types` | 🟢 `list(...)` | 🟢 | 🟢 | 공유 없음 | **없음** — 3-F-27 이 고쳤다 |
| `ranges` | 🟢 `list(...)` | 🟢 | 🟢 | 공유 없음 | 🔴 **자기 호출이 상속값을 덮지 못함 (12블록)** |
| `target_ranges` | 🟢 `list(...)` | 🟢 | 🟢 | 공유 없음 | 🔴 **같음 (9블록)** |
| `categories` | 🟢 `list(...)` | 🟢 | 🟢 | 공유 없음 | 🔴 **같음 (24블록)** |
| `properties` | 🟢 `list(...)` | 🟢 | 🟢 | 공유 없음 | 🔴 **같음 (19블록)** |
| `code` | 🟢 대입 | 🟢 | 🟢 | 해당 없음 | **없음** — 3-E-18 이 고쳤다 |
| `count_limit` | 🟢 대입 | 🟢 | 🟢 | 해당 없음 | **없음** — 대입이다 |
| `index` · `cloned_from` | 설정됨 | 🟢 | 🟢 | 해당 없음 | **없음** |

즉 **`EffectSpec` 의 가변 칸 전부를 조사했고**, 문제는 네 칸에만 있었다.

---

## 7. 64개 후보 전수 분류

### 7.1 숫자를 다시 측정했다

3-F-28 이 남긴 "약 64 blocks" 를 **사실로 가정하지 않고** 현재 HEAD 에서 다시 셌다.

| field | 3-F-28 기록 | 현재 HEAD 재측정 |
|---|---|---|
| `ranges` | 12 | **12** |
| `target_ranges` | 9 | **9** |
| `categories` | 24 | **24** |
| `properties` | 19 | **19** |
| **합계** | 64 | **64** |

정의: **`Clone` 자식의 첫 자기 호출이 물려받은 값을 포함하지 않는** 블록
(`inherited ⊄ own`, `inherited` 비어 있지 않음). 즉 **더하기와 덮어쓰기의 결과가 다른**
블록이다. 숫자가 맞았다.

### 7.2 64개의 모양 (전수)

| 모양 | 수 | 뜻 |
|---|---|---|
| 상속값과 자기값이 **전혀 겹치지 않음** | **45** | 자식이 완전히 다른 값을 쓴다 |
| 자기 호출이 플래그 0개 — **명시적 `SetX(0)`** | **11** | 자식이 **비운다** |
| 자기값이 상속값의 **부분집합** (좁힘) | **7** | 자식이 일부만 남긴다 |
| 일부만 겹침 | **1** | `c55262310` — `POSITION` 은 유지, 두 번째만 교체 |

칸별:

* `ranges` 12 — **전부** 겹치지 않음 (`PZONE`→`MZONE` 6 · `HAND`→`GRAVE`/`DECK`/`EXTRA` 6)
* `target_ranges` 9 — 겹치지 않음 8 · 좁힘 1
* `categories` 24 — 겹치지 않음 20 · 좁힘 1 · 명시적 0 **2** · 일부 겹침 1
* `properties` 19 — 명시적 0 **9** · 좁힘 5 · 겹치지 않음 5

### 7.3 지시서 §10 의 A~F 분류 — 64개 전부

| 분류 | 수 | 근거 |
|---|---|---|
| A. 실제 sibling contamination | **0** | §2 D·F · §3 C — 형제는 서로를 보지 못한다 |
| B. 정상 inheritance | **0** | 상속 자체는 64개 전부 정상이지만, **자식이 그 칸을 재지정한 뒤에도 남는 것**이 문제다. "정상" 으로 분류하면 `SetCategory(0)` 을 무시하게 된다 |
| C. 정상 additive semantics | **0** | §7.5 — 네 칸 어디에도 더하기를 뒷받침하는 **독립** 증거가 없다 |
| D. parser false positive | **0** | 64개 전부 더하기/덮어쓰기 결과가 실제로 다르다 |
| E. **runtime 과 parser 가 다른 문제** | **64** | runtime `Clone` 은 정상이고, **parser 의 누적**이 문제다 → 판정 **C** |
| F. 기타 | **0** | |

### 7.4 🔴 덮어쓰기가 맞다는 근거 — 저장소 내부 증거만

EDOPro 의 `SetCategory` · `SetProperty` · `SetRange` · `SetTargetRange` API 가 대입인지
OR 인지는 **이 저장소에 문서화돼 있지 않다** (`data/constants/*.lua` · `sources/README.md` ·
`core/README.md` 전수 확인). 그래서 Lua 의미를 추측하지 않고 corpus 로만 판단했다.

**근거 1 (결정적) — 자식이 물려받은 플래그를 자기 호출에 다시 적는 블록이 43개다.**

| field | 재진술 | 그대로 다시 | 유지하며 확장 |
|---|---|---|---|
| `ranges` | 1 | 1 | 0 |
| `target_ranges` | 11 | 11 | 0 |
| `categories` | 8 | 1 | 7 |
| `properties` | 23 | 1 | 22 |
| **합계** | **43** | **14** | **29** |

더하기라면 물려받은 플래그를 다시 적는 것은 **아무 효과도 없는 죽은 코드**다. 서로 다른
43개 스크립트가 그럴 이유가 없다. 덮어쓰기라면 **유지할 플래그를 반드시 다시 적어야
한다.** 실제 모양이 정확히 그것이다 —

* `c13708888` `e2`: 부모 `CARD_TARGET+DELAY` → 자식이 `CARD_TARGET+DELAY+DAMAGE_STEP` 을 쓴다.
* `c66984907` `e2`: 부모 `TOGRAVE` → 자식이 `TOGRAVE+TOHAND+SEARCH` 를 쓴다.

🔴 3-F-27 이 `SetType` 에서 같은 근거를 썼는데 그때는 **1건**이었다. 여기서는 **43건**이다.

**근거 2 — 명시적으로 비우는 스크립트가 11개 있다.**
`SetProperty(0)` 9건 · `SetCategory(0)` 2건. 대입이 아니면 **의미가 없는 줄**이다.
더하기 규칙에서는 부모의 플래그가 남아, 스크립트가 분명히 지운 것을 계속 주장했다.

**근거 3 (보조) — 더하기가 어떤 카드도 쓰지 않는 조합을 만든다.**
64 중 **4건**에서 더하기 결과가 corpus 의 어떤 `SetX` 호출에도 (상위집합으로도) 없다
(`c93473606` · `c55262310` · `c55948544` · `c63259351`).
🔴 `SetType` 에서는 77 중 76 이었다 — **비율이 훨씬 낮다. 숫자를 부풀리지 않고 그대로
적는다.** 그래서 이 근거는 보조이고, 결정적인 것은 근거 1 이다.

**근거 4 — `effect_types` 가 같은 결론을 이미 받았다** (3-F-27). 같은 `clone` 분기가 같은
방식으로 물려주는 칸인데 규칙만 달랐다.

### 7.5 🔴 반대 방향 증거도 측정하고 기록했다

한 블록이 같은 설정자를 두 번 부르며 서로 다른 값을 쓰면 **더하기 쪽 증거**다.

| field | 사례 | 내용 |
|---|---|---|
| `ranges` | **0** | — |
| `target_ranges` | **0** | — |
| `categories` | **1** | `c52445243` — `if`/`elseif` **배타 분기**다. 런타임에 한 번만 실행되므로 누적과 무관하다 |
| `properties` | **5** | 3건은 `SetDescription(...)` + `SetProperty(EFFECT_FLAG_CLIENT_HINT)` 라는 **같은 복사-붙여넣기 관용구** (`c50619462` · `c64867422` · `c73899015`) · 1건은 `e2` 를 쓸 자리에 `e1` 을 쓴 **오타** (`c76685519`) · **1건은 독립 사례** (`c49460512` — `IGNORE_IMMUNE` → `EVENT_PLAYER`) |

🔴 **정정** — 처음에 테스트에 *"properties 5건 중 4건이 같은 관용구"* 라고 적었는데
**틀렸다**. `c49460512` 에는 `CLIENT_HINT` 가 없다. 재측정해 **3건**으로 고쳤고,
**독립 사례가 1건 남는다**는 사실을 숨기지 않고 `test_37` 에 고정했다.

그래서 **독립 증거는 더하기 쪽 1건 · 덮어쓰기 쪽 43건**이다. 그리고 그 1건은
`Clone` 블록이 **아니다.** 그래서:

* `Clone` 이 물려준 값을 덮어쓰는 **첫 호출만** 고쳤다.
* **한 블록이 같은 설정자를 두 번 부르는 경우의 더하기는 그대로 두었다** (`test_17`) —
  증거가 한쪽으로 기울지 않는 것은 바꾸지 않는다.

### 7.6 🔴 "읽지 못한 것" 과 "비운 것" 을 구분했다

플래그를 하나도 못 읽은 첫 호출이 corpus 에 **27건** 있다.

| 종류 | 수 | 예 |
|---|---|---|
| **명시적 0** — 스크립트가 비운다 | **11** | `SetProperty(0)` · `SetCategory(0)` |
| 🔴 **읽을 수 없음** — `LOCATION_*` 이 애초에 없다 | **16** | `SetTargetRange(0,1)` 13 · `(1,1)` · `(1,0)` · `(POS_FACEUP,1)` |

`SetTargetRange(0,1)` 은 **플레이어 대상 형식**이다. 이것을 "대상 범위가 없다" 로 읽으면
**읽지 못한 것을 빈 값으로 단정**하는 것이고, 이 저장소의 규칙에 어긋난다.

그래서 `_write_list` 에 **보호 분기**를 넣었다 — 플래그를 못 읽었고 인자가 리터럴 0 도
아니면 **물려받은 값을 그대로 두고 칸을 상속 상태로 남긴다**. 뒤에 읽을 수 있는 호출이
오면 그때 덮어쓴다. Phase 3-E-18 이 `code` 에서 *"읽지 못한 것은 `None`(모른다)"* 으로
되돌린 것과 같은 원칙이다.

🔴 **현재 corpus 에서 이 분기는 숫자를 바꾸지 않는다** — 읽을 수 없는 16건은 **전부**
물려받은 값이 비어 있다 (전수 확인). 즉 이 분기는 지금의 숫자를 위한 것이 아니라,
그런 스크립트가 들어와도 틀리지 않기 위한 것이다 (`test_41` · `test_42`).

---

## 8. corpus 통계 (현재 HEAD 재측정)

3-F-28 의 수치를 복사하지 않고 다시 측정했다.

| 항목 | 수 |
|---|---|
| 스크립트 | 12,702 |
| 효과 블록 | **34,681** (3-F-28 과 같다 — 이 Phase 는 블록을 더하지 않았다) |
| `Clone` 을 쓰는 스크립트 | 2,145 |
| `Clone` 자식 블록 | **2,744** |
| `Clone` 부모 (변수 단위) | 2,345 |
| 같은 부모에서 Clone 2개 이상인 묶음 | **332** |
| 그 묶음에 속한 Clone | **731** |
| `Clone` + 자기 `SetType` | 77 |
| `Clone` + 자기 `SetCategory` | 36 |
| `Clone` + 자기 `SetProperty` | 91 |
| `Clone` + 자기 `SetRange` | 32 |
| `Clone` + 자기 `SetTargetRange` | 37 |
| 🔴 실제 contamination 후보 (더하기 ≠ 덮어쓰기) | **64** |
| 🔴 false positive | **0** |
| 순수 상속에 의존하는 Clone 블록 | `ranges` 1,054 · `target_ranges` 350 · `categories` 993 · `properties` 1,664 |

---

## 9. 실제 카드 사례 (12장)

| # | 카드 | Lua 모양 | 수정 전 | 수정 후 |
|---|---|---|---|---|
| 1 | `c18438874` | `e1` `DRAW`/`PLAYER_TARGET` → `e2=e1:Clone()` + `SetCategory(TOHAND+SEARCH)` + `SetProperty(0)` → `e3=e2:Clone()` | `e2` cat `['DRAW','TOHAND','SEARCH']` prop `['PLAYER_TARGET']` | `e2` cat `['TOHAND','SEARCH']` prop `[]`, `e3` 도 같이 |
| 2 | `c295517` | `e2` tr `HAND\|MZONE` → `e3=e2:Clone()` + `SetTargetRange(MZONE,MZONE)` → `e4=e3:Clone()` | `e3`·`e4` tr `['HAND','MZONE']` | `['MZONE']` — `EFFECT_UPDATE_DEFENSE` 가 손에 적용될 리 없다 |
| 3 | `c71650854` | `e2` prop `SET_AVAILABLE+IGNORE_IMMUNE` → `e3=e2:Clone()` + `SetProperty(SET_AVAILABLE)` → `e4`·`e5=e3:Clone()` | `e3`·`e4`·`e5` 전부 두 플래그 | `['SET_AVAILABLE']` — **형제 둘까지 전파** |
| 4 | `c93473606` | `e1` cat `TODECK+DRAW` → `e2=e1:Clone()` + `SetCategory(ATKCHANGE+DEFCHANGE)` | `['TODECK','DRAW','ATKCHANGE','DEFCHANGE']` | `['ATKCHANGE','DEFCHANGE']` |
| 5 | `c55262310` | `e1` cat `POSITION+TODECK` prop `CARD_TARGET` → `e2` + `SetCategory(POSITION+LVCHANGE)` + `SetProperty(0)` | cat 3개 · prop `['CARD_TARGET']` | cat `['POSITION','LVCHANGE']` · prop `[]` |
| 6 | `c55948544` | `e1` → `e2`~`e6` 가 `SetCode` **만** 바꾼다 / `e11` → `e12` 가 tr 을 바꾼다 | `e2`~`e6` prop 유지(정상) · `e12` tr `['SZONE','MZONE']` | `e2`~`e6` **그대로** · `e12` `['MZONE']` |
| 7 | `c13708888` | 자식이 부모 플래그를 **다시 적고** `DAMAGE_STEP` 을 더한다 | `{CARD_TARGET, DELAY, DAMAGE_STEP}` | **그대로** — 재진술이므로 결과가 같다 |
| 8 | `c63259351` | `e1` prop `SINGLE_RANGE` → `e2=e1:Clone()` + `SetProperty(PLAYER_TARGET)` + `SetTargetRange(1,1)` | prop 두 개 | prop `['PLAYER_TARGET']` · tr 은 **읽을 수 없어 건드리지 않음** |
| 9 | `c66984907` | `e1` cat `TOGRAVE` → `e2` + `SetCategory(TOGRAVE+TOHAND+SEARCH)` + `SetProperty(0)` | cat 그대로 · prop `['CARD_TARGET']` | cat 그대로 · prop `[]` |
| 10 | `c73899015` | **Clone 아님** — 한 블록이 `SetProperty` 를 순차 2회 | `{CLIENT_HINT, CANNOT_DISABLE, OATH}` | **그대로** (더하기 유지) |
| 11 | `c76685519` | **Clone 아님** — `e2` 를 쓸 자리에 `e1` 오타 | `CLIENT_HINT` 포함 | **그대로** |
| 12 | `c324483` | 3-F-27 의 카드 — `IGNITION` → Clone → `QUICK_O` | `['QUICK_O']` | **그대로** |

유형 커버리지: Clone 1개(4·5) · Clone 여러 개(3·6) · Clone+SetType(12) ·
Clone+SetCategory(1·4·5·9) · Clone+SetProperty(3·5·8·9) · Clone+SetRange(§7.2 의 12건) ·
Clone+SetTargetRange(2·6·8) · Clone 후 setter 여러 번(1·5·9) ·
형제 Clone 이 서로 다른 값(3) · 같은 부모에서 2개 이상(3·6).

---

## 10. EffectRef / ordinal

지시서 §12 의 다섯 가지를 확인했다. **전부 불변이다** (`test_19` · `test_20`).

| 확인 | 결과 |
|---|---|
| `Clone` 이 `ordinal` 을 새로 만드는가 | **아니다** — 블록 수 34,681 그대로, `Clone` 블록 2,744 그대로 |
| `Clone` 이 effect count 를 잘못 늘리는가 | **아니다** — corpus diff 에서 블록 수가 바뀐 스크립트 **0개** |
| `Clone` 누락으로 `ordinal` 이 밀리는가 | **아니다** — 부모가 자식보다 앞에 있다 (3-F-28 이 고정한 `c39114494` 1건 예외 유지) |
| `EffectRef` 가 clone 을 잘못 가리키는가 | **아니다** — `ordinal`/`index` 순서가 바뀐 스크립트 **0개** |
| 부모와 clone 의 identity 혼동 | **없다** — `cloned_from` 이 부모 변수명을 유지하고, 식별자는 `ordinal` 이다 |

새 ID 시스템은 도입하지 않았다. `EffectRef` 는 `(card_id, ordinal)` 두 칸짜리 frozen
dataclass 그대로이고, `engine/ids.py` 에 `uuid` · `id(self)` · `EffectId` 가 0회다.

---

## 11. 16개 EffectDefinition

**전부 수정 전후 동일하다** (`test_23`).

| 확인 | 결과 |
|---|---|
| 정의 수 | 16 |
| effect count | 16장 **전부 1개** |
| `ordinal` | 16장 **전부 0** |
| `EffectRef` | 16장 **전부 `[EffectRef(id, 0)]`** · `resolve()` 성공 |
| `code` | 16장 **전부 `EVENT_FREE_CHAIN`** |
| 수정 전/후 블록 전체 비교 | 16장 **전부 완전히 동일** |
| 🔴 스크립트에 `:Clone()` | 16장 **전부 없음** |
| 이 Phase 가 바꾼 59장에 포함 | 16장 **전부 미포함** |

🔴 그래서 `EffectDefinition → TriggerSpec → ChainLink → activation path` 에
**이 수정이 닿을 수가 없다.**

---

## 12. cache 영향

`LuaScriptSource._signature()` 는 `f"v{N}:{스크립트 수}:{최신 mtime}"` 이고 **파서 버전이
들어 있지 않다.** 스크립트가 바뀌지 않으면 서명이 같으므로, 고친 파서가 옛 캐시를 계속
읽는다.

* 3-E-18 이 설치한 `test_setcode_provenance_audit.py::test_19` 가 **세 Phase 연속으로
  설계대로 걸렸다** (3-F-27 `v4`→`v5` · 3-F-28 `v5`→`v6` · 3-F-29 `v6`→**`v7`**).
* `data/cache/lua_scripts.json` 을 새 서명으로 다시 썼다.
* `test_25` (round-trip + cache hit) · `test_26` (접두사) · `test_27` (stale 거부) 가
  고정한다. `test_27` 은 `v6` 서명과 **거짓 내용**을 심어 놓고 그것이 무시되는지,
  그리고 **고친 값**(`properties == []`)이 들어오는지 본다.

🔴 지시서의 *"parser cache architecture 자체를 재설계하지 마라"* 를 지켰다 — 접두사 한
글자만 올렸고 최소 cache 테스트만 추가했다.

---

## 13. 수정 여부 / 내용

**수정했다.** 판정이 C 이고, 지시서가 A/B/C 면 최소 수정을 지시한다.

`sources/lua_loader.py` **한 파일**이다 (`test_40`).

```python
_CLONE_INHERITED_LISTS = (
    "effect_types", "ranges", "target_ranges", "categories", "properties",
)
_RE_LITERAL_ZERO = re.compile(r"0(?:\s*,\s*0)*\s*\Z")

def _write_list(spec, inherited, var, field, regex, args):
    found = regex.findall(args)
    if field in inherited.get(var, ()):
        if not found and not _RE_LITERAL_ZERO.match(args.strip()):
            return                      # 읽지 못했다 — 단정하지 않는다 (§7.6)
        setattr(spec, field, _strip_prefix(found))      # 덮어쓴다
        inherited[var].discard(field)
    else:
        setattr(spec, field, _strip_prefix(getattr(spec, field) + found))  # 더한다
```

* `inherited_types: dict[str, bool]` (3-F-27) 을 `inherited: dict[str, set[str]]` 로
  **일반화**했다 — "이 변수의 **어느 칸**이 `Clone` 이 물려준 값인가".
* `clone` 분기가 **비어 있지 않은** 칸만 추적한다 (빈 목록은 덮어쓰기와 더하기의 결과가
  같다).
* 네 칸의 설정자 분기를 `_write_list` 하나로 모았다.
* `effect_types` 의 동작은 **글자 그대로 같다** — 3-F-27 의 분기가 그대로 남아 있고
  `_write_list` 가 그 칸을 받지 않는다 (`test_35` 가 구문으로 확인한다).
* `_signature` `v6` → `v7`.

### 13.1 하지 않은 것 (지시서 §16 금지 사항)

| 금지 | 확인 |
|---|---|
| Lua 파일 대량 수정 | **0줄** — 고친 것은 파서다 |
| Clone 전체 semantics 재설계 | **안 함** — `list(parent.X)` 다섯 줄 그대로, `deepcopy` 0회 |
| 새로운 EffectID | **없음** — `EffectRef` 그대로 |
| 새로운 graph 시스템 | **없음** |
| Engine 변경 | **0줄** |
| AI/Search 변경 | **0줄** |
| EffectRef 설계 변경 | **없음** |
| 새 abstraction · 새 enum · public API 변경 | **없음** — 새 이름은 private 둘(`_write_list` · `_CLONE_INHERITED_LISTS`) + `_RE_LITERAL_ZERO` |
| `EffectSpec` · `EffectDefinition` · `LuaScriptInfo` 칸 변화 | **없음** |

---

## 14. corpus diff

수정 전 파서 모듈과 수정 후 파서로 12,702 스크립트를 각각 파싱해 `EffectSpec` 9칸과
`LuaScriptInfo` 10칸을 전수 비교했다.

| 지시서 §17 분류 | 결과 |
|---|---|
| A. 오염 제거 | **71 블록-칸 쌍** — 직접 후보 64 + `Clone` 연쇄 전파 7 |
| B. 정상 inheritance 유지 | **2,744 Clone 블록 중 순수 상속은 전부 유지** (`c55948544` `e2`~`e6` 등) |
| C. 정상 additive semantics 유지 | **유지** — 한 블록의 두 번째 이후 호출은 더하기 (`test_17`) |
| D. ordinal 변화 | **0** |
| E. EffectRef 변화 | **0** |
| F. 🔴 예상하지 못한 변화 | **4** — 아래 §14.1 |

| 총계 | 전 | 후 |
|---|---|---|
| 블록 | 34,681 | **34,681** |
| 블록 수가 바뀐 스크립트 | — | **0** |
| `effects` 가 바뀐 스크립트 | — | **59** |
| `ordinal`/`index` 순서가 바뀐 스크립트 | — | **0** |
| `effect_types` 합계 | 45,337 | **45,337** (3-F-27 유지) |
| `ranges` 합계 | 15,075 | **15,063** (−12) |
| `target_ranges` 합계 | 2,072 | **2,062** (−10) |
| `categories` 합계 | 20,534 | **20,505** (−29) |
| `properties` 합계 | 23,907 | **23,884** (−23) |
| `code` · `count_limit` · `cloned_from` 합계 | 30,127 · 11,187 · 2,744 | **그대로** |
| `LuaScriptInfo` 의 다른 10칸 | — | **0건 변화** |

### 14.1 🔴 예상하지 못한 변화를 추적했다

바뀐 블록-칸 쌍은 **75** 인데 직접 후보는 **64** 였다. 11개를 전수로 찾아 원인을 확인했다.

**(1) `Clone` 연쇄 전파 — 7건.** 중간 자식이 좁히면 **그 아래로 전파된다.**

* `c18438874` `e3` (cat·prop 2칸) — `e2` 가 `SetProperty(0)` 으로 비운 값을 `e3` 가 상속
* `c21984400` `e3` · `c295517` `e4` · `c71650854` `e4`·`e5` · `c71948047` `e4`

내 후보 측정이 **첫 자기 호출만** 봤기 때문에 놓친 것이고, **의도된 결과**다
(`test_11` 이 최소 사례로 고정한다).

**(2) 순서만 바뀐 것 — 4건.** 집합은 같고 **순서**만 다르다.

* `c34472920` `['SET_AVAILABLE','IGNORE_IMMUNE']` → `['IGNORE_IMMUNE','SET_AVAILABLE']`
* `c54423935` · `c64591429` · `c95440946`

재진술(`inherited ⊆ own`)인데 더하기는 **상속 순서**를 앞에 두고 덮어쓰기는 **스크립트가
적은 순서**를 쓴다. `_strip_prefix` 가 중복을 제거하므로 집합은 동일하고, 순서는
**스크립트가 적은 쪽이 더 정확하다.**

🔴 둘 다 확인했고, **원인을 모른 채 넘긴 변화는 없다.**

---

## 15. SetType regression (§18 교차 검증)

3-F-27 의 결과를 **되돌리지 않았다** (`test_35`).

| 확인 | 결과 |
|---|---|
| `effect_types` corpus 합계 | 45,337 → **45,337** (변화 0) |
| 모순 조합 블록 (적용 범위 2+ 또는 발동 분류 2+) | **0개** (전수) |
| `IGNORE`/`QUICK_O` — `c324483` `e2` | `['QUICK_O']` — `['IGNITION','QUICK_O']` 이 아니다 |
| Clone + SetType | `test_12` |
| 여러 sibling Clone | `test_05` (다섯 칸) · `test_35` (연쇄 + 형제) |
| Clone 연쇄 | `['IGNITION'] → ['QUICK_O'] → ['TRIGGER_O']`, 그리고 `e4=e1:Clone()` 은 `['IGNITION']` |
| `_write_list` 가 `effect_types` 를 받는가 | **아니다** — 구문으로 확인 |

3-F-28 의 결과도 유지된다 — 블록 34,681 · `ordinal` 불변 · `c39114494` 예외 1건 유지.

---

## 16. production 영향

production diff 는 **`sources/lua_loader.py` 한 파일**뿐이다 (`test_40`).

3-F-28 이 `analysis/effect_analyzer.py` 를 로더에서 `import` 하도록 바꿔 놓았으므로,
이 Phase 는 `analysis` 를 건드리지 않았고 두 모듈의 **블록 탐지가 여전히 일치한다**
(3-F-28 `test_32` 가 전수로 지킨다). `_write_list` 는 블록 **개수**가 아니라 **값**만
바꾸므로 그 정합에 영향이 없다.

---

## 17. Engine 영향

**없다.** Engine V1 freeze 유지 (`test_34`).

* `engine/` 이 diff 에 **없다.**
* `engine/` · `agent/` 가 `EffectSpec` 고유 칸(`effect_types` · `cloned_from` ·
  `count_limit` · `target_ranges`)을 **0회** 읽는다 (AST 전수).
* `CardDefinitionView` 26칸에 `ranges` · `target_ranges` · `categories` · `properties` ·
  `code` · `effects` 가 **없고** `effect_count` 만 있다.

지시서 §15 의 계층을 모두 확인했다 — `EffectDefinition` · `TriggerSpec` · `ChainLink` ·
`EffectActivator` · `ChainResolver` · `legal_actions` · `apply` · `GameStateView` ·
`Search` · `AI` 중 **이 네 칸을 소비하는 곳은 하나도 없다.** 🔴 그러므로 이 수정은
**production execution 에 닿지 않는다.**

---

## 18. AI / Search 영향

**없다.**

* `agent/` 전체가 diff 에 **없다** (`test_33`).
* `core/card_search.py` · `core/query_parser.py` · `core/card_repository.py` ·
  `agent/search.py` 가 diff 에 **없다** (`test_32`).
* 6판 **611결정** digest 불변 (`test_30`). 기대값을 손으로 적지 않고, 다른 테스트
  파일이 이미 고정해 둔 값을 AST 로 읽어 **가장 많이 고정된 것**을 쓴다.

---

## 19. 테스트 결과

### 19.1 신규

`tests/test_clone_sibling_contamination_audit.py` — **42개**. 지시서 §19 의 1~35 를 전부
덮고 7개를 더했다 (근거 43건 · 반대 증거 측정 · 더하기 조합 · corpus diff 범위 ·
production 범위 · 명시적 0 vs 읽을 수 없음 · 그 두 종류의 전수).

### 19.2 기존 테스트 갱신 — 7개

삭제 0 · skip 추가 0 · assertion 약화 0.

| # | 테스트 | 전 → 후 | 왜 |
|---|---|---|---|
| 1 | `setcode_provenance::test_19` | `v6` → **`v7`** | 🔴 3-E-18 의 캐시 가드가 **세 Phase 연속** 설계대로 걸렸다. `v4`·`v5`·`v6` 로 되돌아가지 않았음도 함께 못 박았다 |
| 2 | `settype_clone::test_22` | `v6` → **`v7`** | 같은 이유 |
| 3 | `settype_clone::test_34` (`*_TOTAL`) | `ranges` −12 · `target_ranges` −10 · `categories` −29 · `properties` −23 | 🔴 이 테스트는 3-F-27 이 **"범위 밖" 으로 세어 두기만 한** 결함이고, `test_29` 가 그 수(64)를 **다음 Phase 후보의 근거로** 고정해 두었다. 3-F-29 가 그것을 고쳤으므로 숫자가 움직이는 것이 **설계된 신호**다 |
| 4 | `create_effect_ordinal::test_19` | 캐시 서명 `v6` → `v7` | 주장("캐시가 지금 파서의 결과를 돌려준다")은 그대로, 고정값만 따라 올렸다 |
| 5 | `create_effect_ordinal::test_20` | `v6` → `v7`, 금지 토큰에 `_write_list` 추가 | 되돌아가지 않았는지 보는 목록에 `v6` 를 **추가**했다 — 더 강해졌다 |
| 6 | `create_effect_ordinal::test_21` | 심는 서명 `v5` → `v6` | "**직전 버전**의 캐시가 거부되는가" 를 보는 테스트이므로 파서가 `v7` 이 된 지금은 `v6` 을 심어야 같은 것을 측정한다 |
| 7 | `effectdefinition_activation::test_13` | 원문 문자열 검색 → `code_only` | 🔴 **내가 깨뜨렸다.** 그 테스트가 `assert 'SetTarget' not in loader` 로 **원문**을 검색하는데, 내가 로더 주석에 `SetTargetRange` 를 적자 (`SetTarget` 을 **부분 문자열로** 포함) **코드는 그대로인데** 깨졌다. 주석과 코드를 구분하는 `code_only` 로 바꿨다 — 계약은 같고 **측정이 정확해졌다.** 반대쪽(analysis 가 그 슬롯을 읽는다)도 함께 고정했다 |

### 19.3 🔴 내가 만든 두 실수

1. **`test_30` 의 digest 고정 수를 8 로 적었다.** 실측 **7** 이다 (3-F-28 의 파일은 AST 로
   읽으므로 리터럴을 갖지 않는다). 재측정해 7 로 고쳤다.
2. **`test_37` 에서 "properties 5건 중 4건이 같은 관용구" 라고 적었다.** 실제로는
   **3건**이고, `c49460512` 는 **독립 사례**다. 재측정해 고치고, 독립 사례가 1건 남는다는
   사실을 `test_37` 에 고정했다. **반대 증거를 축소하지 않았다.**

또 하나, `test_13` (§19.2 #7) 은 **내 주석이 남의 테스트를 깨뜨린 사례**다. 교훈:
**원문 문자열 검색은 주석과 코드를 구분하지 못한다** — 3-F-26 에서 같은 교훈을 라인 수
고정에서 배웠고, 이번엔 부분 문자열에서 다시 만났다.

### 19.4 전체 회귀

현재 HEAD 에서 전체 pytest 를 실행했다 (`python -m pytest -q -p no:randomly`).

```
4844 passed, 4 skipped in 1028.38s (0:17:08)
```

| 기준 | 결과 |
|---|---|
| 3-F-28 baseline | 4,802 passed / 4 skipped |
| 이번 Phase | **4,844 passed / 4 skipped** |
| 차이 | **+42** = 신규 테스트 42개 그대로 |
| 예상하지 않은 failure | **0** |
| 삭제 | **0** |
| skip 추가 | **0** (4개 그대로) |
| assertion 약화 | **0** — §19.2 의 7건은 전부 이유를 적고 기대값을 **정확한 새 값**으로 옮긴 것이고, `test_20` 과 `test_13` 은 **더 강해졌다** |
| `state_hash` · RNG · digest · hidden-info | 🟢 §20 |
| Search / AI | 🟢 §18 |
| Engine V1 freeze | 🟢 §17 |

중간 과정도 그대로 적어 둔다 — 수정 직후 1차 전체 회귀는 **7 failed / 4,795 passed**
였다. 캐시 서명 `v6`→`v7` 4건 · 3-F-27 이 세어 둔 형제 칸 총계 1건 · **내 주석이 남의
테스트를 깨뜨린 것 1건**(§19.2 #7) · 그 테스트가 함께 쓰는 파일의 1건이다.

---

## 20. 불변 조건

| 항목 | 결과 | 테스트 |
|---|---|---|
| `state_hash` | 같은 seed 동일 · 다른 seed 상이 | `test_28` |
| RNG | 같은 seed 에서 난수열 12개 동일 | `test_29` |
| digest | 6판 611결정 동일 | `test_30` |
| hidden-info | `CardDefinitionView` 26칸, 블록 내용 칸 0 | `test_31` |
| Search | diff 에 없음 | `test_32` |
| AI | `agent/` diff 에 없음 | `test_33` |
| Engine V1 freeze | `engine/` diff 에 없음 + 네 칸 0회 참조 | `test_34` |
| `EffectRef` / `ordinal` | 블록 수·순서 불변 | `test_19` · `test_20` |
| 3-F-27 `SetType` | `effect_types` 합계 불변 · 모순 0건 | `test_35` |
| 3-F-28 `CreateEffect`/`ordinal` | 블록 34,681 불변 | `test_20` |

---

## 21. 최종 판정

**C. CONFIRMED_PARSER_CLONE_ACCUMULATION**

runtime `Clone` 은 정상이다 — 형제 간 오염도, 역오염도, 가변 컨테이너 공유도 **없다.**
문제는 **parser** 가 `Clone` 이 물려준 값 위에 자식의 자기 호출을 **더한** 것이고, 그래서
자식이 분명히 재지정한 칸에 부모의 값이 남았다 (64블록 + 연쇄 7블록).

🔴 **판정 C 의 문구에 대한 정정** — C 는 *"parser 가 sibling state 를 잘못 누적함"* 이라고
적는데, 실제로 누적되는 것은 **sibling 의 상태가 아니라 parent 의 상태**다. `clone` 분기가
`bindings.get(src)` 로 부모만 집고, 형제는 서로를 볼 수 없다. **"parser 쪽 누적"** 이라는
C 의 취지에는 맞고, "sibling" 이라는 표현은 정확하지 않다. 그 사실을 숨기지 않고 적는다.

* **A 가 아니다** — sibling contamination 은 전수로 0건이다 (§2 D·F · `test_05`).
* **B 가 아니다** — 가변 컨테이너 공유가 0쌍이고 중첩 구조 자체가 없다 (§3.1).
* **D 가 아니다** — 상속은 정상이지만, 자식이 **재지정한 뒤에도** 남는 것은 정상이 아니다.
  `SetCategory(0)` 11건이 그 증거다.
* **E 가 아니다** — 네 칸 어디에도 더하기를 뒷받침하는 독립 증거가 없다. 1건 있는 독립
  사례는 `Clone` 블록이 아니고, 그 동작은 **바꾸지 않았다** (`test_17`).
* **F 가 아니다** — 64블록 전부 실제로 결과가 달라진다.

---

## 22. 남은 구조적 위험

1. 🟠 **네 설정자의 Lua API 의미는 여전히 문서화되지 않았다.** 결론은 corpus 증거
   (재진술 43 · 명시적 0 11 · 조합 4) 에 기반한 것이고, EDOPro 소스로 확인한 것이
   아니다. 반대 방향 독립 증거도 1건 남아 있다 (`c49460512`).
2. 🟠 **"읽을 수 없는 인자" 는 목록 칸에서 "모른다" 를 표현할 수 없다.** 지금은 물려받은
   값을 그대로 두는 쪽을 골랐지만, 그것도 **단정**이다. `code` 처럼 `None`(모른다) 을
   가질 수 있는 구조가 아니라 `[]` 와 "값 있음" 둘뿐이다.
3. 🟠 **한 블록이 같은 설정자를 두 번 부르는 경우의 더하기는 그대로다.** 증거가 1건뿐이라
   바꾸지 않았다. 그 1건이 실제로는 스크립트 버그라면 (대입이면 `IGNORE_IMMUNE` 이
   손실된다) 더하기가 **그 버그를 가리고 있는** 셈이다.
4. 🟠 **캐시 서명에 파서 버전이 여전히 없다.** 세 Phase 연속 손으로 올렸다
   (`v4`→`v5`→`v6`→`v7`).
5. 🟠 **보조 함수가 만드는 effect 를 파서가 모른다** (3-F-28 §22 유지) —
   `Fusion.CreateSummonEff` 45 · `Ritual.CreateProc` 20 · `Ritual.AddProcGreater` 5.
   `c39114494` `e4` 가 부모를 못 찾는 유일한 예외로 남아 있다.
6. 🟠 **`EffectSpec.index` 가 유일하지 않다** (3-F-28 §22 유지).
7. 🟠 **`SetCategory(aux.Stringid(...))` 가 8건 있다** — `SetDescription` 을 쓸 자리에
   쓴 스크립트 버그로 보이지만, 이 Phase 의 범위가 아니므로 세어 두기만 했다.
   파서는 그 호출에서 플래그를 읽지 못하므로 지금은 무해하다 (Clone 블록이 아니다).

---

## 23. Commit

| commit | 내용 |
|---|---|
| (작업) | `Phase 3-F-29: fix Clone sibling contamination` — `sources/lua_loader.py` |
| (테스트) | `Phase 3-F-29: update Clone contamination audit tests` — 신규 42개 + 기존 7개 갱신 |
| (보고서) | `Phase 3-F-29: document Clone sibling contamination audit` |

기존 commit 은 rewrite 하지 않았다. `claude/pensive-goodall-te1egy` 에 push 한다.

---

## 24. 다음 Phase 후보 1개

**Phase 3-F-30 — 분기 안의 설정자 감사 (`if`/`else` 양쪽을 파서가 합친다)**

이 Phase 와 3-E-18 에서 **같은 유형**이 세 번 나왔다.

* `c52445243` — `if lv==1 then e1:SetCategory(DESTROY) elseif lv==2 then
  e1:SetCategory(DRAW) end`. 런타임에는 **하나만** 실행되는데 파서는 둘을 본다.
* `c62784717` — `if ... then e1:SetTargetRange(1,0) else e1:SetTargetRange(0,1) end`.
* 3-E-18 이 `SetCode` 에서 같은 모양 3건을 찾아 *"분기 — Lua 는 둘 중 하나만 실행하지만
  파서는 뒤에 쓰인 쪽을 적는다"* 로 기록했다.

범위가 좁고(파서의 설정자 분기 + 분기 구간 인식), corpus 로 전수 측정할 수 있고, engine 이
그 칸들을 읽지 않는다는 것도 이미 확인되어 있다. 그리고 이 Phase 가 **덮어쓰기**로
바꿨기 때문에 분기의 영향이 전보다 **커졌다** — 전에는 양쪽이 합쳐졌고 지금은 **뒤쪽이
앞쪽을 지운다.** 먼저 "그것이 실제로 몇 블록인지" 와 "파서가 분기를 표현할 수 있는지" 를
조사한 뒤, 표현할 수 없으면 **추측해서 구조화하지 않고 기록만 하는** 것도 정당한 결론이다.
