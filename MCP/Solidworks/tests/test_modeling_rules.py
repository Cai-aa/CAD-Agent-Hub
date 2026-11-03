import copy
import unittest
from solidworks_mcp.modeling_rules import plane_frame,review_feature_graph,validate_sketch_transform
from solidworks_mcp.feature_graph import compile_feature_graph
from solidworks_mcp.contracts import ContractError

def graph():
    return {'version':'1.0','metadata':{'tree_language':'zh-CN'},'features':[
        {'name':'part','display_name':'测试零件','kind':'new_part'},
        {'name':'oblique','display_name':'倾斜基准面','kind':'reference_plane_points','points_mm':[[0,0,0],[1,0,0],[0,1,1]]},
        {'name':'profile','display_name':'修整轮廓','kind':'sketch','plane':'oblique','entities':[{'kind':'circle','radius_mm':2}]},
        {'name':'trim','display_name':'局部修整切除','kind':'cut_extrude','sketch':'profile','depth_mm':3}]}

class ModelingRulesTests(unittest.TestCase):
    def test_display_names_remap_graph_references_and_preserve_input(self):
        g=graph();original=copy.deepcopy(g);plan=compile_feature_graph(g)
        self.assertEqual(plan[2]['plane'],'倾斜基准面')
        self.assertEqual(plan[3]['sketch'],'修整轮廓')
        self.assertEqual(g,original)
        self.assertEqual(review_feature_graph(g)['name_map']['trim'],'局部修整切除')

    def test_english_ids_receive_default_chinese_display_names(self):
        g=graph()
        for f in g['features']:f.pop('display_name')
        plan=compile_feature_graph(g)
        self.assertEqual(plan[0]['name'],'零件001')
        self.assertEqual(plan[-1]['sketch'],plan[2]['name'])

    def test_duplicate_display_names_are_rejected(self):
        g=graph();g['features'][2]['display_name']=g['features'][1]['display_name']
        with self.assertRaises(ContractError):compile_feature_graph(g)

    def test_system_plane_names_cannot_be_shadowed(self):
        g=graph();g['features'][1]['display_name']='前视基准面'
        with self.assertRaises(ContractError):compile_feature_graph(g)

    def test_nearly_collinear_plane_is_rejected_independently_of_scale(self):
        for scale in (1,1e6):
            with self.assertRaises(ContractError):plane_frame([[0,0,0],[scale,0,0],[2*scale,scale*1e-10,0]])

    def test_frame_keeps_declared_normal_and_reports_nonassociativity(self):
        frame=plane_frame([[0,0,0],[1,0,0],[0,1,0]])
        self.assertEqual(frame['normal'],[0,0,1])
        self.assertFalse(frame['associative'])

    def test_sheared_sketch_transform_is_rejected(self):
        with self.assertRaises(ContractError):validate_sketch_transform([1,.2,0,0,1,0,0,0,1,0,0,0,1,0,0,0])

    def test_oblique_finite_cut_requests_boundary_review_not_geometry_pass(self):
        result=review_feature_graph(graph())
        self.assertEqual(result['status'],'REVIEW_REQUIRED')
        self.assertFalse(result['geometry_verified'])
        self.assertIn('FINITE_OBLIQUE_CUT',[f['code'] for f in result['findings']])

    def test_finishing_order_is_flagged_without_automatic_reordering(self):
        g=graph();g['features'].extend([
            {'name':'fillet','kind':'fillet','radius_mm':1,'selector':{'orientation':'any'}},
            {'name':'chamfer','kind':'chamfer','distance_mm':1,'selector':{'orientation':'any'}}])
        before=copy.deepcopy(g);review=review_feature_graph(g)
        self.assertEqual(g,before)
        self.assertIn('FINISHING_INTERACTION',[f['code'] for f in review['findings']])
