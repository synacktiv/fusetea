import os
import re
import subprocess

from setuptools import setup

HERE = os.path.dirname(os.path.abspath(__file__))


def get_version():
    # Same scheme as the Makefile: <VERSION>.<number of commits>
    try:
        count = subprocess.check_output(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=HERE,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        with open(os.path.join(HERE, "VERSION")) as f:
            return f"{f.read().strip()}.{count}"
    except (OSError, subprocess.CalledProcessError):
        pass

    # Building from an sdist: no git history, reuse the version baked in
    with open(os.path.join(HERE, "PKG-INFO")) as f:
        return re.search(r"^Version: (.+)$", f.read(), re.M).group(1)


setup(version=get_version())
