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
| 최종 HEAD | `ae5f15f` (이 보고서 커밋은 그 뒤에 온다 — §12) |
| 브랜치 | `claude/pensive-goodall-te1egy` |

커밋 셋이고 **되돌리는 단위**로 끊었다.

| 커밋 | 무엇 |
|---|---|
| `9395375` | ② — `graveyard_zone_for` (§7 의 범위 밖 변경이 **여기 하나에만** 있다) |
| `e43a1fd` | ① — 빈 체인의 빠른 효과 기회 + 정정한 기대값 64건 |
| `ae5f15f` | `/combo` 의 걸음마다 자기 결과를 적는다 |

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

