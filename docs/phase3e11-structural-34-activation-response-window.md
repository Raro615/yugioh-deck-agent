# Phase 3-E-11 — STRUCTURAL-34 절반 구현 · Activation-Immediate RESPONSE Window

Base: `ef94d5d` (Phase 3-E-10 Audit · 판정 C)
범위: 발동 직후의 RESPONSE 창 **하나**.

---

## 0. 한 줄

```
전:  ACTIVATE_EFFECT → ChainLink → Resolution                    (한 apply)
후:  ACTIVATE_EFFECT → ChainLink → RESPONSE(상대) → PASS ×2 → Resolution
```

공식 근거 **RULE-CHAIN-001**

> "If a card's effect is activated, the opponent is **always** given a chance to
> respond with a card effect of their own, creating a Chain. … Both players
> continue to add effects to the Chain until **they both wish to add nothing
> else**, then you resolve the outcome in reverse order."

그래서 패스가 **두 번**이다 — 상대가 한 번, 발동한 쪽이 한 번.

**새 구조를 하나도 만들지 않았다.** 새 Priority/Response/Chain Engine 없음,
새 ActionKind 없음, 새 EventBus 없음. 3-E-10 Audit 이 "다음 Phase 는 새 구조를
만드는 일이 아니라 **이미 있는 것을 부르는 일**" 이라고 적었고, 그대로였다.

---

## 1. 변경 파일 (2개)

| 파일 | 무엇을 | 왜 |
|---|---|---|
| `engine/duel.py` | ① `ResponseLoop`/`ResponseState` import ② `pending_spells` 필드 ③ `_response_loop`/`_response_state()` ④ `legal_actions` 에 `and not self.priority.is_open` ⑤ `_apply_activation` 이 해결 대신 창을 연다 ⑥ `_apply_pass` 가 양쪽 패스 때 해결한다 ⑦ `_resolve_chain`/`_retire_pending` ⑧ **잠복 버그 수정** | 기회를 **여는 쪽**이 필요했다 |
| `agent/simulation.py` | `_settle_forced_passes` — 사본에서 **고를 것이 없는** 패스만 대신 밟는다 | 깊이 1 의 미래가 체인 도중이 되지 않게 |

`agent/evaluation.py` · `engine/game_state_view.py` · `agent/search.py` ·
`agent/policy.py` · `agent/heuristic.py` — **변경 0건.**

### 1-1. 고친 잠복 버그 하나

`PriorityState.both_passed` 는 `@property` 인데 `duel.py:557` 이
`both_passed()` 로 **괄호를 붙여** 불렀다. 그러면 bool 이 아니라 메서드
객체가 참으로 평가되어 **한 번의 패스로 기회가 닫힌다.**

3-E-10 Audit 이 이 자리를 "죽은 분기" 로 기록했고(우선권이 열리지 않아
`_apply_pass` 가 도달 불가), 그래서 아무도 밟지 않았다. 창을 여는 순간 바로
밟히는 자리였다. **괄호 하나를 지웠다.**

---

## 2. Execution Path (실제 코드 경로)

```
Duel.apply(ACTIVATE_EFFECT)
└ _apply_activation                              engine/duel.py
  ⓪ selections_for(definition, action)           engine/target_bridge.py
  ① NormalSpellPlacement.place                   engine/spell_activation.py
  ② EffectActivator.activate → Chain.push        engine/activation.py · chain.py
  ③ pending_spells += (placed,)                  ← 묘지로 보낼 시점이 밀렸다
  ④ ResponseLoop.opened(RESPONSE, 1-actor).priority    engine/response.py
    → return DuelStep("… 상대의 응답을 기다립니다.")

Duel.apply(PASS)  — 상대
└ _apply_pass → PriorityState.passed()           consecutive_passes 1
  → ResponseLoop.ready_to_resolve → INVALID(아직 차례)
    → return DuelStep("우선권을 넘겼습니다.")

Duel.apply(PASS)  — 발동한 쪽
└ _apply_pass → passed()                         consecutive_passes 2
  → ready_to_resolve → VALID
  └ _resolve_chain
    ⑤ ResponseLoop.resolve → ChainResolver.resolve_all    engine/chain.py
    ⑥ priority.closed(AFTER_CHAIN_RULE)          ← 응답 계층이 닫는다
    ⑦ _retire_pending → NormalSpellPlacement.retire  (RULE-SPELLTRAP-002)
    → return DuelStep("체인1 … 를 해결했습니다.", result=_check_end())
```

**기회를 닫는 쪽이 `duel.py` 에서 `response.py` 로 옮겨 갔다.** 닫는 이유
(`AFTER_CHAIN_RULE`)를 응답 계층이 들고 있으므로 거기서 닫는 것이 맞다 —
흐름을 두 곳에서 닫으면 둘이 갈라진다. 그래서 `duel.py` 에 `closed` 가
더 이상 없다.

---

## 3. Response Window

| | |
|---|---|
| **open** | `_apply_activation` 의 마지막 — `ResponseLoop.opened(chain, 1 - action.actor, …)`. 여는 자리는 **코드 전체에서 하나뿐**이다 (`test_02` 가 센다) |
| **response seat** | `1 - action.actor` — **발동한 쪽의 상대.** `turn_player` 가 아니다 |
| **pass** | 기존 `PlayerAction.passing` + `_flow_actions` 의 기존 분기. **새 ActionKind 를 만들지 않았다** (§10) — 이미 있었고, 창이 열리자 후보가 되었다 |
| **close** | `ResponseLoop.resolve` 가 `priority.closed(AFTER_CHAIN_RULE)` 로 닫는다 |

### 왜 패스가 두 번인가

RULE-CHAIN-001: "until **they both wish to add nothing else**". 상대가 거절한
뒤에도 발동한 쪽이 두 번째 효과를 붙일 수 있다("If your opponent does not
respond, **you may activate a second effect**"). 그래서 양쪽이 모두 "그만" 이라고
해야 해결이다. `PriorityState.consecutive_passes >= 2` 가 그 사실을 들고,
`ResponseLoop.ready_to_resolve` 가 그것을 읽는다.

---

## 4. PriorityState

| 시점 | holder | window | passes | chain |
|---|---|---|---|---|
| 발동 전 | `nobody` | `none` | 0 | 0 |
| **발동 후** | **`player_1`** | **`response`** | 0 | **1** |
| 상대 패스 후 | `player_0` | `response` | 1 | 1 |
| 양쪽 패스 후 (해결) | `nobody` | `none` | 0 | 0 |

**이번 Phase 에서 구현하지 않은 lifecycle**

- 페이즈 전환의 우선권 (`RULE-CHAIN-009` · `ResponseWindow.PHASE_CHANGE`) —
  `duel.py` 에 `PHASE_CHANGE` 가 한 번도 나오지 않는다
- 체인 해결 뒤 누구에게 열리는가 (`AFTER_CHAIN_RULE`) — `give_to` 를 부르지
  않는다
- Trigger 자동 발동 · Damage Step · Battle Step

---

## 5. legal_actions

### Response OFF (창이 닫혀 있을 때) — **한 건도 변하지 않는다**

더한 조건은 `and not self.priority.is_open` **하나**이고, 창이 닫혀 있으면
그 조건은 **늘 참**이므로 기존 경로가 그대로다. `test_h` 가 후보 집합을
그대로 고정한다.

### Response ON

| 자리 | 후보 |
|---|---|
| 응답 자리 (상대) | `PASS` — 그것뿐 |
| 턴 플레이어 | **없음** |

턴 플레이어에게 소환·세트·공격을 주지 않는 근거는 **RULE-CHAIN-011** 이다.

> "Summoning a monster, Tributing, changing a monster's battle position and
> paying costs **are not effect activations** and therefore you cannot respond
> to those actions using a Chain."

체인은 **효과 발동의 사슬**이므로, 쌓여 있는 동안 발동이 아닌 행위가 끼어들
수 없다. (같은 조항이 "소환 뒤에는 응답 창을 열지 않는다" 의 근거이기도
하다 — `test_h` 가 그 자리도 함께 지킨다.)

### 응답 후보는 **하나도 생기지 않는다** — 그리고 그 사실을 적는다 (§6)

창은 열리지만 `ACTIVATE_EFFECT` 가 응답 후보로 오르지 않는다. 이유가 둘이다.

1. `Duel._activation_actions` 가 **체인이 빈 자리만** 본다
2. 발동 범위가 "자기 메인 페이즈의 패에 있는 통상 마법" 으로 좁혀져 있다
   (Phase 3-E-3 의 범위 결정)

**억지로 승격하지 않았다.** 응답 후보를 만들려면 `ActivationTimingChecker` 를
행동 공간에 이어야 하고, 그것은 이 Phase 의 범위 밖이다 (§7 — "unsupported /
unknown timing은 VALID로 승격하지 않는다"). `test_f` 가 이 한계를 고정하고,
`withheld` 의 `missing` 이 `activation-timing` 이라고 적는 것까지 확인한다.

그리고 **그것이 규칙과도 맞는 경우가 있다**: 상대 패에 욕망의 항아리(통상
마법 · 스펠 스피드 1)가 있어도 응답 후보가 아니어야 한다 —
**RULE-CHAIN-004** "cannot be activated in response to any other effects".
`test_e` 가 그 자리를 지킨다.

---

## 6. 실제 카드 Trace

욕망의 항아리 · `55144522` · `EffectRef(55144522, 0)`

```
[발동 전]  to_act=0  holder=nobody  window=none  chain=0  pending=0
           seat=0 allowed=[ACTIVATE_EFFECT, END_PHASE, SET_SPELL_TRAP]  상대=[]
           덱=20  패=1

① ACTIVATE_EFFECT → accepted=True
   "55144522:e[0] 를 체인 1 로 발동했습니다. 상대의 응답을 기다립니다."
[발동 후]  to_act=1  holder=player_1  window=response  passes=0  chain=1  pending=1
           seat=1 allowed=[PASS]  상대=[]
           덱=20  패=0  SZONE=1      ← 아직 해결 전. 카드는 앞면으로 필드에 있다

② P1 PASS → accepted=True  "우선권을 넘겼습니다."
[P1 패스 후] to_act=0  holder=player_0  window=response  passes=1  chain=1

③ P0 PASS → accepted=True  "체인1 P0 55144522:e[0] 를 해결했습니다."
[해결 후]  to_act=0  holder=nobody  window=none  passes=0  chain=0  pending=0
           seat=0 allowed=[END_PHASE, NORMAL_SUMMON, SET_MONSTER]
           덱=18  패=2  묘지=1
```

**결과 숫자가 한 개도 바뀌지 않았다** — 덱 −2, 패 −1+2, 묘지 +1. 바뀐 것은
걸음 수다.

---

## 7. 실제 Response — **불가능했다. 정확한 이유**

§14 가 요구한 "Spell Speed 2+ 이면서 executable 한 카드" 를 찾았다.
`EFFECT_LIBRARY` 에 **8장**이 있다 (3-E-10 Audit 이 센 그대로) — 함정 5장,
속공 마법 3장. 그러나 **발동 후보가 되지 않는다.**

| 막는 곳 | 내용 |
|---|---|
| `Duel._activation_actions` | 체인이 빈 자리만 본다 |
| `Duel.legal_actions` | `seat == self.turn_player` 인 자리만 발동 후보를 만든다 |
| `_activate_effect` 의 범위 조건 | 패에 있는 통상 마법 외에는 `UNKNOWN` → 후보가 아니다 (Phase 3-E-3) |

> **"Response window 는 정상적으로 열렸으나 실제 response card execution 은
> 현재 corpus 에서 지원 범위 밖이다."**

§14 가 쓰라고 한 문장 그대로다. 억지로 쓰지 않았다.

### Chain Link 2 (§15)

`Chain.push` 와 `ChainResolver.resolve_all` 이 **이미 여러 링크를 다룬다** —
막혀 있는 곳은 체인이 아니라 **행동 공간**이다. 그래서 새 Chain Engine 을
만들지 않았다.

**STRUCTURAL-124 와의 관계를 분리한다.** 124 는 "상대의 응답이 들어갈 자리가
없다" 였고 그 자리는 **이제 있다.** 남은 것은 "그 자리에서 고를 것이 없다" 이고,
그것은 응답 후보 생성(= 타이밍 관문을 행동 공간에 잇는 일)의 문제다. 124 를
RESOLVED 로 바꾸지 않고, **원인이 옮겨 갔다**고만 적는다.

---

## 8. Safety

| 항목 | 결과 | 근거 |
|---|---|---|
| original state unchanged | **PASS** | `test_j` — `state_hash` · `priority` · `chain` · `pending_spells` · `randomness.draws` 다섯이 모두 그대로 |
| clone independence | **PASS** | `pending_spells` 는 `tuple` 이므로 `dataclasses.replace` 가 값으로 가져간다. `priority` · `chain` 은 `frozen` 이고 전이는 **대입**이다 |
| RNG isolation | **PASS** | `test_j` — 사본이 2장 뽑아도 원본의 `draws` 가 그대로 |
| hidden information | **PASS** | `test_k` — 창이 열린 동안에도 상대 패는 `concealed`, `cards == ()`, 장수만 공개. 응답 기회를 주려고 상대 패를 읽지 않는다 |

---

## 9. Search / Simulation 영향

### 깊이 1 의 미래가 **체인 도중**이 되는 문제 — 그리고 해결

처음 구현한 그대로면 `Simulator.simulate(ACTIVATE_EFFECT)` 의 미래가
**발동했지만 해결되지 않은** 위치가 된다. 그 위치는 아무도 고르는 자리가
아니고, 그것을 재면

- 대상이 다른 두 발동이 **같은 점수**를 받는다 (Phase 3-E-4 가 세운 구분이
  사라진다 — 측정으로 확인: `test_23_different_targets_give_different_futures`
  가 깨졌다)
- 욕망의 항아리가 `spells +300 − hand 200 = +100` 으로 읽혀 탐색이 그것을
  고르기 시작한다 (드로우를 보지 않으므로). STRUCTURAL-122 가 말한 "−400" 이
  사라진다

둘 다 **깊이 1 이 짧아서** 생기는 일이고, 평가의 문제가 아니다.

`Simulator._settle_forced_passes` 를 더해 해결했다.

> 후보가 `PASS` **하나뿐**이면 패스는 고르는 일이 아니다 — 드로우가 행위
> 목록에 없는 것과 같은 이유다 (`Duel.advance` 의 설명). 그래서 사본에서 그
> 걸음을 대신 밟는다. **고를 것이 하나라도 있으면 즉시 멈춘다** — 그 자리가
> 진짜 결정 지점이고, 거기까지가 깊이 1 이다.

**깊이를 늘리는 것이 아니다.** 상대의 **선택을 예측하지 않는다.** 선택이
존재하는 순간 멈춘다.

| 단계 | 영향 |
|---|---|
| candidate | **변화 없음** — `legal_actions` 가 이미 걸러낸다 |
| simulation | 강제된 패스를 사본에서 밟는다. 미래는 **해결된 판**이다 |
| future state | 수정 전과 **같은 판** (`test_21` 이 실제와 견준다) |
| evaluation | **변경 0건** |
| ranking | **변경 0건** — `ordering_key` 를 건드리지 않았다 |

전체 테스트에서 search/attack/evaluation 쪽 18건이 이 한 군데 수정으로
되돌아왔다 (29 → 11).

### 그래도 남은 영향 — 숨기지 않고 적는다

실제 대국의 **걸음 수**가 늘었다 (발동 하나가 3 걸음). 그래서 무작위 정책의
궤적이 갈라지고, `test_f_greedy_is_not_the_best_play` 의 무작위 측정값이
19,200 → **9,600** 으로 내려갔다. 규칙 기반의 70,700 과 붕괴 씨앗([10, 15])은
**한 점도 바뀌지 않았다** — 그 시험이 지키는 주장은 거기에 있다.

---

## 10. Evaluation

`agent/evaluation.py` **변경 없음.** `engine/game_state_view.py` **변경 없음.**
우선권·응답 자리가 관측에 노출되지 않으므로 평가는 그것을 **읽을 방법이
없다**. Phase 3-E-5 ~ 3-E-10 이 세운 경계가 그대로다.

> Evaluation 은 State Value 를 평가한다.
> Action availability / response opportunity 는 Action Space / Engine 의 일이다.

점수에 `+400 for priority` 같은 것을 넣지 않았다.

---

## 11. 테스트

```
3424 passed · 0 failed · 4 skipped
```

기준(`ef94d5d`) **3411 passed** → **+13**

### 신규 — `tests/engine/test_activation_response_window.py` (13개)

§19 의 A~K 를 모두 덮는다.

| 테스트 | §19 |
|---|---|
| `test_a_activation_opens_a_response_window` | A |
| `test_b_the_response_seat_is_the_opponent_of_the_activator` | B |
| `test_c_two_passes_resolve_the_chain` | C |
| `test_d_the_state_mutation_is_exactly_what_it_was` | D |
| `test_e_a_spell_speed_1_card_is_not_a_response_candidate` | E |
| `test_f_no_response_candidate_is_generated_yet_and_we_say_why` | F |
| `test_g_chain_link_2_is_not_reachable_yet` | §15 |
| `test_h_the_normal_action_space_is_untouched_without_a_window` | G |
| `test_i_the_chain_link_is_preserved_while_the_window_is_open` | H |
| `test_j_the_simulation_leaves_the_real_duel_alone` | I · J |
| `test_k_the_opponent_learns_nothing_hidden_from_the_window` | K |
| `test_l_a_refused_activation_opens_no_window` | — |
| `test_m_the_simulator_only_settles_what_is_not_a_choice` | §17 |

그리고 `tests/conftest.py` 에 `settle_chain` / `activate_and_settle` 헬퍼를
더했다 — 해결 결과를 보려면 패스 두 번을 거쳐야 하므로, 그 걸음을 한 곳에만
적는다.

### 기존 테스트 수정 — **13개. 삭제 0 · skip 0 · assertion 완화 0**

**(가) 걸음이 늘어난 것을 반영 (7개)** — 주장은 글자 하나 바뀌지 않았고
`settle_chain(duel)` 한 줄이 늘었다.

`test_effect_activation_path.py` `test_12` · `test_16` · `test_21` · `test_23`,
`test_target_bridge.py` `test_07` · `test_12` · `test_13`

`test_21_the_simulation_matches_what_really_happens` 는 특히 중요하다 —
시뮬레이터가 강제된 패스를 밟으므로 **진짜 쪽도 같은 자리까지** 와야 같은
것을 견주는 것이 된다. 한쪽만 밟고 견주면 깨지고, 실제로 깨져서 이 줄이 생겼다.

**(나) 전제가 이 Phase 로 바뀐 것 (6개)** — 각각 왜 바뀌었는지 docstring 에
적었다.

| 테스트 | 기존 전제 | 왜 바뀌었는가 |
|---|---|---|
| `test_effect_action_space_audit::test_18` | "`Duel` 은 `ResponseLoop` 를 모른다" | 규칙이 없었던 것이 아니라 **그 자리의 규칙을 쓰지 않았던** 것이다. RULE-CHAIN-001 이 한 문장으로 요구한다 |
| `test_priority_response_audit::test_02` | "`opened` 를 한 번도 부르지 않는다" | 같은 이유. 지금은 **자리 하나에서만** 부른다 (`count == 1` 로 고정) |
| `test_priority_response_audit::test_03` | "`ResponseLoop` 를 import 하는 production 모듈 0개" | `duel.py` 가 그 끝을 잡는다. **그것 하나뿐**임을 고정 |
| `test_priority_response_audit::test_07` | "체인 링크가 남는 결정 시점이 없다" | 그 시점이 **생겼다.** 창이 닫힌 자리에서는 여전히 비어 있음도 함께 고정 |
| `test_duel_loop::test_e_priority_opens_only_where_a_rule_says_so` | "우선권 창이 한 번도 열리지 않는다" | **모든** 듀얼에 참이던 것이 **발동이 없는 듀얼**에만 참이 되었다. 주장의 범위를 좁혀 적었다 (assertion 은 그대로) |
| `test_rule_based_ai::test_d_pass_now_shows_up_because_a_response_window_opens` | "`PASS` 는 후보에 오르지 않는다" | 창이 열리므로 오른다. 나머지 다섯 종류 주장은 그대로 |

**(다) Phase 3-E-9 가 깨질 것을 미리 적어 둔 것 (2개)**

3-E-9 Audit 이 STRUCTURAL-128 을 CASE B 로 닫으면서 **다시 열리는 조건**을
적어 두었다 — "END 페이즈에 발동이 후보로 오르면(STRUCTURAL-34 가 열리면)
그날 이 시험이 깨진다", "상대 턴에 행동할 수 있게 되면 '현재 차례 = viewer'
가 깨진다." **두 조건이 모두 성립했다.**

| 테스트 | 새 사실 |
|---|---|
| `test_06_the_turn_is_no_longer_constant_within_every_decision` | 차례가 행위자와 다른 미래를 만드는 결정이 **생겼다.** 다만 그런 결정의 후보가 하나뿐이라 아직 순위를 다투지 않는다 |
| `test_07_the_actor_is_no_longer_always_the_turn_player` | `legal.seat != turn_player` 인 결정이 **생겼다.** 1053/1053 이 깨졌다 |

**(라) 측정값 갱신 (1개)** — `test_rule_based_ai::test_f` 의 무작위 측정값
19,200 → 9,600. 규칙 기반 70,700 과 붕괴 씨앗은 그대로.

### 의도적 위반 주입 — 5건 중 **4건 잡힘, 1건은 못 잡았다**

| # | 주입 | 결과 |
|---|---|---|
| 1 | 창을 열지 않고 바로 해결 (옛 동작) | **잡힘** 19개 |
| 2 | 창을 **발동한 쪽**에게 연다 (응답 자리 오류) | **잡힘** 8개 |
| 3 | 한 번의 패스로 해결 (`ready_to_resolve` 무시) | **잡힘** 20개 |
| 4 | 창이 열려 있어도 턴 플레이어가 소환 가능 | **잡힘** 5개 |
| 5 | 시뮬레이터가 **고를 것이 있어도** 대신 패스 | **못 잡았다** ↓ |

위반 5 는 69개 테스트 전부 통과했다. 이유는 분명하다 — 응답 창의 후보가
언제나 `PASS` 하나뿐이므로(`test_f`), 조건의 두 번째 절이 참이 되는 상태가
**아직 없다.** 그래서 지금 잡을 수 있는 방법으로 잡았다:
`test_m_the_simulator_only_settles_what_is_not_a_choice` 가 조건식 자체를
고정한다. 재주입했고 잡혔다.

**응답 후보가 생기기 시작하면 이 자리를 실행으로 다시 재야 한다.** 숨기지
않고 적는다.

---

## 12. STRUCTURAL-34 상태 — **HALF RESOLVED**

> Activation 직후 opponent RESPONSE window 는 **연결되었다.**
> Phase Change Priority(`RULE-CHAIN-009` · `ResponseWindow.PHASE_CHANGE`)와
> AFTER_CHAIN Priority(`AFTER_CHAIN_RULE`)는 **여전히 미구현**이므로
> STRUCTURAL-34 전체 RESOLVED 로 판정하지 않는다.

이은 것과 잇지 않은 것을 코드로 고정했다 (`test_02`).

| | 상태 |
|---|---|
| 발동 직후 RESPONSE 창 | **이었다** (`ResponseLoop.opened(` 가 `duel.py` 에 정확히 1회) |
| 페이즈 전환 우선권 | 미구현 (`PHASE_CHANGE` 가 `duel.py` 에 0회) |
| 체인 해결 뒤 우선권 | 미구현 (`give_to` 가 `duel.py` 에 0회) |
| 응답 후보 생성 | 미구현 — 타이밍 관문이 행동 공간에 연결되지 않았다 |

---

## 13. 기존 TODO 상태

| ID | 상태 | 비고 |
|---|---|---|
| **STRUCTURAL-34** | **HALF RESOLVED** | 위 표 |
| **STRUCTURAL-124** | **유지** | "응답할 자리가 없다" 는 해소되었으나 "그 자리에서 고를 것이 없다" 가 남았다. **원인이 옮겨 갔다**고만 적고 RESOLVED 로 바꾸지 않는다 |
| **STRUCTURAL-128** | **유지 — 다시 열렸다** | 3-E-9 이 적어 둔 두 조건이 성립했다. `viewer != turn_player` 인 결정이 생겼고, 차례가 상수가 아닌 결정이 생겼다. 다만 그런 결정의 후보가 하나뿐이라 아직 순위를 다투지 않는다 |
| `AFTER_CHAIN_RULE` | **유지** | 건드리지 않았다 |
| `UNRESOLVED_PROGRESSION_RULES` | **유지** | "우선권을 쥔 쪽이 페이즈 종료를 선언했는가" · "전이 직후 우선권이 누구에게 열리는가" 그대로 |
| STRUCTURAL-102 · 107 · 109 · 110 · 116 · 118 · 120 · 122 · 123 · 125 · 126 · 127 · 129 · 130 · 131 · 132 · 133 | **전부 유지** | 손대지 않았다 |

### 신규 TODO — 없음

이 Phase 가 드러낸 것들은 모두 기존 TODO 의 범위 안이다. 특히 "깊이 1 이
체인 도중을 재는 문제" 는 새 문제로 등록하지 않았다 —
`Simulator._settle_forced_passes` 가 그 자리를 막았고, 막은 조건을 `test_m` 이
고정한다.

---

## 14. Engine Change Required — **NO**

§22 의 일곱 중단 조건 중 하나도 발생하지 않았다.

| 조건 | 결과 |
|---|---|
| response seat 를 표현할 수 없음 | `PriorityHolder` + `ResponseWindow.RESPONSE` 로 충분 |
| `legal_actions` 가 response seat 를 받을 구조가 없음 | `to_act` 가 이미 "홀더 → 턴 플레이어" 였다. **한 글자도 고치지 않았다** |
| `ResponseLoop` API 가 실제 execution 과 비호환 | `opened` · `ready_to_resolve` · `resolve` 가 그대로 맞았다 |
| Chain 이 창을 삽입할 수 없는 구조 | `ResponseState(chain, priority)` 가 둘을 함께 든다 |
| resolution 이 activation 과 분리 불가 | `ChainResolver.resolve_all` 이 이미 따로 있었다 |
| PASS 가 새 `PlayerAction` 을 요구 | **이미 있었다** (`PlayerAction.passing`) |
| hidden information 없이 response legality 판단 불가 | 응답 후보를 만들지 않았으므로 해당 없음 |

---

## 15. 다음 Phase 후보 — 하나만

**응답 후보 생성: `ActivationTimingChecker` 를 행동 공간에 잇는다.**

이번 구현이 직접 가리킨다. 창은 열렸는데 **그 자리에서 고를 것이 없다**
(`test_f`). 그래서 지금 창은 "기회가 있다" 를 말하지만 "무엇을 할 수 있다" 는
말하지 못한다.

근거:

1. **이번 Phase 가 막아 둔 자리가 정확히 하나다** — `Duel._activation_actions`
   가 체인이 빈 자리만 본다. 그 조건을 `ActivationTimingChecker` 로 바꾸는
   일이고, 그 checker 는 **공식 룰북에서 뽑은 `RESPONSE_TABLE` 을 이미 들고
   있다** (RULE-CHAIN-003/004/005/006)
2. **새 구조가 필요 없다** — `ResponseLoop.act` 가 이미 타이밍 판정 →
   발동 → 링크 추가를 한다. 지금은 부르는 곳이 없을 뿐이다
3. **열리면 네 개가 동시에 측정 가능해진다** — STRUCTURAL-124(체인 링크 2),
   128(차례가 순위를 바꾸는가), 123(두 정책의 차이), 그리고 위반 5 를 실행으로
   잡는 자리
4. **가중치를 만들지 않는다** — 발동 가능성은 룰 문제다

하지 **않을** 것: 페이즈 전환 우선권 · 체인 해결 뒤 우선권 · Trigger ·
Damage Step · Depth-2 · 전체 카드 풀.

그리고 **RULE-CHAIN-011 이 정한 자리는 계속 열지 않는다** — 소환 · 릴리스 ·
표시 형식 변경 · 비용 지불에는 응답할 수 없다 (`test_h` 와
`test_09_a_summon_correctly_opens_no_window` 가 지킨다).
