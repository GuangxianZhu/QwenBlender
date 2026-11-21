# demo.json 怎么写

demo.json 决定网页演示的全部内容。页面骨架是固定的（讲解 / 零件 / 爆炸 / 剖切四个标签），你只填这份配置。
坐标一律用建模坐标：毫米，Z 朝上。零件名必须和 model.py 里 part() 登记的英文名一致（用 list_parts 查）。

```json
{
  "title": "标题",
  "subtitle": "一句话副标题",
  "params": [
    {"id": "rpm", "label": "转速", "min": 0, "max": 120, "value": 30, "step": 1, "unit": "转/分"}
  ],
  "readouts": [
    {"label": "从动轮转速", "expr": "rpm * 20 / 40", "unit": "转/分", "digits": 1}
  ],
  "steps": [
    {
      "title": "1 整体",
      "text": "讲解文字。**加粗**，\n 换行。每步 2~4 句。",
      "view": "iso",
      "explode": 0,
      "highlight": ["零件名"],
      "ghost": ["零件名"],
      "hide": ["零件名"],
      "section": {"axis": "x", "pos": 0.5},
      "labels": [{"part": "零件名"}, {"at": [0, 0, 30], "text": "这里是进水口"}],
      "anim": [
        {"part": "GearA", "type": "spin", "axis": "z", "speed": "rpm * 6"}
      ],
      "readouts": []
    }
  ]
}
```

## 字段

- `view`：视角。写名字 `front`（从 -Y 看）`back` `right`（从 +X 看）`left` `top` `bottom` `iso` `iso2`，
  或者 `{"az": 30, "el": 15, "zoom": 1.2, "focus": "零件名"}`。az=0 是正前方，az=90 是右侧；el 是仰角；
  focus 让镜头对准某个零件。
- `explode`：0 合起来，1 完全拆开。拆开的方向来自 part(..., explode=(dx,dy,dz))，没写就自动往外推。
- `highlight`：高亮这些零件，其余变淡。`ghost`：这些零件半透明。`hide`：隐藏。
- `section`：剖切。axis 是 x / y / z，pos 是 0~1（0.5 是正中间），坐标大的那一半被切掉。
- `labels`：标签。`{"part": "零件名"}` 贴在零件上显示中文名，也可以加 `"text"` 改文字；`{"at": [x,y,z], "text": "…"}` 贴在一个点上。
- `params`：滑条。id 是英文名，可以在表达式里用。只有用到它的步骤才显示滑条。
- `readouts`：读数。expr 是表达式。写在最外层就每步都显示，写在某一步里就只在那一步显示。

## 动画 anim

| type | 作用 | 必填 | 可选 |
|---|---|---|---|
| `spin` | 一直转 | part, speed（度/秒） | axis, pivot, delay |
| `turn` | 转过一个角度 | part, by（度） | axis, pivot, time, loop, pause, delay, ease |
| `move` | 平移 | part, by（[dx,dy,dz] 毫米） | time, loop, pause, delay, ease |
| `screw` | 边转边走（螺纹） | part, turns（圈数）, pitch（螺距） | axis, pivot, time, loop, pause, delay, ease |
| `blink` | 闪烁提示 | part | time, delay |

- `axis`：`"x"` `"y"` `"z"`，可以带负号（`"-z"`），或者 `[x,y,z]`。默认 `"z"`。转动方向按右手定则。
  screw 的前进方向就是 axis 的方向。
- `pivot`：转动中心 `[x,y,z]`。不写就绕零件自己的原点转。
- `time`：一次动作的秒数（默认 2）。`loop`：`once` 只做一次，`repeat` 重复，`pingpong` 来回。
  `pause`：每次停顿的秒数。`delay`：开始前等几秒。`ease`：`smooth` 或 `linear`。
- 一个零件可以有多条动画，按顺序叠加。

## 表达式

speed、by、turns、pitch、readouts 的 expr 可以写数字，也可以写带引号的算式：
`"rpm * 6"`、`"-rpm * 6 * 20 / 40"`、`"10 * sin(t * 2)"`。
能用的名字：params 里的 id、`t`（这一步已经过了多少秒）、`sin cos tan abs min max sqrt pow floor round PI`。

## 常用换算

- 转速 n 转/分 → speed = n × 6 度/秒。
- 两个啮合的齿轮转向相反：从动轮 speed = −主动轮 speed × 主动齿数 / 从动齿数。
- 螺纹：走的距离 = 圈数 × 螺距。

## 写法建议

- 4~7 步。第一步看整体，然后拆开认零件，再讲原理，最后总结。
- 每一步都换一个合适的视角；讲内部结构时用 section 或 ghost。
- 讲解文字写给第一次见这个东西的人：先说看到什么，再说为什么。数字要和模型一致。
