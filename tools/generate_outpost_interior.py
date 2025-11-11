import json
from dataclasses import asdict, dataclass
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "game" / "assets" / "data" / "outpost_interior_v1.json"


@dataclass
class Node:
    id: str
    layer: str
    type: str
    style: str | None
    points: list[tuple[float, float, float]]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "layer": self.layer,
            "type": self.type,
            "style": self.style,
            "points": [[round(x, 3), round(y, 3), round(z, 3)] for x, y, z in self.points],
        }


nodes: list[Node] = []
labels: list[dict] = []
navmesh: list[dict] = []
interact: list[dict] = []
no_walk: list[dict] = []
chunks: list[dict] = []
ladders: list[dict] = []
door_defs: list[dict] = []

layers = {
    "floor": "Floor",
    "walls": "Walls",
    "ceiling": "Ceiling",
    "fixtures": "Fixtures",
    "doors": "Doors",
    "signs": "Signs",
}


def add_node(node_id: str, layer: str, points: list[tuple[float, float, float]], *, type_: str = "polyline", style: str | None = None) -> None:
    nodes.append(Node(node_id, layer, type_, style, points))


# --- Hangar geometry ------------------------------------------------------
floor_outline = [(-40.0, -40.0, 0.0), (40.0, -40.0, 0.0), (40.0, 40.0, 0.0), (-40.0, 40.0, 0.0)]
add_node("hangar_floor", layers["floor"], floor_outline, type_="polyline_closed", style="primary")

corners = [(-40.0, -40.0), (40.0, -40.0), (40.0, 40.0), (-40.0, 40.0)]
for idx, (x, y) in enumerate(corners):
    add_node(f"hangar_wall_column_{idx}", layers["walls"], [(x, y, 0.0), (x, y, 30.0)], style="primary")

add_node(
    "hangar_wall_base",
    layers["walls"],
    [(-40.0, -40.0, 0.0), (40.0, -40.0, 0.0), (40.0, 40.0, 0.0), (-40.0, 40.0, 0.0), (-40.0, -40.0, 0.0)],
    style="secondary",
)
add_node(
    "hangar_wall_top",
    layers["walls"],
    [(-40.0, -40.0, 30.0), (40.0, -40.0, 30.0), (40.0, 40.0, 30.0), (-40.0, 40.0, 30.0), (-40.0, -40.0, 30.0)],
    style="secondary",
)

add_node("hangar_ceiling", layers["ceiling"], [(-40.0, -40.0, 30.0), (40.0, -40.0, 30.0), (40.0, 40.0, 30.0), (-40.0, 40.0, 30.0)], type_="polyline_closed", style="ceiling_primary")

for idx, y in enumerate(range(-32, 33, 8)):
    pts = [(-40.0, float(y), 30.0), (40.0, float(y), 30.0), (40.0, float(y), 29.5), (-40.0, float(y), 29.5)]
    add_node(f"hangar_beam_x_{idx}", layers["ceiling"], pts, type_="polyline_closed", style="ceiling_beam")

for idx, x in enumerate(range(-32, 33, 8)):
    pts = [(float(x), -40.0, 30.0), (float(x), 40.0, 30.0), (float(x), 40.0, 29.5), (float(x), -40.0, 29.5)]
    add_node(f"hangar_beam_y_{idx}", layers["ceiling"], pts, type_="polyline_closed", style="ceiling_beam")

for xi, x in enumerate(range(-32, 33, 16)):
    for yi, y in enumerate(range(-32, 33, 16)):
        pts = [
            (float(x) - 1.5, float(y) - 0.6, 29.0),
            (float(x) + 1.5, float(y) - 0.6, 29.0),
            (float(x) + 1.5, float(y) + 0.6, 29.0),
            (float(x) - 1.5, float(y) + 0.6, 29.0),
        ]
        add_node(f"hangar_light_{xi}_{yi}", layers["fixtures"], pts, type_="polyline_closed", style="fixture_light")

for side, sign in (("west", -1.0), ("east", 1.0)):
    x_outer = 40.0 * sign
    x_inner = x_outer - sign * 1.5
    pts = [
        (x_outer, -40.0, 6.0),
        (x_inner, -40.0, 6.0),
        (x_inner, 40.0, 6.0),
        (x_outer, 40.0, 6.0),
    ]
    add_node(f"hangar_catwalk_{side}", layers["fixtures"], pts, type_="polyline_closed", style="catwalk")
    add_node(
        f"hangar_catwalk_rail_{side}",
        layers["fixtures"],
        [(x_inner, -40.0, 6.8), (x_inner, 40.0, 6.8)],
        style="catwalk",
    )

for idx, x in enumerate((-35.0, 35.0)):
    add_node(f"hangar_ladder_{idx}", layers["fixtures"], [(x, -20.0, 0.0), (x, -20.0, 6.0)], style="ladder")
    ladders.append(
        {
            "id": f"hangar_ladder_{idx}",
            "aabb": [[x - 0.4, -20.4, 0.0], [x + 0.4, -19.6, 6.2]],
            "facing": [0.0, 1.0, 0.0],
        }
    )

deck_pad_centers = [(-12.0, -12.0), (12.0, -12.0), (-12.0, 12.0), (12.0, 12.0)]
for idx, (px, py) in enumerate(deck_pad_centers):
    pad = [
        (px - 1.0, py - 1.0, 0.2),
        (px + 1.0, py - 1.0, 0.2),
        (px + 1.0, py + 1.0, 0.2),
        (px - 1.0, py + 1.0, 0.2),
    ]
    add_node(f"hangar_deck_pad_{idx}", layers["fixtures"], pad, type_="polyline_closed", style="deck_pad")

# Hangar outer doors (closed)
door_opening_y = -36.0
half_opening = 12.0
for side, sign in (("left", -1.0), ("right", 1.0)):
    x_min = sign * 0.0
    x_max = sign * (half_opening * 2.0)
    if sign < 0:
        x_min, x_max = x_max, x_min
    panel = [
        (x_min, door_opening_y - 4.0, 0.0),
        (x_max, door_opening_y - 4.0, 0.0),
        (x_max, door_opening_y + 4.0, 18.0),
        (x_min, door_opening_y + 4.0, 18.0),
    ]
    add_node(f"hangar_bay_door_{side}", layers["doors"], panel, type_="polyline_closed", style="door_panel")

# Hangar to vestibule door frame
add_node(
    "hangar_vestibule_frame",
    layers["doors"],
    [(-3.0, 36.0, 0.0), (3.0, 36.0, 0.0), (3.0, 36.0, 6.0), (-3.0, 36.0, 6.0), (-3.0, 36.0, 0.0)],
    style="door_frame",
)
add_node(
    "hangar_vestibule_header",
    layers["fixtures"],
    [(-3.0, 36.0, 6.0), (3.0, 36.0, 6.0)],
    style="door_frame",
)

# Hangar interior signage
labels.append({"text": "HANGAR", "layer": layers["signs"], "pos": [0.0, -12.0, 4.0]})

# Vestibule geometry
vest_bounds = (-4.0, 36.0, 4.0, 39.0, 0.0, 4.0)
vest_floor = [(-4.0, 36.0, 0.0), (4.0, 36.0, 0.0), (4.0, 39.0, 0.0), (-4.0, 39.0, 0.0)]
add_node("vestibule_floor", layers["floor"], vest_floor, type_="polyline_closed", style="primary")
add_node("vestibule_ceiling", layers["ceiling"], [(-4.0, 36.0, 4.0), (4.0, 36.0, 4.0), (4.0, 39.0, 4.0), (-4.0, 39.0, 4.0)], type_="polyline_closed", style="ceiling_primary")
for idx, (x, y) in enumerate([(-4.0, 36.0), (4.0, 36.0), (4.0, 39.0), (-4.0, 39.0)]):
    add_node(f"vestibule_column_{idx}", layers["walls"], [(x, y, 0.0), (x, y, 4.0)], style="primary")
add_node(
    "vestibule_wall_top",
    layers["walls"],
    [(-4.0, 36.0, 4.0), (4.0, 36.0, 4.0), (4.0, 39.0, 4.0), (-4.0, 39.0, 4.0), (-4.0, 36.0, 4.0)],
    style="secondary",
)
add_node(
    "vestibule_wall_base",
    layers["walls"],
    [(-4.0, 36.0, 0.0), (4.0, 36.0, 0.0), (4.0, 39.0, 0.0), (-4.0, 39.0, 0.0), (-4.0, 36.0, 0.0)],
    style="secondary",
)
add_node(
    "vestibule_light",
    layers["fixtures"],
    [(-1.0, 37.5, 3.6), (1.0, 37.5, 3.6)],
    style="fixture_light",
)
add_node(
    "vestibule_beam",
    layers["ceiling"],
    [(-4.0, 37.5, 4.0), (4.0, 37.5, 4.0), (4.0, 37.5, 3.6), (-4.0, 37.5, 3.6)],
    type_="polyline_closed",
    style="ceiling_beam",
)

# Vestibule inner door frame to hallway
add_node(
    "vestibule_hall_frame",
    layers["doors"],
    [(-3.0, 39.0, 0.0), (3.0, 39.0, 0.0), (3.0, 39.0, 6.0), (-3.0, 39.0, 6.0), (-3.0, 39.0, 0.0)],
    style="door_frame",
)

# Hallway geometry
hall_floor = [(-4.0, 39.0, 0.0), (4.0, 39.0, 0.0), (4.0, 79.0, 0.0), (-4.0, 79.0, 0.0)]
add_node("hall_floor", layers["floor"], hall_floor, type_="polyline_closed", style="primary")
add_node("hall_ceiling", layers["ceiling"], [(-4.0, 39.0, 4.0), (4.0, 39.0, 4.0), (4.0, 79.0, 4.0), (-4.0, 79.0, 4.0)], type_="polyline_closed", style="ceiling_primary")
for idx, (x, y) in enumerate([(-4.0, 39.0), (4.0, 39.0), (4.0, 79.0), (-4.0, 79.0)]):
    add_node(f"hall_column_{idx}", layers["walls"], [(x, y, 0.0), (x, y, 4.0)], style="primary")
add_node(
    "hall_wall_base",
    layers["walls"],
    [(-4.0, 39.0, 0.0), (4.0, 39.0, 0.0), (4.0, 79.0, 0.0), (-4.0, 79.0, 0.0), (-4.0, 39.0, 0.0)],
    style="secondary",
)
add_node(
    "hall_wall_top",
    layers["walls"],
    [(-4.0, 39.0, 4.0), (4.0, 39.0, 4.0), (4.0, 79.0, 4.0), (-4.0, 79.0, 4.0), (-4.0, 39.0, 4.0)],
    style="secondary",
)

# Hallway beams every 4 m along Y
beam_positions = [39.0 + step * 4.0 for step in range(1, 10)]
for idx, y in enumerate(beam_positions):
    pts = [(-4.0, y, 4.0), (4.0, y, 4.0), (4.0, y, 3.6), (-4.0, y, 3.6)]
    add_node(f"hall_beam_{idx}", layers["ceiling"], pts, type_="polyline_closed", style="ceiling_beam")
    conduit = [(-0.8, y, 3.2), (0.8, y, 3.2)]
    add_node(f"hall_conduit_{idx}", layers["fixtures"], conduit, style="service_line")

labels.append({"text": "HALLWAY", "layer": layers["signs"], "pos": [0.0, 59.0, 3.0]})

# Fleet shop room
fleet_floor = [(-14.0, 55.0, 0.0), (-4.0, 55.0, 0.0), (-4.0, 63.0, 0.0), (-14.0, 63.0, 0.0)]
add_node("fleet_floor", layers["floor"], fleet_floor, type_="polyline_closed", style="primary")
add_node("fleet_ceiling", layers["ceiling"], [(-14.0, 55.0, 3.5), (-4.0, 55.0, 3.5), (-4.0, 63.0, 3.5), (-14.0, 63.0, 3.5)], type_="polyline_closed", style="ceiling_primary")
for idx, (x, y) in enumerate([(-14.0, 55.0), (-4.0, 55.0), (-4.0, 63.0), (-14.0, 63.0)]):
    add_node(f"fleet_column_{idx}", layers["walls"], [(x, y, 0.0), (x, y, 3.5)], style="primary")
add_node(
    "fleet_wall_top",
    layers["walls"],
    [(-14.0, 55.0, 3.5), (-4.0, 55.0, 3.5), (-4.0, 63.0, 3.5), (-14.0, 63.0, 3.5), (-14.0, 55.0, 3.5)],
    style="secondary",
)
add_node(
    "fleet_wall_base",
    layers["walls"],
    [(-14.0, 55.0, 0.0), (-4.0, 55.0, 0.0), (-4.0, 63.0, 0.0), (-14.0, 63.0, 0.0), (-14.0, 55.0, 0.0)],
    style="secondary",
)
for idx, x in enumerate((-13.7, -8.5, -5.0)):
    add_node(f"fleet_light_{idx}", layers["fixtures"], [(x, 55.4, 3.2), (x, 62.6, 3.2)], style="fixture_light")
add_node(
    "fleet_beam",
    layers["ceiling"],
    [(-14.0, 59.0, 3.5), (-4.0, 59.0, 3.5), (-4.0, 59.0, 3.1), (-14.0, 59.0, 3.1)],
    type_="polyline_closed",
    style="ceiling_beam",
)
labels.append({"text": "FLEET SHOP", "layer": layers["signs"], "pos": [-9.0, 59.0, 2.5]})

# Fleet shop doorway
add_node(
    "fleet_door_frame",
    layers["doors"],
    [(-4.0, 58.5, 0.0), (-4.0, 61.5, 0.0), (-4.0, 61.5, 3.0), (-4.0, 58.5, 3.0), (-4.0, 58.5, 0.0)],
    style="door_frame",
)

# Weapons bay room
weap_floor = [(4.0, 61.0, 0.0), (14.0, 61.0, 0.0), (14.0, 71.0, 0.0), (4.0, 71.0, 0.0)]
add_node("weapons_floor", layers["floor"], weap_floor, type_="polyline_closed", style="primary")
add_node("weapons_ceiling", layers["ceiling"], [(4.0, 61.0, 3.5), (14.0, 61.0, 3.5), (14.0, 71.0, 3.5), (4.0, 71.0, 3.5)], type_="polyline_closed", style="ceiling_primary")
for idx, (x, y) in enumerate([(4.0, 61.0), (14.0, 61.0), (14.0, 71.0), (4.0, 71.0)]):
    add_node(f"weapons_column_{idx}", layers["walls"], [(x, y, 0.0), (x, y, 3.5)], style="primary")
add_node(
    "weapons_wall_top",
    layers["walls"],
    [(4.0, 61.0, 3.5), (14.0, 61.0, 3.5), (14.0, 71.0, 3.5), (4.0, 71.0, 3.5), (4.0, 61.0, 3.5)],
    style="secondary",
)
add_node(
    "weapons_wall_base",
    layers["walls"],
    [(4.0, 61.0, 0.0), (14.0, 61.0, 0.0), (14.0, 71.0, 0.0), (4.0, 71.0, 0.0), (4.0, 61.0, 0.0)],
    style="secondary",
)
# U-shaped crane rail at Z=3.2 along interior
rail = [
    (5.0, 62.0, 3.2),
    (13.0, 62.0, 3.2),
    (13.0, 70.0, 3.2),
    (6.0, 70.0, 3.2),
]
add_node("weapons_crane_rail", layers["fixtures"], rail, style="crane_rail")
add_node(
    "weapons_beam",
    layers["ceiling"],
    [(4.0, 65.0, 3.5), (14.0, 65.0, 3.5), (14.0, 65.0, 3.1), (4.0, 65.0, 3.1)],
    type_="polyline_closed",
    style="ceiling_beam",
)
labels.append({"text": "WEAPONS BAY", "layer": layers["signs"], "pos": [9.0, 65.0, 2.5]})

add_node(
    "weapons_door_frame",
    layers["doors"],
    [(4.0, 61.5, 0.0), (4.0, 64.5, 0.0), (4.0, 64.5, 3.0), (4.0, 61.5, 3.0), (4.0, 61.5, 0.0)],
    style="door_frame",
)

labels.append({"text": "FLEET SHOP", "layer": layers["signs"], "pos": [-5.0, 58.5, 3.2]})
labels.append({"text": "WEAPONS BAY", "layer": layers["signs"], "pos": [5.0, 63.5, 3.2]})

# Interact prompts
interact.append({"id": "inspect_ship", "aabb": [[-5.0, -5.0, 0.0], [5.0, 5.0, 6.0]]})

# Door definitions
def door(frame_min, frame_max, trigger_inset: float, facing, door_id, tags=(), sign=None, group=None):
    fx0, fy0, fz0 = frame_min
    fx1, fy1, fz1 = frame_max
    trigger = [
        [fx0 + trigger_inset, fy0 + trigger_inset, fz0],
        [fx1 - trigger_inset, fy1 - trigger_inset, min(fz1, fz0 + 3.0)],
    ]
    door_defs.append(
        {
            "id": door_id,
            "frame": [list(frame_min), list(frame_max)],
            "trigger": trigger,
            "facing": list(facing),
            "tags": list(tags),
            "sign": sign,
            "group": group,
        }
    )

# Hangar to vestibule door (airlock group)
door((-3.0, 36.0, 0.0), (3.0, 42.0, 6.0), 0.8, (0.0, -1.0, 0.0), "hangar_airlock_outer", tags=("auto",), group="main_airlock")
# Vestibule inner door
door((-3.0, 39.0, 0.0), (3.0, 45.0, 6.0), 0.8, (0.0, 1.0, 0.0), "hangar_airlock_inner", tags=("airlock",), group="main_airlock")
# Fleet shop door
door((-4.0, 58.5, 0.0), (-1.0, 61.5, 3.0), 0.4, (1.0, 0.0, 0.0), "fleet_shop", tags=("proximity",), sign="FLEET SHOP")
# Weapons bay door
door((1.0, 61.5, 0.0), (4.0, 64.5, 3.0), 0.4, (-1.0, 0.0, 0.0), "weapons_bay", tags=("proximity",), sign="WEAPONS BAY")

# NavMesh definitions
navmesh.append({
    "id": "hangar_nav_outer",
    "points": [
        [-40.0, -40.0, 0.0],
        [40.0, -40.0, 0.0],
        [40.0, 40.0, 0.0],
        [-40.0, 40.0, 0.0],
    ],
})
navmesh.append({
    "id": "vestibule_nav",
    "points": [
        [-4.0, 36.0, 0.0],
        [4.0, 36.0, 0.0],
        [4.0, 39.0, 0.0],
        [-4.0, 39.0, 0.0],
    ],
})
navmesh.append({
    "id": "hall_nav",
    "points": [
        [-4.0, 39.0, 0.0],
        [4.0, 39.0, 0.0],
        [4.0, 79.0, 0.0],
        [-4.0, 79.0, 0.0],
    ],
})
navmesh.append({
    "id": "fleet_nav",
    "points": [
        [-14.0, 55.0, 0.0],
        [-4.0, 55.0, 0.0],
        [-4.0, 63.0, 0.0],
        [-14.0, 63.0, 0.0],
    ],
})
navmesh.append({
    "id": "weapons_nav",
    "points": [
        [4.0, 61.0, 0.0],
        [14.0, 61.0, 0.0],
        [14.0, 71.0, 0.0],
        [4.0, 71.0, 0.0],
    ],
})

no_walk.append({
    "id": "hangar_ship_safety",
    "aabb": [[-12.0, -12.0, 0.0], [12.0, 12.0, 8.0]],
    "dynamic": True,
})

chunks.extend(
    [
        {"id": "hangar", "aabb": [[-40.0, -40.0, 0.0], [40.0, 40.0, 30.0]], "label": "HANGAR", "stream": "Hangar"},
        {"id": "vestibule", "aabb": [[-4.0, 36.0, 0.0], [4.0, 39.0, 4.0]], "label": "HANGAR", "stream": "VestibuleHall"},
        {"id": "hall", "aabb": [[-4.0, 39.0, 0.0], [4.0, 79.0, 4.0]], "label": "HALLWAY", "stream": "VestibuleHall"},
        {"id": "fleet", "aabb": [[-14.0, 55.0, 0.0], [-4.0, 63.0, 3.5]], "label": "FLEET SHOP", "stream": "FleetShop"},
        {"id": "weapons", "aabb": [[4.0, 61.0, 0.0], [14.0, 71.0, 3.5]], "label": "WEAPONS BAY", "stream": "WeaponsBay"},
    ]
)

nav = {
    "spawn": {"position": [0.0, -10.0, 0.0]},
    "navmesh": navmesh,
    "interact": interact,
    "noWalk": no_walk,
    "chunks": chunks,
    "ladders": ladders,
}

metadata = {
    "name": "outpost_interior_v1",
    "units": "m",
    "version": 2,
}

payload = {
    "metadata": metadata,
    "nodes": [node.to_dict() for node in nodes],
    "labels": labels,
    "doors": door_defs,
    "nav": nav,
}

OUTPUT.write_text(json.dumps(payload, indent=2))
print(f"Wrote {OUTPUT}")
