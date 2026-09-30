# Phase 2-AO — Playable Duel Core / Engine V1 Freeze

기준 커밋: `f2325de` (Phase 2-AN) · 2944 passed / 4 skipped
→ 이번 단계: **2961 passed / 4 skipped**

한 줄 결론: **듀얼 한 판이 `PlayerAction` 만으로 처음부터 끝까지 간다.**
16턴 · 100걸음 · 덱아웃으로 종료. 규칙을 새로 만들지 않고 이미 있는 계층을
이어 붙였다.

> 명세가 §1 중간에서 잘려 들어왔다 (§0 의미 · §1 성공 조건의 흐름도까지
> 받았다). 그 흐름도를 그대로 목표로 삼았다.

---

## 1. 없던 것은 규칙이 아니라 **자리**였다

계층은 전부 있었다. 없던 것은 그것들을 **이어 붙이고 흐름의 위치를 들고
있는 자리**다.

```
GameState        판의 모양        ← state_hash() 가 보는 것
PriorityState    흐름의 위치      ← 판 밖에 산다 (Phase 1 의 결정)
Chain            흐름의 위치
EventJournal     흐름의 위치
```

흐름의 위치가 판 밖에 있는 것은 **일부러 그렇게 한 것**이다 (같은 판은
경로와 무관하게 같은 해시여야 한다). 그런데 그것들을 **함께 들고 있는
객체가 없었다.** 시험마다 각자 `PriorityState` 와 `Chain` 을 만들어 썼고,
그래서 듀얼 한 판을 끝까지 굴린 적이 없다.

`engine/duel.py` 가 그 자리다.

```python
Duel.start(repo, decks=…, seed=…)   # 섞고 5장씩
duel.advance()                      # 고르지 않아도 일어나는 일 (드로우)
duel.legal_actions(seat)            # 허가가 난 행위들
duel.apply(action)                  # 적용
duel.result                         # 승패
```

---

## 2. 실제로 끝까지 간다

```
T1 P0 DRAW — 시작
P0 패 5 · 덱 7 / P1 패 5 · 덱 7        (12장 덱)
…
T16 P1 DRAW — 끝: P1: 덱에서 뽑을 수 없다
승자 P0 · 걸음 114
고른 행위: end_phase 90 · normal_summon 10
방문한 페이즈: DRAW · STANDBY · MAIN1 · BATTLE · MAIN2 · END (매 턴)
```

판을 직접 건드린 곳이 **하나도 없다.** `legal_actions()` 로 고르고
`apply()` 로 적용했다.

---

## 3. 규칙은 전부 룰북에서 왔다

| 규칙 | 룰북 원문 |
|---|---|
| 시작 패 5장 | "Finally, draw 5 cards from the top of your Deck; this is your starting hand." |
| 선공 첫 턴 드로우 없음 | "The player who goes first **cannot draw** during the Draw Phase of their first turn." |
| 덱아웃 패배 | "A player with no cards left in their Deck and **unable to draw** loses the Duel." |
| 라이프 0 패배 | "you reduce your opponent's LP to 0" |

네 문장이 저장소의 공식 룰북에 **그대로 있다**는 것을 시험이 확인한다.

**셋째 승리 조건("카드 효과가 이긴다고 적은 경우")은 옮기지 않았다** —
그렇게 적힌 카드가 등재되어 있지 않고, 없는 것을 미리 만들지 않는다.

덱이 0장인 것만으로는 지지 않는다. **뽑아야 할 때 뽑을 수 없어야** 진다 —
룰북이 "unable to draw" 라고 적는 그대로다.

---

## 4. 허가가 나지 않은 것은 내놓지 않는다

`legal_actions()` 는 **`VALID` 가 나온 것만** 담는다. `UNKNOWN` 은 허가가
아니므로 후보가 아니다 — 이 프로젝트의 다른 모든 자리와 같다.

그래서 지금 고를 수 있는 것은 **일반 소환**과 **페이즈 넘기기**뿐이다.

**감추지 않는다.** 못 넣은 것은 이유와 함께 `withheld` 에 남는다.

```
ACTIVATE_CARD  →  missing="activation-timing (Phase 2-C/2-F)"    (100회 관측)
```

빈 목록은 "할 것이 없다" 로 읽히고, 적어 둔 것은 "아직" 으로 읽힌다.

### 드로우는 행위가 아니다

**뽑지 않겠다고 고를 수 없다.** 그래서 행위 목록에 없고 `advance()` 가
한다. 고르는 일과 규칙이 하는 일을 한 목록에 섞으면, 고르는 쪽이 규칙을
거부할 수 있게 된다.

---

## 5. 듀얼 루프는 규칙을 새로 만들지 않는다

시험이 AST 로 고정한다.

- 판을 바꾸는 호출은 **셋뿐**이다 — 시작 드로우 · 페이즈 드로우 ·
  승패 기록. 카드를 옮기거나 라이프를 건드리는 코드가 없다.
- `engine.effect` · `engine.condition` 을 **import 하지 않는다.**

하는 일은 부르는 것뿐이다.

```
ActionValidator   이 행위를 해도 되는가
ActionExecutor    (소환) 적용한다
TurnProgressor    페이즈를 옮긴다
PriorityState     우선권
GameState         판
```

관측 경계도 그대로다 — 각 자리는 자기 패만 보고, 상대 패는 **장수만**
보인다.

---

## 6. Engine V1 이 **하지 못하는 것** (알려진 한계)

숨기지 않는다. 이것이 V1 의 정직한 경계다.

| 못 하는 것 | 왜 | 수 |
|---|---|---|
| **마법 · 함정 발동** | `activation-timing` 계층이 없어 검증기가 `UNKNOWN` | 등재 13장이 전부 여기 걸린다 |
| **우선권 창** | `PriorityState` 는 있지만 "언제 누구에게 여는가" 규칙이 없다 | `PASS` 가 후보가 된 적 없음 |
| **전투** | 계층 자체가 없다 | — |
| **트리거 발동** | 후보는 모으지만 체인에 올리는 규칙이 없다 | — |
| **아키타입 조건** | STRUCTURAL-77 | 단독 병목 **148장** (2-AN) |
| **파괴 · 특수 소환 판정** | ADR-006, 판정기 미등록 | 등재 16장 중 3장이 거절됨 |

**실행되는 실제 카드 13장**은 그대로 있고, 듀얼 루프 밖에서는 여전히
발동·해결된다 (`test_real_card_execution.py`). 루프 안으로 들어오지
못하는 이유는 **카드가 아니라 타이밍 계층**이다.

---

## 7. 코드 변경

| 파일 | 변경 |
|---|---|
| `engine/duel.py` | **신규** — `Duel` · `LegalActions` · `WithheldAction` · `DuelStep` · `TurnStep` |

**기존 파일을 하나도 고치지 않았다.** 새 규칙도, 새 조건도, 새 조작도
만들지 않았다. 기존 테스트 수정 **0건**.

---

## 8. 테스트

- New tests: **17** (`tests/engine/test_duel_loop.py`)
- Passed **2961** / Failed 0 / Skipped 4 / Regression **0**

| 무엇을 | 시험 |
|---|---|
| 룰북 네 문장이 진짜 있다 | `test_a_the_rules_this_loop_follows_are_in_the_rulebook` |
| 5장씩 시작 · 선공은 안 뽑는다 | `test_a_*` |
| **끝까지 간다** | `test_b_a_duel_runs_from_start_to_finish` |
| 진 쪽이 덱이 없다 | `test_b_the_loser_is_the_one_who_ran_out` |
| 여섯 페이즈를 다 돈다 | `test_b_every_phase_is_visited` |
| 같은 씨앗 → 같은 판 / 다른 씨앗 → 다른 판 | `test_b_*` |
| 목록 밖 행위는 거절 | `test_c_an_action_outside_the_list_is_refused` |
| **마법은 이유와 함께 보류** | `test_c_spells_are_withheld_with_the_reason` |
| 드로우는 고르는 일이 아니다 | `test_c_drawing_is_a_rule_not_a_choice` |
| 끝난 뒤엔 아무것도 안 받는다 | `test_c_nothing_is_accepted_after_the_duel_ends` |
| 라이프 0 · "뽑을 수 없을 때" 덱아웃 | `test_d_*` |
| **루프가 규칙을 안 만든다** (AST) | `test_e_the_duel_makes_no_rules_of_its_own` |
| 관측 경계 유지 | `test_e_each_seat_only_sees_its_own_hand` |
| **우선권이 안 열린다는 사실을 고정** | `test_e_priority_never_opens_yet_and_that_is_recorded` |

---

## 9. TODO

- **STRUCTURAL-103 (신규 · 🟠)** — **우선권 창을 여는 규칙이 없다.**
  `PriorityState` 는 값과 전이를 다 갖고 있지만 "페이즈가 바뀌면 누구에게
  언제 열리는가" 를 정한 곳이 없다. 그래서 `PASS` 가 한 번도 후보가 되지
  않고, 그것이 **마법 발동을 막는 것과 같은 뿌리**다 —
  `activation-timing (Phase 2-C/2-F)`. V2 의 첫 목표로 적어 둔다.
- **STRUCTURAL-77 (아키타입 조건) — 🟠 그대로.** 2-AN 이 잰 단독 병목
  148장. 루프 밖 coverage 의 1위다.
- **ADR-006 — 그대로 부분 해결.**
- **102 · 101 · 97 · 95 · 93 · 90 · 87 · 86 · 83 · 76 · 75 · 74 · 61 —
  그대로 둔다.**
- 78 — 건드리지 않았다.

---

## 10. 판정

| 등급 | 건수 | 내용 |
|---|---:|---|
| 🔴 BLOCKER | **0** | |
| 🟠 STRUCTURAL | 1 신규 | 103 (우선권 창을 여는 규칙) |
| 🟡 DETAIL | 0 신규 | |
| 🟢 COSMETIC | 0 신규 | |

---

## 11. ENGINE V1 FREEZE

§0 의 조건("제한된 실제 카드 풀로 하나의 Duel 을 시작부터 종료까지")을
충족했다. **Engine V1 을 여기서 얼린다.**

### V1 이 들고 있는 것

Turn / Phase · Priority(값) · Chain · Trigger(후보 수집) · Activation ·
Normal Summon · Special Summon · Operation Execution · Target / Choice ·
Random Selection · Result / ResultRef · Deferred Result · Conditional Flow ·
Partial Outcome · Operation Ruling · Applicability / Scope ·
Observation Boundary · Deterministic RNG · Event / Timing ·
Operation Result Semantics · **Duel Loop**

### V1 의 수

```
테스트            2961 passed · 4 skipped · regression 0
BLOCKER           0
등재 실제 카드     16장 (실행 가능 13장)
구조적으로 열린 카드  368장 (ACTIVATE 단독 1,385장 중)
듀얼               처음부터 끝까지 진행됨
```

### V1 이 **지키기로 한 것들**

이 목록이 V1 의 성격이다. V2 가 무엇을 하든 이것들은 유지한다.

1. **`UNKNOWN` 은 허가가 아니다.** 모르는 것을 후보에 넣지 않는다.
2. **빈 칸을 남기지 않는다.** 못 한 것은 이유와 함께 적는다.
3. **카드가 적어 둔 것만 옮긴다.** 관문 · `Shortfall` · `Partial` ·
   `ATTEMPTED/AFFECTED` 가 전부 카드 선언이다.
4. **룰북이 답한 것은 룰북을 따른다.** 셔플 · 토큰 · 통상 몬스터 · 승패.
5. **공식 자료가 아니면 근거가 아니다.** 공식 재정으로 STRUCTURAL-96 을
   닫았다.
6. **판의 모양과 흐름의 위치를 섞지 않는다.**
7. **등록하지 않은 것은 실행되지 않는다** (ADR-006).
8. **측정한 뒤에 만든다.** 2-AN 에서 측정이 두 번 스스로 틀렸다.

**다음은 AI 다. V1 은 여기서 멈춘다.**
