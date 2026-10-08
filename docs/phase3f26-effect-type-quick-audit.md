# Phase 3-F-26 — `EFFECT_TYPE_QUICK_O` ↔ 몬스터 Spell Speed `UNKNOWN` 경계 감사

> **조사 전용 + docstring 정정 2건.** 실행 코드 0줄 변경.

---

## 0. 🔴 이름부터 — `QUICK_0` 이 아니라 `QUICK_O` 다

사양서는 `EFFECT_TYPE_QUICK_0`(숫자 0)으로 적었지만, 저장소의 실제 상수는
**문자 O** 로 끝난다.

| 측정 | 값 |
|---|---|
| `constant.lua` 의 `EFFECT_TYPE_QUICK_0`(숫자) | **0건** |
| `constant.lua` 의 `EFFECT_TYPE_QUICK_O`(문자) | 1건 (`= 0x100`) |
| Lua corpus 에서 `EFFECT_TYPE_QUICK_0` 을 쓰는 파일 | **0 / 12,702** |
| Lua corpus 에서 `EFFECT_TYPE_QUICK_O` 을 쓰는 파일 | **1,718 / 12,702** |

그리고 짝을 이루는 **`EFFECT_TYPE_QUICK_F`** 가 따로 있다(`= 0x400`, 16블록).
이 보고서는 실제 이름 `QUICK_O` 를 쓴다.

---

## 1. 실제 HEAD / Base — `git` 으로 검증

| 항목 | 지정값 | 실제 확인 | 결과 |
|---|---|---|---|
| 3-F-25 작업 commit | `9f42dae` | `9f42dae` Phase 3-F-25: audit EVENT_FREE_CHAIN semantics | ✅ |
| 3-F-25 보고서 commit | `adcd877` | `adcd877` Phase 3-F-25: document EVENT_FREE_CHAIN semantic audit | ✅ |
| 작업 시작 HEAD | — | `adcd877` | ✅ |
| worktree | — | `git status --short` 출력 없음 · `git diff --stat` 없음 | ✅ clean |
| `origin` 동기 | — | `HEAD == origin/claude/pensive-goodall-te1egy` | ✅ |
| branch | — | `claude/pensive-goodall-te1egy` | ✅ |

기존 commit rewrite 없음.

---

## 2. `QUICK_O` corpus 통계 — §3

### 단위를 먼저 고정한다

3-F-25 와 같은 규칙: **스크립트 단위**를 기준으로 쓰고, 카드 종류가 필요한
통계만 **카드 단위**로 쓴다. 섞지 않는다.

| 측정 | 스크립트 단위 | 카드 단위 |
|---|---|---|
| 전체 블록 | 34,680 | 35,385 |
| `QUICK_O` 블록 | **1,875** | 1,952 |
| `QUICK_O` 보유자 | **1,712** 스크립트 | **1,781** 카드 |
| 모집단 | 12,702 스크립트 | 12,968 카드 (전체 14,520) |

사양서가 인용한 "약 1,875" 는 **스크립트 단위**와 일치한다.

### 🔴 카드 종류별 — "대부분 몬스터" 와 "몬스터 전용" 은 다르다

| 카드 종류 | `QUICK_O` 카드 | 전체 | 비율 | 공식 Spell Speed |
|---|---|---|---|---|
| 몬스터 | **1,338** | 8,268 | 16.2% | 효과별 (카드로 안 정해짐) |
| 통상 함정 | 185 | 1,283 | 14.4% | 2 |
| 지속 함정 | **229** | 542 | 42.3% | 2 |
| **카운터 함정** | **16** | 167 | 9.6% | **3** |
| 지속 마법 | 10 | 478 | 2.1% | **1** |
| 필드 마법 | 2 | 312 | 0.6% | **1** |
| 장착 마법 | 1 | 274 | 0.4% | **1** |
| 통상 마법 | **0** | 1,037 | — | 1 |
| 속공 마법 | **0** | 522 | — | 2 |
| 의식 마법 | **0** | 79 | — | 1 |

> 🔴 **몬스터 전용이 아니다.** 몬스터가 아닌 `QUICK_O` 카드가 **443장**이고,
> 몬스터 비중은 1,338/1,781 = **75.1%** 다.
>
> 그리고 **속공 마법에는 하나도 없다.** 공식적으로 속공 마법이야말로 스펠
> 스피드 2 인데, Lua 는 그것을 `QUICK_O` 로 적지 않는다 — 이름만 보고 의미를
> 추론하면 안 되는 이유가 데이터에 그대로 있다.

### `initial_effect` 안/밖

3-F-25 가 측정했듯 `CreateEffect` 의 **23.2%** 가 `initial_effect` 밖이다.
`QUICK_O` 블록도 그 구분을 따르며, 이 Phase 는 **블록을 세고
`(card_id, index)` 를 키로 쓰지 않는다** (index 는 고유하지 않다).

---

## 3. `effect_types` 구조 — §11

### 🔴 15개는 독립 비트다 — **하나의 분류가 아니라 플래그 집합**

```lua
EFFECT_TYPE_SINGLE     = 0x1      EFFECT_TYPE_TRIGGER_O  = 0x80
EFFECT_TYPE_FIELD      = 0x2      EFFECT_TYPE_QUICK_O    = 0x100
EFFECT_TYPE_EQUIP      = 0x4      EFFECT_TYPE_TRIGGER_F  = 0x200
EFFECT_TYPE_ACTIONS    = 0x8      EFFECT_TYPE_QUICK_F    = 0x400
EFFECT_TYPE_ACTIVATE   = 0x10     EFFECT_TYPE_CONTINUOUS = 0x800
EFFECT_TYPE_FLIP       = 0x20     EFFECT_TYPE_XMATERIAL  = 0x1000
EFFECT_TYPE_IGNITION   = 0x40     EFFECT_TYPE_GRANT      = 0x2000
                                  EFFECT_TYPE_TARGET     = 0x4000
```

15개가 전부 **서로 다른 한 비트**(2의 거듭제곱, 겹침 0)이고 `SetType` 은
그것을 `+` 로 묶어 받는다.

### 동시 등장 행렬 (교체 규칙 기준 · `.` = 0)

|  | SINGLE | FIELD | EQUIP | ACTIVATE | FLIP | IGNITION | TRIGGER_O | QUICK_O | TRIGGER_F | QUICK_F | CONT. | XMAT. | GRANT |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **SINGLE** | 14,731 | . | . | . | 189 | . | 4,070 | . | 1,236 | . | 860 | . | . |
| **FIELD** | . | 8,881 | . | . | . | . | 2,016 | 4 | 735 | . | 1,583 | 3 | 30 |
| **EQUIP** | . | . | 639 | . | . | . | . | . | . | . | 13 | . | . |
| **ACTIVATE** | . | . | . | 4,297 | . | . | . | . | . | . | . | . | . |
| **FLIP** | 189 | . | . | . | 189 | . | **63** | . | **6** | . | . | . | . |
| **IGNITION** | . | . | . | . | . | 4,137 | . | . | . | . | . | 5 | . |
| **TRIGGER_O** | 4,070 | 2,016 | . | . | 63 | . | 6,087 | . | . | . | . | 2 | . |
| **QUICK_O** | . | **4** | . | . | . | . | . | **1,875** | . | . | . | **4** | . |
| **TRIGGER_F** | 1,236 | 735 | . | . | 6 | . | . | . | 1,972 | . | . | 1 | . |
| **QUICK_F** | . | . | . | . | . | . | . | . | . | 16 | . | . | . |
| **CONTINUOUS** | 860 | 1,583 | 13 | . | . | . | . | . | . | . | 2,456 | . | . |

`TARGET` · `ACTIONS` 는 corpus 에 **0블록**이다.

### 축이 최소 둘이다

| 축 | 플래그 | 서로 공존 |
|---|---|---|
| **적용 범위** | `SINGLE` 14,731 · `FIELD` 8,881 · `EQUIP` 639 | **0회** — 완전 배타 |
| **발동 분류** | `TRIGGER_O` 6,087 · `ACTIVATE` 4,297 · `IGNITION` 4,137 · `CONTINUOUS` 2,456 · `TRIGGER_F` 1,972 · `QUICK_O` 1,875 · `FLIP` 189 · `QUICK_F` 16 | 대부분 배타, **`FLIP` 만 예외** |

### `EffectDefinition` 구조 — 네 가지가 섞여 있는가

| 칸 | 담는 것 | `effect_types` 인가 |
|---|---|---|
| `effect_ref` | 어느 카드의 몇 번째 효과인가 | ✗ |
| `source_card_id` | 정의의 출처 카드 | ✗ |
| `operations` | **하는 일** | ✗ |
| `activation` | **발동 조건** (`Condition \| None`) — `None` 은 "없다" 가 아니라 "적지 않았다" | ✗ |
| `cost` · `targets` · `declarations` · `requirements` · `guards` · `provenance` | 비용 · 대상 · 수 선언 · 조작 간 순서 · 조작 가드 · 출처 | ✗ |

> 🔴 **`EffectDefinition.effect_types` 는 존재하지 않는다.** 10칸 전수로
> 확인했다. 사양서가 조사 대상으로 적은 그 이름은 **없는 필드**다 —
> `code` 와 똑같은 모양이다 (3-F-24 · 3-F-25).

그래서 네 개념은 **섞여 있지 않다** — 섞일 자리조차 없다:

```
effect_types        (EffectSpec · 파서 계층)        ← engine 에 없다
activation          (EffectDefinition.activation)  ← 발동 조건
activation timing   (engine/activation_timing.py)  ← 체인 · 우선권 · 스펠 스피드
Spell Speed         (SpellSpeedClassification)     ← 카드 종류에서 파생
```

### 🔴 `effect_types` 라는 **같은 이름이 둘**

| 이름 | 실제로 담는 것 |
|---|---|
| `EffectSpec.effect_types` | Lua `EFFECT_TYPE_*` 플래그 (15종) |
| `rules.structured.StructuredRules.effect_types` | **공식 룰북의 효과 종류 5종** |

부분 문자열로 세면 조용히 섞인다.

---

## 4. 실제 카드 표본 — 34장

실제 카드명을 측정으로 확인한 것만 적는다. "공식 SS" 는 **룰북의 Spell Speed
표**에서 오고, Lua 이름에서 역추론하지 않는다.

### ① `QUICK_O` 단독 몬스터

| passcode | 카드명 | effect_types (블록별) | code | 공식 SS | 엔진 classify |
|---|---|---|---|---|---|
| 494922 | 초중황신 스사노－O | SINGLE / **QUICK_O** / SINGLE | `EFFECT_DEFENSE_ATTACK`, `EVENT_FREE_CHAIN`, … | 효과별 | UNKNOWN |
| 744887 | 허구의 제너레이드 우트가르자 | **QUICK_O** | `EVENT_FREE_CHAIN` | 효과별 | UNKNOWN |
| 900787 | 드래그니티 나이트－게이볼그 | **QUICK_O** / SINGLE | `EVENT_FREE_CHAIN`, … | 효과별 | UNKNOWN |
| 1287123 | 머티리얼 팔코 | **QUICK_O** | **`EVENT_CHAINING`** | 효과별 | UNKNOWN |
| 1340142 | 바르모니카의 신주－바라르 | SINGLE / SINGLE / **QUICK_O** | …, `EVENT_SPSUMMON` | 효과별 | UNKNOWN |

### ② `TRIGGER_O` 몬스터 (`QUICK_O` 없음)

| passcode | 카드명 | effect_types | 공식 SS | 엔진 classify |
|---|---|---|---|---|
| 123709 | 라바르 란스로드 | SINGLE / SINGLE+TRIGGER_O / FIELD+TRIGGER_F | 효과별 | UNKNOWN |
| 135598 | 키 마우스 | SINGLE+TRIGGER_O | 효과별 | UNKNOWN |
| 176392 | 코아키메일 테스트베드 | CONTINUOUS+FIELD / FIELD+TRIGGER_O | 효과별 | UNKNOWN |
| 220414 | EM 턴트루퍼 | FIELD+TRIGGER_O ×2 / IGNITION | 효과별 | UNKNOWN |

### ③ `IGNITION` 몬스터 (`QUICK_O` 없음)

| passcode | 카드명 | effect_types | 공식 SS | 엔진 classify |
|---|---|---|---|---|
| 39015 | 버스터 스나이퍼 | IGNITION ×2 / FIELD / SINGLE | 효과별 | UNKNOWN |
| 41546 | DD 마도현자 토마스 | IGNITION ×2 / SINGLE ×2 | 효과별 | UNKNOWN |
| 109401 | 암흑차원의 전사 | IGNITION / FIELD+TRIGGER_F | 효과별 | UNKNOWN |
| 114932 | 플레이트 크래셔 | IGNITION | 효과별 | UNKNOWN |

### ④ `CONTINUOUS` 몬스터

| passcode | 카드명 | effect_types | 공식 SS | 엔진 classify |
|---|---|---|---|---|
| 131182 | 미러클 플리퍼 | SINGLE ×3 / FIELD | 효과별 | UNKNOWN |
| 293542 | TG 워울프 | FIELD+TRIGGER_O / SINGLE+CONTINUOUS / FIELD+TRIGGER_O | 효과별 | UNKNOWN |
| 368382 | 다이너미스트 브라키온 | FIELD+CONTINUOUS / FIELD | 효과별 | UNKNOWN |

### ⑤ `FLIP` 몬스터

| passcode | 카드명 | effect_types | 공식 SS | 엔진 classify |
|---|---|---|---|---|
| 62121 | 암흑의 성 | **SINGLE+FLIP** / FIELD ×2 / FIELD+TRIGGER_F | 효과별 | UNKNOWN |
| 759393 | 화령사 히타 | **SINGLE+FLIP** / SINGLE | 효과별 | UNKNOWN |
| 759394 | Hiita the Fire Charmer | **SINGLE+FLIP** / SINGLE | 효과별 | UNKNOWN |

### ⑥ 🔴 `QUICK_O` + 공식 SS1 계열이 **한 카드에** 섞인 몬스터

| passcode | 카드명 | effect_types | 공식 SS | 엔진 classify |
|---|---|---|---|---|
| 2511 | 라뷰린스 쿠클락 | **QUICK_O** / FIELD+**TRIGGER_O** / FIELD | 효과별 — **답이 둘** | UNKNOWN |
| 35699 | SPYRAL－보텍스 | SINGLE / FIELD / **QUICK_O** / SINGLE+**TRIGGER_F** | 효과별 — **답이 둘** | UNKNOWN |
| 43227 | 매그넘 더 릴리버 | **IGNITION** / **QUICK_O** | 효과별 — **답이 둘** | UNKNOWN |
| 44818 | 홀리나이츠 오르비타엘 | **QUICK_O** / FIELD+**TRIGGER_O** | 효과별 — **답이 둘** | UNKNOWN |
| 122520 | EM 스카이 퓨필 | **QUICK_O** / FIELD / SINGLE+**TRIGGER_O** | 효과별 — **답이 둘** | UNKNOWN |

### ⑦ 🔴 `QUICK_O` 인데 Quick Effect 로 단정하기 어려운 비몬스터

| passcode | 카드명 | 카드 종류 | effect_types | 공식 SS | 엔진 classify |
|---|---|---|---|---|---|
| 703897 | 오르페골 클리막스 | **카운터 함정** | ACTIVATE / **QUICK_O** / FIELD | **3** | 스펠 스피드 **3** |
| 799183 | 초전사의 방패 | **카운터 함정** | ACTIVATE / **QUICK_O** / SINGLE | **3** | 스펠 스피드 **3** |
| 27561302 | 비의 천후모양 | 지속 마법 | ACTIVATE / **QUICK_O** / FIELD+GRANT | **1** | 스펠 스피드 **1** |
| 28669235 | 등룡화해롱문 | 지속 마법 | ACTIVATE / FIELD / **QUICK_O** / FIELD+GRANT | **1** | 스펠 스피드 **1** |
| 31461282 | 개운 미라클 스톤 | 지속 마법 | ACTIVATE / FIELD ×2 / **QUICK_O** | **1** | 스펠 스피드 **1** |
| 276357 | 에스프릿 힐링 | 지속 함정 | ACTIVATE / **QUICK_O** / FIELD+TRIGGER_O | 2 | 스펠 스피드 2 |
| 1157683 | 사이버다크 인베이전 | 지속 함정 | ACTIVATE / **QUICK_O** ×2 / SINGLE / EQUIP | 2 | 스펠 스피드 2 |

### ⑧ `QUICK_F` (`QUICK_O` 가 **아닌** 쪽)

| passcode | 카드명 | effect_types | 비고 |
|---|---|---|---|
| 65240384 | 빅 실드 가드너 | SINGLE+CONTINUOUS / **QUICK_F** | `QUICK_O` 없음 |
| 2948263 | 고고고 골렘－GF | SINGLE / FIELD / SINGLE / **QUICK_F** | `QUICK_O` 없음 |
| 5861892 | 아르카나 포스 EX－빛의 통치자 | FIELD / SINGLE / SINGLE+TRIGGER_F / … | `QUICK_F` 포함 |

`QUICK_F` 는 **16장**이고 `QUICK_O` 와 **0회** 공존한다.

### ⑨ 파서 누적 artifact 의 원본

| passcode | 카드명 | Lua 원문 | 파서 결과 |
|---|---|---|---|
| 324483 | — | `e1:SetType(IGNITION)` → `e2=e1:Clone()` → `e2:SetType(QUICK_O)` | `e2.effect_types = ['IGNITION','QUICK_O']` |

---

## 5. `QUICK_O` ↔ `TRIGGER_F` / `IGNITION` / `FLIP` 관계 — §5

### 블록 단위 — 배타인가

| 쌍 | production (누적) | 교체 규칙 | 판정 |
|---|---|---|---|
| `QUICK_O` + `TRIGGER_F` | **0** | **0** | 배타 |
| `QUICK_O` + `TRIGGER_O` | **0** | **0** | 배타 |
| `QUICK_O` + `QUICK_F` | **0** | **0** | 배타 |
| `QUICK_O` + `FLIP` | **0** | **0** | 배타 |
| `QUICK_O` + `CONTINUOUS` | **0** | **0** | 배타 |
| `QUICK_O` + `IGNITION` | **41** | **0** | 🔴 **전부 파서 artifact** |
| `QUICK_O` + `ACTIVATE` | **5** | **0** | 🔴 **전부 파서 artifact** |
| `QUICK_O` + `FIELD` | 4 | **4** | 실제 — 다른 축(적용 범위) |
| `QUICK_O` + `XMATERIAL` | 4 | **4** | 실제 |

### 🔴 `IGNITION+QUICK_O` 41건은 카드 데이터가 아니다

파서의 `"Type"` 분기는 이렇게 **더한다**:

```python
if setter == "Type":
    spec.effect_types = _strip_prefix(
        spec.effect_types + _RE_EFFECT_TYPE.findall(args)
    )
```

그리고 `"clone"` 분기는 부모의 목록을 **물려준다**
(`spec.effect_types = list(parent.effect_types)`). 그래서 `Clone` 뒤에
`SetType` 을 다시 부른 블록은 **물려받은 플래그를 그대로 달고 있다.**

실제 Lua (`c324483.lua`):

```lua
local e1=Effect.CreateEffect(c)
e1:SetType(EFFECT_TYPE_IGNITION)
...
local e2=e1:Clone()
e2:SetType(EFFECT_TYPE_QUICK_O)
```

**판단 근거를 저장소 내부로 한정한다.** EDOPro `SetType` API 의 정확한
의미는 이 저장소에 문서화돼 있지 않다. 그러나 다음은 측정된 사실이다.

- 한 `SetType` 호출 안에서 `IGNITION` 과 `QUICK_O` 를 **함께 적는 카드는
  corpus 전체(34,680블록)에 0장**이다.
- 41건 **전부** `cloned_from` 이 채워져 있다 (`e1` 22 · `e2` 15 · `e3` 2 ·
  `e4` 2).
- 그러므로 파서의 출력은 **어떤 카드도 적지 않은 조합**을 주장한다.

### 결함의 규모

| 측정 | 값 |
|---|---|
| 누적 때문에 교체 규칙과 달라지는 블록 | **78 / 34,680 = 0.22%** |
| 해당 스크립트 | **75** |
| 그중 `QUICK_O` 관련 | **46** (전부 `Clone` 유래) |
| 남은 여분 플래그 상위 | `IGNITION` 41 · `SINGLE` 15 · `FIELD` 11 · `ACTIVATE` 8 · `TRIGGER_O` 1 |
| 영향 **없는** 플래그 | `QUICK_O` · `TRIGGER_F` · `QUICK_F` · `FLIP` · `CONTINUOUS` · `EQUIP` · `GRANT` · `XMATERIAL` (0) |

> 🔴 `QUICK_O` 자체의 **개수는 영향받지 않는다**(1,875 양쪽 동일). 누적은
> 플래그를 **더하기만** 하고 빼지 않는다.

### 🔴 `code` 는 같은 위험을 이미 고쳤다 — `effect_types` 는 안 고쳤다

파서의 `"Code"` 분기에는 Phase 3-E-18 의 수정이 **주석까지 달려** 있다.

> *"여기서 **앞 값을 그대로 두면 안 된다.** Clone 은 부모의 `code` 를
> 물려받으므로, 물려받은 값이 남은 채 스크립트가 분명히 덮어쓴 코드를 계속
> 주장하게 된다 … 읽지 못한 것은 **모른다**(`None`)로 되돌린다."*

`"Type"` 분기에는 그 처리가 **없다.** 같은 결함 유형이 한 필드에서는 고쳐지고
다른 필드에서는 남았다.

**이 Phase 는 파서를 바꾸지 않았다** (§15 금지). 무엇이 올바른 등재 규칙인지
정해지기 전에 바꾸면 무엇을 잃는지 알 수 없다.

### 🔴 `FLIP` 만 예외다 — 그리고 공식 룰북이 그것을 적는다

| `FLIP` 189블록과 함께 | 수 |
|---|---|
| `SINGLE` | 189 (전부) |
| `TRIGGER_O` | **63** |
| `TRIGGER_F` | **6** |
| `QUICK_O` | 0 |

공식 룰북 `effect_types` 의 Flip Effect 항목:

> *"Flip effect is a part of the Trigger Effect."*

즉 발동 분류 축조차 **완전한 배타가 아니고**, 그 예외가 공식 개념과 **방향이
맞는다**. (이것이 이 Phase 가 찾은 유일한 공식↔Lua 일치다.)

### `QUICK_O` 를 "효과의 최종 분류" 로 볼 수 있는가

| 질문 | 답 |
|---|---|
| **효과(블록)** 의 최종 분류인가? | **그렇다** — 발동 분류 축의 다른 플래그와 0회 공존 |
| **카드**의 분류인가? | 🔴 **아니다** — 아래 |

`QUICK_O` 카드 1,781장 중 **다른 발동 분류 블록이 전혀 없는 카드는 418장
(23.5%)** 뿐이다.

| `QUICK_O` 카드가 함께 가진 블록 | 카드 수 | 비율 |
|---|---|---|
| `TRIGGER_O` | 604 | 33.9% |
| `ACTIVATE` | 429 | 24.1% |
| `IGNITION` | 293 | 16.5% |
| `CONTINUOUS` | 254 | 14.3% |
| `TRIGGER_F` | 90 | 5.1% |
| `FLIP` | 5 | 0.3% |
| `QUICK_F` | **0** | — |

---

## 6. 공식 Quick Effect 정의 — §6

### A · B — 공식 정의가 있는가, 저장소에 근거가 있는가

공식 룰북(`data/rules/structured/sd-rulebook-en-v10.json`)의 `effect_types`:

| 공식 분류 | `spell_speed` | `has_activation` | `activation_timing` |
|---|---|---|---|
| **Quick Effect** | **2** | True | `null` (`not_stated: ["activation_timing"]`) |
| Ignition Effect | 1 | True | `"your Main Phase"` |
| Trigger Effect | 1 | True | `"specific times, such as during the Standby Phase or when this monster is destroyed"` |
| Flip Effect | 1 | True | `"when a face-down card is flipped face-up"` — *"part of the Trigger Effect"* |
| Continuous Effect | 1 | **False** | `null` — *"There is no trigger for its activation"* |

→ **A: 있다. B: 있다.** 공식 5종이 `spell_speed` 와 함께 정의돼 있다.

### C — `QUICK_O` 과 직접 대응한다고 볼 근거가 있는가

> 🔴 **없다.**

| 측정 | 값 |
|---|---|
| 공식 자료(룰북 · 재정 686파일 · 한국어 DB) 검사 파일 | **829** |
| `QUICK_O` 출현 | **0** |
| `QUICK_F` · `TRIGGER_O` · `TRIGGER_F` · `EFFECT_TYPE` 출현 | **각 0** |

probe 는 살아 있다 — 같은 자료에서 `Quick Effect` · `Spell Speed` ·
`Ignition Effect` 는 정상적으로 잡힌다.

그리고 **개수부터 다르다** — 공식 5종 vs Lua 15종. 1:1 대응이 성립할 수 없는
모양이다.

### D — 단순히 데이터 분류일 가능성이 있는가

> **그렇다.** 그것이 측정이 지지하는 쪽이다 (§15 판정).

### 🔴 `_O` / `_F` 접미사의 뜻 — **UNKNOWN 으로 남긴다**

Phase 3-E-31 보고서가 `TRIGGER_O` 를 *(임의)*, `TRIGGER_F` 를 *(강제)* 로
적었다. 이 Phase 는 그 뜻풀이를 **근거 없음**으로 기록한다.

- 공식 자료에 그 이름이 **0회**다(위).
- production 코드에서 접미사를 **해석하는 자리가 0곳**이다 (주석/docstring 만).
- 엔진에는 `TriggerRequirement.MANDATORY` / `OPTIONAL` 축이 **따로** 있고,
  그것은 `TriggerSpec.requirement` 에서 오며 `effect_types` 와 **연결되지
  않는다**.

즉 "강제/임의 축이 엔진에 있다" 와 "Lua 에 `_O`/`_F` 쌍이 있다" 는 **둘 다
사실**이지만, **그 둘을 잇는 근거는 저장소에 없다.** 이 Phase 는 잇지 않는다.

---

## 7. Spell Speed 와의 관계 — §7

### 🔴 `QUICK_O → Spell Speed 2` 는 성립하지 않는다

카드 종류로 공식 스펠 스피드가 정해지는 `QUICK_O` 카드:

| 공식 Spell Speed | `QUICK_O` 카드 | 내역 |
|---|---|---|
| **1** | **13** | 지속 마법 10 · 필드 마법 2 · 장착 마법 1 |
| **2** | 414 | 통상 함정 185 · 지속 함정 229 |
| **3** | **16** | **카운터 함정** |
| 정해지지 않음 | 1,338 | 몬스터 |

**세 등급 전부에 걸쳐 있다.** 엔진이 실제로 돌려주는 값으로도 확인된다 —
오르페골 클리막스(`QUICK_O` 보유)는 **스펠 스피드 3**, 비의 천후모양
(`QUICK_O` 보유)은 **스펠 스피드 1**.

### 사양서가 요구한 각 항목

| 항목 | 결과 |
|---|---|
| `QUICK_O` 카드의 공식 Spell Speed | 1 · 2 · 3 **전부** (위 표) |
| `QUICK_O` + `TRIGGER_F` 카드 | **블록 단위 0건.** 카드 단위로는 90장이 두 블록을 따로 가진다 |
| `QUICK_O` + `IGNITION` 카드 | **블록 단위 0건**(41은 artifact). 카드 단위 293장 |
| `QUICK_O` + `FLIP` 카드 | **블록 단위 0건.** 카드 단위 5장 |
| `QUICK_O` 가 없는 몬스터 Quick Effect 가 있는가 | **UNKNOWN** — 카드별 공식 분류 자료가 저장소에 없다. 단 `QUICK_F` 16장이 `QUICK_O` 없이 별도 "quick" 플래그를 가진다 |
| `QUICK_O` 인데 Spell Speed 2 가 아닌 사례 | **29장** (SS1 13 + SS3 16) — 반례가 실재한다 |

### 🔴 §7 판정

> ## **C. DATA_CLASSIFICATION_ONLY**

**근거**

1. `QUICK_O` 라는 이름이 공식 자료 **829파일에 0회**다(§6 C).
2. 공식 Spell Speed 와 **1:1 이 아니다** — 1 · 2 · 3 전부에 걸치고, 반례가
   29장이다(§7).
3. 공식 분류는 **5종**, Lua 플래그는 **15종**이다. 모양이 다르다.
4. 공식 Quick Effect 의 대표 카드군인 **속공 마법에는 `QUICK_O` 가 0건**이다
   — 이름이 가리키는 쪽에 데이터가 **없다.**
5. engine/agent 코드에서 **0회** 소비된다(§12). 동작에 아무 의미도 갖지
   않는다.
6. `FLIP` ↔ Trigger 라는 **한 가지** 일치(§5)는 있지만, 그것은 `QUICK_O` 의
   대응이 아니다.

**왜 A 가 아닌가** — `DIRECT_SPELL_SPEED_2_MAPPING` 은 29장의 반례로 **직접
반증**된다.

**왜 B 가 아닌가** — `QUICK_EFFECT_CORRELATION_ONLY` 는 *"공식 Quick Effect 와
상관이 있다"* 를 주장한다. 그 주장을 하려면 카드별 공식 분류가 있어야 하는데
저장소에 **없다**. 그리고 가장 쉽게 확인할 수 있는 상관 — 공식 스펠 스피드 —
은 **역방향 반례**를 낸다(카운터 함정 16 · SS1 마법 13). 근거 없는 semantic
mapping 을 만들지 않는다.

**왜 D 가 아닌가** — `SEMANTIC_UNRESOLVED` 는 *"의미를 확정할 수 없다"* 다.
공식 대응은 확실히 미확정이고 그것을 §6 에 UNKNOWN 으로 적었다. 그러나 **이
저장소에서 이 값이 무엇인지**는 확정됐다 — 파서가 쓰고 분석이 읽는 **데이터
분류 플래그**이며 engine 이 소비하지 않는다. C 는 바로 그 문장이다.

> 🔴 **판정이 바뀔 조건.** 카드별 공식 효과 분류(공식 DB Q&A 본문 또는 공식
> 룰북의 카드별 기재)를 확보해 `QUICK_O` 와 대조할 수 있게 되면 **B** 로 옮길
> 수 있다. 이 Phase 는 그 자료를 얻지 못했다 (3-F-25 가 공식 DB 전문검색이
> 작동하지 않음을 확인했다).

---

## 8. `activation_timing.py` 경계 — §8 의 A~G

| 질문 | 답 | 근거 |
|---|---|---|
| **A.** `QUICK_O` 를 직접 읽는가? | **아니다** | 모듈 전체 코드(문자열 제거)에 `effect_types` · `QUICK_O` **0회** |
| **B.** 읽는다면 어디서? | — | 해당 없음 |
| **C.** 현재 무엇을 쓰려 하는가? | **카드 종류** | `classify_spell_speed` 가 읽는 속성은 `type_names` · `is_trap` · `is_spell` · `is_monster` **뿐**(AST 측정) |
| **D.** `QUICK_O` 가 없어서 `UNKNOWN` 인가? | **아니다** | 데이터는 파서 계층에 **있다**(1,875블록) |
| **E.** 다른 데이터가 없어서인가? | **부분적으로 그렇다** | `CardDefinitionView` 26칸에 그 값이 없어 engine 은 **볼 수조차 없다** |
| **F.** `QUICK_O` 로 해결할 수 있는 문제인가? | 🔴 **아니다 — 그것만으로는** | §9 |
| **G.** 공식 semantic contract 가 충분히 확정됐는가? | **아니다** | §6 C — 공식 자료에 0회, Spell Speed 와 역방향 반례 |

> **"구현할 수 있다" 와 "구현해도 계약상 안전하다" 를 구분한 결과:**
> 전자도 성립하지 않고(§9 의 입도 문제), 후자는 더 멀다(G). 그래서 이 Phase 는
> **구현하지 않는다.**

### 실제 경로

```
classify_spell_speed(definition: CardDefinitionView | None)
  ├─ is_trap  + "COUNTER" in type_names → SpellSpeed.COUNTER (3)
  ├─ is_trap                            → SpellSpeed.FAST    (2)
  ├─ is_spell + "QUICKPLAY"             → SpellSpeed.FAST    (2)
  ├─ is_spell                           → SpellSpeed.NORMAL  (1)
  └─ is_monster                         → None, missing=MONSTER_CLASSIFICATION_MISSING
                                           ↑ 여기서 끝난다

ActivationTimingChecker.spell_speed(instance)
  → self._view.find(instance).definition        ← 카드 단위
  → classify_spell_speed(...)

ActivationTimingChecker.speed_of_link(link)
  → self.spell_speed(link.source)               🔴 link.effect_ref 를 **버린다**
```

---

## 9. `MONSTER_CLASSIFICATION_MISSING` 의 원인 — §10 분해

사유 문자열 자체:

```python
MONSTER_CLASSIFICATION_MISSING = (
    "monster effect classification (기동 · 유발 · 플립 vs 유발즉시)"
)
```

**"monster *effect* classification"** — 카드가 아니라 **효과**다.

| § | 가능성 | 성립? | 실제 근거 |
|---|---|---|---|
| **A** | `QUICK_O` 정보가 실제로 없다 | ❌ | 파서 계층에 1,875블록으로 **있다** |
| **B** | 있는데 현재 코드가 읽지 않는다 | ✅ | engine/agent 코드 등장 **0회**. `CardDefinitionView` 26칸에 **없다** |
| **C** | 공식 의미가 충분히 확정되지 않았다 | ✅ | 공식 자료 829파일에 **0회**, Spell Speed 와 역방향 반례 29장 |
| **D** | 분류 정보가 여러 필드에 분산 | ✅ | `effect_types`(15플래그 · 2축) + `code`(298상수) + 카드 `type_mask`. 한 카드가 블록마다 다른 분류를 가진다 |
| **E** | 현재 설계가 분류와 timing 을 혼합 | ⚠️ 부분 | `SpellSpeedClassification` 은 **속도**만 담고 분류를 담지 않는다. 혼합은 아니고 **분류 단계가 아예 없다** |
| **F** | 분류와 Spell Speed 는 별도 축인데 하나로 취급 | ✅ **주원인** | 아래 |

### 🔴 F — 주원인은 **입도(granularity)** 다

| 측정 | 값 |
|---|---|
| 몬스터 | 8,268 |
| 🔴 공식 SS1 계열(`IGNITION`·`TRIGGER_O`·`TRIGGER_F`·`FLIP`)과 SS2 계열(`QUICK_O`·`QUICK_F`) 블록을 **둘 다** 가진 몬스터 | **856 (10.4%)** |
| SS2 계열만 | 497 |
| SS1 계열만 | 6,020 |
| 발동 분류 블록이 하나도 없는 몬스터 | 895 |
| `QUICK_O` 몬스터 1,338 중 SS1 계열도 가진 것 | **847 (63.3%)** |

`classify_spell_speed` 는 **카드 하나**를 받아 **값 하나**를 돌려준다. 그런데
856장에는 **카드 단위의 답이 존재하지 않는다.** `effect_types` 를
`CardDefinitionView` 에 그대로 실어도 그 함수는 답할 수 없다 — 묻는 단위가
틀렸기 때문이다.

그리고 효과 단위 정보가 **있는 자리에서 버려진다**:

```python
def speed_of_link(self, link: ChainLink | None) -> SpellSpeedClassification:
    ...
    return self.spell_speed(link.source)   # link.effect_ref 를 쓰지 않는다
```

`ChainLink` 는 `effect_ref` 를 **들고 있다**(6칸 중 하나). 즉 체인 문맥에서는
"어느 효과인가" 를 **이미 알고 있는데** 카드 단위 함수로 내려간다.

### 🔴 §10 판정 (복수)

> ## **B. DATA_PRESENT_BUT_UNUSED**
> ## **C. SEMANTIC_NOT_CONFIRMED**
> ## **D. MODEL_LAYER_SEPARATION**
> ## **F**(별도 축을 하나로 취급) — 사양서 §18 의 목록에서는 **D** 에 포함

사양서 §18 의 선택지로 환원하면 **B · C · D 세 가지가 함께 성립**한다.
**A(MISSING_DATA)는 성립하지 않고**, **E(INTENTIONAL_ENGINE_BOUNDARY)는 부분적
으로만 성립한다** — 모듈이 *"추측해서 1 로도 2 로도 만들지 않는다"* 라고 적는
것은 분명한 의도이지만, 그 의도가 **입도 문제를 선택한 것은 아니다**. 입도
불일치는 설계의 결과이지 선언된 경계가 아니다.

---

## 10. `EffectDefinition` 구조 — §11

→ **§3 의 마지막 두 절**에 표로 정리했다. 요약:

- `EffectDefinition` 은 **10칸**이고 `effect_types` · `code` **둘 다 없다.**
- `effect_types` ≠ `activation` ≠ activation timing ≠ Spell Speed 는 **서로 다른
  모듈의 서로 다른 타입**이다. 섞여 있지 않다.
- 🔴 다만 **`effect_types` 라는 이름이 두 곳**에 있다 —
  `EffectSpec.effect_types`(Lua 플래그)와
  `StructuredRules.effect_types`(**공식 5종**).
- 새 필드는 만들지 않았다.

---

## 11. `EVENT_FREE_CHAIN` 과의 분리 — §12

3-F-25 의 판정(**C. LUA_INTERNAL_TAG**)을 **유지한다.** 이 Phase 는 둘 사이에
semantic mapping 을 **만들지 않았다.**

근거 — **양방향 반례가 둘 다 많다**:

| 방향 | 반례 블록 수 |
|---|---|
| `QUICK_O` 인데 `code != EVENT_FREE_CHAIN` | **600+** (예: 머티리얼 팔코 `1287123` → `EVENT_CHAINING`) |
| `code == EVENT_FREE_CHAIN` 인데 `QUICK_O` 아님 | **3,000+** (대부분 `ACTIVATE`) |

그리고 **서로 다른 칸**이다 — 하나는 `effect_types`(`SetType`), 하나는
`code`(`SetCode`). 사양서가 경고한 혼동(`SetCode(EVENT_*)` ↔ `effect_types`)을
이 Phase 는 구조적으로 분리해 측정했다.

> 같은 카드에서 자주 함께 나타나는 것은 사실이지만, 그것만으로 인과관계나
> 동의어 관계를 만들지 않는다.

---

## 12. `legal_actions` / `EffectActivator` / Chain 영향 — §13

| 대상 | 판정 | 근거 |
|---|---|---|
| `Duel.legal_actions()` | **DOES NOT READ** | 본문 + 후보 생성기 4개 전부 `effect_types`·`QUICK_O` 0회 |
| `Duel.apply()` · `_apply_activation` | **DOES NOT READ** | 0회 |
| `EffectActivator` | **DOES NOT READ** | 0회 · `EffectSpec` 도 import 안 함 |
| `ChainLink` | **DOES NOT READ** | 6칸에 없음 (단 `effect_ref` 는 **있다**) |
| `ChainResolver` (`engine/chain.py`) | **DOES NOT READ** | 모듈 전체 0회 |
| `TriggerCandidate` 생성 | **DOES NOT READ** | 10칸에 없음 · `engine/trigger.py` 0회 |
| activation timing | **DOES NOT READ** | §8 A |

### 🔴 "미지원" 과 "버그" 의 구분

**미지원이다.** 버그가 아니다.

- 모듈이 `UNKNOWN` 을 **명시적으로 선택**하고 그 사유를 이름으로 지목한다
  (`MONSTER_CLASSIFICATION_MISSING`).
- `UNKNOWN` 은 **후보가 되지 않는다** — `legal_actions` 의 docstring 이
  *"`UNKNOWN` 은 후보가 아니다"* 라고 적는다. 그래서 모르는 것이 합법으로
  새지 않는다.
- 실제 주행으로 확인했다 — `QUICK_O` 카드가 든 덱도 정상적으로 돌고
  `activate_effect` 가 받아들여진다.

단, **파서 누적 결함(§5)은 다른 문제다.** 그것은 "읽지 않는 데이터"가 아니라
**잘못된 데이터**이고, 지금은 engine 이 읽지 않아 동작에 닿지 않지만 읽기
시작하면 78블록에서 틀린 값을 준다. 🔴 **배선 전에 먼저 고쳐야 한다.**

---

## 13. AI / Search 영향 — §14

| 대상 | 판정 |
|---|---|
| Search candidate generation (`agent/search.py` · `simulation.py`) | **DOES NOT READ** (`.script` 접근도 0) |
| `RuleBasedPolicy` (`agent/policy.py`) | **DOES NOT READ** |
| Search evaluation (`agent/evaluation.py`) | **DOES NOT READ** |
| 휴리스틱 (`agent/heuristic.py`) | **DOES NOT READ** |
| `legal_actions` | **DOES NOT READ** (§12) |
| `GameStateView` / `CardDefinitionView` | 🔴 **칸 자체가 없다** — AI 는 **볼 수조차 없다** |

AI 가 `QUICK_O` 를 보고 행동을 발명할 구조는 **없다**. 관측에 그 값이
존재하지 않기 때문이다. **AI/Search 변경 0.**

---

## 14. 실제 카드 8장 이상으로 경계 검증 — §9

| 카드 | Lua type | 현재 엔진 분류 | 공식 분류 | timing 결과 | 불일치 |
|---|---|---|---|---|---|
| 허구의 제너레이드 우트가르자 `744887` | `QUICK_O` | 분류 **없음** | UNKNOWN (카드별 자료 없음) | `UNKNOWN` | — (둘 다 모름) |
| 플레이트 크래셔 `114932` | `IGNITION` | 분류 **없음** | UNKNOWN | `UNKNOWN` | — |
| 화령사 히타 `759393` | `SINGLE+FLIP` | 분류 **없음** | UNKNOWN | `UNKNOWN` | — |
| 코아키메일 테스트베드 `176392` | `CONTINUOUS+FIELD` / `FIELD+TRIGGER_O` | 분류 **없음** | UNKNOWN | `UNKNOWN` | — |
| 🔴 매그넘 더 릴리버 `43227` | `IGNITION` / `QUICK_O` (**두 블록**) | 분류 **없음** | 효과마다 다름 | `UNKNOWN` | 🔴 **카드 단위 답이 없다** |
| 🔴 라뷰린스 쿠클락 `2511` | `QUICK_O` / `FIELD+TRIGGER_O` | 분류 **없음** | 효과마다 다름 | `UNKNOWN` | 🔴 **같음** |
| 🔴 오르페골 클리막스 `703897` | `ACTIVATE` / `QUICK_O` / `FIELD` | 카운터 함정 | 공식 **SS 3** | **스펠 스피드 3** | 🔴 `QUICK_O` 인데 3 |
| 🔴 비의 천후모양 `27561302` | `ACTIVATE` / `QUICK_O` / `FIELD+GRANT` | 지속 마법 | 공식 **SS 1** | **스펠 스피드 1** | 🔴 `QUICK_O` 인데 1 |
| 빅 실드 가드너 `65240384` | `SINGLE+CONTINUOUS` / **`QUICK_F`** | 분류 **없음** | UNKNOWN | `UNKNOWN` | `QUICK_O` 없이 "quick" |
| 🔴 유언장 `85602018`(3-F-25) · `c324483` | `IGNITION`→Clone→`QUICK_O` | — | — | — | 🔴 **파서 artifact** |

**읽는 법**: 몬스터 줄의 "불일치 — 둘 다 모름" 은 **엔진이 틀렸다는 뜻이
아니다.** 공식 카드별 분류 자료가 저장소에 없으므로 대조할 기준 자체가 없다.
실제 불일치는 **비몬스터 두 줄**(`QUICK_O` 인데 공식 SS 3 과 1)과 **혼재 몬스터
두 줄**(카드 단위 답이 없음), 그리고 **파서 artifact** 다.

---

## 15. 최종 `QUICK_O` 판정

> ## **C. DATA_CLASSIFICATION_ONLY**

근거는 §7 에 여섯 항목으로 적었다. 한 줄로: **공식 자료에 이름이 없고, 공식
Spell Speed 와 1:1 이 아니며(반례 29장), engine 이 소비하지 않는 — 파서가
쓰고 분석이 읽는 데이터 분류 플래그다.**

---

## 16. `MONSTER_CLASSIFICATION_MISSING` 원인 판정

> ## **B. DATA_PRESENT_BUT_UNUSED** + **C. SEMANTIC_NOT_CONFIRMED** + **D. MODEL_LAYER_SEPARATION**

- **A(MISSING_DATA) 아님** — 데이터는 1,875블록으로 실재한다.
- **E(INTENTIONAL_ENGINE_BOUNDARY) 부분만** — `UNKNOWN` 을 고른 것은 분명한
  의도이지만(모듈이 *"추측해서 1 로도 2 로도 만들지 않는다"* 라고 적는다),
  **입도 불일치는 선언된 경계가 아니라 설계의 결과**다.
- **주원인은 D** — 분류는 **효과 단위**인데 함수는 **카드 단위**다. 몬스터
  856장(10.4%)에는 카드 단위의 답이 **존재하지 않는다**.

---

## 17. production 변경 여부 — **docstring 2건** (실행 코드 0줄)

§15 가 허용한 *"명백하게 틀린 docstring 수정"* 과 *"이번 Phase 에서 확정된
사실을 기록하는 최소 문서 변경"* 에만 해당한다.

| 파일 | 고친 것 |
|---|---|
| `core/card_model.py` | `EffectSpec.effect_types` — 한 줄짜리 설명이 **누적**과 `Clone` 상속을 말하지 않았다. 축 구조(2축 · 비트) + 결함 규모(78블록 / 75스크립트 / 0.22%) + 실제 카드(`c324483`)를 적었다. `code` 는 같은 위험을 3-E-18 이 고쳤다는 대조도 적었다 |
| `engine/activation_timing.py` | 모듈 설명이 *"`EFFECT_TYPE_QUICK_O` 를 읽는 계층이 없다"* 로 끝나 **"읽기만 하면 풀린다" 로 읽혔다.** 입도 원인(856장 10.4% · 847장 63.3% · `speed_of_link` 가 `effect_ref` 를 버린다)과 공식 대응 미확정(829파일 0회 · SS 1·2·3 전부)을 적었다 |

### 금지 항목 — 하나도 하지 않았다

`QUICK_O` semantic implementation ✗ · activation_timing 변경 ✗ · Monster
classification 구현 ✗ · Spell Speed 계산 구현 ✗ · `legal_actions` 변경 ✗ ·
`EffectActivator` 변경 ✗ · Chain engine 변경 ✗ · Trigger engine 변경 ✗ ·
새 enum ✗ · 새 field ✗ · 새 abstraction ✗ · AI/Search 변경 ✗ ·
Engine V1 freeze 해제 ✗ · **파서 변경 ✗**

**증명**: 문자열 리터럴을 벗긴 AST 가 base(`adcd877`)와 **글자 그대로 같다** —
두 파일 모두. 그리고 바꾼 파일이 **정확히 그 둘**임을 함께 못 박는다
(`test_30`).

---

## 18. 테스트 결과

### 신규 36개 — `tests/test_effect_type_quick_audit.py`

| # | 무엇을 재는가 | §16 항목 |
|---|---|---|
| 01 | 🔴 이름이 `QUICK_O`(문자) · 15개가 독립 비트 | 1 |
| 02 | corpus 블록 수 (1,875 / 1,952) | 1·2 |
| 03 | 스크립트 1,712 / 카드 1,781 | 3 |
| 04 | 몬스터 분포 (1,338/8,268) | 4 |
| 05 | 🔴 몬스터 전용 아님 — 함정 430 · 마법 13 · 카운터 16 | 5 |
| 06 | `QUICK_O` + TRIGGER/FLIP/QUICK_F/CONT. = 0 | 6·8 |
| 07 | 🔴 `IGNITION`·`ACTIVATE` 공존 46건이 **파서 artifact** (78블록 규모) | 7 |
| 08 | 🔴 `FLIP` 만 TRIGGER 와 공존 (63·6) + 공식 문장 | 8·16 |
| 09 | 🔴 적용 범위 축이 완전 배타 · `TARGET`/`ACTIONS` 0블록 | — |
| 10 | 🔴 `EffectDefinition` 에 칸이 **없다** (10칸 전수) | 10 |
| 11 | activation_timing 소비 0 (AST 속성 집합) | 11 |
| 12 | 🔴 사유 문장이 **효과 단위**를 가리킨다 | 12 |
| 13 | 공식 Quick Effect = SS2 · timing 미기재 | 13 |
| 14 | 공식 Trigger Effect = SS1 | 14 |
| 15 | 공식 Ignition Effect = SS1 · 자신의 메인 페이즈 | 15 |
| 16 | 공식 Flip = Trigger 의 일부 · Continuous = 발동 없음 · **5종** | 16 |
| 17 | 🔴 `QUICK_O` 카드가 공식 SS **1·2·3 전부** | 17 |
| 18 | 🔴 `EVENT_FREE_CHAIN` 과 독립 (양방향 반례) | 18 |
| 19 | `legal_actions` 소비 0 | 19 |
| 20 | `EffectActivator` 소비 0 | 20 |
| 21 | `ChainLink`·`Chain` 소비 0 (단 `effect_ref` 는 있다) | 21 |
| 22 | `apply` 소비 0 | 22 |
| 23 | Search 소비 0 | 23 |
| 24 | AI 소비 0 · `CardDefinitionView` 에 칸 없음 | 24 |
| 25 | `TriggerCandidate` 소비 0 | 21 |
| 26 | 🔴 §10 A 반증 — 데이터는 있고 engine/agent 만 안 읽는다 | — |
| 27 | 🔴 카드의 분류가 아니다 — 순수 418장(23.5%) | — |
| 28 | 🔴 **입도 불일치** 856장(10.4%) + `speed_of_link` 가 `effect_ref` 를 버린다 | 12 |
| 29 | 🔴 공식 자료 829파일에 Lua 이름 0회 | 13~16 |
| 30 | 🔴 production 변경 = docstring 2건 (AST) | — |
| 31 | 🔴 정정 docstring 이 수치를 실제로 적는다 (문장 단위) | — |
| 32 | 🔴 `_O`/`_F` 뜻풀이는 **근거 없음** — UNKNOWN 유지 | — |
| 33 | 🔴 `effect_types` 이름 충돌 (Lua 15 vs 공식 5) | — |
| 34 | `state_hash` · RNG 불변 | 25 |
| 35 | `QUICK_O` 덱이 돌고 몬스터는 여전히 UNKNOWN | 19 |
| 36 | 검색 digest 불변 (611결정) | 25 |

실제 카드 **34장** 사용 — §4 의 표 그대로.

**skip 추가 0** — `test_30` 은 commit 전에도 base 와 비교해 skip 하지 않는다.

### 🔴 기존 테스트 2개가 깨졌다 — 삭제·skip·약화 없이 고쳤다

첫 전체 회귀에서 **4,726 passed / 2 failed** 가 나왔다. 둘 다 **내 docstring
변경 때문**이다. 사용자 규칙에 따라 **왜 기존 테스트가 잘못된 가정을 갖고
있었는지** 적는다. 기존 commit 은 rewrite 하지 않았고, 수정은 별도 commit
(`Phase 3-F-26: fix two audit tests broken by the docstring change`)으로 남겼다.

#### ① `tests/test_event_free_chain_semantic_audit.py::test_30` (3-F-25 작)

**틀린 가정: "`HEAD` 가 내 Phase 의 끝이다."**

```python
base = f"{added[-1]}^"        # 내 Phase 의 직전
head = "HEAD"                 # 🔴 "지금"
changed = git("diff", "--name-only", base, head, ...)
assert set(changed) <= {"core/card_model.py", "analysis/effect_model.py"}
```

끝점을 `HEAD` 로 두면 **뒤에 오는 Phase 의 변경이 전부 섞여** 들어온다. 이
Phase 가 `engine/activation_timing.py` 의 docstring 을 고치자 그 파일이
`changed` 에 끼어들어 깨졌다.

*"내 Phase 가 무엇을 바꿨는가"* 를 묻는 테스트의 끝점은 **내 commit** 이다.
3-F-24 의 `test_25` 는 처음부터 `git show --stat <그 commit>` 으로 **그
commit 하나만** 봤다 — 3-F-25 를 쓸 때 내가 그 방식을 `base..HEAD` 로 바꾸면서
결함을 넣었다.

**고친 방법**: 끝점을 `added[-1]`(그 Phase 의 commit)로 바꿨다. 단정 강도는
그대로다 — `⊆ 두 파일` · `len == 2` · 문자열 제거 AST 동일.

**같은 결함이 이 Phase 의 `test_30` 에도 있었다.** 함께 고쳤다. 고치지
않았다면 **다음 Phase 에서 똑같이 깨졌을 것**이다.

> 🔴 정직하게 적는다 — commit 이 역사에 들어간 뒤로는 `base..tip` 범위가
> **불변**이므로 이 테스트는 "그 commit 이 rewrite 되지 않았는가" 를 지키는
> 역사 검증이 된다. Phase 진행 중(commit 전)에는 base ↔ 작업 트리를 비교하는
> **살아 있는 가드**다. 3-F-24 의 `test_25` 와 같은 성질이다.

#### ② `tests/test_trigger_pipeline_dormant_audit.py::test_25` (3-E-43 작)

**틀린 가정: "원본 줄 수가 dormant 의 증거다."**

```python
assert sizes == {..., "engine/activation_timing.py": 541}
```

**줄 수는 주석과 코드를 구분하지 못한다.** 그래서 docstring 만 고친 Phase 가
올 때마다 숫자를 갱신해야 했고 — 그 테스트의 docstring 자체가 **3-E-45 ·
3-F-11 · 3-F-14** 세 번의 갱신을 기록하고 있다 — 갱신은 *"코드가 그대로인가"* 를
**증명하지 않는다.**

**고친 방법**: 약화하지 않고 **보강**했다.

1. `541` → `570` 으로 갱신하고 사유를 docstring 에 적었다 (그 파일의 기존
   관례와 같다).
2. 🔴 **문자열 리터럴을 벗긴 줄 수 6개를 함께 못 박았다** —
   `trigger.py` 735 · `trigger_chain.py` 257 · `trigger_order.py` 194 ·
   `timing.py` 194 · `event_pipeline.py` 227 · `activation_timing.py` 227.
   이 숫자는 **docstring 을 고쳐도 움직이지 않고 실행 코드를 고치면
   움직인다.** 원래의 원본 줄 수 핀은 **그대로 남겼다.**

측정으로 확인했다 — 여섯 모듈 **전부** base(`adcd877`) 대비 문자열 제거 AST 가
**동일**하다. 즉 트리거 파이프라인은 여전히 dormant 다.

### 전체 회귀

```
$ python -m pytest -p no:randomly -q
4728 passed, 4 skipped in 598.49s (0:09:58)
```

| 항목 | 값 |
|---|---|
| Phase 3-F-25 종료 시점 baseline | 4,692 passed |
| 이번 Phase 신규 테스트 | **+36** |
| 합계 (측정값) | **4,728 passed** |
| 실패 | **0** |
| skip | **4** — 3-F-25 와 **동일**. 이번 Phase 가 추가한 skip 은 0건 |

36 = 4,728 − 4,692 가 정확히 맞고 skip 수가 그대로다.

> 🔴 **첫 회귀는 2건이 실패했다** (4,726 passed / 2 failed). 둘 다 기존 감사
> 테스트였고, 아래 절에 원인과 수정을 적었다. 위 숫자는 **수정 후 재실행**
> 결과다. 첫 결과를 숨기지 않는다.

### 🔴 고의 위반 주입 13건 — 전부 검출

9개 파일을 md5 로 백업하고 하나씩 심었다 되돌렸다. 각 주입은 **먼저 `import`
로 유효성을 확인**했다 — 모듈을 깨뜨리는 주입은 "테스트가 약하다" 의 증거가
아니라 **나쁜 probe** 다.

| # | 심은 위반 | 걸린 테스트 |
|---|---|---|
| 1 | `EffectDefinition` 에 `effect_types` 칸을 더한다 | `test_10` `test_26` `test_30` |
| 2 | `classify_spell_speed` 가 `definition.effect_types` 를 읽는다 (죽은 코드로) | `test_11` `test_26` `test_30` |
| 3 | `CardDefinitionView` 에 `effect_types` 를 싣는다 | `test_10` `test_24` `test_26` `test_30` |
| 4 | engine 코드가 `QUICK_O` 라는 이름을 쓴다 | `test_26` `test_30` `test_32` |
| 5 | AI(`heuristic.py`)가 `card.script.effect_types` 를 본다 | `test_24` `test_26` `test_30` |
| 6 | `ChainLink` 가 `effect_types` 를 들고 다닌다 | `test_21` `test_26` `test_30` |
| 7 | `speed_of_link` 가 `effect_ref` 를 쓴다 | `test_28` `test_30` |
| 8 | 🔴 파서가 `SetType` 을 교체로 바꾼다 (결함을 고쳐 버린다) | `test_07` `test_30` |
| 9 | 파서가 `QUICK_O` 를 흘린다 | `test_02` `test_03` `test_07` `test_30` |
| 10 | `card_model` 정정 docstring 을 되돌린다 | `test_31` |
| 11 | `activation_timing` 정정 docstring 을 되돌린다 | `test_31` |
| 12 | `MONSTER_CLASSIFICATION_MISSING` 을 카드 단위 문장으로 바꾼다 | `test_12` |
| 13 | `legal_actions` **본문**이 `effect_types` 를 읽는다 | `test_19` `test_26` `test_30` |

마지막 복원을 **md5 로 확인**했다 (9/9 OK).

#### 🔴 주입 13 — 내 probe 가 과녁을 빗났다

처음에는 `Duel` 에 **형제 메서드**(`_peek_types`)를 심었다. `test_19` 는
`legal_actions` 와 후보 생성기의 **본문**만 보므로 걸리지 않았다 — 그리고
그것이 맞다. 호출되지 않는 형제 메서드는 `legal_actions` 에 영향을 주지
않는다. `legal_actions` **본문 안**으로 옮겨 심으니 `test_19` 가 잡았다.

> **"주입이 걸리지 않았다" 를 "테스트가 약하다" 로 읽지 않는다.** 먼저 probe
> 가 주장한 일을 실제로 했는지 확인한다 (3-F-25 에서 배운 것).

#### 🔴 나쁜 probe 를 `import` 단계에서 걸러냈다

`EffectDefinition`/`ChainLink` 에 기본값 필드를 **맨 위**에 넣어 dataclass 필드
순서를 깨뜨린 것, `@dataclass` 와 `class Duel:` **사이**에 문장을 끼워
`SyntaxError` 를 낸 것, 앵커가 2회 이상 걸린 것 — 모두 앵커를 고쳤다.

---

## 19. 불변 조건 검증 — §17

| 항목 | 결과 | 근거 |
|---|---|---|
| `state_hash` 불변 | ✅ | `test_34` — 같은 seed 동일, 다른 seed 상이 |
| RNG 불변 | ✅ | `test_34` — 뽑은 값 8개 비교 |
| digest 불변 | ✅ | `test_36` — 6판 **611결정**, 기존 pin 7개를 AST 로 대조 |
| hidden-information 불변 | ✅ | `test_24` — `CardDefinitionView` 26칸 그대로 |
| `GameStateView` 불변 | ✅ | 변경 0 (`test_30`) |
| Search 불변 | ✅ | `test_23` `test_36` |
| AI 불변 | ✅ | `test_24` · `agent/` 변경 0 |
| Engine V1 freeze | ⚠️ | `engine/` 에서 바꾼 것은 **`activation_timing.py` 의 모듈 docstring 뿐**이고 문자열 제거 AST 가 동일하다. 실행 코드는 0줄 |
| 기존 검색 결과 불변 | ✅ | 실행 코드 0줄 변경 |
| 기존 테스트 baseline + 신규 | ✅ | §18 |
| 기존 테스트 삭제 | **0** | — |
| skip 추가 | **0** | `test_30` 이 fallback 으로 skip 회피 |
| assertion 약화 | **0** | 🔴 기존 테스트 **2개를 고쳤다** — §18 에 각각의 잘못된 가정을 적었다. `test_25` 는 핀 6개를 **더해** 보강했고 기존 핀은 남겼다 |

---

## 20. 남은 구조적 위험

| 등급 | 내용 | 근거 |
|---|---|---|
| 🔴 | **파서가 `effect_types` 를 누적한다.** 78블록(0.22%)이 **어떤 카드도 적지 않은 조합**을 주장한다. 지금은 engine 이 읽지 않아 동작에 닿지 않지만, 배선하는 순간 틀린 값이 들어간다. `code` 는 3-E-18 이 고쳤고 이 칸은 안 고쳤다 | §5 |
| 🔴 | **입도 불일치.** `classify_spell_speed` 는 카드 단위, 공식 분류는 효과 단위. 몬스터 856장(10.4%)에 카드 단위 답이 없다. `effect_types` 를 싣기만 해도 풀리지 않는다 | §9 |
| 🔴 | **공식 카드별 효과 분류 자료가 없다.** 그래서 `QUICK_O` 의 공식 대응을 검증할 기준이 없다. 3-F-25 가 공식 DB 전문검색이 작동하지 않음을 확인했다 | §6·§7 |
| 🟠 | **`effect_types` 이름이 둘** (Lua 15플래그 vs 공식 5종). 부분 문자열 측정이 조용히 섞인다 | §3 |
| 🟠 | **`_O`/`_F` 뜻풀이가 근거 없이 보고서에 적혀 있다** (3-E-31). 엔진의 `MANDATORY`/`OPTIONAL` 축과 이름이 비슷해 잇고 싶어진다 — 잇는 근거는 없다 | §6 |
| 🟡 | **`speed_of_link` 가 `effect_ref` 를 버린다.** 효과 단위 정보가 있는 유일한 자리에서 버려진다 | §8 |
| 🟠 | **감사 테스트가 서로를 깨뜨린다.** 이 Phase 가 docstring 두 개를 고치자 앞선 Phase 의 테스트 2개가 깨졌다 — 끝점을 `HEAD` 로 둔 것과 주석 포함 줄 수를 핀으로 쓴 것. 둘 다 고쳤고 **같은 유형을 전수 조사했다**: 원본 줄 수를 핀으로 쓰는 테스트는 `test_trigger_pipeline_dormant_audit.py` **하나뿐**이고(이번에 보강), 끝점을 `HEAD` 로 쓰는 테스트는 3-F-25 · 3-F-26 **둘뿐**이었다(둘 다 고침). 다만 **다음 Phase 가 production docstring 을 고치면 또 다른 핀을 건드릴 수 있으므로**, 회귀를 반드시 끝까지 보고 2건이 아닌지 확인해야 한다 | §18 |
| 🟢 | `effect_types` 가 engine 에 없는 것은 **미지원 경계**이고 `UNKNOWN` 이 후보로 새지 않는다 | §12 |

---

## 21. 다음 Phase 후보 (최대 1개)

> **파서 `SetType` 누적 결함 감사 및 수정 — `effect_types` 의 `Clone` 노후값
> (조사 + 최소 수정)**

이유는 이 Phase 의 측정에서 바로 따라온다.

- 🔴 **이것만이 "틀린 데이터" 다.** 이 Phase 가 찾은 나머지는 전부 *미지원
  경계*(읽지 않음)이거나 *미확정 의미*(UNKNOWN)인데, 누적 결함은 **78블록에서
  실제로 거짓을 주장**한다.
- **고쳐야 할 순서가 정해져 있다.** §9 의 입도 문제를 풀려면 언젠가
  `effect_types` 를 engine 쪽으로 옮겨야 하고, **옮기기 전에 고쳐야 한다** —
  틀린 값을 배선하면 틀린 규칙이 된다.
- **선례가 저장소 안에 있다.** `code` 의 같은 결함을 Phase 3-E-18 이
  주석까지 달아 고쳐 놓았다. 그 수정의 모양을 그대로 따를 수 있는지
  확인하는 것이 조사 범위다.
- **규모가 작고 경계가 분명하다** — 78블록 / 75스크립트 / 1개 분기.
  영향받는 플래그도 측정돼 있다(`IGNITION` 43 · `SINGLE` 15 · `FIELD` 11 ·
  `ACTIVATE` 8 · `TRIGGER_O` 1).
- **Engine V1 freeze 를 건드리지 않는다.** `sources/lua_loader.py` 는 파서
  계층이고 engine 이 그 값을 읽지 않으므로 duel 동작은 바뀔 수 없다. 다만
  **검색(`core/card_search.py`)과 분석 출력은 바뀔 수 있으므로** 그 범위를
  먼저 재야 한다 — 그것이 조사 부분이다.

**이번 Phase 에서 고치지 않은 이유**: §15 가 파서 변경을 금지했고, 무엇이
올바른 등재 규칙인지 정해지기 전에 바꾸면 무엇을 잃는지 알 수 없다.
