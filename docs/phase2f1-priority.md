# Phase 2-F-1 — Priority / Response Window 최소 구조

기준 커밋: `3a51cd8` (Phase 2-E)

이 단계가 답하는 질문은 **하나뿐**이다.

> 지금 누가 다음 선택을 할 차례인가?

그 사람이 **무엇을** 할 수 있는지는 답하지 않는다.

---

## 1. 작업 전 검수 결과

| 읽은 것 | 확인한 사실 |
|---|---|
| `engine/state/turn.py` | `TurnState(turn_number, turn_player, phase, step)` — **가변**이고 우선권 개념 없음. 문서에 "우선권이 누구에게 있는가는 Phase 4" 라고 적혀 있다 |
| `engine/condition/context.py` | `PlayerRef` 는 **문맥 상대적**(CONTROLLER/OPPONENT). 절대 자리가 아니다 |
| `engine/action.py` | `PlayerActionKind.PASS` 가 **이미 있다**. `PlayerAction.actor` 는 절대 자리(0/1) |
| `engine/action_validation.py` | `ActionValidator(view)` — 관측만 읽는다. 우선권을 검사하지 않는다 |
| `engine/game_state_view.py` | `viewer` · `turn_player` · `phase` · `turn_number` 를 이미 노출한다 |
| `engine/validation.py` | `ActionValidity` VALID/INVALID/**UNKNOWN** · `ValidationCode` · `ValidationResult` |
| `engine/effect/journal.py` | `EventJournal` 이 `GameState` 밖에 사는 선례 |

**우선권 · 응답 기회 구조는 없었다.** 새로 만들었고, 기존 구조는 하나도
대체하지 않았다.

---

## 2. 네 가지를 따로 둔다

```
turn_player   누구의 턴인가          TurnState
phase         어느 페이즈인가        TurnState
holder        누구의 차례인가        PriorityState   ← 새로
window        어떤 종류의 기회인가   PriorityState   ← 새로
```

**`holder == turn_player` 를 어디에서도 강제하지 않는다.** 상대의 응답
기회가 바로 그 반례이고, 테스트가 그것을 고정한다.

옛 OCG 의 "선공 우선권" 재정을 구현하는 것이 아니다. 여기서 우선권은 엔진
내부의 추상화 — 게임 흐름에서 다음 합법적 선택의 기회를 누가 쥐고 있는가 —
일 뿐이다.

---

## 3. `PriorityHolder` — 절대 자리

```python
PriorityHolder.PLAYER_0 | PLAYER_1 | NOBODY
```

`PlayerRef` 를 쓰지 않았다. `PlayerRef` 는 **문맥 상대적**("자신"/"상대")인데
우선권에는 기준이 될 문맥이 없다 — 누구의 관점도 아니고 그냥 0번이거나
1번이다. `PlayerRef.CONTROLLER` 를 우선권 보유자로 쓰면 "무엇의
컨트롤러인가" 라는 답 없는 질문이 생긴다.

`int | None` 도 쓰지 않았다. **`NOBODY` 는 "0번의 차례다" 와 다른 사실**이고,
`None` 으로 두면 "아무도" 인지 "아직 안 정했다" 인지 구분되지 않는다.

`NOBODY.opponent` 는 여전히 `NOBODY` 다 — 아무도 아닌 것의 상대는 없다.

---

## 4. `ResponseWindow` — 어떤 종류의 기회인가

| | |
|---|---|
| `NONE` | 열린 기회가 없다. 아무도 결정할 차례가 아니다 |
| `ACTION` | 턴 플레이어가 자기 턴의 행동을 고르는 기회 |
| `RESPONSE` | 방금 일어난 일에 응답하는 기회 |
| `PHASE_CHANGE` | 페이즈를 넘기기 전의 기회 |

`allows_decision` 은 `NONE` 에서만 거짓이다.

**발동 합법성도 스펠 스피드도 여기 없다.** 이 열거형은 "어떤 종류의 결정
기회인가" 라는 **문맥**일 뿐이다.

---

## 5. `PriorityState` — 불변

```python
PriorityState(holder, window, consecutive_passes, turn_player, phase, reason)
```

`GameState` 를 담지 않는다. `GameState` 안에 **살지도 않는다** — 우선권은
판의 *모양*이 아니라 흐름의 위치이고, `state_hash()` 에 섞으면 "같은 판" 의
뜻이 달라진다 (`EventJournal` 을 밖에 둔 것과 같은 이유).

생성 시점에 두 가지 모순을 거부한다.

- 기회가 없는데 쥔 사람이 있다
- 기회는 열렸는데 차례인 사람이 없다

`turn_player` / `phase` 는 **복사본**이라 판과 어긋날 수 있다. 그 위험을
숨기지 않고, `PriorityResolver` 가 감지해서 `UNKNOWN` 으로 답한다 (§7).

### 결정론

`canonical_state()` 는 문자열과 정수로만 이루어진다. dict/set 순회 순서에
의존하지 않고, `PYTHONHASHSEED` 를 0/1/12345 로 바꿔 **별도 프로세스에서
실제로 돌려** 같은 값이 나오는지 확인한다.

---

## 6. 전이 — 전부 새 상태를 돌려준다

```python
new = old.passed()      # old 는 그대로다
```

| | 하는 일 | 연속 패스 |
|---|---|---|
| `opened(window, holder, …)` | 기회를 연다 | 0 |
| `give_to(holder)` | 우선권을 넘긴다 (**새 기회를 주는 것**) | 0 으로 |
| `passed()` | 지금 차례인 사람이 패스 → 맞은편으로 | +1 |
| `acted()` | 무언가 했다 | 0 으로 |
| `closed(reason)` | 기회를 닫는다 | 0 |
| `in_phase(phase, turn_player)` | 턴 문맥만 갈아 끼운다 | 유지 |

### 패스는 아무것도 해결하지 않는다

`passed()` 안에서 체인을 닫지도, 효과를 처리하지도, 페이즈를 넘기지도
않는다. **기회는 그대로 유지된다** — 패스가 기회를 닫는다면 그 판단이 이미
규칙이기 때문이다. 6번 연속 패스해도 `window` 는 그대로라는 테스트가 있다.

`both_passed` 는 `consecutive_passes >= 2` 라는 **사실**만 말한다. 그것이
무엇을 뜻하는지(체인 종료 등)는 Phase 2-F-2 가 정한다.

### 잘못된 전이

"아무도 차례가 아닌데 패스한다" 는 판정이 아니라 **호출 쪽의 결함**이므로
`PriorityError` 를 던진다. 반면 "지금 이 플레이어가 행동할 수 있는가" 는
판정이므로 `ValidationResult` 로 답한다. 둘을 섞지 않는다.

---

## 7. `PriorityResolver` — 관측만 읽는다

```python
PriorityResolver(view, priority).may_act(seat)    -> ValidationResult
PriorityResolver(view, priority).may_respond(seat)
```

`GameState` 를 넘기면 `TypeError` 다 (`CostValidator` · `ActionValidator` 와
같은 태도).

| 상황 | 판정 | 코드 |
|---|---|---|
| 우선권 상태가 판과 어긋남 | **`UNKNOWN`** | `PRIORITY_STATE_STALE` |
| 열린 기회 없음 | `INVALID` | `NO_RESPONSE_WINDOW` |
| 다른 사람 차례 | `INVALID` | `NOT_PRIORITY_HOLDER` |
| 그 사람 차례 | `VALID` | `OK` |

어긋남이 `UNKNOWN` 인 이유: 복사본이 다르다는 것은 어느 한쪽이 낡았다는
뜻인데 **어느 쪽인지 알 수 없다.** 모르는 것을 "안 된다" 로 단정하지 않는다.

> **`VALID` 는 차례가 그 사람의 것이라는 뜻일 뿐이다.** 할 수 있는 행위가
> 하나라도 있다는 뜻이 아니다. 행위 하나의 합법성은 `ActionValidator` 가
> 따로 답하고, 그쪽은 이번 단계에서 **바꾸지 않았다.**

### 정보가 새지 않는다

`PriorityState` 에는 카드가 하나도 들어 있지 않다. 그래서 두 관측자
(`viewer=0` / `viewer=1`)가 **같은 판정**을 받는다 — 가려진 정보에
의존한다면 두 답이 갈렸을 것이다. 테스트가 둘을 비교한다.

---

## 8. 구현하지 않은 것

Chain (`ChainLink` · `ChainBlock` · `ChainResolver` · `ChainExecutor`) ·
Trigger · Timing ("when"/"if" · optional/mandatory · SEGOC · 동시 트리거
순서) · Spell Speed · 발동 합법성 · 카드별 발동 조건 · Phase progression ·
ActionExecutor · Summon · Battle · Damage Step · 승패 판정 · AI · search/
planning.

`ActionValidator` 는 **한 줄도 바꾸지 않았다.** 우선권 검사를 붙이는 것은
이번 단계에 꼭 필요하지 않다.

`EffectExecutor` · `CostPayer` · `GameState` · `TurnState` 도 그대로다.

---

## 9. 테스트

`tests/engine/test_priority.py` — 47개.

| 묶음 | 보는 것 |
|---|---|
| 불변 · 결정론 | 필드 수정 거부 · 값 비교 · 평문 직렬화 · **`PYTHONHASHSEED` 3종을 별도 프로세스에서** |
| 전이 | 양방향 패스 · 연속 패스 추적 · `acted()` 가 끊음 · `give_to` ≠ 패스 · 닫기 · **패스가 기회를 닫지 않음** |
| 잘못된 전이 | 기회 없이 패스/행동/넘김 · 모순된 상태 2종 · `NONE` 열기 · `NOBODY` 에게 넘김 · 없는 자리 · 음수 패스 |
| 보존 | 기회·턴 문맥 유지 · 재동기화 · **holder ≠ turn_player 허용** · `NOBODY` 의 상대 · 절대 자리 ≠ 상대 참조 |
| 판 불변 | 생성·전이·조회가 `state_hash` 를 건드리지 않음 · 판 손잡이 없음 · raw `GameState` 거부 · **우선권은 판 해시에 없음** · `clone()` 독립성 유지 |
| 조회 판정 | 보유자/비보유자 · 기회 없음 · ACTION ≠ RESPONSE · **`VALID` 가 행위 존재를 주장하지 않음** · `bool()` 거부 · 없는 자리 · **어긋남 → `UNKNOWN`** |
| 정보 | 카드 정보 부재(모양으로 확인) · **두 관측자가 같은 판정** |
| 경계 | 체인/트리거/스펠스피드 이름 부재 · `analysis` 미import · 어휘 고정 |

전체 회귀: **1257 passed, 4 skipped** (Phase 2-E 기준 1210 + 47).
