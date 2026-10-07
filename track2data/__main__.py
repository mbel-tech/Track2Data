"""``python -m track2data`` runs the command-line interface.

Useful where the ``track2data`` console script points at a different installation than the
code you are working in: ``python -m`` always runs the package on the current path.
"""

from track2data.cli import main

if __name__ == "__main__":
    main()
