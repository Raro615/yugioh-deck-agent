# Phase 5-B — 갈라테아 Discord `/search` 명령

- 기준 커밋: `ef677c7` (Phase 5-A 보고서)
- 작업 브랜치: `claude/pensive-goodall-te1egy`
- 변경한 프로덕션 파일: **`app/discord_bot.py` 하나**
- 변경한 테스트 파일: **`tests/test_discord_bot.py` 하나**
- 🔴 **커밋·푸시하지 않았다** (§10). 이 보고서는 커밋 전 상태를 적은 것이다.

---

## 1. 무엇을 구현했고 무엇을 구현하지 않았는가

이 구분을 먼저 적는다. 아래 "구현하지 않음" 에 있는 것은 **작동하지 않는다.**

| 기능 | 상태 | 근거 |
|---|---|---|
| `/ping` | ✅ 구현 (Phase 5-A) | 사용자가 Windows / Python 3.13.16 에서 실제 접속·응답 확인 |
| `/search` 한국어 검색 | ✅ 구현 (이번 단계) | 실제 데이터로 7개 질의 실행, `test_31` 이 회귀로 고정 |
| 검색 결과 0건 안내 | ✅ 구현 | `test_23` |
| 해석 실패(`unknown_terms`) 안내 | ✅ 구현 | `test_24` · `test_25` |
| 2,000자 상한 보장 | ✅ 구현 | `test_20` · `test_26` |
| 카드 데이터 1회 생성 | ✅ 구현 | `test_27` · `test_30` · `test_31` |
| 초기화 실패 안내 | ✅ 구현 | `test_28` |
| `defer()` 선행 + 스레드 실행 | ✅ 구현 | `test_29` |
| `/deck` (덱 구축) | ❌ **구현하지 않음** | 등록하지도 않았다. `test_18` 이 "등록 집합 = {ping, search}" 를 고정 |
| `/combo` (전개 계획) | ❌ **구현하지 않음** | 위와 같다 |
| 카드 상세 조회 명령 | ❌ 구현하지 않음 | CLI `app/main.py` 의 `print_card_detail` 은 Discord 로 연결하지 않았다 |
| 랜덤 초기 패 · 초동 확률 | ❌ 구현하지 않음 | Phase 4-B 에서 후속으로 남긴 범위다 |
| 전개 합법성 엔진 검증 | ❌ 구현하지 않음 | Phase 4-C 결론: 엔진은 14,127장 중 13장만 효과를 실행한다 |
| 파괴 실행 | ❌ 구현하지 않음 | Phase 4-C: `ValidationCode.RULE_NOT_IMPLEMENTED` |

---

## 2. 어떻게 기존 검색을 재사용했는가 (§2)

검색 로직을 **다시 쓰지 않았다.** `app/discord_bot.py` 는 `app.main` 의 것을
그대로 부른다.

```
Discord 슬래시 명령
      ↓
search_command(interaction, query)      ← discord 를 아는 유일한 자리
      ↓  asyncio.to_thread
SearchService.search_text(query)
      ↓
search_message(agent, query, limit)     ← discord 를 모르는 순수 함수
      ↓
DeckAgent.search_korean(query, limit)   ← 기존 파이프라인. 손대지 않았다
ParsedQuery.explain_ko()                ← 해석 설명도 기존 것
format_card_line(card, index)           ← CLI 와 같은 한 줄
```

`app/discord_bot.py` 가 **import 하는 것은 `app.main` 뿐**이다. 검색 계층을
직접 만들지 않는다 — 다음 이름은 이 파일에 **없다**:
`SearchFilters(` · `CardSearchEngine(` · `KoreanQueryParser(` (각 0회, §4 표 참조).
`test_15` 가 AST 로 import 집합을 고정하고, 이 세 이름의 부재를 함께 고정한다.

결과적으로 CLI 와 Discord 가 **같은 문자열**을 낸다. 한쪽에서 표시 규칙을
바꾸면 다른 쪽도 같이 바뀐다 — 두 번 고치지 않는다.

---

## 3. 무거운 초기화를 한 번만 하는 이유와 방법 (§3)

### 측정값 (이 환경, 실제 실행)

| 항목 | 값 |
|---|---|
| `SearchService.prepare()` 1회차 | **4,276 ms** |
| `prepare()` 2회차 (재사용) | **0.003 ms** |
| `build_count` (3회 호출 후) | **1** |
| Discord 가 첫 응답에 주는 시간 | **3,000 ms** |

🔴 **초기화 시간이 Discord 의 첫 응답 제한보다 길다.** 명령마다 다시 만들면
첫 응답이 제한을 넘고 상호작용이 만료된다. 그래서:

- `SearchService` 가 `on_ready` 에서 **한 번** 만들어 들고 있다.
- `prepare()` 는 이미 준비됐으면 즉시 `True` 를 돌려준다 — `on_ready` 는
  재접속 때 다시 불릴 수 있고, 그때마다 4초를 쓰면 안 된다.
- 준비 자체도 `asyncio.to_thread` 로 보낸다. 이벤트 루프에서 4초를 쓰면
  하트비트와 명령 동기화가 그동안 멈춘다.

### 실패했을 때 (§3 후단)

실패를 **삼키지 않는다.**

- `logger.exception("카드 데이터 초기화에 실패했습니다.")` — 스택까지 기록한다.
- 예외 객체를 `SearchService.error` 에 보관한다.
- 이후 `/search` 는 다음 문구를 돌려준다:
  > 지금은 카드 검색을 할 수 없습니다. 카드 데이터 초기화가 실패했습니다 — 봇 로그를 확인해 주세요.
- 🔴 **"조건에 맞는 카드가 없습니다" 를 돌려주지 않는다.** 그러면 사용자는
  그 카드가 존재하지 않는다고 믿는다. 두 문구를 분리한 것이 `test_28` 이
  고정하는 핵심이다.
- 실패를 명령마다 4초씩 재시도하지 않는다 (`build_count` 가 1에 머문다).
- `on_ready` 는 준비 실패로 **죽지 않는다.** 죽으면 `/ping` 조차 등록되지
  않는다 (`test_30`).

---

## 4. Discord 제한을 지키는 방법 (§4)

### 실측 출력 길이 (실제 카드 데이터, 상한 2,000자)

| 질의 | 길이 | 카드 줄 | 검색 시간 |
|---|---|---|---|
| `마법사족 몬스터` | 773자 | 10 | 14.6 ms |
| `레벨 4 화염 속성` | 694자 | 10 | 4.1 ms |
| `링크 2 몬스터` | 713자 | 10 | 2.2 ms |
| `오르페골` | 570자 | 10 | 156.4 ms |
| `마법사족 아무거나이상한말` | 844자 | 10 | 129.6 ms |
| `완전히알수없는질의어` | 55자 | 0 | 175.4 ms |
| `레벨 13 어둠 속성 기계족` | 66자 | 0 | 3.7 ms |

최대 844자로 상한의 42% 다. 그래도 길이 검사를 둔 이유:

🔴 **건수 제한(상위 10건)은 길이를 보장하지 않는다.** 카드 이름 길이는
카드마다 다르고, 해석 설명과 경고 줄의 길이도 질의마다 다르다. `test_26` 이
그 상황을 실제로 만든다 — 10건만 넣어도 2,510자가 되는 입력에서
`clamp_to_discord_limit` 가 2,000자 이하를 보장한다.

자를 때는 **줄 경계**에서 자르고(카드 한 줄이 반토막 나지 않게),
`… (길이 제한으로 줄였습니다)` 를 붙인다 — 자른 사실을 적지 않으면
사용자는 결과가 그것뿐이라고 믿는다.

### `defer()` 와 스레드

```python
await interaction.response.defer()                                   # ① 먼저
text = await asyncio.to_thread(search_service.search_text, query)    # ② 루프 밖
await interaction.followup.send(text)                                # ③ 후속 응답
```

- ①이 없으면 3초 제한에 걸린다. 검색 자체는 2~176 ms 지만, 카드 데이터가
  아직 준비되지 않은 상태라면 그 자리에서 기다릴 수 있다.
- ②가 없으면 (동기 검색을 이벤트 루프에서 돌리면) 그 시간 동안 봇 전체가
  멈추고 `/ping` 도 응답하지 않는다.
- `test_29` 가 **실제 `app_commands` 핸들러**를 거쳐 ①→②→③ 순서와,
  검색이 이벤트 루프 스레드가 **아닌** 곳에서 돈 사실을 확인한다
  (`threading.get_ident()` 비교).

---

## 5. 세 가지 결과 상태를 구분한다 (§5)

🔴 **해석에 실패한 검색어를 정상적으로 검색된 것처럼 표시하지 않는다.**

### ① 정상

```
🔎 검색: `마법사족 몬스터`
해석: 마법사족, 몬스터
검색 결과: 794장 (상위 10장 표시)
  1. ...
```

총 건수와 **보여 준 건수**를 함께 적는다. 794장 중 10장만 보여 주면서
그것이 전부인 것처럼 적지 않는다.

### ② 해석 실패 (결과는 있음)

```
🔎 검색: `마법사족 아무거나이상한말`
해석: 마법사족, 몬스터
인식하지 못한 표현: 아무거나이상한말
⚠️ 해석하지 못한 말: `아무거나이상한말` — **조건에 넣지 않았습니다.**
검색 결과: 794장 (상위 10장 표시)
  1. ...
```

794장이 나왔다는 사실은 그대로 적지만, `아무거나이상한말` 이 조건에
**들어가지 않았다**는 사실을 함께 적는다. 결과가 나왔다는 이유로 해석에
성공한 것처럼 적으면 사용자는 **다른 질문의 답**을 보게 된다.

🔴 이 예가 왜 위험한지 숫자로 드러난다: `마법사족 몬스터` 의 결과도
**794장으로 같다.** 해석되지 않은 말이 조건에서 그냥 빠졌기 때문이다.
경고 줄이 없으면 사용자는 `아무거나이상한말` 조건이 적용된 794장을 보고
있다고 믿는다.

### ③ 결과 0건

```
🔎 검색: `레벨 13 어둠 속성 기계족`
해석: 기계족, 어둠속성, 레벨 13, 몬스터
조건에 맞는 카드가 없습니다.
```

해석은 성공했고 결과만 없는 경우다. 여기에는 해석 실패 안내를 섞지 않는다 —
원인을 잘못 짚게 만든다.

해석 실패와 0건이 **겹치면** 그때만 한 줄을 덧붙인다:
> 해석하지 못한 말이 원인일 수 있습니다. 다른 말로 다시 물어봐 주세요.

`test_25` 가 ②·③ 두 문구가 **같지 않다**는 것을 고정한다.

---

## 6. 변경한 코드 (§1)

### `app/discord_bot.py` (+230 / −22)

| 추가 | 역할 |
|---|---|
| `SEARCH_DESCRIPTION` | 명령 설명 문구 |
| `DISCORD_MESSAGE_LIMIT = 2000` | 메시지 상한 |
| `SEARCH_RESULT_LIMIT = 10` | 표시 건수 상한 (§4 "상위 10건 이내") |
| `UNAVAILABLE_MESSAGE` | 초기화 실패 안내 문구 |
| `TRUNCATION_NOTICE` | 잘렸다는 사실을 적는 문구 |
| `clamp_to_discord_limit(text, limit)` | 길이 보장. 줄 경계에서 자른다 |
| `search_message(agent, query, limit)` | **순수 함수.** discord 를 모른다 |
| `SearchService` | 카드 데이터를 1회 만들어 들고 있는 자리 |
| `SEARCH_SERVICE` | 봇 하나가 쓰는 서비스 하나 |
| `/search` 핸들러 | `defer` → `to_thread` → `followup` |
| `on_ready` 의 `prepare()` | 4초짜리 초기화를 여기서 한 번 |
| `build_client(dev_guild_id, service=None)` | `service` 주입 지점 추가 |

변경하지 않은 것: `app/main.py` · `core/` · `deck/` · `engine/` · `agent/` ·
`analysis/` · `rules/` · `rulings/` · `sources/` · `data/` · `README` ·
Lua 파일. `git diff --stat` 이 두 파일만 보여 준다.

### 두 가지 설계 선택을 기록해 둔다

**(1) `SearchService` 를 왜 클래스로 두었는가.** 모듈 전역 변수로 두면
"한 번만 만들었다" 를 테스트가 **세어 볼 방법이 없고**, 테스트가 서로의
상태를 물려받는다. `build_count` 와 `builder` 주입이 그래서 있다.

**(2) `@tree.command` 의 이름 가림 — 작업 중 실제로 깨졌다.** `build_client`
안에서 서비스 변수를 `search` 로 두었더니, 아래의
`@tree.command ... async def search` 가 **같은 스코프에 같은 이름을 다시
바인딩**해서 그 변수를 가렸다. 핸들러가 `Command` 객체에서 `search_text` 를
찾다가 `AttributeError` 로 죽었다. 변수를 `search_service`, 함수를
`search_command` 로 바꿔 해결했고, 같은 실수를 반복하지 않도록 코드에
🔴 주석으로 경위를 남겼다.

---

## 7. 테스트 (§7 · §8)

### 기존 테스트를 어떻게 다루었는가

🔴 **삭제·skip 추가·assertion 약화는 없다.** 두 개를 **사실에 맞게 갱신**했다.

| 테스트 | 갱신 전 | 갱신 후 | 왜 기존 가정이 틀렸는가 |
|---|---|---|---|
| `test_15` | `"app" not in imported` — 봇이 다른 계층을 전혀 import 하지 않는다 | `"app" in imported` **그리고** `deck/core/engine/agent/analysis/rules/rulings/sources` 부재 + `search_korean(` · `format_card_line(` 존재 + `SearchFilters(` · `CardSearchEngine(` · `KoreanQueryParser(` 부재 | Phase 5-A 의 봇은 어떤 계층도 안 썼으므로 "아무것도 import 하지 않는다" 가 사실이었다. Phase 5-B 는 **의도적으로** `app.main` 을 재사용한다(§2) — 그것이 검색 로직 중복을 막는 방법이다. 그래서 "아무것도 import 하지 않는다" 를 "**`app.main` 만** import 하고, 검색 엔진을 직접 만들지 않는다" 로 바꿨다. 고정 조건의 **개수는 늘었다** — 약화가 아니다 |
| `test_18` | `registered == {"ping"}` | `registered == {"ping", "search"}` + `deck` · `combo` 부재 | `/search` 를 실제로 등록했으므로 사실이 바뀌었다. `/deck` · `/combo` 가 끼면 여전히 실패한다 |
| `test_08` | 가짜 `build_client` 를 `lambda guild: ...` 로 교체 | `lambda guild, service=None: ...` | `build_client` 가 `service` 인자를 받게 됐다. 서명을 안 맞추면 이 테스트는 "토큰이 안 샌다" 가 아니라 `TypeError` 를 본다 — **의미는 그대로**다 |
| `test_19` | `[c.name for c in commands] == ["ping"]`, `commands[0]` | `set(commands) == {"ping","search"}`, 이름으로 `ping` 을 꺼낸다 | 등록 집합이 늘었다. 집합을 **여전히 정확히** 고정한다 |

### 새로 추가한 테스트 12개

| 테스트 | 무엇을 고정하는가 | §7 항목 |
|---|---|---|
| `test_20` | 2,000자 상한 보장 · 경계값 · 줄 경계 절단 · 안내 문구 | 출력 길이 제한 |
| `test_21` | 정상 검색: 총 건수 + 보여 준 건수 + `format_card_line` 과 같은 줄 + `limit` 전달 | 정상 검색 |
| `test_22` | 결과가 상한보다 적으면 "상위 N장 표시" 를 **적지 않는다** | 정상 검색 |
| `test_23` | 0건: 그 사실을 적고 카드 줄이 **없다** · 해석 실패 문구를 섞지 않는다 | 결과 0건 |
| `test_24` | `unknown_terms` 를 그대로 적고 "조건에 넣지 않았습니다" 를 붙인다 | 해석 실패 |
| `test_25` | 0건과 해석 실패를 **구분**한다 (두 문구가 같지 않다) | 결과 0건 · 해석 실패 |
| `test_26` | 건수 상한을 지켜도 길이를 넘는 경우에 보장이 작동한다 | 출력 길이 제한 |
| `test_27` | `prepare()` 3회 + `search_text()` 5회 후에도 `build_count == 1` | 리포지토리 1회 생성 |
| `test_28` | 실패를 기록·보관하고 안내 문구를 돌려준다 · 0건으로 위장하지 않는다 · 재시도하지 않는다 | 초기화 실패 |
| `test_29` | 실제 핸들러에서 `defer` → `search` → `followup` 순서 + 검색이 루프 스레드 밖 | `defer()` · 비동기 스레드 |
| `test_30` | `on_ready` 가 `prepare` 를 스레드에서 1회 부르고 **실패해도** 동기화를 계속한다 | 리포지토리 1회 생성 · 초기화 실패 |
| `test_31` | **실제 카드 데이터**로 4개 질의: 길이 ≤ 2,000 · 카드 줄 ≤ 10 · `build_count == 1` | 정상 검색 · 출력 길이 제한 |

`test_29` · `test_30` 은 `pytest.importorskip("discord")` 로 봇 전용 의존성이
없는 환경에서만 건너뛴다. `test_31` 은 `tests/conftest.py` 의
`requires_official_db` 표식을 쓴다 (`cards.cdb` 없으면 건너뜀) —
🔴 **새 `pytest.skip` 호출은 추가하지 않았다.**

### 테스트가 비어 있지 않다는 확인 (돌연변이 검사)

"통과한다" 와 "무언가를 실제로 고정한다" 는 다르다. 프로덕션 코드를 일부러
망가뜨려 각 테스트가 **실제로 실패하는지** 확인했다. 확인 후 원본을 복원하고
34개 통과를 다시 확인했다.

| 돌연변이 | 결과 |
|---|---|
| `await interaction.response.defer()` 삭제 | **1 failed** (`test_29`) |
| `clamp_to_discord_limit` 를 무조건 통과로 | **2 failed** (`test_20` · `test_26`) |
| 초기화 실패 시 `UNAVAILABLE_MESSAGE` → `"조건에 맞는 카드가 없습니다."` | **1 failed** (`test_28`) |
| `prepare()` 의 재사용 분기 삭제 (매번 재빌드) | **1 failed** (`test_27`) |
| `asyncio.to_thread(...)` → 직접 호출 | **1 failed** (`test_29`) |
| `unknown_terms` 경고 줄 생성 삭제 | **2 failed** (`test_24` · `test_25`) |
| (복원 후) | **34 passed** |

### 실행 결과 (§8)

변경 범위 밖의 전체 회귀 테스트는 실행하지 않았다.

```
$ python3 -m pytest tests/test_discord_bot.py -p no:randomly -q
34 passed, 1 warning in 4.12s

$ python3 -m pytest tests/test_discord_bot.py tests/test_korean_search.py \
    tests/test_search_integration.py tests/test_search_semantics.py \
    tests/test_query_parser.py -p no:randomly -q
113 passed, 1 warning in 17.05s
```

(경고 1개는 `discord.py` 가 Python 3.11 에서 `audioop` 을 import 하며 내는
`DeprecationWarning` 이다. 이 저장소 코드와 무관하다.)

추가로, **새 테스트 파일이 아닌데도** 이 저장소에는 테스트 파일 목록·검색
다이제스트·`pytest.skip` 문구를 고정하는 감사 테스트가 있어서, 테스트를
추가하면 그쪽이 깨질 수 있다. 정적으로 먼저 확인했다 —
`app/discord_bot.py` 에 `KOREAN_OVERLAY` · `.name_ko` · `print_card_detail` ·
`.apply(` · `TextEffectAnalyzer` 가 **각 0회**, 새 테스트에 64자리 16진
다이제스트 리터럴 **0개**, 새 `pytest.skip` 호출 **0개**. 그다음 해당 감사
3개 파일을 실제로 돌렸다:

```
$ python3 -m pytest tests/test_auxiliary_effect_creation_clone_audit.py     tests/test_provenance_consumer_audit.py     tests/test_update_coverage_contract_audit.py -p no:randomly -q
134 passed in 445.34s (0:07:25)
```

이 3개는 §8 이 말한 "변경 범위" 밖이지만, 내 변경이 **그것들을 깨뜨리는지**
확인하는 목적이므로 돌렸다. 전체 회귀 테스트는 돌리지 않았다.

---

## 8. 실제로 확인하지 않은 것

🔴 **Discord 에 접속해 `/search` 를 실행한 결과는 확인하지 않았다.** 이
환경에는 유효한 봇 토큰이 없고, 토큰을 요구하지도 않는다 (Phase 5-A §3.3 ·
§5). 확인한 것은 다음까지다:

- 실제 카드 데이터로 `SearchService` → `search_message` 경로를 돌려 문구와
  길이를 측정했다 (§4 표).
- 실제 `discord.app_commands` 트리를 만들어 `/search` 핸들러를 직접 호출해
  `defer` → 스레드 → `followup` 순서를 확인했다 (`test_29`). **접속은 하지
  않았다** — 가짜 `Interaction` 을 넣었다.

Discord 서버에서의 동작 확인은 토큰을 가진 환경에서 해야 한다.

---

## 9. 구조적으로 미해결로 남긴 것 (§10 — 보고만 한다)

이번 단계에서 **확대하지 않았다.** 이유만 적는다.

### S6. `/deck` 출력이 Discord 메시지 상한을 넘는다

Phase 4-A 에서 측정한 `/deck` 상당 출력은 **3,102~3,367자**로 상한의
**1.6~1.7배**다. `/search` 처럼 잘라서 보내면 덱 목록의 뒷부분이 사라지는데,
덱은 "일부만 보여 주면 되는 목록" 이 아니다. 선택지는 세 가지고 **아직
결정하지 않았다**:

1. 메시지를 여러 개로 나눈다 (후속 메시지 순서가 보장되는지 확인 필요).
2. `discord.Embed` 로 바꾼다 (필드별 상한이 다르다 — 재측정 필요).
3. 파일 첨부로 보낸다 (복사·붙여넣기는 쉬워지지만 읽기가 불편해진다).

### S7. 해석되지 않은 테마로도 덱이 만들어진다

Phase 4-B 의 `parse_deck_request` 는 테마를 해석하지 못해도 덱을 돌려준다.
CLI 에서는 `explain_ko()` 와 경고가 바로 보이지만, Discord 에서는 사용자가
그 덱을 "요청한 테마의 덱" 으로 받아들일 위험이 더 크다. `/deck` 을 붙일 때
**0건·해석 실패를 어떻게 구분해 보여 줄지**를 `/search` 와 같은 수준으로
먼저 정해야 한다.

### 이전 단계에서 열어 둔 항목 (이번 단계와 무관하게 유지)

- **N62 · N63** (Phase 3-F-46): `UNKNOWN_BY_DESIGN`. 임의로 종료하지 않았다.
- **S5** (Phase 4-B): `git diff <base> HEAD` 기반 감사 8개 중 6개만 수정했다.
- **Phase 4-C**: 파괴 실행 미구현 (`RULE_NOT_IMPLEMENTED`) · `DuelRunner._step`
  이 정책 위반과 엔진 거부를 같은 `accepted` 필드에 기록하는 분류 결함.

---

## 10. 다음 단계 후보 (최대 1개)

**`/deck` 을 붙이기 전에 출력 전달 방식을 먼저 정한다 (S6).** 측정은 이미
있다 (3,102~3,367자). 다음 단계는 세 선택지 중 하나를 **실제로 측정해**
고르는 것이고, 그것 없이 `/deck` 을 붙이면 잘린 덱을 보내게 된다.

🔴 다음 Phase 는 임의로 진행하지 않는다.
