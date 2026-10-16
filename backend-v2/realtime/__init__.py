"""Shared primitives for authenticated sessions and voice configuration.

Only the pieces the platform depends on live here today: token signing
(`realtime.auth`) and the supported-language / voice registry
(`realtime.voices`). The live-voice transport is not part of this package yet;
`main_clinical` mounts it only when its modules are present.
"""
