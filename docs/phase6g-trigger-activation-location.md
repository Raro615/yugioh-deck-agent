# Phase 6-G — 갈라테아 카드 효과 발동 위치 분석 및 검증 계층 연결

작업 브랜치: `claude/pensive-goodall-te1egy`
선행: 6-A(실행 경로) · 6-B(EventJournal) · 6-C(아키타입) · 6-D(카드군 컴파일러) ·
6-E(TRIGGER 컴파일러) · 6-F(사건 주체)

---

## 0. 가장 먼저 — 이 Phase 의 중심 발견

**`SetRange()` 는 "발동 위치" 가 아니다. "등록 범위" 다.**

두 사실이 **대부분 같지만 항상 같지는 않다.** 카드 **자신**이 그 사건으로
움직이면 갈라진다. 그리고 그 증거가 추측이 아니라 **corpus 안의 Lua** 에
있다 — 드로우 개구리(56840658)::

```lua
e2:SetType(EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O)
e2:SetRange(LOCATION_MZONE)          -- 등록 범위
e2:SetCode(EVENT_TO_GRAVE)           -- 묘지로 갈 때
e2:SetCondition(s.condition)
-- s.condition:  c:IsPreviousLocation(LOCATION_ONFIELD)
```

🔴 **스크립트 자신이 `IsPreviousLocation` 을 쓴다.** 발동하는 순간 그 카드는
**묘지**에 있고 `LOCATION_MZONE` 은 효과가 등록되어 있던 자리다. 공식 원문도
같은 말을 한다 — 「**필드의 앞면 표시의** 이 카드가 **묘지로 보내졌을 때**에
발동할 수 있다」.

6-E 는 그 범위를 `activates_from`(= 지금 어디 있어야 하는가) 에 넣었다. 그래서
자리 관문이 **확정 거부**를 냈다. 실제 판에서 재현한 출력:

```
후보 56840658:e[0] source=#40          ← 실제로 묘지로 옮긴 그 카드
  EVENT_RELATION     = valid/ok         ← 6-F 의 주체 판정은 통과한다
  🔴 ACTIVATION_ZONE = invalid/source_wrong_zone
     "GRAVE 는 발동할 수 있는 자리가 아닙니다 (MZONE)."
  판정기             = ineligible
```

효과는 실제로 발동한다. **`UNKNOWN` 이 아니라 잘못된 확신**이라서 더 나쁘다.

---

## 1. 기존 `activates_from` 데이터 생성 및 전달 경로

```
c*.lua  e2:SetRange(LOCATION_MZONE)
   ↓  sources/lua_loader.py  _write_list(..., "ranges", _RE_LOCATION, args)
EffectSpec.ranges = ["MZONE"]          ← LOCATION_(\w+) 의 캡처 그룹
   ↓  analysis/effect_analyzer.py      (effect.raw.ranges 로 그대로 통과)
   ↓  engine/trigger_compiler.py       _zones_from(ranges)
TriggerSpec.activates_from = frozenset({Zone.MZONE})
   ↓  engine/trigger.py                TriggerEligibilityJudge._activation_zone
view.find(candidate.source).zone in spec.activates_from  →  VALID / INVALID
```

| 질문 (§4-A) | 답 |
|---|---|
| 1. 타입 | `frozenset[Zone] | None` |
| 2. 생성 위치 | `engine/trigger_compiler.py` 의 `_zones_from` **한 곳** |
| 3. `SetRange` 분석 | ✅ 파서가 `LOCATION_(\w+)` 를 뽑아 `EffectSpec.ranges` 에 넣는다 |
| 4. 없을 때 의미 | `None` → 자리 관문이 `UNKNOWN`. *"적지 않은 것을 '어디서든 발동 가능' 으로 읽지 않는다"* |
| 5. 비트 조합 해석 | 🔴 **비트가 아니라 이름**으로 온다. 파서가 상수 이름을 캡처하므로 `LOCATION_HAND+LOCATION_GRAVE` 는 `["HAND","GRAVE"]` 두 이름이 된다 |
| 6. 효과 종류별 기본 영역 | ❌ 없다. 기본값을 넣는 코드가 **어디에도 없다** (§6 오류 D 를 구조적으로 피한다) |
| 7. 816건의 근거 | 전부 `SetRange` 뿐이다. 다른 출처는 없다 |
| 8. 잘못된 사례 | 🔴 **1건** (§3) |

---

## 2. Lua 효과 등록 정보와 실제 발동 위치의 관계

### 🔴 두 축이 거의 **상보적**이다 (전수 측정)

|  | 위치 선언됨 | 위치 없음 |
|---|---|---|
| **주체 `SELF`** (= `SINGLE` 등록) | **32** | **3,357** |
| **주체 미선언** (= `FIELD` 등록) | **784** | **0** |

* `FIELD` 등록은 **100%** `SetRange` 를 선언한다 — 어디를 지켜보는지 적지
  않으면 효과가 성립하지 않으므로 **적어야 한다.**
* `SINGLE` 등록은 **0.9%** 만 적는다 (32/3,389) — 핸들러가 곧 주체이므로
  대부분 범위가 필요 없다.

🔴 **그래서 두 관문(주체 · 위치) 을 **모두** 통과할 수 있는 등록은 32건뿐이다**
(6-G 뒤 31건). 위치 축을 넓혀도 발동 가능이 늘지 않는 이유가 이것이고, §17
의 "지원 비율과 실제 실행 가능 비율을 구분한다" 가 가리키는 바로 그 사실이다.

### `FIELD` 범위는 발동 위치다 — 원문이 직접 말한다

| 카드 | 공식 원문 | `activates_from` |
|---|---|---|
| 숲의 파수꾼 그린 바분 46668237 | 「①: **이 카드가 패 / 묘지에 존재하고**, …」 | `{GRAVE, HAND}` |
| 환롱룡화－패파 56499179 `e[1]` | 「②: **이 카드가 제외 상태이고**, …」 | `{REMOVED}` |
| 이계의 극자룡 25206027 | 「… 이 카드를 **패에서** 특수 소환할 수 있다」 | `{HAND}` |
| 다크 버저 50164989 | 「… 이 카드를 **묘지에서** 특수 소환할 수 있다」 | `{GRAVE}` |

### 🔴 "어긋나 보이는" 174건은 어긋난 것이 아니다

등록 범위에 사건의 도착지가 없는 사례를 세면 **174건**인데, 읽어 보니 전부
`FIELD` 이고 **범위는 이 카드의 자리, 도착지는 다른 카드의 자리**다.

> 에스프릿 힐링 276357 `e[2]` — 「①: **이 카드가 마법 & 함정 존에 존재하고**,
> 자신 필드 앞면 표시의 스피릿 몬스터가 **자신의 패로 되돌아갔을 경우**」
> → 범위 `SZONE` = 이 카드 / 도착지 `HAND` = 그 몬스터

지시서 §3-7 이 요구한 구분이 바로 이것이고, 그래서 6-G 의 변환은 **주체가
`SELF` 일 때만** 적용된다.

---

## 3. 기존 816건 발동 위치 선언의 정확성 조사

| 구분 | 수 | 판정 |
|---|---|---|
| `FIELD` 등록 (주체 미선언) | 784 | ✅ 범위 = 이 카드의 자리 = 발동 위치 |
| `SELF` · `EVENT_DRAW` · `HAND` | 8 | ✅ 뽑힌 카드는 패에 있다 |
| `SELF` · 소환 성공 · `MZONE` | 20 | ✅ 소환된 카드는 필드에 있다 |
| `SELF` · `EVENT_TO_HAND` · `HAND` | 3 | ✅ 도착지 = 범위 |
| 🔴 `SELF` · `EVENT_TO_GRAVE` · `MZONE` | **1** | ❌ **틀렸다** — 범위가 이동 **전** 자리다 |

**오류율 1/816 (0.12%).** 그 1건이 드로우 개구리이고, 모양이 데이터만으로
식별된다 — 주체 `SELF` · 시점 `CARD_MOVED` · 도착지가 범위 밖.

🔴 이 숫자가 작은 이유도 §2 의 상보성이다. `SELF` 등록 중 범위를 가진 것이
32건뿐이라서 어긋날 기회가 애초에 32번밖에 없었다.

---

## 4. 새로 확인된 발동 위치 정보의 출처

**없다.** 🔴 6-G 는 발동 위치를 **하나도 새로 추가하지 않았다.**

조사 결과가 그것을 허락하지 않았다. 컴파일되는 4,173건 중 위치 정보가 없는
3,357건은 `SetRange` 가 **실제로 없다**:

| 왜 비었나 | 수 |
|---|---|
| 스크립트가 `SetRange` 를 **아예 부르지 않는다** | 1,177 |
| 스크립트는 부르는데 **그 효과 블록에는 없다** | 2,180 |

후자가 파서 결함일까 봐 직접 읽었다 — 가가가 시스터(387282) 는 `e1`
(`TRIGGER_O`) 에 `SetRange` 가 없고 `e2`(`IGNITION`) 에 `SetRange(MZONE)` 가
있다. **파서가 정확하다.** 부재는 실재한다.

없는 것을 메우려면 "기본 발동 영역" 을 지어내야 하는데, 그것이 지시서 §6
오류 D 다. 🔴 **그래서 메우지 않았다.**

### 못 옮기는 이름도 0건이다

컴파일되는 등록의 `ranges` 에 나타나는 `LOCATION_*` 이름은 **여덟 가지뿐**이고
전부 `Zone` 멤버다.

```
MZONE 298 · SZONE 166 · HAND 155 · GRAVE 123 · FZONE 72 · PZONE 20 · REMOVED 6 · EXTRA 2
```

`LOCATION_ONFIELD` 같은 **합성 상수는 트리거 등록에 한 번도 쓰이지 않는다**
(corpus 전체에 그런 `SetRange` 를 가진 파일이 4개이고 그중 트리거는 없다).
그래서 §6 오류 C(복수 영역 손실) 가 합성 상수 경로로는 발생하지 않는다.

---

## 5. 선택한 최소 구현 방식과 대안 비교

| 설계 | 내용 | 판단 |
|---|---|---|
| A | `activates_from` 을 그대로 두고 1건을 예외 처리 | 🔴 카드별 하드코딩 (§3-5) |
| B | 새 필드 `registered_in` 을 더하고 새 관문을 만든다 | 🔴 §15 *"기존 코드로 정확하게 표현할 수 있다면 새로운 모델을 추가하지 않는다"*. 관문 추가는 감사 수십 개를 흔든다 |
| C | 그 1건의 `activates_from` 만 비운다 (`UNKNOWN`) | 거짓 음성은 사라지지만 **정보를 버린다** — 범위가 말하는 사실이 남지 않는다 |
| **D ✅** | **이미 그 뜻을 가진 기존 필드로 옮긴다** | `TriggerSpec.from_zones` = "어떤 이동에만 반응하는가" 이고 `matches` 가 `event.from_zone` 과 비교한다 |

### 채택한 것 — 새 모델 0개

```python
def _split_range(declared, *, subject, point, to_zones):
    """SetRange 하나를 (이동 전 필터, 발동 위치) 로 가른다."""
    if declared is None:
        return None, None
    if (subject is TriggerSubject.SELF            # 이 카드가 곧 사건의 주체다
            and point is TimingPoint.CARD_MOVED   # from_zones 를 걸 수 있는 유일한 시점
            and to_zones is not None
            and not (to_zones & declared)):       # 도착지가 범위 밖이다
        return declared, None                     # → 범위는 **이동 전** 자리
    return None, declared                         # → 범위가 곧 발동 위치
```

세 조건이 **모두** 맞을 때만 옮긴다. 조건마다 근거가 있다:

* **주체 `SELF`** — 그때만 사건의 도착지가 곧 "이 카드" 의 위치다. `FIELD` 에
  서는 도착지가 다른 카드의 것이다 (§2 의 174건).
* **`CARD_MOVED`** — `from_zones` 를 걸 수 있는 유일한 시점이고, 소환 시점에는
  영역 축이 금지되어 있다 (3-F-5 ②, 6-F 가 유지 확인).
* **도착지가 범위 밖** — 안이면 범위가 곧 발동 위치다 (`EVENT_TO_HAND` +
  `HAND` 3건이 그 모양이고 바뀌지 않는다).

### 🔴 왜 "카드가 간 곳" 을 발동 위치로 적지 않았나

`SELF` + `EVENT_TO_GRAVE` 면 카드는 묘지에 있으므로 `activates_from={GRAVE}`
라고 적을 수 있다. 그러면 자리 관문이 **통과**한다 — 그런데 그 통과는
**항상** 일어난다. 사건이 카드를 거기로 보냈으므로 관측의 현재 영역이 곧
도착지다.

즉 **동어반복이고, 검사한 척하는 것**이다. 지시서 §17-8 ("위치 조건만
통과했다고 전체 발동 가능으로 승격하지 않는다") 과 §11 ("잘못된 후보가
생성되지 않는 것이 우선") 에 어긋난다. 그래서 **모름으로 남겼다.**

### 🔴 이 변환은 거짓 양성을 만들 수 없다

바뀌는 방향이 **하나**다: 자리 관문의 `INVALID` → `UNKNOWN`. 동시에
`from_zones` 라는 **새 필터가 더해지므로** 반응하는 사건이 오히려 줄어든다.

```
MZONE → GRAVE 이동:  반응 1건
HAND  → GRAVE 이동:  반응 0건   ← from_zones 가 걸러낸다
DECK  → GRAVE 이동:  반응 0건
```

---

## 6. 변경 파일 및 함수

| 파일 | 변경 | 줄 |
|---|---|---|
| `engine/trigger_compiler.py` | `_split_range` (신규) · `PREVIOUS_ZONE_RULE` · `_zones_from` 전수 측정 주석 · `compile_trigger_spec` 연결 | (§18) |
| `tests/engine/test_trigger_activation_location.py` | **신규** 18개 | (§18) |

🔴 **`engine/trigger.py` 는 한 줄도 바뀌지 않았다.** 관문도 `TriggerSpec` 도
`TimingEvent` 도 그대로다 — 쓰려는 뜻을 가진 칸이 **이미 있었다.**

`data/` · `c*.lua` · `sources/` · `analysis/` · `core/` · `engine/duel.py` ·
`engine/effect/` · `engine/condition/` · `agent/` · `app/` · `rules/` ·
`rulings/` 도 전부 그대로다.

---

## 7. 새로 지원되는 위치 종류와 미지원 위치

### 지원 (실측 분포)

| 영역 | 등록 수 | 원문 근거 예 |
|---|---|---|
| `MZONE` 몬스터 존 | 297 | 레알 제넥스 마그나 「이 카드를 일반 소환했을 때」 |
| `SZONE` 마법·함정 존 | 166 | 에스프릿 힐링 「이 카드가 마법 & 함정 존에 존재하고」 |
| `HAND` 패 | 155 | 이계의 극자룡 「이 카드를 패에서 특수 소환」 |
| `GRAVE` 묘지 | 123 | 다크 버저 「이 카드를 묘지에서 특수 소환」 |
| `FZONE` 필드 존 | 72 | 아마조네스의 마을 |
| `PZONE` 펜듈럼 존 | 20 | — |
| `REMOVED` 제외 | 6 | 환롱룡화－패파 「이 카드가 제외 상태이고」 |
| `EXTRA` 엑스트라 덱 | 2 | — |

**복수 영역 26건** (전부 2개): `GRAVE+HAND` 21 · `HAND+MZONE` 2 ·
`GRAVE+MZONE` 2 · `GRAVE+SZONE` 1. 세 영역 이상은 corpus 에 없다.
`DECK` 은 트리거 등록에 **0건**이다.

### 미지원

* 🔴 **3,358건** — `SetRange` 가 없어서 모른다 (§4).
* `EMZONE` · `OVERLAY` — `Zone` 에 있지만 트리거 `SetRange` 에 0건.
* 합성 상수 (`LOCATION_ONFIELD` 등) — 트리거 등록에 0건이므로 변환을 만들지
  않았다. 쓰이면 `_zones_from` 이 **전부-아니면-없음**으로 `None` 을 돌려주고
  관문이 `UNKNOWN` 이 된다 (조용히 좁히지 않는다).

---

## 8. 현재 위치와 이전 위치를 구분한 방식

| 무엇 | 어디서 오는가 | 누가 읽는가 |
|---|---|---|
| **현재** 영역 | `GameStateView` → `CardView.zone` | `_activation_zone` 관문 ↔ `activates_from` |
| **직전** 영역 | 🔴 **사건**이 들고 있다 — `ZoneMoved.from_zone` → `TimingEvent.from_zone` | `TriggerSpec.matches` ↔ `from_zones` |

🔴 **`CardView` 를 넓히지 않았다.** `CardInstance.previous`(`PreviousState`) 가
`GameState` 에 **기록되지만** view 에는 없고 엔진의 어느 술어도 읽지 않는다
(조사 결과: `engine/` 전체에서 `previous` 를 읽는 production 코드가 0곳). 그런데
**이동 사건은 출발 영역을 이미 들고 있으므로** view 를 넓힐 필요가 없었다.

그리고 그것이 Lua 와 같은 모양이다 — 드로우 개구리의 `SetCondition` 이
`c:IsPreviousLocation(...)` 으로 묻는 것을, 엔진은 `event.from_zone` 으로 묻는다.

### 소환 사건의 직전 영역은 **의도적으로** 쓰지 않는다

`MonsterSummoned.from_zone` 은 delta 에 있지만 `TimingEvent.from_zone` 이
`None` 을 돌려준다 (`MonsterSummoned` 는 `CardMovement` 가 아니다). 그리고
`TriggerSpec` 이 소환 시점에 영역 축을 **금지**한다 (3-F-5 ②). 6-G 는 그
결정을 건드리지 않았다 — 고칠 근거가 이번 범위에 없다 (§13).

---

## 9. TRIGGER 및 조건 판정 계층 연결 결과

```
SetRange(LOCATION_MZONE)  ·  EVENT_TO_GRAVE  ·  SINGLE
   ↓ Effect Analysis Layer         (기존)
   ↓ _zones_from → _split_range    (6-G: 가른다)
TriggerSpec(from_zones={MZONE}, to_zones={GRAVE}, subject=SELF, activates_from=None)
   ↓ TriggerRegistry.watching      (기존 matches 가 from_zone 을 비교)
   ↓ TriggerCollector               (기존 · 6-F 의 주체 축)
   ↓ TriggerEligibilityJudge        (기존 관문 5개)
EVENT_RELATION=valid · ACTIVATION_ZONE=unknown · may_activate=False
```

새 관문도 새 변환 함수 호출 경로도 없다. `compile_trigger_spec` 안에서
한 번 가르고, **그 뒤는 전부 기존 계층**이다.

---

## 10. 기르수 대표 회귀 결과

기르수(69811710) 의 두 등록에는 **`SetRange` 가 없다.** 그래서:

| | 6-F | **6-G** |
|---|---|---|
| `subject` | `SELF` | `SELF` (불변) |
| `activates_from` | `None` | `None` (불변) |
| `from_zones` | `None` | `None` (불변) |
| 페더맨 소환에서 수집기 | `INELIGIBLE` / `CANDIDATE_NOT_ELIGIBLE` | **같음** |
| `may_activate` | `False` | `False` |

🔴 **한 글자도 바뀌지 않았다.** 위치 정보가 없으므로 6-G 가 더할 것이
없고, 지어내지도 않았다. 기르수 전용 분기는 production 에 **없다.**

---

## 11. 구현 전후 측정 지표 (§11 의 11항목)

| # | 지표 | 전 | 후 |
|---|---|---|---|
| 1 | TRIGGER 전체 등록 | 4,173 | **4,173** |
| 2 | 발동 위치가 선언된 등록 | 816 | **815** |
| 3 | Lua 에서 위치 정보가 확인되는 등록 | 816 | **816** |
| 4 | 🔴 새로 **정확히** 컴파일된 등록 | — | **1** (이동 전 자리로) |
| 5 | 복수 영역 등록 | 26 | **26** |
| 6 | 위치 부족으로 미확인 | 3,357 | **3,358** |
| 7 | 🔴 기존 선언 중 **잘못된** 사례 | **1** | **0** |
| 8 | 위치 불일치로 올바르게 거절된 후보 | — | 시나리오 1~4 · 8 에서 확인 |
| 9 | 위치 부족으로 보류된 후보 | — | 시나리오 9 · 10 에서 확인 |
| 10 | 사건 주체 판정 회귀 | SELF 3,389 / 미선언 784 | **동일** (전수) |
| 11 | 🔴 잘못된 `ELIGIBLE` 승격 | 0 | **0** |

🔴 **②가 줄었다는 것이 이 Phase 의 성과다.** 816 → 815 는 지원이 줄어든 것이
아니라 **틀린 선언 하나가 제자리로 갔다**는 뜻이고, ⑦이 1 → 0 이 된 것이
같은 사실의 다른 쪽이다.

**지원 비율과 실행 가능 비율은 다르다**: 위치를 아는 등록이 815/4,173
(19.5%) 이지만, 주체까지 함께 아는 등록은 **31/4,173 (0.74%)** 이고, 그
31건도 실행 권위·비용이 `UNKNOWN` 이라 **발동 가능은 0건**이다.

---

## 12. 거짓 양성 및 UNKNOWN 유지 검증

### 진리표를 전수로 돌렸다 (`test_06`)

3 주체 × 2 시점 × 3 도착지 = 18칸. 범위를 옮기는 칸은 **정확히 하나**다.

```
moved == {(SELF, CARD_MOVED, {GRAVE})}
```

그 칸의 결과는 `(declared, None)` — 즉 발동 위치가 **비고**, 관문은
`UNKNOWN` 이 된다. 나머지 17칸은 전부 `(None, declared)` 로 **6-G 이전과
같다.** 범위가 없으면 `(None, None)` 이고 지어내지 않는다.

### UNKNOWN 의 두 까닭을 가른다 (`test_10`)

| 무엇을 모르는가 | 코드 |
|---|---|
| 선언이 없다 | `RULE_NOT_IMPLEMENTED` (코드가 생겨야 풀린다) |
| 카드가 관측에 보이지 않는다 | `HIDDEN_CARD` (판이 바뀌면 풀린다) |

### 변이 시험 — 내 코드가 틀렸을 때 잡히는가

프로덕션을 한 자리씩 망가뜨리고 돌렸다 (6-G 타깃 + 6-F 주체 + 6-E 컴파일러
= 83개).

| 변이 | 결과 |
|---|---|
| G1 가르지 않고 전부 발동 위치로 (= 6-G 이전 상태) | **4 failed** |
| G2 주체 조건을 뺀다 (`FIELD` 까지 옮긴다) | **5 failed** |
| G3 도착지 조건을 뒤집는다 | **5 failed** |
| G4 옮기면서 발동 위치도 같이 적는다 | **4 failed** |
| G5 범위를 통째로 버린다 | **13 failed** |
| G6 복수 영역에서 하나만 남긴다 | **5 failed** |
| G7 못 옮기는 이름을 조용히 건너뛴다 | **2 failed** |
| G8 시점 조건을 뺀다 (`CARD_DRAWN` 까지) | **2 failed** |

🔴 **8종 전부 검출되었다.** G1 이 잡힌다는 것이 "6-G 이전의 동작으로
되돌리면 시험이 발화한다" 는 뜻이고, G4 가 잡힌다는 것이 **동어반복 통과를
막는 단정이 실제로 있다**는 뜻이다. G2 · G3 · G8 은 세 조건 하나씩을
없앴을 때 각각 잡힌다 — 조건마다 그것을 지키는 시험이 있다.

🔴 **변이 시험 중에 내가 한 번 실수했다.** 변이가 적용된 상태에서 동시에
`tests/engine` 을 돌려 4건이 실패했다. 그 실패는 **변이 때문이고 코드
때문이 아니다** — 변이 실행이 끝나고 작업 트리가 복원된 뒤 다시 돌려
확인했다. 섞인 실행은 아무것도 증명하지 않는다.

---

## 13. Phase 6-F 사건 주체 판정 회귀 결과

전수로 다시 셌다 — `SELF` **3,389** · 미선언 **784**. 6-F 가 측정한 값과
**정확히 같다** (`test_13`).

그리고 두 축이 함께 일하는 것을 동작으로 확인했다 (`test_11`):

* 소환된 그 카드 → 주체 `VALID` + 자리 `VALID` → 그래도 `may_activate=False`
  (막는 관문은 `EXECUTION_AUTHORITY` · `COST_FEASIBILITY` 둘뿐이다)
* 같은 카드의 묘지 사본 → **주체에서** 먼저 막힌다 (`CANDIDATE_NOT_ELIGIBLE`)

🔴 **주체가 다른 효과는 발동 위치가 맞아도 승격되지 않고**, 주체가 맞아도
**위치를 모르면 승격되지 않는다** (§8 의 두 요구).

---

## 14. Engine V1 및 EventJournal 회귀

* `test_14`: 자리 판정 전후로 `state_hash()` · `repr(rng)` · journal 의
  `canonical_state()` 전부 **같다.**
* `test_15`: `UNCHECKED_RULES` **6개 그대로**, `EligibilityGate` **5개 그대로**
  (새 관문 없음).
* `engine/trigger.py` · `engine/duel.py` · `engine/effect/journal.py` 는 **한
  줄도** 바뀌지 않았다.

---

## 15. 타깃 · 통합 · 최종 테스트 결과

지시서 §12 의 3단계를 그대로 따랐다.

### 1단계 — 타깃

```
pytest tests/engine/test_trigger_activation_location.py -p no:randomly -q
→ 18 passed in 88.53s
```

시나리오 1~10 전부와 §11 의 지표 전수 측정이 이 파일 안에 있다.

### 2단계 — 통합

```
pytest tests/engine -p no:randomly -q
→ 3,013 passed in 362.94s
```

`TriggerEligibilityJudge` · `TriggerCollector` · `TriggerSubject` · 효과 분석
계층 · 조건 평가기 · `EventJournal` 회귀가 모두 이 안에 든다.

🔴 **밖에서 난 핀은 1개뿐이다.** 6-E 의 census(`test_i_...`) 가
`activates_from` 수를 816 으로 박아 두었고 6-G 가 1건을 `from_zones` 로
옮겨서 815 가 되었다. 그 시험이 재려던 것은 **"`SetRange` 를 읽은 등록 수"**
이므로 두 칸을 **합쳐** 세도록 고치고 816 을 그대로 두었다 — 단정의 뜻을
지키고 숫자를 바꾸지 않았다. 분리 자체는 새 파일의 `test_07` 이
815 + 1 = 816 으로 따로 잠근다.

### 3단계 — 필요한 범위의 회귀 (1회)

| 범위 | 파일 | 결과 | 시간 |
|---|---|---|---|
| `tests/engine` | — | **3,013 passed** | 6분 03초 |
| `tests/agent` + `rules` + `rulings` | — | **529 passed · 4 skipped** | 6분 28초 |
| 묶음 0 | 23 | **614 passed** | 24분 46초 |
| 묶음 1 | 23 | **587 passed** | 12분 45초 |
| 묶음 2 | 23 | **559 passed** | 20분 58초 |
| 묶음 3 | 22 | **517 passed** | 24분 25초 |
| **합계** | **91 + 하위** | 🔴 **5,819 passed · 4 skipped · 0 failed** | — |

전부 `-p no:randomly` (순서 고정). 🔴 **묶음을 한 번만 돌렸다** — 1차에서
실패가 없었으므로 반복할 이유가 없었다 (§12: *"동일한 대규모 테스트 묶음을
반복하지 않는다"*). 6-F 는 핀이 48개 움직여 두 번 돌려야 했는데, 6-G 는
`engine/trigger.py` 를 건드리지 않아서 핀이 1개였다.

삭제한 테스트 0개 · 추가한 skip 0개 · 약화한 단정 0개 · 낮춘 threshold 0개.

---

## 16. 추가로 발견된 구조적 차단 문제

### 🔴 B-1. 두 축이 상보적이어서 **발동 가능이 구조적으로 0건**이다

§2 의 표가 그것이다. `FIELD` 등록은 위치를 알지만 주체를 모르고, `SINGLE`
등록은 주체를 알지만 위치를 모른다. 둘 다 아는 31건도 실행 권위·비용이
`UNKNOWN` 이다.

**이것이 6-H 의 가장 큰 차단 요인이다.** 위치를 더 넓히거나 주체를 더
넓히는 것보다, **두 축이 겹치는 영역을 넓히는 것**이 실행 가능으로 가는
길이다. 구체적으로는 `FIELD` 등록 784건의 **주체**를 읽을 수 있게 되면
위치는 이미 있으므로 784건이 한꺼번에 두 관문을 통과할 후보가 된다.

### 🟠 B-2. `SetRange` 부재 3,358건은 데이터가 없다

파서 결함이 아니다 (§4). Lua 가 적지 않은 것이므로, 풀려면 EDOPro 코어의
기본 범위 규칙을 **규칙 계층으로** 들여와야 하고 그것은 추측이 아닌 근거를
요구한다. 이번 범위 밖이다.

### 🟠 B-3. `CardInstance.previous` 가 기록만 되고 아무도 읽지 않는다

`engine/` 전체에서 `previous` 를 읽는 production 코드가 **0곳**이다. 6-G 는
사건 쪽(`event.from_zone`) 으로 우회했으므로 **막히지 않았다.** 다만 사건이
없는 자리(예: 지속 효과의 "직전" 판정) 에서는 view 가 그 값을 노출해야 한다.

### 🟠 B-4. 소환 사건의 출발 영역이 시점에 실리지 않는다

`MonsterSummoned.from_zone` 은 delta 에 있는데 `TimingEvent.from_zone` 이
`None` 이다. 지금은 `TriggerSpec` 이 소환 시점의 영역 축을 금지하므로
문제가 되지 않지만, 「패에서 특수 소환했을 때」 류를 가르려면 그 결정을
다시 봐야 한다.

### 🟡 B-5. 6-F 의 `actor` 축은 그대로

3-F-8 이 측정한 사건군별 의미 불일치. 6-G 는 건드리지 않았다 (§13).

---

## 17. Phase 6-H 의 권장 선행 조건과 최소 구현 범위

우선순위 순. 🔴 **1번이 압도적으로 중요하다** — B-1 때문이다.

1. 🔴 **`FIELD` 등록 784건의 주체를 읽는다.** 위치는 **이미 100% 있다**.
   주체만 생기면 두 관문을 통과할 후보가 31건 → 최대 815건이 된다.
   최소 구현 범위: Lua 조건 함수 본문에서 `eg:IsContains(e:GetHandler())` ·
   `eg:GetFirst()` 류를 **블록 단위로** 읽을 수 있는지 먼저 측정한다 (6-F 가
   카드 단위로 2.8%/38.8% 를 재 두었다). 읽히면 `TriggerSubject` 에 세 번째
   값이 생길 근거가 되고, 안 읽히면 그 사실을 기록하고 멈춘다.
2. **`EffectDefinition` 과 컴파일된 선언을 잇는다.** 지금 둘은 이어져 있지
   않고(6-E `test_10`), 그래서 `EXECUTION_AUTHORITY` 가 전부 `UNKNOWN` 이다.
   31건을 실제로 끝까지 판정해 보려면 이것이 필요하다.
3. **`COST_FEASIBILITY`** — 비용과 발동 조건을 섞지 않는 선에서.
4. B-3 (view 의 직전 영역) · B-4 (소환의 출발 영역) — 각각 작고 독립적이다.

**6-H 에서 하지 말 것**: `SetRange` 부재 3,358건을 기본값으로 메우는 것
(B-2), 미지원 사건 코드 3,693건을 넓히는 것 (6-E 가 측정), `actor` 축을
주체 축과 섞는 것.

---

## 18. Git 커밋 및 푸시 결과

### 변경 파일 — 프로덕션 1 · 테스트 2 · 문서 1

| 구분 | 파일 | 줄 |
|---|---|---|
| 프로덕션 | `engine/trigger_compiler.py` | +97 / −5 |
| 테스트 (신규) | `tests/engine/test_trigger_activation_location.py` | +791 |
| 테스트 (핀 1개) | `tests/engine/test_trigger_compiler.py` | +13 / −1 |
| 문서 (신규) | `docs/phase6g-trigger-activation-location.md` | 이 파일 |

🔴 **프로덕션이 한 파일이다.** 그리고 그중 실제 로직은 `_split_range` **14줄**
이고 나머지는 근거를 적은 주석이다.

바뀌지 않은 것: **`engine/trigger.py`** (관문 · `TriggerSpec` · `TimingEvent`
전부) · `engine/duel.py` · `engine/effect/` · `engine/condition/` ·
`engine/state/` · `sources/` · `analysis/` · `core/` · `data/` ·
`script/c*.lua` · `agent/` · `app/` · `rules/` · `rulings/`.

### 커밋 — 3개, 브랜치 `claude/pensive-goodall-te1egy`

| 커밋 | 내용 |
|---|---|
| (프로덕션) | `_split_range` — 등록 범위와 발동 위치 분리 |
| (테스트) | 신규 18개 + 6-E census 핀 1개 |
| (보고서) | 이 파일 |

기존 커밋을 rewrite·amend 하지 않았고, force push 하지 않았으며, 새 브랜치나
PR 을 만들지 않았다.

### 🔴 다음 단계

**Phase 6-H 는 자동으로 시작하지 않는다.** 사용자 검토를 기다린다.

이 단계가 끝낸 것은 **"발동 위치 데이터가 어디서 오는지 확인하고, 그중 틀린
해석 하나를 고치고, 현재 영역과 직전 영역을 가른 것"** 까지다. 🔴 **발동
가능한 효과는 0건이다** — §16-B-1 이 그 이유이고, 위치를 아는 815건은 주체를
모르며 주체를 아는 3,389건은 위치를 모른다. 갈라테아는 이 단계 뒤에도 유발
효과를 **자동으로 발동시키지 못한다.**
