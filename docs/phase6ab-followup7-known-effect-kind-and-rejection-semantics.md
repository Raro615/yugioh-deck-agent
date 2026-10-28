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

### 커밋

| 커밋 | 무엇 |
|---|---|
| `a849e7d` | 구현 — 분류 전달 경로와 룰북 표, 새 시험 21개, 보완6 보고서 §0 정정 |
| `36a0ea5` | 이 보고서의 §1~§9 (회귀가 돌고 있던 동안 측정이 끝난 부분만) |
| `6df5b70` | dormant 감사의 줄 수 핀 (§10.4 ④) |
| (이 커밋) | `test_effect_type_quick_audit::test_12` 핀(§10.4 ⑤)과 이 보고서의 §10~§14 — 🔴 자기 해시를 넣으려고 커밋을 반복하지 않는다 |

### 변경 파일 — production **네 개** + 다리 하나

| 파일 | 무엇 |
|---|---|
| `engine/activation_timing.py` | `KIND_SPEED` · `KIND_RULES` (룰북의 효과 분류별 스펠 스피드) · `classify_spell_speed(activation_kind=)` · `ActivationTiming.activation_kind` · `.responding_kind` · `spell_speed(activation_kind=)` · `speed_of_link(activation_kind=)` |
| `engine/effect/definition.py` | `verified_activation_kind` — 등록부에서 분류를 찾아 **카드까지 맞춰 보는** 한 자리 |
| `engine/duel.py` | `Duel._effect_kind` · `_activation_gate` 가 두 분류를 넘긴다 |
| `engine/response.py` | `ResponseLoop._effect_kind` · `check_timing` 이 같은 함수로 분류를 찾는다 |
| `engine/spell_activation.py` | `effect_kind_of` — 다리 쪽 통로 한 줄. `engine.duel` 이 `engine.effect` 를 import 하지 않으므로 그쪽을 지난다 (§14) |

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



## 10. 실행한 시험 — 명령 · 결과 · 시간 · **실제 종료 코드**

🔴 **harness 가 보여 주는 종료 코드는 감싼 쉘의 것이다.** 그래서 모든
실행을 래퍼로 돌려 로그 끝에 `PYTEST_EXIT=<코드>` 를 적고 **그 숫자만**
옮긴다 (보완6 §10 과 같은 래퍼다).

```bash
LOG="$1"; shift
timeout 7000 python3 -m pytest "$@" -q -rf > "$LOG" 2>&1
CODE=$?
echo "PYTEST_EXIT=$CODE" >> "$LOG"
exit $CODE
```

### 10.1 검증 순서 — 최소 재현 → 타깃 → 관련 통합 → 필요한 회귀

| 순서 | 무엇 | 결과 |
|---|---|---|
| ① 최소 재현 | 검토 기준 HEAD `b8a1648` 에서 §2 의 다섯 측정 | **전부 재현** — pytest 가 아니라 직접 실행이다 |
| ② 타깃 | 새 파일 + 보완6·7 의 관련 파일 일곱 | `163 passed` · **0** |
| ③ 관련 통합 | `tests/engine` 전체 | `3879 passed` · **0** |
| ④ 필요한 회귀 | `tests/agent`+`rules`+`rulings`, root 92 파일 | §10.3 |

### 10.2 타깃과 관련 통합

| 명령 | 결과 | 시간 | `PYTEST_EXIT` |
|---|---|---|---|
| `tests/engine/test_known_effect_kind_legality.py` | **21 passed** | 4.8초 | **0** |
| 보완6·7 의 여섯 파일 + `test_activation_timing.py` | **163 passed** | 115.2초 | **0** |
| `tests/engine` | **3879 passed** | 688.8초 (11:28) | **0** |

🔴 **engine 전체가 실패 0건이다.** 수가 맞아떨어진다 — 보완6 의 3856 +
속공 마법 시험 1(보완6 이 그 실행 **뒤에** 더한 것) + 보완7 의 새 파일 21 +
`test_c03` 1 = **3879**.

🔴 **왜 0건인가.** 두 칸이 **기본값 `None`** 이고 분류를 받지 못하면
예전과 똑같이 `UNKNOWN` 이다. 조용히 넓어진 자리가 없다는 뜻이고, 그것이
이 설계를 고른 이유다.

그 실행 **전에** engine 쪽 정정 둘이 있었다 (아래 §10.4 의 ①②).

### 10.3 필요한 회귀 — 범위와 근거

🔴 **왜 돌렸는가.** 보완7 이 공유 계약 셋을 건드렸다.

| 계약 | 영향 |
|---|---|
| `ActivationTiming` 의 칸 둘 | 칸 열거를 못 박는 감사가 있다 |
| `classify_spell_speed` 의 키워드 인자 | 그 **서명**을 못 박는 감사가 있다 (§10.4 ⑤) |
| 몬스터 효과의 거절 코드 | `UNKNOWN`/`RULE_NOT_IMPLEMENTED` → `INVALID`/`SPELL_SPEED_TOO_LOW`, 그리고 **함정이 몬스터 효과에 응수할 수 있게 됐다**. 탐색 랭킹과 후보 수를 못 박는 감사가 22개 있다 |

🔴 **왜 쪼갰는가.** 배경 명령의 상한이 30분이다. `tests/*.py` **92 파일**을
12 파일씩 여덟 조각으로 나눴다 (보완6 과 같은 분할). 기록한 예상은
1.5~2시간이었고 실제 root 합이 **60분**이다. **잘린 실행을 통과로
합산하지 않는다** — 아래는 전부 `PYTEST_EXIT` 가 찍힌 완주 실행이다.

| 조각 | 결과 | 시간 | `PYTEST_EXIT` |
|---|---|---|---|
| `tests/agent` + `rules` + `rulings` | 2 failed · 526 passed · 1 skipped | 339.9초 (5:39) | **1** |
| rootA 1 | 337 passed | 834.4초 (13:54) | **0** |
| rootA 2 | 309 passed | 591.4초 (9:51) | **0** |
| rootA 3 | 2 failed · 379 passed | 719.6초 (11:59) | **1** |
| rootA 4 | 1 failed · 215 passed · 1 skipped | 179.2초 (2:59) | **1** |
| rootB 1 | 4 failed · 323 passed · 8 skipped | 683.0초 (11:22) | **1** |
| rootB 2 | 254 passed | 105.0초 (1:44) | **0** |
| rootB 3 | 1 failed · 235 passed | 119.9초 (1:59) | **1** |
| rootB 4 | 263 passed | 366.5초 (6:06) | **0** |
| **root 합** | **8 failed · 2315 passed · 9 skipped** | **3598.9초 (60분)** | — |

🔴 **버리고 다시 돌린 실행이 있다.** 처음 돌린 `tests/engine` ·
`tests/agent` 묶음 · rootB 2 는 **import 경계를 고치는 중**에 걸쳐 있었다
(§14 의 `engine.duel` 항목). 코드가 실행 도중 바뀐 결과는 믿을 수 없으므로
**버리고 처음부터 다시 돌렸다** — 위 표는 전부 다시 돌린 것이다. 버린
실행의 숫자를 합산하지 않는다.

### 10.4 8개 실패를 셋으로 갈랐다

| | 수 | 무엇 |
|---|---|---|
| **기존 실패** | 6 | §11.1 — 보완5 · 보완6 보고서에 같은 이름으로 적혀 있다 |
| **내 변경이 움직인 측정값 핀** | 2 | 아래 ④⑤ |
| **내 변경의 미처리 회귀** | **0** | 남긴 것이 없다 |

`tests/agent` 묶음의 2개도 **둘 다 기존 실패**다 (보완6 때는 4개였고, 그때
고친 핀 둘을 보완7 이 움직이지 않았다).

움직인 측정값 핀 전부 — ①②는 engine 실행 **전**에, ③은 회귀 전에,
④⑤는 조각 실행이 **찾아 준** 것이다.

| | 자리 | 전 → 후 | 근거 |
|---|---|---|---|
| ① | `test_activation_timing::test_f_the_context_stores_nothing_twice` | 칸 열거에 `activation_kind` · `responding_kind` 추가 | 둘 다 **관측에 없는 사실**이다 — 분류는 효과 정의 등록부에 있고 `GameStateView` 는 들고 다니지 않는다. 그 시험이 지키는 주장("관측과 겹치지 않는다")은 그대로다 |
| ② | `test_fast_window_legality::test_c02` | `RULE_NOT_IMPLEMENTED` → `SPELL_SPEED_TOO_LOW` | 🔴 **느슨하게 한 것이 아니라 좁혔다** — 전에는 코드 하나만 셌고 지금은 `INVALID` · `SPELL_SPEED_TOO_LOW` · `missing_rule is None` · 이유 문장 일치 넷을 센다 |
| ③ | `test_rule_not_implemented_code_audit` (2건) · `test_unimplemented_rule_semantics_audit::test_03` | 문자열 91 → **93**, 산문 17 → **19**, 좌표 셋 +58 | **코드 수 74 는 그대로**다 — 늘어난 둘은 전부 산문이고 (`responding_kind` · `verified_activation_kind` 의 설명이 실측을 인용한다), 이 Phase 는 그 코드를 **덜 쓰게** 만들었다 |
| ④ | `test_trigger_pipeline_dormant_audit::test_25` | 원본 804 → **952**, 문자열에 둔감한 핀 276 → **294** | **실행 코드는 18줄**이고 나머지 130줄은 설명이다. 나머지 다섯 모듈의 숫자는 그대로 — dormant 가 깨지지 않았다 |
| ⑤ | `test_effect_type_quick_audit::test_12` | 서명 `["definition"]` → `["definition", "activation_kind"]` | 🔴 **그 시험이 못 박고 있던 것이 입도 불일치 자체였다** — *"사유는 효과를 가리키는데 함수는 카드만 받는다"*. 보완7 이 그 어긋남을 고쳤으므로 핀을 **바꿔 못 박는다**: 새 인자가 **키워드 전용 · 기본값 `None`** 임을 세고(주지 않으면 전과 같은 `UNKNOWN`), `effect_ref` · 카드 ID · `EffectSpec` 을 받지 않는다는 원래 주장은 그대로 센다 |

🔴 **탐색 랭킹 digest 는 움직이지 않았다** — §11.2.

#### 확인 실행 — 고친 핀 일곱을 **한 번에** 다시 돌렸다

```
tests/test_rule_not_implemented_code_audit.py::test_02_...
tests/test_rule_not_implemented_code_audit.py::test_05_...
tests/test_unimplemented_rule_semantics_audit.py::test_03_...
tests/test_trigger_pipeline_dormant_audit.py::test_25_...
tests/test_effect_type_quick_audit.py::test_12_...
tests/engine/test_activation_timing.py::test_f_the_context_stores_nothing_twice
tests/engine/test_fast_window_legality.py::test_c02_...

7 passed in 6.01s
PYTEST_EXIT=0
```

조각 전체를 다시 돌리지는 않았다 — 그 조각 안에서 바뀐 파일은 내가 고친
파일뿐이고, 같은 10분 실행을 근거 없이 반복하지 않는다는 §7 을 따랐다.
조각 **사이의** 상호작용은 재지 않았고 §11.4 에 한계로 적는다.

#### skip 의 사유 — **하나도 더하지 않았다**

| 묶음 | skip | 사유 (실측) |
|---|---|---|
| `tests/agent`+`rules`+`rulings` | 1 | `tests/rules/test_extraction_determinism.py:20: PyMuPDF 없음 (추출기 전용 의존성)` |
| rootA 4 | 1 | `tests/test_korean_collector.py:88: 수집 캐시 없음` |
| rootB 1 | 8 | `pytest.skip("이 Phase 의 commit 이 아직 없다")` 계열과 `tests/test_lua_loader.py` 의 `"샘플 스크립트 없음"` |

전부 보완6 과 **같은 자리 같은 수**이고, 자료나 커밋이 없을 때만 걸린다.
`test_lua_verified_provenance_audit::test_39`(*"기존 테스트 삭제 · skip
추가가 없다"*)가 그것을 따로 세고, 통과했다 (rootB 1).

### 10.5 데이터 준비 상태 · 버전 · 출처

| | |
|---|---|
| `data/cards.cdb` | 있음 — 세션 시작 훅이 적은 것: **카드 14,127장 · 스크립트 12,972장** (4.1초) |
| `data/constants` | 있음 — git 추적 대상이 아니다 (훅이 내린다) |
| 한국어 자료 | 있음 (`data/ko`) — 그런데도 `test_korean_overlay_unapplied_audit` 넷은 기존 실패다 |
| 수집 캐시 | **없음** → rootA 4 의 skip 1 |
| 룰북 | `data/rules/structured/sd-rulebook-en-v10.json` — `effect_types` 를 `test_a01` 이 대조한다 |
| 공식 Lua | `c37742478.lua` (`EFFECT_TYPE_IGNITION` + `SetRange(LOCATION_MZONE)`) · `c5915629.lua` |
| Discord 토큰 | **없음** — §9.1 은 문자열 검사이고 **접속 검증이 아니다** |

---

## 11. 기존 실패 · 신규 회귀 · 남은 한계

### 11.1 기존 실패 8개 — 보완7 이 만든 것이 아니다

보완5 · 보완6 보고서에 같은 이름으로 적혀 있고, 보완7 의 변경과 닿는
자리가 없다 (자료 부족이거나 범위 밖이다).

| 파일 | 시험 | 성격 |
|---|---|---|
| `tests/rulings/test_data_audit.py` | `test_every_repository_card_can_reach_a_cid` | 카드 DB 자료 |
| `tests/agent/test_opponent_resource_weighting_audit.py` | `test_07` | 전략 평가 (범위 밖) |
| `tests/test_effect_type_quick_audit.py` | `test_29` | 공식 자료 어휘 |
| `tests/test_event_free_chain_semantic_audit.py` | `test_27` | 공식 자료 어휘 |
| `tests/test_korean_overlay_unapplied_audit.py` | `test_01` · `test_13` · `test_21` · `test_25` | 한국어 자료 |

### 11.2 신규 회귀 — **0건**

내 변경이 깬 뒤 **고치지 못한 채 남긴** 자리는 없다. 닿은 자리는 전부
둘 중 하나였다.

| | 수 | 처리 |
|---|---|---|
| 측정값 핀 | engine 2건 · root **4개 파일 5건** | 실측값으로 갱신하고 **왜 움직였는지** 각 자리에 적었다 (§10.4) |
| **내가 만든 실제 결함** | 1 | §14 — `engine.duel` 의 import 경계를 깼고 감사가 잡았다. 다리 쪽을 지나게 고쳤다 |

🔴 **필수 절차와 합법 후보가 바뀌어 실행 경로가 달라진 자리를 근거와 함께
적는다.** 이전 수치에 맞추려고 잘못된 동작을 유지한 자리는 없다.

| 바뀐 것 | 전 → 후 | 근거 |
|---|---|---|
| 어니스트 ①의 빠른 효과 기회 거절 | `UNKNOWN` → **`INVALID`** | 룰북 Ignition Effect = 스펠 스피드 1 (RULE-EFFECT-002) · 공식 Fast Effect Timing 상자 A |
| 함정의 몬스터 효과 응수 | **거절 → 허용** (후보 1건 · 체인 2) | 스펠 스피드 2 → 1 은 응수할 수 있다 (RULE-CHAIN-005) |
| 체인 응답의 스펠 스피드 1 몬스터 효과 | `UNKNOWN` → **`INVALID`** | 좁아졌다 — RULE-CHAIN-004 |
| 탐색 `decisions` · digest | **움직이지 않았다** | 아래 |
| `/combo` 걸음 수 · 글자 수 | **움직이지 않았다** | §9.1 |

🔴 **탐색 랭킹 digest 는 움직이지 않았다** — `decisions` 1065 ·
해시 `9bc5fadb…` · 종류별 분포까지 그대로다. 그 판의 덱(러스터 드래곤 ·
욕망의 항아리 · 넉넉한 보상)에 **분류가 적힌 몬스터 효과가 없으므로**
보완7 이 좁힌 자리를 그 궤적이 지나가지 않는다. 직접 계산해서 확인했고
(같은 여섯 씨앗 · 같은 계산), 그래서 22개 파일의 핀을 **건드리지
않았다**.

### 11.3 남은 한계 — 네 갈래로 구분한다

사용자 §8 의 요구대로 **미지원 기능 · 정확성 결함 · 검증 부족 · 성능
비용**을 섞지 않는다.

#### 정확성 결함 (규칙이 틀릴 수 있다)

| | 무엇 |
|---|---|
| **BLOCKER-F7-1** | 🔴 **비유발 후보 생성이 관문 거절을 보류로 남기지 않는다.** `Duel._activation_actions` 가 조용히 `continue` 한다 (유발 쪽은 `withheld` 에 이유를 싣는다). 그래서 빠른 효과 기회의 기동 효과 거절은 *"미지원으로 잘못 집계"* 가 아니라 **집계에 아예 없다** — 보완7 전에도 그랬고 보완7 이 바꾸지 않았다. 읽는 쪽은 "후보가 없다" 와 "규칙이 막았다" 를 구별할 수 없다. `test_g02` 가 그 사실을 센다 |
| **BLOCKER-F6-2** | `Duel.apply` 가 흐름 계층(우선권 · 차례 · 필수 처리)의 거절에 여전히 *"아직 구현하지 않은 규칙"* 문장을 쓴다. 🔴 **보완7 에 필요한 부분이 아니다** — 보완7 이 고친 것은 **발동 관문**의 답이고, 그 자리는 관문이 `VALID` 를 낸 뒤 흐름이 막는 자리다. 사용자 §5 의 요구대로 구분해서 남긴다 (모든 거절을 재설계하지 않았다) |
| **BLOCKER-F5-1** | 「경우」 효과의 장소 검사 — 보완5 그대로 |
| **BLOCKER-F5-2** | 강제 「때」가 타이밍을 놓친 경우 `UNKNOWN` — 6-AB 이래 그대로 |

#### 미지원 기능 (규칙은 알지만 수단이 없다)

| | 무엇 |
|---|---|
| **BLOCKER-F7-2** | 🔴 **분류가 적힌 효과가 둘뿐이다.** `EFFECT_LIBRARY` 18 항목 중 `activation_kind` 가 있는 것은 `37742478:e[0]`(IGNITION) · `69811710:e[0]`(TRIGGER) 다. 등재되지 않은 **나머지 모든** 몬스터 효과는 정의가 없으므로 **여전히 `UNKNOWN`** 이고, 그것이 올바른 답이다 (ADR-006 — 적는 것과 실행을 허가하는 것은 다른 결정). 보완7 은 **길**을 냈고 **목록**을 넓히지 않았다 |
| **BLOCKER-F7-3** | 🔴 **유발즉시 · 플립 효과는 분류를 알아도 발동되지 않는다.** `ACTIVATION_KINDS_IN_SCOPE` 가 기동 효과 하나이고, 룰북이 유발즉시의 발동 시점을 **적지 않았다**(`not_stated`). 보완7 이 그 자리를 **우회하지 않았다** (§5.3) — 근거가 생겨야 풀린다 |
| **BLOCKER-F5-4** | SEGOC 의 5~7 순위 — 네 묶음만 구현했다 |
| **BLOCKER-F5-5** | 묘지 **밖** 도착지의 발동 자리 (`UNKNOWN` 유지) |
| **BLOCKER-F5-6** | 스펠 스피드 2 전체 — `EFFECT_LIBRARY` 18 항목 밖은 후보가 되지 않는다 |
| **BLOCKER-F5-7** | 묶음 안 순서를 한 번의 호출로 쌓는 API 가 없다 |
| **BLOCKER-F5-8** | `93920420` ②의 실제 효과 미구현 — 2링크 검증의 조작 둘이 합성이다 |

#### 검증 부족 (구현은 있으나 재지 못했다)

| | 무엇 |
|---|---|
| **BLOCKER-F7-4** | `QUICK` 분류의 **실제 카드** 측정이 없다. `B` 절의 유발즉시 측정은 전부 **합성 정의**이고 (실제 어니스트 정의에서 분류 칸만 바꿨다), 그 사실을 시험마다 적었다. 실제 유발즉시 효과를 등재하는 일은 `EFFECT_LIBRARY` 를 넓히는 일이고 이번 범위가 아니다 |
| **BLOCKER-F5-9** | 창에 사건이 하나뿐이다 — 어휘 판정이 실행 경로에서 답을 가르지 않는다 |
| **BLOCKER-F5-10** | 비공개 영역(덱 · 패) 유발의 순서 — 조사만 했다 |
| **BLOCKER-F5-11** | 실제 Discord 접속 — 토큰 없음 (§9.1 은 문자열 검사다) |

#### 성능 비용 (정확성과 무관 — BLOCKER 로 만들지 않는다)

| | 무엇 |
|---|---|
| **BLOCKER-F7-5** | `_activation_gate` 가 발동 하나마다 등록부 조회를 **둘** 더 한다 (발동하려는 효과 · 응수 대상 링크). 둘 다 사전 조회이고, 거절 경로에만 있는 비용이 아니다 — 수락 경로에도 있다 |
| **BLOCKER-F5-12** | `_window_can_act` 가 강제 묶음일 때 관문을 두 번 돌린다 |
| **BLOCKER-F5-13** | 판을 바꾸는 행위마다 `PASS` 둘이 더 필요하다 — 공식 도표가 요구하는 절차이고 비용이지 결함이 아니다 |
| **BLOCKER-F6-4** | `_refusal_verdict` 가 거절 한 건마다 관문을 한 번 더 돌린다 |

#### 해소된 것

| | |
|---|---|
| **BLOCKER-F6-1** | 🔴 **해소됐다.** 기동 효과의 거절이 `INVALID` / `SPELL_SPEED_TOO_LOW` / `missing_rule=None` 이다 (§5.1) |
| **BLOCKER-F6-3** | 🔴 **해소됐다.** 비턴 플레이어의 실제 함정 발동 · 해결을 쟀고 회귀로 남겼다 (§6.4) |

### 11.4 이번 검증의 한계 — 명시한다

| | |
|---|---|
| 전체 회귀를 **한 번의 실행으로** 돌리지 않았다 | 조각마다 `PYTEST_EXIT` 를 남겼다. 조각 **사이의** 상호작용은 재지 않았다 |
| `B` 절의 UNKNOWN 경계는 **전부 합성** | 실제 어니스트 정의에서 분류 칸만 바꾼 등록부다. 실제 카드 지원을 주장하지 않는다 (BLOCKER-F7-4) |
| 기동 효과의 시작 판 | 손으로 구성했다. 등재된 기동 효과를 필드에 내놓는 소환 경로는 범위 밖이다 |
| Discord | 토큰이 없어 문자열 검사로 갈음했다 — **접속 검증이 아니다** |
| 보고 계층의 집계 | `_gate_code` 는 같은 판정을 읽는 것을 쟀지만, 보류에 남지 않는 거절은 집계에 들어가지 않는다 (BLOCKER-F7-1) |

---

## 12. 선행 보고서 정정 내용

보완6 보고서 `docs/phase6ab-followup6-fast-window-legality-and-two-link-followup.md`
머리에 **§0 정정 안내**를 더하고 §13 의 ① 판정을 고쳤다. **원래 문장을
지우지 않고** 무엇이 틀렸는지 적는 방식이다.

| 자리 | 정정 |
|---|---|
| §13 의 ① "**완료**" | 🔴 **부분 완료**로 고쳤다. 목표 문장 안의 요구(*"규칙상 불가능한 행동과 판정 근거가 없는 UNKNOWN 을 구분한다"*)가 기동 효과에서 성립하지 않았으므로, 괄호로 제외를 적는 것으로는 부족했다 |
| §11.3 BLOCKER-F6-1 의 *"그 축을 심는 일은 ①·② 밖이고 저장소 전역에 기록된 `UNKNOWN`"* | 🔴 **축은 이미 있었다.** 없던 것은 그 값이 관문까지 가는 **길** 하나이고, 바꾼 production 파일이 네 개다. "저장소 전역을 건드려야 한다" 는 진단이 과장이었다 |
| §11.3 BLOCKER-F6-3 | 🔴 **검증 공백이었고 해소됐다.** 엔진은 그 자리를 이미 지원하고 있었고, 보완7 이 실제 카드로 재서 회귀로 남겼다 |
| (보완6 이 재지 않은 자리) | 🔴 같은 원인의 결함이 **체인 응답에도** 있었다 — 적법한 함정이 몬스터 효과에 응수할 수 없었다. 보완6 의 모듈 설명이 그 가능성을 *세 번째 경고*로 이미 적어 두었는데 측정하지 않았다 |

🔴 **"거절되므로 충분하다" 로 완료를 판정하지 않았다.** 보완6 의 ①이
그 판정이었고 (차단은 성립했으므로 완료로 적었다), 보완7 이 그것을
정정한다.

---

## 13. 완료 기준별 판정

사용자 §8 이 넷으로 나누라고 적은 그대로 나눈다.

| | 기준 | 판정 | 근거 |
|---|---|---|---|
| 1 | **실행 차단의 정확성** | **완료** | 어니스트 ①이 열린 상태에서 발동 · 해결되고(허용 대조), 빠른 효과 기회에서는 후보도 아니고 직접 `apply` 도 거절이고 상태가 불변이고, 양측이 지나가면 다시 발동된다 (§6.1). 적법한 함정 · 속공 마법 · 유발 등재 · 복수 유발 · 체인 응답 제약은 그대로다 (§6.3) |
| 2 | **판정 의미와 거절 사유의 정확성** | **완료** (몬스터 효과 발동 관문에 대해) | 규칙이 막으면 `INVALID` / `SPELL_SPEED_TOO_LOW` / `missing_rule=None`, 분류가 없으면 `UNKNOWN` 과 모자란 정보의 이름, 통과면 `VALID` / `OK` — 셋이 다른 코드를 받는다 (§5). 🔴 **흐름 계층의 거절 문장은 그대로다** (BLOCKER-F6-2) — 그 자리는 이번 수정에 필요한 부분이 아니고, 그것을 구분해서 남겼다 |
| 3 | **후보 · 관문 · 직접 적용 · 보고의 일치** | **완료** | 네 자리가 `Duel._activation_gate` 하나를 지나고 분류를 넘기는 코드가 그 **안**에 있다 (§7.1). 실측: `_gate_code` · 관문 · `apply` 가 같은 코드, 이유 문장까지 동일. 🔴 **다만 보류에 남지 않는 거절은 집계에 들어가지 않는다** (BLOCKER-F7-1) |
| 4 | **기존 실행 경로와 사본 격리 보존** | **완료** | 원본 · 사본의 분류 · 판정 · 이유가 같고, 사본의 거절 · 발동 · 등록이 부모에 보이지 않는다 (§8). 기르수 전개 · 2링크 후속 유발 · `/combo` 는 **바이트 단위로 동일**하다 (§9) |

🔴 **이번 보완의 완료는 Engine V1 전체나 Phase 6-AB 전체의 완료가
아니다.** 보완7 이 메운 것은 *"이미 확인된 효과 분류를 공통 발동 관문에
전달한다"* 하나이고, 남은 것은 §11.3 의 네 갈래에 그대로 있다. 특히
**분류가 적힌 효과는 둘뿐이다** (BLOCKER-F7-2) — 길을 냈다는 것이
목록을 넓혔다는 뜻이 아니다.

🔴 **통과한 시험 수로 완료를 주장하지 않는다.** 위 근거는 전부 "무엇을
어떤 판에서 쟀는가" 이고, 시험은 그 측정이 회귀하지 않게 못 박은 것이다.

---

## 14. 범위 · 다음 Phase

| | |
|---|---|
| Engine V1 책임 분리 | 유지 — 규칙 · 필수 절차 · 합법성 · 상태 변경은 `engine`, 판단은 AI, 전달과 변환은 연결 계층 |
| ADR-007 | 유지 — 분류는 관측에 없으므로 **값으로** 넘긴다. `engine/activation_timing.py` 는 `engine.effect` 도 `rules` 도 import 하지 않는다 (`test_f04`) |
| `engine.duel` 의 import 경계 | 유지 — 🔴 **한 번 깼고 측정이 잡았다.** 처음에는 `from engine.effect import verified_activation_kind` 를 썼고 `test_a_the_duel_module_still_imports_no_effect_layer` 가 거절했다. 다리 쪽 `engine.spell_activation.effect_kind_of` 를 지나게 고쳤다 (`duel_components` 가 journal 을 그쪽에서 만드는 것과 같은 자리) |
| 둘째 분류표 | 만들지 않았다 — `KIND_SPEED` 하나 (`test_f01` 이 production 전수로 센다) · `verified_activation_kind` 하나 (`test_f02`) |
| 카드 ID 전용 분기 | 없다 — 어니스트 번호는 효과 목록(대장)에만 있고 규칙 · 판정 · 흐름 계층에는 없다 (`test_f03`) |
| Lua 자동 승격 | 하지 않았다 — 입력은 손으로 적어 검증한 정의뿐이다 (§3.1 · §3.5) |
| 관측되지 않은 카드 정보의 정책 노출 | 없다 — 분류는 `ActivationTiming` 에만 들어가고 `GameStateView` 는 그대로다 |
| 범위 밖 | 신규 카드 실행 지원 확대 · 신규 소환 기능 · 전략 평가 · 학습 · EDOPro·리플레이 연동 · 검색 · 카드·금제 업데이트 · 광범위한 최적화 — 손대지 않았다 |
| 광범위한 공개 계약 변경 | 없음. 두 칸 모두 **기본값 `None`** 이고, 주지 않으면 몬스터 효과는 `UNKNOWN` 이다 — 조용한 허가가 되지 않는다 |
| 다음 Phase | 🔴 **시작하지 않았다** |
