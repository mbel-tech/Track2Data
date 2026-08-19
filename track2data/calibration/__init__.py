"""Calibration subsystem (px↔cm and body-length normalisation).

Public API re-exported here for convenient imports:

    from track2data.calibration import apply_scalar_calibration
    from track2data.calibration import apply_bodylength_calibration
"""

from track2data.calibration.bodylength import apply_bodylength_calibration
from track2data.calibration.scalar import apply_scalar_calibration, px_to_bl, px_to_cm

__all__ = [
    "apply_bodylength_calibration",
    "apply_scalar_calibration",
    "px_to_bl",
    "px_to_cm",
]
