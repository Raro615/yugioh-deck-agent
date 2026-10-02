# Phase 3-E-4 — Target Selection Bridge

- **Base commit**: `d5fbc29` (Phase 3-E-3 — Effect Action Space)
- **Branch**: `claude/pensive-goodall-te1egy`
- **결과**: 3306 → **3339 passed, 4 skipped** · 새 테스트 33개 · 회귀 0건
- **`engine/` 변경**: 새 파일 1개 + 기존 파일 1개

---

## 1. 증명한 한 줄

```
PlayerAction(targets=(ActionTarget.instance(#42),))
  → selections_for → (TargetSelection(@primary, Selection((#42,))),)
  → EffectActivator.activate → ChainLink(selections=…)
  → ChainResolver → EffectOperation(targets=…) → state change
```

실제 실행 trace (무정한 말살 `73148972`):

```
내 몬스터: 사파이어 드래곤=#41  배틀 옥스=#42

① legal_actions     → ACTIVATE_EFFECT 후보 2개 (대상마다 하나)
                        activate_effect P0 #40 73148972:e[0] ->#41
                        activate_effect P0 #40 73148972:e[0] ->#42
   고른 후보          ... ->#42
② selections_for    → @primary = (42,)   (@random 은 짝에서 빠진다)
③ validation        → valid [ok]
   적용 전              내MZONE=[41,42] 내묘지=[] 상대패=2 상대묘지=[]
④ Duel.apply        → accepted=True [ok]
                      체인1 P0 73148972:e[0] 대상 @primary=[#42] 를 해결했습니다.
   적용 후              내MZONE=[41] 내묘지=[42,40] 상대패=1 상대묘지=[20]
```

고른 `#42` 가 묘지로, 발동한 `#40` 도 묘지로(RULE-SPELLTRAP-002), 상대 패에서
무작위 1장(`#20`)이 묘지로 — **세 가지가 서로 다른 경로**다.

---

## 2. Engine 변경

| 파일 | 무엇을 | 왜 |
|---|---|---|
| `engine/target_bridge.py` **(신규)** | `selections_for` · `targets_from` · `target_combinations` · `chosen_bindings` · `required_target_count` | 없던 것은 `ActionTarget` ↔ `TargetSelection` **환전** 하나였다 (STRUCTURAL-121) |
| `engine/duel.py` | `_activation_actions` 가 대상 조합마다 후보 생성 · `_apply_activation` 이 환전 결과를 전달 | 후보와 실행 양쪽에 다리를 꽂는다 |

**`PlayerAction` 은 바꾸지 않았다.** `targets: tuple[ActionTarget, ...]` 가
이미 있고 `_TARGET_COUNT[ACTIVATE_EFFECT]` 가 이미 `None`(제한 없음)이며,
`ActionTarget` 이 이미 `InstanceId` 를 담는다. §3 이 "최소 구조가 필요하다면
추가한다" 고 했는데 **추가할 것이 없었다.**

새로 만들지 **않은** 것: TargetEngine · TargetGraph · TargetSearchEngine ·
EffectEngine · ChainEngine · 새 `ValidationCode` · 새 적법성 어휘 ·
새 hidden-information 체계 · 새 random target 체계.

재사용한 것: `TargetResolver.candidates`(후보 세기) · `TargetResolver.validate`
(적법성) · `CandidateResolver` · `TargetSelection`/`Selection` · `ChainLink` ·
`EffectExecutor` · `GameStateView` + `looked_at`(Phase 2-Y) · 기존 Game RNG.

---

## 3. TargetSelection

| | |
|---|---|
| **구조** | 기존 `TargetSelection(ref: TargetRef, selection: Selection)` 를 **그대로** 쓴다. 새 타입 없음 |
| **identity** | `InstanceId`. 카드 이름도 `card_id` 도 쓰지 않는다 — 같은 이름 세 장이 서로 다른 후보가 된다 (`test_07`) |
| **ordering** | 관측의 순서(몬스터 존 자리 순서)를 보존한다. `set` 을 거치지 않는다 (`test_10`) |
| **multiple target** | 구조는 0 · 1 · N 을 표현한다 (`Selection(chosen=tuple)`). 다리는 **고르는 자리 1개 × 1장**까지만 조합을 만들고, 그 밖은 빈 목록 → 후보 없음 (NOT_REACHED) |

### 환전은 **순서 → 이름**이다

`PlayerAction` 에는 이름이 없고 순서만 있다. `EffectDefinition` 에는 이름이
있다(`@primary` · `@random`). 다리는 `action.targets` 를 정의의 **고르는
자리들**에 정의 순서대로 짝지운다.

```
ActionTarget      행위가 무엇을 가리키는가 (자리 · 플레이어 · 존도 가능, 이름 없음)
TargetSelection   어느 이름의 대상에 무엇이 골라졌는가 (이름은 정의에서 온다)
```

둘을 합치지 않았다 — 다른 질문에 답하는 다른 타입이다.

---

## 4. Legal Action (8씨앗, `사파이어드래곤×8 + 배틀옥스×4 + 욕망의항아리×4 + 무정한말살×4`)

### 대상이 **없는** ACTIVATE (욕망의 항아리)

| 조합 | legal | selected | executed |
|---|---|---|---|
| search | 69 | 0 | 0 |
| rule | 89 | 45 | 45 |
| random | 111 | 31 | 31 |
| first-legal | 53 | 0 | 0 |

### 대상이 **있는** ACTIVATE (무정한 말살)

| 조합 | legal | selected | executed |
|---|---|---|---|
| search | 49 | 0 | 0 |
| rule | 80 | 45 | 45 |
| random | 131 | 18 | 18 |
| first-legal | 35 | 0 | 0 |

4조합 모두 8/8 completed · refusals 0 · errors 0 · limits 0.

**탐색이 고르지 않는 것은 평가의 결과다.** 무정한 말살은 자기 몬스터를 묘지로
보내므로 손해다. 그런데도 **두 대상 중 덜 손해인 쪽**(공격력이 낮은 배틀 옥스)
에 더 높은 점수를 매긴다 — 평가가 대상을 구별한다는 증거이고 `test_28` 이
그것을 센다. **가중치를 고쳐 고르게 만들지 않았다.**

---

## 5. 실제 카드

| | |
|---|---|
| Card | 무정한 말살 |
| Card ID | `73148972` |
| EffectRef | `EffectRef(73148972, 0)` |
| 종류 | `['SPELL']` — 통상 마법 (Phase 3-E-3 범위 안) |
| 비용 | `CostGroup(costs=())` — 없음 |
| `@primary` | 자신 필드의 몬스터 1장 — **플레이어가 고른다** (`TargetSpec.targeting`) |
| `@random` | 상대 패에서 1장 — **아무도 고르지 않는다** (`TargetSpec.at_random`) |
| 발동 조건 | `And(내 MZONE ≥ 1, 상대 HAND ≥ 1)` |
| 근거 | `c73148972.lua` 의 `s.target` · `s.activate`. `lua_excerpt` 에 `SelectTarget` 과 `RandomSelect` 가 함께 들어 있다 |

**왜 이 카드인가** (§13): `EFFECT_LIBRARY` 에 등록 · `executable=True` ·
대상을 요구 · 조작(`send_to_grave`)이 실행 가능 · Lua 근거 확인 가능 —
다섯 조건을 모두 만족하는 가장 단순한 1-target 통상 마법이다. 그리고 한 장으로
§18 의 구분(플레이어 선택 vs 무작위)까지 증명한다.

| 단계 | 판정 |
|---|---|
| Activation | **PASS** |
| Target | **PASS** — `@primary` 가 `ChainLink.selections` 에 보존된다 (`test_14`) |
| Chain | **PASS** — 체인 1 |
| Resolution | **PASS** |
| State Change | **PASS** — 고른 몬스터 MZONE→GRAVE, 상대 패 1장 HAND→GRAVE |

### 후보가 되지 못한 카드 — 이유를 적는다

| 카드 | 이유 | 판정 |
|---|---|---|
| 어리석은 매장 `81439173` | 대상이 **덱**에 있다 (§8 아래) | **NOT_REACHED** |
| 싸이크론 `5318639` · 육신보살 `15103313` · 리로드 `22589918` | **속공** 마법 — Phase 3-E-3 의 발동 타이밍 범위 밖 (RULE-SPELLTRAP-007) | NOT_REACHED |
| 벌금 · 강제 탈출 장치 · 의적의 입문서 | **함정** — 세트가 앞선다 (RULE-SPELLTRAP-009) | NOT_REACHED |

---

## 6. 가려진 자리의 대상은 가리키지 않는다 — **STRUCTURAL-125** (신규)

구현 중에 발견한 것이고, 이번 Phase 에서 가장 중요한 안전 결정이다.

어리석은 매장은 **자기 덱**의 몬스터를 고른다. 규칙이 그 효과에게 덱을 열어
주므로(`TargetSpec.looked_at_zones() == {DECK}`) 후보를 **셀 수는 있다** —
실제로 20장이 나왔다.

그런데 `PlayerAction` 은 `legal_actions` 가 **정책에게 그대로 건네는
데이터**다. 거기에 덱의 카드를 적으면 **후보 목록을 읽는 것만으로 덱 내용이
새어 나간다.** `looked_at` 이 효과에게 준 권한은 해결 중에만 유효한데, 그것이
AI 에게까지 새는 길이 된다.

그래서 다리가 `eligible` 을 **평소 관측으로 한 번 더 좁힌다.**

```python
ordinary = GameStateView.from_state(state, viewer=seat)
return [... for instance in found.eligible if ordinary.find(instance) is not None]
```

`ActionValidator` 의 참조 무결성 검사(`_first_unseen`)도 같은 것을 잡지만
(이중 방어, `test_18b` 가 둘 다 확인한다), **가려진 카드를 가리키는 Action 을
만들지 않는 것**이 만들고 거절하는 것보다 낫다.

Phase 3-E-3 은 이 카드가 후보가 아닌 이유를 "대상을 건넬 길이 없다"
(STRUCTURAL-121) 로 적었다. 길은 생겼고, **이제 이유가 관측 경계다.**

---

## 7. Search Simulation

| 항목 | 판정 |
|---|---|
| candidate | **PASS** — 대상마다 하나 |
| target candidate | **PASS** — `TargetResolver.candidates` 의 `eligible` 만 |
| simulation | **PASS** — `SUPPORTED`, 미래가 돌아온다 |
| future state | **PASS** — 대상이 다르면 미래가 다르다 (`test_23`) |
| evaluation | **PASS** — 대상마다 점수가 다르다 (`test_28`) |

**`SearchPolicy` 에 대상 분기를 넣지 않았다.** Action 자체가 대상을 들고
있으므로 평소 경로가 그대로 돈다. `agent/` 어디에도 `TargetSelection` ·
`ActionTarget` · `choose_target` 토큰이 **0건**이다 (`test_27`).

**후보 폭발을 만들지 않았다** (§17): 같은 Action + 같은 대상의 중복이 없고
(`test_11`), 패에 2장 × 대상 1장이 4개가 아니라 2개다. pruning · MCTS ·
transposition table 은 만들지 않았다.

---

## 8. Negative Cases (§15)

| # | 경우 | 결과 | 테스트 |
|---|---|---|---|
| 1 | 없는 `instance_id` | **UNKNOWN** (`HIDDEN_CARD`) — 아래 설명 | `test_16` |
| 2 | 잘못된 zone (패의 카드를 필드 대상으로) | **INVALID** (`CANDIDATE_NOT_ELIGIBLE`) | `test_17` |
| 3 | 조건 불만족 (상대 몬스터) | **INVALID** (`CANDIDATE_NOT_ELIGIBLE`) | `test_18` |
| 4 | 가려진 정체 (뒷면 마법·함정) | **UNKNOWN** (`INFORMATION_UNAVAILABLE`) · 후보 0 | `test_19` |
| 4b | 가려진 자리 (덱) | 후보 0 + 검증기 `UNKNOWN` | `test_18b` |
| 5 | 대상이 필요한데 없음 | 후보 아님 → `apply` 거절 · 판 불변 / 다리는 `TargetBridgeError` | `test_20` |
| 6 | 대상 없는 효과에 대상 | 같음 | `test_21` |
| 7 | 같은 이름 여러 장 | `instance_id` 로 구분 | `test_07` |

### §15-1 에서 `INVALID` 가 아니라 `UNKNOWN` 을 고른 이유

§15-1 은 없는 `instance_id` → `INVALID` 를 기대하지만, 이 저장소는
**`UNKNOWN` 으로 남긴다.** 그대로 따르면 §6 · §19 를 깨기 때문이다.

"그런 카드가 없다" 와 "그 카드를 볼 수 없다" 는 관측에서 **구별되지 않는다.**
구별해서 `INVALID` 를 돌려주면, 임의의 id 로 검증을 반복하는 것만으로 상대
패·덱에 어떤 instance 가 있는지 탐지할 수 있다 — ADR-007 이 막는 바로 그
경로다.

어느 쪽이든 **허가가 아니므로** 후보가 되지 않고 `apply` 도 거절하고 판도
바뀌지 않는다. 안전성은 같고, 정보가 새지 않는 쪽을 골랐다 (`test_16` 이 이
판단을 기록한다).

---

## 9. Safety

| 항목 | 판정 | 증거 |
|---|---|---|
| original state unchanged | **PASS** | 시뮬레이션 5×전체 후 `board()` 불변 (`test_22`·`test_24`) |
| clone independence | **PASS** | 사본에서 대상이 사라지고 원본에는 남아 있다 |
| RNG isolation | **PASS** | `@random` 이 Game RNG 만 쓴다 — 같은 씨앗이면 같은 카드, 사본의 난수가 원본에 남지 않는다 (`test_25`) |
| hidden information | **PASS** | 후보가 상대 패를 가리키지 않는다. `@random` 으로 갈 카드가 Action 에 **적혀 있지 않다** (`test_26`) |
| 환전이 배치보다 **앞** | **PASS** | 모양이 틀린 Action 이 카드를 필드에 올려놓고 멈추지 않는다 (`test_20`) |

고의 위반 6건으로 전부 잡히는지 확인하고 되돌렸다.

| 위반 | 깨진 시험 |
|---|---|
| `undecided`(가려진 정체)도 후보로 | `test_19` |
| `looked_at` 을 평소 관측으로 좁히지 않음 | `test_18b` |
| `at_random` 도 플레이어가 고르게 짝지음 | 18건 |
| 대상 개수 검사 제거 | `test_04` |
| 후보 순서를 `set` 으로 뒤집음 | `test_10` |
| 환전을 배치 **뒤**로 이동 | `test_20` |

**뒤의 둘은 처음에 잡히지 않아서 시험을 고쳤다.** `test_10` 은 "같은 판이면
같은 순서" 만 봐서 뒤집힌 순서를 통과시켰고(관측 순서에 못박아 고쳤다),
`test_20` 은 `apply` 로만 두드려서 `_apply_activation` 안의 순서를 보지
못했다(실행 경로를 직접 부르도록 고쳤다).

---

## 10. Regression

| | |
|---|---|
| Baseline | 3306 passed / 4 skipped |
| New | `tests/engine/test_target_bridge.py` — **33개** |
| 총계 | **3339 passed / 4 skipped** |
| Regression | **0건** |
| 기존 테스트 수정 | docstring 1건 (`test_06` — 어리석은 매장이 후보가 아닌 **이유**가 달라졌다) |

`NORMAL_SUMMON` · `SPECIAL_SUMMON` · `ATTACK` · `SET_MONSTER` ·
`SET_SPELL_TRAP` · `ACTIVATE_EFFECT` 와 네 정책 전부 그대로 동작한다
(`test_29`·`test_30`).

---

## 11. TODO

### 해결

| ID | 근거 |
|---|---|
| **STRUCTURAL-121** | `ActionTarget` ↔ `TargetSelection` 환전이 생겼고, 대상이 있는 통상 마법이 후보 → 실행 → state mutation 까지 간다 (`test_12`) |

### 유지

STRUCTURAL-102 · 107 · 109 · 110 · 115 · 116 · 118 · 120 · 122 · 123 · 124 ·
34 · 55 · 56 · 47 · 7 · 16 · 50 · 51 — 전부 §22 범위 밖.

STRUCTURAL-122(평가가 드로우를 손해로 읽는다)와 123(규칙 기반이 알파벳
순서로 고른다)은 이번 측정에서 **다시 관찰됐다**: 탐색은 대상 발동도 고르지
않고(자기 몬스터를 버리는 것이 손해), 규칙 기반은 대상 발동을 45회 고르는데
그것을 보는 규칙은 여전히 없다.

### 새로 발견

| ID | 내용 | 근거 |
|---|---|---|
| **STRUCTURAL-125** | `looked_at` 이 효과에게 준 관측 권한을 `PlayerAction` 에 실으면 AI 에게 샌다. 그래서 다리가 평소 관측으로 좁히고, **덱·상대 패를 대상으로 하는 효과는 후보가 될 수 없다** | `test_18b` |
| **STRUCTURAL-126** | 고르는 자리가 **둘 이상**이거나 **N장**을 고르는 효과는 조합을 만들지 않는다 (빈 목록 → 후보 없음). 조합 폭발과 순서 규칙을 함께 정해야 하고 그 규칙이 없다 | `target_combinations` |
| **STRUCTURAL-127** | `Duel.apply` 의 후보 재확인이 다리의 모양 검사보다 **앞**이므로, 다리의 `TargetBridgeError` 는 `apply` 경로에서 도달하지 않는다 (두 번째 방어). 그래서 그 경로는 `_apply_activation` 을 직접 불러야 시험된다 | `test_20`·`test_21` |

---

## 12. 범위 밖으로 둔 것

모든 target rule · 모든 카드 target effect · targeting vs non-targeting 전체
규칙 · 대상 지정 후 변경 · 체인 상의 대상 적법성 · replay target engine ·
UI · Discord · Master Duel · MCTS · Depth-2 · RL · NN · deck builder ·
모든 Spell/Trap · 모든 Monster Effect — 전부 손대지 않았다.

**random target 체계도 새로 만들지 않았다.** 기존 `TargetSpec.at_random` 과
Game RNG 를 그대로 쓰고, 다리는 그 자리를 짝짓기에서 제외한다.
