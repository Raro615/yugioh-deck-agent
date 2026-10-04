# Phase 3-E-19 — EVENT_PHASE Modifier / Timing Semantics Audit

## 1. HEAD / Base

| | |
|---|---|
| Base (지시) | `d605558` — Phase 3-E-18 |
| 실제 HEAD | `d605558` (동일) |
| Working tree | 감사 시작 시 clean (`git status --short` 비어 있음) |
| Branch | `claude/pensive-goodall-te1egy` |

Base 차이 없음. `git diff -- engine/ agent/ core/ analysis/ sources/` 도 비어 있었다.

## 2. BLOCKER

**NO.**

## 3. Engine Change

**B. ENGINE CHANGE NOT REQUIRED.**

이 Phase 는 `engine/` · `agent/` · `core/` · `analysis/` · `sources/` 를 **한 줄도
바꾸지 않았다.** 추가한 것은 `tests/test_event_phase_semantics_audit.py` (18개)와
이 문서뿐이다.

## 4. Repository Audit

실제 위치 (HEAD `d605558` 기준):

| 대상 | 위치 | 사실 |
|---|---|---|
| 공식 상수 | `data/constants/constant.lua:708-709` · `:227-236` | `EVENT_PHASE=0x1000` · `EVENT_PHASE_START=0x2000` · `PHASE_DRAW=0x1` … `PHASE_END=0x200` |
| 원문 진입 | `sources/lua_loader.py:149-156` | `c*.lua` 를 정규식으로 훑어 create/clone/setter 를 위치 순으로 모은다 |
| SetCode 파싱 | `sources/lua_loader.py:189-196` | `_RE_EVENT`(`:47`) 가 **첫 이름만** 찾는다 |
| `EffectSpec.code` | `core/card_model.py:50` | `str | None`. 수정자를 담을 자리가 없다 |
| 파일 단위 목록 | `sources/lua_loader.py:231` | `trigger_events` 도 `_RE_EVENT` 기반 + **중복 제거**(`:75`) |
| 분석 복사 | `analysis/effect_analyzer.py:375` · `:475` | `effect.trigger_event = spec.code` (그대로 복사) |
| 캐시 | `core/card_repository.py:183-185` | `data/cache/lua_scripts.json`. 값을 JSON 왕복만 한다 |
| 페이즈 어휘 | `engine/vocabulary.py:184-209` | `Phase` enum + `TURN_PHASE_ORDER` (배틀 내부 스텝 제외) |
| 페이즈 전이 | `engine/turn_progression.py` | `PhaseChanged` delta 만 남긴다. `engine.trigger` 를 **import 하지 않는다** |
| `PhaseChanged` | `engine/effect/delta.py:383-402` | `from_phase` · `to_phase` 를 **갖고 있다** |
| 사건 변환 | `engine/trigger.py:260-264` | `PhaseChanged` → `TimingEvent(PHASE_CHANGED, delta=delta)` |
| 선언 | `engine/trigger.py:425-497` | `TriggerSpec` — 필터는 `operations`/`from_zones`/`to_zones` (전부 `CARD_MOVED` 전용) |
| 통합 계층 | `engine/timing.py:269-` `TimingCoordinator` | production 에서 **import 하는 모듈이 없다** |
| 듀얼 루프 | `engine/duel.py:56-82` | `engine.timing`/`engine.trigger_chain` 을 import 하지 않는다. 파일에 `trigger` 라는 글자가 없다 |
| 검색 | `core/card_search.py:322` → `core/card_model.py:337` | `has_effect_code()` 가 `EVENT_*` 를 본다 — **유일한 소비자**이고 듀얼 엔진이 아니다 |
| 규칙 | `data/rules/structured/sd-rulebook-en-v10.json` `phases[]` | 페이즈마다 별개 항목 · 별개 규칙 ID (END → `RULE-TURN-007`, STANDBY → `RULE-TURN-003`) |

§2 의 10개 질문에 대한 답:

1. 원문 진입 — `LuaScriptSource` → `parse_lua_source`.
2. 파싱 — `lua_loader.py:189` `elif setter == "Code":`.
3. `EffectSpec.code` 구성 — 같은 자리. 정규식 첫 그룹.
4. 버려지는 수정자 — **그렇다.** `+PHASE_END` 같은 꼬리가 사라진다.
5. 분석의 별도 표현 — **없다.** `EffectAnalysis.raw` 는 `EffectSpec` **객체**이고,
   `ActivationCondition.raw` 는 `SetCondition` 함수 원문이다 (SetCode 가 아니다).
6. Engine 이 `EffectSpec.code` 를 읽는가 — **아니다** (3-E-18 에서 확정, 재확인).
7. Engine 이 `trigger_events` 를 읽는가 — **아니다.** 문자열 자체가 없다.
8. `PHASE_END`/`PHASE_START` 를 읽는 production 경로 — **없다.**
9. 테스트만 읽는가 — `EVENT_PHASE` 는 감사 테스트 2개(E-18 · E-19)에만 나온다.
10. EVENT_PHASE 에 의존하는 카드 실행 경로 — **없다.** 등록된 `TriggerSpec` 이 0개다.

## 5. EVENT_PHASE Corpus

측정 방법: 파서의 이벤트 루프를 그대로 재현해 **묶인 효과 블록에 붙은**
`SetCode` 호출만 센다 (파일 전체 정규식은 묶이지 않은 변수와 함수마다 재사용되는
`e1` 때문에 수가 틀린다 — 3-E-18 이 E-17 의 숫자를 바로잡은 이유). 전수:
`c*.lua` **12,702개**.

| 인자 원문 | 건수 | 파서 결과 |
|---|---|---|
| `EVENT_PHASE+PHASE_END` | 751 | `EVENT_PHASE` |
| `EVENT_PHASE\|PHASE_STANDBY` | 394 | `EVENT_PHASE` |
| `EVENT_PHASE\|PHASE_BATTLE` | 131 | `EVENT_PHASE` |
| `EVENT_PHASE\|PHASE_BATTLE_START` | 39 | `EVENT_PHASE` |
| `EVENT_PHASE+PHASE_BATTLE` | 5 | `EVENT_PHASE` |
| `EVENT_PHASE+PHASE_STANDBY` | 4 | `EVENT_PHASE` |
| `EVENT_PHASE\|PHASE_DRAW` | 2 | `EVENT_PHASE` |
| `EVENT_PHASE_START\|PHASE_DRAW` | 3 | `EVENT_PHASE_START` |
| `EVENT_PHASE_START\|PHASE_STANDBY` | 3 | `EVENT_PHASE_START` |
| `EVENT_PHASE_START\|PHASE_MAIN1` | 2 | `EVENT_PHASE_START` |
| `EVENT_PHASE_START+PHASE_DRAW` | 1 | `EVENT_PHASE_START` |
| `EVENT_PHASE_START\|PHASE_BATTLE_START` | 1 | `EVENT_PHASE_START` |
| **합계** | **1,336** | 이름 **2개** |

§3 의 분류:

| 분류 | 건수 |
|---|---|
| A `EVENT_PHASE` 단독 | **0** |
| B `EVENT_PHASE + PHASE_START` | **0** — `PHASE_START` 라는 상수 자체가 없다 |
| C `+ PHASE_END` | 751 |
| D 다른 페이즈 비트 | 585 (STANDBY 401 · BATTLE 136 · BATTLE_START 40 · DRAW 6 · MAIN1 2) |
| D′ 페이즈 비트 2개 이상 | 0 |
| E 한 블록에 `SetCode` 2회 이상(EVENT_PHASE 포함) | 0 |
| F 유발과 무관한 `PHASE_*` 사용 | `SetReset` **4,269** · `SetCondition` 55 · `SetOperation` 7 |
| G 파서가 못 읽은 EVENT_PHASE (묶이지 않은 변수) | **0** |

모델 쪽:

* `code == "EVENT_PHASE"` 인 spec **1,329개** + `"EVENT_PHASE_START"` **10개** = **1,339개**
  (= 자기 호출 1,336 + `Clone()` 으로 물려받은 3).
* 그 1,339개의 `effect_types` 분포: `CONTINUOUS+FIELD` 520 · `FIELD+TRIGGER_O` 452 ·
  `FIELD+TRIGGER_F` 365 · 기타 2. 즉 **실제로 유발/지속 선언이다** (빈도로 추론한
  것이 아니라 블록의 `SetType` 을 읽은 것이다).
* **한 카드 안에 서로 다른 페이즈 유발을 둘 이상 가진 카드: 55장.**

E-18 과의 정합: E-18 은 "한정자를 버린 블록 1,430개" 중 `EVENT_PHASE` 계열
1,326개라고 적었다. 이번 전수는 `EVENT_PHASE` 1,326 + `EVENT_PHASE_START` 10 =
1,336 이다. **모순이 아니다** — E-18 은 `EVENT_PHASE` 만 셌다.

## 6. Source Semantics

**수정자는 이름의 장식이 아니라 사건 번호의 일부다.** 공식 상수가 그렇게 말한다:

```
EVENT_PHASE = 0x1000        PHASE_STANDBY = 0x2     PHASE_END = 0x200
EVENT_PHASE+PHASE_END   = 0x1200
EVENT_PHASE+PHASE_STANDBY = 0x1002
```

* `+` 와 `|` 는 비트가 겹치지 않으므로 Lua 에서 **같은 값**이다 → 모양 12개가
  사건 번호 **9개**가 된다.
* `EVENT_PHASE`(0x1000) 자체는 **원문에서 한 번도 쓰이지 않는다.** 그러므로 모델의
  `"EVENT_PHASE"` 는 원문에 존재하지 않는 값이고, "모든 페이즈" 가 아니라
  **"어느 페이즈인지 적지 못했다"** 를 뜻한다.
* `EVENT_PHASE_START`(0x2000) 는 "EVENT_PHASE + PHASE_START" 가 **아니다** —
  독립된 사건 상수다. 지시문에 예로 적힌 `SetCode(EVENT_PHASE + PHASE_START)` 는
  **corpus 에 0건**이고, `PHASE_START` 라는 상수도 없다. (§19.4 대로 이름에서
  의미를 추론하지 않고 상수 파일을 읽은 결과다.)

규칙 계층의 근거 — 공식 룰북(구조화)은 페이즈마다 별개 항목을 갖고, 엔드
페이즈와 스탠바이 페이즈는 **순서도 규칙 ID 도 다르다** (`RULE-TURN-007` vs
`RULE-TURN-003`). 두 항목 모두 "이 페이즈에 발동/해결하는 효과" 를 자기
main_actions 에 적는다. 따라서 **게임 규칙 계층에서도 두 시점은 다르다.**

주의 — 같은 `PHASE_*` 토큰이 **유발이 아닌 뜻**으로 더 많이 쓰인다:
`SetReset(RESET_PHASE|PHASE_END)` 는 "엔드 페이즈까지 지속" 이라는 **리셋 시점**
이며 4,269건이다 (SetCode 쪽 1,336건의 3배). "PHASE 가 보이니 페이즈 유발" 로
읽으면 틀린다.

## 7. Parser / EffectSpec Data Flow

| 단계 | EVENT_PHASE 값 | 수정자 | 비고 |
|---|---|---|---|
| Lua 원문 | `EVENT_PHASE+PHASE_END` | **있다** | 파일은 그대로 보존된다 |
| Parser (`:189`) | `_RE_EVENT` 첫 그룹 | **버린다** | `\bEVENT_(\w+)` 가 `+` 앞에서 멈춘다 |
| `EffectSpec.code` | `"EVENT_PHASE"` | 없다 | 담을 필드가 없다 |
| `LuaScriptInfo.trigger_events` | `["EVENT_PHASE"]` | 없다 | **중복까지 제거**된다 |
| Repository/cache | 동일 | 없다 | JSON 왕복만 |
| Analysis | `trigger_event="EVENT_PHASE"` | 없다 | `raw` 는 `SetCondition` 원문 |
| Engine | **읽지 않는다** | — | 문자열 자체가 없다 |

## 8. Modifier Preservation / Loss

* **모델 안에서는 어디에도 남지 않는다.** `trigger_events` · `effect_codes` ·
  `locations` · `categories` · `effect_types` · `ranges` · `target_ranges` ·
  `properties` · `count_limit` 를 전부 확인했다 — `PHASE_` 로 시작하는 값이 하나도
  없다 (1,339개 전수 확인).
* **원문에는 남아 있다.** `c*.lua` 는 원본 데이터로 보존되므로 정보는 **파괴된
  것이 아니라 모델에 올라오지 않은 것**이다. 필요해지면 재파싱으로 복구할 수 있다.
* 손실 분류 (§5 의 1~4): **2. 유용하지만 현재 authoritative 하지 않은 metadata.**
  (3 "future-required" 에 가깝지만, 소비자가 생길 때 표현 형태도 함께 정해야 하므로
  지금 보존 형식을 못 박는 것은 이르다. 4 "current production blocker" 는 아니다 —
  §10 참조.)

왜 "parser bug" 가 아닌가: 파서가 **약속한 것**은 "`SetCode` 인자의 상수 이름"
이고, 그 이름은 실제로 `EVENT_PHASE` 다. 3-E-18 이 고친 것은 **틀린 값을 주장**
하던 자리였고(Clone 이 물려준 값이 남았다), 이것은 **덜 읽은 값**이다. 게다가
보존해도 **넣을 곳이 없다** (§10 의 `TriggerSpec`).

## 9. Representative Cases

| | 사례 | RAW → PARSER → EffectSpec → ANALYSIS → ENGINE | 분류 |
|---|---|---|---|
| A | `EVENT_PHASE` 단독 | **원문에 없음** → (모델에서만 1,339개 등장) → `"EVENT_PHASE"` → 복사 → 읽지 않음 | COLLAPSED (원문에 없는 값) |
| B | `EVENT_PHASE+PHASE_START` | **존재하지 않음** (`PHASE_START` 상수 없음) | N/A |
| B′ | `c10960419` `e1:SetCode(EVENT_PHASE_START+PHASE_DRAW)` | → `"EVENT_PHASE_START"` → 복사 → 읽지 않음 | COLLAPSED (어느 페이즈인지 소실) |
| C | `c10000000` `e6:SetCode(EVENT_PHASE+PHASE_END)` (`FIELD+TRIGGER_F`) | → `"EVENT_PHASE"` → `trigger_event="EVENT_PHASE"` → 읽지 않음 | COLLAPSED · NOT USED |
| D | `SetReset(RESET_PHASE\|PHASE_END)` 4,269건 | → 모델에 아예 담기지 않음 | NOT USED (유발이 아니다 — 무해) |
| E | `c23846921` `e1:+PHASE_END` **와** `e2:\|PHASE_DRAW` | → 두 `code` 가 **글자까지 같다** · `trigger_events` 는 중복 제거로 **1개** → 읽지 않음 | SEMANTICALLY REQUIRED (소비자가 생기면) · NOT CURRENTLY REQUIRED |
| F | 같은 `c23846921` 를 듀얼에 올렸을 때 | 엔진은 `EffectRef` 로 **지목**만 하고 `code` 를 읽지 않음 | NOT USED |

(카드 식별자만 적는다. 카드 텍스트는 인용하지 않는다.)

## 10. Production Engine Impact

**현재 production Engine 은 EVENT_PHASE 수정자 정보에 의존하지 않는다.**

증거 (전부 테스트로 고정):

1. `engine/` · `agent/` 전체에 `EVENT_PHASE` · `PHASE_END` · `PHASE_START` ·
   `trigger_events` 라는 **문자열이 하나도 없다** (주석 포함).
2. `TriggerSpec` 에 **페이즈를 적을 필드가 없다.** 필터 3개는 `CARD_MOVED`
   전용이고 `__post_init__` 이 다른 시점에 걸면 `TriggerError` 를 던진다. 따라서
   `point=PHASE_CHANGED` 선언은 `Phase.END` 전이와 `Phase.STANDBY` 전이를
   **똑같이 통과시킨다** (`spec.matches()` 가 둘 다 `True`).
3. 사건 쪽에는 페이즈가 **있다** — `TimingEvent(PHASE_CHANGED).delta.to_phase`.
   비대칭이다: 사건은 알고 선언은 못 묻는다.
4. **production 에 등록된 `TriggerSpec` 이 0개다** (ADR-006: 손으로 등록).
   `TriggerSpec(` 를 생성하는 코드는 `engine/trigger.py`(정의)와 테스트뿐이다.
5. 트리거→체인 통합 계층(`engine/timing.py` `TimingCoordinator`)을 import 하는
   production 모듈이 **없다**. `engine/duel.py` 에는 `trigger` 라는 글자가 없다.
6. `TurnProgressor` 는 `PhaseChanged` 만 남기고 `engine.trigger` 를 import 하지
   않는다 — 자기 문서에 "트리거도 만들지 않는다" 고 적어 두었고 코드가 그대로다.
7. `ActivationTiming.point` 는 값을 **싣기만** 하고 어떤 판정에도 쓰이지 않는다
   (`canonical_state`/`to_dict` 에만 등장).

유일한 실제 소비자는 **듀얼 엔진이 아니라 카드 검색**이다:
`SearchFilter.effect_codes` → `Card.has_effect_code()`. 거기서는 collapse 가
"엔드 페이즈 유발만 찾기" 를 불가능하게 만든다. 다만 그 필터를 채우는 CLI /
자연어 질의 경로는 아직 없다 (프로그램 API 로만 닿는다). **이것은 검색 기능의
표현력 문제이고 듀얼 규칙의 정확성 문제가 아니다.**

## 11. STRUCTURAL-34 Impact

**STRUCTURAL-34 unaffected.**

`EVENT_PHASE` 수정자 소실은 다음 어디에도 닿지 않는다:

| 대상 | 영향 | 이유 |
|---|---|---|
| response seat | 없음 | `PriorityState`/`ResponseState` 는 사건 정체를 보지 않는다 |
| priority holder | 없음 | `TurnProgressor` 는 `PriorityState` 를 읽지도 쓰지도 않는다 |
| phase-change priority | 없음 | 아직 규칙이 없다 (`requires_priority_update` 만 남긴다) |
| AFTER_CHAIN_RULE | 없음 | 체인 종료 후 처리이고 사건 정체와 무관 |
| response candidate generation | 없음 | `ActivationTimingChecker` 는 chain/priority/speed/set_this_turn 만 본다 |
| activation timing | 없음 | 위와 같다. `point` 는 metadata 로만 실린다 |
| turn_player | 없음 | `TurnState` 가 소유 |

"phase" 라는 낱말이 같다는 이유로 우선권 문제라고 부르지 않는다.

## 12. Observation Boundary

| 질문 | 답 |
|---|---|
| hidden card identity 를 노출하는가 | **아니다.** 수정자는 스크립트 metadata 이고 관측에 나가지 않는다 |
| GameStateView 가 노출해야 하는가 | **아니다.** 관측에는 "지금 어느 페이즈인가"(`GameStateView.phase`)만 있고 그것은 공개 정보다 |
| evaluation 이 필요한가 | 아니다 |
| search ranking 이 필요한가 | 아니다 |
| simulation 이 필요한가 | 아니다 |

**GameStateView 변경 = NO.** hidden information leak = NO.
`engine/game_state_view.py` 에 `EVENT_` · `trigger` 라는 글자가 없다 (테스트로 고정).

## 13. Evaluation / Search Impact

`agent/evaluation.py` · `agent/search.py` · `agent/policy.py` ·
`agent/simulation.py` 에 `EVENT_PHASE` · `PHASE_END` · `trigger_events` ·
`EffectSpec` 이 **없다**.

* Evaluation change = **0**
* Search change = **0**
* Ranking change = **0**

페이즈 가중치 · 사건별 heuristic · 카드 이름 로직을 **더하지 않았다.**

## 14. Tests

신규: `tests/test_event_phase_semantics_audit.py` — **18개**.

| # | 검증 |
|---|---|
| 01 | 수정자는 사건 번호의 일부다 (공식 상수 값) · `PHASE_START` 상수는 없다 |
| 02 | 공식 룰북이 페이즈를 별개 시점으로 다룬다 (별개 규칙 ID) |
| 03 | 파서는 첫 이름만 남긴다 · `+`/`\|` 를 구분하지 않는다 |
| 04 | 수정자가 모델 어느 필드에도 남지 않는다 · `trigger_events` 는 중복까지 지운다 |
| 05 | 같은 `PHASE_*` 가 `SetReset` 에서는 유발이 아니다 |
| 06 | **전수**: `EVENT_PHASE` 단독 0건 · 모든 호출이 페이즈 비트를 갖는다 |
| 07 | 모양 12개 → 사건 번호 9개 → 모델 이름 2개 |
| 08 | 보고서의 수를 다시 센다 (하한으로 고정 — 데이터가 늘 수 있다) |
| 09 | 한 카드 안의 두 페이즈 유발이 같은 값이 된다 (55장) |
| 10 | `engine/`·`agent/` 에 그 이름이 없다 |
| 11 | `TriggerSpec` 은 "어느 페이즈" 를 적을 수 없고 둘을 구분하지 못한다 |
| 12 | production 에 등록된 `TriggerSpec` 이 0개다 |
| 13 | 듀얼 루프가 트리거를 모으지 않는다 (`timing.py` 미연결) |
| 14 | `TurnProgressor` 가 의도적으로 사건을 만들지 않는다 (import 로 확인) |
| 15 | 관측은 현재 페이즈만 싣는다 |
| 16 | 평가·탐색에 없다 |
| 17 | **UNKNOWN ≠ ALL** — 수정자 없음을 "모든 페이즈" 로 바꾸는 변환이 없다 |
| 18 | **UNKNOWN ≠ NONE** — `"EVENT_PHASE"` 는 "유발 없음" 이 아니다 |

고의 위반 4건 — **전부 잡혔다** (넣고 → 실패 확인 → `git checkout` 으로 되돌림):

| | 위반 | 잡은 테스트 |
|---|---|---|
| A | 파서가 수정자를 보존한다 | 03 · 07 · 09 · 18 |
| B | `TriggerSpec` 에 페이즈 필터를 더한다 | 11 |
| C | 엔진 모듈이 `EVENT_PHASE` 를 언급한다 | 10 · 17 |
| D | production 에서 `TriggerSpec` 을 등록한다 | 12 |

전체: **3565 passed · 4 skipped · 0 failed.**

* Regression = **0**
* 신규 = 18 · 수정 = **0** · 삭제 = **0** · skip 증가 = **0**

## 15. Performance

| | 값 |
|---|---|
| 감사 테스트 파일 단독 (캐시 전) | 3.9s |
| 감사 테스트 파일 단독 (캐시 후) | **1.8s** — 전수 순회 4회 → 1회 |
| 전체 pytest · 3-E-18 | 346s (그 전 3-E-17 은 365s) |
| 전체 pytest · 3-E-19 (캐시 전) | 364s |
| 전체 pytest · 3-E-19 (캐시 후) | **362s** |

늘어난 유일한 작업은 전수 순회(`c*.lua` 12,702개)이고, 그것은 **단독 측정으로
1.8초**다. 전체 시간 차이(+16s)는 그 1.8초로 설명되지 않으며, 지금까지 관측한
전체 실행 시간의 폭(340~365s) 안에 있다 — **새 테스트의 비용이라고 주장하지
않는다.** 캐시는 테스트 모듈 안에서만 썼고 production 코드에는 넣지 않았다.

## 16. Structural TODO Status

새 STRUCTURAL ID 를 **만들지 않았다.** §13 의 5개 조건으로 따진 결과:

| 조건 | 충족 | 근거 |
|---|---|---|
| 1. 의미 정보가 authoritative 한가 | **YES** | 상수 값 + 공식 룰북의 페이즈 구분 |
| 2. 현재 architecture 가 그것을 요구하는가 | **NO** | 읽는 production 경로가 없다 |
| 3. 기존 production 경로가 표현/실행하지 못하는가 | 해당 없음 | 그 경로 자체가 아직 없다 |
| 4. 없는 표현이 현재 엔진의 유효한 동작을 막는가 | **NO** | 등록된 트리거 선언이 0개다 |
| 5. 나중에 처리할 수 없는가 | **NO** | 원문이 보존되어 있어 재파싱으로 복구된다 |

→ **감사 결과(audit finding)로만 기록한다.**

기존 TODO 상태 (모두 **그대로**):

| ID | 상태 |
|---|---|
| STRUCTURAL-34 | 유지 — unaffected (§11) |
| STRUCTURAL-124 / -128 / -131 / -133 | 유지 |
| STRUCTURAL-134 | RESOLVED 유지 |
| SET_ACTIVATION_MISSING | RESOLVED 유지 |
| SET_ACTIVATION_TIMING | 유지 — 이 감사가 건드리지 않았다 |
| SET_ACTIVATION_EXECUTION | 유지 |
| SET_CARD_EFFECT_EXECUTION | 유지 |
| AFTER_CHAIN_RULE | 유지 — unaffected |
| UNRESOLVED_PROGRESSION_RULES | 유지 — 목록을 **수정하지 않았다** |

기록해 두는 감사 소견 (ID 를 붙이지 않는다):

* `UNRESOLVED_PROGRESSION_RULES` 에 "페이즈에 유발하는 카드 효과" 항목이 없다.
  (가장 가까운 것은 "페이즈를 건너뛰거나 추가하는 카드 효과" 로, 다른 문제다.)
  이 Phase 는 `engine/` 를 바꾸지 않기로 했으므로 **여기에 적어 두기만 한다.**
* `TriggerSpec` 에 페이즈 필터가 없는 것과 파서가 수정자를 버리는 것은 **같은
  공백의 양쪽**이다. 한쪽만 고치면 다른 쪽에서 막힌다.

## 17. Final Judgment

| | 질문 | 답 |
|---|---|---|
| 1 | `EVENT_PHASE + 수정자` 는 `EVENT_PHASE` 단독과 의미가 다른가 | **YES.** 사건 번호가 다르고(0x1200 ≠ 0x1002 ≠ 0x1000), 규칙 계층에서도 다른 시점이다. 게다가 단독 형태는 원문에 **0건**이다 |
| 2 | 수정자가 지금 어디에든 보존되는가 | **모델에는 NO** (전 필드 확인). **원문 `c*.lua` 에는 YES** — 복구 가능하다 |
| 3 | production Engine 이 지금 소비하는가 | **NO.** 이름 자체가 `engine/`·`agent/` 에 없다 |
| 4 | 잃어서 지금 실행되는 듀얼이 달라지는가 | **NO.** 등록된 트리거 선언 0개 · 통합 계층 미연결 |
| 5 | parser bug 인가, 표현 한계인가, 데이터 한계인가, 미래 요구인가 | **표현 한계 + 미래 요구.** parser bug 아니고 데이터 한계도 아니다 (원문에 다 있다) |
| 6 | 지금 Engine 변경을 정당화하는가 | **NO** (§12 의 B) |
| 7 | 새 STRUCTURAL ID 를 정당화하는가 | **NO** (§13 조건 2·3·4 불충족) |
| 8 | STRUCTURAL-34 에 영향이 있는가 | **NO** |
| 9 | GameStateView 에 영향이 있는가 | **NO** |
| 10 | Evaluation/Search 에 영향이 있는가 | 듀얼 평가/탐색은 **NO**. 카드 **검색** 기능의 표현력만 제한된다 (별개 계층) |

판정: **B. 의도적이지 않은, 그러나 현재 무해한 collapse** — §1 의 보기로는
(B) 와 (E) 의 결합이다. 수정자 소실은 실재하고 의미도 실재하지만(=C 가 아니라
B: 파서가 "첫 이름" 만 약속했으므로 정보 손실이 설계상 예상된 범위다),
**지금 그것을 읽는 production 경로가 없으므로 (E) 현재는 무관하다.** (F) 구조적
blocker 는 아니다.

## 18. Next Phase Candidate

**EVENT_PHASE 표현 설계는 미룬다.** 소비자(Trigger Engine)가 그 정보를 실제로
읽기 전에 보존 형식을 못 박으면, 형식과 소비 방식이 어긋날 위험만 산다. 원문이
보존되어 있으므로 나중에 재파싱으로 복구할 수 있다.

이번 감사가 실제로 드러낸 **더 앞선 공백 하나**를 다음 후보로 올린다:

> **(B) 트리거 계층과 듀얼 루프 사이의 단절 감사** — `TriggerSpec` ·
> `TriggerCollector` · `TriggerChainIntegrator` · `TimingCoordinator` 가 모두
> 존재하고 테스트도 있는데, **production 에 등록된 선언이 0개이고
> `engine/duel.py` 가 그 계층을 아예 import 하지 않는다.** 즉 지금 엔진은 어떤
> 유발 효과도 후보로 만들 수 없다. EVENT_PHASE 든 EVENT_DESTROYED 든, 표현을
> 고치기 전에 **소비자가 하나라도 연결되어야 의미가 생긴다.**

다음 Phase 는 지시 없이 진행하지 않는다.
