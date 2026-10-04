# Phase 3-E-27 — Trigger UNKNOWN Reason Semantics Audit

- 검증한 HEAD: `3e23444` (Phase 3-E-26) — `git rev-parse HEAD` 로 확인, 작업본 깨끗
- 성격: **감사 먼저, 최소 수정 나중.** 감사 중에는 코드를 고치지 않았다
- 판정: **MINIMAL FIX** — 네 자리의 분류 코드만 고쳤다

## 1. 감사 — 조건 계층은 이미 답을 알고 있었다

고치기 전에 실제 저장소 동작을 측정했다 (`ConditionEvaluator` 와
`Condition.missing_rules` 를 직접 불러서).

| 사례 | `ConditionResult` | `missing_rules()` | `unknown_reasons` |
|---|---|---|---|
| A 상대 뒷면 카드의 정체 | `unknown` | **`()`** | `('#8 는 뒷면이라 정체를 모름',)` |
| A' 관측 밖의 카드 | `unknown` | **`()`** | `('#9999 가 관측에 보이지 않음 …',)` |
| B `UnimplementedRule` | `unknown` | **`('체인 위의 카드 수',)`** | `('규칙 미구현: …',)` |
| C `Always(FALSE)` | `false` | `()` | `()` |
| D 미구현 AND 가려짐 | `unknown` | **`('체인 위의 카드 수',)`** | 둘 다 남는다 |
| D' 순서 반대 | `unknown` | **`('체인 위의 카드 수',)`** | 둘 다 남는다 |
| E 조건 없음 | `all_of([]) is TRUE` | — | — |

**결론: 구분은 이미 가능하다.** `missing_rules()` 가 A/A' 에서는 비어 있고 B
에서는 규칙 이름을 준다. 트리거 계층은 그것을 **묻지 않고 있었을 뿐**이다.

그리고 D·D' 가 같은 답을 준다 — `And.missing_rules` 가 자식 순서와 무관하게
규칙을 모은다. 즉 **우선순위를 지어낼 필요가 없다.** 저장소가 이미 정했다.

## 2. 네 자리의 수정 전/후

| # | 위치 | 가진 정보 | 수정 전 | 수정 후 |
|---|---|---|---|---|
| 1 | `TriggerCollector._judge` 조건 UNKNOWN | `self._view` · `context` · `conditions` → **`missing_rules` 호출 가능** | 언제나 `INFORMATION_UNAVAILABLE` | A→정보 / B→**규칙** |
| 2 | `TriggerEligibilityJudge._trigger_condition` UNKNOWN | 같음 + `GateVerdict` 가 `ValidationResult` 를 싣는다 → **`missing_rule` 까지 가능** | 언제나 `INFORMATION_UNAVAILABLE`, `missing_rule=None` | A→정보 / B→**규칙 + 규칙 이름** |
| 3 | `TriggerChainIntegrator._undecided` | **조건 객체가 없다** (다시 평가하지 않는 계층) — 막힌 관문의 코드만 있다 | 언제나 `INFORMATION_UNAVAILABLE` | 막힌 **UNKNOWN 관문**의 코드 |
| 4 | `TriggerChainIntegrator._refused` | 같음 | 언제나 `RULE_NOT_IMPLEMENTED` | 막힌 **INVALID 관문**의 코드 |

### 4번은 이번에 새로 찾았다

`_refused` 는 **확실한 거부**(`ChainInsertion.NOT_INSERTABLE`)에
`RULE_NOT_IMPLEMENTED` 를 적고 있었다. 3-E-26 이 `trigger.py` 에서 고친 것과
**같은 결함**인데 그때 놓쳤다 — 3-E-26 의 측정(`test_11`)이
`ActionValidity.INVALID` · `CONDITION_FALSE` · `INELIGIBLE` 만 찾고
`ChainInsertion.NOT_INSERTABLE` 을 보지 않았기 때문이다.

측정된 영향: 자리가 틀려 막힌 후보가 `rule_not_implemented` 로 보고되고
있었다. 수정 후 `source_wrong_zone` 이다.

## 3. 사례별 수정 후 결과 (네 자리 전부 실측)

| 사례 | site 1 후보 | site 2 관문 | site 3·4 삽입 |
|---|---|---|---|
| A 가려진 정체 | `unknown` / `information_unavailable` | `unknown` / `information_unavailable` / `missing_rule=None` | `unknown` / `information_unavailable` |
| A' 관측 밖 | `unknown` / `information_unavailable` | 같음 | 같음 |
| B 미구현 규칙 | `unknown` / **`rule_not_implemented`** | `unknown` / **`rule_not_implemented`** / **`missing_rule='체인 위의 카드 수'`** | `unknown` / **`rule_not_implemented`** |
| C 거짓 | `ineligible` / `candidate_not_eligible` | `invalid` / `candidate_not_eligible` | `not_insertable` / **`candidate_not_eligible`** |
| D 둘 다 | `unknown` / `rule_not_implemented` (순서 무관) | 같음 | 같음 |
| E 조건 없음 | `eligible` / `ok` | `valid` / `ok` | `insertable` / `ok` |
| 자리 위반 | — | `invalid` / `source_wrong_zone` | `not_insertable` / **`source_wrong_zone`** |

**E 가 조건 metadata 부재만으로 UNKNOWN 이 되지 않는다** — 조건 관문은
`VALID`/`OK` 다. (전체 판정이 UNKNOWN 이 되는 경우가 있는데, 그것은 **다른**
관문 때문이다: 정의가 등록되지 않았으면 `_execution_authority` 가
`RULE_NOT_IMPLEMENTED` 로 UNKNOWN 이다 — ADR-006 의 올바른 동작이다.)

## 4. §12 우선순위를 지어내지 않았다 (CASE D)

규칙도 없고 정보도 없을 때 어느 쪽을 말하는가. **저장소에서 읽었다.**

- `engine/action_validation.py` `_check_requirements`: 빠진 규칙이 하나라도
  있으면 `RULE_NOT_IMPLEMENTED` 를 쓴다.
- `engine/condition/model.py` `And.missing_rules`: 자식 순서와 무관하게 모은다.

→ **"규칙이 없다" 가 "정보가 없다" 를 이긴다.** `test_07` 이 조건 순서를
바꿔도 같은 답이 나오는 것으로 이것을 지킨다 (지어낸 우선순위라면 순서에
따라 답이 흔들릴 것이다).

## 5. Production Path — dormant 확인 (3-E-26 의 내 서술을 고친다)

`engine/duel.py` 에서 import 전이 폐쇄를 AST 로 구했다.

| 모듈 | 정론 경로 도달 |
|---|---|
| `engine/trigger.py` | **그렇다** |
| `engine/trigger_chain.py` | 아니다 |
| `engine/trigger_order.py` | 아니다 |
| `engine/timing.py` | 아니다 |
| `engine/event_pipeline.py` | 아니다 |

> **3-E-26 보고서를 고친다.** 그 보고서는 "`engine/duel.py` 가
> `engine.trigger` 를 import 하지 않는다" 고 적었다. **직접** import 는 하지
> 않지만 **전이적으로는 닿는다**: `duel.py` → `activation_timing.py` →
> `trigger.py`. 그래서 "dormant" 의 근거를 다시 세웠다.

다시 세운 근거 — `activation_timing.py` 가 `trigger.py` 에서 가져오는 것은
**`TimingPoint` 하나**(열거형)뿐이고, 쓰는 자리도 `point: TimingPoint | None`
필드 선언 한 곳이다. 이번에 고친 네 자리가 들어 있는 클래스들은:

| 클래스 | production 생성 자리 | 정론 경로 도달 |
|---|---|---|
| `TriggerCollector` | `trigger_chain.py` · `timing.py` · `event_pipeline.py` | **아니다** |
| `TriggerEligibilityJudge` | `trigger_chain.py` | **아니다** |
| `TriggerChainIntegrator` | `timing.py` | **아니다** |

→ **네 자리 모두 dormant.** 정론 경로
(`legal_actions` → `PlayerAction` → `apply` → `EffectActivator` → `ChainLink`)
는 이 코드를 부르지 않는다. 그래서 이번 수정은 **production 동작을 바꾸지
않는다.**

### §5 와 §6 의 긴장 — 어떻게 판단했는가

- §6 은 "production engine code 를 고치려면 **실제 production 경로가 영향을
  받아야 한다**" 고 한다. 조건 1 은 **불성립**이다.
- §5 는 "트리거 계층의 구분이 test-only 거나 dormant 라면 … **분명히 안전하고
  유용할 때는 국소 분류 코드만 고쳐라**" 고 한다. 이쪽은 성립한다.

둘이 충돌한다. §5 가 **이 상황을 직접 지목한** 더 구체적인 지시이고, §6 이
막으려는 것(아키텍처 변경)은 하지 않았으므로 §5 를 따랐다. 판단 근거를 여기
남기니, 다르게 보신다면 되돌리기 쉽다 (`engine/trigger.py` ·
`engine/trigger_chain.py` 두 파일뿐이다).

§13 의 선택지 C("dormant 아키텍처가 안전하게 구현할 **context 가 부족하다**")는
**측정이 부정한다** — §1 이 보인 대로 site 1·2 에는 `missing_rules()` 가 바로
있고, site 3·4 에는 관문의 코드가 바로 있다.

## 6. 새 어휘 없음 · 새 필드 없음

| 금지 | 지켰는가 |
|---|---|
| 새 `ValidationCode` | 그렇다 — 48개 그대로 |
| 새 Status enum | 그렇다 — `TriggerStatus` 4 · `ActionValidity` 3 · `ChainInsertion` 3 |
| 새 subsystem | 그렇다 |
| 새 dataclass 필드 | 그렇다 — `_gate()` 에 붙인 `missing_rule` 은 **`ValidationResult` 가 이미 가진 필드**를 실어 보내는 인자다 |

`TriggerCandidate` 와 `TriggerChainEntry` 에는 `missing_rule` 필드가 없다.
**만들지 않았다** — 규칙 이름이 이미 `notes` 에 (`"규칙 미구현: …"`) 그대로
실려 있어 잃는 정보가 없다. 감사 소견으로만 적는다.

## 7. 관측 경계 — 누출 없음

`missing_rules(view, context)` 는 평가가 받은 것과 **같은 `GameStateView`** 를
받는다. 새 관측을 열지 않았다.

측정한 경계: 상대의 뒷면 세트 카드는 보는 쪽에게 `card_id` 조차 `None` 이고,
주인 쪽에서는 `1001` 이다. (`definition` 은 양쪽 다 `None` 인데, 그것은
관측이 아니라 ADR-006 의 등록 사실이다 — 처음에 나는 주인 쪽에서 `definition`
이 보일 것이라고 **틀리게 가정했고**, 측정해서 고쳤다.)

`test_11` 이 세 가지를 지킨다.

1. 경계가 살아 있다 (보는 쪽은 `card_id` 를 못 본다).
2. 가려진 정체가 `reason` · `notes` 로 **새지 않는다.**
3. 가려진 사실에서 **규칙 이름을 지어내지 않는다** (`missing_rules() == ()`,
   `missing_rule is None`).

## 8. AI / Search 영향 — 전부 0

`agent/` 아래 어떤 파일도 고치지 않았다 (`git diff --name-only` 로 확인).
그리고 영향이 없는 **구조적** 이유가 있다.

- 네 자리가 dormant 이므로 `DuelStep.code` 에 닿지 않는다 (§5).
- 닿더라도 `agent/simulation.py` 의 `_UNKNOWN_CODES` 는
  `RULE_NOT_IMPLEMENTED` 와 `INFORMATION_UNAVAILABLE` 을 **둘 다** 품고 있어
  `SimulationStatus` 분류가 같다 (3-E-26 측정, 이번에도 유효).
- `agent/search.py` 는 `UNKNOWN` 에 **점수를 주지 않는다** — 0점도 최저점도
  아니다. 이번 수정이 `UNKNOWN` 을 만들거나 없애지 않았으므로 순위도 그대로다.

| 항목 | 변화 |
|---|---|
| Evaluation | **0** |
| Search ranking | **0** |
| Candidate generation | **0** |

## 9. 테스트

`tests/test_trigger_unknown_reason.py` — **13개 신규.**

| # | 보는 것 |
|---|---|
| 01 | 가려진 정체 → `INFORMATION_UNAVAILABLE` (판이 바뀌면 풀리는 까닭) |
| 02 | 관측 밖의 카드 → `INFORMATION_UNAVAILABLE` |
| 03 | `UnimplementedRule` → `RULE_NOT_IMPLEMENTED`, 정보 쪽 아님 |
| 04 | 관문이 `missing_rule` 까지 싣는다 / 정보 쪽은 `None` (빈 칸을 지어내지 않는다) |
| 05 | 거짓은 **절대** UNKNOWN 이 되지 않는다 |
| 06 | 조건 없음은 모름이 아니다 |
| 07 | D — 순서를 바꿔도 같은 답 (**우선순위를 지어내지 않았다는 증거**) |
| 08 | 체인 계층이 관문의 까닭을 올린다 (규칙/정보 양쪽) |
| 09 | `_refused` 가 거부를 "미구현" 으로 부르지 않는다 |
| 10 | `UNKNOWN` 관문이 섞여 있어도 거부의 이름을 가져가지 않는다 |
| 10b | **검사 순서가 아니라 판정으로 고른다** — 모름 관문이 **먼저** 막힌 판 |
| 11 | 관측 경계 · 누출 없음 · 가려진 사실에서 규칙 이름을 짓지 않음 |
| 12 | 새 어휘 없음 (48 · 3 · 4 · 3) |

`tests/engine/test_trigger.py` — **1개 신규**
(`test_a_hidden_fact_makes_the_candidate_unknown_for_a_different_reason`):
갈래의 가려진 정보 쪽을 같은 파일에서 잠근다.

### 기존 테스트 갱신 4개 — 삭제 · skip · 약화 **없음**

넷 다 **같은 잘못된 가정**이다: `UnimplementedRule` 을 걸어 놓고
"`UNKNOWN` 의 코드는 `INFORMATION_UNAVAILABLE`" 이라고 단정했다. 걸린 조건의
까닭은 **규칙이 없어서**이고, `INFORMATION_UNAVAILABLE` 의 docstring 은 원인을
"가려진 카드 · 읽을 수 없는 카드 정의" 로 열거한다 — 전부 정보 쪽이다.
3-E-24 가 세운 `MISSING_RULE ≠ HIDDEN_INFORMATION` 을 네 테스트가 뭉개고
있었다. (3-E-26 이 `test_effect_execution.py` 에서 고친 것과 **똑같은** 가정이다.)

| 파일 | 테스트 | 바꾼 것 |
|---|---|---|
| `tests/engine/test_trigger.py` | `test_an_unjudgeable_condition_is_unknown_not_ineligible` | `RULE_NOT_IMPLEMENTED` 단정 + `is not INFORMATION_UNAVAILABLE` **추가** |
| `tests/engine/test_trigger_eligibility.py` | 같은 이름 | 위 + `missing_rule == '체인 위의 카드 수'` **추가** |
| `tests/engine/test_trigger_chain.py` | `test_an_unknown_trigger_is_kept_apart_and_not_called_absent` | 위와 같음 |
| `tests/engine/test_timing_priority.py` | `test_an_unknown_trigger_is_preserved_not_turned_into_ineligible` | 위와 같음 |

단정은 **늘었고 좁아졌다.** 지운 단정은 없다.

### 회귀

| 항목 | 값 |
|---|---|
| 3-E-26 기준선 | 3655 passed · 4 skipped · 0 failed |
| 이번 | **3669 passed · 4 skipped · 0 failed** (395s) |
| 차 | +14 = 신규 13 + 1. 잃은 테스트 0 · 새 skip 0 · **회귀 0** |

테스트 수가 늘었다는 것만으로 개선이라고 주장하지 않는다 — 아래 고의 위반이
근거다.

## 10. 고의 위반 검증 — 9개

전부 커밋 후 주입 → 확인 → `git checkout` 복구.

| 주입 | 되돌린 것 | 잡혔는가 |
|---|---|---|
| A | site 1 의 갈래 제거 | 3개 실패 ✅ |
| B | site 2 의 갈래 제거 | 5개 실패 ✅ |
| C | site 2 의 `missing_rule` 전달 제거 | 2개 실패 ✅ |
| D | site 3 하드코딩 복귀 | 3개 실패 ✅ |
| E | site 4 하드코딩 복귀 | 2개 실패 ✅ |
| F | `_refusal_code` 가 UNKNOWN 관문도 보게 | **처음엔 안 잡혔다** → 아래 |
| G | D 우선순위 뒤집기 | 3개 실패 ✅ |
| H | UNKNOWN → INELIGIBLE (최상위 불변식) | 8개 실패 ✅ |

### 주입 F 가 처음에 안 잡힌 것 — 테스트의 결함

`test_10` 은 "패의 사본이 `SOURCE_WRONG_ZONE` 을 받는다" 를 봤다. 그런데 그
판에서는 `INVALID` 관문(`activation_zone`)이 `UNKNOWN` 관문
(`trigger_condition`)보다 **먼저** 오기 때문에, "처음 막힌 관문" 으로 골라도
같은 답이 나온다. 즉 **판정으로 고르는지 순서로 고르는지를 구분하지 못하는
테스트**였다.

구분되는 판을 만들었다: `activates_from` 을 적지 않아 자리 관문이
`UNKNOWN`(`RULE_NOT_IMPLEMENTED`)이고 조건 관문이
`INVALID`(`CANDIDATE_NOT_ELIGIBLE`)인 모양 — **모름이 먼저 막힌다.**
`test_10b` 가 그것을 잠그고, 전제(`blocking` 안의 순서)까지 테스트가 직접
확인한다. 다시 주입하니 F 도 잡힌다.

### 또 하나 — 내 첫 구현이 틀렸다

처음에는 `_blocking_code` 하나로 두 자리를 다 처리하면서 "빠진 규칙이 이긴다"
를 **거부에도** 적용했다. 측정해 보니 자리에서 막힌 후보가
`rule_not_implemented` 로 보고됐다 — 고치려던 결함을 그대로 재현한 것이다.
`_refusal_code`(INVALID 관문만) 와 `_undecided_code`(UNKNOWN 관문만) 로
쪼개서 고쳤다. "규칙이 이긴다" 는 **모름 안에서만** 맞는 말이다.

## 11. STRUCTURAL TODO

**신규 STRUCTURAL ID 없음.**

`STRUCTURAL-31 / -32 / -33 / -34 / -124 / -128 / -131 / -133` 전부 유지 ·
영향 없음.

감사 소견으로만 적는 것 (§12 기준 1 불성립 — 잃는 정보가 없어 미래의
아키텍처 문제가 아니다):

- `TriggerCandidate` · `TriggerChainEntry` 에 `missing_rule` 필드가 없다.
  규칙 이름은 `notes` 가 그대로 전하므로 지금 잃는 것이 없다.
- `TriggerChainIntegrator` 는 조건을 다시 평가하지 않는다 — 그것이 설계이고,
  그래서 관문의 코드를 올리는 것이 이 계층의 정답이다.

## 12. 최종 판정 — **MINIMAL FIX**

트리거 계층의 `UNKNOWN` 은 **정확히 갈릴 수 있었고, 갈랐다.**

- `INFORMATION_UNAVAILABLE` — 판이 바뀌면 풀리는 까닭 (가려짐 · 관측 밖)
- `RULE_NOT_IMPLEMENTED` — 코드가 생겨야 풀리는 까닭 (`UnimplementedRule`)
- `CANDIDATE_NOT_ELIGIBLE` · `SOURCE_WRONG_ZONE` — 확실한 거부, 모름이 아니다

새 enum 0 · 새 필드 0 · 새 subsystem 0 · production 동작 변화 0 ·
AI/Search 변화 0 · 회귀 0.

## 13. 다음 Phase 후보 — **하나만**

### `_judge` 와 관문의 이중 평가 정합성 감사 (Trigger Double-Evaluation Consistency Audit)

- 측정된 사실: `TriggerCollector._judge` 와
  `TriggerEligibilityJudge._trigger_condition` 이 **같은 조건을 각자 한 번씩**
  평가한다. 이번 Phase 가 둘의 **코드**를 맞췄지만, 둘이 서로 다른 답을 낼 수
  있는지는 아직 보지 않았다.
- 볼 것: (a) 두 평가가 같은 `view` · 같은 `ConditionContext` 를 쓰는가 —
  `_judge` 는 `context` 를 `card.controller` 로, 관문은
  `candidate.controller` 로 만든다. 같은 값인지 **측정**한다. (b) 조건이
  판을 읽는 사이에 판이 바뀔 수 있는가. (c) 한 번만 평가하고 결과를 넘기는
  것이 더 안전한지, 아니면 두 계층의 독립성이 의도인지.
- 왜 지금이 아닌가: 이번 Phase 는 §12 범위가 "코드 분류" 였다. 이중 평가는
  성능이 아니라 **정합성** 문제이고, 답이 "한쪽을 없애자" 가 될 수 있어 별도
  감사가 필요하다.
- 왜 다음인가: 트리거 계층을 정론 경로에 잇는 날 **두 평가가 어긋나면 어느
  쪽을 믿을지** 정해야 한다. 잇기 전에 답이 나와 있어야 한다.

**이 Phase 는 여기서 멈춘다. 다음 Phase 는 임의로 진행하지 않는다.**
