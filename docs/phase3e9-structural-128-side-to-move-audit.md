# Phase 3-E-9 — STRUCTURAL-128 Side-to-Move Evaluation Audit

Base: `468ea12` (Phase 3-E-8 · STRUCTURAL-130 RESOLVED)
범위: STRUCTURAL-128 하나. **AUDIT ONLY.**
변경: `engine/` **0건** · `agent/evaluation.py` **0건** · `agent/search.py` **0건** ·
`agent/policy.py` **0건**. 새 테스트 1파일과 이 문서뿐이다.

---

## 0. 결론 — **CASE B, 단서를 붙여서**

주장 두 개를 분리해 답한다 (§8).

| 주장 | 답 |
|---|---|
| **A** — 평가가 `turn_player` 를 알아야 한다 | **지금은 아니다.** 현재 평가의 정의("관측된 상태 자체의 값, `viewer` 관점")에 차례는 들어가지 않는다 |
| **B** — 점수에 차례 기반 가감점을 넣어야 한다 | **아니다.** 근거가 없고, 지금 넣으면 잘못을 고치는 것이 아니라 새 가중치를 만드는 것이다 |

그리고 "그래서 문제가 없다" 로 끝내지 않는다 (§13 Q4).

> **차례는 평가에서 사라진다. 그런데 지금 그것이 순위를 틀어지게 하지
> 않는 이유는 평가가 옳기 때문이 아니라 행동 공간이 좁기 때문이다.**

차례를 바꾸는 행위는 END 페이즈의 `END_PHASE` 하나이고, 그 자리에서 **후보가
그것뿐**이다 (실측 131/131). 한 결정 안의 모든 후보가 같은 차례를 공유하므로
차례는 **모든 후보에 공통인 상수**이고, 상수는 순위를 바꿀 수 없다.

즉 **지금 증상이 없는 구조적 공백**이다. 공백이 증상이 되는 조건은 정확히
적을 수 있다 (§9-2).

---

## 1. Repository Audit (§3)

| 무엇 | 어디 |
|---|---|
| `turn_player` 의 원본 | `engine/state/turn.py` — `TurnState(turn_number, turn_player, phase, step)` (가변) |
| 정규 표현에 포함 | `engine/state/turn.py:92` `canonical_state() = (turn_number, turn_player, phase.value, step)` → `engine/state/game_state.py:509` 가 이것을 품는다 → `state_hash()` 도 품는다 |
| 관측 노출 | `engine/game_state_view.py` — `GameStateView.turn_player` · `turn_number` · `phase` · `step` · `is_my_turn` |
| 행위자 결정 | `engine/duel.py:260` `to_act` = 우선권 홀더, 없으면 `turn_player` |
| 차례를 넘기는 자리 | `engine/duel.py:561` `_apply_end_phase` → `TurnProgressor().advance(state)` |
| 평가 | `agent/evaluation.py` — `StateEvaluator.evaluate(view)` |
| 순위 | `agent/search.py:108` `SearchCandidate.ordering_key()` |
| 기록 | `agent/search.py` `SearchDecision(seat, state_hash, turn_number, phase, …)` |

**`SearchDecision` 은 차례 문맥을 기록한다.** 즉 탐색 계층은 `turn_number` ·
`phase` 를 **보고용으로 들고 있으면서** 순위에는 쓰지 않는다. 정보가 agent
계층에 도달하지 못하는 것이 아니다 — 평가가 쓰지 않는 것이다.

---

## 2. 현재 Evaluation 관찰 (§4) — **읽지 않는다**

### 2-1. 직접 읽지 않는다

`agent/evaluation.py` 의 AST 전체에서 `turn_player` · `is_my_turn` ·
`turn_number` · `step` 이 **0건**이다.

### 2-2. 간접으로도 읽지 않는다 (§2-D)

"이름이 `turn_player` 가 아니어서 못 찾았다" 가 되지 않도록 차례를 알 수 있는
**모든** 관측 이름을 함께 확인했다. 전부 0건이다.

| 간접 경로 | 평가가 읽는가 |
|---|---|
| `phase` | **아니다** |
| `step` | **아니다** |
| `normal_summons_used` (턴 플레이어만 늘어난다) | **아니다** |
| `attacks_used` / `attacks_by` | **아니다** |
| `priority` | 관측에 아예 없다 |
| legal action 의 소유자 | 평가는 `legal` 을 받지 않는다 |

평가가 실제로 읽는 것: `viewer` · `me` · `opponent` · `life_points` · 9개 존의
크기와 카드 · 카드 정의 · `winner` · `is_over`. **끝이다.**

### 2-3. 그런데 `viewer` 로 **현재** 차례는 사실상 안다

`Duel.to_act` 는 "우선권을 쥔 사람, 없으면 턴 플레이어" 이고, 지금은 응답 창이
열리는 자리가 없으므로(STRUCTURAL-34) 언제나 턴 플레이어다.

실측: 결정 **1053회 중 1053회**에서 `legal.seat == duel.turn_player`.

그리고 탐색은 `simulate(action, viewer=legal.seat)` 로 **행위자의 눈으로**
미래를 본다. 그러므로

- **현재** 상태의 차례 = `viewer` → 평가가 암묵적으로 안다
- **미래** 상태의 차례 → 평가가 **모른다**

평가가 못 보는 것은 정확히 **후자**다. 이 구분이 §2-D 의 답이다.

---

## 3. Evaluation 의 의미 (§3 · §4) — 순수 **State Value**

§4 의 세 가지로 분류하면 현재 점수는 **A(State Value) 하나**다.

| 항 | `me` / `opponent` 의 기준 | 분류 |
|---|---|---|
| `lp` | `view.me` = `players[viewer]` | A |
| `atk` · `monsters` · `spells` · `deck` | 같음 | A |
| `hand` | 내 것만 (`me.hand.size`) | A (비대칭 — STRUCTURAL-129, 범위 밖) |
| `terminal` | `view.winner == view.viewer` | A |

근거는 추측이 아니라 코드와 문서다.

- 모듈 설명: *"관점은 언제나 `view.viewer` 다 (§23). P0 가 평가할 때와 P1 이
  평가할 때 **같은 평가자가** 각자의 관점으로 작동한다"* — 관점만 말하고
  차례는 **한 번도 언급하지 않는다**
- `me` = `players[viewer]`. `turn_player` 가 바뀌어도 `me` 는 **바뀌지
  않는다** (§9 의 질문에 대한 답)
- 기존 `test_01_the_evaluator_receives_only_an_observation` 이 "평가는 행위를
  볼 수 없다 — 같은 관측이면 같은 점수" 를 고정한다 → **C(Action Value) 아님**
- 차례를 읽지 않으므로 **B(Side-to-Move Value) 아님**

**`viewer` 와 `turn_player` 가 다른 개념임을 실험으로 분리했다.**

| 실험 | 결과 |
|---|---|
| 같은 판, **관점**만 바꾼다 (P0 → P1) | 점수가 **뒤집힌다** (`+1000` ↔ `-1000`) |
| 같은 판, **차례**만 바꾼다 (P0 → P1) | 점수가 **한 칸도 안 움직인다** |

둘이 같은 개념이라면 두 결과가 같아야 한다. 다르다 — 그래서 "평가는 `viewer`
를 아니까 차례도 안다" 는 추론은 성립하지 않는다.

---

## 4. 동일 상태 / 차례 변경 실험 (§5 · §6)

### 4-1. 손으로 만든 합법 쌍

`GameState.create(turn_player=…)` 는 엔진의 정상 입구다 — 어느 쪽이 선공인지는
듀얼이 정상적으로 갖는 값이므로 **가짜 상태가 아니다**. 양쪽 필드에 ATK 1900
하나씩, 나머지 전부 동일.

| 비교 대상 | Case A (`turn_player=0`) vs Case B (`turn_player=1`) |
|---|---|
| `state_hash` | **다르다** |
| `canonical_state` | **다르다** (`TurnState.canonical_state` 가 품는다) |
| `view.turn_player` | **다르다** (0 vs 1) |
| `view.is_my_turn` | **다르다** (True vs False) |
| `terminal` | 같다 (`ongoing`) |
| `heuristic` | **같다** (0 vs 0) |
| `terms` | **같다** |
| `partial` | 같다 (False) |
| `excluded` | 같다 (`()`) |
| `ordering_key()` | **같다** `(1, 0)` |

두 관점(`viewer=0`, `viewer=1`) 모두에서 같은 결과다.

### 4-2. 엔진이 **스스로** 만드는 쌍 — 더 강한 증거

END 페이즈의 `END_PHASE` 는 판을 바꾸지 않고 **차례만** 넘긴다. 그리고
`Simulator.simulate` 는 `advance()` 를 돌리지 않으므로(= 다음 턴의 드로우가
아직 일어나지 않는다) 미래의 자원이 **행동 전과 완전히 같다.**

```
행동 전: turn_player=0  phase=END   turn=1      heuristic 600
행동 후: turn_player=1  phase=DRAW  turn=2      heuristic 600   (viewer=0 그대로)
         terms 동일 · ordering_key 동일
```

실측 **131/131** 전부 이렇다. 즉 **평가에게 턴을 넘기는 일은 공짜다** —
"내가 한 수 더 둔다" 와 "상대가 한 수 둔다" 가 같은 값으로 읽힌다 (3-E-5 가
우려한 바로 그 모양이고, 여기서 실제 사례로 확인된다).

### 4-3. `canonical_state` 는 손대지 않았다 (§6)

포함한다. 그 설계 의도도 코드에 적혀 있다 — `chain` · `pending` · `journal` ·
`allocator` · 난수원은 "판의 모양이 아니다" 라며 **일부러 제외**하는데,
`turn.canonical_state()` 는 **포함한다.** 즉 이 설계는 **차례를 판의 모양으로
본다.**

그런데 평가는 `canonical_state` 를 읽지 않고(관측만 받는다),
`SearchCandidate.ordering_key()` 의 마지막 동점 처리도 **행위의**
`canonical_state` 를 쓴다 — 미래 상태의 것이 아니다. 그래서 차례는 동점
처리에도 들어가지 않는다.

---

## 5. Search 영향 (§7 · §12 · §13)

말뭉치: 3-E-7 / 3-E-8 과 같은 결정적 말뭉치 (seed 1–6, 무작위 선택).
**결정 1053회 · 평가 3031회** — 이전 Phase 들과 같은 수다.

### Q1. 차례를 무시해서 잘못된 순위가 날 수 있는가 — **구조적으로는 그렇다**

평가가 미래의 차례를 못 보므로, 차례가 다른 두 미래가 같은 점수를 받을 수
있다. 실제로 그런 묶음이 있다: **(viewer, terminal, terms) 가 같은데
`turn_player` 가 다른 평가 묶음 118개 / 642개.**

### Q2. 그 현상이 실제로 순위를 틀어지게 하는가 — **NO**

| 측정 | 값 |
|---|---|
| 한 결정 안에서 후보들의 미래 `turn_player` 가 **갈린** 경우 | **0 / 1053 (0.00%)** |
| 그 중 차례가 다른데 `ordering_key` 가 같은 짝 | **0** |
| 차례를 넘기는 후보가 있던 결정 | 131 |
| 그때 **후보가 그것뿐**이었던 경우 | **131 / 131** |

118개의 "같은 값, 다른 차례" 묶음은 **서로 다른 결정에 속한 미래들**이다.
형제 후보가 아니므로 순위를 다투지 않는다.

### Q3. 원인 분리 — 관찰되지 않으므로 원인 분리는 해당 없음

다만 **만약** 관찰된다면 어디의 문제일지는 지금 단정할 수 있다.

| 계층 | 차례를 옳게 전달하는가 |
|---|---|
| State transition | **그렇다** — `_apply_end_phase` 가 `TurnProgressor` 로 정상 전이 |
| Action simulation | **그렇다** — 미래의 `turn_player` · `turn_number` · `phase` 가 모두 바뀌어 온다 |
| Observation | **그렇다** — `view.turn_player` · `is_my_turn` 노출 |
| **Perspective / Evaluation 정의** | **여기뿐이다** — 평가가 그 값을 읽지 않는다 |

### Q4. 왜 관찰되지 않는가 — **행동 공간 때문이다** (평가가 옳기 때문이 아니다)

페이즈별 후보 분포 (실측):

| 페이즈 | 후보 |
|---|---|
| DRAW | `END_PHASE` 134 |
| STANDBY | `END_PHASE` 134 |
| MAIN1 | `NORMAL_SUMMON` 646 · `SET_MONSTER` 646 · `SET_SPELL_TRAP` 87 · `ACTIVATE_EFFECT` 79 · `END_PHASE` 280 |
| BATTLE | `ATTACK` 358 · `END_PHASE` 224 |
| MAIN2 | `END_PHASE` 150 · `NORMAL_SUMMON` 62 · `SET_MONSTER` 62 · `SET_SPELL_TRAP` 22 · `ACTIVATE_EFFECT` 16 |
| **END** | **`END_PHASE` 131 — 그것뿐** |

행동 종류별로 차례를 넘기는지:

| 행동 | 차례 넘김 | 횟수 |
|---|---|---|
| `END_PHASE` | 아니다 (MAIN1→BATTLE 등) | 922 |
| **`END_PHASE`** | **그렇다 (END→다음 턴)** | **131** |
| `NORMAL_SUMMON` · `SET_MONSTER` · `SET_SPELL_TRAP` · `ATTACK` · `ACTIVATE_EFFECT` | 아니다 | 1978 |

**차례를 넘기는 유일한 행위에게 형제가 없다.** END 페이즈에 후보가 하나뿐인
이유는 거기서 발동이 후보로 오르지 않기 때문이고, 그것은 이미 기록된
**STRUCTURAL-34**(응답 · 우선권 창이 열리는 자리가 없다)다.

---

## 6. Observation Boundary (§10) — 접근 **NO**

- 평가를 한 줄도 바꾸지 않았으므로 새로 읽은 관측이 **0개**다
- Audit 은 `GameStateView` 밖을 보지 않았다. `state_hash` · `canonical_state`
  비교는 `GameState` 를 쓰지만 **테스트가 판을 만드는 쪽**에서 하는 일이고,
  평가에 넘어가는 것은 관측뿐이다
- **차례는 공개 정보다.** 같은 판을 두 관점에서 보면 `turn_player` ·
  `turn_number` · `phase` 가 **같은 값**으로 나온다 (`is_my_turn` 만 각자
  입장에서 읽은 같은 사실이다). 그래서 **나중에 평가가 차례를 읽기로 해도
  관측 경계를 깨지 않는다** — 이것이 CASE A/B 판단에 필요한 사실이므로
  미리 확인해 두었다

---

## 7. 두 정책 비교 — 관찰만 (§14)

둘 다 "턴을 넘기기보다 행동한다" 를 선호한다. **근거가 서로 다르고, 어느
쪽도 차례가 아니다.** 누가 더 좋은지는 판단하지 않는다.

| 정책 | 차례를 읽는가 | 왜 행동을 선호하는가 |
|---|---|---|
| `RuleBasedPolicy` | **아니다** (`heuristic.py` 에 `turn_player` · `is_my_turn` 0건) | `EndThePhaseAsLastResort` 가 `END_PHASE` 에 평평하게 **0** 을 주고, `SummonBeforeEndingThePhase` 등이 양수를 준다 — **행동의 종류**로 가른다 |
| `SearchPolicy` | **아니다** (`search.py` · `policy.py` 도 0건) | 판이 좋아지는 쪽이 이긴다 — 소환은 자원이 필드로 올라와 점수가 오르고 `END_PHASE` 는 판을 그대로 둔다 |

실측: 차례를 넘기는 `END_PHASE` 가 그 결정의 최고점이었던 경우 131회 —
**전부 후보가 그것뿐이었던 경우**다. 형제가 있는 결정에서 `END_PHASE` 가
이긴 적은 없다.

---

## 8. 결론 — **CASE B** (단서 포함)

### 왜 CASE A 가 아닌가

CASE A 는 "평가가 차례를 반드시 알아야 하는 근거가 있고, 현재 구조에서 **실제
정보 손실이 발생**" 이다. 정보 손실은 **발생한다** (§4). 그러나 "반드시 알아야
하는 근거" 가 서지 않는다.

1. 현재 평가의 정의는 **관측된 상태 자체의 값**이다 (§3). 그 정의 안에서
   차례는 필요하지 않다 — 내 LP · 내 필드 · 내 자원은 누구 차례든 같은 값이다
2. 차례의 값("내가 한 수 더 둘 수 있다")은 **상태의 값이 아니라 수순의
   값**이다. 그것을 Depth-1 한 수의 점수로 환산하려면 **"한 수의 값이 LP
   몇인가"** 를 정해야 하고, 그것은 이 Phase 가 금지한 새 가중치다 (§0 · §8)
3. 그리고 그 환산은 **Depth-2 가 하는 일**이다 — 상대가 무엇을 할 수 있는지
   실제로 내다보면 차례의 값이 **가중치 없이** 나온다. 3-E-6 문서가 "128 · 129
   는 Depth-2 와 함께" 라고 적어 둔 것이 이 이유다

### 왜 "문제 없음" 으로 닫지 않는가

§13 Q4 가 요구한 대로 적는다. 증상이 없는 이유는 **평가가 옳기 때문이 아니라
END 페이즈에 후보가 하나뿐이기 때문**이다. 증상이 생기는 조건을 정확히 적어
둔다.

| 조건 | 그러면 |
|---|---|
| END 페이즈에 발동이 후보로 오른다 (**STRUCTURAL-34** 가 열린다) | `END_PHASE`(턴 넘김) 가 `ACTIVATE_EFFECT`(턴 유지) 와 형제가 된다 → 차례가 상수가 아니게 된다 → 그때 점수가 같으면 **순위가 임의로 정해진다** |
| 상대 턴에 행동할 수 있게 된다 (함정 발동) | `viewer != turn_player` 인 결정이 생긴다 → §2-3 의 "현재 차례 = viewer" 가 깨진다 |
| Depth-2 가 들어온다 | 차례가 **구조적으로 필요해진다** — 다음 수를 누가 두는지 모르면 내다볼 수 없다 |

그러므로 **STRUCTURAL-128 을 RESOLVED 로 닫지 않는다.** 지금은
**"DESIGNED-OUT, 단 조건부"** 가 가장 정확한 상태다: 현재 평가의 정의상
필요하지 않고, 위 세 조건 중 하나라도 성립하면 다시 열린다.

---

## 9. 구현 제안 — **없다** (CASE B 이므로)

§10 은 CASE A 인 경우에만 설계를 제안하라고 한다. CASE B 이므로 **제안하지
않는다.** 임의의 가중치(`+400` 등)는 제안하지 않았다.

대신 다음 Phase 가 쓸 수 있는 **사실**만 남긴다.

- 차례는 공개 정보이고, 관측에 이미 있다 → 읽기로 하면 경계를 깨지 않는다
- 차례를 읽어야 하는 첫 시점은 **Depth-2** 또는 **STRUCTURAL-34 의 개방**이다
- 가중치 없이 차례를 쓰는 길이 있다: Depth-2 가 "상대가 무엇을 할 수 있는지"
  를 실제로 내다보면 차례의 값이 **유도된다**

---

## 10. 테스트

```
3400 passed · 0 failed · 4 skipped
```

기준(`468ea12`) 3392 passed → **+8** (신규 `tests/agent/test_side_to_move_audit.py`)

| 테스트 | §17 항목 | 무엇을 고정하는가 |
|---|---|---|
| `test_01_the_observation_exposes_the_whole_turn_context` | 1 | 차례 문맥이 관측에 있고 **공개 정보**다 |
| `test_02_the_evaluation_reads_no_part_of_the_turn_context` | 2 | 직접도 간접도 읽지 않는다 (8개 이름 전부 0건) |
| `test_03_viewer_changes_the_score_but_turn_player_does_not` | 4 | `viewer` ≠ `turn_player` — 한쪽은 점수를 뒤집고 한쪽은 안 움직인다 |
| `test_04_the_three_layers_disagree_about_the_turn` | 3 | State · Observation 은 구분, Evaluation 만 구분하지 않는다 |
| `test_05_handing_over_the_turn_costs_nothing_in_the_score` | 3 | 엔진이 스스로 만드는 합법 쌍 — 턴 넘김이 공짜다 |
| `test_06_within_one_decision_the_turn_is_the_same_for_every_candidate` | 6 | 한 결정 안에서 차례는 상수 → 순위에 영향 없음 |
| `test_07_the_actor_is_the_turn_player_at_every_decision` | — | 1053/1053 — 현재 차례는 `viewer` 로 안다 |
| `test_08_neither_policy_reads_the_turn_to_prefer_acting` | — | 두 정책 모두 차례를 읽지 않는다 (§14) |

§17-5(hidden information 유입)는 평가를 바꾸지 않았으므로 기존
`test_02_the_evaluator_reads_no_hidden_channel` 이 그대로 지킨다.

**의도적 위반 주입 1건.** 평가에 `view.is_my_turn` 을 읽고 `±400` 항을 넣었더니
`test_02` · `test_04` · `test_05` 셋이 잡았다. 되돌린 뒤
`git diff agent/ engine/` 가 비어 있음을 확인했다.

기존 테스트: **삭제 0 · skip 0 · assertion 완화 0 · 수정 0건.** Regression 0.

---

## 11. TODO

| 번호 | 상태 |
|---|---|
| **STRUCTURAL-128** | **AUDIT ONLY — CASE B (조건부 DESIGNED-OUT).** RESOLVED 로 닫지 않는다. 현재 평가 정의상 필요하지 않고 실측 순위 영향 0이지만, STRUCTURAL-34 개방 · 상대 턴 행동 · Depth-2 중 하나라도 들어오면 다시 열린다 |
| 102 · 107 · 109 · 110 · 116 · 118 · 120 · 122 · 123 · 129 · 130 · 131 · 132 · 133 | **전부 유지**, 손대지 않았다 |

새로 만든 TODO 없음.

---

## 12. 다음 Phase 후보 — 하나만

**STRUCTURAL-34 — 응답 · 우선권 창이 열리는 자리가 없다.**

이번 Audit 이 직접 가리킨 것이다.

1. **STRUCTURAL-128 의 증상을 막고 있는 것이 바로 이것이다** — END 페이즈에
   후보가 하나뿐인 이유가 응답 창이 열리지 않아서다. 그래서 128 을 고치기
   전에 34 가 먼저다. 순서가 뒤바뀌면 "증상 없는 것을 고치고, 고친 것이 맞는지
   확인할 방법이 없는" 상태가 된다
2. **가중치를 만들지 않는다** — 발동 기회를 어디서 주는가는 룰 문제이고,
   공식 룰북에 근거가 있다 (RULE-SPELLTRAP-007 Quick-Play · RULE-CHAIN-004
   Spell Speed · RULE-CHAIN-009 턴 플레이어 우선권). 3-E-3 에서 이미 인용했다
3. **이미 자료가 다 있다** — `PriorityState` 와 `ResponseLoop` 가 구현되어
   있는데 **아무도 열지 않는다** (STRUCTURAL-34 의 정의 그대로). 새 시스템을
   만드는 일이 아니라 **연결하는 일**이다
4. 열리면 128 · 123 · 133 이 **동시에 측정 가능해진다** — 차례가 상수가 아닌
   결정이 생기고, 두 정책의 차이가 드러나고, `UNKNOWN` 이 실제로 발생한다

Depth-2 는 그다음이다. 129(`hand` 비대칭)와 131(표시 형식)은 각각 영합 설계와
STRUCTURAL-108 의 나머지 절반에 묶여 있어 지금 할 수 없다.
