这是沙箱工作区里的说明文件（readme.txt）。

Agent 被允许读写的就是 sandbox_workspace/ 目录：
- 只读操作（list/read/run_shell 白名单命令）自动放行
- 写操作（write_file）记录审计后放行
- 破坏性操作（delete_file）默认拒绝，需人工审批

试试对 02_secure_agent.py 说：
    "列出沙箱文件，然后读 readme.txt 总结"
