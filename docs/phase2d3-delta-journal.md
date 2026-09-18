# Phase 2-D-3 — StateDelta + EventJournal 최소 골격

기준 커밋: `5f57762` (Phase 2-D-2 Hotfix)

이 단계는 **새 능력을 주지 않는다.** 실행기가 하는 일은 어제와 같다. 달라진
것은 그 실행이 판을 어떻게 바꿨는지를 **값으로 남긴다**는 것뿐이다.

```
EffectExecutor
    ↓  GameState mutation      ← 실제 변경은 여전히 여기서 일어난다
    ↓  StateDelta              ← 그 변경을 값으로 적는다
    ↓  EventJournal            ← 순서대로 쌓는다
```

---

## 1. 작업 전 검수 결과

### 기존 mutation 구조

`EffectExecutor` 하나만 판을 바꾼다. 계획(`_plan`) 이 전부 확인한 뒤
적용(`_apply`) 이 `GameState.move` / `draw` / `PlayerState.change_life` 를
부른다. 실패하면 적용이 시작되지 않으므로 부분 변경이 없다.

### 기존 result 구조

`EffectResult(status, code, reason, missing, applied)`. `applied` 는
`AppliedOperation` 의 튜플로 **어떤 일을 실행했는가**를 담는다. 목적지도
출발지도 없다 (이미 STRUCTURAL-12 로 기록되어 있던 한계).

### 이미 있던 Delta/Journal 구조

**없었다.** 실제 코드에 있는 것은 `GameState.journal: list[Any]` 라는
빈 자리표시 하나뿐이고, 아무도 읽거나 쓰지 않으며 `canonical_state()` 에도
들어가지 않는다. 설계 문서(`duel-engine-design.md` §13, ADR-008)에 이름만
예고되어 있었다. 그래서 새로 만들었다.

### 새 StateDelta 구조

`engine/effect/delta.py` — `StateDelta` (기반) · `CardMovement` (카드가
움직인 변화의 공통 질문) · `ZoneMoved` · `CardDrawn` · `LifeChanged`.

### 새 EventJournal 구조

`engine/effect/journal.py` — `EffectEvent` (불변, `sequence` 가 identity) ·
`EventJournal` (append-only) · `JournalError`.

---

## 2. Delta 는 기록이지 계획이 아니다

`StateDelta` 에 `apply(state)` 도 `undo(state)` 도 **없다.** 테스트가 이것을
직접 고정한다 (`test_a_delta_cannot_change_the_board`).

기록이 판을 바꿀 수 있게 되는 순간 "무슨 일이 있었는가" 와 "무슨 일을
하겠다" 가 한 타입에 섞인다. 되돌리기는 정확한 의미(무엇을 어디까지
되돌리는가, 그 사이 발동한 트리거는 어떻게 되는가)를 정한 뒤에 만든다
(ADR-008).

다만 **나중에 추가할 수 없는 것은 그때 사라진 정보**뿐이므로, 지금부터
빠짐없이 적는다: 어느 카드가 · 어디에서 · 어디로 · 무슨 의미로.

---

## 3. Delta 세 종류

| 타입 | 담는 것 |
|---|---|
| `ZoneMoved` | `operation` · `instance` · `from(player, zone)` · `to(player, zone)` |
| `CardDrawn` | `player` · `instance` (출발·도착은 DECK→HAND 로 고정) |
| `LifeChanged` | `player` · `before` · `after` |

### 목적지로는 구분할 수 없다

`ZoneMoved` 가 `operation` 을 함께 든다. 없으면 이렇게 뭉개진다.

```
파괴        → GRAVE
묘지로 보냄 → GRAVE     ← Delta 가 목적지만 적으면 셋이 하나가 된다
릴리스      → GRAVE
버림        → GRAVE
```

`reason_names` 도 함께 노출한다 (`REASON_*` 의 **이름**, 값은
`constant.lua` 에서 읽는다). 트리거 계층이 "파괴되었을 때" 와 "묘지로
보내졌을 때" 를 가를 근거가 이것이다 (ADR-002).

### 한 사실은 한 모양으로만

`ZoneMoved` 는 `operation is DRAW` 를 **거부한다.** 드로우는 `CardDrawn`
하나로만 적는다. 같은 사실을 두 모양으로 적을 수 있으면 세는 쪽이 반드시
두 번 센다.

대신 둘 다 `CardMovement` 다. 트리거 계층은 종류를 하나하나 세지 않고
`isinstance(delta, CardMovement)` 로 "이번에 움직인 카드" 를 물을 수 있다.

### 요청한 값과 실제로 달라진 값

`LifeChanged` 는 `before` / `after` 를 적는다. `change_life` 는 0 아래로
내려가지 않으므로, 1000 남은 플레이어에게 -3000 을 걸면 **실제 변화는
-1000** 이다.

```
AppliedOperation.amount = -3000   요청한 값
LifeChanged.amount      = -1000   실제로 달라진 값
```

둘의 차이가 곧 "얼마가 막혔는가" 다. 한쪽만 남기면 이 사실이 사라진다.
실제로 달라진 것이 없으면(이미 0 인 라이프) Delta 도 만들지 않는다.

---

## 4. `AppliedOperation` 과의 관계

**삭제하지 않았고, 필드도 바꾸지 않았다.**

```
AppliedOperation   어떤 효과의 일을 실행했는가
      ↓  1 : N
StateDelta         그 실행으로 판이 어떻게 달라졌는가
```

"몬스터 2장을 제외한다" 는 `AppliedOperation` 하나 · `ZoneMoved` 둘이다.
"3장 드로우" 는 하나 · `CardDrawn` 셋이다.

---

## 5. `EffectResult.deltas`

```python
EffectResult(
    status=ResolutionStatus.RESOLVED,
    applied=(...),   # 무슨 일을 했는가
    deltas=(...),    # 판이 어떻게 달라졌는가
)
```

`RESOLVED` 가 아닌 결과에 `deltas` 를 주면 **생성 자체가 거부된다**
(`__post_init__`). "실패했는데 변화 기록이 있는" 결과는 만들어지지 않는다.

### `resolved` 와 `changed_state` 를 나눴다

`changed_state` 의 뜻을 `status is RESOLVED` 에서 `bool(deltas)` 로 바꿨고,
예전 뜻은 새 `resolved` 속성이 가져갔다.

이유: 하는 일이 하나도 적혀 있지 않은 정의(`operations=()`)는 성공하고도
아무것도 바꾸지 않는다. 그때 `changed_state` 가 참이면 결과가 거짓말을
한다. 두 질문은 다르다.

| | 해결됨 | 판이 달라짐 |
|---|---|---|
| 드로우 1장 | ✓ | ✓ |
| 일이 없는 정의 | ✓ | ✗ |
| 조건 거짓 | ✗ | ✗ |

---

## 6. EventJournal

```python
journal = EventJournal()
executor = EffectExecutor(registry, journal=journal)
executor.execute(state, definition, context)

journal[0].sequence      # 0
journal[0].effect_ref    # EffectRef(2511, 0)
journal[0].deltas        # (ZoneMoved(...), CardDrawn(...))
journal.journal_hash()   # 결정론적
```

### 판을 소유하지 않는다

`EventJournal` 은 `GameState` 를 참조조차 하지 않는다. 방향은 한 쪽뿐이다 —
실행기가 판을 바꾸고, 그 결과를 journal 에 적는다.

같은 이유로 journal 은 `GameState` **안에** 살지 않는다. 안에 넣으면
`state_hash()` 가 "판의 모양" 이 아니라 "어떤 경로로 왔는가" 를 뜻하게
되고, Phase 1 이 세운 **"같은 판은 만들어진 경로와 무관하게 같은 해시"**
가 깨진다.

```
state.state_hash()      판이 어떤 모양인가
journal.journal_hash()  어떤 역사를 지나왔는가
```

다른 질문이므로 따로 둔다. `test_a_different_history_hashes_differently` 가
이것을 고정한다 — 순서만 다르게 같은 판에 도달하면 `state_hash` 는 같고
`journal_hash` 는 다르다.

`GameState.journal` 자리표시는 **비워 둔 채로 남겼고**, 왜 채우지 않는지를
주석에 적었다.

### 덧붙이기만 한다

`append` 와 `record` 뿐이다. `delete` · `remove` · `pop` · `clear` ·
`edit` · `replace` · `insert` 는 만들지 않았고, 테스트가 그 부재를 직접
확인한다.

`append` 는 번호가 어긋나면 **거부한다.** 조용히 다시 매기지 않는다 —
고쳐 주면 기록과 실제 실행 순서가 달라진 것을 아무도 모르게 된다.

### 기록은 선택이다

`journal=None` 이 기본이다. 있든 없든 **실행 결과와 판은 똑같아야 한다** —
기록이 판정에 끼어들면 기록이 아니다
(`test_a_journal_is_optional_and_never_changes_the_outcome`).

### 무엇을 적는가

`RESOLVED` 이고 **변화가 하나라도 있을 때**만 적는다.

- 실패 → `deltas == ()` · journal 변화 없음
- 성공했으나 바꾼 것이 없음 → journal 변화 없음
- 성공하고 바꿨음 → 사건 하나 추가

세 번째 줄이 §12 의 "성공한 mutation 만 기록한다" 다. 두 번째 줄은
재생(replay)이 들어올 때 다시 봐야 한다 — 아래 STRUCTURAL-13 참고.

---

## 7. 결정론

`EffectEvent.sequence` 가 identity 다. 쓰지 않는 것:

- 무작위 UUID
- 시각(timestamp)
- 객체 주소 · `repr`
- 파이썬 기본 `hash()`
- 프로세스에 따라 달라지는 순서

`canonical_state()` 는 정수 · 문자열 · 불리언으로만 이루어지고, JSON 으로
직렬화한 뒤 SHA-256 을 취한 것이 `journal_hash()` 다.

`effect_ref` 는 언제나 `EffectRef(card_id, ordinal)` 다. `EffectSpec.index`
(Lua 변수명 `"e1"`, 한 카드 안에서 중복 — 실측 4,884장)를 실행 identity 로
쓰지 않는다는 Phase 2-D-1 의 원칙 그대로이고, 직렬화 결과에 `"e1"` 이
나오지 않는지를 테스트가 확인한다.

---

## 8. 실패 불변식

Phase 2-D-2 가 세운 것에 journal 한 줄이 더해졌다.

```
실패:  state_hash_before == state_hash_after
       journal_before    == journal_after
       deltas            == ()

성공:  deltas            != ()          (바꾼 것이 있다면)
       journal 에 사건 하나 추가
```

다음 여섯 가지 실패 전부에서 확인한다: forbidden source · unsupported
operation · condition false · condition unknown · invalid target ·
insufficient cards. 여기에 미등록(`NOT_IMPLEMENTED`)을 더해 일곱이다.

`EXECUTION_ERROR` 는 예외다. 판이 반쯤 바뀌어 있을 수 있으므로 **변화
기록을 돌려주지 않는다** — 반쪽짜리 기록은 없는 것보다 나쁘다. 그것을
근거로 되감으면 틀린 판이 된다.

---

## 9. 주인 · 컨트롤러 · InstanceId

Hotfix 의 `destination = owner` 가 **기록에도** 그대로 나온다.

```
owner=P1, controller=P0 인 카드를 묘지로:

ZoneMoved(
    operation=SEND_TO_GRAVE,
    from_player=0,   ← 내가 컨트롤하고 있었다
    to_player=1,     ← 주인에게 돌아간다
)
```

출발지는 **옮기기 전에** 읽는다. 옮긴 뒤에 읽으면 도착지가 두 번 적힌다.

`test_a_delta_never_names_a_card_that_is_not_there` 가 기록에 나온 모든
카드에 대해 실제 판의 존·컨트롤러가 기록과 같은지 확인한다. 판은 맞는데
기록이 틀리면 트리거 계층이 틀린 사건을 보게 된다.

---

## 10. 만들지 않은 것

- **Replay engine** — journal 로 판을 되살리는 것
- **Rollback / undo** — Delta 에 `apply` · `undo` 가 없다
- **Transaction system**
- **파일 · DB · 네트워크 journal** — 메모리뿐이다
- **실패 이벤트 기록** — §12 를 임의로 확장하지 않았다
- Chain · Trigger · Timing · Priority · CostPayment · ActionExecutor ·
  Summon · Battle · AI

---

## 11. 테스트

`tests/engine/test_state_delta_journal.py` — 46개.

| 묶음 | 보는 것 |
|---|---|
| StateDelta | 불변 · `apply`/`undo` 부재 · 값 비교 · `to_dict` 가 JSON 이 됨 · 객체 identity 없음 · 드로우는 한 모양 · `CardMovement` 공통 질문 |
| Zone mutation | 5개 일의 Delta · 버리기의 출발 존 · 릴리스 ≠ 묘지送り · 여러 장 → 변화 여럿 |
| Life | before/after · **요청값 ≠ 실제 변화** · 변화 없으면 기록 없음 |
| Draw | 장당 Delta · 상대 드로우 · 부족하면 Delta 없음 |
| EffectResult | `applied` 3 / `deltas` 4 · 일 없는 정의의 성공 · 6가지 실패 전부 |
| EventJournal | append · 불변 사건 · 순서 · `EffectRef` 사용 · 결정론 · **append-only** · 선택적 · 판 비소유 |
| Authority | `TEXT_DERIVED` · 미등록 · unsupported — 전부 기록 없음 |
| Identity | 주인의 존이 기록됨 · identity 보존 · **기록과 판의 일치** |
| Determinism | 같은 입력 → 같은 Delta·기록 · 다른 역사는 다른 해시 · 판 해시는 역사와 무관 |

전체 회귀: **1163 passed, 4 skipped** (Phase 2-D-2 Hotfix 기준 1116 + 46,
그리고 기존 테스트 1개가 2개로 나뉘며 강화).
