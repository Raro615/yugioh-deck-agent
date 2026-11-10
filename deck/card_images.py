"""
카드 이미지 계층 — 패스코드 하나로 **그 카드의 실제 이미지**를 가져온다
(Phase 6-AW).

무엇이고 무엇이 아닌가
----------------------
🔴 **이름으로 찾지 않는다.** 열쇠는 패스코드 하나뿐이다. 같은 이름의 다른
카드 · 번역 차이 · 유사 검색은 틀린 그림을 띄울 수 있고, 틀린 그림은
"이 카드" 라고 말하는 거짓말이다. 패스코드가 없으면 **그림도 없다** —
화면은 카드 이름으로 대신 그리고 "이미지 없음" 이라고 적는다.

🔴 **그림을 만들어 내지 않는다.** 생성 모델로 카드 그림을 대신 그리거나,
다른 카드의 그림을 가져다 쓰지 않는다.

출처와 이용 조건
----------------
:data:`SOURCE_NAME` · :data:`SOURCE_URL` · :data:`SOURCE_TERMS` 에 적어
둔다. 2026-11 기준 제공처(YGOPRODeck) 의 안내문은 **직접 연결(hotlink) 을
금지하고 내려받아 보관해 쓰라**고 적는다:

    "NOTE ON IMAGES: Do not continually hotlink images directly from this
    site. Please download and re-host the images yourself. Failure to do so
    will result in an IP blacklist."

    "Images are pulled from our image server images.ygoprodeck.com. You must
    download and store these images yourself! Please only pull an image once
    and then store it locally."

    -- https://ygoprodeck.com/api-guide/

그래서 이 계층은 **한 번만 받아** :data:`CACHE_DIRNAME` 에 넣고, 그 다음
부터는 파일에서 읽는다. 뷰어 HTML 은 그 파일을 ``data:`` 로 **안에 담아**
나가므로, 화면을 열 때 제공처로 다시 요청이 가지 않는다 (재생할 때마다
같은 그림을 다시 받지 않는다).

🔴 **카드 그림은 코나미의 저작물이다.** 그래서 받아 둔 그림도, 그림을 담은
HTML 도 저장소에 커밋하지 않는다 — ``.gitignore`` 의 룰북 PDF 와 같은
취급이다. 필요한 사람이 자기 자리에서 받아 쓴다.

열쇠
----
API 키가 필요 없다. 그래서 코드에도 HTML 에도 **비밀값이 하나도 없다**.
"""

from __future__ import annotations

import base64
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "SOURCE_NAME", "SOURCE_URL", "SOURCE_TERMS", "IMAGE_URL_TEMPLATE",
    "CACHE_DIRNAME", "ImageSet", "cache_dir", "cache_path",
    "record_passcodes", "load_images", "prepare_images",
]

#: 출처 — 화면과 보고서에 그대로 적는다.
SOURCE_NAME = "YGOPRODeck 카드 이미지 서버 (images.ygoprodeck.com)"
SOURCE_URL = "https://ygoprodeck.com/api-guide/"
SOURCE_TERMS = (
    "제공처 안내: 직접 연결(hotlink) 하지 말고 내려받아 보관해서 쓸 것 — "
    "“Please only pull an image once and then store it locally.” "
    "그래서 한 번만 받아 로컬에 보관하고, 뷰어 HTML 안에 담아 보낸다. "
    "카드 그림의 권리는 코나미에 있다."
)

#: 🔴 **작은 쪽을 쓴다** (268×391). 화면의 칸과 확대 칸 모두 이 크기로
#: 충분하고, 한 장이 30KB 안쪽이라 디스코드 첨부 상한 안에 들어간다.
IMAGE_URL_TEMPLATE = "https://images.ygoprodeck.com/images/cards_small/{passcode}.jpg"

CACHE_DIRNAME = Path("data") / "cache" / "card_images"

#: 제공처가 적은 상한은 API 초당 20건이다. 그림은 "한 번만" 이 원칙이라
#: 애초에 몇 장 받지 않지만, 받을 때도 넉넉히 띄운다.
_MIN_INTERVAL = 0.15
_TIMEOUT = 20.0
_USER_AGENT = "galatea-replay-viewer/1.0 (+local cache, one fetch per card)"

_REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class ImageSet:
    """
    화면에 넘길 그림 묶음.

    :attr:`uris` 는 ``"패스코드" -> data:`` 다 (문자열 열쇠 — JSON 과 같은
    모양). :attr:`missing` 은 **구하지 못한 패스코드**이고, 화면은 그 카드를
    이름으로 그리고 누락을 알린다.
    """

    uris: dict[str, str] = field(default_factory=dict)
    missing: tuple[int, ...] = ()
    downloaded: int = 0
    from_cache: int = 0
    source: str = SOURCE_NAME
    terms: str = SOURCE_TERMS

    def to_payload(self) -> dict:
        """뷰어가 읽는 모양. 🔴 누락을 **감추지 않는다**."""
        return {
            "uris": dict(self.uris),
            "missing": [str(code) for code in self.missing],
            "source": self.source,
            "terms": self.terms,
        }

    @property
    def bytes_embedded(self) -> int:
        return sum(len(value) for value in self.uris.values())


# ======================================================================
# 자리
# ======================================================================
def cache_dir(root: Path | None = None) -> Path:
    """받아 둔 그림이 사는 자리. ``.gitignore`` 가 이미 덮고 있다."""
    return (Path(root) if root is not None else _REPO_ROOT) / CACHE_DIRNAME


def cache_path(passcode: int, root: Path | None = None) -> Path:
    """🔴 **정수만 경로가 된다** — 패스코드로 디렉터리를 벗어나지 못한다."""
    return cache_dir(root) / f"{int(passcode)}.jpg"


# ======================================================================
# 어떤 카드가 그림이 필요한가
# ======================================================================
#: 덱은 뒷면이다 — 그 안에만 있던 카드는 화면에 얼굴이 나오지 않는다.
_HIDDEN_ZONES = frozenset({"DECK"})


def record_passcodes(record) -> tuple[int, ...]:
    """
    기록 한 건이 **실제로 보여 줄** 패스코드들.

    🔴 **필요한 카드부터**다. 상대 덱 40장처럼 끝까지 뒷면인 카드는 그림을
    받지 않는다 — 받아도 화면에 나오지 않고, 제공처에 요청만 늘린다.
    """
    cards = (record or {}).get("cards") or {}
    seen: set[str] = set()

    def _mark(instance) -> None:
        seen.add(str(instance))

    for block in ("initial", "final"):
        zones = ((record or {}).get(block) or {}).get("zones") or {}
        for _seat, by_zone in zones.items():
            for zone, instances in by_zone.items():
                if zone in _HIDDEN_ZONES:
                    continue
                for instance in instances:
                    _mark(instance)

    #: 사건에 나온 개체는 한 번이라도 움직였다 — 보이는 자리를 지난다.
    for event in (record or {}).get("events") or ():
        for change in event.get("changes") or ():
            if "instance" in change:
                _mark(change["instance"])

    codes: list[int] = []
    for key in seen:
        entry = cards.get(key)
        if not entry:
            continue
        code = entry.get("passcode")
        if isinstance(code, int) and code > 0 and code not in codes:
            codes.append(code)
    return tuple(sorted(codes))


# ======================================================================
# 받기 · 읽기
# ======================================================================
def _download(passcode: int, target: Path) -> bool:
    """한 장. 받으면 ``True``. 🔴 실패는 **조용히 없음**이 된다 (멈추지 않는다)."""
    url = IMAGE_URL_TEMPLATE.format(passcode=int(passcode))
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            if response.status != 200:
                return False
            payload = response.read()
    except (urllib.error.URLError, OSError, ValueError):
        return False
    if not payload.startswith(b"\xff\xd8"):  # JPEG 가 아니면 쓰지 않는다
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part")
    tmp.write_bytes(payload)
    tmp.replace(target)
    return True


def load_images(passcodes, root: Path | None = None) -> ImageSet:
    """
    🔴 **받아 둔 것만 읽는다** — 네트워크를 쓰지 않는다. 디스코드 응답처럼
    기다릴 수 없는 자리가 이 길을 쓴다.
    """
    uris: dict[str, str] = {}
    missing: list[int] = []
    for code in passcodes:
        path = cache_path(code, root)
        try:
            raw = path.read_bytes()
        except OSError:
            missing.append(int(code))
            continue
        if not raw:
            missing.append(int(code))
            continue
        uris[str(int(code))] = (
            "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")
        )
    return ImageSet(uris=uris, missing=tuple(missing),
                    from_cache=len(uris), downloaded=0)


def prepare_images(passcodes, *, root: Path | None = None,
                   allow_download: bool = True, max_downloads: int | None = None,
                   log=None) -> ImageSet:
    """
    없는 것만 받고, 전부 읽어 돌려준다.

    ``allow_download=False`` 면 :func:`load_images` 와 같다. 받지 못한
    패스코드는 :attr:`ImageSet.missing` 에 남고 — **없는 그림을 지어내지
    않는다.**

    ``max_downloads`` 는 **이번 호출에서 새로 받을 장수의 상한**이다.
    🔴 디스코드처럼 사람을 기다리게 하는 자리가 쓴다 — 상한에 걸린 카드는
    이름으로 그려지고, 받아 둔 그림은 다음 호출부터 바로 쓰인다.
    """
    wanted = [int(code) for code in passcodes if int(code) > 0]
    downloaded = 0
    if allow_download:
        for code in wanted:
            if max_downloads is not None and downloaded >= max_downloads:
                if log is not None:
                    log(f"카드 이미지 상한에 걸렸습니다 ({max_downloads}장)")
                break
            path = cache_path(code, root)
            if path.exists() and path.stat().st_size:
                continue
            if _download(code, path):
                downloaded += 1
                if log is not None:
                    log(f"카드 이미지 내려받음: {code}")
            elif log is not None:
                log(f"카드 이미지 없음: {code}")
            time.sleep(_MIN_INTERVAL)
    found = load_images(wanted, root)
    return ImageSet(uris=found.uris, missing=found.missing,
                    downloaded=downloaded, from_cache=len(found.uris) - downloaded)
