# Phase 6-AC — 기르수에서 시작하는 오르페골 전개 한 경로를 엔진에서 끝까지 실행

## 1. 기준점과 로드맵 위치

| 항목 | 값 |
| --- | --- |
| 시작 HEAD | `8630622c1ba4f0d3ab22d01270f957fcae57befa` |
| 브랜치 | `claude/pensive-goodall-te1egy` |
| 직전 작업 | 6-AB 보완8 (비유발 후보의 거절·미지원 사유 보존) |

### 이 Phase 가 로드맵의 어디인가

6-T 부터 6-AB 보완8 까지의 열한 걸음은 **보고와 판정**을 다뤘다 — 후보가 왜
오르지 않았는지, 규칙이 막은 것과 엔진이 모르는 것이 어떻게 다른지, 그 구분이
`/combo` 까지 가는지. 그 결과 `/combo` 의 실제 실행은 **「일반 소환 → 기르수 ①
→ 마법·함정 세트」** 에서 끝났다 (6-AB 보완8 시점 실측: 5걸음 · 효과 해결 1건).

이 Phase 는 **그 뒤를 실제로 잇는다.** 보고를 더 다듬는 것이 아니라, 한 경로가
끝까지 돌게 만드는 데 필요한 **규칙 계약 세 개**를 넣었다.

🔴 **코드 주석의 `Phase 6-U` · `Phase 6-V` 는 앞을 가리키는 표가 아니다.**
`deck/opening.py` 의 *"Phase 6-U 가 넓힙니다"* · *"전략적 선택은 Phase 6-U ·
6-V 의 일이다"* 같은 줄은 6-T 당시에 적힌 것이고, 그 두 Phase 는 **이미
끝났다** (각각 "효과 몬스터 일반 소환 조건 판정 개선" · "소환 성공 시 유발 효과
등록"). 즉 그 주석이 미루어 둔 "전략적 선택" 은 번호가 가리키는 자리에 없다 —
이 Phase 도 그것을 만들지 않았다. 여기서 만든 것은 **적어 둔 한 경로를 따라가는
검증용 정책**이고, 그 이름이 그 사실을 말한다.

---

## 2. 작업 전에 확인한 것 (§2)

### 2.1 기르수 효과의 구현 범위

`engine/effect/library.py` 의 `_GIRSU_TRIGGER_ENTRY` 하나다.

| 옮긴 것 | 어디서 |
| --- | --- |
| 발동 분류 `TRIGGER` | `c69811710.lua` e1 `EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O` |
| 시점 `MONSTER_SUMMONED` | `EVENT_SUMMON_SUCCESS` (+ e2 의 `EVENT_SPSUMMON_SUCCESS`) |
| 후보 조건 (덱의 「오르페골」·「성유물」) | `s.tgfilter` 의 `IsSetCard({SET_ORCUST,SET_WORLD_LEGACY})` |
| 하는 일 (묘지로 보내기) | `s.tgop` 의 `Duel.SendtoGrave(tc,REASON_EFFECT)` |
| 발동 조건 (덱 1장 이상) | `s.tgtg` 의 `IsExistingMatchingCard(...)` 중 **장수 부분만** |

작업 전 시점에 **옮기지 못한 것**이 둘이었다.

1. `SetCountLimit(1,id)` — 1턴 1회 제한. **이 Phase 가 옮겼다** (§4.3).
2. `GetColumnGroupCount()>=2` 갈래 (같은 열에 다른 카드가 2장 이상이면 이 턴
   튜너로 취급) — **여전히 옮기지 못했다.** 칸의 열 기하도, 종류를 더하는 지속
   효과 계층도 없다.

### 2.2 특수 소환이 UNKNOWN 으로 막히던 두 자리

| 자리 | 무엇을 막았나 | 이 Phase 의 처리 |
| --- | --- | --- |
| `engine/action_validation.py` `_special_summon` | **플레이어가 선언하는** `SPECIAL_SUMMON` — 언제나 `UNKNOWN`, `missing_rule="special-summon-condition (카드마다 다르다)"` | **한 글자도 바꾸지 않았다** |
| `engine/effect/ruling.py` `BoardRuling.may_be_special_summoned` | **효과 해결 중의** 관문 — `return ConditionResult.UNKNOWN` ("소생 제한은 카드가 아니라 **이력**이다") | **좁게 열었다** (§4.2) |

둘을 가른 것이 §4 의 요구 *"효과에 의한 특수 소환과 플레이어가 직접 선언하는
소환 절차를 구분하고, 구현한 절차에만 권한을 부여해라"* 에 해당한다.

### 2.3 링크 소환에 없던 계약

| 계약 | 작업 전 상태 |
| --- | --- |
| 행위 종류 | `PlayerActionKind` 에 `link_summon` **없음** (열한 종류) |
| 소재 칸 | `PlayerAction` 에 소재를 담을 칸 **없음** (`targets` 는 대상이다) |
| 소환 의미 | `SummonKind` 에 `LINK` **없음** (`normal` · `special` 둘) |
| 절차 | 없음. `SummonProcedure` 는 있었고 (`engine/summon.py`), `Zone.EMZONE` 도 자리당 1칸으로 모델에 있었다 |
| 소재 조건 지식 | 없음 |
| 실행 등록 | `duel_executor` 에 핸들러 없음 |
| 후보 생성 | `Duel.legal_actions` 의 고리가 **패만** 돈다 — 엑스트라 덱을 보지 않는다 |
| 검증 | `_REQUIREMENT_BUILDERS` 에 항목 없음 |

### 2.4 효과 정의 → 실행 등록 → 후보 생성 → 선택 정책 → 사본

```
engine/effect/library.py          LibraryEntry(definition=…, executable=True)
    ↓ definition_registry() / implementation_registry()
engine/spell_activation.py        duel_components(...)  ← journal 하나를 공유한다
    ↓ _executor · _activator · _resolver
engine/duel.py Duel.legal_actions
    ├ _trigger_offers(seat)       integration.autonomy.trigger_offers
    │     ↓ timing_events(journal) → registry_for_view(view, repository)
    │     ↓ TriggerCollector · TriggerEligibilityJudge (다섯 관문)
    ├ _trigger_actions            제안 → PlayerAction → _activation_gate
    ├ _activation_actions         판의 카드 → target_combinations → 관문
    ├ _link_summon_actions        엑스트라 덱 → 소재 조합 → 검증기   ← **신규**
    └ _flow_actions · _withheld_* 흐름과 보류
    ↓ LegalActions(allowed, withheld)
deck/opening.py execute_opening(choose=…)
    ↓ choose = first_meaningful  (기본값)
    ↓ choose = VerificationLinePolicy(line=…)                      ← **신규**
Duel.apply → _apply_board / _apply_activation
agent/simulation.py Simulator._fork   판만 복제 · 기록은 씨앗으로 물려받음
```

관문은 셋이고 한 자리에서만 세운다 (`Duel._activation_gate`): ①
`ActionValidator.validate` → ② `ActivationTimingChecker.check` → ③
`EffectActivator.can_activate`. 후보 생성과 `apply` 가 **같은 함수**를 부른다
(STRUCTURAL-134).

---

## 3. 고른 경로와 그 근거 (§3)

### 3.1 경로

| # | 행동 | 결과 |
| --- | --- | --- |
| 1 | 「잭나이츠 오르페골 기르수」(69811710) **일반 소환** | 필드에 기르수 |
| 2 | 기르수 ① **발동** — 덱의 「성유물－『성장』」(93920420) 을 묘지로 | 묘지에 『성장』 |
| 3 | 묘지로 보내진 『성장』 ② **발동** — **패의** 『성장』 을 **특수 소환** | 필드에 『성장』 |
| 4 | 기르수 + 『성장』 을 소재로 「오르페골 갈라테아」(30741503) **링크 소환** | 엑스트라 몬스터 존에 갈라테아 |

§3 의 다섯 조건을 각각 만족한다.

- **현재 구현을 재사용한다** — 1·2 단계는 6-V 가 만든 것 그대로다.
- **앞 단계의 실제 효과 해결이 뒤 단계를 가능하게 한다** — 2 단계의 해결이
  만든 `ZoneMoved(DECK→GRAVE)` 가 3 단계의 사건이고, 3 단계의 특수 소환이 4
  단계의 소재를 만든다.
- **특수 소환 1회 · 링크 소환 1회**가 들어 있다.
- 기존 결과(「일반 소환 후 마법·함정 세트뿐」)와 **분명히 다르다**.
- 엑스트라 몬스터 존의 링크 몬스터라는 **완결된 최종 상태**에 닿는다.

### 3.2 카드 효과·규칙 근거

세 자료를 대조했다: 공식 카드 텍스트(`data/cards.cdb`) · 저장소의 공식 Lua
스크립트 · 공식 룰북(`data/rules/documents/sd-rulebook-en-v10.json`).

**기르수 (69811710)**

> If this card is Normal or Special Summoned: You can send 1 "Orcust" or
> "World Legacy" card from your Deck to the GY, then, if there are 2 or more
> other cards in this card's column, treat this card as a Tuner this turn.
> … You can only use each effect of "Girsu, the Orcust Mekk-Knight" once per
> turn.

`c69811710.lua` e1: `SetCode(EVENT_SUMMON_SUCCESS)` · `SetCountLimit(1,id)` ·
`s.tgfilter = c:IsSetCard({SET_ORCUST,SET_WORLD_LEGACY}) and c:IsAbleToGrave()`
· `Duel.SendtoGrave(tc,REASON_EFFECT)`.

**성유물－『성장』 (93920420) — 등재한 것은 공식 ②다**

> 이 카드명의 ②③의 효과는 각각 1턴에 1번밖에 사용할 수 없다.
> ①: 통상 소환한 이 카드는 엑스트라 덱에서 특수 소환된 몬스터와의 전투로는
> 파괴되지 않는다.
> **②: 이 카드가 묘지로 보내졌을 경우에 발동할 수 있다. 패에서 "성유물"
> 몬스터 1장을 특수 소환한다.**
> ③: 묘지의 이 카드를 제외하고, 자신의 제외 상태인 "오르페골" 몬스터 1장을
> 대상으로 하여 발동할 수 있다. …

🔴 **등재 번호가 처음으로 0 이 아니다.** 지금까지 모든 등재는
`EffectRef(card_id, 0)` 이었고, 이것은 `EffectRef(93920420, 1)` 이다 — 공식
②가 Lua 의 **두 번째** 블록(`e2`)이기 때문이다. 블록과 공식 번호의 대응:

| Lua | 공식 | 등재 | `SetCountLimit` |
| --- | --- | --- | --- |
| `e1` (ordinal 0) | ① 전투 내구 (지속) | 아니오 | 없다 |
| `e2` (ordinal 1) | ② 묘지로 보내졌을 경우 → 패에서 특수 소환 | **예** | `(1, id)` |
| `e3` (ordinal 2) | ③ 묘지의 이 카드를 제외 → 제외된 「오르페골」 | 아니오 | `(1, {id,1})` |

②와 ③의 제한 **열쇠가 다르다** — ②는 카드명 기준이고 ③은 그 카드명의 그
효과 기준이다. 그래서 「각각 1턴에 1번」 을 한 범위로 뭉뚱그리지 않았다:
등재한 ②에만 `LimitScope.PER_CARD_NAME` 을 적었고, ③은 **등재하지 않았으므로
제한도 적지 않았다** (ADR-006 — 없는 것을 기본값으로 메꾸지 않는다).

`c93920420.lua` e2: `EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O` ·
`SetCode(EVENT_TO_GRAVE)` · `SetCountLimit(1,id)` ·
`s.sptg1 = Duel.GetLocationCount(tp,LOCATION_MZONE)>0 and
IsExistingMatchingCard(s.spfilter1,tp,LOCATION_HAND,0,1,nil,e,tp)` ·
`s.spfilter1 = c:IsSetCard(SET_WORLD_LEGACY) and c:IsCanBeSpecialSummoned(...)`
· `Duel.SpecialSummon(g,0,tp,tp,false,false,POS_FACEUP)`.

**오르페골 갈라테아 (30741503)**

> 2 Effect Monsters, including an "Orcust" monster

`c30741503.lua`: `Link.AddProcedure(c, aux.FilterBoolFunctionEx(Card.IsType,
TYPE_EFFECT), 2, nil, s.matcheck)` ·
`s.matcheck = g:IsExists(Card.IsSetCard, 1, nil, SET_ORCUST, lc, sumtype, tp)`.
`max` 가 `nil` 이므로 **정확히 2장**이다.

**소재 적격 대조** (`data/cards.cdb` 실측)

| 카드 | `type` | 효과 몬스터 | `setcode` | 「오르페골」(0x11b) |
| --- | --- | --- | --- | --- |
| 69811710 기르수 | `0x21` | 예 | `0x011b`, `0x010c` | **예** |
| 93920420 『성장』 | `0x21` | 예 | `0x00fe` | 아니오 |
| 30741503 갈라테아 | `0x4000021` | 예 (링크) | `0x011b` | — |

두 소재가 모두 효과 몬스터이고 그중 하나가 「오르페골」 이므로 갈라테아의 소재
조건을 만족한다.

### 3.3 자료 사이의 차이와 판정 기준

| 차이 | 판정 기준 |
| --- | --- |
| 「성유물」 과 「오르페골」 — 『성장』 의 `s.listed_series` 에 `SET_ORCUST` 가 **적혀 있다** | 그것은 **텍스트가 그 이름을 언급한다**는 색인이고 카드군 소속이 아니다. 소속은 `cards.cdb` 의 `setcode` 가 정하고, 『성장』 은 `0xfe` 하나다. 후보 조건에 `0xfe` 만 적었다 |
| 「각각 1턴에 1번」(텍스트)과 `SetCountLimit(1,id)`(스크립트) | 스크립트의 열쇠가 **카드명**이므로 `LimitScope.PER_CARD_NAME` 으로 옮겼다. 저장소의 `UseRegistry` 가 그 세 범위를 이미 그 대응으로 적고 있다 |
| 영어 텍스트와 한국어 표시명 | 판정에 쓰는 것은 `setcode` · `type` 같은 **수치**이고, 이름은 보고용이다 (`cards.cdb` 의 한국어 오버레이) |

**추측으로 통과시킨 것은 없다.** 읽지 못한 것은 §5 에 그대로 적었다.

### 3.4 금제

🔴 **확인하지 않았다.** 이 저장소에 금지·제한 데이터가 없고
(`DeckValidator` 가 그 사실을 "검증 불가" 로 적는다), 어느 날짜의 어느 포맷인지도
없다. 그래서 §6 의 레시피를 **"최신 대회 합법 덱" 이라고 부르지 않는다.**

---

## 4. 더한 실행 지원 (§4)

### 4.1 링크 소환

**판정** — `engine/link_rules.py` (신규)

| 보는 것 | 어디서 |
| --- | --- |
| `source` 가 자신 **엑스트라 덱의 링크 몬스터**인가 | `LINK_SUMMON_FROM_ZONES = {EXTRA}` · `definition.is_link` |
| 소재 조건이 **적혀 있는가** | `LINK_MATERIAL_RULES` — 손으로 읽은 카드만 |
| 소재 **장수** | `LinkMaterialRule.count` (정확한 한 수) |
| 소재 **하나하나** | `MaterialRequirement.each` (효과 몬스터 · 카드군) |
| 소재 **묶음** | `MaterialRequirement` `includes` (「…를 포함」) |
| 소재가 자신 필드의 **앞면 몬스터**인가 | `LINK_MATERIAL_ZONES = {MZONE, EMZONE}` · `face_up` |
| 놓을 **자리**가 있는가 | `assess_link_placement` — **소재가 떠난 뒤의** 판으로 센다 |

**절차** — `engine/link_summon.py` (신규). 순서가 규칙이다: 소재를 **먼저**
묘지로 보내고 (`ZoneMoved(send_to_grave)` × N) 그 다음 엑스트라 덱에서 엑스트라
몬스터 존으로 꺼낸다 (`MonsterSummoned(summon=LINK)`). 두 걸음을 **판에 손대기
전에** 함께 계획한다.

**지원하지 않는 것 — 각자 이름이 있다**

| 지원하지 않는 것 | 이름 | 판정 |
| --- | --- | --- |
| 소재 조건을 읽지 않은 링크 몬스터 | `link-material-requirement` | `UNKNOWN` |
| 링크 몬스터를 소재로 쓰기 (링크 수치만큼 센다) | `link-material-link-rating` | `UNKNOWN` |
| 마커가 가리키는 메인 몬스터 존에 놓기 | `link-placement-linked-zone` | `UNKNOWN` |
| 「링크 소재로 할 수 없다」 제약 | `link-material-restriction` | **판정을 막지 않고** `unchecked` 에 남긴다 |

마지막 줄이 중요하다. 지속 효과 계층이 없으므로 (STRUCTURAL-76) 그 제약을 읽을
자리가 판 어디에도 없다. 그것을 `UNKNOWN` 으로 만들면 **어떤 링크 소환도 못
한다**. 그래서 판정을 바꾸지 않는 **못 본 것**으로 남긴다
(`LinkMaterialAssessment.unchecked` — `BoardRuling._blind_spots` 와 같은 자리).

🔴 **엑스트라 몬스터 존이 찼을 때 두 갈래로 갈린다.** 자신 필드에 링크 몬스터가
**없으면** 가리키는 칸도 없으므로 규칙이 막는다 (`ILLEGAL`). **있으면** 마커의
칸 기하를 옮기지 못해 모른다 (`UNDETERMINED`). 섞어 적으면 규칙 거절이 엔진
미지원으로 집계된다 (보완6 이 고친 바로 그 혼동이다).

**어휘와 배선**

- `PlayerActionKind.LINK_SUMMON` · `PlayerAction.materials` (소재는 **대상이
  아니다** — 링크 소재는 대상으로 지정되지 않으므로 `targets` 에 넣으면 "대상
  내성을 가진 몬스터는 링크 소재가 될 수 없다" 가 된다)
- `SummonKind.LINK` · `SPECIAL_SUMMON_KINDS` — 링크 소환은 규칙상 특수 소환
  이므로 (공식 룰북) 「특수 소환에 성공했을 경우」 유발이 링크 소환에도 발화한다.
  그 사실은 **한 곳에만** 적고 `EVENT_TIMING` 이 그것을 읽는다.
- `ActionValidator._link_summon` → `_COMPLETE_RULES` 에 올렸다. 범위는
  `LINK_MATERIAL_RULES` 가 정하고 그 밖을 전부 `UNKNOWN` 으로 남기므로 올려도
  넓어지지 않는다 (`ACTIVATE_EFFECT` 를 올릴 때와 같은 구조).
- `Duel._link_summon_actions` — 엑스트라 덱 × 소재 조합을 만들어 **검증기에게
  하나씩 묻는다**. 조합 수는 `C(필드 몬스터, 장수)` 로 닫히고 필드가 여섯 칸이므로
  카드당 최대 20이다.
- `engine/summon.py duel_executor` 에 `LinkSummonHandler` 등록.

### 4.2 효과에 의한 특수 소환 권한

`BoardRuling.explain_special_summon` 이 세 걸음으로 답한다.

1. **어디서 나오는가.** `REVIVAL_LIMIT_FREE_ZONES = {HAND}` 밖이면 `UNKNOWN`
   이고 `special-summon-history` 가 그 이름이다. 공식 규칙이 소생 제한을 "묘지
   또는 제외 상태에서의 특수 소환" 에 걸므로, 패에 있는 카드에는 그 질문이
   **생기지 않는다** — 질문이 생기지 않는 것과 답을 아는 것은 다르고, 이 표가
   적는 것은 앞쪽이다.
2. **그 카드가 등록되어 있는가.** `RuleQuestion.MAY_BE_SPECIAL_SUMMONED` 가
   `OPERATION_RULINGS` 에 적혀 있어야 한다. 적히지 않은 카드는 `UNKNOWN`.
3. **판에 막는 것이 있는가.** `_interference` 가 본다 — 모르는 앞면 카드가
   하나라도 있으면 `UNKNOWN`.

`EffectExecutor._summon_ruling` 이 **판을 아는 판정기**를 만들어 묻는다
(`_movement_ruling` 과 같은 모양 · 같은 이유: 답이 그 카드가 **지금 어디에
있는지**에 달려 있다).

🔴 **모든 `SPECIAL_SUMMON` 을 일괄 `VALID` 로 바꾸지 않았다.** 플레이어가
선언하는 특수 소환은 여전히 언제나 `UNKNOWN` 이고, 열린 범위는 **패에서 나오고
손으로 읽은 카드**뿐이다.

『성장』 에 대해 읽은 것 (`RuleBasis.CARD_TEXT`):

- `MAY_BE_SENT_TO_GRAVE = TRUE` — ② 가 「이 카드가 묘지로 보내졌을 경우」 라고
  적어 그 상황을 스스로 전제한다. 메인 덱의 효과 몬스터이므로 토큰도 엑스트라
  덱 카드도 아니다.
- `MAY_BE_SPECIAL_SUMMONED = TRUE` — 소환 조건이 **없다.** 「일반 소환할 수
  없다」 도 「특수 소환으로만 특수 소환할 수 있다」 도 적혀 있지 않다. 기계로 읽은
  근거도 같다: `normal_summon_restriction_signals == ()` (스크립트를 끝까지
  읽었고 제약 상수가 0건 — `core.card_model` 의 세 갈래 규약에서 "제약 없음을
  확인했다" 쪽).
- `restricts_others = False` — 🔴 **근거가 카드가 아니라 등재 범위다.** ③ (묘지의
  자신을 제외 → 제외된 「오르페골」 특수 소환, 그리고 「그 턴 어둠 속성 이외를
  특수 소환할 수 없다」) 에는 남을 막는 문장이 **있다.** 그 제약은 그 효과를
  발동했을 때에만 걸리고, ③ 은 `EFFECT_LIBRARY` 에 등재되지 않았으므로 이
  엔진에서 발동될 수 없다. 그 의존을 **import 시점에 기계가 지킨다** —
  `_WORLD_WAND_RESTRICTION_GUARD` 가 『성장』 의 등재가 `e[1]` 하나임을 단언하고,
  ③ 을 등재하면 import 가 실패한다.

### 4.3 1턴 1회

| 자리 | 하는 일 |
| --- | --- |
| `engine/state/use_registry.py` `UseLimit` | **확인된** 제한 하나 (`scope` · `times`). `NONE` · `UNKNOWN` 범위는 담을 수 없다 — 모르는 제한은 `None` 이다 |
| `EffectDefinition.use_limit` | 지식. `None` 은 "읽지 않았다" 이고 "없다" 가 아니다 |
| `GameState.uses` (`UseRegistry`) | 상태. **세기만** 한다 |
| `EffectActivator._check_use_limit` | 판정. 발동 조건 **뒤**에 본다 — 조건이 거짓인 효과까지 "이미 썼다" 로 보고하지 않으려고 |
| `EffectActivator.activate` | 비용 지불 **뒤**, 체인에 오를 때 센다 — 공식 규칙에서 「1턴에 1번」 은 **발동**으로 소비된다 |
| `TurnProgressor._apply` | 턴이 넘어갈 때 `state.uses.clear()` |

마지막 줄은 이 Phase 가 함께 들고 왔다. `TurnState.begin_next_turn` 이 "사용
횟수 초기화는 여기서 하지 않는다 — 무엇이 언제 리셋되는가는 규칙이다" 라고 적어
두었고, 제한을 **판정하기 시작한** Phase 가 리셋도 책임진다. 비우지 않으면 다음
턴에도 영원히 막힌다.

`ValidationCode.EFFECT_USE_LIMIT_REACHED` (INVALID) ·
`ActivationStatus.USE_LIMIT_REACHED`. `CONDITION_FALSE` 와 **합치지 않는다** —
발동 조건은 판이 바뀌면 참이 될 수 있지만 이쪽은 이 턴 안에서 다시 참이 되지
않는다.

### 4.4 이 경로가 드러낸 결함 다섯 개

**① 발동 시점에 고르는 유발의 조합을 열거하지 못했다.**

`Duel._trigger_actions` 가 `targets=()` 인 후보 **하나**만 만들고
`selections_for` 에 넘겼다. 기르수 ① 은 **덱**에서 고르므로 선택이 해결
시점으로 미뤄지고 (`decided_at_resolution`) 그 길을 타지 않았지만, 『성장』 ② 은
**패**에서 고른다 — 자기 패는 평소 관측에 보이므로 발동 시점에 가리킨다. 실측:

```
🔴 activate_effect [이 유발 효과의 실행 구현]:
   93920420:e[1] 의 대상 지정을 이 계층이 옮기지 못했습니다
```

그 문장은 **거짓이었다.** 실행 구현은 있었고 없었던 것은 이 자리의 조합 열거다.
`target_combinations` 로 고쳤다 — `_activation_actions` 가 쓰는 **같은 함수**이고,
고를 것이 없으면 빈 조합 하나를 돌려주므로 기르수 쪽 동작은 바뀌지 않는다.

**② 창을 닫은 규칙이 「엔진 미지원」 으로 집계됐다.**

`event_backed` 를 만드는 `_offer_is_activatable` 은 `_window_admits` 하나로
묻고, 그 함수는 `window_passed`(그 자리가 이 창에서 발동하지 않기로 했다)를
**한 가지 더** 본다. `_trigger_actions` 의 네 검사에는 그것이 없어서 둘의 답이
갈렸고, 갈리면 관문이 `event_backed` 없이 판정해 `trigger-effect-activation`
(엔진 미지원)을 적었다. 실측 (자동 `PASS` 뒤의 『성장』 ②):

```
🔴 activate_effect [trigger-effect-activation]: 발동 관문을 지나지 못했습니다
   실제 이유 = 그 자리가 이 창에서 포기했다 (window_passed)
```

**같은 함수를 부르게** 고쳤다 (판정을 복제하지 않는다). 그리고 조합이 0가지인
경우도 두 갈래로 갈랐다 — `unsupported_enumeration` 이 모양 이름을 대면
`RULE_NOT_IMPLEMENTED`, 그냥 적격 후보가 없으면 `NO_CANDIDATES`(규칙의 답).

**③ `Condition.refusal_reasons`** — 조건이 `FALSE` 인 **구체적인 이유**를
전하는 자리. `unknown_reasons` 와 대칭이고 기본값이 빈 튜플이므로 그것을 채우지
않는 조건의 문장은 바뀌지 않는다. 없으면 소재 조건 위반 네 가지가 모두 같은 한
줄로 보고된다 (실측).

**④ 보고가 링크 몬스터를 적지 않았다.**

`render_opening_board` 의 표에 **엑스트라 몬스터 존이 없었다.** 링크 소환이
실행되기 전에는 그 자리가 언제나 비어 있었으므로 빠진 것이 보이지 않았다.
실측 (이 경로를 돌린 직후):

```
몬스터 존: 0장 — 없음
...
엑스트라 덱: 5장 — ...   ← 갈라테아만 빠져 있다
```

즉 **갈라테아가 보고에서 사라졌다** — 읽는 쪽이 카드가 어디로 갔는지 알 수
없었다. 판에 있는 자리를 적지 않는 것은 보고의 결함이므로 한 줄을 더했다
(`("엑스트라 몬스터 존", Zone.EMZONE)`). 다른 줄은 바뀌지 않았다.

**⑤ import 고리** — `engine/effect/executor.py` 가 `engine.special_summon` ·
`engine.summon` 을 모듈 위에서 읽어, 그 두 모듈이 먼저 import 되는 경로에서
`ImportError` 가 났다. 🔴 **기준 HEAD `8630622` 에서도 재현된다** (단독 실행한
`tests/engine/test_action_validation.py`) — 전체 테스트에서는 다른 파일이
`engine.effect` 를 먼저 import 해 가려져 있었다. 이 Phase 가 그 자리를 밟았으므로
함께 끊었다 (두 이름을 함수 안에서 읽는다 — 그 두 모듈이 실행기 계층을 그렇게
읽는 것과 **같은 자리**다).

### 4.5 늘어난 어휘 (전부 손으로 적었다)

| 어휘 | 전 | 후 | 더한 것 |
| --- | --- | --- | --- |
| `PlayerActionKind` | 11 | **12** | `link_summon` |
| `PlayerAction` 의 칸 | 6 | **7** | `materials` (대상이 아니다) |
| `SummonKind` | 2 | **3** | `LINK` (절차가 있는 이름만 더한다 — 융합 · 싱크로 · 엑시즈 · 의식 · 펜듈럼은 여전히 없다) |
| `ValidationCode` | 51 | **53** | `EFFECT_USE_LIMIT_REACHED` · `LINK_MATERIAL_INVALID` (둘 다 `INVALID`) |
| `ActivationStatus` | 15 | **16** | `USE_LIMIT_REACHED` |
| `RuleQuestion` | 7 | **8** | `MAY_BE_SPECIAL_SUMMONED` |
| `EffectDefinition` 의 칸 | 12 | **13** | `use_limit` |
| 등재한 `ordinal` 의 집합 | `{0}` | **`{0, 1}`** | 공식 ②를 등재한 첫 자리 (『성장』) |
| `EFFECT_LIBRARY` | 18 (실행 15) | **19 (실행 16)** | 성유물－『성장』 ② |
| `OPERATION_RULINGS` | 19 | **21** | 『성장』 · 갈라테아 |
| `Condition` 의 설명 메서드 | `unknown_reasons` · `missing_rules` | **+ `refusal_reasons`** | 기본값이 빈 튜플이므로 기존 문장은 바뀌지 않는다 |
| `Duel` 의 보류 생성 자리 | 7 | **9** | `_link_summon_actions` · `_note_trigger_refusal` |
| `engine/` 모듈 | 69 | **72** | `link_summon.py` · `link_rules.py` · `use_limit.py` |

**새 모듈 셋을 왜 갈랐는가**

| 모듈 | 들고 있는 것 | 가른 이유 |
| --- | --- | --- |
| `engine/link_rules.py` | 소재 조건의 판정 (순수) | `link_summon.py` 에 함께 두면 `engine.effect` 초기화 중에 순환 import 가 난다 (실측 — §4.1) |
| `engine/link_summon.py` | 절차 (소재 이동 · 배치) | — |
| `engine/use_limit.py` | 「1턴에 몇 번까지인가」 — **값** | 처음에는 `engine/state/use_registry.py` 에 두었다. 그 모듈에는 **판의 기록**(`UseRegistry`)도 있어서, 정의 계층이 그것을 가져오면 **정의가 판을 알게 된다**. `test_the_library_never_reaches_into_the_board` 가 그것을 금지하고 있었고 실제로 깨졌다 — 값과 기록을 갈랐다 |

🔴 **열쇠를 만드는 자리는 하나다.** `UseRegistry.card_key` ·
`card_name_key` · `effect_key` 는 이름을 유지한 채 `engine/use_limit.py` 로
넘긴다. 양쪽에 적으면 둘이 갈라지고, 그러면 "이 카드 1장" 과 "이 카드명
전체" 가 같은 제약이 되는 사고가 난다 — 그것이 그 모듈 머리말의 경고다.

🔴 **코드 분류를 비워 둔 자리는 없다.** `CODE_VALIDITY` 는 분류되지 않은 코드가
있으면 import 가 실패하므로 (53 / 53), 두 새 코드도 `INVALID` 로 적혀 있다 —
확인된 제한과 확인된 소재 조건의 위반이고 모름이 아니다.

---

## 5. 아직 지원하지 않는 범위

| 범위 | 이름 / 사실 |
| --- | --- |
| 소재 조건을 읽지 않은 링크 몬스터 | `link-material-requirement`. 등록은 갈라테아 **하나**다 |
| 소재 장수가 범위인 링크 몬스터 (`2+` 류) | `LinkMaterialRule.count` 가 정확한 한 수다. 장수를 고르는 계층이 없으므로 **등록하지 않는다** |
| 링크 몬스터를 소재로 쓰기 | `link-material-link-rating` |
| 마커가 가리키는 메인 몬스터 존 배치 | `link-placement-linked-zone` |
| 「링크 소재로 할 수 없다」 제약 | `link-material-restriction` — 판정을 막지 않는 **못 본 것** |
| 소재 고르기의 전략 | 없다. 조합을 전부 만들어 검증기에게 묻고, 정책이 **카드 ID 로** 하나를 고른다 |
| 묘지 · 제외 · 덱 · 엑스트라 덱에서의 특수 소환 | `special-summon-history` (이력) + `SPECIAL_SUMMON_FROM_ZONES` 가 패 · 묘지만 옮겼다 |
| 표시 형식 선택 | `SPECIAL_SUMMON_POSITION` 이 앞면 공격으로 고정 (STRUCTURAL-61). 링크 몬스터는 **규칙이** 하나로 정하므로 그쪽은 고정이 맞다 |
| 『성장』 ① (통상 소환한 이 카드는 엑스트라 덱에서 특수 소환된 몬스터와의 전투로 파괴되지 않는다) | 등재하지 않았다 — 지속 효과이고 전투 계층이 범위 밖이다 |
| 『성장』 ③ (묘지의 이 카드를 제외 → 제외된 「오르페골」 특수 소환 + 소환 제약) | 등재하지 않았다. 제약을 적는 계층이 없다. 제한의 열쇠도 ②와 **다르다** (`(1, {id,1})`) — 적지 않았으므로 제한도 적지 않았다 |
| 기르수 ② (「성유물 토큰」을 서로의 필드에 1장씩) · 기르수 ① 의 열 갈래 (같은 세로열에 다른 카드 2장 이상 → 이 턴 튜너 취급) | 등재하지 않았다 |
| 「오르페골 디베르」 · 「오르페골 스켈레촌」 의 묘지 제외 전개 | 등재하지 않았다 — 덱에서의 특수 소환과 제외 소재가 범위 밖이다 |
| 갈라테아 ① (제외된 기계족 → 덱 + 「오르페골」 마법·함정 세트) | 등재하지 않았다 |
| `activate_card` 의 발동 타이밍 | `activation-timing (Phase 2-C/2-F)` — 이 Phase 전부터 남아 있는 범용 한계다 |
| 금지·제한 판정 | 데이터가 없다 (§3.4) |

---

## 6. 검증용 정책의 역할과 한계 (§5)

`deck/combo_policy.py` 의 `VerificationLinePolicy` 다.

**하는 일** — 적어 둔 `ComboLine` 의 단계를 순서대로 훑어, 그 자리의
`legal.allowed` 와 맞는 **첫 단계**를 고른다.

**지키는 것**

1. **엔진이 낸 후보에서만 고른다.** 이 모듈에는 `PlayerAction` 을 **만드는
   코드가 없다** (AST 로 센다 — `test_f01`). 엔진을 우회해 상태를 바꿀 길이
   구조적으로 없다.
2. **매 상태마다 다시 묻는다.** `(duel, legal)` 을 받을 때마다 그 자리의 후보만
   본다.
3. **상태를 갖지 않는다.** frozen 이고 cursor 도 trace 도 없다 — 어느 단계인지는
   **후보 목록이 말한다**. 그래서 사본(`Simulator._fork`)에 같은 정책을 그대로
   써도 원본이 오염되지 않는다.
4. **대상과 소재는 기존 계약을 따른다.** 효과의 대상은 `target_combinations` 가
   만든 조합이고 링크 소재는 `assess_link_materials` 가 판정한 것이다 — 정책은
   그 안에서 카드 ID 로 하나를 고르기만 한다.
5. **기대한 행동이 없으면 조용히 넘기지 않는다.** `None` 을 돌려주면
   `execute_opening` 이 멈추고 이유를 적는다. 어디까지 갔는지는 `line_progress`
   가 **실행 기록과 경로를 대조해** 답한다 (정책에게 묻지 않는다 — 정책은
   상태가 없고, 답을 들고 있는 것은 수락된 걸음의 기록이다).

**한계 — 이것이 아닌 것**

- 🔴 **최선 전개 탐색이 아니다.** 경로를 사람이 적어 두었다.
- 🔴 **범용 오르페골 AI 가 아니다.** 적혀 있지 않은 판에서는 아무것도 고르지
  못한다.
- 🔴 **LLM 이 스스로 찾은 전개가 아니다.** 네 단계는 공식 텍스트와 공식
  스크립트를 대조해 손으로 적었다.
- 🔴 **`first_meaningful` 을 바꾸지 않았다.** 그 함수에 `LINK_SUMMON` 을 넣지
  않았고, `choose` 를 주지 않으면 다른 요청의 행동 선택은 예전과 한 글자도
  다르지 않다.
- 🔴 **같은 행동이 두 번 허가되는 경로를 적으면 두 번 고른다.** 그때 멈추는 것은
  `execute_opening` 의 걸음 상한이고, 그것이 **경로를 잘못 적었다는 신호**다 —
  정책이 몰래 중복을 걸러 주면 그 신호가 사라진다.

**제품에서 쓰는 길** — `/combo` 의 `line:` 옵션과 CLI 의 `--line` 이다. 이름을
주지 않으면 `first_meaningful` 그대로이고, 이름이 틀리면 **비슷한 것을 골라 주지
않고** 그 사실을 적는다 (요청한 경로가 아닌 것으로 검증한 결과를 보여 주면
사용자는 그 경로가 돌았다고 읽는다).

---

## 7. 레시피와 입력 (§6)

🔴 **이 레시피는 명시적으로 제공하는 검증 자료다.** `recipe:` 를 생략한 요청에서
자동으로 쓰이는 길은 없다 (`test_g03` 이 전달 경로에 그 상수의 이름이 없음을
센다). **추천 덱이 아니고**, 금제를 확인하지 않았으므로 포맷 적법성을 주장하지
않는다.

### 7.1 지정 패 (5장)

사용자가 이미 적어 둔 그대로다. **패에 없는 카드를 보태지 않았다** — 경로의 2
단계가 덱에서 『성장』 을 꺼내 오므로 추가 시작 패가 필요하지 않다.

| 패스코드 | 한국어 이름 |
| --- | --- |
| 69811710 | 잭나이츠 오르페골 기르수 |
| 703897 | 오르페골 클리막스 |
| 2930675 | 성유물에 이르는 열쇠 |
| 12989604 | 성유물로부터의 자각 |
| 93920420 | 성유물－『성장』 |

### 7.2 메인 덱 40장

| 패스코드 | 매수 | 한국어 이름 |
| --- | --- | --- |
| 69811710 | 3 | 잭나이츠 오르페골 기르수 |
| 93920420 | 3 | 성유물－『성장』 |
| 57835716 | 3 | 오르페골 디베르 |
| 21441617 | 3 | 오르페골 스켈레촌 |
| 94046012 | 3 | 오르페골 카노네 |
| 40441990 | 3 | 성유물－『성건』 |
| 2930675 | 3 | 성유물에 이르는 열쇠 |
| 90351981 | 3 | 오르페골 바벨 |
| 26845680 | 3 | 오르페골 프라임 |
| 61654098 | 3 | 성유물과의 해후 |
| 703897 | 3 | 오르페골 클리막스 |
| 12989604 | 3 | 성유물로부터의 자각 |
| 55051920 | 2 | 오르페골 코어 |
| 47171541 | 2 | 오르페골 릴리스 |

### 7.3 엑스트라 덱 6장

| 패스코드 | 한국어 이름 | 비고 |
| --- | --- | --- |
| 30741503 | 오르페골 갈라테아 | LINK-2. **이 경로가 소환한다** |
| 48835607 | 오르페골 갈라테아i | LINK-1. 소재 조건 미등록 |
| 76145142 | 오르페골 롱기르수 | LINK-3. 소재 조건 미등록 |
| 93854893 | 시오르페골 딩기르수 | LINK-8. 소재 조건 미등록 |
| 74820316 | 잭나이츠 오르페골 엔릴기르수 | LINK-4. 소재 조건 미등록 |
| 3134857 | 오르페골 오케스트리언 | LINK-4. 소재 조건 미등록 |

### 7.4 왜 『성장』 이 3장인가

경로가 그 카드를 **두 장** 쓴다 — 하나는 기르수 ① 이 **덱에서** 묘지로 보내고,
다른 하나는 묘지의 그 카드가 **패에서** 특수 소환한다. 지정된 패가 한 장을 들고
있으므로 덱에 최소 한 장이 더 있어야 한다.

### 7.5 검증용 레시피와 실제 추천 덱의 차이

실제 오르페골 덱은 「오르페골 디베르」 · 「오르페골 스켈레촌」 의 **묘지 제외**
전개로 이어지고 (제외된 「오르페골」 을 소재로 더 큰 링크 몬스터로 간다) 패
트랩과 범용 마법·함정을 함께 쓴다. 그 효과들은 이 저장소에 등재되지 않았으므로
(덱에서의 특수 소환 · 제외 소재가 범위 밖) 여기 넣어도 실행에 쓰이지 않는다.
이 레시피의 그 카드들은 **기르수 ① 의 후보로서** 들어 있다.

---

## 8. 걸음마다의 비용 · 선택 · 해결 · 상태 변화

실측이다 (`/combo` 와 같은 배선 · 위 레시피 · 위 패 · `line:orcust-girsu`).

| # | 행동 | 비용 | 선택 | 해결 | 상태 변화 |
| --- | --- | --- | --- | --- | --- |
| 1 | `normal_summon` 69811710 | 없음 (소환권은 비용이 아니다) | 없음 | — (소환은 효과가 아니다) | 패 → 몬스터 존[0] 앞면 공격 |
| 2 | `activate_effect` `69811710:e[0]` | 없음 (`cost.costs == ()`) | **해결 중에** 덱의 『성장』 (덱은 가려진 자리 — `decided_at_resolution`) | `체인1 … 해결했습니다` · `EffectEvent 69811710:e[0]` | 덱 → 묘지 (`ZoneMoved send_to_grave`) |
| 3 | `activate_effect` `93920420:e[1]` | 없음 | **발동 시점에** 패의 『성장』 (`@primary=[#79]`) | `체인1 … 대상 @primary=[#79] 를 해결했습니다` · `EffectEvent 93920420:e[1]` | 패 → 몬스터 존[0] 앞면 공격 (`MonsterSummoned special`) |
| 4 | `link_summon` 30741503 | 없음 — **소재는 비용이 아니라 소환 절차다** | 소재 = 기르수 + 『성장』 (조합 1가지가 허가됨) | — (소환은 효과가 아니다) | 소재 2장 → 묘지, 엑스트라 덱 → 엑스트라 몬스터 존[0] (`MonsterSummoned link`) |
| 5 | `pass` | — | — | 이 유발 처리 기회에서 발동하지 않기로 했다 | 없음 |

5 걸음째의 `pass` 는 4 단계가 만든 새 사건(소재가 묘지로 갔다)이 연 『성장』 ②
의 기회를 지나간다. 그 효과는 「1턴에 1번」 을 이미 썼고 패에 「성유물」 몬스터도
없다.

🔴 **소재는 `targets` 가 아니라 `ExecutedStep.materials` 에 적힌다.** 보고에도
다른 줄로 나온다 — `소재 2장: 잭나이츠 오르페골 기르수 · 성유물－『성장』`.
한 칸에 넣으면 보고가 "대상 2개" 로 적고, 그것은 거짓이다 (링크 소재는 대상으로
지정되지 않는다).

### 8.1 최종 상태

| 자리 | 내용 |
| --- | --- |
| 엑스트라 몬스터 존 | 오르페골 갈라테아 [30741503] |
| 몬스터 존 | 없음 |
| 마법·함정 존 | 없음 |
| 패 (3장) | 오르페골 클리막스 [703897] · 성유물에 이르는 열쇠 [2930675] · 성유물로부터의 자각 [12989604] |
| 묘지 (3장) | 성유물－『성장』 (덱에서) · 잭나이츠 오르페골 기르수 (소재) · 성유물－『성장』 (소재) |
| 제외 | 없음 |
| 남은 덱 | 34장 |
| 엑스트라 덱 | 5장 (갈라테아만 빠졌다) |

### 8.2 카드 수 대조 (§7)

| | 전 | 후 |
| --- | --- | --- |
| 총 장수 | 46 (메인 40 + 엑스트라 6) | **46** |
| 개체 번호 묶음 | — | **같다** (새로 생기거나 사라진 번호 0건) |
| 카드 정체 | — | **같다** |

움직인 개체는 넷이고 각자 어디서 어디로 갔는지 말할 수 있다.

| 카드 | 전 | 후 | 무엇이 옮겼나 |
| --- | --- | --- | --- |
| 69811710 기르수 | HAND | GRAVE | 일반 소환 → 링크 **소재** |
| 93920420 『성장』 | DECK | GRAVE | 기르수 ① 의 **효과** |
| 93920420 『성장』 | HAND | GRAVE | 『성장』 ② 의 **효과**로 특수 소환 → 링크 **소재** |
| 30741503 갈라테아 | EXTRA | EMZONE | 링크 **소환** |

소재 · 비용 · 효과로 움직인 카드가 각각 구분된다 — 소재는 `ZoneMoved` 의
`send_to_grave`(링크 절차), 효과는 `EffectEvent` 와 함께 남은 `ZoneMoved`,
비용은 이 경로에 **없다**.

---

## 9. 이 경로의 실행 여부와 지원 범위의 구분 (§7)

| 질문 | 답 |
| --- | --- |
| **경로를 끝까지 실행했는가** | ✅ `line_progress(...).completed is True` — 4/4 단계 |
| **후보 공간 전체를 지원 범위 안에서 검증했는가** | 🔴 아니다 — `run.fully_supported is False` |

두 질문은 다르고 한 값으로 뭉치면 둘 중 하나가 거짓이 된다 (보완8 이
`fully_supported` 와 `stopped_kind` 를 가른 것과 같은 자리).

이 실행에서 남은 미지원 2건은 **경로와 무관하다**.

1. `link_summon [link-material-requirement]` — 엑스트라 덱의 **다른 다섯 장**의
   소재 조건을 읽지 않았다.
2. `activate_card [activation-timing (Phase 2-C/2-F)]` — 패의 마법·함정의 카드
   발동 타이밍. 이 Phase 전부터 있던 범용 한계다.

🔴 **그 2건 때문에 경로 실행을 실패로 적지 않는다.** 그리고 반대로, 경로를
끝냈다는 이유로 그 2건을 지우지도 않는다.

🔴 **멈춘 자리는 `not_chosen`** 이다 — 경로가 끝나고 정책이 더 고를 것을 찾지
못했으며, 남은 후보는 세트와 `end_phase` 였다. 그것은 "막혔다" 가 아니다.

---

## 10. 테스트 (§8)

### 10.1 새 통합 시험 — `tests/test_orcust_girsu_line.py`

| 묶음 | 재는 것 |
| --- | --- |
| **A** 경로 실행 (6건) | 발표한 레시피 + 지정 패로 4단계 전부 · 걸음마다의 선택과 해결 · 최종 상태 · **카드 수와 개체 이동 대조** · 같은 입력의 재현 · 사본과 원본의 후보·결과 일치 |
| **B** 링크 소환 음성 (10건) | 통상 몬스터 소재 · 묶음 조건(「오르페골」 포함) 위반 · 필드 몬스터 부족 · 소재 조건 미등록(UNKNOWN) · 읽은 카드가 가려지지 않음 · 엑스트라 몬스터 존이 찼을 때의 **두 갈래** · 링크 몬스터를 소재로(UNKNOWN) · 엑스트라 덱 밖의 카드 · 소재는 대상이 아니다(모양 검사) · 등록이 하나다 |
| **C** 특수 소환 권한 (4건) | 플레이어 선언은 **여전히 UNKNOWN** · 묘지의 카드는 소생 제한으로 UNKNOWN · 미등록 카드는 UNKNOWN · 몬스터 존이 꽉 차면 발동 조건이 **거짓** |
| **D** 1턴 1회 (3건) | 둘째 발동이 `EFFECT_USE_LIMIT_REACHED` 로 거절되고 **판은 그대로** · 턴이 넘어가면 비워진다 · 제한을 적지 않은 효과는 영향 없음 |
| **E** 보완8 회귀 (4건) | 규칙 INVALID 가 미지원으로 집계되지 않는다 · 경로 성공과 지원 한계가 갈린다 · `/combo` 가 검증용 정책임을 적는다 · 틀린 경로 이름을 조용히 바꾸지 않는다 |
| **F** 정책 (6건) | `PlayerAction` 을 만들지 않는다(AST) · 상태가 없다 · 기대한 행동이 없으면 멈춘다 · `first_meaningful` 이 그대로다 · 인스턴스 번호로 적지 않는다 · 모양 검사 |
| **G** 레시피 (4건) | 정상 크기 · 매수 3 이하 · 메우기 없음 · 지정 패가 매수 안에 든다 · 생략하면 자동으로 쓰이지 않는다 · 포맷 적법성을 주장하지 않는다 |

음성 사례마다 **관련 코드·사유와 상태 불변**을 함께 센다 (B01 · D01 이
`state_hash()` 를 전후 비교한다).

### 10.2 정정한 기존 감사

고친 시험 파일은 **83개**다. 전부 "수를 고치고 **무엇이 왜 바뀌었는가**를 그
자리에 적는" 방식이고, **assertion 을 지우거나 skip 으로 숨긴 자리는 없다.**
몇 자리는 더 정확한 축으로 **다시 세게** 바꿨다.

**① 같은 수가 여러 파일에 박혀 있던 것 (기계적)**

| 바뀐 사실 | 파일 수 |
| --- | --- |
| `EFFECT_LIBRARY` 18 → 19 | 23 |
| 실행 가능 15 → 16 | 6 |
| `OPERATION_RULINGS` 19 → 21 | 5 |
| `ValidationCode` 51 → 53 (그리고 그 파생 — `INVALID` 42 → 44 · 나머지 39 → 41 · 코드에서 판정을 되찾는 자리 50 → 52) | 11 |
| `EffectDefinition` 칸 12 → 13 | 5 |
| 등재 `ordinal` 집합 `{0}` → `{0, 1}` | 6 |
| `PlayerActionKind` 11 → 12 | 5 |

**② 사실이 뒤집혀 시험의 이름까지 고친 것**

| 시험 | 전 | 후 |
| --- | --- | --- |
| `test_j_no_real_card_special_summons_yet` | 실행 가능한 실제 카드가 특수 소환을 **하지 않는다** | `..._exactly_one_...` — 정확히 하나이고, **죽은 자의 소생은 여전히 못 한다** (패와 묘지의 차이 = 소생 제한) |
| `test_12_no_registered_effect_performs_a_special_summon` | 등재 중 `SPECIAL_SUMMON` 이 **0개** | `test_12_exactly_one_...` — 그 하나를 `EffectRef` 로 못박는다 |
| `test_c09_girsu_is_the_only_registered_trigger_effect` | 등재된 유발이 **하나** | `test_c09_two_registered_trigger_effects_now_exist` — 수만 늘리지 않고 **공통성을 센다** (같은 등재 경로 · 같은 분류 · 서로 다른 조작과 `ordinal`) |
| `test_16_the_library_now_has_exactly_one_trigger` | — | `..._exactly_two_triggers` |
| `test_02_summon_kind_says_which_summon_and_only_that` | 멤버 둘을 센다 | 멤버 셋을 **구현된 절차와 대조**한다 (값마다 그것을 들고 있는 절차가 하나) |
| `test_07_the_executable_set_is_exactly_eight_kinds` | 여덟 | `..._nine_kinds` — "낼 수 있는 일곱" 과 섞지 않는다 |
| `test_14_no_registered_effect_can_special_summon` | 0개 | 그 하나를 못박는다 (이름은 유지 — 파일 전체가 그 축이다) |

**③ 측정 자리가 옮겨 간 것 (느슨하게 하지 않고 걸음을 적었다)**

| 시험 | 무엇이 달라졌나 |
| --- | --- |
| `test_a03` · `test_a07` (`test_trigger_normal_path_integration`) · `test_b04` (`test_bilateral_trigger_order`) · `test_a05` (`test_empty_chain_fast_window`) | 기르수 ① 의 해결이 묘지로 보낸 카드가 『성장』 이고 6-AC 가 그 ②를 등재했으므로, **해결 직후가 등재 단계(box D)** 다. 단언을 느슨하게 하지 않고 그 기회를 지나는 걸음을 적었다 |
| `test_b11` · `test_d04` (같은 두 파일) | 같은 이유로 다음 발동이 `STAGE_FORBIDS_ACTION` 으로 거절된다 — **그 거절은 옳다.** 지나는 걸음을 더했다 |
| `test_d05_a_state_hash_alone_does_not_decide_...` | 기르수 ① 에 `use_limit` 이 붙어 **발동이 판의 모양을 바꾼다** (`uses` 가 `canonical_state` 에 들어 있다). 그래서 주장을 더 날카롭게 고쳤다 — 사용 기록을 맞춰 해시를 되돌려도 **기회는 돌아오지 않는다** |
| `test_e02` (`test_withheld_reason_propagation`) | `activate_card` 보류가 멈춘 자리에서 사라졌다 (전개가 한 걸음 더 간다). 그 보류가 **실제로 있는 자리**(전개 시작 전)에서 재고, `run.unsupported` 가 그것을 싣는 것을 함께 센다 |
| `test_c01` · `test_g05` (`test_graveyard_movement_ruling`) · `test_f01` · `test_f02` · `test_i01` · `test_i02` (`test_deck_to_grave_blocker`) | 묘지행 판정의 근거가 **파생에서 등재로** 옮겼다 (991/684 → 990/685, 합 1,675 그대로 · 뒤집힌 카드 **0장**). 사본 등록소는 그 자리를 **빼고** 만든다 — 한 카드의 사실은 한 군데에만 적는다는 계약을 우회하지 않는다 |

**④ 사용자 패 전개의 수가 움직인 것**

| 시험 | 전 | 후 |
| --- | --- | --- |
| `test_combo_output_consistency` (3) · `test_withheld_reason_propagation` (2) · `test_trigger_window_completion` (3) | 5걸음 · 효과 해결 1 · 멈춘 자리 `unsupported` | **6걸음 · 효과 해결 2 · `flow_only`** |

🔴 멈춘 자리가 깨끗해진 것과 **전개 전체가 검증된 것**은 다르다 —
`run.fully_supported is False` 는 그대로이고, 지나온 미지원 1건이 보고에 남는다.

**⑤ 좌표와 목록을 실측값으로 다시 적은 것**

| 감사 | 바뀐 것 |
| --- | --- |
| `test_rule_not_implemented_code_audit` | 문자열 111 → 117 · 코드 80 → 83 · 산문 31 → 34 (세 수를 **따로** 세는 등식이 이 감사의 주장이고 그대로다) · status/code 위반 13 · 적합 19 는 **그대로**이고 열 자리의 좌표만 밀렸다 (원인 셋을 적었다) |
| `test_validation_code_rejection_semantics_audit` | 코드 51 → 53 · 거부 생성 67 → 70 · `RULE_NOT_IMPLEMENTED` 자리 80 → 83 (차이 13 **그대로**) · 섹션 하나 추가 · 좌표 255 → 260 · 여러 줄이 된 호출을 다시 못박았다 |
| `test_duelstep_withheld_validation_audit` | `WithheldAction` 자리 24 → 28 · `missing` 채우는 자리 12 → 16 · **비우는 자리 12 그대로**. 출처 종류가 셋 → 다섯이 된 것을 숨기지 않고 적고, **성질로는 셋**임을 조건식 셋을 못박아 함께 센다 |
| `test_trigger_pipeline_dormant_audit` | `Duel` 폐쇄 59 → 62 (새 모듈 셋) · dormant 와 무관한 코드 43 → 45 — **휴면 모듈 넷은 그대로 폐쇄 밖**이고 새 코드 둘 다 dormant 층에 없다 |
| `test_unimplemented_rule_semantics_audit` | `missing_rules` override 8 → 9 (`_LinkMaterialsLegal` — `UnimplementedRule` 이 아니면서 **조건부로** 낸다) · `UnimplementedRule` 이 아닌 `activation` 9 → 10 |
| `test_engine_condition_none_contract_audit` | `engine/` 파일 69 → 72 — `Condition | None` 칸은 **다섯 그대로** |
| `test_legal_action_engine_boundary_audit` | 실행 가능 8 → 9 · 후보 생성기 5 → 6 · **낼 수 있는 종류는 일곱 그대로** (`_special_summon_actions` 는 여전히 **없다**) |
| `test_official_activation_player_action_contract` | 몬스터 효과 등재 2 → 3 · `executable` 의 `ordinal` 분포 `{0: 15, 1: 1}` · 금지 항목 셋은 여전히 없다 |
| `test_opening_duel_integration` | `combo_messages` · `combo_texts` 에 `line_text` 가 **맨 뒤**에 붙었다 (기본값 `""` — 예전 호출이 그대로 돈다) |
| `test_deck_builder_planner` 쪽 정적 계획 문구 | `deck/planner.py` 의 "엔진이 구조적으로 지원하지 않는 절차" 목록에서 특수 소환 · 링크 소환 줄을 **정정**했다 — 둘 다 좁은 범위에서 실제로 실행된다 |


### 10.3 측정 결과

(아래 §10.4 에 명령 · passed/failed/skipped · 종료 코드 · 소요 시간을 적는다.)

---

## 11. `/combo` 로 재현하는 방법

Discord:

```
/combo hand:69811710,703897,2930675,12989604,93920420 line:orcust-girsu recipe:<아래 YDK>
```

CLI (`recipe` 는 `.ydk` 파일 경로도 받는다):

```
python -m app.main combo "69811710,703897,2930675,12989604,93920420" \
    --recipe orcust-verification.ydk --line orcust-girsu
```

`orcust-verification.ydk`:

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

같은 레시피와 패가 `deck.combo_policy.ORCUST_VERIFICATION_RECIPE` ·
`ORCUST_VERIFICATION_HAND` 에 있고, 사람이 읽는 표는
`ORCUST_VERIFICATION_RECIPE_KO` 다. 🔴 **세 상수 중 어느 것도 `recipe:` 를
생략한 요청에 자동으로 쓰이지 않는다.**

`line:` 을 주지 않으면 `first_meaningful` 로 돌고, 그때는 3 단계까지 간 뒤 세트로
이어진다 (링크 소환은 그 순서에 없다).

### 11.1 Discord 출력 길이 (기존 한계)

실측 (`combo_messages` 의 문자열, 토큰 없이 생성):

| 입력 | 메시지 | 각 메시지 글자 | 줄 | 글자 | 못 보낸 줄 |
| --- | --- | --- | --- | --- | --- |
| `line:` 없음 | 4 | 1,918 · 1,987 · 1,995 · 1,964 | 147 | 7,867 | 6 |
| `line:orcust-girsu` | 4 | 1,826 · 1,912 · 1,946 · 1,929 | 144 | 7,616 | 6 |

못 보낸 줄은 **조용히 사라지지 않는다** — 마지막 메시지가
*"… (길이 제한으로 6줄을 보내지 못했습니다)"* 를 적는다 (실측, 두 입력 모두).

🔴 **잘림은 이 Phase 가 만든 것이 아니다** — 보완8 마무리 시점에도 같은 자리가
잘려 있었고, `/combo` 는 메시지 4개 · 각 2,000자의 상한을 쓴다. `line:` 쪽이
**더 짧다** (정적 계획의 선택 방식 설명 세 줄이 경로 요약 세 줄로 바뀐다).

---

## 12. 다음 단계가 붙을 자리

이 Phase 는 **그 기능들을 만들지 않았다.** 붙을 **자리**가 어디인지만 적는다.

| 다음 단계 | 붙을 자리 |
| --- | --- |
| 레시피 자동 구성 | `deck/builder.py DeckBuilder.build(request)` → `build_opening(repository, draft, hand, …)` 의 `draft` 자리. 지금 `/combo` 의 `deck:` 이 초안을 만들지만 **실행에 쓰지 않는다** (사용자가 확정한 덱이 아니다) |
| 전개 탐색 | `execute_opening(choose=…)` 의 `choose` 자리. `VerificationLinePolicy` 가 지금 그 자리를 **적어 둔 경로로** 채우고 있고, 탐색기는 같은 서명(`(duel, legal) -> PlayerAction | None`)을 만족하면 된다 |
| 범용 LLM 전략 선택 | 같은 `choose` 자리 + 해결 중의 선택은 `agent/choice.py` 의 `FirstPermittedChoice` 자리 (`integration.autonomy.PolicyChooser`) |
| 웹 검색 · 외부 시뮬레이터 | `deck/report.py` 의 `render_simulator_steps` 가 **사람이 할 조작**을 적는 자리이고, 지금 그 출력은 안내문이다. 실제 전송 경로는 없다 |
| 링크 소환 범위 확대 | `engine/link_rules.py LINK_MATERIAL_RULES` 에 줄을 더한다 (근거 필수). 장수가 범위인 카드는 **장수를 고르는 계층**이 먼저 필요하다 |
| 특수 소환 범위 확대 | `OPERATION_RULINGS` 의 `MAY_BE_SPECIAL_SUMMONED` 와 `REVIVAL_LIMIT_FREE_ZONES`. 묘지·제외를 열려면 **소환 이력**을 적는 자리가 먼저 필요하다 |

🔴 **다음 단계를 자동으로 시작하지 않았다.**
