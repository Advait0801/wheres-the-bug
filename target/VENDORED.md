# Vendored target

The `toolz` package, its `tlz` compatibility alias, and its tests are vendored
from the upstream `1.1.0` tag. A minimal distribution metadata file preserves
the upstream package's `importlib.metadata`-based version lookup without
installing a second copy from PyPI.

- Repository: https://github.com/pytoolz/toolz
- Tag: `1.1.0`
- Commit: `568c2b8393973cd172a466546c9d95779c452438`
- License: BSD 3-Clause (`target/LICENSE.txt`)

Keeping the source and tests in this repository makes benchmark generation
independent of whichever `toolz` version may be installed in the environment.
