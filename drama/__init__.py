"""互动短剧《望潮楼》的剧本依据追踪与交片评估工具。

模块分工：

- model   资料表的不可变数据模型与索引
- loader  从 JSON 读取并校验轮次稿
- acts    台词行为分类（许诺、交付、转述、改口……）
- state   沿路线累积的认知/持有状态与依据
- graph   分支图遍历、回头路剪枝、实际选择顺序追踪
- review  依据核对、共用场景兼容性、编剧确认单
- release 授权语言/音轨就绪度/按钮可播放性交片评估
- cli     命令行入口
"""

__all__ = [
    "model",
    "loader",
    "acts",
    "state",
    "graph",
    "review",
    "release",
]
