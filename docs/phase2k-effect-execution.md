# Phase 2-K — Effect Execution Core

기준 커밋: `344d31a` (Phase 2-J)

```
ChainLink(effect_ref)
    ↓  ChainResolver.resolve_top()        무엇을 언제 (2-F-2)
    ↓  EffectDefinitionRegistry           그 효과가 무엇을 하는가
    ↓  EffectExecutor.execute()           실제로 판을 바꾼다 (2-D-2)
GameState 변경  +  StateDelta
    ↓  EventReader.read()                 사건으로 (2-J)
ObservedEvent → TriggerCollection
```

---

## 1. 작업 전 검수 — 무엇이 실제로 비어 있었는가

조사 결과 **배관은 전부 이미 있었다.**

| 이미 있던 것 | 상태 |
|---|---|
| `EffectExecutor` (2-D-2) | 계획-후-적용, 권위 검사, Delta · Journal 기록까지 완성 |
| `EffectDefinition` · `EffectProvenance` · `execution_availability` (2-D-1) | 완성 |
| `EffectImplementationRegistry` · `EffectDefinitionRegistry` | 완성 |
| `ChainResolver` (2-F-2) | 링크 → 정의 → 실행기 호출까지 완성 |
| `EventReader` · `EventPipeline` (2-J) | `.deltas` 를 든 결과면 무엇이든 읽는다 |

비어 있던 것은 하나였다:

> **`engine/` 안에 `EffectDefinition` 이 단 하나도 없었다.**
> (`grep -rn "EffectDefinition(" engine/` → 0건, 테스트에만 존재)

그래서 실행기는 "구현이 등록되어 있지 않다" 만 돌려줄 수 있었고, 카드 효과가
판을 바꾸는 경로는 **테스트 안에서만** 존재했다.

이번 단계가 만든 것은 그 목록 하나다. **새 Effect 시스템도, 병렬 실행기도
만들지 않았다.** `executor.py` · `definition.py` · `chain.py` ·
`event_pipeline.py` 는 한 줄도 고치지 않았다.

---

## 2. 실제로 판을 바꾸는 코드 경로

테스트가 통과했다는 말이 아니라, 코드에서 확인한 경로다.

| 단계 | 파일 · 줄 |
|---|---|
| 링크 선택 | `engine/chain.py:583` `link = chain.top` |
| 정의 조회 | `engine/chain.py:585` `definition_for(link)` |
| 실행 호출 | `engine/chain.py:596` `self._executor.execute(...)` |
| 권위 확인 | `engine/effect/executor.py:376` `execution_availability(...)` |
| **판 변경** | `engine/effect/executor.py:578` `state.draw(step.player, step.amount)` |
| 변화 기록 | 같은 함수가 `CardDrawn` 을 만든다 |
| 기록 남김 | `executor.py` `self._journal.record(...)` |

실측: 욕망의 항아리를 해결하면 덱 10장 → 8장, 패 0장 → 2장, `state_hash()`
가 달라지고 `CardDrawn` 두 개가 나온다.

---

## 3. 구현한 효과 — 두 장, 그리고 왜 두 장뿐인가

### 욕망의 항아리 (55144522) — **실행된다**

```lua
-- c55144522.lua
function s.activate(e,tp,eg,ep,ev,re,r,rp)
    local p,d=Duel.GetChainInfo(0,CHAININFO_TARGET_PLAYER,CHAININFO_TARGET_PARAM)
    Duel.Draw(p,d,REASON_EFFECT)
end
```

`d` 는 `Duel.SetTargetParam(2)` 로 정해진 2, `p` 는 발동한 플레이어다.
대상도 비용도 없고, 해석의 여지가 없다. →
`DrawOperation(count=2, who=CONTROLLER)`.

발동 조건은 `s.target` 의 `Duel.IsPlayerCanDraw(tp,2)` 중 **덱 장수 부분만**
옮겼다 (`ZoneCountAtLeast(CONTROLLER, DECK, 2)`). "드로우를 막는 효과" 는 이
엔진에 없으므로 그 부분은 확인하지 않는다 — 이 조건은 **필요조건이지
충분조건이 아니다.** 모듈 주석에 그렇게 적었다.

### 블랙홀 (53129443) — **실행되지 않는다**

의미는 분명하다 (`Duel.Destroy(sg, REASON_EFFECT)`, `sg` = 양쪽 몬스터 존
전체). 그런데 옮길 수 없는 것이 둘이다.

1. `OperationKind.DESTROY` 를 실행기가 지원하지 않는다. 파괴는 묘지로
   보내기와 **다르고** (내성 · 대체 · "파괴되었을 때"), 그 계층이 없다.
   목적지가 묘지라는 이유로 구현했다고 말하지 않는다 (ADR-002).
2. "필드의 몬스터 **전부**" 를 `TargetSpec` 이 담지 못한다 (STRUCTURAL-10).

그래서 **하는 일을 적지 않은 채로** 싣고 `executable=False` 로 둔다. 빼
버리면 "왜 못 하는가" 가 사라진다.

### 왜 더 늘리지 않았는가

세 번째 후보들(천사의 자비 · 고블린의 돌격부대 …)은 전부 **대상 선택**이
필요하다. 대상 선택 계층은 이번 단계의 범위가 아니고 (§11), 없는 것을
있는 척 채우면 이 목록의 신뢰가 사라진다. Infrastructure 검증에는 한 장이면
충분하다는 것이 §7 의 요구이기도 하다.

---

## 4. 근거를 함께 들고 다닌다

`LibraryEntry` 는 정의만 담지 않는다.

```python
LibraryEntry(
    definition=...,
    lua_file="c55144522.lua",
    lua_excerpt="Duel.Draw(p,d,REASON_EFFECT)  -- d = Duel.SetTargetParam(2)",
    executable=True,
)
```

근거 없이 적힌 정의는 검증된 의미가 아니라 **추측**이다. 테스트가
`lua_file` 이 실제로 존재하는 파일인지 확인한다.

`__post_init__` 이 네 가지를 거부한다.

- 출처가 금지인데 `executable=True` (ADR-004)
- 검증되지 않았는데 `executable=True`
- 하는 일이 비었는데 `executable=True` — "아무 일도 없었는데 해결됐다" 가 된다
- 실행하지 않으면서 이유를 적지 않음

---

## 5. 세 가지 상태

| 상태 | 목록의 예 | `execution_availability` |
|---|---|---|
| `TEXT_DERIVED` | (싣지 않는다) | `FORBIDDEN_SOURCE` — 구현이 있어도 실행 안 함 |
| `LUA_VERIFIED`, 구현 없음 | 블랙홀 | `NO_IMPLEMENTATION` |
| `LUA_VERIFIED` + 구현 | 욕망의 항아리 | `EXECUTABLE` |

셋 다 테스트가 확인한다. 특히 `TEXT_DERIVED` 는 **구현을 등록해 놓고도**
실행되지 않으며 `state_hash()` 가 그대로다.

`definition_registry()` 와 `implementation_registry()` 는 **다른 목록**이다.
블랙홀은 앞쪽에만 있다 — 정의가 있다고 실행할 수 있는 것이 아니다 (ADR-006).

---

## 6. 책임 경계

| | 하는 일 |
|---|---|
| `ChainResolver` | **무엇을 언제** — 링크를 역순으로 고르고 실행기에게 넘긴다 |
| `EffectExecutor` | **어떻게** — 권위 · 조건 · 대상을 보고 판을 바꾼다 |
| `library.py` | **무엇을** — 어떤 효과가 무슨 일을 하는지 |

테스트가 AST 로 확인한다.

- `chain.py` 에 `move` · `draw` · `change_life` · `create_instance` 호출이 없다
- `executor.py` 가 `engine.chain` · `engine.priority` · `engine.timing` 을
  가져오지 않는다
- `library.py` 가 `chain` · `trigger` · `event_pipeline` ·
  `action_execution` 을 가져오지 않는다 — 효과 계층이 자기 위를 부르면
  방향이 뒤집힌다. 그래서 `build_chain_resolver()` 같은 편의 함수를 **만들지
  않았다.**

AI 는 어디에도 없다. `library.py` 에 `choose` · `score` · `policy` 같은
이름이 없음을 테스트가 확인한다 — "이 효과를 쓸 것인가" 는 나중의 질문이고,
목록은 "쓰기로 했다면 무엇이 일어나는가" 만 안다.

---

## 7. 사건 통로

`EffectResult` 는 `.deltas` 를 들고 있으므로 2-J 의 `EventReader` 가
**그대로 읽는다.** 새 `EventKind` 도, 새 Event 클래스도, EventBus 도 만들지
않았다.

```python
events = EventReader(view).read(result, actor=MINE)
# → CARD_DRAWN 두 개, sequence 0 · 1
```

`actor` 를 인자로 받는 이유는 `EffectResult` 가 발동자를 들고 있지 않기
때문이다 — 그것은 `ResolutionContext.controller` 에 있다. 파이프라인이
`ResolutionContext` 를 알게 하지 않으려고 인자로 받는다.

---

## 8. 실패 안전성

실패 경로 전부에서 `state_hash()` 가 그대로다 (테스트로 확인).

| 실패 | 결과 |
|---|---|
| 출처 금지 | `ResolutionStatus.FORBIDDEN` |
| 구현 없음 | 실행 안 함 |
| 정의 없음 (체인) | `INVALID_CHAIN_LINK`, 체인이 진행하지 않는다 |
| 덱이 모자람 | 조건이 거짓 — **한 장도 뽑지 않는다** |

새 트랜잭션 · 롤백 프레임워크를 만들지 않았다 (§10). 실행기의 계획-후-적용이
이미 부분 변경을 막는다. 롤백은 여전히 ADR-008 의 TODO 다.

---

## 9. 결정론

같은 판 + 같은 효과 → 같은 해시, 같은 `canonical_state()`. 복제본에서
해결해도 원본은 그대로다. 무작위를 쓰는 효과는 싣지 않았다.

---

## 10. 구현하지 않은 것

§16 이 금지한 것 전부. 특히:

- 대상 선택 · 대상 적법성
- 파괴 · 보내기 · 버리기 · 릴리스 · 제외 · 되돌리기의 완전한 의미
- 지속 효과 · 대체 효과 · 데미지 스텝
- `analysis` → `EffectDefinition` 컴파일러 (STRUCTURAL-7)
- 자동 체인 생성 · 전체 게임 루프
- AI · 덱 빌딩 · 검색 변경

---

## 11. 새로 발견된 것

- **🟡 DETAIL** — 출처 금지로 거절할 때 `EffectResult.code` 가
  `RULE_NOT_IMPLEMENTED` 다. 금지를 가리키는 `EXECUTION_FORBIDDEN` 이
  나중(2-F-1)에 생겼는데 실행기(2-D-2)가 아직 쓰지 않는다. **판정 자체는
  정확하다** (`status` 가 `FORBIDDEN`, `missing` 이 무엇이 없는지 말한다) —
  코드만 덜 구체적이다. 기존 API 를 건드리지 않으려고 이번 단계에서 고치지
  않았다.
- **🟠 STRUCTURAL-44** — 목록이 14,127장 중 2장이다. 컴파일러가 없으면
  손으로 늘리는 수밖에 없고, 컴파일러를 만들 때 `TEXT_DERIVED` 차단을 다시
  확인해야 한다 (STRUCTURAL-7 과 같은 뿌리).

---

## 12. 앞으로 만들면 좋은 것

1. **대상 선택 계층** — 목록을 늘리는 데 가장 먼저 필요한 것.
2. **파괴 의미** — 블랙홀을 실을 수 있게 되는 지점.
3. `analysis` → `EffectDefinition` 컴파일러 (STRUCTURAL-7).
4. `EXECUTION_FORBIDDEN` 코드 정리 (위 DETAIL).
