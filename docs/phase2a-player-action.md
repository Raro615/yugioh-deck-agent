# Phase 2-A — PlayerAction · GameStateView

**기준 커밋:** `3fbe32e` → 이 문서의 구현
**범위:** AI 가 **무엇을 할지 표현할 수 있지만, 아직 판을 바꾸지는 못한다.**

```
GameState
    ↓  GameStateView.from_state(state, viewer)     ← 읽기 전용 스냅숏
GameStateView
    ↓  PlayerAction.normal_summon(...)             ← 의도. 아무 일도 안 일어난다
PlayerAction
    ↓  ActionValidator().validate(state, action)   ← 모양만 본다. 상태를 안 바꾼다
ValidationResult(UNKNOWN)                          ← 규칙이 아직 없다
    ✗  실행 없음 — Phase 2-B 이후
```

---

## 1. 구현 전 확인한 것

| 질문 | 답 | 근거 |
|---|---|---|
| 기존 Action 모델이 있는가 | `analysis.effect_model.ActionKind` / `EffectAction` **뿐**. `engine/` 에는 없다 | Contract E |
| 두 어휘를 어떻게 분리하나 | 별도 이름 `PlayerActionKind` + AST 검사 | ADR-001 |
| View 는 스냅숏인가 살아있는 뷰인가 | **스냅숏** | 아래 §5 |
| 숨긴 정보를 어떻게 가리나 | **값을 안 넣는다** (플래그 아님) | 아래 §6 |
| ID 타입을 새로 만드나 | **안 만든다.** `InstanceId` · `EffectRef` · `int` 재사용 | 아래 §3 |
| UNKNOWN 을 어떻게 표현하나 | `ActionValidity.UNKNOWN` + `permits_execution` | 아래 §4 |
| 상태를 안 바꾼다는 걸 어떻게 검증하나 | `state_hash()` 비교 | 아래 §7 |

---

## 2. Action semantics

**Action 은 의도(intent)이고 실행이 아니다.**

```python
action = PlayerAction.normal_summon(actor=0, source=instance_id)
# 카드는 여전히 패에 있다. 소환권도 그대로다. state_hash() 도 그대로다.
```

### PlayerActionKind — 10가지

| 종류 | source | 대상 | effect_ref | phase |
|---|---|---|---|---|
| `NORMAL_SUMMON` | 필수 | 0 | ✗ | ✗ |
| `SET_MONSTER` | 필수 | 0 | ✗ | ✗ |
| `SET_SPELL_TRAP` | 필수 | 0 | ✗ | ✗ |
| `ACTIVATE_CARD` | 필수 | 제한 없음 | 선택 | ✗ |
| `ACTIVATE_EFFECT` | 필수 | 제한 없음 | **필수** | ✗ |
| `CHANGE_POSITION` | 필수 | 0 | ✗ | ✗ |
| `ATTACK` | 필수 | **정확히 1** | ✗ | ✗ |
| `CHANGE_PHASE` | ✗ | 0 | ✗ | **필수** |
| `END_PHASE` | ✗ | 0 | ✗ | ✗ |
| `PASS` | ✗ | 0 | ✗ | ✗ |

**`DESTROY` · `BANISH` · `SEND_TO_GRAVE` · `DISCARD` · `RELEASE` 는 없다.**
효과 해결의 결과이지 누가 고르는 것이 아니다 (ADR-002).

### 일부러 넣지 않은 것

| 빠진 것 | 이유 |
|---|---|
| `DRAW` | **아무도 고르지 않는다.** 턴 드로우는 규칙이고, 효과 드로우는 Effect 다. Action = "고르는 주체가 고르는 것" (ADR-001) 이므로 강제 드로우는 Action 이 아니다 |
| `TRIBUTE_SUMMON` | 릴리스할 몬스터를 **Action 이 들고 있어야 하는지, 해결 중의 선택인지** 아직 모른다. 지금 정하면 규칙의 모양을 미리 못박는다 (§10 참조) |
| `FLIP_SUMMON` | 같은 이유 — `CHANGE_POSITION` 과 별개 행위인지가 규칙 문제다 |
| 체인 응수 | Phase 2-F |

### 다이렉트 어택을 "대상 없음" 으로 두지 않는다

```python
PlayerAction.attack_directly(actor=0, source=attacker)
# → targets=(ActionTarget.player_target(1),)
```

대상을 비우면 **빠뜨린 것과 의도한 직접 공격이 구분되지 않는다.** 그래서
`ATTACK` 은 대상이 정확히 1개여야 하고, 없으면 구조 오류다.

---

## 3. Target model

파이썬 객체 참조를 담지 않는다. 담으면 Action 이 특정 `GameState` 에 묶이고
직렬화도 replay 도 불가능해진다.

```
ActionTarget
 ├ NONE       — 없음
 ├ INSTANCE   — InstanceId              "저 몬스터"
 ├ PLAYER     — int (0|1)               "상대에게 직접 공격"
 └ ZONE       — (player, Zone, index?)  "내 몬스터 존 3번 칸"
```

**ID 타입을 새로 만들지 않았다.** `InstanceId` · `EffectRef` 는 `engine.ids`
의 것을 그대로 쓰고, 플레이어는 코드베이스 전체가 쓰는 `int` 다
(`PlayerState.player_id`, `CardInstance.owner` / `controller`).
`PlayerId` 를 새로 만들면 기존 모든 곳에 파급된다.

### 존재할 수 없는 자리는 만들지 못한다

```python
ActionTarget.zone_target(0, Zone.HAND, 2)     # ValueError — 패에는 칸이 없다
ActionTarget.zone_target(0, Zone.MZONE, 5)    # ValueError — 칸은 0..4
ActionTarget.zone_target(0, Zone.EMZONE, 1)   # ValueError — EMZ 는 칸이 1개
```

칸 번호 검사는 규칙이 아니라 **표현 가능성**이다. "저기에 놓아도 되는가" 는
여전히 모른다.

---

## 4. Validation boundary

두 층이 있고, Phase 2-A 는 아래층만 갖는다.

| 층 | 질문 | 상태 |
|---|---|---|
| 구조 | 이 Action 이 **말이 되는 모양인가** | 구현됨 |
| 적법성 | 이 행위를 지금 **해도 되는가** | Phase 2-B ~ 2-G |

```python
validator.validate_structure(state, action)  # VALID | INVALID
validator.validate(state, action)            # INVALID | UNKNOWN
```

**Phase 2-A 에서는 어떤 Action 도 `VALID` 를 받지 못한다.** 구조가 멀쩡하면
전부 `UNKNOWN` 이다 — 적법성을 볼 계층이 없기 때문이다. 이것이 정직한 답이다.

### UNKNOWN 은 허가가 아니다

```python
# 위험: UNKNOWN 이 허가로 새어 나간다
if result.validity is not ActionValidity.INVALID:
    execute(action)          # ✗

# 안전: VALID 하나에만 참이다
if result.permits_execution:
    execute(action)          # ✓
```

`ValidationResult.permits_execution` 은 `VALID` 일 때만 참이다. 실수를
주석이 아니라 **구조로** 막는다. 프로젝트 전체가 지켜 온 "`unknown` 을
임의로 참/거짓으로 바꾸지 않는다" 와 같은 태도다.

`UNKNOWN` 결과에는 **무엇이 없어서 모르는지**가 함께 담긴다.

```python
ValidationResult(
    validity=UNKNOWN,
    reason="normal_summon 의 적법성을 판정할 규칙 계층이 아직 없습니다.",
    missing_rule="summon-legality (Phase 2-G)",
)
```

### 참조 무결성은 규칙이 아니다

구조 검사는 `state` 가 주어지면 다음도 본다.

- `source` 인스턴스가 이 듀얼에 실제로 있는가
- 대상 인스턴스가 실제로 있는가
- `effect_ref.card_id` 가 `source` 카드와 **같은 카드인가**

없는 카드를 가리키는 Action 은 어떤 규칙을 붙여도 처리할 수 없다. 그래서
규칙이 아니라 구조다.

---

## 5. GameStateView

### 스냅숏인 이유

살아 있는 읽기 전용 프록시 대신 **만드는 순간 값을 복사한다.**

| | 스냅숏 | 살아있는 프록시 |
|---|---|---|
| 안전 | 원본 참조가 **없다** | 감싸는 것을 하나라도 빠뜨리면 샌다 |
| AI | 관측이 고정 — MCTS 노드 평가 중 흔들리지 않음 | 평가 도중 판이 바뀔 수 있다 |
| 비용 | 만들 때 한 번 | 읽을 때마다 |

전부 frozen dataclass 와 tuple 이라 `view.hand.cards.append(...)` 가 애초에
불가능하다.

```
GameStateView
 ├ viewer, turn_number, turn_player, phase, step
 ├ players: (PlayerView, PlayerView)
 │    ├ player_id, life_points
 │    └ zones: (ZoneView, ...)          존 10개 전부 (EMZ 포함)
 │         ├ zone, owner, visibility, kind, capacity, size, concealed
 │         └ cards: (CardView | None, ...)
 └ winner, result_reason
```

`ZoneView.size` 는 **언제나 정확하다** — 장수는 숨겨진 존에서도 공개다.
`cards` 는 보이는 만큼만 담고, 통째로 가려졌으면 `concealed=True` 다.
"빈 덱" 과 "안 보이는 덱" 을 구분하기 위해서다.

### 노출하지 않는 것

`uses` · `allocator` · `repository` · `rng` · `seed` · `journal`.
AI 가 알 필요가 없고, 내보내면 엔진 내부 구현을 관측에 묶게 된다.

> "이 효과를 이번 턴에 썼는가" 는 **정당한 공개 정보**다. 다만 그것을
> 질의로 내보내는 것은 Condition 계층(Phase 2-B)이 모양을 정한 뒤에 한다.
> `UseRegistry` 자료구조를 그대로 내보내는 것과는 다른 이야기다.

---

## 6. Hidden information

**"보이지만 잠겨 있다" 가 아니라 "값이 아예 없다" 로 숨긴다.** 숨긴 값을
들고 있으면서 플래그로 가리면, 그 플래그를 보지 않는 코드 한 줄이 곧 유출이다.

| 존 | 보는 사람에게 보이는 것 |
|---|---|
| 덱 | **장수만.** 자기 덱도 마찬가지다 |
| 패 · 엑스트라 덱 | 자기 것이면 전부, 상대 것이면 **장수만** |
| 묘지 | 전부. **언제나** |
| 필드 (MZONE/EMZONE/SZONE/FZONE/PZONE) | 앞면은 전부, 뒷면은 **컨트롤러에게만** |
| 제외 | 앞면은 전부, 뒷면 제외는 **제외한 쪽에게만** |

### 뒷면 카드는 정체만 가리고 자리는 남긴다

```python
CardView(instance_id=InstanceId(12), card_id=None, name=None, owner=None, ...)
```

상대의 세트 카드를 "저 자리의 그것" 으로 지목해 공격하거나 파괴할 수 있어야
하므로 `instance_id` 는 남긴다. 반대로 상대의 **패**는 `instance_id` 도 주지
않는다 — 주면 "3턴에 뽑은 그 카드가 아직 손에 있다" 가 드러나고, 그것은 실제
대전에서 알 수 없는 사실이다.

### 앞뒷면보다 존을 먼저 본다

구현 중 실제로 잡힌 버그다. `move_card` 는 표시 형식을 건드리지 않으므로,
덱에서 바로 묘지로 간 카드는 `position` 이 `FACEDOWN` 인 채로 남는다.
앞뒷면만 보고 가리면 **상대 묘지가 통째로 안 보였다.**

묘지에 뒷면은 없다. 그래서 앞뒷면이 공개 여부를 좌우하는 존을 명시한다
(`_FACE_SENSITIVE_ZONES`). 제외 존은 거기 들어 있다 — 뒷면 제외는 실재한다.

---

## 7. Mutation boundary

다음 셋 중 **어느 것도** `GameState` 를 바꾸지 않는다.

- `PlayerAction` 생성
- `GameStateView.from_state()`
- `ActionValidator.validate()` / `validate_structure()`

검증 방법은 Phase 1 이 준 것을 그대로 쓴다.

```python
before = (state.state_hash(), state.allocator.next_value, len(state.uses), ...)
...  # Action 생성 · View 생성 · 검증
assert snapshot(state) == before
```

`state_hash()` 는 판 전체의 결정론적 해시이고, 할당기와 `UseRegistry` 는
해시에 들어가지 않으므로 따로 본다.

---

## 8. owner / controller / actor

세 축이 서로 독립이다.

| | 뜻 | 어디에 |
|---|---|---|
| `owner` | 이 카드가 **누구의 덱**에서 왔는가 | `CardInstance.owner` |
| `controller` | 지금 **누가 쥐고 있는가** | `CardInstance.controller` |
| `actor` | 이 행위를 **누가 시도하는가** | `PlayerAction.actor` |

컨트롤을 빼앗긴 카드로 상대가 공격하는 상황이 `owner=0, controller=1,
actor=1` 로 표현된다. `PlayerAction` 은 카드를 `InstanceId` 로만 가리키므로
`owner` / `controller` 를 복제하지 않는다 — 복제하면 두 곳이 어긋날 수 있다.

---

## 9. analysis.ActionKind 와의 분리

같은 문자열 `normal_summon` 이 양쪽에 있고 **뜻이 다르다.**

| | `analysis.ActionKind.NORMAL_SUMMON` | `PlayerActionKind.NORMAL_SUMMON` |
|---|---|---|
| 뜻 | 효과 해결 중 `Duel.Summon` 이 호출된다 | 플레이어가 소환권을 **쓰기로 고른다** |
| 실측 | 74개 효과 | — |
| 소환권 | 소비할 수도, 안 할 수도 | **반드시** 소비 |

`engine` 은 `analysis` 의 어휘를 가져오지 않는다. Contract E 가 **AST 로**
감시한다 — 문자열 검색이 아니다. `engine/action.py` 의 설명글은 두 어휘가
왜 다른지 설명하려고 `analysis.ActionKind` 를 언급하는데, 그것은 막아야 할
것이 아니라 있어야 할 것이기 때문이다.

---

## 10. 남은 설계 문제

| # | 문제 | 막는 단계 |
|---|---|---|
| 1 | 릴리스 · 코스트 선택이 Action 에 들어가는가, 해결 중의 선택인가 | Phase 2-C (Effect 모델) |
| 2 | `ACTIVATE_CARD` 와 `ACTIVATE_EFFECT` 가 정말 다른 행위인가 | Phase 2-B |
| 3 | 관측이 "이 효과를 이번 턴에 썼는가" 를 어떤 모양으로 답할 것인가 | Phase 2-B |
| 4 | 뒷면 카드의 `counters` 를 상대에게 보여줘야 하는가 (지금은 보여준다) | Phase 2-B |
| 5 | `TEXT_DERIVED` 덱 거부 단위 — 덱 전체인가 카드 하나인가 | **사용자 결정 필요** (ADR-004) |

1 · 2 는 지금 정하면 규칙의 모양을 미리 못박는다. 4 는 실제 유희왕에서
뒷면 카드 위의 카운터가 보이므로 지금 동작이 맞을 가능성이 높지만,
확인 없이 확정하지 않는다.

---

## 11. 구현하지 않은 것 (Phase 2-B 이후)

Action 실행 · Effect · Condition · Chain · Trigger · 소환 절차 ·
공격 처리 · 데미지 계산 · 타이밍 · `StateDelta` · `EventJournal` ·
`ActionGenerator` · AI.

`PlayerActionKind` 에 `NORMAL_SUMMON` 이 있다는 것은 **그 어휘가 있다**는
뜻이지 일반 소환이 된다는 뜻이 아니다.
