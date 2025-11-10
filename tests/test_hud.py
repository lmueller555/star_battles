from game.render.hud import _gimbal_radius


def test_gimbal_radius_zero_for_non_positive_angle():
    assert _gimbal_radius(0.0, 70.0, 16 / 9, (1920, 1080)) == 0.0
    assert _gimbal_radius(-5.0, 70.0, 16 / 9, (1920, 1080)) == 0.0


def test_gimbal_radius_increases_with_angle():
    small = _gimbal_radius(5.0, 70.0, 16 / 9, (1920, 1080))
    large = _gimbal_radius(15.0, 70.0, 16 / 9, (1920, 1080))
    assert 0.0 < small < large


def test_gimbal_radius_handles_wide_angles():
    wide = _gimbal_radius(40.0, 70.0, 16 / 9, (1920, 1080))
    assert 0.0 < wide < max(1920, 1080)


def test_gimbal_radius_zero_for_invalid_fov_and_surface():
    assert _gimbal_radius(10.0, 0.0, 16 / 9, (1920, 1080)) == 0.0
    assert _gimbal_radius(10.0, 70.0, 16 / 9, (0, 1080)) == 0.0
