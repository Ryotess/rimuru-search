# src/vector_search/utils.py
import numpy as np
from numpy.typing import NDArray


def to_float32(vec: list[float]) -> NDArray[np.float32]:
    """
    Turn list of float vector into float32 np array
    """
    return np.asarray(vec, dtype=np.float32)
