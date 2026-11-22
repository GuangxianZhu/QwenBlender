# QwenBlender 工作规则

- 说明文档、注释、给模型看的提示和报错一律用中文。
- 单位毫米，角度用度，Z 朝上。demo.json 和 custom.js 也用这套坐标，换算只在 `web/viewer.js` 里做。
- `blender/qblib.py` 里的公开函数：参数先校验，报错信息要写清楚哪个参数、现在是什么值、应该是什么。
- 新增或修改 qblib 函数后：更新 `qb/search.py` 的 `GROUPS`，在 `tests/lib_all_model.py` 里加一行，运行 `python tests/test_lib.py`。
- 零件库生成的每个零件都必须是封闭实体。
- 工具返回给模型的文字：先给结论，再给数字，最后给下一步该调哪个工具。
- 改了 `qb/tools.py`、`qb/agent.py`、`qb/ollama.py` 后运行 `python tests/test_agent_fake.py`。
- 改了 `qb/calc.py` 后运行 `python tests/test_page.py`。
- 运动检查里的位置算法和视角表（`blender/runner.py` 的 `pose_at`、`PAGE_VIEWS`）要和 `web/viewer.js` 保持一致。
- 改了 `web/` 或 `qb/page.py` 后运行 `python tests/test_page.py` 和 `python -m qb selftest`。
- 所有 `.bat` 只用 ASCII 字符，换行用 CRLF。实际逻辑在 `start.bat`，第一步是 `git pull`；`启动.bat` 和 `试跑.bat` 只负责调用它。
- 只走 Ollama 原生接口 `/api/chat`。
- `jobs/`、`cache/`、`config.json` 不提交。
