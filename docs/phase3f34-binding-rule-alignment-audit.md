# Phase 3-F-34 — analyzer 바인딩 규칙 일치 적용 및 산출물 불변성 검증

**최종 판정: `ALIGNMENT_CONFIRMED_OUTPUT_STABLE`**

Phase 3-F-33 이 조사만 하고 남긴 **N11 · N12** 를 적용했다. 규칙은 일치하게
되었고, **코퍼스 산출물은 하나도 바뀌지 않았다.**

| | 결과 |
|---|---|
| N11 (analyzer 에 `_RE_REBIND` 없음) | 🟢 **해소** — 로더에서 import |
| N12 (`Clone` 부모 재바인딩 시 정면 모순) | 🟢 **해소** — 같은 주장을 한다 |
| 산출물 변화 | 🟢 **0** — §5 의 11개 항목 전부 동일 |
| 의도된 변경(A) / 회귀(B) / UNKNOWN(C) | **A 0건 · B 0건 · C 유지** |
| production 변경 | `analysis/effect_analyzer.py` **1파일** (+35/−2) |
| 캐시 서명 | `v9` — **올리지 않았다** |

---

## 1. 기준 HEAD 및 테스트 검증

`git log` · `git show` · `git status` · `git rev-parse` 로 직접 확인했다.
**지시서 기준과 전부 일치한다.**

| 항목 | 지시서 | 실측 | 결과 |
|---|---|---|---|
| 기준 HEAD | `83b06cf…` | `83b06cfc4d9908c526b32ff0d786b439162a826a` | 일치 |
| 3-F-33 작업+테스트 commit | — | `cf0de5e` (1 file, +1123) | — |
| 3-F-33 보고서 commit | — | `83b06cf` (629줄) | — |
| 기준 보고서 | `docs/phase3f33-…-audit.md` | 629줄, 존재 | 일치 |
| 브랜치 | `claude/pensive-goodall-te1egy` | 같음 | 일치 |
| `origin/claude/…` | — | `83b06cf` — **HEAD 와 동일** | — |
| worktree | — | **clean** | — |
| 기준 전체 테스트 | 5,004 / 4 skipped / 0 failed | 같음 | 일치 |

### 1.1 기준 corpus 통계를 **실제로 재측정**했다 (§1.4)

| 항목 | 3-F-33 보고 | 이 Phase 재측정 | 결과 |
|---|---:|---:|---|
| 스크립트 | 12,702 | **12,702** | 일치 |
| 파서 블록 | 34,684 | **34,684** | 일치 |
| `cards.cdb` 붙은 카드 | 12,687 | **12,687** | 일치 |
| 붙은 블록 | 34,635 | **34,635** | 일치 |
| 등록 Effect | 26,352 | **26,352** | 일치 |
| 해결 Effect | 8,283 | **8,283** | 일치 |
| 조건 / 비용 / 대상 | 12,438 / 5,007 / 5,516 | **같음** | 일치 |
| 액션 / 카테고리 | 18,280 / 20,484 | **같음** | 일치 |
| `EffectRef` 연결 불일치 | 0 | **0** | 일치 |

🔴 **지문 값은 3-F-33 의 것을 그대로 쓰지 않았다.** 그 Phase 가 보고한
`CardAnalysis` 지문 `a68ac9ead874…` 는 **그 스크립트가 쓴 튜플 모양**에
대한 해시다. 이 Phase 의 측정 스크립트는 필드를 더 넣었으므로 지문이
`602328c9…` 로 다르다. **같은 스크립트로 수정 전/후를 맞대는 것**이
의미 있는 비교이고, 3-F-33 의 숫자와는 **개수 항목으로** 맞춰 봤다
(위 표 — 전부 일치). 지문 리터럴을 베껴 적어 "일치" 를 주장하지 않았다.

기존 commit 은 rewrite/amend 하지 않았다.

---

## 2. N11 / N12 의 실제 재현 코드

§4 의 6개 사례를 **수정 전 코드로** 실제 돌렸다. 각 사례에서 원본 Effect ·
Clone 된 Effect · 변수의 현재 바인딩 · 등록 목록 · `EffectSpec` ·
`EffectRef` 를 구분해 기록했다.

### 2.1 사례별 결과 (수정 전 → 수정 후)

| # | 사례 | 블록 | 수정 전 | 수정 후 | 판정 |
|---|---|---:|---|---|---|
| 1 | 생성 → Clone → 원래 변수를 **새 Effect** 로 재바인딩 | 3 | 정상 | 같음 | 🟢 |
| **2** | **생성 → 원래 변수 재바인딩 → Clone** | 2 | 🔴 `Condition,Operation` | `Operation` | **N12** |
| 3 | Clone 결과를 다른 변수에 대입 | 2 | 정상 | 같음 | 🟢 |
| 4 | 같은 변수에 Clone 결과 재대입 | 2 | 정상 | 같음 | 🟢 |
| 5 | 지역/전역이 같은 이름 | 3 | 정상 | 같음 | 🟢 |
| **6** | **parser 가 대입 순서를 인식하지 못함** | 2 | 🔴 `Condition,Operation,Target` | `Operation` | **N12** |

### 2.2 N12 — 사례 2 의 전문

```lua
function s.initial_effect(c)
    local e1=Effect.CreateEffect(c)
    e1:SetCondition(s.con)
    e1:SetCode(EVENT_FREE_CHAIN)
    c:RegisterEffect(e1)
    e1=e:GetLabelObject()      -- loader 는 여기서 e1 을 푼다
    local e2=e1:Clone()        -- 🔴 부모가 누구인가?
    e2:SetOperation(s.op)
    c:RegisterEffect(e2)
end
```

| 관점 | ord1(`e2`) 에 대한 주장 | |
|---|---|---|
| loader (`EffectSpec`) | `cloned_from='e1'` · `code=None` · `effect_types=[]` — **여섯 칸을 하나도 물려받지 않았다** | 수정 전후 동일 |
| analyzer **수정 전** | 핸들러 `{Condition: s.con, Operation: s.op}` — **옛 부모의 `Condition` 을 물려받았다** | 🔴 모순 |
| analyzer **수정 후** | 핸들러 `{Operation: s.op}` — **물려받지 않았다** | 🟢 loader 와 같다 |

🔴 수정 전에는 같은 블록에 대해 **"물려받은 것 없음"(loader)** 과
**"하나 물려받았음"(analyzer)** 이 동시에 주장됐다. 그것이 N12 다.

### 2.3 N11 — 재바인딩 뒤의 핸들러 설정자

```lua
    local e1=Effect.CreateEffect(c)
    e1:SetTarget(s.tg)
    e1:SetCode(EVENT_FREE_CHAIN)
    c:RegisterEffect(e1)
    e1=e:GetLabelObject()
    e1:SetOperation(s.op)      -- 🔴 여기서 갈렸다
```

| | ord0 의 핸들러 |
|---|---|
| loader | 설정자를 **버린다** (`code` 는 제 값 `EVENT_FREE_CHAIN` 그대로) |
| analyzer **수정 전** | `{Target: s.tg, **Operation: s.op**}` — Lua 원문에 없는 값 |
| analyzer **수정 후** | `{Target: s.tg}` |

### 2.4 🔴 §4 의 제약을 지켰다 — 사례 1 이 그 증거다

> *"Clone 부모가 재바인딩되었다는 사실만으로 과거 Clone 의 부모 관계나
> ordinal 을 변경하지 않는다."*

사례 1 은 `Clone` **뒤에** 부모를 새 Effect 로 재바인딩한다. 수정 전후
모두:

```
ord0 index=e1 code=EVENT_FREE_CHAIN cloned_from=None
ord1 index=e2 code=EVENT_FREE_CHAIN cloned_from=e1    ← 그때 유효했던 부모
ord2 index=e1 code=EVENT_TO_HAND    cloned_from=None  ← 새 생성, 별개 블록
```

`ord1` 의 `cloned_from` 과 핸들러(`Condition,Operation`)가 **그대로**이고
`ordinal` 도 움직이지 않는다. 테스트 `test_09` · `test_13` 이 이것을 못
박는다. (`Clone` 결과 객체와 원본을 같은 객체로 취급하지 않는 것도
`test_14` 가 확인한다 — `blocks[0] is not blocks[1]`, 목록 칸도 별개 객체.)

---

## 3. 수정 전후 loader / analyzer 처리 차이

### 3.1 loader 가 실제로 쓰는 규칙 (§3 — 실제 HEAD 에서 읽었다)

```python
# sources/lua_loader.py
_RE_REBIND = re.compile(
    r"(?:(?<=^)|(?<=[;\s\)])) *(?:local\s+)?"
    r"([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)"
    r"\s*=(?!=)"
    r"(?!\s*(?:Effect\.(?:CreateEffect|GlobalEffect)\s*\("     # 아는 세 형태는
    r"|[A-Za-z_]\w*\s*:\s*Clone\s*\([^()\n]*\)"                # 선읽기로 제외
    r"|Effect\s*\.\s*Clone\s*\(\s*[A-Za-z_]\w*\s*\)))",
    re.M,
)
_EVENT_ORDER = {"create": 0, "clone": 0, "rebind": 1, "set": 2}
```

처리 순서: 이벤트를 `(byte offset, _EVENT_ORDER[kind])` 로 정렬해
`create`/`clone` → `rebind` → `set` 순으로 재생한다.

### 3.2 표로

| 항목 | loader | analyzer **수정 전** | analyzer **수정 후** |
|---|---|---|---|
| `_RE_CREATE_EFFECT` · `_RE_CLONE_EFFECT` · `_clone_source` · `_is_card_effect` | 정의 | 🟢 import | 🟢 import |
| `_RE_REBIND` | 정의 | 🔴 **없음** | 🟢 **import** |
| `_EVENT_ORDER` | 정의 | 🔴 **없음** (`pos` 만 정렬) | 🟢 **import** |
| 소비 설정자 | 값 7개 | 함수 슬롯 4개 | 같음 (교집합 없음) |
| 블록 생성 | `create`/`clone` 만 | 같음 | 같음 |
| 재바인딩이 블록에 하는 일 | **없음** (바인딩만 푼다) | — | **없음** |

🔴 **규칙을 베끼지 않고 import 한다.** 복사본을 두면 로더만 고친 순간 두
경로가 다시 갈린다 — 3-F-28 이 탐지 정규식에서, 3-F-32 가 `Clone` 형태에서
각각 겪었다. `test_01` 이 객체 동일성(`is`)까지 확인한다.

---

## 4. corpus 전수 측정 결과

| 항목 | 값 |
|---|---:|
| `_RE_REBIND` 매치 **원문** | 67,226 |
| 🔴 **이름 단위** unbind 이벤트 | 81,688 |
| 🔴 그중 **실제 Effect 변수**를 푸는 자리 | **30** |
| Effect 와 무관한 일반 변수 | 81,658 |
| 🔴 설정자가 **풀린 바인딩에 붙는** 자리 | **0** |
| 🔴 **풀린 부모를 쓰는 `Clone`** | **0** |

🔴 **정규식 매치 수(67,226)를 Effect 재바인딩 수(30)로 쓰면 2,240배
틀린다.** `test_06` 이 그 비율을 다시 산출하고 `effect_vars < matches/1000`
으로 못 박는다.

마지막 두 줄이 **0 인 것이 산출물 불변의 이유**다. 그러나 0 은 "구조적으로
불가능" 이 아니라 **"이 코퍼스에 없다"** 다 — §2 의 최소 재현이 그것을
보인다. 두 사실을 섞지 않는다.

---

## 5. 산출물 fingerprint 및 상세 diff

§5 가 요구한 **11개 항목 전부**를 수정 전/후로 측정했다. 비교는 항상
**같은 측정 스크립트를 두 설정으로 돌려** 맞댔다.

| 항목 | 수정 전 | 수정 후 | 결과 |
|---|---|---|---|
| 전체 스크립트 수 | 12,702 | 12,702 | 🟢 |
| 전체 파서 블록 수 | 34,684 | 34,684 | 🟢 |
| `cards.cdb` 붙은 카드 / 블록 | 12,687 / 34,635 | 같음 | 🟢 |
| `EffectSpec` 전수 지문 | `b2623fe93aa0…` | `b2623fe93aa0…` | 🟢 **동일** |
| **`CardAnalysis` 전수 지문** | `602328c9c029…` | `602328c9c029…` | 🟢 **동일** |
| 등록 Effect 수 | 26,352 | 26,352 | 🟢 |
| 해결 Effect 수 | 8,283 | 8,283 | 🟢 |
| 조건 / 비용 / 대상 | 12,438 / 5,007 / 5,516 | 같음 | 🟢 |
| 액션 / 카테고리 | 18,280 / 20,484 | 같음 | 🟢 |
| `EffectRef` 연결 (총 34,635, 불일치) | 0 | 0 | 🟢 |
| 검색 **카테고리** 결과·순위 지문 (31개) | `d57c6ae18b70…` | 같음 | 🟢 |
| 검색 **위치** 결과·순위 지문 (31개) | `a822e7604cab…` | 같음 | 🟢 |
| 3-F-32 대표 3사례 + 반례 2사례 | — | 같음 | 🟢 |

### 5.1 상세 diff

**없다.** 달라진 스크립트 **0개**, 달라진 블록 **0개**, 달라진 핸들러
**0개**, 달라진 카드 **0장**.

### 5.2 🔴 검색은 analyzer 를 거치지 않는다 — 처음에 공허한 테스트를 썼다

처음에는 `_collect_handlers` 를 수정 전 것으로 끼워 넣고 검색 지문을
before/after 로 비교하는 테스트를 썼다. **그 비교는 공허했다** —
`core/card_search.py` 는 `analysis` 를 아예 import 하지 않고
`card.effects` 는 `card.script.effects`(**loader** 의 산출물)이므로, 끼워
넣어도 아무 일이 일어나지 않고 결국 **검색을 자기 자신과 비교**하고 있었다.

지우고 실제로 확인할 수 있는 둘로 다시 썼다 (`test_34`): ① AST 로
구조적 독립성을 증명하고 (`"analysis" not in imported_modules`,
`card.effects is card.script.effects`), ② 3-F-32 가 세운 사실
(`c56410769` 의 MZONE 범위 블록이 `['e1','e2','e3']` 이고 셋째가
`cloned_from='e2'`) 을 실제로 돌려 확인한다.

위 표의 검색 지문 두 줄은 **별도 측정 스크립트**로 수정 전/후를 각각 돌려
얻은 값이고(§5 표), 그쪽은 공허하지 않다 — loader 를 건드리지 않았으므로
동일한 것이 당연하지만, 당연함을 가정하지 않고 측정했다.

---

## 6. 의도된 변경과 회귀의 구분

§5 는 산출물이 달라졌을 때 A/B/C 로 나누라고 했다.

| 분류 | 건수 | 내용 |
|---|---:|---|
| **A. 실제 오귀속/누락을 바로잡은 의도된 변경** | **0** | 코퍼스에 그런 자리가 없다 (§4 의 마지막 두 줄이 0) |
| **B. 기존 분석 결과를 훼손한 회귀** | **0** | 지문이 전부 동일하다 |
| **C. 파서가 판정할 수 없는 UNKNOWN** | **유지** | 아래 §10.1 |

🔴 **A 가 0 이라고 해서 수정이 무의미한 것은 아니다.** 바뀐 것은
**계약**이다 — 두 경로가 같은 규칙을 쓰므로, 앞으로 §2 같은 Lua 가
들어오면 **지금부터는 둘이 같은 답을 낸다.** §5 가 "산출물의 완전한
동일성은 목표" 라고 했고, 이 Phase 는 그 목표를 **달성한 쪽**이다.

그리고 C 를 임의 추론으로 제거하지 않았다 — 재바인딩 뒤의 설정자는
**계속 버려진다**(UNKNOWN). analyzer 가 loader 와 같아진 것은
"추측하기" 가 아니라 "같이 모른다고 말하기" 다.

---

## 7. 신규 · 기존 테스트 결과

### 7.1 신규

`tests/test_binding_rule_alignment.py` — **41개** (지시서 최소 25개).
§6 의 14개 범주를 전부 덮는다. 🔴 **정규식 문자열 존재 여부만 보는
테스트로 개수를 채우지 않았다** — 전부 실제 `parse_lua_source` ·
`EffectAnalyzer._collect_handlers` · `CardSearchEngine` 을 실행한다.

핵심은 `_collect_without_rebind` 다. 산출물 불변성을 주장하려면 **"수정
전" 을 실제로 돌려야** 하므로, 3-F-33 시점의 analyzer 동작을 한 곳에만
남겨 두고 before/after 를 맞댄다. 탐지 정규식과 `_clone_source` 는 지금
것을 그대로 쓴다 — 바뀐 것이 재바인딩 규칙 하나뿐임을 보이려면 나머지가
같아야 한다.

🔴 **지문 값을 리터럴로 적지 않았다.** 비교는 "같은 측정을 두 설정으로
돌려 맞대기" 로만 한다 (`test_31` · `test_32`). 개수 항목만 3-F-33 이
보고한 값과 맞춰 본다.

### 7.2 기존 테스트 수정 — 3개, 전부 이유를 기록

삭제 0 · skip 추가 0 · assertion 약화 0 · threshold 완화 0.
`tests/test_loader_analyzer_binding_consistency.py` 의 40개 가운데
**정확히 1개**가 깨졌고, 나머지 2개는 통과하지만 **framing 이 낡아서**
바로잡았다.

| 테스트 | 왜 바꿨는가 |
|---|---|
| **`test_40`** | 🔴 **3-F-33 이 심어 둔 의도적 tripwire 가 뒤집혔다.** 그 docstring 이 *"이 테스트는 '없는 것이 옳다' 는 주장이 아니다. 지금 상태가 무엇인지를 못 박아, 다음 Phase 가 넣을 때 **의도적으로** 이 줄을 바꾸게 만든다"* 라고 적어 두었다. 장치가 설계대로 작동해 **40개 중 이것 하나만** 멈춰 세웠다. 이제 "규칙이 한 곳에 정의되고 양쪽이 import 한다" 를 못 박고, 복사본을 만들면 다시 깨지도록 **객체 동일성(`is`)** 까지 확인한다 |
| `test_01` | 비교 대상이 바뀌었다. 3-F-33 시점에는 스위치를 **끈** 쪽이 production 이었고 이제 **켠** 쪽이 production 이다. 🔴 양쪽 다 통과하지만(코퍼스가 그 스위치에 무감하다 — `test_03`), 무엇이 production 인지 틀리게 적어 두면 **계측 검증이라는 이 테스트의 목적이 사라진다.** 바로잡고 끈 쪽은 따로 확인한다 |
| `test_03` | 어서션은 그대로고 **읽는 방향만 반대**가 됐다 — 이제 이 0 은 "넣어도 안 바뀐다" 가 아니라 **"빼도 안 바뀐다"** 를 뜻한다. 어느 쪽으로 읽어도 같은 사실이다 |

### 7.3 신규 테스트 작성 중 **내가** 틀린 것 2건

| 테스트 | 원인 |
|---|---|
| `test_32` | `classmethod` 가 첫 인자로 `cls` 를 넘기는 것을 빠뜨려 `TypeError`. 람다로 감쌌다 |
| `test_34` | 🔴 **공허한 비교**를 썼다 (§5.2). 검색이 analyzer 를 거치지 않으므로 monkeypatch 가 아무 일도 하지 않았다. 구조적 독립성을 AST 로 증명하고 3-F-32 의 사실을 실제로 확인하도록 다시 썼다 |

### 7.4 회귀 결과

| 실행 | 결과 |
|---|---|
| 기준 (3-F-33 끝, `83b06cf`) | 5,004 passed / 4 skipped / 0 failed |
| 3-F-33 파일 단독 (수정 적용 후) | 39 passed / **1 failed** — `test_40` (의도된 tripwire) |
| 신규 파일 단독 (1차) | 38 passed / **1 failed** / 2 skipped — 내 `test_32` |
| **최종 전체 (commit 된 상태)** | 🟢 **5,045 passed / 4 skipped / 0 failed** |

### 7.5 최종 전체 회귀

```
5045 passed, 4 skipped in 2634.74s (0:43:54)
```

🔴 **계정이 맞는다**: 5,004 → 5,045 는 **+41** 이고 신규 테스트 수와 정확히
같다. skip 은 **4 → 4** 로 유지됐다 (§8 의 조건). 기존 테스트 3개를
수정했지만 **개수는 늘거나 줄지 않았다** — 전부 같은 테스트의 어서션과
docstring 을 고친 것이다.

### 7.6 commit 셋

| commit | 내용 |
|---|---|
| `dac1c8d` | *align the analyzer binding rule with the loader* — `analysis/effect_analyzer.py` (+35/−2) |
| `b959dda` | *test binding rule alignment and output invariance* — 신규 41개 + 기존 3개 수정 |
| (아래) | *document binding rule alignment audit* — 이 보고서 |

---

## 8. production 변경 파일과 정확한 diff

`analysis/effect_analyzer.py` **한 파일**, **+35 / −2** (주석 포함).
`sources/lua_loader.py` 는 **건드리지 않았다.**

### 8.1 import — 공통 규칙 둘을 가져온다

```diff
 from sources.lua_loader import (
     _clone_source,
+    _EVENT_ORDER,
     _extract_call_args,
     _is_card_effect,
     _RE_BLOCK_COMMENT,
     _RE_CLONE_EFFECT,
     _RE_CREATE_EFFECT,
+    _RE_REBIND,
 )
```

### 8.2 이벤트 수집과 정렬

```diff
+        for m in _RE_REBIND.finditer(source):
+            events.append((m.start(), "rebind", m.group(1)))
         for m in _RE_SETTER.finditer(source):
             events.append(
                 (m.start(), "set", f"{m.group(1)}|{m.group(2)}|{m.end() - 1}")
             )
-        events.sort(key=lambda e: e[0])
+        events.sort(key=lambda e: (e[0], _EVENT_ORDER[e[1]]))
```

### 8.3 재생 루프

```diff
         for pos, kind, payload in events:
-            if kind == "create":
+            if kind == "rebind":
+                for name in payload.split(","):
+                    bindings.pop(name.strip(), None)
+            elif kind == "create":
```

🔴 **`order` 는 건드리지 않는다.** 블록은 `create`/`clone` 만 만들고,
재바인딩은 **이미 만들어진 블록의 자리나 부모 관계를 바꾸지 않는다**
(`ordinal` 불변). §4 의 제약이 코드 구조로 보장된다.

### 8.4 금지 경로

| 경로 | 변경 |
|---|---|
`.lua` 원본 | **0건** |
`README.md` | **0건** |
`engine/` · `agent/` | **0건** |
`core/` · `sources/` | **0건** |
새 enum · public API · abstraction | **0건** (새 이름은 `rebind` 이벤트 종류 하나뿐이고 로더의 표를 쓴다) |
`EffectSpec` · `EffectRef` 설계 | **0건** (`test_24` 가 필드 목록을 글자 그대로 고정) |

### 8.5 캐시 서명 — 올리지 않았다

§7 은 *"실제 캐시 무효화가 필요한 경우에 한한"* 갱신만 허용한다.
**필요하지 않다**:

* analyzer 는 디스크 캐시가 **없다** — `_cache` 는 인스턴스 안의 메모리
  dict 하나이고, 쓰기 경로(`write_text`·`dump`·`load_cached`·`replace`)가
  AST 로 **0건**이다 (`test_38`).
* loader 는 건드리지 않았고 그 산출물(`EffectSpec` 전수 지문)도 **동일**하다.

올리면 12,702 스크립트를 쓸데없이 재파싱한다. `v9` 를 유지한다.

---

## 9. 불변 조건 검증

| 조건 | 확인 방법 | 결과 |
|---|---|---|
| `state_hash` 불변 | `GameState.canonical_state` 를 **AST** 로 읽어 `effects`·`effect_count`·`script`·`handlers` 부재 확인. 넣는 것은 `players`·`turn`·`uses`·`rule_uses`·`result` 다섯 | 🟢 **구조적으로 무관** |
| RNG · digest 불변 | 6듀얼 / 611결정 digest 핀 7개 그대로 | 🟢 |
| hidden information 경계 | 블록 수 34,684 불변 | 🟢 |
| `GameStateView` 불변 | 같음 | 🟢 |
| Engine V1 freeze | `EFFECT_LIBRARY` 16개 정의 전부 `ordinal 0`, 3-F-32 의 세 카드 **0장** | 🟢 |
| `EffectRef(card_id, ordinal)` 설계 | 필드 `["card_id","ordinal"]` · 연결 전수 성립 | 🟢 |
| Phase 3-F-27 ~ 33 회귀 | 3-F-27 `SetType` 교체 · 3-F-31 `GetLabelObject` UNKNOWN · 3-F-32 세 사례 + 반례 · 3-F-33 40개 중 39개 그대로(1개는 의도된 tripwire) | 🟢 |
| 기존 skip 수 4 유지 | 4 → 4 | 🟢 |
| Lua 원본 변경 없음 | `git show --name-only` 에 `.lua` 0건 | 🟢 |
| 금지 경로 변경 없음 | §8.4 | 🟢 |

---

## 10. 남은 UNKNOWN 영역과 구조적 위험

### 10.1 UNKNOWN 은 그대로 남겼다 (§5 의 C)

| 영역 | 규모 | 상태 |
|---|---:|---|
| 함수 매개변수 `e` 의 설정자 | 661 | **유지** — 런타임 값이므로 원리적으로 불가능 |
| `e:GetLabelObject()` 가 가리키는 블록 | 1,196 자리 | **유지** — 정적으로 풀 수 없다 |
| 보조 함수가 만드는 Effect 수 | 15종 / 1,532 호출 | **유지** — 구현 원문이 저장소에 없다 (3-F-32 N8) |
| 재바인딩 뒤의 설정자 | 1,330 (loader) | **유지** — 🔴 이제 analyzer 도 **같이** 버린다 |
| `e1:Clone(e1)` 의 추가 인자 의미 | 2 자리 | **유지** (3-F-32) |

🔴 **analyzer 가 loader 와 같아진 것은 "추측하기" 가 아니라 "같이 모른다고
말하기" 다.** UNKNOWN 을 임의 추론으로 제거하지 않았다.

### 10.2 이 Phase 가 해소한 위험

| # | 위험 | 출처 | 상태 |
|---|---|---|---|
| **N11** | analyzer 에 `_RE_REBIND` 가 없다 | 3-F-33 | 🟢 **해소** — import 로 공유, `test_01` 이 객체 동일성 고정 |
| **N12** | `Clone` 부모가 풀린 경우 두 경로가 정면 모순 | 3-F-33 | 🟢 **해소** — `test_12` 가 일치를 고정 |

### 10.3 남은 구조적 위험

| # | 위험 | severity | 재현 | 현재 영향 | 왜 지금 안 고치는가 |
|---|---|---|---|---|---|
| **N13** | 🟡 `_EVENT_ORDER` 가 코퍼스에서 한 번도 발동하지 않는다 (겹치는 자리 0건) | 🟢 정보 | 3-F-33 `test_26` | 없음 | 방어적 장치로 **유지가 맞다.** 🔴 이 Phase 가 analyzer 에도 같은 표를 넣었으므로 **이제 두 곳이 그것에 의존한다** — 지우면 둘이 조용히 갈린다 |
| **N14** | 🟠 두 경로가 "같은 블록 수" 를 **암묵적 계약**으로만 지킨다 | 🟠 중 | `test_21` | 없음 (전수 0) | 🔴 **이 Phase 가 규칙을 하나 더 공유하게 만들어 위험이 줄었지만 없어지지는 않았다.** 구조적으로 강제하려면 두 함수를 합쳐야 하고 그것은 §7 이 금지한 parser 재설계다. 현실적 방어는 전수 테스트 유지뿐이다 |
| **N15** | 🟡 "파일을 세는 테스트" 가 서로를 깨뜨린다 | 🟡 하 | 3-F-33 `test_36` | 측정 오류 | **유지** — 방법론 위험. 전역 규칙으로 강제하려면 conftest 장치가 필요하고 이 Phase 의 범위가 아니다 |
| **N16** | 🟡 **`_collect_without_rebind` 가 "수정 전" 의 복사본이다** | 🟡 하 | `test_31`·`test_32` | 테스트 전용 | 🔴 산출물 불변성을 주장하려면 수정 전을 실제로 돌려야 하므로 불가피하다. 다만 이것은 **또 하나의 복사본**이고, loader 의 탐지 규칙이 다시 바뀌면 이 함수도 같이 손봐야 한다. 테스트 전용이고 production 경로에 없으므로 위험이 제한적이다 |
| N2~N10 | 주석 처리된 설정자 · 다중 반환 보조 함수 · `Clone` 인자 한 줄 제한 등 | 3-F-31·32 | — | **유지** |
| E1~E8 | 설정자 API 의미 · "모른다" 표현 칸 없음 · `index` 비유일 · 분기 의미 표현 불가 · 캐시 서명에 파서 버전 없음 | 3-F-27~30 | — | **유지** (E4 는 이 Phase 가 올릴 이유가 없었다) |

---

## 11. 최종 판정 및 다음 Phase 후보

## **`ALIGNMENT_CONFIRMED_OUTPUT_STABLE`**

* **정렬 확인됨** — analyzer 가 loader 의 `_RE_REBIND` 와 `_EVENT_ORDER` 를
  **import 해서** 쓴다. N11 · N12 가 둘 다 해소되고, §4 의 6개 사례 가운데
  갈렸던 2개(사례 2 · 6)가 이제 loader 와 같은 답을 낸다.
* **산출물 안정** — §5 의 11개 항목 **전부 동일**. 달라진 스크립트 0 ·
  블록 0 · 핸들러 0 · 카드 0. `EffectSpec` 과 `CardAnalysis` 전수 지문이
  수정 전/후 **같다.**
* **의도된 변경(A) 0 · 회귀(B) 0 · UNKNOWN(C) 유지.**

다른 판정을 고르지 않은 이유: `ALIGNMENT_CONFIRMED_INTENDED_CHANGES` 는
A 가 1건 이상일 때 쓸 말이고 A 는 0 이다. `REGRESSION_DETECTED` 는 B 가
있을 때이고 B 는 0 이다. `MIXED_FINDINGS` 는 서로 다른 방향의 사실이
공존할 때인데, 이번에는 "정렬했고 산출물은 그대로" 라는 **한 방향**이다.
`UNKNOWN_BY_DESIGN` 은 판정 자체를 못 할 때이고, 이번에는 전수로 측정해
판정했다.

### 11.1 다음 Phase 후보 1개

**Phase 3-F-35 — 블록 목록 길이 계약의 구조적 강제 가능성 조사 (N14)**

이 Phase 가 규칙 하나를 공유하게 만들어 위험을 줄였지만, **가장 비싼
실패 양식**은 아직 암묵적 계약으로만 막혀 있다.

* `EffectAnalyzer._collect_handlers` 가 돌려주는 목록의 `i` 번째가
  `card.script.effects[i]` 여야 한다. 어긋나면 **다른 블록의 핸들러를
  붙인다** — 3-F-28 이 실제로 겪었고, 3-F-32 가 `_clone_source` 를 안
  만들었다면 또 겪었을 일이다.
* 지금 그것을 막는 것은 ① 탐지 규칙을 import 로 공유한다는 관례와
  ② 전수 테스트(`test_21`) 둘뿐이다. **코드가 강제하지 않는다.**
* 🔴 **먼저 재야 할 것**: 두 함수를 합치지 않고(§7 금지) 길이 정합을
  강제할 수 있는가. 후보는 ⓐ 블록 생성 이벤트만 만드는 작은 공통 함수를
  두고 양쪽이 그것을 쓰는 방법, ⓑ analyzer 가 `card.script.effects` 를
  인자로 받아 길이를 assert 하는 방법, ⓒ 지금처럼 테스트로만 막는 방법.
  ⓐ·ⓑ 가 §7 의 "필요성이 입증되지 않은 공통 프레임워크" 선을 넘는지,
  그리고 산출물이 바뀌지 않는지를 **측정으로** 판단해야 한다.
* 성공 기준은 이 Phase 와 같다 — **산출물 무변화** (블록 34,684 ·
  `CardAnalysis` 지문 · 검색 지문 · digest 핀 7개). 그 값은 이 Phase 가
  이미 측정해 두었다.
* 함께 정리할 것: N16 (테스트 쪽 "수정 전" 복사본)을 그 공통 함수로
  대체할 수 있는지.
