# Phase 3-E-2 — SET Action Space

- **Base commit**: `49bc897` (Phase 3-E-1 — ATTACK Action Space 정식 검증)
- **Branch**: `claude/pensive-goodall-te1egy`
- **결과**: 3165 → **3245 passed, 4 skipped** · 새 테스트 80개 · 회귀 0건
- **`engine/` 변경**: 승인된 5건 (아래 §2) — 새 파일 1개 + 기존 파일 3개

---

## 1. 네 단계를 따로 증명했다 — 그리고 셋만 참이다

| 단계 | SET SPELL/TRAP | SET MONSTER |
|---|---|---|
| **① 할 수 있다** (legal_actions) | ✅ `test_02` | ✅ `test_02` |
| **② 내다볼 수 있다** (simulate) | ✅ `test_08` | ✅ `test_08` |
| **③ AI 가 고른다** | ✅ `SearchPolicy` 가 고른다 (`test_18`) | ❌ **탐색도 규칙 기반도 고르지 않는다** (`test_20`·`test_21`) |
| **④ 실제로 실행된다** | ✅ `test_19` | ✅ **난수 정책으로** (`test_22`) |

③ 의 ❌ 를 숨기지 않는다. `SET_MONSTER` 는 **후보에 오르고 시뮬레이션도 되고
실행도 되지만**, 현재 평가 함수에서는 같은 카드의 일반 소환과 **점수가 같거나
낮아서** 탐색·규칙 기반이 한 번도 고르지 않는다. 이유는 §6 에 측정값과 함께
적었다. 세트에 가산점을 넣어 "고르게" 만들지 않았다 (§9 · §15 금지).

---

## 2. Engine 변경 (승인된 5건)

| # | 파일 | 무엇을 | 왜 |
|---|---|---|---|
| 1 | `engine/set_card.py` **(신규)** | `CardSet` 델타 · `SetExecutor` · 두 핸들러 · 두 절차 | 세트를 **소환이 아닌 것**으로 실행할 자리가 없었다 |
| 2 | `engine/summon.py` | `SummonProcedure.summon` 을 `SummonKind \| None` 로 | `summon=None` 이 "이 배치는 소환이 아니다" 를 **타입으로** 적는다 |
| 3 | `engine/summon.py` | `duel_executor()` 에 두 세트 핸들러 등록 | ADR-006 — 등록하지 않은 것은 UNKNOWN |
| 4 | `engine/action_validation.py` | `_set_monster` 에 페이즈 · 소환권 · 절차 요구 3개, `_set_spell_trap` 에 페이즈 요구 1개, `_COMPLETE_RULES` 에 두 종류 추가 | UNKNOWN 이 가리고 있던 요구를 **올리기 전에** 채웠다 |
| 5 | `engine/duel.py` | 패의 카드마다 세트 후보도 생성 | 후보에 오르지 않으면 AI 가 고를 수 없다 |

새로 만들지 **않은** 것: 배치 절차(빈 칸 고르기 · 컨트롤러 · 착지 확인)는
`SummonProcedure` 를 표시 형식만 바꿔 그대로 썼다. 소환권도 기존
`RuleActionKind.NORMAL_SUMMON` 을 그대로 쓴다.

---

## 3. STRUCTURAL-113 — SET ≠ MonsterSummoned

> RULE-SUMMON-010 — "To play a Monster Card from your hand in face-down
> Defense Position is called a Normal Set. A monster Normal Set on the field
> is **NOT considered Summoned**."

그래서 세 가지가 **서로 다른 사실**로 남는다.

```
MonsterSummoned(NORMAL)    일반 소환
MonsterSummoned(SPECIAL)   특수 소환
CardSet                    세트 — 소환이 아니다
```

`SummonKind` 에 `SET` 을 더하는 길은 택하지 않았다 — 그 열거형의 이름이
"어떤 **소환**인가" 이므로 같은 범주 오류다. 대신 `SummonProcedure.summon` 을
nullable 로 만들어 세트 절차가 "나는 소환이 아니다" 를 선언한다.

`CardSet` 이 **주장하지 않는 것**:

| 칸 | 값 | 왜 |
|---|---|---|
| `operation` | `MOVE` | `OperationKind` 는 **효과**의 어휘다. `DESTROY`·`SEND_TO_GRAVE` 를 고르면 거짓이 된다. 무슨 일인지는 **델타의 타입**이 말한다 |
| `reason_names` | `()` | 세트는 아무것도 파괴하지 않고 묘지로 보내지 않는다. `EFFECT` 를 적으면 트리거 계층이 세트를 "효과로 움직였다" 로 읽는다 |
| `to_dict()["summoned"]` | `False` | 기록을 읽는 쪽에서 소환과 구별된다 |

**고의 위반으로 확인**: `"summoned": True` 로 바꾸면 `test_05`·`test_26` 이 깨진다.

---

## 4. STRUCTURAL-114 — `_COMPLETE_RULES` 를 넓게 풀지 않았다

UNKNOWN 이 가리고 있던 사실이 하나 있었다: **세트에 페이즈 검사가 없었다.**
`SET_MONSTER` 는 Phase 2-B-2 부터 `_summon_like` 하나만 썼고(턴 플레이어 ·
컨트롤러 · 패 · 몬스터 · 빈 칸) 그대로 UNKNOWN 이었으므로, 메인 페이즈 밖
세트가 허가되지 않는 이유는 "검사했다" 가 아니라 "몰랐다" 였다.

그래서 **올리기 전에 채웠다.** 올린 뒤에 채우면 그 사이에 배틀 페이즈 세트가
허가된다.

| 종류 | 더한 요구 |
|---|---|
| `SET_MONSTER` | `PhaseIs(MAIN1, MAIN2)` · `_NormalSummonRightAvailable` · `_NormalSummonProcedure` |
| `SET_SPELL_TRAP` | `PhaseIs(MAIN1, MAIN2)` |

올린 것은 **둘뿐**이다. `CHANGE_POSITION`·`ACTIVATE_CARD`·`ACTIVATE_EFFECT` 는
그대로 UNKNOWN 이다 (`test_19`).

**고의 위반으로 확인**: `_set_monster` 에서 `PhaseIs` 를 지우면 engine 쪽
`test_12` 4건과 agent 쪽 `test_06`·`test_24` 가 깨진다.

---

## 5. 소환권은 하나다 (RULE-SUMMON-009)

> "You can only Normal Summon **OR** Normal Set once per turn."

`RuleActionKind` 의 기존 설명이 이미 결정해 둔 것을 그대로 따랐다 — 세트도
`RuleActionKind.NORMAL_SUMMON` 이라는 **같은 이름으로** 기록한다. 이름을
나누면 한 턴에 소환과 세트를 둘 다 할 수 있게 된다.

| 사실 | 테스트 |
|---|---|
| 몬스터 세트가 소환권을 쓴다 | `test_08` |
| 세트 → 소환, 소환 → 세트 **양쪽 순서**에서 두 번째가 거절된다 | `test_09` |
| 마법 · 함정 세트는 권리를 쓰지 않는다 (몇 장이든) | `test_10` |
| 권리는 턴마다 새로 생긴다 | `test_11` |
| 권리를 쓰면 **후보 목록에서** 몬스터 세트가 사라진다 | agent `test_05` |

**고의 위반으로 확인**: `spends_summon_right` 를 `False` 로 바꾸면 6건이 깨진다.

---

## 6. 측정 — 네 가지를 따로 센다

8개 씨앗 · 같은 덱 · 끝까지 굴린 듀얼. **`SET_MONSTER` 와 `SET_SPELL_TRAP` 을
합치지 않았고**, 후보 · 선택 · 실행을 따로 세었다.

### SET MONSTER

| 조합 | legal | selected | executed |
|---|---|---|---|
| search vs search | 318 | **0** | 0 |
| search vs rule | 314 | **0** | 0 |
| rule vs rule | 295 | **0** | 0 |
| first-legal vs first-legal | 215 | **0** | 0 |
| random vs random | 621 | **88** | 88 |

### SET SPELL / TRAP

| 조합 | legal | selected | executed |
|---|---|---|---|
| search vs search | 113 | **51** | 51 |
| search vs rule | 453 | **21** | 21 |
| rule vs rule | 599 | **0** | 0 |
| first-legal vs first-legal | 82 | **36** | 36 |
| random vs random | 233 | **77** | 77 |

### 판에 실제로 나타난 표시 형식

| 조합 | positions |
|---|---|
| search / rule / first-legal | `FACEUP_ATTACK` 만 |
| random | `FACEUP_ATTACK`, **`FACEDOWN_DEFENSE`** |

### 왜 탐색이 `SET_MONSTER` 를 고르지 않는가

같은 카드의 일반 소환과 **평가 점수가 정확히 같다.**

```
normal_summon  heuristic 2600  terms {atk 1900, monsters 500, hand 200}
set_monster    heuristic 2600  terms {atk 1900, monsters 500, hand 200}
                               excluded ("내 뒷면 카드 1장은 값을 매기지 않았다",)
```

동점이면 `SearchCandidate.ordering_key()` 의 마지막 항인 `canonical_state` 가
가르고, `"normal_summon" < "set_monster"` 이므로 결과가 한쪽으로 고정된다.

### 왜 규칙 기반이 고르지 않는가

두 세트가 **서로 다른 이유로** 진다 (`test_21`).

| 후보 | 총점 | 이유 |
|---|---|---|
| `normal_summon` | 11,901,600 | 세 규칙이 모두 값을 준다 |
| `set_monster` | 1,901,600 | `summon-before-ending` 만 값을 주지 않는다 (`BOARD_KINDS = {NORMAL_SUMMON}`) — 차이가 정확히 `BOARD_PRESENCE` = 10,000,000 |
| `set_spell_trap` | 0 | 어떤 규칙도 보지 않는다. `END_PHASE`(0)와 동점이 되어 `"end_phase" < "set_spell_trap"` 으로 진다 |

### 안전 · 성능 (search vs search, 8판)

| 항목 | 값 |
|---|---|
| completed / games | 8 / 8 |
| refusals · errors · limits | 0 · 0 · 0 |
| 결정 수 | 843 |
| 시뮬레이션 수 | 1,746 |
| 결정 시간 p95 / 최대 | 15.9 ms / 27.9 ms |

**승률은 해석하지 않는다.** 이 행동 공간에서 승패는 아직 정책의 강함을 재는
값이 아니다.

---

## 7. 세트에 가산점이 없다 — 구조적 보장

| 보장 | 어떻게 |
|---|---|
| 평가가 **행위를 볼 수 없다** | `evaluate(self, view)` — 인수에 행위가 없다. 서명 + AST 검사 (`test_14`) |
| `agent/` 어디에도 세트의 이름이 없다 | 식별자 토큰 안에서 `set_monster`·`SET_MONSTER`·`CardSet`·`FACEDOWN`·`monster_set` 를 찾아 0건 (`test_13`) |
| 가중치를 건드리지 않았다 | Phase 3-C 의 다섯 상수가 그대로 (`test_15`) |

`test_13` 은 **처음 쓴 판이 약했다.** 토큰이 금지어와 *정확히 같은지*만 봐서
일부러 넣어 본 `SET_MONSTER_BONUS = 0` 을 잡지 못했다. 토큰 **안에서** 찾도록
고쳤고, `set()`·`settings`·`supported`·`offset`·`dataset` 가 걸리지 않는 것도
같은 시험이 확인한다. 고친 뒤 같은 위반을 다시 넣으면 깨진다.

---

## 8. 숨은 정보 (§8 · §13)

"없다" 와 "안 보인다" 가 구분된다. 장수와 표시 형식은 공개, 정체는 비공개.

| 보는 쪽 | `card_id` | `name` | `definition` | `position` |
|---|---|---|---|---|
| 놓은 사람 | `11091375` | 있음 | 있음 | `FACEDOWN_DEFENSE` |
| 상대 | `None` | `None` | `None` | `FACEDOWN_DEFENSE` |

`instance_id` 와 `position` 을 숨기지 않는 이유: 상대가 그 카드를 **공격
대상으로 고를 수 있어야** 한다. 시뮬레이션으로도 새지 않고(`test_12`),
검증을 반복해서 읽을 수도 없다(engine `test_25`).

평가 쪽에서도 상대 관점의 뒷면 몬스터는 `atk` 항에 0 으로 들어간다 —
보이지 않는 것을 세지 않는다.

---

## 9. STRUCTURAL-108 — 절반이 풀렸다

Phase 3-E-1 은 "수비 표시를 만들 길이 없다" 를 사실로 적었고, 그 설명에
**"여기서 통과시키려고 가짜 상태를 만들지 않는다"** 고 썼다. 이번 Phase 가
가짜 상태가 아니라 **세트 실행 계층**을 넣어 길을 냈다.

| 절반 | 상태 |
|---|---|
| 패에서 뒷면 수비 표시로 **놓는** 길 (`SET_MONSTER`) | ✅ **RESOLVED** — 난수 정책이 고르고 판에 실제로 생긴다 |
| 이미 놓인 몬스터의 표시 형식을 **바꾸는** 길 (`CHANGE_POSITION` · Flip Summon) | ❌ 그대로 — §24 가 범위 밖으로 두었다 |

`test_defence_position_is_not_reachable_through_legal_actions` 는 그래서
`test_defence_position_is_now_reachable_through_legal_actions` 로 **뒤집혔다.**
약화가 아니라 반대 방향의 강화다 — 예전에는 한 가지만 적었는데 지금은 네
가지를 따로 적는다 (후보에 오른다 / 규칙 기반은 고르지 않는다 / 난수는 고르고
판에 생긴다 / `CHANGE_POSITION` 은 여전히 없다).

### ATK vs DEF — 실제 SET 으로 도달했다 (§19)

가짜 상태도, 손으로 바꾼 표시 형식도 쓰지 않았다. `legal_actions` 의
`SET_MONSTER` 를 골라 만든 뒷면 몬스터를 상대가 공격한다.

```
소울 타이거  ATK 0 / DEF 2100   — p0 이 실제 후보에서 세트
사파이어 드래곤 ATK 1900        — p1 이 실제 후보에서 소환 후 공격

결과: p1 LP 8000 → 7800 (차이 200), 어느 쪽도 파괴되지 않음 (RULE-BATTLE-012)
```

공격력 0 으로 판정했다면 1900 데미지가 **반대쪽으로** 갔을 것이다. 숫자의
크기와 방향 둘이 "수비력으로 판정했다" 를 증명한다 (engine `test_30`).

---

## 10. 기존 테스트 4건이 깨졌다 — 원인과 처리

하나도 삭제하지 않았고, 하나도 skip 하지 않았다. 넷 다 **세트가 적법해진
결과**이고 결함이 아니다.

| 테스트 | 원인 | 처리 |
|---|---|---|
| `test_set_spell_trap_rejects_a_monster` (engine) | 픽스처가 드로우 페이즈여서 새로 넣은 `PhaseIs(MAIN_PHASES)` 가 먼저 걸렸다 | **주장을 늘렸다** — 메인 페이즈 밖은 `WRONG_PHASE`, 메인 페이즈면 `VALID`. 원래의 `UNKNOWN` 은 세트 절차가 없던 시절의 사실이고, 지금 그 답은 "할 수 있는데 모른다" 는 거짓말이 된다 |
| `test_e_how_much_room_a_policy_actually_has` (3-A) | 가장 넓은 결정 지점이 11 → **23** | 측정값을 갱신. 좁은 쪽(60곳) · 갈라지는 자리 수(30곳) · 페이즈(MAIN1·2)는 **하나도 변하지 않았다**. 11 을 상한으로 읽은 것이 잘못된 가정이었다 |
| `test_d_pass_never_shows_up_but_attack_now_does` (3-B) | 후보 종류에 두 세트가 추가 | 사실을 갱신. 이 시험이 지키는 것은 "`PASS` 가 없다" 이고 그 주장은 글자 하나 바뀌지 않았다 |
| `test_defence_position_is_not_reachable_through_legal_actions` (3-E-1) | **일부러 심어 둔 tripwire 가 예고대로 발사** | 뒤집어서 §9 처럼 네 가지를 따로 적는다 |

---

## 11. 남은 한계 (추측으로 메우지 않았다)

| ID | 내용 | 왜 이번에 고치지 않는가 |
|---|---|---|
| **STRUCTURAL-115** (신규) | 평가가 뒷면 몬스터에 대해 **모순**을 말한다 — `atk` 항에 1900 을 세면서 동시에 "내 뒷면 카드 1장은 값을 매기지 않았다" 를 남긴다. 그 결과 `set_monster` 와 `normal_summon` 의 점수가 같아진다 | 올바른 셈이 무엇인지가 **설계 결정**이다 (공격력을 빼야 하는가 · 수비력을 넣어야 하는가 · 아무 값도 주지 않아야 하는가). §15 가 평가 변경을 범위 밖으로 두었고, 모르는 것을 임의로 정하는 쪽이 모순을 기록하는 쪽보다 나쁘다. `test_17` 이 사실로 적는다 |
| **STRUCTURAL-116** (신규) | 공격받은 뒷면 몬스터를 **앞면으로 뒤집지 않는다**. 실제 데미지 스텝은 뒤집는다 | 리버스 효과 · 플립 소환과 함께 다룰 일이다 (RULE-SUMMON-012). engine `test_30` 이 현재 동작을 사실로 적고, 바뀌면 깨진다 |
| STRUCTURAL-108 (절반) | `CHANGE_POSITION` · Flip Summon 이 없다 | §24 범위 밖 |
| STRUCTURAL-111 | 이기는 공격들 사이에서 평가가 같다 | §15 가중치 변경 금지 |
| — | 세트한 카드를 **발동하지 않는다**. 함정의 발동 타이밍도 보지 않는다 | 이 Phase 의 일은 "패에서 뒷면으로 놓는 것" 하나다 |
| — | 제물이 필요한 세트(Tribute Set)는 `UNKNOWN` 이다 | 제물 절차가 아직 없다. **`UNKNOWN` 을 허가로 바꾸지 않았다** (engine `test_18`) |

---

## 12. 테스트

| 파일 | 개수 | 무엇을 |
|---|---|---|
| `tests/engine/test_set_card.py` (신규) | 49 | 조립 · 절차 · 실행 · 델타 · 소환권 · 적법성 · 숨은 정보 · 안전 · ATK vs DEF |
| `tests/agent/test_set_action_space.py` (신규) | 31 | 후보 · 시뮬레이션 · 평가 · 탐색 선택 · 통계 · STRUCTURAL-108 · 결정론 |

고의 위반 5건을 넣어 시험이 실제로 잡는지 확인하고 되돌렸다 (소환권 미소비 /
세트를 소환으로 기록 / 페이즈 요구 제거 / 세트를 앞면으로 / 탐색에 세트
하드코딩). 다섯째는 **처음에 잡히지 않아서 시험을 고쳤다** (§7).
