# Phase 5-D — 갈라테아 Discord `/combo` 명령

- 기준 커밋: `b4e4f3a` (보강 카드 오분류 수정)
- 작업 브랜치: `claude/pensive-goodall-te1egy`
- 변경한 프로덕션 파일: **`app/discord_bot.py` 하나**
- 범위: **`/combo` 하나.** 엔진 재설계 · 새 탐색 알고리즘 · AI 학습 ·
  덱 빌더 실전성 · EDOPro 연동 · 데이터 파이프라인은 하지 않았다.

> 파일명 메모: 직전 작업(보강 카드 오분류 수정)의 보고서도
> `docs/phase5d-…` 로 시작한다. 이 문서는 `/combo` 쪽이다.

---

## 1. 기존 콤보 플래너의 진입점 및 호출 흐름

```
Discord /combo hand:"오르페골 디베르, 하루 우라라" [board:…] [deck:…]
      ↓
combo_command(interaction, hand, board, deck)   ← app/discord_bot.py (신규)
      ↓  defer() → asyncio.to_thread
SearchService.combo_texts(hand, board, deck)    ← app/discord_bot.py (신규)
      ↓
combo_messages(agent, hand, board, deck)        ← 순수 함수 (신규)
      ↓
app.main._parse_card_ids(raw, agent)            ← 기존. 이름·ID 둘 다 받는다
      ↓
deck.hand.FixedHand(tuple(hand_ids))            ← 기존. 유일한 HandProvider
      ↓
deck.planner.ComboPlanner(repository).plan(hand_source, board, draft)
      ↓
ComboPlan(hand, board, steps, stopped_reason, unsupported, manual_checks)
```

### 확인한 실제 인터페이스 (추측하지 않았다)

| 대상 | 실제 |
|---|---|
| `ComboPlanner(repository, executable_ids=None)` | 요구하는 것은 **`repository` 하나** |
| `.plan(hand_source, board=(), draft=None)` | `hand_source` 는 `HandProvider` **또는** 카드 ID 시퀀스 |
| `HandProvider` | `hand() -> list[int]` 프로토콜. 구현은 `FixedHand` **하나** |
| `ComboPlan` | `hand` · `board` · `steps` · `stopped_reason` · `unsupported` · `manual_checks` · `confirmed_steps` · `describe_ko()` |
| `PlanStep` | `order` · `card_id` · `card_name` · `action` · `requires` · `expected` · `basis` · `status` · `note` (frozen) |
| `StepStatus` | `CONFIRMED` · `CONDITIONAL` · `UNKNOWN` · `UNSUPPORTED` |
| `StepBasis` | `ENGINE_ACTION` · `ENGINE_EXECUTABLE` · `LUA_PARSED` · `PRINTED_TYPE_ONLY` · `NONE` |
| `engine_executable_card_ids()` | `EFFECT_LIBRARY` 를 **읽어** ID 집합을 만든다 |
| `app.main._parse_card_ids(raw, agent)` | `(ids, unresolved)`. 🔴 장수를 제한하지 않는다 |
| CLI `cmd_combo` | 위치 인자 `hand` + `--board`. **`draft` 를 주지 않는다** |

---

## 2. 현재 콤보 플래너의 실제 지원 범위

### 🔴 가장 중요한 사실 — **플래너는 게임 엔진을 실행하지 않는다**

`deck/planner.py` 를 AST 로 확인했다. `Duel` · `GameState` ·
`ActionValidator` · `DuelRunner` 를 **호출하는 곳이 하나도 없다.** 엔진
쪽에서 가져오는 것은 `from engine.effect.library import EFFECT_LIBRARY`
하나이고, 그것도 **읽어서** `executable=True` 항목의 카드 ID 집합을
만드는 데만 쓴다.

즉 플래너는 **정적인 전개 후보 계산기**다. 실제 게임 상태를 돌리지도,
일부 규칙만 검증하지도 않는다 — 패의 카드마다 다음을 **정적으로** 적는다:

1. 몬스터면 일반 소환 걸음 (일반 소환권 1회를 계획 안에서 추적)
2. 효과 걸음 (근거 3층: 엔진 실행 구현 / Lua 파싱 / 카드 종류)
3. 아무 근거도 없으면 `UNKNOWN` 걸음

### 측정값

| 항목 | 값 |
|---|---|
| 엔진에 실행 구현이 등록된 카드 | **13장** / 14,127장 (전부 마법·함정) |
| 그 13장 | `5318639` `5915629` `15103313` `22589918` `55144522` `66719324` `69091732` `70368879` `73148972` `81439173` `84257639` `92595643` `94192409` |
| 엔진이 지원하지 않는 절차 | **5가지** (`ComboPlan.unsupported`) |
| 특수 소환 | `ActionValidator` 가 **언제나 `UNKNOWN`** (`UnimplementedRule("special-summon-condition")`) |
| 융합·싱크로·엑시즈·링크 | 재료 선택 절차가 엔진에 **없음** |
| 무작위 초기 패 | **구현 없음** (`FixedHand` 하나뿐) |

### 미구현 규칙 처리 방식

`RULE_NOT_IMPLEMENTED` 은 엔진의 `ValidationCode` 다. 🔴 **플래너는 그
코드를 보지 않는다** — 엔진을 돌리지 않으므로 받을 일이 없다. 미구현은
두 자리에서 표현된다: 걸음 단위로 `StepStatus.UNSUPPORTED`, 절차 단위로
`ComboPlan.unsupported` 목록.

### 덱 빌더와의 연결

`plan(draft=DeckDraft)` 를 주면 `_check_hand_against_deck` 가 "이 패가 덱
초안에서 나올 수 있는가" 를 **실제로** 본다. 주지 않으면 그 검증을
하지 않았다는 사실을 `manual_checks` 에 적는다. CLI 는 `draft` 를 주지
않으므로 **CLI 에서는 그 검증이 한 번도 돌지 않았다.**
`/combo` 의 `deck` 인자가 그것을 처음으로 돌린다.

### 테스트에서 이미 검증된 전개 사례

`tests/test_deck_builder_planner.py`: `test_14`(패 장수 0·1·7·9 모두 수용)
· `test_16`(엔진 등록 카드 → `CONFIRMED`) · `test_17`(스크립트 없는 카드 →
`UNKNOWN` 유지) · `test_18`(소환권 소진 → `CONDITIONAL`) ·
`test_19`(미지원 소환법은 계획에 넣지 않고 목록에 적는다) ·
`test_20`(없는 카드 ID 를 조용히 건너뛰지 않는다) · `test_21`(부분 근거
계획이 어디서 멈췄는지 적는다) · `test_29`(계획이 합법이라고 주장하지
않는다).

---

## 3. 변경한 파일과 변경 이유

| 파일 | 변경 | 이유 |
|---|---|---|
| `app/discord_bot.py` | +314 / −19 | `/combo` 명령 · `combo_messages` · `ComboVerdict` · `combo_verdict` · `_combo_step_lines` · `_hand_activation_correction` · `SearchService.combo_texts` · 상수 3개. **유일한 프로덕션 변경** |
| `tests/test_discord_bot.py` | +600 / −15 | `/combo` 테스트 15개 추가 + 기존 4개 갱신 |
| `docs/phase5d-galatea-discord-combo.md` | 신규 | 이 보고서 |

**변경하지 않은 것**: `deck/` 전체(플래너 포함) · `engine/` · `agent/` ·
`analysis/` · `core/` · `rules/` · `rulings/` · `app/main.py` — `git diff` 가
비어 있다. 새 의존성 0개.

Phase 5-C 의 `paginate` 를 **그대로** 재사용했다. 콤보 출력에 맞지 않는
부분이 없어 확장하지 않았다.

---

## 4. `/combo` 명령어 사용법

```
/combo hand:<카드 이름 또는 ID, 쉼표 구분>  [board:<…>]  [deck:<덱 요청>]
```

| 인자 | 필수 | 플래너의 무엇에 대응하는가 |
|---|---|---|
| `hand` | ✅ | `plan(hand_source=FixedHand(...))` |
| `board` | — | `plan(board=[...])` |
| `deck` | — | `plan(draft=DeckBuilder(...).build(...))` |

🔴 **인자 셋은 `plan()` 이 실제로 받는 것 그대로다.** 플래너가 받지 않는
입력(전개 깊이·목표 보드 등)은 만들지 않았다.

🔴 **`hand` 가 필수인 이유**: 무작위 패 생성이 구현되어 있지 않다. 패를
비워 두면 계획을 세우지 않고 그 사실을 안내한다.

예:
- `/combo hand:오르페골 디베르, 오르페골 스켈레촌`
- `/combo hand:55144522`
- `/combo hand:오르페골 디베르 deck:오르페골 덱, 패트랩 비중 우선`

### 실측 (실제 카드 데이터)

| 패 | `deck` | 메시지 | 길이 | 시간 | 판정 |
|---|---|---|---|---|---|
| `오르페골 디베르, 오르페골 스켈레촌` | — | 1 | 984 | 150 ms | 근거 있음 · 🔴 실행 검증 안 됨 |
| `55144522` (욕망의 항아리) | — | 1 | 724 | 0 ms | 근거 있음 · 🔴 실행 검증 안 됨 |
| 5장 혼합 | — | 1 | 1,936 | 0 ms | 근거 있음 · 🔴 실행 검증 안 됨 |
| `펜리르` | — | 1 | 1,081 | 0 ms | 근거 있음 · 🔴 실행 검증 안 됨 + **정정** |
| `오르페골 갈라테아` (엑스트라) | — | 1 | 761 | 0 ms | 엔진 미지원 (계획 불가) |
| `999999999` | — | 1 | 784 | 0 ms | 검증되지 않음 |
| (빈 패) | — | 1 | 190 | 0 ms | 계획 미수립 (안내만) |
| `오르페골 디베르` | ✅ | 1 | 748 | 167 ms | 근거 있음 · 🔴 실행 검증 안 됨 |

전부 2,000자 이하다. 걸음이 많으면 `paginate` 가 나눈다 (`test_52` 가
40걸음으로 확인).

### 응답에 적는 것 (플래너가 준 정보만)

요청 원문 · 해석된 카드(이름 + ID) · 🔴 해석 실패한 토큰 · 덱 비교 여부 ·
**판정** · 걸음별 (상태 · 근거 · 필요 조건 · 기대 · 비고) · 중단 사유 ·
엔진 미지원 절차 · 사람이 확인할 것.

🔴 **효과가 무엇을 하는지는 적지 않는다** — 플래너가 적지 않기 때문이다
(적으려면 효과를 해석해야 하고 이 저장소는 그 해석을 보증하지 않는다).

---

## 5. 전개 결과의 검증 상태 표시 방식

### 기존 상태 모델을 우선 재사용했다

걸음 단위 상태는 **이미 있는** `StepStatus`(확정/조건부/미확인/미지원)와
`StepBasis`(5층)를 그대로 쓴다. 엔진이나 `deck/` 에 새 상태를 추가하지
않았다.

### 계획 단위 판정만 Discord 출력 계층에 추가했다

`ComboVerdict` 는 `app/discord_bot.py` 안에만 있고, 걸음들의 `StepStatus`
에서만 계산된다 (`combo_verdict`). 카드를 다시 보거나 효과를 다시 해석하지
않는다.

| 판정 | 조건 | 표시 |
|---|---|---|
| `GROUNDED_UNEXECUTED` | `CONFIRMED` 또는 `CONDITIONAL` 걸음이 하나라도 있다 | "근거 있음 · 🔴 실행 검증 안 됨" |
| `UNVERIFIED` | 걸음이 없거나 전부 `UNKNOWN` | "검증되지 않음 (근거 있는 걸음 없음)" |
| `UNSUPPORTED` | 걸음이 전부 `UNSUPPORTED` | "엔진 미지원 (계획 불가)" |

### 🔴 `VERIFIED` 와 `PARTIALLY_VERIFIED` 를 만들지 않았다

제안된 4단계 중 둘을 **의도적으로 빼고** 그 이유를 코드와 테스트에 적었다.

플래너가 **엔진을 실행하지 않으므로** "실행하고 검증한 전개" 가 지금은
하나도 없다. `StepStatus.CONFIRMED` 조차 그 docstring 그대로
"엔진에 실행 구현이 있어 **돌려볼 수 있다**" 는 뜻이고 "돌려 봤다" 가
아니다. 그래서 가장 높은 판정이 `GROUNDED_UNEXECUTED` 이고, 그 설명에
**"실제로 돌려 본 것이 아닙니다"** 가 들어간다.

`test_47` 이 세 가지를 함께 고정한다: ① 플래너에 엔진 실행 호출이 없다
(AST), ② `ComboVerdict` 에 `verified` · `partially_verified` 값이 없다,
③ 최상위 판정조차 미실행을 적는다.

🔴 세 판정 **모두** `detail_ko()` 에 🔴 표시가 있다 (`test_48`). 어느
판정도 "전개가 된다" 로 읽히지 않게 했다. `UNVERIFIED` 도 "전개가
불가능하다" 가 아니라 "이 저장소가 판정하지 못했다" 라고 적는다.

### 🔴 플래너의 과대 진술을 출력 계층에서 정정한다

`deck/planner.py` 의 효과 걸음은 `card.has_effect_from("HAND")` 로
갈린다. 그 신호는 `SetRange` 만 보므로 **특수 소환 절차**에도 참이 된다 —
직전 작업에서 덱 빌더의 같은 결함을 고치면서 **미해결로 보고한 항목**이다.

실측: `/combo hand:펜리르` 는 "'펜리르' 의 패에서 발동하는 효과를 씁니다"
를 **조건부**로 적는다. 그런데 펜리르의 패 범위 블록은
`EFFECT_SPSUMMON_PROC` 하나이고 패에서 발동 가능한 효과는 **0개**다.
독법사 · 텐사우전드 드래곤도 같다.

§2-4 와 §9 에 따라 **플래너를 고치지 않았다** (구조적 TODO, 범위 밖).
대신 §7-1("카드 효과에 존재하지 않는 행동을 생성하지 않는다")을 지키기
위해 출력 계층이 `deck.evidence`(직전 작업에서 만든 것)로 정정 줄을
붙인다:

> 🔴 **정정**: 이 카드에는 패에서 **발동 가능한 효과가 없습니다** — 패
> 범위 블록 1개가 전부 발동이 아닌 절차·지속 효과입니다 (특수 소환 절차
> 등). 위 걸음은 전개 계획이 발동 위치만 보고 적은 것이므로 **그대로
> 믿지 마세요.**

정정은 데이터가 뒷받침할 때만 붙는다 — 하루 우라라처럼 실제로 발동
가능한 블록이 있으면 붙지 않는다 (`test_55` 가 양쪽을 고정).

---

## 6. 새로 추가한 테스트와 전체 테스트 결과

`tests/test_discord_bot.py` 에 15개 추가 (`test_44`~`test_58`).

| § | 요구 | 테스트 |
|---|---|---|
| 8-1 | `/combo` 등록 | `test_44` (실제 트리 · 인자 3개 · 필수 여부) · `test_18` · `test_19` |
| 8-2 · 8-3 | 정상 입력 전달 · 기존 플래너 호출 | `test_45` (스파이가 받은 `FixedHand` · 저장소 동일성 · 이름/ID 혼용) |
| 8-4 | Discord 메시지 변환 | `test_46` (걸음의 모든 칸 · 중단 · 미지원 · 사람 확인) |
| 8-5 | 입력 오류 | `test_49` (빈 패 → 플래너 호출 0) · `test_50` (미해석 토큰 명시) |
| 8-6 | 후보 없음 | `test_48` · `test_51` |
| 8-7 | 미구현 규칙 | `test_51` ("미구현 ≠ 불가능", `✔` 부재) |
| 8-8 | 긴 응답 분할 | `test_52` (40걸음 · 무손실) |
| 8-9 | 예외 안정성 | `test_53` (스택은 로그, 경로 비노출) · `test_54` (전용 안내) |
| 8-10 | 기존 회귀 | 같은 파일 61개 전부 |
| 5 | 검증 상태 | **`test_47`** (VERIFIED 부재 + 플래너 미실행 AST) · `test_48` |
| 7-1 · 7-3 | 없는 행동 생성 금지 | **`test_55`** (정정 · 양방향) |
| 4 | `deck` 인자 | `test_56` (초안이 실제로 전달됨 / 해석 실패 시 안 넘김) |
| 6 | `defer` · 스레드 | **`test_58`** |
| 8 | 실제 데이터 | `test_57` |

### 돌연변이 검사 — 그리고 이 검사가 내 테스트 구멍을 찾았다

🔴 **처음에 `test_58` 이 없었다.** `/deck` 에는 같은 테스트(`test_41`)를
두었는데 `/combo` 에는 빼먹었고, 돌연변이로 `defer()` 를 지우고
`to_thread` 를 직접 호출로 바꿨을 때 **60개가 모두 통과**해서 드러났다.
`test_58` 을 추가한 뒤 다시 돌려 둘 다 잡히는 것을 확인했다.

| 돌연변이 | 결과 |
|---|---|
| `/combo` 핸들러의 `defer()` 제거 | **1 failed** (`test_58`) |
| `to_thread` → 직접 호출 | **1 failed** (`test_58`) |
| 첫 메시지만 전송 | **1 failed** (`test_58`) |
| `ComboVerdict` 에 `VERIFIED` 추가 | **2 failed** (`test_47` · `test_48`) |
| 미지원뿐인데 "근거 있음" 으로 판정 | **3 failed** (`test_48` · `51` · `57`) |
| 빈 패에도 플래너 호출 | **1 failed** (`test_49`) |
| 미해석 토큰 조용히 버림 | **1 failed** (`test_50`) |
| 정정 줄 제거 | **1 failed** (`test_57`) |
| `paginate` → `clamp` | **1 failed** (`test_52`) |
| `combo_texts` 의 `try/except` 제거 | **1 failed** (`test_53`) |
| `deck` 초안을 플래너에 안 넘김 | **1 failed** (`test_56`) |
| (복원 후) | **61 passed** |

### 실행 결과

```
$ python3 -m pytest tests/test_discord_bot.py -p no:randomly -q
61 passed, 1 warning in 8.96s
```

테스트 파일 목록·`pytest.skip` 문구를 고정하는 감사 3개도 돌렸다
(테스트 추가가 그쪽을 깨뜨리는지 확인):

```
$ python3 -m pytest tests/test_auxiliary_effect_creation_clone_audit.py \
    tests/test_provenance_consumer_audit.py \
    tests/test_update_coverage_contract_audit.py -p no:randomly -q
134 passed in 391.93s (0:06:31)
```

**실패한 테스트는 없다.** 경고 1개는 `discord.py` 가 Python 3.11 에서
`audioop` 을 import 하며 내는 `DeprecationWarning` 이다. 변경 범위 밖의
전체 회귀 테스트는 돌리지 않았다.

---

## 7. 기존 기능에 대한 회귀 테스트 결과

```
$ python3 -m pytest tests/test_discord_bot.py tests/test_deck_builder_planner.py \
    tests/test_korean_search.py tests/test_search_integration.py \
    tests/test_search_semantics.py tests/test_query_parser.py -p no:randomly -q
187 passed, 1 warning in 21.20s
```

실측으로도 기존 명령이 그대로다: `/search "마법사족 몬스터"` 773자,
`/deck "오르페골 덱 짜줘"` 1개 메시지, 그리고 `/combo` 를 여러 번 돌린
뒤에도 `build_count == 1` — 네 명령이 **같은 카드 데이터**를 쓴다.
CLI `python3 -m app.main combo "오르페골 디베르, 하루 우라라"` 도 그대로
동작한다.

### 기존 테스트 4개 갱신 (삭제·skip·약화 없음)

| 테스트 | 갱신 | 왜 |
|---|---|---|
| `test_15` | 재사용 함수 목록에 `_parse_card_ids(` · `FixedHand(` · `ComboPlanner(` · `hand_effect_facts(` 추가 (5개 → 9개) | `/combo` 가 쓰는 기존 진입점을 함께 고정한다. **조건이 늘었다** |
| `test_18` | `registered == {"ping","search","deck","combo"}` · `"아직 구현하지 않았다"` → `"구현되어 있지 않습니다"` | `/combo` 를 실제로 등록했다. "구현하지 않은 것을 적지 않는다" 는 계약은 **미구현 항목 목록**(무작위 패·실행 검증·초동 확률·특수 소환 절차·EDOPro)으로 계속 지킨다 |
| `test_19` · `test_32` | 등록 집합을 네 개로 | 위와 같다. 집합을 정확히 고정하므로 구현 없는 명령이 끼면 실패한다 |

---

## 8. 실제 Discord 에서 확인해야 할 항목

🔴 이 환경에는 유효한 봇 토큰이 없다. 아래는 **확인되지 않았다.**
`test_44` · `test_58` 은 실제 `app_commands` 트리를 쓰지만 **가짜
`Interaction`** 을 넣고 접속하지 않는다.

1. **`/combo` 가 개발용 서버에 동기화되어 보이는지** (명령이 4개로 늘었다).
2. **선택 인자 두 개(`board` · `deck`)가 Discord UI 에서 생략 가능한지.**
3. **긴 패 입력이 Discord 인자 길이 제한에 걸리지 않는지.**
4. **걸음이 많을 때 메시지 2개가 순서대로 도착하는지** — 순서가 보장되지
   않으면 `(1/2)` 표시가 필요하다 (Phase 5-C 와 같은 미확인 항목).
5. **정정 줄의 마크다운이 모바일에서 읽히는지** (한 줄이 길다).

---

## 9. 아직 해결되지 않은 엔진 한계

이번 단계에서 **해결하려 하지 않았다** (§9). 숨기지 않고 적는다.

1. 🔴 **전개를 실행해 검증하는 계층이 없다.** 플래너는 정적 계산기다.
   그래서 `VERIFIED` 가 없고, 모든 판정이 "실행 안 됨" 을 적는다.
2. 🔴 **엔진 효과 실행 구현이 13장뿐이다** (14,127장 중 0.09%). 전부
   마법·함정이고 몬스터 효과는 하나도 없다.
3. 🔴 **특수 소환이 언제나 `UNKNOWN`** 이다 (`UnimplementedRule
   ("special-summon-condition")`). 융합·싱크로·엑시즈·링크의 재료 선택
   절차가 없다. 현대 유희왕 전개의 중심이 전부 여기 있다.
4. 🔴 **`deck/planner.py` 의 효과 걸음이 발동 위치만 본다.** 출력 계층에서
   정정하지만 **플래너 자체는 그대로다** (§5 마지막 절). 이것을 고치는
   것이 가장 작은 다음 수정이다.
5. 🔴 **체인·타이밍 처리가 없다.** 플래너는 걸음을 **순차 목록**으로만
   적고 체인 블록·우선권을 모델링하지 않는다. 그래서 "이 순서로 실제로
   통하는가" 는 판정되지 않고, 걸음의 `requires` 가 사람에게 넘긴다.
6. 🔴 **발동 조건과 비용을 구분하지 못한다.** `requires` 에 "발동 조건을
   이 저장소가 판정하지 못합니다" 로 적히고, 그 둘을 나누는 데이터가 없다.
7. 🔴 **무작위 초기 패가 없어 초동 확률을 계산할 수 없다.**
8. **파괴 실행 미구현** (`ValidationCode.RULE_NOT_IMPLEMENTED`) 과
   `DuelRunner._step` 이 정책 위반과 엔진 거부를 같은 `accepted` 필드에
   기록하는 분류 결함 — Phase 4-C 에서 보고한 그대로 남아 있다.
9. 동일명 매수 상한·금지·제한 검증 불가 · N62 · N63 · S5 — 그대로.

### EDOPro 에서 실제로 듀얼하는 최종 목표까지의 거리

현재 `/combo` 가 보여 주는 것은 **"엔진이 무엇을 모르는가" 의 목록**에
가깝다. 실제 듀얼 AI 가 되려면 3번(특수 소환 조건 판정)과 5번(체인·타이밍)
이 먼저 필요하고, 그 둘은 Engine V1 의 범위를 넘는 작업이다.

---

## 10. Git 커밋 및 푸시 결과

아래 §커밋 절에 적는다 (보고서 작성 시점에는 커밋 전).

## 다음 단계 후보 (최대 1개)

**`deck/planner.py` 의 효과 걸음을 `deck.evidence` 로 고친다** (위 4번).
지금은 Discord 출력 계층이 정정하고 있어 CLI 에는 정정이 없다 — 플래너를
고치면 두 곳이 같아진다.

🔴 다음 Phase 는 임의로 진행하지 않는다.
