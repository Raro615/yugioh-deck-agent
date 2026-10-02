# Phase 3-E-3 Implementation — Effect Action Space

- **Base commit**: `a2be286` (Phase 3-E-3 — Effect Action Space Audit)
- **Branch**: `claude/pensive-goodall-te1egy`
- **결과**: 3266 → **3306 passed, 4 skipped** · 새 테스트 40개 · 회귀 0건
- **`engine/` 변경**: 새 파일 1개 + 기존 파일 2개

---

## 1. 증명한 한 줄

```
legal_actions → ACTIVATE_EFFECT 후보 → validation → Duel.apply
  → place(패→SZONE 앞면) → activate(ChainLink) → resolve(효과)
  → retire(→묘지) → Search simulation
```

실제 실행 trace (`test_12` · `test_15` 가 같은 사실을 주장으로 고정한다):

```
① legal_actions   → ACTIVATE_EFFECT 후보 1개: activate_effect P0 #40 55144522:e[0]
② validation      → valid [ok]
   적용 전            욕망의항아리=HAND  덱=20 패=1 SZONE=0 묘지=0 chain=0
③ place           → P0 가 #40 를 발동 선언하며 SZONE 에 앞면으로 놓았다 (해결 전)
④ activate        → activated | 55144522:e[0] 를 체인 1 로 발동했습니다.
                     ChainLink seq=0 chain#1 effect=55144522:e[0] actor=P0
⑤ resolve_top     → resolved | 체인1 P0 55144522:e[0] 를 해결했습니다.
                     delta CardDrawn reasons=('DRAW','EFFECT') DECK→HAND
                     delta CardDrawn reasons=('DRAW','EFFECT') DECK→HAND
⑥ retire          → P0 의 #40 가 해결을 마치고 GRAVE 로 갔다 (효과가 아니라 규칙)

Duel.apply        → accepted=True [ok] 체인1 P0 55144522:e[0] 를 해결했습니다.
   적용 후            욕망의항아리=GRAVE 덱=18 패=2 SZONE=0 묘지=1 chain=0
```

---

## 2. Engine 변경

| # | 파일 | 무엇을 | 왜 |
|---|---|---|---|
| 1 | `engine/spell_activation.py` **(신규)** | `NormalSpellPlacement` · `SpellPlaced`/`SpellRetired`/`SpellRestored` 델타 · `duel_activator()`/`duel_resolver()`/`activatable_effects()` | 발동을 **배치**로 정의한 RULE-SPELLTRAP-002 를 수행하는 자리가 **없었다** (§3) |
| 2 | `engine/action_validation.py` | `_activate_effect` 를 `_activate` 에서 분리 · `_NormalSpellActivation` 조건 · `_COMPLETE_RULES` 에 `ACTIVATE_EFFECT` | 승인 범위 2번. `ACTIVATE_CARD` 는 **손대지 않았다** |
| 3 | `engine/duel.py` | `chain: Chain` 칸 · `_activation_actions()` · `_apply_activation()` | 승인 범위 1 · 3 · 4번 |

새로 만들지 **않은** 것: ActivationEngine · ChainEngine · EffectEngine · EventBus ·
SearchEngine · Effect Graph · Expression Language · 새 `ValidationCode` ·
새 cost system · 새 target system · 새 hidden-information system.

재사용한 것: `EffectActivator` · `CostPayer` · `Chain` · `ChainResolver` ·
`EffectExecutor` · `GameState.move` · 기존 `Condition` 들 (`IsTurnPlayer` ·
`ControllerIs` · `PhaseIs` · `ZoneHasFreeSlot`) · 기존 `ValidationCode`.

### 왜 파일 하나가 더 필요했나 (§3)

승인된 4건에는 없던 항목이다. 공식 조항이 발동을 **배치**로 정의한다.

> RULE-SPELLTRAP-002 — "To use a Normal Spell Card, announce its activation to
> your opponent, **placing it face-up on the ﬁeld**. If the activation
> succeeds, then you resolve the effect written on the card. **After resolving
> the effect, send the card to the Graveyard.**"

그 배치를 하는 자리가 repository 에 **하나도 없었다** — `activation.py` 는 비용과
체인 링크만 만들고 `ChainResolver` 는 효과만 해결한다. 그래서 Audit 에서 손으로
발동시켰을 때 **카드가 패에 그대로 남았다.** 규칙 위반이고, 그보다 먼저
**끝나지 않는 듀얼**이 된다: 욕망의 항아리가 패에 남으면 덱이 마를 때까지 같은
턴에 계속 발동된다.

`Duel._apply_activation` 안에서 `GameState.move` 를 직접 부르는 길도 있었지만
택하지 않았다 — `Duel` 의 모듈 설명이 "규칙을 새로 만들지 않는다. 이미 있는
계층들을 부르고 그 답을 그대로 전하는 것뿐이다" 라고 적고,
`test_e_the_duel_makes_no_rules_of_its_own` 이 그것을 AST 로 지킨다. 그래서
Phase 3-E-2 의 `engine/set_card.py` 와 **같은 모양**의 얇은 배치 계층을 두었다.
architecture 가 아니라 배치 하나다.

---

## 3. ACTIVATE Action Space

8개 씨앗 · 같은 덱(`LUSTER_DRAGON`×6 + `BATTLE_OX`×6 + `POT_OF_GREED`×8) ·
끝까지 굴린 듀얼. **네 가지를 따로 센다.**

### `ACTIVATE_EFFECT`

| 조합 | legal | selected | simulated | executed |
|---|---|---|---|---|
| search vs search | 151 | **0** | 전부 (`SUPPORTED`) | 0 |
| rule vs rule | 226 | **106** | — (탐색 없음) | 106 |
| random vs random | 279 | **48** | — | 48 |
| first-legal vs first-legal | 131 | **0** | — | 0 |

### `ACTIVATE_CARD`

| 조합 | legal | selected | simulated | executed |
|---|---|---|---|---|
| 전부 | **0** | **0** | **0** (`NOT_A_CANDIDATE`) | **0** |

`ACTIVATE_CARD` 는 발동 계층이 받지 않으므로 (모양 검사에서 거절) 손대지
않았다. Audit 의 주장이 **그대로** 살아 있다 (`test_18`).

### 왜 탐색이 고르지 않는가 — 측정해서 적는다

평가가 **손해**로 읽는다. Phase 3-C 가 실측으로 정한 가중치가 덱 한 장(300)을
패 한 장(200)보다 높게 보기 때문이다.

```
지금             heuristic 1000  {hand: 1000}
end_phase        heuristic 1000  {hand: 1000}
activate_effect  heuristic  600  {deck: -600, hand: 1200}

덱 −2장(−600) + 패 +2장(+400) − 발동한 카드가 패를 떠남(−200) = −400
```

**가중치를 고쳐서 고르게 만들지 않았다** (§16). 덱아웃이 패배 조건이라는
Phase 3-C 의 근거는 그대로 옳고, 모자란 것은 "뽑은 카드로 무엇을 할 수
있는가" 를 담는 계층이다 — Depth-1 로는 볼 수 없다 (`test_27`).

### 왜 규칙 기반이 고르는가 — 이것도 측정해서 적는다

규칙 기반에는 발동을 보는 규칙이 **하나도 없다.** 모든 발동 후보가 0 점으로
`END_PHASE` 와 동점이 되고, 동점은 `canonical_state()` 가 가르는데
`"activate_effect" < "end_phase"` 다. 그래서 **알파벳 순서 때문에** 이긴다.

Phase 3-E-2 에서 세트가 같은 자리에서 **졌던** 것과 같은 메커니즘이고
(`"end_phase" < "set_spell_trap"`) 방향만 반대다. "규칙 기반 AI 가 발동을
활용한다" 로 적지 않는다 (`test_28`).

---

## 4. 실제 카드

| | |
|---|---|
| Card | 욕망의 항아리 |
| Card ID | `55144522` |
| EffectRef | `EffectRef(55144522, 0)` |
| 종류 | `['SPELL']` — 통상 마법 (하위 종류 없음) |
| 비용 | `CostGroup(costs=())` — 없음 |
| 대상 | `()` — 없음 |
| 조작 | `DrawOperation(count=2, who=CONTROLLER)` |
| 발동 조건 | `ZoneCountAtLeast(CONTROLLER, DECK, 2)` |
| 근거 | `c55144522.lua` 의 `s.activate` · `lua_excerpt` 가 원문을 들고 있다 |

| 단계 | 판정 |
|---|---|
| Activation | **PASS** |
| Cost | **NOT_REACHED** — 이 카드에 비용이 없다 (`CostPayer` 는 불리지만 치를 것이 없다) |
| Chain | **PASS** — 체인 1 |
| Resolution | **PASS** |
| State Change | **PASS** — 덱 20→18 · 패 1→2 · 묘지 0→1 |

**Engine execution 과 official ruling verification 을 혼동하지 않는다** (§8).
이 카드의 공식 재정은 repository 에서 `not_checked` 다 (수집된 11장에 없다).
위 표는 **엔진이 무엇을 하는가**이고 공식 재정과의 대조가 아니다.

---

## 5. 범위 — `_COMPLETE_RULES` 에 올렸지만 아무것도 넓히지 않았다

Audit §11 의 세 선택지 중 **③(가장 좁게)** 를 택했다. 범위는 **패의 통상 마법
하나**이고, 그 밖의 모든 카드는 `UNKNOWN` 으로 남는다.

`_activate_effect` 의 요구가 **두 갈래**인 것이 이것을 지킨다. 언제나 묻는 것은
둘뿐이다 — 자기가 쥔 카드인가, **이번 Phase 가 판정할 수 있는 발동인가**.
범위 안일 때만 좁은 요구(턴 플레이어 · 메인 페이즈 · 빈 칸)를 더한다.

| 카드 | 결과 | `missing_rule` | 근거 |
|---|---|---|---|
| 패의 통상 마법 | **VALID** | — | RULE-SPELLTRAP-001 · 002 |
| 속공 마법 | UNKNOWN | `quick-play-timing` | RULE-SPELLTRAP-007 |
| 함정 | UNKNOWN | `non-spell-activation-timing` | RULE-SPELLTRAP-009 |
| 지속 · 장착 · 필드 마법 | UNKNOWN | `continuous-card-lifecycle` 등 | RULE-SPELLTRAP-004 · 005 · 006 |
| 의식 마법 | UNKNOWN | `ritual-summon-procedure` | RULE-SPELLTRAP-003 |
| 카운터 함정 | UNKNOWN | `counter-trap-timing` | RULE-SPELLTRAP-011 |
| 필드/세트된 카드의 발동 | UNKNOWN | `on-field-activation-timing` | — |
| 몬스터 효과 | UNKNOWN | `non-spell-activation-timing` | — |

### 구현 중에 한 번 틀렸던 자리

"패에 있는가" 를 처음에 **`INVALID`**(`SOURCE_WRONG_ZONE`) 요구로 두었다.
그러자 필드의 몬스터가 자기 효과를 발동하는 것이 **규칙 위반**으로 읽혔다 —
실제 규칙에서는 적법하고(기동 효과) 없는 것은 그 타이밍 계층뿐이다.
`tests/engine/test_action_legality.py::test_an_effect_ordinal_beyond_the_card_is_invalid`
가 이것을 잡았다. 자리 검사를 범위 조건 안으로 옮겨 `UNKNOWN` 이 되게 고쳤다.

같은 이유로 `IsTurnPlayer` 도 범위 안에서만 쓴다 — 함정은 상대 턴에 발동하는
것이 정상이므로(RULE-SPELLTRAP-008) 거기에 걸면 `NOT_TURN_PLAYER` 라는
거짓말이 된다. `test_05b`·`test_05c` 가 이 구분을 지킨다.

---

## 6. 후보가 되기 위한 관문은 **둘**이다

```
① ActionValidator       규칙 쪽 — 턴 플레이어 · 컨트롤러 · 메인 페이즈 ·
                        빈 칸 · 패의 통상 마법인가
② EffectActivator       구현 쪽 — 구현이 등록됐는가(EXECUTABLE) ·
   .can_activate        발동 조건이 참인가 · 대상이 쓸 수 있는가
```

합치지 않은 이유: ①은 "규칙이 허락하는가" 이고 ②는 "우리가 할 수 있는가" 다.
합치면 구현이 없는 카드가 **규칙 위반**으로 읽히고, 그것은 거짓이다 (ADR-006).

`test_10`(덱 1장 → 후보 없음)과 `test_11`(체인 있음 → 후보 없음)이 **검증기
혼자서는 통과시킨다**는 것을 함께 확인해서 둘이 따로임을 증명한다.

`Duel` 이 더 거르는 셋은 **범위**이고 규칙이 아니다.

| 거름 | 왜 | 지금 거르는 것 |
|---|---|---|
| 체인이 비었을 때만 | RULE-CHAIN-004 — 스펠 스피드 1 은 응답할 수 없다. 체인은 `GameState` 밖이므로 검증기가 볼 수 없다 (ADR-007) | 체인 중 발동 |
| 비용이 없는 효과만 | 비용을 치른 뒤 발동이 깨지면 되돌릴 수 없다 (ADR-008) | **0건** — 등록된 16개 전부 비용이 없다 (STRUCTURAL-120) |
| 대상이 없는 효과만 | `PlayerAction` → `TargetSelection` 길이 없다 | 어리석은 매장 등 8개 |

---

## 7. Safety

| 항목 | 판정 | 증거 |
|---|---|---|
| original state unchanged | **PASS** | 시뮬레이션 5×전체 후 `board()` 가 한 글자도 안 바뀐다 (`test_19`·`test_20`) |
| clone independence | **PASS** | `Chain` 이 불변이라 공유해도 안전 — 링크를 쌓으면 새 `Chain` 이 나오고 그것을 받는 `Duel` 만 달라진다 |
| RNG isolation | **PASS** | 사본의 뽑기가 원본 `randomness.draws` 에 남지 않는다 (`test_22`) |
| hidden information | **PASS** | 발동 카드는 상대에게 보이고(앞면 배치 — RULE-SPELLTRAP-002) **뽑은 카드는 안 보인다**. 장수 공개 · 정체 비공개 (`test_23`) |
| 정책 경계 | **PASS** | 정책은 `GameStateView` 와 후보 목록만 받는다 (`test_24`) |
| 탐색 하드코딩 없음 | **PASS** | `agent/` 어디에도 `activate_effect`·`EffectRef` 토큰이 0건 (`test_25`) |
| 모든 판이 끝난다 | **PASS** | 4조합 × 4씨앗 전부 completed · refusals/errors/limits 0 (`test_29`) |

---

## 8. Negative cases (§18)

| # | 경우 | 결과 | 테스트 |
|---|---|---|---|
| 1 | 열거형에 있지만 실행 불가 (블랙홀 — `executable=False`) | 후보 **0건** | `test_04` |
| 2 | 발동 타이밍이 다르다 (속공 · 함정) | **UNKNOWN** (INVALID 아님) | `test_06`·`test_05b` |
| 3 | 관찰 권한이 없는 상대 카드 | **UNKNOWN** (`HIDDEN_CARD`) | — (3-E-3 Audit `test_25`) |
| 4 | 지원하지 않는 `ACTIVATE_CARD` | 후보 0 · UNKNOWN · apply 거절 · 판 불변 | `test_18` |
| 5 | 목록에 아예 없는 카드 (통상 몬스터) | 후보 **0건** | `test_05` |
| + | 메인 페이즈 밖 / 상대 턴 / 존 꽉 참 / 조건 거짓 / 체인 중 | 후보 0건 | `test_07`~`test_11` |

고의 위반 5건으로 시험이 실제로 잡는지 확인하고 되돌렸다.

| 위반 | 깨진 시험 |
|---|---|
| 범위 밖(속공·함정)도 통과 | `test_05b` |
| `executable` 무시 | `test_04` |
| 체인이 쌓여도 발동 허가 | `test_11` |
| 해결 뒤 묘지로 안 보냄 | `test_12`·`16`·`19`·`23`·`26`·`27` (6건) |
| 발동 카드를 필드에 놓지 않음 | 11건 |

---

## 9. 기존 테스트 13건이 깨졌다 — 원인과 처리

하나도 삭제하지 않았고 skip 도 넣지 않았다. **둘은 실제 결함**이었고 나머지는
기록된 사실의 갱신이다.

### 실제 결함 (고쳤다)

| 테스트 | 무엇을 잡았나 | 어떻게 고쳤나 |
|---|---|---|
| `test_an_effect_ordinal_beyond_the_card_is_invalid` | 필드의 몬스터 효과가 `SOURCE_WRONG_ZONE` **INVALID** 로 거절됐다 — 규칙에 대한 거짓말 | 자리 검사를 범위 조건 안으로 옮겨 `UNKNOWN` 이 되게 (§5) |
| `test_e_the_duel_makes_no_rules_of_its_own` | `engine/duel.py` 가 `engine.effect.library` 를 직접 읽었다 | 공장 셋을 `engine/spell_activation.py` 로 옮겼다. duel.py 의 `engine.effect`/`engine.condition` import 는 다시 **0건** |

### 기록된 사실의 갱신 (Audit 이 "여기가 끊어졌다" 고 적은 자리들)

Audit 테스트 9건을 갱신했다 — `test_02`(STRUCTURAL-119 해결) ·
`test_04`·`test_05`(한쪽만 올랐다) · `test_06`(후보가 장수만큼) ·
`test_07b`(STRUCTURAL-117 해결) · `test_08`(ACTIVATE_CARD 만 거절) ·
`test_10`(체인 칸이 생겼다) · `test_16`·`test_17`. 각 docstring 에 **무엇을
적고 있었고 왜 바뀌었는지**를 남겼고, 여전히 참인 `ACTIVATE_CARD` 쪽 주장은
글자 하나 바뀌지 않았다. `test_09`(수행기 미등록 — STRUCTURAL-55)와
`test_07`(withheld)은 **그대로 통과**한다.

행동 공간 census 3건 — 3-A 의 가장 좁은 갈림길 9→**11**(넓은 쪽 23 · 좁은 쪽
60곳 · 갈라지는 자리 30곳은 그대로), 3-B 의 후보 종류에 `ACTIVATE_EFFECT`
추가(`PASS` 부재 주장은 불변), 3-E-1 의 `SET_MONSTER` 후보 104→271.

### 다시 읽어야 했던 시험 하나

`test_f_greedy_is_not_the_best_play` 는 "무작위가 이기는 씨앗이 존재한다" 로
탐욕의 한계를 보였는데, 그 씨앗이 사라졌다. **규칙이 나아져서가 아니다** —
측정해 보니 무작위 쪽이 훨씬 빨리 무너진다 (16씨앗 합계 규칙 70,700 vs
무작위 19,200, 무작위가 10씨앗에서 0). 즉 **척도가 둘을 가르지 못하게 된
것**이다.

그래서 증거를 씨앗 비교에서 **절대적인 사실**로 바꿨다: 규칙 기반도 씨앗
10 · 15 에서 몬스터 하나 없이 LP 0 으로 진다. 주장("탐욕은 baseline 이지
정답이 아니다")은 그대로다. **무작위가 이기는 씨앗을 찾아 범위를 넓히지
않았다** — 그렇게 하면 측정이 아니라 원하는 답을 찾는 일이 된다.

---

## 10. 테스트

| 파일 | 개수 | 무엇을 |
|---|---|---|
| `tests/engine/test_effect_activation_path.py` (신규) | 38 | §17 A~P · §18 1~5 전부 |
| `tests/engine/test_effect_action_space_audit.py` (갱신) | 23 (+2) | Audit 기록 + 구현 뒤의 사실 |

Baseline 3266 → **3306 passed, 4 skipped**. Regression **0건**.

---

## 11. Engine 변경 규모 — **중간 변경**

"작은 변경" 이 아닌 이유: 새 파일 하나와 `Duel` 의 새 실행 경로가 생겼고,
`_COMPLETE_RULES` 에 ActionKind 하나가 올라갔다. 행동 공간이 넓어져 기존
측정값 4건을 다시 재야 했다.

"큰 변경" 이 아닌 이유: 새 engine · 새 어휘 · 새 `ValidationCode` ·
새 cost/target/hidden-information 계층이 **하나도 없다**. 발동 · 비용 · 체인 ·
해결 · 효과 실행은 전부 **이미 있던 것을 그대로 부른다**. `Duel` 에 더한 칸은
`chain` 하나이고, `ActionExecutor` 는 건드리지 않았다 (STRUCTURAL-55 유지).

---

## 12. TODO

### 해결됨 (근거와 함께)

| ID | 상태 | 근거 |
|---|---|---|
| **STRUCTURAL-117** | **RESOLVED** | 후보 생성과 적법성 판정 둘을 모두 이었다. `Duel._activation_actions` (`test_07b`) |
| **STRUCTURAL-119** | **RESOLVED** | `_activate` / `_activate_effect` 분리 (`test_02`) |

### 유지

| ID | 왜 이번에 손대지 않았나 |
|---|---|
| STRUCTURAL-102 · 107 · 109 · 110 | §20 범위 밖 |
| STRUCTURAL-115 | 평가 모순. §16 이 평가 재설계를 범위 밖으로 둔다 |
| STRUCTURAL-116 | 뒷면 몬스터가 뒤집히지 않는다 |
| STRUCTURAL-118 | `ACTIVATE_EFFECT` 가 `withheld` 에 안 남는다. 지금은 **후보로 올라가므로** 이유를 적을 필요가 줄었지만, 범위 밖 발동의 이유는 여전히 `withheld` 에 없다 |
| STRUCTURAL-120 | `EFFECT_LIBRARY` 16개 전부 비용 없음 — 비용 경로 미주행 |
| STRUCTURAL-34 | 우선권을 누가 여는가. **그래서 응답 루프를 연결하지 않았다** |
| STRUCTURAL-55 | 발동은 `ActionHandler` 가 아니다 — 유지한 것이지 해결한 것이 아니다 |
| STRUCTURAL-56 · 47 · 7 · 16 · 51 | 범위 밖 |

### 새로 확인됨

| ID | 내용 | 근거 |
|---|---|---|
| **STRUCTURAL-121** | `PlayerAction` 에서 `TargetSelection` 으로 가는 길이 없다. `PlayerAction.targets`(`ActionTarget`)와 `EffectActivator` 가 받는 `selections`(`TargetSelection`)가 **다른 타입**이고 변환이 없다. 그래서 대상이 있는 효과 8개가 후보가 될 수 없다 | `test_06`·`Duel._activation_actions` |
| **STRUCTURAL-122** | 평가가 **드로우를 손해로 읽는다** (덱 300 > 패 200). 그래서 탐색이 욕망의 항아리를 한 번도 고르지 않는다. 가중치가 틀린 것이 아니라 "뽑은 카드로 무엇을 할 수 있는가" 를 담는 항이 없는 것이고, Depth-1 로는 볼 수 없다 | `test_27` — 측정값 −400 |
| **STRUCTURAL-123** | 규칙 기반이 **알파벳 순서 때문에** 발동을 고른다 (`"activate_effect" < "end_phase"`, 둘 다 0점). 발동을 보는 규칙은 하나도 없다 | `test_28` |
| **STRUCTURAL-124** | 체인이 **한 링크로 끝난다.** `_apply_activation` 이 발동 직후 바로 해결하므로 상대의 응답이 들어갈 자리가 없다. `ResponseLoop` 는 있지만 여는 규칙이 없어서 (STRUCTURAL-34) 연결하지 않았다 | `Duel._apply_activation` |

추측한 것은 없다. 넷 다 실행되는 주장 또는 코드 위치로 고정했다.

---

## 13. 범위 밖으로 둔 것

Damage Step · Battle Step 세부 · CHANGE_POSITION · Flip Summon · 모든 카드
효과 · Trigger/Quick/Continuous Effect · Replacement · 복잡한 target
selection · random effect · determinization · MCTS · Depth-2 · RL · NN ·
deck builder · UI · Discord — 전부 손대지 않았다.

**우선권과 응답 루프도 연결하지 않았다.** `ResponseLoop` 는 존재하지만 "누가
언제 응답 기회를 여는가" 가 정해지지 않았고 (STRUCTURAL-34), 없는 규칙을
지어내면 틀린 채로 굳는다.
