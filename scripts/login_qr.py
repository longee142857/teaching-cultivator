"""独立二维码登录脚本。运行后扫码即可。"""
import sys, os, time, json, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from deliver.weixin_bridge import WechatBridge

wx = WechatBridge()
ok = wx.login_interactive()
if ok:
    print("\n✅ 登录成功！程序退出，请运行 main.py --listen 开始监听")
else:
    print("\n❌ 登录失败")
