---
id: T000
title: 冒烟测试
executor: dsh
status: doing
depends:
workspace: app
started: 2026-11-03 17:42
---
## 目标
验证分发链路可用。

## 具体要求
- 在仓库根目录创建 RELAY_SMOKE.md，内容为一行：relay ok

## 验收命令
```bash
cat RELAY_SMOKE.md
```

## 禁止事项
- 不要修改任何其他文件
