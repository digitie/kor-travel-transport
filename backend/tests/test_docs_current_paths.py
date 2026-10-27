"""운영 문서가 저장소에 없는 파일을 링크하지 않는다.

#92·T-TRN-03b로 지운 `scripts/deploy-odroid.ps1`·`deploy/odroid/remote-deploy.sh` 등을 배포 런북이 "현재 fail-closed
차단 파일"로 링크해 운영자가 없는 절차를 찾게 했다. 문구가 아니라 링크 대상의 존재(효과)로 본다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_DOCS = ("docs/runbooks/deployment.md", "docs/current-state.md")
_LINK = re.compile(r"\]\(([^)\s]+)\)")


@pytest.mark.parametrize("name", _DOCS)
def test_operational_doc_links_point_to_tracked_files(name: str) -> None:
    path = _REPO / name
    if not path.is_file():
        pytest.skip("Docker 회귀 이미지에는 docs/가 없다 — 저장소 checkout(CI)에서 검사한다")
    targets = [target.split("#", 1)[0] for target in _LINK.findall(path.read_text(encoding="utf-8"))
               if not target.startswith(("http://", "https://", "mailto:", "#"))]
    assert targets, "상대 링크를 하나도 찾지 못했다 — 파서가 낡았다"
    missing = [target for target in targets if target and not (path.parent / target).exists()]
    assert not missing, missing
