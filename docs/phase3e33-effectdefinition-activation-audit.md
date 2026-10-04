# Phase 3-E-33 — `EffectDefinition.activation` 출처·분리 가능성 감사

**판정: B. ACTIVATION_NEEDS_BOUNDARY_CLARIFICATION**

**production 변경: 0줄.** `engine/` · `agent/` · `core/` · `analysis/` ·
`sources/` 를 한 글자도 바꾸지 않았다. 더한 것은 감사 테스트 1개와 이 문서뿐이다.

---

## 1. 실제 HEAD 확인

| 항목 | 값 |
|---|---|
| 브랜치 | `claude/pensive-goodall-te1egy` |
| 감사 시작 HEAD | `214ddc0` — "Phase 3-E-32 보고서 + test_12 enum 멤버 구멍 수정 (AUDIT-ONLY)" |
| 그 직전 | `6c6019a` Phase 3-E-32 · `89f37cf` Phase 3-E-31 보고서 |
| 작업 트리 | 깨끗함 (`git status --porcelain` 비어 있음) |
| `89f37cf..HEAD` production diff | **0** — 3-E-31 이후 production 은 손대지 않았다 |

프롬프트가 적은 `c690091732.lua` 는 실제로 **`c69091732.lua`** 다 (자릿수 하나
많다). 파일 이름을 추측하지 않고 저장소에서 확인했다.

## 2. Phase 3-E-32 기준선과의 관계

3-E-32 가 세운 것 — **`EVENT_FREE_CHAIN` 은 사건이 아니라 발동형 효과의 "유발
조건 없음" 분류값**이고, 등재된 함정 5장 중 의적의 입문서(69091732)만 Lua 에
`SetCondition` 을 갖는다. 판정은 `C. ACTIVATION_TIMING_FITS` 였다.

3-E-33 은 그 발견의 **다음 칸**을 본다. 3-E-32 가 "`code` 는 시점 분류다" 를
확정했으므로, 이제 **발동 조건 자체가 어디에서 와서 어디에 들어갔는가**를 묻는다.
3-E-32 의 결론을 전제로 쓰되 다시 측정했고, 숫자가 전부 재현되었다
(`EVENT_FREE_CHAIN` 블록 4,909개 · 등재 16개 전부 `EVENT_FREE_CHAIN`).

## 3. 핵심 질문에 대한 답 (§3)

| # | 질문 | 답 |
|---|---|---|
| 1 | `activation` 은 원본 Lua 의 어디에서 오는가 | **두 곳**이다 — `SetCondition`, 그리고 `SetTarget` 의 `chk==0` 분기 |
| 2 | 파서는 `SetCondition` 을 읽는가 | **`sources/lua_loader.py` 는 읽지 않는다.** 읽는 곳은 `analysis/effect_analyzer.py::_collect_handlers` 하나뿐 |
| 3 | `EffectSpec` 에 조건 칸이 있는가 | **없다** — `index`/`effect_types`/`code`/`ranges`/`target_ranges`/`categories`/`properties`/`count_limit`/`cloned_from` 9칸 |
| 4 | `SetCondition` 과 `SetTarget` 은 같은 뜻인가 | **아니다.** 전수 교차 집계에서 네 범주가 모두 비어 있지 않다 (§10) |
| 5 | `SetTarget` 은 대상 선택만 하는가 | **아니다.** `chk==0` 분기는 **발동 적법성 검사**이고 `chk~=0` 분기가 대상 선택이다 |
| 6 | `activation=None` 은 무슨 뜻인가 | docstring 은 "적지 않았다", 실행은 "조건 없음" — **둘이 어긋난다** (§8) |
| 7 | 지금 `SetCondition` 을 잃은 등재 효과가 있는가 | **없다** (`test_11`) |
| 8 | `activation` 이 `SetTarget` 에서 온 것이 있는가 | **8개 중 7개** (`test_12`) |
| 9 | 그 출처가 데이터에 적혀 있는가 | **아니다** — `library.py` 주석 산문에만 있다 |
| 10 | `EVENT_FREE_CHAIN` 이 "조건 없음" 으로 접혔는가 | **아니다.** 의적의 입문서의 조건은 실제로 옮겨져 있다 (`test_06`) |
| 11 | `UNKNOWN` 이 `FALSE` 로 바뀌는 자리가 있는가 | **없다** (`test_07`) — 발동기·실행기 둘 다 |
| 12 | 정보가 사라졌는가 | **아니다.** `SetCondition` 원문은 `analysis` 공개 경로에서 읽힌다 (`test_13`) |

## 4. 원본 Lua → parser → `EffectSpec` → `EffectDefinition` 추적

```
c<id>.lua
  │  e1:SetCode(EVENT_FREE_CHAIN)        ┐
  │  e1:SetType(EFFECT_TYPE_ACTIVATE)    │ lua_loader 가 읽는 것
  │  e1:SetRange(...) / SetProperty(...) ┘
  │  e1:SetCondition(s.condition)        ┐
  │  e1:SetTarget(s.target)              │ lua_loader 는 **읽지 않는다**
  │  e1:SetCost(...) / SetOperation(...) ┘
  │
  ├─ sources/lua_loader.py  ──→ EffectSpec(index, effect_types, code, ranges,
  │                                        target_ranges, categories, properties,
  │                                        count_limit, cloned_from)
  │                             → core.Card.script.effects[ordinal]
  │
  ├─ analysis/effect_analyzer.py::_collect_handlers
  │        → {"Condition": "s.condition", "Target": "s.target", ...}
  │        → ActivationCondition(has_condition_function, raw, tree,
  │                              requirements, limit, unparsed)
  │
  └─ engine/effect/library.py  (**손으로** 적는다 — 컴파일러 없음, STRUCTURAL-7)
           → EffectDefinition(activation=Condition | None, targets=(...), ...)
```

두 갈래가 **합쳐지지 않는다**. `analysis` 쪽 `ActivationCondition` 과 `engine`
쪽 `EffectDefinition.activation` 사이에 코드 경로가 없다 — 사람이 읽고 옮긴다.
`EffectRef(card_id, ordinal)` 이 둘을 가리키는 유일한 다리다.

## 5. `SetCondition` 의 의미 (§5)

- **무엇인가**: EDOPro 의 효과 발동 조건 함수. 서명은
  `(e,tp,eg,ep,ev,re,r,rp)` 이고 `chk` 인자가 **없다** — 즉 묻는 것이 하나다,
  "지금 이 효과를 발동할 수 있는가".
- **적는 모양이 둘이다**: 이름 붙은 함수 참조(`s.condition` · `s.actcon` ·
  `s.thcon` · `s.accon`)와 인라인 람다(`function(e,tp) return ... end`).
  `test_02`/`test_04` 가 두 모양을 실제 카드로 고정한다.
- **블록 단위 성질이다**: 라뷰린스 쿠클락(2511)은 `e[0]` 에 없고 `e[1]`·`e[2]`
  에 있다. 카드가 아니라 효과 블록이 조건을 갖는다.
- **`analysis` 가 보존한다**: `ActivationCondition.has_condition_function` 이
  유무를, `raw` 가 인자 원문을, `tree`/`requirements` 가 읽어낸 구조를,
  `unparsed` 가 읽지 못한 호출 이름을 각각 들고 있다.
- **전수 12,437개 블록**이 갖는다 (34,631개 중 35.9%).

## 6. `SetTarget` 의 의미 (§6)

여기가 이번 감사의 분기점이다. `SetTarget` 은 **이름과 달리 한 가지 일을 하지
않는다.** 서명에 `chk` 가 있고, 그 값으로 두 질문에 답한다.

```lua
function s.target(e,tp,eg,ep,ev,re,r,rp,chk)
	if chk==0 then return Duel.IsPlayerCanDraw(tp,2) end   -- 발동 적법성
	Duel.SetTargetPlayer(tp)                               -- 대상/파라미터 선언
	Duel.SetTargetParam(2)
	Duel.SetOperationInfo(0,CATEGORY_DRAW,nil,0,tp,2)
end
```
(`c55144522.lua` 욕망의 항아리 — 실제 원문)

- `chk==0` → **불린을 돌려주는 적법성 질문.** "이 효과를 지금 발동해도 되는가."
- `chk~=0` → **대상 선택과 조작 정보 선언.** 돌려주는 값이 없다.

그러므로 `SetTarget` 의 `chk==0` 분기를 발동 조건 쪽으로 옮기는 것은
**의미상 맞다.** 틀린 것은 "SetTarget = 대상 선택" 이라는 이름 읽기다.

의적의 입문서는 둘이 명확히 갈린 예다 — `s.condition` 이 실제 조건(상대 패
5장 이상)이고, `s.target` 의 `chk==0` 은 `return true` 다. 즉 **적법성 제약이
없고 조건만 있다.**

전수 19,262개 블록이 `SetTarget` 을 갖는다 (55.6%).

## 7. 네 범주 교차 감사 (§7)

| | `SetTarget` 없음 | `SetTarget` 있음 | 합 |
|---|---|---|---|
| **`SetCondition` 없음** | 11,626 (33.6%) | 10,568 (30.5%) | 22,194 |
| **`SetCondition` 있음** | 3,743 (10.8%) | 8,694 (25.1%) | 12,437 |
| **합** | 15,369 | 19,262 | **34,631** |

**네 범주가 모두 비어 있지 않다.** 따라서 §7 이 묻는 두 명제가 **둘 다 거짓**이다.

- "`SetTarget` 이 있으면 `SetCondition` 이 있다" → 반례 **10,568개**
- "`SetCondition` 이 있으면 `SetTarget` 이 필요하다" → 반례 **3,743개**

그래서 `EffectDefinition` 이 `activation` 과 `targets` 를 **따로** 들고 있는
것은 중복이 아니라 필요다. 하나로 합치면 22,194 + 15,369 개 블록이 자기와
다른 사실을 주장하게 된다.

각 범주의 실제 카드 2장씩은 §11 에 있다.

## 8. `EffectDefinition.activation` 의미 감사 (§8) — **이번 Phase 의 중심 발견**

### 8-1. 같은 타입·같은 기본값에 **반대 계약**이 적혀 있다

`engine/` 안의 두 production dataclass 다.

```python
# engine/effect/definition.py:250
    activation: Condition | None = None
    """발동 조건. ``None`` 이면 **조건이 없다는 뜻이 아니라 적지 않았다는 뜻**이다."""
```

```python
# engine/observation_grant.py:88
    condition: Condition | None = None
    """
    언제 살아 있는가 (``SetCondition``).

    ``None`` 은 **"조건이 없다"** 는 뜻이다 — 원본에 ``SetCondition`` 이
    없으면 조건이 없는 것이 사실이다. 옮기지 못한 조건은 ``None`` 이
    아니라 :class:`~engine.condition.UnimplementedRule` 로 적어야
    ``UNKNOWN`` 이 되고, 그러면 권한이 생기지 않는다.
    """
```

타입이 같고(`Condition | None`) 기본값이 같고(`None`) **뜻이 반대다.**
`test_09` 가 두 계약을 동시에 고정한다 — 어느 쪽이 맞다고 주장하지 않고,
**두 계약이 같은 저장소에 함께 적혀 있다는 사실**을 고정한다.

### 8-2. 실행은 `ObservationGrant` 쪽 계약대로 동작한다

`activation is None` 을 만나면 두 production 독자가 모두 **넘어간다** —
즉 "조건 없음" 으로 처리하고 발동을 허가한다.

```python
# engine/activation.py:658  EffectActivator._check_condition
        if definition.activation is None:
            return None            # 통과

# engine/effect/executor.py:968  EffectExecutor._check_condition
        if definition.activation is None:
            return None            # 통과
```

그래서 `None` 은 적힌 뜻("적지 않았다")과 달리 **허가 쪽으로 기운다.**
`SetCondition` 이 있는 효과를 `None` 으로 등재하면 조건 없이 발동한다.
`test_10` 이 그 동작을 고정하고, `test_11` 이 **지금 그런 등재 효과는 하나도
없다**는 것을 확인한다.

`UnimplementedRule` 로 적으면 `UNKNOWN` 이 되어 발동이 막히므로, 기울기를
막을 수단은 **이미 있다**. 쓰이지 않고 있을 뿐이다 — 등재 16개 중
`UnimplementedRule` 은 **0개**.

### 8-3. `NO` · `UNKNOWN` · `FALSE` 는 세 가지가 전부 표현 가능하다 (§8-7/8/9)

| 적고 싶은 사실 | 적는 방법 | 발동 결과 |
|---|---|---|
| 조건이 **없다** (원본에 `SetCondition` 없음) | `activation=None` | `ACTIVATED` |
| 조건이 있는데 **아직 못 옮겼다** | `UnimplementedRule("...")` | `CONDITION_UNKNOWN` + `RULE_NOT_IMPLEMENTED` |
| 조건이 **거짓이다** | `Always(ConditionResult.FALSE)` | `CONDITION_FALSE` |
| 조건이 **참이다** | `Always()` | `ACTIVATED` |

`test_07`/`test_15` 가 네 경우를 production 발동기·실행기로 전부 돌린다.
**새 필드도 새 enum 도 필요하지 않다.** 부족한 것은 표현력이 아니라
`None` 하나가 두 사실("없다" · "안 적었다")을 겸하고 있다는 **계약의 모호함**이다.

### 8-4. `activation` 은 두 출처를 섞어 들고 있고, 구분할 칸이 없다

등재 16개 중 `activation` 이 있는 것은 **8개**. 그중 **7개**는 Lua 에
`SetCondition` 이 **아예 없다**.

| 카드 | `activation` | 원본 위치 | `has_condition_function` |
|---|---|---|---|
| 55144522 욕망의 항아리 | `ZoneCountAtLeast(CONTROLLER, DECK, 2)` | `s.target` `chk==0`: `Duel.IsPlayerCanDraw(tp,2)` | **False** |
| 5915629 욕망의 선물 | `ZoneCountAtLeast(OPPONENT, DECK, 2)` | `s.target` `chk==0`: `Duel.IsPlayerCanDraw(1-tp,2)` | **False** |
| 70368879 갑부 고블린 | `ZoneCountAtLeast(CONTROLLER, DECK, 1)` | `s.target` `chk==0`: `Duel.IsPlayerCanDraw(tp,1)` | **False** |
| 92595643 벌금 | `ZoneCountAtLeast(CONTROLLER, HAND, 2)` | `s.target` `chk==0`: `IsExistingMatchingCard(... LOCATION_HAND ... 2 ...)` | **False** |
| 81439173 어리석은 매장 | `ZoneCountAtLeast(CONTROLLER, DECK, 1)` | `s.target` `chk==0`: `IsExistingMatchingCard(... LOCATION_DECK ... 1 ...)` | **False** |
| 73148972 무정한 말살 | `And(ZoneCountAtLeast(CONTROLLER, MZONE, 1), ZoneCountAtLeast(OPPONENT, HAND, 1))` | `s.target` `chk==0`: `IsExistingTarget(...) and GetFieldGroupCount(tp,0,LOCATION_HAND)>0` | **False** |
| 22589918 리로드 | `ZoneCountAtLeast(CONTROLLER, HAND, 1, 이 카드 제외)` | `s.target` `chk==0`: `IsPlayerCanDraw(tp) and IsExistingMatchingCard(Card.IsAbleToDeck,tp,LOCATION_HAND,0,1,e:GetHandler())` | **False** |
| **69091732 의적의 입문서** | `ZoneCountAtLeast(OPPONENT, HAND, 5)` | **`s.condition`**: `GetFieldGroupCount(tp,0,LOCATION_HAND)>4` | **True** |

`has_condition_function` 열은 `analysis` 공개 경로가 돌려주는 값이다. 즉
**`analysis` 는 "이 카드에 `SetCondition` 이 없다" 고 말하는데 `engine` 은
`activation` 을 들고 있다.** 두 계층이 같은 효과에 대해 다른 모양을 보여 준다.

§6 에서 보았듯 `chk==0` 분기는 실제로 발동 적법성 검사이므로 **옮긴 것 자체는
틀리지 않았다.** 틀린 것도 잃은 것도 아니다. 문제는 **그 사실이 데이터에 없다**는
것이다 — 출처는 `library.py` 의 주석 산문에만 있다.

```python
# engine/effect/library.py:225
        # ``s.target`` 의 ``Duel.IsPlayerCanDraw(tp,2)`` 중 **덱 장수 부분만**
        # 옮겼다. "드로우를 막는 효과" 는 이 엔진에 없으므로 그 부분은
        # 확인하지 않는다 — 이 조건은 필요조건이지 충분조건이 아니다.
```

이 주석은 **정확하고 정직하다** (필요조건/충분조건 구분까지 적는다). 그러나
기계가 읽을 수 없다. `EffectDefinition` 에 `activation_source` 같은 칸은 없고
(`test_12` 가 그 부재를 구조적으로 고정한다), `EffectProvenance` 는 효과 전체의
출처를 적되 **필드별 출처는 적지 않는다**.

## 9. 기존 semantic layer 와의 충돌 여부 (§9)

| 계층 | 조건을 적는 칸 | `None` 의 뜻 | 충돌? |
|---|---|---|---|
| `analysis/effect_model.py` `ActivationCondition` | `tree` + `requirements` + `has_condition_function` + `raw` + `unparsed` | `tree=None` 은 "읽어내지 못했다" (그래서 `raw`·`unparsed` 가 남는다) | 없음 — **유무와 내용을 다른 칸에 적는다** |
| `engine/observation_grant.py` `ObservationGrant` | `condition` | "조건이 없다" | — |
| `engine/effect/definition.py` `EffectDefinition` | `activation` | "적지 않았다" | **`ObservationGrant` 와 반대** |
| `engine/trigger.py` `TriggerSpec` | `condition` | (유발 조건, 발동 조건과 별개 축) | 없음 — 3-E-31 에서 확인 |

가장 깔끔한 쪽이 `analysis` 다. `has_condition_function`(유무)과 `tree`(내용)을
**갈라 두었기 때문에** "원본에 없다" 와 "있는데 못 읽었다" 가 섞이지 않는다.
`engine` 쪽 `activation` 한 칸은 그 두 사실을 겸한다.

## 10. 코퍼스 전수 측정 (§10)

고유 스크립트 **12,687개** · 효과 블록 **34,631개**, 건너뛴 스크립트 **0개**.
(측정이 불완전하면 결론이 거짓이 되므로 `0` 임을 테스트가 함께 검증한다.)

| 슬롯 | 블록 수 | 비율 |
|---|---|---|
| `SetCondition` | 12,437 | 35.9% |
| `SetTarget` | 19,262 | 55.6% |
| `SetCost` | 5,007 | 14.5% |

`EVENT_FREE_CHAIN` 블록 **4,909개**의 분해:

| | `SetTarget` 없음 | `SetTarget` 있음 |
|---|---|---|
| `SetCondition` 없음 | 1,117 (22.8%) | 2,373 (48.3%) |
| `SetCondition` 있음 | **138 (2.8%)** | **1,281 (26.1%)** |

**`EVENT_FREE_CHAIN` + `SetCondition` = 1,419개 (28.9%).** `EVENT_FREE_CHAIN`
을 "조건 없음" 으로 읽으면 이 1,419개가 전부 틀린다. 3-E-32 의 결론이
전수에서도 유지된다.

## 11. 실제 카드 샘플링 (§11) — 범주마다 2장, 이름이 아니라 데이터로 골랐다

| 사례 | 카드 | `code` | `SetCondition` | `SetTarget` |
|---|---|---|---|---|
| **1. 조건만** | 847915 `e[0]` 넘버즈 월 | `EVENT_FREE_CHAIN` | `s.actcon` | — |
| | 885016 `e[0]` 멀티유니버스 | `EVENT_FREE_CHAIN` | `function(e,tp) return not Duel.IsExistingMatchingCard(Card.IsFaceup,tp,LOCATION_FZONE,0,1,nil) end` | — |
| **2. 대상만** | 27551 `e[0]` 리미트 리버스 | `EVENT_FREE_CHAIN` | — | `s.target` |
| | 35699 `e[2]` SPYRAL－보텍스 | `EVENT_FREE_CHAIN` | — | `s.destg` |
| **3. 둘 다** | 111280 `e[0]` 매직 익스팬드 | `EVENT_FREE_CHAIN` | `s.condition` | `s.target` |
| | 126218 `e[0]` 악마의 주사위 | `EVENT_FREE_CHAIN` | `function() return not (Duel.IsPhase(PHASE_DAMAGE) and Duel.IsDamageCalculated()) end` | `s.target` |
| **4. 둘 다 없음** | 2511 `e[0]` 라뷰린스 쿠클락 | `EVENT_FREE_CHAIN` | — | — |
| | 164710 `e[0]` 소인의 장난 | `EVENT_FREE_CHAIN` | — | — |
| **5·6. `EVENT_FREE_CHAIN` 아님** | 2511 `e[1]` 라뷰린스 쿠클락 | `EVENT_TO_GRAVE` | `s.thcon` | `s.thtg` |
| | 2511 `e[2]` 라뷰린스 쿠클락 | `EFFECT_TRAP_ACT_IN_SET_TURN` | `s.accon` | `function(e,c) return c:IsNormalTrap() end` |

**라뷰린스 쿠클락 한 장이 세 블록을 갖고 `code` 가 셋 다 다르다** —
`EVENT_FREE_CHAIN` · `EVENT_TO_GRAVE` · `EFFECT_TRAP_ACT_IN_SET_TURN`. 그리고
`e[0]` 은 조건·대상이 둘 다 없고 `e[1]`·`e[2]` 는 둘 다 있다. **조건은 카드의
성질이 아니라 블록의 성질이다.** 카드 단위로 묶어 세면 틀린 결론이 나온다.

## 12. Data-loss 판정 (§12)

**`ACTUALLY_LOST` 가 아니다.**

- `SetCondition` 원문은 `analysis` **공개 경로**에서 읽힌다 —
  `EffectAnalyzer.analyze(card).effects[ordinal].activation` 의
  `has_condition_function` · `raw` · `tree` · `requirements` · `unparsed`.
  `test_13` 이 §11 의 열 블록 전부에 대해 확인한다.
- `sources/lua_loader.py` 는 네 슬롯을 읽지 않는다. 그것은 **유실이 아니라
  계층 경계다** — 슬롯 해석은 `analysis` 의 일이고, 파서는 등록 메타데이터만
  본다. `test_13` 이 그 경계도 고정한다.
- 등재된 효과 중 `SetCondition` 이 있으면서 `activation=None` 인 것은
  **0개** (`test_11`).

따라서 판정은 `D` 가 아니다. 다만 **보존을 구조가 보장하지 않는다** — 손으로
맞춘 결과가 맞은 것이고, 다음 카드에서 틀릴 수 있다. 그것이 `B` 다.

## 13. Production reachability (§13)

`definition.activation` / `self.activation` 을 **읽는** 곳 (AST 로 셌다 —
주석·docstring 은 세지 않는다):

| 파일 | 하는 일 |
|---|---|
| `engine/activation.py` | `EffectActivator._check_condition` — 발동 전 판정 |
| `engine/effect/executor.py` | `EffectExecutor._check_condition` — 해결 중 판정 |
| `engine/effect/definition.py` | `canonical_state()` · `to_dict()` · `describe_ko()` |
| `engine/trigger.py` | 주석에서 언급 (구조적 읽기는 없음) |

**읽지 않는 곳**: `engine/duel.py` · `engine/action_validation.py` ·
`engine/activation_timing.py` · `engine/trigger_chain.py` · `agent/search.py` ·
`agent/simulation.py` · `agent/evaluation.py`. `test_14` 가 양쪽을 고정한다.

즉 `activation` 은 **발동 계층과 해결 계층에서만** 읽히고, AI·탐색은 그
결과(합법 행동 목록)만 본다. ADR-007 의 `GameStateView → LegalActions → AI`
경계가 유지되고 있다.

## 14. Trigger 계층과의 경계 (§14)

3-E-31 의 결론을 다시 확인했다 — `EffectDefinition.activation` 은 **발동 조건**
축이고, `TriggerSpec.condition` 은 **유발 조건** 축이다. 둘은 다른 질문에 답한다.

- `activation`: "지금 이 효과를 발동할 수 있는가" (상태 질문)
- `TriggerSpec.condition`: "이 사건이 이 효과를 유발하는가" (사건 질문)

등재 16개는 **전부 `EVENT_FREE_CHAIN`** 이므로 유발 축이 비어 있는 효과들이고,
`TriggerSpec` 은 production 에서 **0개** 생성된다 (3-E-29 · 3-E-31 측정).
이번 발견은 그 경계를 건드리지 않는다 — `SetCondition` 을 Trigger 계층으로
옮겨야 한다는 근거가 **없다**.

## 15. Hidden Information (§15)

새 관측 경로를 만들지 않았다. 감사 테스트는 다음만 읽는다.

- Lua 스크립트 파일 (공개 원본)
- `CardRepository` (공개 카드 데이터)
- `EFFECT_LIBRARY` (손 등록 정의)
- production 발동기·실행기를 기존 테스트 하네스
  (`tests/test_validation_code_consistency.py`) 로 호출

조건 평가는 production 과 똑같이 `GameStateView.from_state(state, viewer=...)`
를 지나간다. `UNKNOWN` 을 허가로 바꾸는 자리를 만들지 않았고, `test_07` 이
오히려 그 금지를 고정한다.

## 16. AI / Search 영향 (§16)

**없다.** §13 이 측정한 대로 `agent/` 의 어느 파일도 `activation` 을 읽지
않는다. 탐색은 `legal_actions()` 가 돌려주는 행동만 보고, 그 목록은 발동
계층이 이미 `activation` 을 적용한 결과다. 이번 Phase 가 `activation` 값을
하나도 바꾸지 않았으므로 탐색이 보는 목록도 그대로다 — 전체 회귀가 그것을
확인한다.

결정론·RNG 도 건드리지 않았다. 감사 테스트는 셔플하지 않는 기존 `new_state()`
를 쓰고, 판 상태 해시가 바뀌지 않음을 함께 확인한다 (`test_07`).

## 17. Engine 변경 금지 준수 (§17)

```
$ git diff --stat 214ddc0..HEAD -- engine/ agent/ core/ analysis/ sources/
(출력 없음)
```

더한 파일은 둘이다.

- `tests/test_effectdefinition_activation_audit.py` (새 파일, 15개 테스트)
- `docs/phase3e33-effectdefinition-activation-audit.md` (이 문서)

**기존 테스트를 하나도 삭제·수정하지 않았다.** `skip` 을 더하지 않았고
assertion 을 약하게 바꾸지 않았다. 새 enum · 새 필드 · 새 status · 새 계층을
하나도 만들지 않았다.

## 18. 테스트 (§18)

`tests/test_effectdefinition_activation_audit.py` — **15개, 전부 통과.**

| # | 무엇을 고정하는가 | §18 요구 |
|---|---|---|
| 01 | 네 범주가 모두 비어 있지 않다 (34,631 블록 전수) | Test 1 |
| 02 | `SetCondition` 만 있는 실제 카드 2장 (+ 참조형/인라인형 두 모양) | Test 2 |
| 03 | `SetTarget` 만 있는 실제 카드 2장 | Test 3 |
| 04 | 둘 다 있는 실제 카드 2장 | Test 4 |
| 05 | 둘 다 없는 실제 카드 2장 + 한 카드 세 블록이 다 다르다 | Test 5 |
| 06 | `EVENT_FREE_CHAIN` + `SetCondition` 1,419개 · 의적의 입문서의 조건이 실제로 옮겨져 있다 | Test 6 |
| 07 | `UNKNOWN` 이 `FALSE` 로 바뀌지 않는다 (발동기·실행기 둘 다) | Test 7 |
| 08 | 대상 요구 ≠ 발동 조건 (칸·직렬화·status enum·실제 데이터 네 축) | Test 8 |
| 09 | **같은 타입·같은 기본값에 반대 계약이 적혀 있다** | 중심 발견 |
| 10 | 두 production 독자가 모두 `None` 을 넘긴다 (실행은 "조건 없음") | §8 |
| 11 | `SetCondition` 을 잃은 등재 효과가 0개다 | §12 |
| 12 | `activation` 8개 중 7개가 `SetTarget` 에서 왔고 출처 칸이 없다 | §8 |
| 13 | 원문이 `analysis` 공개 경로에서 여전히 읽힌다 | §12 |
| 14 | `activation` 을 읽는 곳 / 읽지 않는 곳 | §13 |
| 15 | `UNKNOWN`·`FALSE`·복합 조건이 이미 다 표현 가능하다 | §20 |

### 고의 위반 검증

주장이 정말 잡히는지 확인하려고 production 에 결함을 **일부러** 넣고 테스트가
잡는지 보았다. 전부 되돌렸다 (commit 뒤에 실행했으므로 작업 트리로 복구를
검증할 수 있다).

| 주입 | 잡은 테스트 |
|---|---|
| A. `activation` 의 `None` 계약을 `ObservationGrant` 쪽으로 베낀다 | `test_09` |
| B. 발동기가 `UNKNOWN` 을 `CONDITION_FALSE` 로 접는다 | `test_07` |
| C. `canonical_state()` 가 `activation` 을 빼먹는다 | `test_08` |
| D. `EffectDefinition` 에 `activation_source` 칸을 더한다 | `test_12` |
| E. 욕망의 항아리의 `activation` 을 떼어낸다 | `test_12` |
| F. `agent/search.py` 가 `activation` 을 읽는다 | `test_14` |
| G. 파서가 `SetCondition` 을 읽게 만든다 | `test_13` |
| H. 발동기가 `activation=None` 을 `UNKNOWN` 으로 바꾼다 | `test_10` |

여덟 가지 모두 잡혔고, 작업 트리는 전부 되돌아갔다 (`git status` 비어 있음).
정직하게 적어 둘 한 가지 — **G 는 소스 문자열 단정이다.** `test_13` 의 계층
경계 주장은 `sources/lua_loader.py` 본문에 `SetCondition` 등이 나타나지 않는다는
것이고, 동작이 아니라 문면을 본다. 파서가 슬롯을 읽기 시작하면 그 문자열이
반드시 생기므로 신호로는 충분하지만, 다른 이름으로 읽는 구현은 잡지 못한다.

### 회귀

| | 전 (3-E-32 완료 시점) | 후 |
|---|---|---|
| 통과 | 3,744 | 3,759 |
| 건너뜀 | 4 | 4 |
| 실패 | 0 | 0 |

## 19. 최종 판정 — **B. ACTIVATION_NEEDS_BOUNDARY_CLARIFICATION**

다른 후보를 고르지 않은 이유를 먼저 적는다.

- **A. ACTIVATION_SEMANTICS_ALREADY_SEPARATED 가 아니다.** `SetCondition` 과
  `SetTarget` 은 원본에서 분리되어 있고 `analysis` 도 분리해 들고 있지만,
  `engine` 쪽 `activation` **한 칸이 두 출처를 겸한다** (8개 중 7개가
  `SetTarget` 에서 왔고 그 사실이 데이터에 없다). 게다가 `Condition | None`
  의 `None` 계약이 `engine/` 안에서 **반대로** 적혀 있다. "이미 분리되어
  있다" 고 적으면 그 두 사실을 숨긴다.
- **C. ACTIVATION_TARGET_CONFLATION 이 아니다.** 섞였다고 적으려면 **틀린
  판정**이 나와야 한다. §6 이 보인 대로 `SetTarget` 의 `chk==0` 분기는 실제로
  발동 적법성 검사이므로 그것을 발동 조건으로 옮긴 7개는 **의미상 맞다**.
  그리고 `targets`(대상 선택)와 `activation`(조건)은 칸·직렬화 자리·거부
  status 가 모두 따로다 (`test_08`). 혼동이 실제 판정을 틀리게 만든 사례를
  **하나도 찾지 못했다.**
- **D. ACTIVATION_INFORMATION_LOSS 가 아니다.** 원문이 `analysis` 공개 경로에
  남아 있고(`test_13`), `SetCondition` 을 잃은 등재 효과가 0개다(`test_11`).
  **근거 없이 D 를 고르지 않는다.**
- **E. UNKNOWN 이 아니다.** 34,631 블록 전수와 등재 16개 전부를 측정했고,
  §3 의 열두 질문에 모두 답했다. 모르는 채로 남은 것이 없다.

**B 를 고르는 근거는 두 가지다.**

1. **`Condition | None = None` 의 뜻이 `engine/` 안에서 둘로 갈려 있다**
   (§8-1). `EffectDefinition` 은 "적지 않았다", `ObservationGrant` 는 "없다".
   그런데 실행은 뒤쪽대로 동작한다 (§8-2) — 즉 `EffectDefinition` 의 docstring
   이 **자기 실행과 어긋난다**. 이것은 지금 틀린 판정을 내지는 않지만,
   다음 사람이 `SetCondition` 이 있는 효과를 `activation=None` 으로 등재하면
   **조건 없이 발동하는 쪽으로 틀린다** — 프로젝트가 금지한 방향이다.
2. **`activation` 의 출처를 구별할 칸이 없다** (§8-4). 지금은 주석이 정확해서
   맞지만, 주석은 기계가 읽지 못한다. `SetCondition` 에서 온 조건과
   `SetTarget` `chk==0` 에서 온 적법성 제약은 **다른 사실**이고, 특히 후자는
   `library.py` 자신이 "필요조건이지 충분조건이 아니다" 라고 적는 **불완전한**
   조건이다. 그 불완전성이 데이터에 없다.

둘 다 **경계를 더 분명히 적어야 하는 문제**이고, 둘 다 지금 production 의
판정을 틀리게 하고 있지 않다. 그래서 `B` 다.

**그리고 이번 Phase 는 production 을 고치지 않는다.** 두 항목 모두 "어느 쪽
계약을 정본으로 삼을 것인가" 라는 **설계 결정**을 먼저 요구하고, 그 결정은
감사가 혼자 내릴 것이 아니다. §17 의 금지도 그대로 지켰다.

---

## §22 — 최종 질문 세 개에 대한 답

### Q1. 현재 `EffectDefinition.activation` 은 원본 Lua 의 activation semantics 를 충분히 보존하고 있는가?

**등재된 16개에 대해서는 보존하고 있다. 구조적으로는 보장되지 않는다.**

- 보존하고 있다는 근거: `SetCondition` 이 있는 등재 효과는 의적의 입문서
  하나뿐이고, 그 조건(`GetFieldGroupCount(tp,0,LOCATION_HAND)>4`)이 실제로
  `ZoneCountAtLeast(OPPONENT, HAND, 5)` 로 옮겨져 있다. `SetCondition` 을
  잃은 등재 효과는 **0개**다.
- 보장되지 않는다는 근거: `activation=None` 이 "조건 없음" 과 "안 적었음" 을
  겸하고, 실행은 앞쪽으로 읽는다. 그리고 `activation` 이 `SetCondition` 에서
  왔는지 `SetTarget` `chk==0` 에서 왔는지 **데이터로 알 수 없다**. 지금
  맞는 것은 손으로 맞춘 결과이고, 코퍼스에는 아직 등재하지 않은
  `SetCondition` 블록이 **12,436개** 더 있다.

### Q2. `SetCondition` 과 `SetTarget` 을 현재 구조에서 별개의 의미로 안전하게 취급할 수 있는가?

**취급할 수 있다 — 칸은 이미 따로 있고, 표현력도 충분하다. 안전하게 하려면
규칙을 글로 적어야 한다.**

- 할 수 있다는 근거: `activation`(조건)과 `targets`(대상 선택)는 다른 칸이고,
  `canonical_state()` 의 다른 자리이고, 거부 status 도 따로다
  (`CONDITION_*` · `*_TARGET` · `COST_*`). `UNKNOWN`·`FALSE`·복합 조건이
  전부 이미 표현 가능하다 (`test_15`). **새 필드도 새 enum 도 필요 없다.**
- 안전하지 않은 지점: `SetTarget` 이 한 함수 안에 두 일(`chk==0` 적법성 /
  `chk~=0` 대상 선택)을 담고 있다는 것이 **어디에도 글로 적혀 있지 않다.**
  이름만 보면 "SetTarget = 대상" 이라 읽게 되고, 그러면 7개 등재 효과가
  왜 `activation` 을 갖는지 설명되지 않는다. 다음 사람이 그 7개를 "잘못
  옮긴 것" 으로 보고 `None` 으로 되돌릴 위험이 실재한다.

### Q3. 다음 단계에서 production 변경이 필요한가, 아니면 추가 audit 이 필요한가?

**추가 audit 이 먼저다. 그다음이 (아주 작은) production 변경이다.**

production 변경이 **지금** 필요하지 않은 이유: 틀린 판정이 하나도 없고
(`test_11`), 표현력이 부족하지도 않다 (`test_15`). 고쳐야 하는 것은 **계약의
문장**이고, 어느 쪽을 정본으로 삼을지는 설계 결정이다.

필요한 순서는 이렇다.

1. **추가 audit**: `ObservationGrant.condition` 과 `EffectDefinition.activation`
   중 어느 계약이 프로젝트의 정본인지, 그리고 `engine/` 의 다른
   `Condition | None` 필드들(`TriggerSpec.condition` 등)이 어느 쪽을 따르는지
   전수 감사. 계약이 셋 이상으로 갈려 있을 수 있다 — 세지 않고 추측하지 않는다.
2. 그 결과에 따라 **docstring 한 줄**(production diff 1~2줄) 또는
   **등재 효과의 `None` → `UnimplementedRule` 치환**. 어느 쪽이든 새 필드·새
   enum 은 필요 없다.
3. `activation` 의 출처 구분은 **지금 더하지 않는다.** 등재가 16개뿐이라
   주석으로 충분하고, 칸을 더하면 "컴파일러가 없는데 컴파일러용 칸이 생기는"
   상태가 된다 (STRUCTURAL-7). 등재가 늘어나 주석으로 감당이 안 될 때
   다시 묻는다.

---

## 다음 Phase 후보 (하나만 제안한다)

**Phase 3-E-34 — `engine/` 전역 `Condition | None` 계약 정합성 감사**

`engine/` 안의 모든 `Condition | None` 필드를 AST 로 전수 수집해서, 각 필드가
`None` 에 어떤 뜻을 적고 있고 **그 독자가 실제로 어떻게 읽는지**를 짝지어
측정한다. 3-E-33 이 두 개를 찾았으므로 셋 이상일 수 있다. AUDIT-ONLY 로 시작해
계약이 몇 가지로 갈려 있는지 먼저 세고, 정본을 고르는 일은 그 측정 뒤에 둔다.

**이 Phase 는 여기서 멈춘다. 다음 Phase 는 임의로 진행하지 않는다.**
