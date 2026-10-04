# Phase 3-E-18 — `SetCode` 의 부재 · 존재 · 파싱 실패를 구분할 수 있는가 (감사)

Base: `8019875` (Phase 3-E-17) · Branch: `claude/pensive-goodall-te1egy`

판정: **B. AUDIT ONLY** — 단, §16 의 예외 조항에 해당하는 **parser 분기 1곳**을
고쳤다 (틀린 값을 남기던 블록 3개). Engine 변경 없음.

이 문서가 답하는 질문은 "SetCode 를 구현했는가" 가 아니라

> 지금 repository 가 **"SetCode 가 없다"** 와 **"SetCode 를 읽지 못했다"** 를
> 구분할 수 있는가

하나다.

---

## §3 — Repository Audit (실제 위치)

| 대상 | 위치 |
|---|---|
| `SetCode` 분기 | `sources/lua_loader.py:189` `elif setter == "Code":` |
| 이름 인식 정규식 | `sources/lua_loader.py:47` `_RE_EVENT` · `:50` `_RE_EFFECT_CODE` |
| 묶이지 않은 변수 탈락 | `sources/lua_loader.py:182` `if spec is None: continue` |
| Clone 상속 | `sources/lua_loader.py:164-177` (`:171` `spec.code = parent.code`) |
| 필드 정의 | `core/card_model.py:50` `EffectSpec.code: str | None` |
| 캐시 적용 | `core/card_repository.py:183-185` → `data/cache/lua_scripts.json` |
| 캐시 서명 | `sources/lua_loader.py:303` `load_cached` · `:333` `_signature` |
| provenance 어휘 | `core/provenance.py:26` `SourceKind` · `:44` `FieldStatus` · `:57` `AnalysisStatus` |
| 효과 주소 지정 | `engine/ids.py:102` `EffectRef.resolve` · `:123` `effect_refs` · `:130` `iter_effects` |
| 관측 | `engine/game_state_view.py:161` `setcodes` · `:237-238` |

`elif setter == "Code":` 주변 전체 문맥에서 확인한 사실:

* 인자는 **정규식으로 이름만** 찾는다 (`EVENT_*` 우선, 없으면 `EFFECT_*`).
* 둘 다 못 찾으면 **수정 전에는 아무 일도 하지 않았다** — 이것이 아래 §16 의 bug다.
* 실패를 기록하는 자리가 **없다.** `raw` · `unparsed` · provenance 필드가
  `EffectSpec` 에 없다.

---

## §4 — 원본 Lua 7 사례 (실측)

| # | 사례 | 카드 | 원문 | 파서 결과 |
|---|---|---|---|---|
| 1 | `SetCode(id)` | `c13599884` | `e1:SetCode(id)` | `None` |
| 2 | 여러 `SetCode` (한 카드) | `c3461403` | `e1 EVENT_FREE_CHAIN` · `e2 EFFECT_CHANGE_RACE` · `e4 EVENT_PHASE+PHASE_END` | 블록마다 각각 |
| 3 | 조건부 `SetCode` | `c50789693` | `if opt==0 then SetCode(ATK) else SetCode(DEF) end` | `EFFECT_UPDATE_DEFENSE` 만 |
| 4 | `SetCode` 없는 효과 | `c114932` | 호출 자체가 없다 | `None` |
| 5 | 다른 setter 와 함께 | `c55144522` | `SetType` · `SetCode(EVENT_FREE_CHAIN)` · `SetOperation` | `EVENT_FREE_CHAIN` |
| 6 | 정상 처리 | `c3461403` e1 | `SetCode(EVENT_FREE_CHAIN)` | `EVENT_FREE_CHAIN` |
| 7 | 처리하지 못함 | `c13599884` e2 | `SetCode(1082946)` | `None` |

(카드 이름은 공식 DB 표기를 그대로 쓴다: `c13599884` 강철의 스콜피온 ·
`c114932` 플레이트 크래셔 · `c55144522` 욕망의 항아리 · `c3461403` 불사무사의 애도.)

---

## §5 — SetCode 의 단위: **Effect-level** (C + D 혼합)

```
Card (cards.cdb)
 └─ setcodes: list[int]        ← 카드군 (archetype). 공개 정보. 관측에 나간다.
Card.script (c*.lua)
 └─ effects: list[EffectSpec]
      └─ code: str | None      ← Effect:SetCode(). 효과 단위. 관측에 나가지 않는다.
```

**`SETCODE ≠ SETCODE`.** 이름이 같아서 하나로 보이지만 서로 다른 것이다.

* `Card.setcodes` — cards.cdb 의 카드군 비트. "이 카드가 어느 카드군인가".
* `EffectSpec.code` — Lua 의 `Effect:SetCode()`. 대부분 **유발 이벤트**
  (`EVENT_*`) 거나 **지속 효과의 종류**(`EFFECT_*`) 다. 즉 archetype 이 아니라
  **런타임 효과 코드**다 (§5 의 C). 다만 `SetCode(id)` · `SetCode(1082946)` 처럼
  **카드 식별자**를 넣어 사적인 꼬리표로 쓰는 용례도 있다 (§5 의 D).

"카드 하나에 SetCode 하나" 는 성립하지 않는다. `c64591429` 는 블록 8개에
`code` 가 8개 있다.

---

## §6 — Data Flow

| 단계 | SetCode 값 | 실패 시 표현 | provenance |
|---|---|---|---|
| Lua 원문 | `SetCode(EVENT_PHASE+PHASE_END)` | — | 원문 자체 |
| Parser | `_RE_EVENT` 로 **첫 이름만** | 이름 없으면 `None` (수정 후) | **없음** |
| `EffectSpec.code` | `"EVENT_PHASE"` | `None` | **없음** |
| Repository/cache | 그대로 (JSON 왕복) | `null` | 서명 `v4:{개수}:{mtime}` 뿐 |
| Analysis | `EffectAnalysis.effect_code` 로 복사 | `None` | `AnalysisStatus` (효과 단위 아님) |
| Engine | **읽지 않는다** (`len()` 만) | — | — |

핵심: **파서 → EffectSpec 사이에서 실패가 기록되지 않는다.** 그래서 "없다" 와
"읽지 못했다" 가 같은 `None` 이 된다.

---

## §7 · §9 — `None` 에 몇 가지가 겹쳐 있는가 (실측)

측정 방법: `parse_lua_source` 를 **직접** 돌려(캐시 우회) 블록마다 `spec.code` 와
"이 블록에 Code setter 가 붙었는가" 를 같이 본다. 전 corpus `c*.lua` 12,702개 ·
효과 블록 **34,680개** 기준 (수정 후).

| 상태 | 블록 | 비율 |
|---|---|---|
| A `SetCode` 가 없다 (물려받은 값도 없다) | 4,436 | 12.79% |
| B 자기 `SetCode` 를 읽었다 | 29,978 | 86.44% |
| B′ Clone 이 물려받은 값만 있다 | 148 | 0.43% |
| C/E 호출은 있는데 이름을 못 붙였다 | 118 | 0.34% |
| (별도) 묶이지 않은 변수의 setter | 3,327 | — |

Case 별 결론:

| Case | 뜻 | 현재 표현 | 구분되는가 |
|---|---|---|---|
| 1 | 원본에 `SetCode` 없음 | `None` | — |
| 2 | 있음 + 정상 | 이름 문자열 | **YES** |
| 3 | 있음 + parser 미지원 | `None` | **NO** (Case 1 과 같다) |
| 4 | malformed | `None` | **NO** (Case 1·3 과 같다) |
| 5 | source 불완전 | `None` 또는 블록 없음 | **NO** |
| 6 | cache stale | 겉보기엔 정상 값 | **NO** (표식이 없다) |

즉 `EffectSpec.code is None` 은 **"없다" 와 "읽지 못했다" 를 구분하지 못한다.**
Q6 의 답은 **NO**, Q7 의 답도 **NO** (실패 provenance 가 없다), Q8/Q9 의 답은
"두 상태가 하나로 collapse 되어 있다" 다.

### E-17 의 "162장" 재검증 → 틀린 수였다

E-17 은 "파일의 `SetCode(` 호출 수 > `code` 가 있는 spec 수" 로 셌다. 이 방법은
(1) **묶이지 않은 변수**의 setter 3,327개를 호출 쪽에만 넣고, (2) `local e1=` 을
함수마다 다시 쓰는 스크립트에서 호출 수와 spec 수가 상쇄되는 것을 무시한다.

파서 결과로 다시 세면 **수정 전 115개 블록 · 109개 스크립트**, 수정 후
**118개 블록 · 112개 스크립트**다. (162 는 측정 artifact였다.)

corpus 수 차이도 측정 대상 차이다. E-17 은 `all_cards()` 기준 **34,631 블록 ·
효과 있는 카드 12,504장**, 이번은 `c*.lua` **12,702개 · 34,680 블록**.
차이 49 블록은 **cards.cdb 에 없는 패스코드 15개**의 스크립트다 —
`34,631 + 49 = 34,680` 으로 정확히 맞는다. **두 수 모두 맞다.**

### 캐시: 지금은 **충실하다**, 그러나 파서 변경을 숨긴다

* 표본 400장을 캐시 vs 원문 재파싱으로 비교 → **불일치 0**.
* 서명은 `sources/lua_loader.py:341` `f"v4:{개수}:{최신 mtime}"` 이다. **스크립트
  파일만** 본다. 데이터가 바뀌면 무효화되지만 **파서가 바뀌어도 그대로**다.
* E-17 의 고의 위반 A 가 잡히지 않은 원인이 정확히 이것이다. 이번 Phase 는
  파서를 고쳤으므로 접두사를 `v3` → `v4` 로 **손으로** 올렸다
  (`test_19` 가 이 사실을 고정한다).

---

## §10 — 대표 사례

| Case | Source | Parser | EffectSpec | 판정 |
|---|---|---|---|---|
| A | `c114932` — `SetCode` 없음 | 호출 없음 | `code=None` | SETCODE_ABSENT |
| B | `c55144522` — `SetCode(EVENT_FREE_CHAIN)` | 이름 인식 | `code="EVENT_FREE_CHAIN"` | SETCODE_PRESENT |
| C | `c13599884` — `e1:SetCode(id)` | 이름 못 붙임 | `code=None` | A 와 구분 불가 |
| D | `c3461403` — `e4:SetCode(EVENT_PHASE+PHASE_END)` | 첫 이름만 | `code="EVENT_PHASE"` | 한정자 소실 |
| E | 캐시 경유 400장 | 동일 | 동일 | 일치 (불일치 0) |

### 상태 D — 한정자를 버린다 (1,430개, **고치지 않았다**)

값을 읽은 29,978개 중 **1,430개(4.77%)** 는 인자가 읽은 이름보다 길다.

| 원문 | 수 | 기록된 값 |
|---|---|---|
| `EVENT_PHASE+PHASE_END` | 751 | `EVENT_PHASE` |
| `EVENT_PHASE|PHASE_STANDBY` | 394 | `EVENT_PHASE` |
| `EVENT_PHASE|PHASE_BATTLE` | 131 | `EVENT_PHASE` |
| `EVENT_CUSTOM+id` | 74 | `EVENT_CUSTOM` |

`EVENT_PHASE` 가 **단독으로 쓰인 블록은 0개**다 (1,326개 전부 한정자가 있다).
따라서 `code == "EVENT_PHASE"` 는 **"어느 페이즈인지 모른다"** 를 뜻하고, 서로
다른 1,326개 유발 시점이 한 값으로 합쳐진다. 이것은 **틀린 값이 아니라 덜 읽은
값**이고 읽는 곳도 없으므로 §16 의 예외에 해당하지 않는다 → 고치지 않았다.

### 한 블록에 `SetCode` 가 두 번 (10건)

파서는 블록마다 `code` 하나를 들고 **마지막으로 읽힌 값**을 남긴다.

| 모양 | 건수 | 의미 |
|---|---|---|
| 분기 `if/else` | 3 | Lua 는 하나만 실행 → 뒤쪽만 남는다 (**손실**) |
| Clone 후 원본 수정 | 4 | 두 코드가 모두 남는다 (배정만 바뀜) |
| 덮어쓰기 | 2 | 스크립트 자신의 재지정 → 마지막 값이 맞다 |
| 비-`local` 재생성 | 1 | 앞선 spec 의 `code` 를 덮어쓴다 (**귀속 오류**) |

마지막 1건 `c9839115` 는 `_RE_CREATE_EFFECT` 가 `local` 을 요구해서 생긴다
(`e1=Effect.CreateEffect(c)` 가 새 spec 을 만들지 못하고 앞 spec 에 얹힌다).
`EVENT_SPSUMMON_SUCCESS` 는 `trigger_events` 에 남으므로 **소실이 아니라 귀속
오류**다. 고치면 corpus 블록이 34,680 → 34,682 로 바뀌어 **관측
(`effect_count`)에 닿는다** → 이 감사에서 고치지 않았다 (`test_17` 이 현재
상태를 고정한다).

---

## §11 — `SetCode(1082946)` 의 의미

확인된 것:

* `1082946` 은 **실제 카드 패스코드**다 — cards.cdb 에 있다 (운명의 불시계 · 함정).
* 쓰는 쪽은 `c13599884` (강철의 스콜피온) 의 `e2:SetCode(1082946)` 이고, 같은
  블록에 `SetLabelObject` 가 있다. 즉 **유발 이벤트도 발동도 아니다** — 효과
  사이에 꼬리표를 붙여 서로 찾게 하는 **사적인 기록용 코드**로 쓰인다.
* 같은 모양의 다른 용례: `c16317140` (하이퍼브레이즈) 는 `SetCode(16317140)`
  으로 **자기 패스코드**를 쓴다. `SetCode(id)` 와 같은 관용이다.

확인하지 못한 것: EDOPro 런타임이 이 숫자 코드를 정확히 어떻게 취급하는지
(어느 테이블에 들어가고 누가 조회하는지)는 공식 문서에서 확인하지 못했다 →
**UNKNOWN 으로 남긴다.** 추측해서 의미를 만들지 않는다.

확실한 것은 하나다: **`SetCode(id)` 와 `SetCode(EVENT_*)` 는 같은 종류가 아니다.**

---

## §12 · §14 · §15 — Engine · 관측 · 평가

**Engine 은 `EffectSpec.code` 를 읽지 않는다.** 근거:

* `engine/` 전체에서 `card.script.effects` 를 만지는 모듈은 두 곳이다 —
  `engine/ids.py` (주소 지정) 와 `engine/game_state_view.py`
  (`len()` 으로 **개수만**). `test_10` 이 AST 로 고정한다.
* `EffectRef.resolve` · `effect_refs` · `iter_effects` 를 **production 에서
  호출하는 곳이 없다** (호출자는 테스트뿐). 엔진은 효과를 *지목* 할 수만 있고
  아직 꺼내 읽지 않는다.
* `engine/` 의 `.code` 는 전부 `ValidationCode` 다 — `SetCode` 와 무관하다.
* `CardDefinitionView.setcodes` 는 **cards.cdb 의 카드군**이다 (`setcodes=
  tuple(card.setcodes)`), Lua 효과 코드가 아니다. 상대의 뒷면 카드는
  `CardView.concealed` 로 `definition=None` 이므로 카드군도 보이지 않는다
  (`test_12`).
* `agent/evaluation.py` · `search.py` · `policy.py` · `simulation.py` 에
  `SetCode` · `EffectSpec` · `setcodes` · `trigger_events` 가 **하나도 없다**
  (`test_16`).

→ **ENGINE CHANGE = NO** · GameStateView 변경 없음 · Evaluation/Search 변경 없음.

이것이 이번 collapse 가 **지금** 어떤 판정도 틀리게 만들지 않는 이유다. 동시에,
Trigger Engine 이 생기는 순간 상태 D(1,326개 페이즈 유발)가 먼저 문제가 된다.

---

## §8 — Provenance: 어휘는 **이미 있다**, 닿지 않는다

`core/provenance.py` 에 이미 있는 것:

* `SourceKind` — `LUA` · `OFFICIAL_DB` · `DERIVED` · `UNKNOWN` …
* `FieldStatus` — `CONFIRMED` · `SUPPLEMENTARY` · `MISSING` · `CONFLICTED`
* `AnalysisStatus` — `LUA_VERIFIED` · `TEXT_DERIVED` · `NO_EFFECT` ·
  `UNAVAILABLE` · `UNKNOWN`

없는 것: **효과 단위 provenance.** `Card.provenance` 는 있지만
`EffectSpec`/`LuaScriptInfo` 에는 `provenance`·`status`·`raw`·`unparsed` 필드가
하나도 없다 (`test_09` 가 확인한다).

따라서 나중에 필요해지면 할 일은 **"새 enum 을 만든다" 가 아니라 "이미 있는
어휘를 효과 단위까지 내린다"** 다. 이 Phase 에서는 만들지 않았다 — 읽는 곳이
없는데 필드를 먼저 만들면 ADR-006 의 "등록되지 않은 것은 UNKNOWN" 원칙과
반대로 빈 값을 양산한다.

---

## §16 — 고친 것 하나 (parser bug 증명)

왜 bug 인가:

1. **원문** `c4179255.lua` — `e1:SetCode(EVENT_CHAINING)` → `local e2=e1:Clone()`
   → `e2:SetCode(id)`. Lua 에서 `e2` 의 코드는 `id` 다. `EVENT_CHAINING` 이 아니다.
2. **파서** — `Clone` 분기가 `spec.code = parent.code` 로 물려주고,
   `setter == "Code"` 분기는 인자를 읽지 못하면 **아무것도 하지 않았다.**
3. 결과는 "모른다" 가 아니라 **틀린 주장**이었다 — 스크립트가 분명히 덮어쓴
   유발 코드를 계속 들고 있었다. corpus 전체에서 **3개 블록**
   (`c4179255` · `c73734821` · `c64591429`).

수정:

```python
                    else:
                        spec.code = None   # 읽지 못했으면 '모른다'로 되돌린다
```

* 분기 하나에 `else` 를 더한 것뿐이다. schema · Engine · API 변경 없음.
* 블록 수 34,680 그대로, `effect_count` 그대로 → **관측 불변**.
* 상태 분포만 바뀐다: B 29,981 → 29,978 · C/E 115 → 118.
* 파서가 바뀌었으므로 캐시 서명 `v3` → `v4`.

이 수정이 §16 의 "그 외에는 수정하지 않는다" 와 충돌하지 않는 이유: §16 이 허용한
예외는 **정상적인 `SetCode` 문법을 잘못 처리하는 것이 원문과 파서 코드 대조로
증명된 경우**다. `e2:SetCode(id)` 는 완전히 정상적인 문법이고, 대조 결과는 위와
같다. 그리고 UNKNOWN 을 값처럼 들고 있는 구조는 이 프로젝트가 금지한 바로 그
모양이다.

고치지 않은 것(한정자 소실 1,430개 · 비-`local` 재생성 1건 · 분기 3건)은 모두
**틀린 값이 아니라 덜 읽은 값**이거나 **관측에 닿는 변경**이어서 제외했다.

---

## §17 · §18 — 테스트

신규 `tests/test_setcode_provenance_audit.py` — **19개**.

| # | 검증 |
|---|---|
| 01 | A: 호출이 없으면 `None` |
| 02 | B: 이름 있는 인자를 읽는다 |
| 03 | C/E: 이름 못 붙이면 `None` — **그리고 A 와 같은 값이 된다** |
| 04 | D: 한정자를 조용히 버린다 |
| 05 | 실제 카드 4장에서 다섯 상태 (원문 대조) |
| 06 | `EVENT_PHASE` 는 단독으로 쓰이지 않는다 (표본) |
| 07 | `1082946` 은 실제 패스코드다 + 쓰임새 |
| 08 | 캐시 == 원문 재파싱 (표본 400장) |
| 09 | provenance 어휘는 있고 효과 단위에는 없다 |
| 10 | 엔진은 효과를 지목·계수만 한다 (AST) |
| 11 | 관측의 `setcodes` 는 카드군이다 |
| 12 | 상대 세트 카드는 정체도 카드군도 안 보인다 |
| 13 | `None` 을 "SetCode 없음" 으로 보고하면 안 된다 |
| 14 | 실패를 성공으로 적으면 안 된다 |
| 15 | 모르는 `SetCode` 로 카드군 판정을 하지 않는다 |
| 16 | 평가 · 탐색 · 정책에 들어가지 않았다 |
| 17 | 한 블록에 `SetCode` 두 번 — 세 모양 |
| 18 | **읽지 못한 인자는 물려받은 값을 지운다** (이번 수정) |
| 19 | 캐시 서명은 파서 변경을 모른다 → 손으로 올려야 한다 |

고의 위반 — **전부 잡혔다** (넣고 → 실패 확인 → 되돌림):

| | 위반 | 잡은 테스트 |
|---|---|---|
| A | 읽지 못한 인자를 값처럼 적는다 | 03 · 08 · 14 |
| B | 한정자를 버리지 않고 원문을 적는다 | 04 · 08 · 14 |
| C | 관측이 효과 코드를 내보낸다 | 10 · 11 |
| D | 상대 세트 카드에 정의를 싣는다 | 12 |
| E | `local` 없는 생성도 새 효과로 센다 | 17 |
| F | 이번 수정을 되돌린다 (앞 값을 남긴다) | 18 |

기존 테스트: **삭제 0 · skip 추가 0 · assertion 약화 0 · 수정 0.**

전체: **3547 passed · 4 skipped** (E-17 기준 3528 + 19).

---

## §19 — 성능

| | E-17 | E-18 |
|---|---|---|
| 전체 pytest | 343s | **346s** |
| `c*.lua` 12,702개 원문 파싱 | — | 7.9s |
| repository load (캐시) | — | 2.2s |
| repository load (캐시 없음) | — | 9.5s |

유의미한 regression 없음 (+3s, 측정 편차 범위). 단, 캐시 서명을 `v4` 로 올렸으므로
**다음 첫 실행 한 번만** 전체 재파싱(약 +7s)이 든다.

---

## §20 · §21 — 보호

* STRUCTURAL-34 / 124 / 128 / 131 / 133 유지 · 134 RESOLVED 유지 ·
  SET_ACTIVATION_MISSING RESOLVED 유지. **새 ID 만들지 않았다.**
* `SET_ACTIVATION_TIMING` · `SET_ACTIVATION_EXECUTION` ·
  `SET_CARD_EFFECT_EXECUTION` 그대로. 이번 결과가 이 TODO 들에 필요한가 →
  **아직 아니다.** 세트 카드의 발동 타이밍은 `ActivationTimingChecker` 가 쓰는
  `set_this_turn`·speed 로 결정되고 `spec.code` 를 보지 않는다. `spec.code` 가
  필요해지는 것은 **유발 효과**를 실행할 때(= Trigger Engine)이고, 그때 먼저
  걸리는 것은 상태 D 다.

---

## 다음 Phase 후보 (하나)

**`EVENT_PHASE` 한정자 소실 — 1,326개 블록이 "어느 페이즈인지 모른다" 로 합쳐져
있다.** 이번 Phase 가 측정했고(상태 D), 틀린 값은 아니지만 **유발 시점 자체가
사라진** 유일한 대규모 collapse다. Trigger Engine 이 생기기 전에 "엔드 페이즈에
유발" 과 "스탠바이 페이즈에 유발" 을 구분할 수 있어야 한다.

자동으로 진행하지 않는다.
