# Phase 3-E-6 — STRUCTURAL-115 Evaluation Correction

- **Base commit**: `c842000` (Phase 3-E-5 — Evaluation Alignment Audit)
- **Branch**: `claude/pensive-goodall-te1egy`
- **결과**: 3364 → **3365 passed, 4 skipped** · 회귀 0건
- **변경**: `agent/evaluation.py` **하나** · `engine/` 변경 **0건**

---

## 0. 먼저 — 문제의 이름을 바로잡는다

이번 Phase 의 지시문은 STRUCTURAL-115 를 *"앞면/뒷면 **공격 상황**을 평가할 때
서로 다른 실제 **전투 결과**를 같은 방식으로 평가하는 문제"* 로 적었다.

**재현 케이스(`test_11`)는 전투를 하지 않는다.** 두 **판 상태**를 비교한다 —
내 몬스터가 앞면 공격 표시인 판과 뒷면 수비 표시인 판. 공격은 일어나지 않고,
그래서 전투 결과가 끼어들 자리가 없다.

그리고 **전투 결과는 애초에 올바르게 달랐다** (§3 에서 실측). 그래서 이번
작업은 전투가 아니라 **판 상태 평가**의 문제였고, 아래는 그 기준으로 적는다.

---

## 1. 한 줄 결론

> ``_zone_attack`` 이 ``card.position`` 과 ``card.face_up`` 을 **한 번도 읽지
> 않았다.** Battle 도 Observation 도 정상이었고, 결함은 Evaluation 층 하나에
> 있었다.

---

## 2. 3층 분리 — 어디에서 정보가 사라졌나

지시문 §2 가 섞지 말라고 한 셋을 각각 실측했다.

### A. Battle Execution — **정상**

실제 `BattleExecutor().judge()` 로 ATK 1900 이 배틀 옥스(ATK 1700 / DEF 1000)를
공격하게 했다.

| 수비 측 표시 형식 | kind | rule | target_value | damage | destroy_target |
|---|---|---|---|---|---|
| 앞면 공격 표시 | `versus_attack` | RULE-BATTLE-011 | **1700** (ATK) | 200 | True |
| 뒷면 수비 표시 | `versus_defence` | RULE-BATTLE-012 | **1000** (DEF) | 0 | True |

전투 층은 position 을 올바르게 읽는다. **문제가 아니다.**

### B. State / Observation — **정상**

| | Case A (앞면 공격) | Case B (뒷면 수비) |
|---|---|---|
| `state_hash` | `cebe622fd84cced8bfc408a7…` | `968de2ad47f5cc8fbdfd39de…` |
| `view.canonical_state()` | — | **다르다** |
| `CardView.position` | `FACEUP_ATTACK` | `FACEDOWN_DEFENSE` |
| `CardView.face_up` | `True` | `False` |
| `definition.atk` | 1900 | 1900 |
| `definition.defense` | 1600 | 1600 |
| `definition.has_defense` | `True` | `True` |

관측은 두 경우를 **구분하고**, 수비력까지 **이미 제공한다**. 관측 계층을 바꿀
필요가 없었다.

### C. Evaluation — **여기가 결함**

| | heuristic | `atk` | `monsters` | `excluded` |
|---|---|---|---|---|
| Case A | `+2400` | `+1900` | `+500` | `()` |
| Case B | `+2400` | `+1900` | `+500` | `("내 뒷면 카드 1장은 값을 매기지 않았다",)` |

### §5 판정 — **③ GameStateView 도 다른데 Evaluation score 만 동일하다**

세 후보 중 ③ 으로 특정된다. `state_hash` 도 `canonical_state` 도 `CardView`
도 전부 다르고, 점수만 같았다.

---

## 3. 원인 — 코드 수준

```python
def _zone_attack(zone: ZoneView) -> tuple[int, int]:
    for card in zone.occupied():
        definition = card.definition
        if definition is None or not definition.is_monster: ...
        if definition.atk_is_question or not definition.has_atk: ...
        total += definition.atk          # ← position · face_up 을 보지 않는다
```

`occupied()` 의 **모든** 몬스터에서 `definition.atk` 를 그대로 더했다.
`card.position` 도 `card.face_up` 도 한 번도 읽지 않는다.

그리고 `StateEvaluator.evaluate` 는 **따로** 뒷면 카드 수를 세어
`excluded` 에 "값을 매기지 않았다" 를 적었다 — 값은 이미 들어가 있는데.

| 종류 | 당시 상태 |
|---|---|
| `DEF` 를 `ATK` 처럼 취급하는 코드 | **없다** (DEF 를 아예 읽지 않았다) |
| position 을 무시하는 코드 | **있다** — `_zone_attack` |
| battle result 를 읽는 코드 | **없다** (판 상태만 본다 — 설계대로) |

---

## 4. 재현

### Case A

| | |
|---|---|
| 카드 | 사파이어 드래곤 `11091375` (ATK 1900 / DEF 1600) |
| position | `FACEUP_ATTACK` |
| battle | 해당 없음 (공격하지 않는다) |
| `canonical_state` | A |
| Evaluation | `+2400` — `atk +1900`, `monsters +500`, `excluded ()` |

### Case B

| | |
|---|---|
| 카드 | **같은 카드** 사파이어 드래곤 `11091375` |
| position | `FACEDOWN_DEFENSE` |
| battle | 해당 없음 |
| `canonical_state` | B (**A 와 다르다**) |
| Evaluation (수정 전) | `+2400` — `atk +1900`, `monsters +500`, `excluded ("값을 매기지 않았다",)` |
| Evaluation (수정 후) | `+500` — `atk 0`, `monsters +500`, `excluded ("공격력은 세지 않았다",)` |

**차이가 정확히 1900** = 그 카드의 공격력이다.

---

## 5. 수정 내용

### 파일: `agent/evaluation.py` 하나

**① `_zone_attack` 이 "읽을 수 없다" 와 "세지 않는다" 를 가른다**

반환값이 `(total, unknown)` → `(total, unknown, withheld)` 로 늘었다.

```python
for card in zone.occupied():
    definition = card.definition
    if definition is None or not definition.is_monster:
        unknown += 1;  continue      # 읽을 수 없다 (상대 뒷면)
    if definition.atk_is_question or not definition.has_atk:
        unknown += 1;  continue      # 값이 ? 다
    if _is_face_down(card):
        withheld += 1; continue      # 읽을 수 있지만 세지 않는다 (내 뒷면)
    total += definition.atk
```

**순서가 규칙이다.** 읽을 수 있는지를 **먼저** 본다 — 상대의 뒷면 카드는
정의가 없으므로 `unknown` 으로 가고, `withheld` 는 **정의를 읽을 수 있는 뒷면
카드**(내 것)만 센다. 순서를 뒤집으면 상대 뒷면이 `withheld` 로 새고, 그것은
"상대 카드를 알지만 안 셌다" 는 새 거짓이 된다.

**② 보고가 사실을 말한다**

- 새 문장: `"내 뒷면 몬스터 N마리의 공격력은 세지 않았다 (뒷면은 공격하지 않는다)"`
- 지운 문장: `"내 뒷면 카드 N장은 값을 매기지 않았다"` — **어느 쪽으로도 참이
  아니었다.** 공격력은 세고 있었고, 자리의 값(`monsters`·`spells`)은 **지금도**
  센다.

**③ 모듈 설명을 코드에 맞췄다** — "모른다" 와 "세지 않았다" 의 구분을 적고,
수비력 점수화는 하지 않았다는 것을 명시했다.

### 왜 이것이 최소 변경인가

| 하지 않은 것 | 왜 |
|---|---|
| 관측 계층 변경 | `position`·`face_up`·`defense` 가 **이미** 있었다 |
| Battle 계층 변경 | 전투 결과는 애초에 올바르게 달랐다 |
| 새 가중치 · 새 상수 | 하나도 더하지 않았다 (§9) |
| 수비력 점수화 | 환산 근거를 새로 정해야 하므로 별도 Phase (§9) |
| `monsters` / `spells` 항 변경 | 뒷면도 칸을 차지하고 나중에 쓸 수 있다 — 세는 것이 사실이다. 양쪽을 같은 방식으로 세므로 대칭이고 가려진 정체를 읽지도 않는다 |

바꾼 것은 **"뒷면의 공격력은 지금 들어올 피해가 아니다"** 하나이고, 그것은
평가 모듈의 설명이 **이미 의도라고 적고 있던 것**이다.

### 세 선택지 중 ① 을 고른 근거

Phase 3-E-5 가 세 선택지를 적었다. 둘은 이번 Phase 의 제약이 **배제한다**.

| | 선택지 | 판정 |
|---|---|---|
| ① | 뒷면의 공격력을 세지 않는다 | **채택** — 모듈 설명이 이미 의도라고 적고 있다 |
| ② | 수비력을 센다 | §9 가 금지 — LP 환산 근거를 새로 정해야 한다 |
| ③ | 그대로 세고 문장만 지운다 | §11 · 최종원칙 위반 — 두 상태가 **여전히 구분되지 않는다** |

자유롭게 고른 것이 아니라 **제약이 하나만 남겼다.**

---

## 6. Evaluation 결과

| 판 | 수정 전 | 수정 후 |
|---|---|---|
| 내 1900 앞면 공격 | `+2400` · `excluded ()` | `+2400` · `excluded ()` (변화 없음) |
| 내 1900 뒷면 수비 | `+2400` · 거짓 보고 | **`+500`** · 참인 보고 |
| 내 뒷면 함정 1장 | `+300` · 거짓 보고 | `+300` · **`excluded ()`** (뺀 것이 없다) |
| 상대 1900 뒷면 | `-500` · "모른다" | `-500` · "모른다" (변화 없음) |

### 덤으로 맞춰진 것 — 뒷면이 영합(zero-sum)이 되었다

| 판 | 수정 전 (P0 + P1) | 수정 후 |
|---|---|---|
| 내 앞면 공격 1900 | `+2400 − 2400 = 0` | `0` |
| 내 뒷면 수비 1900 | `+2400 − 500 = **+1900**` | `+500 − 500 = **0**` |

평가 모듈의 설명이 **바로 이것을 피하려 했다**고 적고 있었다: *"넣으면 같은
판이 보는 자리에 따라 다른 점수가 되어 §23 의 일관된 관점이 깨지기 때문이다."*

**이것은 STRUCTURAL-129 를 고친 것이 아니다.** 패 항은 그대로 차분이 아니고,
여기서 맞춰진 것은 뒷면 몬스터뿐이다.

---

## 7. Search 영향 (§12)

8씨앗 · 같은 덱 · `set_monster` 를 네 가지로 따로 셈.

| 조합 | legal | selected | simulated | executed |
|---|---|---|---|---|
| search | 230 | **0** | **230** | 0 |
| rule | 258 | 0 | — | 0 |
| random | 514 | 85 | — | 85 |
| first-legal | 260 | 0 | — | 0 |

4조합 전부 `completed 8/8` · `refusals 0` · `errors 0` · `limits 0`.

### 탐색이 고르지 않는 **이유가 달라졌다**

| | 수정 전 | 수정 후 |
|---|---|---|
| `set_monster` 점수 | `normal_summon` 과 **같았다** (둘 다 2400) | **낮다** |
| 무엇이 결정했나 | `canonical_state` 알파벳 순서 | **점수** |

같은 카드의 `normal_summon` − `set_monster` 점수차를 230건 전부 측정했다.

```
차이 분포: {1700: 129건, 1900: 101건}   ← 전부 그 카드의 공격력과 정확히 같다
전부 양수(소환이 항상 높다): True
```

즉 **평가가 두 수를 구별하게 되었고**, 선택이 순서가 아니라 점수로 정해진다.
"AI 가 세트를 쓴다" 로 적지 않는다 — 세트를 고르게 만들려면 뒷면 수비 표시가
실제로 막아 내는 값을 세는 항이 필요하고, 그 설계는 이 Phase 의 범위가 아니다.

---

## 8. Hidden Information · Safety

| 항목 | 결과 |
|---|---|
| 상대 뒷면의 정체 | **여전히 읽지 않는다** — `definition is None` → `unknown` ("모른다") |
| 상대 뒷면을 `withheld` 로 잘못 보내는가 | **아니다** — 순서 검사가 막는다 |
| 내 카드를 "모른다" 고 적는가 | **아니다** — 새 문장이 "세지 않았다" 다 |
| 가려진 정보를 공개해서 해결했는가 | **아니다** — 이미 공개인 `face_up` 만 읽는다 |
| 같은 관측 → 같은 점수 | **유지** (100회 반복 결과 1개) |
| Search simulation safety | **유지** — 기존 테스트 전부 통과 |
| RNG isolation | **유지** — 평가는 난수를 읽지 않는다 |

---

## 9. 성능 (§13)

| 항목 | 3-E-5 | 3-E-6 |
|---|---|---|
| Evaluation 1회 | 8.4 µs | **7.5 µs** |
| 결정당 시뮬레이션 | 2.11회 | 2.11회 |
| 결정 시간 평균 / p95 / 최대 | 5.56 / 25.51 / 94.30 ms | **5.35 / 25.51 / 93.65 ms** |

의미 있는 변화 없음. 뒷면 카드에서 `definition.atk` 를 읽지 않으므로 아주
조금 빠르지만 측정 잡음 수준이다.

---

## 10. 기존 테스트 4건이 깨졌다 — 원인과 처리

삭제·skip·완화 **0건**.

| 테스트 | 원인 | 처리 |
|---|---|---|
| `test_11_…counted_while_reported_as_excluded` (3-E-5) | **결함을 기록한 tripwire** — 고치면 깨지도록 쓴 것 | 뒤집었다. 차이가 정확히 1900 이고 보고가 참임을 주장. `test_11b` 추가(영합) |
| `test_17_the_evaluator_contradicts_itself…` (3-E-2) | 같은 모순을 기록 | 뒤집었다 — 모순의 **해소**를 적는다 |
| `test_20_search_does_not_select_a_monster_set_and_we_say_why` (3-E-2) | 점수가 같다고 주장 | **이유를 갱신.** 여전히 고르지 않지만 이제 **점수** 때문이다. 결론(고르지 않는다)은 그대로 |
| `test_12_an_unknown_attack_is_excluded_not_counted_as_zero` (3-C) | `_zone_attack` 반환값이 2 → 3 | 순수 기계적. 세 값으로 받고 `withheld == 0` 을 **추가** 주장 (두 카드가 앞면이므로). 기존 주장은 글자 하나 안 바뀜 |

### 고의 위반 5건 — 전부 잡혔다

| 위반 | 깨진 시험 |
|---|---|
| 되돌리기 (뒷면 공격력을 다시 셈) | 4건 |
| "세지 않았다" → "모른다" (내 카드를 모른다는 거짓) | 2건 |
| 상대 뒷면도 `withheld` 로 (관측 경계 위반) | 3건 — `test_10` 포함 |
| `monsters` 도 뒷면을 세지 않음 (과잉 수정) | 5건 |
| 뒷면에 임의 가중치 `+500` (§9 금지) | 5건 — `test_13`(토큰 검사) 포함 |

---

## 11. Tests

| | |
|---|---|
| Baseline | 3364 passed / 4 skipped |
| 총계 | **3365 passed / 4 skipped** (`test_11b` 추가) |
| Failed | **0** |
| Regression | **0건** |
| `engine/` 변경 | **0건** |

---

## 12. TODO

### 해결

| ID | 근거 |
|---|---|
| **STRUCTURAL-115** | **해결.** 두 상태가 구별되고(차이 = 공격력), 보고가 사실이고, 관측 경계가 유지된다 |

### 유지 — 하나도 건드리지 않았다

STRUCTURAL-102 · 107 · 109 · 110 · 116 · 118 · 120 · 122 · 123 · 124 · 125 ·
126 · 127 · 128 · 129 · 130 · 34 · 55 · 56 · 47 · 7 · 16 · 50 · 51.

### ⚠ 3-E-5 의 예측 하나가 틀렸다 — STRUCTURAL-130

Phase 3-E-5 는 *"115 를 고치면 130(`partial` 이 99.6% 참)이 함께 줄어든다"*
고 적었다. **측정해 보니 줄지 않았다.**

| | 3-E-5 | 3-E-6 |
|---|---|---|
| `partial` 비율 | 99.6% | **99.6%** (변화 없음) |
| "내 뒷면" 사유 | 93.3% | **56.1%** (줄었다) |
| "상대 패" 사유 | 71.8% | 71.8% |
| "묘지" 사유 | 거의 100% | 거의 100% |

"내 뒷면" 은 줄었지만 **구속 조건이 아니었다.** 묘지와 상대 패가 거의 모든
판에서 제외 항목을 만들므로 `partial` 은 그대로 늘 참이다. STRUCTURAL-130 은
**유지**되고, 그 예측은 정정한다.

### 새 TODO

| ID | 내용 | severity |
|---|---|---|
| **STRUCTURAL-131** | 앞면 **수비** 표시(`FACEUP_DEFENSE`)의 공격력은 여전히 세진다. 이번 수정은 `face_up` 을 기준으로 했고 position 의 공격/수비는 보지 않는다. 실제 플레이에서는 도달하지 않으므로(`CHANGE_POSITION` 미구현 — STRUCTURAL-108 의 나머지 절반) 지금 증상이 없지만, 플립 소환·표시 형식 변경이 들어오면 같은 종류의 불일치가 생긴다 | 🟡 DETAIL |

실제 코드에서 확인한 것만 적었다 (`Position.FACEUP_DEFENSE` 는 엔진 테스트의
직접 배치에서만 쓰인다).

---

## 13. 다음 Phase 제안 — 하나만

### **STRUCTURAL-130 — `excluded` 를 읽을 수 있게 만들기** 를 제안한다.

이번 Phase 가 보여준 것: `excluded` 가 **사실을 말하게 되었는데도** `partial`
은 여전히 99.6% 참이라 쓸 수 없다. 그리고 그 원인은 이제 **명확하다** —
"묘지를 세지 않았다"(설계상 의도)와 "상대 패를 모른다"(불완전정보의 본질)가
거의 모든 판에서 참이기 때문이다.

둘은 **성질이 다르다.**

```
설계상 세지 않는다   묘지 · 제외 존 — 되살릴 수단이 후보에 없다 (바뀔 수 있다)
본질적으로 모른다    상대 패 · 상대 뒷면 — 불완전정보 게임의 정의 (안 바뀐다)
세지 않기로 했다     내 뒷면 몬스터의 공격력 (이번 Phase 가 추가)
```

셋을 한 리스트에 몰아넣으면 "이 평가에서 **지금 문제가 되는** 누락이 있는가"
를 읽을 수 없다. 분류를 넣는 것은 **가중치 설계가 아니므로** 지금 할 수 있고,
STRUCTURAL-122·128·129 를 측정하려면 그 신호가 먼저 필요하다.

**STRUCTURAL-128 · 129 는 Depth-2 와 함께** 다루는 것이 여전히 맞다. 둘 다
"상대 차례를 어떻게 셀 것인가" 라는 같은 질문이고 Depth-1 에서는 증상이
드러나지 않는다.
