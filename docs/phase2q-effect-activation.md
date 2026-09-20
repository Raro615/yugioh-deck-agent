# Phase 2-Q — Effect Activation Core

기준 커밋: `127b1da` (Phase 2-P Effect Execution Scenario Validation)

```
PlayerAction(ACTIVATE_EFFECT)
    ↓  EffectActivator.can_activate()      읽기만 한다 → ValidationResult
    ↓  EffectActivator.activate()
       ├ 모양 검사 (종류 · effect_ref · source)
       ├ 허가        ← 밖에서 온다 (VALID 만)
       ├ 정의 조회 · 문맥 일치
       ├ 실행 권위   (TEXT_DERIVED · 미검증 · 미등록)
       ├ 발동 조건   (TRUE 만)
       ├ 대상 검증   (Phase 2-N TargetResolver)
       ├ 체인 수용   ← **지불 전에** 본다
       ├ 비용 지불   (Phase 2-E CostPayer)  ← 발동에서 판이 바뀌는 유일한 곳
       └ ChainLink → Chain.push()
    ↓  ................................   (다른 시점, 다른 호출)
ChainResolver.resolve_top()
    ↓
EffectExecutor → Operation → GameState → Delta → EventPipeline
```

**이 단계의 전부는 한 줄이다: 발동 ≠ 해결.**

---

## 1. 변경 파일

| 파일 | 변경 |
|---|---|
| `engine/activation.py` | **신규** — `ActivationStatus` · `ActivationResult` · `EffectActivator` |
| `tests/engine/test_effect_activation.py` | 신규 — 함수 47개 |
| `docs/phase2q-effect-activation.md` | 신규 |
| `engine/__init__.py` | Phase 2-Q 항목 |

기존 모듈은 **한 줄도 바꾸지 않았다.** `Chain` · `ChainLink` · `CostPayer` ·
`TargetResolver` · `PriorityState` · `EffectExecutor` 전부 그대로다.

---

## 2. 조사 — 지시서의 경로와 실제 경로

| 지시서 (§3) | 실제 |
|---|---|
| `engine/targeting.py` | `engine/effect/targeting.py` |
| `engine/game_state.py` | `engine/state/game_state.py` |
| `engine/operation.py` | `engine/effect/operation.py` |

**이미 있는 것을 먼저 확인했고, 새로 만든 것은 발동 계층 하나뿐이다.**

| 필요했던 것 | 이미 있던 것 |
|---|---|
| 체인 · 링크 · LIFO 해결 | `Chain` · `ChainLink` · `ChainResolver` (Phase 2-F-2) |
| 비용 지불 | `CostPayer` · `PaymentContext` · `CostSelection` (Phase 2-E) |
| 대상 판정 | `TargetResolver` (Phase 2-N) |
| 우선권 | `PriorityState.acted()` (Phase 2-F-1) |
| 실행 권위 | `execution_availability` (Phase 2-D-1) |
| 판정 어휘 | `ValidationResult` · `ValidationCode` |

`ChainLink` 는 이미 `selections` 와 `payments` 칸을 들고 있었다 — 발동 계층을
기다리고 있던 자리다. 그 칸을 채우는 것이 이번 단계다.

---

## 3. `ACTIVATE_EFFECT` 흐름

`EffectActivator.activate(state, chain, action, selections, cost_selections,
authorization)` → `ActivationResult`.

**순서가 규칙이다.** 읽기만 하는 검사를 전부 끝내고, 체인이 링크를 받을 수
있는지까지 확인한 뒤에야 비용을 치른다. 치른 뒤에 거절당하면 되돌릴 방법이
없기 때문이다 (ADR-008 이 rollback 을 미뤄 두었다).

### `ActionExecutor` 에 등록하지 않는다 — 🟠 STRUCTURAL-55

`ActionHandler` 는 `apply(state, action) -> tuple[StateDelta, ...]` 다. 그런데
발동의 결과물은 판의 모양이 아니라 **흐름의 위치**(`Chain`)이고, 그것은
`GameState` 밖에 산다 (`EventJournal` · `PriorityState` 와 같은 이유).

`ActionHandler` 로 끼워 넣으면 체인을 어딘가 숨겨 두고 주고받아야 한다.
숨긴 통로는 통로가 아니다. 그래서 발동은 자기 진입점을 갖고, `ActionExecutor`
는 `engine.activation` 도 `engine.chain` 도 import 하지 않는다 (테스트가
AST 로 확인한다).

---

## 4. Activation Check

`can_activate()` 는 **읽기만 한다.** 새 어휘를 만들지 않고
`ValidationResult`(VALID / INVALID / UNKNOWN)를 그대로 돌려준다.

| 보는 것 | 통과하지 못하면 |
|---|---|
| 행위의 모양 (종류 · `effect_ref` · `source`) | `INVALID_ACTION` |
| **허가** (페이즈 · 우선권 · 타이밍) | `UNAUTHORIZED` |
| 정의가 있는가 | `NOT_IMPLEMENTED` |
| 정의와 행위가 같은 효과인가 | `INVALID_CONTEXT` |
| 출처 (ADR-004) | `FORBIDDEN` |
| 의미 검증 | `UNVERIFIED` |
| 실행 구현 등록 (ADR-006) | `NOT_IMPLEMENTED` |
| 발동 조건 | `CONDITION_FALSE` · `CONDITION_UNKNOWN` |
| 대상 (Phase 2-N) | `INVALID_TARGET` · `UNCHECKED_TARGET` |
| 체인 수용 | `CHAIN_REFUSED` |

### 허가는 밖에서 온다

`ActionValidator` 는 오늘 `ACTIVATE_EFFECT` 에 **`UNKNOWN`** 을 돌려준다 —
발동 타이밍 계층(`activation-condition · cost · timing`)이 없기 때문이다.

그래서 허가를 건네지 않으면 언제나 `UNAUTHORIZED` 다. **`UNKNOWN` 을 허가로
바꾸지 않고**, 우회하려고 이 모듈이 타이밍 규칙을 지어내지도 않는다. 부르는
쪽이 명시적인 `VALID` 를 건네야 하고 그 판단의 책임은 건넨 쪽에 있다 —
`ActionExecutor.execute(authorization=...)` 과 같은 자리다.

테스트는 `GRANTED = ValidationResult.valid("테스트가 발동 타이밍을 허가했다")`
를 건넨다. Phase 2-M 의 `DeclaredDestructionRuling` 과 같은 성격의 값이다.

### 왜 새 `ActivationStatus` 인가

| 기존 | 왜 쓸 수 없는가 |
|---|---|
| `ResolutionStatus` | **해결**의 결과다. 발동에 쓰면 이 단계의 전부인 구분이 무너진다 |
| `ActionStatus` | 판을 바꾸는 행위의 결과다. "비용을 못 냈다" 와 "대상이 틀렸다" 를 구분할 칸이 없다 |

`code` 는 기존 `ValidationCode` 를 그대로 쓴다 — **새 코드 어휘는 만들지
않았다.**

---

## 5. Cost

Phase 2-E 의 `CostPayer` 를 **그대로** 쓴다. 비용 로직을 다시 구현하지
않았다 (`CostPayer(journal=...)` 를 주면 그 기록기가 자기 기록을 남긴다는
것으로 확인한다).

- 비용은 **발동에서** 치른다 — 발동이 판을 바꾸는 유일한 자리다.
- 영수증(`CostPayment`)은 링크가 **참조로만** 들고 간다. 해결 중에 다시
  치르지 않는다 (라이프가 두 번 깎이지 않음을 테스트가 확인한다).
- 비용 선택도 **값으로 온다** — 엔진이 고르지 않는다.

### 🟠 STRUCTURAL-56 — `can_activate` 는 비용을 약속하지 못한다

`CostPayer._preflight` 는 비공개다. 밖에서 흉내 내면 두 벌이 갈리므로
`can_activate` 는 비용을 보지 않는다. 그래서 `VALID` 인데 `activate` 가
`COST_UNPAYABLE` 로 멈출 수 있다. **그때도 링크는 생기지 않고 판도 바뀌지
않는다** — 정확하지 않을 뿐 위험하지는 않다.

### rollback 구멍 (§11)

지불 뒤에 실패할 수 있는 자리를 **구조적으로 없앴다**: 체인 수용을 지불
전에 확인하고, 링크 생성은 실패할 수 없다. 남은 것은 `CostPayer` 자신의
`EXECUTION_ERROR` 하나뿐이고, 그것은 `ActivationStatus.COST_ERROR` 로
나오며 "판이 반쯤 바뀌어 있을 수 있다" 고 적혀 있다. 되돌리기는 ADR-008.

---

## 6. Target

Phase 2-N 의 `TargetResolver` 를 그대로 쓴다. 정의의 `TargetBinding` 마다
`validate(spec, selection, context, ref)` 를 부르고, **`LEGAL` 일 때만**
통과시킨다.

- 대상을 요구하지 않는 효과에 선택이 들어오면 `INVALID_TARGET`.
- 아직 고르지 않았으면 `INVALID_TARGET` / `TOO_FEW_SELECTED`.
- 가려진 정보면 `UNCHECKED_TARGET` — **`ILLEGAL` 과 합치지 않는다.**

### 발동 시점 snapshot 은 만들지 않았다 (§7)

링크는 **고른 결과**를 들고 가지만 "그때 적법했다" 는 사실은 어디에도 남지
않는다. 억지로 snapshot 시스템을 만들지 않았다 — STRUCTURAL-51 과
STRUCTURAL-53 이 이 단계에서 그대로 드러난다:

- **STRUCTURAL-51** — 발동 시점 대상 확정이 없다. 링크가 `selections` 를
  들고 가는 것으로 절반은 메워졌지만, 해결 직전 재검증은 여전히 "지금
  후보인가" 만 본다.
- **STRUCTURAL-53** — 그래서 "고른 뒤 자리를 떠난 대상" 과 "애초에 부적법한
  대상" 이 해결에서 같은 답으로 나온다.

---

## 7. ChainLink

| 칸 | 값 |
|---|---|
| `sequence` | `len(chain)` — 체인 1 이 `0` |
| `actor` | `action.actor` |
| `effect_ref` | `action.effect_ref` |
| `source` | `action.source` |
| `selections` | 발동 시점에 고른 대상 |
| `payments` | 이미 치른 영수증 |

정의는 담지 않는다 — 담으면 링크가 낡은 정의를 영구히 들고 다닌다.
`canonical_state()` 가 전부 값 타입이라 identity 가 결정적이다.

---

## 8. Chain insertion

`chain.push(link)` — **새 체인**을 돌려준다. 원래 체인은 그대로다.
실패하면 `ActivationResult.chain` 이 **들어온 체인 그대로**다 (`None` 을
돌려주면 "체인이 없다" 와 "체인이 그대로다" 가 구분되지 않는다).

두 번째 발동은 체인 2 로 **위에** 쌓이고, `resolution_order` 가 뒤에서부터
푼다.

---

## 9. Priority

`EffectActivator.advance_priority(priority)` → `priority.acted()`.
**새 우선권 시스템을 만들지 않았다.**

`activate()` 는 `priority` 인자를 **받지 않는다.** 누가 언제 우선권을
옮겨야 하는지가 아직 정해지지 않았으므로(STRUCTURAL-34), 몰래 옮기는 대신
부르는 쪽이 고른다. 테스트가 `inspect.signature` 로 그 사실을 고정한다.

---

## 10. Activation vs Resolution

| | 발동 직후 | 해결 후 |
|---|---|---|
| 체인 | 링크 1개 | `is_complete` |
| 대상 카드 | **MZONE 그대로** | GRAVE |
| `state_hash` | **불변** (비용이 없으면) | 바뀜 |
| `deltas` | `()` — 비용이 없으면 | 효과의 변화 |
| `EventReader` | **사건 0건** | 사건 1건 |
| `EffectExecutor` | **불리지 않음** | 불림 |

마지막 줄을 코드로도 고정했다: `engine/activation.py` 는 `EffectExecutor`
를 import 하지 않고, `EffectExecutor` · `ChainResolver` · `execute` 라는
이름을 **쓰지도 않는다** (AST 확인).

---

## 11. synthetic end-to-end

"필드의 몬스터 1장을 대상으로 파괴한다" (출처 `hand_written`, 어떤 실제
카드의 의미도 주장하지 않는다).

```
ACTIVATE_EFFECT → 대상 선택(값으로) → 비용 없음 → ChainLink → Chain[1]
   ↳ 대상은 MZONE 그대로, state_hash 불변, 사건 0건
ChainResolver.resolve_top → EffectExecutor → DESTROY → MOVE → GRAVE
   ↳ state_hash 변경, 사건 1건
```

비용이 있는 판(`LifeCost(800)`)에서는 **발동에서** 라이프가 줄고, 해결에서는
다시 줄지 않는다.

---

## 12. 실제 카드

| 카드 | 발동 | 해결 |
|---|---|---|
| 욕망의 항아리 (55144522) | `ACTIVATED` — 판 불변, 드로우 없음 | `RESOLVED` — 그제서야 2장 |
| 싸이크론 (5318639) | `ACTIVATED` — 대상 규칙 전부 통과 | **`UNCHECKED_RULES`** — 파괴 판정이 없어 멈춤 |

싸이크론의 두 줄이 이 단계의 요점을 그대로 보여 준다: **발동이 되는 것과
해결이 되는 것은 다른 계층의 답이다.** 실제 카드의 재정을 지어내지 않았다.

욕망의 항아리의 `CONDITION_FALSE` 테스트는 스크립트에서 옮긴 실제 조건
(`덱 2장 이상`)을 쓴다 — 규칙을 추측하지 않았다.

---

## 13. Failure matrix

전부 **링크 없음 · 체인 불변 · `state_hash` 불변**.

| # | 상황 | status | code |
|---|---|---|---|
| A | `effect_ref` 없음 | `INVALID_ACTION` | `EFFECT_REF_REQUIRED` |
| A | 정의 없는 `EffectRef` | `NOT_IMPLEMENTED` | `RULE_NOT_IMPLEMENTED` |
| — | 허가 없음 / `UNKNOWN` 허가 | `UNAUTHORIZED` | 검증기의 코드 |
| B | `TEXT_DERIVED` | `FORBIDDEN` | `RULE_NOT_IMPLEMENTED` |
| C | 구현 미등록 | `NOT_IMPLEMENTED` | `RULE_NOT_IMPLEMENTED` |
| D | 비용 부족 | `COST_UNPAYABLE` | `INSUFFICIENT_LIFE` 등 |
| E | 부적법한 대상 | `INVALID_TARGET` | `CANDIDATE_NOT_ELIGIBLE` |
| E | 대상 미선택 | `INVALID_TARGET` | `TOO_FEW_SELECTED` |
| F | 모르는 대상 | `UNCHECKED_TARGET` | `INFORMATION_UNAVAILABLE` |
| G | 조건 거짓 | `CONDITION_FALSE` | `RULE_NOT_IMPLEMENTED` |
| G | 조건 판정 불가 | `CONDITION_UNKNOWN` | `INFORMATION_UNAVAILABLE` |
| H | 발동이 아닌 행위 | `INVALID_ACTION` | `RULE_NOT_IMPLEMENTED` |
| H | 정의가 다른 효과 | `INVALID_CONTEXT` | `EFFECT_REF_CARD_MISMATCH` |
| I | 해결이 시작된 체인 | `CHAIN_REFUSED` | `RULE_NOT_IMPLEMENTED` |

`CHAIN_REFUSED` 테스트는 비용이 `LifeCost(800)` 인 정의로 돌린다 — **라이프가
빠져나가지 않는다**는 것이 "체인 수용을 지불 전에 본다" 의 증거다.

`ActivationResult` 자체도 모순을 막는다: 실패인데 링크가 있거나, 성공인데
링크가 없거나, 실패인데 변화 기록이 있으면 생성 시점에 `ActivationError` 다.
`__bool__` 은 언제나 `TypeError` 다.

---

## 14. Determinism · clone

| 보는 것 | 확인 |
|---|---|
| 같은 입력 → 같은 링크 | `ChainLink.canonical_state()` 가 같다 |
| 같은 입력 → 같은 체인 | `Chain.canonical_state()` 가 같다 |
| 같은 입력 → 같은 결과 | `ActivationResult.canonical_state()` 가 같다 |
| 실패도 결정적 | 거절 결과의 `canonical_state()` 가 같다 |
| **복제 독립성** | 복제본에서 비용을 치러도 원본의 라이프·해시 불변 |
| 체인 불변성 | 들어온 체인은 그대로, 새 체인이 돌아온다 |

---

## 15. Hidden information

- 거절 사유와 `to_dict()` 어디에도 상대의 뒷면 카드 `card_id` 가 없다.
- 관측은 **언제나 행위자의 시점**으로 만든다 — `viewer=` 키워드가 전부
  `action.actor` 임을 AST 로 확인한다. 물어보는 것만으로 상대의 패를
  탐지할 수 없다.

---

## 16. AI 경계

무엇을 발동해야 하는가는 이 계층의 질문이 아니다. 대상도 비용 선택도
**테스트가 값으로 준다.** `engine/activation.py` 에 `choose` · `score` ·
`policy` · `random` 이 없고, USE/PASS 를 정하는 구조도 없다.

---

## 17. 남은 것 (기록만)

- **STRUCTURAL-55 (신규)** — `ActionHandler` 프로토콜이 "결과물이 흐름의
  위치인 행위"(발동)를 표현하지 못한다. 그래서 발동이 `ActionExecutor` 밖에
  있다. `apply` 가 `StateDelta` 외의 것을 돌려줄 수 있게 되면 합칠 수 있다.
- **STRUCTURAL-56 (신규)** — `can_activate` 가 비용 지불 가능성을 답하지
  못한다 (`CostPayer._preflight` 비공개). `VALID` 여도 `COST_UNPAYABLE` 로
  멈출 수 있다.
- **STRUCTURAL-34 (관찰)** — 우선권 갱신의 주체가 정해지지 않았다.
  `activate()` 가 우선권을 건드리지 않는 것으로 피해 간다.
- **STRUCTURAL-51 · 53 (관찰, §7 대로 드러남)** — 링크가 `selections` 를
  들고 가지만 "발동 시점에 적법했다" 는 사실은 남지 않는다.
- 나머지(45 · 46 · 48 · 49 · 50 · 52 · 54 · 15 · 10 · 7) 변동 없음.
- 아직 없는 것: SEGOC · 스펠 스피드 · 체인 중 발동 · 강제 트리거 · 타이밍
  놓침 · 발동 타이밍 규칙 그 자체.

---

## 18. 테스트

`tests/engine/test_effect_activation.py` — 함수 **47개**, 전부 통과.

| 묶음 | 함수 | 보는 것 |
|---|---|---|
| A. 허가 | 5 | `UNKNOWN` 은 발동 허가가 아니다 |
| B. 발동 ≠ 해결 (실제 카드) | 7 | 발동해도 아무 일도 일어나지 않는다 |
| C. synthetic end-to-end | 4 | 발동 직후 ≠ 해결 후 |
| D. 비용 | 6 | Phase 2-E 재사용 · 두 번 내지 않는다 |
| E. 실패 행렬 | 15 | 링크 없음 · 체인 불변 · 판 불변 |
| F. 우선권 | 3 | 기존 구조 재사용 · 몰래 옮기지 않음 |
| G. 결정론 · 경계 | 7 | 같은 답 · 복제 독립 · 정보 경계 |

전체 회귀: **2035 passed, 4 skipped** (직전 1988 + 47). 기존 테스트
수정·삭제 **0건**.
