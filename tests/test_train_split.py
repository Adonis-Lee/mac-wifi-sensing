import pytest
from app import train


def test_refuses_without_three_subjects(monkeypatch):
    import numpy as np
    monkeypatch.setattr(train, "dataset", lambda **k: (np.zeros((4, 13)), np.array(["A"] * 4),
                                                        np.array(["S1", "S1", "S2", "S2"]), np.array(["e"] * 4)))
    with pytest.raises(SystemExit):
        train.main(["--test", "S2", "--val", "S1"])
