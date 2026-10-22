"""python -m ecoscribe.callprobe [--seconds N] [--raw]: print the call-detection signals live (dictado-nhn).

Who is on the mic (and plays sound), the app in front, whether a meeting tab title is in a browser window
(never the title itself), what the detector makes of it. Records nothing. On the Mac, --raw also lists every
audio process with its bundle id and the app it counts as. detect.py can't be the -m target itself: its
platform readers import it back.
"""
from ecoscribe.detect import main

if __name__ == "__main__":
    raise SystemExit(main())
