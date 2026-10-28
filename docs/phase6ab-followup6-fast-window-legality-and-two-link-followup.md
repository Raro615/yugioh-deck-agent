# Phase 6-AB 보완6 — 빠른 효과 기회의 발동 적법성 · 2링크 체인의 후속 유발

🔴 **먼저 적어 두는 다섯 가지**

1. **목표 ①·② 둘 다 완료**로 판정한다. 근거는 §4~§6 이고, **통과한 시험
   수로 주장하지 않는다** — ①은 두 효과 종류를 각각 열린 상태에서 먼저
   허용되게 하고 나서 차단을 쟀고, ②는 필수 실행 순서를 저널과 해결 걸음
   두 층에서 입증했다.
2. **보완6 이 스스로 낸 결함 둘을 측정으로 잡고 고쳤다** — 무한 재귀와
   잘못된 ``selections`` 전달이다. §4.4 가 둘 다 적는다.
3. **기동 효과의 차단은 성립하고 거절 코드의 구분은 성립하지 않는다.**
   그 자리를 "완료" 로 적지 않고 BLOCKER-F6-1 로 남긴다 (§11).
4. **합성한 것과 실제인 것을 줄 단위로 갈랐다** (§7). ②의 CL1 조작과 후속
   조작은 합성이고, **CL2 와 그 사건은 실제**다.
5. **다음 Phase 를 시작하지 않았다.**

---

## 1. 시작 커밋 · 변경 파일 · 검증한 코드 커밋

| | |
|---|---|
| 검토 기준 HEAD (요청) | `263c13b` |
| 확인한 실제 HEAD | `263c13b` — **일치**. 작업 트리 비어 있었고 원격과도 일치 |
| 후속 변경 | **없었다** (덮어쓴 것이 없다) |
| 브랜치 | `claude/pensive-goodall-te1egy` |

### 커밋

| 커밋 | 무엇 |
|---|---|
| `55e6dc5` | ① 체인 유무와 발동 가능 단계를 분리한다 (+ 정정 34건) |
| `c6396e5` | agent 측정값 핀 둘 · 보완5 보고서 정정 다섯 |
| `6ece7e0` | root 그룹 감사의 측정값 핀 24개 파일 (§10.4) |
| `5bd17a0` | rootB 4 의 산문 등장 핀 · 속공 마법 시험 `test_d06` |
| (이 커밋) | 이 보고서 — 🔴 자기 해시를 넣으려고 커밋을 반복하지 않는다 |

### 변경 파일 — 엔진 · 규칙

| 파일 | 무엇 |
|---|---|
| `engine/activation_timing.py` | `ActivationStage` (네 갈래) · `ActivationTiming.stage` · `ActivationTimingChecker._by_stage` · `STAGE_MISSING` · `FAST_WINDOW_RULES` |
| `engine/duel.py` | `Duel._activation_stage` · `_refusal` · `_refusal_verdict` · `_activation_gate` 가 단계를 넘긴다 |
| `engine/response.py` | `check_timing(stage=)` · `act(stage=)` · `_activate(stage=)` |

### 변경 파일 — 시험

| 파일 | 무엇 |
|---|---|
| `tests/engine/test_fast_window_legality.py` | **새로 만들었다** — 23개 (A 단계 판정 · B 통상 마법 · C 기동 효과 · D 허용되는 빠른 효과 · E 사본 · F 보고 계층 · G 단계 책임) |
| `tests/engine/test_two_link_followup_trigger.py` | **새로 만들었다** — 17개 (A 2링크 구성 · B 실행 순서 · C 비간섭 · D 후속 체인 · E 사본 · H 실제/합성 구분) |
| `tests/engine/` 의 기존 파일 **12개** · `tests/` 뿌리의 **25개** · `tests/agent/` 의 **2개** | 측정값 핀을 실측값으로 맞췄다 (§10.4). 지운 시험 · 더한 skip · 느슨해진 assertion 은 없다 |

🔴 **새 모듈을 만들지 않았다.** 네 갈래를 쓰는 자리는 기존 관문
(`ActivationTimingChecker`) 하나, 읽는 자리는 판을 든 쪽(`Duel`) 하나다.

---

## 2. 선행 리뷰 A — 일반 마법의 불법 발동을 현재 HEAD 에서 재현했다

사용자가 보고한 재현을 기준 HEAD `263c13b` 에서 **그대로 다시 쟀다.**
도구는 기존 `tests/engine/test_trap_activation_free_chain.py` 의
`staged(repository, mine=[POT_OF_GREED], fodder=2)` 이고, 경로는 정상
`legal_actions` → `Duel.apply` 다.

```
1. 열린 상태    win=none  chain=0
   욕망의 항아리 후보 ['55144522:e[0]']
2. 몬스터 세트 후보 2 → accepted=True
   win=response holder=0 chain=0
3. 빠른 효과 기회 허가 ['activate_effect', 'pass']
   🔴 욕망의 항아리 후보 ['55144522:e[0]']
   🔴 Duel.apply accepted=True code=OK
      "55144522:e[0] 를 체인 1 로 발동했습니다. 상대의 응답을 기다립니다."
      체인 링크 [(1, '55144522:e[0]', 0)]
```

**재현됨.** 통상 마법(스펠 스피드 1)이 빠른 효과 기회에서 후보로 오르고
체인 1 로 수락되었다.

### 2.1 검토 지점 — 어디가 열려 있었나

| 자리 | 무엇을 하고 있었나 |
|---|---|
| `engine/duel.py` `legal_actions` | `priority.is_open and priority.holds(seat)` 면 `_activation_actions` 를 낸다 — **발동은 창에 끼어들 수 있다**가 맞고, 그 자체는 규칙이다 |
| `engine/activation_timing.py` `check()` | `if not timing.chain_is_open:` → *"체인이 비어 있어 스펠 스피드 제약이 걸리지 않습니다"* 로 **이른 통과** |
| `tests/engine/test_empty_chain_fast_window.py` `test_b01` | 소환 · 세트 · 페이즈 이동만 셌다 (§8.2) |

🔴 **열려 있던 것은 둘째 자리 하나다.** 보완5 까지 *"체인이 비었다"* 와
*"판이 열렸다"* 가 같은 뜻이었으므로 그 이른 통과가 맞았고, 보완5 가
**체인이 비어 있는데 판이 열리지 않은 자리**를 만들면서 틀린 말이 되었다.

---

## 3. 기동 효과의 **별도** 조사와 재현

🔴 **일반 마법에서 재현됐다는 이유로 기동 효과까지 재현됐다고 적지 않았다.**
따로 판을 만들고 따로 쟀다.

### 3.1 어느 효과를 썼는가 — 기존 지원 효과를 먼저 찾았다

`EFFECT_LIBRARY` 18 항목에서 `activation_kind` 가 적힌 것은 둘뿐이다.

```
37742478:e[0]  IGNITION  exec=True  어니스트   ops=[CardOperation] targets=0
69811710:e[0]  TRIGGER   exec=True  기르수     ops=[CardOperation] targets=1
```

그래서 **합성하지 않고 실제 카드 어니스트 ①**을 썼다. `c37742478.lua` 가
`EFFECT_TYPE_IGNITION` + `SetRange(LOCATION_MZONE)` 로 등록하고 대상이
없다 — *"자신 필드의 이 카드를 패로 되돌린다"*.

🔴 **초기 판 구성만 손으로 했다** (그 카드를 앞면으로 내 몬스터 존에
둔다). 등재된 기동 효과를 필드에 내놓는 소환 경로는 이 범위가 아니다.
허가도 상태 변경도 주입하지 않았고, 이후 모든 변화는 `Duel.apply` 가 만든다.

### 3.2 🔴 **먼저 열린 상태에서 실제로 허용됨을 확인했다**

이것을 확인하지 않으면 차단 측정은 *"원래 후보가 없었다"* 와 구별되지 않는다.

```
1. 열린 상태   win=none chain=0
   🔵 기동 효과 후보 ['37742478:e[0]']
   열린 상태 발동 accepted=True code=OK
   해결: "체인1 P0 37742478:e[0] 를 해결했습니다."
   해결 뒤 내 패에 어니스트 있나 = True | MZONE []
```

**실제로 발동되고 해결되어 판을 바꾼다** (필드 → 패).

### 3.3 그리고 같은 카드가 빠른 효과 기회에서도 수락되었다

```
2. 몬스터 세트 accepted=True → win=response holder=0 chain=0
3. 빠른 효과 기회 허가 ['activate_effect', 'pass']
   🔴 기동 효과 후보 ['37742478:e[0]']
   🔴 Duel.apply accepted=True code=OK → 체인 [(1, '37742478:e[0]')]
```

**재현됨 — 통상 마법과 독립적으로.**

---

## 4. 판정 구조 — 열린 상태 · 유발 등재 · 빈 체인 빠른 효과 · 체인 응답

### 4.1 단계 정보를 **누가** 책임지는가

조사 결과 네 계층의 역할이 이미 갈려 있었고, 비어 있던 것은 **그 사이의
값 하나**였다.

| 계층 | 아는 것 | 모르는 것 |
|---|---|---|
| `GameStateView` | 페이즈 · 턴 플레이어 · 자리 | 체인 · 우선권 (판 밖에 산다 — ADR-007) |
| `PriorityState` | 창의 종류 · 쥔 자리 · 연속 패스 | 유발 등재가 남았는지 |
| `ActivationTiming` | 체인 · 우선권 (참조로) | **지금이 어느 단계인가** |
| `Duel` | `window_passed` · 등재 자리 · 체인 · 우선권 | — **여기가 안다** |

그래서 `ActivationTiming` 이 이미 쓰던 방식을 그대로 따랐다 — `point` ·
`set_this_turn` · `simultaneous` 셋이 전부 *"관측에 없고 판을 든 쪽이
읽어서 값으로 넘긴다"* 다. **네 번째 값**을 더했다.

```python
class ActivationStage(str, Enum):
    OPEN                  # 상자 A
    TRIGGER_REGISTRATION  # 그 기회의 유발을 등재한다
    FAST_WINDOW           # 상자 B · C
    CHAIN_RESPONSE        # 체인이 쌓여 있다
```

### 4.2 네 단계의 판정

```
ActivationTimingChecker.check(timing, action)
  ① _set_turn_refusal                      ← 그대로 (체인과 무관한 제약)
  ② 체인이 쌓여 있으면 → 기존 비교 그대로   ← 🔴 한 줄도 바꾸지 않았다
       simultaneous 면 통과 (룰북 — 동시 발동 묶음)
       스펠 스피드 비교 (RULE-CHAIN-003 · 004)
  ③ 체인이 비어 있으면 → _by_stage
       stage is None              → UNKNOWN / INFORMATION_UNAVAILABLE
       OPEN                       → 통과
       TRIGGER_REGISTRATION       → 통과 (유발은 대개 스펠 스피드 1)
       CHAIN_RESPONSE             → UNKNOWN (모순이다 — 지어내지 않는다)
       FAST_WINDOW                → 스펠 스피드 1 이면 INVALID
                                     그 밖은 통과
```

🔴 **"스펠 스피드 1 은 무조건 금지" 로 고치지 않았다.** 그렇게 하면
유발 등재가 막혀 **유발 효과가 발동되지 않는다** (기르수 ①은 몬스터
효과 = 스펠 스피드 1 이다). `test_d02` 가 그것을 센다.

### 4.3 `Duel._activation_stage` — 새 사실을 만들지 않는다

```python
if not self.chain.is_empty:        return CHAIN_RESPONSE
if self.priority.is_open:          return FAST_WINDOW
if self._window_claims(tp) or self._window_claims(1 - tp):
                                   return TRIGGER_REGISTRATION
return OPEN
```

네 갈래가 전부 `Duel` 이 이미 들고 있는 값에서 나온다. 실측한 전이:

```
열린 상태        stage=open
  ↓ 몬스터 세트
빠른 효과 기회    stage=fast_window      허가 ['pass']
  ↓ 양측 PASS
열린 상태        stage=open             허가 ['activate_effect', …]
  ↓ 발동
체인 응답 단계    stage=chain_response
```

그리고 유발이 있는 판에서는 `stage=trigger_registration` 이다.

### 4.4 🔴 보완6 이 스스로 낸 결함 둘 — 측정이 잡았다

#### ① 무한 재귀

처음에는 등재 단계를 `_registration_is_open()` 으로 물었다. 그쪽이
`_window_actor` → `_window_can_act` → **관문**을 지나고, 이 함수의 답이
바로 그 관문의 입력이다.

```
_activation_gate → _activation_stage → _registration_is_open
→ _window_actor → _window_can_act → _trigger_actions
→ _activation_gate → …
RecursionError: maximum recursion depth exceeded
```

고친 방식: **관문을 지나지 않는** `_window_claims` 로 묻는다 (창 ·
강제/임의 · 자격만 본다). 그 결과 "관문이 거절할 claim 만 남은 자리" 도
등재 단계로 세는데, **그것이 맞다** — 기회는 열려 있고 고를 것이 없을
뿐이고, 그 판정은 `_window_can_act` 가 따로 한다.

`test_a03` 이 **관문을 실제로 돌리는 판**(강제 묶음)에서 단계를 묻고
터지지 않는 것을 센다 — 그 판이 아니면 재귀가 재현되지 않는다.

#### ② 잘못된 `selections` 전달

`_refusal_verdict` 가 날 `action.targets` 를 관문에 넣었다 →
`AttributeError: 'ActionTarget' object has no attribute 'ref'`. 고친 방식:
`_apply_activation` 과 **같은** `selections_for` 환전을 쓰고, 환전이
실패하면 그 사실(`TARGET_COUNT_MISMATCH`)이 거절의 이유다.

---

## 5. 후보 생성 · 공통 관문 · 직접 apply · 보고 계층의 일치

### 5.1 같은 판정을 쓴다 — 실측

```
관문에 직접:  invalid SPELL_SPEED_TOO_LOW
              "판이 열려 있지 않아 스펠 스피드 1 은 발동할 수 없습니다
               (공식 Fast Effect Timing — 상자 A 에서만 할 수 있는
               행동입니다). 양쪽이 이 기회를 지나가면 판이 다시 열립니다."
              missing_rule = None

후보 목록:    []                            ← 같은 판정이 거른다
직접 apply:   accepted=False
              code = SPELL_SPEED_TOO_LOW    ← 같은 코드
              reason = (위와 **문자 단위로 동일**)
상태:         불변 (판 · 체인 · 우선권 · 기록 · 소비 묶음 비교)
```

`test_b04` 가 `verdict.reason == step.reason` 으로 그 동일성을 센다.

### 5.2 🔴 규칙이 막은 것을 "엔진 미지원" 으로 적지 않는다

`Duel.apply` 는 후보가 아닌 행위를 전부
`RULE_NOT_IMPLEMENTED`("이 저장소에 그 규칙이 없다") 하나로 답하고 있었다.
그래서 **규칙이 분명히 막은 발동도 미지원으로 보고되었다.**

보완6 은 `_refusal` / `_refusal_verdict` 로 **후보를 만든 그 관문**의
판정을 그대로 옮긴다. 관문이 `VALID` 면 막은 것은 흐름 계층(우선권 ·
차례 · 필수 처리)이므로 **예전 문장을 그대로** 쓴다 — 그쪽 이유를
지어내지 않는다.

측정된 효과 — 같은 `apply` 자리에서 나오던 한 문장이 실제 이유로 갈렸다.

| 상황 | 전 | 후 |
|---|---|---|
| 빠른 효과 기회의 통상 마법 | `RULE_NOT_IMPLEMENTED` | `SPELL_SPEED_TOO_LOW` |
| 세트한 턴의 함정 | `RULE_NOT_IMPLEMENTED` | `SET_THIS_TURN` |
| 대상 없는 효과에 대상을 줬다 | `RULE_NOT_IMPLEMENTED` | `TARGET_COUNT_MISMATCH` |
| `effect_ref` 와 `source` 가 다르다 | `RULE_NOT_IMPLEMENTED` | `EFFECT_REF_CARD_MISMATCH` |
| 흐름 계층이 막았다 | `RULE_NOT_IMPLEMENTED` | **그대로** |

### 5.3 세 사실이 서로 다른 코드를 받는다

| | validity / code |
|---|---|
| 규칙이 막는다 | `INVALID` / `SPELL_SPEED_TOO_LOW` |
| 부르는 쪽이 단계를 알려주지 않았다 | `UNKNOWN` / `INFORMATION_UNAVAILABLE` |
| 통과했다 | `VALID` / `OK` |

`test_f02` 가 셋을 나란히 센다. 그리고 `test_f01` 이 규칙 거절이
`unsupported()` 에 **들어가지 않음**을 센다 — 들어가면 `/combo` 가
그것을 고쳐야 할 공백으로 적는다.

### 5.4 생산 경로는 단계를 **반드시** 넘긴다

`test_g01` 이 `engine/duel.py` 의 `ActivationTiming(` 호출이 한 자리이고
그 자리가 `stage=` 를 넘긴다는 것을 AST 로 못박는다 — 넘기지 않으면
모든 발동이 `UNKNOWN` 이 되므로 그 자리가 조용히 비면 안 된다.

`test_g02` 는 `ResponseLoop.check_timing` 이 `stage` 를 **키워드로**
받고 기본값이 `None` 임을 센다.

🔴 **`ResponseLoop` 에 대한 내 첫 전제가 틀렸고 측정이 잡았다.** 처음에는
*"이 루프는 쌓인 체인에 링크를 더하는 자리"* 로 적고 단계를 넘기지
않았다. 그 루프는 **체인 1 을 여는 데도** 쓰인다 (실측: 빈 체인에서
`respond` 가 `REFUSED` · `missing='activation-stage …'`). 그래서
`act` → `_activate` → `check_timing` 으로 **넘기게** 했다.

---

## 6. 2링크 시나리오 — 실제 등록 · 해결 · 사건 · 후속 발동

### 6.1 구성 — 필요한 것은 새 카드가 아니라 **순서 선택**이었다

보완5 의 BLOCKER-F5-3 은 *"실제 카드로 둘째 링크를 세울 수단이 없다"*
였다. 🔴 **그럴 필요가 없었다.** 같은 기회의 유발 둘을 올리는 순서는
**고르는 쪽**의 것이고 (룰북 *"in any order"*, 보완4 가 구현), 합성 효과를
**CL1** 에 두면 실제 기르수 ①이 **CL2** 가 된다.

```
CL1 = 69811710:e[1]   합성 드로우 — 나중에 해결된다
CL2 = 69811710:e[0]   🔴 실제 기르수 ① — 덱의 카드를 묘지로 보낸다
후속 = 93920420:e[1]  🔴 실제 Lua 선언 (EVENT_TO_GRAVE) · 합성 조작
```

체인은 역순으로 풀리므로 **CL2 가 먼저** 해결되어 사건을 쓰고, 그때
CL1 이 아직 남아 있다.

🔴 `_PairOnce` — 보완5 의 `_Pair` 는 실제 원천의 **모든** 제안을 복제해
후속 제안까지 가짜 쌍을 만든다. 복제 대상을 기르수 ① 하나로 못박고
나머지는 **그대로 흘린다** — 후속 제안은 실제 `TriggerSource` 의 것이다.

### 6.2 11걸음 — 실측

```
 1. 소환 뒤 후보 ['69811710:e[1]', '69811710:e[0]']  stage=trigger_registration
 2. CL1 발동 accepted=True  체인=1
 3. CL2 발동 accepted=True  체인=2
    링크 [(1, '69811710:e[1]'), (2, '69811710:e[0]')]
    🔴 체인 도중 후보 [] []
 4. 패스 P1 체인=2  "우선권을 넘겼습니다."
 5. 패스 P0 체인=0  "체인1 P0 69811710:e[1] 를 해결했습니다."
 6. 저널 — **실행 순서**
      seq=1 EFFECT 69811710:e[0]   ← CL2 가 먼저
             #34 P0/DECK → P0/GRAVE (send_to_grave)
             P0 의 DECK 34장을 섞었다
      seq=2 EFFECT 69811710:e[1]   ← CL1 은 그 뒤
             P0 가 #7 를 드로우
    내 묘지 [93920420]
 7. 전부 해결된 뒤 후보 ['93920420:e[1]']   stage=trigger_registration
 8. 후속 발동 accepted=True  체인=1  holder=1  source=#34
 9. 중복 차단 — 후보 []  · 직접 재시도 accepted=False
10. 패스 P1 → 패스 P0  "체인1 P0 93920420:e[1] 를 해결했습니다."
11. 판 — 패 5 → 6 · 덱 33 → 32
    저널 seq=3 EFFECT 93920420:e[1]  "P0 가 #0 를 드로우"
    소비 기록 {69811710:e[0], 69811710:e[1], 93920420:e[1]}
12. 빠른 효과 기회(stage=fast_window, 허가 ['pass']) → 2 PASS
    → stage=open → END_PHASE 수락 → BATTLE
```

### 6.3 🔴 필수 실행 순서를 어떻게 입증했나

**중간에서 후보를 조회할 자리가 구조상 없다** —
`ChainResolver.resolve_all` 이 체인 전체를 한 `Duel.apply` 안에서
해결한다. §5 가 허락한 대로 테스트용 공개 step API 를 만들지 않았고,
그 사실을 숨기지도 않았다. 대신 **셋으로** 입증한다.

#### ① 저널의 실행 순서

`seq=1` 이 CL2, `seq=2` 가 CL1 이다 (§6.2). 🔴 **이것을 "규칙상 동시성"
으로 읽지 않는다** — 저널이 적는 것은 실행 순서이고, 여기서 재려는 것이
그것이다.

#### ② 해결 걸음의 체인 상태 — **가장 직접적인 증거**

`ChainResolver` 를 상속해 `super()` 를 그대로 부르고 결과만 적는 계측으로
기존 해결 경계를 읽었다.

```
(링크번호, 효과, 남은링크, 해결수, 완료)
(2, 69811710:e[0], 2, 1, False)   ← CL2 해결. 체인에 링크 2 · 해결 1 · 미완료
                                     🔴 즉 그 순간 CL1 이 남아 있었다
(1, 69811710:e[1], 2, 2, True)    ← 그 다음에 CL1 해결 · 완료
```

#### ③ 후보의 부재와 등장

체인이 서 있는 동안 양측 후보가 `[]` 이고, 전부 해결된 뒤에 나타난다.
🔴 **보완5 와 달리 이 값을 지연 처리의 증거로 쓰지 않는다** (§8.3) —
그 시점에는 사건이 아직 없다. 지연을 입증하는 것은 ①과 ②다.

#### 계측이 아무것도 바꾸지 않는다

`test_c03` 이 계측 있는 판과 없는 판을 대조한다 — `state_hash` · 저널
전체(순번 · 종류 · 효과) · 후보 · `consumed_events` 가 모두 같다.

---

## 7. 실제 카드 검증과 합성 검증의 구분

### 7.1 ① — **합성이 없다**

| | |
|---|---|
| 통상 마법 | 🔴 실제 `55144522` 욕망의 항아리 (열린 상태에서 2장 드로우까지 확인) |
| 기동 효과 | 🔴 실제 `37742478:e[0]` 어니스트 ① (필드 → 패까지 확인) |
| 허용되는 빠른 효과 | 🔴 실제 `5915629` 욕망의 선물 (상대 패 2 → 4) |
| 유발 등재 | 🔴 실제 `69811710:e[0]` 기르수 ① |
| 손으로 한 것 | **초기 판 구성뿐** — 어니스트를 앞면으로 몬스터 존에 둔다 |

### 7.2 ② — 조작 **둘**이 합성이다

| | 실제 | 합성 |
|---|---|---|
| 카드 `69811710` · `93920420` | 🔴 cdb · Lua | — |
| 기르수 ①의 조작 (덱 → 묘지) | 🔴 실제 | — |
| 그 사건 · 번호 · 개체 · 자리 | 🔴 실제 | — |
| 후속의 시점 선언 (`EVENT_TO_GRAVE`) | 🔴 실제 Lua | — |
| 후보 생성 · 다섯 관문 · 체인 · 응답 · 해결 · 소비 | 🔴 실제 | — |
| **CL1 의 조작** (드로우 1장) | — | 합성 |
| **후속의 조작** (드로우 1장) | — | 합성 |

🔴 **그래서 실제 카드 지원 완료가 아니다.** `test_h01` 이 프로덕션
등록부에 두 합성 정의가 **없다**는 것을 센다. `test_h03` 은 그 반대쪽을
센다 — **CL2 와 그 사건은 합성이 아니다.**

### 7.3 금지 사항 — 지킨 것을 적는다

| §5 가 금지한 것 | 지킨 방식 |
|---|---|
| 체인 링크 직접 주입 | 둘 다 `legal_actions` → `Duel.apply` (`test_a01`) |
| 발동 허가 직접 주입 | `authorization` 은 관문이 낸 판정 그대로 |
| 사건 순번을 바꿔 위장 | 손대지 않았다 — `_PairOnce` 는 `effect_ref` 칸만 바꾼다 |
| 소비 기록 · 최종 상태 주입 | 전부 `Duel.apply` 가 적는다 (`test_d03`) |
| 원하는 시점의 제안 하드코딩 | 후속 제안은 실제 `TriggerSource` 가 만든다 |
| 사건 **전**의 빈 후보로 지연 입증 | §6.3 ③ 이 그 한계를 명시한다 |

---

## 8. 원본 · 사본의 일치와 분기 격리

| 재는 것 | 결과 | 시험 |
|---|---|---|
| 빈 체인 빠른 효과 단계의 **단계** 일치 | 완료 | `fast_window_legality::test_e01` |
| 같은 자리의 합법 후보 · 직접 apply 판정 일치 | 완료 | 같음 (`accepted` · `code` 둘 다) |
| 사본의 PASS 가 부모 기회를 닫지 않음 | 완료 | `test_e02` — 원본은 여전히 `fast_window`, 후보 `[]` |
| 2링크 체인의 사본 상태 보존 | 완료 | `two_link::test_e01` (링크 · `resolved_count` · 단계 · 후보) |
| 사본이 체인을 풀고 후속까지 써도 원본 불변 | 완료 | `test_e02` — `state_hash` · 체인 · 소비 · 저널 길이 |

---

## 9. Simulator · `/combo` 와 기존 경로 보존

### 9.1 Simulator — 실측

```
① 열린 상태 발동   status=SUPPORTED code=OK
   reason: "체인1 P0 55144522:e[0] 를 해결했습니다."   ← 해결 결과가 보존된다
   unsupported=1 (기존 activate_card 축)
② 빠른 효과 기회   status=NOT_A_CANDIDATE
   reason: "지금 허가된 후보가 아닙니다 — 탐색은 후보만 해 봅니다."
   🔴 "엔진 미지원" 으로 적지 않는다
③ PASS 모의        status=SUPPORTED
   reason: "양쪽이 빠른 효과 기회를 지나갔습니다 — 판이 다시 열렸습니다."
   unsupported 전달됨
```

### 9.2 `/combo` — **걸음 기록까지 동일**

기준 커밋 `263c13b` 를 별도 worktree 에 두고 (`data/cards.cdb` 와
`data/constants` 를 연결) 같은 입력을 돌렸다.

```
263c13b   정상: 메시지 4개 6166자
보완6     정상: 메시지 4개 6166자
```

```
걸음 수 = 5 | stopped_kind = unsupported
  ✔ 1. P0 normal_summon    기르수        이유: normal_summon 를 적용했습니다 (1건).
  ✔ 2. P0 activate_effect  69811710:e[0] 이유: 체인1 P0 69811710:e[0] 를 해결했습니다.
  ✔ 3~5. P0 set_spell_trap               이유: set_spell_trap 를 적용했습니다 (1건).
```

🔴 **실행 경로도 걸음 수도 바뀌지 않았다.** 이유: 이 보드의 전개는 열린
상태에서만 스펠 스피드 1 을 발동하고, `_settle_chain` 이 빠른 효과 기회를
이미 지나고 있다. 보완6 이 좁힌 것은 **열려 있지 않은 자리**뿐이다.

거절 경로도 그대로다 — 메시지 1개 · 1,740자 · *"패의 매수가 덱 보유 매수
이내인가: 기르수 [69811710]: 패 4장 > 덱 3장"*.

🔴 **토큰 없는 문자열 검사이고 실제 Discord 접속 검증이 아니다.**

### 9.3 기존 경로 보존

| | 결과 |
|---|---|
| 기르수 소환 → 유발 → 해결 시점 AI 선택 → Deck → Graveyard | 유지 (`/combo` 걸음 2 · `tests/engine` 3856 passed) |
| 체인 응답 단계의 스펠 스피드 제약 | 유지 — **이유 문장까지 예전 것**이다 (`test_d04`) |
| 같은 기회의 복수 유발 등재와 묶음 순서 | 유지 (`test_d03`) |
| UNKNOWN 차단 | 유지 — 단계를 못 받으면 `UNKNOWN` 이고 허가가 아니다 |
| 해결 결과가 PASS 문장으로 덮이지 않음 | 유지 (보완5 의 네 자리 그대로) |

---

## 10. 실행한 시험 — 명령 · 결과 · 시간 · **실제 종료 코드**

🔴 **harness 가 보여 주는 종료 코드는 감싼 쉘의 것이다.** 그래서 모든
실행을 작은 래퍼로 돌려 로그 끝에 `PYTEST_EXIT=<코드>` 를 적고, **그
숫자만** 아래에 옮긴다.

```bash
# runtests.sh <로그파일> <pytest 인자...>
LOG="$1"; shift
timeout 7000 python3 -m pytest "$@" -q -rf > "$LOG" 2>&1
CODE=$?
echo "PYTEST_EXIT=$CODE" >> "$LOG"   # 로그만 남은 뒤에도 판단할 수 있게
exit $CODE
```

🔴 보완 단계들에서 내가 쓴
`nohup timeout N python3 -m pytest … > log 2>&1 &` 뒤의 `$?` 는
**백그라운드로 보낸 결과**이고 pytest 의 종료 코드가 아니었다. 실측: 실패가
있는 묶음을 직접 돌리면 `1`, `&` 뒤의 `$?` 는 `0`. 그래서 보고서에
"종료 코드 0" 을 적고 그 이유를 지어낸 전례가 있다 — 이 래퍼가 그것을
막는다.

### 10.1 검증 순서 — 최소 재현 → 타깃 → 관련 통합 → 필요한 회귀

| 순서 | 무엇 | 결과 |
|---|---|---|
| ① 최소 재현 | 검토 기준 HEAD `263c13b` 에서 통상 마법 · 기동 효과의 불법 발동 (§2 · §3) | **둘 다 재현** — pytest 가 아니라 직접 실행이다 |
| ② 타깃 | 새 파일 둘 | `40 passed` · `PYTEST_EXIT=0` |
| ③ 관련 통합 | `tests/engine` 전체 | `3856 passed` · `PYTEST_EXIT=0` |
| ④ 필요한 회귀 | `tests/agent` + `rules` + `rulings`, 그리고 root 92 파일 | §10.3 |

### 10.2 타깃과 관련 통합

| 명령 | 결과 | 시간 | `PYTEST_EXIT` |
|---|---|---|---|
| `tests/engine/test_fast_window_legality.py` (23) + `tests/engine/test_two_link_followup_trigger.py` (17) | **40 passed** | 37.4초 | **0** |
| `tests/engine` | **3856 passed** | 719.7초 (11:59) | **0** |

🔴 `tests/engine` 의 3856 은 `test_d06` (속공 마법)을 **더하기 전**의 수다.
그 시험은 회귀 조각들을 돌리는 중에 발견한 공백을 메우려고 뒤에 더했고
(사용자 ③의 "속공 마법"), 더한 뒤 그 파일을 다시 돌려 **23 passed ·
`PYTEST_EXIT=0`** 을 확인했다. 지금 `tests/engine` 을 돌리면 3857 이다 —
**그 수를 직접 재지 않았으므로 그렇게 적지 않는다.**

`tests/engine` 의 **첫 실행은 34 failed / 3783 passed** 였다. 전부
`ActivationTiming` 을 단계 없이 만들던 자리이거나 **일반 거절 문장**을
기대한 자리이고, 하나하나 실측값으로 고쳤다. 기대값을 느슨하게 한 자리는
없다 — 일반 문장을 기대하던 자리는 실제로 나오는 **더 좁은** 이유
(`SET_THIS_TURN` · `TARGET_COUNT_MISMATCH` · `EFFECT_REF_CARD_MISMATCH`)
로 바꿨다.

### 10.3 필요한 회귀 — root 92 파일과 agent 묶음

🔴 **왜 돌렸는가.** 보완6 이 공유 계약 둘을 건드렸다 —
`ActivationTiming.stage` (구성 자리 28곳) 와 `Duel.apply` 의 거절
코드·이유다. 둘 다 저장소 전역의 감사가 못 박고 있고, 특히 탐색 랭킹
digest 를 **22개 파일**이 각각 적는다 (그중 8개는 해시까지).

🔴 **왜 쪼갰는가.** 배경 명령의 상한이 30분이고 보완5 에서 통짜 실행이 두
번 잘렸다. `tests/*.py` 92 파일을 12 파일씩 여덟 조각으로 나눴다.
**잘린 실행을 통과로 합산하지 않는다** — 아래는 전부 `PYTEST_EXIT` 가
찍힌 완주 실행이다.

| 조각 | 결과 | 시간 | `PYTEST_EXIT` |
|---|---|---|---|
| `tests/agent` + `rules` + `rulings` | 4 failed · 524 passed · 1 skipped | 346.1초 (5:46) | **1** |
| rootA 1 | 6 failed · 331 passed | 864.1초 (14:24) | **1** |
| rootA 2 | 309 passed | 609.4초 (10:09) | **0** |
| rootA 3 | 1 failed · 380 passed | 738.7초 (12:18) | **1** |
| rootA 4 | 1 failed · 215 passed · 1 skipped | 188.1초 (3:08) | **1** |
| rootB 1 | 7 failed · 320 passed · 8 skipped | 702.8초 (11:42) | **1** |
| rootB 2 | 2 failed · 252 passed | 110.4초 (1:50) | **1** |
| rootB 3 | 1 failed · 235 passed | 131.3초 (2:11) | **1** |
| rootB 4 | 1 failed · 262 passed | 379.4초 (6:19) | **1** |
| **root 합** | **19 failed · 2304 passed · 9 skipped** | **3724.0초 (62분)** | — |

### 10.4 19개 실패를 셋으로 갈랐다

| | 수 | 무엇 |
|---|---|---|
| **기존 실패** | 6 | §11.1 — 보완6 이전부터 같은 이름으로 실패하던 자리 |
| **내 변경이 움직인 측정값 핀** | 13 | 아래 표. 실측값으로 갱신하고 **왜 움직였는지** 각 자리에 적었다 |
| **내 변경의 미처리 회귀** | **0** | 남긴 것이 없다 |

`tests/agent` 묶음의 4개도 같은 방식이다 — 기존 2 + 핀 2.

| 자리 | 전 → 후 | 근거 |
|---|---|---|
| 탐색 랭킹 digest (22개 파일 중 8개가 조각 실행에서 걸렸다) | `decisions` 979 → **1065**, 해시 `a864ac09…` → `9bc5fadb…` | 빠른 효과 기회에서 스펠 스피드 1 후보가 사라지면 그 자리의 유일한 행동이 `PASS` 가 되고, 양측이 지나가며 판이 다시 열린다 — **공식 도표가 요구하는 절차**가 걸음으로 나타난다. 두 번 돌려 같은 값임을 확인했다. 종류별로는 `pass` 459 · `end_phase` 378 · `set_spell_trap` 71 · `normal_summon` 66 · `attack` 60 · `activate_effect` 31 |
| `test_legal_action_engine_boundary_audit::test_03` | 단계 없이 `ActivationTiming` 을 만들어 `UNKNOWN` | `stage=duel._activation_stage()` 를 넘기고 단계가 `OPEN` 임과 이유가 *"판이 열려 있어"* 임을 **추가로** 센다 |
| `test_rule_not_implemented_code_audit` (2건) | 문자열 89 → **91** | **코드 수 74 는 그대로**다 — 늘어난 둘은 전부 산문이다. 좌표 목록도 실측값으로 맞췄다 |
| `test_unimplemented_rule_semantics_audit::test_03` | `RULE_NOT_IMPLEMENTED_MENTIONS` 89 → **91** | 같은 둘이고, `UnimplementedRule` 생성 자리 수는 **그대로**다 — 이 파일이 지키는 구분(그 코드와 `UnimplementedRule` 은 다른 개념)이 보완6 에서 **실제로 쓰인 자리**다 |
| `test_trigger_pipeline_dormant_audit::test_25` | `activation_timing.py` 원본 618 → **804** | 문자열에 둔감한 핀도 233 → **276** 으로 갱신했다 — **실행 코드 43줄**이고 나머지 143줄은 설명이다 |
| `tests/agent` 의 핀 2건 | 후보 수 · `all(r >= c)` | §11.2 |

#### 확인 실행 — 고친 핀을 **한 번에** 다시 돌렸다

조각 전체를 다시 돌리지는 않았다. 그 조각 안에서 바뀐 파일은 내가 고친
파일뿐이고, **걸렸던 15개 시험을 한 번의 실행으로 다시 돌려** 확인했다.

```
tests/test_branch_setter_audit.py::test_29_the_search_ranking_digest_is_unchanged
tests/test_actor_relation_boundary_audit.py::test_19_this_phase_changed_nothing_in_production
tests/test_actor_semantic_contract.py::test_14_the_search_ranking_is_untouched
tests/test_actor_role_separation_audit.py::test_23_this_phase_changed_nothing
tests/test_activation_precondition_audit.py::test_26_the_search_ranking_digest_is_unchanged
tests/test_activation_action_semantic_boundary_audit.py::test_30_the_search_ranking_digest_is_unchanged
tests/test_official_activation_player_action_contract.py::test_25_the_search_ranking_digest_is_unchanged
tests/test_legal_action_engine_boundary_audit.py::test_30_the_search_ranking_digest_is_unchanged
tests/test_legal_action_engine_boundary_audit.py::test_03_everything_offered_is_actually_executed
tests/test_rule_not_implemented_code_audit.py::test_05_...
tests/test_rule_not_implemented_code_audit.py::test_02_...
tests/test_trigger_pipeline_dormant_audit.py::test_25_this_phase_changed_no_production_file
tests/test_unimplemented_rule_semantics_audit.py::test_03_...
tests/agent/test_rule_based_ai.py::test_f_greedy_is_not_the_best_play
tests/agent/test_attack_action_space.py::test_defence_position_is_now_reachable_through_legal_actions

15 passed in 254.09s (0:04:14)
PYTEST_EXIT=0
```

🔴 같은 10분 실행을 근거 없이 반복하지 않는다는 §7 을 따랐다. 조각
**사이의** 상호작용은 재지 않았고, 그것을 §11.4 에 한계로 적는다.

#### skip 의 사유 — **하나도 더하지 않았다**

| 묶음 | skip | 사유 (실측) |
|---|---|---|
| `tests/agent` + `rules` + `rulings` | 1 | `tests/rules/test_extraction_determinism.py:20: PyMuPDF 없음 (추출기 전용 의존성)` |
| rootA 4 | 1 | `tests/test_korean_collector.py:88: 수집 캐시 없음` |
| rootB 1 | 8 | `pytest.skip("이 Phase 의 commit 이 아직 없다")` — 해당 Phase 의 커밋을 git 로그에서 찾는 감사들과 `tests/test_lua_loader.py` 의 `"샘플 스크립트 없음"` |

전부 보완6 **이전부터** 있던 자리이고, 자료나 커밋이 없을 때만 걸린다.
`tests/test_lua_verified_provenance_audit.py::test_39`
(*"기존 테스트 삭제 · skip 추가가 없다"*) 가 그것을 따로 센다 — 그 시험은
통과했다 (rootB 1).

### 10.5 데이터 준비 상태 · 버전 · 출처

| | |
|---|---|
| `data/cards.cdb` | 있음 — **14,759 행** (`datas` · `texts` 각각). 세션 시작 훅이 내린다 |
| `data/constants` | 있음 — **git 추적 대상이 아니다**. worktree 비교에서 이것을 빠뜨려 한 번 틀린 수치를 얻었고 (§12.2) 연결해서 다시 쟀다 |
| 공식 Lua 스크립트 | 있음 — `c37742478.lua` · `c69811710.lua` · `c93920420.lua` 를 §3 · §7 에서 인용했다 |
| 룰북 | `data/rules/documents/sd-rulebook-en-v10.json` (Konami Structure Deck 룰북 v10) |
| 공식 도표 | Fast Effect Timing (`yugioh-card.com/en/play/fast-effect-timing/`) — 상자 A · B · C 를 §4 에서 인용했다 |
| 한국어 자료 · 수집 캐시 | 일부 없음 → 위 skip 9 |
| Discord 토큰 | **없음** — §9.2 는 토큰 없는 문자열 검사이고 **실제 접속 검증이 아니다** |

---

## 11. 기존 실패 · 신규 회귀 · 남은 BLOCKER · 검증의 한계

### 11.1 기존 실패 8개 — 보완6 이 만든 것이 아니다

보완5 보고서에도 같은 이름으로 적혀 있고, 보완6 의 변경과 닿는 자리가
없다 (자료 부족이거나 범위 밖이다).

| 파일 | 시험 | 성격 | 조각 |
|---|---|---|---|
| `tests/rulings/test_data_audit.py` | `test_every_repository_card_can_reach_a_cid` | 카드 DB 자료 | agent 묶음 |
| `tests/agent/test_opponent_resource_weighting_audit.py` | `test_07` | 전략 평가 (범위 밖) | agent 묶음 |
| `tests/test_effect_type_quick_audit.py` | `test_29` | 공식 자료 어휘 | rootA 3 |
| `tests/test_event_free_chain_semantic_audit.py` | `test_27` | 공식 자료 어휘 | rootA 4 |
| `tests/test_korean_overlay_unapplied_audit.py` | `test_01` · `test_13` · `test_21` · `test_25` | 한국어 자료 없음 | rootB 1 |

### 11.2 신규 회귀 — **0건**

내 변경이 깬 뒤 **고치지 못한 채 남긴** 자리는 없다. 닿은 자리는 전부
둘 중 하나였다.

| | 수 | 처리 |
|---|---|---|
| 측정값 핀 | engine 34 · root 13 · agent 2 | 실측값으로 갱신하고 각 자리에 근거를 적었다 |
| **내가 만든 실제 결함** | 2 | §4.4 — 무한 재귀와 잘못된 `selections`. 둘 다 고치고 각각 시험으로 못 박았다 (`test_a03` · `test_b04`) |

🔴 **필수 절차와 합법 후보가 바뀌어 실행 경로 · 걸음 수가 달라진 자리를
근거와 함께 적는다** (사용자 §6 요구). 이전 수치에 맞추려고 잘못된 동작을
유지한 자리는 없다.

| 바뀐 것 | 전 → 후 | 근거 |
|---|---|---|
| 탐색 `decisions` | 979 → **1065** | 빠른 효과 기회에서 스펠 스피드 1 이 후보에서 빠지면 그 자리는 `PASS` 뿐이고, 양측이 지나가야 판이 다시 열린다. 공식 도표가 요구하는 절차다 |
| `set_spell_trap` 후보 | 16 → **56** | 🔴 **보완5 이전 값으로 돌아왔다.** 보완5 가 열어 둔 자리에서 세트가 빠른 효과 기회의 후보로 섞여 분포가 틀어져 있었다 |
| `tests/agent/test_f_greedy_is_not_the_best_play` | `all(r >= c)` 가 깨졌다 | 🔴 **Phase 3-B 의 원래 근거가 돌아왔다** — 씨앗 3 (5500 < 6500) 과 씨앗 16 (5700 < 7900). 느슨하게 하지 않고 그 사실을 못 박았다 |
| `tests/agent/test_defence_position_is_now_reachable_through_legal_actions` | 후보 수 | 같은 결 — 빠른 효과 기회가 절차를 하나 더 요구한다 |
| `/combo` 걸음 수 | **5 → 5 (불변)** | §9.2. 그 전개는 열린 상태에서만 스펠 스피드 1 을 발동한다 |

### 11.3 남은 BLOCKER — 네 갈래로 구분한다

사용자 §8 의 요구대로 **성능 비용 · 미지원 기능 · 정확성 결함 · 검증
부족**을 섞지 않는다. 그리고 *"성능 비용이나 API 표현 방식 자체를 정확성
BLOCKER 로 만들지 않는다"* 를 따른다.

#### 정확성 결함 (규칙이 틀릴 수 있다)

| | 무엇 |
|---|---|
| **BLOCKER-F6-1** | 🔴 **기동 효과의 거절 코드가 `SPELL_SPEED_TOO_LOW` 가 아니다.** 차단 자체는 성립한다 — 후보에서 빠지고 `apply` 가 거절하고 판이 바뀌지 않는다. 그런데 코드는 `UNKNOWN` / `RULE_NOT_IMPLEMENTED` 이고 `missing = MONSTER_CLASSIFICATION_MISSING` 이다: 관문이 몬스터 효과를 "기동 · 유발 · 플립" 과 "유발즉시" 로 가르는 축을 갖고 있지 않다. 그 축을 심는 일은 ①·② 밖이고 저장소 전역에 기록된 `UNKNOWN` 이라 건드리지 않았다. `test_c02` 가 **실측된 사실**을 센다 — 통과시키려고 기대값을 바꾼 것이 아니다 |
| **BLOCKER-F6-2** | `Duel.apply` 가 **흐름 계층**(우선권 · 차례 · 필수 처리)의 거절에는 여전히 *"아직 구현하지 않은 규칙"* 문장을 쓴다. 관문이 `VALID` 를 낸 자리이므로 이유를 **지어내지 않고** 예전 문장을 그대로 둔 것이고 (§5.2), 그 문장이 그 자리에 대해 부정확하다 |
| **BLOCKER-F5-1** | 「경우」 효과의 **장소 검사** — 보완5 그대로. `graveyard_zone_for` 가 반쪽을 메웠다 |
| **BLOCKER-F5-2** | 강제 「때」가 타이밍을 놓친 경우 `UNKNOWN` — 6-AB 이래 그대로. 공식 근거를 찾지 못했다 |

#### 미지원 기능 (규칙은 알지만 수단이 없다)

| | 무엇 |
|---|---|
| **BLOCKER-F5-4** | SEGOC 의 5~7 순위 — 네 묶음만 구현했다 |
| **BLOCKER-F5-5** | 묘지 **밖** 도착지의 발동 자리 (`UNKNOWN` 유지) |
| **BLOCKER-F5-6** | 스펠 스피드 2 전체 — `EFFECT_LIBRARY` 18 항목 밖은 후보가 되지 않는다 |
| **BLOCKER-F5-7** | 묶음 안 순서를 **한 번의 호출**로 쌓는 API 가 없다 (관측되는 규칙 차이는 없다) |
| **BLOCKER-F5-8** | `93920420` ②의 실제 효과(특수 소환) 미구현 — ②의 조작은 합성이다 (§7) |

#### 검증 부족 (구현은 있으나 재지 못했다)

| | 무엇 |
|---|---|
| **BLOCKER-F5-3** | 🔴 **해소됐다.** §6 이 2링크에서 CL2 의 사건 → CL1 해결 → 후속 등록 → 후속 해결을 실제로 쟀다. 그리고 보완5 의 진단(*"실제 카드로 둘째 링크를 세울 수단이 없다"*)이 **틀렸다** — 필요한 것은 묶음 안의 **순서 선택**이었다 (§12.4) |
| **BLOCKER-F5-9** | 창에 사건이 하나뿐이다 — 어휘 판정(「때 / 경우」)이 실행 경로에서 답을 가르지 않는다 |
| **BLOCKER-F5-10** | 비공개 영역(덱 · 패) 유발의 순서 — 조사만 했다 |
| **BLOCKER-F5-11** | 실제 Discord 접속 — 토큰 없음 (§9.2 는 문자열 검사다) |
| **BLOCKER-F6-3** | 🔴 **상대(비턴 플레이어)가 빠른 효과 기회에서 발동하는 자리**를 실제 카드로 재지 못했다. 보완6 의 측정은 전부 **턴 플레이어** 쪽이다 (`test_d01` 의 함정과 `test_d06` 의 속공 마법 둘 다 `P0` 가 자기 턴에 발동한다). 기회 자체가 양측으로 도는 것은 보완5 가 실었고 `test_a03` 이 `_window_actor() == P1` 을 센다 — 그 자리에서 **발동**까지 가는 측정은 없다 |

#### 성능 비용 (정확성과 무관 — BLOCKER 로 만들지 않는다)

| | 무엇 |
|---|---|
| **BLOCKER-F5-12** | `_window_can_act` 가 강제 묶음일 때 관문을 두 번 돌린다. 임의 묶음에서는 돌리지 않는다 |
| **BLOCKER-F5-13** | 판을 바꾸는 행위마다 `PASS` 둘이 더 필요하다 — 공식 도표가 요구하는 절차이고 **비용이지 결함이 아니다** |
| **BLOCKER-F6-4** | `_refusal_verdict` 가 **거절 한 건마다** 관문을 한 번 더 돌린다. 수락 경로에는 없다 (거절할 때만 이유를 묻는다) |

### 11.4 이번 검증의 한계 — 명시한다

| | |
|---|---|
| 전체 회귀를 **한 번의 실행으로** 돌리지 않았다 | 여덟 조각이고 조각마다 `PYTEST_EXIT` 를 남겼다. **조각 사이의 상호작용은 재지 않았다** |
| 고친 파일만 다시 돌렸다 | 조각 전체의 재실행이 아니다 (§10.4) |
| `tests/integration` · Discord | 토큰이 없어 §9 의 문자열 검사로 갈음했다 — **접속 검증이 아니다** |
| 기동 효과의 시작 판 | 손으로 구성했다. 등재된 기동 효과를 필드에 내놓는 소환 경로는 범위 밖이다 (§3.1) |
| ②의 CL1 조작과 후속 조작 | **합성**이다. CL2 와 그 사건은 **실제**다 (§7) |
| 기동 효과의 거절 **코드** | 구분이 성립하지 않는다 — BLOCKER-F6-1 |

---

## 12. 선행 보고서(보완5)의 정정

보완5 보고서
`docs/phase6ab-followup5-empty-chain-fast-window-and-followup-trigger.md`
머리에 **§0 정정 안내**를 더하고 본문 §4.3 의 판정표도 고쳤다.
**원래 문장을 지우지 않고** 무엇이 틀렸는지 적는 방식이다.

### 12.1 "빠른 효과 기회에서 열린 상태 전용 발동을 모두 차단했다"

🔴 **차단하지 않았다.** 보완5 는 빈 체인에서 양측 기회를 열었고, 관문은
*"체인이 비어 있어 스펠 스피드 제약이 걸리지 않습니다"* 로 **통과**를
냈다. 그 기회에서 통상 마법과 기동 효과가 **실제로 발동 가능했다**
(§2 · §3). 보완5 의 그 자리를 "부분 완료" 로 고쳤다.

### 12.2 "`test_b01` 이 일반 마법 · 기동 효과까지 검증했다"

🔴 `test_b01` 은 소환 · 세트 · 페이즈 이동만 센다. **발동 가능한 판을
구성하지 않았으므로** 금지가 검증된 것이 아니다 — 후보가 원래 없었다.
보완6 은 §3.2 처럼 **먼저 열린 상태에서 실제로 허용됨을 확인하고 나서**
차단을 쟀고, 기동 효과를 통상 마법과 **따로** 조사했다.

함께 발견한 수치 오류도 적었다 — 보완5 가 적은 `/combo` 의 "6,189자" 는
보완5 자신의 `_settle_chain` 수정 **전**에 쟀다. 기준 커밋 `263c13b` 를
worktree 에 두고 다시 재어 **6,166자**를 얻었다 (첫 시도는
`data/constants` 를 연결하지 않아 걸음 2 가 불발하고 6,208자가 나왔다).

### 12.3 "사건 발생 **전**의 빈 후보 조회" 를 지연 처리의 증거로 썼다

🔴 `_resolved_girsu()` 의 `links_during` 조회는 기르수 발동 **직후**, 즉
묘지 이동 사건이 **발생하기 전**이다. 그때 후보가 없는 것은 당연하고
*"이미 발생한 후속 사건이 남은 링크 해결을 기다린다"* 의 증거가 아니다.
보완6 은 §6.3 처럼 **사건이 저널에 적힌 그 시점**에 CL1 이 아직 서 있음을
해결기 쪽에서 쟀다.

### 12.4 "2링크 검증에 신규 실제 카드 지원이 반드시 필요하다"

🔴 **필요하지 않았다.** 필요한 것은 같은 기회에 등재된 묶음의 **순서
선택**이고 그것은 보완4 가 이미 구현했다 (룰북 §*When multiple cards are
activated simultaneously* — *"in any order"*). 같은 기회에 두 발동을
등재하고 해결 순서를 고르면 2링크가 선다. BLOCKER-F5-3 의 진단이 틀렸다.

### 12.5 🔴 미완료된 실행 검증을 문서 문제로 축소하지 않는다

위 넷 중 §12.1 과 §12.3 은 **문서 표현의 문제가 아니다** — 앞은 실제로
막히지 않는 발동이 있었다는 **규칙 결함**이고, 뒤는 **입증되지 않은 실행
순서**였다. 보완6 이 둘 다 코드와 측정으로 메웠고, 그 사실을 "보고서를
고쳤다" 로 적지 않는다. 반대로 §12.2 의 수치와 §12.4 의 진단은 보고서
쪽의 잘못이고 그것은 그것으로 적는다.

---

## 13. 두 목표의 판정

🔴 **통과한 시험 수로 완료를 주장하지 않는다.** 아래 근거는 전부 "무엇을
어떤 판에서 쟀는가" 이고, 시험은 그 측정이 회귀하지 않게 못 박은 것이다.

| 목표 | 판정 | 근거 |
|---|---|---|
| ① 빈 체인의 빠른 효과 기회에서 **열린 상태 전용 발동 차단** | **완료** | 통상 마법과 기동 효과를 **각각** 열린 상태에서 먼저 허용됨을 확인하고 나서 차단을 쟀다 (§3.2 · §3.3 · §4). 후보 생성 · 직접 `apply` · 내부 공통 관문 · 보고 계층이 **같은 단계 정보**를 쓴다 (§5). 거절이 판 · 체인 · 우선권 · Journal · 소비 기록을 바꾸지 않는다 (§5.1). 적법한 함정과 **속공 마법**은 그대로 허용된다 (`test_d01` · `test_d06`), 스펠 스피드 1 유발 등재도 그대로다 (`test_d02`), 같은 기회의 복수 등재와 묶음 순서도 그대로다 (`test_d03`), 체인 응답 단계의 제약은 **이유 문장까지** 그대로다 (`test_d04`). 규칙상 불가능한 행동과 판정 근거가 없는 `UNKNOWN` 이 다른 코드를 받는다 (§5.3) |
| ② 2링크 체인 해결 중 발생한 사건의 **후속 유발 통합 검증** | **완료** | CL2 의 사건 발생 → CL1 해결 → 후속 유발 등록 → 후속 효과 해결을 §5 금지 목록(링크 직접 주입 · 발동 허가 주입 · 사건 순번 조작 · 소비 기록·최종 상태 주입 · 시점 하드코딩 · 사건 발생 전의 빈 후보)을 전부 피해서 쟀다 (§6). 공개 `step` API 를 새로 만들지 않고 **저널 순서**와 **해결기 쪽 읽기 전용 계측** 두 층으로 입증했고, 계측이 허가 · 상태 · 제어 흐름을 바꾸지 않음을 따로 쟀다 (`test_c03`) |

①의 **거절 코드 구분**은 완료에 포함시키지 않았다 — 기동 효과에서
`SPELL_SPEED_TOO_LOW` 가 아니라 `UNKNOWN` 이 나온다 (BLOCKER-F6-1).
차단은 성립하고 **코드의 정확성은 성립하지 않는다**, 그 둘을 섞지 않는다.

---

## 14. 범위 · 다음 Phase

| | |
|---|---|
| Engine V1 책임 분리 | 유지 — 규칙 · 필수 절차 · 합법성 · 상태 변경은 `engine`, 판단은 AI, 전달과 변환은 연결 계층 |
| ADR-007 | 유지 — `engine` 은 `core` 를 가져오지 않는다. 단계는 판을 든 쪽이 **값으로** 넘긴다 (`point` · `set_this_turn` · `simultaneous` 와 같은 자리) |
| 둘째 규칙 엔진 | 만들지 않았다 — 판정하는 자리는 `ActivationTimingChecker` 하나다 (`test_g03` · `test_activation_timing.test_f_no_second_timing_system_was_built`) |
| 문자열 분석 · 후보 숨김 · 카드 ID 예외 | 하나도 쓰지 않았다 (§4 · `test_g01`) |
| 범위 밖 | 신규 소환 기능 · 전략 평가 · 학습 · EDOPro·리플레이 연동 · 검색 기능 · 카드·금제 업데이트 · 광범위한 최적화 — 손대지 않았다 |
| 광범위한 공개 계약 변경 | 없음. `ActivationTiming.stage` 와 `ResponseLoop.check_timing(stage=…)` 은 **기본값 `None`** 이고 넘기지 않으면 `UNKNOWN` 이다 — 조용한 허가가 되지 않는다 |
| 다음 Phase | 🔴 **시작하지 않았다** |
