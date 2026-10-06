# Phase 3-F-3 — Opponent Resource Weighting and Search Integration

## 1. Phase / Base / 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-F-3 — 상대 자원 가중치와 Search 연결 |
| 성격 | **AUDIT-ONLY** (production 수정 0줄) |
| Base Phase | 3-F-2 — Opponent Resource Feature Foundation (판정 **A**) |
| Base baseline | 4,143 passed / 4 skipped |

**실제 HEAD 확인 (작업 시작 전)**

```
$ git rev-parse HEAD
fb34854734e312ac9472a1f7bc8094edbb61c969
$ git rev-parse --abbrev-ref HEAD
claude/pensive-goodall-te1egy
$ git status --short      → (비어 있음)
```

### Base commit SHA 정정

프롬프트가 적은 두 SHA 중 **하나가 존재하지 않는다.**

| 프롬프트 | 실제 | 상태 |
| --- | --- | --- |
| `f47d428` | **`f476428`** | 숫자 두 개가 바뀌었다 (`47d` → `476`) — 그 객체는 저장소에 없다 |
| `fb34854` | `fb34854` | 맞다 |

```
$ git cat-file -t f47d428   → 존재하지 않음
$ git cat-file -t f476428   → commit   (Phase 3-F-2: establish opponent resource feature)
```

실제 SHA 로 ancestor 를 확인하고 진행했다. Engine V1 freeze 를 유지한다.

---

## 2. 기존 score 구조

조사 11항목의 실측 결과다.

| 조사 항목 | 결과 |
| --- | --- |
| 1. `StateValue` | **네 칸** — `terminal`·`heuristic`·`terms`·`excluded` |
| 2. `StateValue.terms` | 이름 여섯, 순서 고정: `lp` `atk` `monsters` `spells` `deck` `hand` |
| 3. `StateValue.heuristic` | `sum(terms 값)` — 숨은 항이 없다 |
| 4. `Evaluator` Protocol | `evaluate(view) -> StateValue` (관측 **하나**) |
| 5. `SearchPolicy` | `evaluator: Evaluator = field(default_factory=StateEvaluator)` |
| 6. Search 가 비교하는 값 | `SearchCandidate.ordering_key()` → `(0, -terminal, -heuristic, canonical_state)` |
| 7. `SearchCandidate.value` | `StateValue | None`. `None` 이면 뒤로 보내고 **0 점으로 접지 않는다** |
| 8–9. 항과 단위 | 아래 표 — **전부 LP** |
| 10. 3-F-2 가 더한 것 | `OpponentResources`(장수) · `OpponentResourceDelta`(변화 + `drawn_from_deck`). 단위는 **장**, 가중치 없음 |
| 11. 같은 정보가 다른 항에 있는가 | **있다** — §4 가 그것을 다룬다 |

| 항 | 식 | 가중치 | 어느 쪽을 세는가 |
| --- | --- | --- | --- |
| `lp` | `me.lp − opp.lp` | — | 차 |
| `atk` | `(내 공격력 − 상대 공격력) × 1` | `ATK_IN_LP = 1` | 차 |
| `monsters` | `(내 몬스터 − 상대 몬스터) × 500` | `MONSTER_IN_LP = 500` | 차 |
| `spells` | `(내 마법함정 − 상대 마법함정) × 300` | `SPELL_TRAP_IN_LP = 300` | 차 |
| `deck` | `(내 덱 − 상대 덱) × 300` | `DECK_CARD_IN_LP = 300` | 차 |
| `hand` | `내 패 × 200` | `HAND_CARD_IN_LP = 200` | **내 쪽만** |

---

## 3. feature / source 관계

§3 이 요구한 표다.

| feature | source | 의미 | 단위 | score 에 들어가는가 |
| --- | --- | --- | --- | --- |
| `deck` 항 | `me.deck.size` · `opponent.deck.size` | 덱아웃까지의 거리 차 | LP | **들어간다** |
| `hand` 항 | `me.hand.size` | 내가 쥔 자원 | LP | **들어간다** |
| `monsters` 항 | 양쪽 `monster_zone.size` + EMZ | 필드에 선 수의 차 | LP | **들어간다** |
| `OpponentResources` | 상대 일곱 자리의 `size` | 상대가 들고 있는 장수 | **장** | **들어가지 않는다** |
| `drawn_from_deck` | 두 관측의 `hand`·`deck` 차 | 상대가 **새로 얻은** 자원 | **장** | **들어가지 않는다** |
| 상대 패의 **값** | — | — | — | **어느 항도 세지 않는다** |

**상대 패 장수를 세는 항이 하나도 없다** — 기존 설계가 그렇게 적어 두었다:

> 상대 패는 세지 않는다 — 장수는 보이지만 **그 값을 매기려면 내용을 알아야
> 한다.**

---

## 4. double-counting 조사

### 4-1. 상대가 1장 뽑으면 — `deck` 항이 **이미 움직인다**

실측 (상대만 1장 드로우):

```
term 변화: {lp:0, atk:0, monsters:0, spells:0, deck:+300, hand:0}
heuristic: +300
상대 패:   5 → 6      (어느 항도 세지 않는다)
상대 덱:  20 → 19     (deck 항이 +300 으로 센다)
```

**새 항을 더해도 "상대 패 +1" 을 두 번 세는 일은 없다** — 지금 그것을 세는 항이
하나도 없기 때문이다. 대신 기존 `deck` 항과 **같은 사건의 다른 결과**를 각자
세게 된다.

| 한 번의 드로우가 만드는 두 사실 | 지금 세는 항 |
| --- | --- |
| 상대 덱이 1 줄었다 (덱아웃에 1 가까워졌다) | `deck` **+300** |
| 상대 패가 1 늘었다 (쓸 수 있는 자원이 생겼다) | **없음** |

그래서 weight `W` 를 붙이면 한 장당 합계가 **`+300 − W`** 다. 두 항은 독립이
아니고, **이 식이 weight 결정의 전부**다 (§5).

### 4-2. 진짜 double-counting 위험 — 상대 몬스터가 죽을 때

실측 (내 공격으로 상대 앞면 몬스터가 묘지로):

```
term 변화: {atk:+1900, monsters:+500, 나머지 0}   합계 +2400
상대 총 장수:  25 → 25      ← 자리만 옮겼다
상대 묘지:      0 → 1
상대 몬스터:    1 → 0
drawn_from_deck: 0
```

**`atk` 와 `monsters` 가 이미 전부 센다.** 그러니 "상대 묘지가 늘었다" 를 항으로
더하면 **같은 사건을 두 번** 세게 된다.

| 상대 자원을 어떻게 항으로 쓰는가 | 이 사건에서 중복인가 |
| --- | --- |
| `drawn_from_deck` | **아니다** — 0 이고 반응하지 않는다 |
| `OpponentResources.total` | **아니다** — 25 → 25, 변하지 않는다 |
| `opponent.grave` 하나만 | **그렇다** — +1 이 되어 `monsters` 와 겹친다 |
| `opponent.monsters` 하나만 | **그렇다** — `monsters` 항과 같은 사실이다 |

**결론**: `drawn_from_deck` 을 쓰는 한 중복은 없다. `grave`/`monsters` 를 직접
항으로 쓰면 중복이다. 이것이 3-F-2 가 `drawn_from_deck` **하나만** 득으로 세기로
한 설계가 지금 값을 갖는 자리다.

---

## 5. weight 결정 근거

### 5-1. 유도되는 값은 **하나**뿐이다

한 장당 합계가 `+300 − W` 이므로:

| W | 뜻 |
| --- | --- |
| `W < 300` | 상대가 뽑아도 **여전히 나에게 이득**으로 읽힌다 (3-F-1 의 결함이 남는다) |
| **`W = 300`** | **중립** — 뽑기 자체가 점수를 움직이지 않는다 |
| `W > 300` | "상대에게 주는 것은 나쁘다" 를 **단정**한다 |

`W = 300` 은 `DECK_CARD_IN_LP` **그 자체**다. 고른 것이 아니라 **유도된다.**
그리고 §9 가 금지한 "상대에게 3장을 주면 무조건 나쁜 행동" 규칙을 만들지 않는
유일한 값이다.

`HAND_CARD_IN_LP = 200` 을 대칭으로 쓰는 것은 **근거가 되지 않는다** —
`900 − 3×200 = +300` 으로 여전히 이득으로 읽히고, 게다가 기존 설계가 상대 패에
값을 매기지 않기로 적어 두었다 (§3).

### 5-2. 그런데 **붙이지 않았다.** 붙여도 아무 일도 일어나지 않는다

이것이 이 Phase 의 결론이고, 구조적 사슬로 측정했다.

| # | 사실 | 측정 |
| --- | --- | --- |
| 1 | 등재 효과 16개 중 상대에게 카드를 주는 것은 **하나** | `5915629` → `DrawOperation(who=opponent, count=2)` |
| 2 | 그 카드는 **함정**이다 | 공식 DB: **욕망의 선물**, `type_names = {TRAP}` |
| 3 | 함정은 live 발동 관문의 **범위 밖**이다 | 손에 쥐어도 관문이 `UNKNOWN / RULE_NOT_IMPLEMENTED` |
| 4 | 그래서 **후보가 되지 않는다** | 같은 판에서 욕망의 항아리(마법)는 후보, 욕망의 선물(함정)은 아니다 |
| 5 | 그래서 한 결정 안에서 상대 자원 결과가 **언제나 같다** | **273 / 273** · 욕망의 선물 덱으로 **510 / 510**, 변동 **0** |
| 6 | 그래서 어떤 weight 도 **상수 오프셋**이고 순위를 못 바꾼다 | 오프셋 0 · −900 · +5000 에서 순서 동일 |

3번의 까닭은 이미 이름이 붙어 있다 (Phase 3-E-44 가 측정했다):

> `trap-activation-timing (함정의 유발 조건을 효과마다 구분할 수 없다 — 공식
> 스크립트의 SetCode(EVENT_*) 가 EffectDefinition 에 없다)`

**막고 있는 것은 가중치가 아니라 행동 공간이다.** 그리고 그 자리를 고치는 것은
§15 가 금지했다 (`LegalActions` · 발동 경로).

### 5-3. 왜 "그래도 붙여 두면 되지 않는가" 가 아닌가

붙이면 **값이 맞는지 확인할 방법이 없다.** 순위가 바뀌는 결정이 하나도 없으므로
어떤 duel 로도 `W = 300` 이 `W = 100` 보다 나은지 보일 수 없다. 그 상태에서
상수를 심으면, 나중에 함정 발동이 열릴 때 **검증되지 않은 값이 이미 자리를 잡고
있게** 된다. §4 가 "근거 없는 큰 숫자를 사용하지 않는다" 고 한 것의 연장이다.

---

## 6. LP / board / 다른 term 과의 scale 관계

§6 이 요구한 조사다. **normalization 을 새로 만들지 않았다** — 단위가 이미 LP
하나다 (3-F-1 §9 가 같은 결론을 적었다).

상대 자원을 **만약** LP 로 환산한다면 그 크기가 어디에 놓이는지:

| 비교 대상 | 값 (LP) | 상대 자원 1장(가정 300) 과의 비 |
| --- | --- | --- |
| `terminal` 등급 | **숫자가 아니다** | 비교 불가 — 등급이 다르면 휴리스틱을 보지 않는다 |
| 몬스터 하나 | 500 | 0.6배 |
| 마법·함정 하나 | 300 | 1.0배 |
| 덱 한 장 | 300 | 1.0배 |
| 내 패 한 장 | 200 | 1.5배 |
| ATK 1점 | 1 | 300배 |
| 증G benchmark 의 전개 3마리 | `atk 5700 + monsters 1500 = 7200` | 자원 3장(900) 은 그 **12.5%** |

**한 feature 가 다른 feature 를 무시하게 만드는 크기가 아니다** — 자원 3장(900)이
전개 3마리(7200)를 뒤집지 못하고, 그것이 §9 가 요구한 trade-off 다. `terminal` 만
숫자 공간 밖에 있고, 그것은 사전식 비교로 **분리**되어 있어 추월이 불가능하다.

이 표는 **weight 를 붙일 때 쓸 근거**로 기록한다. 이번에 붙이지 않았으므로
normalization 도 필요하지 않았다.

---

## 7. Search 연결

### **하지 않았다.**

`agent/search.py` 에 상대 자원이 들어가지 않는다 — `OpponentResource` ·
`opponent_resource` · `drawn_from_deck` 문자열이 **하나도 없다**. 비교는 여전히
`StateValue.ordering_key()` 하나로만 한다.

§7 이 금지한 것도 전부 확인했다 — Depth-2 · MCTS · beam search ·
opponent response search · self-play · RL · neural network **없음**. 새 Search
algorithm **없음**.

흐름은 그대로다:

```
GameStateView → StateEvaluator → StateValue(항 여섯) → SearchPolicy → ranking
                    ↑
      OpponentResources / OpponentResourceDelta 는 **이 경로 밖**이고,
      측정 · 설명 도구로 남는다 (3-F-2 가 둔 자리 그대로).
```

---

## 8. Search ranking before / after

production 을 고치지 않았으므로 바뀔 자리가 없다. 그래도 **측정했다** — 3-F-2 가
쓴 것과 같은 방법(결정마다 정렬된 후보 전체의 `ordering_key`, 고른 행동,
`simulations`, `skipped`, `comparable_count` 를 해시)으로 세 상태를 비교한다.

| | 3-F-1 (feature 없음) | 3-F-2 | **3-F-3 (이번)** |
| --- | --- | --- | --- |
| Search 결정 수 | 510 | 510 | **510** |
| 비교한 후보 총수 | 1,551 | 1,551 | **1,551** |
| `state_hash` 8개 | — | 동일 | **동일** |
| 후보 순서 digest | `f5e27134…` | `f5e27134…` | **`f5e27134…`** |

§8 이 요구한 일곱 항목:

| § | 항목 | 결과 |
| --- | --- | --- |
| 1 | Search decision count | 510 — 변화 없음 |
| 2 | candidate count | 1,551 — 변화 없음 |
| 3 | candidate ordering digest | 동일 |
| 4 | `state_hash` | 8개 전부 동일 |
| 5 | selected action | digest 에 포함, 동일 |
| 6 | score/value | 항 여섯·가중치 다섯 그대로 |
| 7 | deterministic repeatability | 동일 입력 30회 동일 결과 |

### §8 의 핵심 질문에 대한 답

> "같은 상태에서 opponent resource penalty 가 추가되었기 때문에 의도적으로 더
> 적은 상대 자원을 주는 action 의 ranking 이 올라가는가?"

**그런 선택이 현재 행동 공간에 존재하지 않는다.** "드물다" 가 아니라 **273/273 ·
510/510 으로 0건**이다. 한 결정의 모든 후보가 상대 자원을 같은 수로 남기므로,
penalty 는 그 결정에서 모든 후보에 **같은 양**이 더해지는 상수이고, `ordering_key`
는 상수 오프셋에 불변이다.

관측된 상대 자원 변화 71건의 정체도 밝혔다 — **둘 다 "내가 준 자원" 이 아니다.**

| 변화 | 건수 | 정체 | 내가 준 것인가 |
| --- | --- | --- | --- |
| `grave+1 monsters-1` | 57 | `attack` — **내 공격으로 상대 몬스터가 죽었다** | 아니다 (내 **득**) |
| `hand+2 deck-2 grave+1 spells-1` | 14 | `pass` — **상대가 자기 욕망의 항아리를 해결했다** | **아니다** (상대 자기 카드) |

14건이 특히 중요하다. 그것을 벌점으로 세면 **"상대 턴에 우선권을 넘기는 것"**
에 벌점을 매기게 되고, 그것은 전략적 선택이 아니라 규칙상의 의무다. 의도와
**반대 방향**의 ranking 변화가 생긴다.

---

## 9. 증식의 G benchmark

§9 의 두 상태다. 카드도 효과도 쓰지 않고 모양만 손으로 만들었다.

| | 내 전개 | 상대에게 | `atk` | `monsters` | `deck` | `hand` | `heuristic` | `drawn` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **A** | 3 | 3 | 5,700 | 1,500 | **900** | 400 | **+8,500** | **3** |
| **B** | 3 | 0 | 5,700 | 1,500 | **0** | 400 | **+7,600** | **0** |

내 전개 쪽 항(`atk`·`monsters`·`spells`·`hand`·`lp`)은 **한 칸도 다르지 않다.**
차이 **+900 전부가 `deck` 항**에서 오고, 그것은 정확히 `3 × DECK_CARD_IN_LP` 다.

### weight 를 붙였다면 (산술만, 적용하지 않았다)

```
A − B = 900 − 3W
```

| W | A − B | 뜻 |
| --- | --- | --- |
| 0 (현재) | **+900** | A 가 더 좋다고 읽는다 |
| 100 | +600 | 여전히 A |
| 200 | +300 | 여전히 A |
| **300** | **0** | **중립** |
| 400 | −300 | B 가 더 좋다 |
| 500 | −600 | B 가 더 좋다 |

§9 가 요구한 대로 **"A 가 무조건 나쁘다" 를 정답으로 두지 않았다.** `W = 300`
에서 trade-off 가 **정확히 균형**이고, 그 지점이 유도되는 유일한 값이다 (§5).

그리고 §8 이 보인 대로, 이 benchmark 의 A/B 는 **같은 결정의 두 후보가 아니다** —
손으로 만든 두 판이다. 실제 Search 에서는 A 와 B 를 **고를 수 없다.**

---

## 10. 다른 유사 효과의 일반성 확인

§10 이 요구한 확인이다. **증G 전용 로직 없이 같은 feature 로 들어간다.**

증거는 benchmark 가 아니라 **등재된 실제 카드**다 — `5915629` **욕망의 선물**은
증식의 G 와 **다른 카드**이고 `DrawOperation(who=opponent, count=2)` 를 가진다.
그 효과가 해결되면 상대 패 +2 · 덱 −2 가 되고, 그것은 `drawn_from_deck = 2` 로
**같은 feature 에** 들어간다.

| 확인 | 결과 |
| --- | --- |
| production 에 카드 이름/passcode 가 있는가 | **없다.** `agent/evaluation.py` 는 `card_id` 도 `name` 도 읽지 않는다 (3-F-2 `test_04`) |
| 효과를 **연산**으로 찾을 수 있는가 | **그렇다.** `DrawOperation.who == opponent` 로 16개 중 1개를 찾았다 |
| 같은 경로로 들어가는가 | **그렇다.** 장수 변화만 보므로 어느 카드가 일으켰는지 묻지 않는다 |
| 마루챠미 후와로스 | **등재되어 있지 않다** — 16개 라이브러리에 없으므로 이 엔진에서 측정할 수 없다. 카드 이름을 production 에 넣지 않았다 |

측정이 밝힌 것이 하나 더 있다. 14건의 `pass` 사례는 **상대가 자기 욕망의 항아리를
해결한 것**이다 — 즉 이 feature 는 "내가 준 자원" 과 "상대가 스스로 얻은 자원" 을
**장수만으로는 구분하지 못한다.** weight 를 붙이려면 그 구분이 먼저 필요하고,
그것은 "누가 그 효과를 발동했는가" 를 보는 일이므로 delta 하나로는 안 된다.
**§7 의 DEFERRED 목록에 더한다.**

---

## 11. hidden information

**3-F-2 의 경계를 그대로 유지했다.** production 을 고치지 않았으므로 새로 생긴
접근 경로가 없다.

| 금지 | 확인 |
| --- | --- |
| 상대 hidden hand 직접 접근 | **없음** — `size` 만 읽는다 |
| 상대 deck contents 접근 | **없음** |
| 숨겨진 카드 identity 추정 | **없음** |
| Opponent Model · Bayesian belief | **없음** |
| 상대 덱 리스트를 score 에 | **없음** — 덱 구성이 달라도 장수가 같으면 점수가 같다 |

욕망의 선물의 passcode 는 **테스트 파일에만** 있다. production 에는 들어가지
않았고, 그 사실도 테스트가 지킨다.

---

## 12. state_hash / RNG

| 질문 | 결과 |
| --- | --- |
| `GameState` mutation | **없음** — 30회 평가 전후 `state_hash` 동일 |
| RNG 소비 | **없음** — `rng.getstate()` 전후 동일 |
| random choice | **없음** |
| Engine action 실행 | **없음** |
| hidden info bypass | **없음** |
| 동일 state → 동일 evaluation | **그렇다** (30회) |
| clone 동일 결과 | **그렇다** |
| 실제 듀얼 8판 `state_hash` | **전부 동일** (§8) |

---

## 13. 테스트 결과

### 새로 더한 것

`tests/agent/test_opponent_resource_weighting_audit.py` — **16개** (전부 통과).

| 묶음 | 내용 |
| --- | --- |
| A (`test_01`–`08`) | **왜 weight 가 아무 일도 못 하는가** — 효과 1개 · 함정 · 범위 밖 · 후보 아님 · 결정 안에서 불변 · 상수 오프셋 불변 · 실제 듀얼 · 막는 것은 발동 계층 |
| B (`test_09`–`11`) | **double-counting 추적** — 드로우는 `deck` 항이 이미 센다 · 몬스터 죽음은 이미 전부 센다 · `drawn_from_deck` 은 거기 반응하지 않는다 |
| C (`test_12`–`13`) | **benchmark 산술** — 차이가 정확히 `3 × DECK_CARD_IN_LP` · 유도되는 W 는 300 이고 "중립" 을 뜻한다 |
| D (`test_14`–`16`) | 가중치 0건 · 네 칸·항 여섯·Search 그대로 · 순수성과 관측 경계 유지 |

### §14 의 14개 요구와 대응

| § | 요구 | 어디서 |
| --- | --- | --- |
| 1 | 동일 상태 deterministic | `test_16` (30회) |
| 2 | 상대 자원 0 vs 3 의 score 차이 | `test_12` (+900 = `3 × 300`) |
| 3 | 내 전개 동일 + 상대 자원 차이 | `test_12` (내 쪽 항 전부 동일) |
| 4 | board score 와 double-counting 없음 | `test_10`·`test_11` |
| 5 | deck/draw double-counting 없음 | `test_09` |
| 6 | LP 와 상대 자원 scale | §6 의 표 + `test_13` |
| 7 | hidden info 접근 없음 | `test_16` + 3-F-2 `test_04` (수정 0건) |
| 8 | state mutation 없음 | `test_16` |
| 9 | RNG 소비 없음 | `test_16` |
| 10 | clone 동일 | `test_16` |
| 11 | Search ranking 의 **의도된 변화** | **없음**이 답이다 — `test_05`·`test_06`·`test_07` 이 왜 없는지 고정 |
| 12 | 동일 seed deterministic | §8 의 digest (3회 측정 동일) |
| 13 | `RuleBasedPolicy` regression | 전체 회귀 + `agent/heuristic.py` diff 0 |
| 14 | 전체 regression | 아래 |

### 전체 회귀

```
$ python3 -m pytest tests/agent/test_opponent_resource_weighting_audit.py -p no:randomly -q
16 passed in 4.46s

$ python3 -m pytest -p no:randomly -q
4159 passed, 4 skipped in 399.58s (0:06:39)
```

| | 통과 | skip |
| --- | --- | --- |
| Phase 3-F-2 직후 (baseline) | 4,143 | 4 |
| Phase 3-F-3 (이번) | **4,159** | 4 |
| 차이 | **+16** | 0 |

**+16 이 이번에 더한 시험 수와 정확히 같다.** 기존 테스트 **수정 0건** —
production 을 고치지 않았으므로 기존 계약이 깨질 자리가 없었다.

### 고의 위반 검증 — 6건, 전부 잡았다

| # | 위반 | 잡은 테스트 |
| --- | --- | --- |
| 1 | 상대 자원 벌점 항을 실제로 더한다 | `test_09`·`test_12`·`test_15` |
| 2 | `DECK_CARD_IN_LP` 300 → 250 | `test_12`·`test_13`·`test_14` |
| 3 | 함정을 발동 범위 안으로 받는다 | `test_03`·`test_04`·`test_08` |
| 4 | Search 가 상대 자원을 import 한다 | `test_15` |
| 5 | 묘지 증가도 "상대가 얻었다" 로 센다 | `test_11` |
| 6 | `MONSTER_IN_LP` 를 0 으로 | `test_10` (**처음엔 못 잡았다** → 고쳤다) · `test_14` |

**6번을 처음 놓쳤다.** `test_10` 이 `after - before == MONSTER_IN_LP` 로 **상수와만**
견주고 있었고, 그 상수를 0 으로 바꾸면 `0 == 0` 이 되어 통과했다. 실제 숫자(500 ·
합계 2400)도 함께 못박아 고쳤고, 그 까닭을 테스트 docstring 에 적었다.

복원은 매번 md5 로 확인했다.

---

## 14. 최종 판정

### **B. WEIGHT_NOT_YET_JUSTIFIED**

근거:

* **weight 를 유도할 수는 있다** — `W = DECK_CARD_IN_LP = 300` 이 유일하게
  유도되는 값이고, 그 값은 상대의 드로우를 **중립**으로 만든다 (§5-1).
* **그런데 그 값이 맞는지 확인할 방법이 없다.** 상대 자원 결과가 한 결정 안에서
  **언제나 같으므로** (273/273 · 510/510), 어떤 weight 도 상수 오프셋이고
  순위를 바꾸지 못한다. `W = 300` 이 `W = 100` 보다 나은지 **어떤 duel 로도
  보일 수 없다.**
* **막고 있는 것은 가중치가 아니라 행동 공간이다.** 상대에게 카드를 주는 등재
  효과가 하나뿐이고(욕망의 선물), 그것이 **함정**이라서 발동 관문의 범위 밖이다
  (`trap-activation-timing`). 그 자리를 고치는 것은 §15 가 금지했다.
* **§16-A 의 요구를 만족할 수 없다** — "Search 가 이를 소비하며 **의도된
  ranking 변화가 확인됨**". 변화가 확인되지 않는 것이 아니라, 변화가 가능한
  **선택 자체가 없다.**
* 그리고 지금 붙이면 **검증되지 않은 상수가 자리를 잡는다** — 나중에 함정 발동이
  열릴 때 그것이 기본값이 되어 있다.

`A. OPPONENT_RESOURCE_WEIGHTED` 가 아닌 까닭: 위 네 번째 항목. weight 를 심는
것은 가능했지만 **소비와 검증이 불가능**하다.

`C. STRUCTURAL_BLOCKER_FOUND` 가 아닌 까닭: Evaluation/Search 구조에는 막는
것이 없다. `StateEvaluator` 에 항을 더하는 것도, `Evaluator` 를 교체하는 것도
열려 있다. 막는 것은 **발동 계층의 함정 범위**이고 그것은 이미 이름이 붙어
기록된 공백이다(3-E-44) — 새로 발견한 blocker 가 아니다.

### 이번 Phase 에서 하지 않은 것

§15 의 금지 목록 전부 확인:

* Engine V1 · `GameState` · `GameStateView` architecture · Trigger pipeline ·
  Chain · Priority · `LegalActions` · `ActionExecutor` · card effect execution
  — **전부 수정 0줄**
* Opponent Model · Deck Builder · Card Evaluation AI · Self-play · RL ·
  Neural Network · MCTS · Depth-2 Search · UI/API · README · Lua 구조 — **없음**
* 가중치 상수 **추가 0건** · 새 UNKNOWN enum **없음** · 카드 이름/passcode 를
  production 에 **넣지 않음**

```
$ git diff --stat -- engine agent app core analysis rules rulings sources scripts
(출력 없음 — production 수정 0줄)
```

산출물은 둘뿐이다: `tests/agent/test_opponent_resource_weighting_audit.py` (신규) ·
`docs/phase3f3-opponent-resource-weighting.md` (이 보고서).

---

## 15. 다음 Phase 후보 (1개)

**Phase 3-F-4 — 함정 발동의 유발 조건 구분 (`SetCode(EVENT_*)` → `EffectDefinition`)**

이 Phase 가 측정한 사슬의 **3번**을 푸는 일이다. 그것이 풀리면 나머지가 따라온다.

```
함정이 발동 후보가 된다
   → 욕망의 선물이 후보가 된다
   → 한 결정 안에서 상대 자원 결과가 **달라진다**
   → weight 가 상수 오프셋이 아니게 된다
   → W = 300 이 맞는지 **실제 duel 로 검증할 수 있다**
```

그 Phase 가 답해야 할 것:

1. 공식 스크립트의 `SetCode(EVENT_*)` 를 `EffectDefinition` 에 **어떻게** 옮기는가.
   지어내지 않고 옮길 수 있는지부터 재야 한다.
2. 유발 조건 없는 함정(`EVENT_FREE_CHAIN`) 과 유발 함정을 구분한 뒤에도
   `ActivationTimingChecker` 가 세트한 턴·스펠 스피드를 볼 수 있는가
   (RULE-SPELLTRAP-007 · 009).
3. 그 변경이 **Engine V1 freeze 와 충돌하는가** — 발동 경로를 건드리므로
   별도 승인이 필요할 수 있다.

**이 Phase 는 그 작업을 하지 않았다.**

---

## Commit · Push 기록

| 항목 | 값 |
| --- | --- |
| 결과 commit | `f1772fe` — `Phase 3-F-3: weight opponent resource evaluation` |
| 브랜치 | `claude/pensive-goodall-te1egy` |
| Push | `fb34854..f1772fe` → `origin/claude/pensive-goodall-te1egy` (성공) |
| production diff | **0 줄** |
| 기존 테스트 수정 | **0건** |
| 변경 파일 | 신규 테스트 1 · 신규 보고서 1 |

**다음 Phase 는 임의로 진행하지 않는다.**
