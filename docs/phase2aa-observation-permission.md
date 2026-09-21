# Phase 2-AA — Dynamic Observation Permission / Information Effect Core

기준 커밋: `8a782d3` · 2507 passed / 4 skipped

> **이름에 대하여.** 지시서의 제목은 "Phase 2-Z" 이지만 그 이름은 직전
> 단계(재현 가능한 무작위, `8a782d3`)가 이미 쓰고 있다. 문서가 서로를
> 덮어쓰지 않도록 이 단계를 **2-AA** 로 적는다. 내용과 기준 커밋은
> 지시서 그대로다.

```
Effect
  → ObservationGrant     효과가 **선언**한다 (카드 이름을 모른다)
  → derive_policy        지금 살아 있는 것만 남긴다
  → ObservationPolicy    값
  → GameStateView        viewer 마다 다른 것을 본다
```

한 줄 목표: **효과가 정보를 볼 권한을 동적으로 주고, 각 플레이어의 관측이
그 권한에 따라 서로 다른 것을 보여준다.**

---

## 1. 변경 파일

| 파일 | 변경 |
|---|---|
| `engine/observation.py` | **신규** — 권한의 **값** (`ObservationPermission` · `ActivePermission` · `ObservationPolicy` · `EMPTY_POLICY` · `LUA_PERMISSION_SOURCES`) |
| `engine/observation_grant.py` | **신규** — **선언과 계산** (`ObservationGrant` · `derive_policy`) |
| `engine/game_state_view.py` | `from_state(..., policy=)` · `_zone_view` 가 패 공개를 · `_card_view` 가 뒷면 확인을 본다 |
| `tests/engine/test_observation_permission.py` | **신규** — 34개 |
| `docs/phase2aa-observation-permission.md` · `engine/__init__.py` | 문서 |

**기존 테스트 수정 0건 · 삭제 0건.** `policy` 기본값이 비어 있어 기존
2,507개가 손대지 않은 채 통과한다.

**새 ObservationBus · InformationEventBus · GlobalVisibilityManager ·
CardNameBasedVisibilityRegistry · EventBus 0개.**

---

## 2. 조사 결과 (§1)

먼저 저장소를 읽었다.

| 확인한 것 | 결과 |
|---|---|
| `ObservationPolicy` | **없었다.** 이름만 지시서에 있었고 구현은 없었다 |
| `GameStateView.from_state(..., looked_at=)` | Phase 2-Y 에 있었다 — 대체하지 않았다 |
| 기본 공개 범위 | `zone_visibility` 표 + `_card_view` 의 앞뒷면 판정 |
| `Condition` / `ConditionEvaluator` | 있었다 — 조건 평가를 새로 만들지 않았다 |
| `EffectRef` · `CardInstance` | 있었다 — 권한의 **출처**로 그대로 쓴다 |

그리고 **공식 데이터에서 근거를 찾았다.**

| Lua 원시 | 실제 카드 | 뜻 |
|---|---:|---|
| `EFFECT_PUBLIC` (`constant.lua:492`) | **20장** | 그 자리의 카드가 공개된다 |
| 뒷면 확인에 해당하는 상수 | **없다** | 코퍼스에 그런 상수가 없다 |

`EFFECT_PUBLIC` 을 쓰는 카드의 모양이 그대로 선언이 된다. 마인드 온 에어
(66690411):

```lua
e1:SetType(EFFECT_TYPE_FIELD)
e1:SetCode(EFFECT_PUBLIC)
e1:SetRange(LOCATION_MZONE)            -- 이 카드가 몬스터 존에 있는 동안
e1:SetTargetRange(0, LOCATION_HAND)    -- 앞의 0 = 자신 쪽 없음, 상대 패
```
공식 텍스트: *"Your opponent must play with their hand revealed."*

세레모니 벨(20228463)은 `SetTargetRange(LOCATION_HAND, LOCATION_HAND)` —
*"Both players"* 다. 앞이 자신 쪽, 뒤가 상대 쪽이라는 것이 **세 카드에서
일관되게 확인**된다 (진실의 눈 34694160 과 마인드 온 에어가 `(0, HAND)`,
세레모니 벨이 `(HAND, HAND)`).

---

## 3. 새 abstraction과 그 이유 (§19-3)

**두 파일, 다섯 타입.** 그 밖은 전부 기존 것을 썼다.

### 왜 **두 파일**인가 — 계층이 다르기 때문이다

이것이 이번 단계에서 유일하게 구조적인 판단이다.

```
game_state_view  ──읽는다──▶  observation        (값)
        ▲                          ▲
        │                          │읽는다
        └──읽는다── condition ◀── observation_grant  (선언 · 계산)
```

관측 계층이 권한의 **값**을 읽어야 한다. 그런데 권한이 살아 있는지
판정하려면 **조건 평가기**가 필요하고, 조건 평가기는 거꾸로 관측을 읽는다.
한 파일에 넣으면 import 고리가 생긴다 (실제로 생겼고, 그래서 나눴다).

값을 아래에, 계산을 위에 둔다. **새 시스템을 만든 것이 아니라 한 파일을
두 계층으로 나눈 것이다.**

### 다섯 타입

| 타입 | 왜 필요한가 |
|---|---|
| `ObservationPermission` | 종류를 **값으로** 든다. `REVEAL_HAND` 와 `INSPECT_FACE_DOWN` 을 합치지 않기 위해 (§3) |
| `ObservationGrant` | 효과의 **선언**. Lua 의 `SetRange`/`SetTargetRange`/`SetCondition` 이 그대로 온다 |
| `ActivePermission` | **지금 살아 있는** 권한. 상대 기준(`PlayerRef`)이 절대 번호로 풀려 있다 |
| `ObservationPolicy` | 한 관측에 적용되는 묶음. 불변 |
| `derive_policy` | 판 + 선언 → 살아 있는 것만. **저장하지 않는다** |

---

## 4. Observation Permission 구조 (§19-4)

선언 하나가 담는 것:

```python
ObservationGrant(
    permission=ObservationPermission.REVEAL_HAND,
    source=EffectRef(66690411, 0),      # 어느 효과가 주는가  ← 추적 가능
    holder=InstanceId(...),             # 어느 카드가 들고 있는가
    active_zones=frozenset({Zone.MZONE}),   # SetRange
    beneficiary=PlayerRef.CONTROLLER,   # 누가 보게 되는가
    subject=PlayerRef.OPPONENT,         # 누구의 정보인가   ← SetTargetRange
    condition=None,                     # SetCondition
)
```

`beneficiary`/`subject` 가 **카드의 컨트롤러 기준**이다. 절대 번호를 적으면
같은 선언을 양쪽이 쓸 수 없다 — 조건 계층의 `PlayerRef` 와 같은 이유다.

`active_zones` 는 **비워 둘 수 없다.** 비우면 "어디에 있든" 이 되고, 그것은
원본이 말하지 않은 것을 주장하는 일이다.

### 권한은 저장되지 않는다 (§5)

플래그를 켜 두지 않는다. `derive_policy` 가 **언제나 지금 판에서 다시
계산**하고, 세 관문을 전부 통과해야 살아 있다.

1. holder 카드가 아직 판에 있는가
2. 그 카드가 `active_zones` 안에 있는가 (`SetRange`)
3. 조건이 **참**인가 — `FALSE` 도 `UNKNOWN` 도 권한이 아니다

그래서 **지우는 코드가 없다.** 카드가 사라지면 애초에 계산되지 않는다.
껐다 켜는 상태가 없으면 어긋날 수도 없다.

조건은 holder 컨트롤러의 **기본 관측**으로 판정한다. 권한을 적용한
관측으로 판정하면 "권한이 있어서 조건이 참이고 조건이 참이라 권한이
있다" 가 된다.

---

## 5. REVEAL_HAND 처리 (§19-5 · §6)

`_zone_view` 의 한 줄이다.

```python
revealed = zone is Zone.HAND and policy.permits(REVEAL_HAND, viewer, container.owner)
```

§6 의 표 그대로 동작한다.

| | 자기 패 | 상대 패 |
|---|---|---|
| 권한 없음 · View(P1) | A B C | **hidden** |
| 권한 없음 · View(P2) | D E F | **hidden** |
| P1 에게만 권한 · View(P1) | A B C | **D E F** |
| P1 에게만 권한 · View(P2) | D E F | **hidden** |

`permits(REVEAL_HAND, P1, P2) is True` 이면서
`permits(REVEAL_HAND, P2, P1) is False` — **대칭이 아니다.**

세레모니 벨처럼 양쪽을 공개하는 카드는 **선언 둘**로 표현된다. 하나의
boolean 을 뒤집는 것이 아니다.

패를 공개해도 **덱과 엑스트라 덱은 열리지 않는다** — 권한은 적어 둔
자리만 연다.

---

## 6. INSPECT_FACE_DOWN 처리 (§19-6 · §7)

`_card_view` 의 한 줄이다. 앞뒷면 판정 **뒤**에 온다.

```python
if policy.permits(INSPECT_FACE_DOWN, viewer, card.controller):
    return CardView.revealed(card)
```

| | X(뒷면) | Y(뒷면) | Z(앞면) |
|---|---|---|---|
| 권한 있는 P1 | **확인 가능** | **확인 가능** | 원래부터 공개 |
| 권한 없는 viewer | hidden | hidden | 공개 |

**확인했다고 전체 공개되지 않는다** (§7). `CardInstance` 자체를 바꾸지
않고 **그 관측에서만** 드러낸다 — 확인한 뒤에도 카드는 `is_faceup ==
False` 이고, 권한 없는 관측은 그대로 `None` 이다.

`REVEAL_HAND` 와 **서로를 주지 않는다**: 패만 공개된 관측에서 뒷면은
여전히 가려져 있고, 그 반대도 같다.

### 정직한 결과 — 이 권한을 주는 실제 카드가 없다

"상대의 세트 카드를 언제든 확인한다" 에 해당하는 EDOPro 상수가 코퍼스에
**없다.** 그렇게 적힌 카드(마인드 스캔)에는 스크립트가 아예 없다.

그래서 `LUA_PERMISSION_SOURCES[INSPECT_FACE_DOWN]` 은 `None` 이다 — 빈 칸
대신 **적어 둔다.** 빈 칸은 "없다" 로, 적어 둔 것은 "아직" 으로 읽힌다.
권한의 **모양**은 만들었고 그것을 주는 실제 카드는 아직 없다.

---

## 7. looked_at 과의 관계 (§19-7 · §8)

**대체하지 않았다. 둘은 함께 있을 수 있다.**

| | 무엇 | 누구의 자리 | 언제까지 |
|---|---|---|---|
| `looked_at` (2-Y) | 이 판정을 위한 **일시적 열람** | **자기** 자리만 | 그 판정 동안 |
| `policy` (2-AA) | 효과가 주는 **권한** | **남의** 자리도 | 효과가 살아 있는 동안 |

최종 공개 범위 = **기본 공개 범위 + 권한 + 일시적 열람.**

테스트가 셋을 한 관측에서 확인한다 — 내 덱은 `looked_at` 으로 열리고,
상대 패는 `policy` 로 열리고, 상대 덱은 **둘 다 아니므로 그대로 가려진다.**

`looked_at` 이 `owner == viewer` 를 요구하는 방어는 그대로다. 권한이 남의
자리를 여는 것은 **효과가 그렇게 말하기 때문**이고, 누가 무엇을 보는지가
권한마다 적혀 있다.

---

## 8. Mind Scan validation (§19-8 · §4)

### 사실부터

공식 DB 에 텍스트가 있다 (테스트가 `cards.cdb` 를 직접 읽는다):

> "While you have a "Toon" card in your field or GY, **your opponent must
> keep their hand revealed, also you can look at their Set cards at any
> time.** …"

그리고 **이 저장소에 `c34298391.lua` 가 없다.** 그러므로 이 카드의 의미는
`LUA_VERIFIED` 가 아니고, 목록에 실행 가능한 항목으로 올릴 수 없다
(ADR-004). **검증 시나리오로만 쓴다.**

### 결과 셋

1. **모양은 그대로 적힌다.** 두 권한(`REVEAL_HAND` + `INSPECT_FACE_DOWN`)을
   한 카드가 컨트롤러에게 주는 선언이 그대로 써진다. 카드 이름을 관측
   계층에 적지 않고.
2. **조건이 막는다.** "자신의 필드나 묘지에 '툰' 카드가 존재" 를 판정하려면
   아키타입(setcode) 조건이 필요한데 이 엔진에 없다. `UnimplementedRule`
   로 적으면 `UNKNOWN` → **권한 없음.** 추측해서 켜지 않는다 (§16).
3. **조건을 밖에서 받으면 끝까지 간다.** 같은 선언에 조건만 명시적으로
   끼우면 둘 다 살아나고, 상대에게는 아무것도 열리지 않는다. 구조가
   작동한다는 것이 확인된다 — 싸이크론의 파괴 판정과 같은 자리다.

### 실제로 검증에 쓴 카드

**마인드 온 에어 (66690411)** — `LUA_VERIFIED` 이고 `EFFECT_PUBLIC` 을
쓴다. 테스트가 그 스크립트에서 `EFFECT_PUBLIC` ·
`SetRange(LOCATION_MZONE)` · `SetTargetRange(0,LOCATION_HAND)` 를 실제로
읽어 확인한다.

**마인드 스캔의 두 번째 효과는 구현하지 않았다.**

---

## 9. hidden information safety (§19-9 · §10)

| 경로 | 확인 |
|---|---|
| `to_dict()` · `repr()` · `str()` | 권한 없는 viewer 의 관측에 상대 패의 `card_id` 없음 |
| `instance_id` | **구조로** 확인한다 — 가려진 자리의 `cards == ()`, 관측에 보이는 instance 집합과 비밀 집합이 겹치지 않는다 |
| `ActivePermission.to_dict()` | `{permission, viewer, about, source}` 뿐. **holder 도 카드 정체도 없다** |
| `ObservationPolicy.describe_ko()` | 카드 번호 없음 |
| `state_hash` · `canonical_state` | 권한이 들어가지 않는다 |

권한의 **존재**는 공개 정보지만 그것이 **보여 주는 내용**은 아니다.

**authoritative `GameState` 는 그대로 전부 안다** — 문제는 잘못된 viewer
에게 노출되는 것이지 엔진이 아는 것 자체가 아니다. 테스트가 그 둘을
나란히 확인한다.

### 카드 이름을 보지 않는다 (§20)

가장 중요한 단언이다. 관측 세 파일에 대해 AST 로 확인한다.

1. 카드 번호를 뜻하는 **큰 정수 상수가 없다** (10만 이상).
2. `card_id` · `name` 을 **구체적인 값과 비교하지 않는다.**
   (`self.card_id is not None` 은 "공개되었는가" 이지 어느 카드인지 보는
   것이 아니므로 허용한다.)
3. 주석이 아닌 코드에 카드 이름이 없다.

---

## 10. clone / determinism (§19-10 · §12)

| 보는 것 | 확인 |
|---|---|
| 복제 독립 | 사본에서 holder 를 치워도 원본의 권한과 관측은 그대로 |
| 결정론 | 같은 판 · 같은 선언 · 같은 viewer → 같은 `canonical_state()` |
| 정책도 결정론적 | `ObservationPolicy.canonical_state()` 동일 |

---

## 11. state_hash 영향 (§19-11 · §13)

**바꾸지 않았다.**

권한은 `GameState` + 효과 선언에서 **파생되는 값**이다. 판에 저장된 것이
아니므로 `canonical_state()` 에 넣을 것이 없다. 테스트가 그것을 고정한다
— 관측을 여러 번 만들어도 `state_hash` 가 그대로이고,
`canonical_state()` 의 표현에 `"permission"` 이 없다.

§9 가 요구한 대로 **관측은 읽기다**: 다섯 번씩 관측을 만들고 정책을
계산해도 `state_hash` · `canonical_state` · 덱 순서 · `journal` 이
전부 그대로다.

---

## 12. 테스트 결과 (§19-12 · §17)

`tests/engine/test_observation_permission.py` — **34개**, 전부 통과.

| 묶음 | 수 | §17 | 보는 것 |
|---|---:|---|---|
| A. 기본 숨은 정보 | 3 | A | 권한 없으면 예전 그대로 · 빈 정책 = 무변화 · 자기 세트는 안다 |
| B. REVEAL_HAND | 4 | B | §6 의 표 · 비대칭 · 양쪽은 선언 둘 · 덱은 안 열린다 |
| C. INSPECT_FACE_DOWN | 4 | C | 뒷면 확인 · **전체 공개 아님** · 두 권한은 서로를 안 준다 · 실제 카드 없음 |
| D · E. 생명주기 | 5 | D · E | 카드가 사라지면 · 자리를 떠나면 · 조건 거짓 · **조건 UNKNOWN** · 다시 살아남 |
| F. 여러 효과 | 3 | F | 둘 다 부여 · **하나만 제거** · 같은 권한의 출처 둘 |
| G. looked_at | 3 | — | 함께 존재 · 각자 독립 · 자리 이름을 안 넘는다 |
| H. 판 불변 · 결정론 | 4 | G · H · I | 관측이 판을 안 바꾼다 · 해시 불변 · 복제 독립 · 같은 답 |
| I · J. 유출 | 3 | J | 권한 없는 viewer · 정책 자체 · 엔진은 그대로 안다 |
| K. 마인드 스캔 | 5 | K | 공식 텍스트 · **스크립트 없음** · 모양은 되고 조건이 막는다 · 답을 받으면 끝까지 · **카드 이름 없음** |

전체 회귀: **2541 passed, 4 skipped** (직전 2507 + 34).

---

## 13. 수정/삭제된 기존 테스트 (§19-13)

**0건.** `policy` 기본값이 비어 있어 기존 2,507개가 손대지 않은 채
통과한다.

---

## 14. 새 TODO (§19-14)

- **STRUCTURAL-76 (신규 · 🟠)** — **지속 효과 계층이 없다.**
  `ObservationGrant` 는 만들어졌지만 그것을 **카드에서 자동으로 읽어 오는
  자리**가 없다. 지금은 부르는 쪽이 선언을 넘겨야 한다. `EFFECT_TYPE_FIELD`
  같은 지속 효과를 정의에서 읽는 계층은 여전히 Phase 8 이다.
- **STRUCTURAL-77 (신규 · 🟠)** — **아키타입(setcode) 조건이 없다.**
  "'툰' 카드가 자신 필드나 묘지에 존재" 를 판정할 수 없다. 마인드 스캔을
  비롯해 `IsSetCard` 를 쓰는 실제 카드 4,601장이 여기 걸린다.
- **STRUCTURAL-78 (신규 · 🟡)** — `INSPECT_FACE_DOWN` 을 주는 실제 카드가
  없다. EDOPro 에 해당 상수가 없고, 그렇게 적힌 카드에는 스크립트가 없다.
- **STRUCTURAL-73 · 74 · 75 — 그대로 둔다** (§15). 이번 단계에서 억지로
  해결하지 않았다.
- 그 밖의 기존 TODO 도 **하나도 건드리지 않았다.**

---

## 15. 판정 (§19-1 · §19-15)

| 등급 | 건수 | 내용 |
|---|---:|---|
| 🔴 BLOCKER | **0** | |
| 🟠 STRUCTURAL | 2 신규 | 76 (지속 효과 계층) · 77 (아키타입 조건) |
| 🟡 DETAIL | 1 신규 | 78 (뒷면 확인 실제 카드 없음) |
| 🟢 COSMETIC | 0 | |

### §18 완료 기준

- [x] Dynamic Observation Permission 개념 구현
- [x] REVEAL_HAND 지원
- [x] INSPECT_FACE_DOWN 지원
- [x] viewer 별 permission 분리
- [x] `looked_at` 과 독립적으로 공존
- [x] permission source 추적 가능 (`ObservationPolicy.sources`)
- [x] effect/condition 에 따른 활성/비활성
- [x] permission 제거 시 정보 즉시 비공개
- [x] GameState 와 observation view 분리
- [x] hidden card ID leak 없음
- [x] observation 이 GameState 를 mutate 하지 않음
- [x] clone independence
- [x] deterministic observation
- [x] state_hash semantics 보존
- [x] Mind Scan 기반 validation
- [x] 기존 테스트 전부 통과 (수정 0건)
- [x] 새 테스트 추가 (34개)

**다음 Phase 진행 가능하다.**
