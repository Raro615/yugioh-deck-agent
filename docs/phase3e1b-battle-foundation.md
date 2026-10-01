# Phase 3-E-1-B — Minimal Battle Execution Foundation

- **Base commit**: `490ddcd` (Phase 3-D — AI vs AI / Search Validation)
- **Branch**: `claude/pensive-goodall-te1egy`
- **결과**: 3089 → **3133 passed, 4 skipped** · 새 테스트 44개 · 회귀 0건
- **`engine/` 변경**: **있음** (이번 Phase 에 한해 승인됨) — 신규 1개 + 수정 5개

---

## 1. 무엇이 왜 필요했나

Phase 3-E-1 감사 결과: `PlayerAction.attack` · `ActionValidator._attack` ·
`BATTLE_PHASES` · `change_life` · `LifeChanged` 는 **이미 있었고**, 없는 것은
네 가지였다.

| 없던 것 | 이번에 만든 것 |
|---|---|
| 🔴 전투 실행 계층 (STRUCTURAL-103) | `engine/battle.py` — `BattleExecutor` + `AttackHandler` |
| 🔴 몬스터별 공격 횟수 (STRUCTURAL-104) | `RuleUsageRegistry` 의 **카드별 표** |
| 🟠 ATTACK legality (STRUCTURAL-105) | 조건 4개 + `_COMPLETE_RULES` 승격 |
| 🟠 BATTLE 단계 연결 (STRUCTURAL-106) | **최소 연결만** — 아래 §7 참고 |

## 2. Engine 변경 — 파일별 이유

| 파일 | 줄 | 이유 |
|---|---|---|
| `engine/battle.py` | 신규 | `BattleExecutor` · `AttackHandler` · `BattleOutcome` · `BattleDestruction`. `action_execution` 의 설명이 "앞으로 붙을 자리" 로 적어 둔 `BattleExecutor` 가 이것이다 |
| `engine/state/rule_usage.py` | +159 | 공격권은 **카드마다** 하나다 (RULE-BATTLE-002). 기존 키 `(turn, player, action)` 은 플레이어 단위라 표현할 수 없다 |
| `engine/action_validation.py` | +201 | 조건 4개 추가 + `ATTACK` 을 `_COMPLETE_RULES` 로. 그 전까지는 요구를 전부 통과해도 `UNKNOWN` 이었다 |
| `engine/game_state_view.py` | +33 | **검증기는 관측만 본다** (ADR-007). 공격 기록이 관측에 실리지 않으면 "이미 공격했는가" 를 판정할 길이 없다 |
| `engine/duel.py` | +56 | ATTACK 후보 열거 + `duel_executor()` 사용 |
| `engine/summon.py` | +14 | `duel_executor()` 추가. `summon_executor()` 는 **건드리지 않았다** — 그 이름이 말하는 것은 소환이고 거기에 전투를 넣으면 이름이 거짓이 된다 |

관련 없는 리팩터는 하지 않았다.

## 3. 공식 규칙 근거 — 추측한 규칙이 하나도 없다

판정 전부가 `rules` 계층의 조항에서 온다. `BattleOutcome.rule_id` 가 그 증거다.

| 조항 | 구현된 내용 |
|---|---|
| **RULE-BATTLE-001** | "the player who goes first cannot conduct a Battle Phase in their very first turn" → 1턴 공격 금지 |
| **RULE-BATTLE-002** | "Each face-up Attack Position monster you control is allowed 1 attack per turn" → 표시 형식 + **카드별** 공격권 |
| **RULE-BATTLE-010** | "If you attack an Attack Position monster, compare ATK vs. ATK. If you attack a Defense Position monster, compare your monster's ATK vs. the attacked monster's DEF" → 분기 기준 |
| **RULE-BATTLE-011** | ATK vs ATK — 높으면 파괴 + 초과분, 같으면 **양쪽 파괴 · 데미지 없음**, 낮으면 공격자 파괴 + 초과분 |
| **RULE-BATTLE-012** | ATK vs DEF — 높으면 파괴 · **데미지 없음**, 같으면 **아무 일도 없음**, 낮으면 공격자 쪽 LP |
| **RULE-BATTLE-013** | "If there are no monsters on your opponent's side of the field, you can attack directly. The **full amount**..." |
| **RULE-BATTLE-014** | "Monsters with 0 ATK cannot destroy anything by battle" → 0 끼리는 아무 일도 없음 |

`test_every_rule_id_the_executor_cites_really_exists` 가 소스에서 룰 ID 를
뽑아 **`rules` 계층에 실제로 있는지** 확인한다 — 없는 조항을 인용할 수 없다.

## 4. 전투 파괴의 이유는 `EFFECT` 가 아니다

`REASON_NAMES[DESTROY]` 는 `("DESTROY", "EFFECT")` 인데 전투 파괴는 효과가
아니다. 그 표의 주석이 직접 적어 두었다:

> "전투 · 비용으로 인한 경우는 여기 없다 — 그것은 효과가 아니라 다른 경로이고,
> 그 경로가 생길 때 함께 정한다."

**이 Phase 가 그 경로다.** 그래서 `ZoneMoved` 를 쓰지 않고 `BattleDestruction`
을 따로 두고 `reason_names = ("DESTROY", "BATTLE")` 로 적는다
(`constant.lua` 의 `REASON_BATTLE = 0x20`).

`EFFECT` 로 적으면 나중에 트리거 계층이 전투 파괴를 "효과로 파괴됐다" 로 읽고,
"효과로 파괴될 때" 를 조건으로 하는 카드가 **잘못 발동한다.**

`CardMovement` 를 상속하므로 "이번에 움직인 카드" 를 세는 기존 코드가
고치지 않고 이것도 센다 — 새 이벤트 모델을 만들지 않았다.

## 5. 모르는 능력치를 숫자로 바꾸지 않는다

공격력이 `?` 인 몬스터(실측 56장)가 전투에 들어오면 `BattleError` 로 **멈춘다.**
0 으로 읽으면 "약하다" 가 거짓이 되고 큰 수로 읽으면 "강하다" 가 거짓이 된다.
공격력을 바꾸는 효과 계층이 생기기 전까지는 멈추는 것이 정직하다.

## 6. 공격권 — 카드마다 하나 (STRUCTURAL-104)

```
키:  (turn_number, player, instance_id, "attack")
```

- 같은 이름의 두 몬스터가 **서로 다른** 공격권을 갖는다 (실증)
- 턴이 넘어가면 키가 달라지므로 **지울 것이 없다** (기존 설계 그대로)
- `clone()` 이 함께 복제하므로 사본에서 쓴 것이 원본에 남지 않는다
- 두 표가 서로의 행위를 **거부한다** — `key()` 에 `ATTACK` 을 주면 `ValueError`,
  `card_key()` 에 `NORMAL_SUMMON` 을 주면 `ValueError`

## 7. STRUCTURAL-106 은 **최소 연결만** 했다

`Phase.BATTLE` 안에서 공격 하나를 **원자적으로** 해결한다.
`BATTLE_START` · `BATTLE_STEP` · `DAMAGE` · `DAMAGE_CAL` 하위 페이즈에는
**들어가지 않는다** (실측: 듀얼이 지나가는 배틀 계열 페이즈는 `BATTLE` 하나).

이것은 **의도한 단순화**이고 숨기지 않는다. 리플레이(RULE-BATTLE-005) ·
데미지 스텝 발동 제한(RULE-BATTLE-007) · 뒷면 반전(RULE-BATTLE-008) ·
플립 효과(RULE-BATTLE-009)가 필요해지면 그때 하위 단계를 연다. 지금은 그것을
필요로 하는 카드 효과가 발동되지 않는다.

## 8. 전투 결과 검증 (실제 엔진, 실제 카드)

| 경우 | 결과 | 조항 |
|---|---|---|
| ATK 1900 > ATK 1500 | 대상 파괴 · 상대 LP −400 | RULE-BATTLE-011 |
| ATK 1500 < ATK 1900 | **공격자** 파괴 · **내** LP −400 | RULE-BATTLE-011 |
| ATK 1700 = ATK 1700 | **양쪽 파괴** · 데미지 0 | RULE-BATTLE-011 |
| ATK 0 vs ATK 0 | **아무 일도 없음** | RULE-BATTLE-014 |
| ATK 1900 > DEF 900 | 대상 파괴 · **데미지 0** (관통 없음) | RULE-BATTLE-012 |
| ATK 1700 = DEF 1700 | **아무 일도 없음** | RULE-BATTLE-012 |
| ATK 1200 < DEF 1600 | 아무것도 안 부서지고 **내** LP −400 | RULE-BATTLE-012 |
| 다이렉트 (ATK 1900) | 상대 LP −1900 (**전액**) | RULE-BATTLE-013 |

## 9. 행동 공간 — ATTACK = 0 → 777

5조합 × 16씨앗 = **80 대국** 측정:

| 행위 | Phase 3-D | Phase 3-E-1-B |
|---|---|---|
| `END_PHASE` | 2,976 | 4,122 |
| `NORMAL_SUMMON` | 160 | 719 |
| **`ATTACK`** | **0** | **777** |
| 나머지 | 0 | 0 (변화 없음) |

거절 **0** · 예외 **0** · 완주 **80/80**.

후보가 2개 이상인 결정 지점: 20판에서 200곳 → **458곳**.

## 10. STRUCTURAL-101 이 풀렸다

| | Phase 3-D | Phase 3-E-1-B |
|---|---|---|
| 종료 이유 | 전부 덱아웃 | 전부 **LP 0** (16/16) |
| 최종 LP | 전부 8000/8000 | **8000/8000 인 대국 0건** |
| 평균 턴 | 32.0 | **8.4~10.1** |
| 승자가 정책에 따라 달라지는가 | **아니오** (112대국 전부 P0) | **예** (씨앗 4 에서 승자 집합 {0,1}) |

`test_f_the_winner_now_depends_on_the_policy` 가 이 사실을 기록한다. Phase 3-B
에서 그 시험은 반대를 적었고, 설명에 **"전투가 들어오면 이 시험이 깨진다 —
그때는 깨지는 것이 옳다"** 고 적어 두었다. 그 순간이 왔다.

## 11. STRUCTURAL-102 가 움직였다

20판 · 후보 2개 이상인 결정 지점 458곳:

| | Phase 3-C/3-D | Phase 3-E-1-B |
|---|---|---|
| 탐색과 규칙이 같은 수 | 200 / 200 | 401 / 458 |
| **다른 수** | **0 (0.0%)** | **57 (12.4%)** |

차이의 모양이 의미 있다:

```
seed=1  rule=attack P0 #0 ->#23   search=end_phase P0
seed=2  rule=attack P0 #1 ->#21   search=end_phase P0
```

규칙 기반은 **공격자의 공격력만** 보고 공격한다 (대상과 견주지 않는다).
탐색은 그 수를 **실제로 해 보고** 자기 몬스터가 부서지고 LP 를 잃는 미래를
보기 때문에 **공격을 포기한다.** 내다보기가 사기로 했던 바로 그 판단이다.

**아직 결론을 내리지 않는다.** 16판은 승률을 말할 표본이 아니고, Search 대
RuleBased 는 7승 9패다. 이 Phase 가 보고하는 것은 **행동이 갈라지기 시작했다**
는 사실뿐이다.

## 12. 기존 테스트 수정 — 왜, 그리고 무엇을 바꾸지 않았나

전투가 들어오면서 **듀얼의 성질이 바뀌었다**: 덱아웃 196걸음 → LP 0 으로
46~126걸음. 기존 테스트 7개가 그 영향을 받았다. **주장(assertion)의 방향을
약화시킨 것은 하나도 없다.**

| 테스트 | 무엇을 바꿨나 | 바꾸지 않은 것 |
|---|---|---|
| `_battle()` 픽스처 (engine) | 턴 1 → 턴 2 | 주장 전부. RULE-BATTLE-001 이 먼저 걸려 **시험하려던 규칙을 가리던** 것을 치웠다. 같은 파일 632행의 `# 페이즈 위반이 먼저 걸리지 않도록` 와 같은 손질 |
| `test_attack_..._reaches_the_missing_rule` | `UNKNOWN` → `VALID` 로 **뒤집고** 이름 변경 + 다이렉트 어택 시험 2개 추가 | — 전에는 "모른다" 였고 지금은 "된다/안 된다" 를 말한다. **반대 방향의 강화** |
| `test_d_pass_never_shows_up...` (3-B) | 후보 종류에 `ATTACK` 추가 | `PASS` 가 없다는 주장은 **글자 하나 안 바뀜** |
| `test_e_a_whole_duel_runs...` (3-B) | `steps > 100` → `> 30` | `refusals == ()` · `finished` 그대로 |
| `test_f_the_winner_does_not_yet...` (3-B) | **주장을 뒤집음** (§10) | — 이 시험은 깨지도록 심어 둔 것이다 |
| `test_17` / `test_24` / `test_25` / 성능 (3-C) | 시뮬레이션·걸음 상한을 재측정값에 맞춤, 종료 이유 덱아웃 → LP | `state_hash` 일치 · 원본 불변 · 거절 0 **그대로** |
| `test_search_on_and_search_off...` (3-D) | `> 100` → `> 30` | "대국이 똑같다" 는 주장 그대로 |

삭제한 테스트 **0개** · skip 한 테스트 **0개** · `UNKNOWN` 을 `VALID` 로 바꿔
통과시킨 자리 **0개** · 예외를 catch 해서 통과시킨 자리 **0개**.

## 13. 고의 위반으로 검사 기제를 확인했다

| 심은 위반 | 깨진 시험 |
|---|---|
| 공격권을 고정 instance_id 로 기록 (카드별 추적 무력화) | 6개 |
| 전투 파괴 이유를 `EFFECT` 로 | `test_20_destruction_is_recorded_as_a_battle_movement` |
| `ATK ?` 를 0 으로 읽기 | `test_an_unknown_attack_value_stops_the_battle` |
| 동점에서 한쪽만 파괴 | `test_11_equal_attack_destroys_both...` |

## 14. 성능

결정당 평균 시뮬레이션 **1.037** · 결정 하나 평균 **1.054ms** / 최대 **7.3ms** ·
평균 턴 **8.4** · 평균 수 **65**. 전투가 들어와 듀얼이 **짧아졌으므로** 한 판의
총 비용은 Phase 3-D 보다 낮다. cache 는 넣지 않았다.

## 15. 의도적으로 구현하지 않은 것 (§14)

관통 · 공격 무효 · 공격 대상 변경 · 공격력/수비력 변화 효과 · 전투 데미지 대체 ·
전투 데미지 반사 · 공격 횟수 증가/감소 효과 · 공격 선언 시 트리거 ·
전투 중 퀵 이펙트 · 리플레이(RULE-BATTLE-005) · 데미지 스텝 발동 제한
(RULE-BATTLE-007) · 뒷면 반전(RULE-BATTLE-008) · 플립 효과(RULE-BATTLE-009) ·
카드별 특수 전투 조건 — **하나도 구현하지 않았다.**

`SET_MONSTER` · `SET_SPELL_TRAP` · `ACTIVATE_CARD` · `ACTIVATE_EFFECT` ·
`CHANGE_POSITION` 도 그대로 0 이다. Depth-2 · MCTS · RL · UI 도 없다.
`agent/` 는 **한 줄도 바꾸지 않았다** (테스트의 기준값만 재측정값에 맞췄다).

## 16. 새 TODO

- 🟠 **STRUCTURAL-107** — 배틀 스텝/데미지 스텝 하위 단계가 없다. 공격을
  `Phase.BATTLE` 안에서 원자적으로 해결한다. 리플레이 · 데미지 스텝 타이밍 ·
  플립 효과를 붙일 때 이 단순화를 열어야 한다.
- 🟠 **STRUCTURAL-108** — 수비 표시 몬스터를 **만들 수 없다**. `SET_MONSTER` 와
  `CHANGE_POSITION` 이 후보에 오르지 않으므로 실제 듀얼에서 `RULE-BATTLE-012`
  경로는 **도달하지 않는다** (단위 시험으로만 검증됨). 다음 Phase 의 대상.
- 🟡 **STRUCTURAL-109** — `RuleBasedPolicy` 가 공격을 **대상과 견주지 않고**
  고른다 (공격자의 ATK 만 본다). 그래서 지는 공격을 한다 (실측 57곳). 이것은
  규칙 기반 AI 의 한계이고 엔진 문제가 아니다. `agent/` 를 건드리지 않기로
  했으므로 이번에 고치지 않았다.
- 🟡 **STRUCTURAL-110** — `_AttackAvailable` 이 `NORMAL_SUMMON_ALREADY_USED`
  코드를 재사용한다. 공격권 전용 코드가 없어서다. `ValidationCode` 에 칸을
  더하는 것은 이번 범위를 넘으므로 하지 않았다.

## 17. 기존 TODO

- **STRUCTURAL-101** — **해결됨** (§10)
- **STRUCTURAL-102** — **움직임** (0% → 12.4%), 해결 아님 (§11)
- STRUCTURAL-103 · 104 · 105 — **해결됨**
- STRUCTURAL-106 — **최소 해결**, 나머지는 STRUCTURAL-107 로 이어짐
