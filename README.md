# AI Relay

Opus（Genspark 聊天）负责规划与审查，Codex / dsh 由本地分发器自动执行，Grok Bot 处理网页与运营类任务。

常用命令（在 ai-relay 目录下）：
- python3 scripts/relay.py run            执行一个可运行任务
- python3 scripts/relay.py run --watch    持续轮询执行
- python3 scripts/relay.py run --dry-run  只打印将执行什么
- python3 scripts/relay.py status         重新生成 STATUS.md 并推送
- python3 scripts/relay.py approve T001   合并 relay/T001 分支并标记通过
- python3 scripts/relay.py reject T001 "意见"  附上意见并退回 todo

审查入口：STATUS.md 的 raw 链接。
