---
id: T001
title: 一句话标题
executor: codex
status: todo
depends:
workspace: app
---
## 目标
一句话。

## 上下文
相关文件路径、接口约定、参考资料。

## 具体要求
- 可验证的要求 1
- 可验证的要求 2

## 验收命令
```bash
ls
```

## 禁止事项
- 不要修改 xxx

<!-- executor: codex / dsh / grokbot；status: todo → doing → review → approved（打回则回到 todo，失败为 failed）；depends: 逗号分隔的任务 id，依赖全部 approved 才执行 -->
