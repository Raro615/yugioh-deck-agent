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
