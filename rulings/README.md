# Card Ruling Layer

공식 코나미 OCG 카드 데이터베이스에서 온 **카드별 재정**. 네 계층 중 세 번째다.

| 계층 | 무엇을 말해 주는가 | 권위 있는 출처 | 어디에 |
|---|---|---|---|
| General Rules | 게임이 어떻게 굴러가는가 | 공식 룰북 | `rules/` |
| Card Data | 카드가 무엇인가 | 공식 카드 텍스트 | `core/`, `sources/` |
| **Card Rulings** | **이 카드에서는 어떻게 되는가** | **공식 카드별 Q&A** | `rulings/` ← 이 문서 |
| Card Implementation | 효과가 실제로 어떻게 처리되는가 | Lua | `analysis/` |

계층을 섞지 않는다. 룰북은 "체인이 어떻게 쌓이는가"를, 재정은 "이 카드의 ①효과가
데미지 스텝에 발동되는가"를 말한다. 하나의 레코드에 합치면 어느 쪽 권위로
판단해야 하는지 알 수 없게 된다.

## 세 가지 원칙

**1. 공식 출처만.** `RulingSource` 에는 값이 하나뿐이다 — `konami_ocg_database`.
비공식 위키 · 커뮤니티 재정 · 모델의 기존 지식은 타입 수준에서 들어올 자리가 없다.

**2. 원문이 권위를 갖는다.** 일본어 원문만 authoritative 하다. 번역은
`RulingTranslation` 으로 붙고, `TranslationSource` 는 `RulingSource` 와 값이
하나도 겹치지 않아 원문 자리에 들어갈 수 없다.

```
Official Japanese Ruling  ->  authoritative     (question_original / answer_original)
Korean Translation        ->  non-authoritative (translations["ko"])
```

**3. "재정 없음"과 "확인 실패"는 다르다.**

| 상태 | 뜻 |
|---|---|
| `ruling_exists` | 공식 사이트에서 재정을 실제로 확인했다 |
| `ruling_not_found` | 정상 조회했고, 이 카드에는 재정이 없다 |
| `source_unavailable` | 접근·파싱 실패. **아무것도 결론 내리지 않는다** |

수집한 적 없는 카드를 물으면 `source_unavailable` 이 나온다. "재정이 없다"가
아니다.

## OCG / TCG

이 계층은 **OCG 전용**이다. 한국어 카드 데이터가 OCG 기준이므로 재정도 OCG 로
맞춘다. `RulingGame` 에 `TCG` 값은 있지만 이번 구현에서 수집하지 않으며,
하나의 레코드에 섞지 않는다.

## 식별자 — 이름으로 잇지 않는다

```
한국어 이름  ->  card_id (passcode)  ->  공식 cid  ->  일본어 Q&A
```

한국어와 일본어 카드명은 문자열이 전혀 다르다.

| passcode | 한국어 | 일본어 |
|---|---|---|
| 2511 | 라뷰린스 쿠클락 | 白銀の城の狂時計 |
| 24224830 | 무덤의 지명자 | 墓穴の指名者 |

앞의 예는 **공통 글자가 하나도 없다.** 어떤 문자열 유사도로도 이어지지 않으므로
숫자 식별자로만 잇는다 (`core/card_identity.py`, `data/identity/cid_map.json`).

```python
from core.card_identity import CardIdentityMapping

identity = CardIdentityMapping.load()
identity.cid_for(2511)          # 17366
identity.card_ids_for(17366)    # [2511]
identity.primary_card_id(17366) # 2511  (일러스트 판본이 여럿일 때 대표 하나)
```

`cid` 값 자체는 공식 사이트에서 왔지만 **`cid` 와 패스코드를 잇는 링크는 보조
출처(YGOPRODeck `misc_info.konami_id`)에서 온 추론**이다. 데이터가 그 사실을
숨기지 않고 `link_source` 로 들고 있다.

추론을 그대로 믿지 않기 위해 **독립된 두 출처의 일본어 카드명을 완전 일치**
대조한다.

- 패스코드 → 일본어 이름 : Lua 스크립트 주석 (`LuaScriptInfo.name_ja`, 12,968장)
- `cid` → 일본어 이름 : 코나미 공식 페이지

일치하면 `verified`, 다르면 `conflict` 이고 **`conflict` 인 링크는 조회에서
아예 빠진다.** 대조하지 않은 것은 `unverified` 이며, 틀렸다는 뜻이 아니라
확인하지 않았다는 뜻이다.

```bash
python -m scripts.build_card_identity --verify 300   # 300장 교차 검증
```

## 데이터 모델

```
CardRulingSet                 카드 한 장에 대해 확인한 결과 전부
 ├ official_cid / card_id
 ├ availability               ruling_exists | ruling_not_found | source_unavailable
 ├ name_ja / card_text_ja     공식 페이지가 보여준 일본어
 ├ reported_total             공식이 밝힌 "全N件" (받은 개수와 대조)
 ├ rulings[]      -> CardRuling
 └ supplement     -> CardRulingSupplement | None

CardRuling                    Q&A 하나        (ruling_id = OCG-QA-<fid>)
 ├ question_original          일본어 원문
 ├ answer_original            일본어 원문
 ├ ruling_category            공식 태그 (モンスター / 魔法 / 罠 …)
 ├ published_or_updated_at    공식 更新日
 ├ related_card_cids / _ids   공식이 본문에 **직접 건 링크**만
 ├ provenance                 source · language · authority · game · url · retrieved_at
 ├ content_hash               변경 감지의 유일한 근거
 └ translations{}             non-authoritative

CardRulingSupplement          補足情報        (ruling_id = OCG-SUP-<cid>)
 ├ text_original              질문이 없다
 └ published_or_updated_at    Q&A 와 **다른** 갱신일
```

`CardRuling` 과 `CardRulingSupplement` 는 **다른 타입이다.** 補足情報 는 질문이
없고, 카드당 하나이며, 자기 갱신 날짜를 따로 갖는다. 하나의 텍스트 필드로 합치면
"질문에 대한 답"인지 "카드에 대한 보충"인지 구분할 수 없게 된다.

## 검색

```python
from rulings import RulingRepository, RulingSearch

search = RulingSearch(RulingRepository.load())

search.by_card_id(89631139)          # 이 카드의 재정 전부
search.by_cid(4007)
search.by_ruling_id("OCG-QA-24359")
search.by_card_name("青眼の白龍")     # 일본어 이름은 그대로
search.by_category("魔法")
search.updated_between(since="2025-01-01")
search.related_to(2511)              # 이 카드를 언급한 다른 카드의 재정
search.availability(46986414)        # 확인 안 함 / 없음 / 있음

search.search("ダメージステップ", field="question")
search.search("対象", card_id=89631139)
```

한국어 이름으로 찾으려면 카드 계층의 해석기를 주입한다 — 재정 계층이 카드명을
혼자 넘겨짚지 않는다.

```python
from core.card_repository import CardRepository

repository = CardRepository.build()
search = RulingSearch(
    RulingRepository.load(),
    card_name_resolver=lambda name: [c.id for c in repository.find_by_exact_name(name)],
)
search.by_card_name("푸른 눈의 백룡")
```

### 일본어 검색은 부분 문자열이다

일본어에는 띄어쓰기가 없다. 형태소 분석기를 넣으면 사전 없이는 신뢰할 수 없고,
사전이 틀리면 **검색 결과가 조용히 비어버린다.** 그래서 부분 문자열 일치만 쓴다.
느리지만 틀리지 않고, 왜 걸렸는지 설명할 수 있다.

비교할 때만 NFKC 정규화를 한다 — 공식 재정은 「１ターンに１度」처럼 전각 숫자를
쓰므로, 정규화하지 않으면 `1ターンに1度` 로는 영영 걸리지 않는다. **원문은
바꾸지 않는다.**

## 공식 사이트 구조

HTML 구조를 아는 파일은 `sources/ocg_ruling_adapter.py` **하나뿐이다.**
`core/` · `analysis/` · `rules/` · `rulings/` 는 어느 태그에 무엇이 있는지 모른다.
사이트 개편이 오면 고칠 곳이 한 군데다.

| 용도 | URL |
|---|---|
| 카드별 Q&A 목록 | `faq_search.action?ope=4&cid=<cid>&request_locale=ja&page=<n>&rp=<n>` |
| Q&A 상세 | `faq_search.action?ope=5&fid=<fid>&request_locale=ja` |
| 카드 상세 | `card_search.action?ope=2&cid=<cid>&request_locale=ja` |

목록 페이지에서 읽는 것:

| 선택자 | 내용 |
|---|---|
| `meta[name=keywords]` 첫 항목 | 일본어 카드명 |
| `#card_text` | 일본어 카드 텍스트 |
| `全N件中 a～b件` | 전체 Q&A 수 |
| `div.t_row` | Q&A 한 건 |
| ↳ `span.name` / `div.tag_name span` / `div.date` | 질문 제목 / 공식 태그 / 更新日 |
| ↳ `input.link_value` | `ope=5&fid=<fid>` |
| `div.supplement` | **補足情報 (있는 카드만)** |
| ↳ `span.update` / `#supplement` | 補足 갱신일 / 본문 |

상세 페이지: `#question_text`, `#answer_text`, `#tag_update .btn`(태그),
`#tag_update .date`(更新日), 본문 안의 `a[href*="ope=4&cid="]`(관련 카드).

`rp=100` 이 받아들여지므로 316건짜리 카드도 목록 요청 4번이면 된다.

## 수집

**전체 수집은 기본값이 아니다.** 샘플로 파싱을 검증한 뒤에만 전체를 돌린다.

```bash
# 1) 식별자 매핑 (한 번만)
python -m scripts.build_card_identity

# 2) 검증용 표본 8장
python -m scripts.fetch_ocg_rulings --sample

# 3) 특정 카드만
python -m scripts.fetch_ocg_rulings --card-id 14558127 --card-id 2511

# 4) 이어받기 — 이미 받은 카드는 건너뛴다
python -m scripts.fetch_ocg_rulings --all --skip-collected --limit 0

# 4') 갱신 — 전부 다시 확인하고 content_hash 로 new/changed/removed 를 가린다
python -m scripts.fetch_ocg_rulings --all --limit 0 --refresh

# 5) 전체 수집 — 카드 14,362장, 매우 오래 걸린다
python -m scripts.fetch_ocg_rulings --all --limit 0 --delay 1.5
```

수집 정책: 요청 사이 기본 1.2초 대기, 받은 HTML 은 `data/rulings/.cache/` 에
두고 재파싱 시 다시 받지 않는다 (캐시는 커밋하지 않는다).

## 증분 갱신

카드 데이터 쪽 `sources/source_manager.py` 와 같은 철학이되 **비교 단위가
재정 하나**다. 카드 하나 안에서 Q&A 가 따로 생기고 따로 사라지기 때문이다.

```
new        이번에 처음 본 재정
changed    content_hash 가 달라진 재정
removed    정상 조회했는데 사라진 재정
unchanged  그대로
unavailable 확인하지 못한 카드   <- 위 넷과 절대 섞지 않는다
```

판단 근거는 `content_hash` 다. 공식 更新日 은 있을 때도 없을 때도 있어서 그것만
보면 변경을 놓친다.

**확인에 실패했을 때는 아무 판단도 하지 않는다.** 그때 `removed` 를 매기면
사이트가 잠깐 죽었을 뿐인데 재정이 삭제됐다고 기록하게 된다.

재수집해도 기존 번역은 `merge_translations()` 로 옮겨 붙고, 원문이 바뀌었으면
`translation.is_stale()` 이 참이 되어 낡았다는 것이 드러난다.

## 테스트

```bash
python -m pytest tests/rulings -q
```

- **Identity** — 양방향 매핑, 1:N, 충돌 링크 거부, 중복 탐지, 한일 이름이 실제로 다름
- **Parsing** — 공식 사이트에서 **실제로 받은 페이지**(gzip 픽스처)로 검증.
  손으로 지어낸 HTML 로 시험하면 사이트가 바뀌어도 테스트가 계속 통과한다
- **Repository** — card_id / cid / ruling_id / 이름 / 분류 / 날짜 / 관련 카드 검색
- **Provenance** — 공식 출처, `language=ja`, 원문 보존, 번역 없음
- **Translation** — 원문과 번역의 분리, 번역은 언제나 non-authoritative
- **Incremental** — new / changed / removed / unchanged
- **Failure** — `ruling_not_found` 와 `source_unavailable` 의 분리

## 한계

- **번역기는 구현하지 않았다.** `RulingTranslation` 자리만 있고 비어 있다.
  공식 한국어 재정은 존재하지 않으므로, 채운다면 기계 번역이고 그때도
  `translation_source` 가 공식과 구분된다.
- **관련 카드에는 그 카드 자신도 들어간다.** 공식 페이지가 본문에서 자기 자신을
  링크하기 때문이고, 페이지가 준 그대로 보존한다. 걸러 쓰려면 호출자가 한다.
- `related_card_ids` 는 식별자 매핑에 있는 `cid` 만 옮긴다. 매핑에 없으면
  **빈 채로 둔다** — 추측하지 않는다.
- 공식 사이트의 태그는 `モンスター` / `魔法` / `罠` 수준이라 "대상 지정 효과인가"
  같은 질문에는 태그가 아니라 본문 검색이 필요하다.
- TCG 재정은 수집하지 않는다.
