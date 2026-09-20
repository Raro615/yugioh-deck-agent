# Phase 2-P — Effect Execution Scenario Validation

기준 커밋: `e465a43` (Phase 2-O completion fix)

**새 기능을 만들지 않는 단계다.** 지금까지 쌓인 실행 경로가 서로 다른 효과
유형에서도 같은 약속을 지키는지, 실제 시나리오로 확인한다.

```
정의  →  (대상)  →  의미  →  조작  →  GameState  →  Delta  →  사건  →  기록
```

엔진 코드는 **한 줄도 바꾸지 않았다.** 추가된 것은 시나리오 테스트 파일
하나뿐이다.

---

## 1. 조사 — 지시서의 경로와 실제 경로

| 지시서 (§2) | 실제 위치 |
|---|---|
| `engine/targeting.py` | **`engine/effect/targeting.py`** (Phase 2-N) |
| `engine/operation.py` | **`engine/effect/operation.py`** (Phase 2-L) |

나머지(`engine/effect/`, `executor.py`, `resolution.py`, `event_pipeline.py`,
`chain.py`, `cost/`)는 지시서 그대로다. 두 파일은 `engine/` 최상위가 아니라
`engine/effect/` 안에 있고, 그것이 의도된 배치다 — 대상과 조작은 효과 계층의
부품이지 독립 계층이 아니다.

**새 abstraction 이 필요한지 먼저 확인했고, 필요하지 않았다.** 다섯 시나리오
전부 기존 타입으로 표현된다.

| 필요했던 것 | 이미 있던 것 |
|---|---|
| 대상 없는 효과 | `EffectDefinition.targets = ()` |
| 대상 있는 효과 | `TargetBinding` + `TargetSpec.targeting` |
| 의미 없는 이동 | `MoveOperation` (Phase 2-L) |
| 파괴 판정 | `DestructionRuling` (Phase 2-M) |
| 사건 읽기 | `EventReader` → `ObservedEvent` → `TimingEvent` (Phase 2-J) |
| 실패 분류 | `ResolutionStatus` × `ValidationCode` |

---

## 2. 시나리오 A — 대상을 지정하는 효과 (회귀)

두 경로를 Phase 2-O 그대로 유지한다.

| | 결과 |
|---|---|
| 실제 싸이크론 (판정기 없음) | 대상 `LEGAL` → `DESTROY` → **`UNCHECKED_RULES`** → mutation 없음 |
| synthetic (판정 확인됨) | 대상 `LEGAL` → `DESTROY` → `MOVE` → GRAVE → Delta → Event → Journal |

---

## 3. 시나리오 B — 대상을 쓰지 않는 효과

**실제 카드가 끝까지 간다.** 파괴가 아니므로 받을 판정이 없다.

| 카드 | 결과 |
|---|---|
| 욕망의 항아리 (55144522) | `RESOLVED` · 패 +2 · `CardDrawn` ×2 |
| 은혜의 단비 (66719324) | `RESOLVED` · 양쪽 LP +1000 · `LifeChanged` ×2 |

`targets == ()` 이므로 `pending_targets()` 가 비고, 빈 `selections` 로도
해결된다 — **대상 계층에 들어가지 않는다.**

### 🟠 그런데 `targets == ()` 하나로는 두 가지가 구분되지 않는다

| | `targets` | 뜻 |
|---|---|---|
| 욕망의 항아리 | `()` | 대상을 **요구하지 않는다** |
| 블랙홀 (53129443) | `()` | "필드의 몬스터 **전부**" 를 `TargetSpec` 이 담지 못한다 (STRUCTURAL-10) |

정의의 **모양이 같다.** 지금 둘을 가르는 것은 정의 밖의
`LibraryEntry.executable` 과 `note` 이고, 등록되지 않은 블랙홀은
`NOT_IMPLEMENTED` 로 멈춘다. 안전하지만, 구분이 정의 자체에 없다는 사실은
적어 둔다 (**STRUCTURAL-54**).

---

## 4. 시나리오 C — `MOVE` 의 경계

`MOVE` 는 **의미를 주장하지 않는 저수준 이동**이다. 세 경로를 실제로 실행한다.

| 출발 | 도착 | 결과 |
|---|---|---|
| `HAND` | `GRAVE` | `RESOLVED` |
| `HAND` | `DECK` | `RESOLVED` |
| `GRAVE` | `HAND` | `RESOLVED` |

지켜지는 구분:

- `applied[0].reason_names == ()` — `REASON_EFFECT` **조차** 주장하지 않는다.
- 같은 패에서 같은 묘지로 가도 `MOVE` 와 `DISCARD` 는 **다른 사건**이다
  (`operation` 과 `reason_names` 가 다르다).
- 사건도 `operation=MOVE` 로 읽힌다 — `DESTROY` 로 보이지 않는다.
- 필드(`MZONE`/`SZONE`/`EMZONE`/`FZONE`/`PZONE`)로는 옮길 수 없다.

**같은 판 · 같은 대상 · 판정기 없음**으로 나란히 돌리면:
`DESTROY` 는 `UNCHECKED_RULES` 로 멈추고 `MOVE` 는 지나간다. 판정을 요구하는
것은 **의미를 주장하는 쪽**이라는 사실이 여기서 눈에 보인다. 뒤집어 말하면
`MOVE` 로 파괴를 우회해도 아무 트리거도 보지 못한다.

---

## 5. 시나리오 D — 실패 행렬

아홉 갈래를 **각각 새 판에서** 돌리고 `(status, code)` 를 모은다. 전부
`applied == ()` · `deltas == ()` · `state_hash` 불변.

| # | 상황 | status | code |
|---|---|---|---|
| 1 | `TEXT_DERIVED` | `FORBIDDEN` | `RULE_NOT_IMPLEMENTED` |
| 2 | `LUA_VERIFIED` + 구현 없음 | `NOT_IMPLEMENTED` | `RULE_NOT_IMPLEMENTED` |
| 3 | 부적법한 대상 | `INVALID_TARGET` | `CANDIDATE_NOT_ELIGIBLE` |
| 4 | 모르는 대상 | `UNCHECKED_TARGET` | `INFORMATION_UNAVAILABLE` |
| 5 | 대상 없음 | `INVALID_TARGET` | `TOO_FEW_SELECTED` |
| 6 | 자리를 떠난 대상 | `INVALID_TARGET` | `CANDIDATE_NOT_ELIGIBLE` |
| 7 | 모르는 파괴 규칙 | `UNCHECKED_RULES` | `RULE_NOT_IMPLEMENTED` |
| 8 | 못 하는 일 | `UNSUPPORTED_OPERATION` | `RULE_NOT_IMPLEMENTED` |
| 9 | 다른 효과의 문맥 | `INVALID_CONTEXT` | `EFFECT_REF_CARD_MISMATCH` |

### 🟠 아홉 갈래가 **여덟 개**의 답으로 나온다 — STRUCTURAL-53

**3 번과 6 번이 같다.**

- 3 번: "자신 필드의 몬스터" 인데 상대 몬스터를 골랐다 — **고른 순간부터 틀렸다.**
- 6 번: 고를 때는 후보였는데 그 사이에 자리를 떠났다 — 유희왕에서는
  **"대상이 필드를 벗어나 불발"** 이고, 발동 자체가 위법이었던 것과 다른 사건이다.

실행기가 "지금 후보인가" 만 볼 수 있고 **발동 시점에 확정된 대상**을 들고
있지 않기 때문이다 (STRUCTURAL-51 의 구체적 증상).

위험하지는 않다 — 둘 다 거절하고 판을 건드리지 않는다. 테스트는 이 사실을
**덮지 않고 그대로 적는다**: 여덟 개라고 단언하고, 겹치는 쌍을 따로 본다.
이번 단계에서 고치지 않는다 (§8: 새 시스템을 만들지 않는다).

### 앞의 일이 성공해도 뒤가 막히면 전부 취소된다

`DrawOperation` + `DESTROY` 를 한 정의에 넣고 판정기를 주지 않으면, 드로우도
일어나지 않는다. 계획이 **전부** 끝난 뒤에야 적용이 시작되기 때문이다.

---

## 6. 시나리오 E — 결정론 · 복제 독립성 · 정보 경계

| 보는 것 | 확인 |
|---|---|
| 같은 입력 → 같은 결과 | `EffectResult.canonical_state()` 가 같다 |
| 같은 입력 → 같은 판 | `state_hash()` 가 같다 |
| 같은 입력 → 같은 사건 identity | `ObservedEvent.event_id` 가 같다 |
| 실패도 결정적인가 | 싸이크론의 `UNCHECKED_RULES` 가 두 판에서 같다 |
| **복제 독립성** | 복제본에서 실행해도 원본의 `state_hash` 불변, 카드도 제자리 |
| 복제본의 답 | 원본과 같은 `canonical_state()` |
| 상대의 패 | 후보가 되지 않고, `unchecked` 에 남는다 (`fully_checked is False`) |
| 뒷면 카드 | 실패 메시지와 `to_dict()` 어디에도 `card_id` 가 없다 |

---

## 7. 중복 시스템이 생기지 않았는가

테스트가 AST 로 확인한다.

- `engine/effect/` 의 파일 목록이 Phase 2-O 와 **정확히 같다** (새 모듈 0개).
- `EffectExecutor` · `TargetResolver` · `CandidateResolver` · `EventReader` ·
  `EventPipeline` 이 각각 **한 곳에서만** 정의된다.
- `engine/` 어디에도 이름에 `Bus` 가 들어간 클래스가 없다.
- 이 시나리오 파일 자체가 클래스를 하나도 정의하지 않는다 — 흉내 내면
  검증이 아니라 두 번째 구현이 된다.

---

## 8. 실제 카드

| 카드 | 유형 | 결과 |
|---|---|---|
| 욕망의 항아리 (55144522) | 비대상 · 드로우 | **`RESOLVED`** — 실제 카드가 끝까지 간다 |
| 은혜의 단비 (66719324) | 비대상 · 라이프 | **`RESOLVED`** |
| 싸이크론 (5318639) | 대상 · 파괴 | `UNCHECKED_RULES` — 규칙 지식이 없어 멈춘다 |
| 블랙홀 (53129443) | 대상 규칙을 못 옮김 | `NOT_IMPLEMENTED` |

실제 카드의 재정을 지어내지 않았다. `DeclaredDestructionRuling` 을 받는 것은
synthetic 정의뿐이다.

---

## 9. 테스트

`tests/engine/test_effect_scenarios.py` — 함수 **40개**, 실행 **42건**
(시나리오 C 에 `parametrize` 3갈래). 전부 통과.

| 묶음 | 함수 | 보는 것 |
|---|---|---|
| A. 대상 효과 | 2 | Phase 2-O 두 경로 회귀 |
| B. 비대상 효과 | 8 | 대상 계층에 들어가지 않는다 · `targets==()` 의 모호함 |
| C. `MOVE` | 7 | 의미를 주장하지 않는다 · 판정을 요구하지 않는다 |
| D. 실패 행렬 | 12 | 아홉 갈래 + 집계 + 겹침 기록 + 전체 취소 |
| E. 결정론 · 경계 | 7 | 같은 답 · 복제 독립 · 정보 경계 |
| F. 중복 금지 | 4 | 새 모듈 · 중복 클래스 · `EventBus` 없음 |

전체 회귀: **1988 passed, 4 skipped** (직전 1946 + 42). 기존 테스트 수정·삭제
**0건**.

---

## 10. 남은 것 (기록만 — 이번 단계에서 고치지 않는다)

- **STRUCTURAL-53 (신규)** — "애초에 부적법한 대상" 과 "고른 뒤 자리를 떠난
  대상" 이 같은 `(INVALID_TARGET, CANDIDATE_NOT_ELIGIBLE)` 로 나온다.
  STRUCTURAL-51(발동 시점 대상 확정)이 생겨야 갈린다.
- **STRUCTURAL-54 (신규)** — `EffectDefinition.targets == ()` 가 "대상이
  없다" 와 "대상 규칙을 옮기지 못했다" 를 구분하지 못한다. 지금은
  `LibraryEntry.executable`/`note` 가 정의 **밖에서** 들고 있다.
- STRUCTURAL-50 (`IsRelateToEffect` 없음) · 51 · 52 (`PZONE` 미확인) ·
  15 (`unchecked` 를 비용 검증기가 안 읽음) · 10 (존 전체 일괄 처리) ·
  7 (`EffectSpec → EffectDefinition` 컴파일러 없음) — 전부 유지.
- 실행 가능한 실제 카드는 여전히 **3장**이다.
