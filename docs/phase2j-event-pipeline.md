# Phase 2-J — Event Pipeline / Summon Event Integration

기준 커밋: `e599e41` (Phase 2-I)

```
GameState 변경                     ← 실행기가 이미 끝냈다
    ↓  StateDelta                  무엇이 달라졌는가 (2-D-3 · 2-H · 2-I)
    ↓  EventReader.read()          ← 이번 단계
ObservedEvent                      언제 · 누가 · 무슨 사건이었는가
    ↓  TriggerCollector.collect()  (2-F-3-A, 그대로)
TriggerCollection                  이 사건에서 나온 후보들
    ↓
[여기서 멈춘다]                     적격성 · 정렬 · 체인 · 우선권은 각자의 계층
```

---

## 1. 작업 전 검수

이번 단계에서 **새로 만든 것은 하나뿐이다** — Delta 와 사건 사이의 한 구간.

| 이미 있던 것 | 이번 단계에서 |
|---|---|
| `StateDelta` · `MonsterSummoned` · `PhaseChanged` | 그대로 사용, **변경 없음** |
| `TimingEvent` · `TimingPoint` | 값 두 개 추가 + `from_delta` 두 갈래 |
| `TriggerRegistry` · `TriggerCollector` · `TriggerCollection` | **그대로 호출.** 중복 수집기 없음 |
| `TriggerEligibilityJudge` (F-3-B) | 건드리지 않음 |
| `TriggerOrderer` (F-3-C) · `TriggerChainIntegrator` (F-3-D) | 건드리지 않음 |
| `TimingCoordinator` (F-4) | 건드리지 않음 — 만든 사건을 그대로 받는다 |
| `EventJournal` | **건드리지 않음.** `EventKind` 를 늘리지 않았다 |

기존 타입으로 표현할 수 없던 것은 하나였다: **"이 변화가 언제 · 누구의
행위로 일어났는가"**. 그것만 `EventContext` 로 만들었다.

---

## 2. Delta 와 사건을 구분한 이유 (§4)

| | 답하는 질문 |
|---|---|
| `StateDelta` | 판이 **어떻게 달라졌는가** |
| `TimingEvent` | 그 변화가 **무슨 사건인가** |
| `ObservedEvent` | 그 사건이 **언제 · 누구의 행위로** 일어났는가 |

`ObservedEvent` 는 Delta 를 **다시 적지 않는다.** `TimingEvent` 가 이미
Delta 를 들고 있으므로 그것을 감싸고, 더하는 것은 문맥 하나뿐이다. 같은
사실을 두 모양으로 적으면 세는 쪽이 두 번 센다 (`ZoneMoved` /
`CardDrawn` 을 가른 것과 같은 규율).

**새 Event 클래스를 카드 사건마다 만들지 않았다.** `MonsterSummonedEvent`
같은 타입을 세우면 사건 종류가 늘 때마다 클래스가 늘고, `TimingEvent` 와
두 갈래가 된다.

---

## 3. 새 `TimingPoint` 두 개

```
MONSTER_SUMMONED = "monster_summoned"
PHASE_CHANGED    = "phase_changed"
```

`TimingPoint` 는 "만들어 낼 수 있는 사건만 넣는다" 는 규칙을 지켜 왔다.
이 둘은 **그 규칙대로** 들어왔다 — Phase 2-H 와 2-I 가 실제로 그 변화를
만들어 내게 된 **뒤에** 이름이 생겼다. 전투 · 데미지 스텝은 여전히 없다.

**소환을 `CARD_MOVED` 에 합치지 않았다.** 카드가 패에서 필드로 움직인 것은
맞지만, "소환되었을 때" 와 "필드로 보내졌을 때" 는 유희왕에서 전혀 다른
사건이다. 합치면 트리거 계층이 그 둘을 영영 구분할 수 없다 — ADR-002 가
파괴와 묘지로 보내기를 가른 것과 같은 이유다.

`PHASE_CHANGED` 는 **행위자를 적지 않는다** (`actor=None`). 페이즈 전이는
규칙이 하는 일이고, 누가 그것을 선언했는가는 우선권 계층의 질문이다. 턴
플레이어를 적어 넣으면 "그 사람이 한 일" 로 읽히게 된다.

`TimingEvent.instance` 도 고쳤다 — `MonsterSummoned` 는 `CardMovement` 가
아니지만 (소환은 효과의 어휘를 쓰지 않는다) 분명히 카드 한 장의 사건이라,
이동한 사건만 보던 것을 Delta 의 `instance` 까지 보도록 넓혔다.

---

## 4. 옮길 이름이 없는 변화 (STRUCTURAL-39)

`TimingEvent.from_delta` 는 모르는 Delta 를 만나면 **예외를 던진다.**
그것은 "지어내지 않겠다" 는 뜻이므로 그대로 두었다.

파이프라인은 거기서 멈추는 대신 그 사실을 사건으로 남긴다 —
`TimingPoint.UNIMPLEMENTED` 에 무엇을 옮기지 못했는지 적는다.
`ObservedEvent.is_observable` 이 거짓이면 **"사건이 없었다" 가 아니라
"옮길 이름이 없었다"** 는 뜻이다. 새 Delta 가 생겼을 때 실행이 죽는 것보다
이쪽이 낫다.

---

## 5. 사건 식별자 (§14)

`ObservedEvent.event_id` 는 **내용에서 나온다** — 문맥과 시점의
`canonical_state()` 를 SHA-256 으로 줄인 값이다. 무작위도, 시각도, 객체
주소도 쓰지 않는다. 같은 판에서 같은 행위를 하면 같은 값이고, 복제본에서도
같다 (테스트가 확인한다).

**듀얼 전체에 걸친 유일성은 보장하지 않는다.** 같은 턴 · 같은 페이즈에
내용이 똑같은 변화가 두 번 일어나면 같은 값이 나온다. 전역 번호가
필요해지면 `EventJournal.sequence` 가 그 자리다 — 지금 없는 것을 만들지
않았다 (STRUCTURAL-42 로 기록).

한 번의 변화 묶음 안에서는 `EventContext.sequence` 가 사건을 구분한다.
**순서가 곧 사실**이므로 Delta 순서를 그대로 유지한다.

---

## 6. 사건 하나 ↔ 후보 여럿 (§9)

`EventObservation` 이 `ObservedEvent` 와 `TriggerCollection` 을 **함께**
안고 있다. 후보 목록을 따로 펼치지 않는 이유는 단순하다 — 펼치는 순간
"어느 사건에서 나왔는가" 가 사라지고, 나중에 SEGOC 순서를 정할 근거가
없어진다.

`TriggerCollection.event` 가 이미 그 관계를 담고 있으므로 새 필드를 만들지
않았다. `__post_init__` 이 **다른 사건의 후보를 붙이는 것을 거부한다.**

실측: 페더맨 두 장이 보이는 판에서 소환 한 번에 후보 두 개가 나온다.

---

## 7. Hidden Information (§15)

파이프라인은 `GameStateView` 하나만 들고 있다. 관측자가 정하는 것은 부르는
쪽이고, **볼 수 없는 곳은 `unchecked` 로 남는다** — 상대의 패 · 덱 · 뒷면
카드에도 트리거가 있을 수 있으므로, 관측에 없다고 "후보가 없다" 고 답하면
모르는 것을 거짓으로 접는 것이다.

`unchecked` 에는 **장수만** 적힌다. 테스트가 상대 패의 카드 ID 가 결과에
새지 않음을 확인한다.

---

## 8. Mutation Safety (§16)

- `EventReader` · `EventPipeline` 은 `GameStateView` 만 받는다. `GameState`
  를 넘기면 **거부한다** — 바꿀 수 있는 것을 애초에 갖고 있지 않다.
- 사건을 읽어도, 후보를 모아도 `state_hash()` 가 변하지 않는다 (세 번
  반복해도 같다).
- 관측은 스냅숏이라 뒤에 판이 바뀌어도 파이프라인이 든 것은 흔들리지 않는다.
- 복제본을 관찰해도 원본은 그대로다.

---

## 9. 누가 부르는가 (§11 · §12)

**실행기는 이 파일을 모른다.** `event_pipeline.py` 도 실행기를 모른다 —
`ActionExecutor` · `NormalSummonHandler` · `TurnProgressor` · `GameState`
를 하나도 import 하지 않는다 (테스트가 AST 로 확인한다).

`read(result)` 는 **변화를 들고 있는 것**이면 무엇이든 받는다
(`ActionExecution` · `ProgressionResult` · 앞으로의 `EffectResult`). 특정
실행기를 가져오면 "실행기가 사건을 만들어야 한다" 는 뜻이 되고, 상태 변경과
사건 관찰이 다시 붙는다.

그래서 순서는 이렇게 된다 — **바깥에서 잇는다.**

```python
execution = executor.execute(state, action)      # 판이 바뀐다
pipeline  = EventPipeline(view_of(state), registry)
for observation in pipeline.collect(execution):  # 판은 그대로
    observation.candidates
```

`TimingCoordinator` (F-4) 도 그대로다 — 만들어진 `TimingEvent` 를 받아
자기 창을 연다. 파이프라인이 조정자를 부르지 않고, 조정자가 파이프라인을
부르지도 않는다.

---

## 10. 이번 단계에서 하지 않은 것

§21 이 금지한 것 전부. 특히:

- 자동 체인 생성 · 체인 해결 · 효과 실행
- EventBus · 구독 · 발행 프레임워크
- 완전한 SEGOC · WHEN/IF · Fast Effect Timing
- 실제 카드의 "소환 성공 시" 효과 — **트리거 선언은 손으로 등록한다**
  (자동 생성 컴파일러는 여전히 없다, STRUCTURAL-7)
- `EventJournal` 에 `EventKind.SUMMON` 추가
- 페이즈별 타이밍 규칙 ("스탠바이 페이즈에" 등)

---

## 11. 기존 STRUCTURAL 재검토

| | 이번 단계에서 |
|---|---|
| **STRUCTURAL-39** (소환 · 페이즈 변화를 시점으로 못 옮김) | **해결.** `from_delta` 가 둘을 옮기고, 모르는 Delta 는 `UNIMPLEMENTED` 로 남는다 |
| **STRUCTURAL-38** (Delta → Timing/Trigger 경계 없음) | **해결.** `EventReader` · `EventPipeline` 이 그 구간이다 |
| STRUCTURAL-15 · 34 · 35 · 36 · 37 · 40 · 41 | 그대로. 이번 구현을 막지 않았다 |
| `ActionEvent` · handler rollback | 그대로 |

---

## 12. 앞으로 만들면 좋은 것

1. **전역 사건 번호** — `EventJournal.sequence` 를 파이프라인에 잇는 것
   (STRUCTURAL-42).
2. **동시 사건을 한 창으로 묶는 규칙** — SEGOC 의 전제 (STRUCTURAL-35 와
   같은 뿌리). 지금은 사건마다 따로 수집한다.
3. **트리거 선언의 자동 생성** — 지금은 손 등록뿐이라 실제 카드의 "소환
   성공 시" 는 아무것도 걸리지 않는다.
4. **`EventKind` 확장** — 소환 · 페이즈 전이를 기록에 남기는 것.
5. **전투 · 데미지의 시점** — 그 계층이 생긴 뒤에.
