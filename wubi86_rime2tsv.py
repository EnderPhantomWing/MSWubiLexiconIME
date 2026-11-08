#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 rime-wubi 的 wubi86.dict.yaml 中提取「汉字<TAB>全码」并输出 TSV。

规则：
  1. 只保留单个汉字（CJK 统一表意文字）。
  2. 跳过编码以 zz 开头的条目（Rime 五笔用 zz 引导标点/符号）。
  3. 对每个汉字，用剩余的正常编码取「最长编码」作为全码：
     - 4 码字 → 4 码全码
     - 两字根 + 识别码的字 → 3 码全码
     - 1~3 码简码会被自动过滤

支持两种来源：
  - 从 GitHub 下载 wubi86.dict.yaml
  - 使用本地已下载的 yaml 文件
"""

import argparse
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

DEFAULT_URL = (
    "https://raw.githubusercontent.com/rime/rime-wubi/"
    "refs/heads/master/wubi86.dict.yaml"
)
DEFAULT_OUTPUT = "wubi86_fullcode.tsv"


# ---------- 汉字判定 ----------
def is_cjk_hanzi(ch: str) -> bool:
    """判断是否为单个 CJK 汉字（基本区 + 扩展 A + 兼容区）。"""
    if len(ch) != 1:
        return False
    cp = ord(ch)
    return (
        0x4E00 <= cp <= 0x9FFF      # CJK 统一表意文字
        or 0x3400 <= cp <= 0x4DBF   # 扩展 A
        or 0xF900 <= cp <= 0xFAFF   # 兼容表意文字
        or 0x20000 <= cp <= 0x2A6DF # 扩展 B（可选）
    )


# ---------- 读取来源 ----------
def load_text(source: str) -> str:
    if source.startswith(("http://", "https://")):
        print(f"正在下载：{source}", file=sys.stderr)
        with urllib.request.urlopen(source) as resp:
            raw = resp.read()
        return raw.decode("utf-8-sig")
    print(f"正在读取本地文件：{source}", file=sys.stderr)
    return Path(source).read_text(encoding="utf-8-sig")


# ---------- 解析词典 ----------
def collect_single_char_codes(text: str) -> dict:
    """
    解析词典正文，返回 {汉字: set(正常编码)}。
    - 只收集单个汉字
    - 跳过 zz 开头的编码
    """
    codes = defaultdict(set)
    in_body = False
    skipped_zz = 0

    for line in text.splitlines():
        line = line.rstrip("\r\n")
        if not line.strip():
            continue
        if line.strip() == "...":
            in_body = True
            continue
        if not in_body or line.lstrip().startswith("#"):
            continue

        parts = line.split("\t")
        if len(parts) < 2:
            continue

        word, code = parts[0].strip(), parts[1].strip()

        # 只保留单个汉字
        if not is_cjk_hanzi(word):
            continue

        # 过滤 zz 开头的符号编码
        if code.lower().startswith("zz"):
            skipped_zz += 1
            continue

        if not code:
            continue

        codes[word].add(code)

    if skipped_zz:
        print(f"已跳过 {skipped_zz} 条 zz 开头编码", file=sys.stderr)
    return codes


# ---------- 选取全码 ----------
def pick_full_codes(all_codes: set) -> list:
    """取最长编码作为全码；等长的全部保留。"""
    if not all_codes:
        return []
    max_len = max(len(c) for c in all_codes)
    return sorted(c for c in all_codes if len(c) == max_len)


# ---------- 输出 ----------
def write_tsv(codes: dict, output_path: str) -> int:
    count = 0
    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        for word in sorted(codes.keys()):
            for code in pick_full_codes(codes[word]):
                f.write(f"{word}\t{code}\n")
                count += 1
    return count


# ---------- 主流程 ----------
def main():
    parser = argparse.ArgumentParser(
        description="从 wubi86.dict.yaml 提取汉字全码，输出 TSV（过滤 zz 符号）"
    )
    parser.add_argument(
        "-s", "--source", default=None,
        help="词典来源：URL 或本地文件路径。不指定时交互询问。"
    )
    parser.add_argument(
        "-o", "--output", default=DEFAULT_OUTPUT,
        help=f"输出 TSV 文件路径（默认 {DEFAULT_OUTPUT}）"
    )
    args = parser.parse_args()

    source = args.source
    if source is None:
        print("请选择词典来源：")
        print("  1) 从网络下载（GitHub rime-wubi/wubi86.dict.yaml）")
        print("  2) 使用本地文件")
        choice = input("输入 1 或 2 [默认 1]: ").strip() or "1"
        if choice == "1":
            source = DEFAULT_URL
        elif choice == "2":
            source = input("请输入本地文件路径：").strip()
            if not source:
                print("未提供路径，退出。", file=sys.stderr)
                sys.exit(1)
        else:
            print("无效选择，退出。", file=sys.stderr)
            sys.exit(1)

    text = load_text(source)

    print("正在解析单字编码…", file=sys.stderr)
    codes = collect_single_char_codes(text)
    print(f"共找到 {len(codes)} 个汉字", file=sys.stderr)

    n = write_tsv(codes, args.output)
    print(f"已写入 {n} 行到 {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
