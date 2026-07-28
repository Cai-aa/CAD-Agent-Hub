"""Parametric, STEP-first planar planetary gear concept.

CAD brief:
- Assembly: separate sun, planet, internal ring, carrier, and pin bodies.
- Units / frame: millimetres, XY gear plane, +Z through thickness.
- Hard constraint: three planet centres lie on a 42 mm radius at 120 degrees.
- Assumptions: module 2 mm; 18/24/66 tooth counts; 8 mm gear thickness;
  simplified straight-sided trapezoidal teeth with small radial clearances.
- This is concept geometry, not a production involute or tolerance-qualified gearset.
"""

from __future__ import annotations

from math import cos, radians, sin

from build123d import Align, Axis, Box, Color, Cylinder, Polygon, Vector, extrude
from cadpy.assembly import AssemblyHelper, label_shape


MODULE = 2.0
SUN_TEETH = 18
PLANET_TEETH = 24
RING_TEETH = SUN_TEETH + 2 * PLANET_TEETH

PLANET_ORBIT_RADIUS = 42.0
GEAR_THICKNESS = 8.0
ADDENDUM = 1.7
DEDENDUM = 2.2

SUN_BORE_DIAMETER = 10.0
PLANET_BORE_DIAMETER = 8.6
RING_OUTER_DIAMETER = 150.0

CARRIER_THICKNESS = 3.0
CARRIER_CENTER_BORE_DIAMETER = 16.0
CARRIER_PIN_HOLE_DIAMETER = 8.3
CARRIER_Z = -5.7

PIN_SHAFT_DIAMETER = 8.0
PIN_SHAFT_LENGTH = 11.5
PIN_HEAD_DIAMETER = 11.0
PIN_HEAD_THICKNESS = 1.5
PIN_ASSEMBLY_Z = CARRIER_Z - CARRIER_THICKNESS / 2.0 - PIN_HEAD_THICKNESS / 2.0


def pitch_radius(teeth: int) -> float:
    return MODULE * teeth / 2.0


def polar(radius: float, angle_deg: float) -> tuple[float, float]:
    angle = radians(angle_deg)
    return radius * cos(angle), radius * sin(angle)


def trapezoid_outline(
    teeth: int,
    root_radius: float,
    tip_radius: float,
    *,
    root_fraction: float = 0.28,
    tip_fraction: float = 0.14,
):
    """Create one closed polygon with straight flanks and flat tooth tips."""
    tooth_pitch = 360.0 / teeth
    root_half = tooth_pitch * root_fraction
    tip_half = tooth_pitch * tip_fraction
    points: list[tuple[float, float]] = []

    for index in range(teeth):
        center = index * tooth_pitch
        points.extend(
            [
                polar(root_radius, center - tooth_pitch / 2.0),
                polar(root_radius, center - root_half),
                polar(tip_radius, center - tip_half),
                polar(tip_radius, center + tip_half),
                polar(root_radius, center + root_half),
            ]
        )

    return Polygon(*points)


def make_external_gear(teeth: int, bore_diameter: float, label: str):
    pitch = pitch_radius(teeth)
    profile = trapezoid_outline(
        teeth,
        pitch - DEDENDUM,
        pitch + ADDENDUM,
    )
    gear = extrude(profile.face(), amount=GEAR_THICKNESS).translate(
        Vector(0, 0, -GEAR_THICKNESS / 2.0)
    )
    bore = Cylinder(bore_diameter / 2.0, GEAR_THICKNESS + 2.0)
    gear = gear - bore
    return label_shape(gear, label)


def make_sun_gear():
    return make_external_gear(SUN_TEETH, SUN_BORE_DIAMETER, "sun_gear")


def make_planet_gear():
    return make_external_gear(PLANET_TEETH, PLANET_BORE_DIAMETER, "planet_gear")


def make_ring_gear():
    pitch = pitch_radius(RING_TEETH)
    outer = Cylinder(RING_OUTER_DIAMETER / 2.0, GEAR_THICKNESS)
    inner_void_profile = trapezoid_outline(
        RING_TEETH,
        pitch + DEDENDUM,
        pitch - ADDENDUM,
    )
    inner_void = extrude(inner_void_profile.face(), amount=GEAR_THICKNESS + 2.0).translate(
        Vector(0, 0, -(GEAR_THICKNESS + 2.0) / 2.0)
    )
    ring = outer - inner_void
    return label_shape(ring, "ring_gear")


def make_carrier():
    hub_radius = 18.0
    arm_width = 14.0
    planet_boss_radius = 10.0

    carrier = Cylinder(hub_radius, CARRIER_THICKNESS)
    for angle in (0.0, 120.0, 240.0):
        arm = Box(
            PLANET_ORBIT_RADIUS,
            arm_width,
            CARRIER_THICKNESS,
            align=(Align.MIN, Align.CENTER, Align.CENTER),
        ).rotate(Axis.Z, angle)
        boss_x, boss_y = polar(PLANET_ORBIT_RADIUS, angle)
        boss = Cylinder(planet_boss_radius, CARRIER_THICKNESS).translate(
            Vector(boss_x, boss_y, 0)
        )
        carrier = carrier + arm + boss

    center_bore = Cylinder(CARRIER_CENTER_BORE_DIAMETER / 2.0, CARRIER_THICKNESS + 2.0)
    carrier = carrier - center_bore

    for angle in (0.0, 120.0, 240.0):
        pin_x, pin_y = polar(PLANET_ORBIT_RADIUS, angle)
        pin_hole = Cylinder(CARRIER_PIN_HOLE_DIAMETER / 2.0, CARRIER_THICKNESS + 2.0).translate(
            Vector(pin_x, pin_y, 0)
        )
        carrier = carrier - pin_hole

    return label_shape(carrier, "planet_carrier")


def make_planet_pin():
    head = Cylinder(PIN_HEAD_DIAMETER / 2.0, PIN_HEAD_THICKNESS)
    shaft = Cylinder(
        PIN_SHAFT_DIAMETER / 2.0,
        PIN_SHAFT_LENGTH,
        align=(Align.CENTER, Align.CENTER, Align.MIN),
    ).translate(
        Vector(0, 0, PIN_HEAD_THICKNESS / 2.0)
    )
    return label_shape(head + shaft, "planet_pin")


def placed(shape, x: float, y: float, z: float, angle_deg: float = 0.0):
    return shape.rotate(Axis.Z, angle_deg).translate(Vector(x, y, z))


def make_assembly():
    asm = AssemblyHelper("planar_planetary_gear")

    asm.add(make_ring_gear(), "ring_gear", color=Color(0.35, 0.42, 0.50))
    asm.add(make_sun_gear(), "sun_gear", color=Color(0.95, 0.63, 0.10))
    asm.add(
        placed(make_carrier(), 0, 0, CARRIER_Z),
        "planet_carrier",
        color=Color(0.18, 0.45, 0.75),
    )

    planet_pitch_angle = 360.0 / PLANET_TEETH
    for index, angle in enumerate((0.0, 120.0, 240.0), start=1):
        x, y = polar(PLANET_ORBIT_RADIUS, angle)
        # A planet gap faces the sun and an inward ring tooth at each radial line.
        planet_phase = angle - planet_pitch_angle / 2.0
        asm.add(
            placed(make_planet_gear(), x, y, 0, planet_phase),
            f"planet_gear_{index}",
            f"orbit_{int(angle):03d}_deg",
            color=Color(0.80, 0.80, 0.82),
        )
        asm.add(
            placed(make_planet_pin(), x, y, PIN_ASSEMBLY_Z),
            f"planet_pin_{index}",
            f"orbit_{int(angle):03d}_deg",
            color=Color(0.55, 0.32, 0.16),
        )

    return asm.build()
