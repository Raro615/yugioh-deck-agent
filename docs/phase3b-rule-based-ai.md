# Phase 3-B — Rule-Based Duel AI

- **Base commit**: `1a76140` (Phase 3-A — AI Action Interface)
- **Branch**: `claude/pensive-goodall-te1egy`
- **결과**: 2982 → **3014 passed, 4 skipped** · 새 테스트 32개 · 회귀 0건
- **`engine/` 변경**: **0건** (설명 한 줄도 바꾸지 않았다 — ENGINE V1 FREEZE)

> 받은 스펙은 §3 중간("Rule-Based AI → Baseline → Search/Simulation →
> Self-Play/Learning" 흐름도)에서 끊겨 있었다. §0~§3 의 범위로 작업했고,
> 끊긴 뒤에 무엇이 있었는지는 추측하지 않았다.

---

## 1. 만든 것

| 파일 | 상태 | 내용 |
|---|---|---|
| `agent/heuristic.py` | 신규 | `Consideration` · `Appraisal` · `Evaluation` · `Judgement` · `RuleBasedPolicy` · 규칙 4개 |
| `agent/__init__.py` | 수정 | 3-B 이름 16개 추가 export |
| `tests/agent/test_rule_based_ai.py` | 신규 | 테스트 32개 (§0 · A~H) |
| `tests/agent/test_action_interface.py` | 수정 | 기존 테스트 1개의 잘못된 가정 교정 (§6) |

흐름:

```
GameStateView(viewer) + LegalActions
        ↓   Consideration 들이 후보마다 점수를 낸다
    Evaluation × 후보 수   →   Judgement (왜 그 수인가)
        ↓   가장 높은 하나
    PlayerAction  →  Duel Engine
```

---

## 2. 먼저 쟀다 — 규칙 기반 AI 가 실제로 마주하는 결정은 무엇인가

규칙을 짓기 전에 **엔진이 무엇을 후보로 내놓는지** 셌다. 실제 카드로
48 판(덱 구성 3종 × 씨앗 12개), 결정 지점 4,104 곳:

| 후보로 나타난 행위 | 횟수 |
|---|---|
| `END_PHASE` | 4,104 (모든 지점) |
| `NORMAL_SUMMON` | 1,115 |
| 그 밖의 모든 종류 | **0** |

`ATTACK` · `SET_MONSTER` · `SET_SPELL_TRAP` · `ACTIVATE_CARD` ·
`ACTIVATE_EFFECT` · `CHANGE_POSITION` · `PASS` 는 **한 번도** 후보에 오르지
않는다. 그래서 그것들을 보는 규칙을 쓰지 않았다 — **발화할 수 없는 규칙은
규칙이 아니라 희망이다.**

엔진이 규칙을 올바르게 보류하는 것도 확인했다 (각각 0건):

- 레벨 5+ 몬스터가 릴리스 없이 일반 소환 후보로 제시되는 일: **0**
- 몬스터 존이 꽉 찼는데 일반 소환이 제시되는 일: **0**

## 3. 규칙 네 개 — 전부 근거가 있다

각 규칙은 `basis` 를 들고 있고, 근거 없는 규칙은 **조립 단계에서 거부된다.**

| 규칙 | 하는 일 | 근거 |
|---|---|---|
| `summon-before-ending` | 소환 가능하면 턴 넘기기보다 소환 | 룰북: 일반 소환은 턴에 한 번이고 쓰지 않으면 사라진다 |
| `higher-attack-first` | 공격력 높은 쪽 먼저 | 룰북: 전투에서 공격력 높은 쪽이 낮은 쪽을 파괴한다 |
| `higher-defence-breaks-tie` | 공격력이 같으면 수비력으로 갈림 | 룰북: 수비 표시 몬스터는 수비력으로 싸운다 |
| `end-phase-as-last-resort` | 더 할 것이 없으면 턴을 넘긴다 (0점) | 다른 규칙이 값을 주지 못한 경우에만 남는 선택 |

### 점수는 지어낸 숫자가 아니다

가중치 셋은 **실제 카드 14,127 장을 세어서** 정했고, 테스트가 **다시 세서**
확인한다:

```
실측: 서로 다른 ATK 값 82개 · DEF 값 75개 · 둘 다 최소 간격 10 · 최대 5000
```

| 상수 | 값 | 왜 |
|---|---|---|
| `MIN_STAT_GAP` | 10 | 실측된 능력치 한 칸 |
| `ATK_WEIGHT` | 1,000 | 한 칸 = 10,000점 |
| `DEF_WEIGHT` | 1 | 최대 5,000점 — **공격력 한 칸을 넘지 못한다** |
| `BOARD_PRESENCE` | 10,000,000 | 능력치 최대 합(5,005,000)보다 크다 |

두 부등식이 규칙의 순위를 보장하고, 둘 다 테스트가 지킨다:

```
DEF 최대 5,000  <  ATK 한 칸 10,000           (수비력은 갈림용이다)
BOARD_PRESENCE  >  ATK·DEF 최대 합 5,005,000  (공격력 0 짜리라도 두는 게 낫다)
```

카드가 늘어나 실측이 바뀌면 `test_b_the_weights_are_measured_from_the_real_cards`
가 **먼저** 깨진다 — 부등식이 조용히 무너지는 것보다 낫다.

## 4. 모르는 것을 숫자로 바꾸지 않는다

공격력이 `?` 인 몬스터를 0 으로 읽으면 가장 약한 카드가 되고, 큰 수로
읽으면 가장 강한 카드가 된다. **둘 다 거짓이다.** 그래서
`HigherAttackFirst` 는 `None` 을 돌려주고 — **판단을 포기한다.**

포기는 0점이 아니다. 0점은 "재어 봤더니 0" 이고 포기는 "재지 못했다" 이며,
`Evaluation.abstained` 가 그 둘을 끝까지 분리해 둔다. 어떤 규칙도 어떤
후보도 보지 못하면 `Judgement.nothing_was_judged` 가 참이 되고 기록에
"규칙이 모자랍니다" 가 남는다 — 고르기는 하지만 **아는 척하지 않는다.**

포기는 카드마다가 아니라 **값마다**다. `저주받은 하인 킹`(ATK ? / DEF 0)
에서 공격력 규칙은 포기하고 수비력 규칙은 판단한다.

### 발견: `ATK ?` 는 지금 듀얼에서 볼 수 없다

공격력이 `?` 인 메인덱 몬스터는 **하나도 빠짐없이 효과 몬스터**다(실측).
효과 몬스터는 `ActionValidator` 가 `summoning-condition` 미구현을 이유로
`UNKNOWN` 을 돌려주므로 후보에 오르지 않는다. 즉 **포기 가지는 전체
듀얼에서 0번 발화한다.**

그래도 지우지 않았다 — 지우면 `?` 를 숫자로 읽는 구조가 된다. 대신
후보 목록을 손으로 만들어 **실제 카드·실제 관측으로** 따로 시험하고,
`test_every_question_mark_monster_is_an_effect_monster` 가 이 전제 자체를
공식 DB 에서 감시한다.

## 5. 경계 — 규칙은 고르기만 한다

| 보장 | 어떻게 |
|---|---|
| 행위를 **만들지 않는다** | `heuristic.py` 에 `PlayerAction(...)` 호출이 0건 (AST) |
| 판을 **만지지 않는다** | `project`·`clone`·`apply`·`advance`·`draw`·`move`·`set_result`·`state_hash`·`legal_actions` 이름 사용 0건 (AST) |
| `Duel` 을 **들이지 않는다** | `engine.duel` 에서 가져오는 이름 = `{LegalActions}` 뿐 |
| 난수가 **없다** | `random`·`secrets`·`copy` import 0건 |
| 규칙 하나는 **후보 하나만** 본다 | `appraise(self, view, action)` — 목록 전체를 주지 않는다 |
| §2 의 금지 목록 | `torch`·`mcts`·`rollout`·`reward`·`neural`·`dqn`·`ppo`·`genetic` 등 20개 이름을 꾸러미 전체에서 검사 (설명문 제외) |

**네 가지 경계 검사가 고의로 심은 위반을 실제로 잡는지 확인했다** —
`import numpy` / `PlayerAction.passing(...)` / `view.project` /
`from engine.duel import Duel` / `reward = 0` 을 각각 넣어 해당 테스트가
깨지는 것을 보고 되돌렸다.

왜 "거절" 이 아니라 "떠올릴 수 없게" 인가: 규칙이 행위를 만들 수 있으면
허가받지 않은 수를 떠올릴 수 있고, 그러면 거절이 `DuelRunner` 의 몫으로
미뤄진다. 떠올릴 수 없게 만드는 것이 거절하는 것보다 낫다.

## 6. 기존 테스트 1개를 고쳤다 — 왜 그 가정이 틀렸는가

`test_e_the_baseline_policies_are_not_ai` (Phase 3-A).

- **그때 한 일**: `agent/` **꾸러미 전체**의 소스를 읽어 `evaluate` ·
  `minimax` · `mcts` · `rollout` · `reward` · `train` 이 없음을 주장했다.
- **왜 틀린 가정이었나**: Phase 3-A 시점에 꾸러미에는 기준점 정책밖에
  없었으므로 "꾸러미" 와 "기준점 정책" 이 **구별되지 않았다.** 그래서
  둘을 같은 것으로 적었다. 주장하려던 것은 *기준점이 AI 가 아니다* 이지
  *이 꾸러미는 영원히 평가하지 않는다* 가 아니었다. 평가 함수는 §1 이
  이번 Phase 에 요구한 것이다.
- **어떻게 고쳤나**: 읽는 대상을 `agent/policy.py` 로 **좁혔다.** 원래의
  주장은 그대로 남는다. 꾸러미 전체에 탐색·학습이 없다는 보장은
  `test_h_the_agent_package_contains_no_search_and_no_learning` 이
  §2 의 목록 그대로, 더 넓게 이어받는다.
- **삭제한 테스트**: 없음.

## 7. 판단을 읽을 수 있다

`Judgement` 는 **고른 것만** 남기지 않는다. 고르지 않은 후보의 점수가
없으면 "왜 저것이 아니었는가" 에 답할 수 없다.

```
P0: normal_summon: 소환권을 버리지 않는다; 공격력 1700; 수비력 1000
 → normal_summon P0 #0 → 11701000 (summon-before-ending=10000000, higher-attack-first=1700000, higher-defence-breaks-tie=1000) · 보류 1
   normal_summon P0 #3 → 11701000 (summon-before-ending=10000000, higher-attack-first=1700000, higher-defence-breaks-tie=1000) · 보류 1
   normal_summon P0 #2 → 11501200 (summon-before-ending=10000000, higher-attack-first=1500000, higher-defence-breaks-tie=1200) · 보류 1
   normal_summon P0 #1 → 11200900 (summon-before-ending=10000000, higher-attack-first=1200000, higher-defence-breaks-tie=900) · 보류 1
   normal_summon P0 #4 → 10001000 (summon-before-ending=10000000, higher-attack-first=0, higher-defence-breaks-tie=1000) · 보류 1
   end_phase P0 → 0 (end-phase-as-last-resort=0) · 보류 3
```

`#0` 과 `#3` 은 점수가 **완전히 같다**(같은 카드). 그때는
`canonical_state` 가 작은 쪽을 고른다 — **후보 목록의 순서에 기대지
않는다.** 목록 순서는 엔진이 패를 어떻게 훑는지에 달린 구현 세부이고,
그것이 바뀌어서 AI 의 수가 바뀌면 설명할 수 없다. 테스트가 목록을 뒤집어도
같은 수가 나오는지 확인한다.

## 8. 네 규칙 모두 실제로 발화한다

실제 카드 16 판, P0 자리, 결정 지점 1,616 곳:

| 규칙 | 발화 | 판단 포기 |
|---|---|---|
| `summon-before-ending` | 214 | 1,616 |
| `higher-attack-first` | 214 | 1,616 |
| `higher-defence-breaks-tie` | 214 | 1,616 |
| `end-phase-as-last-resort` | 1,616 | 214 |

- 한 번도 발화하지 않은 규칙: **0개**
- 아무 규칙도 판단하지 못한 지점: **0곳**
- 선택 여지가 있던 지점: **80 / 1,616 (5.0%)** — 나머지는 후보가 하나뿐이다

## 9. baseline 은 무엇보다 나은가 — 그리고 무엇은 아직 재지 못하는가

### 잴 수 있는 것: 끝났을 때 내 몬스터 존의 공격력 합

**상대를 고정하고 내 자리의 정책만 바꿨다.** 그렇게 하지 않으면 양쪽의
패가 달라져서 정책을 비교한 것이 아니게 된다 (처음 측정에서 이 함정에
빠졌고, 대조군을 바로잡았다).

| 정책 | 16판 합계 | 판당 평균 |
|---|---|---|
| **규칙 기반** | 115,000 | **7,188** |
| 무작위 | 97,900 | 6,119 |
| 첫 후보 | 100,400 | 6,275 |

규칙 기반이 더 높은 판 **10** / 낮은 판 **1** / 같은 판 **5**.

### 탐욕은 baseline 이지 정답이 아니다

16판 중 **1판에서 무작위가 더 좋은 판을 만들었다.** 매번 가장 센 몬스터를
고르면 몬스터 존이 찰 때까지의 **순서**가 바뀌고, 한 수도 내다보지 않는
규칙으로는 이것을 고칠 수 없다. 이것이 다음 단계가 탐색인 이유다.
`test_f_greedy_is_not_the_best_play` 가 이 사실을 기록한다.

### 재지 못하는 것: **승률**

| seed | 규칙 기반 | 무작위 | 첫 후보 |
|---|---|---|---|
| 1 | P0 승 · 196걸음 · LP 8000/8000 | 동일 | 동일 |
| 4 | P0 승 · 196걸음 · LP 8000/8000 | 동일 | 동일 |
| 8 | P0 승 · 196걸음 · LP 8000/8000 | 동일 | 동일 |

**승패가 정책과 완전히 무관하다.** 이유는 규칙이 아니라 엔진에 있다:

1. `ATTACK` 이 후보에 오르지 않는다 (측정: 4,104 지점에서 0회)
2. 그래서 **LP 가 8000 에서 움직이지 않는다**
3. 남은 패배 조건은 덱아웃 하나이고, 그것은 누가 먼저 뽑느냐로 정해진다

즉 지금 엔진은 **잘 둔 것에 보상을 줄 수 없다.** Phase 3-A 가 "정책을
바꾸면 듀얼이 달라진다" 고 한 것은 사실이고(판과 transcript 가 달라진다),
거기에 "**승패는 달라지지 않는다**" 가 추가된다.

`test_f_the_winner_does_not_yet_depend_on_the_policy` 가 이것을 기록한다.
전투가 들어오면 이 테스트가 깨지고, **그때 깨지는 것이 옳다.**

## 10. 분류

| 등급 | 내용 | 다음 단계를 막는가 |
|---|---|---|
| **BLOCKER** | 없음 | — |
| **STRUCTURAL-101** | `ATTACK` 이 후보에 오르지 않아 LP 가 변하지 않고, 그래서 **승률로 AI 를 평가할 수 없다.** 탐색·학습은 평가 신호를 필요로 하므로 이것이 해결되기 전에는 "더 나은 AI" 를 주장할 수 없다 | **Phase 3-B 는 막지 않는다** (규칙은 짓고 시험할 수 있다). **탐색/학습 단계는 막는다** |
| **coverage** | 효과 몬스터는 `summoning-condition` 미구현으로 전부 `UNKNOWN` → 일반 소환 후보가 통상 몬스터로 제한된다. `ATK ?` 포기 가지가 듀얼에서 발화하지 않는 원인 | 막지 않음 (규칙은 단위 시험으로 검증됨) |
| **coverage** | `PASS` 가 후보에 오르지 않는다 (우선권을 여는 규칙이 없다) | 막지 않음 |

STRUCTURAL-101 은 **이번 Phase 에서 고치지 않았다.** 고치려면 배틀 페이즈 ·
공격 선언 · 전투 데미지가 필요하고 그것은 `engine/` 을 여는 일이다 —
§2 가 "Engine V1 Freeze 해제" 를 금지했다.

## 11. 테스트

| 항목 | 값 |
|---|---|
| 새 테스트 | 32개 |
| 전체 | 2982 → **3014 passed, 4 skipped** |
| 기존 테스트 수정 | **1개** (§6 에 이유 명시) |
| 기존 테스트 삭제 | **0개** |
| 회귀 | **0건** |
| `engine/` 파일 변경 | **0건** |

구역: §0 시험 덱 검증 2 · A 경계 4 · B 가중치 4 · C 모르는 값 3 ·
D 실제 카드 판단 5 · E 결정론 4 · F baseline 3 · G 조립 거부 5 · H §2 2.

## 12. 하지 않은 것 (§2 그대로)

강화학습 · PyTorch · PPO · DQN · 신경망 · MCTS · Monte Carlo Tree Search ·
self-play · 유전 알고리즘 · LLM 기반 판단 · 덱 빌더 · 카드 추천 AI ·
Discord 봇 · 웹 UI · 전체 카드 풀 확장 · Engine V2 · Engine V1 Freeze 해제 —
**하나도 하지 않았다.** `test_h_the_agent_package_contains_no_search_and_no_learning`
이 이름으로 감시한다.
