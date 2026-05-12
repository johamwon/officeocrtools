"""
打包脚本 - 构建绿色免安装包

使用方式:
    python scripts/build_package.py

产出:
    dist/DocParser/  — 完整的绿色包目录
    dist/DocParser.zip — 压缩包

前置条件:
    1. 已下载 Python embeddable package 到 scripts/python-embed.zip
    2. 已下载 llama-server.exe 到 scripts/llama-server.exe
    3. 已下载 qwen2.5-coder-1.5b-instruct-q8_0.gguf 到 scripts/ 或指定路径
"""
import os
import sys
import shutil
import zipfile
import subprocess
from pathlib import Path

# 配置
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
DIST_DIR = PROJECT_DIR / "dist"
PACKAGE_DIR = DIST_DIR / "DocParser"

# 嵌入式Python下载地址（需要手动下载到 scripts/ 目录）
PYTHON_EMBED_ZIP = SCRIPT_DIR / "python-3.12.8-embed-amd64.zip"
LLAMA_SERVER_EXE = SCRIPT_DIR / "llama-server.exe"
MODEL_FILE = SCRIPT_DIR / "qwen2.5-coder-1.5b-instruct-q8_0.gguf"


def clean():
    """清理旧的构建产物"""
    if PACKAGE_DIR.exists():
        print("[清理] 删除旧的构建目录...")
        shutil.rmtree(PACKAGE_DIR)
    PACKAGE_DIR.mkdir(parents=True)


def setup_python_runtime():
    """设置嵌入式Python运行时"""
    print("[Python] 解压嵌入式Python...")
    python_dir = PACKAGE_DIR / "runtime" / "python"
    python_dir.mkdir(parents=True)

    if not PYTHON_EMBED_ZIP.exists():
        print(f"  ❌ 未找到 {PYTHON_EMBED_ZIP}")
        print(f"  请从 https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip 下载")
        print(f"  放到 {SCRIPT_DIR} 目录下")
        return False

    with zipfile.ZipFile(PYTHON_EMBED_ZIP, "r") as z:
        z.extractall(python_dir)

    # 修改 ._pth 文件以支持 site-packages
    pth_files = list(python_dir.glob("python*._pth"))
    if pth_files:
        pth_file = pth_files[0]
        content = pth_file.read_text()
        # 取消注释 import site
        content = content.replace("#import site", "import site")
        # 添加 app 目录到路径
        content += "\n../../../app\n"
        pth_file.write_text(content)
        print(f"  ✓ 修改 {pth_file.name} 启用 site-packages")

    # 安装 pip
    print("[Python] 安装 pip...")
    get_pip_url = "https://bootstrap.pypa.io/get-pip.py"
    get_pip_path = python_dir / "get-pip.py"

    # 下载 get-pip.py
    import urllib.request
    urllib.request.urlretrieve(get_pip_url, get_pip_path)

    python_exe = python_dir / "python.exe"
    subprocess.run(
        [str(python_exe), str(get_pip_path), "--no-warn-script-location"],
        cwd=str(python_dir),
        check=True,
    )
    get_pip_path.unlink()

    # 安装项目依赖
    print("[Python] 安装项目依赖...")
    requirements = PROJECT_DIR / "requirements.txt"
    subprocess.run(
        [
            str(python_exe), "-m", "pip", "install",
            "-r", str(requirements),
            "--no-warn-script-location",
            "--disable-pip-version-check",
        ],
        check=True,
    )
    print("  ✓ 依赖安装完成")
    return True


def setup_llm_runtime():
    """设置LLM运行时"""
    print("[LLM] 设置 llama-server...")
    runtime_dir = PACKAGE_DIR / "runtime"

    if LLAMA_SERVER_EXE.exists():
        shutil.copy2(LLAMA_SERVER_EXE, runtime_dir / "llama-server.exe")
        print("  ✓ llama-server.exe 已复制")
    else:
        print(f"  ⚠ 未找到 {LLAMA_SERVER_EXE}")
        print(f"  请从 https://github.com/ggerganov/llama.cpp/releases 下载 Windows 版本")

    # 模型文件
    models_dir = PACKAGE_DIR / "models" / "llm"
    models_dir.mkdir(parents=True)

    if MODEL_FILE.exists():
        print("[LLM] 复制模型文件（可能需要几分钟）...")
        shutil.copy2(MODEL_FILE, models_dir / MODEL_FILE.name)
        print("  ✓ 模型文件已复制")
    else:
        print(f"  ⚠ 未找到模型文件 {MODEL_FILE}")
        print(f"  请将 gguf 模型文件放到 {models_dir}")


def copy_app_code():
    """复制业务代码"""
    print("[App] 复制业务代码...")
    app_dir = PACKAGE_DIR / "app"
    app_dir.mkdir(parents=True)

    # 复制模块
    modules = ["doc_parser", "backend", "frontend", "notifier"]
    for mod in modules:
        src = PROJECT_DIR / mod
        dst = app_dir / mod
        if src.exists():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            print(f"  ✓ {mod}/")

    # 复制入口文件
    shutil.copy2(PROJECT_DIR / "run_backend.py", app_dir / "run_backend.py")
    shutil.copy2(PROJECT_DIR / "requirements.txt", app_dir / "requirements.txt")
    print("  ✓ run_backend.py")


def copy_config():
    """复制配置文件"""
    print("[Config] 复制配置...")
    config_dir = PACKAGE_DIR / "config"
    config_dir.mkdir(parents=True)
    shutil.copy2(PROJECT_DIR / "config" / "app.ini", config_dir / "app.ini")
    print("  ✓ config/app.ini")


def copy_scripts():
    """复制启动脚本"""
    print("[Scripts] 复制启动脚本...")
    shutil.copy2(PROJECT_DIR / "start.bat", PACKAGE_DIR / "start.bat")
    shutil.copy2(PROJECT_DIR / "stop.bat", PACKAGE_DIR / "stop.bat")
    print("  ✓ start.bat, stop.bat")


def create_directories():
    """创建运行时目录"""
    print("[Dirs] 创建运行时目录...")
    (PACKAGE_DIR / "storage" / "uploads").mkdir(parents=True)
    (PACKAGE_DIR / "storage" / "ocr_cache").mkdir(parents=True)
    (PACKAGE_DIR / "logs").mkdir(parents=True)
    (PACKAGE_DIR / "models" / "paddleocr").mkdir(parents=True, exist_ok=True)
    print("  ✓ storage/, logs/, models/")


def create_readme():
    """创建用户说明"""
    readme = PACKAGE_DIR / "使用说明.txt"
    readme.write_text("""
╔══════════════════════════════════════════════╗
║     文档解析与合同管理系统 v0.2.0            ║
╚══════════════════════════════════════════════╝

【启动方式】
  双击 start.bat 即可启动系统。
  浏览器会自动打开 http://localhost:8000

【停止方式】
  双击 stop.bat 停止所有服务。

【配置修改】
  编辑 config/app.ini 文件，修改后重启生效。

【钉钉推送】
  在 config/app.ini 的 [notify] 部分配置：
  - enabled = true
  - dingtalk_webhook = 你的钉钉机器人Webhook地址

【数据存储】
  - storage/parser.db — 数据库
  - storage/uploads/ — 上传的文档
  - logs/ — 运行日志

【系统要求】
  - Windows 10 64位
  - 内存 >= 4GB（推荐8GB）
  - 磁盘空间 >= 5GB

【常见问题】
  Q: 启动后浏览器打不开？
  A: 等待10秒后手动访问 http://localhost:8000

  Q: OCR识别很慢？
  A: 首次运行需要加载模型（约15秒），后续会快很多。

  Q: 如何卸载？
  A: 运行 stop.bat 停止服务，然后直接删除整个文件夹即可。
""", encoding="utf-8")
    print("  ✓ 使用说明.txt")


def make_zip():
    """打包为zip"""
    print("[Zip] 创建压缩包...")
    zip_path = DIST_DIR / "DocParser.zip"
    if zip_path.exists():
        zip_path.unlink()

    shutil.make_archive(str(DIST_DIR / "DocParser"), "zip", DIST_DIR, "DocParser")
    size_mb = zip_path.stat().st_size / 1024 / 1024
    print(f"  ✓ {zip_path} ({size_mb:.1f} MB)")


def main():
    print("=" * 50)
    print("  文档解析系统 - 打包构建")
    print("=" * 50)
    print()

    clean()
    create_directories()
    copy_app_code()
    copy_config()
    copy_scripts()
    create_readme()

    # 以下步骤需要预先下载的文件
    has_python = setup_python_runtime()
    setup_llm_runtime()

    if has_python:
        make_zip()

    print()
    print("=" * 50)
    print("  构建完成！")
    print(f"  输出目录: {PACKAGE_DIR}")
    print("=" * 50)


if __name__ == "__main__":
    main()
