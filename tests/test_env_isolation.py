"""
测试环境隔离性与 _env.py 约束生效情况
======================================
断言：任何干净子进程在导入 animeautosub._env 后，
HuggingFace 缓存路径必须严格指向 D:\Dev\huggingface，严禁回退 C 盘。
"""

import os
import sys
import subprocess
from pathlib import Path

def test_env_injection_in_clean_subprocess():
    """在清理掉环境变量的独立子进程中测试 _env 注入效果"""
    cmd = [
        sys.executable,
        "-c",
        (
            "import os; "
            "import animeautosub._env; "
            "import huggingface_hub.constants as c; "
            "print('RESOLVED_HF_HOME=' + str(c.HF_HOME)); "
            "assert str(c.HF_HOME).lower().startswith(r'd:\\dev\\huggingface'), 'Leaked to C drive!'"
        )
    ]
    # 使用干净环境变量测试
    clean_env = os.environ.copy()
    clean_env.pop("HF_HOME", None)
    clean_env.pop("HF_HUB_CACHE", None)

    r = subprocess.run(cmd, env=clean_env, capture_output=True, text=True, cwd=str(Path(__file__).parent.parent))
    assert r.returncode == 0, f"Subprocess failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    assert "RESOLVED_HF_HOME=D:\\Dev\\huggingface" in r.stdout
