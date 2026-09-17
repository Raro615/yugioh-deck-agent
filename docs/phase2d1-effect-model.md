# Phase 2-D-1 — Effect Model + Resolution Contract

**기준 커밋:** `d8d20d6` → 이 문서의 구현
**범위:** 효과가 무엇인지 정의하고, 실행기가 지킬 **계약**을 고정한다.
실행하지 않는다.

```
EffectDefinition                    무엇을 요구하고 무엇을 하는가
  ├ activation  engine.condition    발동 조건
  ├ cost        engine.cost         비용
  ├ targets     TargetBinding       대상 규칙 — **이름별**
  ├ operations  Operation           무엇을 하는가 — 그 **이름을 가리킨다**
  └ provenance  EffectProvenance    어디서 왔는가
        ↓
ResolutionContext                   누가 · 어느 이름에 무엇을 골랐는가
        ↓  EffectResolver.resolve()   ← 계약만
EffectResult
        ✗  StateDelta → GameState — Phase 2-E (ADR-008)
```

---

## 1. 작업 전 검수

### 기존 Effect 관련 구조

| 구조 | 위치 | 정체 |
|---|---|---|
| `EffectSpec` | `core/card_model.py` | Lua 효과 블록의 기계적 명세. **가변**, `index`=`"e1"` |
| `EffectAnalysis` | `analysis/effect_model.py` | 분석 결과. 가변, `raw` 보존 |
| `EffectAction(kind: ActionKind)` | `analysis/effect_model.py` | 효과가 하는 일의 **기록** |
| `EffectCost` · `EffectSelection` | `analysis/effect_model.py` | 비용 · 선택의 기록 |
| `EffectRef(card_id, ordinal)` | `engine/ids.py` | **이미 있는 실행 identity.** frozen |
| `AnalysisStatus` | `core/provenance.py` | LUA_VERIFIED / TEXT_DERIVED / NO_EFFECT / … |
| `CardDefinitionView.effect_count` | `engine/game_state_view.py` | 지목 가능한 효과 개수 |

### 재사용한 것

`EffectRef`(identity 그대로) · `engine.condition.Condition` ·
`engine.cost.CostGroup` / `ChoiceSpec` / `Selection` ·
`engine.validation.ValidationCode` · `engine.game_state_view.GameStateView`.

### 새로 필요했던 것

`EffectDefinition` · `Operation` 어휘 · `TargetSpec` · `EffectProvenance` ·
`ExecutionAvailability` · `ResolutionContext` · `EffectResult` ·
`EffectResolver` 계약.

**`analysis` 에서도 `core` 에서도 아무것도 가져오지 않았다.** AST 검사가 지킨다.

---

## 2. analysis.EffectSpec 과 나눈 이유

| | `core.card_model.EffectSpec` | `engine.effect.EffectDefinition` |
|---|---|---|
| 정체 | Lua 효과 블록을 **읽은 기록** | **실행 계약** |
| 가변성 | 가변 | 불변 |
| identity | `index` = `"e1"` (한 카드 안에서 중복, 4,884장) | `EffectRef(card_id, ordinal)` |
| 조건 · 비용 | 문자열과 분석 dataclass | 실제 엔진 타입 |

`analysis.EffectSpec` → `EffectDefinition` **컴파일러는 만들지 않았다**
(§20). 그 경계를 넘을 때 `TEXT_DERIVED` 차단을 다시 확인해야 한다.

---

## 3. EffectRef 는 그대로 identity 다

```python
EffectDefinition(effect_ref=EffectRef(2511, 1), source_card_id=2511)
EffectDefinition(effect_ref=EffectRef(2511, 1), source_card_id=9999)
# → EffectDefinitionError: 한 효과는 한 카드의 것입니다.
```

`effect_ref.card_id != source_card_id` 는 **구조적으로 거부**한다.
정의가 스스로 어느 카드의 효과인지 모순이기 때문이다.

`EffectSpec.index` 는 어디에도 없다 — 직렬화에 `"e1"` 이 나타나지 않는지
테스트가 확인한다.

---

## 4. Operation — 목적지로 의미를 구분하지 않는다

```
DESTROY  SEND_TO_GRAVE  BANISH  RELEASE  DISCARD
RETURN_TO_HAND  RETURN_TO_DECK  DRAW  CHANGE_LIFE  UNKNOWN
```

파괴 · 묘지로 보내기 · 릴리스는 **전부 묘지로 간다.** 목적지로는 절대
구분할 수 없다. 구분은 `REASON_*` 비트다 (ADR-002).

| Operation | reason | 실측 마스크 |
|---|---|---|
| `DESTROY` | `DESTROY \| EFFECT` | `0x41` |
| `SEND_TO_GRAVE` | `EFFECT` | `0x40` |
| `RELEASE` | `RELEASE` | `0x2` |

**숫자를 코드에 적지 않았다.** `engine/vocabulary.py` 의 원칙 그대로 이름만
들고 있고 `reason_mask()` 가 `constant.lua` 에서 읽는다. 읽을 수 없는
이름은 조용히 0 이 되지 않고 `KeyError` 다 — 0 으로 접으면 "이유 없음" 과
"이름을 못 읽음" 이 같아진다.

### PlayerAction 이 되지 않는다

`DestroyOperation` 에 대응하는 `PlayerActionKind.DESTROY` 는 **없다**
(ADR-001). 흐름은 한 방향이다.

```
PlayerAction.ACTIVATE_EFFECT  →  EffectDefinition  →  Operation.DESTROY
```

`engine/effect/` 는 `engine/action` 을 **가져오지 않는다.** 그래야 Phase
2-D-2 에서 Action 이 Effect 를 볼 때 순환이 생기지 않는다 (§19).

---

## 5. 하는 일이 어느 대상을 쓰는지 말한다

처음 판에서는 `TargetSpec` 과 `operations` 가 따로 있어서 **"대상으로 지정한
몬스터 1장을 파괴한다" 를 표현할 수 없었다.** 파괴가 그 대상을 쓴다는
연결이 어디에도 없었다.

대상에 **이름**을 붙이고 하는 일이 그 이름을 가리킨다.

```python
EffectDefinition(
    targets    = (TargetBinding(PRIMARY_TARGET, TargetSpec.targeting(...)),),
    operations = (CardOperation.destroy(PRIMARY_TARGET),),
)
```

| 조각 | 무엇 | 어디에 |
|---|---|---|
| `TargetRef` | 이름 (`@primary`) | 정의 |
| `TargetBinding` | 이름 ↔ 대상 규칙 | 정의 |
| `TargetSelection` | 이름 ↔ **골라진 카드** | 해결 문맥 |

`TargetRef` 는 이름일 뿐이고 `InstanceId` 가 아니다. **정의에 카드를 박으면
그 정의는 한 판에서 한 번밖에 못 쓴다.** 정의는 "무엇을 대상으로 하는가",
문맥은 "이번에 무엇이 골라졌는가" 다.

### 네 가지 잘못된 연결을 거부한다

생성 단계에서 `EffectDefinitionError` 다.

| 잘못 | 왜 |
|---|---|
| 없는 이름을 가리킨다 | 해결할 수 없다 |
| 대상을 하나도 선언하지 않았는데 가리킨다 | 같은 이유 |
| 같은 이름을 두 번 선언했다 | 어느 규칙인지 정해지지 않는다 |
| 선언한 대상을 아무 일도 쓰지 않는다 | 고르게 해 놓고 쓰지 않는 정의다 |

마지막은 **하는 일을 아직 적지 않았으면(`operations` 가 비었으면) 넘어간다.**
"미완성" 과 "모순" 은 다르고, Phase 2-D-1 이 세운 "적지 않음 ≠ 없음" 원칙
그대로다.

### 대상이 없는 일과 대상을 빠뜨린 일

`DrawOperation` 에는 `target_ref` **칸 자체가 없다.** 없는 것을 `None` 으로
표현하면 "빠뜨렸다" 와 구분되지 않는다. 반대로 `CardOperation` 은
`target_ref` 를 **필수로** 받으므로, 빠뜨린 일은 애초에 만들어지지 않는다.

```python
DrawOperation(1).target_refs                    # ()  — 필요 없다
CardOperation.destroy(PRIMARY_TARGET)           # (@primary,)
CardOperation(OperationKind.DESTROY, None)      # TypeError
```

### 무엇을 아직 기다리는가

문맥은 자기가 무엇을 요구받았는지 모른다. 요구는 정의에 있다.

```python
context.pending_targets(definition)   # (@primary, @second)
```

빈 `Selection` 과 `None` 도 다르다 — 전자는 "고른 결과가 없음", 후자는
"아직 고르지 않음" 이다.

---

## 6. TargetSpec — 없음과 아직 안 고름은 다르다

```
NONE       대상을 요구하지 않는다
TARGETING  규칙상 대상으로 지정한다 — 발동 시점 확정, 무효화·회피의 대상
CHOOSING   고르지만 대상 지정은 아니다 — 해결 시점에 고른다
```

유희왕에서 "대상으로 한다" 와 "고른다" 는 **다른 규칙**이다. `analysis` 도
이미 구분한다 (`EffectAnalysis.targets_card`).

§11 의 구분은 `is_pending()` 이 담는다.

```python
TargetSpec.none().is_pending(Selection())       # False — 기다릴 것이 없다
TargetSpec.targeting(spec).is_pending(None)     # True  — 아직 안 골랐다
```

`NONE` 인데 `ChoiceSpec` 이 붙어 있거나, `TARGETING` 인데 없으면 모순이므로
생성 단계에서 거부한다.

---

## 7. 검증된 의미 ≠ 실행 가능

**ADR-006 을 효과 단위로 구현했다.**

```
EffectProvenance         이 정의가 어디서 왔는가
  source    OFFICIAL_LUA | OFFICIAL_TEXT | HAND_WRITTEN | UNKNOWN
  verified  의미가 공식 근거에서 확인되었는가

ExecutionAvailability    지금 이 엔진 빌드가 실행할 수 있는가
  EXECUTABLE | NO_IMPLEMENTATION | FORBIDDEN_SOURCE | UNVERIFIED | UNKNOWN
```

판정 순서가 중요하다. **출처 금지가 가장 먼저**다.

```python
execution_availability(text_derived_effect, everything_registered)
# → FORBIDDEN_SOURCE.  구현이 등록되어 있어도 실행하지 않는다 (ADR-004)

execution_availability(official_lua_effect)
# → NO_IMPLEMENTATION.  공식 스크립트에서 나왔어도 구현이 없으면 못 한다
```

`permits_execution` 은 `EXECUTABLE` 하나에만 참이다 —
`if availability is not FORBIDDEN_SOURCE:` 로 나머지가 허가로 새는 것을 막는다.

`EffectImplementationLookup` 은 **Protocol 로만** 두었다. 레지스트리 자체는
Phase 2-D-2 다 (§16). 기본값 `EmptyImplementationLookup` 은 아무것도 없다고
답하는데, 그것이 지금의 사실이다.

---

## 8. 해결 계약

```python
class EffectResolver(Protocol):
    def resolve(self, definition, context, view) -> EffectResult: ...
```

구현이 **반드시** 지킬 것:

1. `GameStateView` 를 받는다. `GameState` 를 받지 않는다
2. `execution_availability` 가 `EXECUTABLE` 이 아니면 **아무것도 하지 않고** 그 사실을 돌려준다
3. `RESOLVED` 가 아닌 결과를 돌려줄 때 판은 **바뀌지 않은 상태**여야 한다 — 반쯤 실행해 놓고 실패를 알리지 않는다
4. 같은 정의 · 문맥 · 관측이면 같은 결과

### 지금 유일한 실행기

`UnimplementedResolver` 는 언제나 실패를 돌려주고 판을 바꾸지 않는다.
자리표시가 아니라 **지금 엔진의 정직한 상태**다 — 등록된 구현이 하나도
없다. 이것이 있어서 계약이 지켜지는지 실제로 테스트할 수 있다.

`EffectResult.__bool__` 은 예외를 던진다. `if result:` 로 실패가 성공으로
읽히는 길을 막는다. `changed_state` 는 `RESOLVED` 일 때만 참이고, 지금은
어떤 실행기도 그 값을 내지 않으므로 **언제나 거짓**이다.

---

## 9. ResolutionContext

```python
ResolutionContext(effect_ref, controller, source=None, targets=Selection(),
                  cost_selections=())
```

값 타입만 담는다 — `CardInstance` 나 `GameState` 를 담으면 문맥이 특정 판에
묶이고 직렬화도 replay 도 불가능해진다.

조건 계층과 타입을 합치지 않고 `condition_context()` 로 **변환**한다.
조건은 비용 선택을 알 필요가 없다.

**체인 · 트리거 · 타이밍은 자리도 만들지 않았다.** 그 시스템이 없는데 칸을
비워 두면 모양을 미리 못박게 된다.

---

## 10. 실제 구현된 Operation

| Operation | 생성자 | 비고 |
|---|---|---|
| `DESTROY` | `CardOperation.destroy(ref)` | `REASON_DESTROY \| EFFECT` |
| `SEND_TO_GRAVE` | `CardOperation.send_to_grave(ref)` | 파괴가 **아니다** |
| `BANISH` | `CardOperation.banish(ref)` | |
| `RELEASE` | `CardOperation.release(ref)` | `REASON_RELEASE` |
| `DISCARD` | `CardOperation.discard(ref)` | |
| `RETURN_TO_HAND` | `CardOperation.return_to_hand(ref)` | |
| `RETURN_TO_DECK` | `CardOperation.return_to_deck(ref)` | |
| `DRAW` | `DrawOperation(count, who)` | |
| `CHANGE_LIFE` | `LifeChangeOperation(delta, who)` | |
| `UNKNOWN` | `UnimplementedOperation(rule)` | 표현 불가를 솔직하게 |

---

## 11. 의도적으로 미구현

| 영역 | 어떻게 |
|---|---|
| 실제 효과 실행 · 상태 변경 | 계약만. `UnimplementedResolver` 가 언제나 실패 |
| `EffectRegistry` | `Protocol` 만 (§16) |
| `analysis.EffectSpec` → `EffectDefinition` 컴파일러 | 없음 (§20) |
| `StateDelta` · `EventJournal` | ADR-008 이 Phase 2-E 로 미룸 |
| 체인 · 트리거 · 타이밍 | 문맥에 자리도 없음 |
| 소환 · 표시 형식 변경 · 수치 변경 · 무효화 | `UnimplementedOperation` |
| "효과 데미지" 와 "효과로 LP 감소" 구분 | 데미지 처리 계층이 없어 남겨 둠 |
| 전투 · 비용으로 인한 `REASON_*` | 그 경로가 생길 때 함께 |
| 195장의 공유 라이브러리 효과 | 건드리지 않음 |
| 여러 일의 순서 · 동시 처리 · 조건 분기 | `operations` 는 순차 목록뿐 (STRUCTURAL-8) |
| "존 전체를 대상" (고르지 않는 일괄 처리) | `TargetSpec` 이 담지 못함 (STRUCTURAL-10) |

---

## 12. 의존 방향

```
engine.validation · engine.ids · engine.vocabulary
        ↓
engine.game_state_view
        ↓
engine.condition
        ↓
engine.cost
        ↓
engine.effect          ← 아래를 의존한다. 위는 이쪽을 모른다

engine.action · engine.action_validation   ← effect 를 아직 모른다
```

`engine.effect` 가 `engine.action` 을 가져오지 않는 것을 테스트가 지킨다.
Phase 2-D-2 에서 Action 검증이 Effect 를 보게 될 때 순환이 생기지 않는다.
