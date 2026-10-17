# Phase 6-T — 선공 패 기반 실제 Duel 실행 및 콤보 탐색 기반

작업 브랜치: `claude/pensive-goodall-te1egy`
시작 HEAD: `67bb9aa` (Phase 6-S 마지막 commit)
새 생산 파일: `deck/recipe.py` · `deck/opening.py`
바꾼 생산 파일: `deck/report.py` · `app/discord_bot.py` · `app/main.py`

> ## 🔴 §0. 먼저 — 작업 시작 시 컨테이너의 클론이 낡아 있었다
>
> §1 이 "작업 시작 전 현재 브랜치, HEAD, 작업 트리 상태를 확인한다" 고
> 적었고, 확인하니 **HEAD 가 `9246495` (3 commit · Lua 파일과 README 뿐)**
> 이었다. `engine/` · `tests/` · `docs/` · `core/` 가 **하나도 없었다** —
> Phase 1 ~ 6-S 의 작업이 이 컨테이너에 없었다.
>
> **작업이 사라진 것이 아니었다.** `git ls-remote` 로 재니 원격은 제자리였다.
>
> ```
> 67bb9aae45e76b5e089022e4218f02071a091cfe  refs/heads/claude/pensive-goodall-te1egy
> 9246495afaa36a4d8e4581e2afd04a382fddb47a  refs/heads/main
> ```
>
> 낡은 것은 이 컨테이너의 `origin/claude/pensive-goodall-te1egy` 추적
> ref 였다. 🔴 **덮어쓰지 않고 복구했다** (§1 "사용자의 기존 변경 사항을
> 임의로 덮어쓰지 않는다"):
>
> 1. `git fetch origin claude/pensive-goodall-te1egy` → `9246495..67bb9aa`
> 2. `git merge-base --is-ancestor HEAD origin/…` 로 **현재 HEAD 가 원격의
>    조상임을 먼저 확인** (잃을 commit 이 없다는 증거)
> 3. `git merge --ff-only` — rebase 도 force 도 reset 도 쓰지 않았다
> 4. `python -m scripts.fetch_official_db` 로 `data/cards.cdb` 를 다시 받았다
>    (gitignore 대상이라 클론에 없다)
> 5. `pip install pytest pytest-randomly`, 그리고 뒤에 `requirements-bot.txt`
>
> 복구 확인: 6-R 의 45개 + 6-S 의 39개 = **84 passed**.

---

## 1. 기존 `/combo` 와 `ComboPlanner` 구조

### 1-1. 호출 사슬 (실측)

```
Discord /combo  (app/discord_bot.py:combo_command)
    ↓  hand · board · deck   ← 🔴 세 입력 모두 **문자열**
SearchService.combo_texts
    ↓
combo_messages              ← discord 를 모른다. 메시지 목록을 돌려준다
    ├ app.main._parse_card_ids   이름 또는 ID → 카드 ID (못 찾은 토큰은 **적는다**)
    ├ deck.request.parse_deck_request   deck: 를 **자연어 요청**으로 읽는다
    ├ deck.builder.DeckBuilder.build    → DeckDraft (**초안**)
    └ deck.planner.ComboPlanner.plan(FixedHand, board=…, draft=…)
         ↓
       ComboPlan (PlanStep 들 · stopped_reason · unsupported · manual_checks)
    ↓
combo_verdict → ComboVerdict
    ↓
paginate → 메시지 여러 개
```

### 1-2. 🔴 `ComboPlanner` 는 엔진을 **부르지 않는다** (6-S 가 실측, 6-T 가 재확인)

| 측정 | 결과 |
|---|---|
| `deck/planner.py` 가 import 한 `engine` 모듈 | **`engine.effect.library` 하나** |
| `legal_actions` · `apply` · `validate` · `create` · `start` 호출 | **전부 없음** |
| `deck/` 전체에서 `Duel`·`GameState`·`PlayerAction` 의 **코드** 사용 | **0회** (산문에만) |

그리고 **그 사실이 이미 정직하게 적혀 있었다.** `ComboVerdict` 의 최고
판정이 `GROUNDED_UNEXECUTED` ("근거 있음 · 🔴 실행 검증 안 됨") 이고
docstring 이 *"`VERIFIED` 와 `PARTIALLY_VERIFIED` 가 없는 것이 의도다 —
`ComboPlanner` 는 엔진을 실행하지 않는다"* 라고 적는다.

🔴 **6-T 는 그 판정을 바꾸지 않았다.** 그것은 정적 계획에 대해 옳다. 바꾼
것은 **그 판정이 무엇에 대한 것인지 이름으로 적은 것**이다 (§14).

---

## 2. 덱 · 패 입력 계약 조사 결과

### 2-1. 실측 — `/combo` 의 세 입력

| 입력 | 지금 무엇인가 | 실제 덱인가 |
|---|---|---|
| `hand` | 이름 또는 ID 를 쉼표로 (`_parse_card_ids`) | — |
| `board` | 같은 모양. 이미 필드·묘지에 있는 카드 | — |
| `deck` | 🔴 **자연어 요청** → `parse_deck_request` → `DeckBuilder` 초안 | **아니다** |

§5 가 못 박은 그대로다 — *"현재 Discord의 deck 입력이 자연어 요청이고 실제
확정된 덱 레시피를 의미하지 않는다면 그 값을 곧바로 실제 덱으로 취급하지
않는다."*

### 2-2. 🔴 사용자 승인을 받고 고른 방식

§5 가 "공유 명령어 계약을 크게 변경해야 한다면 먼저 사용자 승인을 요청한다"
고 적었으므로 **물었고 승인을 받았다.**

| 물음 | 승인된 답 |
|---|---|
| 실제 레시피를 어떻게 넣을까 | **`recipe:` 선택 파라미터 추가** |
| 레시피 없이 패만 들어오면 | **정적 계획 + 부족한 입력 명시** |

고르지 않은 대안과 이유:

| 대안 | 이유 |
|---|---|
| `deck:` 를 레시피로도 해석 | 🔴 입력 모양을 **추측**하게 되어 §3-6 과 충돌한다 |
| Discord 를 건드리지 않는다 | §21 수준 3 (Discord 실제 실행 출력) 이 미달성이 된다 |

**하위 호환**: `recipe` 는 **마지막 선택 인자**다. 주지 않으면 기존 동작이
한 글자도 바뀌지 않는다 (`test_f03` · `test_f04` · Discord 회귀 61개).

### 2-3. 🔴 새 모델을 만들지 않았다

레시피는 **기존 `DeckDraft`** 로 담는다 — 그것은 이미 `(card_id, copies)` 와
메인·엑스트라 구분을 들고 있다. 새 타입을 만들면 검증기(`DeckValidator`)와
보고서(`deck/report.py`)를 둘 다 고쳐야 한다.

그래서 `DeckValidator` 를 **그대로** 재사용한다 — §6 의 열 항목 중 다섯을
그것이 이미 본다 (§3 의 표).

🔴 **역할은 추측하지 않는다.** `CardRole` 은 "이 저장소가 왜 이 카드를
골랐는가" 를 적는 칸이고, 레시피는 사용자가 고른 것이므로 고를 이유가
**없다**. 엑스트라 덱 여부만 카드 데이터로 판정하고
(`RoleEvidence.PRINTED_CARD_TYPE`), 나머지는 `UNCLASSIFIED` · 근거 없음이다.

### 2-4. 받는 두 모양 (`deck/recipe.py`)

**① YDK** — EDOPro · YGOPRODeck 이 내보내는 모양 그대로. `#main` / `#extra`
구역, 한 줄에 패스코드 하나, 같은 패스코드가 여러 줄이면 그 수가 매수다.
사이드(`!side` · `#!side` · `#side`)는 **읽고 버리고 버린 사실을 적는다**.

**② 목록** — `<이름 또는 ID> [x매수]` 를 쉼표·줄바꿈으로. 구역은
`엑스트라:` / `extra:` 로 바꾼다.

🔴 **모양을 추측하지 않는다** — 구역 표시가 있으면 ①, 없으면 ②다.
🔴 **해석하지 못한 토큰을 버리지 않는다** (`RecipeParse.unresolved`).

CLI 는 `.ydk` **파일 경로**도 받는다 (`--recipe <경로>.ydk`).

---

## 3. `GameState.create` 및 초기 상태 구성 방식

### 3-1. 왜 `Duel.start` 를 쓰지 않았는가

`Duel.start` 는 **섞고 5장씩 뽑는다.** 6-T 의 패는 사용자가 **지정한**
것이므로 뽑을 수 없다. 그래서

```
GameState.create(repository, decks=(남은 메인 덱, 상대 덱 자리),
                 turn_player=0, seed=0, shuffle=False)
  → create_instance(card_id, owner=0, zone=Zone.HAND)   패 5장
  → create_instance(card_id, owner=0, zone=Zone.EXTRA)  엑스트라
  → state.turn.set_phase(Phase.DRAW)
Duel(state=…, priority=idle(turn_player=0, phase=DRAW),
     step=TurnStep.OPEN,        🔴 선공 첫 턴은 뽑지 않는다 (룰북)
     first_player=0, **duel_components(journal=EventJournal()))
```

🔴 **그래서 "실제 셔플로 이 패를 뽑았다" 고 말하지 않는다** — 이 패는 분석
조건이다 (§8). 그 사실이 `OpeningSetup.unknowns` 에 적힌다.

### 3-2. §6 의 열 항목 — 누가 보는가

| § | 항목 | 어디서 |
|---|---|---|
| 1 | 메인 덱 카드 수 | `DeckValidator._check_main_size` (룰북 데이터) |
| 2 | 엑스트라 덱 카드 수 | `DeckValidator._check_extra_size` (룰북 데이터) |
| 3 | 카드 인스턴스 중복 | `DeckValidator._check_slot_sanity` + `test_d01` |
| 4 | 각 카드의 등록 매수 | `DeckValidator._check_copy_limit` → 🔴 **검증 불가** |
| 5 | 시작 패가 메인 덱에 있는가 | **`check_hand_against_recipe`** (6-T 가 더함) |
| 6 | 패가 보유 매수를 넘지 않는가 | **`check_hand_against_recipe`** |
| 7 | 엑스트라 덱 카드가 패에 없는가 | **`check_hand_against_recipe`** (카드 데이터로) |
| 8 | CDB 에서 정의를 읽을 수 있는가 | **`check_hand_against_recipe`** |
| 9 | 금지·제한 데이터가 있는가 | `DeckValidator._check_limit_regulation` → 🔴 **없다** |
| 10 | 판정 불가를 명시하는가 | `OpeningSetup.unverifiable` → `unknowns` |

🔴 **4 와 9 는 검증 불가다.** 룰북 데이터에 동일명 3장 제한이 없고, 저장소에
금지·제한 데이터가 아예 없다. **그래서 "덱 합법성을 완전히 검증했다" 고
적지 않는다** (§6). 이번 단계에서 금지·제한 데이터를 새로 만들지 않았다.

### 3-3. 🔴 위반이 있으면 상태를 만들지 않는다

`build_opening` 은 위반이 하나라도 있으면 `duel` 을 **만들지 않고**
`blockers` 에 이유를 적는다. 틀린 덱으로 돌려서 나온 결과는 검증이 아니다
(`test_a05` ~ `test_a09`, 변이 M5 가 이 자리를 지킨다).

---

## 4. 선공 첫 턴 규칙 검증

### 4-1. 🔴 페이즈를 **걸어서** 간다 (실측)

§7 이 "필요한 게임 단계를 건너뛰어 규칙 위반 상태를 만들지 않는다" 고
적었다. 그래서 드로우 페이즈에서 시작해 `legal_actions` 가 내놓는
`END_PHASE` 를 **실제로 적용**한다.

```
[DRAW]    후보 ['END_PHASE']  → apply → "STANDBY 로 넘어갔습니다."
[STANDBY] 후보 ['END_PHASE']  → apply → "MAIN1 로 넘어갔습니다."
[MAIN1]   후보 8건 — ACTIVATE_EFFECT · NORMAL_SUMMON · SET_MONSTER ·
                      SET_SPELL_TRAP · END_PHASE
```

`test_b03` 이 그 두 걸음을 다시 걸어서 센다.

### 4-2. 실측된 초기 상태

| 항목 | 값 | 근거 |
|---|---|---|
| 턴 | **1** | `state.turn.turn_number` |
| 페이즈 | **MAIN1** | `state.turn.phase` |
| 선공 | **P0** | `turn_player` · `first_player` |
| 드로우 | **없음** | `step=TurnStep.OPEN` · 패가 입력 그대로 5장 |
| 패 | 5장 (입력 그대로) | `Counter(hand) == Counter(입력)` |
| 남은 메인 덱 | **35장** (40 − 5) | `len(zone(DECK))` |
| 내 필드·묘지·제외 | **비어 있음** | `test_b05` |
| 상대 패·필드·묘지 | **비어 있음** | `test_b04` |
| 일반 소환권 | 미사용 | 통상 소환 후보가 나온다 |
| 사용한 효과 | 없음 | `rule_uses` 비어 있음 |
| 체인 · 우선권 | 비어 있음 · 닫힘 | `chain.is_empty` · `not priority.is_open` |

### 4-3. 🔴 상대의 비공개 정보를 지어내지 않았다

상대 **덱 자리 40장**만 두고 패는 **비웠다**. 그 사실이 `unknowns` 에 적힌다:

> *"상대의 덱·패·필드는 입력에 없습니다 — 상대 덱 자리 40장만 두고 패는
> 비워 두었습니다 (상대의 방해가 없는 상황입니다)."*

---

## 5. `CardInstance` 및 덱 수량 처리

### 5-1. 🔴 §15 를 전수로 센다 (`test_d01`)

| 측정 | 결과 |
|---|---|
| 초기 판의 카드별 매수 == 레시피 | **일치** |
| 총 장수 | 40 → **40** (보존) |
| 카드별 매수 보존 | **전부 일치** (차이 0) |
| 인스턴스 중복 | **0** |
| 실행 중 사라진 인스턴스 | **0** |
| 실행 중 새로 생긴 인스턴스 | **0** |

### 5-2. 시작 패를 덱에서 **정확히** 뺀다

```
레시피  {POT:3, GIFT:3, HONEST:3, FINE:3, LUSTER:28}  = 40
패      [POT, HONEST, GIFT, LUSTER, LUSTER]            = 5
남은 덱 {POT:2, GIFT:2, HONEST:2, FINE:3, LUSTER:26}   = 35
```

### 5-3. 🔴 덱 순서 — "모른다" 와 "재현되지 않는다" 를 가른다

사용자가 레시피와 패만 주었으므로 **섞인 순서는 입력에 없다.** 그래서

* `shuffle=False` — 섞으면 "모른다" 는 사실이 숨는다
* 남은 덱을 **패스코드 순으로 정렬** — 같은 입력이 같은 결과를 준다
* 그 배열이 실제 셔플이 아니라는 사실을 `unknowns` 가 적는다

🔴 **그리고 그것이 결과를 바꾼다는 것을 실측으로 보았다.** 표본 ①에서
욕망의 항아리가 뽑은 2장이 **욕망의 선물 2장**이었고 (덱 맨 위가
`[5915629, 5915629, …]`), 그래서 세트가 1장이 아니라 **3장** 되었다. 다른
배열이면 다른 결과다 — 그것이 `unknowns` 가 적는 바로 그 사실이다.

`test_d03` 이 재현성(같은 입력 → 같은 배열)과 선언(정렬)과 고지(`unknowns`)
를 함께 센다. 변이 M7 (섞는다) · M8 (정렬하지 않는다) 이 이 자리를 지킨다.

---

## 6. 채택한 최소 실행 연결 방식

### 6-1. 새 파일 둘, 그리고 **규칙은 한 줄도 없다**

| 파일 | 하는 일 |
|---|---|
| `deck/recipe.py` | 레시피 문자열 → `DeckDraft` (+ 해석 못한 토큰) |
| `deck/opening.py` | §6 패 검사 · §7 상태 구성 · §9 실행 · §10 기록 |

🔴 `deck/opening.py` 에 **판정기도 실행기도 없다** — 클래스가
`OpeningSetup` · `ExecutedStep` · `OpeningRun` **셋뿐**이고 전부 입력과
기록이다. 그리고 `legal_actions` · `apply` · `advance` · `validate` 를
**부른다** (`test_h01` 이 AST 로 센다).

### 6-2. 왜 `deck/` 인가

`engine/` 은 덱과 레시피를 몰라야 한다. `deck/` → `engine` 방향은 이미
열려 있다 (`deck/planner.py` 가 `engine.effect.library` 를 읽는다).

### 6-3. 🔴 탐색 깊이는 **이 단계의 선언**이고 규칙이 아니다

`MAX_EXECUTED_ACTIONS = 8` · `MAX_CHAIN_PASSES = 8`. 상수의 설명이 그것을
적고 `test_h02` 가 그 문장을 센다 — 적지 않으면 다음에 읽는 사람이 유희왕의
규칙이라고 믿는다.

### 6-4. 🔴 고른 행동을 최선이라고 말하지 않는다

`first_meaningful` — 발동 → 통상 소환 → 마법·함정 세트 → 몬스터 세트 → …
같은 종류가 여럿이면 **첫 번째**다. 이름과 설명이 "검증용" 과 "최선이
아니다" 를 적고 `test_e05` 가 그 문장을 센다.

🔴 그리고 **`END_PHASE` 는 고르지 않는다** — 고르면 전개가 끝나 버린다.
흐름만 남으면 `None` 을 돌려주고 호출자가 멈춘다. 변이 M11 이 이 자리를
지킨다.

---

## 7. 변경한 파일 및 함수

| 파일 | 변경 |
|---|---|
| `deck/recipe.py` | **새 파일** — `parse_recipe` · `RecipeParse` · `looks_like_ydk` |
| `deck/opening.py` | **새 파일** — `OpeningSetup` · `ExecutedStep` · `OpeningRun` · `build_opening` · `check_hand_against_recipe` · `execute_opening` · `first_meaningful` · `opening_hand_size` |
| `deck/report.py` | `render_opening_setup` · `render_opening_run` · `render_opening_board` 추가 |
| `app/discord_bot.py` | `_executed_lines` 추가 · `combo_messages`/`combo_texts`/`combo_command` 에 `recipe` · `COMBO_DESCRIPTION` · 판정 줄을 정적 계획 절로 이동 |
| `app/main.py` | `cmd_combo` 에 `--recipe` (`.ydk` 경로 포함) · `_print_opening` 추가 |

바꾸지 않은 것: `engine/` **전체** · `deck/planner.py` · `deck/model.py` ·
`deck/validator.py` · `deck/builder.py` · `deck/hand.py` · `ComboVerdict`.

### 움직인 기존 핀 다섯 (삭제 0 · skip 0 · 약화 0 · threshold 완화 0)

**이 Phase 의 변경 때문에 움직인 셋** — 전부 `recipe` 파라미터와 출력 구조:

| 테스트 | 변경 | 왜 |
|---|---|---|
| `test_discord_bot.py::test_44` | 인자 3 → **4**, 이름도 맞췄다 | `recipe` 가 붙었다. 🔴 **마지막 선택 인자**라 기존 호출은 그대로다 |
| `test_discord_bot.py::test_51` | `**판정:` → `**정적 계획의 판정:` + 자리 검사 추가 | 실행 절이 위에 생겨 같은 줄이 "방금 실행한 결과의 판정" 으로 읽혔다 (§13) |
| `test_discord_bot.py::test_58` | 가짜 `combo_texts` 에 `recipe_text` · 받은 튜플 4칸 | 서명을 안 맞추면 그 시험이 `TypeError` 를 본다 |

세 핀 모두 **틀린 가정을 갖고 있던 것이 아니다** — 그때는 실제로 그랬다.

### 🔴 이 Phase 와 **무관하게** 움직인 둘 — 상류 데이터 드리프트

| 테스트 | 변경 |
|---|---|
| `tests/engine/test_archetype_compiler.py::test_a_…` | 카드군 수 615 → **616** |
| `tests/engine/test_archetype_condition.py::test_c_…` | 같음 |

`data/constants/archetype_setcode_constants.lua` 는 **상류에서 계속 갱신되고
`.gitignore` 대상**이다. §0 의 환경 복구에서 `fetch_official_db` 로 다시
받았고, 그 사이 상류에 카드군 하나가 늘었다 (실측 **616**).

🔴 **6-T 는 `engine/` 을 한 줄도 바꾸지 않았다** (`git status` 가 그 증거 —
변경된 생산 파일은 `deck/` 와 `app/` 뿐이다). 그래서 이 이동은 데이터
드리프트이고, **그 핀이 바로 그것을 드러내도록 설계되어 있다는 증거**다.
늘어난 카드군의 이름은 가를 수 없다 — 그 파일이 저장소에 없으므로 이전
판과 비교할 대상이 없다. 그 사실까지 핀의 설명에 적었다.

### 🔴 환경 문제였던 실패 하나 (고치지 않았다 — 설치했다)

`tests/test_discord_bot.py::test_08_the_token_value_never_reaches_the_log`
이 처음 실패했다. 원인은 **`discord.py` 가 이 컨테이너에 없었다** —
`bot.main()` 이 2 를 돌려주었다 ("discord.py 가 없습니다"). 세션 시작 훅은
`requirements-dev.txt` 만 설치하고 `requirements-bot.txt` 는 설치하지
않는다. 🔴 **토큰이 샌 것이 아니다** — 설치한 뒤 그대로 통과한다. 이것도
6-T 의 변경과 무관하다.

---

## 8. 실제 `legal_actions` 후보

표본 넷의 **MAIN1 첫 후보** (실측):

| 표본 | 레시피 | 패 | MAIN1 첫 후보 |
|---|---|---|---|
| ① | 항아리3·선물3·어니스트3·벌금3·드래곤28 | 항아리·어니스트·선물·드래곤·드래곤 | **8** |
| ② | 항아리3·드래곤37 | 항아리·항아리·드래곤×3 | **11** |
| ③ | 선물3·벌금3·드래곤34 | 선물·벌금·드래곤×3 | **9** |
| ④ | 탈출3·항아리3·드래곤34 | 탈출·항아리·드래곤×3 | **10** |
| **합** | | | **38** |

종류: `ACTIVATE_EFFECT` · `NORMAL_SUMMON` · `SET_MONSTER` ·
`SET_SPELL_TRAP` · `END_PHASE`.

---

## 9. `ActionValidator` 및 `Duel.apply` 결과

### 9-1. 걸음마다 판정 코드를 **기존 판정기에서** 받는다

| 행동 종류 | 누가 답하는가 |
|---|---|
| `ACTIVATE_EFFECT` | `Duel._activation_gate` — 관문 셋 (6-S §4) |
| 판 행동 | `ActionValidator` |
| `PASS` · `END_PHASE` | 🔴 **흐름 계층** — 검증기가 답하지 않는다 → `"FLOW"` |

실측: 표본 넷의 걸음 **14개** 전부 판정 `OK`, `apply` 접수 **14**,
해결 **14**, 상태 변경 **14**.

### 9-2. 🔴 거절된 걸음은 거절로 적힌다 (`test_e00`)

변이 시험이 먼저 이 구멍을 찾았다 — `accepted`·`resolved`·`state_changed`
를 상수로 바꾼 변이 셋이 **살아남았다.** 이 경로의 모든 걸음이 수락되기
때문이었다. 그래서 **후보 목록에 없는 행동**을 고르는 시험을 더했다.

```
accepted=False · resolved=False · state_changed=False
state_hash 변화 없음
stopped_reason: "행동이 거절되었습니다: …"
run.executed=0 · run.resolved=0 · run.state_changes=0
```

### 9-3. 🔴 행동을 추측해서 실행하지 않는다 (`test_c06`)

걸음마다 "고른 행동이 **그 시점의 후보 목록에 있었는가**" 를 확인한다
(`assert action in legal.allowed`).

---

## 10. 체인 · 우선권 처리 결과

발동 → 응답 창 → **기존 PASS 절차**로 양쪽 패스 → 해결. 실측 (표본 ①의
첫 걸음):

```
apply   accepted=True  code=OK  "…를 체인 1 로 발동했습니다. 상대의 응답을 기다립니다."
패스 ×2 accepted=True  code=OK  "체인1 P0 55144522:e[0] 를 해결했습니다."
뒤      chain.links=0  chain.resolved_count=0  priority.is_open=False
```

🔴 **해결 여부를 `accepted` 로 읽지 않는다** (6-R) — 적법한 패스는 링크가
불발되어도 수락이고, 불발은 `code` 가 들고 온다. `_settle_chain` 이
`code is ValidationCode.OK` 로 판단한다. 변이 M13 이 이 자리를 지킨다.

**모든 걸음에서 잔류 링크 0** (`test_g04`).

---

## 11. 실제 `GameState` 변경

표본 ①의 최종 판 (실측):

| 자리 | 장수 | 내용 |
|---|---|---|
| 몬스터 존 | 1 | 사파이어 드래곤 |
| 마법·함정 존 | 3 | 욕망의 선물 ×3 (세트) |
| 패 | 2 | 어니스트 · 사파이어 드래곤 |
| 묘지 | 1 | 욕망의 항아리 |
| 제외 · 엑스트라 | 0 | — |
| 남은 덱 | **33** | 35 − 2 (드로우) |

드로우가 **실제로** 일어났다: 덱 35 → 33, 패 5 → (−1 발동, +2 드로우) 6 →
(−1 소환, −3 세트) 2 (`test_c02`).

---

## 12. `EventJournal` 기록

```
0 ACTION activate_effect   ← 발동 선언 (체인 등록)
1 EFFECT 55144522:e[0]     ← 🔴 **적용된 효과** (applied · deltas 있음)
2 ACTION activate_effect   ← 놓인 마법이 묘지로
3 ACTION normal_summon
4 ACTION set_spell_trap
5 ACTION set_spell_trap
6 ACTION set_spell_trap
```

🔴 **적용된 것만 `EFFECT` 로 남는다.** 걸음들이 적은 `effect_events` 의
합이 기록의 `EFFECT` 사건 목록과 **정확히 같다** (`test_e03`) — 양쪽이 같은
사실을 센다. 세트 셋은 효과가 아니므로 `EFFECT` 가 없다.

---

## 13. 실행 후 후속 행동 후보

걸음마다 **그 뒤의 후보 수**를 기록한다 (`ExecutedStep.next_candidates`):

```
1. activate_effect (항아리) → 8건
2. normal_summon          → 4건
3. set_spell_trap         → 3건
4. set_spell_trap         → 2건
5. set_spell_trap         → 1건  ← END_PHASE 만 남았다
```

🔴 그리고 **일반 소환권이 다시 쓰이지 않는다** — 실행 뒤 통상 소환 후보가
**0건**이다 (`test_c05`).

멈춘 이유가 **세 가지로 갈린다** (`test_e04`):

| 이유 | 뜻 |
|---|---|
| "판을 바꿀 후보가 더 없습니다 … 막힌 것이 아닙니다" | 전개가 끝났다 |
| "이 단계가 선언한 상한 N걸음에 닿았습니다 … 전개가 끝났다는 뜻이 아닙니다" | 6-U 가 넓힌다 |
| "행동이 거절되었습니다: …" | 엔진이 막았다 |

---

## 14. Discord `/combo` 출력 전후 비교

### 14-1. 레시피를 **주지 않았을 때** — 기존 경험 유지 + 부족 입력 명시

| | 전 (6-S) | 후 (6-T) |
|---|---|---|
| 맨 위 판정 줄 | `**판정: 근거 있음 · 🔴 실행 검증 안 됨**` | (옮겨짐 ↓) |
| 실제 실행 절 | 없음 | 🔴 **"하지 않았습니다 — 실제 덱 레시피가 없습니다"** + 왜 `deck:` 으로는 안 되는지 + `recipe:` 사용법 |
| 정적 계획 | 바로 나옴 | `**[아래는 실행하지 않은 정적 계획입니다]**` 머리 + `**정적 계획의 판정: …**` |
| 정적 걸음 | 그대로 | **그대로** |

### 14-2. 레시피를 **주었을 때** — 새 절

```
**[실제 엔진 실행]**
  레시피 모양: 목록 (이름 또는 ID · x매수)
✅ **엔진이 실제로 5걸음 실행**했습니다 (해결 5 · 상태 변경 5). 아래는 실측 기록입니다.

선공 상태 구성
  턴 1 · MAIN1 · 선공 P0
  시작 패 5장 · 남은 메인 덱 35장 · 엑스트라 0장
  선공 첫 턴 드로우 없음 (룰북) · 일반 소환권 미사용 · 사용한 효과 없음
  검증 통과 10건
  ⚠️ 검증 불가 2건 — **문제 없음이 아닙니다**
  🔴 알 수 없는 것 (실행 결과를 읽을 때 함께 보아야 합니다)  …5건

🔴 실제 엔진 실행 (검증된 걸음)
  ✔ 1. P0 activate_effect · 욕망의 항아리 [55144522]
      판정 OK · 수락 예 · 결과 OK · 상태 변경 있음
      효과 55144522:e[0] / 적용된 효과 기록: 55144522:e[0]
      이유: 체인1 P0 55144522:e[0] 를 해결했습니다.
      이 뒤의 행동 후보 8건
  …
  실행 5걸음 · 해결 5걸음 · 상태 변경 5걸음
  멈춘 이유: 판을 바꿀 후보가 더 없습니다 … 막힌 것이 아닙니다.

현재까지의 결과 (실제 GameState)
  몬스터 존 / 마법·함정 존 / 패 / 묘지 / 제외 / 엑스트라 / 남은 덱
  🔴 집의 강도 평가는 미구현입니다 (Phase 6-V) …

**[아래는 실행하지 않은 정적 계획입니다]**
🔴 카드 데이터를 읽어 만든 계획이고 **엔진으로 돌린 것이 아닙니다.**
**정적 계획의 판정: 근거 있음 · 🔴 실행 검증 안 됨**
```

### 14-3. 🔴 넷을 혼동시키지 않는다 (§13)

| | 어디에 |
|---|---|
| ① 실제 `Duel` 에서 실행한 행동 | `🔴 실제 엔진 실행 (검증된 걸음)` · ✔ 표시 · 판정 코드 · 기록 |
| ② 엔진이 후보로만 생성한 행동 | `이 뒤의 행동 후보 N건` (수만) |
| ③ `ComboPlanner` 의 정적 추론 | `**[아래는 실행하지 않은 정적 계획입니다]**` 아래 |
| ④ 아직 지원하지 않는 행동 | `**[엔진이 지원하지 않아 계획에 넣지 않은 절차]**` · `blockers` |

순서가 **정해져 있다**: 실행 절 → 정적 계획 절 (`test_f02` 가 index 비교로
센다). 변이 M19 · M20 이 이 자리를 지킨다.

### 14-4. 메시지 길이

기존 `paginate` 를 그대로 쓴다. 실측: 레시피 없이 **2개**, 레시피와 함께
**3개**, 최대 길이 **1,985자** (상한 미만).

### 14-5. CLI 도 같은 길

```
$ python3 -m app.main combo "55144522, 5915629, 11091375, 11091375, 11091375" \
      --recipe /path/to/deck.ydk
```

`.ydk` 파일 경로를 그대로 받는다.

---

## 15. 미지원 행동 및 정보 부족 처리

### 15-1. 🔴 **이 Phase 의 가장 중요한 실측 — 효과 몬스터는 통상 소환할 수 없다**

```
어니스트      ['MONSTER', 'EFFECT'] -> UNKNOWN  RULE_NOT_IMPLEMENTED
                                     missing=summoning-condition (카드 텍스트의 소환 제약)
사파이어 드래곤 ['MONSTER', 'NORMAL'] -> VALID    OK
욕망의 항아리   ['SPELL']             -> INVALID  SOURCE_WRONG_CARD_TYPE
```

🔴 **그리고 그것이 옳다.** 효과 몬스터는 카드 텍스트에 소환 제약이 있을 수
있고 ("이 카드는 통상 소환할 수 없다"), 엔진은 그 문장을 읽지 못한다. 읽지
못하는 것을 `VALID` 로 올리면 규칙이 금지한 소환을 허가하게 된다 —
`UNKNOWN` 이 정확한 답이다 (ADR-006 · §3-8).

**결과**: 선공 전개의 폭이 **통상 몬스터로 묶인다.** 이것이 §19 의 BLOCKER
이고 `test_g01` 이 재어서 남긴다 (풀리면 그 단언이 깨진다).

처음 이 시험을 "어니스트를 통상 소환한 뒤 효과를 발동한다" 로 적었고
**틀렸다** — 재어서 정정했다.

### 15-2. 정보가 부족한 자리를 **그 지점에서** 멈춘다

| 부족한 것 | 어떻게 |
|---|---|
| 레시피 없음 | `duel` 을 만들지 않고 `recipe:` 사용법을 적는다 |
| 레시피에서 카드를 못 읽음 | 실행하지 않고 해석 못한 토콘을 적는다 |
| 패가 덱에 없음 · 매수 초과 · 엑스트라가 패에 | `blockers` 에 적고 실행하지 않는다 |
| 덱 순서 · 금지 제한 · 상대 상태 | `unknowns` 에 적는다 (실행은 한다) |

🔴 그리고 **"전체 전개가 불가능하다" 고 주장하지 않는다** (§15 마지막 줄).
멈춘 이유가 그것을 명시한다.

---

## 16. 기존 어니스트 · 6-O · 6-P · 6-Q · 6-R · 6-S 회귀

| § | 기능 | Phase | 결과 |
|---|---|---|---|
| 14-L | 어니스트 효과 실행 | 6-L | 🟢 유지 — 🔴 **단 필드에 있을 때만** (§15-1). `test_g01b` 가 그 조건을 명시한다 |
| — | 강제 탈출 장치 | 6-O | 🟢 표본 ④에서 세트·발동까지 (3걸음 실행) |
| 14-M | 벌금의 패 2장 | 6-P | 🟢 조합이 **C(패−1, 2)** 개 · 각 2장 · 전부 다름 · 해결 `OK` |
| 14-N | 세트된 일반 함정 | 6-Q | 🟢 세트한 턴 후보 0 → 다음 내 턴 후보 1 → 해결 · 상대 패 +2 |
| 14-O | 체인 종료 | 6-R | 🟢 모든 걸음에서 잔류 링크 **0** |
| 14-P | 후보·판정·실행 정합성 | 6-S | 🟢 이 경로의 후보 전부가 사본에서 `apply` 접수 (거절 0) |

🔴 **`test_g02` 의 기대값을 상수로 적었다가 틀렸다.** 3 으로 적었는데 실측은
10 이었다 — 턴을 넘기는 동안 드로우로 패가 늘었기 때문이다. 수를 세는 쪽이
아니라 **세는 방법**(`math.comb(len(pool), 2)`)을 못 박도록 고쳤다.

---

## 17. 타깃 · 통합 · 관련 회귀 테스트 결과

→ 부록의 실행 기록.

### 변이 시험 — 내 생산 코드에 변이를 넣고 내 시험이 잡는지

변이 **20개**를 `deck/opening.py` · `deck/recipe.py` ·
`app/discord_bot.py` 에 하나씩 넣었다.

**1차: 16/20.** 살아남은 넷과 그 이유:

| 변이 | 왜 살아남았나 | 더한 시험 |
|---|---|---|
| M8 덱 순서를 정렬하지 않는다 | 레시피 파서가 이미 칸을 정렬해 만든다 → 이 입력에선 동등 변이 | `test_e00b` — 칸을 **거꾸로 뒤집은** 초안으로 센다 (`DeckBuilder` 초안은 정렬되어 있지 않다) |
| M12 거절된 걸음도 수락으로 | 이 경로의 모든 걸음이 수락된다 | `test_e00` — **후보에 없는 행동**을 고르는 선택 함수 |
| M13 불발을 해결로 | 같음 | 같음 |
| M14 상태 변경을 늘 있다고 | 같음 | 같음 |

**2차: 20/20.** 🔴 변이 시험이 **내 기록이 정직한지**를 내 시험보다 먼저
물었고, 그 자리가 실제로 비어 있었다.

---

## 18. 실제 실행 가능성 전후 비교 (§16 의 열세 지표)

**"전" 은 HEAD `67bb9aa` 다** — 거기에는 이 경로가 **없다.** 레시피를 받는
길도, 선공 상태를 만드는 길도, 엔진으로 돌리는 길도 없었다. 그래서 1 ~ 9 의
"전" 은 모두 **0** 이고, 그것은 이 Phase 가 길을 **새로** 만들었다는 뜻이다.

측정 범위: **선공 패 5장 × 덱 레시피 40장 표본 6개** (상대 방해 없음).
🔴 한 번의 성공을 전체 카드에 일반화하지 않는다 — 표본에 쓴 카드는
등재된 실행 가능 14장 중 **5종**이다.

| § | 지표 | 전 | 후 |
|---|---|---|---|
| 1 | 실제 `GameState` 구성 성공 | **0** | **4 / 4** (거절 2건은 의도대로 거절) |
| 2 | 덱·패 정합성 검증 사례 | **0** | **6** (통과 4 · 거절 2) |
| 3 | 실제 `legal_actions` 후보 | **0** | **38** (MAIN1 첫 후보 합) |
| 4 | 판정을 통과한 행동 | **0** | **14** |
| 5 | `Duel.apply` 가 접수한 행동 | **0** | **14** |
| 6 | 실제 해결한 행동 | **0** | **14** |
| 7 | `GameState` 변경 검증 사례 | **0** | **14** |
| 8 | 후속 `legal_actions` 생성 성공 | **0** | **4 / 4** |
| 9 | 🔴 **연속 실행에 성공한 최대 행동 수** | **0** | **5** |
| 10 | Discord 에서 실제 실행 결과 출력 | **없음** | **있음** (레시피 없으면 부족 입력 명시) |
| 11 | 🔴 정적 추론을 실행 성공으로 오인한 사례 | — | **0** |
| 12 | 기존 효과 실행 회귀 | — | **6 / 6 유지** (§16) |
| 13 | 남아 있는 구조적 BLOCKER | — | §19 |

### 🔴 실행 가능한 카드 효과 수의 증가 — **0건**

이 Phase 는 새 효과도 새 조작도 등재하지 않았다. 등재된 실행 가능 카드는
**14장** 그대로다. 늘어난 것은 **그 14장을 실제 선공 판에서 돌릴 수 있는
길**이다.

🔴 **테스트 45개의 증가를 듀얼 능력 증가로 읽지 않는다.** 그리고 **후보
수(38)와 실행한 행동 수(14)를 합산하지 않는다** (§16).

---

## 19. 남아 있는 구조적 BLOCKER

### 19-1. 🔴 **효과 몬스터를 통상 소환할 수 없다** (새로 이름 붙임)

`missing=summoning-condition (카드 텍스트의 소환 제약)`. 선공 전개의 폭이
통상 몬스터로 묶인다 — **6-U 가 다중 경로를 탐색하기 전에 알아야 하는
가장 큰 제약**이다. `test_g01` 이 재어서 남긴다.

### 19-2. 🔴 금지·제한 데이터가 없다

`DeckValidator._check_limit_regulation` 이 **검증 불가**를 돌려준다. 동일명
3장 제한도 룰북 데이터에 없다. 그래서 **덱 합법성을 완전히 검증했다고
적지 않는다**. 이번 단계에서 만들지 않았다 (§18 의 범위 밖).

### 19-3. 🔴 덱 순서를 모른다 → 드로우 분기 탐색이 없다

지금은 **하나의 선언된 배열**에서의 결과다. 모든 가능한 드로우를 대표하지
않는다 (§8 "이번 Phase에서는 드로우 분기 탐색을 완성하지 않는다").

### 19-4. 그대로 남은 것 (6-S 가 적은 것들)

| BLOCKER | 상태 |
|---|---|
| 룰북 §82 의 뒷절반 (페이즈·스텝 끝의 우선권 이양) | 그대로 — 상대 턴 함정이 실제 루프에서 닿지 않는다 |
| 관문이 막은 발동이 `withheld` 에 이유를 남기지 않는다 | 그대로 |
| STRUCTURAL-34 의 나머지 · 35 · 36 | 그대로 |
| TRIGGER 자동 발동 · 모든 특수 소환 절차 | 그대로 |
| 집의 강도 평가 | 🔴 **미구현이라고 출력에 적는다** (`test_h03`) |

---

## 20. Phase 6-U 의 최소 선행 조건

### 충족된 것

| 조건 | 근거 |
|---|---|
| 실제 선공 `GameState` 를 만들 수 있다 | §4 |
| 덱·패 정합성을 검증한다 | §3-2 · §5 |
| 후보 → 판정 → 실행 → 상태 → 후속 후보가 **돈다** | §8 ~ §13 |
| 연속 실행이 된다 (최대 5걸음) | §18-9 |
| 실행 기록이 세 사실을 따로 들고 있다 | §9 · `ExecutedStep` |
| 실행과 정적 추론이 출력에서 갈린다 | §14 |
| 거절·불발·상한·종료가 서로 다른 이유로 적힌다 | §13 |

### 🔴 6-U 를 시작하기 전에 결정해야 하는 것

1. **분기의 단위를 무엇으로 할 것인가.** 지금 `execute_opening` 은 한 경로만
   민다. 분기하려면 `Duel` 사본이 필요하고, `GameState.clone()` 과
   `duel_components(journal=False)` 로 이미 가능하다 (`test_g05` 가 그 길을
   쓴다). 다만 **기록을 어디에 둘 것인가**가 정해져 있지 않다.
2. **중복 상태를 무엇으로 판정할 것인가.** `state_hash()` 가 있지만 체인과
   우선권은 거기 들어가지 않는다 (의도) — 전개 중간 상태를 같다고 볼
   기준을 정해야 한다.
3. **§19-1 을 먼저 풀 것인가.** 효과 몬스터를 통상 소환할 수 없으면 분기의
   폭이 통상 몬스터로 묶인다. 탐색기를 먼저 만들면 좁은 공간을 넓게
   탐색하게 된다.
4. **드로우 분기** (§19-3) — 덱 순서를 모르는 채로 분기하면 경로 수가
   폭발한다. 명시적 시드나 분기 상한이 필요하다.

**평가**: 6-T 의 목표(§1-10, "이후 Phase에서 다단계 탐색을 추가할 수 있는
최소 연결 지점 확보")는 달성되었다. 🔴 다만 3번은 **순서의 결정**이고
사용자의 판단이 필요하다.

---

## 21. 완료 수준

### 수준 3 — Discord `/combo` 실제 실행 출력 **달성**

| §21 수준 3 항목 | 근거 |
|---|---|
| 실제 실행된 전개 걸음을 출력한다 | §14-2 |
| 실제 상태 변경과 결과를 표시한다 | §11 · §14-2 |
| 정적 계획과 실제 실행을 구분한다 | §14-3 (순서까지 못 박음) |
| 미지원 행동과 정보 부족을 명확하게 표시한다 | §15 |
| 기존 Discord 명령어와의 호환성을 유지한다 | §2-2 · Discord 회귀 61개 |
| 관련 회귀 테스트를 통과한다 | 부록 |

### 수준 2 — 실제 연속 행동 실행 **달성**

실제 `legal_actions` → `ActionValidator`/관문 → `Duel.apply` → `GameState`
변경 → 후속 후보. **최대 5걸음 연속**, 전부 실측.

### 수준 1 — 실제 선공 상태 구성 **달성**

§3 · §4 · §5. 인스턴스 중복 0 · 매수 보존 · 임의 카드 생성 0.

🔴 **그리고 §21 의 마지막 줄을 지킨다.**

> *"단순히 카드 효과 텍스트를 읽어 전개 과정을 출력했다면 수준 2나 수준 3을
> 달성했다고 주장하지 않는다."*

이 Phase 의 모든 걸음은 `Duel.legal_actions` 가 **내놓은 후보**를
`Duel.apply` 에 넣어 나온 결과이고, 그 결과를 `GameState` 와
`EventJournal` 로 다시 셌다. 정적 계획은 **출력에서 갈라** 두었고 "실행하지
않았다" 고 적었다.

**최적의 집을 완성하지 못했다** — 그것은 Phase 6-U · 6-V 의 일이고, 이
Phase 의 출력은 "집의 강도 평가는 미구현" 이라고 적는다.

**다음 Phase 는 자동으로 시작하지 않는다.**

---

## 부록 — 실행 기록

모든 수는 `pytest` 의 **실제 종료 코드**와 마지막 줄을 그대로 적은 것이다
(§17 "pytest의 실제 종료 코드를 확인한다").

### 0단계 — 환경 복구 (§0)

```
$ git ls-remote origin
67bb9aae45e76b5e089022e4218f02071a091cfe  refs/heads/claude/pensive-goodall-te1egy

$ git fetch origin claude/pensive-goodall-te1egy
   9246495..67bb9aa  claude/pensive-goodall-te1egy -> origin/claude/pensive-goodall-te1egy

$ git merge-base --is-ancestor HEAD origin/claude/pensive-goodall-te1egy  → 0
$ git merge --ff-only origin/claude/pensive-goodall-te1egy                → 67bb9aa

$ python3 -m scripts.fetch_official_db
받음: data/cards.cdb  (7,958,528 bytes) + 상수 세 파일

$ python3 -m pytest tests/engine/test_legal_action_candidate_consistency.py \
                   tests/engine/test_duelstep_accepted_contract.py -q -p no:randomly
84 passed in 41.58s        exit 0      ← 6-R 45 + 6-S 39 복구 확인
```

### 1 · 2단계 — 타깃 · 수직 통합

```
$ python3 -m pytest tests/test_opening_duel_integration.py -q -p no:randomly
45 passed in 3.15s
exit 0
```

이 한 파일이 §17 의 1단계(타깃: 입력 해석 · `FixedHand`/레시피 · 덱 정합성 ·
`GameState` 구성 · `CardInstance` · 초기 턴 상태 · `legal_actions` ·
`Duel.apply` · 실행 기록)와 2단계(수직 통합: 패 5장 → 레시피 → 초기 상태 →
후보 → 실행 → 체인 → 상태 변경 → 후속 후보 → 출력)를 같이 담는다.

절별 구성 (45개):

| 절 | 수 | 내용 |
|---|---|---|
| A | 9 | §14-A·B·C·D — 레시피 둘(목록·YDK) · 해석 못한 토큰 · 빈 레시피 · 패 4가지 거절 |
| B | 5 | §14-E — 턴 1 MAIN1 · 드로우 없음 · **걸어서** 간 페이즈 · 상대·내 판이 비었다 |
| C | 7 | §14-F·G·H·I — 후보 실행 · 실제 드로우 · 체인 · 연속 5걸음 · 소환권 · **후보에서 왔다** · 후속 후보 |
| D | 4 | §15 — 매수·인스턴스 전수 · 패를 덱에서 뺌 · 선언된 덱 순서 · 후보 생성 부작용 0 |
| E | 7 | §10 — 세 사실 분리 · 🔴 거절 기록 · 정렬 독립 · 실제 카드/기록 대조 · 멈춘 이유 셋 · "최선 아님" |
| F | 4 | §14-J·K — 레시피 없으면 실행 없음 · 출력 분리(순서까지) · 부족 입력 명시 · 기존 호출 계약 |
| G | 6 | §14-L~P — 🔴 효과 몬스터 소환 불가 실측 · 어니스트 · 6-P · 6-Q · 6-R · 6-S |
| H | 3 | 하지 않은 것 — 새 엔진 없음(AST) · 선언된 상한 · 집 평가 미구현 |

### 3단계 — 관련 회귀 (12파일)

```
$ python3 -m pytest $(cat rootset.txt) -q -p no:randomly
446 passed, 1 warning in 315.21s (0:05:15)
exit 0
```

(`test_discord_bot.py` **61개** · `test_deck_builder_planner.py` ·
`test_opening_duel_integration.py` 45개 · `/search`·`/deck` 관련 · provenance
감사 등.)

**첫 실행**은 2건 실패였고 **둘 다 6-T 와 무관**했다 — 하나는
`discord.py` 미설치(환경), 하나는 출력 구조 변경에 따른 핀 이동(§7). 세
번째는 뒤에.

### 3단계 — `tests/engine` 전체

```
$ python3 -m pytest tests/engine -q -p no:randomly
3497 passed in 330.09s (0:05:30)
exit 0
```

| | 6-S | 6-T |
|---|---|---|
| `tests/engine` | 3,497 | **3,497** (변화 0) |

🔴 **0 인 것이 맞다** — 6-T 는 `engine/` 을 한 줄도 바꾸지 않았고 새 시험도
`tests/` 루트에 두었다.

**첫 실행**은 2건 실패였고 **상류 데이터 드리프트**였다 (카드군 615 → 616,
§7). 핀을 갱신하고 까닭을 적은 뒤 재실행했다.

### 4단계 — 최종 회귀

공유 계약을 바꾸지 않았으므로 (아래 §참고) 저장소 전체 회귀는 하지 않았다
(§17 "동일한 장시간 테스트를 불필요하게 반복하지 않는다"). 바꾼 생산 파일이
`deck/` · `app/` 뿐이고 그 호출자를 전부 돌렸다.

🔴 **공유 계약 변경 여부**: `recipe` 는 **마지막 선택 인자**이고 기존 호출은
한 글자도 바뀌지 않는다. 새 모델도 새 enum 도 없다 (`DeckDraft` 재사용).
`engine/` · `deck/planner.py` · `deck/model.py` · `deck/validator.py` ·
`ComboVerdict` 는 그대로다.

### 변이 시험

```
$ python3 /tmp/.../mutate.py
1차: === 변이 20개 중 16개를 잡았다 ===
     🔴 살아남은 변이: M8 · M12 · M13 · M14
     → test_e00 · test_e00b 추가
2차: === 변이 20개 중 20개를 잡았다 ===
되돌림 확인: app/discord_bot.py, deck/opening.py, deck/recipe.py
```

변이가 적용된 동안 다른 테스트를 돌리지 않았고, 끝나고 세 파일 모두 원본과
바이트가 같은지 `assert` 했다.

### §16 지표 측정

```
$ python3 /tmp/.../metrics.py
표본 (선공 패 5장 × 덱 레시피 40장, 상대 방해 없음) 6개
METRIC 1 GameState 구성 성공 = 4        METRIC 7 상태 변경 검증 = 14
METRIC 2 정합성 검증 사례 = 6           METRIC 8 후속 후보 생성 성공 = 4
METRIC 거절된 입력 = 2                  METRIC 9 최대 연속 실행 = 5
METRIC 3 legal_actions 후보 = 38        METRIC 10 Discord 실제 실행 출력 = 있음
METRIC 4 판정 통과 = 14                 METRIC 11 정적 추론을 실행으로 오인 = 0
METRIC 5 apply 접수 = 14                METRIC 10b 레시피 없을 때 부족 입력 명시 = 있음
METRIC 6 실제 해결 = 14
```

### 측정 환경

- 측정 날짜: 2026-10-17
- 시작 HEAD: `67bb9aa` (Phase 6-S 마지막 commit) · 🔴 컨테이너 클론 복구 후
- 브랜치: `claude/pensive-goodall-te1egy`
- 무작위 순서 끄기: `-p no:randomly` (전 실행 공통)
- 추가 설치: `pytest` · `pytest-randomly` · `discord.py 2.7.1`

---

## 부록 — Git 커밋

| commit | 내용 |
|---|---|
| `d7ee8c9` | `deck/recipe.py` · `deck/opening.py` · `deck/report.py` — 레시피를 읽고 선공 판을 만들어 돌린다 |
| `487986f` | `app/discord_bot.py` · `app/main.py` — `recipe` 를 더하고 실행과 계획을 가른다 |
| `d5a0baa` | 테스트 — 새 파일 45개 + 움직인 기존 핀 다섯 |
| (이 보고서) | `docs/phase6t-first-turn-combo-duel-integration.md` |

### 푸시

```
$ git push -u origin claude/pensive-goodall-te1egy
To https://github.com/Raro615/yugioh-deck-agent
   67bb9aa..6ed7395  claude/pensive-goodall-te1egy -> claude/pensive-goodall-te1egy
```

보고서 commit: `6ed7395`
