# Phase 3-F-1 — AI Evaluation Core: Feature / State Evaluation Foundation

## 1. Phase / Base / 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-F-1 — AI Evaluation Core |
| 성격 | **AUDIT-ONLY** (production 수정 0줄) |
| Base Phase | 3-E-45 — `_event_relation` 최소 판정 수정 |
| Base commit | `077e44a` (보고서) · `7fd50b6` (결과) |
| Base baseline | 4,099 passed / 4 skipped |

**실제 HEAD 확인 (작업 시작 전)**

```
$ git rev-parse HEAD
077e44a476f8110a7016b709351f36a6a00e8ae2
$ git rev-parse --abbrev-ref HEAD
claude/pensive-goodall-te1egy
$ git status --short      → (비어 있음)
```

3-E-45 산출물도 그 자리에 있다 — `docs/phase3e45-event-relation-minimal-fix.md`
(27,635 B) · `tests/test_event_relation_minimal_fix.py` (26,357 B).
Engine V1 freeze 를 유지한다.

---

## 2. 기존 evaluation 구조 조사 결과

### 2-1. **Evaluation Core 가 이미 있다**

조사의 첫 결론이 이 Phase 전체를 결정했다. `agent/evaluation.py` 가 **661줄**로
이미 존재하고, Phase 가 목표로 적은 구조를 **그대로** 구현하고 있다.

```
GameStateView  →  Evaluation Features  →  Evaluation Score  →  Search 가 소비
   (관측만)         StateValue.terms        StateValue.heuristic    SearchPolicy
```

Phase 3-C 에서 만들어졌고 3-E-6 · 3-E-7 · 3-E-8 이 세 번 다듬었다.

| 조사 항목 | 실측 결과 |
| --- | --- |
| 1. 현재 Search 구현 | `agent/search.py` (381줄) · `SearchPolicy`, 깊이 1 (`SUPPORTED_DEPTH`) |
| 2. `SimulationResult` | `agent/simulation.py` — `action`/`status`/`viewer`/`reason`/`code`/`future` |
| 3. `SearchCandidate` | `agent/search.py` — `action`/`status`/`value`/`reason`, `value: StateValue \| None` |
| 4. `SearchResult` | **없다.** 그 이름의 타입은 존재하지 않고 `SearchDecision` 이 결정 하나를 든다 |
| 5. `GameStateView` | 공개 표면 21개. `legal_actions`·`chain`·`priority` **없음** |
| 6. 기존 evaluation 코드 | `agent/evaluation.py` — `Terminal`·`StateValue`·`Evaluator`·`StateEvaluator`·`ExclusionCategory`·`Exclusion` |
| 7. `RuleBasedPolicy` | `agent/heuristic.py` — `agent.evaluation` 을 **import 하지 않는다** |
| 8. 3-C 의 score/value 구조 | `StateValue(terminal, heuristic, terms, excluded)` + `ordering_key()` |
| 9. AI 가 후보를 비교하는 값 | `SearchCandidate.ordering_key()` → `StateValue.ordering_key()` = `(terminal.rank, heuristic)` |
| 10. 이미 있는 abstraction | **있다** (위 6번) — 그래서 새로 만들지 않았다 |

### 2-2. 이름이 닮은 **두 abstraction 은 다른 것**이다

중복 abstraction 을 피하려면 이 구분이 먼저다.

| | 무엇을 채점하는가 | 소비자 |
| --- | --- | --- |
| `agent.heuristic.Evaluation` | **행동** 하나 (`action` 필드) | `RuleBasedPolicy` |
| `agent.evaluation.StateValue` | **상태** 하나 (`terminal` 등급) | `SearchPolicy` |

필드 집합이 거의 서로소다 (`test_02`). 합치면 "이 수가 좋다" 와 "이 판이 좋다"
가 한 숫자가 되므로 합치지 않는다. Phase 가 말한 Evaluation Core 는 **후자**다.

### 2-3. 결론 — 새 클래스를 만들지 않았다

Phase §2 가 적은 그대로다: "새로운 Evaluation 클래스를 만들기 전에 기존 구조에
이미 같은 역할의 코드가 있는지 확인한다. 중복 abstraction 을 만들지 않는다."
있었다. 그래서 만들지 않았다.

---

## 3. Evaluation Core 설계 (기존 설계의 기록)

```
Simulation State → GameStateView(viewer) → StateValue
```

핵심 설계 결정 넷은 전부 이미 내려져 있고 근거가 모듈 docstring 에 적혀 있다.

1. **끝난 판은 숫자가 아니라 등급이다.** 승리를 "매우 큰 수" 로 적으면 휴리스틱
   항이 자랄 때 조용히 추월당하고, 그때 AI 가 이기는 수를 버린다. 그래서
   비교가 `(등급, 휴리스틱)` 사전식이고 등급이 다르면 휴리스틱을 **보지 않는다.**
2. **모든 항의 단위가 LP 하나다.** "왜 100 인가" 에 답할 수 있게 하려는 것이고,
   각 가중치는 "이것을 얻으려 LP 를 얼마까지 내줄 것인가" 로 적혀 있다.
3. **모르는 것을 0 으로 바꾸지 않는다.** 합에서 빼고 `excluded` 에 적는다.
4. **관측만 받는다.** `GameState` 를 넘기면 상대 패와 덱이 그대로 보인다.

---

## 4. Feature 목록

Phase §3 이 요구한 범주 A–G 와 실제 구현의 대응이다.

| | Phase 요구 | 실제 | 상태 |
| --- | --- | --- | --- |
| **A** | Game Outcome | `Terminal` — `WIN`/`ONGOING`/`DRAW`/`LOSS` (항이 아니라 **등급**) | **구현됨** |
| **B** | Board State | `atk` · `monsters` · `spells` | **구현됨** |
| **C** | Resource | `deck` · `hand` (내 쪽만). 묘지·제외·필드존·펜듈럼존·엑스트라덱은 `DESIGNED_OUT` | **부분 구현** |
| **D** | Interaction | — | **DEFERRED** (§7) |
| **E** | Follow-up | — | **DEFERRED** (§7) |
| **F** | Life Point | `lp`, 그리고 **단위 자체가 LP** | **구현됨** |
| **G** | Information | `ExclusionCategory` 세 범주 + `partial` | **구현됨** |

항의 이름은 **정확히 여섯**이고 순서까지 고정이다 (`test_04`):

```python
("lp", "atk", "monsters", "spells", "deck", "hand")
heuristic = sum(값)          # 숨은 항이 없다
ordering_key() = (terminal.rank, heuristic)
```

### A — Game Outcome 의 등급 순서

```
WIN(2)  >  ONGOING(1)  >  DRAW(0)  >  LOSS(-1)
```

`DRAW` 가 `ONGOING` 보다 **아래**인 이유: 진행 중인 판은 아직 이길 수 있고,
무승부는 더 이상 이길 수 없다. `is_over` 인데 `winner` 가 없으면 `DRAW` 이고,
그런 결과를 만드는 자리가 지금 엔진에 없어도(측정 0회) 조용히 승/패로 바꾸지
않는다.

끝난 판은 `terms == ()` · `heuristic == 0` · `excluded == ()` 다 (`test_16`) —
등급이 이미 모든 것을 말하고, 끝난 판의 자원은 의미가 없다.

### G — Information 의 세 범주

| 범주 | 뜻 | `partial` 에 드는가 |
| --- | --- | --- |
| `DESIGNED_OUT` | 값이 보이는데 **항으로 두지 않기로 했다** (묘지·제외존·뒷면 몬스터의 공격력) | 아니다 |
| `UNKNOWN` | **다 보이는데 숫자가 없다** (공격력이 `?`) | **그렇다** |
| `WITHHELD` | **합법적으로 볼 수 없다** (상대 뒷면 정체·상대 패 내용) | 아니다 |

`partial = any(category is UNKNOWN)`. `bool(excluded)` 로 두면 깃발이 거의 언제나
참이 되어 (실측 99.6%) 아무것도 알려주지 않는다.

---

## 5. 각 feature 의 의미 / 단위

단위는 **전부 LP** 다. 가중치는 다섯이고 이 Phase 는 하나도 바꾸지 않았다
(`test_07`).

| feature | 식 | 가중치 | 단위 근거 |
| --- | --- | --- | --- |
| `lp` | `me.lp − opp.lp` | 1 (환산 없음) | LP 그 자체 |
| `atk` | `(내 공격력 합 − 상대 공격력 합) × 1` | `ATK_IN_LP = 1` | **환산이 필요 없다** — 공격력은 그대로 LP 로 들어오는 피해이므로 1:1 |
| `monsters` | `(내 몬스터 수 − 상대 몬스터 수) × 500` | `MONSTER_IN_LP = 500` | 공격력이 같아도 몬스터가 하나 더 있는 쪽이 낫다 (한 번 더 때리고 한 번 더 막는다) |
| `spells` | `(내 마법함정 수 − 상대 마법함정 수) × 300` | `SPELL_TRAP_IN_LP = 300` | 몬스터보다 낮다 — 지금 엔진에서 **발동이 후보에 오르지 않으므로** "놓여 있다는 사실" 의 값만 센다 |
| `deck` | `(내 덱 − 상대 덱) × 300` | `DECK_CARD_IN_LP = 300` | **자원 중 가장 무겁다** — 지금 도달 가능한 패배 조건이 덱아웃 하나이므로 덱의 한 장은 패배로부터의 거리 1 |
| `hand` | `내 패 × 200` | `HAND_CARD_IN_LP = 200` | 아직 쓸 수 없는 자원이므로 덱보다 가볍다. **상대 패는 세지 않는다** |

`GRAVE_IS_COUNTED = False` — 묘지는 공개 정보지만 되살릴 수단이 후보에 오르지
않으므로 값을 **0 으로 두지 않고 세지 않는다**(= `DESIGNED_OUT` 으로 적는다).

**`hand` 만 차가 아니다.** 나머지 다섯은 `me − opponent` 이고, 두 자리에서 본
값의 차 항은 부호만 뒤집힌다 (`test_08`). 이 사실이 §13 의 결론으로 이어진다.

---

## 6. 구현된 feature

A · B · F · G 는 완전히, C 는 부분적으로 구현되어 있다. 이 Phase 는 **하나도
더하지 않았다** — 더할 것이 없었다.

실측 예 (ATK 1900 몬스터 둘, 양쪽 대칭, 내 패 3장):

```
terms = {lp: 0, atk: 3800, monsters: 1000, spells: 0, deck: 0, hand: 600}
heuristic = 5400 · terminal = ONGOING
```

경계값도 확인했다 — 빈 필드 · 빈 패 · 양쪽 덱 1장이면 여섯 항이 전부 0 이고
`excluded` 가 비며 `partial` 이 거짓이다.

---

## 7. DEFERRED / UNKNOWN feature

**둘 다 가중치 문제가 아니라 입력 문제다.** 그래서 억지로 계산하지 않았다.

### D — Interaction (상대 턴 개입 수단) → **DEFERRED**

"상대 턴에 개입할 수 있는 수단이 몇 개인가" 를 세려면 세트된 카드가 **유발
조건이 있는 함정인지** 알아야 한다. 엔진은 그것을 구분하지 못한다:

> `trap-activation-timing (함정의 유발 조건을 효과마다 구분할 수 없다 — 공식
> 스크립트의 SetCode(EVENT_*) 가 EffectDefinition 에 없다)`

그래서 지금 셀 수 있는 것은 **마법·함정 존의 장수**뿐이고 그것이 `spells` 항이다.
**장수와 interaction capability 를 혼동하지 않는다** — `spells` 의 가중치 주석이
"놓여 있다는 사실 자체의 값만 센다" 라고 적는다 (`test_06`).

### E — Follow-up (다음 행동 가능성) → **DEFERRED**

평가가 받는 것은 `GameStateView` 뿐이고, 거기에는 `legal_actions` · `chain` ·
`priority` 가 **없다**. 체인과 우선권은 `GameState` 밖에 산다 (ADR-007).

억지로 세려면 평가가 `Duel` 을 받아야 하고, 그러면 §4 의 순수 읽기 구조가
깨진다. `StateEvaluator.evaluate(self, view)` 의 인수가 둘뿐인 것이 그 경계다
(`test_05`).

### C 안에서 세지 않는 자리 다섯

묘지 · 제외 존 · 필드 존 · 펜듈럼 존 · 엑스트라 덱. 전부 `DESIGNED_OUT` 으로
**적혀 있다** — 적지 않으면 `partial` 이 거짓으로 "다 셌다" 고 말한다
(STRUCTURAL-130 이 그 거짓이었다).

---

## 8. 초기 weight baseline

§5 의 금지를 모두 지켰다 — **가중치 최적화 · 머신러닝 · self-play · neural
network · MCTS · 강화학습 전부 하지 않았다.** 기존 baseline 다섯을 **그대로**
두었다 (§5 표 참조).

Phase 가 예로 든 식과 실제 구조의 대응:

```
Phase 의 예시                        실제
w_board * board_value          →    atk + monsters + spells
w_resource * resource_value    →    deck + hand
w_interaction * ...            →    (DEFERRED)
w_followup * ...               →    (DEFERRED)
w_lp * lp_value                →    lp
terminal_value                 →    terminal (더하지 않고 **등급으로 분리**)
```

**`terminal` 을 더하지 않는 것이 이 설계의 핵심**이고, 그것이 Phase 의 예시 식과
다른 유일한 지점이다. 더하면 휴리스틱이 자랄 때 승리가 추월당한다.

---

## 9. normalization 여부와 이유

**normalization 을 하지 않는다. 필요가 없다 — 단위가 이미 하나다.**

Phase §5 가 "서로 다른 단위의 feature 를 그대로 더하는 경우 normalization 이
필요한지 검토한다" 고 했다. 검토 결과: 여섯 항이 **전부 LP** 로 환산되어
있으므로 그대로 더하는 것이 맞다. 각 가중치가 "LP 로 얼마인가" 의 답이고,
`ATK_IN_LP = 1` 은 환산이 **아니라 등식**이다(공격력은 그대로 들어오는 피해).

단위가 다른 두 양을 섞는 자리가 **하나** 있고, 그것은 더하지 않고 **분리**로
해결했다 — `terminal`(등급, 순서만 있는 양) 과 `heuristic`(LP, 크기가 있는 양).
사전식 비교가 그 둘을 섞지 않는 방법이다.

---

## 10. hidden information 경계

**누출 없음.** 세 겹으로 확인했다.

1. **입력이 관측뿐이다.** `evaluate` 가 `GameStateView` 가 아니면
   `EvaluationError` 를 던진다. (이 보호를 제거하는 고의 위반 8 은 기존 테스트
   `test_01_the_evaluator_receives_only_an_observation` 가 잡았다.)
2. **상대 덱 구성이 점수에 닿지 않는다.** 장수가 같고 카드가 전부 다른 두 판의
   점수가 **같다** (`test_17`).
3. **정체를 읽는 접근자를 쓰지 않는다.** 모듈 전체의 attribute 접근에
   `name` · `card_id` · `definition_for` · `repository` · `setcode` · `text` ·
   `state` · `clone` · `randomness` · `rng` 가 **하나도 없다**. 읽는 정의 항목은
   `atk` · `has_atk` · `atk_is_question` 셋뿐이고 전부 앞면 카드의 공개 정보다
   (`test_12`). 숫자 리터럴에 passcode(8자리) 가 없다.

상대 패는 **장수만 보이고 값은 매기지 않는다** → `WITHHELD` 로 적는다. 그리고
`WITHHELD` 는 `partial` 을 올리지 않는다 — 규칙대로 처리한 결과이고 어떤
평가자도 이보다 잘할 수 없기 때문이다.

**"모른다" 와 "없다" 를 구분한다.** 상대 패 0장이면 `WITHHELD` 항목이 아예 생기지
않고, 1장 이상이면 "상대 패 N장의 값을 모른다" 가 생긴다.

---

## 11. RNG / state mutation 여부

| 질문 | 결과 |
| --- | --- |
| `GameState` 를 mutate 하는가 | **아니다.** 30회 평가 전후 `state_hash` 동일 |
| RNG 를 소비하는가 | **아니다.** `state.rng.getstate()` 전후 동일 |
| 같은 state → 같은 evaluation | **그렇다.** 30회 전부 동일 객체값 |
| clone 의 평가가 같은가 | **그렇다.** `state_hash` 도 `StateValue` 도 동일 |
| `PlayerAction` 을 실행하는가 | **아니다.** `engine.action` 을 import 하지 않는다 |
| Search 를 호출하는가 | **아니다.** `agent.search` 를 import 하지 않는다 (의존 방향이 반대다) |
| Engine mutation API 를 부르는가 | **아니다.** attribute 접근에 `clone`·`move`·`draw`·`set_result` 가 없다 |

`agent/evaluation.py` 의 import 는 `engine.game_state_view` **하나**뿐이다 —
순수 읽기 구조가 import 수준에서 강제된다.

---

## 12. Search 와의 연결 여부

**§8 의 답: 연결할 것이 없다 — 이미 (A) 로 연결되어 있다.** Phase 3-C 가 그렇게
만들었다.

```python
# agent/search.py
evaluator: Evaluator = field(default_factory=StateEvaluator)   # 주입 지점
...
if not isinstance(self.evaluator, Evaluator):                  # 런타임 검사
    raise SearchError(...)
...
value=self.evaluator.evaluate(result.future)                   # 유일한 호출
```

| 확인 | 결과 |
| --- | --- |
| `SearchPolicy.evaluator` 기본값 | `StateEvaluator` (`default_factory`) |
| `search_policy(duel)` 의 평가자 | `StateEvaluator`, `name="state-evaluator"` |
| 다른 평가자를 주입할 수 있는가 | **그렇다** — `search_policy(duel, evaluator=...)` 가 받는다 (`test_14`) |
| 평가자 없는 객체를 거부하는가 | **그렇다** — `SearchError` (`test_11`) |
| 비교 방법 | `ordering_key()` 하나 — 평가자가 바뀌어도 비교 방법은 안 바뀐다 |

**기존 Search 동작을 깨뜨리지 않았다.** 가중치 다섯 · 항 이름 여섯 · 등급 넷이
그대로이므로 같은 판에서 같은 점수가 나오고, 따라서 deterministic ordering ·
tie-break · `SimulationStatus` · UNKNOWN/REFUSED semantics 가 전부 그대로다
(`test_15`). production diff 가 **0줄**인 것이 그 보증이다.

`RuleBasedPolicy` 는 `agent.evaluation` 을 import 하지 않으므로 애초에 영향권
밖이다 (`test_03`).

---

## 13. 증식의 G 시나리오에서 표현 가능한 정보

**이 Phase 의 가장 중요한 측정 결과다.**

§6 의 질문: *"Evaluation Core 가 '내 필드가 강해졌다' 와 '상대에게 자원을
제공했다' 를 서로 다른 feature 로 표현할 수 있는 구조인가?"*

### 답: **아니다. 그리고 부호가 거꾸로다.**

증식의 G **모양**만 손으로 만들어 쟀다 (그 카드도 그 효과도 쓰지 않았다).
전개 수와 상대에게 준 장수를 **따로** 움직였다.

| 상태 | 내 몬스터 | 상대에게 준 장수 | `heuristic` | `atk` | `monsters` | `deck` | `hand` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **0** 아무것도 안 함 | 0 | 0 | **+1,000** | 0 | 0 | 0 | 1,000 |
| **0′** 전개 없이 주기만 | 0 | **3** | **+1,900** | 0 | 0 | **900** | 1,000 |
| **A** 특수소환 1회 | 1 | 1 | +3,500 | 1,900 | 500 | 300 | 800 |
| **B** 특수소환 3회 | 3 | 3 | +8,500 | 5,700 | 1,500 | 900 | 400 |
| **B′** 같은 전개, 안 주기 | 3 | **0** | **+7,600** | 5,700 | 1,500 | **0** | 400 |
| **C** 풀 전개 | 5 | 5 | +13,500 | 9,500 | 2,500 | 1,500 | 0 |

**0 → 0′ 이 결정적이다.** 내 판을 **한 칸도 바꾸지 않고** 상대에게 3장을 주면
점수가 **+900 올라간다**.

```
B (주고 전개) +8,500  >  B′ (안 주고 같은 전개) +7,600       차이 = 3 × 300
```

즉 **평가만 보고 고르면 자원을 주는 쪽을 고른다.**

### 왜 그런가

| 사실 | 표현하는 feature |
| --- | --- |
| "내 필드가 강해졌다" | `atk` · `monsters` — **잘 표현된다** |
| "상대 덱이 줄었다" | `deck` — 표현되고, **점수를 올린다** |
| "상대 패가 늘었다" | **없다.** `WITHHELD` 메모가 장수(5→8)만 적고 값은 0 |

`deck = (내 덱 − 상대 덱) × 300` 이므로 상대가 뽑으면 차가 커진다. 그리고 상대
패가 늘어난 것을 세는 항이 **하나도 없다.**

### 이것은 가중치로 고칠 수 없다

`DECK_CARD_IN_LP` 를 낮춰도 부호는 그대로다. "상대에게 자원을 제공했다" 에
대응하는 **항이 애초에 없고**, 움직이는 유일한 항이 **반대 방향으로** 움직인다.
항을 더해야 하는 일이고, 항을 더하면 `heuristic` 이 바뀌어 **Search 결정이
바뀐다** — §8 이 금지한 것이다. 그래서 이 Phase 에서 고치지 않고 기록한다.

### 전제는 내부적으로 일관된다

`deck` 이 가장 무거운 근거는 "지금 도달 가능한 패배 조건이 덱아웃 하나" 다. 그
전제 아래서는 상대 덱을 줄이는 것이 **실제로** 진전이다. 모순은 전제가 틀렸다는
뜻이 아니라, 그 전제가 **"상대 패가 늘었다" 를 세지 않는 것과 짝이 되면** 거짓을
만든다는 뜻이다.

### 하지 않은 것

증식의 G 의 효과도 카드별 대응 로직도 **하드코딩하지 않았다.** 카드 이름도
passcode 도 평가에 들어가지 않는다 (`test_12`). 실제 대응은 향후 Search 가 엔진
결과를 비교할 일이다.

---

## 14. 테스트 결과

### 새로 더한 것

`tests/agent/test_evaluation_core_audit.py` — **17개** (전부 통과).

| 묶음 | 내용 |
| --- | --- |
| A (`test_01`–`03`) | 이미 있는 것 · 닮은 두 abstraction 의 구분 · `RuleBasedPolicy` 무관함 |
| B (`test_04`–`07`) | feature 집합 여섯 · D/E DEFERRED 의 **까닭** · 가중치 다섯 |
| C (`test_08`–`10`) | **§6 의 답** — 항이 전부 차다 · 자원을 주면 점수가 오른다 · A·B·C 순서 |
| D (`test_11`–`12`) | `Evaluator` 에 context 없음 · 상대 덱/카드 이름 미사용 |
| E (`test_13`–`17`) | Search 가 이미 소비 · 교체 가능 · 점수 불변 · terminal 등급 · 덱 구성 무관 |

**이미 있는 것은 다시 적지 않았다.** 순수성 · 관측 경계 · 제외 범주 · 등급
우선순위는 `test_evaluation_alignment_audit.py`(1,008줄) ·
`test_exclusion_categories.py`(303줄) · `test_evaluation_excluded_audit.py`(519줄)
합 **1,830줄**이 이미 지킨다. 그 파일들은 **한 줄도 고치지 않았다.**

### Phase §10 의 12개 요구와 대응

| § | 요구 | 어디서 |
| --- | --- | --- |
| 1 | 동일 state → 동일 evaluation | `test_15` (30회) |
| 2 | mutate 하지 않음 | `test_15` (`state_hash`) |
| 3 | RNG 소비 안 함 | `test_15` (`rng.getstate()`) |
| 4 | clone 동일성 | 기존 `test_04_the_same_observation_scores_the_same_through_any_route` |
| 5 | hidden info 누출 없음 | `test_12` · `test_17` + 기존 `test_02`·`test_05` |
| 6 | terminal WIN/LOSS | `test_16` (WIN·LOSS·DRAW·ONGOING 네 등급) |
| 7 | feature 경계값 | `test_08` (대칭판에서 차 항 전부 0) |
| 8 | 빈 필드/패/묘지 | `test_08` + 실측(§6) |
| 9 | 가능/불가능 feature 구분 | `test_04`·`test_05`·`test_06` |
| 10 | Search deterministic 유지 | `test_15` + production diff 0줄 |
| 11 | `RuleBasedPolicy` 유지 | `test_03` (import 하지 않음) + diff 0줄 |
| 12 | 전체 regression | 아래 |

### 고의 위반 검증 — 9건, 전부 잡았다

| # | 위반 | 잡은 테스트 |
| --- | --- | --- |
| 1 | `deck` 을 차가 아니라 내 쪽만 세게 | `test_08`·`test_09`·`test_10`·`test_15` |
| 2 | 상대 패를 음수 항으로 더한다 | `test_04`·`test_09`·`test_10`·`test_15` |
| 3 | 가중치 임의 변경 (`MONSTER_IN_LP` 500→700) | `test_07`·`test_15` |
| 4 | 평가가 카드 이름을 읽는다 | `test_12` |
| 5 | 끝난 판에서 휴리스틱을 센다 | `test_16` |
| 6 | 무승부가 진행 중보다 높아진다 | `test_16` |
| 7 | Search 의 평가자 Protocol 검사 제거 | `test_11` (**처음엔 못 잡았다** → 고쳤다) |
| 8 | 평가가 관측 아닌 것을 받는다 | 기존 `test_01` (새 파일이 아니라 **기존 테스트**가 잡았다) |
| 9 | 평가가 난수를 쓴다 | `test_08`·`test_09`·`test_15` |

**7번을 처음 놓쳤다.** `test_11` 이 `"isinstance(self.evaluator, Evaluator)"`
라는 **문자열이 소스에 있는지**만 보았고, `if False and isinstance(...)` 로 바꾸면
문자열은 그대로 남아 통과했다. 실제로 **거부하는지**를 보도록 고쳤더니 잡혔다.
그 까닭을 테스트 docstring 에도 적어 두었다.

8번은 **기존 테스트가 잡았다** — 기존 1,830줄이 실제로 작동한다는 증거다.

복원은 매번 md5 로 확인했다.

### 전체 회귀

```
$ python3 -m pytest tests/agent/test_evaluation_core_audit.py -p no:randomly -q
17 passed in 4.14s

$ python3 -m pytest -p no:randomly -q
4116 passed, 4 skipped in 536.74s (0:08:56)
```

| | 통과 | skip |
| --- | --- | --- |
| Phase 3-E-45 직후 (baseline) | 4,099 | 4 |
| Phase 3-F-1 (이번) | **4,116** | 4 |
| 차이 | **+17** | 0 |

**+17 이 이번에 더한 감사 시험 수와 정확히 같다.** 기존 테스트를 **하나도
수정하지 않았다** — 삭제 · skip 추가 · assertion 약화도 없다. production 을
한 줄도 고치지 않았으므로 기존 계약이 깨질 자리가 없었다.

---

## 15. 최종 판정

### **B. EVALUATION_CORE_AUDIT_ONLY**

근거:

* **Evaluation Core 가 이미 있다** (`agent/evaluation.py`, 661줄, Phase 3-C).
  Phase 가 목표로 적은 `GameStateView → Features → Score → Search` 구조가
  그대로 구현되어 있고, 1,830줄의 테스트가 이미 지키고 있다.
* 그래서 **별도 production 구현이 필요하지 않다.** 새 Evaluation 클래스를
  만들면 그것이 §2 가 금지한 중복 abstraction 이다.
* **Search 연결도 이미 되어 있다** (§8 의 선택지 A). 연결할 것이 없다.
* 요구된 feature 중 A·B·F·G 는 구현되어 있고 C 는 부분 구현이며, **D·E 는
  가중치가 아니라 입력 때문에 불가능**하므로 DEFERRED 로 적었다 — 억지로
  계산하지 않았다.

`A. EVALUATION_CORE_ESTABLISHED` 가 아닌 까닭: 그 Core 를 **이 Phase 가 세운
것이 아니다.** 3-C 가 세웠고 3-E-6·7·8 이 다듬었다. A 로 적으면 이 Phase 가
만든 것처럼 읽힌다.

`C. STRUCTURAL_BLOCKER_FOUND` 가 아닌 까닭: §13 의 부호 결함은 Core 를 **만드는
것을 막는** blocker 가 아니다. 이미 있는 Core 의 **feature 집합이 좁다**는
문제이고, 고치는 길(항 추가) 도 분명하다. 다만 그 길은 `heuristic` 을 바꾸므로
Search 결정이 바뀌고, §8 이 그것을 금지했다. 그래서 다음 Phase 의 일이다.

### 이번 Phase 에서 하지 않은 것

§12 의 금지 목록 전부 확인:

* Engine V1 freeze 해제 **안 함** · Trigger pipeline 연결 **안 함** ·
  dormant trigger / `activation_zone` / `cost_feasibility` 수정 **안 함**
* Chain architecture 변경 · 새 EventBus / graph engine / rule engine /
  card effect executor **없음**
* Depth-2 Search · MCTS · 강화학습 · Neural Network · Self-play ·
  Opponent Model **없음**
* Deck Builder · Card Evaluation AI · UI/API · Discord **없음**
* README 수정 **없음** · Lua 위치/구조 변경 **없음**
* 3-C Search/Simulation 구조 변경 **없음** · AI Action Interface 와
  `RuleBasedPolicy` **그대로**
* 가중치 최적화 **없음** · 새 UNKNOWN enum **없음** (기존 `ExclusionCategory`
  재사용)

```
$ git diff --stat -- engine agent app core analysis rules rulings sources scripts
(출력 없음 — production 수정 0줄)
```

산출물은 둘뿐이다: `tests/agent/test_evaluation_core_audit.py` (신규) ·
`docs/phase3f1-evaluation-core.md` (이 보고서).

---

## 16. 향후 확장 방향

이번 Phase 에서 **구현하지 않는다.** 순서는 §13 의 측정이 정한다.

1. **상대 자원 feature** — §13 의 부호 결함. 항을 더해야 하고, 더하면
   `heuristic` 이 바뀌어 Search 결정이 바뀐다. 그 변경이 **의도된 것**임을
   먼저 문서화해야 한다. 가장 먼저 할 일이다.
2. **Depth-2 Search** — 상대 응수를 한 수 더 본다. 지금 `SUPPORTED_DEPTH = 1`.
3. **Opponent Response Search** — 상대 턴 개입을 본다. D(Interaction) 이 먼저
   필요하고, 그것은 `SetCode(EVENT_*)` 가 `EffectDefinition` 에 들어와야 한다.
4. **Opponent Model** — `Evaluator.evaluate(view)` 에 context 인수가 없으므로
   Protocol 변경이 선행한다 (`test_11`). Search 의 런타임 검사까지 닿는다.
5. **Self-play** · **Learned Evaluation** — 위 넷이 안정된 뒤의 일이다.

---

## Commit · Push 기록

| 항목 | 값 |
| --- | --- |
| 결과 commit | `bd1f8c3` — `Phase 3-F-1: establish AI evaluation core` |
| 브랜치 | `claude/pensive-goodall-te1egy` |
| Push | `077e44a..bd1f8c3` → `origin/claude/pensive-goodall-te1egy` (성공) |
| production diff | **0 줄** |
| 변경 파일 | 신규 테스트 1 · 신규 보고서 1 (기존 파일 수정 0건) |

**다음 Phase 는 임의로 진행하지 않는다.**
