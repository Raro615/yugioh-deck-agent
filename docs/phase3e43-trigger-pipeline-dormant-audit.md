# Phase 3-E-43 — Trigger pipeline dormant 구조 감사

> **AUDIT-ONLY.** production 을 한 줄도 고치지 않았다 (§11 에서 `git diff` 로 확인).
> 목적은 "trigger 구조를 고치는 것" 이 아니라 **현재 trigger 구조가 실제 production
> architecture 에서 어떤 상태인지 확정하는 것** 이다.

---

## 1. Phase / Base / 실제 HEAD

| 항목 | 값 |
| --- | --- |
| Phase | 3-E-43 — Trigger pipeline dormant structure audit |
| 성격 | **AUDIT-ONLY** (production diff = 0) |
| Base | Phase 3-E-42 (`dfd08a6` + 보고서 `4f009fc`) |
| 작업 시작 시 실제 HEAD | `4f009fc` — "Phase 3-E-42 보고서: commit SHA · push 결과 기록" |
| 두 SHA 가 HEAD 의 조상인가 | ○ `dfd08a6` · `4f009fc` 둘 다 확인 |
| `docs/phase3e42-...-audit.md` | ○ 존재 (36,684 bytes) |
| `tests/test_simulation_result_search_candidate_audit.py` | ○ 존재 (36 tests) |
| working tree | clean (reset · checkout 하지 않았다) |
| 브랜치 | `claude/pensive-goodall-te1egy` |
| 결과 commit | `<<SHA1>>` — `Phase 3-E-43: audit dormant trigger pipeline structure` |
| push | <<PUSH>> |

---

## 2. Trigger 관련 구조 전체 목록

**이번 감사에서 처음 드러난 사실**: trigger 관련 production 모듈이 **셋이 아니라
다섯**이다. 앞선 Phase 들은 `trigger.py` · `trigger_chain.py` · `trigger_order.py`
만 보았는데, 그 부품을 **조립하는** 모듈이 둘 더 있다.

| 층 | 모듈 | 줄 수 | 역할 |
| --- | --- | --: | --- |
| **LIVE** | `engine/activation_timing.py` | 541 | 스펠 스피드 · 발동 타이밍. `duel.py` · `response.py` 가 쓴다 |
| **DORMANT-ASSEMBLY** | `engine/timing.py` | 436 | 창(window) 하나를 열고 닫는 **조립도**. `TriggerCollector` · `TriggerChainIntegrator` 를 만든다 |
| 〃 | `engine/event_pipeline.py` | 417 | 상태 변화 → 사건 읽기 |
| **DORMANT-PARTS** | `engine/trigger.py` | 1,565 | 선언 · 수집 · 판정 (`TriggerSpec` · `TriggerRegistry` · `TriggerCollector` · `TriggerEligibilityJudge` · `EligibilityGate` …) |
| 〃 | `engine/trigger_chain.py` | 594 | 후보 → 체인 삽입 |
| 〃 | `engine/trigger_order.py` | 443 | SEGOC 순서 |
| | **합계 (dormant)** | **3,455** | |

부품 층이 선언하는 **최상위 이름 32개**를 전수 측정했다 (`test_03`). 주요 이름:

```
TriggerSpec · TriggerRegistry · TriggerCandidate · TriggerCollector ·
TriggerCollection · TriggerEligibility · TriggerEligibilityJudge · TriggerGroup ·
GateVerdict · EligibilityGate · TriggerStatus · TriggerRequirement · TriggerWording ·
TimingEvent · TimingPoint · PlayerRole · OrderingBasis · ChainInsertion ·
TriggerChainIntegrator · TriggerChainPlan · TriggerChainEntry ·
TriggerOrderer · TriggerOrdering · TriggerError · timing_for · timing_events …
```

---

## 3. 실제 production caller graph

### import 폐쇄 (`engine` 안)

```
engine.duel  ──────────────────────────────── (engine 모듈 57개에 닿는다)
   │
   ├─ engine.chain                   ← LIVE  (CHAIN_DEFINITION_UNAVAILABLE 한 자리)
   ├─ engine.response ─┐
   └─ engine.activation_timing ←─────┘  LIVE
          │
          └─ from engine.trigger import TimingPoint      ← ★ 넘어오는 이름 **하나**

engine.timing          ← production importer **0곳**  (테스트만 쓴다)
engine.event_pipeline  ← production importer **0곳**
engine.trigger_chain   ← engine.timing 만
engine.trigger_order   ← engine.timing · engine.trigger_chain 만
```

**폐쇄 밖**: `engine.timing` · `engine.event_pipeline` · `engine.trigger_chain` ·
`engine.trigger_order` (`test_06`).

`engine/summon.py` · `engine/execution.py` · `engine/__init__.py` · `engine/trigger.py`
가 `event_pipeline` 을 언급하지만 **전부 docstring 의 `:class:` 참조**다 — import 가
아니다. 문자열로 세면 그것까지 걸린다 (이 감사에서 구문과 문자열을 구분해야 했던
자리다).

### live 경계가 **얼마나 얇은가**

| 측정 | 값 |
| --- | --- |
| `activation_timing.py` 가 `engine.trigger` 에서 가져가는 이름 | **`TimingPoint` 하나** (`test_07`) |
| 그 이름을 **값으로** 쓰는 자리 (live 모듈 안) | **0곳** — 타입 주석으로만 쓰인다 (`test_08`) |
| `ActivationTiming.point` 를 채우는 production 생성 자리 | **0곳** — 두 생성 모두 `point=` 를 넘기지 않으므로 늘 `None` = "모른다" (`test_09`) |
| `TimingPoint` 를 값으로 읽는 production 자리 | `event_pipeline.py:188` **하나** — 그 모듈도 dormant |

즉 **1,565줄 모듈의 live 기여가 "채워지지 않는 필드의 타입 주석" 하나**다.

### 런타임 확인 — 가장 강한 증거

세 부품 모듈의 클래스 메서드와 최상위 함수를 **테스트 안에서만** 감싸 세고 실제
듀얼을 돌렸다 (production 수정 없음).

| 모듈 | 16판 1,359행동에서의 호출 수 |
| --- | --: |
| `engine/activation_timing.py` | **86,439** |
| `engine/trigger.py` | **0** |
| `engine/trigger_chain.py` | **0** |
| `engine/trigger_order.py` | **0** |

세부: `ActivationTimingChecker.spell_speed` 18,766 · `classify_spell_speed` 18,766 ·
`check` 15,253 · `_set_turn_refusal` 15,253 · `_passed` 12,105 ·
`speed_of_link` 3,148 · `SpellSpeed.responds_to` 3,148.

**`trigger.py` 는 import 되지만 그 안의 어떤 함수도 실행되지 않는다** (`test_10` ·
`test_11`). 그리고 `duel.py` 는 "trigger" 라는 말을 **한 번도** 쓰지 않는다
(`test_12`).

### 추적한 다섯 경로 (§"최소 5개")

| # | 경로 | 결과 |
| --- | --- | --- |
| 1 | `Duel.apply` → `_apply_activation` → `_activation_gate` → `ActivationTimingChecker.check` | **LIVE** (15,253회) |
| 2 | `Duel.legal_actions` → `_activation_actions` → `_activation_gate` → 같은 체커 | **LIVE** |
| 3 | `TriggerRegistry` 생성 → … | **없다.** production 생성 0곳 (`test_13`) |
| 4 | `TriggerCollector` 생성 → `TriggerEligibilityJudge.judge_all` | `timing.py:342` 가 **만들지만** `timing.py` 를 import 하는 production 이 없다 (`test_04` · `test_15`) |
| 5 | `TriggerChainIntegrator` 생성 → 체인 삽입 | `timing.py:298` 이 **만들지만** 같은 이유로 닿지 않는다 |

`judge_all(` 을 부르는 production 자리는 **부품 층 밖에 하나도 없다** (`test_15`).

---

## 4. dormant 여부

**dormant 다** — 그리고 "단순 미사용" 보다 정확한 표현은 **"조립도가 펴지지 않은
부품 창고"** 다.

| 질문 | 답 |
| --- | --- |
| 구조가 존재하는가 | ○ 3,455줄, 최상위 이름 32개 |
| production 이 import 하는가 | △ `trigger.py` 만, **이름 하나** |
| production 이 **실행**하는가 | **✕ 0회** (16판 측정) |
| 테스트가 쓰는가 | ○ 많이 — `TriggerSpec` 88회 · `TriggerStatus` 125회 · `EligibilityGate` 50회 등 |
| 서로 다른 실행 경로가 존재하는 구조인가 | **그렇다** (§5 의 R-2) — 같은 질문에 대한 **두 구현**이 있고 한쪽만 돈다 |

§9 가 물은 구분: **단순 미사용이 아니다.** 부품 층은 live 경로가 이미 답하는 질문
넷을 **자기 어휘로 다시** 답하고 (`EligibilityGate` 5개 중 4개), 하나는 live 에
대응이 없다 (`EVENT_RELATION`).

---

## 5. 구조별 분류

분류: **USED** 실제로 실행된다 / **PRESERVED** 타입·어휘로만 live 에 닿는다 /
**DORMANT** 실행 0 / **DUPLICATED** live 가 같은 질문을 따로 답한다 /
**CONFLICT** live 와 뜻이 어긋난다.

| 구조 | 분류 | 근거 |
| --- | --- | --- |
| `activation_timing.ActivationTimingChecker` | **USED** | 15,253회 |
| `activation_timing.SpellSpeed` · `classify_spell_speed` | **USED** | 18,766회 |
| `trigger.TimingPoint` | **PRESERVED** | 타입 주석 하나. 값으로 읽히지 않고 채워지지 않는다 |
| `trigger.TriggerSpec` · `TriggerRegistry` | **DORMANT** | production 생성 0곳 |
| `trigger.TriggerCollector` · `TriggerCollection` | **DORMANT** | `timing.py` 만 만들고 그 모듈이 닿지 않는다 |
| `trigger.TriggerEligibilityJudge` · `TriggerEligibility` | **DORMANT** + **DUPLICATED** | 다섯 관문 중 넷이 live 세 관문과 같은 질문 (R-2) |
| `trigger.EligibilityGate.EVENT_RELATION` | **DORMANT** + **CONFLICT** | `INVALID` + `RULE_NOT_IMPLEMENTED` (M3, §6) |
| `trigger.GateVerdict` · `TriggerStatus` · `TriggerRequirement` · `TriggerWording` · `PlayerRole` | **DORMANT** | 어휘만 존재 |
| `trigger.TimingEvent` | **DORMANT** | 생성 0곳 (production) |
| `trigger_chain.TriggerChainIntegrator` · `TriggerChainPlan` · `TriggerChainEntry` | **DORMANT** | `timing.py` 경유만 |
| `trigger_chain.ChainInsertion` | **DORMANT** + **CONFLICT** | `CHAIN_DEFINITION_UNAVAILABLE` 에서 live 와 어긋난다 (R-1, §7) |
| `trigger_order.TriggerOrderer` · `TriggerOrdering` · `OrderingBasis` | **DORMANT** | `timing.py` · `trigger_chain.py` 경유만 |
| `timing.py` 전체 | **DORMANT-ASSEMBLY** | production importer 0곳 |
| `event_pipeline.py` 전체 | **DORMANT-ASSEMBLY** | production importer 0곳 |

### R-2 — 중복의 실체 (`test_19`)

| dormant 관문 (`TriggerEligibilityJudge.judge`) | live 대응 (`Duel._activation_gate` 외) |
| --- | --- |
| `EVENT_RELATION` | **없다** — live 경로에는 사건이 없다 |
| `ACTIVATION_ZONE` | `ActionValidator` 의 존 요구 |
| `TRIGGER_CONDITION` | `EffectActivator.can_activate` 의 조건 평가 |
| `EXECUTION_AUTHORITY` | `_check_authority` (ADR-004 출처 금지) |
| `COST_FEASIBILITY` | `_activation_actions` 의 `definition.cost.costs` 걸러내기 |

**넷이 같은 질문을 두 구현으로 답한다.** 지금은 한쪽이 돌지 않으므로 해가 없지만,
연결하는 순간 **둘이 같은 답을 내는지**가 먼저 증명되어야 한다. (3-E-28 이
`_judge`/Gate 이중 평가를 이미 감사했다 — 이번에는 그 둘이 **live/dormant 로
갈려 있다**는 사실을 더한다.)

---

## 6. M3 의 `INVALID` + `RULE_NOT_IMPLEMENTED` 재검증

```python
# engine/trigger.py  _event_relation (약 1306행)
return _gate(
    EligibilityGate.EVENT_RELATION,
    ActionValidity.INVALID,                  # ← 확실한 거부
    ValidationCode.RULE_NOT_IMPLEMENTED,     # ← policy 가 "모른다" 라고 하는 코드
    f"이 선언은 {event.point.value} 사건에 반응하지 않습니다.",
)
```

| 재검증 항목 | 결과 |
| --- | --- |
| 그 자리가 그대로 있는가 | ○ (`test_14`) — 3-E-38 이 **일부러 남겼고** 그 뒤로 바뀌지 않았다 |
| policy 가 그 코드를 어떻게 보는가 | `ActionValidity.UNKNOWN` — 즉 **어긋남이 그대로다** |
| production 판정을 만들 수 있는가 | **아니다.** `trigger.py` 의 메서드 호출이 0회이고 (`test_10`), `_event_relation` 을 `duel.py` · `response.py` · `chain.py` 가 언급하지 않는다 (`test_15`) |
| `judge_all` 호출자 | 부품 층 밖에 **0곳** |
| 자기 방어 장치 | `trigger_chain._refusal_code` 의 기본값이 `CANDIDATE_NOT_ELIGIBLE` 이다 — gate 가 코드를 **적지 않았다면** 저절로 맞는 답이 나왔을 자리다 (`test_16`) |

**결론: M3 는 여전히 살아 있지 않다.** 코드는 그 자리에 있고 뜻은 어긋나 있으나,
그 어긋남이 어떤 production 판정도 만들지 못한다.

---

## 7. `CHAIN_DEFINITION_UNAVAILABLE` 관계

**이번 Phase 가 찾은 가장 분명한 구조적 위험(R-1)이다** (`test_17`).

| carrier | 모듈 | Duel 폐쇄 | 짝지은 status | 읽히는 뜻 |
| --- | --- | :--: | --- | --- |
| `chain.py:592` | `engine/chain.py` | **안 (LIVE)** | `ChainResolutionStatus.INVALID_CHAIN_LINK` | **확정 거부** 쪽 |
| `trigger_chain.py:406` | `engine/trigger_chain.py` | **밖 (DORMANT)** | `ChainInsertion.UNKNOWN` | **모름** ("확인할 수 없습니다") |

두 쪽이 같은 코드에 **반대 축의 상태**를 붙인다. 그래서 Phase 3-E-40 이 48개 중
**이 하나만** policy 에서 `None`("이 코드만으로는 정할 수 없다") 으로 두었고,
`test_17` 이 `None` 인 코드가 정확히 이것뿐임을 확인한다.

**함의**: dormant 구조가 **live policy 의 한 칸을 묶어 두고 있다.** live carrier
하나만 보면 그 코드는 `INVALID` 로 확정된다 — 즉 "정할 수 없음" 의 원인이 **돌지
않는 코드**다. 이것이 "dormant 는 완전히 격리되어 있다" 를 말할 수 없는 까닭이다.

**영향 범위는 좁다.** 부품 층의 호출 인자로 등장하는 `ValidationCode` 는 **7개**
(`OK` · `RULE_NOT_IMPLEMENTED` · `EXECUTION_FORBIDDEN` ·
`CHAIN_DEFINITION_UNAVAILABLE` · `CANDIDATE_NOT_ELIGIBLE` · `HIDDEN_CARD` ·
`SOURCE_WRONG_ZONE`) 이고 나머지 **41개는 dormant 층과 아무 관계가 없다**
(`test_18`). 그 7개 중 live 와 **status 가 어긋나는 것은 하나**다.

---

## 8. Engine V1 영향

**없다.**

| 측정 | 결과 |
| --- | --- |
| 네 정책 조합 × seed 2 전체 듀얼 | **4/4 completed** · refusal 0 · `state_hash` 64자 (`test_20`) |
| 16판 1,359행동 중 trigger 부품 호출 | **0회** |
| `duel.py` 가 trigger 를 언급 | **0회** |
| `TriggerSpec`/`TriggerRegistry` production 생성 | **0곳** |
| Engine V1 freeze | **유지** — `engine/` diff 0 |

dormant 구조가 **없는 것처럼** 듀얼이 돌아간다. §"PRODUCTION_BLOCKER" 가 요구하는
"호출되어야 하는데 호출되지 않아 동작 오류" 의 **재현 시나리오를 만들 수 없었다** —
현재 등록된 16개 효과에 트리거 효과가 없고, 룰북에서 온 네 승리 조건에도 트리거가
개입하지 않는다.

---

## 9. AI / Search 영향

**없다.** `agent/` 의 일곱 모듈(`search` · `simulation` · `evaluation` · `policy` ·
`heuristic` · `arena` · `runner`) 전부에 `Trigger` · `trigger` · `TimingEvent` ·
`event_pipeline` 이라는 **문자열이 하나도 없다** (`test_21`).

AI 는 `PlayerAction` 을 고르고, 후보는 `legal_actions()` 가 만들고, 그 목록은
`_activation_gate`(live) 가 정한다. 트리거 계층은 그 경로에 **참여하지 않는다.**

---

## 10. hidden information / state_hash / RNG 영향

| 불변식 | 결과 |
| --- | --- |
| `legal_actions()` 를 양쪽 자리에서 읽은 뒤 `state_hash` | **불변** (`test_22`) |
| 같은 뒤 RNG `draws` | **불변** |
| 상대 패 관측 | `concealed=True` · `cards=()` (`test_23`) |
| `ValidationCode` 48 · `ActionValidity` 3 · `SimulationStatus` 5 · `unknown_codes()` 7 | **그대로** (`test_24`) |
| 다섯 모듈의 줄 수 | **그대로** (`test_25`) |
| 새 `EventBus`/graph | **없다** (`test_26`) |

`event_pipeline.py` 는 자기 docstring 에 "**EventBus 도, 구독 · 발행 프레임워크도
만들지 않는다**" 고 적어 두었다 — 회피가 기록되어 있다.

---

## 11. 실제 발견된 문제

### R-1 — dormant carrier 가 live policy 의 한 칸을 묶어 둔다

`CHAIN_DEFINITION_UNAVAILABLE` 의 두 carrier 가 live ↔ dormant 로 갈라져 반대 축의
상태를 붙이고, 그 때문에 3-E-40 policy 의 그 칸이 `None` 이다 (§7).

- **지금 해가 있는가**: **없다.** `None` 과 `INVALID` 둘 다 `unknown_codes()` 밖이라
  분류 결과가 같다. 그리고 dormant carrier 는 실행되지 않는다.
- **왜 기록하는가**: "dormant 는 격리되어 있다" 가 **정확한 서술이 아니기** 때문이다.
  설계 시점에 이미 한 번 영향을 주었다.

### R-2 — 같은 질문에 대한 두 구현

dormant 판정기의 다섯 관문 중 **넷**이 live 세 관문과 같은 질문을 묻는다 (§5).

- **지금 해가 있는가**: **없다.** 한쪽이 돌지 않는다.
- **왜 기록하는가**: 연결하는 순간 **둘이 같은 답을 내는지**가 증명 대상이 된다.
  3-E-28 이 이미 그 정합성을 감사했으나, 그때는 live/dormant 로 갈려 있다는 사실이
  정리되지 않았다.

### O-1 (관찰) — live 경계가 "채워지지 않는 필드의 타입 주석" 하나다

1,565줄 모듈이 live 경로에 기여하는 것이 `ActivationTiming.point` 의 타입 하나이고,
production 은 그 칸을 **채우지 않는다**(늘 `None` = "모른다"). 지우자는 뜻이 아니라,
**경계가 이보다 얇아질 수 없다**는 사실을 적어 둔다.

### O-2 (관찰) — 조립 층의 존재가 앞선 Phase 들에 기록되지 않았다

3-E-33 이후 여러 Phase 가 "`TriggerSpec`/`TriggerRegistry` 생성 0곳" 을 반복해
측정했는데, 그 둘을 **쓰는** `engine/timing.py`(436줄) 와 `event_pipeline.py`(417줄)
가 목록에 없었다. 3-E-20 이 "dormant event model" 로 적었고 `event_pipeline` 이
unreachable 임을 기록했지만, **조립 층이라는 역할**로 묶이지는 않았다. 이번에
`LIVE / DORMANT-ASSEMBLY / DORMANT-PARTS` 세 층으로 정리했다.

---

## 12. 발견되지 않은 문제

**정직하게 적는다 — 찾았는데 없었던 것들이다.**

| 찾은 것 | 결과 |
| --- | --- |
| 실제 듀얼에서 trigger 가 호출되어야 하는데 안 되는 자리 | **없다.** 등록된 16개 효과에 트리거 효과가 없고, 룰북의 네 승리 조건에 트리거가 개입하지 않는다 |
| dormant 구조가 `state_hash` · RNG · 관측 경계를 건드리는 자리 | **없다** |
| AI/Search 가 trigger 를 참조하는 자리 | **없다** (문자열 수준에서도 0) |
| M3 가 production 판정을 만드는 경로 | **없다** |
| 부품 층이 live 코드를 **호출하는** 역방향 의존 | 있으나 무해 — `trigger.py` 가 `validation` · `condition` 등을 읽는 것은 아래 방향이다 |
| 41개 `ValidationCode` 와 dormant 층의 관계 | **없다** — 관계가 있는 것은 7개뿐 |
| 새 `EventBus` · graph · 중복 enum | **없다** |
| 기존 trigger 구조가 삭제된 흔적 | **없다** — 다섯 모듈의 줄 수가 그대로다 |

---

## 13. 최종 판정

**STRUCTURAL_RISK_IDENTIFIED**

까닭을 둘로 적는다.

1. **`AUDIT_ONLY_SUFFICIENT` 로 적을 수 없다.** 그 판정은 "dormant 구조가 실제로
   production consumer 가 없는 legacy/future boundary 임이 확인됨" 을 요구한다.
   런타임 consumer 는 없지만 (0회), **설계 시점 consumer 가 하나 있었다** — 3-E-40 의
   policy 가 dormant carrier 때문에 한 칸을 `None` 으로 비웠다 (R-1). 그리고 같은
   질문을 두 구현이 답하고 있다 (R-2). 둘 다 B 의 정의 그대로다 — "dormant 구조와
   production 구조 사이에 실제 의미 **중복 · 불일치**가 존재함".
2. **`PRODUCTION_BLOCKER` 는 아니다.** 그 판정은 "호출되어야 하는데 호출되지 않아
   Engine V1 의 명백한 동작 오류" 를 요구하고, **재현 시나리오를 만들 수 없었다** —
   16판 1,359행동이 전부 정상 완주하고, 등록된 효과에 트리거 효과가 없다.

**그리고 B 의 조건대로 이번 Phase 에서는 아무것도 고치지 않았다** — blocker 와
structural risk 만 기록했다.

### Full regression

```
$ python -m pytest -q -p no:randomly
4034 passed, 4 skipped in 518.33s (0:08:38)
```

| 항목 | Phase 3-E-42 종료 시 | 이번 Phase 종료 시 |
| --- | --- | --- |
| passed | 4008 | **4034** (+26, 새 파일) |
| failed | 0 | **0** |
| skipped | 4 | **4** |
| production diff | — | **0** |
| 기존 테스트 수정 | — | **0** |

### 새 테스트

`tests/test_trigger_pipeline_dormant_audit.py` — **26개**. 감사의 결론만 고정하고
동작 · 상태 · 난수 · 순위 · 관측 경계를 건드리는 테스트가 하나도 없다.

이 파일을 쓰며 고친 내 측정 오류 다섯 (production 은 멀쩡했다):

1. `Duel` 폐쇄를 66 으로 적었다 → `engine` 만 세면 **57** 이다 (앞의 수는
   `core`·`analysis`·`sources` 를 함께 센 것).
2. `judge_all` 의 호출자를 `timing.py` 로 적었다 → 그 모듈은 **부르지 않고**
   `TriggerCollector`·`TriggerChainIntegrator` 를 **만들기만** 한다.
3. dormant carrier 를 가진 코드를 넷으로 적었다 → **일곱**이다 (넷은 "같은 호출에서
   status 와 짝지은" 더 좁은 모양이었다). live 와 **어긋나는 것은 하나**다.
4. `activation_timing.py` 를 589줄로 적었다 → **541** 줄.
5. `EventBus` 를 문자열로 찾아 `event_pipeline.py` 의 **"EventBus 도 만들지 않는다"
   라는 설명**을 걸렀다 → 구문으로 세도록 고쳤고, 그 설명의 존재 자체를 테스트로
   적었다.

---

## 이번 Phase 에서 하지 않은 것

- `TriggerRegistry` 를 `duel.py` 에 **연결하지 않았다.**
- trigger pipeline 을 **새로 구현하지 않았다.**
- 기존 trigger 구조를 **하나도 삭제하지 않았다** (다섯 모듈 줄 수 불변, `test_25`).
- 새 `EventBus` 를 **만들지 않았다** (`test_26`).
- 새 graph / event architecture 를 **만들지 않았다.**
- `Chain` 구조를 **변경하지 않았다.**
- `ValidationCode` enum 을 **추가 · 변경하지 않았다** (48개 그대로, `test_24`).
- R-1 을 고치지 않았다 — `CHAIN_DEFINITION_UNAVAILABLE` 의 policy 를 `None` 에서
  `INVALID` 로 **바꾸지 않았다.**
- R-2 를 고치지 않았다 — 중복된 네 관문을 **합치지 않았다.**
- M3 의 `RULE_NOT_IMPLEMENTED` 를 **바꾸지 않았다** (3-E-38 의 결정을 유지).
- Search / AI 구조를 **변경하지 않았다.**
- Engine V1 freeze 를 **해제하지 않았다** (`engine/` diff 0).
- "앞으로 필요할 것 같다" 는 이유로 **refactor 하지 않았다.**
- `state_hash` · RNG · 관측 경계 · 순위를 건드리는 테스트를 **쓰지 않았다.**
- 기존 테스트를 **한 줄도 고치지 않았다** (삭제 0 · skip 추가 0 · assertion 약화 0).

---

## 다음 Phase 후보 (하나만)

> **Phase 3-E-44 — dormant 판정기와 live 세 관문의 답 일치 측정**
> (R-2 를 **고치지 않고** 재는 Phase)

까닭 — **연결의 첫 경계가 어디인지 이번 감사가 정했다** (§10 의 요구).

연결을 시작할 수 있는 지점은 `TriggerRegistry` 를 `duel.py` 에 꽂는 자리가
**아니다.** 그 앞에 증명되어야 하는 것이 있다.

```
① dormant 판정기의 네 관문과 live 세 관문이 **같은 입력에서 같은 답**을 내는가
      ACTIVATION_ZONE      ↔ ActionValidator
      TRIGGER_CONDITION    ↔ can_activate 의 조건
      EXECUTION_AUTHORITY  ↔ _check_authority
      COST_FEASIBILITY     ↔ definition.cost.costs
   → 다르면, 연결은 "기능 추가" 가 아니라 **판정 변경**이다.

② 다섯째 관문(EVENT_RELATION)은 live 대응이 없다 — 사건 자체가 없기 때문이다.
   그래서 **사건을 만드는 것이 먼저**이고, 그것이 event_pipeline / timing 조립 층의
   일이다.

③ R-1 은 ①·② 뒤에 저절로 정해진다 — 두 carrier 중 어느 쪽이 살아남는지가
   그때 결정되므로, 지금 policy 를 고치면 순서가 거꾸로다.
```

즉 다음에 할 일은 **연결이 아니라 ①의 측정**이다. 그것이 끝나기 전에는 `duel.py`
에 아무것도 꽂지 않는 것이 맞다.

**이번 Phase 에서 그것을 하지 않았다.** 다음 Phase 의 범위와 금지 사항은 사용자가
정한다.
