"""Regression checks for review/filter separation in the observed Mall layout."""
import unittest
from collect import parse_page

CFG = dict(package='test.shop', list_resource_id='test.shop:id/reviews',
           body_left=44, sku_left=177, sku_regex='【|/')

def text(value, left):
    from xml.sax.saxutils import escape
    return f'<node text="{escape(value)}" bounds="[{left},400][1000,500]" />'

def page(frames):
    return '<hierarchy><node package="test.shop" resource-id="test.shop:id/reviews">'+''.join('<node>'+f+'</node>' for f in frames)+'</node></hierarchy>'

class ReviewParser(unittest.TestCase):
    def test_filter_tabs_are_not_reviews(self):
        raw=page([text('全部',44)+text('图/视频',234)])
        self.assertEqual(parse_page(raw,CFG),[])

    def test_review_body_sku_and_date_remain_paired(self):
        raw=page([text('买**家',155)+text('15天前',155),
                  text('猫猫用/6支【管6个月】',177)+text('物流很快，使用方便。',44)])
        rows=parse_page(raw,CFG)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['date_raw'],'15天前')
        self.assertEqual(rows[0]['text'],'物流很快，使用方便。')
        self.assertEqual(rows[0]['sku_raw'],'猫猫用/6支【管6个月】')

if __name__=='__main__':unittest.main()
