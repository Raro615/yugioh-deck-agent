# Phase 6-M — 카드 이동 출발 영역 규칙 및 `RETURN_TO_HAND` 정합성

> **달성 수준: §17 수준 2 (실제 효과 이동 검증) 달성.**
>
> 다만 **지원 범위는 넓어지지 않았다** — 실행 가능한 효과는 6-L 과 똑같이
> 14건이다. 6-M 이 바꾼 것은 **정확성**이다 (§12).
>
> 🔴 **과제 설명의 전제가 코드와 반대였다.** §2 는 "`ORIGIN_RULES` 에
> `RETURN_TO_HAND` 관련 출발 영역 제약이 있다 … 일부 정상적인 카드 이동이
> 기존 제약으로 인해 차단될 수 있다" 고 적었다. 실측은 반대다 — **제약이
> 하나도 없었고**, 막힌 이동은 하나도 없었으며, **모든 이동이 열려
> 있었다.** 그 열림이 결함이었다 (§2 · §3).

- 브랜치 `claude/pensive-goodall-te1egy` · 시작 HEAD `42b5362`
- 작업 전 작업 트리 clean, 원격과 동일

---

## 1. 기존 `CardOperation` 및 `ORIGIN_RULES` 의 실제 구조

### 1-1. 이동을 결정하는 표는 **넷**이고 서로 다른 축이다

| 표 | 파일 | 무엇을 정하는가 | `RETURN_TO_HAND` |
|---|---|---|---|
| `ORIGIN_RULES` | `engine/effect/semantics.py` | 일의 종류마다 **출발** 자리 | **항목 없음** |
| `DESTINATION` | `engine/effect/executor.py` | 일의 종류마다 **도착** 자리 | `Zone.HAND` |
| `DESTINATION_OWNER` | 같음 | 도착 자리의 **주인** | `OWNER` |
| `DECLARED_GATE_RULINGS` | `semantics.py` | 카드가 **선언할 때만** 묻는 관문 | `MAY_BE_RETURNED_TO_HAND` |

실측 — `ORIGIN_RULES` 전수는 **두 줄**뿐이다.

```
discard   zones=['HAND']                             known=True   missing=None
destroy   zones=['EMZONE','FZONE','MZONE','PZONE','SZONE']
                                                     known=False  missing=off-field destruction
```

그 표의 docstring 이 왜 두 줄뿐인지 직접 적어 두고 있었다 — "``SEND_TO_GRAVE``
가 여기 없는 것은 우연이 아니다 … 모르는 것을 빈 제약으로 적으면 '전부
허용' 이 규칙인 것처럼 보인다."

### 1-2. `OriginRule` 은 **종류 하나에 규칙 하나**다

```python
ORIGIN_RULES: dict[OperationKind, OriginRule]
```

구조 자체가 **전역**이다. `OperationKind.RETURN_TO_HAND` 에 줄을 더하면 그
제약이 **모든** 패 되돌림에 걸린다. 그것이 6-M 이 이 표를 건드리지 않은
이유이고, §3 에 근거를 수치로 적었다.

### 1-3. 실행 경로 (§4-C)

```
EffectExecutor.execute
  → _plan_card_operation        ← 계획 단계. 판을 읽기만 한다 (ADR-008)
       _target_spec_of / _resolve_selection
       state.find_instance      ← 판에 있는가
       origin_rule(kind)        ← 전역 출발 자리
       _check_rule_gate         ← 카드가 선언한 관문
       movement_player(...)     ← 도착 주인 (계획이 정한다)
  → _apply_card_movement        ← 여기서만 판이 바뀐다
       state.move(...)
       ZoneMoved 델타 → EventJournal
```

비용은 **다른 모듈**이다 (`engine/payment.py`, `CostPayer.pay`), 그리고
`EffectActivator.activate` 가 부른다. 실행기는 지불기를 들고 있지도 않다
(§9).

---

## 2. `RETURN_TO_HAND` 를 차단하던 정확한 원인 — **없었다**

6-L 보고서 §16-1 이 적은 가설을 코드로 재검증했고, 그대로였다.

구현 전 실측 (어니스트 ①, 열 자리 전부, `gated=True` · `gated=False` 양쪽):

| 출발 자리 | 결과 | 카드 위치 |
|---|---|---|
| `MZONE` · `EMZONE` · `SZONE` · `FZONE` · `PZONE` | `RESOLVED` | `HAND` |
| `GRAVE` · `REMOVED` · `DECK` · `EXTRA` | `RESOLVED` | `HAND` |
| `HAND` | `RESOLVED` | `HAND` ← **아무 일도 없었는데 성공** |

🔴 **차단은 하나도 없었다.** 그러므로 §2 가 말한 "정상적인 카드 이동이
기존 제약으로 인해 차단될 수 있다" 는 현재 코드에서 **재현되지 않는다.**
`gated=True` 가 통과한 것도 근거가 있다 — 6-L 이 어니스트에 대해
`MAY_BE_RETURNED_TO_HAND = TRUE` 를 공식 텍스트 근거로 답해 두었고, 그
답은 **자리를 묻지 않는다.** 그것이 §1 의 핵심 원칙이 가리킨 바로 그
자리다.

> "카드를 패로 되돌릴 수 있다" 는 사실만으로 어떤 영역에서든 모든 카드를
> 패로 이동시킬 수 있다는 의미가 되는 것은 아니다.

추가로 **카드 종류를 하나도 보지 않았다.**

| 카드 | 구현 전 결과 | 패 | 엑스트라 |
|---|---|---|---|
| 궁극의 푸른 눈의 백룡 (FUSION) | `RESOLVED` | **1장** | 0장 |
| 암흑차원의 전사 (SYNCHRO) | `RESOLVED` | **1장** | 0장 |

융합 · 싱크로 몬스터가 **패에 들어갔다.**

---

## 3. 현재 제약이 정당했던 부분과 오류였던 부분

| 자리 | 판정 | 근거 |
|---|---|---|
| `ORIGIN_RULES` 에 `RETURN_TO_HAND` 가 **없는 것** | 🟢 **정당** | 전역 표이고, 필드 밖에서 패로 되돌리는 공식 스크립트가 많다 (아래 측정) |
| `ORIGIN_RULES[DISCARD] = {HAND}` · `known=True` | 🟢 정당 | 룰북이 말하는 규칙이고 6-M 이 건드리지 않았다 |
| `DESTINATION[RETURN_TO_HAND] = HAND` | 🟢 정당 | 보통의 메인 덱 카드에 대해 맞다 |
| `DESTINATION_OWNER` 전부 `OWNER` | 🟢 정당 | 실측으로 확인 (§7 D) |
| **이 효과가 적은 출발 자리를 적을 칸이 없었다** | 🔴 **오류** | 어니스트 ① 의 공식 텍스트가 「필드의」 라고 적는데 옮길 자리가 없었다 |
| **엑스트라 덱 몬스터를 메인 덱 카드처럼 옮겼다** | 🔴 **오류** | 룰북의 `Hand` · `Deck` 칸에 그 카드가 들어오는 길이 없다 |
| **일어나지 않은 이동을 성공으로 기록했다** | 🔴 **오류** | §11-5 를 정면으로 위반한다 (`P0/HAND → P0/HAND`) |

### 3-1. 전역으로 좁히면 틀리는 카드를 **셌다**

표본: 저장소의 `c*.lua` **12,968개 전부**. 세는 것은 `Duel.SendtoHand` 를
쓰는 파일 중 필드 밖 자리 상수를 함께 적은 파일 수다. **정적 분석이고
실행 수치가 아니다.**

| 측정 | 값 |
|---|---|
| 스크립트 총수 | 12,702 |
| `Duel.SendtoHand` 를 쓰는 스크립트 | **2,588** |
| 그중 `LOCATION_GRAVE` 를 함께 적음 | **1,337** |
| 그중 `LOCATION_DECK` 를 함께 적음 | **1,698** |
| 그중 `LOCATION_REMOVED` 를 함께 적음 | **252** |
| 그중 필드 밖 자리를 하나라도 적음 | **2,285** (2,588 중 88%) |

패로 되돌리는 스크립트의 **88%** 가 필드 밖 자리를 함께 적는다.
`ORIGIN_RULES[RETURN_TO_HAND] = FIELD_ZONES` 를 적으면 그 2,285개가 전부
틀린다. 그래서 전역 표에 줄을 더하는 선택지는 **측정으로 기각**됐다.

🔴 이 숫자는 **정적 분석**이다. "그 카드의 효과가 실제로 묘지에서 패로
되돌린다" 를 증명하지 않는다 — 한 파일에 여러 효과가 있고, 자리 상수가
다른 효과의 것일 수 있다. 증명하는 것은 더 약하고 충분한 것이다:
**전역으로 좁히면 영향을 받을 수 있는 카드가 세 자리 수가 아니라 네 자리
수다.**

---

## 4. 실제 카드 이동 규칙의 근거

### 4-1. 어니스트 ① — 「필드의」

공식 한국어 텍스트 (저장소의 공식 DB 원문, **번역하지 않았다**):

> 「**필드의 앞면 표시의** 이 카드를 패로 되돌린다」

공식 Lua (`c37742478.lua`):

```lua
e1:SetType(EFFECT_TYPE_IGNITION)
e1:SetRange(LOCATION_MZONE)
...
local c=e:GetHandler()
if c:IsFaceup() and c:IsRelateToEffect(e) then
    Duel.SendtoHand(c,nil,REASON_EFFECT)
end
```

둘이 같은 것을 말한다. 「필드의」 만 옮겼고, 「앞면 표시의」 는 **자리가
아닌 다른 축**이어서 옮기지 않았다 (§16).

### 4-2. 엑스트라 덱 몬스터 — 룰북의 **침묵**이 근거다

`data/rules/structured/sd-rulebook-en-v10.json` 의 `zones`:

| 칸 | `movement` |
|---|---|
| `Hand` | "draw 5 cards from the top of your Deck at the start of the Duel" |
| `Deck` | "draw cards from here to add to your hand" |
| `Extra Deck` | "Extra Deck Monsters may be Summoned to the field from here using special methods" / "**Pendulum Monster Cards that would be sent from the field to the Graveyard are placed face-up here**" |

🔴 **그래서 "엑스트라 덱으로 간다" 고 적지 않았다.** 룰북은 그런 우회를
말할 때 **명시한다** — 펜듈럼 문장이 그 증거다. 패 · 덱으로 가는 경우에
대해서는 그런 문장이 없으므로, 목적지를 **지어내지 않고 모른다로 멈춘다.**

`MOVABLE_DESTINATIONS` 에 `Zone.EXTRA` 가 **없다**는 것도 같은 방향이다 —
이 엔진은 엑스트라 덱으로 카드를 옮길 줄 모른다.

### 4-3. 토큰 — 이 엔진에 **들어올 수 없다**

| 측정 | 값 |
|---|---|
| `cards.cdb` 의 `TYPE_TOKEN` 카드 | **241장** |
| `CardRepository` 가 실은 토큰 | **0장** |

`OfficialDatabaseSource.iter_cards(include_tokens=False)` 가 기본값이고,
production 에서 `True` 를 넘기는 자리가 **없다** (테스트 한 곳뿐).

그러므로 "토큰이 패에 남지 않게 한다" 는 **지금 고칠 수 있는 결함이
아니다** — 토큰 `CardInstance` 를 만들 수조차 없다 (`definition` 이
`KeyError`). 데이터 파이프라인 변경은 이번 범위가 아니므로 (§3-18)
**미지원으로 보존하고 수치로 적었다.**

---

## 5. 채택한 최소 수정 방식과 대안 비교

§9 의 네 선택지를 전부 재 보았다.

| 대안 | 채택 | 이유 |
|---|---|---|
| **A** `ORIGIN_RULES` 의 잘못된 제약 수정 | ❌ | **잘못된 제약이 없었다.** 줄이 없는 것이 맞고, 더하면 §3-1 의 카드들이 틀린다 |
| **B** 카드 타입별 도착 자리 판정 재사용 | ✅ **부분** | `is_extra_deck` 는 이미 있는 파생값이고 `engine/summon_rules.py` 가 같은 값을 읽는다. 다만 **도착 자리를 정하지 않고 거절한다** — 근거가 없으므로 |
| **C** `CardOperation` 의 출발 · 도착 자리 연결 개선 | ✅ **주된 수정** | 출발 자리를 **이 효과가** 적게 하고, 도착 자리를 정하는 자리를 하나로 모았다 |
| **D** 미지원과 불법 이동의 구분 보완 | ✅ | 두 거절이 서로 다른 상태 · 코드 · `missing` 으로 나간다 (§7) |

### 왜 C 가 최소인가

- 새 `OperationKind` 를 만들지 않았다 (§3-4).
- 새 `Zone` 도, 새 이동 모듈도 없다.
- `PlayerAction` · `GameState` · `ResolutionContext` · `EffectDefinition` ·
  `TargetRequirement` 를 **하나도 바꾸지 않았다** (§3-2).
- `CardOperation` 에 **기본값이 있는 칸 하나**를 더했다. `None` 이
  "적지 않았다" 이고, 그 기본값에서 **오늘까지의 동작이 그대로다**
  (§8 "최소한의 하위 호환 확장").

---

## 6. 변경한 파일 및 함수

| 파일 | +/− | 무엇 |
|---|---|---|
| `engine/effect/executor.py` | +132 −13 | `movement_destination` · `movement_player` · `_is_extra_deck` · `_movement_refusal` |
| `engine/effect/operation.py` | +66 −3 | `CardOperation.origin_zones` + 검증 + `canonical_state` · `to_dict` |
| `engine/effect/semantics.py` | +35 −0 | `MAIN_DECK_ONLY_ZONES` · 두 `missing` 이름 |
| `engine/effect/library.py` | +26 −5 | 어니스트 ① 이 「필드의」 를 적는다 |
| **합계** | **+259 −21** | production 4파일 |

새 모듈 **0개**. 새 `OperationKind` · 새 `Zone` · 새 이동 엔진 **0개**.

### 6-1. 조작이 자기 출발 자리를 적는다

```python
@dataclass(frozen=True, slots=True)
class CardOperation(Operation):
    ...
    origin_zones: "frozenset[Zone] | None" = None
```

`__post_init__` 이 **빈 집합을 막는다** — "어디서도 일어나지 않는 일" 은
적을 수 없고, 자리를 모르는 것은 `None` 이 이미 뜻한다.

### 6-2. 목적지를 정하는 자리가 하나다

```python
def movement_destination(operation) -> Zone:
    if isinstance(operation, MoveOperation):
        return operation.destination
    return DESTINATION[operation.kind]


def movement_player(operation, card) -> int:
    if isinstance(operation, MoveOperation):
        return card.owner if operation.to_owner else card.controller
    return destination_player(operation.kind, card)
```

전에는 같은 조건식이 **계획과 적용 두 곳**에 따로 있었다. 한쪽만 고치는
날이 오면 계획이 통과시킨 이동이 다른 자리로 간다. AST 로 못박았다 —
`_apply_card_movement` 안에 `DESTINATION[` 가 **없다**.

### 6-3. 계획 단계의 거절 둘

```python
def _movement_refusal(self, operation, card, instance):
    destination = movement_destination(operation)
    if destination in MAIN_DECK_ONLY_ZONES:
        extra = self._is_extra_deck(card)
        if extra is not False:          # True 와 None 을 함께 막는다
            return _fail(UNSUPPORTED_OPERATION, RULE_NOT_IMPLEMENTED, ...,
                         missing=MISSING_EXTRA_DECK_DESTINATION)
    if card.zone is destination and card.controller == movement_player(...):
        return _fail(UNSUPPORTED_OPERATION, RULE_NOT_IMPLEMENTED, ...,
                     missing=MISSING_SAME_ZONE_MOVEMENT)
    return None
```

🔴 `extra is not False` 가 요점이다. 카드 정의를 읽을 수 없으면 `None`
이고, 그것을 **"메인 덱 카드다" 로 읽지 않는다** (§3-10).

---

## 7. 출발 영역과 도착 영역의 판정 방식

계획 단계가 **네 관문을 순서대로** 지난다. 순서가 의미를 갖는다 — 더 강한
말을 먼저 한다.

| 순서 | 관문 | 어긋나면 | 상태 / 코드 | `missing` |
|---|---|---|---|---|
| 1 | `state.find_instance` | 판에 없다 | `INVALID_TARGET` / `CANDIDATE_NOT_FOUND` | 없음 |
| 2 | `ORIGIN_RULES[kind]` | 전역 자리 규칙 | `known` → `INVALID_TARGET`/`SOURCE_WRONG_ZONE`, 아니면 `UNSUPPORTED_OPERATION`/`RULE_NOT_IMPLEMENTED` | 표가 적은 것 |
| 3 | **`operation.origin_zones`** | 이 효과가 적은 자리 | `INVALID_TARGET` / `SOURCE_WRONG_ZONE` | **없음** (아는 규칙) |
| 4 | **`_movement_refusal`** | 도착 자리가 불가능 · 옮길 것이 없음 | `UNSUPPORTED_OPERATION` / `RULE_NOT_IMPLEMENTED` | 두 이름 중 하나 |
| 5 | `_check_rule_gate` | 카드가 선언한 관문 | `UNCHECKED_RULES` 등 | 관문 이름 |

실측으로 확인한 순서의 결과 — 어니스트 ① 이 `HAND` 에 있을 때:

| 정의 | 결과 | 이유 |
|---|---|---|
| 자리를 적지 않은 시험용 조작 | `UNSUPPORTED_OPERATION` / `RULE_NOT_IMPLEMENTED` | 옮길 것이 없다 (4번) |
| **등재된** 어니스트 ① | `INVALID_TARGET` / `SOURCE_WRONG_ZONE` | 필드가 아니다 (3번, 더 먼저) |

3번이 4번보다 먼저인 것이 맞다. 공식 텍스트가 「필드의」 라고 적었으므로
그것은 **아는 규칙**이고, "옮길 것이 없다" 보다 강한 말이다.

---

## 8. 카드 종류별 이동 지원 및 미지원 범위

| 카드 종류 | `HAND` · `DECK` 로 | `GRAVE` · `REMOVED` 로 | 근거 |
|---|---|---|---|
| 메인 덱 몬스터 | 🟢 **지원** | 🟢 지원 | 실측 (어니스트 · 페더맨) |
| 마법 · 함정 | 🟢 지원 | 🟢 지원 | 기존 등재 효과 14건이 그대로 통과 |
| **펜듈럼** (메인 덱) | 🟢 **지원** | 🟡 **미지원 보존** | 패로 되돌리는 것은 보통의 일이다. 필드 → 묘지의 엑스트라 덱 우회는 룰북에 있으나 **옮기지 않았다** (§16-2) |
| **엑스트라 덱 몬스터** | 🔴 **미지원 (거절)** | 🟢 지원 | 룰북이 패 · 덱으로 가는 길을 말하지 않는다 (§4-2) |
| **토큰** | ⚫ **도달 불가** | ⚫ 도달 불가 | 저장소가 싣지 않는다 (§4-3) |
| 정의를 읽을 수 없는 카드 | 🔴 **미지원 (거절)** | 🟢 지원 | 모르는 것을 메인 덱으로 읽지 않는다 |

🔴 **막는 것은 패 · 메인 덱뿐이다.** 융합 몬스터가 묘지로 가고 제외되는
것은 룰북이 말하는 보통의 일이므로 6-M 이 건드리지 않았다. 카드 종류로
**모든** 이동을 막으면 그것이 새 결함이다 (테스트가 센다).

---

## 9. 비용 이동과 효과 해결 이동의 구분

§8 의 다섯 질문에 코드와 측정으로 답한다.

| 질문 | 답 |
|---|---|
| 1. 비용은 적절한 발동 절차에서 처리되는가? | 🟢 `EffectActivator.activate` 가 `self._payer.pay(...)` 를 부른다. 실행기 소스에 `CostPayer` · `_payer` · `CostSemantics` · `COST_OPERATION` 이 **하나도 없다** (AST 로 센다) |
| 2. 해결 단계의 이동을 비용으로 잘못 기록하지 않는가? | 🟢 `ZoneMoved.movement` 가 그 효과의 `OperationKind` 를 싣는다. 실측: 어니스트 ① 의 델타는 `RETURN_TO_HAND` 이고 `COST_OPERATION` 의 값(둘) 중 어느 것도 아니다 |
| 3. 이동 원인에 따라 제한이 달라지는가? | 🟢 달라진다. 공식 Lua 가 `IsAbleToHand` 와 `IsAbleToHandAsCost` 를 **다른 술어**로 쓰고, `LUA_GATE_PREDICATES` 가 앞의 것만 싣는다 ("`*AsCost` 변종은 여기 없다 — 비용 계층의 질문이고 효과의 질문과 다르다") |
| 4. 비용 실패를 발동으로 잘못 처리하지 않는가? | 🟢 `PaymentStatus.PAID` 하나만 판을 바꾼다. 나머지는 전부 "아무것도 내지 않았다" 다 |
| 5. 해결 실패 때 비용을 임의로 되돌리지 않는가? | 🟢 되돌리지 않는다 (ADR-008: 롤백이 없다). 그래서 거절을 **계획 단계에서만** 한다 — 6-M 의 두 거절도 계획 단계다 (AST 로 센다) |

### 🔴 비용 경로는 **등재된 효과에서 도달하지 않는다**

| 측정 | 값 |
|---|---|
| 등재 효과 중 비용이 있는 것 | **0건** |
| 비용이 옮길 수 있는 일 | `DISCARD` · `RELEASE` 둘 |
| 그 둘의 목적지 | 둘 다 `GRAVE` |

목적지가 `MAIN_DECK_ONLY_ZONES` 와 겹치지 않으므로 6-M 의 도착 자리
거절은 **비용 경로의 동작을 바꾸지 않는다.** 그래서
`engine/payment.py` 를 고치지 않았고, 남은 공백은 §16-3 에 적었다.

---

## 10. 실제 카드 이동 전후 `GameState` 비교

어니스트 ① · 실제 `Duel` · `settle_chain`.

| 시점 | `#40` 의 자리 | 내 패 | `MZONE` | `state_hash` |
|---|---|---|---|---|
| 발동 전 | `MZONE` | 0장 | 1장 | H₀ |
| 발동 직후 (체인 1, 응답 창 열림) | `MZONE` | 0장 | 1장 | H₀ |
| 해결 후 | **`HAND`** | **1장** | **0장** | H₁ ≠ H₀ |

거절되는 경우 (`GRAVE` 에 있는 어니스트 ①):

| 시점 | 자리 | `state_hash` | journal |
|---|---|---|---|
| 실행 전 | `GRAVE` | H₀ | 0건 |
| 거절 후 | `GRAVE` | **H₀ (같다)** | **0건** |

🔴 `state_hash()` 가 같다는 것이 "카드 위치가 같다" 보다 센 단언이다 —
다른 칸이 조용히 바뀌는 것까지 잡는다 (§11-1).

---

## 11. `EventJournal` 기록 검증 결과

| 사례 | 기록 |
|---|---|
| 어니스트 ① 해결 | 1건 — `#40 P0/MZONE → P0/HAND (return_to_hand)`, `effect_ref=37742478:e[0]`, `source=#40` |
| 필드 밖에서 거절 | **0건** |
| 엑스트라 덱 몬스터 거절 | **0건** |
| 이미 패에 있어 거절 | **0건** (구현 전에는 `P0/HAND → P0/HAND` 가 **1건** 적혔다) |
| 가려진 카드라 판정 불가 | **0건** |

§11-5 를 위반하던 자리가 닫혔다. 기록 의미론은 바뀌지 않았다 (§3-13) —
`ZoneMoved` 의 칸도 `movement` 의 뜻도 그대로다.

---

## 12. 어니스트 효과 회귀 결과

6-L 이 확보한 경로가 **그대로 간다.**

| 확인 | 결과 |
|---|---|
| `legal_actions` 후보 | 1건, `ACTIVATE_EFFECT`, `effect_ref=37742478:e[0]`, `targets=()` |
| `apply` | `accepted`, 체인 링크 1, 응답 창 열림 |
| 발동 직후 카드 위치 | `MZONE` (아직 안 움직인다) |
| `settle_chain` 후 | **`HAND`**, 내 패 +1장 |
| `EventJournal` | 1건, `movement=RETURN_TO_HAND`, `MZONE → HAND` |
| 잘못된 대상 선택 방지 | 같은 카드 셋 중 **발동한 쪽만** 움직인다 (`[MZONE, HAND, MZONE]`) |

🔴 그리고 **새로 거절된다** — 어니스트 ① 이 `GRAVE` · `REMOVED` · `DECK` ·
`HAND` · `EXTRA` 에 있으면 `INVALID_TARGET` / `SOURCE_WRONG_ZONE` 이고,
판도 journal 도 그대로다. 6-L §16-1 이 "그 길이 생기는 날 반드시 틀린다"
고 적은 자리가 닫혔다.

---

## 13. 기존 효과 실행 범위의 전후 비교

🔴 **지원 범위는 넓어지지 않았다.** §12 의 열 항목을 그대로 적는다.

| # | 지표 | 전 (6-L) | 후 (6-M) |
|---|---|---|---|
| 1 | `RETURN_TO_HAND` 가 허용하는 출발 자리 (전역) | 열 자리 전부 (제약 없음) | **열 자리 전부 (제약 없음 · 그대로)** |
| 1' | 같은 것, **등재된 어니스트 ①** | 열 자리 전부 | **필드 다섯 자리** |
| 2 | 기존에 잘못 **차단**되던 이동 | **0건** | 0건 |
| 3 | 새로 정상 실행할 수 있게 된 이동 | — | **0건** |
| 4 | 출발 자리를 적은 등재 조작 | 0건 | **1건** (어니스트 ①) |
| 5 | 아직 `UNKNOWN` · 미지원으로 남는 이동 | (아래) | 네 가지 (§16) |
| 6 | **잘못 허용되던** 이동 | 엑스트라 덱 → 패 · 덱, 필드 밖 어니스트, 같은 자리 이동 | **0건** (셋 다 거절) |
| 7 | 실제 `GameState` 변경 검증 사례 | 어니스트 ① | 어니스트 ① (유지) + 페더맨 · 펜듈럼 · 소유권 이전 |
| 8 | 어니스트 효과 회귀 | 통과 | **통과** (§12) |
| 9 | `EventJournal` 기록 일관성 | `HAND → HAND` 가 성공으로 **1건** 적혔다 | **0건** (§11) |
| 10 | 새로운 구조적 차단 요인 | — | §16 에 넷 |
| — | 등재 효과 / 실행 가능 | 17 / **14** | 17 / **14 (같다)** |

**정확성만 개선됐다.** §12 가 "지원 기능이 증가하지 않고 정확성만 개선됐다면
그 사실을 그대로 보고한다" 고 했고, 그것이 이 Phase 의 결과다.

표본 범위 (§12 "전수 검증을 수행하지 않았다면 표본 및 검사 범위를
명시한다"):

- **이동 실행 측정**: 등재된 효과 17건 전수 + 손으로 만든 조작 조합. 자리는
  엔진이 가진 **열 자리 전수**.
- **카드 종류 측정**: 메인 덱 몬스터 2장 (어니스트 · 페더맨) · 융합 1장
  (궁극의 푸른 눈의 백룡) · 싱크로 1장 (암흑차원의 전사) · 펜듈럼 1장
  (오드아이즈 펜듈럼 드래곤) · 마법 1장 (욕망의 항아리). **표본이고 전수가
  아니다.**
- **코퍼스 측정**: `c*.lua` 12,702개 전수. **정적 분석이고 실행 수치가
  아니다.**

---

## 14. 추가한 타깃 및 통합 테스트 결과

### 14-1. 새 파일 — `tests/engine/test_card_movement_origin.py` (63개)

| 절 | 무엇 | 개수 |
|---|---|---|
| A | `ORIGIN_RULES` 의 실제 구조 · 구현 전 측정 · 코퍼스 근거 | 13 |
| B | 이 효과가 적은 출발 자리 (양방향 · 검증 · 정규 표현) | 16 |
| C | 어니스트 ① 의 근거와 회귀 | 3 |
| D | 도착 자리와 주인을 정하는 자리가 하나 | 4 |
| E | 엑스트라 덱 몬스터 · 펜듈럼 · 남은 공백 | 10 |
| F | 일어나지 않은 이동 · 가려진 카드 | 7 |
| G | 거절은 계획 단계에서만 (AST) | 2 |
| H | 비용과 효과 해결의 구분 | 4 |
| I | 상태 · 기록 일관성 (`state_hash` 포함) | 3 |
| J | 토큰 — 도달 불가를 수치로 | 1 |

### 14-2. 움직인 기존 테스트 — **넷** (모두 이유를 적었다)

**지운 테스트도, 추가한 skip 도, 약화한 단언도, 완화한 threshold 도 없다.**

| 테스트 | 왜 움직였나 |
|---|---|
| `test_self_reference_target.py::test_e03` | 6-L 이 **현재 동작을 사실로** 적어 둔 핀이다 ("바람직하다는 뜻이 아니다"). 6-M 이 그 공백의 일부를 닫았으므로 **두 축을 갈라서** 다시 적었다 — 전역 표는 그대로 비어 있고, 등재된 어니스트 ① 은 거절되고, `HAND` 는 둘 다 거절하되 **이유가 다르다** |
| `test_random_selection.py::test_a_every_zone_can_be_a_candidate_source` | 여섯 경우가 전부 `send_to_grave` 였다. 묘지에서 고른 카드를 묘지로 보내는 것은 **아무 일도 없는 이동**이고, 이 시험이 재는 것은 **후보 자리**였다. 묘지 두 경우만 제외(실제로 일어나는 이동)로 바꾸고 출발 자리를 델타로 확인한다 |
| `test_random_selection.py::test_i_the_selected_card_flows_into_an_existing_operation` | 셋 다 상대 **패**에서 골랐다. 패에서 고른 카드를 패로 되돌리는 것은 같은 이유로 아무 일도 없다. 패 되돌림만 상대 **필드**에서 고른다 — "어느 일이든 같은 선택 결과를 받는가" 는 그대로 센다 |
| `test_card_movement_origin.py::test_e06` (같은 Phase 안에서) | 처음에 "정의를 읽을 수 없으면 거절한다" 로 썼다가, 그 선택이 기존 단위 시험 **열한 개**를 깨뜨리는 것을 실측하고 **공백을 남기는 쪽으로 바꿨다.** 그 사실과 이유를 시험 자신이 적는다 (§16-4) |

🔴 **새로 더한 핀 하나**: `test_random_selection.py::
test_a_a_move_that_changes_nothing_is_refused`. 위에서 뺀 사실(묘지 → 묘지가
거절된다)을 잃지 않으려고 따로 센다.

### 14-3. Mutation 테스트 — 6-M 프로덕션 코드에 고의 결함 14개

**내가 쓴 코드만** 대상으로 했다. `git checkout` 을 쓰지 않았고, 원본을
메모리에 들고 있다가 되돌리고 `assert` 로 확인했다
(`scratchpad/mutate4.py`). 판정 테스트는 새 파일 + 6-L 의 자기 참조 파일
이고, **pytest 의 실제 종료 코드**로 판정했다.

| # | 고의 결함 | 결과 |
|---|---|---|
| P1 | 이 효과가 적은 출발 자리를 보지 않는다 | killed (10 failed) |
| P2 | 출발 자리를 "아는 규칙" 이 아니라 "모른다" 로 거절한다 | killed (10) |
| P3 | 도착 자리 거절을 아예 부르지 않는다 | killed (8) |
| P4 | 엑스트라 덱 몬스터를 메인 덱 카드처럼 옮긴다 | killed (2) |
| P5 | 막는 자리를 패·덱이 아니라 묘지·제외로 바꾼다 | killed (5) |
| P6 | 카드 종류를 읽지 못하면 메인 덱 카드로 읽는다 | killed (1) |
| P7 | 일어나지 않은 이동을 거절하지 않는다 | killed (6) |
| P8 | 자리만 보고 주인을 보지 않는다 | killed (2) |
| P9 | 어니스트 ① 이 출발 자리를 적지 않는다 | killed (7) |
| P10 | 어니스트 ① 의 출발 자리를 필드가 아니라 묘지로 적는다 | killed (13) |
| P11 | 빈 출발 자리를 받아 준다 | killed (1) |
| P12 | 출발 자리를 정규 표현에서 뺀다 | killed (1) |
| P13 | 적용 단계가 계획과 다른 목적지를 쓴다 | killed (35) |
| P14 | `MOVE` 의 주인 규칙을 뒤집는다 | killed (1) |

**14개 중 14개 killed, 생존 0.**

🔴 P6 이 killed 인 것이 §16-4 와 어긋나 보이지만 아니다. P6 은
`_is_extra_deck` 가 ``None`` 대신 ``False`` 를 **돌려주게** 바꾼 것이고,
`test_e06` 이 그 세 값 구분을 직접 센다. 공백은 **부르는 쪽이 `None` 을
막지 않는다**는 것이고, 그것은 `test_e06` 이 사실대로 적어 둔 상태다.

---

## 15. 엔진 회귀 테스트 결과

§13 의 4단계 정책을 그대로 따랐고, **pytest 의 실제 종료 코드**를 읽었다
(`tail` 이나 `grep` 의 종료 코드가 아니다).

| 단계 | 명령 | 통과 | 실패 | 건너뜀 | 시간 | 종료 코드 |
|---|---|---|---|---|---|---|
| 1 타깃 | `pytest tests/engine/test_card_movement_origin.py -q -p no:randomly` | 63 | 0 | 0 | 4.2s | `0` |
| 2 통합 (자기 참조 회귀) | `pytest tests/engine/test_self_reference_target.py -q -p no:randomly` | 42 | 0 | 0 | 5.7s | `0` |
| 3 엔진 (1차) | `pytest tests/engine -q -p no:randomly` | 3,223 | **11** | 0 | 6:05 | `1` |
| 3 엔진 (2차) | 같음 | 3,234 | **1** | 0 | 6:40 | `1` |
| 3 엔진 (최종) | 같음 | **3,236** | **0** | **0** | 6:46 | **`0`** |
| 4 관련 루트 | `pytest <52 files> -q -p no:randomly` | §18 | | | | |

### 🔴 1차 · 2차의 실패를 숨기지 않는다

**1차 11건** — 전부 같은 원인이었다. 엑스트라 덱 거절을 처음에
`_is_extra_deck(card) is not False` 로 썼고, 그러면 **카드 정의를 읽을 수
없는 판**도 막힌다. 합성 카드 ID (`1000` · `1500`)로 실행기 기계를 재는
기존 단위 시험 열한 개가 거기 걸렸다.

그 열한 개의 전제("정의를 읽을 수 없는 카드를 패로 옮길 수 있다")가
**옳지는 않다.** 그런데 고치려면 그 파일들의 판 구성을 실제 카드로 바꿔야
하고, 그것은 §3-1 · §14 가 금지한 범위다. 그래서 **거절 조건을
`is True` 로 좁히고 공백을 §16-4 에 적었다** — 테스트를 고쳐 통과시킨 것이
아니라, 범위를 넘는 변경을 피하고 그 대가를 기록했다.

**2차 1건** — 내가 1차 전에 써 둔 `test_e06` 이 "정의를 읽을 수 없으면
거절한다" 를 단언하고 있었다. 위 결정과 어긋나므로 **시험을 사실에 맞게
다시 썼다** (`test_e06_an_unreadable_definition_is_a_measured_hole_not_a_refusal`)
— 지금은 통과한다는 사실과 왜 그렇게 두었는지를 시험 자신이 적는다.

**3차 3건** (그 사이에 따로 돌린 네 파일 회귀) — `test_random_selection.py`
의 "아무 일도 없는 이동" 세 경우. §14-2 에 이유를 적었다.

---

## 16. 새로 발견한 구조적 차단 요인

### 16-1. 「앞면 표시의」 를 옮기지 못했다 — **표시 형식 축이 없다**

어니스트 ① 의 공식 텍스트는 「필드의 **앞면 표시의** 이 카드를」 이고,
6-M 은 「필드의」 만 옮겼다. `CardOperation` 에 표시 형식을 적는 칸이
없다.

- **위치**: `engine/effect/operation.py` (`CardOperation`),
  `engine/effect/executor.py` (`_plan_card_operation`)
- **영향**: 지금은 닿지 않는다 — 발동 범위가 앞면 몬스터 존으로 좁혀져
  있고 (Phase 6-K), 발동과 해결 사이에 그 카드를 뒤집는 효과가 이 엔진에
  하나도 없다. 그 길이 생기면 뒷면 카드가 패로 돌아간다.
- **최소 수정안**: `origin_zones` 와 **같은 모양**의 칸 하나
  (`origin_face_up: bool | None = None`). 같은 자리에서 `card.is_faceup`
  과 비교한다. `CardInstance.is_faceup` 이 이미 있다.

### 16-2. 펜듈럼이 필드에서 묘지로 갈 때의 엑스트라 덱 우회

🔴 **이것은 룰북이 말한다** — 유일하게 근거가 이미 있는 미구현 규칙이다.

> "Pendulum Monster Cards that would be sent from the field to the
> Graveyard are placed face-up here" (`sd-rulebook-en-v10.json`, Extra Deck)

- **위치**: `DESTINATION[SEND_TO_GRAVE]` · `DESTINATION[DESTROY]` 가
  무조건 `Zone.GRAVE` 다. 카드 종류를 보지 않는다.
- **영향**: 지금은 **닿지 않는다**. 등재된 효과 중 필드에서 묘지로 보내는
  것이 없고 (어리석은 매장은 덱을 대상으로 한다), 파괴는 판정기가 없어
  어떤 파괴도 일어나지 않는다 (`UnknownDestructionRuling`).
- **6-M 이 고치지 않은 이유**: `RETURN_TO_HAND` 가 아니고 (§1 의 범위),
  `MOVABLE_DESTINATIONS` 에 `Zone.EXTRA` 가 없어 **도착 자리를 더하는
  일**이 따라온다. 닿지 않는 경로에 도착 자리를 더하면 회귀로 검증할 수
  없다.
- **최소 수정안**: `MOVABLE_DESTINATIONS` 에 `Zone.EXTRA` 를 더하고,
  `_movement_refusal` 과 같은 자리에서 "필드 → 묘지 · 펜듈럼" 을
  `Zone.EXTRA` 로 **돌린다** (거절이 아니라 우회다 — 근거가 있으므로).

### 16-3. 비용 경로에는 같은 두 검사가 **없다**

- **위치**: `engine/payment.py` 의 `CostPayer._preflight` · `_apply`. 그쪽은
  `DESTINATION[operation]` 를 직접 읽고 `_movement_refusal` 을 부르지
  않는다.
- **영향**: 지금은 **닿지 않는다**. 등재된 효과 중 비용이 있는 것이
  **0건**이고, 비용이 옮길 수 있는 둘(`DISCARD` · `RELEASE`)의 목적지는
  둘 다 묘지라서 `MAIN_DECK_ONLY_ZONES` 와 겹치지 않는다. 다만 묘지에
  있는 카드를 릴리스하는 "아무 일도 없는 이동" 은 그쪽에서 막히지
  않는다 (`RELEASE` 에는 `ORIGIN_RULES` 항목이 없다).
- **6-M 이 고치지 않은 이유**: 비용 계층은 **다른 모듈**이고, 공통 함수를
  꺼내 양쪽에서 부르게 하면 두 계층의 경계를 손대는 일이 된다 (§3-6
  "효과에 의한 이동과 비용에 의한 이동을 구분한다"). 도달하지 않는 경로를
  위해 경계를 흐리지 않는다.
- **최소 수정안**: `movement_destination` 과 같은 자리에 "일어나지 않는
  이동" 판정을 **순수 함수**로 꺼내고, `CostPayer._preflight` 가 그것을
  부른다. 실행기의 거절 **상태**는 가져가지 않는다 — 비용의 거절은
  `PaymentStatus` 다.

### 16-4. 🔴 카드 정의를 읽을 수 없으면 **모르는 것이 통과한다**

- **위치**: `EffectExecutor._movement_refusal` 의
  `self._is_extra_deck(card) is True`.
- **사실**: `_is_extra_deck` 는 세 값을 돌려주는데 (`True` · `False` ·
  `None`), 부르는 쪽이 `True` 만 막는다. 즉 **`None` 이 허가로 쓰인다** —
  이 저장소의 삼값 규율을 이 한 자리에서 지키지 못했다.
- **왜 그렇게 두었는가 (측정)**: 저장소가 연결되지 않은 `GameState` 는
  시험용 구성이고, 그 자리를 막으면 합성 카드 ID 로 실행기 기계를 재는
  기존 단위 시험 **열한 개**가 깨진다 (실측). 그 덱은 `1000` · `1500` 같은
  합성 ID 라서 저장소를 연결해도 정의를 얻을 수 없다 — 고치려면 그
  파일들의 판 구성을 실제 카드로 바꿔야 하고, 그것은 §3-1 · §14 가 금지한
  범위의 변경이다.
- **영향**: production 의 듀얼 경로는 언제나 저장소를 건넨 `GameState` 를
  쓰므로 **닿지 않는다.** 그 사실을 `test_e07` 이 센다.
- **최소 수정안** (승인 대기): (1) 그 열한 시험의 판 구성을 실제 카드로
  바꾸거나, (2) `GameState` 가 저장소 없이 만들어졌음을 **값으로** 들고
  있게 하고 실행기가 "정의를 읽을 수 없는 판" 과 "정의를 읽을 수 없는
  카드" 를 구분하게 한다. 둘 다 공유 모델 변경이므로 §3-16 에 따라
  보고만 한다.

### 16-5. 수정하지 않은 것 (§14)

효과 사용 횟수 제한 · 소환 조건 · TRIGGER 자동 발동 · 콤보 플래너 ·
체인/우선권 개편 · 덱 빌더 · Discord 명령어 · 금지 제한 리스트 ·
Duel Simulator · EDOPro 연동 — **하나도 건드리지 않았다.**

---

## 17. 다음 단계에서 가장 먼저 해결할 최소 작업

**§16-1 (표시 형식 축)** 을 권한다.

- 가장 작다 — `origin_zones` 와 **같은 모양**의 칸 하나이고, 읽을 값
  (`CardInstance.is_faceup`)이 이미 있다.
- 가장 근거가 분명하다 — 어니스트 ① 의 공식 텍스트가 직접 말하고, 공식
  Lua 가 `c:IsFaceup()` 으로 적는다.
- 6-M 이 만든 자리를 그대로 쓴다 — `_movement_refusal` 바로 앞에 같은
  모양의 검사 한 줄이 들어간다.

그다음은 **§16-2 (펜듈럼 우회)** 다. 근거가 룰북에 있으므로 지어낼 것이
없고, `Zone.EXTRA` 를 `MOVABLE_DESTINATIONS` 에 더하는 일이 §16 전체에서
가장 많은 카드에 영향을 준다.

**§16-4** 는 공유 모델 변경이므로 **사용자 승인을 기다린다** (§3-16).

🔴 **이 Phase 는 위 셋 중 아무것도 진행하지 않았다.**

---

## 18. Git 커밋 및 푸시 결과

브랜치 `claude/pensive-goodall-te1egy`. 시작 HEAD `42b5362` (6-L 의 마지막).
**기존 커밋을 rewrite 하거나 amend 하지 않았고, force push 하지 않았다.**
새 브랜치도 PR 도 만들지 않았다.

| 커밋 | 무엇 |
|---|---|
| `027d6b6` | production 4파일 (+259 −21) |
| `4f13655` | 테스트 — 새 파일 1 (63개) + 움직인 기존 테스트 2파일 |
| (이 커밋) | 보고서 |

푸시: `42b5362..4f13655` (`git push -u origin claude/pensive-goodall-te1egy`).
재시도가 필요한 네트워크 오류는 없었다.

### 🔴 관련 루트 회귀는 이 커밋 시점에 **아직 돌고 있다**

52파일이고 1차 10% 지점이다. 끝나는 대로 결과를 §15 의 표와 이 절에 적고
**별도 커밋**으로 올린다 — **숫자를 예측해서 적지 않는다.**

### 저장소 전체 테스트를 돌리지 않은 이유

§13 이 "릴리즈 수준 또는 광범위한 공유 계약 변경이 있는 경우에만 저장소
전체 회귀를 수행한다. 불필요하게 동일한 대규모 테스트를 반복하지 않는다"
고 적었다. 6-L 이 직전에 전체 범위(엔진 3,172 + 관련 루트 1,573)를
돌렸고, 6-M 이 건드린 공유 계약은 `CardOperation` · `EffectExecutor` ·
`semantics` · `EffectLibrary` 넷이다. 그 넷을 이름으로 읽는 루트 테스트를
전수 검색해서 52개를 얻었고 (`CardOperation|ORIGIN_RULES|origin_rule|
DESTINATION|destination_player|OperationKind|effect/executor|
effect/semantics|effect/operation|EFFECT_LIBRARY|MovementRuling|ZoneMoved`),
그 집합과 `tests/engine` 전체를 돌렸다.

---

**다음 Phase 는 자동으로 시작하지 않는다. 사용자 검토를 기다린다.**
