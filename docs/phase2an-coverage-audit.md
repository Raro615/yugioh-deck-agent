# Phase 2-AN — Real Card Execution Coverage Audit & Expansion

기준 커밋: `73217a2` (Phase 2-AM) · 2929 passed / 4 skipped
→ 이번 단계: **2944 passed / 4 skipped**

한 줄 결론: **측정이 두 번 스스로 틀렸고, 그것을 고친 것이 이 단계의 가장
큰 성과다.** 계층을 하나도 만들지 않고 "막는 것이 없는 카드" 가 216 →
368 로 늘었다. 그리고 반복되는 병목이 **하나**라는 것이 수로 확정됐다.

> 명세가 §1 중간에서 잘려 들어왔다 (§0 목적 · §1 핵심 원칙 일곱 개와
> 판단 흐름까지 받았다). 받은 범위를 그대로 따랐다.

---

## 1. 무엇을 재는가 — 모집단부터 정한다

"12,702장을 다 실행한다" 가 목표가 아니다. 엔진이 **지금 담는 모양**을
먼저 정해야 한다.

```
효과 타입 조합 (상위 5)
  1385  ACTIVATE                        ← 엔진이 담는 모양
   752  SINGLE + TRIGGER_O
   715  FIELD + SINGLE + TRIGGER_O
   489  IGNITION
   464  IGNITION + SINGLE
```

`EFFECT_TYPE_ACTIVATE` **하나뿐**인 카드가 1,385장이고, 등재된 16장이
**전부** 그 모양이다. 우연이 아니라 그것만 담을 수 있다 — 유발 · 지속 ·
기동 효과 계층이 없다. 그래서 측정 모집단은 1,385장이다.

---

## 2. 🔴 측정이 틀렸다 (1) — `ConfirmCards`

`Duel.ConfirmCards` 는 244장이 쓰고, **그것 하나만** 막는 것처럼 보이는
카드가 48장이었다. 계층 하나를 만들 근거로 충분해 보였다.

**세어 보기 전에 만들지 않았다.** 그 48장의 공식 텍스트를 읽었다.

```
O  5556668  익스체인지     "①: 양쪽 플레이어는 패를 **공개**하고 …"
X 32807846  증원          "①: 덱에서 레벨 4 이하의 전사족 몬스터 1장을 패에 넣는다."
X 73628505  테라포밍       "①: 덱에서 필드 마법 카드 1장을 패에 넣는다."
X 47325505  화석조사       "①: 덱에서 레벨 6 이하의 공룡족 몬스터 1장을 패에 넣는다."
…
공식 텍스트에 '공개' 가 있는 카드: 1 / 48
```

룰북이 못박는다.

> **Reveal** — "When an effect **says** to reveal a card, you show it to
> both players."

공개는 **카드가 적을 때만** 일어난다. 덱을 뒤지는 규칙은 공개를 말하지
않는다 — 그 규칙이 말하는 것은 **셔플**이다 (§4).

그러므로 스크립트의 `ConfirmCards` 는 EDOPro 가 검색 결과를 보여 주는
**구현**이고 카드의 규칙이 아니다. `NOT_A_RULE` 로 옮겼다.

→ 막는 것이 없는 카드 **320 → 368**. 계층은 **0개** 추가.

남은 한 장(익스체인지)은 §1-5 그대로 둔다 — 한 장 때문에 계층을 만들지
않는다.

---

## 3. 🔴 측정이 틀렸다 (2) — 실행되는 카드가 분류를 보정한다

처음 순위는 이랬다.

```
108  Card.IsSetCard
 24  Duel.GetChainInfo     ← ???
 17  Duel.SetTargetCard
 16  Duel.BreakEffect      ← ???
```

**욕망의 항아리 · 다이안 켓 · 리로드가 `GetChainInfo` 와 `BreakEffect` 를
쓰면서 멀쩡히 실행된다.** 그런데 분류는 그것들을 "막는다" 로 세고 있었다.

여기서 방법이 하나 나온다.

> **실행되는 카드가 쓰는 API 는 막는 것일 수 없다.** 증명되어 있다.

등재·실행되는 13장이 쓰는 `Duel.*` 22개를 뽑아 분류와 맞춰 보니 다섯이
어긋났다.

| API | 왜 막지 않는가 |
|---|---|
| `GetChainInfo` | "누가 대상 플레이어인가" → `PlayerRef` 가 그것이다 |
| `SetTargetPlayer` · `SetTargetParam` | 같은 것을 체인에 심는 EDOPro 의 배선 |
| `BreakEffect` | 체인 처리의 마디 — 효과 하나에는 규칙 내용이 없다 |
| `IsPlayerCanDraw` | 덱 장수는 `ZoneCountAtLeast`, 나머지는 미확인으로 기록 |

→ 막는 것이 없는 카드 **250 → 368**. 계층은 **0개** 추가.

이 보정은 시험이 **라이브러리에서 직접 끌어낸다**. 나중에 카드가 더
등재되면 분류가 좁아졌다는 것을 바로 알려 준다.

---

## 4. 보정된 결과 — 병목은 **하나**다

```
그 하나만 풀면 열리는 카드 수
  148  Card.IsSetCard        ← STRUCTURAL-77 (아키타입/setcode 조건)
   22  Duel.SetTargetCard
   19  Duel.ShuffleHand      ← STRUCTURAL-75
   19  Duel.ChangePosition   ← STRUCTURAL-61
   16  Duel.SelectYesNo
   14  Duel.GetMatchingGroupCount
   10  Duel.GetOperatedGroup ← STRUCTURAL-87
```

**1위가 2위의 일곱 배다.** 병목이 여럿이 아니라 하나이고, 그것은 **이미
기록된 STRUCTURAL-77** 이다. 이번 단계가 새로 만들 것이 아니라, 다음
단계의 목표가 수로 확정된 것이다.

### 커버리지를 정직하게 적으면

| | 장수 |
|---|---:|
| 스크립트가 있는 카드 | 12,702 |
| 엔진이 담는 모양 (`ACTIVATE` 단독) | 1,385 |
| **막는 것이 하나도 없는 카드** | **368** |
| 등재된 카드 | 16 |
| 실행되는 카드 | **13** |

368 과 13 의 차이는 **구조가 아니라 손**이다 — 정의를 손으로 적지 않았을
뿐이다 (ADR-006). 368 을 "커버리지" 로 읽지 않는다: **적을 수 있다**는
것과 **적어 두었다**는 것은 다른 말이다.

---

## 5. 고친 것 — STRUCTURAL-71 (들여다본 덱을 섞는다)

§1 의 일곱 기준을 전부 통과한 유일한 항목이다.

| 기준 | 확인 |
|---|---|
| 실제 카드에서 재현 | ✔ 어리석은 매장(81439173) — **등재·실행되는** 카드 |
| 원인 분류 | ✔ 규칙 미이행 (룰북 일반 규칙) |
| 반복되는가 | ✔ ACTIVATE 단독 **269장** · 코퍼스 전체 **3,082장** |
| 공통 semantics 인가 | ✔ 카드가 아니라 **룰북**이 시킨다 |
| 카드 하나 때문인가 | ✘ (아니다) |
| ruling/data 문제인가 | ✘ 룰북이 직접 답한다 |
| 이미 해결됐는가 | ✘ `ShuffleOperation` 은 있는데 **부르는 자리가 없었다** |

### 룰북

> "If a card effect requires you to reveal cards from your Deck, **or look
> through it, shuffle it** and put it back in this space afterwards."
> "You must shuffle your Deck **after any time you search it** and let your
> opponent shuffle or cut."

### 재현 (고치기 전)

```
덱: 20 → 19
남은 카드의 순서가 그대로인가: True
  before: [1, 2, 3, 5, 6, 7, 8, 9, 10, 11]
  after : [1, 2, 3, 5, 6, 7, 8, 9, 10, 11]
```

들여다본 사람이 **덱 순서를 아는 채로 남는다.**

### 왜 정의에 적지 않는가

스크립트도 적지 않는다 — 덱을 들여다보는 ACTIVATE 단독 269장 중
`Duel.ShuffleDeck` 을 직접 부르는 것은 **31장**뿐이고, 나머지 238장은
EDOPro 엔진이 알아서 섞는다. 이 엔진에서 그 "알아서" 에 해당하는 자리가
없던 것이 STRUCTURAL-71 이다. 정의에 적으면 **같은 규칙이 269곳에
복사된다.**

### 어느 자리를 들여다보았는지는 이미 적혀 있다

새로 추론하지 않는다. `TargetSpec.looked_at_zones()` (2-Y) 가 그것이다.
**아무도 들여다보지 않은 선택은 여기 오지 않는다** — 무작위 선택(2-AA)과
"전부"(2-AI)는 빈 집합이고, 룰북이 말하는 "search" 도 아니다.

### 처음에 틀린 것 — 누구의 덱인가

`source.owner` 로 적었다가 **상대 덱까지 섞었다.** 아무도 열어 보지 못한
덱이다.

`looked_at_zones()` 가 이미 규칙을 들고 있었다: 주인이 상대면 **빈
집합**이고("남의 자리에서 고르라는 규칙이 남의 자리를 볼 권리까지 주지는
않는다"), 주인을 가리지 않으면 열리는 것은 보는 사람 자신의 자리뿐이다.
그러므로 섞는 것은 언제나 **`chooser` 의 덱**이다.

### 난수원이 없을 때

카드가 적은 셔플이라면 효과를 거절하는 것이 맞다 (2-Z). 그러나 이것은
**룰북이 시키는 정리**이고, 정리를 못 했다고 카드의 일까지 무르면 씨앗
없는 판에서 **셔플과 무관한 효과가 죽는다**.

그래서 **조용히 넘기지 않고 적어서** 내보낸다 — 2-AL · 2-AM 이 만든
`_Step.blind` → `EffectResult.unchecked_rules` 를 그대로 쓴다. 자리를 새로
만들지 않았다.

---

## 6. 코드 변경

| 파일 | 변경 |
|---|---|
| `engine/effect/executor.py` | `_shuffle_searched_decks()` 추가 (+`_plan` 끝에서 호출) |

**한 파일, 한 함수다.** 새 Operation · 새 Delta · 새 계층 없음 —
`ShuffleOperation` · `_plan_shuffle` · `_apply_shuffle` · `looked_at_zones()`
를 그대로 조립했다.

기존 테스트 수정 **2건** (삭제 0건):

- `test_semantic_effects.py::new_state` — **씨앗을 준다.** 이 파일의
  synthetic 명세가 후보 자리에 `Zone.DECK` 을 넣어 두었으므로 이제 정리
  셔플이 일어난다. 이 파일이 보는 것은 의미 계층이고 덱 순서가 아니므로,
  씨앗을 주면 단언이 **전과 똑같은 강도로** 유지된다.
- `test_semantic_effects.py::test_the_event_pipeline_keeps_the_three_apart`
  — 사건이 하나에서 둘이 되었다. **잘못된 가정은 "이 효과의 사건은
  하나"** 였다. 이 시험이 보는 것은 의미가 통로를 지나 살아 남는가이므로,
  세는 것을 카드 이동으로 좁혔다 (나머지가 셔플뿐임을 함께 단언한다).

---

## 7. 테스트

- New tests: **15** (`tests/engine/test_real_card_coverage.py`)
- Passed **2944** / Failed 0 / Skipped 4 / Regression **0**

| 무엇을 | 시험 |
|---|---|
| 모집단 (1,385 · 등재 16장이 전부 그 모양) | `test_a_the_engine_targets_activate_only_cards` |
| **분류 보정** (실행되는 카드가 기준) | `test_a_the_executing_cards_calibrate_the_classifier` |
| 막는 것 없는 카드 368 | `test_a_three_hundred_sixty_eight_cards_…` |
| 병목이 하나임 (148 vs 22) | `test_a_the_repeated_blockers_are_ranked_and_already_filed` |
| **`ConfirmCards` 는 규칙이 아니다** | `test_b_*` 3개 (48장 · 룰북 · 공식 텍스트 1/48) |
| 룰북이 셔플을 시킨다 | `test_c_the_rulebook_makes_the_shuffle_a_general_rule` |
| 269 / 31 측정 | `test_c_most_scripts_do_not_say_it_because_the_engine_does_it` |
| **실제 카드에서 섞인다** | `test_c_a_searched_deck_is_shuffled` |
| 카드가 선언하지 않는다 | `test_c_the_card_does_not_declare_the_shuffle` |
| **고른 사람의 덱만** | `test_c_only_the_chooser_s_deck_is_shuffled` |
| 난수원 없으면 기록 | `test_c_without_randomness_it_is_recorded_not_skipped` |
| 결정론 | `test_c_the_same_seed_shuffles_the_same_way` |
| 엑스트라 덱은 아니다 | `test_c_the_extra_deck_is_not_tidied_up` |

---

## 8. TODO

- **STRUCTURAL-71 — 해결.** 들여다본 덱을 섞는다. 무작위 선택 · "전부"
  에는 적용되지 않는다 (아무도 들여다보지 않는다 — 룰북의 "search" 가
  아니다). 난수원이 없으면 기록하고 넘어간다.
- **STRUCTURAL-77 (아키타입 조건) — 🟠 로 올린다.** 보정된 측정에서
  **단독 병목 148장**, 2위의 7배다. `Card.IsSetCard` 를 쓰는 카드는
  코퍼스 전체 4,601장. **다음 단계의 목표는 이것 하나다.**
- **STRUCTURAL-102 (신규 · 🟡)** — **`Duel.SelectYesNo` 에 해당하는 것이
  없다.** "할 것인가" 를 플레이어에게 묻는 선택이고, 단독 병목 16장 ·
  ACTIVATE 단독 140장이 쓴다. 2-AD 의 `DeclaredNumber` 는 **수**를
  선언하는 것이고 예/아니오가 아니다 (STRUCTURAL-97 과 같은 종류의 빈
  칸이다).
- **STRUCTURAL-75 (패 셔플) · 61 (표시 형식) · 87 (GetOperatedGroup) —
  각각 19 · 19 · 10 장으로 측정됐다.** 그대로 둔다.
- **STRUCTURAL-101 · 97 · 95 · 93 · 90 · 86 · 83 · 76 — 그대로 둔다.**
- 74 · 78 — **건드리지 않았다.**

---

## 9. 판정

| 등급 | 건수 | 내용 |
|---|---:|---|
| 🔴 BLOCKER | **0** | |
| 🟠 STRUCTURAL | 0 신규 (71 해결 · 77 을 🟠 로 승격) | |
| 🟡 DETAIL | 1 신규 | 102 (예/아니오 선택) |
| 🟢 COSMETIC | 0 신규 | |

---

## 10. 이번에 하지 않은 것 (§1)

**새 카드를 한 장도 등재하지 않았다.** 368장이 열려 있지만 그것은 손으로
적는 일이고, 이번 단계의 일은 재는 것이었다.

계층을 하나도 만들지 않았다 — `ConfirmCards` 를 위한 공개 계층도,
`SelectYesNo` 를 위한 선택 계층도, 아키타입 조건도 만들지 않았다. 앞의
둘은 근거가 부족하고(1장 · 16장), 뒤의 하나는 **다음 단계의 목표**로
적어 두는 것이 이 단계의 결론이다.

Duel Engine 재설계 · EffectExecutor 재작성 · 새 Graph Engine · 새 EventBus ·
새 Expression Language · 새 Rule Engine · AI 의사결정 · 카드 이름별
hardcoded rule · 테스트 삭제 · 규칙 추측 — 하나도 하지 않았다.

**다음 Phase 는 시작하지 않았다.**
