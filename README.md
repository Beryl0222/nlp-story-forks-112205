# 互动短剧

《望潮楼》是练习用的虚构互动短剧。对白、角色和交付记录用于编剧与后期之间的文字交接。

## 资料格式

数据位于 `data/records.json`，以 UTF-8 保存。各表的记录以本表内的 `id` 或 `seq` 识别。原话保留提交时的文字。

脚本节点可以被多次访问。入口为 S1，边上的 option 是观众选择，trigger 是编剧的条件原话。对白 variant 不为空时指同节点同 line_no 下的备选台词。音轨 ready 表示已经具备发行用素材，不赋予剧本有效性。目标片单由市场、语言、入口和允许选项范围组成。

- `roles` 保存人物和剧本中的称呼。 字段为 `id`、`name`、`aliases`。
- `scenes` 保存场景及作者拟安排的行动。 字段为 `id`、`place`、`narration`。
- `edges` 保存可见选项和有向连接。 字段为 `id`、`origin`、`target`、`option`、`trigger`。
- `dialogue` 保存分场原稿。speaker、listeners 是剧本登记角色。quote 是逐字稿。 字段为 `id`、`scene`、`line_no`、`speaker`、`listeners`、`variant`、`quote`。
- `tracks` 保存语言、台词与音轨的制作登记。 字段为 `id`、`line`、`language`、`ready`。
- `releases` 保存市场片单和计划实际提供的主要分支。 字段为 `id`、`entry`、`languages`、`rights`、`options`。

## 查看资料与自检

使用 Python 3.11.2 自带的标准库读取资料并验证字段和引用。

```sh
python3 -m json.tool data/records.json
python3 -m unittest discover -s tests -v
```

## 依据追踪工具 `drama`

`drama` 包在不改原始稿的前提下，把台词行为、依据等级与分支图连起来，回答三类问题：
谁知道谁说过什么、某条选择顺序在哪一幕失去承诺依据、后期哪些路线还能交片。

### 依据分层

每条台词先做行为分类（许诺、接受、亲自交付、转述、听错改口、行动主张、
保管预设、收回、拒绝、中性），再标注依据等级，三者全程不混用：

- `direct`：当事人在场原话，可作为承诺或交付的直接依据；
- `hearsay`：转述，只证明“有人这样说过”，不证明被转述的事实；
- `retracted`：听错后的改口，相关错误复述立即失效。

附条件许诺（L1）永远不等于交付；只有当面交付（L3）才建立持有关系。
回到同一房间不清空历史，收回与反向承诺只追加事件并改变当前效力。

### 常用命令

```sh
# 字段/引用自检 + 审查计数
python3 -m drama check

# 遍历分支：路线、回头路剪枝、触发不成立的死边
python3 -m drama walk

# 按观众实际选择顺序追踪，定位依据断点（退出码 2 表示被阻断）
python3 -m drama trace E2 E4 E6
python3 -m drama trace E1 E3 E6 --variant S6:1:L8
# 同一房间第二次到访选不同台词：@ 后是到访次序，通用键只作用于第一次
python3 -m drama trace E1 E3 E8 E9 E10 E7 --variant S2:2:L10@2

# 查看某选择顺序下各角色掌握的事实与依据
python3 -m drama knowledge E2 E5 E7

# 依据审查与共用场景兼容性矩阵（有阻断项时退出码 1）
python3 -m drama review

# 导出带上下文签名的编剧确认单；确认只能解决读法，不能补出交付事实
python3 -m drama questions --write confirmations.json
python3 -m drama review --confirmations confirmations.json

# 按片单评估授权语言、音轨就绪度与按钮一致性
python3 -m drama release
```

所有命令都支持 `--json`，并可用 `-f a.json b.json` 接入多轮稿，后一轮可
替换同 id 台词/边、新增记录；角色与场景身份冲突会直接报错。

### 循环剪枝与确认作用域

分支允许回头路。遍历按“判断相关状态签名”剪除沿本路线回到等价状态的环，
重复点返回不会每次生成新待审路线，完整时间线仍保留可追溯。待确认问题的
键含具体台词与分支上下文签名，只在上下文真正相同的出现位置可复用，
对不上的确认键会被拒绝。

### 交片规则

- 只按 `rights` 授权语言判定可交付性，`languages` 中未授权的语言单独标注；
- 音轨 `ready` 只表示素材齐备，不赋予剧本有效性，依据断裂照样阻断；
- 某路线依赖的新台词未录好时，只阻断该路线，已制片路线继续可交付；
- 依据断裂的选项按钮必须关闭；仅待重录但依据成立的按钮保留并标明补录义务，
  不会留下能点进空片的入口。

