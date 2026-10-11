# Phase 3-F-40 — `AnalysisStatus.LUA_VERIFIED` 의미 및 Provenance 경계 감사

핵심 질문: **Lua 가 존재·파싱되었다는 사실**과 **분석 결과가 Lua 원문으로
검증되었다는 사실**을 시스템이 구분하는가.

**구분하지 않았다.** 그리고 그 사실이 사용자에게 `Lua 검증됨 12,687장` 이라는
문장으로 나가고 있었다.

---

## 1. 기준 상태

| 항목 | 값 |
|---|---|
| 브랜치 | `claude/pensive-goodall-te1egy` |
| HEAD | `f61f5ad` (= `origin/claude/pensive-goodall-te1egy`) |
| worktree | clean |
| 3-F-39 작업 / 테스트 / 보고서 / 보고서 수정 | `6d1b280` · `53202a5` · `87eb10f` · `f61f5ad` — **네 SHA 모두 실존** |
| 기준 전체 테스트 | `5,277 passed / 4 skipped / 0 failed` (3-F-39 가 `87eb10f` 에서 실측) |
| 기준 corpus | 18개 비교 항목 — 이번 Phase 가 4개를 더해 22개로 다시 떴고, 기존 18개는 전부 동일 |

`f61f5ad` 는 `87eb10f` 와 **문서 한 파일만** 다르다 (`git diff --numstat` 확인).
기존 commit 을 rewrite/amend 하지 않았다.

---

## 2. `LUA_VERIFIED` 의 실제 정의와 생성 경로

### 2.1 생성 자리는 한 곳, 조건은 하나

AST 로 "`*.analysis_status` 에 **대입**하는" production 자리를 전수 조사했다
(문자열 검색이 아니다). 결과: **`core/card_repository.py` 의 4줄뿐**이고 모두
`CardRepository._record_provenance` 안의 서로 다른 분기다 (`test_01`).

```python
if card.script is not None:
    availability.lua_available = True
    availability.effect_analysis_available = True
    record.record("effect_analysis", SourceKind.LUA)
    record.analysis_status = AnalysisStatus.LUA_VERIFIED    # ← 조건은 이것 하나
elif not card.has_printed_effect:
    record.analysis_status = AnalysisStatus.NO_EFFECT
elif card.desc:
    record.analysis_status = AnalysisStatus.TEXT_DERIVED
else:
    record.analysis_status = AnalysisStatus.UNAVAILABLE
```

즉 `LUA_VERIFIED` 의 **유일한** 조건은 `card.script is not None` 이다.
`_record_provenance` 는 분석기를 import 하지도, 부르지도 않는다 — AST import
검사와 토큰 검사로 확인했다 (`test_03`).

### 2.2 §2 의 여덟 질문

| # | 질문 | 실측 답 (파일·함수) |
|---|---|---|
| ① | 어느 조건에서 생성되는가 | `card.script is not None` **하나**. `core/card_repository.py` `CardRepository._record_provenance` (`test_01`, `test_02`) |
| ② | 존재 / 읽기 성공 / 파싱 / 블록 식별 / 원문 일치가 구분되는가 | **구분되지 않는다.** 이 상태는 **첫 번째(존재)만** 본다. 읽기 성공은 `EffectAnalyzer._read_source`, 파싱은 `sources.lua_loader.parse_lua_source`, 블록 식별은 `effect_offsets`, 원문 일치는 `source_digest` 로 각각 **다른 계층에서** 판정된다 (`test_05`, `test_11`) |
| ③ | `MATCHED` 와 `LUA_VERIFIED` 의 관계 | **아무 코드도 둘을 연결하지 않는다.** `card_repository.py` 의 실행 코드에 `HandlerBinding` 이 없고, `EffectAnalyzer._analyze_card` 에 `AnalysisStatus` 가 없다 (`test_10`, AST). 상태는 build 시점, 결합은 analyze 시점이고 근거도 다르다 |
| ④ | `UNPROVABLE`·`SOURCE_MISSING` 과 동시에 성립하는가 | **성립한다.** 다섯 사례 전부 `LUA_VERIFIED` 다 (`test_06`). 의미: "근거는 붙어 있는데 그 근거와의 대응을 증명하지 못했다" |
| ⑤ | 텍스트 분석이 Lua 검증으로 표시될 수 있는가 | **없다.** `TEXT_DERIVED` 는 `card.script is None` 일 때만 붙고, 상태를 재대입·승격하는 분기가 없다 (`test_15`, `test_17`). 🔴 다만 `TextEffectAnalyzer` 는 **production 호출자가 0개**다 (`test_16`) — 그러니 "텍스트 유래" 도 분석 결과가 아니라 근거 표시다 |
| ⑥ | 카드 단위와 블록 단위가 다른 의미로 쓰이는가 | **그렇다.** `CardAnalysis.handler_binding` 은 블록 중 **가장 심각한 값**이고, 블록별 값은 개별이다 (`test_24`). 블록이 0개인 카드의 `MATCHED` 는 "증명했다" 가 아니라 "어긋날 자리가 없다" 다 (`test_25`) |
| ⑦ | 캐시·직렬화를 지나며 잘못 유지·승격되는가 | **승격은 없다** — `CardProvenance` 에 직렬화 메서드가 없고, Lua 캐시와 source_manager 상태 파일에도 저장되지 않아 매 `build()` 마다 새로 계산된다 (`test_21`, `test_23`). 🔴 **유지는 된다** — `card.script` 가 낡은 캐시에서 오면 파일이 사라진 뒤에도 상태는 `LUA_VERIFIED` 이고 증명만 `SOURCE_MISSING` 이 된다 (`test_22`) |
| ⑧ | provenance 가 소비자에게 보존되는가 | **대부분 소실된다.** `analysis_status` 를 읽는 production 자리는 세 곳(`core/provenance.py`·`scripts/update_cards.py`·`app/main.py` — 세 번째는 이 Phase 가 추가)뿐이고, `CardProvenance.describe_ko()` 는 **production 호출자가 0개**다. 필드별 출처·충돌 기록과 6개 availability 플래그는 만들어서 카드에 달아 두기만 하고 **어떤 화면에도 나오지 않는다** (`test_18`, `test_19`, `test_20`) |

---

## 3. `HandlerBinding` 과의 관계 — 서로 다른 계층

| | `AnalysisStatus` | `HandlerBinding` |
|---|---|---|
| 재는 것 | **어느 소스가 근거인가** | **그 소스와의 대응을 증명했는가** |
| 정해지는 시점 | `CardRepository.build()` | `EffectAnalyzer.analyze()` |
| 근거 | `card.script is not None` | `(source_digest, effect_offsets)` 쌍 재검증 (3-F-37) |
| 단위 | 카드 | 블록 (+ 카드 단위 최악값 요약) |
| 생성 자리 | `_record_provenance` 4줄 | `_analyze_card` 의 결합 루프 |

§3 이 나열한 개념에 현재 모델을 대응시키면:

| 개념 | 현재 모델에서 표현되는가 |
|---|---|
| `SOURCE_PRESENT` | ✔ `AnalysisStatus.LUA_VERIFIED` / `availability.lua_available` |
| `SOURCE_READABLE` | ✔ `HandlerBinding.SOURCE_MISSING` 의 반대쪽 |
| `PARSE_SUCCESS` | △ 별도 표현 없음 — `parse_lua_source` 는 실패하지 않고, 결과가 빈 것은 `script.effects == []` 로만 나타난다 |
| `HANDLER_MATCHED` | ✔ `HandlerBinding.MATCHED` |
| `LUA_VERIFIED` (= 의미적 검증) | ✘ **표현 수단이 없다** — §6 참고 |
| `UNPROVABLE` | ✔ `HandlerBinding.UNPROVABLE` |
| `SOURCE_MISSING` | ✔ `HandlerBinding.SOURCE_MISSING` |

🔴 **그래서 새 enum 을 만들지 않았다.** 일곱 개 중 여섯 개는 이미 표현된다.
표현되지 않는 하나(의미적 검증)는 **만들어낼 수 없는 사실**이다 — §6.

---

## 4. provenance 전파 경로

```
cards.cdb / c*.lua / 한국어 DB
        │
        ▼  CardRepository.build()
   _record_provenance()  ──▶  card.provenance : CardProvenance
        │                        ├─ analysis_status  ──┐
        │                        ├─ availability (6)   │  (아무 화면에도 안 나옴)
        │                        └─ fields{} + conflicts ┘  (아무 화면에도 안 나옴)
        │
        ├──▶ scripts/update_cards.py  summarise()      : analysis_status 만
        ├──▶ app/main.py              cmd_analyze()    : analysis_status 만 ← 이 Phase 가 추가
        └──▶ core/provenance.py       describe_ko()    : 호출자 0개 (사실상 사문)

c*.lua  ──▶ EffectAnalyzer.analyze()  ──▶ HandlerBinding  (완전히 별도 경로)
```

`engine/` 과 `agent/` 는 `analysis_status` 를 **읽지 않는다**(전수 확인).
`engine/effect/definition.py` 는 자기 provenance 를 따로 두고, 주석에서
"`core.provenance.AnalysisStatus` 와 나란한 개념이지만 같은 것이 아니다" 라고
스스로 밝힌다.

---

## 5. 사례별 상태와 기대 결과

여덟 사례 전부 **실제 production 함수**로 돌렸다
(`CardRepository._record_provenance` + `EffectAnalyzer.analyze`).

| # | 입력 조건 | `AnalysisStatus` | `HandlerBinding` | effects/해결/미증명 | 사용자에게 보였던 것 | 기대 | 차이 |
|---|---|---|---|---|---|---|---|
| ① | 정상 Lua·정상 결합 | `lua_verified` | `matched` | 2/0/0 | "Lua 검증됨" | 맞음 | 없음 |
| ② | Lua 있음·지문 불일치 | `lua_verified` | **`mismatched`** | **0/0/2** | "Lua 검증됨" | "근거는 있고 증명 실패" | 🔴 **검증 주장이 거짓** |
| ③ | Lua 있음·지문 없음(낡은 캐시) | `lua_verified` | **`unprovable`** | **0/0/2** | "Lua 검증됨" | "근거는 있고 증명 불가" | 🔴 같음 |
| ④ | Lua 없음 | `text_derived` | `matched`(블록 0) | 0/0/0 | "텍스트 유래" | 맞음 | 🟠 결합이 `matched` 로 보이는 것은 주의 (`test_25`) |
| ⑤ | 일부 블록만 미인식 | `lua_verified` | **`mismatched`** | **1/0/1** | "Lua 검증됨" | "절반만 증명" | 🔴 같음 |
| ⑥ | 캐시엔 있고 디스크 파일 소실 | `lua_verified` | **`source_missing`** | **0/0/2** | "Lua 검증됨" | "근거 파일 없음" | 🔴 같음 |
| ⑦ | 효과 텍스트만 | `text_derived` | `matched`(블록 0) | 0/0/0 | "텍스트 유래" | 맞음 | 🟠 텍스트 분석은 **돌지 않는다** (`test_16`) |
| ⑧ | 통상 몬스터 | `no_effect` | `matched`(블록 0) | 0/0/0 | "효과 없음" | 맞음 | 없음 |

### 5.1 🔴 실제 코퍼스에서도 나온다 (가상 사례가 아니다)

`LUA_VERIFIED` 12,687장 중 **215장이 등록 효과 0개**다.

| 구분 | 수 | 정체 |
|---|---|---|
| (a) 효과 블록 자체가 0개 | **183장** | 융합 소재 선언만 있는 스크립트 — `Fusion.AddProcMix` · `EnableReviveLimit` |
| (b) 블록은 있으나 전부 해결 효과 | **32장** | 붉은 눈 융합 · 대융합 · 오스티나토 등 |

실제 파일로 확인한 세 장 (`test_13`):

```lua
-- c1641882.lua (퓨저니스트)
function s.initial_effect(c)
	c:EnableReviveLimit()
	Fusion.AddProcMix(c,true,true,38142739,83464209)
end
```

파서가 효과 블록을 하나도 뽑지 못한다. 그런데 상태 docstring 은 "실제 카드
스크립트에서 **구조화했다**" 였고, 요약 라벨은 "Lua **검증됨**" 이었다.

> 🔴 **분명히 적어 둔다.** 이 183장의 **분석이 틀렸다고 주장하지 않는다** —
> 스크립트에 효과 블록이 없는 것이 사실일 수 있다. 틀린 것은 **"검증했다" 는
> 주장**이다. 아무것도 구조화하지 않았고 아무것도 검증하지 않았다.

---

## 6. 최종 판정: **`MIXED_FINDINGS`**

사례마다 판정이 다르므로 §5 의 지시대로 따로 적는다.

| 대상 | 판정 | 근거 |
|---|---|---|
| 사용자에게 표시되던 "Lua 검증됨" | **`CONFIRMED_FALSE_VERIFICATION`** | 사례 ②③⑤⑥ + 실제 183/215장. 검증하지 않은 것을 검증으로 표시 |
| `analysis_status` **값 자체** | **`CONFIRMED_SEMANTICS`** (근거 계층으로서) | "어느 소스가 근거인가" 로 읽으면 네 분기 모두 정확하다. 그래서 생성 조건을 **바꾸지 않았다** |
| 필드별 provenance·availability 전파 | **`PROVENANCE_LOSS`** | `describe_ko()` 호출자 0개, 6개 플래그 출력 0곳. 기록은 만들고 아무도 읽지 않는다 |
| "의미적 검증" 자체 | **`UNKNOWN_BY_DESIGN`** | `MATCHED` 는 핸들러 짝짓기만 증명한다. 결합이 전부 증명된 카드에도 미구조화 호출이 남는다 (`test_14`). 현재 데이터 모델에는 "효과의 의미가 옳다" 를 입증할 수단이 **없다** |

---

## 7. production 변경과 변경하지 않은 것

### 7.1 변경 (3개 파일)

| 파일 | 줄 | 내용 |
|---|---|---|
| `core/provenance.py` | +40/-3 | `AnalysisStatus` 와 두 멤버의 docstring — 이 enum 이 **근거 계층**임을, 결합 증명은 `HandlerBinding` 이 재며 둘이 어긋날 수 있음을, 그래서 합치거나 승격·강등하지 않음을 적는다. **실행 코드 0줄** |
| `scripts/update_cards.py` | +16/-2 | 라벨 `"Lua 검증됨"` → `"Lua 근거 있음 (스크립트 첨부)"`, 그리고 이 표가 근거만 센다는 한 줄 |
| `app/main.py` | +10/-0 | 한 카드에서 **근거와 증명을 나란히** 보여주는 한 줄 (provenance 없으면 생략) |

### 7.2 **변경하지 않은 것과 이유**

* **상태 생성 코드** — 한 줄도 바꾸지 않았다 (`test_38` 이 `core/card_repository.py`
  의 diff 가 비어 있음을 확인한다). 근거 계층으로서는 값이 정확하고, 바꾸면
  §5 가 금지한 일괄 강등·승격이 된다.
* **`HandlerBinding` → 상태 승격** — 하지 않았다. 결합 성공은 의미의 정확성이
  아니다 (§3 의 명시적 금지, `test_09`·`test_14`).
* **결합 실패 → 상태 강등** — 하지 않았다. 증명이 실패해도 **근거가 사라진 것은
  아니고**, 강등하면 "Lua 가 아예 없는 카드" 와 구별되지 않는다 (`test_08`).
* **enum 이름·값** — `"lua_verified"` 를 그대로 뒀다. 공개 API 이고 여러 기존
  테스트가 이 값을 고정한다. 이름만 바꾸는 것은 §5 가 금지한 처리다.
* **새 enum / provenance 프레임워크** — 만들지 않았다. §3 의 일곱 개념 중
  여섯 개는 이미 표현되고, 남은 하나는 입증할 수 없는 사실이다 (§6).
* **`TEXT_DERIVED` 라벨** — 고치지 않았다. 이 Phase 의 질문은 `LUA_VERIFIED`
  이고, 텍스트 쪽 과잉 주장은 **위험으로 기록**했다 (N41).
* **`CardProvenance.describe_ko()` 를 화면에 붙이기** — 하지 않았다. 새 출력
  설계이고 이번 범위가 아니다. 소실 사실만 측정해 기록했다 (N42).
* **`engine/`·`agent/`·검색 계층·Lua·README·`data/`** — 한 줄도 건드리지 않았다
  (`test_37`).

### 7.3 🔴 기존 테스트 2개의 assertion 을 고쳤다 — 왜 기존 가정이 틀렸는가

| 테스트 | 원래 | 왜 틀린 가정이었나 | 어떻게 고쳤나 |
|---|---|---|---|
| `test_handler_binding_diagnostics.py::test_25` | `assert "Lua 검증됨" in out` | 그 라벨이 **검증을 주장**하는데 production 은 검증한 적이 없다. 조건은 script 존재 하나이고, 그 행에 든 12,687장 중 215장은 등록 효과가 0개다 | 새 라벨을 확인하고, **`"Lua 검증됨" not in out` 을 추가**했다 (약화가 아니라 강화) |
| `test_update_coverage_contract_audit.py::test_31` | `for label in ("Lua 검증됨", …)` | 같은 이유 | 같은 방식 |

삭제 0 · skip 추가 0 · assertion 약화 0 · threshold 완화 0 (`test_39`).

> 🔴 작성 중 내 실수 2건.
> ① `test_10` 이 `core/card_repository.py` 소스에 `"HandlerBinding"` 문자열이
> 없는지 보려 했는데, 그 파일은 3-F-35 이후 **주석에서** 그 이름을 설명한다.
> 주석의 언급은 계층 결합이 아니다 — AST 로 실행 코드의 이름만 보도록 고쳤다.
> ② 갱신 요약에 붙인 설명 줄에 결합 표의 **제목을 그대로** 넣었더니, "결합
> 표가 출력됐는가" 를 그 문구로 확인하던 기존 테스트 3개가 설명 줄에도
> 걸리게 됐다 (하나는 실패, 둘은 거짓 양성 위험). **production 문구를** 표
> 제목을 쓰지 않도록 고쳤다 — 기존 테스트를 느슨하게 만드는 쪽이 아니라.

---

## 8. 사용자에게 보이는 변화

**갱신 요약 (실제 출력):**

```
  카드            : 14,127장 (판본 포함 14,520)
- Lua 검증됨                   : 12,687장
+ Lua 근거 있음 (스크립트 첨부)         : 12,687장
  텍스트 유래 (Lua 없음)             : 756장
  효과 없음 (통상 몬스터·토큰)           : 684장
  분석 근거 없음                    : 0장
+ (이 표는 분석 근거만 셉니다 — 블록·핸들러 결합 증명은 별도 표에서 셉니다.)
```

**분석 CLI — 근거와 증명이 어긋나는 카드 (실제 출력):**

```
+ 분석 근거  : lua_verified (근거 계층 — 증명은 다음 줄)

  🔴 결합 상태  : 증명된 블록 0/2
      · 대응 불일치 확인 2개 [e1, e2]
```

이 Phase 이전에는 이 화면에 **근거가 없었다.** 즉 "증명 0/2" 만 보이고, 그
카드가 여전히 `Lua 검증됨 12,687장` 에 집계된다는 사실은 알 수 없었다.

---

## 9. 신규 테스트와 전체 회귀

신규 파일: `tests/test_lua_verified_provenance_audit.py` — **46개**
(함수 39개 중 둘이 4-way·5-way parametrize).

| 묶음 | 수 | 내용 |
|---|---|---|
| A. 상태 생성 | 9 | 대입 자리 1곳(AST) · 조건 하나 · 분석 없이 결정 · 네 상태 4사례 · availability 플래그 |
| B. 결합과의 동시 성립 | 9 | 다섯 사례 전부 `LUA_VERIFIED` · 세 실패에서 effects 0 · 강등 없음 · 승격 없음 · 계층 결합 코드 부재(AST) |
| C. 파싱 결과 부족 | 4 | 블록 0개 스크립트 · **실제 215장(183+32)** · 실제 3장 · `MATCHED`≠의미 검증 |
| D. 텍스트 | 3 | Lua 없을 때만 · `TextEffectAnalyzer` 호출자 0개 · 승격 경로 없음 |
| E. provenance 전파 | 3 | 읽는 자리 전수 · `describe_ko` 호출자 0개 · availability 미노출 |
| F. 캐시·갱신 | 3 | 직렬화 없음 · 낡은 캐시로 **유지** · 매번 재계산 |
| G. 카드/블록 단위 | 2 | 최악값 vs 개별 · 블록 0개의 `MATCHED` |
| H. CLI·갱신 요약 | 6 | 나란히 표시 · 어긋날 때 둘 다 · provenance 없어도 무사 · 라벨에서 "검증" 제거 · 표가 센 것 명시 · 상태 합계 |
| I. 반복·불변 | 3 | 반복 동일 · 상태×결합 교차표 · 분석·검색·`EffectRef` |
| J. 금지·범위 | 5 | 새 enum 없음 · 3개 파일 · 금지 경로 · **생성 코드 diff 빈 것** · 테스트 삭제/skip |

### 9.1 관련 테스트 선행 실행 (실측)

```
신규 + test_handler_binding_diagnostics + test_update_coverage_contract_audit
+ test_update_pipeline + rulings/test_data_audit + engine/test_phase2_contracts
→ 189 passed / 4 skipped / 1 failed  (설명 줄의 표 제목 충돌 — §7.3 ②)
수정 후 재실행: 85 passed / 4 skipped / 0 failed
```

### 9.2 전체 회귀 (실측)

작업·테스트·보고서 commit 이 모두 올라간 뒤 `pytest -q -p no:randomly` 로
한 번에 측정했다.

| 항목 | 기준 (`87eb10f`) | 이번 Phase (`2adec59`) | 차이 |
|---|---|---|---|
| passed | 5,277 | **5,323** | +46 |
| skipped | 4 | **4** | 0 |
| failed | 0 | **0** | 0 |
| errors | 0 | **0** | 0 |

실행 결과 마지막 줄: `5323 passed, 4 skipped in 2302.87s (0:38:22)`.
출력 전체에서 `F`·`E` 문자 **0개**.

* 증가분 **+46 은 신규 파일이 수집하는 테스트 수와 정확히 같다**
  (함수 39개 + 4-way·5-way parametrize 로 늘어난 7개). 기존 5,277개가 한
  개도 줄지 않았다.
* skip **4개는 기준과 동일한 기존 skip** 이다. 신규 파일의
  `test_36`~`test_39` 는 "이 Phase 의 commit 이 존재할 때까지" 건너뛰도록
  썼는데, 세 commit (`95cfae8`·`6eea2de`·`2adec59`) 이 생긴 뒤 측정했으므로
  **실제로 실행되어 통과**했다 (§9.1 의 선행 실행에서는 4개가 skip 이었다).
  신규 skip 은 0개다.
* 기존 테스트 **삭제 0 · skip 추가 0 · assertion 약화 0 · threshold 완화 0**
  (`test_39` 가 파일별 테스트 개수를 부모 커밋과 비교해 확인한다). 수정한
  것은 assertion **2개**이고 둘 다 강화다 — 이유는 §7.3.

### 9.3 기준 전체 테스트를 독립적으로 재측정하지 않았다

3-F-39 와 같은 이유로 적어 둔다. 기준 숫자 `5,277` 은 **Phase 3-F-39 가
`87eb10f` 에서 실측해 보고서에 적은 값**이고, 이번 Phase 가 다시 완주해
확인한 것은 **수정 후** 실행뿐이다. `f61f5ad`(이번 Phase 의 시작 HEAD)는
`87eb10f` 와 **문서 한 파일만** 다르다 (`git diff --numstat` 으로 확인).
회귀를 실제로 잡아내는 측정은 수정 후 전체 실행이고, 그것은 완주했다.
확인하지 않은 것을 확인한 것처럼 적지 않는다.

---

## 10. corpus 및 검색 산출물 비교

3-F-39 의 측정 스크립트에 **상태 분포·상태×결합 교차표·`LUA_VERIFIED` 생성
수·등록 효과 0개 수** 네 항목을 더해 22개로 비교했다.

| # | 항목 | 기준 = 수정 후 | 결과 |
|---|---|---|---|
| 1–4 | 스크립트 12,702 · parser block 34,684 · attached card 12,687 · attached block 34,635 | 동일 | ✔ |
| 5–7 | `EffectSpec` / `CardAnalysis` / `coverage` digest | `b2623fe9…` · `602328c9…` · `9edd1a0e…` | ✔ |
| 8 | coverage 분자·분모 14항목 | 전부 동일 (`effects 26,352` 등) | ✔ |
| 9–10 | 등록·해결 Effect · 조건/비용/대상/행동/category | `26,352 / 8,283` · `12,438 / 5,007 / 5,516 / 18,280 / 20,484` | ✔ |
| 11–12 | 검색 결과·위치 digest | `d57c6ae1…` · `a822e760…` (각 31종) | ✔ |
| 13 | `EffectRef` 총수 / 불일치 | 34,635 / **0** | ✔ |
| 14 | `HandlerBinding` 상태별 (카드/블록) | `{matched: 12,687}` / `{matched: 34,635}` | ✔ |
| 15 | **`AnalysisStatus` 상태별** | `lua_verified 12,687 · text_derived 756 · no_effect 684` (합 14,127) | ✔ |
| 16 | **상태 × 결합 교차표** | `lua_verified\|matched 12,687 · text_derived\|<블록 없음> 756 · no_effect\|<블록 없음> 684` | ✔ |
| 17 | **`LUA_VERIFIED` 생성 수** | 12,687 | ✔ |
| 18 | **`LUA_VERIFIED` 인데 등록 효과 0개** | **215** | ✔ |
| 19 | `unbound_effects` | 0 | ✔ |
| 20–22 | 검색 카테고리/위치 수 · Phase 3-F-32 대표 5장 | 31 / 31 · 전부 | ✔ |

**22개 비교 항목 전부 동일 (다름 0개).** 상태 분포가 그대로인 것이 "생성
조건을 건드리지 않았다" 의 증거이고, 그 상태 중 215장이 등록 효과 0개라는
사실이 "표시가 틀렸다" 의 증거다. 두 수치를 함께 적는 이유가 그것이다.

---

## 11. 남은 위험

| # | 내용 | 상태 |
|---|---|---|
| **N41** | 🟠 `TEXT_DERIVED` 라벨 "텍스트 유래" 도 과잉 주장이다. `TextEffectAnalyzer` 는 production 호출자가 **0개**이므로 아무것도 유추하지 않았다. 756장이 이 행에 있다 | 미해결(의도) — 이번 질문은 `LUA_VERIFIED` 였다. 고치려면 라벨 하나와 기존 assertion 2개를 더 건드린다 |
| **N42** | 🟠 `CardProvenance.describe_ko()` 는 호출자가 없고, 필드별 출처·충돌과 6개 availability 플래그는 어떤 화면에도 안 나온다. 기록은 매번 만들어진다 | 미해결 — 화면에 붙이는 것은 새 출력 설계다 |
| **N43** | 🟠 블록이 0개인 카드의 `HandlerBinding.MATCHED` 는 "증명했다" 가 아니라 "어긋날 자리가 없다" 다. Lua 없는 카드 756장·블록 0개 183장이 이 값을 가진다. 두 값을 조인하는 소비자가 생기면 오독할 수 있다 | 기록만 — 3-F-37 의 의도된 규정이고, 이 Phase 가 docstring 에 적었다 |
| **N44** | 🟠 `PARSE_SUCCESS` 에 해당하는 표현이 없다. `parse_lua_source` 는 실패하지 않으므로 "파싱했는데 결과가 비었다" 와 "파싱할 것이 없었다" 가 `script.effects == []` 하나로 합쳐진다 (183장) | 미해결 — 파서 계약 변경이라 범위 밖 |
| **N45** | 🟠 `AnalysisStatus.UNKNOWN` 은 라벨 표에 없고 실측 0장이다 (3-F-38 의 N33 그대로) | 의도된 선택 |
| N34~N38 (3-F-39) | flag 무효화 · `--update` 비용 · coverage 분모 · 비율 소비자 0 · **N38 = 이 Phase 의 주제** | N38 🟢 해결(표시), 나머지 그대로 |
| N31·N32·N33 (3-F-38) · N25~N28 (3-F-37) | — | 그대로 |

---

## 12. 다음 Phase 후보 (제안 1개)

**Phase 3-F-41 — 근거 기록의 소비자 부재 감사 (N41 + N42)**

이 Phase 가 측정한 소실은 두 가지다. ① `CardProvenance` 가 매 카드마다
필드별 출처·충돌·6개 availability 플래그를 만드는데 **읽는 화면이 하나도
없다**. ② `TextEffectAnalyzer` 는 **한 번도 돌지 않는데** 756장이 "텍스트
유래" 로 표시된다. 둘 다 "만들어 두고 쓰지 않는 기록" 이라는 같은 모양이고,
3-F-38 의 N29(소비자 부재)와 같은 종류다. 어느 쪽을 화면에 붙일지, 아니면
돌지 않는 분석기를 어떻게 표시할지는 출력 설계 결정이라 별도 지시가 필요하다.

---

이 Phase 를 완료한 뒤 다음 Phase 를 임의로 시작하지 않는다.
