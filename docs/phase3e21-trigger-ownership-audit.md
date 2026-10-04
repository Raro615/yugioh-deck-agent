# Phase 3-E-21 — Trigger Requirement / PlayerAction Ownership Audit

## 1. HEAD / Base

| | |
|---|---|
| 지시문의 Base | `120fc65` — **이 커밋은 존재하지 않는다** (`git cat-file -t 120fc65` → `Not a valid object name`) |
| 실제 HEAD | `120fce5` — Phase 3-E-20 (`Phase 3-E-20 audit trigger duel loop connectivity`) |
| 해석 | 지시문의 해시는 `120fce5` 의 **오타**로 보인다 (`e5` ↔ `65`). 내용상 Base 는 3-E-20 이 맞다 |
| Working tree | clean · `git diff --stat` 비어 있음 |
| Branch | `claude/pensive-goodall-te1egy` |

실제 HEAD 기준으로 감사했다. 사용자 변경사항은 없었고 아무것도 덮어쓰지 않았다.

## 2. BLOCKER / Engine 변경

**BLOCKER: NO** · **Engine 변경: NO.**

production 코드를 한 줄도 바꾸지 않았다 (`git diff -- engine/ agent/ core/
analysis/ sources/` 가 0줄). 추가한 것은
`tests/test_trigger_ownership_audit.py` (13개)와 이 문서뿐이다.

## 3. 공식 규칙 근거

| 규칙 ID | 원문 핵심 | 의미 | 현재 repository 의 대응 계층 |
|---|---|---|---|
| **RULE-EFFECT-004** (Trigger Effect) | "These effects are **activated** at specific times, such as 'during the Standby Phase' or 'when this monster is destroyed'." | 유발 효과는 **발동되는** 것이다 | 발동의 입구 = `PlayerActionKind.ACTIVATE_EFFECT` → `EffectActivator.activate` |
| **RULE-EFFECT-001** (Continuous Effect) | "There is no trigger for its **activation**." | 발동이 **없는** 효과는 따로 있다 | 구조화 자료의 `has_activation: false` 로 구분된다 |
| **RULE-CHAIN-004** (Spell Speed 1) | Trigger · Flip · Ignition 은 스펠 스피드 1 — "cannot be activated in response to any other effects" | 유발은 응답 발동이 아니다 | `ActivationTimingChecker` 의 `SpellSpeed` |
| **RULE-CHAIN-010** (simultaneous) | "the turn player **builds the Chain** starting with their **mandatory** effects, **in any order**. Then the opponent … Afterwards, the turn player adds their **optional** effects in any order …" | ① 체인에 올리는 주체는 **효과의 주인** ② 묶음 순서는 규칙이 정한다 ③ **묶음 안의 순서는 그 사람이 고른다** | `engine/trigger_order.py` — 아직 비어 있고 `UNRESOLVED_ORDER_RULES` 가 그 사실을 적어 둔다 |
| **RULE-CHAIN-011** (cannot be chained to) | "You can only create a Chain by **responding to the activation** of a card or effect. Summoning … Tributing … paying costs are not effect activations" | 체인은 **발동**의 사슬이다 | `engine/action_validation.py` · `engine/duel.py` 가 이미 인용한다 |
| 구조화 `chain.simultaneous_order` | 네 묶음 순서를 그대로 보존 | SEGOC 의 골격 | 아직 구현 없음 (의도적) |
| **ADR-002** | 파괴 · 제외 · 보내기 · 되돌리기는 **효과 해결의 결과**이고 고르는 것이 아니다 | 결과를 행위로 만들지 않는다 | `PlayerActionKind` 에 그 이름들이 없다 |
| **ADR-006** | 구현은 **손으로** 등록한다. 등록되지 않은 것은 UNKNOWN | 자동 생성 금지 | `EFFECT_LIBRARY` · `TriggerRegistry` (등록 0개) |

**공식 자료의 한계도 함께 적는다** (`test_03` 이 고정): 이 룰북(v10)에는
**"missed timing"(놓친 타이밍)이 한 번도 나오지 않고**, `mandatory`/`optional`
이라는 낱말이 나오는 절은 **RULE-CHAIN-010 하나**다. 그러므로 "WHEN/IF 로
놓친 타이밍을 판정" 같은 규칙은 **지금 근거가 없다** — 만들면 지어내는 것이다.
(`rulings/` 의 공식 카드 ruling 계층은 카드별 질의응답이고, 이 질문에 쓸
일반 규칙 문장을 갖고 있지 않다.)

## 4. Trigger 구조 Audit

| 심볼 | 정의 | production caller | test caller | production 사용 | PlayerAction 연결 | Chain 연결 |
|---|---|---|---|---|---|---|
| `TriggerSpec` | `engine/trigger.py:425` | 없음 (등록 0개) | 12개 파일 | **아니다** | 없음 | 없음 |
| `TriggerCandidate` | `engine/trigger.py:590` | 없음 | 있음 | 아니다 | 없음 | 없음 (`ChainLink` 상속도 아니다) |
| `TriggerRequirement` | `engine/trigger.py:140` | 없음 | 있음 | 아니다 | — | — |
| `TriggerCollector` | `engine/trigger.py:775` | `event_pipeline.py:376` (그 모듈 자체가 unreachable) | 있음 | 아니다 | 없음 | 없음 |
| `TriggerOrdering` | `engine/trigger_order.py:191` | 없음 | 있음 | 아니다 | 없음 | 없음 |
| `TriggerChainIntegrator` | `engine/trigger_chain.py` | `timing.py:298` (unreachable) | 있음 | 아니다 | **없음** | **`ChainLink` 를 만든다** |
| `TimingPoint` | `engine/trigger.py:85` | `activation_timing.py:55` | 있음 | **타입만** | 없음 | 없음 |
| `trigger_event` / `trigger_events` | `analysis/` · `core/card_model.py` | 카드 **검색**(`has_effect_code`) | 있음 | 검색만 | 없음 | 없음 |
| `EffectActivator.can_activate` / `.activate` | `engine/activation.py:350` · `:389` | `duel.py:604` · `:901` · `response.py:572` | 있음 | **그렇다** | **`action: PlayerAction` 필수** | **`ChainLink` 를 만든다** |
| `Chain.push` | `engine/chain.py` | `activation.py:460` · `:577` | 있음 | 그렇다 | 간접 | 그렇다 |
| `ChainResolver` | `engine/chain.py` | `duel_resolver()` → `duel.py` | 있음 | 그렇다 | 간접 | 해결 |

### `TriggerChainIntegrator._entry` 에 대한 네 질문

| 질문 | 답 (`test_10` 이 AST 로 고정) |
|---|---|
| `PlayerAction` 없이 `ChainLink` 를 만드는가 | **그렇다.** 인자에 `action` 이 없다 |
| production caller 가 있는가 | 없다 (`timing.py` 만 부르고, 그 모듈을 import 하는 곳이 0개) |
| test-only 인가 | 그렇다 |
| dormant code 인가 | 그렇다 |
| 활성화되면 `legal_actions()` 를 우회하는가 | **그렇다.** 만드는 링크에 `selections` · `payments` 가 **없다** — 발동 경로가 채우는 바로 그 둘이다 |

## 5. PlayerAction Ownership — 판정

**가설 B 가 맞다.** 다만 범위를 정확히 한다.

> **"유발 효과를 체인에 올리는 사건"은 공식 용어로 발동(activation)이고,
> 이 엔진에서 발동의 입구는 이미 `PlayerAction` 하나다.
> 그러므로 임의 유발의 발동은 `PlayerAction` 이어야 한다.**

근거 네 가지:

1. **규칙** — RULE-EFFECT-004 가 유발 효과를 "activated" 라고 말한다. 지속
   효과만 `has_activation: false` 다.
2. **규칙** — RULE-CHAIN-010 이 체인을 쌓는 주체를 **효과의 주인**으로 적고,
   같은 묶음 안의 순서를 **그 사람의 임의**로 둔다. 엔진이 대신 고를 근거가 없다.
3. **코드** — production 에서 `ChainLink` 를 만드는 함수는 `PlayerAction` 을
   인자로 받는다 (`test_05`). 링크의 `actor` · `effect_ref` · `source` ·
   `selections` · `payments` 가 전부 그 행위와 그 뒤의 지불에서 나온다.
4. **코드** — `Duel.apply` 는 **허가 목록에 없는 행위를 거절한다**
   (`test_06`, Phase 3-E-13). 그러므로 "엔진 내부가 직접 발동" 을 끼워 넣으려면
   `apply` 를 우회해야 하고, 그것이 곧 두 번째 실행 경로다.

**새 `ActionKind` 는 필요하지 않다** (`test_04`):

| 필요한 표현 | 이미 있는 것 |
|---|---|
| "이 카드의 이 효과를 발동한다" | `ACTIVATE_EFFECT` + `effect_ref` |
| "발동하지 않겠다" | `PASS` — "아무것도 하지 않겠다는 **선택**" |
| "대상 · 비용을 고른다" | `targets` · `EffectActivator` 의 `selections` / `cost_selections` |
| "지금은 발동할 수 없다(모른다)" | `LegalActions.withheld` + `missing` |

## 6. Mandatory vs Optional

| | 임의 유발 (`OPTIONAL`) | 강제 유발 (`MANDATORY`) |
|---|---|---|
| 고르는 것 | **발동 여부** | 발동 여부는 **아니다** |
| 하나뿐일 때 | `ACTIVATE_EFFECT` 또는 `PASS` | **고르는 일이 아니다** — `Duel.advance()` 와 같은 자리 |
| 둘 이상일 때 | 어느 것을 먼저 올릴지 **고른다** (RULE-CHAIN-010) | **순서를 고른다** (같은 규칙, "in any order") |
| 새 추상화 필요? | **아니다** | **아니다 — 선례가 이미 있다** |

`Duel.advance()` 가 그 선례다 (`test_07`). 드로우 페이즈의 드로우는
`legal_actions` 에 **없다** — "뽑지 않겠다고 고를 수 없기 때문" 이고, 그 일은
`advance()` 가 한다. 즉 엔진에는 이미 **두 개의 정당한 경계**가 있다:

```
legal_actions() → PlayerAction → apply()     결정이 있는 일
advance()                                     결정이 없는 일 (지금은 드로우)
```

그리고 `advance()` 도 보고는 행위 모양으로 낸다 — 영수증의 `action.kind` 가
`PASS` 다. 판을 바꾼 일이 기록 없이 사라지지 않는다.

따라서 **`SystemAction` 같은 새 개념을 지금 만들 이유가 없다.** 강제 유발
하나는 `advance()` 쪽, 둘 이상의 순서와 임의 유발은 `PlayerAction` 쪽이다.

## 7. Optional Trigger Semantics — 여섯 경우

현재 architecture 기준으로 **무엇이 만들어져야 하는가** (구현이 아니라 판정).

| Case | candidate | legal action | PlayerAction | activation | ChainLink |
|---|---|---|---|---|---|
| A 조건 미발생 | 없음 | 없음 | 없음 | 없음 | 없음 |
| B 발생 → 강제 | **있다** | 하나뿐이면 **아니다** · 둘 이상이면 **순서 선택** | 하나뿐이면 아니다 (`advance()` 계열) | **그렇다** (강제도 발동이다) | 발동 경로가 만든다 |
| C 발생 → 임의 → 고를 수 있다 | 있다 | **`ACTIVATE_EFFECT` + `PASS`** | 그렇다 | 고르면 | 고르면 |
| D 임의 → 발동하지 않음 | 있다 | `PASS` | **`PASS`** | 없음 | 없음 |
| E 임의 → 발동함 | 있다 | `ACTIVATE_EFFECT` | 그렇다 | 그렇다 | **그렇다** — 그 뒤 기존 응답 창(3-E-11/12) |
| F 후보는 있으나 타이밍 · 스펠 스피드 · 발동 조건이 막는다 | **있다** | **아니다** | 없음 | 없음 | 없음 |

**Case F 가 "candidate ≠ legal action" 의 증거이고, 그 구분은 이미 구현되어
있다.** `LegalActions` 는 `allowed` 와 `withheld` 를 따로 들고, `withheld` 는
`missing`(아직 없는 규칙)을 적는다. UNKNOWN 을 후보에 넣지 않는 규율
(`Duel.legal_actions` 의 설명) 이 그대로 적용된다.

## 8. Canonical Execution Path

§8 의 네 경로를 실제 연결로 가린다.

| 경로 | 상태 |
|---|---|
| **A** `legal_actions()` → `PlayerAction` → `Duel.apply()` | **canonical** — 유일한 production 결정 경로 |
| B `TriggerCandidate` → `ChainLink` → `Chain.resolve()` | **존재하지 않는다** — 후보에서 링크로 가는 production 호출이 없다 |
| C `ActivationCandidate` → `EffectActivator` → `ChainLink` | **canonical 의 뒷부분** — 입력이 A 의 `PlayerAction` 이다 |
| D `TriggerChainIntegrator` → `ChainLink` | **dormant** (test-only). 활성화되면 A 를 우회한다 |

즉 canonical execution boundary 는 **A(+C)** 하나이고, D 는 잠들어 있다.
**두 번째 실행 경로는 "지금은" 없다.**

## 9. AI / Search 영향

**변경 없음.** 그리고 변경할 필요도 없다 — 조건이 하나 지켜지는 동안은.

| §7 의 질문 | 답 |
|---|---|
| 1. 유발이 `PlayerAction` 이면 AI 는 어떻게 보는가 | `legal_actions()` 에 `ACTIVATE_EFFECT` 로 나타난다. **지금 구조 그대로** 보인다 |
| 2. `PlayerAction` 이 아니면 탐색이 놓치는가 | **놓친다.** `Simulator.simulate` 는 후보 목록에 없는 행위를 `NOT_A_CANDIDATE` 로 돌려준다 (`test_11`) |
| 3. "탐색은 `legal_actions()` 만 본다" 와 충돌하는가 | 유발이 행위면 **충돌 없음**. 엔진 내부 발동이면 **충돌한다** |
| 4. 시뮬레이션에서 유발이 자동 실행되면 | 깊이 1 의 미래가 **아무도 고르지 않은 자리**가 된다. `agent/simulation.py` 가 이미 그 위험을 적어 두었다 — "고를 것이 있다 — 그것은 결정이므로 여기서 멈춘다" (`test_12`) |
| 5. hidden information 경계 변화 | **필요 없다.** 후보 수집은 `GameStateView` 만 보고 가려진 자리는 `unchecked` 로 남긴다 (3-E-20) |
| 6. evaluation 변경 | 필요 없다 |
| 7. ranking 변경 | 필요 없다 |

**인터페이스 요구사항으로만 기록한다**:

> 유발 발동이 `legal_actions()` 에 나타나는 한 `agent/` 는 한 줄도 바뀌지
> 않는다. 반대로 엔진이 `apply()` 안에서 유발을 자동 발동하면
> `Simulator._autoplay` 의 "PASS 뿐인 자리만 대신 밟는다" 규약이 깨지고,
> 탐색이 보지 못한 상태 전이가 깊이 1 에 섞인다.

## 10. STRUCTURAL-34 영향

**STRUCTURAL-34 unaffected.**

* 유발 소유권은 34 의 blocker 가 **아니다.** 34 는 "응답/우선권 창을 여는
  자리" 의 문제이고, 발동 직후 창은 3-E-11/3-E-12 가 이미 열었다. 남은 것은
  `AFTER_CHAIN_RULE`(체인 해결 뒤 우선권)과 페이즈 전이 우선권이다.
* 거꾸로도 아니다 — 유발을 `PlayerAction` 으로 표현하는 데 34 의 나머지가
  필요하지 않다. 임의 유발 하나를 고르는 자리는 **발동 창**이고 그것은 이미
  있다.
* 이 Phase 는 34 를 다시 열지 않았다.

## 11. Tests

신규: `tests/test_trigger_ownership_audit.py` — **13개**.

| # | 검증 |
|---|---|
| 01 | 룰북이 유발 효과를 "activated" 라고 말한다 · 지속 효과는 `has_activation: false` |
| 02 | RULE-CHAIN-010 — 주인이 체인을 쌓고 묶음 안 순서는 임의 · `cannot_chain_to` |
| 03 | 룰북에 "missed timing" 이 없고 mandatory/optional 은 한 절에만 나온다 |
| 04 | `ACTIVATE_EFFECT` + `effect_ref` 로 표현된다 · `PlayerActionKind` 집합 고정 (새 종류 0) |
| 05 | production 의 `ChainLink` 생성 함수가 `action: PlayerAction` 을 받는다 |
| 06 | `Duel.apply` 가 허가 목록 밖의 행위를 거절한다 |
| 07 | `Duel.advance()` 가 "고르지 않는 일" 의 기존 자리다 (드로우 · 영수증은 `PASS`) |
| 08 | `TriggerRequirement` 는 담기만 한다 · 기본값 `UNKNOWN` |
| 09 | `UNRESOLVED_ORDER_RULES` 가 "그 사람이 고르는 순서" 를 이미 공백으로 적어 두었다 |
| 10 | 잠든 `_entry` 는 `action` 없이 링크를 만들고 `selections`/`payments` 가 없다 |
| 11 | 탐색은 `legal_actions` 밖을 `NOT_A_CANDIDATE` 로 본다 |
| 12 | 탐색의 "PASS 뿐이면 결정이 아니다" 규약이 코드에 있다 |
| 13 | `STRUCTURAL-31` 이 이미 이 공백을 소유한다 |

고의 위반 3건 — 전부 잡혔다 (넣고 → 실패 확인 → `git checkout` 되돌림):

| | 위반 | 잡은 테스트 |
|---|---|---|
| A | 트리거용 새 `ActionKind` 를 만든다 | 04 |
| B | 잠든 `_entry` 가 `action` 을 받게 한다 | 10 |
| C | 탐색의 결정 지점 규약을 지운다 | 12 |

전체: **3593 passed · 4 skipped · 0 failed · 372s.**
Regression **0** · 신규 13 · 수정 **0** · 삭제 **0** · skip 증가 **0**.

## 12. 신규 STRUCTURAL ID

**신규 STRUCTURAL 없음.**

이 감사가 찾은 공백은 **이미 등록되어 있다** (`test_13`):

* **STRUCTURAL-31** (Phase 2-F-3-D) — "`blocked`(대상/비용 미정)를 채워 줄
  계층이 아직 없다. 트리거 효과는 그 둘이 정해지기 전까지 체인에 들어가지
  못한다." → 이번 감사가 더한 것은 **그 계층이 이미 있다**는 사실이다:
  `PlayerAction` → `EffectActivator`(대상 · 비용). 트리거가 그 자리를 쓰지 않고
  있을 뿐이다.
* **STRUCTURAL-32** — 실행 권한을 두 곳에서 확인한다.
* **STRUCTURAL-33** — `plan` 이 `base_chain` 에 묶여 있다.
* `UNRESOLVED_ORDER_RULES` 5항목 — 그중 **2항목**(묶음 순서 · 같은 묶음 안의
  임의 순서)은 이번에 **공식 근거(RULE-CHAIN-010)를 확보**했다. 구현은 하지
  않았고, 근거가 생겼다는 사실만 기록한다.

## 13. Final Decision Matrix

| 항목 | 판정 |
|---|---|
| Trigger Candidate는 존재하는가 | **예** (`TriggerCandidate`, `engine/trigger.py:590`) |
| Trigger Candidate production caller가 있는가 | **아니다** (`event_pipeline` 만, 그 모듈도 unreachable) |
| Trigger → Chain production path가 있는가 | **아니다** |
| Trigger → PlayerAction path가 있는가 | **아니다** (구조적으로 가능하지만 연결 없음) |
| OPTIONAL Trigger의 선택 지점은 존재하는가 | **표현 수단은 있다** (`ACTIVATE_EFFECT` / `PASS`) · **후보 생성은 없다** |
| Mandatory Trigger의 자동 처리 지점은 존재하는가 | **선례가 있다** (`Duel.advance()`) · 트리거용 구현은 없다 |
| PlayerAction이 canonical execution boundary인가 | **예** (결정이 있는 일) · 결정이 없는 일은 `advance()` |
| legal_actions()가 Trigger decision을 표현할 수 있는가 | **예** — 새 종류 없이 `ACTIVATE_EFFECT` + `PASS` + `withheld` |
| TriggerChainIntegrator가 production에 연결되어 있는가 | **아니다** (dormant) |
| 두 번째 실행 경로가 존재하는가 | **지금은 아니다.** 잠든 계층을 그대로 이으면 생긴다 |
| AI Search가 현재 Trigger를 놓치는가 | **놓칠 것이 없다** (후보가 0개). 엔진 내부 발동을 만들면 **놓친다** |
| Simulation이 Trigger를 자동 처리하는가 | **아니다** (PASS 뿐인 자리만 대신 밟는다) |
| STRUCTURAL-34에 영향이 있는가 | **아니다 (unaffected)** |
| Engine Change가 필요한가 | **아니다** |

## 14. Structural Decision

**B. AUDIT-ONLY / FUTURE ARCHITECTURE GAP.**

`C` 가 아닌 이유: 두 개의 canonical path 가 **충돌하고 있지 않다.** 두 번째
경로는 잠들어 있고, 지금 어떤 정상적인 게임 실행도 막지 않는다 (등록된 유발
효과 0개 — 3-E-20 §16). "아직 구현되지 않았다" 는 `C` 의 근거가 아니다.

이 Phase 가 남기는 **구조 결정** (다음에 이을 때의 계약):

1. 유발 효과를 체인에 올리는 사건은 **발동**이고, 발동의 입구는
   `PlayerAction`(`ACTIVATE_EFFECT`) 하나로 유지한다. 새 `ActionKind` 를
   만들지 않는다.
2. "발동하지 않겠다" 는 `PASS` 로 표현한다.
3. 강제 유발이 **하나**일 때는 고르는 일이 아니므로 `advance()` 쪽 경계에
   둔다. **둘 이상이면 순서가 선택이므로** 행위 공간으로 돌아온다
   (RULE-CHAIN-010).
4. `TriggerChainIntegrator` 를 **그대로** 연결하지 않는다 — `PlayerAction` ·
   `selections` · `payments` 를 건너뛰기 때문이다. 이으려면 후보를
   **행위 후보로** 번역하는 자리를 먼저 만든다.
5. `GameStateView` · `agent/` 는 그대로 둔다. 유발이 행위로 나오면 탐색은
   고칠 필요가 없다.

## 15. 다음 Phase 후보 — 정확히 하나

> **`TriggerCandidate` → `PlayerAction` 번역 지점의 **감사** (구현 아님).**
>
> 이번 Phase 가 "유발 발동은 `PlayerAction` 이다" 를 규칙과 코드로 확정했다.
> 그러면 다음 질문은 자연히 하나로 좁혀진다 — **그 번역은 누가 하는가?**
> `Duel.legal_actions` 가 후보를 묻는 자리(`_activation_actions`)에서
> 직접 묻는가, 아니면 사건이 생긴 시점에 모아 두는 자리가 필요한가?
> 이것은 `TriggerCandidate` 가 **언제** 만들어져야 하는가의 문제이고
> (사건 발생 시점 vs 후보 조회 시점), 지금 `legal_actions` 가
> **판 상태만 보고 매번 새로 계산**하는 구조와 충돌할 가능성이 있다
> ("이미 지나간 사건" 을 기억하지 않기 때문이다).
>
> 그 충돌 여부를 먼저 감사한다. 그 전에는 Trigger Engine 을 만들지 않는다.

다음 Phase 는 지시 없이 진행하지 않는다.
