# Phase 2-H — Turn / Phase Progression

기준 커밋: `c37daec` (Phase 2-G)

```
GameState (T1 P0 DRAW)
    ↓  TurnProgressor.next_position()     순수 계산 — 판정하지 않는다
TurnPosition (T1 P0 STANDBY)
    ↓  TurnProgressor.plan()              진행 순서와 맞는가
TransitionPlan          허가 · 전이 · 아직 보지 않은 규칙
    ↓  TurnProgressor.advance()           여기서만 판이 바뀐다
GameState (T1 P0 STANDBY)  +  PhaseChanged
```

---

## 1. 작업 전 검수 — §19 의 아홉 질문

코드를 고치기 전에 저장소를 먼저 읽고 답한 것이다. 답이 설계를 줄였다.

### Q1. 현재 `GameState` 에 Turn/Phase 상태가 어떻게 저장되어 있는가

`GameState.turn` 에 `TurnState` 하나로 들어 있다 (Phase 1).

| 칸 | 뜻 |
|---|---|
| `turn_number` | 1 부터. `__post_init__` 이 0 이하를 거부한다 |
| `turn_player` | 0 또는 1 |
| `phase` | `engine.vocabulary.Phase` |
| `step` | 페이즈 안의 진행 단계 (Phase 1 은 0 고정) |

그리고 `TurnState.canonical_state()` 가 이미 `GameState.canonical_state()` 에
들어가 있다 — **페이즈는 처음부터 판의 모양에 포함되어 있었다.** 그래서
페이즈를 옮기면 `state_hash()` 가 바뀐다.

### Q2. Phase 1 의 Turn/Phase 모델을 그대로 재사용할 수 있는가

**그대로 쓴다. 한 줄도 고치지 않았다.**

- `Phase` (10개) — `DRAW · STANDBY · MAIN1 · BATTLE_START · BATTLE_STEP ·
  DAMAGE · DAMAGE_CAL · BATTLE · MAIN2 · END`. 이름이 `PHASE_*` 상수에서
  왔으므로 새로 만들면 어휘가 어긋난다.
- `TURN_PHASE_ORDER` (6개) — `DRAW → STANDBY → MAIN1 → BATTLE → MAIN2 →
  END`. 요구된 순서가 **이미 있었다.** 배틀 스텝 내부는 여기 없다.
- `TurnState.advance_phase()` / `begin_next_turn()` / `set_phase()` — 값을
  바꾸는 낮은 API. 규칙이 아니라고 스스로 적어 두었다.

### Q3. 새로운 모델이 정말 필요한가

**필요한 것은 하나뿐이었다** — "지금 자리에서 다음 자리로 가는 한 걸음" 을
값으로 표현하는 것. `TurnState` 는 그것을 표현하지 못한다:

- `advance_phase()` 는 엔드 페이즈에서 **멈춘다.** 턴 넘김은 다른
  메서드이고, 언제 어느 쪽을 부르는지는 아무 데도 적혀 있지 않았다.
- 돌려주는 것이 `Phase` 하나라서 "턴 번호와 턴 플레이어가 함께 바뀌었다"
  를 말하지 못한다.
- 갈 수 있는지 없는지를 판정하지 않는다 (판정하지 않는 것이 그 계층의
  올바른 책임이다).

그래서 `TurnPosition` · `PhaseTransition` · `TransitionPlan` ·
`ProgressionResult` 넷만 만들었다. **범용 상태 기계도, 이벤트 버스도,
규칙 DSL 도 만들지 않았다** (§18).

### Q4. Turn transition 은 어디에 있는 것이 자연스러운가

**`engine/turn_progression.py`** — `state/` 위, `priority.py` ·
`timing.py` 옆이다.

`TurnState` 안에 넣으면 Phase 1 이 규칙을 갖게 되고 (그 모듈이 스스로
거부한 것이다), `GameState` 에 넣으면 판이 자기 시간을 스스로 굴리게 된다.
판정은 판 밖에 둔다 — `ActionValidator` · `PriorityResolver` ·
`TimingCoordinator` 가 전부 그렇게 서 있다.

### Q5. `ActionExecutor` 와 어떻게 연결되는가

`PhaseTransitionHandler` 가 `ActionHandler` 프로토콜을 만족한다. **규칙을
하나도 갖지 않고** `TurnProgressor` 에게 전부 넘긴다 (테스트가 AST 로
확인한다 — 핸들러 본문에 `TURN_PHASE_ORDER` 도 `Phase` 도 없다).

**기본 등록은 하지 않는다.** `ActionValidator.validate()` 는 여전히
`CHANGE_PHASE` 에 `UNKNOWN` 을 준다. 진행 순서가 생겼다고 해서 Action 이
허가되지는 않기 때문이다 — 우선권을 쥔 쪽이 선언했는지, 체인이 남아
있는지, 그 페이즈에 들어가도 되는지가 전부 없다. **억지로 `VALID` 로 만들지
않았다** (§6).

그래서 오늘의 경계는 이렇다:

```
PlayerAction → ActionValidator → (UNKNOWN, 여기서 멈춘다)
TurnProgressor.advance(state)  ← 지금 쓸 수 있는 입구
```

규칙 계층이 생기는 날에는 `executor.register(CHANGE_PHASE,
PhaseTransitionHandler())` 한 줄이면 위의 경로가 이어진다. 테스트가 그
날의 경로를 미리 한 번 통과시켜 둔다 (허가는 `ValidationResult.valid()`
공개 생성자로 만든다).

`END_PHASE` 는 **맡지 않는다.** "엔드 페이즈로 간다" 인지 "턴을 끝낸다"
인지 정해져 있지 않고, 하나를 고르면 그 추측이 규칙이 된다.

### Q6. `PriorityState` 와 무엇을 공유하고 무엇을 공유하지 않는가

| | |
|---|---|
| 공유한다 | 없음. 진행 계층은 `engine.priority` 를 **import 하지 않는다** |
| 남긴다 | `PhaseTransition.requires_priority_update` — "다시 정해야 한다" 는 사실만 |
| 정하지 않는다 | **누구에게 가는가.** 그것은 우선권 계층의 규칙이다 |

턴 플레이어가 P0 → P1 로 바뀌었다고 우선권을 P1 로 대입하지 않는다 (§5).
테스트가 확인한다: 턴이 넘어가도 옆에 있던 `PriorityState` 는 한 글자도
바뀌지 않는다.

`PriorityResolver._staleness()` 는 이미 "우선권이 말하는 턴/페이즈" 와
"판이 말하는 턴/페이즈" 가 어긋나면 `UNKNOWN` 을 준다. 즉 **전이 뒤에
우선권이 낡았다는 사실은 이미 감지된다** — 갱신 규칙이 없을 뿐이다
(STRUCTURAL-34 그대로).

### Q7. 턴 경계에서 어떤 상태가 나중에 reset 되어야 하는가

`TURN_BOUNDARY_RESETS` 에 목록으로 남겼다. **이번 단계에서 하나도 지우지
않는다.**

1. `UseRegistry` — `PER_CARD` · `PER_CARD_NAME` · `PER_EFFECT` 의 "1턴에 1번"
2. 일반 소환권 (아직 모델이 없다)
3. "이 턴에 공격했는가 · 표시 형식을 바꿨는가" (아직 모델이 없다)
4. 이 턴에만 적용되는 지속 효과 (`AppliedEffect`, Phase 8)
5. `TurnState.step`

`UseRegistry` 는 "언제 지워지는가는 규칙이라 Phase 1 이 정하지 않는다" 고
스스로 적어 두었다. 그 정책을 깨지 않았다 (§11) — 규칙 없이 지우면
"지웠다" 는 사실이 판에 남아 되돌릴 수 없다.

### Q8. Event/Timing 으로 이어질 최소 boundary 는 무엇인가

**`PhaseChanged` 라는 `StateDelta` 하나다.**

새 이벤트 모델을 만들지 않았다. `ActionHandler` 가 이미
`tuple[StateDelta, ...]` 를 돌려주기로 되어 있으므로, 진행 결과가 같은
모양으로 나오면 `EventJournal` 이 붙을 자리가 이미 있는 셈이다.

**턴 변화를 따로 만들지 않았다.** 턴 넘김은 엔드 페이즈에서 다음 턴
드로우 페이즈로 가는 *한 번의* 이동이고, `PhaseChanged` 와 `TurnChanged`
두 장으로 적으면 세는 쪽이 한 사건을 두 번 센다. 턴이 함께 바뀌었는지는
`changes_turn` 이 말한다. (`ZoneMoved` 와 `CardDrawn` 을 **갈라놓은** 이유와
정확히 반대되는 이유다 — 저쪽은 두 사건, 이쪽은 한 사건이다.)

`EventJournal` 에 `EventKind.PHASE_CHANGE` 를 **만들지 않았다.** 페이즈
변화가 어떤 사건으로 기록되어야 하는지는 트리거 계층이 정할 일이고,
Phase 2-G 에서 `ActionEvent` 를 만들지 않은 것과 같은 이유다.
`TimingEvent` · `TriggerCandidate` · `ChainLink` 도 만들지 않는다 —
테스트가 AST 로 감시한다.

### Q9. 현재 구조에 BLOCKER 가 있는가

**없다.** 구현을 막은 것이 하나도 없었다. 재검토한 기존 문제:

| | 진행 계층을 막는가 |
|---|---|
| STRUCTURAL-15 (`CandidateResolver` 의 가려진 존 처리) | 아니다 — 비용 선택의 문제다 |
| STRUCTURAL-34 (우선권 갱신 없음) | 아니다 — 진행은 우선권을 건드리지 않는다 |
| STRUCTURAL-35 (`TimingWindow` 가 사건 하나) | 아니다 |
| STRUCTURAL-36 (준비된 체인의 채택 주체 없음) | 아니다 |
| `ActionEvent` 부재 | 아니다 — Delta 로 충분하다 |
| 핸들러 rollback 부재 | 아니다 — 전이는 한 걸음이라 중간 상태가 없다 |

---

## 2. 책임 분리

| | 답하는 질문 |
|---|---|
| `TurnState` | 지금 **몇 턴 누구의 어느 페이즈**인가 (값) |
| `TurnProgressor.next_position` | 순서상 **다음 자리**는 어디인가 (계산) |
| `TurnProgressor.plan` | 그리로 **옮겨도 되는가** (판정) |
| `TurnProgressor.advance` | 실제로 **옮긴다** (변경) |
| `PhaseChanged` | 무엇이 **달라졌는가** (기록) |

---

## 3. `VALID` 가 뜻하는 것 — 좁게 읽어야 한다

`plan()` 의 `VALID` 는 **"이 엔진이 아는 진행 순서와 맞다"** 는 뜻이다.
"지금 이 페이즈에 들어가도 된다" 는 규칙 전체의 허가가 **아니다.**

둘을 한 단어로 부르면 아직 없는 규칙들이 조용히 통과한다. 그래서 허가가
난 계획도 `unresolved_rules` 를 **그대로 들고 다닌다**:

- 선공 첫 턴에 배틀 페이즈를 실행할 수 없다는 규칙
- 배틀 페이즈가 없었으면 메인 페이즈 2 도 없다는 규칙
- 체인이 남아 있거나 해결 중일 때 페이즈를 끝낼 수 있는가
- 우선권을 쥔 쪽이 페이즈 종료를 선언했는가
- 페이즈를 건너뛰거나 추가하는 카드 효과
- 전이 직후 우선권이 누구에게 열리는가
- 배틀 스텝 · 데미지 스텝 안의 진행

특히 **선공 첫 턴의 배틀 페이즈**는 실제 규칙이지만 구현하지 않았다.
구현하려면 "그럼 메인1 다음은 어디인가" 라는 건너뛰기 규칙이 함께
필요하고, 그것은 이번 단계의 범위를 넘는다. 아는 척하지 않고 목록에
적어 둔다 (테스트가 이 사실을 고정한다).

---

## 4. 세 갈래 거절

| 상황 | 판정 | 코드 |
|---|---|---|
| 끝난 듀얼 | INVALID | `DUEL_ALREADY_OVER` |
| 이미 그 페이즈 | INVALID | `PHASE_UNCHANGED` |
| 지나온 페이즈로 되감기 | INVALID | `WRONG_PHASE` |
| 순서 위에 없는 페이즈를 요청 | INVALID | `WRONG_PHASE` |
| 배틀 스텝 · 데미지 스텝에 서 있음 | **UNKNOWN** | `RULE_NOT_IMPLEMENTED` |
| 앞쪽 페이즈로 건너뛰기 (메인1 → 엔드) | **UNKNOWN** | `RULE_NOT_IMPLEMENTED` |

**새 `ValidationCode` 를 하나도 만들지 않았다.** 여섯 가지 전부 기존
코드로 표현된다 (§14).

건너뛰기를 `INVALID` 로 적지 않은 것이 중요하다 — 실제 규칙에서는 메인
페이즈 1 에서 엔드 페이즈로 바로 갈 수 있다. "안 된다" 가 아니라 "건너뛴
배틀 페이즈가 없었다는 사실이 무엇을 바꾸는지 모른다" 이다.

---

## 5. Mutation Safety

- 판이 바뀌는 곳은 `TurnProgressor._apply` **한 곳**이고, 거기서도
  `TurnState.advance_phase()` / `begin_next_turn()` 만 부른다. `GameState`
  에 새 mutation API 를 붙이지 않았다.
- `plan()` 은 아무것도 바꾸지 않는다 (테스트가 해시로 확인한다).
- 허가가 나지 않으면 `_apply` 를 **부르지도 않는다.** 전이는 한 걸음이라
  부분 변경이 생길 수 없다 — rollback 이 필요 없는 이유다.
- 옮긴 뒤 **계획한 자리에 있는지 확인한다.** 어긋나면 기록을 남기지 않고
  `TurnProgressionError` 를 던진다 (`EffectExecutor` 의 이동 후 검증과 같은
  규율).
- `TransitionPlan` 은 허가가 났을 때만 전이를 들고, `ProgressionResult` 는
  `ADVANCED` 일 때만 Delta 를 든다. 둘 다 `__post_init__` 이 강제한다.
- `PhaseTransition` 은 턴 넘김의 모양을 강제한다 — "턴은 늘었는데
  플레이어는 그대로" 같은 전이는 **값으로도 만들어지지 않는다.**
- `TransitionPlan` · `ProgressionResult` 의 `__bool__` 은 예외를 던진다.

---

## 6. Determinism

- `TurnProgressor` 는 **상태를 갖지 않는다** (`__slots__ = ()`). 난수도
  시간도 사전 순회 순서도 쓰지 않는다.
- 같은 판에서 같은 명령 → 같은 판. 같은 해시.
- 복제본을 옮겨도 원본은 그대로다.
- 카드 정의는 읽지도 않는다.

---

## 7. 이번 단계에서 만들지 않은 것

§16 이 금지한 것 전부. 특히:

- 실제 드로우 · 스탠바이 처리 · 엔드 페이즈 처리 — **시간만 옮긴다**
- 시작 시 드로우 · 첫 턴 드로우 여부
- 페이즈별 행동 제한 (`ActionValidator` 는 그대로다)
- 우선권 갱신 · 응답 창 · SEGOC
- 트리거 발생 · 체인 구성
- 턴 경계 리셋 — **목록만 남겼다**
- `EventKind.PHASE_CHANGE`

---

## 8. 앞으로 만들면 좋은 것

이번 단계에서 고칠 것이 아니라, 다음 계층이 할 일이다.

1. **전이 직후 우선권을 여는 규칙** (STRUCTURAL-34 와 같은 뿌리). 진행
   계층은 "다시 정해야 한다" 까지만 말한다.
2. **페이즈 변화의 사건화** — `TimingEvent` 로 만들어 트리거 수집에
   넣는 것. `PhaseChanged` 가 그 입력이 된다.
3. **턴 경계 리셋** — `TURN_BOUNDARY_RESETS` 의 다섯 줄.
4. **`END_PHASE` 의 뜻을 정하는 것** — 엔드 페이즈로 가는가, 턴을 끝내는가.
5. **선공 첫 턴 배틀 페이즈 · 페이즈 건너뛰기** — 지금은 `UNKNOWN` 으로
   남아 있다.
6. **`ActionValidator` 가 `CHANGE_PHASE` 에 `VALID` 를 주는 날** — 그때
   `PhaseTransitionHandler` 를 등록하면 `ActionExecutor` 경로가 이어진다.
