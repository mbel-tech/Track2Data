import argparse
import csv
import json
import pickle
import sys
from pathlib import Path

import numpy as np

# Try to import idtrackerai if available, otherwise we'll try to rely on pickle
try:
    from idtrackerai.list_of_blobs import ListOfBlobs
except ImportError:
    ListOfBlobs = None


def load_list_of_blobs(path: Path):
    """
    Robustly load list_of_blobs.pickle.
    Prefers ListOfBlobs.load(path) if class is available,
    otherwise standard pickle.load.
    """
    path = str(path)
    if ListOfBlobs is not None and hasattr(ListOfBlobs, "load"):
        try:
            return ListOfBlobs.load(path)
        except Exception:
            pass

    with open(path, "rb") as f:
        return pickle.load(f)


def get_bbox_diag_px(blob):
    """
    Get diagonal length of bbox in pixels.
    Prefers blob.extension if available.
    """
    if hasattr(blob, "extension") and blob.extension is not None:
        try:
            return float(blob.extension)
        except (TypeError, ValueError):
            pass

    # Fallback: try to compute from contours
    try:
        if hasattr(blob, "contours") and blob.contours is not None and len(blob.contours) > 0:
            all_points = np.vstack(blob.contours)
            if len(all_points) > 0:
                x_min, y_min = np.min(all_points, axis=0)
                x_max, y_max = np.max(all_points, axis=0)
                dx = x_max - x_min
                dy = y_max - y_min
                return float(np.sqrt(dx**2 + dy**2))
    except Exception:
        pass

    return None


def process_session(session_path, output_dir):
    session_path = Path(session_path)
    session_id = session_path.name
    output_dir = Path(output_dir)

    # Paths
    lob_path = session_path / "preprocessing" / "list_of_blobs.pickle"
    attrs_path = session_path / "trajectories" / "trajectories_csv" / "attributes.json"

    summary = {
        "session_id": session_id,
        "status": "skipped",
        "reason": "",
        "n_frames_in_blobs": 0,
        "n_rows_written": 0,
        "metadata": {}
    }

    # 0. Check requirements
    if not lob_path.exists():
        summary["reason"] = "Missing list_of_blobs.pickle"
        return summary

    if not attrs_path.exists():
        summary["reason"] = "Missing attributes.json"
        return summary

    # 1. Load Metadata
    try:
        with open(attrs_path, encoding="utf-8") as f:
            attrs = json.load(f)

        length_unit = attrs.get("length_unit", 0)
        fps = attrs.get("frames_per_second", None)

        try:
            length_unit = float(length_unit)
            if not (length_unit > 0):
                length_unit = None
        except Exception:
            length_unit = None

        summary["metadata"] = {"length_unit": length_unit, "fps": fps}

    except Exception as e:
        summary["reason"] = f"Error loading attributes: {e}"
        return summary

    # 2. Load Blobs
    try:
        lob = load_list_of_blobs(lob_path)
        n_frames = lob.number_of_frames
        blobs_in_video = lob.blobs_in_video
        summary["n_frames_in_blobs"] = int(n_frames)
    except Exception as e:
        summary["reason"] = f"Error loading blobs: {e}"
        return summary

    # 3. Iterate Frames
    candidate_rows = []

    exclusion_counts = {
        "no_identity": 0,
        "crossing_filtered": 0,
        "missing_bbox": 0,
        "multiple_candidates_dropped": 0
    }

    for f in range(n_frames):
        blobs_in_frame = blobs_in_video[f]
        frame_candidates = {}  # { identity: [candidates] }

        for blob in blobs_in_frame:
            # Identity extraction
            identities = []
            if hasattr(blob, "final_identities") and blob.final_identities:
                identities = blob.final_identities
            elif hasattr(blob, "identity") and blob.identity is not None:
                identities = [blob.identity]

            valid_identities = []
            for ident in identities:
                try:
                    valid_identities.append(int(ident))
                except (ValueError, TypeError):
                    continue

            if not valid_identities:
                exclusion_counts["no_identity"] += 1
                continue

            # Metrics
            body_length_px = get_bbox_diag_px(blob)

            # CM conversion if possible
            body_length_cm = None
            if body_length_px is not None and length_unit is not None:
                body_length_cm = body_length_px / length_unit

            # QC Flags
            is_ind = getattr(blob, "is_an_individual", None)
            is_cross = getattr(blob, "is_a_crossing", None)

            if is_ind is None:
                is_ind = (len(valid_identities) == 1)
            if is_cross is None:
                is_cross = not is_ind

            certainty = getattr(blob, "identity_certainty", None)
            area = getattr(blob, "area", None)

            for ident in valid_identities:
                cand = {
                    "session_id": session_id,
                    "frame": int(f),
                    "identity": int(ident),
                    "body_length_px": body_length_px,
                    "body_length_cm": body_length_cm,
                    "is_individual": bool(is_ind) if is_ind is not None else None,
                    "is_crossing": bool(is_cross) if is_cross is not None else None,
                    "identity_certainty": certainty,
                    "area_px": area,
                    "_n_ids": len(valid_identities),
                }

                if body_length_px is None:
                    exclusion_counts["missing_bbox"] += 1
                    continue

                frame_candidates.setdefault(ident, []).append(cand)

        # 4. Resolve Conflicts (per identity, per frame)
        for _ident, cands in frame_candidates.items():
            individuals = [c for c in cands if c.get("is_individual") is True]
            valid_cands = individuals if individuals else []

            if not valid_cands:
                exclusion_counts["crossing_filtered"] += 1
                continue

            if len(valid_cands) > 1:
                valid_cands.sort(key=lambda x: (x["_n_ids"], x["body_length_px"]))
                exclusion_counts["multiple_candidates_dropped"] += (len(valid_cands) - 1)
                selected = valid_cands[0]
            else:
                selected = valid_cands[0]

            selected.pop("_n_ids", None)
            candidate_rows.append(selected)

    # 5. Write CSV
    output_dir.mkdir(parents=True, exist_ok=True)

    if not candidate_rows:
        summary["status"] = "completed_empty"
        summary["reason"] = "No valid rows extracted"
    else:
        candidate_rows.sort(key=lambda x: (x["frame"], x["identity"]))

        out_name = f"{session_id}_bboxes.csv"
        out_path = output_dir / out_name

        fieldnames = [
            "session_id", "frame", "identity",
            "body_length_px", "body_length_cm",
            "is_individual", "is_crossing",
            "identity_certainty", "area_px"
        ]

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(candidate_rows)

        summary["n_rows_written"] = len(candidate_rows)
        summary["status"] = "completed"

        # Per identity stats
        ident_stats = {}
        rows_by_id = {}
        for r in candidate_rows:
            i = r["identity"]
            rows_by_id.setdefault(i, []).append(r["body_length_cm"])

        for ident, values in rows_by_id.items():
            vals = np.array([v for v in values if v is not None], dtype=float)
            if len(vals) == 0:
                stats = {"n_frames": 0}
            else:
                q25, q50, q75 = np.percentile(vals, [25, 50, 75])
                stats = {
                    "n_frames": len(vals),
                    "pct_valid": round(len(vals) / float(n_frames) * 100, 2),
                    "median_body_length_cm": round(float(q50), 4),
                    "iqr_body_length_cm": round(float(q75 - q25), 4),
                }
            ident_stats[int(ident)] = stats

        summary["identity_stats"] = ident_stats

    summary["exclusion_counts"] = exclusion_counts

    # 6. Write Summary JSON
    sum_name = f"{session_id}_bboxes_summary.json"
    with open(output_dir / sum_name, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return summary


def main():
    ap = argparse.ArgumentParser(
        description="Extract per-frame bbox proxy lengths from idtracker.ai list_of_blobs.pickle"
    )
    ap.add_argument("--session_dir", required=True, help="Path to one session_* folder")
    ap.add_argument(
        "--out_dir", required=True,
        help="Folder where to write <session_id>_bboxes.csv and summary",
    )
    args = ap.parse_args()

    session = Path(args.session_dir)
    out_dir = Path(args.out_dir)

    if not session.exists() or not session.is_dir():
        print(f"Session not found or not a folder: {session}", file=sys.stderr)
        sys.exit(2)

    print(f"Processing {session.name}...")
    res = process_session(session, out_dir)
    print(f"  -> {res['status']} ({res['n_rows_written']} rows)")
    if res.get("reason"):
        print(f"     Reason: {res['reason']}")

    # non-zero only for real failures
    if res["status"] not in ("completed", "completed_empty"):
        sys.exit(3)


if __name__ == "__main__":
    main()
