# Phase 2-X — Real Card Rule Gate Expansion: Grave / Discard

기준 커밋: `60ecef6` (Phase 2-W Real Card Execution Expansion)

> 지시서의 "기준 커밋 2d760d5" 는 Phase 2-V 의 해시다. 지시서가 설명하는
> 상태(Phase 2-W 완료 · 2386 passed)는 `60ecef6` 이므로 그 위에서 작업했다.

```
공식 스크립트의 술어         Card.IsAbleToGrave · Card.IsDiscardable
    ↓  효과가 **선언**한다
CardOperation.gated          한 칸. 추론하지 않는다
    ↓
MovementRuling               TRUE · FALSE · UNKNOWN  (UNKNOWN 은 허가가 아니다)
    ↓  EffectExecutor 관문 — 대상 판정 **뒤**, 변경 **앞**
GameState → StateDelta → ObservedEvent → TimingEvent   (기존 경로 그대로)
```

---

## 1. 변경 파일

| 파일 | 변경 |
|---|---|
| `engine/effect/operation.py` | `DECLARABLE_GATE_KINDS` · `CardOperation.gated` · 공장 두 개에 `gated=` |
| `engine/effect/semantics.py` | `RuleQuestion` · `LUA_GATE_PREDICATES` · `DECLARED_GATE_RULINGS` · `UNASKED_QUESTIONS` · `MovementRuling` · `Unknown/DeclaredMovementRuling` · `declared_gate_question` · `ask_movement` · `GATING_RULES`/`MISSING_GATE` 확장 |
| `engine/effect/executor.py` | `movement=` 판정기 · `_check_rule_gate(operation, instance)` 로 서명 변경 |
| `engine/effect/library.py` | `build_executor(movement=)` · 어리석은 매장(81439173) |
| `tests/engine/test_rule_gate_grave_discard.py` | 신규 — 47개 |
| `tests/engine/test_real_card_execution.py` | 수 단언 2건 갱신 (§15) |
| `docs/phase2x-rule-gate-grave-discard.md` · `engine/__init__.py` | 문서 |

**새 EventBus · EffectEngine · TargetSystem · ChainSystem · OperationSystem ·
RuleEngine 0개.**

---

## 2. 실제 Lua 조사 (§2)

구현 전에 `c*.lua` **12,702개**를 읽었다. 추측한 이름은 하나도 쓰지
않았고, 그 사실을 테스트가 고정한다.

### 존재하지 않는 이름

지시서가 예로 든 것 중 셋은 **코퍼스에 없다.**

| 추측했을 이름 | 실제 사용 |
|---|---:|
| `IsAbleToDiscard` | **0장** |
| `IsCanBeGrave` | **0장** |
| `IsCanBeDiscarded` | **0장** |

이름만 그럴듯한 것을 구현했다면 아무 카드와도 이어지지 않았을 것이다.

### 실제로 쓰이는 이름

| 술어 | 카드 수 | 묻는 것 |
|---|---:|---|
| `Card.IsAbleToGrave` | 544 | A — 묘지로 보낼 수 있는가 |
| `Card.IsAbleToGraveAsCost` | 664 | **다른 질문** — 비용으로 보낼 수 있는가 |
| `Card.IsDiscardable` | 537 | B — 버릴 수 있는가 |
| `Card.IsCanBeEffectTarget` | 429 | C — 대상으로 지정할 수 있는가 |
| `Card.IsAbleToHand` / `IsAbleToRemove` / `IsAbleToDeck` | 2516 / 775 / 572 | 이번 범위 밖 (STRUCTURAL-48) |
| `Card.IsCanBeSpecialSummoned` | 4297 | 이미 관문이 있다 (Phase 2-U) |

### A 와 B 는 **다른 질문이다** — 관측된 증거

추론이 아니다.

| | 카드 수 |
|---|---:|
| `IsAbleToGrave` 만 쓴다 | 518 |
| `IsDiscardable` 만 쓴다 | 511 |
| 둘 다 쓴다 | 26 |

그리고 결정적으로, `c26400609.lua` 가 **한 줄에서 둘을 함께 묻는다**:

```lua
return c:IsAttribute(ATTRIBUTE_WATER) and c:IsDiscardable() and c:IsAbleToGraveAsCost()
```

같은 질문이라면 스크립트가 둘 다 쓸 이유가 없다.

### 네 질문을 합치지 않는다 (§2 A · B · C · D)

| | 질문 | Lua | 엔진 |
|---|---|---|---|
| A | 묘지로 보낼 수 있는가 | `Card.IsAbleToGrave` | `MovementRuling.may_be_sent_to_grave` |
| B | 버릴 수 있는가 | `Card.IsDiscardable` | `MovementRuling.may_be_discarded` |
| C | 대상으로 지정할 수 있는가 | `Card.IsCanBeEffectTarget` | **없다** — `UNASKED_QUESTIONS` 에 적어 둔다 |
| D | 그 이동을 수행할 수 있는가 | — | `EffectExecutor` 의 계획 단계 (이미 있다) |

`MovementRuling` 의 **메서드가 둘인 것**이 A/B 분리의 실체다.
`may_be_moved(kind, instance)` 하나로 합치지 않았다 — 합치면 구현하는
쪽이 "둘 다 같은 답" 을 내놓기 쉬워지고, `kind` 를 잘못 넘겨도 타입이
잡아 주지 못한다. `DeclaredMovementRuling` 이 **네 집합**인 것도 같은
이유다: "묘지로는 보낼 수 있지만 버릴 수 있는지는 모른다" 를 적을 수
있어야 한다.

C 는 **빈 칸으로 두지 않았다.** 빈 칸은 "없다" 로 읽히고, 적어 둔 것은
"아직" 으로 읽힌다.

---

## 3. 새 abstraction과 그 이유 (§1 · §18-4)

새로 만든 것은 **둘**이다. 나머지는 전부 기존 것을 썼다
(`OperationKind` · `CardOperation` · `OPERATION_HANDLERS` · `TargetSpec` ·
`CandidateResolver` · `TargetResolver` · `ValidationResult`/`Code` ·
`RULE_GATED`/`GATING_RULES`/`MISSING_GATE` · `StateDelta` ·
`AppliedOperation` · `EventReader` · `EventJournal` · `TimingEvent` ·
`EffectExecutor` · `ConditionResult`).

### (1) `MovementRuling` — 왜 기존 것으로 안 되는가

`DestructionRuling` · `SummonRuling` 과 **모양은 같지만 질문이 다르다.**
기존 둘 중 하나에 얹으면 "파괴해도 되는가" 와 "묘지로 보내도 되는가" 가
한 메서드를 공유하게 되고, ADR-002 가 값에서 지켜 온 구분이 판정
계층에서 무너진다. 이름이 다른 이유가 그것이고, 이것은 `SummonRuling` 이
`DestructionRuling` 과 따로 생긴 것(Phase 2-U)과 **같은 근거**다.

`ConditionResult` 를 그대로 쓰므로 새 삼치 논리는 만들지 않았다.

### (2) `CardOperation.gated` — 왜 `RULE_GATED` 로 안 되는가

**이번 Phase 의 핵심 설계 판단이다.**

파괴와 특수 소환의 관문은 *언제나* 적용된다 — 어떤 파괴든 내성에 막힐 수
있다. 그래서 그 둘은 **종류로** 막는다(`RULE_GATED`).

묘지로 보내기는 다르다. 실제 카드가 그렇게 말한다:

| 카드 | `Duel.SendtoGrave` | 후보 조건 |
|---|---|---|
| 육신보살 (15103313) | 부른다 | `nil` — **묻지 않는다** |
| 어리석은 매장 (81439173) | 부른다 | `c:IsMonster() and c:IsAbleToGrave()` — **묻는다** |

같은 일인데 한쪽은 묻고 한쪽은 묻지 않는다. `RULE_GATED` 에 종류를
넣었다면 육신보살과 벌금이 **실행을 멈췄을 것이다** — 즉 실제 카드
coverage 가 *줄었을* 것이다. 스크립트가 묻지 않는 것을 엔진이 물으면
그것도 추측이다.

그래서 관문 선언은 `gated` **한 칸**이고, 그 값은 원본 스크립트를 읽어서
정한다. 기본값은 거짓이다 — **적지 않은 것을 "관문이 있다" 로 읽지
않는다.**

---

## 4. SEND_TO_GRAVE 실제 카드 coverage 변화 (§18-5)

| | Phase 2-W | Phase 2-X |
|---|---|---|
| 해결까지 **실행되는** 실제 카드 | 1장 (육신보살) | **1장 (육신보살)** — 변화 없음 |
| 관문을 **선언하고 등록된** 실제 카드 | 0장 | **1장 (어리석은 매장)** |
| `IsAbleToGrave` 를 **표현할 수 있는가** | 아니오 | **예** |

어리석은 매장은 `EXECUTABLE` 이고 **발동 단계에서 멈춘다**:
`UNCHECKED_TARGET` / `HIDDEN_CARD`.

### 왜 여전히 실행되지 않는가 (§7-3)

**관문이 유일한 막이 아니었다.** 조사가 그것을 보여 준다.

`IsAbleToGrave` 를 선언하면서 이 엔진이 닿을 수 있는 카드(발동형 마법 /
함정 · 단일 효과 · 비용 없음 · 횟수 제한 없음 · 별도 조건 없음)는
**15장**이고, **그 15장이 전부 덱이나 엑스트라 덱에서 보낸다.**

```
544장 선언
 ├ 389장  발동형 마법/함정이 아니다 (몬스터 효과 · 유발)
 ├ 101장  효과가 여럿
 ├  22장  횟수 제한
 ├  11장  비용
 ├   6장  별도 발동 조건
 └  15장  남음  →  전부 LOCATION_DECK 또는 LOCATION_EXTRA
```

이 엔진의 관측 모델에서 덱은 `HIDDEN` 이다 — **주인조차 보지 못한다**
(룰북 `sd-rulebook-en-v10` 의 Deck visibility = `count_public`). "자신의
덱을 본다" 는 별도의 동작이고 그 계층이 없다 (**STRUCTURAL-69**).

그래서 순서상 대상 판정이 먼저 막는다. 순서 자체는 규칙이 맞다:
**대상이 적법한가 → 해도 되는가 → 어디로 가는가.** 관문을 앞으로 당기면
판정기가 상대 패의 카드를 아는 척하게 된다 (§9, 테스트로 고정).

그래도 이 항목을 실은 이유는 분명하다. Phase 2-W 에서는 이 카드를
**표현조차 할 수 없었고**, 이제는 표현되고 엔진이 **무엇이 막고 있는지
정확히 지목한다.**

---

## 5. DISCARD 실제 카드 coverage 변화 (§18-6)

| | Phase 2-W | Phase 2-X |
|---|---|---|
| 해결까지 **실행되는** 실제 카드 | 1장 (벌금) | **1장 (벌금)** — 변화 없음 |
| 관문을 선언하고 등록된 실제 카드 | 0장 | **0장** |
| `IsDiscardable` 을 표현할 수 있는가 | 아니오 | **예** |

**실제 카드를 붙이지 못했다. 그것이 사실이다.**

```
537장 선언
 ├ 370장  발동형 마법/함정이 아니다
 ├ 105장  효과가 여럿
 ├  57장  비용 (IsDiscardable 의 주된 용도다)
 ├   4장  횟수 제한
 ├   1장  별도 발동 조건
 └   0장  남음
```

이 엔진이 닿는 발동형 마법 / 함정 중 `IsDiscardable` 을 선언하는 카드가
**하나도 없다.** 없는 것을 있는 척 만들지 않았다 — 억지로 하나를
고르려면 비용 계층이나 몬스터 유발 효과를 이번 범위로 끌어와야 하는데,
§15 가 금지한 것이다.

관문 기계장치는 A 와 완전히 대칭으로 갖춰져 있고 synthetic 으로 검증되어
있다. 실제 카드가 닿는 날 붙이면 된다.

---

## 6. 성공 경로 (§18-9)

관문을 선언한 이동이 판정을 **받으면** 지나간다 (synthetic).

```
CardOperation.send_to_grave(@primary, gated=True)
  → TargetResolver         대상이 적법한가            LEGAL
  → MovementRuling         묘지로 보내도 되는가        TRUE
  → GameState.move         HAND/MZONE → GRAVE
  → ZoneMoved(movement=SEND_TO_GRAVE)                 ← 의미가 살아 있다
  → EventReader → ObservedEvent → TimingPoint.CARD_MOVED
  → EventJournal 에 1건
```

`applied != ()` · `deltas != ()` · `state_hash` 변화 — 전부 확인한다.

**의미는 관문을 통과해도 그대로다** (§14). 목적지가 둘 다 묘지인데
`ZoneMoved.movement` 가 `SEND_TO_GRAVE` 와 `DISCARD` 로 갈리고,
`reason_names` 도 `("EFFECT",)` 와 `("DISCARD","EFFECT")` 로 갈린다.

---

## 7. 실패 행렬 (§18-10)

관문을 선언한 두 종류 각각에 대해 다섯 갈래. 전부 `applied == ()` ·
`deltas == ()` · **`state_hash` 불변 · 사건 0건 · journal 0건**.

| 갈래 | status | code |
|---|---|---|
| 판정기 없음 (UNKNOWN) | `UNCHECKED_RULES` | `RULE_NOT_IMPLEMENTED` |
| 판정이 거절 (FALSE) | `INVALID_TARGET` | `CANDIDATE_NOT_ELIGIBLE` |
| 가려진 대상 (상대 패) | `UNCHECKED_TARGET` | `HIDDEN_CARD` |
| 안 골랐다 | `INVALID_TARGET` | `TOO_FEW_SELECTED` |
| 없는 `InstanceId` | `UNCHECKED_TARGET` | `HIDDEN_CARD` |

§4 가 요구한 여섯 상태가 전부 구분된다.

| §4 의 상태 | 어디서 |
|---|---|
| 대상 후보가 존재하지 않음 | `TOO_FEW_SELECTED` |
| 대상이 숨겨져 있음 | `HIDDEN_CARD` |
| 대상이 관측 가능함 | 대상 판정 통과 |
| 이동이 허용되는지 **모름** | `UNCHECKED_RULES` + `MISSING_GATE` |
| 이동이 **허용됨** | `RESOLVED` |
| 이동이 **명백히 불가능함** | `CANDIDATE_NOT_ELIGIBLE` |

`can_send_to_grave: bool` 하나로 압축하지 않았다 — 마지막 두 줄이 같은
답이 되기 때문이다.

**부분 적용이 없다** (§12): 두 장 중 한 장만 판정을 받으면 **한 장도**
옮겨지지 않는다. 계획이 전부 끝난 뒤에야 적용이 시작되므로 새 rollback
을 만들지 않았다 (STRUCTURAL-49 그대로).

---

## 8. Hidden information (§9 · §18-11)

| 보는 것 | 확인 |
|---|---|
| 상대 패의 카드를 고른다 | `UNCHECKED_TARGET` / `HIDDEN_CARD` — **"없다" 가 아니다** |
| 거절 결과 `to_dict()` · `reason` | 상대 카드의 `card_id` 없음 |
| 어리석은 매장의 덱 카드 | 정체가 `reason` 에 새지 않는다 |
| 관문 순서 | 가려진 카드에 `TRUE` 를 돌려주는 판정기를 줘도 답은 `HIDDEN_CARD` |

마지막 줄이 중요하다. 관문을 대상 판정보다 **앞**에 두었다면 판정기가
상대 패의 카드를 아는 척하게 된다. 테스트가 그 순서를 고정한다.

테스트의 `viewer` 는 언제나 결정하는 자리(`MINE`)다.

---

## 9. Determinism (§10 · §18-12 · §18-13)

| 보는 것 | 확인 |
|---|---|
| 같은 판 · 같은 선택 · 같은 판정기 | `canonical_state()` 동일 |
| 같은 판 | `state_hash()` 동일 |
| **판정기가 없을 때도** 결정적 | `UNCHECKED_RULES` 결과가 두 판에서 같다 |
| 선언이 정규 표현에 남는다 | `gated` 가 `canonical_state()` 에 실린다 |
| AI 판단 없음 | AST — `semantics.py` 에 `choose`/`select`/`score`/`policy`/`best`/`prefer` 이름 없음 · `random` 없음 |

관문은 "가능한가" 만 답한다. "무엇을 고를 것인가" 는 들어오지 않았다
(§11).

---

## 10. Event Pipeline (§13 · §18-14)

새 EventBus 를 만들지 않았다. 관문을 통과한 이동이
`StateDelta → EventReader → ObservedEvent → TimingEvent → EventJournal`
을 **그대로** 지난다.

`SEND_TO_GRAVE` 와 `DISCARD` 가 같은 `TimingPoint.CARD_MOVED` 를 쓰지만
`ZoneMoved.movement` 가 의미를 들고 가고, `TriggerSpec.operations` 가
그것으로 거른다 — 정보가 사라지지 않는다 (Phase 2-W 의 DETAIL 그대로).

---

## 11. 기존 테스트 수정 / 삭제 (§17 · §18-15)

**삭제 0건. 수정 2건** — 둘 다 목록이 늘어나면 깨지도록 설계된 수
단언이고, 약화하지 않고 정확한 새 값으로 갱신했다.

| 테스트 | 이전 전제 | 왜 바뀌었는가 |
|---|---|---|
| `test_a_the_library_is_exactly_twelve_real_cards` → `..._thirteen_...` | 목록이 12장 | **그때의 사실**이었다. 어리석은 매장이 더해졌다. 집합 단언을 그대로 유지하고 한 장만 추가했다 |
| `test_a_eight_real_effect_refs_are_executable` → `..._nine_...` | `EXECUTABLE` 이 8장 | 같은 이유. 겸해서 docstring 에 "`EXECUTABLE` 은 실행 권위이지 해결 성공이 아니다" 를 적었다 — 싸이크론과 어리석은 매장이 둘 다 `EXECUTABLE` 이면서 멈추기 때문이다 |

**엔진 테스트는 한 건도 고치지 않았다.** `gated` 기본값이 거짓이라
기존 2,386개가 손대지 않은 채 통과한다 — 관문을 종류로 걸지 않은 설계
판단(§3)이 그대로 확인된 셈이다.

---

## 12. 새 TODO (§16 · §18-16)

- **STRUCTURAL-69 (신규 · 🟠)** — **자신의 덱을 보는 동작이 없다.**
  관측 모델에서 덱은 `HIDDEN` 이고 그것은 기본 가시성으로는 맞지만,
  "덱에서 조건에 맞는 카드를 고른다" 는 효과는 그 순간 덱을 본다.
  이 계층이 없어서 `IsAbleToGrave` 를 선언하는 **실제 카드 15장 전부**가
  관문에 닿기 전에 멈춘다. STRUCTURAL-65(대상 미지정 검색)와 이웃이지만
  같지 않다 — 저쪽은 "고를 것을 엔진이 찾는다", 이쪽은 "가려진 자리를
  본다" 다.
- **STRUCTURAL-70 (신규 · 🟠)** — `IsAbleToGraveAsCost` (664장) ·
  `IsAbleToRemoveAsCost` (581장) 등 **비용 전용 술어**가 별도 질문이다.
  `RuleQuestion` 에 넣지 않았다 — 비용 계층과 이어야 의미가 생기는데
  이번 범위가 아니다.
- **STRUCTURAL-48 (범위 축소)** — "보내기 · 버리기에 관문이 없다" 였는데,
  이제 **선언한 카드에는 있다.** 남은 것은 `BANISH` · `RELEASE` ·
  `RETURN_TO_HAND` · `RETURN_TO_DECK` 넷이다.
- **STRUCTURAL-68 (변동 없음)** — `IsAbleToHand` 2,516장 ·
  `IsAbleToRemove` 775장 · `IsAbleToDeck` 572장은 그대로 막혀 있다.
  이번 범위가 아니다.
- STRUCTURAL-10 · 41 · 47 · 49 · 50 · 51 ~ 67 — 변동 없음.

---

## 13. BLOCKER / STRUCTURAL / DETAIL / COSMETIC (§18-17)

| 등급 | 건수 | 내용 |
|---|---:|---|
| 🔴 BLOCKER | **0** | 이번 구현을 막는 것이 없었다. 기존 2,386개가 수정 없이 통과한다 |
| 🟠 STRUCTURAL | 2 신규 | 69(덱을 보는 동작) · 70(비용 전용 술어) |
| 🟡 DETAIL | 1 | `IsAbleToGrave` 의 **내용**(토큰 · 펜듈럼 · "묘지로 보낼 수 없다")은 저장소 어디에서도 근거를 찾지 못했다. 룰북은 토큰을 한 번 언급하는데 엑시즈 소재 이야기다. 그래서 `UnknownMovementRuling` 이 모든 카드에 `UNKNOWN` 이고, 그것이 **정직한 기본값**이다 |
| 🟢 COSMETIC | 0 | |

---

## 14. 테스트 (§18-7 · §18-8 · §18-18)

`tests/engine/test_rule_gate_grave_discard.py` — **47개**, 전부 통과.

| 묶음 | 수 | 종류 | 보는 것 |
|---|---:|---|---|
| A. 실제 Lua 조사 | 6 | **실제 파일** | 추측한 이름은 없다 · A≠B · 같은 일인데 한쪽만 묻는다 · 닿는 카드가 전부 덱을 쓴다 · DISCARD 는 0장 |
| B. 네 질문 분리 | 6 | synthetic | 네 값 · 메서드 둘 · 한쪽만 확인된 카드 · C 는 적어 둔다 · 파괴를 넓히지 않았다 |
| C. 선언 | 4 | synthetic | 선언이 없으면 관문도 없다 · 두 종류만 선언 가능 · 정규 표현에 남는다 |
| D. 세 값 | 9 | synthetic | UNKNOWN 정지 · FALSE≠UNKNOWN · TRUE 통과 · 미선언은 그냥 지나감 · A 허가가 B 를 답하지 않는다 |
| E. 의미 · 사건 | 4 | synthetic | `movement` 가 갈린다 · 기존 event 경로 |
| F. 실패 안전성 | 4 | synthetic | 다섯 갈래 판·사건·기록 불변 · 부분 적용 없음 |
| G. 숨은 정보 | 2 | synthetic | 모른다 ≠ 없다 · 관문은 대상 판정 **뒤** |
| H. 결정론 | 5 | synthetic | 같은 답 · UNKNOWN 도 결정적 · AI 없음 |
| I. **실제 카드** | 5 | **`@pytest.mark.real_card`** | 어리석은 매장이 관문을 선언한다 · 기존 두 장은 선언하지 않는다 · 덱을 지목하며 멈춘다 · 기존 두 장은 그대로 실행된다 · 기본 판정기는 아무것도 허가하지 않는다 |

**실제 카드 테스트 수**: 5 (이 파일) · 89 (`-m real_card` 전체)
**synthetic 테스트 수**: 42 (이 파일) · 2,344 (`-m "not real_card"` 전체)

A 묶음은 `real_card` 표식이 없지만 실제 `c*.lua` 를 읽는다 — 카드의
*의미*를 주장하지 않고 *파일에 무엇이 적혀 있는가*만 세기 때문이다.
그 구분을 흐리지 않기 위해 표식을 붙이지 않았다.

전체 회귀: **2433 passed, 4 skipped** (직전 2386 + 47).

```
pytest -m real_card         89 passed
pytest -m "not real_card"   2344 passed, 4 skipped
```
