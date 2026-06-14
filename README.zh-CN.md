# Love Live! Series Official Card Game Analysis & Simulation Platform

[日本語](./README.md) | [简体中文](./README.zh-CN.md)

这是一个面向 Love Live! Series Official Card Game（ラブカ）的本地卡牌数据库、牌组分析与规则验证工具。

项目始终以官方日文资料为唯一权威来源。内部英文标识只用于工程实现，不替代官方日文术语。

## 当前状态

`v0.4.0-alpha.2` 当前已收录:

- 正式官方 `card_list` 卡牌 importer
- SQLite Schema v2 本地卡牌数据库
- 带本地保存能力的 Deck Builder
- 基于 `decklist.v0` 的 Deck Analyzer
- FastAPI + React SPA 可视化规则验证器
- 可回放的 Action-only GameState

当前规则验证器已覆盖:

- 先后攻、起手、调度、初始 Energy
- Member 登场、满位替换、`バトンタッチ`
- Live Set、等量补抽、Live 公开、应援
- Heart 分配、部分特殊 Blade Heart 自动处理
- 成功 Live 移动、下一回合先攻判定、3 张成功 Live 胜负
- 尚未自动化的技能通过 `ManualAdjustmentAction` 处理

当前还没有:

- 全卡技能自动执行
- AI、Monte Carlo、胜率引擎
- 在线对战、账户和同步

## 界面预览

启动页：可直接选择已保存牌组并创建对局。

![启动页](docs/images/home-desktop.png)

Deck Builder：右侧筛选选卡，中央查看构筑与分析结果。

![Deck Builder](docs/images/deck-builder-desktop.png)

规则验证器：同屏查看盘面、Action/Event Log 与人工规则调整。

![规则验证器](docs/images/match-actions-desktop.png)

## 环境要求

- Python `3.11+`
- Node.js `20` / `22` / `24+`
- SQLite 无需额外安装

安装依赖:

```powershell
python -m pip install -e ".[dev]"
cd web
npm install
cd ..
```

## 本地启动

1. 初始化卡牌数据库。

```powershell
loveca cards init --database data/loveca.sqlite3
```

2. 从官网抓取卡牌并生成本地规范化产物。

```powershell
loveca cards import-official `
  --output-root data/imports/official `
  --delay 1
```

3. 将规范化产物导入 SQLite。

```powershell
loveca cards import `
  --database data/loveca.sqlite3 `
  --input data/imports/official/normalized/cards-official.json `
  --normalization data_sources/card-entity-normalization.json `
  --report logs/import-full.md
```

4. 构建前端。

```powershell
cd web
npm run build
cd ..
```

5. 如需牌面图片，先缓存官方图片。

```powershell
loveca cards cache-images `
  --database data/loveca.sqlite3 `
  --cache-dir data/card_images `
  --delay 1
```

6. 启动 Web UI。

```powershell
loveca web serve `
  --database data/loveca.sqlite3 `
  --matches data/matches.sqlite3 `
  --image-cache data/card_images `
  --host 127.0.0.1 `
  --port 8765
```

浏览器访问 <http://127.0.0.1:8765>。

如果 `8765` 已被占用，可以改成 `--port 8766`。

## 常用命令

牌组分析:

```powershell
loveca decks analyze `
  --database data/loveca.sqlite3 `
  --deck data/decks/your-deck.json `
  --output text
```

按补充包增量导入:

```powershell
loveca cards import-official `
  --output-root data/imports/official-bp06 `
  --mode incremental-set `
  --card-set BP06 `
  --delay 1
```

```powershell
loveca cards import `
  --database data/loveca.sqlite3 `
  --input data/imports/official/normalized/cards-official.json `
  --normalization data_sources/card-entity-normalization.json `
  --card-set BP06 `
  --report logs/import-bp06.md
```

## 测试

Python:

```powershell
python -m pytest
```

前端:

```powershell
cd web
npm run test -- --run
npm run build
```

## 目录概览

- `src/loveca/cards/`: importer、catalog、图片缓存
- `src/loveca/decks/`: 牌组格式、分析器、本地牌组库
- `src/loveca/simulation/`: GameState、Action、runtime、effects
- `src/loveca/webapp.py`: FastAPI 与 SPA 分发
- `web/`: React 规则验证 UI
- `docs/`, `specs/`: 架构文档与规格
