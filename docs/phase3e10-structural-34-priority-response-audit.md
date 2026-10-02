# Phase 3-E-10 — STRUCTURAL-34 Priority / Response Seat Audit

Base: `5d1e787` (Phase 3-E-9)
범위: STRUCTURAL-34 하나. **AUDIT ONLY.**
변경: `engine/` **0건** · `agent/` **0건**. 새 테스트 1파일과 이 문서뿐이다.
작업 트리: Audit 시작 시 `git status` · `git diff` 모두 **비어 있었다**.

---

## 0. 한 줄 결론 — **STRUCTURAL ISSUE (판정 C)**

> **우선권을 여는 자리가 아무 데도 없다.**

어휘는 모자라지 않다. `PriorityHolder` · `ResponseWindow`(NONE · ACTION ·
RESPONSE · PHASE_CHANGE) · `PriorityState` 의 여섯 전이 · `ResponseLoop` ·
공식 룰북에서 뽑은 `SpellSpeed` 와 `RESPONSE_TABLE` · `ActivationTimingChecker`
가 **전부 구현되어 있고 단위 시험도 있다.**

끊긴 것은 **하나**다. `Duel` 이 `PriorityState.opened(...)` 를 **한 번도
부르지 않는다.** 그래서

- `priority` 는 평생 `holder=NOBODY · window=NONE` 이다
- `Duel.to_act` 는 언제나 턴 플레이어로 떨어진다
- 상대 자리는 **어떤 순간에도** 후보를 하나도 받지 못한다
- `ResponseLoop` 는 **production 에서 import 하는 모듈이 0개**다

**BLOCKER 는 아니다.** 빠진 자리를 허가로 바꾸지 않고 `withheld` 에 이유를
적는다 — 틀린 Action 이 하나도 생성되지 않는다 (§6).

---

## 1. Repository Audit (§2) — "있다" 와 "쓰인다" 를 가른다

| 구조 | 위치 | 존재 | 상태 보관 | Action Space 연결 | 실행 연결 |
|---|---|---|---|---|---|
| `PriorityState` | `engine/priority.py:154` | ✔ | ✔ `Duel.priority` | **부분** — `is_open` 분기가 있지만 늘 거짓 | **부분** — `idle`·`passed`·`closed` 셋만 |
| `PriorityHolder` / `ResponseWindow` | `engine/priority.py:68` · `:127` | ✔ | ✔ | — | `NOBODY` · `NONE` 만 쓰인다 |
| `PriorityResolver` (`may_act` · `may_respond`) | `engine/priority.py:389` | ✔ | — | ✘ | ✘ `Duel` 이 쓰지 않는다 |
| `ResponseLoop` | `engine/response.py` | ✔ | — | ✘ | ✘ **import 하는 production 모듈 0개** |
| `ActivationTimingChecker` · `SpellSpeed` · `RESPONSE_TABLE` | `engine/activation_timing.py` | ✔ | — | ✘ | ✘ `response.py` 만 쓰고, 그 `response.py` 를 쓰는 곳이 없다 |
| `Chain` / `ChainLink` | `engine/chain.py` | ✔ | ✔ `Duel.chain` | ✔ | ✔ 단 **한 `apply` 안에서** 생성·해결·소멸 |
| `EffectActivator.advance_priority` | `engine/activation.py:470` | ✔ | — | ✘ | ✘ **호출자는 테스트 하나뿐** |
| `legal_actions` | `engine/duel.py:284` | ✔ | — | ✔ | ✔ 우선권을 **읽는다**(늘 닫힘) |
| `END_PHASE` | `engine/duel.py:561` | ✔ | ✔ | ✔ | ✔ 단 우선권을 **`idle()` 로 되돌린다** |
| `ACTIVATE_EFFECT` | `engine/duel.py:597` | ✔ | ✔ | ✔ | ✔ (Phase 3-E-3) |
| `ACTIVATE_CARD` | `engine/action_validation.py` | ✔ | — | ✘ `withheld` | ✘ `missing=activation-timing` |

`duel.py` 가 `priority` 를 만지는 자리는 **정확히 다섯 줄**이다.

```
245  priority=PriorityState.idle(...)        Duel.start
266  seat = self.priority.holder.seat        to_act — 늘 None → turn_player
470  if self.priority.is_open and ...        PASS 허가 — 늘 거짓 (죽은 분기)
481  if ... and not self.priority.is_open    END_PHASE 허가 — 늘 참
556  self.priority = self.priority.passed()  _apply_pass — 도달 불가
570  self.priority = PriorityState.idle(...) _apply_end_phase
```

`opened` · `give_to` · `acted` 는 **한 번도 나오지 않는다.**

---

## 2. Turn Player vs Priority / Response Seat (§4)

**절대 동일시하지 않았다.** 넷은 서로 다른 것이고, 지금 우연히 겹친다.

| 개념 | 현재 의미 | 코드 위치 | 실제 동작 |
|---|---|---|---|
| `turn_player` | 이번 턴의 플레이어 | `engine/state/turn.py` — `TurnState.turn_player` | `END_PHASE` 로만 바뀐다. `canonical_state` 에 **포함**된다 |
| priority holder | 지금 결정권을 쥔 자리 | `engine/priority.py` — `PriorityState.holder` | **언제나 `NOBODY`** — 여는 자리가 없다 |
| response seat | 방금 일어난 일에 응답할 자리 | `ResponseWindow.RESPONSE` + `PriorityState.holder` | **한 번도 만들어지지 않는다** |
| chain owner | 체인 링크를 만든 자리 | `engine/chain.py` — `ChainLink.player` | ✔ 정상 기록. 단 링크가 `apply` 밖으로 나오지 않는다 |
| `viewer` | 관측 주체 | `engine/game_state_view.py` — `GameStateView.viewer` | 평가/탐색의 관점. 우선권과 **무관** |
| legal seat | 후보를 생성할 자리 | `engine/duel.py:291` — `seat = self.to_act` | `to_act` = 홀더 ?? 턴 플레이어 → **늘 턴 플레이어** |

즉 `turn_player == to_act == legal seat` 가 **지금은 언제나 참**이지만, 그것은
설계가 아니라 **우선권이 닫혀 있기 때문에 생기는 우연**이다. Phase 3-E-9 의
실측(결정 1053회 중 1053회 `legal.seat == turn_player`)이 바로 이 사실이었고,
이번 Audit 이 **왜** 그런지를 밝힌다.

---

## 3. 공식 규칙 근거 (§3)

repository 의 `data/rules/documents/sd-rulebook-en-v10.json` 에서 그대로 읽었다.
새 해석을 만들지 않았다.

### A · B — 턴 플레이어의 우선권과 상대의 응답 기회

**RULE-CHAIN-009 (TURN PLAYER'S PRIORITY)**

> "The turn player **always starts with Priority**, or the choice to activate a
> card first, in each phase or step of their turn. As long as the turn player
> has Priority, the opponent cannot activate cards or effects, except for
> effects that activate automatically, like Trigger or Flip effects.
> The turn player can either: • Use Priority to play a card or activate an
> effect **OR** • **Pass Priority to the opponent** so they can activate an
> effect."

| | |
|---|---|
| 규칙 근거 | 턴 플레이어가 먼저 쥐고, **넘길 수 있다** |
| repository 구현 | `ResponseWindow.ACTION` 과 `give_to()` 가 이 자리를 위해 있다 |
| 실제 실행 | **둘 다 쓰이지 않는다.** 턴 플레이어가 "넘긴다" 를 고를 방법이 없다 |

### C — 체인 링크를 추가할 수 있는 플레이어

**RULE-CHAIN-001 (WHAT IS A CHAIN?)**

> "If a card's effect is activated, the opponent is **always** given a chance to
> respond with a card effect of their own, creating a Chain. If your opponent
> responds with an effect, then you can choose to respond and add another
> effect to the Chain. If your opponent does not respond, **you may activate a
> second effect** and create a Chain to your own card's activation."

| | |
|---|---|
| 규칙 근거 | 발동마다 상대에게 **반드시** 기회가 간다. 상대가 응답하지 않으면 **같은 플레이어가 연속으로** 추가할 수 있다 (§9-3 의 답) |
| repository 구현 | `ResponseLoop.opened(...)` + `ResponseWindow.RESPONSE` + `PriorityState.give_to` |
| 실제 실행 | **열리지 않는다.** `_apply_activation` 이 한 `apply` 안에서 해결까지 끝낸다 |

### D — 둘 다 더 추가하지 않을 때

> "Both players continue to add effects to the Chain until **they both wish to
> add nothing else**, then you resolve the outcome in reverse order."

| | |
|---|---|
| 규칙 근거 | **양쪽 모두** 패스하면 해결이 시작된다 |
| repository 구현 | `PriorityState.consecutive_passes` + `both_passed()` + `ResponseLoop` 가 `passed()` 를 돈다 |
| 실제 실행 | `duel.py:557` 에 `both_passed()` 분기가 **있지만** `PASS` 가 후보가 되지 않으므로 `_apply_pass` 자체가 도달 불가 |

### E — 체인 해결 뒤의 우선권

`engine/response.py:377` 에 `AFTER_CHAIN_RULE = "체인 해결 뒤 우선권 규칙
(STRUCTURAL-34)"` 이라고 **적혀 있다.** 즉 구현자가 "이 규칙을 아직 정하지
않았다" 를 명시했다. 룰북은 이 자리를 한 문장으로 못 박지 않으므로
**UNKNOWN 으로 남긴다** — 추측하지 않는다.

### F — 페이즈 종료 시 우선권

**RULE-CHAIN-009 이어지는 문장**

> "A player **must pass Priority to the opponent when moving on to the next
> phase or step.** Strictly speaking, you would always declare that you're
> passing Priority before the end of every phase and step, and ask your
> opponent if they wish to play a card. However, for ease of play, **announcing
> the end of your phases or steps implies giving up Priority.**"

| | |
|---|---|
| 규칙 근거 | 페이즈를 넘길 때 **상대에게 기회가 생긴다.** 종료 선언이 곧 우선권 양도다 |
| repository 구현 | `ResponseWindow.PHASE_CHANGE` 가 이 자리를 위해 정의되어 있다 |
| 실제 실행 | `_apply_end_phase` 가 `PriorityState.idle()` 로 **되돌린다** — 넘기는 것이 아니라 **없애는 것**이다. `PHASE_CHANGE` 는 `duel.py` 에 한 번도 나오지 않는다 |

### G — Spell Speed 와 응답 관계

**RULE-CHAIN-003 / 004 / 005 / 006** 그대로:

| Spell Speed | 카드 | 응답 가능 대상 |
|---|---|---|
| 1 | Spell(Normal·Equip·Continuous·Field·Ritual), Effect Monster 의 Ignition·Trigger·Flip | **없음** — "cannot be activated in response to any other effects" |
| 2 | Trap(Normal·Continuous), Quick-Play Spell, Quick Effect | 1, 2 — "can typically be activated **during any phase**" |
| 3 | Counter Trap | 1, 2, 3 |

`engine/activation_timing.py:94` 의 `RESPONSE_TABLE` 이 이 표를
`sd-rulebook-en-v10.json` 의 `chain.spell_speeds[*].can_respond_to` 에서
**그대로 뽑아** 들고 있다. 구현은 끝나 있고 **부르는 곳이 없다.**

### H — Trigger Effect 와 Quick Effect

RULE-CHAIN-009: Trigger · Flip 은 "activate **automatically**" 이므로 우선권과
무관하게 발동한다. RULE-CHAIN-010 이 동시 발동 순서를 정한다(턴 플레이어 강제
→ 상대 강제 → 턴 플레이어 임의 → 상대 임의). `engine/trigger_order.py` 가 이
순서를 구현하고 있다. **이번 Audit 의 범위 밖이다** — Trigger 는 선택이 아니라
자동이고, STRUCTURAL-34 는 **고르는 기회**의 문제다.

### I — Ignition/Normal action 과 response 의 차이

**RULE-CHAIN-011 (Actions which cannot be Chained to)**

> "You can only create a Chain by responding to the activation of a card or
> effect. **Summoning a monster, Tributing, changing a monster's battle
> position and paying costs are not effect activations** and therefore you
> cannot respond to those actions using a Chain."

| | |
|---|---|
| 규칙 근거 | 소환 · 릴리스 · 표시 형식 변경 · 비용 지불에는 **응답할 수 없다** |
| repository 구현 | 소환 뒤 우선권을 열지 않는다 |
| 실제 실행 | **규칙과 맞다.** 이 자리는 누락이 아니다 (실측 확인 · `test_09`) |

**이것이 중요하다.** 공백을 고칠 때 소환 뒤까지 열면 **규칙을 어기는 것**이다.

---

## 4. PriorityState Audit (§5)

| 질문 | 답 |
|---|---|
| 필드 | `holder` · `window` · `consecutive_passes` · `turn_player` · `phase` · `reason` (frozen · slots) |
| 초기화 | `Duel.start` 의 `PriorityState.idle(turn_player, phase)` **한 곳** |
| 갱신하는 주체 | `Duel` 만 (`_apply_pass`, `_apply_end_phase`) |
| 턴 시작 | `_apply_end_phase` 가 `idle()` 로 재설정 |
| 통상 소환 후 | **변하지 않는다** — 규칙대로다 (RULE-CHAIN-011) |
| 마법/함정 세트 후 | 변하지 않는다 (`SET_SPELL_TRAP` 은 `_apply_board`) |
| 효과 발동 후 | **변하지 않는다** — `advance_priority()` 를 아무도 부르지 않는다 |
| 체인 링크 추가 후 | 링크가 `apply` 밖으로 나오지 않으므로 해당 없음 |
| 체인 해결 후 | 변하지 않는다 (`AFTER_CHAIN_RULE` 미정) |
| 페이즈 변경 후 | `idle()` — **넘기지 않는다** |
| `END_PHASE` 후 | `idle()` |
| 상대가 응답 안 함 | 그 상태가 존재하지 않는다 |
| 아무도 응답 안 함 | 같음 |

**"존재하지만 아무도 여는 사람이 없다"** — 구현 완료로 취급하지 않는다.

---

## 5. ResponseLoop Audit (§6)

```
A. PlayerAction → validation → apply → response opportunity
                                        └─ ✘ 없다. apply 가 끝나면 바로
                                           다음 결정이고 그 결정은 다시
                                           턴 플레이어의 것이다

B. Effect activation → ChainLink → opponent response → ChainLink → pass → resolution
   ├ ChainLink 생성      ✔ engine/activation.py
   ├ opponent response   ✘ ResponseLoop.act 가 있지만 부르는 곳이 없다
   ├ pass                ✘ PASS 가 후보가 되지 않는다
   └ resolution          ✔ 단 **같은 apply 안에서 즉시**

C. Chain resolution → next action / response → priority
                        └─ ✘ AFTER_CHAIN_RULE 미정 (STRUCTURAL-34)
```

`ResponseLoop` 는 네 가지를 다 들고 있다 — `opened()`(기회 생성),
`act()`(응답 한 번, `ActivationTimingChecker` 로 스펠 스피드 판정),
`passed()`(패스), `closed(AFTER_CHAIN_RULE)`(해결 뒤 닫기). 설계자가
`opened()` 의 docstring 에 적어 두었다:

> "**'링크가 쌓였으니 자동으로 열린다' 는 규칙을 만들지 않았다** — 누가 언제
> 여는지는 아직 정해지지 않았고 (STRUCTURAL-34), 여기서 정하면 틀린 채로
> 굳는다. 부르는 쪽이 값으로 연다."

즉 **의도적으로 비워 둔 자리**이고, 그 "부르는 쪽" 이 아직 없다.

---

## 6. legal_actions 영향 (§7) — 시나리오 실측

전부 실제 엔진으로 돌렸다. 가짜 상태 없음. 가려진 정보 출력 없음.

| Scenario | turn_player | priority (holder/window) | chain | legal.seat 의 후보 | 상대 자리의 후보 |
|---|---|---|---|---|---|
| 1 체인 없는 MAIN1 | 0 | `nobody` / `none` | 0 | `END_PHASE` · `NORMAL_SUMMON` · `SET_MONSTER` | **없음** |
| 2 통상 소환 **직후** | 0 | `nobody` / `none` | 0 | `END_PHASE` | **없음** ← 규칙대로 (RULE-CHAIN-011) |
| 3 욕망의 항아리 발동 **직후** | 0 | `nobody` / `none` | 0 | `END_PHASE` · `NORMAL_SUMMON` · `SET_MONSTER` | **없음** ← 규칙 위반 (RULE-CHAIN-001) |
| 4 체인 링크 1 존재 | — | — | — | **도달 불가** | — |
| 5 상대가 응답 가능 | — | — | — | **도달 불가** | — |
| 6 상대가 패스 | — | — | — | **도달 불가** | — |
| 7 체인 해결 직후 | 0 | `nobody` / `none` | 0 | (3 과 같음) | **없음** |
| 8 END 페이즈 (END_PHASE 전) | 0 | `nobody` / `none` | 0 | `END_PHASE` **하나뿐** | **없음** ← 규칙 위반 (RULE-CHAIN-009) |
| 9 END_PHASE **적용 후** | **1** | `nobody` / `none` | 0 | 없음 (`step=DRAW_PENDING`) | 없음 |

**모든 결정에서 상대 자리의 `allowed` 가 비어 있고**, 그 자리에 다음 두
`withheld` 가 적힌다.

```
PASS           우선권이 열려 있지 않습니다.
               missing = 우선권을 여는 규칙 (Phase 2-F)
ACTIVATE_CARD  activate_card 의 남은 적법성을 판정할 규칙 계층이 아직 없습니다.
               missing = activation-timing (Phase 2-C/2-F)
```

**Scenario 4~7 은 `Duel` 로 만들 수 없다.** `_apply_activation` 이
놓기 → 발동 → 해결 → 묘지로 를 한 `apply` 안에서 끝내고 `Chain()` 으로
비우기 때문이다. 억지로 만들지 않고 그 사실을 적는다 (§5 · §7). 이것은
**STRUCTURAL-124 로 이미 등록된 문제**다.

### Scenario 9 의 `step=DRAW_PENDING`

`END_PHASE` 가 다음 턴 드로우 페이즈로 넘기면 양쪽 모두 후보가 0 이 되고,
`Duel.advance()` 가 드로우를 처리한다. 드로우는 **고르는 일이 아니므로**
행위 목록에 없는 것이 맞다. 다만 RULE-TURN-002 는 그 직후를 이렇게 적는다 —
"**After you draw, Trap Cards or Quick-Play Spell Cards can be activated**
before proceeding to the Standby Phase." 그 자리도 지금 열리지 않는다.

---

## 7. 실제 실행 Trace (§9)

욕망의 항아리 하나. 상대 패에 함정 구멍이 있는 상태(내용은 출력하지 않는다).

```
[발동 전]
  turn_player=0  phase=MAIN1
  priority: holder=nobody  window=none  is_open=False
  chain: len=0  complete=True
  legal.seat=0  allowed=['ACTIVATE_EFFECT', 'END_PHASE', 'SET_SPELL_TRAP']
  상대(1) allowed=[]
    withheld PASS: 우선권이 열려 있지 않습니다. | missing=우선권을 여는 규칙 (Phase 2-F)

발동: 55144522:e[0]
apply: accepted=True  code=OK
reason: 체인1 P0 55144522:e[0] 를 해결했습니다.
덱 20 → 18 / 내 패 장수 1 → 2

[발동 후 — 같은 apply 안에서 해결까지 끝났다]
  turn_player=0  phase=MAIN1
  priority: holder=nobody  window=none  is_open=False
  chain: len=0  complete=True
  legal.seat=0  allowed=['END_PHASE', 'NORMAL_SUMMON', 'SET_MONSTER']
  상대(1) allowed=[]
```

**상대는 발동과 해결 사이에 단 한 번도 결정하지 않았다.** RULE-CHAIN-001 은
"the opponent is **always** given a chance to respond" 라고 적는다.

---

## 8. 어떤 '정상 Action' 이 누락되는가 (§14 의 증거)

§14 는 "구현되어 있지 않다" 만으로 BLOCKER 라 하지 말고 **증거**를 내라고
한다. 증거는 이것이다.

`EFFECT_LIBRARY` 에 **이미 등록된** 16개 효과 중 **8개가 Spell Speed 2 이상**
이다.

| 카드 | 종류 | passcode |
|---|---|---|
| 욕망의 선물 | TRAP | 5915629 |
| 벌금 | TRAP | 92595643 |
| 강제 탈출 장치 | TRAP | 94192409 |
| 로스트 | TRAP | 24623598 |
| 의적의 입문서 | TRAP | 69091732 |
| 싸이크론 | SPELL · QUICKPLAY | 5318639 |
| 육신보살 | SPELL · QUICKPLAY | 15103313 |
| 리로드 | SPELL · QUICKPLAY | 22589918 |

RULE-CHAIN-005 는 이들이 "can typically be activated **during any phase**"
라고 적는다. 실측: **상대 턴에, 패에 있든 필드에 세트되어 있든, 후보가 하나도
나오지 않는다.** 그리고 그 이유가 `missing=우선권을 여는 규칙` 으로 적힌다.

즉 **효과 정의는 작동하는데 발동할 수 있는 순간이 존재하지 않는다.** 가설이
아니라 이름이 있는 카드 8장이다.

**단, 이것을 새 TODO 로 등록하지 않는다** (§15). STRUCTURAL-34 의 **증상**
이고, 34 가 열리면 함께 해소된다.

---

## 9. Search 영향 (§11)

| 단계 | 우선권 영향 |
|---|---|
| candidate 생성 | **PASS** — `legal_actions` 가 이미 걸러낸다. 탐색은 걸러진 목록만 받는다 |
| simulation | **PASS** — `Simulator._fork` 는 `dataclasses.replace(duel, state=clone())` 로 `priority` 와 `chain` 을 **참조 공유**한다. 둘 다 `frozen=True` 이고 `Duel` 은 전이할 때 **새 값을 대입**하므로 사본의 전이가 진짜를 건드리지 않는다 |
| future state | **PASS** — 사본의 `apply` 가 진짜와 **같은 규칙**으로 돈다 |
| evaluation | **NOT_REACHED** — `GameStateView` 가 `priority` 를 **노출하지 않는다** |
| ranking | **NOT_REACHED** — 같은 이유 |

**존재하지 않는 Action 을 후보로 만들지 않는다.** 거꾸로, 실제로 가능한
Response Action 을 **누락한다** (§8) — 그러나 그 누락이 Search 를 깨뜨리지는
않는다. 탐색은 자기가 받은 목록이 전부라고 가정하고, 그 목록은 **정직하게
좁다.**

---

## 10. Evaluation 영향 (§11) — 읽지 않는다

`agent/evaluation.py` · `search.py` · `policy.py` · `heuristic.py` 네 파일에
`priority` · `Priority` 가 **0건**이다. 그리고 `GameStateView` 에도 0건이므로
**읽을 방법 자체가 없다.**

Phase 3-E-5 ~ 3-E-9 가 세운 경계가 **구조로** 지켜진다.

> Evaluation 은 State Value 를 평가한다.
> Action availability / response opportunity 는 Action Space / Engine 의 일이다.

그래서 **STRUCTURAL-34 를 고칠 때 `GameStateView` 를 넓힐 이유가 없다.**
우선권은 `Duel` 안에서 `legal_actions` 가 쓰는 것이고, 평가로 올라갈 필요가
없다.

---

## 11. Observation Boundary (§12)

| 정보 | 공개인가 | 관측에 있는가 |
|---|---|---|
| `turn_player` · `turn_number` · `phase` · `step` | 공개 | ✔ |
| chain 길이 | 공개 (체인은 양쪽이 본다) | ✘ **노출되지 않는다** |
| priority / response seat | 공개 (누구 차례인지는 양쪽이 안다) | ✘ **노출되지 않는다** |
| 패 · 덱 · 뒷면 카드 정체 · RNG | 비공개 | ✘ (올바름) |

우선권과 체인 길이는 **공개 정보인데 관측에 없다.** 지금은 평가도 탐색도
필요하지 않으므로 문제가 아니다 (§10). 넓히지 않았고, 넓힐 이유도 찾지
못했다.

**hidden information leak: 없음.** Audit 은 `GameStateView` 밖을 읽지 않았고,
trace 에 가려진 카드의 정체를 출력하지 않았다.

---

## 12. STRUCTURAL-34 판정 — **C. STRUCTURAL ISSUE**

### 왜 A(RESOLVED) 가 아닌가

"필요한 의미와 갱신 경로가 충분히 존재하며 **실제 Action Space 에서도 올바르게
사용된다**" 가 A 다. 의미는 있고 갱신 경로의 **일부**(idle · passed · closed)만
있으며, **여는 경로가 없다.** Action Space 에서 상대 자리는 영구히 비어 있다.

### 왜 B(DESIGNED-OUT) 가 아닌가

B 는 "구현하지 않아도 되는 것이 **증명**된다" 는 뜻이다. 증명되지 않는다 —
공식 규칙이 명시적으로 요구하는 자리가 **둘** 비어 있다.

| 규칙 | 요구 | 현재 |
|---|---|---|
| RULE-CHAIN-001 | 발동마다 상대에게 **반드시** 응답 기회 | 없다 |
| RULE-CHAIN-009 | 페이즈를 넘길 때 **반드시** 우선권 양도 | `idle()` 로 없앤다 |

Phase 3-E-9 의 STRUCTURAL-128 과 결정적으로 다른 점이 이것이다. 128 은 "현재
평가의 정의 안에서 필요하지 않다" 를 **설계 문서로** 보일 수 있었다. 34 는
**룰북이 반대로 적는다.**

### 왜 D(BLOCKER) 가 아닌가

§14 가 요구한 세 증거를 따로 본다.

| 질문 | 답 | 근거 |
|---|---|---|
| **틀린 Action 이 생성되는가** | **아니다** | 모든 결정에서 상대 자리 `allowed == ()`. 범위 밖 발동은 `UNKNOWN` 이라 후보가 되지 않는다 (3-E-3). `withheld` 에 `missing` 이 적힌다 |
| **정상 Action 이 누락되는가** | **그렇다** | SS2+ 등록 카드 8장이 영구히 발동 불가 (§8) |
| **실행 경로가 불가능해지는가** | **아니다** | `legal_actions` → `apply` → `state` 가 정합적이다. 좁지만 틀리지 않다. 전체 테스트 3400개가 통과한다 |

"없는 권한을 허가로 바꾸지 않는다" 는 프로젝트의 핵심 불변식(UNKNOWN ≠
permission)이 **이 자리에서 지켜지고 있다.** 그래서 다음 Phase 가 잘못되지
않는다 — 좁은 채로 정확하다.

### 판정

> **C — STRUCTURAL ISSUE.** 개념은 전부 있고 연결이 끊겨 있다. 끊긴 지점은
> **한 곳**이다: 아무도 `PriorityState.opened(...)` 를 부르지 않는다. 지금
> 틀린 동작을 만들지는 않지만, 공식 규칙이 요구하는 두 자리가 비어 있고
> 등록된 카드 8장이 그 때문에 쓰이지 못한다.

---

## 13. 발견된 문제 (§15 — 중복 등록하지 않는다)

### 기존 TODO 로 **이미 등록된** 것 — 새로 매기지 않는다

| ID | 문제 | 어디에 적혀 있는가 |
|---|---|---|
| **STRUCTURAL-34** | 응답 · 우선권 창을 여는 자리가 없다 | `engine/response.py:54` · `:418` · `:642`, `engine/activation.py:407` |
| **STRUCTURAL-124** | 체인이 한 링크로 끝난다 — `_apply_activation` 이 즉시 해결 | `docs/phase3e3-effect-action-space.md` |
| `UNRESOLVED_PROGRESSION_RULES` | "우선권을 쥔 쪽이 페이즈 종료를 선언했는가", "전이 직후 우선권이 누구에게 열리는가", "체인이 남아 있거나 해결 중일 때 페이즈를 끝낼 수 있는가" | `engine/turn_progression.py:62` — **모든 `plan()` 이 이 목록을 들고 다닌다** |
| `AFTER_CHAIN_RULE` | 체인 해결 뒤 우선권 규칙 미정 | `engine/response.py:377` |

**END_PHASE 가 우선권을 넘기지 않는다** 는 이번 Audit 의 핵심 발견이지만,
`UNRESOLVED_PROGRESSION_RULES` 가 **이미 두 줄로 적고 있다.** 새 TODO 를
만들지 않고 그 목록을 가리킨다.

**SS2+ 카드 8장이 발동 불가**도 새 TODO 가 아니다 — STRUCTURAL-34 의 증상이다.

### 신규 TODO

**없다.** 이번 Audit 이 찾은 모든 문제가 기존 TODO 또는 기존
`UNRESOLVED_*` 목록에 이미 적혀 있다. 그것 자체가 중요한 결과다 — 엔진이
자기 공백을 **정직하게 기록해 두었다.**

### 관찰만 (TODO 아님)

| 관찰 | 내용 |
|---|---|
| 죽은 분기 | `duel.py:470` 의 `if self.priority.is_open and ...` 와 `_apply_pass` 전체가 도달 불가. 34 가 열리면 살아난다 — 지금 지우면 안 된다 |
| 보고 누락 | 필드에 **세트된** 마법·함정에 대해서는 `ACTIVATE_CARD` 의 `withheld` 가 나오지 않는다 (패의 카드만 본다). 이유가 적히지 않는 자리가 하나 있다 |
| 관측 미노출 | 체인 길이와 우선권이 공개 정보인데 `GameStateView` 에 없다. 지금 필요하지 않으므로 넓히지 않았다 |

---

## 14. Tests (§17)

```
3411 passed · 0 failed · 4 skipped
```

기준(`5d1e787`) **3400 passed** → **+11**

신규 `tests/engine/test_priority_response_audit.py` (11개):

| 테스트 | 무엇을 고정하는가 |
|---|---|
| `test_01_the_priority_vocabulary_is_complete` | 자리 · 기회 · 여섯 전이가 전부 있다 — 데이터 구조가 없는 것이 아니다 |
| `test_02_only_three_transitions_are_wired_into_the_duel` | `Duel` 이 `opened`·`give_to`·`acted` 를 **한 번도 부르지 않는다** |
| `test_03_the_response_loop_is_imported_by_no_production_module` | `ResponseLoop` 를 import 하는 production 모듈이 0개 |
| `test_04_the_window_is_closed_at_every_decision_of_a_real_duel` | 실제 대국 전체에서 `window=NONE`, `to_act == turn_player` |
| `test_05_the_opponent_never_receives_a_candidate` | 상대 `allowed == ()`, `missing` 에 우선권 규칙이 적힌다 |
| `test_06_no_registered_fast_effect_can_ever_be_activated` | SS2+ 등록 카드 8장이 상대 턴에 후보가 되지 않는다 |
| `test_07_the_chain_is_empty_at_every_decision` | Scenario 4~7 이 도달 불가 — 억지로 만들지 않는다 |
| `test_08_end_phase_resets_priority_instead_of_passing_it` | RULE-CHAIN-009 과 어긋나는 자리. `PHASE_CHANGE` 가 `duel.py` 에 없다 |
| `test_09_a_summon_correctly_opens_no_window` | RULE-CHAIN-011 — **여기는 맞다.** 고칠 때 열면 안 되는 자리 |
| `test_10_priority_is_not_in_the_observation_and_not_in_the_agent` | 관측·agent 에 0건 — 경계가 구조로 지켜진다 |
| `test_11_the_simulator_shares_the_frozen_priority_safely` | 사본이 공유해도 안전한 이유 |

**의도적 위반 주입 1건.** `_apply_end_phase` 가 `PHASE_CHANGE` 기회를 열도록
바꿨더니 `test_02` · `test_04` · `test_05` · `test_07` · `test_08` 다섯이
잡았다. 되돌린 뒤 `git diff engine/ agent/` 가 비어 있음을 확인했다.

기존 테스트: **수정 0 · 삭제 0 · skip 0 · assertion 완화 0.** Regression 0.

---

## 15. Performance (§18)

**측정하지 않았다.** 이번 단계는 Audit 이고 최적화를 하지 않는다.

관찰만 하나: `Duel.legal_actions` 는 호출마다 `self.priority` 를 두 번 읽는다
(`_flow_actions` 의 두 분기). frozen dataclass 의 속성 읽기이므로 비용이 없고,
캐시를 만들 이유가 없다.

---

## 16. Engine Change Required — **NO**

§19 의 여섯 조건을 하나씩 본다. **하나도 해당하지 않는다.**

| 조건 | 해당 |
|---|---|
| priority state 자체가 없어 새 상태가 필요 | **아니다** — `PriorityState` 가 완전하다 |
| response seat 를 표현할 구조가 없다 | **아니다** — `PriorityHolder` + `ResponseWindow.RESPONSE` |
| Chain 과 Priority 가 구조적으로 충돌 | **아니다** — `ResponseState(chain, priority)` 가 둘을 함께 든다 |
| `legal_actions` 가 올바른 seat 를 정할 수 없다 | **아니다** — `to_act` 가 이미 "홀더 → 턴 플레이어" 를 쓴다. 홀더가 채워지면 그대로 작동한다 |
| `ActionExecutor` 가 priority 를 필요로 하는데 전달 방법이 없다 | **아니다** — `ResponseLoop.act` 가 `ResponseState` 로 전달한다 |
| END_PHASE 와 Chain resolution 이 서로 다른 priority 규칙을 요구 | **그렇지만 충돌이 아니다** — `ResponseWindow` 가 `PHASE_CHANGE` 와 `RESPONSE` 를 **따로** 갖고 있다. 두 규칙을 두 값으로 구분할 수 있다 |

그러므로 **ENGINE CHANGE REQUIRED 가 아니다.** 다음 Phase 는 새 구조를 만드는
일이 아니라 **이미 있는 것을 부르는 일**이다 — 승인을 받고 시작하면 된다.

---

## 17. 다음 Phase 후보 — 하나만

**STRUCTURAL-34 의 절반: 체인 응답 창 하나만 연다 (RULE-CHAIN-001).**

범위를 **발동 직후의 RESPONSE 창 하나**로 좁힌다. 페이즈 전환
(RULE-CHAIN-009)과 체인 해결 뒤(`AFTER_CHAIN_RULE`)는 **건드리지 않는다.**

근거:

1. **규칙 근거가 한 문장으로 끝난다** — RULE-CHAIN-001: "the opponent is
   always given a chance to respond". 해석할 것이 없다
2. **새 구조가 필요 없다** (§16) — `ResponseLoop.opened` · `act` · `passed` ·
   `PriorityState` 전이가 전부 있다. `_apply_activation` 을 네 걸음에서
   **창을 여는 자리까지** 늘리는 일이다
3. **열리면 STRUCTURAL-124 가 함께 풀린다** — 체인이 두 링크 이상이 될 수 있다
4. **측정 가능한 변화가 바로 나온다** — SS2+ 카드 8장이 후보에 오르고,
   한 결정 안에서 `turn_player` 가 상수가 아니게 되어 **STRUCTURAL-128 ·
   123 · 133 이 동시에 측정 가능**해진다 (Phase 3-E-9 가 예고한 조건)
5. **경계를 넓히지 않는다** — `GameStateView` 를 손대지 않아도 된다 (§10)

하지 **않을** 것을 미리 적는다: 페이즈 전환 우선권 · 체인 해결 뒤 우선권 ·
Trigger Effect 자동 발동 · Damage Step · Depth-2 · 새 Priority/Response Engine.

그리고 RULE-CHAIN-011 이 정한 자리는 **열지 않는다** — 소환 · 릴리스 ·
표시 형식 변경 · 비용 지불에는 응답할 수 없다 (`test_09` 가 지킨다).
