#!/usr/bin/env python3
"""聚合生成 QuanX 版 Meta.list：
blackmatrix7 Facebook.list + Whatsapp.list，MetaCubeX geosite/meta 域名列表，以及 meta_extra.txt 手动补充。
任何上游拉取失败或结果异常都直接报错退出，不提交任何内容。"""
import sys
import urllib.request
from pathlib import Path

BM = "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/QuantumultX/{0}/{0}.list"
QX_SOURCES = [BM.format("Facebook"), BM.format("Whatsapp")]
# MetaCubeX 文本格式：“+.example.com”为后缀，“example.com”为精确主机
GEOSITE_META = "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/geosite/meta.list"

ROOT = Path(__file__).resolve().parent
EXTRA_FILE = ROOT / "meta_extra.txt"
OUTPUT = ROOT.parent / "Quantumult" / "Meta.list"
POLICY = "Meta"  # 列表内占位策略名，实际策略由配置里的 force-policy 决定
MIN_RULES = 500  # Facebook.list 单独就有约 570 条，低于此值视为拉取异常

ORDER = ["HOST", "HOST-SUFFIX", "HOST-KEYWORD", "IP-CIDR", "IP6-CIDR", "IP-ASN"]


def fetch(url: str) -> list[str]:
    req = urllib.request.Request(url, headers={"User-Agent": "meta-list-build"})
    with urllib.request.urlopen(req, timeout=60) as r:
        if r.status != 200:
            raise RuntimeError(f"{url} -> HTTP {r.status}")
        return r.read().decode("utf-8").splitlines()


def main() -> None:
    rules: dict[str, set[str]] = {k: set() for k in ORDER}
    counts: dict[str, int] = {}

    for url in QX_SOURCES:
        n = 0
        for line in fetch(url):
            line = line.strip()
            if not line or line.startswith(("#", ";", "//")):
                continue
            parts = [p.strip() for p in line.split(",")]
            kind = parts[0].upper()
            if kind not in rules or len(parts) < 2:
                raise RuntimeError(f"{url} 出现无法识别的规则：{line}")
            rules[kind].add(parts[1].lower())
            n += 1
        if n == 0:
            raise RuntimeError(f"{url} 为空")
        counts[url.rsplit("/", 1)[-1]] = n

    n = 0
    for line in fetch(GEOSITE_META):
        line = line.strip().lower()
        if not line or line.startswith("#"):
            continue
        if line.startswith("+."):
            rules["HOST-SUFFIX"].add(line[2:])
        else:
            rules["HOST"].add(line)
        n += 1
    if n == 0:
        raise RuntimeError("geosite/meta 为空")
    counts["geosite/meta"] = n

    extra = [l.strip().lower() for l in EXTRA_FILE.read_text("utf-8").splitlines()
             if l.strip() and not l.lstrip().startswith("#")]
    rules["HOST-SUFFIX"].update(extra)
    counts["meta_extra.txt"] = len(extra)

    # 去重：被某条后缀覆盖的子域后缀和精确主机都没有必要保留
    suffixes = rules["HOST-SUFFIX"]

    def covered_by_parent(d: str, include_self: bool) -> bool:
        labels = d.split(".")
        start = 0 if include_self else 1
        return any(".".join(labels[i:]) in suffixes for i in range(start, len(labels)))

    rules["HOST-SUFFIX"] = {d for d in suffixes if not covered_by_parent(d, include_self=False)}
    suffixes = rules["HOST-SUFFIX"]
    rules["HOST"] = {d for d in rules["HOST"] if not covered_by_parent(d, include_self=True)}

    total = sum(len(v) for v in rules.values())
    if total < MIN_RULES:
        raise RuntimeError(f"结果只有 {total} 条，低于 {MIN_RULES}，判定为上游异常")

    body = []
    for kind in ORDER:
        for value in sorted(rules[kind], key=lambda x: (x.isdigit(), x)):
            body.append(f"{kind},{value},{POLICY}")

    stat = "，".join(f"{k} {v}" for k, v in counts.items())
    header = [
        "# Meta.list：由 scripts/build_meta.py 自动生成，请勿手改",
        f"# 来源：{stat}",
        "# 合计 " + "，".join(f"{k} {len(rules[k])}" for k in ORDER if rules[k]) + f"，共 {total} 条",
    ]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(header + body) + "\n", "utf-8")
    print(header[-1])


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"构建失败：{e}", file=sys.stderr)
        sys.exit(1)
