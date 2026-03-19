import os
import sys

# 确保无论从哪里启动，都能找到 hospital_deploy_tool 包
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

# 单文件打包模式下，PySide2 DLL 解压在临时目录中，
# 部分电脑缺少 VC++ Runtime 或 DLL 搜索路径不完整会导致 ImportError。
# 必须在导入 PySide2 之前将解压目录加入 DLL 搜索路径。
if getattr(sys, "frozen", False):
    _meipass = sys._MEIPASS
    os.add_dll_directory(_meipass)
    pyside2_dir = os.path.join(_meipass, "PySide2")
    if os.path.isdir(pyside2_dir):
        os.add_dll_directory(pyside2_dir)
    os.environ["PATH"] = _meipass + os.pathsep + os.environ.get("PATH", "")

from hospital_deploy_tool.main import run

if __name__ == "__main__":
    raise SystemExit(run())
