from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from folderpilot.samples import create_demo
create_demo('demo-work')
print('Missing synthetic demo files created under demo-work; existing files unchanged.')
