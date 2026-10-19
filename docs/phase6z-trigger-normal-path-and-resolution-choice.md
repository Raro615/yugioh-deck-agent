# Phase 6-Z — 유발 발동의 정상 Duel 경로 통합 및 실제 해결 시점 선택

**기준 커밋**: `e429146` (Phase 6-Y 보고서)
**작업 브랜치**: `claude/pensive-goodall-te1egy`

---

## 0. 한 줄 요약

6-Y 가 남긴 세 가지 — 유발 발동이 `legal_actions` 에 오르지 않는다 ·
배선이 체인을 직접 쌓는다 (`BLOCKER-6Y-1`) · 선택을 체인 쌓기 **전에**
묻는다 — 를 **셋 다** 닫았다. 유발 발동이 사건이 있을 때만 정상 후보가
되고, `Duel.apply` 가 같은 관문으로 재검증하며, 상대 응답 기회를 지나
체인이 풀리는 **그 안에서** 처음으로 선택을 묻는다. 그 결과로 Deck →
Graveyard 가 실제로 일어나고, `/combo` 와 CLI 에도 연결되어 있다.

**실측 (seed 없는 고정 배열 · 오르페골 레시피 · 선공 패 5장):**

```
① 소환 전 유발 후보: 0
② 소환 뒤 유발 후보: 1 | 물은 횟수: 0 | 소비한 사건: 0
③ apply 수락: True | 체인 링크: 1 | 우선권 소유: P1 | 물은 횟수: 0 | 소비한 사건: 1
④ 상대 패스: True | 체인 링크: 1 | 물은 횟수: 0 | 묘지: 0
⑤ 내 패스:   True OK | 체인 링크: 0 | 물은 횟수: 1
   후보 35장 · 허용 1장 · 고른 것 InstanceId(34)
⑥ 덱: 34 · 묘지: 1 · 옮긴 카드: 93920420 GRAVE
⑦ 재발동 후보: 0 | 후속 후보: 4
```

②·③·④ 의 "물은 횟수 0" 이 이 Phase 의 핵심 증거다 — **발동을 정하기
전에도, 응답 창이 열려 있는 동안에도 덱을 보여 주지 않는다.** 묻는 것은
⑤ 한 자리뿐이고 그곳이 해결 중이다.

---

## 1. 구현 전 조사 — 이미 있던 것과 모자랐던 것

| 질문 | 답 (실측) |
|---|---|
| 유발 후보를 만드는 계층이 있는가 | 있다 — `TriggerRegistry` · `TriggerCollector` · `TriggerEligibilityJudge` (관문 다섯) · `TriggerOrderer` · `TriggerChainIntegrator` |
| 사건 기록이 있는가 | 있다 — `EventJournal` + `timing_events(JournalEvent)` |
| 왜 `legal_actions` 에 오르지 않았는가 | 분류다. `ACTIVATION_KINDS_IN_SCOPE == {IGNITION}` 이고, `MONSTER_ACTIVATION_MISSING_BY_KIND[TRIGGER]` 가 *"유발 효과는 사건이 시점을 정한다"* 로 범위 밖을 선언한다 (RULE-EFFECT-004) |
| `EventJournal` 이 규칙상 사건을 대체하는가 | **아니다.** 기록은 "무엇이 일어났는가" 이고, 그것이 유발 타이밍인지는 `timing_events` 와 유발 계층의 다섯 관문이 판정한다. 그래서 이 Phase 는 기록을 **직접 허가로 쓰지 않고** 그 판정을 지난 짝만 받는다 |
| 해결 시점 선택을 받을 통로가 있었는가 | **없었다.** `EffectExecutor._plan` 은 정해지지 않은 선택을 `TOO_FEW_SELECTED` 로 거절하는 자리 하나뿐이었다 |
| 발동 시점에 덱을 가리킬 수 있었는가 | 없다 — `STRUCTURAL-125`. `target_combinations` 가 0건을 돌려주어 발동 자체가 막혀 있었다 |
| 등재된 유발 효과는 몇 개인가 | **하나** (기르수 `69811710:e[0]`). `test_c09` 가 센다 |

---

## 2. 설계 결정 네 가지와 그 근거

### 2.1 사건을 **값으로** 넘긴다 — 분류 집합을 넓히지 않는다

`TRIGGER` 를 `ACTIVATION_KINDS_IN_SCOPE` 에 더하는 것이 가장 짧은 길이지만
**하지 않았다.** 더하면 사건이 없어도 유발이 발동되고, 그것은 룰북이 적지
않은 허가다. `MONSTER_ACTIVATION_MISSING_BY_KIND[TRIGGER]` 의 문장은
**그대로 남아 있고**, 사건이 없을 때 여전히 그 문장이 쓰인다.

대신 `ActionValidator` 가 값 하나를 더 받는다:

```python
ActionValidator(view, *, definitions=None, event_backed=())
```

`event_backed` 는 `(source, effect_ref)` 짝의 모음이고 **기본이 비어
있다** — 주지 않으면 6-Z 이전과 한 글자도 다르지 않다 (ADR-006).

그 방식의 선례가 둘 있다: `ActivationTiming.set_this_turn` (관측에 없는
사실을 흐름 계층이 값으로 넘긴다)과 6-K 의 `definitions` (효과 단위의
사실을 등록소로 넘긴다). 셋 다 같은 이유다 — 검증기는 관측만 읽는다
(ADR-007).

**짝으로 묻는 이유**: 카드만 맞고 효과가 다른 발동, 효과만 맞고 다른
인스턴스인 발동은 둘 다 사건이 열어 준 것이 아니다. 어느 한쪽만 보면 같은
카드 두 장 중 사건을 맞지 않은 쪽이 발동할 수 있게 된다 (`test_b08` ②).

### 2.2 가려진 자리의 고르기만 해결 시점으로 미룬다

```python
CONCEALED_ZONES = frozenset({Zone.DECK, Zone.EXTRA})

def decided_at_resolution(spec) -> bool:
    if spec.is_targeting or spec.is_random or spec.is_bulk:
        return False
    if spec.choice is None:
        return False
    return bool(spec.looked_at_zones() & CONCEALED_ZONES)
```

**대상 지정은 미루지 않는다.** 미루면 기존 발동 경로가 달라지고, 그것은
이번 범위가 아니다. 실측으로 실행 등재된 효과 15개 중 미뤄진 것은
**둘**이고 (기르수 · 어리석은 매장) 둘 다 덱을 본다. 나머지 열셋 —
벌금(패) · 싸이크론 · 강제 탈출 장치 등 — 은 한 글자도 달라지지 않았다
(`test_b12`).

그래서 `STRUCTURAL-125` 가 지키려던 것이 **그대로 지켜진다**: 덱 인스턴스가
`PlayerAction` 에 실리지 않는다. 지키는 방식만 바뀌었다 — 예전에는 조합을
0건으로 만들어 발동을 막았고, 지금은 **대상 없이 발동한다** (조합이 빈 조합
하나다). 측정이 더 강해졌다: 발동은 되고, 새는 것은 없다.

### 2.3 해결 시점 선택은 **요청 하나**다

```python
@runtime_checkable
class ResolutionChooser(Protocol):
    def choose(self, request: "ResolutionChoice") -> "tuple[InstanceId, ...]": ...

@dataclass(frozen=True, slots=True)
class ResolutionChoice:
    effect_ref: EffectRef
    target_ref: TargetRef
    view: GameStateView      # 규칙이 선언한 looked_at 만 열린 관측
    candidates: tuple[InstanceId, ...]
    minimum: int
    maximum: int
```

🔴 **`GameState` 도 `Duel` 도 실리지 않는다** (`test_c01` 이 필드 집합으로
센다). 고르는 쪽이 받는 것은 읽기 전용 관측 하나이고, 그래서 정책이 판을
만질 길이 없다.

책임이 셋으로 갈린다 (`EffectExecutor._ask_for_choice`):

1. **엔진이 센다** — `TargetResolver.candidates` 가 `looked_at` 을 열고
   후보를 만든다. 여기서 후보를 새로 세지 않는다.
2. **고르는 사람이 고른다** — 요청에 실린 관측만 본다.
3. **엔진이 다시 본다** — 후보 목록 밖은 `CANDIDATE_NOT_ELIGIBLE`,
   장수와 중복은 같은 `TargetResolver.validate`, 움직일 수 있는지는 해결
   중의 `BoardRuling` 관문 (6-X).

🔴 **고르는 사람이 없으면 거절한다** — 6-Z 이전과 같은 자리 · 같은 코드 ·
같은 문장(`TOO_FEW_SELECTED`, "아직 고르지 않은 대상이 있습니다"). 열린
것은 "있을 때 묻는다" 하나다. 엔진이 전략적으로 좋은 카드를 대신 고르지
않는다.

### 2.4 `Duel` 은 유발 계층도 효과 계층도 모른다

`Duel` 에 칸 둘이 생겼다.

| 칸 | 뜻 |
|---|---|
| `triggers` | `offers(duel, seat)` 를 가진 **아무 물건**. 없으면 유발 후보가 오르지 않는다 |
| `consumed_events` | 이미 유발 발동에 쓴 `(event_key, effect_ref)` 짝 |

둘 다 **타입을 이름으로 적지 않는다** — `engine.duel` 은 `engine.effect`
도 `integration` 도 `core` 도 import 하지 않는다 (ADR-007). `journal` 과
`chooser` 와 같은 자리다. `test_c04` 가 금지 문자열로, 복원된 6-I 의
`test_h` 가 AST import 로 센다.

`event_key` 는 `TimingEvent` **자체**다. 새 식별자를 만들지 않은 이유:
`TimingEvent` 는 불변이고 값 동치이므로 같은 기록을 다시 펼치면 같은 값이
나온다. 그것이 요구 조건이다 — 후보를 두 번 물으면 같은 열쇠가 나와야 하고,
다른 소환은 다른 열쇠여야 한다. 따로 번호를 붙이면 그 번호를 어딘가에 적어
두어야 하고, 적어 둔 곳이 `Duel` 밖이면 두 기록이 갈라진다.

---

## 3. 바꾼 것 전부 (프로덕션)

| 파일 | +/− | 무엇을 |
|---|---|---|
| `engine/effect/executor.py` | +171/−8 | `ResolutionChooser` 프로토콜 · `ResolutionChoice` · `EffectExecutor(chooser=…)` · `_ask_for_choice` |
| `engine/effect/library.py` | +7 | `build_executor(chooser=…)` 통로 |
| `engine/spell_activation.py` | +14/−4 | `duel_resolver` · `duel_components` 통로 |
| `engine/target_bridge.py` | +51/−1 | `CONCEALED_ZONES` · `decided_at_resolution` · `chosen_bindings` 에서 제외 |
| `engine/activation.py` | +16 | `_check_targets` 가 미뤄진 자리를 **비워 둘 수 있다** |
| `engine/action_validation.py` | +160/−8 | `event_backed` · `_activation_has_event` · `activation_is_event_backed_trigger` · 범위 조건 · `_NormalSpellActivation` 필드 |
| `engine/duel.py` | +223/−8 | `triggers` · `consumed_events` · `activation_validator` · `_trigger_offers` · `_trigger_actions` · `_apply_activation` 의 사건 소비 |
| `integration/autonomy.py` | +292/−76 | `TriggerSource` · `PolicyChooser` · `ChoiceRecord` · `choice_offer_from_request` · `_judged_candidates` · `run_trigger` 재작성 |
| `deck/opening.py` | +24/−6 | `build_opening(chooser=…, triggers=…)` 통로 · `_gate_code` 가 듀얼의 검증기를 쓴다 |
| `app/discord_bot.py` · `app/main.py` | +45/−2 | `/combo` · CLI 연결 + 기준점임을 적는 출력 |

### 3.1 🔴 관문을 세우는 자리를 **하나로** 묶었다

6-Z 가 관측에 없는 둘째 사실(`event_backed`)을 더하면서, 자리마다 손으로
넘기던 모양이 위험해졌다 — 한 자리라도 빠뜨리면 **오류 없이 조용히** 후보
생성과 재검증이 갈라지고, 그것이 STRUCTURAL-134 가 고친 어긋남이다.

**그 위험이 실제로 터졌다.** `deck/opening.py` 의 `_gate_code` 가 제
검증기를 손으로 만들고 있었고 `event_backed` 를 넘기지 않아, 실제로 수락된
유발 발동을 `/combo` 출력이 `판정 RULE_NOT_IMPLEMENTED` 로 적었다 (실측).
행동은 성공했는데 보고가 "규칙 계층이 없다" 고 말한 것이다.

그래서 `Duel.activation_validator(seat, offers=None)` 하나가 만들고, 세
자리가 그것을 부른다 — `legal_actions` (후보 생성) · `_apply_activation`
(재검증) · `deck/opening.py::_gate_code` (보고). `test_n05` 가 그 자리가
하나임과 셋이 그것을 부름을 센다.

### 3.2 두 후보 생성 함수를 **갈라 둔 이유**

`_activation_actions` 는 **판에 있는 카드**에서 후보를 만들고,
`_trigger_actions` 는 **사건**에서 만든다. 출처가 다르므로 함수를 가른다.

그리고 `_activation_actions` 에 한 줄을 더했다 — `activation_kind is
TRIGGER` 면 건너뛴다. 6-Z 전까지 거기서 만든 유발 후보는 관문이 전부
거절했으므로 이 줄이 없어도 결과가 같았다. 사건이 관문을 열게 된 지금은,
없으면 **같은 발동이 목록에 두 번** 오른다.

관문은 여전히 **하나**다 (`_activation_gate`) — `test_b01` 이 세 호출
자리를 센다.

---

## 4. 유발 발동이 정상 경로를 지난다는 증거

```
TriggerSource.offers(duel, seat)        조립 층이 사건에서 후보를 만든다
      ↓                                 (관문 다섯을 지난 ELIGIBLE 만)
Duel._trigger_offers                    consumed_events 를 걸러 낸다
      ↓
Duel.activation_validator               event_backed 를 실은 검증기
      ↓
Duel._trigger_actions → _activation_gate   관문 셋 (검증기 · 타이밍 · can_activate)
      ↓
legal_actions().allowed                 유발 발동이 **후보로** 오른다
      ↓  AI 가 고른다
Duel.apply → legal_actions 재확인 → _activation_gate 재검증
      ↓
EffectActivator.activate → 체인 링크 1
      ↓
ResponseLoop.opened(1 - actor)          🔴 상대에게 응답 기회 (RULE-CHAIN-001)
      ↓  P1 PASS → P0 PASS
ResponseLoop.resolve → ChainResolver → EffectExecutor._plan
      ↓  PolicyChooser.choose           🔴 **여기서 처음 묻는다**
정책이 고른다 → 엔진이 다시 본다 → Deck → Graveyard
```

측정으로 고정한 것 (`test_a01`–`test_a08`):

- 소환 **전**에는 후보도 제안도 0건이다. 사건이 후보를 만든다.
- 후보에 오른 행위의 `targets` 가 비어 있다 — 덱 인스턴스가 실리지 않는다.
- `Duel.apply` 가 그것을 수락하고 체인 링크가 **1**이 된다.
- 발동 직후 우선권이 **상대**에게 열린다. 한 번의 패스로는 풀리지 않는다.
- 둘째 패스에 풀리고 `code is OK` 다.
- 덱이 1장 줄고 묘지가 1장 늘며, 움직인 것이 **정책이 고른 그 인스턴스**다.
- `EventJournal` 에 `send_to_grave` · `DECK` · `GRAVE` · "섞었다" 가 적힌다.
- 해결 뒤 체인이 비고 우선권이 닫히고 후속 후보가 다시 만들어진다 (4건).

---

## 5. 선택이 **해결 중에** 일어난다는 증거

6-Y 의 `run_trigger` 는 체인을 쌓기 **전에** `choose_cards` 를 불렀다. 그
보고서가 스스로 그것은 해결 시점의 선택이 아니라고 적었다.

지금은 `PolicyChooser.choose` 가 불린 때가 곧 해결 시점이다 —
`EffectExecutor._plan` 이 계획 중에 부르므로, 체인이 풀리는 그 안이 아니면
불릴 자리가 없다. 그 사실을 `ChoiceRecord` 가 좌표로 남긴다
(`test_a04` · `test_g02`):

| 시점 | 물은 횟수 |
|---|---|
| 후보를 물어보기만 했다 | 0 |
| 발동을 정하지 않기로 했다 (`DeclineChoice`) | 0 |
| 발동했다 (응답 창 열림) | 0 |
| 상대가 패스했다 (체인 아직 1) | 0 |
| 내가 패스했다 (체인 풀림) | **1** |

그리고 후보가 **해결 시점의 판**에서 세어진다 (`test_b11`). 같은 효과를 한
턴에 두 번 해결하면 둘째의 후보가 하나 적다 (14 → 13) — 첫 해결이 덱에서 한
장을 꺼냈기 때문이다. 발동 시점에 세어 두었다면 둘이 같아야 한다. 판정도
그 판을 본다: 첫째가 보낸 카드가 묘지에 생기면서 6-X 의 간섭 규칙
(`INTERFERENCE_ZONES` 에 `GRAVE` 가 있다) 이 둘째의 허용 후보를 줄인다 —
발동 시점에 굳혀 두었다면 보이지 않을 변화다.

---

## 6. 거절되는 것들 — 전부 엔진이 거절한다

`PolicyChooser` 는 **옮기기만 한다.** 고른 것을 거르지 않는다 — 거르면
엔진이 무엇을 거절하는지가 가려진다. `test_c13` 이 그 `choose` 의 몸통에
판정 부호가 없음을 센다.

| 무엇 | 어디서 | 부호 | 판이 바뀌는가 |
|---|---|---|---|
| 고를 사람이 없다 | `_ask_for_choice` | `TOO_FEW_SELECTED` | 아니오 |
| 후보 목록 **밖** | `_ask_for_choice` ③ | `CANDIDATE_NOT_ELIGIBLE` | 아니오 |
| 장수 미달 | `TargetResolver._check_count` | `TOO_FEW_SELECTED` | 아니오 |
| 장수 초과 | 같은 자리 | `TOO_MANY_SELECTED` | 아니오 |
| 같은 카드 두 번 | 같은 자리 | `DUPLICATE_SELECTION` | 아니오 |
| 움직일 수 있는지 `UNKNOWN` | 해결 중 `BoardRuling` (6-X) | `RULE_NOT_IMPLEMENTED` | 아니오 |
| 사건 없는 발동 | `legal_actions` + `_activation_gate` | 후보가 아니다 | 아니오 |
| 다른 인스턴스로 같은 효과 | 같은 자리 (짝으로 묻는다) | 후보가 아니다 | 아니오 |
| 같은 사건 두 번째 | `consumed_events` | 후보가 아니다 | 아니오 |

🔴 **장수 상한이 중복 검사보다 앞이다.** 기르수의 선택은 1장이 상한이므로
같은 장을 두 번 건네면 엔진이 `TOO_MANY_SELECTED` 로 먼저 막는다. 그래서
중복 규칙 자체가 살아 있는지를 **따로** 센다 — 벌금(최소·최대가 둘 다 2장)
으로 `DUPLICATE_SELECTION` 을 직접 확인한다
(`test_autonomous_resolution::test_d03`).

### 6.1 소비는 **수락한 뒤**에 적는다

- 후보를 다섯 번 물어도 `state_hash` 가 같고, 기록도 늘지 않고,
  `consumed_events` 가 비어 있다 (`test_b02`).
- 발동을 **수락한 직후** 적힌다 — 해결을 기다리지 않는다 (`test_b09`).
  해결이 실패해도 그 사건은 썼다.
- 발동이 **거절되면** 적지 않는다 — 다시 시도할 수 있어야 한다
  (`test_b10`).

---

## 7. 재현과 후속 상태

- 같은 씨앗 → 같은 선택 (`RandomChoice(5)` 두 번이 같은 결과).
- 다른 씨앗 → 선택이 갈린다 (씨앗 5개에서 서로 다른 결과 2개 이상).
- `FirstPermittedChoice` 는 카드를 옮기고 `DeclineChoice` 는 옮기지 않는다
  — 이동이 **정책의 결정**이라는 대조군이다 (`test_b14`).
- 해결 시점 선택의 기록은 `PolicyChooser.records` 에 남는다. 🔴 그 기록은
  **AI 의 관측이 아니다** — `offer.view` 안에는 덱이 보이므로, 기록은 보고와
  재현을 위해 **조립 층이** 들고 있고 어느 정책에도 되돌려주지 않는다.
  정책이 보는 것은 그때 그 요청 하나뿐이다.
- 해결 뒤 `GameState` · `EventJournal` · 체인이 서로 맞는다: 덱 −1 · 묘지 +1
  · 기록에 `send_to_grave` · 체인 0 · 우선권 닫힘 · 후속 후보 4건.

---

## 8. 구조 — 주지 않은 것과 넓히지 않은 것

| 지킨 것 | 어떻게 센다 |
|---|---|
| AI 에 수정 가능한 `GameState`·`Duel` 을 주지 않는다 | `ResolutionChoice` 필드 집합 (`test_c01`), `choose(request)` 서명 (`test_c02`) |
| 평소 관측에 덱이 보이지 않는다 | `test_c03` — 평소 관측은 전부 `None`, 해결 중 관측은 **내 덱만** 열리고 상대 덱은 여전히 `None` |
| `engine.duel` 이 효과·조립·코어를 모른다 | `test_c04` + 복원된 6-I `test_h` (AST import) |
| 둘째 실행 경로가 없다 | `test_c05` — `integration/autonomy.py` 에 `ChainResolver(` · `integrator.plan(` · `extend(` · `resolve_top(` · `resolve_all(` 이 **하나도 없다** |
| 분류 집합을 넓히지 않았다 | `test_c06` — `{IGNITION}` 그대로, `TRIGGER` 의 "없는 이유" 문장도 그대로 |
| 허가를 넓히지 않았다 | `test_c07` — `OPERATION_RULINGS` 19줄 그대로 |
| 주지 않으면 이전과 같다 | `test_c08` — 다섯 기본값 (`event_backed=()` · `chooser=None` ×3 · `triggers=None`) |
| 배선이 없으면 아무것도 달라지지 않는다 | `test_c10` — `triggers=None` 이면 사건이 있어도 후보가 오르지 않는다 |
| `agent` 는 `engine` 만 읽는다 | `test_c11` — import 줄만 본다 (설명문에 층 이름이 나오는 것은 위반이 아니다) |
| 두 사용자 경로가 같은 것을 꽂는다 | `test_c12` — `/combo` 와 CLI 양쪽, 그리고 `deck` 이 조립 층을 읽지 않음 |
| 정책의 답을 엔진이 다시 본다 | `test_c13` |

---

## 9. 테스트 — 위험 기반 4단계

### 9.1 새로 쓴 것

`tests/engine/test_trigger_normal_path_integration.py` — **35개**, 1,190줄.
A 수직 경로 8 · B 시점과 경계 14 · C 구조 13.

### 9.2 고친 기존 시험 11개 — 무엇이 왜 달라졌는가

🔴 **하나도 삭제하지 않았고, skip 을 넣지 않았고, 단언을 느슨하게 하지
않았다.** 전부 "재는 모양이 바뀌었고 측정이 더 강해졌다" 쪽이다.

| 시험 | 예전에 재던 것 | 지금 재는 것 |
|---|---|---|
| `test_autonomous_resolution` A–G (9개) | 6-Y 의 둘째 경로 | `legal_actions` → `apply` → 상대 응답 → 해결 중 선택. `_opening_with_chooser` 가 배선을 꽂는다 |
| ↳ `test_g01` | "유발은 `legal_actions` 에 오르지 않는다" | **사건이 있을 때만** 오른다 + 분류 집합은 그대로다 |
| ↳ `test_g02` | "상대 응답 순환이 돌지 않는다" | **돈다** + 한 번의 패스로는 풀리지 않는다 |
| ↳ `test_g03` | 조합 0건 | 빈 조합 하나 + **후보 목록의 어느 행위에도 덱 인스턴스가 없다** |
| ↳ `test_d01` | 배선이 미리 거절 ("고를 수 없습니다") | **엔진**이 해결 중에 거절 (6-X 관문 문장) + 체인에는 올랐다 |
| ↳ `test_d03` | "두 번" 문장 | 장수로 먼저 막힘 + **중복 규칙 자체를 벌금으로 따로 센다** |
| `test_deck_to_grave_blocker::test_g03` | 조합 0건 | 빈 조합 하나 + `chosen_bindings == ()` + `duel.triggers is None` |
| `test_effect_activation_path::test_06` | 어리석은 매장이 후보가 아니다 | 목록에서 빼고 **`test_06b` 를 새로 더했다** — 후보가 되고 대상이 비어 있다 |
| `test_legal_action_candidate_consistency::test_b01` | `_activation_gate` 호출 2곳 | 3곳 + 왜 함수를 갈랐는지 |
| `test_monster_effect_activation::test_n05` | `ActionValidator(` 2곳이 `definitions` 를 넘긴다 | **만드는 자리가 1곳**이고 둘을 다 넘기며, 세 자리가 그 공장을 부른다 (보고 계층 포함) |
| `test_multi_target_selection::test_e04` | HAND+DECK 조합 252개 | ① 가려진 자리는 열거하지 않는다 ② HAND 만 보는 명세는 여전히 252개 |
| ↳ `test_f05` | `is_targeting` 읽는 자리 1곳 | 2곳 + **다리에서 읽는 자리는 `decided_at_resolution` 하나**이고 대상 지정은 미뤄지지 않는다 |
| ↳ `test_k04` | `chosen_bindings(…)[0]` | 선언은 그대로 · 미뤄짐 True · `chosen_bindings == ()` · 빈 조합 하나 · 평소 관측에 덱 없음 |
| `test_operation_integration::test_k` | 모듈 전체 함수 이름에 `choose` 금지 | **`EffectExecutor` 의 메서드**에 금지 + `choose` 라는 이름은 프로토콜 하나뿐이고 그 몸통이 `...` 이다 |
| `test_summon_trigger_execution::test_f02` | 조합 0건 → 후보 없음 | 빈 조합 하나 + 배선이 없으므로 후보 없음 |
| `test_target_bridge::test_18b` | 조합 0건 | 미뤄짐 True · 빈 조합 하나 · 후보 1건이고 **그 행위에 덱 카드가 없다** |
| `test_trigger_compiler::test_h` | `"trigger" not in duel.py` (낱말) | **AST import** 로 센다 + 트리거 계층 타입 이름 6개를 글자로도 쓰지 않는다 |

### 9.3 실행 결과

| 단계 | 범위 | 결과 |
|---|---|---|
| ① 변경 모듈 표적 | 6-W · 6-X · 6-Y 시험 파일 3개 | **85 passed** |
| ① 새 시험 | `test_trigger_normal_path_integration.py` | **35 passed** |
| ② 복원 확인 | 6-I `test_trigger_duel_integration.py` + 새 파일 | **61 passed** |
| ③ Duel 수직 + 엔진 전체 | `tests/engine` | **3,673 passed** (375s) |
| ④ 공유 계약 루트 감사 + Agent + Discord | `tests/` (engine 제외) | *§9.4* |

**③ 중간에 한 번 10건이 깨졌고, 전부 고쳤다.** 그 10건이 §9.2 의 표이고,
하나도 "원인 불명" 이 아니었다 — 전부 6-Z 가 의도적으로 바꾼 두 가지
(사건으로 관문을 연 것 · 가려진 자리의 고르기를 미룬 것) 의 결과다.

**유발 감사 셋을 추가로 고쳤다** (`tests/` 루트):

| 시험 | 예전에 재던 것 | 지금 재는 것 |
|---|---|---|
| `test_trigger_connectivity_audit::test_03` | `"trigger" not in duel.py` (낱말) | 트리거 계층 타입 이름 **10개**를 모른다 + AST import 로 `engine.trigger*` · `integration` · `engine.effect` · `core` · `analysis` 전부 없음 + 들고 있는 칸이 `object` 다 |
| ↳ `test_12` | 후보를 만드는 자리 넷에 트리거가 없다 | 자리가 **다섯**이 되었고 **새 행위 종류는 만들지 않았다** (`_trigger_actions` 가 만드는 것이 `PlayerAction.activate_effect` 다) |
| `test_trigger_pipeline_dormant_audit::test_12` | 같은 낱말 검사 | 파이프라인·트리거 타입 이름 8개를 모른다 |
| `test_trigger_ownership_audit::test_10` | (본문 그대로 통과) | 🔴 경고문만 고쳤다 — "6-Y 가 둘째 경로를 만들었다" → "6-Z 가 되돌렸다". **본문은 그대로다**: `_entry` 가 지금도 `PlayerAction` 을 받지 않으므로 다시 연결하면 같은 위험이 생긴다 |

### 9.4 전체 결과 — *실행 중, 끝나면 이 절을 채운다*

---

## 10. Discord 연결 상태 — **별도 보고**

🔴 **연결했다.** `app/discord_bot.py` 의 `/combo` 와 `app/main.py` 의 CLI
양쪽이 `build_opening(..., chooser=PolicyChooser(FirstPermittedChoice()),
triggers=TriggerSource(agent.repository))` 를 넘긴다.

**사용자에게 보이는 출력 비교 (같은 레시피 · 같은 패):**

```
6-Z 이전:  executed=4  resolved=4  changes=4
  1 normal_summon   잭나이츠 오르페골 기르수   OK
  2 set_spell_trap  오르페골 클리막스        OK
  3 set_spell_trap  성유물에 이르는 열쇠      OK
  4 set_spell_trap  성유물로부터의 자각       OK

6-Z 배선:  executed=5  resolved=5  changes=5
  1 normal_summon   잭나이츠 오르페골 기르수   OK
  2 activate_effect 잭나이츠 오르페골 기르수   OK   적용된 효과 기록: 69811710:e[0]
  3 set_spell_trap  오르페골 클리막스        OK
  4 set_spell_trap  성유물에 이르는 열쇠      OK
  5 set_spell_trap  성유물로부터의 자각       OK
```

- `execute_opening` 은 **그대로**다 — 응답 창을 닫는 `_settle_chain` 이 이미
  있었으므로 (6-T) 고칠 것이 없었다.
- 출력은 여전히 **실측만** 적는다 (`render_opening_run` 은 수락 · 체인 링크
  · 해결 · 상태 변경 · 효과 기록을 각각 따로 센다).
- 🔴 **기준점임을 출력이 말한다.** 한 줄을 더했다 — *"고른 방식은 검증용
  기준점입니다 — 행동은 `first_meaningful`, 해결 중의 카드 선택은
  `first-permitted`. **최선의 전개가 아닙니다.**"* 이 줄이 없으면 사용자는
  전략적 전개로 읽는다.
- `_gate_code` 가 `duel.activation_validator` 를 쓰도록 고쳤다 (§3.1) —
  그 전에는 실제로 수락된 유발 발동을 `판정 RULE_NOT_IMPLEMENTED` 로
  적었다.

---

## 11. 완료 수준 — **따로** 적는다

### 수준 1 — 계층이 있고 경계가 지켜졌다 ✅

유발 후보 생성 · 사건 판정 · 해결 시점 선택 요청/응답 계약 · 재검증이 전부
기존 계층 위에 있다. 새 엔진도, 중복 AI 실행기도, 규칙 하드코딩도 없다.
구조 시험 13개가 경계를 센다.

### 수준 2 — 정상 경로가 끝까지 돈다 ✅

`legal_actions` → `Duel.apply` → 체인 링크 → 상대 응답 기회 → 양쪽 패스 →
체인 해결 → 해결 중 선택 → 엔진 재검증. 각 단계가 측정으로 고정되어 있고,
중간에 손으로 넣은 허가가 없다.

### 수준 3 — 외부 지정 없이 실제 효과가 해결된다 ✅

시험이 준 것은 **덱 레시피 · 선공 패 · 정책 셋**뿐이다. 정책이 ① 일반 소환
② 유발 발동 여부 ③ 어느 카드를 각각 정하고, 그 결과로 성유물－『성장』
(93920420) 이 Deck → Graveyard 로 **실제로** 움직인다. `DeclineChoice` 로
돌리면 움직이지 않는다 — 그 이동이 정책의 결정이라는 대조군이다.

🔴 **단, 수준 3 의 범위를 넓혀 말하지 않는다.** 아래 BLOCKER 를 읽어야
한다.

---

## 12. BLOCKER 와 측정해 둔 한계

### BLOCKER-6Z-1 — 등재된 유발 효과가 **하나**다

실행 등재된 `TRIGGER` 효과는 기르수 하나다 (`test_c09` 가 센다). 그래서
*"다른 유발 효과로도 같은 경로가 돈다"* 는 **아직 측정할 수 없다.**

공통성은 다른 축으로만 보였다 — 어리석은 매장(`81439173`, **카드 발동**)이
같은 해결 시점 선택 경로를 쓴다 (`test_b13`). 즉 그 경로는 효과 종류와
무관하다. `test_c09` 가 깨지는 날 (유발 효과가 늘어나는 날) 공통성을
**실제로** 측정해야 한다.

### BLOCKER-6Z-2 — 체인 2 의 응답이 후보를 바꾸는 것을 측정하지 못했다

필수 검증 B 가 요구한 *"상대가 체인 2 로 응답해 후보가 달라지는 경우"* 는
**이 저장소의 카드 집합으로 도달할 수 없다**:

- `build_opening` 이 만드는 상대는 **덱 자리만** 있고 패가 비어 있다
  (비공개 정보를 지어내지 않는 설계 — 6-T).
- 기르수의 유발은 스펠 스피드 1 이고, 등재된 효과 중 응수할 수 있는 스펠
  스피드 2 가 **없다** (속공 마법 싸이크론은 등재돼 있으나 상대 패에 넣을
  경로가 `build_opening` 에 없다).

그래서 **지어내지 않았다.** 대신 같은 질문에 답하는 것을 측정했다 — 후보가
**해결 시점의 판**에서 세어진다 (`test_b11`: 14 → 13, 허용 후보도 줄어든다).
판이 언제 바뀌었든 해결 시점의 판을 본다는 사실은 같고, 그 변화를 일으킨
것이 상대의 응답인 경우만 아직 못 돌렸다.

### BLOCKER-6Z-3 — 부정(무효화) 경로를 돌리지 못했다

필수 검증 B 가 *"부정 경로 또는 명시적 한계"* 를 요구했다. 명시적 한계
쪽이다 — 이 엔진에 효과 무효화 구현이 없고, 등재된 효과에도 없다.
BLOCKER-6Z-2 와 같은 이유로 상대가 끼어들 수단 자체가 없다.

### BLOCKER-6Z-4 — 후보 조회 비용을 줄이지 않았다 (실측)

`triggers` 를 꽂으면 `legal_actions` 한 번이 **약 12배** 느려진다 (실측,
같은 판 30회 평균):

```
미배선  legal_actions ×30: 0.028s   (0.9ms/회)
배선    legal_actions ×30: 0.352s  (11.7ms/회)
```

원인은 둘이고 **둘 다 이번 범위에서 고치지 않았다**:

1. `registry_for_view(view, repository)` 를 호출마다 다시 만든다 — 관측에
   보이는 카드의 선언을 매번 컴파일한다.
2. 사건 기록 전체를 매번 다시 펼친다 (`for recorded in duel.journal`).
   그래서 비용이 **기록 길이에 따라 자란다.**

지금 영향 범위는 좁다 — `/combo` 는 걸음 상한이 있으므로 총 0.2초 미만이고,
Agent 의 탐색 경로(`DuelSimulator`)는 `triggers` 를 꽂지 않으므로 한 글자도
느려지지 않는다. 그러나 **긴 듀얼을 돌리는 날 먼저 걸릴 자리**이므로 여기에
적어 둔다. 고치는 방법은 둘 다 캐시이고 (관측 해시로 등록소 캐시 · 읽은
기록 위치 기억), 둘 다 "같은 판이면 같은 답" 이라는 지금의 성질에 기댄다.

### 그대로 남은 것

- `TriggerRequirement.UNKNOWN` — 강제 유발과 임의 유발을 가르는 지식이
  없다. 그래서 후보로 **내놓기만** 하고 발동할지는 고르는 쪽이 정한다.
  `FirstPermittedChoice` 가 "언제나 받아들인다" 는 것은 전략이 아니라 그
  모름을 자기 선택으로 메꾸는 기준점이다.
- `ActivationKind.FLIP` · `QUICK` — 범위 밖 그대로 (룰북 근거 그대로).
- `IGNITION_ACTIVATION_ZONES` 가 EMZ 를 포함하지 않는다 — 6-K 그대로.
- 유발 효과의 **발동 자리**는 `TriggerEligibilityJudge` 의
  `ACTIVATION_ZONE` 관문이 판정한다. `_monster_activation_out_of_scope` 는
  유발에 대해 자리를 다시 보지 않는다 — 두 곳이 각자 보면 갈라진다.

---

## 13. 범위 밖으로 둔 것 (손대지 않았다)

- 새 엔진 · 중복 AI 실행기 · 전략 평가 함수.
- 카드 ID·이름 기반 프로덕션 분기. 🔴 이 Phase 의 프로덕션 코드에 카드 번호
  하나도 없다.
- Lua 파일 이동·삭제, 카드 데이터 재생성, 재정 캐시 커밋.
- 무관한 구조적 TODO (`STRUCTURAL-*`) 수정.
- `ACTIVATION_KINDS_IN_SCOPE` · `OPERATION_RULINGS` 확대.
- 대상 지정(`TARGETING`) 효과의 발동 시점 경로.

---

## 14. 부록 A — 이 Phase 에서 내가 한 실수

🔴 6-Y 보고서의 부록 A 와 같은 자리다. 숨기면 다음 Phase 가 같은 실수를
한다.

### A.1 🔴 기존 시험 파일을 **덮어썼다** (가장 큰 실수)

새 시험을 `tests/engine/test_trigger_duel_integration.py` 로 썼는데, 그
이름의 파일이 **이미 있었다** — Phase 6-I 의 시험 26개, 1,224줄. `git
status` 가 그 파일을 `??` (새 파일) 가 아니라 `M` (수정) 으로 적은 것을
보고서용 수치를 모으다가 알아차렸다.

- 복원: 새 내용을 `/tmp` 로 옮기고 `git checkout --` 로 되돌린 뒤,
  새 파일을 `test_trigger_normal_path_integration.py` 로 다시 두었다.
- 확인: 복원된 6-I 26개 + 새 파일 35개 = **61 passed**.
- 🔴 **원인**: 파일을 만들기 전에 그 이름이 비어 있는지 확인하지 않았다.
  `cat > <path>` 는 묻지 않고 지운다.
- 🔴 **교훈**: 시험 파일을 새로 만들기 전에 `ls`/`git status` 로 그 경로가
  비어 있음을 먼저 확인한다. 그리고 커밋 **전에** `git status` 에서 새
  파일이 `??` 로 보이는지 반드시 본다 — `M` 이면 덮어쓴 것이다.

### A.2 보고가 거짓을 적었다 — 그리고 그것이 설계 결함을 가리켰다

`/combo` 출력이 실제로 수락된 유발 발동을 `판정 RULE_NOT_IMPLEMENTED` 로
적었다. 원인은 `_gate_code` 가 **제 검증기를 손으로 만들면서**
`event_backed` 를 빠뜨린 것이고, 그것은 "자리마다 손으로 넘긴다" 는 모양
자체의 결함이었다. 그래서 문장을 고치지 않고 **만드는 자리를 하나로**
묶었다 (§3.1). 시험도 그 방향으로 강해졌다 (`test_n05`).

### A.3 측정 전에 설계를 믿었다 — 두 번

- `_board(girsu_copies=2)` 로 "같은 턴에 유발을 두 번" 재려 했다. 일반
  소환은 **한 턴에 한 번**이다 (규칙). 어리석은 매장 2장으로 다시 썼다.
- `GameStateView.looked_at` 를 속성으로 읽으려 했다. 그것은 생성 인자이고
  속성이 아니다. 관측이 **무엇을 보여 주는가**로 재도록 고쳤고, 그쪽이 더
  강하다 (내 덱은 열리고 상대 덱은 닫혀 있다).

### A.4 죽은 코드를 남기려 했다

`integration.autonomy._judge_choice` 는 6-Y 가 정책의 선택을 **미리** 거르던
자리다. 6-Z 는 그 거르기를 엔진에 맡기기로 했으므로 (`PolicyChooser` 는
옮기기만 한다) 그 함수를 부르는 곳이 없어졌다. 처음에는 그대로 두었다.

**지우기로 했다** (28줄). 엔진이 하는 일을 배선이 **또** 하는 함수가 남아
있으면 다음 사람이 그것을 다시 꽂고, 그 순간 엔진의 거절이 가려진다 —
`test_d01` 이 그 차이를 재는 자리다. `tests/test_trigger_ownership_audit.py`
의 경고문이 그 함수를 가리키고 있었으므로 그 문장도 함께 고쳤다.

### A.5 선공 첫 패를 늘리려 했다

`extra_hand` 를 더하며 패를 6장으로 만들어 `build_opening` 이 듀얼을 만들지
않았다 (*"선공 첫 패 장수: 6장"*). 검증을 우회하지 않고 **보고 싶은 카드를
앞에 두어** 다섯 안에 들게 했다.

---

## 15. 다음 Phase 후보 (자동으로 시작하지 않는다)

1. **유발 효과를 더 등재한다** — BLOCKER-6Z-1 을 닫는 유일한 길이고,
   공통성을 실제로 측정할 수 있게 된다.
2. **상대의 패와 응답 수단** — BLOCKER-6Z-2 · 3 을 닫는다. 비공개 정보를
   지어내지 않으면서 상대 카드를 지정하는 입력 경로가 필요하다.
3. **강제/임의 유발을 가르는 지식** — `TriggerRequirement.UNKNOWN` 을
   없애려면 공식 스크립트의 `EFFECT_FLAG_` 축을 읽어야 한다.
4. **SEGOC 와 유발 순서** — `UNRESOLVED_ORDER_RULES` 5줄이 그대로다.
   유발이 둘 이상 동시에 열리는 판이 생기면 그 순서가 필요해진다.
