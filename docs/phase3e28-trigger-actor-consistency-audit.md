# Phase 3-E-28 — `_judge` / Gate 이중 평가 정합성 감사

- 검증한 HEAD: `734d2be` (Phase 3-E-27) — `git rev-parse HEAD` 로 확인, 작업본 깨끗
- 성격: **감사.** production code 를 한 줄도 고치지 않았다
- 판정: **AUDIT-ONLY** (불일치 없음 + 감사 소견 1건)

## 0. 먼저 요청서의 전제 하나를 고친다

요청서는 `TriggerEligibilityJudge._judge` 라고 적는다. **그런 메서드는 없다.**

| 이름 | 실제 소속 | 줄 |
|---|---|---|
| `_judge` | **`TriggerCollector`** | `engine/trigger.py:894` (클래스 775) |
| `_trigger_condition` 등 관문 | `TriggerEligibilityJudge` | `engine/trigger.py:1216~` |

즉 "두 계층" 은 `TriggerEligibilityJudge` 안의 두 메서드가 아니라 **서로 다른
두 클래스**다. 비교 대상을 잘못 잡으면 결론도 틀리므로 먼저 바로잡는다.

## 1. 핵심 측정 — 같은 뜻이 아니라 **같은 값**이다

요청서의 걱정은 "`_judge` 는 `card.controller`, 관문은 `candidate.controller`
— 같은 뜻인가" 였다. **이름이 아니라 대입 사슬을 봤다.**

```python
# engine/trigger.py:894  TriggerCollector._judge
base = {
    "source": card.instance_id,
    "controller": card.controller,      # ← 여기서 들어간다
    ...
}
return TriggerCandidate(**base, ...)

# engine/trigger.py:1399  TriggerEligibilityJudge._trigger_condition
context = ConditionContext(
    player=candidate.controller,        # ← 위에서 들어간 그 값
    source=candidate.source,
    effect_ref=spec.effect_ref,
)
```

`candidate.controller` **는** `card.controller` 다 — 같은 뜻이기 때문이 아니라
**직접 대입**이기 때문이다. 실측으로도 확인했다 (양쪽 플레이어의 카드 전부):

| 후보 | `candidate.controller` | 관측의 `card.controller` | zone |
|---|---|---|---|
| `#0` | 0 | 0 | MZONE |
| `#1` | 0 | 0 | HAND |
| `#7` | **1** | **1** | MZONE |

마지막 줄이 중요하다 — **상대가 쥔 카드도 후보가 되고, 주체가 1 로 제대로
잡힌다.** 한쪽만 보고 "같다" 고 결론내지 않았다.

### 관측도 같은 것을 쓴다

같은 값이어도 **다른 관측**으로 평가하면 답이 갈릴 수 있다.
`TriggerChainIntegrator.collect_and_order` 를 보면 `self._view` 가 **세 번**
나온다 — 수집기 · 판정기 · 정렬기 **전부 같은 `GameStateView` 객체**를 받는다.

## 2. §3 Controller / Actor Semantics — 실측표

`ConditionContext.player` 는 "이 조건은 **누구의 것인가**" 이고,
`PlayerRef.CONTROLLER` 가 가리키는 쪽이다. **문맥 상대적**이며 (카드 텍스트의
"자신"/"상대"), 절대 번호를 조건에 적지 않는다.

| 계층 | 사용 객체 | `player` 에 넣는 값 | 실제 의미 |
|---|---|---|---|
| `TriggerCollector._judge` | `CardView` | `card.controller` | 그 카드를 **쥔 쪽** |
| `TriggerEligibilityJudge._trigger_condition` | `TriggerCandidate` | `candidate.controller` | **위와 같은 값** |
| `TriggerEligibilityJudge._cost_feasibility` | `TriggerCandidate` | `candidate.controller` | 같음 |
| `ActionValidator.context_for` | `PlayerAction` | **`action.actor`** | 이 행위를 **시도하는 쪽** |
| `EffectActivator._condition_context` | `PlayerAction` | **`action.actor`** | 같음 |
| `CostPaymentContext.condition_context` | 지불 문맥 | `self.payer` | **치르는 쪽** |
| `ResolutionContext.condition_context` | 해결 문맥 | `self.controller` | 해결 중인 효과의 주인 |
| `ObservationGrant` 평가 | `CardView` | `card.controller` | 쥔 쪽 |
| `target_bridge` | 좌석 | `seat` | 보는/고르는 쪽 |

저장소는 세 개념을 **이미 명시적으로** 나눠 두었다
(`engine/action.py` `PlayerAction` docstring):

> `actor` 는 **이 행위를 시도하는 플레이어**다. 카드의 `owner` / `controller`
> 와 다르다. 컨트롤을 빼앗긴 카드로 상대가 공격하는 상황은
> `owner=0, controller=1, actor=1` 로 표현된다 (ADR 문서 §22).

→ **새 소유권 추상을 만들 이유가 없다.** 이미 셋으로 나뉘어 있다.

### 두 계층을 잇는 계약이 이미 코드에 있다

production 은 세 번째 값(`action.actor`)을 쓰는데, 발동 요구가 이것이다:

```python
Requirement(
    ControllerIs(PlayerRef.CONTROLLER, action.source),
    ValidationCode.SOURCE_NOT_CONTROLLED,
    "자신이 쥐고 있는 카드가 아닙니다.",
)
```

`PlayerRef.CONTROLLER.resolve(context)` 는 `context.player` = `action.actor`
다. 즉 **production 은 `actor == card.controller` 를 요구한다** (`_activate`
와 `_activate_effect` 둘 다). 그래서 트리거 계층의 `card.controller` 가 나중에
그대로 올바른 `actor` 가 된다 — 둘을 잇는 규칙이 이미 있고, 이번 Phase 가
만들 것이 없다.

## 3. §4 Double Evaluation Audit — 주체가 틀리면 답이 뒤집히는 조건으로 봤다

`Always(TRUE/FALSE)` 만으로는 주체 불일치가 드러나지 않는다. 그래서
`ControllerIs(자신)` · `ControllerIs(상대)` 를 넣었다 — 주체를 잘못 잡으면
**참/거짓이 반대로 나오는** 조건이다.

| 사례 | `_judge` 결과 | Gate 결과 | 동일/차이 | 이유 |
|---|---|---|---|---|
| 조건 TRUE | `eligible` / `ok` | `valid` / `ok` | **동일** | 같은 값 · 같은 관측 |
| 조건 FALSE | `ineligible` / `candidate_not_eligible` | `invalid` / `candidate_not_eligible` | **동일** | 같음 (3-E-26 이 코드를 맞췄다) |
| 규칙 미구현 | `unknown` / `rule_not_implemented` | `unknown` / `rule_not_implemented` | **동일** | 같음 (3-E-27 이 까닭을 갈랐다) |
| **`ControllerIs(자신)`** | `eligible` / `ok` | `valid` / `ok` | **동일** | **주체가 같다는 직접 증거** |
| **`ControllerIs(상대)`** | `ineligible` / `candidate_not_eligible` | `invalid` / `candidate_not_eligible` | **동일** | 같음 |

→ **A. SAME.** 다섯 모양 전부에서 `code` 가 같고, 주체 민감 조건에서도 같다.

### 의도된 차이는 따로 있다 (§5 — 조건과 관문을 섞지 않는다)

수집기와 판정기가 **같은 후보에 다른 상태**를 주는 경우가 있고, 그것은 모순이
아니다. 수집기는 "타이밍이 맞고 조건이 참인가" 까지만 보고, 판정기는 자리 ·
실행 권위 · 비용을 더한다.

실측: 정의를 등록하지 않은 후보는 `_judge` → `ELIGIBLE`,
`TriggerEligibility` → `UNKNOWN` (`EXECUTION_AUTHORITY` 관문이
`RULE_NOT_IMPLEMENTED`, ADR-006). **조건 관문은 통과했다** — 어긋난 것이
아니라 다른 질문이다. `TriggerCandidate.status` 의 docstring 이 "합친 결과는
이 값과 **다를 수 있다**" 고 미리 적어 둔다. → **B. DIFFERENT BUT
INTENTIONAL.**

## 4. §6 Controller edge case — 표현 가능한 것만 시험했다

| # | 사례 | 표현 가능 | 근거 |
|---|---|---|---|
| 1 | controller=P0, turn=P0 | **가능** | 기본 판 |
| 2 | controller=P0, turn=P1 | **가능** | `begin_next_turn()` 후에도 후보의 주체는 그대로 (실측) |
| 3 | `candidate.controller` ≠ `card.controller` | **불가 (production)** | 아래 |
| 4 | 트리거 source ≠ 발동 플레이어 | **불가** | Candidate→PlayerAction 번역기가 없다 (3-E-22) |
| 5 | 상대가 쥔 카드가 **그 쪽을 위해** 트리거 | **가능** | 후보 `#7` 의 controller=1, `ControllerIs(자신)` 이 **양쪽에서 참** |
| 6 | 비턴 플레이어의 응답 | **가능** | `_activate` 는 "**누구 턴인지 묻지 않는다**" (함정·퀵 효과가 정상이므로) |

### 3번이 왜 불가인가 — 지속적 컨트롤 변경이 유지되지 않는다

| 사실 | 측정 |
|---|---|
| `CardInstance.set_controller` 가 **있다** | `engine/state/card_instance.py:168` |
| 그런데 **아무도 부르지 않는다** | 저장소 전체에서 호출 0건 |
| 존을 재색인할 때마다 덮어쓴다 | `ZoneContainer._reindex` · `_rebuild_from_slots` → `card.controller = self.owner` |

실제로 해 봤다: `set_controller(1)` → `controller == 1` 이 되지만, 같은 존에
카드 하나를 더 놓자 **`controller == 0` 으로 돌아갔다.**

즉 카드의 `controller` 는 지금 엔진에서 **항상 그 카드가 든 존의 주인**이다.
`candidate.controller` 가 관측과 어긋나는 상태를 production API 로 만들 길이
없다. **없는 기반을 만들지 않았다** — 표현 불가로 기록만 한다.

## 5. 감사 소견 — 고치지 않은 것 하나

`judge()` 는 후보와 선언이 다른 효과를 가리키면 `TriggerError` 를 던진다.
그런데 **`controller` · `source` 가 관측과 어긋나는지는 확인하지 않는다.**

손으로 만든 후보로 어긋나게 해 봤다 (`controller=1`, 관측은 0):

| 관문 | 무엇으로 평가했는가 | 결과 |
|---|---|---|
| `TRIGGER_CONDITION` | **후보가 준** `controller` | `invalid` / `candidate_not_eligible` |
| `ACTIVATION_ZONE` | **관측의** 카드 | `valid` / `ok` |

→ 한 번의 `judge()` 안에서 두 관문이 **서로 다른 전제**를 썼고, 예외도 나지
않았다.

### 그런데 production 에서는 닿지 않는다

| 조건 (§9) | 충족 |
|---|---|
| 1. production 에서 닿는가 | **아니다** — 같은 관측 배선 · 컨트롤 변경 표현 불가 · 트리거 계층 잠듦 |
| 2. 두 계층이 일치해야 하는가 | 그렇다 (한 판정 안에서는) |
| 3. 현재 동작이 증명 가능하게 틀렸는가 | **아니다** — 그 상태를 만드는 production 경로가 없다 |
| 4. 올바른 값이 이미 있는가 | 그렇다 (`view.find(candidate.source).controller`) |
| 5. 국소 수정인가 | 그렇다 (`effect_ref` 검사 옆에 한 줄) |
| 6. 새 subsystem 필요 없는가 | 그렇다 |

조건 1·3 불성립 → **고치지 않는다.** 3-E-27 과 달리 이번 요청서에는 dormant
코드를 고쳐도 된다는 §5 류의 예외 조항이 **없다**. 요청서가 명시한 대로 따랐다:

> If the mismatch exists only in dormant trigger infrastructure:
> do not force production integration.

대신 **지금 동작을 테스트로 그대로 고정**했다 (`test_09`) — 트리거 계층을 이을
때 이 자리가 먼저 보이도록.

## 6. §7 Production Path

| 대상 | 상태 |
|---|---|
| `TriggerCollector._judge` | **dormant** |
| `TriggerEligibilityJudge` 관문 | **dormant** |
| `ActionValidator` (production gate) | **production** |
| `EffectActivator` | **production** |
| 정론 `PlayerAction` 경로 영향 | **없음** |

HEAD 에서 다시 측정했다. `engine/duel.py` 의 import 전이 폐쇄에
`engine.trigger` 는 들어 있지만 (`activation_timing` 이 `TimingPoint` 열거형
하나를 쓴다), 두 계층을 **생성하는** 모듈
(`trigger_chain` · `timing` · `event_pipeline`) 은 **들어 있지 않다.**

즉 이번 감사의 어떤 발견도 production blocker 가 아니다.

## 7. §5 / §7 UNKNOWN · Validation Semantics 보존

| 불변식 | 유지 | 근거 |
|---|---|---|
| `UNKNOWN ≠ FALSE` | 그렇다 | `UnimplementedRule` 후보는 `UNKNOWN`, `Always(FALSE)` 만 `INELIGIBLE` |
| `INFORMATION_UNAVAILABLE ≠ RULE_NOT_IMPLEMENTED` | 그렇다 | 3-E-27 의 갈래가 그대로 (전체 회귀 통과) |
| `INVALID ≠ EXECUTION_FORBIDDEN` | 그렇다 | `GateVerdict.forbids` 가 코드로 판단 (3-E-26) |
| `missing_rule` 의미 | 그렇다 | 관문이 규칙 이름을 싣고, 정보 쪽은 `None` |
| 조건 평가 ≠ 행위 적법성 | 그렇다 | `test_05` 가 의도된 차이를 고정 |

이번 Phase 가 production 을 고치지 않았으므로 바뀔 여지도 없었고, 전체 회귀가
그것을 확인한다.

## 8. §10 Hidden Information

**누출 없음. `GameStateView` 경계 변경 없음. controller 를 추측한 자리 없음.**

`controller` 는 뒷면 카드도 **공개 정보**다 — 실측: 상대의 뒷면 세트 카드에
대해 `controller == 1`, `zone == SZONE` 은 보이고 `card_id` · `definition` 은
`None` 이다. 그래서 `ControllerIs` 가 "**정체를 몰라도** 판정할 수 있다"
(그 클래스의 docstring 이 그렇게 적는다). 가려진 것을 추측할 필요가 애초에
없는 구조다.

## 9. §11 AI / Search 영향 — 전부 변화 없음

| 항목 | 변화 |
|---|---|
| Evaluation (`agent/evaluation.py`) | **없음** |
| Search ranking (`agent/search.py` · `SearchPolicy`) | **없음** |
| Candidate generation | **없음** |
| Simulation (`agent/simulation.py`) | **없음** |

근거는 측정이 아니라 **구조적 사실**이다: 이번 Phase 의 변경 파일은
`tests/test_trigger_actor_consistency.py` **하나**뿐이다 (`git status` 로 확인).
production code 가 바뀌지 않았으므로 Search 가 숨은 controller 를 추론할
새로운 길도 생기지 않았다.

## 10. §12 테스트

`tests/test_trigger_actor_consistency.py` — **17개 신규. 기존 테스트 수정 0.**

| # | 보는 것 | §12 범주 |
|---|---|---|
| 01 | 후보의 `controller` 가 관측의 `card.controller` 와 같다 (**양쪽 플레이어 모두**) | 1 |
| 02 | 그것이 우연이 아니라 **대입**임을 원본에서 확인 | 1 |
| 03 | 세 계층이 **같은 `GameStateView` 객체**를 받는다 | 1 |
| 04 | 다섯 조건 모양에서 두 계층이 일치 (`ControllerIs` 포함, parametrize 5건) | 1 |
| 05 | 수집기와 판정기는 **다른 질문**에 답한다 (의도된 차이) | 2 |
| 06 | 상대가 쥔 카드는 **그 쪽 주체로** 판정된다 | 5 |
| 07 | 턴 플레이어는 조건의 주체가 **아니다** | 3 |
| 08 | 지속적 컨트롤 변경이 **표현 불가**임을 기록 (호출 0건 + 덮어쓰기 실측) | 4 |
| 09 | `judge()` 가 `effect_ref` 는 막고 `controller` 는 막지 않는다 (**감사 소견 고정**) | 4 |
| 10 | production 은 `action.actor` 를 쓰고 `actor == controller` 를 요구한다 | 7 |
| 11 | 두 계층이 정론 경로에서 **잠들어 있다** | — |
| 12 | `owner` · `controller` · `actor` 가 이미 나뉘어 있다 | — |
| 13 | 관측 경계 그대로 — `controller` 는 뒷면도 공개 정보 | 8 |

### 회귀

| 항목 | 값 |
|---|---|
| 3-E-27 기준선 | 3669 passed · 4 skipped · 0 failed |
| 이번 | **3686 passed · 4 skipped · 0 failed** (385s) |
| 차 | +17 = 신규 그대로. 잃은 테스트 0 · 새 skip 0 · **회귀 0** |

테스트 수가 늘었다는 것만으로 개선이라고 주장하지 않는다. production 을 고치지
않았으므로, 이 테스트들의 값은 **계약을 고정하는 힘**에만 있다. 그래서 고의
위반을 넣어 확인했다.

### 고의 위반 검증 — 7개 전부 잡혔다

| 주입 | 깨뜨린 계약 | 잡혔는가 |
|---|---|---|
| A | `_judge` 가 `card.controller` 대신 턴 플레이어를 쓴다 | 4개 실패 ✅ |
| B | 관문이 반대편 주체로 조건을 평가한다 | 5개 실패 ✅ |
| C | 판정기에게 다른 관측을 넘긴다 | 1개 실패 ✅ |
| D | `judge()` 의 `effect_ref` 검사를 없앤다 | 1개 실패 ✅ |
| E | production 에 `set_controller` 호출을 심는다 | 1개 실패 ✅ |
| F | production 검증기가 `actor` 대신 턴 플레이어를 쓴다 | 1개 실패 ✅ |
| G | 발동에서 `ControllerIs` 요구를 뺀다 | 1개 실패 ✅ |

B 가 특히 중요하다 — 주체만 반대로 바꿨을 때 `ControllerIs` 두 사례가 **둘 다**
깨진다. 그것이 `test_04` 가 이름이 아니라 **의미**를 보고 있다는 증거다.

## 11. §10 Structural TODO

- 신규 Structural ID: **없음**
- 기존 TODO 변경: **없음** (`STRUCTURAL-31 / -32 / -33 / -34 / -119 / -124 / -128 / -131 / -133` 유지 · 영향 없음)
- 감사 소견 (ID 없이 기록):
  1. `judge()` 에 `controller`/`source` 정합 검사가 없다 — §5 참조. `test_09` 가 현재 동작을 고정한다.
  2. `CardInstance.set_controller` 는 호출되지 않고, 존 재색인이 덮어쓴다. 컨트롤 변경 규칙을 넣는 날 **같이** 봐야 한다.

§10 기준 1·3 이 불성립이다 — 둘 다 "미래 엔진 정확성에 영향" 이 아니라 "트리거
계층을 이을 때 함께 처리할 일" 이고, 테스트가 이미 지키고 있다.

## 12. 최종 판정 — **AUDIT-ONLY**

`_judge` 와 Gate 가 같은 조건을 **서로 다른 주체로 평가하는 실제 문제는
없다.** 두 값은 대입으로 이어져 있고, 관측도 같은 객체이며, 주체 민감 조건에서
같은 답을 낸다.

production code 변경 0 · 새 enum 0 · 새 subsystem 0 · AI/Search 변화 0 ·
회귀 0 · 신규 STRUCTURAL 0.

## 13. 다음 Phase 후보 — **하나만**

### `TriggerCandidate` → `PlayerAction` 번역 계약 감사 (Candidate-to-Action Contract Audit)

- 측정된 사실: 이번 Phase 가 "`candidate.controller` 가 올바른 미래의
  `actor` 다" 를 확인했다 (production 이 `actor == card.controller` 를
  요구하므로). 그런데 **번역기 자체가 없다** (3-E-22 가 측정).
- 볼 것: (a) `TriggerCandidate` 가 `PlayerAction.activate_effect(actor=,
  source=, effect_ref=)` 를 만드는 데 필요한 것을 **전부** 들고 있는가 —
  `controller`/`source`/`effect_ref` 는 있지만 대상 선택과 비용 영수증은
  `TriggerChainIntegrator._missing_execution_inputs` 가 "이 계층이 갖고 있지
  않다" 고 적는다. (b) 그 둘을 누가 공급해야 하는가. (c) 번역이 어느 계층의
  일인가 — `Duel` · `Timing` · 새 자리 중 어디인지, **구현하지 않고** 판단한다.
- 왜 지금이 아닌가: 이번 Phase 는 "두 계층이 같은 주체를 쓰는가" 라는 닫힌
  질문이었다. 번역 계약은 설계 판단이 필요하고, 잘못 열면 잠든 기반을
  정론 경로에 끌어들이게 된다.
- 왜 다음인가: 주체 문제가 해결됐으므로, 남은 것은 **무엇이 더 있어야
  `PlayerAction` 이 되는가**다. 그것이 트리거 계층과 정론 경로 사이의 마지막
  빈칸이다.

**이 Phase 는 여기서 멈춘다. 다음 Phase 는 임의로 진행하지 않는다.**
