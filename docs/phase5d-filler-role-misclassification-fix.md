# Phase 5-D — 보강 카드 오분류 수정

- 기준 커밋: `a89ab91` (Phase 5-C `/deck`)
- 작업 브랜치: `claude/pensive-goodall-te1egy`
- 범위: **보강 카드 분류와 선정 로직.** `/combo` · 듀얼 엔진 · 카드 데이터
  파이프라인은 수정하지 않았다.

---

## 1. 오분류의 실제 원인과 코드 위치

### 증상

`/deck request:"오르페골 덱 짜줘"` 가 8종을 모두 같은 근거
`패에서 발동 (패트랩 계열)` 로 메인 덱에 넣었다.

### 원인은 **하나의 신호가 세 가지 일을 겸한 것**이다

```
core/card_model.py:469   Card.has_effect_from(location)
                         → "SetRange() 에 LOCATION_HAND 이 있는가" 만 본다
                            (core/card_model.py:186  EffectSpec.usable_from)
        │
        ├─ deck/builder.py:229 (수정 전)  _classify
        │     if card.is_monster and card.has_effect_from("HAND"):
        │         return CardRole.HAND_TRAP, "…패에서 발동 가능한 효과가 확인됩니다"
        │
        └─ deck/builder.py:155 (수정 전)  _fill
              if not card.has_effect_from("HAND"): continue
              → 카드 ID 순서로 집어넣고 role=CardRole.HAND_TRAP 하드코딩
```

세 가지가 겹쳐 있었다.

| # | 겹친 것 | 왜 틀렸는가 |
|---|---|---|
| 1 | **발동 위치 ↔ 발동 가능성** | `SetRange(LOCATION_HAND)` 은 `EFFECT_SPSUMMON_PROC`(특수 소환 **절차**)와 지속 효과에도 붙는다. 절차는 발동이 아니다 |
| 2 | **효과 사실 ↔ 카드 역할** | "패에서 발동 가능" 이라는 위치 사실에 "패트랩" 이라는 **역할 이름**을 붙였다 |
| 3 | **장수 부족 ↔ 카드 선정** | 부족하다는 사실은 '몇 장' 만 알려 준다. '어떤 카드' 인지는 알려 주지 않는데, 그 자리를 **카드 ID 순서**가 대신했다 |

### 8장의 실제 효과 데이터 (측정값)

🔴 **이름으로 확인한 것이 아니다.** 전부 Lua 효과 블록에서 읽었다.

| 카드 | `LOCATION_HAND` 블록 | 실제 |
|---|---|---|
| 텐사우전드 드래곤 `10000` | `FIELD` / `EFFECT_SPSUMMON_PROC` | **특수 소환 절차 — 발동 아님** |
| SPYRAL－보텍스 `35699` | `FIELD` / `EFFECT_SPSUMMON_PROC` | **특수 소환 절차 — 발동 아님** |
| 펜리르 `218704` | `FIELD` / `EFFECT_SPSUMMON_PROC` | **특수 소환 절차 — 발동 아님** |
| 독법사 `263926` | `FIELD` / `EFFECT_SPSUMMON_PROC` | **특수 소환 절차 — 발동 아님** |
| 라뷰린스 쿠클락 `2511` | `QUICK_O` / 범주 **없음** | 발동 가능, 무엇을 하는지 모름 |
| EM 스카이 퓨필 `122520` | `QUICK_O` / `SPECIAL_SUMMON` | 발동 가능, 특수 소환 |
| 하나된 마음의 용 `291414` | `TRIGGER_O` / `EVENT_DRAW` / `SPECIAL_SUMMON` | 발동 가능, 드로우에 반응 |
| 육화의 하얀 공주 `132308` | `QUICK_O` / `EVENT_CHAINING` / **`DISABLE`** | **무효화 근거 있음** |

**네 장은 효과를 발동하는 카드가 아니었다.** 세 장은 발동은 하지만 무엇을
하는지 이 저장소가 판정하지 못한다. 실제로 무효화 근거가 있는 것은 **한
장**이다.

### 모집단 측정 (메인 덱 몬스터 7,067장)

| 기준 | 장수 |
|---|---|
| `has_effect_from("HAND")` — 수정 전 기준 | **1,795** |
| `+` 발동 가능한 효과 종류 (절차·지속 제외) | 1,208 |
| `+` 무효/무력화 범주까지 | **37** |

🔴 **1,795 대 37 — 48배.** 그중 587장은 "패에서 발동" 조차 아니었다.

---

## 2. 수정한 파일과 변경 이유

| 파일 | 변경 | 이유 |
|---|---|---|
| **`deck/evidence.py`** | 신규 | 효과 **사실만** 읽는 자리. 역할을 붙이지 않는다 |
| `deck/model.py` | `CardRole.HAND_ACTIVATABLE` 추가 · `HAND_TRAP` 의 기준과 한국어 표기 교정 · `RoleEvidence` 추가 · `DeckSlot.evidence` 추가 | 역할과 **역할의 근거**를 다른 칸으로 분리 |
| `deck/builder.py` | `_classify` 가 근거 등급에 따라 다른 역할을 돌려준다 · `_fill` 이 목표 + 측정 근거가 둘 다 있을 때만 보강 · `_fill_with_negation_evidence` 분리 · `_priority` 에 새 역할 추가 | 오분류의 두 지점이 여기였다 |
| `deck/report.py` | 역할 줄에 **출처**를 함께 표시 | 근거 없이 붙은 역할이 측정된 역할처럼 보이지 않게 |
| `app/discord_bot.py` | `_deck_role_evidence_lines` 추가 (`[역할의 출처]` 절) | 같은 이유. Discord 응답에도 출처가 보인다 |
| `tests/test_deck_builder_planner.py` | 회귀 테스트 11개 추가 | §C |
| `tests/test_discord_bot.py` | `test_43` 갱신 | 아래 §4 |

**수정하지 않은 것** (범위 제한): `deck/planner.py` · `deck/hand.py` ·
`deck/request.py` · `deck/validator.py` · `app/main.py` · `core/` ·
`engine/` · `agent/` · `analysis/` — `git diff` 가 비어 있다.

🔴 **`core/card_model.py` 를 고치지 않았다.** `has_effect_from` 은 공개
API 이고 `core/card_search.py` · 검색 테스트가 쓴다. 그 의미("`SetRange` 에
그 위치가 있는가") 자체는 틀리지 않았다 — 틀린 것은 그것을 역할 판정에
단독으로 쓴 쪽이다. 그래서 **가르는 일을 `deck/evidence.py` 에서** 한다.

### A. 분리한 개념 (요구사항 A)

| 질문 | 어디서 답하는가 | 값 |
|---|---|---|
| 패에서 효과를 발동할 수 있는가? | `HandEffectFacts.activatable_from_hand` | 측정 |
| 무효·무력화를 하는가? | `HandEffectFacts.negation_blocks` | 측정 |
| 어떤 발동에 체인하는가? | `chains_on_activation()` | 측정 |
| 패트랩 역할이 효과로 뒷받침되는가? | `HandTrapEvidence` 3단계 | 판정 |
| 역할이 어디서 나왔는가? | `RoleEvidence` 5단계 | 판정의 출처 |
| **이 덱에 채용할 근거가 있는가?** | **함수가 없다** | 🔴 **판정 불가** |

🔴 마지막 줄이 중요하다. 이 저장소에는 덱 적합성을 판정할 데이터가 없다.
**없는 판정에는 함수를 두지 않았다** — 두면 누군가 그것을 근거로 쓴다.

🔴 그리고 **"상대의 행동을 방해한다" 는 말을 쓰지 않는다.**
`EVENT_CHAINING` 은 "발동에 체인한다" 는 사실이고 **누구의** 발동인지는
Lua 블록에 없다. 그래서 함수 이름이 `chains_on_activation` 이고
("상대" 가 없다), 보강 근거 문장에도 "상대" 가 없다 (`test_41` 이 고정).

### B. 보강 선정 기준 (요구사항 B)

```
목표에 '패트랩 비중' 이 있는가?
  ├─ 없다 → 🔴 보강하지 않는다.
  │         부족한 장수와 "고를 근거가 없다" 를 notes 에 적고,
  │         DeckValidator 가 장수 위반을 그대로 보고한다.
  └─ 있다 → 후보 = HandTrapEvidence.NEGATION_FROM_HAND 인 카드뿐 (37장)
            역할 = HAND_TRAP, 출처 = LUA_EFFECT_CATEGORY
            근거 문장 = 측정값 + "🔴 이 덱에 맞는지는 판정하지 않았습니다"
            후보 사이 순서 = 카드 ID (notes 에 **임의**라고 적는다)
            근거 있는 후보가 떨어지면 → 멈추고 그 사실을 적는다
```

### 실제 동작 변화

| 요청 | 수정 전 | 수정 후 |
|---|---|---|
| `오르페골 덱 짜줘` | 메인 **40장** (테마 24 + 근거 없는 보강 16), 위반 0건 | 메인 **24장**, **위반 1건**, "보강하지 않았습니다" 기록 |
| `오르페골 덱, 패트랩 비중 우선` | 40장, 보강 8종 전부 "패트랩 계열" | 40장, 보강 **6종 전부 무효/무력화 범주 확인** |

🔴 **첫 줄이 눈에 보이는 변화다.** 목표를 주지 않은 요청은 이제 규격을
만족하지 않는 덱을 돌려주고 **그 이유를 적는다.** 40장이던 것은 근거 없는
16장이 채운 결과였고, 그 16장이 이번에 고친 결함 자체다. 숨기지 않고
위반으로 보고하는 쪽을 골랐다.

보강 결과를 독립적으로 뒷받침하는 사실: 좁힌 기준이 고른 6종은
**하루 우라라 · PSY프레임기어 ε · 고성대 사우라비스 · 구풍룡－뷰포트 노웸 ·
육화의 하얀 공주 · 홀리 엘프－홀리 버스트 스트림** 이다. 🔴 **이름을 보지
않고** `CATEGORY_NEGATE`/`DISABLE` 만으로 고른 결과이고, 수정 전 8종 중
7종은 사라졌다.

---

## 3. 새로 추가한 회귀 테스트 (요구사항 C)

`tests/test_deck_builder_planner.py` **§F** 11개.

| 테스트 | 고정하는 것 | §C |
|---|---|---|
| `test_33` | `LOCATION_HAND` ≠ 발동 가능. 두 모집단의 차이가 400장 이상 | C-1 |
| `test_34` | 보고된 8장이 **세 등급으로 갈린다** (`len(set(...)) == 3`) + 각 등급의 정확한 집합 | **C-2** |
| `test_35` | 역할이 근거 등급을 따라간다. 세 경로(자체 특소 / 발동만 / 무효 근거)를 모두 밟았는지 확인 | C-1 · C-3 |
| `test_36` | 장수 부족만으로는 아무 카드도 고르지 않는다 + 장수 위반이 보고된다 | B-1 |
| `test_37` | 보강 카드마다 `negation_blocks >= 1` 이 **실제로** 있다 + 8장 중 근거 없는 7장은 들어오지 않는다 | B |
| `test_38` | 보강 근거에 테마 이름이 없고 추천·시너지 주장이 없다 | **C-4** |
| `test_39` | `deck/evidence.py` 에 **카드 ID 리터럴도 카드 이름 접근도 없다** | 원칙 4 |
| `test_40` | 좁힌 모집단 크기(37)가 옛 것(1,795)의 1/10 미만 | B |
| `test_41` | 코드와 근거 문장에 "상대" 가 없다 + 체인 사실 자체는 읽는다 | A |
| `test_42` | 역할과 근거가 **다른 칸**이고 기본값이 "근거 없음" | A |
| `test_43` | 역할 이름에 "패트랩 계열" 이 없다 | B-3 |

🔴 **8장을 하드코딩 제외 목록으로 처리하지 않았다** (원칙 4). 테스트의
`MISCLASSIFIED_SAMPLE` 은 **판정이 갈리는지 보는 표본**이고 프로덕션
코드에는 없다 — `test_39` 가 `deck/evidence.py` 에 카드 ID 리터럴이
하나도 없음을 AST 로 고정한다.

### 돌연변이 검사 — 테스트가 비어 있지 않다

| 돌연변이 | 결과 |
|---|---|
| 발동 종류 필터 제거 (옛 기준으로 되돌림) | **2 failed** (`test_33` · `test_34`) |
| 무효 범주 없이도 `HAND_TRAP` 부여 | **1 failed** (`test_35`) |
| 목표 없이도 보강 | **2 failed** (`test_36` · `test_43`/discord) |
| 후보를 패 범위 전체로 넓힘 | **4 failed** (`test_34` · `35` · `37` · `40`) |
| 역할 이름을 "패트랩 계열" 로 되돌림 | **1 failed** (`test_43`) |
| 보강 근거에 "오르페골 덱에 추천하는 시너지 카드" 추가 | **1 failed** (`test_38`) |
| `DeckSlot.evidence` 기본값을 그럴듯한 값으로 | **1 failed** (`test_42`) |
| (복원 후) | **93 passed** |

---

## 4. 기존 테스트 1개 갱신 (삭제·skip·약화 없음)

| 테스트 | 갱신 | 왜 기존 가정이 틀렸는가 |
|---|---|---|
| `tests/test_discord_bot.py::test_43` | `"**메인 40장**"` → `"**메인 24장**"` + `"보강하지 않았습니다"` + `"메인 덱 장수: 위반"` + `"패트랩 계열" not in` + `"**[역할의 출처]**"` | 그 40장은 테마 24장 + **근거가 신뢰할 수 없는 16장**이었다. 즉 이 단정은 결함을 고정하고 있었다. 단정 1개가 **5개로 늘었다** — 약화가 아니다 |

`tests/test_deck_builder_planner.py` 의 기존 32개는 **하나도 수정하지
않았다.** `test_08`(목표가 매수를 바꾼다)이 `CardRole.HAND_TRAP` 을 세지만
조건부 단정(`if traps_plain and traps_weighted`)이라 그대로 통과한다.

---

## 5. 테스트 결과

```
$ python3 -m pytest tests/test_deck_builder_planner.py tests/test_discord_bot.py \
    -p no:randomly -q
93 passed, 1 warning in 11.24s

$ python3 -m pytest tests/test_deck_builder_planner.py tests/test_discord_bot.py \
    tests/test_duelstep_withheld_validation_audit.py \
    tests/test_simulation_status_unknown_codes_audit.py \
    tests/test_special_summon_event_foundation_audit.py \
    tests/test_trigger_condition_separation_audit.py \
    tests/test_korean_search.py tests/test_search_integration.py \
    tests/test_search_semantics.py tests/test_query_parser.py -p no:randomly -q
274 passed, 1 warning in 36.96s
```

테스트 파일 목록·`pytest.skip` 문구를 고정하는 감사 3개도 돌렸다
(테스트 추가가 그쪽을 깨뜨리는지 확인):

```
$ python3 -m pytest tests/test_auxiliary_effect_creation_clone_audit.py \
    tests/test_provenance_consumer_audit.py \
    tests/test_update_coverage_contract_audit.py -p no:randomly -q
134 passed in 408.87s (0:06:48)
```

**실패한 테스트는 없다.** 경고 1개는 `discord.py` 가 Python 3.11 에서
`audioop` 을 import 하며 내는 `DeprecationWarning` 이다. 변경 범위 밖의
전체 회귀 테스트는 돌리지 않았다.

CLI 도 그대로 동작한다 (`python3 -m app.main deck "오르페골 덱, 패트랩 비중 우선"`).

---

## 6. 여전히 해결되지 않은 한계

🔴 숨기지 않고 적는다.

1. **덱 적합성(시너지)을 판정할 데이터가 없다.** "이 카드가 오르페골 덱에
   맞는가" 에 답할 근거가 이 저장소에 없다. 그래서 보강은 목표에 대응하는
   측정 근거가 있을 때만 하고, 그때도 **적합성을 주장하지 않는다.**
   목표 없는 요청은 40장을 채우지 못한다 — 그것이 현재 능력의 정직한
   표현이다.
2. **"상대를 방해한다" 를 말할 수 없다.** `EVENT_CHAINING` 과 `NEGATE` /
   `DISABLE` 은 대상이 누구인지 적지 않는다. 그래서 `HAND_TRAP` 역할의
   뜻은 "패에서 발동 · 무효/무력화 범주 확인" 까지이고, 그 이상이 아니다.
3. **`ACTIVATABLE_ONLY` 는 그대로 미판정이다** (실측 1,171장 = 1,208 − 37).
   `CATEGORY_*` 가 없거나 무효 범주가 아닌 블록이 무엇을 하는지는 판정하지
   않는다 — `CardRole.HAND_ACTIVATABLE` 이 그 상태를 그대로 유지한다.
4. **`deck/planner.py:243` 은 아직 위치만 본다.**
   ```python
   if card.effects and card.has_effect_from("HAND"):
       action=f"'{name}' 의 패에서 발동하는 효과를 씁니다"
   ```
   `/combo` 경로이고 이번 범위 밖이라 **고치지 않았다.** 같은 과대 진술이
   남아 있다 — 특수 소환 절차만 가진 카드도 "패에서 발동하는 효과를
   씁니다" 로 적힐 수 있다. `/combo` 를 붙이는 단계에서 같은 방식으로
   (`deck.evidence` 를 써서) 고쳐야 한다.
5. **동일명 매수 상한과 금지·제한은 여전히 검증 불가.** Phase 5-C 와 같다.
   보강 매수 3장도 '규칙상 허용' 이 아니라 이 빌더의 값이다.
6. **메타 평가는 없고, 앞으로도 측정 없이 넣지 않는다.** 보강 후보 사이의
   순서는 카드 ID 이고 그것은 임의다 — `notes` 에 그렇게 적힌다.

### 이전 단계에서 열어 둔 채 유지

N62 · N63 (3-F-46) · S5 (4-B) · Phase 4-C 의 파괴 실행 미구현과
`DuelRunner._step` 분류 결함 · Phase 5-C 의 Discord 실측 미확인 항목.

---

## 7. 다음 단계 후보 (최대 1개)

**`deck/planner.py:243` 의 같은 과대 진술을 `/combo` 단계에서 고친다** (위 4번).
이번 범위가 보강 분류였으므로 손대지 않았다.

🔴 다음 Phase 는 임의로 진행하지 않는다.
