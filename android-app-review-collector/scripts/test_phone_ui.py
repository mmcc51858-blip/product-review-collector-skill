"""Navigation guards, using real UI fixture signatures and synthetic unsafe controls."""
import unittest
import xml.etree.ElementTree as ET
from phone_ui import validate_target,verify_search_text

def node(**kw):
    attrs={'text':'搜索','class':'android.widget.TextView','package':'com.ss.android.ugc.aweme','bounds':'[10,100][110,180]','enabled':'true'}
    attrs.update(kw);return ET.Element('node',attrs)

class NavigationGuards(unittest.TestCase):
    def test_same_visible_control_is_centered(self):
        a=node();b=node()
        self.assertEqual(validate_target(a,b,'com.ss.android.ugc.aweme'),(60,140))
    def test_moved_control_requires_reobservation(self):
        with self.assertRaises(ValueError):validate_target(node(),node(bounds='[0,0][30,30]'),'com.ss.android.ugc.aweme')
    def test_other_app_rejected(self):
        a=node(package='other.app')
        with self.assertRaises(ValueError):validate_target(a,a,'com.ss.android.ugc.aweme')
    def test_purchase_and_account_controls_rejected(self):
        for title in ['加入购物车','购物车','现在下单','立即购买','领券抢购','收藏','有用','客服','登录','验证码']:
            with self.subTest(title=title):
                a=node(text=title)
                with self.assertRaises(ValueError):validate_target(a,a,'com.ss.android.ugc.aweme')
    def test_disabled_and_empty_controls_rejected(self):
        for a in [node(enabled='false'),node(bounds='[0,0][0,0]')]:
            with self.assertRaises(ValueError):validate_target(a,a,'com.ss.android.ugc.aweme')
    def test_ime_rewritten_share_code_rejected(self):
        r=ET.Element('hierarchy');r.append(node(text='＃＃2C2身体哦＃＃',focused='true',**{'class':'android.widget.EditText'}))
        with self.assertRaises(ValueError):verify_search_text(r,'com.ss.android.ugc.aweme','##fixture-code##')
    def test_exact_share_code_accepted(self):
        r=ET.Element('hierarchy');r.append(node(text='##exact##',focused='true',**{'class':'android.widget.EditText'}))
        verify_search_text(r,'com.ss.android.ugc.aweme','##exact##')

if __name__=='__main__':unittest.main()
