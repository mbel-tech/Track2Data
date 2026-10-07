"""Format-quirk tests.

These parse the real fixture files directly and assert the properties that make
each format awkward to import. They do not need Track2Data. They serve two
purposes: they document each quirk as an executable fact, and they fail loudly
if an upstream fixture or a tracker's output convention changes.

Every number below was observed on the pinned file, not taken from documentation.
"""
import re

import h5py
import numpy as np
import pandas as pd
import pytest

from tests.real_samples import oracles as O

pytestmark = pytest.mark.quirk

DLC_EPM = "DLC_single-mouse_EPM.predictions.h5"
DLC_2 = "DLC_two-mice.predictions.csv"
EKS = "EKS_IBL-paw_multicam_left.predictions.csv"
SL_3 = "SLEAP_three-mice_Aeon_mixed-labels.analysis.h5"
SL_1 = "SLEAP_single-mouse_EPM.analysis.h5"
ANI = "anipose_mouse-paw_anipose-paper.triangulation.csv"
LOC = "TRex_five-locusts.zip"
ATA = "2602_ISA3080_Low_5_Coordinates.csv"
CTX = "2602_ISA3080_Low_5.mat"
TOX = "Tracking_RealSpace_1.txt"
OLD = [f"2602_ISA3080_Low_5_fish{i}.npz" for i in range(13)]


# =============================================================== DeepLabCut / Lightning Pose
def test_dlc_h5_single_animal_has_three_level_columns_and_no_nan(fx):
    """Key is /df_with_missing; columns are scorer/bodyparts/coords with likelihood third."""
    with h5py.File(fx(DLC_EPM), "r") as f:
        assert list(f.keys()) == ["df_with_missing"]
    df = O.read_dlc(fx(DLC_EPM))
    assert df.shape == (18485, 24)
    assert list(df.columns.names) == ["scorer", "bodyparts", "coords"]
    assert list(dict.fromkeys(df.columns.get_level_values("coords"))) == ["x", "y", "likelihood"]
    assert list(dict.fromkeys(df.columns.get_level_values("bodyparts"))) == [
        "snout", "left_ear", "right_ear", "centre", "lateral_left", "lateral_right", "tailbase", "tail_end"]
    assert int(df.isna().sum().sum()) == 0
    assert df.index[0] == 0 and df.index[-1] == 18484


def test_dlc_h5_records_no_frame_rate_or_video_size(fx):
    """Nothing in the file says fps or frame size, so a reader cannot fill VideoInfo from it."""
    with h5py.File(fx(DLC_EPM), "r") as f:
        text = " ".join(str(dict(f[k].attrs)) for k in f)
        names = []
        f.visit(names.append)
    blob = (text + " ".join(names)).lower()
    for token in ("fps", "frame_rate", "framerate", "width", "height", "video"):
        assert token not in blob


def test_dlc_multi_animal_csv_has_four_header_levels(fx):
    """Multi-animal CSV adds an 'individuals' header row; the first header row names the scorer."""
    df = O.read_dlc(fx(DLC_2))
    assert list(df.columns.names) == ["scorer", "individuals", "bodyparts", "coords"]
    assert list(dict.fromkeys(df.columns.get_level_values("individuals"))) == ["individual1", "individual2"]
    assert len(set(df.columns.get_level_values("bodyparts"))) == 12
    assert df.shape == (59999, 72)
    assert int(df.isna().sum().sum()) == 5890            # lost keypoints are NaN, not zero
    assert df.index[0] == 0 and df.index[-1] == 59998


def test_dlc_header_depth_must_be_detected_from_the_second_row(fx):
    """Same extension and same first cell ('scorer') for 3- and 4-level files."""
    first = lambda p: [open(p).readline().split(",")[0]]
    assert first(fx(DLC_2)) == first(fx(EKS)) == ["scorer"]
    second = lambda p: [ln.split(",")[0] for ln in open(p).read().splitlines()[:3]][1]
    assert second(fx(DLC_2)) == "individuals"
    assert second(fx(EKS)) == "bodyparts"


def test_lightning_pose_eks_has_nine_coords_per_keypoint_interleaved(fx):
    """EKS output carries 9 coords per keypoint; x,y,likelihood are NOT the only columns."""
    df = O.read_dlc(fx(EKS))
    assert df.shape == (997, 18)
    assert list(dict.fromkeys(df.columns.get_level_values("bodyparts"))) == ["paw_l", "paw_r"]
    assert list(dict.fromkeys(df.columns.get_level_values("coords"))) == [
        "x", "y", "likelihood", "x_ens_median", "y_ens_median",
        "x_ens_var", "y_ens_var", "x_posterior_var", "y_posterior_var"]
    assert df.columns.get_level_values("scorer").unique().tolist() == ["ensemble-kalman_tracker"]


# =============================================================== SLEAP analysis HDF5
def test_sleap_gui_export_carries_no_layout_attributes(fx):
    """GUI-exported analysis files have no file or dataset attributes (no 'dims', no 'preset')."""
    s = O.read_sleap(fx(SL_3))
    assert s["file_attrs"] == {}
    assert all(a == {} for a in s["ds_attrs"].values())


def test_sleap_layout_is_tracks_xy_nodes_frames(fx):
    """tracks is (n_tracks, 2, n_nodes, n_frames); occupancy is (n_frames, n_tracks) uint8."""
    s = O.read_sleap(fx(SL_3))
    assert s["tracks"].shape == (3, 2, 1, 601)
    assert s["occupancy"].shape == (601, 3) and s["occupancy"].dtype == np.uint8
    assert s["node_names"] == ["centroid"]


def test_sleap_named_tracks_decode_from_bytes(fx):
    s = O.read_sleap(fx(SL_3))
    assert s["track_names"] == ["AEON3B_NTP", "AEON3B_TP1", "AEON3B_TP2"]
    with h5py.File(fx(SL_3), "r") as f:
        assert f["track_names"].dtype.kind == "S"


def test_sleap_occupancy_agrees_with_nan_pattern(fx):
    """occupancy==0 exactly where the coordinates are NaN (3 tracks x 601 frames = 1803 slots)."""
    s = O.read_sleap(fx(SL_3))
    xy_nan = np.isnan(s["tracks"]).all(axis=(1, 2))            # (tracks, frames)
    assert int(s["occupancy"].sum()) == 1575
    assert np.array_equal(xy_nan.T, s["occupancy"] == 0)
    assert int(np.isnan(s["tracks"]).sum()) == 456


def test_sleap_project_without_tracks_has_empty_float_track_names(fx):
    """No tracks: track_names is an EMPTY float64 dataset (not bytes), yet tracks still has one slot."""
    with h5py.File(fx(SL_1), "r") as f:
        assert f["track_names"].shape == (0,) and f["track_names"].dtype == np.float64
        assert f["tracks"].shape == (1, 2, 6, 18485)
        assert f["edge_inds"].shape == (7, 2)
    assert O.read_sleap(fx(SL_1))["track_names"] == []
    assert int(np.isnan(O.read_sleap(fx(SL_1))["tracks"]).sum()) == 18460


def test_sleap_single_node_skeleton_has_empty_edge_datasets(fx):
    with h5py.File(fx(SL_3), "r") as f:
        assert f["edge_inds"].shape == (0,) and f["edge_names"].shape == (0,)


# =============================================================== Anipose
def test_anipose_keypoint_names_contain_hyphens_and_columns_split_from_the_right(fx):
    """Columns are '{keypoint}_{x,y,z,error,ncams,score}'; a keypoint may itself contain '_' or '-'."""
    df = pd.read_csv(fx(ANI))
    assert df.shape == (246, 49)
    kps = sorted({c.rsplit("_", 1)[0] for c in df.columns if c.endswith("_score")})
    assert kps == ["l-base", "l-edge", "l-middle", "r-base", "r-edge", "r-middle"]
    for kp in kps:
        for suf in ("x", "y", "z", "error", "ncams", "score"):
            assert f"{kp}_{suf}" in df.columns
    assert [c for c in df.columns if c.startswith("M_")] == [f"M_{i}{j}" for i in range(3) for j in range(3)]
    assert {"center_0", "center_1", "center_2", "fnum"} <= set(df.columns)


def test_anipose_is_three_dimensional_and_frame_index_is_zero_based(fx):
    df = pd.read_csv(fx(ANI))
    assert df["fnum"].tolist() == list(range(246))
    assert df["l-base_z"].notna().any()                       # a z coordinate exists
    assert int(df.isna().sum().sum()) == 4812


def test_anipose_missing_points_are_nan_in_all_three_coordinates_together(fx):
    df = pd.read_csv(fx(ANI))
    for kp in ("l-base", "r-middle"):
        nan_x = df[f"{kp}_x"].isna()
        assert nan_x.equals(df[f"{kp}_y"].isna()) and nan_x.equals(df[f"{kp}_z"].isna())


# =============================================================== TRex
def test_trex_new_export_has_metadata_arrays_and_pose_keypoints(fx):
    members = O.trex_zip_members(fx(LOC))
    assert list(members) == [f"locusts-noqr_20250117_5_id{i}.npz" for i in range(5)]
    for m in members.values():
        assert {"id", "frame_rate", "cm_per_pixel", "video_size", "detection_p", "tracklets"} <= set(m)
        assert all(f"poseX{k}" in m and f"poseY{k}" in m for k in range(7))
        assert len(m["frame"]) == 2845 and m["frame"][0] == 0 and m["frame"][-1] == 2844
        assert float(m["frame_rate"][0]) == 30.0
        assert float(m["cm_per_pixel"][0]) == pytest.approx(0.02619, abs=1e-5)
        assert m["video_size"].tolist() == [4096.0, 3000.0]


def test_trex_old_export_lacks_the_metadata_arrays_and_renames_segment_tables(fx):
    members = O.trex_npz_files([fx(n) for n in OLD])
    for m in members.values():
        assert not ({"id", "frame_rate", "cm_per_pixel", "video_size", "detection_p"} & set(m))
        assert {"frame_segments", "segment_vxys", "segment_length"} <= set(m)
        assert "tracklets" not in m


def test_trex_files_differ_in_length_within_one_recording(fx):
    members = O.trex_npz_files([fx(n) for n in OLD])
    lengths = [len(m["frame"]) for m in members.values()]
    assert lengths == [12013, 12024, 12014] + [12024] * 10     # video has 12033 frames (AnimalTA rows)


def test_trex_file_names_need_a_numeric_sort(fx):
    """fish10..12 sort between fish1 and fish2 lexicographically; identity order must be numeric."""
    names = [fx(n).name for n in OLD]
    lexicographic = sorted(names)
    numeric = sorted(names, key=O.numeric_key)
    assert numeric == names
    assert lexicographic != numeric
    assert [O.numeric_key(n) for n in lexicographic][:4] == [0, 1, 10, 11]


def test_trex_untracked_frames_are_positive_infinity_never_nan(fx):
    """+inf (not NaN, not -inf) in every float array; nothing is NaN in the whole file."""
    sets = list(O.trex_zip_members(fx(LOC)).values()) + list(O.trex_npz_files([fx(n) for n in OLD]).values())
    assert len(sets) == 18
    for m in sets:
        n = len(m["frame"])
        for key, v in m.items():
            if v.shape == (n,) and v.dtype.kind == "f":
                assert not np.isnan(v).any(), key
                assert not np.isneginf(v).any(), key
    for key in ("X", "Y", "ANGLE", "SPEED"):
        for m in sets:
            v = m[key]
            assert np.isposinf(v).any() or (m["missing"] == 0).all()


def test_trex_missing_flag_is_not_a_reliable_mask(fx):
    """Every flagged frame is +inf, but in 3 of 13 older files one +inf frame has missing==0."""
    exceptions = []
    for i, m in enumerate(O.trex_npz_files([fx(n) for n in OLD]).values()):
        nonfinite = ~np.isfinite(m["X"])
        flagged = m["missing"] == 1
        assert (nonfinite | ~flagged).all()                      # flagged  =>  non-finite
        if (nonfinite & ~flagged).any():
            exceptions.append((i, int(np.where(nonfinite & ~flagged)[0][0])))
    assert exceptions == [(5, 0), (6, 0), (11, 27)]            # (file, frame): one frame in each of three files
    for m in O.trex_zip_members(fx(LOC)).values():               # new export: exact agreement
        assert np.array_equal(~np.isfinite(m["X"]), m["missing"] == 1)


def test_trex_missing_counts_per_file(fx):
    new = [int((m["missing"] == 1).sum()) for m in O.trex_zip_members(fx(LOC)).values()]
    old = [int((m["missing"] == 1).sum()) for m in O.trex_npz_files([fx(n) for n in OLD]).values()]
    assert new == [22, 16, 17, 9, 0]
    assert old == [939, 1005, 1351, 587, 1231, 1333, 1117, 984, 1967, 1285, 1471, 937, 478]


def test_trex_new_export_centroid_is_in_cm_and_pose_is_in_pixels(fx):
    """X is cm (47 here) while poseX0 is pixels (1811); cm_per_pixel reconciles them."""
    m = next(iter(O.trex_zip_members(fx(LOC)).values()))
    ok = np.isfinite(m["X"])
    px = m["X"][ok] / float(m["cm_per_pixel"][0])
    pose_x = np.stack([m[f"poseX{k}"] for k in range(7)], axis=1)[ok]
    assert (px >= pose_x.min(axis=1) - 40).all() and (px <= pose_x.max(axis=1) + 40).all()
    assert float(np.median(m["X"][ok])) < 100 < float(np.median(m["poseX0"][ok]))


def test_trex_old_export_x_is_pixel_scale_despite_cm_labelling(fx):
    """No cm_per_pixel in the file and X reaches 3,700: pixel scale, though TRex names the unit cm."""
    top = max(float(np.nanmax(np.where(np.isfinite(m["X"]), m["X"], np.nan)))
              for m in O.trex_npz_files([fx(n) for n in OLD]).values())
    assert top > 3000


def test_trex_csv_export_has_units_in_headers_and_no_identity(fx):
    df = pd.read_csv(fx("test_fish0.csv"))
    assert list(df.columns) == ["frame", "SPEED#wcentroid (cm/s)", "X#wcentroid (cm)", "blobid", "midline_length", "num_pixels"]
    assert len(df) == 200
    assert not any(c.lower() in ("id", "individual", "fish") for c in df.columns)
    assert not any(c.startswith("Y") for c in df.columns)       # this export selected X but not Y


# =============================================================== AnimalTA
def test_animalta_csv_is_semicolon_delimited(fx):
    """A default comma read yields a single column; the delimiter must be ';'."""
    assert pd.read_csv(fx(ATA)).shape[1] == 1
    df = O.read_animalta(fx(ATA))
    assert df.shape == (12033, 26)
    assert list(df.columns[:4]) == ["Frame", "Time", "X_Arena0_Ind0", "Y_Arena0_Ind0"]
    assert [c for c in df.columns[2:]] == [f"{a}_Arena0_Ind{i}" for i in range(12) for a in "XY"]


def test_animalta_missing_target_is_the_literal_NA(fx):
    text = open(fx(ATA), encoding="utf8").read()
    assert len(re.findall(r"(?<=;)NA(?=;|\r?\n)", text)) == 5242
    assert int(O.read_animalta(fx(ATA)).isna().sum().sum()) == 5242


def test_animalta_time_is_rounded_so_fps_must_come_from_the_total_span(fx):
    """Time is rounded to 0.01 s, so per-step differences are unreliable at non-round frame rates."""
    df = O.read_animalta(fx(ATA))
    assert np.allclose(df["Time"], df["Time"].round(2))
    fps = (len(df) - 1) / (df["Time"].iloc[-1] - df["Time"].iloc[0])
    assert fps == pytest.approx(25.0, rel=1e-6)


# =============================================================== Ctrax raw .mat
def test_ctrax_raw_mat_is_a_flat_per_detection_layout_not_a_trx_struct(fx):
    m = O.read_ctrax(fx(CTX))
    assert set(m) == {"ntargets", "maj_ax", "angle", "min_ax", "x_pos", "y_pos", "startframe", "identity", "timestamps"}
    assert "trx" not in m
    nt = m["ntargets"].ravel().astype(int)
    assert len(nt) == 12033 and int(nt.sum()) == 159765 == m["x_pos"].shape[0]
    assert (nt.min(), nt.max()) == (9, 17)
    assert int(m["startframe"].ravel()[0]) == 0


def test_ctrax_identities_are_fragments_not_animals(fx):
    m = O.read_ctrax(fx(CTX))
    ids = np.unique(m["identity"].ravel())
    assert len(ids) == 193 and ids.min() == 0 and ids.max() == 192
    assert len(ids) > m["ntargets"].max()                      # more identities than animals ever present


def test_ctrax_timestamps_give_the_frame_rate(fx):
    ts = O.read_ctrax(fx(CTX))["timestamps"].ravel()
    assert (len(ts) - 1) / (ts[-1] - ts[0]) == pytest.approx(25.0, rel=1e-6)


# =============================================================== ToxTrac
def test_toxtrac_realspace_header_is_exact_and_tab_delimited(fx):
    df = O.read_toxtrac(fx(TOX))
    assert list(df.columns) == O.TOX_COLUMNS
    assert len(df) == 17811
    assert set(df["Arena"]) == {1} and set(df["Track"]) == {1}


def test_toxtrac_label_is_a_position_status_code(fx):
    """Per the manual: 0 predicted, 1 confirmed, 2 occluded, 3 mirror. 43 rows are predicted."""
    vc = O.read_toxtrac(fx(TOX))["Label"].value_counts().to_dict()
    assert vc == {1: 17768, 0: 43}


def test_toxtrac_lost_frames_are_absent_rows_and_time_does_not_start_at_zero(fx):
    df = O.read_toxtrac(fx(TOX))
    t = df["Time (sec)"].values
    step = float(np.median(np.diff(t)))
    gaps = np.round(np.diff(t) / step).astype(int) - 1
    assert int((gaps > 0).sum()) == 26 and int(gaps.max()) == 66
    assert 200 <= int(gaps.sum()) <= 230
    assert t[0] == pytest.approx(12.2585)
    assert not df.isna().any().any()                           # absent rows, not NaN rows


def test_toxtrac_frozen_events_header_misspells_length(fx):
    header = open(fx("FrozenEvents_1.txt")).readline().rstrip("\n").split("\t")
    assert header == ["Time (sec)", "Arena", "Track", "Avg. Pos. X (mm)", "Avg. Pos. Y (mm)", "Time Lenght (sec)"]


def test_toxtrac_stats_file_alternates_name_and_value_lines(fx):
    st = O.read_toxtrac_stats(fx("Stats_1.txt"))
    assert st["Video Resolution"] == "[1920 x 1080]"
    assert float(st["Video FrameRate"]) == pytest.approx(29.8568)
    assert int(st["Analysed Video Frames"]) == 18034
    t = O.read_toxtrac(fx(TOX))["Time (sec)"].values
    assert 1 / float(np.median(np.diff(t))) == pytest.approx(float(st["Video FrameRate"]), rel=0.01)


# =============================================================== cross-tracker agreement (same video)
def _trex_old_points(fx, frame):
    pts = []
    for m in O.trex_npz_files([fx(n) for n in OLD]).values():
        j = np.where(m["frame"].astype(int) == frame)[0]
        if len(j) and np.isfinite(m["X"][j[0]]):
            pts.append((m["X"][j[0]], m["Y"][j[0]]))
    return np.array(pts)


def _animalta_points(fx, frame):
    o = O.oracle_animalta(fx(ATA)).xy
    return o[frame, :, 0, :]


@pytest.mark.parametrize("frame", [0, 3000, 9000])
def test_trex_and_animalta_share_the_same_pixel_frame(fx, frame):
    assert O.median_nn(_animalta_points(fx, frame), _trex_old_points(fx, frame)) < 15.0


@pytest.mark.parametrize("frame", [0, 3000, 9000])
def test_ctrax_y_is_measured_from_the_bottom(fx, frame):
    """After y' = 2160 - y Ctrax agrees with AnimalTA; without the flip it does not."""
    m = O.read_ctrax(fx(CTX))
    ata = _animalta_points(fx, frame)
    assert O.median_nn(ata, O.ctrax_points(m, frame, height=2160)) < 2.0
    assert O.median_nn(ata, O.ctrax_points(m, frame, height=None)) > 100.0


def test_frame_counts_agree_across_trackers(fx):
    n_ata = len(O.read_animalta(fx(ATA)))
    n_ctx = len(O.read_ctrax(fx(CTX))["ntargets"])
    longest_trex = max(len(m["frame"]) for m in O.trex_npz_files([fx(n) for n in OLD]).values())
    assert n_ata == n_ctx == 12033
    assert longest_trex == 12024 < n_ata
