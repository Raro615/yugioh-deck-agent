# Phase 3-F-19 — `ChainResolution` 직렬화 ↔ replay 입력 경계 감사

> ### 🔴 정정 (Phase 3-F-21, 2026-10)
>
> 이 보고서는 "`legal_actions` 가 `activate_*` 를 허가하지 않는다" 라고 적었다.
> **`activate_effect` 에 대해서는 틀렸다.** Phase 3-F-21 이 실측으로 확인했다 —
> `legal_actions` 는 `activate_effect` 를 **후보로 내놓고**, 고르면 **수락되고
> 체인까지 쌓인다** (주문 16장 덱에서 후보 292회 · 수락 81회 · 거부 0).
>
> 이 보고서의 관측("실제 듀얼에서 `activate_*` 0회")은 **그 덱과 그 정책에서의
> 사실**이었다. 통상 몬스터 위주 덱이라 탐색 정책이 발동을 고르지 않았을 뿐인데,
> 그것을 **엔진의 제한으로 일반화한 것이 잘못**이었다.
>
> 실제로 막혀 있는 것은 `activate_card` · `special_summon` ·
> `change_position` · `change_phase` 넷이다. 자세한 분류는
> `docs/phase3f21-legal-action-engine-boundary-audit.md` §1 · §3 에 있다.



## 0. Base 와 실제 HEAD

| 항목 | 값 | 확인 |
|---|---|---|
| Phase 3-F-18 작업 commit | `aa3772f38733f305f36c74e549ec1881a993d09d` — *Phase 3-F-18: audit ChainResolution link result invariant* | ✅ 존재 |
| Phase 3-F-18 보고서 commit | `a881834aac85af92a2da8968114e61d69d7a9685` — *Phase 3-F-18: document ChainResolution invariant audit* | ✅ 존재 |
| 작업 시작 시 실제 HEAD | `a881834` | ✅ 지시받은 Base 와 **일치** |
| 작업 트리 | 깨끗함 | — |

Base 가 어긋나지 않았다. Phase 3-F-18 최종 판정
**A. CHAIN_RESOLUTION_INVARIANT_ALREADY_SUFFICIENT** 를 전제로 삼았다.

---

## 1. 핵심 질문과 답

> `ChainResolution` 을 **serialization → replay 입력으로 직접 복원해야 하는 실제
> 요구가 존재하는가.**

**없다.** 그리고 "쓰이지 않아서 없다" 가 아니다 — **복원하지 않고도 판이 똑같이
재현된다**는 것을 실제로 돌려서 확인했다(§7).

§2 가 요구한 세 갈래를 각각 판단한다.

| 갈래 | 판정 |
|---|---|
| **A.** `ChainResolution` 이 replay 데이터의 일부인가 | 🔴 **아니다.** 만들어진 자리에서 `code`·`reason` 만 뽑히고 **버려진다**(§4) |
| **B.** runtime object 이고 replay 는 다른 기록을 쓰는가 | 🟢 **그렇다.** 재현 기록은 **`PlayerAction` 순서**다(§5 · §7) |
| **C.** 복원해야 할 호출자가 아예 없는가 | 🟢 **없다.** `ChainResolution.to_dict()` 를 부르는 production 자리가 0곳이고, `from_dict` 는 아예 없다(§3) |

---

## 2. `ChainResolution` lifecycle (AST + 실행 측정)

```
PlayerAction                     ← 🟢 왕복한다 (to_dict / from_dict)
    ↓  Duel.apply
ChainLink                        ← Duel.chain 에 쌓인다 (판이 아니다)
    ↓  ChainResolver.resolve_top
ChainResolution                  ← 🔴 여기서 태어난다
    ↓  link.resolution_context()
EffectResult                     ← 보고 안에만 있다
    ↓  Duel._resolve_chain
DuelStep(action, accepted, code, reason, result=DuelResult|None)
                                 ← 🔴 보고는 여기서 **사라진다**
```

`Duel._resolve_chain` 이 보고에서 실제로 읽는 것을 AST 로 전수 측정했다.

| 받는 쪽 | 읽는 속성 |
|---|---|
| `resolution` | `state`, `steps`, `fully_resolved` — **셋뿐** |
| `steps[-1]` · `last` | **`code`, `reason`** — 열거값과 문자열뿐 |

🔴 `link` · `result` · `deltas` · `to_dict` · `canonical_state` 는 **한 번도 읽지
않는다.** 그리고 보고를 담는 칸이 `DuelStep` 에도 `Duel` 에도 **없다**(dataclass
필드 전수 확인).

`_resolve_chain` 이 바꾸는 것도 측정했다 — `self.chain` 과 `self.priority` **둘뿐**
이고, `self.state` 에 쓰는 자리도 `self.state` 의 메서드를 부르는 자리도 **0곳**이다.

---

## 3. serialization 호출 경로 — `to_dict` 는 **쓰기 전용**이다

문자열 리터럴을 지운 AST 로 측정했다. 설명문에 적힌 낱말을 코드로 세지 않았다.

| 측정 | production 결과 |
|---|---|
| `.to_dict()` **호출** | **116곳** |
| `.from_dict()` **호출** | **1곳** — `engine/action.py:346` 의 `ActionTarget.from_dict(t)` |
| `from_dict` 를 **정의한** 클래스 (저장소 전체) | **2개** — `PlayerAction`, `ActionTarget` |
| `serialize` / `deserialize` / `serialization` / `asdict` | **0회** |
| `replay` / `Replay` / `Replayer` | **0회** |
| `__getstate__` / `__setstate__` / `__reduce__` / `__deepcopy__` | **0개** |
| `ChainResolution.to_dict()` 를 부르는 자리 | **0곳** |
| `ResponseResolution.to_dict()` 를 부르는 자리 | **0곳** (자기 안에서 `step.to_dict()` 로 중첩되기만 한다) |

→ **역방향 입구가 행위 하나로 모여 있다.** `to_dict` 나무 전체는 **진단용 한 방향
출력**이고 읽는 쪽이 없다.

그래서 §6 이 요구한 네 갈래 구분이 이렇게 갈린다.

| §6 의 구분 | 판정 |
|---|---|
| ① dataclass 이므로 기술적으로 serialize 할 수 있다 | 🟢 **참** — `to_dict()` 가 있다 |
| ② serialize 할 수 있도록 API 를 만들어야 한다 | 🔴 **거짓** — 쓸 호출자가 없다 |
| ③ **replay 를 위해 반드시 serialize 해야 한다** | 🔴 **거짓** — §7 이 반증한다 |
| ④ debugging/snapshot 에 편하다 | 🟡 **참이지만 이유가 못 된다** — 그 용도는 이미 `to_dict()` 로 충분하다 |

지시대로 ③을 기준으로 판단했고, "할 수 있다" 를 이유로 `from_dict` 를 만들지
않았다.

---

## 4. replay 호출 경로 — 무엇이 authoritative 한가

| 후보 | 실제 상태 |
|---|---|
| **`PlayerAction`** | 🟢 **왕복한다.** 저장소에서 `from_dict` 를 가진 유일한 입력. `Transcript.entries` 에 그대로 쌓인다 |
| `Transcript` | 🟢 한 판의 기록. `canonical_state()` 가 **받아들여진 행위 순서**로 "같은 판인가" 를 정의한다 |
| `DuelStep` | 🟡 걸음 기록. `action`/`accepted`/`code`/`reason`/`result` — 보고로 가는 길이 없다 |
| `EventJournal` | 🟡 **미래의 재생 기록으로 지정**되어 있다 (ADR-008: "적는 데까지만 한다 … 나중에 되살리는 데 필요한 것을 빠짐없이 적어 둔다"). 그런데 **production 에서 한 번도 켜지지 않는다** (Phase 3-F-16). `from_dict` 도 없다 |
| `ChainResolution` | 🔴 runtime transient. 위 어디에도 들어가지 않는다 |

🔴 **`DuelStep.result` 를 `EffectResult` 와 혼동하지 않는다.** 그것은
`DuelResult | None` — **듀얼의 승패**다. 이름이 비슷해서 "걸음마다 효과 결과가
기록된다" 고 잘못 읽기 쉽다.

---

## 5. 재실행 구조는 **이미 있다**

replay 라는 **기능**은 없지만 **재실행**은 이미 엔진의 일상이다.

```
Simulator._fork()  →  dataclasses.replace(duel, state=duel.state.clone())
                   →  fork.apply(action)
                   →  SimulationResult(action, status, viewer, reason, code, future)
```

`SimulationResult` 의 칸은 여섯이고 보고로 가는 칸이 **없다.** 탐색은 한 수를
**다시 실행**해서 미래를 보지, 결과 객체를 복원하지 않는다.

🔴 그리고 탐색이 그 재실행을 **실제로 어디서 하는지**도 측정했다. 실제 듀얼 한 판
(seed=231)에서 `Duel._resolve_chain` 호출 **67번이 전부 탐색이 복제한
판(fork)** 에서 일어났다 — **실제 판에서는 0번**이다. 현재 `Duel.legal_actions` 가
`activate_card` 를 허가하지 않아(`rule_not_implemented`) 실제 듀얼에서는 체인이
쌓이지 않는다. 이것은 Engine V1 범위의 사실이고 이 Phase 가 고칠 일이 아니다 —
다만 **감사 방법에 영향을 준다**(§11).

---

## 6. state_hash 와의 관계

`GameState.canonical_state` 가 스스로 적어 두었다.

> `chain` / `pending` / `journal` 은 항상 비어 있으므로 포함하지 않고, **앞으로도
> 넣지 않는다** — 역사도 체인도 우선권도 판의 모양이 아니고 … (Phase 2-D-3 ·
> 2-F-1 · 2-F-2)

실측으로도 확인했다: 체인을 바꿔 끼워도 `state.state_hash()` 가 그대로다.

§8 이 요구한 분류:

| 객체 | state_hash 안/밖 |
|---|---|
| `GameState` | 🟢 **안** — 해시 그 자체 |
| `ChainResolution` | 🔴 **밖** |
| `ChainLink` | 🔴 **밖** (체인은 `Duel` 에 있다) |
| `EffectResult` | 🔴 **밖** |
| `CostPaymentResult` | 🔴 **밖** |
| `DuelStep` | 🔴 **밖** (걸음은 기록이고 판이 아니다) |

정규 표현을 직렬화해서 네 이름 중 **하나도** 나오지 않는 것을 확인했다.
`state_hash` 계산 방식은 **건드리지 않았다.**

→ runtime transient 가 해시에 없으므로, **직렬화 필요성과 해시는 분리된다.**

---

## 7. 🟢 결정적 측정 — 행위 기록만으로 판이 재현된다

한 판을 끝까지 돌린 뒤, **받아들여진 `PlayerAction` 만** `to_dict` → JSON →
`from_dict` 로 왕복시켜 같은 seed 의 새 판에 다시 적용했다.
`ChainResolution` 은 **한 개도 복원하지 않았다.**

| seed | 기록 행위 | 재적용 | 거부 | 규칙 걸음 (원본) | `state_hash` |
|---|---|---|---|---|---|
| 11 | 90 | **90** | **0** | 10 (10) | 🟢 **같다** |
| 12 | 151 | **151** | **0** | 18 (18) | 🟢 **같다** |

직렬화 왕복도 값까지 동일했다 (`restored == accepted`).

→ **"`ChainResolution` 을 직렬화해야 replay 가 된다" 는 거짓이다.**

### 🔴 다만 재현에는 **문서화되지 않은 조건**이 있었다

처음 이 측정을 **틀렸다.** 행위만 순서대로 들이부었더니 90걸음 중 **8걸음만**
받아들여지고 해시가 달랐다. 원인은 엔진이 아니라 **내 측정**이었다 — 규칙이 스스로
하는 일(`Duel.advance()`: 드로우 · 페이즈 전환)을 끼워 넣지 않았기 때문이다.
`DuelRunner._step` 은 **행위를 묻기 전에 먼저 `advance()`** 를 한다.

그래서 재현 입력 계약은 네 가지다.

1. `seed`
2. 양쪽 덱
3. `accepted` 인 `PlayerAction` **순서**
4. 🔴 **`Duel.advance()` 를 행위 사이에 끼워 넣기**

`Transcript.rule_steps` 는 그 규칙 걸음의 **횟수만** 센다 — 무엇이었는지는 적지
않는다. 그래서 네 번째 조건을 모르면 재현에 실패한다. 그런데 그 조건이 **어디에도
적혀 있지 않았다.** `test_25` 가 "빼면 정말 깨진다" 를 못 박는다.

---

## 8. clone / deepcopy / snapshot / restore

| 측정 | 결과 |
|---|---|
| `clone()` 을 정의한 클래스 | 판 계층뿐 — `GameState`, `PlayerState`, `CardInstance`, `TurnState`, zones, use_registry, rule_usage, randomness, `InstanceId`. 🔴 `ChainResolution`·`ChainLink`·`Chain`·`EffectResult`·`DuelStep` 에는 **없다** |
| production `deepcopy` 호출 | **1곳** — `analysis/condition_parser.py:141` (조건 트리 복제). 보고와 무관 |
| `__deepcopy__`/`__getstate__`/`__setstate__`/`__reduce__` | production 에 **0개** → pickle 특수 처리 없음 |
| `ChainResolution` 에 `replace` 를 쓰는 production 호출 | **0곳** (Phase 3-F-18 측정을 **다시** 확인) |
| `snapshot` | `sources/source_manager.py`(데이터 수집) · `CardInstance`/`zones`(이전 상태). `engine/chain.py` 에는 없다 |
| `restore` | `engine/spell_activation.py` 의 `NormalSpellPlacement.restore` **하나** — **놓은 마법을 되돌리는** 것이고 판 복원도 기록 복원도 아니다 |

지시대로 "`dataclasses.replace` 가 이론적으로 가능하다" 만으로 방어 코드를 **추가하지
않았다.** 실제 호출자가 0곳이다.

---

## 9. link / result provenance 영향

Phase 3-F-17 · 3-F-18 이 고정한 계약은 그대로다.

```
EffectResult        ← ChainResolution.link.actor
CostPaymentResult   ← ActivationResult.action.actor
```

이 Phase 가 확인한 것은 **그 provenance 가 replay 에서 필요하지 않다**는 것이다.
재현은 결과 객체를 되살리는 것이 아니라 **행위를 다시 실행하는 것**이므로, 사람은
`PlayerAction.actor` 로 들어오고 그 뒤 provenance 는 엔진이 다시 만든다.

측정으로 확인한 두 가지:

* 보고를 직렬화하면 `link.actor` 가 남는다 — 그런데 **되읽을 입구가 없다.**
* 보고에서 `link` 를 떼면 provenance 가 사라지는데, 그 상태로 사건을 읽으면
  Phase 3-F-14 의 `read()` 입력 계약이 **`TypeError` 로 거부**한다 (3-F-18 측정).

금지 항목 준수: `EffectResult.actor` ✗ · `CostPaymentResult.actor` ✗ ·
`ActorProvenance` ✗ · 새 enum ✗ · 새 `to_dict`/`from_dict` ✗ · 새 serializer ✗ ·
새 replay framework ✗.

---

## 10. hidden information · AI / Search 영향

| 항목 | 결과 |
|---|---|
| `agent/` 코드에 `ChainResolution`·`EffectResult`·`CostPaymentResult`·`EventJournal` | **한 번도 나오지 않는다** (문자열 제거 AST) |
| 직렬화가 AI 쪽으로 정보를 새게 하는 경로 | **없다** — 가능성이 아니라 **연결 자체가 없다** |
| `GameStateView` | 불변. 상대 손·덱이 `concealed=True`, `cards=()` |
| RNG | seed 로 완전히 결정. 같은 seed → 같은 `state_hash` |
| Search clone | `GameState.clone()` 만 쓴다. 보고를 복제하지 않는다 |
| AI decision trace | `Transcript` — 행위만 담는다 |
| 검색 ranking digest | 6판 **611결정** 불변 |

보고의 `to_dict()` 에는 카드 신원이 들어간다. 그러나 **부르는 production 자리가
없으므로** 숨은 정보 경계는 그대로다. 가능성을 결함으로 과장하지 않고, **연결이
없다는 사실**을 적는다. AI/Search 코드는 **한 줄도** 고치지 않았다.

---

## 11. 🔴 고의 위반 주입 8건 — 그리고 세 개를 **놓쳤다**

`engine/chain.py` · `agent/runner.py` · `engine/duel.py` · `agent/simulation.py` ·
`engine/state/game_state.py` 를 md5 로 백업하고 하나씩 심었다 되돌렸다. 마지막
복원을 md5 로 확인했다.

| # | 심은 위반 | 걸린 테스트 | 결과 |
|---|---|---|---|
| 1 | `ChainResolution` 에 `from_dict` 를 만든다 | `test_04` `test_05` `test_21` `test_27` | ✅ |
| 2 | `DuelStep` 이 보고를 들고 다니게 한다 | `test_01` `test_11` | ✅ |
| 3 | `_resolve_chain` 이 걸음에서 `result` 까지 읽는다 | `test_01` | ✅ |
| 4 | 해결한 보고를 판의 journal 에 쌓는다 | `test_23b` | ⚠️ **두 번 놓쳤다 → 구조 단정으로 잡았다** |
| 5 | `ChainResolution` 에 `clone` 을 만든다 | `test_15` | ✅ |
| 6 | AI 계층이 보고를 알게 한다 | `test_19` | ✅ |
| 7 | `ChainResolution` 에 `__deepcopy__` 를 만든다 | `test_08` | ✅ (anchor 교정 후) |
| 8 | `Transcript` 의 `advance` 조건 설명을 지운다 | `test_28` | ⚠️ **놓쳤다 → 단정을 강화해 잡았다** |

### 주입 4 — 왜 두 번이나 놓쳤나

1차: `test_02`·`test_03` 이 `ChainResolver.resolve_top` 을 **직접** 부른다.
`Duel._resolve_chain` 을 지나가지 않으니 거기 심은 위반이 보이지 않는다.
**구성 요소만 재면 조립된 경로가 사각지대로 남는다.**

2차: 실제 듀얼을 돌려 `state.journal == []` 을 재는 테스트를 추가했는데 **여전히
놓쳤다.** 원인을 재 보니 §5 의 사실 — `_resolve_chain` 호출 67번이 **전부
fork** 에서 일어나고 실제 판에서는 **0번**이다. **닿지 않는 경로는 돌려도 안
보인다.**

고친 방향: **구조로 잡는다.** `_resolve_chain` 이 바꾸는 것이 `self.chain`,
`self.priority` **둘뿐**이고 `self.state` 에 쓰거나 그 메서드를 부르는 자리가
**0곳**이라는 것을 AST 로 단정했다. 행동 단정(실제 듀얼 journal 비어 있음)과
구조 단정을 **둘 다** 둔다.

### 주입 8 — 왜 놓쳤나

`test_28` 이 `"advance" in transcript_doc` 으로 **낱말만** 세고 있었다. 네 번째
항목을 지워도 그 낱말이 다른 줄에 남아 있어서 통과했다. **낱말이 아니라 계약을
센다** — 네 항목이 번호와 함께 다 있는지, 네 번째가 `advance()` 끼워 넣기인지,
"빼면 재현되지 않는다" 경고가 함께 있는지를 단정하도록 고쳤다.

---

## 12. 테스트 결과

새 파일: `tests/test_chain_resolution_replay_boundary_audit.py` — **31개**
(요구 최소 20개)

| # | 테스트 | §13 요구 항목 |
|---|---|---|
| 01 | 보고는 만들어진 자리에서 소비되고 버려진다 | 1, 7 |
| 02 | link-only lifecycle 이 아무것도 남기지 않는다 | 2 |
| 03 | result 는 보고와 같은 수명이다 | 3 |
| 04 | actor provenance 는 살아 있는 보고로만 읽는다 | 4 |
| 05 | 🔴 `from_dict` 정의는 저장소 전체에서 **둘뿐** | 5 |
| 06 | production `from_dict` 호출은 한 곳(중첩) | 5, 6 |
| 07 | production 코드에 `replay` 가 **0회** | 6 |
| 08 | serializer/deserializer/pickle 훅 **0개** | 5 |
| 09 | 🔴 `to_dict` 는 **쓰기 전용**이다 | 5, 6 |
| 10 | 재생 기록으로 **지정된** 것은 `EventJournal` (ADR-008) | 6 |
| 11 | `DuelStep` 은 **행위**를 담는다 | 7 |
| 12 | `DuelStep.result` 는 승패이고 `EffectResult` 가 아니다 | 7 |
| 13 | `state_hash` 는 체인도 journal 도 보지 않는다 | 8 |
| 14 | 여섯 객체를 해시 안/밖으로 분류 | 8 |
| 15 | 보고와 그 부품에 `clone` 이 없다 | 9 |
| 16 | production `deepcopy` 는 한 곳이고 무관하다 | 11 |
| 17 | production `replace` 호출 0곳 (재확인) | 10 |
| 18 | `snapshot`·`restore` 는 **다른 것**이다 | 12, 13 |
| 19 | 보고가 AI 계층에 **닿지 않는다** | 17 |
| 20 | 탐색 fork 는 보고 없이 재실행한다 | 16 |
| 21 | 직렬화가 숨은 정보를 넓히지 않는다 | 14 |
| 22 | 같은 seed → 같은 판 | 15 |
| 23 | 실제 듀얼 기록에는 **행위만** 남는다 | 18 |
| **23b** | 🔴 **보고를 판에 쌓는 코드가 없다** (구조 + 행동) | §11 |
| **24** | 🟢 **직렬화한 행위 기록만으로 `state_hash` 재현** | 19 |
| 25 | 🔴 `advance()` 를 빼면 재현되지 않는다 | 19 |
| 26 | 비용 결과 쪽 계약 불변 | — |
| 27 | 이 Phase 는 docstring 둘만 바꿨다 (AST 증명) | 20 |
| 28 | 그 docstring 둘이 측정한 사실을 적는다 | 20 |
| 29 | `state_hash`·RNG·관측 불변 | 20 |
| 30 | 검색 ranking digest 불변 (611결정) | 20 |

존재하지 않는 replay API 를 위한 **가짜 abstraction 을 만들지 않았다.** `test_10` ·
`test_07` 은 "없다" 를 **없는 그대로** 측정한다.

기존 테스트를 **삭제하지 않았고, skip 을 넣지 않았고, assertion 을 약화하지
않았다.** 기존 테스트를 고친 것도 **없다.**

### 전체 회귀

```
4519 passed, 4 skipped in 510.62s (0:08:30)
```

| | 개수 |
|---|---|
| Phase 3-F-18 (base `a881834`) | 4488 |
| 이 Phase 가 추가한 테스트 | **+31** |
| **합계 (실측)** | **4519** |
| 실패 | **0** |
| skip | 4 (이 Phase 가 추가한 것 **없음**) |

삭제 0 · skip 추가 0 · assertion 약화 0 · 기존 테스트 수정 0.

---

## 13. production 변경 — **docstring 둘**

§14 가 "그 외에는 문서 · 테스트만 수정한다" 라고 했고, §14 의 ①②③ (잘못된 복원
경로 · 누락된 계약으로 인한 runtime bug · provenance/state 손실) 은 **하나도
성립하지 않는다.** 그래서 실행되는 코드는 **한 글자도** 바꾸지 않았다.
`test_27` 이 두 파일의 **문자열을 지운 AST** 가 이 Phase 의 작업 commit
(`9989c00`) 앞뒤로 동일함을 증명한다. 그 commit 이 건드린 것은
`engine/chain.py`(+22) · `agent/runner.py`(+20) · 새 테스트 파일뿐이다.

### ① `engine/chain.py` — 측정과 어긋나는 문장을 고쳤다

**이전 (Phase 3-F-17 에서 내가 쓴 것):**

> … 그래서 result 만 들고 다니면 행위자를 되찾을 수 없다 — **기록(replay)에
> 남겨야 하는 것은 이 객체다.**

🔴 이 문장은 **측정과 어긋난다.** 재현 기록은 행위이고(§7), 사건 단위 기록 자리는
`EventJournal` 로 지정되어 있다(ADR-008). `ChainResolution` 은 **둘 다 아니다.**
게다가 `from_dict` 가 없어 되살릴 수도 없다. 문맥상으로는 "`EffectResult` 혼자
떼지 말라" 는 비교였지만, replay 경계를 찾는 사람이 읽으면 **반대로 안내한다.**

**이후:** 그 문장을 "둘을 떼지 말고 이 객체째로 넘긴다" 로 바꾸고, 새 절
*"이 객체는 기록이 아니다 (Phase 3-F-19)"* 를 더해 (가) runtime transient 이고
`code`/`reason` 만 뽑힌 뒤 버려진다 (나) `from_dict` 를 가진 것은 `PlayerAction` ·
`ActionTarget` 둘뿐이다 (다) 재현 기록은 `Transcript`, 사건 기록 자리는
`EventJournal` (ADR-008) (라) 직렬화 보관·복원 길을 **만들지 않는다** — 만들면
생성 입구가 `resolve_top` 하나라는 전제가 깨지고 그 전제가 바로 Phase 3-F-18 의
`result ⟹ link` 보장 근거다 — 를 적었다.

### ② `agent/runner.py` — 재현 입력 계약을 적었다

`Transcript` docstring 에 §7 의 네 가지를 적었다. 특히 **네 번째**
(`Duel.advance()` 끼워 넣기)와 "빼면 재현되지 않는다"를 명시했고,
`ChainResolution`·`EffectResult` 는 **필요하지 않다**는 것도 적었다.

---

## 14. 최종 판정

> ## **B. CHAIN_RESOLUTION_SERIALIZATION_BOUNDARY_DOCUMENT_ONLY**

직접 직렬화는 **필요하지 않지만**, replay/serialization 경계를 **문서로 명확히
해야 한다.**

### 왜 A 가 아닌가

A(`REPLAY_DOES_NOT_REQUIRE_CHAIN_RESOLUTION`)의 내용은 **참이고 §7 이 증명했다.**
B 의 첫 구절이 바로 그것이다. 그런데 A 만 고르면 "그러므로 할 일이 없다" 가 되는데
**그것이 사실이 아니었다.**

* `engine/chain.py` 가 **측정과 반대로** 안내하고 있었다 (3-F-17 에서 내가 쓴 문장).
* 재현 입력 계약의 네 번째 조건(`advance()` 끼워 넣기)이 **어디에도 없었다.** 이
  감사가 **먼저 그 함정에 빠졌다** — 문서가 없어서 실제로 사람이 틀린 사례다.

### 왜 C · D · E 가 아닌가

| 선택지 | 고르지 않은 이유 |
|---|---|
| C. `…REPLAY_INPUT_REQUIRED` | 보고를 입력으로 요구하는 replay 가 **없다.** 요구하는 호출자가 0곳이다 |
| D. `…REPLAY_PROVENANCE_GAP` | replay 에서 provenance 가 **손실되지 않는다.** 사람은 `PlayerAction.actor` 로 들어오고, 보고를 복원하지 않으므로 잃을 것이 없다 |
| E. `REPLAY_ARCHITECTURE_NOT_PRESENT` | 가장 가까웠지만 **틀리다.** replay **기능**은 없어도 **재실행 구조**는 이미 있다 (`Simulator._fork` → `clone` → `apply`, seed 결정론). 그래서 "판단할 단계가 아니다" 가 아니라 **판단했고 답이 나왔다**(§7). 지시 §10 이 요구한 구분 — "현재 구현 범위에서 필요 없음" vs "미래 replay 시스템에서는 별도 설계 필요" — 을 B 가 정확히 담는다 |

### 🟡 고치지 않고 기록만 하는 것

| 항목 | 내용 |
|---|---|
| `EventJournal` 이 켜지지 않는다 | 재생 기록으로 **지정**되어 있으나 production 에서 journal 은 항상 `None`/빈 리스트다 (3-F-16). 켜는 것은 이 Phase 의 일이 아니다 |
| `rule_steps` 가 횟수만 센다 | 규칙 걸음이 **무엇이었는지**는 기록되지 않는다. 지금은 `advance()` 를 다시 돌려서 메우지만, 규칙이 비결정적으로 바뀌면 그 방법이 깨진다 |
| 실제 듀얼이 체인을 해결하지 않는다 | `Duel.legal_actions` 가 `activate_card` 를 허가하지 않는다(`rule_not_implemented`). 그래서 체인 해결은 **탐색 fork 에서만** 일어난다 — Engine V1 범위의 사실 |
| `ChainResolution.to_dict()` 에 읽는 쪽이 없다 | 진단용으로는 쓸모가 있으므로 **지우지 않는다.** 다만 `from_dict` 를 만들지 않는다 |

---

## 15. 다음 Phase 후보 (최대 1개)

**`Duel.advance()` 규칙 걸음의 기록 계약 감사.**

이유: 이 Phase 가 재현 입력 계약의 네 번째 조건을 문서로 고정했지만, 그 조건은
"규칙 걸음을 **다시 돌려서** 메운다" 는 방식에 의존한다. `Transcript.rule_steps` 는
**횟수만** 세고 무엇이 일어났는지 적지 않는다. 지금은 규칙이 결정론적이어서
문제가 없지만, 그 결정론이 어디까지 보장되는지는 **측정된 적이 없다.** 재현이
`advance()` 재실행에 의존해도 되는지 — 아니면 규칙 걸음도 기록되어야 하는지 —
를 replay 를 구현하기 **전에** 재는 것이 순서상 맞다.

다만 **다음 Phase 는 임의로 진행하지 않는다.**
