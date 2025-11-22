"""
Utility functions for astronomical calculations and data transformations.
"""
import numpy as np


def time_to_phase(time, period, t0=0.0):
    """
    Convert time to orbital phase in the range [-0.5, 0.5].

    Parameters:
    -----------
    time : array-like
        Time values (e.g., BJD)
    period : float
        Orbital period in same units as time
    t0 : float, optional
        Reference time (epoch), default is 0.0

    Returns:
    --------
    array-like
        Phase values in range [-0.5, 0.5]
    """
    phase = ((time - t0) % period) / period
    # Convert from [0, 1] to [-0.5, 0.5]
    phase = np.where(phase > 0.5, phase - 1.0, phase)
    return phase


def alias_data(data, extend_range=0.1):
    phase = data[:, 0]
    mask_left = (phase >= -0.5) & (phase < -0.5 + extend_range)
    mask_right = (phase > 0.5 - extend_range) & (phase <= 0.5)

    # Copy left edge to right extension
    left_copied = data[mask_left].copy()
    left_copied[:, 0] = left_copied[:, 0] + 1.0  # e.g., -0.45 -> 0.55

    # Copy right edge to left extension
    right_copied = data[mask_right].copy()
    right_copied[:, 0] = right_copied[:, 0] - 1.0  # e.g., 0.45 -> -0.55

    # Concatenate original and aliased data
    aliased = np.concatenate([data, left_copied, right_copied], axis=0)

    # Optionally, sort by phase
    aliased = aliased[np.argsort(aliased[:, 0])]

    return aliased


def flux_to_magnitude(flux, zero_point=0.0):
    """
    Convert flux to magnitude.

    Parameters:
    -----------
    flux : array-like
        Flux values
    zero_point : float, optional
        Magnitude zero point, default is 0.0

    Returns:
    --------
    array-like
        Magnitude values
    """
    return -2.5 * np.log10(flux) + zero_point


def magnitude_to_flux(magnitude, zero_point=0.0):
    """
    Convert magnitude to flux.

    Parameters:
    -----------
    magnitude : array-like
        Magnitude values
    zero_point : float, optional
        Magnitude zero point, default is 0.0

    Returns:
    --------
    array-like
        Flux values
    """
    return 10**(-0.4 * (magnitude - zero_point))


def magnitude_error_to_flux_error(flux, mag_error):
    """
    Convert magnitude error to flux error.

    Parameters:
    -----------
    flux : array-like
        Flux values
    mag_error : array-like
        Magnitude error values

    Returns:
    --------
    array-like
        Flux error values
    """
    return flux * mag_error * np.log(10) / 2.5
