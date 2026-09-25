"""Download catalog + external images and build the synthetic dock photos into data/images/."""
import sys

from _path import *  # noqa: F401,F403
from reclaim.scenarios import ScenarioBook

made = ScenarioBook().prepare_images(sys.argv[1] if len(sys.argv) > 1 else "all")
print(f"built {len(made)} dock photos")
