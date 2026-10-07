# -*- coding: utf-8 -*-
"""창이 나타나거나 제목이 바뀔 때 Windows 가 알려 주는 이벤트(SetWinEventHook)를 받는다 — 폴링이 아니다.

    ev = WindowEvents(lambda hwnd, kind: q.put((hwnd, kind)))
    ev.start()        # 별도 스레드에서 훅을 걸고 메시지 루프를 돈다
    ...
    ev.stop()

kind: 'show'(창이 보이게 됨) · 'name'(제목이 바뀜). 콜백은 훅 스레드에서 불리므로 가볍게 큐에 넣기만 하고 끝낸다.
WINEVENT_OUTOFCONTEXT 라서 다른 프로세스에 DLL 을 심지 않는다(관리자 권한도 필요 없다).
"""
import ctypes
import ctypes.wintypes as wt
import threading

EVENT_OBJECT_SHOW = 0x8002
EVENT_OBJECT_NAMECHANGE = 0x800C
WINEVENT_OUTOFCONTEXT = 0x0
WINEVENT_SKIPOWNPROCESS = 0x2
OBJID_WINDOW = 0
CHILDID_SELF = 0
WM_QUIT = 0x0012

_user32 = ctypes.WinDLL('user32', use_last_error=True)
_kernel32 = ctypes.WinDLL('kernel32')
_PROC = ctypes.WINFUNCTYPE(None, wt.HANDLE, wt.DWORD, wt.HWND, wt.LONG, wt.LONG, wt.DWORD, wt.DWORD)
_user32.SetWinEventHook.argtypes = [wt.DWORD, wt.DWORD, wt.HMODULE, _PROC, wt.DWORD, wt.DWORD, wt.DWORD]
_user32.SetWinEventHook.restype = wt.HANDLE
_user32.UnhookWinEvent.argtypes = [wt.HANDLE]
_user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
_user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
_user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
_user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
_kernel32.GetCurrentThreadId.restype = wt.DWORD


class WindowEvents:
    def __init__(self, on_event, names=True):
        self._on_event = on_event
        self._names = names
        self._thread = None
        self._tid = None
        self._ready = threading.Event()
        self._error = None
        self._proc = _PROC(self._callback)          # 참조를 들고 있어야 GC 되지 않는다

    def _callback(self, hook, event, hwnd, id_object, id_child, thread, time_ms):
        if hwnd and id_object == OBJID_WINDOW and id_child == CHILDID_SELF:
            try:
                self._on_event(hwnd, 'show' if event == EVENT_OBJECT_SHOW else 'name')
            except Exception:
                pass

    def _run(self):
        self._tid = _kernel32.GetCurrentThreadId()
        hooks = []
        try:
            kinds = [EVENT_OBJECT_SHOW] + ([EVENT_OBJECT_NAMECHANGE] if self._names else [])
            for ev in kinds:
                h = _user32.SetWinEventHook(ev, ev, None, self._proc, 0, 0, WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)
                if not h:
                    raise OSError(ctypes.get_last_error(), 'SetWinEventHook 실패')
                hooks.append(h)
        except Exception as e:
            self._error = e
            self._ready.set()
            return
        self._ready.set()
        msg = wt.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:      # 훅 알림은 이 메시지 루프로 전달된다
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))
        for h in hooks:
            _user32.UnhookWinEvent(h)

    def start(self):
        self._thread = threading.Thread(target=self._run, name='winevents', daemon=True)
        self._thread.start()
        self._ready.wait(5)
        if self._error:
            raise self._error
        return self

    def stop(self):
        if self._tid:
            _user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
