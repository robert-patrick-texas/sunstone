"""``sunstone self-update``: install a newer signed release, and roll back.

Releases come from GitHub: the ``.deb``, ``SHA256SUMS``, and an SSH
signature over it, checked against the signers the installed package ships
before anything changes. The update backs up the configuration and saved
state, installs with apt, checks the new version, and rolls back if it
fails. Modelled on vakr's updater, without its timer, proxy settings, or
trusted-CA management.
"""
