"""Main module"""
import sys
# For whatever reason this is needed to get the logging system to start properly when
# run from uv run.
sys.path.pop(0)

import j2live.app
sys.exit(j2live.app.main(sys.argv))