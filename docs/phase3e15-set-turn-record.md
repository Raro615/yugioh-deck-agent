# Phase 3-E-15 — 세트한 턴의 기록 (`SET_ACTIVATION_MISSING` RESOLVED)

- 실제 Base: `5c53dca` (Phase 3-E-14). 계보 기준: `a7396b5` (3-E-13)
- 결론: **`SET_ACTIVATION_MISSING` RESOLVED.** 세트한 속공 마법이 세트한 턴에는
  `INVALID`, 다음 턴부터 `VALID` 이고, **상대 턴의 응답으로도 발동한다.**
- 함정은 여전히 `UNKNOWN` — **이유가 세트한 턴이 아니다.**

---

## §3 — Audit: 무엇이 있었고 무엇이 없었나

| 조사 대상 | 결과 |
|---|---|
| `RuleActionKind.SET_SPELL_TRAP` | **존재하지 않았다** (`NORMAL_SUMMON` · `ATTACK` 둘뿐) |
| `SET_SPELL_TRAP` 실행 경로 | `SetExecutor.apply` → 존 이동만. `rule_uses` 에 **아무것도 적지 않았다** |
| `SET_MONSTER` 실행 경로 | `rule_uses.record(..., NORMAL_SUMMON)` — 소환권을 쓰므로 (RULE-SUMMON-009) |
| `CardInstance` | zone · sequence · position · previous · counters · status_flags. **턴 없음** |
| `set_turn` / `placed_turn` / `set_history` | repository 전체에 **하나도 없음** |
| `RuleUsageRegistry` 키 | `(턴, 플레이어, 행위)` 와 `(턴, 플레이어, instance_id, 행위)` |
| `clone()` | `rule_uses=self.rule_uses.clone()` — 이미 깊은 복제 |
| `canonical_state()` | `self.rule_uses.canonical_state()` 포함 — **이미 해시에 들어 있다** |
| `GameStateView` 의 rule-usage | `normal_summons_used` · `attacks_used` **둘뿐** |

### §4 — 기존 정보로는 안 된다

`previous=HAND` 는 "방금 패에서 왔다" 이고 "몇 턴 전에 세웠는가" 가 아니다.
Phase 3-E-14 가 이미 그 둘을 구분해 적어 두었고, 이번에도 같은 결론이다.

> `SET STATE` ≠ `SET HISTORY`

---

## §1 · §5 — 핵심 설계 결정: **D (RuleUsageRegistry)**

| 후보 | 판단 |
|---|---|
| A. `GameStateView` | **기각** — 상대가 언제 세웠는지는 공개 정보가 아니다 (§12 · §13) |
| B. `CardInstance.set_turn` | 기각 — `CardInstance` 는 **상태**를 갖고, 세트한 턴은 **역사**다. 자리를 떠날 때마다 무효화를 손으로 챙겨야 한다 |
| C. `GameState` 에 별도 표 | 기각 — D 가 이미 그 표다 |
| **D. `RuleUsageRegistry`** | **채택** |
| E. 별도 history/event | 기각 (§2 금지) |
| F. 기존 action 기록 재사용 | 그런 것이 없다 (action history 가 없다) |

채택 이유 네 가지.

1. **키가 이미 턴을 담는다.** 담을 그릇을 새로 만들지 않았다 (§26-1).
2. **역사는 무효화하지 않는다.** "턴 5 에 #40 을 세웠다" 는 영원히 참이다.
   현재 상태(존 · 표시 형식)와 **AND** 해서 읽으므로, 카드가 자리를 떠나도
   오래된 기록이 판단을 오염시키지 않는다 (§20-10).
3. `clone()` · `canonical_state()` 가 **이미** 이 표를 다룬다 (§14 · §15 무료).
4. `instance_id` 가 키에 있다 — `ATTACK` 과 같은 이유다 (§21).

### 받아들인 의미 충돌 하나 (§5-Q1 · §5-Q2)

`RuleUsageRegistry` 는 자신을 **"규칙이 정한 1턴 1회의 기록"** 이라고 적고
있었다. 마법 · 함정 세트는 **횟수 제한이 없다** — 칸이 있는 만큼 할 수 있다.
그대로 넣으면 "세트는 1턴 1회다" 라는 거짓이 enum 이름에서 읽힌다.

그래서 **틀을 넓혔다**: "횟수를 정해 둔 행위" → **"턴 단위로 묻는 행위"**.
세는 것이 **횟수가 아니라 턴**이라는 것을 `RuleActionKind.SET_SPELL_TRAP` 의
설명과 모듈 설명에 적었다. 숨기지 않고 적는 것이 §27 의 "기존 semantics 와
충돌" 을 BLOCKER 로 만들지 않는 조건이다.

### §12 · §13 — `GameStateView` 변경 **0**

판정하는 자리는 `Duel` 이다. 체인과 우선권이 이미 그렇게 처리된다 (ADR-007:
검증기는 관측만 읽고, 관측 밖의 사실은 판을 들고 있는 쪽이 값으로 넘긴다).

```
SetExecutor.apply         →  rule_uses.record_card(...)        WRITE (한 곳)
Duel._set_this_turn       →  rule_uses.used_card(...)          READ
ActivationTiming          →  set_this_turn=<bool | None>       값으로 전달
ActivationTimingChecker   →  규칙 적용                          READ
```

---

## §9 — Set-Turn Semantics

| 상황 | `set_this_turn` |
|---|---|
| 현재 턴에 세트 | `True` |
| 이전 턴에 세트 | `False` |
| 마법 & 함정 존이 아님 (패 등) | `False` (기록이 없다) |
| 앞면 | 기록은 남지만 **타이밍 규칙의 자리가 아니다** (`reveal` 뒤) |
| 카드를 못 찾음 | **`None` = 모른다** → 관문이 `UNKNOWN` |
| 같은 `card_id` 다른 instance | **독립** |

`None` 을 `False` 로 읽지 않는다 — 모르는 것을 "세우지 않았다" 로 바꾸면
세트한 턴에도 발동할 수 있게 된다.

---

## §10 · §11 — Timing: 세 조항이 서로 다르게 적는다

| | 조항 | 세트한 턴 | 자기 턴 | 상대 턴 |
|---|---|---|---|---|
| 세트한 **통상 마법** | RULE-SPELLTRAP-012 | **걸리지 않는다** | 메인 페이즈만 | **못 한다** |
| 세트한 **속공 마법** | RULE-SPELLTRAP-007 | **INVALID** | 아무 페이즈 | **한다** |
| 세트한 **함정** | RULE-SPELLTRAP-009 | (기록은 남는다) | — | — · 아직 범위 밖 |

> **SET_TURN ≠ ACTIVATION_INVALID.** 스펠 스피드로 가른다 — 1 은 걸리지 않고
> 2 · 3 만 걸린다. 카드 이름을 보지 않는다 (§13).

함정이 남은 이유는 **세트한 턴이 아니다.** 유발 · 응답 타이밍 계층이 없고,
`_OUT_OF_SCOPE_TYPES` 의 `TRAP` 항목이 그것을 말한다. 기록이 생겼다는 이유로
통과시키면 없는 규칙을 있는 것처럼 쓰게 된다.

---

## §6 · §17 — Action → State Transition

```
PlayerAction.SET_SPELL_TRAP
  → Duel.apply → ActionExecutor → SetSpellTrapHandler → SetExecutor.apply
      ① procedure.plan / procedure.place     패 → SZONE (뒷면)
      ② rule_uses.record_card(턴, 플레이어, instance_id, "set_spell_trap")
```

②가 ① **뒤**인 것은 소환권 기록과 같은 이유다 — 배치가 실패하면 기록만 남은
판이 된다. 기존 동작을 복제하지 않았고, 기록은 **한 번만** 일어난다
(`test_17` 이 `record_card(` 를 부르는 모듈이 하나인지 센다).

---

## §19 — 여섯 시나리오 (전부 실행으로 측정)

| # | 상황 | 후보 | validator | `set_this_turn` | apply |
|---|---|---|---|---|---|
| A | 통상 마법 세트 → **같은 턴** | O | `valid` | `True` | **O** (RULE-SPELLTRAP-012) |
| B | 속공 마법 세트 → **같은 턴** | X | `valid` | `True` | **X — `SET_THIS_TURN`** |
| C | 함정 세트 → 같은 턴 | X | `unknown` | `True` | X (더 넓은 이유) |
| D | 속공 마법 세트 → **다음 턴** | **O** | `valid` | `False` | **O** |
| D2 | 속공 마법 → **상대 턴 응답** | **O** | `valid` | `False` | **O — 체인 링크 2** |
| E | 두 장 세트 → 한 장 발동 | 남은 장 `True` 유지 | | | |
| F | 같은 `card_id` 두 장, 다른 턴 | 이전 턴 장만 후보 | | | |

B 에서 `validator=valid` 인 것이 핵심이다 — 검증기는 세트한 턴을 **보지
않는다**. 체인을 보지 못해 스펠 스피드 1 의 한가운데 발동에도 `VALID` 를 내는
것과 같은 분업이고, 막는 것은 흐름 계층이다.

### §9 실제 Trace — D2

```
[SET]       P0 turn=5  리로드 → SZONE 뒷면   rule_uses{(5,0,#40,set_spell_trap):1}
[TURN]      turn=6  turn_player=P1
[ACTIVATE]  P1 욕망의 항아리 → 체인 1 · 창=response · 쥔 자리=P0
[CANDIDATE] P0 후보 = [리로드]          (turn_player 는 그대로 P1)
[VALIDATE]  validator=valid · set_this_turn=False · 스펠 스피드 2 → 2 응수 가능
[APPLY]     체인 링크 2 · SZONE 에서 앞면으로 (칸 그대로)
[RESOLVE]   양쪽 패스 → 역순 해결 → 둘 다 묘지
```

---

## §14 · §15 · §16 — 해시 · 복제 · 난수

- **해시**: `rule_uses` 가 이미 `canonical_state` 에 있고 키에 턴이 있으므로
  "이번 턴에 세운 판" ≠ "이전 턴에 세운 판". **새로 넣은 것이 없다.**
  `test_11` 이 기록을 지우면 해시가 달라지는 것으로 이를 역으로 잰다.
- **복제**: `clone()` 이 기록을 정확히 옮기고, 사본에서 세워도 원본의 해시와
  표가 변하지 않는다 (`test_12`).
- **난수**: 세트는 `draws` 를 늘리지 않는다 (`test_13`).
- **읽기는 쓰지 않는다**: `legal_actions` · `_set_this_turn` · 타이밍 관문을
  여러 번 불러도 표와 해시가 그대로다 (`test_15`).

---

## §22 — Hidden Information

| | 결과 |
|---|---|
| 상대의 세트한 턴 | **비공개** — `GameStateView` 에 그런 필드가 없다 |
| 상대의 세트 카드 정체 | **비공개** (`card_id=None` · `name=None` · `definition=None`) |
| 상대의 세트 카드 장수 | 공개 (원래부터) |
| `GameStateView` 변경 | **0** |
| 관측의 rule-usage 필드 | 여전히 **둘** (`normal_summons_used` · `attacks_used`) |

`test_14` 가 셋째 필드가 생기지 않았음을 **필드 집합으로** 고정한다 — 간접
노출(새 getter)도 막는다.

---

## §23 · §24 — Evaluation · Search

- **Evaluation 변경 0.** 같은 판에서 기록만 지워도 점수가 같고,
  `agent/evaluation.py` 에 `rule_uses` · `set_this_turn` 류 문자열이 없다
  (`test_16`).
- **Search ranking 로직 변경 0.** `agent/` 전체 변경 0.
- **후보는 늘었다.** 세트한 속공 마법이 (ⓐ 다음 턴 자기 턴, ⓑ 상대 턴 응답
  창) 후보가 된다. 경로는 그대로다 — legal → simulate → evaluate → rank.
  fake simulation 없음.

---

## §25 — 성능

`_set_this_turn` 은 dict 조회 하나다 (`O(1)`). 선형 탐색도 새 캐시도 없다.
전체 테스트 시간은 **366s → 349s** 로, 늘지 않았다 (후보가 늘었는데도 그렇다 —
세트한 속공 마법이 열리면서 듀얼이 조금 더 빨리 끝나는 쪽으로 움직였다).

---

## 변경 파일 (6개, `agent/` 0개, `GameStateView` 0개)

| 파일 | 변경 |
|---|---|
| `engine/state/rule_usage.py` | `RuleActionKind.SET_SPELL_TRAP` + `PER_CARD_ACTIONS`. 틀을 "턴 단위로 묻는 행위" 로 넓힘 |
| `engine/set_card.py` | `SetExecutor.apply` 가 카드별로 기록 (쓰는 곳 **하나**) |
| `engine/activation_timing.py` | `ActivationTiming.set_this_turn`, `_set_turn_refusal`, `SET_TURN_MISSING`, `UNRESOLVED_TIMING_RULES` 갱신 |
| `engine/duel.py` | `_set_this_turn` (READ) → `ActivationTiming` 으로 전달 |
| `engine/action_validation.py` | `SET_ACTIVATION_MISSING` **삭제**. `_is_set_normal_spell` → `_is_set_spell` (속공 마법 포함). 세트한 속공 마법은 `IsTurnPlayer` 를 지지 않는다 |
| `engine/validation.py` | `ValidationCode.SET_THIS_TURN` |

새 엔진 0 · 새 `ActionKind` 0 · 새 state 필드 0.

---

## 테스트

### 전체

```
3496 passed, 4 skipped in 349.08s
```

기준선 3480 − 1 + 17 = 3496. 빠진 1 은 `test_10` 의 parametrize 두 경우 중
**세트한 속공 마법**이 빠진 것이다 — 더 이상 `UNKNOWN` 이 아니므로 그 목록에
있을 자리가 없고, 같은 주장을 `test_set_turn_record.py` 의 `test_06` ·
`test_08` 이 더 강하게 잰다 (`INVALID` / `VALID` 로).

신규 `tests/engine/test_set_turn_record.py` — **17개**

1. 기록이 남는다 (카드별 표에, 플레이어별 표에는 안 적는다)
2. 이 표에 적는 것이 맞는가 — `card_key` 는 받고 `key` 는 거부한다
3. **`card_id` 가 아니라 `instance_id`** 로 센다 (같은 이름 두 장, 다른 턴)
4. 같은 턴 두 장 — 한 장 발동해도 남은 장 독립
5. 세트한 통상 마법은 이 제약을 **무시한다**
6. 세트한 속공 마법은 같은 턴 **`INVALID`** (`UNKNOWN` 이 아니다)
7. 세트한 함정은 **더 넓은 이유**로 여전히 `UNKNOWN`
8. 다음 턴부터 발동 — 바뀐 것은 턴 번호 하나
9. **상대 턴 응답으로 체인 링크 2** (turn_player 불변)
10. set state 가 같고 set history 만 다른 두 판
11. 해시가 차이를 유지한다
12. 복제가 옮기고, 사본의 변경이 번지지 않는다
13. 난수 소비 0
14. 세트한 턴이 관측에 **닿지 않는다** (필드 집합으로 고정)
15. 읽기가 쓰지 않는다
16. Evaluation 이 읽지 않는다
17. 새 ActionKind · 새 엔진 없음 · 쓰는 곳 하나

### 고의 위반 6건 — 전부 잡힘

| 위반 | 잡은 시험 |
|---|---|
| A 아예 기록하지 않는다 | 12개 |
| B 플레이어 단위로 센다 (카드 구분 상실) | `test_03` |
| C `None`(모름)을 통과시킨다 | `test_set_card_activation::test_03` |
| D 통상 마법에도 세트한 턴을 적용한다 | 5개 |
| E 관측에 세트한 턴을 노출한다 | `test_14` |
| F 후보 생성이 기록을 **쓴다** | 6개 |

### 수정한 기존 테스트 6건 (삭제 0 · skip 0)

| 테스트 | 틀렸던 가정 |
|---|---|
| `test_set_card_activation::test_01` | "**세트한 턴은 적혀 있지 않다**." Phase 3-E-14 당시의 사실이고, 그 한 줄이 다음 단계를 가리켰다. 주장을 **반대 방향으로 강화**했다 |
| `test_set_card_activation::test_03` | "타이밍 관문은 세 종류 모두에 `VALID` 를 낸다." 이제 세트한 턴을 **받아서** 본다 — 안 주면 `UNKNOWN`, `True` 면 `INVALID`, `False` 면 `VALID` |
| `test_set_card_activation::test_10` | 세트한 속공 마법이 `UNKNOWN` 목록에 있었다. 모자란 것이 "세트한 턴" 하나뿐이었고 채워졌다. **함정과 이유를 나눠 적어 둔 것이 여기서 값을 했다** |
| `test_set_card_activation::test_15` | "세트된 속공 마법은 세트된 마법이 아니다." 두 질문을 섞은 가정이었다 — "세트된 마법인가"(자리 · 표시 형식)와 "세트한 턴이 걸리는가"(조항)는 다르다. 앞의 것은 둘 다 참이고, 뒤의 것을 타이밍 관문으로 옮겼다 |
| `test_activation_timing::test_f_the_context_stores_nothing_twice` | "`ActivationTiming` 의 필드는 세 개다." 주장은 "**관측과 겹치지 않는다**" 였고 `set_this_turn` 은 관측에 없는 값이므로 그 주장을 깨지 않는다 |
| `test_effect_action_space_audit::test_05b3` | "세트된 속공 마법은 여전히 `UNKNOWN`", 근거는 "세는 자리가 없다". **그 근거가 사라졌다.** 검증기가 `VALID` 를 내고 세트한 턴은 흐름 계층이 본다는 것으로 바꿨다 |

---

## §15 — STRUCTURAL 상태

- **`SET_ACTIVATION_MISSING` — RESOLVED.** 그 문자열이 말한 것은 "세트한 턴을
  세는 자리가 없다" 였고, 이제 있다. 상수를 **지웠다** (지우고 이유를 그 자리에
  주석으로 남겼다).
- 새 STRUCTURAL ID **만들지 않았다**.
- STRUCTURAL-34 · 124 · 128 · 131 · 133 유지. 134 RESOLVED 유지.

---

## §16 — 남은 Set 관련 문제

| 이름 | 상태 |
|---|---|
| `SET_ACTIVATION_MISSING` | **RESOLVED** |
| `SET_ACTIVATION_TIMING` | 열려 있음 — 상대 턴에 **창이 열리는 자리**가 발동 뒤뿐이다 (STRUCTURAL-34: Phase Change · AFTER_CHAIN 우선권). 상대가 아무것도 발동하지 않으면 세트한 속공 마법을 쓸 기회가 없다 |
| `SET_ACTIVATION_EXECUTION` | 열려 있음 — `reveal` 은 "해결 뒤 묘지" 하나만 안다. 지속 · 필드 · 지속 함정은 필드에 남는다 |
| `SET_CARD_EFFECT_EXECUTION` | 열려 있음 — 함정의 유발 타이밍 계층 (`_OUT_OF_SCOPE_TYPES` 의 `TRAP`) |
| 비용 | ADR-008 그대로 (등재 16개 전부 비용 없음 — 도달 불가) |

---

## §17 — 다음 Phase 후보 (하나)

**세트한 함정의 발동 — `_OUT_OF_SCOPE_TYPES` 의 `TRAP` 항목.**

이번 감사가 그 범위를 좁혀 두었다. 등재된 함정 4장
(욕망의 선물 · 벌금 · 강제 탈출 장치 · 의적의 입문서)은 **전부
`EVENT_FREE_CHAIN`** 이다 — 즉 유발 조건이 없고, 필요한 타이밍 규칙이
**세트한 턴 + 스펠 스피드뿐**이며 둘 다 이제 있다. 해결 뒤 묘지로 가는
모양도 통상 함정이면 `reveal` + `retire` 와 같다.

그래서 첫 질문은 "함정 전체" 가 아니라 **"유발 조건이 없는 통상 함정만 범위에
넣을 수 있는가, 그 경계를 카드 데이터에서 어떻게 읽는가"** 다 —
`EVENT_FREE_CHAIN` 에 해당하는 것이 이 엔진의 `EffectDefinition` 에 적혀
있는지가 그 Phase 의 BLOCKER 조건이 된다.
