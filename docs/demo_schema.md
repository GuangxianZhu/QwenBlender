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
| `spin` | 一直转 | part, speed（度/秒） | axis, pivot, delay, hollow |
| `turn` | 转过一个角度 | part, by（度） | axis, pivot, time, loop, pause, delay, ease |
| `move` | 平移 | part, by（[dx,dy,dz] 毫米） | time, loop, pause, delay, ease |
| `screw` | 边转边走（螺纹） | part, turns（圈数）, pitch（螺距） | axis, pivot, time, loop, pause, delay, ease |
| `blink` | 闪烁提示 | part | time, delay |

- `axis`：`"x"` `"y"` `"z"`，可以带负号（`"-z"`），或者 `[x,y,z]`。默认 `"z"`。转动方向按右手定则。
  screw 的前进方向就是 axis 的方向。
- `pivot`：转动中心，写 `[x,y,z]`，或者写一个零件名（用那个零件的中心，一般写轴或销子）。不写就绕零件自己的原点转。
- `hollow`：`true` 表示这个零件本来就是空心的、轴线上不需要有轴（不写的话，转轴上是空的会被检查报出来）。
- `time`：一次动作的秒数（默认 2）。`loop`：`once` 只做一次，`repeat` 重复，`pingpong` 来回。
  `pause`：每次停顿的秒数。`delay`：开始前等几秒。`ease`：`smooth` 或 `linear`。
- 一个零件可以有多条动画，按顺序叠加。

## 连杆机构

曲柄滑块和四连杆不用自己算，写一条动画，页面按几何关系解出每个零件的位置。
铰点填模型里**初始姿态**下的位置：直接写销子或轴的零件名（用它的中心，推荐），或者写 `[x,y,z]`。机构在垂直于 `axis` 的平面里运动。
model.py 里用 `pin_joint` 做铰点、用 `shaft_through` 做固定转轴，构建报告会列出它们的名字。

曲柄滑块（曲柄转，滑块沿直线走）：

```json
{"type": "crank_slider", "id": "m",
 "crank": "Crank", "rod": "Rod", "slider": ["Piston", "PistonPin"],
 "center": [0, 0, 0], "crank_pin": [15, 0, 0], "slider_pin": "PistonPin",
 "axis": "y", "slide": "z", "speed": "rpm * 6"}
```

- `center` 曲柄的转动中心；`crank_pin` 曲柄和连杆的铰点；`slider_pin` 连杆和滑块的铰点。
- `axis` 转动轴的方向（默认 `"y"`）；`slide` 滑块移动的方向（默认 `"z"`）。
- 连杆长度 = crank_pin 到 slider_pin 的距离，要大于曲柄半径，不然转不了整圈（校验会指出来）。

四连杆（曲柄 AB、连杆 BC、摇杆 DC，A 和 D 固定在机架上）：

```json
{"type": "four_bar", "id": "f",
 "crank": ["Crank", "PinB"], "coupler": "Coupler", "rocker": ["Rocker", "PinC"],
 "a": "ShaftA", "b": "PinB", "c": "PinC", "d": "ShaftD",
 "axis": "y", "speed": "rpm * 6"}
```

两种都适用的：

- `crank` `rod` `slider` `coupler` `rocker` 可以写一个零件名，也可以写一组（跟着一起动的零件，比如活塞和活塞销）。
  销子要写进它跟着动的那一组；固定在机架上的转轴不用写进任何一组。
- `speed`（度/秒，一直转）和 `angle`（直接给角度，度，一般写一个滑条的 id）二选一。
  曲柄转不了整圈的机构（双摇杆）只能用 `angle`，滑条范围取它能到的角度。
- 写了 `id` 就多出几个可以放进读数的变量：`<id>_angle` 曲柄转角（度），`<id>_pos` 滑块位移（毫米，只有曲柄滑块有），
  `<id>_rocker` 摇杆摆角（度，只有四连杆有）。例：`{"label": "活塞位置", "expr": "m_pos", "unit": "mm"}`。
- 和曲柄同轴一起转的零件（飞轮、皮带轮）另外加一条 `spin`，speed 写成一样的。

## 表达式

speed、by、turns、pitch、readouts 的 expr 可以写数字，也可以写带引号的算式：
`"rpm * 6"`、`"-rpm * 6 * 20 / 40"`、`"10 * sin(t * 2)"`。
能用的名字：params 里的 id、`t`（这一步已经过了多少秒）、`sin cos tan abs min max sqrt pow floor round PI`。

## 常用换算

- 转速 n 转/分 → speed = n × 6 度/秒。
- 两个啮合的齿轮转向相反：从动轮 speed = −主动轮 speed × 主动齿数 / 从动齿数。
- 螺纹：走的距离 = 圈数 × 螺距。
- 皮带：两个轮转向相同，从动轮 speed = 主动轮 speed × 主动轮直径 / 从动轮直径。
- 蜗轮蜗杆：蜗轮 speed = ±蜗杆 speed × 头数 / 蜗轮齿数。正负号看蜗轮在蜗杆哪一侧，先写一个，check_page 报「动起来以后穿模」就取负。
- 行星轮系（内齿圈固定）：行星架 speed = 太阳轮 speed × 太阳轮齿数 / (太阳轮齿数 + 内齿圈齿数)；
  行星轮写两条 spin：先一条绕太阳轮中心公转（`pivot` 写太阳轮中心，speed 同行星架），再一条绕自己转。

## 运动检查

check_page 会把每一步的动画摆到几个时刻（`angle` 由滑条给的连杆会把滑条从最小扫到最大），检查：

- 动起来以后有没有互相穿模。常见原因——齿轮、蜗轮蜗杆：转向反了，或者速比和齿数对不上；
  连杆：铰点和模型里的真实位置不一样；运动的零件路上有别的零件挡着，回 model.py 给它开槽或者挪开。
- 连杆的铰点上有没有销子把两组零件连着；转动零件的转轴上有没有轴。缺了就回 model.py 用 `pin_joint` / `shaft_through` 补。
- 静止时贴着的两个零件（刮片和玻璃、滑块和导轨），动起来以后还贴不贴。完全离开算问题，探出去一部分给提醒。
- 网页文字、读数、零件说明里写的摆角和行程，和算出来的对不对得上。
- 没有写 highlight 的步骤里，在动的零件从这一步的视角看是不是被不透明的零件挡住了。
  挡住了就把挡它的零件写进这一步的 `ghost`，或者换视角，或者用 `section`。

它同时返回「运动范围」：摇杆的摆角、滑块的行程、每个运动零件扫过的范围。文字里的数字用这里的数；
要给运动的零件配一块玻璃、一条导轨、一个罩子，大小和位置按扫过的范围定。

## 写法建议

- 4~7 步。第一步看整体，然后拆开认零件，再讲原理，最后总结。
- 每一步都换一个合适的视角；讲内部结构时用 section 或 ghost。
- 讲解文字写给第一次见这个东西的人：先说看到什么，再说为什么。数字要和模型一致。
