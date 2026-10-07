"""Une seule instance du bot par broker : une seconde instance doit être refusée."""

import subprocess
import sys

from superbot.main import _acquire_single_instance_lock


def test_second_instance_is_refused_while_first_holds_lock():
    lock = _acquire_single_instance_lock("testbroker")
    assert lock is not None
    try:
        # Un autre processus (même LOG_DIR via l'environnement de test) ne doit pas obtenir le verrou
        code = ("from superbot.main import _acquire_single_instance_lock as a; "
                "import sys; sys.exit(0 if a('testbroker') is None else 1)")
        assert subprocess.run([sys.executable, "-c", code], timeout=60).returncode == 0
    finally:
        lock.close()
    # Verrou libéré : une nouvelle acquisition réussit
    again = _acquire_single_instance_lock("testbroker")
    assert again is not None
    again.close()
