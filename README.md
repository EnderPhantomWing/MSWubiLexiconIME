# MSWubiLexiconIME（五笔自定义短语词库生成器 TSV → DAT）

一条命令把「目标字符 + 中文含义 / 直接编码」对照表转成微软输入法的用户自定义短语 `.dat`。

你可以在**release**里下载转换好的dat  
目标字符不限于 emoji——可以是数学符号（`Ω`、`→`、`∑`）、生僻字（`䊘、𪩘 等等`）、甚至常用汉字词语 短语，
只要你想给它绑定五笔编码或直接编码，都能写进同一份对照表。

```bash
python wubi_converter.py input.tsv -o wubi_custom_lexicon.dat  

python wubi_converter.py input.tsv --strict --output wubi_custom_lexicon.dat --json wubi_custom_lexicon.json
```

输入：

```
😀	咧嘴	嘿嘿
😃	张嘴	哈哈
```

一个目标字符可以对应**多个含义**（Tab 分隔），每个含义单独计算五笔编码、单独生成一条记录，
所以 `.dat` 里同一个字符出现多次是正常的。

除自动计算五笔编码外，含义列里写**纯 ASCII 键位**（`a`–`y`，1–4 个字符）时，
会被当作**直接编码**原样写入，不做编码计算。例如：

```
䊘	omeg
Ω	omeg	欧姆    ohm
```

生成后，输入 `omeg` 会同时出现「䊘」和「Ω」，「欧姆」按五笔码输出「Ω」，`ohm` 直接指向「Ω」。
用 `--no-literal-code` 可以关闭这个识别，让所有内容都按中文含义计算。

## 文件说明

| 文件 | 说明 |
| --- | --- |
| `wubi_converter.py` | 主程序，无第三方依赖，Python 3.8+ |
| `wubi_rime2tsv.py` | 附加程序，无第三方依赖，转换rime.dict.yaml到tsv，Python 3.8+ |
| `wubi86_words.tsv` | 内置五笔 86 单字全码表（20,979 字） |
| `wubi86_fullcode.tsv` | 内置rime五笔 86 单字全码表（70,641 字） |
| `input.tsv` | 仓库词库 |

## 快速开始

```bash
# 直接生成 .dat
python wubi_converter.py input.tsv -o wubi_custom_lexicon.dat

# 顺便保留中间 JSON
python wubi_converter.py input.tsv -o wubi_custom_lexicon.dat --json wubi_custom_lexicon.json

# 带表头的 CSV
python wubi_converter.py emoji含义清单.csv -o wubi_custom_lexicon.dat --strip-non-cjk

# 直接指定编码（纯 ASCII 键位原样写入）
python wubi_converter.py symbol.tsv -o symbol_wubi.dat
```

输出名以 `.json` 结尾时只写 JSON（不生成 `.dat`）：

```bash
python wubi_converter.py input.tsv -o wubi_custom_lexicon.json
```

## 输入格式

### 文本 / TSV

每行一条，**目标字符**后面用 **Tab** 分隔一个或多个含义：

```
# 以 # 开头的行为注释，空行会被忽略
😀	咧嘴	嘿嘿
😃	张嘴	哈哈
Ω	欧姆
→	箭头	向右
```

目标字符后面的每一列都是一个独立含义，都会各自编码并写入。也支持空格分隔，
但含义内部不能有空格（有空格时请用 Tab）。

多个含义挤在同一个单元格里时，用 `--meaning-sep` 指定分隔符：

```bash
python wubi_converter.py words.tsv --meaning-sep '、'
```

### 直接编码

当某一列是纯 ASCII 字母（`a`–`y`，1–4 个字符）时，程序会把它当作**直接编码**，
原样写进 `.dat`，不再经过五笔编码计算：

```
䊘	omeg
Ω	omeg	欧米伽	ohm
⌛	hourglass	时
```

> 不推荐将英语单词直接写入tsv！

- `omeg`、`ohm`、`hourglass` 属于直接编码（小写化后写入，`OMEG` 与 `omeg` 视为同一条）；
- `欧米伽`、`时` 是中文，仍按五笔规则计算；
- 同一个字符对应的不同列（直接编码、中文含义）会**分别**生成记录；
- 长度超过 4、含 `z`、或含非 ASCII 字符的内容**不会**被识别为直接编码；
- `--strip-non-cjk` 输出纯汉字后，不再满足直接编码条件，仍走编码流程。

需要强制所有列都按中文含义计算（例如含义本身就是英文 `good`）时，加 `--no-literal-code`。

### CSV

需要表头。默认按列名自动查找：

- 字符列：名字里含 `Emoji` / `表情`；
- 含义列：名字里含 `含义` / `中文` / `meaning` / `text`。

找不到时退回第 1、2 列；也可以用 `--emoji-col`、`--text-col` 指定列名或从 1 开始的序号
（`--emoji-col` 指向的是「目标字符」列，不限 emoji）。单元格里有多含义时同样可以用
`--meaning-sep '、'` 拆分。

含义列里的「男人: 红发」「日文的“申请”按钮」这类写法，加 `--strip-non-cjk`
会自动去掉空格、标点和字母，只保留汉字再编码。

## 五笔编码规则

程序按五笔 86 的词组规则，用单字全码拼出词组编码：

| 词长 | 规则 | 示例 |
| --- | --- | --- |
| 1 字 | 取该字全码 | 爱 → `epdc` |
| 2 字 | 各取前两码 | 咧嘴 → `kg` + `kh` = `kgkh` |
| 3 字 | 前两字各取首码 + 第三字前两码 | 计算机 → `y` + `t` + `sm` = `ytsm` |
| 4 字及以上 | 前三字各取首码 + 末字首码 | 中华人民共和国 → `kwwl` |

验证过的例子：你好 `wqvb`、我们 `trwu`、五笔字型 `gtpg`、微笑 `tmtt`。

### 直接编码 vs 自动编码

含义列按以下顺序判定：

1. 若开启了 `--strip-non-cjk`，先去掉非汉字字符；
2. 结果若是纯 ASCII 字母（`a`–`y`，1–4 个字符），**视为直接编码**，原样写入；
3. 否则按上表规则计算五笔编码。

第 2 步可以用 `--no-literal-code` 关闭。

## 候选位置与重复

`rank` 默认从 **3** 开始。同一个五笔编码对应多个目标字符时依次顺推：

```
😀  咧嘴  ->  kgkh, rank 3
😄  咧嘴  ->  kgkh, rank 4
```

同一字符的多个含义一般编码不同，各自都是 3；如果不同含义撞了同一个编码，
同样按 3、4、5……顺推。完全相同的「字符 + 含义」组合会被去重。

编码相同的直接编码与自动编码（例如 `omeg` 与某中文词算出来的 `omeg`）会合并计算 rank，
从 `--start-rank` 起依次顺推，不会互相覆盖。

## 输出的 .dat 结构

按项目里 `wubi_converter.py` 的格式生成：

- 头部 64 字节：`mschxudp` + 版本 + offsetStart(0x40) + dataStart + fileLen + itemCnt + 时间戳；
- 偏移表：每条记录 4 字节；
- 记录：16 字节头 + UTF-16LE 的按键 + 2 字节结尾 + UTF-16LE 的字符串 + 2 字节结尾。

`rank` 在记录里是单字节，所以必须在 1–255 之间；超出时程序会直接报错。
我用同样的数据把本程序和 `wubi_converter.py` 生成的文件做过逐字节对比（固定时间戳），
结果完全一致；生成的 `wubi_custom_lexicon.dat` 也逐条校验过按键、目标字符、rank 都能正确读回。

## 常用参数

| 参数 | 说明 |
| --- | --- |
| `-o, --output` | 输出文件，默认 `wubi_custom_lexicon.dat`；以 `.json` 结尾则只写 JSON |
| `--json` | 额外保存一份中间 JSON 到指定路径 |
| `--dict` | 指定其他码表（格式：`汉字<TAB>编码`），会完全替代内置码表 |
| `--start-rank` | 起始候选位置，默认 5 |
| `--meaning-sep` | 一个单元格内多个含义的分隔符（如 `、`），默认不拆分 |
| `--format` | `auto`（默认，`.csv` 走 CSV）/ `text` / `csv` |
| `--sep` | 文本模式下使用：`auto` / `tab` / `comma` / 直接写分隔符 |
| `--emoji-col`、`--text-col` | CSV 模式下目标字符列 / 含义列的列名或从 1 开始的序号 |
| `--strip-non-cjk` | 编码前去掉空格、标点、字母等非汉字字符 |
| `--no-literal-code` | 关闭「纯 ASCII 字母（a–y，1–4 个字符）作为直接编码」的识别 |
| `--swap` | 文本模式下输入是「含义 → 目标字符」时使用 |
| `--strict` | 有任何一条转换失败就退出，不写文件 |

无法编码的含义（缺字、混有中英文的整段等）会在 stderr 列出行号和原因，同一行的其它含义照常输出。
需要支持更多生僻字时，把自己的码表用 `--dict` 传进来即可；纯 ASCII 键位（`a`–`y`，1–4 个字符）
则会被识别为直接编码，不会报错。

## 码表来源

`wubi86.tsv` 由 npm 包 [`wubi-code-data`](https://www.npmjs.com/package/wubi-code-data)
的「五笔86」数据整理而来（ISC License），覆盖 20,976 个汉字。
如果更信任 Rime 的码表，可以把
[`rime-wubi`](https://github.com/rime/rime-wubi) 的 `wubi86.dict.yaml`
转成 `汉字<TAB>编码` 的文本后用 `--dict` 指定。

## 导入输入法

微软拼音：右键任务栏输入法图标 →「用户自定义短语」→ 导入，选择生成的 `.dat`。

> 注意：该项目（MSWubiLexiconIME / `wubi_converter.py`）面向的是**微软拼音**；
> 微软五笔是否接受同样的 `.dat` 需要实测。导入前建议先导出备份现有的自定义短语。

## 鸣谢

[Github@gxgzf](https://github.com/gxgzf) 提供的思路及初始文件  
参考项目: https://github.com/Nativu5/MSPinyinEmoji