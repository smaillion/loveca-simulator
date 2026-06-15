$ErrorActionPreference = "Stop"

$env:PYTHONPATH = "src"
$python = "C:\Users\HanX_\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

& $python -m loveca.cli web serve `
  --database data/loveca.sqlite3 `
  --matches data/matches.sqlite3 `
  --image-cache data/card_images `
  --host 127.0.0.1 `
  --port 8765
