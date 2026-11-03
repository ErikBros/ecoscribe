"""The speakers pass next to a call on the Mac (dictado-692): room = enough free memory, which the GPU shares."""
import sys

import pytest

from ecoscribe.platform.macos import speakers

GB32 = 32 * 2**30


def reader(level, total=GB32):
    return lambda name: {"kern.memorystatus_level": level, "hw.memsize": total}[name]


def test_room_when_enough_memory_is_free():
    assert speakers.free_mb(reader(50)) == 16384
    assert speakers.gpu_room(read=reader(50))  # 16 GB free
    assert not speakers.gpu_room(read=reader(15))  # under 5 GB free
    assert not speakers.gpu_room(read=reader(70, 8 * 2**30))  # an 8 GB Mac with 5.6 GB free


def test_unknown_memory_waits_for_the_call_to_end():
    assert not speakers.gpu_room(read=lambda name: None)


@pytest.mark.skipif(sys.platform != "darwin", reason="sysctl on macOS")
def test_reads_this_mac():
    free = speakers.free_mb()
    assert free is not None and free > 0
