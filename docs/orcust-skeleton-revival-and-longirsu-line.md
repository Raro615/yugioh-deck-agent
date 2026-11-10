# 오르페골 스켈레촌 묘지 소생 효과와 롱기르수까지의 전개 (Phase 6-AQ)

기준 HEAD: `7d5c45b9062d44d65b606f1d594e622db3ad3923`

이 문서는 「오르페골 스켈레촌」(21441617) ① 을 실제 엔진 행동으로 연결한
결과를 적는다. 과거 측정값은 보존하고 이번 실측과 구분한다.

---

## 1. 기존 지원과 이번에 더한 범위

| | 6-AP 까지 | 6-AQ |
| --- | --- | --- |
| 스켈레촌 ① 발동 | ❌ 등재 없음 (`EFFECT_LIBRARY` 에 없다) | ✅ `21441617:e[0]` |
| 묘지에서 **묘지의** 몬스터 특수 소환 | ❌ 소생 제한을 판정할 수 없어 전부 `UNKNOWN` | ✅ 룰북이 그 질문을 **걸지 않는 카드**를 구분 |
| 대상 지정(`EFFECT_FLAG_CARD_TARGET`) 몬스터 효과 | ❌ 등재 0건 | ✅ 1건 (이것이 첫 등재) |
| 지정한 대상을 해결 시 쓸 수 없을 때 | ❌ 효과 **전체**가 거절됨 | ✅ **그 대상을 쓰는 조작만** 생략, 나머지는 수행 |
| 검증용 고정 경로 | 4건 | **5건** (`orcust-skeleton-longirsu`) |
| 스켈레촌의 `restricts_others=False` 근거 | 「① 이 등재되지 않았다」(등재 범위) | **디베르와 같은 근거**(제한을 적는 계층이 따로 있다) |

🔴 **등재 범위는 그 밖으로 넓어지지 않았다.** 카노네 ① · 갈라테아 · 갈라테아i ·
롱기르수의 효과, 바벨의 유발즉시 처리는 **여전히 미지원**이다 (§8).

---

## 2. 카드 계약 — `c21441617.lua` 를 한 줄씩

공식 한국어 텍스트 (`data/ko/ko-KR.json` 21441617):

> 이 카드명의 효과는 1턴에 1번밖에 사용할 수 없다.
> ①: 묘지의 이 카드를 제외하고, "오르페골 스켈레촌" 이외의 자신 묘지의
> "오르페골" 몬스터 1장을 대상으로 하여 발동할 수 있다. 그 몬스터를 특수
> 소환한다. 이 효과의 발동 후, 턴 종료시까지 자신은 어둠 속성 몬스터밖에
> 특수 소환할 수 없다.

### 2.1 발동 위치 · 종류 · 타이밍

| Lua | 옮긴 자리 |
| --- | --- |
| `e1:SetType(EFFECT_TYPE_IGNITION)` | `activation_kind=IGNITION` |
| `e1:SetRange(LOCATION_GRAVE)` | `activation_zones={GRAVE}` |
| `e1:SetProperty(EFFECT_FLAG_CARD_TARGET)` | `TargetRequirement.TARGETING` |
| `e2` = `e1:Clone()` + `EFFECT_TYPE_QUICK_O` + `s.spcon2` | ❌ **옮기지 않았다** |

`e2` 는 **바벨이 적용되고 있을 때** 쓰이는 유발즉시 효과다. 룰북이 유발즉시의
발동 시점을 적지 않으므로 (`ACTIVATION_KINDS_IN_SCOPE` · ADR-006) 이 저장소는
그 분류를 허가하지 않는다 — 디베르와 **같은 경계**이고, 그래서 **바벨이 깔린
판에서 스켈레촌 ① 도 발동되지 않는다** (`s.spcon1` 이 거짓, `e2` 는 미지원).

### 2.2 자신 제외 비용과 지불 시점

`e1:SetCost(Cost.SelfBanish)` → `CostGroup((SelfCardCost.banish({GRAVE}),))`.

🔴 **비용은 발동 시점에 치러진다.** 실측 (`test_c01`): 발동이 수락된 직후
`REMOVED == [21441617]` 이고, 해결은 아직 일어나지 않았다. 그래서 해결이
불발해도 **제외는 되돌아오지 않는다** (`test_d01` · `test_d04` 가 센다).

### 2.3 발동 시 지정하는 대상의 조건

```lua
s.spfilter(c,e,tp) = c:IsSetCard(SET_ORCUST)
    and c:IsCanBeSpecialSummoned(e,0,tp,false,false)
    and not c:IsCode(id)
s.sptg: chkc → chkc:IsControler(tp) and chkc:IsLocation(LOCATION_GRAVE)
               and s.spfilter(chkc,e,tp)
```

| Lua | 옮긴 자리 |
| --- | --- |
| `chkc:IsControler(tp)` | `owner=PlayerRef.CONTROLLER` |
| `chkc:IsLocation(LOCATION_GRAVE)` | `zones={Zone.GRAVE}` |
| `IsSetCard(SET_ORCUST)` | `compile_archetype_condition(("SET_ORCUST",))` — 숫자를 손으로 적지 않았다 |
| `not c:IsCode(id)` | `Not(CardIdIs(CYMBAL_SKELETON))` — **카드명 기준**이므로 묘지의 다른 사본도 함께 빠진다 |
| `IsCanBeSpecialSummoned` | 관문 (`MAY_BE_SPECIAL_SUMMONED` + 소생 제한) |
| `SelectTarget(...,e:GetHandler(),...)` | `exclude_source=True` |
| `SelectTarget(...,1,1,...)` | `minimum=maximum=1` |
| 공식 텍스트의 「"오르페골" **몬스터**」 | `IsMonster()` (Lua 는 `IsCanBeSpecialSummoned` 가 함의하고, 그 술어는 관문이 들고 갔다) |

### 2.4 대상의 특수 소환 가능 여부와 소생 제한

🔴 **이 절이 이번 Phase 의 가장 큰 발견이다.**

6-AC~6-AO 동안 이 저장소는 소생 제한을 **출발 자리**로만 판정했다 —
`REVIVAL_LIMIT_FREE_ZONES = {HAND, DECK}` 밖이면 "소환 이력을 적지 않으므로
모른다"(`SUMMON_HISTORY_RULE`). 그래서 **묘지에서의 특수 소환은 전부
`UNCHECKED_RULES`** 였다. 6-AQ 시작 시점의 실측:

```
체인1 P0 21441617:e[0] 대상 @primary=[#41] 를 해결하지 못했습니다:
#41 가 GRAVE 에 있습니다. 그 자리에서 나오는 특수 소환은 소생 제한을 묻고,
이 엔진은 소환 이력을 적지 않습니다 (special-summon-history …)
```

🔴 **그 자리를 완화하지 않았다.** 대신 룰북이 그 질문을 **누구에게 거는가**를
읽었다 (`data/rules/documents/sd-rulebook-en-v10.json`, `RULE-SUMMON-014`):

> Monsters can also be Special Summoned onto the field through the effect of
> another card. **This is different from "Special Summon Monsters."** You
> cannot use a card effect to Special Summon **those monsters** from your
> hand, Deck, or the Graveyard unless it was properly Special Summoned first.
> For example, if a Synchro Monster is sent from your Extra Deck to the
> Graveyard without being Synchro Summoned, you cannot use a Spell Card to
> Special Summon it from the Graveyard, **because Synchro Monsters have to be
> properly Special Summoned first**, before they can be Special Summoned by
> another card's effect.

"those monsters" 가 가리키는 것은 바로 앞 문장의 「"Special Summon
Monsters"」 이고, 예시가 가리키는 것은 **엑스트라 덱 몬스터**다. 즉 소생
제한은 "묘지에 있는 모든 몬스터" 의 문제가 **아니다**.

그래서 `engine.effect.ruling.revival_limit_applies(definition)` 를 더했다 —
세 값짜리 판정이다.

| 답 | 조건 | 실측 (몬스터 9,224장) |
| --- | --- | --- |
| `TRUE` (제한이 걸린다) | `is_extra_deck` | 2,157 |
| `TRUE` | `type_names` 에 `SPSUMMON` · `RITUAL` | 492 |
| `FALSE` (**질문이 생기지 않는다**) | 메인 덱 · 위 비트 없음 · `normal_summon_restriction_signals == ()` | 5,460 |
| `UNKNOWN` | 스크립트가 없다 (`None`) | 958 |
| `UNKNOWN` | 조건부 제약 상수를 찾았다 (누구에게 걸리는지 이 신호가 말하지 않는다) | 157 |

🔴 **왜 `SPSUMMON` 비트인가.** 이 저장소는 이미 그것을 읽고 있다 —
`engine.summon_rules.NEVER_NORMAL_SUMMONABLE` 이 `{"RITUAL","TOKEN",
"SPSUMMON"}` 이고, 그 근거가 Phase 6-C 의 전수 측정이다 (「(이 카드는) 일반
소환할 수 없다」 를 EDOPro 는 스크립트가 아니라 `TYPE_SPSUMMON` 비트로 적고,
344장 중 338장의 공식 한국어 원문이 그 문장을 직접 말한다).

🔴 **완화가 아닌 이유 셋.**

1. `FALSE` 는 **읽어서** 답한 것이다 — 읽지 못한 1,115장은 그대로 `UNKNOWN`.
2. 그 뒤의 두 걸음(등재된 `MAY_BE_SPECIAL_SUMMONED` · 판의 간섭 `_interference`)
   은 한 글자도 달라지지 않았다. "소생 제한이 없다" 가 "특수 소환해도 된다" 로
   바뀌지 않는다.
3. 「죽은 자의 소생」(83764718)은 **여전히 `executable=False`** 다
   (`test_j_exactly_one_real_card_special_summons` 가 센다). 달라진 것은 소생
   제한 판정 **한 자리**이고 등재 범위가 아니다.

🔴 **좁히지 않은 쪽을 적어 둔다.** 룰북 문장은 그 제한을 "hand, Deck, or the
Graveyard" 전부에 건다. 즉 `REVIVAL_LIMIT_FREE_ZONES = {HAND, DECK}` 는
**특수 소환 몬스터 · 엑스트라 덱 몬스터에 대해서는 지금도 너무 느슨하다** —
그쪽을 조이는 것은 이번 범위에서 하지 않았다 (§8 의 남은 과제). 이번에 바꾼
것은 "질문이 생기지 않는 카드" 를 구분한 한 방향뿐이다.

### 2.5 해결 시 대상과 효과의 관계 재확인

```lua
function s.spop(e,tp,eg,ep,ev,re,r,rp)
    local tc=Duel.GetFirstTarget()
    if tc and tc:IsRelateToEffect(e) then
        Duel.SpecialSummon(tc,0,tp,tp,false,false,POS_FACEUP)
    end
    local e1=Effect.CreateEffect(e:GetHandler())   -- ← if 밖이다
    ...
    Duel.RegisterEffect(e1,tp)
end
```

**두 가지**를 읽었다.

1. `if tc and tc:IsRelateToEffect(e)` — 지정한 그 한 장이 효과와의 관계를
   잃으면 **소환을 시도하지 않는다.**
2. `Duel.SpecialSummon` 의 **반환값을 보지 않는다** — 빈 칸이 없거나 그 소환이
   금지되어 0장이 소환되어도 그 뒤가 그대로 실행된다.

둘 다 "효과가 불발했다" 가 아니다. 그래서 새로 더한 최소 기능이
`ResolutionSkip.when_target_unusable` 하나다 (§3).

### 2.6 빈 몬스터 존과 해결 시 소환 가능 여부

```lua
if chk==0 then return Duel.GetLocationCount(tp,LOCATION_MZONE)>0
    and Duel.IsExistingTarget(s.spfilter,tp,LOCATION_GRAVE,0,1,e:GetHandler(),e,tp) end
```

빈 칸 검사는 **발동 조건**에만 있다 →
`activation=And((ZoneHasFreeSlot(CONTROLLER, MZONE), SpecialSummonPermitted(), Not(FaceUpCardPresent(…BABEL))))`.

🔴 **`s.spop` 에는 그 검사가 없다.** 디베르의 같은 함수 첫 줄에 있는
`if Duel.GetLocationCount(tp,LOCATION_MZONE)<=0 then return end` 가 **이
함수에는 존재하지 않는다** (`c21441617.lua` 44–58행 전문을 읽었다). 그래서
`resolution_condition=And(())` — **빈 조건**을 명시했다.

🔴 **`None` 으로 둘 수 없었다.** `None` 은 "적지 않았다" 이고, 그때 실행기는
`activation` **전체**를 해결 시점에 다시 본다 (6-AF 가 세운 규약). 그대로
두면 해결 전에 칸이 차거나 특수 소환이 금지되었을 때 조작 묶음이 통째로 멈추고
**어둠 속성 제한까지 빠진다** — 실측으로 그 결함을 먼저 보았다:

```
(resolution_condition 을 적기 전)
B3 해결: … 해결하지 못했습니다: 발동 조건이 거짓입니다 …   limits ()
B4 해결: … 해결하지 못했습니다: 발동 조건이 거짓입니다 …   limits ()
```

### 2.7 카드명 기준 사용 제한

`e1:SetCountLimit(1,id)` → `UseLimit(LimitScope.PER_CARD_NAME)`.
실측 (`test_c02`): 묘지에 스켈레촌이 두 장 있어도 한 번 쓰면 두 번째 사본의
후보가 사라진다.

### 2.8 이후 어둠 속성 제한과 지속 기간

```lua
e1:SetType(EFFECT_TYPE_FIELD); e1:SetCode(EFFECT_CANNOT_SPECIAL_SUMMON)
e1:SetProperty(EFFECT_FLAG_PLAYER_TARGET+EFFECT_FLAG_OATH)
e1:SetTargetRange(1,0); e1:SetTarget(s.splimit)
e1:SetReset(RESET_PHASE|PHASE_END)
s.splimit = not c:IsAttribute(ATTRIBUTE_DARK)
```

→ `RestrictSpecialSummonOperation(attribute="DARK", who=CONTROLLER)`, 조작
묶음의 **두 번째**다 (`EFFECT_FLAG_OATH` 를 순서로 지킨다).
`engine.state.summon_limit.AttributeOnlyLimit` 가 턴 번호를 키에 넣으므로
`RESET_PHASE|PHASE_END` 는 그 키로 지켜진다.

### 2.9 바벨 적용 시와 현재 미지원 범위

`s.spcon1 = not Duel.IsPlayerAffectedByEffect(tp,CARD_ORCUSTRATED_BABEL)` →
`Not(FaceUpCardPresent(CONTROLLER, {FZONE}, ORCUSTRATED_BABEL))`.

🔴 **무효화된 바벨을 구별하지 못한다** — 지속 효과가 플레이어에게 걸려 있는가를
적는 계층이 없어 "바벨이 앞면으로 필드에 있는가" 로 옮겼다 (STRUCTURAL-76).
그리고 바벨이 있을 때 쓰이는 `e2` 는 미지원이므로, **바벨이 깔린 판에서
스켈레촌은 어느 쪽으로도 발동되지 않는다.** 그것이 지금의 정직한 범위다.

### 2.10 디베르와 스켈레촌의 차이 (요약)

| | 디베르 ① (6-AO) | 스켈레촌 ① (6-AQ) |
| --- | --- | --- |
| `EFFECT_FLAG_CARD_TARGET` | 없음 | **있음** |
| 고르는 시점 | **해결 중** (`SelectMatchingCard`) → `chosen_at_resolution=True` | **발동 시** (`SelectTarget`) → `TARGETING` |
| 출발 자리 | 덱 | **묘지** |
| `s.spop` 의 조건 재검사 | 빈 칸 하나 (`GetLocationCount<=0 then return`) | **없음** → `resolution_condition=And(())` |
| 생략 선언 | `when_condition_false` + `when_no_candidate` (범위 `TARGET_OPERATIONS`) | `when_target_unusable` 하나 |
| 빈 칸이 해결 전에 사라지면 | **제한도 걸리지 않는다** (`return` 이 `RegisterEffect` 앞) | **제한은 걸린다** (`SpecialSummon` 의 반환값을 보지 않는다) |

🔴 **디베르의 보완을 복사하지 않았다.** 두 카드의 `s.spop` 제어 흐름이 실제로
다르고, 그 차이가 그대로 두 선언의 차이가 되었다. `test_a04` 가 둘을 한자리에서
센다.

---

## 3. 새로 더한 최소 기능 — `when_target_unusable`

### 3.1 선언

`engine/effect/definition.py` 의 `ResolutionSkip` 에 칸 하나를 더했다.

```python
when_target_unusable: bool = False
```

뜻: **발동 시점에 지정해 둔 대상을 해결 시점에 쓸 수 없으면 그 대상을 쓰는
조작만 생략하고 나머지는 수행한다.**

* `when_no_candidate` 와 **다른 축**이다. 그쪽은 "해결 중에 고를 후보가
  없었다"(고르기 효과 · `SelectMatchingCard`), 이쪽은 "**발동 시점에 이미
  지정해 둔** 그 한 장을 지금은 쓸 수 없다"(대상 지정 효과 · `SelectTarget`).
* **범위는 고정이다** — `no_candidate_scope` 처럼 고르지 않는다. 읽어 온 모양
  자체가 "그 대상을 쓰는 `if` 안쪽만 건너뛴다" 이다.
* **대상 지정 효과에만 적을 수 있다.** `EffectDefinition._check_resolution_skip`
  이 `TargetRequirement.TARGETING` 선언이 없는 정의를 만들 때 거절한다
  (`test_e01`).
* `canonical_state()` 가 네 값이 되었다 — 선언한 효과와 안 한 효과가 같은
  것으로 읽히지 않는다.

### 3.2 실행기

`engine/effect/executor.py`:

* `UNUSABLE_TARGET_CODES = frozenset({ValidationCode.CANDIDATE_NOT_ELIGIBLE})`
* `_unusable_target_note(definition, index, operation, failure)` — 네 가지가
  **동시에** 참일 때만 생략으로 바꾼다.
  1. 정의가 `when_target_unusable` 을 **선언했다**.
  2. 거절이 `ResolutionStatus.INVALID_TARGET` 이다.
  3. 거절 코드가 `UNUSABLE_TARGET_CODES` 에 있다.
  4. 그 조작이 **대상 지정된 이름**을 쓴다 (`Operation.target_refs`).
* `_plan` 의 조작 고리가 그 생략을 **6-AO 후속이 만든 같은 기계**로 처리한다 —
  `OperationResult(index, NOT_APPLIED)` 를 그 자리에 넣고 설명을 모아
  결과 문장에 싣는다.

🔴 **좁게 삼킨다.** 삼키지 않는 것들:

| 거절 | 왜 삼키지 않는가 |
| --- | --- |
| `too_few_selected` · `too_many_selected` · `duplicate_selection` · `target_count_mismatch` | 대상 **선언 자체**가 어긋났다는 뜻이고, 부르는 쪽의 잘못이다 |
| `UNCHECKED_TARGET` (`hidden_card` · `information_unavailable`) | **모름**이다. 판정하지 못한 것을 생략으로 바꾸면 그 결정을 엔진이 지어낸 것이 된다 |
| `UNCHECKED_RULES` (`rule_not_implemented`) | 같은 이유 — 소생 제한을 판정할 수 없는 대상이 여기 걸린다 (`test_b02`) |
| `INVALID_CONTEXT` · `EXECUTION_ERROR` | 생략의 축이 아니다 |

🔴 **해결기에 스켈레촌 카드 ID 가 없다** (`test_e03` 이 파일 전문을 센다).
어느 조작이 그 대상을 쓰는지는 `Operation.target_refs` 가 답하고, 생략 여부는
정의가 선언한다.

🔴 **일괄 완화가 아니다.** 이 선언을 적은 효과가 스켈레촌 ① **하나**이고
(`test_e05`), 나머지 21건의 정의는 한 글자도 달라지지 않았다.
그리고 탐색기는 이 경로의 이름도 카드 ID 도 모른다 (`test_e04`).

### 3.3 되돌리지 않는 것

비용(발동 경로의 `CostPayer`)과 사용 기록(`state.uses`)은 해결이 일부
불발했다는 사실로 되돌리지 않는다 — 공식 스크립트가 하지 않는 일이다.
`test_d01` 이 `REMOVED == [21441617]` 과 `uses.count(...) == 1` 을 함께 센다.
그리고 소환하지 않은 상황에 **허위 소환 이벤트를 남기지 않는다** — 그 조작은
`NOT_APPLIED` 로 기록되고 `applied` 에 들어가지 않는다.

---

## 4. 해결 시점의 다섯 갈래 — 실측

준비된 판(묘지에 스켈레촌 + 기르수, 몬스터 존 비어 있음)에서 발동한 뒤
**시험이 손으로** 상황을 바꾸고 해결했다. 🔴 **실제 등재된 상대 카드로 이
상황을 만들었다고 주장하지 않는다** (파키세팔로만 실제 카드다).

| # | 발동 후 바꾼 것 | 소환 | 어둠 제한 | 비용 | 공식 처리와 같은가 |
| --- | --- | --- | --- | --- | --- |
| D1 | 대상을 묘지 → 패로 | ❌ | ✅ 걸림 | 유지 | ✅ (`IsRelateToEffect` 거짓) |
| D2 | 몬스터 존 5칸을 채움 | ❌ | ✅ 걸림 | 유지 | ✅ (`SpecialSummon` 이 0장) |
| D3 | 상대 필드에 파키세팔로 | ❌ | ✅ 걸림 | 유지 | ✅ (같은 이유) |
| D4 | 대상을 묘지 → **덱**으로 | ❌ | ❌ **걸리지 않음** | 유지 | 🔴 **다르다** — 아래 |
| D5 | 대상을 패로 보냈다가 **다시 묘지로** | ✅ 소환된다 | ✅ | 유지 | 🔴 **다르다** — 아래 |

그리고 대상 자체가 부적격한 두 갈래:

| # | 상황 | 결과 |
| --- | --- | --- |
| B2 | 묘지의 **갈라테아**(엑스트라 덱)를 대상으로 지정 | 발동은 수락되지만 해결이 `UNCHECKED_RULES` — **소환도 제한도 없다** |
| C5 | 부적격 카드를 대상으로 / 대상 없이 발동 선언 | **발동 자체가 `INVALID`**, 판은 한 글자도 바뀌지 않는다 (비용도 치러지지 않는다) |

> 🔴 **정정 안내 (Phase 6-AQ 후속).** 위 표의 **D4 · D5 두 줄은 6-AQ 시점의
> 실측**이고, 그 뒤 후속 보완이 둘을 고쳤다 — 지금은 **둘 다 소환만 생략하고
> 어둠 속성 제한을 건다**. 과거 기록을 지우지 않고 그대로 둔다 (그때 그것이
> 사실이었다). 바뀐 뒤의 실측은 **§10** 에 있다.

### 4.1 D4 — 모름은 생략이 아니다

대상이 **관측되지 않는 자리**(덱)로 가면 `TargetResolver` 가 `HIDDEN_CARD` →
`UNCHECKED_TARGET` 을 돌려주고, 효과 전체가 거절된다.

```
… 해결하지 못했습니다: @primary 의 대상이 적법한지 판정할 수 없습니다:
관측에 보이지 않습니다. 이 듀얼에 없는지 가려진 곳에 있는지 구분할 수 없습니다.
limits []
```

공식 처리는 그때도 `IsRelateToEffect` 가 거짓이므로 소환만 건너뛰고 제한을
걸 것이다. 🔴 **이 차이를 숨기지 않는다** — 판정하지 못한 것을 생략으로 바꾸면
그 결정을 엔진이 지어낸 것이 되므로 (ADR-006), 이 저장소는 거절을 고른다.
`test_d04` 가 그 차이를 고정한다.

> 🔴 **정정 (Phase 6-AQ 후속) — 고쳤다.** 위 문단은 **6-AQ 시점의 사실**이고
> 그때 틀린 것이 아니다. 그때 이 저장소에는 "발동 때 지정한 관계" 를 적는
> 자리가 없었으므로, 남은 길은 *현재* 대상을 다시 관측해 후보 조건을 묻는
> 것뿐이었고 덱은 가려져 있으니 `UNCHECKED_TARGET` 이 맞았다.
>
> 후속 보완이 그 자리를 만들었다 (`engine/state/target_relation.py`). 이제
> 해결기는 **관측을 묻기 전에 판에 적힌 관계 기록을 먼저 묻는다** — "그 개체가
> 그 뒤 존을 떠났는가" 는 가려진 카드를 열지 않고 알 수 있는 사실이고, 그
> 답이 "떠났다" 면 **확정**이므로 모름이 아니다. 결과: **소환만 생략하고 어둠
> 속성 제한을 건다** (§10.1 · §10.3 의 실측).
>
> `test_d04` 는 **올바른 동작을 요구하는 회귀 시험**으로 바뀌었다 —
> `test_d04_a_target_moved_to_a_concealed_zone_skips_only_the_summon`.

### 4.2 D5 — STRUCTURAL-50 은 그대로다

지정한 뒤 그 카드가 자리를 떠났다 **돌아오면** 공식 처리는
`IsRelateToEffect` 가 거짓이므로 소환하지 않는다. 이 저장소에는 그 관계를
적는 계층이 없고 `InstanceId` 는 자리를 옮겨도 그대로이므로
(`engine/ids.py` — "한 번 쓴 번호는 재사용하지 않는다") **같은 개체로 읽어
소환한다.**

🔴 **6-AQ 가 옮긴 것은 그 `if` 가 거짓일 때 *무엇이 생략되는가*(소환만, 제한은
그대로)이고, 그 `if` 를 판정하는 계층이 아니다.** STRUCTURAL-50 은 이미 다섯
개의 등재 효과와 네 개의 문서가 이름으로 들고 있는 구조적 미지원이고
(싸이크론 · 강제 탈출 장치 · 육신보살 · 로스트 · 어니스트), 이 Phase 에서
그것을 만들지 않았다 — 만들면 대상 지정 효과 전부의 관계 모델을 새로
세우는 일이 되고, 그것은 §7 의 범위 밖이다. `test_d05` 가 현재 동작을
**측정**해 고정한다.

> 🔴 **정정 (Phase 6-AQ 후속) — 이 한 갈래는 고쳤다.** 위 문단도 **6-AQ 시점의
> 사실**이다. 후속 보완이 `InstanceId`(개체의 영구 번호) 와 **그 효과가 발동
> 때 지정했던 관계**를 분리했고, 존 종류가 바뀌는 이동에서 관계를 끊는다.
> 이제 떠났다 **돌아온** 대상은 `InstanceId` 가 같아도 **소생하지 않고**,
> 어둠 속성 제한만 걸린다 (§10.1 의 실측).
>
> 🔴 **STRUCTURAL-50 전체를 해결한 것이 아니다 — 부분 해결이다.** 옮긴 것은
> "지정한 뒤 그 카드가 존을 떠났는가" 하나이고, 체인 무효화 · 효과 무효화 ·
> 같은 체인 안의 다른 효과가 만드는 관계는 여전히 없다. §10.8 이 남은
> 사례를 이름으로 적는다.
>
> `test_d05` 도 **올바른 동작을 요구하는 회귀 시험**으로 바뀌었다 —
> `test_d05_a_target_that_left_and_came_back_is_not_summoned`.

---

## 5. 시작 패부터의 실제 경로 (B 계층)

### 5.1 입력

```
hand:   69811710,703897,2930675,12989604,61654098
recipe: 69811710 x3, 93920420 x3, 57835716 x3, 21441617 x3, 94046012 x3,
        40441990 x3, 2930675 x3, 90351981 x3, 26845680 x3, 61654098 x3,
        703897 x3, 12989604 x3, 55051920 x2, 47171541 x2,
        extra: 30741503 x1, 48835607 x1, 76145142 x1, 93854893 x1,
               74820316 x1, 3134857 x1
line:   orcust-skeleton-longirsu
```

🔴 **기존 디베르 검증용 패와 레시피를 그대로 썼다** — 새 패를 만들지 않았다.
🔴 **시작 이후의 상태를 손으로 조작하지 않았다**: `build_opening` 에 패와
레시피만 주고 `execute_opening` 이 엔진 후보에서 여섯 걸음을 골랐다.

### 5.2 여섯 걸음 (실측)

```
 0 normal_summon    accepted=True  normal_summon 를 적용했습니다 (1건).
 1 activate_effect  accepted=True  체인1 P0 69811710:e[0] 를 해결했습니다.
 2 activate_effect  accepted=True  체인1 P0 57835716:e[0] 를 해결했습니다.
 3 link_summon      accepted=True  link_summon 를 적용했습니다 (3건).
 4 activate_effect  accepted=True  체인1 P0 21441617:e[0] 대상 @primary=[#75] 를 해결했습니다.
 5 link_summon      accepted=True  link_summon 를 적용했습니다 (3건).

✅ 경로를 끝까지 실행했습니다 (6/6단계)
```

### 5.3 최종 자원 (실측)

```
MZONE    []
EMZONE   [76145142]            ← 오르페골 롱기르수
GRAVE    [30741503, 69811710]  ← 소재가 된 갈라테아 · 기르수
REMOVED  [57835716, 21441617]  ← 비용으로 제외된 디베르 · 스켈레촌
HAND     [703897, 2930675, 12989604, 61654098]
DECK     33장
EXTRA    [3134857, 48835607, 74820316, 93854893]
limits:  [('DARK', 21441617), ('DARK', 57835716)]
```

🔴 **어둠 속성 제한이 두 번 걸렸고 두 링크 소환이 그것을 지났다** — 갈라테아와
롱기르수 모두 `attribute=DARK` 다 (`data/cards.cdb` 로 대조했다).

### 5.4 갈라테아 · 롱기르수의 소재 조건이 실제로 판정되었다

(걸음 번호는 §5.2 의 로그 번호다 — 0부터 센다.)

* 걸음 3(갈라테아): 기르수 + 스켈레촌 — 둘 다 효과 몬스터이고 setcode `0x11b`
  를 가진다. 장수 2 · 링크 수치 합 2.
* 걸음 5(롱기르수): **이미 엑스트라 몬스터 존에 있는** 갈라테아(링크 2) +
  소생한 기르수(레벨 4, 수치 1) — 장수 2, **링크 수치 합 3** 이고 롱기르수의
  링크 수와 같다 (Phase 6-AG 가 장수와 수치 합을 분리 판정한다). 소재가 된
  갈라테아가 엑스트라 몬스터 존을 비우고 롱기르수가 그 자리에 놓인다
  (Phase 6-AN 의 소환 위치 판정 — `EMZONE == [76145142]` 이 그것을 보인다).

### 5.5 소생한 기르수의 유발 효과

🔴 **다시 발동되지 않고, 발동되어서는 안 되는 쪽도 발동되지 않는다.**

`c69811710.lua` 는 소환 유발을 `e1`(`EVENT_SUMMON_SUCCESS`) 과
`e2`(`EVENT_SPSUMMON_SUCCESS`) **두 효과로** 적는데, 이 저장소는 `e[0]` 과
`e[2]`(토큰) 만 등재했다. 그래서:

* 특수 소환 쪽 유발(`e[1]`)은 **미지원**이다 — 이번 범위에서 임의로 더하지
  않았다. 실제 카드는 소생된 기르수로 ① 을 쓸 수 있고(턴 1회 제한 안에서),
  이 저장소는 그것을 하지 못한다.
* 일반 소환 쪽 유발(`e[0]`)이 **잘못 다시 발동되지도 않는다** — 그쪽은
  `EVENT_SUMMON_SUCCESS` 이고 사용 제한이 카드명 기준이다. `test_g02` 가
  소생 직후 `69811710:e[0]` 후보가 0건임을 센다.

---

## 6. 고정 경로 · 일반 탐색 · 재생

### 6.1 고정 경로 (`--line orcust-skeleton-longirsu`)

✅ **6/6 단계 완료.** §5 가 실측을 적었다. 🔴 **탐색기와 다른 질문이다** —
사람이 적어 둔 여섯 걸음을 그대로 밟는다.

### 6.2 일반 탐색 — `search:galatea` (목표 30741503)

🔴 **탐색기에 정답 수순을 하드코딩하지 않았다.** 목표 판정은 `FieldGoal`
하나이고 후보는 엔진이 허가한 것뿐이다. 그런데 **탐색이 스스로 스켈레촌 ① 을
쓴다** — 그것이 "등재가 탐색 경로까지 닿았는가" 의 답이다.

입력은 §5.1 과 같고 (`search: galatea`), 예산은 기본값
(`SearchBudget(max_depth=8, max_nodes=300, max_seconds=300.0,
max_choice_branches=8)`) 이다. 실측:

```
reached: True | termination: GOAL_REACHED
nodes: 34  deepest: 5  elapsed: 76.4s  budget_hit: ()
goal_reason: [30741503] 가 자신 필드에 있고 판이 정리되었습니다.

1 normal_summon    기르수 일반 소환
2 activate_effect  69811710:e[0]  — 선택 후보 9장 중 → 21441617 (기준점이 집었다)
3 activate_effect  69811710:e[2]  — 성유물 토큰 2장
4 link_summon      소재 (기르수) 1장 → 갈라테아i
5 activate_effect  21441617:e[0]  대상 @primary=[#75] → 묘지의 기르수를 소생
6 link_summon      소재 (갈라테아i, 기르수) → 갈라테아

final_field: (('MZONE', 46647145, True), ('EMZONE', 30741503, True))
final_hash:  44e3cbe8e28e4e1dd459c731afcec19606aa7ef7358a4579a722990edda2c6bd
```

**재생** — 같은 입력으로 `build_opening` 을 **다시** 불러 만든 새 초기
상태에서 여섯 걸음을 다시 밟았다:

```
rerun.ok: True   goal_reached: True   matches_search: True
재생 성공 — 걸음 6 · 목표 True · 탐색 결과와 일치 True
```

🔴 그 재생이 **이번 Phase 의 일을 전부 지난다** — 비용 지불(스켈레촌 자기
제외) · **발동 시점의 대상 지정**(`@primary=[#75]`) · 묘지에서의 소생 ·
어둠 속성 제한 · 링크 소재 포함.

🔴 **6-AP 의 측정값과 다르다 — 그때 틀렸던 것이 아니다.** 6-AP 는 같은
목표에서 노드 28개 · 197.899초 · 최종 해시
`e66020d1c942d059bea4d578bfd68c5d6479b6b571ff4b958ad88815da3998d0` 를 적었고,
그 경로는 기르수 → 디베르 → 스켈레촌 → 갈라테아였다. 6-AQ 가 스켈레촌 ① 을
등재하면서 **그 전까지 없던 합법 후보**가 생겼고, 탐색이 더 얕은 깊이(5)에서
다른 경로로 목표에 닿는다. 🔴 **이전 수치와 같게 만들려고 합법 후보를
제거하지 않았다.**

### 6.3 일반 탐색 — `search:longirsu` (목표 76145142) · 🔴 **찾지 못했다**

같은 입력 · 같은 기본 예산으로 목표만 롱기르수로 바꾼 실측:

```
reached: False | termination: BUDGET_EXCEEDED
budget_hit: ('max_depth=8', 'max_seconds=300')
nodes: 173  deepest: 8  elapsed: 301.8s
goal_reason: [76145142] 가 자신 필드에 없습니다.
final_field: ()   (목표에 닿지 못해 비어 있다)
```

🔴 **직접 실행 성공과 구분해서 적는다.** §5 의 고정 경로는 **엔진에서 여섯
걸음이 전부 수행되었고** (`--line orcust-skeleton-longirsu`), 일반 탐색은
**기본 예산 안에서 그 경로를 찾지 못했다.** 둘은 다른 사실이다 — 앞쪽은 "그
전개가 이 엔진에서 적법하고 실행된다", 뒤쪽은 "탐색기가 그것을 스스로
찾아내지 못한다" 다.

🔴 **예산을 무제한으로 늘리거나 후보를 제거하지 않았다.** 깊이 8 과 300초를
둘 다 소진했고 (173노드), 그것을 늘려 "찾았다" 로 바꾸지 않았다. 왜 어려운지는
적어 둔다 — 목표 경로가 여섯 걸음인데 각 걸음마다 세트 · 다른 링크 소환 ·
다른 효과 발동이 함께 후보이고, 해결 중 선택 분기도 함께 펼쳐진다
(`max_choice_branches=8`). 이것은 **탐색 알고리즘의 과제**이고, 이번
Phase 의 범위 밖으로 적혀 있었다 ("탐색 알고리즘 전면 개편") — 손대지 않았다.

### 6.4 재현 가능성 — 고정 경로를 두 번 돌렸다

`tests/test_skeleton_revival_and_longirsu.py::test_g03` 이 같은 입력으로
`build_opening` 을 **두 번** 불러 각각 여섯 걸음을 돌리고, 두 판의 **상태
해시 · 제한의 정규 표현 · 다섯 자리의 카드 목록**이 같음을 센다.


---

## 7. 테스트 명령과 실측 결과

🔴 **묶음마다 따로 돌렸다.** 한 번에 다 돌리는 것도 해 봤지만 배경 실행의
시간 한도(30분)에 걸려 **중단되었고 한 줄도 내지 못했다** — 그래서 그 결과를
적지 않고, 아래의 끝까지 돌아간 묶음들을 적는다.

```
# ① 공통 계층 + 이번 Phase 의 세 파일
timeout 1800 python3 -m pytest tests/engine \
    tests/test_skeleton_revival_and_longirsu.py \
    tests/test_harp_horror_graveyard_effect.py \
    tests/test_token_and_galateai_summon_gates.py -q -rf -p no:randomly

# ② 고정 경로 · /combo 출력
timeout 1800 python3 -m pytest tests/test_orcust_girsu_line.py \
    tests/test_girsu_token_line.py tests/test_combo_output_consistency.py \
    tests/test_combo_brief_and_detail.py -q -rf -p no:randomly

# ③ ~ ⑥ census 를 들고 있는 루트 감사들
timeout 1800 python3 -m pytest tests/test_create_effect_ordinal_audit.py \
    tests/test_branch_setter_audit.py \
    tests/test_trigger_condition_separation_audit.py -q -rf -p no:randomly
timeout 1800 python3 -m pytest \
    tests/test_activation_action_semantic_boundary_audit.py -q -rf -p no:randomly
timeout 1800 python3 -m pytest \
    tests/test_unimplemented_rule_semantics_audit.py -q -rf -p no:randomly
timeout 1800 python3 -m pytest tests/test_effectdefinition_activation_audit.py \
    tests/test_variable_rebinding_audit.py \
    tests/test_clone_sibling_contamination_audit.py -q -rf -p no:randomly
```

| 묶음 | 결과 |
| --- | --- |
| ① `tests/engine` + 이번 Phase 의 세 파일 (스켈레촌 33건 포함) | ✅ **3977 passed** in 877.99s |
| ② 고정 경로 · `/combo` 출력 네 파일 | ✅ **82 passed** in 298.58s |
| ③ `test_create_effect_ordinal_audit` + `test_branch_setter_audit` + `test_trigger_condition_separation_audit` | ✅ **87 passed** in 349.02s |
| ④ `test_activation_action_semantic_boundary_audit` | ✅ **30 passed** in 72.08s |
| ⑤ `test_unimplemented_rule_semantics_audit` | ✅ **17 passed** in 8.68s |
| ⑥ `test_effectdefinition_activation_audit` + `test_variable_rebinding_audit` + `test_clone_sibling_contamination_audit` | ✅ **92 passed** in 415.26s |
| 남은 감사 열한 개 (`len(EFFECT_LIBRARY)` 만 움직인 자리) | ✅ 위 묶음들을 만들기 전의 두 배치 실행에서 전부 통과했다 |

🔴 **고치지 않은 실패 하나를 적어 둔다.**
`tests/agent/test_opponent_resource_weighting_audit.py::test_07_a_whole_duel_never_offers_a_choice_about_opponent_resources`
는 **이 Phase 의 기준 HEAD `7d5c45b` 에서도 같은 이유로 실패한다** —
`git worktree` 로 그 커밋을 꺼내 돌려 `1 failed, 15 passed` 를 확인했다.
6-AQ 가 만든 실패가 아니므로 손대지 않았다. (그 파일의
`len(EFFECT_LIBRARY)` census 는 이 Phase 가 고쳤다.)

🔴 **준비된 판 · 자동 테스트 · CLI 실행 · Discord 실행은 서로 다른 검증이다.**

| 종류 | 이번에 한 것 |
| --- | --- |
| 준비된 판 (시험이 손으로 만든 초기 상태) | §4 의 다섯 갈래 · A~F 묶음 |
| 자동 테스트 | 위 표 |
| CLI / 파이썬 직접 실행 | §5 (`build_opening` + `execute_opening`) · §6.2 · §6.3 |
| **Discord 실행** | ❌ **디스코드 검증 대기** — 이 저장소에서 디스코드에 접속하지 않았고, 접속했다고 적지 않는다 |

### 7.1 고친 census 들

이전 수가 **틀렸던 것이 아니다** — 그때의 사실이었고, 등재가 늘어 사실이
바뀌었다.

| 자리 | 이전 | 이번 |
| --- | --- | --- |
| `len(EFFECT_LIBRARY)` | 21 | **22** |
| `executable` 효과 수 | 18 | **19** |
| 특수 소환하는 등재 효과 | `93920420:e[1]` · `57835716:e[0]` | +`21441617:e[0]` |
| 비용이 있는 등재 효과 | `[57835716]` | `[57835716, 21441617]` |
| `resolution_skip` 을 적은 효과 | 3 | **4** |
| `COMBO_LINES` | 4 | **5** |
| `test_f03` 의 탐색 경로 단언 | `DIBER in chosen` | 묘지 제외 효과 둘 중 하나 + **지금 집히는 것은 스켈레촌 ①** |
| 등재된 **카드** 수 | 20 | **21** |
| 비용이 있는 효과 | 1 | **2** |
| 특수 소환하는 등재 효과 | 2 | **3** |
| 사용 제한을 가진 등재 효과 | 4 | **5** |
| 기동 효과의 카드별 블록 수 표 | 셋 (어니스트 · 기르수 · 디베르) | **넷** (+스켈레촌 3블록) |
| 카드군 조건을 쓰는 효과 | 3 | **4** |
| 정확히 1장을 고르는 효과 | 8 | **9** |
| 대상 묶음(`TargetBinding`) 수 | 12 | **13** |
| `activation` 을 가진 등재 효과 | 12 | **13** |
| Lua `SetCondition` 을 가진 등재 효과 | 3 | **4** |
| `SpecialSummonPermitted` 를 내는 조건 | 3 | **4** |
| 코드 분포의 "코드 없음" | 3 | **4** (자유 체인 16 · 유발 2 는 그대로) |
| 몬스터 등재 수 (마법 11 · 함정 5 는 그대로) | 4 | **5** |
| 묘지 질문에 답하는 등록 카드 | 3 | **4** |
| `already`(등재와 파생이 같은 답) | 686 | **687** (`newly_true` 는 그대로 990, 뒤집힌 카드 0장) |
| 기본(자율) 전개 | 7걸음 · 효과 수행 3걸음 | **6걸음 · 2걸음** (§7.2) |

`test_f03` 이 바뀐 이유를 적어 둔다. 기르수 ① 의 기준점(`FirstPermittedChoice`)이
집는 것은 패스코드가 더 작은 `21441617` 이고, 6-AO 시점에는 **그 분기가 목표에
닿지 못해** 탐색이 디베르 분기까지 갔다. 6-AQ 가 스켈레촌 ① 을 등재하자 그
분기가 먼저 목표에 닿는다. 🔴 **탐색 결과를 이전과 같게 만들려고 합법 후보를
제거하지 않았다.**

### 7.2 기본(자율) 전개가 6걸음으로 돌아간 이유

6-AP 는 이 패(`69811710,703897,2930675,12989604,93920420`)의 기본 전개를
**7걸음 · 효과 수행 3걸음**으로 적었고 **그때 사실이었다.** 6-AQ 의 실측은
**6걸음 · 2걸음**이다.

```
수정 전(6-AP): 일반 소환 / 기르수 ① (→ 디베르) / 기르수 ③ / 디베르 ① / 세트 x3
수정 후(6-AQ): 일반 소환 / 기르수 ① (→ **스켈레촌**) / 기르수 ③ / 세트 x3
               묘지: [21441617]
```

원인은 **기준점 선택**이다. 기르수 ① 의 해결 중 선택은
`FirstPermittedChoice` 가 집고 그것은 허용된 후보의 앞쪽(패스코드가 작은
쪽)이다. 6-AQ 가 스켈레촌 ① 을 등재하면서 그 카드의
`MAY_BE_SENT_TO_GRAVE` 를 공식 텍스트 전문을 읽어 적었으므로 허용 후보가
하나 늘었고, **21441617 < 57835716** 이다.

그 다음이 갈린다 — 디베르 ① 은 「덱에서」 특수 소환하므로 묘지에 혼자
있어도 발동하지만, 스켈레촌 ① 은 「자신 묘지의 "오르페골" 몬스터」 를
**대상으로 지정**해야 하고 그 자리의 묘지에는 **스켈레촌 자신뿐**이다
(「"오르페골 스켈레촌" 이외의」 로 자기 사본은 빠진다).

🔴 **이전 수치로 되돌리려고 합법 후보를 제거하지 않았다.**
`FirstPermittedChoice` 는 전략이 아니라 **기준점**이고
(`app/main.py::opening_wiring`), 보장받는 경로는 `--line` 쪽이다. 6-AP 의
보고서 §6.4 에도 같은 주석을 달아 두었다.

---

## 8. 남은 미지원

| 항목 | 상태 |
| --- | --- |
| `Card.IsRelateToEffect` 자체 | 🔺 **부분 해결** (STRUCTURAL-50, Phase 6-AQ 후속) — "지정한 뒤 존을 떠났는가" 는 판정한다. 무효화 계열의 관계는 여전히 없다 (§10.8) |
| 관측되지 않는 자리로 간 대상 | ✅ **해결** (Phase 6-AQ 후속) — 소환만 생략하고 제한은 건다 (§10.1) |
| 스켈레촌 `e2` (바벨 적용 시 유발즉시) | ❌ 유발즉시 발동 시점 미지원 |
| 기르수 `e[1]` (특수 소환 유발) | ❌ 등재하지 않았다 (§5.5) |
| 카노네 ① | ❌ 등재하지 않았다 — `_CANNONE_RESTRICTION_GUARD` 가 그 사실에 근거한 `restricts_others=False` 를 import 시점에 지킨다 |
| 갈라테아 · 갈라테아i · 롱기르수의 효과 | ❌ 소재 조건과 "막지 않는다" 만 읽었다 |
| 바벨 자신의 효과 | ❌ |
| 특수 소환 몬스터 · 엑스트라 덱 몬스터의 **패 · 덱**에서의 소생 제한 | ❌ 룰북은 그 셋 모두에 제한을 걸지만 `REVIVAL_LIMIT_FREE_ZONES` 가 패 · 덱을 그대로 열어 둔다 (§2.4 의 "좁히지 않은 쪽") |
| `Duel.SetOperationInfo` 의 예고 | ❌ 체인 중 예고 계층이 없다 |
| `EFFECT_FLAG_OATH` 깃발 | ❌ 조작 순서로만 지킨다 |
| 무효화된 바벨의 구별 | ❌ STRUCTURAL-76 (지속 효과 계층이 없다) |
| 기본 실행과 탐색 결과가 한 응답에 섞이는 문제 · 탐색 시간 | 📌 6-AP 가 기록한 후속 과제 그대로 |

### 8.1 시뮬레이터 연동 전에 필요한 항목

프로젝트 방향은 **대표 오르페골 전개를 시작 패부터 목표 필드까지 연결한 뒤
Duel Simulator 시각화 연동**이다. 이번 Phase 로 그 전개가 연결되었으므로, 연동
전에 남은 것을 적어 둔다.

1. **최종 필드의 안정적인 표현.** 지금 최종 자원은 자리별 카드 ID 목록으로만
   나온다 (§5.3). 시각화는 자리 번호 · 표시 형식 · 링크 마커까지 필요하다 —
   `SummonPlacement` 가 이미 자리를 정하므로 그것을 내보내는 일이다.
2. **걸음마다의 상태 스냅샷.** 지금은 걸음의 `reason` 문자열과 최종 해시만
   남는다. 애니메이션에는 걸음별 자리 변화(`StateDelta`)가 필요하고, 그것은
   `EventJournal` 에 이미 있다 — 내보내는 형식만 없다.
3. **제한 · 사용 기록의 표시.** 어둠 속성 제한 두 건이 왜 걸렸는지가 화면에
   보여야 "왜 이 소환만 되는가" 를 읽을 수 있다.
4. **기본 실행과 탐색 출력의 분리** (6-AP 의 후속 과제). 한 응답에 섞이면
   어느 쪽 필드를 그려야 하는지 알 수 없다.

🔴 **이번 범위에서 연동을 구현하지 않았다** — 위 넷은 다음 작업의 목록이다.

> 🔴 **정정 안내 (Phase 6-AQ 후속).** 위 표의 두 줄(`IsRelateToEffect` 자체 ·
> 관측되지 않는 자리로 간 대상)은 **6-AQ 시점에 ❌ 였고**, 후속 보완이 각각
> 부분 해결 · 해결로 바꿨다. 과거 기록은 §4.1 · §4.2 에 그대로 남겨 두었다.
> 나머지 줄은 **하나도 바뀌지 않았다** — 후속 보완이 건드린 범위가 아니다.

---

## 9. 디스코드에 넣을 입력값

🔴 **디스코드 검증 대기** — 아래 값은 이 저장소에서 CLI · 파이썬으로 돌려
확인한 것이고, 디스코드에서 실행하지 않았다.

**고정 경로** (§5 의 실측과 같은 입력):

```
hand:   69811710,703897,2930675,12989604,61654098
recipe: 69811710 x3, 93920420 x3, 57835716 x3, 21441617 x3, 94046012 x3,
        40441990 x3, 2930675 x3, 90351981 x3, 26845680 x3, 61654098 x3,
        703897 x3, 12989604 x3, 55051920 x2, 47171541 x2,
        extra: 30741503 x1, 48835607 x1, 76145142 x1, 93854893 x1,
               74820316 x1, 3134857 x1
line:   orcust-skeleton-longirsu
```

**일반 탐색** (같은 패 · 같은 레시피, `line:` 없이):

```
search: galatea     → §6.2 — 도달 + 재생 성공 (스켈레촌 ① 을 탐색이 스스로 쓴다)
search: longirsu    → §6.3 — 🔴 기본 예산 안에서 찾지 못한다 (BUDGET_EXCEEDED)
```

### 9.1 예상 최종 필드와 확인 지점

`line: orcust-skeleton-longirsu` 의 예상 결과:

| 자리 | 예상 |
| --- | --- |
| 엑스트라 몬스터 존 | 「오르페골 롱기르수」(76145142) 1장 |
| 메인 몬스터 존 | 비어 있음 |
| 묘지 | 「오르페골 갈라테아」(30741503) · 「잭나이츠 오르페골 기르수」(69811710) |
| 제외 | 「오르페골 디베르」(57835716) · 「오르페골 스켈레촌」(21441617) |
| 패 | 4장 (703897 · 2930675 · 12989604 · 61654098) |

확인할 지점 넷:

1. **6/6 단계 완료** 로 적히는가 (중간에 멈추면 몇 번째에서 멈췄는지).
2. 다섯째 걸음이 `21441617:e[0]` 이고 **대상이 `@primary=[기르수]`** 로
   적히는가 (대상 지정이 발동 시점에 실려야 한다).
3. 여섯째 걸음의 링크 소재가 **갈라테아 + 기르수** 두 장인가 (장수 2 ·
   링크 수치 합 3).
4. 어둠 속성 제한이 **두 건** 적히는가 (디베르 · 스켈레촌).

---

## 10. 후속 보완 — 대상 관계 단절 (Phase 6-AQ 후속)

6-AQ 가 남긴 **두 결함**을 고쳤다. §4.1 · §4.2 · §8 에 정정 안내를 달았고
과거 기록은 지우지 않았다 — 그때 그 설명은 사실이었다.

### 10.1 두 결함과 수정 전 · 후 (실측)

| 발동 후 바꾼 것 | 6-AQ (수정 전) | 후속 보완 (수정 후) |
| --- | --- | --- |
| **A.** 대상을 묘지 → 패 → **다시 묘지로** | ✅ 소환된다 (같은 `InstanceId` 라서 같은 대상으로 읽었다) | ❌ **소환하지 않는다** · 어둠 제한 ✅ · 비용 · 사용 기록 유지 |
| **B.** 대상을 묘지 → **덱**(비공개 존)으로 | ❌ `UNCHECKED_TARGET` 으로 **효과 전체 거절** (제한도 걸리지 않았다) | ❌ 소환 생략 · 어둠 제한 ✅ · 비용 · 사용 기록 유지 · 덱은 열지 않는다 |

🔴 **발동 후의 변화는 시험용 조작이다** — 실제 등재된 상대 카드로 이 상황을
만들었다고 주장하지 않는다. 묘지 → 패 · 묘지 → 덱 · 묘지 → 제외는 시험이
`GameState.move` 를 직접 불러 만든다.

해결기의 실제 문장 (수정 후, 두 갈래가 같은 문장을 쓴다):

```
status: resolved | code: ok
reason: 21441617:e[0] 를 적용했습니다 (1건). 0번 조작(special_summon)은
        지정한 대상(primary)을 쓸 수 없어 하지 않았습니다: @primary 로 지정한
        #41 는 그 뒤에 존을 떠나 이 효과와의 관계가 끊겼습니다. 공식 처리도
        그때 그 카드를 쓰지 않습니다 (Card.IsRelateToEffect 가 거짓).
        나머지 일은 그대로 했습니다.
MZONE   []            ← 소환 없음
REMOVED [21441617]    ← 비용 유지
limits  [('DARK', 21441617)]   ← 제한 걸림
```

대상이 묘지에 **그대로** 있을 때는 바뀌지 않았다 (회귀):

```
status: resolved | code: ok
reason: 21441617:e[0] 를 적용했습니다 (2건).
MZONE   [69811710]    ← 소생
limits  [('DARK', 21441617)]
```

### 10.2 무엇을 적고, 무엇이 관계를 끊는가

새 상태 표 하나다 — `engine/state/target_relation.py` 의
`TargetRelationRegistry`. `uses` · `rule_uses` · `summon_uses` ·
`summon_limits` 에 이어지는 **다섯 번째 표**이고 `GameState` 가 들고 있다.

* **적는 때**: `engine/activation.py` 가 체인 링크를 쌓을 때. 그 효과의
  **TARGETING 바인딩**에서 고른 개체만 적는다 (`CHOOSING` · `ALL` 은 대상
  지정이 아니므로 적지 않는다 — 디베르 ① 은 여기 들어오지 않는다).
* **열쇠**: `(발동한 개체, 카드 ID, 효과 번호, 대상 개체)`. 같은 카드명 두
  장이 각각 같은 효과를 발동할 수 있으므로 **어느 개체가 발동했는지**까지
  적어야 한 링크의 관계가 다른 링크의 것과 섞이지 않는다.
* **지우는 때**: `engine/chain.py` 가 그 링크을 해결하면 그 링크의 기록만
  지운다 (`forget`). 불발된 링크의 기록은 남기지 않는다.

🔴 **적용 범위를 좁게 적는다.** 끊는 것은 **존 종류가 바뀌는 이동 하나**이고,
`GameState.move` 가 그 자리다 (`move_card` 의 유일한 호출자).

| 조작 | 관계 |
| --- | --- |
| 묘지 → 패 · 묘지 → 덱 · 묘지 → 제외 · 필드 → 묘지 | 🔴 **끊는다** |
| 같은 존 안의 순서 변경 · 섞기 (`ZoneContainer.reorder`) | 끊지 않는다 |
| 표시 형식 변경 (`set_position`) | 끊지 않는다 |

근거는 EDOPro 의 `Card::clear_relate_effect()` 가 **위치 변경**에서 불린다는
것이다. 표시 형식 · 컨트롤 변경은 그 자리가 아니고, 이 저장소에는 컨트롤만
바꾸는 primitive 가 **없다** (실측: `GameState` 에 `take_control` 류가 없다) —
그래서 그 갈래는 지금 구현할 것이 없다. `test_d08` 이 끊지 않는 셋(묘지에
카드 추가 · `reorder` · `set_position`)을 센다.

🔴 **같은 개체 번호 하나로 판단하지 않는다.** `InstanceId` 는 개체의 영구
번호이고 (한 번 쓴 번호는 재사용하지 않는다), 관계는 **그 효과가 그 때
지정했다** 는 따로 적힌 사실이다. `test_d06` 이 제외를 거쳐 돌아온 경우도
관계가 회복되지 않음을 센다. `test_d07` 은 관계가 끊긴 뒤 **같은 카드명의
다른 카드**를 같은 자리에 놓아도 그것이 대신 소환되지 않음을 센다.

### 10.3 비공개 정보를 열지 않는 판정

바뀐 것은 **묻는 순서와 묻는 것**이다. 조작 하나를 계획하기 전에
`EffectExecutor._check_target_relations` 가 먼저 묻는다.

| 판에 적힌 관계 | 답 | 결과 |
| --- | --- | --- |
| 끊겼다 (`intact=False`) | **확정 거부** — `TARGET_RELATION_LOST` | 소환만 생략, 제한은 건다 |
| 살아 있다 (`intact=True`) | 통과 | 기존 적법성 · 소환 제한 검사를 **그대로** 지난다 |
| 기록이 없다 | **모름** — `UNCHECKED_TARGET` + `INFORMATION_UNAVAILABLE` | 실행하지 않는다 (`missing=effect-target-relation`) |

🔴 **현재 대상의 비공개 위치 · 정체를 찾아 정책에 넘기지 않는다.** 판정에
쓰는 것은 판에 적힌 관계 기록 하나이고, 덱에 있는 카드를 열어 보지 않는다.
`test_d04` 가 그것을 센다 — 해결 뒤에도 그 카드는 **어느 관측에도** 보이지
않는다 (`GameStateView.visible_instances()` 두 좌석 모두).

🔴 **모든 `HIDDEN_CARD` / `UNCHECKED_TARGET` 을 대상 이탈로 바꾸지 않았다.**
기록이 없으면 모름이 그대로 남고 (`test_d09`: 기록을 지운 판에서는 **소환도
제한도 없다**), 잘못된 대상 ID · 누락된 대상 · 후보 밖 선택 · 실행 예외는
기존 코드와 기존 자리를 그대로 쓴다 (`test_c05` · `test_e02` ·
`test_d10`). `test_d10` 은 끊긴 관계가 `CANDIDATE_NOT_ELIGIBLE` 과 **다른
코드**임을 센다.

`ValidationCode.TARGET_RELATION_LOST` 는 **`INVALID` 쪽**이다 — 관계가
끊겼다는 것은 가려진 카드를 읽지 않고 아는 **확정된** 사실이므로 모름이
아니다. 그 코드가 `engine/validation.py` 에서 자기 묶음(`대상 관계 (Phase
6-AQ 후속)`)을 갖는다.

### 10.4 비용 · 사용 기록 · 제한 · 소환 이벤트

| 항목 | 두 갈래 모두 |
| --- | --- |
| 자기 제외 비용 | 유지 (`REMOVED [21441617]`) — 돌려주지 않는다 |
| 카드명 기준 사용 제한 | 유지 (`uses.count(...) == 1`) — 두 번째 장이 막힌다 |
| 어둠 속성 제한 | **걸린다** (한 건, 출처 21441617) |
| 소환 이벤트 | **없다** — `EventJournal` 에 `special_summon` 기록이 남지 않는다 |
| 대상 재선택 | 없다 — 해결 중에 다른 카드를 고르지 않는다 |

🔴 **"관계 단절로 소생 생략" 과 "판정 불명으로 실행 불가" 가 다른 문장으로
남는다.** 앞쪽은 `RESOLVED` + 생략 안내 문장, 뒤쪽은 `UNCHECKED_TARGET` +
`missing` 이다 (§10.3 의 표).

🔴 **스켈레촌 카드 ID 를 해결기에 하드코딩하지 않았다** — `test_e03` 이
`engine/effect/executor.py` 에 `21441617` · `57835716` 이 없음을 센다. 쓰는
것은 효과 정의의 `ResolutionSkip(when_target_unusable=True)` 선언 하나이고,
`test_e05` 가 다른 등재 효과가 그 선언을 얻지 않았음을 센다.

### 10.5 fork · 상태 해시 · 재생

| 요구 | 결과 | 어디서 센다 |
| --- | --- | --- |
| 발동 때의 기록이 해결까지 남는다 | ✅ | `test_f05` |
| `fork` · `project` 가 기록을 정확히 복사한다 | ✅ | `test_f03` |
| 한 분기의 이동이 다른 분기의 관계를 끊지 않는다 | ✅ | `test_f03` (원본과 다른 분기 모두 유지) |
| 해결 결과가 다른 판이 중복 제거에서 합쳐지지 않는다 | ✅ | `test_f04` |
| 재생이 실제 발동 과정에서 기록을 다시 만든다 | ✅ | `test_f02` · `test_g03` · `search:galatea` 재생 |
| 체인이 끝난 뒤 기록이 정리된다 | ✅ | `test_f05` |
| `InstanceId` 를 재발급하거나 카드 선택 기록을 깨뜨리지 않는다 | ✅ | `test_f02`(같은 해시) · `test_g03` |

🔴 **상태 해시에 들어가는 것은 단절뿐이다.** `canonical_state` 는
`only_broken=True` 로 **끊긴 기록만** 싣는다. 살아 있는 기록은 "해결을
기다리는 대상 지정 링크가 있다" 와 같은 말이고, 체인은 같은 판이 경로에 따라
다른 해시를 갖지 않도록 **일부러** 정규 표현에서 빠져 있다 (Phase 2-D-3 ·
2-F-1 · 2-F-2) — 그 사실을 관계 표로 우회해 들여놓지 않는다. 비어 있으면
자리를 아예 만들지 않으므로 (`()` 를 끼워 넣기만 해도 JSON 이 길어진다),
**단절이 일어난 판만** 새 해시를 갖는다.

🔴 **그 결과 기존 판의 해시가 한 글자도 움직이지 않았다.** 처음에는 기록
전부를 실었고, 그때는 **체인 해결을 기다리는 판**의 해시가 `tests/engine` 의
8곳에서 움직였다 (싸이크론 등 대상 지정 효과의 보류 상태). 그것이 이 변경의
범위가 아니라고 보아 단절만 싣도록 좁혔고, 그 8곳이 다시 원래 값으로
돌아왔다 — 고정값을 고쳐 맞춘 것이 아니다. `test_f04` 가 양쪽을 함께 센다:
살아 있는 기록을 지워도 해시가 같고, 끊긴 기록은 해시를 바꾼다.

### 10.6 정상 전개가 그대로인가 (회귀)

**고정 경로** `line: orcust-skeleton-longirsu` — 시작 패 · 레시피를 바꾸지
않았다. 실측 (수정 후):

```
can_run: True []    completed: True  done: 6  blocked_at: None
 0 normal_summon    accepted=True
 1 activate_effect  69811710:e[0]
 2 activate_effect  57835716:e[0]
 3 link_summon      → 갈라테아
 4 activate_effect  21441617:e[0] 대상 @primary=[#75]
 5 link_summon      → 롱기르수

EMZONE  [76145142]
GRAVE   [30741503, 69811710]
REMOVED [57835716, 21441617]
limits  [('DARK', 21441617), ('DARK', 57835716)]
```

**일반 탐색** `search: galatea` — §6.2 의 측정값과 **완전히 같다**:

```
reached: True | termination: GOAL_REACHED
nodes: 34  deepest: 5  budget_hit: ()   elapsed: 67.5s
final_hash: 44e3cbe8e28e4e1dd459c731afcec19606aa7ef7358a4579a722990edda2c6bd
rerun.ok: True  goal_reached: True  matches_search: True
```

🔴 **`search:longirsu` 는 여전히 기본 예산 안에서 찾지 못한다** (§6.3). 이
보완의 성공 조건을 그 탐색의 성공으로 바꾸지 않았고, 탐색 알고리즘 · 예산 ·
후보를 건드리지 않았다.

### 10.7 실행한 테스트와 실제 결과

🔴 **구현자(나)가 돌린 것이다.** 사용자에게 pytest 실행이나 테스트 작성을
요구하지 않는다.

| 명령 | 실측 |
| --- | --- |
| `pytest tests/test_skeleton_revival_and_longirsu.py` | **40 passed** (D 절이 10개로 늘었다) |
| `pytest tests/engine/test_effect_activation.py …(5개 파일)… tests/test_skeleton_revival_and_longirsu.py` | **349 passed** — 대상 지정 효과의 보류 상태 해시 8곳 포함 |
| `pytest tests/test_orcust_girsu_line.py tests/test_girsu_token_line.py tests/test_combo_output_consistency.py tests/test_combo_brief_and_detail.py` | **123 passed** |
| `pytest`(ValidationCode census 9개 파일) | 아래 §10.9 |
| `python3 runline.py` (고정 경로) | 6/6 · 위 §10.6 의 판 |
| `python3 search_galatea.py` | 도달 + 재생 성공 · 위 §10.6 의 수치 |

🔴 **디스코드에서 실행하지 않았다 — 디스코드 검증 대기.** §9 의 입력값은
그대로다 (패 · 레시피 · `line:` 이 바뀌지 않았으므로).

### 10.8 여전히 지원하지 않는 대상 관계 사례

🔴 **모든 카드의 `IsRelateToEffect` 를 지원했다고 주장하지 않는다.**
STRUCTURAL-50 은 **부분 해결**이다. 남은 것:

| 사례 | 상태 |
| --- | --- |
| 체인 무효화 · 효과 무효화가 만드는 관계 단절 | ❌ 무효화 계층 자체가 없다 |
| 같은 체인 안의 다른 효과가 대상을 건드려 생기는 관계 | ❌ |
| 컨트롤 변경으로 끊기는 관계 | ❌ 컨트롤만 바꾸는 primitive 가 이 저장소에 없다 |
| 표시 형식 변경이 관계에 영향을 주는 특수한 카드 | ❌ 일반 규칙(끊지 않는다)만 적었다 |
| 필드 → 필드 이동(존 종류가 같은 이동)의 세부 | ❌ 지금은 "존 종류가 바뀌면 끊는다" 한 줄이다 |
| 관계 기록이 없는 판 | 🔴 **모름으로 남긴다** — 정상 이탈로 흡수하지 않는다 (`test_d09`) |

### 10.9 census 와 기준 HEAD 에서 이미 실패하던 감사들

`ValidationCode` 가 54 → **55** 로 늘었으므로 (`TARGET_RELATION_LOST`), 그
수를 들고 있던 census 들을 고쳤다. 숫자만 올리지 않고 **무엇이 늘었는지를
이름으로** 고정하는 기존 방식을 따랐다 (`ADDED_IN_PHASE_6AQ_FOLLOWUP`).

| 파일 | 고친 것 |
| --- | --- |
| `test_validation_code_consistency.py` · `test_validation_code_minimal_fix.py` · `test_trigger_unknown_reason.py` | 새 집합을 더해 48 의 산술을 유지 |
| `test_validation_code_unknown_policy.py` | 멤버 55 · `INVALID` 46 · 묶음 분할 (1, 46, 7, 1) |
| `test_validation_code_rejection_semantics_audit.py` | 선언 묶음에 `대상 관계 (Phase 6-AQ 후속): 1` 추가 |
| `test_simulation_status_unknown_codes_audit.py` | 이름 붙인 12 는 그대로, 나머지 42 → 43 |
| `test_duelstep_withheld_validation_audit.py` | 55 · 54 · `INVALID` 46 |
| `test_rule_not_implemented_code_audit.py` | `CODE_READERS` 를 넷 → 다섯으로 (6-AQ 의 `UNUSABLE_TARGET_CODES` 자리) |
| 기타 census 파일 9개 | 54 → 55 한 줄씩 |

🔴 **모름 쪽은 7 그대로다** — 늘어난 하나가 `INVALID` 이므로, 모름을 늘려
문제를 덮은 것이 아니다.

🔴 **기준 HEAD 에서 이미 실패하던 감사 11개는 고치지 않았다.** 아래는
`74acd0c`(이 보완의 기준) 과 `74acd0c~5`(6-AQ 전) **두 곳에서 모두** 같은
이유로 실패한다 — 이 보완이 만든 것이 아니고, 이 보완의 범위도 아니다.

```
tests/test_validation_code_minimal_fix.py::test_17_legal_actions_and_search_are_unchanged
tests/test_validation_code_minimal_fix.py::test_24_only_four_production_lines_changed_their_code
tests/test_validation_code_unknown_policy.py::test_29_the_board_and_the_randomness_do_not_move
tests/test_validation_code_rejection_semantics_audit.py::test_03 · test_22 · test_31
tests/test_event_relation_minimal_fix.py::test_18_the_two_different_result_gates_were_left_alone
tests/test_rule_not_implemented_code_audit.py::test_02 · test_05 · test_15
tests/test_duelstep_withheld_validation_audit.py::test_09
```

둘은 고정된 상태 해시(`test_17` · `test_29`)이고 나머지는 production 소스의
문자열 · 자리 수 census 다. 🔴 **그중 `test_rule_not_implemented_code_audit.py
::test_02` 하나는 이 보완이 세는 수를 더 움직인다** — 기준 HEAD 에서 `127 ==
125` 로 실패하고, 이 보완의 설명 문장들 때문에 `128 == 125` 가 된다. 어느
Phase 가 그 수를 처음 어긋나게 했는지 확인하지 않은 채 고정값을 올리면 근거
없는 완화가 되므로, **고치지 않고 이렇게 적어 둔다.**
