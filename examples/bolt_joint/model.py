# 螺栓连接：两块板用 M8 螺栓、垫圈、螺母夹紧
from qblib import *

T = 6          # 每块板的厚度
PLATE = 40     # 板的边长

# 下板、上板（上板叠在下板上）
lower = rounded_box(PLATE, PLATE, T, 4)
hole(lower, 9, (0, 0, T))
mat(lower, "aluminum")
part(lower, "PlateLower", cn="下板", info="被连接件。通孔 Φ9，比螺栓大 1 mm，方便装配。", explode=(0, 0, -14))

upper = rounded_box(PLATE, PLATE, T, 4)
stack(upper, lower)
hole(upper, 9, (0, 0, 2 * T))
mat(upper, "blue")
part(upper, "PlateUpper", cn="上板", info="被连接件。和下板靠摩擦力传递横向力。", explode=(0, 0, 6))

# 上垫圈：放在上板顶面
w1 = washer(8.4, 16, 1.6)
stack(w1, upper)
mat(w1, "zinc")
part(w1, "WasherTop", cn="上垫圈", info="把螺栓头的压力分散到更大的面积上。", explode=(0, 0, 22))

# 螺栓：头部下表面压在上垫圈顶面
bolt = hex_bolt(8, 30)
at(bolt, 0, 0, 2 * T + 1.6)
mat(bolt, "steel")
part(bolt, "Bolt", cn="M8 螺栓", info="M8×30，螺距 1.25。拧紧后被拉长，像一根很硬的弹簧把零件夹住。", explode=(0, 0, 44))

# 下垫圈：贴在下板底面
w2 = washer(8.4, 16, 1.6)
beside(w2, lower, "-z")
mat(w2, "zinc")
part(w2, "WasherBottom", cn="下垫圈", info="保护下板表面，防止螺母转动时刮伤。", explode=(0, 0, -26))

# 螺母：夹紧厚度 = 上垫圈 + 两块板 + 下垫圈
n = nut(8)
screw_on(n, bolt, grip=1.6 + 2 * T + 1.6)
mat(n, "brass")
part(n, "Nut", cn="M8 螺母", info="拧一圈前进一个螺距 1.25 mm。", explode=(0, 0, -40))
