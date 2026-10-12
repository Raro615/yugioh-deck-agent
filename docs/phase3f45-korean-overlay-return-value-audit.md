# Phase 3-F-45 — Korean Overlay 반환값 소비 및 집계 경계 감사

**결론부터:**

* `apply()` 의 반환값은 **파생 통계**다. 버려지는 값(13,892)은
  `CardSource.KOREAN_OVERLAY` 플래그로 **공개 API 만으로 정확히 재계산**
  된다. 복구 불가능한 정보가 아니다 → **`CONFIRMED_SAFE`**.
* 🔴 **Phase 3-F-44 가 제안한 "반환값 보존" 은 겨냥이 틀렸다.** 실제로
  도달 가능한 실패 모드에서는 `apply()` 가 **호출조차 되지 않는다**
  (`autoload()` 가 빈 소스를 돌려주면 `if korean_source:` 가 거짓).
  반환값을 받아 두어도 그 실패는 잡히지 않는다.
* 다만 **갱신 파이프라인의 보고에는 공백이 있다.** 한국어 오버레이가
  **전면 미적용**이어도 `validate()` 와 `summarise()` 의 출력은
  **바이트 단위로 같다** (실측). 이것은 반환값 계층이 아니라 **요약 보고
  계층**의 문제다 → **`CONFIRMED_CONTRACT_GAP`**.
* 그 공백에 사용자 피해는 없다. 전면 미적용은 카드 출력 자체가
  영어로 바뀌어 **즉시 눈에 보인다** (실측).
* `13,899` 과 `13,892` 는 **같은 모집단이 아니다.** 입력 계층과 결합
  계층이고, 차이 7은 "레코드가 없는 항목" 하나로 닫힌다.
* **production 을 한 줄도 바꾸지 않았다** (audit-only).

---

## 1. 작업 전 기준 상태

| 항목 | 지시 | 실제 (작업 전) |
|---|---|---|
| 기준 commit | `cdeaf7a` | **`cdeaf7a`** ✔ 일치 |
| origin | — | `cdeaf7a` ✔ |
| worktree | — | clean ✔ |
| 브랜치 | — | `claude/pensive-goodall-te1egy` ✔ |

기준이 지시와 같으므로 reset·checkout 하지 않았다. 직전 Phase 3-F-44 의
commit 3개(`ee12991` · `ed3ea4c` · `cdeaf7a`)가 모두 있다.

### 1.1 전제의 재검증

3-F-44 의 결론을 전제로 받되 **이번에 다시 측정했다.**

| 항목 | 3-F-44 | 이번 재측정 | 일치 |
|---|---|---|---|
| `data/ko` 항목 | 13,899 | **13,899** | ✔ |
| `apply()` 반환값 | 13,892 | **13,892** | ✔ |
| 미적용 | 7 | **7** | ✔ |
| 적용된 alias 판본 | 164 | **164** | ✔ |

---

## 2. `apply()` 정의와 반환값의 실제 의미

`sources/korean_names.py:145`

```python
def apply(self, cards: dict[int, Card]) -> int:
    applied = 0
    for card_id, entry in self.entries.items():
        card = cards.get(card_id)
        if card is None:
            continue
        ...
        card.sources.add(CardSource.KOREAN_OVERLAY)
        applied += 1
    return applied
```

반환값의 정확한 정의는 **`|entries ∩ cards.keys()|`** 다. 실측으로
확인했다.

| 측정 | 값 |
|---|---|
| `len(entries)` | 13,899 |
| `len(OfficialDatabaseSource.load())` | 14,514 |
| `apply()` 반환값 | **13,892** |
| `len(set(entries) & set(load))` | **13,892** |
| `KOREAN_OVERLAY` 가 붙은 카드 수 | **13,892** |

🔴 **세 값이 전부 같다.** 반환값은 "입력 항목 수" 가 아니고 "카드 수"
도 아니라 **결합에 성공한 수**이며, 그 수는 카드 객체에 남는 플래그로
**완전히 재구성된다.**

부수 확인: `data/ko` 항목 13,899개 전부가 이름과 텍스트를 **둘 다** 갖고
있다 (이름만 0개 · 텍스트만 0개 · 둘 다 빈 것 0개). 그래서 `name_ko` 로
세도 같은 13,892가 나온다 — 우연이 아니라 데이터의 성질이다.

---

## 3. 직접 호출부 전수 조사

AST 로 저장소 전체의 `*.apply(...)` 호출을 셌다. 문자열 검색은 주석과
스캔용 리터럴까지 세므로 쓰지 않았다.

| 범위 | 호출 자리 | 반환값 버림 |
|---|---|---|
| production (9개 디렉터리) | **12** | **1** |
| `tests/` | **205** | **66** |
| 합계 | **217** | 67 |

### 3.1 production 12곳

| 자리 | 호출 | 반환값 |
|---|---|---|
| `core/card_repository.py:222` | `korean_source.apply(cards)` | **버림** |
| `agent/runner.py:204` | `self.duel.apply(decision.action)` | 사용 |
| `agent/simulation.py:228·263·311` | `fork.apply(action)` | 사용 |
| `engine/action_execution.py:312` | `handler.apply(state, action)` | 사용 |
| `engine/battle.py:452` | `self.executor.apply(...)` | 사용 |
| `engine/effect/executor.py:1772` | `handler.apply(...)` | 사용 |
| `engine/normal_summon.py:215` | `self.executor.apply(...)` | 사용 |
| `engine/set_card.py:361·373` | `self.executor.apply(...)` | 사용 |
| `engine/special_summon.py:152` | `self.executor.apply(...)` | 사용 |

🔴 **3-F-44 의 진술을 두 군데 정정·한정한다.**

1. **범위.** "반환값을 버리는 유일한 `*.apply(...)` 호출" 은
   **production 범위**의 말이다. 테스트 코드에는 버리는 호출이 66곳
   있다. 저장소 전체에 대한 진술로 읽으면 틀린다.
2. **비교의 성질.** 나머지 11곳은 **같은 메서드가 아니다.** 전부
   엔진의 액션 실행기(`handler.apply(state, action)` 류)이고 반환값이
   다음 상태라서 **구조적으로 받지 않을 수 없다.** 따라서 "11곳은 쓰는데
   1곳만 버린다" 를 **관례 위반의 근거로 쓸 수 없다.** 이름만 같은
   서로 무관한 메서드들이다. 3-F-44 가 이 비교를 근거로 제시한 것은
   과했고, 여기서 바로잡는다.

### 3.2 유일한 호출부의 문맥

`core/card_repository.py:219-222`

```python
if korean_source is None and use_korean:
    korean_source = KoreanTextSource.autoload()
if korean_source:
    korean_source.apply(cards)
```

호출 순서: `official.load()` → Lua 첨부 → 상수 해석 → **오버레이** →
`_record_provenance()` → `cls(cards, ...)`. 오버레이는 **중복 제거 전**,
**alias 판본을 포함한 전체 레코드**에 적용된다. 이것이 164의 출처다.

### 3.3 반환값의 실제 소비자 — 테스트

`apply()` 의 반환값은 **이미 계약으로 검증되고 있다.**

| 테스트 | 단정 |
|---|---|
| `test_korean_overlay.py:34` | `source.apply(cards) == 1` |
| `test_korean_overlay.py:49` | `KoreanTextSource.load(path).apply(cards) == 1` |
| `test_korean_overlay.py:56` | `source.apply(_sample_cards()) == 0` (디렉터리 없음) |
| `test_card_detail_provenance_display_audit.py:484` | 비교 단정 |
| `test_korean_overlay_display_boundary_audit.py:366` | 비교 단정 |

즉 반환값은 **단위 테스트가 결합 성공을 확인하는 수단**이고, 그
소비자는 이미 존재한다. production 호출부가 쓰지 않는다는 것은 "소비자가
없다" 가 아니라 **"그 호출부에는 필요가 없다"** 는 뜻이다.

---

## 4. `13,899` 대 `13,892` — 계층별 설명

### 4.1 같은 모집단이 아니다

| 계층 | 모집단 | 한국어 적용 |
|---|---|---|
| 입력 | `data/ko` 항목 **13,899** | — |
| 결합 | `OfficialDatabaseSource.load()` **14,514** | **13,892** |
| 저장소 | `repo` 전체 레코드 **14,520** | **13,892** |
| 사용자 | 정본 카드 **14,127** | **13,728** |

### 4.2 세 식이 닫힌다 (실측)

```
13,899 (입력 항목)  -  13,892 (결합 성공)  =      7   레코드 자체가 없음
13,892 (결합 성공)  -  13,728 (정본 적용)  =    164   적용된 alias 판본
14,127 (정본 카드)  -  13,728 (정본 적용)  =    399   한국어 데이터가 없는 정본
```

`164` 는 전부 alias 판본임을 확인했다 (정본이 섞인 것 **0개**). 그래서
이것은 **손실이 아니라 집계 기준의 차이**다.

🔴 **`399` 는 지금까지 어느 출력에도 나오지 않은 수다.** 그리고 세 계층
중 **사용자에게 의미가 있는 유일한 수**다. 사용자는 정본 카드를 보고,
그중 399장에는 한국어 데이터가 없다. `7` 과 `164` 는 내부 집계의 차이다.

### 4.3 어느 계층에서 설명해야 하는가 (§2 질문 6)

| 수 | 설명 계층 | 이유 |
|---|---|---|
| 7 | **오버레이 입력 대 기준 DB** | 카드 레코드가 없다. 저장소도 CLI 도 관여하지 않는다 |
| 164 | **집계 기준(정본 대 판본)** | 데이터는 정상 적용됐다. 세는 기준이 다를 뿐 |
| 399 | **카드 데이터 상태** | 사용자가 실제로 마주치는 유일한 결핍 |

세 수를 한 줄로 합치면 안 된다. Phase 3-F-43 의 "171" 오류가 정확히
그 합치기(입력 계층을 사용자 계층과 직접 뺀 것)에서 나왔다.

### 4.4 두 production 경로가 서로 다른 계층을 센다

| 경로 | 세는 것 | 값 |
|---|---|---|
| `KoreanDatabaseAdapter.load_records()` | 입력 항목 | **13,899** |
| `KoreanTextSource.apply()` | 결합 성공 | **13,892** |

갱신 파이프라인이 실제로 찍는 수는 앞쪽이다. 실행해 확인했다
(`python3 -m scripts.update_cards --check --source korean`).

```
소스별 변경 내역
------------------------------------------------------------
  korean_db        new=0  changed=0  removed=0  unchanged=13,899

다시 처리할 카드: 0장
```

🔴 이 `13,899` 는 **틀린 수가 아니다.** 제목이 `소스별 변경 내역` 이고
세는 대상이 소스 레코드이므로 입력 계층의 수가 맞다. "13,899장에 한국어가
적용됐다" 고 주장하지 않는다. 두 수를 억지로 맞추려 하면 한쪽 계층이
사라진다.

---

## 5. 반환값을 버려서 실제 문제가 생기는가 (§2 질문 4)

### 5.1 전면 미적용을 재현해 보았다

`CardRepository.build(use_korean=False)` 로 오버레이를 완전히 끄고
`validate()` 와 `summarise()` 를 돌렸다.

| 항목 | 정상 적용 | 전면 미적용 |
|---|---|---|
| `validate()` 문제 목록 | `[]` | **`[]`** |
| `summarise()` 에 "한국어" 등장 | 아니오 | **아니오** |
| `summarise()` 출력 길이 | 319 | **319** |
| 출력 내용 | — | **바이트 단위로 동일** |

🔴 **갱신 요약은 한국어 오버레이에 대해 아무것도 말하지 않는다.**
13,892장이 적용돼도, 0장이 적용돼도 같은 글자가 나온다. `validate()`
에도 한국어 관련 검사가 없다.

### 5.2 그러나 사용자에게는 **즉시 보인다**

같은 두 빌드로 `print_card_detail` 을 실제로 돌렸다 (카드 483).

| | 정상 적용 | 전면 미적용 |
|---|---|---|
| 제목 | `패러렐 텔레포트 · 마법/속공` | **`Parallel Teleport · 마법/속공`** |
| `한국어` 행 | 있음 | **없음** |
| 텍스트 라벨 | `카드 텍스트(한국어)` | **`카드 텍스트`** |
| 본문 | 한국어 | **영어 원문** |

사용자가 "한국어가 적용됐다" 고 오해할 수 없다. 출력 자체가 신호다.
복구 방법도 있다 — `data/ko` 를 복원하거나 수집기를 다시 돌린다.

### 5.3 🔴 도달 가능한 실패 모드에서는 반환값이 **존재하지 않는다**

`autoload()` 의 실제 동작 (`sources/korean_names.py:74-97`):

```
data/ko 가 없거나 모든 후보 파일 파싱 실패
  → cls() 빈 소스를 돌려준다 (docstring: "없으면 비어 있는 소스를
    돌려준다(오류가 아니다)" — 의도된 설계)
  → if korean_source:  ← __bool__ 이 거짓
  → apply() 가 호출되지 않는다
  → 반환값이라는 것이 아예 생기지 않는다
```

실측: `autoload("/없는 경로")` → `entries=0`, `bool=False`.

그리고 `use_korean=False` 는 **어떤 CLI 진입점에서도 도달할 수 없다**
(`DeckAgent.build()` 가 넘기지 않는다. `use_korean` 을 쓰는 자리는
`core/card_repository.py` 안의 4곳뿐이다).

**따라서 3-F-44 가 제안한 "반환값 보존" 은 실패를 잡지 못한다.**
도달 가능한 실패에서 `apply()` 는 돌지 않으므로, 받아 둘 값이 없다.
보고 공백을 메우려면 **반환값이 아니라 저장소 상태**를 세어야 한다 —
그리고 그것은 §6 처럼 공개 API 로 이미 가능하다.

---

## 6. 새 API 나 추상화가 필요한가 (§2 질문 7)

**필요하지 않다.** 실측으로 확인했다.

```python
sum(1 for c in repository.all_cards(include_alternates=True)
    if CardSource.KOREAN_OVERLAY in c.sources)
#  -> 13,892   (apply() 가 돌려주던 값과 정확히 같다)
```

`all_cards(include_alternates=True)` 는 공개 메서드이고
`CardSource.KOREAN_OVERLAY` 는 공개 enum 이다. 정본 기준 `13,728` 과
한국어 없는 정본 `399` 도 `all_cards()` 로 같은 방식으로 나온다.

새 enum · 새 공개 API · 새 추상화 · 진단 전용 계층 — **하나도 필요
없다.** 이 결론은 §4 금지 조항과도 같은 방향이다.

---

## 7. 발견 사항별 판정

| # | 발견 | 판정 | 근거 |
|---|---|---|---|
| N53 | `core/card_repository.py:222` 가 `apply()` 반환값을 버린다 | **`CONFIRMED_SAFE`** | 반환값 == `KOREAN_OVERLAY` 플래그 수 (§2). 공개 API 로 정확히 재계산된다 (§6). 호출부는 그 수를 쓰지 않고, 쓸 소비자도 없다 (§4.4). 버려도 복구 불가능한 정보가 없다 |
| N54 | 갱신 요약(`summarise`/`validate`)에 한국어 계층이 **전혀 없다** | **`CONFIRMED_CONTRACT_GAP`** | 전면 미적용에서도 출력이 바이트 단위로 같다 (§5.1, 실측). 사용자 피해는 재현되지 않았다 (§5.2) — 그래서 버그가 아니라 보고 계약의 공백이다 |
| N55 | 3-F-44 의 "유일한 호출" 진술이 범위·성질 양쪽에서 과하다 | **`CONFIRMED_CONTRACT_GAP`** (문서 계약) | production 한정이며(테스트 66곳), 나머지 11곳은 이름만 같은 엔진 실행기다 (§3.1). 여기서 정정했다 |
| N56 | `autoload()` 의 조용한 빈 소스 복귀 | **`CONFIRMED_SAFE`** | docstring 에 "오류가 아니다" 로 명시된 의도된 설계이고, 결과가 사용자 출력에 즉시 드러난다 (§5.2, 실측) |
| N57 | `13,899` vs `13,892` 가 다른 모집단인데 한 자리에서 비교되는가 | **`CONFIRMED_SAFE`** | 비교하는 production 자리가 없다. 어댑터는 입력 계층만, 저장소는 결합 계층만 센다 (§4.4). 둘을 섞어 쓴 것은 Phase 3-F-43 **보고서**였고 3-F-43-K0 이 이미 정정했다 |
| N58 | `399` (한국어 없는 정본 카드)가 어느 출력에도 없다 | **`UNKNOWN_BY_DESIGN`** | 이 수를 보여 달라는 요구사항이나 소비자가 코드·문서 어디에도 없다. 필요 여부를 코드만으로 판단할 수 없다. 가능성만으로 결함이라고 선언하지 않는다 |

가능성만으로 버그라고 선언하지 않았다. 반환값을 무시한다는 사실만으로
수정 필요성을 주장하지 않았다 (§3 분류 원칙).

---

## 8. production 수정 여부

🔴 **수정하지 않았다.** audit-only (§4). production 변경 **0건**.

재현된 사용자 피해가 없고, 유일한 실질 공백(N54)은 반환값 계층이 아니라
요약 보고 계층의 문제이며, 그 수정은 "갱신 요약에 행을 추가" 라는
**출력 정책 변경**이라 이번 단계의 범위가 아니다.

### 8.1 최소 수정안 (제안만 — 실행하지 않았다)

N54 를 고치기로 **결정한다면** 최소 변경은 이렇다.

```
scripts/update_cards.py 의 summarise() 에 한 행 추가:
  "한국어 데이터 있음 : {N}장 / 없음 : {M}장"   (정본 기준)
  N = all_cards() 중 KOREAN_OVERLAY 보유 수   (= 13,728)
  M = len(all_cards()) - N                    (=    399)
```

이 안이 지켜야 하는 것:

* **반환값을 받는 방향으로 고치지 않는다.** 도달 가능한 실패에서는
  `apply()` 가 호출되지 않으므로 반환값으로는 잡히지 않는다 (§5.3).
* **정본 기준으로 센다.** 사용자가 보는 계층이고, `164` 를 "미적용" 으로
  오해하게 만들지 않는다 (§4.3).
* **새 API 를 만들지 않는다.** 공개 `all_cards()` 로 충분하다 (§6).
* `7` 을 이 행에 섞지 않는다. 그것은 카드가 없는 항목이고 사용자 계층의
  수가 아니다.

🔴 이것은 **제안**이다. 실행 여부는 다음 Phase 의 지시를 기다린다.

---

## 9. 변경 파일 · 테스트 · 회귀

### 9.1 변경 파일

| 파일 | 종류 | 상태 |
|---|---|---|
| `tests/test_korean_overlay_return_value_audit.py` | 신규 테스트 | 추가 |
| `docs/phase3f45-korean-overlay-return-value-audit.md` | 신규 보고서 | 추가 |
| production 파일 | — | **0건** |

기존 테스트 삭제·수정·skip 추가·assertion 약화 **모두 0건**.
production 변경이 없으므로 빈 production commit 을 만들지 않았다.

### 9.2 신규 테스트가 필요하다고 판단한 이유

§5 의 판정 `CONFIRMED_SAFE` 는 **"반환값 == 플래그 수"** 라는 등식에
전적으로 의존한다. 이 등식이 깨지면(예: 이후에 `apply()` 가 플래그를
붙이지 않고 세거나, 조건부로 세게 되면) "버려도 안전하다" 는 판단이
**조용히 무너진다.** 그래서 등식과 세 계층의 닫힘을 못 박았다.
수를 채우기 위한 테스트는 만들지 않았다 — 15개 전부 §2 의 질문 하나에
직접 대응한다.

`tests/test_korean_overlay_return_value_audit.py` — 15개.

| 구획 | 내용 | 수 |
|---|---|---|
| A | 반환값의 의미 (결합 수 · 플래그 등식 · 빈 소스 · 상한) | 4 |
| B | 공개 API 재계산 (등식 · 두 증거의 일치 이유) | 2 |
| C | 세 계층의 닫힘 (입력 · 정본 · 카드) + 두 경로의 모집단 | 4 |
| D | 3-F-44 진술의 범위 한정 | 1 |
| E | 범위·금지 자체 점검 (production 0건 · tripwire 준수) | 4 |

측정 결과:

```
12 passed, 3 skipped in 14.63s
```

skip 3개는 전부 `이 Phase 의 commit 이 아직 없다` 게이트다. commit 이
생긴 뒤에는 실행된다 (§9.4).

### 9.3 Tripwire 사전 점검

전체 회귀 **전에** 과거에 실제로 깨뜨린 tripwire 들을 먼저 돌렸다
(digest 리터럴을 세는 감사 · 텍스트 분석기 인스턴스화 파일 목록 · 신규
테스트 파일의 skip 문구 검사), 한국어 오버레이 관련 기존 테스트까지 함께.

| 대상 | 파일 수 | 결과 |
|---|---|---|
| `auxiliary_effect_creation_clone` · `create_effect_ordinal` · `provenance_consumer` · `update_coverage_contract` · `lua_verified_provenance` · `korean_overlay_unapplied` · `korean_overlay_display_boundary` · `korean_overlay` · `handler_binding_diagnostics` · `text_analysis_consumer_policy` · `card_detail_provenance_display` · `chain_resolution_link_result_invariant` · `result_actor_provenance_contract` | 13 | **450 passed in 1178.74s (0:19:38)** |

**실패 0건.** 신규 파일이 기존 감사 전제를 하나도 깨지 않는다.

### 9.4 전체 회귀

실제로 실행했다. `python3 -m pytest -q -p no:randomly` (전체).

```
5516 passed, 4 skipped in 4370.05s (1:12:50)
```

**실패 0건.** 숫자가 전부 설명된다.

| 항목 | 기준 (`cdeaf7a`) | 이번 (`a312415`) | 차이 |
|---|---|---|---|
| passed | 5,501 | **5,516** | **+15** |
| skipped | 4 | **4** | 0 |
| failed | 0 | **0** | 0 |
| 수집 합계 | 5,505 | **5,520** | **+15** |

+15 는 신규 파일의 테스트 함수 수와 **정확히 일치한다** (parametrize 를
쓰지 않았으므로 함수 수 = 수집 수). 기존 테스트가 하나도 사라지지 않았고
하나도 추가로 skip 되지 않았다.

🔴 **skipped 가 4 로 그대로인 이유.** 신규 파일의 commit 게이트 skip
3개는 §9.2 단독 실행 시점에는 commit 이 없어 skip 되었다. 이번 전체
회귀는 commit 2개가 생긴 뒤에 돌았으므로 그 3개가 **실행되어 통과했다**.
남은 skipped 4 는 기준에 이미 있던 것이다 — 숫자가 같을 뿐 같은 테스트가
아니다.

| 항목 | 값 |
|---|---|
| 기준 commit | `cdeaf7a` |
| 측정 commit | `a312415` (테스트 `4e045c7` + 보고서) |
| 실행 시각 worktree | clean |
| 기존 테스트 삭제·수정·skip 추가·assertion 약화 | **0건** |

소요 시간이 직전 회귀(49:45)보다 긴 것은 §9.3 의 tripwire 실행이 초반에
겹쳤기 때문이다. 통과·실패 수에는 영향이 없다.

이 수치는 이번 실행에서 실제로 측정한 값이다. 이전 Phase 의 수치를
재사용하지 않았다.

---

## 10. 다음 단계 후보 (최대 1개)

**갱신 요약(`summarise`)의 한국어 계층 공백(N54) 수정 여부 결정.**

§8.1 의 최소 수정안을 적용할지 판단한다. 조사는 끝났고(공백은 실측으로
재현됨, 사용자 피해는 없음, 공개 API 로 충분함) 남은 것은 **출력 정책
결정**이다. 결정한다면 정본 기준 두 수(13,728 / 399)를 한 행으로 추가하고,
반환값을 받는 방향으로는 고치지 않는다.

🔴 다음 Phase 는 자동으로 시작하지 않는다.
