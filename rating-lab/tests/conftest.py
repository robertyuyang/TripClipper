"""评分实验室测试路径配置。"""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LAB_ROOT = REPO_ROOT / "rating-lab"
TRIPCLIPPER_SRC = REPO_ROOT / "src"

for path in (LAB_ROOT, TRIPCLIPPER_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
