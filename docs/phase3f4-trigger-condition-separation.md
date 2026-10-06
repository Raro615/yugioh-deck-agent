# Phase 3-F-4 — Evaluation scenario 를 위한 Trigger Condition 분리 감사

## 1. Phase / Base / 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-F-4 — Event / Trigger Condition / Eligibility / Activation 분리 |
| 성격 | **AUDIT-ONLY** (production 수정 0줄) |
| Base Phase | 3-F-3 — Opponent Resource Weighting (판정 **B. WEIGHT_NOT_YET_JUSTIFIED**) |
| Base baseline | 4,159 passed / 4 skipped |

**실제 HEAD 확인 (작업 시작 전)**

```
$ git rev-parse HEAD
e3b3f7fefaf535145e34ca7ec0d470edfd7f95d3
$ git rev-parse --abbrev-ref HEAD
claude/pensive-goodall-te1egy
$ git status --short      → (비어 있음)
```

3-F-3 의 두 commit 을 실제 history 에서 확인했다 — 프롬프트의 SHA 를 믿지 않고
`git log` 로 확인했다.

| commit | 제목 | ancestor |
| --- | --- | --- |
| `f1772fe` | Phase 3-F-3: weight opponent resource evaluation | ✅ |
| `e3b3f7f` | Phase 3-F-3 보고서: commit SHA · push 결과 기록 | ✅ |

산출물도 그 자리에 있다 — `docs/phase3f3-opponent-resource-weighting.md` ·
`tests/agent/test_opponent_resource_weighting_audit.py`.

**3-F-3 의 weight 결론을 다시 측정하지 않았다.** Engine V1 freeze 를 유지한다.

---

## 2. 실제 trigger / activation 구조

### 2-1. LIVE 경로 (실제 듀얼이 쓰는 것)

```
Duel.legal_actions(seat)
   └→ Duel._activation_actions(seat, validator)      ← **사건을 읽지 않는다**
        │   activatable_effects(card_id)              구현이 등록된 효과만
        │   definition.cost.costs → 비면 통과          (ADR-008)
        │   target_combinations(...)                  대상마다 다른 후보
        └→ Duel._activation_gate(action, …)           **세 관문**
             ├→ ActionValidator.validate              규칙 쪽 (범위 검사 포함)
             ├→ ActivationTimingChecker.check         스펠 스피드 · 세트한 턴
             └→ EffectActivator.can_activate          구현 · 조건 · 대상
```

### 2-2. DORMANT 경로 (존재하지만 production 이 부르지 않는 것)

3-E-43 이 기록한 세 층을 다시 확인했다 — **그대로다.**

| 층 | 모듈 | production 소비 |
| --- | --- | --- |
| LIVE | `engine/activation_timing.py` | **있다** |
| DORMANT-ASSEMBLY | `engine/timing.py` · `engine/event_pipeline.py` | **importer 0** |
| DORMANT-PARTS | `engine/trigger.py` · `trigger_chain.py` · `trigger_order.py` | **call 0** |

`engine/duel.py` 에 `trigger` · `Trigger` 문자열이 **하나도 없다** (`test_02` ·
`test_18`). `agent/` 다섯 모듈도 `engine.trigger` 를 import 하지 않는다.

**"구조가 존재한다" 와 "지금 연결해야 한다" 를 섞지 않았다** (§7 의 요구).

---

## 3. EffectDefinition 조사

**열 칸이고 그중 사건 칸이 없다** (`test_01`).

```
effect_ref · source_card_id · operations · activation · cost
targets · declarations · requirements · guards · provenance
```

`code` · `event` · `point` · `trigger` · `setcode` · `timing` **전부 없다.**
그리고 `engine/effect/definition.py` 안에 `EVENT` 라는 글자도 없다.

**있는 것은 `activation: Condition | None` 하나이고, `Condition` 은 상태에 대해
평가된다** — "무엇이 일어났는가" 가 아니라 "무엇이 참인가" 다. 이 차이가 이 Phase
전체의 출발점이다.

---

## 4. EVENT_* 조사

### 4-1. 어디 사는가 — **파서 계층**이다

`EVENT_*` 는 `EffectSpec.code` 에 있고, engine 에서 `iter_effects(card)` 로
**닿을 수 있다.** 즉 "정의에 없다" 는 잃어버린 것이 아니라 **읽지 않기로 한**
것이다 (3-E-31 의 `INTENTIONALLY_DROPPED`).

실측 (3-E-31 의 숫자를 다시 셌고 **정확히 재현되었다**):

| 세는 기준 | 값 |
| --- | --- |
| 효과 블록 전체 | 34,631 |
| 그중 `code` 가 있는 것 | 30,084 |
| 그중 **`EVENT_*` 인 것** | **16,381** |
| 서로 다른 **`EVENT_*` 상수** | **70** |
| `code = None` | 4,547 |
| 스크립트가 있는 카드 | 12,504 |

> **세는 기준을 적어 둔다.** 처음에 "블록 34,631 · 상수 299" 로 재고 3-E-31 의
> 16,381 / 70 과 어긋난다고 보았는데, 그것은 `EFFECT_*` 와 `None` 까지 포함한
> **다른 분모**였다. `EVENT_*` 로 좁히면 두 숫자가 똑같다.

### 4-2. 상위 분포 — 증G 가 쓰는 사건이 **두 번째로 많다**

| `EVENT_*` 상수 | 블록 수 |
| --- | --- |
| `EVENT_FREE_CHAIN` | **4,909** |
| **`EVENT_SPSUMMON_SUCCESS`** | **2,114** |
| `EVENT_PHASE` | 1,328 |
| `EVENT_SUMMON_SUCCESS` | 1,249 |
| `EVENT_TO_GRAVE` | 1,173 |
| `EVENT_CHAINING` | 866 |

### 4-3. 등재 16효과는 **전부 `EVENT_FREE_CHAIN`**

`test_04` 가 고정한다. `EVENT_FREE_CHAIN` 은 **사건이 아니라** 발동형 효과의
"유발 조건 없음" 분류값이다 (3-E-32 가 확정). 이름이 `EVENT_` 로 시작한다고
사건으로 읽지 않는다.

**결론: 지금 엔진에는 사건에 반응하는 효과가 하나도 없다.**

---

## 5. TriggerSpec / TriggerRegistry 조사

`TriggerSpec` 은 아홉 칸이고 **`point` 를 든다** — 사건을 들고 있는 것이 이쪽이다.

```
effect_ref · point · requirement · wording
operations · from_zones · to_zones      ← CARD_MOVED 에만 걸 수 있다
activates_from · condition
```

`__post_init__` 가 `point is not CARD_MOVED` 일 때 세 필터를 **거부한다**
(`test_13`). 그래서 `MONSTER_SUMMONED` 에는 **어떤 필터도 걸 수 없다.**

`TriggerRegistry` 는 `watching(event)` 로 `spec.matches(event)` 를 거르지만,
그 호출자는 `engine/trigger.py` 안 두 곳뿐이다 (3-E-45 가 고정).

---

## 6. LIVE / DORMANT 경계

§7 의 네 질문에 답한다.

### Q1. LIVE 경로만으로 서로 다른 trigger/condition scenario 를 만들 수 있는가?

**조건 차이는 만들 수 있다. 사건 차이는 만들 수 없다.**

| 시나리오 종류 | LIVE 로 가능한가 | 근거 |
| --- | --- | --- |
| 같은 EVENT + **조건 TRUE/FALSE** | **가능** (마법) | `test_06`–`test_09` |
| 같은 EVENT + 조건 차이 (**함정**) | **불가능** | `test_10` — 범위 검사가 먼저 걸린다 |
| **다른 EVENT** → 다른 후보 | **불가능** | `test_11` — 반응할 사건이 없고 열거가 사건을 읽지 않는다 |
| 특수소환 사건 (증G 유형) | **불가능** | `test_12`–`test_14` — 세 계층이 비어 있다 |

### Q2. dormant pipeline 이 없으면 어떤 scenario 를 만들 수 없는가?

**사건에 반응하는 모든 scenario.** 구체적으로:

* "상대가 특수소환했을 때" (증G · 후와로스)
* "카드가 묘지로 갔을 때" (`EVENT_TO_GRAVE`, 1,173 블록)
* "체인이 쌓였을 때" (`EVENT_CHAINING`, 866 블록)
* 같은 사건의 **의미별 구분** (파괴 ↔ 묘지送り, ADR-002)

`TimingPoint` 8개와 `TriggerSpec` 의 필터가 그 어휘를 들고 있으나, **production
이 그것을 만들지도 소비하지도 않는다.**

### Q3. Evaluation 을 발전시키기 위해 dormant pipeline 을 지금 살려야 하는가?

**아니다 — 지금 필요한 종류의 benchmark 는 LIVE 로 만들 수 있다.**

3-F-2 가 쓴 benchmark(상대 자원 0 vs 3) 는 `state.draw(THEIRS, n)` 으로 **손으로**
만들었고, 조건 기반 benchmark 는 이 Phase 가 **LIVE 관문으로** 만들었다
(`test_06`–`test_09`). 둘 다 dormant 를 요구하지 않는다.

dormant 를 살려야 하는 것은 그 다음 질문 — "그 상태가 **실제 플레이에서 생기는가**"
— 이고, 3-F-3 이 그것을 이미 blocker 로 기록했다.

### Q4. 아니면 현재 Engine V1 범위 밖의 문제인가?

**일부는 범위 밖이고, 일부는 범위 안의 데이터 문제다.** §10 이 가른다.

---

## 7. Event / Trigger Condition / Eligibility / Activation 구분

§3 이 요구한 네 단계를 **각자 재서** 적는다.

| 단계 | 질문 | LIVE | DORMANT |
| --- | --- | --- | --- |
| **EVENT** | 무슨 일이 일어났는가 | **없다** — 열거가 사건을 읽지 않는다 | `TimingEvent` · `TimingPoint` 8개 |
| **TRIGGER CONDITION** | 어떤 사건에 반응하는가 | **없다** — `EffectDefinition` 에 사건 칸이 없다 | `TriggerSpec.point` + 필터 (`CARD_MOVED` 만) |
| **ELIGIBILITY** | 지금 후보가 될 수 있는가 | **있다** — `activation` 상태 조건 → `CANDIDATE_NOT_ELIGIBLE` | `TriggerEligibilityJudge` 다섯 관문 |
| **ACTIVATION** | 지금 실제로 고를 수 있는가 | **있다** — 세 관문 + 대상 바인딩 → `TOO_FEW_SELECTED` 등 | **없다** (dormant 는 발동하지 않는다) |

**두 경로가 서로의 빈 칸을 메운다** — LIVE 는 뒤 두 단계를, DORMANT 는 앞 두
단계를 갖는다. 그리고 그 둘이 연결되어 있지 않다.

### ELIGIBILITY ≠ ACTIVATION 을 실제로 가른 측정

`test_09` 가 **같은 판에서** 둘을 갈랐다 — 무정한 말살(통상 마법):

| | 결과 |
| --- | --- |
| 조건(자신 MZONE 1+ AND 상대 HAND 1+) | 만족 |
| **ELIGIBILITY** — 후보가 되는가 | **된다.** 그리고 후보가 **대상을 들고** 나온다 |
| **ACTIVATION** — 대상 없이 만든 같은 발동 | **거절.** `INVALID` / **`TOO_FEW_SELECTED`** |

코드가 다른 것이 요점이다 — `CANDIDATE_NOT_ELIGIBLE`("자격이 없다") 과
`TOO_FEW_SELECTED`("이 행위가 덜 적혔다") 는 다른 사실이고, 하나의 boolean 으로
뭉개면 그 차이가 사라진다.

---

## 8. 최소 3개 실제 카드 / 효과 사례

**등재되어 실행 가능한 실제 카드** 넷을 썼다. 종류는 **공식 DB 가 말한다** —
추측하지 않았다 (`test_05`).

| | 카드 | passcode | 종류 | effect | EVENT (parser) | trigger condition | eligibility condition | activation condition | LIVE/DORMANT | production consumer |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 욕망의 항아리 | 55144522 | 통상 마법 | `e[0]` 드로우 2 | `EVENT_FREE_CHAIN` | **없음** | 자신 DECK 2+ | 세 관문 | **LIVE** | **있다** (후보로 나온다) |
| 2 | 리로드 | 22589918 | 속공 마법 | `e[0]` 패 교환 | `EVENT_FREE_CHAIN` | **없음** | 자신 HAND 에 **이 카드 말고** 1+ | 세 관문 | **LIVE** | **있다** |
| 3 | 무정한 말살 | 73148972 | 통상 마법 | `e[0]` 대상 2개 | `EVENT_FREE_CHAIN` | **없음** | 자신 MZONE 1+ **AND** 상대 HAND 1+ | 세 관문 + **대상 바인딩** | **LIVE** | **있다** |
| 4 | 의적의 입문서 | 69091732 | **함정** | `e[0]` | `EVENT_FREE_CHAIN` | **없음** | 상대 HAND 5+ | **범위 밖** | LIVE 이지만 **후보 불가** | **없다** |

§5 가 요구한 세 종류가 모두 들어 있다.

* **A (특정 EVENT 에 반응)** — 해당 사례가 **없다.** 등재 16개 전부
  `EVENT_FREE_CHAIN` 이므로 사건에 반응하는 효과가 하나도 없다. 그 사실이 이
  Phase 의 주요 측정 결과다.
* **B (조건이 추가로 필요)** — 사례 1 · 2 · 3 · 4 모두. 셋은 자신 쪽 조건,
  **사례 4 는 상대 쪽 공개 장수**를 조건으로 쓴다.
* **C (비슷한데 조건 때문에 결과가 달라진다)** — 사례 1 vs 4. 둘 다
  `EVENT_FREE_CHAIN` 이고 둘 다 조건이 있는데, **마법은 조건 차이가 보이고
  함정은 보이지 않는다.**

### expected / current / validation 결과

| 사례 | 상태 | expected | validation 결과 | 후보 |
| --- | --- | --- | --- | --- |
| 1 | 내 덱 2 | 발동 가능 | `VALID` / `OK` | ✅ |
| 1 | 내 덱 1 | 조건 거짓 → 확실한 거부 | `INVALID` / `CANDIDATE_NOT_ELIGIBLE` | ❌ |
| 2 | 패에 다른 카드 1 | 발동 가능 | `VALID` / `OK` | ✅ |
| 2 | 패에 이 카드만 | 조건 거짓 | `INVALID` / `CANDIDATE_NOT_ELIGIBLE` | ❌ |
| 3 | 내 몬스터 1 · 상대 패 1 | 후보가 된다 | (대상 포함 후보) | ✅ |
| 3 | 내 몬스터 0 · 상대 패 1 | 앞 조건 거짓 | `INVALID` / `CANDIDATE_NOT_ELIGIBLE` | ❌ |
| 3 | 내 몬스터 1 · 상대 패 0 | 뒤 조건 거짓 | `INVALID` / `CANDIDATE_NOT_ELIGIBLE` | ❌ |
| 4 | 상대 패 5 (조건 **참**) | 판정 불가 | `UNKNOWN` / `RULE_NOT_IMPLEMENTED` | ❌ |
| 4 | 상대 패 4 (조건 **거짓**) | 판정 불가 | `UNKNOWN` / `RULE_NOT_IMPLEMENTED` | ❌ |

---

## 9. 동일 입력에서 조건 변화에 따른 판정 차이

§6 이 요구한 검증이다. **축 하나만 바꾸고 나머지를 고정**했다.

### 성공 — 마법 셋

```
욕망의 항아리:  내 덱 2 → VALID/OK (후보)     |  내 덱 1 → INVALID/CANDIDATE_NOT_ELIGIBLE (후보 아님)
리로드:        패 2장 → VALID/OK (후보)      |  패 1장  → INVALID/CANDIDATE_NOT_ELIGIBLE (후보 아님)
무정한 말살:    몬1·상패1 → 후보              |  몬0·상패1 / 몬1·상패0 → 둘 다 CANDIDATE_NOT_ELIGIBLE
```

**왜 이 판정이어야 하는가**: 조건을 **끝까지 보고 거짓을 받았으므로** 확실한
거부이고, 그래서 `INVALID` 다. `RULE_NOT_IMPLEMENTED`(= 모름) 를 붙이면
"엔진이 못 한다" 는 거짓이 된다 (3-E-38 이 이 자리를 그렇게 고쳤다).

### 실패 — 함정 하나, 그리고 **그것이 올바른 실패**다

```
의적의 입문서:  상대 패 5 (조건 참)  → UNKNOWN/RULE_NOT_IMPLEMENTED
               상대 패 4 (조건 거짓) → UNKNOWN/RULE_NOT_IMPLEMENTED   ← 같다
```

조건이 참인 쪽과 거짓인 쪽이 **구분되지 않는다.** 범위 검사(`함정이다`)가 조건
평가보다 **먼저** 걸리기 때문이다.

**이것을 결함으로 적지 않는다.** 조건이 거짓인 것이 아니라 **판정할 규칙이 없는**
것이므로 `UNKNOWN` 이 맞다. 여기서 `CANDIDATE_NOT_ELIGIBLE` 이 나오면 "규칙이
금지한다" 는 거짓이 된다 (§9). **대가는 분명하다 — 함정의 조건 차이로는
benchmark 를 만들 수 없다.**

### 불가능 — 사건 차이

`test_11` 이 둘을 측정한다. ① 등재 16효과 전부 `EVENT_FREE_CHAIN` 이라
반응할 사건이 없다. ② `Duel._activation_actions` 가 `TimingEvent` ·
`TimingPoint` · `TriggerSpec` · `TriggerRegistry` · `JournalEvent` 를 **하나도
읽지 않는다** (AST 로 확인).

---

## 10. Engine V1 freeze 와의 관계

§8 의 세 선택지 중 **B** 다.

> **B. 일부 scenario 는 fixture / audit 수준에서만 검증 가능하다.**

갈라서 적는다.

| 만들려는 scenario | 지금 가능한가 | 필요한 것 | Engine V1 변경인가 |
| --- | --- | --- | --- |
| 조건 TRUE/FALSE (마법) | **production 에서 가능** | 없음 | — |
| 상대 자원 0 vs 3 | **fixture 로 가능** (3-F-2) | 없음 | — |
| 조건 TRUE/FALSE (함정) | **불가능** | `SetCode(EVENT_*)` → `EffectDefinition` + 함정 발동 계층 | **그렇다** (발동 경로) |
| 다른 사건 → 다른 후보 | **불가능** | 사건을 가진 효과 등재 + dormant 연결 | 일부 **데이터**, 일부 **구조** |
| 특수소환 사건 (증G) | **불가능** | ① `SPECIAL_SUMMON` 쓰는 효과 등재 ② `TimingPoint` 에 소환 종류 ③ `TriggerSpec` 필터 ④ pipeline 연결 | ①은 **데이터**, ②③④는 **구조** |

**①은 Engine V1 구조 변경이 아니다** — 효과 라이브러리에 카드를 등재하는 것은
데이터 작업이다. **②③④는 구조 변경**이고, 그중 ②③은 dormant 모듈 안이라
live 경로를 건드리지 않는다.

**이 Phase 는 그 어느 것도 하지 않았다.** production diff 0 이다.

---

## 11. ValidationCode 의 의미

§9 가 요구한 구분이 **실제로 갈려 있다** (`test_15`). 같은 "발동할 수 없다" 가
세 코드로 나오고, 셋이 서로 다르다.

| 사실 | validity | code | 사례 |
| --- | --- | --- | --- |
| 조건을 끝까지 보고 **거짓** | `INVALID` | **`CANDIDATE_NOT_ELIGIBLE`** | 욕망의 항아리 · 덱 1장 |
| **판정할 규칙이 없다** | `UNKNOWN` | **`RULE_NOT_IMPLEMENTED`** | 의적의 입문서 (함정) |
| 자격은 있는데 **행위가 덜 적혔다** | `INVALID` | **`TOO_FEW_SELECTED`** | 무정한 말살 · 대상 없음 |

세 번째가 첫 번째와 다른 것이 요점이다 — **둘 다 `INVALID` 지만 코드가 다르고**,
그래서 "왜 안 되는가" 가 남는다.

`INFORMATION_UNAVAILABLE` 은 이 사례들에서 나오지 않았다 — 조건이 읽는 장수가
전부 **공개 정보**이기 때문이다 (상대 패 **장수**도 공개다, 3-F-2 §5).

### `UNIMPLEMENTED` 를 "사건이 없었다" 로 읽지 않는다

`test_16` 이 고정한다. `TimingPoint.UNIMPLEMENTED` 는 **사건이 있었는데 옮길
이름이 없다** 는 뜻이고, 그래서 `note` 를 **반드시** 요구한다
(`TimingEvent.unimplemented("")` 는 `TriggerError`). 3-E-45 가 그 시점을 받으면
`UNKNOWN` 으로 돌려주도록 고쳤다 — 거부가 아니다.

---

## 12. 증G / 후와로스 / 드롤 유형과의 관계

§11 이 요구한 **분류**다. **어느 카드의 로직도 구현하지 않았고 이름을 production
에 넣지 않았다.**

| 카드 유형 | 요구하는 상태 변화 | 필요한 사건 | 지금 표현 가능한가 |
| --- | --- | --- | --- |
| 증식의 G | 상대의 **특수소환**마다 내가 1장 드로우 | `EVENT_SPSUMMON_SUCCESS` (2,114 블록) | **아니다** — 세 계층 공백 |
| 마루챠미 후와로스 | 특정 **특수소환**에 따른 상대 자원 획득 | 같은 사건 + 소환 종류 구분 | **아니다** — 같은 공백 |
| 드롤 & 로크 버드 | 이후의 **card acquisition 제한** | 사건이 아니라 **지속 금지 효과** | **아니다** — 금지 효과 계층이 없다 |

### 특수소환 사건의 **세 계층 공백** (측정)

| 계층 | 상태 |
| --- | --- |
| `SummonKind = {normal, special}` | **있다** (`engine.effect.delta` · `engine.summon`) |
| `MonsterSummoned.summon` 이 그것을 싣는다 | **있다** |
| `OperationKind.SPECIAL_SUMMON` | **있다** (어휘) |
| 그 연산을 쓰는 **등재 효과** | **0개** — 등재 연산은 8종뿐 (`DRAW` · `DESTROY` · `DISCARD` · `SEND_TO_GRAVE` · `RETURN_TO_HAND` · `RETURN_TO_DECK` · `CHANGE_LIFE` · `SHUFFLE`) |
| `TimingPoint` 의 **특수소환 전용 시점** | **없다** — `monster_summoned` 하나뿐 |
| `TriggerSpec` 의 **소환 종류 필터** | **없다** — 필터 셋이 `CARD_MOVED` 에만 걸린다 |

**어느 하나를 고쳐도 나머지가 남는다.** 그래서 "증G 를 지원한다" 는 한 걸음이
아니라 네 걸음이다.

### 드롤 유형이 더 먼 까닭

드롤은 **사건에 반응하는 것이 아니라 이후의 행동을 금지**한다. 그것은
`TriggerSpec` 의 문제가 아니라 **지속 효과 / 금지 효과** 계층의 문제이고, 이
저장소에 그 계층이 없다 (`_OUT_OF_SCOPE_TYPES` 가 `CONTINUOUS` 를 범위 밖으로
적어 둔 것과 같은 자리).

---

## 13. Evaluation / Search 영향

**없다.** §10 의 금지를 전부 지켰다.

| 금지 | 확인 |
| --- | --- |
| opponent resource weight 변경 | **안 함** — 가중치 다섯 그대로 |
| `W = -300` 등 숫자 확정 | **안 함** |
| board / resource weight 변경 | **안 함** |
| Search ranking 의도적 변경 | **안 함** — production diff 0 이므로 바뀔 자리가 없다 |
| 증G / 후와로스 / 드롤 전용 로직 | **안 함** — 카드 이름·passcode 가 production 에 0건 |

`test_17` 이 못박는다 — `StateValue` 네 칸 · `SearchCandidate` 네 칸 ·
`(DECK_CARD_IN_LP, HAND_CARD_IN_LP, MONSTER_IN_LP) == (300, 200, 500)` ·
`agent/evaluation.py` 에 `TimingPoint` 없음 · `agent/search.py` 에 `TriggerSpec`
· `TimingEvent` 없음.

---

## 14. state_hash / RNG / hidden-info 영향

| 질문 | 결과 |
| --- | --- |
| production 수정 | **0줄** → 모든 불변식이 자동으로 유지된다 |
| `state_hash` | 바뀔 자리 없음 |
| RNG | 바뀔 자리 없음 |
| hidden information 경계 | **그대로** — 이 Phase 가 읽은 상대 정보는 `hand.size` 뿐이고 그것은 공개 사실이다 (3-F-2 §5) |
| Search ranking | 바뀔 자리 없음 |

fixture 가 쓴 `state.create_instance` · `state.move` · `state.draw` 는 **테스트
안에서 판을 세우는 도구**이고, 판정(`_activation_gate`)은 읽기만 한다.

---

## 15. 테스트 결과

### 새로 더한 것

`tests/test_trigger_condition_separation_audit.py` — **18개** (전부 통과).

| 묶음 | 내용 |
| --- | --- |
| A (`test_01`–`05`) | `EffectDefinition` 에 사건 칸 없음 · `TriggerSpec` 이 `point` 를 든다 · `EVENT_*` 는 파서 계층(16,381 · 70) · 등재 16개 전부 `EVENT_FREE_CHAIN` · 조건 8개는 전부 **상태** 조건 |
| B (`test_06`–`test_11`) | **같은 EVENT + 조건 차이 → 다른 판정** (마법 셋) · **ELIGIBILITY ≠ ACTIVATION** · 함정은 조건 차이가 안 보인다 · 사건 차이는 LIVE 로 불가 |
| C (`test_12`–`14`) | 특수소환 **세 계층 공백** — 어휘는 있고 시점·필터·등재 효과가 없다 |
| D (`test_15`–`16`) | 세 거부 의미가 갈려 있다 · `UNIMPLEMENTED` ≠ 사건 부재 |
| E (`test_17`–`18`) | Evaluation/Search 무변경 · dormant 미연결 |

### §13 의 12개 요구와 대응

| § | 요구 | 어디서 |
| --- | --- | --- |
| 1 | 서로 다른 EVENT 가 구분되는가 | `test_11` — **LIVE 로는 불가**가 답이다 |
| 2 | 같은 EVENT + 다른 condition | `test_06`–`test_08` (가능) · `test_10` (함정은 불가) |
| 3 | condition TRUE/FALSE 가 결과 차이를 만드는가 | `test_06`·`test_07`·`test_08` |
| 4 | eligibility 와 activation 구분 | **`test_09`** |
| 5 | INVALID 와 UNKNOWN 구분 | `test_15` |
| 6 | `RULE_NOT_IMPLEMENTED` ≠ 사건 부재 | `test_16` |
| 7 | hidden information 경계 유지 | production diff 0 + 읽은 것은 `hand.size` 뿐 |
| 8 | `state_hash` 변화 없음 | production diff 0 |
| 9 | RNG 변화 없음 | production diff 0 |
| 10 | Search ranking 변화 없음 | `test_17` + production diff 0 |
| 11 | `RuleBasedPolicy` regression | 전체 회귀 + `agent/heuristic.py` diff 0 |
| 12 | 전체 regression | 아래 |

### 전체 회귀

```
$ python3 -m pytest tests/test_trigger_condition_separation_audit.py -p no:randomly -q
18 passed in 2.97s

$ python3 -m pytest -p no:randomly -q
4177 passed, 4 skipped in 431.36s (0:07:11)
```

| | 통과 | skip |
| --- | --- | --- |
| Phase 3-F-3 직후 (baseline) | 4,159 | 4 |
| Phase 3-F-4 (이번) | **4,177** | 4 |
| 차이 | **+18** | 0 |

**+18 이 이번에 더한 시험 수와 정확히 같다.** 기존 테스트 **수정 0건** ·
**삭제 0건** · **skip 추가 0건** — production diff 가 0 이므로 기존 계약이
깨질 자리가 없었다. skip 4 건은 baseline 과 동일한 기존 skip 이다.

### 고의 위반 검증 — 5건, 전부 잡았다

| # | 위반 | 잡은 테스트 |
| --- | --- | --- |
| 1 | 조건 거짓에 `RULE_NOT_IMPLEMENTED` (거부↔모름 혼동) | `test_06`·`test_07`·`test_08`·`test_15` |
| 2 | 함정을 발동 범위 안으로 받는다 | `test_10`·`test_15` |
| 3 | `MONSTER_SUMMONED` 에 필터를 허용한다 | `test_13` |
| 4 | `duel.py` 가 `TriggerRegistry` 를 import | `test_02`·`test_18` |
| 5 | 대상 부족을 `CANDIDATE_NOT_ELIGIBLE` 로 (eligibility↔activation 혼동) | `test_09`·`test_15` |

복원은 매번 md5 로 확인했다.

### 측정 방법에 대한 정정

`test_14` 가 **엉뚱한 이유로 통과할 수 있었다.** `getattr(op, "kind", None)` 이
전부 `None` 을 돌려주면 "`SPECIAL_SUMMON` 을 쓰는 효과가 없다" 가 **그냥**
참이 된다. 실제로 읽힌 연산 종류 8개를 함께 못박아 고쳤다 — 이제 조회가 깨지면
테스트가 실패한다.

---

## 16. 최종 판정

### **B. SCENARIO_FOUNDATION_INSUFFICIENT**

근거:

* **조건 기반 scenario 는 지금 production 에서 만들 수 있다** — 마법 셋에서
  조건 하나를 뒤집어 `VALID/OK` ↔ `INVALID/CANDIDATE_NOT_ELIGIBLE` 로 판정이
  갈리는 것을 측정했다. 그리고 ELIGIBILITY 와 ACTIVATION 이 **다른 코드**로
  갈린다.
* **사건 기반 scenario 는 만들 수 없다** — 등재 16효과 전부 `EVENT_FREE_CHAIN`
  이고(사건에 반응하는 효과가 0개), 발동 열거가 사건을 읽지 않는다.
* **함정의 조건 차이도 보이지 않는다** — 범위 검사가 조건 평가보다 먼저 걸린다.
  그리고 그것은 올바른 동작(`UNKNOWN`)이므로 **고칠 결함이 아니라 받아들일
  한계**다.
* **그런데 Engine V1 변경까지는 아직 필요하지 않다** — 지금 Evaluation 이 필요한
  benchmark(조건 차이 · 상대 자원 차이) 는 LIVE 와 fixture 로 전부 만들 수 있다.
  구조 변경이 필요한 것은 "그 상태가 **실제 플레이에서 생기는가**" 라는 **다음**
  질문이고, 3-F-3 이 이미 그것을 blocker 로 기록했다.

`A. TRIGGER_CONDITIONS_SUFFICIENT` 가 아닌 까닭: "충분히" 가 아니다. 네 단계 중
**앞 두 단계(EVENT · TRIGGER CONDITION)가 LIVE 에 없다.**

`C. ENGINE_V1_BOUNDARY_BLOCKS` 가 아닌 까닭: 지금 필요한 benchmark 를 만드는 데
Engine V1 변경이 **필요하지 않다.** 변경이 필요한 것은 더 뒤의 요구이고, 그것을
지금의 blocker 로 적으면 범위를 넘겨 읽게 된다.

`D. STRUCTURAL_BLOCKER_FOUND` 가 아닌 까닭: 예상하지 못한 것이 없었다. 세 계층
공백도 함정 범위도 **이미 이름이 붙어 기록된** 공백이다 (3-E-16 · 3-E-31 ·
3-E-32 · 3-E-43 · 3-F-3).

### 이번 Phase 에서 하지 않은 것

§16 의 금지 목록 전부 확인:

* 3-F-3 재실행 · weight 재측정 · 상수 추가 — **없음**
* 증G / 후와로스 / 드롤 hardcode · 카드별 패트랩 대응표 — **없음**
* Opponent Model · Depth-2 Search · MCTS · RL · Neural Network · Self-play ·
  Deck Builder · Card Evaluation AI · UI/API · README · Lua 위치 — **없음**
* **dormant pipeline 의 무단 production 연결 — 없음** (`test_18`)
* **Engine V1 freeze 해제 — 없음**

```
$ git diff --stat -- engine agent app core analysis rules rulings sources scripts
(출력 없음 — production 수정 0줄)
```

산출물은 둘뿐이다: `tests/test_trigger_condition_separation_audit.py` (신규) ·
`docs/phase3f4-trigger-condition-separation.md` (이 보고서).

---

## 17. 다음 Phase 후보 (1개)

**Phase 3-F-5 — `SPECIAL_SUMMON` 연산을 쓰는 효과 하나를 등재할 수 있는지 감사**

§12 의 네 걸음 중 **①(데이터)만** 보는 Phase 다. 그것이 구조 변경이 아니고,
나머지 세 걸음의 **필요성을 실제로 확인할 수 있는 유일한 입구**이기 때문이다.

그 Phase 가 답해야 할 것:

1. `OperationKind.SPECIAL_SUMMON` 을 쓰는 효과를 **지어내지 않고** 등재할 수
   있는가 — 공식 Lua 에서 그 연산으로 읽히는 카드가 실제로 있는지부터 센다.
2. 등재하면 `MonsterSummoned(summon=SPECIAL)` 델타가 **실제로 생기는가.**
   생긴다면 `timing_for` 가 그것을 `MONSTER_SUMMONED` 로 옮기는지 확인한다.
3. 그때 `TimingPoint` 에 소환 종류가 없다는 공백이 **실제로 문제가 되는가** —
   지금은 가정이고, 델타가 생긴 뒤에야 측정할 수 있다.
4. ①이 Engine V1 freeze 와 충돌하는가 — 효과 등재는 데이터지만 `special_summon`
   실행 경로가 live 에 닿는다면 그것은 별도 승인이 필요하다.

**이 Phase 는 그 작업을 하지 않았다. 다음 Phase 는 임의로 진행하지 않는다.**
