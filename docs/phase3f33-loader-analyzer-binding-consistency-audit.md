# Phase 3-F-33 — loader / analyzer 바인딩 규칙 일관성 감사

**최종 판정: `MIXED_FINDINGS`**

하나로 뭉갤 수 없는 두 사실이 동시에 성립한다.

| 갈래 | 판정 | 근거 |
|---|---|---|
| **현재 코퍼스의 산출물** | **`CONFIRMED_CONSISTENT`** | `_RE_REBIND` 를 analyzer 에 넣어도 **0 스크립트 / 0 블록** 변화. 최종 `CardAnalysis` 지문까지 동일 |
| **규칙 자체** | **`CONFIRMED_BINDING_INCONSISTENCY`** | analyzer 에 `_RE_REBIND` 가 **없다**. §3.A 의 9가지 중 **2가지**에서 다른 결과를 **실제로 재현**했다 |

**production 코드는 변경하지 않았다** — §5 의 *"두 경로가 같은 결과를 내고
있다면 production 코드를 변경하지 않는다"* 를 따랐다. 확인된 범위와 미확인
범위를 §12 에서 나눠 적는다.

---

## 1. 실제 HEAD / base 검증

`git log` · `git show` · `git status` · `git rev-parse` 로 직접 확인했다.
**지시서의 기준과 전부 일치한다.**

| 항목 | 지시서 | 실측 | 결과 |
|---|---|---|---|
| 3-F-32 작업 commit | `81eed74` | `81eed74` *audit auxiliary effect creation and clone forms* (2 files, +73/−8) | 일치 |
| 3-F-32 테스트 commit | `b382afd` | `b382afd` *update tests for the recognized clone forms* (13 files, +1422/−124) | 일치 |
| 3-F-32 보고서 / 시작 HEAD | `2a73168` | `2a73168ed28914a31ec55b5703bd6b1818126803` (727줄) | 일치 |
| 브랜치 | `claude/pensive-goodall-te1egy` | 같음 | 일치 |
| `origin/claude/...` | — | `2a73168` — **HEAD 와 동일 (동기화됨)** | — |
| worktree | — | **clean** | — |
| 기준 전체 테스트 | 4,964 / 4 skipped / 0 failed | 같음 (3-F-32 종료 시 이 commit 에서 실측) | 일치 |

기존 commit 은 rewrite/amend 하지 않았다.

🔴 **3-F-32 의 결과를 전제로 깔지 않고 실제 HEAD 의 코드를 읽었다** (§2 지시).
그 결과 아래 §2·§3 의 구조 차이 5개를 새로 확정했다.

---

## 2. loader 와 analyzer 의 처리 경로

### 2.1 두 경로를 나란히

```
          c*.lua 원문
                │
      _RE_BLOCK_COMMENT.sub("")            ← 두 경로가 **똑같이** 쓴다
                │
      ┌─────────┴──────────┐
      ▼                    ▼
 lua_loader.py        effect_analyzer.py
 parse_lua_source     EffectAnalyzer._collect_handlers
      │                    │
 _RE_CREATE_EFFECT ──공유── _RE_CREATE_EFFECT   (import)
 _RE_CLONE_EFFECT  ──공유── _RE_CLONE_EFFECT    (import)
 _clone_source     ──공유── _clone_source       (import)
 _is_card_effect   ──공유── _is_card_effect     (import)
      │                    │
 🔴 _RE_REBIND          🔴 **없다**
      │                    │
 _RE_SETTER             _RE_SETTER
  Set(\w+) → 7개 소비     Set(Cost|Condition|Target|Operation)
      │                    │
 sort (pos, _EVENT_ORDER)  sort (pos)
      │                    │
 bindings: var→EffectSpec  bindings: var→handlers dict
      │                    │
 info.effects[i]           order[i]
      │                    │
      └──────── i 가 같아야 한다 ────────┘
                  = EffectRef(card_id, i)
```

### 2.2 구조 차이 5개 (실제 코드에서 확인)

| # | 차이 | loader | analyzer | 측정된 영향 |
|---|---|---|---|---|
| **D1** | `_RE_REBIND` | 적용 | 🔴 **없다** | **0** (§5) |
| **D2** | 이벤트 정렬 | `(pos, _EVENT_ORDER[kind])` | `pos` 만 (stable) | **0** — 아래 |
| **D3** | 소비 설정자 | 값 7개 | 함수 슬롯 4개 | 교집합 **없음** |
| **D4** | 블록 탐지 | 공유 (import) | 공유 (import) | 없음 — 3-F-28 이 통일 |
| **D5** | 전처리 | `_RE_BLOCK_COMMENT` | 같음 | 없음 |

🔴 **D2 는 지금 한 번도 발동하지 않는다.** 같은 byte offset 에 두 종류의
이벤트가 겹치는 자리가 코퍼스 전체에 **0건**이다. `_EVENT_ORDER` 는 3-F-31 이
넣은 **방어적 장치**이고, analyzer 의 단순 정렬이 결과상 같다. (장치는 유지하는
것이 맞다 — 0 은 "지금 없다" 이고 "생길 수 없다" 가 아니다.)

🔴 **D3 의 두 집합은 완전히 분리되어 있다.**

| 경로 | 소비하는 설정자 | 호출 수 |
|---|---|---:|
| loader | `Type` · `Code` · `Range` · `TargetRange` · `Category` · `Property` · `CountLimit` | 121,636 |
| analyzer | `Cost` · `Condition` · `Target` · `Operation` | 54,284 |
| 교집합 | **없음** | — |

(`SetTargetRange(` 가 analyzer 의 `Set(Target)` 에 걸리지 않는 것도 확인했다 —
`Target` 뒤에 `(` 가 바로 와야 한다.) 이 분리 덕분에 **두 경로가 갈릴 수 있는
자리가 하나로 좁혀진다**: "Effect 변수가 풀린 뒤 **네 핸들러 설정자**가 오는
자리".

### 2.3 analyzer 산출물은 디스크에 캐시되지 않는다

`EffectAnalyzer._cache` 는 **인스턴스 안의 메모리 dict** 하나다. 디스크 캐시는
loader 쪽(`LuaScriptSource.load_cached`) 에만 있다. 따라서 **analyzer 를 고쳐도
`_signature()` 를 올릴 필요가 없다** (§5 의 "캐시 서명 갱신이 실제로 필요한
경우" → **해당 없음**). 이 Phase 는 `v9` 를 그대로 둔다.

---

## 3. `_RE_REBIND` 의 실제 적용 위치

| 위치 | 적용 | 비고 |
|---|---|---|
| `sources/lua_loader.py` 정의 | 🟢 있다 | 127행 |
| `parse_lua_source` 의 이벤트 수집 | 🟢 적용 | 407행 — `events.append((m.start(), "rebind", ...))` |
| `parse_lua_source` 의 재생 루프 | 🟢 적용 | `bindings.pop` + `inherited.pop` |
| `analysis/effect_analyzer.py` import 목록 | 🔴 **없다** | `_clone_source`·`_RE_BLOCK_COMMENT`·`_RE_CLONE_EFFECT`·`_RE_CREATE_EFFECT`·`_extract_call_args`·`_is_card_effect` 는 import 한다 |
| `_collect_handlers` | 🔴 **없다** | 바인딩을 **한 번도 풀지 않는다** |
| `_analyze_card` | — | 바인딩을 다루지 않는다. `entries[position]` 으로 짝만 짓는다 |

🔴 즉 **`_RE_REBIND` 가 적용되는 지점(loader)과 Effect 핸들러를 수집하는
지점(analyzer)이 서로 다른 모듈에 있고, 한쪽에만 규칙이 있다.** 이것이 §0
질문 2 의 답이다.

---

## 4. corpus 전수 조사 결과

실제 HEAD 에서 다시 산출했다. 기준값과 일치한다.

| 항목 | 값 |
|---|---:|
| Lua 스크립트 | **12,702** |
| loader 블록 | **34,684** |
| analyzer `order` 항목 | **34,684** |
| 🔴 길이가 어긋난 스크립트 | **0** |
| `cards.cdb` 에 붙은 카드 / 블록 | 12,687 / 34,635 |

### 4.1 §4 의 6개 범주

| # | 범주 | 수 |
|---|---|---:|
| 1 | `_RE_REBIND` 에 일치하는 **원문** 수 | **67,226** |
| 2 | 그 원문이 있는 **고유 스크립트** 수 | **12,701** / 12,702 |
| — | 그중 `local` 선언 | 63,753 |
| — | 🔴 **이름 단위** unbind 이벤트 (다중 대입 때문에 더 많다) | **81,688** |
| 3 | 🔴 실제 **Effect 재바인딩**으로 확인된 사례 | **30** |
| 4 | Effect 와 무관한 일반 변수 재바인딩 | **81,658** |
| 5 | 정규식만으로 의미를 확정할 수 없는 사례 | **30** (= 3번과 같은 집합, §4.3) |
| 6 | 🔴 **loader 와 analyzer 의 결과가 다른 사례** | **0** |

🔴 **정규식 매치 수(67,226)를 Effect 재바인딩 수(30)로 쓰면 2,240배 틀린다.**
지시서 §4 가 금지한 바로 그 혼동이다. 두 단계로 갈린다.

1. 매치 67,226 → 이름 81,688 (한 매치가 `local a,b,c=…` 처럼 여러 이름을 푼다)
2. 이름 81,688 → Effect 변수 **30** (나머지 81,658 은 `g`·`tc`·`sg` 같은
   Group/Card 변수이거나 애초에 묶여 있지 않은 이름이다)

### 4.2 Effect 변수를 푸는 30건의 RHS 전부

| RHS | 건수 |
|---|---:|
| `aux.createContinuousLizardCheck(...)` | 9 |
| `table.unpack(...)` | 5 |
| `e:GetLabelObject(...)` | 5 |
| `reglevel(...)` | 3 |
| `Duel.IsPlayerAffectedByEffect(...)` | 2 |
| `aux.AddNormalSummonProcedure(...)` | 2 |
| `s.tempregister(...)` | 2 |
| `aux.CreateWitchcrafterReplace(...)` | 1 |
| `e1:GetLabelObject(...)` | 1 |
| **합계** | **30** |

🔴 **30건 전부가 보조 함수 호출이거나 런타임 조회다.** Effect → Effect
alias(`e2=e1`)는 **하나도 없다** — 3-F-31 이 bare-var 대입 579건을 전수 조사해
전부 `nil`/`true`/`false`/상수임을 확인한 결과와 일치한다. "변수 이름이 같다는
이유만으로 객체 정체성이 같다고 판단하지 않는다"(§4) 를 지킬 자리가 애초에
없다.

### 4.3 왜 결과 차이가 0 인가 — 갈릴 수 있는 두 자리를 직접 셌다

| 자리 | 수 |
|---|---:|
| (a) 풀린 변수에 analyzer 의 **네 핸들러 설정자**가 오는 자리 | **0** |
| (b) 풀린 변수를 **부모로 쓰는 `Clone`** | **0** |

이 둘이 D1 이 결과에 영향을 줄 수 있는 **유일한** 경로다. 둘 다 0 이므로
결과 차이가 0 이다. 🔴 **운이 아니라 구조적 이유가 있다**: 30건의 재바인딩은
전부 보조 함수 반환값을 받는 자리이고, 그 자리의 스크립트는 그 변수에
`SetCost`/`SetCondition`/`SetTarget`/`SetOperation` 을 걸지 않고
`RegisterEffect` 로 바로 넘긴다. 다만 그것이 **보장**은 아니다 — §7 이 그
반례를 만들어 보인다.

---

## 5. 동일 Lua 원문의 양쪽 처리 결과 비교

### 5.1 계측 신뢰성을 먼저 확보했다

🔴 production 을 **재구현하지 않았다.** `parse_lua_source` 와
`EffectAnalyzer._collect_handlers` 를 **그대로 호출**한다. 스위치를 켠 변형만
따로 두고, **스위치를 끈 변형이 production 과 전수로 같은지 먼저 확인했다**
(0 스크립트 차이 — 새 테스트 `test_01`). 3-F-28 과 3-F-32 가 각각 한 번씩
"복제본의 버그를 측정" 했으므로 그 검증을 통과하지 못하는 계측은 쓰지 않는다.

### 5.2 두 스위치를 **따로** 켜서 영향을 분리

한꺼번에 켜서 0 이 나오면 서로 상쇄했을 수도 있으므로 분리해 셌다.

| 조합 | 다른 스크립트 | 다른 블록 | `order` 합 |
|---|---:|---:|---:|
| 기준 (production) | 0 | 0 | 34,684 |
| **D1 만** (`_RE_REBIND` 추가) | **0** | **0** | 34,684 |
| **D2 만** (정렬 맞춤) | **0** | **0** | 34,684 |
| **D1 + D2** (loader 와 동일) | **0** | **0** | 34,684 |

### 5.3 최종 산출물까지 비교 — `CardAnalysis` 지문

`_collect_handlers` 가 같아도 그 아래에서 갈릴 수 있으므로 **끝까지** 봤다.
`EffectAnalyzer._collect_handlers` 를 변형으로 바꿔 끼우고 12,687장 전부를
다시 분석했다.

| 항목 | production | +rebind | 결과 |
|---|---:|---:|---|
| `CardAnalysis` SHA-256 지문 | `a68ac9ead874…` | `a68ac9ead874…` | 🟢 **동일** |
| `initial_effect` 등록 효과 | 26,352 | 26,352 | 🟢 |
| 해결 중 생성 효과 | 8,283 | 8,283 | 🟢 |
| 조건 있는 블록 | 12,438 | 12,438 | 🟢 |
| 비용 있는 블록 | 5,007 | 5,007 | 🟢 |
| 대상 지정 블록 | 5,516 | 5,516 | 🟢 |
| 액션 합 | 18,280 | 18,280 | 🟢 |
| 카테고리 합 | 20,484 | 20,484 | 🟢 |
| **달라진 카드** | — | — | 🟢 **0** |
| `EffectRef` 연결 불일치 | — | — | 🟢 **0** |

🔴 **§0 질문 1 의 답: 달라지지 않는다.** Effect 수 · `ordinal` · 분석 결과
전부 동일하다.

### 5.4 §3.A 의 9가지 상황 — 양쪽 경로에 실제로 넣었다

| # | 상황 | 블록 | production | +rebind | 판정 |
|---|---|---:|---|---|---|
| 1 | 기존 변수에 새 Effect 대입 | 2 | `T` \| `T` | `T` \| `T` | 🟢 같다 |
| 2 | Clone 을 새 변수에 대입 | 2 | `C` \| `CO` | `C` \| `CO` | 🟢 같다 |
| 3 | 같은 변수에 Clone 결과 재대입 | 2 | `C` \| `CO` | `C` \| `CO` | 🟢 같다 |
| **4** | **기존 Effect 변수에 일반 값 대입** | 1 | `OT` | `T` | 🔴 **다르다** |
| 5 | 지역/전역 변수 재바인딩 | 1 | `O` | `O` | 🟢 같다 |
| 6 | 같은 이름이 서로 다른 scope | 2 | `T` \| `O` | `T` \| `O` | 🟢 같다 |
| 7 | setter 가 기존 Effect 를 수정 | 1 | `T` | `T` | 🟢 같다 |
| 8 | 보조 함수가 Effect 를 반환 | 0 | — | — | 🟢 같다 |
| **9** | **파서가 대입을 인식하지 못함** | 1 | `COT` | `C` | 🔴 **다르다** |

**7 / 9 는 같고, 2 / 9 는 다르다.** 다른 둘은 **같은 원인**이다 — "파서가
인식하지 못하는 대입". 3번(`e1=e1:Clone()`)이 같은 것이 중요하다: 그것은
파서가 **아는** 형태라 재바인딩이 아니고, 3-F-32 가 넓힌 세 형태가 전부
`_RE_REBIND` 의 선읽기에서 제외되어 있기 때문이다.

---

## 6. Effect 개수 및 ordinal 차이

| 비교 | 결과 |
|---|---|
| loader 블록 수 vs analyzer `order` 길이 | 🟢 **전수 일치** (34,684 = 34,684, 어긋난 스크립트 0) |
| 블록 **순서** (원문 등장 순서) | 🟢 전수 일치 — 불일치 0 |
| `ordinal` append-only | 🟢 전수 성립 — 자리가 움직인 스크립트 0 |
| `EffectRef(card_id, i).resolve(card) is card.script.effects[i]` | 🟢 전수 성립 |
| 재바인딩 **이전** Effect 의 잔존 | 🟢 두 경로 모두 블록은 남긴다 (append-only). 🔴 **핸들러만** analyzer 에서 계속 쌓일 수 있다 |
| 새 Effect 의 누락 | 🟢 **0** — 블록 탐지는 공유다 |

🔴 **`ordinal` 은 영향받을 수 없다**: 블록은 `_RE_CREATE_EFFECT` ·
`_RE_CLONE_EFFECT` · `_is_card_effect` 로만 만들어지고, 그 셋은 **두 경로가
import 로 공유**한다 (3-F-28 이 통일). `_RE_REBIND` 는 바인딩만 풀고 블록을
만들거나 지우지 않는다. 그래서 D1 은 **핸들러 귀속**에만 닿을 수 있다.

---

## 7. 대표 재현 사례

🔴 **차이는 구조적으로 실재한다.** 0 은 "이 코퍼스에 없다" 이고 "생길 수
없다" 가 아니다. 그 둘은 전혀 다른 결론이므로 최소 재현을 만들어 증명했다.

### 7.1 사례 B — 인식 못 한 대입 뒤의 핸들러 (§3.A 9번)

```lua
function s.initial_effect(c)
    local e1=Effect.CreateEffect(c)
    e1:SetTarget(s.tg)
    c:RegisterEffect(e1)
    e1=e:GetLabelObject()      -- loader 는 여기서 e1 을 푼다
    e1:SetOperation(s.op)      -- 🔴 이 줄에서 갈린다
end
```

| | 결과 |
|---|---|
| loader | `e1` 바인딩이 풀려 **설정자를 버린다** |
| analyzer (production) | ord0 의 핸들러 = `{Target: s.tg, **Operation: s.op**}` |
| analyzer (+rebind) | ord0 의 핸들러 = `{Target: s.tg}` |

🔴 **Lua 원문에서 ord0 블록은 `SetOperation` 을 갖지 않는다.** production
analyzer 는 **없는 값을 만든다.** 3-F-31 이 loader 에서 바로 이것을 고쳤고,
그때 세운 원칙이 *"틀린 값을 만드는 것보다 모른다고 말하는 것이 맞다"* 였다.

### 7.2 사례 C — 풀린 변수를 부모로 쓰는 `Clone` (두 경로가 **정면으로 모순**)

```lua
    local e1=Effect.CreateEffect(c)
    e1:SetTarget(s.tg)
    e1:SetOperation(s.op)
    c:RegisterEffect(e1)
    e1=e:GetLabelObject()      -- loader 는 e1 을 푼다
    local e2=e1:Clone()        -- 🔴 부모가 누구인가?
    c:RegisterEffect(e2)
```

| 관점 | ord1(`e2`) 에 대한 주장 |
|---|---|
| loader 의 `EffectSpec` | `cloned_from='e1'` 이지만 **여섯 칸을 하나도 물려받지 않았다** (`parent=None`) |
| analyzer (production) | 핸들러 `{Target: s.tg, Operation: s.op}` 를 **물려받았다** |
| analyzer (+rebind) | 핸들러 `{}` — 물려받지 않았다 |

🔴 같은 블록에 대해 **"물려받은 것이 없다"(loader)** 와 **"둘을
물려받았다"(analyzer)** 가 동시에 주장된다. 이것이 이 Phase 가 찾은 가장
선명한 불일치다.

### 7.3 사례 E — 다중 대입이 Effect 이름 **둘**을 푼다

```lua
    local e1,e2=Spirit.AddProcedure(c,true)
    e1:SetTarget(s.tg)
    e2:SetOperation(s.op)
```

production analyzer 는 **두 블록 모두** 엉뚱한 핸들러를 얻는다
(ord0 `{Cost, Target}` · ord1 `{Cost, Operation}`). +rebind 는 둘 다 `{Cost}` 다.

### 7.4 같은 결과를 내는 사례 — 왜 코퍼스가 0 인가

| 사례 | 이유 |
|---|---|
| 일반 변수 재바인딩 (`g=g:Filter(...)`) | 묶인 Effect 변수가 아니다 → 81,658건이 여기 |
| 같은 이름 다른 scope | 새 `create` 가 바인딩을 **교체**한다 (재바인딩이 아니다) |
| 전역 효과(`ge1`) 재바인딩 | 게이트가 블록 자체를 만들지 않는다 |
| `e1=e1:Clone()` | **인식되는** 대입이다 (3-F-32 가 넓힌 세 형태 전부 선읽기 제외) |
| 보조 함수 30건 | 그 변수에 **네 핸들러 설정자를 걸지 않고** `RegisterEffect` 로 바로 넘긴다 |

---

## 8. Phase 3-F-32 회귀 여부

§3.C 가 요구한 항목 전부를 다시 측정했다. **하나도 되돌아가지 않았다.**

| 보존 항목 | 결과 |
|---|---|
| `c44887817` — `e1:Clone(e1)` | 🟢 블록 5 · ord4 `code='EFFECT_CANNOT_MSET'` · `cloned_from='e1'` |
| `c4997565` — `Effect.Clone(e1)` | 🟢 블록 5 · ord3 `code='EFFECT_DISABLE_EFFECT'` · `cloned_from='e1'` |
| `c56410769` — `e2:Clone(c)` | 🟢 블록 3 · ord2 `code='EFFECT_CANNOT_ATTACK_ANNOUNCE'` · `cloned_from='e2'` |
| `c63708033` — Group clone 반례 | 🟢 블록 1 (`['e1']`), Clone 정규식 매치 0 |
| `EffectRef` append-only 설계 | 🟢 전수 성립 |
| 생성 순서에 따른 `ordinal` | 🟢 전수 불일치 0 |
| 미인식 대입을 추론하지 않는 정책 | 🟢 loader 는 계속 **버린다** |
| `UNKNOWN` 처리 | 🟢 `c52445243` 의 `SetCategory` 3건은 **계속 어느 블록에도 붙지 않는다** |
| 3-F-27 `SetType` 교체 (`c324483`) | 🟢 clone 블록이 `['QUICK_O']` — `IGNITION` 없음 |
| 코퍼스 총계 | 🟢 12,702 스크립트 / 34,684 블록 (기준과 동일) |

---

## 9. production 수정 여부와 정확한 diff

## **production 코드를 변경하지 않았다.**

### 9.1 근거

§5 는 두 조건을 적었다.

> 실제 결과 불일치가 확인된 경우에만 최소 수정한다.
> **두 경로가 같은 결과를 내고 있다면 production 코드를 변경하지 않는다.**

* 코퍼스 전수에서 두 경로는 **같은 결과를 낸다** (0/12,702 · 0/34,684 ·
  `CardAnalysis` 지문 동일). → 후자가 적용된다.
* §5 의 마지막 문장도 따랐다 — *"실제로 잘못된 결과가 재현되었다면 단순히
  UNKNOWN 으로 덮지 말고 확인된 범위와 미확인 범위를 나눠 기록한다."*
  §7 에서 **재현했고**, §12 에서 **나눠 적는다.**

### 9.2 diff

```
$ git log --format=%H --grep='^Phase 3-F-33:' | xargs -n1 git show --name-only --format=
tests/test_loader_analyzer_binding_consistency.py            (신규, 40 테스트)
docs/phase3f33-loader-analyzer-binding-consistency-audit.md  (신규, 이 보고서)
```

**`.py` production 파일 변경 0건.** 금지 경로(`.lua` · README · `engine/` ·
`agent/` · `core/` · `sources/` · `analysis/`) 변경 **0건**. 캐시 서명은
`v9` 그대로 (§2.3 — analyzer 는 디스크 캐시가 없으므로 올릴 이유가 없다).

🔴 **commit 이 셋이 아니라 둘이다.** §9.7 은 작업 · 테스트 · 보고서 commit 을
따로 만들라고 적었지만, 이 Phase 는 §5 에 따라 production 을 바꾸지 않았으므로
**작업 commit 에 담을 내용이 없다.** 빈 commit 을 만들어 세 개로 맞추는 것은
없는 작업을 있는 것처럼 보이게 하는 일이므로 하지 않았다. 조사의 산출물은
테스트 파일이고, 그것이 작업 commit 의 역할을 겸한다.

| commit | 내용 |
|---|---|
| *Phase 3-F-33: audit loader/analyzer binding rule consistency* | 신규 테스트 40개 (= 작업 + 테스트) |
| *Phase 3-F-33: document loader/analyzer binding consistency audit* | 이 보고서 |

### 9.3 다음 Phase 가 적용한다면 — 정확히 이 3줄이다

조사 결과 최소 수정의 모양까지 확정됐으므로 적어 둔다. **이 Phase 는 적용하지
않았다.**

```diff
  from sources.lua_loader import (
      _clone_source,
      _extract_call_args,
      _is_card_effect,
      _RE_BLOCK_COMMENT,
      _RE_CLONE_EFFECT,
      _RE_CREATE_EFFECT,
+     _RE_REBIND,
  )
```

```diff
      for m in _RE_SETTER.finditer(source):
          events.append(...)
+     for m in _RE_REBIND.finditer(source):
+         events.append((m.start(), "rebind", m.group(1)))
-     events.sort(key=lambda e: e[0])
+     events.sort(key=lambda e: (e[0], _EVENT_ORDER[e[1]]))
```

```diff
      for pos, kind, payload in events:
-         if kind == "create":
+         if kind == "rebind":
+             for name in payload.split(","):
+                 bindings.pop(name.strip(), None)
+         elif kind == "create":
```

측정된 코퍼스 영향: **0 스크립트 / 0 블록 / `CardAnalysis` 지문 불변.**
캐시 서명 갱신 **불필요**. 즉 적용하더라도 **데이터는 변하지 않고 계약만
일치**한다.

---

## 10. 신규 · 기존 테스트 결과

### 10.1 신규

`tests/test_loader_analyzer_binding_consistency.py` — **40개** (지시서 최소
25개). §6 의 13개 범주를 전부 덮는다.

🔴 **모든 테스트가 실제 코드 경로를 실행한다.** `parse_lua_source` 와
`EffectAnalyzer._collect_handlers` 를 그대로 호출하고, 정규식 문자열이
존재하는지만 보는 테스트로 개수를 채우지 않았다. `test_40` 하나만 import
목록을 보는데, 그것은 "지금 상태를 못 박아 다음 Phase 가 **의도적으로**
바꾸게 만드는" 목적이고 그 사실을 docstring 에 적었다.

가장 중요한 것이 **`test_01`** 이다 — 스위치를 끈 변형이 production 과 전수로
같은지 먼저 확인하고, 그것이 깨지면 아래 측정 전부가 무의미함을 명시한다.

삭제 0 · skip 추가 0 · assertion 약화 0 · threshold 완화 0.
(`test_39` 는 이 Phase 의 commit 이 없을 때만 건너뛰는 guard 이고 commit 후에는
실행된다.)

### 10.2 신규 테스트 작성 중 **내가** 틀린 것 1건

| 테스트 | 내가 쓴 값 | 실측 | 원인 |
|---|---|---|---|
| `test_36` (1차) | digest 를 담은 파일 7개 | **8개** | 🔴 Phase 3-F-32 가 **바로 이 문제를 겪고**(그 `test_42`: 7 로 썼다가 8 이 나왔다) 자기 파일 제외 검사를 넣었는데, **그 파일 자신이 digest 문자열을 담고 있다** |
| `test_36` (2차) | 내 파일에 리터럴을 둔 채 숫자만 8 로 고침 | — | 🔴 그러면 **3-F-32 의 `test_42` 가 깨진다** (§10.6). 리터럴을 지우고 AST 로 읽도록 다시 썼다 |
| `test_36` (3차) | 64자 16진수 상수는 1종 | **3종** | `test_validation_code_*` 가 각자 다른 핀을 갖는다. 여러 파일이 **공유하는** 쪽을 duel digest 로 골라낸다 |

🔴 3-F-32 가 기록해 둔 실수를 **한 Phase 만에 똑같이 반복**했다. 자기 파일이
측정 대상에 들어가는 함정은 주석으로 남기는 것만으로는 막히지 않는다.

### 10.3 기존 테스트

**하나도 수정하지 않았다.** production 을 바꾸지 않았으므로 기존 어서션이
전부 그대로 성립한다 — 이것 자체가 §3.C 회귀 검증이다.

### 10.4 회귀 결과

| 실행 | 결과 |
|---|---|
| 기준 (3-F-32 끝, `2a73168`) | 4,964 passed / 4 skipped / 0 failed |
| 신규 파일 단독 (1차) | 38 passed / **1 failed** / 1 skipped — 내 `test_36` |
| 전체 (1차) | 5,002 passed / **1 failed** / 5 skipped — 🔴 **3-F-32 의 `test_42`** |
| **최종 전체 (commit 된 상태)** | 🟢 **5,004 passed / 4 skipped / 0 failed** |

### 10.5 최종 전체 회귀

```
5004 passed, 4 skipped in 2121.28s (0:35:21)
```

🔴 **계정이 맞는다**: 4,964 → 5,004 는 **+40** 이고 신규 테스트 수와 정확히
같다. skip 은 4 → **4** 로 되돌아왔다 (1차의 5 는 `test_39` 가 "이 Phase 의
commit 이 아직 없다" 로 건너뛴 것이고, commit 후에는 실행되어 통과한다).

### 10.6 🔴 1차 전체 회귀에서 **내가 남의 테스트를 깼다**

전체 1차에서 실패한 1건은 내 테스트가 아니라
`test_auxiliary_effect_creation_clone_audit.py::test_42` (3-F-32 의 것)였다.

* 원인: 내 `test_36` 이 digest **리터럴**을 적었고, 3-F-32 의 `test_42` 는
  "그 문자열을 담은 테스트 파일 수" 를 세어 7 을 기대한다. 내 파일이
  8번째가 됐다.
* 🔴 **고친 방향이 중요하다.** 3-F-32 의 7 을 8 로 올리지 **않았다** — 그러면
  앞으로 리터럴을 적는 파일이 생길 때마다 그 숫자를 올려야 하는 **번지는
  수정**이 된다. 대신 **내 파일에서 리터럴을 지우고 기존 핀에서 AST 로
  읽도록** 바꿨다. 그 결과 **기존 테스트를 하나도 수정하지 않았다.**
* 그 과정에서 또 틀렸다: "64자 16진수 상수는 duel digest 하나뿐" 이라고
  가정했는데 실측 **3종**이었다 (`test_validation_code_minimal_fix` ·
  `test_validation_code_unknown_policy` 가 각자 다른 핀을 갖는다). 여러
  파일이 **공유하는** 쪽을 duel digest 로 골라내도록 고쳤다.

---

## 11. Engine V1 및 AI/Search 불변성

production 을 바꾸지 않았으므로 **모든 불변 조건이 정의상 유지된다.** 그래도
주장하지 않고 측정했다.

| 불변 조건 | 확인 방법 | 결과 |
|---|---|---|
| `state_hash` 불변 | `GameState.canonical_state` 를 **AST** 로 읽어 `effects`·`effect_count`·`script`·`handlers` 가 **없음**을 확인. 넣는 것은 `players`·`turn`·`uses`·`rule_uses`·`result` 다섯 | 🟢 **구조적으로 무관** |
| RNG · digest 불변 | 6듀얼 / 611결정 digest 핀 **7개** 그대로 | 🟢 불변 |
| hidden information 경계 | 블록 수가 바뀌지 않았다 (34,684) | 🟢 불변 |
| `GameStateView` 경계 | 같음 | 🟢 불변 |
| Engine V1 freeze | `EFFECT_LIBRARY` 16개 정의가 전부 `ordinal 0`, 3-F-32 의 세 카드 **하나도 없음** | 🟢 불변 |
| `EffectRef(card_id, ordinal)` 설계 | 전수 성립, 새 식별 체계 없음 | 🟢 유지 |
| 기존 `UNKNOWN` 의미 | loader 는 계속 **버린다** | 🟢 유지 |
| AI/Search 동작 | `engine/`·`agent/` 가 `EffectSpec` 전용 칸을 **하나도** 읽지 않음 (AST 전수) | 🟢 불변 |
| Lua 파일 위치·내용 | `git show --name-only` 에 `.lua` **0건** | 🟢 불변 |
| skip 수 증가 없음 | 4 → 4 | 🟢 불변 |
| 기존 commit rewrite | 없음 | 🟢 |

---

## 12. 미확인 사항과 남은 구조적 위험

### 12.1 🔴 확인된 범위와 미확인 범위 (§5 가 요구한 구분)

| | 범위 | 결론 |
|---|---|---|
| **확인됨 ✅** | 현재 코퍼스 12,702 스크립트 / 34,684 블록의 **산출물** | 두 경로가 **완전히 같다** (지문 일치) |
| **확인됨 ✅** | 두 경로의 **규칙** | **다르다** — analyzer 에 `_RE_REBIND` 가 없다 |
| **확인됨 ✅** | 그 차이가 **결과로 나타나는 조건** | "Effect 변수가 풀린 뒤 네 핸들러 설정자가 오거나, 풀린 변수가 `Clone` 의 부모가 되는" 자리. 현재 **0건** |
| **확인됨 ✅** | 그 조건에서의 **결과** | §7 에서 3가지 재현. analyzer 가 **없는 핸들러를 만든다** |
| **미확인 ❓** | 앞으로 추가될 스크립트가 그 조건을 만들지 | **알 수 없다.** 0 은 현재 데이터의 성질이고 코드의 보장이 아니다 |
| **미확인 ❓** | `e1:Clone(e1)` 의 추가 인자 의미 | 3-F-32 가 UNKNOWN 으로 남긴 것 그대로 (라이브러리 원문 없음) |
| **미확인 ❓** | 보조 함수가 만드는 Effect 수 | 3-F-32 의 N8 그대로 |

### 12.2 이 Phase 에서 새로 확정한 위험

| # | 위험 | severity | 재현 | 현재 영향 | Engine | AI/Search | 왜 지금 안 고치는가 |
|---|---|---|---|---|---|---|---|
| **N11** | 🔴 **analyzer 에 `_RE_REBIND` 가 없다** — 두 경로의 바인딩 계약이 다르다 | 🟠 중 | ✅ `test_07`·`test_12`·`test_14` | **0건** (전수) | 없음 | 없음 | §5: *"두 경로가 같은 결과를 내고 있다면 production 코드를 변경하지 않는다."* 수정 모양은 §9.3 에 적어 두었고 코퍼스 영향이 **0** 으로 측정되었으므로, 적용은 **안전하지만 이 Phase 의 권한 밖**이다 |
| **N12** | 🟠 **`Clone` 의 부모가 풀린 경우 두 경로가 정면으로 모순** — loader "물려받은 것 없음" vs analyzer "둘 물려받음" | 🟠 중 | ✅ `test_12` | **0건** | 없음 | 없음 | N11 과 같은 뿌리이고 같은 3줄로 함께 해소된다 |
| **N13** | 🟡 **`_EVENT_ORDER` 가 한 번도 발동하지 않는다** — 겹치는 자리 0건 | 🟢 정보 | ✅ `test_26` | 없음 | 없음 | 없음 | 방어적 장치로 **유지하는 것이 맞다.** 0 은 "지금 없다" 이고 "생길 수 없다" 가 아니다. 지우면 D2 가 조용히 되살아난다 |
| **N14** | 🟡 **두 경로가 "같은 블록 수" 를 암묵적 계약으로만 지킨다** — 어긋나면 `entries[position]` 이 **다른 블록의 핸들러를 붙인다** | 🟠 중 | ✅ `test_02` | 없음 (전수 0) | 없음 | 없음 | 3-F-28 이 정규식 공유로 막았고 이 Phase 가 전수 테스트로 고정했다. 구조적으로 강제하려면 두 함수를 합쳐야 하고 그것은 parser 재설계(§5 금지)다 |
| **N15** | 🟠 **"테스트 파일을 세는 테스트" 가 서로를 깨뜨린다** | 🟡 하 | ✅ `test_36` · 3-F-32 `test_42` | 측정 오류 + **다른 Phase 의 테스트 실패** | — | — | 🔴 코드가 아니라 **방법론** 위험이고, 이 Phase 에서 **세 번 연속 틀렸다**(§10.2·§10.6). 교훈: 파일을 세는 테스트는 ① 자기 파일을 **먼저** 제외하고 ② 세는 **리터럴을 자기 파일에 두지 않고** AST 로 읽어야 한다. 전역 규칙으로 강제하려면 conftest 수준의 장치가 필요한데 그것은 이 Phase 의 범위가 아니다 |

### 12.3 기존 위험 (유지)

| # | 위험 | 출처 | 상태 |
|---|---|---|---|
| E1~E3 | 설정자 API 의미 · "모른다" 표현 칸 없음 · 두 번째 setter 는 더하기 | 3-F-29 | **유지** |
| E4 | 캐시 서명에 파서 버전이 없다 | 3-F-27~29 | **유지** — 이 Phase 는 올릴 필요가 없었다 (`v9` 그대로) |
| E6 | `EffectSpec.index` 가 유일하지 않다 | 3-F-28 | **유지** — `test_18` 이 재확인 |
| E8 | 분기별 의미를 표현할 칸이 없다 | 3-F-30 | **유지** |
| N2 | 주석 처리된 설정자가 적용된다 | 3-F-31 | **유지** |
| N3 | `GetLabelObject` 가 가리키는 블록을 알 수 없다 | 3-F-31 | **유지** — 🔴 이 Phase 가 그 중 5건이 **Effect 변수를 푼다**는 것까지 확정 |
| N5 | 함수 매개변수 `e` 의 설정자 661건 | 3-F-31 | **유지** |
| N6 | 두 정규식이 같은 형태 목록을 두 곳에 적는다 | 3-F-32 | **유지** — 🔴 이 Phase 가 `test_09` 로 둘의 동기화를 고정 |
| N7 | 분석기에 `_RE_REBIND` 가 없다 | 3-F-32 | 🔴 **N11·N12 로 승격** — 이 Phase 가 조건·결과·영향 범위를 전부 확정 |
| N8~N10 | 라이브러리 원문 없음 · 다중 반환 · `Clone` 인자 한 줄 제한 | 3-F-32 | **유지** |

---

## 13. 최종 판정 및 다음 Phase 후보

## **`MIXED_FINDINGS`**

증거 없이 결론을 강하게 만들지 않는다. 두 사실이 동시에 성립한다.

1. **`CONFIRMED_CONSISTENT`** — **현재 코퍼스에서** 두 경로의 산출물은
   완전히 같다. `_RE_REBIND` 를 analyzer 에 넣어도 0 스크립트 / 0 블록 /
   `CardAnalysis` 지문 불변이고, Effect 수 · `ordinal` · `EffectRef` 전부
   영향이 없다. **그래서 production 을 바꾸지 않았다.**

2. **`CONFIRMED_BINDING_INCONSISTENCY`** — **규칙 자체는 다르다.** analyzer 에
   `_RE_REBIND` 가 없고, §3.A 의 9가지 중 2가지에서 **실제로 다른 결과를
   재현했다.** 그중 하나는 두 경로가 같은 블록에 대해 정면으로 모순하는
   주장을 한다 (N12). 원인은 "한 모듈에만 규칙이 있다" 이고 영향 범위는
   "Effect 변수가 풀린 뒤 네 핸들러 설정자가 오거나 그 변수가 `Clone` 의
   부모가 되는 자리 — 현재 0건" 이다.

🔴 **"같은 결과를 낸다" 와 "같은 규칙을 쓴다" 는 다르다.** 전자만 보고
`CONFIRMED_CONSISTENT` 로 적으면 §7 에서 재현한 사실을 숨기는 것이고,
후자만 보고 `CONFIRMED_BINDING_INCONSISTENCY` 로 적으면 데이터에 영향이
0 이라는 사실을 과장하는 것이다.

### 13.1 다음 Phase 후보 1개

**Phase 3-F-34 — analyzer 바인딩 규칙 일치 적용 및 산출물 무변화 검증 (N11 + N12)**

이 Phase 가 조사만 하고 남긴 것을 **적용**하는 단계다. 조사가 이미 끝났으므로
범위가 좁다.

* 수정은 §9.3 의 **3줄**이다 — `_RE_REBIND` import, 이벤트 추가와 정렬 맞춤,
  재생 루프의 `pop`. 새 추상화·새 helper·새 enum 없음.
* **성공 기준은 "산출물 무변화"** 다: 블록 34,684 · `cards.cdb` 붙은 블록
  34,635 · `CardAnalysis` 지문 `a68ac9ead874…` · digest 핀 7개 · 전체 테스트
  4,964+N. 이 Phase 가 그 값을 전부 미리 측정해 두었으므로 그대로 쓰면 된다.
* 🔴 **산출물이 바뀌면 그때는 리팩터가 아니라 또 다른 버그 수정**이다. 그
  경우 3-F-32 처럼 `ordinal` 영향부터 재야 하고, 이 Phase 의 0 측정이 왜
  틀렸는지를 먼저 밝혀야 한다.
* 캐시 서명은 **올릴 필요가 없다** (§2.3) — 그 판단 근거도 `test_38` 이
  고정해 두었다. 올리면 12,702 스크립트를 불필요하게 재파싱한다.
* 함께 결정할 것: N14 를 구조적으로 강제할지. 두 함수를 합치는 것은 §5 가
  금지한 parser 재설계이므로, 현실적인 선택은 **전수 테스트 유지**(이 Phase 의
  `test_02`)뿐이라는 것이 이 Phase 의 판단이다.
