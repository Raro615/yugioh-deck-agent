# Phase 3-E-7 — STRUCTURAL-130 Partial / Excluded Evaluation Audit

Base: `b4ba963` (Phase 3-E-6 · STRUCTURAL-115 해결)
범위: STRUCTURAL-130 하나.
Engine 변경: **없음.** 변경 파일은 `agent/evaluation.py` 하나다.

---

## 0. 결론 한 줄

`excluded` 는 **서로 다른 세 가지**를 한 자유 문자열 목록에 담고 있고,
`partial` 은 그 목록이 비었는지만 보는 **한 비트**다. 분류해 보니 그 셋 중
어느 것도 아닌 **네 번째**가 있었다 — 관측에 있고 평가 목적에도 들어가는데
평가가 읽지 않아서 **아무 기록도 남지 않은** 자리들이다. 그 중 하나는 점수가
틀렸다 (**STRUCTURAL-132**, 엑스트라 몬스터 존).

---

## 1. partial / excluded 의 정의 (코드 수준)

### 1-1. 코드 경로

```
GameState ──clone──▶ Simulator ──▶ GameStateView(viewer)
                                        │
                                        ▼
                        StateEvaluator.evaluate(view)
                                        │
                     ┌──────────────────┴──────────────────┐
                     ▼                                     ▼
            terms: list[(name, int)]              excluded: list[str]
                     │                                     │
                     └──────────────▶ StateValue ◀─────────┘
                                          │
                                          ▼
                              partial = bool(excluded)
```

`excluded` 를 만드는 자리는 `agent/evaluation.py` 의 `StateEvaluator.evaluate`
**하나뿐**이고, 수정 전에는 `excluded.append(...)` 가 **6 곳**이었다.

### 1-2. 정의

| 이름 | 코드 | 뜻 |
|---|---|---|
| `excluded` | `StateValue.excluded: tuple[str, ...]` | 합에 넣지 **못한** 것의 한국어 설명. 범주를 담는 자리가 없다 |
| `partial` | `return bool(self.excluded)` | 그 목록이 비었는가. **그뿐이다** |

### 1-3. `partial` 은 세 뜻을 하나로 묶고 있다 (§7)

Audit 질문은 `partial` 이 셋 중 **무엇**인지 물었다. 답은 **셋 다**이고, 그것이
문제다.

| 후보 뜻 | 실제로 그런 경우 |
|---|---|
| "일부 항만 계산됐다" | 아니다 — 여섯 항은 **언제나** 계산된다 |
| "일부 값이 UNKNOWN 이다" | 그렇다 — 상대 뒷면 · `?` 공격력 |
| "설계상 빠진 것이 있다" | 그렇다 — 묘지 · 제외 존 … |
| (추가) "알지만 세지 않기로 했다" | 그렇다 — 내 뒷면 몬스터의 공격력 (Phase 3-E-6) |

**서로 다른 세 사실이 같은 한 비트로 들어간다.** 그래서 `partial == True` 를
보고 할 수 있는 판단이 없다 — 실측 99.6% 가 참이라는 것은 이 구조의 결과다.
`StateValue.excluded` 의 타입이 `tuple[str, ...]` 이므로 **기계가 범주를 읽을
방법이 아예 없다.** 이것이 STRUCTURAL-130 의 본체이고, **이 Phase 로 해결되지
않는다** (§13).

### 1-4. 이름이 겹치는 다른 것들 (혼동 주의)

| 이름 | 위치 | 이것과 **무관**하다 |
|---|---|---|
| `TriggerOrdering.excluded` | `engine/trigger_order.py:212` | `INELIGIBLE` · `FORBIDDEN` 인 트리거. `UNKNOWN` 은 여기 안 들어간다 |
| `is_partial` | `engine/execution.py:990` | 연산이 일부만 수행된 결과 |
| `Partial.AS_MANY_AS_POSSIBLE` | `engine/effect/operation.py` | 효과의 "가능한 만큼" 의미 |

`agent` 쪽 `partial`/`excluded` 는 **이 셋과 아무 관계가 없다.**

### 1-5. 99.6% 라는 수치의 기준

`tests/agent/test_evaluation_alignment_audit.py::test_12` 가 재는 값이다.

```
분모 = 실제 듀얼을 돌리며 simulate 한 모든 future (result.future is not None)
분자 = 그 중 EV.evaluate(future).partial 이 참인 것
```

**상태의 비율이 아니라 "평가 호출 횟수" 의 비율**이다. 선택 정책에 따라 달라지는
수치임을 실측으로 확인했다:

| 선택 정책 | 평가 호출 | partial |
|---|---|---|
| `allowed[0]` · seed 1,2 (테스트와 동일) | 443 | 99.32% |
| 무작위 · seed 1–6 | 3031 | **99.64%** |
| ATK `?` 덱 · 무작위 · seed 1–4 | 975 | 99.90% |

---

## 2. Excluded 전체 목록 (실측)

사례를 만들지 않고 실제 듀얼에서 모았다 (무작위 선택 · seed 1–6 · 3031 회 평가).

| # | 문구 | 실측 빈도 | observable | hidden info | 점수 반영 | 제외 이유 |
|---|---|---|---|---|---|---|
| 1 | 상대 패 N장의 값을 모른다 | 99.64% | 장수만 | **예** (내용) | 안 함 | 내용을 알아야 값을 매긴다고 적혀 있다 |
| 2 | 묘지 N/N장은 값을 매기지 않았다 | 92.74% | 예 (PUBLIC) | 아니오 | 안 함 | `GRAVE_IS_COUNTED = False` |
| 3 | 내 뒷면 몬스터 N마리의 공격력은 세지 않았다 | 68.99% | 예 (내 카드) | 아니오 | 안 함 | 뒷면은 공격하지 않는다 (3-E-6) |
| 4 | 상대 몬스터 N마리의 공격력을 모른다 | 65.89% | 아니오 | **예** | 안 함 | 정의를 읽을 수 없다 |
| 5 | 내 몬스터 N마리의 공격력을 모른다 | 0% (실측) | 예 | 아니오 | 안 함 | 공격력이 `?` 다 — 숫자가 없다 |
| 6 | 상대 뒷면 몬스터 N마리의 공격력은 세지 않았다 | **도달 불가** | — | — | — | 상대 뒷면은 정의를 못 읽으므로 #4 로 먼저 걸린다 |

\#5 는 실제 듀얼 말뭉치에서 0 회였지만 **도달 가능**하다 — 저주받은 하인 킹
(36021814, ATK `?`) 을 내 몬스터 존에 두면 바로 나온다 (실측 확인).
\#6 은 `_zone_attack` 의 판정 순서 때문에 **구조적으로 도달 불가**다.

### 2-1. 그리고 excluded 에 **적히지 않고 사라지던 것** (이 Audit 의 발견)

아래 자리는 카드가 있어도 `excluded` 가 **비었고**, 그래서 `partial` 이
`False` — 즉 "다 셌다" 는 **거짓**을 말했다.

| 자리 | 가시성 | 점수 반영 | excluded | 수정 전 평가 |
|---|---|---|---|---|
| 엑스트라 몬스터 존 (EMZONE) | PUBLIC | **안 함** | 없음 | ATK 1900 몬스터가 **+0** |
| 필드 존 (FZONE) | PUBLIC | 안 함 | 없음 | +0 |
| 펜듈럼 존 (PZONE) | PUBLIC | 안 함 | 없음 | +0 |
| 제외 존 (REMOVED) | PUBLIC | 안 함 | 없음 | +0 |
| 엑스트라 덱 (EXTRA) | 장수 공개 | 안 함 | 없음 | +0 |

`GRAVE_IS_COUNTED` 의 주석은 "묘지 **· 제외 존**의 한 장" 이라고 적고 있는데
실제 보고는 묘지만 적고 있었다 — 주석과 코드가 어긋나 있었다.

---

## 3. A / B / C 분류

| 사례 | Category | 근거 |
|---|---|---|
| 상대 패 N장 | **B** (+A) | 내용은 관측 불가(B). 장수는 보이지만 "세지 않는다" 는 명시된 설계(A) — 그 결과가 STRUCTURAL-129 이고 §0 범위 밖이다 |
| 묘지 | **A** | PUBLIC 이고 정의도 읽히지만 `GRAVE_IS_COUNTED = False` 로 **명시적으로** 세지 않는다 |
| 내 뒷면 몬스터 공격력 | **A** | Phase 3-E-6 에서 근거와 함께 정한 의도적 제외 (WITHHELD) |
| 상대 몬스터 공격력 | **B** | 정의가 `None` 이다. 공개해서 해결하지 않는다 |
| 내 몬스터 공격력 (`?`) | **A/B 경계 → 제외 유지** | 정의는 읽히는데 **공격력 자리에 숫자가 없다**. 0 도 큰 수도 거짓이므로 UNKNOWN 으로 남긴다 |
| 제외 존 · 필드 존 · 펜듈럼 존 · 엑스트라 덱 | **A, 단 보고 누락** | 세지 않는 것은 설계. **적지 않은 것이 결함**이었다 |
| **엑스트라 몬스터 존** | **C** | §4 다섯 조건을 모두 만족한다 (아래) |

**Category A: 5** (묘지 · 내 뒷면 · 제외 존 · 필드 존/펜듈럼 존 · 엑스트라 덱)
**Category B: 2** (상대 패 내용 · 상대 뒷면 몬스터)
**Category C: 1** (엑스트라 몬스터 존 = STRUCTURAL-132)

---

## 4. Category C 증명 — STRUCTURAL-132

§4 의 다섯 조건을 **코드로** 확인한다. 어느 하나도 내 추정이 아니다.

### 조건 1 — 정보가 GameState 에 있다
`Zone.EMZONE` 은 `engine/vocabulary.py` 에 칸 1개로 정의돼 있고
(`ZONE_CAPACITY[Zone.EMZONE] = 1`), `GameState.move` 로 카드가 들어간다.

### 조건 2 — viewer 가 관측할 수 있다
`ZONE_VISIBILITY[Zone.EMZONE] = PUBLIC`. 앞면 카드이므로 `_card_view` 가
`CardView.revealed` 를 돌려준다.

### 조건 3 — GameStateView 로 합법적으로 전달된다
`PlayerView.extra_monster_zone` 이 존재하고, 실측에서 `size=1`,
`definition.atk=1900`, `face_up=True` 가 모두 읽혔다.

### 조건 4 — 현재 Evaluation 의 목적에 포함된다 ← **이것이 핵심**

"EMZ 의 몬스터가 평가 목적에 들어가는가" 는 의견이 아니다. **엔진이 이미 다섯
자리에서 `MZONE` 과 `EMZONE` 을 함께 센다.**

| 위치 | 내용 |
|---|---|
| `engine/battle.py:97` | `BATTLE_ZONES = (Zone.MZONE, Zone.EMZONE)` |
| `engine/duel.py:82` | `BATTLE_TARGET_ZONES = (Zone.MZONE, Zone.EMZONE)` |
| `engine/action_validation.py:82` | `MONSTER_ZONES = {Zone.MZONE, Zone.EMZONE}` |
| `engine/action_validation.py:1112` | **RULE-BATTLE-013** (직접 공격) 이 두 존의 장수를 합쳐 센다 |
| `engine/cost/model.py:41` | `FIELD_MONSTER_ZONES = {Zone.MZONE, Zone.EMZONE}` |

그러므로 EMZ 의 몬스터는 **공격하고, 공격 대상이 되고, 직접 공격을 막는다.**
`MONSTER_IN_LP` 의 근거가 "공격을 한 번 더 할 수 있고 한 번 더 막을 수 있다"
이고 `ATK_IN_LP` 의 근거가 "공격력은 그대로 LP 로 들어오는 피해" 이므로, 두
가중치의 **기존 근거가 글자 그대로 성립한다.** 새 가중치가 필요 없다.

### 조건 5 — 그런데 Evaluation 이 버린다
`_zone_attack(me.monster_zone)` · `me.monster_zone.size` — `MZONE` 하나만
읽었다.

### 실측 — 탐색이 공격하는 몬스터를 평가가 부정한다

내 MZONE 에 사파이어 드래곤(1900), 상대 EMZONE 에 버닝 블러드(1700)를 두고
배틀 페이즈에서:

```
legal: ['ATTACK', 'END_PHASE']          ← 엔진은 그 몬스터를 공격 대상으로 준다
P0 평가: +2400  excluded=()  partial=False   ← 상대 필드가 빈 것과 같은 점수
P1 평가: -2400  excluded=()  partial=False   ← 제 몬스터를 제 것으로 세지 않는다
```

`partial=False` 가 "빠진 것 없다" 고 말하는 동안 **필드의 몬스터 한 마리가
통째로 사라졌다.** STRUCTURAL-115 보다 나쁜 형태다 — 115 는 거짓 보고를
남겼지만 이쪽은 **아무 기록도 남기지 않는다.**

### 왜 FZONE / PZONE 은 Category C 가 아닌가

조건 1·2·3·5 는 같다. **조건 4 가 확인되지 않는다** — `SPELL_TRAP_IN_LP` 가
필드 존·펜듈럼 존을 포함하도록 정해졌다는 기록이 어디에도 없고, 엔진의
`FIELD_ZONES` 가 이들을 "필드" 로 묶는 것은 **파괴가 일어나는 자리**라는 다른
목적이다. §14 경우 3 에 따라 **점수화하지 않는다.** 다만 조용히 빠지던 것은
보고를 고쳤다 (점수 변화 0).

---

## 5. 최소 수정 (§8)

변경 파일: `agent/evaluation.py` **하나.** engine/ 변경 0건. 가중치 변경 0건.

### 5-1. STRUCTURAL-132 — 자리 하나를 더 읽는다

```python
def _field_monster_zones(player: PlayerView) -> tuple[ZoneView, ZoneView]:
    return (player.monster_zone, player.extra_monster_zone)
```

`atk` 와 `monsters` 가 이 둘을 함께 본다. **가르는 규칙(`_zone_attack`)은
건드리지 않았다** — 자리마다 세고 더하기만 한다. 새 상수 0개.

### 5-2. STRUCTURAL-130 — 세지 않은 것을 적는다

```python
_UNSCORED_ZONES = (
    ("제외 존", lambda player: player.removed),
    ("필드 존", lambda player: player.field_zone),
    ("펜듈럼 존", lambda player: player.pendulum_zone),
    ("엑스트라 덱", lambda player: player.extra),
)
```

네 자리 모두 **장수가 양쪽에 공개된 사실**이므로 문구는 "모른다" 가 아니라
"값을 매기지 않았다" 다 — Phase 3-E-6 에서 가른 둘을 다시 섞지 않는다.
묘지는 `GRAVE_IS_COUNTED` 가 따로 쥐고 있어 기존 블록을 그대로 두었다.

**점수는 하나도 바뀌지 않는다.** 세지 않던 것을 세기 시작한 것이 아니라,
세지 않는다고 말하기 시작한 것이다.

### 5-3. 중간에 잡힌 내 실수

처음에는 `_UNSCORED_ZONES` 를 `("grave", "묘지")` 처럼 **속성 이름 문자열**로
적고 `getattr(me, attribute)` 로 읽었다. 그러자
`test_03_the_evaluator_reads_these_and_not_side_to_move` 가 깨졌다 — 그 테스트는
"평가가 어느 자리를 읽는가" 를 소스의 이름으로 고정하는데, `getattr` 이 그
이름을 지워 버린 것이다.

**테스트가 옳았다.** 테스트를 고치지 않고 코드를 접근자(`lambda player:
player.removed`)로 바꿨다. 정적으로 읽히는 것이 실제로 가치가 있었다.

---

## 6. Observation Boundary (§5)

침범 없음.

- 상대 뒷면 몬스터: 정의를 못 읽으므로 `unknown` 으로 간다. 세트한 카드를
  바꿔도 점수가 **같다** (실측).
- 상대 패: 장수만 쓰고 내용은 읽지 않는다. 변경 없음.
- `withheld` 는 **정의를 읽을 수 있는 뒷면 카드만** 센다 — 판정 순서가
  그것을 보장한다 (`unknown` 판정이 먼저다).
- 새로 읽은 자리는 EMZONE / FZONE / PZONE / REMOVED / EXTRA 의 **장수와
  앞면 카드의 정의**뿐이다. 모두 이미 공개된 사실이다.
- 가려진 정보를 읽는 위반을 주입했을 때 기존
  `test_02_the_evaluator_reads_no_hidden_channel` 이 잡았다 (아래 §9).

---

## 7. withheld / unknown / excluded / partial 의 관계 (§6)

```
_zone_attack(zone)
   ├─ total     ─────────────▶ terms["atk"] 에 들어간다
   ├─ unknown   ─┐             읽을 수 없다      "…모른다"
   └─ withheld  ─┤             알지만 안 센다    "…세지 않았다"
                 │
설계상 안 세는 존 ┤             GRAVE_IS_COUNTED · _UNSCORED_ZONES
                 │             "…값을 매기지 않았다"
                 ▼
             excluded: tuple[str, ...]   ← 세 범주가 **같은 목록**으로
                 │
                 ▼
             partial: bool               ← **한 비트로 뭉개진다**
```

`unknown` 과 `withheld` 는 `_zone_attack` 안에서 **갈라져 있다** (3-E-6).
`excluded` 에서는 **문구로만** 갈라진다. `partial` 에서는 **갈라지지 않는다.**

---

## 8. 수정 전 / 후 (§10)

점수가 바뀐 것은 **EMZ 하나뿐**이다.

| 상태 | 수정 전 | 수정 후 |
|---|---|---|
| 내 MZONE 에 ATK 1900 | +2400 / `partial=False` | +2400 / `partial=False` (변화 없음) |
| 내 **EMZONE** 에 ATK 1900 | **+0** / `partial=False` | **+2400** / `partial=False` |
| 내 EMZ 1900 vs 상대 EMZ 1700 | 비대칭 | `atk=+200`, 두 자리 합 **0** (영합) |
| 내 FZONE 에 1장 | +0 / `partial=False` | **+0** / `partial=True`, "필드 존 1/0장은 값을 매기지 않았다" |
| 내 PZONE 에 1장 | +0 / `partial=False` | +0 / `partial=True` |
| 내 REMOVED 에 1장 | +0 / `partial=False` | +0 / `partial=True` |
| 엑스트라 덱 3/3 | +0 / `partial=False` | +0 / `partial=True` |

### 실제 듀얼 통계는 **전혀 바뀌지 않았다**

| 선택 정책 | 수정 전 partial | 수정 후 partial |
|---|---|---|
| `allowed[0]` seed 1,2 | 99.3228% (443건) | **99.3228% (443건)** |
| 무작위 seed 1–6 | 99.6371% (3031건) | **99.6371% (3031건)** |
| ATK `?` 덱 무작위 | 99.8974% (975건) | **99.8974% (975건)** |

문구별 빈도도 소수점까지 같고, 적용된 행동 분포도 같다. 지금 엔진에서는
EMZ · FZONE · PZONE · REMOVED · EXTRA 에 **도달하는 수단이 없기** 때문이다.

**즉 STRUCTURAL-130 은 이 Phase 로 해결되지 않았다.** `partial` 은 여전히
99.6% 다. 묘지(92.7%)와 상대 패(99.6%)가 지배하고, 둘 다 Category A/B 이므로
"없앨" 수 있는 것이 아니다. 해결은 `partial` 을 **쓸 수 있는 신호로 바꾸는**
일이고 그것은 자료 구조 변경이다 (§12 제안).

---

## 9. 의도적 위반 주입 (5건)

| # | 주입 | 결과 |
|---|---|---|
| 1 | `_field_monster_zones` 에서 EMZ 를 다시 뺀다 | **잡힘** — `test_08b`, `test_09`, `test_10` |
| 2 | `_UNSCORED_ZONES` 루프를 지운다 | **잡힘** — `test_02`, `test_04`, `test_05` |
| 3 | `_zone_attack` 의 판정 순서를 뒤집는다 | **처음엔 못 잡았다** ↓ |
| 4 | 제외 문구에서 범주 표현을 없앤다 | **잡힘** — `test_02`, `test_04` |
| 5 | 상대 뒷면의 `card_id` 를 점수에 흘린다 | **잡힘** — 기존 `test_02_the_evaluator_reads_no_hidden_channel` |

### 위반 3 — 내 테스트가 비어 있었다

판정 순서를 뒤집어도 **69개 테스트 전부 통과했다.** 내가 세트한 공격력 `?`
몬스터만 영향을 받는데(`unknown` → `withheld`), 그 경우를 아무 테스트도
고정하지 않았기 때문이다. Phase 3-E-6 이 "순서가 규칙이다" 라고 적어 둔
자리인데 그 규칙이 테스트로 지켜지지 않고 있었다.

`test_07b_unreadable_beats_face_down_when_both_are_true` 를 추가해 재주입했고,
이번에는 잡혔다. **읽을 수 없는 것이 뒷면보다 먼저다** — 앞면으로 뒤집어도
여전히 셀 수 없으므로 `UNKNOWN` 이 더 근본적인 사실이다.

---

## 10. Search 영향 (§10 · 최소 확인만)

`legal action → simulation → future state → GameStateView → evaluation` 경로가
깨지지 않는지만 확인했다. AI 성능 비교는 하지 않았다.

| 조합 | 완주 | 거부 | 에러 | 한도 | 시뮬 | 결정 |
|---|---|---|---|---|---|---|
| search vs search | 8/8 | 0 | 0 | 0 | 1834 | 818 |
| search vs rule | 8/8 | 0 | 0 | 0 | 802 | 768 |
| rule vs search | 8/8 | 0 | 0 | 0 | 801 | 709 |
| rule vs rule | 8/8 | 0 | 0 | 0 | 0 | 716 |

시뮬레이션 수 · 결정 수 · 행동 분포가 수정 전과 **동일**하다.

---

## 11. 성능 (§13)

### evaluate 하나 (같은 판에서 수정 전/후 교차 측정)

| 판 | 수정 전 | 수정 후 | 배수 |
|---|---|---|---|
| 몬스터 0마리씩 | 8.07 µs | 12.63 µs | 1.57× |
| 몬스터 3마리씩 | 9.11 µs | 16.28 µs | 1.79× |
| 몬스터 5마리씩 | 9.15 µs | 17.40 µs | 1.90× |

**원인을 숨기지 않는다.** `PlayerView.monster_zone` 같은 접근자는 매번
`zones` 를 선형 탐색한다 (`engine/game_state_view.py:513`). 읽는 존이 양쪽
합계 10곳 → 20곳이 되었으므로 그만큼 느려졌다. `engine/` 은 §11 로 동결이라
그쪽 색인화는 하지 않았고, `agent` 쪽에서 같은 자리를 두 번 꺼내지 않도록
자리 목록을 한 번만 만들어 넘기는 것까지만 했다 (처음 측정 2.4× → 1.6×).

### 탐색 전체 (8판 × 3회 최소값)

| 조합 | 수정 전 | 수정 후 |
|---|---|---|
| search vs search | 5742 ms | **5699 ms** |
| search vs rule | 3293 ms | **3333 ms** |
| rule vs rule | 1846 ms | **2007 ms** |

평가는 시뮬레이션 비용의 작은 일부여서 **의미 있는 차이가 없다**
(rule vs rule 은 평가를 쓰지 않으므로 그 차이는 측정 잡음이다).

---

## 12. TODO

### 해결

- **STRUCTURAL-132 (신규 · 이 Audit 에서 발견) — RESOLVED**
  엑스트라 몬스터 존의 몬스터가 평가에서 통째로 빠졌다. Category C.

### AUDIT ONLY — 분류만 끝났고 해결되지 않았다

- **STRUCTURAL-130 — AUDIT ONLY**
  `partial` 은 여전히 한 비트이고 실측 99.6% 다. 조용히 빠지던 네 자리의
  **보고**는 고쳤지만, 세 범주를 **기계가 구분할 수 없다는 구조**는 그대로다.

### 유지 (§0 범위 밖 · 손대지 않았다)

STRUCTURAL-102 · 107 · 109 · 110 · 116 · 118 · 120 · 122 · 123 · 128 · 129 ·
131 전부 유지.

특히 **STRUCTURAL-129** 와 겹치는 지점을 적어 둔다: "상대 패는 내용을 알아야
값을 매긴다" 는 명시된 설계지만, 평가는 **내 패도 내용과 무관하게 장수로만**
센다 (`me.hand.size * HAND_CARD_IN_LP`). 즉 비대칭의 근거가 그 자신의 기준으로
성립하지 않는다. 129 가 §0 범위 밖이므로 **고치지 않고 기록만 한다.**

---

## 13. 테스트

```
3378 passed · 0 failed · 4 skipped
```

기준(`b4ba963`) 3365 passed → **+13 (신규 파일 `tests/agent/test_evaluation_excluded_audit.py`)**

- 삭제 0 · skip 0 · assertion 완화 0
- 기존 테스트 **수정 0건.** `test_03` 이 한 번 깨졌지만 §5-3 처럼 **코드를**
  고쳐서 되돌렸다
- Phase 3-E-1 ~ 3-E-6 regression **0**

---

## 14. 다음 Phase 후보 — 하나만

**STRUCTURAL-130 을 구조로 해결한다: `excluded` 에 범주를 담는다.**

이번 Audit 이 분류를 **문서와 문구로** 끝냈다. 다음은 그것을 자료 구조로
옮기는 일이다.

```
excluded: tuple[str, ...]
  → excluded: tuple[Exclusion, ...]
       Exclusion(category: ExclusionCategory, note: str)
       ExclusionCategory = DESIGNED_OUT | UNKNOWN | WITHHELD
```

그러면 `partial` 대신 "**모르는 것이 있는가**"(UNKNOWN 만) 를 물을 수 있게 되고,
그것은 99.6% 가 아니다 — 묘지(92.7%)가 DESIGNED_OUT 으로 빠지기 때문이다.

근거가 강한 이유:

1. 분류가 이미 **실측으로 완결**되었다 (§2 · §3). 추측할 것이 남지 않았다
2. **가중치를 만들지 않는다** — 점수는 한 숫자도 바뀌지 않는다
3. **engine/ 을 건드리지 않는다**
4. 이번 Audit 에서 "범주를 담는 자리가 없다" 가 STRUCTURAL-130 의 **본체**로
   확인되었다

128 / 129 는 Depth-2 · 영합 설계와 함께 묶여 있어 지금 할 수 없다.
