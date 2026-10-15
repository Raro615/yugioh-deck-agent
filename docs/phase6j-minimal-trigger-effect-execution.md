# Phase 6-J — 최소 TRIGGER 효과 실행 경로 구축

작업 브랜치: `claude/pensive-goodall-te1egy`
선행: [6-E](phase6e-trigger-analysis-candidate-integration.md) ·
[6-F](phase6f-trigger-event-subject-validation.md) ·
[6-G](phase6g-trigger-activation-location.md) ·
[6-H](phase6h-field-trigger-condition-integration.md) ·
[6-I](phase6i-trigger-duel-production-integration.md)

---

## 🔴 결과: **실행 경로 조사 및 차단 요인 규명 완료 · 실제 효과 실행 미달성**

§18 의 완료 기준 4~5 (실제 TRIGGER 효과 해결 · GameState 변화 검증) 를
**달성하지 못했다.** 달성한 척하지 않는다.

| §18 기준 | 결과 |
|---|---|
| 1. 기존 효과 실행 계층을 정확히 조사 | ✅ |
| 2. TRIGGER 와 실행 정의의 연결 범위 확인 | ✅ 0건 · 까닭까지 |
| 3. 공통 실행 연산 재사용 가능한 최소 사례 | ✅ 후보 24건 식별 |
| **4. 실제 Duel 에서 TRIGGER 효과 실행** | **❌ 미달성** |
| **5. GameState 변화 검증** | **❌ 미달성 (4가 선행)** |
| 6. 미지원 조건·효과가 실행되지 않는다 | ✅ |
| 7. Engine V1 · EventJournal 의미론 유지 | ✅ production 실행 경로 **무변경** |
| 8. 관련 회귀 통과 | ✅ 3,163 passed · 0 failed |
| 9. 차단 원인과 최소 후속안 보고 | ✅ §3 · §16 |

**실행을 막은 것은 실행기가 아니다.** 실행기는 13종 중 12종을 지원하고,
옮겨진 연산 중 지원 밖인 것은 **0건**이다. 막는 것은 실행보다 **위**에 있는
세 층이고, 그 셋을 이 Phase 가 실제 실행으로 특정했다.

---

## 1. 기존 효과 실행 계층의 실제 구조

```
PlayerAction(activate_effect)
    ↓  ActionValidator.validate              ← 규칙: 발동해도 되는가
    ↓  ActivationTimingChecker               ← 스펠 스피드 · 체인
    ↓  EffectActivator.can_activate/activate ← 등록 · 조건 · 대상
    ↓  Chain → ChainResolver
    ↓  EffectExecutor.execute                ← **계획 → 적용** 두 단계
    ↓  GameState 변경 + StateDelta
    ↓  EventJournal
```

### 1.1 `EffectExecutor` 가 할 줄 아는 일 — 13종 중 **12종**

| 연산 | 핸들러의 근거 |
|---|---|
| `draw` | `GameState.draw` |
| `change_life` | `PlayerState.change_life` |
| `special_summon` | `SummonProcedure` (Phase 2-T) |
| `shuffle` | `RandomSource.shuffle` + `ZoneContainer.reorder` |
| `destroy` · `send_to_grave` · `release` · `discard` | `GameState.move` → GRAVE (의미별) |
| `banish` | → REMOVED · `return_to_hand` → HAND · `return_to_deck` → DECK |
| `move` | 의미 없는 저수준 이동 |
| ~~`unknown`~~ | **유일한 미지원** — "표현되지 않은 일" |

계획과 적용이 갈라져 있고 (`_plan_*` / `_apply_*`), **판에 손대기 전에**
관문을 전부 지난다. 한 장만 처리되는 부분 적용이 없다 (STRUCTURAL-49).

### 1.2 비용과 해결이 갈라져 있다

`EffectDefinition.cost: CostGroup` 가 `operations` 와 따로 있고,
`Duel` 은 **비용이 없는 효과만** 후보로 낸다 — "비용을 치른 뒤 발동이
깨지면 되돌릴 방법이 없다" (ADR-008). 등록된 16건 전부 비용이 없어서
지금 그 관문은 아무것도 거르지 않는다 (STRUCTURAL-120).

### 1.3 대상·선택은 `TargetSpec` 가 표현한다

`TARGETING` · `CHOOSING` · `RANDOM` · `ALL` 네 종류가 이미 있고,
`CandidateSource`(존 · 소유자 · 술어)로 후보를 좁힌다. 실제로 쓰이고 있다 —
무정한 말살이 `TARGETING` + `RANDOM` 둘을 함께 쓴다.

---

## 2. 기존 EffectDefinition 및 EffectLibrary 지원 범위

16건. 전부 `ordinal == 0` 이고 전부 **마법**이며, 13건이 `executable` 이다.

| 연산 | 쓰는 항목 |
|---|---|
| `draw` | 4 |
| `change_life` | 3 |
| `send_to_grave` | 3 |
| `discard` | 2 |
| `destroy` · `return_to_hand` · `return_to_deck` · `shuffle` | 각 1 |
| **`special_summon`** | **0** |

실행 불가 3건이 **무엇이 없어서인지** 적어 두고 있고, 그 주석이 6-J 의
조사를 크게 줄였다.

| 카드 | 실행하지 않는 까닭 |
|---|---|
| 블랙홀 | 파괴 의미 + 존 전체 일괄 처리 (STRUCTURAL-10) |
| 죽은 자의 소생 | **소환 조건 판정(`IsCanBeSpecialSummoned`) + 표시 형식 선택(POS_FACEUP, STRUCTURAL-61)** |
| 로스트 | `aux.SpElimFilter` 미해석 + 공식 텍스트와 스크립트의 자리 불일치 |

🔴 **그 둘 중 하나는 이미 해결돼 있었다.** 표시 형식은
`SPECIAL_SUMMON_POSITION = Position.FACEUP_ATTACK` 로 **고정**되어 있고,
그 상수가 *"고를 수 없어서 하나로 고정했을 뿐이고 이것이 규칙이라고
주장하지 않는다"* 고 적는다. 즉 표시 형식은 **충실도의 한계**이고 실행을
막지 않는다. 남은 하나가 소환 조건 판정이다 (§3 의 B1).

`SPECIAL_SUMMON_FROM_ZONES = {HAND, GRAVE}` 이므로 **패에서의 특수 소환은
출발 자리도 지원된다.**

---

## 3. TRIGGER 실행을 막고 있던 정확한 원인 — **셋**

무는 순서대로. 위의 것이 아래를 가린다.

### B3 — 발동 절차가 없다 (4,173건 **전부**)

```
ActionValidator.validate(activate_effect, 패의 몬스터 유발 효과)
    → UNKNOWN / RULE_NOT_IMPLEMENTED
    → missing_rule = "monster-activation-timing
                      (기동 · 유발 · 플립 · 유발즉시 분류가 없다)"
```

**대조군이 결정적이다** — 같은 `activate_effect` 가 패의 통상 마법에는
`VALID` 다. 즉 "발동 자체를 못 한다" 가 아니라 **"몬스터 효과를 분류하는
층이 없다"** 이고, `UNKNOWN` 은 허가가 아니므로 `legal_actions` 가 그 행동을
**제시하지 않는다** (실측: `allowed` 에 `activate_effect` 가 없다).

이것이 가장 먼저 물고, **모든** TRIGGER 에 걸린다.

### B2 — 사건을 만들 수 없다 (`monster_summoned` 후보)

```
assess_normal_summon(레알 제넥스 마그나)
    → UNDETERMINED
    → "효과 몬스터는 카드 자신의 제약이 있을 수 있습니다 — 룰북은
       'most Effect Monsters (unless they have a specific restriction)'
       라고만 말합니다. 이 엔진은 그 제약을 아직 읽지 못합니다."
    → missing_rule = "summoning-condition (카드 텍스트의 소환 제약)"
```

「이 카드를 **일반 소환했을 때**」 가 유발 조건인 등록은 그 소환을 엔진이
수행할 수 없어 **사건 자체가 나지 않는다.** 통상 몬스터는 `ORDINARY` 로
소환되므로, 소환 절차가 없는 것이 아니라 **효과 몬스터의 제약을 읽는 층**이
없다.

### B1 — 해결 단계의 소환 관문 (`special_summon` 후보 9건)

```
EffectExecutor().summoning                     → UnknownSummonRuling
  .may_be_special_summoned(어느 인스턴스든)      → UNKNOWN   (언제나)
inspect.signature(build_executor)              → summoning 인자 **없음**
```

판정기가 *"소생 제한은 카드가 아니라 **이력**이다"* 라고 적는다 — 카드 한
장을 보고 답할 수 없는 질문이다. 그리고 production 조립 자리
(`build_executor`) 에 **그 판정기를 넘길 칸이 아예 없다.**

통과시킬 수 있는 `DeclaredSummonRuling` 은 존재하지만 **production 어디에서도
쓰이지 않는다** (실측 0곳). 거기에 꽂는 것이 6-J §8 이 금지한 "미지원 조건을
우회하는 테스트용 권한" 이다.

🔴 **B1·B2 를 고쳐도 B3 이 남는다.** 그래서 다음 구현 단위는 B3 이다 (§16).

---

## 4. 조사한 최소 실행 후보 및 선정 기준

카드 이름이나 ID 로 고르지 않았다. §5 의 10개 조건을 **데이터로** 걸러
전수 조사했다.

### 4.1 4,173건 → 후보 좁히기

| 단계 | 남은 수 |
|---|---|
| 컴파일된 TRIGGER 등록 | 4,173 |
| 해결 동작을 읽을 수 있다 | 3,447 |
| 그 동작을 engine 연산으로 옮길 수 있다 | 3,225 |
| 비용이 없다 | 2,999 |
| 6-F 의 주체 관문 + 6-G 의 위치 관문을 통과한다 | **31** |
| 그중 해결 단계가 준비된 것 | **24** |

### 4.2 두 관문 통과 31건의 해부

| 분류 | 수 | 왜 |
|---|---|---|
| 해결이 `special_summon` 이다 | 9 | **B1** |
| 해결이 다른 연산이고 사건이 `monster_summoned` | 14 | **B2** |
| 해결이 다른 연산이고 사건이 `card_drawn` | 1 | B1 (하나된 마음의 용도 특수 소환) |
| 해결 동작을 못 읽었다 | 4 | 브라이니글 ×2 · 커스 오브 뱀파이어 · 기동석기 도그라드 |
| 비용을 판정할 수 없다 | 1 | 수호신관 마하드 — 「상대에게 **보여주고**」 가 비용인지 모른다 |
| 옮길 수 없는 동작 | 2 | 프루프 프루플라스 — `normal_summon` 은 **연산이 아니다** (ADR-001) |

### 4.3 가장 가까웠던 둘

**점쟁이 마녀 (5장, 예: 31683874)** — 「①: 이 카드를 드로우했을 때, 이
카드를 상대에게 보여주고 발동할 수 있다. 이 카드를 패에서 특수 소환한다.」

| 조건 | 결과 |
|---|---|
| Lua 등록 · `EffectRef` 명확 | ✅ |
| 사건 종류 지원 (`card_drawn`) | ✅ 욕망의 항아리로 **실제로 만들었다** |
| 주체 (SELF) · 위치 (HAND) | ✅ 둘 다 통과 (6-I 가 증명) |
| 발동 조건 | ✅ **조건 함수가 아예 없다** |
| 비용 · 선택 | ✅ 둘 다 없다 |
| 해결 연산 | ⚠️ `special_summon` — **B1** |
| 발동 절차 | ❌ **B3** |

**레알 제넥스 마그나 (1533292)** — 「①: 이 카드를 일반 소환했을 때에 발동할
수 있다. 덱에서 레벨 2 의 "레알 제넥스" 몬스터 1장을 패에 넣는다.」

해결이 `to_hand` 라서 **소환 관문이 필요 없는 유일한 모양**이지만, 사건을
만들 수 없다 (**B2**) — 그리고 만들 수 있어도 **B3** 이 남는다.

---

## 5. 선택한 구현 방식과 대안 비교

| 대안 | 무엇을 해야 하는가 | 판단 |
|---|---|---|
| **A. 차단 요인을 측정하고 분류기만 만든다** | 읽기 전용 `integration` 모듈 1개 | **채택** |
| B. 점쟁이 마녀 ① 의 정의를 등록한다 | `EffectDefinition` 1건 | 기각 — **실행할 수 없는 정의**가 목록에 남는다. B1 이 열리지 않으므로 `executable=False` 로만 넣을 수 있고, 그것은 이 Phase 가 측정한 사실을 **데이터로 중복 기록**하는 것뿐이다 |
| C. `build_executor` 에 `summoning` 인자를 더하고 `DeclaredSummonRuling` 을 꽂는다 | 3줄 + 선언 | 기각 — §8 의 "우회 권한" 금지. 그리고 **B3 때문에 그래도 실행되지 않는다** |
| D. 소생 제한 규칙을 구현한다 | 인스턴스 **이력** 모델 (정규 소환 여부) | 기각 — `GameState`/`CardInstance` 구조 변경 (§15 · §16-11 → 승인 필요) |
| E. 몬스터 효과 발동 분류를 구현한다 (B3) | 기동/유발/플립/유발즉시 + 타이밍 창 | 기각 — §15 가 "체인·우선권 처리 전면 재설계" 와 "완전 자동 발동" 을 금지. **다음 Phase 의 본체**다 (§16) |

**A 를 고른 이유**: §18-9 가 요구하는 것이 "차단 원인과 최소 후속안의 명확한
보고" 이고, 그 보고를 **코드로 측정 가능하게** 만드는 것이 다음 단계가 실제로
쓸 수 있는 산출물이다. B~E 는 전부 B3 뒤에 줄을 서거나 금지선을 넘는다.

🔴 **B 를 특히 조심해서 기각했다.** 정의를 하나 적으면 "6-J 가 무언가
만들었다" 고 말할 수 있지만, 그 정의는 **영원히 실행되지 않는 채** 목록에
남는다. ADR-006 이 `executable` 을 따로 둔 이유가 그것이고, 실행할 수 없는
정의를 늘리는 것은 §16-7 이 금지한 "실행 구현의 존재와 실제 실행 가능성의
혼동" 을 **데이터에 새겨 넣는** 일이다.

---

## 6. 변경한 파일 및 함수

| 파일 | 증감 | 무엇 |
|---|---|---|
| `integration/execution_readiness.py` | +287 | `RESOLUTION_OPERATIONS` · `UNMAPPED_ACTIONS` · `ExecutionBlocker` · `ResolutionReadiness` · `operation_blockers` · `readiness_for` |
| `integration/__init__.py` | +10 | 재수출 |
| `tests/engine/test_trigger_effect_execution.py` | +803 | 신규 20개 |

🔴 **production 실행 경로를 한 줄도 고치지 않았다.** `engine/` 전체 ·
`EffectLibrary` · `EffectDefinition` · `Duel` · `EffectExecutor` 가
`git diff` 에 없다. `EFFECT_LIBRARY` 는 **16건 그대로**이고 정의를 하나도
추가하지 않았다 (§5 의 대안 B).

### 6.1 핵심 코드

```python
# analysis 의 해결 동작 → engine 의 실행 연산. **옮길 수 있는 것만** 적는다.
RESOLUTION_OPERATIONS: dict[ActionKind, OperationKind] = { … 11줄 … }
UNMAPPED_ACTIONS = frozenset(k for k in ActionKind if k not in RESOLUTION_OPERATIONS)

# 막는 층은 **집합**이다 — 한 효과가 여럿을 가질 수 있다.
def operation_blockers(actions, *, supported=SUPPORTED):
    if not actions:                       → OPERATION_UNREADABLE
    operation = RESOLUTION_OPERATIONS.get(action.kind)
    if operation is None:                 → OPERATION_UNTRANSLATABLE
    if operation not in supported:        → OPERATION_UNSUPPORTED

# 모르는 비용과 있는 비용을 **가른다**
if cost.kind is CostKind.UNKNOWN:         → COST_UNKNOWN
elif cost.kind is not CostKind.NONE:      → COST_UNPAYABLE
```

🔴 **`is_resolvable` 은 "발동할 수 있다" 가 아니다.** 이름에 `resolution` 이
들어 있는 것이 그 경계이고, 모듈 머리말이 B3 의 실측을 적어 둔다.
`is_executable` 이라고 불렀다면 거짓이 된다.

🔴 **이 모듈은 실행할 손이 없다** (`test_18` 이 AST 로 고정) — `execute` ·
`resolve` · `activate` · `apply` · `place` 중 어느 것도 부르지 않는다.
"해결할 수 있는가" 와 "해결한다" 를 한 모듈에 두면 전자가 후자의 허가처럼
읽힌다.

---

## 7. EffectDefinition 연결 결과

| 항목 | 수 |
|---|---|
| 컴파일된 TRIGGER 등록 | 4,173 |
| 서로 다른 `EffectRef` | 4,173 (**중복 0**) |
| `EffectDefinition` 이 있는 것 | **0** |
| 연결 불명 또는 모호 | **0** |

6-I 가 밝힌 그대로다 — **식별 문제가 아니다.** 두 계층이 같은
`EffectRef(card_id, ordinal)` 를 쓰고, `ordinal` 로 한 카드의 서로 다른
효과를 가른다 (`test_06`: `EffectRef(POT, 1)` 은 `None` 이다). 문제는 두
집합이 **서로소**라는 것이다.

---

## 8. 발동 조건 및 비용 판정 범위

| 층 | 판정할 수 있는가 |
|---|---|
| 사건 발생 조건 | ✅ 6-E (`EVENT_TIMING` 7종) |
| 사건 주체 관계 | ✅ 6-F (SELF 3,389 · OTHER 80) |
| 발동 위치 | ✅ 6-G (816건) |
| 카드 상태 | ✅ `GameStateView` |
| 발동 조건 | ⚠️ `Condition` AST 는 있고 **정의가 없어서** 묻지 못한다 |
| 발동 비용 | ⚠️ `CostGroup` 는 있고 치르는 계층이 없다 (260건이 비용 보유 · 18건은 비용을 **판정조차** 못 한다) |
| 대상 · 선택 | ✅ `TargetSpec` 4종 |
| 타이밍 · 우선권 | ❌ **B3** — `UNCHECKED_RULES` 6개 |
| 효과 해결 | ✅ 연산 12/13 · 옮겨진 것 중 지원 밖 **0건** |

🔴 **모르는 비용과 있는 비용을 갈랐다.** 있는 비용은 "치를 수 있는가" 를
물을 수 있고, 모르는 비용은 **물을 수조차 없다.** 수호신관 마하드가 후자다 —
「상대에게 **보여주고**」 가 비용인지 엔진이 모른다. 둘을 합치면 그 차이가
사라지고, 다음 단계가 엉뚱한 곳을 고친다.

---

## 9. 실제 TRIGGER 효과 실행 여부

**0건.** 그리고 그것을 **실제 듀얼에서** 확인했다 (`test_11`).

```
Duel.start(덱 = [욕망의 항아리] + [점쟁이 마녀]×20)
    ↓  legal_actions → activate_effect 55144522:e[0]      ← 실제 합법 행동
    ↓  apply → pass → "체인1 P0 … 를 해결했습니다"
CardDrawn × 2                                             ← 실제 delta
    ↓  registry_for_view → observe_all
```

뽑힌 점쟁이 마녀 자신의 드로우 사건에서:

| 항목 | 결과 |
|---|---|
| `stage` | `JUDGEMENT_PENDING` — 두 축은 통과 |
| `has_definition` | **False** |
| `is_executable` | **False** |
| `EXECUTION_READY` 도달 | **없음** |
| 미검사 규칙 | 6개 남아 있다 (숨기지 않는다) |

**사건은 났고 후보도 났고 두 축도 통과했는데 해결은 일어나지 않았다.**
그것이 6-J 의 한 줄 요약이다.

---

## 10. 실제 GameState 변경 및 EventJournal 검증

| 축 | 결과 | 근거 |
|---|---|---|
| 관찰 전후 `state_hash` | 같음 | `test_12` |
| `chain` · `priority` · `step` | 같음 | `test_12` |
| `journal.events` 의 모든 `canonical_state()` | 같음 | `test_12` |
| 기록에 남은 점쟁이 마녀의 효과 | **0건** | `test_12` |
| 기존 ACTIVATE 효과의 상태 변경 | ✅ 덱 −2 · 패 +1 | `test_15` |

🔴 **시나리오 I 의 핵심** — 실행되지 않은 후보가 성공 이벤트로 남지 않는다.
기록에 있는 것은 욕망의 항아리의 발동 · 해결 · 드로우뿐이고, 점쟁이 마녀의
효과는 **하나도 없다.** "후보를 봤다" 가 "효과가 해결됐다" 로 새지 않는다.

그리고 **기존 효과는 그대로 작동한다** — 6-J 가 production 실행 경로를
고치지 않았다는 것을 판이 실제로 바뀌는 것으로 확인했다 (`test_15`).

---

## 11. 기르수 회귀 결과

| 항목 | 결과 |
|---|---|
| TRIGGER 등록 | e[0] · e[1] 둘 (`EVENT_SUMMON_SUCCESS` · `EVENT_SPSUMMON_SUCCESS`) |
| 주체 | `SELF` (6-F 가 이미 답했다) |
| **발동 위치** | **`None`** — `SetRange` 가 없다 |
| `EffectDefinition` | 없음 |
| 해결 동작 | `to_grave` (선택 절차 있음) |
| 비용 | 없음 |

🔴 **기르수는 6-J 의 "두 관문 통과 31건" 에 들어가지도 않는다.** 위치
관문이 `UNKNOWN` 이기 때문이다 (6-I §9.2 가 측정한 그대로).

막는 것이 **넷**이다: 위치 미확정 · 정의 없음 · B2 (일반 소환 판정
`UNDETERMINED`) · B3. **기르수만 작동하게 하는 코드를 쓰지 않았고**
(§11 의 금지), 기르수 전개 완성을 완료 조건으로 삼지 않았다.

---

## 12. 실행 전후 지원 범위 비교

§12 의 11개 지표. 전부 전수 측정이고 `test_05` 가 핀으로 고정한다.

| # | 지표 | 전 | 후 |
|---|---|---|---|
| 1 | TRIGGER 등록 수 | 4,173 | 4,173 |
| 2 | `EffectDefinition` 연결 가능 | 0 | **0** |
| 3 | 정확히 일치하는 `EffectRef` | 4,173 | 4,173 |
| 4 | 연결 불명 · 중복 | 0 | **0** |
| 5 | 발동 조건 검증 가능 (두 관문 통과) | 31 | 31 |
| 6 | 비용·선택 검증 가능 | — | 2,999 (비용 없음) · 선택은 `TargetSpec` 가 표현 |
| 7 | **실행 지원 연산이 존재하는 사례** | 미측정 | **2,999** (두 관문까지면 **24**) |
| 8 | **실제 효과 해결 성공** | 0 | **0** |
| 9 | **실제 상태 변경 검증 성공** | 0 | **0** |
| 10 | 잘못된 발동 · 거짓 양성 | 0 | **0** |
| 11 | 미지원 상태가 올바르게 보존된 사례 | — | 4,173 (전부) |

막는 층별 (한 효과가 여럿 가질 수 있다):

| 층 | 수 |
|---|---|
| `definition_missing` | 4,173 |
| `operation_unreadable` | 726 |
| `cost_unpayable` | 260 |
| `operation_untranslatable` | 222 |
| `cost_unknown` | 18 |
| **`operation_unsupported`** | **0** ← 실행기는 병목이 아니다 |

🔴 **2,999 와 0 의 거리가 이 Phase 의 결론이다.** 해결 동작은 옮길 수 있고
실행기도 지원하는데, 그 앞의 세 층이 없어서 **하나도 실행되지 않는다.**
정적 분석 성공을 실제 실행 성공으로 적지 않는 것이 §12 의 요구다.

---

## 13. 타깃 · 통합 · 회귀 테스트 결과

### 13.1 명령과 결과

명령: `python3 -m pytest <대상> -q -p no:randomly --no-header --tb=line`
(각 묶음의 **pytest 종료 코드**를 함께 확인했다 — `tail` 로 가리지 않았다.)

| 단계 | 대상 | 통과 | 실패 | 종료 코드 | 시간 |
|---|---|---|---|---|---|
| 1·2 타깃+통합 | `tests/engine/test_trigger_effect_execution.py` | **20** | 0 | **0** | 48s |
| 3 관련 회귀 | `tests/engine` + dormant · connectivity · binding 감사 | **3,163** | 0 | **0** | 11:06 |
| 3 추가 | `integration` 을 범위에 넣은 감사 전부 | 82 | 0 | **0** | 04:37 |

🔴 **4단계(전체 회귀)를 돌리지 않았다** — §13-4 가 "릴리즈 수준 변경 또는
광범위한 공유 계약 변경일 때" 라고 적었고, 이번 변경은 **읽기 전용
`integration` 모듈 하나**다. 공유 계약도 production 실행 경로도 바뀌지
않았으므로 (§6) 같은 대규모 묶음을 이유 없이 반복하지 않는다. 6-I 가
움직인 감사 열셋은 **하나도 움직이지 않았다** — 새 모듈이
`engine.event_pipeline` 도 `engine.trigger` 도 import 하지 않기 때문이다.

### 13.2 변이 테스트 — 열 가지로 틀리게 만들었다

| 변이 | 잡은 테스트 |
|---|---|
| M1 표에 미지원 연산을 넣는다 | `test_01`·`04`·`05` |
| M2 모르는 비용과 있는 비용을 합친다 | `test_05` |
| M3 동작을 못 읽어도 막지 않는다 | `test_05` |
| M4 옮길 수 없는 동작을 조용히 버린다 | `test_05` |
| M5 목록을 안 줘도 "정의 없음" 으로 센다 | `test_05` |
| M6 정의 없이도 구현 없음을 함께 센다 | `test_05` |
| M7 자리를 `enumerate` 순번으로 추정한다 | `test_05` |
| M8 언제나 해결 가능이라고 말한다 | `test_05`·`07`·`17` |
| M9 지원 밖 연산도 통과시킨다 | `test_20` |
| M10 못 옮긴 연산을 옮긴 것처럼 적는다 | `test_04`·`05`·`20` |

🔴 **첫 실행에서 M9 가 살아남았고, 그것이 코드를 고치게 했다.**
"지원 밖 연산을 통과시킨다" 는 변이가 **실제 데이터에서 티가 나지
않는다** — 옮겨진 연산이 전부 지원되므로 (`test_04` 가 0건을 센다) 그
분기에 **도달하지 않는다.** 즉 지금 데이터로는 그 보호가 있는지 없는지 알 수
없었다.

그래서 분류를 `operation_blockers(actions, *, supported=SUPPORTED)` 로 꺼내
**집합을 주입할 수 있게** 했고, `test_20` 이 좁힌 집합으로 그 분기를 직접
겨눈다. `definitions`·`implementations` 를 주입받는 것과 같은 규율이다 —
이 함수가 의지하는 것을 숨기지 않는다. (6-I 에서 같은 종류의 변이 둘이
살아남아 같은 교훈을 얻었다.)

변이를 적용한 상태로 다른 테스트를 돌리지 않았다. 매 변이마다 적용 →
해당 파일만 실행 → 복원이고, 마지막에 `git status` 로 복원을 확인했다.

---

## 14. 기존 Engine V1 호환성

- **production 실행 경로 무변경.** `engine/` 전체가 `git diff` 에 없다.
- `PlayerAction` · `GameState` 의미론 그대로. 새 행동 종류도, 새 상태 칸도 없다.
- `EFFECT_LIBRARY` **16건 그대로** (`test_16`), `executable` 13건 그대로.
- 기존 ACTIVATE 효과가 실제 듀얼에서 **판을 바꾼다** (`test_15`: 덱 −2 · 패 +1).
- `EventJournal` 은 관찰·감사 기록으로 유지. 실행되지 않은 후보가 기록에
  들어가지 않는다 (`test_12`).
- 6-I 가 움직인 감사 열셋은 그대로다 — 새 모듈이 파이프라인을 import 하지
  않는다.
- 우회 없음 (`test_19`): `DeclaredSummonRuling` · `DeclaredDestructionRuling`
  을 production 에서 만드는 자리가 **0곳**이고, `integration` 에
  `ValidationResult.valid(...)` 를 손으로 만드는 자리도 **0곳**이다.

---

## 15. 새로 발견한 구조적 차단 문제

| # | 문제 | 지금의 모습 | 영향 |
|---|---|---|---|
| 1 | **`monster-activation-timing`** | 몬스터 효과를 발동할 `PlayerAction` 을 판정하는 층이 없다 | 🔴 **4,173건 전부.** 다음 Phase 의 본체 |
| 2 | **`summoning-condition`** | 효과 몬스터의 소환 제약을 읽지 못한다 → `UNDETERMINED` | `monster_summoned` 사건을 만들 수 없다 |
| 3 | **소생 제한 (이력)** | `may_be_special_summoned` 가 언제나 `UNKNOWN`, `build_executor` 에 인자 없음 | `special_summon` 해결 9건 |
| 4 | **해결 동작을 못 읽는 726건** | `analysis` 가 `Duel.*` 호출을 동작으로 옮기지 못했다 | 정의를 손으로 써야 하는 수를 늘린다 |
| 5 | **옮길 수 없는 동작 222건** | `negate` · `control` · `equip` · `position` · `token` · `atk_def_change` 에 대응 연산이 없다 | 그만큼은 새 `OperationKind` 가 필요하다 |
| 6 | **비용을 치르는 계층** | `CostGroup` 는 있고 지불·되돌리기가 없다 (ADR-008) | 260건 |
| 7 | **비용인지 모르는 것 18건** | 「보여주고」 처럼 비용 여부가 불명 | 판정 자체가 불가 |
| 8 | **표시 형식 고정** (STRUCTURAL-61) | `FACEUP_ATTACK` 하나로 고정 | 실행을 막지 않지만 **충실도의 한계** |

§14 가 열거한 잠재적 장애물 중 **직접 차단으로 확인된 것은 1·2·3** 이고,
그 셋만 이 보고서가 "차단" 으로 적는다. 나머지는 범위를 넓히는 문제다.

STRUCTURAL TODO 는 **하나도 수정하지 않았다** — 실제 차단으로 확인된 셋이
전부 새 층을 요구하고, 그것은 §15 가 금지한 범위다.

---

## 16. 다음 단계에서 필요한 최소 추가 작업

§3 이 밝힌 순서를 그대로 따른다. **B3 → B2 → B1.**

### 1단계 (다음 Phase) — 몬스터 효과의 발동 분류

`ActionValidator` 가 몬스터 효과를 **분류**할 수 있게 한다:
기동(IGNITION) · 유발(TRIGGER) · 플립(FLIP) · 유발즉시(QUICK).
그 분류는 **이미 데이터에 있다** — `EffectSpec.effect_types` 가
`IGNITION` · `TRIGGER_O` · `TRIGGER_F` 를 들고 있고 6-E 가 그것을 읽는다.

최소 목표: **기동 효과 하나**를 발동한다. 유발 효과보다 먼저인 이유 —
기동 효과는 "자기 턴 메인 페이즈에 스스로 발동" 이므로 **타이밍 창이
필요 없다.** 유발 효과는 "사건에 반응" 이라 타이밍 창(놓친 타이밍 ·
WHEN/IF) 이 함께 필요하다.

### 2단계 — 그 발동에 맞는 `EffectDefinition` 하나

1단계가 열리면 **처음으로** 실행할 수 있는 정의가 생긴다. 지금 적으면
실행되지 않는 채 남는다 (§5 의 대안 B).

### 3단계 — 타이밍 창 (WHEN/IF · 놓친 타이밍)

유발 효과의 발동에 필요하다. `UNCHECKED_RULES` 의 첫 두 항목.

### 4단계 — B2 (소환 제약) 와 B1 (소생 제한)

둘은 **사건의 종류를 늘리는** 일이고 판정 정확성과 독립이다. B1 은
인스턴스 **이력** 모델을 요구하므로 (`CardInstance` 에 "정규 소환되었는가")
`GameState` 구조 변경 승인이 먼저 필요하다.

🔴 **순서를 바꾸면 안 되는 이유**: B1·B2 를 먼저 고쳐도 B3 때문에
**실행은 0건 그대로다.** B3 을 먼저 열면 1건이라도 실행되고, 그 1건으로
경로 전체를 검증할 수 있다 — 6-I 의 `test_09` 와 6-J 의 `test_11` 이 이미
그 형태다.

---

## 17. Git 커밋 및 푸시 결과

브랜치: `claude/pensive-goodall-te1egy` (기존 커밋 rewrite · amend · force
push 없음 · 새 브랜치 없음 · PR 없음)

| 커밋 | 내용 |
|---|---|
| `16c3d28` | 막는 것이 실행기가 아니라는 것을 측정한다 (`integration/execution_readiness.py` + 테스트 20개) |
| (이 보고서) | `docs/phase6j-minimal-trigger-effect-execution.md` |

푸시: `7cb309d..16c3d28` → `origin/claude/pensive-goodall-te1egy` (성공),
그리고 이 보고서 커밋.

---

## 부록 A — §15 금지 목록 대조

새 듀얼 엔진 · `EffectLibrary` 재설계 · 전 카드 Lua 실행기 · 카드별 Python
처리 · 모든 TRIGGER 지원 · 완전 자동 발동 · 체인·우선권 재설계 · 모든 특수
소환 방식 · ComboPlanner 실행 연결 · Discord 명령어 · 덱 빌더 · 금지·제한
리스트 · Duel Simulator · EDOPro · 전략 추론 · 카드 데이터 재생성 · Lua 파일
이동·삭제 · 관련 없는 TODO — **하나도 하지 않았다.**

카드 ID · 카드명 하드코딩: production 코드에 **없다.** `execution_readiness`
는 `ActionKind` → `OperationKind` 표와 실행기의 `SUPPORTED` 집합만 본다.
테스트의 대표 사례 상수는 전수 측정으로 고른 것이고, 특정 카드를 위한 분기는
없다.

## 부록 B — 이 Phase 가 "성공" 이라고 부르지 않는 것

§18 이 요구한 대로 적는다.

- ❌ 실제 TRIGGER 효과를 **해결하지 못했다.**
- ❌ 그 결과 GameState 변화도 **검증하지 못했다.**
- ✅ 막는 세 층을 **실제 실행으로** 특정했고 테스트로 고정했다.
- ✅ 다음 구현 단위(B3)와 그 순서를 근거와 함께 제시했다.

**Phase 6-J = "실행 경로 조사 및 차단 요인 규명 완료, 실제 효과 실행
미달성".**

**다음 Phase 는 자동으로 시작하지 않는다.** 사용자 검토를 기다린다.
