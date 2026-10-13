# Phase 5-C — 갈라테아 Discord `/deck` 명령

- 기준 커밋: `6400b45` (Phase 5-B `/search`)
- 작업 브랜치: `claude/pensive-goodall-te1egy`
- 변경한 프로덕션 파일: **`app/discord_bot.py` 하나**
- 이번 범위: **`/deck` 하나.** `/combo` 는 구현하지 않았다 (§7).

---

## 1. 기존 덱 빌더의 진입점과 실제 호출 흐름 (§8-1)

구현 전에 저장소를 읽고 확인한 것이다. 추측해서 쓴 API 는 없다.

```
Discord /deck request:"오르페골 덱 짜줘"
      ↓
deck_command(interaction, request)           ← app/discord_bot.py (신규)
      ↓  defer() → asyncio.to_thread
SearchService.deck_texts(request_text)       ← app/discord_bot.py (신규)
      ↓
deck_messages(agent, request_text)           ← app/discord_bot.py (신규, 순수 함수)
      ↓
deck.request.parse_deck_request(text) -> DeckRequest
      ↓
deck.builder.DeckBuilder(agent.repository).build(request) -> DeckDraft
      ↓                  (내부에서 CardRepository.resolve_archetype 호출)
deck.validator.DeckValidator().validate(draft) -> DeckValidation
      ↓
paginate(lines) -> list[str]                 ← app/discord_bot.py (신규)
```

### 확인한 실제 인터페이스

| 대상 | 실제 서명 / 사실 |
|---|---|
| `parse_deck_request(text, language="ko")` | `DeckRequest(raw, themes, goals, excluded_names, language)` 를 돌려준다 |
| `DeckRequest.is_empty` | `not themes and not goals` — 프로퍼티 |
| `DeckRequest.describe_ko()` | 테마·목표·제외를 한국어 3줄로 |
| `DeckGoal` | `OPENING_STABILITY` · `BOARD_DISRUPTION` · `HAND_TRAP_WEIGHT` **셋뿐** |
| `DeckBuilder(repository, search_engine=None)` | 요구하는 것은 **`repository` 하나** |
| `DeckBuilder.build(request)` | `DeckDraft` |
| `DeckDraft` | `main` · `extra` (둘 다 `list[DeckSlot]`) · `requested_themes` · `resolved_themes` · `unresolved_themes` · `notes` · `main_count`/`extra_count` (프로퍼티) · `all_slots()` |
| `DeckSlot` | `card_id` · `name` · `copies` · `role` · `reason` · `theme` (frozen) |
| `CardRole.describe_ko()` | 6종 역할의 한국어 이름 |
| `DeckValidator(rulebook_path=None)` · `.validate(draft)` | `DeckValidation(findings=[RuleFinding…])` |
| `RuleFinding` | `rule` · `outcome` · `detail` · `source` |
| `ValidationOutcome` | `SATISFIED` · `VIOLATED` · `UNVERIFIABLE` |
| `app.main.cmd_deck(agent, args)` | 결과를 **`print`** 하고 argparse `args` 를 받는다 → **Discord 에서 재사용 불가** |

### 🔴 `app.main.cmd_deck` 을 부르지 않고 덱 계층을 직접 부르는 이유

`cmd_deck` 은 (1) `argparse` 의 `args` 객체를 받고 (2) 결과를 `print` 로
stdout 에 쓰고 (3) 종료 코드를 돌려준다. Discord 핸들러는 **문자열이
필요하다.** stdout 을 가로채는 것은 재사용이 아니라 우회다. 그래서
`cmd_deck` 이 부르는 것과 **같은 세 함수**를 같은 순서로 부른다 — 덱 구성
로직을 복사한 곳은 없다.

### 덱 빌더가 요구하는 카드 데이터

`DeckBuilder` 가 쓰는 것은 `repository.resolve_archetype(term)` 과
`repository.all_cards()` 다. 그 저장소는 `/search` 가 쓰는
`DeckAgent.repository` 와 **같은 객체**이므로 `/deck` 때문에 다시 만들지
않는다 (`test_42` 가 고정).

### 덱 빌더가 이미 지원하는 것과 지원하지 않는 것

| 지원함 | 근거 |
|---|---|
| 테마(카드군) 해석 | `resolve_archetype` — 공식 setcode |
| 목표 3종 반영 (매수·자르는 순서) | `_copies_for` · `_priority` |
| 카드명 제외 (`…제외`) | `_EXCLUDE_TAIL` + `_is_excluded` |
| 역할 분류 6종 (측정 가능한 신호만) | `_classify` |
| 메인 40장 / 엑스트라 15장 목표 | `_TARGET_MAIN` · `_TARGET_EXTRA` |
| 부족분 보강 + 그 사실 기록 | `_fill` — 기준은 `has_effect_from("HAND")` 하나 |
| 메인/엑스트라 장수 검증 | 룰북 `zones` 데이터 |

| **지원하지 않음** | 결과 |
|---|---|
| 동일명 3장 제한 | `UNVERIFIABLE` — 룰북 데이터에 없다 |
| 금지·제한(리미트 레귤레이션) | `UNVERIFIABLE` — 저장소에 데이터가 없다 |
| 메타·강도 평가 | 하지 않는다. 보강 기준은 카드 ID 순서이고 그 사실을 `notes` 에 적는다 |
| 전개 합법성 / 초동 확률 | 없다 (`/combo` 쪽이고 이번 범위 밖) |

---

## 2. 변경한 파일과 이유 (§8-2)

| 파일 | 변경 | 이유 |
|---|---|---|
| `app/discord_bot.py` | +280 / −15 | `/deck` 명령, `deck_messages`, `paginate`, `SearchService.deck_texts`, 상수 4개. **이번 단계의 유일한 프로덕션 변경** |
| `tests/test_discord_bot.py` | +499 / −28 | `/deck` 테스트 12개 추가 + 기존 3개를 사실에 맞게 갱신 |
| `docs/phase5c-galatea-discord-deck.md` | 신규 | 이 보고서 |

변경하지 않은 것: `app/main.py` · `core/` · `deck/` · `engine/` · `agent/`
· `analysis/` · `rules/` · `rulings/` · `sources/` · `data/` · `README` ·
Lua 파일. `git diff --stat` 이 두 파일만 보여 준다.

### 추가한 것

| 이름 | 역할 |
|---|---|
| `DECK_DESCRIPTION` | 명령 설명 |
| `DECK_UNAVAILABLE_MESSAGE` | 카드 데이터 초기화 실패 시 안내. 🔴 `/search` 와 **다른 문구** — 사용자가 무엇을 못 하는지 알아야 한다 |
| `DECK_ERROR_MESSAGE` | 빌더 예외 시 안내. 🔴 **예외 내용을 담지 않는다** |
| `DECK_MESSAGE_LIMIT = 4` | 한 명령이 보낼 최대 메시지 수 |
| `paginate(lines, limit, max_messages)` | 줄 목록 → 상한 이하 메시지 여러 개 |
| `_deck_slot_lines` · `_deck_reason_lines` · `_deck_validation_lines` | 표시 보조 |
| `deck_messages(agent, request_text)` | 순수 함수. discord 를 모른다 |
| `SearchService.deck_texts(request_text)` | 예외를 잡고 카드 데이터를 공유 |
| `/deck` 핸들러 | `defer` → `to_thread` → `followup` × n |

---

## 3. `/deck` 사용법과 입력 인자 (§8-3)

```
/deck request:<한국어 요청 문장>
```

인자는 **`request` 문자열 하나**이고 필수다.

### 🔴 인자를 하나로 둔 이유

`parse_deck_request` 는 테마·목표·제외를 **그 문장 하나에서** 읽는다.
Discord 쪽에 `theme`·`goal`·`exclude` 를 따로 만들면 파서를 우회하는 두
번째 입력 경로가 생기고, 같은 요청이 두 가지로 해석될 수 있다. §2-4
("중복 구현하지 않는다") 와 §4 ("기존 엔진이 지원하지 않는 조건을 새로운
기능인 것처럼 노출하지 않는다") 에 따라 하나로 뒀다.

### 쓸 수 있는 말 (실제로 파서가 읽는 것만)

| 쓰는 말 | 읽히는 것 |
|---|---|
| 카드군 이름 | 테마 — 여러 개는 `+` · `그리고` · `와` 로 잇는다 |
| `초동`, `초동 안정`, `안정성` | 목표 = 초동 안정성 우선 |
| `견제`, `제압`, `최종 필드` | 목표 = 최종 필드 견제력 우선 |
| `패트랩`, `핸드트랩` | 목표 = 패에서 발동하는 카드 비중 우선 |
| `<카드명> 제외` | 그 카드를 넣지 않는다 |

예:
- `/deck request:오르페골 덱 짜줘`
- `/deck request:오르페골 + K9으로 덱을 짜 줘. 초동 안정성을 우선하고 패트랩도 충분히`
- `/deck request:오르페골 클리막스 제외하고 오르페골 덱`

### 응답 구성 (빌더가 준 정보만)

1. 요청 해석 (`DeckRequest.describe_ko()`)
2. 메인/엑스트라 장수와 종류 수, 해석된 카드군
3. 메인 덱 · 엑스트라 덱 — `2x 이름 [카드ID] · 역할` 한 줄씩
4. 채택 근거 — `DeckSlot.reason` 을 묶어 `(n종류)` 와 함께
5. 덱 규격 검증 — 7개 항목, `✔`/`✗`/`?` 와 근거 규칙 ID
6. 구성 기록 — `DeckDraft.notes` 전부

🔴 **4번을 묶은 이유**: `reason` 은 (테마, 역할) 조합으로 정해져 카드마다
같은 문장이 반복된다. 카드마다 한 줄씩 적으면 덱 하나가 3,600자를 넘어
메시지 수만 늘어난다. 묶는 것은 **같은 정보의 다른 배치**이고, 몇 종류가
그 근거로 들어왔는지 함께 적으므로 버린 정보가 없다.

### 세 가지 입력 상태를 구분한다

| 상태 | 처리 |
|---|---|
| 테마도 목표도 못 읽음 (`is_empty`) | 🔴 **빌더를 부르지 않는다.** 어떻게 적는지 예시와 함께 안내 (CLI 도 같은 자리에서 종료 코드 1) |
| 테마가 **하나도** 카드군으로 해석되지 않음 | 🔴 **덱을 보내지 않는다.** 아래 §6 참조 |
| 일부만 해석됨 | 덱을 보내되 **실패한 테마를 맨 앞에** 적는다 |

---

## 4. Discord 구현 조건 (§5)

### 실측값

| 항목 | 값 |
|---|---|
| `prepare()` (카드 데이터) | 3,021 ms · `build_count = 1` |
| 덱 구성 + 검증 | **112~221 ms** |
| `/search` 는 그대로 | 773자, `build_count` 여전히 1 |

| 요청 | 메시지 수 | 각 길이 | 시간 |
|---|---|---|---|
| `오르페골 덱 짜줘` | 2 | [1972, 32] | 132 ms |
| `오르페골 + K9으로 … 패트랩도 충분히` | 2 | [1998, 253] | 197 ms |
| `오르페골 + 존재하지않는테마 덱 짜줘` | 2 | [1906, 233] | 221 ms |
| `존재하지않는테마 덱` | 1 | [215] | 112 ms |
| `덱` | 1 | [201] | 0 ms |

전부 2,000자 이하다.

### 🔴 왜 `clamp` 이 아니라 `paginate` 인가

Phase 5-B 보고서에 **S6** 으로 열어 둔 결정이다. 측정값은 그때와 같다 —
CLI 전체 출력이 3,109~3,617자로 상한의 1.6~1.8배다.

`clamp_to_discord_limit` 는 **버리고 버렸다고 적는다.** 검색 결과는 "상위
몇 건" 이 원래 의미이므로 그래도 된다. 덱은 다르다 — **40장 중 뒤 15장이
사라진 덱은 그 덱이 아니다.** 그래서 나눠 보내는 쪽을 골랐다.

세 선택지 중 이것을 고른 근거:

| 선택지 | 판단 |
|---|---|
| **나눠 보내기** (채택) | `followup.send` 를 여러 번 부르면 된다. 추가 의존성 0, 정보 손실 0 |
| Embed | 필드별 상한(1,024자)이 따로 있어 긴 카드 목록을 또 나눠야 한다. 상한 문제를 해결하지 못하고 표시 코드만 복잡해진다 |
| 파일 첨부 | Discord 에서 바로 읽을 수 없고, 모바일에서 더 불편하다 |

`paginate` 는 줄을 쪼개지 않고, 한 줄이 그 자체로 상한을 넘으면 그 줄만
`clamp` 하며, `DECK_MESSAGE_LIMIT`(4) 를 넘으면 **몇 줄을 못 보냈는지
적는다.** 조용히 끊지 않는다.

### 그 밖의 조건

- `defer()` 를 먼저 부른다 — 덱 구성은 221 ms 지만 카드 데이터가 아직
  준비되지 않았으면 그 자리에서 기다릴 수 있다.
- 동기 작업은 `asyncio.to_thread` — 이벤트 루프에서 돌리면 그 동안
  `/ping` 도 응답하지 않는다.
- 예외는 `SearchService.deck_texts` 가 잡는다. 스택은 `logger.exception`
  으로 로그에만, 사용자에게는 `DECK_ERROR_MESSAGE` 만 간다. 🔴 예외
  메시지에는 파일 경로 같은 내부 정보가 들어 있으므로 사용자 응답에 넣지
  않는다 (`test_38` 이 고정).
- 사용자 입력은 **문자열로만** 다룬다. `eval`·`exec`·셸 호출이 없고,
  `request` 는 `parse_deck_request` 에만 들어간다.
- 토큰 처리는 Phase 5-A 그대로 — 이번에 건드리지 않았다.
- `/ping`·`/search`·개발용 서버 동기화(`sync_commands`)는 그대로다.

---

## 5. 테스트 (§6 · §8-4 · §8-5)

### 실행 명령과 결과

```
$ python3 -m pytest tests/test_discord_bot.py -p no:randomly -q
46 passed, 1 warning in 7.50s

$ python3 -m pytest tests/test_discord_bot.py tests/test_deck_builder_planner.py \
    tests/test_korean_search.py tests/test_search_integration.py \
    tests/test_search_semantics.py tests/test_query_parser.py -p no:randomly -q
161 passed, 1 warning in 21.49s
```

추가로, 이 저장소에는 테스트 파일 목록·검색 다이제스트·`pytest.skip`
문구를 고정하는 감사 테스트가 있어서 테스트를 추가하면 그쪽이 깨질 수
있다. 그 3개 파일도 돌렸다:

```
$ python3 -m pytest tests/test_auxiliary_effect_creation_clone_audit.py \
    tests/test_provenance_consumer_audit.py \
    tests/test_update_coverage_contract_audit.py -p no:randomly -q
134 passed in 405.31s (0:06:45)
```

**실패한 테스트는 없다.** 경고 1개는 `discord.py` 가 Python 3.11 에서
`audioop` 을 import 하며 내는 `DeprecationWarning` 으로 이 저장소 코드와
무관하다. 변경 범위 밖의 전체 회귀 테스트는 돌리지 않았다.

### §6 요구 항목과 대응 테스트

| § | 요구 | 테스트 |
|---|---|---|
| 6-1 | `/deck` 이 등록되는가 | `test_32` (실제 트리 + 인자·필수 여부) · `test_18` (AST) · `test_19` |
| 6-2 | 유효한 입력이 기존 빌더에 전달되는가 | `test_33` — 스파이 빌더가 받은 `DeckRequest` 의 테마·목표를 확인하고, 저장소가 **에이전트의 것 그대로**인지 확인 |
| 6-3 | 결과가 올바른 Discord 응답이 되는가 | `test_34` — 장수·종류·카드줄·채택 근거·구성 기록·검증 결과 + 큰 초안(45종)에서 **하나도 빠지지 않음** |
| 6-4 | 잘못되거나 부족한 입력 | `test_35` (`is_empty` → 빌더 호출 0) · `test_36` (해석 실패 → 덱 미전송) · `test_37` (일부 해석 → 경고 선행 후 전송) |
| 6-5 | 빌더 예외에 봇이 죽지 않는가 | `test_38` (예외 → 안내 + 로그, 내부 경로 비노출) · `test_39` (초기화 실패 → 전용 안내, 재시도 없음) |
| 6-6 | 길이 제한 위반이 없는가 | `test_40` (`paginate` 경계·무손실·상한 초과 고지) · `test_43` (**실제 카드 데이터**) |
| 6-7 | 기존 `/ping`·`/search` 가 계속 통과하는가 | 같은 파일 46개 전부 + 관련 5개 파일 161개 |
| 5 | `defer` 선행 · 스레드 · 전 메시지 전송 | `test_41` |
| 5 | 저장소 중복 생성 없음 | `test_42` (`build_count == 1`, 두 명령 교차 실행) |

### 기존 테스트 3개를 사실에 맞게 갱신 (삭제·skip·약화 없음)

| 테스트 | 갱신 | 왜 기존 가정이 더 이상 사실이 아닌가 |
|---|---|---|
| `test_15` | 허용 import 에 `deck` 추가. 금지 목록은 `core`·`engine`·`agent`·`analysis`·`rules`·`rulings`·`sources` 로 유지 | `app.main.cmd_deck` 는 `print` 하고 argparse `args` 를 받으므로 재사용할 수 없다 → 덱 계층을 직접 부르는 것이 "복사하지 않는다" 를 지키는 방법이다. **대신 고정 조건을 늘렸다**: 재사용 함수 5개(`search_korean(`·`format_card_line(`·`parse_deck_request(`·`DeckBuilder(`·`DeckValidator(`)의 존재와, 중복 구현 7개(`SearchFilters(`·`CardSearchEngine(`·`KoreanQueryParser(`·`resolve_archetype(`·`CardRole.`·`ValidationOutcome.`·`RuleFinding(`)의 부재 |
| `test_18` | `registered == {"ping","search","deck"}` + `combo` 부재 | `/deck` 을 실제로 등록했다. 집합을 정확히 고정하므로 `/combo` 를 구현 없이 등록하면 실패한다 |
| `test_19` | `set(commands) == {"ping","search","deck"}` | 위와 같다 |

### 테스트가 비어 있지 않다는 확인 (돌연변이 검사)

프로덕션 코드를 일부러 망가뜨려 각 테스트가 **실제로 실패하는지** 확인한
뒤 원본을 복원하고 46개 통과를 다시 확인했다.

| 돌연변이 | 결과 |
|---|---|
| `/deck` 핸들러의 `defer()` 삭제 | **1 failed** (`test_41`) |
| 첫 메시지만 전송 (`texts[0]`) | **1 failed** (`test_41`) |
| 해석 실패여도 덱 전송 | **2 failed** (`test_36` · `test_43`) |
| `is_empty` 분기 무시 | **1 failed** (`test_35`) |
| `deck_texts` 의 `try/except` 제거 | **1 failed** (`test_38`) |
| `paginate` → `clamp` (잘라 보내기) | **2 failed** (`test_34` · `test_43`) |
| 채택 근거 생략 | **1 failed** (`test_34`) |
| 오류 응답에 스택 노출 | **1 failed** (`test_38`) |
| (복원 후) | **46 passed** |

### 단위 테스트와 실제 Discord 테스트의 구분

🔴 **위 161개는 전부 단위·통합 테스트다. Discord 서버에서 `/deck` 을
실행한 결과가 아니다.** `test_32`·`test_41` 은 실제
`discord.app_commands` 트리를 만들어 핸들러를 직접 부르지만, **접속하지
않고 가짜 `Interaction` 을 넣는다.**

---

## 6. 알려진 한계와 미해결 문제 (§7 · §8-6)

### 이번에 어댑터에서 막은 것 (S7 — `deck/` 은 고치지 않았다)

Phase 5-B 보고서의 **S7** 이다. 빌더는 테마 해석에 실패해도 덱을 돌려준다
— 실측으로 `"존재하지않는테마 덱"` 이 테마 밖 보강 카드 **20종 40장**을
낸다. CLI 에서는 `notes` 의 🔴 줄이 바로 보이지만, Discord 에서는 사용자가
그것을 "요청한 테마의 덱" 으로 받아들일 위험이 더 크다.

그래서 **해석된 카드군이 하나도 없으면 덱을 보내지 않고 안내만 한다.**
🔴 `deck/` 의 계약은 그대로 두고 "보여 줄지" 만 어댑터에서 정했다 (§2-8:
엔진 계약을 바꿔야만 되는 일이 아니었다). 일부라도 해석됐으면 덱을 보낸다
— 그 덱은 요청과 관계가 있기 때문이다.

### 숨기지 않고 보고하는 한계

1. **동일명 3장 제한과 금지·제한을 검증하지 못한다.** 룰북 데이터에 매수
   상한 규칙이 없고 저장소에 금지·제한 데이터가 없다. `/deck` 응답은 이
   두 항목을 `?` (검증 불가) 로 적고 "검증 불가 ≠ 통과" 를 함께 적는다.
   **그러므로 `/deck` 이 낸 덱이 공식 대회에서 적법한지는 알 수 없다.**
2. **메타 평가가 없다.** 부족분 보강 기준은 `has_effect_from("HAND")`
   하나이고 순서는 카드 ID 다. 강한 덱이 아니라 **규격을 맞춘 덱**이다.
   응답의 구성 기록에 그 사실이 그대로 적힌다.
3. **목표 3종이 전부다.** `초동 안정성` · `견제` · `패트랩 비중`. 그 밖의
   요청(예: "원핸드 전개", "후공 덱")은 목표로 읽히지 않고, 읽히지 않은
   말은 요청 해석 줄에 드러난다.
4. **전개 가능성을 확인하지 않는다.** `/deck` 은 덱을 구성하고 규격을
   검증할 뿐이다. 그 덱으로 전개가 되는지는 `/combo` 쪽이고, Phase 4-C
   측정대로 엔진에 효과 실행 구현이 있는 카드는 14,127장 중 **13장**이다.
5. **`SearchService` 라는 이름이 좁다.** 이제 `/search` 와 `/deck` 이
   같이 쓴다. 이름만 바꾸는 변경이 이번 목적이 아니고 이 클래스를
   가리키는 기존 테스트를 함께 건드려야 해서 그대로 뒀다 (§2-5). 클래스
   docstring 에 "명령들이 공유하는 카드 데이터 보관소" 라고 적어 뒀다.

### 이전 단계에서 열어 둔 채 유지하는 것

- **N62 · N63** (Phase 3-F-46): `UNKNOWN_BY_DESIGN`. 종료하지 않았다.
- **S5** (Phase 4-B): `git diff <base> HEAD` 기반 감사 8개 중 6개만 수정.
- **Phase 4-C**: 파괴 실행 미구현(`RULE_NOT_IMPLEMENTED`) · `DuelRunner._step`
  이 정책 위반과 엔진 거부를 같은 `accepted` 필드에 기록하는 분류 결함.

---

## 7. 실제 Discord 서버에서 추가로 확인해야 하는 것 (§8-7)

🔴 이 환경에는 유효한 봇 토큰이 없다. 아래는 **확인되지 않았다.**

1. **`/deck` 이 개발용 서버에 동기화되어 보이는지.** 명령이 3개로 늘었다
   (`sync_commands` 는 그대로지만 명령 수가 바뀌었다).
2. **긴 요청 문장이 Discord 인자 길이 제한에 걸리지 않는지.** 슬래시 명령
   문자열 인자의 상한은 이 저장소에서 측정한 값이 아니다.
3. **메시지 2개가 순서대로 도착하는지.** `followup.send` 를 연속으로 부르면
   보통 순서대로 오지만, 이 저장소에서 측정한 사실이 아니다. 순서가
   뒤바뀌면 메시지에 `(1/2)` 같은 표시를 붙여야 한다.
4. **3초 제한 안에서 `defer` 가 먼저 가는지** — 코드 순서는 테스트로
   고정했지만 실제 왕복 시간은 측정하지 못했다.
5. **`DECK_MESSAGE_LIMIT`(4) 가 실제 rate limit 과 맞는지.** 한 상호작용에
   짧은 간격으로 여러 메시지를 보내면 Discord 가 제한할 수 있다.

---

## 8. Git diff 요약 (§8-8)

```
 app/discord_bot.py        | +280 / −15
 tests/test_discord_bot.py | +499 / −28
```
신규: `docs/phase5c-galatea-discord-deck.md`

불필요한 변경이 없는지 확인한 것:

- `app/main.py` · `deck/` · `core/` · `engine/` · `agent/` · `analysis/`
  에 대한 `git diff` 가 **비어 있다.**
- `app/discord_bot.py` 에 `KOREAN_OVERLAY` · `.name_ko` ·
  `print_card_detail` · `.apply(` · `resolve_archetype(` · `CardRole.` ·
  `ValidationOutcome.` · `RuleFinding(` 가 **각 0회** (고정 문자열 기준).
- 새 테스트에 64자리 16진 다이제스트 리터럴 **0개**, 새 `pytest.skip`
  호출 **0개** (저장소의 감사 테스트가 고정하는 조건).
- CLI 가 그대로 동작한다 (`python3 -m app.main deck "오르페골 덱 짜줘"`).
- 새 의존성 **0개**.

---

## 9. 다음 단계 후보 (최대 1개)

**`/combo` 를 붙인다.** 다만 Phase 4-C 가 측정한 대로 엔진에 효과 실행
구현이 있는 카드가 13장이므로, 전개 계획의 대부분이 `UNKNOWN` 으로 나오는
것이 정상이다. 그 사실을 Discord 에서 어떻게 적어야 사용자가 "전개가
확인됐다" 고 오해하지 않는지가 그 단계의 실제 과제다.

🔴 다음 Phase 는 임의로 진행하지 않는다.
