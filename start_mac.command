#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if [ -d /opt/homebrew/share/tessdata ]; then
  export TESSDATA_PREFIX="/opt/homebrew/share/tessdata"
elif [ -d /usr/local/share/tessdata ]; then
  export TESSDATA_PREFIX="/usr/local/share/tessdata"
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Создан .env. Заполните AI_BASE_URL, AI_API_KEY и AI_MODEL."
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 не найден. Установите его командой: brew install python"
  exit 1
fi

if command -v tesseract >/dev/null 2>&1; then
  echo "OCR: $(command -v tesseract)"
else
  echo "Предупреждение: Tesseract не найден. Демо ЛУКОЙЛ работает по проверенному профилю; для других сканов установите:"
  echo "  brew install tesseract tesseract-lang"
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install --disable-pip-version-check -r backend/requirements.txt

PORT_VALUE="$(grep -E '^PORT=' .env | tail -1 | cut -d= -f2 | tr -d '[:space:]' || true)"
PORT_VALUE="${PORT_VALUE:-8000}"
echo ""
echo "FinSight AI v2.1 запускается: http://127.0.0.1:${PORT_VALUE}"
echo "Оставьте это окно терминала открытым. Остановка: Ctrl+C"
echo ""
cd backend
exec python run.py
