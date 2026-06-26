"""Camera capture helpers shared by the GUI and tests."""


def stable_frame_timestamp(segment_start_timestamp, frame_index, fps):
    """Return the stable video-clock timestamp for a frame.

    segment_start_timestamp: Unix timestamp in seconds.
    frame_index: zero-based frame index within the segment.
    fps: frames per second for the encoded video.
    """
    if fps <= 0:
        raise ValueError("fps must be positive")
    return segment_start_timestamp + frame_index / fps


def camera_timestamp_row(frame_index, capture_timestamp, segment_start_timestamp, segment, fps):
    """Build one timestamp CSV row with both capture time and video time."""
    video_timestamp = stable_frame_timestamp(segment_start_timestamp, frame_index, fps)
    return {
        "frame": frame_index,
        "timestamp": capture_timestamp,
        "capture_timestamp": capture_timestamp,
        "video_timestamp": video_timestamp,
        "segment": segment,
    }


def camera_roles_from_selection(cameras, selected_names):
    """Map selected camera names to recorder roles in selection order."""
    roles = {}
    selected = []
    for name in selected_names:
        for cam_id, cam_name in cameras:
            if cam_name == name:
                selected.append((cam_id, cam_name))
                break

    if selected:
        roles["nir_camera"] = selected[0]
    if len(selected) > 1:
        roles["rgb_camera"] = selected[1]
    return roles
