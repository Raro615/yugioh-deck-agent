# Phase 6-AB 보완7 — 확인된 효과 분류의 전달과 거절의 뜻

🔴 **먼저 적어 두는 다섯 가지**

1. **목표를 완료로 판정한다.** 어니스트 ①(실제 기동 효과)의 빠른 효과
   기회 거절이 `INVALID` / `SPELL_SPEED_TOO_LOW` / `missing_rule=None` 이고,
   분류가 **실제로 없는** 효과는 `UNKNOWN` 그대로다 (§5). 근거는 측정이고
   통과한 시험 수가 아니다.
2. **고칠 정보는 이미 저장소에 있었다.** 보완6 이 *"그 축을 심는 일은 범위
   밖"* 으로 적었는데, 그 축은 `EffectDefinition.activation_kind` 로 **이미
   손으로 적혀 검증되어 있었다** (ADR-006). 없던 것은 그 값이 관문까지 가는
   길 하나다 — 바꾼 production 파일이 **네 개**다 (§1 · §3).
3. **같은 결함이 체인 응답에도 있었고 함께 메웠다.** 전 턴에 세운 적법한
   함정이 몬스터 효과에 **응수할 수 없었다** (`RULE_NOT_IMPLEMENTED`).
   규칙은 그 응수를 허락한다 (§2.4 · §6.2).
4. **분류를 안다는 것이 실행 지원이 아니다.** `QUICK` 으로 적은 합성 정의는
   속도 관문을 지나고도 **발동이 거절된다** — 룰북이 유발즉시의 발동 시점을
   적지 않았고 그 사실이 코드에 이미 있다 (§5.3).
5. **다음 Phase 를 시작하지 않았다.**

---

## 1. 시작 커밋 · 변경 파일

| | |
|---|---|
| 검토 기준 HEAD (요청) | `b8a1648` |
| 확인한 실제 HEAD | `b8a1648` — **일치**. 작업 트리 비어 있었고 원격과도 일치 |
| 후속 변경 | **없었다** (덮어쓴 것이 없다) |
| 브랜치 | `claude/pensive-goodall-te1egy` |

### 변경 파일 — production **네 개**

| 파일 | 무엇 |
|---|---|
| `engine/activation_timing.py` | `KIND_SPEED` · `KIND_RULES` (룰북의 효과 분류별 스펠 스피드) · `classify_spell_speed(activation_kind=)` · `ActivationTiming.activation_kind` · `.responding_kind` · `spell_speed(activation_kind=)` · `speed_of_link(activation_kind=)` |
| `engine/effect/definition.py` | `verified_activation_kind` — 등록부에서 분류를 찾아 **카드까지 맞춰 보는** 한 자리 |
| `engine/duel.py` | `Duel._effect_kind` · `_activation_gate` 가 두 분류를 넘긴다 |
| `engine/response.py` | `ResponseLoop._effect_kind` · `check_timing` 이 같은 함수로 분류를 찾는다 |

`engine/effect/__init__.py` 는 새 함수를 내보내는 한 줄이다.

🔴 **새 모듈도 새 규칙 엔진도 만들지 않았다.** 분류 → 스펠 스피드를 적는
자리는 `KIND_SPEED` 하나이고 (`test_f01` 이 production 전수로 센다),
등록부에서 분류를 찾는 자리는 `verified_activation_kind` 하나다
(`test_f02`).

### 변경 파일 — 시험

| 파일 | 무엇 |
|---|---|
| `tests/engine/test_known_effect_kind_legality.py` | **새로 만들었다** — 21개 (A 룰북 대조 · B UNKNOWN 경계 · C 실제 어니스트 · D 비턴 플레이어 · E 사본 · F 책임 · G 보고 계층) |
| `tests/engine/test_fast_window_legality.py` | `test_c02` 를 실측값으로 정정 (`RULE_NOT_IMPLEMENTED` → `SPELL_SPEED_TOO_LOW`) · `test_c03` 추가 (효과 단위 분류) |
| `tests/engine/test_activation_timing.py` | `ActivationTiming` 칸 열거에 두 이름을 더하고 **왜 관측에 없는 사실인지** 적었다 |

### 문서

`docs/phase6ab-followup6-…md` 머리에 **§0 정정 안내**를 더하고 §13 의 ①
판정을 "부분 완료" 로 고쳤다 (§12).

---

## 2. 재현 — 검토 기준 HEAD `b8a1648` 에서 직접 실행

🔴 **최종 `accepted=False` 만 비교하지 않는다.** `validity` · `code` ·
`missing_rule` · `reason` 을 따로 적는다.

### 2.1 어니스트가 **열린 상태**에서는 발동 · 해결된다 (허용 대조)

```
stage = ActivationStage.OPEN
후보 ['37742478:e[0]']
관문  validity=VALID  code=OK  missing_rule=None
      reason="37742478:e[0] 를 발동할 수 있습니다 (비용 판정 제외)."
apply accepted=True  code=OK
해결  "체인1 P0 37742478:e[0] 를 해결했습니다."
결과  패 2 → 3 · MZONE []        ← 필드에서 패로 되돌아갔다
```

이 대조가 없으면 아래의 차단 측정은 *"원래 후보가 없었다"* 와 구별되지
않는다.

### 2.2 🔴 같은 효과가 빠른 효과 기회에서 **모름**으로 막힌다

```
stage = ActivationStage.FAST_WINDOW
후보 []
관문  validity=UNKNOWN  code=RULE_NOT_IMPLEMENTED
      missing_rule='monster effect classification (기동 · 유발 · 플립 vs 유발즉시)'
      reason="발동하려는 카드의 스펠 스피드를 판정할 수 없습니다 (몬스터 효과)."
apply accepted=False  code=RULE_NOT_IMPLEMENTED
```

### 2.3 욕망의 항아리는 같은 단계에서 **규칙 거절**이다

```
관문  validity=INVALID  code=SPELL_SPEED_TOO_LOW  missing_rule=None
      reason="판이 열려 있지 않아 스펠 스피드 1 은 발동할 수 없습니다
              (공식 Fast Effect Timing — 상자 A 에서만 할 수 있는 행동입니다).
              양쪽이 이 기회를 지나가면 판이 다시 열립니다."
apply accepted=False  code=SPELL_SPEED_TOO_LOW
```

**같은 단계 · 같은 스펠 스피드 1 · 다른 코드.** 그것이 보완7 의 과제다.

### 2.4 🔴 함께 재어 발견한 것 — 체인 응답도 같은 원인으로 막혔다

전 턴에 세운 **적법한** 욕망의 선물(`5915629`, 함정 = 스펠 스피드 2)로
어니스트 ①(체인 1)에 응수하려 했다.

```
P1 허가       ['pass']                    ← 응수 후보가 **없다**
직접 apply    accepted=False  code=RULE_NOT_IMPLEMENTED
              reason="응수할 링크의 스펠 스피드를 판정할 수 없습니다 (몬스터 효과)."
```

🔴 **규칙은 그 응수를 허락한다** (스펠 스피드 2 → 1). 막은 것은 규칙이
아니라 `speed_of_link` 가 링크의 `effect_ref` 를 **버리고** 카드만 본
것이고, 그 사실은 보완6 의 모듈 설명이 *세 번째 경고*로 이미 적어
두었다. 사용자 §4 가 *"체인 링크의 속도 판정에도 같은 정보가 필요해지면
동일한 효과별 분류 경로를 재사용한다"* 고 적은 자리다.

### 2.5 분류가 **실제로 없는** 몬스터 효과

```
어니스트 정의 activation_kind = IGNITION        ← 있다
classify_spell_speed(카드)  = 스펠 스피드 미상 (몬스터 효과)
정의 없는 효과(11091375:e[0]) = None
```

카드만 보는 함수는 **여전히** 모른다 — 그것이 입도의 차이이고, 보완7 도
그 함수의 카드 단위 답을 바꾸지 않았다.

---

## 3. 효과 분류의 출처 · 신뢰 조건 · 전달 경로

### 3.1 출처 — 손으로 적어 검증한 정의 하나

```
EffectDefinition(effect_ref=37742478:e[0], source_card_id=37742478,
                 activation_kind=ActivationKind.IGNITION,
                 provenance=hand_written(verified=True))
```

`activation_kind` 의 docstring 이 그 태도를 적어 두었다 — *"**손으로
적는다** (ADR-006). `EffectSpec.effect_types` 에서 자동으로 옮기지 않는다 —
그 변환은 12,702장을 한꺼번에 분류로 바꾸는 일이고, 적는 것과 **실행을
허가하는 것**은 다른 결정이다."*

🔴 **그래서 Lua 를 자동 승격하지 않았다.** 보완7 의 입력은 `EFFECT_LIBRARY`
18 항목 중 분류가 적힌 둘뿐이다 (`37742478:e[0]` IGNITION ·
`69811710:e[0]` TRIGGER).

### 3.2 신뢰 조건 — 넷 중 하나라도 어긋나면 **주지 않는다**

`verified_activation_kind` 가 `None` 을 돌려주는 자리 (넷 다 "모른다" 다):

| | |
|---|---|
| 등록부가 없다 | 판정할 근거가 없다 |
| `effect_ref` 가 없다 | 어느 효과인지 모른다 |
| 그 `effect_ref` 의 정의가 없다 | 적힌 것이 없다 |
| 정의의 카드와 발동하려는 카드가 **다르다** | 🔴 **남의 분류를 빌리지 않는다** |

🔴 마지막 줄이 안전장치다. `source` 와 `effect_ref` 가 어긋난 요청은
검증기가 `EFFECT_REF_CARD_MISMATCH` 로 따로 거절하지만, 이 함수는 **그
거절을 기다리지 않고** 분류 자체를 주지 않는다 — 순서가 바뀌어도 다른
카드의 분류가 새어 들어오지 않게 (`test_b03`).

### 3.3 전달 경로 — `stage` 와 **같은 자리이고 같은 이유**

```
EffectDefinitionRegistry          ← 분류가 적혀 있는 곳
   │  verified_activation_kind(definitions, effect_ref, source_card_id=…)
   ├── Duel._effect_kind            → ActivationTiming.activation_kind
   │                                → ActivationTiming.responding_kind
   └── ResponseLoop._effect_kind    → (같은 두 칸)
                 ↓
   ActivationTimingChecker.check    ← 관측(GameStateView)만 받는다
                 ↓
   classify_spell_speed(definition, activation_kind=…)
                 ↓
   KIND_SPEED[kind]                 ← 룰북에서 옮긴 표 **한 벌**
```

🔴 **왜 값으로 받는가.** 분류는 효과 정의 등록부에 있고 관측에는 **없다**.
타이밍 관문은 `GameStateView` 만 받으므로 (판을 바꿀 수 있는 것을 애초에
들지 않는다) 등록부를 볼 수 없다. 그래서 `point` · `set_this_turn` ·
`simultaneous` · `stage` 와 같은 방식으로 넘긴다 (ADR-007).
`test_f04` 가 그 규율을 AST 로 못박는다 — `engine/activation_timing.py` 는
`engine.effect` 도 `rules` 도 import 하지 않는다.

🔴 **`ResponseLoop` 은 받지 않고 직접 찾는다.** 그 루프는 등록부를 **들고
있으므로** (`self._activator.definitions`) 밖에서 받을 필요가 없다. 찾는
함수가 같으므로 두 자리의 답이 같다 (`test_f02` 가 둘 다
`verified_activation_kind` 를 부르는 것을 AST 로 센다).

### 3.4 표의 근거 — 룰북에서 옮겼고 **시험이 대조한다**

| `ActivationKind` | 룰북의 분류 | 스펠 스피드 | 근거 |
|---|---|---|---|
| `IGNITION` | Ignition Effect | 1 | RULE-EFFECT-002 |
| `TRIGGER` | Trigger Effect | 1 | RULE-EFFECT-004 |
| `FLIP` | Flip Effect | 1 | RULE-EFFECT-005 |
| `QUICK` | Quick Effect | **2** | RULE-EFFECT-003 |

`data/rules/structured/sd-rulebook-en-v10.json` 의 `effect_types[*]` 가
`spell_speed` 와 `rules` 를 직접 적는다. `engine` 은 `rules` 를 import 하지
않고 **`test_a01` 이 둘을 대조한다** — `RESPONSE_TABLE` · `SPEED_RULES` 와
같은 약속이다. 그 시험은 네 분류가 전부 표에 있고(빠뜨린 멤버 없음), 수와
근거 번호가 같고, 넷 다 `has_activation: true` 이고, **지속 효과는 축에
없다**(`has_activation: false`)는 것을 함께 센다.

### 3.5 🔴 `QUICK_O` 를 카드 단위로 읽는 방법이 아니다

보완6 의 모듈 설명이 그 방법이 성립하지 않는다고 **측정해** 두었다 —
몬스터 856장(10.4%)이 1 계열과 2 계열 블록을 **둘 다** 가지고, `QUICK_O`
라는 이름은 공식 자료 829파일에서 0회다. 보완7 은 그 측정을 뒤집지
않았다. 입력이 **카드가 아니라 효과**이고 손으로 적어 검증한 값이므로
입도 문제가 생기지 않는다 (`test_c03` 이 같은 카드의 두 효과가 다른 답을
받는 것을 센다).

---

## 4. 단계와 효과 종류에 따른 판정표

```
ActivationTimingChecker.check(timing, action)
  ① _set_turn_refusal                      ← 그대로
  ② 체인이 쌓여 있으면
       simultaneous 면 통과                 ← 그대로
       mine   = spell_speed(action.source, activation_kind=timing.activation_kind)
       theirs = speed_of_link(responding_to, activation_kind=timing.responding_kind)
       둘 중 하나라도 모르면 UNKNOWN
       mine.responds_to(theirs) 면 통과, 아니면 INVALID
  ③ 체인이 비어 있으면 _by_stage
       stage is None         → UNKNOWN
       OPEN                  → 통과                 ← 분류를 보지 않는다
       TRIGGER_REGISTRATION  → 통과                 ← 분류를 보지 않는다
       CHAIN_RESPONSE        → UNKNOWN (모순)
       FAST_WINDOW           → mine = spell_speed(…, activation_kind=…)
                               모르면 UNKNOWN
                               스펠 스피드 1 이면 INVALID
                               2 이상이면 통과
```

실측한 판정표 — 같은 판 · 같은 카드 · 같은 단계에서 **분류만** 다르다.

| 효과 | 분류 | 열린 상태 | 빠른 효과 기회 | 체인 응답 (상대가 SS1) |
|---|---|---|---|---|
| 어니스트 ① (실제) | `IGNITION` | **VALID** / OK | **INVALID** / `SPELL_SPEED_TOO_LOW` | **INVALID** / `SPELL_SPEED_TOO_LOW` |
| 같은 효과, 분류 칸만 비움 (합성) | `None` | UNKNOWN / `monster-activation-timing` | UNKNOWN / `monster effect classification` | UNKNOWN |
| 같은 효과, 분류 칸만 `QUICK` (합성) | `QUICK` | 속도 통과 · **발동 거절** (`quick-effect-activation`) | 같음 | 속도 **통과** |
| 욕망의 선물 (실제 함정) | — (카드 종류) | VALID | **VALID** | **VALID** (2 → 1) |
| 욕망의 항아리 (실제 통상 마법) | — (카드 종류) | VALID | **INVALID** / `SPELL_SPEED_TOO_LOW` | INVALID |
| 기르수 ① (실제 유발) | `TRIGGER` | 유발 등재 단계에서 통과 | — | — |

🔴 **마법 · 함정은 `activation_kind` 를 보지 않는다.** 그 발동은 카드 종류로
이미 판정되고, 그 축에 마법 · 함정의 발동을 넣지 않은 이유를
`ActivationKind` 가 스스로 적어 두었다. 그래서 등재된 16개 효과가
`activation_kind=None` 인 것이 **정상**이고, 보완7 이 그것을 바꾸지 않았다.

---

## 5. 거절의 뜻 — 셋이 다른 코드를 받는다

### 5.1 규칙이 막는다 → `INVALID`

```
어니스트 ①, 빠른 효과 기회
관문   validity=INVALID  code=SPELL_SPEED_TOO_LOW  missing_rule=None
       reason="판이 열려 있지 않아 스펠 스피드 1 은 발동할 수 없습니다 …"
후보   []                                   ← 같은 판정이 거른다
apply  accepted=False  code=SPELL_SPEED_TOO_LOW
       reason = 관문의 것과 **문자 단위로 동일**
상태   불변 (판 · 체인 · 우선권 · 기회 수명 · 소비 기록 · Journal 길이)
```

🔴 **이유 문장이 욕망의 항아리와 같은 것**이다 — 같은 규칙이 막았으므로.
`test_c01` 이 `step.reason == verdict.reason` 과 상태 불변을 함께 센다.

### 5.2 분류가 없다 → `UNKNOWN` 그대로

```
분류 칸을 비운 합성 정의
ActionValidator          UNKNOWN · 'monster-activation-timing (… 분류가 없다)'
ActivationTimingChecker  UNKNOWN · 'monster effect classification …'
후보                      []            ← 규칙 쪽 관문이 **더 앞에서** 막는다
apply                    accepted=False · RULE_NOT_IMPLEMENTED · 상태 불변
```

🔴 **보완7 은 "모름" 의 범위를 줄이지 않았다.** 바꾼 것은 *아는 것을
전달하는 길*뿐이다 (`test_b02`).

### 5.3 🔴 분류를 알아도 **발동 허가가 아니다**

분류만 `QUICK` 으로 바꾼 합성 정의에서 두 계층의 답이 갈린다.

| | |
|---|---|
| `ActivationTimingChecker` | **VALID** — 스펠 스피드 2 이므로 속도가 막지 않는다 |
| `ActionValidator` | **UNKNOWN** · `quick-effect-activation (룰북이 발동 시점을 적지 않는다 — RULE-EFFECT-003 의 not_stated)` |
| 공통 관문의 답 | **거절** · 후보 아님 · 상태 불변 |

그 범위가 코드에 이미 있었다 —
`ACTIVATION_KINDS_IN_SCOPE = frozenset({ActivationKind.IGNITION})`. 발동까지
판정하는 분류는 **기동 효과 하나**이고, 룰북이 그 시점을 문장으로 확정해
두었기 때문이다. `test_b05` 가 이 전부를 센다.

🔴 즉 사용자 §4 의 *"유발즉시라는 분류가 확인돼도 미구현 조건 · 비용 ·
타이밍 · 실행 관문을 우회하지 않는다"* 가 **측정으로** 지켜진다.

---

## 6. 필수 검증의 결과

### 6.1 A — 실제 어니스트 대조 (`test_c01` · `test_fast_window_legality::test_c02`)

| 요구 | 결과 |
|---|---|
| 열린 상태에서 후보 존재 | ✔ |
| 실제 발동 · 해결로 필드에서 패로 이동 | ✔ 패 2 → 3 · MZONE `[]` |
| 별도의 같은 초기 판에서 빠른 효과 기회 진입 | ✔ 실제 몬스터 세트 하나로 |
| 후보 제외 | ✔ `[]` |
| 공통 관문 `INVALID` | ✔ `SPELL_SPEED_TOO_LOW` · `missing_rule=None` |
| 직접 apply 도 같은 규칙 거절 | ✔ 이유 문장까지 동일 |
| 거절 전후 상태 불변 | ✔ 12칸 지문 비교 |
| 양측 PASS 후 다시 발동 가능 | ✔ `accepted=True` |

### 6.2 B — UNKNOWN 경계

| 요구 | 시험 | 결과 |
|---|---|---|
| 정의 없음 | `test_b01` | `None` — 등록부에 없으면 분류도 없다 |
| 정의는 있고 `activation_kind` 없음 | `test_b02` | 두 계층 모두 `UNKNOWN` · 후보 아님 · 상태 불변 |
| `source` 와 `EffectRef` 불일치 | `test_b03` | 분류 `None` + 기존 `EFFECT_REF_CARD_MISMATCH` 거절 |
| 같은 카드의 서로 다른 효과 | `test_b04` | `e[0]` IGNITION · `e[1]` QUICK — 섞이지 않는다 |
| 알려진 분류로 미구현 효과가 실행되지 않음 | `test_b05` | 속도 통과 · 발동 거절 (§5.3) |

🔴 **B 는 전부 합성 검증이다** (실제 어니스트 정의에서 분류 칸만 바꾼
등록부). 실제 카드 지원을 주장하지 않는다.

### 6.3 C — 기존 동작 보존

| | 결과 |
|---|---|
| 빠른 효과 기회에서 욕망의 항아리 차단 | 유지 (`test_fast_window_legality::test_b02`~`b04`) |
| 열린 상태에서 욕망의 항아리 허용 | 유지 (`test_b01`) |
| 적법한 함정 · 속공 마법 발동 | 유지 (`test_d01` · `test_d06`) |
| 유발 등록 단계에서 기르수 발동 | 유지 (`test_d02` · 2링크 파일 전체) |
| 같은 기회의 복수 유발 등록 | 유지 (`test_d03`) |
| 체인 응답의 속도 제약 | 유지 — 🔴 **좁아졌다**: 스펠 스피드 1 몬스터 효과가 전에는 `UNKNOWN`, 지금은 `INVALID` (`test_c03`) |
| 2링크 체인의 후속 유발 통합 검증 | 유지 (17개 전부 통과) |
| 단계를 받지 못한 판정의 UNKNOWN | 유지 (`test_g02` · `test_a03`) |

### 6.4 D — 비턴 플레이어의 실제 빠른 효과 (보완6 BLOCKER-F6-3)

```
전 턴: P1 이 실제 SET_SPELL_TRAP 으로 욕망의 선물을 세운다   accepted=True
턴 넘김 (실제 진행)                                          stage=OPEN
P0 의 정상 행동(몬스터 세트)으로 기회 개시                     stage=FAST_WINDOW · holder=P0
P0 는 후보가 없다 → PASS                                      accepted=True · holder=P1
🔴 P1 후보 ['5915629:e[0]'] · 허가 ['activate_effect','pass']
정상 Duel.apply 로 발동                                       체인 1
양측 PASS → 해결                                              "해결"
결과: 발동한 쪽의 **상대(P0)** 패 +2                           DrawOperation(count=2, who=OPPONENT)
```

| 요구 | 결과 |
|---|---|
| 이전 턴에 세워진 초기 판 | ✔ 세우는 것도 **실제 행위**다 (기록이 남는다) |
| 턴 플레이어의 정상 행동으로 기회 개시 | ✔ 몬스터 세트 하나 |
| 턴 플레이어 PASS | ✔ 그러면 기회가 상대에게 간다 |
| 비턴 플레이어의 실제 함정 후보 생성 | ✔ |
| 정상 `Duel.apply` 로 발동 | ✔ |
| 응답 · 해결 후 상대 패 2장 증가 | ✔ **발동한 쪽의 상대**가 2장 (카드 문면 그대로) |
| 세트한 턴 제한 우회 없음 | ✔ `test_d02` — 같은 턴이면 `SET_THIS_TURN` 거절 |

🔴 **초기 판 구성과 검증 대상 실행을 구분했다.** 손으로 둔 것은 시작 판의
카드 배치뿐이고, 세트 · 턴 넘김 · 기회 개시 · 발동 · 해결은 전부 실제
`Duel.apply` 다. 필수 상태 전이를 실행 중에 주입한 자리는 없다.

### 6.5 E — 사본과 결과 전파

| 요구 | 시험 | 결과 |
|---|---|---|
| 원본 · 사본의 분류와 판정 일치 | `test_e01` | 분류 · 허가 종류 · 코드 · **이유 문장**까지 같다 |
| 사본의 발동 · 포기가 부모에 안 보임 | `test_e02` | 12칸 지문 불변 · 단계 그대로 |
| 정의 등록부 격리 | `test_e03` | 사본에 등록한 효과를 원본이 **모른다** |
| Simulator · `/combo` 의 규칙 거절 / 미지원 구분 | §9 | 바이트 단위로 동일 |
| 기르수 전개 · `/combo` 입력 매수 검증 | §9 | 유지 |
| 해결 결과가 PASS 문장으로 덮이지 않음 | §9 | 유지 |

---

## 7. 후보 · 관문 · 직접 apply · 보고 계층의 일치

### 7.1 네 자리가 **한 판정**을 본다

| 자리 | 무엇을 부르는가 |
|---|---|
| 후보 생성 (`legal_actions`) | `Duel._activation_gate` |
| 직접 적용 (`Duel.apply` → `_apply_activation`) | 같은 함수 |
| 거절 이유 (`Duel._refusal_verdict`, 보완6) | 같은 함수 |
| 보고 계층 (`deck/opening.py::_gate_code`) | 같은 함수 |

분류를 넘기는 자리는 `_activation_gate` **안**이므로, 네 자리가 **자동으로**
같은 분류를 본다 — 넘기는 코드를 네 번 쓰지 않았다.

실측 (`test_g01`):

```
열린 상태        _gate_code = "OK"
빠른 효과 기회    _gate_code      = "SPELL_SPEED_TOO_LOW"
                 관문             = "SPELL_SPEED_TOO_LOW"
                 Duel.apply       = "SPELL_SPEED_TOO_LOW"
```

### 7.2 규칙 거절은 **미지원으로 집계되지 않는다**

`LegalActions.unsupported()` 는 `missing` 이 붙은 보류만 고른다. 규칙
거절은 `missing_rule=None` 이므로 들어가지 않고, 유발 경로의 보류 생성이
그 구분을 직접 적는다 — *"관문이 모른다고 하면 채우고, 규칙이 금지한다고
하면 비운다"*.

🔴 **다만 이 경로는 보류 자체를 남기지 않는다.** 비유발 후보 생성
(`Duel._activation_actions`)은 관문 거절을 조용히 `continue` 한다. 그래서
빠른 효과 기회의 어니스트 거절은 *"미지원으로 잘못 집계된다"* 가 아니라
**집계에 아예 없다** — 보완7 전에도 그랬다. 개선이 아니므로 개선이라고
적지 않고, 남은 한계로 적는다 (§11, `test_g02` 가 그 사실을 센다).

---

## 8. 원본 · 사본 일치와 분기 격리

```
원본 분류 = 사본 분류                        IGNITION == IGNITION
원본 허가 = 사본 허가                        ['pass'] == ['pass']
원본 거절 = 사본 거절                        (False, SPELL_SPEED_TOO_LOW) 양쪽
                                            이유 문장도 동일
사본이 거절 받고 기회를 지나 발동해도         원본 12칸 지문 불변 · stage 그대로
사본에 정의를 등록하면                       원본은 그 효과를 **모른다** (None)
```

🔴 **정의 등록부 격리가 분류의 격리다.** 분류의 출처가 그 등록부이므로
격리가 깨지면 한쪽의 등록이 다른 쪽의 **판정**을 바꾼다 — 보완4 가 만든
격리가 보완7 에서 그 뜻을 하나 더 갖는다 (`test_e03`).

---

## 9. 기르수 · 2링크 후속 유발 · Simulator · `/combo` 보존

### 9.1 `/combo` — **바이트 단위로 동일**

```
보완6 기준     정상: 메시지 4개 6166자 | 거절: 메시지 1개 1740자
보완7          정상: 메시지 4개 6166자 | 거절: 메시지 1개 1740자
```

```
✅ 엔진이 실제로 5걸음 실행 (효과 해결 1걸음 · 상태 변경 5걸음)
  1. P0 normal_summon    기르수
  2. P0 activate_effect  69811710:e[0]  "체인1 P0 69811710:e[0] 를 해결했습니다."
  3~5. P0 set_spell_trap
멈춘 이유: 판을 바꿀 후보가 없고 남은 후보는 흐름뿐 (['end_phase']),
          🔴 이 자리에 지원하지 않아 후보가 되지 못한 것 1건:
             activate_card [activation-timing (Phase 2-C/2-F)]
```

🔴 **왜 바뀌지 않았는가.** 그 전개에서 발동되는 것은 기르수 ①(유발 등재
단계 — 분류를 보지 않는 갈래)과 마법 · 함정뿐이고, 남은 미지원 1건은
`activate_card` 의 **카드 발동 타이밍**이다 (몬스터 효과 분류와 다른 축).
보완7 이 좁힌 자리를 그 전개가 지나가지 않는다.

🔴 **토큰 없는 문자열 검사이고 실제 Discord 접속 검증이 아니다.**

### 9.2 해결 결과가 PASS 문장으로 덮이지 않음

보완5 가 고친 네 자리 그대로다 — 걸음 2 의 이유가
*"체인1 P0 69811710:e[0] 를 해결했습니다"* 이고 PASS 문장이 아니다.

### 9.3 2링크 후속 유발

`tests/engine/test_two_link_followup_trigger.py` **17개 전부 통과**.
그 체인의 둘째 링크는 `simultaneous` 갈래로 등재되므로 보완7 의 분류
전달을 지나지 않고, 응수가 아닌 묶음이라는 판정도 그대로다.

---


## 10~14 — 작성 중

🔴 **이 커밋에는 §1~§9 까지만 들어 있다.** 남은 §10(테스트 명령 · 결과 ·
시간 · 실제 종료 코드 · skip 사유) · §11(기존 실패 · 신규 회귀 · 남은 한계) ·
§12(선행 보고서 정정) · §13(완료 기준별 판정) · §14(범위)는 회귀 실행이
완주해 **실제 `PYTEST_EXIT` 가 찍힌 뒤** 다음 커밋에서 채운다.

실행 중인 묶음: `tests/engine` · `tests/agent`+`rules`+`rulings` · root 92 파일
여덟 조각. **잘린 실행을 통과로 합산하지 않는다.**
