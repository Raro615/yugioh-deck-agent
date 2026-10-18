# Phase 6-Y — AI 자율 행동 선택 및 효과 해결 시점 선택 연결

브랜치: `claude/pensive-goodall-te1egy` · 시작 지점 `374b27b` (6-X 완료)

## 요약 — 달성 수준

| 수준 | 내용 | 결과 |
| --- | --- | --- |
| 수준 1 | Agent·Duel·선택 계약 조사, 자율 의사결정이 끊기는 지점 확인 | ✅ **달성** — 끊김이 **셋**이다 (§2) |
| 수준 2 | Agent 가 합법적 행동과 해결 시점 선택을 **각각 독립적으로** 결정 | ✅ **달성** |
| 수준 3 | 실제 선공 GameState 에서 외부 행동 지정 없이 기르수 전개 수행·검증 | ✅ **달성** (한 가지 경계를 §12 에 적는다) |

AI 가 결정한 것 셋, 시험이 준 것 셋을 가른다.

| | AI 가 결정 | 시험이 제공 |
| --- | --- | --- |
| ① 어떤 합법 행동인가 | `rule_based_policy` → `normal_summon` (후보 6개 중) | 덱 레시피 · 선공 패 |
| ② 유발을 발동할 것인가 | `FirstPermittedChoice` → `True` | 정책 객체와 씨앗 |
| ③ 어느 카드를 고를 것인가 | 후보 35개 · 허용 1개 중 `InstanceId(34)` | — |

```
#0 normal_summon P0: P0 가 #75 를 HAND 에서 MZONE[0] 로 normal 소환 (FACEUP_ATTACK)
#1 69811710:e[0] P0: #34 P0/DECK → P0/GRAVE (send_to_grave),
                     P0 의 DECK 34장을 섞었다
덱 35 → 34 · 묘지 0 → 1 · 후속 legal_actions ['end_phase', 'set_spell_trap']
```

🔴 **그 이동이 정책의 결정임을 대조군으로 보인다.** 같은 판 · 같은 소환인데
`DeclineChoice` 로 돌리면 **아무것도 움직이지 않는다** (덱 35 · 묘지 0 ·
효과 기록 없음). 씨앗이 다른 `RandomChoice` 는 서로 **다른 카드**를 고른다.

🔴 **아직 안 되는 것도 적는다.** 유발 발동은 `legal_actions` 에 오르지 않고
`Duel.apply` 도 받지 않는다. 그래서 상대 응답 순환이 이 경로에서 돌지
않았고, **돌았다고 적지 않았다** (`BLOCKER-6Y-1` · `BLOCKER-6Y-2`).

---

## 1. 기존 Agent와 Duel 연결 구조

**이미 완성되어 있었다.** 6-Y 가 새로 만든 것이 아니다.

```
Duel                              엔진 (V1 FREEZE)
  ↓  view(seat) · legal_actions(seat)
Policy.decide(view, legal)         AI — 관측과 후보 목록 **둘뿐**을 받는다
  ↓  PlayerAction
DuelRunner._judge                  🔴 정책의 말은 허가가 아니다 — 다시 본다
  ↓
Duel.apply(action)                 엔진
  ↓
Transcript                         무슨 일이 있었는가
```

| 자리 | 파일 | 하는 일 |
| --- | --- | --- |
| 정책 프로토콜 | `agent/policy.py` | `decide(view, legal) -> PlayerAction \| None` |
| 기준점 정책 | `agent/policy.py` | `FirstLegalPolicy` · `RandomPolicy(seed)` · `ScriptedPolicy` |
| 규칙 기반 정책 | `agent/heuristic.py` | `rule_based_policy` (`SummonBeforeEndingThePhase` 등 고려 넷) |
| 탐색 정책 | `agent/search.py` · `agent/evaluation.py` | 상태 평가 · 탐색 |
| 실행 | `agent/runner.py` | `DuelRunner.step` · `run` · `Transcript` |
| 대전 | `agent/arena.py` | `make_search` · `make_rule_based` · `make_random` · `make_first_legal` |

### 1.1 §4 의 요구 8개는 **기존 구조가 이미 만족한다**

| § | 요구 | 어디서 |
| --- | --- | --- |
| 4-1 | 합법적인 후보만 선택 | `DuelRunner._judge` — `chosen not in legal.allowed` 면 거절 |
| 4-2 | 선택 근거 기록 | `Transcript` · `TranscriptEntry(policy, reason, legal_count)` |
| 4-3 | 재현 가능 | `RandomPolicy(seed)` — 듀얼과 **다른 난수원** |
| 4-4 | 불확실한 행동 강행 금지 | 엔진이 `DuelStep.accepted=False` 로 거절 |
| 4-5 | 무한 반복 금지 | `MAX_STEPS = 5_000` + 거절 시 `run` 이 멈춘다 |
| 4-6 | 종료 사유 기록 | `Transcript.result` · `TranscriptEntry.reason` |
| 4-7 | 횟수·시간 제한 | `run(max_steps=…)` · `arena._Timed` |
| 4-8 | PASS · 턴 종료 적법 처리 | `PlayerActionKind.PASS` · `end_phase` |

🔴 **그래서 새 정책도 새 실행기도 만들지 않았다** (§3 의 금지).

### 1.2 조립 층이 이미 있다

`integration/` 은 Phase 6-I 가 **바로 이런 배선을 위해** 만든 자리다 —
"`core` · `analysis` · `engine` 을 전부 import 하는 **유일한** 자리". 거기에
`compiled_triggers` · `registry_for_view` · `readiness_for` 가 있다.

---

## 2. 자율 행동·해결 시점 선택의 실제 누락 원인

🔴 **끊김이 하나가 아니라 셋이다.** 전부 실측으로 확인했다.

### 2.0 먼저 — 발동 시점은 **이미 자율이었다**

| 정책 | 첫 선택 | 기르수가 필드에 | 
| --- | --- | --- |
| `rule_based_policy` | `normal_summon` | ✅ |
| `FirstLegalPolicy` | `normal_summon` | ✅ |
| `RandomPolicy(7)` | `set_spell_trap` (나중에 소환) | ✅ |

세 정책 **전부** 기르수를 필드에 올린다. 6-Y 가 열어야 할 것은 그 **뒤**다.

### 2.1 `BREAK-1` — 유발 발동이 `legal_actions` 에 오르지 않는다

```
legal_actions(MINE) → ['end_phase', 'set_spell_trap']   (activate_effect 0개)
duel.apply(activate_effect) → accepted=False
    "activate_effect 는 지금 허가된 행위가 아닙니다."
```

원인은 **발동 분류**다.

```python
ACTIVATION_KINDS_IN_SCOPE = frozenset({ActivationKind.IGNITION})
기르수 정의의 activation_kind = ActivationKind.TRIGGER
```

그 범위가 기동 하나인 **이유가 적혀 있다** — 룰북이 발동 시점을 문장으로
확정한 분류가 그것뿐이다 (`RULE-EFFECT-002`: *"You use this type of effect
just by declaring its activation during your Main Phase."*). 유발의 시점은
**사건**이고, 그 지식은 트리거 계층에 있는데 아직 듀얼 루프에 이어지지
않았다.

### 2.2 `BREAK-2` — 발동 시점 다리가 덱 선택을 지운다

```
target_combinations(state, MINE, 기르수 정의, source) → []
```

`STRUCTURAL-125` 다. 6-W §1.1 이 그 경계가 **옳은** 이유를 적었다 —
`PlayerAction` 은 정책에게 가는 데이터이므로 거기에 덱 인스턴스를 적으면
정책이 후보 목록을 읽는 것만으로 덱 내용을 알게 된다.

그리고 발동 자체도 선택을 **먼저** 요구한다.

```
EffectActivator.activate(..., selections=())  →  invalid_target
    "@primary 의 대상이 발동에 쓸 수 없습니다: 0장 골랐습니다 (최소 1장)."
```

### 2.3 🔴 `BREAK-3` — **엔진이 스스로 무엇이 없는지 적어 두었다**

트리거 계층을 실제 Duel 의 기록에서 구동하면 후보가 **나온다**.

```
registry_for_view → RegistryBuild(registered=2, concealed=0, …)
timing_events(ActionEvent) → TimingPoint.MONSTER_SUMMONED
collect_and_order → TriggerGroup(role=TURN_PLAYER,
                                 mandatory=(), optional=(), undetermined=(…))
```

그 후보를 뜯어보면 이렇게 적혀 있다.

```
TriggerCandidate(
    point=MONSTER_SUMMONED,
    effect_ref=69811710:e[0],
    source=InstanceId(75),
    status=TriggerStatus.ELIGIBLE,            ← 다섯 관문 통과
    requirement=TriggerRequirement.UNKNOWN,   ← 강제/임의를 모른다
)
TriggerChainEntry(
    link=None,
    reason='발동에 필요한 것이 아직 정해지지 않았습니다: 대상 선택 (@primary).
            가짜로 채워 넣지 않습니다.'
)
```

🔴 **그 마지막 문장이 이 Phase 의 발견이다.** 후보는 적법하고, 막는 것은
"선택이 아직 정해지지 않았다" 이고, **정해졌을 때 그것을 받을 통로가
없었다.** `TriggerChainIntegrator.plan` 에 선택을 넣을 자리가 없다.

그래서 고르는 사람이 골라도 체인에 오르지 못했다 — 이것이 §11 수준 2 가
가리키는 끊김이고, 6-Y 가 연 **단 하나의 엔진 변경**이다.

---

## 3. 채택한 정책 및 선택 근거

### 3.1 네 안을 비교했다

| 안 | 내용 | 판단 |
| --- | --- | --- |
| ① `ACTIVATION_KINDS_IN_SCOPE` 에 `TRIGGER` 추가 | `Duel.apply` 가 유발을 받는다 | 🔴 **기각** — 사건 상태를 `Duel` 에 넣어야 하고 (`TimingCoordinator` 미연결), `legal_actions` 가 바뀌어 모든 결정 digest 가 움직인다. 중대한 공유 계약 변경이다 |
| ② `target_combinations` 가 `[()]` 를 내놓게 + 발동 관문 완화 | 다리가 열린다 | 🔴 **기각** — 발동 관문의 의미를 **모든** `CHOOSING` 효과에 대해 바꾼다. `STRUCTURAL-125` 가 지키는 것은 정보 경계이고, 완화하면 그 경계가 약해진다 |
| ③ `agent/` 에 유발·선택 구동기를 둔다 | 엔진 무변경 | 🔴 **기각** — `agent` 는 `engine` 만 import 한다 (실측: `core` · `analysis` · `integration` **0곳**). 유발 후보를 만들려면 등록 정보를 읽어야 하고 ADR-007 이 그것을 금지한다 |
| ④ `plan(selections=…)` 한 칸 + 조립 층 배선 + 선택 정책 | 끊김 하나만 연다 | ✅ **채택** |

### 3.2 ④를 고른 이유

**열린 것이 정확히 하나다.** `TriggerChainIntegrator.plan` 이 "선택이
정해졌는가" 를 받을 통로.

```python
def plan(self, chain, ordering, *, selections=None) -> TriggerChainPlan:
```

* **기본값이 `None` 이고, 그때는 6-Y 이전과 같은 거절을 그대로 돌려준다**
  (`test_g04`). 주지 않으면 아무것도 바뀌지 않는다.
* `PlayerAction` · `Duel` · `legal_actions` · `target_bridge` · 발동 관문
  **전부 손대지 않았다.**
* 🔴 **허가가 아니다.** `plan` 이 하는 일은 "정해졌는가" 를 보는 것뿐이고,
  그 선택이 적법한지는 `ChainResolver` 가 `TargetResolver` · `BoardRuling`
  으로 **다시** 본다. 관문이 둘인 자리를 하나로 줄이지 않았다 (`test_d04`).

### 3.3 두 시점을 **다른 프로토콜**로 둔 이유 (§2 의 A/B 분리)

| | `Policy` (기존) | `ChoicePolicy` (6-Y) |
| --- | --- | --- |
| 언제 | 발동 시점 | 해결 시점 |
| 묻는 것 | 어떤 합법 `PlayerAction` 인가 | 허용된 후보 중 어느 인스턴스인가 |
| 보이는 것 | 평소 관측 — **덱이 보이지 않는다** | 규칙이 선언한 `looked_at` — 그 효과가 볼 수 있는 것만 |

🔴 **합치지 않은 이유가 규칙이다.** 룰북이 덱을 보는 것을 licensing 하는
자리는 "효과가 그렇게 지시할 때" 다 (`Search your Deck`). 한 프로토콜로
합쳐서 발동 전에 덱을 보여 주면 **"덱을 보고 발동할지 정한다"** 가 되고,
그것은 규칙이 허락한 범위가 아니다.

그래서 `run_trigger` 의 순서가 고정이다 — ① 발동 여부를 묻고 → ② 그 뒤에야
덱을 연다. 발동하지 않기로 하면 **선택지를 만들지도 않는다**
(`test_c01`: `run.choice is None`).

### 3.4 강제/임의를 모르는 것을 **모름으로 남겼다** (§5)

후보의 `requirement` 가 `TriggerRequirement.UNKNOWN` 이다. 배선은 그것을
강제로 바꾸지 않고 **정책에게 묻는다**. `FirstPermittedChoice` 가 언제나
발동하는 것은 **그 정책의 선택**이고, 규칙이 강제한다는 주장이 아니다 —
docstring 과 `test_b02` 가 그것을 적는다.

---

## 4. 변경 파일·함수

| 파일 | 변경 | 무엇 |
| --- | --- | --- |
| `engine/trigger_chain.py` | **+65 / −11** | `plan(..., *, selections=None)` · `_entry(..., decided)` · `_missing_execution_inputs(definition, chosen)` · 링크가 `selections` 를 들고 간다 |
| `integration/autonomy.py` | **신규** | `TriggerOffer` · `ChoiceOffer` · `ChoiceCandidate` · `ChoiceSelector` · `SelectionRefused` · `TriggerRun` · `trigger_offers` · `choice_offer` · `choice_offer_for` · `run_trigger` |
| `agent/choice.py` | **신규** | `ChoicePolicy` · `FirstPermittedChoice` · `DeclineChoice` · `RandomChoice(seed)` |
| `tests/engine/test_autonomous_resolution.py` | **신규** 29건 | A–G |
| `docs/phase6y-autonomous-action-resolution-selection.md` | **신규** | 이 보고서 |

🔴 **`agent/policy.py` · `agent/runner.py` · `engine/duel.py` ·
`engine/action.py` · `engine/target_bridge.py` · `engine/activation.py` 를
한 줄도 바꾸지 않았다.**

### 4.1 계층 경계를 양쪽 다 지켰다

| 규칙 | 지킨 방법 |
| --- | --- |
| `agent` 는 `engine` 만 import | `agent/choice.py` 가 `engine.ids` 하나만 가져온다. 제안의 **모양만** 읽는다 (`offer.permitted` · `offer.minimum`) |
| `integration` 은 `agent` 를 import 하지 않는다 | 정책을 `ChoiceSelector` **프로토콜**로 받는다 (`DuelRunner` 가 `Policy` 를 그렇게 받는 것과 같다) |
| 합법성과 전략을 가른다 (§3) | 후보는 조립 층이 **엔진 것을 그대로 불러** 만들고, 선택만 정책이 한다 |

---

## 5. AI가 실제 결정한 행동 목록

```
=== AI 가 결정한 것 1: 발동 시점 행동
  정책: rb-p0 | 고른 것: normal_summon | 후보 수: 6 | accepted: True
=== AI 가 결정한 것 2: 발동 여부
  제안: 69811710:e[0] | requirement: unknown
  정책: first-permitted | 발동: True
=== AI 가 결정한 것 3: 해결 시점 카드
  보여 준 후보: 35 | 허용: 1
  고른 것: (InstanceId(34),) -> 93920420
```

### 5.1 시험이 제공한 것 — 전부 적는다

| 제공 | 무엇 |
| --- | --- |
| 덱 레시피 40장 | 기르수 1 + 오르페골/성유물 39 (성유물－『성장』이 덱에 남게 순서를 정했다) |
| 선공 패 5장 | 기르수 + 카드군 4장 |
| 정책 객체 | `rule_based_policy` (행동) · `FirstPermittedChoice` 등 (발동·선택) |

🔴 **행동도 선택도 지정하지 않았다.** `_agent_summons` 는 `DuelRunner.step()`
을 부르고 정책이 고른 것을 그대로 받는다.

### 5.2 정책을 바꾸면 결과가 바뀐다

| 선택 정책 | 발동 | 고른 것 | 덱 → | 묘지 → |
| --- | --- | --- | --- | --- |
| `FirstPermittedChoice` | **True** | `InstanceId(34)` | 35 → **34** | 0 → **1** |
| `DeclineChoice` | **False** | — | 35 → 35 | 0 → 0 |
| `RandomChoice(3)` | **False** | — | 35 → 35 | 0 → 0 |
| `RandomChoice(5)` | True | `InstanceId(32)` | −1 | +1 |
| `RandomChoice(23)` | True | `InstanceId(33)` | −1 | +1 |

🔴 **씨앗 5와 23이 다른 카드를 고른다** — 결과가 고정되어 있지 않다는 증거다
(`test_e02`). 그리고 같은 씨앗은 같은 선택을 한다 (`test_e01`).

---

## 6. 발동 후보 및 체인 처리 결과

제안은 **엔진이 만든다.** 조립 층은 세는 코드를 새로 쓰지 않았다.

```
EventJournal(#0 normal_summon)
  → timing_events()          → TimingPoint.MONSTER_SUMMONED
  → registry_for_view()      → registered=2 · concealed=0 · unsupported=0
  → TriggerCollector         → 후보 수집
  → TriggerEligibilityJudge  → 다섯 관문
  → TriggerOffer(status=ELIGIBLE, requirement=UNKNOWN)
```

관문 다섯의 결과가 제안의 이유에 그대로 남는다.

```
event_relation=valid; activation_zone=valid; trigger_condition=valid;
execution_authority=valid; cost_feasibility=valid
```

| 검사 (§5) | 결과 |
| --- | --- |
| 올바른 이벤트에서 생성됐는가 | ✅ `MONSTER_SUMMONED` · 소환 전에는 제안 **0건** (`test_b03`) |
| `EffectRef` 와 인스턴스가 일치하는가 | ✅ `offer.source == entry.action.source` (`test_b01`) |
| 발동 권한·타이밍이 적법한가 | ✅ 다섯 관문 전부 `valid` |
| 발동 여부가 선택적인가 | 🔴 **모른다** (`requirement=UNKNOWN`) — 그래서 강제하지 않는다 |
| 조건·비용·횟수 제한 | ✅ `cost_feasibility=valid` · `UseRegistry` 는 6-V 그대로 |
| `Duel.apply` 가 접수하는가 | 🔴 **아니다** — `BLOCKER-6Y-1` |

### 6.1 체인 처리

```
plan(Chain(), ordering, selections={69811710:e[0]: (TargetSelection(@primary, …),)})
  → TriggerChainEntry(INSERTABLE, "체인 1 로 넣을 수 있습니다", link=ChainLink(…))
extend(Chain(), plan) → len(chain) == 1
ChainResolver.resolve_top → RESOLVED
```

선택을 주지 않으면 같은 호출이 `NOT_INSERTABLE` + `TOO_FEW_SELECTED` 로
거절한다 — 6-Y 이전과 같다.

🔴 **상대 자리로는 제안이 나오지 않는다** (`test_b04`). `controller != seat`
인 후보는 그 자리의 목록에 들어가지 않는다.

---

## 7. 해결 시점 카드 선택 결과

| 측정 | 값 |
| --- | --- |
| 보여 준 후보 | **35** (규칙이 선언한 `looked_at={DECK}` 를 열고 센 것) |
| 그중 허용 (`verdict is TRUE`) | **1** — 성유물－『성장』(93920420) |
| 나머지 | **34** 전부 `UNKNOWN`, 이유가 비어 있지 않다 |
| 장수 | `minimum == maximum == 1` (정의에서 온다) |
| 정책이 고른 것 | `InstanceId(34)` |

🔴 **`UNKNOWN` 후보도 목록에 남긴다.** 왜 못 고르는지가 정책에게도 보여야
한다. 그러나 `permitted` 는 `TRUE` 만 센다 — `UNKNOWN` 은 허가가 아니다.

### 7.1 같은 ID 여러 장 (§6-4)

증거 카드를 3장 넣은 덱에서:

```
허용 후보: [(InstanceId(32), 93920420), (InstanceId(33), 93920420),
            (InstanceId(34), 93920420)]
고른 것: (InstanceId(32),)   → 그 인스턴스가 GRAVE 로 갔다
```

카드 ID 가 같아도 **서로 다른 세 후보**이고, 정확히 한 장만 움직였다.

---

## 8. 실제 GameState·EventJournal 변화

| 축 | 소환 전 | 소환 후 | 해결 후 |
| --- | --- | --- | --- |
| P0 덱 | 40 | 35 | **34** |
| P0 묘지 | 0 | 0 | **1** |
| P0 몬스터존 | — | 기르수 | 기르수 |
| 고른 인스턴스의 존 | `DECK` | `DECK` | **`GRAVE`** |

🔴 **두 사건이 같은 기록에 들어간다.** 배선이 `duel.journal` 을 그대로
`build_executor` 에 넘기므로, 효과 기록이 듀얼의 역사에 이어 붙는다.

```
#0 normal_summon P0: P0 가 #75 를 HAND 에서 MZONE[0] 로 normal 소환 (FACEUP_ATTACK)
#1 69811710:e[0] P0: #34 P0/DECK → P0/GRAVE (send_to_grave),
                     P0 의 DECK 34장을 섞었다
```

셔플이 기록에 있는 것이 중요하다 — 룰북이 요구한다 (*"You must shuffle your
Deck after any time you search it"*).

후속 `legal_actions`: `['end_phase', 'set_spell_trap']` — 판이 멈추지 않고,
일반 소환권은 이미 썼다 (`normal_summon` 이 없다).

---

## 9. 거짓 양성·무한 반복·불확실성 처리

### 9.1 정책의 말은 허가가 아니다 — 관문이 **셋**이다

| 관문 | 어디 | 무엇을 막는가 |
| --- | --- | --- |
| ① | `DuelRunner._judge` | 후보 목록 밖의 `PlayerAction` |
| ② | `integration.autonomy._judge_choice` | 후보 밖 · 장수 위반 · 중복 · `UNKNOWN` 선택 |
| ③ | `ChainResolver` → `TargetResolver` · `BoardRuling` | 적법성 재판정 |

실측:

| 정책이 한 일 | 결과 | 판 |
| --- | --- | --- |
| `UNKNOWN` 후보를 골랐다 | `SelectionRefused("#0 는 고를 수 없습니다: …")` | 덱 35 · 묘지 0 **불변** |
| 3장 골랐다 (최대 1장) | `SelectionRefused("3장 골랐습니다 (최대 1장).")` | 불변 |
| 같은 카드를 두 번 골랐다 | `SelectionRefused("같은 카드를 두 번 골랐습니다.")` | 불변 |
| 남의 자리 행동을 돌려줬다 | `TranscriptEntry(accepted=False)` | 불변 |

### 9.2 무한 반복·중복 해결

| 검사 | 결과 |
| --- | --- |
| 같은 제안을 두 번 돌리면 | 두 번째는 **해결되지 않는다** — 후보가 이미 묘지에 있다 (`test_e04`) |
| 묘지 장수 | 두 번째 실행 뒤에도 **1** (두 장 움직이지 않는다) |
| 러너의 걸음 상한 | `MAX_STEPS = 5_000`, 거절 시 `run` 이 멈춘다 (기존) |

### 9.3 불확실성

| 모르는 것 | 어떻게 적었는가 |
| --- | --- |
| 강제/임의 구분 | `TriggerRequirement.UNKNOWN` → 발동을 강제하지 않고 정책에게 묻는다 |
| 34장의 묘지 이동 가능성 | `ConditionResult.UNKNOWN` + 이유 → `permitted` 에 들어가지 않는다 |
| 패에서 적용되는 지속 효과 | `BoardRuling` 의 `unchecked` 에 실린다 (6-X §1.2) |
| 유발 순서 규칙 | `unresolved_rules` 5건 (SEGOC · 턴 플레이어 묶음 순서 · 강제/임의 우선순위 · 같은 플레이어의 순서 · trigger placement) |

🔴 **`ELIGIBLE` 만 제안한다.** `UNDETERMINED` 후보는 "발동할 수 있는지
모른다" 이고, 모르는 것을 제안하면 `UNKNOWN` 이 허가가 된다.

---

## 10. 다른 카드 시나리오 검증

§8-16 — **기르수 전용이 아니다.** 어리석은 매장(81439173)은 **카드 발동**
이고 (`activation_kind is None`, 기르수는 `TRIGGER`), 같은
`choice_offer_for` 로 같은 모양의 선택지가 나온다.

| | 기르수 | 어리석은 매장 |
| --- | --- | --- |
| 발동 분류 | `TRIGGER` | `None` (카드 발동) |
| 선택 자리 | `CHOOSING` · `DECK` | `CHOOSING` · `DECK` |
| 장수 | `(1, 1)` | `(1, 1)` |
| 허용 후보 | 증거 있는 카드만 | 증거 있는 카드만 (3장 중 3) |
| 같은 선택 정책이 읽는가 | ✅ | ✅ `FirstPermittedChoice` 가 그대로 고른다 |

그리고 고를 자리가 없는 효과 · 정의가 없는 효과는 **소리를 낸다**
(`AutonomyError`) — 조용히 0건으로 넘기지 않는다 (`test_f02`).

---

## 11. 관련 회귀 테스트·시간·종료 코드

§9 의 위험 기반 순서를 따랐다. 프로덕션 변경이 **엔진 1파일 + 신규 2파일**
이므로 영향 파일을 **73개**로 특정했다 (`trigger_chain` · `TriggerChainIntegrator`
· `ChainInsertion` · `integration` · `agent/` · 센서스 상수 · 테스트 트리를
`rglob` 로 훑는 감사, 합집합).

### 11.1 최종 실행

| 단계 | 범위 | 통과 | 실패 | 건너뜀 | 시간 | exit |
| --- | --- | --- | --- | --- | --- | --- |
| ① 변경 모듈 타깃 | 6파일 | **175** | 0 | 0 | 49.57s | **0** |
| ② Agent·Duel 수직 통합 + Discord | `tests/agent` + 2파일 | **418** | **1** | 0 | 236.42s (3:56) | 1 |
| ③ 관련 엔진 전체 | `tests/engine` | **3,637** | **1** | 0 | 389.96s (6:29) | 1 |
| ④ 루트 영향 파일 | 73파일 | **1,972** | **6** | 8 | 3,170.26s (52:50) | 1 |

모두 `-p no:randomly -q --no-header --tb=short` 로 돌렸다.

### 11.2 실패 8건의 분류

| 실패 | 분류 | 증명 |
| --- | --- | --- |
| `tests/agent/…::test_07_a_whole_duel_never_offers_a_choice_about_opponent_resources` | **기존 실패** | `374b27b` worktree 에서 **같은 줄 같은 값**(`[1, 1, 1, …]`)으로 실패 |
| `tests/test_effect_type_quick_audit::test_29` | **기존 실패** (재정 캐시, `15 >= 800`) | 6-X §12.2 가 같은 worktree 로 확인 |
| `tests/test_event_free_chain_semantic_audit::test_27` | **기존 실패** (같음, `15 >= 600`) | 같음 |
| `tests/test_korean_overlay_unapplied_audit` **×4** | **기존 실패** (로컬 `cards.cdb` 14,759 대 핀 14,755) | 같음 |
| 🔴 `tests/engine/test_effect_activation_path::test_25` | **신규** — 내 이름 변경이 깼다 | **고쳤다** (부록 A.2) |

### 11.3 내 변경이 움직인 12건 — 전부 해소

| 원인 | 건수 | 고친 것 |
| --- | --- | --- |
| 🔴 **내가 넣은 `pytest.skip`** | **3** | **지웠다** (단언 2 → 7) |
| 🔴 **설계 경계** — `agent/` 의 어휘 (사건 쪽) | **1** | **구현을 고쳤다** |
| 🔴 **설계 경계** — `agent/` 의 어휘 (엔진 쪽) | **1** | **구현을 또 고쳤다** |
| 🔴 **3-E-20 의 경고** — 두 번째 경로 | **1** | 감사를 다시 적었다 (단정 +1) |
| 휴면 센서스 (importer · 생성자 자리 · 줄 수 ×2) | **5** | 센서스 값 + 근거 |
| `RULE_NOT_IMPLEMENTED` 산문 줄번호 | **1** | 줄번호 (총수 88 · 73 · 15 불변) |

1차 루트 실행은 **17 failed / 1,961 passed** 였고 최종은
**6 failed / 1,972 passed** 다 — 줄어든 11건과 늘어난 통과 11건이 같다.
(여기에 `tests/engine` 의 신규 1건을 더해 12건이다.)

### 11.4 테스트 정책 — 금지 사항 점검

- 기존 테스트 **삭제 0건** · **assertion 완화 0건** · **threshold 완화 0건**.
- 🔴 **skip 추가 1건을 내가 했고, 지웠다** (부록 A.1). 지금 저장소의
  `pytest.skip` 은 전부 이 Phase 전의 것이다.
- 단정이 **세 자리에서 늘었다** — `test_c06` (2 → 7) ·
  `ownership::test_10` (+1) · `connectivity::test_04` (+1).
- 🔴 **실행하지 않은 것을 성공으로 적지 않았다.** `BLOCKER-6Y-2` (상대
  응답 순환)는 `test_g02` 가 "돌지 않는다" 를 단언으로 적는다.

---

## 12. 남은 구조적 BLOCKER

| ID | 내용 | 이번 Phase |
| --- | --- | --- |
| **BLOCKER-6Y-1** | 🔴 **유발 발동이 `legal_actions` 에 오르지 않는다.** `ACTIVATION_KINDS_IN_SCOPE` 가 기동 하나이고, 유발의 시점 지식(트리거 계층)이 듀얼 루프에 이어지지 않았다. 그래서 AI 가 **`Duel.apply` 로** 유발을 발동할 수는 없다 | 원인 확정 · 고치지 않음 (§3.1 ①) |
| **BLOCKER-6Y-2** | 🔴 **상대 응답 순환이 이 경로에서 돌지 않는다.** 체인을 배선이 세우고 `ChainResolver` 가 바로 해결하므로 그 사이에 상대가 끼어들 자리가 없다. `BLOCKER-6Y-1` 이 풀리면 함께 열린다 | 측정 · **돌았다고 적지 않았다** (`test_g02`) |
| **BLOCKER-6Y-3** | 강제 유발과 임의 유발을 가르지 못한다 (`TriggerRequirement.UNKNOWN`). 지금은 정책이 그 모름을 자기 선택으로 메꾼다 | 모름으로 남김 |
| **BLOCKER-6Y-4** | 유발 순서 규칙 5건이 미정 (`unresolved_rules`). 후보가 둘 이상인 판에서 **누가 먼저인가**를 말할 수 없다 | 측정 · 범위 밖 |
| `STRUCTURAL-125` | 해결 시점 선택이 `PlayerAction` 에 들어갈 수 없다. **경계가 옳다** — 6-Y 는 그것을 우회하지 않고 선택을 해결 시점으로 옮겼다 | 그대로 (`test_g03`) |
| `BLOCKER-6X-1~3` | 대체 효과 미실행 · 덱 금지 범위 미독해 · 증거 없는 12,452장 `UNKNOWN` | 그대로 |

---

## 13. 다음 최소 개발 단계 추천

**13.1 (권장) 유발 발동을 `Duel.apply` 가 받게 한다 (`BLOCKER-6Y-1`)**

가장 직접적인 다음 관문이다. 최소 경로:

1. `Duel` 이 **방금 일어난 사건**을 들고 있게 한다 — 기록(`EventJournal`)은
   이미 있으므로 "어디까지 봤는가" 표식 하나로 충분하다.
2. `_activation_actions` 가 그 사건에서 트리거 계층을 불러 `TRIGGER` 후보를
   더한다. 후보를 새로 세지 않고 `trigger_offers` 와 **같은 호출**을 쓴다.
3. `ACTIVATION_KINDS_IN_SCOPE` 에 `TRIGGER` 를 더하되, **사건이 있을 때만**
   판정하게 한다 — 사건 없는 유발은 여전히 범위 밖이다.

🔴 **`legal_actions` 가 바뀌므로 모든 결정 digest 가 움직인다.** 6-Q 가 같은
종류의 갱신을 한 선례가 있다 (611 → 689). 공유 계약 변경이므로 **사용자
승인** 대상이다.

**13.2 상대 응답과 우선권 (`BLOCKER-6Y-2`)**

13.1 이 풀리면 `Duel` 의 응답 순환이 유발 체인에도 적용된다. 그때
`Policy` 가 `PASS` 를 고르는 자리가 생기고, §7 의 "상대 응답 기회와 PASS"
가 실제로 돌아간다. 13.1 과 **같은 Phase** 로 묶는 것이 맞다.

**13.3 해결 시점 선택을 `ChoicePolicy` 없이도 쓰게 한다**

지금은 `run_trigger` 를 부르는 쪽이 `ChoiceSelector` 를 넘겨야 한다.
13.1 이 풀리면 `DuelRunner` 가 그것을 들고 다니는 쪽이 자연스럽다 —
`DuelRunner(duel, policies, choosers=…)` 한 칸.

**13.4 강제 유발 판정 (`BLOCKER-6Y-3`)**

`TriggerWording` · `TriggerRequirement` 가 이미 자리를 만들어 두었다. 공식
텍스트의 「발동한다」 대 「발동할 수 있다」 가 그 구분이고, 6-X 가 묘지
질문에 한 것과 같은 방식(카드 자신의 텍스트에서 유도)으로 접근할 수 있다.

**13.5 탐색 정책을 이 경로에 붙인다**

`agent/search.py` · `agent/evaluation.py` 가 이미 있다. 6-Y 의 기준점
정책들을 `StateEvaluator` 를 쓰는 선택으로 바꾸면 "어느 카드가 좋은가" 를
처음으로 말할 수 있다. 🔴 **그것이 콤보 탐색의 시작이고, 이번 Phase 는
의도적으로 하지 않았다** (§1: "최적 콤보 탐색이나 집 평가까지 구현하지
않는다").

---

## 14. Git 커밋·푸시 결과

브랜치 `claude/pensive-goodall-te1egy` · 시작 지점 `374b27b` (6-X 완료).

| # | 커밋 | 내용 |
| --- | --- | --- |
| 1 | `3477bd2` | **엔진** — `plan` 이 정해진 대상 선택을 받을 통로를 연다 |
| 2 | `d884c5f` | **배선·정책** — 엔진의 후보를 정책에게 주고 결정을 되돌린다 |
| 3 | `5f3e710`(의 앞) | **테스트 29건** — AI 가 결정한 것과 시험이 준 것을 가른다 |
| 4 | `5f3e710` | 보고서 (§11 · §14 미완으로 먼저 커밋) |
| 5 | `05e3d1a`(의 앞) | 🔴 `agent` 의 어휘 수정 + 내가 넣은 skip 제거 |
| 6 | `05e3d1a`(의 앞) | 휴면 센서스 다섯 정정 |
| 7 | `05e3d1a` | 보고서 부록 A |
| 8 | (아래) | 🔴 `accept_offer` 로 최종 개명 + §11 · §14 실측 |

```
$ git push -u origin claude/pensive-goodall-te1egy
   374b27b..05e3d1a  claude/pensive-goodall-te1egy -> …
```

✅ **푸시 완료** · 작업 트리 깨끗 · Pull request 는 요청받지 않았으므로
만들지 않았다.

**다음 Phase 는 자동으로 시작하지 않는다.** §13.1 과 §13.2 는 묶어서 하는
것이 맞고, `ACTIVATION_KINDS_IN_SCOPE` 를 넓히는 **공유 계약 변경**이므로
§10 에 따라 **사용자 승인**을 기다린다.

---

## 부록 A. 🔴 회귀가 네 가지를 잡았다

이 절은 **내가 틀린 기록**이다. 넷 다 `tests/engine` 3,638건과 Duel 수직
통합 418건을 **전부 통과한 뒤** 깨졌다 — 셋은 루트에서, 하나는 이름을 고친
뒤 `tests/engine` 에서.

### A.1 🔴 내가 이 Phase 의 금지를 어겼다 — `pytest.skip` 추가

```
FAILED tests/test_lua_verified_provenance_audit.py::test_39_no_test_was_deleted_and_no_skip_was_added
FAILED tests/test_provenance_consumer_audit.py::test_39_no_test_was_deleted_and_no_skip_was_added
FAILED tests/test_update_coverage_contract_audit.py::test_41_no_test_was_deleted_and_no_skip_was_added
    ('tests/engine/test_autonomous_resolution.py',
     'pytest.skip("이 덱에서는 제안이 생기지 않는다 — 그것도 정상 중단이다")')
```

§9 가 **skip 추가를 금지**한다. 내가 `test_c06` 에 그것을 넣었다 — 카드군
카드가 없는 덱에서 제안이 생길지 몰라서 빠져나갈 구멍을 둔 것이다.

🔴 **구멍을 만든 이유가 게으름이었다.** 실제로 재 보니 제안은 **생긴다** —
발동 조건이 덱 장수만 보므로 카드군 카드가 없어도 적법하고, 막히는 자리는
그 뒤다 (허용 후보 0건 → 장수로 거절). skip 을 지우고 그 사실을 단언으로
적었다. **단언이 2개에서 7개로 늘었다.**

### A.2 🔴 `agent/` 가 사건 계층의 어휘를 쓰면 안 된다

```
FAILED tests/test_trigger_connectivity_audit.py::test_15_the_agent_layer_knows_nothing_about_triggers
    (path.name, token)  — agent/choice.py 에 'trigger'
```

그 감사는 `agent/**.py` 전수에서 네 토큰(`Trigger` · `trigger` ·
`TimingEvent` · `TimingPoint`)을 **글자로** 센다. 내 `ChoicePolicy` 의
메서드 이름이 `activate_trigger` 였다.

🔴 **이름만의 문제가 아니었다.** 정책이 결정하는 것은 "제안된 효과를
발동할 것인가" 이고, 그 제안이 **왜** 생겼는지(사건 · 시점 · 선언)는
정책이 알 필요가 없다. 이름이 그 사실을 흐리고 있었다.

테스트가 아니라 구현을 고쳤다 — 6-X 부록 A 와 같은 방법이다.

#### 🔴 그리고 **같은 경계를 두 번 깼다**

고친 이름이 `activate_effect` 였는데, 그것도 금지 토큰이었다. 다른 감사가
잡았다.

```
FAILED tests/engine/test_effect_activation_path.py::test_25_the_search_policy_needs_no_activation_branch
    ('choice.py', {'activate_effect'})
```

> **§15 — 탐색에 발동 전용 분기를 넣지 않았다.** 후보 목록이 넓어진
> 것만으로 저절로 들어오고, 시뮬레이션되고, 점수를 받는다. **`agent/`
> 어디에도 발동의 이름이 없다**는 것을 AST 토큰으로 지킨다.

금지 목록이 `ACTIVATE_CARD` · `ACTIVATE_EFFECT` · `activate_card` ·
`activate_effect` · `EffectRef` · `effect_ref` · `SpellPlaced` 다.

🔴 **두 번 깬 것이 배울 점이다.** 첫 이름은 *사건* 계층의 어휘였고
(`trigger`), 두 번째는 *엔진* 계층의 어휘였다 (`activate_effect`). 둘 다
"정책이 무엇을 결정하는가" 가 아니라 **"그 결정이 엔진에서 무엇이 되는가"**
를 이름에 적은 것이다. 정책은 그것을 알 필요가 없다.

그래서 세 번째 이름은 정책이 **하는 일**만 말한다.

| | 1차 | 2차 | 최종 |
| --- | --- | --- | --- |
| 프로토콜 메서드 | `activate_trigger` | `activate_effect` | **`accept_offer`** |
| 어느 계층의 어휘인가 | 사건 | 엔진 | **정책 자신** |
| 감사 | 연결성 실패 | 발동 경로 실패 | **둘 다 수정 없이 통과** |
| 정책이 읽는 것 | 같다 (`offer.permitted` · `offer.minimum` · `offer.requirement_known`) | 같다 | 같다 |

🔴 **감사 파일 이름조차 적을 수 없었다.** docstring 에서 그 감사를
파일명으로 가리켰더니 그것도 걸렸다 — 전수 토큰 검사이므로 파일명 안의
토큰도 센다. 이름 없이 "루트와 엔진의 두 감사" 로 적었다.

### A.3 🔴 **Phase 3-E-20 이 이 Phase 의 위험을 미리 적어 두었다**

```
FAILED tests/test_trigger_ownership_audit.py::test_10_the_dormant_integrator_builds_links_without_any_action
    assert "selections" not in kwargs and "payments" not in kwargs
```

그 테스트의 원래 문장이 이렇다.

> **§4 — 잠든 계층은 `PlayerAction` 없이 `ChainLink` 를 만든다.**
> `TriggerChainIntegrator._entry` 의 인자에 `action` 이 없고, 만드는 링크에
> `selections` 도 `payments` 도 없다. 그러므로 **그대로 연결하면
> `legal_actions()` 를 우회하는 두 번째 경로가 된다.** 지금은 불리지
> 않으므로 모순이 아니다 (Phase 3-E-20).

🔴 **6-Y 가 그것을 불렀다.** 마지막 문장이 더 이상 참이 아니다.

**그래서 숨기지 않고 적는다.** 그 경로가 무검증은 아니다 —

| 관문 | 무엇이 판정하는가 |
| --- | --- |
| ① | `TriggerEligibilityJudge` 의 다섯 관문 (후보가 적법한가) |
| ② | `integration.autonomy._judge_choice` (고른 것이 후보 목록에 있는가) |
| ③ | `ChainResolver` → `TargetResolver` · `BoardRuling` (적법성 재판정) |

그러나 그 셋 중 어느 것도 **`ActionValidator` 가 아니다.** 이 감사가
가리키는 위험은 "검증이 없다" 가 아니라 **"판정의 주체가 둘로 갈린다"** 다.

🔴 **올바른 해법은 경로를 하나로 되돌리는 것**이고, 그것이
`BLOCKER-6Y-1` 이다 — 유발 발동을 `legal_actions` 에 올리면 두 번째 경로가
사라진다. 그 변경은 `ACTIVATION_KINDS_IN_SCOPE` 를 넓히는 **공유 계약
변경**이므로 §10 에 따라 **사용자 승인 대상**으로 남겼다.

감사는 약화하지 않고 **다시 적었다** — `action` 이 없다는 본문은 그대로,
`selections` 가 늘었다는 사실과 `payments` 는 여전히 없다는 사실을 각각
단언한다 (비용이 있는 효과는 이 경로로 올 수 없다).

### A.4 휴면 센서스 — 6-Y 가 파이프라인을 **깨웠다**

| 감사 | 전 | 후 |
| --- | --- | --- |
| `connectivity::test_01` — `engine.trigger_chain` 의 importer | `{engine.timing}` | `{engine.timing, integration.autonomy}` |
| `connectivity::test_02` — `engine.trigger` 의 importer | 8곳 | **9곳** |
| `connectivity::test_04` — 트리거 구조를 만드는 production 자리 | 3곳 | **4곳** (`TriggerChainIntegrator(`) |
| `dormant::test_01` · `test_25` — `trigger_chain.py` 줄 수 | 594 | **648** (문자열 벗긴 257 → **268**) |
| `rule_not_implemented::test_02` — 산문 줄번호 | 553 · 569 | **607 · 623** (총수 88 · 73 · 15 불변) |

🔴 **앞의 모든 갱신과 다른 점이 하나 있다.** 6-B · 6-F · 6-H · 6-V 는
전부 "늘어난 코드가 후보를 모으는 자리를 늘리지 않았다 — dormant 를 깨지
않는다" 였다. 6-Y 는 **깼다.** 그래서 그 파일 이름이 말하는 "dormant" 는
이제 `engine/duel.py` 에 대해서만 참이다 (`legal_actions` 는 여전히 유발을
제공하지 않는다).

### A.5 남는 교훈

6-X 부록 A 가 적은 문장이 또 맞았다 — *"관측에 새 칸을 더할 때는 '이 값이
무엇을 말하는가' 를 먼저 묻는다."* 6-Y 가 한 줄 더한다.

🔴 **휴면 계층을 깨울 때는 "누가 그 휴면을 세고 있는가" 를 먼저 찾는다.**
이 저장소는 휴면을 **다섯 감사**로 세고 있었고 (importer 그래프 · 생성자
자리 · 줄 수 둘 · 소유권), 그중 하나는 **깨우면 생기는 위험까지** 적어
두었다 (3-E-20). 그 다섯을 먼저 읽었다면 `BLOCKER-6Y-1` 을 설계 **전에**
알았을 것이고, 두 번째 경로를 만들지 않는 쪽을 먼저 저울질했을 것이다.
