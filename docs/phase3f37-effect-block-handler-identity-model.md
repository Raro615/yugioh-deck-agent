# Phase 3-F-37 — 파싱 시점 블록 식별자 보존 및 결합 실패의 UNKNOWN 처리

> Phase 3-F-36 의 판정 `IDENTITY_REQUIRES_DATA_MODEL_CHANGE` 를 받아, 그 Phase 가
> **보고만 하고 구현하지 않은 안 B** 를 실행했다.
>
> 보존한 식별자는 **한 쌍**이다.
>
> ```
> (LuaScriptInfo.source_digest , LuaScriptInfo.effect_offsets[i])
>   └ 어느 소스 버전인가           └ 그 안의 어느 자리인가
> ```
>
> 그리고 대응을 증명하지 못한 블록은 **등록/해결 중 어느 쪽도 주장하지 않고**
> `HandlerBinding` 과 `CardAnalysis.unbound_effects` 에 적어 둔다.

---

## 1. 기준 HEAD 와 전체 테스트 결과

| 항목 | 값 | 확인 |
|---|---|---|
| Phase 3-F-36 최종 commit | `edcd96e` | `git rev-parse` 실측 |
| 3-F-36 테스트 commit | `5e47bae` | 실측 |
| 3-F-36 보고서 commit | `cfd279b` | 실측 |
| 3-F-36 테스트 수정 commit | `741cddc` | 실측 |
| 기준 전체 테스트 | 5,140 passed / 4 skipped / 0 failed | 3-F-36 에서 실측 |
| 기준 corpus | 14개 비교 항목 | §9 에서 다시 측정 |
| HEAD / origin / worktree | 일치 · clean | 실측 |

§1 이 적어 준 네 SHA 가 모두 일치했고, 기준 상태의 차이는 없었다.

전체 회귀 결과는 §10 에 있다. 🔴 **중간에 기존 테스트 113건이 깨졌고, 그 원인과
처리를 §8 과 §10 에 전부 적었다.** 숨기지 않았다.

---

## 2. 기존 데이터 흐름 (3-F-37 이전)

현재 HEAD 의 코드를 따라갔다. 보고서의 서술을 가정하지 않았다.

```
                 ┌─ 리포지토리 빌드 시점 ────────────────────────────┐
c*.lua ─────────▶│ sources/lua_loader.parse_lua_source()            │
  (또는           │   → LuaScriptInfo.effects : list[EffectSpec]     │
 data/cache/     │   → card.script.effects                          │  ← 목록 ①
 lua_scripts     └──────────────────────────────────────────────────┘
  .json)
                 ┌─ 분석 시점 ──────────────────────────────────────┐
c*.lua ─────────▶│ EffectAnalyzer._read_source(file_name)           │
 (다시 읽는다)     │ EffectAnalyzer._collect_handlers(source, spans)  │  ← 목록 ②
                 └──────────────────────────────────────────────────┘
                            entry = entries[position] …
```

경로별로 **실제로 보존되던 정보**를 적으면 이렇다.

| 경로 | script 식별 | byte offset / span | 블록 식별 | handler 대응 | Clone·재바인딩 |
|---|---|---|---|---|---|
| `parse_lua_source` 이벤트 수집 | 파일명 | 🟢 `m.start()` 를 **갖고 있다** | — | — | `cloned_from` |
| `create`/`clone` 재생 | 파일명 | 🔴 `for _pos, …` — **버린다** | 목록 위치뿐 | — | `cloned_from` |
| `LuaScriptInfo` (14칸) | `card_id`·`file_name` | 🔴 없음 | 🔴 없음 | — | `EffectSpec.cloned_from` |
| 캐시 JSON | 같음 | 🔴 없음 | 🔴 없음 | — | 같음 |
| `_collect_handlers` | — | 🟢 `pos` 를 갖고 있다 | 🔴 `_enclosing_function` 에만 쓴다 | `handlers` dict | 부모 핸들러 상속 |
| `_analyze_card` 결합 | — | 🔴 없음 | 🔴 **`position` 뿐** | 위치로 붙인다 | — |
| `EffectSpec` (9칸) | — | 🔴 없음 | `index`(고유 아님) | — | `cloned_from` |
| `CardAnalysis` | `card_id` | 🔴 없음 | 🔴 없음 | `effects`/`resolution_effects` | — |

### 2.1 추가로 확인한 두 가지

* 🔴 **`_read_source` 가 `None` 을 돌려주면 `_analyze_card` 가 효과 없는 분석을
  조용히 돌려줬다.** `has_script=True` 인데 `effects` 와 `resolution_effects` 가
  모두 비어 있고, **블록이 0개인 카드와 구별되지 않았다.**
* 🔴 **`core.provenance.AnalysisStatus` 로는 이 구분을 적을 수 없다.** 그것은
  카드 한 장의 분석이 **무엇에 근거하는가**(`LUA_VERIFIED`/`TEXT_DERIVED`/
  `NO_EFFECT`/`UNAVAILABLE`)를 말하고, `core/card_repository.py` 가 카드 단위로
  정하며 듀얼 엔진이 `TEXT_DERIVED` 를 실행 차단에 쓴다. 필요한 것은 **블록
  하나의 핸들러 연결이 증명되었는가**이고, 두 축은 교차한다 — `LUA_VERIFIED` 인
  카드 안에서도 블록 하나는 증명되고 다른 하나는 안 될 수 있다. 그래서 §6 의
  "기존 오류 타입으로 표현할 수 있으면 새 enum 을 만들지 않는다" 를 적용할 수
  없었고, 이 보고서로 그 근거를 남긴다.

---

## 3. 식별자 후보 비교 (§4)

### 후보 A — 파싱 시점 식별자

| 안 | 내용 | 판정 |
|---|---|---|
| A-1 | 블록 offset 만 저장 | 🔴 **부족하다.** offset 이 같다는 것은 두 파싱이 **같은 바이트 자리**를 봤다는 뜻이지 **같은 텍스트**를 봤다는 뜻이 아니다. 길이가 변하지 않는 제자리 수정(`s.con` → `s.XYZ`)은 앞의 offset 을 밀지 않으므로 **우연히 일치**하고, 바뀐 텍스트의 핸들러를 붙이면서 "증명됐다" 고 말한다. §4 가 금지한 "서로 다른 block 을 같은 식별자로 잘못 합치는" 경우다 |
| A-2 | 소스 지문만 저장 | 🟠 "같은 텍스트인가" 는 증명하지만 **블록별 짝짓기**를 못 한다. 같은 텍스트라도 어느 entry 가 어느 블록인지 말할 수단이 필요하다 |
| **A-3** | **(소스 지문, 블록 offset) 쌍** | 🟢 **채택.** 지문이 증명을 맡고 offset 이 블록별 짝짓기를 맡는다. §4-A 가 말한 "원본 script 와 block 의 위치를 결합" 이 문자 그대로 이것이다 |
| A-4 | `EffectSpec` 에 칸 추가 | 🔴 §7 금지 (`EffectSpec` 공개 API 변경) |
| A-5 | 결합 자리에서 offset 재계산 | 🔴 **순환이라 아무것도 못 잡는다** (3-F-36 `test_17` 이 증명). 두 값이 같은 텍스트에서 나오므로 정의상 일치한다 |

### 후보 B — 명시적 대응 관계

🟢 **함께 채택했다.** 대응은 **증명된 경우에만** 기록한다. `_collect_handlers`
가 각 항목에 자기 `offset` 을 담고, 결합 자리는 `(지문 일치) ∧ (offset 일치)` 일
때만 `MATCHED` 를 적는다. 증명되지 않은 블록에는 **다른 항목의 핸들러를 붙이지
않는다.**

### 후보 C — 식별 불가능 상태의 명시적 표현

🟢 채택. 기존 타입으로 표현할 수 없음을 §2.1 에서 확인했으므로 **새 enum 하나**를
만들었다 (`analysis.effect_model.HandlerBinding`). 값은 **실제로 도달하는 네
개**뿐이다. §6 이 요구한 다섯 번째 상태(파싱 자체의 실패)는 §5 에서 보듯 **도달
불가능**이어서 넣지 않았다 — 도달하지 않는 값을 미리 만들지 않는다.

### §4 가 요구한 조건 대조

| 조건 | 충족 | 근거 |
|---|---|---|
| 같은 script·block 은 반복 분석 시 같은 식별 정보 | 🟢 | `test_05` — 같은 텍스트면 카드 ID·파일명이 달라도 지문이 같다 |
| 서로 다른 block 을 같은 식별자로 합치지 않는다 | 🟢 | `test_31` — offset 이 같은 제자리 수정을 지문이 가른다 |
| offset 을 **버전 간 영구 ID 라고 주장하지 않는다** | 🟢 | 모델 docstring 과 `test_33` 이 그 한계를 못 박는다 |
| Clone 원본과 복제본의 정체성을 혼동하지 않는다 | 🟢 | Clone 자식은 **자기 offset** 을 갖고, 복제 관계는 `cloned_from` 이 따로 적는다 (`test_28`) |
| `EffectRef(card_id, ordinal)` 과 append-only ordinal 불변 | 🟢 | `test_03`·`test_44`·`test_45` (전수 34,635 참조, bad 0) |
| parser 가 증명하지 못한 관계를 analyzer 가 추측하지 않는다 | 🟢 | `test_22`·`test_23` |

---

## 4. 선택한 최소 데이터 모델과 이유

production 변경은 **5개 파일**이고, 그중 하나는 **주석만** 바뀌었다.

| 파일 | 변경 | 왜 최소인가 |
|---|---|---|
| `core/card_model.py` | `LuaScriptInfo` +2칸 (`effect_offsets`, `source_digest`) | 식별자를 담을 자리가 **어디에도 없었다**. `EffectSpec` 은 §7 이 금지했으므로 평행 목록으로 둔다 |
| `sources/lua_loader.py` | `_pos` → `pos` 로 **읽어서** 기록 · 원문 지문 계산 · 직렬화 2줄 · 캐시 signature | 값이 이미 그 자리에 있었다. 새로 계산하는 것은 지문 하나뿐이다 |
| `analysis/effect_model.py` | `HandlerBinding` enum · `EffectAnalysis.handler_binding` · `CardAnalysis.handler_binding` · `CardAnalysis.unbound_effects` | 결합 실패를 **적을 자리**가 없었다 (§2.1) |
| `analysis/effect_analyzer.py` | entry 에 `offset` 추가 · 결합을 식별자 기반으로 · 소스 없음 처리 | 결합 자리 한 곳 |
| `core/card_repository.py` | 🟠 **주석만** | 3-F-35 가 적어 둔 설명이 결합 방식이 바뀌며 사실과 어긋나게 됐다. 실행되는 줄은 **하나도** 바뀌지 않았다 (`test_52`) |

🔴 **`unbound_effects` 를 따로 둔 이유.** `effects` 와 `resolution_effects` 를
가르는 기준은 `is_registered` 이고, 그 값은 **핸들러 항목의 `function` 이름**에서
온다. 대응이 증명되지 않았다면 그 이름도 믿을 수 없고, 둘 중 하나를 고르는 순간
`False` 를 지어낸다 — 3-F-36 이 "위조" 로 기록한 바로 그 동작이다. 그래서 어느
쪽에도 넣지 않는다.

🔴 **`EffectSpec` 9칸 · `EffectRef` 2칸 · ordinal 규칙은 건드리지 않았다.**
`engine/`·`agent/`·AI/Search·Lua 원본·README 도 변경 0이다.

---

## 5. 결합 실패 상태의 구분 (§6)

| §6 이 요구한 상태 | 표현 | 도달 경로 | 테스트 |
|---|---|---|---|
| 증명되어 정상 연결 | `MATCHED` | 지문 일치 + offset 일치 | `test_13` |
| 대응 관계 불일치 | `MISMATCHED` | 지문 불일치, 또는 지문은 같은데 그 블록의 offset 이 entry 쪽에 없음 | `test_14`·`test_15`·`test_16`·`test_31` |
| 증명할 정보가 없음 | `UNPROVABLE` | 지문 `None`(낡은 캐시) · offset 평행 목록 길이 불일치 · entry offset 중복 · entry 에 offset 칸이 없음 | `test_19`·`test_20` |
| 입력 소스/handler 가 없음 | `SOURCE_MISSING` | 분석 시점에 `c*.lua` 를 못 읽음 | `test_17`·`test_18` |
| 파싱 자체가 실패함 | **표현하지 않았다** | 🔴 **도달 불가능** — `parse_lua_source` 는 정규식 기반이라 실패하지 않고, 파일을 못 읽으면 `LuaScriptSource.load()` 가 그 카드를 건너뛴다. 그 결과는 `card.script is None`(= `has_script=False`) 이고 **이미 표현된다** | `test_18` |

금지 사항 대조:

| §6 금지 | 지키는가 | 근거 |
|---|---|---|
| 길이가 같다는 이유만으로 정상 처리 | 🟢 | `test_34` — 길이 2=2 인데 `MISMATCHED` |
| 같은 이름이라는 이유만으로 정상 처리 | 🟢 | `test_35` — 이름 순서 `['e1','e2']` 까지 같은데 `MISMATCHED` |
| `None`/빈 목록을 임의로 정상 취급 | 🟢 | `test_09` — 낡은 캐시는 `[]`/`None` 로 복원되고 **0 으로 채우지 않는다** |
| 결합 실패를 조용히 무시 | 🟢 | `test_22` — 어느 목록에도 들어가지 않는다 |
| 증명 못한 관계를 `False`·빈 값·임의 ordinal 로 대체 | 🟢 | `test_23` — 남의 핸들러를 받지 않는다 |

🟢 **"handler 없는 유효 block" 은 정상으로 둔다.** §6 이 조사하라고 한 항목이다.
코퍼스에 **9,887개**(그중 미등록 6,022개)가 실재하고, 증명된 것은 **대응
관계**이지 핸들러의 존재가 아니다. 그래서 `MATCHED` + 빈 핸들러가 올바른 결과다
(`test_25`).

---

## 6. 실제 재현 사례 (§5 의 12개)

전부 `parse_lua_source` → `EffectAnalyzer.analyze` 실제 경로로 구성했다.

| # | 사례 | 결과 | 테스트 |
|---|---|---|---|
| 1 | 정상 연결 | 🟢 `MATCHED`, `e1` 조건 / `e2` 비용 | `test_13` |
| 2 | 길이 불일치 (2 vs 1) | 🔴 `MISMATCHED`, unbound 2, **오분류 없음** | `test_14` |
| 3 | 길이 같고 순서 다름 | 🔴 `MISMATCHED` | `test_15` |
| 4 | 같은 handler 이름이 두 block 에 | 🟢 `MATCHED`, offset 이 구별 | `test_27` |
| 5 | handler 없는 유효 block | 🟢 `MATCHED` + 빈 핸들러 | `test_25` |
| 6 | parser 가 인식 못한 handler | 🟢 양쪽이 똑같이 버린다 | `test_26` |
| 7 | Clone 이후 변수 재바인딩 | 🟢 블록 2개, 재바인딩은 블록도 offset 도 만들지 않는다 | `test_28` |
| 8 | 보조 함수가 Effect 생성·등록 | 🟢 블록이 아니므로 양쪽이 안 센다 | `test_29` |
| 9 | 서로 다른 `script_dir`, 같은 카드 ID | 🔴 **내용이 기준**이다 — 같으면 `MATCHED`, 다르면 `MISMATCHED` | `test_30` |
| 10 | 소스가 바뀌어 offset 이 달라짐 | 🔴 `MISMATCHED` (앞에 줄이 늘어 밀린 경우 / 뒤에 블록이 붙은 경우) | `test_32`·`test_33` |
| 10′ | 🔴 **offset 이 전혀 안 밀리는 제자리 수정** | 🔴 `MISMATCHED` — **지문만 잡는다** | `test_31` |
| 11 | 캐시 있을 때 / 없을 때 | 🟢 분석 결과가 **같다** | `test_11`·`test_12` |
| 12 | 식별 정보가 부족한 경우 | 🟠 `UNPROVABLE` — **임의 연결이 일어나지 않는다** | `test_19`·`test_20`·`test_22` |

### 6.1 사례 10′ — 이 Phase 의 핵심 근거

```lua
-- 파싱 시점
e1:SetCondition(s.con)
-- 분석 시점 (글자 수가 완전히 같다)
e1:SetCondition(s.XYZ)
```

* 길이 같다 (2=2) · 이름 순서 같다 (`['e1','e2']`) · **블록 offset 도 완전히 같다**
* 🔴 offset 만 비교했다면 `MATCHED` 라고 말하며 바뀐 텍스트의 핸들러를 붙였다
* 🟢 소스 지문이 달라 `MISMATCHED` 로 걸린다

---

## 7. Clone · 재바인딩 · 보조 함수의 영향

| 상황 | 블록 | offset | 결합 | 의미 |
|---|---|---|---|---|
| `Clone` (부모+자식) | 2 | 서로 다름 | 🟢 `MATCHED` | 자식은 **자기 자리**를 갖는 별개 블록. 복제 관계는 `cloned_from` 이 따로 적는다 — 식별자와 의미 관계를 섞지 않는다 |
| Clone 뒤 재바인딩 | 2 | 서로 다름 | 🟢 `MATCHED` | `e2=e:GetLabelObject()` 은 블록을 만들지 않으므로 offset 도 만들지 않는다. 그 뒤 `SetTarget` 은 **양쪽이 똑같이 버린다** |
| 같은 변수에 Clone 재대입 | 2 | 서로 다름 | 🟢 | 둘 다 `index == "e1"` 인데 offset 이 구별한다 |
| 보조 함수 생성 | 1 | 1 | 🟢 | 블록이 아니므로 어긋날 자리가 없다 (3-F-32 결론 유지) |
| 같은 이름 다른 함수 | 2 | 서로 다름 | 🟢 | `function` 이름이 등록 여부를 가른다 |

🟢 **ordinal 과 offset 은 같은 순서다** — append-only 규칙을 바꾸지 않았다
(전수 12,000+ 스크립트에서 `offsets == sorted(offsets)`, `test_45`).

---

## 8. 캐시 · fingerprint 영향

### 8.1 signature 를 `v9:` → `v10-<shape>:` 로 바꿨다

`LuaScriptInfo` 에 칸이 둘 생겼으므로 기존 캐시는 무효다. 올리지 않으면 낡은
캐시가 그 칸 없이 복원되어 전 코퍼스가 `UNPROVABLE` 이 된다 — **틀린 결과는
아니지만 쓸 수 없는 결과**다.

### 8.2 🔴 작업 중 실제로 겪은 사고 — 기존 테스트 113건이 깨졌다

1. `effect_offsets` 를 넣고 signature 를 `v9:` → `v10:` 으로 올렸다.
2. 그 상태로 테스트를 한 번 돌렸고, **그때 `v10:` 캐시가 디스크에 쓰였다.**
3. 이어서 `source_digest` 를 **같은 `v10:` 아래에서** 추가했다.
4. 🔴 2단계에서 쓰인 캐시는 signature 검사를 **통과하는데** `source_digest` 가
   없다. 전 코퍼스가 `UNPROVABLE` 로 복원되어 `effects` 가 모두 비었다.
5. 결과: `113 failed, 5074 passed, 7 skipped, 4 errors`.

🟢 **동작은 설계대로였다** — 증명할 수 없으니 `UNPROVABLE` 이라고 말했고, 틀린
값을 지어내지 않았다. 문제는 **그 캐시가 애초에 받아들여졌다**는 것이다.

### 8.3 그래서 signature 가 저장 모양을 **자동으로** 반영한다

```python
_CACHE_TOP_KEYS    = (... "effect_offsets", "source_digest", ...)
_CACHE_EFFECT_KEYS = ("index", ... "cloned_from")
_CACHE_SHAPE_TAG   = sha256("|".join(top) + "#" + "|".join(effect))[:8]
...
return f"v10-{_CACHE_SHAPE_TAG}:{count}:{newest:.0f}"
```

* 숫자(`v10`)는 **파서의 의미**가 바뀔 때 손으로 올린다.
* `<shape>` 는 **저장되는 칸 목록**이 바뀌면 자동으로 바뀐다.
* 🟢 이로써 Phase 3-F-30 부터 다섯 Phase 를 따라다닌 위험(**수동 승급 누락**,
  3-F-32 가 E4, 3-F-36 이 N24 로 기록)의 절반이 구조로 막혔다. 남은 절반은
  "모양은 같은데 의미가 달라진" 경우이고, 그것은 여전히 수동이다 (§11).

### 8.4 캐시 왕복

* 12,702 스크립트 전부에서 `effect_offsets` 와 `source_digest` 가 보존된다.
* 캐시로 만든 분석과 디스크에서 바로 만든 분석이 **같다** (`test_12`).
* 캐시 JSON 은 약 13.9 MB → 약 14.9 MB (지문 64자 × 12,702 + offset 목록).

---

## 9. corpus 및 검색 산출물 비교 (§8)

수정 전(`edcd96e`)과 수정 후를 **같은 측정 스크립트**로 비교했다.

| # | 비교 항목 | 기준 | 수정 후 | 결과 |
|---|---|---|---|---|
| 1 | script 수 | 12,702 | 12,702 | 🟢 |
| 2 | parser block 수 | 34,684 | 34,684 | 🟢 |
| 3 | attached block 수 | 34,635 | 34,635 | 🟢 |
| 4 | `EffectSpec` digest | `b2623fe9…8fbf3` | 동일 | 🟢 |
| 5 | `CardAnalysis` digest | `602328c9…b30509` | 동일 | 🟢 |
| 6 | 등록 Effect 수 | 26,352 | 26,352 | 🟢 |
| 7 | 해결 Effect 수 | 8,283 | 8,283 | 🟢 |
| 8 | 조건·비용·대상·행동·category 집계 | 12,438 / 5,007 / 5,516 / 18,280 / 20,484 | 동일 | 🟢 |
| 9 | 검색 결과 digest | `d57c6ae1…1b98d6` | 동일 | 🟢 |
| 10 | 검색 위치 digest | `a822e760…40375d` | 동일 | 🟢 |
| 11 | `EffectRef` 불일치 수 | 0 | 0 | 🟢 |
| + | attached card 수 | 12,687 | 12,687 | 🟢 |
| + | 검색 분류/위치 종류 | 31 / 31 | 31 / 31 | 🟢 |
| + | 3-F-32 대표 3장 | 보존 | 보존 | 🟢 |

**14개 항목 전부 동일**하다. 분류상 **의도된 수정도 회귀도 아니고 "변화 없음"**
이다 — 정상 corpus 에서는 두 목록이 전수로 같은 텍스트에서 나오므로 식별자
기반 결합이 위치 기반과 **같은 entry 를 고른다** (3-F-36 이 34,635 블록 전부에서
0 불일치를 측정했고, 이 Phase 가 다시 확인했다).

### 9.1 새 산출물의 전수 분포

| 측정 | 값 |
|---|---|
| 블록별 `handler_binding` | `MATCHED` **34,635** / 나머지 0 |
| 카드별 `handler_binding` | `MATCHED` **12,687** / 나머지 0 |
| `unbound_effects` 총합 | **0** |

🟢 정상 corpus 에서 `unbound_effects` 는 **언제나 비어 있다.** 비어 있지 않다면
캐시가 낡았거나 `script_dir` 이 어긋난 것이다.

---

## 10. 신규 · 기존 테스트 결과

### 10.1 신규

`tests/test_effect_block_handler_identity_model.py` — **54개** (§9 최소 25개).
구성: 식별자 보존·직렬화·캐시(12) · 결합 상태 5종 구분(12) · §5 사례(8) ·
금지된 결합 근거(6) · 산출물 불변성(6) · 3-F-27~36 회귀(6) · 변경 범위(3) ·
그 외 한계 기록(1).

### 10.2 기존 테스트 — 원인 분류 후 처리

🔴 **원인을 먼저 분류했다.** 기대값을 바꿔 통과시키지 않았다.

| 분류 | 건수 | 원인 | 처리 |
|---|---|---|---|
| **① 중간 캐시** | **86** | §8.2 의 사고. production 이 틀린 게 아니라 **낡은 캐시를 받아들인 것**이 문제 | 🟢 **production 을 고쳤다** (`_CACHE_SHAPE_TAG`). 이 86건은 테스트를 **한 줄도 건드리지 않고** 전부 다시 통과한다 |
| **② 캐시 signature 리터럴** | **15** | `v9:` 를 문자열로 고정한 테스트 9개 파일. 이 Phase 가 서명을 정당하게 바꿨다 | 테스트의 **주장은 그대로** 두고 (파서 산출물이 달라지면 서명도 달라져야 한다) 리터럴만 `v10-` 로 옮기고, 왜 바뀌었는지 주석으로 남겼다 |
| **③ 결함 스냅샷** | **14** | 3-F-35/3-F-36 이 **고치지 말라는 지시 아래** 결함 자체를 기록한 테스트 (`entries[position]` 가 있다 · `_pos` 를 읽지 않는다 · 조용히 뒤집힌다 · 구현하지 않았다 …) | "그때 그랬다" 를 지우지 않고 `.. note::` 로 남긴 뒤 **"지금은 이렇다"** 로 옮겨 적었다. 가정이 틀렸던 것이 아니라 **대상이 바뀌었다** |
| **④ 복제본에 식별자 누락** | **2** | 3-F-33·3-F-34 가 `_collect_handlers` 를 **복제본으로 갈아끼워** 산출물을 비교하는데, 복제본이 `offset` 을 담지 않아 비교가 "바인딩 규칙 차이" 대신 "식별자 부재" 를 재게 됐다 | 복제본에 `"offset": pos` 를 더해 **비교의 의미를 복원**했다. 더불어 production 이 `entry["offset"]` 대신 `entry.get("offset")` 을 쓰도록 고쳐, 식별자가 없는 호출자에게 **예외 대신 `UNPROVABLE`** 을 주게 했다 |

합계 86 + 15 + 14 + 2 = **117** (1차 회귀의 `113 failed + 4 errors`).

🔴 **자발적으로 고친 테스트 1건도 적어 둔다.** `test_effect_block_handler_identity_audit.py::test_03`
은 깨지지 않았다 (`EffectSpec` 쪽 9칸을 보기 때문이다). 그런데 그 제목이
"캐시 직렬화도 식별자를 담지 않는다" 여서 **사실과 어긋난 채 통과**하게
됐으므로, 깨지지 않았어도 바로잡고 새 두 칸까지 확인하도록 강화했다.

* 기존 테스트 **삭제 0 · skip 추가 0 · assertion 약화 0 · threshold 완화 0**.
* ②③④ 는 모두 **더 강한 주장으로** 바뀌었다 (예: "조용히 뒤집힌다" → "뒤집힌
  값을 주장하지 않는다 + 어느 목록에도 넣지 않는다").

### 10.3 전체 회귀

```
기준 (edcd96e)       : 5,140 passed /  4 skipped / 0 failed
1차 (중간 캐시 사고)  : 5,074 passed /  7 skipped / 113 failed / 4 errors
최종                 : (§10.4 참고)
```

---

## 11. 남은 위험과 설계 한계

| # | 내용 | 상태 |
|---|---|---|
| **N25** | 🔴 offset·지문은 **한 소스 버전 안의** 식별자다. 서로 다른 Lua 버전에서 "같은 효과" 를 식별하지는 **못한다** — 그런 식별자는 이 자료만으로 만들 수 없다. 모델 docstring 과 `test_33` 이 그 한계를 못 박는다 | **설계 한계** (§4 가 주장하지 말라고 한 것을 주장하지 않는다) |
| **N26** | 🟠 지문이 다르면 그 카드의 분석이 **전부** `MISMATCHED` 가 되어 `effects` 가 빈다. 틀린 값을 주지 않는 대신 **아무 값도 주지 않는다** | **의도된 교환** (§6). 정상 corpus 영향 0 |
| **N27** | 🟠 캐시 signature 의 **숫자 부분**은 여전히 수동이다. "저장 모양은 같은데 파서의 **의미**가 바뀐" 변경(정규식 수정 등)은 자동으로 잡히지 않는다 | N24 의 **절반만** 해결 |
| **N28** | 🟠 `_info_from_dict` 는 `EffectSpec(**e)` 를 쓰므로, 모양 태그를 우회한 손상된 캐시에 모르는 칸이 있으면 `TypeError` 가 `load_cached` 의 `except (OSError, ValueError, KeyError)` 를 **빠져나간다** | 미해결 (이 Phase 범위 밖) |
| **N29** | 🟠 `unbound_effects` 를 읽는 downstream 소비자가 **아직 없다.** 정상 corpus 에서 항상 비어 있으므로 지금은 무해하지만, 어긋남이 생겼을 때 **사람에게 보이는 경로**(CLI 경고 등)가 없다 | 미해결 → 다음 Phase 후보 |

---

## 12. 최종 판정과 다음 Phase 후보

### 최종 판정: **`IDENTITY_MODEL_VALIDATED`**

| 후보 판정 | 선택하지 않은 이유 |
|---|---|
| `IDENTITY_MODEL_PARTIALLY_VALIDATED` | §0 의 두 목표가 **모두** 측정으로 확인됐다 — 식별자가 파싱 결과에 보존되고(전수 12,702), 결합 실패가 위치 기반 fallback 없이 네 상태로 구분된다(§5·§6 의 12 사례 전부). N25 는 §4 가 **주장하지 말라고 한 한계**이므로 미달이 아니다 |
| `IDENTITY_REQUIRES_BROADER_DESIGN` | 4개 파일 · 1 enum · 5칸으로 끝났고, `EffectSpec`/`EffectRef`/engine/Lua/README 를 건드리지 않았다 |
| `UNKNOWN_FALLBACK_REQUIRED` | `UNKNOWN`(= `UNPROVABLE`)은 **필요했고 구현했다.** 다만 그것이 전부가 아니다 — "모른다" 와 "틀렸다" 를 가르는 것이 이 Phase 의 절반이다 |
| `REGRESSION_DETECTED` | 🔴 1차 회귀에서 113건이 깨진 것은 **중간 캐시** 때문이고 production 의 잘못된 동작이 아니었다 (§8.2·§10.2①). 원인을 고친 뒤 corpus 14개 항목이 **전부 동일**하다 |
| `MIXED_FINDINGS` | 결과가 섞이지 않았다. 열두 사례가 한 방향을 가리킨다 |

근거 한 줄 요약:

> 식별자는 **(소스 지문, 블록 offset) 쌍**으로 파싱 시점에 보존되고, 전수
> 12,702 스크립트에서 캐시를 왕복해도 유지되며, 정상 corpus 산출물 14개 항목을
> **하나도 바꾸지 않는다**(34,635 블록 전부 `MATCHED`, `unbound_effects` 0).
> 그리고 길이·이름·순서·offset 이 **모두 같은** 제자리 수정까지 `MISMATCHED` 로
> 걸리며, 증명하지 못한 블록은 등록/해결 어느 쪽도 주장하지 않는다.

### 다음 Phase 후보 (한 개)

**Phase 3-F-38 — `HandlerBinding` 을 사람에게 보이는 경로까지 전달 (N29)**

지금 어긋남은 **모델에만** 적힌다. `app/main.py` 의 분석 출력과
`scripts/update_cards.py` 의 요약이 `handler_binding` 과 `unbound_effects` 를
읽어 "이 카드는 핸들러 대응을 증명하지 못했다 / 캐시를 다시 만들라" 를 말하도록
한다. 조사 범위: 출력 경로가 이 값을 **무시하고 있지 않은지** 전수 확인,
`AnalysisStatus` 와의 교차 표시 방법, 그리고 `MISMATCHED` 와 `UNPROVABLE` 에
서로 다른 복구 안내(소스 확인 / 캐시 재생성)를 주는 것. 🔴 Engine V1 freeze 와
검색 계층은 건드리지 않는다.

다음 Phase 는 임의로 진행하지 않습니다.
