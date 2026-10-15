# Phase 6-I — TRIGGER 등록 · 효과 정의 · Duel 실행 경로 최소 통합

작업 브랜치: `claude/pensive-goodall-te1egy`
선행: [6-E](phase6e-trigger-analysis-candidate-integration.md) ·
[6-F](phase6f-trigger-event-subject-validation.md) ·
[6-G](phase6g-trigger-activation-location.md) ·
[6-H](phase6h-field-trigger-condition-integration.md)

6-H 까지 부품은 전부 있었다. 없던 것은 **그것을 한 줄로 잇는 자리**였고,
6-I 가 그 자리를 만들었다.

> **합법적인 `PlayerAction` 하나가 실제 사건을 만들고, 그 사건에서 기존
> 수집기·판정기가 후보를 내놓는다.** 지어낸 `TimingEvent` 가 하나도 없다.

자동 발동도, 체인 생성도, 효과 해결도 하지 않았다 (§15).

---

## 1. 기존 EffectDefinition 과 TriggerSpec 식별 구조

**두 계층이 이미 같은 이름을 쓴다.** 조사의 첫 결론이 이것이고, 그것이
§5 의 답을 바꿨다.

| | 식별자 | 조회 |
|---|---|---|
| `EffectDefinition.effect_ref` | `EffectRef(card_id, ordinal)` | `EffectDefinitionRegistry.definition_for(ref)` |
| `TriggerSpec.effect_ref` | `EffectRef(card_id, ordinal)` | `TriggerRegistry.watching(event)` |
| 실행 구현 | 같은 `EffectRef` | `EffectImplementationRegistry.has_implementation(ref)` |

- `EffectRef` 는 **두 값**으로 식별한다 (`card_id`, `ordinal`). 그래서 한
  카드의 서로 다른 효과가 섞이지 않는다 — 카드 ID 만으로 연결하면 안 되는
  이유가 그 자리에 있다 (§3-4 · §3-5).
- **모호성 문제가 애초에 없다.** 문제는 두 집합이 **서로소**라는 것이다.

### 1.1 `ordinal` 이 무엇의 자리인가 — 조용히 틀릴 수 있던 곳

`ordinal` 은 `card.script.effects` 안의 자리다 (3-F-37 이 세운 규약:
*"돌려주는 목록의 `i` 번째가 `card.script.effects[i]` 여야 하고, 그것이 곧
`EffectRef(card_id, i)` 다"*).

그런데 6-E~6-H 의 측정은 전부 `enumerate(analysis.effects)` 의 **순번**을
`ordinal` 로 썼다. `analysis.effects` 는 `initial_effect` 에서 만들어진
블록만 담으므로 두 값은 **다를 수 있다.**

전수로 재어 보았다.

| 측정 | 값 |
|---|---|
| 등록 효과가 있는 카드 | 12,472 |
| 두 값이 어긋난 등록 | **0** |

0 인 까닭은 규약이다 — `initial_effect` 가 파일의 첫 함수이므로 그 블록의
offset 이 가장 작고, 등록 효과가 언제나 앞에 모인다. **문법이 아니라 관습**
이므로 production 은 그 성질에 기대지 않고 **자리를 직접 찾는다**
(`compiled_triggers` 의 `ordinal_of`), 그리고 `test_23` 이 성질 자체를
핀으로 남긴다.

🔴 **이 결정이 왜 중요했는지는 변이 테스트가 증명했다** — §13.3.

---

## 2. 기존 TriggerRegistry 의 생성 및 사용 경로

조사 결과 (코드로 재검증):

| 질문 | 6-H 까지 | 근거 |
|---|---|---|
| `TriggerRegistry(...)` 를 만드는 production 자리 | **0곳** | AST 전수 |
| `engine.event_pipeline` 을 import 하는 production 파일 | **0곳** | import 전수 |
| `engine.timing` 을 import 하는 production 파일 | **0곳** | 같음 |
| `Duel` 이 등록소를 들고 있는가 | 아니다 | `duel.py` 에 `trigger` 라는 말이 없다 |
| `compile_trigger_spec` 의 production 호출자 | **0곳** | 6-H §15 가 보고 |

소비자는 전부 등록소를 **인자로 받는다** (`TriggerCollector` ·
`EventPipeline` · `engine/timing.py` · `trigger_chain.py`). 즉 끊긴 지점은
하나이고 정확하다.

> **아무도 등록소를 만들지 않았다.** 부품과 조립도가 다 있는데 조립도를
> 펴는 사람이 없었다.

---

## 3. 실제 Duel 실행에서 사건이 발생하는 경로

측정 (실제 듀얼):

```
Duel.apply(action)
    ↓
EventJournal 에 기록 하나          ActionEvent(kind=ACTION, actor, deltas, …)
    ↓  EventPipeline.collect(record, actor=record.actor)
EventReader → TimingEvent          ← 사건은 **여기서** 만들어진다
    ↓
EventObservation.candidates        TriggerCollector 가 모은 후보
```

- `TimingEvent` 는 `Duel` 이 만들지 않는다. **기록에서 읽어 낼 때** 만들어진다.
- 주체 · 인스턴스 · 이동 전후 영역은 기록 안의 **delta** 가 들고 있다.
- 한 행동이 사건 여럿을 만들면 순서는 기록의 순서 그대로다. 실측: 욕망의
  항아리 발동 한 번이 기록 **3건**(ACTION · EFFECT · ACTION) 을 만들고 그중
  EFFECT 기록이 `CardDrawn` **둘**을 품는다.

---

## 4. 연결을 막고 있던 정확한 원인

하나가 아니라 **셋**이고, 셋이 같은 방향을 가리켰다.

1. **조립 자리가 없었다** (§2). 등록소를 만드는 production 코드가 0곳.
2. **`engine` 안에 그 자리를 둘 수 없었다.** 두 감사가 막는다.
   - ADR-007 — `engine` 이 `analysis` 에서 가져올 수 있는 이름은
     `LimitScope` **하나**다 (`test_contract_h`).
   - `EffectSpec` 전용 칸(`effect_types` 등)을 `engine` · `agent` 가 읽지
     않는다 (`test_binding_rule_alignment::test_37`). 등록 정보를 꺼내려면
     그 칸을 읽어야 한다.
3. **`Duel` 안에도 둘 수 없었다.** `duel.py` 에 `trigger` 라는 **말**이
   없음을 `test_trigger_pipeline_dormant_audit::test_12` 가 고정한다.

→ 그래서 자리를 **두 층 위에** 만들었다. 두 규칙에 예외를 파지 않았다.

---

## 5. 선택한 최소 통합 방식과 대안 비교

| 대안 | 깨지는 계약 | 판단 |
|---|---|---|
| **A. 관찰자를 `Duel` **밖**에 둔다** (채택) | dormant 핀 **2개** (`test_04` · `test_05`) | **채택** |
| B. `Duel` 에 `triggers` 칸을 더한다 (6-B 의 `journal` 선례) | `test_12` (말 금지) + `test_06`(폐쇄) + 쓰이지 않는 칸이 계약에 남는다 | 기각 — §6-1/-2 가 계약 보존을 요구하고, 자동 발동이 없는 동안은 듀얼이 등록소를 들 이유가 없다 |
| C. 조립 자리를 `engine` 안에 둔다 | ADR-007 + `test_37` | 기각 — §4 의 둘째 원인 |
| D. 조립 자리를 `analysis` 에 둔다 | `analysis → engine` 역방향 의존이 새로 생긴다 (현재 0곳) | 기각 — 한 방향 계층을 뒤집는 쪽이 더 큰 변경이다 |
| E. 등록소를 시험이 만들던 대로 둔다 | 없음 | 기각 — §16-6 이 금지한 "시험만의 통합" |

**A 를 고른 이유 세 가지** (모듈 머리말에 그대로 적었다):

1. `test_12` 가 지키는 것은 *"듀얼은 스스로 규칙을 만들지 않는다"* 이고,
   이번 단계가 원하는 **관찰**은 그 규칙을 바꾸지 않아도 된다.
2. 자동 발동이 없는 동안 듀얼이 등록소를 들고 있을 이유가 없다. 지금 넣으면
   **쓰이지 않는 칸**이 계약에 남는다.
3. 밖에 두면 *"관찰이 판을 바꾸지 않는다"* 가 **구조로** 참이 된다 —
   바꿀 손이 없다 (`test_21` 이 AST 로 고정한다).

🔴 **B 는 버린 것이 아니라 다음 단계의 일이다.** 듀얼이 스스로 후보를 모아
체인에 넣어야 할 때 그 변경이 필요하고, 그때 `test_12` 를 움직일 **이유**도
함께 생긴다. 지금 움직이면 이유 없이 움직이는 것이다.

---

## 6. 변경한 파일 및 함수

| 파일 | 줄 | 무엇 |
|---|---|---|
| `integration/__init__.py` | +47 | 새 조립 층. 왜 이 자리가 필요했는지와 두 감사의 근거 |
| `integration/trigger_registry.py` | +215 | `CardTriggers` · `RegistryBuild` · `compiled_triggers` · `registry_for_view` |
| `engine/trigger_observation.py` | +300 | `ObservationStage` · `TriggerObservation` · `_stage_of` · `TriggerObserver` |
| `tests/engine/test_trigger_duel_integration.py` | +1200 | 신규 26개 |
| `tests/test_trigger_pipeline_dormant_audit.py` | +67/−20 | 핀 2개 갱신 + 1개 **강화** |
| `tests/test_binding_rule_alignment.py` | +4/−1 | 금지 import 검사 범위에 `integration` 추가 |

**기존 production 파일을 하나도 고치지 않았다.** `engine/duel.py` ·
`engine/trigger.py` · `engine/event_pipeline.py` · `engine/trigger_compiler.py`
모두 `git diff` 에 없다. Engine V1 의 공개 계약 · `PlayerAction` ·
`GameState` 가 그대로다.

### 6.1 핵심 코드

```python
# integration — 자리를 **찾는다**. 순번으로 추정하지 않는다.
ordinal_of = {id(spec): index for index, spec in enumerate(card.script.effects)}
for effect in analyzer.analyze(card).effects:
    ordinal = ordinal_of.get(id(effect.raw))
    if ordinal is None:
        unplaceable += 1          # 자리를 모르면 **등록하지 않는다**
        continue

# integration — **보이는 카드만**, 카드 정의마다 **한 번**
for instance in view.visible_instances():
    card = view.find(instance)
    if card is None or card.card_id is None:
        concealed += 1            # 가려진 카드는 세고 넘어간다 (§6-7)
        continue
    if card.card_id in seen:
        continue                  # 사본이 둘이어도 등록은 하나

# engine — 사다리의 마지막 칸은 **네 조건을 모두** 요구한다
if eligibility.status in (FORBIDDEN, INELIGIBLE):      return REFUSED
if relation.result.validity is UNKNOWN:               return EVENT_UNDECIDED
if eligibility.status is not ELIGIBLE:                return JUDGEMENT_PENDING
if not eligibility.fully_checked:                     return RULES_SATISFIED
if has_definition and is_executable:                  return EXECUTION_READY
return RULES_SATISFIED
```

---

## 7. 실제 사건 → 등록 조회 → 후보 판정 호출 경로

```
Duel.start(repository, decks=…, seed=…)            ← 기존 생성자. 그대로.
    ↓  duel.legal_actions(seat).allowed            ← 기존 행동 목록
PlayerAction(activate_effect, 55144522:e[0])
    ↓  duel.apply(action)                          ← 기존 실행 경로
    ↓  duel.apply(pass)   × 응답 창                 ← 기존 ResponseLoop
EventJournal: ActionEvent · EffectEvent · ActionEvent
    ↓  integration.registry_for_view(duel.view(0), repository)
RegistryBuild(registry, card_ids, registered, concealed, …)
    ↓  engine.trigger_observation.TriggerObserver(view, registry,
    ↓                                             definitions, implementations)
    ↓  observer.observe_all(duel.journal.events)
    ↓      └─ EventPipeline.collect  → TriggerCollector  ← 기존 계층
    ↓      └─ TriggerEligibilityJudge.judge             ← 기존 판정
TriggerObservation × 12
```

**새로 만든 것은 가운데 두 줄뿐이다.** 수집도 판정도 다시 짜지 않았다
(§3-12 · §15 의 중복 구현 금지).

---

## 8. EffectDefinition 연결 성공·실패·모호 사례

전수 측정 (`test_24`):

| 항목 | 수 |
|---|---|
| 컴파일된 TRIGGER 등록 | 4,173 |
| 그중 `EffectDefinition` 이 있는 것 | **0** |
| 그중 실행 구현까지 있는 것 | **0** |
| `EffectDefinition` 중 TRIGGER 인 것 | **0** |
| **모호(AMBIGUOUS)** | **0** |

🔴 **0 이 네 번 나오는데 까닭이 하나다.** `EFFECT_LIBRARY` 16건은 전부
마법의 `ACTIVATE` 효과이고 `ordinal` 이 모두 0 인 **블록 하나짜리** 카드다.
두 집합이 서로소다.

"모호 0" 은 운이 아니라 **식별자가 같아서**다 (§1). 그래서 다음 단계가 고칠
곳은 식별 체계가 아니라 **정의 목록**이다 (§16).

🔴 **연결 실패가 분석 결과를 지우지 않았다** (§5 의 마지막 금지). 정의가
없는 4,173건도 등록되고 후보가 되고 판정된다 — 다만 `EXECUTION_READY` 가
되지 않는다 (`test_13`).

### 8.1 한계 하나를 정직하게

`EffectRef` 의 `ordinal` 이 두 계층에서 같은 뜻이라는 것은 **타입과 규약**
으로는 참이지만, **`ordinal > 0` 인 정의가 하나도 없어서** 실제 데이터로
교차 검증할 수 없다. 16건 전부 `ordinal == 0` 이기 때문이다. 블록이 여러
개인 카드의 정의가 처음 등록되는 날 이 교차를 다시 확인해야 한다.

---

## 9. 실제 게임 상태에서 수행한 수직 통합 테스트

`tests/engine/test_trigger_duel_integration.py` — **26개**.

§10 의 여덟 시나리오가 모두 들어 있고, 전부 **실제 `Duel.apply`** 를 지난다.

| 시나리오 | 테스트 | 무엇을 보았는가 |
|---|---|---|
| A 실제 행동 | `test_04` | 승인 · `state_hash` 변화 · 기록 1건 · `actor`/`deltas`/`changed_state` |
| B 등록 조회 | `test_05`·`06`·`07` | 보이는 카드만 · 덱 카드 제외 · 뒷면 카드 제외 |
| C 후보 판정 | `test_08`·`09` | 주체 · 위치 · 미구현 · UNKNOWN 전파 |
| D 복수 인스턴스 | `test_10` | 사건의 그 한 장만 통과, 나머지는 확정 거부 |
| E 부적합 사건 | `test_11`·`12` | 등록은 있고 사건이 달라서 후보 0건 / 기르수 회귀 |
| F 구현 없음 | `test_13`·`14`·`15`·`16` | 후보는 유지, 실행 가능이라고는 말하지 않음 |
| G 등록 미제공 | `test_17` | 등록소 없는 듀얼과 `state_hash` 가 같다 |
| H 복수 듀얼 격리 | `test_19` | 등록소 · 후보가 섞이지 않는다 |

### 9.1 §10 의 수직 경로 (`test_09`)

```
Duel.start(덱 = [욕망의 항아리] + [마하드]×20)
    ↓  legal_actions → activate_effect 55144522:e[0]     ← 실제 합법 행동
    ↓  apply → "체인 1 로 발동했습니다. 상대의 응답을 기다립니다."
    ↓  apply(pass) → "체인1 P0 55144522:e[0] 를 해결했습니다."
CardDrawn × 2                                            ← 실제 delta
    ↓  registry_for_view → 등록 1건 (마하드 e[0], card_drawn, HAND)
    ↓  observe_all → 관찰 12건
```

뽑힌 카드 자신의 드로우 사건에서의 판정:

| 관문 | 결과 |
|---|---|
| `event_relation` | **VALID / OK** ← 6-F 의 주체 축 |
| `activation_zone` | **VALID / OK** ← 6-G 의 위치 축 |
| `trigger_condition` | UNKNOWN |
| `execution_authority` | UNKNOWN |
| `cost_feasibility` | UNKNOWN |
| 전체 | **UNKNOWN** · `stage=JUDGEMENT_PENDING` |

**6-F 와 6-G 가 만든 두 축이 실제 `PlayerAction` 에서 동시에 통과한 첫
사례다.** 6-H 의 `test_22` 는 `GameState` 에서 같은 일을 했고, 6-I 는
그것을 **`Duel` 의 행동 목록에서 고른 행동**으로 한다.

관찰 12건의 구성: 드로우 사건 2 × 보이는 마하드 사본 6 = 12. 그중 **2건**이
자기 사건이고 `JUDGEMENT_PENDING`, **10건**이 다른 사본이고 `REFUSED`.

### 9.2 기르수 (§11 의 회귀 요구)

`test_12` — 기르수를 필드에 두고 **페더맨**을 일반 소환한다. 기르수의
등록은 `SINGLE`(→`SELF`) 이므로 사건 관계가 **확정 거부**이고 `REFUSED` 다.

🔴 **기르수의 일반 소환이 `UNDETERMINED` 인 것을 우회하지 않았다.** 기르수를
소환하지 않고 필드에 두었고, 소환되는 쪽은 엔진이 실제로 소환할 수 있는
통상 몬스터다.

---

## 10. 미지원 효과 및 UNKNOWN 처리 결과

§8 의 A~E 를 **다섯 값 한 사다리**로 적었다 (`ObservationStage`). 순서는
`fold` 와 같다 (거부 → 모름 → 통과).

| 값 | 뜻 | 실측 도달 |
|---|---|---|
| `REFUSED` | 확정 거부 | ✅ 10/12 · 기르수 전부 |
| `EVENT_UNDECIDED` | 사건 관계부터 모른다 (A) | ✅ 알렉산더 |
| `JUDGEMENT_PENDING` | 사건은 맞고 미확인이 남았다 (B·C·D) | ✅ 2/12 |
| `RULES_SATISFIED` | 관문 다섯 통과, 미검사 규칙 남음 | ❌ 0건 |
| `EXECUTION_READY` | 위 + 정의 + 구현 (E) | ❌ **0건 — 도달 불가** |

`EXECUTION_READY` 가 도달 불가인 까닭은 **하나가 아니라 셋**이다
(`test_14`): 정의 0건 · 구현 0건 · `UNCHECKED_RULES` 6개가 비지 않는다.

🔴 **도달할 수 없는 칸을 값으로 적어 둔 이유**: 비워 두면 "실행 가능" 과
"아직 모른다" 가 같은 값이 된다. `test_15` 가 네 조건을 하나씩 떼어 보며
**한 조건만 빠져도 그 칸이 아니라는 것**을 확인한다.

🔴 **정의 없이 "실행 가능" 이라고 말하지 않는다** (`test_16`). 구현 목록에만
이름이 있고 정의가 없으면 **무엇을 실행할지 모르는** 상태다 (ADR-006).

---

## 11. 중복 · 복수 인스턴스 · 듀얼 격리

| 질문 | 답 | 근거 |
|---|---|---|
| 같은 카드 두 장이 등록을 공유하는가 | **등록은 하나** (정의별) | `test_10`: `len(refs) == len(set(refs))` |
| 사건과 무관한 사본이 통과하는가 | 아니다 — 확정 거부 | `test_10`: 사본 5건 전부 `REFUSED` |
| 같은 사건이 중복 처리되는가 | 아니다 | 사건마다 따로 돌려주고 합치지 않는다 |
| 두 듀얼의 등록소가 섞이는가 | 아니다 — 호출마다 새 등록소 | `test_19`: `rich.registry is not poor.registry` |
| 판에 없는 카드가 등록되는가 | 아니다 | `test_06`: 덱의 20장이 등록을 20배로 만들지 않는다 |
| 가려진 카드의 정체가 새는가 | 아니다 — 세고 넘어간다 | `test_07`: 유출 0건 |

**등록은 정의별이고 후보는 인스턴스별**이라는 구분이 이 여섯 줄의 근거다.
`TriggerSpec` 은 인스턴스를 들고 있지 않고, "어느 인스턴스의 사건인가" 는
등록이 아니라 **판정**이 답한다 (6-F 의 `subject_relation`). 이 구분을
흐리면 "등록을 인스턴스마다 복제해야 한다" 는 잘못된 결론이 나오고, 그
복제가 후보를 중복시킨다 — 변이 **M2** 가 그것을 재현하고 `test_06` 이
잡았다.

---

## 12. EventJournal 및 Engine V1 호환성

- **기존 production 파일을 하나도 고치지 않았다.** `Duel` 의 생성자 ·
  `legal_actions` · `apply` · `advance` · `journal` 이 전부 그대로다.
- `test_17` — 등록소를 만든 듀얼과 만들지 않은 듀얼의 `state_hash` 가
  **같다.** 같은 씨앗 · 같은 행동 · 같은 결과.
- `test_18` — 관찰 전후로 `(state_hash, len(chain), priority, step,
  모든 기록의 canonical_state)` 가 **한 글자도 다르지 않다.** 두 번
  관찰해도 같다 (관찰에 누적 상태가 없다).
- `test_21` — 관찰 모듈이 상태를 바꾸는 이름을 **하나도 부르지 않는다**
  (AST). "바꾸지 않는다" 를 시험으로만 보이면 시험하지 않은 경로가 남지만,
  호출이 없으면 경로 자체가 없다.
- `test_22` — 관찰 모듈은 `analysis` 도 `integration` 도 import 하지 않는다
  (ADR-007 을 새 모듈에 대해서도 확인).
- EventJournal 은 **관찰·감사 기록으로 남았다** (§3-11). 읽기만 한다.

---

## 13. 타깃 · 통합 · 최종 회귀 테스트 결과

### 13.1 움직인 기존 핀 — 셋 (둘은 갱신, 하나는 **강화**)

| 핀 | 전 | 후 | 왜 |
|---|---|---|---|
| `dormant::test_04` | `event_pipeline` importer **0곳** | **1곳** (`engine/trigger_observation.py`) | 조립도를 펴는 사람이 생겼다 — **이번 Phase 의 산출물**이다. `engine.timing` 은 **여전히 0곳** (체인을 만들지 않으므로) |
| `dormant::test_05` | `engine.trigger` importer 6곳 | **7곳** | 같은 모듈이 늘었다. 휴면 모듈 넷은 그대로 휴면 (`test_06` 이 고정) |
| `dormant::test_13` | `engine/` 만 뒤져 `TriggerRegistry` **0곳** | production 패키지 **전체**를 뒤져 **1곳** (`integration/trigger_registry.py`) | 🔴 **강화했다** |
| `binding::test_39` | 금지 import 검사 5패키지 | **6패키지** (`integration` 추가) | 새 패키지가 금지선 밖에 있으면 안 된다 |

🔴 **`test_13` 을 왜 강화했는가.** 원래 `engine/` 만 뒤졌다. 등록소를
`integration/` 에서 만들면 그 감사는 **조용히 참이 된다** — 측정값이
바뀌었는데 감사가 통과하는 것은 감사가 아니라 눈가림이다. 범위를 production
패키지 전체로 넓혀 "정확히 한 곳" 을 고정했다.

`test_12` (`duel.py` 에 `trigger` 라는 말 금지) 와 `test_06` (Duel 의 import
폐쇄) 은 **움직이지 않았다.** 그것이 §5 에서 A 를 고른 결과다.

### 13.2 테스트 명령과 결과

| 단계 | 명령 | 결과 |
|---|---|---|
| 1·2 타깃 + 통합 | `pytest tests/engine/test_trigger_duel_integration.py -q -p no:randomly` | **26 passed** · 49s |
| 3 관련 회귀 | `pytest tests/test_trigger_pipeline_dormant_audit.py` | 26 passed · 13s |
| | `pytest tests/test_binding_rule_alignment.py tests/engine/test_phase2_contracts.py` | 60 passed · 3m43s |
| 4 최종 | §13.4 |

🔴 **출력을 자르지 않고 종료 코드를 확인했다.** 6-H 에서 `| tail` 이 실패
목록을 가렸고, `python3 -I` 가 코드와 무관한 실패를 만들었다. 이번에는
`-I` 를 쓰지 않고 각 묶음의 `[exit N]` 을 함께 기록했다.

### 13.3 변이 테스트 — 열 가지로 틀리게 만들었다

| 변이 | 잡은 테스트 |
|---|---|
| M1 가려진 카드도 등록한다 | `test_07` |
| M2 같은 카드를 사본마다 등록한다 | `test_06` |
| M3 블록의 자리를 순번으로 추정한다 | `test_25`·`test_26` |
| M4 자리를 못 찾아도 0 으로 지어낸다 | `test_26` |
| M5 정의 없이도 실행 가능이라고 한다 | `test_16` |
| M6 미검사 규칙을 무시하고 올린다 | `test_15` |
| M7 사건 관계의 모름을 건너뛴다 | `test_08` |
| M8 거부를 가장 앞에 두지 않는다 | `test_10` |
| M9 정의가 없어도 `EXECUTION_READY` 로 | `test_15` |
| M10 관찰이 등록소를 다시 채운다 | `test_05` |

🔴 **첫 실행에서 M3 · M4 가 살아남았고, 그것이 §1.1 의 결정을 시험에
묶었다.** 둘 다 **실제 카드에서는 티가 나지 않는다** — 전 corpus 에서
`enumerate` 순번과 블록의 자리가 같고 (12,472장, 어긋남 0) 자리를 못 찾는
경우가 0건이기 때문이다. 즉 **지금 데이터로는 그 코드가 틀렸는지 알 수
없었다.**

그래서 데이터가 그렇지 않은 모양을 직접 만들어 함수에 넣었다 (`test_25` ·
`test_26`): 등록 효과가 블록 **0 과 2** 이고 블록 1 은 등록 효과가 아닌
카드. 올바른 코드는 `ordinal` 을 **0 과 2** 로 적고, 순번 추정은 **0 과 1**
로 적어 둘째 선언이 **다른 블록의 효과**를 가리킨다 — §5 가 금지한 바로 그
잘못된 연결이다.

사건을 지어낸 것이 아니다 (§16-6 은 **사건**을 지어내지 말라는 것이다).
순수한 자리 찾기 함수에 실제 `EffectSpec` · `LuaScriptInfo` 를 넣었고,
`test_20` 이 이 파일에 `TimingEvent` · delta 생성이 **하나도 없음**을 AST 로
고정한다.

변이를 적용한 상태로 다른 테스트를 돌리지 않았다. 매 변이마다 적용 →
해당 파일만 실행 → 복원이고, 마지막에 `git status` 로 복원을 확인했다.

### 13.4 움직인 감사 — 전부 **같은 한 가지 사실**이다

회귀 4분할에서 실패 **14건**이 나왔다. 전부 *"트리거 파이프라인에 production
importer 가 0곳이다"* 또는 *"`TriggerRegistry` 를 만드는 production 자리가
0곳이다"* 를 적어 둔 핀이고, **그 사실이 이번 Phase 의 산출물로 바뀌었다.**

| 파일 | 테스트 | 무엇이 움직였나 |
|---|---|---|
| `test_trigger_pipeline_dormant_audit` | `test_04`·`test_05`·`test_13` | importer 0→1 · 6→7 · 레지스트리 생성 자리 (+범위 강화) |
| `test_actor_declaration_scope_audit` | `test_23` | pipeline importer |
| `test_actor_role_separation_audit` | `test_18` | 같음 |
| `test_event_context_actor_provenance` | `test_20` | 같음 |
| `test_event_reader_actor_input_boundary` | `test_03`·`test_21` | actor 호출 자리 +1 · importer |
| `test_event_reader_actor_input_contract` | `test_19` | importer |
| `test_result_actor_provenance_design_audit` | `test_13` | importer |
| `test_engine_condition_none_contract_audit` | `test_01` | `engine/` 파일 수 68→69 |
| `test_trigger_connectivity_audit` | `test_01`·`test_02`·`test_04` | 두 입구 중 하나가 열렸다 · importer 6→8 · 생성 자리 2→3 (+범위 강화) |
| `test_trigger_spec_declaration_audit` | `test_17` | pipeline importer |
| `test_trigger_to_action_contract` | `test_01` | 후보 소비 모듈 목록 +1 |
| `test_validation_code_minimal_fix` | `test_09` | 레지스트리 생성 자리 |
| `test_binding_rule_alignment` | `test_39` | 금지 import 검사 범위 +`integration` |

**움직이지 않은 것이 더 중요하다.**

| 유지된 단정 | 왜 유지되는가 |
|---|---|
| `duel.py` 에 `trigger`·`Trigger` 라는 말이 없다 | `Duel` 을 고치지 않았다 |
| `Duel` 의 import 폐쇄가 휴면 모듈 넷을 제외한다 | 듀얼이 관찰 모듈을 부르지 않는다 |
| `engine.timing` 의 production importer **0곳** | 체인을 만들지 않았다 (§15) |
| 살아 있는 경로가 `engine.trigger` 에서 가져가는 이름이 `TimingPoint` 하나 | 그대로 |
| 후보를 `PlayerAction` 으로 바꾸는 production 함수 **0곳** | 자동 발동이 없다 |
| `PlayerAction` 을 만드는 production 모듈이 `engine/duel.py` 하나 | 그대로 |
| M3 (`_event_relation` 의 관문 코드) | 등록소가 생긴 것이 그 코드를 바꾸지 않는다 |
| ADR-007 (`engine` 이 `analysis` 에서 `LimitScope` 하나만) | 조립 자리를 `integration` 에 두었다 |

🔴 **범위를 넓힌 감사 둘** (`dormant::test_13` · `connectivity`):
원래 `engine/`(또는 `engine`·`agent`·`app`) 만 뒤졌다. 등록소를
`integration/` 에서 만들면 그 감사들은 **조용히 참이 된다** — 측정값이
바뀌었는데 통과하는 것은 감사가 아니라 눈가림이다. 범위를 넓혀
"정확히 어디 한 곳" 을 고정했다.

🔴 **거짓 양성 하나를 코드로 고쳤다.** `connectivity::test_04` 는 문자열
`"TriggerRegistry("` 를 찾는데, `integration/__init__.py` 의 **설명 문장**이
거기에 걸렸다. 감사의 기대 목록에 그 파일을 더하면 "그 파일이 등록소를
만든다" 는 **거짓을 기록**하게 되므로, 설명 문구를 `:class:` 참조로 바꿨다.

**assertion 약화 · threshold 완화 · skip 추가 · 테스트 삭제는 하나도
없다.** 전부 "지금 몇 곳인가" 를 세는 핀이고, 센 값이 달라졌으므로 값을
갱신하면서 **왜 달라졌는지**와 **무엇이 그대로인지**를 같은 자리에 적었다.

### 13.5 최종 회귀 — 측정값

명령: `python3 -m pytest <대상> -q -p no:randomly --no-header --tb=line`
(각 묶음의 **pytest 종료 코드**를 함께 기록했다. `-I` 는 쓰지 않았다 —
6-H 에서 그 플래그가 코드와 무관한 실패를 만들었다.)

| 대상 | 통과 | 건너뜀 | 실패 | 종료 코드 | 시간 |
|---|---|---|---|---|---|
| `tests/engine` | 3,061 | 0 | 0 | **0** | 05:12 |
| `tests/agent` + `tests/rules` + `tests/rulings` | 529 | 4 | 0 | **0** | 03:36 |
| `tests/*.py` chunk0 (25파일) | 678 | 0 | 0 | **0** | 20:43 |
| `tests/*.py` chunk1 (22파일) | 557 | 0 | 0 | **0** | 11:50 |
| `tests/*.py` chunk2 (23파일) | 576 | 0 | 0 | **0** | 12:31 |
| `tests/*.py` chunk3 (22파일) | 466 | 0 | 0 | **0** | 07:14 |
| **합계** | **5,867** | **4** | **0** | | 61:06 |

4분할은 `split -n l/4` 로 나누고 `diff` 로 **빠짐·중복 없음**을 확인했다
(92파일 = 25+22+23+22).

6-H 가 보고한 5,841 passed 와 비교하면 **+26** 이고, 그것이 이번에 더한
테스트 수(26)와 같다.

---

## 14. 후보 수집 전후의 게임 상태 및 우선권 변화 여부

**없다.** 그리고 그것이 시험으로만이 아니라 **구조로** 참이다.

| 축 | 전 | 후 | 근거 |
|---|---|---|---|
| `state.state_hash()` | 같음 | 같음 | `test_18` |
| `len(duel.chain)` | 같음 | 같음 | `test_18` |
| `duel.priority` | 같음 | 같음 | `test_18` |
| `duel.step` | 같음 | 같음 | `test_18` |
| `journal.events` 의 모든 `canonical_state()` | 같음 | 같음 | `test_18` |
| 같은 행동의 결과 (등록소 있음 / 없음) | — | `state_hash` 동일 | `test_17` |

구조적 근거 (`test_21`): `engine/trigger_observation.py` 가 `apply` ·
`advance` · `move` · `draw` · `create_instance` · `register` · `record` ·
`set_phase` · `set_result` · `push` · `resolve*` 중 **어느 것도 부르지
않는다** (AST). 바꿀 손이 없으므로 시험하지 않은 경로도 없다.

또한 **관찰을 두 번 해도 결과가 같다** — 관찰자에 누적 상태가 없다
(`observe` 는 매번 새 리스트를 만들고 돌려주는 객체는 전부 frozen).

---

## 15. 발견한 추가 구조적 차단 문제

| # | 문제 | 지금의 모습 | 영향 |
|---|---|---|---|
| 1 | **TRIGGER 의 `EffectDefinition` 이 0건** | `EFFECT_LIBRARY` 16건 전부 마법 `ACTIVATE` | 다음 단계의 **첫 일**. 세 관문이 동시에 이것 하나를 기다린다 |
| 2 | **`ordinal > 0` 인 정의가 없어 교차 검증이 안 된다** | 16건 전부 `ordinal == 0` | 블록 여러 개인 카드의 정의가 처음 등록되는 날 §1.1 을 다시 확인해야 한다 |
| 3 | **등록소가 관측 시점의 사진이다** | 사건이 카드를 움직이면 보이는 카드가 달라진다 | 지금은 "사건 뒤의 관측" 을 쓰면 되지만, 자동 발동에서는 **사건 시점의** 등록소가 필요해진다 |
| 4 | **드로우 페이즈의 드로우가 사건을 만들지 않는다** | `Duel.advance` 가 `state.draw` 를 직접 부른다 (6-H §15 가 측정) | 효과 드로우로 우회했다. 「드로우했을 때」 카드가 **일반 드로우**에 반응하려면 고쳐야 한다 |
| 5 | **어드밴스 · 특수 소환 절차가 없다** | `legal_actions` 가 소환 행동을 0건 제시 | 두 관문을 통과하는 31건 중 다수가 그 때문에 사건을 못 만든다 (6-H §10) |
| 6 | **`engine.timing` 은 여전히 아무도 안 쓴다** | importer 0곳 | 체인 삽입 · SEGOC 가 거기 있고, 자동 발동의 다음 칸이다 |
| 7 | **`UNCHECKED_RULES` 6개** | 타이밍 창 · WHEN/IF · spell speed · 턴 1회 · SEGOC · 체인 삽입 | `RULES_SATISFIED` 조차 도달 불가인 까닭 |
| 8 | **복수 카드 사건** (STRUCTURAL-35) | `TimingEvent` 가 주체 한 장만 | 6-H 가 측정한 84건이 계속 보류 |

**§13 이 열거한 항목 중 이번에 고친 것은 둘**이다 —
"EffectDefinition 과 TriggerSpec 의 식별 관계 부족" (실은 **부족하지
않았다**: §1) 과 "TriggerRegistry 생산 경로 미연결" (§2 → §6). 나머지는
실제 통합을 막지 않았으므로 손대지 않았다 (§13 의 지시).

STRUCTURAL-15 · 34 · 35 · 36 · 77 은 **직접적인 차단 요인이 아니었으므로
수정하지 않았다.**

---

## 16. 다음 단계에서 실제 효과 실행까지 필요한 최소 작업

§9.1 의 표가 순서를 정한다 — **남은 세 관문이 전부 같은 하나를 기다린다.**

1. **`EffectRef(71703785, 0)` 의 `EffectDefinition` 을 손으로 등록한다**
   (ADR-006 의 손 등록 · ADR-004 의 출처 검증을 지나서). 그것 하나로
   `trigger_condition` · `execution_authority` · `cost_feasibility` 가
   동시에 답을 갖고, `stage` 가 `RULES_SATISFIED` 까지 올라간다.
   효과 내용은 「이 카드를 패에서 특수 소환한다」이고 특수 소환 절차는
   §15 금지에 걸리므로, **발동 가능성 판정까지**가 경계다.
2. **타이밍 창** — 「~했을 때」(WHEN) 와 「~했을 경우」(IF) 의 구분과 놓친
   타이밍. `UNCHECKED_RULES` 의 첫 두 항목이고, 이것 없이는
   `fully_checked` 가 참이 될 수 없어 `EXECUTION_READY` 에 닿지 못한다.
3. **`engine.timing` 을 펴는 자리** — 체인 삽입과 SEGOC. 그때가
   `Duel` 이 등록소를 들고 있어야 하는 시점이고 (§5 의 대안 B),
   `test_12` 를 움직일 **이유**도 그때 생긴다.
4. 그 다음이 **일반 드로우의 사건화** (§15-4) 와 **소환 절차** (§15-5) 다.
   둘은 "반응할 수 있는 사건의 종류" 를 늘리는 일이고, 판정 정확성과
   독립이다.

🔴 **1 → 2 → 3 의 순서를 바꾸면 안 된다.** 3 을 먼저 하면 정의가 없는
4,173건이 전부 `UNKNOWN` 후보로 체인 계층에 들어가고, 그 모름을 어디서
막을지가 다시 문제가 된다. 정의가 하나라도 있는 상태에서 연결하면 **그
하나로 경로 전체를 검증**할 수 있다 — `test_09` 가 이미 그 형태다.

---

## 17. Git 커밋 및 푸시 결과

브랜치: `claude/pensive-goodall-te1egy` (기존 커밋 rewrite · amend · force
push 없음 · 새 브랜치 없음 · PR 없음)

| 커밋 | 내용 |
|---|---|
| `b27d2c0` | 조립도를 펴는 사람을 만든다 (`integration/` 2파일 · `engine/trigger_observation.py`) |
| `453c111` | 수직 통합 테스트 26개 + 움직인 감사 열셋 |
| (이 보고서) | `docs/phase6i-trigger-duel-production-integration.md` |

푸시: `60795c6..453c111` → `origin/claude/pensive-goodall-te1egy` (성공),
그리고 이 보고서 커밋.

---

## 부록 A — §15 금지 목록 대조

새 듀얼 엔진 · `GameState` 재설계 · 트리거 처리 계층 중복 구현 · 자동 TRIGGER
발동 · 자동 체인 링크 · 효과 해결 확장 · 모든 카드 효과 실행 구현 · 소환 절차 ·
ComboPlanner 실행 연결 · Discord 명령어 · 금지·제한 리스트 · Duel Simulator ·
EDOPro · AI 전략 추론 · Lua 파일 이동·삭제 · 카드 데이터 재생성 · 관련 없는
TODO 일괄 수정 — **하나도 하지 않았다.**

수집도 판정도 다시 짜지 않았다. `EventPipeline` · `TriggerCollector` ·
`TriggerEligibilityJudge` 를 그대로 쓴다 (§3-12).

카드 ID · 카드명 하드코딩: production 코드에 **없다.** 테스트의 대표 사례
상수는 측정으로 고른 것이고, 특정 카드를 위한 분기는 없다 (§11 의 마지막 금지).

## 부록 B — §18 완료 기준 대조

| # | 기준 | 결과 |
|---|---|---|
| 1 | 식별 관계 확인 및 안전한 연결 범위 명시 | §1 · §8 — 식별자가 같고, 연결 가능 범위는 **0건**이며 그 까닭이 서로소임 |
| 2 | TriggerRegistry 를 실제 Duel 실행 경로에서 쓸 수 있게 최소 통합 | §6 · §7 — `integration` + `engine/trigger_observation` |
| 3 | 실제 `PlayerAction` 사건에서 등록 조회 | `test_05`·`test_08`·`test_09` |
| 4 | 기존 Collector·Judge 로 후보 검증 | 같음 — 둘 다 그대로 쓴다 |
| 5 | 등록·사건 일치·조건·실행 가능을 구분 | `ObservationStage` 다섯 값 + `has_definition`/`is_executable` 두 칸 |
| 6 | 미확인을 발동 가능·실행 완료로 잘못 표시하지 않음 | `test_13`·`14`·`15`·`16` |
| 7 | 관찰이 상태·체인·우선권·기록을 바꾸지 않음 | §14 — `test_17`·`18`·`21` |
| 8 | 복수 인스턴스·복수 Duel 구분 | §11 — `test_10`·`test_19` |
| 9 | 관련 회귀 통과 | §13.5 — 5,867 passed · 4 skipped · 0 failed |
| 10 | 최소 수직 통합 테스트와 남은 장애물 문서화 | §9.1 · §15 · §16 |

**다음 Phase 는 자동으로 시작하지 않는다.** 사용자 검토를 기다린다.
