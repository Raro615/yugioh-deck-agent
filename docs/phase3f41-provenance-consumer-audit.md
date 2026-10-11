# Phase 3-F-41 — Provenance 기록 및 텍스트 분석 상태의 소비자 경로 감사

핵심 질문: 시스템이 기록한 출처·신뢰도 정보가 **실제 사용자에게 전달되며**,
전달되는 표현이 **확보된 근거의 수준을 정확히 반영**하는가.

실측 답: **요약 표는 맞고, 카드 단위 CLI 가 틀렸다.** 그리고 출처 요약
메서드는 자기 필드 하나를 빠뜨리고 있었다.

---

## 1. 기준 상태

| 항목 | 값 |
|---|---|
| 브랜치 | `claude/pensive-goodall-te1egy` |
| HEAD | `d7bcd9a` (= `origin/claude/pensive-goodall-te1egy`) |
| worktree | clean |
| 3-F-40 작업 / 테스트 / 보고서 / 보고서 수정 | `95cfae8` · `6eea2de` · `2adec59` · `d7bcd9a` — **네 SHA 모두 실존** |
| 기준 전체 테스트 | `5,323 passed / 4 skipped / 0 failed` (3-F-40 이 `2adec59` 에서 실측) |
| 기준 corpus | 22개 항목 — 이번 Phase 가 2개를 더해 **24개**로 비교했고 전부 동일 |

`d7bcd9a` 는 `2adec59` 와 **문서 한 파일만** 다르다 (`git diff --numstat` 확인).
기존 commit 을 rewrite/amend 하지 않았다.

---

## 2. N41 — `TEXT_DERIVED` 의 생성·소비 경로

### 2.1 §2 의 여덟 질문

| # | 질문 | 실측 답 (파일·함수) |
|---|---|---|
| ① | 텍스트 분석기는 언제 실행되는가 | **한 번도 실행되지 않는다.** `TextEffectAnalyzer` 는 production 호출자가 **0개**다 — import 도, 이름 참조도, 속성 접근도 없고 `analysis/__init__` 이 내보내지도 않는다 (AST 전수, `test_01`). 호출자는 **테스트 두 곳**뿐이다 (`tests/test_update_pipeline.py` 와 이 Phase 의 감사 파일, `test_02`) |
| ② | 결과가 어떤 상태·provenance 를 갖는가 | 돌지 않으므로 **아무것도 붙지 않는다.** `TEXT_DERIVED` 는 `CardRepository._record_provenance` 가 `card.script is None and card.has_printed_effect and card.desc` 일 때 붙이고, 함께 `availability.text_analysis_available = True`, `fields["effect_analysis"] = (official_text, SUPPLEMENTARY, "Lua 없음 — 텍스트 유래")` 를 적는다 |
| ③ | 사용자 출력에서 어떤 문구인가 | 갱신 요약: `텍스트 유래 (Lua 없음) : 756장`. 분석 CLI: **`Lua 스크립트가 없습니다 (일반 몬스터 등).`** ← 🔴 |
| ④ | Lua 분석·검증 완료처럼 보일 수 있는가 | **아니다.** 두 상태는 다른 행·다른 라벨이고, 3-F-40 이 "검증" 이라는 말을 뺐다. CLI 에서도 텍스트 카드에는 `결합 상태`·`구조화 정도` 가 아예 나오지 않는다 (`test_12`) |
| ⑤ | 일부 효과만 텍스트 분석된 카드는 구분되는가 | **그런 카드가 존재할 수 없다.** `TEXT_DERIVED` 는 `script is None` 일 때만 붙어 Lua 와 배타적이다. 전수 확인: 겹치는 카드 **0장** (`test_13`). 그래서 카드 단위/효과 단위 구분이 아직 필요 없다 |
| ⑥ | "결과 없음" 과 "시도하지 않음" 이 구분되는가 | **모델에서는 구분된다** — `TextAnalysis.skipped_reason` vs `is_empty` (`test_04`). 🔴 그런데 `TEXT_DERIVED` **756장에서는 `skipped_reason` 이 한 번도 생기지 않는다**: 그 상태의 조건과 `_is_flavor_text_only` 의 조건이 배타적이기 때문이다 (`test_05`). 즉 모델의 구분이 이 집단에는 적용될 자리가 없고, 분석기가 돌지 않으므로 사용자 수준에서는 **구분되지 않는다** |
| ⑦ | `UNKNOWN`·`NO_EFFECT`·`SOURCE_MISSING` 이 혼동되어 표시되는가 | 🔴 **그렇다.** Lua 가 없는 **1,440장 전부**가 같은 한 문장을 받았다 — `NO_EFFECT` 684장과 `TEXT_DERIVED` 756장이 구별되지 않았다 |
| ⑧ | 사용자 출력에서 출처·검증 수준을 판단할 수 있었는가 | 🔴 **Lua 카드는 가능, 나머지 1,440장은 불가능.** 3-F-40 이 넣은 `분석 근거` 줄이 `has_script` **이른 반환 뒤**에 있었다 |

### 2.2 🔴 재현 — 속공 마법에게 "일반 몬스터 등" 이라고 말하고 있었다

수정 전, 실제 CLI 출력:

```
========================================================================
패러렐 텔레포트 · 마법/속공
  Lua 스크립트가 없습니다 (일반 몬스터 등).
========================================================================
```

`패러렐 텔레포트`(483)는 **속공 마법**이고 `has_printed_effect` 가 참이며
`text_derived` 다. 통상 몬스터가 아니다. 같은 문장을 `13번째 매장자`
(통상 몬스터)도 받았다 — 둘을 구별할 수 없었다.

카드에 이미 붙어 있는 상태를 읽으면 알 수 있는 사실을 **추측으로 덮은**
것이고, 그 추측이 756장에서 틀렸다.

### 2.3 판정

| 대상 | 판정 |
|---|---|
| 분석 CLI 의 "일반 몬스터 등" 과 근거 줄 누락 | **`CONFIRMED_OUTPUT_OVERCLAIM`** |
| 갱신 요약의 "텍스트 유래 (Lua 없음)" 라벨 | **`CONFIRMED_CONSISTENT`** — 아래 |
| `TextEffectAnalyzer` 자체 | **`CONFIRMED_UNUSED_INTERFACE`** — 아래 |

🟢 **요약 라벨은 고치지 않았다.** "텍스트 유래" 는 **근거의 이름**이고
"검증했다" 를 주장하지 않는다. 3-F-40 이 고친 "Lua 검증됨" 과는 다르다 —
그쪽은 검증을 주장했고 이쪽은 출처를 가리킨다 (`test_24`). 라벨을 바꾸면
기존 assertion 두 개를 또 건드리면서 얻는 것이 문구 취향뿐이다.

🔴 **`TextEffectAnalyzer` 는 production 에 연결하지 않았다.** 756장에
돌려 보면 **753장(99.6%)** 에서 행동이 나온다 — 쓸모가 없어서가 아니라,
연결하는 것이 **새 분석 경로**이고 §5 가 금지한 "소비자가 없다는 이유만으로
소비자를 추가" 에 정확히 해당하기 때문이다. 수치만 기록한다 (`test_03`).

---

## 3. N42 — `CardProvenance` 의 생성·전달·소비

### 3.1 전달 경로 (실측)

```
cards.cdb / c*.lua / 한국어 DB
        │  CardRepository.build()
        ▼
   _record_provenance()  ──▶  card.provenance : CardProvenance
        │                      ├─ analysis_status      ─┐
        │                      ├─ availability (6칸)    │
        │                      └─ fields{} + conflicts  │
        │                                               │
        ├──▶ scripts/update_cards.py summarise()  : analysis_status 만
        ├──▶ app/main.py cmd_analyze()            : analysis_status 만 (getattr)
        └──▶ core/provenance.py describe_ko()     : 호출자 0개
                     └─▶ DataAvailability.describe_ko()  : 위에서만 불린다
             core/provenance.py missing()         : 호출자 0개 (어디에도 없다)
```

### 3.2 §3 의 여덟 질문

| # | 질문 | 실측 답 |
|---|---|---|
| ① | `describe_ko()` 의 정의와 호출자 | `core/provenance.py` `CardProvenance.describe_ko`. **외부 호출자 0개**, 내부 호출 1개(`self.availability.describe_ko()`) (`test_18`) |
| ② | 호출되지 않는 이유 | 같은 정보를 더 좁게 전달하는 경로가 이미 있다 — 요약 표는 상태별 건수, 분석 CLI 는 카드 한 장의 상태. 함수가 깨진 것은 아니다 (`test_28` 이 실제로 돌려 본다) |
| ③ | 생성 위치 | `_record_provenance` — 모든 카드에 `fields` 와 `availability` 를 채워 붙인다 (`test_17`). 충돌은 덮어쓰지 않고 `conflicts` 로 남는다 (`test_27`) |
| ④ | 분석 결과와 함께 보존되는가 | `card.provenance` 로 카드에 붙어 끝까지 남는다. 다만 **읽는 곳이 세 곳**뿐이다 (`test_22`) |
| ⑤ | 소실·생략되는 경로 | 🔴 **`DataAvailability` 자신의 두 요약 메서드**. 여섯 칸 중 다섯 칸만 요약했다 — 아래 §3.3 |
| ⑥ | CLI·갱신 요약의 표시 방식 | 갱신 요약은 상태별 건수, 분석 CLI 는 `분석 근거 : <상태>` 한 줄. 필드별 출처는 어느 쪽에도 없다 |
| ⑦ | 필드별 availability 가 구별되는가 | **사용자 출력에는 전혀 나오지 않는다.** 플래그를 읽는 production 자리는 `card_repository`(쓰기)와 `provenance.py`(요약)뿐이다 |
| ⑧ | 이미 충분한데 중복을 추가하려는 것은 아닌가 | **그렇다 — 그래서 추가하지 않았다.** 새 기록·새 출력 경로를 만들지 않고, 이미 있는 여섯 번째 칸이 요약에서 빠진 것만 바로잡았다 |

### 3.3 🔴 재현 — 요약 메서드가 자기 필드 하나를 빠뜨렸다

`DataAvailability` 는 칸이 **여섯 개**인데 `missing()` 과 `describe_ko()` 는
**다섯 개만** 훑고 있었다. 빠진 칸이 하필 `text_analysis_available` 이고,
그것은 **Lua 가 없는 카드에서 유일하게 켜지는** 플래그다.

수정 전, 실제 출력 (`패러렐 텔레포트`):

```
✓CDB ✓공식텍스트 ✓한국어 ✗Lua ✗효과분석
```

`text_analysis_available` 은 `True` 인데 요약에는 흔적이 없고, 보이는 것은
`✗효과분석` 뿐이다 — **그 카드의 유일한 긍정적 근거가 떨어진다.**
Phase 3-F-38 이 `summarise()` 에서 `NO_EFFECT` 행이 빠진 것을 고친 것과
같은 모양의 결함이다.

판정: **`CONFIRMED_PROVENANCE_LOSS`** (요약 메서드 안에서의 소실).

---

## 4. 사례별 상태와 사용자 출력

여덟 사례 전부 실제 경로로 돌렸다. ⑤⑧ 은 테스트용 가상 사례이고 나머지는
실제 카드다.

| # | 입력 | 상태 | `HandlerBinding` | 수정 전 사용자 문구 | 수정 후 | 근거 수준 반영 |
|---|---|---|---|---|---|---|
| ① | Lua 정상 (증원 `32807846`) | `lua_verified` | `matched` | 근거 줄 있음 + 결합 상태 | 그대로 | ✔ |
| ② | 일부 블록 미인식 (가상) | `lua_verified` | `mismatched` | 근거 줄 + 🔴 결합 상태 | 그대로 | ✔ |
| ③ | 텍스트 근거만 (패러렐 텔레포트 `483`) | `text_derived` | — | **"(일반 몬스터 등)"**, 근거 줄 **없음** | `분석 근거 : text_derived` + "효과가 있는 카드인데 스크립트가 아직 없습니다…" | 🔴→✔ |
| ④ | 텍스트 분석 결과 없음 | 분석기가 **돌지 않는다** | — | 해당 없음 | 해당 없음 — "구조화된 텍스트 분석은 돌지 않습니다" 로 명시 | ✔ |
| ⑤ | 상태를 알 수 없음 (가상 `UNKNOWN`) | `unknown` | — | "(일반 몬스터 등)" | "이 카드의 분석 근거를 판단할 수 없습니다." | 🔴→✔ |
| ⑥ | `MATCHED` 지만 의미 검증 없음 | `lua_verified` | `matched` | "정상 연결" | 그대로 — "검증 완료" 라고 말하지 않는다 (`test_16`) | ✔ |
| ⑦ | 등록 효과 0개 (퓨저니스트 `1641882`) | `lua_verified` | `matched` | 근거 줄 없음(반환 전) | 근거 줄 있음 | ✔ |
| ⑧ | provenance 자체가 없음 (가상) | — | — | "(일반 몬스터 등)" | 근거 줄 생략 + "판단할 수 없습니다" | 🔴→✔ |

**문제가 난 계층:** 전부 **표시 계층**이다. 상태 생성(`_record_provenance`)과
결합 판정(`EffectAnalyzer`)은 손대지 않았고, corpus 수치도 바뀌지 않았다 (§9).

---

## 5. 최종 판정: **`MIXED_FINDINGS`**

| 대상 | 판정 | 조치 |
|---|---|---|
| 분석 CLI 의 Lua 없는 카드 문구 | **`CONFIRMED_OUTPUT_OVERCLAIM`** | 상태별 실제 이유로 교체 |
| 분석 CLI 의 근거 줄 위치 | **`CONFIRMED_PROVENANCE_LOSS`** | 이른 반환 **위**로 이동 |
| `DataAvailability` 의 두 요약 메서드 | **`CONFIRMED_PROVENANCE_LOSS`** | 여섯 번째 칸 추가 |
| `CardProvenance.describe_ko()` | **`CONFIRMED_UNUSED_INTERFACE`** | **수정하지 않음** — 대체 경로가 있고, 호출자를 만드는 것은 §5 금지 |
| `TextEffectAnalyzer` | **`CONFIRMED_UNUSED_INTERFACE`** | **수정하지 않음** — 연결은 새 분석 경로 |
| 갱신 요약의 "텍스트 유래" 라벨 | **`CONFIRMED_CONSISTENT`** | **수정하지 않음** |
| 텍스트 "결과 없음" vs "시도 안 함" 구분 | **`UNKNOWN_BY_DESIGN`** | 모델에는 있으나 이 집단에서 도달 불가 — 기록만 |

---

## 6. production 변경과 변경하지 않은 것

### 6.1 변경 (2개 파일)

| 파일 | 줄 | 내용 |
|---|---|---|
| `app/main.py` | +39/-11 | ① `분석 근거` 줄을 `has_script` 이른 반환 **위**로 이동 (1,440장이 처음으로 근거를 본다) ② `(일반 몬스터 등)` 추측을 **상태별 실제 이유**로 교체 ③ 상태를 모르면 "판단할 수 없습니다" |
| `core/provenance.py` | +9/-0 | `DataAvailability.missing()` 과 `.describe_ko()` 에 여섯 번째 칸 `text_analysis_available` 추가 |

### 6.2 **변경하지 않은 것과 이유**

* **`TextEffectAnalyzer` 를 production 에 연결** — 하지 않았다. 새 분석 경로이고,
  §5 가 "소비자가 없다는 이유만으로 소비자를 추가" 를 금지한다. `test_36` 이
  `analysis/text_effect_analyzer.py`·`analysis/__init__.py`·
  `core/card_repository.py` 의 diff 가 **비어 있음**을 확인한다.
* **`CardProvenance.describe_ko()` 를 화면에 붙이기** — 하지 않았다. 같은
  정보를 더 좁게 전달하는 경로가 이미 있고, 새 출력 설계는 이번 범위가 아니다.
* **갱신 요약 라벨** — 고치지 않았다 (§2.3).
* **상태 생성 조건** — 한 줄도 바꾸지 않았다. `TEXT_DERIVED` 를 오류로
  바꾸지도, Lua 존재만으로 `LUA_VERIFIED` 를 설정하지도, `MATCHED` 를 의미적
  검증으로 취급하지도 않았다 (`test_35`, `test_16`).
* **새 enum·진단 프레임워크·provenance 프레임워크** — 만들지 않았다.
  `AnalysisStatus` 5값 · `HandlerBinding` 4값 · `DataAvailability` 6칸 그대로.
* **`engine/`·`agent/`·검색 계층·Lua·README·`data/`** — 한 줄도 건드리지 않았다
  (`test_38`).

### 6.3 🟢 기존 테스트를 **한 줄도 고치지 않았다**

작업 전 전수 grep 으로 확인했다: 바꾼 문구 `"일반 몬스터 등"` 을 고정하는
테스트가 **없었고**, `"Lua 스크립트가 없습니다"` 앞부분은 그대로 두었기 때문에
그것을 보는 기존 테스트(`test_handler_binding_diagnostics::test_17`)도 그대로
통과한다. 삭제 0 · skip 추가 0 · assertion 약화 0 · 수정 0 (`test_39`).

> 🔴 작성 중 내 테스트 오류 2건 (production 결함 아님).
> ① `test_02` 가 `"TextEffectAnalyzer("` 문자열로 호출자를 세려 했는데, 이
> 파일과 3-F-40 감사 파일은 **그 문자열 자체를 자기 검사에 쓴다**. 스캔용
> 리터럴과 실제 호출을 문자열로는 가를 수 없어 AST `Call` 노드로 바꿨다.
> ② `test_11` 이 `"분석 근거" not in out` 을 봤는데, fallback 문장
> ("이 카드의 **분석 근거**를 판단할 수 없습니다") 안에 그 낱말이 있다.
> 없어야 하는 것은 **근거 줄**이므로 `^\s*분석 근거\s*:` 정규식으로 바꿨다.

---

## 7. 사용자에게 보이는 변화 (실제 출력)

**텍스트 근거만 있는 카드 (패러렐 텔레포트 · 마법/속공):**

```
  패러렐 텔레포트 · 마법/속공
- Lua 스크립트가 없습니다 (일반 몬스터 등).
+   분석 근거  : text_derived
+   Lua 스크립트가 없습니다 — 효과가 있는 카드인데 스크립트가 아직 없습니다.
+   효과 텍스트만이 근거이고, 구조화된 텍스트 분석은 돌지 않습니다.
```

**통상 몬스터 (13번째 매장자):**

```
+   분석 근거  : no_effect
+   Lua 스크립트가 없습니다 — 공식 DB 가 효과 없는 카드로 분류합니다 (통상 몬스터·토큰).
```

**출처 요약 (`availability.describe_ko()`):**

```
- ✓CDB ✓공식텍스트 ✓한국어 ✗Lua ✗효과분석
+ ✓CDB ✓공식텍스트 ✓한국어 ✗Lua ✗효과분석 ✓텍스트근거
```

Lua 가 있는 카드의 출력은 **근거 줄의 위치만** 올라갔고 내용은 그대로다.

---

## 8. 신규 테스트와 전체 회귀

신규 파일: `tests/test_provenance_consumer_audit.py` — **39개**.

| 묶음 | 수 | 내용 |
|---|---|---|
| A. 텍스트 분석기 | 5 | production 호출자 0개(AST) · 테스트 호출자 2곳 · 돌리면 753장 · 모델의 시도/결과 구분 · 그 구분이 이 집단에 도달 불가 |
| B. 사용자 출력 | 11 | 속공 마법≠일반 몬스터 · 근거 줄이 1,440장에 도달 · 두 상태가 다른 문장 · 분석했다고 말하지 않음 · `UNKNOWN` fallback · provenance 없음 · Lua/검증처럼 안 보임 |
| C. 카드 단위 | 4 | Lua·텍스트 배타(전수) · 등록 효과 0개 카드 · 미인식 블록 카드 · `MATCHED`≠의미 검증 |
| D. provenance 소비 | 8 | 생성·필드 · `describe_ko` 호출자 0 · `missing` 호출자 0 · **여섯 칸 전부 요약** · 켜진 칸 유지 · 읽는 자리 전수(getattr 포함) · 갱신 요약 · 라벨 판정 |
| E. 부분·갱신 | 4 | 재빌드 시 출처 전환 · 부분 기록 · 충돌 보존 · 전체 기록 렌더 |
| F. 통합·회귀 | 6 | 모든 상태가 근거를 본다(전수 샘플) · 반복 동일 · 기존 호출자 호환 · 상태 분포 · 분석·결합 집계 · 검색·`EffectRef` |
| G. 금지·범위 | 5 | 새 enum 없음 · **분석기 미연결 diff** · 2개 파일 · 금지 경로 · 테스트 삭제/skip/수정 0 |

### 8.1 관련 테스트 선행 실행 (실측)

```
수정 적용 후, 가장 가까운 다섯 파일 (신규 제외):
  test_lua_verified_provenance_audit · test_handler_binding_diagnostics
  · test_update_pipeline · test_update_coverage_contract_audit
  · rulings/test_data_audit
→ 175 passed / 0 skipped / 0 failed (2분 43초)

신규 파일 단독: 35 passed / 4 skipped (commit 게이트 4개)
```

### 8.2 전체 회귀 (실측)

(측정 후 기록한다.)

---

## 9. corpus 및 검색 산출물 비교

3-F-40 의 측정 스크립트에 **텍스트 분석 결과 분포**와 **availability 플래그별
켜진 카드 수** 두 항목을 더해 **24개**로 비교했다. "수정 전" 은 변경 파일을
`git stash` 로 되돌린 **실제 작업 트리**에서 측정했다 (추론이 아니다).

| # | 항목 | 기준 = 수정 후 | 결과 |
|---|---|---|---|
| 1–4 | 스크립트 12,702 · parser block 34,684 · attached card 12,687 · attached block 34,635 | 동일 | ✔ |
| 5–7 | `EffectSpec` / `CardAnalysis` / `coverage` digest | `b2623fe9…` · `602328c9…` · `9edd1a0e…` | ✔ |
| 8 | coverage 분자·분모 14항목 | 전부 동일 | ✔ |
| 9–10 | 등록·해결 Effect · 조건/비용/대상/행동/category | `26,352 / 8,283` · `12,438 / 5,007 / 5,516 / 18,280 / 20,484` | ✔ |
| 11–12 | 검색 결과·위치 digest | `d57c6ae1…` · `a822e760…` | ✔ |
| 13 | `EffectRef` 총수 / 불일치 | 34,635 / **0** | ✔ |
| 14 | `HandlerBinding` 상태별 (카드/블록) | `{matched: 12,687}` / `{matched: 34,635}` | ✔ |
| 15 | `AnalysisStatus` 상태별 | `lua_verified 12,687 · text_derived 756 · no_effect 684` | ✔ |
| 16 | 상태 × 결합 교차표 | 3항목 전부 동일 | ✔ |
| 17–18 | `LUA_VERIFIED` 생성 수 · 등록 효과 0개 | 12,687 · 215 | ✔ |
| 19 | `unbound_effects` | 0 | ✔ |
| 20–21 | 검색 카테고리/위치 수 · 3-F-32 대표 5장 | 31 / 31 · 전부 | ✔ |
| 22 | **텍스트 분석을 돌렸다면** (`would_yield` / `empty`) | **748 / 8** | ✔ |
| 23 | **availability 플래그별 켜진 카드 수** | `cdb 14,121 · official_text 14,121 · lua 12,687 · effect_analysis 12,687 · text_analysis 756` | ✔ |
| 24 | Phase 3-F-32 대표 사례 상세 | 동일 | ✔ |

**24개 비교 항목 전부 동일 (다름 0개).**

> 🔴 **같은 수치가 아닌 두 측정을 섞지 않는다.** §2 에 적은 `753 / 3` 과 위
> 22번의 `748 / 8` 은 **다른 빌드**에서 나온 값이다. 지문 스크립트는 3-F-38
> 이후 줄곧 `use_cache=False, use_korean=False` 로 돌고(그래야 다른 21개
> 항목이 비교 가능하다), CLI 가 쓰는 기본 빌드는 한국어 오버레이를 켠다.
> 직접 확인했다: 한국어 ON → `753 / 3`, OFF → `748 / 8`. 5장은 한국어
> 텍스트가 있어야 행동이 읽힌다. 테스트가 쓰는 `repository` 픽스처는
> 오버레이를 켜므로 `test_03` 의 기준값은 `753` 이다.

`availability` 플래그에서 `korean_available` 이 0인 것도 같은 이유다
(`use_korean=False`). 기준·수정 후 양쪽 모두 같은 조건에서 쟀다.

---

## 10. 남은 위험과 미해결 사항

| # | 내용 | 상태 |
|---|---|---|
| **N46** | 🟠 `TextEffectAnalyzer` 는 여전히 production 호출자가 0개다. 756장 중 753장에서 결과가 나올 텐데 쓰이지 않는다 | 미해결(의도) — 연결은 새 분석 경로. §5 가 금지한 "소비자 없다고 소비자 추가" |
| **N47** | 🟠 `CardProvenance.describe_ko()` 와 `DataAvailability.missing()` 은 호출자가 0개다. 이 Phase 가 **내용은 고쳤지만** 부르는 곳은 만들지 않았다 | 미해결(의도) — 같은 정보가 더 좁은 경로로 이미 전달된다 |
| **N48** | 🟠 필드별 출처(`fields{}`)와 충돌(`conflicts`)은 여전히 어떤 화면에도 안 나온다. 분석 CLI 는 상태 한 줄만 보여 준다 | 미해결 — 새 출력 설계 |
| **N49** | 🟠 텍스트 "결과 없음" 과 "시도하지 않음" 의 구분이 `TEXT_DERIVED` 집단에서는 도달 불가다 (`skipped_reason` 0건). 분석기를 연결하면 그때 의미가 생긴다 | 기록만 |
| **N50** | 🟠 텍스트 분석 결과가 한국어 오버레이 유무에 따라 달라진다 (753 vs 748). 분석기를 연결한다면 **어느 텍스트를 근거로 삼는지**를 먼저 정해야 한다 | 이 Phase 가 측정 중 발견 — 기록만 |
| N41·N42 (3-F-40) | — | 🟢 **표시 계층에서 해결** (§5) |
| N43~N45 (3-F-40) · N34~N37 (3-F-39) · N31~N33 (3-F-38) · N25~N28 (3-F-37) | — | 그대로 |

---

## 11. 다음 Phase 후보 (제안 1개)

**Phase 3-F-42 — 텍스트 기반 분석의 연결 여부 결정 (N46 + N49 + N50)**

이 Phase 는 "돌지 않는다" 를 측정하고 표시만 바로잡았다. 남은 결정은
**돌릴 것인가**이고, 그것은 세 가지를 먼저 정해야 하는 설계 결정이다.
① 어느 텍스트를 근거로 삼는가(한국어 오버레이 유무로 753/748 이 갈린다),
② 결과를 `CardAnalysis` 와 **섞지 않고** 어디에 둘 것인가,
③ `skipped_reason` 과 `is_empty` 를 사용자에게 어떻게 구분해 보일 것인가.
연결하면 756장의 효과 윤곽이 처음으로 사용자에게 도달하지만, Lua 분석과
같게 취급되는 순간 이 프로젝트가 3-F-36 이후 지켜 온 구분이 무너진다.
그래서 별도 지시가 필요하다.

---

이 Phase 를 완료한 뒤 다음 Phase 를 임의로 시작하지 않는다.
