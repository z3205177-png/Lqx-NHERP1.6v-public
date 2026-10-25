import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import verify_codes as v


def erp_record(code, name, source="组合装", item_id="ITEM-A"):
    return {
        "code": code,
        "name": name,
        "source": source,
        "item_id": item_id,
        "features": v.build_features("", "", erp_name=name),
    }


class MatchingRulesTest(unittest.TestCase):
    def setUp(self):
        self.aitcao = erp_record("ERP-AI-30", "暖贴艾草30片")
        self.ginger = erp_record("ERP-GJ-30", "暖贴生姜30片", item_id="ITEM-B")
        self.records = [self.aitcao, self.ginger]
        self.by_code = {"ERP-AI-30": [self.aitcao], "ERP-GJ-30": [self.ginger]}

    def test_correct_code_requires_identity_match(self):
        pf = v.build_features("暖火艾草暖贴", "艾草暖贴30片")
        pf["erp_item_id"] = "ITEM-A"
        result = v.classify_row("ERP-AI-30", pf, self.by_code, self.records)
        self.assertEqual(result["核验状态"], "编码正确")
        self.assertEqual(result["应改为编码"], "")

    def test_wrong_code_only_recommends_unique_erp_record(self):
        pf = v.build_features("暖火艾草暖贴", "艾草暖贴30片")
        pf["erp_item_id"] = "ITEM-A"
        result = v.classify_row("ERP-GJ-30", pf, self.by_code, self.records)
        self.assertEqual(result["核验状态"], "编码错误（建议修改）")
        self.assertEqual(result["应改为编码"], "ERP-AI-30")

    def test_blank_code_can_be_filled_only_when_unique(self):
        pf = v.build_features("暖火艾草暖贴", "艾草暖贴30片")
        pf["erp_item_id"] = "ITEM-A"
        result = v.classify_row("", pf, {"ERP-AI-30": [self.aitcao]}, [self.aitcao])
        self.assertEqual(result["核验状态"], "编码缺失（待补录）")
        self.assertEqual(result["应改为编码"], "")

    def test_ambiguous_matches_are_manual(self):
        duplicate_candidate = erp_record("ERP-AI-30-2", "暖贴艾草30片")
        records = [self.aitcao, duplicate_candidate]
        result = v.classify_row("", v.build_features("暖火艾草暖贴", "艾草暖贴30片"), {}, records)
        self.assertEqual(result["核验状态"], "待人工确认")
        self.assertEqual(result["应改为编码"], "")

    def test_existing_code_does_not_resolve_multiple_identities(self):
        other = erp_record("ERP-OTHER", "暖贴艾草30片", item_id="ITEM-OTHER")
        result = v.classify_row("ERP-AI-30", v.build_features("暖贴艾草30片", "暖贴艾草30片"),
                                self.by_code, [self.aitcao, other])
        self.assertEqual(result["核验状态"], "待人工确认")

    def test_exact_name_alone_never_authorizes(self):
        result = v.classify_row("WRONG", v.build_features("暖贴艾草30片", "暖贴艾草30片"),
                                self.by_code, self.records)
        self.assertEqual(result["核验状态"], "异常（ERP未找到）")
        self.assertEqual(result["应改为编码"], "")

    def test_pair_conversion_authorized_for_foot_patches(self):
        self.assertTrue(v.quantity_compare((20, "片"), (10, "对"), {"足贴"}))
        self.assertIsNone(v.quantity_compare((20, "片"), (10, "对"), {"手套"}))

    def test_multipack_pair_quantity(self):
        self.assertEqual(v.extract_quantity("儿童鞋垫5对*4包", {"发热鞋垫"}), (20, "对"))

    def test_three_in_one_each_and_total_are_distinct(self):
        self.assertEqual(v.extract_quantity("艾草/益母草/生姜暖贴各20片"), (60, "片"))
        self.assertEqual(v.extract_quantity("三合一暖贴20片（艾草5+益母草5+生姜10）"), (20, "片"))

    def test_cartoon_is_not_kt_alias(self):
        self.assertNotEqual(v.extract_variant_groups("卡通暖贴"), v.extract_variant_groups("KT暖贴"))

    def test_duplicate_erp_code_is_manual(self):
        duplicate = erp_record("ERP-AI-30", "暖贴艾草30片盒装", "单品")
        result = v.classify_row("ERP-AI-30", v.build_features("暖火艾草暖贴", "艾草暖贴30片"),
                                {"ERP-AI-30": [self.aitcao, duplicate]}, [self.aitcao, duplicate])
        self.assertEqual(result["核验状态"], "待人工确认")
        self.assertEqual(result["应改为编码"], "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
