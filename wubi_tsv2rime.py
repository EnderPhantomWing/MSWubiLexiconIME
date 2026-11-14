#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把「emoji + 中文含义」对照表转换为 Rime 的 dict.yaml（五笔编码）。

输入格式（每行）：
    😀	闭笑	大笑
    😅	冷汗	苦笑
    Ω	omeg	欧姆	ohm
    😀	good	good        # 纯 ASCII 1-4 字母视为直接编码

输出格式：
    ---
    name: emoji
    version: "1.0"
    sort: by_weight
    columns:
      - text
      - code
      - weight
    ...
    😀	khhh	1000000
    😅	kfim	999999
    ...

用法：
    python emoji_to_rime_dict.py emoji.txt -o emoji.dict.yaml
    python emoji_to_rime_dict.py emoji.txt -o emoji.dict.yaml --strip-non-cjk
    python emoji_to_rime_dict.py emoji.txt --meaning-sep '、' --dict wubi86_words.tsv
"""

import argparse
import os
import sys
import unicodedata

DICT_FILENAME = "wubi86_words.tsv"
MAX_DIRECT_CODE_LEN = 4
MAX_WARNINGS = 50
DEFAULT_START_WEIGHT = 1000000


def eprint(*args):
    """向 stderr 输出（不污染生成文件）。"""
    print(*args, file=sys.stderr)


# --------------------------------------------------------------------------- #
# 五笔码表
# --------------------------------------------------------------------------- #
def resolve_dict(path):
    """定位五笔码表：优先 --dict，其次脚本所在目录的 wubi86_words.tsv。"""
    if path:
        full = os.path.abspath(os.path.expanduser(path))
        if not os.path.isfile(full):
            raise SystemExit("错误：找不到码表文件 %s" % full)
        return full
    full = os.path.join(os.path.dirname(os.path.abspath(__file__)), DICT_FILENAME)
    if not os.path.isfile(full):
        raise SystemExit(
            "错误：找不到内置码表 %s。\n"
            "请把它放在脚本同目录，或用 --dict 指定码表路径。" % DICT_FILENAME
        )
    return full


def load_table(path):
    """读取 <汉字>\\t<五笔编码> 码表，返回 (dict, 非法行数)。"""
    table = {}
    bad = 0
    with open(path, "r", encoding="utf-8-sig") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                parts = line.split()
            if len(parts) < 2:
                continue
            char, code = parts[0].strip(), parts[1].strip().lower()
            if len(char) != 1 or not code:
                continue
            # 五笔只用 a-y，z 是通配符
            if any(c < "a" or c > "y" for c in code):
                bad += 1
                continue
            table[char] = code
    if not table:
        raise SystemExit("错误：码表 %s 为空或格式不正确。" % path)
    return table, bad


# --------------------------------------------------------------------------- #
# 编码规则
# --------------------------------------------------------------------------- #
def wubi_code(word, table):
    """按五笔 86 规则求词组编码；返回 (code, 缺失字符)。"""
    codes = []
    for char in word:
        code = table.get(char)
        if code is None:
            return None, char
        codes.append(code)
    n = len(codes)
    if n == 0:
        return None, ""
    if n == 1:
        return codes[0], None
    if n == 2:
        return codes[0][:2] + codes[1][:2], None
    if n == 3:
        return codes[0][0] + codes[1][0] + codes[2][:2], None
    return codes[0][0] + codes[1][0] + codes[2][0] + codes[-1][0], None


def is_cjk(char):
    code = ord(char)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0xF900 <= code <= 0xFAFF
        or 0x20000 <= code <= 0x2FA1F
    )


def is_direct_code(text):
    """纯 ASCII 小写字母、1-4 字符 → 直接作为编码。"""
    if not text or not (1 <= len(text) <= MAX_DIRECT_CODE_LEN):
        return False
    return all("a" <= c <= "z" for c in text.lower())


def looks_like_long_code(text):
    """看起来像自定义编码但超过 4 字符（用于报错提示）。"""
    return (
        bool(text)
        and len(text) > MAX_DIRECT_CODE_LEN
        and all("a" <= c <= "z" for c in text.lower())
    )


# --------------------------------------------------------------------------- #
# 输入解析
# --------------------------------------------------------------------------- #
def parse_input(path, encoding="utf-8-sig", sep="auto"):
    """解析文本对照表，返回 ([(行号, emoji, [含义...])], [(行号, 错误说明)])。"""
    if not os.path.isfile(path):
        raise SystemExit("错误：找不到输入文件 %s" % path)

    pairs = []
    problems = []
    with open(path, "r", encoding=encoding) as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\r\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if sep == "auto":
                fields = line.split("\t") if "\t" in line else line.split()
            else:
                if sep not in line:
                    problems.append((lineno, "找不到分隔符 %r" % sep))
                    continue
                fields = line.split(sep)
            fields = [f.strip() for f in fields if f.strip()]
            if len(fields) < 2:
                problems.append((lineno, "至少需要 emoji 和一个含义"))
                continue
            emoji, meanings = fields[0], fields[1:]
            pairs.append(
                (lineno, emoji, [unicodedata.normalize("NFC", m) for m in meanings])
            )
    return pairs, problems


def expand_meanings(pairs, meaning_sep):
    """按 --meaning-sep 把一个单元格拆成多个含义。"""
    if not meaning_sep:
        return pairs
    expanded = []
    for lineno, emoji, meanings in pairs:
        items = []
        for meaning in meanings:
            items.extend(
                part.strip() for part in meaning.split(meaning_sep) if part.strip()
            )
        if items:
            expanded.append((lineno, emoji, items))
    return expanded


# --------------------------------------------------------------------------- #
# YAML 输出工具
# --------------------------------------------------------------------------- #
def yaml_scalar(text):
    """YAML plain scalar 的安全输出；必要时加双引号。"""
    if not text:
        return '""'
    special_starts = "-?:,[]{}#&*!|>'\"%@`"
    needs_quote = (
        text[0] in special_starts
        or text[0].isspace()
        or text[-1].isspace()
        or any(c in text for c in ("\n", "\r", "\t"))
        or ": " in text
        or text.lower() in ("null", "true", "false", "yes", "no", "on", "off", "~")
    )
    if needs_quote:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def build_parser():
    parser = argparse.ArgumentParser(
        prog="emoji_to_rime_dict.py",
        description="把「emoji + 中文含义」TSV 转换为 Rime 的 dict.yaml（五笔编码）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python emoji_to_rime_dict.py emoji.txt -o emoji.dict.yaml\n"
            "  python emoji_to_rime_dict.py emoji.txt -o emoji.dict.yaml --strip-non-cjk\n"
            "  python emoji_to_rime_dict.py emoji.txt --meaning-sep '、' -o emoji.dict.yaml\n"
        ),
    )
    parser.add_argument(
        "input", help="输入对照表（UTF-8，每行「emoji <Tab> 含义1 <Tab> 含义2 ...」）"
    )
    parser.add_argument(
        "-o", "--output", default="emoji.dict.yaml",
        help="输出 dict.yaml（默认 emoji.dict.yaml）",
    )
    parser.add_argument(
        "--name", default=None,
        help="字典名（默认从输出文件名取，去掉 .dict.yaml 后缀）",
    )
    parser.add_argument("--version", default="1.0", help="字典版本（默认 1.0）")
    parser.add_argument(
        "--dict", default=None,
        help="五笔码表（默认使用脚本同目录的 %s）" % DICT_FILENAME,
    )
    parser.add_argument(
        "--sep", default="auto",
        help="列分隔符：auto（默认）/ tab / space / 或直接写字符",
    )
    parser.add_argument(
        "--meaning-sep", default=None,
        help="单元格内多个含义的拆字符（如 '、'）；默认不拆",
    )
    parser.add_argument("--encoding", default="utf-8-sig", help="输入文件编码（默认 utf-8-sig）")
    parser.add_argument(
        "--strip-non-cjk", action="store_true",
        help="编码前去掉含义里的空格、标点、字母等非汉字字符",
    )
    parser.add_argument(
        "--no-literal-code", action="store_true",
        help="关闭「纯 ASCII 字母（a-z、长度 1-4）作为直接编码」的识别",
    )
    parser.add_argument(
        "--start-weight", type=int, default=DEFAULT_START_WEIGHT,
        help="起始权重（默认 %d）" % DEFAULT_START_WEIGHT,
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="有任何一条无法转换就报错退出，不写文件",
    )
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass

    args = build_parser().parse_args(argv)
    if args.start_weight < 1:
        raise SystemExit("错误：--start-weight 必须大于 0。")

    dict_path = resolve_dict(args.dict)
    table, bad_codes = load_table(dict_path)
    if bad_codes:
        eprint("警告：码表中有 %d 条编码含非法字母，已忽略。" % bad_codes)

    sep = args.sep
    if sep.lower() == "auto":
        sep = "auto"
    elif sep.lower() == "tab":
        sep = "\t"
    elif sep.lower() == "space":
        sep = " "

    pairs, parse_problems = parse_input(args.input, args.encoding, sep)
    if not pairs and not parse_problems:
        raise SystemExit("错误：输入文件里没有可用的数据行。")

    pairs = expand_meanings(pairs, args.meaning_sep)

    # 去掉非汉字（可选）
    if args.strip_non_cjk:
        cleaned = []
        for lineno, emoji, meanings in pairs:
            kept = []
            for meaning in meanings:
                stripped = "".join(ch for ch in meaning if is_cjk(ch))
                if not stripped:
                    parse_problems.append(
                        (lineno, "「%s」去掉非汉字后为空" % meaning)
                    )
                    continue
                kept.append(stripped)
            if kept:
                cleaned.append((lineno, emoji, kept))
        pairs = cleaned

    # 生成条目
    entries = []
    seen = set()
    encode_errors = []
    duplicate_rows = 0

    for lineno, emoji, meanings in pairs:
        for text in meanings:
            direct = not args.no_literal_code and is_direct_code(text)
            effective = text.lower() if direct else text
            key = (emoji, effective)
            if key in seen:
                duplicate_rows += 1
                continue
            seen.add(key)

            if direct:
                code = effective
            else:
                code, missing = wubi_code(text, table)
                if code is None:
                    if not args.no_literal_code and looks_like_long_code(text):
                        reason = "自定义编码 %r 超过 %d 字符上限" % (
                            text, MAX_DIRECT_CODE_LEN
                        )
                    elif not missing:
                        reason = "含义为空"
                    elif not is_cjk(missing):
                        reason = "包含非汉字字符 %r" % missing
                    else:
                        reason = "码表中缺少汉字 %r" % missing
                    encode_errors.append((lineno, emoji, text, reason))
                    continue

            entries.append({"text": emoji, "code": code})

    # 报告问题
    if parse_problems:
        eprint("输入格式问题（%d 行）：" % len(parse_problems))
        for lineno, msg in parse_problems[:MAX_WARNINGS]:
            eprint("  第 %d 行：%s" % (lineno, msg))
        if len(parse_problems) > MAX_WARNINGS:
            eprint("  ……另有 %d 行" % (len(parse_problems) - MAX_WARNINGS))

    if encode_errors:
        eprint("无法编码的条目（%d 条）：" % len(encode_errors))
        for lineno, emoji, text, reason in encode_errors[:MAX_WARNINGS]:
            eprint("  第 %d 行：%s  %s  —— %s" % (lineno, emoji, text, reason))
        if len(encode_errors) > MAX_WARNINGS:
            eprint("  ……另有 %d 条" % (len(encode_errors) - MAX_WARNINGS))

    if args.strict and (parse_problems or encode_errors):
        eprint("已启用 --strict：存在无法转换的行，未生成文件。")
        return 2

    if not entries:
        eprint("错误：没有任何条目转换成功，未生成文件。")
        return 1

    # 确定输出路径与字典名
    out_path = os.path.abspath(os.path.expanduser(args.output))
    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.isdir(out_dir):
        raise SystemExit("错误：输出目录不存在 %s" % out_dir)

    name = args.name
    if not name:
        base = os.path.basename(out_path)
        for suffix in (".dict.yaml", ".yaml", ".yml"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        name = base or "emoji"

    # 写 YAML：权重按出现次序递减，同一编码内保持文件顺序
    weight = args.start_weight
    lines = [
        "---",
        "name: %s" % yaml_scalar(name),
        "version: %s" % yaml_scalar(args.version),
        "sort: by_weight",
        "use_preset_vocabulary: false",
        "columns:",
        "  - text",
        "  - code",
        "  - weight",
        "...",
        "",
    ]
    for entry in entries:
        lines.append(
            "%s\t%s\t%d" % (yaml_scalar(entry["text"]), entry["code"], weight)
        )
        if weight > 1:
            weight -= 1

    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
        fh.write("\n")

    # 统计
    unique_codes = len({e["code"] for e in entries})
    eprint("已生成：%s" % out_path)
    eprint("  条目：%d 条" % len(entries))
    eprint("  唯一编码：%d 个" % unique_codes)
    if duplicate_rows:
        eprint("  忽略完全重复的「emoji + 含义」：%d 条" % duplicate_rows)

    return 0


if __name__ == "__main__":
    sys.exit(main())
