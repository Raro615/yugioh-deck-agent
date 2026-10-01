# Phase 3-D — AI vs AI / Search Validation

- **Base commit**: `40ea6c8` (Phase 3-C — Search / Simulation AI)
- **Branch**: `claude/pensive-goodall-te1egy`
- **결과**: 3056 → **3089 passed, 4 skipped** · 새 테스트 33개 · 회귀 0건
- **`engine/` 변경**: **0건** — ENGINE V1 FREEZE 유지 (3-A·3-B·3-C·3-D 네 Phase 연속)

---

## 1. 만든 것

| 파일 | 상태 | 내용 |
|---|---|---|
| `agent/arena.py` | 신규 | `run_match` · `run_series` · `summarize` · `MatchResult` · `MatchOutcome` · `DecisionRecord` · `MatchupSummary` · 정책 공장 4개 |
| `agent/runner.py` | 수정 | `TranscriptEntry` 에 결정 시점 자리표 3칸 추가 (`turn_number` · `phase` · `legal_count`) |
| `agent/__init__.py` | 수정 | 3-D 이름 13개 추가 export |
| `tests/agent/test_ai_vs_ai.py` | 신규 | 테스트 33개 (§20 의 모든 그룹) |

**러너를 새로 만들지 않았다.** `DuelRunner` 가 이미 정책 둘을 받고 자리마다
`view(seat)` 를 넘긴다 (Phase 3-A). 아레나가 더한 것은 둘뿐이다.

1. **정책을 판에 붙인다** — `SearchPolicy` 는 그 듀얼의 `Simulator` 가 필요해서
   판보다 먼저 존재할 수 없다. 그래서 `PolicyFactory` 가 `(duel, seat)` 를 받는다.
2. **끝나지 않은 판을 예외가 아니라 결과로 적는다** — 여러 판을 줄줄이 돌릴 때
   한 판이 터져서 나머지를 못 보게 되면, 터진 것도 측정값이라는 사실을 잃는다.

### `TranscriptEntry` 를 왜 늘렸나

§11·§12 가 결정 흔적에 **턴 · 페이즈 · 후보 수**를 요구한다. 이 셋은 **러너만
적절한 순간에 알고 있다** — 적용이 끝난 뒤에는 페이즈가 이미 옮겨가 있어서
밖에서는 "어느 페이즈에서 고른 것인가" 를 되찾을 수 없다. 그래서 새 구조를
만들지 않고 기존 기록에 세 칸을 더했다 (§12 "기존 trace 구조를 재사용한다").

모르는 값의 기본값은 **`-1` 과 `None` 이고 `0` 이 아니다.** `0` 은 "첫 턴" ·
"후보 없음" 이라는 사실이지만 여기서는 "모른다" 를 적어야 한다.

## 2. Repository Audit (§21) — 전부 기존 구조다

| 필요 | 쓴 것 | 새로 만들었나 |
|---|---|---|
| 정책 인터페이스 | `agent.policy.Policy` (`decide(view, legal)`) | **아니오** |
| 러너 | `agent.runner.DuelRunner` / `play()` | **아니오** (자리표 3칸만 추가) |
| 관측 | `engine.game_state_view.GameStateView.from_state(viewer=)` | **아니오** |
| 후보 | `engine.duel.Duel.legal_actions(seat)` | **아니오** |
| 적용 | `engine.duel.Duel.apply()` | **아니오** |
| 지문 | `engine.state.game_state.GameState.state_hash()` | **아니오** |
| 난수 | `GameState.randomness` (`RandomSource`) | **아니오** |
| 시뮬레이션 | `agent.simulation.Simulator` (3-C) | **아니오** |
| 평가 | `agent.evaluation.StateEvaluator` (3-C) | **아니오** |
| 정책들 | `SearchPolicy` · `RuleBasedPolicy` · `RandomPolicy` · `FirstLegalPolicy` · `ScriptedPolicy` | **아니오** |
| 안전 상한 | `agent.runner.MAX_STEPS = 5000` | **아니오** |

중복 Policy 인터페이스 · 중복 Runner · 중복 Simulation 엔진 — **하나도 만들지
않았다.** `ENGINE CHANGE REQUIRED` 는 없었다.

## 3. AI vs AI 실행 경로

```
          DuelRunner (Phase 3-A, 그대로)
   ┌──────────────┴──────────────┐
view(0) / legal_actions(0)    view(1) / legal_actions(1)
   ↓                              ↓
Policy P0.decide(…)           Policy P1.decide(…)
   ↓ PlayerAction                 ↓ PlayerAction
          Duel.apply() — 같은 엔진, 같은 검증
```

두 정책이 **같은 관측 객체를 돌려 쓰지 않는다**: 시험이 P0 이 받은 관측 객체의
`id` 집합과 P1 의 것을 교차시켜 **교집합이 빈 것**을 확인한다.

## 4. Policy Matrix (§17) — seed 1~16, 실제 카드 112판

| P0 | P1 | 완주 | 거절 | 예외 | 상한 | 평균 턴 | 수 | 시뮬레이션 | 승자 |
|---|---|---|---|---|---|---|---|---|---|
| Search | RuleBased | **16/16** | 0 | 0 | 0 | 32.0 | 3136 | 1830 | P0 ×16 |
| RuleBased | Search | **16/16** | 0 | 0 | 0 | 32.0 | 3136 | 1853 | P0 ×16 |
| Search | Search | **16/16** | 0 | 0 | 0 | 32.0 | 3136 | **3683** | P0 ×16 |
| Search | Random | **16/16** | 0 | 0 | 0 | 32.0 | 3136 | 1830 | P0 ×16 |
| Random | Search | **16/16** | 0 | 0 | 0 | 32.0 | 3136 | 1853 | P0 ×16 |
| Search | FirstLegal | **16/16** | 0 | 0 | 0 | 32.0 | 3136 | 1830 | P0 ×16 |
| FirstLegal | Search | **16/16** | 0 | 0 | 0 | 32.0 | 3136 | 1853 | P0 ×16 |

행동 분포는 **일곱 조합 모두 똑같다**: `end_phase` 2976 · `normal_summon` 160.

`Search vs Search` 의 시뮬레이션 3683 ≈ 1830 + 1853 — 두 자리의 탐색이
**따로 세어지고 서로 더해진다**. 한쪽이 다른 쪽의 사본을 쓰지 않는다는 뜻이다.

### 승패를 우열로 읽지 않는다 (§18)

**모든 조합에서 P0 가 16/16 으로 이겼다.** 이것은 정책의 강함이 아니라
Phase 3-B 에서 이미 측정한 사실의 재확인이다 — `ATTACK` 이 후보에 없어 LP 가
움직이지 않고, 남은 패배 조건은 덱아웃 하나이므로 **승자는 누가 먼저 뽑느냐로
정해진다.** 정책을 어떻게 바꿔도 턴 수(32)와 수(3136)까지 동일하다.

그래서 이 Phase 는 다음을 **주장하지 않는다**: "Search 가 RuleBased 보다 강하다"
· "Search 가 더 좋은 AI 다" · "Search 가 승률에서 우위다."

## 5. Determinism (§8)

같은 씨앗 · 같은 설정 → `MatchResult.canonical_state()` 가 **완전히 일치**.
그 안에 들어 있는 것: 결과 등급 · 승자 · 턴 · 수 · 규칙 걸음 · 시뮬레이션 수 ·
거절 수 · 양쪽 LP · `state_hash` · 그리고 **결정마다** 자리 · 턴 · 페이즈 ·
후보 수 · 수의 정규 표현 · 수락 여부 · 후보 수 · 시뮬레이션 수 · 점수.

시간은 넣지 않았다 — 같은 대국을 두 번 돌리면 같은 수가 나오지만 같은
밀리초가 나오지는 않는다.

네 조합(`Search/RuleBased` · `RuleBased/Search` · `Search/Search` ·
`Search/Random`)에서 모두 PASS. 다른 씨앗 넷은 서로 다른 `state_hash` 를
만든다 — 재현이 "언제나 같다" 가 아니라는 것도 확인했다.

### 감싸도 대국이 달라지지 않는다

아레나는 결정 시간을 재려고 정책을 `_Timed` 로 감싼다. 감싸지 않은 경로
(`play()` + `search_policy()`)와 감싼 경로(`run_match`)가 **같은 `state_hash`
와 같은 수의 순서**를 만드는지 확인한다.

## 6. RNG Isolation (§7)

| 항목 | 결과 |
|---|---|
| Game RNG — 대국 내내 탐색이 좌표를 움직이지 않는가 | **PASS** (양쪽이 탐색하는 대국 전체에서 `randomness.draws` 가 단 하나의 값) |
| Search RNG — 사본의 난수원이 원본과 분리되는가 | **PASS** (3-C `test_16`: 사본에서 50회 돌려도 원본 불변) |
| Search ON/OFF — 같은 수를 두면 같은 대국인가 | **PASS** (`state_hash` · 승자 · 턴 · 수 · LP · 수의 순서 전부 일치) |
| Policy RNG — 자리마다 다른 씨앗인가 | **PASS** (`make_random(seed)` → `seed + seat`) |

`make_random` 이 자리마다 씨앗을 다르게 주는 이유: 같은 씨앗을 양쪽에 주면 두
정책이 같은 순서로 뽑아서 **서로 독립인 정책 둘이 아니라 거울 둘**이 된다.

### 다시 적어 두는 제약 (3-C 에서 이어짐)

측정: 대국 전체에서 `randomness.draws` 가 **초기 셔플 2회 뒤로 한 번도 움직이지
않는다.** 즉 현재 행동 공간에는 난수를 꺼내는 수가 없다. 그래서 §7 식 시험만으로는
`clone` → `project` 회귀를 잡지 못한다 — 그것을 잡는 것은 사본의 난수원을 직접
돌리는 3-C 의 `test_16` 하나다. 숨기지 않고 다시 적는다.

## 7. Hidden Information (§5 · §11)

| 항목 | 결과 |
|---|---|
| P0 관측 분리 | **PASS** — `view.viewer == 0`, 상대 패 `cards == ()`, 양쪽 덱 `cards == ()` |
| P1 관측 분리 | **PASS** — 같음 |
| 관측 객체 공유 | **없음** — 두 자리의 `id` 집합 교집합이 빔 |
| 정책이 판을 받는가 | **아니오** — `GameStateView` 뿐, `draw`·`move`·`set_result`·`apply`·`state_hash` 손잡이 없음 |
| 흔적에 가려진 정보 | **없음** — `DecisionRecord` · `MatchResult` 어느 칸에도 `Duel` · `GameStateView` · `Simulator` 가 없고 `state`·`future`·`view` 라는 칸도 없다 |

## 8. Simulation Safety (§6 · §10)

| 항목 | 결과 | 확인 방법 |
|---|---|---|
| 원본 불변 | **PASS** | 결정마다 고르기 **전후**로 판을 찍어 비교. 100회 이상, **양쪽이 동시에 탐색하는 대국**에서 |
| 사본 독립 | **PASS** | P0 가 후보를 전부 해 본 직후 P1 의 관측이 **변하지 않았다** |
| 실패 격리 | **PASS** | 후보 밖의 수를 해 보게 한 뒤 같은 시뮬레이터로 대국이 계속된다 |

찍어 비교한 mutation surface는 3-C 와 같다: `state_hash` · `draws` · 턴 ·
페이즈 · `step` · `priority` · `result` · 양쪽 LP · 덱 · 패 · 몬스터존 ·
마법함정존 · 묘지 · 제외의 **instance_id 순서**.

## 9. Game Loop Safety (§14 · §15)

| 상황 | 결과 |
|---|---|
| 정책이 `None` 을 돌려준다 | `POLICY_REFUSED`, **승자 `None`** — 강제 실행하지 않는다 |
| 정책이 후보 밖의 수를 돌려준다 | `POLICY_REFUSED`, 판이 바뀌지 않는다, 흔적에 `accepted=False` |
| 정책이 예외를 던진다 | `MatchOutcome.ERROR` + 예외 이름, **승자 `None`** |
| 걸음 상한에 걸린다 | `GAME_LIMIT_REACHED`, **승자 `None`** |
| 같은 상태 반복 | 측정값: 같은 자리·같은 수 연속 **최대 1회** (정체 없음) |

`MatchOutcome` 을 엔진의 `DuelResult` 와 **다른 층**에 둔 이유: 한 칸에 담으면
"안전 상한에 걸렸다" 가 "졌다" 로 읽힌다. 상한은 무한 반복을 막는 장치이고
정상 종료를 **대체하지 않는다.**

## 10. Decision Trace (§11 · §12)

양쪽 정책에 똑같은 모양으로 남는다. 앞 여섯 칸은 **언제나** 채워지고, 뒤 네
칸은 **탐색일 때만** 채워진다 — 아니면 `None` 이고 **0 이 아니다.** 0 은
"후보가 없었다" 라는 사실이고 `None` 은 "탐색하지 않았다" 이며 둘은 다르다.

```
P0 T1 MAIN1 search-p0: normal_summon (후보 3) · 후보 3 시뮬 3 → ongoing +2800
P1 T2 MAIN1 search-p1: normal_summon (후보 6) · 후보 6 시뮬 6 → ongoing +900
P0 T3 MAIN1 search-p0: normal_summon (후보 3) · 후보 3 시뮬 3 → ongoing +2600
P1 T4 MAIN1 search-p1: normal_summon (후보 5) · 후보 5 시뮬 5 → ongoing +1100
```

### 점수가 엉뚱한 수에 붙지 않는다

아레나는 "자리 `s` 의 `n` 번째 걸음 = 그 정책의 `n` 번째 결정" 이라는 대응으로
탐색 흔적과 실제 수를 잇는다. 이 대응을 **가정하지 않고 확인한다**: 탐색 흔적의
`chosen` · `candidates` 수 · `simulations` · 턴 · 페이즈가 실제로 둔 수의 기록과
모두 일치하는지 맞춰 본다. 고의로 짝을 한 칸 밀면 시험 둘이 깨진다 (확인).

## 11. Performance (§25)

| 항목 | 값 |
|---|---|
| 총 대국 | **112** (7 조합 × 16 씨앗) |
| 총 턴 | 3,584 |
| 총 수 (결정) | 21,952 |
| 총 시뮬레이션 | 14,732 |
| 결정당 평균 시뮬레이션 | **0.671** |
| 결정 하나 평균 | **1.324ms** (중앙값 1.388ms) |
| 결정 하나 최대 | **161.5ms** |
| 총 런타임 | **64.3s** |
| 대국 한 판 평균 | **574ms** |
| invalid action | **0** |
| 예외 | **0** |
| 상한 초과 | **0** |

결정당 시뮬레이션이 0.671 인 이유: 비탐색 정책의 결정(절반)은 시뮬레이션이
0 이고, 탐색 쪽도 결정 지점의 대부분은 후보가 하나다.

최대 161.5ms 는 **첫 결정 한 번**이고 중앙값(1.388ms)의 116배다 — 카드 정의를
처음 읽을 때의 비용으로 보인다. 이번 Phase 에서 성능 최적화를 위한 구조 변경은
하지 않았으므로 원인을 단정하지 않고 측정값으로 남긴다. 대국 한 판 574ms 는
실제 진행을 방해하지 않는다.

## 12. 고의 위반으로 검사 기제를 확인했다

세 가지를 심어 보고 해당 시험이 깨지는 것을 확인한 뒤 되돌렸다.

| 심은 위반 | 깨진 시험 |
|---|---|
| 양쪽 정책에 `view(0)` 을 똑같이 넘김 | `test_each_policy_sees_only_its_own_side` |
| 탐색 흔적의 짝을 한 칸 밀기 | `test_the_decision_trace_is_the_same_shape_for_every_policy` · `test_the_search_trace_lines_up_with_the_actions_that_were_played` |
| 승패가 없는 판에 승자를 넣기 | `test_a_policy_that_returns_an_illegal_action_is_rejected` · `test_an_exploding_policy_is_recorded_not_swallowed` · `test_the_safety_budget_is_not_a_win` |

## 13. 테스트

| 항목 | 값 |
|---|---|
| 새 테스트 | **33개** |
| 전체 | 3056 → **3089 passed, 4 skipped** |
| 실패 | 0 |
| 기존 테스트 수정 | **0개** |
| 기존 테스트 삭제 | **0개** |
| 기대값 완화 | **0개** |
| 회귀 | **0건** (3-A 21 · 3-B 32 · 3-C 42 전부 유지) |

## 14. STRUCTURAL TODO

이번 Phase 에서 **해결한 구조 문제는 없다.** 이 Phase 는 검증이고, 발견된 제약은
전부 이전 Phase 의 것을 재확인한 것이다.

### 🟠 STRUCTURAL-102 (3-C 에서 계속, 해결하지 않음)

깊이 1 탐색의 후보 순위가 RuleBased 의 행동과 100% 같다. 3-D 가 더한 증거:
**일곱 조합의 행동 분포가 전부 동일하다** (`end_phase` 2976 · `normal_summon`
160). 정책을 바꿔도 턴 수와 수가 바뀌지 않는다.

### 🟠 STRUCTURAL-101 (3-B 에서 계속, 해결하지 않음)

평가값에 `lp` · `atk` 항이 있지만 **실제로 움직이는 것은 `atk` 뿐**이다.
3-D 측정: 112 대국 전부 LP 8000/8000 으로 끝나고, **모든 조합에서 P0 가
16/16 으로 이긴다.** 승패가 정책과 무관하다는 것이 7 조합으로 재확인되었다.

### 실제 관측된 legal action 제한 (3-D 112 대국 재측정)

| 행위 | 후보 등장 |
|---|---|
| `END_PHASE` | 2,976 |
| `NORMAL_SUMMON` | 160 |
| `ATTACK` | **0** |
| `SET_MONSTER` | **0** |
| `SET_SPELL_TRAP` | **0** |
| `ACTIVATE_CARD` | **0** |
| `ACTIVATE_EFFECT` | **0** |
| `CHANGE_POSITION` | **0** |
| `PASS` | **0** |

### 🟡 DETAIL

- 현재 행동 공간에 난수를 꺼내는 수가 없어 §7 식 시험만으로는 `clone`→`project`
  회귀를 잡지 못한다 (3-C 에서 이어짐). 3-C `test_16` 이 잡는다.
- 결정 하나 최대 시간이 중앙값의 116배(161.5ms vs 1.388ms). 첫 결정 한 번이다.
  원인을 단정하지 않고 측정값으로 남긴다.
- `_Timed` 래퍼가 정책과 러너 사이에 한 겹 들어간다. 고른 것을 바꾸지 않는
  것은 시험이 확인하지만, 래퍼 없는 경로도 계속 유지된다 (`play()`).

## 15. 이번 Phase 에서 하지 않은 것 (§22 그대로)

MCTS · Monte Carlo Tree Search · Depth-2/3 Search · 깊은 게임 트리 · 강화학습 ·
PPO · DQN · 신경망 · PyTorch · self-play · 유전 알고리즘 · LLM 판단 · 덱 빌더 ·
카드 평가 AI · 새 효과/이벤트/그래프 엔진 · transposition table · determinization ·
belief state · 상대 비공개 정보 재구성 · `ATTACK` 구현 · 전투 시스템 ·
마법·함정 전체 구현 · Discord 봇 · 웹 UI · WebSocket · REST API ·
Engine V1 unfreeze — **하나도 하지 않았다.**

`agent/` 전체를 식별자 단위로 검사하는 Phase 3-B 의 시험이 계속 감시한다.
