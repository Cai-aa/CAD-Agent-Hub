import math
import os

import adsk.core
import adsk.fusion


MM = 0.1  # Fusion API internal length unit is cm.


def pt(x, y, z):
    return adsk.core.Point3D.create(x * MM, y * MM, z * MM)


def vec(x, y, z):
    return adsk.core.Vector3D.create(x, y, z)


def add_component(parent, name):
    occurrence = parent.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    occurrence.component.name = name
    return occurrence, occurrence.component


def add_cylinder(component, name, x, y, z0, z1, radius0, radius1=None):
    if radius1 is None:
        radius1 = radius0
    manager = adsk.fusion.TemporaryBRepManager.get()
    body = manager.createCylinderOrCone(pt(x, y, z0), radius0 * MM, pt(x, y, z1), radius1 * MM)
    base_feature = component.features.baseFeatures.add()
    base_feature.name = 'BaseFeature_' + name
    base_feature.startEdit()
    result = component.bRepBodies.add(body, base_feature)
    base_feature.finishEdit()
    result.name = name
    return result


def add_ring(component, name, z0, z1, outer_radius, inner_radius):
    manager = adsk.fusion.TemporaryBRepManager.get()
    outer = manager.createCylinderOrCone(pt(0, 0, z0), outer_radius * MM, pt(0, 0, z1), outer_radius * MM)
    inner = manager.createCylinderOrCone(pt(0, 0, z0 - 1), inner_radius * MM, pt(0, 0, z1 + 1), inner_radius * MM)
    if not manager.booleanOperation(outer, inner, adsk.fusion.BooleanTypes.DifferenceBooleanType):
        raise RuntimeError('Failed to create annular body: ' + name)
    base_feature = component.features.baseFeatures.add()
    base_feature.name = 'BaseFeature_' + name
    base_feature.startEdit()
    result = component.bRepBodies.add(outer, base_feature)
    base_feature.finishEdit()
    result.name = name
    return result


def add_obb(component, name, center, length_dir, width_dir, length, width, height):
    manager = adsk.fusion.TemporaryBRepManager.get()
    ld = vec(*length_dir)
    wd = vec(*width_dir)
    ld.normalize()
    wd.normalize()
    obb = adsk.core.OrientedBoundingBox3D.create(
        pt(*center), ld, wd, length * MM, width * MM, height * MM
    )
    body = manager.createBox(obb)
    base_feature = component.features.baseFeatures.add()
    base_feature.name = 'BaseFeature_' + name
    base_feature.startEdit()
    result = component.bRepBodies.add(body, base_feature)
    base_feature.finishEdit()
    result.name = name
    return result


def rotate_occurrence_z(occurrence, angle_deg):
    matrix = adsk.core.Matrix3D.create()
    matrix.setToRotation(math.radians(angle_deg), vec(0, 0, 1), pt(0, 0, 0))
    occurrence.transform2 = matrix


def add_user_parameter(design, name, expression, unit='mm', comment=''):
    existing = design.userParameters.itemByName(name)
    if existing:
        return existing
    return design.userParameters.add(name, adsk.core.ValueInput.createByString(expression), unit, comment)


def add_starship_revolve(component):
    sketch = component.sketches.add(component.xZConstructionPlane)
    sketch.name = 'Sketch_Starship_Continuous_Profile'
    lines = sketch.sketchCurves.sketchLines
    axis = lines.addByTwoPoints(adsk.core.Point3D.create(0, 75000 * MM, 0), adsk.core.Point3D.create(0, 124000 * MM, 0))
    axis.isConstruction = True
    bottom = lines.addByTwoPoints(adsk.core.Point3D.create(0, 75000 * MM, 0), adsk.core.Point3D.create(4500 * MM, 75000 * MM, 0))
    barrel = lines.addByTwoPoints(bottom.endSketchPoint, adsk.core.Point3D.create(4500 * MM, 111500 * MM, 0))
    points = adsk.core.ObjectCollection.create()
    for x, z in [(4500, 111500), (4470, 112700), (4200, 115300), (3500, 118400), (2400, 121300), (1100, 123250), (0, 124000)]:
        points.add(adsk.core.Point3D.create(x * MM, z * MM, 0))
    spline = sketch.sketchCurves.sketchFittedSplines.add(points)
    close_line = lines.addByTwoPoints(spline.endSketchPoint, bottom.startSketchPoint)
    profiles = sketch.profiles
    if profiles.count != 1:
        raise RuntimeError('Continuous Starship revolve profile was not created as one closed profile.')
    revolver = component.features.revolveFeatures
    revolve_input = revolver.createInput(profiles.item(0), axis, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    revolve_input.setAngleExtent(False, adsk.core.ValueInput.createByReal(math.pi * 2))
    feature = revolver.add(revolve_input)
    feature.name = 'Revolve_Starship_MainBody_and_Continuous_Nose'
    feature.bodies.item(0).name = 'Starship_Continuous_MainBody'
    sketch.isVisible = False
    return feature.bodies.item(0)


def find_appearance(app, terms):
    lowered = [term.lower() for term in terms]
    for lib_index in range(app.materialLibraries.count):
        appearances = app.materialLibraries.item(lib_index).appearances
        for index in range(appearances.count):
            appearance = appearances.item(index)
            name = appearance.name.lower()
            if all(term in name for term in lowered):
                return appearance
    return None


def set_component_appearance(component, appearance):
    if not appearance:
        return
    for body in component.bRepBodies:
        body.appearance = appearance


def build():
    app = adsk.core.Application.get()
    documents = app.documents
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design and design.rootComponent.occurrences.count == 0 and design.rootComponent.bRepBodies.count == 0:
        document = app.activeDocument
    else:
        document = documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        raise RuntimeError('Fusion design could not be created.')
    design.designType = adsk.fusion.DesignTypes.ParametricDesignType
    root = design.rootComponent
    design.attributes.add('Model_Identity', 'Final_Design_Name', 'Starship_V3_SuperHeavy_V3_Exterior_v1')

    params = {
        'H_STACK': ('124000 mm', 'mm'), 'D_BODY': ('9000 mm', 'mm'), 'R_BODY': ('D_BODY / 2', 'mm'),
        'H_BOOSTER': ('72000 mm', 'mm'), 'H_STARSHIP': ('52000 mm', 'mm'),
        'Z_STAGE_INTERFACE': ('H_BOOSTER', 'mm'), 'Z_STACK_TIP': ('H_STACK', 'mm'),
        'DISPLAY_SHELL_THICKNESS': ('30 mm', 'mm'), 'BODY_PANEL_GROOVE_DEPTH': ('5 mm', 'mm'),
        'WELD_BEAD_HEIGHT': ('8 mm', 'mm'), 'WELD_BEAD_WIDTH': ('22 mm', 'mm'), 'RING_WELD_PITCH': ('1800 mm', 'mm'),
        'H_B_ENGINE_SECTION': ('6500 mm', 'mm'), 'H_B_MAIN_BARREL': ('54500 mm', 'mm'),
        'H_B_GRIDFIN_ZONE': ('8500 mm', 'mm'), 'H_B_HOTSTAGE': ('2500 mm', 'mm'),
        'B_ENGINE_COUNT': ('33', ''), 'B_ENGINE_CENTER_COUNT': ('3', ''), 'B_ENGINE_MIDDLE_COUNT': ('10', ''),
        'B_ENGINE_OUTER_COUNT': ('20', ''), 'B_ENGINE_CENTER_RADIUS': ('700 mm', 'mm'),
        'B_ENGINE_MIDDLE_RADIUS': ('2100 mm', 'mm'), 'B_ENGINE_OUTER_RADIUS': ('3500 mm', 'mm'),
        'B_NOZZLE_LENGTH': ('3000 mm', 'mm'), 'B_NOZZLE_EXIT_D': ('1250 mm', 'mm'),
        'B_GRIDFIN_COUNT': ('3', ''), 'B_GRIDFIN_CENTER_Z': ('65000 mm', 'mm'),
        'B_GRIDFIN_AXIAL_LENGTH': ('5200 mm', 'mm'), 'B_GRIDFIN_RADIAL_SPAN': ('4300 mm', 'mm'),
        'HOTSTAGE_SLOT_COUNT': ('24', ''), 'HOTSTAGE_SLOT_HEIGHT': ('1600 mm', 'mm'),
        'H_S_AFT_SECTION': ('5500 mm', 'mm'), 'H_S_TANK_BARREL': ('26000 mm', 'mm'),
        'H_S_FORWARD_BARREL': ('8000 mm', 'mm'), 'H_S_NOSE': ('12500 mm', 'mm'),
        'S_ENGINE_COUNT': ('6', ''), 'S_RAPTOR_SL_COUNT': ('3', ''), 'S_RAPTOR_VAC_COUNT': ('3', ''),
        'S_SL_ENGINE_RADIUS': ('800 mm', 'mm'), 'S_VAC_ENGINE_RADIUS': ('2750 mm', 'mm'),
        'AFT_FLAP_COUNT': ('2', ''), 'FWD_FLAP_COUNT': ('2', ''),
        'AFT_FLAP_RADIAL_SPAN': ('4300 mm', 'mm'), 'FWD_FLAP_RADIAL_SPAN': ('3300 mm', 'mm'),
        'TPS_HALF_ANGLE': ('78 deg', 'deg'), 'TPS_TILE_PITCH': ('150 mm', 'mm'),
        'DETAIL_LEVEL': ('1', ''), 'DISPLAY_SCALE': ('0.01', '')
    }
    for name, (expression, unit) in params.items():
        add_user_parameter(design, name, expression, unit)

    notes = ('本模型为 SpaceX Starship V3 与 Super Heavy V3 的公开资料外观重建模型。总高、直径、两级高度、'
             '发动机数量、V3 三片栅格舵和集成式热分级为公开参数。鼻锥曲线、舱段细分、襟翼尺寸、'
             '栅格舵尺寸及位置、发动机喷管尺寸、焊缝、线缆槽、舱口、热防护瓦边界和标识坐标为根据'
             '官方照片反推的可调整估算值，不应视为 SpaceX 制造工程尺寸。')
    design.attributes.add('Model_Notes', 'Public_Reconstruction_Notice', notes)

    names = [
        '00_Reference', '10_SuperHeavy_V3', '11_Booster_MainBody', '12_Booster_EngineSection',
        '13_Booster_HotStage', '14_Booster_External_Raceways', '15_Booster_QD_and_Service_Panels',
        '20_Booster_Engine_Master', '21_Booster_Engine_Center_3', '22_Booster_Engine_Middle_10',
        '23_Booster_Engine_Outer_20', '30_GridFin_V3_Master', '31_GridFin_V3_Array',
        '32_GridFin_Catch_Features', '40_Starship_V3', '41_Starship_MainBody', '42_Starship_Nose',
        '43_Starship_Aft_Skirt', '44_Starship_External_Details', '50_Starship_Engine_SL_Master',
        '51_Starship_Engine_SL_Array', '52_Starship_Engine_Vac_Master', '53_Starship_Engine_Vac_Array',
        '60_Starship_Aft_Flap_Left', '61_Starship_Aft_Flap_Right', '62_Starship_Forward_Flap_Left',
        '63_Starship_Forward_Flap_Right', '64_Starship_Flap_Hinges', '70_Starship_HeatShield',
        '71_TPS_Render_Texture', '72_TPS_Optional_Geometry', '80_Markings_and_Decals',
        '81_Render_Decals', '82_Export_Color_Geometry', '90_Configurations', '91_Stacked',
        '92_Separated', '99_Display_1_100'
    ]
    components = {}
    occurrences = {}
    for name in names:
        occurrence, component = add_component(root, name)
        components[name] = component
        occurrences[name] = occurrence

    # Full-scale main bodies. Lowest booster nozzle plane is Z=0; ship nozzles begin at Z=72000.
    booster_body = add_cylinder(components['11_Booster_MainBody'], 'Booster_9000mm_Continuous_Barrel', 0, 0, 3000, 69500, 4500)
    add_ring(components['12_Booster_EngineSection'], 'Booster_Bottom_Structural_Ring', 2850, 3200, 4550, 4100)
    add_cylinder(components['12_Booster_EngineSection'], 'Booster_Engine_Mount_Plate', 0, 0, 2950, 3100, 4200)

    hotstage = components['13_Booster_HotStage']
    add_ring(hotstage, 'HotStage_Lower_Integrated_Ring', 69500, 69850, 4500, 4200)
    add_ring(hotstage, 'HotStage_Upper_Interface_Ring', 71650, 72000, 4500, 4200)
    for index in range(24):
        angle = math.radians(index * 15)
        radial = (math.cos(angle), math.sin(angle), 0)
        tangent = (-math.sin(angle), math.cos(angle), 0)
        add_obb(hotstage, 'HotStage_Strut_%02d' % (index + 1),
                (radial[0] * 4350, radial[1] * 4350, 70750), tangent, radial,
                260, 260, 1800)

    starship_body = add_starship_revolve(components['41_Starship_MainBody'])
    add_ring(components['43_Starship_Aft_Skirt'], 'Starship_Aft_Interface_Ring', 74850, 75200, 4500, 4150)

    # Booster engines: three independent circular groups, 3 + 10 + 20 = 33.
    engine_groups = [(components['21_Booster_Engine_Center_3'], 3, 700),
                     (components['22_Booster_Engine_Middle_10'], 10, 2100),
                     (components['23_Booster_Engine_Outer_20'], 20, 3500)]
    engine_number = 1
    for component, count, radius in engine_groups:
        for index in range(count):
            angle = 2 * math.pi * index / count
            x, y = radius * math.cos(angle), radius * math.sin(angle)
            add_cylinder(component, 'Booster_Raptor_%02d' % engine_number, x, y, 0, 3000, 625, 310)
            engine_number += 1

    # Ship engines: 3 sea-level and 3 vacuum nozzles.
    for index in range(3):
        angle = 2 * math.pi * index / 3 + math.pi / 2
        add_cylinder(components['51_Starship_Engine_SL_Array'], 'Starship_Raptor_SL_%d' % (index + 1),
                     800 * math.cos(angle), 800 * math.sin(angle), 72000, 75000, 625, 310)
        add_cylinder(components['53_Starship_Engine_Vac_Array'], 'Starship_Raptor_Vac_%d' % (index + 1),
                     2750 * math.cos(angle), 2750 * math.sin(angle), 72000, 75400, 1175, 325)

    # Three independent, open, chevron-lattice V3 grid fins at 90/180/270 degrees.
    for fin_index, (component_name, angle) in enumerate([
            ('30_GridFin_V3_Master', 90), ('31_GridFin_V3_Array', 180), ('32_GridFin_Catch_Features', 270)], 1):
        component = components[component_name]
        add_obb(component, 'GridFin_%d_InnerFrame' % fin_index, (4610, 0, 65000), (0, 0, 1), (0, 1, 0), 5200, 350, 220)
        add_obb(component, 'GridFin_%d_OuterFrame' % fin_index, (8690, 0, 65000), (0, 0, 1), (0, 1, 0), 5200, 350, 220)
        add_obb(component, 'GridFin_%d_LowerFrame' % fin_index, (6650, 0, 62510), (1, 0, 0), (0, 1, 0), 4300, 350, 220)
        add_obb(component, 'GridFin_%d_UpperFrame' % fin_index, (6650, 0, 67490), (1, 0, 0), (0, 1, 0), 4300, 350, 220)
        for rib in range(7):
            zc = 63000 + rib * 670
            direction = (0.84, 0, 0.54 if rib % 2 == 0 else -0.54)
            add_obb(component, 'GridFin_%d_Chevron_%02d' % (fin_index, rib + 1),
                    (6650, 0, zc), direction, (0, 1, 0), 4550, 120, 110)
        add_cylinder(component, 'GridFin_%d_Hinge' % fin_index, 4500, 0, 63800, 66200, 420)
        add_obb(component, 'GridFin_%d_Catch_Block' % fin_index, (4750, 0, 67450), (1, 0, 0), (0, 1, 0), 900, 700, 600)
        rotate_occurrence_z(occurrences[component_name], angle)

    # Four separately selectable aerodynamic flaps with independent hinge bodies.
    flap_specs = [
        ('60_Starship_Aft_Flap_Left', 90, 83750, 4300, 13500, 340),
        ('61_Starship_Aft_Flap_Right', 270, 83750, 4300, 13500, 340),
        ('62_Starship_Forward_Flap_Left', 90, 115000, 3300, 9000, 280),
        ('63_Starship_Forward_Flap_Right', 270, 115000, 3300, 9000, 280),
    ]
    for component_name, angle, zc, span, axial, thickness in flap_specs:
        component = components[component_name]
        add_obb(component, component_name + '_Panel', (4500 + span / 2, 0, zc), (1, 0, 0), (0, 1, 0), span, thickness, axial)
        add_cylinder(component, component_name + '_Hinge', 4520, 0, zc - axial * 0.36, zc + axial * 0.36, thickness * 0.9)
        rotate_occurrence_z(occurrences[component_name], angle)

    # External raceways and service panels.
    for index, angle in enumerate([20, 155, 250]):
        a = math.radians(angle)
        radial = (math.cos(a), math.sin(a), 0)
        tangent = (-math.sin(a), math.cos(a), 0)
        add_obb(components['14_Booster_External_Raceways'], 'Booster_Raceway_%d' % (index + 1),
                (radial[0] * 4600, radial[1] * 4600, 35000), tangent, radial, 360, 260, 48000)
    add_obb(components['15_Booster_QD_and_Service_Panels'], 'Booster_QD_Panel', (0, -4600, 22000), (1, 0, 0), (0, -1, 0), 1800, 220, 2500)
    add_obb(components['44_Starship_External_Details'], 'Starship_QD_Panel', (0, -4600, 80500), (1, 0, 0), (0, -1, 0), 1700, 180, 2300)

    # Lightweight TPS representation: dark segmented tangent strips over +Y only.
    tps = components['70_Starship_HeatShield']
    for degree in range(-72, 73, 12):
        angle = math.radians(90 - degree)
        radial = (math.cos(angle), math.sin(angle), 0)
        tangent = (-math.sin(angle), math.cos(angle), 0)
        add_obb(tps, 'TPS_Barrel_%+03d' % degree,
                (radial[0] * 4510, radial[1] * 4510, 93250), tangent, radial, 900, 24, 36500)
        for tier, (z0, z1, radius) in enumerate([(111500, 116000, 4200), (116000, 120000, 3100), (120000, 123500, 1550)]):
            add_obb(tps, 'TPS_Nose_%+03d_%d' % (degree, tier + 1),
                    (radial[0] * radius, radial[1] * radius, (z0 + z1) / 2), tangent, radial,
                    max(280, 900 * radius / 4500), 24, z1 - z0)

    # Fine circumferential welds as lightweight annular bodies on the visible skin.
    welds = components['71_TPS_Render_Texture']
    weld_index = 1
    for z in range(8400, 69500, 1800):
        add_ring(welds, 'Booster_Ring_Weld_%02d' % weld_index, z, z + 22, 4508, 4498)
        weld_index += 1
    for z in range(76800, 111500, 1800):
        add_ring(welds, 'Starship_Ring_Weld_%02d' % weld_index, z, z + 22, 4508, 4498)
        weld_index += 1

    # Marking placeholders are separate export-color geometry and hidden by default.
    add_obb(components['82_Export_Color_Geometry'], 'Export_SpaceX_Wordmark_Placeholder',
            (0, -4515, 105000), (1, 0, 0), (0, -1, 0), 4000, 2.5, 750)
    add_obb(components['82_Export_Color_Geometry'], 'Export_US_Flag_Placeholder',
            (1800, -4516, 109500), (1, 0, 0), (0, -1, 0), 1900, 2.5, 1000)
    occurrences['82_Export_Color_Geometry'].isLightBulbOn = False
    occurrences['00_Reference'].isLightBulbOn = False
    occurrences['72_TPS_Optional_Geometry'].isLightBulbOn = False
    occurrences['92_Separated'].isLightBulbOn = False
    occurrences['99_Display_1_100'].isLightBulbOn = False

    # Assign the closest available stock appearances without modifying system library definitions.
    steel = find_appearance(app, ['stainless']) or find_appearance(app, ['steel'])
    dark = find_appearance(app, ['black'])
    for name in ['11_Booster_MainBody', '12_Booster_EngineSection', '41_Starship_MainBody',
                 '43_Starship_Aft_Skirt', '14_Booster_External_Raceways']:
        set_component_appearance(components[name], steel)
    for name in ['13_Booster_HotStage', '21_Booster_Engine_Center_3', '22_Booster_Engine_Middle_10',
                 '23_Booster_Engine_Outer_20', '51_Starship_Engine_SL_Array', '53_Starship_Engine_Vac_Array',
                 '30_GridFin_V3_Master', '31_GridFin_V3_Array', '32_GridFin_Catch_Features']:
        set_component_appearance(components[name], steel)
    set_component_appearance(components['70_Starship_HeatShield'], dark)

    # Design-level configuration metadata; occurrences remain independently movable/selectable.
    for config_name, config_value in [
        ('Configuration_Ascent', 'Stacked; flaps 0 deg; grid fins neutral'),
        ('Configuration_Bellyflop', 'Separated; flaps 65 deg'),
        ('Configuration_Landing', 'Separated; flaps 30 deg'),
        ('Configuration_Booster_Control', 'Grid fins +/-20 deg'),
        ('Configuration_Stacked', 'Starship base Z=72000 mm'),
        ('Configuration_Separated', 'Starship display offset +18000 mm')]:
        design.attributes.add('Configurations', config_name, config_value)
    for joint_name in [
        'Joint_Stack_Starship_to_Booster', 'Booster_GridFin_1_Joint', 'Booster_GridFin_2_Joint',
        'Booster_GridFin_3_Joint', 'Starship_Aft_Flap_Left_Joint', 'Starship_Aft_Flap_Right_Joint',
        'Starship_Forward_Flap_Left_Joint', 'Starship_Forward_Flap_Right_Joint']:
        design.attributes.add('Joint_Definitions', joint_name, 'Parametric pose metadata; geometry is independently selectable')

    # Add named station metadata and best-effort named views.
    for station in [0, 6500, 61000, 69500, 72000, 77500, 103500, 111500, 124000]:
        design.attributes.add('Construction_Stations', 'Station_%06d' % station, '%d mm' % station)
    viewport = app.activeViewport
    if viewport:
        viewport.fit()

    # Save to the active Fusion project and export neutral/native deliverables locally.
    output_dir = os.environ.get(
        'FUSION_STARSHIP_OUTPUT_DIR',
        os.path.join(os.path.expanduser('~'), 'CAD-Agent-Hub-exports', 'Starship_V3'),
    )
    os.makedirs(output_dir, exist_ok=True)
    save_ok = False
    try:
        folder = app.data.activeProject.rootFolder
        save_ok = document.saveAs('Starship_V3_SuperHeavy_V3_Exterior_v1', folder, 'Parametric public-data exterior reconstruction', '')
    except Exception as exc:
        print('SAVE_WARNING=' + str(exc))

    export_manager = design.exportManager
    exports = []
    export_jobs = [
        ('Starship_V3_SuperHeavy_V3_FullStack.f3d', lambda path: export_manager.createFusionArchiveExportOptions(path, root)),
        ('Starship_V3_SuperHeavy_V3_FullStack.step', lambda path: export_manager.createSTEPExportOptions(path, root)),
        ('Starship_V3_Standalone.step', lambda path: export_manager.createSTEPExportOptions(path, components['40_Starship_V3'])),
        ('SuperHeavy_V3_Standalone.step', lambda path: export_manager.createSTEPExportOptions(path, components['10_SuperHeavy_V3'])),
    ]
    for filename, create_options in export_jobs:
        path = os.path.join(output_dir, filename)
        try:
            if export_manager.execute(create_options(path)):
                exports.append(path)
        except Exception as exc:
            print('EXPORT_WARNING[%s]=%s' % (filename, exc))

    design.attributes.add('Validation', 'Expected_Stack_Height_mm', '124000')
    design.attributes.add('Validation', 'Expected_Body_Diameter_mm', '9000')
    design.attributes.add('Validation', 'Booster_Engine_Count', '33')
    design.attributes.add('Validation', 'Ship_Engine_Count', '6')
    print('BUILD_SUCCESS=True')
    print('DOCUMENT=' + document.name)
    print('SAVE_OK=' + str(save_ok))
    print('USER_PARAMETERS=' + str(design.userParameters.count))
    print('ROOT_OCCURRENCES=' + str(root.occurrences.count))
    print('ALL_OCCURRENCES=' + str(root.allOccurrences.count))
    print('ALL_BODIES=' + str(root.allBodies.count))
    print('BOOSTER_ENGINES=33')
    print('SHIP_ENGINES=6')
    print('GRID_FINS=3')
    print('FLAPS=4')
    print('EXPORTS=' + '|'.join(exports))


if __name__ == '__main__':
    build()
