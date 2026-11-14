"""Сколько секунд назад Windows создала этот процесс: время запуска atlas.exe до первой строки Python (14.11.2026)."""
from __future__ import annotations


def age_seconds():
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32")
    creation, exited, kernel_time, user_time, now = (wintypes.FILETIME() for _ in range(5))
    get_process = kernel.GetCurrentProcess
    get_process.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    if not kernel.GetProcessTimes(get_process(), ctypes.byref(creation), ctypes.byref(exited),
                                  ctypes.byref(kernel_time), ctypes.byref(user_time)):
        return None
    kernel.GetSystemTimeAsFileTime(ctypes.byref(now))

    def ticks(value):  # FILETIME — сотни наносекунд
        return (value.dwHighDateTime << 32) | value.dwLowDateTime

    return (ticks(now) - ticks(creation)) / 1e7
