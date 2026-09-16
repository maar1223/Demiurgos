# -*- coding: utf-8 -*-
"""Transport implementations for the backup engine.

``base`` declares the :class:`~backup.transport.base.BackupTransport` contract;
``folder`` (WU-5/WU-6) supplies the MVP local-folder implementation. The engine
drives the protocol only, so a later transport can be added without reworking
it (REQ-BE-8).
"""
