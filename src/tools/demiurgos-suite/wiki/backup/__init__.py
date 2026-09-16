# -*- coding: utf-8 -*-
"""Backup package — provider-agnostic write-side engine (WU-4 … WU-16).

The engine writes a backup tree into a folder the user already syncs. It never
talks to a cloud API and never claims an upload: every module here reports the
LOCAL write only (REQ-SF-4). The package is additive — nothing imports it until
the engine slices land, so removing this directory reverts the change cleanly.
"""
