# Phase 3-E-30 — Activation Action Event-Input Contract Audit

> **이번 Phase는 activation_actions()가 사건 없이 후보를 생성하는 것이
> 정상적인 상태 기반 활성화 설계인지, 아니면 사건 기반 트리거와 잘못 결합되어
> 있는지를 감사한다. Trigger 시스템의 구현이나 production 연결은 수행하지
> 않는다.**

## 1. BLOCKER

**없음.**

## 2. Actual HEAD

프롬프트의 기대와 **일치한다.**

| 항목 | 값 |
|---|---|
| `git rev-parse HEAD` | **`a0316c4`** (Phase 3-E-29 보고서) |
| `HEAD^` | `1140d3f` (Phase 3-E-29 감사) |
| `git status --short` | 비어 있음 (깨끗) |
| 브랜치 | `claude/pensive-goodall-te1egy` |

불일치 없음. 실제 깨끗한 HEAD 에서 진행했다.

## 3. Engine Change

**없음.** production code 를 한 줄도 고치지 않았다. 변경 파일은 테스트 1개와
이 문서 1개뿐이다. **production diff = 0.**

## 4. `activation_actions()` Contract

### 먼저 이름을 바로잡는다

**production 에 `activation_actions()` 라는 공개 함수는 없다.**

| 이름 | 어디에 | 성격 |
|---|---|---|
| `Duel._activation_actions` | `engine/duel.py:426` | **production** (private) |
| `Duel._activation_sources` | `engine/duel.py:527` | production (private) |
| `Duel._activation_gate` | `engine/duel.py:551` | production (private) |
| `activatable_effects` | `engine/spell_activation.py:425` | production (public) |
| `activation_actions` | `tests/test_trigger_connectivity_audit.py:121` | **테스트 도우미** |

감사 대상을 잘못 잡으면 결론도 틀리므로 먼저 적어 둔다.

### `_activation_actions` 가 **읽는 것** (AST 측정, docstring 아님)

| 읽는 것 | 값 |
|---|---|
| attribute | `self.state` · `card.card_id` · `card.instance_id` · `definition.cost` · `definition.cost.costs` |
| 호출 | `self._activation_sources` · `activatable_effects` · `definition_for` · `target_combinations` · `selections_for` · `self._activation_gate` · `PlayerAction.activate_effect` |

### `_activation_actions` 가 **읽지 않는 것**

| 항목 | 읽는가 |
|---|---|
| `Event` · `TimingEvent` · `TimingPoint` | **아니다** |
| `TriggerCandidate` · `TriggerSpec` · `TriggerCollector` | **아니다** |
| journal · `JournalEvent` · `StateDelta` | **아니다** |
| chain · priority | **아니다** (관문이 본다 — 아래) |
| phase · turn player | **아니다** (관측과 검증기가 본다) |
| RNG | **아니다** |
| 상대의 가려진 정보 | **아니다** |
| `GameState` 변경 | **아니다** |

### 열거와 판정이 나뉘어 있다

| 함수 | 읽는 것 | 성격 |
|---|---|---|
| `_activation_sources` | `self.state.player(seat).hand` + `Zone.SZONE` | **자리 열거** (자기 좌석만) |
| `_activation_actions` | 판 + 등록소 + 대상 조합 | **후보 만들기** |
| `_activation_gate` | `self.chain` · `self.priority` · `ActivationTimingChecker` · `validator.validate` · `can_activate` | **판정** |

타이밍 · 우선권 · 체인을 열거가 보지 않는 것은 **빠뜨린 것이 아니라** 관문이
보기 때문이다. `_activation_sources` 의 docstring 이 그 설계를 적는다:

> **여기서 거르지 않는다.** 뒷면인지 · 마법인지 · 속공인지 · 함정인지는 전부
> 규칙이고, 그 판정은 `_activation_gate` 의 몫이다. 여기서 미리 걸러 두면
> 규칙이 두 곳에 적히고 둘이 갈라진다.

## 5. State-Based Activation Semantics

`_activation_actions` 가 답하는 질문은 **"지금 이 판에서 이 플레이어가 무엇을
발동할 수 있는가"** 다. 과거 사건을 묻지 않는다.

```
_activation_sources(seat)            자기 패 + 자기 마법/함정 존
  → activatable_effects(card_id)     EFFECT_LIBRARY 에서 executable 만 (ADR-006)
  → target_combinations(...)         대상 조합마다 **다른 후보**
  → PlayerAction.activate_effect(actor=seat, source=..., effect_ref=..., targets=...)
  → selections_for(definition, candidate)
  → _activation_gate(...)            관문 셋
```

실측으로 확인한 상태 의존성:

| 판 | 통상 마법(패) 후보 | 근거 |
|---|---|---|
| 대상 없음 | `ACTIVATE_EFFECT` ×1 | 대상이 필요 없는 효과 |
| 속공 마법(패), 대상 없음 | **0** | `target_combinations` 가 조합을 못 만든다 |
| 속공 마법(패), 상대 앞면 마법 1장 | `ACTIVATE_EFFECT` ×1 (`targets=['#13']`) | **판**이 정한다 |

→ 후보의 유무가 **사건이 아니라 판**에 달려 있다. 사건 입력이 없어도 답이
흔들리지 않는다.

## 6. Event-Dependent Trigger Semantics

사건 의존 효과는 **범위 밖**으로 선언되어 있고, 그 사실이 코드에 이름으로
적혀 있다.

`_NormalSpellActivation` (`engine/action_validation.py:1406`):

> `TRUE` 는 **통상 마법 하나**다. 그 밖의 모든 카드는 `UNKNOWN` 이고,
> `FALSE` 는 **하나도 없다** — 실제 규칙에서는 전부 발동할 수 있고, 없는
> 것은 그 타이밍을 볼 규칙 계층뿐이다.
>
> **`FALSE` 로 적지 않는 것이 이 조건의 핵심이다.** `FALSE` 는 "규칙이
> 금지한다" 이고 … 전부 "규칙은 허락하는데 우리가 모른다" 다.

그리고 **빠진 규칙의 이름이 사건을 가리킨다**:

```python
TRAP_TRIGGER_MISSING = (
    "trap-activation-timing (함정의 유발 조건을 효과마다 구분할 수 없다 — "
    "공식 스크립트의 SetCode(EVENT_*) 가 EffectDefinition 에 없다)"
)
```

즉 저장소가 **스스로** "사건 구분이 없다" 고 적어 두었고, 그래서 사건 의존
효과는 `UNKNOWN` 으로 남는다. `UNKNOWN` 은 허가가 아니므로 후보가 되지 않는다.

몬스터는 **다른 이유**로 빠져 있다 (Phase 3-E-16 이 나눴다):

```python
MONSTER_ACTIVATION_MISSING  # 기동 · 유발 · 플립 · 유발즉시 분류가 없어
                            # 스펠 스피드조차 정할 수 없다
```

## 7. Effect Type Audit

### 등록된 실행 가능한 효과 13개의 범주 (공식 DB `type_mask`)

| 범주 | 수 | 카드 (공식 DB 이름 — 수동 번역 없음) |
|---|---|---|
| `SPELL` (통상 마법) | **6** | 욕망의 항아리 · 은혜의 단비 · 치료의 신 다이안 켓 · 갑부 고블린 · 어리석은 매장 · 무정한 말살 |
| `SPELL+QUICKPLAY` (속공 마법) | **3** | 싸이크론 · 육신보살 · 리로드 |
| `TRAP` (함정) | **4** | 욕망의 선물 · 벌금 · 강제 탈출 장치 · 의적의 입문서 |

**유발 효과(몬스터의 trigger effect)는 하나도 없다.** 등록되지 않은 3개
(블랙홀 · 죽은 자의 소생 · 로스트)도 `executable=False` 다.

### 각 범주의 현재 상태

| # | 범주 | 후보가 되는가 | 상태 기반인가 | 사건 필요 | 지금 어디서 막히는가 |
|---|---|---|---|---|---|
| 1 | 통상 마법 (패) | **그렇다** | **그렇다** | 아니다 | 막히지 않는다 |
| 2 | 통상 마법 (세트) | 그렇다 | 그렇다 | 아니다 | `_is_set_spell` 이 범위 안에 둔다 (3-E-14) |
| 3 | 속공 마법 (패) | **그렇다** (대상이 있을 때) | **그렇다** | 아니다 | 막히지 않는다 |
| 4 | 속공 마법 (세트) | 그렇다 | 그렇다 | 아니다 | 세트한 턴은 `set_this_turn` 이 본다 (3-E-15) |
| 5 | 함정 (세트) | **아니다** | — | **그렇다** | `TRAP_TRIGGER_MISSING` (UNKNOWN) |
| 6 | 함정 (패) | **아니다** | — | — | 같음 — 그리고 애초에 발동 자리가 아니다 |
| 7 | 기동 효과 (몬스터) | 아니다 | 그렇다 (개념상) | 아니다 | `MONSTER_ACTIVATION_MISSING` (UNKNOWN) |
| 8 | 유발즉시 효과 | 아니다 | — | 그렇다 | 같음 |
| 9 | 유발 효과 (필수/임의) | 아니다 | — | **그렇다** | 같음 + 트리거 파이프라인 (잠듦) |
| 10 | 지속 · 장착 · 필드 | 아니다 | — | 아니다 | `_OUT_OF_SCOPE_TYPES` (UNKNOWN) |
| 11 | 카운터 함정 | 아니다 | — | 그렇다 | `_OUT_OF_SCOPE_TYPES` + `TRAP` |

**§10 의 분류**: 1~4 는 `STATE_BASED_ACTIVATION`, 5·8·9·11 은
`EVENT_DEPENDENT_TRIGGER`, 10 은 `CONTINUOUS/PASSIVE`, 7 은 상태 기반이지만
효과 분류 어휘가 없어 지금은 `UNKNOWN`.

### 실측 — 함정은 어떤 자리에서도 일반 발동 후보가 되지 않는다

| 판 | 그 카드를 출처로 하는 후보 종류 | `ACTIVATE_EFFECT` 수 |
|---|---|---|
| 통상 마법 (패) | `{SET_SPELL_TRAP: 1, ACTIVATE_EFFECT: 1}` | **1** |
| 속공 마법 (패), 대상 없음 | `{SET_SPELL_TRAP: 1}` | **0** |
| 속공 마법 (세트) | 없음 | **0** |
| **함정 (세트)** | 없음 | **0** |
| **함정 (패)** | `{SET_SPELL_TRAP: 1}` | **0** |

> 처음 측정에서 "함정(패) → 후보 있음" 으로 보였는데, 그것은
> **`SET_SPELL_TRAP`** 이었다. `ActionKind` 로 나눠 보니 `ACTIVATE_EFFECT` 는
> **0** 이다. 종류를 묶어 세면 틀린 결론이 나온다.

## 8. Timing / Priority Audit

| 항목 | 누가 보는가 | 일반 발동에 필요 | 트리거에만 필요 |
|---|---|---|---|
| 현재 페이즈 | `ActionValidator` (관측) | 그렇다 | — |
| 턴 플레이어 | `_activate_effect` 의 요구 | 그렇다 (통상 마법) | — |
| 우선권 | `legal_actions` + `_activation_gate` | 그렇다 | 그렇다 |
| 스펠 스피드 | `ActivationTimingChecker` | 그렇다 | 그렇다 |
| 체인 상태 | `_activation_gate` (`self.chain`) | 그렇다 | 그렇다 |
| 세트한 턴 | `ActivationTiming.set_this_turn` | 그렇다 (속공 · 함정) | — |
| 카드 자리 · 앞/뒷면 | `_activation_out_of_scope` · `_is_set_spell` | 그렇다 | — |
| controller | `ControllerIs(CONTROLLER, source)` | 그렇다 | 그렇다 |
| **사건 시점 (`point`)** | **아무도** | **아니다** | **그렇다** |

### 감사 소견 — `ActivationTiming.point` 는 선언되어 있고 비어 있다

```python
point: TimingPoint | None = None
"""지금이 어떤 시점인가. ``None`` 은 **"모른다"** 이지 "시점이 없다" 가 아니다."""
```

측정 결과:

| 질문 | 답 |
|---|---|
| `ActivationTimingChecker.check` 가 `point` 를 읽는가 | **아니다** |
| `point` 를 읽는 자리는 | `canonical_state()` · `to_dict()` — **직렬화뿐** |
| production 호출자가 `point` 를 넘기는가 | **아니다** (`duel.py:595` · `response.py:504` 둘 다 생략) |

→ **사건을 받을 자리는 이미 선언되어 있고 비어 있다.** 지금은 아무도 읽지
않으므로 해가 없고, 트리거를 이을 때 **먼저 볼 자리**다. `test_04` 가 현재
상태를 고정한다.

## 9. Production Call Graph

### 실제 경로 (측정)

```
Duel.legal_actions(seat)                       engine/duel.py:314
  │  (우선권이 열려 있고 이 자리가 쥐었거나, 턴 플레이어이고 창이 닫혔을 때)
  └→ Duel._activation_actions(seat, validator) engine/duel.py:426
       ├→ Duel._activation_sources(seat)       engine/duel.py:527   판 (자기 패 + SZONE)
       ├→ activatable_effects(card.card_id)    engine/spell_activation.py:425  등록소
       ├→ definitions.definition_for(ref)
       ├→ target_combinations(state, seat, definition, source)  engine/target_bridge.py:171
       ├→ PlayerAction.activate_effect(...)    ← **후보가 여기서 태어난다**
       ├→ selections_for(definition, candidate)
       └→ Duel._activation_gate(...)           engine/duel.py:551
            ├→ validator.validate(action)
            ├→ ActivationTimingChecker(view).check(ActivationTiming(chain, priority, set_this_turn=...), action)
            └→ EffectActivator.can_activate(state, chain, action, selections, authorization)

Duel.apply(action)  →  EffectActivator.activate(...)  →  ChainLink
```

### 트리거 경로 (측정)

```
TimingEvent → TriggerCollector → TriggerCandidate → TriggerEligibilityJudge
            → TriggerOrderer → TriggerChainIntegrator → ChainLink
```

### 두 경로가 production 에서 교차하는가

**교차하지 않는다.** `_activation_actions` · `_activation_sources` ·
`_activation_gate` · `legal_actions` 네 함수 중 어느 것도 트리거 계층의 이름을
하나도 쓰지 않는다 (AST 측정, `test_13`).

## 10. Trigger Pipeline Reachability

§7 의 A~D 중 **A. No trigger dependency at all.**

`engine/duel.py` 의 import 전이 폐쇄를 HEAD 에서 다시 쟀다.

| 모듈 | 정론 경로 도달 |
|---|---|
| `engine/trigger.py` | 그렇다 — **`TimingPoint` 열거형 하나** 때문 (`ActivationTiming.point` 의 타입) |
| `engine/trigger_chain.py` | **아니다** |
| `engine/trigger_order.py` | **아니다** |
| `engine/timing.py` | **아니다** |
| `engine/event_pipeline.py` | **아니다** |

`TimingPoint` 가 닿는 유일한 이유가 **쓰이지 않는 `point` 칸의 타입**이라는
것이 §8 의 소견과 맞물린다. 파이프라인을 **만드는** 모듈은 하나도 닿지 않는다.

## 11. PlayerAction Contract

`PlayerAction.activate_effect` 가 실제로 요구하는 최소 입력:

| 칸 | 필요 | 어디서 오는가 |
|---|---|---|
| `kind` | 고정 `ACTIVATE_EFFECT` | 생성자가 정한다 |
| `actor` | **필요** | `seat` (= `card.controller`, 3-E-28 이 동일 값임을 증명) |
| `source` | **필요** | `card.instance_id` |
| `effect_ref` | **필요** | `activatable_effects` |
| `targets` | 효과가 요구하면 | `target_combinations` — **판에서 센다** |
| `phase` | 불필요 | 페이즈 변경 전용 |

| 질문 | 답 |
|---|---|
| 상태 기반 발동 후보를 기존 `PlayerAction` 으로 **온전히** 표현할 수 있는가 | **그렇다** — 지금 그렇게 하고 있다 |
| 사건 유발 후보를 기존 `PlayerAction` 으로 표현할 수 있는가 | **식별 칸은 그렇다** (3-E-29: `actor`·`source`·`effect_ref` 대응 완료). **단 "어떤 사건에 응답하는가" 는 표현할 수 없다** — Action 에 사건 칸이 없고, 없는 것이 맞다 (ADR-007: Action 은 AI 의 출력, 과거 사건이 아니다) |

차이가 나는 이유: 사건 정보는 **적법성과 순서**의 것이고 의도 표현의 것이
아니다 (3-E-29 §10 에서 측정). 그래서 `PlayerAction` 을 고칠 필요가 없다.

**`PlayerAction` 을 고치지 않았다.**

## 12. Mandatory / Optional

`_activation_actions` 안에 강제/임의 트리거를 다루는 코드가 **하나도 없다.**
`TriggerRequirement` · `TriggerWording` · 순서 · 사건 매칭 — 어느 이름도 읽지
않는다 (`test_02` · `test_13`).

**그것을 결함으로 보지 않는다.** 저장소가 경계를 이미 선언한다:

- `legal_actions` — 드로우는 "**선택이 아니라 규칙**이므로 행위 목록에 넣지
  않고 `advance` 가 수행한다" → 강제 진행은 흐름 계층의 것
- `WithheldAction` 의 칸은 `kind`·`reason`·`missing` 셋뿐 — `PlayerAction` 을
  들고 있지 않으므로 **`UNKNOWN` 이 구조적으로 후보가 될 수 없다**
- 강제/임의 구분은 `TriggerRequirement` 가 들고 있고 (잠든 계층), Action 에는
  그 칸이 없다 (3-E-29 `test_11` 이 고정)

→ **`SystemAction` · `TriggerAction` · 새 `PlayerActionKind` 를 만들지
않았다.** 트리거 파이프라인은 **의도적으로 잠들어 있다.**

## 13. Hidden Information

**누출 없음. `GameStateView` 변경 없음.**

| 점검 | 결과 |
|---|---|
| 상대 패 | `_activation_sources` 가 `self.state.player(seat)` — **자기 좌석만** 본다 |
| 상대 덱 | 같음 |
| 뒷면 카드 정체 | 상대 뒷면 세트 카드는 보는 쪽에게 `card_id is None` · `definition is None` (실측) |
| 비공개 효과 정의 | 관문은 `GameStateView` 로 판정한다 (ADR-007) |
| 비공개 사건 기록 | 열거가 journal 을 읽지 않는다 |
| 비공개 RNG | 열거가 RNG 를 만지지 않는다 (§14) |

경계의 위치: **열거는 판을 읽고 (자기 자리를 훑기 위해), 판정은 관측만
읽는다.** 상대의 뒷면 카드가 있어도 내 후보 수는 그대로다 (실측).

## 14. RNG / Determinism

| 항목 | 측정 |
|---|---|
| 같은 판에서 5번 호출 → 같은 답 | **그렇다** |
| `state_hash()` 불변 | **그렇다** |
| `state.rng.getstate()` 불변 | **그렇다** |
| RNG 소비 | **없음** |
| `GameState` 변경 | **없음** |

`test_10` 이 세 가지를 모두 고정한다. 그리고 `target_combinations` 는
`set` 을 쓰지 않으므로 순서가 관측의 순서로 고정된다 (그 함수의 docstring 이
그렇게 적는다).

## 15. AI / Search Impact

| 항목 | 변화 |
|---|---|
| legal action 생성 | **없음** |
| Search candidate generation | **없음** |
| ranking | **없음** |
| simulation | **없음** |
| clone 안전성 | **없음** |
| RNG 격리 | **없음** |
| hidden information | **없음** |
| `GameStateView` | **없음** |
| Evaluation | **없음** |

가정이 아니다: 이 Phase 의 변경 파일은 테스트 1개 + 문서 1개이고
(`git status`), `agent/` 는 손대지 않았다.

## 16. Corpus Findings

§9 의 9개 범주를 **등록된 코퍼스로** 따졌다 (무제한 카드 규칙 구현은 하지
않았다).

- 등록된 실행 가능한 효과는 **통상 마법 6 · 속공 마법 3 · 함정 4** — 전부
  마법/함정이고 유발 효과는 없다.
- 실제로 후보가 되는 것은 **통상 마법과 속공 마법**뿐이다.
- 함정 4장은 등록되어 있지만 **후보가 되지 않는다** — `UNKNOWN` +
  `TRAP_TRIGGER_MISSING`. 즉 "등록했으니 돈다" 가 아니라 **"등록했지만 발동
  타이밍을 모른다"** 가 정확히 기록된다.
- 사건 의존 효과가 들어올 자리: 함정은 유발 조건(`SetCode(EVENT_*)`) 이
  `EffectDefinition` 에 생기는 날, 몬스터는 효과 분류가 생기는 날. **둘 다
  지금 production 에 필요하지 않다** — 등록된 13개가 그것을 요구하지 않는다.

## 17. Structural Decision

**신규 STRUCTURAL ID 없음.**

기존 TODO 전부 유지 · 영향 없음 (`STRUCTURAL-31 / -32 / -33 / -34 / -119 /
-120 / -124 / -128 / -131 / -133 / -134`).

§18 의 다섯 조건으로 §8 의 소견(`point` 가 비어 있다)을 따졌다.

| 조건 | 충족 |
|---|---|
| 1. 아키텍처 문제인가 | 부분적 — 선언된 칸이 비어 있다 |
| 2. staged design 에 영향을 주는가 | 아니다 — 아무도 읽지 않는다 |
| 3. 기존 계약으로 표현할 수 없는가 | **표현된다** — `None` = "모른다" 가 이미 그 뜻이다 |
| 4. 다음 단계를 **실질적으로 막는가** | **아니다** |
| 5. 단순한 미래 구현 선택이 아닌가 | **단순한 미래 구현 선택이다** |

→ 조건 2·3·4·5 불성립. **감사 소견으로만 기록한다.**

### 감사 소견 (ID 없음)

1. **`ActivationTiming.point` 가 선언되어 있고 아무도 읽지 않는다.**
   `check` 가 쓰지 않고 production 호출자도 넘기지 않는다. 사건을 이을 때
   가장 먼저 볼 자리다. (`test_04` 가 고정)
2. **`_NormalSpellActivation` 의 docstring 표는 Phase 3-E-3 당시의 범위를
   적는다.** 그 표는 속공 마법을 범위 밖으로 적지만, 3-E-14 · 3-E-15 가
   세트된 통상 · 속공 마법을 범위 안으로 넣었고 `_NOT_A_SET_SPELL` 이
   "**`QUICKPLAY` 는 여기 없다** (Phase 3-E-15)" 라고 근거와 함께 적는다.
   **코드가 맞고 표가 역사적이다** — 결함이 아니라 문서의 시점 차이다.

## 18. Final Decision

**A. CORRECT STATE-BASED DESIGN → AUDIT-ONLY / FUTURE ARCHITECTURE GAP**

`_activation_actions` 는 **현재 판에서의 발동 열거기**이고, 사건 입력이 없는
것이 **맞다.** 사건 의존 효과는 범위 밖으로 선언되어 `UNKNOWN` 으로 남으며,
그 까닭이 사건을 명시적으로 가리키는 이름으로 기록된다. 두 경로는 production
에서 교차하지 않는다.

§23 의 조건에 그대로 걸린다 → production diff 0 · 새 `ActionKind` 없음 ·
`SystemAction` 없음 · 변환기 없음 · `activation_actions` 에 `Event` 인자 추가
없음 · 트리거 파이프라인 연결 없음.

### §22 의 다섯 질문

**Q1. `activation_actions()` 가 Event 없이 동작하는 것 자체가 문제인가?**

**NO.**
- 근거: AST 로 재면 `self.state` · `card.card_id` · `card.instance_id` ·
  `definition.cost` 만 읽는다. 그리고 등록된 13개가 전부 통상 마법 · 속공
  마법 · 함정이며 **이 중 후보가 되는 것은 사건을 묻지 않는 것들**이다.
  "지금 이 통상 마법을 발동할 수 있는가" 는 과거 사건을 요구하지 않는다.
- 의미: 상태 기반 열거기에 사건 입력이 없는 것은 **정상 설계**다. 사건이
  필요한 것은 적법성(어떤 사건에 응답하는가)과 순서이며, 그것은 다른 계층의
  질문이다.

**Q2. `activation_actions()` 가 `TriggerCandidate` 를 생성하거나 소비하는가?**

**NO.**
- 근거: `_activation_actions` · `_activation_sources` · `_activation_gate` ·
  `legal_actions` 네 함수의 AST 에 `TriggerCandidate` · `TriggerSpec` ·
  `TriggerCollector` · `TimingEvent` 가 하나도 없다. `engine/duel.py` 의
  import 전이 폐쇄에 파이프라인을 **만드는** 모듈이 하나도 없다
  (`trigger_chain` · `trigger_order` · `timing` · `event_pipeline`).
- 의미: 두 아키텍처가 **완전히 분리되어 있다.** 섞인 하이브리드가 아니다.

**Q3. event-dependent trigger effect 가 ordinary activation candidate 로
잘못 들어오는 production 경로가 있는가?**

**NO.**
- 근거: 함정은 패에 있든 세트되어 있든 `ACTIVATE_EFFECT` 후보가 **0개**다
  (실측). 검증기가 `UNKNOWN` + `RULE_NOT_IMPLEMENTED` +
  `missing_rule = TRAP_TRIGGER_MISSING` 을 돌려주고, 그 문장이 바로
  "공식 스크립트의 `SetCode(EVENT_*)` 가 `EffectDefinition` 에 없다" 다.
  `UNKNOWN` 은 허가가 아니므로 `legal_actions` 가 후보로 올리지 않는다.
- 의미: 사건 의존 효과가 **조용히** 섞이는 일이 없다. 막히고, **왜 막혔는지가
  이름으로 남는다.** `INVALID` 가 아니라 `UNKNOWN` 인 것도 중요하다 — 실제
  규칙은 함정 발동을 허락하므로 금지라고 적으면 거짓이 된다.

**Q4. 현재 `PlayerAction` / `legal_actions()` 계약을 변경해야 하는가?**

**NO.**
- 근거: 상태 기반 후보는 기존 `PlayerAction.activate_effect(actor, source,
  effect_ref, targets)` 로 **온전히** 표현되고 있다 (실측: 통상 마법 1개 ·
  대상 있는 속공 마법 1개). 사건 유발 후보도 식별 칸은 이미 대응되고
  (3-E-29), 사건 정보는 Action 의 것이 아니다 (ADR-007).
- 의미: 계약이 **충분하다.** 바꿀 이유가 없다.

**Q5. 현재 단계에서 Trigger pipeline 을 production 에 연결해야 하는가?**

**NO.**
- 근거: 등록된 13개 효과 중 **연결을 요구하는 것이 하나도 없다** (유발 효과
  0개). 그리고 `ActivationTiming.point` 가 선언되어 있지만 `check` 가 읽지
  않으므로, 지금 연결해도 **판정이 달라지지 않는다.**
- 의미: 연결은 **유발 조건(`SetCode(EVENT_*)`) 이 `EffectDefinition` 에
  들어오는 날**의 일이다. 그 전에 연결하면 읽지 않는 값을 넘기는 배관만
  늘어난다.

## 19. Next Phase Candidate

### `EffectDefinition` 의 유발 조건 칸 감사 (Trigger Condition Field Audit)

- 측정된 사실: 이 Phase 가 막는 벽의 이름이 하나로 수렴한다 —
  `TRAP_TRIGGER_MISSING` 이 말하는 **"공식 스크립트의 `SetCode(EVENT_*)` 가
  `EffectDefinition` 에 없다"**. `EffectDefinition` 의 칸은
  `effect_ref` · `source_card_id` · `operations` · `activation` · `cost` ·
  `targets` · `declarations` · `requirements` · `guards` · `provenance` 열
  개이고, **사건을 적는 칸이 없다.** 반면 `TriggerSpec` 은 `point` ·
  `condition` · `requirement` · `wording` · `activates_from` 을 갖고 있다.
- 볼 것: (a) `TriggerSpec` 이 이미 그 정보를 들고 있는데 `EffectDefinition`
  에 또 칸을 만들어야 하는가, 아니면 **둘을 잇는 조회**로 충분한가 (ADR-006
  의 "등록소에서 찾는다" 태도와 같은가). (b) 3-E-18/19 가 측정한 Lua
  `SetCode(EVENT_*)` 파싱 결과를 **손으로 등록**하는 것이 ADR-006 과 맞는가.
  (c) 칸이 생기면 `_activation_out_of_scope` 의 함정 분기가 어떻게 바뀌는가 —
  `UNKNOWN` 에서 벗어나는 효과가 생기는가.
- 왜 지금이 아닌가: 이번 Phase 는 "열거가 사건 없이 도는 것이 옳은가" 라는
  닫힌 질문이었고 답은 "옳다" 였다. (a) 는 설계 판단이므로 별도 감사가 필요
  하다.
- 왜 다음인가: 이 Phase 가 **막는 벽의 이름을 하나로 좁혔다.** 그 벽이
  `EffectDefinition` 의 빈 칸이므로, 다음 질문은 "그 칸이 정말 필요한가" 다.

**이 Phase 는 여기서 멈춘다. 다음 Phase 는 임의로 진행하지 않는다.**
