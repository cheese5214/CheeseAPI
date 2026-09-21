''' 测试包：确保本仓库源码（而不是 site-packages 里的旧版 CheeseAPI）优先被导入 '''
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
