from __future__ import annotations

import importlib
import json
import math
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path


class FakeFeature:
    def __init__(self, name="BLOCK(1)", journal_id="BLOCK 1"):
        self.Name = name
        self.JournalIdentifier = journal_id


class FakeBlockBuilder:
    class Types:
        OriginAndEdgeLengths = 1

    def __init__(self, part):
        self.part = part
        self.Type = None
        self.values = None
        self.destroyed = False

    def SetOriginAndLengths(self, point, length, width, height):
        self.values = (point, length, width, height)

    def SetBooleanOperationAndTarget(self, operation, target):
        self.operation = operation
        self.target = target

    def CommitFeature(self):
        feature = FakeFeature()
        self.part.Features.items.append(feature)
        self.part.Bodies.append(object())
        return feature

    def Destroy(self):
        self.destroyed = True


class FakeFeatures:
    def __init__(self, part):
        self.part = part
        self.items = [FakeFeature("DATUM_CSYS(0)", "FEATURE 0")]
        self.last_builder = None

    def __iter__(self):
        return iter(self.items)

    def CreateBlockFeatureBuilder(self, _null):
        self.last_builder = FakeBlockBuilder(self.part)
        return self.last_builder


class FakePart:
    def __init__(self, full_path=r"C:\temp\test.prt"):
        self.Tag = 42
        self.Leaf = Path(full_path).stem
        self.FullPath = full_path
        self.Bodies = []
        self.Features = FakeFeatures(self)

    def Save(self, save_components, close_after):
        self.save_args = (save_components, close_after)
        return FakeSaveStatus()


class FakeSaveStatus:
    NumberUnsavedParts = 0

    def __init__(self):
        self.disposed = False

    def Dispose(self):
        self.disposed = True


class FakeParts:
    def __init__(self):
        self.Work = FakePart()
        self.Display = self.Work

    def NewDisplay(self, path, units):
        part = FakePart(path)
        part.units = units
        self.Work = part
        self.Display = part
        return part


class FakeListingWindow:
    def Open(self):
        pass

    def WriteLine(self, _message):
        pass


class FakeSession:
    class MarkVisibility:
        Visible = 1

    def __init__(self):
        self.Parts = FakeParts()
        self.ListingWindow = FakeListingWindow()
        self.mark_names = []

    def SetUndoMark(self, *_args):
        return 7

    def SetUndoMarkName(self, mark, name):
        self.mark_names.append((mark, name))


def install_fake_nxopen():
    session = FakeSession()
    nxopen = types.ModuleType("NXOpen")
    nxopen.__path__ = []
    nxopen.Session = types.SimpleNamespace(
        GetSession=lambda: session,
        MarkVisibility=FakeSession.MarkVisibility,
    )
    nxopen.Point3d = lambda x, y, z: types.SimpleNamespace(X=x, Y=y, Z=z)
    nxopen.Body = types.SimpleNamespace(Null=None)
    nxopen.Part = types.SimpleNamespace(
        Units=types.SimpleNamespace(Millimeters="mm", Inches="in")
    )
    nxopen.BasePart = types.SimpleNamespace(
        SaveComponents=types.SimpleNamespace(TrueValue=True),
        CloseAfterSave=types.SimpleNamespace(FalseValue=False),
    )

    features = types.ModuleType("NXOpen.Features")
    features.Feature = types.SimpleNamespace(
        Null=None, BooleanType=types.SimpleNamespace(Create=1)
    )
    features.BlockFeatureBuilder = FakeBlockBuilder
    geometric = types.ModuleType("NXOpen.GeometricUtilities")
    nxopen.Features = features
    nxopen.GeometricUtilities = geometric
    sys.modules["NXOpen"] = nxopen
    sys.modules["NXOpen.Features"] = features
    sys.modules["NXOpen.GeometricUtilities"] = geometric
    return session


class NXBridgeOperationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.pop("NX_MCP_TOKEN", None)
        cls.session = install_fake_nxopen()
        sys.modules.pop("nx_bridge", None)
        cls.bridge = importlib.import_module("nx_bridge")
        sys.modules.pop("nx_remote_ops", None)
        cls.remote_ops = importlib.import_module("nx_remote_ops")

    def setUp(self):
        self.session.Parts.Work = FakePart()
        self.session.Parts.Display = self.session.Parts.Work
        self.bridge._EXEC_NS.clear()
        self.bridge._EXEC_NS.update(
            {"__name__": "__nx_mcp_exec__", "__doc__": None}
        )

    def test_ping_reports_work_part(self):
        result = self.bridge._op_ping({})
        self.assertTrue(result["ok"])
        self.assertEqual("test", result["work_part"])
        self.assertEqual("0.3.0", result["bridge_version"])

    def test_part_summary_is_bounded(self):
        self.session.Parts.Work.Features.items.extend(
            [FakeFeature("F2", "FEATURE 2"), FakeFeature("F3", "FEATURE 3")]
        )
        result = self.bridge._op_part_summary({"max_features": 2})
        self.assertEqual(3, result["feature_count"])
        self.assertEqual(2, len(result["features"]))
        self.assertTrue(result["features_truncated"])

    def test_create_block_uses_recorded_api_shape(self):
        result = self.bridge._op_create_block(
            {"length": 10, "width": 20, "height": 30, "origin": [1, 2, 3]}
        )
        self.assertEqual("BLOCK 1", result["feature"])
        self.assertEqual(1, result["body_count"])
        builder = self.session.Parts.Work.Features.last_builder
        self.assertTrue(builder.destroyed)
        self.assertEqual(("10.0", "20.0", "30.0"), builder.values[1:])

    def test_create_block_rejects_invalid_dimensions(self):
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            self.bridge._op_create_block({"length": 0})

    def test_create_part_is_workspace_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            original = self.bridge.WORKSPACE
            self.bridge.WORKSPACE = directory
            try:
                result = self.bridge._op_create_part(
                    {"file_name": "new_test", "units": "millimeters"}
                )
            finally:
                self.bridge.WORKSPACE = original
        self.assertEqual("new_test", result["name"])
        self.assertTrue(result["full_path"].endswith("new_test.prt"))

    def test_create_part_rejects_path_traversal(self):
        with self.assertRaisesRegex(ValueError, "plain file name"):
            self.bridge._op_create_part({"file_name": "../outside.prt"})

    def test_save_work_part_uses_confirmed_enums(self):
        result = self.bridge._op_save_work_part({})
        self.assertEqual(0, result["number_unsaved_parts"])
        self.assertEqual((True, False), self.session.Parts.Work.save_args)

    def test_execute_does_not_leak_stale_result(self):
        first = self.bridge._op_execute({"code": "result = 123"})
        second = self.bridge._op_execute({"code": "value = 456"})
        self.assertEqual(123, first["return_value"])
        self.assertIsNone(second["return_value"])

    def test_involute_gear_profile_has_expected_standard_dimensions(self):
        outer, inner, dimensions = self.remote_ops._involute_gear_profile(
            2.0, 20, 20.0, 10.0, 10, 4
        )
        self.assertGreater(len(outer), 400)
        self.assertEqual(40, len(inner))
        self.assertAlmostEqual(40.0, dimensions["pitch_diameter"], places=9)
        self.assertAlmostEqual(44.0, dimensions["outside_diameter"], places=9)
        self.assertAlmostEqual(35.0, dimensions["root_diameter"], places=9)
        self.assertAlmostEqual(10.0, dimensions["bore_diameter"], places=9)
        self.assertAlmostEqual(
            math.pi, dimensions["pitch_tooth_thickness"], places=9
        )
        self.assertLess(
            dimensions["outside_tooth_thickness"],
            dimensions["pitch_tooth_thickness"],
        )
        self.assertLess(
            dimensions["pitch_tooth_thickness"],
            dimensions["root_tooth_thickness"],
        )
        self.assertTrue(dimensions["tooth_thickness_decreases_outward"])
        self.assertAlmostEqual(
            44.0,
            2.0 * max(math.hypot(point[0], point[1]) for point in outer),
            places=9,
        )

    def test_principal_sketch_planes_have_orthogonal_axes(self):
        for plane_name in ("XY", "XZ", "YZ"):
            returned_name, axes = self.remote_ops._principal_plane(plane_name)
            self.assertEqual(plane_name, returned_name)
            u_axis, v_axis, normal = axes
            self.assertAlmostEqual(0.0, sum(a * b for a, b in zip(u_axis, v_axis)))
            self.assertAlmostEqual(0.0, sum(a * b for a, b in zip(u_axis, normal)))
            self.assertAlmostEqual(0.0, sum(a * b for a, b in zip(v_axis, normal)))

    def test_principal_sketch_plane_rejects_unknown_plane(self):
        with self.assertRaisesRegex(ValueError, "XY, XZ, or YZ"):
            self.remote_ops._principal_plane("custom")

    def test_stable_topology_id_is_deterministic_for_mapping_order(self):
        first = self.remote_ops._stable_topology_id(
            "edge", {"length": 12.5, "direction": [1.0, 0.0, 0.0]}
        )
        second = self.remote_ops._stable_topology_id(
            "edge", {"direction": [1.0, 0.0, 0.0], "length": 12.5}
        )
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("edge:"))

    def test_direction_match_ignores_edge_orientation_by_default(self):
        self.assertTrue(
            self.remote_ops._direction_matches(
                [1.0, 0.0, 0.0], [-1.0, 0.0, 0.0], 0.1, False
            )
        )
        self.assertFalse(
            self.remote_ops._direction_matches(
                [1.0, 0.0, 0.0], [-1.0, 0.0, 0.0], 0.1, True
            )
        )

    def test_cam_object_names_reject_paths_and_control_characters(self):
        self.assertEqual("T01_END_MILL", self.remote_ops._cam_safe_name("name", " T01_END_MILL "))
        for unsafe in ("../post", r"C:\\private\\post", "bad\nname"):
            with self.assertRaises(ValueError):
                self.remote_ops._cam_safe_name("name", unsafe)

    def test_cam_blank_offsets_are_non_negative_and_overrideable(self):
        offsets = self.remote_ops._cam_offsets(
            {"blank_offset": 2.0, "blank_offsets": {"positive_z": 5.0}}
        )
        self.assertEqual(2.0, offsets["negative_x"])
        self.assertEqual(5.0, offsets["positive_z"])
        with self.assertRaisesRegex(ValueError, "must not be negative"):
            self.remote_ops._cam_offsets({"blank_offset": -0.1})

    def test_cam_template_status_is_explicitly_named(self):
        setup = types.SimpleNamespace(GetTemplateStatus=lambda _obj: (True, False))
        status = self.remote_ops._cam_template_status(setup, object())
        self.assertEqual(
            {"use_as_template": True, "create_with_parent": False}, status
        )

    def test_cam_feed_configuration_disables_inheritance(self):
        def value():
            return types.SimpleNamespace(
                InheritanceStatus=True, Value=0.0, Unit=None
            )

        feeds = types.SimpleNamespace(
            SpindleRpmToggle=0,
            SpindleRpmBuilder=value(),
            FeedCutBuilder=value(),
            FeedApproachBuilder=value(),
            FeedRetractBuilder=value(),
        )
        builder = types.SimpleNamespace(FeedsBuilder=feeds)
        cam = types.SimpleNamespace(
            FeedRateUnit=types.SimpleNamespace(PerMinute="per_minute")
        )
        configured = self.remote_ops._cam_configure_feeds(
            cam,
            builder,
            {"spindle_rpm": 2500.0, "cut_feed": 800.0},
        )
        self.assertEqual(1, feeds.SpindleRpmToggle)
        self.assertFalse(feeds.SpindleRpmBuilder.InheritanceStatus)
        self.assertEqual(2500.0, feeds.SpindleRpmBuilder.Value)
        self.assertFalse(feeds.FeedCutBuilder.InheritanceStatus)
        self.assertEqual(800.0, feeds.FeedCutBuilder.Value)
        self.assertEqual("per_minute", feeds.FeedCutBuilder.Unit)
        self.assertEqual(
            {"spindle_rpm": 2500.0, "cut_feed": 800.0}, configured
        )
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            self.remote_ops._cam_configure_feeds(
                cam, builder, {"cut_feed": 0.0}
            )

    def test_machine_axis_matching_accepts_numbered_axis_names(self):
        axes = ["X1", "Y1", "Z1", "B", "C1"]
        for required in ("X", "Y", "Z", "B", "C"):
            self.assertTrue(
                self.remote_ops._machine_axis_matches(axes, required)
            )
        self.assertFalse(self.remote_ops._machine_axis_matches(axes, "A"))

    def test_machine_library_catalog_returns_names_without_paths(self):
        class FakeLibraryBuilder:
            def __init__(self):
                self.destroyed = False

            def GetAllMachineNames(self):
                return ["sim05_mill_5ax_tnc", "private_machine"]

            def Destroy(self):
                self.destroyed = True

        library_builder = FakeLibraryBuilder()
        kinematic = types.SimpleNamespace(
            CreateMachineLibraryBuilder=lambda: library_builder
        )
        result = self.remote_ops._machine_library_catalog(
            kinematic, "5ax", 10
        )
        self.assertEqual(["sim05_mill_5ax_tnc"], result["matching_librefs"])
        self.assertTrue(result["paths_redacted"])
        self.assertTrue(library_builder.destroyed)
        self.assertNotIn("part_file_path", json.dumps(result))
        with self.assertRaisesRegex(ValueError, "not a path"):
            self.remote_ops._machine_library_catalog(
                kinematic, r"C:\\machine", 10
            )

    def test_machine_source_profile_uses_local_alias_and_redacts_path(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "private_machine.prt"
            source.write_bytes(b"NX")
            config = Path(folder) / "machine_sources.local"
            config.write_text(
                json.dumps(
                    {
                        "profiles": {
                            "five_axis_test": {
                                "source_part": str(source),
                                "expected_axes": ["X", "Y", "Z", "B", "C"],
                                "expected_controller": "TNC 640",
                                "machine_libref": "five_axis_test",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            profile = self.remote_ops._machine_source_profile(
                "five_axis_test", str(config)
            )
            self.assertEqual(str(source), profile["source_part"])
            self.assertTrue(profile["public"]["source_path_redacted"])
            self.assertNotIn(str(source.parent), json.dumps(profile["public"]))
            self.assertEqual(
                ["X", "Y", "Z", "B", "C"], profile["expected_axes"]
            )

    def test_machine_source_profile_rejects_direct_path_as_alias(self):
        with self.assertRaisesRegex(ValueError, "not a path"):
            self.remote_ops._machine_source_profile(r"C:\\private\\machine.prt")

    def test_machine_kinematic_plan_parses_axes_without_returning_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "machine.prt"
            source.write_bytes(b"NX")
            for name in ("base.stl", "x.stl", "y.stl", "z.stl", "b.stl", "c.stl"):
                (root / name).write_bytes(b"solid test\nendsolid test\n")
            definition = root / "machine.mch"
            definition.write_text(
                """<VcMachine>
                <Component Name="Base" Type="base"><Attach/><Position X="0" Y="0" Z="0"/><STL><File>base.stl</File></STL></Component>
                <Component Name="X" Type="linear"><Attach>Base</Attach><Position X="1" Y="0" Z="0"/><Link Axis="X" Register="X"><TlRecord TlMin="-1" TlMax="2"/></Link><STL><File>x.stl</File></STL></Component>
                <Component Name="Y" Type="linear"><Attach>X</Attach><Position X="0" Y="2" Z="0"/><Link Axis="Y" Register="Y"><TlRecord TlMin="-2" TlMax="3"/></Link><STL><File>y.stl</File></STL></Component>
                <Component Name="Z" Type="linear"><Attach>Y</Attach><Position X="0" Y="0" Z="3"/><Link Axis="Z" Register="Z"><TlRecord TlMin="-3" TlMax="4"/></Link><STL><File>z.stl</File></STL></Component>
                <Component Name="B" Type="rotary"><Attach>Base</Attach><Position X="0" Y="0" Z="0"/><Link Axis="Y" Register="B"><TlRecord TlMin="-60" TlMax="120"/></Link><STL><File>b.stl</File></STL></Component>
                <Component Name="C" Type="rotary"><Attach>B</Attach><Position X="0" Y="0" Z="0"/><Link Axis="Z" Register="C"><TlRecord TlMin="0" TlMax="360" TlIgnore="on"/></Link><STL><File>c.stl</File></STL></Component>
                </VcMachine>""",
                encoding="utf-8",
            )
            config = root / "machine_sources.local"
            config.write_text(
                json.dumps(
                    {
                        "profiles": {
                            "five_axis_test": {
                                "source_part": str(source),
                                "expected_axes": ["X", "Y", "Z", "B", "C"],
                                "machine_libref": "five_axis_test",
                                "kinematic_definition": str(definition),
                                "geometry_root": str(root),
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            profile = self.remote_ops._machine_source_profile(
                "five_axis_test", str(config)
            )
            plan = self.remote_ops._machine_kinematic_plan(profile)
            self.assertTrue(plan["machine_kit_build_ready"])
            self.assertEqual(["X", "Y", "Z", "B", "C"], plan["axis_names"])
            self.assertEqual(6, plan["component_count"])
            self.assertTrue(plan["paths_redacted"])
            self.assertNotIn(str(root), json.dumps(plan))
            c_axis = next(item for item in plan["components"] if item["name"] == "C")
            self.assertTrue(c_axis["axis"]["unlimited"])
            self.assertEqual(
                ["Base", "X", "Y", "Z", "B", "C"], plan["build_sequence"]
            )
            self.assertTrue(
                all(
                    geometry["direct_import_supported"]
                    for component in plan["components"]
                    for geometry in component["geometry"]
                )
            )

    def test_machine_kinematic_plan_resolves_oem_machine_reference_to_spindle(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "machine.prt"
            source.write_bytes(b"NX")
            definition = root / "machine.mch"
            definition.write_text(
                """<VcMachine>
                <Table Name="Machine Reference Location"><Row><System>1</System><Value>-1</Value><Value>-2</Value><Value>-3</Value><Value>0</Value></Row></Table>
                <Component Name="Base" Type="base"><Attach/><Position X="0" Y="0" Z="0"/></Component>
                <Component Name="X" Type="linear"><Attach>Base</Attach><Position X="1" Y="0" Z="0"/><Link Axis="X" Register="X"><TlRecord TlMin="-10" TlMax="0.1"/></Link></Component>
                <Component Name="Y" Type="linear"><Attach>X</Attach><Position X="0" Y="2" Z="0"/><Link Axis="Y" Register="Y"><TlRecord TlMin="-10" TlMax="0.1"/></Link></Component>
                <Component Name="Z" Type="linear"><Attach>Y</Attach><Position X="0" Y="0" Z="3"/><Link Axis="Z" Register="Z"><TlRecord TlMin="-10" TlMax="0.1"/></Link></Component>
                <Component Name="Spindle" Type="spindle"><Attach>Z</Attach><Position X="0" Y="0" Z="0"/><Link Axis="Z" Register="S"/></Component>
                <Component Name="Tool" Type="tool"><Attach>Spindle</Attach><Position X="0" Y="0" Z="0"/></Component>
                </VcMachine>""",
                encoding="utf-8",
            )
            profile = {
                "name": "test",
                "source_part": str(source),
                "expected_axes": ["X", "Y", "Z"],
                "expected_controller": None,
                "machine_libref": None,
                "kinematic_definition": str(definition),
                "geometry_root": str(root),
                "public": {"name": "test", "source_path_redacted": True},
            }
            plan = self.remote_ops._machine_kinematic_plan(profile)
            self.assertTrue(plan["machine_kit_build_ready"])
            self.assertEqual(
                [-1.0, -2.0, -3.0],
                plan["machine_reference_location"]["linear_axis_values"],
            )
            self.assertEqual(
                [1.0, 2.0, 3.0], plan["coordinate_frame"]["machine_zero_origin"]
            )
            self.assertEqual(
                plan["coordinate_frame"]["machine_zero_origin"],
                plan["coordinate_frame"]["spindle_origin"],
            )
            self.assertTrue(
                plan["coordinate_frame"]["reference_consistent_with_spindle"]
            )

    def test_machine_kinematic_plan_blocks_inconsistent_machine_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "machine.prt"
            source.write_bytes(b"NX")
            definition = root / "machine.mch"
            definition.write_text(
                """<VcMachine>
                <Table Name="Machine Reference Location"><Row><System>1</System><Value>-9</Value><Value>-2</Value><Value>-3</Value></Row></Table>
                <Component Name="Base" Type="base"><Attach/><Position X="0" Y="0" Z="0"/></Component>
                <Component Name="Spindle" Type="spindle"><Attach>Base</Attach><Position X="1" Y="2" Z="3"/><Link Axis="Z" Register="S"/></Component>
                </VcMachine>""",
                encoding="utf-8",
            )
            profile = {
                "name": "test",
                "source_part": str(source),
                "expected_axes": [],
                "expected_controller": None,
                "machine_libref": None,
                "kinematic_definition": str(definition),
                "geometry_root": str(root),
                "public": {"name": "test", "source_path_redacted": True},
            }
            plan = self.remote_ops._machine_kinematic_plan(profile)
            self.assertFalse(plan["machine_kit_build_ready"])
            self.assertIn(
                "machine_reference_location_inconsistent", plan["blockers"]
            )

    def test_machine_kinematic_plan_blocks_nonidentity_geometry_transform(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "machine.prt"
            source.write_bytes(b"NX")
            (root / "base.stl").write_bytes(b"solid test\nendsolid test\n")
            definition = root / "machine.mch"
            definition.write_text(
                """<VcMachine><Component Name="Base" Type="base"><Attach/><Position X="0" Y="0" Z="0"/><STL><File>base.stl</File><Matrix><MatrixOrigin X="1" Y="0" Z="0"/><MatrixXAxis X="1" Y="0" Z="0"/><MatrixYAxis X="0" Y="1" Z="0"/><MatrixZAxis X="0" Y="0" Z="1"/></Matrix></STL></Component></VcMachine>""",
                encoding="utf-8",
            )
            profile = {
                "name": "test",
                "source_part": str(source),
                "expected_axes": [],
                "expected_controller": None,
                "machine_libref": None,
                "kinematic_definition": str(definition),
                "geometry_root": str(root),
                "public": {"name": "test", "source_path_redacted": True},
            }
            plan = self.remote_ops._machine_kinematic_plan(profile)
            self.assertFalse(plan["machine_kit_build_ready"])
            self.assertIn(
                "component_geometry_transform_not_supported", plan["blockers"]
            )
            self.assertEqual(
                ["base.stl"], plan["unsupported_transformed_geometry_file_names"]
            )

    def test_machine_kinematic_plan_parses_oem_collision_pairs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "machine.prt"
            source.write_bytes(b"NX")
            definition = root / "machine.mch"
            definition.write_text(
                """<VcMachine><Collision>
                <Between Sub1="off" Sub2="on" Tol="2.5"><Component>Z</Component><Component>C</Component></Between>
                <Between Sub1="off" Sub2="off" Tol="1.25"><Component>Z</Component><Component>B</Component></Between>
                </Collision>
                <Component Name="Base" Type="base"><Attach/><Position X="0" Y="0" Z="0"/></Component>
                <Component Name="Z" Type="linear"><Attach>Base</Attach><Position X="0" Y="0" Z="500"/><Link Axis="Z" Register="Z"><TlRecord TlMin="-400" TlMax="0"/></Link></Component>
                <Component Name="B" Type="rotary"><Attach>Base</Attach><Position X="0" Y="0" Z="0"/><Link Axis="Y" Register="B"><TlRecord TlMin="-60" TlMax="120"/></Link></Component>
                <Component Name="C" Type="rotary"><Attach>B</Attach><Position X="0" Y="0" Z="0"/><Link Axis="Z" Register="C"><TlRecord TlMin="0" TlMax="360" TlIgnore="on"/></Link></Component>
                </VcMachine>""",
                encoding="utf-8",
            )
            profile = {
                "name": "test",
                "source_part": str(source),
                "expected_axes": ["Z", "B", "C"],
                "expected_controller": None,
                "machine_libref": None,
                "kinematic_definition": str(definition),
                "geometry_root": str(root),
                "public": {"name": "test", "source_path_redacted": True},
            }
            plan = self.remote_ops._machine_kinematic_plan(profile)
            self.assertEqual(2, plan["collision_pair_count"])
            self.assertEqual(2.5, plan["collision_pairs"][0]["clearance"])
            self.assertTrue(
                plan["collision_pairs"][0]["include_second_subcomponents"]
            )
            mapped = self.remote_ops._machine_oem_collision_configuration(plan)
            self.assertEqual("Z_SLIDE", mapped["pairs"][0]["first_name"])
            self.assertEqual("C_SLIDE", mapped["pairs"][0]["second_name"])
            self.assertEqual("B_SLIDE", mapped["pairs"][1]["second_name"])
            self.assertTrue(
                all(item["source"] == "oem_machine_definition" for item in mapped["pairs"])
            )

    def test_machine_build_workspace_is_copy_only_and_confirmation_gated(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.prt"
            source.write_bytes(b"NX machine source")
            profile = {
                "name": "five_axis_test",
                "source_part": str(source),
                "expected_axes": ["X", "Y", "Z", "B", "C"],
                "expected_controller": "TNC 640",
                "machine_libref": "five_axis_test",
                "kinematic_definition": str(root / "machine.mch"),
                "geometry_root": str(root),
                "public": {
                    "name": "five_axis_test",
                    "source_file_name": "source.prt",
                    "source_path_redacted": True,
                },
            }
            plan = {
                "machine_kit_build_ready": True,
                "blockers": [],
                "component_count": 9,
                "axis_names": ["X", "Y", "Z", "B", "C"],
            }
            old_workspace = self.remote_ops.WORKSPACE
            old_profile = self.remote_ops._machine_source_profile
            old_plan = self.remote_ops._machine_kinematic_plan
            self.remote_ops.WORKSPACE = str(root / "workspace")
            self.remote_ops._machine_source_profile = lambda _name: profile
            self.remote_ops._machine_kinematic_plan = lambda _profile: plan
            try:
                dry = self.remote_ops._op_create_machine_build_workspace(
                    {
                        "source_profile": "five_axis_test",
                        "workspace_file_name": "build.prt",
                        "dry_run": True,
                    }
                )
                target = root / "workspace" / "machine_builds" / "build.prt"
                self.assertFalse(target.exists())
                self.assertTrue(dry["nx_display_unchanged"])
                self.assertTrue(dry["paths_redacted"])
                with self.assertRaisesRegex(PermissionError, "confirmation"):
                    self.remote_ops._op_create_machine_build_workspace(
                        {
                            "source_profile": "five_axis_test",
                            "workspace_file_name": "build.prt",
                            "dry_run": False,
                        }
                    )
                committed = self.remote_ops._op_create_machine_build_workspace(
                    {
                        "source_profile": "five_axis_test",
                        "workspace_file_name": "build.prt",
                        "dry_run": False,
                        "confirmation": "CREATE_MACHINE_BUILD_WORKSPACE",
                    }
                )
                self.assertTrue(target.exists())
                self.assertEqual(source.read_bytes(), target.read_bytes())
                self.assertTrue(Path(str(target) + ".nxmcp.json").exists())
                self.assertTrue(committed["source_unchanged"])
                self.assertNotIn(str(root), json.dumps(committed))
                activation = self.remote_ops._op_activate_machine_build_workspace(
                    {
                        "workspace_file_name": "build.prt",
                        "recovery_token": committed["recovery_token"],
                        "preserve_current": True,
                        "dry_run": True,
                    }
                )
                self.assertTrue(activation["preserve_current"])
                self.assertFalse(activation["changed"])
            finally:
                self.remote_ops.WORKSPACE = old_workspace
                self.remote_ops._machine_source_profile = old_profile
                self.remote_ops._machine_kinematic_plan = old_plan

    def test_machine_mutation_confirmations_are_distinct(self):
        confirmations = {
            self.remote_ops._MACHINE_WORKSPACE_CONFIRMATION,
            self.remote_ops._SMART_MACHINE_KIT_WORKSPACE_CONFIRMATION,
            self.remote_ops._MACHINE_WORKSPACE_ACTIVATE_CONFIRMATION,
            self.remote_ops._MACHINE_WORKSPACE_RESTORE_CONFIRMATION,
            self.remote_ops._MACHINE_GEOMETRY_IMPORT_CONFIRMATION,
            self.remote_ops._MACHINE_KINEMATICS_BUILD_CONFIRMATION,
            self.remote_ops._MACHINE_AXIS_PROBE_CONFIRMATION,
            self.remote_ops._MACHINE_JUNCTION_RETARGET_CONFIRMATION,
            self.remote_ops._MACHINE_KIT_EXPORT_CONFIRMATION,
            self.remote_ops._MACHINE_KIT_IMPORT_CONFIRMATION,
            self.remote_ops._MACHINE_STATIC_COLLISION_CONFIRMATION,
            self.remote_ops._MACHINE_KIT_CAM_BIND_CONFIRMATION,
        }
        self.assertEqual(12, len(confirmations))
        self.assertEqual(
            "BUILD_MACHINE_KINEMATICS",
            self.remote_ops._MACHINE_KINEMATICS_BUILD_CONFIRMATION,
        )
        self.assertEqual(
            "PROBE_MACHINE_AXIS_MOTION",
            self.remote_ops._MACHINE_AXIS_PROBE_CONFIRMATION,
        )

    def test_cam_tool_sections_validate_and_preserve_explicit_profile(self):
        sections = self.remote_ops._normalize_cam_tool_sections(
            "holder_sections",
            [
                {
                    "lower_diameter": 20,
                    "upper_diameter": 32,
                    "length": 20,
                    "corner_radius": 1,
                }
            ],
        )
        self.assertEqual(20.0, sections[0]["lower_diameter"])
        self.assertEqual(32.0, sections[0]["upper_diameter"])
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            self.remote_ops._normalize_cam_tool_sections(
                "holder_sections",
                [{"lower_diameter": 0, "upper_diameter": 10, "length": 20}],
            )
        with self.assertRaisesRegex(ValueError, "corner_radius"):
            self.remote_ops._normalize_cam_tool_sections(
                "holder_sections",
                [
                    {
                        "lower_diameter": 10,
                        "upper_diameter": 10,
                        "length": 20,
                        "corner_radius": 6,
                    }
                ],
            )

    def test_machine_path_is_within_rejects_a_different_windows_drive(self):
        self.assertFalse(
            self.remote_ops._machine_path_is_within(
                r"C:\machine_library", r"E:\workspace\machine.mtk"
            )
        )

    def test_protected_simulation_wrapper_uses_readiness_selection(self):
        readiness = {
            "machine_simulation_ready": True,
            "blockers": [],
            "selection": {"operation_names": ["OPERATION_1"]},
            "machine": {"libref": "machine_ref"},
        }
        calls = []
        original_readiness = self.remote_ops._machine_simulation_readiness
        original_proxy = self.remote_ops._op_simulation_runtime_proxy
        original_work_part = self.remote_ops._work_part
        try:
            self.remote_ops._machine_simulation_readiness = lambda _params: readiness
            self.remote_ops._op_simulation_runtime_proxy = lambda payload: (
                calls.append(payload) or {"simulation_prepared": True}
            )
            self.remote_ops._work_part = lambda: types.SimpleNamespace(Leaf="part")
            result = self.remote_ops._op_start_machine_simulation_with_collision_stop(
                {"play_immediately": False}
            )
        finally:
            self.remote_ops._machine_simulation_readiness = original_readiness
            self.remote_ops._op_simulation_runtime_proxy = original_proxy
            self.remote_ops._work_part = original_work_part
        self.assertTrue(result["readiness_passed"])
        self.assertEqual(
            ["OPERATION_1"], calls[0]["runtime_params"]["operation_names"]
        )

    def test_machine_kit_manifest_is_retargeted_and_sanitized(self):
        manifest = b"""<?xml version='1.0' encoding='utf-8'?>
        <machine_tool_kit>
          <name>reference</name>
          <meta_data><provider>private-user</provider><sold_to>private-license</sold_to></meta_data>
          <database_entry>
            <libref>reference</libref><Type>MDM0101</Type>
            <Description>Reference</Description><Control>Old</Control>
            <Manufacturer>Example</Manufacturer><config_file>old.dat</config_file>
            <rigidity>1.0</rigidity><part_file_path>old</part_file_path>
          </database_entry>
          <content><folder name='reference' origin='Main'>
            <folder name='graphics' origin='Graphics'>
              <file name='reference.prt' origin='MachineLibrary'/>
            </folder>
            <folder name='cse_driver' origin='CSE'>
              <file name='reference.MCF' origin='DatFile'/>
            </folder>
            <folder name='postprocessor' origin='Postprocessor'>
              <file name='reference.tcl' origin='DatFile'/>
            </folder>
          </folder></content>
        </machine_tool_kit>"""
        sanitized, old_root = self.remote_ops._machine_kit_sanitized_manifest(
            manifest,
            "mikron_mill_e500u_tnc640",
            "mikron_mill_e500u_tnc640.prt",
        )
        text = sanitized.decode("utf-8")
        self.assertEqual("reference", old_root)
        self.assertIn("mikron_mill_e500u_tnc640.prt", text)
        self.assertIn("reference.MCF", text)
        self.assertIn("reference.tcl", text)
        self.assertNotIn("private-user", text)
        self.assertNotIn("private-license", text)
        self.assertNotIn("sold_to", text.lower())

    def test_machine_kit_repackage_contains_part_cse_and_post(self):
        import zipfile

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reference = root / "reference.mtk"
            output = root / "output.mtk"
            part = root / "machine.prt"
            part.write_bytes(b"NX-PART")
            manifest = b"""<machine_tool_kit><name>reference</name>
              <meta_data><provider>private</provider><sold_to>secret</sold_to></meta_data>
              <database_entry><libref>reference</libref><Type>MDM0101</Type>
              <Description>Reference</Description><Control>Old</Control>
              <Manufacturer>Example</Manufacturer><config_file>old.dat</config_file>
              <rigidity>1.0</rigidity><part_file_path>old</part_file_path></database_entry>
              <content><folder name='reference' origin='Main'>
                <folder name='graphics' origin='Graphics'><file name='old.prt' origin='MachineLibrary'/></folder>
                <folder name='cse_driver' origin='CSE'><file name='reference.MCF' origin='DatFile'/></folder>
                <folder name='postprocessor' origin='Postprocessor'><file name='reference.tcl' origin='DatFile'/></folder>
              </folder></content></machine_tool_kit>"""
            with zipfile.ZipFile(reference, "w") as archive:
                archive.writestr("kit_information.xml", manifest)
                archive.writestr("reference/graphics/old.prt", b"OLD")
                archive.writestr("reference/cse_driver/reference.MCF", b"CSE")
                archive.writestr("reference/postprocessor/reference.tcl", b"POST")
                for index in range(8):
                    archive.writestr(
                        "reference/postprocessor/resource_%02d.dat" % index,
                        b"RESOURCE",
                    )
            record = self.remote_ops._machine_kit_repackage_reference(
                str(reference), str(output), str(part), "mikron_test"
            )
            self.assertGreaterEqual(record["member_count"], 10)
            self.assertTrue(record["has_cse_driver"])
            self.assertTrue(record["has_postprocessor"])
            self.assertTrue(
                self.remote_ops._machine_kit_is_verified_reference_container(
                    str(output)
                )
            )
            with zipfile.ZipFile(output, "r") as archive:
                self.assertEqual(
                    b"NX-PART",
                    archive.read("mikron_test/graphics/mikron_test.prt"),
                )
                self.assertNotIn(
                    b"sold_to", archive.read("kit_information.xml").lower()
                )
            part.write_bytes(b"NX-PART-UPDATED")
            refreshed = self.remote_ops._machine_kit_repackage_reference(
                str(output), str(output), str(part), "mikron_test"
            )
            self.assertEqual(record["member_count"], refreshed["member_count"])
            with zipfile.ZipFile(output, "r") as archive:
                self.assertEqual(
                    b"NX-PART-UPDATED",
                    archive.read("mikron_test/graphics/mikron_test.prt"),
                )

            unique_graphics = self.remote_ops._machine_kit_repackage_reference(
                str(output),
                str(output),
                str(part),
                "mikron_test",
                graphics_file_name="mikron_test_refzero_v17.prt",
            )
            self.assertEqual(
                "mikron_test_refzero_v17.prt", unique_graphics["graphics_part"]
            )
            with zipfile.ZipFile(output, "r") as archive:
                self.assertEqual(
                    b"NX-PART-UPDATED",
                    archive.read(
                        "mikron_test/graphics/mikron_test_refzero_v17.prt"
                    ),
                )
                manifest_text = archive.read("kit_information.xml").decode("utf-8")
                self.assertIn(
                    "mikron_test/graphics/mikron_test_refzero_v17",
                    manifest_text,
                )

    def test_machine_system_classes_match_supported_nx_machine_semantics(self):
        self.assertEqual(
            {
                "BASE": "Machine",
                "SPINDLE": "Turret",
                "TOOL": "PocketOnHead",
                "ATTACH": "SetupElement",
            },
            self.remote_ops._MACHINE_REQUIRED_SYSTEM_CLASSES,
        )

    def test_machine_faceted_body_collection_supports_nx_iterable_shape(self):
        bodies = [object(), object()]
        work = types.SimpleNamespace(FacetedBodies=bodies)
        self.assertEqual(bodies, self.remote_ops._machine_faceted_bodies(work))

    def test_collision_stop_options_are_forced_on(self):
        enum = types.SimpleNamespace
        cam = types.SimpleNamespace(
            SimulationOptionsBuilder=types.SimpleNamespace(
                SimulationDisplayMode=enum(All="all"),
                Accuracy=enum(Fine="fine_accuracy"),
                Stationary=enum(Part="part"),
                IpwUpdateMode=enum(MotionBased="motion_update"),
                Resolution=enum(Fine="fine_resolution"),
                StockType=enum(Automatic="automatic"),
            )
        )
        options = types.SimpleNamespace()
        result = self.remote_ops._configure_collision_stop_options(
            cam, options, {"material_removal": True}
        )
        self.assertTrue(options.EnableMachineCollision)
        self.assertTrue(options.CheckLimitViolation)
        self.assertTrue(options.CheckToolHolderIpw)
        self.assertTrue(options.CheckToolHolderGougeCheck)
        self.assertTrue(options.StopOnCollision)
        self.assertTrue(options.StopOnLimitViolation)
        self.assertTrue(options.EnableMaterialRemoval)
        self.assertEqual("motion_update", options.IpwUpdate)
        self.assertTrue(result["collision_detection"])
        self.assertEqual(
            "stop_on_collision", result["rapid_through_ipw_stop_source"]
        )

    def test_existing_machine_replacement_confirmation_is_exact(self):
        self.assertEqual(
            "REPLACE_EXISTING_MACHINE_TOOL",
            self.remote_ops._MACHINE_REPLACE_CONFIRMATION,
        )

    def test_cam_postprocess_requires_both_safety_gates(self):
        old_value = os.environ.pop("NX_MCP_ENABLE_POSTPROCESS", None)
        try:
            with self.assertRaises(PermissionError):
                self.remote_ops._cam_require_post_authorization(
                    {"confirmation": self.remote_ops._CAM_POST_CONFIRMATION}
                )
            os.environ["NX_MCP_ENABLE_POSTPROCESS"] = "1"
            with self.assertRaises(PermissionError):
                self.remote_ops._cam_require_post_authorization(
                    {"confirmation": "not-confirmed"}
                )
            self.remote_ops._cam_require_post_authorization(
                {"confirmation": self.remote_ops._CAM_POST_CONFIRMATION}
            )
        finally:
            if old_value is None:
                os.environ.pop("NX_MCP_ENABLE_POSTPROCESS", None)
            else:
                os.environ["NX_MCP_ENABLE_POSTPROCESS"] = old_value

    def test_public_machine_profile_contains_no_private_paths_or_secret_fields(self):
        profile_path = (
            Path(__file__).resolve().parents[1]
            / "config"
            / "machine_profiles"
            / "mikron_mill_e_500u_tnc640_public.json"
        )
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        encoded = json.dumps(profile, ensure_ascii=False).lower()
        self.assertEqual("public_machine_specification_only", profile["source_classification"])
        self.assertFalse(profile["safety"]["vendor_assets_embedded"])
        self.assertFalse(profile["safety"]["postprocess_enabled_by_default"])
        for forbidden in ("serial", "license_key", "password", "onedrive", "e:\\\\"):
            if forbidden == "serial":
                self.assertNotIn('"serial"', encoded)
            else:
                self.assertNotIn(forbidden, encoded)


if __name__ == "__main__":
    unittest.main()
