#!/usr/bin/env bash
# 一键跑 demo-scan：init → analyze --stage scan → export → 打开 review.html
#
# 用法：
#   bash scripts/demo.sh                 # 默认 demo-scan
#   bash scripts/demo.sh other-slug      # 指定 slug（projects/<slug>/project.yaml）
set -euo pipefail

SLUG="${1:-demo-scan}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${ROOT}/projects/${SLUG}/project.yaml"
REVIEW_HTML="${ROOT}/projects/${SLUG}/exports/review.html"

cd "${ROOT}"

# 非交互 shell 不会加载 ~/.zshrc，需要手动把 Homebrew 加进 PATH，
# 否则 scan 阶段 ffmpeg/ffprobe 测不到，缩略图/关键帧会被清空。
for brew_bin in /opt/homebrew/bin /usr/local/bin; do
  if [[ -x "${brew_bin}/ffmpeg" && ":${PATH}:" != *":${brew_bin}:"* ]]; then
    PATH="${brew_bin}:${PATH}"
  fi
done
export PATH

# 优先使用项目虚拟环境里的 tripclipper。
if [[ -x "${ROOT}/.venv/bin/tripclipper" ]]; then
  TRIPCLIPPER="${ROOT}/.venv/bin/tripclipper"
elif command -v tripclipper >/dev/null 2>&1; then
  TRIPCLIPPER="$(command -v tripclipper)"
else
  echo "找不到 tripclipper 命令；请先 'pip install -e .'" >&2
  exit 1
fi

if [[ ! -f "${CONFIG}" ]]; then
  echo "项目配置不存在：${CONFIG}" >&2
  exit 1
fi

echo "==> [1/3] init  (${SLUG})"
"${TRIPCLIPPER}" init --config "${CONFIG}" --force

echo
echo "==> [2/3] analyze --stage scan  (${SLUG})"
"${TRIPCLIPPER}" analyze --stage scan --config "${CONFIG}"

echo
echo "==> [3/3] export → review.html  (${SLUG})"
"${TRIPCLIPPER}" export "${SLUG}" --html --open

echo
echo "完成。review.html: ${REVIEW_HTML}"
