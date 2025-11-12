from game.world.interior import InteriorDefinition
from game.world.outpost_layouts import build_outpost_interior_v1


def _load_definition() -> InteriorDefinition:
    return build_outpost_interior_v1()


def test_all_spaces_have_ceiling_planes_and_members() -> None:
    definition = _load_definition()
    chunk_targets = {
        "hangar": 45.0,
        "vestibule": 4.0,
        "hall": 4.0,
        "fleet": 3.5,
        "weapons": 3.5,
    }
    nodes = list(definition.nodes)
    for chunk_id, height in chunk_targets.items():
        chunk = next((c for c in definition.chunks if c.id == chunk_id), None)
        assert chunk is not None, f"Missing chunk {chunk_id}"
        min_x, min_y, min_z = chunk.aabb_min
        max_x, max_y, max_z = chunk.aabb_max
        found_plane = False
        found_beam = False
        for node in nodes:
            if node.layer != "Ceiling" or not node.points:
                continue
            xs = [pt[0] for pt in node.points]
            ys = [pt[1] for pt in node.points]
            zs = [pt[2] for pt in node.points]
            max_z = max(zs)
            min_z = min(zs)
            if abs(max_z - height) <= 0.6 and abs(min_z - height) <= 1.0:
                overlap_x = min(xs) <= max_x + 0.1 and max(xs) >= min_x - 0.1
                overlap_y = min(ys) <= max_y + 0.1 and max(ys) >= min_y - 0.1
                if overlap_x and overlap_y:
                    if node.type.endswith("closed"):
                        found_plane = True
                    if node.style == "ceiling_beam":
                        found_beam = True
        assert found_plane, f"Chunk {chunk_id} missing ceiling plane at {height}m"
        assert found_beam, f"Chunk {chunk_id} missing ceiling member lines"
