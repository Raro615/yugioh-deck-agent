# Phase 6-AB 보완5 — 빈 체인의 빠른 효과 기회 · 실제 사건의 후속 유발

🔴 **먼저 적어 두는 네 가지**

1. **이 작업 환경에 `data/cards.cdb` 가 있다.** 보완5 의 통합 검증은
   생략되지 않았고, 아래 §8 의 명령·로그·종료 코드가 실제로 돌린 것이다.
   (사용자 §1 이 "없어서 생략되었다" 를 전체 성공으로 읽지 말라고 적었다 —
   이번에는 생략이 없으므로 그 조건이 걸리지 않는다. 그 대신 **생략한
   것이 따로 있고** §8.5 가 적는다.)
2. **②는 실제 카드로 한 바퀴를 돌았다. 그러나 그 카드의 지원 완료가
   아니다.** 합성한 것은 **조작 하나**(드로우 1장)이고, 그 카드의 실제
   효과(특수 소환)는 구현되지 않았다. §6 이 실제와 합성을 줄 단위로
   가른다.
3. **②를 재려다 규칙 계층의 누락 하나를 함께 메웠다** — 목표에 없던
   변경이다. §7 이 그것만 따로 적는다 (근거 · 범위 · 되돌리는 방법).
   받아들일지 되돌릴지는 사용자의 판단이다.
4. **다음 Phase 를 시작하지 않았다.**

---

## 1. 시작 / 최종 커밋과 변경 파일

| | |
|---|---|
| 검토 기준 HEAD (작업 시작) | `5b6e020` |
| 최종 HEAD (코드) | `981b083` (이 보고서 커밋은 그 뒤에 온다 — §12) |
| 브랜치 | `claude/pensive-goodall-te1egy` |

커밋 셋이고 **되돌리는 단위**로 끊었다.

| 커밋 | 무엇 |
|---|---|
| `9395375` | ② — `graveyard_zone_for` (§7 의 범위 밖 변경이 **여기 하나에만** 있다) |
| `e43a1fd` | ① — 빈 체인의 빠른 효과 기회 + `tests/engine` 의 정정 64건 |
| `ae5f15f` | `/combo` 의 걸음마다 자기 결과를 적는다 |
| `a2f3d87` | 측정값 핀 갱신 + 간접 지표를 직접 측정으로 (탐색 digest · `tests/agent` 셋 · `test_03`) |
| `981b083` | 열거 감사 다섯의 좌표와 수 |

### 변경 파일

**엔진 · 규칙**

| 파일 | 무엇 |
|---|---|
| `engine/duel.py` | `_response_priority` 가 빈 체인에서 기회를 연다 (여는 호출은 한 곳) · `_after_window_moved` 신규 · `_apply_pass` 의 빈 체인 가지 |
| `engine/response.py` | `AFTER_FAST_WINDOW_RULE` · `ResponseLoop.close_fast_window` |
| `engine/trigger.py` | `graveyard_zone_for` · `_activation_zone(moved_to=)` · `_zone_from_grave` |

**조립 · 응용**

| 파일 | 무엇 |
|---|---|
| `integration/autonomy.py` | `_duel_registries` 신규 · `_integrator(definitions=, implementations=)` · `trigger_offers` 가 그 판의 등록부를 쓴다 · `run_trigger` 가 해결 걸음을 읽는다 |
| `agent/simulation.py` | `_settle_forced_passes` 가 해결 걸음을 돌려준다 |
| `deck/opening.py` | `_settle_chain` 이 해결 걸음을 돌려준다 (없으면 `None`) · `execute_opening` 이 `PASS` 만 남은 자리에서 멈추지 않는다 |

**시험**

| 파일 | 무엇 |
|---|---|
| `tests/engine/test_empty_chain_fast_window.py` | **신규 19건** (①) |
| `tests/engine/test_followup_trigger_integration.py` | **신규 26건** (②) |
| `tests/engine/window_helpers.py` | 공용 도구 (수집되지 않는다 — `test_` 로 시작하지 않는다) |
| `tests/conftest.py` | `settle_chain` 의 계약 정정 |
| 기존 시험 19 파일 | 기대값 정정 — §9.3 |

---

## 2. 재현한 결함 — 관측한 사실

### 2.1 A — 체인이 비면 빠른 효과 기회 없이 판이 열렸다

`_bilateral` 판(같은 사건에 양측 기회)에서 양쪽이 임의 유발을 포기한 직후:

```
상대 포기: priority.window=none holder=None open=False
          chain=0 window_passed=[0, 1]
🔴 내 허가   = ['end_phase', 'set_spell_trap']
🔴 상대 허가 = []
🔴 END_PHASE 즉시 수락 = True → 페이즈=BATTLE
```

**재현됨.** 턴 플레이어가 빠른 효과 기회 없이 다음 행동으로 넘어갔고,
상대는 그 자리에서 함정도 속공 마법도 발동할 기회를 받지 못했다.

같은 증상을 **네 자리**에서 재현했다.

| 자리 | 관측 |
|---|---|
| 양쪽이 임의 유발을 포기 | 위 |
| 한쪽만 유발 기회 · 그쪽이 포기 | `window=none` · 상대 허가 `[]` |
| 유발이 **없는** 판 변경(세트) 뒤 | `window=none` · 다음 세트가 바로 수락 |
| 체인이 해결된 뒤 | `window=none` · `['end_phase','set_spell_trap']` |

🔴 **네 번째는 처음 측정에서 판단을 유보했다.** 쓰던 탐침의 `_settle` 이
`while duel.priority.is_open` 으로 돌아서, 새로 열린 기회까지 삼켜 버릴
수 있었다. 걸음마다 끊어 다시 재서 확정했다 — 그래서 §9 의 새 도구
`_decline_triggers` 는 **유발 기회만** 지나가고 빠른 효과 기회는 남긴다.

### 2.2 B — 후속 유발이 후보로 오르지 못했다

기르수 ①이 **실제로** 풀리면 저널에 이렇게 적힌다.

```
seq=1 EFFECT 69811710:e[0]
   #34 P0/DECK → P0/GRAVE (send_to_grave)
   P0 의 DECK 34장을 섞었다
내 묘지 [93920420]
```

그 카드(`93920420` 星遺物－『星杖』)의 **실제 Lua** 가 `EVENT_TO_GRAVE` +
`EFFECT_TYPE_TRIGGER_O` + `EFFECT_FLAG_DELAY` 를 등록하고, `registry_for_view`
가 그것을 `93920420:e[1] @card_moved subject=SELF to_zones={GRAVE} OPTIONAL IF`
로 컴파일해 **등록까지 한다** (카드가 묘지에 보이므로).

그런데 후보가 되지 않았다. **조건부 발생**이고, 막는 것이 **둘**이었다.

```
① 후보를 세는 쪽이 다른 등록부를 본다
   status=UNKNOWN code=RULE_NOT_IMPLEMENTED
   reason='93920420:e[1] 의 정의가 등록되어 있지 않아 조건을 확인할 수
           없습니다.'
   → trigger_offers 는 ELIGIBLE 만 돌려주므로 후보에 오르지 않는다

② 정의를 그 판의 등록부에 꽂아도 자리 관문이 모른다
   collect=1  order=0        ← 수집은 ELIGIBLE, 판정이 떨어뜨린다
   activation_zone=unknown RULE_NOT_IMPLEMENTED
       '발동할 수 있는 자리가 선언되지 않았습니다.'
```

①은 조립 층의 전달 누락이고 (§6.2), ②는 규칙 계층의 읽기 누락이다 (§7).

### 2.3 미재현

| 항목 | 결과 |
|---|---|
| 유발 등재 단계 자체가 안 닫힌다 | **미재현** — 보완4 가 고친 그대로다 |
| 체인 도중에 후속 유발이 끼어든다 | **미재현** — 체인이 서 있는 동안 양측 후보가 `[]` 였다 |
| 사본이 원본의 기회를 소비한다 | **미재현** — 보완4 의 `_fork` 보존이 그대로 선다 |

---

## 3. 공식 근거와 대조한 결과

### 3.1 단정의 근거 — 공식 Fast Effect Timing 도표

`https://www.yugioh-card.com/en/play/fast-effect-timing/` (6-AB 이래 이
저장소가 써 온 자료).

| 도표의 문장 | 이 작업에서 쓴 곳 |
|---|---|
| *"Many actions can ONLY be performed when the game state is open (when you're in box A)."* | ①-3 — 빠른 효과 단계에 열린 상태 전용 행동을 내지 않는다 |
| *"Whenever either player performs an action, the game state is no longer open."* | ①-1 · A-3 · A-4 — 판을 바꾸는 행위 뒤에도 기회가 열린다 |
| *"If there is no effect that can be triggered."* → **Turn Player (box B)** | 🔴 **핵심.** 유발할 효과가 없을 때 가는 곳이 **열린 상태가 아니다** |
| *"If the Turn Player passes."* → **Opponent (box C)** | ①-4 — 제어권이 실제로 넘어간다 |
| 다시 열리는 조건 — 턴 플레이어가 넘기고 · 상대가 되돌려 넘기고 · 체인이 없다 | ①-5 — **셋**이다. "체인이 없다" 는 그 중 하나다 |
| 체인 해결 뒤에도 유발 확인 자리를 거친다 | ①-8 |

### 3.2 단정의 근거 — Konami 룰북

`data/rules/documents/sd-rulebook-en-v10.json`, *Trigger Effect* 절:

> These effects are activated at specific times, such as "during the
> Standby Phase" or "when this monster is destroyed".
> **Example**: When this card is destroyed by battle and sent to the
> Graveyard: Target 1 card on the field; destroy that target.

🔴 **이 한 줄이 §7 의 유일한 근거다.** 공식 자료가 **발동할 수 있는 유발
효과의 예로** 그 문장을 들고 있고, 그 효과가 발동하는 순간 카드가 있는
자리는 묘지다.

### 3.3 구현 관찰 — 공식 재정이 아니다

저장소 안의 Project Ignis / EDOPro 카드 스크립트를 센 것이다. **공식
근거로 쓰지 않았고**, 범위를 좁히는 쪽으로만 썼다.

```
EFFECT_TYPE_TRIGGER_O   4,471 파일
EFFECT_TYPE_TRIGGER_F   1,661
EFFECT_TYPE_QUICK_O     1,718
EFFECT_TYPE_QUICK_F        19
EFFECT_FLAG_DELAY       2,733
```

`c93920420.lua` · `c56840658.lua` 의 등록 내용도 구현 관찰이다 — 그
카드가 **언제 유발하는가**는 거기서 읽고, **무엇을 하는가**는 §6 이
합성이라고 적는다.

### 3.4 근거를 찾지 못해 그대로 둔 것

| 질문 | 상태 |
|---|---|
| 덱 · 패 · 제외 도착에서 유발을 발동할 수 있는가 | **근거 없음** → `UNKNOWN` 유지 (§7.2) |
| 강제 「때」가 타이밍을 놓쳤을 때의 세부 | **근거 없음** → `UNKNOWN` (6-AB 이래 그대로) |
| 비공개 영역(덱 · 패) 유발의 순서 | **근거 없음** → `UNKNOWN` |
| 상자 D~F (데미지 스텝 · 체인 중 타이밍 세부) | 범위 밖 — 손대지 않았다 |

🔴 **TCG 도표를 OCG 의 비공개 유발 세부까지 검증한 근거로 쓰지 않았다.**
도표에서 읽은 것은 **상자 A · B · C 의 전이**뿐이고, 그 셋은 도표에
문장으로 적혀 있다.

---

## 4. ① 빈 체인의 빠른 효과 기회 — 구현과 상태 전이

### 4.1 고친 방식

세 자리이고 **전부 기존 계층을 부른다.**

```
Duel._response_priority()
    체인이 비면 → 쥐는 자리는 턴 플레이어 (box B)
    체인이 쌓였으면 → 마지막 발동 자리의 상대 (RULE-CHAIN-001)
    🔴 여는 호출은 ResponseLoop.opened( 한 곳이다 — 쥘 자리와 이유만
       갈라진다 (test_priority_response_audit.test_02 가 그 수를 센다)

Duel._after_window_moved()            ← 신규
    등재할 유발이 있으면  → 등재 단계가 먼저다 (우선권은 닫힌 채)
    없으면                → 빠른 효과 기회를 연다
    부르는 자리 둘: apply (판을 바꾸는 행위 수락 뒤) · _resolve_chain
    🔴 _apply_end_phase 에서는 부르지 않는다 — 도표가 "This is where each
       Phase and Step starts" 를 box A 로 적는다

Duel._apply_pass()  빈 체인 가지       ← 신규
    양쪽이 지나갔으면 → ResponseLoop.close_fast_window 로 닫는다
    아니면            → "상대의 차례입니다"
    🔴 닫는 일을 Duel 이 직접 하지 않는다 — 닫는 이유를 응답 계층이 들고
       있고 (AFTER_FAST_WINDOW_RULE), 흐름을 두 곳에서 닫으면 둘이 갈라진다
```

🔴 **두 번째 규칙 엔진을 만들지 않았다.** 자리를 가리키는 권위는 여전히
`_window_actor()` 하나(SEGOC 네 묶음)이고, 체인·응답·해결은 `ResponseLoop`
와 `ChainResolver` 그대로다.

🔴 **새 상태 필드를 만들지 않는 것을 목표로 삼지 않았다.** 결과적으로
새 필드는 없었다 — 기존 `priority` · `window_passed` · `chain` 이 이미
서로 다른 것을 세고 있었고, 비어 있던 것은 **그 사이의 전이**였다.

### 4.2 전이 — 지금 (실측)

```
열린 상태 (box A)
  │  판을 바꾸는 행위 (소환 · 세트 · 발동)
  ▼
유발 등재 단계                        window_floor 가 옮겨 간다
  │  네 묶음 순서로 자리를 가리킨다 (_window_actor)
  │  각 자리가 발동하거나 PASS → window_passed 에 든다
  ▼
빠른 효과 기회 (box B)                priority.window = RESPONSE
  │  쥔 쪽 = 턴 플레이어 · 허가 = ['pass'] (+ 발동할 수 있으면 발동)
  │  TP PASS →  (box C) 쥔 쪽 = 상대
  │  NTP PASS →
  ▼
열린 상태 (box A)                     priority.window = NONE
```

실측 (`verify_a.py`):

```
시작          win=none  holder=None passes=0 chain=0 passed=[]      ['activate_effect','pass']
내 유발 포기   win=none  holder=None passes=0 chain=0 passed=[0]
상대 유발 포기 win=response holder=0 passes=0 chain=0 passed=[0,1]
   🔴 내 허가 ['pass']  상대 허가 []   · END_PHASE 직접 = False
TP 빠른 포기  win=response holder=1 passes=1                "빠른 효과 기회를 넘겼습니다 — 상대의 차례입니다."
   🔴 내 허가 []        상대 허가 ['pass']
NTP 빠른 포기 win=none  holder=None passes=0                "양쪽이 빠른 효과 기회를 지나갔습니다 — 판이 다시 열렸습니다."
   🔴 내 허가 ['end_phase','set_spell_trap']   · END_PHASE = True → BATTLE
```

### 4.3 §3 의 필수 동작 10 — 하나씩

| | 요구 | 결과 | 근거 |
|---|---|---|---|
| 1 | 임의 유발을 모두 포기해 체인이 비어도 곧바로 일반 행동으로 돌아가지 않는다 | **완료** | `test_a01` · `test_a02` — `END_PHASE` 수락 `False`, 허가 `['pass']` |
| 2 | 유발 기회가 한쪽에만 있었어도 양측의 빠른 효과 기회를 **별도로** 보장한다 | **완료** | `test_a03` — `window_passed=={0}` 인데도 양측 PASS 를 요구 |
| 3 | 빠른 효과 단계에 열린 상태 전용 행동을 허용하지 않는다 | **완료** | `test_b01` — 소환 · 세트 · 기동 · 페이즈 이동 전부 후보 밖 |
| 4 | TP 가 포기하면 상대에게 **실제** 제어권이 넘어간다 | **완료** | `test_b02` — `holder` · `to_act` 가 옮겨 가고 **허가도 뒤집힌다** (`내 []` / `상대 ['pass']`) |
| 5 | 양측이 포기한 뒤 열린 상태로 돌아간다 | **완료** | `test_b03` — `window=NONE`, `END_PHASE` 수락, 페이즈 이동 |
| 6 | 이 PASS 를 페이즈 이동 동의나 체인 해결 PASS 로 잘못 재사용하지 않는다 | **완료** | `test_c01`~`c03` — §4.4 |
| 7 | 빠른 효과가 발동되면 정상 체인 구성 · 응답 · 해결 경로로 연결한다 | **완료 (실제 카드)** | `test_b04` · `test_b05` — §4.5 |
| 8 | 체인 해결 뒤에도 유발 확인과 필요한 빠른 효과 기회를 거친다 | **완료** | `test_a05` · `test_c04`(②) |
| 9 | 종료된 유발 기회가 빠른 효과 단계나 열린 상태 복귀 시 재등장하지 않는다 | **완료** | `test_d01` · `test_d02` — 양쪽 자리 모두 후보 `[]` |
| 10 | 반복 조회 · 불법 행동 거절이 포기나 우선권 이동을 만들지 않는다 | **완료** | `test_e01` · `test_e02` — 판 · 기회 · 우선권 · 저널 · 소비를 한 묶음으로 비교 |

### 4.4 PASS 의 **세** 가지 뜻 — 섞이지 않는다

보완4 까지 둘이었고 보완5 가 셋이 되었다.

| PASS | 무엇을 하는가 | 이유 문장 | 체인 |
|---|---|---|---|
| 유발 처리 기회를 지나간다 | `window_passed` 에 든다 | *"이 유발 처리 기회에서 발동하지 않기로 했습니다"* | 그대로 |
| **빠른 효과 기회를 지나간다** | 우선권이 옮겨 가거나 기회가 닫힌다 | *"빠른 효과 기회를 넘겼습니다 — 상대의 차례입니다."* / *"양쪽이 … 판이 다시 열렸습니다."* | **비어 있다** |
| 체인을 푼다 | `ChainResolver` 가 푼다 | *"체인1 P0 … 를 해결했습니다."* | 비워진다 |

🔴 **두 번째가 아무것도 풀지 않는다는 것을 규칙 계층이 말한다** —
`ResponseStep.NO_CHAIN` 이고 `ready_to_resolve` 가
`CHAIN_EMPTY`(*"풀 링크가 없습니다"*)를 돌려준다 (`test_c01`).

🔴 **페이즈 이동 동의도 아니다** — 창이 `PHASE_CHANGE` 가 아니고, 두
PASS 어느 것도 페이즈를 움직이지 않는다 (`test_c02`). 페이즈를 넘기는
것은 `END_PHASE` 이고 그것은 판이 열린 뒤에만 후보가 된다.

🔴 **유발 포기를 빠른 효과 포기로 간주하지 않았다** (§2 의 요구).
`window_passed` 와 `priority` 는 끝까지 **다른 것을 센다** — `test_a03`
이 `window_passed=={0}` 인 판에서도 양측 PASS 를 요구하는 것이 그 증거다.

### 4.5 ①-7 — **실제 카드**로 빠른 효과가 실행된다

🔴 **우선권 값이 바뀐 것을 실행 성공으로 적지 않았다.** 잰 것은 상대
패의 장수다.

실제 카드 **욕망의 선물 `5915629`** (일반 함정 — *상대는 2장 드로우한다*).
세트한 턴 제약(`RULE-SPELLTRAP-009`)을 그대로 지나려고 다음 턴에 본다.

```
세트 직후   win=response holder=0 chain=0  ['pass']          ← 세트도 기회를 연다
다음 턴     win=none                       ['activate_effect','end_phase',…]
몬스터 세트 win=response holder=0 chain=0
🔴 빠른 효과 창 허가 ['activate_effect','pass']
🔴 함정 후보 ['5915629:e[0]']
발동        chain=1 holder=1  "5915629:e[0] 를 체인 1 로 발동했습니다. 상대의 응답을 기다립니다."
패스 P1     chain=1 holder=0  "우선권을 넘겼습니다."
패스 P0     chain=0           "체인1 P0 5915629:e[0] 를 해결했습니다."
패스 P0     chain=0 holder=1  "빠른 효과 기회를 넘겼습니다 — 상대의 차례입니다."
패스 P1     win=none          "양쪽이 빠른 효과 기회를 지나갔습니다 — 판이 다시 열렸습니다."
🔴 상대 패 = 2 → 4
```

**완료.** 실제 카드가 그 창에서 후보로 올라 정상 체인 경로로 해결되고
판을 바꾸었다.

🔴 **그러나 스펠 스피드 2 전체의 지원이 아니다.** `EFFECT_LIBRARY` 에
실행 구현이 있는 함정은 4장 · 속공 마법은 3장이고, 그 7장 밖의 빠른
효과는 여전히 후보가 되지 않는다.

---

## 5. 사본 — 새 단계도 원본과 섞이지 않는다

| 재는 것 | 결과 | 근거 |
|---|---|---|
| 사본이 **같은 단계 · 같은 차례 · 같은 후보**를 본다 | **완료** | `test_f01` — `window` · `holder` · `to_act` · `window_passed` · 양측 허가가 전부 같다 |
| 사본의 PASS 가 원본을 바꾸지 않는다 | **완료** | `test_f02` — 사본이 두 번 지나가 창을 닫은 뒤에도 원본의 묶음 지문이 동일 |
| 사본이 **후속 유발**을 써도 원본의 기회가 남는다 | **완료** | `test_c05`(②) — 원본 후보에 그대로 있고 `consumed_events` 가 비어 있다 |

비교에 쓴 지문은 **판 하나만이 아니다**:

```
state_hash · phase · len(chain) · window_floor · chain_floor ·
window_passed · consumed_events · priority.window · holder · passes ·
len(journal.events)
```

---

## 6. ② 체인 해결 중 발생한 실제 사건의 후속 유발

### 6.1 실제인 것과 합성인 것 — 줄 단위로

| | 실제 | 합성 |
|---|---|---|
| 카드 | `93920420` 星遺物－『星杖』 (실제 cdb · 실제 Lua) | — |
| 사건 | 기르수 ①의 **실제 해결**이 쓴 `ZoneMoved #34 DECK→GRAVE` | — |
| 사건 번호 · 개체 · 자리 | 실제 (`seq=1` · `#34` · `GRAVE`) | — |
| 시점 선언 (언제 유발하는가) | 실제 Lua → `@card_moved subject=SELF to_zones={GRAVE} OPTIONAL IF` | — |
| 후보 생성 · 다섯 관문 · SEGOC 정렬 | 실제 | — |
| 체인 구성 · 응답 · 해결 · 소비 기록 | 실제 (`Duel.apply`) | — |
| **조작 (무엇을 하는가)** | — | 🔴 **드로우 1장.** 실제는 패에서 「星遺物」 몬스터 특수 소환이고, 특수 소환은 범위 밖이다 |

🔴 **그래서 이것은 `93920420` 의 지원 완료가 아니다.** `test_e01` 이
프로덕션 등록부에 그 정의가 **없다**는 것을 센다. `test_e02` 가 합성이
조작 하나뿐임을, `test_e03` 이 시점 · 강제 여부를 **정의가 말하지 않고
등록소가 Lua 에서 만든다**는 것을 센다.

🔴 **사용자 §4 의 조건을 지켰다** — 초기 보드 · 덱 구성과 효과 정의 ·
조건 등록만 했다. 원하는 시점의 제안을 하드코딩하지 않았고 (제안은 실제
`TriggerSource` 가 만든다), 사건 순번을 바꾸지 않았고, 실행 중에 허가 ·
체인 링크 · 소비 기록 · 최종 상태를 주입하지 않았다.

### 6.2 막던 것 ① — 후보를 세는 쪽이 다른 등록부를 보았다

`trigger_offers` 는 `_integrator` 를 통해 **프로덕션 등록부**로만
판정했다. 그래서 다른 등록부를 꽂은 판에서는:

```
발동기 (EffectActivator)  그 효과를 안다
해결기 (ChainResolver)    실행할 수 있다
후보 판정                 "정의가 등록되어 있지 않아 조건을 확인할 수 없습니다"
```

**보완4 가 `Simulator._fork` 에서 고친 것과 같은 병이다** — 판마다 등록부가
다를 수 있는데 한쪽이 프로덕션을 되묻는다. 조립 층의 일은 **전달과
변환**이므로, 판이 들고 있는 것을 가져다 넘기게 했다
(`_duel_registries` — 읽기만 한다).

`test_f03` 이 **같은 판 · 같은 사건 · 같은 선언인데 등록부만 다른** 두
판정을 나란히 돌려 그 차이를 센다.

### 6.3 막던 것 ② — 발동 자리를 모른다고 했다

§7 이 따로 적는다.

### 6.4 한 바퀴 — 실측

```
 1. 소환 뒤 유발 후보 ['69811710:e[0]']
 2. 기르수① 발동      chain=1 chain_floor=1 holder=1
 3. 체인 도중 후보     내 [] / 상대 []        ← 끼어들지 않는다 (聖鳥クレイン)
 4. 패스 P1            chain=1  "우선권을 넘겼습니다."   후보 []
 5. 패스 P0            chain=0  "체인1 P0 69811710:e[0] 를 해결했습니다."
 6. 저널               seq=1 EFFECT  #34 P0/DECK → P0/GRAVE (send_to_grave)
    내 묘지            [93920420]
 7. 해결 뒤 후보       ['93920420:e[1]']      ← 다 풀린 뒤에 오른다
 8. 발동               chain=1 "93920420:e[1] 를 체인 1 로 발동했습니다.
                                상대의 응답을 기다립니다."  holder=1
 9. 같은 사건 재발동    후보 []  · 직접 넣으면 거절
10. 패스 P1 · 패스 P0  chain=0  "체인1 P0 93920420:e[1] 를 해결했습니다."
11. 판                 패 4→5 · 덱 34→33
    저널               seq=2 EFFECT 93920420:e[1]  "P0 가 #7 를 드로우"
    소비 기록          (card_moved #34 DECK→GRAVE, 93920420:e[1], #34)
12. 빠른 효과 기회      2 PASS → win=none → ['end_phase','set_spell_trap']
    END_PHASE          수락 → BATTLE
```

| 걸음 | 결과 | 시험 |
|---|---|---|
| 실제 해결이 사건을 쓴다 | **완료** | `test_a01` |
| 그 카드가 실제 `93920420` 이고 관측에 보인다 | **완료** | `test_a02` |
| 시점 선언이 실제 Lua 에서 나온다 | **완료** | `test_a03` |
| 묘지 도착 관문이 자리를 인정한다 | **완료** | `test_b01` |
| 체인 도중에 끼어들지 않는다 | **완료** | `test_b02` |
| 다 풀린 뒤에 후보가 된다 | **완료** | `test_b03` |
| `Duel.apply` 가 체인 1 을 세우고 응답 기회를 연다 | **완료** | `test_c01` |
| 해결이 판을 바꾸고 저널이 일치한다 | **완료** | `test_c02` |
| 같은 사건으로 두 번 발동할 수 없다 | **완료** | `test_c03` |
| 그 뒤 일반 흐름으로 돌아간다 | **완료** | `test_c04` |
| 사본이 원본의 기회를 쓰지 않는다 | **완료** | `test_c05` |

🔴 **체인 링크는 하나였다.** "남은 링크가 후속 유발보다 먼저 풀린다" 를
2 링크 체인으로 직접 재지는 않았다 — 실제 카드로 그 자리에 둘째 링크를
세울 수단이 이 범위에 없다 (`EFFECT_LIBRARY` 의 속공 마법 셋은 전부 대상
1개를 요구하고, 이 판에 그 대상이 없다). 다만 `Duel._resolve_chain` 이
`resolver.resolve_all` 로 **체인 전체를 한 `apply` 안에서** 풀므로 구조상
끼어들 자리가 없고, `test_b02` 가 체인이 서 있는 동안 후보가 `[]` 임을
센다. **미달성 항목으로 적는다** → BLOCKER-F5-3.

---

## 7. 🔴 목표 밖의 변경 — `graveyard_zone_for`

### 7.1 왜 했는가

②를 재려 하자 `activation_zone` 관문이 멈춰 세웠다.

```
activation_zone=unknown RULE_NOT_IMPLEMENTED
    '발동할 수 있는 자리가 선언되지 않았습니다.'  notes=('activates_from 미선언',)
```

`EFFECT_TYPE_SINGLE` 트리거 등록은 `SetRange` 를 **적지 않는다** —
그래서 `activates_from` 이 비고, 관문이 전부 모름을 낸다. 이 상태에서는
②의 검증이 **후보 생성 앞에서 끝난다.**

### 7.2 어떻게 했는가 — 6-V 와 **같은 모양**

6-V 가 소환 사건에 대해 이미 같은 자리를 풀어 두었다
(`summoned_zone_for` — *"사건 자신이 자리를 들고 있다"*). 보완5 는
묘지 도착에 대해 같은 모양으로 푼다.

```
graveyard_zone_for(event, source) -> Zone | None
    이동 사건이 아니면            → None
    그 이동이 다른 카드의 것이면   → None
    도착지가 묘지가 아니면         → None       🔴 덱 · 패 · 제외는 그대로 모름
    그 밖                        → Zone.GRAVE
```

관문 쪽 보호장치도 소환 쪽과 같다.

* 시점이 `CARD_MOVED` 이고 주체가 `SELF` 일 때만 본다
* 사건이 적은 도착지와 **관측이 보는 현재 자리**가 **둘 다** 맞아야 통과한다
  (사이에 또 움직였으면 `UNKNOWN` — `_zone_from_grave` 의 두 번째 가지)
* 카드별 분기가 **없다** — 데이터(시점 · 주체 · 도착지)만 본다

### 7.3 근거

§3.2 의 룰북 *Trigger Effect* 예문 하나다. 그 밖의 도착지에 대한 근거는
찾지 못했고, **그래서 묘지만 열었다.**

### 7.4 이것이 "UNKNOWN 을 VALID 로 승격" 인가 — 둘 다 적는다

🔴 **사용자 §7 이 금지한 항목과 모양이 겹친다.** 그래서 판단을 숨기지 않고
양쪽 사실을 적는다.

**승격이 아니라고 보는 근거**

* 바꾼 것은 **빠져 있던 읽기**다 — 사건이 들고 있던 값을 관문에 전달한다.
  6-V 가 같은 일을 소환에 대해 이미 했고, 그 설계를 그대로 따랐다.
* 프로덕션 규칙 계층의 변경이고 **테스트 전용 허가가 아니다.**
* **관문 하나가 허가를 만들지 않는다.** `test_05` 가 그것을 센다 — 자리
  관문이 `VALID` 가 되어도 정의가 등록되지 않은 판정은 **전체가 그대로
  `UNKNOWN`** 이고 `may_activate is False` 다.
* 이 저장소가 스스로 적어 둔 반례가 **이 변경의 정답을 가리킨다.**
  `_activation_zone` 의 설명이 *"그쪽에 `MZONE` 을 채우면 드로우
  개구리(56840658)에서 이미 재현된 잘못된 확신이 된다"* 고 적어 두었다.
  그 말은 맞다 — 그런데 보완5 가 채우는 값은 `MZONE` 이 **아니라 사건이
  적은 도착지**이고, 드로우 개구리의 실제 발동 자리는 묘지다.
  (`test_trigger_activation_location.test_05` 가 쓰는 카드가 바로 그
  카드다.)

**그래도 짚어 둘 것**

* 목표 ①·②에 **없던 변경**이다. ②의 검증을 가능하게 한 변경이므로,
  "검증을 통과시키려고 모름을 열었다" 는 의심이 성립할 수 있는 자리다.
* 근거가 **룰북 예문 하나**다. 그 문장은 "묘지로 간 카드의 유발 효과가
  발동한다" 를 보여 주지만, *"그 효과의 발동 장소가 묘지다"* 를 그 말로
  적지는 않는다 — 그것은 **"카드가 그때 거기 있다"** 에서 따라오는
  읽기다.

**되돌리는 방법**: 커밋 `9395375` 하나를 되돌리면 된다 (`engine/trigger.py`
+ 그 시험 둘). 되돌린 뒤의 상태는 §7.1 의 측정 그대로다 — ②는
**부분 완료**가 되고, 후보 생성 앞에서 멈춘다.

### 7.5 되돌린 상태의 ② — 측정값

`graveyard_zone_for` 가 없을 때 (§2.2 의 ② 측정):

| 걸음 | 결과 |
|---|---|
| 실제 해결이 사건을 쓴다 | 완료 |
| 그 카드가 묘지에 보인다 | 완료 |
| 실제 Lua 가 선언을 만들고 등록된다 | 완료 (`registered=3`) |
| `TriggerCollector` 가 후보를 만든다 | 완료 (`collect=1`) |
| **판정이 통과한다** | **미달성** — `activation_zone=unknown` |
| 후보로 오른다 | 미달성 (`order=0` · `trigger_offers` 가 빈 짝) |
| 발동 · 응답 · 해결 · 재발동 차단 · 복귀 | 미달성 (닿지 않는다) |

---

## 8. 테스트 — 명령 · 결과 · 실제 종료 코드

### 8.1 실행 방식

```bash
#!/usr/bin/env bash
# scratchpad/run/runtests.sh — pytest 의 **진짜 종료 코드**를 기록한다
set -u
LOG="$1"; shift
timeout 7000 python3 -m pytest "$@" -q -rf > "$LOG" 2>&1
CODE=$?
echo "PYTEST_EXIT=$CODE" >> "$LOG"
echo "PYTEST_EXIT=$CODE"
exit $CODE
```

🔴 **이 파일이 왜 있는가**: 보완 이전에 `nohup … &` 뒤의 `$?` 를 읽고
"종료 코드 0" 을 보고서에 적은 적이 있다. 그것은 백그라운드로 보낸
결과이고 pytest 의 것이 아니다. 이번에도 한 번 걸렸다 — 하네스가
"exit code 0" 이라고 알려 준 실행의 로그에 `PYTEST_EXIT=1` 이 적혀
있었고 **64건이 실패**였다 (§9.2). 로그의 값을 읽었다.

### 8.2 최소 재현 → 목표 → 통합 → 회귀

| 단계 | 무엇 | 결과 |
|---|---|---|
| 최소 재현 (A) | `repro_a.py` → `verify_a.py` | §2.1 · §4.2 |
| 최소 재현 (B) | `repro_b*.py` → `probe_b_full.py` → `probe_b_tail.py` | §2.2 · §6.4 |
| 목표 ① | `tests/engine/test_empty_chain_fast_window.py` | **19 passed** · `PYTEST_EXIT=0` |
| 목표 ② | `tests/engine/test_followup_trigger_integration.py` | **26 passed** · `PYTEST_EXIT=0` |
| 통합 (`/combo`) | `probe_combo.py` · `probe_discord2.py` | §10 |
| 회귀 | 네 묶음 — §8.3 | §8.3 |

### 8.3 네 묶음 — 실제 종료 코드

🔴 **묶음 넷을 그대로 썼다** (보완4 와 같은 위험 기반 분할). 그런데
``tests/`` 뿌리 묶음 둘이 **백그라운드 30분 한계에 걸려 두 번 중단되었다**
(81% · 89%). 실패가 아니라 **중단**이므로 그렇게 적고, 각 묶음을 열두
파일씩 **여덟 조각**으로 쪼개 전부 끝까지 돌렸다.

#### 1차 실행 — 실제 종료 코드

| 묶음 | 결과 | 종료 코드 |
|---|---|---|
| `tests/engine` | **64 failed, 3708 passed** (919.54s) | `PYTEST_EXIT=1` |
| `tests/agent` + `rules` + `rulings` | **5 failed, 523 passed, 1 skipped** (443.99s) | `PYTEST_EXIT=1` |
| 뿌리 A (46 파일) | 🔴 **81% 에서 중단** — 30분 한계 | — |
| 뿌리 A (23 파일) | 🔴 **89% 에서 중단** — 30분 한계 | — |
| 뿌리 A1 (12 파일) | 6 failed, 331 passed (1201.01s) | `PYTEST_EXIT=1` |
| 뿌리 A2 (11 파일) | 0 failed | `PYTEST_EXIT=0` |
| 뿌리 A3 (12 파일) | 2 failed, 379 passed (926.15s) | `PYTEST_EXIT=1` |
| 뿌리 A4 (11 파일) | 1 failed, 215 passed, 1 skipped (244.17s) | `PYTEST_EXIT=1` |
| 뿌리 B1 (12 파일) | 7 failed, 320 passed, 8 skipped (955.24s) | `PYTEST_EXIT=1` |
| 뿌리 B2 (11 파일) | 2 failed, 252 passed (148.18s) | `PYTEST_EXIT=1` |
| 뿌리 B3 (12 파일) | 2 failed, 379 passed | `PYTEST_EXIT=1` |
| 뿌리 B4 (11 파일) | 3 failed, 260 passed (492.58s) | `PYTEST_EXIT=1` |

🔴 **하네스가 알려 준 "exit code 0" 을 믿지 않았다.** `tests/engine` 의
1차 실행에서 하네스는 *"completed (exit code 0)"* 을 보냈고 로그에는
`PYTEST_EXIT=1` · **64 failed** 가 적혀 있었다. 로그의 값으로 판단했다.
(같은 모양의 거짓 보고가 보완 이전에 보고서까지 올라간 적이 있다 —
`runtests.sh` 가 그래서 있다.)

### 8.4 처리 뒤 확인 실행 — 묶음별

| 확인 대상 | 결과 | 종료 코드 |
|---|---|---|
| `tests/engine` 전체 (처리 뒤) | **3817 passed** (940.26s) · 실패 0 | `PYTEST_EXIT=0` |
| `tests/engine/test_trigger_window_completion.py` (`deck/opening.py` 수정 반영) | passed | `PYTEST_EXIT=0` |
| `tests/engine/test_empty_chain_fast_window.py` (①) | **19 passed** (40.30s) | `PYTEST_EXIT=0` |
| `tests/engine/test_followup_trigger_integration.py` (②) | **26 passed** | `PYTEST_EXIT=0` |
| 정정한 `tests/agent` 세 파일 | passed | `PYTEST_EXIT=0` |
| 탐색 digest 시험 **21건** (21 파일) | **21 passed** (618.98s) | `PYTEST_EXIT=0` |
| `test_rule_not_implemented_code_audit.py` | passed | `PYTEST_EXIT=0` |
| `test_validation_code_rejection_semantics_audit.py` + `test_unimplemented_rule_semantics_audit.py` | passed | `PYTEST_EXIT=0` |
| `test_dormant_live_gate_equivalence.py` | passed | `PYTEST_EXIT=0` |
| `test_trigger_pipeline_dormant_audit.py` | passed | `PYTEST_EXIT=0` |
| `test_legal_action_engine_boundary_audit.py::test_03` | passed | `PYTEST_EXIT=0` |

🔴 **`tests/engine` 1차 실행은 `deck/opening.py` 수정 **전**의 코드를
돌렸다.** 그 실행이 시작된 뒤에 그 파일을 고쳤기 때문이다. 그래서
`execute_opening` · `combo_messages` 를 쓰는 **유일한** 엔진 시험
(`test_trigger_window_completion.py`) 을 따로 다시 돌려 확인했다 —
위 둘째 줄이다. 🔴 **"전체가 한 번에 통과했다" 로 적지 않는다.**

🔴 **개별 재실행은 회귀를 찾는 도구이고 없음을 증명하는 도구가 아니다.**
위 확인 실행은 "고친 자리가 고쳐졌다" 를 말하고, 묶음 전체의 상태를 말하는
것은 `tests/engine` 의 3817 passed 와 1차 실행의 각 묶음 수다.

### 8.5 🔴 **생략한 것**

| 생략 | 이유 |
|---|---|
| 실제 Discord 접속 | 토큰이 없다. §10 은 저장소 안에서 `combo_messages` 가 돌려주는 **문자열을 잰 것**이고, 실제 봇에 붙여 보는 것은 사용자의 확인이다 |
| 2 링크 체인에서의 후속 유발 | 실제 카드로 둘째 링크를 세울 수단이 범위에 없다 → BLOCKER-F5-3 (§11) |
| 스펠 스피드 2 전체 | `EFFECT_LIBRARY` 에 실행 구현이 있는 함정 4장 · 속공 마법 3장 밖은 후보가 되지 않는다 |
| 뿌리 묶음을 **한 번에** 돌리기 | 🔴 백그라운드 30분 한계에 **두 번 중단**되었다 (81% · 89%). 열두 파일씩 여덟 조각으로 쪼개 전부 끝까지 돌렸고, 조각마다 실제 종료 코드를 §8.3 에 적었다 — **중단된 두 실행의 수는 어디에도 쓰지 않았다** |
| 처리 뒤 `tests/` 뿌리 묶음 **전체** 재실행 | 조각 여덟을 다시 돌리면 또 ~2시간이다. 대신 **고친 자리를 정확히** 다시 돌렸다 (§8.4) — 🔴 "뿌리 묶음 전체가 통과한다" 로 적지 않는다 |
| 상자 D~F (데미지 스텝 · 체인 중 타이밍 세부) | 범위 밖 |

🔴 **빈 후보 목록 · 빈 반복문 · skip 으로 통과한 것을 실행 검증으로
세지 않았다.** 새 시험 45건 중 `skip` 은 **0건**이고, 후보가 비어 있는
것을 재는 시험(`test_d01` · `test_d02` · `test_b02`)은 **먼저 비어
있지 않았음을 확인**한 뒤 비는 것을 센다 (`assert before, "유발 후보가
처음에는 있어야 이 시험이 뜻을 가진다"`).

---

## 9. 기존 실패 · 신규 회귀 · 정정한 기대값

### 9.1 기존 실패 여덟 — 이번 변경이 손대지 않았다

| 시험 | 이유 (기존) |
|---|---|
| `tests/rulings/test_data_audit.py::test_every_repository_card_can_reach_a_cid` | cid 매핑 데이터 |
| `tests/agent/test_opponent_resource_weighting_audit.py::test_07` | 상대 자원 가중 |
| `tests/test_effect_type_quick_audit.py::test_29` | QUICK 집계 |
| `tests/test_event_free_chain_semantic_audit.py::test_27` | EVENT_FREE_CHAIN 집계 |
| `tests/test_korean_overlay_unapplied_audit.py::test_01` `test_13` `test_21` `test_25` | 한국어 오버레이 |

**여덟 개 전부를 실행에서 다시 관측했다** — 한 건도 사라지거나 늘지 않았다.

| 묶음 | 관측한 기존 실패 |
|---|---|
| `tests/agent` + `rules` + `rulings` | `test_data_audit` 1 · `test_opponent_resource_weighting_audit::test_07` 1 |
| 뿌리 A3 | `test_effect_type_quick_audit::test_29` 1 |
| 뿌리 A4 | `test_event_free_chain_semantic_audit::test_27` 1 |
| 뿌리 B1 | `test_korean_overlay_unapplied_audit` 4 |
| **합** | **8** |

### 9.2 신규 회귀 — 묶음별로 세고 전부 처리했다

| 묶음 | 1차 실패 | 기존 | **신규** |
|---|---|---|---|
| `tests/engine` | 64 | 0 | **64** |
| `tests/agent` + `rules` + `rulings` | 5 | 2 | **3** |
| 뿌리 A1 | 6 | 0 | **6** |
| 뿌리 A2 | 0 | 0 | 0 |
| 뿌리 A3 | 2 | 1 | **1** |
| 뿌리 A4 | 1 | 1 | 0 |
| 뿌리 B1 | 7 | 4 | **3** |
| 뿌리 B2 | 2 | 0 | **2** |
| 뿌리 B3 | 2 | 0 | **2** |
| 뿌리 B4 | 3 | 0 | **3** |
| **합** | **92** | **8** | **84** |

🔴 **84건 전부 ①이 더한 필수 절차 때문**이고, 성격이 다섯으로 갈렸다.

| 성격 | 대략 | 어떻게 처리했는가 |
|---|---|---|
| **공용 도구의 계약이 낡았다** | 40 | 도구를 고쳤다 — 시험 본문은 손대지 않았다 (§9.3) |
| **기대값이 확인된 규칙과 충돌한다** | 20 | 기대값을 정정하고 근거를 주석으로 적었다 (§9.5) |
| **프로덕션 결함이 드러났다** | 4 자리 | 프로덕션을 고쳤다 (§9.4) |
| **측정값 핀이 움직였다** | 25 | 두 번 돌려 결정적임을 확인하고 실제 값으로 다시 못박았다 (§9.6 · §9.7) |
| **열거 감사의 좌표·수** | 10 | 전부 `_zone_from_summon` 과 같은 결이고, 그 핀의 설명이 이미 같은 모양을 적어 두었다 (§9.7) |

### 9.3 고친 공용 도구 — 같은 세 줄을 21 파일에 복사하지 않았다

| 도구 | 무엇이 낡았나 |
|---|---|
| `tests/engine/window_helpers.py` (신규) | `pass_fast_window` · `settle`(+`Steps.resolution`) · `act` · `reopen` · `resolve_and_reopen` |
| `tests/conftest.py::settle_chain` | *"마지막 패스의 걸음이 해결의 결과다"* → **해결 걸음** |
| `test_trigger_normal_path_integration.py::_settle` | 상한 2 → 6 · `Steps.resolution` |
| `test_duelstep_accepted_contract.py::settle` | 공용 도구에 위임 |
| `test_trigger_execution_and_timing.py::_decline_window` · `test_trigger_requirement_and_opportunity.py::_decline_window` | 유발 기회만 지나고 멈췄다 → 빠른 효과 기회까지 |
| `test_set_turn_record.py` · `test_set_card_activation.py` · `test_set_trap_timing_audit.py` 의 `set_down` | 세트 둘을 연달아 넣었다 |
| `test_legal_action_candidate_consistency.py::resolve` · `all_states` | 해결 걸음 · "소환권 사용 뒤" 상태를 **열린 판**으로 |
| `test_set_card.py::_drive_to` | `END_PHASE` 만 밟아 빠른 효과 기회에서 멈췄다 → `PASS` 를 먼저 |

🔴 **이것은 테스트 전용 허가가 아니다.** 이 도구들이 하는 일은
`legal_actions` 로 `PASS` 가 올라 있는지 보고 `Duel.apply` 로 넣는 것뿐이다
— 손으로 우선권을 돌리거나 상태를 주입하지 않는다. **사람이 하는 일을
그대로** 한다.

### 9.4 드러난 프로덕션 결함 넷 — 전부 같은 병

보완5 가 "마지막 패스" 와 "해결 걸음" 을 **다른 것**으로 만들었는데, 네
자리가 마지막 걸음을 읽고 있었다. 고치지 않으면 **불발 · 대상 미선택 ·
후보 아님이 전부 한 문장으로 덮인다.**

| 자리 | 무엇이 망가졌나 (실측) |
|---|---|
| `agent/simulation.py::_settle_forced_passes` | `SimulationResult.reason` 이 *"양쪽이 빠른 효과 기회를 지나갔습니다"* — 모든 후보가 같은 이유를 받았다 |
| `integration/autonomy.py::run_trigger` | `TriggerRun.refused` 가 `None` 이 되었다 — **거절이 사라졌다** (`test_autonomous_resolution` 의 d01·d02·d03·c06 이 잡았다) |
| `deck/opening.py::_settle_chain` | `/combo` 보고의 2~5 걸음이 자기 결과 대신 절차 문장을 적었다 (§10) · `resolved` 도 거짓이 되었다 |
| `tests/conftest.py::settle_chain` | 위 둘과 같은 계약 |

🔴 **이 넷은 시험이 잡았다.** `test_f01`(duelstep) · `test_h01` ·
`test_autonomous_resolution` 의 네 건 · `test_g01`/`test_h06` 이 각각
다른 각도에서 같은 병을 가리켰다.

### 9.5 정정한 기대값 — 사용자 §6 이 지목한 셋을 포함

| 시험 | 보완4 의 기대값 | 보완5 의 기대값 | 근거 |
|---|---|---|---|
| `test_bilateral_trigger_order.test_a02` | 양쪽 포기 직후 `priority.is_open is False` + `end_phase` | 기회가 열려 있고 `['pass']` 뿐 · 양측 PASS 뒤 열린다 | 도표의 상자 B·C — 다시 열리는 조건이 **셋**이다 |
| `test_bilateral_trigger_order.test_a03` | 한쪽만 기회면 한 걸음으로 끝 + `end_phase` | **유발 기회**는 한 걸음 · **빠른 효과**는 양측 | 유발 포기 ≠ 빠른 효과 포기 (§4.4) |
| `test_trigger_window_completion.test_b02` | 포기 뒤 `end_phase` 수락 | 차례는 돌아오지만 자리는 빠른 효과 기회 | 같음 |
| `test_trigger_requirement_and_opportunity.test_b01` | 포기 직후 `_end_phase` 성공 | 먼저 기회를 지나야 성공 | 같음 |
| `test_trigger_requirement_and_opportunity.test_b05` | 모름이면 `end_phase` 가 **바로** 오른다 | `PASS` 가 오른다 (= 영영 막히지 않는다, **그 지표는 그대로**) | 같음 |
| `test_priority_response_audit.test_02` | `Duel` 이 `closed` 를 부르지 않는다 · `opened(` 1회 | **그대로 지켰다** — 닫는 일을 `ResponseLoop` 로 옮기고 여는 호출을 한 곳으로 모았다 | 이 시험의 요구가 옳았다 |
| `test_priority_response_audit.test_07` · `test_09` | 해결 뒤 / 소환 뒤 `window is NONE` | `window is RESPONSE` + **체인은 비어 있다** (`RULE-CHAIN-011` 은 그대로 지켜진다) | 도표 |
| `test_activation_response_window.test_c` · `test_h` | 같음 | 같음 | 도표 |
| `test_duelstep_accepted_contract.test_b01` · `test_f01` | 패스의 종류가 **둘** | **셋** — 셋 다 수락이고 `reason`·체인 상태로 갈린다 | §4.4 |
| `test_trigger_normal_path_integration.test_a03` | 해결 뒤 `is_open is False` | 기회 하나가 남는다 | 도표 |
| `test_trigger_activation_location.test_05` | 묘지 도착 자리 관문이 `UNKNOWN` | 관문은 `VALID`, **전체 판정은 여전히 `UNKNOWN`** | §7.4 |

🔴 **assertion 을 지우거나 약하게 하지 않았다.** 전부 **지날 절차를 더하고**
재던 사실은 그대로 두거나 **더 적었다**. 예:

* `test_a02` — 원래 재던 넷을 그대로 두고, 그 앞에 기회의 상태 · 허가 ·
  `END_PHASE` 거절 · 제어권 이동을 **일곱 줄 더** 적었다.
* `test_09` — `window` 하나를 비교하던 자리에 `chain.is_empty` ·
  `ready_to_resolve` 거절 · 상대 허가 `()` 를 더했다 (`RULE-CHAIN-011` 이
  깨지지 않았음을 직접 센다).
* `test_05` — 묘지만 열렸다는 **경계**를 두 층에서 센다 (선언이 먼저
  막는 것과 읽는 쪽이 `None` 을 돌려주는 것).

### 9.6 측정값 핀 — 두 번 돌려 확인하고 실제 값으로

🔴 **어느 것도 약하게 만들지 않았다.** 실제 값으로 다시 못박고, "왜
움직였는가" 를 적고, **움직이지 않은 값**을 함께 세었다.

| 핀 | 전 | 후 | 움직이지 않은 것 |
|---|---|---|---|
| 탐색 결정 수 (21 파일) | 689 | **979** | 순위 로직 한 줄도 바뀌지 않았다 |
| 탐색 digest (8 파일) | `78d35fb4…` | `a864ac09…` | 같음 |
| 무작위 AI 최종 공격력 합 | 13,300 | **12,000** | 규칙 기반의 **70,700** · 붕괴 씨앗 **10 · 15** |
| `SET_SPELL_TRAP` 후보 등장 | 56 | **16** | `SET_MONSTER` 의 **271** · `CHANGE_POSITION` 의 **0** |
| `test_p04` 의 불발 수 | 3 | **1** | 거부 **0건** · 수락 **450** · 남은 체인 **0** |

탐색 쪽 종류별 실측 (979):

```
pass 442 · end_phase 300 · set_spell_trap 76 ·
activate_effect 65 · normal_summon 51 · attack 45
```

늘어난 290 의 정체가 저 `pass` 다 — **빠른 효과 기회를 지나는 걸음**이다.

🔴 **두 번 돌려 같은 값이 나오는 것을 확인했다** (결정적이다). 그러지
않으면 "핀을 실측값으로 갱신했다" 가 "그때 한 번 나온 값으로 맞췄다" 와
구별되지 않는다.

### 9.7 열거 감사 다섯 — 전부 6-V 와 같은 결

`graveyard_zone_for` · `_zone_from_grave` 가 더한 자리를 세는 감사들이다.
🔴 **여섯 핀 모두 `_zone_from_summon` 과 자리 수까지 같다**, 그리고 그
핀들의 설명이 6-V 때 **이미 같은 모양을 적어 두었다**.

| 감사 | 전 → 후 | 그대로인 것 |
|---|---|---|
| `test_rule_not_implemented_code_audit` 문자열 | 88 → **89** | 산문 **15** |
| 같은 감사 코드 자리 | 73 → **74** | — |
| 같은 감사 산문 좌표 | 일곱 자리 밀림 (`trigger.py` +36 · `duel.py` +38) | 성격 · 개수 |
| `test_validation_code_rejection_semantics_audit` 거부 생성 | 60 → **61** | "차이가 13" |
| 같은 감사 코드 자리 | 73 → **74** | — |
| `test_unimplemented_rule_semantics_audit` 언급 | 88 → **89** | — |
| `test_dormant_live_gate_equivalence` `_gate` 자리 | 25 → **28** | `conditional` **1** · `event_gate` 집합 **그대로** |
| `test_trigger_pipeline_dormant_audit` `trigger.py` 줄 | 2,199 → **2,309** | 나머지 두 모듈 **한 줄도** |
| 같은 감사 세 모듈 합 | 3,290 → **3,400** | — |
| 같은 감사 부품 층 `trigger.py` | 840 → **868** | dormant (`duel.py` 는 "trigger" 를 쓰지 않고 `TriggerRegistry` 생성 **0곳**) |
| `test_rule_not_implemented_code_audit` `response.py` 거부 자리 | 476 → **485** | 위반 **13** · 적합 **19** |

🔴 **`_gate` 자리가 셋 늘어난 것이 중요하다.** 6-F 가 한 번 "전달 한 줄"
로 줄였다가 이 감사에 걸려 되돌린 적이 있다 — 그러면 감사가 짝을 구문으로
읽을 수 없게 된다. 보완5 도 **짝을 리터럴로** 적었고, 그 증거가
`conditional` 과 `event_gate` 집합이 **하나도 늘지 않았다**는 것이다.

### 9.8 측정이 내 가설을 부정한 자리 — 셋

🔴 **세 번 가설을 세웠고 세 번 측정이 부정했다.** 셋 다 "산책의 상한에
걸려 덮는 범위가 줄었다" 였다. 적어 두는 이유: 그 가설대로 상한만 올리고
넘어갔다면 **세 자리 모두 틀린 설명이 보고서에 올라갔을 것**이다.

#### ① `test_p04` — 불발 수 3 → 1

🔴 **첫 가설은 "산책의 상한 400 에 닿아 덮는 범위가 줄었다" 였고, 측정이
그것을 부정했다.**

```
limit=400 : accepted=450 refused={} fizzles=1 leftover=0
limit=1200: accepted=450 refused={} fizzles=1 leftover=0
limit=4000: accepted=450 refused={} fizzles=1 leftover=0
   seed 303 → 155 걸음  "듀얼 종료" (8턴 · 덱 소진)
   seed 304 → 155 걸음  "듀얼 종료"
   seed 305 → 161 걸음  "듀얼 종료"
```

상한에 닿지 않는다. 실제 원인은 **산책이 밟는 수의 순서가 달라진 것**이다
(빠른 효과 기회의 `PASS` 가 끼므로 같은 씨앗에서 다른 판이 나온다).

그래서 상한 변경을 **되돌리고** 실제 값으로 다시 못박았다. 그리고 "덮는
범위가 줄지 않았다" 를 추측으로 두지 않고 **새 assertion 셋**으로 세었다:
`accepted == 450` · `leftover == 0` · `finished == 3`(세 판 모두 듀얼의
끝에서 멈췄다).

#### ② `test_legal_action_engine_boundary_audit::test_03` — 간접 지표를 버렸다

6-R 은 *"체인 잠금이 사라졌다"* 를 **다음 두 턴 안에 발동 후보가 한 번이라도
오른다**로 쟀다. 보완5 뒤 그 수가 0 이 되었다.

같은 가설(상한 60)을 세우고 240 으로 올려 측정했고 **같은 0 이 나왔다**.
멈춘 이유는 `over=True` 였다 — 실측 (seed 305):

```
턴 7 MAIN1 에서 시작 … 걸음 15 에서 턴 8 · over=True (덱 소진)
발동 후보 0건 · 체인 잠금 흔적 0건 · chain.is_empty=True
```

즉 궤적이 달라져 **발동할 수 있는 자리에 닿기 전에 듀얼이 끝난다.**

그래서 간접 지표를 버리고 **잠금 자체**를 잰다 — 궤적에 기대지 않으므로
더 강한 주장이다.

```
ActivationTiming.chain_is_open is False
ActivationTimingChecker → valid / OK
   "체인이 비어 있어 스펠 스피드 제약이 걸리지 않습니다."
```

🔴 **빈 결과로 통과하지 않는다** — 관문이 그 이유를 **말로** 적고, 시험이
그 문장을 센다. 🔴 그리고 **이것은 관문 단위 측정이고 통합 검증이 아니라고
주석에 적었다.**

#### ③ `/combo` 의 걸음 수 — 늘 것이라고 생각했다

필수 절차가 늘었으니 걸음 수도 늘 것이라 보고 §10.2 를 그렇게 적으려 했다.
측정은 **5 그대로**였다 — `_settle_chain` 이 이미 `while priority.is_open`
으로 창을 지나고 있었기 때문이다 (§10.2 가 그 이유를 적는다).

---

### 9.9 🔴 시험을 약하게 만들지 않았다 — 세어서 적는다

사용자 §7 이 금지한 것은 *"테스트 삭제 · skip 추가 · assertion 완화로
결함 숨기기"* 다. 세 축을 **전수로** 세었다 (`git diff` 로 측정).

| | 수 |
|---|---|
| 지운 시험 (`def test_`) | **0** |
| 더한 `skip` · `xfail` | **0** |
| 지운 `assert` | **12** |
| 더한 `assert` | **253** |

지운 12개를 **하나씩** 적는다 — 전부 **그 자리에서 교체**되었다.

| 지운 것 | 무엇으로 |
|---|---|
| `seen[SET_SPELL_TRAP] == 56` | `== 16` **+ `> 0`** (더 적었다) |
| `sum(chance) == 13300` | `== 12000` (규칙 기반 70,700 은 그대로 남았다) |
| `priority.window is NONE` ×2 | `is RESPONSE` + `chain.is_empty` + 지나간 뒤 `is NONE` |
| `len(settled) == 2` | `== 4` + 셋째 · 넷째 걸음의 뜻을 재는 **다섯 줄** |
| `fizzles == 3` | `== 1` **+ `accepted == 450` · `leftover == 0` · `finished == 3`** |
| `assert passing…` ×3 | 공용 도구 안의 `assert steps` (같은 사실, 한 자리) |
| `gate.validity is UNKNOWN` + `code is RULE_NOT_IMPLEMENTED` | `is VALID` + `is OK` + **이유 문장 둘** + **전체 판정이 여전히 UNKNOWN** + **묘지 밖 경계 두 층** |
| `[a … END_PHASE]` (b05) | `[a … PASS]` + `not […END_PHASE]` + 지나간 뒤 `_end_phase()` 성공 |

🔴 **그리고 새 시험 45건에 `skip` 이 0건이다.** 후보가 비어 있는 것을 재는
셋(`test_d01` · `test_d02` · `test_b02`)은 **먼저 비어 있지 않았음을
확인**한 뒤 비는 것을 센다.

---

## 10. `/combo` — 필수 절차와 걸음 수

### 10.1 필수 절차 앞에서 끝내지 않는지 확인했다 (§5)

`execute_opening` 의 반복 머리에서 **`PASS` 하나만 남은 자리**를
*"남은 후보는 흐름뿐"* 으로 읽고 멈추던 가지를 고쳤다. 엔진이 그 자리에서
`PASS` 만 허가한 것은 **거쳐야 하는 절차가 남았다**는 뜻이다.

🔴 **`END_PHASE` 는 여기에 들지 않는다** — 그것은 절차가 아니라 **전개를
끝내는 선택**이고, 이 단계가 보려는 것이 전개다.

### 10.2 실제 카드 경로의 걸음 수 — **5 그대로다**

🔴 **절차가 늘었는데 걸음 수가 그대로인 이유를 적는다.**
`execute_opening` 은 행위를 수락한 뒤 `_settle_chain` 을 부르고, 그 함수가
**이미** `while duel.priority.is_open` 으로 창을 지나고 있었다. 보완5 가
연 기회도 같은 반복이 지나간다. 그래서 반복 머리에서는 판이 늘 열려 있고,
10.1 의 가지는 **이 보드에서 밟히지 않는다** (밟히는 자리는 유발 제안이
관문에 걸려 `PASS` 만 남는 경우다).

```
걸음 수 = 5 | stopped_kind = unsupported          ← 보완4 와 같다
  1. P0 normal_summon   기르수      OK  상태변경 ○
  2. P0 activate_effect 69811710:e[0]  OK  상태변경 ○  효과기록 69811710:e[0]
  3. P0 set_spell_trap  클리막스    OK  상태변경 ○
  4. P0 set_spell_trap  성유물에 이르는 열쇠  OK  상태변경 ○
  5. P0 set_spell_trap  성유물로부터의 자각   OK  상태변경 ○
정지: 남은 후보는 흐름뿐이지만 지원하지 않아 후보가 되지 못한 것 1건
      (activate_card [activation-timing (Phase 2-C/2-F)])
```

🔴 **"필수 절차가 추가되어 걸음 수가 바뀌면 설명한다" 는 요구에 대해:
바뀌지 않았고, 바뀌지 않은 이유가 위다. 걸음 수를 유지하려고 절차를
생략하거나 테스트를 왜곡하지 않았다** — `/combo` 가 지나는 `PASS` 는
실제로 늘어났고 (행위마다 둘), 그것이 `ExecutedStep` 에 따로 적히지
않는 것은 보완5 **이전과 같은 설계**다 (`_settle_chain` 이 창을 닫는
걸음을 걸음으로 세지 않는다).

### 10.3 `/combo` 가 한 번 망가졌다 — 고쳤다

`_settle_chain` 이 마지막 걸음을 돌려주어 보고의 걸음마다 절차 문장이
적혔다 (§9.4). 실측 — 고치기 전:

```
✔ 2. P0 activate_effect  이유: 양쪽이 빠른 효과 기회를 지나갔습니다 — 판이 다시 열렸습니다.
✔ 3. P0 set_spell_trap   이유: 양쪽이 빠른 효과 기회를 지나갔습니다 — 판이 다시 열렸습니다.
```

고친 뒤:

```
✔ 1. P0 normal_summon    이유: normal_summon 를 적용했습니다 (1건).
✔ 2. P0 activate_effect  이유: 체인1 P0 69811710:e[0] 를 해결했습니다.
✔ 3. P0 set_spell_trap   이유: set_spell_trap 를 적용했습니다 (1건).
```

---

## 11. BLOCKER 재평가와 분류

### 11.1 🔴 BLOCKER-F4-4 — **해소. 결함이 아니다**

사용자 §8 의 조건: *"묶음 안의 순서가 고르는 쪽의 것이고, 같은 묶음의
등재 사이에 다른 효과가 끼어들지 못하고, 우선권이 넘어가지 않으면,
'한 번에 일괄 등록하지 않는다' 는 이유만으로 BLOCKER 로 남기지 않는다."*

**세 조건을 측정했다.** 같은 묶음에 제안이 둘인 판에서 **두 순서 모두**:

```
[0] 처음 후보 ['69811710:e[1]', '69811710:e[0]'] | 상대 후보 []
  ① 69811710:e[1] 발동 = True | 체인 1 | 창=none holder=None | to_act=0
  남은 내 후보 ['69811710:e[0]']        상대 후보 []
  내 허가 ['activate_effect', 'pass']
  ② 69811710:e[0] 발동 = True | 체인 2
  체인 링크 [(1, '69811710:e[1]'), (2, '69811710:e[0]')]
  해결 전 우선권 holder=1

[1] (순서를 뒤집어 같은 판)
  체인 링크 [(1, '69811710:e[0]'), (2, '69811710:e[1]')]
```

| 조건 | 결과 |
|---|---|
| 묶음 안의 순서가 고르는 쪽의 것인가 | **예** — 두 순서가 그대로 체인 순서가 된다 |
| 같은 묶음의 등재 사이에 다른 효과가 끼어들 수 있는가 | **아니다** — 상대 후보가 끝까지 `[]` |
| 그 사이에 우선권이 넘어가는가 | **아니다** — 창이 닫힌 채(`holder=None`)이고 `to_act` 가 그대로다. 묶음이 끝난 뒤에 `holder=1` 이 된다 |

**→ 해소.** 남는 것은 **인터페이스 모양의 차이**다: 룰북의 *"in any
order"* 를 이 엔진은 후보 목록 + 하나씩 `apply` 로 제공하고, "한 번에
쌓는다" 를 한 번의 호출로 표현하는 API 는 없다. 관측되는 규칙 차이가
없으므로 **정확성 결함이 아니고 미지원 기능이다** (아래 분류).

### 11.2 남은 것 — 네 갈래로 구분한다

사용자 §8 의 요구대로 **성능 비용 · 미지원 기능 · 정확성 결함 · 검증
부족**을 섞지 않는다.

#### 정확성 결함 (규칙이 틀릴 수 있다)

| | 무엇 | 비고 |
|---|---|---|
| **BLOCKER-F5-1** | 「경우」 효과의 **장소 검사**가 없다 (F4-3 그대로) | 2020 마스터 룰의 그 조항에 대한 공식 근거를 찾지 못했다. 🔴 **보완5 가 이 자리를 건드렸다** — `graveyard_zone_for` 가 **발동 시점의 자리**를 읽으므로 반쪽은 메워졌지만, "발동 타이밍에 그 장소에 없으면 발동 불가" 의 일반 검사는 여전히 없다 |
| **BLOCKER-F5-2** | 강제 「때」가 타이밍을 놓친 경우 `UNKNOWN` | 6-AB 이래 그대로. 근거 없음 |

#### 미지원 기능 (규칙은 알지만 수단이 없다)

| | 무엇 |
|---|---|
| **BLOCKER-F5-4** | SEGOC 의 **5~7 순위** (F4-1) — 네 묶음만 구현했다 |
| **BLOCKER-F5-5** | 묘지 **밖** 도착지의 발동 자리 (`UNKNOWN` 유지 — §7.2) |
| **BLOCKER-F5-6** | 스펠 스피드 2 전체 — `EFFECT_LIBRARY` 의 7장 밖은 후보가 되지 않는다 |
| **BLOCKER-F5-7** | 묶음 안 순서를 **한 번의 호출**로 쌓는 API 가 없다 (전 F4-4 — §11.1. 관측되는 규칙 차이는 없다) |
| **BLOCKER-F5-8** | `93920420` 의 실제 효과(특수 소환) 미구현 — ②는 조작을 합성했다 (§6.1) |

#### 검증 부족 (구현은 있으나 재지 못했다)

| | 무엇 |
|---|---|
| **BLOCKER-F5-3** | **2 링크 체인**에서 "남은 링크가 후속 유발보다 먼저 풀린다" 를 직접 재지 못했다 (§6.4). 실제 카드로 둘째 링크를 세울 수단이 범위에 없다. 구조상 끼어들 자리가 없다는 것과 체인 도중 후보가 `[]` 라는 것만 쟀다 |
| **BLOCKER-F5-9** | 창에 사건이 **하나뿐**이다 (F4-6 그대로) — 어휘 판정(「때/경우」)이 실행 경로에서 답을 가르지 않는다 |
| **BLOCKER-F5-10** | 비공개 영역(덱 · 패) 유발의 순서 — 조사만 했다 (F4-2) |
| **BLOCKER-F5-11** | 실제 Discord 접속 — 토큰 없음 (§10 은 문자열 검사다) |

#### 성능 비용 (정확성과 무관)

| | 무엇 |
|---|---|
| **BLOCKER-F5-12** | `_window_can_act` 가 강제 묶음일 때 관문을 **두 번** 돌린다 (F4-5). 임의 묶음에서는 돌리지 않으므로 실제 경로의 비용은 0 |
| **BLOCKER-F5-13** | 판을 바꾸는 행위마다 `PASS` 둘이 더 필요하다 — 🔴 **이것은 비용이지 결함이 아니다.** 공식 도표가 요구하는 절차이고, 탐색의 깊이 1 이 그만큼 길어진다 |

### 11.3 보완4 의 BLOCKER 와 대조

| 보완4 | 현재 |
|---|---|
| F4-1 — SEGOC 5~7 순위 | **그대로** → F5-4 |
| F4-2 — 비공개 영역 유발을 조사만 했다 | **그대로** → F5-10 |
| F4-3 — 「경우」 효과의 장소 검사 | **부분** → F5-1 (반쪽을 메웠다) |
| F4-4 — 묶음 안의 순서를 묻지 않는다 | 🔴 **해소 (결함 아님)** → F5-7 (미지원 기능) |
| F4-5 — 관문을 두 번 돌린다 | **그대로** → F5-12 (성능) |
| F4-6 — 창에 사건이 하나뿐 | **그대로** → F5-9 |
| F3-2 — ③이 합성 효과로만 통과한다 | 🔴 **부분 해소** — ①-7 은 **실제 카드**(5915629)로 통과한다. ②는 조작만 합성이다 (§6.1) → F5-8 |
| F3-6 — 묘지로 보내는 효과 둘의 둘째가 `UNKNOWN` | **그대로** (엔진의 보수적 답이고 우회하지 않았다) |

---

## 12. 🔴 보완4 의 표현 정정 고지

사용자 §9 가 지목한 셋이다.

### 12.1 *"유발 포기 뒤 흐름이 다시 열린다"*

보완4 보고서 §4.2 · §4.4 와 `test_a02` · `test_a03` ·
`test_trigger_window_completion.test_b02` 가 **유발 기회를 지나간 것**을
**판이 열린 상태로 돌아간 것**과 같이 적었다.

🔴 **틀렸다.** 같은 공식 도표를 근거로 들면서 그 도표의 가운데를
건너뛴 것이다 — *"If there is no effect that can be triggered."* 는 턴
플레이어를 **상자 B** 로 보내고, 판이 다시 열리는 조건은 **셋**이다.
"체인이 없다" 는 그 중 하나일 뿐이다.

정정: 유발 기회가 닫히면 **빠른 효과 기회**가 열리고, 양측이 지나가야
판이 열린다. 세 시험의 기대값을 정정했고 (§9.5) 근거를 주석으로 적었다.

### 12.2 *"내부 순번 판정을 후속 사건 통합 검증 완료로 적었다"*

보완4 보고서가 `_window_admits` 의 `sequence` / `chain_floor` 비교와
`test_b04b` 를 근거로 **"체인 해결 중 발생한 사건의 후속 유발을 처리한다"**
쪽으로 읽히게 적었다.

🔴 **그것은 내부 경계 검증이었다.** 재던 것은 "사건 번호가 체인 바닥보다
크면 그 창에서 열지 않는다" 이고, **실제 사건이 실제 후보가 되어 실제로
해결되는 한 바퀴는 재지 않았다.** 그 증거: 보완5 가 그 한 바퀴를 재려
하자 **두 군데가 막고 있었다** (§2.2) — 통합이 통하고 있었다면 막힐 것이
없다.

정정: 그 부류의 시험은 **내부 경계 검증**이고, 통합 검증은 보완5 의
`test_followup_trigger_integration.py` 가 처음 한 것이다. 두 파일의
머리말이 그 구분을 적는다. (`test_c01` 류의 내부 경계 검증은 유지한다 —
없애면 경계가 안 지켜져도 모른다.)

### 12.3 *"같은 묶음의 순차 등재를 BLOCKER 로 분류했다"*

보완4 가 BLOCKER-F4-4 를 *"묶음 안의 순서를 정책에게 묻지 않는다"* 로
적었다.

🔴 **제목이 사실과 달랐다.** 엔진은 그 선택을 **후보 목록으로 묻고**
있었고 (`test_b06` 이 이미 세고 있었다), 다른 것은 "한 번에 쌓는 API 가
없다" 뿐이다. 그리고 성능 비용 · 미지원 기능 · 정확성 결함 · 검증
부족을 구분하지 않고 한 목록에 섞어 두었다.

정정: §11.1 이 세 조건을 측정해 **해소 (결함 아님)** 로 분류하고,
§11.2 가 남은 것을 네 갈래로 나눈다.

### 12.4 보완5 자신에 대해

🔴 **이 보고서에 자기 커밋 해시를 넣으려고 커밋을 반복하지 않았다.**
§1 의 최종 HEAD `981b083` 은 **이 보고서 앞의** 코드 커밋이고, 보고서는
그 뒤에 한 번 커밋된다.

🔴 **토큰 없는 응답 생성 검사를 실제 Discord 접속 검증이라고 적지
않았다** — §10 · §8.5 가 그것을 명시한다.

🔴 **다음 Phase 를 시작하지 않았다.**

---

## 13. 사용자 확인 방법과 예상 결과

🔴 **실제 Discord 접속 검증이 아니다.** 아래는 저장소 안에서
`combo_messages` 가 돌려주는 **문자열을 잰 것**이다.

봇을 띄우고 (`DISCORD_TOKEN` 필요) 보완4 와 **같은 입력**을 보낸다.

```
/combo
  hand:   69811710, 703897, 2930675, 12989604, 93920420
  recipe: 69811710 x3, 703897 x3, 2930675 x3, 12989604 x3, 93920420 x3,
          21441617 x3, 4055337 x3, 57835716 x3, 94046012 x3, 26845680 x3,
          29666221 x3, 47171541 x3, 55051920 x3, 90351981 x1
```

### 예상 결과 (측정값)

메시지 **4개 · 6,189자**. 보완4 와 **같은 모양**이고 걸음 수도 5 그대로다.

```
✅ 엔진이 실제로 5걸음 실행했습니다 (효과 해결 1걸음 · 상태 변경 5걸음).
🔴 고른 방식은 검증용 기준점입니다 — first_meaningful · first-permitted.
   최선의 전개가 아닙니다.
🔴 엔진이 지원하지 않아 후보가 되지 못한 것이 1건 있었습니다.
🔴 멈춘 자리가 미지원 때문입니다 — 정상 전개 종료가 아닙니다.

  ✔ 1. P0 normal_summon    기르수       이유: normal_summon 를 적용했습니다 (1건).
  ✔ 2. P0 activate_effect  69811710:e[0] 이유: 체인1 P0 69811710:e[0] 를 해결했습니다.
  ✔ 3. P0 set_spell_trap   클리막스     이유: set_spell_trap 를 적용했습니다 (1건).
  ✔ 4. P0 set_spell_trap   성유물에 이르는 열쇠
  ✔ 5. P0 set_spell_trap   성유물로부터의 자각
```

거절 경로 (패의 매수가 덱 보유 매수를 넘는다):

```
/combo hand: 69811710, 69811710, 69811710, 69811710, 93920420  (recipe 동일)
```

메시지 **1개 · 1,740자**.

```
🔴 실행하지 않았습니다 — 입력 검증을 통과하지 못했습니다.
  🔴 위반 1건
    - 패의 매수가 덱 보유 매수 이내인가: 기르수 [69811710]: 패 4장 > 덱 3장
```

🔴 **`/combo` 의 출력에 보완5 의 빠른 효과 기회가 보이지 않는다.**
`_settle_chain` 이 그 절차를 지나고 걸음으로 세지 않기 때문이다 (§10.2).
사용자가 그 절차를 눈으로 보려면 `tests/engine/test_empty_chain_fast_window.py`
의 이유 문장들이 그것을 적는다.

---

## 14. 다음에 올 것 — **시작하지 않았다**

| 후보 | 이유 |
|---|---|
| BLOCKER-F5-3 의 2 링크 검증 | 실제 카드로 둘째 링크를 세울 수단이 필요하다 — `EFFECT_LIBRARY` 를 넓히는 일이고 별개의 범위다 |
| BLOCKER-F5-1 「경우」 장소 검사 | 공식 근거를 더 찾아야 한다 |
| BLOCKER-F5-4 SEGOC 5~7 순위 | 공식 근거가 TCG 도표에 없다 |
| §7 의 변경을 되돌릴지 | **사용자의 판단**이다 (`9395375` 하나) |

🔴 **다음 Phase 는 자동으로 시작하지 않는다.**
