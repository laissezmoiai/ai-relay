#!/usr/bin/env python3
"""AI Relay 分发器：tasks/ -> codex/dsh -> reports/ -> STATUS.md -> git push"""
import argparse, json, re, subprocess, sys, time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "relay.config.json").read_text(encoding="utf-8"))
TASKS, REPORTS, LOGS = ROOT / "tasks", ROOT / "reports", ROOT / "logs"
FM_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)
REPORT_RE = re.compile(r"<<<REPORT\s*\n(.*?)\nREPORT>>>", re.S)


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def sh(args, cwd=None, check=True):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"命令失败: {' '.join(args)}\n{r.stdout}\n{r.stderr}")
    return r


def load(path):
    text = path.read_text(encoding="utf-8")
    m = FM_RE.match(text)
    if not m:
        return None
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    if "id" not in meta:
        return None
    meta["_path"], meta["_text"] = path, text
    return meta


def all_tasks():
    return [t for t in (load(p) for p in sorted(TASKS.glob("T*.md"))) if t]


def find(tid):
    for t in all_tasks():
        if t["id"] == tid:
            return t
    sys.exit(f"找不到任务 {tid}")


def set_field(t, key, value):
    text = t["_path"].read_text(encoding="utf-8")
    m = FM_RE.match(text)
    fm = m.group(1)
    if re.search(rf"^{key}:", fm, re.M):
        fm = re.sub(rf"^{key}:.*$", lambda _: f"{key}: {value}", fm, count=1, flags=re.M)
    else:
        fm += f"\n{key}: {value}"
    t["_path"].write_text(f"---\n{fm}\n---\n" + text[m.end():], encoding="utf-8")
    t[key] = value


def redact(s):
    for p in CFG.get("redact_patterns", []):
        s = re.sub(p, "[REDACTED]", s)
    return s


def workspace(t):
    name = t.get("workspace") or CFG["default_workspace"]
    return Path(CFG["workspaces"][name]).expanduser()


def ensure_clean(ws):
    if sh(["git", "status", "--porcelain"], cwd=ws).stdout.strip():
        raise RuntimeError(f"项目仓库 {ws} 有未提交改动，请先清理")


def pull():
    sh(["git", "pull", "--rebase", "--autostash"], cwd=ROOT, check=False)


def push(msg):
    write_status()
    sh(["git", "add", "-A"], cwd=ROOT)
    if sh(["git", "diff", "--cached", "--quiet"], cwd=ROOT, check=False).returncode == 0:
        return
    sh(["git", "commit", "-m", msg], cwd=ROOT)
    if CFG.get("auto_push", True):
        pull()
        r = sh(["git", "push"], cwd=ROOT, check=False)
        if r.returncode != 0:
            print("警告：push 失败\n" + r.stderr)


def ready(t, tasks):
    deps = [d.strip() for d in t.get("depends", "").split(",") if d.strip()]
    st = {x["id"]: x.get("status") for x in tasks}
    return all(st.get(d) == "approved" for d in deps)


def build_prompt(t):
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    return f"""你是 AI Relay 的执行者。先阅读协作规则，再完成任务卡。

=== 协作规则 ===
{agents}

=== 任务卡 ===
{t['_text']}

=== 交付要求 ===
1. 直接在当前目录的仓库中修改代码；不要 git commit，不要切换分支。
2. 运行任务卡中的验收命令。
3. 最后一条回复必须包含如下格式的报告（两个标记各自单独成行）：
<<<REPORT
改动文件: ...
做了什么: ...
验收命令与结果: ...
需要 Opus 决策 / 遗留问题: ...
REPORT>>>
"""


def write_status():
    base = CFG["raw_base"]
    lines = [f"# AI Relay 状态（更新于 {now()}）", "",
             f"计划：{base}PLAN.md", "",
             "| ID | 标题 | 执行者 | 状态 | 依赖 | 任务卡 | 报告 |",
             "|---|---|---|---|---|---|---|"]
    for t in all_tasks():
        rep = REPORTS / f"{t['id']}.md"
        rlink = f"{base}reports/{t['id']}.md" if rep.exists() else "-"
        lines.append(f"| {t['id']} | {t.get('title','')} | {t.get('executor','')} | "
                     f"{t.get('status','')} | {t.get('depends','') or '-'} | "
                     f"{base}tasks/{t['_path'].name} | {rlink} |")
    (ROOT / "STATUS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


TRANSIENT = ("stream_closed", "at capacity", "rate limit", "too many requests",
             "overloaded", "service unavailable", "bad gateway", "econnreset", "etimedout")


def execute(cmd, ws, ex):
    delays = CFG.get("retry_delays_sec", [30, 90, 180])
    logs, code = [], -1
    for attempt in range(len(delays) + 1):
        try:
            r = subprocess.run(cmd, cwd=ws, capture_output=True, text=True,
                               timeout=CFG["executors"][ex].get("timeout_sec", 3600))
            out, code = (r.stderr or "") + "\n" + (r.stdout or ""), r.returncode
        except subprocess.TimeoutExpired:
            out, code = "执行超时", -1
        except FileNotFoundError as e:
            return f"找不到执行器命令: {e}", -2
        logs.append(f"===== 第 {attempt + 1} 次尝试，退出码 {code} =====\n{out}")
        low = out.lower()
        if code == 0 or attempt == len(delays) or not any(k in low for k in TRANSIENT):
            break
        print(f"  临时错误，{delays[attempt]} 秒后重试（第 {attempt + 2} 次）...")
        time.sleep(delays[attempt])
    return "\n".join(logs), code


def run_task(t, dry=False):
    tid, ex = t["id"], t["executor"].lower()
    ws, base = workspace(t), CFG["base_branch"]
    branch = f"relay/{tid}"
    cmd = [a.replace("{prompt}", build_prompt(t)) for a in CFG["executors"][ex]["cmd"]]
    if dry:
        print(f"[dry-run] {tid} -> {ex} @ {ws} 分支 {branch}")
        return
    ensure_clean(ws)
    set_field(t, "status", "doing")
    set_field(t, "started", now())
    push(f"[relay] {tid} doing")

    sh(["git", "checkout", base], cwd=ws)
    exists = sh(["git", "rev-parse", "--verify", branch], cwd=ws, check=False).returncode == 0
    sh(["git", "checkout", branch] if exists else ["git", "checkout", "-b", branch], cwd=ws)
    print(f"执行 {tid} -> {ex} ...")
    out, code = execute(cmd, ws, ex)
    LOGS.mkdir(exist_ok=True)
    (LOGS / f"{tid}.log").write_text(out, encoding="utf-8")

    sh(["git", "add", "-A"], cwd=ws)
    sh(["git", "commit", "-m", f"[relay] {tid}: {t.get('title','')}"], cwd=ws, check=False)
    stat = sh(["git", "diff", "--stat", f"{base}...{branch}"], cwd=ws, check=False).stdout
    diff = sh(["git", "diff", f"{base}...{branch}"], cwd=ws, check=False).stdout
    sh(["git", "checkout", base], cwd=ws)

    found = [x for x in REPORT_RE.findall(out) if "改动文件: ...\n做了什么: ..." not in x]
    selfrep = found[-1].strip() if found else "（执行者未按格式输出报告）"
    limit = CFG.get("max_diff_chars", 20000)
    if len(diff) > limit:
        diff = diff[:limit] + f"\n... [已截断，原长 {len(diff)} 字符]"
    ok = code == 0 and bool(found)
    body = [f"# 报告 {tid}: {t.get('title','')}", "",
            f"- 执行者: {ex}", f"- 退出码: {code}", f"- 时间: {now()}",
            f"- 分支: {branch}", f"- 结果: {'待审查' if ok else '失败'}", "",
            "## 执行者自述", "", selfrep, "",
            "## 改动统计", "", "~~~~", stat.strip() or "(无改动)", "~~~~", ""]
    if limit > 0:
        body += ["## Diff", "", "~~~~diff", diff.strip() or "(无)", "~~~~", ""]
    if not ok:
        body += ["## 日志尾部", "", "~~~~", out[-4000:], "~~~~", ""]
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"{tid}.md").write_text(redact("\n".join(body)), encoding="utf-8")
    set_field(t, "status", "review" if ok else "failed")
    push(f"[relay] {tid} {'review' if ok else 'failed'}")


def cmd_run(args):
    while True:
        pull()
        ran = False
        for t in all_tasks():
            if args.only and t["id"] != args.only:
                continue
            if (t.get("status") == "todo" and t.get("executor", "").lower() in CFG["executors"]
                    and ready(t, all_tasks())):
                try:
                    run_task(t, args.dry_run)
                    ran = True
                except Exception as e:
                    print(f"{t['id']} 出错: {e}")
                    if not args.dry_run:
                        set_field(t, "status", "failed")
                        push(f"[relay] {t['id']} error")
                if not args.dry_run:
                    break
        if not args.watch:
            if not ran:
                print("没有可执行的任务")
            if not args.dry_run:
                push("[relay] status")
            return
        time.sleep(CFG.get("poll_interval_sec", 60))


def cmd_approve(args):
    t = find(args.id)
    if t.get("executor", "").lower() in CFG["executors"]:
        ws = workspace(t)
        ensure_clean(ws)
        sh(["git", "checkout", CFG["base_branch"]], cwd=ws)
        sh(["git", "merge", "--no-ff", "-m", f"[relay] merge {args.id}", f"relay/{args.id}"], cwd=ws)
    set_field(t, "status", "approved")
    push(f"[relay] {args.id} approved")


def cmd_reject(args):
    t = find(args.id)
    with open(t["_path"], "a", encoding="utf-8") as f:
        f.write(f"\n\n## 审查意见（{now()}）\n{args.feedback}\n")
    t = find(args.id)
    set_field(t, "status", "todo")
    push(f"[relay] {args.id} rejected")


def main():
    p = argparse.ArgumentParser(description="AI Relay 分发器")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--watch", action="store_true")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--only")
    sub.add_parser("status")
    a = sub.add_parser("approve"); a.add_argument("id")
    j = sub.add_parser("reject"); j.add_argument("id"); j.add_argument("feedback")
    args = p.parse_args()
    if args.cmd == "run":
        cmd_run(args)
    elif args.cmd == "status":
        pull(); push("[relay] status")
    elif args.cmd == "approve":
        cmd_approve(args)
    elif args.cmd == "reject":
        cmd_reject(args)


if __name__ == "__main__":
    main()
