# Phase 3-E-29 — TriggerCandidate → PlayerAction Translation Contract Audit

> **이번 Phase의 목적은 TriggerCandidate → PlayerAction 변환을 구현하는 것이
> 아니라, 그 변환 계약이 현재 production architecture에 실제로 필요한지
> 감사하는 것이다.**

## 1. BLOCKER

**없음.**

## 2. Engine Change

**없음.** production code 를 한 줄도 고치지 않았다. 변경 파일은 테스트 1개와
이 문서 1개뿐이다.

## 3. Actual HEAD

**프롬프트의 HEAD 와 실제 HEAD 가 다르다.**

| 출처 | 값 |
|---|---|
| 프롬프트가 적은 HEAD / Base | `734d2be` |
| **실제 HEAD** | **`ad69c9f`** |

`734d2be` 는 Phase **3-E-27** 보고서 커밋이다. 3-E-28 이 `fcd2a4a` + `ad69c9f`
를 남겼으므로, 프롬프트의 "Base: 734d2be" 와 "actual HEAD 가 3-E-28 결과임을
확인하라" 는 서로 맞지 않는다. 지시대로 reset · checkout 하지 않고 실제 깨끗한
HEAD(`ad69c9f`, `git status --short` 비어 있음)에서 감사를 진행했다.

## 4. Production Reachability

AST 로 **함수 서명과 호출**을 읽어 측정했다 (파일명·문자열 추측 아님).

| 질문 | 답 |
|---|---|
| `Duel` 이 `TriggerCollector` 를 부르는가 | **아니다** |
| `Duel` 이 `TriggerEligibilityJudge` 를 부르는가 | **아니다** |
| `Duel` 이 `TriggerChainIntegrator` 를 부르는가 | **아니다** |
| `legal_actions()` 가 `TriggerCollector` 를 부르는가 | **아니다** |
| `legal_actions()` 가 `TriggerEligibilityJudge` 를 부르는가 | **아니다** |
| `EffectActivator` 가 `TriggerCollector` 를 부르는가 | **아니다** |
| `TriggerCandidate` 를 받아 `PlayerAction` 을 돌려주는 production 함수 | **없음 (none)** |
| `TriggerCandidate` 를 받아 `ChainLink` 를 만드는 production 함수 | `engine/trigger_chain.py:441` — **단 잠들어 있다** |
| 간접 변환 자리 | **없음** |

후보/적격성을 인자로 받는 production 함수는 **15개**이고 **전부**
`engine/trigger*.py` 안이며, **어느 것도** `PlayerAction` 을 돌려주지 않는다.

`PlayerAction` 을 만드는 production 모듈은 **`engine/duel.py` 하나**다
(8곳). `agent/` 전체와 정론 경로 모듈 전부가 트리거 계층 이름을 **하나도**
쓰지 않는다.

> `engine/activation_timing.py` 는 `engine.trigger` 에서 `TimingPoint`
> **열거형 하나**만 가져오고 필드 선언 한 곳에서 쓴다. 파이프라인을 부르는
> 것이 아니므로 도달성으로 세지 않았다 (3-E-27 · 3-E-28 과 같은 기준).

## 5. TriggerCandidate Semantics

`TriggerCandidate` 가 답하는 것은 **"이 사건 때문에 무엇이 후보가 될 수
있는가"** 하나다. 모듈이 스스로 그렇게 적는다.

| 칸 | 뜻 | 성격 |
|---|---|---|
| `point` | 어떤 시점의 사건인가 | **사건/순서** |
| `effect_ref` | 어떤 효과인가 | 식별 |
| `source` | 판 위의 어느 카드인가 | 식별 |
| `controller` | 지금 그 카드를 쥔 쪽 | 식별 (3-E-28: `actor` 와 같은 값) |
| `status` | 수집 단계까지 알아낸 것 | 판정 |
| `requirement` | 강제/임의 | 규칙의 성질 |
| `wording` | WHEN/IF 문구 | 규칙의 성질 |
| `code` · `reason` · `notes` | 왜 그렇게 판정했는가 | 판정 근거 |

**없는 칸**: `card_id` · `definition` · `targets` · `selections` · `payments` ·
`owner` · `hand` · `deck`. 하나도 없다 (`test_13` 이 고정).

## 6. PlayerAction Semantics

| 칸 | 뜻 |
|---|---|
| `kind` | 11가지 중 무엇인가 |
| `actor` | **이 행위를 시도하는 쪽** (카드의 `owner`/`controller` 와 다를 수 있다, ADR §22) |
| `source` | 출처 카드 |
| `targets` | 고른 대상들 (`ActionTarget`) |
| `effect_ref` | 발동할 효과 |
| `phase` | 페이즈 변경용 |

ADR-007 이 경계를 못박는다: `GameStateView → LegalActions → AI → Action →
Engine → GameState'`. **AI 는 `Action` 객체만 돌려준다.** 즉 `PlayerAction` 은
"플레이어의 의도" 를 싣는 자리이고, 과거 사건을 싣는 자리가 아니다.

## 7. Translation Information Matrix

| 정보 | TriggerCandidate 보유 | PlayerAction 필요 | GameState에서 파생 가능 | Event/Timing context 필요 | Player choice 필요 | Cost/Target layer 필요 | 현재 production 경로 필요 | 판정 |
|---|---|---|---|---|---|---|---|---|
| card instance (`source`) | **있다** | **필요** | 그렇다 | 아니다 | 아니다 | 아니다 | 그렇다 | **대응 완료** |
| card id | 없다 | 불필요 | 그렇다 | 아니다 | 아니다 | 아니다 | 아니다 | 없어도 된다 |
| controller | **있다** | — | 그렇다 | 아니다 | 아니다 | 아니다 | — | `actor` 와 **같은 값** (3-E-28) |
| actor | (= controller) | **필요** | 그렇다 | 아니다 | 아니다 | 아니다 | 그렇다 | **대응 완료** |
| `effect_ref` | **있다** | **필요** | 등록소에서 | 아니다 | 아니다 | 아니다 | 그렇다 | **대응 완료** |
| trigger event | `point` 로 | **불필요** | 아니다 | **그렇다** | 아니다 | 아니다 | 아니다 | **Action 밖에 둔다** |
| timing point | **있다** | **불필요** | 아니다 | **그렇다** | 아니다 | 아니다 | 아니다 | **적격성·순서의 것** |
| condition result | `status`·`code` | 불필요 | 그렇다 | 아니다 | 아니다 | 아니다 | 아니다 | 판정 결과 |
| mandatory/optional | `requirement` | **불필요** | 아니다 | 아니다 | 아니다 | 아니다 | 아니다 | 규칙의 성질 |
| eligibility | `status` | 불필요 | 그렇다 | 그렇다 | 아니다 | 아니다 | 아니다 | 판정 결과 |
| **target selection** | **없다** | **필요** | **그렇다** (`target_combinations`) | 아니다 | **그렇다** | 그렇다 | **그렇다** | **빠진 유일한 칸** |
| cost payment | 없다 | 불필요 | 아니다 | 아니다 | 그렇다 | **그렇다** | 그렇다 | `ChainLink` 의 칸 |
| declaration | 없다 | 불필요 | — | 아니다 | 그렇다 | 아니다 | 아니다 | 규칙 계층 미구현 |
| chain position | 없다 | 불필요 | 아니다 | 아니다 | 아니다 | 아니다 | 그렇다 | `ChainLink.sequence` |
| activation permission | 없다 | 불필요 | 그렇다 | 아니다 | 아니다 | 아니다 | 그렇다 | `ActionValidator` 의 것 |
| event identity | `point` 뿐 | 불필요 | 아니다 | **그렇다** | 아니다 | 아니다 | 아니다 | 3-E-23 이 측정 (고유 id 없음) |
| source zone | 없다 (관측에서 읽는다) | 불필요 | **그렇다** | 아니다 | 아니다 | 아니다 | 그렇다 | 관문이 관측에서 본다 |
| current zone | 없다 (관측에서 읽는다) | 불필요 | **그렇다** | 아니다 | 아니다 | 아니다 | 그렇다 | 같음 |

### §4 의 열 가지 질문에 대한 답

1. **겹치는 칸**: `source` · `effect_ref`, 그리고 `controller` ↔ `actor` (같은 값).
2. **후보에 빠진 칸**: `targets` **하나**.
3. **일부러 넣지 않은 칸**: `selections` · `payments` · `kind` · `phase`.
4. **뒤 단계의 것**: `selections`(`ChainLink`) · `payments`(비용 지불) ·
   `sequence`(체인).
5. **판에서 파생 가능**: `targets` · `source zone` · `current zone` ·
   `activation permission`.
6. **사건에서만 오는 것**: `point` · 사건 관계 — 그리고 **Action 에 필요하지
   않다.**
7. **플레이어 선택이 필요한 것**: 대상 선택 · 발동 여부 · 비용 선택.
8. **대상 선택**: production 은 `target_combinations(state, seat, definition,
   source)` 로 **판에서** 센다 — 후보가 아니라 판이 입력이다.
9. **비용 지불**: `CostPayer` 가 판을 바꾸며 만든다. 관측만 읽는 트리거 계층이
   할 수 없는 일이다.
10. **`ChainLink` 의 것**: `sequence` · `selections` · `payments`.

### 결정적 관찰 — 빈칸이 아니라 **다른 설계**다

production 은 이미 `ACTIVATE_EFFECT` 를 만든다. 입력이 다르다.

```
Duel._activation_actions:
    _activation_sources(seat)          판 (패 + 마법/함정 존)
    activatable_effects(card.card_id)  효과 등록소 (executable 만, ADR-006)
    target_combinations(...)           대상 조합마다 **다른 후보**
    PlayerAction.activate_effect(actor=seat, source=..., effect_ref=..., targets=...)
    selections_for(definition, candidate)
    _activation_gate(...)              세 관문
```

사건도 후보도 입력이 아니다. 즉 **"트리거를 Action 으로 바꾸는 자리" 가 비어
있는 것이 아니라, Action 을 만드는 자리가 사건을 보지 않는다.** 이것이 이
Phase 의 가장 중요한 발견이다 — 필요한 것은 "변환기" 가 아니라 "발동 열거가
사건을 입력으로 받을 것인가" 라는 설계 결정이다.

## 8. Mandatory vs Optional

| 질문 | 답 | 근거 |
|---|---|---|
| 임의 후보를 `ACTIVATE_EFFECT` 로 표현할 수 있는가 | **그렇다** | 식별 칸 셋이 이미 대응된다 |
| 강제 후보도 `ACTIVATE_EFFECT` 여야 하는가 | **아니다** | 강제는 흐름 계층의 것이다 |
| 여러 강제 트리거의 순서를 `PlayerAction` 으로 표현하는가 | **아니다** | `TriggerOrderer` 의 것 (SEGOC) |
| 임의 트리거 중 선택을 `PlayerAction` 으로 표현하는가 | **그렇다** | `ACTIVATE_EFFECT` + `PASS` |
| `withheld`/`missing` 가 필요한 상태를 덮는가 | **그렇다** | 아래 |

저장소가 강제/임의 경계를 **이미 선언**한다. `legal_actions` 의 드로우 처리:

> 드로우는 **선택이 아니라 규칙**이므로 행위 목록에 넣지 않고 `advance` 가
> 수행한다.

그리고 `WithheldAction` 의 칸은 `kind` · `reason` · `missing` **셋뿐**이다 —
`PlayerAction` 을 들고 있지 않다. 그래서 `UNKNOWN` 이 **구조적으로** 후보가 될
수 없다 (`test_14` 가 고정).

강제/임의 구분은 `TriggerRequirement` 가 들고 있고, 같은 후보로 만든
`PlayerAction` 에는 그 칸이 **없다** — 있어야 할 이유도 없다. Action 은
플레이어의 의도이고, 강제인지는 규칙의 성질이다 (`test_11`).

→ **`SystemAction` 을 만들 근거가 없다.** 대칭을 위해 강제를
`PlayerAction` 에 밀어 넣지 않는다.

## 9. ActionKind Audit

**새 ActionKind 불필요.**

측정값 11개 (`NORMAL_SUMMON` · `SPECIAL_SUMMON` · `SET_MONSTER` ·
`SET_SPELL_TRAP` · `ACTIVATE_CARD` · `ACTIVATE_EFFECT` · `CHANGE_POSITION` ·
`ATTACK` · `CHANGE_PHASE` · `END_PHASE` · `PASS`).

§7 의 네 조건을 따진 결과:

| 조건 | 충족 |
|---|---|
| 기존 종류로 표현할 수 없는 production semantics 가 있는가 | **아니다** — `ACTIVATE_EFFECT` 로 표현된다 |
| 기존 종류가 의미상 틀렸는가 | **아니다** |
| ADR 이 다른 경계를 정해 두지 않았는가 | **정해 두었다** — ADR-007 (Action = AI 의 출력) |
| 정론 경로에 영향을 주는 빈칸인가 | **아니다** — 잠든 계층의 일이다 |

하나도 충족하지 않는다.

## 10. Event/Timing Requirements

`point`(및 사건 문맥) 가 필요한 곳을 §10 의 네 갈래로 나눴다.

| 쓰임 | 필요한가 | 근거 |
|---|---|---|
| A. **Action 생성** | **아니다** | `PlayerAction` 에 사건 칸이 없고, 없는 것이 맞다 |
| B. **트리거 적격성** | **그렇다** | `_event_relation` 이 `spec.matches(event)` 를 본다 |
| C. **순서** | **그렇다** | `TriggerOrderer` 가 `event: TimingEvent` 를 들고 다닌다 |
| D. **효과 해결** | 아니다 (지금) | 해결은 `ResolutionContext` 를 쓴다 |

→ **사건 문맥은 `PlayerAction` 밖에 둔다.** B·C 의 것이고, Action 은 지금의
의도다. `test_12` 가 양쪽을 고정한다 (Action 에 사건 칸 없음 + 적격성이 사건을
반드시 봄).

## 11. Hidden Information

**누출 없음. `GameStateView` 변경 없음.**

| 점검 | 결과 |
|---|---|
| 상대 뒷면 카드 정체 | 후보에 `card_id`·`definition` **칸 자체가 없다** |
| 상대 패 | 칸 없음. 못 본 곳은 `unchecked` 에 **"어디를"** 만 남는다 |
| 상대 덱 | 같음 |
| 사건의 비공개 세부 | 후보는 `point` 만 싣는다 |
| 공개되지 않은 효과 정의 | 후보는 정의를 담지 않는다 (ADR-006 조회로만) |
| 숨은 대상 | 후보에 `targets` 가 없다 |
| 비공개 RNG 상태 | 트리거 계층은 RNG 를 만지지 않는다 |

실측: 상대의 뒷면 세트 카드는 **후보에 나타나지 않는다** (관측에 정체가 없다).
`unchecked` 는 `'P1 HAND 2장'` 처럼 **장수와 자리**만 적고 카드 id 를 적지
않는다.

→ **가상의 변환기도 `GameStateView` 를 넓힐 필요가 없다.** `targets` 는
production 이 이미 **행위자 자신의 관측**으로 센다 (ADR-007 · `looked_at`).

## 12. Canonical Path

```
legal_actions()                  ← Duel 이 판 + 등록소에서 열거한다
  → PlayerAction                 ← production 에서 만드는 모듈은 duel.py 하나
  → Duel.apply()
  → EffectActivator.activate(state, chain, action, selections, cost_selections, authorization)
  → ChainLink(sequence, actor=action.actor, effect_ref=action.effect_ref,
              source=action.source, selections=..., payments=payment.payments)
```

이 경로는 **그대로다.** `test_14` 가 동작으로 확인한다 (같은 판에서 두 번
물어 같은 답, 후보 전부 `PlayerAction`, 보류는 Action 을 들고 있지 않음).

## 13. Trigger Path

§5 의 A~E 중 **어느 하나가 아니라 두 모듈이 서로 다른 답을 적고 있다.** 이것이
이번 Phase 의 감사 소견이다.

| 모듈 | 선언한 파이프라인 | Action 의 자리 |
|---|---|---|
| `engine/trigger.py` | `TimingEvent → TriggerCollection → ` **`Action → CostPayment → ChainLink`** | **거쳐야 한다** ("실제 발동은 Action · 비용 · `ChainLink` 를 거쳐야 한다") |
| `engine/trigger_chain.py` | `TriggerEligibility → TriggerChainPlan → ` **`ChainLink`** | **언급 없음** (그림에 Action 이 없다) |
| `engine/timing.py` | `TriggerChainIntegrator` — "그 후보를 **체인에 넣을 준비가 되었는가**" | 언급 없음 |

### 말뿐이 아니다 — 실행으로 확인했다

대상도 비용도 없는 효과는 `TriggerChainIntegrator` 에서 `INSERTABLE` 이 되고,
`extend()` 가 실제로 체인에 넣는다. **`PlayerAction` 도 `EffectActivator` 도
거치지 않는다.**

```
ChainLink(sequence=0, actor=0, effect_ref=1000:e[0], source=#0,
          selections=(), payments=())
extend() → len=1
```

후보의 세 값이 그대로 링크의 세 칸이 된다. 빈 `selections`/`payments` 는
**거짓이 아니다** — 그 효과에 필요 없는 값이다. 그리고 대상이 필요한 효과는
거부된다 (`too_few_selected`, `notes=('대상 선택 (@primary)',)`, "가짜로 채워
넣지 않습니다").

### 그래도 production 결함이 아닌 이유

`_check_authority` 가 링크를 만들기 **직전에** ADR-004(출처 금지)와
ADR-006(구현 등록)을 다시 본다. 그리고 §4 가 보인 대로 이 경로는 production
에서 닿지 않는다. 다만 이 경로는 `ActionValidator` 의 요구(`ControllerIs` 등)와
`ActivationTimingChecker` 를 **거치지 않는다** — 이을 때 반드시 정해야 하는
자리다.

→ 고치지 않고 **지금 동작을 테스트로 고정**했다 (`test_07` · `test_08` ·
`test_09`).

## 14. AI/Search Impact

| 항목 | 변화 |
|---|---|
| `GameStateView` | **없음** |
| legal action 생성 | **없음** |
| candidate generation | **없음** |
| Search ranking (`agent/search.py` · `SearchPolicy`) | **없음** |
| simulation (`agent/simulation.py`) | **없음** |
| RNG 격리 | **없음** |
| hidden information | **없음** |

가정이 아니라 측정이다: `agent/` 의 어떤 모듈도 트리거 계층 이름을 쓰지 않고
(`test_03`), 이 Phase 의 변경 파일은 테스트 1개 + 문서 1개다.

## 15. Tests

`tests/test_trigger_to_action_contract.py` — **15개 신규. 기존 테스트 수정 0.**

| # | 보는 것 |
|---|---|
| 01 | 후보를 받아 `PlayerAction` 을 돌려주는 production 함수가 **없다** (AST 서명) |
| 02 | `PlayerAction` 을 만드는 production 모듈은 `duel.py` **하나** |
| 03 | 정론 경로와 `agent/` 가 트리거 계층 이름을 하나도 쓰지 않는다 |
| 04 | 후보가 식별 칸 **셋을 이미** 들고 있다 (빠진 것은 `targets` 하나) |
| 05 | 후보에 없는 칸이 **다른 계층의 것**임을 칸 집합으로 확인 |
| 06 | production 은 `targets` 를 **판에서** 센다 (사건·후보가 입력이 아니다) |
| 07 | **두 모듈이 서로 다른 파이프라인을 선언한다** (감사 소견) |
| 08 | 대상·비용 없는 효과가 `PlayerAction` 없이 `ChainLink` 에 닿는다 (감사 소견) |
| 09 | 대상이 필요한 효과는 **거부**되고 빈칸을 채우지 않는다 |
| 10 | 기존 11개 `ActionKind` 로 임의 선택이 덮인다 / 강제는 `advance` 의 것 |
| 11 | 강제/임의는 `TriggerRequirement` 의 것이고 Action 에 없다 |
| 12 | 사건 문맥은 적격성·순서의 것이고 Action 에 칸이 없다 |
| 13 | 후보에 숨은 정보 칸이 없고 `unchecked` 가 정체를 적지 않는다 |
| 14 | 정론 `legal_actions` 경로가 동작으로 그대로다 (보류는 Action 을 들지 않음) |
| 15 | `ChainLink` 생성 자리가 셋 그대로 — **두 번째 실행 경로가 생기지 않았다** |

### 회귀

| 항목 | 값 |
|---|---|
| 3-E-28 기준선 | 3686 passed · 4 skipped · 0 failed |
| 이번 | **3701 passed · 4 skipped · 0 failed** (398s) |
| 차 | +15 = 신규 그대로. 잃은 테스트 0 · 새 skip 0 · **regression 0** |

### 고의 위반 검증 — 11개 전부 잡혔다

production 을 고치지 않았으므로 테스트의 값은 **계약을 고정하는 힘**에만 있다.
그래서 계약을 하나씩 깨뜨려 봤다.

| 주입 | 깨뜨린 계약 | 잡혔는가 |
|---|---|---|
| A | production 에 `candidate → PlayerAction` 함수를 심는다 | 2개 실패 ✅ |
| B | `duel.py` 밖에서 `PlayerAction` 을 만든다 | 1개 실패 ✅ |
| C | 새 `ActionKind`(`SYSTEM_TRIGGER`) 를 추가한다 | 1개 실패 ✅ |
| D | 후보에 `targets` 칸을 넣는다 | 2개 실패 ✅ |
| E | 후보에 `card_id` 칸을 넣는다 (숨은 정보) | 1개 실패 ✅ |
| F | `PlayerAction` 에 사건 칸을 넣는다 | 2개 실패 ✅ |
| G | `_missing_execution_inputs` 가 빈칸을 묵인한다 | 1개 실패 ✅ |
| H | 네 번째 `ChainLink` 생성 자리를 만든다 | 1개 실패 ✅ |
| I | 발동 열거가 사건을 입력으로 받는다 | 3개 실패 ✅ |
| J | `trigger.py` 선언에서 `Action` 을 지운다 | 1개 실패 ✅ |
| K | `trigger_chain` 이 링크를 못 만들게 한다 | 1개 실패 ✅ |

J·K 가 특히 중요하다 — 감사 소견(§13)을 고정하는 두 테스트가 실제로 물린다는
확인이다.

## 16. Structural Status

**신규 STRUCTURAL ID 없음.**

기존 TODO 전부 유지 · 영향 없음 (`STRUCTURAL-31 / -32 / -33 / -34 / -119 /
-120 / -124 / -128 / -131 / -133 / -134`).

§13 의 기준("staged design 을 막거나 무효로 만드는 실제 아키텍처 결함")으로
§13 의 감사 소견을 따졌다.

| 조건 | 충족 |
|---|---|
| 실제 아키텍처 결함인가 | **부분적** — 두 모듈의 선언이 어긋난다 |
| staged design 을 **막는가** | **아니다** — 둘 다 잠들어 있고 production 은 제 길로 돈다 |
| staged design 을 **무효로 만드는가** | **아니다** — 이을 때 정하면 된다 |
| "미래에 변환기가 필요할 수도" 라는 이유뿐인가 | 아니다 (지금 존재하는 불일치다) |

막지도 무효로 만들지도 않으므로 **감사 소견으로만 기록**한다.

### 감사 소견 (ID 없음)

1. **두 모듈이 Action 의 자리를 다르게 선언한다.** `engine/trigger.py` 는
   "Action 을 거쳐야 한다", `engine/trigger_chain.py` 는 후보 → `ChainLink`
   직행. 이을 때 **한쪽을 고쳐야 한다.**
2. **`trigger_chain` 의 링크 생성은 `ActionValidator` 와
   `ActivationTimingChecker` 를 거치지 않는다.** ADR-004 · ADR-006 은
   `_check_authority` 가 다시 보지만 나머지 요구는 보지 않는다.
3. **`Duel._activation_actions` 가 사건을 입력으로 받지 않는다.** 트리거를
   정론 경로에 이으려면 "변환기를 만든다" 가 아니라 "발동 열거가 사건을
   입력으로 받는다" 가 더 작은 변경일 수 있다 — 다음 Phase 가 정할 일이다.

## 17. Final Decision

**AUDIT-ONLY / FUTURE ARCHITECTURE GAP**

§17 의 규칙에 그대로 걸린다.

- 정론 `legal_actions() → PlayerAction` 이 현재 production 에 **충분하다**
  → AUDIT-ONLY.
- `TriggerCandidate` 가 잠들어 있고 production 소비자가 **없다**
  → 변환기를 만들지 않는다.
- 임의 트리거가 `ACTIVATE_EFFECT` 로 **이미 표현된다** → ActionKind 추가 없음.
- 강제 트리거는 자동 진행의 것이다 → 대칭을 위해 `PlayerAction` 에 밀어 넣지
  않는다.
- 사건 문맥은 적격성에 필요하고 의도 표현에는 불필요하다 → Action 밖에 둔다.
- 대상·비용·선택은 뒤 계층의 것이다 → 후보나 Action 에 복제하지 않는다.
- 숨은 정보가 필요하지 않다 → `GameState` 를 열지 않는다.
- production 결함이 **없다** → **production diff 0.**

## 18. Future Phase Candidate

### 발동 열거의 사건 입력 계약 감사 (Activation Enumeration Event-Input Contract Audit)

- 측정된 사실: `Duel._activation_actions` 는 판과 등록소만 보고 사건을 보지
  않는다. 반면 트리거 적격성은 사건 관계(`_event_relation`)가 **핵심**이다.
  그래서 두 계층을 잇는 가장 작은 변경이 "후보 → Action 변환기" 가 아니라
  "발동 열거가 사건을 **선택적 입력**으로 받는가" 일 수 있다.
- 볼 것: (a) `_activation_actions` 에 사건이 들어오면 지금 세 관문
  (`ActionValidator` · 체인 비었는지 · `can_activate`) 중 무엇이 달라지는가.
  (b) 사건 없이 열거하는 지금 동작이 **규칙상 틀린** 후보를 내고 있는가, 아니면
  단지 트리거를 **못 내고 있는** 것인가 — 전자면 production 결함이고 후자면
  미구현이다. 이 구분이 다음 Phase 의 핵심 질문이다. (c) `legal_actions` 의
  서명을 바꾸지 않고 할 수 있는가.
- 왜 지금이 아닌가: 이번 Phase 는 "변환 계약이 필요한가" 라는 닫힌 질문이었고
  답은 "지금은 아니다" 였다. (b) 는 production 정확성 질문이므로 별도 감사가
  필요하다.
- 왜 다음인가: 이 Phase 가 "변환기가 없는 것이 빈칸이 아니라 다른 설계" 임을
  밝혔으므로, 남은 질문은 **그 다른 설계가 규칙상 옳은가**다.

**이 Phase 는 여기서 멈춘다. 다음 Phase 는 임의로 진행하지 않는다.**
