import unittest
from solidworks_mcp.feature_graph import compile_feature_graph
from solidworks_mcp.contracts import ContractError

class LoftContracts(unittest.TestCase):
    def test_loft_rejects_same_profile_twice(self):
        graph={'version':'1.0','features':[{'name':'零件','kind':'new_part'},
            {'name':'截面','kind':'sketch','entities':[{'kind':'circle','radius_mm':3}]},
            {'name':'切除','kind':'cut_loft','profiles':['截面','截面']}]}
        with self.assertRaises(ContractError):compile_feature_graph(graph)

    def test_chinese_tree_policy_rejects_english_display_name(self):
        with self.assertRaises(ContractError):compile_feature_graph({'version':'1.0','metadata':{'tree_language':'zh-CN'},
            'features':[{'name':'Part','display_name':'Part','kind':'new_part'}]})
