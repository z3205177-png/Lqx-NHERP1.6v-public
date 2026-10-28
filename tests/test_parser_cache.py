import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import verify_codes as v


class ParserCacheTests(unittest.TestCase):
    def test_mutation_of_returned_structures_does_not_leak(self):
        text='暖贴20片+足贴10对'
        first=v.quantity_structure(text)
        first['parts'][0]['families'].clear()
        self.assertEqual(v.quantity_structure(text)['parts'][0]['families'],['暖贴'])
        parts=v.audit_components(text)
        parts['暖贴']['families'].clear()
        self.assertEqual(v.audit_components(text)['暖贴']['families'],{'暖贴'})

    def test_conversion_permission_changes_invalidate_cache_key(self):
        text='暖贴20片+足贴10对'
        with patch.dict(v.BUSINESS_RULES,{'pair_piece_families':['足贴']}):
            self.assertEqual(v.quantity_structure(text)['qty'],(40,'片'))
        with patch.dict(v.BUSINESS_RULES,{'pair_piece_families':[]}):
            self.assertIsNone(v.quantity_structure(text)['qty'])
            self.assertEqual(v.audit_components(text)['足贴']['qty'],(10,'对'))


if __name__=='__main__':unittest.main()
