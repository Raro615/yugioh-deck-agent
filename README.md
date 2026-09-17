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

### 카드명과 게임 용어가 겹칠 때

`마법족의 마을` 은 카드명이지만 `마법` 이 카드 종류로 읽힌다. 질의 전체가
실제 카드명과 일치하면 이름 검색이 이긴다. 용어만으로 온전히 해석되는 질의
(`기계족 빛속성 몬스터`)는 가로채지 않는다.

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
