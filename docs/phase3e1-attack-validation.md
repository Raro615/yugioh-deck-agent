# Phase 3-E-1 — ATTACK Action Space 정식 검증

- **Base commit**: `66e1188` (Phase 3-E-1-B — Minimal Battle Execution Foundation)
- **Branch**: `claude/pensive-goodall-te1egy`
- **결과**: 3133 → **3165 passed, 4 skipped** · 새 테스트 32개 · 회귀 0건
- **`engine/` 변경**: **0건**

---

## 1. 네 단계를 따로 증명했다

§최종원칙이 섞지 말라고 한 네 단계다. 앞의 것이 참이어도 뒤의 것은 따로 보여야 한다.

| 단계 | 증거 | 테스트 |
|---|---|---|
| **① 할 수 있다** | 실제로 굴린 듀얼의 BATTLE 자리에서 ATTACK 후보가 나온다 (만든 판이 아니다) | `test_01` |
| **② 내다볼 수 있다** | 시뮬레이션이 **진짜 `BattleExecutor`** 를 지나 미래에 파괴·LP·묘지·공격권이 반영된다 | `test_05·06·07` |
| **③ AI 가 고른다** | 결정 흔적에 ATTACK 선택이 남고, 같은 지점에 END_PHASE 후보도 있었다 | `test_14` |
| **④ 실제로 실행된다** | transcript 에 수락된 ATTACK 이 있고 LP 가 0 에 닿아 듀얼이 끝난다 | `test_15` |

## 2. 강제하지 않았다 — 구조적 보장

| 보장 | 어떻게 |
|---|---|
| 평가가 **행위를 볼 수 없다** | `evaluate(self, view)` — 인수에 행위가 **없다**. 서명 검사 + AST 로 `PlayerAction`·`kind`·`action` 이름이 `evaluation.py` 에 없음을 확인 |
| 탐색에 ATTACK 분기가 없다 | `search.py`·`simulation.py` 의 코드(설명문 제외)에 `attack` 이라는 글자가 **0건** |
| `agent/` 전체 | ATTACK 관련 식별자는 `_zone_attack`·`my_attack`(공격력 **수치**)와 `"higher-attack-first"`(규칙 이름)뿐. `if action == ATTACK` 없음 |

**고의 위반으로 확인**: 평가에 ATTACK 분기를 넣으면 `test_08c` 가, 평가 함수에
`action` 인수를 더하면 `test_08b` 가 깨진다.

### 공격 우대가 없다는 가장 강한 증거

**손해인 공격 앞에서 탐색은 턴을 넘긴다.**

```
ATK 1500 공격자 vs ATK 1900 대상  →  SearchPolicy 는 END_PHASE 를 고른다
```

공격 후보는 시뮬레이션되고 점수까지 받았다(`SUPPORTED` · `value is not None`).
그런데도 고르지 않았다 — 미래가 나쁘기 때문이다 (`test_09`).

## 3. Candidate identity — instance 단위 (§5)

같은 이름 두 장 × 같은 이름 두 장 = **서로 다른 네 후보**:

```
('attack', 0, 48, (('instance', 50, …),), …)
('attack', 0, 48, (('instance', 51, …),), …)
('attack', 0, 49, (('instance', 50, …),), …)
('attack', 0, 49, (('instance', 51, …),), …)
```

`canonical_state` 가 넷 다 다르고, `to_dict()` 에 `card_id` 가 **없다**. 카드
이름으로 식별하면 네 개가 하나로 뭉친다.

## 4. Scenario 검증 (§14~§17)

| Scenario | 결과 |
|---|---|
| **A** ATK 1900 vs ATK 1500 | 대상 파괴 · 상대 LP 7600 · 묘지 1 · 공격자 생존 · 공격권 기록 ✓ |
| **B** ATK 1500 vs ATK 1900 | **공격자** 파괴 · **내** LP 7600 · 상대 생존 ✓ |
| **C** 다이렉트 (ATK 1900) | 상대 LP 6100 (**전액**) · 공격자 생존 ✓ |
| **D** 대상 둘 | 후보 2개 · **미래가 서로 다르다** (LP 6300 / 7800, 생존자 다름) ✓ |

## 5. 🟠 STRUCTURAL-111 — 평가가 "이기는 대상들" 사이에서 무차별하다

Scenario D 에서 발견했다. **두 공격의 점수가 정확히 같다.**

```
공격자 ATK 1700
  대상 ATK 0    → lp +1700 · atk  +200 → 합계 1300
  대상 ATK 1500 → lp  +200 · atk +1700 → 합계 1300
```

산술로 설명된다. 공격자가 이기는 전투에서는 **언제나**

```
(입힌 데미지) + (지운 상대 공격력) = 공격자의 공격력
```

이고 `ATK_IN_LP == 1` 이므로 두 항이 **정확히 상쇄된다.** 그래서 어느 대상을
치는지가 점수로 갈리지 않고 `canonical_state` 순서로 갈린다.

Phase 3-C 가 공격력을 1:1 로 둔 근거("공격력은 그대로 LP 로 들어오는 피해")는
그대로 옳다. 담지 못한 것은 **파괴가 지우는 미래의 공격·방어 기회**다.

**가중치를 고쳐서 이 문제를 덮지 않았다** (§9 · §35). 숫자를 비틀어 원하는
결과를 만드는 것은 측정이 아니다. `test_09c` 가 사실을 기록하고, 해결되면
그 테스트가 깨져서 보고서를 다시 쓰게 만든다.

### 범위는 "이기는 몬스터 전투" 하나다

다이렉트 어택끼리는 **구별된다** (파괴가 없어 상쇄할 항이 없다):

```
P0 T7 BATTLE state_hash=df6a2eaa96a3… 시뮬레이션 4회
 → attack P0 #6 ->P1 → +15300 (lp=+7900, atk=+5100, monsters=+1500, …)
   attack P0 #3 ->P1 → +15100 (lp=+7700, …)
   attack P0 #0 ->P1 → +14900 (lp=+7500, …)
   end_phase P0      → +13400 (lp=+6000, …)
```

공격력이 큰 공격자로 때리는 것을 고르고, 턴 넘기기를 가장 낮게 본다.

## 6. 네 가지 셈을 섞지 않았다 (§23)

4조합 × 16씨앗 = **64 대국** 측정:

| 셈 | 값 |
|---|---|
| ATTACK **legal** count | **1,092** |
| ATTACK **selected** count | **588** |
| ATTACK **simulation** count | **585** |
| ATTACK **execution** count | **588** |

- `legal ≫ selected` — 후보로 오른 것의 절반가량만 선택된다 (대상이 여럿이면 하나만 고른다)
- `simulated ≠ selected` — 시뮬레이션은 **탐색 정책만** 한다. `RuleBased vs RuleBased` 는 시뮬레이션 0회인데 실행 133회다
- `selected == executed (588)` — 고른 공격이 전부 수락되었다. **invalid 0**

다이렉트 어택: legal **466** / selected **302** / executed **302**.
공격 후보가 있던 결정 지점 **658** · 대상이 2개 이상이던 지점 **332**.

## 7. 조합별 (seed 1~16)

| P0 | P1 | 완주 | 평균턴 | legal | 선택 | 시뮬 | 실행 | 직접 | invalid |
|---|---|---|---|---|---|---|---|---|---|
| Search | Search | 16/16 | 9.6 | 339 | 161 | 339 | 161 | 76 | 0 |
| Search | RuleBased | 16/16 | 8.4 | 278 | 145 | 111 | 145 | 74 | 0 |
| RuleBased | Search | 16/16 | 8.4 | 268 | 149 | 135 | 149 | 77 | 0 |
| RuleBased | RuleBased | 16/16 | 7.2 | 207 | 133 | **0** | 133 | 75 | 0 |

예외 **0** · 전부 LP 0 으로 종료.

## 8. Safety

| 항목 | 결과 |
|---|---|
| original state unchanged | **PASS** — 공격 후보 3개를 내다본 뒤에도 LP·필드·묘지·**공격권**·해시 전부 그대로 |
| clone independence | **PASS** — 두 공격 시뮬레이션의 생존자와 LP 가 서로 다르고, 각 미래에 **자기 공격만** 반영 |
| RNG isolation | **PASS** — 대국 내내 `draws` 가 한 값. 전투는 난수를 쓰지 않는다 |
| determinism | **PASS** — 같은 씨앗 → 같은 `canonical_state`·`state_hash`·수의 순서 |
| simulation == real | **PASS** — `fork_after` 로 받은 사본과 실제 적용 후 원본의 `state_hash`·관측·LP·공격권이 **전부 일치** |

## 9. UNKNOWN (§10)

ATTACK 시뮬레이션에서 **`UNKNOWN` 이 한 번도 발생하지 않았다** (585회 전부
`SUPPORTED`). `_COMPLETE_RULES` 에 올랐으므로 허가된 후보는 실행되고, 허가되지
않은 수는 후보 목록에 애초에 없다. 임의 변환한 자리는 없다.

후보 목록 밖의 공격은 `NOT_A_CANDIDATE` 로 되돌아온다 — 상대 몬스터로 공격 ·
자기 몬스터를 공격 · 상대 필드가 있는데 다이렉트, 세 경우 모두 확인 (`test_20`).

## 10. 성능 (§25)

| 항목 | Phase 3-D | Phase 3-E-1 |
|---|---|---|
| games | 112 | 64 |
| decisions | 21,952 | **4,156** |
| 결정 하나 평균 | 1.324ms | **1.792ms** |
| 중앙값 | 1.388ms | **1.391ms** |
| 최대 | 161.5ms | **329.3ms** |
| 평균 턴 | 32.0 | **7.2~9.6** |

중앙값은 거의 같고 평균만 올랐다 — 공격 후보가 늘어 시뮬레이션이 많아진 결과다.
최대값은 여전히 **첫 결정 한 번**의 이상치다(카드 정의 최초 적재). 듀얼이
짧아졌으므로 한 판의 총 비용은 3-D 보다 낮다. cache 는 넣지 않았다.

## 11. NOT_REACHED — 정직하게 적는다

**ATK vs DEF 경로의 탐색 검증은 NOT_REACHED 다.**

측정: 실제 듀얼에서 몬스터 존에 나타난 표시 형식은 `FACEUP_ATTACK` **하나**
뿐이고, `SET_MONSTER`·`CHANGE_POSITION` 후보는 **0회**다 (`test_defence_...`).
수비 표시를 만들 길이 없으므로 탐색이 그 경로를 지날 수 없다.

엔진 수준에서는 Phase 3-E-1-B 가 ATK>DEF · ATK==DEF · ATK<DEF 를 모두 검증했다.
그것을 이 Phase 의 탐색 검증으로 **옮겨 적지 않는다.** 가짜 상태로 통과시키지도
않았다 (STRUCTURAL-108).

## 12. 만든 판이 가짜가 아니라는 것

Scenario 테스트는 `GameState.move`(엔진의 primitive)로 판을 세운다. 그것이
가짜가 아닌 근거:

1. 그 판에서 **엔진이 직접** `VALID` 를 돌려준다
2. 쓰는 표시 형식이 `engine.normal_summon.SUMMON_POSITION` 과 같다 — 일반
   소환이 실제로 만드는 상태다
3. 전투는 손으로 만든 결과가 아니라 **등록된 `BattleExecutor`** 가 만든다

그리고 ①③④ 단계는 **만든 판을 전혀 쓰지 않고** 실제로 굴린 듀얼에서만 증명한다.

## 13. 기존 TODO 상태

| 항목 | 상태 | 근거 |
|---|---|---|
| **STRUCTURAL-101** | **해결** (3-E-1-B) | 64대국 전부 LP 0 종료, 8000/8000 종료 0건 |
| **STRUCTURAL-102** | **유지** (움직였으나 미해결) | 불일치 0% → 12.4%. 아래 참고 |
| **STRUCTURAL-107** | **UNRESOLVED / DEFERRED** | 배틀 스텝·데미지 스텝 하위 단계 없음. 이번에 손대지 않았다 |
| **STRUCTURAL-108** | **유지** | 수비 표시 생성 불가 → ATK vs DEF 탐색 NOT_REACHED |
| **STRUCTURAL-109** | **유지 (측정만)** | 아래 참고 |
| **STRUCTURAL-110** | **유지** | `_AttackAvailable` 이 `NORMAL_SUMMON_ALREADY_USED` 재사용. 오판정은 없었다 (ATTACK legality 테스트 전부 통과) |
| **STRUCTURAL-111** | **신규** | §5 |

### STRUCTURAL-109 측정 결과 (고치지 않았다)

`RuleBasedPolicy` 는 **공격 후보가 있으면 공격을 고른다.** 점수는 공격자의
공격력만 보고 매긴다 — 대상을 보는 규칙이 **없다**. 그래서 ATK 1500 으로 ATK
1900 을 치는 **손해인 공격도 한다.** 같은 판에서 탐색은 턴을 넘긴다.

`test_18` 이 이 사실을 못박는다. 개선하지 않았고, 엔진 문제로 분류하지 않았다.

## 14. 하지 않은 것

`SET_MONSTER` · `SET_SPELL_TRAP` · `ACTIVATE_CARD` · `ACTIVATE_EFFECT` ·
`CHANGE_POSITION` 추가 · 배틀 스텝/데미지 스텝 · 전투 예외 규칙 · Depth-2 ·
MCTS · RL · UI — **하나도 하지 않았다.** `engine/` 변경 **0건**.

`agent/` 변경은 `arena.py` 의 **설명문 한 단락**뿐이다 — "ATTACK 이 후보에 없어
LP 가 움직이지 않는다" 는 문장이 이제 거짓이므로 사실로 고쳤다. 정책의 행동을
바꾼 코드는 없다.
