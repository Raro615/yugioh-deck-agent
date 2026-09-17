# Rules Knowledge Layer

공식 룰북에서 온 **게임 자체의 규칙**. 카드 데이터와 분리된 세 번째 지식 원천이다.

| 계층 | 무엇을 말해 주는가 | 어디에 있는가 |
|---|---|---|
| Card Data | 카드가 무엇인가 (이름 · 수치 · 텍스트) | `core/`, `sources/` |
| Card Analysis | 그 카드의 효과가 어떻게 생겼는가 (Lua) | `analysis/` |
| **Rules Knowledge** | **게임이 어떻게 굴러가는가** | `rules/` ← 이 문서 |

Rules Knowledge 는 카드의 효과를 **대체하지 않는다.** 룰북은 "체인이 어떻게
쌓이고 어떤 순서로 해결되는가"를 말해 주지만, "이 카드가 무엇을 하는가"는
언제나 Lua 와 공식 카드 텍스트가 정한다.

## 권위 순서

```
게임 규칙          Official Rulebook          <- rules/
카드의 실제 처리    Lua (authoritative)        <- analysis/, sources/lua_loader.py
카드 공식 문구      Official card text         <- sources/official_db.py
한국어 표시         Korean DB                  <- sources/korean_names.py
보조 정보           Supplementary sources      <- sources/supplementary.py
```

`rules.rule_model.RULE_AUTHORITY` 가 이 순서를 코드로 들고 있다. **어떤 보조
출처도 공식 룰을 덮어쓰지 못한다.**

## 의존 방향

```
Card Data -> Card Analysis ---+
                              |--> Duel Engine -> GameState -> Legal Actions / Resolution
Rules Knowledge --------------+
```

- `rules/` 는 `engine/` 을 import 하지 않는다. 엔진 어휘와의 연결은 이름
  문자열(`engine_zone`, `engine_phase`, `engine_summon_type`)로만 적어두고,
  실제 연결은 `rules/concept_map.py` 가 표로 관리한다.
- `rules/` 는 `core/` 나 `analysis/` 도 import 하지 않는다. 규칙은 카드를
  포함하지 않고, 카드는 규칙을 포함하지 않는다.

## 파일

```
rules/
  rule_model.py        RuleDocument · RuleSection · RuleRef · RuleProvenance
  rule_repository.py   적재 · Rule ID 조회 · 무결성 검사
  rule_search.py       rule_id / title / keyword / category / section / text 검색
  structured.py        TurnStructure · ZoneRule · ChainRule · SummonRule …
  concept_map.py       룰 개념 <-> 엔진 개념 <-> 조건 술어

data/rules/
  sources/             원본 PDF (저작물이라 커밋하지 않음, .gitignore)
  documents/           추출한 **원문** — 요약 없음
  structured/          구조화 데이터 — 모든 항목이 rule_id 로 원문을 가리킴
  index/rule_ids.json  Rule ID 고정 등록부

scripts/extract_rulebook.py   PDF -> documents/*.json
```

**원본과 가공물을 파일 단위로 분리한다.** `documents/` 는 룰북에 인쇄된 문장
그대로이고, `structured/` 는 그것을 해석한 것이다. 엔진 구현이 막혔을 때
되돌아가 읽을 원문이 있어야 하기 때문이다.

## Rule ID

```
RULE-<분류>-<번호>        예: RULE-CHAIN-001, RULE-TURN-004, RULE-TERM-023
```

13개 분류: `GAME` `DECK` `ZONE` `CARD` `MONSTER` `EFFECT` `SUMMON` `SPELLTRAP`
`TURN` `BATTLE` `CHAIN` `MISC` `TERM`

번호는 문서 순서대로 붙이되, **한 번 붙인 번호는 `data/rules/index/rule_ids.json`
에 분류 + 제목 슬러그로 적어두고 다음 판본에서도 재사용한다.** 룰북이 개정되어
앞쪽에 규칙이 끼어들어도 `RuleRef("RULE-CHAIN-001")` 이 딴 규칙을 가리키지
않는다. 새 항목만 그 분류의 다음 번호를 받는다.

```python
from rules import RuleRepository, RuleRef

repository = RuleRepository.load()
section = repository[RuleRef("RULE-CHAIN-007")]
print(section.title)                       # How a Chain Works
print(section.source_reference.describe())  # sd-rulebook-en-v10 p.46
print(section.text)                         # 원문 그대로
```

## 검색

```python
from rules import RuleRepository, RuleSearch

search = RuleSearch(RuleRepository.load())

search.search("체인이 어떻게 처리되는가?")        # 한국어 질의도 가능
search.search("damage step", category="BATTLE")
search.search("spell speed", within="RULE-CHAIN-002")
search.by_text("resolved starting with the most recent card")
search.by_rule_id("RULE-TURN-004")
```

한국어 질의는 `rule_search.KO_QUERY_TERMS` 를 거쳐 룰북 어휘로 바뀐다.
**룰북을 번역한 것이 아니다** — `core/constants.py` 의 `KO_RACE_ALIASES` 와
같은 질의어 별칭표이고, 표에 없는 한국어는 그냥 걸리지 않는다.

검색 결과는 언제나 원문 절이다. 요약을 만들어 돌려주지 않는다.

## 구조화 데이터

```python
from rules import load_structured_rules

rules = load_structured_rules()[0]
rules.turn_order()
# ['Draw Phase', 'Standby Phase', 'Main Phase 1', 'Battle Phase', 'Main Phase 2', 'End Phase']

rules.zone("Graveyard").ordering          # 'fixed'
rules.zone("Graveyard").capacity          # None  <- 룰북이 말하지 않는다
rules.zone("Graveyard").not_stated        # ('capacity',)
rules.summon("Tribute Summon").procedure
rules.chain.spell_speeds[2].can_respond_to  # (1, 2, 3)
```

세 가지 규칙을 지킨다.

1. **모든 항목이 `rules` 로 자기 근거를 가리킨다.** 근거 없는 항목은 만들지 않는다.
2. **룰북이 말하지 않은 값은 `None` 이고 `not_stated` 에 이름이 들어간다.**
   빈칸을 그럴듯한 값으로 메우지 않는다.
3. 구조화 값은 원문을 대체하지 않는다. 애매하면 `rules` 가 가리키는 원문으로 돌아간다.

## Duel Engine 과의 연결

엔진이 조건을 판정할 때 "이 판정의 근거가 룰북 어디인가"를 찾는 표가
`rules/concept_map.py` 다.

```python
from rules.concept_map import rules_for, ungrounded_predicates

rules_for("chain_state")        # (RuleRef('RULE-CHAIN-001'), RuleRef('RULE-CHAIN-007'))
rules_for("previous_location")  # ()  <- 이 룰북에 근거가 없다
ungrounded_predicates()
# ['previous_location', 'previous_position', 'previous_controller',
#  'card_status', 'flag_effect', 'unknown']
```

`analysis.predicate_model.PredicateKind` 26종 전부에 대해 연결이 있고,
그중 **6종은 이 룰북에 근거가 없다.** 비슷해 보이는 절에 억지로 붙이지
않았다 — 붙여두면 나중에 그 절을 근거로 잘못된 판정을 구현하게 된다.
그 6종의 판정 근거는 Lua 나 상급 룰 문서에서 따로 구해야 한다.

## 룰북 다시 추출하기

```bash
pip install pymupdf
python -m scripts.extract_rulebook path/to/SD_RuleBook_EN_10.pdf
```

추출기는 룰북에 **인쇄된 제목을 앵커로** 삼아 본문을 자른다. 앵커가 그 쪽에서
정확히 한 번 나오지 않으면 조용히 넘어가지 않고 실패한다. 판본이 바뀌면 여기가
먼저 깨지므로 변경을 놓치지 않는다.

`pymupdf` 는 추출기 전용 의존성이다. `rules/` 를 읽기만 할 때는 필요 없다.

### PDF 추출에서 실제로 겪은 문제

- **올드스타일 숫자.** 본문 글꼴이 text figure 를 쓴다. pypdf 로 뽑으면 숫자
  `2` 가 `•` 로 바뀌어 `Spell Speed •`, `Chain Link •`, `require • Tributes`
  처럼 **규칙의 숫자가 통째로 사라진다.** PyMuPDF 는 올바르게 읽는다.
  `REQUIRED_PHRASES` 와 `tests/rules/test_rule_document.py` 가 이 자리를
  직접 검사한다.
- **펼침면.** PDF 한 장이 인쇄본 두 쪽이다. 인쇄 쪽번호는
  `2 * pdf_page - 6 + half`.
- **가운데 정렬 제목 띠.** 제목이 본문보다 오른쪽에서 시작해서, 단순한
  x 기준 단 나누기로는 제목이 자기 본문보다 뒤로 밀린다. 그래서 단 후보
  사이의 틈을 가로지르는 줄이 거의 없을 때만 진짜 단 경계로 본다.
- **그림자 제목.** 제목이 살짝 어긋난 위치에 두 번 찍힌다. 같은 줄 안에서
  겹친 것과 줄이 아예 나뉜 것을 각각 처리한다.

### 남은 한계

- 용어집 항목 `RULE-TERM-022` 의 제목이 `Shuff le` 다. PDF 제목 글꼴이 `ffl`
  자리를 끊어 찍은 결과이고, **원문을 고치지 않는 원칙에 따라 그대로 둔다.**
  본문에는 `shufﬂe` 로 정상 표기되어 있고, `normalized_text` 가 합자를 펴므로
  `shuffle` 로 검색된다.
- 삽화·다이어그램의 글자(전투 결과표의 `WIN/TIE/LOSE`, 체인 예시 도식 등)는
  본문 줄로 같이 들어온다. 그림 없이 읽으면 문맥이 끊긴다.
- 룰북 원문은 **영어뿐이다.** 한국어 번역본을 만들지 않았다 — 공식 번역이
  아닌 번역을 authoritative rule 로 저장할 수 없기 때문이다.
- 이 룰북은 스타터 덱 동봉본(Version 10, 2017)이라 **완전한 상급 규칙서가
  아니다.** missing timing, "if" 와 "when" 의 타이밍 차이, 치환 효과
  (replacement effect), 강제/임의 효과의 상세 규칙은 여기 없다.
  `Rules vs. Card Effects`(RULE-MISC-004) 가 "규칙과 카드 효과가 어긋나면 카드
  효과가 우선한다"는 원칙만 준다.

## 테스트

```bash
python -m pytest tests/rules -q
```

- 룰북이 정상적으로 적재되는가
- Rule ID 가 중복되지 않는가 · 형식이 맞는가 · 분류마다 빈 번호가 없는가
- 모든 섹션이 ID 로 접근 가능한가 · 부모-자식이 일관적인가
- 검색이 되는가 (6개 축 + 요구된 질문들)
- **원문이 손상되지 않았는가** (숫자 보존, 첫 줄이 인쇄된 제목인가, 구절 대조)
- 구조화 항목이 전부 실재하는 원문을 가리키는가 · `not_stated` 가 실제로 비었는가
- 같은 PDF 를 다시 처리하면 같은 결과가 나오는가 (원본 PDF 가 있을 때만)

원본 PDF 가 필요한 결정론 테스트는 `YGO_RULEBOOK_PDF` 환경변수나
`data/rules/sources/` 에 PDF 를 두면 실행된다. 없으면 건너뛴다.
