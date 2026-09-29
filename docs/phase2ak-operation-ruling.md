# Phase 2-AK — Operation Ruling Layer (ADR-006)

기준 커밋: `bb7796a` (Phase 2-AJ) · 2871 passed / 4 skipped
→ 이번 단계: **2908 passed / 4 skipped**

```
RuleQuestion              무엇을 묻는가        semantics.py (2-X · 2-AK)
CardRuleFacts             그 카드에 대해 **확인한 것**   ┐
OperationRulingRegistry   확인된 것들의 모음            ├ ruling.py (신규)
BoardRuling               판을 보고 **답을 합성**한다    ┘
```

한 줄 결론: **관문의 구조는 있었고 지식이 없었다.** 지식을 담는 자리를
만들고, 2-W 부터 네 단계 동안 멈춰 있던 실제 카드 한 장을 돌렸다.

> 명세가 §0 중간에서 잘려 들어왔다 (핵심 질문까지 받았다). §1 이후의
> Severity · 금지 목록 · 완료 보고서 형식을 보지 못했으므로, 앞 단계들이
> 쓰던 형식을 그대로 따른다.

---

## 1. 감사 — 무엇이 없었는가

| 있던 것 | 상태 |
|---|---|
| `DestructionRuling` / `MovementRuling` / `SummonRuling` 프로토콜 | ✔ (2-M · 2-X) |
| `Unknown*Ruling` — "아무것도 모른다" 기본값 | ✔ |
| `Declared*Ruling` — 손 선언 | ✔ **그러나 `InstanceId` 키** |
| `_check_rule_gate` — 실행 전 관문 | ✔ |
| **카드 단위의, 출처가 있는, 다시 쓸 수 있는 지식** | **✘** |

`Declared*Ruling` 은 **판 번호**를 키로 삼는다. 시험 대역으로는 맞지만
지식이 아니다 — 같은 카드를 다음 듀얼에서 다시 확인해야 하고, 무엇을 읽고
그렇게 적었는지가 남지 않는다.

그래서 등재 16장 중 4장이 실행되지 않았고 넷 다 이유가 같았다:
**답할 지식이 없다.**

### 질문 자체가 없던 것도 셋

| 술어 | 쓰는 카드 | 2-AK 전 |
|---|---:|---|
| `Card.IsAbleToHand` | 2,516 | **질문이 없었다** |
| `Card.IsAbleToRemove` | 775 | **질문이 없었다** |
| `Card.IsAbleToDeck` | 572 | **질문이 없었다** |
| `Card.IsAbleToGrave` | 544 | A (2-X) |
| `Card.IsDiscardable` | 537 | B (2-X) |
| `Card.IsCanBeEffectTarget` | 429 | C — 아직 아무도 묻지 않는다 |
| `Card.IsDestructable` | 347 | 종류로 거는 관문 (2-M) |

---

## 2. 더한 것 — 질문 셋과 파일 하나

### 질문 셋 (E · F · G)

종류로 박지 않고 **카드가 선언**하게 했다. 2-X 와 **같은 실측**이 같은
답을 준다 — 그 조작을 하는 카드 중 술어를 적는 비율이 100% 도 0% 도 아니다.

```
Duel.SendtoHand  2,587장 중 IsAbleToHand   2,437  (94%)
Duel.Remove      1,396장 중 IsAbleToRemove   711  (50%)
Duel.SendtoDeck    825장 중 IsAbleToDeck     557  (67%)
```

`Duel.Release` 도 같은 모양이지만(693장 중 73장, 10%) **열지 않았다** —
이번에 필요한 카드가 없고, 필요 없는 것을 미리 열면 그것이 옳은지 아무도
확인하지 않는다.

### `engine/effect/ruling.py`

```python
RuleBasis       RULEBOOK · CARD_TEXT · OFFICIAL_RULING   # "짐작했다" 는 없다
RuleFact        answer(TRUE|FALSE) · basis · note
CardRuleFacts   card_id · answers · restricts_others
OperationRulingRegistry   손 등록. 없으면 UNKNOWN (ADR-006)
BoardRuling     view + registry → ConditionResult
```

**`RuleFact` 에 `UNKNOWN` 을 담을 수 없다.** "모른다" 는 사실이 아니라
사실이 없는 것이고, 그것은 **표에 줄이 없는 것**으로 표현된다. 담을 수
있게 하면 "확인해 보니 모르겠더라" 와 "안 봤다" 가 같은 모양이 된다.

**`restricts_others` 의 기본값이 참이다.** 확인하지 않은 카드는 막을 수
있다고 본다. 거짓으로 적으려면 근거를 함께 적어야 한다 — 공짜로 "안
막는다" 를 주장할 수 없다.

---

## 3. TRUE 는 공짜가 아니다

"이 카드 텍스트에 막는 말이 없다" 만으로 `TRUE` 를 내면, 판에 깔린 다른
카드가 막고 있을 때 틀린다. `BoardRuling` 은 둘을 다 본다.

```
1. 그 카드 자신이 무엇을 말하는가          CardRuleFacts
2. 판에 막을 수 있는 것이 있는가            INTERFERENCE_ZONES 훑기
```

2번에서 **등록되지 않은 카드를 하나라도 만나면 `UNKNOWN`** 이다. 지나치게
조심스러운 것이 아니라 정확한 것이다 — "아무도 안 막는다" 는 판 전체를 다
읽었을 때만 할 수 있는 말이다.

`FALSE` 는 훑지 않는다. **막는 것은 혼자서도 막는다.**

### 훑는 자리와 훑지 않는 자리

| | 자리 | 이유 |
|---|---|---|
| 훑는다 | MZONE · EMZONE · SZONE · FZONE · PZONE · GRAVE · REMOVED | 전부 **누구나 볼 수 있는** 자리다. 훑기가 관측 경계를 넘지 않는다 |
| 훑지 않는다 | 뒷면 카드 | 세트된 카드는 발동 · 반전 전까지 효과를 적용하지 않는다 (룰북) |
| 훑지 않는다 | 덱 | 덱의 카드는 효과를 적용하지 않는다 |
| **훑지 않는다** | **패** | **상대의 패는 보이지 않는다 — STRUCTURAL-98** |

마지막 줄이 이 계층의 진짜 한계다. **빈 칸으로 두지 않고**
`BoardRuling.scope_limits()` 가 값으로 들고 있다 — 문서에만 적으면 코드가
잊는다.

---

## 4. 룰북이 직접 답하는 것

지식의 출처가 추측이 아니라는 근거. 두 문장 다 저장소의 공식 룰북
(`data/rules/documents/sd-rulebook-en-v10.json`)에 **그대로 있고**, 테스트가
그것을 확인한다.

> **Yellow Normal Monster Cards do not have effects**, and have a
> description of them written here that does not affect the game.

→ 통상 몬스터는 (1) 스스로를 지키지 않고 (2) 남을 막지 않는다.
추측이 아니라 **귀결**이다. `normal_monster_facts()` 가 그 한 줄에서 나온다.

> They are not included in the Deck, and **cannot be sent anywhere other
> than the field, such as the hand or Graveyard.**

→ 토큰은 패 · 묘지 · 덱으로 갈 수 없다. **제외는 적지 않았다** — 룰북이
이름을 대지 않았고, 대지 않은 것을 채워 넣으면 그것이 옳은지 아무도
확인하지 않는다.

### 적지 않은 것이 더 중요하다

통상 몬스터의 사실에 **파괴와 특수 소환은 없다.**

- "파괴 내성이 없다" 와 "지금 이 카드를 파괴해도 된다" 는 다른 문장이다.
  뒤의 것은 대체 효과 · 동시 파괴 처리까지 봐야 한다.
- 소생 제한은 카드 텍스트가 아니라 **그 카드가 어떻게 필드를 떠났는가**에
  달려 있다. 카드 단위로 적을 수 없다 (STRUCTURAL-64).

그래서 `BoardRuling.may_be_destroyed` · `may_be_special_summoned` 는
**언제나 `UNKNOWN`** 이다. 답하는 척하면 내성을 가진 카드가 실제로
파괴된다.

---

## 5. 실제 카드 — 강제 탈출 장치 (94192409)

```
공식 텍스트: ①: 필드의 몬스터 1장을 대상으로 하고 발동할 수 있다.
             그 몬스터를 패로 되돌린다.
```

```lua
-- c94192409.lua
Duel.SelectTarget(tp,Card.IsAbleToHand,tp,LOCATION_MZONE,LOCATION_MZONE,1,1,nil)
Duel.SendtoHand(tc,nil,REASON_EFFECT)
```

2-W 부터 **네 단계 동안** "일부러 실행하지 않는다" 로 실려 있었다. 막던
것은 후보 조건 하나 — `Card.IsAbleToHand`. 이제 그 질문에 답할 자리가 있다.

| 스크립트 | 정의 |
|---|---|
| `EFFECT_FLAG_CARD_TARGET` | `TargetSpec.targeting` |
| `LOCATION_MZONE` (양쪽) | `zones={MZONE}, owner=None` |
| `SelectTarget(…, 1, 1, nil)` | `minimum=1, maximum=1` |
| **`Card.IsAbleToHand`** | **`gated=True`** (2-X · 2-AK) |
| `Duel.SendtoHand(tc,nil,…)` | `CardOperation.return_to_hand` |

**`IsAbleToHand` 를 후보 조건이 아니라 관문으로 옮겼다.** 스크립트에서는
같은 술어가 두 자리에 쓰이지만, 이 엔진은 관문을 계획 단계에서 묻는다.
후보 조건으로도 걸면 같은 질문을 두 계층이 각자 답하게 되고, 둘이 갈리면
어느 쪽이 맞는지 알 수 없다 — **2-AJ 가 사건 계층에서 겪은 바로 그 일**이다.

세 갈래가 전부 시험으로 고정되어 있다.

| 판정 | 결과 | 판 |
|---|---|---|
| 판정기 없음 → `UNKNOWN` | `UNCHECKED_RULES`, `missing="…IsAbleToHand 판정"` | 그대로 |
| `FALSE` (토큰) | `INVALID_TARGET`, "패로 되돌릴 수 없다고 판정되었습니다" | 그대로 |
| `TRUE` | `RESOLVED` — 몬스터가 실제로 패로 간다 | 바뀐다 |

**라이브러리: 16장 / 실행 가능 13장.**

---

## 6. 로스트 — 이유가 바뀌었다 (여전히 실행하지 않음)

2-W 의 이유("`IsAbleToRemove` 를 판정할 계층이 없다")는 **더 이상 참이
아니다.** 그래서 다시 읽었고, 남은 둘을 찾았다.

1. **`aux.SpElimFilter`** — EDOPro 보조 함수. 내용을 읽지 않고는 무슨
   조건인지 말할 수 없고, 읽지 않은 것을 "없는 조건" 으로 옮기면 후보가
   넓어진다.
2. **공식 텍스트와 스크립트가 다른 자리를 가리킨다.**

   | 공식 텍스트 (KO/EN) | `c24623598.lua` |
   |---|---|
   | "**상대의 묘지의** 카드 1장" / "1 card from your opponent's Graveyard" | `LOCATION_MZONE\|LOCATION_GRAVE` (상대 쪽) |

   스크립트는 상대 **필드의 몬스터**도 고를 수 있다. 2-AJ 가
   STRUCTURAL-96 을 닫은 방법(공식 재정을 받아서 확인한 뒤에 적는다)을
   여기에도 적용해야 하고, 이번에는 받지 않았다.

**이유가 바뀐 것을 기록하는 것**이 이 단계가 로스트에 한 일이다.

---

## 7. 기존 테스트 수정 (삭제 0건, 수정 10건)

전부 **장부(census)** 이거나 **그때의 사실**을 들고 있던 것이다.

| 파일 | 테스트 | 왜 바뀌었는가 |
|---|---|---|
| `test_rule_gate_grave_discard.py` | `…_the_four_questions_are_four_values` → `…_every_question_is_its_own_value` | 넷이 **그때의 사실**이었다. 실측이 셋을 더 요구했고, 이 시험이 지키는 것은 개수가 아니라 **합치지 않는다**는 것 |
| 〃 | `…_asking_routes_to_the_matching_method` | `ask_movement` 가 새 질문에 `UNKNOWN` 을 준다. **잘못 부른 것**(대상 지정 · 수행 가능)은 여전히 예외 — 모르는 것과 오타를 같은 모양으로 만들지 않는다 |
| 〃 | `…_only_the_two_kinds_may_declare_a_gate` → `…_a_gate_is_declarable_only_where_the_corpus_is_split` | 둘이 다섯이 됐다. 늘린 근거는 2-X 와 **같은 실측** |
| `test_effect_scenarios.py` | `…_this_phase_added_no_engine_module` → `…_the_effect_package_is_exactly_these_modules` | 2-P 의 기록("이번 단계는 새 파일이 없다")은 그때 참이었다. 이 단언이 실제로 지키는 것은 **꾸러미의 내용**이므로 이름을 그쪽으로 |
| `test_real_card_execution.py` | `…_twelve…` → `…_thirteen_real_effect_refs_are_executable` | 장부 |
| 〃 | `…_every_declined_card_says_what_is_missing` | 넷 → 셋. 강제 탈출 장치가 빠진 것은 **이유가 없어져서**다. 로스트의 이유가 바뀐 것도 여기 적힌다 |
| 〃 | `…_operation_coverage_by_real_cards` | `RETURN_TO_HAND` 가 B(synthetic 전용) → A(실제 카드) |
| 〃 | `…_unsupported_operation_is_unreachable_from_real_cards` | 거절 목록에서 한 장이 빠졌다 |
| 〃 | `…_a_declined_real_card_cannot_be_activated` | 예로 쓰던 카드가 실행되기 시작했다. 보는 것은 **거절된 카드의 발동이 어디서 멈추는가**이므로 예를 로스트로 바꿨다 |
| `test_operation_integration.py` | `…_no_real_card_uses_move_or_special_summon_yet` | 종류 집합만 넓혔다. **요점(MOVE·특수소환에는 아직 실제 카드가 없다)은 그대로** |

**어느 단언도 약해지지 않았다.**

---

## 8. 테스트

- New tests: **37** (`tests/engine/test_operation_ruling.py`)
- Passed: **2908** / Failed 0 / Skipped 4 / Regression **0**

| 무엇을 | 시험 |
|---|---|
| 질문 셋의 근거 (corpus 재측정) | `test_a_*` — 2,516 · 775 · 572 · 94% · 50% · 67% |
| 사실은 사실만 담는다 | `test_b_a_fact_cannot_be_unknown` · `…_needs_evidence` |
| 룰북 인용이 진짜 룰북에 있다 | `test_c_both_rulebook_quotes_are_really_in_the_rulebook` |
| 적지 않은 것 (파괴 · 특수 소환 · 토큰의 제외) | `test_c_a_normal_monster_says_nothing_about_being_destroyed` |
| 모르는 카드 하나가 판 전체를 `UNKNOWN` 으로 | `test_d_one_unknown_card_on_the_board_is_enough_to_stop_it` |
| 뒷면 카드는 훑기를 막지 않는다 | `test_d_a_set_card_does_not_stop_the_scan` |
| 한계를 값으로 들고 있다 | `test_d_what_is_not_scanned_is_written_down` |
| 실제 카드 세 갈래 | `test_e_*` (판정기 없음 · `FALSE` · `TRUE`) |
| 결정론 · 복제 독립 · 판 불변 | `test_f_*` |

---

## 9. TODO

- **ADR-006 — 부분 해결.** 답할 **자리**가 생겼고 실제 카드 한 장이 돈다.
  파괴(347+533장)와 특수 소환(4,297장)은 **그대로** — 그 둘은 카드 텍스트
  한 줄로 환원되지 않는다.
- **STRUCTURAL-98 (신규 · 🟠)** — **관문이 통과시킨 것에 "무엇을 보지
  않았는가" 를 실을 자리가 없다.** `BoardRuling.scope_limits()` 가 값으로
  들고 있지만 `EffectResult` 로 나가지 못한다. `unchecked_rules` 는 조작
  **종류**별 표라 판정 **한 번**의 한계를 담지 못한다.
- **STRUCTURAL-99 (신규 · 🟡)** — **판정기가 판을 스스로 보지 못한다.**
  `BoardRuling` 은 `GameStateView` 를 받아 들고 있으므로 부르는 쪽이
  해결 직전에 만들어 넘겨야 한다. 실행기가 계획 시점의 **투영된 판**으로
  만들어 주는 편이 맞지만, 그러려면 "규칙 질문은 누구의 눈으로 보는가" 를
  정해야 한다 (2-AI 의 `_authoritative_candidates` 가 자리마다 주인의
  눈으로 세는 것과 같은 문제).
- **STRUCTURAL-76 (지속 효과 계층) — 그대로.** 이 계층은 지속 효과를
  **해석하지 않는다.** 막을 수 있는 카드가 있으면 그냥 `UNKNOWN` 이다.
- **STRUCTURAL-97 (선언이 수가 아닐 수 있다) · 96(해결) · 95 · 93 · 90 ·
  87 · 86 · 83 — 그대로 둔다.**
- 71 · 74 · 75 · 77 · 78 — **하나도 건드리지 않았다.**

---

## 10. 판정

| 등급 | 건수 | 내용 |
|---|---:|---|
| 🔴 BLOCKER | **0** | |
| 🟠 STRUCTURAL | 1 신규 | 98 (판정의 한계를 실을 자리) |
| 🟡 DETAIL | 1 신규 | 99 (판정기 배선) |
| 🟢 COSMETIC | 0 신규 | |

---

## 11. 이번에 하지 않은 것

Duel Engine 재설계 · EffectExecutor 재작성 · 새 Graph Engine · 새 EventBus ·
새 Expression Language · 새 Rule Engine · AI 의사결정 · Discord/Web UI ·
모든 카드 지원 시도 · **카드 이름별 hardcoded rule** · 테스트 삭제 ·
규칙 추측.

특히 **옛 프로토콜 셋을 재작성하지 않았다.** `DestructionRuling` ·
`MovementRuling` · `SummonRuling` 은 80곳 넘게 쓰인다. `BoardRuling` 이
그것들을 **만족시키는** 쪽을 택했고, 새 질문만 `may(question, instance)`
로 받는다. 옛 판정기는 새 질문에 `UNKNOWN` 이다 — 그것이 사실이다.

파괴 관문도 **넓히지 않았다.** 파괴가 가장 큰 corpus 이지만, 카드 텍스트로
환원되지 않는 질문에 답하는 척하는 것보다 `UNKNOWN` 으로 두는 편이 맞다.

**다음 Phase 는 시작하지 않았다.**
