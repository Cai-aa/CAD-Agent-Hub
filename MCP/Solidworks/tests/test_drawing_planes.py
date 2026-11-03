import unittest
from types import SimpleNamespace
from solidworks_mcp.contracts import ContractError
from solidworks_mcp.feature_graph import compile_feature_graph
from solidworks_mcp.native_features import _com_value

class DrawingPlaneTests(unittest.TestCase):
    def test_collinear_plane_rejected(self):
        with self.assertRaises(ContractError):
            compile_feature_graph({"version":"1.0","features":[{"name":"Part","kind":"new_part"},
                {"name":"Plane","kind":"reference_plane_points","points_mm":[[0,0,0],[1,0,0],[2,0,0]]}]})

    def test_fixed_plane_model_space_graph_compiles(self):
        result=compile_feature_graph({"version":"1.0","features":[{"name":"Part","kind":"new_part"},
            {"name":"Plane","kind":"reference_plane_points","points_mm":[[0,0,0],[1,0,0],[0,0,1]]},
            {"name":"Sketch","kind":"sketch","plane":"Plane","coordinate_space":"model",
             "entities":[{"kind":"circle","center":[10,0,10],"radius_mm":2}]}]})
        self.assertEqual(result[-1]["coordinate_space"],"model")

    def test_com_dispatch_property_is_not_invoked_as_default_method(self):
        class Dispatch:
            _oleobj_=object()
            def __call__(self):
                raise AssertionError("COM object's default member must not be called")
        obj=Dispatch()
        self.assertIs(_com_value(SimpleNamespace(ActiveSketch=obj),"ActiveSketch"),obj)

if __name__=="__main__":unittest.main()
