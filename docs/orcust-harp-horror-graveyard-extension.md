# 오르페골 디베르의 묘지 효과로 몬스터를 추가 확보한다 (Phase 6-AO)

「오르페골 디베르」(57835716) ① — 「묘지의 이 카드를 제외하고 발동할 수 있다.
덱에서 "오르페골 디베르" 이외의 "오르페골" 몬스터 1장을 특수 소환한다. 이
효과의 발동 후, 턴 종료시까지 자신은 어둠 속성 몬스터밖에 특수 소환할 수
없다」 — 를 **전체 경로**로 연결했다.

```
합법 행동 후보 생성 → 발동 조건과 비용 검증 → 비용 지불과 체인 처리
→ 해결 중 허용 카드 선택 → 특수 소환 → 사용 제한·소환 제한 기록
→ 탐색 → 새 초기 상태에서 전체 경로 재생
```

> 🔴 **이 단계가 지원한 것은 디베르 ① 하나다.** ② (바벨이 적용될 때의
> 유발즉시) 는 등재하지 않았고, 이 효과로 **특수 소환된 몬스터의 효과**도
> 등재하지 않았다 (스켈레촌 · 카노네의 ① 은 여전히 미지원). §8 이 그 목록이다.

> 🔴 **준비한 판에서의 성공과 시작 패에서의 성공을 구분한다.** §4 는 손으로
> 구성한 작은 상태이고, §5~§7 이 시작 패부터의 결과다.

관련 문서 — `docs/orcust-longirsu-link-summon.md`(링크 소재 등재),
`docs/orcust-first-executable-combo.md`(기르수 경로),
`docs/orcust-post-goal-continuation.md`(후속 탐색).

---

## 1. 기존 지원 상태와 추가한 구현

### 1.1 이 Phase 전에 막혀 있던 것 (실측)

| 자리 | 그때의 상태 | 증거 |
|---|---|---|
| **묘지에서의 발동** | 발동 출발지에 묘지가 없었다 | `Duel.ACTIVATION_SOURCE_ZONES = (SZONE, MZONE, EMZONE)` |
| **비용 있는 효과의 후보 생성** | `if definition.cost.costs: continue` — **비용이 있으면 전부 건너뛰었다** | `Duel._activation_actions` (STRUCTURAL-120) |
| **발동 관문의 비용 판정** | 관문이 비용을 보지 않았다 (지불기 안에서만 판정) | `EffectActivator._check_before_targets` 에 비용 단계가 없었다 |
| **비용으로서의 제외** | 치를 수 없는 비용이었다 | `UNSUPPORTED_REASON[BANISH] = "비용으로서의 제외 (Phase 2-F~)"` |
| **자신을 내놓는 비용** | 표현할 자료형이 없었다 (`CardCost` 는 **고르는** 비용이다) | `engine/cost/model.py` 에 `Cost` 구현이 셋 (`CardCost`·`LifeCost`·`UnimplementedCost`) |
| **덱에서 나오는 특수 소환** | 절차가 옮기지 않은 출발 자리였다 | `SPECIAL_SUMMON_FROM_ZONES = {HAND, GRAVE}` |
| **덱 카드의 소생 제한** | 덱이 "소생 제한을 묻지 않는 자리" 에 없었다 | `REVIVAL_LIMIT_FREE_ZONES = {HAND}` |
| **「…밖에 특수 소환할 수 없다」** | **적는 계층이 없었다** | `engine/effect/library.py` 의 `_WORLD_WAND_RESTRICTION_GUARD` 가 그 사실을 import 시점에 지키고 있었다 |

마지막 줄이 이 Phase 의 중심이다. 6-AN 까지 저장소는 성유물－『성장』 ③ 을
등재하지 않는 이유로 **바로 그 계층의 부재**를 적어 두었다:

> 등재해야 한다면 이 단언을 지우는 것이 **할 일이 아니다.** ③ 이 거는 제약
> (「그 턴 어둠 속성 이외를 특수 소환할 수 없다」) 을 적는 계층을 만들고,
> `restricts_others` 를 다시 판단해야 한다.

### 1.2 이 Phase 가 더한 것

| 더한 것 | 어디 |
|---|---|
| `SelfCardCost` — **고를 것이 없는** 「이 카드 자신을 …」 비용 | `engine/cost/model.py` |
| 그 비용의 검증과 지불 | `engine/cost/validation.py` · `engine/payment.py` |
| 비용 의미 `BANISH` → `OperationKind.BANISH` | `engine/payment.py::COST_OPERATION` |
| **발동 관문의 비용 단계** | `engine/activation.py::EffectActivator._check_cost` |
| `CardIdIs` — `c:IsCode(id)` (카드명 조건) | `engine/condition/model.py` |
| `FaceUpCardPresent` — 바벨 조건의 대리 | `engine/condition/model.py` |
| `SummonLimitRegistry` · `AttributeOnlyLimit` — **제한을 적는 표** | `engine/state/summon_limit.py` (새 파일) |
| 그 표를 상태 · 해시 · 사본 · 관측에 연결 | `engine/state/game_state.py` · `engine/game_state_view.py` |
| 제한의 **판정** (`summoned=` 인자) | `engine/summon_restriction.py` |
| `RestrictSpecialSummonOperation` + 실행기 + 변화 기록 | `engine/effect/operation.py` · `executor.py` · `delta.py` |
| 묘지를 발동 출발지로 · 덱을 특수 소환 출발지로 · 덱을 소생 제한 자유 자리로 | `engine/duel.py` · `engine/special_summon.py` · `engine/effect/ruling.py` |
| 앞뒷면 질문을 **필드에서만** 묻는다 (`FACE_SENSITIVE_ZONES`) | `engine/action_validation.py` |
| 디베르 ① 등재 + 네 장의 판정 사실 + 세 장의 금지 표 줄 | `engine/effect/library.py` · `engine/summon_restriction.py` |
| 검증용 경로 · 시작 패 | `deck/combo_policy.py` |
| 제한을 사용자 출력에 적는다 | `deck/report.py` |

---

## 2. 효과 계약과 근거

읽은 자리: `c57835716.lua` · `data/cards.cdb`(57835716) · 공식 한국어 텍스트 ·
`data/constants/archetype_setcode_constants.lua:395`(`SET_ORCUST = 0x11b`).

공식 스크립트 (`e1` 만 — ② 는 §8):

```lua
local e1=Effect.CreateEffect(c)
e1:SetCategory(CATEGORY_SPECIAL_SUMMON)
e1:SetType(EFFECT_TYPE_IGNITION)
e1:SetRange(LOCATION_GRAVE)
e1:SetCountLimit(1,id)
e1:SetCost(Cost.SelfBanish)
e1:SetCondition(s.spcon1)   -- not Duel.IsPlayerAffectedByEffect(tp,CARD_ORCUSTRATED_BABEL)
e1:SetTarget(s.sptg)
e1:SetOperation(s.spop)

function s.filter(c,e,tp)
    return c:IsSetCard(SET_ORCUST)
       and c:IsCanBeSpecialSummoned(e,0,tp,false,false)
       and not c:IsCode(id)
end
function s.sptg(e,tp,...,chk)
    if chk==0 then return Duel.GetLocationCount(tp,LOCATION_MZONE)>0
        and Duel.IsExistingMatchingCard(s.filter,tp,LOCATION_DECK,0,1,nil,e,tp) end
    Duel.SetOperationInfo(0,CATEGORY_SPECIAL_SUMMON,nil,1,tp,LOCATION_DECK)
end
function s.spop(e,tp,...)
    if Duel.GetLocationCount(tp,LOCATION_MZONE)<=0 then return end
    local g=Duel.SelectMatchingCard(tp,s.filter,tp,LOCATION_DECK,0,1,1,nil,e,tp)
    if #g>0 then Duel.SpecialSummon(g,0,tp,tp,false,false,POS_FACEUP) end
    local e1=Effect.CreateEffect(e:GetHandler())
    e1:SetType(EFFECT_TYPE_FIELD)
    e1:SetCode(EFFECT_CANNOT_SPECIAL_SUMMON)
    e1:SetProperty(EFFECT_FLAG_PLAYER_TARGET+EFFECT_FLAG_OATH)
    e1:SetTargetRange(1,0)
    e1:SetTarget(s.splimit)             -- not c:IsAttribute(ATTRIBUTE_DARK)
    e1:SetReset(RESET_PHASE|PHASE_END)
    Duel.RegisterEffect(e1,tp)
end
```

### 2.1 계약표 — 자리마다 따로 읽는다

| 물음 | 읽은 답 | Lua 의 자리 | 옮긴 자리 |
|---|---|---|---|
| **발동 위치** | 묘지 | `SetRange(LOCATION_GRAVE)` | `activation_zones={GRAVE}` |
| **발동 타이밍** | 기동 효과 (판이 열린 상태) | `EFFECT_TYPE_IGNITION` | `activation_kind=IGNITION` |
| **발동 조건** | 빈 몬스터 존 · 특수 소환 금지 없음 · 바벨 미적용 | `s.sptg` 앞부분 · `s.spcon1` | `activation=And(...)` |
| **비용** | **이 카드 자신**을 제외 | `Cost.SelfBanish` | `SelfCardCost.banish({GRAVE})` |
| **비용 지불 시점** | **발동 시점** | `SetCost` | `EffectActivator.activate` 안의 `CostPayer` |
| **덱 후보 조건** | 「오르페골」 몬스터 · **디베르 이외** · 지금 특수 소환할 수 있다 | `s.filter` 세 항 | `require=And(IsMonster, IsSetCard(0x11b), Not(CardIdIs(57835716)))` + 관문 |
| **대상 지정** | **아니다** | `SetOperationInfo(...,nil,...)` | `TargetSpec.choosing(... chosen_at_resolution=True)` |
| **고르는 시점** | **해결 중** | `s.spop` 의 `SelectMatchingCard` | 같음 |
| **특수 소환 위치 · 표시 형식** | 자신 몬스터 존 · 앞면 | `SpecialSummon(g,0,tp,tp,false,false,POS_FACEUP)` | `SpecialSummonOperation` (이 저장소는 앞면 공격 고정) |
| **소환 가능 여부** | 카드별로 묻는다 | `IsCanBeSpecialSummoned` | 관문 `MAY_BE_SPECIAL_SUMMONED` |
| **같은 이름 사용 제한** | 1턴 1번, **카드명** 기준 | `SetCountLimit(1,id)` | `UseLimit(PER_CARD_NAME)` |
| **이후의 제한** | 어둠 속성만 · **자신에게만** · 턴 종료까지 · **소환법 무관** | `EFFECT_CANNOT_SPECIAL_SUMMON` + `SetTargetRange(1,0)` + `s.splimit` + `RESET_PHASE\|PHASE_END` | `RestrictSpecialSummonOperation("DARK")` → `engine.state.summon_limit` |
| **무효 · 불발 시의 비용** | 되돌아오지 않는다 | 비용과 해결이 다른 단계다 | 지불은 발동 경로, 해결기는 그것을 모른다 |

### 2.2 섞지 않은 네 가지

1. **비용과 해결** — 제외는 발동 시점, 특수 소환은 해결 시점. 그래서 해결이
   불발되어도 제외는 그대로다 (§4.4 의 실측).
2. **후보 조건과 관문** — 「오르페골」 · 「디베르 이외」 는 후보 조건이고,
   「지금 특수 소환할 수 있는가」 는 관문의 질문이다. 후자는 카드별로
   등재되어야 하고 등재되지 않으면 `UNKNOWN` 이다 (ADR-006).
3. **카드명 조건과 개체 조건** — 「디베르 이외」 는 **카드명**이다
   (`c:IsCode(id)`). `instance_id` 로 한 장만 빼면 덱의 다른 사본이 조용히
   통과한다 (§4.2 가 사본 둘로 잰다).
4. **「필드에 있어서 막는다」 와 「발동해서 걸었다」** — 디베르의
   `special_summon_restriction_signals` 에는
   `EFFECT_CANNOT_SPECIAL_SUMMON` 이 **있지만**, 그 제한은 ① 의 해결이
   그때 만들어 플레이어에게 등록하는 것이고 그 시점에 디베르는 비용으로
   **제외되어 필드에 없다.** 그래서 금지 표에는 `prohibits=False` 로 적고,
   제한 자체는 **상태의 표**가 들고 있다.

### 2.3 옮기지 **못한** 것 (생략하지 않고 적는다)

- `Duel.IsPlayerAffectedByEffect` 자체. 지속 효과가 **플레이어에게** 걸려
  있는가를 적는 계층이 없어 「바벨이 앞면으로 필드에 있는가」로 옮겼다
  (`FaceUpCardPresent`). **무효화된 바벨을 구별하지 못한다** — 무효화 계층이
  없다.
- `EFFECT_FLAG_OATH` 깃발 자체. 조작 묶음의 **순서**로만 지킨다 (소환 다음에
  제한을 건다 — 공식 스크립트도 그 순서다).
- ~~`#g>0` **밖**의 `RegisterEffect`.~~ → 🔴 **후속 보완에서 옮겼다 (§10).**
  6-AO 의 기록은 이랬고 **그때 사실이었다**: "공식 스크립트는 **고를 후보가
  0장이어도 제한을 건다.** 이 저장소는 `ResolutionSkip(when_no_candidate=True)`
  로 조작 묶음을 통째로 생략하므로 그때 제한도 걸리지 않는다 — **다른
  동작이고, 제한을 덜 거는 쪽이다.** 지금 등재된 효과로는 그 자리에 닿을 수
  없다 (발동 시점에 후보의 존재를 확인했고, 발동과 해결 사이에 덱을 비우는
  등재 효과가 없다)."
  🔴 **"닿을 수 없다" 는 부분이 틀렸다** — 발동과 해결 사이에 판이 바뀌면
  닿는다 (§10.1 의 재현). 지금은 `NoCandidateScope.TARGET_OPERATIONS` 로
  **소환만** 생략하고 제한은 그대로 건다.
- `aux.RegisterClientHint` (표시용 안내).

---

## 3. 판정 · 비용 · 해결 · 제한의 처리

### 3.1 후보 생성과 직접 실행이 같은 판정을 쓴다

두 자리를 고쳤다.

```python
# engine/duel.py::_activation_actions — 6-AN 까지
if definition.cost.costs:
    continue                       # 비용이 있으면 **전부** 건너뛴다

# 6-AO
if definition.cost.choice_specs():
    withheld.append(WithheldAction(..., missing=COST_SELECTION_MISSING))
    continue                       # **고를 것이 있는** 비용만, 그리고 이유를 적는다
```

```python
# engine/activation.py::_check_before_targets — 6-AO 가 더한 마지막 단계
payable = self._check_cost(state, definition, action, chain, verdict)
if payable is not None:
    return payable
```

`_check_before_targets` 는 `can_activate`(실제 발동) 와
`can_activate_ignoring_targets`(후보 생성의 대상 독립 판정) 가 **함께 쓰는**
자리다. 그래서 비용을 치를 수 없는 발동은 **후보에도 오르지 않고** `apply`
에서도 거절된다 — `test_g04` 가 네 판에서 그 둘을 나란히 센다.

🔴 **치르지 않는다.** `CostValidator` 는 관측만 읽는다; 지불은 `activate` 의
일이다.

### 3.2 묘지에 있다는 이유만으로 허가하지 않는다

발동이 거절되는 자리가 여섯이고 **각각 다른 문장**이다 (§4.1 의 실측).

| 판 | 답 | 코드 |
|---|---|---|
| 정상 | 후보가 오른다 | `OK` |
| 디베르가 패에 있다 | **확정 거부** | `source_wrong_zone` |
| 몬스터 존이 꽉 찼다 | 발동 조건 거짓 | `candidate_not_eligible` |
| 덱에 합법 후보가 없다 | 후보 없음 | `no_candidates` |
| 바벨이 앞면으로 있다 | 발동 조건 거짓 | `candidate_not_eligible` |
| 이 턴에 같은 이름을 썼다 | 사용 제한 | `effect_use_limit_reached` |

🔴 **발동 위치가 틀린 것은 `UNKNOWN` 이 아니라 확정 거부다.** 정의가 발동
자리를 적어 두었기 때문이다 (`activation_zones`) — 적지 않은 효과는 여전히
모름으로 남는다.

### 3.3 해결 중 선택은 엔진이 만든 후보 안에서만

고르는 것은 정책이고 **다시 보는 것은 엔진**이다
(`EffectExecutor._check_targets` 의 ③ 단계). 후보 밖 카드를 고르는 정책을
꽂으면 거절되고 판은 바뀌지 않는다 (`test_d03`).

### 3.4 제한 — 적는 자리와 읽는 자리를 가른다

```
RestrictSpecialSummonOperation      ← 효과가 "건다"
        ↓ (해결 중)
engine.state.summon_limit           ← 상태가 "적는다" (해시·사본·관측에 들어간다)
        ↓
assess_special_summon_permission(view, actor, summoned=...)   ← "판정한다"
        ↓
① 효과에 의한 특수 소환   ② 링크 소환   ③ 토큰 생성
```

세 경로 모두 **같은 함수**를 부른다.

| 경로 | 묻는 자리 | 무엇을 넘기는가 |
|---|---|---|
| 효과에 의한 특수 소환 | `BoardRuling.explain_special_summon` | 그 카드의 정의 |
| 링크 소환 | `assess_link_materials` | 소환될 링크 몬스터의 정의 |
| 토큰 | `EffectExecutor._plan_create_token` | 손으로 읽어 대조한 `TokenRule` |

🔴 **`summoned` 를 주지 않으면 이 제한을 보지 않는다.** 판 전체에 걸리는
금지와 달리 이 제한은 **무엇을 소환하는가**에 따라 답이 갈리므로, 카드가
정해지지 않은 자리(발동 조건의 `SpecialSummonPermitted()`) 에서 묻는 것은
틀린 질문이다 — 물으면 「해결 중에 고르는」 효과가 전부 막힌다.

🔴 **모름을 허가로 바꾸지 않는다.** 속성을 읽을 수 없으면 `UNDETERMINED`
이고 그것은 허가가 아니다 (`test_e07`). 관측이 제한 칸을 싣지 않으면 역시
`UNDETERMINED` 다 (`test_e08`).

### 3.5 소환법과 존의 범위

`s.splimit(e,c,sump,sumtype,sumpos,targetp)` 는 **`sumtype` 을 보지 않는다** —
속성 하나만 본다. 그래서 링크 · 융합 · 효과에 의한 특수 소환 **전부**에
걸리고 존도 가리지 않는다. 그 사실을 범위로 좁혀 적으면 다른 소환 경로로
우회된다. 실측으로 **링크 소환**과 **토큰** 두 경로가 막히는 것을 확인했다
(§4.5).

### 3.6 상태와 분기

- **해시에 들어간다** — 들어가지 않으면 「제한이 걸린 판」과 「걸리지 않은
  판」이 탐색의 중복 제거에서 합쳐지고, 한쪽에서만 합법인 소환이 다른 쪽의
  경로로 보고된다 (`test_e09` · `test_e10`).
- **사본은 따로 적는다** — `clone()` 이 표를 복제한다. 한 분기가 걸어 둔
  제한이 다른 분기에 보이면, 그 분기에서는 발동하지도 않은 효과의 제약이
  소환을 막는다 (`test_g02`).
- **지우지 않는다** — 열쇠에 턴 번호가 들어가므로 턴이 바뀌면 자동으로
  만료된다 (`test_e06`).

---

## 4. 작은 준비 상태에서의 검증

> 🔴 **이 절의 시작 상태는 손으로 구성한 것이다** (`tests/
> test_harp_horror_graveyard_effect.py::_board` 가 묘지 · 덱 · 필드 · 패를
> 직접 채운다). **이 판이 기존 시작 패에서 도달 가능하다고 주장하지 않는다** —
> 그 질문의 답은 §6 이다. 첫 행동 **뒤**의 모든 변화는 엔진이 만들었다.

### 4.1 발동의 경계 (실측)

```
--- 정상 (묘지 디베르 · 덱 스켈레촌 · 필드 기르수): 후보 1건
--- 덱에 디베르 사본만: 후보 0건
     보류: no_candidates | 57835716:e[0] … @primary 를 해결 중에 고르려면
            후보가 있어야 합니다: 후보가 0장뿐입니다 (필요 1장).
--- MZONE 5칸 꽉 찼다: 후보 0건
     보류: candidate_not_eligible | … 발동 조건이 거짓입니다:
            (자신 MZONE 에 빈 칸 그리고 …)
--- 바벨 앞면: 후보 0건
     보류: candidate_not_eligible | … 아님(자신 FZONE 에 [90351981] 가 앞면으로 있음)
--- 디베르가 패에: 후보 0건
     보류: source_wrong_zone | 이 효과를 그 자리에서 발동할 수 없습니다
            (공식 스크립트의 SetRange 가 적은 자리: GRAVE).
--- 묘지에 디베르 2장, 1회 해결 뒤 다른 개체로 재발동: 후보 0
     보류: effect_use_limit_reached | 57835716:e[0] 는 1턴에 1번
            (같은 이름의 카드 전체 기준) 이고 이 턴에 이미 1번 썼습니다.
```

### 4.2 정상 해결의 실제 변화 (실측)

```
행동: activate_effect P0 #43 57835716:e[0]
수락: True | ok | 57835716:e[0] 를 체인 1 로 발동했습니다.
(체인 해결)
MZONE     [69811710, 21441617]      ← 덱에서 스켈레촌이 나왔다 (앞면 공격)
GRAVE     []                        ← 디베르가 떠났다
REMOVED   [57835716]                ← 비용으로 제외되었다
제한      T3 P0: DARK 속성 몬스터밖에 특수 소환할 수 없다 ([57835716]:e[0])
uses      name=1                    ← 카드명 기준 1회
```

기록(`EventJournal`) 은 세 가지를 **한 줄에** 적는다:

```
#0 비용 P0: P0 #41 제외
#1 57835716:e[0] P0: P0 가 #0 를 DECK 에서 MZONE[0] 로 special 소환
   (FACEUP_ATTACK), P0 는 이 턴 DARK 속성 몬스터밖에 특수 소환할 수 없다
   ([57835716]:e[0]), P0 의 DECK 20장을 섞었다
```

🔴 **덱을 들여다본 뒤 섞는다** — 룰북이 요구하는 처리이고 기존 계층이 한다.

### 4.3 「디베르 이외」 는 카드명이다

덱에 디베르 사본 **둘**과 스켈레촌 하나를 두면 소환되는 것은 스켈레촌이고,
디베르 사본은 덱에 **그대로** 남는다 (`test_b05`).

### 4.4 비용은 되돌아오지 않는다

발동 **직후**(해결 전) 이미 제외되어 있고 (`test_c03`), 해결이 불발되어도
그대로다. 발동과 해결 사이에 몬스터 존을 채운 실측:

```
발동 수락: True
비용 직후 — GRAVE: []   REMOVED: [57835716]
해결 전 MZONE: [기르수, 페더맨, 페더맨, 페더맨, 페더맨]
해결: "57835716:e[0] 는 해결되었지만 일을 하지 않았습니다 —
       자신 MZONE 에 빈 칸이 없습니다 (5/5). (공식 처리: c57835716.lua 의 s.spop …)"
해결 후 MZONE: 그대로   REMOVED: [57835716]   제한: 없음
```

🔴 **세 사실이 각각 지켜졌다**: ① 정상 불발이고 오류 · 미지원이 아니다,
② 비용은 유지된다, ③ **제한도 걸리지 않는다** (공식 스크립트의 `return` 이
`RegisterEffect` **앞**이다).

### 4.5 제한의 적용 범위 (실측)

```
[실제 제한 · 실제 카드] 디베르 ① 해결 뒤
  페더맨(WIND) 효과 특수 소환: false
    | T3 P0: DARK 속성 몬스터밖에 특수 소환할 수 없다 ([57835716]:e[0])
      — 소환하려는 카드는 WIND 속성입니다.
  갈라테아(DARK) 링크 소환: legal      ← 제한이 전부를 막지 않는다
  기르수(DARK) 효과 특수 소환: true

[합성 제한 — 값만 손으로 적었다] 「WIND 속성만 허용」
  갈라테아 링크 소환: illegal
    | 링크 소환은 특수 소환입니다 — … 소환하려는 카드는 DARK 속성입니다.
    후보: 0건
    보류: link_material_invalid | 고른 소재가 그 링크 몬스터의 소재 조건을
           만족하지 않습니다. (링크 소환은 특수 소환입니다 — …)
  기르수 ③ (성유물 토큰 2장): 발동은 수락 · **토큰은 만들어지지 않았다**
    MZONE: [기르수]   상대 MZONE: []
```

🔴 **합성인 것을 정확히 적는다.** 등재된 링크 몬스터와 토큰이 **전부 어둠
속성**이므로 (실측: 갈라테아 · 갈라테아i · 롱기르수 · 엔릴기르수 · 성유물
토큰 모두 DARK) 실제 제한으로는 **거절 쪽**을 만들 수 없다. 그래서 제한
기록의 **값 하나**만 손으로 적었고, **판정 경로는 production 그대로**다 —
재는 것은 "그 경로가 이 표를 본다" 이다.

### 4.6 적용 시점과 만료

| 시점 | 제한 |
|---|---|
| 발동 직후 (해결 전) | **없다** |
| 해결 뒤 | 하나 (DARK · 자신 · T3) |
| 같은 턴의 상대 자리 | 없다 (`SetTargetRange(1,0)`) |
| 다음 턴 (T4) | 없다 (`RESET_PHASE\|PHASE_END`) |

---

## 5. 새 검증용 레시피와 시작 패

### 5.1 레시피는 **기존 것을 그대로 쓴다**

`deck/combo_policy.py::ORCUST_VERIFICATION_RECIPE` (메인 40 · 엑스트라 6) 에
**디베르가 이미 x3** 들어 있다 (실측: `parse_recipe` 의 `main` 슬롯에서
`57835716: 3` · `21441617: 3` · `94046012: 3`). 그래서 새 레시피를 만들지
않았다 — 만들면 같은 덱이 두 벌이 된다.

🔴 **기존 ORCUST 검증용 입력을 바꾸지 않았다.** `ORCUST_VERIFICATION_HAND` ·
`ORCUST_GIRSU_TOKEN_HAND` 는 한 글자도 그대로이고, `ORCUST_GIRSU_LINE` 은
`note` 한 문단만 고쳤다 (그 문단이 "디베르 효과는 등재되지 않았다" 고
적고 있었고, 그것이 이 Phase 로 거짓이 되었다).

### 5.2 새 시작 패

```python
ORCUST_HARP_HORROR_HAND = (
    69811710,  # 잭나이츠 오르페골 기르수
    703897,    # 오르페골 클리막스
    2930675,   # 성유물에 이르는 열쇠
    12989604,  # 성유물로부터의 자각
    61654098,  # 성유물과의 해후
)
```

- 다섯 장 모두 그 레시피 안에 있고 매수를 넘지 않는다 (`test_f02` 가 센다).
- **「성유물－『성장』」(93920420) 이 없다** — 그래서 기르수 ① 이 덱에서
  꺼내 오는 카드가 **디베르**이고, 패의 『성장』 을 특수 소환하는 기존 경로와
  갈린다.
- **「오르페골 바벨」(90351981) 도 없다** — 바벨이 앞면으로 있으면 ① 은
  발동할 수 없다 (§3.2).

🔴 **대회 합법 덱이라고 부르지 않는다.** 금지 · 제한 데이터가 이 저장소에
없으므로 그 검증은 "전혀 판정하지 못했다" 로 남는다 — 입력 검증의 「알 수
없는 것」 에 그대로 적혀 있고 `test_f02` 가 그것을 센다.

### 5.3 새 검증용 경로

`ORCUST_HARP_HORROR_LINE` (`/combo … line:orcust-harp-horror`) — 네 단계:

| | 단계 |
|---|---|
| 1 | 「잭나이츠 오르페골 기르수」 일반 소환 |
| 2 | 기르수 ① — 덱의 **「오르페골 디베르」** 를 묘지로 (고르는 것은 해결 중) |
| 3 | 묘지의 디베르 ① — **자신을 제외**하고 덱에서 「오르페골 스켈레촌」 특수 소환 |
| 4 | 기르수 + 스켈레촌 을 소재로 「오르페골 갈라테아」 링크 소환 |

🔴 **기존 두 경로를 바꾸지 않았다** — `COMBO_LINES` 에 한 줄이 늘었다.

---

## 6. 직접 실행 경로와 일반 탐색 결과

### 6.1 직접 제출한 검증 경로 (실측)

```
python3 -m app.main combo "69811710,703897,2930675,12989604,61654098" \
  --recipe <검증용 레시피>.ydk --line orcust-harp-horror
```

```
✔ 1. P0 normal_summon · 잭나이츠 오르페골 기르수 [69811710]
✔ 2. P0 activate_effect · 잭나이츠 오르페골 기르수 [69811710]
      효과 69811710:e[0] · 조작 수행
      해결 중 선택 1장: 오르페골 디베르 [57835716] (후보 6장)
✔ 3. P0 activate_effect · 오르페골 디베르 [57835716]
      효과 57835716:e[0] · 조작 수행
      해결 중 선택 1장: 오르페골 스켈레촌 [21441617] (후보 8장)
✔ 4. P0 link_summon · 오르페골 갈라테아 [30741503]
      소재 2장: 잭나이츠 오르페골 기르수 · 오르페골 스켈레촌

  실행 4걸음 · 상태 변경 4걸음 · 막히지 않고 끝난 걸음 4 / 4
  그중 효과의 조작이 실제로 수행된 걸음 2걸음
```

최종 판과 **제한**이 함께 보고된다 (이 Phase 가 `deck/report.py` 에 더한 줄):

```
  엑스트라 몬스터 존: 1장 — 오르페골 갈라테아 [30741503]
  묘지: 2장 — 잭나이츠 오르페골 기르수, 오르페골 스켈레촌
  제외: 1장 — 오르페골 디베르 [57835716]
  남은 덱: 33장

  🔴 이 턴에 걸린 특수 소환 제한 (효과가 건 것):
    - 자신: DARK 속성 몬스터밖에 특수 소환할 수 없습니다
            — 오르페골 디베르 [57835716] 의 e[0] 가 걸었습니다 (턴 종료까지)
```

### 6.2 일반 탐색 (실측) — **스스로 찾았다**

```
python3 -m app.main combo "69811710,703897,2930675,12989604,61654098" \
  --recipe <검증용 레시피>.ydk --search galatea
```

```
✔ 도달 — 목표 도달
행동 4걸음 · 해결 중 선택 2회 · 펼친 노드 28개 · 최대 깊이 3 · 54.39초
예산: 깊이 8 · 노드 300 · 300초 · 선택 분기 8 · 중복 제거 켜짐
예산에 걸리지 않았습니다 (중복 제거로 버린 노드 2개).

찾은 경로
  1. 일반 소환
  2. 효과 발동 (해결 중 선택 [57835716])    ← 디베르를 스스로 골랐다
  3. 효과 발동 (해결 중 선택 [21441617])    ← 스켈레촌을 스스로 골랐다
  4. 링크 소환
```

그 자리의 **허용 후보가 기록에 그대로 남는다** (고른 것만 적지 않는다):

```
2. 선택 [0] 69811710:e[0] 후보 6장 중 1~1장 → 57835716
     그 자리의 허용 후보: #19[57835716] · #20[57835716] · #21[57835716]
                        · #29[93920420] · #30[93920420] · #31[93920420]
3. 선택 [0] 57835716:e[0] 후보 8장 중 1~1장 → 21441617
     그 자리의 허용 후보: #6[21441617] · #7[21441617] · #8[21441617]
                        · #24[69811710] · #25[69811710]
                        · #32[94046012] · #33[94046012] · #34[94046012]
```

🔴 **탐색기에 「디베르면 이 순서」 를 적지 않았다.** 목표 판정은 `FieldGoal`
하나이고 후보는 엔진이 허가한 것뿐이다 — 그래서 §6.1 과 §6.2 는 **다른
질문의 답**이다: 저쪽은 적어 둔 순서를 밟았고, 이쪽은 엔진이 찾았다.

### 6.3 롱기르수(LINK-3) 는 이번에도 닿지 않았다

6-AN 이 등재한 롱기르수는 소재가 **2~3장이고 기여의 합이 3** 이어야 한다.
이 경로가 만드는 필드는 기르수 + 스켈레촌 **두 장**이고 둘 다 기여가 `{1}`
이므로 합이 2 에서 멈춘다 — 즉 거절 사유는 **소재 부족**이다 (6-AN 보고서
§5.3 과 같은 모양). 디베르 ① 은 1턴 1번이므로 세 번째 몬스터를 더 세울
수단이 이 등재 범위에 없다.

🔴 **롱기르수 도달은 이번 완료 조건이 아니다** (요구 §5). 그리고 **불가능하다고
적지 않는다** — 스켈레촌 · 카노네의 ① 이 등재되면 세 번째 몬스터를 세우는
길이 생길 수 있고, 그것은 §8 의 목록에 있다.

---

## 7. 전체 경로 재생 결과

```
경로 재생 (새 초기 상태에서 다시 실행): ✔ 성공
  걸음 4개를 새 초기 상태에서 다시 밟아 같은 최종 판에 닿았습니다.
  재생 최종 해시: e66020d1c942d059bea4d578bfd68c5d6479b6b571ff4b958ad88815da3998d0
```

재생은 같은 입력(레시피 · 시작 패) 에서 **다시 조립한** 초기 상태에서 돌고,
**카드 선택 · 비용 · 제한 · 최종 상태**를 함께 확인한다 — 경로의 걸음마다
그때의 허용 후보를 다시 찾으므로 (`PathStep.action_key`), 선택이 달라졌다면
재생이 실패한다. `test_f03` 이 같은 것을 단위 시험으로 고정한다 (경로에
`57835716` 선택과 링크 소환이 들어 있는지까지 본다).

---

## 8. 아직 막히는 기능

### 8.1 이 카드에 대해

- **② (유발즉시) 는 등재하지 않았다.** `EFFECT_TYPE_QUICK_O` + 조건이
  「바벨이 적용되고 있다」 이고, 유발즉시의 발동 시점을 룰북에서 읽지 못했다
  (`ACTIVATION_KINDS_IN_SCOPE` · ADR-006). 🔴 **그래서 바벨이 깔린 판에서
  디베르는 발동할 수 없다** — ① 은 조건이 거짓이고 ② 는 미지원이다.
- **바벨 자신의 효과도 등재하지 않았다.** `IsPlayerAffectedByEffect` 를
  「앞면으로 필드에 있는가」로 옮겼으므로 **무효화된 바벨을 구별하지 못한다.**
- ~~**`#g>0` 밖의 제한 등록을 옮기지 못했다**~~ → 🔴 **후속 보완에서
  옮겼다 (§10).** 6-AO 의 기록은 "공식 스크립트는 고를 후보가 0장이어도
  제한을 걸고, 이 저장소는 그때 묶음을 통째로 생략한다. **제한을 덜 거는
  쪽**이고, 지금 등재된 효과로는 그 자리에 닿을 수 없다" 였다. 앞 문장은
  그때 사실이었고 **뒤 문장이 틀렸다** — 발동과 해결 사이에 판이 바뀌면
  닿는다. 지금은 **소환만** 생략하고 제한은 걸린다 (§10).
- **표시 형식을 고르지 못한다.** `POS_FACEUP` 은 앞면 공격 · 앞면 수비를
  고를 수 있다는 뜻인데 이 저장소는 앞면 공격으로 고정했다 (STRUCTURAL-61).

### 8.2 이 효과로 소환한 몬스터에 대해

🔴 **스켈레촌(21441617) · 카노네(94046012) 의 ① 은 등재하지 않았다.** 이번
경로에서 그 카드들은 **링크 소재로만** 쓰인다. 둘 다 디베르와 같은 모양의
제한을 걸고 (`EFFECT_CANNOT_SPECIAL_SUMMON` + `s.splimit`), 금지 표의
`prohibits=False` 는 **그 효과가 등재되지 않았다**는 사실에 근거한다 —
등재하면 그 줄을 디베르와 같은 근거로 다시 적어야 한다.

이 Phase 가 그 둘에 대해 읽은 것은 **`MAY_BE_SPECIAL_SUMMONED` 하나**다
(디베르 ① 의 후보가 되기 위해). 다른 질문은 묻지 않았고, 묻지 않은 것을
참으로 채우지 않았다.

### 8.3 특수 소환 사건의 유발 (실측)

디베르 ① 로 덱에서 **기르수**를 특수 소환하면 기록은 소환으로 적지만
(`special 소환 (FACEUP_ATTACK)`), 기르수 ① 의 유발은 **열리지 않는다**:

```
특수 소환 뒤 유발 제안: []
```

이유는 등재 범위다 — 등재된 `69811710:e[0]` 은 `EVENT_SUMMON_SUCCESS`
(**일반 소환**) 에서 컴파일되고, 특수 소환 쪽 복제본(`e[1]`,
`EVENT_SPSUMMON_SUCCESS`) 은 등재되지 않았다. 🔴 **사건이 없는 것과 등재가
없는 것은 다른 사실이므로 둘을 함께 적는다** (`test_d02`).

### 8.4 다른 미지원 (같은 실행에 남아 있는 것)

```
link_summon [link-material-requirement]: 엑스트라 덱 6장 중 3장의 소재 조건을
  아직 읽지 않았다 (오케스트리언 · 엔릴기르수 · 딩기르수)
activate_card [activation-timing (Phase 2-C/2-F)]: activate_card 의 남은
  적법성을 판정할 규칙 계층이 아직 없다 (패의 마법 · 함정)
```

### 8.5 이번 변경이 **기존 출력을 바꾼 자리** (실측)

🔴 **숨기지 않고 적는다.** 아래는 전부 이 Phase 의 등재가 만든 변화이고,
기존 기대값을 고친 자리는 §9.4 에 근거와 함께 있다.

| 자리 | 6-AN 까지 | 6-AO 부터 | 왜 |
|---|---|---|---|
| `/combo` **기본(자율)** 실행에서 기르수 ① 이 덱에서 꺼내는 카드 | 「성유물－『성장』」(93920420) | **「오르페골 디베르」**(57835716) | 그 선택은 기준점 `FirstPermittedChoice` 가 집는다 (허용 후보의 앞쪽). 6-AN 까지 허용 후보는 『성장』 **한 장뿐**이었다 — 디베르를 묘지로 보낼 수 있는지가 등재되지 않아 `UNKNOWN` 이었고 ADR-006 으로 후보가 되지 못했다. 이 Phase 가 그 사실을 읽어 등재하자 후보가 둘이 되었고 패스코드가 더 작은 디베르가 앞이다 |
| 같은 실행의 **멈춘 분류** | `flow_only` (그 자리 보류 0건) | **`unsupported`** (보류 2건) | 묘지에 디베르가 있으므로 디베르 ① 이 발동 자리에 오르지만, 기르수 ③ 이 만든 성유물 토큰(46647145)의 특수 소환 금지 여부를 읽은 것이 없어 해결 중 후보의 존재가 `UNKNOWN` 이다. 🔴 **그 `UNKNOWN` 을 OK 로 바꾸지 않았다** |
| `--line orcust-girsu` · `--line orcust-girsu-token` | 『성장』 경로 · 토큰 경로 | **그대로** | 경로는 `resolution_preferences` 를 선택 정책에 싣는다 (`app.main.opening_wiring(repository, line)`) — CLI 와 Discord 어댑터 둘 다 그렇게 부른다 |
| 묘지가 **발동 출처**가 된다 | 묘지는 보지 않았다 | `ACTIVATION_SOURCE_ZONES` 에 들어왔다 | 「묘지의 이 카드를 제외하고 발동할 수 있다」 를 판정할 기회를 주는 유일한 방법이다. 🔴 **부수 효과**: 묘지에 **등재된 효과를 가진 카드**가 있으면 그 자리에 보류 1건이 생긴다 (마법이면 `off-field-activation-timing` — 이 Phase 가 `on-field-activation-timing` 과 **이름을 갈랐다**: 묘지의 카드는 필드에 없다) |
| 제한 전개 탐색의 분기 수 | 기르수 ① 의 해결 중 선택 후보가 『성장』 뿐이었다 (디베르 시작 패에서 **3장** · 기르수 시작 패에서 **2장** — 그 패는 『성장』 한 장을 들고 있다) | **6장** · **5장** (디베르 x3 이 더해졌다) · 디베르 ① 은 **8장** (스켈레촌 x3 · 기르수 x2 · 카노네 x3) | 등재가 늘면 합법 후보가 는다. 실측은 §6.2 의 탐색 기록과 `scratchpad/ao/probe_pgc.py` 의 `ChoiceAsk.offered` 다 |
| 기르수 ① 가지의 **최초 도달 깊이** | 『성장』 이 묘지로 가면 `EVENT_TO_GRAVE` 로 **또 하나의 발동 기회**가 열려 그 자리에서 판이 정리되지 않았다 → 최초 도달은 `패스` 쪽이 먼저 | 디베르는 묘지로 **보내질 때** 발동하는 효과가 없어 판이 바로 정리된다 → 같은 깊이에서 도달하고 `_order_key` 가 `"activate_effect" < "pass"` 로 줄 세우므로 **발동 쪽이 앞** | 실측 (기준 HEAD `9ab4e38` 와 대조): 기준점이 `['normal_summon','pass']` → `['normal_summon','activate_effect']` |
| `EffectActivator.can_activate` | 비용을 **보지 않았다** (STRUCTURAL-56) | **본다** (`_check_cost` — 같은 `CostValidator`) | 디베르 ① 이 **비용 있는 첫 등재 효과**다. 보지 않으면 치를 수 없는 비용의 발동이 후보로 올라가고 `apply` 에서만 거절된다 |
| `GameState.state_hash()` | — | **값이 바뀐다** | 정규 표현에 `summon_limits` 가 들어왔다 (§3.6). 제한이 없는 판도 값이 달라지므로 **이전 보고서에 적힌 해시와 비교할 수 없다**. 제한을 해시에서 빼면 탐색의 중복 제거가 제한이 걸린 판과 걸리지 않은 판을 합친다 |

🔴 **이 Phase 가 만들지 않은 실패 1건.** `tests/agent/
test_opponent_resource_weighting_audit.py::test_07_a_whole_duel_never_offers_a_
choice_about_opponent_resources` 는 **기준 HEAD `9ab4e38` 에서도 실패한다** —
그 커밋을 `git worktree` 로 따로 풀고 `data/cards.cdb` · `data/constants` 를
붙여 돌려 확인했다 (`1 failed, 15 passed in 4.80s`, 같은 단언 `{1, 2} == {1}`).
원인은 **세트한 통상 마법이 상대 턴에 발동 후보로 오르는 자리**이고 (실측:
「욕망의 선물」(5915629)이 뒷면으로 마법 & 함정 존에 있고 턴 플레이어가 상대일
때 `activate_effect` 가 허용된다), 이 Phase 의 범위가 아니다. 🔴 **고치지
않았고, 통과했다고 적지도 않는다.**

### 8.6 범위 밖

상대 방해를 탐색하는 AI · 실전 강도 평가 · 승률 계산 · 범용 Lua 실행기 개편 ·
LLM · 외부 시뮬레이터 · 탐색 알고리즘 전면 개편. 🔴 **이 Phase 는 효과 하나와
그것을 정확히 처리하는 최소 공통 기능을 더한 것이고, 전개의 좋음을 재는
기준을 더하지 않았다.**

---

## 9. 실행한 테스트 명령과 결과

실행한 것만 적는다. 실행하지 않은 검사는 "통과" 라고 적지 않는다.

### 9.1 이번 단계의 새 시험

```
timeout 1800 python3 -m pytest tests/test_harp_horror_graveyard_effect.py \
  -q -rf -p no:randomly
→ 36 passed in 84.18s
```

🔴 모든 수정을 반영한 뒤 §9.2 ④ 의 묶음 ② 안에서 **다시** 돌았다
(`210 passed in 450.87s` — 이 파일 36건을 포함한다).

| 절 | 무엇을 재는가 |
|---|---|
| A (5건) | 계약이 등재표와 같은가 · ② 는 등재되지 않았는가 · 읽은 판정 사실 · 금지 표의 세 줄 · 넓힌 공용 계층 셋의 범위 |
| B (7건) | 정상 발동 · 패에서의 발동(확정 거부) · 빈 칸 없음 · 후보 없음 · **카드명 제외** · 바벨 · 카드명 사용 제한(다른 개체 우회 불가) |
| C (4건) | 고를 것이 없는 비용 · 치를 수 없는 비용(판 불변) · **비용은 발동 시점** · 해결 불발 뒤에도 비용 유지(제한도 걸리지 않는다) |
| D (3건) | 해결의 전체 변화와 세 기록 · 특수 소환 **사건**과 유발의 등재 범위 · 허용 후보 밖 선택 거절 |
| E (10건) | 실제 제한의 거절·허용 경계 · 링크 경로 · 토큰 경로 · 적용 시점 · 만료 · 모름을 허가로 바꾸지 않음 · 관측에 칸이 없을 때 · 해시 포함 |
| F (3건) | 시작 패부터의 네 걸음 · 새 패와 레시피의 기존 검증 · **일반 탐색의 발견과 전체 경로 재생** |
| G (4건) | 사본에서의 비용 지불과 원본 불변 · 분기 간 제한 격리 · 손으로 만든 행동의 같은 검사 · 후보 목록과 관문의 일치(네 판) |

### 9.2 직접 영향받는 기존 회귀

**① 먼저 좁게 — 비용 · 조건 · 상태 · 특수 소환 · 발동 관문**

```
timeout 3000 python3 -m pytest \
  tests/engine/test_cost_model.py tests/engine/test_cost_payment.py \
  tests/engine/test_cost_validation.py tests/engine/test_condition_model.py \
  tests/engine/test_condition_evaluator.py tests/engine/test_game_state.py \
  tests/engine/test_game_state_view.py tests/engine/test_effect_library.py \
  tests/engine/test_effect_execution.py tests/engine/test_effect_special_summon.py \
  tests/engine/test_special_summon.py tests/engine/test_action_validation.py \
  tests/engine/test_activation_gate_parity.py \
  tests/engine/test_legal_action_candidate_consistency.py \
  tests/engine/test_graveyard_movement_ruling.py -q -rf -p no:randomly
→ 8 failed, 550 passed in 28.26s      (실패 8건은 모두 §9.4 의 낡은 기대값)
```

**② 공통 소환 제한 계층을 바꿨으므로 엔진 모음 전체로 넓혔다**

> 🔴 요구 §9 의 "공통 소환 제한 계층을 변경했다면 해당 계층의 회귀 범위를
> 넓혀라" 에 따른 것이다. 세 번 돌렸고 **매번 수치를 그대로 적는다** — 앞의
> 실행 수치를 뒤의 결과처럼 쓰지 않는다.

```
timeout 3000 python3 -m pytest tests/engine -q -rf -p no:randomly
→ 65 failed, 3817 passed in 761.90s   (1회 — 낡은 census · fixture)
→ 30 failed, 3852 passed in 783.19s   (2회 — 고치는 중)
→ 3882 passed in 766.71s              (3회 — 전부 통과)
→ 3882 passed in 776.91s              (4회 — `off-field-activation-timing` 을
                                       가른 뒤)
→ 3882 passed in 782.17s              (5회 — **최종**, 모든 수정 반영)
```

**③ 전개 경로 · 출력 · 탐색 · 어댑터 (위험에 맞춰 고른 범위)**

```
timeout 3000 python3 -m pytest \
  tests/test_orcust_girsu_line.py tests/test_girsu_token_line.py \
  tests/test_girsu_token_chain_integration.py \
  tests/test_link_material_count_and_rating.py \
  tests/test_longirsu_link_summon.py \
  tests/test_harp_horror_graveyard_effect.py \
  tests/test_combo_output_consistency.py \
  tests/test_withheld_reason_propagation.py \
  tests/test_resolution_outcome_four_cases.py -q -rf -p no:randomly
→ 17 failed, 193 passed in 359.74s    (1회 — §9.4 의 낡은 기대값)

timeout 3000 python3 -m pytest \
  tests/test_bounded_search_first_pass.py \
  tests/test_bounded_search_multi_results.py \
  tests/test_bounded_search_rerun_limits.py \
  tests/test_bounded_search_rerun_apply_errors.py \
  tests/test_post_goal_continuation.py \
  tests/test_post_goal_continuation_boundaries.py \
  tests/test_result_ranking_v1.py tests/test_discord_bot.py \
  tests/test_summon_prohibition_and_resolution_choice.py -q -rf -p no:randomly
→ 7 failed, 264 passed in 1699.34s    (1회 — §9.4 의 낡은 기대값)
```

고친 뒤 파일별로 다시 돌린 것 (실측):

```
tests/test_orcust_girsu_line.py                      → 37 passed in 160.80s
tests/test_girsu_token_line.py                       → 36 passed in 40.03s
tests/test_combo_output_consistency.py               → 9 passed in 52.34s
tests/test_withheld_reason_propagation.py
  + tests/engine/test_effect_action_space_audit.py
  + tests/engine/test_activation_gate_parity.py       → 86 passed in 47.78s
tests/test_resolution_outcome_four_cases.py          → 8 passed in 44.40s
tests/test_activation_action_semantic_boundary_audit.py → 30 passed in 75.74s
tests/test_dormant_live_gate_equivalence.py          → 41 passed in 28.90s
tests/test_effectdefinition_activation_audit.py      → 15 passed in 17.41s
tests/test_trigger_condition_separation_audit.py     → 18 passed in 3.14s
tests/test_unimplemented_rule_semantics_audit.py     → 17 passed in 8.65s
네 snapshot 감사의 그 시험 넷                          → 4 passed in 23.07s
tests/test_summon_prohibition_and_resolution_choice.py → 21 passed in 77.03s
tests/test_post_goal_continuation.py                 → 28 passed in 603.21s
tests/test_post_goal_continuation_boundaries.py      → 18 passed in 322.81s
```

**④ 마지막으로 — 모든 수정을 반영한 뒤 네 묶음으로 전부 다시**

🔴 **한 번에 돌리지 못했다.** 바꾼 시험 파일 전부를 한 명령으로 돌리면
`timeout 3000` 에 걸려 82% 에서 끊겼다 (실측 2회). 그래서 **네 묶음으로
나눠** 돌렸고, 아래가 그 전부다 — 바꾼 시험 파일 **28개**와 새 시험 파일이
모두 이 넷 안에 들어 있다.

```
① 감사 · census 묶음 (20개 파일)
timeout 2400 python3 -m pytest \
  tests/agent/test_opponent_resource_weighting_audit.py \
  tests/test_activation_action_semantic_boundary_audit.py \
  tests/test_auxiliary_effect_creation_clone_audit.py \
  tests/test_binding_rule_alignment.py tests/test_branch_setter_audit.py \
  tests/test_clone_sibling_contamination_audit.py \
  tests/test_create_effect_ordinal_audit.py \
  tests/test_dormant_live_gate_equivalence.py \
  tests/test_effect_block_alignment_audit.py \
  tests/test_effect_block_handler_identity_audit.py \
  tests/test_effect_block_handler_identity_model.py \
  tests/test_effectdefinition_activation_audit.py \
  tests/test_effectdefinition_trigger_boundary_audit.py \
  tests/test_event_free_chain_semantics_audit.py \
  tests/test_handler_binding_diagnostics.py \
  tests/test_loader_analyzer_binding_consistency.py \
  tests/test_trigger_condition_separation_audit.py \
  tests/test_trigger_semantics_audit.py \
  tests/test_unimplemented_rule_semantics_audit.py \
  tests/test_variable_rebinding_audit.py -q -rf -p no:randomly
→ 1 failed, 646 passed in 2146.05s
   🔴 그 1건은 `test_opponent_resource_weighting_audit::test_07` 이고
   **기준 HEAD 에서도 실패하는 선재 결함**이다 (§8.5 의 마지막 문단).

② 전개 경로 · 출력 묶음 (9개 파일 — 새 시험 파일 포함)
timeout 2900 python3 -m pytest \
  tests/test_orcust_girsu_line.py tests/test_girsu_token_line.py \
  tests/test_combo_output_consistency.py \
  tests/test_harp_horror_graveyard_effect.py \
  tests/test_longirsu_link_summon.py \
  tests/test_girsu_token_chain_integration.py \
  tests/test_link_material_count_and_rating.py \
  tests/test_resolution_outcome_four_cases.py \
  tests/test_withheld_reason_propagation.py -q -rf -p no:randomly
→ 210 passed in 450.87s

③ 탐색 · 추천 · 어댑터 묶음 (4개 파일)
timeout 2900 python3 -m pytest \
  tests/test_bounded_search_first_pass.py \
  tests/test_bounded_search_multi_results.py \
  tests/test_result_ranking_v1.py tests/test_discord_bot.py \
  -q -rf -p no:randomly
→ 166 passed in 415.36s

④ 후속 탐색 · 소환 제한 묶음 (느려서 파일별로 돌렸다)
timeout 2400 python3 -m pytest tests/test_post_goal_continuation.py \
  -q -rf -p no:randomly                       → 28 passed in 603.21s
timeout 2700 python3 -m pytest \
  tests/test_post_goal_continuation_boundaries.py -q -rf -p no:randomly
                                              → 18 passed in 322.81s
timeout 1200 python3 -m pytest \
  tests/test_summon_prohibition_and_resolution_choice.py -q -rf -p no:randomly
                                              → 21 passed in 77.03s
```

### 9.3 실제 입력 실행 (§6 의 측정)

🔴 **아래 둘은 모든 수정을 반영한 뒤 다시 측정한 값이다** — 앞선 실행의
수치를 그대로 옮기지 않았다.

```
python3 -m app.main combo "69811710,703897,2930675,12989604,61654098" \
  --recipe <검증용 레시피>.ydk --line orcust-harp-horror
→ 종료 코드 0 · real 0m12.082s
→ ✅ 경로를 끝까지 실행했습니다 (4/4단계) · 4걸음 전부 수락 · 상태 변경 4걸음
→ 효과의 조작이 수행된 걸음 2 (69811710:e[0] · 57835716:e[0])
→ 엑스트라 몬스터 존 1장 「오르페골 갈라테아」 · 제외 1장 「오르페골 디베르」
   · 묘지 2장 (기르수 · 스켈레촌)
→ 보고에 적힌 제한: "자신: DARK 속성 몬스터밖에 특수 소환할 수 없습니다 —
   오르페골 디베르 [57835716] 의 e[0] 가 걸었습니다 (턴 종료까지)"
→ 멈춘 이유: 검증용 선택 방식이 고를 행동을 찾지 못했습니다 (경로가 끝났다)
→ 전체 지원 상태: 🔴 끝까지 검증하지 못했습니다 (미지원 2건 — §8.4)

python3 -m app.main combo "69811710,703897,2930675,12989604,61654098" \
  --recipe <검증용 레시피>.ydk --search galatea
→ 종료 코드 0 · real 1m21.602s
→ ✔ 도달 · 행동 4걸음 · 해결 중 선택 2회 · 펼친 노드 28개 · 최대 깊이 3
   · 54.39초 (예산: 깊이 8 · 노드 300 · 300초 · 선택 분기 8)
→ 경로: 일반 소환 / 효과 발동 (해결 중 선택 [57835716]) /
   효과 발동 (해결 중 선택 [21441617]) / 링크 소환
→ 그 자리의 허용 후보가 기록에 남는다 — 기르수 ① 6장 · 디베르 ① 8장
→ 경로 재생 (새 초기 상태에서 다시 실행): ✔ 성공 · 최종 판 해시
   e66020d1c942d059bea4d578bfd68c5d6479b6b571ff4b958ad88815da3998d0
   (재생 최종 해시도 같다)
```

🔴 **실제 Discord 메시지는 보내지 않았다.** 어댑터 쪽은 기존 단위 시험으로만
확인했다 (`tests/test_discord_bot.py`).

### 9.4 고친 낡은 기대값 — **왜 이전 기대값이 맞았는가**

🔴 **조건을 약하게 만들어 통과시킨 것이 하나도 없다.** 전부 "그때는 그것이
사실이었고, 이 Phase 가 **읽어서** 사실을 바꿨다" 는 종류이고, 각 자리에
근거를 함께 적었다.

| 자리 | 이전 기대 | 바뀐 뒤 | 왜 이전 기대가 맞았는가 |
|---|---|---|---|
| `test_cost_payment::test_unsupported_cost_kinds_are_named_not_guessed` | 제외가 **치를 수 없는** 비용 | 목록에서 제외를 빼고 **치를 수 있다**를 새 시험이 받는다 | `COST_OPERATION` 에 그 줄이 없었다 — 6-AO 가 더했다 |
| `…::test_the_supported_set_is_exactly_what_the_step_promised` | 셋 | 넷 (+`BANISH`) · 들어오지 **않은** 셋도 함께 센다 | 같은 이유 |
| `test_special_summon::test_a_the_procedure_says_what_it_supports` | `{HAND, GRAVE}` | `{HAND, GRAVE, DECK}` · 엑스트라 덱은 **여전히 없다** | 덱에서 특수 소환하는 효과가 없었다 |
| `…::test_g_5_an_unsupported_source_stops_the_execution` | 덱을 예시로 썼다 | **엑스트라 덱**으로 바꾸고, 덱은 새 시험(`g_5b`)이 받는다 | 재는 사실은 "목록에 없는 자리는 거절한다" 이고 특정 존이 아니다 |
| `…::test_i_only_one_library_effect_special_summons` | 특수 소환 효과 **하나** · 소환 종류 하나 | **둘** (+디베르 ①) · `RESTRICT_SPECIAL_SUMMON` 은 소환하는 일이 아니므로 따로 센다 | 그때 등재가 하나였다 |
| `test_legal_action_candidate_consistency::test_i03` | 보류를 만드는 자리 **아홉** | **열** (+`_activation_actions`) · 그 자리는 언제나 `missing` 을 채운다 | 그때 그 함수는 보류를 만들지 않고 **조용히** 건너뛰었다 (6-AO 가 그것을 고쳤다) |
| `test_graveyard_movement_ruling::test_d01` | 증거를 가진 후보 **하나** | 수를 박지 않고 **등재된 것과 등재되지 않은 것의 합**을 센다 (+디베르) | 그때 하나였다 |
| `…::test_g05` | `already == 685` · 합 1,675 | `686` · 1,676 · `newly_true` 는 **그대로 990** | 디베르는 파생이 답하지 못한 카드였다 (실측: `self_grave_text_fact` → `None`) |
| `test_deck_to_grave_blocker` 를 쓰는 **11개 fixture 자리** | 「성유물－『성장』」 이 "묘지로 보낼 수 있다" 의 첫 후보였다 | 등록소에서 **아직 선언되지 않은 카드**를 뽑는 `_undeclared_grave_pool(repository)` 로 바꿨다 | 디베르에 `MAY_BE_SENT_TO_GRAVE` 를 선언하자 패스코드가 더 작은 디베르(57835716 < 93920420)가 "첫 허용 후보" 가 되어 fixture 가 가리키던 카드가 바뀌었다. 🔴 **그 시험들이 재는 것은 "선언되지 않은 카드는 후보가 되지 못한다" 이고 특정 카드가 아니다** — 그래서 카드를 박지 않고 등록소에서 **파생**한다 |
| 등재 수를 세는 **~31개 파일** | `len(EFFECT_LIBRARY) == 20` · 실행 가능 17 · `len(OPERATION_RULINGS) == 22` | **21** · **18** · **25** | 디베르 ① 이 등재되고 (`executable=True`), 판정 사실 셋이 더해졌다 (기르수 · 디베르 · 스켈레촌 · 카노네 중 새 카드 셋) |
| `test_cost_validation::test_d_can_activate_does_not_promise_the_cost_can_be_paid` | `can_activate` 는 비용을 **보지 않는다** (STRUCTURAL-56) | 이름을 `…test_d_can_activate_now_checks_whether_the_cost_can_be_paid` 로 바꾸고 **둘이 같은 답을 낸다**를 잰다 | 디베르 ① 이 **비용 있는 첫 등재 효과**이므로, 보지 않으면 치를 수 없는 비용의 발동이 후보로 올라간다. 🔴 **약해진 것이 아니라 더 센 단언이다** |
| `test_dormant_live_gate_equivalence` (`test_19` · `test_20` · `test_21` · `test_33`) | `COST_FEASIBILITY` 는 `DIFFERENT_RESULT` · `validate_group` 호출자 **하나** · 비용 있는 등재 효과 **0개** · `engine/duel.py` 에 `if definition.cost.costs:` | **둘이 같다** · 호출자 **둘** (그 둘이 무엇인지까지 못박는다) · 비용 있는 효과 **하나**(`57835716:e[0]`) · `if definition.cost.choice_specs():` | 3-E-44 의 측정은 그때 맞았고 **그 전제(비용 있는 등재 효과가 없다)가 이 Phase 에 끝났다**. 파일 머리말에 그 경위를 적었다 |
| `test_orcust_girsu_line::_run_line` · `test_a04` | `opening_wiring(repository)` — 경로를 넘기지 않았다 | `opening_wiring(repository, ORCUST_GIRSU_LINE)` | production 은 CLI·Discord 모두 경로를 넘긴다. 경로를 빼고도 돌았던 이유는 기르수 ① 의 허용 후보가 그때 『성장』 **한 장뿐**이어서 기준점이 우연히 같은 것을 집었기 때문이다. 🔴 **고친 것은 기대값이 아니라 배선**이다 |
| `test_orcust_girsu_line::test_d03` · `test_g04` | 제한을 든 효과 **셋** · 경로 **둘** | **넷** (+`57835716:e[0]`) · **셋** (+`orcust-harp-horror`) | 등재와 경로가 늘었다 |
| `test_girsu_token_line::UNJUDGED` · `test_summon_prohibition_and_resolution_choice` 의 `test_h05` · `test_h08` | 「오르페골 스켈레촌」 · 「오르페골 디베르」 가 "신호를 적었는데 표에 없는" 예시였다 | **「오르페골 트로이메어」(4055337)** 로 옮겼다 | 이 Phase 가 그 둘의 신호를 **읽어서 표에 적었다** (`prohibits=False`). 재는 것은 "읽지 않은 신호는 `UNDETERMINED` 다" 이고 특정 카드가 아니다. 실측: 신호를 적었고 표에 없는 몬스터가 **536장**이며 그중 「오르페골」 계열은 트로이메어 하나다 |
| `…::test_h10` | 금지 표 **세 줄** | **여섯 줄** (+디베르 · 스켈레촌 · 카노네, 전부 `prohibits=False`) | 셋 다 「그 카드의 ① 을 쓴 턴에만」 걸리는 제한이고, 턴에 걸리는 쪽은 `engine.state.summon_limit` 가 따로 들고 판정한다 — **버린 것이 아니다** |
| `…::test_j05` | `preferred` 없이 돌려 묘지의 『성장』 을 찾았다 | `preferred=(WAND,)` 를 준다 | 기준점이 디베르를 집으면 묘지에 『성장』 이 없어 **재려는 질문에 닿지도 못한다** (`StopIteration`). 경로가 적는 것과 같은 자리로 『성장』 을 집게 했다 |
| `test_combo_output_consistency::test_06` · `test_07` | `flow_only` · 둘째 효과 해결이 `93920420:e[1]` | **`unsupported`** (보류 2건 — 무엇인지까지 적는다) · `69811710:e[2]` | §8.5 의 첫 두 줄이 그 이유다. 🔴 수는 그대로다 (`executed` 6 · `resolved` 6 · `effects_resolved` 2) |
| `test_withheld_reason_propagation::test_h02` | 앞면 욕망의 항아리를 **묘지**로 치웠다 | **제외 존**으로 치운다 | 6-AO 가 묘지를 발동 출처로 더했으므로 **묘지는 더 이상 조용한 자리가 아니다**. 🔴 기대값(`fully_supported is True` · `unsupported == []`)을 약하게 고치는 대신 **구성에서 그 카드를 치웠다** — 재는 요구(뒷면 카드 유무만으로 지원 상태가 달라지지 않는다)는 그대로다 |
| `test_resolution_outcome_four_cases::test_n05` | `resolution_skip` 을 선언한 정의 **둘** | **셋** (+디베르 ①, 근거는 `c57835716.lua` 의 `s.spop`) | 등재가 늘었다. 일괄 완화가 아니라 **카드마다 그 카드의 해결 함수에서 읽은 선언**이라는 사실은 그대로다 |
| `test_activation_action_semantic_boundary_audit::test_12` | 카드 19장 · 몬스터 3 · 실행되는 몬스터 3 · 합 16 | **20** · **4** · **4** · **17** | 마법·함정 쪽 16·13 은 **하나도 움직이지 않았다** — 늘어난 쪽이 몬스터이고 거기뿐이다 |
| 네 snapshot 감사 (`branch_setter` · `clone_sibling_contamination` · `create_effect_ordinal` · `variable_rebinding`) | 기동 효과의 블록 수 표에 두 카드 | **디베르 3블록**을 더했다 (①기동 · ②유발즉시 · 해결이 등록하는 `EFFECT_CANNOT_SPECIAL_SUMMON`) | 표가 카드별 실측이므로 새 카드는 줄을 더해야 한다 (`KeyError` 였다) |
| `test_effectdefinition_activation_audit::test_11` · `test_12` | Lua `SetCondition` 을 가진 등재 효과 **둘** · `activation` 이 있는 효과 **11** | **셋** (+디베르 — `s.spcon1`) · **12** | 그 조건도 **버려지지 않고** 옮겨져 있다 (`FaceUpCardPresent` — 옮김의 손실은 §2.3) |
| `test_trigger_condition_separation_audit::test_04` · `test_05` · `test_14` | 사건 코드 20개 (`None` 2) · 조건 있는 카드 10 · 특수 소환하는 효과 **하나** | **21** (`None` **3**) · **11** · **둘** (`93920420:e[1]` · `57835716:e[0]`) · `present` 에 `RESTRICT_SPECIAL_SUMMON` 추가 | 디베르 ① 은 기동이라 `SetCode` 가 없고, 조건은 상태 조건이고, **덱에서** 특수 소환한다 (6-AC 의 하나는 패에서였다). 제한을 거는 일은 소환하는 일이 **아니므로** `users` 에 들지 않는다 |
| `test_unimplemented_rule_semantics_audit::test_03` · `test_13` | `RULE_NOT_IMPLEMENTED` 언급 **125** · `activation` **11** · 그 이름을 내는 조건 **2** | **127** · **12** · **3** | 늘어난 언급 둘은 `engine/duel.py` 의 **보류 사유**다 (고르는 비용 · 토큰의 소환 제한 판정). `UnimplementedRule` **생성** 수와 비율의 모집단은 그대로이고 배수(30)도 낮추지 않았다 |
| `test_post_goal_continuation::test_a05` · `test_a06` | `first_only` 결과에 패스가 있었다 · `continued` 후속 중 목표가 **소재로 쓰이는** 것이 있었다 | 패스는 **깊이 2 예산**의 새 fixture(`flow_baseline`)가, 소재로 쓰이는 후속은 **목표를 스켈레촌으로 둔** 새 fixture(`consumed`)가 잰다 | 기르수 ① 의 해결 중 선택 후보가 2 → 5 로 늘어 `max_results`(상한 5)가 그 변형으로 채워지고, 패스·링크 소환 가지가 그 밖으로 밀렸다. 🔴 **요구는 목표가 무엇이든 같은 요구**이므로, 이 Phase 가 만든 전개(기르수 ① → 디베르 → 디베르 ① → 스켈레촌 → 링크 소환)에서 그 현상이 실제로 일어나는 목표로 옮겼다 (실측: 후속 5건 중 2건이 `goal_kept is False`) |
| `test_post_goal_continuation_boundaries::test_a09` · `test_a09b` | `max_baselines=1` 의 `baselines[0]` 경로에 패스가 있었다 · `max_nodes=30` 에서 상한에 닿은 노드가 열렸다 | `max_baselines=5` 로 올려 **패스를 지나는 기준점을 찾고**, 후속 후보는 **자기 기준점의 경로를 앞에 들고 있다**로 잰다 · `max_nodes=50` | §8.5 의 "기르수 ① 가지의 최초 도달 깊이" 줄이 그 이유다. 🔴 **패스 자리가 없어진 것이 아니다** — 기준점 보관 수가 1 이라 앞의 하나만 남았던 것이고, 기준 HEAD 와 대조해 확인했다 |

### 9.5 돌리지 않은 것

- **전체 테스트 모음은 이번에 돌리지 않았다.** 돌린 것은 §9.1~§9.4 의 범위이고
  (엔진 모음 전체 + 바꾼 시험 파일 전부 + 전개·출력·탐색·어댑터), 그 밖의
  파일은 이번 변경의 위험 범위에 들지 않아 고르지 않았다. 직전 전체 실행의
  수치는 `docs/orcust-multiple-path-resource-comparison.md` §5.4 에 있고,
  **그 수치를 이번 결과로 쓰지 않는다.**
- **실제 Discord 메시지를 보내지 않았다** (요구 §5).
- **금지·제한 데이터로 검증하지 않았다** — 그래서 이 레시피를 "대회 합법 덱"
  이라고 부르지 않는다 (§5.1).
- `tests/agent/test_opponent_resource_weighting_audit.py::test_07` 은 **고치지
  않았다** — 기준 HEAD 에서도 실패하는 선재 결함이고 이 Phase 의 범위가 아니다
  (§8.5 의 마지막 문단에 측정 근거를 적었다).

---

## 10. 후속 보완 — 후보 0장일 때의 제한 등록 (6-AO 후속)

🔴 **§1~§9 는 6-AO 의 기록이고 그대로 둔다.** 이 절은 그 뒤에 고친 것이고,
과거 측정값과 이번 측정값을 섞지 않는다. 기준 HEAD 는
`14cdbd196521bba24e18b852be75c94fcefd8a67` 다.

### 10.1 수정 전 재현과 원인

**재현 순서** (기준 HEAD · 준비된 판):

```
자신 필드   기르수(69811710)
자신 묘지   디베르(57835716)
자신 덱     스켈레촌(21441617) 1장 + 페더맨(21844576) 20장
① 디베르 ① 을 Duel.apply 로 발동시킨다                → 수락
② 비용으로 디베르가 제외된 것을 확인한다               → REMOVED [57835716]
③ 🔴 시험 조작: 덱의 스켈레촌을 묘지로 옮긴다           → 덱의 「오르페골」 0장
④ 정상 체인 해결 경로로 해결한다 (settle_chain)
```

🔴 **③ 은 시험 도구가 손으로 만든 상태 변화다.** 발동과 해결 사이에 덱을
비우는 **등재된 상대 카드가 이 저장소에 없다** — 실제 카드로 이 상황을
만들었다고 주장하지 않는다.

**기준 HEAD 의 실측** (`scratchpad/ao2/repro.py`):

```
MZONE    [69811710]        소환 없음          ← 맞다
REMOVED  [57835716]        비용 유지          ← 맞다
use      1                 사용 기록 유지      ← 맞다
limits   ()                🔴 **제한 누락**    ← 결함
```

**원인.** `c57835716.lua` 의 `s.spop` 는 제어 흐름이 **세 토막**이다.

```lua
if Duel.GetLocationCount(tp,LOCATION_MZONE)<=0 then return end   -- (A)
local g=Duel.SelectMatchingCard(tp,s.filter,tp,LOCATION_DECK,0,1,1,nil,e,tp)
if #g>0 then Duel.SpecialSummon(g,0,tp,tp,false,false,POS_FACEUP) end  -- (B)
local e1=...; Duel.RegisterEffect(e1,tp)                          -- (B 밖)
```

(A) 의 `return` 은 `RegisterEffect` **앞**이므로 효과 전체가 끝난다. (B) 의
`if` 는 **소환만** 감싸고, `RegisterEffect` 는 그 밖이다. 6-AO 는 이 둘을
`ResolutionSkip(when_condition_false=True, when_no_candidate=True)` **하나로**
적었고, `when_no_candidate` 의 처리가 "조작 묶음 전체 생략" 뿐이었으므로 (B)
에서도 제한이 빠졌다.

🔴 **6-AO 가 이 차이를 몰랐던 것은 아니다** — §2.3 · §8.1 에 "제한을 덜 거는
쪽" 이라고 적어 두었다. 틀린 것은 **"지금 등재된 효과로는 그 자리에 닿을 수
없다"** 는 뒤 문장이다. 발동과 해결 사이에 판이 바뀌면 닿는다.

### 10.2 네 갈래를 가른다

| 해결 시점의 사실 | 소환 | 제한 | 비용·사용 기록 | 결과 상태 |
|---|---|---|---|---|
| **빈 칸 없음** (A) | 안 함 | **안 걸림** | 유지 | `RESOLVED_WITHOUT_EFFECT` |
| **합법 후보 0장** (B) | 안 함 | **걸림** | 유지 | `RESOLVED` (조작 2건) |
| **후보 밖 선택** | 안 함 | 안 걸림 | 유지 | `INVALID_TARGET` / `CANDIDATE_NOT_ELIGIBLE` |
| **판정 불명 (UNKNOWN)** | 안 함 | 안 걸림 | 유지 | `UNCHECKED_RULES` / `RULE_NOT_IMPLEMENTED` |

🔴 **아래 둘은 이번 보완에 흡수되지 않는다.** 생략의 근거는 "후보를 **전부
확인**했고 0장이다" 이고, 후보 밖 선택은 그 전제가 거짓(후보가 있었다)이며
UNKNOWN 은 "전부 확인했다" 가 거짓이다. 그 두 갈래는 `_short_selection` 에서
**생략 판정에 닿기 전에** 갈린다 (후보 밖은 `_ask_for_choice` 의 ③ 단계가,
모름은 그 앞의 `unknown` 검사가).

### 10.3 효과 정의와 해결기 변경

**① 정의 쪽 — 선언을 하나 더 만든다** (`engine/effect/definition.py`)

```python
class NoCandidateScope(str, Enum):
    WHOLE_EFFECT = "whole_effect"          # 기본값 — 6-AO 까지의 유일한 동작
    TARGET_OPERATIONS = "target_operations"  # 그 대상을 쓰는 조작만 생략
```

`ResolutionSkip.no_candidate_scope` 로 싣는다. 🔴 **기본값이 전체 생략**이므로
**선언하지 않은 효과는 한 글자도 달라지지 않는다** — 성유물－『성장』 ②
(`93920420:e[1]`) 와 기르수 ③ (`69811710:e[2]`) 가 그렇고, `test_h08` 이 그
사실을 등재표에서 센다. 범위만 적고 `when_no_candidate` 를 적지 않으면
`ValueError` 다. 정규 표현(`canonical_state`)에 범위가 들어간다 — 범위만 다른
두 선언은 **다른 선언**이다.

**② 해결기 쪽 — 생략을 "전부" 에서 "그 대상을 쓰는 일" 로 좁힌다**
(`engine/effect/executor.py`)

| 자리 | 바뀐 것 |
|---|---|
| `_VacantTarget` (새 값) | "고를 후보가 하나도 없었던 대상" 과 그 설명. 🔴 **가짜 선택을 만들지 않는다** — 빈 `Selection` 을 문맥에 넣으면 뒤의 조작이 0장을 소환하려 들고 기록에 고르지 않은 선택이 남는다 |
| `_short_selection` | 범위가 `TARGET_OPERATIONS` 면 `EffectResult` 대신 `_VacantTarget` 을 돌려준다. **UNKNOWN · 후보 밖 갈래는 그 앞에서 그대로 갈린다** |
| `_ask_for_choice` | `(문맥, 비어 있는 대상들)` 을 돌려준다. 비어 있는 대상에는 **선택을 더하지 않는다** |
| `_plan` | `(할 일들, 하지 않은 일의 설명들)` 을 돌려준다. 조작 고리에서 `set(operation.target_refs) & vacant_refs` 인 일만 건너뛰고, 번호는 밀리지 않으며 그 자리에 `NOT_APPLIED` 가 들어간다 — `_check_guards` 의 거짓 갈래와 **같은 처리**다 |
| `execute` | 하지 않은 일의 설명을 결과 문장에 **같이** 적는다. 남은 일이 하나도 없으면 `RESOLVED_WITHOUT_EFFECT` 로 돌려준다 (조작 묶음 전부가 그 대상을 쓰는 효과) |

🔴 **해결기에 카드 ID 가 없다.** 어느 일이 그 대상을 쓰는지는 짐작하지 않고
`Operation.target_refs` 가 답한다 (`test_h09` 가 `engine/effect/executor.py`
전문에 `57835716` 이 없는 것까지 센다).

**③ 등재 쪽** (`engine/effect/library.py`) — 디베르 ① 에
`no_candidate_scope=NoCandidateScope.TARGET_OPERATIONS` 를 적고, 근거 문장과
`provenance` 를 고쳤다 (`RegisterEffect` 가 `if #g>0` **밖**이라는 것이 근거다).

### 10.4 실제 결과 (실측)

**수정 뒤 같은 재현** (`scratchpad/ao2/repro.py`):

```
MZONE    [69811710]                소환 없음
REMOVED  [57835716]                비용 유지
GRAVE    [21441617]                시험이 옮긴 스켈레촌
use      1                         사용 기록 유지
limits   (AttributeOnlyLimit(turn_number=3, player=0, attribute='DARK',
          source_card_id=57835716, ordinal=0, basis='c57835716.lua 의
          s.spop 끝 — …'),)        🔴 **제한 등록**
journal  #0 비용 P0: P0 #42 제외
         #1 57835716:e[0] P0: P0 는 이 턴 DARK 속성 몬스터밖에 특수 소환할
            수 없다 ([57835716]:e[0]), P0 의 DECK 20장을 섞었다
```

**해결 결과 객체** (`scratchpad/ao2/probe_exec.py` — `EffectExecutor.execute`
의 반환값):

```
status   resolved          code  ok
applied  ['RESTRICT_SPECIAL_SUMMON', 'SHUFFLE']
deltas   ['SpecialSummonLimited', 'ZoneShuffled']
reason   57835716:e[0] 를 적용했습니다 (2건). @primary 에 고를 수 있는 후보가
         없습니다 (후보 0장을 전부 확인했습니다, 필요 1장) — 그 대상을 쓰는
         일은 하지 않고 나머지 일은 그대로 수행했습니다. 공식 처리: …
```

🔴 **기록과 실제 변화가 일치한다** — `SPECIAL_SUMMON` 조작이 기록에 없고,
스켈레촌의 개체는 기록이 건드린 카드 목록에 없다 (`test_h01` ⑥). 허위 소환
이벤트를 만들지 않았다.

🔴 **덱 섞기가 일어난다** — 공식 `SelectMatchingCard` 가 덱을 **들여다봤기**
때문이고, 룰북의 "search 뒤에는 섞는다" 가 그 자리다. (A) 갈래에서는
`return` 이 `SelectMatchingCard` **앞**이라 섞기도 없다 — 두 갈래의
비대칭이 **공식 스크립트의 비대칭과 같다.**

### 10.5 기존 정상 전개와 탐색 · 재생 (실측)

🔴 **시작 패 · 레시피 · 탐색 정책을 바꾸지 않았다** (요구 ⑦). §5 의
`ORCUST_HARP_HORROR_HAND` 와 기존 `ORCUST_VERIFICATION_RECIPE` 그대로다.

```
python3 -m app.main combo "69811710,703897,2930675,12989604,61654098" \
  --recipe <검증용 레시피>.ydk --line orcust-harp-horror
→ 종료 코드 0 · real 0m10.111s
→ ✅ 경로를 끝까지 실행했습니다 (4/4단계) · 상태 변경 4걸음
→ 효과의 조작이 수행된 걸음 2 · 엑스트라 몬스터 존 1장 「오르페골 갈라테아」
→ 제외 1장 「오르페골 디베르」 · 보고에 DARK 제한이 그대로 적힌다

python3 -m app.main combo "…" --recipe <…>.ydk --search galatea
→ 종료 코드 0 · real 1m9.236s
→ ✔ 도달 · 행동 4걸음 · 해결 중 선택 2회 · 펼친 노드 28개 · 최대 깊이 3
   · 46.01초
→ 경로 재생 (새 초기 상태에서 다시 실행): ✔ 성공
→ 최종 판 해시 · 재생 최종 해시 둘 다
   e66020d1c942d059bea4d578bfd68c5d6479b6b571ff4b958ad88815da3998d0
```

🔴 **해시가 6-AO (§7) 와 같다.** 정상 경로에는 합법 후보가 있어 이 보완이
닿는 갈래를 지나지 않기 때문이다 — 그것이 "기존 동작을 바꾸지 않았다" 의
실측이다. (노드 수 28 · 깊이 3 도 같고, 초 수만 측정마다 다르다.)

### 10.6 테스트 명령과 결과 (실측)

**① 먼저 "수정 전 실패" 를 확보했다.** 기준 HEAD 를 `git worktree` 로 따로
풀고 (`data/cards.cdb` · `data/constants` 를 붙였다) 새 시험만 돌렸다:

```
timeout 900 python3 -m pytest tests/test_harp_horror_graveyard_effect.py \
  -q -rf -p no:randomly -k "h0"          # 기준 HEAD 14cdbd1 에서
→ 6 failed, 3 passed, 36 deselected in 20.40s
   실패: h01 · h03 · h06 · h07 · h08 · h09
   통과: h02 (빈 칸 없음) · h04 (UNKNOWN) · h05 (후보 밖 선택)
```

🔴 **통과한 셋이 중요하다** — 이미 맞던 경계를 이 보완이 흔들지 않았다는
뜻이고, 수정 뒤에도 그대로 통과한다.

**② 수정 뒤** (모든 수치는 이번 실행의 실측이다):

```
timeout 1200 python3 -m pytest tests/test_harp_horror_graveyard_effect.py \
  -q -rf -p no:randomly
→ 45 passed in 72.70s        (6-AO 의 36건 + 이번 H 절 9건)

timeout 2900 python3 -m pytest tests/engine -q -rf -p no:randomly
→ 3882 passed in 666.39s      (🔴 공용 해결 경로를 바꿨으므로 그 경로의
                               기존 사용자 전체로 범위를 넓혔다)

timeout 600 python3 -m pytest tests/engine/test_cost_payment.py \
  tests/engine/test_partial_outcome.py tests/engine/test_deferred_resolution.py \
  tests/engine/test_autonomous_resolution.py \
  tests/engine/test_multi_target_selection.py -q -rf -p no:randomly
→ 203 passed in 28.77s        (생략 · 부분 결과 · 선택 검증 쪽)

timeout 2900 python3 -m pytest tests/test_orcust_girsu_line.py \
  tests/test_girsu_token_line.py tests/test_girsu_token_chain_integration.py \
  tests/test_combo_output_consistency.py \
  tests/test_withheld_reason_propagation.py \
  tests/test_summon_prohibition_and_resolution_choice.py \
  tests/test_link_material_count_and_rating.py \
  tests/test_resolution_outcome_four_cases.py -q -rf -p no:randomly
→ 169 passed in 342.40s       (성유물－『성장』 · 기르수 · 출력 · 제한 쪽)

timeout 1200 python3 -m pytest tests/test_harp_horror_graveyard_effect.py \
  tests/test_longirsu_link_summon.py tests/engine/test_cost_payment.py \
  -q -rf -p no:randomly
→ 118 passed in 77.10s
```

🔴 **마지막 묶음의 기준 수치는 109 였다** (기준 검토에서 받은 값이고 **이번
결과가 아니다**). 늘어난 9건이 이번 H 절이다 — 기존 109건은 그대로 통과한다.

**③ 고친 낡은 기대값 하나**

| 자리 | 이전 기대 | 바뀐 뒤 | 왜 이전 기대가 맞았는가 |
|---|---|---|---|
| `test_resolution_outcome_four_cases::test_n06` | `ResolutionSkip.canonical_state() == (False, True)` | `== (False, True, "whole_effect")` · 범위를 좁힌 선언의 정규 표현과 `ValueError` 갈래를 **새로 센다** | 그때 선언의 칸이 둘이었다. 범위를 정규 표현에 넣는 이유는 범위만 다른 두 선언이 **다른 선언**이기 때문이고, 기본값이 `whole_effect` 이므로 **적지 않은 선언의 뜻은 달라지지 않았다** |

🔴 **그 밖에 완화한 기대값이 없다.** `tests/engine` 3,882건과 통합 묶음
169건은 **한 줄도 고치지 않고** 통과했다.

### 10.7 남은 한계

- **(B) 갈래는 아직 준비된 판에서만 닿는다.** 발동과 해결 사이에 덱의
  「오르페골」 몬스터를 전부 치우거나 특수 소환을 금지하는 **등재된 상대
  카드가 없다** (상대 방해는 범위 밖이다). `test_h01` · `test_h03` ·
  `test_h06` · `test_h07` 의 상태 변화는 전부 **시험 조작**이고, 각 시험이
  자기 docstring 에 그렇게 적는다.
- **`EFFECT_FLAG_OATH` 깃발 자체**는 여전히 옮기지 못했다 — 조작 **순서**로만
  지킨다 (§2.3).
- **무효화된 바벨을 구별하지 못한다** — 무효화 계층이 없다 (§2.3).
- **`e2` (유발즉시) · `aux.RegisterClientHint`** 는 여전히 미등재 (§8.1).
- **스켈레촌 · 카노네의 ①** 은 여전히 미등재 (§8.2). 🔴 **그 둘의 `s.spop`
  을 이번에 읽었다** (실측 — `c21441617.lua` · `c94046012.lua`): 둘 다
  `RegisterEffect` 가 소환을 감싼 `if` **밖**이다. 카노네는 디베르와 **같은
  모양**이고 (`GetLocationCount(...)<=0 then return` → `SelectMatchingCard`
  → `if #g>0 then SpecialSummon` → `RegisterEffect`, 다만 **패**에서
  고른다), 스켈레촌은 발동 시점에 대상을 잡아 두고
  (`Duel.GetFirstTarget`) `if tc and tc:IsRelateToEffect(e)` 로 감싼다 —
  즉 "대상이 사라졌다" 쪽이고 "후보가 0장" 과는 **다른 질문**이다. 등재할
  때 카노네는 이번 선언을 그대로 쓰고, 스켈레촌은 **그 질문을 적을 자리가
  따로 필요하다** — 이번 보완은 그 자리를 만들지 않았다.
- **범위를 선언한 효과는 디베르 ① 하나뿐이다** (`test_h08` 의 실측). 다른
  효과의 공식 스크립트를 다시 읽지 않았으므로, 그 효과들이 `WHOLE_EFFECT`
  라는 것은 **6-AD 후속2 · 6-AF 에서 읽은 그대로**이고 이번에 다시 확인한
  것이 아니다.
