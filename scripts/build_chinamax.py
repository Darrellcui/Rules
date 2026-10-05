#!/usr/bin/env python3
"""从 blackmatrix7 ChinaMax 生成清洗版：去掉与境外服务列表冲突的条目、关键字规则和手动排除项；
同时生成 STUN.list，把常见 STUN 服务器以最高优先级的精确 host 规则拉回代理。
任何上游拉取失败或结果异常都直接报错退出，不提交任何内容。"""
import sys
import urllib.request
from pathlib import Path

UPSTREAM = "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/QuantumultX/ChinaMax/ChinaMax.list"
BM = "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/QuantumultX/{0}/{0}.list"
# 与 QuanX 配置里 [filter_remote] 的境外服务列表保持一致
PROTECTED_LISTS = [BM.format(n) for n in (
    "Twitter", "Claude", "Line", "Google", "LinkedIn", "OpenAI",
    "YouTube", "TikTok", "Microsoft", "LineTV", "Netflix", "PayPal",
)] + [
    "https://raw.githubusercontent.com/Darrellcui/Rules/refs/heads/main/Quantumult/MultiRules.list",
    "https://raw.githubusercontent.com/sve1r/Rules-For-Quantumult-X/main/Rules/Services/Paypal.list",
]
STUN_LISTS = [
    "https://raw.githubusercontent.com/pradt2/always-online-stun/master/valid_hosts.txt",
    "https://raw.githubusercontent.com/pradt2/always-online-stun/master/valid_hosts_tcp.txt",
]
ROOT = Path(__file__).resolve().parent
STUN_EXTRA_FILE = ROOT / "stun_extra.txt"
STUN_OUTPUT = ROOT.parent / "Quantumult" / "STUN.list"
MIN_STUN = 100  # 公共列表正常有两百多个主机名
EXCLUDE_FILE = ROOT / "chinamax_exclude.txt"
OUTPUT = ROOT.parent / "Quantumult" / "ChinaMax_Clean.list"
# 同一次运行中由 build_meta.py 先生成的本地列表，同样视为受保护的境外服务
PROTECTED_LOCAL = [ROOT.parent / "Quantumult" / "Meta.list"]
MIN_RULES = 100_000  # 上游正常规模约 12 万条，低于此值视为拉取异常


def fetch(url: str) -> list[str]:
    req = urllib.request.Request(url, headers={"User-Agent": "chinamax-clean"})
    with urllib.request.urlopen(req, timeout=60) as r:
        if r.status != 200:
            raise RuntimeError(f"{url} -> HTTP {r.status}")
        return r.read().decode("utf-8").splitlines()


def parse(line: str):
    line = line.strip()
    if not line or line.startswith(("#", ";", "//")):
        return None
    parts = [p.strip() for p in line.split(",")]
    return (parts[0].upper(), parts[1].lower()) if len(parts) >= 2 else None


def covered(domain: str, suffixes: set[str]) -> bool:
    labels = domain.split(".")
    return any(".".join(labels[i:]) in suffixes for i in range(len(labels)))


def is_ip(host: str) -> bool:
    return host.replace(".", "").isdigit() or ":" in host


def load_stun_hosts() -> set[str]:
    hosts: set[str] = set()
    for url in STUN_LISTS:
        for line in fetch(url):
            line = line.strip()
            if line and not line.startswith("#"):
                hosts.add(line.rsplit(":", 1)[0].strip("[]").lower())
    hosts |= {l.strip().lower() for l in STUN_EXTRA_FILE.read_text("utf-8").splitlines()
              if l.strip() and not l.lstrip().startswith("#")}
    hosts = {h for h in hosts if not is_ip(h)}
    if len(hosts) < MIN_STUN:
        raise RuntimeError(f"STUN 主机名只有 {len(hosts)} 个，低于 {MIN_STUN}，判定为上游异常")
    return hosts


def main() -> None:
    protected: set[str] = set()
    for url in PROTECTED_LISTS:
        for line in fetch(url):
            p = parse(line)
            if p and p[0] in ("HOST", "HOST-SUFFIX"):
                protected.add(p[1])
    for path in PROTECTED_LOCAL:
        if not path.exists():
            raise RuntimeError(f"{path.name} 不存在，需先运行对应的构建脚本")
        for line in path.read_text("utf-8").splitlines():
            p = parse(line)
            if p and p[0] in ("HOST", "HOST-SUFFIX"):
                protected.add(p[1])
    if not protected:
        raise RuntimeError("境外服务列表为空")

    excluded = {l.strip().lower() for l in EXCLUDE_FILE.read_text("utf-8").splitlines()
                if l.strip() and not l.lstrip().startswith("#")}
    block = protected | excluded
    stun_hosts = load_stun_hosts()

    upstream = fetch(UPSTREAM)
    kept, stats = [], {"keyword": 0, "conflict": 0, "excluded": 0, "stun": 0}
    for line in upstream:
        p = parse(line)
        if p is None:
            continue
        kind, value = p
        if kind == "HOST-KEYWORD":
            stats["keyword"] += 1
            continue
        if kind == "HOST" and value in stun_hosts:
            stats["stun"] += 1
            continue
        if kind in ("HOST", "HOST-SUFFIX", "HOST-WILDCARD") and covered(value, block):
            stats["excluded" if covered(value, excluded) else "conflict"] += 1
            continue
        kept.append(line.strip())

    if len(kept) < MIN_RULES:
        raise RuntimeError(f"结果只有 {len(kept)} 条，低于 {MIN_RULES}，判定为上游异常")

    header = [
        "# ChinaMax_Clean：由 scripts/build_chinamax.py 自动生成，请勿手改",
        f"# 上游：{UPSTREAM}",
        f"# 保留 {len(kept)} 条；移除关键字 {stats['keyword']}、与境外列表冲突 {stats['conflict']}、手动排除 {stats['excluded']}、STUN 主机 {stats['stun']}",
    ]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(header + kept) + "\n", "utf-8")
    print(header[-1])

    # 已在境外服务列表里的 STUN 主机（如 Google）保持原策略，不在这里覆盖
    stun_rules = sorted(h for h in stun_hosts if not covered(h, protected))
    STUN_OUTPUT.write_text("\n".join([
        "# STUN.list：由 scripts/build_chinamax.py 自动生成，请勿手改",
        "# 来源：pradt2/always-online-stun + scripts/stun_extra.txt",
        f"# 共 {len(stun_rules)} 个主机名；host 精确规则优先级最高，可压过 ChinaMax 的后缀规则",
    ] + [f"host, {h}, proxy" for h in stun_rules]) + "\n", "utf-8")
    print(f"STUN.list：{len(stun_rules)} 条")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"构建失败：{e}", file=sys.stderr)
        sys.exit(1)
