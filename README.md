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
