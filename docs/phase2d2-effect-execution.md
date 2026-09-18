# Phase 2-D-2 — Effect Execution

기준 커밋: `4615f2f` (Phase 2-D-1 fix: Operation ↔ Target link)
Hotfix: `7feb37b` 이후 — mutation 경계 두 곳 (§7 · §8)

이 단계에서 엔진이 **처음으로 효과 때문에 판을 바꾼다.** 지금까지의 모든
계층은 읽거나 판정하기만 했다.

```
EffectDefinition  +  ResolutionContext  +  GameState
        ↓  EffectExecutor.execute()
GameState 변경  +  EffectResult(applied=…)
```

---

## 1. 효과가 판을 바꾸는 문은 하나다

`EffectExecutor.execute()` 밖에 없다. `Operation.execute(state)` 를 만들지
않았다 — 일은 **무엇을 한다는 의미**일 뿐이고, 그 의미를 상태 조작으로
옮기는 것은 실행기 하나의 책임이다.

흩어 놓으면 나중에 `StateDelta` · `EventJournal` 을 끼워 넣을 자리가 없다.
그때 모든 Operation 을 찾아다니며 고쳐야 한다.

`GameState.move` / `draw` / `change_life` 는 그대로 남아 있다. 그것은 **존
이동 primitive** 이고, 실행기는 그것을 부르는 유일한 효과 경로다. 테스트와
설정(초기 배치)은 여전히 primitive 를 직접 쓴다.

---

## 2. 먼저 다 따져보고, 그 다음에 바꾼다

실행은 두 단계다.

| 단계 | 하는 일 | 판을 |
|------|---------|------|
| 1. 계획 (`_plan`) | 문맥 · 권위 · 지원 여부 · 조건 · 대상을 전부 확인하고, 할 일을 **카드 단위까지** 확정 | 읽기만 |
| 2. 적용 (`_apply`) | 확정된 일을 순서대로 수행 | 바꾼다 |

계획이 실패하면 적용은 **시작도 하지 않는다.** 그래서 판이 반쯤 바뀌는 일이
없다.

이것이 우연이 아닌 이유: 지원하는 일들의 목적지(묘지 · 제외 · 패 · 덱)는
전부 칸 수 제한이 없는 `ORDERED` 존이다. 계획을 통과한 이동이 적용 중에
`ZoneFull` 로 거부될 여지가 구조적으로 없다. 칸이 있는 존(MZONE · EMZONE ·
SZONE)으로 **보내는** 일 — 소환 · 세트 · 특수 소환 — 은 아직 지원하지
않으므로, 그것이 들어올 때 이 보장을 다시 세워야 한다.

`ResolutionStatus.EXECUTION_ERROR` 는 그럼에도 예상 못 한 오류가 났을 때다.
**이때만 판이 반쯤 바뀌어 있을 수 있다.** 일어나서는 안 되는 경우이고,
일어났다면 결함이다. 원자적 되돌리기는 `StateDelta` 가 들어오는 Phase 2-E
의 몫이다 (ADR-008).

---

## 3. 지원하는 일과, 지원하지 않는 일

### 지원 (8종)

| Operation | 목적지 | `reason_names` |
|-----------|--------|----------------|
| `SEND_TO_GRAVE` | `GRAVE` | `("EFFECT",)` |
| `RELEASE` | `GRAVE` | `("RELEASE",)` |
| `DISCARD` | `GRAVE` | `("DISCARD", "EFFECT")` |
| `BANISH` | `REMOVED` | `("EFFECT",)` |
| `RETURN_TO_HAND` | `HAND` | `("RETURN", "EFFECT")` |
| `RETURN_TO_DECK` | `DECK` | `("RETURN", "EFFECT")` |
| `DRAW` | — | `("DRAW", "EFFECT")` |
| `CHANGE_LIFE` | — | `("EFFECT",)` |

앞의 세 줄은 **전부 묘지로 간다.** 목적지로는 구분할 수 없다. 구분은
`AppliedOperation.kind` 와 `reason_names` 가 지킨다 (ADR-002). 트리거
계층이 생기면 "파괴되었을 때" 와 "묘지로 보내졌을 때" 를 이 기록으로
가른다.

### 지원하지 않음

**`DESTROY` 는 실행하지 않는다.** `UNSUPPORTED_OPERATION` 을 돌려주고
`missing` 에 무엇이 없는지 적는다.

> `destruction semantics — 파괴 내성 · 파괴 대체 · 파괴 트리거 (Phase 2-E~)`

목적지가 묘지라는 이유로 "묘지로 옮겼으니 구현했다" 고 말하면 세 가지가
조용히 틀린다.

1. 파괴 내성을 가진 몬스터가 파괴된다.
2. 파괴 대체 효과("파괴되는 대신 …")가 발동할 기회를 잃는다.
3. "파괴되었을 때" 트리거가 발동하지 않는데 판은 바뀌어 있다.

셋 다 **조용히** 틀린다. 그래서 하지 않는 쪽을 골랐다.

`UnimplementedOperation` (소환 · 표시 형식 변경 · 수치 변경 · 무효화 …)도
같다. 추측해서 실행하지 않는다.

---

## 4. 실행 권위 — 순서가 의미다

`_check_authority` 가 `execution_availability()` 를 그대로 쓴다. 순서가
중요하다.

```
1. FORBIDDEN_SOURCE   출처 금지가 가장 먼저      → FORBIDDEN
2. UNVERIFIED         의미가 확인되지 않았다      → UNKNOWN
3. NO_IMPLEMENTATION  구현이 등록되어 있지 않다  → NOT_IMPLEMENTED
4. EXECUTABLE         ← 이때만 통과
```

- **`TEXT_DERIVED` 는 구현을 등록해도 실행되지 않는다** (ADR-004). 출처
  검사가 조회보다 먼저다.
- **`LUA_VERIFIED` 라고 자동으로 실행되지 않는다** (ADR-006). 등록된 구현이
  있어야 한다.

`EffectImplementationRegistry` 는 그 등록을 담는 최소 구조다. **등록은 손으로
한다.** 카드 데이터가 `lua_verified` 라는 것만으로 자동 등록되지 않는다 —
그것이 "검증된 의미" 와 "실행 가능" 을 나누는 지점이다.

등록 단위는 `EffectRef(card_id, ordinal)` 이다. 카드 단위가 아니다. 한 카드의
0번 효과를 등록해도 1번 효과는 실행되지 않는다.

`analysis` → `EffectDefinition` 컴파일러는 **여전히 없다.** 만들 때
`TEXT_DERIVED` 차단을 다시 확인해야 한다.

---

## 5. 조건 — `UNKNOWN` 은 `TRUE` 가 아니고 `FALSE` 도 아니다

`activation` 이 있으면 `GameStateView` 로 평가한다. **`TRUE` 일 때만
통과**한다.

| 결과 | 상태 | 판 |
|------|------|----|
| `TRUE` | (통과) | 바뀐다 |
| `FALSE` | `CONDITION_FALSE` | 그대로 |
| `UNKNOWN` | `CONDITION_UNKNOWN` | 그대로 |

두 실패를 **하나로 합치지 않는다.** "안 된다" 와 "모르겠다" 는 다른 답이고,
모르는 것을 거짓으로 접으면 프로젝트 전체의 원칙이 깨진다.
`CONDITION_UNKNOWN` 은 `ValidationCode.INFORMATION_UNAVAILABLE` 을 달고,
`missing` 에 조건 계층의 `unknown_reasons` 를 그대로 옮긴다.

조건 평가는 **관측**으로 한다 (`GameStateView.from_state(state,
viewer=controller)`). 관측을 통해 판을 고치지 않는다. 그래서 가려진 정보를
조건이 물으면 `UNKNOWN` 이 되고, 효과는 실행되지 않는다.

가려진 것과 알려진 것을 섞지 않는다는 점은 그대로다. 상대 세트 카드의
**표시 형식**은 공개 정보라 `CardIsFaceUp` 은 `FALSE` 를 답하지만, 그 카드가
**무엇인가**는 보이지 않으므로 `IsMonster` 는 `UNKNOWN` 이다.

---

## 6. 대상 — 이름으로 잇고, 카드는 문맥에서 온다

```
EffectDefinition.targets      @primary → "몬스터 1장을 대상으로"
CardOperation.banish(@primary)          "그것을 제외한다"
ResolutionContext.selections  @primary → #7
```

계획 단계가 이름을 실제 카드로 푼다. 다음 중 하나라도 걸리면 **아무 일도
일어나지 않는다.**

| 상황 | 상태 | 코드 |
|------|------|------|
| 아직 고르지 않음 | `INVALID_TARGET` | `TOO_FEW_SELECTED` |
| 고른 결과가 비어 있음 | `INVALID_TARGET` | `TOO_FEW_SELECTED` |
| 고른 카드가 이 듀얼에 없음 | `INVALID_TARGET` | `CANDIDATE_NOT_FOUND` |
| 버리기인데 패에 없음 | `INVALID_TARGET` | `SOURCE_WRONG_ZONE` |
| 문맥이 다른 효과를 가리킴 | `INVALID_CONTEXT` | `EFFECT_REF_CARD_MISMATCH` |

여러 장 중 **한 장이라도** 잘못되면 한 장도 옮기지 않는다.

버리기의 존 검사가 따로 있는 이유: 버리기는 패에서만 일어난다. 필드의
카드를 "버렸다" 고 기록하면 트리거 계층이 틀린 사건을 보게 된다.

---

## 7. 주인 ≠ 컨트롤러 — 일마다 적어 둔다

`GameState.move` 의 `to_player` 기본값은 **컨트롤러**다.

```python
owner = to_player if to_player is not None else card.controller
```

컨트롤을 빼앗긴 카드를 그대로 옮기면 **빼앗은 쪽의 묘지로 간다.** 규칙상
카드는 언제나 **주인의** 존으로 돌아간다.

그래서 실행기는 기본값을 쓰지 않는다. 그리고 `card.owner` 를 한 줄로 쓰지도
않는다 — **일마다 표에 적는다.**

```python
DESTINATION_OWNER = {
    OperationKind.DESTROY:        DestinationOwner.OWNER,
    OperationKind.SEND_TO_GRAVE:  DestinationOwner.OWNER,
    OperationKind.RELEASE:        DestinationOwner.OWNER,
    OperationKind.DISCARD:        DestinationOwner.OWNER,
    OperationKind.BANISH:         DestinationOwner.OWNER,
    OperationKind.RETURN_TO_HAND: DestinationOwner.OWNER,
    OperationKind.RETURN_TO_DECK: DestinationOwner.OWNER,
}
```

지금은 전부 `OWNER` 인데, 그것은 우연이 아니라 **지원하는 일들이 모두
소유권 기반 존으로 보내기 때문**이다. 소환 · 세트처럼 *필드로* 보내는 일이
들어오면 그것은 `CONTROLLER` 이고, 그때 이 표에 줄이 늘어난다. 한 줄로
`card.owner` 를 쓰고 있으면 그 날 조용히 틀린다.

`DESTROY` 도 적어 두었다. 파괴된 카드가 주인의 묘지로 간다는 것은 이미
정해진 사실이고, 실행하지 않는 이유는 목적지가 아니라 **파괴 의미**(내성 ·
대체 · 트리거)가 없기 때문이다 (§3).

주인 결정은 **계획 단계**에서 끝난다. `_Step.owners` 가 `instances` 와 짝을
이루어 카드마다 목적지의 주인을 들고 있고, 적용 단계는 그것을 그대로 넘긴다.
한 번의 해결에서 양쪽 카드를 옮길 때 첫 장의 주인으로 전부 보내는 실수가
구조적으로 불가능하다.

옮긴 뒤에는 카드가 실제로 그 존, 그 플레이어 쪽에 있는지 확인한다. 아니면
`EffectExecutionError` 이고 `EXECUTION_ERROR` 로 올라간다 — 존과 인스턴스가
서로 다른 말을 하는 상태로 계속 가지 않는다.

**소유권 자체는 바뀌지 않는다.** 실행기는 `owner` 를 쓰지 않고 읽기만 한다.
`controller` 는 기존 규칙 그대로 `ZoneContainer._sync_from` 이 존의 주인으로
맞춘다.

---

## 8. 덱이 모자란 드로우

`GameState.draw` 자체는 있는 만큼만 옮기고 멈춘다 (Phase 1 의 primitive 는
규칙을 모른다). 그것을 그대로 쓰면 "3장 드로우" 가 1장 드로우로 조용히
줄어들고, 결과는 성공처럼 보인다. **부분 적용 후 성공**이 가장 나쁜 실패다.

그래서 `DRAW` 는 계획 단계에서 세 가지를 순서대로 본다.

| 검사 | 결과 | 코드 |
|------|------|------|
| `count <= 0` | `INVALID_OPERATION` | `INVALID_AMOUNT` |
| `len(deck) < count` | `INSUFFICIENT_CARDS` | `INSUFFICIENT_DECK` |
| 통과 | (적용) | |

`INSUFFICIENT_CARDS` 를 `UNSUPPORTED_OPERATION` 과 합치지 않는다. 실행기는
드로우를 할 줄 알고, 다만 **지금 덱이 모자랄 뿐**이다. 둘은 다른 사실이다.
모자랄 때 무슨 일이 일어나는가(덱 데스)가 없어서 거절한다는 것은
`missing="deck-out rule (Phase 2-G)"` 에 그대로 남는다.

`count <= 0` 은 `DrawOperation.__post_init__` 이 **생성 시점에** 막는 것이
1차 방어다. 실행기의 검사는 그 방어를 우회해서 들어온 값을 위한 것이고,
`INVALID_OPERATION` 은 "이 실행기가 못 한다"(`UNSUPPORTED_OPERATION`)와
달리 **그 일이 애초에 말이 되지 않는다**는 뜻이다.

---

## 9. 실패하면 한 글자도 바뀌지 않는다

§25 가 요구한 보장이다. 다섯 가지 실패 전부에서 `state_hash()` 가 **동일**해야
한다.

- forbidden source
- invalid target
- unsupported operation
- condition false
- condition unknown

`test_every_refusal_leaves_the_board_byte_identical` 이 다섯을 한 판에서
차례로 시도하며 매번 해시를 비교한다. 각 정의에는 **뒤에 드로우가 붙어
있다** — 앞의 일이 걸렸을 때 뒤의 일이 새어 나가지 않는지 보기 위해서다.

`test_a_later_failure_does_not_apply_the_earlier_operations` 는 반대 방향을
본다: 첫 일이 멀쩡해도 뒤의 일이 계획에서 걸리면 첫 일도 일어나지 않는다.

---

## 10. `AppliedOperation` 은 `StateDelta` 가 아니다

성공한 실행은 무슨 일이 있었는지를 `EffectResult.applied` 에 남긴다.

```python
AppliedOperation(
    kind=OperationKind.SEND_TO_GRAVE,
    reason_names=("EFFECT",),
    instances=(InstanceId(20),),
    amount=None,
    player=None,
)
```

**되돌리는 데 쓸 수 없다.** 어디서 왔는지, 어떤 위치였는지를 담지 않는다.
되돌리기는 ADR-008 이 Phase 2-E 로 미뤄 두었고, 여기서 반쯤 만들면 그때
두 모델을 합쳐야 한다.

`DRAW` 만은 적용 단계에서 기록을 다시 만든다 — 어떤 카드가 뽑혔는지는
뽑아 봐야 알기 때문이다. 나머지는 계획 단계의 기록을 그대로 쓴다.

---

## 11. 이번 단계에서 **만들지 않은** 것

요청의 §30 그대로다.

- **Chain / Trigger / Timing** — 자리도 만들지 않았다. 그 시스템이 없는데
  칸을 비워 두면 모양을 미리 못박게 된다.
- **StateDelta / 되돌리기** — ADR-008, Phase 2-E.
- **CostPayment** — 비용은 `CostGroup` 으로 표현되어 있지만 실행기는
  **치르지 않는다.** `ResolutionContext.cost_selections` 를 읽지도 않는다.
  비용을 치르는 것은 발동 시점의 일이고, 그 시점 계층이 아직 없다.
- **ActionExecutor** — `PlayerAction` 을 실행하는 계층. 효과 실행과 다른
  경로다 (ADR-001).
- **`analysis` → `EffectDefinition` 컴파일러** — §4 참고.
- **소환 · 표시 형식 변경 · 무효화 · 수치 변경** — `UnimplementedOperation`
  으로 정직하게 남아 있다.
- **덱 데스 · 라이프 0 판정** — `change_life` 는 라이프를 바꾸기만 하고
  패배를 판정하지 않는다.

---

## 12. 테스트

`tests/engine/test_effect_execution.py` — 48개.

| 묶음 | 보는 것 |
|------|---------|
| Executor contract | 기본 실행기는 아무것도 실행하지 않는다 · 성공 · 실패 · unsupported · 관측 거부 · `bool()` 거부 |
| Mutation | 8종 전부 + 덱 부족 드로우 + 여러 일의 순서 |
| Target | 이름별 연결 · 미선택 · 빈 선택 · 없는 카드 · 잘못된 존 · 한 장이라도 틀리면 전부 취소 |
| Authority | `TEXT_DERIVED` 금지 · 등록 없음 · 미검증 · 형제 효과 분리 |
| Condition | TRUE / FALSE / UNKNOWN · 가려진 정보 · 표시 형식은 공개 정보 |
| Integrity | InstanceId 보존 · **주인의 묘지** · 존 유일성 · 장수 보존 · 칸 있는 존 |
| Determinism | 같은 입력 → 같은 결과 · 같은 해시 · 직렬화 |
| Failure atomicity | 다섯 가지 실패에서 해시 동일 · 뒤의 실패가 앞의 일을 취소 |

`tests/engine/test_effect_mutation_safety.py` — 28개 (Hotfix).

| 묶음 | 보는 것 |
|------|---------|
| Owner / controller | 표가 일마다 적혀 있는가 · 빼앗은 카드의 5개 목적지 · 버리기 · 소유권 불변 · 컨트롤러 정책 불변 · 내 카드 · 한 해결에서 양쪽 카드 · **기본값을 쓰면 틀린다는 것 자체** · 가려진 존으로 사라짐 |
| Draw | 덱에 맞는 드로우 · 부족 → 명시적 실패 · 해시/패/덱 동일 · 빈 덱 · 상대 덱을 센다 · `count<=0` 생성 거부 · 실행 거부 |
| 순서 | 뒤의 드로우가 걸리면 앞의 제외도 없다 · 뒤의 대상이 틀리면 앞의 드로우도 없다 · operation identity 유지 |

전체 회귀: **1116 passed, 4 skipped** (Phase 2-D-2 기준 1088 + 28).

Hotfix 에서 기존 테스트 2개의 단언을 **더 정확한 쪽으로** 바꿨다 (드로우
부족이 `UNSUPPORTED_OPERATION` → `INSUFFICIENT_CARDS`). 약화가 아니라
강화이고, 그 외 기존 테스트는 하나도 삭제·수정하지 않았다.
