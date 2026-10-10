# Phase 3-F-36 — Effect 블록 / 핸들러 식별자 대응 감사

> 핵심 질문: **서로 다른 파싱 시점이나 경로에서 생성된 두 목록을, 순서나 길이에
> 의존하지 않고 동일한 Effect 단위로 정확히 연결할 수 있는가?**
>
> 답: **식별자는 존재하고 유효하다. 그런데 두 경로가 모두 그것을 버린다.**
> 쓰려면 파싱 시점에 저장해야 하고, 저장 자리를 만드는 것은 §6 이 이번 Phase 에서
> 금지한 광범위한 자료구조 변경이다. 그래서 **구현하지 않고 설계 선택지와 비용을
> 적는다.**

---

## 1. 기준 HEAD 와 테스트 결과

| 항목 | 값 | 확인 방법 |
|---|---|---|
| Phase 3-F-35 작업 commit | `5b9c0fb` | `git log` 실측 |
| Phase 3-F-35 테스트 commit | `98aa9cc` | `git log` 실측 |
| Phase 3-F-35 보고서 commit | `96b1299` | `git log` 실측 — 기준 HEAD |
| 기준 worktree | clean | `git status --short` 가 빈 출력 |
| 기준 전체 테스트 | 5,083 passed / 4 skipped / 0 failed | §8 |
| 기준 corpus 산출물 | 11개 비교 항목 전부 동일 | §6 |

§1 이 적어 준 세 SHA 와 HEAD, 기준 테스트 수, clean worktree 를 모두 실제
저장소에서 확인했다. 차이는 없었다.

이번 Phase 는 **production 코드를 한 줄도 바꾸지 않았다** (audit-only, §7 참고).
따라서 §1 의 기준 산출물이 그대로 유지되어야 하고, §6 에서 실제로 다시 측정해
확인했다.

---

## 2. 실제 parser → analyzer 연결 경로

보고서의 서술이 아니라 현재 HEAD 의 코드를 따라갔다.

### 2.1 두 목록은 **같은 파싱의 두 뷰가 아니다**

```
                 ┌─ 리포지토리 빌드 시점 ─────────────────────────────┐
c*.lua ─────────▶│ sources/lua_loader.parse_lua_source()              │
   (또는          │   → LuaScriptInfo.effects : list[EffectSpec]       │
 data/cache/     │   → card.script.effects                            │
 lua_scripts     └────────────────────────────────────────────────────┘
  .json)                                   │
                                           │ ← 목록 ①
                 ┌─ 분석 시점 ──────────────┼─────────────────────────┐
c*.lua ─────────▶│ EffectAnalyzer._read_source(file_name)             │
 (다시 읽는다)     │ EffectAnalyzer._collect_handlers(source, spans)    │
                 │   → entries : list[{"handlers", "function"}]        │
                 └────────────────────────────────────────────────────┘
                                           │ ← 목록 ②
                            결합 (analysis/effect_analyzer.py)
                 entry = entries[position] if position < len(entries) else {}
```

목록 ①은 리포지토리를 만들 때 파싱한 결과이고, **디스크 캐시에서 올 수도 있다.**
목록 ②는 분석할 때 `c*.lua` 를 **다시 읽어** 만든다. 두 텍스트가 어긋나면 길이도
순서도 어긋날 수 있다 (Phase 3-F-35 가 출하된 CLI 로 재현했다).

### 2.2 결합 자리에 식별자 비교가 없다

`analysis/effect_analyzer.py` 의 `_analyze_card`:

```python
entries = self._collect_handlers(source, spans)

for position, spec in enumerate(card.script.effects):
    entry = entries[position] if position < len(entries) else {}
    effect = self._analyze_effect(spec, entry.get("handlers", {}), functions, analysis)
    effect.is_registered = entry.get("function") == "initial_effect"
```

`entries` 를 색인하는 구문은 **단 하나**이고 그 색인은 `position` 이다 (AST 로
확인 — `test_06`). 두 목록에서 같은 `position` 을 갖는다는 것은 대응 관계의
증거가 아니다. §4 가 금지한 "목록에 index 를 붙이는 것" 이 지금 상태다.

### 2.3 `EffectSpec` / `EffectRef` 가 만들어지는 경로

* `EffectSpec` 은 `create`/`clone` 이벤트를 재생할 때 만들어지고, 9칸 전부
  Lua 상수 값이다. **자기가 어디서 왔는지 적는 칸이 없다** (`test_01`).
* `EffectRef(card_id, ordinal)` 의 `ordinal` 은 `card.script.effects` 안의
  0-기반 **목록 위치**다 (`engine/ids.py` docstring 과 `test_07`). 즉 목록
  위치로 목록 대응을 검증하는 것은 **순환**이다.

### 2.4 downstream

`CardAnalysis` → 검색/분석 계층으로 흐른다. 검색(`core/card_search.py`)은
`analysis` 를 import 하지 않고 `card.script` (= 목록 ①)만 읽는다 (Phase 3-F-34
`test_34` 가 확인했다). 그래서 **결합이 잘못되어도 검색 결과는 바뀌지 않고**,
오염은 `CardAnalysis` 와 그것을 읽는 쪽에서만 보인다 — 더 조용하다는 뜻이다.

---

## 3. 사용 가능한 식별자 후보와 생명주기

§4.2 가 물은 네 후보를 하나씩 실측했다.

| 후보 | 실제로 존재하는가 | 어디까지 살아남는가 | 판정 |
|---|---|---|---|
| **byte offset** (`m.start()`) | 🟢 **두 경로 모두** 이벤트 수집 시점에 갖고 있다 | 🔴 **그 자리에서 버려진다** | 유일한 실질 후보 |
| source span (블록 시작~끝) | 🔴 만들지 않는다 | — | 없음 |
| block ordinal | 🟢 있다 | 🟢 `EffectRef` 까지 | 🔴 목록 위치 그 자체 — 순환 |
| parser entry ID | 🔴 존재하지 않는다 | — | 없음 |

### 3.1 offset 이 버려지는 지점 — 두 곳 모두 코드로 확인했다

`sources/lua_loader.py`:

```python
events.append((m.start(), "create", m.group(2)))     # ← 여기서 갖는다
...
for _pos, kind, payload in events:                   # ← 이름이 `_pos` 다
    ...
    elif kind == "create":
        handlers = {}
        bindings[payload] = handlers                 # ← `_pos` 를 읽지 않는다
```

루프 본문 전체에서 `_pos` 를 **Load 하는 노드가 0개**다 (AST — `test_04`).

`analysis/effect_analyzer.py`:

```python
for pos, kind, payload in events:
    ...
    order.append({"handlers": handlers,
                  "function": cls._enclosing_function(pos, spans)})
```

`pos` 가 인자로 들어가는 호출은 `_enclosing_function` **하나뿐**이다 (AST —
`test_05`). 즉 analyzer 도 블록과 짝지을 때는 offset 을 쓰지 않는다.

### 3.2 자료구조와 캐시에도 자리가 없다

| 구조 | 칸 수 | offset 을 담는 칸 |
|---|---|---|
| `EffectSpec` | 9 | 없음 (`test_01`) |
| `LuaScriptInfo` | 14 | 없음 (`test_02`) |
| 캐시 JSON (`_info_to_dict`/`_info_from_dict`) | 위 두 구조를 그대로 | 없음 (`test_03`) |

캐시에서 복원된 블록은 **자기 출처 위치를 더더욱 모른다.** 캐시 signature 는
`v9:{스크립트 수}:{최신 mtime}` 이라 파서 버전을 보지 않으므로, 식별자를 넣으면
signature 를 손으로 올려야 한다 (§7 비용표).

### 3.3 offset 은 유효한 식별자인가 — 전수 측정

| 측정 | 결과 |
|---|---|
| 스크립트 수 | 12,702 |
| 재계산한 블록 offset 수 | **34,684** (= `parser_blocks`) |
| 🔴 한 스크립트 안에서 offset 이 중복된 스크립트 | **0** (`test_12`) |
| 블록 목록(`card.script.effects`)과 개수·순서 불일치 | **0** (`test_13`) |
| analyzer `entries` 와 개수 불일치 | **0** (`test_14`, 34,635 블록) |

이름으로는 구별되지 않는 두 블록도 offset 은 구별한다 — 같은 변수에 `Clone` 을
재대입하면 블록 둘 모두 `index == "e1"` 인데 offset 은 34 / 122 로 다르다
(`test_11`).

### 3.4 🔴 offset 의 한계를 정직하게 적는다

offset 은 **"한 텍스트 안의 식별자"** 이고 **"텍스트 버전 간의 식별자" 가
아니다.**

* 🟢 뒤에 블록이 더 붙어도 앞 블록의 offset 은 그대로다 (`test_15`) —
  `ordinal` 과 다른 점이다. Phase 3-F-32 가 측정한 `c4997565` 의 블록 offset
  `[199, 542, 2703, 2911, 3516]` 은 각 블록 **자신의 자리**다 (`test_31`).
* 🔴 앞에 글자가 한 줄만 들어가도 뒤의 offset 이 전부 밀린다 (`test_16`).
  그런데 **이름과 길이는 그대로다** — 그래서 이름·길이 검사는 그 차이를 못 본다.

즉 offset 은 "두 목록이 **같은 텍스트**에서 나왔는지" 를 검증하는 데 쓸 수 있고,
"서로 다른 두 버전의 텍스트에서 같은 효과를 찾아내는" 데는 쓸 수 없다. 이번
문제(캐시 노후·`script_dir` 어긋남)는 **정확히 전자**다.

---

## 4. 길이·순서 불일치 재현 결과

§5 가 요구한 열 가지 사례를 **실제 production 파싱·분석 경로**로 구성했다
(`_analyze_with` 가 `parse_lua_source` → `EffectAnalyzer.analyze` 를 그대로
호출한다). 기대값은 임의로 정하지 않고 **원본 Lua 의 의미**로 판정했다.

| # | 사례 | 길이 | 이름 순서 | 결합 결과 | 테스트 |
|---|---|---|---|---|---|
| ① | 길이·순서 일치 (정상) | 2=2 | 같다 | 🟢 올바르다 | `test_19` |
| ② | 길이가 다르다 (2 vs 1) | 2≠1 | — | 🔴 `e1` 이 남의 핸들러, `e2` 는 빈 dict → **미등록 오분류** | `test_20` |
| ③ | **길이 같고 이름 순서까지 같다** | 2=2 | **같다** | 🔴 **조건/비용이 정확히 뒤바뀐다** | `test_21` |
| ④ | 길이 같고 순서만 다르다 | 2=2 | 다르다 | 🔴 뒤바뀐다 | `test_22` |
| ⑤ | handler 없는 유효 블록 | 1=1 | 같다 | 🟢 네 슬롯이 비는 것이 정답 | `test_23` |
| ⑥ | parser 가 인식 못한 handler | 1=1 | 같다 | 🟢 **양쪽이 똑같이 버린다** | `test_24` |
| ⑦ | 같은 handler 이름이 두 블록에 | 2=2 | 같다 | 🔴 핸들러 dict 가 글자까지 같다 → 이름은 식별자가 못 된다 | `test_25` |
| ⑧ | 생성 후 변수 재바인딩 | 1=1 | 같다 | 🟢 블록이 안 생기므로 offset 도 안 생긴다 | `test_26` |
| ⑨ | `Clone` | 2=2 | 같다 | 🟢 부모/자식이 **다른 offset**, 관계는 `cloned_from` | `test_27` |
| ⑩ | 보조 함수가 Effect 생성·등록 | 1=1 | 같다 | 🟢 블록이 아니므로 양쪽이 똑같이 안 센다 | `test_28` |
| + | Phase 3-F-32~35 대표 회귀 | — | — | 🟢 전부 보존 | `test_30`~`test_33` |

### 4.1 🔴 §4.5 의 결정적 답 — **"길이와 index 로는 절대 못 잡는 사례가 있다"**

사례 ③이 §4.5 가 물은 바로 그것이다.

파싱 시점의 Lua (목록 ①이 여기서 나온다):

```lua
function s.initial_effect(c)
    local e1=Effect.CreateEffect(c)
    e1:SetCode(EVENT_FREE_CHAIN)
    e1:SetCondition(s.con)        -- e1 = 조건
    c:RegisterEffect(e1)
    local e2=Effect.CreateEffect(c)
    e2:SetCode(EVENT_TO_HAND)
    e2:SetCost(s.cost)            -- e2 = 비용
    c:RegisterEffect(e2)
end
```

분석 시점에 디스크에 있던 Lua (목록 ②가 여기서 나온다):

```lua
--이 카드의 효과를 다시 쓴 버전
--줄이 늘어 offset 이 밀린다
function s.initial_effect(c)
    local e1=Effect.CreateEffect(c)
    e1:SetCode(EVENT_FREE_CHAIN)
    e1:SetCost(s.cost)            -- 🔴 뒤바뀌었다
    c:RegisterEffect(e1)
    local e2=Effect.CreateEffect(c)
    e2:SetCode(EVENT_TO_HAND)
    e2:SetCondition(s.con)        -- 🔴 뒤바뀌었다
    c:RegisterEffect(e2)
end
```

| 검사 | 통과하는가 |
|---|---|
| 길이 (2 vs 2) | 🟢 통과 — 못 잡는다 |
| `EffectSpec.index` 순서 (`['e1','e2']` vs `['e1','e2']`) | 🟢 통과 — 못 잡는다 |
| 핸들러 함수 이름 집합 (`{s.con, s.cost}`) | 🟢 통과 — 못 잡는다 |
| 🔴 **파싱 시점에 저장한 offset** (`[34,155]` vs `[75,192]`) | 🔴 **잡는다** |

실제 분석 결과는 정확히 뒤집힌다 — `e1` 이 `cond=False/cost=True`,
`e2` 가 `cond=True/cost=False` (`test_21`). 예외도 경고도 로그도 없다
(`test_40`).

### 4.2 🔴 Phase 3-F-35 가 적어 둔 다음 단계 후보는 **순환이라 아무것도 못 잡는다**

3-F-35 보고서는 "자료구조 변경 없이 `_analyze_card` 가 블록 offset 을 다시
계산" 하는 방안을 다음 후보로 적었다. 실제로 돌려 봤다.

| 방안 | 블록 offset | entries offset | 결과 |
|---|---|---|---|
| A. 결합 자리에서 **재계산** | `[75, 192]` | `[75, 192]` | 🔴 **언제나 같다** — 둘 다 같은 디스크 텍스트에서 나온다. 불일치를 **못 잡는다** (`test_17`) |
| B. **파싱 시점에 저장**한 값과 비교 | `[34, 155]` | `[75, 192]` | 🟢 **다르다 — 잡는다.** 교집합이 비어 있어 "짝이 없다" 고 말할 수 있다 (`test_18`) |

재계산은 정의상 자기 자신과 비교하는 것이다. 식별자는 **파싱 시점에
저장되어야만** 쓸모가 있다. 이것이 이번 Phase 의 가장 중요한 발견이고,
판정을 `IDENTITY_REQUIRES_DATA_MODEL_CHANGE` 로 이끈 근거다.

---

## 5. Clone · 재바인딩 · 보조 함수의 영향 (§4.4)

§4.4 는 "식별자가 유지되어도 의미상 동일한 Effect 로 볼 수 있는가" 를 물었다.
여섯 가지 의미 상황을 전부 구성해 측정했다.

| 상황 | 블록 | offset | 고유 | 1:1 | 의미 |
|---|---|---|---|---|---|
| `Clone` (부모+자식) | 2 | 34 / 122 | 2 | 🟢 | 자식은 **자기 자리**를 갖는 별개 블록. 복제 관계는 `cloned_from` 이 따로 적는다 |
| 같은 변수에 `Clone` 재대입 | 2 | 34 / 122 | 2 | 🟢 | 이름이 둘 다 `e1` 인데 offset 이 구별한다 |
| 생성 후 재바인딩 | 1 | 34 | 1 | 🟢 | 블록이 안 생기므로 **offset 도 안 생긴다** — 기존 블록의 자리·부모 관계 불변 (3-F-34) |
| 보조 함수가 Effect 생성 | 1 | 129 | 1 | 🟢 | 블록이 아니므로 **양쪽이 똑같이 안 센다** |
| 같은 이름이 다른 함수에 | 2 | 34 / 146 | 2 | 🟢 | offset 이 구별하고 `function` 이 등록 여부를 가른다 |
| 같은 handler 이름이 두 블록에 | 2 | 34 / 125 | 2 | 🟢 | 핸들러 이름은 식별자가 못 되지만 offset 은 된다 |

**§4.4 의 답: offset 이 같다는 것은 "같은 블록" 이라는 뜻이고, "의미상 같은
Effect" 라는 뜻이 아니다.** 그리고 그 구분은 이미 모델에 있다 —

* `Clone` 자식은 부모와 **다른 offset** 을 갖고, 두 블록이 의미상 연결돼 있다는
  사실은 `cloned_from` 이 **별도 칸**에 적는다. 식별자와 의미 관계가 섞이지
  않는다 (`test_27`, `test_30`).
* 재바인딩은 `order` 를 건드리지 않으므로 **기존 블록의 ordinal 도 offset 도
  바꾸지 않는다** (3-F-34 의 불변 조건이 그대로 유지된다 — `test_26`).
* 보조 함수가 만든 Effect 는 두 경로가 **똑같이 블록으로 세지 않는다.**
  따라서 어긋날 자리가 애초에 없다 (Phase 3-F-32 의 결론 유지 — `test_28`).

즉 offset 을 식별자로 쓰는 것이 Clone·재바인딩·보조 함수의 의미를 **훼손하지
않는다** (§6 조건 3을 만족한다).

---

## 6. corpus 산출물 및 검색 결과 비교 (§4.6 · §7)

### 6.1 식별자 기반 연결을 **실제로 적용**해 전수 재측정했다

`_analyze_card` 를 **offset 키 결합**으로 바꿔 끼우고(파싱 시점 offset 을
저장하는 안 B 를 흉내낸 것), 기준과 같은 11개 항목을 다시 지문화했다.

| 연결 통계 | 값 |
|---|---|
| 짝지어진 블록 | **34,635** (= 전부) |
| 짝을 못 찾은 블록 | **0** |
| offset 이 중복된 카드 | **0** |
| 🔴 위치 기반과 **다른 entry** 를 고른 블록 | **0** |

고른 entry 가 위치 기반과 **객체까지 동일**했다 (`test_34`). 그러므로:

| 비교 항목 | 기준 (`96b1299`) | offset 키 결합 | 결과 |
|---|---|---|---|
| `scripts` | 12,702 | 12,702 | 🟢 |
| `parser_blocks` | 34,684 | 34,684 | 🟢 |
| `attached_cards` | 12,687 | 12,687 | 🟢 |
| `attached_blocks` | 34,635 | 34,635 | 🟢 |
| `effectspec_digest` | `b2623fe9…8fbf3` | `b2623fe9…8fbf3` | 🟢 |
| `cardanalysis_digest` | `602328c9…0b30509` | `602328c9…0b30509` | 🟢 |
| `analysis_totals` | registered 26,352 · resolution 8,283 · cond 12,438 · cost 5,007 · target 5,516 · action 18,280 · cat 20,484 | 동일 | 🟢 |
| `effectref_total` / `effectref_bad` | 34,635 / **0** | 34,635 / **0** | 🟢 |
| `search_category_digest` | `d57c6ae1…1b98d6` | 동일 | 🟢 |
| `search_location_digest` | `a822e760…40375d` | 동일 | 🟢 |
| `search_categories` / `search_locations` | 31 / 31 | 31 / 31 | 🟢 |

**§4.6 의 답: 바뀌지 않는다.** 정상 corpus 에서 두 목록은 전수로 같은 텍스트에서
나오므로, 식별자 기반 연결이 바꾸는 것은 산출물이 아니라 **어긋났을 때의
행동**이다.

### 6.2 이 Phase 가 production 을 바꾸지 않았음을 다시 측정했다

`docs/`·`tests/` 밖을 건드리지 않았으므로 기준 지문이 유지되어야 한다. §8 의
전체 테스트가 같은 11개 항목(`test_34`~`test_36`, `test_44`)을 다시 산출해
확인했고, 별도로 지문 스크립트를 최종 HEAD 에서 다시 돌려 기준과 **14개 항목
전부 일치**를 확인했다.

### 6.3 §7 의 나머지 불변 조건

| 항목 | 확인 | 테스트 |
|---|---|---|
| 기존 `ordinal` | 전수 `range(len)` 유지 | `test_07`, `test_44` |
| `EffectRef(card_id, ordinal)` 설계 | 34,635 참조 전부 해석 성공, bad 0 | `test_44` |
| `EffectSpec` / `EffectRef` API | 9칸 / 2칸 그대로 | `test_43` |
| 검색 결과와 순위 | 두 digest 일치 | `test_36` |
| `state_hash` · RNG · hidden-information | `canonical_state` 가 `script`/`effects`/`ordinal` 을 보지 않는다 (AST) | `test_45` |
| Engine V1 freeze | `EFFECT_LIBRARY` 16개, 전부 `ordinal 0` | `test_46` |
| 캐시 signature | `v9:` 그대로 (파서 결과 무변경) | `test_42` |
| Lua 파일 · README · `engine/` · `agent/` | 변경 0 | `test_48` |
| skip 수 | 4 유지 | §8 |

---

## 7. 수정 여부와 근거 — **audit-only**

### 7.1 §6 의 다섯 조건을 하나씩 대조했다

| 조건 | 충족 | 근거 |
|---|---|---|
| 1. 잘못된 연결이 실제로 재현됨 | 🟢 | `test_20`~`test_22` — 길이가 달라도, 같아도, 이름 순서까지 같아도 조용히 뒤바뀐다 |
| 2. 식별자 후보가 원본 소스와 Effect 를 안정적으로 연결함 | 🟢 | `test_12`~`test_14` — 전수 중복 0, 양쪽 목록과 1:1 |
| 3. Clone·재바인딩 의미를 훼손하지 않음 | 🟢 | §5 — 여섯 상황 전부 1:1, 복제 관계는 `cloned_from` 이 따로 적는다 |
| 4. **최소 변경으로** 연결 오류를 방지할 수 있음 | 🔴 **아니다** | 재계산은 순환이라 탐지 0 (`test_17`). 실효가 있으려면 파싱 시점 저장이 필요하고, 그것은 자료구조·캐시·분석기 네 곳을 동시에 바꾼다 |
| 5. 정상 corpus 산출물과 downstream 영향이 측정됨 | 🟢 | §6 — 11개 항목 전부 동일 |

조건 4가 충족되지 않는다. 그리고 §6 은 명시적으로 **"식별자 도입이 자료구조의
광범위한 변경을 요구한다면 이번 Phase 에서는 구현하지 말고 설계 선택지와 비용을
보고한다"** 고 했다. 그래서 **production 을 바꾸지 않았다** (`test_41`).

### 7.2 설계 선택지와 비용

#### 안 A — `EffectSpec` 에 `offset` 칸을 더한다

🔴 **§6 이 금지했다** ("`EffectSpec`, `EffectRef` API 변경"). 금지가 아니었더라도
비용이 크다 — 9칸 → 10칸, 캐시 JSON 양방향, `EffectSpec(**e)` 복원, 위치 인자로
`EffectSpec` 을 만드는 모든 테스트 픽스처, 그리고 지문 비교의 튜플 모양까지
바뀐다. **채택하지 않는다.**

#### 안 B — `LuaScriptInfo` 에 병렬 목록을 더한다 (🟢 유일하게 실효 있는 안)

```
LuaScriptInfo.effect_offsets: list[int]     # effects 와 같은 길이, 같은 순서
```

바뀌는 곳과 비용:

| 바뀌는 곳 | 내용 | 비용 |
|---|---|---|
| `sources/lua_loader.py` | `LuaScriptInfo` 14칸 → 15칸. `create`/`clone` 분기에서 `_pos` 를 **읽어** 기록 (지금은 이름이 `_pos` 다) | 작다 — 값이 이미 그 자리에 있다 |
| `_info_to_dict` / `_info_from_dict` | 새 칸 직렬화·복원 | 작다 |
| 캐시 signature | `v9:` → `v10:` — **전 코퍼스 1회 재파싱** (12,702 스크립트). signature 는 파서 버전을 보지 않으므로 손으로 올려야 한다 | 중간 — 과거 다섯 Phase 와 같은 수동 절차 |
| `EffectAnalyzer._collect_handlers` | entry 에 `offset` 을 함께 담는다 | 작다 — `pos` 가 이미 루프 변수다 |
| `EffectAnalyzer._analyze_card` | 결합을 offset 키로 바꾸고, **짝이 없을 때의 행동**을 정한다 | 🔴 **여기가 진짜 비용** — §4.7 참고 |
| `analysis/effect_model.py` | 짝이 없음을 표현하는 자리 신설 | 🔴 모델 변경 |

🔴 **정상 corpus 산출물은 바뀌지 않는다** (§6.1 에서 전수로 0 을 측정했다).
바뀌는 것은 어긋났을 때의 행동뿐이다.

#### 안 C — 길이 + 이름 순서만 검사한다 (자료구조 무변경)

비용은 거의 없다. 그런데 `test_21` 이 **길이도 이름 순서도 같은데 의미가
뒤바뀌는 사례**를 실제로 만들었으므로 그 경우를 못 잡는다. 그리고 §6 이 금지한
"index 또는 길이만으로 동일성을 가정하는 것" 에 닿는다. 지금 코퍼스에서는 전수
일치라 **탐지 건수도 0** 이다. **"고쳤다" 고 주장할 수 없는 변경이므로 하지
않았다.**

#### 안 D — 결합 자리에서 offset 을 재계산한다 (3-F-35 의 후보)

🔴 **순환이라 아무것도 못 잡는다** (`test_17`). **기각한다.**

### 7.3 §4.7 — 식별자를 쓸 수 없을 때 `UNKNOWN` 이 타당한가

**타당하다. 그리고 지금 production 이 하는 일은 `UNKNOWN` 이 아니다.**

짝을 못 찾았을 때 쓰이는 빈 dict 는 "모른다" 가 아니라 다음을 **적극적으로
주장**한다 (`test_37` 이 실제 값으로 못 박았다).

```
has_condition  False      costs      []        selection  None
condition_raw  None       actions    []        unparsed   []
is_registered  False
```

🔴 그 모양은 코퍼스에 **실재하는 블록들과 글자까지 같다** — 핸들러가 비어 있는
블록이 **9,887개**, 그중 미등록이 **6,022개** 다 (`test_38`, 전수 측정). 즉
잘못 붙은 블록은 downstream 에서 진짜 빈 블록과 **구별할 수 없다.** 침묵이
아니라 **위조**다. 이것은 "unknown 을 임의로 true/false 로 처리하는 구조를
만들지 마라" 는 기준에 정면으로 어긋난다.

모델이 못 하는 것도 아니다 — `ActivationCondition` 은 이미
`has_condition_function` 과 `unparsed` 로 **"있었는데 못 읽었다"** 를 말할 수
있다. 없는 것은 **결합 자리의 `UNKNOWN`** 이다 (`test_39`). 그래서 안 B 를
실행할 때 "짝이 없음" 은 반드시 **표현되어야** 하고, 빈 dict 로 대체되면 안
된다.

---

## 8. 신규·기존 테스트 결과

신규 파일: `tests/test_effect_block_handler_identity_audit.py` — **57개**
(§8 이 요구한 최소 25개의 두 배 이상).

문자열 존재 검사로 수를 채우지 않았다. 구성:

| 묶음 | 수 | 내용 |
|---|---|---|
| A. §4.1/§4.2 식별 정보의 존재와 생명주기 | 9 | AST 로 `_pos`/`pos` 의 사용처를 추적, 자료구조 칸 열거, 캐시 왕복 |
| B. offset 의 유효성 | 9 (parametrize 8 포함 16) | 전수 중복 0, 양쪽 1:1, 삽입 안정성과 **편집 비안정성**, 순환 증명 |
| C. §5 열 가지 재현 | 15 | 전부 `parse_lua_source` → `EffectAnalyzer.analyze` 실경로 |
| D. §4.6 산출물 | 3 | 전수 offset 키 결합, 분석 총계, 검색 digest |
| E. §4.7 UNKNOWN | 4 | 빈 dict 가 주장하는 값, 구별 불가능성, 모델의 UNKNOWN 자리 |
| F. §6/§7 audit-only 와 불변 조건 | 10 | production 무변경, API·freeze·Lua·README |

> 🔴 작성 중 내 테스트 셋에서 세 건이 틀렸고, **기대값을 고쳐 통과시키지 않고
> 테스트를 고쳤다.**
> 1. `test_06` — 금지 토큰에 `"span"` 을 넣었는데 `_analyze_card` 에는
>    `spans` (함수 경계 목록) 가 **정당하게 있다.** 문자열 검사를 버리고 AST 로
>    `entries` 의 색인이 `position` 하나뿐임을 확인하도록 고쳤다.
> 2. `test_30` — `PHASE32_CARDS` 두 번째 원소를 "몇 번째 블록" 으로 읽었는데
>    실제로는 **0-기반 ordinal** 이다. 상수의 뜻을 실측해 색인을 고쳤다.
> 3. `test_47` — `"dataflow"` 를 금지 토큰으로 썼는데, 로더 주석에 **"Lua
>    dataflow 를 구현하지 않는다"** 라는 문장이 실제로 있다. 문자열로 판정하면
>    정반대 결론이 난다. import 와 정의된 이름을 AST 로 보도록 고쳤다.
>
> 세 건 모두 "이름이 겹치는 문자열로 부재를 주장하지 말 것" 이라는 같은 함정이다.

전체 회귀:

```
기준 (96b1299) : 5,083 passed /  4 skipped / 0 failed
이번 Phase     : 5,140 passed /  4 skipped / 0 failed   (+57, 전부 신규)
```

* 기존 테스트 **삭제 0 · skip 추가 0 · assertion 약화 0 · threshold 완화 0**
  (`test_49` 가 commit diff 로 확인한다).
* 기존 테스트를 **한 건도 수정하지 않았다** — production 이 그대로이므로 고칠
  이유가 없었다.
* skip 4건은 기준과 **같은 4건**이다.

---

## 9. 남은 구조적 위험

| # | 위험 | 상태 | 근거 |
|---|---|---|---|
| **N20** | 🔴 결합이 여전히 **위치 기반**이다. 두 목록이 다른 텍스트에서 나오면 길이가 같아도, 이름 순서가 같아도 조용히 뒤바뀐다 | **미해결** (설계 변경 필요) | `test_21`, `test_22` |
| **N21** | 🔴 짝을 못 찾은 블록이 `UNKNOWN` 이 아니라 **"조건·비용·처리 없음, 미등록"** 으로 위조된다. 그 모양은 실재하는 6,022개와 구별되지 않는다 | **미해결** (모델 변경 필요) | `test_37`, `test_38` |
| **N22** | 🔴 식별자(byte offset)가 두 경로에 **존재하는데 둘 다 버린다**. 저장 자리가 자료구조·캐시 어디에도 없다 | **미해결** (안 B 필요) | `test_04`, `test_05`, `test_01`~`test_03` |
| **N23** | 🟠 offset 은 **한 텍스트 안의** 식별자다. 서로 다른 Lua 버전 사이에서 같은 효과를 식별하지는 못한다 | **설계 한계** (이번 문제에는 충분) | `test_16` |
| **N24** | 🟠 캐시 signature 가 파서 버전을 보지 않아 파서를 고칠 때마다 손으로 올려야 한다. 안 B 는 `v10:` 승급이 필수다 | 미해결 (3-F-30 부터 이어진 위험) | `test_42` |
| N18/N19 (3-F-35) | 길이 계약 부재 · 조용한 오연결 | **N20/N21 로 승계** | — |

🟢 **지금 피해는 없다.** 정상 corpus 전수에서 두 목록이 같은 텍스트에서 나오고
offset 이 1:1 로 맞으므로, 위 위험은 모두 **캐시가 낡거나 `script_dir` 이
어긋날 때** 발현된다. Phase 3-F-35 가 `script_dir` 경로를 막았지만, 캐시 노후
경로는 그대로 열려 있다.

---

## 10. 최종 판정과 다음 Phase 후보

### 최종 판정: **`IDENTITY_REQUIRES_DATA_MODEL_CHANGE`**

| 후보 판정 | 선택하지 않은 이유 |
|---|---|
| `IDENTITY_ALIGNMENT_ENFORCEABLE` | 🔴 **지금 구조로는 강제할 수 없다.** 결합 자리에서 재계산하면 순환이라 탐지 0 (`test_17`). 강제하려면 파싱 시점 저장이 필요하다 |
| `IDENTITY_AVAILABLE_BUT_SEMANTICS_UNCERTAIN` | 🔴 의미는 **불확실하지 않다.** Clone·재바인딩·보조 함수 여섯 상황 전부에서 offset 이 블록과 1:1 이고, 복제 관계는 `cloned_from` 이 따로 적는다 (§5) |
| `UNKNOWN_REQUIRED_WHEN_IDENTITY_ABSENT` | 🔴 식별자가 **없는 것이 아니다** — 두 경로가 모두 갖고 있다가 **버린다.** `UNKNOWN` 이 필요하다는 것은 이 판정의 **부분 결론**이며(§7.3), 전체를 가리키지 않는다 |
| `MIXED_FINDINGS` | 🔴 결과가 섞이지 않았다. 일곱 질문이 **한 방향**을 가리킨다 — 식별자는 있고 유효하고 의미를 훼손하지 않는데, **저장 자리가 없다** |

선택한 판정의 근거 한 줄 요약:

> byte offset 은 두 경로에 실재하고(🟢), 전수에서 중복 0·양쪽 1:1 이고(🟢),
> Clone·재바인딩의 의미를 훼손하지 않고(🟢), 적용해도 정상 corpus 산출물을
> 바꾸지 않는다(🟢). 그런데 **두 경로가 모두 그 값을 버리고**, 결합 자리에서
> 다시 계산하는 것은 순환이다(🔴). 따라서 정확한 연결은 `LuaScriptInfo` ·
> 캐시 직렬화 · 캐시 signature · 결합 자리 · `UNKNOWN` 표현을 함께 바꾸는
> **자료구조 변경을 요구한다.** §6 은 그 경우 구현하지 말고 보고하라고 했다.

### 다음 Phase 후보 (한 개)

**Phase 3-F-37 — 파싱 시점 블록 식별자 저장과 결합 자리의 `UNKNOWN` 도입 (안 B)**

* `LuaScriptInfo` 에 `effects` 와 같은 길이·순서의 블록 offset 병렬 목록을
  더한다 (`EffectSpec` 은 건드리지 않는다 — §6 유지).
* `_info_to_dict`/`_info_from_dict` 에 직렬화를 더하고 캐시 signature 를
  `v9:` → `v10:` 로 올려 **1회 전수 재파싱**한다.
* `_collect_handlers` 가 entry 에 offset 을 함께 담고, `_analyze_card` 가
  **offset 키로** 결합한다.
* 🔴 **짝이 없을 때 빈 dict 로 대체하지 않는다.** "핸들러를 확인하지 못했다" 를
  표현하는 자리를 만들고, `has_condition=False` 같은 **부재 주장을 하지
  않는다.** 이것이 이 후속 Phase 의 본질이다.
* 착수 전제: 정상 corpus 11개 항목이 **전부 동일**하게 유지되는지 측정하고
  (§6.1 이 0 을 예측한다), 어긋남이 생기는 합성 사례에서는 `UNKNOWN` 이
  나오는지 확인한다.

다음 Phase 는 임의로 진행하지 않습니다.
