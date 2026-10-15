"""Ricezione UDP: un thread tiene l'ULTIMA posa valida, la coda delle pose accettate e le statistiche. Niente maya.

Chi applica (maya_bridge) chiama `drain_recent()` dal main thread alla sua frequenza: ogni posa passa da sessione e
take, la camera prende l'ultima. I comandi arrivano a una callback, chiamata nel thread di ricezione: la callback
deve solo accodare, non toccare Maya.

Pairing (F4.1): con `expected_token` impostato, un mittente e' «abbinato» solo dopo un comando col token giusto
(il telefono manda PING ogni secondo); le pose di mittenti non abbinati, o abbinati da piu' di PAIR_TTL_S, si
scartano e si contano in `stats.unpaired`. Con `expected_token=None` chiunque sulla LAN muove la camera.

Orologio: `time.perf_counter()`, non `time.monotonic()` (su Windows ha un passo di 15,6 ms: misurato nel banco F1.8).
"""

from __future__ import annotations

import logging
import select
import socket
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from magicam import protocol
from magicam.protocol import CommandMessage, PoseMessage, ProtocolError

log = logging.getLogger("magicam.receiver")

DEFAULT_PORT = 9000
RECV_BUFFER = 256 * 1024
LATENCY_WINDOW = 120  # campioni (~2 s a 60 Hz) per stimare l'offset fra orologi
STALE_AFTER_S = 0.5  # senza pacchetti per piu' di cosi' lo stato e' «perso»
PAIR_TTL_S = 3.0  # un abbinamento vale per cosi' tanto dopo l'ultimo comando col token
RECENT_MAXLEN = 1024  # pose accettate in attesa del tick (~17 s a 60 Hz): la take le vuole TUTTE


@dataclass
class Stats:
    received: int = 0  # pose valide accettate
    lost: int = 0  # buchi di seq (pacchetti mai arrivati)
    reordered: int = 0  # pose arrivate con seq minore dell'ultima accettata: scartate
    rejected: int = 0  # ProtocolError o token sbagliato
    unpaired: int = 0  # pose da mittenti non abbinati (solo con expected_token)
    commands: int = 0
    last_seq: int | None = None
    last_recv_mono: float | None = None  # time.perf_counter() dell'ultima posa accettata
    _offsets: deque[float] = field(default_factory=lambda: deque(maxlen=LATENCY_WINDOW), repr=False)
    latency_ms: float = 0.0

    def note_latency(self, t_sensor: float, t_recv: float) -> None:
        # offset = t_recv - t_sensor; il minimo su una finestra e' la stima dell'offset fra orologi + latenza minima
        d = t_recv - t_sensor
        self._offsets.append(d)
        base = min(self._offsets)
        self.latency_ms = (d - base) * 1000.0

    def is_stale(self, now: float) -> bool:
        return self.last_recv_mono is None or (now - self.last_recv_mono) > STALE_AFTER_S

    def silence_s(self, now: float) -> float | None:
        return None if self.last_recv_mono is None else now - self.last_recv_mono


class Receiver:
    def __init__(
        self,
        port: int = DEFAULT_PORT,
        host: str = "0.0.0.0",
        on_command: Callable[[CommandMessage, tuple[str, int]], None] | None = None,
        expected_token: int | None = None,
    ) -> None:
        self.port = port
        self.host = host
        self.on_command = on_command
        self.expected_token = expected_token
        self.stats = Stats()
        self._lock = threading.Lock()
        self._latest: tuple[PoseMessage, float] | None = None
        self._recent: deque[PoseMessage] = deque(maxlen=RECENT_MAXLEN)
        self._last_sender: tuple[str, int] | None = None
        self._paired: dict[tuple[str, int], float] = {}  # mittente -> perf_counter dell'ultimo token giusto
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    # --- ciclo di vita ---------------------------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            raise RuntimeError("receiver gia' avviato")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # niente SO_REUSEADDR: su Windows permetterebbe a due receiver di dividersi la porta in silenzio;
        # meglio un OSError chiaro (F1.8: un receiver orfano in Maya sarebbe rimasto a rubare pacchetti)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, RECV_BUFFER)
        sock.bind((self.host, self.port))
        sock.setblocking(False)
        self.port = sock.getsockname()[1]  # utile con port=0
        self._sock = sock
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="magicam-receiver", daemon=True)
        self._thread.start()
        log.info("in ascolto su %s:%d", self.host, self.port)

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    @property
    def running(self) -> bool:
        return self._running

    # --- lettura dal main thread -------------------------------------------------------------------------------

    def latest(self) -> tuple[PoseMessage, float] | None:
        """Ultima posa accettata e il perf_counter della ricezione; None se nessuna."""
        with self._lock:
            return self._latest

    def drain_recent(self) -> list[PoseMessage]:
        """Tutte le pose accettate dall'ultima chiamata, in ordine di seq: il tick le da' a sessione e take.

        Misurato (F1.8, 2026-10-15): tick e sorgente entrambi a 60 Hz battono; con la sola `latest()` il 19% delle
        pose non arrivava alla take e il filtro vedeva dt irregolari.
        """
        with self._lock:
            items = list(self._recent)
            self._recent.clear()
        return items

    def last_sender(self) -> tuple[str, int] | None:
        with self._lock:
            return self._last_sender

    def paired_senders(self, now: float | None = None) -> list[tuple[str, int]]:
        now = time.perf_counter() if now is None else now
        with self._lock:
            return [a for a, t in self._paired.items() if now - t <= PAIR_TTL_S]

    def send_to_sender(self, data: bytes) -> bool:
        """Manda un datagramma all'ultimo mittente accettato (stats per il telefono). False se nessuno."""
        with self._lock:
            dest = self._last_sender
            sock = self._sock
        if dest is None or sock is None:
            return False
        sock.sendto(data, dest)
        return True

    # --- thread ----------------------------------------------------------------------------------------------

    def _loop(self) -> None:
        sock = self._sock
        assert sock is not None
        while self._running:
            try:
                ready, _, _ = select.select([sock], [], [], 0.05)
            except (OSError, ValueError):
                break  # socket chiuso da stop()
            if not ready:
                continue
            # svuota la coda del kernel: tiene l'ultima posa, non media niente
            while self._running:
                try:
                    data, addr = sock.recvfrom(2048)
                except BlockingIOError:
                    break
                except OSError:
                    return
                self._handle(data, addr, time.perf_counter())

    def _handle(self, data: bytes, addr: tuple[str, int], now: float) -> None:
        try:
            msg = protocol.unpack(data)
        except ProtocolError as e:
            self.stats.rejected += 1
            log.debug("rifiutato da %s: %s", addr, e)
            return
        if isinstance(msg, PoseMessage):
            if not self._is_paired(addr, now):
                self.stats.unpaired += 1
                return
            self._accept_pose(msg, addr, now)
        elif isinstance(msg, CommandMessage):
            if self.expected_token is not None:
                if msg.token != self.expected_token:
                    self.stats.rejected += 1
                    log.warning("comando %s con token sbagliato da %s", msg.cmd.name, addr)
                    return
                with self._lock:
                    self._paired[addr] = now
            self.stats.commands += 1
            with self._lock:
                self._last_sender = addr
            if self.on_command is not None:
                self.on_command(msg, addr)
        # StatsMessage in ingresso: non previsto dal telefono, ignorato ma non contato come errore

    def _is_paired(self, addr: tuple[str, int], now: float) -> bool:
        if self.expected_token is None:
            return True
        with self._lock:
            t = self._paired.get(addr)
        return t is not None and now - t <= PAIR_TTL_S

    def _accept_pose(self, msg: PoseMessage, addr: tuple[str, int], now: float) -> None:
        st = self.stats
        if st.last_seq is not None:
            gap = (msg.seq - st.last_seq) & 0xFFFFFFFF
            if gap == 0 or gap > 0x7FFFFFFF:
                st.reordered += 1  # duplicato o vecchio: l'ultima posa resta la piu' recente
                return
            if gap > 1:
                st.lost += gap - 1
        st.last_seq = msg.seq
        st.received += 1
        st.last_recv_mono = now
        st.note_latency(msg.t_sensor, now)
        with self._lock:
            self._latest = (msg, now)
            self._recent.append(msg)
            self._last_sender = addr
