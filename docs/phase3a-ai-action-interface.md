# Phase 3-A — AI Action Interface

기준 커밋: `0088cc6` (Phase 2-AO / ENGINE V1 FREEZE) · 2961 passed / 4 skipped
→ 이번 단계: **2982 passed / 4 skipped**

한 줄 결론: **AI 가 엔진을 쓰는 창을 열었다.** 정책 둘이 듀얼 한 판을
끝까지 둔다. `engine/` 은 **한 줄도 고치지 않았다.**

> 명세가 §1 중간에서 잘려 들어왔다 (§0 의미 · §1 최종 목표의 흐름도까지
> 받았다). 그 흐름도를 그대로 목표로 삼았다.

---

## 1. 흐름도 그대로

```
GameState
    ↓  Duel.view(seat)
GameStateView(viewer)      ← 정책이 보는 전부
    ↓  Duel.legal_actions(seat)
LegalActions               ← 정책이 고를 수 있는 전부
    ↓  Policy.decide(view, legal)
PlayerAction
    ↓  DuelRunner 가 다시 확인
    ↓  Duel.apply(action)
GameState'
    ↓
반복
```

```python
from agent import RandomPolicy, play
from engine.duel import Duel

duel = Duel.start(repo, decks=(deck, deck), seed=5)
record = play(duel, (RandomPolicy(1), RandomPolicy(2)))

record.result        # DuelResult(winner=0, reason='P1: 덱에서 뽑을 수 없다')
record.refusals      # ()  — 정책이 규약을 어긴 적 없다
record.describe_ko() # '100걸음 · 규칙 15회 · P1: 덱에서 뽑을 수 없다'
```

---

## 2. `engine/` 을 고치지 않았다

V1 은 얼렸다. 그래서 **새 꾸러미**를 만들었다.

```
agent/__init__.py    공개 API
agent/policy.py      Policy · Decision · 기준점 셋
agent/runner.py      DuelRunner · Transcript
```

`engine/` 안의 파일은 **0개 변경**. 시험이 그것까지 본다 — `agent/` 어디에도
판을 바꾸는 호출(`draw` · `move` · `set_result` · `change_life` …)이 없다.

`LegalActionGenerator` 를 **따로 만들지 않았다.** 그 일은 이미
`Duel.legal_actions()` 가 한다. 떼어내려면 우선권·체인(판 **밖**에 사는 흐름의
위치)을 함께 넘겨야 하고, 그러면 2-AO 가 세운 경계가 흐려진다.

---

## 3. 경계 셋 — 이 단계가 지키는 것

### (1) 정책은 **관측과 후보 목록만** 본다

`Duel` 도 `GameState` 도 정책에게 가지 않는다. 가면 정책이 상대 패를
읽거나 판을 바꿀 수 있고, 그 순간 "AI 가 엔진을 쓴다" 가 "AI 가 엔진이다"
가 된다.

AST 로 못박았다 — `decide` 를 부르는 자리가 넘기는 것은
`self.duel.view(seat)` 와 `legal` **둘뿐**이고, 키워드 인자도 없다.

관측 경계도 그대로다: 정책이 받은 모든 관측에서 상대 패는 `concealed` 이고
`cards == ()` 다. **장수만** 보인다.

### (2) 정책의 말은 **허가가 아니다**

돌려준 것을 그대로 적용하지 않는다. 후보 목록에서 다시 확인하고, 없으면
거절한다 — 엔진이 `UNKNOWN` 을 허가로 바꾸지 않는 것과 **같은 자리**다.

| 정책이 돌려준 것 | 러너의 답 |
|---|---|
| 목록에 없는 행위 | 거절 · 판 그대로 |
| 남의 자리의 행위 | 거절 |
| `PlayerAction` 이 아닌 것 | 거절 |
| 고를 것이 있는데 `None` | 거절 — "고를 것이 없다" 와 다른 사실이다 |

거절은 **조용하지 않다.** `Transcript.refusals` 에 이유와 함께 남고, 거기서
**멈춘다** — 계속 돌리면 같은 거절이 기록을 채운다.

### (3) 정책의 난수는 **듀얼의 난수가 아니다**

이것은 이번에 정한 것이 아니다. `RandomPurpose` 가 2-Z 에 이미 적어 두었다.

> "`AI_*` 를 여기 두지 않는다. 탐색·정책의 무작위는 규칙의 무작위와 다른
> 계층이고, 한 열거형에 섞으면 같은 난수원을 쓰게 된다 — 그러면 **AI 가
> 한 번 더 생각했다는 이유로 듀얼의 결과가 달라진다.**"

`RandomPolicy` 는 제 `random.Random` 을 들고 다닌다. 정책이 **500번을 더
뽑아도** 덱 셔플은 그대로라는 것을 시험이 확인한다.

씨앗은 **필수**다 — 씨앗 없는 무작위는 재현할 수 없고, 이 저장소는 그것을
다른 모든 자리에서 이미 거부한다.

---

## 4. 재현

| 바뀐 것 | 판 |
|---|---|
| 아무것도 | **같다** |
| 정책 씨앗 | **다르다** |
| 듀얼 씨앗 | **다르다** |

두 번째 줄이 중요하다. 정책이 달라져도 판이 같다면 **정책이 아무 일도
하지 않는다**는 뜻이다.

`Transcript.canonical_state()` 가 비교의 단위다 — 받아들여진 행위의 열과
결과만 담고 **정책 이름은 넣지 않는다**. 같은 수를 둔 두 정책은 같은 판을
만든다.

---

## 5. 지금 AI 에게 주어진 방의 크기 (정직하게)

```
결정 지점 90곳
  후보 1개     60곳 (67%)   페이즈를 넘기는 것 말고 할 것이 없다
  후보 4~11개  30곳 (33%)   메인 페이즈 — 패의 몬스터를 소환할 수 있다
```

고를 것이 둘 이상인 자리는 **전부 MAIN1 · MAIN2** 다.

방이 좁은 이유는 Engine V1 의 **알려진 한계**다 — 마법 발동과 우선권 창이
아직 없다 (STRUCTURAL-103). **AI 가 할 일이 적은 것이지 인터페이스가 좁은
것이 아니다.** 그 한계가 풀리면 같은 인터페이스로 방이 넓어진다.

---

## 6. 기준점 정책 셋 — **AI 가 아니다**

| | 하는 일 |
|---|---|
| `FirstLegalPolicy` | 언제나 목록의 첫 번째 |
| `RandomPolicy(seed)` | 제 난수원으로 하나 |
| `ScriptedPolicy(plan)` | 미리 정한 순서대로, 떨어지면 fallback |

**평가 함수도 탐색도 학습도 없다.** 시험이 그것을 확인한다 — `agent/`
전체에 `evaluate` · `minimax` · `mcts` · `rollout` · `reward` · `train` 이
하나도 없다. 인터페이스가 도는지 보이기 위한 기준점이다.

---

## 7. 코드 변경

| 파일 | |
|---|---|
| `agent/__init__.py` | 신규 |
| `agent/policy.py` | 신규 — `Policy` · `Decision` · 기준점 셋 |
| `agent/runner.py` | 신규 — `DuelRunner` · `Transcript` · `play` |

**`engine/` 변경 0건. 기존 테스트 수정 0건.**

---

## 8. 테스트

- New tests: **21** (`tests/agent/test_action_interface.py`)
- Passed **2982** / Failed 0 / Skipped 4 / Regression **0**

| 무엇을 | 시험 |
|---|---|
| 정책은 관측과 목록만 받는다 | `test_a_the_policy_only_ever_receives_a_view_and_a_list` |
| **AST 로 못박는다** | `test_a_the_runner_hands_over_nothing_else` |
| 상대 패는 안 보인다 | `test_a_the_policy_cannot_see_the_opponents_hand` |
| **더 생각해도 판은 그대로** | `test_a_thinking_harder_does_not_change_the_duel` |
| `agent/` 가 엔진을 안 건드린다 | `test_a_the_agent_package_does_not_touch_the_engine` |
| 거절 넷 + 멈춤 | `test_b_*` (5개) |
| 한 판이 끝까지 돈다 | `test_c_two_random_policies_finish_a_duel` |
| 기록이 누가 무엇을 골랐는지 담는다 | `test_c_the_transcript_records_who_chose_what` |
| 정책이 판을 움직인다 | `test_c_a_scripted_policy_can_steer_the_duel` |
| 재현 셋 + 씨앗 필수 | `test_d_*` (5개) |
| **방의 크기 측정** | `test_e_how_much_room_a_policy_actually_has` |
| 상한에서 소리를 낸다 | `test_e_the_runner_gives_up_loudly_rather_than_spinning` |
| 기준점은 AI 가 아니다 | `test_e_the_baseline_policies_are_not_ai` |

---

## 9. TODO

- **STRUCTURAL-103 (우선권 창) — 🟠 그대로.** AI 의 방을 좁히는 가장 큰
  이유다. 이것이 풀리면 마법 발동과 체인 응답이 같은 인터페이스로 들어온다.
- **STRUCTURAL-77 (아키타입 조건) — 🟠 그대로.** 카드 coverage 의 1위.
- **AI 쪽의 다음 것들은 아직 만들지 않았다** — 평가 함수 · 탐색 · 학습 ·
  관측의 특징 벡터화. 인터페이스가 먼저다.
- 102 · 101 · 97 · 95 · 93 · 90 · 87 · 86 · 83 · 76 · 75 · 74 · 61 — 그대로.

---

## 10. 판정

| 등급 | 건수 |
|---|---:|
| 🔴 BLOCKER | **0** |
| 🟠 STRUCTURAL | 0 신규 |
| 🟡 DETAIL | 0 신규 |
| 🟢 COSMETIC | 0 신규 |

**다음 Phase 는 시작하지 않았다.**
