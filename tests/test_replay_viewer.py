"""
Phase 6-AU — **전개 뷰어** (``deck.replay_viewer``).

이 파일이 재는 것
-----------------
뷰어가 **기록을 읽어 그리는 자리**로 남아 있는가.

========================================  ===============================
기록을 담되 **실행하지 않는다**             ``<script type="application/json">``
바깥에서 받아 오는 자원이 **없다**          서버 없이 파일만으로 열린다
이 경로를 **하드코딩하지 않았다**           카드 ID · 이름이 뷰어에 없다
디스코드가 **네 번째 표현**으로 붙인다       detail · json · **html**
========================================  ===============================

🔴 **이 파일은 화면을 보지 않는다.** 실제로 브라우저에서 열어 한 걸음씩
확인한 결과는 ``docs/duel-simulator-replay-integration.md`` §13 에 있고,
여기 시험이 그것을 대신하지 않는다.
"""

from __future__ import annotations

import json
import re

import pytest

from deck.replay_export import REPLAY_FORMAT, REPLAY_FORMATS_READ
from deck.replay_viewer import render_replay_html

from tests.conftest import requires_official_db

LONGIRSU_LINE = "orcust-skeleton-longirsu"


def _toy(**over) -> dict:
    record = {
        "format": REPLAY_FORMAT,
        "source": {"mode": "line", "line": "toy", "seat": 0, "hand": [1]},
        "result": {"status": "completed", "executed": 1},
        "cards": {"1": {"passcode": 11, "owner": 0, "name": "합성 카드",
                        "kind": "monster", "type_ko": "몬스터/효과"}},
        "initial": {"zones": {"0": {"HAND": [1]}}},
        "steps": [{"order": 1, "actor": 0, "kind": "normal_summon",
                   "accepted": True, "resolved": True, "state_changed": True,
                   "events": [0]}],
        "events": [{"seq": 0, "type": "action", "actor": 0, "changes": [
            {"kind": "monster_summoned", "summon": "normal", "instance": 1,
             "player": 0, "owner": 0, "from": {"zone": "HAND"},
             "to": {"zone": "MZONE", "index": 0,
                    "position": "FACEUP_ATTACK"}}]}],
        "final": {"zones": {"0": {"MZONE": [1]}}},
        "unsupported": [],
    }
    record.update(over)
    return record


def _embedded(html: str) -> dict:
    """담아 둔 기록을 꺼낸다 — 브라우저가 하는 일과 같다."""
    found = re.search(
        r'<script id="replay-data" type="application/json">(.*?)</script>',
        html, re.S,
    )
    assert found, "담아 둔 기록을 찾지 못했습니다"
    return json.loads(found.group(1).replace("<\\/", "</"))


# ======================================================================
# A. 담는 방식 — 데이터이고 코드가 아니다
# ======================================================================
def test_a01_the_record_rides_inside_as_data():
    """기록이 그대로 들어가고, 꺼내면 같은 값이다."""
    record = _toy()
    html = render_replay_html(record)
    assert _embedded(html) == record
    assert html.startswith("<!DOCTYPE html>")


def test_a02_a_card_name_cannot_close_the_script_tag():
    """
    🔴 **기록을 코드로 넣지 않는다.** 카드 이름에 ``</script>`` 가 들어
    있어도 태그가 거기서 끊기지 않는다 — 그것이 유일한 탈출 경로다.
    """
    nasty = '</script><script>window.__owned=1</script>'
    record = _toy()
    record["cards"]["1"]["name"] = nasty
    html = render_replay_html(record)
    #: 담은 자리 안에서는 ``</`` 가 끊겨 있다.
    body = re.search(
        r'<script id="replay-data" type="application/json">(.*?)</script>',
        html, re.S,
    ).group(1)
    assert "</script>" not in body
    assert "<\\/script>" in body
    #: 그래도 값은 그대로 돌아온다.
    assert _embedded(html)["cards"]["1"]["name"] == nasty
    #: 🔴 **담은 자리 밖에는 그 글자가 없다** — 문서 어디에도 새 스크립트가
    #: 생기지 않는다.
    outside = re.sub(
        r'<script id="replay-data" type="application/json">.*?</script>',
        "", html, flags=re.S,
    )
    assert "window.__owned" not in outside


def test_a03_nothing_is_fetched_from_outside():
    """
    🔴 **서버도 네트워크도 필요 없다.** 파일 하나로 열리는 것이 요구였다.
    """
    html = render_replay_html(_toy())
    assert "http://" not in html
    assert "https://" not in html
    assert "<img" not in html
    assert "<link" not in html


def test_a04_an_empty_viewer_still_opens_a_file_picker():
    """기록 없이도 만들어지고, 화면에서 JSON 을 고를 수 있다."""
    html = render_replay_html(None)
    assert 'id="file"' in html
    assert 'type="file"' in html
    body = re.search(
        r'<script id="replay-data" type="application/json">(.*?)</script>',
        html, re.S,
    ).group(1)
    assert body.strip() == ""


def test_a05_the_viewer_reads_both_format_numbers():
    """``/1`` 과 ``/2`` 를 모두 읽는다 — 형식 번호를 올려도 옛 기록이 열린다."""
    html = render_replay_html(_toy())
    for name in REPLAY_FORMATS_READ:
        assert name in html


# ======================================================================
# B. 하드코딩하지 않았다
# ======================================================================
def test_b01_this_line_is_not_written_into_the_viewer():
    """
    🔴 **``orcust-skeleton-longirsu`` 의 이동 순서를 화면 코드에 적지
    않았다.** 뷰어는 어떤 기록이든 읽는다.
    """
    import inspect

    from deck import replay_viewer

    source = inspect.getsource(replay_viewer)
    #: 🔴 카드 패스코드 · 카드 이름 · 경로 이름이 하나도 없다.
    #:
    #: 「갈라테아」는 **이 프로젝트의 이름**이기도 해서 카드 이름 쪽으로
    #: 세지 않는다 — 대신 패스코드로 센다 (그것은 카드만 가리킨다).
    for needle in ("69811710", "21441617", "57835716", "30741503",
                   "76145142", "기르수", "스켈레촌", "오르페골",
                   "orcust", "skeleton", "longirsu"):
        assert needle not in source, needle


def test_b02_an_arbitrary_record_draws_without_this_line():
    """합성 기록 하나로도 화면이 만들어진다 (이 경로와 무관하다)."""
    html = render_replay_html(_toy())
    assert "합성 카드" in _embedded(html)["cards"]["1"]["name"]


# ======================================================================
# C. 디스코드 — 네 번째 표현으로 붙는다
# ======================================================================
@requires_official_db
@pytest.mark.real_card
def test_c01_the_viewer_rides_as_a_third_attachment(repository):
    """detail · json · **html** 셋이 간다."""
    import app.discord_bot as bot
    from deck.combo_policy import COMBO_LINES, ORCUST_VERIFICATION_RECIPE

    class _Agent:
        def __init__(self, repo):
            self.repository = repo

    response = bot.combo_response(
        _Agent(repository),
        ",".join(str(card) for card in COMBO_LINES[LONGIRSU_LINE].hand),
        recipe_text=ORCUST_VERIFICATION_RECIPE,
        line_text=LONGIRSU_LINE,
    )
    names = [item.filename for item in response.attachments]
    assert names == [bot.COMBO_DETAIL_FILENAME, bot.COMBO_REPLAY_FILENAME,
                     bot.COMBO_VIEWER_FILENAME]

    summary = "\n".join(response.messages)
    #: 🔴 **디스코드 안에서 재생되지 않는다고 정확히 적는다.**
    assert "내려받아 브라우저에서 여세요" in summary
    assert "디스코드 안에서는 재생되지 않습니다" in summary
    #: 🔴 호스팅하지 않은 파일을 웹 링크라고 적지 않는다.
    assert "http" not in summary
    #: 볼 수 있는 것이 생겼으므로 "시각 재생 미지원" 은 적지 않는다.
    assert bot.COMBO_REPLAY_VIEW_UNAVAILABLE not in summary

    html = [item.text for item in response.attachments
            if item.filename == bot.COMBO_VIEWER_FILENAME][0]
    record = _embedded(html)
    assert record["format"] == REPLAY_FORMAT
    assert record["result"]["line_completed"] is True


def test_c02_without_a_record_there_is_no_viewer():
    """기록이 없으면 뷰어도 없다 — 빈 화면을 첨부하지 않는다."""
    import app.discord_bot as bot

    item, state = bot.viewer_attachment(None)
    assert item is None
    assert state is bot.ReplayState.NOT_RUN


def test_c03_an_oversized_viewer_is_not_attached(monkeypatch):
    """크기 상한을 넘으면 붙이지 않는다 — 🔴 나누지 않는다."""
    import app.discord_bot as bot

    monkeypatch.setattr(bot, "COMBO_ATTACHMENT_LIMIT", 128)
    item, state = bot.viewer_attachment(_toy())
    assert item is None
    assert state is bot.ReplayState.TOO_LARGE


# ======================================================================
# D. 카드 그림 — 실제 그림을 **안에 담아** 보낸다 (Phase 6-AW)
# ======================================================================
def _images(uris=None, missing=()):
    return {"uris": dict(uris or {}), "missing": [str(m) for m in missing],
            "source": "시험용 출처", "terms": "시험용 조건"}


_TINY_JPEG = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQ=="


def test_d01_an_image_rides_inside_as_a_data_uri():
    """
    🔴 **그림도 바깥에서 받아 오지 않는다.** ``data:`` 로 안에 담기므로,
    화면을 열 때도 재생할 때도 제공처로 요청이 나가지 않는다.
    """
    html = render_replay_html(_toy(), images=_images({"11": _TINY_JPEG}))
    assert _TINY_JPEG in html
    #: 바깥 주소가 하나도 없다 — 서버 없이 파일만으로 열린다.
    assert "http://" not in html
    assert "https://" not in html
    assert 'src="http' not in html


def test_d02_a_missing_image_is_said_out_loud():
    """🔴 **없는 그림을 감추지 않는다** — 누락 패스코드가 화면으로 간다."""
    html = render_replay_html(_toy(), images=_images({}, missing=[11]))
    found = re.search(
        r'<script id="replay-images" type="application/json">(.*?)</script>',
        html, re.S,
    )
    assert found, "그림 묶음을 찾지 못했습니다"
    payload = json.loads(found.group(1).replace("<\\/", "</"))
    assert payload["missing"] == ["11"]
    assert payload["uris"] == {}


def test_d03_without_images_the_viewer_still_builds():
    """그림을 주지 않아도 화면은 만들어진다 (카드는 이름으로 그린다)."""
    html = render_replay_html(_toy())
    body = re.search(
        r'<script id="replay-images" type="application/json">(.*?)</script>',
        html, re.S,
    ).group(1)
    assert body.strip() == ""


def test_d04_only_the_cards_that_are_ever_seen_need_a_picture():
    """
    🔴 **끝까지 뒷면인 카드는 그림을 받지 않는다.** 상대 덱 40장까지 받으면
    제공처에 요청만 늘고 화면에는 나오지 않는다.
    """
    from deck.card_images import record_passcodes

    record = _toy()
    record["cards"]["2"] = {"passcode": 22, "owner": 1}
    record["initial"]["zones"]["1"] = {"DECK": [2]}
    record["final"]["zones"]["1"] = {"DECK": [2]}
    codes = record_passcodes(record)
    assert 11 in codes          # 패 → 필드로 나온 카드
    assert 22 not in codes      # 덱에만 있던 카드


def test_d05_a_passcode_cannot_escape_the_cache_directory(tmp_path):
    """🔴 **정수만 경로가 된다** — 패스코드로 디렉터리를 벗어나지 못한다."""
    from deck.card_images import cache_path

    path = cache_path(69811710, tmp_path)
    assert path.parent == tmp_path / "data" / "cache" / "card_images"
    assert path.name == "69811710.jpg"
    with pytest.raises((ValueError, TypeError)):
        cache_path("../../etc/passwd", tmp_path)


def test_d06_the_discord_viewer_carries_whatever_pictures_are_on_hand(
        monkeypatch, tmp_path):
    """
    디스코드로 가는 HTML 에 **받아 둔 그림이 담긴다**. 🔴 그림을 구하지
    못해도 뷰어는 그대로 나간다 (그림은 덤이다).
    """
    import app.discord_bot as bot
    import deck.card_images as card_images

    seen = {}

    def _fake_prepare(codes, **kw):
        seen["codes"] = tuple(codes)
        seen["limit"] = kw.get("max_downloads")
        return card_images.ImageSet(uris={"11": _TINY_JPEG}, missing=())

    monkeypatch.setattr(card_images, "prepare_images", _fake_prepare)
    item, state = bot.viewer_attachment(_toy())
    assert state is bot.ReplayState.EXPORTED
    assert _TINY_JPEG in item.text
    assert seen["codes"] == (11,)
    #: 🔴 한 응답에서 새로 받을 장수에 상한이 있다.
    assert seen["limit"] == bot.COMBO_IMAGE_FETCH_LIMIT


def test_d07_a_broken_image_layer_does_not_take_the_viewer_down(monkeypatch):
    """그림 준비가 터져도 화면은 나간다 — 카드는 이름으로 그려진다."""
    import app.discord_bot as bot
    import deck.card_images as card_images

    def _boom(codes, **kw):
        raise RuntimeError("그림 서버가 죽었습니다")

    monkeypatch.setattr(card_images, "prepare_images", _boom)
    item, state = bot.viewer_attachment(_toy())
    assert state is bot.ReplayState.EXPORTED
    assert "합성 카드" in item.text


# ======================================================================
# E. 재생 — 장면은 사건 수로 고정이고, 박자는 상태가 아니다
# ======================================================================
def test_e01_the_viewer_has_the_playback_controls_the_screen_promises():
    """재생 · 일시정지 · 처음으로 · 이전 · 다음 · 배속 · 진행 막대."""
    html = render_replay_html(_toy())
    for needle in ('id="play"', 'id="first"', 'id="prev"', 'id="next"',
                   'id="bar"', 'type="range"', 'data-speed="0.5"',
                   'data-speed="3"'):
        assert needle in html, needle


def test_e02_the_beat_is_not_a_judged_state():
    """
    🔴 **한 사건의 연출을 둘로 나눠도 장면은 하나다.** 앞 박자(``showPre``)
    는 이전 판 위에 강조만 얹고, 장면 번호를 늘리지 않는다.
    """
    import inspect

    from deck import replay_viewer

    source = inspect.getsource(replay_viewer)
    assert "function showPre" in source
    #: 앞 박자는 **이전 판**을 그린다 — 새 자리를 만들지 않는다.
    assert "paint(Math.max(0, at - 1), at, false)" in source
