# 필드의 토큰 · 갈라테아i 가 다른 소환 판정을 가리던 자리 (Phase 6-AP)

기준 HEAD: `38a3644e590f2cefc576e4d3f4f8cd80ced3072e`

이 문서는 **디스코드 실제 실행에서 사용자가 관측한 두 ``UNKNOWN``** 의 원인과
수정, 그리고 **토큰의 링크 소재 처리**를 적는다. 과거 측정값은 보존하고 이번
실측과 구분한다.

---

## 1. 디스코드에서 관측한 증상

사용자 입력 (그 외 옵션은 비웠다):

```
hand:   69811710,703897,2930675,12989604,61654098
recipe: 69811710 x3, 93920420 x3, 57835716 x3, 21441617 x3, 94046012 x3,
        40441990 x3, 2930675 x3, 90351981 x3, 26845680 x3, 61654098 x3,
        703897 x3, 12989604 x3, 55051920 x2, 47171541 x2,
        extra: 30741503 x1, 48835607 x1, 76145142 x1, 93854893 x1,
               74820316 x1, 3134857 x1
search: galatea
```

**기본 실행** — 기르수 일반 소환 → 기르수 ① 로 디베르를 묘지로 → 기르수 ③
으로 성유물 토큰 생성 → 그 뒤 **디베르 발동이 후보에서 빠졌다**:

```
gated-candidate-eligibility
"MZONE 의 46647145 에 대해 확인된 것이 없어, 그것이 막는지 알 수 없습니다."
```

마법 · 함정을 세트한 뒤 `not_chosen` 으로 끝났다. 🔴 **그 자리에
`link_summon` 후보도 있었다** — 그래서 이번 수정으로 기본 정책이 반드시 링크
소환까지 고른다고 가정하지 않는다 (§6 의 한계).

**별도의 제한 탐색** — 기르수 → 디베르 → 스켈레촌 → 갈라테아 도달과 새 초기
상태에서의 4걸음 재생이 **성공**했고 최종 해시가
`e66020d1c942d059bea4d578bfd68c5d6479b6b571ff4b958ad88815da3998d0`,
노드 28개 · 197.899초였다. 다른 분기에서 같은 종류의 미지원이 기록되었다:

```
"EMZONE 의 48835607 에 대해 확인된 것이 없어, 그것이 막는지 알 수 없습니다."
```

🔴 **이 기록은 사용자 환경의 실측이다.** 아래 §2 가 현재 구현에서도 같은
원인인지 먼저 확인한 결과다.

---

## 2. 두 UNKNOWN 의 실제 발생 원인

### 2.1 같은 계층이다

둘 다 :meth:`engine.effect.ruling.BoardRuling._interference` 다. 그 함수는
판의 **간섭 가능 자리**(`INTERFERENCE_ZONES`)를 훑으면서, **확인된 사실이
없는 앞면 카드**를 하나라도 만나면 그 자리에서 멈추고 ``UNKNOWN`` 을
돌려준다 — "아무도 안 막는다" 는 판 전체를 다 읽었을 때만 할 수 있는 말이기
때문이다 (ADR-006 의 기본값).

```
BoardRuling.explain_special_summon(후보)
  ├ 그 카드 자신이 무엇을 말하는가   (CardRuleFacts)
  └ 판에 막을 수 있는 것이 있는가    ← _interference, 여기서 UNKNOWN
        └ _facts_of(card)
             ① OPERATION_RULINGS.facts_for(card_id)   손으로 적은 등록소
             ② rulebook_facts(card.definition)        룰북 한 줄로 유도
```

🔴 **기존 금지 판정표가 다시 UNKNOWN 으로 바뀐 것이 아니다.** 금지 판정표
(`engine.summon_restriction.SPECIAL_SUMMON_PROHIBITIONS`) 와 이 등록소
(`engine.effect.library.OPERATION_RULINGS`) 는 **다른 표**이고 다른 질문에
답한다. 토큰 데이터가 관측에 전달되지 않은 것도 아니다 — 관측은 토큰의 종류를
제대로 실어 보냈다 (실측: `types=['MONSTER','NORMAL','TOKEN']`).

### 2.2 A — 성유물 토큰 46647145

:func:`engine.effect.ruling.token_facts` 가 **6-AF 에 이미 적혀 있었고
production 에서 한 번도 불리지 않았다.** `rulebook_facts` 는 토큰을 일부러
제외했고 (`NOT_PLAIN_NORMAL = {"PENDULUM", "TOKEN"}`), 그 자리에 "토큰은
`token_facts` 가 따로 답한다" 는 주석이 있었다 — **그 "따로" 가 연결되지
않았다.**

```
실측 (수정 전, 기준 HEAD):
  rulebook_facts(토큰 관측)            → None
  OPERATION_RULINGS.facts_for(46647145) → None
  explain_special_summon(덱의 스켈레촌) → UNKNOWN
      "MZONE 의 46647145 에 대해 확인된 것이 없어, …"
  디베르 ① 후보 목록                    → 없음 (gated-candidate-eligibility)
```

### 2.3 B — 오르페골 갈라테아i 48835607

이 카드는 **등록소에 줄이 없었다.** 금지 표에는 6-AF 가 적어 두었지만
(`prohibits=False`), 그것은 "특수 소환 자체를 막는가" 에 답하는 **다른
표**다. `rulebook_facts` 도 답할 수 없다 — `EFFECT`·`LINK` 몬스터이므로 룰북의
통상 몬스터 한 줄이 적용되지 않는다.

```
실측 (수정 전, 기준 HEAD):
  explain_special_summon(덱의 스켈레촌) → UNKNOWN
      "EMZONE 의 48835607 에 대해 확인된 것이 없어, …"
```

---

## 3. 확인한 카드별 근거와 수정 계층

### 3.1 성유물 토큰 46647145

| 무엇 | 실측 |
|---|---|
| 카드 데이터 | `MONSTER\|NORMAL\|TOKEN` · setcode `0xfe`(성유물) · 어둠 속성 · 기계족 · 레벨 1 · 0/0 |
| 생성 규칙 | `c69811710.lua` 의 `s.tkop` — `CreateToken` 두 번, `SpecialSummonStep(tk1,0,tp,tp,…)` 과 `SpecialSummonStep(tk2,0,tp,1-tp,…)`, `POS_FACEUP_DEFENSE`. **서로의 필드에 1장씩**이고 컨트롤러가 다르다 |
| 부여되는 제약 | **없다** — `s.tkop` 은 토큰에 아무 `RegisterEffect` 도 하지 않는다 |
| 토큰 전체 | `data/cards.cdb` 의 토큰 **241장** 중 **238장이 정확히 `MONSTER\|NORMAL\|TOKEN`** 이고 그 238장 **전부 `c*.lua` 가 없다**. 남은 3장은 `type` 이 `0x4000` 뿐인 자리표시자(9995767 · 10000110 · 10000120)이고 몬스터로도 적혀 있지 않다 |

**수정 계층**: `engine/effect/ruling.py` 의 :func:`rulebook_facts` 가 관측된
**종류**만 보고 토큰이면 :func:`token_facts` 를 돌려준다.

🔴 **"토큰이니까 제약이 없다" 로 적지 않았다.**

- `token_facts` 가 답하는 것은 룰북이 **이름을 댄 네 자리**뿐이다 (패 · 묘지 ·
  덱 · 버리기 → 전부 `FALSE`). **제외와 특수 소환 가능 여부는 답하지
  않는다** — 룰북이 이름을 대지 않았다.
- `restricts_others=False` 의 근거는 룰북의 「토큰은 필드의 통상 몬스터로
  취급된다」 한 줄이고, 위 표의 238/241 · 스크립트 0장이 그 줄이 성립하는
  범위다.
- **효과를 가진 토큰은 이 줄이 답하지 않는다** (`TOKEN_NOT_PLAIN =
  {"EFFECT", "PENDULUM"}`). 지금 0장이지만, 생기는 날 조용히 "효과 없음" 으로
  읽히면 틀린다.

### 3.2 오르페골 갈라테아i 48835607

`c48835607.lua` 의 등록 효과 **다섯 개를 하나하나 읽었다**.

| 효과 | 무엇을 하는가 | 남을 막는가 |
|---|---|---|
| 링크 절차 | `Link.AddProcedure(..., IsSetCard{SET_ORCUST,SET_WORLD_LEGACY}, 1, 1)` | — (이미 `LINK_MATERIAL_RULES` 에 등록) |
| `e1` | `EVENT_SPSUMMON_SUCCESS` → `s.regop` 이 `EFFECT_CANNOT_SPECIAL_SUMMON` 을 건다. `SetTarget` 이 `c:IsCode(id) and sumtype&SUMMON_TYPE_LINK` — **「갈라테아i」 자신의 링크 소환만** | **아니다.** 그리고 **필드에 있다는 것만으로 걸리지 않는다** — 이 카드를 링크 소환했을 때 걸리고, 이 저장소는 그것을 `engine.link_rules.LINK_SUMMON_ONCE_PER_TURN` + `GameState.summon_uses` 로 따로 들고 판정한다 (6-AF) |
| `e2` | `EFFECT_CANNOT_BE_XYZ_MATERIAL` — **자기 자신**이 엑시즈 소재가 되지 못한다 | 아니다 |
| `e3` · `e3a` | 덱 · 묘지의 「성유물」 몬스터나 「오르페골 바벨」 을 패에 | 아니다 |
| `e4` · `e4a` | 자신을 묘지에서 특수 소환 | 아니다 |

**수정 계층**: `engine/effect/library.py` 의 `OPERATION_RULINGS` 에
`CardRuleFacts(card_id=48835607, restricts_others=False, …)` 한 줄.

🔴 **이 카드의 효과를 구현한 것이 아니다.** `e3` · `e4` 는 `EFFECT_LIBRARY`
에 **없고** 이 저장소에서 발동될 수 없다. 이 줄이 주장하는 것은 **「필드에
있다는 것만으로 다른 카드의 조작을 막는가」 하나**이고, 질문별 답
(`answers`) 은 **하나도 적지 않았다** — 읽지 않은 것을 적지 않는다.

### 3.3 두 구분을 섞지 않았다

| 질문 | 어디서 답하는가 |
|---|---|
| 필드에 **존재하는 것만으로** 다른 소환을 막는가 | `CardRuleFacts.restricts_others` (이번에 더한 두 줄) |
| 그 카드의 **효과를 사용해서** 제한이 생겼는가 | `GameState.summon_limits` (디베르 ①) · `GameState.summon_uses` (갈라테아i 의 1턴 1번 링크 소환) |
| 그 카드가 **특수 소환 자체를** 막는가 | `SPECIAL_SUMMON_PROHIBITIONS` (파키세팔로 등) |

---

## 4. 토큰의 링크 소재 허용 · 거절 조건

🔴 **이미 올바르게 구현되어 있었다 (6-AF).** 다시 쓰지 않고 **실제 후보와
실행 결과로 확인했다.** 토큰을 일괄 제외하지도, 일괄 허용하지도 않는다 —
`MaterialRequirement.holds` 가 **카드 종류와 카드군**으로 판단한다.

| 링크 몬스터 | 등록된 소재 조건 (근거) | 성유물 토큰 | 실측 |
|---|---|---|---|
| 오르페골 갈라테아i (48835607) | 「오르페골」 **또는** 「성유물」 몬스터 1장 · 링크 1 (`c48835607.lua` 의 `Link.AddProcedure`) | **허용** — 토큰의 setcode 가 `0xfe`(성유물)다 | 후보 목록에 `(46647145,)` 가 오르고 실행도 수락 |
| 오르페골 갈라테아 (30741503) | **효과** 몬스터 2장 (「오르페골」 포함) · 링크 2 (`Card.IsType(TYPE_EFFECT)`) | **거절** — 토큰은 `TYPE_NORMAL` 이다 | 후보 목록에 토큰이 든 조합이 **없고**, 손으로 만든 행동은 `LINK_MATERIAL_INVALID` · "효과 몬스터가 아닙니다" · 판 불변 |
| 오르페골 롱기르수 (76145142) | **효과** 몬스터 2~3장 (「오르페골」 포함) · 기여 합 3 | **거절** — 같은 이유 | 같은 사유로 거절 |

그리고 함께 적용되는 것들 (전부 기존 계층):

- **소재 장수 · 링크 수치 합 · 테마 조건**: `LinkMaterialRule.count` ·
  `count_max` · `link_rating` · `each` · `includes` 를 따로 센다 (6-AG ·
  6-AN).
- **개별 소재 사용 제한**: 갈라테아i 의 1턴 1번 링크 소환은
  `summon_uses` 가 판정한다.
- **소유자 · 컨트롤러 구분**: 기르수 ③ 은 **서로의** 필드에 토큰을 만들고,
  상대 필드의 토큰은 **자신의 링크 소재가 되지 않는다** — 실측: 후보 목록에
  오르지 않고, 손으로 만들어 넣으면 `LINK_MATERIAL_INVALID` · "P1 의
  몬스터입니다 — 링크 소재는 **자신이** 컨트롤하는 몬스터입니다" · 판 불변.
- **기여값**: 토큰은 링크 몬스터가 아니므로 기여 1이다 (6-AG 의
  `link_rating` 계산 그대로).

---

## 5. 토큰 소멸과 이벤트 처리 (실측)

소재로 쓴 토큰은 **묘지로 가지 않고 소멸한다** (`engine/token.py` 의
`vanish_token` — `GameState.move` 를 부르지 않는다).

```
갈라테아i ← 자신의 토큰 1장, 상대 필드에도 토큰 1장이 있는 판

MZONE · EMZONE · GRAVE · REMOVED · HAND · DECK · EXTRA
    → 어디에도 46647145 가 없다 (0장)
state.find_instance(그 개체)         → None   (판에서 사라졌다)
상대 MZONE                           → [46647145]  (건드리지 않았다)

기록:
  P0 의 MZONE 에 있던 토큰 46647145 가 소멸 (어느 존에도 가지 않음)
  — 링크 소재, P0 가 #40 를 EXTRA 에서 EMZONE[0] 로 link 소환 (FACEUP_ATTACK)
summon_uses: ((0, 48835607, 'link', 1),)
```

🔴 **분기 격리**: 사본에서만 소재로 쓰면 원본의 해시가 한 글자도 바뀌지 않고
토큰이 그대로 있다 (실측 — `test_c05`).

---

## 6. 준비된 판과 시작 패부터의 실행 — 구분해서 적는다

### 6.1 준비된 판 (판정 경계)

§2 · §3 · §4 · §5 의 실측은 전부 **시험이 손으로 만든 시작 상태**다 (필드 ·
묘지 · 덱에 카드를 놓는다). 그 자리가 시작 패에서 도달 가능하다고 주장하지
않는다.

### 6.2 시작 패부터 — **기존 시작 패와 레시피 그대로**

`ORCUST_HARP_HORROR_HAND`(= 디스코드 입력과 같은 패) 와 기존
`ORCUST_VERIFICATION_RECIPE` 로 **다섯 걸음이 전부 실제 엔진 행동으로**
수행된다. 새 검증용 고정 경로 `orcust-token-diber` 로 등록했다.

```
python3 -m app.main combo "69811710,703897,2930675,12989604,61654098" \
  --recipe <검증용 레시피>.ydk --line orcust-token-diber
→ 종료 코드 0
→ ✅ 경로를 끝까지 실행했습니다 (5/5단계) · 실행 5걸음 · 상태 변경 5걸음
→ 그중 효과의 조작이 실제로 수행된 걸음 3걸음

  ✔ 1. P0 normal_summon · 잭나이츠 오르페골 기르수 [69811710]
  ✔ 2. P0 activate_effect · 기르수 ① — 덱의 디베르를 묘지로
  ✔ 3. P0 activate_effect · 기르수 ③ — 서로의 필드에 성유물 토큰 1장씩
  ✔ 4. P0 activate_effect · 🔴 토큰이 남은 채 디베르 ① — 덱에서 스켈레촌
  ✔ 5. P0 link_summon · 자신의 토큰을 소재로 오르페골 갈라테아i

최종 판:
  몬스터 존 2장 — 기르수 · 스켈레촌
  엑스트라 몬스터 존 1장 — 오르페골 갈라테아i [48835607]
  묘지 0장 · 제외 1장 (디베르)        ← 토큰은 묘지에 없다
  상대 몬스터 존 1장 — 성유물 토큰     ← 내 소재가 아니었다
  🔴 이 턴에 걸린 특수 소환 제한: 자신 DARK 속성만 (디베르 e[0], 턴 종료까지)
```

🔴 **4 단계가 이 Phase 전까지 막혀 있던 자리다** — 3 단계가 만든 토큰이
디베르의 후보 판정을 `UNKNOWN` 으로 만들었다.

🔴 **순서를 강제한 것이 아니다.** 기르수 ③ 의 공식 조건이 「자신 필드에 이
카드 이외의 몬스터가 존재하지 않을 경우」 이므로 (`c69811710.lua` 의 `e3`
`SetCondition`) 디베르 ① 로 스켈레촌을 세운 뒤에는 토큰을 만들 수 없다 —
**발동 조건이 정한 순서**다. 5 단계가 갈라테아가 아니라 갈라테아i 인 것도
조건이 정한다 (§4 의 표).

### 6.3 갈라테아i 가 필드에 있는 상태의 디베르 발동

**준비된 판에서만 확인했다** (`test_b02`) — 엑스트라 몬스터 존에 갈라테아i 를
놓고 디베르 ① 의 후보 판정이 `TRUE` 이며 후보 목록과 관문이 같은 답을 내는
것을 쟀다. 🔴 **시작 패에서 그 상태로 도달한 전개는 이번에 만들지 않았다** —
`orcust-girsu-token` 이 갈라테아i 를 세우지만 그 경로는 기르수 ① 을 쓰지
않는다 (`declines`).

### 6.4 기본(자율) 실행이 한 걸음 더 간다 (실측)

디스코드 입력과 같은 종류의 패에서 기본 정책의 전개가 **6걸음 → 7걸음**,
효과의 조작 수행 **2 → 3걸음**이 되었다.

```
수정 전: 일반 소환 / 기르수 ① / 기르수 ③ / 세트 x3        (6걸음)
         멈춘 자리의 미지원 2건 — activate_card + 디베르 ①(토큰 때문)
수정 후: 일반 소환 / 기르수 ① / 기르수 ③ / 🔴 디베르 ① / 세트 x3  (7걸음)
         멈춘 자리의 미지원 1건 — activate_card 만 남는다
```

🔴 **기본 정책이 링크 소환까지 고른다고 가정하지 않는다.** `first_meaningful`
의 순서에 `link_summon` 이 없고 (6-AC), 그 자리에 링크 소환 후보가 있어도
고르지 않는다 — 그것은 이번 범위가 아니다.

> 🔴 **Phase 6-AQ 에서 이 수가 다시 바뀌었다 (6걸음 · 효과 수행 2걸음).**
> 위 측정값은 **6-AP 시점의 실측이고 그때 사실이었다.** 6-AQ 가 스켈레촌 ①
> 을 등재하면서 그 카드의 `MAY_BE_SENT_TO_GRAVE` 를 함께 읽어 적었고, 기르수
> ① 의 기준점(`FirstPermittedChoice`)이 **패스코드가 더 작은 스켈레촌**
> (21441617 < 57835716)을 집는다. 스켈레촌 ① 은 「자신 묘지의 "오르페골"
> 몬스터」 를 대상으로 지정해야 하는데 그 자리의 묘지에는 자기 자신뿐이어서
> 발동 후보가 되지 않는다. 🔴 **이전 수치로 되돌리려고 합법 후보를 제거하지
> 않았다** — 보장받는 경로는 `--line` 쪽이다
> (`docs/orcust-skeleton-revival-and-longirsu-line.md` §5 · §7.1).

---

## 7. 기존 탐색 · 재생 결과 (실측 — 유지되었다)

```
python3 -m app.main combo "69811710,703897,2930675,12989604,61654098" \
  --recipe <검증용 레시피>.ydk --search galatea
→ 종료 코드 0 · real 1m18.219s
→ ✔ 도달 · 행동 4걸음 · 해결 중 선택 2회 · 펼친 노드 28개 · 최대 깊이 3
   · 51.53초 · 예산에 걸리지 않았다
→ 경로: 일반 소환 / 효과 발동 (선택 57835716) / 효과 발동 (선택 21441617)
         / 링크 소환
→ 경로 재생 (새 초기 상태에서 다시 실행): ✔ 성공
→ 최종 판 해시 = 재생 최종 해시 =
   e66020d1c942d059bea4d578bfd68c5d6479b6b571ff4b958ad88815da3998d0
```

🔴 **해시 · 노드 수 · 깊이가 6-AO 와 같다** — 이 탐색이 찾은 경로는 기르수 ③
을 쓰지 않으므로 이번 수정이 닿는 갈래를 지나지 않는다. 🔴 **같게 만들려고
합법 후보를 제거한 것이 아니다**: 수정으로 **늘어난** 후보는 기본 실행 쪽에서
보인다 (§6.4).

네 검증용 고정 경로 전부 그대로 돈다:

```
--line orcust-girsu         → 4/4단계
--line orcust-girsu-token   → 4/4단계
--line orcust-harp-horror   → 4/4단계
--line orcust-token-diber   → 5/5단계   (이번에 더한 경로)
```

🔴 **검증용 고정 경로와 일반 탐색은 다른 것이다.** 탐색기에는 카드별 정답
수순이 없고, 그 사실을 `test_e02` 가 `agent/bounded_search.py` 전문에
`orcust-token-diber` · `57835716` · `46647145` · `COMBO_LINES` 가 없는 것으로
센다.

---

## 8. 구현자 테스트 결과

🔴 **아래는 전부 구현자(자동 테스트) 쪽 결과이고, 디스코드 실제 실행과
다른 것이다.** 디스코드 검증 대기 항목은 §9 에 있다.

```
timeout 1200 python3 -m pytest tests/test_token_and_galateai_summon_gates.py \
  -q -rf -p no:randomly
→ 18 passed in 12.71s        (이번 Phase 의 새 시험)

timeout 2400 python3 -m pytest tests/engine -q -rf -p no:randomly
→ 3882 passed in 723.69s      🔴 공용 판정 계층(BoardRuling)을 바꿨으므로
                               그 계층의 기존 사용자 전체로 범위를 넓혔다
                               (중간 1회차는 1 failed — §8.2 의 낡은 기대값)

timeout 2900 python3 -m pytest \
  tests/test_orcust_girsu_line.py tests/test_girsu_token_line.py \
  tests/test_girsu_token_chain_integration.py \
  tests/test_harp_horror_graveyard_effect.py \
  tests/test_longirsu_link_summon.py \
  tests/test_link_material_count_and_rating.py \
  tests/test_resolution_outcome_four_cases.py \
  tests/test_withheld_reason_propagation.py \
  tests/test_summon_prohibition_and_resolution_choice.py \
  tests/test_token_and_galateai_summon_gates.py -q -rf -p no:randomly
→ 249 passed in 308.00s

timeout 2400 python3 -m pytest tests/test_bounded_search_first_pass.py \
  tests/test_bounded_search_multi_results.py \
  tests/test_result_ranking_v1.py tests/test_discord_bot.py \
  -q -rf -p no:randomly
→ 166 passed in 364.55s

timeout 2400 python3 -m pytest tests/test_post_goal_continuation.py \
  tests/test_post_goal_continuation_boundaries.py -q -rf -p no:randomly
→ 46 passed in 842.98s

timeout 900 python3 -m pytest tests/test_combo_output_consistency.py \
  -q -rf -p no:randomly
→ 9 passed in 41.16s
```

### 8.1 새 시험이 재는 것

| 절 | 무엇을 재는가 |
|---|---|
| A (4건) | 토큰의 룰북 사실이 관측에서 닿는다 · **답하지 않은 질문은 그대로 비어 있다** · 효과 있는 토큰은 답하지 않는다 · 내 토큰과 **상대 토큰** 둘 다 판정된다 |
| B (3건) | 갈라테아i 의 줄이 **한 가지만** 주장한다 (효과 구현이 아니다) · 그 카드가 있어도 후보가 산다 · 토큰과 함께 있어도 산다 |
| C (5건) | 조건이 허용하는 곳에서 토큰이 소재가 된다 (후보 ↔ 실행 일치) · **효과 몬스터 조건은 거절한다** · **상대 토큰은 쓰지 않는다** · 소재 토큰이 **어디에도 남지 않는다** · fork 격리 |
| D (4건) | **실제 금지는 그대로 막는다** · **미등록 카드는 여전히 UNKNOWN** (토큰과 함께 있어도) · **디베르의 어둠 속성 제한 유지** · **직전 보완(후보 없음에도 제한 등록) 유지** |
| E (2건) | 시작 패부터 다섯 걸음 · 검증용 고정 경로와 탐색의 분리 |

### 8.2 고친 낡은 기대값 — 왜 이전 기대값이 맞았는가

🔴 **근거 없이 완화한 것이 하나도 없다.** 전부 "그때는 그것이 사실이었고, 이
Phase 가 **읽어서** 사실을 바꿨다" 는 종류다.

| 자리 | 이전 기대 | 바뀐 뒤 | 왜 이전 기대가 맞았는가 |
|---|---|---|---|
| `OPERATION_RULINGS` 수를 세는 **6개 파일** | 25 | **26** | 갈라테아i 한 줄이 늘었다 |
| `COMBO_LINES` 목록 (`test_orcust_girsu_line::test_g04` · `test_girsu_token_line::test_e05`) | 셋 | **넷** (+`orcust-token-diber`) | 검증용 경로가 하나 늘었다 |
| `test_combo_output_consistency::test_06` | 멈춘 자리의 미지원 **2건** (`activate_card` + `57835716:e[0]`) | **1건** (`activate_card` 만) · 토큰 때문에 생기던 보류가 없다 | 그때 그 보류는 정말 있었고, 그 사유가 **디스코드에서 사용자가 본 그 문장**이다 |
| `…::test_07` · `test_08` · `test_trigger_window_completion::test_f02` | `executed` 6 · `effects_resolved` 2 · "6걸음" · "2걸음" | **7** · **3** · "7걸음" · "3걸음" | 토큰 때문에 보류되던 디베르 ① 이 실제로 발동된다 (§6.4). 재는 것은 수가 아니라 **두 수가 다르다는 사실**이고 그것은 그대로다. 🔴 **Phase 6-AQ 에서 다시 6 · 2 · "6걸음" · "2걸음" 이 되었다** — §6.4 의 주석 |

---

## 9. 디스코드 검증 대기

🔴 **실제 디스코드에서는 아직 실행하지 않았다.** 아래는 **검증 대기** 항목이고
통과로 세지 않는다.

| 확인 항목 | 구현자 테스트 | 디스코드 |
|---|---|---|
| 토큰 존재만으로 디베르가 UNKNOWN 되던 문제 해소 | ✅ 실측 | **대기** |
| 갈라테아i 존재만으로 같은 문제 해소 | ✅ 실측 (준비된 판) | **대기** (시작 패에서 그 상태에 도달하는 전개는 §6.3 대로 아직 없다) |
| 실제 소환 금지 · 어둠 속성 제한 유지 | ✅ 실측 | **대기** |
| 미등록 카드 자동 허가되지 않음 | ✅ 실측 | **대기** |
| 토큰 허용 소재 조건에서 후보 ↔ 실행 일치 | ✅ 실측 | **대기** |
| 효과 몬스터 조건 미충족 시 토큰 거절 | ✅ 실측 | **대기** |
| 상대 토큰 무단 사용 안 함 | ✅ 실측 | **대기** |
| 소재 토큰이 다른 존에 남지 않음 | ✅ 실측 | **대기** |
| fork · 재생의 토큰 · 제한 일치 | ✅ 실측 | **대기** |
| 직전 보완(후보 없음에도 제한 등록) 유지 | ✅ 실측 | **대기** |
| 기존 `search:galatea` 도달 · 재생 유지 | ✅ 실측 | **대기** |

**디스코드로 직접 재현할 수 없는 경계** (그래서 구현자 테스트로만 쟀다):

- 발동과 해결 사이에 덱을 비우는 경계 (`test_d04`) — 그 상황을 만드는 등재된
  상대 카드가 없다.
- 상대 필드의 토큰을 소재로 **손으로 만들어** 넣는 거절 (`test_c03`) —
  디스코드 입력에는 불법 행동을 직접 넣을 자리가 없다.
- fork 격리 (`test_c05`) — 내부 사본 동작이다.
- 효과를 가진 토큰 (`test_a02`) — 저장소에 **0장**이다.

---

## 10. 남은 미지원

- **갈라테아i 의 효과는 하나도 등재되지 않았다** — `e3`(패에 넣기) ·
  `e4`(묘지에서 자신을 특수 소환) · 그 둘의 유발즉시 사본. 이번에 더한 것은
  「필드에 있다는 것만으로 남을 막는가」 한 줄뿐이다.
- **스켈레촌 · 카노네의 ①** 은 여전히 미등재 (6-AO §8.2).
- **디베르 ②**(유발즉시) · `EFFECT_FLAG_OATH` 깃발 · 무효화된 바벨 구별 ·
  `aux.RegisterClientHint` — 그대로 미지원 (6-AO §2.3 · §8.1).
- **`activate_card` 의 발동 타이밍** — 기본 실행에서 마지막까지 남는 미지원
  1건이고 6-AB 부터 있던 자리다. 이번에 고치지 않았다.
- **지속 효과 계층이 없다** (STRUCTURAL-76). `restricts_others` 는 참/거짓
  하나이고 "무엇을 어떻게 막는가" 를 적지 않는다 — 막을 수 있는 카드가 판에
  있으면 그냥 `UNKNOWN` 이다.
- **등록되지 않은 카드는 여전히 `UNKNOWN`** 이다. 이번에 읽은 것은 토큰
  238장(종류로)과 갈라테아i 한 장뿐이고, 그 밖의 카드가 필드에 있으면 그
  자리의 판정은 그대로 모름이다 (ADR-006).

### 10.1 후속 과제로만 기록한 것 (이번 범위 밖)

- **기본 실행 결과와 탐색 결과가 한 응답에 섞인다** — 사용자가 `search:` 를
  주면 기본 실행 절과 탐색 절이 함께 나온다.
- **탐색 시간** — 사용자 환경에서 197.899초였다 (이 저장소 측정은 51.53초).
  탐색 최적화는 이번 범위가 아니다.
