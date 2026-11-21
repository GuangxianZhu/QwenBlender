// 第 4 步：沿管子中心线画几根流动的箭头，并显示流速
// 管子中心线（毫米）：直上到 z=89，沿半径 24 的圆弧拐弯，再水平走到 x=60
var PATH = [[0, 0, 0], [0, 0, 89], [3.2, 0, 101], [12, 0, 109.8], [24, 0, 113], [60, 0, 113]];
var ID = 28;                                                    // 管子内径（毫米）
var N = 4;                                                      // 箭头数量
var phase = 0;

function pathLength() {
  var s = 0;
  for (var i = 1; i < PATH.length; i++) s += dist(PATH[i - 1], PATH[i]);
  return s;
}
function dist(a, b) { return Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]); }
function pointAt(s) {                                           // 中心线上离起点 s 毫米的点
  for (var i = 1; i < PATH.length; i++) {
    var d = dist(PATH[i - 1], PATH[i]);
    if (s <= d) {
      var k = s / d, a = PATH[i - 1], b = PATH[i];
      return [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k];
    }
    s -= d;
  }
  return PATH[PATH.length - 1];
}

QB.onFrame = function (api, t, dt) {
  var show = api.step() === 3;
  var q = api.param("flow");                                    // 升/分
  var area = Math.PI * Math.pow(ID / 2 / 1000, 2);              // 平方米
  var v = q / 60000 / area;                                     // 米/秒
  var L = pathLength(), seg = 14;
  phase = (phase + v * 60 * dt) % (L / N);                      // 画面上放慢，只表示快慢
  for (var i = 0; i < N; i++) {
    if (!show || q <= 0) { api.hideArrow("flow" + i); continue; }
    var s = phase + i * L / N;
    if (s + seg > L) { api.hideArrow("flow" + i); continue; }
    api.arrow("flow" + i, pointAt(s), pointAt(s + seg), "#1f8fd6");
  }
  if (show) api.readout("管内流速", v.toFixed(2) + " 米/秒");
};
