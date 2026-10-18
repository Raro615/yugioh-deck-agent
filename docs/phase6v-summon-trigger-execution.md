# Phase 6-V — 소환 성공 시 유발 효과 등록 및 실제 Duel 실행

> 대상: 잭나이츠 오르페골 기르수 `69811710` · 브랜치 `claude/pensive-goodall-te1egy`
> 시작 HEAD `73f1d8a` (Phase 6-U 완료 지점)

## 1. 기존 구조와 실제 원인

### 1.1 조사로 확인한 경로 — **데이터는 전부 있었다**

6-U 는 "소환 후 `entry_for(GIRSU) is None` 이라 후보가 안 난다" 로 끝났다.
그 진단은 맞았지만 **그것이 전부가 아니었다.** 경로를 한 단계씩 실측했다.

| 단계 | 상태 | 증거 |
| --- | --- | --- |
| 일반 소환 실행 | ✅ 동작 | 6-U 가 열었다 (`accepted=True code=ok`) |
| `MonsterSummoned` 델타 | ✅ 동작 | `P0 가 #0 를 HAND 에서 MZONE[0] 로 normal 소환` |
| `timing_events` → 시점 | ✅ 동작 | `point=monster_summoned actor=0` |
| Effect Analysis 추출 | ✅ 동작 | 4블록 전부 (`[0]`=e1 `SINGLE`+`TRIGGER_O`, `EVENT_SUMMON_SUCCESS`, `TOGRAVE`, `count_limit='1,id'`) |
| `TriggerRegistry` / `TriggerSpec` | ✅ 동작 | `point=MONSTER_SUMMONED` · `summons={NORMAL}` · `subject=SELF` |
| **`EffectDefinition`** | ❌ **없음** | `readiness` 의 유일한 blocker = `DEFINITION_MISSING` |
| **`activation_zone` 관문** | ❌ **`UNKNOWN`** | `activates_from=None` ("발동할 수 있는 자리가 선언되지 않았습니다") |

🔴 **즉 끊긴 고리가 둘이었다.** 6-U 가 적은 `DEFINITION_MISSING` 하나와,
그 뒤에 숨어 있던 **자리 관문** 하나. 정의만 등재하면 후보가 날 것처럼
읽히지만 실측하면 관문 5개 중 2개가 `UNKNOWN` 이었다.

### 1.2 `Duel` 은 트리거 계층을 부르지 않는다

`engine/duel.py` 에 `trigger` 라는 낱말이 **0회** 나온다. `TimingCoordinator`
(트리거→체인 통합의 설계된 진입점)를 **생산 코드에서 아무도 쓰지 않는다**
(`engine/__init__.py` 의 설명에만 나온다).

그래서 수직 경로는 지금도 `Duel` 안에서 자동으로 흐르지 않는다. 6-V 는
**그 배선을 만들지 않았다** — 아래 §11 의 BLOCKER-2 로 적는다.

### 1.3 🔴 6-U 의 보고에 있던 무의미한 단언

6-U §18-3 과 그 테스트가 `entry_for(MAGNA) is None` 으로 "등재가 없다" 를
주장했다. 그런데 `entry_for` 는 `EffectRef` 를 받는다 — **정수를 넘기면
비교가 언제나 거짓**이라 등재된 카드조차 `None` 이 나온다.

```python
entry_for(HONEST)              # None   ← 등재되어 있는데도
entry_for(EffectRef(HONEST,0)) # 있음
```

결론(기르수·마그나에 등재가 없다)은 **우연히 맞았지만** 그 단언은 아무것도
재지 않았다. `test_a02_entry_for_needs_an_effect_ref_not_a_card_id` 가 두
호출이 다른 것임을 고정한다.

## 2. 수정한 파일 · 함수

프로덕션 **2파일 4군데**. 카드 ID 분기는 없다.

| 파일 | 함수 · 자리 | 무엇을 |
| --- | --- | --- |
| `engine/trigger.py` | `summoned_zone_for` (신규 모듈 함수) | 그 사건이 이 카드를 어느 자리에 내놓았는가 (**읽기**) |
| `engine/trigger.py` | `TriggerEligibilityJudge.judge` | 그 **값 하나**를 관문에 넘긴다 (사건이 아니다) |
| `engine/trigger.py` | `TriggerEligibilityJudge._activation_zone` | 선언이 없으면 그 값을 먼저 본다 |
| `engine/trigger.py` | `TriggerEligibilityJudge._zone_from_summon` (신규) | 그 값으로 자리를 인정할지 **판정** |
| `engine/effect/library.py` | `_GIRSU_TRIGGER_ENTRY` (신규) · `GIRSU` 상수 · `OPERATION_RULINGS` 한 줄 | 기르수 ① 등재 |

### 2.1 `summoned_zone_for` · `_zone_from_summon` — 왜 소환 계열만인가

`EFFECT_TYPE_SINGLE` 트리거 등록은 `SetRange` 를 적지 않는다. 전수 측정:

```
트리거 등록 전체                   8,052
SINGLE 트리거                      5,304
  └ SetRange 없음                  5,204   (98.1%)
  └ SetRange 있음                    100
```

`activates_from` 이 비는 것은 데이터가 없어서가 아니라 **그 축으로 적히지
않기 때문**이고, 그래서 관문이 5,204건 전부에 `UNKNOWN` 을 냈다.

그런데 소환 계열 사건은 **자신이 자리를 들고 있다** — `MonsterSummoned` 가
`to_zone` 을 적고, 그 카드가 사건의 주체이면 발동 시점의 위치가 곧 그
도착지다. 소환이 성공했다는 것이 그 몬스터가 몬스터 존에 나왔다는 뜻이므로
**추론이 아니라 사건의 내용**이다.

🔴 **일괄 적용하지 않은 이유 — 데이터가 반대한다.** 같은 5,204건의 사건
코드 분포:

```
EVENT_SPSUMMON_SUCCESS   1,391   ← 자리를 말한다
EVENT_SUMMON_SUCCESS       936   ← 자리를 말한다
EVENT_TO_GRAVE             907   ← 🔴 발동 순간 카드는 묘지에 있다
EVENT_DESTROYED            379   ← 🔴 필드에 없다
EVENT_BATTLE_DESTROYING    224
EVENT_BATTLE_DESTROYED     196
EVENT_REMOVE               113   ← 🔴 제외되어 있다
EVENT_FLIP_SUMMON_SUCCESS  112   ← 자리를 말한다
EVENT_LEAVE_FIELD           95   ← 🔴 필드를 떠났다
```

`EVENT_TO_GRAVE` 쪽에 `MZONE` 을 채우면 드로우 개구리(`56840658`)에서 이미
재현된 **잘못된 확신**이 2,000건 가까이 생긴다 (`trigger_compiler` 의
`_split_range` 설명이 그 사례를 적어 두었다). 그래서 사건이 자리를
**말해 주는** 경우만 읽는다.

적용 조건 셋, **데이터만 본다**:

1. `spec.point is MONSTER_SUMMONED`
2. `spec.subject is SELF` — 그때만 도착지가 **이 카드**의 것이다
3. 사건의 변화가 `MonsterSummoned` 이고 `delta.card == candidate.source`

🔴 **거짓 양성을 만들 수 없다.** 사건이 적은 도착지와 **관측이 보는 현재
자리**가 둘 다 맞아야 통과한다. 어긋나면 `UNKNOWN` 으로 남는다 (해결 중에
그 카드가 다시 움직인 경우).

### 2.2 `_GIRSU_TRIGGER_ENTRY` — 목록의 첫 유발 효과

그 전까지 등재 17건은 전부 기동 효과이거나 마법·함정의 카드 발동이었다.

| Lua | 옮긴 자리 |
| --- | --- |
| `e1:SetType(EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O)` | `ActivationKind.TRIGGER` |
| `e1:SetCode(EVENT_SUMMON_SUCCESS)` | **정의가 아니라 트리거 등록**이 들고 간다 |
| `s.tgfilter` 의 `IsSetCard({SET_ORCUST,SET_WORLD_LEGACY})` | 후보 조건 (`CandidateSource.require`) |
| `s.tgfilter` 의 `IsAbleToGrave()` | **관문** (`gated=True`) — 2-X 의 가름 |
| `s.tgop` 의 `Duel.SendtoGrave(tc,REASON_EFFECT)` | `CardOperation.send_to_grave` |
| `s.tgtg` 의 `chk==0` 갈래 | **덱 장수 부분만** (`ZoneCountAtLeast`) |

🔴 **카드군 코드를 숫자로 적지 않았다.** `compile_archetype_condition(
("SET_ORCUST","SET_WORLD_LEGACY"))` 이 상수 표에서 해석한다 → `(0x11b, 0xfe)`.
6-D 가 만들어 둔 그 자리를 **처음으로 쓴 것**이다 (6-D 이후 아무도 쓰지
않았고, `test_j` 가 "쓰는 실행이 하나도 없다" 를 지키고 있었다).

**옮기지 못한 것을 적어 두었다**:

1. `e1:SetCountLimit(1,id)` — `UseRegistry` 는 횟수를 **세기만** 하고
   "몇 번까지 허용인가" 는 Phase 4 다 (`engine/__init__.py`). 그래서 정의가
   그 제약을 **주장하지 않는다**
2. `s.tgop` 뒤쪽의 `GetColumnGroupCount()>=2` → `EFFECT_ADD_TYPE` (튜너 추가)
3. `Duel.BreakEffect()` — 같은 해결 안의 처리 분리를 표현할 자리가 없다

### 2.3 `OPERATION_RULINGS` 한 줄 (18 → 19)

**이것은 선택이 아니라 필수였다.** 등재된 카드는 판에 깔리고, 판에 모르는
카드가 하나라도 있으면 `BoardRuling._interference` 가 멈춰 **판 전체의 답이
`UNKNOWN`** 이 된다. 어니스트가 6-K 에서 들어온 것과 같은 이유다.

`answers` 는 **비어 있다**: 효과 몬스터이므로 `normal_monster_facts` 를 쓸
수 없고 (그 근거는 "효과가 없다" 는 룰북 한 줄이다), 기르수의 공식 텍스트는
자기 자신을 어디로 보낼 수 있는지 **말하지 않는다.** 묻지 않은 것을 참으로
채우지 않는다.

## 3. 기르수 Lua 및 EffectRef 연결 결과

```
c69811710.lua
  e1  SINGLE+TRIGGER_O  EVENT_SUMMON_SUCCESS    CountLimit(1,id)  → EffectRef(69811710, 0)  ← 6-V 등재
  e2  e1:Clone()        EVENT_SPSUMMON_SUCCESS                    → EffectRef(69811710, 1)  미등재
  e3  IGNITION          SetRange(LOCATION_MZONE) CountLimit(1,{id,1}) → EffectRef(69811710, 2)  미등재
  e1' SINGLE            EFFECT_ADD_TYPE (s.tgop 내부)              → 블록 [3]
```

| 축 | 수정 전 | 수정 후 |
| --- | --- | --- |
| `entry_for(EffectRef(GIRSU,0))` | `None` | **있음**, `executable=True` |
| `readiness` blockers (e[0]) | `['DEFINITION_MISSING']` | **`[]`** |
| `readiness` blockers (e[1]) | `['DEFINITION_MISSING']` | `['DEFINITION_MISSING']` (그대로) |
| 코퍼스 전체 `with_definition` | 0 | **1** |
| 코퍼스 전체 `definition_missing` | 4,173 | **4,172** |

🔴 **e[1]·e[2] 는 등재하지 않았다.** 하나를 등재했다고 나머지가 열리지
않는다는 것을 `test_m02` 가 ordinal 을 구분해 잰다.

## 4. TRIGGER 후보 생성 전후 비교

같은 판(선공 메인1, 기르수를 실제 일반 소환)에서 관문 5개를 측정했다.

| 관문 | 6-U 직후 | **6-V** |
| --- | --- | --- |
| `event_relation` | ✅ valid — "사건의 주체가 이 카드입니다 (#0)" | ✅ 그대로 |
| `activation_zone` | ❌ **unknown** — "발동할 수 있는 자리가 선언되지 않았습니다" | ✅ **valid** — "MZONE 에서 발동할 수 있습니다 — 소환 사건이 이 카드의 자리를 적었습니다 (normal 소환, HAND → MZONE)" |
| `trigger_condition` | ✅ valid — "자신 DECK 에 1장 이상" | ✅ 그대로 |
| `execution_authority` | ❌ **unknown** — `no_implementation` | ✅ **valid** — "출처가 허용하고 구현이 등록되어 있습니다" |
| `cost_feasibility` | ✅ valid — "치를 비용이 없습니다" | ✅ 그대로 |
| **결과** | `status=unknown` → `unordered` | **`ELIGIBLE`** → `canonical_sequence` |

```
6-U:  적격 0건 · 제외 4건 · 미정 1건
6-V:  적격 1건 · 제외 0건 · 미정 0건
```

**인스턴스 구분이 정확하다.** 패에 기르수가 여럿일 때 후보는 소환된 그 한
장뿐이고, 나머지는 `event_relation` 이 "사건의 주체는 #0 이고 이 카드는 #1
입니다" 로 거른다 (`test_c02`).

## 5. 실제 발동 · 체인 해결 여부

```
@primary 적법 후보 35장 / 덱 35장
  카드군이 아닌 후보  0건      ← 거짓 양성 없음
  덱 밖의 후보        0건

발동:  activated   체인 길이 1        ✅
해결:  unchecked_rules                ❌
  reason: #0 를 묘지로 보낼 수 있는지 판정할 수 없습니다:
          이 카드를 묘지로 보낼 수 있는가 (Card.IsAbleToGrave) ·
          묘지 대신 다른 곳으로 가는가 (펜듈럼 · 토큰 · 대체 효과).
          판정할 수 없는 것을 허가로 바꾸지 않습니다.
```

🔴 **발동은 된다. 해결은 안 된다.** 체인에 링크가 하나 쌓이는 것까지
확인했고, `ChainResolver` 가 관문에서 멈춘다.

**어리석은 매장(`81439173`)이 오늘 멈추는 그 자리와 같다** — 같은
`SelectMatchingCard(... LOCATION_DECK ...)` + `SendtoGrave` 모양이고,
`test_i_foolish_burial_now_reaches_the_gate` 가 이미 `UNCHECKED_RULES` 를
고정해 두었다. 즉 6-V 가 만든 한계가 아니라, 유발 효과를 이어 붙이자
**그 앞에 있던 벽이 드러난 것**이다.

## 6. 덱→묘지 이동 및 GameState 결과

```
덱    35 → 35      (변화 없음)
묘지   0 →  0      (변화 없음)
고른 인스턴스 #0   zone=DECK  (그대로)
```

🔴 **아무것도 움직이지 않았다. 이것을 성공으로 적지 않는다.**
`test_f03` 이 세 축(덱 장수 · 묘지 장수 · 인스턴스의 zone)을 전부 고정한다.

## 7. EventJournal 검증

```
EventJournal: 0건
```

멈춘 해결은 사건을 적지 않는다. §5-11 의 일관성은 **"기록이 비어 있다"**
쪽으로 성립한다 — 판이 안 바뀌었는데 기록이 있으면 그것이 모순이다.

소환 쪽 기록은 따로 확인했다: `ActionEvent` 하나, `MonsterSummoned` 델타
하나, **`EFFECT` 사건 0건** — 소환은 효과 발동이 아니다 (RULE-CHAIN-011,
`test_b03`).

## 8. 효과 사용 횟수 및 거짓 양성 검사

### 8.1 1턴에 1번 — **주장하지 않는다**

| 축 | 상태 |
| --- | --- |
| Lua 원본 | `e1:SetCountLimit(1,id)` **있다** |
| Effect Analysis | `count_limit='1,id'` **추출됨** |
| `UseRegistry` | `PER_CARD_NAME` 축 **있다** |
| `EffectDefinition` | 적을 **칸이 없다** |
| 집행 계층 | **없다** (Phase 4) |

🔴 정의가 그 제약을 들고 있지 않다. 들고 있는 척하면 "한 번만 발동된다" 가
거짓으로 적힌다. `test_f05` 가 다섯 축을 전부 고정한다 (원본에 있다 ·
추출됐다 · 정의에 칸이 없다 · 세는 축은 있다).

### 8.2 거짓 양성 — **0건**

| 검사 | 결과 |
| --- | --- |
| 적법 후보 35장 전부가 「오르페골」/「성유물」인가 | ✅ 위반 0건 |
| 적법 후보 전부가 덱에 있는가 | ✅ 위반 0건 |
| 덱에 적합한 카드가 없을 때 후보가 비는가 | ✅ `()` |
| 소환이 아닌 사건에서 자리가 열리는가 | ✅ 열리지 않음 (`UNKNOWN`) |
| 다른 카드의 소환 사건으로 자리가 열리는가 | ✅ 열리지 않음 |
| 패의 다른 사본이 후보가 되는가 | ✅ 안 됨 (`CANDIDATE_NOT_ELIGIBLE`) |

🔴 **조사 중 내 테스트 전제 4건이 틀렸고, 네 번 다 엔진이 옳았다.**

1. **기르수 자신이 「오르페골」 카드다** (`setcodes` 에 `0x11b`) — 덱에 남은
   기르수가 적법 후보로 나왔고 그것이 규칙상 맞다
2. **마그나는 `SetRange` 를 적는다** (`activates_from={MZONE}`) — 6-V 가 연
   자리가 아니므로 공통 구조 확인에 쓸 수 없다
3. `engine/trigger.py` 에 「기르수」 가 **6-E 때부터** 설명에 있었다
4. `test_d04` 는 패에 기르수가 둘 이상이어야 한다

## 9. 다른 카드로 공통 구조 검증

`SINGLE` + `EVENT_SUMMON_SUCCESS` + `SetRange` 없음인 카드를 코퍼스에서
찾아, 같은 축에 놓이는 등록이 **20건 이상**임을 확인했다 (`test_g01`).

```
문 가드너 336601 · 찬미화 373085 · 가가가 시스터 387282 ·
바이스 샤크 613013 · 사이버스 가제트 645087 · …
```

🔴 **기르수 혼자가 아니다** — 같은 근거로 자리가 열릴 등록이 여럿이고, 그것이
이 수정이 카드별 분기가 아니라는 증거다. 다만 **정의가 없으면 실행되지
않는다** (ADR-006): 그 카드들은 `execution_authority` 에서 멈춘다.

반례도 함께 고정했다 — 마그나는 `SetRange` 를 적으므로 애초에 이 경로가
아니다.

그리고 카드 번호 분기가 없음을 AST 로 센다 (`test_g02`): `engine/trigger.py`
에 기르수 번호가 0회, `ORCUST`·`SET_` 가 0회이고, 새 판정 함수 본문에
`card_id` 가 없다.

## 10. 테스트 통과 · 실패 · 실행 시간

전부 `-p no:randomly` 로, 실제 종료 코드를 읽었다.

| # | 명령어 | 통과 | 실패 | 시간 |
| --- | --- | --- | --- | --- |
| 1 | `pytest tests/engine/test_summon_trigger_execution.py` | **23** | **0** | 3.41s |
| 2 | `pytest tests/engine` | **3,553** | **0** | 342.50s (5:42) |
| 3 | 루트 영향 파일 51개 + `test_opening_duel_integration` | **1,372** | **2** | 2,075.29s (34:35) |

### 10.1 §6 의 위험 기반 순서를 지켰다

| 단계 | 무엇을 | 결과 |
| --- | --- | --- |
| ① 변경 모듈 타깃 | `test_summon_trigger_execution` · `test_trigger_effect_execution` · `test_rule_gate_grave_discard` · `test_real_card_execution` · `test_effect_monster_normal_summon` · `test_normal_summon` | 272 passed |
| ② Duel 수직 통합 | `test_opening_duel_integration` · `test_action_legality` · `test_legal_action_candidate_consistency` · `test_chain` · `test_chain_response` · `test_trigger_chain` · `test_trap_activation_free_chain` · `test_card_definition_view` · `test_archetype_condition` + Discord | 466 passed |
| ③ 관련 엔진 전체 | `tests/engine` | 3,553 passed |
| ④ 공유 계약 변경 범위 | 루트 영향 파일 51개 (`EFFECT_LIBRARY` · `OPERATION_RULINGS` · `activates_from` · `ACTIVATION_ZONE` · `definition_registry` · `compiled_triggers` 를 언급하는 파일 전수) | 1,372 passed / 2 failed |

🔴 **6-U 처럼 한 시간 넘는 전체 루트를 반복하지 않았다.** 영향 파일을
grep 으로 특정해 51개로 좁혔고, 그 안에서 공유 계약 감사 두 건이 실제로
잡혔다 (부록 A).

### 10.2 루트 실패 44건의 분류 — **42건 고침**

| 원인 | 건수 | 6-V 의 것인가 | 상태 |
| --- | --- | --- | --- |
| 목록 수 17→18 · 실행 14→15 | 20 | 🔴 **예** | **고침** |
| 카드 종류 분포 (몬스터 1→2) | 4 | 🔴 **예** | **고침** |
| 발동 조건 8→9 | 3 | 🔴 **예** | **고침** |
| 코드 집합에 `EVENT_SUMMON_SUCCESS` | 5 | 🔴 **예** | **고침** |
| "untouched" 계열 몬스터 분기 | 4 | 🔴 **예** | **고침** |
| 줄 수 핀 (2,059→2,199 · 813→840) | 2 | 🔴 **예** | **고침** |
| 폐쇄·등장·거부 카운트 +1 | 2 | 🔴 **예** | **고침** |
| 🔴 **설계 경계 감사** (`test_15` · `test_11`) | 2 | 🔴 **예** | **구현을 고쳤다** (부록 A) |
| 재정 데이터 의존 (`.gitignore` 크롤 캐시) | 1 | 아니다 | 그대로 |
| 에이전트 상대 자원 한계 주장 | 1 | 아니다 | 그대로 |

**남은 2건**:

```
FAILED tests/agent/test_opponent_resource_weighting_audit.py
       ::test_07_a_whole_duel_never_offers_a_choice_about_opponent_resources
FAILED tests/test_event_free_chain_semantic_audit.py
       ::test_27_the_official_corpus_never_uses_the_term
```

🔴 **둘 다 6-V 와 무관함을 확인했다.** 프로덕션 2파일을 `73f1d8a`
(6-V 시작 지점) 버전으로 임시 교체해 다시 돌렸고 **같은 자리에서 같은
값으로** 실패한다:

```
# 73f1d8a 의 engine/trigger.py · engine/effect/library.py 로 교체한 상태
tests/agent/test_opponent_resource_weighting_audit.py:305  [1, 1, 1, ...]
tests/test_event_free_chain_semantic_audit.py:1105         15
2 failed in 3.90s
```

확인 뒤 `git checkout HEAD --` 로 복원했다. 두 건은 6-U 보고서 §13 · §18-2
가 이미 원인과 조치를 기록해 두었다 (에이전트 한계 주장 무효화 ·
`data/rulings/.cache` 부재). **6-V 는 그 둘을 건드리지 않았다.**

### 10.3 테스트 정책 — 금지 사항 점검

| 금지 | 지켰는가 |
| --- | --- |
| 테스트 삭제 | 하지 않았다 |
| `skip` 추가 | 하지 않았다 |
| assertion 완화 | 하지 않았다 — 사실이 끝난 네 자리는 "0개" 를 **"정확히 하나"** 로 바꿨고, 둘이 되면 깨진다 |
| threshold 완화 | 하지 않았다 |
| 기존 실패와 신규 회귀를 섞기 | 가렸다 — 10.2 의 표와 `73f1d8a` 교체 판별 |

🔴 **그리고 테스트가 옳았던 자리에서는 테스트가 아니라 구현을 고쳤다**
(부록 A). 내 테스트의 틀린 전제 4건도 측정으로 바로잡았고 네 번 다 엔진이
옳았다 (§8-2).

### 10.4 변경 규모

```
프로덕션  2파일  +259 / -2
  engine/trigger.py        +144   (summoned_zone_for · _zone_from_summon · judge)
  engine/effect/library.py +117   (_GIRSU_TRIGGER_ENTRY · GIRSU · OPERATION_RULINGS)

테스트   48파일  +1,581 / -231
  새 파일 1 (test_summon_trigger_execution.py, 23건)
  정정  47 (루트 감사 42건 + engine 쪽 21건이 겹친다)
```

## 11. 남아 있는 구조적 BLOCKER

순서는 **수직 경로에서 만나는 순서**다. 1번이 §4 가 말하는 "첫 번째 실제
BLOCKER" 다.

### BLOCKER-1 🔴 `MAY_BE_SENT_TO_GRAVE` 를 답할 수 있는 카드가 하나도 없다

`CardOperation.send_to_grave(gated=True)` 는 해결 전에 조작 판정을 받는다.
그 판정은 두 곳에서만 나온다:

1. `OPERATION_RULINGS` — **손으로 적은** 19장
2. `rulebook_facts` — 룰북 한 줄에서 **순수 통상 몬스터**에만

기르수의 적법 후보(메인덱 「오르페골」/「성유물」 47장)를 전수로 보면:

```
효과 몬스터       13
통상 함정          9
지속 마법          5
필드 마법          5
지속 함정          5
통상 마법          4
속공 마법          3
카운터 함정        2
효과 몬스터(튜너)  1
──────────────────
순수 통상 몬스터   0   ← 🔴
```

**0장이다.** 그래서 어느 후보를 골라도 관문이 `UNKNOWN` 이고 해결이
`UNCHECKED_RULES` 에서 멈춘다. `test_f04` 가 이 전수를 고정한다.

이것은 "운이 나빴다" 가 아니라 **구조적**이다. 같은 벽이 어리석은 매장을
Phase 2-Y 부터 막고 있다. 풀려면 조작 판정 계층이 통상 몬스터 밖으로
넓어져야 하고, 그것은 **새 규칙 주장**이므로 이 Phase 의 범위가 아니다.

### BLOCKER-2 `Duel` 이 트리거 계층과 배선되어 있지 않다

```
engine/duel.py 안의 "trigger" 언급: 0회
TimingCoordinator 를 쓰는 생산 코드: 없음 (문서에만)
```

지금 수직 경로는 **시험이 손으로 이어서** 흐른다 —
`timing_events` → `TriggerChainIntegrator.collect_and_order` → `plan`.
`Duel.apply` 가 소환을 수락한 뒤 그 사건을 트리거 계층에 넘기지 않는다.

6-V 는 이 배선을 만들지 않았다. 만들면 "소환 → 발동 후보 제시" 가 듀얼
루프 안에서 자동으로 흐르는데, 그 사이에 **우선권과 응답 기회**가 있고
(`trigger_chain` 머리말이 "자동 실행이 없다" 고 적어 둔 이유), 그 계층을
이 Phase 가 정하면 범위를 넘는다.

### BLOCKER-3 `STRUCTURAL-125` — 덱에서 고르는 효과는 `legal_actions` 후보가 될 수 없다

`target_bridge.target_combinations` 가 `looked_at` 권한으로 후보를 센 **뒤
평소 관측으로 다시 좁힌다.** 이유가 코드에 적혀 있다:

> `PlayerAction` 은 정책에게 가는 **데이터**다. 거기에 가려진 존의 카드를
> 적으면, 정책이 후보 목록을 읽는 것만으로 덱 내용을 알게 된다 —
> `looked_at` 이 효과에게 준 권한이 AI 에게까지 새는 길이다.

그래서 기르수를 소환한 뒤에도 `activate_effect` 가 **제시되지 않는다**
(`test_f02` 가 조합 수 0 과 후보 목록 둘 다 잰다). 이것은 의도된 정보 은닉
경계이고 버그가 아니다. 풀려면 "해결 중에 고른다" 는 계층이 필요하다 —
선택을 미리 `Action` 에 적지 않는 구조.

### BLOCKER-4 횟수 제한 집행 계층이 없다

§8-1 의 표 그대로다. `UseRegistry` 는 세고, 허용 여부는 Phase 4 다.

### BLOCKER-5 `e[1]`(특수 소환)·`e[2]`(기동)은 등재하지 않았다

`e[1]` 은 `EVENT_SPSUMMON_SUCCESS` 이고 특수 소환 절차 자체가 범위 밖이다.
`e[2]` 는 토큰 2장을 양쪽 필드에 특수 소환하는 기동 효과이고 토큰 계층이
없다. 둘 다 `DEFINITION_MISSING` 으로 남아 있고, `test_m02` 가 그것을
ordinal 단위로 고정한다.

## 12. 다음 최소 개발 단계 추천

**A. 조작 판정을 「제약이 없으면 보낼 수 있다」 로 넓힌다 (BLOCKER-1)**

6-U 가 소환 제약에서 쓴 것과 **같은 모양**이다: 카드 자신의 스크립트에서
금지 상수를 세고, 한 건도 없으면 룰북의 일반 규칙이 적용된다. `IsAbleToGrave`
를 막는 EDOPro 상수(`EFFECT_CANNOT_TO_GRAVE` 계열)를 전수로 세고, 역검산으로
거짓 허가 0건을 확인하는 절차까지 6-U 의 것을 그대로 쓸 수 있다.

🔴 이것이 **수준 3 을 여는 유일한 최소 경로**다. 다른 BLOCKER 를 먼저
풀어도 해결은 여전히 이 관문에서 멈춘다.

**B. `Duel` 에 트리거 계층을 배선한다 (BLOCKER-2)**

`TimingCoordinator` 가 이미 있으므로 새 엔진을 쓰지 않는다. 다만 우선권·
응답 창과 맞물리므로 그 계층의 결정이 먼저 필요하다.

**C. 해결 중 선택 계층 (BLOCKER-3)**

`TriggerChainPlan.needs_decision` 이 이미 "무엇이 아직 안 정해졌는가" 를
말한다. 그것을 받아 **해결 시점에** 고르게 하는 자리를 만들면 덱에서 고르는
효과가 듀얼 루프 안에서 흐를 수 있다.

권장 순서는 **A → C → B** 다. A 없이는 무엇을 배선해도 판이 바뀌지 않는다.

## 13. Git 커밋 · 푸시 결과

브랜치 `claude/pensive-goodall-te1egy` · 시작 `73f1d8a` (6-U 완료 지점).

| 커밋 | 내용 |
| --- | --- |
| `0a3210e` | **프로덕션** — 소환 사건에서 발동 자리를 읽고 기르수 ① 등재 |
| `a5dad0d` | **테스트** — 수직 경로 23건 + 기존 기대 21건 정정 |
| `164884e` | **보고서** — 조사·수정·측정과 수준 판정 |
| `08fdb3b` | **프로덕션 재설계** — 관문이 사건 대신 자리 값을 받는다 (3-F-5 경계 유지) |
| `a00373b` | **테스트** — 루트 감사 42건 정정 |
| `129b665` | 보고서 — 부록 A (설계 경계를 깼다가 고친 기록) |
| `38ce987` | 보고서 — 절 번호를 요청된 13항목 순서와 맞춤 |
| (이 커밋) | 보고서 — §10 테스트 결과 · §13 Git 결과 |

- 전부 `git push -u origin claude/pensive-goodall-te1egy` 로 푸시됨
  (재시도 없이 1회 성공)
- **기존 commit 을 rewrite/amend 하지 않았다.** force push 없음, 새 브랜치
  없음, PR 없음
- 프로덕션 · 테스트 · 보고서를 **분리된 커밋**으로 올렸다
- 모든 커밋에 요구된 attribution 두 줄이 붙어 있다

## 14. 성공 수준 판정

| 수준 | 요구 | 판정 |
| --- | --- | --- |
| **1** | 기르수 `EffectDefinition` 누락 원인과 TRIGGER 데이터 경로 확인 | ✅ **달성** |
| **2** | 실제 소환 성공 이벤트에서 올바른 유발 효과 후보 생성 및 발동 조건 검증 | ✅ **달성** |
| **3** | 실제 Duel 에서 발동·체인 해결 후 덱의 적법한 카드가 묘지로 이동하고 GameState·EventJournal 로 검증 | ❌ **미달성** |

**수준 1 의 증거**: §1 의 경로 표. 원인이 `DEFINITION_MISSING` **하나가
아니라 둘**이었음을 실측으로 확인했고(자리 관문), `Duel` 배선 부재까지 함께
특정했다.

**수준 2 의 증거**: §4 의 관문 표. 실제 소환 → 적격 1건, 관문 5개 전부
`valid`, 발동 조건(`자신 DECK 에 1장 이상`)이 참으로 평가됐다. 발동까지
갔고 체인 링크가 하나 쌓였다 (§5).

**수준 3 이 미달성인 이유**: 해결이 `UNCHECKED_RULES` 에서 멈추고 덱·묘지·
인스턴스·기록이 **하나도 변하지 않았다** (§6 · §7). BLOCKER-1 이 원인이고
전수 측정으로 "후보 47장 중 룰북이 답할 수 있는 카드 0장" 을 확인했다.

🔴 **정적 효과 분석만으로 수준 3 을 주장하지 않았다** (§7 의 요구). 실제
`EffectActivator.activate` 와 `ChainResolver.resolve_top` 을 돌렸고, 멈춘
자리와 변하지 않은 판을 테스트로 고정했다 (`test_f03`).

🔴 **실제로 실행하지 않은 행동을 성공이라고 기록하지 않았다.** F 묶음 5건이
"여기서 멈춘다" 를 단언으로 적는다.

## 부록 A. 🔴 설계 경계를 한 번 깼고, 테스트가 잡았다

이 절은 **내가 틀린 기록**이다. 숨기면 다음 Phase 가 같은 실수를 한다.

### A.1 무엇을 깼는가

첫 구현은 `_activation_zone` 관문에 `TimingEvent` 를 **그대로** 넘겼다.
`tests/engine` 3,553건은 전부 통과했고 루트 회귀에서 깨졌다:

```
FAILED tests/test_trigger_spec_declaration_audit.py
       ::test_15_no_gate_sees_the_event_and_the_candidate_together
```

그 시험은 Phase 3-F-5 의 **발견**을 census 로 고정한다:

> 다섯 관문 중 사건을 받는 것은 `_event_relation` **하나**이고, 그 관문은
> 후보를 받지 **않는다.** `event.actor` 와 `candidate.controller` 를
> 비교해야 하는데 **두 값이 같은 함수 안에 있는 관문이 하나도 없다.**
> 그래서 이것은 필드 추가가 아니라 **계층 경계의 문제**다.

내 구현은 `_activation_zone` 을 `(event=True, candidate=True)` 로 만들어
그 census 를 깼다.

### A.2 왜 테스트를 고치지 않았는가

그 시험의 요지가 **옳다.** 그리고 저장소가 같은 문제를 푸는 방법을 이미
적어 두었다 — Phase 6-F 가 `_event_relation` 에 주체 질문을 더할 때
**후보 전체가 아니라 필요한 최소 값**(`source`)을 넘겼고, 그래서 census 가
유지됐다 (설계 C · 3-F-8 §5).

### A.3 어떻게 고쳤는가

같은 설계를 따랐다. 관문이 받는 것은 `Zone` **하나**다.

```python
def summoned_zone_for(event, source) -> "Zone | None":
    """그 사건이 이 카드를 어느 자리에 내놓았는가. 읽기이고 판단이 아니다."""
```

`judge` 가 그 값을 계산해 넘기고, 적격성은 관문이 정한다. `None` 인 경우가
셋이고 **셋 다 "자리를 모른다" 가 아니다**: 사건이 없다 · 소환 사건이
아니다 · 그 소환이 **다른 카드**의 것이다. 마지막이 패의 같은 이름 카드를
걸러낸다 (`test_d04`).

census 복원 확인:

| 관문 | event | candidate |
| --- | --- | --- |
| `_event_relation` | ✅ | — |
| `_activation_zone` | — | ✅ |
| `_trigger_condition` | — | ✅ |
| `_execution_authority` | — | — |
| `_cost_feasibility` | — | ✅ |

**결과적으로 더 나은 구현이 됐다.** 관문은 사건 해석을 하지 않고, 사건
읽기는 이름이 붙은 한 함수에 모였다.

### A.4 같은 회귀가 잡은 다른 것

`test_11_the_declaration_type_has_exactly_one_production_module` 도 깨졌다 —
`library.py` 의 **docstring** 이 `TriggerSpec` 이라는 낱말을 썼기 때문이고
의존은 없었다. 이것도 테스트가 아니라 내 설명을 고쳤다: 그 시험이 지키는
"live 경로는 선언을 모른다" 가 옳고, `library.py` 는 그 타입을 쓰지 않는다.

🔴 **교훈: `tests/engine` 만으로는 설계 경계 감사를 지나칠 수 없다.** 그
감사들은 루트에 있다.
