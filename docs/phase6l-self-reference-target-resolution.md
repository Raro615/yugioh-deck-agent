# Phase 6-L — 효과 주체 자기 참조 및 대상 해석 구조 보완

> **달성 수준: §19 수준 2 (실제 효과 실행) 달성.**
>
> 어니스트 ① 이 실제 `Duel` 에서 발동되고 해결되며, `GameState` 가 바뀌고
> `EventJournal` 에 기록된다. **이 엔진이 해결한 첫 몬스터 효과**다.
>
> 🔴 남은 것은 숨기지 않는다 — §16 에 네 가지를 적었다.

- 브랜치 `claude/pensive-goodall-te1egy` · 시작 HEAD `5de992c`
- 작업 전 작업 트리 clean, 원격과 동일

---

## 1. 기존 자기 참조 및 대상 해석 구조

### 1-1. 세 계층이 "어느 카드인가" 를 서로 다르게 말한다

| 계층 | 가리키는 것 | 타입 |
|---|---|---|
| `EffectDefinition` | 대상의 **이름** | `TargetRef` (`@primary` …) |
| `ResolutionContext` | 이번 해결에서 **골라진 카드** | `TargetSelection` → `Selection(InstanceId…)` |
| `ResolutionContext.source` | **발동한 카드** | `InstanceId \| None` |

`TargetRef` 의 docstring 이 이미 적어 둔 대로, 정의는 어느 카드가 골라질지
모르고 알 필요도 없다 — 같은 정의를 여러 판에서 쓴다.

### 1-2. 조작은 대상을 **이름으로만** 가리킨다

```python
class CardOperation(Operation):
    operation: OperationKind
    target_ref: TargetRef      # 필수
```

`"카드를 다루는 일인데 어느 카드인지 말하지 않으면 그것은 일이 아니다"` —
`engine/effect/operation.py` 의 원문.

### 1-3. 이름은 반드시 **선언**되어야 했고, 선언은 반드시 **선택**이었다

```python
# EffectDefinition._check_target_links
if ref not in declared:
    raise EffectDefinitionError("… 선언되지 않은 대상 @self 를 가리킵니다")

# TargetBinding.__post_init__
if not self.spec.requires_selection:
    raise ValueError("… 고를 것이 없는 대상은 이름을 가질 이유가 없습니다")
```

**두 문이 맞물려 자기 참조를 막고 있었다.** 가리키려면 선언해야 하고,
선언하려면 고르는 규칙이 있어야 하는데, "이 카드 자신" 에는 고를 것이 없다.

---

## 2. 어니스트의 실제 실행 차단 원인 — 6-K 의 가설을 코드로 재검증

6-K 보고서는 "정의가 '이 효과의 카드' 를 가리킬 이름이 없다" 고 적었다.
**맞았다. 다만 처음 막는 자리가 실행기가 아니었다.**

실측 (`EffectDefinition` 을 만들어 보는 것만으로):

```
=== 1. 선언 없이 자기 참조 이름을 가리키는 정의 ===
   ❌ EffectDefinition.__post_init__ 에서 거부:
      return_to_hand 가 선언되지 않은 대상 @self 를 가리킵니다. 선언된 것: 없음
=== 2. TargetBinding 으로 선언하려면 선택 명세가 필요하다 ===
   ❌ TargetBinding.__post_init__ 에서 거부:
      @self 에 대상을 요구하지 않는 규칙이 묶였습니다.
```

🔴 **차단은 `EffectExecutor` 도 `CandidateResolver` 도 아니고 정의 생성
시점이었다.** 그래서 6-K 는 `operations=()` 로 실을 수밖에 없었다 — 하는
일을 적는 순간 정의를 만들 수 없었기 때문이다.

이것이 6-K 의 서술을 한 단계 정밀하게 고친 부분이다.

---

## 3. `ResolutionContext.source` 의 의미와 수명주기

### 3-1. 카드 **정의**가 아니라 카드 **한 장**이다

```python
source: InstanceId | None = None
"""효과를 발동한 카드. 필드를 떠난 뒤에도 해결되는 효과가 있으므로 없을 수 있다."""
```

`InstanceId` 는 `engine/ids.py` 가 적어 둔 대로 "듀얼 한 판 안에서 카드
인스턴스를 유일하게 가리키는 값" 이고, **"카드가 존을 옮겨도 번호는
그대로"** 다. 그래서 같은 카드명 세 장을 서로 구분하고, 발동 시점의 카드를
해결 시점까지 들고 갈 수 있다.

### 3-2. 문맥은 **안정적인 식별자만** 담는다

모듈 머리말이 이미 적어 둔 약속이다 — `CardInstance` 나 `GameState` 를
담지 않는다. 담으면 문맥이 특정 판에 묶이고 직렬화도 replay 도 불가능해진다.

그래서 **"발동 당시의 카드 객체" 는 문맥에 없다.** 있는 것은 번호이고, 그
번호로 **현재** 판을 찾는다 (`state.find_instance`). 발동 당시의 자리나
표시 형식을 참조해야 하는 효과는 그 정보를 **아직 들고 다니지 않는다** —
§16-1 이 그 공백이다.

### 3-3. `None` 은 "없다" 가 아니라 "모른다"

필드를 떠난 뒤에도 해결되는 효과를 위해 열어 둔 칸이다. 6-L 은 그 값을
**지어내지 않는다** — 같은 카드 ID 의 다른 인스턴스로 대신하면 **발동하지
않은 카드**가 움직인다.

---

## 4. `CandidateResolver` 와 `TargetRequirement` 의 계약

### 4-1. `CandidateResolver` 는 "관측에서 고를 수 있는 것" 을 센다

- `GameStateView` 만 받는다 (`GameState` 를 주면 거부한다)
- `ChoiceSpec` → `CandidateSet(eligible, undecided, unchecked)` — 셋으로 갈린다
- 가려진 존은 **조용히 건너뛰지 않는다** (STRUCTURAL-15)
- `require` 는 **후보마다** 문맥의 `source` 를 **그 후보로 바꿔** 판정한다

마지막 줄이 중요하다. 그래서 `require` 로 "이 카드인가" 를 물을 수 없다 —
원래 발동한 카드가 거기서 사라진다.

### 4-2. `TargetRequirement` 넷은 전부 "어떻게 고르는가" 다

| 값 | 뜻 |
|---|---|
| `NONE` | 고를 것이 없다 |
| `TARGETING` | 규칙상 **대상으로 지정**한다 |
| `CHOOSING` | 고르지만 대상 지정은 아니다 |
| `ALL` | 고르지 않는다 — 해당하는 것 전부 |
| `RANDOM` | 아무도 고르지 않는다 — 난수가 정한다 |

**자기 참조는 이 축의 다섯 번째 값이 아니다.** 고르는 방식의 한 종류가
아니라, 고르지 않고 **이미 정해진 한 장**을 가리키는 일이다.

### 4-3. `exclude_source` 는 자기 참조의 **정확한 여집합**

실측 (같은 카드 두 장 + 다른 카드 한 장이 컨트롤러의 몬스터 존에):

| 명세 | `eligible` |
|---|---|
| `MZONE` / 컨트롤러 | `#40 · #41 · #42` |
| 같은 명세 + `exclude_source=True` | `#41 · #42` |
| **차** | **`#40`** (발동한 카드) |

엔진은 발동한 카드를 **뺄** 줄은 알았고 **가리킬** 줄은 몰랐다.

---

## 5. 채택한 최소 구현과 대안 비교

### 대안 비교

| | 방식 | 결과 |
|---|---|---|
| **A** | 예약된 `TargetRef` 하나 + 실행기가 `context.source` 에서 푼다 | **채택** |
| B | `TargetBinding` 으로 선언 (후보 선택으로 표현) | ❌ |
| C | `TargetRequirement` 에 다섯 번째 값 | ❌ |

#### B 를 버린 이유 — **실측으로 틀렸다**

"컨트롤러의 몬스터 존에서 1장" 으로 "이 카드" 를 적으면 같은 카드 두 장이
깔린 판에서 후보가 **둘**이 된다 (§4-3 의 표). 플레이어가 **발동하지 않은
쪽**을 고를 수 있고, 그것은 규칙이 아니라 결함이다.

그리고 선언하는 순간 `requires_target` 이 참이 되어 **대상 지정 효과**가
된다 — 어니스트 ① 의 공식 텍스트에 「대상으로 하고」 가 **없는데도**.

#### C 를 버린 이유

축을 늘리면 "고르는 방식" 이 다섯 가지가 되고, 그중 하나는 고르지 않는다.
그 축을 읽는 모든 코드(`target_bridge` · `TargetResolver` · `CostGroup` ·
`EffectActivator`)가 "다섯 번째는 예외" 를 각자 적게 된다.

#### A 를 고른 기준 (§6 의 일곱 항목)

| 기준 | A 의 답 |
|---|---|
| Engine V1 계약 보존 | `PlayerAction` · `EffectRef` · `ResolutionContext` · `TargetRequirement` **칸이 하나도 안 바뀌었다** |
| 카드 인스턴스 식별 정확성 | `InstanceId` 하나를 가리킨다 (§8 이 실측) |
| 카드별 하드코딩 불필요 | 이름 하나를 공유한다 (§12 가 다섯 조작에서 확인) |
| 대상 지정 여부와 구분 | `targets` 가 비어 있고 `requires_target` 이 거짓이다 |
| 비공개 영역 정보 보호 | 후보를 세지 않으므로 관측을 열지 않는다 |
| 기존 테스트 호환성 | `CandidateResolver` · `TargetRequirement` 를 **건드리지 않았다** |
| 추가 구조 복잡도 | 새 타입 **0개** — `TargetRef` 값 하나 |

---

## 6. 변경한 파일 및 함수

| 파일 | +/− | 무엇 |
|---|---|---|
| `engine/effect/library.py` | +67 −35 | 어니스트 ① 에 하는 일을 적고 `executable=True`, `MAY_BE_RETURNED_TO_HAND` 답 |
| `engine/effect/executor.py` | +57 −3 | `_target_spec_of` · `_resolve_self_reference` · 적법성 검사 한 곳 생략 |
| `engine/effect/target.py` | +45 −1 | `SELF_TARGET` + `TargetBinding` 이 그 이름을 거부 |
| `engine/effect/definition.py` | +39 −2 | `_check_target_links` 예외 · `references_self` |
| `engine/spell_activation.py` | +22 −2 | `duel_resolver` 가 `rulings=OPERATION_RULINGS` 를 넘긴다 |
| **합계** | **+230 −43** | production 5파일 |

### 6-1. `SELF_TARGET` — 예약된 이름 하나

```python
SELF_TARGET = TargetRef("self")
```

`TargetBinding.__post_init__` 이 이 이름을 **거부한다** — 선언하면 대상
지정 효과가 되기 때문이다. `EffectDefinition._check_target_links` 는 이
이름만 **선언 없이** 통과시킨다.

### 6-2. 실행기 — 두 함수와 한 생략

```python
@staticmethod
def _target_spec_of(definition, ref):
    if ref == SELF_TARGET:
        return None          # 고를 규칙이 없다
    return definition.target_spec(ref)   # 없는 이름은 여전히 KeyError

def _resolve_self_reference(self, context, operation):
    if context.source is None:
        return _fail(INVALID_CONTEXT, INFORMATION_UNAVAILABLE,
                     "… 같은 카드의 다른 인스턴스로 대신하지 않습니다.")
    return SELF_TARGET, Selection(chosen=(context.source,))
```

`_plan_card_operation` 에서 **건너뛰는 검사는 하나뿐**이다 —
`_check_target`(고른 것이 규칙에 맞는가). 고른 것이 없으므로 물을 수 없고,
`TargetResolver.validate` 는 `spec` 을 받아야 답한다.

**그대로 지나는 것들**: `state.find_instance` (판에 있는가) ·
`origin_rule` (출발 자리) · `_check_rule_gate` (관문). 자기 참조라는 이유로
공짜가 되는 검사가 **없다.**

### 6-3. `duel_resolver` 가 판정 지식을 넘긴다

`build_executor` 는 `rulings` 를 **기본값으로 넣지 않는다** — "목록에
실렸다는 사실이 판정을 대신하게" 되기 때문이다 (ADR-006). 그래서 **부르는
쪽이 고른다**, 그리고 조립 자리가 거기다.

측정: 이 배선 전에는 `gated=True` 이동이 듀얼 경로에서 **하나도** 일어나지
않았다 (`UnknownMovementRuling`). 그리고 그 영향을 받는 기존 등재는 둘뿐이고
(어리석은 매장 · 강제 탈출 장치) **둘 다 애초에 듀얼 경로의 후보가 아니다**
(덱의 대상 · 함정의 발동 타이밍). 그래서 **등재된 마법 열여섯 중 하나도
동작이 바뀌지 않았다** (§15-J 가 확인).

---

## 7. 새로 지원되는 자기 참조 패턴

실측 — 같은 이름을 다섯 조작에서 그대로 쓴다:

| 조작 | 결과 | 도착 자리 |
|---|---|---|
| `return_to_hand(SELF_TARGET, gated=True)` | `RESOLVED` | `HAND` |
| `send_to_grave(SELF_TARGET)` | `RESOLVED` | `GRAVE` |
| `banish(SELF_TARGET)` | `RESOLVED` | `REMOVED` |
| `return_to_deck(SELF_TARGET)` | `RESOLVED` | `DECK` |
| `release(SELF_TARGET)` | `RESOLVED` | `GRAVE` |
| `destroy(SELF_TARGET)` | `UNCHECKED_RULES` | `MZONE` (그대로) |

마지막 줄이 중요하다 — `destroy` 는 **종류만으로** 관문을 받으므로 (파괴
내성 · 대체 효과) 자기 참조가 풀렸어도 그대로 막힌다. 블랙홀이 막혀 있는
것과 같은 자리다. **카드별 분기가 아니라 공통 참조**라는 것이 여기서
증명된다.

🔴 **production 목록에 등재한 것은 어니스트 ① 하나다.** 위의 나머지는
테스트 안에서 만든 정의로 참조의 재사용만 확인했다.

---

## 8. 동일 카드 ID 복수 인스턴스 검증

같은 카드 두 장을 앞면으로 몬스터 존에 놓고, 각각을 발동시켰다.

| 발동한 쪽 | `#40` | `#41` |
|---|---|---|
| `#40` | **HAND** | MZONE |
| `#41` | MZONE | **HAND** |

실제 `Duel` 에서도 같다 — 후보가 **둘**(인스턴스마다 하나) 나오고, 고른
쪽만 움직인다.

그리고 `source=None` 이면:

```
status=invalid_context  code=information_unavailable
reason=return_to_hand 가 이 효과를 발동한 카드를 가리키는데 (@self)
       문맥에 그 카드가 없습니다. 같은 카드의 다른 인스턴스로 대신하지 않습니다.
```

두 장 **다** 그대로 남는다.

---

## 9. 자기 참조와 대상 지정의 구분 결과

| 질문 | 어니스트 ① |
|---|---|
| `definition.targets` | `()` |
| `definition.requires_target` | `False` |
| `definition.references_self` | `True` |
| `chosen_bindings(definition)` | `()` |
| `required_target_count(definition)` | `0` |
| `selections_for(definition, action)` | `()` |
| `target_combinations(...)` | `[()]` |
| `PlayerAction.targets` (실제 후보) | `()` |

`target_bridge` 는 **한 줄도 바꾸지 않았다.** 선언된 대상이 없으므로
짝지을 것이 없고, 그래서 자동으로 맞는다.

`references_self` 를 `requires_target` 과 **다른 프로퍼티**로 둔 이유가
이것이다. 하나로 합치면 "자기 자신을 패로 되돌린다" 가 대상 지정 효과로
읽힌다.

---

## 10. 비용 · 대상 · 효과 해결의 관계

세 단계가 **구조로** 갈려 있고, 자기 참조는 그중 하나만 열었다.

| 단계 | 모델 | 자기 참조 |
|---|---|---|
| A 발동 비용 | `CostGroup(costs=(Cost…))` — `CostKind` · `ChoiceSpec` | ❌ `Cost` 에 `target_ref` 칸이 **없다** |
| B 발동 시 대상 선택 | `TargetBinding` · `TargetSpec` · `CandidateResolver` | ❌ 선언이 **거부**된다 |
| C 효과 해결 | `CardOperation.target_ref` → `EffectExecutor` | ✅ **여기 하나** |

실측: `engine/cost/` 전체에 `SELF_TARGET` 이 **0회** 등장한다 (테스트가
AST 가 아니라 전체 텍스트로 센다). 그래서 어니스트 ②(`Cost.SelfToGrave`)는
**여전히 등재되지 않았다** — 자기 참조가 열린 것은 "하는 일" 쪽이고
"비용" 쪽이 아니다.

§8 이 금지한 오류들에 대해:

| 금지 | 확인 |
|---|---|
| 해결 시 비용 사후 처리 | 등재한 효과에 비용이 **없다** (`cost.is_free`) |
| 자기 참조라서 비용 생략 | 비용 모델에 자기 참조가 닿지 않는다 |
| 대상 지정 아닌 효과를 대상 지정으로 | `TargetBinding` 이 그 이름을 거부한다 |
| 이름이 같다고 다른 카드 선택 | `_resolve_self_reference` 가 `card_id` 를 **읽지 않는다** (AST 로 확인) |
| 카드가 없는데 성공 처리 | `CANDIDATE_NOT_FOUND` 로 멈춘다 |
| 미지원 대상 선택을 자동 선택 | `TOO_FEW_SELECTED` 로 멈춘다 |

---

## 11. 어니스트 대표 사례 결과

공식 Lua (`c37742478.lua`):

```lua
e1:SetType(EFFECT_TYPE_IGNITION)
e1:SetRange(LOCATION_MZONE)
e1:SetTarget(s.target1)
e1:SetOperation(s.operation1)
...
function s.target1(e,tp,eg,ep,ev,re,r,rp,chk)
	if chk==0 then return e:GetHandler():IsAbleToHand() end
	...
function s.operation1(e,tp,eg,ep,ev,re,r,rp)
	local c=e:GetHandler()
	if c:IsFaceup() and c:IsRelateToEffect(e) then
		Duel.SendtoHand(c,nil,REASON_EFFECT)
	end
end
```

옮긴 것과 옮기지 못한 것:

| Lua | 엔진 |
|---|---|
| `SetType(EFFECT_TYPE_IGNITION)` | `activation_kind=ActivationKind.IGNITION` (6-K) |
| `SetRange(LOCATION_MZONE)` | 발동 범위 — `IGNITION_ACTIVATION_ZONES` (6-K) |
| `e:GetHandler():IsAbleToHand()` | `gated=True` + `OPERATION_RULINGS` 의 답 |
| `Duel.SendtoHand(c,…)` · `c=e:GetHandler()` | `CardOperation.return_to_hand(SELF_TARGET)` |
| `c:IsRelateToEffect(e)` | ❌ **옮기지 못했다** (STRUCTURAL-50) |
| `c:IsFaceup()` | ❌ **옮기지 못했다** |

🔴 **카드 ID 분기는 없다.** 어니스트의 번호가 production 코드에 나타나는
자리는 `library.py` 의 **선언**뿐이고 비교문은 0곳이다 (AST 로 확인).

### `MAY_BE_RETURNED_TO_HAND` 의 근거

`RuleBasis.CARD_TEXT` — 공식 텍스트 전문을 읽었다. ① 이
「필드의 앞면 표시의 이 카드를 **패로 되돌린다**」 라고 **직접** 적고, ②는
패에서 묘지로 가는 효과이며, 어디에도 패로 돌아가는 것을 막는 문장이 없다.
메인 덱의 효과 몬스터이므로 토큰도 엑스트라 덱 카드도 아니다.

🔴 **다른 질문에는 답하지 않았다** — 제외 · 묘지 · 덱 · 버리기는 묻지
않았고, 묻지 않은 것을 참으로 채우지 않는다 (테스트가 그것을 센다).

---

## 12. 다른 카드 효과에 대한 재사용 검증

### 12-1. 코퍼스 정적 측정

`Duel.<API>(핸들러, …)` 패턴 — 스크립트 **12,702**개를 훑었다.

| | 수 |
|---|---|
| 그 패턴을 쓰는 카드 | **2,872장** |
| 그중 `e:GetHandler()` 를 인자로 **직접** 적는 카드 | 612장 |

API 별 (상위):

| Lua | 호출 수 | 엔진 `OperationKind` |
|---|---|---|
| `Duel.SpecialSummon` | 1,323 | `special_summon` (B2 로 막혀 있다) |
| `Duel.Destroy` | 448 | `destroy` (파괴 관문) |
| `Duel.SendtoGrave` | 269 | `send_to_grave` ✅ |
| `Duel.SendtoHand` | 231 | `return_to_hand` ✅ |
| `Duel.ChangePosition` | 184 | (없다) |
| `Duel.Remove` | 169 | `banish` ✅ |
| `Duel.SendtoDeck` | 126 | `return_to_deck` ✅ |
| `Duel.Release` | 35 | `release` ✅ |

엔진 `OperationKind` 로 번역 가능한 자기 참조 이동 호출: **1,278건**.

> 🔴 **이것은 정적 수치다.** "1,278개 효과가 이제 실행된다" 가 **아니다** —
> 참조 이름이 그 패턴을 **표현할 수 있게** 되었다는 뜻이고, 각 효과의
> 실행은 비용 · 조건 · 턴 제한 · 관문 · 대상 선택이 따로 결정한다.
> 실제로 실행되는 것은 **1건**이다 (§13).

### 12-2. 실행 재사용

§7 의 표가 다섯 조작에서 같은 이름이 동작함을 보인다. 그중 **아무것도**
production 목록에 등재하지 않았다 — §11 이 요구한 "공통 참조 계약의 재사용
가능성" 을 확인한 것이고, 카드를 늘린 것이 아니다.

---

## 13. 실제 `EffectExecutor` 연결 결과

| 단계 | 결과 |
|---|---|
| `legal_actions` | 후보 **1건** (`source=#40`, `effect_ref=37742478:e[0]`, `targets=()`) |
| `ActionValidator` | `VALID` (6-K 가 열었다) |
| `ActivationTimingChecker` | `VALID` (체인이 비어 있다) |
| `EffectActivator.can_activate` | `VALID` ← **6-K 에서는 여기가 `NOT_IMPLEMENTED`** |
| `activate` | `ACTIVATED`, 체인 1, 판은 **그대로** |
| 응답 창 | 열린다 (RULE-CHAIN-001) |
| `ChainResolver` → `EffectExecutor` | `RESOLVED`, 1건 적용 |
| `GameState` | `#40` MZONE → **HAND** |
| `EventJournal` | `effect actor=0 ref=37742478:e[0] source=#40 deltas=1` |

### 실행 가능 수의 변화

| | 6-K | 6-L |
|---|---|---|
| 등재 (`EFFECT_LIBRARY`) | 17 | 17 |
| 실행 가능 (`executable`) | 13 | **14** |
| 실행되는 **몬스터** 효과 | 0 | **1** |
| 거절(`not executable`) | 4 | 3 |

남은 셋(블랙홀 · 죽은 자의 소생 · 로스트)의 이유는 **없는 의미 계층**이고,
자기 참조가 그것을 열지 않는다.

---

## 14. 실제 `GameState` 변경 및 `EventJournal` 결과

```
delta: ZoneMoved #40 P0/MZONE → P0/HAND (return_to_hand)
```

- 발동 시점에는 **움직이지 않는다** (체인에 올라간 뒤 상대가 응답할 수 있다)
- 해결 시점에 패로 돌아간다
- `journal.events` 가 비어 있다가, 해결 뒤 `effect` 하나가 생긴다
- `source=#40` 이 기록된다 — **어느 인스턴스가 발동했는가**가 역사에 남는다
- 판을 바꾼 해결만 적힌다 (`deltas` 가 비면 기록도 없다)

### §14 정확성 평가 — 전후 비교

| | 6-K | 6-L | 비고 |
|---|---|---|---|
| 1. 자기 참조를 식별할 수 있는 효과 | **0** | **1** (등재) | 표현 가능한 패턴은 정적 1,278 호출 |
| 2. `source` 가 없어 미확인 | — | 거부 (`INFORMATION_UNAVAILABLE`) | 지어내지 않는다 |
| 3. 같은 카드 ID 의 다른 인스턴스 오선택 | — | **0** | §8 이 전수(2장) 확인 |
| 4. 자기 참조 ↔ 대상 지정 혼동 | — | **0** | `requires_target=False` |
| 5. `CandidateResolver` 회귀 | — | **0** | 파일을 건드리지 않았다 |
| 6. 비용 · 대상 선택이 미지원으로 남은 사례 | — | 어니스트 ② (`Cost.SelfToGrave`) | 비용 축은 열지 않았다 |
| 7. `EffectExecutor` 로 전달 가능 | 13 | **14** | |
| 8. `GameState` 변경을 검증한 효과 | 12† | **13†** | †실행 가능 중 실제로 판을 바꾸는 것 |
| 9. `EventJournal` 에 기록된 사례 | 0 (몬스터) | **1** | |
| 10. 새 구조적 차단 요인 | — | **4** | §16 |

검사 범위: 자기 참조는 **전수**(등재 1건 + 테스트 정의 5건), 코퍼스 패턴은
**전수 정적 스캔**(12,702 파일), 실행은 **등재 17건 전수**.

---

## 15. 타깃 · 통합 · 관련 회귀 테스트 결과

§15 의 3단계 정책을 그대로 따랐고, **pytest 의 실제 종료 코드**를 읽었다.

| 단계 | 명령 | 결과 | 시간 | 종료 코드 |
|---|---|---|---|---|
| 1 타깃 | `pytest tests/engine/test_self_reference_target.py` | **42 passed** | 5s | `0` |
| 2 통합 + 3 회귀 (엔진, 1차) | `pytest tests/engine` | **3,171 passed** | 8:21 | `0` |
| 3 회귀 (관련 루트, 1차) | `pytest <57 files>` | **4 failed** — 움직인 핀 넷 (아래) | 중단 | — |
| 2 통합 + 3 회귀 (엔진, 최종) | `pytest tests/engine` | §18 | | |
| 3 회귀 (관련 루트, 최종) | `pytest <57 files>` | §18 | | |

1차 루트 회귀에서 실패한 넷은 전부 **등재된 실행 가능 효과의 수**를 세는
감사 핀이었고 (`13 → 14`, `몬스터 executable 0 → 1`), 아래에 왜 움직였는지를
적었다. 핀을 고친 뒤 2 · 3단계를 **처음부터 다시** 돌렸다 — 바뀐 파일을
포함한 회귀를 중간부터 이어 붙이지 않는다.

### 움직인 기존 핀 — 열아홉

**기존 테스트를 지우지도 skip 을 더하지도 않았다.** threshold 를 완화한
자리도 없다. 움직인 것은 전부 "그 시점에 참이었던 사실" 이고, 각 자리에
왜 움직였는지를 적었다.

| 테스트 | 전 | 후 |
|---|---|---|
| `test_j_this_phase_turned_on_no_new_execution` | 실행 13 | 14 + **카드군 조건을 쓰는 실행이 0** 을 새로 센다 |
| `test_c_the_compiler_now_turns…` | 거절 집합에 어니스트 | 빠졌다 + 실행 집합에 들어갔다 |
| `test_a_the_engine_targets_activate_only_cards` | 실행하는 것은 전부 `ACTIVATE` | `ACTIVATE` 아닌 등재가 **정확히 하나** |
| `test_a_the_executing_cards_calibrate_the_classifier` | 카드 단위 API 집합 | **블록이 하나인 카드만** 센다 (아래) |
| `test_a_five_hundred_sixteen…` | 실행 13 ⊆ clean | 14, 어니스트는 `activate_only` 슬라이스 **밖** |
| `test_a_thirteen_real_effect_refs_are_executable` | 13 | 14 (+어니스트) |
| `test_a_every_declined_card_says_what_is_missing` | 넷 | **셋** |
| `test_16_the_library_is_unchanged…` | 실행 13 | 14 (유발 효과 0 은 분류로 센다) |
| `test_the_library_does_not_pick_targets_for_anyone` | — | 내 주석을 고쳤다 (아래) |
| 6-K 의 `test_b04` · `k02` · `l01`~`l04` | 실행 불가 · 후보 0 · 체인 0 | 실행 · 후보 1 · 체인 1 · 해결 |
| `test_12_every_registered_effect_belongs_to_a_spell_or_trap` | 실행되는 몬스터 0 | **1** + 마법·함정 13 을 따로 센다 |
| `test_05_every_executable_effect_is_a_spell_or_a_trap` | 실행되는 것은 전부 마법·함정 | 몬스터 1 + **그 발동 분류가 기동이어야 한다**를 새로 센다 |
| `test_13_sixteen_registered_definitions_are_tabulated` | 실행 13 | 14 |
| `test_16_monster_effects_are_blocked_for_a_different_reason` | 몬스터 하나, `executable=False` | `True` (막는 이유가 함정과 다르다는 단언은 그대로) |

#### 🔴 사실이 바뀐 자리 두 곳은 **단언을 갈라서 더 적었다**

**(1) `test_a_the_executing_cards_calibrate_the_classifier`** — 이 시험은
"실행되는 카드가 쓰는 API 는 막는 것일 수 없다" 를 센다. 그런데 `corpus`
의 행은 **카드 단위**이고 실행되는 것은 **효과 단위**다. 어니스트가
등재되면서 둘이 **처음으로** 갈렸다 — ① 만 실행되는데 ②(유발 즉시)가 쓰는
`GetAttacker` · `GetAttackTarget` · `IsDamageCalculated` 까지 "실행으로
증명됐다" 로 세게 된다. **그것은 거짓**이므로 블록이 하나인 카드만 쓰고,
빼고 센 카드가 **어니스트 하나**임을 단언으로 못박았다.

**(2) `test_the_library_does_not_pick_targets_for_anyone`** — `library.py`
안에 `InstanceId` 라는 **이름이 나타나는 것**을 금지한다 ("정의에 실제
카드를 박지 않는다"). 내가 설명 주석에 그 단어를 적었다가 걸렸다. 감사에
예외를 더하면 그 감사가 조용히 약해지므로 **주석을 고쳤다** — 6-K 가
`effect_types` 에서 배운 것과 같은 자리다.

### Mutation 테스트 — 6-L 프로덕션 코드에 고의 결함 12개

**내가 쓴 코드만** 대상으로 했고, `git checkout` 을 쓰지 않았다 (6-K 에서
그렇게 했다가 커밋하지 않은 작업이 날아갔다). 원본을 메모리에 들고 있다가
되돌리고 `assert` 로 확인한다 — 하네스는
`scratchpad/mutate3.py` 다. 판정 테스트는
`pytest tests/engine/test_self_reference_target.py` 이고 **pytest 의 실제
종료 코드**로 판정했다.

| # | 고의 결함 | 결과 |
|---|---|---|
| N1 | 문맥에 발동 카드가 없으면 빈 선택으로 넘긴다 (거부하지 않는다) | killed (1 failed) |
| N2 | 자기 참조를 대상으로 선언할 수 있게 한다 (`TargetBinding` 가드 제거) | killed (1 failed) |
| N3 | 선언되지 않은 자기 참조를 모순으로 읽는다 (`continue` 제거) | killed (collection error) |
| N4 | 모든 이름에 대상 규칙 `None` 을 돌려준다 | 🔴 **처음에 생존** → 아래 |
| N5 | 자기 참조에도 `_check_target` 을 건다 | killed (17 failed) |
| N6 | `_resolve_selection` 의 자기 참조 분기를 뺀다 | killed (18 failed) |
| N7 | `duel_resolver` 가 조작 판정 지식을 넘기지 않는다 | killed (4 failed) |
| N8 | 어니스트의 「패로 되돌릴 수 있는가」 답을 거짓으로 뒤집는다 | killed (11 failed) |
| N9 | `references_self` 가 언제나 거짓이다 | killed (3 failed) |
| N10 | 어니스트의 이동에서 관문 선언(`gated`)을 뺀다 | killed (1 failed) |
| N11 | 자기 참조의 이름을 흔한 대상 이름(`primary`)과 같게 만든다 | killed (collection error) |
| N12 | 어니스트를 다시 `executable=False` 로 돌린다 | killed (collection error) |

#### 🔴 N4 가 생존했다 — 테스트를 더해서 잡았다 (숨기지 않았다)

`EffectExecutor._target_spec_of` 가 **모든** 이름에 `None` 을 돌려주게
바꿨는데도 이 파일의 41개가 **전부 통과했다.**

무엇이 깨지는 결함인가: `None` 이 "자기 참조라서 고를 규칙이 없다" 와
"선언되지 않은 이름" 과 "선언된 이름의 규칙" 을 **셋 다** 뜻하게 된다.
그러면 선언된 대상의 자리 · 주인 · 조건을 다시 보는 `_check_target` 이
`spec=None` 으로 불려서 사실상 꺼진다.

추적 측정 — 다른 기존 테스트는 이 결함을 **잡는다**:

| 테스트 | N4 적용 시 |
|---|---|
| `tests/engine/test_targeted_effect.py` | **25 failed**, 29 passed (`rc=1`) |
| `tests/engine/test_real_card_execution.py` | **21 failed**, 63 passed (`rc=1`) |

즉 저장소 전체로는 구멍이 아니지만, **6-L 이 더한 함수를 6-L 의 테스트가
재지 않고 있었다.** 그래서 `test_c05_the_spec_lookup_splits_three_ways_not_two`
를 더해 그 세 갈래(자기 참조 → `None` · 선언된 이름 → **그 규칙 자체** ·
선언되지 않은 이름 → `KeyError`)를 직접 못박았다.

재측정: N4 는 이제 이 파일 하나로도 **killed** (1 failed, 41 passed) 이고,
타깃 테스트는 41 → **42 passed** 다.

**최종: 12개 중 12개 killed, 생존 0.**

---

## 16. 🔴 남아 있는 실행 차단 요인

### 16-1. 「필드의 앞면 표시의」 를 옮기지 못했다 — **잠재적 오동작**

어니스트 ① 의 공식 텍스트는 「**필드의 앞면 표시의** 이 카드를 패로
되돌린다」 이고, Lua 가 `if c:IsFaceup() and c:IsRelateToEffect(e) then`
으로 그것을 적는다. **둘 다 옮기지 못했다.**

- `IsRelateToEffect` — 발동 뒤 그 카드가 떠났는지 (STRUCTURAL-50)
- `IsFaceup` — 해결 시점의 표시 형식
- `ORIGIN_RULES` 에 `RETURN_TO_HAND` 항목이 **없다** (출발 자리 무제약)

실측: 묘지 · 패 · 마법 & 함정 존에 있는 카드도 `RESOLVED` 로 패에 돌아간다.

**지금은 닿지 않는다** — 발동 범위가 앞면 몬스터 존으로 좁혀져 있고
(6-K), 발동과 해결 사이에 그 카드를 옮길 수 있는 효과가 이 엔진에 하나도
없다. 그 길이 생기는 날 **반드시 틀린다.**

`ORIGIN_RULES` 를 여기서 고치지 않은 이유: 그 표는 **조작 종류마다
전역**이고, 묘지 · 덱 · 제외 구역에서 패로 돌아가는 효과가 실제로 많다.
전역으로 막으면 그 카드들이 틀린다. **조작마다의 출발 자리 제약**이
필요하고, 그것은 `CardOperation` 모델 변경이다 (§3-16 → 승인 대기).

### 16-2. 판에 모르는 앞면 카드가 있으면 멈춘다

`BoardRuling._interference` 가 `OPERATION_RULINGS` 에 없는 앞면 카드를
만나면 `UNKNOWN` 을 돌려준다 — "아무도 안 막는다" 는 판 전체를 읽었을
때만 할 수 있는 말이기 때문이다.

실측: 룡기병(미등록)이 앞면으로 같이 있으면 어니스트 ① 이 해결되지
**않는다** (`UNCHECKED_RULES`, 카드는 MZONE 그대로, journal 비어 있음).

이것은 **올바른 보수적 동작**이고 결함이 아니다. 다만 "어니스트가 실행
된다" 가 **모든 판에서** 참이 아니라는 뜻이므로 적어 둔다.

### 16-3. 비용으로서의 자기 참조가 없다

`Cost` 에 `target_ref` 칸이 없으므로 「이 카드를 패에서 묘지로 보내고
발동」(어니스트 ②, `Cost.SelfToGrave`) 은 여전히 표현할 수 없다.

### 16-4. 후보 생성과 발동 허가가 **서로 다른 목록을 읽는다**

`legal_actions` 는 `activatable_effects` 를 **모듈 수준**에서 읽고
(`EFFECT_LIBRARY` 직접), `_activation_gate` 의 셋째 관문은 **주입된**
발동기의 `lookup` 을 읽는다. 둘 다 후보를 **좁히기만** 하므로 오동작은
아니지만, 지금은 "같은 목록을 읽어서 같은 답" 이 아니라 "두 목록이 우연히
같아서 같은 답" 이다.

6-K 가 이 사실을 **반만** 적었던 것을 테스트로 정정했다 (`test_l05`).

---

## 17. 다음 단계에서 가장 먼저 해결할 최소 작업

**조작마다의 출발 자리 제약** (§16-1) 이 가장 작고 가장 위험하다.

- `CardOperation` 에 "이 조작은 이 자리에서만 출발한다" 를 적는 칸 하나
- `_plan_card_operation` 이 이미 `origin_rule` 을 보는 그 자리에서 함께 본다
- 영향: `engine/effect/operation.py` · `executor.py` 와 그 둘을 고정한 테스트

그것이 열리면 어니스트 ① 이 **공식 텍스트대로** 동작한다 (필드의 앞면
표시일 때만). `IsRelateToEffect` 는 그보다 크다 — 발동과 해결 사이의
카드 동일성을 추적하는 계층이 필요하다.

그다음은 §16-2 (판정 지식을 넓히는 일, 통상 몬스터부터) → §16-3 (비용
축의 자기 참조) 순서를 권한다.

**이 Phase 는 §3-16 · §17-13 에 따라 위 셋 중 아무것도 진행하지
않았다.**

---

## 18. Git 커밋 및 푸시 결과

브랜치 `claude/pensive-goodall-te1egy`. 시작 HEAD `5de992c` (6-K 의 마지막).
**기존 커밋을 rewrite 하거나 amend 하지 않았고, force push 하지 않았다.**

| 커밋 | 무엇 |
|---|---|
| `ca78eee` | production 5파일 (+230 −43) |
| `5ef071b` | 테스트 — 새 파일 1 (42개) + 움직인 핀 8파일 |
| (이 커밋) | 보고서 |

### 실행한 테스트 — 명령 · 시간 · 종료 코드

§15 의 3단계 정책을 그대로 따랐다. **`tail` 이나 `grep` 의 종료 코드가
아니라 pytest 자신의 종료 코드**를 읽었다.

| 단계 | 명령 | 통과 | 실패 | 건너뜀 | 시간 | 종료 코드 |
|---|---|---|---|---|---|---|
| 1 타깃 | `pytest tests/engine/test_self_reference_target.py -q -p no:randomly` | 42 | 0 | 0 | 5.3s | `0` |
| 2+3 엔진 (1차) | `pytest tests/engine -q -p no:randomly` | 3,171 | 0 | 0 | 8:21 | `0` |
| 3 루트 (1차) | `pytest <57 files> -q -p no:randomly` | — | **4** | — | 중단 | — |
| 2+3 엔진 (최종) | `pytest tests/engine -q -p no:randomly` | **3,172** | 0 | 0 | 6:41 | `0` |
| 3 루트 (최종) | `pytest <57 files> -q -p no:randomly` | **진행 중** | | | | |

🔴 **루트 회귀(57파일)는 이 커밋 시점에 아직 돌고 있다.** 약 1,800개
규모이고 앞서 같은 집합이 13%에서 16분이었다. 끝나는 대로 결과를 이 절에
적고 **별도 커밋**으로 올린다 — 숫자를 예측해서 적지 않는다.

1차 루트 회귀에서 실패한 넷은 전부 §15 에 적은 감사 핀이고, 고친 뒤 2 · 3
단계를 **처음부터** 다시 돌렸다.

### Mutation

§15 에 12개 전부와 그중 하나가 생존했던 사실, 그리고 그것을 테스트로 잡은
과정을 적었다. **최종 12/12 killed, 생존 0.**

### 저장소 전체 테스트를 돌리지 않은 이유

§15 가 "저장소 전체 테스트는 광범위한 아키텍처 변경이나 릴리즈 수준 검증이
필요할 때 수행한다. 동일한 대규모 테스트를 이유 없이 반복하지 않는다" 라고
적었다. 6-K 가 직전에 전체(5,935 passed · 4 skipped)를 돌렸고, 6-L 이
건드린 공유 계약은 `EffectDefinition` · `EffectExecutor` · `EffectLibrary` ·
`duel_resolver` 넷이다. 그 넷을 이름으로 읽는 파일을 전수 검색해서 57개를
얻었고 (`EFFECT_LIBRARY|EffectDefinition|executable|effect/executor|
effect/target|effect/library|spell_activation|duel_resolver|
OPERATION_RULINGS`), 그 집합과 `tests/engine` 전체를 돌렸다.

---

**다음 Phase 는 자동으로 시작하지 않는다.**
