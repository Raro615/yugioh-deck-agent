# Phase 3-E-32 완료 보고 — EVENT_FREE_CHAIN 5장 EffectDefinition 표현 가능성 감사

> 핵심 원칙: **이름을 보고 의미를 추측하지 않는다.** `EVENT_` 로 시작한다고
> 사건이라고 읽지 않고, `TRAP` 이라고 `EVENT_FREE_CHAIN` 을 추론하지 않는다.
> 원본 Lua → 파서 → analysis → `EffectDefinition` → production reachability 를
> 끝까지 추적한 결과만 적는다.

## 1. Phase / Base / 실제 HEAD

| 항목 | 값 |
|---|---|
| Phase | 3-E-32 (AUDIT-ONLY) |
| 직전 Phase | 3-E-31 (`EffectDefinition` / Trigger 등록 경계 감사) |
| **감사 시작 시 실제 HEAD** | **`89f37cf`** (Phase 3-E-31 보고서) |
| 작업 트리 | 깨끗 (`git status --short` 비어 있음) |
| 3-E-31 포함 확인 | `docs/phase3e31-...md` · `tests/test_effectdefinition_trigger_boundary_audit.py` 존재 |
| `5be3709..89f37cf` production diff | **0** |

프롬프트가 커밋을 지정하지 않았고, 실제 HEAD 에서 진행했다. 불일치 없음.

## 2. BLOCKER

**없음.**

## 3. Engine 변경 여부

**없음. production diff = 0.**

`engine/` · `agent/` · `core/` · `analysis/` · `sources/` 어느 것도 바뀌지
않았다. 변경 파일은 둘뿐이다.

- `tests/test_event_free_chain_semantics_audit.py` (신규)
- `docs/phase3e32-event-free-chain-effect-definition-audit.md` (신규)

## 4. EVENT_FREE_CHAIN 출처

### 공식 상수 — 진짜 사건과 **같은 번호대**다

`data/constants/constant.lua:640`

```
EVENT_STARTUP              = 1000
EVENT_FLIP                 = 1001
EVENT_FREE_CHAIN           = 1002      ← 여기
EVENT_DESTROY              = 1010
EVENT_TO_GRAVE             = 1014
```

→ **이름도 번호대도 진짜 사건과 구분되지 않는다.** 구문으로 가를 수 없다.
가르는 것은 함께 쓰인 `effect_types` 다 (§11).

### 흐름 — 질문별 답

| # | 질문 | 답 |
|---|---|---|
| 1 | 원본 Lua 에 직접 있는가 | **있다.** `e1:SetCode(EVENT_FREE_CHAIN)` — 5장 전부 |
| 2 | parser 가 직접 읽는가 | **읽는다.** `sources/lua_loader.py:192` `_RE_EVENT` → `f"EVENT_{...}"` |
| 3 | 어떤 필드로 저장되는가 | **`EffectSpec.code`** (`str \| None`) |
| 4 | `EffectSpec.code` 와의 관계 | **그 자체다** — `code` 가 `SetCode()` 인자를 담는 유일한 칸 |
| 5 | `TriggerSpec` 생성에 쓰이는가 | **아니다.** production `TriggerSpec` 생성 **0곳** |
| 6 | `EffectDefinition` 생성에 쓰이는가 | **아니다.** `EffectDefinition` 에 `code` 칸이 없다 |
| 7 | 어디에서 의미가 소실되는가 | **소실되지 않는다.** 파서 계층에 그대로 남는다 |
| 8 | engine execution 에 전달되는가 | **전달되지 않는다.** 읽는 production 코드가 0곳 (§13) |

`analysis` 계층도 따로 보존한다 — `analysis/effect_model.py:457`
`trigger_event: str | None` ("SetCode 가 `EVENT_*` 이면 그 값"). 그 docstring 이
**스스로** 경고한다.

> **`is not None` 을 "유발 효과다" 로 읽지 않는다** (Phase 3-E-17).
> `EVENT_FREE_CHAIN` 이 이 자리에 들어오는데, 그것은 유발 이벤트가 아니라
> **"유발 조건이 없다"** 를 적은 값이다.

## 5. 실제 5장 목록

저장소 데이터로 골랐다 — 등재 효과 16개를 훑어 `code == 'EVENT_FREE_CHAIN'`
이고 `type_mask & TYPE_TRAP` 인 것만 남겼다 (`test_01` 이 선정 자체를 검증).

| card id | 한국어 이름 | 원본 이름 | EffectRef | executable |
|---|---|---|---|---|
| 5915629 | 욕망의 선물 | 強欲な贈り物 / The Gift of Greed | `5915629:e[0]` | True |
| 92595643 | 벌금 | 罰則金 / Fine | `92595643:e[0]` | True |
| 94192409 | 강제 탈출 장치 | 強制脱出装置 / Compulsory Evacuation Device | `94192409:e[0]` | True |
| 24623598 | 로스트 | ロスト / Disappear | `24623598:e[0]` | **False** |
| 69091732 | 의적의 입문서 | 義賊の入門書 / Introduction to Gallantry | `69091732:e[0]` | True |

> **먼저 밝혀야 할 사실**: 등재된 16개 효과가 **전부** `EVENT_FREE_CHAIN` 이다
> (통상 마법 8 · 속공 마법 3 · 함정 5). 함정만의 표지가 아니다.

## 6. 5장 상세 분석

파서는 다섯 장에서 **같은 값**을 뽑았다 — `code='EVENT_FREE_CHAIN'`,
`effect_types=['ACTIVATE']`, `ranges=[]`, `target_ranges=[]`,
`count_limit=None`. 다른 것은 `categories` 와 `properties`, 그리고 **Lua 가
가진 슬롯**이다.

| card | Lua `SetCondition` | Lua `SetTarget` `chk==0` | `categories` | `properties` | `EffectDefinition.activation` | `requires_target` |
|---|---|---|---|---|---|---|
| 5915629 욕망의 선물 | **없음** | `Duel.IsPlayerCanDraw(1-tp,2)` | `DRAW` | `PLAYER_TARGET` | `ZoneCountAtLeast(CONTROLLER, DECK, 2)` | False |
| 92595643 벌금 | **없음** | `IsExistingMatchingCard(nil,tp,LOCATION_HAND,0,2,...)` | `HANDES` | `PLAYER_TARGET` | `ZoneCountAtLeast(CONTROLLER, HAND, 2)` | True |
| 94192409 강제 탈출 장치 | **없음** | `IsExistingTarget(Card.IsAbleToHand,tp,LOCATION_MZONE,...)` | `TOHAND` | `CARD_TARGET` | **`None`** | True |
| 24623598 로스트 | **없음** | `IsExistingTarget(s.rmfilter,tp,0,LOCATION_MZONE\|LOCATION_GRAVE,...)` | `REMOVE` | `CARD_TARGET` | **`None`** | False |
| **69091732 의적의 입문서** | **있음** `GetFieldGroupCount(tp,0,LOCATION_HAND)>4` | `true` (무조건) | `HANDES` | `PLAYER_TARGET` | `ZoneCountAtLeast(OPPONENT, HAND, 5)` | True |

### analysis 계층이 둘을 **따로** 보존한다

| card | `trigger_event` | `has_condition_function` | `tree` | `requirements` | `unparsed` | `raw` |
|---|---|---|---|---|---|---|
| 5915629 | `EVENT_FREE_CHAIN` | `False` | `None` | `[]` | `[]` | `''` |
| 92595643 | `EVENT_FREE_CHAIN` | `False` | `None` | `[]` | `[]` | `''` |
| 94192409 | `EVENT_FREE_CHAIN` | `False` | `None` | `[]` | `[]` | `''` |
| 24623598 | `EVENT_FREE_CHAIN` | `False` | `None` | `[]` | `[]` | `''` |
| **69091732** | `EVENT_FREE_CHAIN` | **`True`** | **`ConditionNode`** | **`['card_count']`** | `[]` | `'s.condition'` |

`unparsed == []` 가 중요하다 — **읽지 못한 것이 아니라 끝까지 읽었다.**

### "Free Chain" 은 카드 전체가 아니라 **효과 블록 단위**다

다섯 장 모두 효과 블록이 하나뿐(`e1`)이라 이 코퍼스에서는 구분이 드러나지
않는다. 그러나 `code` 는 `EffectSpec` 의 칸이고 `EffectSpec` 은 블록 하나다 —
구조상 **효과 단위**다. 전체 코퍼스에서 한 카드가 블록마다 다른 `code` 를 갖는
실제 예가 있다 (§7 의 리미트 리버스: `EVENT_LEAVE_FIELD` ×2 +
`EVENT_CHANGE_POS`).

### 등재 노트가 남긴 유도 과정

`engine/effect/library.py` 가 각 `activation` 이 Lua 의 **어느 슬롯**에서
왔는지 적어 두었다.

- 욕망의 항아리(같은 모양): *"`s.target` 의 `Duel.IsPlayerCanDraw(tp,2)` 중
  **덱 장수 부분만** 옮겼다 … 이 조건은 **필요조건이지 충분조건이 아니다**."*
- 의적의 입문서: *"`c69091732.lua` 의 **`s.condition`** 과 `s.activate` 를
  옮겼다. `s.target` 의 `SetTargetPlayer(1-tp)` 는 후보의 owner 로 들어갔다."*

→ `EffectDefinition.activation` 은 **두 가지 Lua 슬롯**(`SetCondition` 과
`SetTarget` 의 `chk==0`)을 같은 칸에 받는다. 둘 다 발동의 필요조건이므로
지금은 해가 없지만, **유도 출처가 다르다는 사실은 노트에만 있다.**

## 7. TRAP ↔ EVENT_FREE_CHAIN 관계

전수 측정 (고유 스크립트 12,687개 / 블록 34,631개).

| # | 질문 | 답 | 근거 |
|---|---|---|---|
| 1 | 모든 TRAP 이 `EVENT_FREE_CHAIN` 인가 | **아니다** | TRAP 블록 4,745개 중 1,833개 = **38.6%** |
| 2 | `EVENT_FREE_CHAIN` 이면 반드시 TRAP 인가 | **아니다** | 4,909개 중 `SPELL` **45.2%** · `TRAP` **37.3%** · `MONSTER` **17.4%** |
| 3 | 다른 타입에도 있는가 | **있다** | 몬스터 블록 **855개** |
| 4 | TRAP 만으로 안전하게 복원 가능한가 | **아니다** | 위 두 숫자가 양방향으로 실패한다 |
| 5 | 추가로 필요한 정보 | **그 효과 블록의 `EffectSpec.code`** (효과 단위) |

세부 종류로 좁혀도 안 된다.

| TRAP 하위 분류 | `EVENT_FREE_CHAIN` 비율 |
|---|---|
| NORMAL | 1,074 / 2,679 = **40.1%** |
| CONTINUOUS | 744 / 1,785 = **41.7%** |
| COUNTER | 15 / 281 = **5.3%** |

### 실제 반례 (TRAP 인데 `EVENT_FREE_CHAIN` 이 아니다)

| card id | `code` | 이름 |
|---|---|---|
| 27551 | `EVENT_LEAVE_FIELD` ×2 · `EVENT_CHANGE_POS` | 리미트 리버스 |
| 50755 | `EVENT_ATTACK_ANNOUNCE` | 매지션즈 서클 |
| 56889 | `EFFECT_DESTROY_REPLACE` · `EVENT_PHASE` | 경투－크로스 디멘션 |

→ **"TRAP 이면 Free Chain" 추론 규칙을 만들면 61.4% 를 틀린다.**

## 8. activation condition 과의 관계

**`EVENT_FREE_CHAIN` ≠ "효과 조건 없음".** 반례가 5장 안에 있다.

```lua
-- c69091732.lua  의적의 입문서
e1:SetCode(EVENT_FREE_CHAIN)       -- 시점 분류: 유발 조건 없음
e1:SetCondition(s.condition)       -- 그런데 발동 조건은 있다
...
function s.condition(e,tp,eg,ep,ev,re,r,rp)
	return Duel.GetFieldGroupCount(tp,0,LOCATION_HAND)>4   -- 상대 패 5장 이상
end
```

그리고 반대 방향도 성립한다 — 조건이 있어도 `EVENT_FREE_CHAIN` 일 수 있다
(위가 바로 그 예다).

따라서 **둘을 `condition=None` 하나로 합치면 안 된다.** 그리고 현재
아키텍처는 **이미 합치지 않았다**.

| 사실 | 소유 칸 |
|---|---|
| 시점 분류 (`EVENT_FREE_CHAIN`) | `EffectSpec.code` |
| 발동 조건 유무 | `ActivationCondition.has_condition_function` |
| 발동 조건 내용 | `ActivationCondition.tree` · `requirements` |
| 읽지 못한 부분 | `ActivationCondition.unparsed` |
| 엔진이 쓰는 발동 조건 | `EffectDefinition.activation` (손 등록) |

## 9. EffectDefinition 표현 가능성

§6 의 세 CASE 로 판정하면 **CASE C** 에 가깝지만, 결론은 "그래서 넣어야 한다"
가 아니다.

| 사실 | 현재 `EffectDefinition` 으로 표현 가능한가 |
|---|---|
| 발동 조건 (의적의 입문서의 상대 패 5장) | **가능하고 이미 되어 있다** — `activation=ZoneCountAtLeast(OPPONENT, HAND, 5)`, Lua 의 `>4` 와 맞는다 |
| 시점 분류 (`EVENT_FREE_CHAIN` 자체) | **불가능** — 10개 칸에 `code`/`trigger_event`/`timing`/`point`/`event` 가 없다 |

그런데 **넣어도 소용이 없다**: 등재된 16개 효과가 **전부**
`EVENT_FREE_CHAIN` 이므로, 그 값을 정의로 옮겨도 등재 코퍼스 안에서 **구분력이
0** 이다. 함정을 가르는 것은 이 값이 아니라 `effect_types`
(`TRIGGER_O`/`TRIGGER_F` 유무)다.

## 10. TriggerSpec 필요성

§7 의 기준으로 5장을 판정했다.

| 기준 | 5장 전부 |
|---|---|
| 실제 사건에 의해 발생하는 trigger 인가 | **아니다** (§11) |
| `TimingPoint` 를 특정해야 하는가 | **아니다** — 특정할 사건이 없다 |
| `TriggerCandidate` 를 만들어야 하는 정보인가 | **아니다** |
| Event identity 가 필요한가 | **아니다** |
| 이전/현재 사건과의 관계가 필요한가 | **아니다** |
| 단순 발동 가능 여부인가 | **그렇다** |
| chain response 가능 여부인가 | **그렇다** (함정은 상대 턴에 응수한다) |
| 효과 자체의 activation condition 인가 | 의적의 입문서만 **그렇다** — 그리고 그것은 `EffectDefinition.activation` 의 것 |
| activation timing gate 에서 처리되는 정보인가 | **그렇다** |

**구조적 근거**: `TriggerSpec` 은 `point: TimingPoint` 를 **필수**로 받는다
(기본값 없음 — `test_11` 이 고정). `EVENT_FREE_CHAIN` 은 사건이 아니므로 넣을
시점이 없고, 억지로 넣으면 **"사건이 없다" 를 "어떤 사건" 으로 적게 된다.**

→ **`TriggerSpec` 은 필요하지 않다. 넣으면 잘못된 추상화다.**

## 11. Trigger 인가 activation timing 인가

**두 어휘가 전수에서 완전히 분리되어 있다.**

### `EVENT_FREE_CHAIN` 이 함께 쓰는 `effect_types` (블록 4,909개)

| 함께 쓰인 종류 | 수 |
|---|---|
| `ACTIVATE` | 3,638 |
| `QUICK_O` | 1,256 |
| `IGNITION` | 58 |
| `FIELD` | 3 |
| `CONTINUOUS` | 1 |
| **`TRIGGER_O`** | **0** |
| **`TRIGGER_F`** | **0** |

### 반대 방향 — 유발 블록 8,052개가 쓰는 `code` (상위)

`EVENT_SPSUMMON_SUCCESS` 1,817 · `EVENT_SUMMON_SUCCESS` 1,097 ·
`EVENT_TO_GRAVE` 1,027 · `EVENT_PHASE` 819 · `EVENT_DESTROYED` 541 …
**`EVENT_FREE_CHAIN` 은 0개.**

### 그리고 발동형의 **기본값**이다

`ACTIVATE` 블록 4,301개 중 `EVENT_FREE_CHAIN` 이 **3,638개 = 84.6%**.

→ 모델 **B** 가 맞다.

```
모델 A (틀렸다)                     모델 B (맞다)
EVENT_FREE_CHAIN                    PlayerAction / activation timing
  ↓ TriggerSpec                       ↓ activation gate
  ↓ TriggerCandidate                  ↓ PlayerAction
  ↓ ChainLink                         ↓ ChainLink
```

세 개념의 분리:

| 개념 | 무엇인가 | 어디서 판정하는가 |
|---|---|---|
| **Trigger** | 사건이 일어나 후보가 되는 것 | `TriggerCollector` (잠듦). `code` 가 진짜 `EVENT_*` 인 블록 |
| **activation timing** | 지금 발동해도 되는 때인가 | `ActivationTimingChecker` (체인 · 우선권 · 세트한 턴). `EVENT_FREE_CHAIN` 이 가리키는 자리 |
| **PlayerAction 선택 조건** | 이 효과를 지금 고를 수 있는가 | `ActionValidator` + `EffectDefinition.activation` + `targets` |

## 12. Data-loss 여부

| 정보 | 분류 | 근거 |
|---|---|---|
| Lua `SetCode(EVENT_FREE_CHAIN)` | **PRESERVED** | `EffectSpec.code` 에 그대로. 5장 전부 확인 |
| Lua `SetCondition` (의적의 입문서) | **PRESERVED + TRANSFORMED** | `ActivationCondition`(`has_condition_function`·`tree`·`requirements`) 에 보존, `EffectDefinition.activation` 으로 **변환**되어 들어갔다 |
| Lua `SetTarget` 의 `chk==0` 게이트 | **TRANSFORMED** | 4장 중 2장은 `activation` 으로, 2장은 `targets` 로 들어갔다. 등재 노트가 "필요조건이지 충분조건이 아니다" 를 적는다 |
| `EFFECT_TYPE_ACTIVATE` | **TRANSFORMED** | 접두어를 떼고 `effect_types=['ACTIVATE']` |
| `EffectDefinition` 의 시점 분류 | **INTENTIONALLY DROPPED** | 컴파일러 없음 (ADR-006 · STRUCTURAL-7). 손 등록이 옮기지 않았다 |
| `activation` 의 **유도 출처** (`SetCondition` 인가 `SetTarget` 인가) | **INTENTIONALLY DROPPED** | 등재 노트(산문)에만 있고 구조에는 없다 — 감사 소견 |
| **ACTUALLY_LOST** | **없음** | 원본 값이 `EffectSpec.code` 에 있고 `engine.ids.iter_effects` 로 닿는다 (3-E-31 측정) |

**질문에 직접 답한다**: parser → `EffectDefinition` 변환에서 의미가
**사라진 것이 아니다.** 원본 데이터에 있고 **execution layer 가 아직 읽지
않는 것뿐**이다.

## 13. Production reachability

| 대상 | `EVENT_FREE_CHAIN` 을 읽는가 |
|---|---|
| `Duel` | **아니다** |
| `legal_actions()` | **아니다** |
| `_activation_actions` | **아니다** (3-E-30 이 AST 로 측정) |
| `EffectActivator` | **아니다** |
| `ActivationTimingChecker` | **아니다** |
| `TriggerCollector` · `TriggerEligibilityJudge` · `TriggerOrdering` · `TriggerChainIntegrator` | **아니다** (전부 잠듦) |
| `timing.py` · `event_pipeline.py` | **아니다** (정론 경로 미도달) |
| `agent/` | **아니다** |

AST 측정: production 7곳에 등장하지만 **전부 주석/docstring** 이다. 홀로 선
문자열 문장(모듈 · 클래스 · 함수의 첫 줄 **그리고 dataclass 칸 아래 설명**)을
걸러내면 **값으로 읽는 자리가 0곳**이다 (`test_10`).

§11 의 질문별 답: (1) `PlayerAction` 생성에 영향 **없음** · (2) activation
timing gate 에서 읽지 **않음** · (3) Trigger pipeline 에서 읽지 **않음** ·
(4) 어떤 production 경로에서도 읽지 **않음** · (5) **parser/core 데이터에만
존재**.

## 14. AI/Search 영향

| 항목 | 변화 |
|---|---|
| `GameStateView` | **없음** |
| `legal_actions` | **없음** |
| candidate generation | **없음** |
| Search ranking | **없음** |
| Evaluation | **없음** |
| Simulation | **없음** |
| clone | **없음** |
| RNG isolation | **없음** |
| hidden information | **없음** |

변경 파일이 테스트 1개 + 문서 1개이므로 구조적으로 영향이 없다. `agent/` 가
`EVENT_FREE_CHAIN` 을 어떻게 쓸지는 구현하지 않았다.

## 15. Tests

`tests/test_event_free_chain_semantics_audit.py` — **12개 신규. 기존 수정 0.**

| # | 보는 것 | §14 요구 |
|---|---|---|
| 01 | 5장 선정을 저장소 데이터로 재검증 (이름으로 고르지 않았다) | — |
| 02 | 다섯 장이 시점 분류는 같고 `SetCondition` 유무는 다르다 | **Test 1** |
| 03 | TRAP ↔ `EVENT_FREE_CHAIN` 양방향 추론 실패 (비율) | **Test 2** |
| 04 | 실제 반례를 카드로 남긴다 | **Test 2** |
| 05 | `EVENT_FREE_CHAIN` ≠ 조건 없음 — analysis 가 따로 보존 | **Test 3** |
| 06 | 조건이 `EffectDefinition.activation` 에 이미 옮겨져 있다 (`count=5` ↔ Lua `>4`) | **Test 4** |
| 07 | 정의 10칸에 시점 분류를 담을 자리가 없다 | **Test 4** |
| 08 | 등재 16개가 전부 `EVENT_FREE_CHAIN` → 구분력 0 | **Test 4** |
| 09 | 유발 어휘와 **교집합 0** / 발동형의 84.6% / 공식 상수 번호대 | **Test 5** |
| 10 | production 이 값을 읽지 않는다 (docstring 제외 AST) | — |
| 11 | `TriggerSpec.point` 가 필수라 넣을 시점이 없다 / production 0곳 | **Test 5** |
| 12 | 감사가 구조를 늘리지 않았다 (10칸 · 9칸 · enum 멤버) | — |

### 회귀

| 항목 | 값 |
|---|---|
| 3-E-31 기준선 | 3732 passed · 4 skipped · 0 failed |
| 이번 | **3744 passed · 4 skipped · 0 failed** (300s) |
| 차 | +12 = 신규 그대로. 잃은 테스트 0 · 새 skip 0 · **regression 0** |

### 고의 위반 검증 — 7개 전부 잡혔다

| 주입 | 깨뜨린 계약 | 잡혔는가 |
|---|---|---|
| A | `EffectDefinition` 에 `trigger_event` 칸 추가 | 2개 실패 ✅ |
| B | 의적의 입문서의 `activation` 을 `None` 으로 | 1개 실패 ✅ |
| C | engine 이 `EVENT_FREE_CHAIN` 문자열을 코드로 읽게 | 1개 실패 ✅ |
| D | `TriggerSpec.point` 를 선택 인자로 | 1개 실패 ✅ |
| E | production 에 `TriggerSpec` 등록 | 1개 실패 ✅ |
| F | `TimingPoint` 에 `FREE_CHAIN` 멤버 추가 | **처음엔 안 잡혔다** → 아래 |
| G | 파서가 `EVENT_FREE_CHAIN` 을 버리게 (+ 캐시 무효화) | 3개 실패 ✅ |

#### 주입 F 가 처음에 안 잡힌 것 — 테스트의 실제 구멍

`test_12` 가 `dir(module)` 만 봤다. **enum 멤버는 모듈 속성 목록에 나타나지
않으므로** `TimingPoint.FREE_CHAIN` 을 추가해도 통과했다. 모듈의 `Enum`
하위 클래스를 찾아 **`__members__` 까지** 보도록 고쳤고, 다시 주입하니 잡힌다.
`TimingPoint` 가 8개임을 함께 고정했다.

> 주입 B·D 는 처음에 **적용 자체가 실패**했다 (내 치환 문자열이 틀렸다 —
> `69091732` 는 리터럴이 아니라 `INTRODUCTION_TO_GALLANTRY` 상수이고,
> `point: TimingPoint` 는 파일에 3번 나온다). 테스트의 구멍이 아니라 주입
> 스크립트의 오류였고, 올바른 대상으로 다시 넣어 둘 다 잡는 것을 확인했다.

## 16. Structural TODO

- **신규 STRUCTURAL ID: 없음.**
- 기존 TODO 변경: **없음.** 번호를 다시 매기지 않았다.

§17 의 제외 사유에 그대로 걸린다.

| 제외 사유 | 해당 |
|---|---|
| 기존 TODO 로 설명 가능 | **그렇다** — **STRUCTURAL-7** (`analysis` → `EffectDefinition` 컴파일러) |
| 단순 audit finding | 그렇다 |
| 구현하지 않은 기능이라는 이유만 | 그렇다 |
| production reachability 없는 dormant subsystem | 그렇다 (§13) |

### 감사 소견 (ID 없이 기록)

1. **`EffectDefinition.activation` 이 서로 다른 Lua 슬롯을 같은 칸에 받는다.**
   `SetCondition`(의적의 입문서)과 `SetTarget` 의 `chk==0`(욕망의 선물 · 벌금)이
   구분 없이 들어간다. 유도 출처는 등재 노트(산문)에만 있다. 둘 다 발동의
   필요조건이므로 지금은 해가 없지만, 유발 조건을 engine 으로 옮기는 날
   **"조건" 과 "대상 가용성" 을 가려야 할 수 있다.**
2. **`EVENT_FREE_CHAIN` 은 등재 코퍼스에서 구분력이 0 이다** (16/16). 이 값을
   옮기는 작업은 **등재를 넓힌 뒤에야** 의미가 생긴다.
3. **구문으로는 진짜 사건과 가를 수 없다** (`= 1002`, 같은 번호대). 가르는
   것은 `effect_types` 뿐이므로, 나중에 `EVENT_*` 를 기계적으로 분류하려면
   **반드시 두 값을 함께** 봐야 한다.

## 17. Final Decision

### **C. ACTIVATION_TIMING_FITS**

`EVENT_FREE_CHAIN` 은 사건(trigger event)이 **아니다** — 전수 측정에서
`TRIGGER_O`/`TRIGGER_F` 와 교집합이 **0** 이고(유발 블록 8,052개 중 0개),
`ACTIVATE`·`QUICK_O`·`IGNITION` 과만 함께 쓰이며 `ACTIVATE` 블록의 **84.6%** 를
차지하는 **발동형 효과의 "유발 조건 없음" 기본값**이다. 따라서 이 정보가
속하는 계층은 Trigger 계층이 아니라 **activation/timing 계층**이고, 그곳은
이미 `ActivationTimingChecker`(체인 · 우선권 · 세트한 턴)와
`_NormalSpellActivation` 범위 조건이 맡고 있다. `TriggerSpec` 에 넣으면
`point`(사건 시점)가 필수인 구조에 "사건이 없다" 를 억지로 사건으로 적는
잘못된 추상화가 되고, `EffectDefinition` 에 넣어도 등재된 16개 효과가 전부 같은
값이어서 **구분력이 0** 이다. 그리고 정말 필요한 발동 조건(의적의 입문서의
"상대 패 5장 이상")은 **이미** `EffectDefinition.activation` 에 옮겨져 있다
(`ZoneCountAtLeast(OPPONENT, HAND, 5)` ↔ Lua `>4`). 다만 5장이 모든 축에서
동일하지는 않다 — **의적의 입문서만 `SetCondition` 을 갖는다** — 그래서 "다섯
장은 같으니 공통 metadata 하나로 처리하자" 는 접근은 금지된다(§1 의 F 가 그
축에 해당한다). 아키텍처는 **이미 두 축을 따로 보존하고 있으므로**
(`EffectSpec.code` vs `ActivationCondition`) 구조 변경 없이 그 구분이 유지된다.

## 18. Next Phase Candidate

### `EffectDefinition.activation` 의 유도 출처 분리 가능성 감사 (Activation-Condition Provenance Split Audit)

- 측정된 사실: `EffectDefinition.activation` 이 Lua 의 **두 다른 슬롯**에서
  온다 — `SetCondition`(의적의 입문서)과 `SetTarget` 의 `chk==0`(욕망의 선물 ·
  벌금). 등재 노트가 "필요조건이지 충분조건이 아니다" 라고 적지만 **구조에는
  그 구분이 없다.** 그리고 같은 5장 중 2장은 그 게이트가 `activation` 이 아니라
  `targets` 로 들어갔다 (강제 탈출 장치 · 로스트).
- 볼 것: (a) 네 장의 `chk==0` 게이트가 **일관된 규칙**으로 배치되었는가, 아니면
  카드마다 판단이 달랐는가 — 등재 노트를 전수로 읽어 확인한다. (b) 공식 규칙에서
  "발동 조건" 과 "대상 가용성" 이 다르게 작동하는 자리가 있는가 (예: 조건은
  발동 선언 시점, 대상은 선택 시점). **공식 룰북 문서로만** 확인하고 추측하지
  않는다. (c) 지금 합쳐 둔 것이 production 판정을 틀리게 하는 실제 사례가
  등재 13개 안에 있는가.
- 왜 지금이 아닌가: 이번 Phase 는 "`EVENT_FREE_CHAIN` 을 어디에 둘 것인가" 라는
  닫힌 질문이었고 답은 "activation/timing 계층이고 지금 옮길 필요 없다" 였다.
  (b) 는 공식 문서 확인이 필요한 별도 작업이다.
- 왜 다음인가: 이 Phase 가 **진짜 모호한 자리를 하나 찾아냈다.**
  `EVENT_FREE_CHAIN` 은 문제가 아니었지만, 그것을 추적하다 `activation` 칸이
  두 출처를 합치고 있다는 사실이 드러났다. 그것은 등재된 **실행 가능한 효과
  13개에 지금 적용되고 있는** 사실이므로 dormant 가 아니다.

**이 Phase 는 여기서 멈춘다. 다음 Phase 는 임의로 진행하지 않는다.**
