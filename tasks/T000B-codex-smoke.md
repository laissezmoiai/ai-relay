---
id: T000B
title: Codex 冒烟测试
executor: codex
status: approved
depends:
workspace: app
started: 2026-11-03 18:33
---
## 目标
验证分发链路可用。

## 具体要求
- 在仓库根目录创建 RELAY_SMOKE_CODEX.md，内容为一行：relay ok

## 验收命令
```bash
cat RELAY_SMOKE_CODEX.md
```

## 禁止事项
- 不要修改任何其他文件
