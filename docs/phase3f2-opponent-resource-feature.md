# Phase 3-F-2 — Opponent Resource Feature Foundation

## 1. Phase / Base / 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-F-2 — 상대 자원 feature 기반 |
| 성격 | **최소 production 추가** (`agent/` 두 파일, **삭제 0줄**) |
| Base Phase | 3-F-1 — AI Evaluation Core (판정 **B. EVALUATION_CORE_AUDIT_ONLY**) |
| Base commit | `bd1f8c3` (결과) · `1ef1ebb` (보고서) |
| Base baseline | 4,116 passed / 4 skipped |

**실제 HEAD 확인 (작업 시작 전)**

```
$ git rev-parse HEAD
1ef1ebb98c5e9e81c2a1dbf287bc723ed4158d94
$ git merge-base --is-ancestor bd1f8c3 HEAD   → ANCESTOR
$ git merge-base --is-ancestor 1ef1ebb HEAD   → ANCESTOR
$ git status --short                          → (비어 있음)
```

3-F-1 산출물도 그 자리에 있다 — `docs/phase3f1-evaluation-core.md` (26,892 B) ·
`tests/agent/test_evaluation_core_audit.py` (25,568 B).
Engine V1 freeze 를 유지한다.

---

## 2. 기존 Evaluation 구조

조사 11항목의 실측 결과다.

| 조사 항목 | 결과 |
| --- | --- |
| 1. `agent/evaluation.py` | 661줄. `Terminal`·`StateValue`·`Evaluator`·`StateEvaluator`·`ExclusionCategory`·`Exclusion` |
| 2. `StateValue` | **네 칸** — `terminal`·`heuristic`·`terms`·`excluded` |
| 3. `StateValue.terms` | `tuple[tuple[str,int],...]`, 이름 여섯 고정 |
| 4. `StateValue.heuristic` | `sum(terms 값)` — **숨은 항이 없다** |
| 5. `SearchPolicy` | `evaluator: Evaluator = field(default_factory=StateEvaluator)` |
| 6. `GameStateView` | 공개 표면 21개. `legal_actions`·`chain`·`priority` **없음** |
| 7. draw / movement / resource 상태 | `GameState.draw`·`move` 가 존 사이를 옮긴다. 관측은 **결과만** 본다 |
| 8. `GameState` 의 자원 표현 | 자리마다 `ZoneContainer` — `deck`·`hand`·`grave`·`removed`·`monster_zone`·`spell_zone`·`extra`·`extra_monster_zone`·`field_zone`·`pendulum_zone` |
| 9. 관측이 주는 상대 공개 정보 | **§5 의 표** — 모든 자리의 `size` 는 주고, 패·덱·엑스트라의 **내용은 주지 않는다** |
| 10. 시뮬레이션 전/후 비교 가능한가 | **가능하다.** `Simulator.view(seat)` 가 전, `SimulationResult.future` 가 후 |
| 11. Search → evaluation caller path | `decide` → `_look_ahead(view, legal)` → `self.evaluator.evaluate(result.future)` — **한 자리** |

### 새 `GameState` 필드를 만들지 않았다

§2 가 요구한 확인이다: 상대 자원을 세는 데 **이미 있는 데이터로 충분하다.**
일곱 자리의 `size` 가 전부 관측에 들어오므로 엔진을 건드릴 이유가 없었다.

### 재사용한 것 · 만들지 않은 것

* **재사용**: `ExclusionCategory`(`UNKNOWN`) · `Exclusion` · `EvaluationError` ·
  `_UNSCORED_ZONES` 의 "이름 + 접근자" 표 패턴.
* **만들지 않음**: 새 UNKNOWN enum · 새 상태 시스템 · 새 모듈 · 새 평가자.

---

## 3. 상대 자원 정의

§3 이 요구한 네 구분을 그대로 적용했다.

| | 구분 | 이번 Phase 의 처리 |
| --- | --- | --- |
| **A** | 현재 상대가 보유한 공개 자원 | :class:`OpponentResources` — **구현** |
| **B** | 이번 행동 때문에 **새로 제공된** 자원 | :class:`OpponentResourceDelta.drawn_from_deck` — **구현** |
| **C** | 상대의 hidden information | **쓰지 않는다.** 추정하지 않고 0 으로도 두지 않는다 |
| **D** | 실제로 알 수 없는 정보 | `unexplained` 에 `UNKNOWN` 으로 **적는다** |

### 읽는 자리 일곱

```python
OPPONENT_RESOURCE_ZONES = (
    ("hand", …), ("deck", …), ("grave", …), ("removed", …),
    ("monsters", …), ("spells", …), ("extra", …),
)
```

이름과 **접근자**를 함께 적는다 (`_UNSCORED_ZONES` 와 같은 이유 — 어느 자리를
읽는지 코드에서 읽혀야 한다).

### 단위는 **장**이고 LP 가 아니다

`OpponentResources` 는 **점수가 아니라 관측**이다. 어떤 가중치도 붙지 않았고,
`StateValue` 와 섞지 않는다. `total` 은 "상대가 얼마나 강한가" 가 아니다 —
묘지의 한 장과 패의 한 장을 같게 세므로 **합이 변했는지** 보는 데만 쓴다.

### §4 의 세 번째 항목 — `opponent_card_advantage` 는 **만들지 않았다**

card advantage 는 "내 카드 수 − 상대 카드 수" 라는 **차**이고, 3-F-1 이 측정한
결함이 바로 **차가 양쪽을 한 숫자로 합쳐 버리는 것**이었다. 그 자리에 또 하나의
차를 만들면 같은 결함을 반복한다. 그래서 두 쪽을 **분리해서** 들고 있고, 합치는
일은 가중치가 정해진 뒤에 할 수 있다.

---

## 4. current resource vs resource delta

**§4 의 핵심 구분이고, 자료형을 둘로 나눈 이유다.**

> "상대에게 3장을 줬다" 와 "상대 패가 지금 3장이다" 는 **다른 정보다.**

| | 무엇을 말하는가 | 어디에 있는가 |
| --- | --- | --- |
| current | 지금 상대가 몇 장 들고 있는가 | `OpponentResources` / `delta.after` |
| delta | 두 관측 **사이**에 몇 장이 움직였는가 | `delta.changes` |
| **gain** | 그중 **상대가 얻었다고 말할 수 있는** 양 | `delta.drawn_from_deck` |

측정으로 둘이 독립임을 보였다 (`test_06`) — **같은 `drawn_from_deck = 3`** 인데
**현재 패 장수가 8 과 6** 인 두 판을 만들 수 있다. 하나로 합치면 "증식의 G 로
3장을 줬다" 와 "상대가 원래 패를 많이 들고 있었다" 를 구분할 수 없다.

---

## 5. hidden information boundary

### 관측이 상대에 대해 **무엇을 주는가** (실측)

| 상대의 자리 | `visibility` | `concealed` | `size` | 내용(정체) |
| --- | --- | --- | --- | --- |
| hand | `owner_only` | **True** | **보인다** | **안 보인다** (목록 0) |
| deck | `hidden` | **True** | **보인다** | **안 보인다** |
| extra | `owner_only` | **True** | **보인다** | **안 보인다** |
| grave | `public` | False | 보인다 | 보인다 |
| removed | `public` | False | 보인다 | 뒷면은 `is_identified=0` |
| monster_zone | `public` | False | 보인다 | 앞면만 |
| spell_zone | `public` | False | 보인다 | 뒷면은 `is_identified=0` |

**장수는 일곱 자리 전부 공개 사실이다.** 그래서 장수를 읽는 것은 hidden
information 접근이 **아니다** (`test_03`). 기존 평가의 주석도 같은 말을 한다 —
"상대 패는 장수가 보이지만 값을 매기려면 내용을 알아야 한다".

### 하지 않은 것 (§7 전부 확인)

| 금지 | 확인 |
| --- | --- |
| opponent hidden hand 직접 접근 | **안 함.** 더한 코드의 attribute 접근에 `cards`·`card_id`·`name`·`is_identified`·`face_up`·`revealed` 가 **하나도 없다** (`test_04`) |
| opponent deck contents 열람 | **안 함.** `deck.size` 만 읽는다 |
| hidden card identity 를 feature 로 | **안 함.** 읽는 것은 `size` 뿐이다 |
| opponent belief model | **안 함** |
| Bayesian inference | **안 함** |

**구조적 보호 둘**: 관측이 아니면 `EvaluationError`, 두 관측의 관점이 다르면
`EvaluationError` (`test_16`). 후자가 필요한 이유 — 관점이 다른 두 판을 비교하면
"상대" 가 서로 다른 사람이 되어 delta 가 뜻을 잃는다.

### 향후 Opponent Model 을 위한 API 설계 (기록만)

`OpponentResourceDelta.between(before, after)` 는 **관측 둘**을 받는다. 미래에
믿음(belief) 을 넣으려면 세 번째 인수가 필요하고, 그것은 이 함수의 서명 변경이다.
**`Evaluator` Protocol 은 건드리지 않아도 된다** — delta 가 그 Protocol 밖에 있기
때문이다. 이것이 별도 자료형으로 둔 또 하나의 이득이다. 이번 Phase 에서
구현하지 않는다.

---

## 6. 구현한 feature

`agent/evaluation.py` 에 **더하기만** 했다 (삭제 0줄, 기존 이름 변경 0건).

### `OpponentResources` — 현재 장수

```python
hand · deck · grave · removed · monsters · spells · extra      # 전부 int
of(view) → 관측에서 읽는다 (관점은 view.viewer)
counts() → (이름, 장수) 일곱
total    → 합 (비교용이 아니라 "변했는가" 용)
```

### `OpponentResourceDelta` — 변화와 **안전한 추론 하나**

```python
before · after            : OpponentResources
drawn_from_deck : int     # 안전하게 "상대가 얻었다" 고 말할 수 있는 양
unexplained : tuple[Exclusion, ...]   # 설명하지 못한 변화 (UNKNOWN)

between(before_view, after_view)
changes          → 자리별 차 (0 인 자리도 적는다)
gave_resource    → drawn_from_deck > 0
fully_explained  → not unexplained
```

### 안전하게 센 **단 하나의 이동** (§6 의 답)

> **덱이 줄고 그만큼 패가 늘었다** → 드로우다.

```python
hand_gain = after.hand  - before.hand
deck_loss = before.deck - after.deck
drawn     = min(hand_gain, deck_loss) if hand_gain > 0 and deck_loss > 0 else 0
```

**그 모양을 만드는 다른 이동이 없다.** 이것이 증식의 G 가 주는 자원의 모양이다.

나머지 변화는 **값으로 세지 않고** `unexplained` 에 `ExclusionCategory.UNKNOWN`
으로 적는다. 적지 않으면 `fully_explained` 가 "다 설명했다" 는 거짓을 말한다
(`StateValue.partial` 과 같은 이유).

### 실측 — 이동 종류별 처리

| 상대에게 일어난 일 | 장수 변화 | `drawn` | `gave` | `fully_explained` |
| --- | --- | --- | --- | --- |
| 드로우 3 (덱→패) | `hand+3 deck-3` | **3** | True | True |
| 디스카드 2 (패→묘지) | `hand-2 grave+2` | 0 | False | **False** (2건) |
| 특수소환 2 (패→필드) | `hand-2 monsters+2` | 0 | False | **False** (2건) |
| 제외 1 (패→제외) | `hand-1 removed+1` | 0 | False | **False** (2건) |
| 덱→묘지 2 | `deck-2 grave+2` | 0 | False | **False** (2건) |
| **필드→패 1** | `hand+1 monsters-1` | **0** | False | **False** (2건) |
| 드로우 3 + 디스카드 1 | `hand+2 deck-3 grave+1` | **2** | True | **False** (2건) |
| 변화 없음 / 내 쪽만 변함 | 없음 | 0 | False | True |

두 줄이 특히 중요하다.

* **필드→패** — 패가 늘었는데 덱은 그대로다. **드로우가 아니다.** 상대가 새
  자원을 얻은 것이 아니라 있던 것을 옮겼다 (`test_09b`).
* **드로우 3 + 디스카드 1** — 실제로는 3장을 뽑았는데 **2 로 센다.** 장수만으로는
  "3장 뽑고 1장 버렸다" 와 "2장 뽑고 1장을 덱에서 묘지로 보냈다" 를 **구분할 수
  없기 때문**이다. 3 이라고 적으면 그것은 추측이다. **적게 세고 남은 것을 적는
  쪽**을 골랐다 (`test_10`).

---

## 7. DEFERRED feature

§6 이 나열한 변화 중 이번에 **정의하지 않은 것**과 그 까닭이다.

| 변화 | 상태 | 까닭 |
| --- | --- | --- |
| `draw` (덱→패) | **구현** | 장수만으로 확정된다 |
| `discard` (패→묘지) | **DEFERRED** | 상대의 실(失)일 수도 **득**일 수도 있다 (코스트로 버리는 것은 전개의 일부다). 장수로는 어느 쪽인지 정해지지 않는다 |
| `card movement` 일반 | **DEFERRED** | 같은 장수 변화가 여러 이동에서 나온다 (필드→패 ↔ 덱→패) |
| `special summon` (패→필드) | **DEFERRED** | 상대 필드가 강해진 것은 **보드 가치**의 문제이고 자원 수지와 다른 축이다 |
| `card destruction` (필드→묘지) | **DEFERRED** | 보통 상대의 실이지만, 파괴를 트리거로 쓰는 카드가 있으므로 장수로 단정할 수 없다 |
| `banish` (→제외) | **DEFERRED** | 제외에서 돌아오는 수단이 있는지 여부에 달려 있고, 그것은 카드별 지식이다 |
| `return` (→덱/패) | **DEFERRED** | 위와 같다 |
| `shuffle` | **해당 없음** | 장수를 바꾸지 않는다. 그리고 엔진은 셔플을 `UNIMPLEMENTED` 사건으로 남긴다 (3-E-45) |

**전부 `changes` 에는 장수로 기록되고, `unexplained` 가 "까닭을 정할 수 없다" 고
말한다.** 즉 빠뜨리지 않고 **모른다고 적는다** — 0 으로도 득으로도 접지 않는다.

완전한 경제 모델(어느 이동이 얼마만큼의 가치인가)은 **카드별 지식**을 요구하고,
그것은 Opponent Model 의 영역이다. 이번 Phase 의 범위가 아니다.

---

## 8. 증G benchmark 결과

§5 의 네 상태다. 증식의 G 라는 카드도 그 효과도 쓰지 않고 **모양만** 손으로
만들었다 — 전개량과 제공 자원량을 **따로** 움직였다.

| 상태 | 내 전개 | 상대에게 제공 | `drawn_from_deck` | `gave_resource` | `monsters` 항 | `heuristic` |
| --- | --- | --- | --- | --- | --- | --- |
| **A** 아무것도 안 함 | 0 | 0 | **0** | False | 0 | +1,000 |
| **B** 전개0 · 자원3 | 0 | 3 | **3** | True | 0 | +1,900 |
| **C** 전개3 · 자원3 | 3 | 3 | **3** | True | 1,500 | +8,500 |
| **D** 전개3 · 자원0 | 3 | 0 | **0** | False | 1,500 | +7,600 |

### C vs D — **차이가 사라지지 않는다**

```
내 전개량:         C = D   (monsters 1,500 · atk 동일)
drawn_from_deck:   C = 3   D = 0      ← 새 feature 가 갈라낸다
heuristic:         C = 8,500 > D = 7,600
```

3-F-1 에서는 이 둘을 구분할 **단서가 하나도 없었다**. 이제 `drawn_from_deck` 이
3 과 0 으로 갈린다. **§5 가 요구한 것이 정확히 이것이다.**

### A vs B — 내 판을 한 칸도 바꾸지 않은 경우

`lp`·`atk`·`monsters`·`spells`·`hand` 항이 **전부 같은데** 자원 제공량만 다르다.
새 feature 가 0 과 3 으로 갈라낸다.

### 점수 순서를 **뒤집지 않았다**

C 가 D 보다 높은 것은 3-F-1 이 측정한 그대로이고 **고치지 않았다.** §5 가
명시했다 — "C 가 반드시 D 보다 낮은 최종 score 가 되어야 한다고 고정하지
않는다. 이번 Phase 의 목표는 '차이를 표현할 수 있는가' 다."

차이는 전부 `deck` 항에서 온다 (`3 × DECK_CARD_IN_LP = 900`). 그 부호를 바꾸는
것은 가중치 결정이고 다음 Phase 의 일이다.

---

## 9. 기존 heuristic 과의 관계

**건드리지 않았다.** 그래서 §9 가 금지한 "근거 없는 값 하나" 가 없다.

| | 상태 |
| --- | --- |
| 가중치 다섯 (`ATK_IN_LP` 등) | **그대로** |
| `StateValue` 칸 수 | **네 칸 그대로** |
| `terms` 이름 여섯 | **그대로** |
| `heuristic` 계산식 | **그대로** |
| 상대 자원의 가중치 | **없다** — `opponent_draws * -300` 같은 값을 확정하지 않았다 |

더한 두 자료형 어디에도 LP 환산이 없고, 다섯 가중치 이름을 **참조조차 하지
않는다** (`test_17`).

### 왜 `StateValue` 안에 넣지 않았는가

Phase 3-E-42 가 `StateValue`·`SearchCandidate` 를 **각각 네 칸**으로 고정했다
("후보는 관측을 들고 있지 않다"). 상대 자원을 그 안에 넣으면 그 계약을 뒤집고
세 곳의 테스트를 고쳐야 한다. **그것은 가중치가 정해진 뒤에 내릴 결정**이므로
별도 자료형으로 두었다 (`test_18`).

### 단위와 normalization

| | 단위 | normalization |
| --- | --- | --- |
| `StateValue` 항 여섯 | **LP** | 불필요 (단위가 하나다) |
| `OpponentResources` | **장** | **하지 않았다** |

**섞지 않았으므로 normalization 이 필요 없다.** 서로 다른 단위를 한 합에 넣는
순간 필요해지고, 그때가 가중치를 정하는 Phase 다. 그 Phase 는 "장 하나가 LP
얼마인가" 를 **근거와 함께** 정해야 한다 — 기존 가중치가 전부 그렇게 적혀 있다.

---

## 10. Search ranking 영향

### **없다. 측정했다.**

같은 측정을 **feature 를 뺀 상태와 넣은 상태**에서 각각 돌려 비교했다
(`git stash` 로 두 파일을 3-F-1 상태로 되돌려 측정 → 복원 후 재측정).

| 측정 항목 | feature 없음 (3-F-1) | feature 있음 (3-F-2) | 동일 |
| --- | --- | --- | --- |
| 판 수 | 8 | 8 | ✅ |
| **Search 결정 수** | **510** | **510** | ✅ |
| **비교한 후보 총수** | **1,551** | **1,551** | ✅ |
| `state_hash` 8개 | — | 전부 동일 | ✅ |
| 진행 step 수 8개 | `83 79 66 71 74 102 119 97` | 같음 | ✅ |
| **후보 순서 digest** | `f5e27134…` | `f5e27134…` | ✅ |

digest 는 결정마다 **정렬된 후보 전체의 `ordering_key`, 고른 행동,
`simulations`, `skipped`, `comparable_count`** 를 전부 담은 것이다. `state_hash`
만 보면 순위 변화를 놓칠 수 있으므로 순서 자체를 해시했다.

**두 번 측정했다.** 처음 구현 뒤 한 번, 그리고 §13 의 인수 이름 변경 뒤 한 번 —
두 번 모두 digest 가 `f5e27134…` 로 같다.

### 왜 바뀔 수 없는가 (구조적 근거)

`agent/search.py` 를 **한 줄도 고치지 않았고**, 그 파일에
`OpponentResource`·`drawn_from_deck` 문자열이 **하나도 없다** (`test_19`).
비교는 여전히 `StateValue.ordering_key()` 하나로만 한다.

| 보존 대상 | 상태 |
| --- | --- |
| deterministic ordering | **그대로** (digest 동일) |
| tie-break (`canonical_state`) | **그대로** |
| `SimulationStatus` | **그대로** |
| UNKNOWN / REFUSED semantics | **그대로** |
| `Evaluator` Protocol | **그대로** — `evaluate(view)` (`test_20`) |

**연결은 가중치가 정해진 뒤의 일이다.** 지금 연결하면 §9 가 금지한 임의 가중치를
확정해야 한다.

---

## 11. state_hash / RNG 영향

| 질문 | 결과 |
| --- | --- |
| `GameState` 를 mutate 하는가 | **아니다.** 30회 계산 전후 `state_hash` 동일 |
| RNG 를 소비하는가 | **아니다.** `rng.getstate()` 전후 동일 |
| 같은 관측 → 같은 feature | **그렇다.** 30회 전부 동일 |
| clone 의 결과가 같은가 | **그렇다** |
| 실제 듀얼의 `state_hash` | **8판 전부 동일** (§10) |

더한 코드의 attribute 접근에 `state`·`clone`·`rng`·`randomness` 가 **하나도
없다** (`test_04`) — 순수 읽기가 코드 수준에서 강제된다.

---

## 12. GameStateView 정보 부족 문제

§8 이 요구한 확인이다. 3-F-1 이 기록한 셋(`legal_actions`·`chain`·`priority`)이
**이번 구현에 필요했는가**:

### **필요하지 않았다. 그래서 추가하지 않았다.**

상대 자원은 **자리별 장수**로 세고, 그 장수는 이미 관측에 전부 들어온다.
행동 가능성·체인·우선권은 **하나도 읽지 않는다.**

그 셋이 필요해지는 자리는 따로 있고, 이번 범위가 아니다.

| 3-F-1 의 DEFERRED | 그 셋이 필요한가 | 이번 Phase 와의 관계 |
| --- | --- | --- |
| D — Interaction (상대 턴 개입 수단) | **`legal_actions` 가 필요하다** | 범위 밖. 그리고 그 전에 `SetCode(EVENT_*)` 가 `EffectDefinition` 에 들어와야 한다 |
| E — Follow-up (다음 행동 가능성) | **`legal_actions` 가 필요하다** | 범위 밖 |

**ADR-007 경계와 충돌하지 않는다** — 체인과 우선권은 `GameState` 밖에 살고,
이번 feature 는 `GameState` 안의 것만 본다. 그래서 관측 architecture 를 손댈
이유가 없었다 (§12 가 금지한 것).

그 셋을 더하는 일은 **별도 Phase 후보**로 남긴다 (§15 참조하지 않음 — 다음 Phase
후보는 하나뿐이고 그것은 아래 §15 다).

---

## 13. 테스트 결과

### 새로 더한 것

`tests/agent/test_opponent_resource_feature.py` — **27개** (전부 통과).

| 묶음 | 내용 |
| --- | --- |
| A (`test_01`–`05`) | 읽는 자리 일곱 · `size` 와 일치 · 가려진 자리도 장수는 준다 · 정체 미열람 · 관점 상대성 |
| B (`test_06`–`07`) | **current ≠ delta** · 변화 없는 자리도 적는다 |
| C (`test_08`–`11`) | 드로우만 득으로 센다 · 다른 이동은 UNKNOWN · **패만 늘면 드로우가 아니다** · 섞인 변화는 적게 센다 |
| D (`test_12`–`14`) | **증G benchmark** A·B·C·D · C vs D · A vs B |
| E (`test_15`–`16`) | 순수성 · clone · 두 보호(관측/관점) |
| F (`test_17`–`20`) | 가중치 0건 · 네 칸 유지 · Search 미변경 · Protocol 유지 |

### §11 의 12개 요구와 대응

| § | 요구 | 어디서 |
| --- | --- | --- |
| 1 | 동일 state → 동일 feature | `test_15` (30회) |
| 2 | 동일 state → 동일 evaluation | `test_15` + 기존 3-F-1 `test_15` |
| 3 | mutate 없음 | `test_15` (`state_hash`) |
| 4 | RNG 소비 없음 | `test_15` (`rng.getstate()`) |
| 5 | hidden info 접근 없음 | `test_03`·`test_04` |
| 6 | 상대 자원 0 과 3 구분 | `test_12`·`test_14` |
| 7 | 전개 같고 자원 다른 두 상태 구분 | **`test_13`** (C vs D) |
| 8 | current 와 delta 구분 | **`test_06`** |
| 9 | 미지원 변화는 UNKNOWN/DEFERRED | `test_09`·`test_09b`·`test_10` |
| 10 | clone 동일 | `test_15` |
| 11 | Search deterministic 유지 | `test_19` + §10 의 digest 비교 |
| 12 | 전체 regression | 아래 |

증G benchmark 는 `test_12`–`test_14` 로 **별도 고정**했다 (§11 의 요청).

### 두 번의 기존 계약 충돌 — **계약을 고치지 않고** 통과시켰다

전체 회귀에서 Phase 3-E-42 의 계약 둘이 걸렸다. 둘 다 **내 쪽을 고쳤다.**

| 걸린 계약 | 무엇이 걸렸나 | 어떻게 했나 |
| --- | --- | --- |
| `test_11` — `SimulationResult.viewer` 는 production 독자가 없어야 한다 | 그 테스트는 `view` 가 든 이름을 관측의 것으로 **인정**하는데, 내 인수 이름이 `before`·`after` 여서 필터를 비껴갔다 | 인수를 **`before_view`·`after_view`** 로 바꿨다. 이름이 "관측을 받는다" 를 말하게 되었으므로 읽기도 나아졌다 |
| `test_29` — `agent/evaluation.py` 는 시뮬레이션을 모른다 | 내가 docstring 에 `SimulationResult` 를 **언급**했고, 그 검사는 문자열이다 | 그 이름을 쓰지 않고 같은 뜻을 적었다 |

**기존 테스트를 한 줄도 고치지 않았다** — 두 계약 모두 정당하고, 걸린 쪽이 내
코드였다.

```
$ git diff --stat -- tests/
(출력 없음)
```

이름을 바꾼 뒤 **§10 의 digest 를 다시 측정했다** — 510 결정 · 1,551 후보 ·
8개 `state_hash` · step 수 · digest `f5e27134…` 전부 **그대로**다.

### 전체 회귀

```
$ python3 -m pytest tests/agent/test_opponent_resource_feature.py -p no:randomly -q
27 passed in 3.38s

$ python3 -m pytest -p no:randomly -q
4143 passed, 4 skipped in 406.56s (0:06:46)
```

| | 통과 | skip |
| --- | --- | --- |
| Phase 3-F-1 직후 (baseline) | 4,116 | 4 |
| Phase 3-F-2 (이번) | **4,143** | 4 |
| 차이 | **+27** | 0 |

**+27 이 이번에 더한 시험 수와 정확히 같다.** 기존 테스트 **수정 0건** — 삭제 ·
skip 추가 · assertion 약화도 없다.

### 고의 위반 검증 — 7건, 전부 잡았다

| # | 위반 | 잡은 테스트 |
| --- | --- | --- |
| 1 | 패가 늘면 **무조건** 드로우로 센다 | `test_09b` (**처음엔 못 잡았다** → 테스트를 더했다) |
| 2 | 미설명 변화를 조용히 버린다 | `test_09`×4 · `test_10` |
| 3 | 관점 보호 제거 | `test_16` |
| 4 | 상대 패의 `card_id` 를 읽는다 | `test_04` |
| 5 | 섞인 변화에서 **많이** 센다 (추측) | `test_10` |
| 6 | 상대 자원에 LP 가중치를 붙인다 | `test_02`·`test_17` |
| 7 | 읽는 자리를 하나 뺀다 | 20건 |

**1번을 처음 놓쳤다.** `drawn = max(hand_gain, 0)` 으로 바꿔도 26개가 전부
통과했다 — **패가 늘면서 덱이 안 줄어드는 판을 하나도 만들지 않았기 때문**이다.
그래서 "덱이 줄었는가" 라는 조건이 실제로 무언가를 막는지 재지 못했다.
필드→패 시나리오(`test_09b`) 를 더하자 잡혔고, 그 까닭을 테스트 docstring 에도
적었다.

복원은 매번 md5 로 확인했다.

---

## 14. 최종 판정

### **A. OPPONENT_RESOURCE_FEATURE_ESTABLISHED**

근거:

* **안전한 상대 자원 feature 가 정의되고 구현되었다** — `OpponentResources`
  (현재 장수) 와 `OpponentResourceDelta` (변화 + 안전한 득 하나).
* **§5 의 benchmark 를 통과한다.** C(전개3+자원3) 와 D(전개3+자원0) 의 차이가
  `drawn_from_deck` 3 vs 0 으로 남는다 — 3-F-1 에서는 단서가 하나도 없었다.
* **hidden information 을 하나도 읽지 않는다.** 일곱 자리의 `size` 는 전부 공개
  사실이고, 정체를 읽는 접근자가 코드에 없다.
* **추측하지 않는다.** 안전하게 확정되는 이동 하나만 세고, 나머지는 `UNKNOWN`
  으로 적는다. 섞인 경우에는 **적게 세고 남은 것을 적는다.**
* **기존 것을 하나도 바꾸지 않았다.** production diff 가 **+220줄 · 삭제 0줄**
  이고, Search ranking 이 510 결정 · 1,551 후보에서 **digest 까지 동일**하다.
* 가중치를 **붙이지 않았다** — §9 가 금지한 임의의 값이 없다.

`B. OPPONENT_RESOURCE_AUDIT_ONLY` 가 아닌 까닭: 기존 구조만으로 부족했고
(3-F-1 이 측정했다), 이번에 **실제로 feature 를 만들었다.** 다음 Phase 로 넘긴
것은 feature 가 아니라 **가중치**다.

`C. STRUCTURAL_BLOCKER_FOUND` 가 아닌 까닭: 관측 경계를 고치지 않고도 안전한
상대 자원 평가가 **가능했다.** 일곱 자리의 `size` 가 이미 관측에 있었고, 새
`GameState` 필드도 observation architecture 변경도 필요하지 않았다.

### 이번 Phase 에서 하지 않은 것

§12 의 금지 목록 전부 확인:

* Engine V1 · `GameState` 구조 · Trigger pipeline · Chain · Priority ·
  `LegalActions` architecture · `ActionExecutor` · card effect execution
  — **전부 수정 0줄** (`engine/` diff 0)
* Opponent Model · Deck Builder · Card Evaluation AI · Self-play ·
  강화학습 · Neural Network · MCTS · Depth-2 Search · UI/API · README ·
  Lua 구조 — **없음**
* **`GameStateView` 에 정보를 더하지 않았다.** 필요하지 않았다 (§12)
* 3-C Search/Simulation 구조 변경 **없음** · `RuleBasedPolicy` **그대로**
  (`agent/heuristic.py` diff 0)
* 새 UNKNOWN enum **없음** (`ExclusionCategory` 재사용)

```
$ git diff --stat -- engine agent app core analysis rules rulings sources scripts
 agent/__init__.py   |   6 ++
 agent/evaluation.py | 214 ++++++++++++++++++++++++++++++++++++++
 2 files changed, 220 insertions(+)
```

삭제가 **0줄**인 것이 "기존 것을 건드리지 않았다" 의 기계적 증거다.

---

## 15. 다음 Phase 후보 (1개)

**Phase 3-F-3 — 상대 자원 가중치 결정과 Search 연결**

이번 Phase 가 feature 를 만들었고, 남은 것은 **값을 매기는 일** 하나다. 그
Phase 가 답해야 하는 것이 분명하다.

1. **장 하나가 LP 얼마인가.** 기존 가중치 다섯이 전부 근거와 함께 적혀 있으므로
   같은 방식으로 적어야 한다. `drawn_from_deck` 은 **상대가 쓸 수 있게 된 자원**
   이므로 `HAND_CARD_IN_LP`(200) 가 기준점의 후보다 — 다만 그것은 **내 패**의
   값이고 상대 패의 값은 내용을 모르므로, 같은 값을 쓸 근거가 있는지부터 재야
   한다.
2. **`deck` 항의 부호를 어떻게 할 것인가.** 지금 상대가 뽑으면 그 항이 **올라
   간다**. 상대 자원 항을 더하면 상쇄되지만, 두 항이 **같은 사실을 두 번 세는
   것**은 아닌지 확인해야 한다 (상대 덱 −1 과 상대 패 +1 은 한 번의 드로우다).
3. **연결 방식.** `StateValue` 에 항을 더할지, `Evaluator` 를 하나 더 둘지.
   전자는 3-E-42 의 네 칸 계약을 뒤집고, 후자는 `Evaluator` Protocol 로
   교체하면 되므로 Search 를 고치지 않는다.
4. **ranking 변화를 측정하고 의도된 것임을 문서화한다.** 이번 Phase 의 digest
   비교(510 결정 · 1,551 후보) 를 before 로 쓸 수 있다.

**다음 Phase 는 임의로 진행하지 않는다.**
