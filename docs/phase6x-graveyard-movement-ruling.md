# Phase 6-X — 묘지 이동 규칙 판정 및 실제 효과 해결

브랜치: `claude/pensive-goodall-te1egy` · 시작 지점 `b36b36d` (6-W 완료)

## 요약 — 달성 수준

| 수준 | 내용 | 결과 |
| --- | --- | --- |
| 수준 1 | 묘지 이동 규칙과 `UNCHECKED_RULES` 의 실제 차단 원인 확인 | ✅ **달성** |
| 수준 2 | 기본 허용 · 금지 · 대체 · UNKNOWN 을 구분하여 실제 GameState 기반 판정 | ✅ **달성** |
| 수준 3 | 실제 Duel 에서 기르수 효과 해결 · Deck→Graveyard 를 GameState · EventJournal 로 검증 | ✅ **달성** |

```
발동: activated            해결: RESOLVED
덱:   35 → 34              묘지: 0 → 1
인스턴스: #34 → GRAVE (card_id 93920420)
기록: #0 69811710:e[0] P0: #34 P0/DECK → P0/GRAVE (send_to_grave),
      P0 의 DECK 34장을 섞었다
후속 legal_actions: ['end_phase', 'set_spell_trap']
```

그리고 **같은 공통 규칙으로 어리석은 매장(81439173)도 해결된다** — 발동
분류가 다른 카드다 (카드 발동 대 유발).

🔴 **근거 없는 허가는 넣지 않았다.** "제약 상수가 없으니 보낼 수 있다" 는
쓰지 않았고 (룰북에 그 문장이 없다 — 6-W §3.5), 쓴 것은 **반대 방향**이다:
그 카드 자신의 텍스트가 자기 묘지행을 적었으면 허가한다. 새로 허가된
**991장 전수를 공식 텍스트로 역검증해 거짓 허가 0건**을 확인했다.

---

## 1. 기존 규칙·실행 구조

판정은 `engine/effect/ruling.py` 한 곳에서 일어난다. 계층이 둘로 갈려 있다.

| 계층 | 무엇 | 듀얼을 보는가 |
| --- | --- | --- |
| `CardRuleFacts` | **카드**에 대해 확인한 사실 | 아니다 |
| `BoardRuling` | **이 판에서** 그 사실이 어떤 답이 되는가 | 본다 |

실행 경로:

```
CardOperation.send_to_grave(gated=True)
  → OperationKind.SEND_TO_GRAVE
  → RuleQuestion.MAY_BE_SENT_TO_GRAVE      (semantics.py:472)
  → BoardRuling.explain(question, instance)
      ① OperationRulingRegistry  — 손으로 적은 19장
      ② rulebook_facts()         — 관측된 카드 **종류**에서 룰북 한 줄로
      → 답이 FALSE 면 즉시 FALSE  (판을 더 볼 필요가 없다)
      → _interference()          — 판에 막을 수 있는 것이 있는가
      → _blind_spots()           — 정말로 못 본 것 (패)
```

### 1.1 판을 보는 기계는 **이미 있었다**

`_interference` 가 `INTERFERENCE_ZONES`(필드 · 묘지 · 제외) 를 훑는다. 셋 다
누구나 볼 수 있는 자리이므로 훑기가 관측 경계를 넘지 않는다. 그리고
`CardRuleFacts.restricts_others` 의 **기본값이 참**이다 — 확인하지 않은
카드는 막을 수 있다고 본다. 거짓으로 적으려면 근거를 함께 적어야 한다.

🔴 **그래서 §5 의 3·4(지속 금지 · 대체 효과)는 처음부터 보수적으로
처리되고 있었다.** 이 Phase 는 그 기계를 바꾸지 않았다.

### 1.2 `_blind_spots` 가 §4 의 네 번째 안전장치다

`UNSCANNED_ZONES` 가 세 자리를 가르는데 **무게가 다르다.** 덱과 뒷면 카드는
"효과가 적용되지 않는다" 고 룰북이 답하므로 못 본 것이 아니고, **패만**
진짜 한계다 (`STRUCTURAL-98`). 그 한계가 판정마다 `RulingVerdict.unchecked`
에 실린다 — 즉 **관측할 수 없는 제한을 "없다" 고 가정하지 않고, 못 봤다고
적는다.**

실측 (기르수 판의 `TRUE`):

```
unchecked = ('P0 의 패 4장: 패는 가려져 있다. 패에서 적용되는 지속 효과를
             가진 카드가 있으면 이 계층은 그것을 못 본다 (STRUCTURAL-98).',)
```

---

## 2. 실제 차단 원인

`MAY_BE_SENT_TO_GRAVE` 에 답하는 지식이 **룰북 한 줄**뿐이었다.

| 출처 | 항목 수 | 묘지 질문에 답하는 것 |
| --- | --- | --- |
| ① `OPERATION_RULINGS` | 19 | **1건** — 엘리멘틀 히어로 페더맨 · `TRUE` · `RuleBasis.RULEBOOK` |
| ② `rulebook_facts()` → `normal_monster_facts()` | 유도 | **순수 통상 몬스터만** · `TRUE` · `RULEBOOK` |

①의 유일한 1건도 통상 몬스터이고 근거도 같은 줄이다. 그래서 전체
14,127장 중 답이 나는 카드가 **684장**이고, 나머지 **13,443장이 `UNKNOWN`**
이었다. 기르수 후보 35장은 전부 그 안에 있었다.

차단 지점의 원문:

```
UNCHECKED_RULES: #0 를 묘지로 보낼 수 있는지 판정할 수 없습니다:
  이 카드를 묘지로 보낼 수 있는가 (Card.IsAbleToGrave) ·
  묘지 대신 다른 곳으로 가는가 (펜듈럼 · 토큰 · 대체 효과).
  판정할 수 없는 것을 허가로 바꾸지 않습니다.
```

---

## 3. 공식 규칙 및 코드 근거

### 3.1 🔴 **쓰지 않은** 추론 — 일반 허용 규칙

6-W 가 룰북의 `Send to the Graveyard` 항목 전문을 읽어 확인했다. "제약이
없으면 보낼 수 있다" 류의 **허가 문장이 없다** (`unless` · `restriction`
둘 다 부재). 소환 쪽에는 그 문장이 **있다**:

> "All Normal Monsters, and most Effect Monsters (**unless they have a
> specific restriction**), can be Summoned in this way" — `RULE-SUMMON-009`

이 Phase 는 §4 의 조건문 — *"공식 룰북에 일반적인 카드 이동 허용 근거가
**있다면**"* — 을 다시 검증했다. 룰북 117절 가운데 묘지 · 이동 · 규칙
우선순위를 말하는 7절을 전문으로 읽었고, **일반 허용 근거는 없다.** 그래서
그 추론은 쓰지 않았다.

### 3.2 🔴 **쓴** 근거 — 카드 자신의 텍스트

같은 항목의 다른 문장이 **텍스트 모양과 묘지행을 직접 묶는다.**

> "A card can be sent to the Graveyard in various ways. Destroying a card,
> discarding, and Tributing a monster are all actions that send a card to
> the Graveyard, and will normally activate **"When this card is sent to
> the Graveyard…"** Trigger Effects."

읽는 방향이 중요하다. 이 문장은 "아무 카드나 묘지에 갈 수 있다" 를 말하지
않는다. **"이 카드가 묘지로 보내졌을 때" 유발은 카드를 묘지로 보내는 행동이
발동시킨다**를 말한다. 그러므로 그 유발을 **인쇄한** 카드는 묘지로 보내지는
카드다 — 대우가 아니라 그 문장의 직접적 귀결이다.

### 3.3 순서의 근거

> "If there is a discrepancy between the basic rules and a card's effect,
> the card effect takes precedence." — `Rules vs. Card Effects`

그래서 유도는 **마지막**이다. 등록소(사람이 읽은 것)와 룰북 유도가 먼저
답하고, 둘이 침묵할 때만 불린다. 순서가 뒤바뀌면 유도가 사람이 확인한
금지를 덮는다.

### 3.4 코드 근거 — `Card.IsAbleToGrave`

| 식별자 | 호출 수 | 파일 수 |
| --- | --- | --- |
| `IsAbleToGrave` (효과) | 676 | 544 |
| `IsAbleToGraveAsCost` (비용) | 811 | 664 |
| 둘 다 쓰는 파일 | — | 36 |

`semantics.py:456` 이 `MAY_BE_SENT_TO_GRAVE` 의 대응물을 **앞쪽**으로 적어
두었다. 기르수의 `s.tgfilter` 가 쓰는 것과 같은 함수다.

---

## 4. 채택한 최소 수정 방법

### 4.1 네 상황 중 **하나만** 코드를 더했다

§2 가 가르라고 한 네 상황을 실제 코드로 대조했다.

| | 상황 | 이미 되는가 | 이 Phase 가 한 일 |
| --- | --- | --- | --- |
| **A** | 기본 규칙상 묘지 이동 가능 | 통상 몬스터만 | 🔴 **유도 하나를 더했다** |
| **B** | 카드 자체에 이동 제한 | 토큰만 (룰북) | 🔴 **코퍼스에 자기 제한 카드가 0장**임을 측정 (§7.1) |
| **C** | 판에 이동을 막는 효과 | ✅ `_interference` | 그대로 — 측정으로 확인 |
| **D** | 묘지 대신 다른 영역 (대체) | ✅ `_interference` | 그대로 — 측정으로 확인 |

**C 와 D 는 손대지 않았다.** `restricts_others` 기본값이 참이므로, 등록소에
없는 카드가 필드 · 묘지 · 제외에 있으면 훑기가 `UNKNOWN` 에서 멈춘다. 대체
효과를 가진 47장 **전부가 등록소에 없다** — 그래서 그 카드가 깔린 판은
허가를 받지 못한다 (`test_g04`).

### 4.2 세 안을 비교했다

| 안 | 내용 | 판단 |
| --- | --- | --- |
| ① "제약 상수 없음 → `TRUE`" | 13,443장이 열린다 | 🔴 **기각** — 룰북 근거 없음 (§3.1). 근거 없는 허가다 |
| ② 자기 묘지행 유발 → `TRUE` | 991장이 열린다 | ✅ **채택** — 룰북이 그 모양을 묘지행에 묶는다 (§3.2) |
| ③ `EFFECT_CANNOT_TO_GRAVE` 3장을 `FALSE` | 금지를 적는다 | 🔴 **기각** — 그 상수는 **자기 제한이 아니다** (§7.1). `FALSE` 로 적으면 거짓 금지다 |

③의 기각이 이 Phase 의 조사 성과다. 6-W 보고서가 그 세 장을 "B — 묘지
이동 불가" 로 분류했는데, Lua 를 읽으면 **필드 효과**다 (§7.1).

### 4.3 유도를 **질문 하나**에 묶었다

6-W §13.1 이 선행 조건으로 적은 것을 지켰다. `normal_monster_facts` 는 다섯
질문을 한꺼번에 답하는데 (근거가 "효과가 없다" 여서 다섯에 모두 걸린다),
이쪽 근거는 묘지에 대한 것뿐이다. 그래서 표로 묶었다.

```python
DERIVED_FACTS: dict[RuleQuestion, object] = {
    RuleQuestion.MAY_BE_SENT_TO_GRAVE: self_grave_text_fact,
}
```

실측: 같은 카드에서 묘지만 `TRUE` 이고 나머지 넷은 `UNKNOWN` 이다
(`test_f01`).

### 4.4 신호에 **범위**를 함께 봤다

`EVENT_TO_GRAVE` 만 보면 *남이* 묘지로 갈 때 반응하는 카드가 자기 묘지행의
증거로 읽힌다. `effect_types` 의 적용 범위 축에서 `SINGLE`("이 카드 한
장") 을 함께 요구했다. 범위를 뺀 집계가 더 크고, 그 차이가 거짓 허가가 될
카드들이다 (`test_a04` 가 그 차이를 단언으로 고정한다).

---

## 5. 변경 파일과 함수

| 파일 | 추가 | 무엇 |
| --- | --- | --- |
| `core/card_model.py` | +51 | `SELF_GRAVE_TRIGGER_EVENT` · `SELF_GRAVE_TRIGGER_SCOPE` · `Card.self_grave_text_evidence` |
| `engine/game_state_view.py` | +26 | `CardDefinitionView.self_grave_text_evidence` (필드 27 → **28**) + `of` · `canonical_state` · `to_dict` |
| `engine/effect/ruling.py` | +105 | `SEND_TO_GRAVE_RULE` · `self_grave_text_fact` · `DERIVED_FACTS` · `derived_fact` · `BoardRuling.explain` 의 마지막 자리 |
| `tests/engine/test_graveyard_movement_ruling.py` | **신규** 31건 | A–G |
| `tests/engine/test_deck_to_grave_blocker.py` | 수정 | 6-W 가 고정한 BLOCKER 가 풀렸다 (§11.2) |
| `docs/phase6x-graveyard-movement-ruling.md` | **신규** | 이 보고서 |

### 5.1 세 값 규약을 6-U 에서 그대로 가져왔다

`Card.self_grave_text_evidence` 는 **세 가지 답**을 구분한다.

| 값 | 뜻 | 판정 |
| --- | --- | --- |
| `None` | 스크립트가 **없다** — 증거를 찾을 정보가 없다 | `UNKNOWN` |
| `False` | 끝까지 읽었고 그런 자리가 **없다** | `UNKNOWN` |
| `True` | 그 카드 자신의 텍스트가 자기 묘지행을 적었다 | `TRUE` |

실측 분포: `None` **1,440** · `False` **11,696** · `True` **991**.

🔴 **`None` 과 `False` 를 합치지 않았다.** 이 Phase 에서 그 방향은 특히
위험하다 — 합치면 "읽지 않았다" 가 허가로 흘러간다. 읽는 쪽은 `is True`
로 묻고, `to_dict` 도 `None` 을 `False` 로 바꾸지 않는다.

🔴 **처음에는 블록 이름 목록(`('e2',)`)을 실었다가 한 비트로 좁혔다.**
이유는 부록 A 에 있다.

### 5.2 `_interference` 를 건드리지 않은 이유

유도를 `_facts_of` 에 넣으면 `_interference` 가 그 `CardRuleFacts` 의
`restricts_others` 를 읽게 된다. 그 값은 **질문과 무관한 카드 단위
불리언**이므로, 묘지 근거로 만든 레코드가 "이 카드는 (모든 질문에 대해)
남을 막는다/안 막는다" 를 말하게 된다. 그래서 유도는 `explain` 안에서
**`RuleFact` 하나만** 돌려주고, 판 훑기는 손대지 않았다.

---

## 6. 이동 가능 판정 전후 비교

전체 14,127장에 대해 `MAY_BE_SENT_TO_GRAVE` 를 물었다.

| | `TRUE` | `UNKNOWN` | `FALSE` |
| --- | --- | --- | --- |
| **전** (6-W) | 684 | 13,443 | 0 |
| **후** (6-X) | **1,675** | **12,452** | 0 |
| 차이 | **+991** | **−991** | 0 |

🔴 **답이 뒤집힌 카드가 0장이다** (`test_g05`). 유도는 `UNKNOWN` 이던 자리만
채운다 — 이미 답이 있던 684장은 그대로다. 그것이 "등록소와 룰북이 먼저" 의
결과다.

새로 허가된 991장: 메인 덱 **818** · 엑스트라 덱 **173** · 토큰 **0**.

### 6.1 기르수 판에서의 변화

| | 6-W | 6-X |
| --- | --- | --- |
| 덱 후보 | 35 | 35 (그대로) |
| 그중 `TRUE` | **0** | **1** |
| 그중 `UNKNOWN` | 35 | 34 |
| 해결 | `UNCHECKED_RULES` | **`RESOLVED`** |

후보 생성은 6-W 에서 이미 정확했다 (거짓 양성 0건). 바뀐 것은 **판정**이다.

---

## 7. 금지·대체 효과의 거짓 양성 테스트

### 7.1 🔴 6-W 의 분류 하나를 정정했다

6-W 보고서 §3.1 은 차원요새 병기(1596508)를 "**B 불가**
(`EFFECT_CANNOT_TO_GRAVE`)" 로 적었다. Lua 를 읽으면 그렇지 않다.

```lua
local e1=Effect.CreateEffect(c)
e1:SetType(EFFECT_TYPE_FIELD)              -- 필드 효과다
e1:SetCode(EFFECT_CANNOT_TO_GRAVE)
e1:SetRange(LOCATION_MZONE)                -- 필드에 있을 때 적용
e1:SetTargetRange(LOCATION_DECK,LOCATION_DECK)  -- 🔴 **덱의 카드**를 막는다
```

그 상수를 쓰는 **세 장 전부** 같은 모양이다 (`c1596508` · `c54407825` ·
`c9272381`): `EFFECT_TYPE_FIELD` + `SetTargetRange(LOCATION_DECK,
LOCATION_DECK)`.

🔴 **그래서 코퍼스에 "자기가 묘지로 못 간다" 를 선언한 카드는 0장이다.**
§5 의 B(명시적 금지)는 **토큰**뿐이고, 그것은 룰북이 답한다. 그 세 장은
B 가 아니라 **C** 다 — 그리고 정확히 기르수를 막는 종류의 효과다.

측정: 그 세 장 자신의 묘지행은 `UNKNOWN` 이다 (`FALSE` 가 아니다) —
**거짓 금지도 만들지 않았다** (`test_c05`).

### 7.2 §5 의 10사례 — 전부 테스트했다

| # | 사례 | 결과 | 시험 |
| --- | --- | --- | --- |
| 1 | 일반적인 덱 몬스터의 효과에 의한 묘지 이동 | **`TRUE`** (증거 있을 때) | `test_c01` |
| 2 | 명시적으로 묘지 이동이 금지된 카드 | **`FALSE`** — 토큰 (룰북) · 코퍼스에 그 외 0장 | `test_c02` |
| 3 | 묘지 이동을 금지하는 지속 효과 적용 중 | **`UNKNOWN`** — 훑기가 멈춘다 | `test_c03` · `test_b03` |
| 4 | 묘지 대신 제외되는 대체 효과 | **`UNKNOWN`** — 결과 영역이 다르다 | `test_c04` |
| 5 | 제한 효과의 적용 대상이 아닌 카드 | **`UNKNOWN`** (거짓 금지 아님) | `test_c05` |
| 6 | 카드 정의가 없는 상황 | **`UNKNOWN`** — "보이지 않아" | `test_c06` |
| 7 | Lua · 제한 데이터가 부족한 상황 | **`UNKNOWN`** — 신호가 `None` | `test_c07` |
| 8 | 비용으로 묘지에 보내는 행동 | 다른 질문 · 다른 상수 | `test_b02` · `test_c08` |
| 9 | 효과 해결로 묘지에 보내는 행동 | `cost.costs == ()` · `gated=True` | `test_c08` |
| 10 | 덱에 실제 카드가 없는 상황 | 후보 0건 · 카드를 만들지 않는다 | `test_c09` |

### 7.3 991장 전수 역검증 — **거짓 허가 0건**

6-U 가 4,028장에 한 것과 같은 방식이다. 새로 허가된 991장 전부가 공식
텍스트로 되짚어진다.

| 어떤 행동으로 묘지에 가는가 | 카드 수 | 룰북 근거 |
| --- | --- | --- |
| 「묘지로/에 보내」 (직접) | **953** | `Send to the Graveyard` |
| 「버려」 (discard) | **33** | `Discard` — *"send a card from your hand to the Graveyard"* |
| 「파괴되」 (destroyed) | **3** | `Send to the Graveyard` — *"Destroying a card … send a card to the Graveyard"* |
| 엑시즈 소재 제거 | **2** | 소재는 제거되면 묘지로 간다 |
| 🔴 **설명되지 않는 카드** | **0** | — |

> **내가 두 번 틀렸고 두 번 고쳤다.** 첫 측정은 어구가 좁아 81장이
> 불일치로 나왔다 (「묘지로 보내진 턴」 · 「묘지로 버려졌을」 을 못 잡았다).
> 어간으로 넓히니 13장이 남았고, 그 13장을 하나씩 읽으니 「묘지로 **직접**
> 보내졌을」 처럼 단어가 끼인 경우와 파괴 · 버리기로 표현된 경우였다.
> 🔴 **그래서 어구 목록은 프로덕션에 넣지 않았다** — 판정의 입력은 스크립트
> 신호이고, 어구는 사람이 되짚는 감사용이다 (`GRAVE_GOING_PHRASES`).

반대 방향(위험한 쪽)도 쟀다.

| 검사 | 결과 |
| --- | --- |
| 허가된 991장 중 `EFFECT_CANNOT_TO_GRAVE` 보유 | 🔴 **0건** |
| 허가된 991장 중 `EFFECT_CANNOT_TO_GRAVE_AS_COST` 보유 | 🔴 **0건** |
| 허가된 991장 중 토큰 | 🔴 **0건** |
| 허가된 991장 중 `EFFECT_TO_GRAVE_REDIRECT` 보유 | **2건** — §7.4 |

### 7.4 대체 상수를 가진 2장은 모순이 아니다

46502744 · 79606837 이 `EFFECT_TO_GRAVE_REDIRECT` 를 가진 채 허가됐다.
Lua 를 읽으면 둘 다 `EFFECT_TYPE_FIELD` + `SetRange(LOCATION_MZONE)` +
`SetValue(LOCATION_REMOVED)` 다 — **그 카드가 필드에 있을 때 남을** 제외로
보내는 효과이고, 자기 묘지행을 막는 것이 아니다.

그리고 대체 효과를 가진 **47장 전부가 등록소에 없다.** 그래서 그 카드가
필드 · 묘지 · 제외에 있으면 `restricts_others` 기본값(참)이 살아 훑기가
멈춘다 (`test_g04`).

---

## 8. 기르수 효과 발동과 체인 해결

프로덕션 경로만 썼다. 등록소 사본도, 임시 사실도 없다.

```
build_opening → Duel.legal_actions(MINE)
  → PlayerActionKind.NORMAL_SUMMON (기르수)        ✅ accepted
  → MonsterSummoned / MONSTER_SUMMONED             ✅ (6-V)
  → TriggerRegistry → 후보 생성                     ✅ (6-V)
  → 덱 후보 35건 · 거짓 양성 0건                     ✅ (6-W)
  → EffectActivator.activate(...)                  ✅ activated
  → ChainResolver.resolve_top(...)                 ✅ **RESOLVED**
  → EffectExecutor → BoardRuling                   ✅ TRUE
  → CardOperation → GameState                      ✅ 이동
  → EventJournal                                   ✅ 기록
```

🔴 **임의의 첫 카드를 고르지 않았다** (§6). 시험이 `chosen_filter` 로 어느
카드인지 명시한다. 사용자 선택이 필요한 실제 Duel 과 테스트의 명시적 선택을
구분해 적는다 — `legal_actions` 는 여전히 덱 선택 효과를 제공하지 않는다
(`STRUCTURAL-125`, 6-W §1.1 이 그 경계가 옳은 이유를 적었다).

### 8.1 증거가 없으면 그대로 멈춘다

같은 효과 · 같은 판에서 **증거 없는 후보**를 고르면:

```
발동: activated      해결: UNCHECKED_RULES
덱 변화 없음 (35)     기록: []
```

🔴 **유도가 통째로 허가가 되지 않았다는 증거다** (`test_d04`).

---

## 9. 실제 Deck → Graveyard 이동 결과

| 축 | 해결 전 | 해결 후 |
| --- | --- | --- |
| 덱 장수 | 35 | **34** |
| 묘지 장수 | 0 | **1** |
| 고른 인스턴스의 존 | `DECK` | **`GRAVE`** |
| 그 인스턴스의 `card_id` | 93920420 | **93920420** (보존) |

§6 의 최소 성공 기준 대조:

| 기준 | 결과 |
| --- | --- |
| 올바른 오르페골/성유물 후보 생성 | ✅ 35건 · 거짓 양성 0 |
| 실제 덱에 있는 `CardInstance` 선택 | ✅ `InstanceId` 로 지목 |
| 이동 가능성 판정 | ✅ `TRUE` · 근거 `CARD_TEXT` |
| 카드 효과 해결 | ✅ `RESOLVED` |
| Deck → Graveyard 이동 | ✅ |
| 덱 카드 수 감소 | ✅ 35 → 34 |
| 묘지 카드 수 증가 | ✅ 0 → 1 |
| `EventJournal` 기록 | ✅ §10 |
| 후속 `legal_actions` 생성 | ✅ `end_phase` · `set_spell_trap` |

---

## 10. GameState 및 EventJournal 검증

```
#0 69811710:e[0] P0: #34 P0/DECK → P0/GRAVE (send_to_grave),
   P0 의 DECK 34장을 섞었다
```

세 가지가 함께 적혀 있다.

1. **출처** — `69811710:e[0]` (어느 카드의 어느 효과인가)
2. **이동** — `#34 P0/DECK → P0/GRAVE (send_to_grave)` (어느 인스턴스가 어디서 어디로, 어떤 이유로)
3. **셔플** — `P0 의 DECK 34장을 섞었다`

🔴 **셔플이 기록에 있는 것이 중요하다.** 룰북이 요구한다 — *"You must
shuffle your Deck after any time you search it and let your opponent
shuffle or cut."* 덱을 들여다본 효과가 그것을 적지 않으면 기록이 규칙과
어긋난다 (`test_d02`).

---

## 11. 기존 기능 회귀

### 11.1 §7 의 검증 범위 대조

| 기능 | 결과 |
| --- | --- |
| 효과 몬스터 일반 소환 (6-U) | ✅ `test_effect_monster_normal_summon` |
| 기르수 TRIGGER 후보 생성 (6-V) | ✅ `test_summon_trigger_execution` |
| 적법한 덱 카드 후보 생성 (6-W) | ✅ `test_deck_to_grave_blocker` |
| 어니스트 효과 실행 | ✅ stage ①–③ |
| 카드 이동 및 자기 참조 | ✅ `test_self_reference_target` |
| 다중 카드 선택 | ✅ `test_multi_target_selection` |
| 함정 발동과 체인 해결 | ✅ `test_trap_activation_free_chain` · `test_chain*` |
| 일반 소환권과 GameState 정합성 | ✅ `test_d03` (해결 뒤 `normal_summon` 이 없다) |
| Discord `/combo` 실행 경로 | ✅ `test_discord_bot` |
| 🔴 **기르수 외 다른 카드** | ✅ **어리석은 매장** — §11.3 |

### 11.2 6-W 가 고정한 BLOCKER 가 풀렸다 — 시험 셋을 다시 적었다

| 시험 | 6-W 의 주장 | 6-X 에서 |
| --- | --- | --- |
| `test_f01_the_gate_cannot_tell_the_three_situations_apart` | "셋 다 같은 답이고 이유문까지 같다" | 🔴 **더 이상 참이 아니다** → `test_f01_the_gate_now_tells_evidence_from_no_evidence` 로 다시 적었다 |
| `test_g01` · `test_g02` | "해결이 멈춘다 · 판이 변하지 않는다" | **여전히 참이다** — 그 판의 후보에 증거 카드가 없다. 🔴 **그 전제를 암묵에서 명시로 바꿨다** (단언을 추가했다) |
| `test_i01` | "막는 것은 사실 하나다 (등록소 사본으로 증명)" | **여전히 통과한다** — 이제 **등가성**의 증거다 (손으로 적은 사실과 유도된 사실이 같은 결과에 이른다) |

🔴 **삭제도 skip 도 assertion 완화도 없다.** `test_f01` 은 더 날카로운
단언으로 바뀌었고 (`TRUE` 와 `UNKNOWN` 을 **구분해** 단언한다),
`test_g01`/`test_g02` 는 단언이 **늘었다**.

### 11.3 어리석은 매장 — 공통성 검증 (§7 의 요구)

| | 기르수 (69811710) | 어리석은 매장 (81439173) |
| --- | --- | --- |
| 발동 분류 | `TRIGGER` | **`None`** (카드 발동) |
| 선택 | `CHOOSING` · `DECK` | `CHOOSING` · `DECK` |
| 조작 | `SEND_TO_GRAVE(gated=True)` | `SEND_TO_GRAVE(gated=True)` |
| 증거 있는 카드 선택 | **`RESOLVED`** · 덱 −1 · 묘지 +1 | **`RESOLVED`** · 덱 −1 · 묘지 +1 |
| 증거 없는 카드 선택 | `UNCHECKED_RULES` · 불변 | `UNCHECKED_RULES` · 불변 |

🔴 **발동 분류가 서로 다른데 같은 관문을 지나 같은 결과에 이른다** — 규칙이
카드에 묶이지 않았다는 증거다 (`test_e01` · `test_e02`).

### 11.4 카드 ID 기반 분기가 없다

판정 계층이 보는 것은 상수 이름 둘(`EVENT_TO_GRAVE` · `SINGLE`)과 관측에
실린 신호뿐이다. `engine/effect/ruling.py` 에 이 Phase 가 다룬 카드 번호도
카드군 이름도 **없다** (`test_f04`).

---

## 12. 테스트 통과·실패·실행 시간

(§TEST_RESULTS)

---

## 13. 남은 구조적 BLOCKER

| ID | 내용 | 이번 Phase |
| --- | --- | --- |
| **BLOCKER-6X-1** | 🔴 **대체 효과를 실행하지 못한다.** `EFFECT_TO_GRAVE_REDIRECT` (31) · `_CB` (16) 가 깔린 판은 `UNKNOWN` 에서 멈춘다. 보수적이지만, 그 판에서는 어떤 묘지 이동도 해결되지 않는다 | 범위 확정 · 고치지 않음 |
| **BLOCKER-6X-2** | 🔴 **덱 카드를 막는 지속 효과를 읽지 못한다.** `EFFECT_CANNOT_TO_GRAVE` 세 장은 `SetTargetRange(DECK,DECK)` 로 덱 카드를 막는데, 판정은 그 **범위**를 읽지 않고 "모르는 카드가 있다" 로만 멈춘다. 맞는 답이지만 이유가 정확하지 않다 | 원인 확정 · 고치지 않음 |
| **BLOCKER-6X-3** | 증거가 없는 **12,452장**은 여전히 `UNKNOWN` 이다. 그 대부분은 실제로 묘지에 갈 수 있는 카드인데, 그것을 말할 룰북 근거가 없다 (§3.1) | 측정 · 근거 없는 허가를 하지 않음 |
| `STRUCTURAL-98` | 패에서 적용되는 지속 효과를 못 본다. 판정마다 `unchecked` 에 실린다 | 그대로 (§1.2) |
| `STRUCTURAL-125` | 해결 시점 선택이 `PlayerAction` 에 들어갈 수 없다. **경계가 옳다** | 그대로 |
| `STRUCTURAL-7` | 분석 → 정의 컴파일러가 없다 (`EFFECT_LIBRARY` 18건) | 그대로 |
| `BLOCKER-6W-4` | 센서스 감사가 영향 파일 grep 에 안 걸린다 | 🔴 이번에는 **센서스 감사를 묶음에 넣었다** (§12) |

---

## 14. 다음 최소 개발 단계 추천

**14.1 (권장) `SetTargetRange` 를 읽어 `_interference` 의 이유를 정확히 한다**

`BLOCKER-6X-2` 의 최소 해법이다. `EffectSpec.target_ranges` 가 이미
파싱되어 있으므로, 금지 · 대체 상수를 가진 카드의 **적용 범위**를 신호로
올리면 "MZONE 의 1596508 에 대해 확인된 것이 없다" 가 "1596508 이 덱의
카드가 묘지로 가는 것을 막는다" 가 된다. 답(`UNKNOWN`)은 같고 **이유가
정확**해진다. 50장 규모이고 질문 하나에 묶을 수 있다.

**14.2 묘지행 대체 효과의 실행 (`BLOCKER-6X-1`)**

`SetValue(LOCATION_REMOVED)` 를 읽어 **도착지를 바꾸는** 조작이 필요하다.
`CardOperation` 에 대체 도착지 개념이 없으므로 공유 계약 변경이고, **별도
Phase 와 사용자 승인** 대상이다.

**14.3 `legal_actions` 가 덱 선택 효과를 제공하는 계약 (`STRUCTURAL-125`)**

이번 Phase 로 **해결은 되지만 자율 발동은 아직 안 된다.** AI 가 기르수
효과를 스스로 쓰려면 해결 중 선택을 요청하는 계약이 필요하다. 이것도 공유
계약 변경이다. 🔴 **갈라테아의 장기 목표(선공 패로 전개 탐색)에 가장
직접적인 다음 단계다.**

**14.4 다른 `gated` 조작의 질문들**

`MAY_BE_RETURNED_TO_HAND` · `MAY_BE_BANISHED` · `MAY_BE_RETURNED_TO_DECK` ·
`MAY_BE_DISCARDED` 는 그대로 `UNKNOWN` 이다. 같은 방식(카드 자신의 텍스트가
그 이동을 적었는가)으로 질문별 유도를 더할 수 있고, `DERIVED_FACTS` 가 그
자리를 이미 만들어 두었다.

---

## 15. Git 커밋·푸시 결과

(§GIT_RESULTS)

---

## 부록 A. 🔴 설계 경계를 또 깼고, 또 루트가 잡았다

이 절은 **내가 틀린 기록**이다. 6-V 부록 A 와 같은 종류의 실수를 **같은
자리에서** 다시 했다.

### A.1 무엇을 깼는가

첫 구현은 관측에 **블록 이름 목록**을 실었다.

```python
Card.self_grave_trigger_signals -> tuple[str, ...] | None   # ('e2',)
CardDefinitionView.self_grave_trigger_signals
```

`tests/engine` 3,600여 건과 Duel 수직 통합 513건이 **전부 통과했고**, 루트
회귀에서 깨졌다.

```
FAILED tests/test_trigger_semantics_audit.py
       ::test_13_trigger_metadata_never_reaches_the_observation
FAILED tests/test_event_phase_semantics_audit.py
       ::test_15_the_view_exposes_the_current_phase_but_no_trigger_metadata
```

두 감사의 주장:

> **§12 · §16-D — 유발 메타데이터가 관측으로 나가지 않는다.**
> 내부에 데이터가 있다는 것과 AI 가 그것을 볼 수 있다는 것은 다른 일이다.

그리고 그것을 두 가지로 지킨다 — `CardDefinitionView` ·
`GameStateView` 의 **필드 이름**에 `trigger` · `event` 가 없고,
`engine/game_state_view.py` **본문**에 `EVENT_` · `trigger` ·
`TriggerSpec` 토큰이 없다.

### A.2 이름 충돌이 아니라 **내용 위반**이었다

처음에는 이름만 걸린 줄 알았다. 아니었다. `('e2',)` 는

- **어느 효과 자리**가 그렇게 등록했는지 말하고,
- 그 자리가 **어떤 사건**(`EVENT_TO_GRAVE`)으로 등록했는지 docstring 이
  적고 있었다.

즉 상대 카드의 유발 사건 정체가 관측으로 나갈 수 있었다. **감사의 주장이
옳았고 내 구현이 틀렸다.**

### A.3 어떻게 고쳤는가 — 6-F · 6-V 와 같은 방법

받는 쪽에 필요한 **최소값**만 넘긴다. 판정이 필요한 것은 "그 텍스트가
있는가" **한 가지**이므로 한 비트만 싣는다.

```python
Card.self_grave_text_evidence -> bool | None
```

| | 첫 구현 | 고친 뒤 |
| --- | --- | --- |
| 관측이 내보내는 것 | 블록 이름 목록 + (문서로) 사건 이름 | **한 비트** |
| 세 값 규약 | `None` · `()` · 비어 있지 않음 | `None` · `False` · `True` |
| 감사 두 건 | 실패 | **수정 없이 통과** |
| 기르수 해결 | `RESOLVED` | `RESOLVED` (동일) |

🔴 **고친 쪽이 더 좁다.** 테스트를 바꾸지 않았고, 내보내는 정보가 줄었다.

### A.4 남는 교훈

**6-V 가 적은 문장이 그대로 또 맞았다** — *"tests/engine 만으로는 설계 경계
감사를 지나칠 수 없다 — 그 감사들은 루트에 있다."*

6-X 가 거기에 한 줄 더한다. **관측에 새 칸을 더할 때는 "이 값이 무엇을
말하는가" 를 먼저 묻는다.** 6-U 의 `normal_summon_restriction_signals` 는
상수 **등장 여부**를 실었으므로 통과했고, 내 첫 구현은 **어느 자리가 어떤
사건으로** 를 실었으므로 걸렸다. 같은 모양의 칸이라고 같은 경계에 있는
것이 아니다.

### A.5 `.code` 센서스 — 이쪽은 경계가 **안 깨졌다**

같은 회귀가 둘을 더 잡았다.

```
FAILED tests/test_activation_precondition_audit.py::test_05_no_engine_file_reads_the_code_field
FAILED tests/test_effectdefinition_trigger_boundary_audit.py::test_14_the_engine_never_reads_the_setcode_argument_today
```

두 감사의 **주장**은 "`engine` production 이 `EffectSpec.code` 를 읽지
않는다" 이고, 그 주장은 **그대로 참이다** — `core/card_model.py` 는
`engine/` 이 아니다. `test_14` 의 `engine/` 전용 단언은 통과했다.

그리고 측정해 보니 `core/card_model.py` 는 **이 Phase 전에도 이미**
`.code` 를 읽고 있었다.

| 줄 | 수신자 | 어디 | 언제 |
| --- | --- | --- | --- |
| 544 | `e.code` | `Card.has_code` | 이 Phase 전부터 |
| 606 | `spec.code` | `Card.self_grave_text_evidence` | **6-X** |
| 620 | `eff.code` | `Card.can_self_special_summon_from_hand` | 이 Phase 전부터 |

앞뒤 둘이 센서스에 없었던 것은 그 감사가 **수신 변수 이름**으로 세기
때문이고 (그 선택의 이유는 감사 자신의 주석이 적는다 — `"block"` 이
`"blocked"` 에 걸린 과거 때문이다), 6-X 의 변수명이 우연히 `spec` 이어서
드러났다.

그래서 이쪽은 **분모 정정**이다. 두 센서스에 `core/card_model.py` 를
더하고, `test_05` 에는 `engine/` 전용 단언을 **새로 하나 더했다** —
그것이 그 감사가 실제로 지켜야 하는 것이다.
