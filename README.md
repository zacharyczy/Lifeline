# Lifeline — Codex 额度悬浮窗

双击 `start.cmd`，两个进度条会浮在屏幕右上角。拖动任意位置可移动；双击可立即刷新；右键或按 `Esc` 可关闭。窗口每 90 秒自动读取一次额度。

两条进度条显示 **剩余** 百分比，分别对应 5 小时和 7 天额度。读不到数据时保留上次结果；首次读取失败会显示 `--`，不把未知数据当成 0%。

程序只通过本机已登录的 Codex CLI 的 App Server 调用 `account/rateLimits/read`，不保存或上传令牌。如果提示找不到 Codex CLI，可以先在终端运行 `codex --version`；也可以将环境变量 `CODEX_BIN` 设为 `codex.exe` 的完整路径。需要 Python 3 与 Tkinter（Windows Python 通常自带）。

这是独立的置顶窗口。若账号未登录 Codex CLI，或当前登录方式不提供订阅额度，窗口会显示 `--`。可用 `python lifeline.py` 从终端启动，查看本机环境中的错误。官方协议说明见 [Codex App Server](https://learn.chatgpt.com/docs/app-server)。
