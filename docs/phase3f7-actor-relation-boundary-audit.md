# Phase 3-F-7 — 행위자 관계 경계 감사 (Event ↔ Candidate)

## 1. Phase · Base · 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-F-7 — Actor Comparison Boundary / Event↔Candidate Relation Audit |
| 모드 | **AUDIT-ONLY** (production diff 0) |
| Base | Phase 3-F-6 (`1f117fe` 작업 · `72a0814` 보고서) |
| 3-F-6 최종 판정 | **C. TRIGGER_SPEC_ARCHITECTURAL_GAP** |
| **실제 HEAD (측정)** | `72a0814 Phase 3-F-6 보고서: commit SHA · push 결과 기록` |
| branch | `claude/pensive-goodall-te1egy` |
| baseline 테스트 | 4,215 passed / 4 skipped |
| 새 테스트 | `tests/test_actor_relation_boundary_audit.py` — **19건** |

`git log` 로 HEAD 를 확인했고 작업 트리는 깨끗했다. 3-F-6 보고서의 판정 줄도
읽어 **C** 임을 확인했다.

### 🔴 프롬프트의 전제 둘을 측정해서 정정했다

이 Phase 는 프롬프트에 적힌 사실을 그대로 받지 않고 다시 쟀다. 둘이
틀렸다.

| 프롬프트의 전제 | 측정 결과 |
| --- | --- |
| "`_event_relation` 이 이 역할을 일부 담당하지만 현재 구조에서는 **event 쪽과 candidate 쪽 정보를 함께 사용한다**" | **아니다.** 서명이 `(spec, event)` 이고 **candidate 를 받지 않는다**. 본문에 `candidate` · `controller` · `actor` 가 **한 번도** 나오지 않는다 (`test_03` · `test_04`). 3-F-6 의 측정과 같다 |
| "`judge()` 는 양쪽 정보를 받지만 실제로는 fold 하여 **일부 정보를 잃는다**" | **`fold` 는 아무것도 버리지 않는다.** 관문 판정을 **전부 보존**한 채 요약 `status` 를 덧붙인다 (`test_09`). 실제로 잃는 것은 다른 것이다 — **`judge` 의 출력에 사건이 없다** (`test_10`) |

두 번째는 **내 3-F-6 보고서의 표현에도 책임이 있다.** 그때 "judge 는 관문의
답을 접기만 한다" 고 적었고, 그것이 "정보를 잃는다" 로 읽혔다. 정확한
사실은 **"접으면서 원본을 함께 들고 있고, 대신 사건은 담지 않는다"** 다.

---

## 2. Event actor 정의

`TimingEvent.actor: int | None` — "이 사건을 일으킨 플레이어. 알 수 없으면
`None`".

### 어디서 오는가 (`test_01`)

`TimingEvent.from_delta` 가 변화의 **사람 칸**에서 그대로 옮긴다.

| 변화 | actor |
| --- | --- |
| `MonsterSummoned` | `delta.player` (소환한 사람) |
| `CardDrawn` | `delta.player` |
| `LifeChanged` | `delta.player` |
| `ZoneMoved` | `delta.to_player` |
| `EffectEvent` / `CostPaymentEvent` | `event.actor` |

### 🔴 없는 경우가 **실재한다**

| 사건 | actor | 왜 |
| --- | --- | --- |
| `PhaseChanged` | **`None`** | **일부러** 적지 않는다 — 페이즈 전이는 규칙이 하는 일이고, "누가 그것을 선언했는가" 는 우선권 계층의 질문이다 (코드 주석) |
| `UNIMPLEMENTED` (`timing_for` 가 옮길 이름을 못 찾은 변화 — 예: `ZoneShuffled`) | **`None`** | 사건 자체를 표현하지 못한다 |
| `TimingEvent.unimplemented(note)` | **`None`** | 기본값 |

`actor` 는 `0` · `1` · `None` 뿐이다 — `2` 를 넣으면 `TriggerError` 가 난다.

---

## 3. Candidate controller 정의

`TriggerCandidate.controller: int` — **언제나 `0` 또는 `1`** 이다
(`__post_init__` 이 `not in (0, 1)` 을 거절한다). `None` 을 넣으면 예외다.

### 모를 수가 없는 이유가 **구조**에 있다 (`test_02`)

후보는 `TriggerCollector._visible_copies` 가 찾은 **보이는 카드**에서만
생긴다. 가려진 자리(상대 패 · 덱 · 뒷면)는 후보가 되지 않고
`TriggerCollection.unchecked` 에 **따로** 적힌다 — "관측에 없다고 '후보가
없다' 고 답하면 모르는 것을 거짓으로 접는 것이다" (코드 주석).

> 그래서 §14 의 **D("controller 정보가 없다") 는 일어날 수 없다**, 그리고
> controller 를 읽는 것이 숨은 정보를 건드리지 않는다 (§12).

**비대칭이 여기서 시작된다**: 사건 쪽 행위자는 없을 수 있고, 후보 쪽
컨트롤러는 언제나 있다.

---

## 4. EventRelation 전체 조사

### 입력 · 출력

| | |
| --- | --- |
| 서명 | `_event_relation(self, spec: TriggerSpec, event: TimingEvent) -> GateVerdict` |
| 반환 | `GateVerdict` (= `EligibilityGate` + `ValidationResult`) |
| production consumer | **없음** |
| dormant consumer | `TriggerEligibilityJudge.judge` 하나 |

### 읽는 것 / 읽지 않는 것 (`test_03` — docstring 을 뺀 **코드만** AST 로 봤다)

| 읽는다 | 읽지 않는다 |
| --- | --- |
| `event.point` · `event.note` | **`event.actor`** |
| `event.operation` · `event.from_zone` · `event.to_zone` | **`event.delta.summon`** |
| `spec.operations` · `spec.from_zones` · `spec.to_zones` | **`candidate`** (받지도 않는다) |
| `spec.matches(event)` | **`candidate.controller`** |
| | `self._view` (판을 읽지 않는다) |

### 네 갈래 (3-E-45 가 만든 셋 + 통과)

`_gate(...)` 호출이 **정확히 4개**다 (AST 로 셌다).

| # | 조건 | validity / code |
| --- | --- | --- |
| 1 | 사건이 `UNIMPLEMENTED` | `UNKNOWN` / `RULE_NOT_IMPLEMENTED` |
| 2 | 시점은 같은데 선언이 걸어 둔 필터를 사건이 안 들고 있다 | `UNKNOWN` / `INFORMATION_UNAVAILABLE` |
| 3 | `spec.matches(event)` | `VALID` / `OK` |
| 4 | 그 밖 | `INVALID` / `CANDIDATE_NOT_ELIGIBLE` |

### §4 의 YES/NO — **NO**

> "현재 `EVENT_RELATION` 은 이미 `event.actor` ↔ `candidate.controller` 를
> 비교하기 위한 정확한 계층인가?"

**아니다.** 두 가지 이유가 겹친다.

1. **입력이 하나 없다.** candidate 를 받지 않는다. 받는 관문 셋
   (`_activation_zone` · `_trigger_condition` · `_cost_feasibility`) 은
   **사건을 받지 않는다.** 둘 다 받는 관문은 **0개**다 (`test_04`).
2. **그러나 의미상으로는 여기가 맞다** (§10). 그래서 판정이 **B 가 아니라
   C** 로 가는 것이 아니고, 아래 §17 에서 따로 정리한다.

---

## 5. judge() 정보 흐름

### `fold` 는 **버리지 않는다** (`test_09`)

```
fold(candidate, gates):
    status = FORBIDDEN / INELIGIBLE / UNKNOWN / ELIGIBLE  (가장 강한 것)
    return cls(candidate=candidate, status=status, gates=gates)   ← 그대로 싣는다
```

세 관문(VALID · INVALID · UNKNOWN)을 넣어 실측했다.

| 확인 | 결과 |
| --- | --- |
| `status` | `INELIGIBLE` (가장 강한 거부) |
| `gates` | **셋 다 그대로** 남아 있다 |
| `gate(TRIGGER_CONDITION).code` | `INFORMATION_UNAVAILABLE` — 보존 |
| `gate(ACTIVATION_ZONE).code` | `SOURCE_WRONG_ZONE` — 보존 |
| `blocking` | 검사 순서대로 둘 |
| UNKNOWN 과 INVALID | **섞이지 않는다** |

> **"정보가 없어서 UNKNOWN" 과 "관계가 FALSE 라서 INVALID" 는 관문 단위로
> 구분된 채 남는다** (§13 의 질문에 대한 답). 요약 `status` 하나만 보면
> 어느 관문이 막았는지 모르지만, 그것은 **요약의 성질**이고 손실이 아니다 —
> `gates` · `gate(g)` · `blocking` 으로 언제든 꺼낸다.

### 🔴 실제로 잃는 것 — **사건** (`test_10`)

```
judge(candidate, spec, event)  ← 사건을 받는다
    ↓
TriggerEligibility(candidate, status, gates, unchecked_rules)   ← 사건이 없다
```

`TriggerEligibility` 의 필드는 넷이고 `event` 가 **없다**.
`canonical_state()` · `to_dict()` 에도 없다 — 실측으로 직렬화에
`"actor"` 라는 문자열이 **하나도** 들어가지 않음을 확인했다.

반면 `TriggerCollection` 에는 `event` 칸이 **있다.** 즉 **사건을 잃는 자리가
정확히 `judge` 다.** 관문이 산문(`reason`)에 적어 둔 것 말고는 행위자가
판정 결과에 남지 않고, replay 로도 되살릴 수 없다.

---

## 6. SELF / OPPONENT / UNKNOWN fixture

세 fixture 를 **같은 선언**(`MONSTER_SUMMONED` · `activates_from={MZONE}`)으로
돌렸다.

| | Fixture A | Fixture B | Fixture C |
| --- | --- | --- | --- |
| 뜻 | **내가** 특수소환 | **상대가** 특수소환 | 누가 했는지 **모름** |
| `event.point` | `monster_summoned` | `monster_summoned` | `unimplemented` |
| `event.actor` | `0` | `1` | **`None`** |
| summon kind | `special` | `special` | — |
| `candidate.controller` | `0` | `0` | `0` |
| **기대 관계** | `SELF` | `OPPONENT` | `UNKNOWN` |
| **실제 `EVENT_RELATION`** | `VALID` / `OK` | **`VALID` / `OK`** | `UNKNOWN` / `RULE_NOT_IMPLEMENTED` |
| `actor != controller` | `False` | `True` | **`True`** ← 위험 |

### A 와 B 가 **같은 답**이다

기대는 달라야 하는데 판정이 같다. 관계를 보는 코드가 없으므로 당연한
결과다.

### C 는 `UNKNOWN` 이 맞다 — 그런데 **이유가 다르다**

억지로 `INVALID` 로 만들지 않았다. 실제로 `UNKNOWN` 이 난다. 다만 그
`UNKNOWN` 의 이유는 **"행위자를 모른다" 가 아니라 "그 사건 자체를 옮길
이름이 없다"** 다 — `reason` 에 "표현하지 못하는 사건" 이 들어 있고
`"actor"` 는 없다. **행위자 부재를 가리키는 판정은 존재하지 않는다.**

### 🔴 행위자만 뒤집으면 **한 글자도 달라지지 않는다** (`test_08`)

이 Phase 의 중심 측정이다. 판과 후보를 **고정**하고 사건의 사람 칸만 바꿨다.

| 확인 | 결과 |
| --- | --- |
| 다섯 관문의 (validity, code) | **완전히 같다** |
| 접힌 `status` | **같다** |
| `canonical_state()` | **같다** |

> **§3 ③ 을 하는 코드가 하나도 없다.**

#### 🟡 처음에 함정에 걸렸다 — 보고서에 남긴다

처음에는 실제 듀얼에서 "내가 소환" 과 "상대가 소환" 을 **각각 실행**해
비교했고, 접힌 상태가 `unknown` 과 `ineligible` 로 **달라 보였다.** 관계를
구분한 것처럼 읽혔다.

그것이 아니었다. 다섯 관문을 하나씩 열어 보니 차이는
`activation_zone = INVALID / SOURCE_WRONG_ZONE` 에서 왔다 — 상대가 소환하면
판이 달라져 **첫 후보가 MZONE 밖의 카드**가 된 것이다. `EVENT_RELATION` 은
양쪽 다 `VALID / OK` 로 **같았다.**

그래서 판과 후보를 고정하고 사건의 사람 칸만 바꾸는 쪽으로 측정을 고쳤다.

> **접힌 `status` 를 보고 "엔진이 자신과 상대를 구분했다" 고 읽으면
> 틀린다.** 이 함정은 실제로 사람을 속일 수 있으므로 테스트 docstring 에도
> 적어 두었다.

---

## 7. "상대" 의 의미 — 기존 API 조사

### 🔴 `event.actor != candidate.controller` 를 "상대" 라고 단정하면 **틀린다** (`test_11`)

행위자가 없는 사건에서 그 비교는 **양쪽 플레이어 모두에 대해 참**이 된다.

```
unknown_actor.actor is None
unknown_actor.actor != 0   →  True
unknown_actor.actor != 1   →  True     ← 둘 다 "상대" 가 되어 버린다
```

그것은 "상대가 했다" 가 아니라 "누가 했는지 모른다" 다. `PhaseChanged` 와
모든 `UNIMPLEMENTED` 사건이 이 자리에 온다. 안전한 비교는 **먼저 존재를
묻는 것**이다.

### 기존 player relation 헬퍼 — 일곱 자리, 전부 `1 - x` (`test_12`)

| 자리 | 클래스 |
| --- | --- |
| `engine/condition/context.py` | `ConditionContext.opponent` |
| `engine/priority.py` | `PriorityHolder.opponent` |
| `engine/effect/resolution.py` | `ResolutionContext.opponent` |
| `engine/action.py` | `PlayerAction.opponent` |
| `engine/game_state_view.py` | `GameStateView` (`opponent` · `opponent_id`) |
| `engine/timing.py` | `TimingWindow.opponent` |

**새 Player API 를 만들지 않았다.** 기존 것을 그대로 조사했다.

### 🔴 그 헬퍼들에 `UNKNOWN` 경로가 **하나도 없다**

전부 `{0, 1}` 위의 **전역 함수**다.

```
ConditionContext(player=None)  →  ValueError: player 는 0 또는 1 입니다
1 - None                       →  TypeError
```

모르는 사람을 받으면 **보류가 아니라 거절**이다. 그래서 §14 의 **E("관계를
계산할 수 없다") 는 `ValidationCode` 가 아니라 예외로 나타난다.**

### 2인 게임 가정이 어디에 있는가

한 군데 API 가 아니다 — `1 - ` 가 여덟 모듈에 **14회 이상** 흩어져 있고
(`duel.py` · `action.py` · `state/turn.py` · `condition/context.py` ·
`effect/resolution.py` · `turn_progression.py` · `observation_grant.py` ·
`action_validation.py`), 각 클래스의 `__post_init__` 이 `not in (0, 1)` 로
그 가정을 되풀이한다.

### 🔴 엔진에 "상대" 가 **이미 두 가지 뜻**으로 있다 (`test_13`)

| 이름 | 기준 | 한국어 표기 |
| --- | --- | --- |
| `PlayerRef.OPPONENT` | **조건 주인**의 상대 | `str()` → **"상대"** |
| `PlayerRole.NON_TURN_PLAYER` | **턴 플레이어**가 아닌 쪽 | `str()` → **"상대"** |
| *필요한 것* | **후보 컨트롤러**의 상대가 **사건의 행위자**인가 | — |

셋이 자주 같은 사람을 가리키지만 **같은 관계가 아니다** — 특수 소환은
상대 턴에도 일어나므로 "턴 플레이어가 아닌 쪽" 과 "내 효과의 상대" 가
갈라진다.

`trigger_order.py` 는 그 구분을 스스로 적어 두었다 — "컨트롤러와 턴
플레이어는 다른 것이다". 그리고 그 모듈은 `event.actor` 를 **한 번도 읽지
않는다.** `trigger_chain.py` 가 `actor` 를 쓰는 **유일한** 자리도
`actor=candidate.controller` 이고 — 그것은 관계가 아니라 **복사**다.

### SELF / OPPONENT / ANY / UNKNOWN (§7 — 새 enum 을 더하지 않았다)

| 범주 | 현재 구조로 표현 가능한가 |
| --- | --- |
| `SELF` (`actor == controller`) | 두 값은 있다 · **비교하는 자리가 없다** |
| `OPPONENT` (`actor == opponent(controller)`) | 같음 |
| `ANY` (행위자와 무관) | **이것만 지금의 동작이다** — 선언이 행위자를 적을 수 없으므로 모든 선언이 사실상 `ANY` 다 |
| `UNKNOWN` (판정할 정보가 부족) | `actor is None` 으로 **알 수는 있다** · 그것을 적을 `ValidationCode` 가 없다 |

> 지금 엔진의 모든 트리거 선언은 **묵시적으로 `ANY`** 다. 그리고 그것이
> `UNKNOWN` 이 아니라 `VALID/OK` 로 나온다.

---

## 8. SPECIAL_SUMMON 결합 분석 (R1~R5)

| | 요구 | event 만으로? | candidate 만으로? | 관계 필요? | 현재 `EventRelation` 으로? | 어디로 보내야 하는가 |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | "특수소환이 발생했다" | **정보는 있다** (`delta.summon`) | 아니다 | 아니다 | **아니다** — 선언이 종류를 못 적는다 (3-F-6) | `EventRelation` (사건 쪽 질문) |
| R2 | "내가 특수소환했다" | 아니다 | 아니다 | **그렇다** | 아니다 | `EventRelation` — 입력이 하나 모자란다 |
| R3 | "상대가 특수소환했다" | 아니다 | 아니다 | **그렇다** | 아니다 | 같음 |
| R4 | "특수소환인지 알 수 없다" | **표현된다** (`UNIMPLEMENTED`) | — | 아니다 | **그렇다** — `UNKNOWN/RULE_NOT_IMPLEMENTED` | 이미 맞다 |
| R5 | "특수소환은 맞지만 누가 했는지 알 수 없다" | — | — | — | — | **구조적으로 만들 수 없다** |

### R5 가 불가능한 이유 (`test_14`)

`MonsterSummoned` 는 `player` 를 **요구한다** — `None` 을 주면
`ValueError: player 는 0 또는 1 입니다`. 즉 **소환 사건에는 행위자가 언제나
있다.** 행위자가 없는 사건은 소환이 아니다 (페이즈 · 미구현).

> 이것이 설계를 단순하게 만든다: **소환 사건에서 "행위자 UNKNOWN" 은
> 일어나지 않는다.** `actor is None` 을 대비해야 하는 것은 소환이 아닌
> 사건들 때문이다.

### R2 와 R3 은 **같은 사건**이다

같은 `MonsterSummoned(player=1)` 사건이 후보의 컨트롤러에 따라 R3(상대)
이기도 하고 R2(나)이기도 하다. 즉 **사건만으로는 결정되지 않는다** —
그것이 이 관계가 사건 속성이 아니라 **관계**인 이유다.

---

## 9. 증식의 G specification (§9)

**구현하지 않았다.** 카드 이름도 패스코드도 쓰지 않았다 (3-F-6 과 같은
규칙). 요구를 분해하면:

| 축 | 값 | 지금 어디에 있는가 | 어느 계층까지 내려가야 판정되는가 |
| --- | --- | --- | --- |
| EVENT | `MONSTER_SUMMONED` | `event.point` | **`EventRelation`** — 이미 된다 |
| EVENT PROPERTY | `SummonKind = SPECIAL` | `event.delta.summon` | **`EventRelation`** — 선언에 칸이 없다 (3-F-6) |
| ACTOR | `opponent of candidate.controller` | `event.actor` + `candidate.controller` | **`EventRelation`** — **입력이 하나 없다** |
| RELATION | `event.actor` ↔ `candidate.controller` | 두 값은 있다 | **판정하는 코드가 없다** |
| CONDITION | 추가 카드 조건 | `TriggerSpec.condition` | `TriggerCondition` — 이미 된다 |

### 어느 계층까지 내려가야 완전히 판정되는가

**`EventRelation` 까지다.** 다섯 축 중 넷이 사건 쪽 질문이고, 나머지 하나는
이미 `TriggerCondition` 이 한다. `Eligibility` 나 `Activation` 까지 내려갈
필요가 **없다** — 내려가면 "사건이 맞는가" 와 "지금 발동할 수 있는가" 가
섞인다.

**"`TriggerSpec` 에 actor field 를 추가하면 된다" 를 결론으로 먼저 가정하지
않았다.** 측정 결과 그 칸만으로는 안 된다 — `PlayerRef.OPPONENT` 는 문맥을
받아야 번호로 풀리고(§7), `matches(event)` 와 `_event_relation(spec, event)`
둘 다 그 문맥(= 후보의 컨트롤러)을 **받지 않는다.**

---

## 10. 후와로스 specification (§10)

**구현하지 않았다.** 요구: "특정 종류의 특수소환 사건에 반응".

증식의 G 와 비교:

| | 증G | 후와로스 |
| --- | --- | --- |
| actor relation 이 필요한가 | **그렇다** | **그렇다** — 같다 |
| summon kind 가 필요한가 | 그렇다 (`SPECIAL`) | 그렇다 **+ 어떤 특수 소환법인가** |
| 추가 event property | 없음 | **있다** — `SummonKind` 에 담을 값이 없다 (STRUCTURAL-62) |

> **행위자 관계는 두 요구가 똑같이 필요하다.** 다른 것은 사건 **속성**의
> 깊이뿐이다. 그러므로 이 Phase 가 보는 경계(관계를 어디서 판정하는가)는
> 두 카드에 **공통**이고, 후와로스의 추가 요구는 그 경계와 **독립**이다.

---

## 11. EventRelation vs TriggerCondition 책임 구분 (§11)

### 현재 구조의 구분은 **입력으로** 정해져 있다 (`test_15`)

| 관문 | 질문 | 입력 | 코드가 읽는 것 |
| --- | --- | --- | --- |
| `EVENT_RELATION` | "이 사건이 그 선언이 바라는 것인가" | **사건** | `event.*` · `spec.*` · **판을 읽지 않는다** (`self._view` 없음) |
| `TRIGGER_CONDITION` | "그 사건을 전제로 무엇이 참인가" | **판** | `ConditionContext(candidate.controller, …)` · `self._evaluator` · **사건을 읽지 않는다** |

측정으로 확인했다 (docstring 을 제외한 **코드만** AST 로 봤다 — 처음엔
`_trigger_condition` 의 **설명**에 적힌 "event relation" 이라는 말이 걸려
틀린 실패가 났고, 그래서 docstring 을 떼는 헬퍼를 만들었다).

### "상대인가?" 는 어느 쪽인가 — **`EVENT_RELATION`**

| 질문 | 어느 관문 | 왜 |
| --- | --- | --- |
| "상대가 했는가?" | **`EVENT_RELATION`** | 사건의 **속성에 대한** 질문이다. 판이 그 뒤에 어떻게 바뀌었든 "누가 그 소환을 했는가" 는 달라지지 않는다 |
| "레벨 4 이상인가?" | `TRIGGER_CONDITION` | **판**에 대한 질문이고, 평가 시점의 상태가 답을 정한다 |

**이 구분은 현재 architecture 와 일치한다.** 두 관문의 성격이 입력으로
갈려 있고, 행위자는 분명히 사건 쪽 값이다.

### 그래서 문제가 "구분이 틀렸다" 가 아니다

`EVENT_RELATION` 이 맞는 자리인데 **비교할 두 번째 값을 받지 않는다.**
그리고 그 "받지 않는다" 가 실수가 아니라 **설계상 지켜 온 성격**이다 —
판을 읽지 않는 순수한 사건 비교였기 때문에 3-E-45 가 세 번째 답
(`INFORMATION_UNAVAILABLE`)을 만들 수 있었다.

> **그 성격을 깨는 것과 관계를 판정하는 것을 동시에 할 수 없다.** 그것이
> 이 Phase 가 결론을 "필드 추가" 로 내리지 않는 이유다.

---

## 12. Event 와 Candidate 를 함께 보는 관문 (§12)

### `match_event_to_candidate(event, candidate)` — **없다**

production 9개 루트의 모든 `.py` 를 읽어 그 이름이 없음을 확인했다
(`test_17`).

### 🟡 그런데 **둘을 함께 들고 있는 자료 구조는 이미 있다**

dormant 쪽이다.

```
TimingWindow(event, viewer, turn_player, phase, priority, chain)
TimingOutcome(window, collection, ordering, plan, chain, priority_check, unresolved_rules)
                 ↑          ↑
               사건      후보들 (TriggerCollection.candidates)
```

**`TimingOutcome` 은 사건과 후보가 한 값 안에 있는 유일한 자리다.** 즉
"책임을 암묵적으로 수행하고 있는 자리" 는 함수가 아니라 **데이터
구조**이고, 거기에 **비교하는 코드가 없다.**

| 측정 | 결과 |
| --- | --- |
| `engine/timing.py` 에 `actor` | **0회** |
| `engine/timing.py` 에 `controller` | **0회** |
| 거기 있는 `opponent` | `1 - self.turn_player` — **턴 플레이어** 기준 |
| production importer | **0** (여전히 dormant) |

> 관계를 판정할 **입력을 다 갖춘 자리가 이미 존재하는데**, 거기 있는
> `opponent` 는 필요한 관계가 아니고, 아무도 그 자리를 쓰지 않는다.
> 이것이 "책임이 정의되어 있지 않다" 의 가장 구체적인 모습이다.

### 암묵적으로 수행하는 세 자리 정리

| 자리 | 사건 | 후보 | 비교하는가 |
| --- | --- | --- | --- |
| `TriggerSpec.matches(event)` | 있다 | **없다** | 아니다 |
| `TriggerCollector._judge(spec, event, card, …)` | 있다 | 있다 (`card.controller`) | **아니다** — `ConditionContext` 에 사건을 넣지 않는다 |
| `TriggerEligibilityJudge.judge(candidate, spec, event)` | 있다 | 있다 | **아니다** — 관문의 답을 `fold` 할 뿐 |
| `TimingOutcome` | 있다 | 있다 | **아니다** — 비교 코드가 없다 |

---

## 13. ValidationCode 경계 (§14)

여섯 상황을 현재 어휘로 적어 봤다. **새 코드를 더하지 않았다** (`test_16`).

| | 상황 | 현재 `ValidationResult` |
| --- | --- | --- |
| A | `actor == controller` (SELF) | **판정이 없다** — `VALID/OK` 가 난다 |
| B | `actor == opponent(controller)` (OPPONENT) | **판정이 없다** — A 와 **같은** `VALID/OK` |
| C | actor 정보가 없다 | `UNKNOWN` / `RULE_NOT_IMPLEMENTED` — 다만 **사건이 미구현이라서**이고 행위자 때문이 아니다 |
| D | controller 정보가 없다 | **일어날 수 없다** (§3) |
| E | 관계 자체를 계산할 수 없다 | **`TypeError`** — 코드가 아니라 예외 |
| F | event type 이 지원되지 않는다 | `UNKNOWN` / `RULE_NOT_IMPLEMENTED` |

### 🔴 C 와 F 가 **같은 코드로 접힌다**

"행위자를 모른다" 와 "이 사건을 아예 모른다" 가 지금은 구별되지 않는다.
그리고 C 는 사실 **독립적으로 일어날 수 없다** — 소환 사건에는 행위자가
언제나 있으므로(R5 불가), 행위자가 없는 사건은 애초에 `UNIMPLEMENTED`
이거나 `PhaseChanged` 다.

### 48개 코드에 행위자 관계를 뜻하는 것이 없다

이름에 `actor`/`player`/`relation` 이 든 코드는 **둘**뿐이고, 둘 다
`INVALID` 이며 **다른 뜻**이다.

| 코드 | validity | 뜻 |
| --- | --- | --- |
| `ACTOR_INVALID` | `INVALID` | 행위를 넘긴 쪽이 0/1 이 아니다 (형식 오류) |
| `NOT_TURN_PLAYER` | `INVALID` | 지금 턴인 사람이 아니다 (**또 다른** 관계) |

`UNKNOWN` 짝은 일곱이고(`card_definition_unavailable` ·
`cost_not_implemented` · `effect_list_unreliable` · `hidden_card` ·
`information_unavailable` · `priority_state_stale` ·
`rule_not_implemented`), 행위자를 가리키는 것이 **하나도 없다.**

> 즉 **"행위자 관계를 판정할 수 없다" 를 적을 자리가 어휘에 없다.** 새
> 코드를 더해야 하는지는 다음 Phase 의 질문이고, 이 Phase 는 더하지 않았다.

---

## 14. hidden-info (§15)

`test_18` — 비교에 필요한 두 값이 **둘 다 공개 정보**다.

| 확인 | 결과 |
| --- | --- |
| `event.actor` | 공개 — 소환은 공개된 자리에서 일어난다 |
| `candidate.controller` | 공개 — 후보는 **보이는 카드**에서만 생긴다 (§3) |
| 소환된 카드 | 내 관측에서 보인다 (`MZONE`, 앞면) |
| 상대의 패 · 덱 | `concealed=True` · `cards == ()` — **그대로 가려져 있다** |
| `state_hash` · RNG | **불변** |

상대 패/덱 접근 · 카드 신원 추정 · Opponent Model 은 하나도 하지 않았다.
플레이어 번호를 비교하는 데 필요한 공개 정보만 썼다.

---

## 15. Engine V1 freeze (§16) · Evaluation/Search 불변 (§17)

`test_19` 가 넷을 함께 확인한다.

| 확인 | 결과 |
| --- | --- |
| `duel.py` 에 `TriggerRegistry`·`TriggerCollector`·`TriggerEligibilityJudge`·`EventReader`·`TimingEvent`·`TimingWindow`·`engine.timing`·`engine.event_pipeline` | **하나도 없음** |
| `TriggerSpec` 필드 수 | **9** (변경 없음) · `actor` 없음 |
| `_event_relation` 서명 | `["spec", "event"]` (변경 없음) |
| `ValidationCode` 수 | **48** (변경 없음) |
| 탐색 순위 | 6판 **611결정**, digest `30fa3597a24d4511d8c92ce9f9921412ffada7546675c4d7d5765381402c4175` — **3-F-5 · 3-F-6 과 같은 값** |

금지 항목 전부 미실행: EventRelation production 변경 없음 · TriggerSpec 필드
추가 없음 · 파이프라인 연결 없음 · `legal_actions` 변경 없음 ·
`SPECIAL_SUMMON` 실행 변경 없음 · EventBus 없음 · graph/rule engine 없음 ·
Evaluation/Search/weight/depth 변경 없음.

---

## 16. 테스트 결과

### 새 테스트 — `tests/test_actor_relation_boundary_audit.py` 19건

| # | 이름 | §18 항목 |
| --- | --- | --- |
| 01 | the event actor is a fact and is sometimes absent | 6 |
| 02 | the candidate controller is always known and always public | 7 |
| 03 | the event relation gate reads the event but never the actor | 12 |
| 04 | **the event relation gate does not receive the candidate** | 8 |
| 05 | fixture a self summon | 1 · 4 · 9 |
| 06 | fixture b opponent summon | 2 · 5 · 10 |
| 07 | fixture c unknown actor | 3 · 6 · 11 |
| 08 | **flipping only the actor changes nothing at all** | 8 |
| 09 | fold keeps every gate verdict | 14 |
| 10 | **what judge actually drops is the event** | 14 |
| 11 | the not equal comparison is unsafe when the actor is absent | 6 |
| 12 | every existing opponent helper is total over two players | 4 · 5 |
| 13 | the engine already has two different meanings of opponent | 4 · 5 |
| 14 | the five requirements need three different kinds of information | 9 · 10 · 11 |
| 15 | the event relation and trigger condition split is about inputs | 13 |
| 16 | no validation code can say the actor relation is unknown | 12 |
| 17 | **the window holds the event and the candidates but never relates them** | 8 |
| 18 | reading the relation inputs touches no hidden information | 15 |
| 19 | this phase changed nothing in production | 16 · 17 · 18 |

```
$ python3 -m pytest tests/test_actor_relation_boundary_audit.py -p no:randomly -q
19 passed in 9.02s
```

### 고의 위반 검증 — 6건, 전부 잡았다

| # | 위반 | 잡은 테스트 |
| --- | --- | --- |
| 1 | `_event_relation` 에 `candidate` 를 넘긴다 | `test_04` · `test_19` |
| 2 | `matches` 에서 행위자를 걸러 **실제로 구분시킨다** | `test_08` · `test_10` · `test_18` + 1건 |
| 3 | `fold` 가 통과한 관문을 버린다 | `test_09` · `test_06` · `test_08` + 1건 |
| 4 | `TriggerEligibility` 에 `event` 칸을 더한다 | `test_10` |
| 5 | `timing.py` 에 `actor_is_opponent_of` 를 더한다 | `test_17` |
| 6 | `duel.py` 가 `TriggerRegistry` 를 import 한다 | `test_19` |

주입 파일 5개(`trigger.py` · `timing.py` · `trigger_order.py` ·
`condition/context.py` · `duel.py`)는 전부 백업에서 복원하고 md5 로 확인했다
(모두 `OK`).

### 🟡 내가 쓴 단정 하나가 처음에 틀렸다 — production 이 아니라 테스트를 고쳤다

`test_15` 에서 "`_trigger_condition` 은 사건을 읽지 않는다" 를 **본문
문자열**로 확인했고 실패했다. 그 함수의 **docstring** 에
"사건 관계(event relation)를 따로 둔다" 는 **설명**이 적혀 있어서 "event"
라는 말이 걸린 것이다.

설명이 아니라 **실제로 읽는 값**을 세야 하므로, docstring 을 떼고 코드만
`ast.unparse` 로 보는 헬퍼(`function_code`)를 만들어 고쳤다. production 은
고치지 않았다. (3-E-44 에서 `EventBus` 가 docstring 에 걸렸던 것과 같은
종류의 실수이고, 그때 세운 "문자열이 아니라 AST" 규칙을 이번엔 **한 단계
더** 적용해야 했다.)

### 전체 회귀

```
$ python3 -m pytest tests/test_actor_relation_boundary_audit.py -p no:randomly -q
19 passed in 9.02s

$ python3 -m pytest -p no:randomly -q
4234 passed, 4 skipped in 344.61s (0:05:44)
```

| | 통과 | skip |
| --- | --- | --- |
| Phase 3-F-6 직후 (baseline) | 4,215 | 4 |
| Phase 3-F-7 (이번) | **4,234** | 4 |
| 차이 | **+19** | 0 |

**+19 가 이번에 더한 시험 수와 정확히 같다.** skip 4건은 baseline 과 동일한
기존 skip 이다.

### 기존 테스트 처리

**수정 0건 · 삭제 0건 · skip 추가 0건 · assertion 약화 0건.**
production diff 가 0 이므로 기존 계약이 깨질 자리가 없었다.

---

## 17. production diff

```
$ git diff --stat -- engine agent app core analysis rules rulings sources scripts
(출력 없음)
```

**0.** 추가한 것은 테스트 하나와 이 보고서뿐이다.

### §2 의 여섯 후보 계층 — 여덟 기준으로 평가

| 기준 | A. Event | B. TriggerSpec | **C. EventRelation** | D. Candidate/Eligibility | E. Activation | F. Condition |
| --- | --- | --- | --- | --- | --- | --- |
| 필요한 입력을 가졌는가 | 사건만 — **후보 없음** | 사건만 — **후보 없음** | **사건 있음 · 후보 없음** | **둘 다 있음** | 둘 다 있음 (멀다) | 판만 — **사건 없음** |
| semantic ownership | ✗ 사건은 관계를 모른다 | ✗ 선언은 사실이 아니다 | **○ 사건 속성 질문의 자리** | △ "지금 발동 가능한가" 와 섞인다 | ✗ 너무 늦다 | ✗ 판 질문의 자리 |
| 재사용 가능한가 | — | — | **○ 모든 사건군에 같은 모양** | △ 후보마다 반복 | ✗ | △ 상태 조건만 |
| hidden info 를 깨지 않는가 | ○ | ○ | **○ 두 값 다 공개** | ○ | ○ | ○ |
| ValidationCode 와 결합되는가 | ✗ 사건은 판정을 내지 않는다 | ✗ | **○ 이미 `GateVerdict` 를 낸다** | ○ | ○ | ○ |
| UNKNOWN 을 정확히 적을 수 있는가 | ✗ | ✗ | **△ 세 번째 답의 틀은 있다 · 행위자용 코드가 없다** | △ | ✗ | △ |
| production 실행과 분리되는가 | ○ | ○ | **○ 판을 읽지 않는다** | ○ | ✗ 실행에 붙는다 | ○ |
| state_hash/canonical_state 영향 | 없음 | **정렬 순서 영향** (3-F-6 §14) | **없음** | 없음 | — | 없음 |

**의미상 가장 맞는 자리는 C(EventRelation)** 이고, 입력이 하나 모자란다.
D 는 입력을 갖췄지만 소유권이 어긋난다("사건이 맞는가" 와 "지금 발동
가능한가" 가 섞인다).

### 설계 제안까지만 — **구현하지 않았다**

관계를 C 에 두려면 **세 가지가 함께** 필요하다. 하나만 해서는 조용한
오답이 남는다.

1. **입력 하나** — `_event_relation` 이 후보의 컨트롤러를 알아야 한다.
   `candidate` 전체를 넘기면 그 관문이 "판을 읽지 않는 순수 사건 비교"
   라는 성격을 잃는다. 컨트롤러 **정수 하나만** 넘기는 쪽이 그 성격을
   지킨다 — 어느 쪽이든 서명 변경이고, **이 Phase 에서 고르지 않는다.**
2. **선언 쪽 어휘** — `PlayerRef`(CONTROLLER/OPPONENT)를 그대로 쓸 수
   있다. 새 enum 이 필요하지 않다. 단 `TriggerSpec` 에 그 칸이 필요하고,
   그것이 3-F-6 이 측정한 필드 추가다 (`canonical_state` 정렬 영향 있음).
3. **`UNKNOWN` 을 적을 길** — `actor is None` 일 때 `!=` 로 "상대" 를
   단정하지 않아야 한다. 지금 어휘에 그 코드가 없고
   `INFORMATION_UNAVAILABLE` 이 가장 가깝다. **소환 사건에서는 이 경우가
   일어나지 않지만**(R5 불가), 다른 사건군에서는 일어난다.

---

## 18. 최종 판정

### **C. CROSS_LAYER_RELATION_GAP**

> Event 와 Candidate 양쪽 정보는 존재하지만 이를 비교하는 책임이
> architecture 에 명확히 정의되어 있지 않다.

근거:

1. **양쪽 정보가 다 있다.** `event.actor` 는 사실이고(`test_01`),
   `candidate.controller` 는 **언제나 있다**(`test_02`). 둘 다 공개
   정보다(`test_18`).
2. **비교하는 코드가 하나도 없다.** 판과 후보를 고정하고 행위자만
   뒤집으면 다섯 관문 · 접힌 상태 · 정규 표현이 **한 글자도 달라지지
   않는다** (`test_08`).
3. **책임을 맡은 자리가 정의되어 있지 않다.** `match_event_to_candidate`
   같은 함수가 없고(`test_17`), 둘을 함께 들고 있는 자료 구조
   (`TimingOutcome`)에는 비교 코드가 없으며, 거기 있는 `opponent` 는
   **턴 플레이어** 기준의 다른 관계다.
4. **어휘에도 자리가 없다.** 48개 코드 중 행위자 관계를 뜻하는 것이 없고,
   `UNKNOWN` 짝 일곱에도 없다 (`test_16`).

### 왜 B 가 아닌가

B 는 "`EVENT_RELATION` 이 후보이지만 **현재 semantic contract 가
불명확하다**" 다. 측정 결과 **그 contract 는 오히려 명확하다** —
`EVENT_RELATION` 은 사건만 보고 판을 읽지 않으며(`self._view` 없음),
`TRIGGER_CONDITION` 은 판만 보고 사건을 읽지 않는다(`test_15`). 둘의
경계가 입력으로 깔끔하게 갈려 있고, 3-E-45 의 세 번째 답도 그 성격 덕에
가능했다.

불명확한 것은 그 관문의 contract 가 아니라 **"관계를 누가 판정하는가" 가
아무 곳에도 적혀 있지 않다**는 것이다. 그것이 C 의 문장과 정확히 같다.

### 왜 A 가 아닌가

A 는 "판단해야 할 **명확한 계층이 존재한다**" 다. 의미상 가장 맞는 자리는
`EventRelation` 이지만(§17 표), 그 자리는 입력을 받지 않고, 받게 하는 것이
그 관문의 성격을 바꾸는 선택을 요구한다. "명확히 존재한다" 고 적으면
그 선택이 이미 끝난 것처럼 읽힌다.

### 왜 D 가 아닌가

예상 밖의 더 큰 구조 문제는 없었다. 오히려 프롬프트의 전제 둘이 실제보다
**나쁘게** 적혀 있었고(§1), 측정은 구조가 생각보다 **깨끗함**을 보였다 —
`fold` 는 정보를 버리지 않고, 두 관문의 경계는 일관되며, 후보 쪽
컨트롤러는 언제나 있고, 소환 사건에서 행위자는 언제나 있다.

---

## 19. 다음 Phase 후보 (1개)

**Phase 3-F-8 — `_event_relation` 에 후보 컨트롤러를 넘기는 두 방식의
비용 측정 (설계 선택 하나만)**

§17 의 1번만 본다. 2번(`TriggerSpec` 칸)과 3번(`UNKNOWN` 코드)은 **입력이
정해진 뒤**에만 모양이 정해진다 — 지금 칸을 먼저 더하면 비교할 자리가
없는 칸이 생긴다.

그 Phase 가 답해야 할 것:

1. `candidate` 전체를 넘기는 것과 **컨트롤러 정수 하나만** 넘기는 것의
   차이를 측정한다 — 각자 몇 개의 기존 테스트가 서명 변경에 걸리는지,
   그 관문이 후보의 다른 값(`source` · `status`)에 접근하게 되는 것이
   실제로 위험한지.
2. 그 변경이 **3-E-45 의 세 번째 답을 깨뜨리는가** — `_event_relation` 이
   판을 읽지 않는다는 성격이 `INFORMATION_UNAVAILABLE` 의 근거였다.
   컨트롤러 정수는 판이 아니므로 깨지지 않을 것으로 **보이지만**, 측정해야
   한다.
3. `judge` 의 출력에 사건을 담아야 하는가 — §5 의 손실은 관계 판정과
   **별개 문제**다. 담지 않고도 관계를 판정할 수 있는지 먼저 본다.
4. `TriggerCollector._judge` 가 이미 둘을 함께 들고 있는데도 거기서
   하지 않아야 하는 이유(3-E-26 의 "같은 사실을 두 어휘로") 가 **입력을
   넘긴 뒤에도 유효한가.**

**이 Phase 는 그 작업을 하지 않았다. 다음 Phase 는 임의로 진행하지 않는다.**
