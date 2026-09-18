# Phase 2-G — ActionExecutor

기준 커밋: `a2d4095` (Phase 2-F-4)

```
PlayerAction
    ↓  ActionExecutor.authorize(state, action)      → ActionValidator 에게 물어본다
ValidationResult
    ↓  permits_execution 이 참일 때만                 (VALID 만 통과 · UNKNOWN 은 허가가 아니다)
ActionHandler                                        손으로 등록된 것만 (ADR-006)
    ↓  handler.apply(state, action)                  GameState 공개 API 로만 변경
tuple[StateDelta, ...]
    ↓
ActionExecution         무엇이 실행되었고, 무엇이 왜 실행되지 않았는가
```

---

## 1. 작업 전 검수 — §16 의 일곱 질문

구현 전에 기존 코드를 먼저 읽고 답한 것이다. 답이 설계를 바꿨다.

### Q1. 현재 `PlayerAction` 모델이 실제 execution 에 충분한가

**행위의 지목에는 충분하고, 실행에는 부족하다.**

`PlayerAction` 은 `kind` · `actor` · `source` · `targets` · `effect_ref` ·
`phase` 를 갖는다. "누가 무엇을 하려는가" 는 이것으로 완전히 표현된다.
그러나 실행에 필요한 나머지가 없다:

| 없는 것 | 누가 갖고 있나 |
|---|---|
| 제물로 바칠 카드의 선택 | 아직 아무도 — 소환 절차 계층이 만들 것 |
| 놓을 칸 (`MZONE` 몇 번) | 없음 — `GameState.move(index=...)` 는 받지만 고르는 주체가 없다 |
| 비용 영수증 | `CostPaymentResult` (Phase 2-E) |
| 체인 위치 | `ChainLink` (Phase 2-F-2) |

그래서 `PlayerAction` 에 칸을 **더 만들지 않았다.** 없는 정보를 담을 자리를
만들면 그 자리를 비워 둔 채로 실행하게 된다. 부족한 것은 부족한 채로 두고,
그것을 요구하는 Action 은 애초에 실행되지 않는다 (Q4 · §4).

### Q2. `ActionExecutor` 가 `GameState` 를 직접 mutation 하는 것이 적절한가

**아니다.** `ActionExecutor` 자신은 `GameState` 를 한 글자도 바꾸지 않는다.
`execute()` 안에 `state.` 로 시작하는 변경 호출이 하나도 없다 —
`isinstance` 확인과 `authorize()` 로 넘기는 것이 전부다.

이유는 Q6 과 같다. 여기서 직접 바꾸기 시작하면 소환 · 전투 · 효과 해결의
절차가 전부 이 파일 안에서 `if kind is ...` 로 자라난다.

### Q3. 그렇다면 기존 `Zone` / `PlayerState` / `GameState` API 를 통해야 하는가

**그렇다. 그리고 그것이 `ActionHandler` 의 유일한 통로다.**

`ActionHandler` 는 `apply(state, action) -> tuple[StateDelta, ...]` 하나뿐인
프로토콜이다. 핸들러는 `GameState.move()` · `GameState.draw()` ·
`PlayerState` 의 공개 API 로만 판을 바꾼다. `ZoneContainer` 의 내부 리스트를
직접 건드리거나 `object.__setattr__` 로 불변을 뚫는 길은 열어 두지 않았다.

`Zone` · `PlayerState` · `GameState` 를 **고치지 않았다.** 새 mutation API 를
만들지 않았고, 기존 API 의 뜻을 바꾸지도 않았다.

### Q4. `StateDelta` / `EventJournal` 과 잇는 최소 boundary 는 무엇인가

**핸들러의 반환값 `tuple[StateDelta, ...]` 하나다.**

`ActionExecutor` 는 Delta 를 **만들지 않는다.** 판을 바꾼 쪽이 무엇을 바꿨는지
말하게 하고, 그것을 그대로 `ActionExecution.deltas` 에 담아 돌려준다.

`EventJournal` 은 **잇지 않았다.** Action 이 어떤 `EventKind` 로 기록되어야
하는지가 아직 정해지지 않았기 때문이다 (`EffectEvent` · `CostPaymentEvent` 는
있지만 `ActionEvent` 는 없다). 없는 어휘를 지어내는 대신, Delta 만 밖으로
내보내고 기록은 부르는 쪽이 하게 두었다. Journal 을 쓰기로 정해지면
`ActionExecution.deltas` 가 그대로 입력이 된다.

불변식으로 못 박았다: **실행되지 않은 결과는 Delta 를 가질 수 없다.**
`ActionExecution.__post_init__` 이 `EXECUTED` 가 아닌데 `deltas` 가 있으면
거부한다.

### Q5. 기존 Validation 모델을 재사용할 수 있는가

**그대로 재사용했다. 새 판정 타입도, 새 `ValidationCode` 도 만들지 않았다.**

`ActionExecutor.authorize()` 는 `ActionValidator(view, definitions).validate()`
를 부르는 것이 전부다. 관측자는 `action.actor` 로 고정된다 — 행위자가 볼 수
없는 정보로 얻은 허가는 허가가 아니다.

여기서 이번 단계의 결론이 나왔다:

> **`ActionValidator.validate()` 에는 `VALID` 반환 경로가 없다.**
> 모듈 전체에서 `ValidationResult.valid(` 는 한 번 나오고, 그것은
> `validate_structure()` — "Action 이 구조적으로 말이 되는가" 다.
> 10개 `PlayerActionKind` 전부를 실제로 돌려 확인했다: 전부 `UNKNOWN`,
> `permits_execution=False`.

그래서 **오늘 `ActionExecutor` 가 실행할 수 있는 Action 은 하나도 없다.**
이것은 결함이 아니라 정직한 상태다. 소환 절차 · 타이밍 · 체인 규칙이 없어서
마지막 한 걸음을 확인할 수 없고, 확인할 수 없는 것은 허가가 아니다.
`UNKNOWN` 을 실행 허가로 바꾸는 순간 "모르는 것을 참으로 접지 않는다" 가
무너진다.

규칙 계층이 생겨 `validate()` 가 `VALID` 를 내주기 시작하면,
**`action_execution.py` 를 고치지 않고도** 그 Action 이 실행된다.

### Q6. 앞으로 SummonExecutor / BattleExecutor / EffectExecutor 를 붙일 때 비대해지지 않는가

**핸들러 등록 구조라서 커지지 않는다.**

`ActionExecutor` 는 `PlayerActionKind → ActionHandler` 사전 하나를 갖고,
`register(kind, handler)` 로만 늘어난다. 같은 종류를 두 번 등록하면 거부한다.
기본값은 **빈 사전**이다 — `EffectRegistry` 가 손으로 등록된 구현만 실행하는
것과 같은 원칙(ADR-006)이다.

`SummonExecutor` 가 생기면 `executor.register(NORMAL_SUMMON, summon_handler)`
한 줄이고, `action_execution.py` 는 바뀌지 않는다. `execute()` 안에
`if kind is NORMAL_SUMMON: ...` 같은 분기는 **하나도 없다.**

### Q7. 현재 구조에서 실행 책임이 중복되는 클래스가 있는가

**없다. 확인한 결과 네 층이 서로 다른 것을 실행한다.**

| 클래스 | 무엇을 실행하나 | 입력 |
|---|---|---|
| `EffectExecutor` (2-D-2) | 효과 해결 한 건 | `EffectSpec` |
| `CostPayer` (2-E) | 비용 지불 | `CostSpec` |
| `ChainResolver` (2-F-2) | 체인 링크를 역순으로 해결 | `Chain` |
| `ActionExecutor` (2-G) | 플레이어가 고른 행위 | `PlayerAction` |

`ActionExecutor` 는 앞의 셋을 **부르지 않는다.** import 도 하지 않는다 —
테스트가 AST 로 감시한다. 부르게 되는 것은 핸들러 쪽이고, 그 핸들러는 아직
없다. 중복은 핸들러를 만들 때 생길 수 있으므로, 그때 "누가 Delta 의 주인인가"
를 다시 본다.

---

## 2. 책임 분리

| | 답하는 질문 |
|---|---|
| `ActionValidator` | 이 행위가 **적법한가** |
| `ActionExecutor` | 적법하다고 **판정되었는가**, 그리고 **할 줄 아는가** |
| `ActionHandler` | 실제로 판을 **어떻게 바꾸는가** |
| `StateDelta` | 무엇이 **바뀌었는가** |

`ActionExecutor` 는 **판정하지 않는다.** 판정 결과를 확인만 한다. 그래서
`authorization` 을 인자로 받을 수 있다 — 이미 우선권 계층이 판정한 결과가
있으면 다시 묻지 않는다. 다만 무엇을 받든 `permits_execution` 을 통과해야
한다.

---

## 3. 다섯 가지 결과

`ActionStatus` 는 "왜 실행되지 않았는가" 를 뭉개지 않는다.

| 상태 | 뜻 | Delta |
|---|---|---|
| `EXECUTED` | 실행되었다 | 있을 수 있다 |
| `INVALID_ACTION` | 규칙이 **안 된다고** 말했다 | 없다 |
| `UNKNOWN_ACTION` | 규칙이 **모른다고** 말했다 | 없다 |
| `UNSUPPORTED_ACTION` | 허가는 났지만 **할 줄 모른다** | 없다 |
| `EXECUTION_ERROR` | 핸들러가 중간에 터졌다 | **없다** |

`INVALID` 와 `UNKNOWN` 을 한 칸에 넣지 않은 이유는 프로젝트 전체와 같다 —
"안 된다" 와 "모른다" 는 다른 사실이고, 규칙 계층이 자라면 `UNKNOWN` 만
움직인다.

`UNSUPPORTED_ACTION` 은 `missing` 에 **무엇이 없어서인지**를 적는다. 예:
`PASS` 는 "우선권 계층의 일 — 패스는 `GameState` 가 아니라 `PriorityState` 를
움직인다".

---

## 4. Mutation Safety

- `ActionExecutor` 자신은 `GameState` 를 바꾸지 않는다.
- 허가가 나지 않으면 핸들러를 **부르지도 않는다.** 판에 손이 닿을 일이
  없으므로 부분 변경이 생길 수 없다.
- 등록된 핸들러가 없으면 역시 부르지 않는다.
- 핸들러가 예외를 던지면 `EXECUTION_ERROR` 이고 **Delta 를 돌려주지 않는다.**
  다만 그 핸들러가 터지기 전에 이미 바꾼 것은 되돌리지 않는다 — rollback 은
  ADR-008 대로 아직 없다. 그래서 문서에 적어 둔다: **핸들러는
  plan-then-apply 로 써야 한다** (`EffectExecutor` · `CostPayer` 와 같은
  규율).
- `ActionExecution` 은 frozen · slots 이고 `__bool__` 은 예외를 던진다.
  `if execution:` 으로 성공 여부를 짐작할 수 없다.

---

## 5. Determinism

`ActionExecutor` 는 상태를 갖지 않는다 — 핸들러 사전 하나뿐이고 실행 중에
바뀌지 않는다. 난수도, 시간도, 딕셔너리 순회 순서에 의존하는 결정도 없다.
허가가 나지 않는 오늘, `execute()` 를 몇 번 부르든 `state_hash()` 는 그대로다
(테스트가 확인한다).

---

## 6. 이번 단계에서 만들지 않은 것

§14 가 금지한 것 전부를 만들지 않았다. 특히:

- 완전한 일반 소환 · 특수 소환 · 제물 · 전투 · 데미지 · 턴 진행
- 실제 카드 효과의 전체 실행
- Condition / Cost 엔진 확장 — **한 줄도 고치지 않았다**
- SEGOC · Spell Speed · WHEN/IF 구분
- AI · 탐색 · 덱 빌딩

그리고 스스로 더 하지 않은 것:

- `PlayerAction` 에 실행용 칸을 더하지 않았다 (Q1)
- `EventJournal` 에 Action 용 `EventKind` 를 만들지 않았다 (Q4)
- 기본 핸들러를 **하나도** 등록하지 않았다 — 허가가 나지 않는 행위에 대한
  핸들러는 시험할 수 없는 코드다

---

## 7. 앞으로 만들면 좋은 것

이번 단계에서 **고쳐야 하는 것이 아니라**, 규칙 계층이 생길 때 할 일이다.

1. `ActionValidator.validate()` 가 `VALID` 를 낼 수 있게 되는 것 — 소환 절차 ·
   칸 · 1턴 1회 규칙. 그전까지 `ActionExecutor` 는 빈 채로 옳다.
2. Action 의 `EventJournal` 기록 어휘 (`ActionEvent`).
3. 핸들러 실패 시의 rollback — `StateDelta` 역적용 (ADR-008).
4. 제물 · 칸 선택을 담는 자리. `PlayerAction` 을 늘릴지, 별도의
   `ActionPlan` 을 둘지는 소환 절차를 만들 때 정한다.
