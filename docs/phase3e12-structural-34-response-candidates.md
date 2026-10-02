# Phase 3-E-12 — STRUCTURAL-34 응답 후보 생성 · ActivationTimingChecker → Action Space

Base: `497d76c` (Phase 3-E-11 · 창을 열었고 후보는 `PASS` 하나뿐이었다)

---

## 0. 한 줄

```
전:  RESPONSE 창  →  PASS
후:  RESPONSE 창  →  PASS  +  ACTIVATE_EFFECT (세 관문을 통과한 것만)
```

`ActivationTimingChecker` 가 **행동 공간의 세 번째 관문**이 되었다. 그리고
체인 링크 2 가 실제로 쌓이고 역순으로 해결된다.

**새 구조 0개** — 새 ActionKind · 새 Priority/Response/Chain Engine · EventBus
전부 없음. `agent/` 변경 **0건**.

---

## 1. 변경 파일 (2개, engine 만)

| 파일 | 변경 | 근거 |
|---|---|---|
| `engine/duel.py` | ① `ActivationTiming`/`ActivationTimingChecker` import ② `legal_actions` 에 응답 분기 ③ `_activation_actions` 의 체인 차단을 **타이밍 관문**으로 교체 | 관문을 행동 공간에 잇는다 |
| `engine/action_validation.py` | ① `_OUT_OF_SCOPE_TYPES` 에서 `QUICKPLAY` 제거 ② `activation_is_quick_play` ③ `SET_ACTIVATION_MISSING` ④ `_activate_effect` 가 속공 마법에는 `PhaseIs(MAIN_PHASES)` 를 걸지 않는다 | RULE-SPELLTRAP-007 |

`agent/evaluation.py` · `agent/search.py` · `agent/policy.py` ·
`agent/heuristic.py` · `agent/simulation.py` · `engine/game_state_view.py` —
**전부 0건.**

---

## 2. Repository Audit (§4)

| 구조 | 위치 | API |
|---|---|---|
| `ActivationTimingChecker` | `engine/activation_timing.py:291` | `check(ActivationTiming(chain, priority), action) → ValidationResult` · `spell_speed(instance) → SpellSpeedClassification` |
| `RESPONSE_TABLE` | `:94` | 공식 룰북 `chain.spell_speeds[*].can_respond_to` 에서 추출 (RULE-CHAIN-003/004/005/006) |
| Spell Speed 판정 | `classify_spell_speed()` `:188` | 카드 **종류만** 본다. TRAP→FAST · TRAP/COUNTER→COUNTER · SPELL/QUICKPLAY→FAST · SPELL→NORMAL · MONSTER→**`None`**(분류가 없다) |
| 뒷면 · 안 보임 | `FACE_DOWN` · `NOT_VISIBLE` | `is_known == False` → `check` 가 **UNKNOWN**. 가려진 정보를 읽지 않는 것이 구조에 들어 있다 |
| `ResponseLoop` | `engine/response.py` | 3-E-11 에서 이미 연결 |
| `legal_actions` | `engine/duel.py:284` | `seat = self.to_act` → 창이 열리면 홀더 |
| response seat | `PriorityState.holder` | 이미 있었다 |

**체크 결과가 세 가지**인 것이 핵심이다 — `VALID` / `INVALID(SPELL_SPEED_TOO_LOW)` /
`UNKNOWN`. 그리고 체인이 비어 있으면 `VALID("체인이 비어 있어 스펠 스피드 제약이
걸리지 않습니다")` 로 통과시킨다 → **기존 메인 페이즈 발동이 한 건도 변하지
않는다.**

---

## 3. Before / After

### Before (3-E-11)

```
P0 ACTIVATE_EFFECT → Chain 1 → RESPONSE(P1)
  P1: [PASS]
  P0: []
```

### After

```
P0 ACTIVATE_EFFECT → Chain 1 → RESPONSE(P1)
  P1: [PASS]                      ← 패에서는 상대 턴에 발동할 수 없다 (규칙)
  P0: []                          ← 창을 쥐지 않았다
P1 PASS → RESPONSE(P0)
  P0: [PASS, ACTIVATE_EFFECT:22589918]   ← **새로 생긴 것**
  P1: []
P0 ACTIVATE_EFFECT → Chain 2 → RESPONSE(P1)
P1 PASS → P0 PASS → resolve_all (역순)
```

---

## 4. 이번 Phase 가 넓힌 범위 — **한 문장**

`RULE-SPELLTRAP-007` 이 속공 마법을 **두 문장**으로 적는다.

> "These are special Spell Cards that can be activated during **any Phase of
> your turn**, not just your Main Phase. You can **also** activate them during
> your opponent's turn **if you Set the card face-down first**, but then you
> cannot activate the card in the same turn you Set it."

| 문장 | 요구 | 이번 Phase |
|---|---|---|
| 첫째 — "any Phase of **your turn**" | 세트를 **요구하지 않는다** | **범위 안으로 넣었다** |
| 둘째 — 상대 턴 | **세트** + "세트한 턴에는 못 쓴다" | **`UNKNOWN` 으로 남겼다** |

둘째를 넣지 않은 이유가 중요하다. `engine/activation_timing.py` 의
`UNRESOLVED_TIMING_RULES` 가 **"세트한 턴의 함정 발동 제약"** 을 보지 않는다고
적어 두었고, 실제로 세트한 턴을 세는 자리가 엔진에 없다. 세지 못하는 제약을
통과시키면 "세트한 턴에 발동할 수 있다" 는 거짓이 된다. 그래서 세트된 속공
마법의 발동은 `SET_ACTIVATION_MISSING` 을 들고 **`UNKNOWN`** 이다 —
`INVALID` 도 아니다.

### 세 관문 (`Duel._activation_actions`)

| # | 관문 | 무엇을 보는가 |
|---|---|---|
| 1 | `ActionValidator` | 자기 카드 · 자기 턴 · 페이즈 · 빈 칸 · 이번 Phase 가 판정할 수 있는 발동인가 |
| 2 | **`ActivationTimingChecker`** (신규) | 스펠 스피드 — RULE-CHAIN-003/004 |
| 3 | `EffectActivator.can_activate` | 구현 등록 · 발동 조건 · 대상 |

**셋 다 `VALID` 여야 후보가 된다.** `UNKNOWN` 은 통과가 아니다.

---

## 5. Response Candidate (§5)

| | |
|---|---|
| 실제 candidate | **리로드** (`22589918`) — 속공 마법, 대상 없음, `executable=True`, 비용 0 |
| actor | **창을 쥔 자리** (`priority.holder.seat`) |
| EffectRef | `EffectRef(22589918, 0)` |
| 어디서 | 패 (`Zone.HAND`) |
| 체인 번호 | **2** |

### 왜 `P1` 이 아니라 `P0` 인가 — 규칙이 그렇다

`RULE-CHAIN-001` 이 적는다.

> "If your opponent does not respond, **you may activate a second effect** and
> create a Chain to your own card's activation."

상대가 패스하면 **발동한 쪽**이 응답 자리가 된다. 그래서 첫 응답 자리(P1)는
패에서 발동할 수 없고(규칙), 두 번째 응답 자리(P0)에서 후보가 생긴다.

**P1 이 응답할 수 없는 것은 누락이 아니라 규칙이다.** 패에 있는 속공 마법은
상대 턴에 쓸 수 없고, 그 판정은 `UNKNOWN` 이 아니라 **`INVALID`
(`NOT_TURN_PLAYER`)** 다 — RULE-SPELLTRAP-007 이 상대 턴의 발동에 세트를
요구하기 때문이다 (`test_03`).

---

## 6. Timing Gate

| | |
|---|---|
| 사용한 checker | `engine/activation_timing.ActivationTimingChecker.check` (**기존 그대로**) |
| 문맥 | `ActivationTiming(self.chain, self.priority)` (**기존 그대로**) |
| 리로드의 Spell Speed | `SpellSpeed.FAST` (카드 종류: SPELL / QUICKPLAY) |
| 응수할 링크 (욕망의 항아리) | `SpellSpeed.NORMAL` (카드 종류: SPELL) |
| 결과 | **VALID** — "fast 로 normal 에 응수할 수 있습니다" |
| 두 번째 욕망의 항아리 | **INVALID** `SPELL_SPEED_TOO_LOW` — "스펠 스피드 1 은 어떤 효과에도 응수할 수 없습니다" (RULE-CHAIN-004) |
| 뒷면 카드 | **UNKNOWN** — 정체를 모르므로 판정할 수 없다. 후보가 되지 않는다 |

새 Spell Speed 규칙을 하나도 쓰지 않았다 (§8).

---

## 7. 실제 Trace

패: P0 = 욕망의 항아리 · 리로드 · 사파이어 드래곤

```
[시작]    holder=nobody   window=none      chain=0  덱=20 패=3 SZONE=0 묘지=0
① P0 ACTIVATE_EFFECT 55144522:e[0]
          "체인 1 로 발동했습니다. 상대의 응답을 기다립니다."
          holder=player_1 window=response  chain=1  덱=20 패=2 SZONE=1 묘지=0
          P1=[PASS]   P0=[]
② P1 PASS
          holder=player_0 window=response  chain=1  passes=1
          P0=[PASS, ACTIVATE_EFFECT:22589918]   ← 응답 후보
③ P0 ACTIVATE_EFFECT 22589918:e[0]
          "체인 2 로 발동했습니다. 상대의 응답을 기다립니다."
          holder=player_1 window=response  chain=2  pending=2  덱=20 패=1 SZONE=2
          체인 링크: [(1, P0, 55144522:e[0]), (2, P0, 22589918:e[0])]
④ P1 PASS                               passes=1
⑤ P0 PASS "체인1 P0 55144522:e[0] 를 해결했습니다."
          holder=nobody   window=none      chain=0  pending=0
          덱=18 패=3 SZONE=0 묘지=2
```

**역순 해결이 숫자로 보인다** (`RULE-CHAIN-007`): 링크 2(리로드)가 먼저 풀려
패 1장을 덱에 넣고 1장 뽑고(덱 20 · 패 1), 그 다음 링크 1(욕망의 항아리)이
2장 뽑는다(덱 18 · 패 3). 두 장 모두 묘지로 갔다 (RULE-SPELLTRAP-002).

기존 `ChainResolver.resolve_all` 을 그대로 썼다 — 새 Chain Engine 0개.

---

## 8. Turn / Priority / Response Seat (§12 · §13)

```
turn_player     = P0        ← **한 번도 바뀌지 않는다**
priority holder = P1 → P0 → P1 → nobody
response seat   = priority holder
viewer          = legal_actions(seat) 가 받는 자리
```

`turn_player` 는 `TurnState` 의 값이고 응답 창은 **우선권의 문맥**이다. 후보를
만들려고 턴을 바꾸지 않았다 (`test_08` — `turn_number` 까지 그대로).

**후보를 받는 자리는 정확히 하나다** (`test_12`):

| 창 | 턴 플레이어 | 상대 |
|---|---|---|
| 닫힘 | 받는다 | **0개** |
| 열림 · 상대가 쥠 | **0개** | 0개 (규칙상 패에서 못 쓴다) |
| 열림 · 턴 플레이어가 쥠 | 받는다 | 0개 |

---

## 9. Hidden Information — **leak NO**

| 검증 | 결과 |
|---|---|
| 상대 패의 내용이 내 후보 목록을 바꾸는가 | **아니다** — 상대 패를 네 가지로 바꿔도 내 후보의 `canonical_state` 집합이 동일 (`test_09`) |
| 관측 | `view.opponent.hand.concealed`, `cards == ()` 그대로 |
| 뒷면 카드의 스펠 스피드 | `FACE_DOWN` → `is_known == False` → `UNKNOWN` → 후보 아님. **구조가 막는다** |
| `GameStateView` | 변경 0건 |

후보 생성은 `self.state.player(seat).hand` 를 읽는다 — **자기 자리의 패**이고,
그 자리의 `GameStateView` 로 만든 validator 가 판정한다. agent 로 나가는 것은
관측뿐이다.

---

## 10. Evaluation — 변경 없음

`agent/evaluation.py` **0건** · `engine/game_state_view.py` **0건**.
`+priority` · `+response seat` · `+number of legal responses` 같은 항을
하나도 넣지 않았다. 점수 함수는 글자 하나 바뀌지 않았다.

---

## 11. Search 영향

전체 테스트에서 `agent/` 쪽 실패 **0건**. 변경 파일에 `agent/` 가 없고,
`ordering_key` 를 건드리지 않았다.

| 항목 | 결과 |
|---|---|
| candidate count | 창이 닫힌 결정에서 **동일** (타이밍 관문이 빈 체인을 통과시킨다) |
| simulation | 동일 — `_settle_forced_passes` 가 그대로 작동 |
| future state | 동일 |
| ranking | **변경 없음** |
| RNG | 변경 없음 |

**응답 창에서 탐색이 새 후보를 본다.** 창을 쥔 자리의 `legal_actions` 에
`ACTIVATE_EFFECT` 가 들어오므로 `Simulator._settle_forced_passes` 는 "고를 것이
있으므로" **멈춘다** — 그 자리가 진짜 결정 지점이고, 3-E-11 이 그렇게 설계해
두었다. 즉 3-E-11 의 `test_m` 이 지키던 조건의 두 번째 절이 **이제 실행으로
재어진다.**

---

## 12. 테스트

```
3438 passed · 0 failed · 4 skipped
```

기준(`497d76c`) **3424 passed** → **+14** (신규 13 + `test_05b` 분할로 +1)

### 신규 — `tests/engine/test_response_candidates.py` (13개)

§21 의 여덟 항목을 모두 덮는다.

| 테스트 | §21 |
|---|---|
| `test_01_the_response_window_still_has_pass` | 1 |
| `test_02_the_response_candidate_actor_is_the_window_holder` | 2 · 3 |
| `test_03_the_opponent_cannot_respond_from_hand_and_that_is_the_rule` | — (규칙 근거) |
| `test_04_a_trap_in_hand_stays_unknown_not_a_candidate` | 6 |
| `test_05_the_normal_window_candidates_are_unchanged` | 4 |
| `test_06_spell_speed_one_is_not_a_response_candidate` | 5 |
| `test_07_an_unknown_timing_is_not_promoted_to_a_candidate` | 6 |
| `test_08_the_turn_player_never_changes` | 7 |
| `test_09_candidate_generation_leaks_nothing_hidden` | 8 |
| `test_10_a_second_link_is_added_and_resolves_in_reverse` | §17 |
| `test_11_…condition_reads_its_own_zone` | **STRUCTURAL-134** |
| `test_12_only_the_window_holder_ever_gets_activation_candidates` | §12 |
| `test_13_the_timing_gate_refuses_anything_that_is_not_valid` | §7 |

### 기존 테스트 수정 — 1개 분할. 삭제 0 · skip 0 · 완화 0

`test_effect_action_space_audit.py::test_05b_everything_outside_the_scope_stays_unknown`
의 parametrize 에서 **속공 마법(싸이크론)을 뺐다.** 함정 케이스는 그대로다.

**왜 기존 전제가 바뀌었는가:** 3-E-3 에서 속공 마법이 `UNKNOWN` 이었던 것은
"그 타이밍을 볼 계층이 없다" 였고 그때는 사실이었다. 이제 **있다** —
`RULE-SPELLTRAP-007` 의 첫 문장이 세트를 요구하지 않으므로 패에 있는 속공
마법은 판정할 수 있다. 두 번째 문장(세트 · 세트한 턴)은 여전히 `UNKNOWN` 이다.

빠진 자리를 두 시험으로 **나눠 적었다** — 주장을 약하게 하지 않았다.

- `test_05b2_a_quick_play_spell_in_hand_is_now_in_scope` — 네 페이즈(MAIN1 ·
  BATTLE · MAIN2 · END) 전부에서 `VALID` ("not just your Main Phase")
- `test_05b3_a_set_quick_play_spell_is_still_unknown` — 세트되면
  `set-card-activation-timing` 을 들고 `UNKNOWN`

### 의도적 위반 주입 — 6건 중 **4건 잡힘**

| # | 주입 | 결과 |
|---|---|---|
| 1 | response seat 대신 `turn_player` 로 후보 생성 | **잡힘** (`test_12`) |
| 2 | 타이밍 관문을 건너뛴다 | **잡힘** (`test_06`) |
| 3 | `UNKNOWN` 을 통과시킨다 | **잡힘** (`test_13`) |
| 4 | 분기에서 창 조건을 없앤다 | **못 잡았다** ↓ |
| 5 | 세트된 속공 마법을 범위 안으로 | **잡힘** (`test_05b3`) |
| 6 | 패의 속공 마법에 상대 턴 발동 허용 | **잡힘** (`test_03` · `test_09`) |

**위반 1 과 3 은 처음에 잡히지 않았다.** 비어 있던 주장이 하나였다 —
"창을 쥐지 않은 자리는 후보를 받지 못한다" 를 **상대 패에 발동할 수 있는
카드가 있는 상태에서** 확인하는 시험이 없었다. 패가 비어 있으면 어떤 잘못된
조건도 후보 0개를 내므로 아무것도 증명하지 못한다. `test_12` 를 더해 잡았고,
`test_13` 으로 관문의 비교를 고정했다.

**위반 4 는 지금도 잡히지 않는다 — 그리고 그것은 구멍이 아니다.** 분기 조건을
약하게 해 상대가 `_activation_actions` 에 들어가게 만들어도 후보는 0개다.
안쪽에서 `ActionValidator` 의 `IsTurnPlayer` 가 **독립적으로** 같은 것을 막기
때문이다. 두 관문이 같은 것을 막고 있으므로 하나를 약하게 해도 결과가 보이지
않는다. 숨기지 않고 적는다.

---

## 13. 이번 Phase 가 드러낸 새 문제 — **STRUCTURAL-134**

> `legal_actions` 가 허가한 발동을 `apply` 가 거절하는 자리가 있다.

`_activation_actions` 는 `can_activate` 를 **배치 전**에 묻고,
`_apply_activation` 은 `RULE-SPELLTRAP-002` 대로 **배치 뒤**에 발동한다
("announce its activation …, placing it face-up on the ﬁeld"). 그 사이에 발동한
카드가 패를 떠나므로 **자기 패를 읽는 조건**은 답이 뒤집힌다.

리로드가 그 첫 카드다 — 조건이 "자신 HAND 에 1장 이상" 이고, 패에 리로드
하나만 있으면 배치 뒤에 패가 비어 거짓이 된다.

| | |
|---|---|
| 재현 | `test_11` — 패에 리로드 하나뿐일 때 후보가 되지만 `apply` 가 거절 |
| 판은 | **되돌아간다** — 놓았던 카드가 패로 돌아오고 체인 · 창 · 대기 목록이 전부 비어 있다 |
| 이 Phase 가 만든 문제인가 | **아니다.** 순서는 3-E-3 이 공식 조항에 맞춰 정했고, 이 Phase 가 **자기 패를 읽는 첫 카드를 후보로 만들면서** 드러났다 |
| 왜 이번에 고치지 않는가 | 고치려면 ① `legal_actions` 가 판을 바꿔 봐야 하거나(읽기 전용이어야 한다) ② 조항이 정한 순서를 뒤집어야 한다. 둘 다 이번 범위 밖이고 위험하다 |

🟠 STRUCTURAL-134 로 등록한다. 기존 TODO 와 중복되지 않음을 확인했다
(134 번호는 비어 있었고, "can_activate 와 activate 가 다른 판을 본다" 를 적은
기존 항목이 없다).

---

## 14. STRUCTURAL-34 상태 — **여전히 HALF RESOLVED**

이번 Phase 에서 해결된 정확한 범위:

> Activation 직후 RESPONSE window 에서 기존 `ActivationTimingChecker` 를
> 이용하여 **실제 response candidate 를 생성할 수 있게 되었고**, 체인 링크 2 가
> 쌓이고 역순으로 해결된다.

**전체 RESOLVED 가 아니다.**

| 자리 | 상태 | 고정 |
|---|---|---|
| 발동 직후 RESPONSE 창 | **연결됨** (3-E-11) | `ResponseLoop.opened(` 1회 |
| 응답 후보 생성 | **연결됨** (이번 Phase) | 세 관문 |
| **Phase Change Priority** (RULE-CHAIN-009) | **미구현** | `PHASE_CHANGE` 가 `duel.py` 에 0회 |
| **AFTER_CHAIN Priority** | **미구현** | `give_to` 가 `duel.py` 에 0회 |
| 상대 턴의 응답 (세트 카드) | **미구현** | `SET_ACTIVATION_MISSING` 으로 `UNKNOWN` |

---

## 15. 기존 TODO

| ID | 상태 | 비고 |
|---|---|---|
| **STRUCTURAL-34** | **HALF RESOLVED** (유지) | 위 표 |
| **STRUCTURAL-124** | **유지** | 체인 링크 2 가 실제로 쌓이게 되었으나, 이번 Phase 는 124 를 재판정하지 않는다 (§17) — 범위를 넓히지 않았다 |
| **STRUCTURAL-128** | **유지** | 손대지 않았다 |
| **STRUCTURAL-134** | **신규 🟠** | §13 |
| `AFTER_CHAIN_RULE` · `UNRESOLVED_PROGRESSION_RULES` | **유지** | |
| 102 · 107 · 109 · 110 · 116 · 118 · 120 · 122 · 123 · 125 · 126 · 127 · 129 · 130 · 131 · 132 · 133 | **전부 유지** | |

---

## 16. 다음 Phase 후보 — 하나만

**STRUCTURAL-134 — `can_activate` 와 `activate` 가 같은 판을 보게 한다.**

이번 Phase 가 직접 드러냈고, **지금 엔진에서 유일하게 "허가한 것을 거절하는"
자리**다. 그 불일치가 남아 있는 동안에는 응답 후보를 더 넓힐 수 없다 — 넓힐
때마다 자기 자리를 읽는 조건이 더 많이 걸린다.

근거:

1. **재현이 한 줄이다** — 패에 리로드 하나. `test_11` 이 고정하고 있다
2. **범위가 좁다** — 조건을 어느 판에서 보는가 하나다. 새 구조가 필요 없다
3. **룰 근거가 이미 있다** — `RULE-SPELLTRAP-002` 가 "놓고 나서 발동이
   성립한다" 를 적는다. 그 순서를 바꾸는 것이 아니라 **후보 생성이 같은 순서를
   보게** 하는 일이다
4. **가중치를 만들지 않는다**

하지 **않을** 것: 페이즈 전환 우선권 · 체인 해결 뒤 우선권 · 세트 카드 발동
(세트한 턴 추적) · Trigger · Damage Step · Depth-2 · 전체 카드 풀.
