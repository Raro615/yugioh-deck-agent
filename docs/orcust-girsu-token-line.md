# Phase 6-AF — 기르수 ③ 의 토큰으로 갈라테아까지

> **완료 기준.** *기존에는 실행하지 못하던, 「성유물－『성장』」 없는 시작
> 패에서 양쪽 토큰 생성과 후속 링크 소환이 실제 엔진으로 이어지는가.*
>
> **이어진다.** 실측: `/combo line:orcust-girsu-token` 이 네 단계를 **4/4**
> 로 수행하고, 최종 판에 「오르페골 갈라테아」가 자신 엑스트라 몬스터 존에
> 있다.

🔴 **이 경로를 최선 전개라고 주장하지 않는다.** 최종 필드가 강하다고도
주장하지 않는다. 이것은 새로 구현한 네 계약(토큰 생성 · 토큰 소멸 · 링크
몬스터 소재 · 턴당 링크 소환 제한)을 실제 듀얼 실행으로 **잇는 검증용
경로**다. 실제 오르페골 전개는 이 자리에서 다른 수를 쓴다.

---

## 1. 카드와 규칙의 근거

### 1.1 잭나이츠 오르페골 기르수 ③ (`69811710`, `e[2]`)

공식 텍스트 (`data/cards.cdb`):

> 자신 필드에 이 카드 이외의 몬스터가 존재하지 않을 경우에 발동할 수 있다.
> 서로의 필드에 「성유물 토큰」(기계족 / 어둠 / 레벨 1 / 공 0 / 수 0)
> 1장씩을 앞면 수비 표시로 특수 소환한다. (이 효과는 1턴에 1번밖에 사용할
> 수 없다)

`c69811710.lua` 의 `e3`:

```lua
e3:SetType(EFFECT_TYPE_IGNITION)
e3:SetRange(LOCATION_MZONE)
e3:SetCountLimit(1,{id,1})
e3:SetCondition(function(e,tp) return not Duel.IsExistingMatchingCard(
    nil,tp,LOCATION_MZONE,0,1,e:GetHandler()) end)
e3:SetTarget(s.tktg)
e3:SetOperation(s.tkop)
```

🔴 **ordinal 2 는 추측이 아니다.** 파싱 결과의 세 번째 항이 이 효과다
(실측 `repository.get(69811710).script.effects`):

| ordinal | index | 분류 | code | categories | ranges | count_limit |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | `e1` | SINGLE+TRIGGER_O | `EVENT_SUMMON_SUCCESS` | TOGRAVE | — | `1,id` |
| 1 | `e2` | SINGLE+TRIGGER_O | `EVENT_SPSUMMON_SUCCESS` | TOGRAVE | — | `1,id` |
| **2** | **`e3`** | **IGNITION** | — | **SPECIAL_SUMMON · TOKEN** | **MZONE** | **`1,{id,1}`** |
| 3 | `e1` | SINGLE | `EFFECT_ADD_TYPE` | — | — | — |

### 1.2 발동 조건과 **해결 시점 재검사**는 다르다

`s.tktg` 의 `chk==0` 갈래가 **다섯 가지**를 보고, `s.tkop` 이 **그 다섯만**
다시 본다 — `SetCondition` 은 다시 보지 않는다 (실측: 그 함수에
`IsExistingMatchingCard` 호출이 없다).

| 어디서 읽었는가 | 옮긴 자리 | 발동 | **해결 재검사** |
| --- | --- | :-: | :-: |
| `e3:SetCondition(not IsExistingMatchingCard(…, e:GetHandler()))` | `Not(ZoneCountAtLeast(자신, MZONE, 1, excluding_source=True))` | ✅ | **❌** |
| `Duel.GetLocationCount(tp,LOCATION_MZONE)>0` | `ZoneHasFreeSlot(자신, MZONE)` | ✅ | ✅ |
| `Duel.GetLocationCount(1-tp,LOCATION_MZONE)>0` | `ZoneHasFreeSlot(상대, MZONE)` | ✅ | ✅ |
| `not IsPlayerAffectedByEffect(tp,CARD_BLUEEYES_SPIRIT)` | `SimultaneousSpecialSummonPermitted(2)` | ✅ | ✅ |
| `IsPlayerCanSpecialSummonMonster(tp,…)` ×2 | `SpecialSummonPermitted()` | ✅ | ✅ |

🔴 **왜 가르는가.** 합치면 **발동 뒤에 자신 필드에 다른 몬스터가 생긴 것만
으로** 해결이 불발로 바뀐다 — 실제 카드는 그때도 토큰을 만든다. 그래서
`EffectDefinition` 에 `resolution_condition` 칸을 더했고, 해결기는 그 칸이
있으면 **그것만** 다시 본다 (없으면 예전 그대로 `activation` 을 본다 —
`c93920420.lua` 의 `s.spop1` 처럼 같은 조건을 다시 보는 효과가 그쪽이다).

`IsPlayerCanSpecialSummonMonster` 가 두 번 불리는데 조건이 한 항인 이유:
두 호출 모두 **첫 인자가 `tp`** 이고 (즉 "tp 가 소환할 수 있는가"), 놓이는
쪽의 차이는 빈 칸 검사 둘이 이미 말한다.

### 1.3 「2장 이상 동시 특수 소환 금지」 는 **다른 질문**이다

`CARD_BLUEEYES_SPIRIT = 59822133` 은 청안의 정령룡이고, 공식 텍스트가

> Neither player can Special Summon 2 or more monsters at the same time.

이다 (`data/cards.cdb` 59822133). `c59822133.lua` 의 `e1` 은
`SetType(EFFECT_TYPE_FIELD)` · `SetCode(id)` · `SetRange(LOCATION_MZONE)` ·
`SetProperty(EFFECT_FLAG_PLAYER_TARGET)` · `SetTargetRange(1,1)` 이다.

🔴 **특수 소환 금지와 합치지 않는다.** 합치면 그 카드가 필드에 있는 판에서
**한 장짜리 특수 소환까지** 막히고, 그것은 규칙이 아니다. 그래서 표와
판정을 따로 두었다 (`SIMULTANEOUS_SUMMON_PROHIBITIONS` ·
`assess_simultaneous_special_summon_permission`), 그리고 `count < 2` 면
아예 묻지 않는다.

🔴 **전수를 확인하지 못했다.** 이 금지는
`SPECIAL_SUMMON_RESTRICTION_CODES` 의 `EFFECT_CANNOT_SPECIAL_SUMMON` 으로
적히지 않는다 — 카드가 **자기 ID 를 코드로** 등록하고(`e1:SetCode(id)`)
다른 스크립트가 `IsPlayerAffectedByEffect` 로 묻는다. 파싱 캐시는 그 숫자
코드를 **`null` 로** 적으므로 (실측: `data/cache/lua_scripts.json` 의
59822133 `e1` → `"code": null`) 이 금지를 등록하는 카드를 전수 조회할 길이
**없다.** 손으로 읽은 한 장만 확정 판정을 받고, 그 사실은
`SIMULTANEOUS_SUMMON_BLIND_SPOTS` 에 이름으로 남는다.

### 1.4 「성유물 토큰」 (`46647145`)

🔴 **같은 이름의 다른 번호가 있다.** `cards.cdb` 에 "World Legacy Token"
이 **69811711** 로도 들어 있고, 그 번호는 기르수의 ID +1 이어서 "기르수가
만드는 토큰" 으로 잘못 짚기 쉽다. 상수 파일이 가리키는 것은 46647145 다
(`data/constants/card_counter_constants.lua` 의
`TOKEN_WORLD_LEGACY=46647145`). **이름이 아니라 상수를 따랐다.**

| 항목 | 값 | 근거 |
| --- | --- | --- |
| setcode | `254` = `0xfe` (SET_WORLD_LEGACY) | `cards.cdb` 46647145 |
| type | `16401` = `MONSTER\|NORMAL\|TOKEN` | 같은 줄 |
| 종족 · 속성 | `32`=MACHINE · `32`=DARK | 같은 줄 |
| 레벨 · 공 · 수 | 1 · 0 · 0 | 같은 줄 |
| 스크립트 | **없다** (HTTP 404) | `ProjectIgnis/CardScripts` 의 `official/c46647145.lua` |

### 1.5 갈라테아i (`48835607`) 와 갈라테아 (`30741503`) — 소재 조건이 다르다

```lua
-- c48835607.lua
Link.AddProcedure(c,aux.FilterBoolFunctionEx(Card.IsSetCard,
    {SET_ORCUST,SET_WORLD_LEGACY}),1,1)
-- c30741503.lua
Link.AddProcedure(c,aux.FilterBoolFunctionEx(Card.IsType,TYPE_EFFECT),
    2,nil,s.matcheck)
function s.matcheck(g,lc,sumtype,tp)
    return g:IsExists(Card.IsSetCard,1,nil,SET_ORCUST,lc,sumtype,tp) end
```

🔴 **갈라테아i 는 효과 몬스터를 요구하지 않는다** — 필터에
`Card.IsType(TYPE_EFFECT)` 가 **없다**. 갈라테아는 요구한다. 그 차이가 이
경로의 모양을 정한다:

* 성유물 토큰은 **`TYPE_NORMAL`** 이므로 갈라테아i 의 소재가 되고
  **갈라테아의 소재는 될 수 없다.**
* 그래서 3 단계가 **필요하다** — 토큰을 갈라테아i 로 바꾸고, 그 **링크
  몬스터**가 갈라테아의 소재가 된다.

### 1.6 갈라테아i 의 턴당 링크 소환 제한

`c48835607.lua` 의 `s.regop` (링크 소환 성공 시):

```lua
e1:SetType(EFFECT_TYPE_FIELD)
e1:SetCode(EFFECT_CANNOT_SPECIAL_SUMMON)
e1:SetProperty(EFFECT_FLAG_PLAYER_TARGET)
e1:SetTargetRange(1,0)
e1:SetTarget(function(e,c,sump,sumtype)
    return c:IsCode(id) and sumtype&SUMMON_TYPE_LINK==SUMMON_TYPE_LINK end)
e1:SetReset(RESET_PHASE|PHASE_END)
Duel.RegisterEffect(e1,tp)
```

즉 **그 카드명의 링크 소환만** 막고, **그 턴**이고, **자신에게만** 걸린다
(`SetTargetRange(1,0)`). 그리고 `Duel.RegisterEffect(e1,tp)` 가 **플레이어
에게** 거는 것이므로, 그 카드가 소재로 떠난 뒤에도 턴 끝까지 남는다.

---

## 2. 구현한 것과 지원 범위

### 2.1 토큰의 생명주기 — `engine/token.py`

🔴 **토큰을 "덱에서 꺼낸 일반 카드" 처럼 다루지 않았다.** 세 가지가 다르다.

| | 일반 카드 | **토큰** |
| --- | --- | --- |
| 출발 자리 | 덱 · 패 · 엑스트라 덱 | **없다** — 그 자리에서 만들어진다 |
| 덱 · 패 장수 | 줄어든다 | **변하지 않는다** (만든 뒤 실측으로 확인) |
| 필드를 떠나면 | 묘지 · 제외로 **간다** | **소멸한다** — 어느 존에도 남지 않는다 |

그래서 `SummonProcedure` 를 쓸 수 없다 (그 절차의 `plan_for` 는 "그 카드가
`from_zones` 에 있는가" 를 먼저 묻는다). `engine/token.py` 가 **만들면서
놓고**, 놓은 뒤 덱 · 패 · 엑스트라 덱 장수가 그대로임을 확인한다.

**최소한의 재사용 계약만 더했다.** 기르수 전용 상태 엔진을 만들지 않았다 —
이 파일에 카드 ID 분기가 **없고** (`test_g04` 가 AST 로 센다), `TOKEN_RULES`
는 "그 토큰의 공식 데이터가 무엇인가" 를 적은 표일 뿐이다.

**가른 네 사람** (`TokenCreated`):

| 칸 | 뜻 | 기르수에서 |
| --- | --- | --- |
| `owner` | 카드의 주인 | **놓이는 쪽** (토큰은 어느 덱에서도 오지 않는다) |
| `controller` | 지금 컨트롤하는 쪽 | `tp` 와 `1-tp` |
| `creator` | 만든 **카드** | 기르수 그 개체 |
| `summoner` | 그 효과를 해결한 **플레이어** | 언제나 `tp` |

🔴 `MonsterSummoned.player` 는 **컨트롤러**다 (그 칸의 기존 설명). 상대
필드의 토큰은 P0 가 해결했지만 P1 의 것이므로, **해결한 플레이어는 거기
적지 않고** `TokenCreated.summoner` 가 들고 있다.

### 2.2 사건 — 실제 소환과 소멸

| 변화 | 언제 | 왜 그 모양인가 |
| --- | --- | --- |
| `TokenCreated` | 만들 때 | **생성 관계** (누가 만들었는가) |
| `MonsterSummoned(SPECIAL, from_zone=None)` | 만들 때 | 토큰도 **특수 소환된다** — 「특수 소환되었을 경우」 유발이 본다 |
| `TokenVanished` | 필드를 떠날 때 | **`ZoneMoved` 가 아니다** |

🔴 **`from_zone=None` 은 "적지 않았다" 가 아니라 "어느 자리에서도 오지
않았다" 다.** 아무 존을 채워 넣으면 그 존에서 카드가 한 장 줄어든 것처럼
읽히고, 「덱에서 특수 소환되었을 경우」 류의 유발이 거짓으로 발화할 자리가
된다.

🔴 **허위 묘지행 사건을 만들지 않는다.** `ZoneMoved(send_to_grave)` 로
적으면 `TimingEvent.from_delta` 가 그것을 `CARD_MOVED` 로 읽고, 「이 카드가
묘지로 보내졌을 경우」 류의 유발이 **묘지에 가지도 않은 토큰**에 발화할
자리가 된다. 실측으로 고정했다 (`test_c01`): 토큰이 소재로 떠난 뒤
`TokenVanished` 가 **1건**, 그 개체의 `ZoneMoved` 가 **0건**, 묘지가
**비어 있다**.

`TokenVanished` 에는 **옮길 시점 이름이 아직 없다** — `timing_for` 가
그것을 `UNIMPLEMENTED` 사건으로 남긴다 (지어낸 시점을 주지 않고, 그 사실이
보고에 보이는 쪽을 골랐다 — STRUCTURAL-74 와 같은 태도).

### 2.3 토큰 정의를 어디서 읽는가

🔴 **검색 · 덱 구축이 보는 목록은 한 장도 늘지 않았다.** 토큰은 덱에 넣을
수 없으므로(공식 규칙) 거기 섞이면 "넣을 수 있다" 로 읽힌다. 그래서

* `OfficialDatabaseSource.iter_cards` 의 기본값은 그대로 `include_tokens=False`
* `CardRepository.all_cards()` · 검색 · 색인은 `_cards` **하나만** 본다
* 토큰은 **다른 표**(`_tokens`)에 들어가고, `get()` 이 ID 로 물을 때만
  그 표까지 본다 — 듀얼 중의 토큰 개체가 쓰는 길이다

실측 (`test_a04`): `all_cards()` 에 토큰 **0장**, `get(46647145)` 는 정의를
돌려준다, `token(69811710)` 은 `None`.

### 2.4 토큰은 "스크립트를 못 읽은 카드" 가 아니다

`special_summon_restriction_signals` 는 세 값이다 — `None`(스크립트가
없다) · `()`(끝까지 읽었고 없다) · 비어 있지 않음(찾았다). 토큰에는 **카드
텍스트가 없고** 스크립트가 존재하지 않으므로 (실측 HTTP 404, 그리고 `type`
비트가 `TYPE_NORMAL`), 답은 **`()`** 다.

🔴 **이 갈래가 없으면** 토큰이 필드에 놓인 것만으로 그 뒤의 모든 특수 소환
판정이 `UNDETERMINED` 가 된다 — 규칙이 막지 않는 판이 **엔진 미지원**으로
집계되는 자리다. 스크립트가 없는 **다른** 효과 카드는 여전히 `None` 이다
(`test_a03` 이 그것을 함께 센다).

### 2.5 링크 소재 — 장수와 **기여**를 가른다

🔴 **이 절은 Phase 6-AG 가 정정했다.** 6-AF 가 여기에 적었던 문장은
공식 규칙의 **절반**이었고, 그 절반이 판정 코드에 그대로 들어가 두 가지를
동시에 틀리게 만들었다. 정정된 내용과 실측은 **§7 후속 보완**에 있다.
아래는 정정된 사실이다.

공식 규칙 (`rules` 계층의 `sd-rulebook-en-v10`, RULE-SUMMON-002) —
*"Normally, 1 monster equals 1 Link Material. But when you use a Link
Monster as material for another Link Summon, you can count it as either
1 monster, or as a number of monsters equal to its Link Rating."*

`material_contribution_options` 가 그 **고를 수 있는 값들**을 돌려준다.

| 소재 | 고른 카드 | **기여로 고를 수 있는 값** |
| --- | --- | --- |
| 기르수 (비링크) | 1장 | `{1}` |
| 성유물 토큰 (비링크) | 1장 | `{1}` |
| 갈라테아i (LINK-1) | 1장 | `{1}` (두 값이 같다) |
| 갈라테아 (LINK-2) | 1장 | **`{1, 2}`** |
| 롱기르수 (LINK-3) | 1장 | **`{1, 3}`** — 사이의 `2` 는 **없다** |

그리고 공식 규칙은 **두 조건을 따로** 센다 (RULE-MONSTER-005 의 "3 goals"):
고른 **카드 장수**는 `LinkMaterialRule.count` 가 받고, **기여의 합**은
`LinkMaterialRule.link_rating` 이 받는다. 두 수를 한 수로 비교하면 안 된다 —
6-AF 가 그렇게 했고 §7 이 그 결과를 적는다. 읽을 수 없으면 `None` 이고
**`{1}` 로도 빈 집합으로도 접지 않는다** (앞은 링크 몬스터를 조용히 1 로만
세고, 뒤는 모름을 확정 거절로 바꾼다).

🔴 **6-AD 까지 이 자리는 `UNDETERMINED` 였다** (`LINK_MATERIAL_AS_LINK_RULE`
이 그 이름이었다). 그 이름은 **남겨 두었다** — 기여 수치를 세도 소재 장수가
**범위**인 링크 몬스터는 여전히 등록할 수 없다.

### 2.6 턴당 링크 소환 제한 — 왜 새 표인가

필요한 사실은 "이 턴에 P{x} 가 그 **카드명**을 링크 소환했는가" 다. 기존 표
둘로는 담을 수 없다.

| 표 | 무엇을 세는가 | 왜 안 되는가 |
| --- | --- | --- |
| `RuleUsageRegistry` | **규칙이** 주는 권리 (소환권 · 공격권) | 카드별 열쇠가 `instance_id` 다 — 같은 이름 두 장이 조용히 통과한다 |
| `UseRegistry` | **효과의** 1턴 1회 | 갈라테아i 의 ① 이 `(player, 48835607)` 칸을 **이미 쓴다** — 같은 칸에 적으면 ① 을 쓴 것이 재소환을 막고 그 반대도 일어난다 |

그래서 `SummonUsageRegistry` 를 더했다 — 열쇠가
`(턴, 플레이어, card_id, 소환법)` 이고, `GameState.summon_uses` 에 살고,
`GameStateView.summons_by_name` 으로 관측에 실린다 (ADR-007: 판정은 관측만
읽는다). **세기만 하고 판정하지 않는다** — 판정은
`LINK_SUMMON_ONCE_PER_TURN` 과 `assess_link_materials` 가 한다.

### 2.7 발동 자리를 적었다 — 거짓 모름 하나를 지웠다

6-AF 가 이 저장소의 **첫 기동 효과를 메인 덱 몬스터에** 등재했다. 그러자
같은 카드가 **묘지 · 덱**에 있는 판마다 그 효과의 발동이
`ignition-effect-location` 으로 보류되었다 — 실측으로 **기존
`orcust-girsu` 경로의 미지원 사유가 2건 → 3건**이 되었다.

그 모름은 **이 카드에 대해서는 거짓이다.** 공식 스크립트가
`e3:SetRange(LOCATION_MZONE)` 라고 적어 두었으므로 묘지에서의 발동은 규칙이
막는 것이다. 그래서 `EffectDefinition.activation_zones` 를 더했다 — 적은
효과는 자리를 **확정 판정**으로 받고(`SOURCE_WRONG_ZONE`), **적지 않은
효과는 한 글자도 바뀌지 않는다** (ADR-006).

실측: 그 칸을 적은 뒤 기존 경로의 미지원 사유가 **2건으로 돌아왔다.**

### 2.8 지원하지 **않는** 것 — 이름으로 막는다

| 이름 | 무엇인가 | 어떻게 되는가 |
| --- | --- | --- |
| `token-to-deck-or-hand` | 토큰을 덱 · 패 · 엑스트라 덱으로 | `token_operation_refusal` 이 **거절한다** |
| `token-as-overlay-or-equip` | 토큰을 엑시즈 소재 · 장착으로 | 같다 |
| 토큰에 걸리는 카드명 · 종류 범위 제약 | `IsPlayerCanSpecialSummonMonster` 의 토큰 부분 | `TOKEN_OPERATION_BLIND_SPOTS` · `SUMMON_RESTRICTION_BLIND_SPOTS` 에 이름으로 남는다 |
| `simultaneous-summon-prohibition-scan` | 같은 금지를 등록하는 다른 카드 | 전수 조회 불가 (§1.3) — 이름으로 남는다 |
| `token-card-data` | 공식 데이터를 읽지 않은 토큰 | `UNSUPPORTED_OPERATION` 으로 **거절한다** |
| `link-material-link-rating` | 소재 장수가 **범위**인 링크 몬스터 | 등록하지 않는다 (§2.5) |
| `Duel.SpecialSummonComplete` 의 동시 처리 | 두 토큰의 동시성을 사건으로 적기 | 계층이 없다 — 한 조작 안에서 **전부 아니면 무**까지만 옮겼다 |
| 주인과 컨트롤러가 다른 토큰 | 컨트롤이 옮겨진 뒤의 토큰 | `create_token` 이 `TokenError` 로 **거절한다** (아래) |

🔴 **컨트롤러를 따로 세우는 길을 두지 않았다.** `plan_token` 은 `owner` 와
`controller` 를 같은 값으로 세우고 (놓이는 쪽이 주인이다), `create_token` 은
둘이 다르면 거절한다. 「컨트롤이 주인과 다른 토큰」을 조용히 허용하는 대신
막는 쪽을 골랐고, 그래서 `engine/token.py` 는 **컨트롤을 옮기는 호출을 하지
않는다** (`tests/test_trigger_actor_consistency.py::test_08` 이 그 사실을
저장소 전체에서 센다 — 이 Phase 가 그 감사를 깨지 않는다).

🔴 **미지원을 허가로 바꾸지 않았다.** 판정하지 못한 특수 소환 금지는 그대로
`UNDETERMINED` 이고 (`test_b07`: 「오르페골 디베르」가 그 예다), 그 판에서
토큰 효과는 **발동되지 않는다.**

---

## 3. 실제로 돈 경로와 최종 판

```
/combo hand:69811710,703897,2930675,12989604,55051920 line:orcust-girsu-token recipe:…
```

| 걸음 | 행동 | 결과 |
| --- | --- | --- |
| 1 | `normal_summon` 69811710 | 수락 · 상태 변경 |
| 2 | `pass` | 기르수 ① 의 발동 기회를 **지나간다** |
| 3 | `activate_effect` `69811710:e[2]` | 수락 · **조작 수행** · 토큰 2장 |
| 4 | `link_summon` 48835607 ← 토큰 | 수락 · 토큰 **소멸** |
| 5 | `link_summon` 30741503 ← 기르수 + 갈라테아i | 수락 |

`line_progress` = **4/4단계**.

🔴 **기르수 ① 을 지나간 것이 조용하지 않다.** ① 은
`EFFECT_TYPE_TRIGGER_O` 이므로 발동하지 않는 것이 적법하고, 그 사실이
실행 기록의 `pass` 걸음으로 남는다. 경로가 **무엇을 지나가는지 선언**하고
(`ComboLine.declines`), 적히지 않은 발동 후보가 열려 있으면 정책은
`None` 을 돌려주고 실행이 멈춘다 — 조용히 넘기면 "경로가 돌았다" 가
"다른 선택을 몰래 했다" 를 숨긴다.

### 최종 판 (실측, `test_e01` 이 고정한다)

| | 자신 (P0) | 상대 (P1) |
| --- | --- | --- |
| 몬스터 존 | **비어 있다** | **`46647145` 성유물 토큰 — 남는다** |
| 엑스트라 몬스터 존 | **`30741503` 오르페골 갈라테아** | 비어 있다 |
| 묘지 | `48835607` · `69811710` (실제 이동 기록) | 비어 있다 |
| 패 | 4장 | 0장 |
| 남은 덱 | 35장 (40 − 5) | 40장 |
| 엑스트라 덱 | 4장 (6 − 2) | — |

* 🔴 **자신의 토큰은 소멸했고 묘지에 없다.**
* 🔴 **상대의 토큰은 남는다** — 공식 효과가 그렇게 적는다. 이 경로가 그것을
  이득으로 주장하지 않는다.
* 사용 제한 기록: `uses.per_effect == {(0, 69811710, 2): 1}` 이고
  `uses.per_card_name == {}` — ③ 을 쓴 턴에도 ① 의 칸은 **비어 있다.**
* 소환 기록: `summon_uses` 에 `48835607:link` 1 · `30741503:link` 1.

### 기존 경로는 그대로다

`orcust-girsu` 가 **4/4** 이고 최종 판도 같다 (엑스트라 몬스터 존에
갈라테아, 묘지 3장). 토큰은 **하나도 만들어지지 않는다** — 그 경로는 ③ 을
쓰지 않는다. Discord 출력도 **바이트까지 같다**: 2메시지 1,929 + 89자 ·
첨부 `combo-detail.txt` **14,891바이트** · 누락 0줄 (6-AE 의 실측과 동일).

새 경로의 출력: **1메시지 1,941자** · 첨부 **14,017바이트** · 누락 0줄.

---

## 4. 검증

### 실행한 명령과 결과

```
python3 -m pytest tests/test_girsu_token_line.py -q -rf
python3 -m pytest tests/engine/test_monster_effect_activation.py \
    tests/engine/test_card_movement_origin.py \
    tests/test_orcust_girsu_line.py \
    tests/test_summon_prohibition_and_resolution_choice.py \
    tests/test_combo_output_consistency.py -q -rf
```

| 묶음 | passed | failed | 종료 코드 | 소요 |
| --- | --- | --- | --- | --- |
| `tests/test_girsu_token_line.py` (새 시험) | **36** | **0** | **0** | 0:44 |
| 고친 기존 시험이 든 다섯 파일 — **고치기 전** | 167 | **12** | 1 | 5:15 |
| 같은 다섯 파일 **+ 새 시험** — **고친 뒤** | **215** | **0** | **0** | 6:15 |

🔴 **고친 뒤의 다섯 파일을 새 시험과 **함께** 돌렸다** — 따로 돌리면 "서로를 깨지 않는가" 를 재지 못한다.

### 4.1 새 시험 36건이 무엇을 재는가

| 묶음 | 재는 것 |
| --- | --- |
| **A** (5) | ordinal · 토큰 ID · 토큰 데이터 대조 · 토큰의 `()` 신호 · 검색 목록 불변 · 발동/해결 조건 분리 · 사용 제한 열쇠 분리 |
| **B** (8) | 양쪽 토큰 생성 (표시 형식 · 컨트롤러 · 개체 번호 · 장수 불변) · 해결자와 컨트롤러 분리 · 실제 소환 사건 · 자기 필드에 다른 몬스터 → 거절 · 한쪽 존 꽉 참 → 거절 (한 장도 만들지 않는다) · 확인된 특수 소환 금지 → 거절 · 동시 다수 금지 (한 장은 막지 않는다) · 판정 못한 제약 → `UNKNOWN` · 같은 턴 재사용 거절 + ① 의 칸 불변 |
| **C** (5) | 토큰 소멸 + **허위 묘지행 사건 없음** · 상대 토큰은 내 소재가 아니다 · 미지원 토큰 조작 차단 · 모르는 개체는 소멸시키지 않는다 · 원본/사본 격리 |
| **D** (5) | 토큰은 갈라테아i 를 만족하고 갈라테아를 만족하지 않는다 (판정과 실행이 **같은 답**) · 링크 수치 기여 · 비워진 엑스트라 몬스터 존 · 갈라테아i 턴당 1번 · 중복 소재와 미등록 소재의 구분 |
| **E** (5) | **전체 경로 4/4 와 최종 판** · 지나간 발동 기회가 기록에 남는다 · 레시피에 패와 엑스트라 덱이 실제로 있다 · **기존 경로 4/4 유지** · 두 경로가 따로 등록되었다 |
| **F** (3) | 발동 뒤 다른 몬스터가 생겨도 토큰이 만들어진다 · 해결 시점 조건이 거짓이면 **정상 불발** · 공식 데이터 없는 토큰은 거절 (**격리 등록소**) |
| **G** (4) | 새 일이 계획기·수행기와 함께 등록되었다 · `link_rules` 가 효과 계층을 모른다 · 소환 기록 표가 따로다 · `engine/token.py` 에 카드 ID 분기가 없다 |
| **H** (1) | Discord 요약과 상세가 같은 전개를 적는다 (전송은 하지 않는다) |

🔴 **합성 효과는 격리 등록소에만 넣었다** (`F`). production 의
`EFFECT_LIBRARY` 는 한 줄도 바뀌지 않고, `test_f03` 이 그것을 함께 센다.

🔴 **실행 중에 판정 결과를 주입하지 않았다.** `F` 묶음은 **판을 직접 바꿔
해결 직전 상태를 만들고** 그 판에서 엔진이 내는 답을 읽는다 — 초기 상태
구성은 허용되고, 판정 주입은 하지 않았다.

### 4.2 기존 시험 중 **고친 것** — 뜻을 적어 두었다

이 Phase 가 **들어 올린 한계**를 측정으로 적어 두었던 시험들이다. 단언을
지우거나 기대값을 완화한 것이 아니라, **측정값을 지금의 사실로 고치고 왜
바뀌었는지 적었다.**

| 시험 | 전 | 후 |
| --- | --- | --- |
| `test_monster_effect_activation::test_b04` | 분류를 적은 등재 3건 | **4건** (기르수 ③ 기동) |
| `…::test_m02` (이름도 바꿨다) | 기르수 ③ 은 "분류를 적지 않았다" | ③ 은 **등재되었고**, **②(`e[1]`) · ④(`e[3]`) 는 여전히 모른다** — "등재한 ordinal 만 열린다" 가 지키는 사실이고 그것은 그대로다 |
| `test_orcust_girsu_line::test_b04` · `b05` · `e01` | 미등록 예시가 갈라테아i | 예시를 **롱기르수**(76145142, 여전히 미등록)로 바꿨다 — 재는 사실은 "미등록은 `UNKNOWN`" 이고 특정 카드가 아니다 |
| `…::test_b07` (이름도 바꿨다) | 링크 몬스터 소재는 `UNDETERMINED` | **기여를 센다** — 기르수 + 갈라테아i = 2장으로 `LEGAL` |
| `…::test_b10` | 등록된 소재 조건 1건 | **2건** (갈라테아i) |
| `…::test_d03` | 제한을 적은 효과 2건 | **3건** (기르수 ③) |
| `…::test_g04` | `COMBO_LINES` 가 1개 | **2개** (기존 이름 그대로) |
| `test_summon_prohibition…::test_h10` | 금지 표 2줄 | **3줄** (갈라테아i — `prohibits=False` 와 그 뜻을 적었다) |
| `test_card_movement_origin::test_k01` | `OperationKind` 13개 | **14개** (`create_token`). 🔴 **이동 목적지 표는 그대로다** — 그것이 이 시험이 지키는 사실이다 |
| `…::test_k02` | 등재 19 · 실행 16 | **20 · 17** |

🔴 **`test_j01_tokens_are_not_in_the_engine_at_all` 은 고치지 않았다 —
그대로 통과한다.** 그 시험이 재는 것은 "저장소의 **목록**에 토큰이 없다" 와
"production 이 `include_tokens=True` 를 쓰지 않는다" 이고, 둘 다 여전히
참이다 (§2.3).

### 4.2-추가 전체 묶음이 드러낸 **97건** — 전부 고쳤다

🔴 **이 Phase 를 커밋한 시점에 §4.3 은 "측정이 끝나지 않았다" 고 적고
있었다.** 측정이 끝나자 **106건**이 실패했고, 그중 **9건**은 기준선의 기존
실패였다. 남은 **97건**이 이 Phase 때문에 깨진 것이고, 아래가 그 전부와
고친 방법이다.

**기존 실패 9건을 가려낸 방법** — 추정이 아니라 측정이다. 기준선
(`8242ccd`) 을 별도 worktree 로 떼어 내고 (`data/` 는 심볼릭 링크로 공유)
**실패한 106건만** 그 worktree 에서 돌렸다:

```
git worktree add <scratch>/base 8242ccd
python3 -m pytest <실패한 106건> -q -rf -p no:randomly   # → 9 failed, 97 passed
```

9건은 기준선에서도 같은 자리에서 실패하고 97건은 통과한다. 그래서 97건이
이 Phase 의 것이다.

| # | 원인 | 무엇이 움직였나 | 고친 방법 |
| --- | --- | --- | --- |
| 1 | 등재 수 스냅샷 **(34)** | `len(EFFECT_LIBRARY)` 19 → **20** 과 같은 시험 안의 파생 수치 (실행 16 → 17 · 발동 조건 10 → 11 · 몬스터 3 → 4 · `kind` 분포 · `ordinal` 집합 `{0,1}` → `{0,1,2}`) | 수를 고치고 🔴 주석으로 **무엇이 늘었는지** 적었다. 단언은 하나도 지우지 않았다 |
| 2 | `EffectDefinition` 칸 수 **(8)** | 14 → **16** (`activation_zones` · `resolution_condition`) | 수를 고치고, 두 칸이 **사건 칸이 아니다**는 근거를 적었다 (`SetRange` 의 자리 집합 · 해결 함수의 재검사). 칸 이름 목록 셋에도 두 이름을 넣었다 |
| 3 | 거부 생성 수 **(3)** | `REJECTION_PRODUCTIONS` 73 → **75** · `CODE_OCCURRENCES` 86 → **88** · `ENGINE_FILE_COUNT` 73 → **75** | `_plan_create_token` 의 `RULE_NOT_IMPLEMENTED` 둘과 새 모듈 둘이다. **"차이가 13" 은 그대로다** |
| 4 | 문자열 등장 수 **(2)** | `RULE_NOT_IMPLEMENTED` 123 → **125** | 같은 둘. 코드 수는 움직이지 않았다 |
| 5 | 모듈 폐쇄 수 **(1)** | 63 → **65** (`engine.token` · `engine.state.summon_usage`) | 늘어난 둘이 휴면 모듈이 아니라는 근거를 적었다. 휴면 넷은 그대로 폐쇄 밖이다 |
| 6 | 줄 번호 스냅샷 | `CONTRACT_VIOLATIONS` 7자리 · `PROSE_OCCURRENCES` 2자리 | **번호만** 옮겼다. 위반 13 · 산문 37 은 그대로이고, 그것이 "성격도 개수도 바뀌지 않았다" 의 증거다 |
| 7 | 조작 종류 집합 **(5)** | `create_token` 이 `SUPPORTED` · 실제 카드가 쓰는 종류 · 열거 고정 집합에 더해졌다 | 이름을 더하고 **특수 소환이 아니다**는 것을 적었다 — 그래서 "특수 소환하는 등재는 하나" 가 그대로다 |
| 8 | 조건 · delta 어휘 **(4)** | 공용 조건 17 → **18** (`SimultaneousSpecialSummonPermitted`) · 구상 delta 12 → **14** (`TokenCreated` · `TokenVanished`) | 이름을 더하고, 둘 다 **판만 묻고 사건을 묻지 않는다**는 것을 함께 쟀다. delta 둘은 `CardMovement` 가 아니므로 시점 이름이 없고 `actor` 가 `None` 이다 |
| 9 | **기동 효과가 실제로 후보로 오른다 (8)** | 필드의 기르수가 `activate_effect` 를 올린다 — 전에는 하나도 오르지 않았다 | 🔴 **가장 조심한 묶음이다.** `"activate_effect" not in kinds` 를 지우지 않고, 그 시험들이 **실제로 재던 사실**로 좁혔다: 올라온 `effect_ref` 가 `EffectRef(GIRSU, 2)` **하나뿐**이고 유발 ①(`ordinal 0`)은 없다. 공유 헬퍼 `_trigger_action` 에는 `ordinal=0` 기본값을 더했다 — 카드를 지목하던 이유가 그대로 ordinal 에도 적용된다 |
| 10 | `state_hash` 2건 | `GameState.canonical_state()` 에 `summon_uses` 가 실렸다 | 해시를 **실측값으로** 갱신하고 원인을 적었다. 같은 시험의 합법 행동 · 보류 · 사유 · 난수 단언은 하나도 달라지지 않았다 |
| 11 | 한국어 덮어쓰기 2건 | `korean_source.apply()` 를 버리는 자리가 1 → **2** (같은 파일) | 토큰 표도 한국어 이름을 받는다. **경계는 그대로다** — 자리가 든 파일은 여전히 하나다 |
| 12 | 발동 자리 관문 3건 | `_activate_effect` 가 `SOURCE_WRONG_ZONE` 을 낸다 | 🔴 **추측이 아니라 선언으로만** 낸다 — `activation_zones` 를 적어 둔 효과에만 `InAnyZone` 요구가 붙고, 적지 않은 효과는 6-AF 전과 한 글자도 다르지 않다. 그 사실을 단언으로 적었다 (`count == 1` + `"activation_zones" in …`) |
| 13 | `engine/state` 의 "summon" 2건 | `summon_usage.py` 가 생겼고 관측에 `summons_by_name` · `summons_of` 가 생겼다 | 🔴 **이 Phase 가 사실을 바꿨다**고 적었다. 그러나 그 시험들이 재던 핵심은 그대로다 — `CardInstance` · `PreviousState` 에는 소환 종류 칸이 **여전히 없고** `RuleActionKind` 에 `special_summon` 이 **여전히 없다** |
| 14 | 공식 Lua 인용 1건 | `PHASE_END` 가 `link_rules.py` · `summon_restriction.py` 의 **문자열**에 들어갔다 | 인용은 근거이고 읽는 코드가 아니다. 감사를 느슨하게 하는 대신 **더 좁게** 쟀다 — 그 두 파일에서 그 이름이 **식별자로 등장하는 자리는 0** 이고 전부 문자열 리터럴 안이다 |
| 15 | diff 범위 감사 2건 | `git diff <옛 Phase 의 base> HEAD -- core/card_repository.py` 가 비지 않았다 | 🔴 **감사 자신이 틀린 것을 쟀다.** docstring 은 "이 Phase 가 바꾸지 않았다" 고 적는데 범위가 `HEAD` 라서 **그 뒤 누가 바꿨는가**를 쟀다. 파일을 목록에서 빼지 않고 **범위를 그 Phase 의 commit 으로** 좁혔다 (`base` → `shas[0]`) |
| 16 | 그 밖의 파생 | `card_ids` · `codes` 분포 · `per_card` 분포 · `resolution_skip` 선언 수 · `missing_rules` override 수 · `ACTIVATION_FROM_SET_TARGET` 의 `card_id → ordinal` 사전 | 전부 **한 카드가 블록 둘을 등재한 첫 사례** 때문이다. 사전으로 가를 수 없는 자리는 **등재 항목을 그대로** 들고 다니게 고쳤다 |

괄호 안의 수는 **그 사유가 처음 걸린 시험 수**다 (한 시험이 사유 둘 이상에
걸린 경우도 있어 합이 97 과 정확히 같지는 않다).

#### 이 뒤에 production 을 두 군데 고쳤다

| 파일 | 고친 것 | 왜 |
| --- | --- | --- |
| `engine/effect/definition.py` | 새 두 칸의 주석을 **문자열 표기에서 보통 표기로** (`"Condition \| None"` → `Condition \| None`) | 나머지 다섯 `Condition \| None` 칸과 표기가 달라 전수 주사가 그 칸을 다른 것으로 읽었다. `from __future__ import annotations` 가 있으므로 동작은 같다 |
| `engine/token.py` | 컨트롤을 옮기는 호출을 **거절로** 바꿨다 | 그 갈래는 지금 경로에서 **한 번도 돌지 않는** 죽은 코드였고(`owner == controller`), 저장소 전체에서 "컨트롤 이동은 표현되지 않는다" 를 세는 감사가 있다. 조용히 허용하는 대신 막고 범위에 적었다 (§2.8) |

### 4.3 전체 묶음

(아래 수치는 이번 작업에서 실제로 돌린 결과다. 기준선의 **기존 실패
9건**은 이 Phase 전부터 실패하고 있었고 이 작업과 무관하다:
`rulings/test_data_audit::test_every_repository_card_can_reach_a_cid` ·
`agent/test_opponent_resource_weighting_audit::test_07` ·
`test_effect_type_quick_audit::test_29` ·
`test_event_free_chain_semantic_audit::test_27` ·
`test_korean_overlay_unapplied_audit::test_01/13/21/25` ·
`test_trigger_lifetime_audit::test_02`.)

```
python3 -m pytest tests -q -rf -p no:randomly          # 전체
python3 -m pytest <그 106건> -q -rf -p no:randomly      # 기준선 worktree 에서
```

| 묶음 | passed | failed | 종료 코드 | 소요 |
| --- | --- | --- | --- | --- |
| 전체 (`tests`) — **고치기 전** | 6833 | **106** | 1 | 1:47:37 |
| 그 106건 — **기준선 `8242ccd` worktree** | 97 | **9** | 1 | 1:42 |
| 그 97건 — **고친 뒤** | **97** | **0** | **0** | 1:18 |
| `tests/test_girsu_token_line.py` — 고친 뒤 | **36** | **0** | **0** | 0:50 |
| 전체 (`tests`) — **고친 뒤** | **6930** | **9** (기존 실패 그 9건) | 1 | 1:46:12 |

🔴 **마지막 줄은 이 보고서를 쓴 뒤에 끝난 실측이다** (1시간 46분짜리
묶음이다). 10건은 `skipped` 다. **종료 코드가 1 인 이유는 남은 실패
9건**이고, 그 9건은 위에 이름을 적어 둔 **기준선의 기존 실패와 정확히 같은
9건**이다 — 더도 덜도 아니다:

```
FAILED tests/agent/test_opponent_resource_weighting_audit.py::test_07_…
FAILED tests/rulings/test_data_audit.py::test_every_repository_card_can_reach_a_cid
FAILED tests/test_effect_type_quick_audit.py::test_29_…
FAILED tests/test_event_free_chain_semantic_audit.py::test_27_…
FAILED tests/test_korean_overlay_unapplied_audit.py::test_01_… / test_13_… / test_21_… / test_25_…
FAILED tests/test_trigger_lifetime_audit.py::test_02_…
```

🔴 **`6833 + 97 = 6930` 이 맞는다.** 고치기 전 통과 6833건에 이 Phase 가
깨뜨렸던 97건이 되돌아온 수다. 즉 **97건을 고치면서 그 전에 통과하던
시험을 하나도 떨어뜨리지 않았다**. 그리고 이 수는 기준선 worktree 측정이
"97건이 이 Phase 의 것"이라는 분류를 뒤에서 한 번 더 확인한다 — 추정이
아니다.

🔴 **고치기 전 12건의 실패를 숨기지 않았다** — 전부 §4.2 의 표에 어느
시험이 왜 바뀌었는지 적혀 있고, 단언을 지우거나 기대값을 완화한 것이
아니다.

---

## 5. 남은 한계

1. **소재 장수가 범위인 링크 몬스터**를 등록할 수 없다 — 기여 수치를 세도
   `LinkMaterialRule.count` 가 정확한 한 수이기 때문이다 (고르는 계층이
   없다).
2. **토큰을 덱 · 패로 되돌리는 처리**와 **엑시즈 소재 · 장착**은 거절된다 —
   공식 규칙은 그때도 토큰을 소멸시키지만 그 경로를 옮기지 못했다.
3. **동시 다수 특수 소환 금지의 전수 확인이 불가능하다** (§1.3) — 파싱
   캐시가 `SetCode(id)` 의 숫자 코드를 적지 않는다.
4. **`TokenVanished` 에 옮길 시점 이름이 없다** — `UNIMPLEMENTED` 사건으로
   남는다. 「토큰이 필드를 떠났을 경우」 를 묻는 카드는 아직 없다.
5. **`Duel.SpecialSummonComplete` 의 동시성**을 사건으로 적는 계층이 없다 —
   한 조작 안에서 전부 아니면 무까지만 옮겼다.
6. **기르수 ② (`e[1]`) · ④ (`e[3]`) 는 여전히 등재되지 않았다** — ② 는
   `EVENT_SPSUMMON_SUCCESS` 사본이고 ④ 는 `EFFECT_ADD_TYPE`(튜너 추가)
   이며, 그 둘을 등재하지 않은 것이 지금 사실이다.
7. **갈라테아i 의 ① (덱 서치) · ② (묘지 자기 소생) 도 등재되지 않았다.**
   이 경로는 그 카드를 **소재로만** 쓴다.
8. **토큰에 걸리는 카드명 · 종류 범위 제약**을 읽는 계층이 없다 (§2.8).
9. **주인과 컨트롤러가 다른 토큰**은 만들지 못한다 — `create_token` 이
   거절한다 (§2.8). 컨트롤 이동 자체가 이 저장소에 없다.

---

## 6. 붙여 넣을 입력

```
/combo hand:69811710,703897,2930675,12989604,55051920 line:orcust-girsu-token recipe:<아래 레시피>
```

경로 이름: `orcust-girsu-token`
시작 패: `69811710,703897,2930675,12989604,55051920`

레시피는 `deck.combo_policy.ORCUST_VERIFICATION_RECIPE` 와 **같은 것**이다
(기존 경로와 레시피를 공유한다 — 두 경로가 같은 덱에서 갈린다는 것이 이
Phase 가 보이려는 것이다). 사람이 읽는 모양은
`ORCUST_VERIFICATION_RECIPE_KO` 에 있다.

```
#main
69811710
69811710
69811710
93920420
93920420
93920420
57835716
57835716
57835716
21441617
21441617
21441617
94046012
94046012
94046012
40441990
40441990
40441990
2930675
2930675
2930675
90351981
90351981
90351981
26845680
26845680
26845680
61654098
61654098
61654098
703897
703897
703897
12989604
12989604
12989604
55051920
55051920
47171541
47171541
#extra
30741503
48835607
76145142
93854893
74820316
3134857
```

🔴 **금제를 확인하지 않았다** — 확인한 금지 · 제한 목록도 그 날짜도 이
저장소에 없으므로 "대회 합법 덱" 이라고 부르지 않는다. 이것은 **검증
자료**이고 추천 덱이 아니다.

---

## 7. 후속 보완 (Phase 6-AG) — 링크 소재 판정 정정과 실제 체인 검증

외부 검토가 두 가지를 짚었다. 둘 다 **재현했고**, 고쳤고, 실측을 아래에
적는다.

### 7.1 재현한 문제와 원인

원인은 **한 줄**이다. `engine/link_rules.py` 의 `assess_link_materials` 가
기여의 합을 `LinkMaterialRule.count` 와 **직접 비교**했다.

```python
    contributed = 0
    for instance in materials:
        ...
        contributed += material_contribution(found)   # 링크 수치로만 센다
    if contributed >= 0 and contributed != rule.count:   # 🔴 장수와 비교한다
        return _illegal(f"소재가 {contributed}장입니다 ...")
```

여기에 **두 개의 서로 다른 혼용**이 겹쳐 있었다.

1. **`material_contribution` 이 링크 수치로만 셌다.** 공식 규칙은
   *"you can count it as **either 1 monster, or** as a number of monsters
   equal to its Link Rating"* 이고 (RULE-SUMMON-002), 고르는 쪽이 1 을
   택할 수 있다. 그 선택지를 잃었다.
2. **`count`(장수)와 기여의 합을 한 수로 비교했다.** 공식 규칙은 두 조건을
   **따로** 적는다 (RULE-MONSTER-005 의 "3 goals" — §2.5).

재현 실측 (수정 **전**, `8242ccd` 이후의 `5c099a2`):

| # | 판 · 소재 | `assess_link_materials` | 후보 생성 | `Duel.apply` |
| --- | --- | --- | --- | --- |
| 1 | 기르수 + 갈라테아(LINK-2) → 다른 갈라테아 | **`illegal`** "소재가 3장입니다 (고른 카드 2장, 링크 수치로 환산한 소재 장수 3장)" | **0건** | 거절 |
| 2 | 갈라테아 한 장 → 다른 갈라테아 | **`legal`** 🔴 | 그 조합을 만들지 않음 | 거절 — **다른 사유**로 ("필드의 몬스터가 1장이라 소재 2장을 고를 수 없습니다") |
| 2b | 같은 판에 기르수가 **있는데** 갈라테아만 고름 | **`legal`** 🔴 | — | — |
| 3 | 롱기르수(LINK-3) 한 장 → 갈라테아 | `illegal` 이지만 사유가 **"소재가 3장입니다"** — 기여를 장수로 읽은 문장 | — | — |
| dup | 기르수를 **두 번** 고름 → 갈라테아 | **`legal`** 🔴 | — | `PlayerAction` 이 `MalformedAction` 으로 막음 |

🔴 **한 장 소환이 실제로 적용된 적은 없다.** 사례 2 는 `Duel.apply` 가
거절했다. 그러나 그 거절은 **소재 판정의 답이 아니었다** — 후보 생성이 그
조합을 만들지 않았기 때문의 "허가된 행위가 아니다" 였다. 즉 **판정 계층과
실행 계층의 답이 달랐고**, 판정을 직접 부르는 길(검증기 · 보고 계층)에는
그 방어막이 없었다. 그것이 이번에 고친 것의 절반이다.

### 7.2 실제 소재 장수와 링크 수치 계산의 분리

`LinkMaterialRule` 의 두 칸에 **각자의 일**을 주었다 (둘 다 이미 있던
칸이고, `link_rating` 은 판정에 **쓰이지 않고 있었다**).

| 칸 | 공식 조건 | 무엇을 세는가 |
| --- | --- | --- |
| `count` | 둘째 — *"The number of materials you use meets the number specified in the materials line or 'recipe'"* | **고른 카드 장수** (`len(materials)`) |
| `link_rating` | 첫째 — *"The amount of materials you use matches the Link Rating (Link Monsters count as 1 OR their own Link Rating)"* | **기여의 합** |

새 함수 둘이 첫째 조건을 센다.

- `material_contribution_options(definition) -> frozenset[int] | None`
  — 비링크는 `{1}`, 링크는 `{1, 링크 수치}`, 읽을 수 없으면 `None`.
  **사이의 값은 없다** (LINK-3 은 1 또는 3이고 2가 아니다).
- `reachable_material_counts(choices) -> frozenset[int]` — 선택들의 곱.
  "도달 가능한가"(참/거짓)가 아니라 **"무엇에 도달하는가"** 를 돌려준다 —
  거절 문장이 어디까지 갈 수 있었는지 적어야 하기 때문이다.

`material_contribution` 은 **지우지 않고** 뜻을 좁혔다 — `options` 의
**최댓값**이고, **판정은 그것을 쓰지 않는다.** 6-AF 가 이 값을 그대로
판정에 쓴 것이 결함이었으므로, 그 사실을 함수 docstring 이 적는다.

판정 순서도 세 조건으로 갈랐다 (`assess_link_materials`):

1. **중복** — 같은 개체를 두 번 고를 수 없다 (`PlayerAction` 과 **같은
   답**을 판정 자신이 낸다).
2. **고른 카드 장수** — 관측을 읽지 않으므로 (`len` 하나) 판을 못 읽는
   모름이 이 사실을 가릴 수 없다. 그래서 가장 먼저 둔다.
3. **카드별 조건** (`each` · `includes`) — 보이지 않는 소재와 못 읽는
   정의를 정확한 문장으로 거른다.
4. **기여의 합** — 3 을 지난 뒤이므로 정의가 전부 읽히고, 남은 `None` 은
   **링크 수치를 못 읽는 경우 하나**로 좁혀진다 → `UNDETERMINED` +
   `LINK_RATING_UNREADABLE_RULE`. 모름을 거절이나 허가로 바꾸지 않는다.

그리고 **달성할 수 없는 등록을 자료형이 막는다** — `link_rating < count`
는 `ValueError` 다. 소재 한 장의 최소 기여가 1 이므로 그런 줄은 어떤
조합도 소환하지 못하는 줄이고, 조용히 등록되면 "그 카드는 소환할 수 없다"
가 규칙이 아니라 오타로 들어온다.

🔴 **카드 ID 분기를 쓰지 않았다.** 고친 것은 두 수의 의미와 기여의 집합
뿐이고, 특정 조합을 위한 예외는 한 줄도 없다. 등록표
(`LINK_MATERIAL_RULES`)의 **값은 한 글자도 바뀌지 않았다** — 갈라테아
`count=2 · link_rating=2`, 갈라테아i `count=1 · link_rating=1` 그대로다.
바뀐 것은 그 두 수를 **어떻게 쓰는가**다.

### 7.3 후보 생성 · 검증 · 실행이 같은 기준을 쓰는가

| 계층 | 무엇을 쓰는가 | 6-AF | 6-AG |
| --- | --- | --- | --- |
| 후보 생성 (`Duel._link_summon_actions`) | `combinations(field, rule.count)` — **장수** | 이미 장수였다 | 그대로 |
| 검증 (`_LinkMaterialsLegal` → `assess_link_materials`) | 판정 함수 하나 | 기여 합을 **장수와** 비교 🔴 | 두 조건을 **각각** |
| 실행 (`Duel.apply` → 같은 검증기) | 같은 함수 | 같음 | 같음 |
| 직접 호출 (보고 계층 · 시험) | 같은 함수 | **중복을 막지 않았다** 🔴 | 판정이 막는다 |

즉 **후보 생성은 처음부터 장수로 세고 있었고**, 판정 함수만 두 의미를
섞었다. 그래서 사례 1 은 후보가 **0건**이었고 (조합은 2장으로 만들어졌는데
판정이 "3장" 이라며 전부 거절했다), 사례 2 는 판정만 `legal` 이었다.
`test_a01` 이 네 계층(판정 · 후보 · 검증기 · 실행)을 한 시험에서 함께
확인한다.

🔴 **소재의 순서는 규칙이 아니다.** `assess_link_materials` 는 순서를
묻지 않지만 `Duel.apply` 는 **자신이 낸 후보**만 실행하므로 손으로 만든
순서가 다르면 "허가된 행위가 아닙니다" 로 거절한다. 이것은 기존 설계이고
이번에 바꾸지 않았다 — 시험은 후보에서 찾아 넘긴다 (`_pick_link`).

### 7.4 실제 체인 통합 시험과 단위 시험의 구분

`tests/test_girsu_token_line.py` 의 `test_f01` · `test_f02` 는 **단위
검증**이다 — 해결 직전 판을 `state.move` 로 만들고 `executor.execute` 를
직접 부른다. 지우지 않았고 (해결 함수의 계약을 재는 자리로 쓸모가 있다),
**그렇게 적도록 머리말을 정정했다** (§7.6).

통합 검증은 새 파일 `tests/test_girsu_token_chain_integration.py` 가
들고 있다. 한 실행 안에서 **발동 수락 → 체인 등록 → 역순 해결 → 우선권
복귀**를 지난다.

🔴 **이 파일은 결함을 고친 것이 아니다.** 다섯 시험 전부 기준선
`5c099a2` 에서도 통과한다 (실측 — §7.5). 즉 6-AF 의 해결 시점 재검사
동작은 **이미 맞았고**, 없었던 것은 그것을 **실제 체인으로 확인하는
시험**이다. A 와 달리 production 코드는 한 줄도 바뀌지 않았다.

| 시험 | 체인 링크 1 | 체인 링크 2 | 기르수 ③ 의 해결 |
| --- | --- | --- | --- |
| `test_o01` | 기르수 ③ (자신 필드에 **다른 몬스터 없음**) | 함정 — 자신 필드에 몬스터 하나를 특수 소환 | **양쪽에 토큰** (발동 전용 절을 재검사하지 않는다) |
| `test_p01` | 기르수 ③ (상대 넷 + **빈 칸 하나**) | 상대의 함정 — 상대 필드의 마지막 칸을 채움 | **양쪽 모두 토큰 없음** — 정상 불발 |
| `test_p02` | 기르수 ③ (같은 시작 판) | 없음 | 양쪽에 토큰 — `test_p01` 의 **대조군** |

🔴 **왜 링크 2 가 함정인가.** 기동 효과 위에 무엇을 쌓으려면 스펠 스피드
2 가 필요하고, 이 저장소가 실제로 허가하는 자리는 **함정**이다 (6-Q).
유발즉시(`ActivationKind.QUICK`)로는 만들 수 없다 — 분류를 그렇게 적어도
공용 관문이 `UNKNOWN` 을 돌려준다 (룰북이 유발즉시의 발동 시점을 적지
않았다 — `ACTIVATION_KINDS_IN_SCOPE` · ADR-006). **미지원을 허가로 바꾸지
않았다.** 스펠 스피드 1 유발도 안 된다 — 지나간 사건에 걸린 것은 체인
응답 단계에서 `stage_forbids_action` 으로 막히고 (실측), 기르수 ③ 은
사건이 아니라 기동이므로 "같은 사건의 동시 유발" 길에도 들어가지 않는다.

🔴 **무엇이 합성인가.** 함정이 **하는 일**(특수 소환 한 장)만 합성이고,
카드 종류 · 스펠 스피드 · 발동 경로 · 체인 · 역순 해결 · 우선권은 전부
실제다. 합성 정의는 「욕망의 선물」 의 그 주소를 **갈아 끼운 격리
등록부**에 있고 (`duel_components(definitions=…)`), production
`EFFECT_LIBRARY` 는 한 줄도 바뀌지 않는다 — `test_n02` 가 그것을 센다
(production 의 그 효과는 여전히 `draw` 다).

🔴 **첫 행동 뒤에 판을 손으로 바꾸지 않는다.** 함정은 **뒷면으로 세워 둔
채** 시작 상태에 적고 턴 번호를 5 로 둔다 — 실제 `SET_SPELL_TRAP` 으로
세우면 「세트한 턴」 제약이 걸리고, 그것을 풀려고 턴을 손으로 넘기면 첫
행동 뒤에 판을 손으로 바꾸는 것이 된다.

### 7.5 실행한 명령과 실제 결과

#### 먼저 **기존 코드에서 실패하는** 시험으로 재현했다

🔴 **새 시험 파일을 그대로 기준선에 놓을 수는 없다.** A 파일은
`material_contribution_options` · `reachable_material_counts` 를 import
하므로 `5c099a2` 에서 **수집 자체가 실패한다** (`ImportError`) — "전부
실패한다" 고 적으면 거짓이다. 그래서 **기존 API 만 쓰는 재현 시험**
(`assess_link_materials` 하나로 §7.1 의 여섯 갈래를 단언한다)을 만들어
**같은 코드**를 두 commit 에서 돌렸다.

```
git worktree add <scratch>/base 5c099a2      # data/ 는 심볼릭 링크로 공유
git worktree add <scratch>/head HEAD
python3 -m pytest tests/test_ag_repro.py -q -rf -p no:randomly   # 양쪽에서
```

| 재현 시험 (동일 코드) | 기준선 `5c099a2` | 고친 뒤 |
| --- | --- | --- |
| `test_r1` 기르수 + 갈라테아 → 다른 갈라테아 (판정 + 후보 1건) | **FAILED** | passed |
| `test_r2` 갈라테아 한 장 → 다른 갈라테아는 불법 | **FAILED** | passed |
| `test_r2b` 다른 몬스터가 있어도 한 장만 고르면 불법 | **FAILED** | passed |
| `test_r3` 롱기르수 한 장의 거절 사유는 **장수** | **FAILED** | passed |
| `test_r4` LINK-3 을 **1 로 세는 길**이 열려 있다 | **FAILED** | passed |
| `test_r5` 중복 소재를 **판정 자신이** 막는다 | **FAILED** | passed |
| **합계** | **6 failed** (24.8초) | **6 passed** (25.7초) |

🔴 **이 재현 파일은 저장소에 넣지 않았다.** 같은 여섯 사실을 A 파일의
`test_a01`~`test_a05` · `test_b01` 이 **더 좁게** 단언하므로 (네 계층 일치 ·
판 보존 · 기여 집합) 두 벌을 들고 다닐 이유가 없다. 이 표는 "고치기 전에
실패하는 것을 보았다" 의 **실측 기록**이다.

🔴 **B 파일은 기준선에서도 통과한다 (5 passed, 3.5초).** 그래서 B 는
**결함 수정이 아니라 검증 추가**다 — 6-AF 의 해결 시점 재검사 동작은
이미 맞았고, 다만 **실제 체인을 지나는 검증이 없었다**. 그 사실을 그대로
적는다 (§7.4).

```
python3 -m pytest tests/test_link_material_count_and_rating.py -q -rf -p no:randomly
python3 -m pytest tests/test_girsu_token_chain_integration.py -q -rf -p no:randomly
python3 -m pytest tests/test_girsu_token_line.py tests/test_orcust_girsu_line.py \
                 tests/test_combo_brief_and_detail.py -q -rf -p no:randomly
python3 -m pytest <engine/link_rules.py 를 참조하는 21개 파일>            \
                 tests/test_girsu_token_chain_integration.py              \
                 tests/test_chain_state_change_between_links.py           \
                 tests/engine/test_trap_activation_free_chain.py          \
                 -q -rf -p no:randomly
python3 -m pytest tests -q -rf -p no:randomly
```

| 묶음 | passed | failed | 종료 코드 | 소요 |
| --- | --- | --- | --- | --- |
| 새 시험 `…_link_material_count_and_rating` | **13** | **0** | **0** | 0:03 |
| 새 시험 `…_girsu_token_chain_integration` | **5** | **0** | **0** | 0:03 |
| 검토가 지목한 3개 파일 — **고치기 전** | 113 | **1** | 1 | 4:54 |
| 직접 영향 24개 파일 — **고친 뒤** | **580** | **0** | **0** | 7:47 |
| 전체 (`tests`) — **고친 뒤** | §7.5-전체 | — | — | — |

🔴 **아직 적지 않은 수를 적어 두지 않는다.** 마지막 줄은 이 커밋 시점에
**측정이 진행 중**이다 (1시간 46분짜리 묶음이다 — §4.3 의 실측). 확실한
것은 위 네 줄이다.

🔴 **"고치기 전 1건" 이 무엇인지 적는다.** `test_girsu_token_line.py::
test_d02` 가 `assert "3장" in over.reason` 으로 **기여를 장수로 읽은 거절
문장**을 고정하고 있었다. 그 문장이 바뀐 것은 정당하다 — 롱기르수 한 장이
갈라테아의 소재가 되지 못하는 이유는 기여가 3이라 넘치는 것이 아니라 **고른
카드가 1장**이라는 것이다 (§7.1 사례 3). 단언을 지우지 않고 **더 좁게**
바꿨다: `"1장" in` · `"3장" not in` 에 더해 **두 장이면 합법**인 대조를
같은 시험에 넣었다 (6-AF 에서는 그 조합이 "4장" 으로 거절되었다).

🔴 **기존 두 전개가 유지된다** (필수 회귀 사례 5). 토큰 → 갈라테아i →
갈라테아 경로는 `test_girsu_token_line.py::test_e01`, 기존 『성장』 경로는
`test_e04` 와 `test_orcust_girsu_line.py` 전체가 들고 있고, 셋 다 고친 뒤
묶음에서 통과한다 — 새 시험을 더해 그 자리를 **대신하지 않았다**.

🔴 **직접 영향 묶음에 기존 실패가 없다.** 24개 파일 580건이 전부 통과하므로
이 범위에서는 "기존 실패와 신규 회귀" 를 가를 일이 없었다. 전체 묶음의
기준선은 `5c099a2` 에서 측정한 **기존 실패 9건**이고 (§4.3 에 이름이 적혀
있다), 전체 묶음의 결과는 그 9건과 대조한다.

### 7.6 정정한 설명

| 자리 | 6-AF 가 적은 것 | 정정 |
| --- | --- | --- |
| `engine/link_rules.py` 머리말 | (없었다) | 공식 3 조건과 두 수의 분리를 적었다 |
| `LINK_MATERIAL_AS_LINK_RULE` | "링크 몬스터를 소재로 쓰면 링크 수치**만큼** 센다" | "**1 또는** 링크 수치로 센다" + 룰북 인용 |
| `LinkMaterialRule.count` | "**정확히** 이 장수다" (무엇의 장수인지 적지 않았다) | "**고른 카드가** 정확히 몇 장이어야 하는가" + "기여의 합이 아니다" |
| `LinkMaterialRule.link_rating` | "카드 데이터의 링크 수치" (판정에 쓰이지 않았다) | "**기여의 합이** 정확히 맞춰야 하는 수" |
| `material_contribution` | "그 소재가 소재 장수로 몇 장으로 세어지는가" | "**최대로** 몇 으로 세어질 수 있는가 — **판정은 쓰지 않는다**" |
| `assess_link_materials` 의 장수 주석 | "장수 검사는 **기여의 합**으로 한다" | 두 조건을 각각 보는 순서를 적었다 |
| `…::test_d02` (이름) | `a_link_monster_counts_as_its_link_rating` | `…_counts_as_one_or_its_link_rating` |
| `…::test_d02` (단언) | `"3장" in over.reason` — 기여를 장수로 읽은 문장을 고정 | `"1장" in` · `"3장" not in` + **두 장이면 합법**인 대조 |
| `tests/test_orcust_girsu_line.py::test_b07` | 같은 "링크 수치만큼" | 이름과 설명을 정정하고 `options` 단언을 더했다 |
| `…::_board` docstring | "이 뒤의 변화는 **전부** 엔진이 만든다" | `F` 절은 그렇지 않다고 적고, 통합 시험의 자리를 가리킨다 |
| `…::test_f01` · `test_f02` | "판을 직접 바꿔 …" (단위인지 통합인지 불분명) | "**이것은 단위 검증이다 — 실제 체인 검증이 아니다**" + 대응 통합 시험 |
| 이 보고서 §2.5 | "링크 몬스터를 소재로 쓰면 그 링크 수치만큼 센다" | 룰북 인용과 **고를 수 있는 값 집합** 표 |

### 7.7 남은 미지원 범위

이번에 **열지 않은** 것들이다.

1. **소재 장수가 범위인 링크 몬스터** (`Link.AddProcedure` 의 `max` 가
   `nil`) 는 여전히 등록할 수 없다. `count` 는 정확한 한 수이고, 범위를
   지원하려면 "어느 장수로 소환할 것인가" 를 고르는 계층이 필요하다.
   🔴 **그래서 등록된 두 카드는 `count == link_rating` 이고**, 실제
   카드로는 **첫째 조건만 깨지는 판을 만들 수 없다** — `count` 장을
   고르면 합이 최소 `count` 이고 그 값이 곧 `link_rating` 이라 언제나
   도달한다. 그 갈래는 `link_rating > count` 인 **합성 규칙**으로만
   잴 수 있고, 새 시험 파일의 `B` 절이 그것이다 (`test_b03` · `test_b04`).
2. **유발즉시의 발동**은 여전히 `UNKNOWN` 이다 (§7.4). 체인 링크 2 를
   함정으로 만든 이유이고, 이번에 그 관문을 열지 않았다.
3. **「링크 소재로 할 수 없다」** 류의 지속 효과 제약은 여전히 못 본다
   (`LINK_MATERIAL_BAN_RULE` — §2.8 그대로).
4. **소재 순서**는 `Duel.apply` 가 자신이 낸 후보와 맞춰야 한다 (§7.3).
   순서를 규칙으로 보지 않는 판정과 그 설계의 간격은 그대로 남았다.
5. **탐색 · 평가 · 자동 레시피 · 외부 시뮬레이터**는 이번에도 시작하지
   않았다. 이 경로는 **등록된 한 전개를 엔진이 끝까지 실행한다**는 것이고
   자율 탐색이나 최선 전개가 아니다.
