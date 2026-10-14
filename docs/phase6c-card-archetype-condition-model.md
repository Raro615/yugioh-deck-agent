# Phase 6-C — 카드 아키타입 슬롯 및 소환 조건 표현 구조 보완

> 요약: **자리는 이미 있었다.** 카드군(setcode)은 ``cards.cdb`` 에서
> ``Card.setcodes`` → ``CardDefinitionView.setcodes`` 로 관측까지 이미 실려
> 있었고, 후보를 거르는 ``CandidateSource.require`` 는 ``Condition`` 을 그대로
> 받는다. 없던 것은 **그 둘을 잇는 조건 하나**다. 그것을 만들었고
> (STRUCTURAL-77), 재서 보니 **"병목은 하나다" 라는 2-AN 의 결론이
> 뒤집혔다.** 그리고 조사 중에 **보고되지 않았던 두 번째 누락**을 찾았다 —
> ``TYPE_SPSUMMON`` 을 아무도 보지 않아 메인덱 몬스터 **344장**이 규칙상
> 일반 소환이 확실히 불가능한데 "모른다 · 제물만 있으면 될지도" 로 나가고
> 있었다. 🔴 **기르수의 일반 소환은 여전히 ``UNDETERMINED`` 다** — 막는 것이
> 카드군이 아니었다 (§8).

---

## 0. 🔴 Phase 6-A 진술 하나를 정정한다

Phase 6-A 보고서 §2 표에 이렇게 적혀 있다.

| 항목 | 수치 | 코드 위치 |
|---|---|---|
| 조건 술어 | 🔴 **3개뿐** — `IsMonster` · `IsSpellTrap` · `IsTurnPlayer` | `condition/model.py` |

**틀린 수다.** 그 파일을 AST 로 세면 이번 Phase **전에** 조건 하위 클래스가
**20개**였다.

```
$ python3 -c "import ast; ..."   # engine/condition/model.py
Always · UnimplementedRule · And · Or · Not · PhaseIs · IsTurnPlayer ·
LifePointsAtLeast · ZoneCountAtLeast · ZoneHasFreeSlot · CardIsInZone ·
CardIsFaceUp · IsMonster · IsSpellTrap · LevelAtLeast · AttackAtLeast ·
AttributeIs · ControllerIs · InAnyZone · NotMonster
```

내가 읽다가 **눈에 걸린 세 개를 세었다.** 측정이 아니라 인상이었고, 그래서
Phase 6-C 지시서 §5 가 "이름만 보고 카드 아키타입 필드라고 가정하지 않는다"
고 경고한 것이 정확했다.

**다만 결론은 바뀌지 않는다.** 20개 중 **카드군을 묻는 것은 0개**였다. 아래
§2 가 그 사실을 측정으로 다시 세운다. 틀린 것은 "3" 이라는 수이고, "아키타입
술어가 없다" 는 진술은 맞았다.

생산 코드에서 **실제로 만들어지는** 조건은 20개 중 **12개**다 (`Always` ·
`AttackAtLeast` · `AttributeIs` · `CardIsFaceUp` · `LevelAtLeast` ·
`LifePointsAtLeast` · `Not` · `Or` 는 만드는 자리가 없다). 이 수도 측정했고,
`IsSetCard` 를 더한 뒤에도 **12개 그대로다** — 새 조건을 만드는 production
자리가 아직 없기 때문이고, 그것이 §13 의 선행 조건이다.

---

## 1. 기존 카드 아키타입 및 조건 모델의 실제 구조

### 1.1 카드군은 **네 계층을 이미 통과한다**

```
cards.cdb  datas.setcode (64비트)
   │  16비트 × 4 로 풀기 — sources/official_db.py::unpack_setcodes
   ▼
core.card_model.Card.setcodes : list[int]
   │  값 복사 (원본을 참조로 들고 있지 않는다)
   ▼
engine.game_state_view.CardDefinitionView.setcodes : tuple[int, ...]
   │  관측에 실려 있다 (3-E-18 test_11 이 고정)
   ▼
engine.condition …  ← 🔴 **여기가 비어 있었다**
```

마지막 칸만 없었다. 3-E-18 감사가 그 사실을 **이름까지 적어** 고정해 두었다
(`test_15_no_archetype_judgment_is_made_from_an_unknown_setcode`): *"엔진에
``IsSetCard`` 류의 판정이 **아예 없다** … 생기는 날 이 시험이 깨지고, 그때
``UNKNOWN`` 을 돌려주는지 다시 봐야 한다."* 이번 Phase 가 그 날이다 (§5).

### 1.2 카드군 코드의 구조 — base 12비트 + subtype 4비트

`data/constants/archetype_setcode_constants.lua` 의 `SET_*` 상수를 세면:

| | 개수 |
|---|---:|
| `SET_*` 상수 전체 | **615** |
| 상위 4비트(subtype)를 쓰는 상수 | **136** |
| 한 base 를 둘 이상의 상수가 공유 | **78 base** |

```
SET_HERO            0x008      6장
SET_ELEMENTAL_HERO  0x3008    82장
SET_VISION_HERO     0x5008    10장
SET_EVIL_HERO       0x6008    19장
SET_MASKED_HERO     0xa008    13장
SET_DESTINY_HERO    0xc008    29장
```

카드 쪽 분포도 재 두었다 — 전체 14,127장 중 **6,221장(44.0%)** 이 코드를
하나도 갖고 있지 않고, 코드가 둘 이상인 카드가 **653장**, 최대 **4개**다
(16비트 × 4 패킹과 맞는다). base 가 0 인 코드는 상수에도 카드에도 **0개**다.

### 1.3 카드 종류 표현 — **빈자리가 없다**

`core/constants.py` 가 EDOPro 의 `TYPE_*` 비트 **27개 전부**를 이름으로 갖고
있고, `CardDefinitionView` 가 `type_names` 와 파생값 (`is_monster` ·
`is_spell` · `is_trap` · `is_xyz` · `is_link` · `is_pendulum` ·
`is_extra_deck` · `monster_level` · `rank` · `link_rating`) 을 함께 싣는다.

복합 유형이 실제로 유지되는지 재 봤다 (측정값, 신규 테스트가 고정한다).

| 조합 | 장수 | 예 |
|---|---:|---|
| `SYNCHRO` + `PENDULUM` | 8 | 사운드 워리어 록스 |
| `XYZ` + `PENDULUM` | 10 | 마제스펙터 드라코 |
| `FUSION` + `PENDULUM` | 13 | 패왕폭룡 스타브 베놈 윙 드래곤 |
| `TUNER` + `SYNCHRO` | 59 | 비서스＝암리타라 |
| `SPIRIT` | 42 | 아수라 |
| `GEMINI` | 45 | 매직 슬라임 |
| `UNION` | 40 | C－크러시 와이반 |
| `TOON` | 18 | 툰 앤틱 기어 골렘 |
| `FLIP` | 212 | 암흑의 성 |
| `SPSUMMON` | 344 | 용암 마신 라바 골렘 |

🔴 **그래서 §6-A(카드 유형 표현)에는 아무것도 더하지 않았다.** 더할 것이
없다는 사실을 신규 테스트 11개(parametrize)로 고정만 했다.

### 1.4 조건 모델의 확장 방식

`Condition` 은 frozen · slots dataclass 이고 하위 클래스가 넷을 채운다 —
`evaluate` · `canonical_state` · `to_dict` · `describe_ko`. 모르는 이유는
`unknown_reasons`, 없는 규칙 계층은 `missing_rules` 로 따로 나간다. 카드를
보는 조건은 전부 `_resolve_definition` 하나를 거치고, 그것이 **못 읽는 세
경우를 구분해서** 돌려준다 (문맥에 source 없음 · 관측에 없음 · 뒷면).
`IsSetCard` 도 같은 모양을 그대로 따랐다 — 새 규약을 만들지 않았다.

---

## 2. 확인된 표현 누락과 원인

### 누락 ① 카드군을 묻는 조건이 없다 (= STRUCTURAL-77)

원인은 **표현 불가**가 아니라 **연결 부재**였다. 값은 관측까지 와 있었고
(§1.1), 쓰는 통로도 있었다 (§4). 조건 클래스 하나가 없었다.

### 누락 ② `TYPE_SPSUMMON` 을 아무도 보지 않는다 (신규 발견)

`engine/summon_rules.py` 의 `NEVER_NORMAL_SUMMONABLE` 이
`{"RITUAL", "TOKEN"}` 이었다. `TYPE_SPSUMMON`(`0x2000000`, 종류 이름
`SPSUMMON`)이 빠져 있어서, 메인덱 몬스터 **344장**이 이렇게 나갔다.

```
NEEDS_TRIBUTE  262장   "레벨 N 이라 제물이 필요합니다"      ← 제물을 치러도 안 된다
UNDETERMINED    82장   "카드 자신의 제약이 있을 수 있습니다"  ← 제약을 이미 알고 있었다
FORBIDDEN        0장
```

🔴 **엔진이 이미 손에 들고 있는 사실을 쓰지 않은 것**이고, 그래서 "모른다"
가 과대 보고되고 있었다. 이것은 Phase 6-A 가 "효과 몬스터 4,311장의 소환
제약을 못 읽는다" 로 뭉쳐 적은 수 안에 섞여 있었다.

### 왜 텍스트를 읽지 않는가 — 양방향 측정

| 방향 | 결과 |
|---|---|
| `TYPE_SPSUMMON` 344장의 공식 한국어 원문이 「일반(통상) 소환할 수 없다」 를 말하는가 | **338장 그렇다.** 남은 6장은 한국어 텍스트가 아직 없거나(4장) 옛 표기다 (그레이트 모스 "특수 소환해야 한다" · 월 섀도우 "효과로 밖에 특수 소환할 수 있다") |
| 그 문구를 가졌는데 `TYPE_SPSUMMON` 이 **아닌** 메인덱 몬스터 | **11장** |

그 11장이 결정적이다. 전부 **다른 규칙**이다.

```
붉은 눈의 비룡        "이 카드의 효과를 발동하는 턴에, 자신은 통상 소환할 수 없다"
                                              → 그 턴 플레이어에게 걸리는 제약
체츠커                "자신 필드에 몬스터가 존재할 경우, 이 카드는 일반 소환할 수 없다"
                                              → 판에 따라 달라지는 조건부 제약
염옥마인 헬 버너      "공격력 2000 이상의 몬스터 1장을 제물로 바치지 않으면 …"
                                              → 제물 요구
레프티레스 서번트    "서로 몬스터를 일반 소환할 수 없다"
                                              → 양쪽에 걸리는 지속 효과
프린시퍼그            "… 자신 필드의 통상 소환할 수 없는 몬스터 1장을 대상으로 …"
                                              → **다른 카드**의 성질을 가리키는 문장
```

**문구로 세면 이 11장을 틀리게 접는다.** 타입 비트는 텍스트보다 **넓게 맞고**
(6장을 더 잡는다) **좁게 틀린다**(11장을 잡지 않는다). 그래서 타입 비트만
본다 — 지시서 §3-3 "제공되지 않는 정보를 임의로 추측하지 않는다" 와
§6-B "알 수 없거나 지원하지 않는 조건의 표현" 에 맞는 선택이다.

---

## 3. STRUCTURAL-77 의 정확한 위치 및 처리 결과

### 3.1 어느 계층의 문제였는가

지시서 §5-1 이 묻는 세 갈래로 답한다.

| 후보 | 판정 |
|---|---|
| 조건 AST 의 **노드** | ✅ **이것이다.** `engine/condition/model.py` 에 카드군 노드가 없었다 |
| 카드 **메타데이터** | ❌ 아니다. `CardDefinitionView.setcodes` 가 이미 있다 |
| **실행기** 로직 | ❌ 아니다. `CandidateResolver` 가 `Condition` 을 이미 받는다 |

§5-3 의 구분으로는 **"표현이 불가능한 문제"** 였다 — 판정기가 해석을 못 한
것이 아니라, 적을 수 있는 노드가 없었다.

### 3.2 2-AN 이 적은 "단독 병목 148장" 재측정 — 🔴 **결론이 뒤집혔다**

Phase 6-A §9 가 "먼저 재측정한다" 고 적어 둔 그 측정이다.
`tests/engine/test_real_card_coverage.py` 의 분류 기준("엔진에 계층이
있는가")에 따라 `Card.IsSetCard` 를 병목에서 빼고 다시 셌다.

| | 이전 | 이후 |
|---|---:|---:|
| 막는 것이 하나도 없는 카드 | 368 | **516** (+148) |

단독 병목 순위:

```
이전                             이후
148  Card.IsSetCard              28  Duel.SelectYesNo
 22  Duel.SetTargetCard          27  Duel.SetTargetCard
 19  Duel.ShuffleHand            27  Duel.ShuffleHand
 19  Duel.ChangePosition         23  Duel.ChangePosition
 16  Duel.SelectYesNo            22  Duel.GetMatchingGroupCount
```

늘어난 148 은 **`Card.IsSetCard` 하나만 걸려 있던 카드 수와 정확히 같다.**
계층을 하나 만들었고 수가 그만큼만 움직였다.

🔴 **그런데 2-AN 의 결론 "병목은 하나다" 가 더 이상 참이 아니다.** 1위가
2위의 7배였던 자리에 28 대 27 이 남았다. 상위 다섯을 **다 풀어도 127장**이고,
이미 막는 것이 없는 **516장**보다 적다. 즉 **다음 병목은 API 하나가 아니라
등재(손으로 적는 `EFFECT_LIBRARY` 정의)** 다. 그 판단의 근거가 이 수다.

그 148장이 `IsSetCard` 를 **어디에** 쓰는지도 재 두었다 — **145장이 선택 ·
검색 필터 안**이고 (`SelectMatchingCard` · `SelectTarget` ·
`GetMatchingGroup` · `IsExistingMatchingCard`), 40장은 `SetCondition` 블록도
갖고 있다. 둘 다 `Condition` 이 들어가는 자리이므로 같은 노드 하나로 덮인다.

### 3.3 "실행된다" 는 뜻이 아니다

516 을 커버리지로 읽지 않는다. 등재는 **16장** 그대로이고 실행되는 것은
**13장** 그대로다. 신규 테스트가 그것도 함께 고정한다
(`test_j_this_phase_turned_on_no_new_execution`).

---

## 4. 기존 모델을 재사용한 부분과 새로 확장한 부분

### 재사용 — **새로 만들지 않은 것들**

| 이미 있던 것 | 어떻게 썼는가 |
|---|---|
| `CardDefinitionView.setcodes` | 그대로 읽는다. 관측에 칸을 **더하지 않았다** |
| `_resolve_definition` | 못 읽는 세 경우를 그대로 물려받는다 |
| `ConditionResult` 3치 | `TRUE` / `FALSE` / `UNKNOWN` 그대로 |
| `CandidateSource.require: Condition` | 🔴 **필터 모델을 새로 만들 필요가 없었다** |
| `CandidateResolver` | 후보마다 `context.source` 를 바꿔 판정하고 `eligible` / `undecided` / `unchecked` 로 갈라 준다 |
| `And` · `Or` · `Not` | 결합과 부정이 이미 있다 (지시서 §6-C) |
| `_NormalSummonProcedure` → `assess_normal_summon` | 판정이 한 곳이므로 비트 하나를 더하면 검증기까지 **저절로** 간다 |
| `analysis` 의 `CardConstraint.setcodes` | 이미 `["ORCUST", "WORLD_LEGACY"]` 로 **읽어 두고 있었다**. 파서를 건드리지 않았다 |

### 확장 — 더한 것 **셋**

1. **`engine/archetype.py`** (신규 114줄) — 데이터 형식의 사실 하나.
   `matches_setcode(card_setcodes, query)` + `validate_setcode` + 마스크 3개.
2. **`engine.condition.IsSetCard`** — 조건 노드 하나.
3. **`NEVER_NORMAL_SUMMONABLE` 에 `"SPSUMMON"`** — 집합에 문자열 하나.

---

## 5. 변경한 파일 및 함수

| 파일 | 변경 | 줄 |
|---|---|---|
| `engine/archetype.py` | **신규** — `matches_setcode` · `validate_setcode` · `SETCODE_*_MASK` | +114 |
| `engine/condition/model.py` | `IsSetCard` 조건 + `archetype` import | +94 / −0 |
| `engine/condition/__init__.py` | `IsSetCard` 재노출 | +2 / −0 |
| `engine/summon_rules.py` | `NEVER_NORMAL_SUMMONABLE` 에 `SPSUMMON` + 순서 근거 주석 | +25 / −1 |
| `tests/engine/test_archetype_condition.py` | **신규** 회귀 테스트 48개 | +809 |
| `tests/engine/test_real_card_coverage.py` | 🔴 **재측정 — 368 → 516, 순위 결론 교체** | +55 / −25 |
| `tests/test_setcode_provenance_audit.py` | 🔴 **설계된 지뢰선 `test_15` 를 새 일로 교체** | +81 / −14 |
| `engine/__init__.py` | 2-AN 측정 기록에 「그 결론이 뒤집혔다」 를 덧붙임 (설명만) | +7 / −0 |
| `tests/test_engine_condition_none_contract_audit.py` | `engine/` 파일 수 65 → 66 | +5 / −1 |
| `tests/test_trigger_pipeline_dormant_audit.py` | `Duel` 폐쇄 57 → 58 | +8 / −2 |
| `tests/test_event_context_audit.py` | 조건 어휘 인구조사 + 🔴 원래 수가 틀렸던 것 기록 | +18 / −4 |

`data/` 는 **한 바이트도 바뀌지 않았다.** Lua 파일도 그대로다.

### 🔴 `test_15` 를 다시 쓴 이유 — 그 테스트가 스스로 지시했다

3-E-18 의 `test_15_no_archetype_judgment_is_made_from_an_unknown_setcode` 는
`engine/` · `agent/` 어디에도 `is_set_card` · `IsSetCard` ·
`matches_archetype` 라는 이름이 없음을 AST 로 단정했다. **그 단정은 쓰여진
시점에 맞았다** — 판정이 없었으므로 "모르는데 판정한다" 는 상태가 생길 수
없었다. 그리고 docstring 이 이어서 말했다: *"생기는 날 이 시험이 깨지고,
그때 ``UNKNOWN`` 을 돌려주는지 다시 봐야 한다."*

그래서 이름을 피해 가지 않았다. 조건 이름을 Lua 원문과 같은 `IsSetCard` 로
두어 지뢰선을 **일부러 밟고**, 테스트의 일을 "이름의 부재" 에서 **"세 답이
갈리는지"** 로 바꿨다 — 실제 판을 만들어 ① 내 패의 카드는 `TRUE`
② 상대 뒷면 카드는 `UNKNOWN` (이유까지) ③ 코드가 없는 카드는 `FALSE` 임을
확인한다. 같은 파일의 `test_16` (평가 · 탐색 · 정책에 setcode 가 들어가지
않았다) 은 **건드리지 않았고 그대로 통과한다.**

---

## 6. 새로운 데이터 계약과 기존 계약의 차이

### 🔴 **카드 데이터 계약은 바뀌지 않았다**

새 필드를 **하나도 더하지 않았다.** `Card` · `CardDefinitionView` ·
`CardInstance` · 캐시 서명 · `provenance` 모두 그대로다. 이것이 §9(호환성)의
근거 전부다.

### 바뀐 것 하나 — 판정 계약

```
assess_normal_summon(TYPE_SPSUMMON 카드)
    이전: NEEDS_TRIBUTE(제물 수 포함) 또는 UNDETERMINED  → 검증기에서 UNKNOWN
    이후: FORBIDDEN                                      → 검증기에서 INVALID
```

방향이 **"모른다 → 안 된다"** 한쪽뿐이다. `ORDINARY` 는 542장 그대로이므로
**허가가 하나도 늘지 않았다** (§7 표). 지시서 §3-7 · §13-5 를 어기지 않는다.

### 새로 생긴 조건 노드의 계약

```python
IsSetCard(setcodes: tuple[int, ...], instance: InstanceId | None = None)
```

- **목록 중 하나라도** 맞으면 참 — 스크립트의 `IsSetCard({A, B})` 와 같다.
- `to_dict()` → `{"kind": "is_set_card", "setcodes": ["0x11b", "0xfd"]}`
- `canonical_state()` → `("is_set_card", (0x11b, 0xfd), None)`
- 빈 목록 · `list` · 코드일 수 없는 값(0 · `0x1000` · `0x10000` 초과)은
  **생성 시점에 거부**한다. 조용히 통과시키면 "아무 카드와도 맞지 않는 조건"
  이 되어 "속하지 않는다" 와 구별되지 않는다.

### 판정 규칙과 그 근거

하위 12비트는 **같아야** 하고, 질의한 상위 4비트는 카드 쪽에 **포함**되어야
한다. 추측이 아니라 두 가지로 재서 정했다.

1. **데이터 구조** — §1.2 의 615 / 136 / 78.
2. 🔴 **공식 카드 텍스트** — 엘리멘틀 히어로 에어맨(40044918)의 공식 한국어
   원문이 「덱에서 "히어로" 몬스터 1장을 패에 넣는다」 이고, 그 스크립트는
   `IsSetCard(SET_HERO)` = `0x008` 로 묻는다. 그런데 엘리멘틀 히어로 카드가
   들고 있는 코드는 `0x3008` 이다. **포함으로 읽지 않으면 이 카드의 공식
   효과가 엘리멘틀 히어로를 한 장도 찾지 못한다.** 반대 방향은 성립하지
   않아야 한다 — `0x3008` 로 물었을 때 `0x008` 만 가진 카드(엑스트라 히어로
   원더 드라이버 · 히어로의 유산)가 걸리면 「엘리멘틀 히어로」 가 아닌 카드를
   그렇다고 말하는 것이다. `SET_HERO` 를 질의하는 스크립트가 **49개** 있다.

덧붙여, cdb 의 setcode 는 **「룰상 ~ 카드로도 취급한다」 까지 담고 있다.**
미라클 엑스클루더(30875635)는 이름에 "히어로" 가 없지만 `0x3008` 을 갖고
있고, 공식 원문이 「이 카드명은 룰상 "엘리멘틀 히어로" 카드로도 취급한다」
라고 말한다. 즉 카드 **자신**이 선언하는 추가 소속은 이미 데이터에 있다.

---

## 7. 카드 유형 및 조건 표현 테스트 결과

신규 `tests/engine/test_archetype_condition.py` — **48개 전부 통과.**

```
$ python3 -m pytest tests/engine/test_archetype_condition.py -p no:randomly -q
48 passed in 4.06s
```

| 묶음 | 개수 | 무엇을 지키는가 |
|---|---:|---|
| A. 표현 | 5 | base 일치 · subtype 포함 · 코드 없음은 거짓 · 불가능한 값 거부 · 마스크 불변식 |
| B. 직렬화 | 3 | 같은 조건은 같은 표현 · 다른 카드군은 다른 표현 · 설명이 코드를 다 적는다 |
| C. 파싱 | 2 | `analysis` 가 이미 이름으로 읽는다 · 🔴 **이름을 조건으로 옮기는 자리가 없다** |
| D. 판정 | 6 | TRUE / FALSE / 목록 중 하나 / 계층 양방향 / 마법도 카드군을 갖는다 |
| E. 모름 | 4 | 뒷면 · 가려진 존 · source 없음 → `UNKNOWN`, 그리고 결합에서 접히지 않음 |
| F. 전달 | 3 | `CandidateResolver` 실제 경로 · 가려진 존이 `unchecked` 로 남음 · 판을 안 건드림 |
| G. 카드 유형 | 13 | 네 기본 종류 + 복합 유형 11조합 + `NEVER_NORMAL_SUMMONABLE` |
| H. 특수 소환 몬스터 | 4 | `FORBIDDEN` · 검증기 거절 · 레벨보다 먼저 · **허가 0 증가** |
| I. 기르수 | 4 | 유형 인식 · 여전히 `UNDETERMINED` · 이유가 카드군이 **아님** · 달라진 것 하나 |
| J. 경계 | 4 | 카드 ID 하드코딩 0 · 규칙이 한 곳 · 런타임 카드군 칸 없음 · 실행 증가 0 |

### 변이 시험 — 내 테스트가 실제로 잡는가 (9종, 전부 잡힘)

| 변이 | 결과 |
|---|---|
| M1 subtype 포함 → 일치 | **5 failed** |
| M2 base 검사 삭제 | **6 failed** |
| M3 정의 못 읽을 때 `FALSE` | **5 failed** |
| M4 목록을 `any` → `all` | **2 failed** |
| M5 코드 검증 삭제 | **1 failed** |
| M6 `SPSUMMON` 되돌리기 | **5 failed** |
| M7 금지 검사를 레벨 뒤로 | **6 failed** |
| M8 카드군 없는 카드를 `UNKNOWN` 으로 (지나친 신중) | **3 failed** |
| M9 `instance` 지목 무시 | **1 failed** |

M8 을 일부러 넣었다 — "모르겠으면 `UNKNOWN`" 쪽으로 틀리는 것도 **틀린
것**이고 (6,221장이 `UNKNOWN` 이 되어 조건이 쓸모없어진다) 그것도 잡혀야
한다.

### 🔴 내가 쓴 테스트가 내 **단정 두 개**를 잡았다

1. `test_c` 를 처음에 "엔진은 `sources` 를 import 하지 않는다" 로 썼다.
   **틀렸다** — `engine/vocabulary.py:28` 이 `ScriptConstants` 를 런타임에
   import 한다. 표는 엔진 손에 닿는 거리에 있고, 없는 것은 표가 아니라
   **옮기는 코드**다. 테스트를 그 사실로 다시 썼다 (§13).
2. `test_j` 의 숫자 범위 단정이 **마스크 자신**(`0xFFF`=4095 ·
   `0xF000`=61440)을 패스코드로 잡았다. 세려던 것만 세도록 좁혔다.

### 일반 소환 판정 재분포 (메인덱 몬스터 7,067장)

| | 이전 | 이후 | 차이 |
|---|---:|---:|---:|
| `ORDINARY` (허가) | 542 | **542** | **0** |
| `FORBIDDEN` (거절) | 148 | **492** | +344 |
| `NEEDS_TRIBUTE` | 2,066 | **1,804** | −262 |
| `UNDETERMINED` | 4,311 | **4,229** | −82 |

**테스트 통과가 게임 규칙의 완전성을 뜻하지 않는다.** 이 표는 "엔진이 각
카드를 어떻게 분류하는가" 일 뿐이고, 분류가 맞다고 그 소환을 **실행할 수
있다는 뜻이 아니다** — 제물 절차는 여전히 없다.

---

## 8. 기르수 회귀 결과

| 항목 | 결과 |
|---|---|
| 카드 유형 인식 | ✅ 몬스터 · 효과 · 메인덱 · 레벨 4 · `setcodes == (0x11b, 0x10c)` |
| 일반 소환 판정 | 🔴 **`UNDETERMINED` 그대로** |
| 그 이유 | `missing_rule = "summoning-condition (카드 텍스트의 소환 제약)"` |
| 검증기 | `UNKNOWN` / `RULE_NOT_IMPLEMENTED`, `permits_execution = False` |
| 이번 확장의 영향 | **판정에 0** |

🔴 **막는 것이 카드군이 아니었다.** Phase 6-A 가 "기르수 ①이 바로
STRUCTURAL-77 이다" 라고 적은 것은 **효과 ①의 대상 필터**에 대해서는 맞지만,
**일반 소환 판정**에 대해서는 아니다. 기르수는 효과 몬스터이고, 룰북이
"most Effect Monsters (**unless they have a specific restriction**)" 라고만
말하므로 그 제약을 카드 텍스트에서 읽는 계층이 없는 한 `UNDETERMINED` 다.
그것은 이번 범위가 아니고, 고쳤다고 말하지도 않는다.

**달라진 것은 정확히 하나다.** 기르수 ①의 「"오르페골" 또는 "성유물" 카드를
덱에서 묘지로」 라는 필터를 이제 **구조로 적을 수 있다.**

```python
CandidateSource(
    zones=frozenset({Zone.DECK}),
    owner=PlayerRef.CONTROLLER,
    require=IsSetCard((SET_ORCUST, SET_WORLD_LEGACY)),
)
```

적을 수 있다는 것과 **그 효과가 실행된다는 것은 다른 말이다.**
`entry_for(69811710) is None` — 기르수는 `EFFECT_LIBRARY` 에 등재되어 있지
않고, 등재하려면 `TRIGGER_O` 모양의 정의가 필요하다 (16/16 이 여전히
`ACTIVATE`). 신규 테스트가 그 두 사실을 **한 시험 안에서** 함께 고정한다.

---

## 9. 기존 데이터 파이프라인과의 호환성

| 요소 | 영향 |
|---|---|
| 기존 카드 데이터베이스 (`data/cards.cdb`) | **없음.** 새 필드 0개, 재생성 0건 |
| 한국어 카드명 데이터 (`data/ko/`) | **없음.** 읽지도 않는다 |
| 기존 Lua 스크립트 (`c*.lua` 12,968개) | **없음.** 삭제 · 이동 · 파서 변경 0건 |
| 카드 효과 분석 결과 | **없음.** `analysis` 를 한 줄도 바꾸지 않았다 |
| 증분 업데이트 파이프라인 | **없음.** 캐시 서명을 올릴 이유가 없다 (파서 불변) |
| CDB · Lua 부분 가용성 | **유지.** `setcodes` 는 cdb 쪽 필드이고, Lua 가 없어도 빈 튜플이 아니라 cdb 값이 온다 |
| 카드 ID 기반 연결 | **없음.** 카드 ID 를 보는 코드를 더하지 않았다 |
| 새 카드가 들어올 때 | 🔴 **코드 수정 없이 따라온다.** 새 카드군은 `SET_*` 상수와 cdb setcode 로 들어오고, 판정 규칙은 비트 구조 하나다. 카드별 분기가 없으므로 추가 작업이 없다 |

새 필드를 만들지 않았으므로 "기존 데이터가 없는 경우" 라는 상태 자체가
생기지 않는다. 카드가 코드를 안 가지면 그것은 결손이 아니라 **44.0% 가
그런 정상 상태**다.

---

## 10. Phase 6-B EventJournal 회귀 결과

```
$ python3 -m pytest tests/engine/test_event_journal_integration.py -p no:randomly -q
14 passed
```

이번 Phase 는 `journal.py` · `action_execution.py` · `spell_activation.py` ·
`duel.py` · `agent/simulation.py` 를 **한 줄도 건드리지 않았다.** 조건은
판을 읽기만 하므로 기록할 변화를 만들지 않는다
(`test_f_evaluating_the_condition_does_not_touch_the_board` 가 `state_hash()`
불변을 고정한다).

---

## 11. 수행한 테스트와 통과 · 실패 수

| 범위 | 명령 | 결과 |
|---|---|---|
| 엔진 전체 | `pytest tests/engine -p no:randomly -q` | ✅ **2,890 passed** (1:17) |
| ↳ 이번 Phase 이전 | 같은 명령 | 2,842 passed |
| 신규 카드군 테스트 | `pytest tests/engine/test_archetype_condition.py` | ✅ **48 passed** |
| 커버리지 재측정 | `pytest tests/engine/test_real_card_coverage.py` | ✅ 15 passed (고정값 2개 갱신 후) |
| setcode 출처 감사 | `pytest tests/test_setcode_provenance_audit.py` | ✅ 19 passed (`test_15` 교체 후) |
| 일반 소환 | `pytest tests/engine/test_normal_summon.py` | ✅ 통과 |
| EventJournal | `pytest tests/engine/test_event_journal_integration.py` | ✅ 14 passed |
| 변이 시험 9종 | 위 네 파일 144개 | ✅ 전부 잡힘 |
| `tests/engine` 밖 전체 | 4묶음 + `agent`·`rules`·`rulings` | 아래 §11.1 |

차이 **+48** 은 전부 신규 파일이다 — `tests/engine/` 안에서 **삭제 0건 ·
skip 추가 0건 · assertion 약화 0건**이고, 수정은 `test_real_card_coverage.py`
의 고정값 2개뿐이다 (§3.2 · §5).

### 11.1 `tests/engine` 밖 전체 스위트 — 묶음으로 끝까지

6-B 에서 배운 대로 처음부터 **묶음으로** 쓸었다 (`tests/*.py` 91개를 4묶음).
한 파일에 6~7분 걸리는 감사가 여럿이라 단일 실행은 30분 상한에서 죽는다.

| 범위 | 1차 | 고친 뒤 |
|---|---|---|
| 묶음 0 (23파일) | 614 passed (16:35) | ✅ **614 passed** (17:07) |
| 묶음 1 (23파일) | 586 passed + **1 failed** (8:52) | ✅ **587 passed** (8:54) |
| 묶음 2 (23파일) | 558 passed + **1 failed** (13:51) | ✅ **559 passed** (14:12) |
| 묶음 3 (22파일) | 516 passed + **1 failed** (15:41) | ✅ **517 passed** (16:12) |
| `engine`+`agent`+`rules`+`rulings` | 2,890 / 529+4skip | ✅ **3,419 passed, 4 skipped** (6:09) |

**최종 실패 0건.** 묶음 셋을 고친 뒤 **전부 다시 돌렸다** — 고친 파일만
돌리지 않았다. 그 사이에 `engine/__init__.py` 와 `engine/condition/model.py`
의 설명을 더 손봤기 때문이고, 줄 수를 고정한 감사가 있을 수 있어 다시 쓸어야
했다.

### 11.2 밖에서 난 3건은 전부 "고정된 수치가 움직인 것"이다 (프로덕션 결함 0건)

| 파일 | 테스트 | 움직인 고정값 | 왜 움직였는가 |
|---|---|---|---|
| `test_engine_condition_none_contract_audit.py` | `test_01` | `engine/` 파일 수 65 → **66** | `engine/archetype.py` 가 생겼다. 그 파일에 `Condition` 칸은 **없으므로** 감사의 두 집합은 그대로다 — 분모만 움직였다 |
| `test_trigger_pipeline_dormant_audit.py` | `test_06` | `Duel` import 폐쇄 57 → **58** | `engine.condition.model` 이 `engine.archetype` 을 import 한다. 🔴 휴면 모듈 넷(`trigger_chain`·`trigger_order`·`timing`·`event_pipeline`)은 **그대로 폐쇄 밖**이다 — 수가 는 것이 트리거가 켜졌다는 뜻이 아니다 |
| `test_event_context_audit.py` | `test_01` | 조건 어휘 인구조사 | `IsSetCard` 추가. 🔴 **그러면서 그 감사가 적어 둔 수가 원래 틀렸던 것도 드러났다** — docstring 은 "16개" 라고 했는데 집합을 세면 **15개**였다. 카드군 조건이 들어와 이제 진짜로 16개다. 감사의 결론(사건을 묻는 술어가 0개)은 그대로다 |

세 건 모두 **이 Phase 가 의도한 변화의 그림자**이고, 어느 것도 판정이
틀렸다는 신호가 아니다.

---

## 12. 남아 있는 구조적 차단 문제

| | 문제 | 왜 이번에 안 했는가 |
|---|---|---|
| 1 | 🔴 **`analysis` 의 카드군 이름 → 엔진 조건** 을 옮기는 계층이 없다 | 새 계층이고 §11 범위 밖. 위치는 확정했다 (§13) |
| 2 | **효과로 더해지는 카드군을 표현할 수 없다** (STRUCTURAL-76) | 지속 효과 계층이 아예 없다. 칸만 만들면 쓰는 자리가 없는 죽은 필드가 된다 |
| 3 | **효과 몬스터의 소환 제약을 못 읽는다** — `UNDETERMINED` 4,229장 | 카드 텍스트에서 읽어야 하고, §2 의 11장이 그 위험을 보여 준다 |
| 4 | **제물 소환 절차가 없다** — `NEEDS_TRIBUTE` 1,804장 | §11 "특수 소환 전 종류의 실행 구현" 금지 |
| 5 | **특수 소환 절차가 없다** — 융합 · 싱크로 · 엑시즈 · 링크 | 같음 |
| 6 | **등재가 16장** — `TRIGGER_O` 모양 정의가 0개 | §11 "개별 카드 효과 실행 대량 추가" 금지 |
| 7 | `EFFECT_LIBRARY` 가 `IsSetCard` 를 쓰는 정의를 하나도 안 갖고 있다 | 6 과 같은 이유. 테스트가 그 사실을 고정한다 |
| 8 | **`OperationKind` 에 `TOKEN` 이 없다** (기르수 ②가 토큰 2개를 만든다) | 6-A 가 이미 기록. 이번 범위 밖 |

### 이번에 **발견했지만 고치지 않은 것** — 보고만 한다

🔴 **`core/card_repository.py::by_setcode` 는 정확 일치 사전이다.**

```python
self._by_setcode: dict[int, list[int]] = defaultdict(list)   # :166
...
def by_setcode(self, setcode: int) -> list[Card]:            # :478
    return [self._cards[i] for i in self._by_setcode.get(setcode, [])]
```

그래서 `by_setcode(0x008)`(SET_HERO) 로 찾으면 **엘리멘틀 히어로 82장 ·
데스티니 히어로 29장 등 153장이 나오지 않는다.** 엔진 조건은 이제 포함
관계를 알지만 **검색 · 덱 빌더 계층은 모른다.**

고치지 않은 이유: `archetype()` 은 `/search` 와 `/deck` 의 결과를 직접
바꾸고, 그 두 명령의 출력 변경은 지시서 §11 이 금지한 범위에 닿는다
(`/combo` 출력 변경 금지와 같은 성질). 수정 위치는 위 두 줄이고, 고친다면
`matches_setcode` 를 쓰는 조회로 바꾸면 된다 — **사용자 승인을 기다린다.**

---

## 13. Phase 6-D 의 선행 조건과 권장 범위

### 선행 조건 — **딱 한 자리**

`analysis` 가 읽어 둔 것과 엔진이 쓸 수 있는 것 사이의 변환이다.

```
analysis.effect_model.CardConstraint.setcodes == ["ORCUST", "WORLD_LEGACY"]
                       │  ← 🔴 이 화살표가 production 에 없다
                       ▼
engine.condition.IsSetCard((0x11b, 0xfe))
```

측정한 사실 셋 (신규 `test_c` 가 고정):

1. 표는 있다 — `ScriptConstants.setcode("ORCUST") == 0x11b`.
2. 엔진이 그 표에 닿는다 — `engine/vocabulary.py:28` 이 런타임에 import 한다.
   다만 `EngineVocabulary` 는 `LOCATION_` · `POS_` · `PHASE_` 등만 묶음으로
   내보내고 **`SET_` 묶음은 내보내지 않는다** (`ScriptConstants` 가
   `setcodes` 를 `others` 와 따로 두기 때문).
3. production 어디에도 `IsSetCard` 를 **만드는** 자리가 없다.

그래서 6-D 의 첫 걸음은 ①`EngineVocabulary` 에 카드군 묶음을 더하고
②`CardConstraint` → `Condition` 컴파일러를 두는 것이다. `model.py` 의
머리말이 이미 그 방향을 적어 두었다 — *"분석이 실행을 낳지, 실행이 분석을
바꾸지 않는다."* 🔴 **이번 Phase 가 그것을 미리 만들지 않은 이유**는 쓰는
자리가 없어서다 (지시서 §3-2 · §10).

### 권장 범위 — Phase 6-D: `TRIGGER_O` 효과 정의의 첫 사례

1. **목표**: `EFFECT_LIBRARY` 에 `TRIGGER_O` 모양 정의 **1개**. 16/16 이
   `ACTIVATE` 이므로 모양 자체가 처음이다.
2. **선행**: 6-B(기록 배선) ✅ · 6-C(카드군 조건) ✅ · 위 컴파일러 또는
   손으로 적은 정의 하나.
3. **실제 카드**: 기르수 ① — `EVENT_SUMMON_SUCCESS` 에 반응해 덱에서
   `IsSetCard((SET_ORCUST, SET_WORLD_LEGACY))` 를 만족하는 1장을 묘지로.
   이제 **그 필터를 적을 수 있다**는 것이 이번 Phase 의 결과다.
4. **위험**: 🔴 몬스터 효과 스펠 스피드가 `UNKNOWN` 이다
   (`activation_timing.py:33-69` 의 입도 불일치). 그 한 줄이 6-D 의 선행
   과제로 분리할 가치가 있다.
5. **완료 판정**: 등재된 유발 효과가 ① 사건에 반응해 후보가 되고 ② 조건이
   `FALSE` 면 후보가 **안 되고** ③ `UNKNOWN` 이면 체인에 **안 올라가고**
   그 이유가 기록으로 남는다.

🔴 **Phase 6-D 를 자동으로 시작하지 않는다.** 사용자 검토를 기다린다.

---

## 14. Git 커밋 및 푸시 결과

브랜치 `claude/pensive-goodall-te1egy` 에만 올렸다. 기존 커밋을 amend ·
rewrite · force push 하지 않았다.

| 커밋 | 내용 |
|---|---|
| `68ad6a7` | 프로덕션 — `engine/archetype.py` · `IsSetCard` · `SPSUMMON` · 측정 기록 갱신 |
| `cbd6bcd` | 회귀 테스트 48개 + 움직인 고정값 5건 |
| (아래) | 이 보고서 |

---

## 결론 — 다음 단계가 활용할 수 있는 표현 모델

```python
from engine.archetype import matches_setcode          # 데이터 형식의 사실
from engine.condition import IsSetCard, And, Or, Not  # 조건 노드
from engine.cost.choice import CandidateSource        # require= 로 후보 거르기
from engine.summon_rules import assess_normal_summon  # 네 갈래 소환 판정
```

- 카드군을 **묻고**, 결합하고, 후보를 거를 수 있다. 세 답이 갈린다.
- 카드 유형은 **원래부터 다 표현된다** — 복합 유형 포함.
- 특수 소환 몬스터 344장이 "모른다" 에서 **"안 된다"** 로 바로잡혔고,
  허가는 하나도 늘지 않았다.
- 🔴 **아직 못 하는 것**: 카드군 이름을 조건으로 자동 변환 · 효과로 더해진
  카드군 · 효과 몬스터의 소환 제약 · 제물/특수 소환 절차 · 유발 효과 등재.

갈라테아가 실행할 수 없는 행동을 실행할 수 있다고 주장하게 만들지 않았다.
움직인 수는 전부 "모른다 → 안 된다" 와 "적을 수 없다 → 적을 수 있다" 두
방향뿐이다.
