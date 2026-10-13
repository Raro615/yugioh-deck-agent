# Phase 5-A — 갈라테아(Galatea) Discord 봇 최소 구현

**기준 commit**: `974f2d4` (Phase 4-C 완료 상태) · **작업일**: 2026-10-13

---

## 0. 한 줄 요약

`/ping` 하나만 가진 Discord 어댑터를 추가했다. **덱 구축·전개 계획은
연결하지 않았다.** 토큰은 환경변수에서만 읽고 로그에 새지 않는다.
🔴 **실제 Discord 접속은 확인하지 않았다** — 유효한 토큰이 필요하고
그것은 사용자의 로컬 환경에서 할 일이다.

---

## 1. 작업 전 상태 (조사 결과)

| 항목 | 값 |
|---|---|
| branch | `claude/pensive-goodall-te1egy` |
| HEAD | `974f2d4` = origin ✔ · 작업 트리 clean ✔ |
| Python | **3.11.15** |
| 의존성 관리 | **`requirements-dev.txt` 하나뿐** (`pytest>=7.0`) |
| 런타임 서드파티 의존 | 🔴 **사실상 없다** — AST 전수 조사 결과 `pymupdf` 한 곳(룰북 추출 스크립트)뿐 |
| CLI 진입점 | `app/main.py` (`python3 -m app.main`), 서브커맨드 11개 |
| Phase 4-B 모듈 | `deck/` — `request.py` · `builder.py` · `validator.py` · `hand.py` · `planner.py` · `report.py` · `model.py` |
| 환경변수 관용구 | `os.environ.get("YGO_CARDS_CDB")` · `os.environ.get("YGO_KO_DIR")` |
| `.gitignore` | `.env` **없었다** → 추가했다 |
| 로깅 | 🔴 프로젝트에 `import logging` 이 **한 곳도 없었다** — CLI 는 `print` + `sys.stderr` |

### 1.1 이 조사가 설계를 바꾼 두 가지

**(1) 저장소가 순수 표준 라이브러리다.** 봇 때문에 그 성질을 깨면
`discord.py` 가 없는 환경에서 봇 모듈을 **읽는 것조차** 실패한다. 그래서
`discord` 를 **함수 안에서만** import 한다 (§2.2).

**(2) 로깅 관용구가 없었다.** CLI 는 `print` 를 쓰지만 봇은 장시간 돌고
`discord` 라이브러리도 로그를 낸다 — 두 출력이 한 흐름으로 섞여야 원인을
짚을 수 있다. 그래서 봇만 `logging` 을 쓰고, **기존 CLI 의 출력 방식은
건드리지 않았다.**

---

## 2. 변경한 파일과 역할

| 파일 | 상태 | 역할 |
|---|---|---|
| `app/discord_bot.py` | **신규** (236줄) | Discord 어댑터. `/ping` · 토큰·서버 ID 읽기 · 명령 동기화 · 로깅 |
| `requirements-bot.txt` | **신규** | 봇 전용 의존성 (`discord.py>=2.3,<3`) |
| `.env.example` | **신규** | 설정 예시. 🔴 값은 **비어 있다** |
| `.gitignore` | 수정 (+4줄) | `.env` · `.env.*` 무시, `!.env.example` 예외 |
| `tests/test_discord_bot.py` | **신규** (19개 함수 / 22개 수집) | 표적 테스트 |
| `docs/phase5a-galatea-discord-bot.md` | **신규** | 이 보고서 |

**건드리지 않은 것**: `app/main.py` · `deck/` · `core/` · `engine/` ·
`agent/` · `analysis/` · `requirements-dev.txt` · `README.md`.
Engine V1 · `PlayerAction` 계약 변경 **0건**.

### 2.1 구조 — 어댑터는 얇다

```
Discord 슬래시 명령
      ↓
CommandTree 핸들러            ← discord 를 아는 유일한 자리
      ↓  받아서 넘기기만 한다
순수 응답 생성 함수            ← discord 를 모른다. 테스트가 여기를 본다
      ↓
(앞으로) core · deck 계층      ← 🔴 아직 연결하지 않았다
```

핸들러는 이렇게만 생겼다.

```python
@tree.command(name="ping", description=PING_DESCRIPTION)
async def ping(interaction: "discord.Interaction") -> None:
    await interaction.response.send_message(ping_message())
```

🔴 **문구를 핸들러 안에 쓰지 않는다.** 쓰면 `Interaction` 없이 부를 수
없어 테스트되지 않는다. `test_04` 가 핸들러 안에 `"Pong!"` 이 없고
`ping_message()` 호출만 있음을 AST 로 못 박는다.

### 2.2 `discord` 를 함수 안에서 import 하는 이유

모듈 최상위 import 는 `logging` · `os` · `sys` 뿐이다. `discord` 는
`build_client()` 와 `main()` 안에서만 import 한다. 그 결과:

* 토큰 처리와 응답 문구가 **라이브러리 없이 테스트된다.**
* 저장소의 "런타임 순수 표준 라이브러리" 성질이 유지된다.
* `test_01` 이 AST 로 최상위 import 를 검사해 이것을 고정한다.

🔴 **파일 이름이 `discord_bot.py` 인 이유**: `discord.py` 로 두면
`import discord` 가 라이브러리 대신 이 파일을 집는다 (`test_02` 가 저장소
어디에도 `discord.py` 가 없음을 확인한다).

### 2.3 명령 동기화 — 개발용 서버와 전역

| 설정 | 동작 |
|---|---|
| `DISCORD_DEV_GUILD_ID` 있음 | `tree.copy_global_to(guild)` → `tree.sync(guild=...)`. **그 서버에만** 올라가고 즉시 보인다 |
| 없음 | `tree.sync()` 전역 동기화. **반영이 느릴 수 있다는 사실을 로그에 적는다** — "명령이 안 보인다" 의 가장 흔한 원인이 이것이다 |
| 있는데 정수가 아님 | 🔴 **거부하고 종료 코드 2.** 조용히 무시하면 "동기화했는데 안 보인다" 를 디버깅할 수 없다 |

서버 ID 를 코드에 넣지 않았다. `test_12` 가 소스에 17~20자리 숫자
리터럴(=실제 서버 ID 모양)이 없음을 정규식으로 확인한다.

### 2.4 특권 intent 를 켜지 않았다

`discord.Intents.default()` 만 쓴다. 슬래시 명령은 메시지 내용을 읽지
않으므로 `message_content` 특권 intent 가 **필요하지 않다** — 켜면
Discord 쪽 승인이 필요해지고 얻는 것이 없다. `test_19` 가 실제
클라이언트에서 `intents.message_content is False` 를 확인한다.

---

## 3. 필요한 의존성과 설치

```bash
python3 -m pip install -r requirements-bot.txt
```

`requirements-bot.txt` 는 `discord.py>=2.3,<3` 하나다. 🔴 **기존
`requirements-dev.txt` 는 건드리지 않았다** — 봇은 선택적이고, 본체는
이것 없이도 전부 돈다 (`test_17` 이 확인한다).

이 환경에서 설치해 본 결과 **`discord.py` 2.7.1** 이 들어왔고,
전이 의존 중 `idna` 가 빠져 있어 따로 넣어야 했다. 같은 일이 생기면:

```bash
python3 -m pip install idna
```

---

## 4. `DISCORD_BOT_TOKEN` 설정 방법

🔴 **토큰을 채팅에 붙이지 마세요.** 아래는 로컬에서만 하는 일입니다.

### 방법 A — `.env` 파일 (권장)

```bash
cp .env.example .env
# .env 를 편집기로 열어 DISCORD_BOT_TOKEN= 뒤에 값을 붙여넣는다
```

`.env` 는 `.gitignore` 에 있으므로 커밋되지 않는다 (`git check-ignore`
로 실제 확인했다). `.env.example` 만 커밋된다.

🔴 **다만 이번 단계에서 `.env` 를 자동으로 읽는 코드는 넣지 않았다.**
그러려면 `python-dotenv` 의존성이 하나 더 필요하고, 그것은 이번 범위에
없다. 그래서 `.env` 를 쓰려면 셸에서 불러온다:

```bash
set -a && . ./.env && set +a
python3 -m app.discord_bot
```

### 방법 B — 셸 환경변수만

```bash
export DISCORD_BOT_TOKEN='여기에_봇_토큰'
export DISCORD_DEV_GUILD_ID='여기에_테스트_서버_ID'   # 선택
python3 -m app.discord_bot
```

토큰 발급: Discord Developer Portal → Applications → (앱) → Bot →
**Reset Token**. 봇을 서버에 넣을 때는 OAuth2 → URL Generator 에서
`bot` + `applications.commands` 범위를 고른다 — `applications.commands`
가 없으면 슬래시 명령이 등록되지 않는다.

---

## 5. 실행 명령

```bash
python3 -m app.discord_bot
```

종료 코드: `0` 정상 · `2` 설정 오류(토큰 없음·서버 ID 형식) ·
`1` 로그인 실패나 그 밖의 오류. 기존 CLI 가 설정 오류에 `2` 를 쓰는 것과
같은 규칙이다.

실측 (토큰 없이 실행):

```
$ python3 -m app.discord_bot
2026-10-13 10:14:45,792 ERROR   galatea: DISCORD_BOT_TOKEN 환경변수가 없습니다.
  .env.example 를 참고해 설정하세요 (토큰 값은 로그에 남기지 않습니다).
   종료 코드: 2
```

실측 (서버 ID 가 정수가 아닐 때):

```
2026-10-13 10:14:45,884 ERROR   galatea: DISCORD_DEV_GUILD_ID 는 서버 ID(정수)여야 합니다: 'not-a-number'
   종료 코드: 2
```

---

## 6. `/ping` 테스트 방법

### 6.1 로컬에서 (실제 Discord 없이)

```bash
python3 -m pytest tests/test_discord_bot.py -q
```

### 6.2 실제 Discord 에서 (사용자가 할 일)

1. 봇을 서버에 초대한다 (`bot` + `applications.commands` 범위).
2. `DISCORD_BOT_TOKEN` 을 설정한다. 테스트 서버가 있으면
   `DISCORD_DEV_GUILD_ID` 도 설정한다 — **그 서버에 즉시 등록된다.**
3. `python3 -m app.discord_bot` 를 돌린다. 로그에
   `갈라테아 접속 완료: <봇이름> (id=...)` 와
   `개발용 서버 동기화 완료: guild=... 명령 1개` 가 나오면 등록됐다.
4. Discord 에서 `/ping` 을 입력한다 → `Pong! 갈라테아 온라인.`

**명령이 안 보일 때**: `DISCORD_DEV_GUILD_ID` 를 설정하지 않았다면
전역 동기화라 반영이 느릴 수 있다 (로그가 그 사실을 적는다). 초대 URL 에
`applications.commands` 범위가 빠졌을 때도 보이지 않는다.

---

## 7. 실행한 테스트와 결과

### 7.1 신규 표적 테스트

`tests/test_discord_bot.py` — **19개 함수 / 22개 수집**.

| 구획 | 내용 | 수 |
|---|---|---|
| A | import 성질 (discord 없이 import · 파일명 충돌 없음) | 2 |
| B | `/ping` 문구 · 핸들러가 순수 함수에 위임 | 2 |
| C | 토큰 — 없음·공백 거부(4경우) · strip · **코드 2 종료** · 🔴 **로그 누출 없음** · 소스·예시 파일에 값 없음 · `.gitignore` | 6 |
| D | 개발용 서버 ID — 없음은 정상 · 정수 파싱 · 하드코딩 없음 · 형식 오류 거부 · 코드 2 | 4 |
| E | 기존 프로젝트와의 분리 — 어댑터가 어느 계층도 import 하지 않음 · 기존 CLI 정상 · 의존성 선언 · 미구현 표기 · **실제 핸들러 호출** | 5 |

```
22 passed in 1.22s
```

### 7.2 실제 `discord` 객체로 오프라인 확인 (접속 없음)

```
클라이언트: Client  intents.message_content=False
등록된 명령 1개:
   /ping — 갈라테아가 살아 있는지 확인합니다
/ping 응답: 'Pong! 갈라테아 온라인.'
✔ 실제 app_commands 핸들러가 기대 문구를 보낸다
```

### 7.3 토큰 누출 검사 (`test_08`)

토큰을 넣고 접속 직전까지 간 뒤(`client.run` 을 가로채 호출만 기록)
로그 전체에서 값을 찾는다.

* `client.run` 에 토큰이 **전달됐다** — 기능은 살아 있다.
* 🔴 그런데 `caplog.text` 와 모든 `record.getMessage()` 에 값이 **없다.**

### 7.4 기존 기능 회귀

production 을 전수 스윕하는 감사와 한국어 표시 계약 테스트를 골라
돌렸다 (`-k "changed_no_production_file or print_card_detail or name_ko
or KOREAN or korean_available"`).

```
159 passed, 5429 deselected in 259.84s (0:04:19)
```

기존 CLI 도 실제로 돌렸다.

```
$ python3 -m app.main card 483
패러렐 텔레포트 · 마법/속공
  카드 ID : 483

$ python3 -m app.main deck "오르페골 덱"
요청 해석
테마: 오르페골
```

둘 다 정상이다 — 봇 추가가 기존 진입점을 깨지 않았다.

**전체 회귀는 실행하지 않았다** (§5 의 지시). 변경은 신규 파일 4개와
`.gitignore` 4줄뿐이고, 기존 production 모듈을 한 줄도 바꾸지 않았다.
`app/` 아래 파일이 늘었으므로 **production 을 전수 스윕하는 감사**와
**기존 CLI 진입점**만 골라 확인했다.

---

## 8. 🔴 실제 Discord 접속 확인 여부

**확인하지 않았다.**

* 유효한 봇 토큰이 필요하고, 토큰은 사용자만 가지고 있다.
* 토큰을 테스트 코드나 이 저장소에 적지 않는다.
* 이 세션의 네트워크에서 Discord 게이트웨이에 붙을 수 있는지도 확인하지
  않았다.

그래서 **"봇이 Discord 에서 동작한다" 고 보고하지 않는다.** 확인된 것은
§7 의 범위 — 명령 등록, 응답 문구, 토큰 처리, 안전 종료, 누출 없음 —
까지다. 완료 기준의 마지막 한 걸음(`/ping` 에 대한 실제 응답)은
§6.2 대로 사용자의 로컬 환경에서 확인해야 한다.

---

## 9. 다음 단계 — `/deck` 을 Phase 4-B 에 연결하는 방법

🔴 **이번 단계에서 하지 않았다.** 아래는 설계 메모이고, 같은 내용이
`app/discord_bot.py` 끝의 "확장 지점" 주석에도 있다.

1. **순수 함수를 하나 더 둔다.** `ping_message()` 와 같은 자리에

   ```python
   def deck_message(request_text: str) -> str:
       request = deck.request.parse_deck_request(request_text)
       draft = deck.builder.DeckBuilder(repository).build(request)
       validation = deck.validator.DeckValidator().validate(draft)
       return "\n".join([render_request(request), render_draft(draft),
                         render_validation(validation)])
   ```

   이 함수는 **discord 를 모른다.** 그래서 테스트가 Discord 없이 돈다.

2. **핸들러는 받아서 넘기기만 한다.**

   ```python
   @tree.command(name="deck")
   async def deck_cmd(interaction, request: str) -> None:
       await interaction.response.defer()
       text = await asyncio.to_thread(deck_message, request)
       await interaction.followup.send(text)
   ```

3. 🔴 **`defer()` 가 필수다.** Discord 는 첫 응답을 **3초** 안에 요구하고,
   덱 구축은 카드 14,127장 리포지토리 빌드를 요구해 **초 단위**가 걸린다
   (이 환경 측정: 세션 예열에 4~5초). `defer()` 없이는 상호작용이
   만료된다.

4. 🔴 **무거운 작업을 이벤트 루프 밖으로 보낸다.** `asyncio.to_thread`
   없이 동기 호출하면 그 시간 동안 **봇 전체가 멈춘다** (`/ping` 도
   응답하지 않는다).

5. 🔴 **리포지토리를 한 번만 만든다.** 명령마다 `CardRepository.build()`
   를 부르면 매번 수 초가 든다. `on_ready` 에서 한 번 만들어 들고 있는
   것이 맞다.

6. **출력 길이**: Discord 메시지는 2,000자 상한이다. Phase 4-B 의
   `render_draft` 는 덱 40장이면 그보다 길다 — 잘라 보내거나 파일 첨부로
   보내야 한다. 이것은 설계 결정이고 다음 단계에서 정한다.

Phase 4-C 가 확인한 실제 듀얼의 제약(파괴 실행 계층 없음)은 이번 범위
밖이고, `/deck` 연결과도 무관하다 — 덱 구축은 엔진 실행을 쓰지 않는다.

🔴 다음 Phase 는 자동으로 시작하지 않는다.
