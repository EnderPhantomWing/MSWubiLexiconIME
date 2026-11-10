#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
author:
    Nativu5
    gxgzf
    EnderPhantomWing
    DeepSeek
"""
"""把「emoji + 中文含义」对照表直接转换为五笔输入法的用户自定义短语 .dat。

一个 emoji 可以对应多个含义，用 Tab 隔开即可::

    😀	咧嘴	嘿嘿
    😃	张嘴	哈哈

每个含义都会单独生成一条记录（各自计算五笔编码），emoji 重复出现是正常的。

除自动计算五笔编码外，还支持 **直接指定编码**（含义列写成纯 ASCII 键位）::

    䊘	omeg
    Ω	omeg	欧姆	ohm
    ①	zzgl

上例中：
- ``omeg``、``ohm``、``zzgl`` 是纯 ASCII（a-z、长度 ≤ 4），会作为编码原样写入；
- ``欧姆`` 是中文，仍走「算五笔码」的流程，最终也指向 Ω。

**直接编码的限制**：只用 a-z 字母，长度 1-6（含 6）。超过 6 字符
会被拒绝并报错，请自行缩短或改用中文含义。

可用 ``--no-literal-code`` 关闭这一识别，让所有内容都按中文含义计算。
"""

import argparse
import csv
import json
import os
import struct
import sys
import time
import unicodedata

DEFAULT_RANK = 3
DICT_FILENAME = "wubi86_words.tsv"
MAX_WARNINGS = 30
MAX_DIRECT_CODE_LEN = 6


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def eprint(*args):
    """向 stderr 输出（不污染 JSON 文件）。"""
    print(*args, file=sys.stderr)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="wubi_emoji.py",
        description="把 emoji + 中文含义对照表转换为五笔输入法的 .dat / JSON。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python wubi_emoji.py emoji.tsv -o emoji_wubi.dat\n"
            "  python wubi_emoji.py emoji.tsv -o emoji_wubi.dat --json emoji_wubi.json\n"
            "  python wubi_emoji.py emoji含义清单.csv --strip-non-cjk -o emoji_wubi.dat\n"
            "  python wubi_emoji.py words.tsv --meaning-sep '、'\n"
        ),
    )
    parser.add_argument(
        "input", help="输入对照表（UTF-8，每行「emoji <Tab> 含义1 <Tab> 含义2 ...」）"
    )
    parser.add_argument(
        "-o", "--output", default="emoji_wubi.dat",
        help="输出文件（默认 emoji_wubi.dat；以 .json 结尾时只写 JSON）",
    )
    parser.add_argument("--json", default=None, help="额外保存一份中间 JSON 到该路径（可选）")
    parser.add_argument(
        "--dict", default=None, help="五笔码表（默认使用脚本同目录的 %s）" % DICT_FILENAME
    )
    parser.add_argument(
        "--start-rank", type=int, default=DEFAULT_RANK,
        help="候选起始位置（默认 %d）" % DEFAULT_RANK,
    )
    parser.add_argument(
        "--sep", default="auto",
        help="文本模式的列分隔符：auto（默认，优先 Tab，其次空白）/ tab / comma / 或直接写字符",
    )
    parser.add_argument(
        "--meaning-sep", default=None,
        help="当一个单元格里放了多个含义时，用它拆分（如 --meaning-sep '、'）；默认不拆分",
    )
    parser.add_argument(
        "--format", choices=("auto", "text", "csv"), default="auto",
        help="输入格式：auto（按扩展名，.csv 用 CSV）/ text（TSV、空格分隔）/ csv",
    )
    parser.add_argument("--emoji-col", default=None, help="CSV 中 emoji 列（列名或从 1 开始的序号）")
    parser.add_argument("--text-col", default=None, help="CSV 中含义列（列名或从 1 开始的序号）")
    parser.add_argument(
        "--strip-non-cjk", action="store_true",
        help="编码前去掉含义里的空格、标点、字母等非汉字字符（如「男人: 红发」→「男人红发」）",
    )
    parser.add_argument(
        "--no-literal-code", action="store_true",
        help="关闭「纯 ASCII 字母（a-z、长度 1-4）自动作为直接编码」的识别（如 Ω<TAB>omeg 里的 omeg）",
    )
    parser.add_argument("--encoding", default="utf-8-sig", help="输入文件编码（默认 utf-8-sig）")
    parser.add_argument("--swap", action="store_true", help="输入列顺序为「含义... <分隔符> emoji」时使用")
    parser.add_argument("--strict", action="store_true", help="有任何一条无法转换就报错退出，不写文件")
    return parser


def normalize_sep(value):
    """把 --sep 的取值统一成实际分隔符，auto 表示自动判断。"""
    if value is None or value == "" or value.lower() == "auto":
        return "auto"
    named = {"tab": "\t", "\\t": "\t", "comma": ",", "space": " ", "semicolon": ";"}
    return named.get(value.lower(), value)


# --------------------------------------------------------------------------- #
# 码表
# --------------------------------------------------------------------------- #
def resolve_dict(path):
    """定位五笔码表：优先 --dict，其次脚本所在目录的 wubi86.tsv。"""
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
            # 五笔只用 a-y 五个键区，z 是通配符，不能出现在编码里
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
    """按五笔 86 规则求词组的编码；返回 (code, 缺失字符)，失败时 code 为 None。"""
    codes = []
    for char in word:
        code = table.get(char)
        if code is None:
            return None, char
        codes.append(code)

    n = len(codes)
    if n == 0:
        return None, ""
    if n == 1:                       # 单字：全码
        return codes[0], None
    if n == 2:                       # 两字：各取前两码
        return codes[0][:2] + codes[1][:2], None
    if n == 3:                       # 三字：第 1、2 字首码 + 第 3 字前两码
        return codes[0][0] + codes[1][0] + codes[2][:2], None
    # 四字及以上：前三字首码 + 末字首码
    return codes[0][0] + codes[1][0] + codes[2][0] + codes[-1][0], None


def is_cjk(char):
    code = ord(char)
    return (
        0x4E00 <= code <= 0x9FFF        # 基本区
        or 0x3400 <= code <= 0x4DBF     # 扩展 A
        or 0xF900 <= code <= 0xFAFF     # 兼容汉字
        or 0x20000 <= code <= 0x2FA1F   # 扩展 B 及以后
    )


def is_direct_code(text):
    """检查 text 是否是直接编码：纯 ASCII 字母 a-z，长度 1-6。

    满足条件的内容会被当作输入法编码原样写入 .dat，
    不再进入五笔编码计算流程。例：``omeg``、``zzgl``、``kl``。

    注意：这里放行 z 开头（例如 ``zzgl`` = ①）。五笔码表本身仍不收录
    z 码，但用户自定义短语的编码字段可以含 z。
    """
    if not text or not (1 <= len(text) <= MAX_DIRECT_CODE_LEN):
        return False
    return all('a' <= c <= 'z' for c in text.lower())


def looks_like_long_code(text):
    """检查 text 是否"看起来像自定义编码，但超过 4 字符"。

    用于在报错时给出更准确的原因（"编码超过 4 字符"而不是误导性的
    "包含非汉字字符 'o'"）。
    """
    return (
        bool(text)
        and len(text) > MAX_DIRECT_CODE_LEN
        and all('a' <= c <= 'z' for c in text.lower())
    )


# --------------------------------------------------------------------------- #
# 输入解析
# --------------------------------------------------------------------------- #
def parse_input(path, encoding="utf-8-sig", sep="auto", swap=False):
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

            fields = [field.strip() for field in fields]
            fields = [field for field in fields if field]
            if len(fields) < 2:
                problems.append((lineno, "至少需要 emoji 和一个中文含义"))
                continue

            if swap:
                emoji, meanings = fields[-1], fields[:-1]
            else:
                emoji, meanings = fields[0], fields[1:]

            pairs.append(
                (lineno, emoji, [unicodedata.normalize("NFC", m) for m in meanings])
            )

    return pairs, problems


# --------------------------------------------------------------------------- #
# CSV 输入
# --------------------------------------------------------------------------- #
def resolve_col(header, spec, keywords, fallback):
    """把列名或 1 起始序号解析成 0 起始下标。"""
    if spec is not None and spec != "":
        if spec.isdigit():
            idx = int(spec) - 1
            if 0 <= idx < len(header):
                return idx
            raise SystemExit("错误：列序号 %s 超出范围（共 %d 列）。" % (spec, len(header)))
        lowered = [h.strip().lower() for h in header]
        if spec.strip().lower() in lowered:
            return lowered.index(spec.strip().lower())
        raise SystemExit("错误：CSV 中没有列 %r，现有列：%s" % (spec, ", ".join(header)))

    for idx, name in enumerate(header):
        lowered = name.strip().lower()
        if any(key in lowered for key in keywords):
            return idx
    if fallback < len(header):
        return fallback
    raise SystemExit("错误：CSV 列数不足，无法定位 emoji / 含义列。")


def parse_csv(path, encoding="utf-8-sig", emoji_col=None, text_col=None):
    """解析带表头的 CSV，返回 ([(行号, emoji, [含义...])], [(行号, 错误说明)])。"""
    if not os.path.isfile(path):
        raise SystemExit("错误：找不到输入文件 %s" % path)

    pairs = []
    problems = []
    with open(path, "r", encoding=encoding, newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            return [], [(0, "CSV 文件为空")]

        emoji_idx = resolve_col(header, emoji_col, ("emoji", "表情"), 0)
        text_idx = resolve_col(header, text_col, ("含义", "中文", "meaning", "text"), 1)

        for row in reader:
            lineno = reader.line_num
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) <= max(emoji_idx, text_idx):
                problems.append((lineno, "列数不足"))
                continue

            emoji = row[emoji_idx].strip()
            text = row[text_idx].strip()
            if not emoji:
                problems.append((lineno, "emoji 为空"))
                continue
            if not text:
                problems.append((lineno, "中文含义为空"))
                continue

            pairs.append((lineno, emoji, [unicodedata.normalize("NFC", text)]))

    return pairs, problems


def detect_format(path, requested):
    if requested != "auto":
        return requested
    return "csv" if path.lower().endswith(".csv") else "text"


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
# 输出：.dat（mschxudp）与 JSON
# --------------------------------------------------------------------------- #
DAT_RECORD_HEAD = 0x100010
DAT_PROTO = b"mschxudp"
DAT_HEADER_SIZE = 0x40


def dat_record(py_text, string_text, rank):
    """生成一条记录（16 字节头 + UTF-16LE 的按键 + 字符串，各带 2 字节结尾）。"""
    py_encoded = py_text.encode("utf-16le")
    str_encoded = string_text.encode("utf-16le")
    pinyin_len = 16 + len(py_encoded) + 2

    record = struct.pack(
        "<I H B B 2I",
        DAT_RECORD_HEAD,  # recordHead
        pinyin_len,       # pyLen
        rank,             # rank
        0x06,             # rankPad
        0,
        0,                # unknown[2]
    )
    record += py_encoded
    record += struct.pack("<H", 0)
    record += str_encoded
    record += struct.pack("<H", 0)
    return record


def dat_header(offset_start, data_start, file_len, item_cnt, timestamp):
    return struct.pack(
        "<8s 2I 4I 1Q 3Q",
        DAT_PROTO,   # proto
        6291458,
        1,           # version[2]
        offset_start,
        data_start,
        file_len,
        item_cnt,
        timestamp,   # time
        0,
        0,
        0,           # empty[3]
    )


def write_dat(path, entries):
    """写出微软输入法的用户自定义短语 .dat。"""
    records = []
    offsets = []
    offset = 0
    for entry in entries:
        rank = entry["rank"]
        if not 1 <= rank <= 255:
            raise SystemExit(
                "错误：rank=%d 超出 .dat 能保存的范围 1-255；"
                "请调小 --start-rank，或减少同一编码的重复条目。" % rank
            )
        record = dat_record(entry["py"], entry["str"], rank)
        offsets.append(offset)
        offset += len(record)
        records.append(record)

    offset_bytes = b"".join(struct.pack("<I", value) for value in offsets)
    data_start = DAT_HEADER_SIZE + len(offset_bytes)
    header = dat_header(
        DAT_HEADER_SIZE, data_start, data_start + offset, len(records), int(time.time())
    )

    with open(path, "wb") as fh:
        fh.write(header)
        fh.write(offset_bytes)
        for record in records:
            fh.write(record)


def write_json(path, entries):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(entries, fh, ensure_ascii=False, indent=4)
        fh.write("\n")


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass

    args = build_parser().parse_args(argv)
    if args.start_rank < 1:
        raise SystemExit("错误：--start-rank 必须大于 0。")

    dict_path = resolve_dict(args.dict)
    table, bad_codes = load_table(dict_path)
    if bad_codes:
        eprint("警告：码表中有 %d 条编码含非法字母（z 等），已忽略。" % bad_codes)

    if detect_format(args.input, args.format) == "csv":
        pairs, parse_problems = parse_csv(
            args.input, args.encoding, args.emoji_col, args.text_col
        )
    else:
        pairs, parse_problems = parse_input(
            args.input, args.encoding, normalize_sep(args.sep), swap=args.swap
        )
    if not pairs and not parse_problems:
        raise SystemExit("错误：输入文件里没有可用的数据行。")

    pairs = expand_meanings(pairs, args.meaning_sep)

    entries = []
    rank_cursor = {}          # 编码 -> 已用次数
    seen_pairs = set()        # 完全相同（emoji, 含义）的组合
    encode_errors = []        # 编码失败的条目
    duplicate_rows = 0
    stripped_rows = 0

    if args.strip_non_cjk:
        cleaned_pairs = []
        for lineno, emoji, meanings in pairs:
            kept = []
            for meaning in meanings:
                cleaned = "".join(char for char in meaning if is_cjk(char))
                if cleaned != meaning:
                    stripped_rows += 1
                if not cleaned:
                    encode_errors.append((lineno, emoji, meaning, "去掉非汉字字符后为空"))
                    continue
                kept.append(cleaned)
            if kept:
                cleaned_pairs.append((lineno, emoji, kept))
        pairs = cleaned_pairs

    for lineno, emoji, meanings in pairs:
        for text in meanings:
            # ① 先判断是否属于「直接编码」：纯 ASCII、a-z、1-4 个字符
            direct = not args.no_literal_code and is_direct_code(text)
            effective = text.lower() if direct else text

            # ② 用统一形式去重：omeg / OMEG 视为同一条
            pair_key = (emoji, effective)
            if pair_key in seen_pairs:
                duplicate_rows += 1
                continue
            seen_pairs.add(pair_key)

            # ③ 直接编码不再查表；中文含义走五笔编码
            if direct:
                code, missing = effective, None
            else:
                code, missing = wubi_code(text, table)

            if code is None:
                if not args.no_literal_code and looks_like_long_code(text):
                    reason = (
                        "自定义编码 %r 超过 %d 字符上限，请缩短到 4 字符以内"
                        % (text, MAX_DIRECT_CODE_LEN)
                    )
                elif not missing:
                    reason = "含义为空"
                elif not is_cjk(missing):
                    reason = (
                        "包含非汉字字符 %r（如需作为自定义编码，请只使用 a-z 字母"
                        "且不超过 %d 字符）" % (missing, MAX_DIRECT_CODE_LEN)
                    )
                else:
                    reason = "码表中缺少汉字 %r" % missing
                encode_errors.append((lineno, emoji, text, reason))
                continue

            rank = args.start_rank + rank_cursor.get(code, 0)
            rank_cursor[code] = rank_cursor.get(code, 0) + 1
            entries.append({"py": code, "str": emoji, "rank": rank})

    # ---------------------------- 报告问题 ---------------------------- #
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

    # ---------------------------- 写出结果 ---------------------------- #
    out_path = os.path.abspath(os.path.expanduser(args.output))
    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.isdir(out_dir):
        raise SystemExit("错误：输出目录不存在 %s" % out_dir)

    if out_path.lower().endswith(".json"):
        write_json(out_path, entries)
        eprint("已生成 JSON：%s" % out_path)
    else:
        write_dat(out_path, entries)
        eprint("已生成 DAT：%s" % out_path)

    if args.json:
        json_path = os.path.abspath(os.path.expanduser(args.json))
        write_json(json_path, entries)
        eprint("已生成 JSON：%s" % json_path)

    # ---------------------------- 统计信息 ---------------------------- #
    pushed = sum(1 for e in entries if e["rank"] > args.start_rank)
    max_rank = max(e["rank"] for e in entries)
    eprint("  条目：%d" % len(entries))
    eprint("  编码顺推：%d 条（最大候选位置 %d）" % (pushed, max_rank))
    if stripped_rows:
        eprint("  去掉非汉字字符：%d 条" % stripped_rows)
    if duplicate_rows:
        eprint("  忽略完全重复的「emoji + 含义」：%d 条" % duplicate_rows)
    if max_rank > 9:
        eprint("  提示：有候选位置超过 9，输入法里可能需要翻页才能看到。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
