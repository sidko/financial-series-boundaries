# Releasing

After `main` CI passes, push the matching `v<version>` tag over SSH. The release
workflow checks out the event SHA, verifies the version, runs the public tests
and example, then builds the distribution. Existing PyPI files must normalize to
the same contents as the build; matching partial files are skipped safely. A
GitHub Release is created only after PyPI succeeds.
