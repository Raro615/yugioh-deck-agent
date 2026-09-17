# Phase 2-C — Cost & Choice System

**기준 커밋:** `a498b32` → 이 문서의 구현
**범위:** 비용과 선택을 **표현하고 검증**한다. 치르지도 고르지도 않는다.

```
CostGroup / Cost
      ↓  choice_spec()
ChoiceSpec
      ↓  CandidateResolver(view).resolve(spec, context)
CandidateSet          확실한 후보 · 판정 불가 · 왜 모르는가
      ↓  플레이어가 고른다   ← 이 계층 **밖**
Selection
      ↓  SelectionValidator(view).validate(...)
ValidationResult
      ✗  지불 없음 — Phase 2-D 이후
```

---

## 1. 작업 전 검수

### 현재 구조

`analysis/effect_model.py` 에 이미 비용과 선택이 있다.

| 있는 것 | 정체 |
|---|---|
| `CostKind` (19종) | Lua 비용 함수를 **읽은 기록**의 분류 |
| `EffectCost(kind, raw, constraint)` | 가변 dataclass, `raw` 에 Lua 원문 |
| `EffectSelection(locations, constraint, min_count, max_count, raw)` | 가변, `raw` 보존 |
| `CardConstraint` | "어떤 카드" 필터. 가변, `raw_predicates` 보존 |

`ConditionNode` 와 같은 성격이다 — **평가하지 않는다.** `analysis` 전체에
평가기가 없다.

### 재사용 가능한 구조

| 재사용한 것 | 어디서 |
|---|---|
| `ConditionEvaluator` · `Condition` | 후보를 거르는 규칙 평가 (§14) |
| `ValidationResult` · `ValidationCode` | 판정 어휘 (§15) |
| `InstanceId` · `EffectRef` · `Zone` · `PlayerRef` | 안정적인 식별자 (§8) |
| `GameStateView` · `CardDefinitionView` | 관측 경계 (§9) |

`analysis` 에서는 **아무것도 가져오지 않았다.** 이유는 §2.

### 새로 필요한 구조

`Cost` · `CostGroup` · `ChoiceSpec` · `CandidateSource` · `CandidateSet` ·
`Selection` · `CandidateResolver` · `CostValidator` · `SelectionValidator`.

### 함께 정리한 것

Phase 2-B-2 가 남긴 **STRUCTURAL-4** 를 해결했다. 검증기 안에 숨어 있던
`_ControllerIs` · `_InAnyZone` · `_NotMonster` 를 `engine/condition/` 으로
옮겨 공개했다 — 후보를 거를 때 같은 질문을 하게 되었고, 두 곳에서 각자
만들면 같은 질문에 다른 답이 나올 수 있기 때문이다.

판정 타입(`ActionValidity` · `ValidationCode` · `ValidationResult`)도
`engine/validation.py` 로 옮겼다. 비용 계층이 `action_validation` 을
가져오게 두면, Phase 2-D 에서 Action 이 비용을 참조할 때 순환이 생긴다.

---

## 2. analysis 와 나눈 이유

| | `analysis.CostKind` / `EffectCost` | `engine.cost` |
|---|---|---|
| 정체 | **Lua 를 읽은 기록** | **실행 전 검증용** |
| 가변성 | 가변 | 불변 |
| 원문 | `raw` 보존 | 없음 |
| 판정 | 없음 | 관측을 받아 답한다 |

이름이 겹치는 것(`CostKind`)을 피하려고 **열거형 대신 클래스를 나눴다.**
조건 계층이 `BoolOp.LEAF` 를 쓰지 않고 `And` / `Or` / 술어를 따로 둔 것과
같은 이유다.

---

## 3. Cost 구조

```
Cost
 ├ CardCost(kind, zones, count, maximum, who, require)
 │    .release()  .discard()  .banish()  .send_to_grave()
 ├ LifeCost(amount, who)
 └ UnimplementedCost(rule)

CostGroup(costs)        AND 관계
```

### 의미를 합치지 않는다

`CostSemantics` 가 구분을 담는다.

```
RELEASE  DISCARD  BANISH  SEND_TO_GRAVE  DETACH  PAY_LIFE  UNKNOWN
```

릴리스와 묘지로 보내기는 둘 다 묘지로 가지만 **다른 사건**이다.
"릴리스되었을 때" 트리거는 묘지로 보내진 몬스터로 발동하지 않는다.

**`DESTROY` 가 없다.** 유희왕에서 카드를 파괴하는 것은 효과의 결과이지
발동 비용이 아니고 — `analysis.CostKind` 에도 없다 — 여기에 넣으면
ADR-002 의 `Destroy ≠ Send to Graveyard` 가 비용 쪽에서 무너진다.

### 다중 비용

`CostGroup` 은 **AND 만** 표현한다. "둘 중 하나를 고른다" 는 넣지 않았다 —
어느 쪽을 고르느냐가 이후 처리까지 갈라지므로, 그 갈래를 담을 구조가 생긴
뒤에 다룬다. 지금 흉내 내면 모양을 미리 못박는다.

---

## 4. 후보와 선택은 다른 것이다

```python
CandidateSet(eligible=(#3, #7, #9), undecided=(#12,), reasons=("#12: 뒷면...",))
Selection(chosen=(#7,))
```

후보는 **관측에서 계산된 결과**이고 선택은 **플레이어가 만든 결과**다.
한 타입으로 합치면 "고를 수 있었다" 와 "골랐다" 가 섞이고 검증할 대상이
사라진다.

### 후보가 셋으로 갈린다

| | 뜻 |
|---|---|
| `eligible` | 확실히 후보다 |
| `undecided` | 후보인지 **모른다** — 조건이 정체를 요구하는데 뒷면이다 |
| `reasons` | 왜 모르는가. 조건 계층이 한 말 그대로 |

`undecided` 를 `eligible` 에 넣으면 못 치를 비용을 치를 수 있다고 하게 되고,
버리면 치를 수 있는 비용을 못 치른다고 하게 된다. 그래서 따로 센다.

### 정렬

`(컨트롤러, PLAYER_ZONES 순, sequence, instance_id)`. 집합이나 딕셔너리의
순회 순서에 의존하지 않으므로, 같은 관측이면 언제나 같은 목록이 나온다.

---

## 5. 판정

### 비용

```
확실한 후보만으로 최소를 채울 수 있다        → VALID
미확정까지 다 세어도 모자란다                → INVALID  (확실하다)
그 사이                                       → UNKNOWN
```

가운데가 핵심이다. 미확정을 전부 후보라고 쳐도 모자라면 **모르는 것이
있어도 확실히 못 치른다.**

`CostGroup` 은 `INVALID` 가 `UNKNOWN` 을 이긴다 — 조건 계층의 삼치 논리와
같은 태도다.

### 선택

수량 · 중복 · 후보 소속만 본다.

| 상황 | 답 |
|---|---|
| 최소 미달 / 최대 초과 | `INVALID(TOO_FEW_SELECTED / TOO_MANY_SELECTED)` |
| 같은 카드 두 번 | `INVALID(DUPLICATE_SELECTION)` |
| 후보가 아님 | `INVALID(CANDIDATE_NOT_ELIGIBLE)` |
| 후보인지 모름 | `UNKNOWN(INFORMATION_UNAVAILABLE)` |
| 관측에 없음 | `UNKNOWN(HIDDEN_CARD)` |

"이 카드가 효과 텍스트상 대상이 될 수 있는가" 는 **보지 않는다.** 대상 지정
규칙 계층이 아직 없다.

---

## 6. 정보 경계

- 상대의 패와 덱은 관측에 **아예 없다.** 후보에 들어갈 길이 없다
- 뒷면 카드는 자리와 컨트롤러만 보인다. 정체가 필요한 조건이면 `undecided`
- 같은 카드라도 **주인이 보면 확정된다**

후보 결과를 통째로 직렬화해서 가려진 카드의 ID 와 이름이 하나도 새지
않는지 테스트가 확인한다.

---

## 7. 아무것도 치르지 않는다

검증 전후로 다음이 전부 같다.

- `state_hash()` · 할당기 · `uses.canonical_state()` · 턴
- **양쪽 라이프**
- 모든 존의 장수
- 모든 `CardInstance` 의 `canonical_state()`

같은 비용을 열 번 검증해도 누적되지 않는다 — "검증을 위해 미리 치러보기"
가 없다는 뜻이다.

---

## 8. 실제로 지원하는 것

| 지원 | 예 |
|---|---|
| 카드 선택 비용 | "자신 필드의 몬스터 1장을 릴리스한다" |
| 여러 장 | "몬스터 2장을 릴리스한다" |
| 수량 범위 | "1~3장을 패에서 버린다" |
| 선택적 비용 | "최대 2장까지" (`minimum=0`) |
| 속성 · 레벨 등 조건 | "어둠 속성 몬스터 1장" |
| 라이프 비용 | "LP 1000 지불" (**깎지 않는다**) |
| 양쪽 필드에서 고르기 | `owner=None` |
| 복수 비용 (AND) | "LP 1000 지불 그리고 몬스터 1장 릴리스" |
| 표현 불가 비용 | `UnimplementedCost(rule)` → 언제나 `UNKNOWN` |

---

## 9. 의도적으로 미구현 / UNKNOWN

| 영역 | 어떻게 |
|---|---|
| 실제 지불 · 릴리스 · 제외 · 묘지로 보내기 · LP 감소 | 구현하지 않음 |
| 엑시즈 소재 제거 · 카운터 제거 | `UnimplementedCost` |
| "둘 중 하나" 선택형 비용 | 표현하지 않음 |
| 비용 타이밍 · 발동 타이밍 | 없음 |
| 대상 지정(targeting) 규칙 | 선택 검증이 보지 않음 |
| 릴리스 수 규칙 (레벨별 제물) | 없음 — 소환 절차는 Phase 2-G |
| 강제 / 임의 선택 구분 | 없음 |
| 체인 · 트리거 · 동시 처리 · 치환 효과 | 없음 |
| 카드별 비용 예외 | 없음 |

---

## 10. TEXT_DERIVED 경계

이 계층은 **효과를 등록하지 않는다.** 비용은 호출하는 쪽이 만들어 넘기는
값이고, 카드에서 자동으로 유도되지 않는다. 따라서 `TEXT_DERIVED` 효과가
실행 가능한 비용으로 등록되는 경로가 **애초에 없다.**

`analysis.EffectCost` → `engine.cost.Cost` 컴파일러는 만들지 않았다.
그것을 만들 때 (Phase 2-D 이후) `AnalysisStatus` 경계를 다시 확인해야 한다.
