# 오르페골 갈라테아 ② 효과 확장 (Phase 6-BF)

**검토 기준 HEAD**: `73696f7408e65e8b30d61510e6dfb835c3c0e3ec`
**목표**: 자율 탐색이 「오르페골 갈라테아 소환 → 갈라테아 효과 해결 → 덱의
오르페골 마법 · 함정 세트」까지 **실제 엔진으로** 이어지게 한다.

🔴 **이 문서가 주장하지 않는 것**부터 적는다.

* **고정 수순을 정답으로 넣지 않았다.** `ComboLine` 도 카드명별 수순도
  건드리지 않았고, 아래 §4 의 탐색 결과는 `autonomous_search_opening` 을
  기본값으로 돌린 것이다.
* **외부 사이트에서 실행하지 않았다.** §6 은 변환기가 만드는 **계획의
  내용**만 본 것이고, 실제 Duel Simulator 에서의 재현은 확인하지 않았다.
* **이 턴에 방해가 완성됐다고 말하지 않는다.** 세트된 바벨 · 클리막스는
  이 저장소에서 **발동될 수 없다** (§5).
* 이번 작업에서 Discord 메시지를 보내지 않았고 외부 공유 링크를 만들지
  않았다.

---

## 1. 기존 구현과 **실제** 장애

### 1.1 작업 전에 있던 것 (재사용했다)

| 있던 것 | 자리 |
| --- | --- |
| 갈라테아 카드 데이터 · Lua | `data/cards.cdb` 30741503 · `c30741503.lua` |
| 효과 분석 (effect 목록 · ordinal) | `core.card_model.LuaScriptInfo.effects` |
| 효과 정의 · 실행 엔진 | `engine/effect/{definition,executor,library}.py` |
| 발동 조건 · 비용 · 대상 선택 · 체인 해결 | `engine/activation.py` · `engine/chain.py` · `engine/payment.py` |
| 카드별 사용 제한 | `engine/use_limit.py` · `engine/state/use_registry.py` |
| 링크 소재 조건 · 마커 · 존 판정 | `engine/link_rules.py` · `engine/link_summon.py` |
| **손패에서** 마법 · 함정을 세트하는 절차 | `engine/set_card.py` (`SET_SPELL_TRAP_PROCEDURE`) |
| 자율 탐색과 해결 중 선택 분기 | `agent/bounded_search.py` · `integration/autonomy.py` |

🔴 **새 효과 엔진을 만들지 않았다.** 아래 §2 · §3 의 전부가 위 표의 계층에
**얹힌** 것이고, 새로 만든 모듈은 하나도 없다.

### 1.2 왜 후보로 나오지 않았는가 — 장애 **일곱 개**를 갈래별로 구분했다

요청이 나눈 갈래 — 발동 조건 미충족 / 대상 없음 / 사용 제한 / 구현 · 연결
누락 / 엔진 미지원 / 탐색 예산 — 중 **어느 것이었는지**를 순서대로 적는다.
앞의 장애를 고치면 다음 장애가 드러나는 구조였으므로, 발견한 순서가 곧
수정 순서다. 🔴 **사용 제한은 원인이 아니었다** — 갈라테아 ② 를 그 턴에
이미 쓴 상황이 아니었고, 등재 후에는 그 제한이 실제로 걸리는 것을 확인했다
(§2.3).

| # | 장애 | 갈래 | 실측 증거 |
| --- | --- | --- | --- |
| 1 | 갈라테아 ② 가 `EFFECT_LIBRARY` 에 **없다** | **구현 · 연결 누락** | 등재 22건에 30741503 이 없었다. 보류 목록에도 그 카드가 **나타나지 않았다** — 정의가 없으면 후보 생성이 그 카드를 거치지도 않는다 |
| 2 | `SET_SPELL_TRAP` 이라는 **조작 종류가 없다** | **엔진 미지원** | `OperationKind` 가 15개(지금 16개)였고 "덱에서 세트" 가 없었다. `engine/set_card.py` 의 절차는 출발 자리가 `Zone.HAND` 로 **고정**이었다 |
| 3 | 비용으로 제외된 카드가 **뒷면**으로 놓였다 | **대상 없음** (뿌리는 구현 누락) | 디베르를 비용 제외한 뒤 `REMOVED` 의 그 카드가 `Position.FACEDOWN` 이었다. 공식 필터는 `c:IsFaceup()` 을 묻는다 → 후보가 0장 |
| 4 | 조립 층이 **이름마다 다른 관문**을 묻지 않았다 | **구현 · 연결 누락** | `_movement_question(definition)` 이 정의의 **첫** 관문 하나(`MAY_BE_RETURNED_TO_DECK`)를 **세트 후보**에게도 걸었다. 덱에 있는 카드는 그 답이 참이 아니므로 바벨 · 클리막스가 `permitted` 에서 빠지고 "후보 0장" 이 되었다 |
| 5 | 디베르 · 스켈레촌의 `IsAbleToDeck`, 바벨 · 클리막스의 `IsSSetable` 이 **등재되지 않았다** | **구현 · 연결 누락** | 실행 거절 문장: `#16 를 덱으로 되돌릴 수 있는지 판정할 수 없습니다 … 판정할 수 없는 것을 허가로 바꾸지 않습니다` |
| 6 | 세트 후보가 **발동 조건**으로 걸렸다 | **구현 · 연결 누락** | 덱에 「오르페골」 마법 · 함정이 없을 때 `@set 를 해결 중에 고르려면 후보가 있어야 합니다: 후보가 0장뿐입니다` 로 **발동 자체가** 막혔다. 공식 `s.tdtg` 는 그 후보를 묻지 않는다 |
| 7 | 자율 탐색이 그 경로까지 **펼치지 않았다** | **탐색 예산** | §4 |

🔴 **"카드에 효과가 있다" 와 "지금 발동할 수 있다" 는 다르다.** 1~6 은
전부 **발동할 수 있는가** 쪽의 공백이었고, 어느 하나도 "이 카드에는 그런
효과가 없다" 가 아니었다. 그리고 7 은 **둘 다 아니다** — 합법인데 탐색이
거기까지 가지 않은 것이다.

🔴 **어느 장애도 조건을 생략해서 통과시키지 않았다.** 3 은 비용이 놓는
표시 형식을 공식대로 고친 것이고 (§3.4), 5 는 판정을 **등재**한 것이며
(읽은 카드 텍스트가 근거다), 6 은 공식 발동 조건이 묻지 **않는** 것을
묻지 않게 한 것이다. `UNKNOWN` 을 허가로 바꾼 자리는 없다 — 등재되지 않은
카드는 지금도 거절된다 (`test_d02`).

---

## 2. 효과를 **무엇을 읽고** 구현했는가

### 2.1 공식 텍스트 (`data/ko/ko-KR.json` 30741503)

> 「오르페골」 몬스터를 포함하는 효과 몬스터 2장
> 이 카드명의 ②의 효과는 1턴에 1번밖에 사용할 수 없다.
> ①: 링크 상태의 이 카드는 전투로는 파괴되지 않는다.
> ②: 자신의 제외 상태인 기계족 몬스터 1장을 대상으로 하고 발동할 수 있다.
> 그 몬스터를 덱으로 되돌린다. 그 후, 덱에서 "오르페골" 마법 / 함정 카드
> 1장을 자신 필드에 세트할 수 있다.

### 2.2 `c30741503.lua` 의 `e2` — 옮긴 것

```lua
e2:SetCategory(CATEGORY_TODECK)
e2:SetType(EFFECT_TYPE_IGNITION)
e2:SetProperty(EFFECT_FLAG_CARD_TARGET)
e2:SetRange(LOCATION_MZONE)
e2:SetCountLimit(1,id)
e2:SetCondition(s.tdcon1)   -- not IsPlayerAffectedByEffect(tp,CARD_ORCUSTRATED_BABEL)
function s.tdfilter(c) return c:IsFaceup() and c:IsRace(RACE_MACHINE) and c:IsAbleToDeck() end
function s.tdtg(...)  Duel.SelectTarget(tp,s.tdfilter,tp,LOCATION_REMOVED,0,1,1,nil) end
function s.filter(c)  return c:IsSetCard(SET_ORCUST) and c:IsSpellTrap() and c:IsSSetable() end
function s.tdop(...)
  Duel.SendtoDeck(tg,nil,SEQ_DECKTOP,REASON_EFFECT)
  if og:IsExists(Card.IsLocation,1,nil,LOCATION_DECK) then Duel.ShuffleDeck(tp) end
  local g=Duel.GetMatchingGroup(s.filter,tp,LOCATION_DECK,0,nil)
  if #g>0 and Duel.SelectYesNo(tp,aux.Stringid(id,1)) then
    Duel.BreakEffect(); local sg=g:Select(tp,1,1,nil); Duel.SSet(tp,sg) end end
```

| Lua | 이 저장소 |
| --- | --- |
| `EFFECT_TYPE_IGNITION` | `activation_kind=IGNITION` |
| `SetRange(LOCATION_MZONE)` | `activation_zones={MZONE, EMZONE}` — 아래 ★ |
| `EFFECT_FLAG_CARD_TARGET` + `SelectTarget` | `@primary` 가 `TargetRequirement.TARGETING` |
| `s.tdcon1` | `Not(FaceUpCardPresent(자신, {FZONE}, 바벨))` |
| `LOCATION_REMOVED, 0` | `zones={REMOVED}, owner=CONTROLLER` |
| `c:IsFaceup()` | `CardIsFaceUp()` |
| `c:IsRace(RACE_MACHINE)` | **새 조건** `RaceIs("MACHINE")` |
| `c:IsAbleToDeck()` | `CardOperation.return_to_deck(..., gated=True)` 의 관문 |
| `Duel.SendtoDeck` | `CardOperation.return_to_deck(PRIMARY_TARGET)` |
| `Duel.ShuffleDeck(tp)` | `ShuffleOperation(DECK, CONTROLLER)` |
| `s.filter` 의 `IsSetCard(SET_ORCUST)` · `IsSpellTrap()` | `@set` 후보 조건 (`compile_archetype_condition` · `IsSpellTrap`) |
| `s.filter` 의 `IsSSetable()` **절반** | **새 조작** `SetSpellTrapOperation(..., gated=True)` 의 관문 `MAY_BE_SET` |
| `g:Select(tp,1,1,nil)` (해결 중) | `chosen_at_resolution=True` |
| `s.tdtg` 가 `s.filter` 를 **묻지 않는다** | **새 선언** `checked_at_activation=False` |
| `Duel.SSet(tp,sg)` | `SetSpellTrapOperation` |
| `if #g>0` (SendtoDeck **뒤**) | `ResolutionSkip(when_no_candidate=True, scope=TARGET_OPERATIONS)` |
| `SetCountLimit(1,id)` | `UseLimit(LimitScope.PER_CARD_NAME)` |

★ **`EMZONE` 을 함께 적은 이유**: EDOPro 의 `LOCATION_MZONE` 은 엑스트라
몬스터 존을 **포함**하고, 이 저장소는 그 자리를 `Zone.EMZONE` 으로 따로
들고 있다. 링크 소환된 갈라테아는 **언제나** `EMZONE` 에 놓이므로
(`LINK_MATERIAL_ZONES`), `MZONE` 만 적으면 이 효과는 한 번도 발동되지
않는다. 범위를 넓힌 것이 아니라 같은 자리를 이 저장소의 두 이름으로 적은
것이다.

### 2.3 요청이 확인하라고 한 항목 — 하나씩

| 항목 | 확인한 것 |
| --- | --- |
| **발동 조건** | `s.tdcon1` **하나뿐**이다. 🔴 **②에 「링크 상태」 조건은 없다** — 그것은 `e1`(`EFFECT_INDESTRUCTABLE_BATTLE`)의 조건이다. `e2:SetCondition` 이 가리키는 함수 전문을 읽어 확인했다. 텍스트의 ①을 ②의 조건으로 끌어오면 **엔진이 규칙을 지어내는 것**이고, 더 엄격해도 거짓이다 |
| **제외된 기계족 대상 적격성** | 앞면(`IsFaceup`) · 기계족(`IsRace`) · 덱으로 되돌릴 수 있음(`IsAbleToDeck`, 관문). 셋 다 옮겼다 |
| **대상 지정과 비용의 구분** | ② 에는 **비용이 없다.** `e2:SetCost` 가 없다 — 되돌리기는 **해결**이다. (비용이 있는 쪽은 디베르 · 스켈레촌의 ① 이고, 그 비용이 이 효과의 **대상을 만든다**) |
| **덱 반환 처리** | `SendtoDeck(…, SEQ_DECKTOP, REASON_EFFECT)` → `RETURN_TO_DECK` + `ShuffleOperation`. 🔴 `SEQ_DECKTOP`(맨 위로) 은 바로 뒤의 `ShuffleDeck` 이 덮으므로 순서를 따로 옮기지 않았다 |
| **반환과 세트의 관계** | 반환은 **무조건**, 세트는 **그 후 · 선택**이다. 공식 처리에서 세트 후보 조회(`GetMatchingGroup`)가 `SendtoDeck` **뒤**에 있으므로, 세트할 것이 없어도 반환은 일어난다 (`checked_at_activation=False` + `TARGET_OPERATIONS`) |
| **덱에서 선택 가능한 범위** | `IsSetCard(SET_ORCUST)` **그리고** `IsSpellTrap()`. 이 덱에는 정확히 두 장 — 오르페골 바벨 (90351981, FIELD SPELL) · 오르페골 클리막스 (703897, COUNTER TRAP) |
| **세트 존 빈자리와 절차** | 손패 세트와 **같은 배치 코드**를 쓴다 (`engine.set_card.effect_set_procedure`). 출발 자리만 `DECK` 이다. 빈 칸이 없으면 **계획 단계에서** 거절하고 판은 그대로다 |
| **카드명 · 효과별 턴 제한** | `SetCountLimit(1,id)` → `LimitScope.PER_CARD_NAME`. 실측 거절: `30741503:e[1] 는 1턴에 1번 (같은 이름의 카드 전체 기준) 이고 이 턴에 이미 1번 썼습니다` |
| **해결 시 대상 소실 · 상태 변화** | 기존 계층이 그대로 본다 — 대상 관계(`engine.state.target_relation`) · 해결 시점 관문 재질의(`BoardRuling`). 대상을 덱으로 되돌릴 수 **없게 된** 경우는 관문이 거절한다 |
| 🔴 **엑스트라 덱 몬스터 대상의 반환 위치 차이** | **거절한다.** `s.tdfilter` 는 메인 · 엑스트라를 가리지 않지만, 실제 처리에서 엑스트라 덱 몬스터는 **엑스트라 덱으로** 돌아간다. 그 자리가 이 저장소에 없으므로 `RETURN_TO_DECK` 이 `MISSING_EXTRA_DECK_DESTINATION` 으로 멈춘다 (Phase 6-M). 🔴 **지어내 통과시키지 않았다** — `tests/test_galatea_effect_extension.py::test_d01` 이 그 자리를 실제로 밟는다 |

### 2.4 옮기지 **못한** 것

* `Duel.SelectYesNo` 의 **「아니오」 갈래**. 공식 처리는 후보가 있어도
  세트를 거절할 수 있다. 이 저장소에는 "고를 수 있는데 고르지 않는다" 를
  표현하는 자리가 없어 (`minimum=0` 을 쓰는 등재 효과가 하나도 없다)
  **후보가 있으면 반드시 한 장을 고른다.** 🔴 표현할 수 있는 결과가
  공식보다 **적다** — 없는 허가를 만든 것이 아니다.
* `Duel.BreakEffect()` (세트 앞에서 체인을 끊는 처리). 체인 블록 경계
  계층이 없다.
* `Duel.IsPlayerAffectedByEffect` 자체. 디베르 · 스켈레촌과 **같은 이유**로
  「바벨이 앞면으로 필드에 있는가」로 옮겼고, **무효화된 바벨을 구별하지
  못한다**.
* `e3` (`EFFECT_TYPE_QUICK_O`, `s.tdcon2` = 바벨이 적용될 때). 유발즉시의
  발동 시점을 룰북에서 읽지 못했으므로 등재하지 않았다 (ADR-006). 즉
  **바벨이 앞면으로 깔린 판에서는 이 효과를 쓸 수 없다** — ②는 조건이
  거짓이고 ③은 미지원이다. 디베르와 똑같은 모양의 정직한 범위다.
* `e1` (`EFFECT_INDESTRUCTABLE_BATTLE`). 지속 효과이고 발동하는 일이 아니다.
* 🔴 **평가가 `FZONE` 을 읽지 않는다** — 바벨을 세트한 결과와 세트하지
  않은 결과가 같은 변형 열쇠를 갖는다 (§5.1 의 마지막 항목).
* `IsSSetable` 의 두 절반은 **둘 다 옮겼지만 자리가 다르다** — 「그 자리에
  놓을 수 있는가」는 배치 계획이 지키고, 「카드가 세트를 금지하지
  않는가」는 관문 `MAY_BE_SET` 이 묻는다. 🔴 **옮기지 못한 것은 그 금지를
  가진 카드**다: 질문할 자리는 생겼지만 세트를 금지하는 카드를 읽어 등재한
  것은 아직 없다. 등재되지 않은 카드는 그 질문에 `UNKNOWN` 이고, 그것은
  허가가 아니라 **거절**이다.
* **고르는 시점과 판을 바꾸는 시점이 어긋난다** (계획 먼저 · ADR-008).
  공식은 되돌리기를 먼저 하고 그 다음 덱에서 고르는데, 이 실행기는 모든
  조작을 계획한 뒤에 적용하므로 세트 후보를 **되돌리기 전의 덱**에서 본다.
  🔴 여기서는 결과가 달라지지 않는다 — `s.filter` 가 마법 · 함정만 받으므로
  방금 되돌아온 **몬스터**는 어느 쪽 덱에서도 후보가 아니다.

---

## 3. 덱에서 세트하는 **실제 상태 변경**

### 3.1 새로 만든 것

| 자리 | 무엇 |
| --- | --- |
| `engine/effect/operation.py` | `OperationKind.SET_SPELL_TRAP` · `SetSpellTrapOperation(target_ref, gated)` |
| `engine/set_card.py` | `EFFECT_SET_FROM_DECK_PROCEDURE` (DECK→SZONE) · `EFFECT_SET_FIELD_FROM_DECK_PROCEDURE` (DECK→FZONE) · `effect_set_procedure(field_spell=…)` |
| `engine/effect/executor.py` | `_plan_set_spell_trap` · `_apply_set_spell_trap` + `OPERATION_HANDLERS` 한 줄. 계획이 `_check_rule_gate` 로 관문을 **엔진에서도** 묻는다 — 조립 층의 후보 판정과 같은 질문이고, 선택이 밖에서 들어오는 길에서도 `UNKNOWN` 이 허가가 되지 않게 한다 |
| `engine/effect/semantics.py` | `RuleQuestion.MAY_BE_SET` (`Card.IsSSetable`) + 다섯 표의 한 줄씩 (`LUA_GATE_PREDICATES` · `DECLARED_GATE_RULINGS` · `GATING_RULES` · `MISSING_GATE` · `QUESTION_VERBS`) + `MISSING_SET_DESTINATION` |
| `engine/condition/model.py` | `RaceIs` (`AttributeIs` 와 같은 모양) |
| `engine/effect/target.py` | `TargetSpec.checked_at_activation` |
| `engine/payment.py` | `COST_LANDING_POSITION` — 제외 비용이 **앞면**으로 놓인다 |
| `engine/activation.py` | `checked_at_activation` 이 거짓인 이름의 **발동 시점 존재 검사를 건너뛴다**. 🔴 그 사실을 적은 효과만 이 길로 가고, 기본값은 참이므로 기존 효과의 발동 조건은 한 글자도 약해지지 않았다 |
| `integration/autonomy.py` | `_movement_question(definition, ref)` — **이름마다** 관문을 고른다. 🔴 ``ref`` 를 주지 않으면 6-BF 이전과 똑같다. 실측으로 등재 23건의 모든 이름을 훑어 **관문 질문이 달라진 자리는 갈라테아 ② 의 `@set` 하나**임을 확인했다 |

### 3.2 요청이 요구한 네 가지

| 요구 | 어떻게 지키는가 | 실측 |
| --- | --- | --- |
| 선택 카드가 **덱에서 빠진다** | `procedure.plan_for` 가 출발 자리를 `DECK` 으로 확인하고 `procedure.place` 가 옮긴다 | 덱 34 → 33장, `card_set` 델타의 `from_zone="DECK"` |
| **합법적인 자리**에 놓인다 | 손패 세트와 **같은 배치 코드**. 필드 마법은 `FZONE`, 나머지는 `SZONE` — 카드 정의의 `type_names` 가 가른다 | 바벨 → `FZONE[0]`, 클리막스 → `SZONE[0]` |
| 표시 형식 · 컨트롤러 · **세트한 턴**을 적는다 | `Position.FACEDOWN` · `placement.player` · `RuleActionKind.SET_SPELL_TRAP` | `count_card(turn, 0, 그 카드, SET_SPELL_TRAP) == 1`, 패의 카드는 `0` |
| 종류별 세트 · 발동 제한을 **기존 계약으로** 유지 | 🔴 **같은 이름으로 적는다** — 플레이어가 패에서 세트한 것과 효과로 덱에서 세트한 것이 같은 기록을 남긴다 (RULE-SPELLTRAP-007 · 009) | 위와 같은 줄 |

### 3.3 혼동하지 않은 세 가지

```
효과로 세트한다      SetSpellTrapOperation → effect_set_procedure (출발: DECK)
손패에서 세트한다     PlayerActionKind.SET_SPELL_TRAP → SET_SPELL_TRAP_PROCEDURE (출발: HAND)
카드를 발동한다       PlayerActionKind.ACTIVATE_CARD — 🔴 이 저장소에서 미지원
```

🔴 **미지원 발동을 가능하다고 표시하지 않았다.** 세트한 클리막스는
`activate_card` 후보로 올라오지 않는다. 그리고 그것은 "발동할 수 없다" 가
아니라 **`activate_card` 의 발동 타이밍 계층이 없어 그 종류 전체가 보류**
라는 뜻이다 (실측 보류 문장: `activate_card 의 남은 적법성을 판정할 규칙
계층이 아직 없습니다`). `test_c03` 이 그 구분을 잡는다.

### 3.4 `COST_LANDING_POSITION` — 왜 제외만 고쳤는가

제외 비용을 치른 카드가 `FACEDOWN` 으로 놓이면 공식 필터 `c:IsFaceup()` 이
영원히 거짓이고, 이 효과는 **한 번도** 발동되지 않는다. 고친 근거는
저장소의 카드 스크립트 모음에서 **직접 읽은** 것이다.

* `SetRange(LOCATION_GRAVE)` 인 효과가 자기 자신을 비용으로 제외하는
  자리는 `Duel.Remove(c,POS_FACEUP,REASON_COST)` 로 적혀 있다 —
  `c16938770` · `c17080584` · `c19403423` · `c29111045` · `c60023855` 등.
* 모음 전체에서 `POS_FACEUP,REASON_COST` 가 **650개 파일**,
  `POS_FACEDOWN,REASON_COST` 가 **19개 파일**이다. 뒷면 제외는 **그렇게
  적힌 카드**의 일이고, 이 저장소가 치를 수 있는 제외 비용
  (`SelfCardCost` 하나) 에는 그런 카드가 없다.

🔴 **표시 형식 모델을 만든 것이 아니다.** 묘지 · 패 · 덱으로 가는 이동은
한 글자도 달라지지 않았고 (표에 없다), 그 자리의 표시 형식은 여전히 **앞
존에서 들고 온 값**이다 — 즉 뜻을 갖지 않는다. 고친 것은 `REMOVED`
하나다.

---

## 4. 자율 탐색 연결 — **기본 입력 · 기본 예산**

### 4.1 입력

`recipe` = `docs/orcust-azamina-note.ydk` · `hand` =
`69811710,14558127,23434538,10045474,24224830` · `search:auto` ·
`results:3` · `followups:6`.

🔴 **기본 패에 성유물－『성장』이 있다고 가정하지 않았다.** 위 다섯 장에
성장(93920420)은 없다. 성장은 **덱**에 있고 기르수 ① 의 덤핑 후보 중
하나로만 나타난다.

### 4.2 합법성과 배분을 **분리해서** 조사했다

**합법성: 문제 없다.** 허용 후보만 따라가는 구동기로 다섯 수에 닿는다.
(`tests/test_galatea_effect_extension.py` 가 매번 이 길을 실제로 밟는다.)

```
1  normal_summon  기르수(75)
2  activate_effect 69811710:e[0]   → 덱에서 디베르를 묘지로        (선택 5개 중)
3  activate_effect 57835716:e[0]   → 자신을 제외하고 덱에서 특수소환 (선택 3개 중)
4  link_summon    갈라테아(83)      소재 (기르수 75, 스켈레촌 7)
5  activate_effect 30741503:e[1]   대상 디베르(16) → 덱 반환 + 세트  (선택 2개 중)
```

🔴 **이 효과에 닿는 가장 짧은 합법 경로는 5수다.** `followups:6` 안에
들어간다 — 즉 **행동 예산이 걸린 것이 아니다.**

**배분: 여기가 걸렸다.** 🔴 **같은 코드**(6-BF 의 등재 · 수정 전부)에서
`candidates_per_baseline` 만 기준 HEAD 의 값 `12` 로 되돌려 돌리면, 탐색은
**깊이 4 에서 바로 그 앞까지 가 놓고 멈춘다.** 보관된 후보 중에 이것이
있다:

```
normal_summon:75 → 69811710:e[0] → 57835716:e[0] → link_summon:83
                                              (깊이 4 · stop=open · 디베르 갈래)
```

다섯째 수가 갈라테아 ② 이고, 펼치지 못한 이유는 **그 기준점이 보관 상한
12 에 닿아 더 펼치지 않았기** 때문이다 (6-BE 가 넣은
`max_candidates_per_baseline` — 상한에 닿은 기준점은 "더 모으지 않고 더
펼치지도 않는다").

### 4.3 걸린 상한을 다섯 값으로 **재서** 골랐다

같은 기본 입력 · 같은 나머지 상한 (풀 20 · 노드 400 · 240초 · 분기 4 ·
기준점 3 · 행동 6) 에서 **그 값 하나만** 움직였다.

| `candidates_per_baseline` | 소요 | 노드 | 최대 깊이 | 후보 | **갈라테아② 경로** | 후속을 받은 기준점 |
| --- | --- | --- | --- | --- | --- | --- |
| 끔 (0) | 7.2초 | 34 | 7 | 28 | 3건 | **1개** ← 6-BE 가 고친 것이 풀린다 |
| **12** (기준 HEAD) | 9.1초 | 64 | 6 | 28 | **0건** | 2개 |
| **16** (6-BF 기본값) | 11.3초 | 72 | 7 | 28 | **1건** (재생 검증 통과) | 2개 |
| 18 | 12.5초 | 76 | 7 | 28 | 2건 | 2개 |
| 20 | 6.5초 | 34 | 7 | 28 | 3건 | **1개** (끔과 같다) |

16 · 18 만 **둘 다** 만족한다 — 6-BE 가 수치로 고친 "서로 다른 해결
선택의 기준점 둘 이상이 후속을 받는다" 와, 이 Phase 가 등재한 효과에
실제로 닿는다는 것. 그래서 **둘 중 작은 쪽인 16** 으로 올렸다.

🔴 **예산을 키워서 해결한 것이 아니다.**

* 후보 풀 · 노드 · 초 · 분기 · 기준점 · 행동 상한은 **한 글자도** 움직이지
  않았다. 움직인 것은 **보관 자리를 기준점 사이에 어떻게 나누는가** 하나다.
* 반대 방향도 확인했다: 풀만 20 → 40 으로 키우면 33.8초 · 239노드를 쓰고도
  **0건**이다. 즉 "예산을 크게 늘리면 찾아진다" 가 아니었다.

🔴 **기준 HEAD 의 기본 예산에서는 발견하지 못했다** (0건). 지금 기본값
(16) 에서 발견한다 (1건). 두 사실을 섞지 않는다.

### 4.3-1 수정 전후의 전개와 최종 자원

🔴 **두 열의 출처를 가른다.** 「전」 열에서 **깊이 · 마지막 수 · 자원**은
6-BF 코드에 `candidates_per_baseline=12` 만 되돌려 **실제로 돌린** 값이고
(§4.2), 「갈라테아 ② 가 후보에도 보류에도 없었다」는 기준 HEAD 코드의
사실이다 (§1.2 의 장애 1). 둘을 한 칸에 섞지 않는다.

| | **전** (상한 12) | **후** (6-BF 기본값 16) |
| --- | --- | --- |
| 최대 깊이 | 6 | **7** |
| 가장 깊은 전개의 마지막 수 | `link_summon` 갈라테아 — **거기서 끝난다** | `activate_effect 30741503:e[1]` — 덱 반환 + 세트 |
| 갈라테아 ② (기준 HEAD 코드) | 후보에도 **보류에도** 없었다 (정의가 없다) | 후보로 나오고 해결된다 |
| 제외 | 스켈레촌 1장이 **남는다** (쓸 길이 없다) | **0장** (덱으로 돌아갔다) |
| `SZONE` · `FZONE` | 패에서 세트한 것만 | **덱에서 세트한 「오르페골」 1장** |
| 갈라테아 ② 사용 기록 | 없다 | 카드명 기준 소진 |

🔴 **"수정 전에는 갈라테아를 세울 수 없었다" 가 아니다.** 갈라테아 링크
소환은 6-AP 부터 후보로 나왔다 (그 보고서 §6). 수정 전에 없던 것은 **그
뒤에 할 수 있는 일**이고, 그래서 제외된 기계족이 쓸 길 없이 남았다.

### 4.4 어느 갈래도 정답으로 고르지 않았다

* **바벨 · 클리막스 중 하나를 무조건 고르지 않는다.** 해결 중 선택 기록의
  `permitted` 가 **두 장 모두**이고 (`test_b01` 이 둘 다 `TRUE` 인 것을
  확인한다), 어느 쪽을 골랐는지는 탐색의 분기가 정한다. 놓이는 자리도
  다르다 (바벨 → `FZONE`, 클리막스 → `SZONE`).
* **토큰은 소재로 계속 쓸 수 있다.** 기르수 ③ 이 만든 토큰이 들어가는
  경로(아래 §4.5)가 실제로 탐색된다 — 링크 규칙을 한 글자도 바꾸지 않았다.
* **고정 ComboLine · 카드명별 정답 수순을 쓰지 않았다.** `opening_wiring
  (repository, None)` 그대로이고 `line` 을 꽂지 않는다.

### 4.5 남은 배분 장애 — **솔직하게**

탐색이 찾아 오는 가장 짧은 경로는 **7수**이고, §4.2 의 **5수 경로가
아니다**. 탐색은 디베르 갈래 대신 다른 길로 갈라테아에 닿는다 — 실제로
찾은 후보 `#24` (재생 검증 통과) 의 걸음 전부는 이것이다.

```
1  normal_summon    기르수(75)
2  activate_effect  69811710:e[0]  선택 (7,)  → 덱의 스켈레촌을 묘지로
3  activate_effect  69811710:e[2]             → World Legacy Token 생성
4  link_summon      갈라테아i(87)   소재 (75)
5  activate_effect  21441617:e[0]             → 묘지의 자신을 제외하고
                                                 기르수를 특수 소환
6  link_summon      갈라테아(83)    소재 (87, 75)
7  activate_effect  30741503:e[1]  선택 (0,)  대상: 제외된 스켈레촌(7)
                                              → 덱 반환 + 클리막스를 세트
```

끝 자원 (좌석 0): `SZONE` 에 오르페골 클리막스 **뒷면** · `EMZONE` 에
갈라테아 · `MZONE` 에 World Legacy Token (앞면 수비) · 묘지에 갈라테아i ·
기르수 · **제외 0장** · 패 4장.

🔴 **토큰이 판에 남아 있다** — 이 경로에서 갈라테아i 의 소재는 기르수
하나였고, 토큰은 소재로 쓰지 **않았다.** 즉 토큰을 소재로 쓰는 길도 여전히
열려 있다 (링크 규칙을 한 글자도 바꾸지 않았다).

🔴 **이 경로의 대상은 디베르가 아니라 스켈레촌이다.** 스켈레촌 ① 의
비용이 자기 자신을 제외했고, 그것이 갈라테아 ② 의 「제외 상태인 기계족」이
되었다. 즉 **등재된 두 제외 비용 모두** 이 효과의 대상을 만든다 — 어느
카드를 정답으로 넣지 않았다는 사실이 여기서도 보인다.

🔴 **즉 "찾았다" 는 사실이지만 "최단 경로를 찾았다" 는 사실이 아니다.**
깊이 4 의 디베르 갈래(`#28`)는 기본 예산에서 여전히 다섯째 수를 받지
못한다. 그것이 이 Phase 가 **닫지 못한** 배분 장애이고, 다음 장애다 (§7).

---

## 5. 평가 · 표시 — 무엇이 확인되었고 무엇이 아닌가

평가기를 **전면 개편하지 않았다.** `agent/open_evaluation_v2.py` ·
`select_top_v2` · `rank_autonomous_results` 를 한 글자도 바꾸지 않았다.

🔴 **연결에 필요한 수정이 0건이었던 이유를 적는다.** `ResourceSummary` 가
이미 **모든 존**을 담으므로 (실측: 새 효과를 지난 결과의 요약에
`ZoneSummary(seat=0, zone='FZONE', size=1, cards=(CardSlot(instance=28,
card_id=90351981, face_up=False, position='FACEDOWN', …)))` 가 들어 있다),
평가 · 후보 선택 · 재생 검증이 **고치지 않고** 이 효과의 결과를 읽는다.
즉 "최소 수정" 이 아니라 **수정이 없었다** — 이것은 기존 계층이 넓게
만들어져 있었다는 뜻이고, 이 Phase 가 평가를 건드리지 않았다는 뜻이다.

🔴 **그 축이 무엇을 세는지 정확히 적는다.** `set_reactive` 는
**`SZONE` 의 뒷면 카드 중 함정 또는 속공마법**을 센다 (실측:
`agent/open_evaluation_v2.py` 가 `Zone.SZONE` 만 읽는다). 그러므로

* 클리막스(카운터 함정 → `SZONE`)는 그 축에 **잡힌다.**
* 바벨(필드 마법 → `FZONE`)은 그 축에 **잡히지 않는다.** 🔴 그것이
  옳다 — 필드 마법은 세트해 두어도 상대 턴에 쓰는 카드가 아니다.
* 그리고 `set_reactive` 는 **표시만 하는 축(B)**이고 **우열에 쓰이지
  않는다** (그 기준의 `role_ko` 가 "B · 표시만" 이다). 즉 세트가
  추천 순위를 올리지 않는다.

🔴 **그래서 남은 한계가 하나 더 있다.** `variant_key` 도 `SZONE` 만
읽으므로 (실측), **바벨을 세트한 결과와 아무것도 세트하지 않은 결과가
같은 변형 열쇠**를 갖는다. 즉 두 갈래 중 바벨 쪽은 평가가 **구별하지
못한다.** 평가기를 손대지 않기로 한 범위 안의 사실이고, 고치려면
`MeasuresV2` 가 `FZONE` 을 읽어야 한다 — 이 Phase 가 열지 않은 공백이다.

### 5.1 🔴 이번에 **확인된** 사실

| 사실 | 증거 |
| --- | --- |
| 효과가 **실제로 해결된다** | `EffectEvent #5 30741503:e[1] P0: #16 P0/REMOVED → P0/DECK (return_to_deck), P0 의 DECK 34장을 섞었다, P0 가 #28 를 FZONE[0] 에 FACEDOWN 로 세트 (소환이 아니다)` — 사건 하나에 세 변화가 **순서대로** 적힌다 |
| **어떤 제외 카드를 어디로** 되돌렸는가 | 디베르(57835716) — 비용으로 앞면 제외된 그 개체 — 를 **메인 덱**으로. 덱의 디베르가 2 → 3장 |
| **어떤 카드를 어느 존에** 세트했는가 | 바벨(90351981) → `FZONE[0]` `FACEDOWN` / 클리막스(703897) → `SZONE[0]` `FACEDOWN`. 둘 다 컨트롤러 0 |
| 남은 자원 | 패 4장 · `EMZONE` 에 갈라테아 · 묘지 2장 · 제외 0장 · 덱 33장 |
| 사용 제한 | 갈라테아 ② 가 카드명 기준으로 소진됐다 (같은 턴 재발동이 보류된다). 세트한 카드에 그 턴의 `SET_SPELL_TRAP` 기록이 붙었다 |

### 5.2 🔴 아직 **검증하지 않은** 것

* **상대 턴에 그 카드를 발동할 수 있는가.** 확인하지 않았다 — 세트는
  발동이 아니고, `activate_card` 의 발동 타이밍 계층이 없으며, 상대 턴
  시뮬레이션도 범위 밖이다.
* **방해를 몇 번 할 수 있는가.** 세지 않았다. 바벨 · 클리막스의 효과는
  `EFFECT_LIBRARY` 에 **등재되지 않았다**.
* **다른 전개보다 강한가.** 비교하지 않았다. v2 평가는 서로 다른 몬스터
  구성 사이의 우열을 **판정하지 않는다** (6-BE §13.2).
* **턴 종료 처리.** 하지 않았다.

🔴 **「바벨/클리막스가 세트됐으므로 확정 방해가 완성됐다」고 말하지
않는다.** 이 저장소에서 세트된 그 카드들은 **발동될 수 없다.** 세트된
것은 **자리에 뒷면으로 놓였다**는 사실 하나이고, 그 카드가 이 턴 이후에
무엇을 할 수 있는지는 이 작업이 재지 않았다.

### 5.3 새 후보 발견과 최종 추천은 **다른 사실이다**

* **새 후보 발견**: 기본 예산에서 갈라테아 ② 를 지나는 후보 **1건**을
  찾았고 재생 검증을 통과했다 (§4.3).
* **최종 대표 추천**: 그것이 `rank_autonomous_results` 의 추천에 들어간다는
  뜻은 **아니다.** 추천은 기존 v2 비교가 정하고, 이 Phase 는 그 비교에
  손대지 않았다. 둘을 같은 문장으로 적지 않는다.

---

## 6. 리플레이 · 외부 시뮬레이터

### 6.1 사건 기록 — 한 기록을 JSON · HTML 이 함께 쓴다

새 효과의 **되돌리기**는 기존 `ZoneMoved`, **세트**는 기존
`engine.set_card.CardSet` 델타로 남는다 — 새 사건 종류를 만들지 않았다.

고친 자리 셋:

| 자리 | 무엇 | 왜 |
| --- | --- | --- |
| `engine/set_card.py` | `CardSet.to_dict()` 의 `"card"` → `"instance"` | 다른 모든 델타가 `instance` 를 쓰고 재생 · 변환 계층이 그 이름으로 읽는다. `card` 인 동안 세트 사건은 **카드가 없는 변화**로 보였다 |
| `deck/replay_export.py` | `_MOVE_KINDS` 에 `card_set` 추가 + 그 분기 | 빠져 있으면 `verify_replay` 가 세트한 카드를 **출발 자리에 그대로 둔 채** 대조해 어긋남을 보고한다 |
| `deck/replay_viewer.py` | `card_set` 분기 (배치 + 안내 문구 + 장면 문장) | 같은 기록을 HTML 이 읽는다 |

🔴 **그 공백은 6-BF 이전에도 있었다.** 플레이어가 **패에서** 세트하는
행동도 같은 델타를 쓰므로, 세트를 지나는 재생 검증이 그때까지 없었을
뿐이다. 6-BF 가 덱에서 세트하는 효과를 등재하면서 그 길을 처음 지났다.

실측: `verify_replay(record) == ()` (어긋남 없음) 이고, 기록에
`card_set` 사건이 **1건** 있으며 `to_zone` 이 `FZONE` 또는 `SZONE` 이다
(`test_e02`).

### 6.2 외부 Duel Simulator 변환기 — **지원 여부를 확인했다**

**작업 전**: `deck/site_plan.py` 의 `_MOVE_KINDS` 에 `card_set` 이 없어
세트 사건이 `plan["unsupported"]` 로 빠졌다 — 🔴 **조용히 빠진 것은
아니었다** (그 목록에 적혔다). 다만 사이트 조작이 하나도 만들어지지
않았다.

**작업 후**: 요청 §6 의 "필요하면 이번 효과 이동 · 세트에 한정해 변환기를
보완" 에 따라 **자리 이동 조작만** 만든다. 그리고 표현하지 못하는 것을
`unsupported` 에 **적는다**:

> 뒷면 세트 — 이 계획은 **자리 이동만** 만듭니다. 표시 형식을 싣는 칸이
> 없어 사이트에서는 앞면으로 놓일 수 있고, 뒷면으로 만드는 조작은 사람이
> 해야 합니다. 🔴 그리고 세트는 발동이 아니므로 이 조작이 그 카드를
> 발동한다는 뜻도 아닙니다.

🔴 **조용히 생략한 뒤 전체 재현 성공으로 표시하지 않았다.** 그리고 🔴
**실제 사이트에서 실행하지 않았으므로 외부 사이트 재현을 확인했다고 말하지
않는다** — `test_e03` 이 보는 것은 계획의 **내용**뿐이다.

### 6.3 하지 않은 것

이번 작업에서 Discord 메시지를 보내지 않았고 외부 공유 링크를 만들지
않았다.

---

## 7. 검증

### 7.1 새 시험 — `tests/test_galatea_effect_extension.py` (21건, 전부 통과)

| 묶음 | 지키는 것 |
| --- | --- |
| A (4) | 올바른 조건에서 후보가 **생긴다** · 제외가 앞면으로 놓인다 · 바벨이 깔리면 닫힌다 · 카드명 기준 1턴 1번 |
| B (2) | 바벨 · 클리막스가 **둘 다** 허용 후보이고 고른 것이 그 안이다 · 대상 지정과 해결 중 선택이 다른 자리에 적힌다 |
| C (3) | 되돌리기 · 섞기 · 세트가 **판과 기록**에 있다 · 세트한 턴이 적힌다 · **세트는 발동이 아니다** |
| D (4) | 엑스트라 덱 대상은 **거절**된다 (판이 그대로다) · 등재되지 않은 세트 후보는 통과하지 않는다 · 이름마다 관문이 다르다 · 후보 0장이면 **세트만** 생략한다 |
| E (3) | 새 초기 상태 재실행이 같은 판을 준다 · 재생 기록이 세트를 설명한다 · 변환기가 조용히 빠뜨리지 않는다 |
| F (3) | 앞선 걸음의 허용 후보가 **그대로**다 (기르수 선택 5개 · 링크 후보 4개) · 롱기르수는 여전히 소재 부족 · 이동 시스템이 늘지 않았다 |
| G (2) | **자율 탐색이 기본 예산에서 실제로 찾는다** · 찾은 경로가 재생 검증을 통과한다 |

🔴 **고정 경로 통과만으로 자율 탐색 성공을 주장하지 않는다.** G 의 두
시험은 수순을 하나도 주지 않는다 — `autonomous_search_opening` 을
기본값으로 돌리고, 돌아온 후보들 **안에** 그 효과를 쓴 경로가 있는지만
본다. 어느 카드를 세트했는지도 요구하지 않는다.

🔴 **단순 코드 문자열 검사로 끝낸 시험이 없다.** A~G 전부 실제 `Duel` 을
돌린다 (`test_d03` · `test_f03` 만 표를 직접 읽는다 — 그 둘은 표의 내용이
곧 주장이다).

### 7.2 전체 스위트를 **기준 HEAD 와 차집합으로** 비교했다

🔴 **먼저 틀린 것을 적는다.** 이 Phase 를 처음 보고할 때 나는 "손댄
파일들을 돌려 전부 통과한다" 를 근거로 회귀가 없다고 적었다. **그 근거로는
회귀가 없다고 말할 수 없다** — 짚지 못한 파일의 audit 들이 등재부 내용을
고정하고 있었고, 실제로 **22건이 새로 실패했다.** 전체 스위트를 양쪽에서
돌려 차집합을 낸 뒤에야 그것이 보였다.

기준 HEAD 는 **별도 worktree** 로 체크아웃해 같은 명령으로 돌렸다
(`pytest tests/ -q -p no:randomly -n 4 --dist loadfile`, 데이터 ·
스크립트는 symlink 로 같은 것을 쓴다).

| | 실패 | 통과 | 스킵 | 소요 |
| --- | --- | --- | --- | --- |
| 기준 HEAD `73696f74` | **72** | 7443 | 10 | 20분 03초 |
| 6-BF 첫 커밋 `4e213f80` | **90** | 7446 | 10 | 20분 01초 |
| 6-BF 후속 `8de37789` | **68** | 7468 | 10 | 19분 50초 |

🔴 **기준 HEAD 가 이미 72건 실패 상태다.** 그러므로 "6-BF 이후 실패 N건"
은 아무것도 말하지 않는다 — 비교는 **차집합**으로만 뜻이 있다.

최종 차집합 (`8de37789` 대 `73696f74`):

* 🔴 **6-BF 가 새로 만든 실패: 0건.** (첫 커밋 `4e213f80` 에서는 **22건**
  이었다 — 전부 등재부 내용을 고정한 audit 이고, 하나하나 근거를 적어
  고쳤다. 아래 표.)
* ✅ **6-BF 가 고친 기존 실패: 4건** — `test_archetype_condition::test_c` ·
  `test_resolution_outcome_four_cases::test_n05` · `::test_n06` ·
  `test_skeleton_revival_and_longirsu::test_e04`.
* 🔴 **남은 68건은 기준 HEAD 에서 그대로 실패하던 것들**이고 6-BF 가
  건드리지 않았다 (`test_effect_type_quick_audit` ·
  `test_korean_overlay_unapplied_audit` · `test_validation_code_*` ·
  `test_rule_not_implemented_code_audit` · `state_hash` 계열 등 — 이
  Phase 의 범위 밖이다).
* 🔴 그 68건 중 **둘**(`test_trigger_window_completion::test_d05` ·
  `::test_f02`) 은 6-BF 가 **고치지 않기로 한** 것이다 (§7.2 의 아래 표
  마지막 줄의 근거).

실행에서 **오르페골 계열 시험은 하나도 실패하지 않았다** — 신규
`test_galatea_effect_extension.py` 21건, `test_open_search.py`,
`test_harp_horror_graveyard_effect.py`,
`test_skeleton_revival_and_longirsu.py`, `test_orcust_girsu_line.py`,
`test_token_and_galateai_summon_gates.py` 전부 통과다.

#### 새로 만든 실패 22건 — 무엇이 늘었고 무엇을 고쳤는가

| 늘어난 사실 | 고친 자리 |
| --- | --- |
| `ordinal == 1` 인 등재가 **둘**이 되었다 (『성장』 ② · 갈라테아 ②) | 7개 파일의 `… ordinal == 1) == 1` → `== 2` |
| 공식 블록 수 표에 `30741503: 3` 이 없다 | 4개 파일의 블록 수 표 (e1 지속 · e2 기동 · e3 유발즉시 — 실측) |
| 대상 묶음이 13 → **15** (한 효과에 이름 둘인 첫 등재) | `test_multi_target_selection` (여러 장 선택 · 가변 장수는 **여전히** 하나 · 0건) |
| **앞면 조건**을 쓰는 등재가 0 → **1** | `test_card_position_visibility::test_f04` — `CandidateSource.require` 로 **모델을 바꾸지 않고** 적혔다는 사실은 그대로 |
| `rule_uses.record_card(` 호출자가 둘 | `test_set_turn_record::test_17` — 두 자리가 **서로 다른 세트**(패에서 · 덱에서)를 적고, 이름이 같아야 같은 제약을 받는다 |
| `OperationKind` 분류에 `set_spell_trap` | `test_operation_integration` · `test_trigger_condition_separation_audit` — **이동 표는 한 글자도 늘지 않았다** |
| 발동 조건 종류에 `Not` | `test_event_context_audit::test_11` — `Not` 도 **판만** 묻는다 |
| 공식 `SetCondition` 을 가진 등재가 넷 → **다섯** | `test_effectdefinition_activation_audit` — `dropped == []` 는 그대로 |
| 사용 제한이 **기록된** 효과가 다섯 → **여섯** | `test_orcust_girsu_line::test_d03` |
| 클리막스가 판정 등록소에 들어왔다 | `test_bounded_search_first_pass` — "등록소에 없다" 를 **"그 질문(`MAY_BE_SENT_TO_GRAVE`)에 답이 없다"** 로 바꿨다. 이 시험이 쓰는 사실은 뒤쪽이다 |

🔴 **어느 단언도 약하게 만들지 않았다.** 늘어난 항목을 근거와 함께 더했고,
각 시험이 지키던 사실("합치지 않는다" · "이동 시스템이 늘지 않았다" ·
"일괄 완화가 아니다" · "가변 장수는 없다")은 그대로 두었다.

### 7.3 기존 시험의 수 고정

**수를 고정한 단언을 고쳤다** — 기존 시험 파일 **39개**다. 등재 수
22 → 23 · 실행 가능 19 → 20 ·
판정 등록소 26 → 28장 · `RuleQuestion` 8 → 9 · `OperationKind` 15 → 16 ·
`DECLARABLE_GATE_KINDS` 5 → 6 — 그 수를 박아 둔 자리마다 **바뀐 이유를 한
줄씩** 적었다. 🔴 **어느 단언도 약하게 만들지 않았다**: 지키는 사실(예
"질문을 합치지 않는다" · "이동 시스템이 늘지 않았다" · "일괄 완화가
아니다")은 그대로 두고, 늘어난 항목을 **근거와 함께** 더했다.

**선언이 둘이 된 자리는 둘을 각각 확인하게 했다.**
`test_h08_the_scope_is_declared_not_assumed` 는
`NoCandidateScope.TARGET_OPERATIONS` 를 선언한 효과가 디베르 ① 하나임을
재고 있었다. 지금은 둘이고, **근거가 서로 다르다** — 디베르는 `if #g>0`
밖의 `RegisterEffect`, 갈라테아는 `if #g>0` 이 `SendtoDeck` **뒤**에 있다는
사실이다. 수만 늘리지 않고 **각 근거를 따로** 단언한다.

#### 🔴 기준 HEAD 에서도 **이미 실패하던** 시험들 — 구분해서 적는다

기준 HEAD (`73696f74`) 를 **별도 worktree 로 체크아웃해 직접 돌려** 확인한
것이다 (데이터 · 스크립트는 symlink 로 같은 것을 쓴다). 아래는 6-BF 의
변경과 **무관하게** 그 시점에 이미 실패하던 시험이다.

| 시험 | 왜 실패하는가 | 6-BF 와의 관계 · 처리 |
| --- | --- | --- |
| `test_archetype_condition.py::test_c` 의 `len(vocabulary.archetypes) == 616` | 그 수는 `data/constants` 의 `SET_*` 줄 수다 (`ScriptConstants.load`). 지금 **617** 이다 | 🔴 **무관.** 6-BF 는 그 디렉터리를 한 글자도 바꾸지 않았다. 전에 데이터가 갱신되면서 어긋났다. **수만 617 로 고치고** 그 사실을 그 자리에 적었다 |
| `test_skeleton_revival_and_longirsu.py::test_e04` | `inspect.getsource(agent.bounded_search)` 의 **원문 전체**에서 카드 ID 를 찾는다. `73696f74`(6-BE)이 `UseRecord.card_id` 의 **칸 설명문**에 `"[21441617]"` 를 "이 꼴을 되파싱하지 마라" 의 예시로 적었다 | 🔴 **무관.** `git log -S "21441617" -- agent/bounded_search.py` 가 `73696f74` 를 가리키고, 6-BF 는 그 파일을 **한 글자도** 바꾸지 않았다. **고쳤다** (아래) |
| `test_resolution_outcome_four_cases.py::test_n06` | `ResolutionSkip.canonical_state()` 가 **4-tuple** 인데 3-tuple 로 비교한다. 넷째 칸 `when_target_unusable` 은 **6-AQ**(커밋 `29da14e4`)가 더했고 그 Phase 가 이 줄을 고치지 않았다 | 🔴 **무관.** `engine/effect/definition.py` 는 이번에 바뀌지 않았다. **고쳤다** |
| `test_resolution_outcome_four_cases.py::test_n05` | 생략을 선언한 효과 목록이 셋으로 적혀 있는데 **6-AQ** 가 스켈레촌 ① 을 더해 넷이 되어 있었다 | 🔴 **절반만 6-BF 다.** 스켈레촌은 6-AQ, 갈라테아는 6-BF 다. **둘을 함께 적어** 고쳤고 어느 Phase 가 어느 항목을 더했는지 그 자리에 썼다 |
| `test_trigger_window_completion.py::test_d05` · `test_f02` | `/combo` **요약 응답**에 `"실행 N걸음 · 상태 변경 M걸음"` 과 `"지원하지 않아 후보가 되지 못한 것이"` 가 있다고 본다. 지금 요약은 그 줄을 싣지 않는다 (걸음 수는 상세 첨부로 갔고, 요약은 `"🔴 미지원 1건 …"` 으로 적는다) | 🔴 **무관하고, 고치지 않았다.** 기준 HEAD 에서 **같은 문장으로** 실패한다 (실측 비교). 이것은 `/combo` **출력 형식**에 대한 판단이고 6-BF 의 범위가 아니다 — 수를 맞추려고 요약의 계약을 이 Phase 에서 다시 쓰지 않는다 |

🔴 **고친 것과 고치지 않은 것의 기준.** 수나 목록이 **한 항목 늘어난**
자리는 근거를 적어 고쳤다. 반면 **무엇이 출력에 실려야 하는가**를 다시
정해야 하는 자리는 6-BF 가 건드리지 않고 **사실만 적었다** — 그 판단은
그 출력 형식을 바꾼 Phase 의 몫이다.

`test_e04` 의 고침은 **단언을 약하게 하지 않는 쪽**을 골랐다. 지키려는
사실은 "탐색기에 정답 수순을 **하드코딩하지 않았다**" 이고 설명문은 코드가
아니므로, `ast` 로 **그 자체로 한 문장인 문자열**(머리말 설명문 · 칸
설명문)만 걷어내고 나머지 전부를 본다 — **값으로 쓰이는 문자열은 남으므로**
고정 경로 이름을 코드에 적으면 여전히 걸린다. (첫 줄만 빼는 것으로는
부족했다: 실측으로 칸 설명문이 남았다.)

### 7.4 남은 미지원과 **다음 장애**

* 🔴 **자율 탐색이 최단 경로(5수)를 찾지 못한다.** 7수 경로로 닿는다
  (§4.5). 깊이 4 의 디베르 갈래가 기본 예산에서 다섯째 수를 받지 못하는
  것이 **다음 장애**이고, 그것은 보관 상한을 키우는 문제가 아니라 **깊이
  우선 탐색이 어느 갈래를 먼저 펼치는가**의 문제다.
* `SelectYesNo` 의 「아니오」 갈래 — 세트를 거절하는 결과를 표현하지 못한다.
* 바벨이 **앞면으로** 깔린 판에서는 ② 도 ③ 도 쓸 수 없다 (③ 미지원).
* 엑스트라 덱 몬스터를 대상으로 하는 갈래는 **거절**된다 (반환 자리가 없다).
* 세트한 카드의 **발동**은 미지원이다 (`activate_card` 타이밍 계층 없음).
* 상대 턴 · 체인 경계(`BreakEffect`) · 무효화 계층 · 전투 · 라이프 · 금제 ·
  턴 종료는 여전히 범위 밖이다.
* **후속 과제로 남긴 것**: 기본 덱 저장 · 패 자동 보충 · 영상 학습 ·
  EDOPro 통합.

---

## 8. 기존 보고서 정정 안내

과거 기록은 지우지 않았다. 아래가 **지금 틀린** 문장들이다.

| 문서 · 절 | 당시 문장 | 지금의 사실 |
| --- | --- | --- |
| `orcust-open-development-search.md` §13.10 | "기준점 셋(디베르 개체 둘 · 성장)은 아직 후속 기회를 못 받는다 — 전체 보관 상한 때문이다" | 🔴 **원인이 그것만은 아니었다.** 기준점별 보관 상한 12 **자신**이 디베르 갈래를 깊이 4 에서 끊고 있었다. 16 으로 올리면 같은 전체 상한에서 깊이가 6 → 7 로 늘고 갈라테아 ② 에 닿는다 (§4.3) |
| `orcust-open-development-search.md` §13.10 | "최대 깊이가 8 → 6 으로 줄었다" | 그때 사실이었다. 지금 기본값에서 **7**이다 (§4.3 표) |
| `orcust-open-development-search.md` §6 (6-AP) 계열의 "갈라테아 ×2 는 후보로 생성된다" | — | 그대로 참이다. 🔴 다만 그때 **그 뒤에 할 수 있는 일이 없었다**는 사실은 적혀 있지 않았다 — 갈라테아 ② 가 등재되지 않았고, 보류 목록에도 나타나지 않았다 (§1.2 의 장애 1) |
| 6-M 보고서의 "`RETURN_TO_DECK` 이 엑스트라 덱 몬스터를 거절한다" | — | 그대로 참이고, **이번에 그 길을 실제로 밟는 효과가 생겼다** — `test_d01` 이 그 자리를 지난다 |

🔴 **등재 수를 적은 과거 단언들**(22 · 19)은 그때 사실이었다. 수가 움직인
것은 **읽은 카드가 하나 늘었기** 때문이고, 그 시험들이 지키는 사실은 하나도
약해지지 않았다.

---

## 9. 사용자가 복사할 값 (옵션별)

🔴 **한 줄짜리 명령 전체를 `hand` 에 붙여 넣지 마십시오.** `/combo` 를 고른
뒤 **옵션마다** 아래 값을 넣습니다.

**`hand`**

```
69811710, 14558127, 23434538, 10045474, 24224830
```

**`recipe`**

```
메인: 69811710 x3, 57835716 x3, 4055337 x2, 21441617, 93920420, 27918365, 72270339, 14558127 x3, 23434538 x2, 42141493 x3, 94145021 x3, 90351981, 99674361, 66328392 x3, 94845588, 80845034, 24224830 x2, 65681983, 81439173, 10045474 x3, 49299410, 703897, 53329234, 엑스트라: 73391962, 46396218, 93854893 x2, 48835607, 30741503 x2, 39752820, 13117073, 65741786, 29301450, 76145142, 74820316, 86066372, 4280258
```

**`search`** → `auto` · **`results`** → `3` · **`followups`** → `6`

* `line` 은 **비워 둡니다** (`search:auto` 와 함께 주면 거절합니다).

---
---

# Phase 6-BG 후속 — 세트의 남은 처리와 **출력 경로 끝까지**

기준 HEAD: `fc47db41` (6-BF 의 마지막 커밋). 아래는 **그 뒤에** 한 일이고,
6-BF 의 본문은 지우지 않았다 — 지금 틀린 문장은 §17 의 표에 적는다.

🔴 **이번 작업의 질문은 "구현했는가" 가 아니라 "사용자에게 닿는가" 였다.**
6-BF 는 갈라테아 ② 를 엔진에서 해결했고, 자율 탐색이 그 경로를 찾는 것까지
보였다. 이번에는 그 뒤를 전부 실제로 돌려 **요약 · 첨부 · 사이트 계획까지
같은 후보를 가리키는지** 재고, 그 과정에서 6-BF 의 구조적 오류 하나를
찾아 고쳤다.

---

## 10. 한눈에 — 고친 것 셋, 확인한 것 넷

| # | 무엇 | 왜 (근거) | 어디 |
| --- | --- | --- | --- |
| G1 | `MAY_BE_SET` 이 **빈 칸까지** 본다 | 공식 `s.filter` 가 `IsSSetable` 을 **후보 조건 안**에 적는다. 6-BF 는 빈 칸 절반을 배치 계획에 두었고, 그래서 자리가 없는 판에서 **되돌리기까지 취소됐다** (실측) | `engine/effect/ruling.py` `BoardRuling.explain_set`, `engine/effect/semantics.py` `set_destination_zone` |
| G2 | **세트하지 않는 선택**을 표현한다 | 공식 `s.tdop` 의 `Duel.SelectYesNo`. 6-BF 에서 빈 선택은 `TOO_FEW_SELECTED` 였고 효과 전체가 거절됐다 | `TargetSpec.declinable` → `ResolutionChoice` → `ChoiceOffer` → `ChoiceAsk` → `iter_selections` |
| G3 | 세트 불가의 **사유를 셋으로** 가른다 | 「카드가 없다」 · 「놓을 자리가 없다」 · 「판정하지 못했다」 가 고칠 자리가 다르다 | `EffectExecutor._candidate_verdicts` · `_candidate_shortfall` · `_declined_target` |
| G4 | 필드 존 세트가 **다른 전개**로 남는다 | 6-BE 의 `variant_key` 가 마법 · 함정 존만 읽어, 필드 마법 세트가 「세트 안 함」 과 같은 열쇠였다 | `agent/open_evaluation_v2.py` |
| G5 | 첨부에 **들어가지 않은 추천**을 이름으로 적는다 | 요약에 전개가 둘인데 첨부는 하나다 — 개수만 적으면 어느 쪽이 빠졌는지 읽는 쪽이 번호를 맞춰 봐야 했다 | `app/discord_bot.py` `_autonomous_record` |
| G6 | 사이트 대조가 **표시 형식을 보지 않았다**고 적는다 | `compareFinal` 은 존별 **자리 집합**만 맞춘다 — 세트 카드가 앞면으로 놓여도 `allOk` 가 참이 될 수 있었다 | `deck/site_plan.py` `expect_positions`, `scripts/duel_simulator_verify.js`, `scripts/duel_simulator_driver.js` |
| G7 | 계획의 한계가 **자동 조작 결과에도** 실린다 | `plan["unsupported"]` 가 계획 파일에만 있었다 | `scripts/duel_simulator_driver.js` |

---

## 11. §1 — 출력 경로를 **실제로** 돌려서 추적했다

### 11.1 `/combo` 의 **실효** 기본값 (실측)

| 옵션 | 사용자가 비워 둠 | 실제로 쓰이는 값 | 어디서 |
| --- | --- | --- | --- |
| `results` | `""` | `search_result_count("")` → `(1, '')` → `max_results = max(2, 1) = ` **2** | `app/discord_bot.py` → `app/main.py` |
| `followups` | `""` | `search_followup_count("")` → `(0, '')` → falsy → `actions` 인자를 **넘기지 않는다** → `AUTONOMOUS_DEFAULT_ACTIONS = ` **6** | 같은 자리 |
| `search` | `auto` | 자율 탐색 (목표 카드 없음) | `is_autonomous_search` |
| `line` | `""` | 꽂지 않는다 — 🔴 고정 경로 정책이 **없다** | `opening_wiring(repository, None)` |

🔴 **정정** — 6-BF 보고서 §4.1 · §9 는 이 경로를 `results:3` 으로 측정하고
그 값을 복사용으로 적었다. **사용자가 `results` 를 비워 두면 2 다.** 아래
수치는 전부 `max_results=2` 에서 다시 쟀다 (§18 에 복사용 값도 고쳐 적는다).

### 11.2 여섯 칸을 지난다 — 칸마다 **실측**

입력: `hand = 69811710,14558127,23434538,10045474,24224830`,
`recipe = docs/orcust-azamina-note.ydk` (메인 **40**장 · 엑스트라 **15**장 ·
사이드 0장, 패 5장이 전부 메인에 있다 — 기르수 ×3 · 우라라 ×3 · 증G ×2 ·
무한포영 ×3 · 지명자 ×2), `search = auto`, 나머지 **기본값**.

| 칸 | 실측 |
| --- | --- |
| ① 자율 탐색 | 74 노드 · 깊이 **7** · 10.1초 · 후보 **28**건 · 선택 분기 10 · 중복 제거 0 · 종료 `BUDGET_EXCEEDED` |
| ② 갈라테아 ② 를 쓴 후보 | **결과 24** 하나. depth 7 · `verified=True` · `SZONE=[(703897, 'FACEDOWN')]` · `FZONE=[]` |
| ③ 비교 · 추천 | `recommended = [결과 17, 결과 24]` — **공동 추천**, 사유는 "필드 구성이 서로 바뀌어 포함 관계가 아니다 (비교 불가)" |
| ④ 요약 | 두 후보의 **최종 필드가 모두 실린다.** 결과 24 줄: `자신 마법·함정 존: 오르페골 클리막스 [703897] 뒷면/FACEDOWN` · `쥔 카드 5 (패 4 + 세트 1)` |
| ⑤ 대표 · 첨부 | `결과 17` 의 재실행 기록 하나 (`combo-replay.json` 90 KB · `combo-replay.html` 889 KB · `combo-detail.txt` 49 KB). 그 사실이 요약에 한 줄로 적힌다 |
| ⑥ 사이트 계획 | `결과 24` 의 기록으로 따로 돌려 확인했다 — §15 |

### 11.3 요청이 물은 네 가지에 **직접** 답한다

1. **기본 설정에서 발견되는가** — 그렇다. 7단계 경로가 기본 예산에서
   나온다 (결과 24, `verified=True`).
2. **최종 추천에 포함되는가** — 그렇다. `recommended` 가 둘이고 그 하나다.
   🔴 **단독 최우수는 아니다** — 결과 17 과 **비교 불가**다.
3. **제외되는 단계가 있는가** — 비교 · 추천에서는 제외되지 않는다.
   **첨부에서는 제외된다**: 뷰어와 JSON 은 기록 하나만 담고, 대표는
   「표시 순서가 가장 앞선 추천」 = 결과 17 이다.
4. **요약 · 상세 · JSON · 시뮬레이터 입력이 같은 후보를 가리키는가** —
   요약과 상세는 **둘 다**, JSON · HTML · 사이트 계획은 **결과 17 하나**를
   가리킨다. 🔴 그 어긋남은 숨겨지지 않는다 (G5 가 나머지 추천 번호까지
   적게 했다):

   ```
   🖥 전개 보기·전개 기록은 **결과 17** 의 재실행 기록입니다
   (🔴 **공동 추천 2개** 가운데 표시 순서가 가장 앞선 것이고, 단독
   최우수라는 뜻이 아닙니다 — 나머지 추천 결과 24 의 전개는 이 기록과
   뷰어에 **들어 있지 않습니다**; 그 최종 판은 위 추천 절에 적혀 있습니다).
   ```

🔴 **"경로가 존재한다" 로 끝내지 않았다.** 결과 24 가 사용자에게 닿는
자리는 **요약과 상세**이고, 닿지 않는 자리는 **뷰어 · JSON · 사이트 계획**
이다. 이번 작업은 그 둘을 가려 적었고, 뷰어를 여러 후보로 늘리는 일은
하지 않았다 (요청 §4 가 "하나만 재생용이면 어느 후보인지 명시" 를 허용한다).

---

## 12. §2 — 세트의 남은 처리

### 12.1 공식 스크립트를 **구조로** 다시 읽었다

```lua
-- c30741503.lua  (저장소 루트에 있는 그 파일)
function s.tdop(e,tp,eg,ep,ev,re,r,rp)
  local tg=Duel.GetTargetCards(e); if #tg==0 then return end
  Duel.SendtoDeck(tg,nil,SEQ_DECKTOP,REASON_EFFECT)          -- ① 무조건
  local og=Duel.GetOperatedGroup(); if #og==0 then return end
  if og:IsExists(Card.IsLocation,1,nil,LOCATION_DECK) then Duel.ShuffleDeck(tp) end
  local g=Duel.GetMatchingGroup(s.filter,tp,LOCATION_DECK,0,nil)   -- ② 후보
  if #g>0 and Duel.SelectYesNo(tp,aux.Stringid(id,1)) then          -- ③ 임의
    Duel.BreakEffect(); local sg=g:Select(tp,1,1,nil); Duel.SSet(tp,sg) end
end
function s.filter(c)
  return c:IsSetCard(SET_ORCUST) and c:IsSpellTrap() and c:IsSSetable()
end
```

세 가지가 **구조로** 읽힌다.

* ① **되돌리기는 조건이 없다.** 세트가 어떻게 되든 일어난다.
* ② **세트가 「실패」 하는 갈래가 없다.** 일어나는지 아닌지는 `s.filter`
  (`IsSSetable` 포함) 가 후보를 몇 장 내는가로 **전부** 결정된다.
  `IsSSetable` 은 「그 자리에 놓을 수 있는가」 와 「카드가 세트를 금지하지
  않는가」 를 **함께** 묻는다.
* ③ 후보가 있어도 **하지 않을 수 있다** (`SelectYesNo`). 하기로 하면
  **정확히 1장** (`Select(tp,1,1,nil)`).

### 12.2 6-BF 의 구조적 오류 — 실측으로 잡았다

6-BF 는 `IsSSetable` 을 **반으로 갈라** 카드 쪽 절반만 관문에 두고
(`MAY_BE_SET`), 빈 칸 절반은 배치 계획(`effect_set_procedure(...).plan_for`)
에 맡겼다. 계획 단계의 거절은 **효과 전체의 거절**이므로 (ADR-008 의
전부-아니면-무), 자리가 없는 판에서 이렇게 끝났다:

```
해결: code=ValidationCode.CANDIDATE_NOT_ELIGIBLE
  체인1 P0 30741503:e[1] 대상 @primary=[#16] 를 해결하지 못했습니다:
  #0 를 세트할 수 없습니다: SZONE 에 빈 칸이 없습니다.
판 후: … REMOVED=57835716/FACEUP     ← 🔴 되돌리기까지 취소됐다
```

공식에서는 되돌리기가 무조건이므로 **틀린 결과**다. 🔴 그리고 6-BF 는 그
가름을 `RuleQuestion.MAY_BE_SET` 의 설명에 *"빈 칸은 이 질문이 아니다"* 라고
**적어 두었다** — 그 문장을 정정 표시와 함께 고쳤다.

### 12.3 고친 것 — 세 자리

**G1. `MAY_BE_SET` 이 판을 본다** (`BoardRuling.explain_set`). 걸음 둘이고
순서가 규칙이다 — ① 등재된 카드 사실(`_explain_fact`)이 `TRUE` 가 아니면
거기서 끝낸다, ② 종류가 목적지를 정하고
(`set_destination_zone`: `type_names` 에 `FIELD` → `FZONE`, 그 밖 → `SZONE`)
그 존의 빈 칸을 본다. 🔴 순서가 뜻을 가진다: 막는 카드가 있어 ① 이
`UNKNOWN` 인 판에서 빈 칸을 세어 `FALSE` 로 내리면 **확인된 모름이 확정
거절로 바뀐다.**

🔴 **목적지를 가르는 자리를 하나로 모았다.** 실행기(`_plan_set_spell_trap`)
가 `"FIELD" in kinds` 로 절차를 고르고 판정기가 같은 질문을 해야 하므로,
두 벌로 적으면 **판정한 존과 놓는 존이 갈릴 수 있다.**

**G2. `TargetSpec.declinable`** — 공식 `SelectYesNo` 를 **장수와 다른 축**
으로 선언한다. 🔴 `minimum=0` 으로 뭉개지 않았다: 기준점 정책들은 정확히
`minimum` 장만 집으므로 (`agent.choice._take`) 0 으로 바꾸면 **세트가 아예
일어나지 않는다.** 공식도 둘을 따로 적는다 (`SelectYesNo` + `Select(1,1)`).

빈 선택이 들어오면 `_ask_for_choice` 가 `_short_selection` **앞**에서
`_VacantTarget` 을 만든다 — 그 순서가 "모자란 선택" 과 "하지 않기로 한
선택" 을 가른다. 탐색 쪽은 `ChoiceAsk.declinable` 을 읽어 `iter_selections`
가 **빈 짝도 허용 조합으로** 낸다.

**G3. 사유를 셋으로 가른다.** `_candidate_verdicts` 가 관문 답을
`permitted` · `unknown` · **`refused`** 로 나눈다 (6-BF 는 `FALSE` 를 세지
않았다). `_candidate_shortfall` 이 그 수로 문장을 가른다:

| 판 | 문장 |
| --- | --- |
| 조건에 맞는 카드가 덱에 없다 | "조건에 맞는 카드가 하나도 없었습니다 (후보 0장을 전부 확인했습니다)" |
| 카드는 있는데 놓을 자리가 없다 | "조건에 맞는 카드 2장을 전부 확인했지만 그중 쓸 수 있는 것이 없었습니다: #0: P0 의 SZONE 5칸이 모두 차 있어…" |
| 판정하지 못했다 | 위 문장 뒤에 "판정하지 못한 후보: #28: …" 이 붙고, 결과의 `unchecked_rules` 에 `gated-candidate-eligibility` 가 남는다 |

🔴 **모름을 조용히 넘기지 않는다.** 「하지 않기로 했다」 가 정상 해결이
되었으므로, 그 자리의 모름이 사라질 수 있었다 — `_VacantTarget.unchecked`
가 그 이름을 들고 계획의 마지막 걸음(`_Step.blind`)에 실려 결과까지 간다.
못 한 덱 정리를 싣는 **같은 칸**이다.

### 12.4 여섯 판을 **실측했다**

전개는 전부 같다 (기르수 일반 소환 → 기르수 ① → 디베르 ① → 갈라테아 링크
소환 → 갈라테아 ②). 판만 손으로 바꿨다.

| 판 | 되돌리기 | 세트 | 결과 코드 | 비고 |
| --- | --- | --- | --- | --- |
| A. 평소 (SZONE 빈 칸) | ✔ | 클리막스 → `SZONE[0]` 뒷면 | `OK` | 6-BF 와 같다 |
| B. SZONE 5/5 | ✔ | **바벨 → `FZONE[0]` 뒷면** | `OK` | 🔴 6-BF 는 **효과 전체 거절**이었다. 공식에서는 클리막스가 후보에서 빠지고 바벨이 남는다 |
| C. SZONE 5/5 + FZONE 에 바벨 (덱에 후보 없음) | ✔ | 없음 | `OK` | 후보 0장 → 세트만 생략 |
| D. FZONE 에 바벨 · SZONE 여유 | ✔ | 클리막스 → `SZONE[0]` | `OK` | |
| E. FZONE 에 **다른** 카드 · SZONE 여유 | ✔ | 클리막스 → `SZONE[0]` | `OK` | 바벨은 `UNKNOWN`, 클리막스가 `TRUE` → 후보가 남는다 |
| F. FZONE 에 다른 카드 + SZONE 5/5 | ✔ | 없음 | `OK` + `unchecked_rules` | 🔴 6-BF 는 `RULE_NOT_IMPLEMENTED` 로 **되돌리기까지 취소**했다 |

F 판의 실제 결과 문장 (전문):

```
30741503:e[1] 를 적용했습니다 (3건). @set 를 고르지 않았습니다 — 조건에
맞는 카드 2장을 전부 확인했지만 그중 쓸 수 있는 것이 없었습니다: #0: P0 의
SZONE 5칸이 모두 차 있어 세트할 자리가 없습니다 (Card.IsSSetable 이 그
자리를 함께 봅니다). 그 대상을 쓰는 일은 하지 않고 나머지 일은 그대로
수행했습니다. 판정하지 못한 후보: #28: P0 의 FZONE 에 이미 카드가
있습니다. 공식 처리는 앞의 필드 마법을 묘지로 보내는 것인데 이 엔진에 그
경로가 없습니다: field-spell-replacement (앞의 필드 마법을 묘지로 보내는
처리 — RULE-SPELLTRAP-006).

unchecked_rules = (… , 'gated-candidate-eligibility (후보를 그 조작으로
움직일 수 있는지 확인되지 않았다)')
```

### 12.5 바벨의 필드 존 — **보류의 근거**

룰북 `RULE-SPELLTRAP-006` (`data/rules/documents/sd-rulebook-en-v10.json`,
인쇄 29쪽) 원문:

> These cards go in your Field Zone and stay there. Each player can have 1
> Field Spell Card on their own side of the field. **To use another Field
> Spell, send your previous one to the Graveyard.** … These cards may be
> placed face-down in the Field Zone, but are not active until flipped
> face-up.

즉 공식에서는 **놓을 수 있다** — 앞의 필드 마법을 묘지로 보내면서. 이
저장소에 그 교체 경로가 **없다.** 그래서 ① `FALSE`(「공식적으로도 못
한다」) 로 적지 않고 ② `UNKNOWN` 으로 보류하며 ③ 규칙 이름
(`field-spell-replacement`) 을 함께 내보낸다. 🔴 **성공으로 기록하지
않았고, 지어내서 구현하지도 않았다.**

### 12.6 발동 시점과 해결 시점

6-BF 가 세운 가름을 **그대로 두었다** — 이번에 한 글자도 바꾸지 않았다.

| 시점 | 무엇을 보는가 | 근거 |
| --- | --- | --- |
| 발동 | 제외된 앞면 기계족 하나의 **존재**만 (`s.tdtg` 의 `IsExistingTarget`) · 바벨이 앞면으로 깔려 있지 않은가 (`s.tdcon1`) | `TargetSpec.checked_at_activation=False` 가 세트 후보를 발동 조건에서 **뺀다** |
| 해결 | 그때의 덱에서 세트 후보를 센다 (`s.tdop` 의 `GetMatchingGroup`) · 각 후보의 `IsSSetable` 을 **판과 함께** 묻는다 | `chosen_at_resolution=True` · `gated=True` → `explain_set` |

🔴 **G1 이 이 가름을 더 뚜렷하게 만들었다.** 빈 칸은 판에 달려 있으므로
**해결 시점의 질문**이고, 발동 조건은 그것을 보지 않는다 — 공식도
`s.tdtg` 에서 덱을 묻지 않는다.

### 12.7 이번에 하지 않은 것 (범위 밖으로 **남겨 둔** 것)

* 필드 마법 **교체** (앞의 것을 묘지로) — 위 보류의 원인. 구현하지 않았다.
* `Duel.BreakEffect()` (세트 전에 체인 블록을 끊는 처리) — 이 저장소에
  그 계층이 없다. 6-BF 의 §2.4 와 같은 상태다.
* 갈라테아 ③ (유발즉시) — `ACTIVATION_KINDS_IN_SCOPE` 밖. 그대로다.
* 효과 실행기의 **광범위한 재설계** — 하지 않았다. 바꾼 것은 ① 판정 질문
  하나(`MAY_BE_SET`), ② 선언 칸 하나(`declinable`)와 그것을 읽는 네 자리,
  ③ 사유 문장을 가르는 헬퍼 둘이다. 전부-아니면-무(ADR-008)도,
  `OperationOutcome` 의 세 값도 건드리지 않았다.

---

## 13. §3 — 비교 · 중복 제거 · 대표 선정

### 13.1 고친 것 — 필드 존이 보이지 않았다

6-BE 의 `measure_v2` · `variant_key` 는 `Zone.SZONE` **하나만** 읽었다.
결과:

* `set_cards` — 필드 마법을 세트한 전개도 **0** 이었다.
* `variant_key` 의 뒷면 목록 — `(card_id, 칸번호)` 였고 **존 이름이
  없었다.** 그래서 ① 필드 존 세트가 「세트 안 함」 과 **같은 열쇠**가 되어
  중복 제거에서 지워질 수 있었고, ② 두 존의 같은 번호 칸이 **같은 자리**로
  읽혔다.

지금은 두 존을 다 읽고 열쇠에 **존 이름**을 함께 넣는다. 실측 (새 시험
`test_h06`):

| 판 | `set_cards` | `set_reactive` | `core_key` | `variant_key` |
| --- | --- | --- | --- | --- |
| 클리막스 → SZONE | 1 | 1 | 같다 | **다르다** |
| 몬스터 5장 + 바벨 → FZONE | 6 | **0** | 같다 | **다르다** |

### 13.2 요청이 요구한 여섯 가지에 하나씩

1. **FZONE 을 포함한 최종 필드가 누락되지 않는다** — 위 표. `set_cards`
   가 필드 존 세트를 센다.
2. **세트한 결과와 세트하지 않은 결과를 합치지 않는다** — `variant_key`
   가 다르다. 🔴 `core_key` 는 **그대로 세트를 보지 않는다** (6-BE 의 가름을
   바꾸지 않았다) — 다양성 배분이 세트 변형에 재생 슬롯을 다 쓰지 않게 하는
   정책이고, 차이는 `variant_key` 가 들고 있다.
3. **같은 최종 상태라도 사용 기록 · 제약이 다르면 보존한다** —
   `variant_key` 가 `bodies_with_use_record` 를 들고 있고, 요약은 기록된
   제약을 그대로 적는다 (실제 출력: 결과 24 는 `card_name [30741503] ×1` ·
   `summon [30741503] link ×1` 이 더 있다).
4. **손패 세트 순서 차이로 밀려나지 않는가** — 실측: 이 입력의 28 후보에서
   **중복 제거 0건** (`deduped=0`). 즉 이번 판에서는 그 일이 **일어나지
   않았다.** 🔴 "일어날 수 없다" 가 아니라 "이 입력에서는 없었다" 다.
5. **세트된 카드는 세트된 자원으로** — `set_cards` 가 센다. `set_reactive`
   는 **종류만** 본다 (함정 · 속공마법): 클리막스는 1, 바벨(필드 마법) 과
   몬스터는 0. 🔴 **발동을 검증하지 않은 카드를 확정 방해로 합산하지
   않는다** — 요약이 그것을 `[B 잠재, 우열에 쓰지 않음]` 으로 적고, 비교
   축에 넣지 않는다 (실제 출력 그대로).
6. **최선이라고 부르지 않는다** — 요약이 적는 그대로다: `🔴 **전역 최적
   전개가 아닙니다**` · `🔴 **공동 추천 2개** — 네 축으로는 우열이 가려지지
   않았습니다` · `**비교 불가**입니다 — … 같다는 뜻이 아니고 현재 기준으로
   **우열 불명**입니다`. 🔴 **억지 순위를 만들지 않았고**, 서로 다른 최종
   상태 둘이 그대로 대표 목록(기본 개수 2)에 들어갔다.

### 13.3 가산점을 주지 않았다 — 값으로 확인

* 카드 ID 를 읽는 자리가 평가에 **없다.** `measure_v2` 가 쓰는 것은
  `CardFacts` 의 **종류** 값들이고 (토큰인가 · 효과 몬스터인가 · 함정 ·
  속공마법인가 · 인쇄된 효과 수), 어느 카드가 좋은지는 적혀 있지 않다.
* 추천 둘은 **상태가 달라서** 둘이다 (필드 구성이 서로 포함 관계가 아니다),
  갈라테아를 쓴다는 이유로 올라간 것이 아니다.
* 고정 수순 주입 없음 — `line` 을 비워 두면 `opening_wiring(repository,
  None)` 이므로 `ComboLine` 의 해결 선택 선호가 **꽂히지 않는다.**

---

## 14. §4 — Discord 요약과 재생 기록

| 요청 | 확인 결과 |
| --- | --- |
| 요약의 전개와 첨부의 전개가 같아야 한다 | 요약은 **둘**, 첨부는 **하나**다 (뷰어 · JSON 이 기록 하나만 담는다). 🔴 그 어긋남을 숨기지 않고, **어느 후보가 빠졌는지**까지 적게 했다 (G5) |
| 하나만 재생용이면 어느 후보인지 명시 | 적는다 — §11.3 의 인용 |
| 재실행 실패 후보를 성공처럼 내보내지 않는다 | `recommended` 는 `Exclusion.NONE` 인 후보만이고, 재생 검증을 통과하지 못한 후보는 `Exclusion.NOT_VERIFIED` 로 빠진다. 기록을 만들지 못하면 `replay=None` · `ReplayState.BUILD_FAILED` 이고 그 사실이 문장으로 나간다 |
| 고정 경로 · 정적 계획이 대신하지 않는다 | 실제 출력: `🔴 이 응답에는 **자율 탐색 결과만** 있습니다 — first_meaningful 기준점 실행도, 정적 전개 추천도 돌리지 않았습니다 (search:auto 이므로)` |
| 정상 응답은 간결 · 세부 한계는 상세로 | 🔴 **이번에 늘리지 않았다.** 추가한 것은 대표 선정 줄에 들어간 **한 구절**이고, 세부 한계(판정 문장 · 못 본 규칙 · 사이트 한계)는 `combo-detail.txt` 와 `plan.json` 으로 간다. 기존 요약이 이미 3개 메시지(약 11 KB)라는 사실은 6-BD · 6-BE 의 설계이고, 이번 범위에서 재편하지 않았다 |

---

## 15. §5 — 실제 Duel Simulator 의 세트 표시

### 15.1 로컬 변환은 **실제 기록으로** 확인했다

결과 24 의 재실행 기록(`autonomous_rerun_record`)을 `build_site_plan` 에
넣어 그대로 읽었다.

```json
// 기록의 사건
{"kind": "card_set", "instance": 0, "player": 0, "owner": 0,
 "from_player": 0, "from_zone": "DECK", "to_zone": "SZONE", "to_index": 0,
 "position": "FACEDOWN", "summoned": false}

// 사이트 조작
{"op": "move", "card": "main-5", "step": 7, "event": 7, "from": "Deck",
 "to": "Spell & Trap Zone1", "position": "FACEDOWN", "face_down": true,
 "why": "오르페골 클리막스 이동", "expect": "→ Spell & Trap Zone1",
 "basis": "engine:event#7.card_set", "n": 17}

// 계획이 들고 가는 "대조하지 않는 것"
{"face_down": [{"slot": "main-5", "zone": "Spell & Trap Zone1"}],
 "compared": false,
 "why": "표시 형식(앞면 · 뒷면)은 **대조하지 않았습니다.** …"}
```

* **일반 마법 · 함정 존과 필드 존을 가른다** — `Spell & Trap Zone{번호}`
  대 `Field Zone` (번호 없음: 사이트에 한 칸뿐이다). 합성 기록으로 양쪽을
  재는 시험을 넣었다 (`test_site_plan.py::test_bg01`).
* **카드 개체가 섞이지 않는다** — 자리(`main-5`)로 묶으므로 같은 이름이
  여러 장이어도 갈린다. 기존 `deck_image_registry` 경로를 그대로 쓴다.
* **토큰 처리도 그대로다** — `token_created` · `token_vanished` 는
  `unsupported` 에 남고 (덱 이미지에 없는 카드라 자리를 묶을 수 없다),
  이번에 바꾸지 않았다.
* 🔴 **새 HTML 뷰어를 만들지 않았다.** 기존 `deck/site_plan.py` ·
  `deck/site_session.py` · `scripts/duel_simulator_driver.js` 경로만 썼다.

### 15.2 "이동만 성공" 이 "재현됐다" 로 읽히던 자리를 고쳤다 (G6)

`compareFinal` 은 존마다 **카드 자리의 집합**만 맞추고 앞면/뒷면은 읽지
않는다. 그래서 세트 카드가 앞면으로 놓여도 `allOk` 가 **참**이 될 수 있었고,
자동 조작의 결과만 읽는 쪽에는 그 사실이 전해지지 않았다
(`_SET_POSITION_NOTE` 는 `plan.json` 에만 있었다).

| 칸 | 지금 |
| --- | --- |
| `allOk` | 그대로 — 자리는 실제로 맞았다. 🔴 거짓으로 만들지 않았다 (그러면 "자리도 틀렸다" 로 읽힌다) |
| `positions` | `{compared: false, face_down: [{slot, zone}…], why: …}` |
| `fullyReproduced` | **거짓** — 뒷면이어야 하는 자리가 하나라도 있으면 |
| `result.notes` | `🔴 자리는 맞았지만 **그대로 재현된 것은 아닙니다** — … 뒷면이어야 하는 자리: main-5→Spell & Trap Zone1.` + `plan.unsupported` 전부 (G7) |

### 15.3 외부 사이트 확인 — **무엇을 했고 무엇이 남았는가**

🔴 **이번에 사이트를 조작하지 않았다.** 아래는 **공개 문서를 읽은 것**과
**로컬 변환**뿐이고, 둘을 섞어 적지 않는다.

| 확인 | 수단 | 결과 |
| --- | --- | --- |
| 사이트가 살아 있는가 | HTTPS GET `/` | **200** |
| 카드 메뉴에 표시 형식 조작이 있는가 | 공개 설명서 `/manual` 5절 | **있다** — "효과의 발동, 무효화, 대상에 취하기, 하이라이트, **표시 형식의 변경**, 카운터 조작, 카드 상세" (우클릭 · 길게 누르기). "그 자리에서 쓸 수 없는 조작은 표시되지 않습니다" |
| 사이트에 「세트」 라는 조작 종류가 있는가 | 공개 설명서 `/manual` 8절 | **있다** — 리플레이 후편집에서 묶을 수 있는 범위를 *"移動・ドロー・セット以外の操作を挟む範囲は指定できません"* 로 적는다 |
| **표시 형식 변경의 하위 항목 이름** | — | 🔴 **설명서에 없다.** 4절은 판 조작이 끌어 놓기라고만 하고, 5절은 메뉴 항목 이름까지만 적는다 |
| 세트가 끌어 놓기로 만들어지는가, 메뉴로 만들어지는가 | — | 🔴 **확인하지 못했다** |

그래서 **구현하지 않았다** — Playwright 가 메뉴를 누르려면 **정확한 항목
이름**이 필요하고, 확인하지 못한 이름을 지어내지 않는다 (ADR-006). 대신
① 사람이 할 조작을 문서의 경로 그대로 적어 두고
(`_SET_POSITION_NOTE` 에 "우클릭 → 「표시 형식의 변경」"),
② 사이트가 「세트」 를 조작 종류로 들고 있다는 근거를
`SITE_SET_OPERATION_EVIDENCE` 에 남겼다.

**남은 일 (사람의 허락이 필요하다)**: 실제 UI 를 한 번 열어 그 메뉴의 하위
항목 이름을 읽는 것. 🔴 그 한 번이 **제3자 서버에 덱 이미지를 올리는 일**을
포함하고, 사이트 안내에 *이용자가 올린 이미지를 스스로 지우는 기능이
없다*고 적혀 있다 (감사 문서 F17). 되돌릴 수 없으므로 혼자 하지 않았다.

🔴 **공유 링크를 만들지 않았고, 이전 링크를 이번 결과로 제시하지 않는다.**
`--share` 는 여전히 기본값이 꺼짐이고, 이번에 한 번도 켜지 않았다.

### 15.4 이후 장면에서도 유지되는가

사이트에서 실제로 확인하지 못했다. 로컬에서 확인한 것은 **계획이 그 뒤의
조작으로 그 카드를 다시 움직이지 않는다**는 것뿐이다 (결과 24 의 세트는
7번째 걸음이고 그 뒤 조작이 없다). 🔴 "유지된다" 고 적지 않는다.

---

## 16. §6 — 검증

### 16.1 새로 넣은 시험 (12건)

`tests/test_galatea_effect_extension.py` **H 절** (6건) — 🔴 재는 것이
"무엇이 일어났는가" 가 아니라 **"무엇이 일어나지 않았는가"** 다.

| 시험 | 고정하는 사실 |
| --- | --- |
| `test_h01_declining_the_set_keeps_the_return` | 세트하지 않기로 골라도 **되돌리기 · 섞기는 남는다** · `card_set` 사건이 **없다** · 그것이 "후보가 없었다" 가 아니라 "고르지 않았다" 로 기록된다 |
| `test_h02_the_decline_is_only_legal_where_the_rule_says_so` | 되돌릴 대상은 `declinable=False`, 세트할 카드는 `True`. 🔴 장수는 **그대로 1~1장** (「하지 않는다」 는 장수가 아니다) |
| `test_h03_a_full_spell_zone_sends_the_set_to_the_field_zone` | SZONE 5/5 에서 클리막스가 후보에서 빠지고 **바벨이 FZONE 에 놓인다** · 되돌리기는 일어난다 |
| `test_h04_no_room_anywhere_skips_only_the_set` | 두 존이 다 막히면 세트만 생략 · **확정 거절 사유**와 **보류 사유**가 따로 적힌다 · 보류가 `unchecked_rules` 에 남는다 |
| `test_h05_the_gate_asks_the_board_not_just_the_card` | 같은 카드 · 같은 등재 사실이 **판에 따라 `TRUE` / `FALSE`** 로 갈린다 · 필드 마법은 다른 존을 본다 |
| `test_h06_a_field_zone_set_is_a_different_development` | FZONE 세트가 `set_cards` 에 세어지고 `variant_key` 가 달라진다 · `core_key` 는 그대로 · 🔴 바벨은 `set_reactive` 에 **들어가지 않는다** |

`tests/test_site_plan.py` (3건) · `tests/test_site_verify.py` (3건)

| 시험 | 고정하는 사실 |
| --- | --- |
| `test_bg01_a_spell_zone_set_and_a_field_zone_set_are_different_places` | `Spell & Trap Zone1` 대 `Field Zone` · 서로의 칸은 비어 있다 |
| `test_bg02_the_plan_says_which_slots_should_end_face_down` | 조작의 `position` · `face_down` · 계획의 `expect_positions.compared is False` |
| `test_bg03_a_face_up_move_is_not_marked_face_down` | 앞면 이동에는 그 표시가 **붙지 않는다** (모든 이동이 "뒷면" 이 되지 않았다) |
| `test_bg01_a_matching_board_is_not_a_reproduced_set` | `allOk is True` **이면서** `fullyReproduced is False` |
| `test_bg02_without_a_face_down_expectation_nothing_changes` | 네 번째 인자가 없는 **옛 호출도 같은 답**을 받는다 |
| `test_bg03_a_wrong_slot_is_still_a_failure` | 표시 형식 보완이 **자리 대조를 약하게 만들지 않았다** |

### 16.2 고친 기존 시험 — **하나**, 그리고 왜 약해진 것이 아닌가

`test_d02_an_unregistered_set_candidate_is_not_waved_through` 가 6-BF 에서
*"판이 하나도 바뀌지 않았다"* 를 고정하고 있었다. 그 문장은 **공식과
어긋난다** (§12.1 ①). 지금 이 시험은 **세 가지를 함께** 고정한다.

1. 세트가 **일어나지 않았다** (두 존이 비어 있다) — `UNKNOWN` 은 허가가
   아니다.
2. 되돌리기는 **일어났다** — 공식 `SendtoDeck` 는 무조건이다.
3. 그 모름이 결과의 `unchecked_rules` 에 **이름으로 남았고** 문장에도
   "판정하지 못한 후보" 로 적혔다.

🔴 **그리고 시험의 판 자체를 고쳤다.** 6-BF 는 조립 층의 `_rulings` 만
좁혔는데, 그러면 **엔진은 여전히 답을 알고 정책만 모르는** 판이 된다 — 그
판에서 엔진이 "후보가 있었는데 고르지 않았다" 로 적는 것은 **정확하다.**
등재 공백을 재려면 엔진과 정책이 같은 표를 못 읽어야 하므로
`lib.OPERATION_RULINGS` 를 좁혔다 (`duel_activator` · `duel_resolver` ·
`_rulings` 가 다 그 이름을 읽는다). 🔴 **단언을 지운 것이 아니라 셋으로
늘렸고, 재는 판을 더 정확하게 만들었다.**

---

## 17. 6-BF 보고서 · 코드 주석 **정정 표**

과거 문장을 지우지 않았다. 아래가 **지금 틀린** 것들이고, 각 자리에 정정
표시를 함께 남겼다.

| 자리 | 당시 문장 | 지금의 사실 |
| --- | --- | --- |
| `engine/effect/semantics.py` `RuleQuestion.MAY_BE_SET` 설명 | "🔴 **빈 칸은 이 질문이 아니다.** … 앞의 절반은 배치 계획이 지키고 …" | 🔴 **틀렸다.** 공식 `s.filter` 가 `IsSSetable` 을 후보 조건 **안**에 적으므로 빈 칸은 「후보가 있는가」 의 일부다. 계획에 두면 그 거절이 **효과 전체의 거절**이 되어 되돌리기까지 취소된다 (실측 · §12.2) |
| `engine/effect/library.py` 갈라테아 ② 머리말 | "둘 다 옮겼지만 **자리가 다르다** — 앞은 계획 단계가 지키고 뒤는 관문이 묻는다" | 🔴 **둘 다 관문이 묻는다** (`BoardRuling.explain_set`) |
| `engine/effect/library.py` `SetSpellTrapOperation` 주석 | "`gated=True` 가 `IsSSetable` 이다 — 그 술어의 **카드 쪽 절반**을 묻는다" | **그 술어 전체**를 묻는다 |
| `engine/effect/library.py` 바벨 `MAY_BE_SET` 사실 노트 | "그 자리에 빈 칸이 있는지는 이 답이 아니라 **배치 계획이 본다**" | 같은 질문의 나머지 절반으로 `BoardRuling.explain_set` 이 **함께 본다** |
| 이 보고서 §4.1 · §9 | `/combo` 기본 입력을 `results:3` 으로 적었다 | 🔴 **사용자가 `results` 를 비워 두면 2 다** (`max(2, 1)`). §11.1 에 실측을 적었고 §18 에 복사용 값을 고쳐 적었다 |
| 이 보고서 §4.5 | 갈라테아 경로를 **결과 24** 로 적었다 | 지금 기본값(`results=2`)에서도 `result.index` 는 **24** 다 (열거 위치는 23). 🔴 **같은 수를 두 뜻으로 쓰지 않는다** — 보고가 가리키는 것은 언제나 `result.index` 다 |
| 이 보고서 §6.2 | 세트 사건의 사이트 변환을 "자리 이동만 만든다 · 표시 형식은 표현하지 못한다" 로 적었다 | 그대로 참이다. 🔴 **덜 적은 것이 있었다** — 그 한계가 `plan.json` 에만 있어서 **자동 조작 결과에는 전해지지 않았다** (G6 · G7 이 고친 자리) |
| 이 보고서 §7.1 | "새 시험 21건" | 지금 **27건** (H 절 6건을 더했다). 사이트 쪽에 6건을 더 넣었다 (§16.1) |

🔴 **6-BF 가 "확인했다" 고 적은 것 중 약해진 것은 없다.** 바뀐 것은 ①
자리가 없는 판의 결과(거절 → 세트만 생략), ② 등재 공백 판의 결과(거절 →
세트만 생략 + 모름 기록) 둘이고, 둘 다 **공식 스크립트의 구조를 근거로**
바꿨다.

---

## 18. 사용자가 복사할 값 (6-BG 기준 · 옵션별)

🔴 **한 줄짜리 명령 전체를 `hand` 에 붙여 넣지 마십시오.** 디스코드에서
`/combo` 를 고른 뒤 **옵션마다** 아래 값을 넣습니다.

**`hand`**

```
69811710, 14558127, 23434538, 10045474, 24224830
```

**`recipe`** — 🔴 **파일 경로가 아니라 아래 내용을 그대로** 넣습니다
(메인 40장 · 엑스트라 15장 · 사이드 0장).

```
#main
69811710
69811710
69811710
57835716
57835716
57835716
4055337
4055337
21441617
93920420
27918365
72270339
14558127
14558127
14558127
23434538
23434538
42141493
42141493
42141493
94145021
94145021
94145021
90351981
99674361
66328392
66328392
66328392
94845588
80845034
24224830
24224830
65681983
81439173
10045474
10045474
10045474
49299410
703897
53329234
#extra
73391962
46396218
93854893
93854893
48835607
30741503
30741503
39752820
13117073
65741786
29301450
76145142
74820316
86066372
4280258
```

**`search`**

```
auto
```

**`results`** · **`followups`** · **`line`** · **`board`** · **`deck`** —
🔴 **비워 둡니다.**

* `results` 를 비우면 **2** 가 쓰이고, 그 2 안에 이번 전개(결과 24)가
  들어간다 — 이 보고서의 모든 수치가 그 설정의 실측이다.
* `followups` 를 비우면 행동 예산 **6** 이 쓰인다.
* 🔴 `line` 은 **반드시 비워 둡니다** — `search:auto` 와 함께 주면
  거절하고, 고정 수순을 주입하는 자리이기도 하다.

### 18.1 그때 보일 것 (실측)

* 요약에 **추천 2개**가 나오고, 둘 다 "비교 불가 · 공동 추천" 으로 적힌다.
* `결과 24` 줄에 7걸음과 `자신 마법·함정 존: 오르페골 클리막스 [703897]
  뒷면/FACEDOWN` 이 적힌다.
* 🖥 줄이 **첨부는 결과 17 이고 결과 24 는 들어 있지 않다**고 적는다.
* 첨부 셋: `combo-detail.txt` · `combo-replay.json` · `combo-replay.html`.
* 요청 전체 약 12초 (실측 12.49초 — 탐색 10.06 · 재생 검증 1.38 · 기록
  0.72 · 그 밖 0.33).

### 16.3 전체 스위트를 **기준 HEAD 와 차집합으로** 비교했다

절차 — 🔴 **반복 실행을 기본 절차로 삼지 않았다.** 전체 스위트는 **한 번**
돌리고, 차집합에 나온 파일만 다시 확인했다.

1. 기준 HEAD `fc47db41` 를 별도 worktree 에 꺼내고 `data/cards.cdb` ·
   `data/constants` · `data/cache` 와 `c*.lua` **12,702개**를 심볼릭
   링크로 걸었다 (6-BF 와 같은 방법).
2. 두 트리에서 `python -m pytest tests -q -n 2` 를 **동시에** 돌렸다.
3. `FAILED` 줄의 집합을 뽑아 차집합을 계산했다.

| | 통과 | 실패 | 건너뜀 | 시간 |
| --- | --- | --- | --- | --- |
| 기준 `fc47db41` | 7468 | **68** | 10 | 41분 37초 |
| 이번 작업 (측정 시점) | 7470 | **78** | 10 | 41분 00초 |

🔴 **"78 > 68" 이 곧 "10건을 깨뜨렸다" 는 뜻이고, 그 10건을 전부 찾아
고쳤다.** 차집합은 정확히 아래 둘이었다 (기준에서 고쳐진 실패는 **0건**).

| 새 실패 | 원인 | 고친 방법 |
| --- | --- | --- |
| `tests/test_open_search.py::test_k09_the_v2_module_holds_no_card_ids_and_no_answer_board` | 🔴 **내가 `agent/open_evaluation_v2.py` 주석에 카드명과 카드군 이름을 적었다** — 그 감사는 평가기가 **덱을 모르는** 계층임을 글자로 지킨다 | 주석을 일반화했다 ("덱에서 필드 마법을 세트하는 효과가 있으면…"). 🔴 감사를 고치지 않았다 |
| `tests/test_open_search.py::test_k01` ~ `test_k13` (9건) | `measure_v2` 가 이제 `FZONE` 을 읽는데, 그 파일의 **대역**(`_V2Resources`) 이 그 존을 흉내 내지 않아 "읽을 수 없다" 로 답했다 | 대역에 `field_zone` 을 더했다 — 진짜 요약은 `FZONE` 을 **언제나** 적으므로 (`OWN_DETAIL_ZONES`) 대역이 어긋나 있던 것이다. 🔴 **단언을 지우거나 약하게 하지 않았다** |
| `tests/engine/test_trigger_normal_path_integration.py::test_c01_the_request_carries_no_mutable_board` | `ResolutionChoice` 의 **필드 집합**을 고정한 시험이고, `declinable` 이 늘었다 | 이름을 더하고 **종류까지 고정했다** (`bool`) — 그 시험이 지키는 사실("판을 주지 않는다")을 값의 종류로 **한 줄 더** 확인한다 |

재확인 (현재 HEAD, 해당 파일 전수 + 이번에 건드린 시험 파일 전부):

```
tests/test_open_search.py
tests/engine/test_trigger_normal_path_integration.py
tests/test_galatea_effect_extension.py
tests/test_site_plan.py
tests/test_site_verify.py
→ 193 passed in 134.57s
```

🔴 **이 "새 실패 0건" 은 두 번째 전체 스위트가 아니라 위 다섯 파일의
재실행으로 받친 결론이다.** 전체 스위트를 다시 돌리지 않은 이유는 요청의
지시(반복 실행을 기본 절차로 삼지 말 것)이고, 고친 뒤 건드린 것이
**주석 한 군데와 시험 파일 둘**뿐이라는 사실이 근거다 —
`agent/open_evaluation_v2.py` 의 변경은 주석이고, 그 파일의 본문을 읽는
감사는 `test_k09` 하나다 (전수 확인).

### 16.4 기준 HEAD 에서도 **이미 실패하던** 68건

6-BF 보고서 §7.2 · §7.3 의 목록과 **같다.** 이번에 하나도 고치지 않았고
하나도 늘리지 않았다. 대표적인 것 셋만 다시 적는다.

| 시험 | 왜 실패하는가 (기준 HEAD 에서도) |
| --- | --- |
| `test_rule_not_implemented_code_audit.py::test_02` | 문자열 수를 고정한 감사다. 기준 HEAD 도 `assert 129 == 125` 로 **같은 수**에서 실패한다 — 🔴 이번 변경이 그 수를 **한 건도** 바꾸지 않았다 (양쪽에서 같은 값을 확인했다) |
| `test_trigger_window_completion.py::test_d05` · `test_f02` | `/combo` 요약 출력 형식 판단이고 6-BF 가 범위 밖으로 둔 자리다. 그대로 남겼다 |
| `test_archetype_compiler.py::test_a` · `test_e` | 카드 자료 갱신으로 카드군 수가 움직였다. 자료 쪽 사실이다 |

### 16.5 요청의 핵심 확인 항목 — 하나씩

| 항목 | 어디서 확인했는가 |
| --- | --- |
| 반환 + 세트 성공 | `test_c*` (6-BF) · §12.4 A · D · E |
| 반환 + 세트하지 않음 | **`test_h01`** · §12.4 C · F |
| 세트 후보 없음 | `test_d04` (6-BF) · §12.4 C |
| 세트 공간 없음 | **`test_h03`** (한 존만 막힘) · **`test_h04`** (두 존 다 막힘) · **`test_h05`** (판정 자체) |
| SZONE 과 FZONE 결과 구분 | **`test_h06`** (평가) · **`test_site_plan::test_bg01`** (사이트) |
| 자율 탐색 → 대표 선정 → 첨부 생성 | `test_g01` · `test_g02` (6-BF) · §11.2 의 실측 여섯 칸 |
| 카드 위치 · 뒷면 표시의 사이트 변환 | **`test_site_plan::test_bg02` · `test_bg03`** · **`test_site_verify::test_bg01`~`03`** · §15.1 의 실제 기록 |
| 요약 · JSON · 재실행 결과 일치 | §11.3 (실제 출력) · §14 |

---
---

# Phase 6-BH 후속 — **고른 후보**를 실제 사이트 재생까지

기준 HEAD: `6a42a6f3` (6-BG 의 커밋). 6-BG 의 본문은 지우지 않았고, 지금
틀린 문장은 §25 의 표에 적는다.

🔴 **6-BG 가 남긴 두 공백을 메웠다.** ① 공동 추천이 둘인데 첨부는 하나였고
사용자가 고를 길이 없었다. ② 표시 형식은 **기대만** 적고 사이트에서 읽지
않았으며, 공유 분기는 여전히 `all_ok` 하나만 보았다 (아래에 값을 두고 위에서
읽지 않는 상태).

---

## 19. 한눈에

| # | 무엇 | 근거 · 자리 |
| --- | --- | --- |
| H1 | **후보 선택** — `/combo` 가 요청 ID 를 내고 `/combo-pick request:<ID> result:<번호>` 가 **그 후보만** 다시 실행한다 | `app/candidate_store.py` (새 파일) · `app/discord_bot.py` `pick_response` · 새 명령 `combo-pick` |
| H2 | 🔴 **고르기가 탐색을 다시 돌리지 않는다** — 그때 그 결과를 보관해 두고 꺼낸다 | `CandidateStore` · `tests/test_candidate_pick.py::test_b04` 가 탐색 함수를 터지게 두고 고정한다 |
| H3 | **실제 사이트의 뒷면 세트를 수행한다** — 조작 바 `Face-down` 토글 + 카드 메뉴 `Set Face-down` | `scripts/duel_simulator_ops.js` (새 파일) · `scripts/duel_simulator_driver.js` |
| H4 | **표시 형식을 사이트에게 물어 확인한다** — 카드 메뉴가 그 상태를 말한다 | `duel_simulator_verify.js` `decidePosition` · `comparePositions` |
| H5 | **토큰을 만든다 · 지운다** — `More → Generate Token` · 카드 메뉴 `Delete Token` | `site_plan` `TOKEN_OPERATIONS` · 드라이버의 두 조작 |
| H6 | **다섯 상태를 가르고 공유를 막는다** — 조작 실행 · 위치 · 표시 형식 · 재현 · 공유 | `compareFinal` → `SiteRunResult` → `SiteShareOutcome` → Discord 한 줄 |
| H7 | **재현에 필수인 미지원**을 따로 센다 (상대 자리 · 자리를 못 준 개체) | `plan["required_unsupported"]` |

---

## 20. §1 — 사용자가 후보를 고르는 방법

### 20.1 두 걸음

```
/combo  hand:… recipe:… search:auto
    → 추천 둘이 요약에 나오고, 마지막에 ↓
    🎞 **다른 추천을 재생하려면** `/combo-pick request:5742c17c result:<번호>`
       — 고를 수 있는 번호: `24`.
/combo-pick  request:5742c17c  result:24
    → 그 후보만 새 초기 상태에서 다시 실행 → JSON · 뷰어 첨부
/combo-pick  request:5742c17c  result:24  share:true
    → 같은 기록 하나로 **실제 사이트 조작**까지
```

🔴 **새 명령 하나와 옵션 셋이 전부다** (`request` · `result` · `share`).
패도 레시피도 다시 받지 않는다 — 다시 받으면 **탐색을 다시 돌리는 길**이
생긴다.

### 20.2 지키는 것 — 실측

| 요청 | 어떻게 | 실측 |
| --- | --- | --- |
| 탐색을 다시 돌리지 않는다 | 보관한 ``SearchResult`` 를 꺼내 **그 경로만** 재실행 | `test_b04` 가 `autonomous_search_opening` 을 터지게 두고 고른다 — 통과 |
| 번호 · 경로가 바뀌지 않는다 | 보관한 객체 그대로 | 결과 17 → 5걸음 · `card_set` 0건 / 결과 24 → **7걸음 · `card_set` 1건** |
| 요청과 후보를 묶는다 | 요청 ID + **만든 사람** | 남의 ID 로 꺼내면 "다른 사람의 것입니다" |
| 없는 후보 · 만료를 가른다 | 버린 ID 를 **기억해** 판정 | 없는 번호 / 만료 / 낸 적 없는 ID / 숫자가 아닌 입력 — **네 문장이 다르다** |
| 재실행 실패를 바꿔치지 않는다 | 기록이 없으면 첨부도 사이트도 없다 | `test_b03` — 다른 후보 번호가 응답에 나타나지 않는다 |
| 같은 후보가 끝까지 간다 | 기록 **하나**가 JSON · 뷰어 · 사이트 계획에 들어간다 | 결과 24 의 계획: 조작 19개 · 뒷면 기대 `main-5 → Spell & Trap Zone1` |
| 기본 동작은 그대로 | `/combo` 는 여전히 표시 순서가 앞선 추천을 첨부하고 **그 사실을 적는다** | 6-BG 의 그 줄 그대로 |

🔴 **후보 번호도 카드도 수순도 코드에 적지 않았다.** 고를 수 있는 번호는 그
탐색의 `ranking.recommended` 를 **읽어** 적고, 시험도 번호를 읽어 쓴다.

🔴 **자체 뷰어를 확장해 대신하지 않았다.** `/combo-pick share:true` 가 **실제
사이트 조작기**를 그 기록으로 부른다.

---

## 21. §2 — 실제 사이트의 세트 조작 (**실측**)

### 21.1 무엇을 열어 보았는가 — 업로드 없이

🔴 **새 이미지를 올리지 않았다.** 사이트 설명서가 말한 샘플 덱은 지금
첫 화면에 없었고 (실측: 파일 입력 하나뿐), 대신 **이미 만들어 둔 공유
리플레이**(6-AZ 가 만든 `/replay/6ZdmBQec`)를 열어 `Manual` 로 바꿨다 —
그러면 그 판(카드 55장)에서 그대로 조작할 수 있다. 기록도 공유도 하지
않았다.

### 21.2 읽은 사실 — 전부 관측값이다

| 사실 | 관측 |
| --- | --- |
| 조작 바에 **`Defense` · `Face-down` · `Stack on top`** 토글이 있다 | `button[aria-pressed]` — 처음 `false` |
| `Face-down` 을 누르면 **`aria-pressed="true"`** 가 된다 | 읽어서 확인 |
| 🔴 그 토글은 **끈적하다** — 드롭 뒤에도 켜져 있다 | 두 번째 드롭에서도 `true` |
| 그 상태로 **덱 → 마법·함정 존**에 끌어 놓으면 뒷면으로 놓인다 | 아래 메뉴로 확인 |
| **덱 → 필드 존**도 같다 | 조작 이력 `#10 · You Deck → Field Zone` |
| **카드 메뉴가 표시 형식을 말한다** — 뒷면이면 `Set Face-up`, 앞면이면 `Set Face-down` | 앞면 마법·함정: `Activate Effect, Negate, Target, Highlight, **Set Face-down**, Add Counter, Card details` / 뒷면: `Target, Highlight, **Set Face-up**, Add Counter, Card details` |
| `Set Face-down` 을 누르면 **뒤집힌다** | 메뉴가 `Set Face-up` 으로 바뀐다 |
| 🔴 **설명서에는 그 하위 항목 이름이 없다** | 6-BG 가 멈춘 자리이고, UI 를 열어 **읽어서** 넘었다 |
| 토큰: `More → **Generate Token**` 이 `Free` 존에 토큰을 만든다 | 새 개체 id 하나(`main-`/`extra-` 가 아닌 **제 id**) · 이력 `#9 · You Summon · Free` |
| 그 토큰의 메뉴에 **`Delete Token`** 이 있다 | `Activate Effect, Negate, Target, Highlight, **Delete Token**` |
| 상대 자리: `Opponent field` 토글을 누르면 드롭 가능한 칸이 **20 → 36** 개가 된다 | 실측 — 🔴 **배선하지 않았다** (§24) |

### 21.3 조작기에 연결한 것

```
덱 → 마법·함정 존 뒷면 세트 : armFaceDown(true) → drag → armFaceDown(false)
                              → readPosition → (앞면이면) cardMenu('Set Face-down')
                              → readPosition 으로 다시 확인
덱 → 필드 존 뒷면 세트       : 같은 순서 (칸 이름만 다르다)
이미 목표 표시일 때          : 🔴 **다시 뒤집지 않는다** — 먼저 읽고, 맞으면 끝
같은 카드 여러 장            : 개체는 `data-card-id` 의 **자리 이름**으로 구분한다
                              (기존 방식 그대로). 토큰은 사이트가 준 제 id 를
                              계획의 이름(`token-<개체번호>`)에 **묶어** 둔다
토큰                         : More → Generate Token / 카드 메뉴 Delete Token
```

🔴 **클릭했다는 사실로 성공 처리하지 않는다.** 드롭 뒤 · 뒤집은 뒤 **매번**
그 카드의 메뉴를 다시 읽어 판정하고, 토큰은 **판에서 사라졌는지**까지 본다.

🔴 **좌표도 이름도 추측하지 않았다.** 칸은 기존 `zoneMap` 이 화면에서 읽고,
메뉴 이름은 위 실측에서 읽은 글자 그대로다.

### 21.4 실제 사이트 확인 — **조작기가 쓰는 그 함수로**

손가락(끌어 놓기 · 카드 메뉴 · 토글 · 표시 형식 읽기)을
`scripts/duel_simulator_ops.js` 로 떼어 내고, 조작기와 확인 스크립트가 **같은
함수**를 쓰게 했다. 그래서 "확인한 것" 과 "도는 것" 이 같은 코드다.

```
$ node scripts/check_site_set_ops.js
  manual-mode ✔ · zones-found ✔ · face-down-armed ✔ (aria-pressed=true)
  face-down-disarmed ✔ · set-landed-in-spell-zone ✔ (main-11)
  set-is-face-down ✔ · face-down-is-idempotent ✔
  control-drop-is-face-up ✔ · menu-flips-to-face-down ✔
  field-zone-set-is-face-down ✔ · generate-token ✔ (새 개체 1개)
  token-menu-has-delete ✔ · delete-token ✔
  → all_ok: true   (업로드 0회 · 기록 0회 · 공유 0회)
```

🔴 **이것은 실제 사이트 확인이다.** 🔴 **다음은 하지 않았다** — 덱 시트를
올려 조작기를 **처음부터 끝까지** 돌리는 일(새 이미지 업로드가 생긴다)과
새 공유 링크 만들기. 요청이 그 둘을 필수 검증으로 삼지 말라고 했고, 올린
이미지는 이용자가 스스로 지울 수 없다.

---

## 22. §3 — 다섯 상태와 공유 차단

### 22.1 6-BG 가 남긴 자리

6-BG 는 `compareFinal` 에 `fullyReproduced` 를 더하고 조작기가 그것을
`fully_reproduced` 로 적게 했다. 🔴 **그런데 위에서 읽지 않았다.**

| 자리 | 6-BG | 지금 |
| --- | --- | --- |
| 조작기의 공유 분기 | `final.all_ok` 하나 | **`final.fully_reproduced`** |
| `deck/site_session.py` 의 `final_ok` | `all_ok` 하나 | 그대로 (② 위치) + **`positions_ok` · `positions_compared` · `positions_mismatched` · `positions_unknown` · `missing_support` · `fully_reproduced`** 를 함께 읽는다 |
| `SiteRunResult.shared` | `final_ok` 까지 | **`fully_reproduced`** 까지 |
| `app/site_share.py` | 상태 넷(없음 · 바쁨 · 실패 · 공유) | 같은 넷 + **판정 여섯 칸**을 그대로 옮긴다 |
| Discord 응답 | 링크 또는 실패 한 줄 | **`🧪 재현 판정: 위치 ✔ · 표시 형식 ✔ → 재현 확인`** 한 줄을 함께 적는다 |

### 22.2 다섯 상태를 가른다

| # | 무엇 | 어디서 |
| --- | --- | --- |
| ① 계획한 조작을 **실행**했는가 | `SiteRunResult.completed` (계획 수와 맞춰 본다) |
| ② 카드 **위치**가 같은가 | `compareFinal` 의 `allOk` → `final_ok` |
| ③ **표시 형식**이 같은가 | `comparePositions` 의 `ok` → `positions_ok` |
| ④ 이 전개를 **재현**했는가 | `fullyReproduced` = ② + ③ + **필수 미지원 없음** |
| ⑤ **공유**해도 되는가 | `shared` = ④ + ① + 실행 ID · 종료 코드 · URL |

### 22.3 「미확인」 을 「맞았다」 로 만들지 않는다

| 판 | ③ | ④ | 공유 | 적는 말 |
| --- | --- | --- | --- | --- |
| 뒷면 기대를 읽었고 뒷면이었다 | ✔ | ✔ | 한다 | 재현 확인 |
| 읽었는데 앞면이었다 | ✘ | ✘ | **막는다** | "표시 형식이 기록과 달라…" + 그 자리 이름 |
| 뒷면 기대를 **읽지 못했다** | ✘ | ✘ | **막는다** | "표시 형식을 확인하지 못해…" |
| 앞면 자리를 읽지 못했다 | ✔ | ✔ | 한다 | 🔴 `compared` 가 **거짓**이고 "일부 미확인" 이라고 적는다 |
| 선언한 자리가 **아예 없다** | ✔ | ✔ | 한다 | 🔴 `compared` **거짓** — 볼 것이 없었다는 사실을 "다 봤다" 로 적지 않는다 |
| 필수 미지원이 있다 | ✔ | ✘ | **막는다** | "재현하는 데 필요한 조작을 하지 못해…" + 그 줄 |

🔴 **뒷면 기대가 없다는 이유만으로 "표시 형식을 다 확인했다" 고 하지
않는다** — 그것이 위 네 번째 · 다섯 번째 줄이다 (`positions.compared`).

🔴 **경고 문자열에 기대지 않는다.** 판정은 전부 구조화된 값이고
(`positions.mismatched` · `required_not_observed` · `missing_support`),
문장은 그 값에서 만든다.

🔴 **「재현 성공」 은 엔진 기록과 사이트 상태가 같다는 뜻이다.** 사이트가
유희왕 규칙을 검증했다는 뜻이 아니고, 응답의 그 줄이 그렇게 적는다.

---

## 23. §4 — 이 전개에서 실제로 막히는 조작: 토큰

### 23.1 먼저 확인한 것

기본 입력의 갈라테아 후보(결과 24)의 기록에는 토큰 **둘**이 있다 (실측):

```json
{"kind":"token_created","instance":95,"card_id":46647145,"owner":0, …}
{"kind":"token_created","instance":96,"card_id":46647145,"owner":1, …}
```

최종 판에서 95 는 **자신** 몬스터 존, 96 은 **상대** 몬스터 존이다. 즉
세트 표시만 고쳐도 **토큰 때문에 재현이 막힌다** — 요청이 먼저 확인하라고
한 그 자리다.

### 23.2 한 것과 못 한 것

| 토큰 | 사이트 지원 | 이번에 | 결과 |
| --- | --- | --- | --- |
| #95 (자신) | `More → Generate Token` + 끌어 놓기 | **연결했다** | 계획에 `generate_token` 조작이 생기고, 뒤의 이동이 그 개체를 자신 몬스터 존으로 옮긴다 |
| #96 (상대) | `Opponent field` 토글로 칸이 열린다 (실측) | **배선하지 않았다** | 🔴 `required_unsupported` 로 올라가 **재현 미완료 · 공유 차단** |

🔴 **6-BG 까지 토큰은 "덱 이미지에 없는 카드라 자리를 묶을 수 없습니다" 로
`unsupported` 에 있었다 — 그 문장은 틀렸다.** 사이트에 조작이 있다.

🔴 **토큰을 생략하거나 다른 카드로 바꾸지 않았다.** 상대 자리의 토큰은
계획이 **자리를 주지 않고** (주면 뒤의 이동이 그것을 자기 쪽에 놓으려
든다 — 실측으로 그랬다) 필수 미지원으로 적는다.

### 23.3 그래서 지금 이 후보는

```
결과 24 의 사이트 계획: 조작 19개 · 뒷면 기대 1곳 · 필수 미지원 2건
  🔴 사건 #2 의 token_created: 상대 자리의 토큰 #96 은 이 계획이 놓지 않습니다
  🔴 최종 판의 상대 MZONE 에 #96 … 이 계획은 상대 자리를 놓지 않습니다
→ ④ 재현 미완료 → ⑤ **공유하지 않는다**
```

🔴 **검증을 통과시키려고 더 쉬운 전개로 바꾸지 않았다.** 막히는 자리를
그대로 두고 **막힌다고 적는다.**

---

## 24. §5 — 검증: **실제 사이트**와 **모의**를 가른다

### 24.1 실제 사이트에서 확인한 것 (업로드 0회 · 공유 0회)

`node scripts/check_site_set_ops.js` — 조작기가 쓰는 그 함수로, 이미 있는
공유 리플레이를 `Manual` 로 바꿔 돌렸다. **13개 확인 전부 통과**
(§21.4 의 목록).

| 요청의 핵심 항목 | 어디서 확인 |
| --- | --- |
| 마법·함정 존의 실제 뒷면 세트 | `set-landed-in-spell-zone` · `set-is-face-down` |
| 필드 존의 실제 뒷면 세트 | `field-zone-set-is-face-down` |
| 조작 후 **관찰값**으로 위치 · 표시 형식 확인 | 모든 확인이 `readPosition`(카드 메뉴) 과 좌표 관측을 쓴다 |
| 이미 목표 표시면 다시 뒤집지 않는다 | `face-down-is-idempotent` |
| 토큰 조작 | `generate-token` · `token-menu-has-delete` · `delete-token` |

### 24.2 모의로 확인한 것 (브라우저를 열지 않는다)

| 항목 | 시험 |
| --- | --- |
| 공동 추천의 각 후보가 **서로 다른 올바른 기록**을 준다 | `tests/test_candidate_pick.py::test_c01` (실제 엔진 · 실제 덱) |
| 선택부터 첨부 · 사이트 계획까지 후보가 바뀌지 않는다 | 같은 시험의 뒷부분 (`build_site_plan` 까지) |
| 고르기가 **탐색을 다시 돌리지 않는다** | `test_b04` (탐색 함수를 터지게 둔다) |
| 없는 후보 · 만료 · 남의 요청 · 숫자가 아닌 입력 | `test_a01` · `test_a02` · `test_b01` · `test_b02` |
| 재실행 실패를 다른 후보로 바꾸지 않는다 | `test_b03` |
| 위치만 일치 / 표시 불일치 / 표시 미확인 / 필수 미지원 → **공유 차단** | `tests/test_site_verify.py::test_bg01` · `test_bg02` · `test_bg04` · `tests/test_site_plan.py::test_bh01`~`test_bh03` |
| 완전히 확인된 경우에만 공유 | `test_bh01` 의 뒤집음 — 옛 드라이버 결과(``all_ok`` 만)는 **공유되지 않는다** |

공유 차단 문장 (모의, 실제 출력):

```
🔴 **외부 공유를 만들지 못했습니다.** — 표시 형식이 기록과 달라 공유하지
   않았습니다: main-5: face_down→face_up
🧪 재현 판정: 위치 ✔ · 표시 형식 ✘ → 미완료 (엔진 기록과 사이트 상태의
   일치 여부이고, 규칙 적법성 판정이 아닙니다)
첨부된 `combo-replay.html` 로는 그대로 재생할 수 있습니다.
```

### 24.3 최소 회귀 — 전체 스위트를 **다시 돌리지 않았다**

이번 변경이 닿는 17개 파일만 돌렸다 (요청의 지시).

```
tests/test_bounded_search_first_pass.py  tests/test_bounded_search_multi_results.py
tests/test_candidate_pick.py             tests/test_combo_brief_and_detail.py
tests/test_combo_output_consistency.py   tests/test_deck_image_registry.py
tests/test_discord_bot.py                tests/test_galatea_effect_extension.py
tests/test_girsu_token_line.py           tests/test_open_search.py
tests/test_opening_duel_integration.py   tests/test_orcust_girsu_line.py
tests/test_replay_export.py              tests/test_replay_viewer.py
tests/test_site_plan.py                  tests/test_site_verify.py
tests/test_withheld_reason_propagation.py
→ 609건 중 608 통과 · 실패 1건
```

🔴 **그 1건은 기준 HEAD 에서도 실패하던 것이다** —
`test_opening_duel_integration.py::test_f02_the_discord_output_separates_executed_from_planned`
는 6-BG 가 적어 둔 **68건의 기존 실패** 목록에 그대로 있다 (§16.4). 이번에
고치지 않았다 (요청: 기존 전체 실패를 일괄 수정하지 않는다).

처음 돌렸을 때는 8건이 실패했고, **7건이 이번 변경이 깨뜨린 것**이어서 전부
고쳤다.

| 깨진 것 | 원인 | 고친 방법 |
| --- | --- | --- |
| `test_open_search.py` 의 `g01`~`g06` · `i08` (6건) | ``/combo`` 가 ``_run_bounded_search`` 에 ``owner`` · ``store`` 를 넘기는데 그 파일의 **대역**이 받지 않았다 | 대역에 두 칸을 더했다 — 🔴 단언은 그대로다 |
| `test_bounded_search_first_pass.py::test_e06` | ``combo_response`` 의 **키워드 전용 인자 목록**을 고정한 시험 | ``owner`` · ``store`` 를 더하고 **기본값까지** 고정했다 (기존 위치 인자 호출이 그대로라는 사실을 그 기본값이 지킨다) |
| `tests/test_discord_bot.py` 의 명령 집합 · 대역 (3곳) | 새 명령 `combo-pick` 과 ``interaction.user`` | 집합에 이름을 더하고 **매개변수까지** 고정했다 (`request` · `result` · `share`). 대역에 `user` 를 더했다 — 진짜 ``discord.Interaction`` 은 언제나 그것을 들고 있다 |
| `tests/test_site_*.py` 의 성공 대역 (4곳) | 6-BG 까지 대역이 ``all_ok`` 만 적었고 그것만으로 공유 성공이었다 | 대역이 **판정을 말하게** 했다 — 🔴 그리고 "옛 모양의 결과는 공유되지 않는다" 를 **새 시험으로** 고정했다 (`test_bh01`) |

🔴 **단언을 지우거나 약하게 한 곳은 없다.** 바꾼 것은 대역이 말하는 **값**과
고정한 **목록의 길이**이고, 그때마다 새 사실을 함께 고정했다.

🔴 **사용자 대신 Discord 에 보내지 않았다.** 봇을 띄우지도 않았다.

---

## 25. 정정 표 (6-BG → 6-BH)

| 자리 | 당시 문장 | 지금의 사실 |
| --- | --- | --- |
| `deck/site_plan.py` `_NO_SITE_OPERATION` | "토큰 생성 — 덱 이미지에 없는 카드라 자리를 묶을 수 없습니다" / "토큰 소멸 — 위와 같습니다" | 🔴 **틀렸다.** 사이트 조작 바의 `More` 메뉴에 **`Generate Token`** 이 있고, 그 카드의 메뉴에 **`Delete Token`** 이 생긴다 (실측). 자신 자리의 토큰은 이번에 **연결했다** |
| `deck/site_plan.py` `_SET_POSITION_NOTE` | "이 계획은 **자리 이동만** 만듭니다 … 뒷면으로 만드는 조작은 사람이 해야 합니다 … 하위 항목 이름은 설명서에 없어 **자동으로 누르지 않습니다**" | 🔴 **조작기가 뒷면으로 만들고 사이트에서 확인한다.** 하위 항목 이름을 **UI 를 열어 읽었다** (`Set Face-down` · `Set Face-up`) — 설명서에 없다는 것이 "확인할 수 없다" 는 뜻은 아니었다 |
| 이 보고서 §15.3 | "**구현하지 않았다** — 정확한 항목 이름이 필요하고, 확인하지 못한 이름을 지어내지 않는다" / "남은 일: 실제 UI 를 한 번 열어 그 메뉴의 하위 항목 이름을 읽는 것 … 제3자 서버에 덱 이미지를 올리는 일을 포함한다" | 🔴 **업로드 없이 읽을 수 있었다** — 이미 있는 공유 리플레이를 `Manual` 로 바꾸면 그 판에서 그대로 조작된다. 그 길로 읽고 **구현했다** (§21) |
| 이 보고서 §15.2 표 | "`fullyReproduced` **거짓** — 뒷면이어야 하는 자리가 하나라도 있으면" | 🔴 **지금은 읽어서 판정한다.** 뒷면 기대가 있어도 **관측이 뒷면이면 재현**이다 (§22.3 의 첫 줄) |
| 이 보고서 §15.2 표 | "`result.notes` 에 … 를 적는다" (조작기 결과에만) | 그대로 참이고, **그 위 세 자리도 읽는다** — `SiteRunResult` · `SiteShareOutcome` · Discord 응답 (§22.1) |
| 이 보고서 §11.3 ④ | "요약과 상세는 **둘 다**, JSON · HTML · 사이트 계획은 **결과 17 하나**를 가리킨다" | 그대로 참이고 (`/combo` 의 기본값), 🔴 **사용자가 고르면 그 후보로 바뀐다** (`/combo-pick`, §20) |
| `tests/test_site_plan.py::test_bg02` | ``expect_positions["compared"] is False`` 를 고정했다 | 🔴 그 칸은 **없어졌다.** 계획은 "대조하지 않았다" 고 선언하는 것이 아니라 **대조할 자리**(`declared`)를 넘기고, 판정은 관측으로 한다 |
| `tests/test_site_verify.py::test_bg02` | "뒷면이 없는 계획은 한 글자도 달라지지 않는다 … `fullyReproduced` 참" | 🔴 **그 이름의 시험을 바꿨다** — 지금 재는 것은 "앞면 자리를 읽지 못한 것은 재현을 깨뜨리지 않지만 `compared` 는 거짓" 이다 |

🔴 **6-BG 가 "확인했다" 고 적은 것 중 약해진 것은 없다.** 바뀐 것은 ① 표시
형식을 **읽게** 된 것, ② 토큰을 **할 수 있게** 된 것, ③ 공유 판정이 그 둘을
**읽게** 된 것이다.

---

## 26. 사용자가 복사할 값 (6-BH 기준 · 옵션별)

### 26.1 1단계 — `/combo`

**`hand`**

```
69811710, 14558127, 23434538, 10045474, 24224830
```

**`recipe`** — 🔴 파일 경로가 아니라 아래 내용을 그대로 (메인 40 · 엑스트라
15 · 사이드 0).

```
#main
69811710
69811710
69811710
57835716
57835716
57835716
4055337
4055337
21441617
93920420
27918365
72270339
14558127
14558127
14558127
23434538
23434538
42141493
42141493
42141493
94145021
94145021
94145021
90351981
99674361
66328392
66328392
66328392
94845588
80845034
24224830
24224830
65681983
81439173
10045474
10045474
10045474
49299410
703897
53329234
#extra
73391962
46396218
93854893
93854893
48835607
30741503
30741503
39752820
13117073
65741786
29301450
76145142
74820316
86066372
4280258
```

**`search`**

```
auto
```

**`results` · `followups` · `line` · `board` · `deck`** — 🔴 **비워 둡니다**
(`results` 를 비우면 2, `followups` 를 비우면 6. `line` 은 `search:auto` 와
함께 주면 거절합니다).

### 26.2 2단계 — `/combo-pick` (추가 동작)

`/combo` 응답의 마지막에 이런 줄이 나옵니다 (ID 는 **매번 다릅니다**):

```
🎞 **다른 추천을 재생하려면** `/combo-pick request:5742c17c result:<번호>`
   — 고를 수 있는 번호: `24`.
```

그 값을 **옵션마다** 넣습니다.

| 옵션 | 넣을 값 |
| --- | --- |
| `request` | 그 줄의 ID 그대로 (예: `5742c17c`) |
| `result` | 그 줄이 적어 준 번호 (갈라테아 ② 를 쓰는 전개가 그쪽입니다) |
| `share` | 기본은 끔. **켜면 외부 사이트에 공개 리플레이를 올립니다** (1~2분, 되돌릴 수 없습니다) |

🔴 **요청 ID 는 30분 동안만** 보관합니다. 지나면 "만료됐습니다" 라고 적고,
그때는 `/combo` 를 다시 돌리면 됩니다 (번호가 달라질 수 있습니다).

### 26.3 그때 보일 것 (실측)

* `result:24` → `7걸음` · `자신 마법·함정 존: 오르페골 클리막스 [703897]
  뒷면/FACEDOWN` · 첨부 `combo-replay.json` · `combo-replay.html`
* `result:17` → `5걸음` · 마법·함정 존 없음 · 같은 두 첨부 (**다른 기록**)
* `share:true` → 🔴 **지금은 공유되지 않습니다.** 이 전개에는 **상대 자리의
  토큰**이 있고 그것을 이 계획이 놓지 못하므로 재현이 미완료이고, 응답이
  그 사유를 적습니다 (§23.3). 자체 뷰어(`combo-replay.html`)로는 그대로
  재생됩니다.

---

# Phase 6-BI 후속 — **오르페골 갈라테아i** 의 필드 효과를 자율 전개에

기준 HEAD: `e53bb48f` (6-BH 의 커밋). 앞 절들의 본문은 지우지 않았고, 지금
틀린 문장은 §34 의 표에 적는다.

🔴 **사용자가 짚은 것.** 디스코드에서 받은 전개에서 갈라테아i 가 필드에
나왔는데 **효과를 쓸지 고려한 흔적이 없었다** — 그대로 링크 소재가 되었다.

🔴 **갈라테아i(48835607) 와 갈라테아(30741503) 는 별개 카드다.** 6-BF 가
등재한 것은 **갈라테아** ② 이고, 이번에 등재한 것은 **갈라테아i** ② 다.

---

## 27. 한눈에

| # | 무엇 | 근거 · 자리 |
| --- | --- | --- |
| I1 | **갈라테아i ② 를 등재했다** — 패 1장을 묘지로 보내고 덱·묘지에서 성유물 몬스터 또는 오르페골 바벨 1장을 패에 넣는다 | `engine/effect/library.py` `_GALATEA_I_TO_HAND_ENTRY` (`c48835607.lua` 의 `e3`) |
| I2 | 🔴 **없던 것은 효과만이 아니었다** — 듀얼 고리가 **고르는 비용을 만들지 않았다.** 비용으로 카드를 고르는 효과는 등재해도 후보가 되지 못했다 | `engine/cost_bridge.py` (새 파일) · `engine/duel.py` `legal_actions` |
| I3 | **비용을 행위가 들고 간다** — 어느 카드를 냈는지가 행위에 적히므로, 비용이 다른 전개는 **다른 행위**이고 탐색이 그것을 갈라서 본다 | `PlayerAction.cost_cards` · `canonical_state()` 가 한 칸 늘었다 |
| I4 | **묘지送り 비용을 실제로 치른다** — 표에 줄이 없어 `COST_NOT_IMPLEMENTED` 로 거절되던 자리 | `engine/payment.py` `COST_OPERATION[SEND_TO_GRAVE]` |
| I5 | 🔴 **후보 목록과 실제 지불이 갈리지 않게 했다** — 판정기가 지불 계층의 표를 **그대로 읽는다** | `engine/cost/validation.py` `CostValidator._unpayable_semantics` |
| I6 | 🔴 **비용만 소모되는 길을 닫았다** — 비용을 치른 **뒤의 판**으로 대상 후보를 보고, 판정할 수 없으면 발동을 보류한다 | `engine/activation.py` `EffectActivator._after_cost` |
| I7 | **패를 장수가 아니라 구성으로 비교한다** — 「비용 1장 내고 1장 가져온 전개」 와 「패를 그대로 둔 전개」 가 둘 다 4장이어도 합쳐지지 않는다 | `agent/open_evaluation_v2.py` `variant_key` |
| I8 | **탐색 예산의 세는 단위를 고쳤다** — 한 자리의 선택 조합이 한 기준점의 보관 상한을 가져가지 않는다 | `agent/bounded_search.py` `choice_family` |
| I9 | **재생 검증 자리를 보관 상한에 맞춰 늘렸다** — 후보가 늘었는데 검증이 2건이면 찾아낸 전개가 추천에 닿지 못한다 | `app/main.py` `AUTONOMOUS_VERIFY_PER_CANDIDATES` |
| I10 | 🔴 **요약이 잘려 요청 ID 가 사라지지 않게 했다** — 후보 블록을 3개로 제한하고 나머지는 **번호를 적어** 상세 기록으로 보낸다 | `deck/report.py` `BRIEF_CANDIDATE_LIMIT` |

---

## 28. §1 — 효과가 빠져 있던 원인: **네 가지였고, 실측으로 갈랐다**

사용자의 요구는 "효과가 엔진에 없는지 · 비용이나 패에 넣을 카드를 고를 수
없는지 · 탐색이나 추천에서 빠지는지 **실제로 구분해라**" 였다. 순서대로
실측했고, 네 자리가 **차례로** 막고 있었다.

| # | 원인 | 어떻게 확인했는가 | 고친 자리 |
| --- | --- | --- | --- |
| 1 | **효과가 EFFECT_LIBRARY 에 없었다** | 갈라테아i 가 필드에 있는 판에서 `legal_actions` 를 떠 보았다 — 후보에도 없고 **보류 줄에도 48835607 이 없었다.** 🔴 없는 효과는 거절될 자리조차 없다 | `_GALATEA_I_TO_HAND_ENTRY` 등재 |
| 2 | **듀얼 고리가 고르는 비용을 만들지 않았다** | 등재만 하고 다시 떠 보니 보류 한 줄: 「비용으로 고를 카드를 이 고리가 만들지 않습니다」. 6-AO 부터 `EffectActivator.activate` 는 `cost_selections` 를 **받을 수 있었지만** `Duel._apply_activation` 이 그것을 **만들지 않았다** | `engine/cost_bridge.py` · `PlayerAction.cost_cards` |
| 3 | **패에 넣을 후보의 규칙이 등재되지 않았다** | 다시 떠 보니 보류: 「후보 3장이 있지만 그중 지금 `may_be_returned_to_hand` 가 참인 것을 확인하지 못했습니다」 (성관 · 바벨 · 성장 셋 다). 🔴 `UNKNOWN` 은 허가가 아니다 (ADR-006) | 세 카드의 `MAY_BE_RETURNED_TO_HAND` 등재 (공식 한국어 텍스트 전문을 읽고) |
| 4 | **묘지送り 비용을 지불 계층이 치르지 못했다** | 후보 4건(패 4장)이 나왔는데 발동이 `COST_NOT_IMPLEMENTED` 로 거절됐다 — `CostSemantics.SEND_TO_GRAVE` 가 `COST_OPERATION` 에 **줄이 없었다** | `COST_OPERATION` 에 한 줄 (옮기는 계층은 이미 있었다) |

🔴 **네 번째를 고치면서 다섯 번째가 드러났다.** 후보 목록은 `VALID` 인데
지불은 거절했다 — `CostValidator` 가 **후보 수만** 세고 "그 종류의 비용을
치를 수 있는가" 는 묻지 않았기 때문이다. 그 둘이 갈리지 않도록 판정기가
지불 계층의 표(`SUPPORTED_COSTS`)를 **그대로 읽게** 했다. 흉내가 아니다.

### 28.1 공식 스크립트에서 읽은 것 — `c48835607.lua` 의 `e3`

```lua
e3:SetType(EFFECT_TYPE_IGNITION)   e3:SetRange(LOCATION_MZONE)
e3:SetCountLimit(1,id)             e3:SetCondition(aux.NOT(s.babelcon))
e3:SetCost(s.thcost)  e3:SetTarget(s.thtg)  e3:SetOperation(s.thop)
```

| 공식 | 이 저장소 |
| --- | --- |
| `s.thcost` 의 `Card.IsAbleToGraveAsCost` + `Duel.SendtoGrave(g,REASON_COST)` | `CardCost.send_to_grave({HAND})` — 🔴 **`DISCARD` 가 아니다** |
| `s.thfilter` — 「성유물」 몬스터 **또는** 오르페골 바벨, 그리고 `IsAbleToHand` | `Or(And(성유물 시리즈, IsMonster), CardIdIs(바벨))` + `existence_requires_gate=True` |
| `s.thtg` 의 `chk==0` 이 `Duel.IsExistingMatchingCard` 로 **존재를 확인한다** | `checked_at_activation` 을 그대로 둔다 (갈라테아 ② 의 세트 대상과 **다른 점**) |
| `s.thop` 의 `Duel.SelectMatchingCard` → `SendtoHand` | `chosen_at_resolution=True` + `return_to_hand(gated=True)` |
| `SetCountLimit(1,id)` | `UseLimit(LimitScope.PER_CARD_NAME)` |
| `s.babelcon` = `Duel.IsPlayerAffectedByEffect(tp,CARD_ORCUSTRATED_BABEL)` | `Not(FaceUpCardPresent(..., FZONE, 바벨))` — **범위를 아래에 적는다** |

### 28.2 **비용**과 **버리는 효과**를 가른다

공식 스크립트가 그 둘을 다른 함수로 적는다 (`IsDiscardable`/`DiscardHand` 대
`IsAbleToGraveAsCost`/`SendtoGrave(…,REASON_COST)`). 이 저장소도 두 의미를
다른 값으로 들고 있고 (`CostSemantics.DISCARD` 대 `SEND_TO_GRAVE`), 각자
다른 `OperationKind` 로 기록된다. 그래서 전개 기록에서 **「비용으로 묘지로
보낸 카드」** 와 **「효과로 버린 카드」** 가 갈린다 (ADR-002).

실측 — 같은 발동이 남긴 기록 두 줄:

```
CostPaymentEvent | 지불 P0 #76 묘지로 보냄 | ZoneMoved     ← 비용 (하루 우라라)
EffectEvent      | ZoneMoved | ZoneShuffled               ← 효과 (덱 → 패, 바벨)
```

### 28.3 바벨 적용 중의 발동 — **이 엔진이 판정할 수 있는 범위**

공식 조건은 「`CARD_ORCUSTRATED_BABEL` 의 효과를 **적용받고 있지 않을 때**」
이고, 그것은 지속 효과 계층이 있어야 그대로 읽을 수 있다. 이 저장소에는 그
계층이 없다 (`STRUCTURAL-76`). 그래서 지금 판정하는 것은 **「오르페골
바벨이 자기 필드 존에 앞면으로 있지 않다」** 하나다.

* ✅ 바벨이 필드 존에 **앞면으로 있으면** 발동하지 않는다.
* ❌ 바벨을 **패에 넣었을 뿐**인 상태는 「적용 중」이 아니므로 발동한다 —
  이것은 공식과 같다.
* 🔴 **아직 못 보는 것**: 바벨의 효과가 무효가 된 경우, 다른 카드가 같은
  효과를 적용하는 경우. 갈라테아 ② 의 `s.tdcon1` 과 **같은 범위 · 같은
  표현**이고, 같은 한계다.

🔴 **바벨은 EFFECT_LIBRARY 에 등재되어 있지 않다.** 그래서 「패에 넣은 것」
과 「필드에서 발동한 것」 중 이 엔진이 하는 일은 **패에 넣는 것까지**다 —
전개 기록의 바벨은 **패에 있고**, 필드 존에 놓이지 않는다. 클리막스 · 성관도
같다 (세트는 갈라테아 ② 가 하는 일이고, 그 카드의 효과 발동이 아니다).

---

## 29. §1 후속 — **비용만 소모되는 오류**를 닫은 자리

🔴 **실측으로 실제로 일어났다.** 비용으로 「하루 우라라」 를 묘지로 보내자
그 카드가 묘지에 앞면으로 놓이고, 등재된 판정이 없어
`BoardRuling._interference` 가 `UNKNOWN` 이 되었다. 발동은 **비용 전 판**을
보고 수락됐고 해결은 **비용 후 판**을 보고 `UNCHECKED_RULES` 로 멈췄다 —
**패 1장이 묘지로 가고 가져온 것은 없었다.**

두 가지를 함께 고쳤다.

1. **들어가기 전에 본다** — `EffectActivator._after_cost` 가 판을 복제해
   **같은 `CostPayer` 로** 비용을 치르고, 그 판으로 대상 후보를 판정한다.
   ADR-008 이 rollback 을 미뤄 두었으니, 치른 뒤에 멈출 수 있는 길을 두면
   그것이 곧 "패만 소모되는" 길이다. 🔴 복제본에는 **기록을 남기지 않는
   지불기**로 치른다 — 살아 있는 기록에 적으면 일어나지 않은 지불이 기록에
   남는다 (실측으로 재생 검증이 그 자리에서 깨졌다).
2. **판정을 등재한다** — 이번 패의 네 장(하루 우라라 · 증식의 G · 무한포영 ·
   무덤의 지명자)에 대해 공식 텍스트를 읽고 `MAY_BE_SENT_TO_GRAVE` 와
   `restricts_others=False` 를 근거와 함께 적었다. 무한포영 · 무덤의 지명자의
   근거에는 **등재 범위**가 섞여 있으므로, 그 ① 이 등재되는 날 그 줄이 조용히
   거짓이 되지 않도록 import 시점에 기계가 본다
   (`_HAND_TRAP_RESTRICTION_GUARD`).

### 29.1 가져올 카드가 하나도 없는 판 — **실측**

덱 · 묘지에서 바벨 · 성장 · 성관을 전부 치운 뒤 같은 자리에서 떠 보았다.

```
갈라테아i ② 후보 0건
보류: @primary 를 해결 중에 고르려면 후보가 있어야 합니다:
      후보가 0장뿐입니다 (필요 1장).  [no_candidates]
패 변화 없음: True        묘지 변화 없음: True
```

🔴 **확정된 부족(`NO_CANDIDATES`)과 판정 불가(`UNKNOWN`)를 가른다** — 앞의
것은 판이 바뀌면 풀리고, 뒤의 것은 등재가 생겨야 풀린다.

🔴 **갈라테아i 의 묘지 소생 효과(e4 · e4a)는 등재하지 않았다** — 사용자가
별도 작업으로 남기라고 했고, `EFFECT_LIBRARY` 에 그 줄이 없다.

---

## 30. §2 — 같은 입력에서 찾아낸 **두 전개** (실측)

입력: `docs/orcust-azamina-note.ydk` (메인 40 · 엑스트라 15) · 패 5장
(기르수 · 하루 우라라 · 증식의 G · 무한포영 · 무덤의 지명자) ·
`/combo search:auto` · `line` 비움 · `results` 비움 · `followups` 비움.

기본 탐색 **73.1초** · 노드 331/400 · 최대 깊이 8 · 후보 **129건** ·
종료 사유 `max_followup_actions=6` · `max_candidates_per_baseline=48` ·
`max_candidates=64`. 🔴 **번호는 실행마다 달라진다** — 아래 번호는 이
측정의 것이고, 복사해 쓸 값이 아니다 (전개는 **수순으로** 알아본다).

분류: 갈라테아i ② 를 쓴 후보 **77건** · 갈라테아 ② 를 쓴 후보 **20건** ·
그중 **갈라테아i 효과를 쓰지 않은** 것 **9건** · 갈라테아i ② 가 바벨을
가져온 것 **20건**.

아래 둘은 **그 실행의 추천 후보 7건 중 두 건**이고, 사용자가 보려던 두
전개가 **나란히** 들어왔다.

| | **경로 ① 효과를 쓴 전개** (8걸음) | **경로 ② 패를 지킨 전개** (6걸음) |
| --- | --- | --- |
| 1 | 기르수 일반 소환 | 기르수 일반 소환 |
| 2 | 기르수 ① — 덱에서 **스켈레촌**을 묘지로 | 기르수 ① — 덱에서 **디베르**를 묘지로 |
| 3 | 기르수 ② — 양쪽 필드에 토큰 | 디베르 ① — 자신을 제외하고 **스켈레촌** 특수 소환 |
| 4 | 기르수를 소재로 **갈라테아i** 링크 소환 | 기르수 + 스켈레촌으로 **갈라테아** 링크 소환 |
| 5 | 스켈레촌 ① — 자신을 제외하고 기르수 소생 | 스켈레촌 ① — 자신을 제외하고 기르수 소생 |
| 6 | 🔴 **갈라테아i ② — 비용: 하루 우라라를 묘지로 · 가져온 것: 성유물－『성관』 (덱 → 패)** | 갈라테아 ② — 제외된 **디베르**를 덱으로 + **클리막스 뒷면 세트** |
| 7 | 갈라테아i + 기르수로 **갈라테아** 링크 소환 | — |
| 8 | 갈라테아 ② — 제외된 스켈레촌을 덱으로 + **클리막스 뒷면 세트** | — |
| **최종 패 (4장)** | 증식의 G · 무한포영 · 무덤의 지명자 · **성유물－『성관』** | 증식의 G · 무한포영 · 무덤의 지명자 · **하루 우라라** |
| 필드 | World Legacy Token · 갈라테아(EM) · 클리막스(뒷면) | 기르수 · 갈라테아(EM) · 클리막스(뒷면) |
| 묘지 | **하루 우라라(비용)** · 갈라테아i · 기르수 | 없음 |
| 제외 | 없음 (스켈레촌은 덱으로 돌아갔다) | 스켈레촌 |
| 재실행 기록 | 사건 **10건** | 사건 **8건** |

🔴 **두 경로의 패 장수는 똑같이 4장이다.** 다른 것은 **구성**이고, 6-BH
까지의 `variant_key` 는 장수만 보았으므로 그 둘이 같은 열쇠가 될 수 있었다.
지금은 패의 카드 ID 다중집합이 열쇠에 들어가므로 갈리지 않는다 (I7).

🔴 **가져온 카드는 「성관」 이었다 — 바벨이 아니다.** 바벨을 가져오는 변형도
**같은 실행에 20건** 있고 (그중 갈라테아 ② 까지 가는 것 2건), 그 기록도
같은 예산의 실행에서 만들어 확인했다 (§32). 🔴 **어느 쪽이 추천 자리에
들어오는지는 표시 순서의 결과이고, 카드별 가산점은 어디에도 없다** — 사용자가
바벨 쪽을 보고 싶으면 `/combo-pick` 으로 그 후보를 고르면 된다.

🔴 **성유물 몬스터도 실제 덱 상태에 따라 선택지에 들어왔다.** 이 덱에서
필터에 맞는 카드는 **세 장**이고 (성관 · 성장 · 바벨), 탐색은 셋 다 골라
보았다. 시작 패에 성장이 있다고 가정하지 않았다 — 셋 다 **덱에서** 왔다.

🔴 **비용도 네 장 전부 갈라 보았다.** 하루 우라라 · 증식의 G · 무한포영 ·
무덤의 지명자 각각을 낸 전개가 따로 있고, 남는 패가 그만큼 다르다.

🔴 **고정하지 않았다.** 탐색기에 특정 비용 카드도, 바벨도, 후보 번호도,
8걸음 수순도 들어 있지 않다. 카드별 추천 가산점도 없다 — `choice_family` 는
카드도 효과도 보지 않고, 기본값 변경은 **보관 상한의 수치** 하나다.

---

## 31. §2 후속 — 두 경로가 **함께** 들어오게 한 자리

🔴 **등재만 했을 때 생긴 일.** 갈라테아i ② 가 한 자리에서 후보를 **12개**로
가른다 (비용 4장 × 패에 넣을 카드 3장). 기준점별 보관 상한이 16이었으므로
**그 한 행동이 한 기준점의 상한을 거의 다 썼고**, 탐색은 그 기준점을 더
펼치지 않았다 — 깊이 5에서 멈추고 6-BH 까지 찾아내던 **7걸음 전개(갈라테아
②)가 기본 탐색에서 사라졌다.**

두 가지를 고쳤다.

1. **세는 단위** — `choice_family` 로 센다. 같은 자리에서 **같은 행동**을
   했고 **고른 것만** 다른 경로들은 상한에 **한 개로** 세어진다. 🔴 버리는
   것이 없다 — 12개는 전부 보관되고 결과에 나온다.
2. **수치** — 전체 보관 상한 20 → **64**, 기준점당 16 → **48**
   (`CANDIDATE_CAP` 은 40 → 96 으로 올려 사용자가 더 넓힐 자리를 남겼다).

| 전체 | 기준점당 | 소요 | 깊이 | 갈라테아i② | 갈라테아② | 효과를 **안 쓴** 갈라테아② |
| --- | --- | --- | --- | --- | --- | --- |
| 20 | 16 | 47.4초 | 6 | 24건 | 0건 | 0건 |
| 40 | 32 | 54.8초 | 8 | 36건 | 3건 | **0건** |
| 64 | 64 | 39.0초 | 8 | 96건 | 13건 | **0건** |
| **64** | **48** | 71.2초 | 8 | 77건 | 20건 | **9건** |

🔴 **64/64 가 아니라 64/48 을 고른 이유** — 기준점당 상한이 전체와 같아지면
6-BE 가 고친 것이 풀린다 (기준점 하나가 보관을 다 쓴다). 실측으로 그때
「효과를 쓰지 않은 갈라테아② 전개」 가 **0건**이다.

🔴 **대가를 적는다** — 같은 입력의 탐색이 24초에서 **71초**가 되었다 (탐색
상한 240초 안이다). 사용자가 기다리는 시간은 여기에 재생 검증과 기록 만들기가
더해진 값이다.

---

## 32. §3 — 재생 기록 (실측)

고른 후보를 **새 초기 상태에서 처음부터 다시 실행해** 기록을 만들었다
(`autonomous_rerun_record`). 🔴 **추천 7건 전부 기록이 만들어졌다**
(사건 4 · 6 · 8 · 8 · 8 · 8 · **10**건).

경로 ① (8걸음, 사건 10건) 의 기록에 사용자가 요구한 네 걸음이 순서대로 있다.

| 기록의 사건 | 무엇 |
| --- | --- |
| `CostPaymentEvent` + `zone_moved` HAND → GRAVE | 🔴 **손패 비용** — 하루 우라라 |
| `zone_moved` DECK → HAND + `zone_shuffled` | 🔴 **가져온 카드를 패에 추가** |
| `zone_moved` EMZONE/MZONE → GRAVE + `monster_summoned` EXTRA → EMZONE | 🔴 **갈라테아 링크 소환** |
| `zone_moved` REMOVED → DECK + **`card_set`** | 🔴 **클리막스 뒷면 세트** (스켈레촌 덱 복귀와 같은 해결) |

🔴 **비용과 효과가 기록에서 갈린다** — 같은 발동이 남긴 두 줄:

```
CostPaymentEvent | 지불 P0 #76 묘지로 보냄 | ZoneMoved     ← 비용 (하루 우라라)
EffectEvent      | ZoneMoved | ZoneShuffled               ← 효과 (덱 → 패)
```

🔴 **바벨을 가져오는 변형도 같은 예산의 실행에서 확인했다** — 비용(패 →
묘지) → **바벨(덱 → 패)** → 갈라테아 링크 소환 → 클리막스 뒷면 세트가
사건 10건으로 기록됐다.

🔴 **기존 7걸음 · 6걸음 · 5걸음 전개의 기록도 그대로 올바르다** —
`verify_replay` 가 기록만으로 계산한 각 존이 최종 판과 같다
(`tests/test_galatea_effect_extension.py` 의 E · G 묶음이 그것을 돌린다).

---

## 33. §3 후속 — **추천까지 이어지는지** (중간에 사라지던 자리)

| 걸음 | 효과 경로가 거기 있는가 | 근거 |
| --- | --- | --- |
| 기본 탐색에서 발견 | ✅ **77건** | §30 |
| 후보 목록 · 보관 | ✅ 129건에 포함 | `CandidateStore` |
| 재생 검증 | ✅ 검증 7건 중 **2건**이 갈라테아i ② (그중 하나는 갈라테아 ② 까지) | 아래 |
| **최종 추천** | ✅ **들어온다** (효과를 쓴 전개와 패를 지킨 전개가 **나란히**) | §30 의 표 |
| `/combo-pick` 으로 고르기 | ✅ 추천이 아닌 후보도 고를 수 있고 기록이 만들어진다 | 6-BH 의 설계 |

🔴 **한 번 사라졌고, 그 자리를 고쳤다.** 보관 상한을 20 → 64 로 올리자 후보가
129건이 되었는데, **재생 검증 자리 수는 `results:` (기본 2) 그대로**였다 —
129건 중 2건만 검증되고, 갈라테아 ② 경로 20건은 **전부 미검증**이었다
(추천은 검증된 것 중에서만 고른다).

그래서 **검증 자리를 보관 상한에 맞춰 늘렸다** —
`AUTONOMOUS_VERIFY_PER_CANDIDATES`(보관 10마다 한 자리) ·
`AUTONOMOUS_VERIFY_SLOTS_CAP`(최대 8). 보관 64 → 자리 **7**.
🔴 **표시 수와 검증 수는 다른 질문이다** — 사용자가 `results:` 로 더 많이
요구하면 그쪽이 이긴다.

| 검증 자리 | 전체 소요 | 검증된 후보 | 그중 갈라테아i② | 그중 갈라테아② |
| --- | --- | --- | --- | --- |
| 2 (6-BH 의 기본) | 71.7초 | 2건 | 1건 | **0건** |
| 4 | 71.5초 | 4건 | 1건 | 1건 |
| 6 | 73.8초 | 5건 | 2건 | 2건 |
| **7 (지금의 기본)** | 73.1초 | 7건 | 2건 | 2건 |

🔴 **싸다** — 자리 2 → 7 의 대가가 약 1.4초다 (탐색이 73초이고 재실행은 한
건당 1초 미만이다).

---

## 34. 정정 표 (6-BH → 6-BI) · 남은 것

| 6-BH 까지 적혀 있던 것 | 지금 |
| --- | --- |
| 「비용이 있는 효과도 후보가 된다」 (6-AO) | **고를 것이 있는 비용은 아니었다** — 듀얼 고리가 비용 선택을 만들지 않았다. 6-BI 가 `engine/cost_bridge.py` 로 그것을 만들었다 |
| `canonical_state()` 가 7칸 | **8칸** — 마지막이 `cost_cards` 다. 행위 자체는 늘지 않았고, 효과 발동이 아닌 행동은 늘 비어 있다 |
| `UNSUPPORTED_REASON` 에 「비용으로서의 묘지送り」 | **`COST_OPERATION` 으로 옮겼다** — 두 표에 함께 있으면 어느 쪽이 참인지 말할 수 없다 |
| `CANDIDATE_CAP = 40` · 기본 20/16 | **96** · 기본 **64/48**, 그리고 세는 단위가 `choice_family` 다 |
| 재생 검증 자리 = `results:` | **보관 상한에 맞춰 늘린다** (§33) |
| 요약이 검증된 결과 **전부**의 블록을 적었다 | **앞의 3개만** 적고 나머지는 **번호를 적어** 상세 기록으로 보낸다 (`BRIEF_CANDIDATE_LIMIT`) — 추천이 7개가 되자 요약이 디스코드 상한을 넘겨 **요청 ID 줄이 잘렸다** (실측으로 두 시험이 잡았다) |
| `OPERATION_RULINGS` 28장 | **33장** — 성관 + 이번 패의 네 장 |

남은 것 (이번 범위 밖 · 사용자가 그렇게 지시했다):

* **갈라테아i 의 묘지 소생 효과** (`e4` · `e4a`) — 별도 작업.
* **상대 토큰의 외부 사이트 배치** · **공유 판정** · **덱 입력 간소화** —
  6-BH 가 남긴 후속 과제 그대로다.
* **바벨을 필드에서 발동하는 것** — 바벨이 `EFFECT_LIBRARY` 에 없다. 지금
  하는 일은 **패에 넣는 것까지**다 (§28.3).
* **유발즉시(`e3a`) · 지속 효과 계층** — 룰북에서 읽지 못한 것을 추측으로
  넣지 않았다 (ADR-006 · STRUCTURAL-76).
* **요약에 담는 후보 블록이 3개로 제한된다** — 나머지는 번호만 적고 상세
  기록 첨부로 보낸다. 더 많이 보이게 하려면 요약을 **여러 메시지로 나누는**
  방법이 필요하고, 그것은 표시 계층의 다음 일이다.
* **탐색 소요가 24초 → 73초** 로 늘었다. 보관 상한을 올린 대가이고, 더 줄이려면
  한 자리의 선택 조합을 **펼치는 순서**를 고쳐야 한다 (지금은 세는 단위만
  고쳤다).

---

## 34.1 검증 — **돌린 것과 돌리지 않은 것**

| 무엇 | 결과 |
| --- | --- |
| `tests/test_galatea_effect_extension.py` (H 묶음 6건을 새로 더했다) · `test_candidate_pick.py` · `tests/engine/` 네 모듈 | **173 passed** (5분 26초) |
| `test_combo_output_consistency.py` · `test_combo_brief_and_detail.py` · `test_discord_bot.py` | **117 passed** |
| `test_bounded_search_*` 다섯 모듈 | **134 passed** (행위 열쇠의 모양이 한 칸 늘어 세 모듈의 적어 둔 열쇠를 고쳤다) |
| `test_open_search.py` · `test_candidate_pick.py` 의 두 실패 | 🔴 **6-BI 가 만든 것이었고 고쳤다** — 요약이 잘려 요청 ID 가 사라진 자리 (I10) |
| 전체 스위트 | 아래 §34.2 |

🔴 **새로 더한 시험 6건** (`tests/test_galatea_effect_extension.py` H 묶음):

| 시험 | 무엇을 지키는가 |
| --- | --- |
| `test_h01` | 비용으로 낼 수 있는 패 카드마다 후보가 하나이고, 보류에 48835607 이 남지 않는다 |
| `test_h02` | 비용은 묘지로 · 고른 카드는 패로 · 패 장수는 그대로 · 비용이 `CostPaymentEvent` 로 적힌다 · 1턴 1번 |
| `test_h03` | 🔴 **가져올 카드가 없는 판에서 발동이 보류되고 패 · 묘지가 한 글자도 바뀌지 않는다** (`NO_CANDIDATES`) |
| `test_h04` | 패 장수가 같아도 구성이 다르면 다른 변형이다 |
| `test_h05` | `choice_family` 가 선택만 다른 경로를 묶고, 앞 걸음 · 효과가 다르면 가른다 |
| `test_h06` | 기본값 그대로 돌린 자율 탐색이 효과를 쓴 전개와 패를 지킨 전개를 **둘 다 추천**에 올리고, 고른 것이 다시 실행된다 |

🔴 **돌리지 않은 것**: 실제 Discord 전송 · 실제 사이트 공유 (`share:true`) ·
새 공개 링크 생성. 사용자가 직접 확인한다.

---

## 35. 사용자가 Discord 에서 볼 것

`/combo` 에 덱 레시피와 패 5장(기르수 · 하루 우라라 · 증식의 G · 무한포영 ·
무덤의 지명자) 을 넣고 `search:auto` 로 돌린다 — `results` · `followups` ·
`line` 은 비운다. 🔴 **요청 ID 와 결과 번호는 실행마다 다르다.** 그래서
전개는 **수순으로** 알아보아야 한다.

* **「갈라테아i 효과를 쓴 전개」** — 수순에 `오르페골 갈라테아i:e[2]` 가 있고,
  요약의 비용 칸에 패 카드 이름(예: 하루 우라라)이 적혀 있다. 최종 패 4장
  가운데 하나가 **덱에서 가져온 카드**(성관 · 성장 · 바벨 중 하나)다.
* **「패를 지킨 전개」** — 수순에 `갈라테아i:e[2]` 가 **없고**, 최종 패가
  시작 패의 네 장(하루 우라라 · 증식의 G · 무한포영 · 무덤의 지명자) 그대로다.

둘 다 **공동 추천**으로 나오므로, 보고 싶은 쪽의 `[결과 N]` 번호를 그 응답의
요청 ID 와 함께 `/combo-pick request:<그 응답의 ID> result:<그 번호>` 에
넣으면 그 후보만 다시 실행한 기록이 첨부로 온다. 🔴 **`share:true` 는 이
전개에서 여전히 막힌다** — 상대 자리의 토큰을 외부 사이트 계획이 놓지 못하고,
그 사유를 응답이 적는다 (§23.3). 자체 뷰어 첨부로는 그대로 재생된다.
