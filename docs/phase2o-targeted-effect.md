# Phase 2-O — Targeted Effect Integration

기준 커밋: `0e0aab9` (Phase 2-N Target Selection Core)

```
engine/effect/library.py   싸이크론 (5318639) e[0]
    ↓  definition_registry()            정의
    ↓  TargetResolver.candidates()      후보          (2-N)
    ↓  부르는 쪽이 고른다                 selected_target
    ↓  TargetResolver.validate()        적법한가       (2-N)
    ↓  DestructionRuling                파괴해도 되는가 (2-M)
    ↓  EffectExecutor.execute()         실행          (2-D-2)
    ↓  ZoneMoved(operation=DESTROY)     Delta         (2-L)
    ↓  TimingEvent.from_delta()         Event         (2-J)
    ↓  EventJournal                     역사          (2-K)
```

이번 단계는 **새 계층을 만들지 않는다.** 이미 있는 계층을 실제 카드 하나로
끝까지 이어 붙이고, 이어 붙였을 때도 구분이 하나도 무너지지 않는지 본다.

---

## 1. 카드 선택 — 왜 싸이크론인가

| 요구 (§2) | 싸이크론이 만족하는 근거 |
|---|---|
| `LUA_VERIFIED` | `c5318639.lua` 가 저장소에 있다 |
| 대상 지정이 필요하다 | `e1:SetProperty(EFFECT_FLAG_CARD_TARGET)` |
| 단순하다 | 효과 블록이 하나(`e1`), 비용 없음, 조건 없음 |
| `DESTROY` 로 이어진다 | `Duel.Destroy(tc,REASON_EFFECT)` |
| 이 엔진의 계층으로 옮길 수 있다 | 자리 · 주인 · 장수 · 필터 전부 기존 타입으로 표현된다 |

- **card_id**: `5318639`
- **EffectRef**: `EffectRef(5318639, 0)` — 스크립트의 효과 블록이 하나뿐이다
- **한국어 카드명**: 싸이크론 (`data/` 의 공식 DB 에서 읽었다. 손으로 옮기지
  않았다)
- **타입**: `['SPELL', 'QUICKPLAY']`

후보로 같이 본 카드들과 탈락 이유:

| 카드 | 탈락 이유 |
|---|---|
| 블랙홀 (53129443) | "필드의 몬스터 **전부**" — `TargetSpec` 이 담지 못한다 (STRUCTURAL-10). 이미 `executable=False` 로 실려 있다 |
| 욕망의 항아리 (55144522) | 대상이 없다 |
| 은혜의 단비 (66719324) | 대상이 없다 |

---

## 2. 스크립트의 어느 줄이 정의의 어디가 되었는가

```lua
e1:SetProperty(EFFECT_FLAG_CARD_TARGET)
function s.filter(c) return c:IsSpellTrap() end
function s.target(e,tp,...,chkc)
  if chkc then return chkc:IsOnField() and s.filter(chkc) and chkc~=e:GetHandler() end
  ...
  local g=Duel.SelectTarget(tp,s.filter,tp,LOCATION_ONFIELD,LOCATION_ONFIELD,1,1,e:GetHandler())
end
function s.activate(e,tp,...)
  local tc=Duel.GetFirstTarget()
  if tc and tc:IsRelateToEffect(e) then Duel.Destroy(tc,REASON_EFFECT) end
end
```

| Lua | 정의 |
|---|---|
| `EFFECT_FLAG_CARD_TARGET` | `TargetSpec.targeting(...)` — 고르기가 아니라 **대상 지정** |
| `s.filter = c:IsSpellTrap()` | `require=IsSpellTrap()` |
| `LOCATION_ONFIELD, LOCATION_ONFIELD` | `zones=FIELD_ZONES`, `owner=None` (양쪽) |
| `SelectTarget(..., 1, 1, ...)` | `minimum=1, maximum=1` |
| `..., e:GetHandler())` (마지막 인자) · `chkc~=e:GetHandler()` | `exclude_source=True` |
| `Duel.Destroy(tc, REASON_EFFECT)` | `CardOperation.destroy(PRIMARY_TARGET)` |

**옮기지 못한 것도 적는다.**

| Lua | 왜 못 옮겼는가 |
|---|---|
| `tc:IsRelateToEffect(e)` | 대상이 발동 후 자리를 옮겼다 돌아왔는지 추적하는 계층이 없다 (STRUCTURAL-50) |
| `e1:SetHintTiming(...)` · `EVENT_FREE_CHAIN` | 퀵플레이 발동 타이밍은 발동 계층의 일이고, 이 목록은 **해결될 때 무엇을 하는가**만 말한다 |
| `chk==0` 의 `IsExistingTarget` | 같은 사실을 `TargetResolver.availability` 가 답한다. 발동 조건 칸에 또 적으면 한 사실이 두 곳에 갈린다 — `activation` 은 `None` 으로 뒀다 |

---

## 3. 새로 만든 것 — 조건 하나

`engine/condition/model.py` 에 `IsSpellTrap` 을 더했다.

```python
class IsSpellTrap(Condition):
    def evaluate(self, view, context):
        definition, _ = _resolve_definition(view, context, self.instance)
        if definition is None:
            return ConditionResult.UNKNOWN
        return ConditionResult.from_bool(definition.is_spell or definition.is_trap)
```

`NotMonster` 로 대신하지 **않았다.** 필드 위에서는 값이 같지만 같은 질문이
아니다 — 저쪽은 "몬스터가 아니다" 이고 이쪽은 "마법이거나 함정이다" 다.
원문이 `IsSpellTrap` 이라고 적혀 있으므로 그대로 적었다. 정의를 못 읽으면
`UNKNOWN` 인 것은 다른 카드 조건과 같다.

`CardDefinitionView` 는 `is_spell` · `is_trap` 을 이미 들고 있었다. 새 관측
필드는 만들지 않았다.

---

## 4. `exclude_source` — Phase 2-N 직전에 추가한 한 칸

`CandidateSource.exclude_source: bool = False`.

`chkc~=e:GetHandler()` 를 표현한다. 싸이크론도 필드의 마법 카드이므로,
이것이 없으면 **자기 자신을 대상으로 고를 수 있게 된다.**

기본값이 거짓인 이유는 대부분의 효과가 자기 자신을 가리지 않기 때문이고,
**적지 않은 것을 "뺀다" 로 읽으면 안 되기** 때문이다.

`CandidateResolver` 가 `context.source` 와 비교해서 뺀다. 그 `source` 는
`ResolutionContext.source` — 발동한 카드 — 에서 온다.

---

## 5. 실행 흐름 12 단계 (테스트가 그대로 따라간다)

| # | 단계 | 누가 |
|---|---|---|
| 1 | 정의 조회 | `definition_registry()` (테스트가 정의를 만들지 않는다) |
| 2 | 실행 권위 | `availability()` → `EXECUTABLE` |
| 3 | 후보 수집 | `TargetResolver.candidates` |
| 4 | **선택** | 테스트가 값으로 준다 (`selected_target = ...`) — 엔진이 고르지 않는다 |
| 5 | 대상 검증 | `TargetResolver.validate` → `LEGAL` |
| 6 | 파괴 판정 | `DestructionRuling.may_be_destroyed` |
| 7 | 계획 | `EffectExecutor._plan` — 여기까지 판은 그대로다 |
| 8 | 적용 | `GameState.move` |
| 9 | 자리 이동 | `SZONE → GRAVE` |
| 10 | Delta | `ZoneMoved(operation=DESTROY, reason_names=('DESTROY',...))` |
| 11 | Event | `TimingEvent.from_delta` → `CARD_MOVED` + `DESTROY` |
| 12 | Journal | `EventJournal` 에 `effect_ref` · `source` · `applied` · `deltas` |

---

## 6. 실패가 판을 건드리지 않는다 — 8 가지

전부 `state_hash()` 가 그대로이고 `applied == ()` · `deltas == ()` 다.

| 고른 것 | 결과 | code |
|---|---|---|
| 상대 몬스터 | `INVALID_TARGET` | `CANDIDATE_NOT_ELIGIBLE` |
| **싸이크론 자신** | `INVALID_TARGET` | `CANDIDATE_NOT_ELIGIBLE` |
| 패의 마법 카드 | `INVALID_TARGET` | `CANDIDATE_NOT_ELIGIBLE` |
| 상대의 세트 카드 | `UNCHECKED_TARGET` | `INFORMATION_UNAVAILABLE` |
| 아무것도 고르지 않음 | `INVALID_TARGET` | `TOO_FEW_SELECTED` |
| 2장 | `INVALID_TARGET` | `TOO_MANY_SELECTED` |
| 고른 뒤 필드를 떠난 카드 | `INVALID_TARGET` | `CANDIDATE_NOT_ELIGIBLE` |
| 존재하지 않는 `InstanceId` | `UNCHECKED_TARGET` | `HIDDEN_CARD` |

**모르는 것과 틀린 것을 합치지 않는다.** 세트 카드와 존재하지 않는 카드는
`UNKNOWN` 이고, 정보가 생기면 답이 달라질 수 있다. 나머지는 확정된 오답이다.

`build_executor()` 에 `destruction` 을 주지 않으면 **적법한 대상이어도
파괴되지 않는다** — `UNCHECKED_RULES` 이고 판은 그대로다. 목록에 실렸다는
사실이 파괴 판정을 대신하지 못한다 (ADR-006 · STRUCTURAL-47).

---

## 7. 지키고 있는 구분

| 구분 | 이번 단계에서 어떻게 지켜지는가 |
|---|---|
| 대상 지정 ≠ 고르기 | `TargetRequirement.TARGETING` 으로 실렸다 |
| `UNKNOWN` ≠ 허가 | 세트 카드는 `UNCHECKED_TARGET`, 판정기 없는 파괴는 `UNCHECKED_RULES` |
| `UNKNOWN` ≠ `ILLEGAL` | 둘이 다른 `ResolutionStatus` 로 나온다 |
| 파괴 ≠ 묘지로 보내기 | Delta · Event · Journal 어디에서도 `DESTROY` 가 남는다 |
| 정의 ≠ 인스턴스 | 정의에 `InstanceId` 가 없다 (테스트가 소스에서 확인한다) |
| Owner ≠ Controller | 파괴된 뒤에도 `owner` 가 그대로다 |
| AI 판단 ≠ 엔진 판정 | 고르는 코드가 라이브러리에도 대상 계층에도 없다 |

---

## 8. 테스트

`tests/engine/test_targeted_effect.py` — 함수 **40개**, 실행 **43건**
(`D` 묶음에 `parametrize` 4갈래가 있다). 전부 통과.

| 묶음 | 함수 | 보는 것 |
|---|---|---|
| A. 정의 | 6 | 스크립트가 말한 것만 적혀 있는가 |
| B. 후보 수집 | 6 | 필터 · 자리 · 자기 제외가 실제로 걸러지는가 |
| C. end-to-end | 4 | 12 단계를 실제로 통과하는가 |
| D. 대상 실패 | 6 | 판을 건드리지 않는가 |
| E. 파괴 판정 | 4 | `UNKNOWN` 이 허가로 새지 않는가 |
| F. 실행 권위 | 3 | `TEXT_DERIVED` · 미등록이 막히는가 |
| G. 가려진 정보 | 3 | 카드 정체가 새지 않는가 |
| H. 결정론 · 경계 | 8 | 같은 판 → 같은 답, 새 계층 없음 (AST) |

전체 회귀: **1935 passed, 4 skipped** (직전 1892 + 43, 기존 테스트 수정 0건).

---

## 9. 남은 것 (기록만 — 이번 단계에서 고치지 않는다)

- **STRUCTURAL-50** — `IsRelateToEffect` 가 없다. 실행 직전 재검증은 자리를
  벗어난 대상을 잡지만, **같은 자리로 돌아온 카드**를 구분하지 못한다.
- **STRUCTURAL-51** — 발동 시점에 대상을 확정하고 해결까지 들고 가는 계층이
  없다. 지금은 `ResolutionContext` 가 해결 시점에 선택을 통째로 받는다.
  대상 지정과 해결 사이에 끼어드는 효과를 표현할 수 없다.
- **STRUCTURAL-52** (새로 관찰) — `LOCATION_ONFIELD` 를 `FIELD_ZONES` 로
  옮겼다. `PZONE` 의 펜듈럼 카드가 `IsSpellTrap` 에 `TRUE` 가 되는지는
  공식 근거로 확인하지 않았다 — 이 엔진에 펜듈럼 존의 카드를 놓는 경로가
  아직 없어서 시험할 대상 자체가 없다.
- **STRUCTURAL-15 (계속)** — `unchecked` 는 `CandidateSet` 까지만 올라오고
  비용 검증기는 아직 그것을 읽지 않는다.
- **STRUCTURAL-7 (계속)** — `analysis.EffectSpec → EffectDefinition` 컴파일러가
  없다. 목록은 여전히 손으로 쓴다. 지금 실행 가능한 카드는 **3장**이다
  (욕망의 항아리 · 은혜의 단비 · 싸이크론).
