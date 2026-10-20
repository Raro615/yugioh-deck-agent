# Phase 6-AB — 유발 효과 실행·타이밍 BLOCKER 해소

## 1. 커밋과 변경 파일

| | |
|---|---|
| 시작 커밋 | `48d6921` (Phase 6-AA 최종) — 작업 트리 깨끗, 원격 동기 |
| 브랜치 | `claude/pensive-goodall-te1egy` |
| 최종 커밋 | §10 에 적는다 |

🔴 **검토 가능한 단위로 쪼갰다** — 근거 / 판정 / 사본 / 시험 / 회귀 정정 / 보고서.

### `08cfcd2` — 어휘 근거 (BLOCKER-6AB-B 의 규칙 근거)

| 파일 | +/− | 무엇을 |
|---|---|---|
| `core/card_model.py` | +64 | `ACTIVATION_WHEN_PHRASES` · `ACTIVATION_IF_PHRASES` · `activation_wording_text` · 출처 |
| `engine/trigger_compiler.py` | +59/−5 | `wording_from` · `TEXT_WHEN/TEXT_IF` · `compile_trigger_spec(text_wording=…)` |
| `integration/trigger_registry.py` | +3 | 카드 텍스트 값을 컴파일러에 넘긴다 |
| `integration/autonomy.py` | +37 | `TriggerOffer.wording` · `misses_timing` |

### `bbbaef5` — 공유 판정 · 수명 · 강제 보장 (A · B · C)

| 파일 | +/− | 무엇을 |
|---|---|---|
| `engine/duel.py` | +274/−30 | `_offer_is_activatable` · `_timing_is_current` · `_enforce_mandatory` · `activation_validator` 가 판정을 거친 제안만 관문에 넣는다 · `_mandatory_offers` 가 지나간 「때」 를 세지 않는다 · 상수 둘 |

### `9dc6b2c` — 탐색 사본 (D)

| 파일 | +/− | 무엇을 |
|---|---|---|
| `agent/simulation.py` | +78/−2 | `_forked_journal` · `_forked_chooser` |
| `engine/effect/executor.py` | +19 | `EffectExecutor.chooser` (읽기 전용) |
| `integration/autonomy.py` | +17 | `PolicyChooser.forked()` |

### `040d51a` — 시험 27개

`tests/engine/test_trigger_execution_and_timing.py` (새 파일, 865줄). 그 뒤
`1709f46` 이 `test_c06` 을 더해 **28개**가 됐다.

### `222c6dd` — 6-AB 가 바꾼 사실에 맞춰 기존 시험 다섯 정정

§9.2 의 표. 🔴 삭제 · skip · assertion 완화 **0건**.

### `1709f46` — 감사가 잡은 엔진 결함 둘

| 파일 | 무엇을 |
|---|---|
| `engine/duel.py` | 차례가 아닌 자리의 **거짓 보류**를 없앴다 (§5.3 의 결 · 실측) |
| `engine/spell_activation.py` · `agent/simulation.py` | 기록을 만드는 자리를 **하나로** 되돌렸다 (`seed_events`) |
| 시험 둘 | `test_c06` (새) · `test_i03` 의 표 |

### `820bf22` — 루트 감사 둘의 census 갱신

`tests/test_trigger_lifetime_audit.py` ·
`tests/test_rule_not_implemented_code_audit.py` — §9.2.

---

## 2. 구현 전 조사 — 무엇이 이미 있었고 무엇이 없었나

조사한 것: 6-AA 보고서와 그 BLOCKER 넷, `engine/trigger.py` 의 `TimingEvent`
· `TriggerRequirement` · `TriggerWording` · `UNRESOLVED_ORDER_RULES`,
**휴면 상태인** `engine/timing.py` 의 `TimingWindow` · `TimingCoordinator` ·
`WINDOW_UNRESOLVED_RULES`, `engine/trigger_compiler.py` 의 선언 종류,
`integration.autonomy.trigger_offers` 와 `TriggerSource`, `Duel` 의
`legal_actions` → `activation_validator` → `_activation_gate` →
`_apply_activation` 경로, `EventJournal` 의 식별자, `agent/simulation.py` 의
`_fork` · `_settle_forced_passes` · `state_hash`, `agent/search.py` 의 상태
비교, 그리고 룰북 데이터 (`data/rules/`).

### 2.1 이미 있던 것 — **재사용했고 다시 만들지 않았다**

| 있던 것 | 어디 | 6-AB 가 쓴 방식 |
|---|---|---|
| 「때 / 경우」 라는 **개념** | `TriggerWording` (WHEN/IF/UNKNOWN) | 그 enum 을 그대로 채웠다 — 새 enum 을 만들지 않았다 |
| 사건의 **순서 식별자** | `JournalEvent.sequence` | "마지막에 일어난 일인가" 를 이것으로 묻는다 — 새 상태를 만들지 않았다 |
| 유발 제안의 운반체 | `TriggerOffer` | 칸 하나(`wording`)와 읽기 하나(`misses_timing`)만 더했다 |
| 발동 관문 | `Duel._activation_gate` · `ActionValidator` | 판정을 **값으로** 넘기는 기존 통로(`event_backed`, 6-Z)를 썼다 |
| 해결 시점 선택 | `ResolutionChooser` · `PolicyChooser` | 계약을 넓히지 않고 **선택적** `forked()` 로 사본에 물려줬다 |
| 기록 한 벌 만들기 | `engine.spell_activation.duel_components(journal=…, chooser=…)` | 이미 `chooser` 를 받던 자리다 — 사본이 안 넘기고 있었을 뿐이다 |

🔴 **`engine/timing.py` 의 `TimingWindow` 계층은 쓰지 않았다.** 그 계층은
창(사건 + 보는 자리 + 턴 플레이어 + 페이즈 + 우선권 + 체인 스냅숏)을 들고
있고, 지금 필요한 질문("이 사건이 마지막인가")은 `EventJournal` 이 **이미**
답한다. 쓰지 않은 이유를 §6 에 적는다 — 그 계층이 필요해지는 자리는
BLOCKER-6AB-1 이다.

### 2.2 규칙 조사 — 룰북에 **없고** 공식 재정에 **있다**

| 질문 | 룰북 (`data/rules/`) | 찾은 근거 |
|---|---|---|
| 「때」 와 「경우」 가 다른가 | **없다** — `effect_types` 는 유발 효과의 발동 시점만 적고 두 어휘를 가르지 않는다 | 「때」 효과는 **그 사건이 마지막에 일어난 일**이어야 발동할 수 있다 (놓친 타이밍). 「경우」 효과는 그렇지 않다 |
| 체인 처리 중에 시점을 만나면 | **없다** | 그 체인이 **완전히 해결된 뒤**에 발동한다 (SEGOC) |

출처는 `core.card_model.Card.activation_wording_text` 의 설명에 적어 두었다
(Yugipedia *Optional Trigger Effect* · Yu-Gi-Oh! Wiki *Simultaneous Effects Go
On Chain*). 🔴 **저장소 데이터에 없다는 것을 공식 근거가 없다는 뜻으로 읽지
않았다** — 룰북에 없다고 적고, 재정을 찾아 출처를 남겼다.

### 2.3 🔴 재현 결과 — 리뷰가 제기한 우회가 **그대로 재현되지는 않았다**

6-AA 최종 HEAD `48d6921` 의 워크트리에서 직접 재어 본 값이다 (합성: 실제
`TriggerSource` 의 제안에서 `requirement` 만 `UNKNOWN` 으로 바꿔 끼웠다).

```
제안: 1
후보 목록에 있는가: False
event_backed: 1              ← 🔴 관문이 열어 두었다
관문 직접 질의: VALID / OK     ← 🔴 관문 자신은 판정하지 않았다
apply 직접 제출: 거절 (RULE_NOT_IMPLEMENTED)
차단 지점: Duel.apply — "activate_effect 는 지금 허가된 행위가 아닙니다."
```

읽는 법:

- **"UNKNOWN 유발이 직접 실행된다" 는 재현되지 않았다.** `Duel.apply` 가
  거절했다.
- **재현된 결함은 다른 것이다** — 관문 자신의 답(`VALID / OK`)이 후보 목록의
  답(제외)과 **달랐다.** 그래서 안전이 `apply` 앞의 **"후보 목록에 있는가"
  한 검사에만** 걸려 있었고, 그 검사의 거절 코드는 "판정할 수 없다" 와
  "규칙이 금지한다" 를 가르지 않았다 (`RULE_NOT_IMPLEMENTED` 로 같이 나온다).
- 그리고 **강제 쪽은 그대로 재현됐다** — 아래 2.4.

### 2.4 재현된 결함 — 실측

```
         강제 유발이 열렸을 때 허가된 행위의 종류
6-AA     ['ACTIVATE_EFFECT', 'SET_SPELL_TRAP']   ← 🔴 세트로 그냥 넘어갔다
6-AB     ['ACTIVATE_EFFECT']

         탐색 사본
6-AA     원본 후보 5 (유발 있음) · 사본 후보 4 (유발 없음) · 사본 기록 None
         simulate → UNKNOWN "activate_effect 는 지금 허가된 행위가 아닙니다."
6-AB     원본 후보 5 (유발 있음) · 사본 후보 5 (유발 있음) · 사본 기록 1
         simulate → SUPPORTED "체인1 P0 69811710:e[0] 를 해결했습니다."
```

🔴 `PASS` 는 6-AA 에서도 직접 제출이 거절됐다 — 그 자리에서 우선권이 열려
있지 않아 애초에 후보가 아니었기 때문이고, **강제 때문에 막힌 것이
아니었다.** 지금은 `_enforce_mandatory` 가 자리마다 판정하므로, 우선권이
열린 자리에서도 강제가 `PASS` 를 막는다 (`test_c02`).

---

## 3. BLOCKER-6AB-A — 후보 생성과 직접 실행이 같은 판정을 쓴다

### 3.1 무엇을 고쳤나

판정을 **관문 안으로** 옮겼다. `Duel.activation_validator` 가
`_offer_is_activatable` 을 거친 제안만 `event_backed` 에 넣는다.

```
activation_validator(seat)
  └ event_backed = { (source, effect_ref) | _offer_is_activatable(offer) }
        ├ 근거 있는 강제 또는 임의인가 (6-AA)
        └ 아직 그 시점인가          (6-AB · _timing_is_current)
```

이 검증기를 **세 자리가 함께** 쓴다 — `legal_actions` (후보 생성) ·
`_apply_activation` (적용 직전 재검증) · 보고 계층 (`deck/opening.py` 의
`_gate_code`). 그래서 "목록에 없으니 안전하다" 에 기대지 않는다.

### 3.2 "판정할 수 없다" 와 "규칙이 금지한다" 를 가른다

| 상황 | 후보 | `missing` | 뜻 |
|---|---|---|---|
| 강제 · 임의를 모른다 | 아니다 | `TRIGGER_REQUIREMENT_MISSING` | 근거가 생겨야 풀린다 |
| 「때 / 경우」 를 모른다 | 아니다 | `TRIGGER_WORDING_MISSING` | 근거가 생겨야 풀린다 |
| 「때」 타이밍을 놓쳤다 | 아니다 | **비어 있다** | 규칙이 **답했다** — 빠진 것이 없다 |
| 사건 기록이 없다 | 아니다 | `TRIGGER_HISTORY_MISSING` | 기록이 있어야 판정된다 |

🔴 마지막 줄의 `missing` 을 비우는 것이 6-S 의 규율이다 — **없는 것을 빈 값으로
채우지 않는다.** `tests/engine/test_legal_action_candidate_consistency.py::test_i03`
이 자리마다 이 기준을 센다.

### 3.3 거절이 아무것도 바꾸지 않는다

`test_a03` 이 센다 — 모름인 유발 · 사건 없는 효과 번호 · 다른 자리의 제출
셋을 넣고, `state_hash` · 기록 길이 · 체인 길이 · 우선권 · `consumed_events`
· `timing_floor` 여섯이 그대로임을 확인한다.

---

## 4. BLOCKER-6AB-B — 기회의 시작과 끝

### 4.1 근거는 어휘다 — 그리고 6-AA 의 읽기가 틀렸다

6-AA 는 `BLOCKER-6AA-2` 에 이렇게 적었다: *"실제 규칙에서는 그 시점이
지나면 기회가 사라지지만, 그것을 판정하려면 타이밍 윈도우 계층이 필요하다."*

**그 읽기가 틀렸다.** 공식 재정이 어휘로 가른다. 기르수의 텍스트는
「…했을 **경우에** 발동할 수 있다」 이므로, 그 사건 뒤에 다른 일이 일어나도
기회가 **남는 것이 규칙대로**다. 6-AA 가 "한계" 로 고정한 동작은 결함이
아니었다.

🔴 **그때 근거 없는 일괄 규칙("다음 행동이면 만료")을 만들지 않은 것은
옳았다** — 세웠다면 「경우」 효과의 적법한 기회를 닫았을 것이다.

### 4.2 판정 — 새 상태를 만들지 않았다

```
_timing_is_current(offer) -> bool | None
    「경우」           → True            (놓치지 않는다)
    체인이 열려 있다    → True            (SEGOC — 보존한다)
    「때」             → 이 사건 번호 == 기록의 마지막 번호
    모름              → 마지막이면 True, 아니면 None (판정 불가)
```

`EventJournal` 이 그 질문에 그대로 답한다. **새 칸도 새 식별자도 만들지
않았다.**

### 4.3 두 축을 섞지 않는다

| 축 | 무엇이 닫는가 | 왜 따로인가 |
|---|---|---|
| 페이즈 경계 | `Duel.timing_floor` (6-AA) | 지나간 페이즈의 사건은 지금의 기회가 아니다 |
| 페이즈 **안** | `_timing_is_current` (6-AB) | 어휘가 가른다 |

어느 한쪽으로 다른 쪽을 흉내 내면 「경우」 의 적법한 기회를 닫거나 「때」 의
지나간 기회를 연다.

### 4.4 기회를 닫는 것 셋

| 무엇으로 | 어디 |
|---|---|
| 발동했다 | `consumed_events` 에 `(사건, 효과, 개체)` 세 짝 (6-AA) |
| 적법하게 포기했다 | 「때」 면 다음 행동이 기록에 남는 순간 (`_timing_is_current` → False) |
| 기회가 끝났다 | 페이즈 경계 (`timing_floor`) |

🔴 **묻는 것과 거절된 불법 행동은 기회를 쓰지 않는다** — `test_b06` ·
`test_b07` 이 센다. 반복 조회 5회 뒤 판 · 기록 · 소비 · 바닥 · 제안 수 ·
허가 종류가 전부 그대로다.

### 4.5 체인 처리 중의 사건 — 어디까지 보존되는가

| | 보존되는가 | 근거 · 한계 |
|---|---|---|
| 체인이 **열려 있는 동안** | **된다** (`test_b05`) | SEGOC — 체인 안의 기록이 기회를 먹지 않게 한다 |
| 체인이 **닫힌 뒤** | **안 된다** | 🔴 BLOCKER-6AB-1 (§8) |

🔴 **순서를 임의로 적법화하지 않았다.** SEGOC 의 순서 결정도 WHEN/IF 의 완전한
구현도 하지 않았다 (`UNRESOLVED_ORDER_RULES` 가 그대로다). 보존만 했다.

---

## 5. BLOCKER-6AB-C — 강제 유발의 처리 보장

### 5.1 한 자리에서 본다

6-AA 는 `_flow_actions` 안에서 **`END_PHASE` 만** 막았다. 지금은
`legal_actions` 의 마지막이 `_enforce_mandatory` 를 지난다 — 일반 행동 ·
`PASS` · 페이즈 이동 전부 같은 자리에서 본다. 🔴 `END_PHASE` 전용 블록은
**지웠다** (`test_c06` 이 자리가 하나임을 센다).

### 5.2 엔진이 대신 고르지 않는다

```
강제 기회가 열려 있다
  ├ 그 발동이 후보에 있다 → 다른 길을 보류로 밀고 그 발동만 남긴다
  │                        🔴 발동을 대신 집지는 않는다
  │                        🔴 해결 중의 카드 선택은 ResolutionChooser 의 것
  └ 후보에 하나도 없다   → 🔴 닫지 않는다 (영구 대기가 된다)
                           MANDATORY_TRIGGER_UNPLAYABLE 로 적는다
```

마지막 줄이 요청의 *"완료 · 정상 종료와 구별되는 미지원 / 보류 결과"* 다.
`test_c03` 이 처리 뒤 흐름이 돌아오고 `PolicyChooser.records` 가 1 이상임을
센다 — **고른 것은 정책이다.**

### 5.3 시험을 쓰다가 찾은 거짓 보류

처음에는 "강제 + 「때」 + 사건이 마지막이 아님" 으로 §5.2 의 아래쪽을
합성했다. 그런데 **지나간 「때」 는 더 이상 의무가 아니다** — 규칙이 이미
"놓쳤다" 고 답했으므로, 그것을 의무로 세면 "규칙이 요구하는데 발동할 수
없다" 는 **거짓 보류**가 붙는다. `_mandatory_offers` 가 그런 제안을 세지
않도록 고치고, 합성을 **모르는 어휘**로 바꿨다 (모름은 끝났다고 단정하지
않으므로 그 모양이 정직하게 나온다).

### 5.4 자리마다 따로 본다

상대의 강제 기회가 내 행동을 막지 않는다 (`test_c05`) — 막으면 상대가
처리할 수 없는 기회로 내 턴이 멈춘다.

---

## 6. BLOCKER-6AB-D — 탐색 사본

### 6.1 원인이 둘이었다

**①** `_fork` 가 `journal=False` 로 **기록하지 않는 한 벌**을 꽂았다 (6-B).
유발 후보는 기록된 사건에서 나오므로 (6-Z) 사본이 **과거를 잃었다**. 미래를
재는 일에 역사가 필요하지 않다는 그때의 판단이 틀렸다 — **지금 무엇을 발동할
수 있는가가 역사에 달려 있다.**

**②** 사본이 실행기 한 벌을 새로 만들면서 `chooser` 를 넘기지 않았다. 그래서
**사본 안에서만** 해결 시점 선택이 거절됐다:

```
simulate → SUPPORTED, "아직 고르지 않은 대상이 있습니다: @primary"
```

발동은 되는데 해결이 거절된다. 그러면 "해결할 수 있는 효과" 가 원본과 사본에서
달라지고, **미래의 값이 규칙이 아니라 배선을 잰다.**

### 6.2 고친 방법 — 6-B 의 요구를 깨지 않는다

| 무엇 | 어떻게 | 6-B 의 요구는 |
|---|---|---|
| 사건 이력 | 부모의 사건을 씨앗으로 받은 **새 `EventJournal`** | 지켜진다 — 부모의 기록 **객체**를 쓰지 않으므로 사본의 전개가 진짜 기록에 남지 않는다 |
| 형제 격리 | 포크마다 새 객체 · 씨앗은 frozen `JournalEvent` | 한쪽의 전개가 다른 쪽에 보이지 않는다 |
| 소비 · 바닥 | `frozenset` · `int` — `dataclasses.replace` 가 값으로 가져간다 | 사본의 소비가 부모의 목록을 늘리지 않는다 |
| 고르는 사람 | `PolicyChooser.forked()` = 같은 정책 · **빈 기록** | 사본의 선택이 실제 듀얼의 `records` 에 섞이지 않는다 |

🔴 **고르는 사람을 지어내지 않는다** — 부모에게 없으면 사본도 없다. 그
듀얼에서는 아직 정해지지 않은 선택이 실제로 거절되는 것이 맞다.

🔴 **`ResolutionChooser` 계약을 넓히지 않았다.** `forked()` 는 **있으면
쓰는** 것이고, 없는 고르는 사람은 그대로 쓴다 — 모양이 `choose(request)`
하나뿐이므로 기록을 가졌는지 사본 쪽에서 알 방법이 없다.

### 6.3 실제 `Simulator` 경로로 확인했다 — 기록 복사로 끝내지 않았다

```
사본 안의 새 소환이 낳은 유발도 후보가 된다        test_d04
형제 분기가 섞이지 않는다 (소비 1 / 0 / 부모 0)   test_d03
simulate → SUPPORTED "…를 해결했습니다."          test_d05
부모의 판 · 기록 · 소비 · 난수가 그대로다          test_d07
부모가 물은 횟수 0 (사본이 물었는데도)             test_d06
```

### 6.4 상태 비교 · 캐시 · 중복 제거 — **고칠 자리가 없었다**

`state_hash` 가 쓰이는 자리를 전수로 봤다 (`agent/` · `deck/` · `app/` ·
`integration/`).

| 자리 | 무엇에 |
|---|---|
| `agent/search.py` `SearchDecision.state_hash` | 흔적 기록 (재현 좌표) |
| `agent/arena.py` | 표시 |
| `deck/opening.py` | **한 걸음 전후 비교** — "이 걸음이 판을 바꿨는가" |

🔴 **중복 제거 · 캐시 · 방문 집합에 쓰이는 자리는 없다.** 같은 해시가 같은
발동 가능성을 뜻하지 않으므로 (6-AA `test_d05`) 그런 자리가 생기면 기회가
다른 두 상태가 합쳐질 텐데, 지금은 **없다.** `deck/opening.py` 의 비교는
같은 걸음의 전후를 보는 것이고 **다른 상태를 합치지 않는다.**

그래서 **탐색 알고리즘 · 평가에는 손대지 않았다.** `test_d08` 이 그 사실을
잠근다 — 해시가 판단에 쓰이기 시작하는 날 이 시험이 먼저 깨진다.

---

## 7. 실측 — 어휘 census 와 Discord 재현

### 7.1 어휘 census (카드 14,127장)

| | 임의 | 강제 | 허가 모름 | 합 |
|---|---|---|---|---|
| 「경우」 | 2,238 | 247 | 276 | **2,761** |
| 「때」 | 826 | 10 | 42 | **878** |
| 어휘 모름 | 5,482 | 454 | 4,552 | **10,488** |
| 합 | **8,546** | **711** | **4,870** | 14,127 |

🔴 **10,488장의 어휘를 모른다** — 「발동」 문장이 없거나 두 어휘가 섞인
텍스트다. 그 카드의 유발은 사건 뒤에 다른 일이 일어나면 **보류**되고, 무엇을
모르는지 적힌다. 모름을 허가로 바꾸지 않았다.

### 7.2 Discord 재현 — 사용자가 본 것과 **일치**

실험 1 (정상 패 `69811710, 703897, 2930675, 12989604, 93920420`):

```
실행 5걸음 · 상태 변경 5걸음 · 효과가 실제로 해결된 걸음 1걸음
몬스터 존 1 · 마법·함정 존 3 · 패 1 · 묘지 1 · 제외 0 · 남은 덱 34
```

실험 3 (매수 초과 `69811710 x4`):

```
🔴 실행하지 않았습니다 — 입력 검증을 통과하지 못했습니다
위반 1건: 잭나이츠 오르페골 기르수 [69811710]: 패 4장 > 덱 3장
실행 0걸음 · 상태 변경 0걸음
🔴 정적 전개 추천은 내지 않았습니다
```

🔴 **둘 다 6-AA 와 같은 값이다.** 6-AB 의 변경이 이 경로의 결과를 바꾸지
않았다 — 기르수가 「경우」 · 임의이므로 어휘 판정이 그 기회를 닫지 않고,
강제 보장도 걸리지 않는다. **옛 결과를 맞추려고 판정을 조정한 것이 아니라,
판정의 결과가 그대로였다.**

🔴 **이것은 토큰 없이 메시지를 생성한 검사다.** 실제 Discord 접속 검증이
아니다 — §9.4.

---

## 8. 남은 BLOCKER

### BLOCKER-6AB-1 — 체인이 **닫힌 뒤**에는 「때」 가 보존되지 않는다

실측 (합성 「때」):

```
소환 직후        기록 1 · 사건 번호 0 · 지금인가 True
발동 · 체인 열림  지금인가 True            ← 보존된다
체인 해결 뒤      기록 2 · 사건 번호 0 → 지금인가 False   ← 🔴 닫혔다
```

SEGOC 는 *체인 처리 중에 시점을 만난 효과는 그 체인이 완전히 해결된 **뒤**에
발동한다* 고 한다. 지금 규칙은 체인이 **열려 있는 동안만** 보존하고, 닫히면
체인 자신의 해결 기록이 마지막이 되어 그 기회를 닫는다.

고치려면 "이 사건이 **어느 체인 처리 중에** 생겼는가" 를 들고 있어야 한다 —
그것이 `engine/timing.py` 의 `TimingWindow` (체인 스냅숏을 든 창) 이고, 그
계층을 살리는 일은 이 Phase 의 측정된 필요를 넘는다. **실행 등재된 유발이
기르수 하나이고 그것은 「경우」 이므로 이 자리를 실제로 밟는 카드가 지금
없다.** 근거 없이 흉내 내지 않고 적어 둔다.

### BLOCKER-6AB-2 — 「경우」 의 기회를 **페이즈 끝까지** 연다

「경우」 는 놓친 타이밍이 없지만, 실제 규칙에서도 **무한히** 열려 있지는
않다. 지금은 `timing_floor` (페이즈 경계) 가 유일한 상한이므로, 같은 페이즈
안에서라면 몇 걸음 뒤에도 발동할 수 있다. 좁히려면 "플레이어가 우선권을 받는
다음 자리" 라는 개념이 필요하고, 그것도 `TimingWindow` 계층의 일이다.

🔴 **근거 없이 좁히지 않았다** — 좁히면 적법한 기회를 닫는다. 6-AA 가
BLOCKER-6AA-2 에서 같은 판단을 했고, 그 판단은 옳았다 (§4.1).

### BLOCKER-6AB-3 — 강제 유발과 「때」 유발의 **실제 카드 검증이 없다**

(6-AA `BLOCKER-6AA-3` 를 그대로 이어받는다.) 실행 등재된 유발 효과는 기르수
하나이고 **임의 · 「경우」** 다. 그래서 §5 와 §4.2 의 「때」 쪽은 판정값 하나만
바꿔 끼운 **합성**으로만 쟀다. 그 시험들은 이름에 `synthetic` 을 달았고,
실제 카드에서 실행됐다고 적지 않았다.

### BLOCKER-6AB-4 — 어휘 모름 10,488장

§7.1. 근거는 카드 텍스트이고, 「발동」 문장이 없거나 두 어휘가 섞인 텍스트는
판정되지 않는다. 공식 재정 데이터가 저장소에 들어오면 풀린다.

---

## 9. 테스트

### 9.1 왜 묶음으로 쪼갰는가

컨테이너가 한 세션에서 두 번 재시작했던 전례가 있어 (6-AA §8.1) 긴 실행은
결과 파일을 따로 쓰는 네 묶음으로 나눈다. 재시작해도 끝난 묶음은 남는다.

🔴 **선행 보고값(6,537 passed / 10 skipped / 기존 실패 8건)을 이번 변경의
검증 결과로 재사용하지 않았다.** 아래는 전부 이번 작업 트리에서 다시 돌린
값이다.

### 9.2 단계 순서와 결과

🔴 **위험 기반 순서다** — 바뀐 모듈 타깃 → `Duel` 수직 통합 → 관련 엔진 ·
Agent · Discord → 공유 계약 루트 감사.

#### ① 바뀐 모듈 타깃 · ② `Duel` 수직 통합

```
tests/engine/test_trigger_execution_and_timing.py          28 passed  (새 파일)
tests/engine/test_trigger_requirement_and_opportunity.py   21 passed  (6-AA)
tests/engine/test_trigger_normal_path_integration.py       35 passed  (6-Z)
tests/engine/test_trigger_duel_integration.py              26 passed  (6-I)
```

#### ③ 관련 엔진 · Agent · Discord

```
tests/engine (104 파일)                3,718 passed · 3 failed   381s
tests/agent + rules + rulings           525 passed · 3 failed · 1 skipped  212s
tests/engine(유발·흐름·기록) + tests/agent
  + opening · combo · discord           670 passed · 1 failed    272s
```

#### ④ 공유 계약 루트 감사

```
tests/test_*.py 앞 46 파일            §9.2-결과 참조
tests/test_*.py 뒤 46 파일            1,072 passed · 8 failed · 8 skipped  1,086s
```

#### 신규 회귀 — **전부 고쳤다**

| 시험 | 원인 | 고친 곳 |
|---|---|---|
| `test_search_ai::test_the_executor_now_carries_per_duel_state_…` | 사본이 기록을 갖게 됐다 | **시험** — 대리 지표를 직접 측정으로 (`222c6dd`) |
| `test_event_journal_integration::test_c_a_search_fork_records_nothing_…` | 같은 원인 | **시험** — 원래 단정은 그대로, 위에 하나 더 (`222c6dd`) |
| `test_operation_integration::test_k_the_executor_makes_no_choice_of_its_own` | `chooser` 의 이름에 `choose` 가 들어 있다 | **시험** — 낱말 금지를 "읽기 전용 칸" 예외와 함께 (`222c6dd`) |
| `test_legal_action_candidate_consistency::test_i03` | 보류 자리 일곱 → 열 · 강제 쪽 이동 | **시험** — 기준은 그대로, 표만 (`222c6dd` · `1709f46`) |
| `test_trigger_lifetime_audit::test_08` | `journal` 읽는 함수 둘 → 셋 | **시험** — 새 자리를 적고 **금지 목록을 넓혔다** (`820bf22`) |
| `test_rule_not_implemented_code_audit::test_02` · `test_05` | 줄 번호 (+19 · +231) | **시험** — 번호만. 불변량 88·73·15·13·19 실측 확인 (`820bf22`) |
| `test_result_actor_provenance_design_audit::test_09` | 🔴 사본이 `EventJournal` 을 **직접 만들었다** | **코드** — `duel_components(seed_events=…)` 로 되돌렸다 (`1709f46`) |

🔴 **마지막 줄이 이 Phase 에서 감사가 가장 잘 일한 자리다.** "듀얼 하나에
기록 하나" 를 production 전수로 세는 감사가 내가 만든 두 번째 생성 자리를
**설계대로** 잡았다. 시험을 넓히지 않고 코드를 되돌렸다.

실측으로 찾아 고친 엔진 결함 둘이 더 있다 (`1709f46` · §5.3 · 커밋 본문).

#### 기존 실패 — 6-AB 가 손대지 않았다

```
tests/test_korean_overlay_unapplied_audit.py::test_01 · test_13 · test_21 · test_25
tests/test_effect_type_quick_audit.py::test_29
tests/test_event_free_chain_semantic_audit.py::test_27
tests/agent/test_opponent_resource_weighting_audit.py::test_07
tests/rulings/test_data_audit.py::test_every_repository_card_can_reach_a_cid
```

한국어 오버레이 데이터와 재정 캐시에 걸린 별개 문제다. 🔴 **같다고 가정하지
않고** 기준 커밋 `48d6921` 의 워크트리에서 대조했다 — 예: `test_07` 은 그
커밋에서도 같은 자리(`:308`)에서 실패한다 (실측).


### 9.3 삭제 · skip · assertion 완화

**0건.** 고친 시험 다섯 전부 단정이 같거나 **더 좁아졌다** (커밋 `222c6dd`
의 본문에 자리별로 적었다).

---

## 10. 최종 상태

| | |
|---|---|
| 브랜치 | `claude/pensive-goodall-te1egy` |
| 커밋 | `08cfcd2` → `bbbaef5` → `9dc6b2c` → `040d51a` → `222c6dd` → `1709f46` → `820bf22` → 이 보고서 |
| 원격 | `820bf22` 까지 반영됨 |

### 달성 여부 — **부분 완료**

| | |
|---|---|
| BLOCKER-6AB-A 공유 판정 | **완료** — 관문 · 후보 · 재검증 · 보고가 한 판정을 쓴다 |
| BLOCKER-6AB-B 기회의 수명 | **부분** — 어휘 근거로 페이즈 안의 만료를 판정한다. 체인이 닫힌 뒤의 SEGOC 보존과 「경우」 의 상한은 남았다 (BLOCKER-6AB-1 · 2) |
| BLOCKER-6AB-C 강제 보장 | **완료** (구조) · **미검증** (실제 카드) — 실행 등재된 유발이 임의 하나뿐이다 (BLOCKER-6AB-3) |
| BLOCKER-6AB-D 사본 | **완료** — 실제 `Simulator` 경로에서 확인했다 |

🔴 **범위 밖은 건드리지 않았다.** `engine/trigger_order.py` ·
`engine/timing.py` 는 이 Phase 에서 **한 줄도 바뀌지 않았다** (`git diff
48d6921..HEAD` 로 확인). 탐색 알고리즘 · 평가도 그대로다 (§6.4). Lua 파일
이동 · 삭제 없음, 카드 데이터 재생성 없음.

🔴 **다음 Phase 는 자동으로 시작하지 않는다.**

