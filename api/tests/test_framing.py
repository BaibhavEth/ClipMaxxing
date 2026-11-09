from app.models import FramingMode
from app.services.framing import (
    Box,
    FaceTrack,
    FrameSample,
    FramingPlan,
    Layout,
    Shot,
    apply_mode,
    classify_shot,
    reliable_faces,
    segment_shots,
    smooth_focus_path,
    track_faces,
)


def _track(box: Box, count: int, start: float = 0) -> FaceTrack:
    return FaceTrack(samples=[(start + index * 0.25, box) for index in range(count)])


def test_short_shots_merge_into_their_neighbours() -> None:
    assert segment_shots([5.0, 5.5, 12.0], 0, 20) == [(0, 5.5), (5.5, 12.0), (12.0, 20)]


def test_weak_detections_do_not_compete_with_a_confident_face() -> None:
    face = Box(0.4, 0.2, 0.1, 0.2)
    background = Box(0.7, 0.1, 0.15, 0.3)
    huge = Box(0.1, 0.0, 0.5, 0.8)

    assert reliable_faces([(face, 0.95), (background, 0.78), (huge, 0.99)]) == [face]


def test_tracks_follow_each_person_separately() -> None:
    left, right = Box(0.2, 0.2, 0.1, 0.2), Box(0.7, 0.2, 0.1, 0.2)
    frames = [FrameSample(t=index * 0.25, faces=[left, right]) for index in range(8)]

    tracks = track_faces(frames)

    assert len(tracks) == 2
    assert all(len(track.samples) == 8 for track in tracks)


def test_classifies_layouts_from_face_tracks() -> None:
    speaker = Box(0.45, 0.2, 0.1, 0.2)
    other = Box(0.75, 0.2, 0.1, 0.2)
    webcam = Box(0.85, 0.75, 0.06, 0.1)

    assert classify_shot([_track(speaker, 20)], 20, 0, 5, 0.32).layout == Layout.TALKING_HEAD
    assert (
        classify_shot([_track(speaker, 20), _track(other, 20)], 20, 0, 5, 0.32).layout
        == Layout.TWO_SHOT
    )
    assert classify_shot([_track(webcam, 20)], 20, 0, 5, 0.32).layout == Layout.SCREEN_CAM
    assert classify_shot([], 20, 0, 5, 0.32).layout == Layout.SCREEN


def test_small_faces_in_opposite_corners_are_a_wide_two_shot() -> None:
    left = Box(0.18, 0.25, 0.04, 0.08)
    right = Box(0.72, 0.25, 0.04, 0.08)

    shot = classify_shot([_track(left, 20), _track(right, 20)], 20, 0, 5, 0.32)

    assert shot.layout == Layout.TWO_SHOT


def test_virtual_camera_ignores_small_movements() -> None:
    samples = [(index * 0.25, Box(0.45 + (index % 2) * 0.01, 0.2, 0.1, 0.2)) for index in range(20)]

    path = smooth_focus_path(samples, 0, 5, 0.32)

    assert len(path) == 2
    assert abs(path[0][1] - path[-1][1]) < 0.001


def test_virtual_camera_pans_at_a_capped_speed() -> None:
    samples = [(index * 0.25, Box(0.1 if index < 4 else 0.7, 0.2, 0.1, 0.2)) for index in range(20)]

    path = smooth_focus_path(samples, 0, 5, 0.32)
    xs = [x for _, x, _ in path]

    assert xs[-1] > 0.6
    for (t0, x0, _), (t1, x1, _) in zip(path, path[1:], strict=False):
        assert abs(x1 - x0) / max(t1 - t0, 1e-6) <= 0.9 * 0.32 + 1e-6


def test_framing_modes_override_detected_layouts() -> None:
    plan = FramingPlan(
        1920,
        1080,
        [
            Shot(0, 5, Layout.TWO_SHOT, people=[Box(0.2, 0.2, 0.1, 0.2), Box(0.7, 0.2, 0.1, 0.2)]),
            Shot(5, 9, Layout.SCREEN),
        ],
    )

    assert {shot.layout for shot in apply_mode(plan, FramingMode.FIT).shots} == {Layout.SCREEN}
    filled = apply_mode(plan, FramingMode.FILL)
    assert [shot.layout for shot in filled.shots] == [Layout.TALKING_HEAD, Layout.TALKING_HEAD]


def test_plan_slices_to_a_trim_and_round_trips_through_json() -> None:
    plan = FramingPlan(1920, 1080, [Shot(0, 5, Layout.SCREEN), Shot(5, 10, Layout.GROUP)])

    sliced = FramingPlan.from_json(plan.slice(3, 7).to_json())

    assert [(shot.start, shot.end, shot.layout) for shot in sliced.shots] == [
        (3, 5, Layout.SCREEN),
        (5, 7, Layout.GROUP),
    ]
