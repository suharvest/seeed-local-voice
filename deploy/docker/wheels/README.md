# Operator-supplied wheels for `Dockerfile.rpi --target final-hailo`

This directory is empty in git on purpose. The `final-hailo` stage needs the
HailoRT Python bindings, and Hailo distributes them only through the Hailo
Developer Zone (login-gated) — the wheel cannot be committed or fetched from
PyPI.

Place one file here before building `final-hailo`:

    hailort-<version>-cp311-cp311-linux_aarch64.whl

`cp311` because the image is `debian:12-slim` (Python 3.11), `aarch64` because
it runs on the board.

## The version must equal the host's

`hailort` ships a Python extension (`_pyhailort`) that dlopens
`libhailort.so.<version>`. That shared object is **not** baked into the image:
it is bind-mounted from the host at run time, because it has to match the
kernel PCIe driver the host loaded. A version skew between the wheel and the
host library fails at import, or later inside `VDevice`.

Check the board first:

    hailortcli fw-control identify     # -> Firmware Version: 4.21.0
    dpkg -l | grep hailort             # -> hailort 4.21.0, hailort-pcie-driver 4.21.0

then build and run with that same version:

    docker build -f deploy/docker/Dockerfile.rpi --target final-hailo \
      --build-arg HAILORT_WHEEL=hailort-4.21.0-cp311-cp311-linux_aarch64.whl \
      -t openvoicestream:rpi-hailo .

    docker run --device /dev/hailo0 \
      -v /usr/lib/libhailort.so.4.21.0:/usr/lib/libhailort.so.4.21.0:ro \
      -v ~/models:/opt/models -p 8621:8000 openvoicestream:rpi-hailo

`/dev/hailo0` is granted to a single process: stop any other container holding
it first, or `VDevice` raises `HAILO_OUT_OF_PHYSICAL_DEVICES (74)`.
