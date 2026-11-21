# QwenBlender

给本地 Qwen（Ollama）配的一套工具，让它能自己用 Blender 建模，再做出带讲解的网页演示。

思路：模型少写长代码，多调现成工具；每一步都有「尺子」和「眼睛」给它反馈。

```
任务描述 ─→ Qwen ─→ 写 model.py ─→ Blender 运行 ─→ 尺寸 / 穿模 / 悬空 / 破面 + 四视图 ─┐
              ↑                                                                    │
              └────────────── 看数字和图，自己改 ←──────────────────────────────────┘
            模型没问题后 ─→ 写 demo.json ─→ 生成网页 ─→ 浏览器检查 + 截图 ─→ 自己改 ─→ 完成
```

## 怎么用

双击 `启动.bat`。它会：

1. `git pull` 拉 main 的更新；
2. 准备 Python 环境（有 uv 用 uv，没有就用系统 Python）；
3. 打开菜单。

菜单里选「新任务」，输入一句话，比如：

> 做一个 M8 螺栓把两块 6 mm 的板夹在一起，带垫圈和螺母，讲清楚它为什么能夹紧

做完会自动打开网页。结果在 `jobs/时间_任务名/out/`：

| 文件 | 内容 |
|---|---|
| `index.html` | 网页演示，单文件，离线能开 |
| `model.glb` | 模型（单位是米，零件名和说明都在里面） |
| `model.blend` | Blender 工程 |
| `sheet.png` | 四视图 |

想先看看能不能跑通，双击 `试跑.bat`：不用输入任何东西，它先自检，再让 Qwen 把同一个任务（C 形夹）做两遍：一遍没有工具、只回答一次，一遍用全套工具。全过程记在 `jobs/trial_log.txt`，对比结果在 `jobs/compare_时间/compare.md`。想换题目，把任务写进 `jobs/trial_task.txt` 再双击；多道题用单独一行 `---` 隔开。

菜单里的「自检」不需要 Qwen：把范例跑一遍，确认 Blender 和浏览器这条链路在这台电脑上是通的。第一次用先跑它。

需要：Ollama（里面有带 tools 和 vision 能力的 qwen 模型）、Blender 4.2 以上、Edge 或 Chrome。

## 给 Qwen 的工具

| 工具 | 作用 |
|---|---|
| `submit_plan` | 先列零件清单，后面拿它核对有没有漏做、尺寸差多少 |
| `write_file` / `edit_file` / `read_file` | 写和改 model.py、demo.json、custom.js。语法错、JSON 错当场拦住 |
| `build_model` | 运行 model.py：报错带行号；每个零件的尺寸、位置、接触了谁；穿模、悬空、破面；一张四视图 |
| `look` | 换个角度看，可以对准某个零件放大 |
| `section` | 剖开看内部，每个零件的切面一种颜色 |
| `measure` | 量一个零件，或两个零件之间的间隙、穿入深度、中心距 |
| `list_parts` | 列出零件名，写网页配置前用 |
| `build_page` | 校验 demo.json（零件名、动画字段、表达式），生成网页 |
| `check_page` | 浏览器打开：控制台报错、每一步能不能跑、动画动没动、手机上溢不溢出，返回截图；再把每一步的动画摆到几个时刻，查零件动起来以后会不会互相穿模（转向反了、速比不对、连杆撞到别的零件） |
| `lib_help` | 查零件库函数的写法 |
| `search_examples` | 搜范例代码 |
| `search_bpy` | 查本机 Blender 版本的 API |
| `finish` | 还有没修的问题时会被拒绝 |

## 零件库 qblib

`blender/qblib.py`，model.py 里 `from qblib import *` 就能用。单位毫米，Z 朝上。

- 基本体：`box` `rounded_box` `cylinder` `cone` `tube` `sphere` `torus` `prism` `extrude` `revolve` `pipe` `spring`
- 机械件：`hex_bolt` `socket_screw` `nut` `screw_on` `washer` `threaded_rod` `bearing` `flange` `l_bracket` `bent_plate` `link_bar`
- 传动件：`spur_gear` `helical_gear` `ring_gear` `mesh` `worm` `worm_wheel` `mesh_worm` `pulley` `belt`
- 加工：`union` `cut` `intersect` `hole` `holes_circle` `bevel` `chamfer`
- 摆放：`at` `move` `rot` `rot_about` `stack` `beside` `center_on` `copy` `mirror_copy` `array_circular` `array_linear` `join`
- 信息：`part` `mat` `color` `bbox` `allow_overlap` `allow_float`

螺栓和螺母带真螺纹，`screw_on(螺母, 螺栓, grip=夹紧厚度)` 会把牙对上。
齿轮用 `mesh(g, ref, angle)` 摆位置和对齿（直齿、斜齿、内齿圈），蜗轮蜗杆用 `mesh_worm`，皮带用 `belt(轮1, 轮2)` 自动绕上去。

完整说明：`python -m qb help`，或者 `python -m qb help hex_bolt`。

## 网页演示

页面骨架是固定的（`web/template.html` + `web/viewer.js`）：讲解、零件、爆炸、剖切四个标签，手机和电脑都能用。
Qwen 只写一份 `demo.json`：讲解步骤、视角、高亮、标签、动画、滑条、读数。动画有转动、平移、螺旋，还有曲柄滑块和四连杆（页面自己解机构位置）。写法见 [docs/demo_schema.md](docs/demo_schema.md)。

demo.json 做不到的效果（按公式移动零件、画箭头）再写 `custom.js`，接口见 [docs/custom_api.md](docs/custom_api.md)。

## 范例

`examples/` 里有四个完整任务，也是 `search_examples` 的检索内容：

| 目录 | 内容 |
|---|---|
| `bolt_joint` | 螺栓连接：真螺纹、剖切、拧螺母的动画和圈数滑条 |
| `gear_pair` | 齿轮减速：渐开线齿轮、转速滑条、联动读数 |
| `pipe_flange` | 法兰连接：弯管、圆周螺栓，custom.js 画流动箭头和流速 |
| `crank_slider` | 曲柄滑块：连杆、活塞、缸筒，机构动画和活塞位置读数 |

`examples/snippets/` 是单项写法：带孔的板、圆周阵列、轴和轴承对位、自定义轮廓、车削体、布尔挖槽、镜像阵列、齿轮对齿、蜗轮蜗杆、皮带传动、钣金、连杆、直接用 bmesh。

## 配置

可选。把 `config.example.json` 复制成 `config.json` 再改：

| 项 | 默认 | 说明 |
|---|---|---|
| `model` | `auto` | 自动在 Ollama 里找 qwen，优先 q8。也可以写死，如 `qwen3.8:27b-q8_0` |
| `num_ctx` | 32768 | 上下文长度 |
| `think` | true | 是否开思考 |
| `max_steps` | 80 | 最多跑多少轮 |
| `blender` | `auto` | 自动找 blender.exe；找不到就写完整路径 |
| `render_device` | `cpu` | 四视图用 CPU 还是 `gpu` 渲染 |
| `render_res` / `render_samples` | 512 / 16 | 四视图每格的像素和采样数 |
| `browser` | `auto` | 先找 Edge，再找 Chrome；也可以写 exe 路径 |

## 命令行

每个工具也能单独运行，不经过 Qwen。其他编程助手可以直接调：

```
python -m qb build   <任务目录>           运行 model.py，打印报告，出四视图
python -m qb look    <任务目录> 30 20 Nut
python -m qb section <任务目录> x 0
python -m qb measure <任务目录> Bolt Nut
python -m qb page    <任务目录>           校验 demo.json，生成网页
python -m qb check   <任务目录>           浏览器检查
python -m qb help [函数名|demo|custom]
python -m qb new "任务描述"               让 Qwen 做（加 --no-page 只要模型）
python -m qb fix <任务目录> "修改意见"
```

任务目录就是一个放着 `model.py`（和 `demo.json`）的文件夹。

## 测试

```
python tests/test_lib.py          零件库：每个函数的结果都是封闭实体；尺寸、穿模、螺纹配合、报错行号
python tests/test_page.py         网页配置校验：零件名、字段、表达式、连杆机构能不能装上
python tests/test_agent_fake.py   工具循环：用按剧本回复的假 Ollama 走完整条链路
python -m qb selftest             全部范例：建模 → 网页 → 浏览器检查
```

## 验证情况

已验证：

- 零件库和检查，在 Blender 5.3 和 4.5 LTS 下测试通过。
- 三个范例的建模、网页生成、无头浏览器检查（电脑和手机两种尺寸）通过。
- 工具循环用假 Ollama 走通：催促、拦截、报错提示、图片回传、finish 把关都按预期工作。
- Windows 11 + Blender 5.2 + Ollama `qwen3.8:27b-q8_0`：`启动.bat`、`试跑.bat`、自动找 Blender、自检、对比试跑都跑通。

对比试跑（C 形夹，同一个模型）：

| 条件 | 用时 | 轮数 | 结果 |
|---|---|---|---|
| 没有工具 | 574 秒 | 1 | 脚本能跑；夹体只剩下臂，丝杆扎进压块和手柄，工件悬空；网页能打开 |
| 有工具 | 421 秒 | 23 | C 形夹体、丝杆、压块、工件、手柄齐全；6 步讲解，带圈数滑条；检查出的一处空白画面它自己改掉了 |

这次试跑里有工具那一遍留下的问题：下臂的孔钻反了方向没钻到，模型用 `allow_overlap` 把穿模盖了过去；手柄偏在一侧没有居中。
前一个现在会被工具拦住（空钻报错；`allow_overlap` 超过 1 mm 不认）。

第二次试跑（行星齿轮减速器：太阳轮 18 齿、行星轮 18 齿 ×3、内齿圈 54 齿，要求真啮合、按 1/4 速比转）：

| 条件 | 用时 | 轮数 | 结果 |
|---|---|---|---|
| 没有工具 | 约 1050 秒 | 1 | 两次都没有写出任何代码：思考把 32k 上下文用完了 |
| 有工具 | 1734 秒 | 19 | 6 个零件，齿全部啮合，0 个必须修的问题；6 步讲解，转速滑条，太阳轮、行星架、行星轮按 1 : 1/4 : −1/2 转 |

第三次试跑（空压机传动机构：Φ30 小皮带轮经皮带带 Φ90 大皮带轮，大轮轴上的曲柄经 60 长的连杆带活塞往复；没有工具那一遍关了思考）：

| 条件 | 用时 | 轮数 | 结果 |
|---|---|---|---|
| 没有工具 | 342 秒 | 1 | 脚本能跑，11 个零件全串在一根轴上，两个皮带轮同轴，13 处穿模；网页能打开，有文字和读数 |
| 有工具 | 1861 秒 | 28 | 13 个零件，皮带绕在两个轮上，曲柄、连杆、活塞、气缸位置正确，0 个必须修的问题；6 步讲解，转速 3:1，活塞位移随曲柄转角变化 |

有工具那一遍留下的问题：气缸不透明，转起来看不见里面的活塞；连杆小头和活塞之间没有做销子。

第四次试跑（只跑有工具的一遍，两道题）：

| 题目 | 用时 | 轮数 | 结果 |
|---|---|---|---|
| 蜗轮蜗杆减速器（模数 2、单头、30 齿） | 1779 秒 | 55 | 9 个零件，蜗杆轴架在两个支座上，蜗轮在竖直的输出轴上，0 个必须修的问题；6 步讲解，减速比 30 算对 |
| 四连杆雨刮器（曲柄 20、连杆 70、摇臂 40、机架 60） | 2452 秒 | 27 | 10 个零件，0 个必须修的问题；曲柄整圈转、摇臂和雨刮臂来回摆，摆角 71° 算对，带转速滑条和摆角读数 |

留下的问题：

- 减速器网页里蜗轮的转向写反了，转起来齿会扎进螺旋里。
- 雨刮器转起来以后连杆会扫过电机；玻璃摆的位置不对，刮片有一半行程在玻璃外面；连杆和摇臂之间没有做销子。

转向反和连杆扫过电机这两条，当时的检查查不出来。之后 `check_page` 加了运动检查，这两个结果拿回来重新检查都能报出来。
玻璃位置这种「摆得合不合理」的问题，工具查不出来。

第二次试跑还查出检查工具自己的一个误报（几块拼起来的零件，面贴面的地方会被当成穿模），已修。

还没验证：

- `render_device: gpu`。
- 「给上一个任务提修改意见」这条路径用真模型跑的效果。
- 运动检查报出问题以后，模型能不能自己改对。

## 目录

```
启动.bat          一键启动（调用 start.bat）
试跑.bat          不用输入的试跑
start.bat         git pull、准备环境、运行
qb/               工具循环、工具实现、网页生成、浏览器检查、菜单
blender/          qblib.py 零件库；runner.py 在 Blender 里运行、测量、渲染、导出
web/              网页骨架（three.js r180 已打包在 vendor/ 里）
docs/             demo.json 和 custom.js 的写法
examples/         范例任务和单项写法
tests/            测试
jobs/             任务输出（不进仓库）
```
