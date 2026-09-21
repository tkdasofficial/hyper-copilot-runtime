"""
Root proxy for backward compatibility.
Delegates to mini-editor/render.py while keeping the short-form logic intact.
"""
import os
import sys

mini_editor_dir = os.path.join(os.path.dirname(__file__), "mini-editor")
sys.path.insert(0, mini_editor_dir)

import render

if __name__ == "__main__":
    sys.exit(render.main())
