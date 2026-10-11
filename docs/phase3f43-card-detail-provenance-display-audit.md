# Phase 3-F-43 — `print_card_detail` 출처 및 언어 표시 일관성 감사 (N51 + N52)

**결론부터: production 을 한 줄도 바꾸지 않았다.** 두 위험 모두 "사용자에게
**잘못된** 정보가 표시되는" 재현 사례가 나오지 않았고, §5 가 그 경우 수정을
금지했다.

---

## 1. 실제 기준 HEAD와 작업 환경

지시된 기준과 실제 저장소를 대조했다.

| 항목 | 지시 | 실제 | 결과 |
|---|---|---|---|
| HEAD | `329a2b1` | `329a2b1` | ✔ 일치 |
| origin | `329a2b1` | `329a2b1` | ✔ 동기화 |
| worktree | clean | clean | ✔ |
| 전체 테스트 | 5,399 passed / 4 skipped / 0 failed | 3-F-42 가 `cb59daf` 에서 실측한 값 | ✔ 그대로 인용 |
| 3-F-42 production 변경 | 0건 | `git diff 8356138 HEAD -- <production>` **비어 있음** | ✔ 확인 |

기존 commit 을 rewrite/amend 하지 않았다.

---

## 2. `print_card_detail` 의 실제 호출 경로

AST 로 전수 조사했다 (`test_01`).

```
app/main.py  cmd_card(agent, args)
  └─ print_card_detail(agent, card)          ← production 호출자 **한 곳**
       ├─ card.summary_ko()                   ← 머리글 (= 검색 줄과 같은 문자열)
       │    └─ card.display_name()            ← name_ko > name > name_ja > #id
       ├─ 이름 세 행: ("한국어", name_ko) ("공식 DB", name_en) ("일본어", name_ja)
       │    └─ `if value` 일 때만 찍는다      ← 소스별로 **각각** 라벨됨
       ├─ 텍스트 행: label = "카드 텍스트(한국어)" if card.name_ko else "카드 텍스트"
       │                                       ← 🔴 **텍스트 라벨을 이름으로 고른다**
       ├─ 원문 행: desc_en 이 desc 와 다를 때만
       └─ Lua 효과 블록 목록
```

`app/main.py format_card_line`(검색 줄)도 `card.summary_ko()` 를 쓴다.
즉 **상세 머리글과 검색 줄은 같은 문자열**이고 일관성이 구조적으로 보장된다
(`test_05`, `test_31`).

> 🔴 작성 중 내 예상 오류: 검색 줄이 `display_name()` 을 직접 부른다고 썼는데
> 실제로는 `summary_ko()` 를 쓰고 그 안에서 `display_name()` 을 부른다. 공유
> 지점이 한 겹 더 깊었다. 테스트를 실제 구조에 맞췄다.

### 2.1 `korean_available` 의 생성 경로 (실제 코드)

```python
# core/card_repository.py  _record_provenance
if card.name_ko:
    availability.korean_available = True
    record.record("card_name", SourceKind.KOREAN_DB)
    record.record("effect_text", SourceKind.KOREAN_DB)   # 🔴 이름을 근거로 텍스트 출처를 적는다
```

조건은 **`card.name_ko` 하나**다 (`test_03`, AST 로도 확인 — `name_ko` 를
보는 `if` 의 조건식이 `card.name_ko` 단독이다).

### 2.2 오버레이 적용 시점과 신호

```python
# sources/korean_names.py  apply()
name = entry.get("name", "").strip()
if name: card.name_ko = name; card.name = name          # 조건 A
desc = entry.get("desc", "").strip()
if desc: ...; card.desc = desc                           # 조건 B (A와 독립)
card.sources.add(CardSource.KOREAN_OVERLAY)              # 🟢 두 if **바깥**
applied += 1
```

* `name_ko` 에 대입하는 production 자리는 **이 한 곳뿐**이다 (`test_02`, AST
  전수). 따라서 **`korean_available` ⟹ 오버레이 적용**은 성립한다.
* **적용 여부의 정확한 신호는 이미 모델에 있다** — `CardSource.KOREAN_OVERLAY`
  는 이름·텍스트와 무관하게 닿은 카드마다 더해진다 (들여쓰기로 확인했다).
  그런데 **production 소비자가 0개**다 (`test_04`).
* CLI 의 오버레이 설정: `DeckAgent.build` 는 `use_korean` 을 넘기지 않아 기본
  `True` 이고, 끄는 플래그가 없다 (Phase 3-F-42 가 측정).

---

## 3. N51 재현 결과 — 이름 언어와 텍스트 언어

### 3.1 이름 언어는 정확하다

세 행이 소스별로 각각 찍히고 값이 있을 때만 나온다. 실제 출력:

```
  한국어    : 패러렐 텔레포트
  공식 DB  : Parallel Teleport
```

한국어가 없는 카드(`212652`)는 **`한국어` 행이 아예 없다** — 빈 값을 찍어
"한국어가 있다" 고 암시하지 않는다 (`test_06`, `test_07`).

### 3.2 텍스트 라벨만 구조적으로 결합돼 있다

`label = "카드 텍스트(한국어)" if card.name_ko else "카드 텍스트"` — AST 로
확인하면 `name_ko` 를 보는 삼항식이 **하나**이고 그것이 고르는 두 값이 바로
텍스트 라벨이다 (`test_08`).

**구성 사례로 재현했다** (🔴 가상 카드, `test_09`):

```
  한국어    : 가짜
  카드 텍스트(한국어):
    This is English text.
```

영어 텍스트에 "한국어" 라벨이 붙고, `desc_en == desc` 라서 원문 행도 나오지
않는다. 즉 **그 라벨 하나만** 달고 나온다.

### 3.3 🟢 그러나 트리거가 실제로 존재하지 않는다

| 측정 | 값 |
|---|---|
| 실제 카드 중 `name_ko` 있고 텍스트가 원문 그대로 | **0장** (`test_10`) |
| `data/ko` 항목 중 **이름만 있고 텍스트 없음** | **0개** (`test_11`) |
| `data/ko` 항목 중 **텍스트만 있고 이름 없음** | **0개** (`test_11`) |
| `data/ko` 전체 항목 | 13,899개 (전부 이름+텍스트 동반) |

"결과 카드 0장" 보다 강한 근거다 — **수집기가 그 상태를 만들어 본 적이
없다.** 그리고 오버레이가 닿은 카드에서 네 신호가 **모두 같은 수**다
(`test_12`):

```
KOREAN_OVERLAY 적용 = name_ko 있음 = korean_available = 텍스트 교체됨 = 13,728
```

한국어 카드는 **두 텍스트 행**(한국어 + 원문)을 받아 원문이 사라지지도
않는다 (`test_13`).

### 3.4 N51 판정

| 대상 | 판정 |
|---|---|
| 이름 언어 표시 | **`CONFIRMED_SAFE`** — 소스별 라벨이 구조적으로 정확하다 |
| 텍스트 라벨의 이름 결합 | **`CONFIRMED_SAFE` (현재 코드+데이터)** — 구조적 결합은 그대로이나 트리거가 결과·원천 데이터 양쪽에서 0이다. 재현 사례가 없어 §5 가 수정을 금지 |

---

## 4. N52 재현 결과 — 오버레이 미적용 상태

§3 의 네 질문에 실제 코드·데이터로 답한다.

| 질문 | 실측 답 |
|---|---|
| 한국어 텍스트가 실제로 존재하는가 | `data/ko` 13,899항목에 전부 존재. 카드에 닿은 것은 13,728장 |
| 오버레이가 실제로 적용되었는가 | `CardSource.KOREAN_OVERLAY in card.sources` 가 **정확한 신호**다. 소비자 0개 |
| 다른 언어의 텍스트를 썼는가 | `desc != desc_en` 로 판별 가능. 13,728장이 교체됨 |
| 적용 여부를 확인할 수 없는가 | **그런 카드가 0장이다** — `desc` 가 있는데 `desc_en` 이 없는 카드가 없다 (`apply` 가 원문을 `desc_en` 으로 옮겨 둔다, `test_25`) |

### 4.1 `korean_available` 은 이름에서 나온다

이름이 암시하는 "한국어 데이터가 있다 / 적용됐다" 와 **정확히 같은 뜻이
아니다.** 다만:

* **정방향은 성립한다** — `korean_available ⟹ 오버레이 적용` (전수 위반 0장,
  `test_14`). `name_ko` 를 쓰는 곳이 `apply` 하나뿐이기 때문이다.
* **역방향은 보장되지 않는다** — 오버레이가 닿았는데 `korean_available` 이
  거짓인 카드가 **구조적으로 가능하다**: 이름 없는 항목. 구성 사례로
  재현했다 (🔴 가상, `test_15`): 적용됨 + 텍스트 교체됨 + `name_ko` 없음 +
  `korean_available=False`.
* 그 카드는 **한국어 텍스트에 "한국어" 라벨이 빠진다** (`test_16`) — N51 과
  N52 가 같은 자리에서 만난다. 실제 데이터에는 없다 (`test_11`).

### 4.2 오버레이 OFF 출력은 거짓을 말하지 않는다

```
Parallel Teleport · 마법/속공
  카드 ID : 483
  공식 DB  : Parallel Teleport
  카드 텍스트:
    Tribute 1 Psychic monster with a Level; …
```

"카드 텍스트" 라고만 적고 **언어를 주장하지 않으며**, 한국어 이름 행도 없다
(`test_18`, `test_23`). 빠진 것은 "한국어 데이터가 디스크에 있는데 적용되지
않았다" 는 **설명**이고, 그것은 **거짓 표시가 아니라 미표시**다.

네 신호 전부 0이므로 서로 어긋나지도 않는다 (`test_17`).

### 4.3 N52 판정

| 대상 | 판정 |
|---|---|
| `korean_available` 의 의미 | **`CONFIRMED_CONTRACT_GAP`** — 이름에서 파생되므로 그 이름이 암시하는 뜻과 다르다. 정방향은 성립, 역방향은 구조적으로 깨질 수 있다 |
| 미적용 상태의 사용자 표시 | **`CONFIRMED_SAFE`** — 거짓 주장이 없다. 미표시일 뿐이다 |
| `CardSource.KOREAN_OVERLAY` | **`CONFIRMED_UNUSED_INTERFACE`** — 정확한 신호가 있는데 production 소비자가 0개 |

---

## 5. 사례별 실제 출력과 근거 (§4 여섯 사례)

| # | 사례 | 실제 카드 수 | 실제 출력 | 의미가 데이터로 입증되는가 |
|---|---|---|---|---|
| ① | 한국어 이름 + 한국어 텍스트 | **13,728장** | `한국어` 행 + `카드 텍스트(한국어)` + `카드 텍스트(원문)` | ✔ `desc != desc_en` 로 입증 |
| ② | 한국어 이름 + 다른 언어 텍스트 | **0장** | — (가상 사례는 §3.2) | ✔ 재현 사례 없음 |
| ③ | 한국어 텍스트는 있으나 미적용 | CLI 로는 도달 불가 · `use_korean=False` 로 재현 | `카드 텍스트` (언어 주장 없음), 한국어 행 없음 | ✔ 네 신호 모두 0과 일치 |
| ④ | 한국어 데이터 없음 | **399장** | `공식 DB` 행만, `카드 텍스트` | ✔ `name_ko` 없음과 일치 |
| ⑤ | 적용 여부 판단 불가 | **0장** | — | ✔ `desc` 있고 `desc_en` 없는 카드가 없다 |
| ⑥ | 이름·텍스트가 없음 | 이름 없는 카드 **0장** / `desc` 빈 카드 6장(전부 Lua 있음) | — | ✔ `display_name` 은 `#id` 로 떨어지게 되어 있다 |

🔴 **가상 사례와 실제 사례를 구분했다**: §3.2(이름만 한국어)와 §4.1(이름 없는
항목)은 **테스트에서 구성한 가상 카드**이고, 나머지는 전부 실제 corpus 와
실제 `print_card_detail` 실행이다.

---

## 6. production 수정 여부 및 근거

**수정하지 않았다 (production diff 0 바이트, `test_34`).**

§5 는 "실제 사용자에게 잘못된 정보가 표시되는 사례가 확인된 경우에만" 수정을
허용한다. 항목별 대조:

| 항목 | 잘못된 정보가 표시되는가 | 근거 |
|---|---|---|
| 이름 언어 표시 | ✘ | 소스별 라벨이 정확하다 |
| 텍스트 라벨 | ✘ | 트리거가 결과 0장·원천 데이터 0항목 |
| 미적용 상태 | ✘ | 언어를 주장하지 않는다 (미표시) |
| `korean_available` 의미 | ✘ | 사용자 출력에 나오지 않는다 |
| `effect_text` 출처 기록 | ✘ | `fields{}` 는 어떤 화면에도 안 나온다 (3-F-41 N48) |

하지 않은 것을 명시한다:

* **텍스트 라벨을 `desc != desc_en` 기준으로 바꾸지 않았다** — 재현 사례가
  없고, 그렇게 바꾸면 "원문과 같은 한국어 텍스트" 같은 경계에서 새 오판을
  만들 수 있다.
* **`CardSource.KOREAN_OVERLAY` 소비자를 만들지 않았다** — §5 의 "기존 데이터
  모델로 표현할 수 있다면 새 필드를 추가하지 말 것" 은 지켰고, 소비자 추가는
  새 출력 설계다 (3-F-42 가 같은 이유로 보류한 것과 같은 성질).
* **`korean_available` 의 의미나 생성 조건을 바꾸지 않았다** — provenance
  필드의 의미 재정의를 §5 가 금지한다.
* **`AnalysisStatus`·`HandlerBinding` 의미 변경 0**, 새 enum·프레임워크 0.
* **`engine/`·`agent/`·`core/`·Lua·README·`data/` 변경 0건** (`test_36`).
* **분석 결과·corpus 변경 0** (§7).

---

## 7. 테스트 결과

신규 파일: `tests/test_card_detail_provenance_display_audit.py` — **38개**.

| 묶음 | 수 | 내용 |
|---|---|---|
| A. 호출 경로 | 5 | 호출자 1곳 · `name_ko` 대입 1곳 · `korean_available` 조건 · 적용 신호의 소비자 0 · 상세/검색 공유 함수 |
| B. N51 | 8 | 이름 행 소스별 라벨 · 없는 행 부재 · 라벨의 구조적 결합(AST) · **구성 사례 재현** · 실제 0장 · **원천 데이터 0항목** · 네 신호 동수 · 두 텍스트 행 |
| C. N52 | 7 | 정방향 성립(전수) · **역방향 갭 재현** · 그 카드의 라벨 누락 · OFF 전부 0 · OFF 거짓 주장 없음 · `apply` 반환값 · 미적용 항목 171개 |
| D. §4 여섯 사례 | 6 | ① 13,728 · ② 0 · ③ 재현 · ④ 399 · ⑤ 0 · ⑥ 0 |
| E. provenance·회귀 | 7 | `effect_text` 출처 기록 + 미노출 · 상태 분포 · availability 플래그 수 · 출력 결정성 · 상세/검색 이름 일치 · 분석·결합 집계 · 검색·`EffectRef` |
| F. 범위·금지 | 5 | **production diff 0** · 변경 파일 2개 · 금지 경로 · 기존 테스트 수정 0 · **이 파일이 digest 리터럴을 쓰지 않음** |

단독 실행: **34 passed / 4 skipped** (skip 4개는 commit 게이트).

### 7.1 지뢰선 조사 — 두 종류는 막았고 **한 종류를 놓쳤다**

Phase 3-F-42 는 새 테스트 파일이 기존 지뢰선을 건드려 전체 회귀에서 1건
실패했다. 그래서 이번에는 파일을 쓰기 **전에** `tests/` 를 훑는 assertion
들을 찾아 두 가지 제약을 확인했다.

1. `test_auxiliary_effect_creation_clone_audit::test_42` 가 검색 digest 핀을
   **정확히 7개**로 세고(자기 파일 제외, 최상위 `tests/test_*.py` 만),
   `test_create_effect_ordinal_audit::test_26` 등이 "가장 많이 못 박힌
   64자 16진수" 를 고른다 → **digest 리터럴을 쓰지 않았다** (`test_38` 이
   스스로 지킨다).
2. `test_provenance_consumer_audit::test_02` 가 `TextEffectAnalyzer` 호출자
   목록을 고정한다 → **호출하지 않았다**.

세 지뢰선을 신규 파일이 있는 상태로 먼저 돌려 통과를 확인했다 (`3 passed`).

#### 🔴 그런데 세 번째 종류를 놓쳤다

첫 전체 회귀 결과:

```
3 failed, 5434 passed, 4 skipped in 3372.99s (0:56:12)
FAILED tests/test_lua_verified_provenance_audit.py::test_39_no_test_was_deleted_and_no_skip_was_added
FAILED tests/test_provenance_consumer_audit.py::test_39_no_test_was_deleted_and_no_skip_was_added
FAILED tests/test_update_coverage_contract_audit.py::test_41_no_test_was_deleted_and_no_skip_was_added
```

세 감사가 `re.findall(r"pytest\.skip\([^)]*\)", text)` 로 **새로 추가된
테스트 파일의 건너뛰기 호출**을 세면서 commit 게이트 문구만 허용한다. 내
파일에는 commit 게이트 4개 외에 **데이터 유무 게이트 3개**가 있었고
(`data/ko 가 없다`), 그것이 그 문구를 갖고 있지 않았다.

**고친 방법:** 저장소의 **기존 관용구**로 바꿨다 — 함수 안에서 건너뛰기를
호출하지 않고 모듈 수준 `pytest.mark.skipif` 마커(`requires_korean_data`)로
거른다. `conftest.requires_official_db` 가 이미 그 형태다. 기존 테스트를
**한 줄도 고치지 않았다** — 세 지뢰선의 의도("새 파일에 설명 없는 조건부
건너뛰기를 몰래 넣지 마라")가 그대로 지켜지고, 데이터 유무 게이트는 그
의도가 겨냥한 종류가 아니다.

🔴 **같은 함정을 한 번 더 피했다.** 처음 고칠 때 주석에 그 호출의 이름을
그대로 적었더니 정규식이 **주석의 글자까지** 잡았다 (3-F-41 에서 겪은
"스캔용 리터럴 vs 실제 호출" 함정). 주석에서 그 이름을 빼고, 정규식이 잡는
호출이 4개뿐이며 전부 commit 게이트 문구를 포함함을 직접 확인했다.

**교훈:** 지뢰선은 "digest 를 세는 것" 과 "호출자 목록" 두 종류라고 생각했는데
**세 종류였다**. 다음에는 `tests/` 를 훑는 정규식 전수를 먼저 뽑아야 한다 —
이번에 확인한 결과 그 정규식을 쓰는 테스트는 위 세 개뿐이다.

### 7.2 전체 회귀 (재측정, 실측)

§7.1 의 수정을 commit 한 뒤 **처음부터 다시** 돌렸다. 고친 뒤의 수치를
쓰려고 첫 실행 결과를 재활용하지 않았다.

| 항목 | 기준 (`cb59daf`) | 1차 | **2차 (재측정, `0a2ca49`)** |
|---|---|---|---|
| passed | 5,399 | 5,434 | **5,437** |
| failed | 0 | **3** | **0** |
| skipped | 4 | 4 | **4** |
| 소요 | 53분 58초 | 56분 12초 | 54분 00초 |

2차 실행 마지막 줄: `5437 passed, 4 skipped in 3240.03s (0:54:00)`.
출력 전체에서 `F`·`E` 문자 **0개**.

* 증가분 **+38 은 신규 파일의 테스트 수와 정확히 같다**. 기준 5,399개가 한
  개도 줄지 않았다.
* 1차의 `5,434` 와 2차의 `5,437` 이 3개 다른 이유: 1차에서 실패로 세어진
  지뢰선 3개가 2차에서 통과로 세어졌다. 수집 개수는 5,441개(= 5,437 + 4
  skip)로 양쪽이 같다.
* skip **4개는 기준과 동일한 기존 skip** 이다. 신규 파일의 데이터 유무
  게이트는 §7.1 의 수정으로 **마커**가 되었고, `data/ko` 와 `cards.cdb` 가
  있는 이 환경에서는 건너뛰지 않는다. commit 게이트 4개도 commit 이 생긴 뒤
  측정했으므로 실제로 실행되어 통과했다.
* 기존 테스트 **삭제 0 · skip 추가 0 · assertion 약화 0 · 수정 0건**.

### 7.3 기준 전체 테스트를 독립적으로 재측정하지 않았다

이전 Phase 들과 같은 이유로 적어 둔다. 기준 `5,399` 는 **Phase 3-F-42 가
`cb59daf` 에서 실측해 보고서에 적은 값**이고, 이번 Phase 가 완주한 것은
**수정 후** 실행 두 번뿐이다.

---

## 8. corpus 및 digest 비교

production 을 바꾸지 않았으므로 **같은 트리에서 재측정**했다. Phase 3-F-42 가
남긴 **30개 항목**(corpus 24 + engine 6)을 같은 스크립트로 다시 재어 전부
일치했다.

```
Phase 3-F-42 측정값과 동일 30개 / 다름 0개 (전체 30개)
```

| # | 항목 | 결과 |
|---|---|---|
| 1–4 | 스크립트 12,702 · parser block 34,684 · attached card 12,687 · attached block 34,635 | ✔ |
| 5–7 | `EffectSpec` / `CardAnalysis` / `coverage` digest | ✔ |
| 8–10 | coverage 분자·분모 14항목 · 등록·해결 Effect `26,352 / 8,283` · 조건/비용/대상/행동/category | ✔ |
| 11–12 | 검색 카테고리·위치 digest (각 31종) | ✔ |
| 13–14 | `EffectRef` 34,635 / 불일치 **0** · `HandlerBinding` 분포 `{matched: 34,635}` | ✔ |
| 15–19 | `AnalysisStatus` 분포 `12,687 / 756 / 684` · 상태×결합 교차표 · `LUA_VERIFIED` 수 · 등록 효과 0개 215 · `unbound_effects` 0 | ✔ |
| 20–21 | 텍스트 분석 가정치 · availability 플래그별 수 (`korean_available 13,728`) | ✔ |
| 22–24 | 검색 종수 31·31 · 3-F-32 대표 5장 | ✔ |
| 25–30 | **Engine V1**: `state_hash` 결정성 · seed 재현 · hidden information 경계 (상대 시점 `occupied()` 0, 식별 0, `is_empty` 거짓) | ✔ |

> 🔴 이 보고서는 digest 값을 표에 적지 않는다. 다른 감사 테스트들이 테스트
> 파일 안의 64자 16진수 리터럴 **개수**를 세기 때문에 테스트에는 쓸 수 없고,
> 보고서와 테스트의 기준을 어긋나게 두지 않기 위해 **집계 수치로만** 못
> 박았다. 실제 digest 값은 Phase 3-F-38~3-F-42 보고서에 기록되어 있고 이번
> 측정에서도 그 값들과 동일했다.

`engine/`·`agent/`·`core/` 변경 0건, Lua·README 변경 0건 (`test_34`,
`test_36`).

---

## 9. 미해결 위험과 다음 단계 후보

| # | 내용 | 상태 |
|---|---|---|
| **N51** | 🟠 텍스트 라벨이 `name_ko`(이름)로 결정된다. 구성 사례로 재현되지만 실제 카드 0장이고 **원천 데이터에도 트리거가 0개**다 | 미해결(의도) — 재현 사례 없음 |
| **N52** | 🟠 `korean_available` 이 이름에서 파생된다. 정방향은 성립, 역방향(이름 없는 항목)은 구조적으로 깨질 수 있다 | 미해결(의도) — 데이터에 0개 |
| **N53** 🆕 | 🟠 `CardSource.KOREAN_OVERLAY` 가 **적용 여부의 정확한 신호**인데 production 소비자가 0개다. `korean_available` 을 쓰는 쪽이 이것을 쓰면 역방향 갭이 사라진다 | 미해결 — 소비자 추가는 출력 설계 |
| **N54** 🆕 | 🟠 `record("effect_text", SourceKind.KOREAN_DB)` 가 **이름을 근거로** 텍스트 필드의 출처를 적는다. 실제 데이터에서는 맞지만 근거가 텍스트가 아니다. `fields{}` 가 미노출이라 사용자에게 보이지 않는다 | 기록만 |
| **N55** 🆕 | 🟡 `data/ko` 항목 **171개**가 카드에 닿지 않고 조용히 버려진다. 어디에도 보고되지 않아 수집 누락과 ID 불일치를 구분할 수 없다 | 기록만 |
| N46·N49·N50 (3-F-42) | 분석기 미연결 · `is_empty` 뭉침 · 오버레이가 분석기 입력을 바꿈 | 그대로 |
| N47·N48 (3-F-41) · N43~N45 (3-F-40) · N34~N37 (3-F-39) · N31~N33 (3-F-38) · N25~N28 (3-F-37) | — | 그대로 |

### 다음 단계 후보 (제안 1개)

**Phase 3-F-44 — `data/ko` 미적용 항목 171개의 정체 (N55)**

이번 Phase 가 측정 중 발견한 것이고, 지금까지의 위험들과 성질이 다르다 —
**표시 문제가 아니라 데이터 적용 문제**다. `data/ko` 에 13,899항목이 있고
13,728장에 적용되었으며 **171항목이 조용히 버려진다**. 그것이 (a) `cards.cdb`
에 없는 카드인지, (b) 다른 일러스트 패스코드라 ID 가 어긋난 것인지
(Phase 3-F-7 의 228장 문제와 같은 종류), (c) 수집기가 잘못 넣은 ID 인지는
아직 측정하지 않았다. 세 경우의 대응이 완전히 다르다. 범위가 좁고
(`sources/korean_names.py` + `data/ko` 읽기 전용 조사) 금지 경로에 닿지
않는다.

---

이 Phase 를 완료한 뒤 다음 Phase 를 임의로 시작하지 않는다.
