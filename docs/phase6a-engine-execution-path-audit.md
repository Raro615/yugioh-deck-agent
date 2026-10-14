# Phase 6-A — 갈라테아 게임 엔진 실행 경로 조사 및 구현 로드맵

- 기준 커밋: `607a4a2` (Phase 5-D `/combo`)
- 작업 브랜치: `claude/pensive-goodall-te1egy`
- 🔴 **조사 및 설계만 수행했다.** 프로덕션 코드 변경 **0건** (§10).
- 결론의 근거는 전부 **실제 코드 경로 · 실측 실행**이고, 추측은 "🔮 추측"
  으로 표시했다.

---

## 0. 먼저 — 내가 이전 단계에서 보고한 내용 중 틀린 것

🔴 **Phase 4-C · 5-D 보고서의 다음 서술은 틀렸다.** 그 보고서들은 `deck/`
계층에서 본 것을 **엔진의 한계로 적었다.**

| 이전 보고 | 실제 (이번에 실행해서 확인) |
|---|---|
| "체인·타이밍 처리가 없다" | ❌ 틀렸다. `engine/chain.py`(715줄) · `priority.py`(538) · `timing.py`(436) · `response.py`(676) · `activation_timing.py`(570) 가 있고 **체인이 실제로 쌓이고 LIFO 로 해결된다** |
| "효과를 발동하는 행동 모델이 없다" | ❌ 틀렸다. `ACTIVATE_EFFECT` 가 `accepted=True` · `code=OK` 로 적용되고 체인 1 을 만든다 |
| "효과 해결 시 게임 상태가 변경되지 않는다" | ❌ 틀렸다. 실측: 욕망의 항아리 발동 → 패 5→4 · SZONE 0→1 → 양쪽 패스 → **패 4→6 · 덱 16→14 · 묘지 0→1** |
| "실제 게임 상태 실행 검증이 없다" | ⚠️ 절반만 맞다. **엔진에는 있다.** 없는 것은 `ComboPlanner` 가 그것을 **부르지 않는다**는 사실이다 |
| "`ACTIVATE_CARD` 가 V1 에서 무효" | ✅ 맞다. 다만 그것은 **다른 어휘**다 — 효과 발동은 `ACTIVATE_EFFECT` 이고 그쪽은 동작한다 (`engine/action.py:83`, Phase 3-F-23 이 정정) |

실측 1판 (12종 덱, seed=7, 137걸음, P1 승 — LP 0):

```
legal_actions 에 등장: ACTIVATE_EFFECT 8 · END_PHASE 110 · PASS 16
                      NORMAL_SUMMON 28 · SET_MONSTER 28 · SET_SPELL_TRAP 7 · ATTACK 42
실제 적용 126건 → accepted=True 126건 / code=OK 126건
withheld: ACTIVATE_CARD 96건 (missing="activation-timing (Phase 2-C/2-F)")
```

**엔진은 이미 실행된다.** 이번 조사의 실제 질문은 "엔진이 실행하는가" 가
아니라 **"어디까지 실행하고, 기르수는 왜 그 안에 들지 못하는가"** 다.

---

## 1. 현재 게임 엔진의 전체 실행 구조

### 실제 호출 흐름 (`engine/duel.py`)

```
Duel.start(repo, decks=[list,list], seed=…)          ← seed 필수
   GameState.create(…, shuffle=True) → state.draw(seat, 5) ×2 → Phase.DRAW
   returns Duel(state, priority=PriorityState.idle(...), step=TurnStep.OPEN)

Duel.advance()      ← 고르지 않아도 일어나는 일 (드로우 · 페이즈 전환)
Duel.legal_actions(seat) -> LegalActions(seat, allowed=(…), withheld=(…))
   ├ _flow_actions          END_PHASE · PASS
   ├ _activation_actions    ACTIVATE_EFFECT   ← _activation_sources + _activation_gate
   ├ _attack_actions        ATTACK
   └ _withheld_board_actions
Duel.apply(action) -> DuelStep(action, accepted, code, reason, result)
   ├ PASS            → _apply_pass → (양쪽 연속 패스면) _resolve_chain
   ├ END_PHASE       → _apply_end_phase → TurnProgressor
   ├ ACTIVATE_EFFECT → _apply_activation → EffectActivator → Chain 에 링크
   └ 그 밖           → _apply_board → ActionExecutor (NormalSummonHandler 등)
Duel.result -> DuelResult(winner, reason)
```

`Duel` 의 칸: `state` · `priority` · `chain` · `step` · `first_player` ·
`_executor` · `_activator` · `_resolver` · `_placement` · `pending_spells`.
🔴 **`EventJournal` 칸이 없다** — 이것이 §5 의 핵심이다.

### `Duel` 이 import 하는 엔진 모듈 (AST 로 확인)

`action` · `action_execution` · `action_target` · `action_validation` ·
`activation_timing` · `chain` · `game_state_view` · `priority` · `response` ·
`spell_activation` · `state.game_state` · `state.rule_usage` · `summon` ·
`target_bridge` · `turn_progression` · `validation` · `vocabulary`

### 🔴 만들어졌지만 **배선되지 않은** 계층 (production 호출자 0개)

| 모듈 | 줄 | 역할 | 부르는 곳 |
|---|---|---|---|
| `engine/event_pipeline.py` | 500 | `StateDelta`/`JournalEvent` → `TimingEvent` | **테스트뿐** |
| `engine/trigger.py` | 1,661 | `TriggerCollector` · `TriggerEligibilityJudge` | **테스트뿐** |
| `engine/trigger_order.py` | 443 | 컨트롤러별 정리·순서 | **테스트뿐** |
| `engine/trigger_chain.py` | 594 | 후보 → `ChainLink` | **테스트뿐** |
| `engine/timing.py` | 436 | `TimingCoordinator` (창 하나로 묶기) | **테스트뿐** |

`engine/summon.py:47-48` 과 `engine/response.py:36` 이 **스스로 적어 두었다**:
"이 파일에는 `TriggerCollector` 도 `Chain` 도 `ChainResolver` 도 없다",
"이 모듈은 `TriggerCollector` 도 `TriggerChainIntegrator` 도 부르지 않는다".
의도된 경계였고, **그 둘을 잇는 자리가 아직 없다.**

### 구성 요소별 조사 (§3)

| 구성 요소 | 목적 | 실제 지원 | 호출 경로 | 미연결 | 입·출력 계약 |
|---|---|---|---|---|---|
| `GameState` (`state/game_state.py` 548줄) | 판의 모양 | 존·패·덱·묘지·LP·턴·seed·`clone()`·`state_hash()` | `Duel.state` | `chain`/`pending`/`journal` 칸은 **앞으로도 안 채운다** (흐름은 판 밖) | `create(repo, decks, life_points, turn_player, seed, shuffle)` |
| `PlayerAction` (`action.py` 398줄) | 고르는 주체의 행위 | 11종 `PlayerActionKind`, `to_dict()`/`from_dict()` | 정책 → `Duel.apply` | — | 불변 dataclass |
| `ActionValidator` (`action_validation.py` 1,551줄) | 확실한 위반 잡기 | `VALID`/`INVALID`/`UNKNOWN` 3치 + `UnimplementedRule` | `Duel.legal_actions` | `SPECIAL_SUMMON` 은 `:116`·`:520`·`:581` 에서 **언제나 `UNKNOWN`** | `ValidationResult(code, reason, unchecked_rules…)` |
| `Duel` (`duel.py` 1,035줄) | 한 판 | 소환·세트·공격·발동·체인해결·페이즈·승패 | 최상위 | journal 없음, 트리거 미배선 | 위 §1 |
| `DuelRunner` (`agent/runner.py:154`) | 정책 2개로 자동 진행 | `step()`·`run()`·`Transcript` | `agent/arena.py` | — | `step() -> TranscriptEntry\|None` |
| 효과 실행 (`effect/executor.py` 2,040줄) | 판을 바꾸는 유일한 문 | `OPERATION_HANDLERS` 12종 | `ChainResolver` ← `Duel._resolve_chain` | `journal=None` 으로 생성됨 | `EffectResult(deltas…)` |
| 효과 목록 (`effect/library.py` 1,227줄) | 등재된 효과 정의 | **16항목 / 실행 13장** | `duel_activator()`·`duel_resolver()` | 🔴 **16/16 이 전부 `('ACTIVATE',)` 모양** | `LibraryEntry(definition, executable, lua_file…)` |
| 효과 분석 (`analysis/`) | 카드 **설명** | Lua 블록 구조화 | `/search`·`/deck` | 🔴 **엔진과 잇는 계약이 없다** | `EffectSpec` |
| 규칙 지식 (`rules/`·`rulings/`) | 룰북·공식 재정 | 구조화 룰북 + 686파일 | `deck/validator.py` | 🔴 `engine` 은 `rules` 를 **import 하지 않는다** (의도) | `RuleDocument` |
| `ComboPlanner` (`deck/planner.py` 345줄) | 정적 전개 후보 | 걸음 생성 | `/combo`·CLI | 🔴 엔진 **실행 0건** | `ComboPlan` |
| `StepStatus` | 걸음의 확실성 | 4값 | `deck/` 전용 | 엔진의 `ValidationCode` 와 **다른 어휘** | — |
| `RULE_NOT_IMPLEMENTED` | 미구현 표기 | `ValidationCode` 멤버 | 엔진 내부 | 플래너는 **보지 않는다** | — |

기존 테스트 규모: `tests/engine/` **2,828 passed (82초)**.

---

## 2. 실제 실행 가능한 기능과 미구현 기능

### ✅ 실행된다 (실측)

| 기능 | 근거 |
|---|---|
| 듀얼 시작·셔플·5장 드로우·선공 첫 턴 드로우 없음 | `Duel.start`, 룰북 4문장 |
| 페이즈 전환·턴 넘김 | `TurnProgressor`, END_PHASE 69회 적용 |
| **일반 소환** (통상 몬스터) | 패 5→4 · MZONE 0→1 · **소환권 소모 확인** (재소환 후보 사라짐) |
| 세트 (몬스터·마법/함정) | `SET_MONSTER` · `SET_SPELL_TRAP` 적용됨 |
| 공격 | `ATTACK` 42회 후보 / 20회 적용 |
| **효과 발동 → 체인 → LIFO 해결 → 상태 변경** | 욕망의 항아리: 패 5→4→6 · 덱 16→14 · 묘지 0→1 |
| 발동 직후 상대 응답 창 | "상대의 응답을 기다립니다" (STRUCTURAL-34 절반) |
| 승패 판정 | LP 0 · 덱아웃 |
| 재현(리플레이) | seed + 덱 + accepted 행위 순서 + `advance()` 끼우기 (Phase 3-F-19 계약) |

### ❌ 미구현 — 실측 수치와 함께

| 항목 | 수치 | 코드 위치 |
|---|---|---|
| **일반 소환이 허가되는 메인덱 몬스터** | **542 / 7,067 = 7.7%** | `summon_rules.py:195` |
| ↳ 효과 몬스터 (소환 제약 못 읽음) | **4,311 (61.0%)** `UNDETERMINED` | `summon_rules.py:195-205` |
| ↳ 레벨 5+ (제물 절차 없음) | 2,066 (29.2%) `NEEDS_TRIBUTE` | `summon_rules.py:185` |
| ↳ 토큰·의식 | 148 (2.1%) `FORBIDDEN` | `NEVER_NORMAL_SUMMONABLE` |
| **효과 실행 구현이 등재된 카드** | **13 / 14,127 = 0.09%** | `effect/library.py` |
| ↳ 등재 효과의 블록 모양 | 🔴 **16/16 이 `('ACTIVATE',)`** — `TRIGGER_O`·`IGNITION`·지속 **0개** | 측정 |
| 특수 소환 판정 | 언제나 `UNKNOWN` | `action_validation.py:581` |
| 융합·싱크로·엑시즈·링크 | 절차 **없음** | `special_summon.py` (이름조차 없다) |
| 조건 술어 | 🔴 **3개뿐** — `IsMonster` · `IsSpellTrap` · `IsTurnPlayer` | `condition/model.py` |
| 토큰 생성 | `OperationKind` 에 `TOKEN` **없음** (12종) | `effect/operation.py` |
| 몬스터 효과 스펠 스피드 | `UNKNOWN` (입도 불일치) | `activation_timing.py:33-69` |
| `ACTIVATE_CARD` | 96건 전부 `withheld` | `missing="activation-timing"` |
| 파괴 실행 | 판정 계층 없어 `UNCHECKED_RULES` | `effect/semantics.py` |

---

## 3. `DuelRunner.step()` 분석

🔴 **먼저 이름 정정**: `DuelRunner` 는 `engine/` 에 없다. `agent/runner.py:154`
에 있고, 엔진의 실행기는 `engine.duel.Duel` 이다.

### 계약 (`agent/runner.py:176-215`)

```python
def step(self) -> "TranscriptEntry | None":
    if self.duel.is_over:            return None          # ① 끝
    if self.duel.advance() is not None:                   # ② 고르지 않아도 되는 일 먼저
        self._rule_steps += 1;       return None
    seat   = self.duel.to_act
    legal  = self.duel.legal_actions(seat)
    chosen = policy.decide(self.duel.view(seat), legal)   # ③ 관측+후보만 넘긴다
    decision = self._judge(seat, policy, legal, chosen)   # ④ 정책의 말은 허가가 아니다
    if not decision.accepted:  return self._record(decision, at=at)
    applied: DuelStep = self.duel.apply(decision.action)  # ⑤ 실행
    return self._record(Decision(...applied.accepted, applied.reason...), at=at)
```

- **중단 위치**: `step()` 자체는 중단하지 않는다. `None` 을 돌려주는 자리가
  둘이고 (①끝 ②규칙 진행), 호출자 `run(max_steps=MAX_STEPS)` 가 상한에서
  멈춘다.
- **검증 결과와 실행 결과를 따로 표현하는가**: 부분적이다. `_judge` 의
  `Decision.accepted`(정책 규약 위반)와 `DuelStep.accepted`(엔진 거부)가
  **같은 `TranscriptEntry.accepted` 칸에 들어간다** — Phase 4-C 가 보고한
  분류 결함 그대로다. 다만 `DuelStep.code`(`ValidationCode`)가 따로 있어
  **새 칸 없이도 가를 수 있다.**
- **실행 후 `GameState` 확인**: 가능하다 (`duel.state`, `duel.view(seat)`).
- **리플레이**: `Transcript` docstring(`:88-116`)이 계약을 못박는다 —
  seed · 덱 · accepted `PlayerAction` 순서 · `advance()` 끼우기 **네 가지**.
  `ChainResolution`·`EffectResult` 는 **필요하지 않다** (runtime transient).
  🔴 그러므로 리플레이는 **행위 수준**이고 **사건 수준이 아니다** — Duel
  Simulator 가 필요로 하는 카드 이동·체인 해결 이벤트 기록은 §5 의 journal
  배선이 없으면 만들 수 없다.

---

## 4. 일반 소환 및 효과 실행 경로 (§4-A · §4-B)

### A. 일반 소환

| 질문 | 답 | 근거 |
|---|---|---|
| 조건 판정은 어디서? | `engine/summon_rules.py::assess_normal_summon(definition)` **한 곳** | Phase 2-I |
| 패→필드 이동이 일어나는가? | ✅ 실측 패 5→4, MZONE 0→1 | `SummonProcedure` ← `NormalSummonHandler` |
| 소환권이 소모되는가? | ✅ 같은 턴 `NORMAL_SUMMON`/`SET_MONSTER` 후보가 사라진다 | `RuleUsageRegistry` |
| 소환 후 유발 효과가 처리되는가? | ❌ **아니다.** `MonsterSummoned` 는 남지만 `Duel` 에 journal 이 없고 트리거 계층이 배선되지 않았다 | §1 표 |
| 테스트로 확인된 것 | `tests/engine/` 2,828개 통과. 통상 몬스터 소환·소환권·절차 | — |
| 🔴 확인되지 않은 것 | **효과 몬스터의 소환 자체** (61% `UNDETERMINED`) | `summon_rules.py:195` |

소환권 소모 뒤 `withheld` 가 **비어 있다** — 거절된 소환이 기록되지 않는다.
"빈 칸을 남기지 않는다" 는 이 저장소의 다른 자리와 어긋난다. (관찰, 차단
요소는 아니다.)

### B. 효과 발동 및 해결

| 질문 | 답 | 근거 |
|---|---|---|
| 발동 행동 모델이 있는가? | ✅ `PlayerActionKind.ACTIVATE_EFFECT` | `action.py:90` |
| 발동 조건과 비용을 구분하는가? | ✅ 구분한다. `cost/`(5파일 1,245줄)가 비용, `condition/`(5파일 1,470줄)이 조건, `payment.py`(638줄)가 지불. 순서도 규칙이다 — **읽기 검사 전부 → 체인이 받을 수 있는지 → 그 뒤에 비용** (ADR-008) | `activation.py` |
| 대상·기타 선택을 표현하는가? | ✅ `TargetRequirement` 4종 (`NONE`·`TARGETING`·`CHOOSING`·`RANDOM`), `SelectionCount` 3종 (`FIXED`·`DERIVED`·`UNKNOWN`) | Phase 2-N·2-AB·2-AC |
| 해결 시 상태가 바뀌는가? | ✅ 실측 (욕망의 항아리) | §0 |
| 실행 구현의 범위 | **13장 / 0.09%**, 전부 마법. 🔴 **블록 모양이 16/16 `ACTIVATE`** | 측정 |
| 분석 데이터 ↔ 실행 효과의 계약이 있는가? | ❌ **없다.** `analysis.effect_model.ActionKind` 와 `engine.PlayerActionKind` 는 의도적으로 **다른 어휘**(ADR-001)이고, `EFFECT_LIBRARY` 는 **손으로** 쓴다 (ADR-006) | `engine/__init__.py` 말미 |

마지막 줄이 이 프로젝트의 중심 병목이다: **Lua 분석 결과를 실행 가능한
`EffectDefinition` 으로 옮기는 자동 경로가 없다.** 14,127장을 손으로 쓸 수는
없다.

---

## 5. 특수 소환과 체인 처리의 구조적 장애물 (§4-C · §4-D)

### C. 특수 소환

- **`UNKNOWN` 의 구조적 원인**: `action_validation.py:581` 이 마지막 요구로
  `UnimplementedRule("special-summon-condition (카드마다 다르다)")` 를 붙인다.
  "이 카드를 특수 소환할 수 있는가" 는 **카드 텍스트의 소생 제한·정규 소환
  여부·턴 1회**가 정하고, 그것을 읽는 계층이 없다.
- **조건을 표현하는 모델은 있는가**: `condition/model.py`(1,009줄)에 모델은
  있다. 🔴 그런데 **술어가 3개뿐**이어서 실제 카드의 조건을 적을 수 없다.
- **효과에 의한 특수 소환 ↔ 절차에 의한 특수 소환을 구분하는가**: ✅ 한다.
  `SpecialSummonOperation`(효과 해결) 과 `PlayerActionKind.SPECIAL_SUMMON`
  (선언)은 다른 어휘이고, 둘 다 `SummonProcedure` 를 **같은 코드로** 쓴다
  (Phase 2-T·2-U).
- **융합·싱크로·엑시즈·링크 선택 절차**: ❌ **표현이 없다.**
  `special_summon.py` 에 그 이름이 아예 없다 (STRUCTURAL-62).
- **최소 변경**: 🔮 추측 — `SummonRuling` 관문(이미 있는 `UnknownSummonRuling`
  자리)에 **카드가 선언한 조건만** 답하는 구현을 넣는 것. 새 계층이 아니라
  기존 관문의 구현체 하나다. 다만 **조건 술어가 먼저 필요하다** (아래 §6).

### D. 체인과 타이밍

| 질문 | 답 |
|---|---|
| 체인 모델 수준 | ✅ `Chain`·`ChainLink` 불변, LIFO 해결, `ChainResolver` 동작 |
| 타이밍 모델 수준 | 모델은 `TimingWindow`·`TimingCoordinator` 로 **있다**. 🔴 그러나 **부르는 곳이 없다** |
| 발동 / 체인 추가 / 체인 해결을 구분하는가 | ✅ 셋이 다른 자리다 (`activation.py` / `Chain.add` / `ChainResolver`) |
| 우선권·응답 선택 | ✅ `PASS` 와 `ACTIVATE_EFFECT` 둘로 동작. 양쪽 연속 패스 → `RESOLVE` |
| 🔴 실행을 막는 구조적 항목 | **사건(event) → 트리거 → 체인 배선 부재**. `Duel` 에 `EventJournal` 칸이 없고, `duel_resolver()` 가 `build_executor()` 를 **journal 인자 없이** 부른다 (`spell_activation.py:417-423`) → `EffectExecutor._journal is None` → deltas 가 journal 에 적히지 않는다. `Duel._resolve_chain` 도 `resolution.deltas` 를 **읽지 않는다** (`duel.py:728-758`) |

---

## 6. 기존 구조적 TODO 검토 (§5)

| TODO | 사용자 제시 설명 | 코드에서 확인한 현재 상태 | 실행 경로를 막는가 |
|---|---|---|---|
| **STRUCTURAL-15** | 숨겨진 영역의 `UNKNOWN` 처리 | **절반 해결** (Phase 2-N). `unchecked` 가 `CandidateSet` 까지 올라오고 비용 쪽이 아직 읽지 않는다. Phase 2-Y 의 `looked_at` 이 "자기 덱 들여다보기" 를 열었다 | ❌ 아니다 — 개별 카드 시나리오에서 드러날 문제 |
| **STRUCTURAL-34** | 우선권 갱신 주체 부재 | **절반 구현됨** (Phase 3-E-11·3-E-12). 발동 직후 상대에게 RESPONSE 창이 열리고 실제 후보가 생성된다. 🔴 남은 절반: **페이즈 전환 시점과 체인 종료 뒤** 창을 여는 규칙이 없다 | ⚠️ **부분적으로 막는다** — 상대 턴 세트 함정 발동이 그 때문에 불가 |
| **STRUCTURAL-35** | `TimingWindow` 단일 사건 모델 | 유지. SEGOC(동시 사건을 한 창으로)의 전제가 없다 | ❌ 지금은 아니다 — 트리거가 배선된 **뒤에** 문제가 된다 |
| **STRUCTURAL-36** | `outcome.chain` 의 게임 상태 연결 | 유지. `TimingOutcome.chain` 은 준비된 체인일 뿐 채택 주체가 없다 | ⚠️ **§5 의 배선과 같은 뿌리** |
| **STRUCTURAL-77** (추가 확인) | `Card.IsSetCard` = 아키타입 술어, **단독 병목 148장** (2위의 7배) | 유지. 조건 술어 3개에 아키타입이 없다 | 🔴 **막는다** — 기르수 ①이 바로 이것 |
| **STRUCTURAL-103** | 우선권 창이 한 번도 열리지 않는다 | **해소됨** (3-E-11 이후 실제로 열린다, 실측 PASS 16회) | ✅ 아니다 |

🔴 **결론**: 사용자가 제시한 4개 중 **실행 경로를 직접 막는 것은
STRUCTURAL-34 의 남은 절반과 36 둘뿐**이고, 둘 다 §5 의 배선과 같은 뿌리다.
15·35 는 개별 카드 시나리오 단계의 문제다. 그리고 **목록에 없던
STRUCTURAL-77(아키타입 술어)이 기르수의 실제 차단 요인**이다.

---

## 7. 기르수 실제 Discord 사례의 단계별 실패 원인 (§6)

`잭나이츠 오르페골 기르수` `69811710` — **레벨 4 · 기계족 · 어둠 · 1800/0 ·
메인 덱 효과 몬스터** (링크가 아니다). 실제 Lua 블록:

| 블록 | 모양 | 공식 텍스트 |
|---|---|---|
| ① | `['SINGLE','TRIGGER_O']` `EVENT_SUMMON_SUCCESS` cat=`TOGRAVE` prop=`DELAY` cl=`1,id` | 일반/특수 소환했을 경우 발동할 수 있다. **덱에서 "오르페골" 카드나 "성유물" 카드 1장을 묘지로** 보낸다 (+ 같은 세로열 조건으로 튜너 취급) |
| ②(동일) | `EVENT_SPSUMMON_SUCCESS` | 위와 같은 효과의 특수 소환 쪽 |
| ③ | `['IGNITION']` ranges=`['MZONE']` cat=`SPECIAL_SUMMON`+`TOKEN` cl=`1,{id,1}` | 자신 필드에 다른 몬스터가 없을 경우 발동. **서로의 필드에 "성유물 토큰" 1장씩**을 수비 표시로 특수 소환 |
| ④ | `['SINGLE']` `EFFECT_ADD_TYPE` prop=`CANNOT_DISABLE` | 튜너 취급 |

### 🔴 실측: 패에 기르수 5장, MAIN1, 허가된 행위는 `END_PHASE` 하나뿐

```
P0 패: 기르수 ×5 | 페이즈: MAIN1 | 차례: 0
허가: ['END_PHASE']
보류: ACTIVATE_CARD (missing="activation-timing") — 그것뿐
```

**`NORMAL_SUMMON` 은 허가도 보류도 아니다. 아예 없다.**

### 단계별 분석

| # | 목표 단계 | 구현 여부 | 담당 구성 요소 | 검증 근거 | 실행 차단 원인 | 필요한 최소 변경 |
|---|---|---|---|---|---|---|
| 1 | 초기 패에 기르수 존재 | ✅ 구현 | `GameState.create`·`draw` | 실측 패 5장 | — | — |
| 2 | 일반 소환 가능 여부 판단 | ✅ 판단은 한다 | `assess_normal_summon` | `summon_rules.py:195-205` | 🔴 **효과 몬스터 → `UNDETERMINED`**, `missing_rule="summoning-condition"`. `ORDINARY` 만 허가가 된다 | 카드 텍스트의 **소환 제약을 읽는 계층**. 🔮 추측: 대부분의 효과 몬스터는 제약이 없으므로 "제약 선언이 있는 카드만 거른다" 가 가능할 수 있으나, **그 선언을 Lua 에서 읽는 근거를 먼저 측정해야 한다** |
| 3 | 일반 소환 실행 | ⚠️ 코드는 있다 | `SummonProcedure`·`NormalSummonHandler` | 통상 몬스터로 실측 성공 | 2번이 허가를 내주지 않아 **도달하지 않는다** | 2번과 동일 |
| 4 | 패·필드 상태 갱신 | ✅ 구현 | `SummonProcedure` | 패 5→4 · MZONE 0→1 (통상 몬스터) | — | — |
| 5 | 소환 후 발동 가능 효과 확인 | ❌ **미구현** | `trigger.py`·`event_pipeline.py` 가 **있으나 배선 안 됨** | `Duel` import 목록에 없음 | 🔴 **`Duel` 에 `EventJournal` 칸이 없다** → 사건이 트리거 수집기에 도달하지 못한다 | **Phase 6-B**: `Duel` 에 journal 칸 + `EventReader` → `TriggerCollector` → `TriggerChainIntegrator` 배선 |
| 6 | 발동 조건·선택 절차 처리 | ❌ **미구현** | `condition/`·`cost/`·`effect/target.py` | 조건 술어 **3개**, 라이브러리 블록 **16/16 `ACTIVATE`** | 🔴 ① **`TRIGGER_O` 효과 정의가 0개** ② **아키타입 술어 없음**("오르페골"/"성유물" 판정 불가 = STRUCTURAL-77) ③ 몬스터 효과 스펠 스피드 `UNKNOWN` | 아키타입 술어 1개 + `TRIGGER_O` 모양의 `EffectDefinition` 1개 (카드별 데이터, 구조는 공용) |
| 7 | 해결 후 카드 위치 갱신 | ⚠️ 기반은 있다 | `SEND_TO_GRAVE` operation + `MovementRuling` | 어리석은 매장이 같은 경로로 관문까지 간다 | 🔴 ①은 **덱에서** 보낸다 → `Card.IsAbleToGrave` 관문 + 덱 관측(`looked_at` 으로 열림) | 관문 구현 (추측 금지 영역) |
| 8 | 후속 행동 조사 | ❌ 미구현 | — | — | 5~7 이 선행 | — |
| ③ 쪽 | 토큰 특수 소환 | ❌ **미구현** | — | `OperationKind` 12종에 **`TOKEN` 없음** | 🔴 토큰은 카드가 아니라 **생성되는 객체**다. `CardInstance` 가 `card_id` 를 요구한다 | 별도 단계 (토큰 모델) |

🔴 **가장 중요한 정정**: `/combo` 는 1걸음을 `확정 (엔진이 이 행위를 허가함)`
으로 적었다. **엔진은 그 소환을 허가하지 않는다.** `deck/planner.py` 의
`ENGINE_ACTION` 근거는 `card.is_monster` 만 보고 `assess_normal_summon` 을
부르지 않는다 — 직전 단계에서 고친 `has_effect_from("HAND")` 과 **같은
종류의 과대 진술**이고, 이번에는 소환 쪽이다.

---

## 8. 콤보 플래너와 게임 엔진 연결 방안 (§7)

### 지금의 단절

`deck/planner.py` 는 `engine.effect.library.EFFECT_LIBRARY` **하나만** import
하고, 그것도 `executable=True` 카드 ID 집합을 만드는 데만 쓴다. `Duel` ·
`GameState` · `ActionValidator` 호출이 **0건**이다 (AST 확인).

### 발전 방향 — 새 엔진을 만들지 않는다

| 필요 기능 | 기존 엔진의 무엇을 쓰는가 | 새로 만들 것 |
|---|---|---|
| 현재 상태에서 가능한 행동 후보 | **`Duel.legal_actions(seat)`** 그대로 | 없음 |
| 각 후보의 합법성 검증 | `legal_actions` 가 이미 `VALID` 만 담는다 | 없음 |
| 행동 실행 후 상태 생성 | `GameState.clone()` → `Duel.apply()` | 없음 |
| 여러 경로 탐색 | `agent/search.py`(381줄)가 이미 있다 | 탐색 ↔ 상태변경 **분리 유지** |
| 최종 필드 비교 | `GameState.state_hash()` · `agent/evaluation.py` | 없음 |
| 전개 불가 지점 판정 | `LegalActions.withheld` + `DuelStep.code` | 없음 |

🔴 **원칙 유지 방법**: `ComboPlanner` 가 규칙을 재구현하지 않게 하려면, 지금의
정적 경로를 **지우지 않고** 실행 경로를 **나란히** 두고 판정만 바꾸는 것이
안전하다 —

- 정적 경로 → `ComboVerdict.GROUNDED_UNEXECUTED` (지금과 같다)
- 실행 경로 → **그때 처음으로** `VERIFIED` 가 의미를 갖는다
- 🔴 실행 경로에서 돌린 전개만 "실행 검증됨" 으로 표시한다

둘을 합치면 "실행 안 된 것" 이 "실행된 것" 으로 보이게 되고, 그것이 이
프로젝트가 계속 거부해 온 실패 모양이다.

---

## 9. Phase 6-B 이후 단계별 개발 로드맵

🔴 **수직 경로를 먼저 뚫는다.** 각 단계가 끝나면 **기르수 시나리오가 한
걸음 더 간다**는 것이 순서의 기준이다. 카드별 예외 처리로 단계를 구성하지
않는다.

### Phase 6-B — 사건 → 트리거 → 체인 배선 (**가장 먼저**)

1. **단계명**: Duel 에 사건 통로를 잇는다
2. **구현 목표**: `Duel` 이 `EventJournal` 을 들고, 상태 변화가
   `EventReader` → `TriggerCollector` → `TriggerEligibilityJudge` →
   `TriggerOrder` → `TriggerChainIntegrator` 를 거쳐 **체인에 오를 수 있게**
   한다. 🔴 **새 규칙을 만들지 않는다** — 다섯 계층은 이미 있다.
3. **수정 구성 요소**: `engine/duel.py` (journal 칸 + 배선),
   `engine/spell_activation.py::duel_resolver` (`build_executor(journal=…)`)
4. **선행 조건**: 없음. **지금 바로 가능하다.**
5. **구조적 위험**: ⚠️ `state_hash()` 에 journal 이 섞이면 "같은 판은 경로와
   무관하게 같은 해시" 가 깨진다 → journal 은 `Duel` 칸이고 `GameState` 가
   아니다. ⚠️ STRUCTURAL-35(단일 사건 창)가 **여기서 처음 문제가 된다** —
   동시 사건은 이 단계에서 **한 창에 하나만** 넣고 그 한계를 기록한다.
6. **자동화 테스트 기준**: ① 통상 몬스터 소환이 `MonsterSummoned` 를 journal
   에 남긴다 ② 그 사건으로 `TriggerCandidate` 가 **0개 이상** 수집된다
   ③ 기존 2,828개가 **하나도 수정되지 않고** 통과 ④ `state_hash()` 가
   journal 과 무관함을 재확인
7. **실제 카드 시나리오**: 통상 몬스터 소환 → 사건 수집까지. 🔴 **기르수는
   아직 트리거 정의가 없어 후보 0개** — 그것이 올바른 결과다
8. **완료 판정**: 사건이 수집기에 **도달**하고, 등재된 트리거 정의가 없어
   후보가 0개라는 사실이 기록으로 남는다

### Phase 6-C — 아키타입 술어 (STRUCTURAL-77)

1. **단계명**: 조건 술어에 카드군을 더한다
2. **목표**: `Card.IsSetCard` 에 대응하는 술어 1개. 근거는 공식 setcode 이고
   `CardDefinitionView.setcodes` 가 **이미 있다**
3. **수정**: `engine/condition/model.py` (술어 1개 추가)
4. **선행**: 없음 (6-B 와 **병행 가능**)
5. **위험**: ⚠️ 측정된 병목 148장이 "단독 병목" 이라는 것은 Phase 2-AN 의
   측정이다. 🔮 추측: 술어가 생겨도 다른 관문이 남은 카드가 있을 수 있으므로
   **먼저 재측정**한다
6. **테스트**: 세 상태(`TRUE`/`FALSE`/`UNKNOWN`) + setcode 가 없는 카드가
   `UNKNOWN` 이 아니라 `FALSE` 인지 **공식 근거로** 결정
7. **실제 카드**: 기르수 ①의 "오르페골 카드" 판정이 `TRUE` 가 된다
8. **완료**: 술어 하나가 3치로 답하고, 병목 재측정 수치가 보고된다

### Phase 6-D — `TRIGGER_O` 효과 정의의 첫 사례

1. **단계명**: 유발 효과를 등재한다
2. **목표**: `EFFECT_LIBRARY` 에 **`TRIGGER_O` 모양**의 정의 1개. 🔴 현재
   16/16 이 `ACTIVATE` 이므로 **모양 자체가 처음**이다
3. **수정**: `engine/effect/definition.py`(필요 시 trigger 모양 표현),
   `engine/effect/library.py` (정의 추가)
4. **선행**: 6-B (배선) + 6-C (술어)
5. **위험**: 🔴 **몬스터 효과 스펠 스피드 `UNKNOWN`**. `activation_timing.py`
   가 입도 불일치를 명시한다 — `speed_of_link` 가 `effect_ref` 를 들고 있는데
   버리고 카드 단위로 묻는다 (`:51-63`). **그 한 줄이 효과 단위 정보를
   살리는 최소 변경**이고, 6-D 의 선행 과제로 분리할 가치가 있다
6. **테스트**: 등재된 유발 효과가 ① 사건에 반응해 후보가 되고 ② 조건이
   `FALSE` 면 후보가 **안 되고** ③ 비용·대상이 없으면 체인에 **안 올라가고**
   그 사실이 기록된다
7. **실제 카드**: 🔴 **기르수 ①을 등재하지 않는다.** 등재는 `SEND_TO_GRAVE`
   관문(§7-7)이 먼저 필요하다. 이 단계의 실제 카드는 **관문 없는 유발
   효과**를 코퍼스에서 측정해 고른다 — 없으면 **없다고 보고한다**
8. **완료**: 유발 효과 한 개가 사건→후보→(체인 또는 기록된 거절)까지 간다

### Phase 6-E — 효과 몬스터의 일반 소환

1. **단계명**: 소환 제약을 읽는다 (`summoning-condition`)
2. **목표**: 메인덱 몬스터의 일반 소환 허가를 **7.7% → 측정된 상한**까지
3. **수정**: `engine/summon_rules.py` (판정 분기), 소환 제약 데이터 출처
4. **선행**: 🔴 **측정이 먼저다.** Lua 에서 소환 제약을 읽을 근거가 무엇인지
   (`EFFECT_SPSUMMON_CONDITION`·`EFFECT_CANNOT_SUMMON`·텍스트) 코퍼스 조사
5. **위험**: 🔴 **가장 크다.** "대부분의 효과 몬스터는 제약이 없다" 를
   근거 없이 적으면 제약 있는 카드가 조용히 소환된다. 룰북 문장이
   "most Effect Monsters (**unless they have a specific restriction**)" 이고,
   그 예외를 읽지 못하면 `UNDETERMINED` 가 맞다
6. **테스트**: 제약이 **선언된** 카드가 `UNDETERMINED` 를 유지하고, 선언이
   없는 카드만 허가된다. 허가 비율 변화를 수치로 고정
7. **실제 카드**: 기르수가 **일반 소환된다** (2·3단계 통과)
8. **완료**: 기르수 일반 소환이 `legal_actions` 에 나오고, 제약 있는 카드가
   여전히 막힌다

### Phase 6-F — 콤보 플래너의 실행 경로

1. **단계명**: 전개를 **돌려서** 검증한다
2. **목표**: `ComboPlanner` 가 `Duel` 로 전개를 실행하고, 실행된 전개만
   `VERIFIED` 로 표시
3. **수정**: `deck/planner.py` (실행 경로 추가, **정적 경로 유지**),
   `app/discord_bot.py` (`ComboVerdict` 에 `VERIFIED` 추가)
4. **선행**: 6-B ~ 6-E
5. **위험**: ⚠️ 탐색 폭발. `agent/search.py` 를 쓰고 **깊이 상한을 값으로**
   받는다. ⚠️ 두 경로를 합치면 미실행이 실행으로 보인다 → 분리 유지
6. **테스트**: 실행된 전개만 `VERIFIED`, 실행 실패는 **원인 코드**
   (`DuelStep.code`)와 함께 남는다
7. **실제 카드**: 기르수 일반 소환 → ① 유발 → 묘지로 보내기까지 **실행**
8. **완료**: `/combo hand:잭나이츠 오르페골 기르수` 가 실행된 전개를 보여
   준다

### Phase 6-G 이후 (순서만 제안)

- **6-G** 체인·타이밍 완성 (STRUCTURAL-34 나머지 · 35 SEGOC)
- **6-H** 특수 소환 조건 (`SummonRuling` 구현체)
- **6-I** 소환법 절차 (융합·싱크로·엑시즈·링크) — **여기서 처음으로 현대
  유희왕 전개가 가능해진다**
- **6-J** 사건 수준 리플레이 출력 (Duel Simulator 변환의 전제)
- **6-K** 금지·제한 데이터 (OCG/TCG · 적용일 · 버전)
- **6-L** EDOPro 연동

🔴 **6-I 가 최종 목표의 문턱이다.** 그 전까지 갈라테아는 "통상 몬스터와
마법 13장으로 듀얼하는 AI" 이고, 그 사실을 숨기지 않는다.

---

## 10. 가장 먼저 구현해야 할 최소 실행 기능과 그 이유

### 👉 **Phase 6-B — `Duel` 에 사건 통로를 잇는다**

**이유 네 가지:**

1. **새 규칙을 만들지 않는다.** 다섯 계층(3,634줄)이 이미 있고 테스트도
   있다. 없는 것은 **자리**다 — Phase 2-AO 가 `Duel` 을 만들 때 쓴 문장이
   그대로 맞는다: *"없던 것은 규칙이 아니라 자리였다."*
2. **선행 조건이 없다.** 지금 바로 할 수 있는 유일한 단계다 (6-C 도 가능하나
   그것만으로는 실행이 한 걸음도 늘지 않는다).
3. **기르수 5단계의 유일한 차단 요인이다.** 소환(2단계)을 푸는 6-E 는 측정이
   먼저 필요하고 위험도 가장 높다. 배선은 **위험이 가장 낮으면서** 이후 모든
   단계(6-D·6-F·6-G·6-I·6-J)의 **공통 선행 조건**이다.
4. **사건 기록이 Duel Simulator·EDOPro 의 전제다.** 지금의 리플레이는 행위
   수준이고, 외부 연동이 필요로 하는 카드 이동·체인 해결 이벤트는 journal 이
   없으면 만들 수 없다 (§3).

**하지 말아야 할 것**: 기르수 효과를 먼저 등재하는 것. 배선 없이 등재하면
사건이 도달하지 않아 **영원히 후보가 되지 않는다** — "등재했는데 안 된다" 는
가장 비싼 실패 모양이다.

---

## 11. 수정 파일 여부와 Git 상태

🔴 **프로덕션 코드 변경 0건.** 이번 단계는 조사·설계만이다 (§10).

추가한 파일: `docs/phase6a-engine-execution-path-audit.md` (이 문서) 하나.

측정에 쓴 스크립트는 **저장소에 남기지 않았다** — 모든 수치는 이 문서에
적혀 있고, 재현 방법(덱 구성·seed)도 함께 적었다.

실행한 테스트: `tests/engine/` **2,828 passed (82.12s)** — 변경이 없으므로
회귀도 없다.

---

## 결론

**엔진은 이미 실행된다.** 효과 발동 → 체인 → 해결 → 상태 변경이 실제로
일어나고, 한 판이 승패까지 간다. 내가 이전 두 보고서에서 "엔진에 없다" 고
적은 것들은 대부분 **플래너가 부르지 않는 것**이었다.

실제 경계는 **세 수치**다:

- 일반 소환이 허가되는 메인덱 몬스터 **542 / 7,067 (7.7%)**
- 효과 실행 구현이 등재된 카드 **13 / 14,127 (0.09%)**
- 등재 효과의 블록 모양 **16 / 16 이 `ACTIVATE`** — 유발·기동·지속 **0개**

그리고 기르수가 멈추는 자리는 **두 곳**이다: 2단계(효과 몬스터의 일반
소환이 `UNDETERMINED`)와 5단계(사건이 트리거 계층에 도달하지 못한다).
앞의 것은 측정이 먼저 필요하고, 뒤의 것은 **지금 바로 배선할 수 있다.**

🔴 **Phase 6-B 구현을 자동으로 시작하지 않는다. 사용자 검토를 기다린다.**
