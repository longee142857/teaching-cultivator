"""Windows Task Scheduler 触发：数学一推送 09:00"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from cultivate import cultivate
cultivate("math")
