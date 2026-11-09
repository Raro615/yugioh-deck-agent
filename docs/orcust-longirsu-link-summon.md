# 오르페골 롱기르수 링크 소환 지원 (Phase 6-AN)

「오르페골 롱기르수」(76145142, LINK-3) 의 **링크 소환 절차**를 엔진이
판정하고 실행할 수 있게 했다.

> 🔴 **이 단계가 지원한 것은 소환 하나다.** 롱기르수의 ①(링크 상태에서의
> 파괴 내성) · ②③(묘지의 기계족 2장을 덱으로) 는 **옮기지 않았다.** 그래서
> 이 문서는 "롱기르수를 소환할 수 있다" 고만 적고 "롱기르수를 지원했다" 고
> 적지 않는다. 두 문장은 다른 뜻이다.

> 🔴 **그리고 아래 §4 의 성공 사례는 손으로 구성한 작은 시작 상태에서 얻은
> 것이다.** 기존 시작 패에서 실제로 무엇에 닿았는지는 **§5** 에 따로 적는다
> — 둘을 섞으면 "준비한 판에서 되었다" 가 "실전 패에서 된다" 로 읽힌다.

관련 문서 — `docs/orcust-girsu-token-line.md`(갈라테아i 등록과 토큰 경로),
`docs/orcust-first-bounded-search.md`(제한 전개 탐색),
`docs/orcust-post-goal-continuation.md`(목표 도달 이후 후속 탐색).

---

## 1. 구현 전에 막혀 있던 지점

### 1.1 자료형이 `2+` 를 적을 수 없었다

`engine/link_rules.py` 의 `LinkMaterialRule.count` 는 6-AM 까지 **정확히 그
장수**였다. 판정도 그렇게 썼다.

```python
if len(materials) != rule.count:        # 6-AM 까지
    return _illegal(f"소재로 고른 몬스터가 {len(materials)}장입니다 …")
```

롱기르수의 소재 줄은 「「오르페골」 몬스터를 포함하는 효과 몬스터 **2장
이상**」 이다. 그래서 **적을 수 있는 수가 없었다**:

- `count=2` 로 적으면 **3장 조합이 거절된다** (실제로 합법인 조합이다).
- `count=3` 으로 적으면 **2장 조합이 거절된다** (기르수 + 갈라테아처럼 링크
  몬스터를 자신의 링크 수치로 세는 조합).

### 1.2 그래서 등록 자체가 없었고, 결과는 `UNKNOWN` 이었다

6-AN 이전 등록표는 두 장이었다 (실측 — `git show HEAD:engine/link_rules.py`
의 `card_id=` 두 줄):

```
6-AN 이전 등록표: [30741503, 48835607]
```

검증용 오르페골 레시피의 엑스트라 덱 6장 중 **4장**이 미등록이었고 (실측,
같은 측정):

```
미등재: [3134857, 74820316, 76145142, 93854893]   # 오케스트리언 · 엔릴기르수 · 롱기르수 · 딩기르수
미등재 수: 4
```

미등록이면 소재 조건을 **모른다**(`UNDETERMINED`) 이므로 후보가 만들어지지
않고, `/combo` 는 그 사실을 미지원 사유로 적었다 — 즉 **이전에 롱기르수가
후보가 되지 못한 이유는 "소재 조건을 읽지 않았다" 하나였다**:

```
link_summon [link-material-requirement (이 링크 몬스터의 소재 조건을 아직 읽지 않았다)]:
  엑스트라 덱 카드의 링크 소재 조건을 이 저장소가 아직 읽지 않았습니다.
  장수와 링크 수치만 맞춰 통과시키지 않으므로 후보를 만들지 않았습니다.
```

🔴 **그 거절은 옳았다.** 장수와 링크 수치만 맞춰 통과시키면 카드가 실제로
요구하는 조건을 지키지 않은 소환을 허가한다 (ADR-006).

---

## 2. 소재 조건의 근거와 구조화

### 2.1 읽은 근거

| 무엇 | 어디 |
|---|---|
| 소재 절차 | `c76145142.lua` 의 `Link.AddProcedure` 와 `s.matcheck` |
| 링크 수치 · 종류 · setcode | `data/cards.cdb` (`repository.get(76145142)`) |
| 공식 한국어 텍스트 | `data/ko/ko-KR.json` |
| 「오르페골」 의 setcode | `data/constants/archetype_setcode_constants.lua:395` (`SET_ORCUST = 0x11b`) |

공식 스크립트 원문:

```lua
Link.AddProcedure(c,aux.FilterBoolFunctionEx(Card.IsType,TYPE_EFFECT),2,nil,s.matcheck)
function s.matcheck(g,lc,sumtype,tp)
	return g:IsExists(Card.IsSetCard,1,nil,SET_ORCUST,lc,sumtype,tp)
end
```

카드 데이터 실측:

```
76145142 오르페골 롱기르수 | MONSTER,EFFECT,LINK | setcodes ['0x11b'] | link 3
```

### 2.2 네 수를 따로 적는다

`Link.AddProcedure(c, filter, min, max, matcheck)` 의 자리를 그대로 읽으면
넷이 나오고, **섞지 않는다**:

| 읽은 것 | Lua 의 자리 | 이 저장소의 자리 | 값 |
|---|---|---|---|
| **고른 카드의 장수** (최소·최대) | `min=2` · `max=nil` | `count` · `count_max` | 2 · 3 |
| **링크 수치에 기여하는 합** | 카드 데이터의 링크 수치 | `link_rating` | 3 |
| **소재 각각의 조건** | `Card.IsType(TYPE_EFFECT)` | `each` | 효과 몬스터 |
| **소재 집합에 포함되어야 하는 조건** | `s.matcheck` 의 `IsSetCard(SET_ORCUST)` | `includes` | setcode `0x11b` |

🔴 **「최소 소재 장수」 와 「링크 수치 합」 은 다른 수다.** 롱기르수에서 그
둘은 2 와 3 이고, 등록된 앞의 두 카드에서는 같았다 (갈라테아 2·2,
갈라테아i 1·1) — 같았기 때문에 6-AG 까지 그 구분이 **측정되지 않았다.**

### 2.3 `max=nil` 을 무한으로 읽지 않은 이유

링크 소환은 기여의 합이 링크 수치에 **정확히** 닿아야 한다. 소재 한 장의
최소 기여는 1 이므로 (링크 몬스터도 1 로 **셀 수 있다**), 소재가
`link_rating` 장보다 많으면 합이 반드시 `link_rating` 을 넘는다. 그래서
상한은 **링크 수치**이고, 그 추론을 자료형이 고정한다:

```python
if self.count_max > self.link_rating:       # LinkMaterialRule.__post_init__
    raise ValueError(
        f"{self.card_id}: 소재 장수의 위쪽 끝 {self.count_max} 가 "
        f"링크 수치 {self.link_rating} 보다 큽니다 — 소재 한 장은 최소 1 로 "
        "세므로 그 장수로는 기여의 합을 맞출 수 없습니다."
    )
```

🔴 **카드별 예외가 아니라 규칙에서 나온 수다.** 그래서 다음 `2+` 카드도 같은
방식으로 상한을 얻는다.

### 2.4 옮기지 못한 조건 (생략하지 않고 적는다)

- `s.matcheck(g,lc,sumtype,tp)` 의 뒤 세 인자(소환될 카드 · 소환법 ·
  플레이어)를 `Card.IsSetCard` 에 넘기는 축을 **옮기지 않았다.** 「그 소환에
  한해 카드군을 얻는」 효과가 깔린 판에서는 이 저장소가 **더 적게 허가한다** —
  거짓 허가가 아니라 거짓 거절이고, `LinkMaterialRule.note` 에 그 문장이
  적혀 있다.
- 롱기르수에는 `EFFECT_CANNOT_SPECIAL_SUMMON` 류의 「1턴에 1번만 링크 소환」
  제약이 없으므로 `LINK_SUMMON_ONCE_PER_TURN` 에 **등록하지 않았다**
  (갈라테아i 와 다른 점이다). ②의 `SetCountLimit(1,id)` 는 **효과의 사용
  제한**이고 소환 횟수가 아니다.

---

## 3. 지원한 판정 · 실행 범위

### 3.1 자료형이 늘어난 자리 (`engine/link_rules.py`)

```python
count_max: "int | None" = None      # None 이면 count 와 같다 = 정확히 그 장수
```

| 새 이름 | 하는 일 |
|---|---|
| `max_count` | `count_max or count` |
| `exact_count` | `max_count == count` (6-AN 이전의 모든 등록이 참) |
| `accepts_count(n)` | `count <= n <= max_count` |
| `counts()` | `(count … max_count)` — **후보 생성이 도는 장수들** |
| `count_ko()` | 「정확히 2장」 / 「2장 이상 3장 이하」 |

🔴 **기본값이 `None` 이므로 기존 등록은 한 글자도 바뀌지 않는다.** 갈라테아 ·
갈라테아i 는 여전히 `exact_count is True` 이고 `counts()` 가 한 값이다
(`test_d01` · `test_d02` 가 그것을 센다).

### 3.2 판정이 바뀐 자리 (한 수)

```python
if not rule.accepts_count(len(materials)):
    return _illegal(
        f"소재로 고른 몬스터가 {len(materials)}장입니다 — "
        f"{rule.card_id} 는 {rule.describe_ko()} 입니다 ({rule.count_ko()})."
    , rule)
```

판정의 **순서는 그대로다** — 장수 → 소재 각각 → 집합 → 기여의 합 → 배치 →
특수 소환 금지의 모름. 그래서 거절 사유가 "무엇을 바꿔야 하는가" 를 그대로
가리킨다.

### 3.3 후보 생성이 바뀐 자리 (`engine/duel.py::_link_summon_actions`)

```python
for size in rule.counts():                      # 6-AN: 장수가 범위면 여러 번 돈다
    for picked in combinations(field, size):
        verdict = validator.validate(PlayerAction.link_summon(...))
```

🔴 **후보 생성과 검증이 같은 판정을 쓴다.** 후보를 만들 때도
`validator.validate` 를 지나므로, 손으로 조립한 행동과 목록에서 고른 행동이
같은 검사를 받는다 (`test_a14` 가 모든 부분집합을 열거해 **집합으로**
비교하고, `test_b04` 가 손으로 조립한 거절이 판을 바꾸지 않는 것을 센다).

🔴 **카드 ID 로 통과시키는 분기는 없다.** 등록표에 없는 링크 몬스터는 여전히
`UNDETERMINED` 이고 후보가 0건이다 — 같은 레시피 · 같은 카드군 · 같은 엑스트라
덱의 엔릴기르수(LINK-4) 로 그것을 센다 (`test_d03`).

### 3.4 사용자 출력 (`app/main.py`)

기존 목표 이름표에 한 줄이 늘었다. **새 명령도 새 인자도 없다.**

```python
SEARCH_GOALS: dict = {
    "galatea": 30741503,
    "longirsu": 76145142,      # Phase 6-AN
}
```

그래서 `--search longirsu` / `/combo search:longirsu` 가 기존 흐름 그대로
돈다 (`test_c02`).

---

## 4. 소환 자체의 통합 검증 — **준비한 작은 상태**

> 🔴 **이 절의 시작 상태는 손으로 구성한 것이다.** `tests/
> test_longirsu_link_summon.py::_board` 가 메인 몬스터 존 · 엑스트라 몬스터
> 존 · 엑스트라 덱 · 패를 직접 채운다. **이 판이 기존 시작 패에서 도달
> 가능하다고 주장하지 않는다** — 그 질문의 답은 §5 다. 첫 행동 **뒤의** 모든
> 변화는 엔진이 만들었고, 성공 사례를 만들기 위해 빈 존이나 소재를 중간에
> 만들어 넣지 않았다.

### 4.1 두 장으로 (최소 장수)

시작: 메인 몬스터 존 기르수 · 엑스트라 몬스터 존 갈라테아 · 엑스트라 덱
롱기르수.

- 판정 `LEGAL`, 후보 **1건**, 검증기 `VALID` (세 계층이 같은 답)
- 실행 뒤 (실측): `EMZONE [76145142]` · `MZONE []` ·
  `GRAVE [69811710, 30741503]` · `EXTRA []` · 앞면 공격 표시
- `summon_uses(롱기르수, link) == 1`

🔴 **갈라테아가 소재이므로 엑스트라 몬스터 존(칸 1개) 이 비고 그 칸에
들어간다.** 배치를 소재가 떠나기 **전**의 판으로 셌다면 이 소환은 "자리가
없다" 로 막혔을 것이다 (`assess_link_placement` 가 떠난 뒤의 판을 센다).

### 4.2 세 장으로 (최대 장수)

시작: 기르수 · 『성장』 · 『성장』, 엑스트라 덱 롱기르수 + 엔릴기르수.

- 실행 뒤 (실측): `EMZONE [76145142]` · `MZONE []` ·
  `GRAVE [69811710, 93920420, 93920420]` · `EXTRA [74820316]`
- 소환한 것만 나온다 — 엔릴기르수는 엑스트라 덱에 **그대로** 있고
  `summon_uses(엔릴기르수) == 0`

### 4.3 소재가 묘지로 간 사건이 유발을 연다

같은 3장 소환에서 소재로 간 성유물－『성장』 두 장이 **각각** 자신의
`EVENT_TO_GRAVE` 유발(②) 기회를 열었다 (실측 — 관문 다섯이 모두 통과):

```
TriggerOffer(effect_ref=EffectRef(card_id=93920420, ordinal=1), source=InstanceId(41),
  requirement=OPTIONAL,
  reason='event_relation=valid; activation_zone=valid; trigger_condition=valid;
          execution_authority=valid; cost_feasibility=valid',
  event=TimingEvent(CARD_MOVED, ZoneMoved(send_to_grave, MZONE → GRAVE)))
… 같은 모양으로 InstanceId(42) 에 하나 더
```

그리고 **흐름이 그 기회를 건너뛰지 않는다** — 유발 처리 기회가 열려 있는
동안 페이즈를 넘기는 수가 보류된다.

🔴 **그 뒤에 막히는 것은 롱기르수와 무관한 자리다.** 패의 성유물－『성관』 을
지금 특수 소환할 수 있는지(`may_be_special_summoned`) 는 이 엔진이 답하지
못하는 질문이므로 (소환 이력을 적는 자리가 없다 — 6-AD), 발동 후보로는
오르지 않고 **보류에 그 이유가 적힌다**:

```
activate_effect | rule_not_implemented | gated-candidate-eligibility
  93920420:e[1] 의 발동 기회가 열렸지만 발동 관문을 지나지 못했습니다:
  … 후보 1장이 있지만 그중 지금 may_be_special_summoned 가 참인 것을 확인하지 못했습니다
```

두 사실을 섞지 않는다 — **사건과 기회는 열렸고**, 막힌 것은 **다른
미지원**이다 (`test_b03`).

### 4.4 원본과 사본

- 거절은 판 · 소환 기록 · 모든 존을 **한 칸도** 바꾸지 않는다 (`test_b04`)
- `Simulator.fork()` 에서 소환해도 원본은 그대로다 (`test_b05`)

### 4.5 탐색과 재생 (준비한 상태에서)

```
reached True · termination goal_reached · 1.6초
  step: 1. link_summon (… materials (41, 40))
  필수 P0 패스 · 필수 P1 패스 (no-interference)
원본 불변: True
rerun ok True — 걸음 1 · 목표 True · 탐색 결과와 일치 True
```

재생은 `_board` 를 **다시 불러** 만든 초기 상태에서 돌았다 (같은 입력 · 같은
씨앗). 탐색기 안에는 "롱기르수면 이렇게" 같은 분기가 없다 — 목표 판정은
`FieldGoal` 하나이고 후보는 엔진이 허가한 것뿐이다 (`test_c01`).

---

## 5. 기존 시작 패에서의 실제 탐색 결과

입력은 **바꾸지 않았다** — `deck/combo_policy.py` 의
`ORCUST_VERIFICATION_RECIPE`(메인 40 · 엑스트라 6) 와
`ORCUST_VERIFICATION_HAND`(기르수 · 클리막스 · 열쇠 · 자각 · 『성장』) 그대로다.

### 5.1 등록 상태의 변화

같은 엑스트라 덱 6장에 대한 실측:

| | 미등록 | 목록 |
|---|---|---|
| 6-AN 이전 | **4장** | 오케스트리언 · 엔릴기르수 · **롱기르수** · 딩기르수 |
| 6-AN 이후 | **3장** | 오케스트리언 · 엔릴기르수 · 딩기르수 |

`/combo` 의 보류 문장도 그대로 따라 바뀐다 — 실행 로그가
`엑스트라 덱 6장 중 3장이 같은 이유` 라고 적는다 (이전에는 4장이었다).

### 5.2 목표를 롱기르수로 둔 탐색 — **예산 안에서 찾지 못했다**

```
python3 -m app.main combo "69811710,703897,2930675,12989604,93920420" \
  --recipe <검증용 레시피>.ydk --search longirsu
```

```
✗ 미도달 — 예산 초과로 멈췄습니다
행동 0걸음 · 펼친 노드 161개 · 최대 깊이 8 · 301.38초
예산에 걸린 칸: max_depth=8 · max_seconds=300
```

🔴 **찾지 못한 것을 불가능하다고 적지 않는다.** 종료 사유는 **예산**이다.

### 5.3 닿은 상태에서의 정확한 거절 사유 — **소재 부족**

예산과 별개로, 실제 시작 패가 **닿은 상태들**에서 롱기르수의 모든 소재
조합을 전수로 판정했다 (실측):

**(a) 검증용 선택 방식(`execute_opening`) 이 멈춘 자리** — 필드 2장
(기르수 · 『성장』), 둘 다 기여 `{1}`:

```
롱기르수 후보: 0건
[illegal] 1장 :: 소재로 고른 몬스터가 1장입니다 — … (2장 이상 3장 이하).
[illegal] 2장 :: 고른 소재 2장으로 만들 수 있는 기여의 합은 2 이고
                 76145142 의 링크 수치 3 에 닿지 않습니다 …
허가된 링크 소환 전부: [갈라테아 ← (기르수, 『성장』), 갈라테아i ← (기르수), 갈라테아i ← (『성장』)]
```

**(b) 그 자리에서 갈라테아를 링크 소환한 뒤** — 필드 1장 (갈라테아, 기여
`{1, 2}`):

```
롱기르수 후보: 0건
[illegal] 1장 :: 소재로 고른 몬스터가 1장입니다 — … (2장 이상 3장 이하).
허가된 링크 소환 전부: []
```

즉 **이 패가 닿은 자리에서의 거절 사유는 소재 부족**이다 — (a) 는 기여의 합이
2 에서 멈추고 (둘 다 1 만 기여), (b) 는 필드에 한 장뿐이라 장수 조건(2장
이상) 을 못 채운다. **소재 조건 미등록도, 소환 절차 미지원도 아니다.**

### 5.4 후속 전개 탐색에서도 나오지 않았다

```
python3 -m app.main combo "…" --recipe <…>.ydk --search galatea --results 3 --followups 2
```

```
검증된 서로 다른 결과 4개 · 최초 목표 도달: 예 — 기준점 1개
재생 검증된 후속 후보 3개
  [결과 2] 기준점 걸음 4 뒤에 더 한 것: 링크 소환
      → 기록된 사용 제한 차이: P0 summon [48835607] link ×1   ← 갈라테아i 다
  [결과 3] · [결과 4] 마법·함정 세트
```

후속으로 발견된 링크 소환은 **갈라테아i** 였다. 기준점 상태의 필드가 갈라테아
한 장이므로 §5.3(b) 와 같은 이유로 롱기르수는 후보가 되지 않는다.

### 5.5 그래서 세 가지를 구분해 적는다

| 구분 | 이번 측정의 답 |
|---|---|
| **소재 부족** | 🔴 닿은 자리들에서의 거절 사유가 이것이다 (§5.3) |
| **다른 효과의 미지원** | 같은 실행에 3건이 남아 있다 (§6.2) — 그 수단이 열리면 세 번째 몬스터를 세울 길이 생길 수 있다 |
| **탐색 예산** | 목표를 직접 둔 탐색이 깊이 8 · 300초에서 끊겼다 (§5.2) |

🔴 **"기존 시작 패로는 롱기르수를 소환할 수 없다" 고 적지 않는다.** 이번
측정은 "검증용 선택 방식이 닿은 자리들에서는 소재가 부족했고, 예산 안의
탐색은 다른 경로를 찾지 못했다" 까지다.

---

## 6. 아직 막히는 기능

### 6.1 이 카드에 대해

- **롱기르수의 효과 ①②③ 은 등록하지 않았다.** 소재 조건 등록표
  (`LINK_MATERIAL_RULES`) 에는 효과를 적는 칸이 없고 (`test_a15` 가 그 사실을
  센다), 효과 등록표(`EFFECT_LIBRARY`) 에 이 카드는 없다.
- `s.matcheck` 의 `lc, sumtype, tp` 축을 옮기지 않았다 (§2.4) — 그 축이
  필요한 판에서 **더 적게 허가한다**.
- **링크 마커의 칸 기하를 옮기지 않았다.** 엑스트라 몬스터 존이 차 있고 소재가
  그 칸을 비우지 않는 조합은 `UNDETERMINED` 이고 (`link-placement-linked-zone`),
  이번 단계도 그것을 열지 않았다 (`test_a13`).

### 6.2 같은 실행에 남아 있는 다른 미지원 (실측, §5.2 의 실행)

```
link_summon [link-material-requirement]: 엑스트라 덱 카드의 링크 소재 조건을
  이 저장소가 아직 읽지 않았습니다 … (6장 중 3장)
activate_card [activation-timing (Phase 2-C/2-F)]: activate_card 의 남은
  적법성을 판정할 규칙 계층이 아직 없습니다
activate_effect [facedown-monster-effect]: 69811710:e[2] 를 지금 발동할 수
  없습니다: 아직 구현하지 않은 규칙이 걸려 있습니다
```

그리고 §4.3 의 `gated-candidate-eligibility`(`may_be_special_summoned` 를
답할 수 없다) 도 그대로 남아 있다.

### 6.3 범위 밖인 것

평가 함수 · 승률 · 상대의 방해 · 전투 · 턴 종료 · 다음 턴. 이번 단계는
**소재 조건 하나를 읽어 소환 절차에 연결한 것**이고, 전개의 좋음을 재는
기준을 더하지 않았다.

---

## 7. 실행한 테스트 명령과 결과

실행한 것만 적는다. 실행하지 않은 검사는 "통과" 라고 적지 않는다.

### 7.1 이번 단계의 새 시험

```
timeout 1200 python3 -m pytest tests/test_longirsu_link_summon.py -q -rf -p no:randomly
→ 26 passed in 7.80s
```

| 절 | 무엇을 재는가 |
|---|---|
| A (15건) | 소재 조건표의 성공·실패 경계 — 장수 최소·최대·부족·초과, 기여 합 미달과 중간값 없음, 소재 각각(통상 몬스터·토큰), 집합 조건(미충족·링크 몬스터가 채움), 중복 개체, 배치 모름, 후보 생성과 판정의 집합 일치, 등록표와 Lua 근거의 대조 |
| B (5건) | 준비한 상태의 실행 — 2장·3장 소환의 모든 존 변화, 소재의 묘지행이 연 유발, 거절의 무변화, 사본/원본 독립 |
| C (2건) | 탐색이 찾고 재조립한 초기 상태에서 재생이 검증, CLI 목표 이름표 |
| D (4건) | 갈라테아·갈라테아i 판정 보존, 범위가 번지지 않음, 미등록 링크 몬스터의 `UNKNOWN` 유지, 등록표 전수 경계 |

### 7.2 이번에 바뀐 공용 판정·실행 절차의 기존 시험

```
timeout 3000 python3 -m pytest \
  tests/test_link_material_count_and_rating.py tests/test_longirsu_link_summon.py \
  tests/test_orcust_girsu_line.py tests/test_girsu_token_line.py \
  tests/test_girsu_token_chain_integration.py \
  tests/test_chain_resolution_link_result_invariant.py \
  tests/test_chain_state_change_between_links.py \
  tests/test_withheld_reason_propagation.py -q -rf -p no:randomly
→ 5 failed, 190 passed in 359.78s      (실패 5건은 모두 §7.4 의 낡은 기대값)
```

낡은 기대값을 고친 뒤:

```
timeout 2400 python3 -m pytest tests/test_orcust_girsu_line.py tests/test_girsu_token_line.py \
  -q -rf -p no:randomly
→ 1 failed, 72 passed in 211.84s       (실패 1건도 §7.4 의 같은 종류)

timeout 1200 python3 -m pytest tests/test_orcust_girsu_line.py -q -rf -p no:randomly
→ 37 passed in 166.34s
```

```
timeout 3000 python3 -m pytest \
  tests/engine/test_action_execution.py tests/engine/test_action_validation.py \
  tests/engine/test_effect_special_summon.py \
  tests/engine/test_legal_action_candidate_consistency.py \
  tests/engine/test_special_summon.py tests/engine/test_two_link_followup_trigger.py \
  tests/engine/test_duelstep_accepted_contract.py -q -rf -p no:randomly
→ 261 passed in 80.24s
```

목표 이름표가 늘어난 자리를 지나는 탐색 · 출력 · 어댑터 계층:

```
timeout 5400 python3 -m pytest \
  tests/test_bounded_search_first_pass.py tests/test_combo_output_consistency.py \
  tests/test_discord_bot.py tests/test_bounded_search_multi_results.py \
  tests/test_post_goal_continuation.py tests/test_result_ranking_v1.py \
  -q -rf -p no:randomly
→ 203 passed in 805.91s (0:13:25)
```

### 7.3 실제 입력 실행 (§5 의 측정)

```
python3 -m app.main combo "69811710,703897,2930675,12989604,93920420" \
  --recipe <검증용 레시피>.ydk --search longirsu
→ 종료 코드 0 · 탐색 미도달 (예산 초과 · 161노드 · 301.38초)

python3 -m app.main combo "…" --recipe <…>.ydk --search galatea --results 3 --followups 2
→ 종료 코드 0 · 검증된 결과 4개 · 후속 링크 소환은 갈라테아i
```

🔴 **실제 Discord 메시지는 보내지 않았다.** 어댑터 쪽은 기존 단위 시험으로만
확인했다.

### 7.4 고친 낡은 기대값 — **왜 이전 기대값이 맞았는가**

여섯 자리가 "롱기르수는 **미등록**이다" 를 고정하고 있었다. 🔴 **그 단언은
그때 사실이었다** — 소재 줄이 `2+` 라서 자료형에 적을 수 없었고(§1.1), 그래서
정말로 등록되지 않았다. 6-AN 이 `count_max` 를 더해 그 모양을 적을 수 있게 되자
사실이 바뀌었다. **조건을 약하게 만들어 통과시킨 것이 하나도 없고**, 재는
사실을 그대로 유지한 채 **예시 카드만** 아직 미등록인 카드로 옮겼다 — 6-AF 가
갈라테아i 를 등록할 때 한 것과 **같은 방식**이다.

| 자리 | 이전 기대 | 바뀐 뒤 |
|---|---|---|
| `test_link_material_count_and_rating::test_b01` | 롱기르수로 "미등록도 소재로는 쓸 수 있다" 를 쟀다 | 같은 사실을 **엔릴기르수**로 잰다 + 롱기르수는 등록되었다 |
| `test_link_material_count_and_rating::test_a07` | `rule.link_rating == rule.count` (관찰로 적힌 것) | 진짜 불변식 `1 ≤ count ≤ max_count ≤ link_rating` + 롱기르수 분기 |
| `test_orcust_girsu_line::UNREAD_LINK` | `76145142` | `74820316` (엔릴기르수) — 이 상수는 등록이 늘 때마다 옮겨 간다 |
| `test_orcust_girsu_line::test_b04` | 갈라테아i 만 "등록됨" 으로 적었다 | 롱기르수도 함께 적는다 |
| `test_orcust_girsu_line::test_b07` | `material_contribution(UNREAD_LINK) == 3` | `… (LONGIRSU) == 3` — **소재로 쓰는 쪽**의 기여는 등록과 무관하므로 카드를 직접 적는다 (상수를 쓰면 수치까지 함께 바뀐다: 실측 4) |
| `test_orcust_girsu_line::test_b10` | 등록표 `[갈라테아, 갈라테아i]` | `[갈라테아, 갈라테아i, 롱기르수]` |
| `test_girsu_token_line::test_d05` | 미등록 예시가 롱기르수 | 엔릴기르수 + 롱기르수는 등록되었다 |

### 7.5 돌리지 않은 것

- **전체 테스트 모음은 이번에 돌리지 않았다.** 바뀐 것은 링크 소재 판정 한
  수 · 후보 생성의 장수 고리 · 목표 이름표 한 줄이므로, 그 세 자리를 지나는
  시험(§7.1 · §7.2) 과 실제 입력 실행(§7.3) 으로 범위를 잡았다. 직전 전체
  실행의 수치는 `docs/orcust-multiple-path-resource-comparison.md` §5.4 에
  있고, **그 수치를 이번 결과로 쓰지 않는다.**
