# yugioh-deck-agent

유희왕 카드 검색 / 덱 분석 에이전트. 한국어 자연어로 질의한다.

```
$ python -m app.main search "4레벨 빛속성 기계족 몬스터 중 특수 소환 효과가 있는 카드"
해석: 기계족, 빛속성, 레벨 4, 몬스터, 효과:SPECIAL_SUMMON
검색 결과: 21장 (상위 5장 표시)
  1. 골드 가제트 · 레벨4 · 빛속성 · 기계족 · 1700/800 · 몬스터/효과  [55010259]
  2. 실버 가제트 · 레벨4 · 빛속성 · 기계족 · 1500/1000 · 몬스터/효과  [29021114]
  ...
```

## 데이터 소스가 둘인 이유

이 저장소에는 EDOPro 카드 스크립트 `c*.lua` 가 12,702개 들어 있다.
**이 스크립트에는 레벨·속성·종족·공격력·카드 텍스트가 들어 있지 않다.**
담겨 있는 것은 카드명 주석과 효과 로직뿐이다.

```lua
--白銀の城の狂時計
--Labrynth Cooclock
local s,id=GetID()
function s.initial_effect(c)
	local e2=Effect.CreateEffect(c)
	e2:SetCategory(CATEGORY_TOHAND+CATEGORY_SPECIAL_SUMMON)
	e2:SetCode(EVENT_TO_GRAVE)
	e2:SetRange(LOCATION_GRAVE)
```

따라서 "4레벨 빛속성 기계족" 같은 수치 필터는 Lua 만으로는 불가능하고,
공식 데이터베이스(`cards.cdb`)가 반드시 필요하다.

반대로 "패에서 특수 소환", "묘지에서 발동" 같은 의미 검색은 Lua 쪽이 정확하다.
효과의 발동 위치와 동작이 상수로 명시되어 있기 때문이다.

| | 공식 DB (`cards.cdb`) | Lua 스크립트 |
|---|---|---|
| 카드명 / 카드 텍스트 | ✅ (한국어 데이터로 덮어씀) | 주석의 일본어·영어명만 |
| 레벨·랭크·링크, 속성, 종족, 공/수 | ✅ | ❌ |
| 카드 종류, 펜듈럼 스케일, 링크 마커 | ✅ | ❌ |
| 효과 발동 위치 (패/묘지/덱/필드) | ❌ | ✅ |
| 효과 동작 분류 (특수소환/서치/파괴…) | 일부 | ✅ |
| 자체 특수 소환 절차 | ❌ | ✅ |
| 지명 카드 / 카드군 참조 | setcode | ✅ |

두 소스는 카드 ID 로 조인한다. 실측 기준 Lua 12,702개 중 **12,696개**가
공식 DB 와 일치하므로 조인 키로 안전하다.

## 설치와 실행

```bash
# 공식 데이터 내려받기 (저장소에 커밋하지 않는다)
python -m scripts.fetch_official_db
# 한국어 데이터는 저장소에 포함되어 있어 따로 받을 필요가 없다

# 검색
python -m app.main search "패에서 특수 소환 가능한 4레벨 몬스터"
python -m app.main search "마법사족에 좋은 드로우 카드" --limit 10
python -m app.main search "묘지에서 효과를 발동하는 카드" --json

# 카드 상세 (ID 또는 이름)
python -m app.main card 2511
python -m app.main card "Dark Magician"

# 관련 카드 / 카드군 / 현황
python -m app.main related 2511
python -m app.main archetype LABRYNTH
python -m app.main stats

# 대화형
python -m app.main repl
```

첫 실행은 Lua 12,702개를 파싱하느라 약 7초가 걸리고, 이후에는
`data/cache/` 캐시 덕분에 약 1초로 줄어든다.

## 구조

```
core/
  constants.py        EDOPro 비트마스크 상수 + 한국어 게임 용어 어휘
  card_model.py       통합 Card 모델, 효과 블록(EffectSpec)
  card_repository.py  두 소스 병합 · 정규화 · 중복 제거 · 인덱싱
  card_search.py      필터 조합 및 실행, 관련도 정렬
  query_parser.py     한국어 자연어 → SearchFilters
sources/
  lua_loader.py       c*.lua 파서 (효과 블록 단위)
  official_db.py      cards.cdb 어댑터
  script_constants.py CARD_* / SET_* 상수 해석
  korean_names.py     한국어 카드명·텍스트 오버레이
app/
  main.py             CLI
scripts/
  fetch_official_db.py  공식 데이터 내려받기
```

### 효과 블록 단위 파싱

파일 전체에서 상수를 모으면 "어떤 효과가 어디서 발동하는지" 알 수 없다.
그래서 `Effect.CreateEffect` 블록 단위로 `SetType`/`SetCode`/`SetRange`/
`SetCategory` 를 묶어서 해석한다. `e4=e3:Clone()` 의 속성 상속도 처리한다.

이 덕분에 "묘지에서 특수 소환하는 효과"와 "묘지에 관한 효과를 가지면서
어딘가에서 특수 소환도 하는 카드"를 구분할 수 있다.

### 검색 조건 결합 규칙

- 같은 항목의 여러 값은 **OR** (종족 [기계, 전사] → 기계족 또는 전사족)
- 다른 항목끼리는 **AND** (종족 + 속성 → 둘 다 만족)

### 해석 결과를 항상 보여준다

질의가 어떻게 해석됐는지 매번 출력하므로, 의도와 다르면 바로 알 수 있다.

```
$ python -m app.main search "마법사족에 좋은 드로우 카드"
해석: 효과:DRAW, 마법사족 서포트
```

`마법사족에 좋은` 은 "그 카드가 마법사족"이 아니라 "마법사족을 지원"으로
해석된다 (해당 종족이거나, 카드 텍스트 원문이 그 종족을 언급).

## 언어 정책

- 코드 식별자 · 함수/클래스명: 영어
- 주석 · 문서: 한국어
- 사용자 출력: 한국어
- **공식 카드명과 카드 텍스트는 번역하지 않는다.** 원문을 그대로 보존한다.

`core/constants.py` 의 한국어 테이블은 카드명이 아니라 *게임 용어*
(기계족, 빛속성, 속공 마법 …)만 담는다. 이것들은 규칙 용어이므로 대응이
일대일이고, 자연어 질의를 수치 필드로 바꾸는 데 쓰인다.

## 한국어 카드 데이터

공식 한국어 카드명과 카드 텍스트가 포함되어 있다 (`data/ko/ko-KR.json`).
출처는 코나미 공식 데이터베이스(Yu-Gi-Oh! Neuron)이며, 번역하지 않고 원문을
그대로 싣는다.

| | 수치 |
|---|---|
| 수집한 한국어 카드 | 13,772장 |
| 패스코드 항목 (일러스트 판본 포함) | 13,899개 |
| 공식 DB 대비 적용률 | 13,728 / 14,127 (97.2%) |

적용되지 않는 약 400장은 한국 미발매 카드다.

원문은 지우지 않는다. 한국어가 적용돼도 `name_en`, `name_ja`, `desc_en` 이
그대로 남아, 세 언어의 카드명과 두 언어의 카드 텍스트를 모두 검색 대상으로 쓴다.

```
$ python -m app.main card 2511
라뷰린스 쿠클락 · 레벨1 · 어둠속성 · 악마족 · 0/0 · 몬스터/효과
  한국어 : 라뷰린스 쿠클락
  공식 DB : Labrynth Cooclock
  일본어  : 白銀の城の狂時計
```

### 다시 수집하려면

```bash
python -m scripts.fetch_korean_db          # 약 5분 (138 페이지, 요청 간격 1초)
python -m scripts.fetch_korean_db --pages 2   # 시험 실행
```

카드마다 상세 페이지를 여는 대신 검색 결과 목록을 훑는다. 목록 한 페이지에
카드 100장의 카드명과 카드 텍스트가 함께 들어 있어, 14,000회가 아니라 138회
요청으로 끝난다. 페이지 단위로 캐시하므로 중간에 끊겨도 이어서 받는다.

코나미 DB 는 자체 `cid` 를, `cards.cdb` 는 패스코드를 쓴다. 둘의 연결은
YGOPRODeck 의 `misc_info.konami_id` 로 얻는다. 하나의 `cid` 에 여러 패스코드가
달릴 수 있어(다른 일러스트) 같은 한국어 표기를 모든 판본에 적용한다.

### 질의 처리 순서와 검색 모드

카드명 안에 게임 용어가 들어 있는 경우가 많아(`마법족의 마을` 의 `마법`),
정확 일치 검사를 가장 먼저 한다.

```
입력
 ├─ 1. 전체 입력이 실제 카드명과 정확히 일치?   → exact_name
 ├─ 2. 관련 카드 / 카드군 요청?                → related / archetype
 │      (그 말이 실제 카드군인지 카드 데이터로 확인, 아니면 다음 단계로)
 ├─ 3. 게임 용어 / 조건 파싱                   → condition
 └─ 4. 해석 못 한 조각이 남고 이름 일부와 맞으면 → partial_name
```

검색 결과에는 항상 어느 모드였는지 표시된다.

| 입력 | 모드 | 결과 |
|---|---|---|
| `마법족의 마을` | `exact_name` | 68462976 1장 |
| `마법사족의 마을` | `condition` | 마법사족 794장, `마을` 은 미인식으로 보고 |
| `오르페골` | `partial_name` | 이름에 포함 18장 |
| `오르페골 카드` | `archetype` | ORCUST 소속 18장 |
| `오르페골과 관련된 카드` | `related` | 19장, 관계 종류 표시 |
| `레벨 5 기계족` | `condition` | 97장 |
| `마법 카드` | `condition` | 카드군이 아니므로 마법 카드 2,838장 |

### 레벨 · 랭크 · 링크는 다른 값이다

`cards.cdb` 는 셋을 `level` 컬럼 하나에 담지만 의미가 다르다.
엑시즈에는 레벨이 없고(랭크), 링크에도 레벨이 없다(링크 수).
검색은 원시값이 아니라 `monster_level` / `rank` / `link_rating` 으로 비교한다.

```
레벨 5 기계족  →  97장  (랭크5 엑시즈·링크5 제외)
랭크 5 기계족  →  10장
링크 3 기계족  →  12장
```

### 관련 카드는 근거를 함께 알려준다

| 관계 | 뜻 |
|---|---|
| `archetype` | 공식 `setcode` 로 같은 카드군에 속함 |
| `listed_name` | 기준 카드의 텍스트가 이 카드를 지명 |
| `referenced_by` | 이 카드의 텍스트가 기준 카드를 지명 |
| `series` | 이 카드의 스크립트가 그 카드군을 지명 (카드군 서포트) |

```
$ python -m app.main search "오르페골과 관련된 카드"
검색 모드: related (관련 카드 검색)
해석: 관련 카드 검색 '오르페골' (archetype 18, referenced_by 2, series 14, listed_name 1)
  1. 시오르페골 딩기르수 · 랭크8 · 어둠속성 · 기계족 · 2600/2100  [93854893]
       관계: archetype, referenced_by, series
```

카드군 판정은 이름이 맞는 카드들이 **다수 공유하는** `setcode` 만 인정한다.
오르페골 카드 18장 중 2장은 기교(MEKK_KNIGHT)도 겸하는데, 교차 소속까지
카드군으로 보면 관련 없는 카드군 전체가 딸려 들어오기 때문이다.
같은 이유로 게임 용어(`마법`, `카운터 함정`)는 공통 `setcode` 가 없어
카드군으로 해석되지 않는다.

### 종과 판본을 구분한다

같은 카드의 다른 일러스트/에라타는 패스코드가 각각 있지만 카드로는 1종이다.
정확 일치 결과는 두 값을 나눠서 보고하고, 이름에 그 말이 들어가는 다른 카드는
섞지 않고 따로 보여준다.

```
$ python -m app.main search "푸른 눈의 백룡"
해석: 카드명 정확 일치 '푸른 눈의 백룡' — 1종 (판본 8개)
검색 결과: 1종
  1. 푸른 눈의 백룡 · 레벨8 · 빛속성 · 드래곤족 · 3000/2500 · 몬스터/일반  [89631139]
       판본 8개: 89631139, 89631140, ...

이름에 '푸른 눈의 백룡' 을(를) 포함하는 다른 카드: 4장
     Sin 푸른 눈의 백룡 · 레벨8 · 어둠속성 · 드래곤족 · 3000/2500 · 몬스터/효과/특수소환  [9433350]
     궁극의 푸른 눈의 백룡 · 레벨12 · 빛속성 · 드래곤족 · 4500/3800 · 몬스터/융합  [23995346]
```

### 영어 용어도 받는다

`Spellcaster`, `Winged Beast`, `Machine Type`, `LIGHT` 는 종족/속성 필터가 된다.
단 **질의 전체가 그 용어일 때만** 적용한다. 카드명에는 `Dragon`, `Warrior` 같은
낱말이 흔해서, 부분 일치를 허용하면 `Blue-Eyes White Dragon` 이 드래곤족 전체
검색이 되어버린다.

## 클라우드 세션 설정 (Claude Code on the web)

`.claude/hooks/session-start.sh` 가 세션 시작 시 자동으로 실행된다.
개발 의존성 설치, 공식 카드 데이터 내려받기, Lua 파싱 캐시 예열,
한국어 데이터 소스 도달 가능 여부 점검을 한 번에 처리한다.
로컬 세션에서는 `CLAUDE_CODE_REMOTE` 검사로 즉시 종료하므로 아무 영향이 없다.

측정값: 데이터가 없는 첫 세션 약 11초, 이후 세션 약 1.6초.

환경 대화상자(claude.ai/code 의 환경 선택기)에는 다음을 넣는다.

**Network access**: `Custom`, 허용 도메인에 `*.yugioh-card.com`,
그리고 **"Also include default list of common package managers" 체크**
(체크하지 않으면 `raw.githubusercontent.com` 과 PyPI 까지 차단된다).

**Environment variables**:

```
PYTHONUNBUFFERED=1
PYTHONDONTWRITEBYTECODE=1
PIP_DISABLE_PIP_VERSION_CHECK=1
PIP_ROOT_USER_ACTION=ignore
```

`YGO_CARDS_CDB` 는 훅이 실제 경로로 직접 써 넣으므로 여기 적을 필요가 없다.
한국어 데이터를 다른 위치에 두려면 `YGO_KO_DIR` 로 지정한다.


## 효과 분석 계층 (analysis/)

검색 계층은 "이 카드가 조건에 맞는가"를 판단한다. 분석 계층은 한 단계 더 들어가
**"이 효과가 무엇을, 어디에서, 어디로, 어떤 비용으로 옮기는가"** 를 구조화한다.
검색 계층과 독립적이며 카드를 읽기만 한다.

```
$ python -m app.main analyze 21441617
오르페골 스켈레촌 · 레벨3 · 어둠속성 · 기계족 · 1200/1500 · 몬스터/효과
  소속 카드군 : ORCUST
  [e1] GRAVE에서 · 비용 self_banish · GRAVE의 ORCUST 카드군 선택 · special_summon→MZONE · 턴 1회
      비용      : self_banish (Cost.SelfBanish)
      대상 지정 : 예
      선택      : GRAVE 의 ORCUST 카드군
      처리      : special_summon  GRAVE → MZONE
```

Lua 핸들러를 따라 들어가 읽는다.

```lua
e1:SetCost(Cost.SelfBanish)   -- 비용: 자신을 제외
e1:SetTarget(s.sptg)          -- s.sptg 의 Duel.SelectTarget(..., LOCATION_GRAVE, ...)
                              --   -> s.spfilter 의 IsSetCard(SET_ORCUST)
e1:SetOperation(s.spop)       -- s.spop 의 Duel.SpecialSummon(...)
```

### 소속과 상호작용을 구분한다

`archetype` 만 소속이고 나머지는 전부 상호작용이다. 소속의 근거는 공식
`setcode` 뿐이며, 카드 텍스트에 이름이 등장한다는 이유로 소속을 판정하지 않는다.

```
$ python -m app.main relations 93920420
성유물－『성장』
소속 (같은 카드군): 1건
  · WORLD_LEGACY   근거=setcode:WORLD_LEGACY
상호작용: 5건
  · series    ORCUST                      ← 지명할 뿐, 오르페골 카드가 아니다
  · summons   ORCUST (REMOVED→MZONE)      ← 실제로 다루기는 한다
```

| 관계 | 근거 | 소속 |
|---|---|---|
| `archetype` | 공식 `setcode` | ✅ |
| `series` | 스크립트의 `listed_series` | ❌ |
| `listed_name` | 스크립트의 `listed_names` | ❌ |
| `searches` / `summons` / `destroys` / `banishes` / `sends_to_grave` / `bounces` / `targets` | 효과 분석 | ❌ |

### 콤보 탐색을 위한 구조

이동을 일으키는 관계는 `from_location` → `to_location` 과 대상 조건을 가진다.
이것이 상태 전이가 되어 역방향 질의가 가능하다.

```python
builder.find_sources(
    kind=RelationshipKind.SUMMONS,
    archetype="ORCUST",
    from_location="GRAVE",
)
# -> 오르페골 몬스터를 묘지에서 특수 소환할 수 있는 카드들
```

### 처리 순서: 조건 → 비용 → 선택 → 처리

효과는 네 단계로 펼쳐진다. 콤보 탐색이 묻게 될 순서 그대로다 —
"쓸 수 있는가 → 무엇을 내야 하는가 → 무엇을 고르는가 → 무엇이 일어나는가".

```
$ python -m app.main analyze 21441617
  [e1] IGNITION
      ① 발동 조건 : GRAVE에서 · 아니어야 함: player_affected · 이 카드명 1턴 1회
      ② 비용 : self_banish
      ③ 선택 : GRAVE 의 ORCUST 카드군
      ④ 처리 : special_summon→MZONE
```

### 발동 조건

`SetCondition` 함수를 따라 들어가 상태 요구를 읽는다.

```lua
Duel.IsExistingMatchingCard(
    aux.FaceupFilter(Card.IsSetCard,SET_PERFORMAPAL), tp, LOCATION_MZONE, 0, 1, ...)
→ 필요: 자신 MZONE에 앞면 PERFORMAPAL 카드군 1장
```

읽는 조건 종류: `requires_card`(1,762) · `turn_player`(979) · `battle`(780) ·
`phase`(768) · `chain`(683) · `card_count`(585) · `zone_available`(540) ·
`life_points`(96) · `player_affected`(74)

**부정을 놓치지 않는다.** `not Duel.IsPlayerAffectedByEffect(...)` 는
`negated=True` 로 기록된다. 놓치면 의미가 정반대가 된다.

### 조건의 논리 구조

조건은 평면 목록이 아니라 트리로 보존한다. OR 를 AND 로 평탄화하면
"둘 중 하나면 된다"가 "둘 다 필요하다"로 바뀌어, 성립하지 않는 경로를
성립한다고 판단하게 된다.

```
$ python -m app.main analyze 2511
  [e2] FIELD/TRIGGER_O
      ① 발동 조건 : GRAVE에서 · EVENT_TO_GRAVE · 이 효과 1턴 1회
          논리: (?(rp==tp) 그리고 … 그리고 ((?(re:IsTrapEffect()) 그리고 ?(re:IsHasType(…)))
                또는 (?(rc:IsSetCard(SET_LABRYNTH)) 그리고 아님(?(rc:IsCode(id))))))
```

다루는 Lua 형태:

| Lua | 트리 |
|---|---|
| `A and B` | `AND(A, B)` |
| `A or B` | `OR(A, B)` |
| `not A` | `NOT(A)` |
| `(A or B) and C` | `AND(OR(A,B), C)` — 괄호 우선순위 보존 |
| `A and (B or C)` | `AND(A, OR(B,C))` |
| `if X then return false end` | `X` 를 AND 가지로 (가드) |
| `if X then return true end` | `X` 를 OR 가지로 (충분조건) |
| `if X then return A else return B end` | `OR(AND(X,A), AND(NOT X,B))` |

Lua 우선순위 `not` > `and` > `or` 를 그대로 따르며, 여러 줄에 걸친 조건식과
줄 머리에 오는 `and` / `or` 도 이어 붙인다.

분류하지 못한 항목은 `?(원문)` 으로 남는다. **논리 구조는 살리되 의미는
지어내지 않는다.** 평면 목록(`requirements`)은 트리 leaf 에서 유도되므로
둘이 어긋나지 않으며, `NOT` 아래의 leaf 는 평면 목록에서도 `negated` 로 표시된다.

### 발동 제한은 범위가 다르다

"1턴에 1번"이 무엇을 기준으로 하는지에 따라 실제 제약이 완전히 달라진다.

| Lua | 범위 | 개수 |
|---|---|---|
| `SetCountLimit(1)` | 이 카드 1장 | 2,566 |
| `SetCountLimit(1,id)` | 이 카드명 전체 | 5,399 |
| `SetCountLimit(1,{id,n})` | 그 카드명의 특정 효과 | 2,478 |
| 없음 | 제한 없음 | 15,763 |

### 구조화 범위와 한계

억지로 추론하지 않는다. 읽어내지 못한 것은 `unparsed` 에 원문으로 남고,
원본 효과 블록은 `raw` 로 항상 보존된다.

전체 코퍼스(12,687장, 등록 효과 26,352블록) 기준. **비율의 분모는 '그 요소를
가진 효과'다** — 비용이 없는 효과까지 분모에 넣으면 실제보다 낮게 보인다.

| 요소 | 해당 효과 | 구조화 |
|---|---|---|
| 발동 조건 | 11,625 | 트리 **82.8%** / 요구 추출 **44.1%** (흔적 보존 100%) |
| 비용 | 4,982 | **95.1%** |
| 선택 조건 | 11,990 | **56.8%** |
| 처리(액션) | 26,352 전체 | 55.0% |

조건은 44.5%만 의미까지 읽지만, **조건이 있는데 흔적 없이 사라지는 경우는 0건**이다.
구조화하지 못하면 호출 이름이 `unparsed` 에 남아 "조건 없음"과 구분된다.

아직 읽지 못하는 것:

- 조건 leaf 의 66% 는 분류하지 못한다 (`re:IsTrapEffect()` 같은 객체 술어).
  **논리 구조는 보존되지만 leaf 의 의미는 원문으로만 남는다**
- 지역 변수 재대입·값 교환이 섞인 조건 (`a,b=b,a`), 중첩 `if`
- 체인·타이밍의 세부 (`GetChainInfo` 의 인자, `SetHintTiming`)
- 지속 효과의 수치 계산 (`SetValue` 의 계산식)
- 액션이 없는 45% 중 실제 미구조화는 15.1% (나머지는 처리 함수가 없는 지속 효과)
- 남은 UNKNOWN 비용 246건 (전체 비용의 4.9%)

## 테스트

```bash
pip install pytest
python -m pytest tests/ -q
```

`cards.cdb` 가 없으면 통합 테스트는 자동으로 건너뛴다.

## 데이터 출처

- [Project Ignis BabelCDB](https://github.com/ProjectIgnis/BabelCDB) — `cards.cdb`
- [Project Ignis CardScripts](https://github.com/ProjectIgnis/CardScripts) — `CARD_*` / `SET_*` 상수
- [코나미 공식 카드 데이터베이스](https://www.db.yugioh-card.com/yugiohdb/) — 한국어 카드명 / 카드 텍스트
- [YGOPRODeck](https://db.ygoprodeck.com/api-guide/) — 코나미 `cid` ↔ 패스코드 매핑
- 저장소에 포함된 `c*.lua` — 카드 스크립트 (원본 데이터, 수정하지 않는다)
