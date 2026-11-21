# custom.js 怎么写（可选）

demo.json 做不到的效果才写 custom.js：比如按公式实时移动零件、画箭头、显示算出来的数。
文件里给 `QB` 挂三个函数，都可以不写：

```js
QB.onInit = function (api) { /* 页面加载好，执行一次 */ };
QB.onStep = function (api, index, step) { /* 每次切到某一步 */ };
QB.onFrame = function (api, t, dt) { /* 每一帧。t 是这一步已过的秒数 */ };
```

坐标都是建模坐标：毫米，Z 朝上。

## api

- `api.part("零件名")` 返回零件句柄：
  - `.move(x, y, z)` 在原位置上再平移（每帧设置，叠加在 demo.json 的动画之后）
  - `.turn("z", 角度)` 绕零件原点再转
  - `.color("#ff0000")` 改颜色，`.color(null)` 还原
  - `.opacity(0.3)` 改不透明度，`.opacity(null)` 还原
  - `.show(false)` 隐藏，`.show(null)` 还原
  - `.center()` 返回零件当前中心 `[x, y, z]`
- `api.param("id")` 读滑条的值；`api.setParam("id", 值)` 改滑条。
- `api.step()` 当前第几步（从 0 开始）；`api.time()` 这一步已过秒数。
- `api.readout("标签", "文字")` 在讲解面板里显示一格读数。
- `api.arrow("名字", [x,y,z], [x,y,z], "#d9730d")` 画或更新一根箭头（从第一个点指向第二个点）；`api.hideArrow("名字")`。
- `api.label("名字", [x,y,z], "文字")` 在一个点上贴标签。
- `api.panel()` 返回讲解面板里一块空的 div，可以往里放自己的 HTML。
- `api.error("说明")` 报告错误（check_page 会看到）。
- `api.THREE`、`api.scene`、`api.camera`、`api.root`：需要直接用 three.js 时用。

## 例子：活塞跟着曲轴转角上下动

```js
QB.onFrame = function (api, t, dt) {
  var a = api.param("angle") * Math.PI / 180;
  var r = 20, l = 60;                                   // 曲柄半径、连杆长度
  var y = r * Math.cos(a) + Math.sqrt(l * l - Math.pow(r * Math.sin(a), 2));
  api.part("Piston").move(0, 0, y - (r + l));          // 上止点时位移为 0
  api.readout("活塞位置", (y - (r + l)).toFixed(1) + " mm");
};
```

写完用 build_page 和 check_page 检查；零件名、参数名写错会直接报出来。
