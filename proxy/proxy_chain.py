"""Multi-hop proxy chaining via SOCKS / HTTP-CONNECT tunneling.

A :class:`ProxyChain` is an ordered list of :class:`Proxy` objects through
which a single outbound request is tunneled (``A -> B -> C -> target``).

Implementation notes
--------------------
* The first hop uses ``PySocks`` directly (it natively handles the SOCKS4 /
  SOCKS5 handshake).
* Each subsequent hop performs a manual protocol handshake over the already
  established tunnel:
    - SOCKS5  -> RFC 1928 (with optional user/pass auth per RFC 1929)
    - SOCKS4  -> the classic 9-byte request
    - HTTP    -> ``CONNECT host:port HTTP/1.1`` + read status line
* The resulting raw socket is then wrapped with ``http.client`` (and ``ssl``
  for HTTPS targets) to issue the actual HTTP request.  The
  ``http.client.HTTPResponse`` is repackaged as a ``requests.Response`` so
  callers can use the familiar API.

``PySocks`` is imported lazily inside :meth:`ProxyChain.send_request`; the
module itself is import-safe without it.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import socket
import ssl
import struct
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .proxy_manager import Proxy

logger = logging.getLogger(__name__)

# Map our protocol strings to PySocks' proxy type constants.
_PROXY_TYPE_MAP = {
    "socks4": 1,   # socks.PROXY_TYPE_SOCKS4
    "socks5": 2,   # socks.PROXY_TYPE_SOCKS5
    "http": 3,     # socks.PROXY_TYPE_HTTP
    "https": 3,    # treat https-upstream as HTTP CONNECT (TLS is end-to-end)
}


class ProxyChainError(RuntimeError):
    """Raised when a chained request cannot be completed."""


class ProxyChain:
    """Chain multiple proxies in series (A -> B -> C -> target).

    Example::

        chain = ProxyChain([proxy_a, proxy_b, proxy_c])
        resp = chain.send_request("GET", "https://httpbin.org/ip", timeout=30)
        print(resp.json())
    """

    def __init__(self, proxies: Optional[List[Proxy]] = None) -> None:
        """Initialise the chain.

        Args:
            proxies: Ordered list of proxies (entry -> exit).  May be empty;
                :meth:`send_request` will then raise :class:`ProxyChainError`.
        """
        self._proxies: List[Proxy] = list(proxies or [])
        self._lock = __import__("threading").RLock()

    # -- chain mutation ------------------------------------------------------
    @property
    def proxies(self) -> List[Proxy]:
        """Return a shallow copy of the chain."""
        with self._lock:
            return list(self._proxies)

    def add(self, p: Proxy) -> None:
        """Append ``p`` to the end of the chain."""
        with self._lock:
            self._proxies.append(p)
        logger.info("chain: appended %s (len=%d)", p.address, len(self._proxies))

    def remove(self, p: Proxy) -> bool:
        """Remove ``p`` from the chain.  Returns ``True`` if removed."""
        with self._lock:
            try:
                self._proxies.remove(p)
            except ValueError:
                return False
        logger.info("chain: removed %s (len=%d)", p.address, len(self._proxies))
        return True

    def reorder(self, new_order: List[Proxy]) -> None:
        """Reorder the chain to ``new_order`` (must contain the same proxies)."""
        with self._lock:
            if sorted(id(p) for p in new_order) != sorted(
                id(p) for p in self._proxies
            ):
                raise ValueError("new_order must contain exactly the same proxies")
            self._proxies = list(new_order)
        logger.info("chain: reordered (len=%d)", len(self._proxies))

    def __len__(self) -> int:
        with self._lock:
            return len(self._proxies)

    # -- validation ----------------------------------------------------------
    def validate_chain(
        self, test_host: str = "httpbin.org", test_port: int = 443, timeout: float = 15.0
    ) -> bool:
        """Open + close a chain socket to verify reachability.

        Args:
            test_host: Target host to probe.
            test_port: Target port.
            timeout: Connect timeout in seconds.
        """
        if not self._proxies:
            return False
        try:
            s = self._build_chain_socket(test_host, test_port, timeout=timeout)
            try:
                s.close()
            except Exception:  # pragma: no cover
                pass
            return True
        except Exception:
            logger.debug("chain validation failed", exc_info=True)
            return False

    # -- main entry point ----------------------------------------------------
    def send_request(
        self,
        method: str,
        url: str,
        timeout: float = 30.0,
        headers: Optional[Dict[str, str]] = None,
        body: Optional[bytes] = None,
        **kwargs: Any,
    ):
        """Send an HTTP(S) request through the chain.

        Args:
            method: HTTP verb (GET, POST, ...).
            url: Absolute URL (http:// or https://).
            timeout: Total timeout in seconds (per connect + per read).
            headers: Extra request headers.
            body: Optional request body (bytes).
            **kwargs: Ignored (for forward-compat with ``requests`` callers).

        Returns:
            ``requests.Response``.

        Raises:
            ProxyChainError: If the chain is empty or the request fails.
        """
        if not self._proxies:
            raise ProxyChainError("proxy chain is empty")

        try:
            import requests  # type: ignore  # noqa: F401  (for Response build)
        except Exception as exc:  # pragma: no cover
            raise ProxyChainError(f"requests is required: {exc}") from exc

        parsed = urlparse(url)
        if not parsed.hostname:
            raise ProxyChainError(f"invalid url (no host): {url!r}")
        dst_host = parsed.hostname
        dst_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        is_https = parsed.scheme.lower() == "https"
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        # 1) Build the multi-hop tunnel socket.
        chain_socket = self._build_chain_socket(dst_host, dst_port, timeout=timeout)

        # 2) Optionally wrap with TLS for HTTPS targets.
        if is_https:
            ctx = ssl.create_default_context()
            try:
                chain_socket = ctx.wrap_socket(chain_socket, server_hostname=dst_host)
            except Exception as exc:
                try:
                    chain_socket.close()
                except Exception:  # pragma: no cover
                    pass
                raise ProxyChainError(
                    f"TLS handshake through chain failed: {exc}"
                ) from exc

        # 3) Issue the HTTP request over the tunnel.
        try:
            return self._http_request(
                chain_socket, method, dst_host, dst_port, path, headers or {}, body, url
            )
        finally:
            try:
                chain_socket.close()
            except Exception:  # pragma: no cover
                pass

    # -- internals: tunnel construction -------------------------------------
    def _build_chain_socket(
        self, dst_host: str, dst_port: int, timeout: float = 30.0
    ) -> socket.socket:
        """Open a TCP socket that exits the last proxy bound for ``dst``.

        Each intermediate hop performs a manual protocol handshake over the
        already-established socket.
        """
        try:
            import socks  # type: ignore  # PySocks
        except Exception as exc:  # pragma: no cover
            raise ProxyChainError(
                "PySocks is required for proxy chaining (pip install PySocks)"
            ) from exc

        with self._lock:
            hops = list(self._proxies)
        if not hops:
            raise ProxyChainError("chain is empty")

        first = hops[0]
        ptype = _PROXY_TYPE_MAP.get(first.protocol)
        if ptype is None:
            raise ProxyChainError(f"unsupported protocol for first hop: {first.protocol}")

        # Layer 0: PySocks handles the first handshake + connects to next hop.
        sock = socks.socksocket()
        sock.set_proxy(
            ptype,
            first.host,
            first.port,
            username=first.username,
            password=first.password,
        )
        sock.settimeout(timeout)

        # Target list: each subsequent hop's address, then the final dst.
        targets: List[Tuple[str, int]] = [(h.host, h.port) for h in hops[1:]]
        targets.append((dst_host, dst_port))

        # The first connect goes to the second hop (or dst if single-hop).
        first_target = targets[0]
        try:
            logger.info(
                "chain hop 0/%d: %s via %s://%s",
                len(hops), f"{first_target[0]}:{first_target[1]}",
                first.protocol, first.address,
            )
            sock.connect(first_target)
        except Exception as exc:
            try:
                sock.close()
            except Exception:  # pragma: no cover
                pass
            raise ProxyChainError(
                f"first-hop connect via {first.address} failed: {exc}"
            ) from exc

        # Subsequent hops: manual handshake over the existing socket.
        for i, hop in enumerate(hops[1:], start=1):
            nxt_host, nxt_port = targets[i]
            logger.info(
                "chain hop %d/%d: %s via %s://%s",
                i, len(hops), f"{nxt_host}:{nxt_port}", hop.protocol, hop.address,
            )
            try:
                self._hop_handshake(sock, hop, nxt_host, nxt_port)
            except Exception as exc:
                try:
                    sock.close()
                except Exception:  # pragma: no cover
                    pass
                raise ProxyChainError(
                    f"hop {i} ({hop.address}) handshake failed: {exc}"
                ) from exc

        return sock

    # -- internals: per-hop handshakes --------------------------------------
    def _hop_handshake(
        self, sock: socket.socket, hop: Proxy, dst_host: str, dst_port: int
    ) -> None:
        """Extend an existing tunnel through ``hop`` to ``dst_host:dst_port``."""
        proto = hop.protocol.lower()
        if proto == "socks5":
            self._socks5_handshake(sock, hop, dst_host, dst_port)
        elif proto == "socks4":
            self._socks4_handshake(sock, hop, dst_host, dst_port)
        elif proto in ("http", "https"):
            self._http_connect_handshake(sock, hop, dst_host, dst_port)
        else:
            raise ProxyChainError(f"unsupported hop protocol: {proto}")

    @staticmethod
    def _recv_exact(sock: socket.socket, n: int) -> bytes:
        """Read exactly ``n`` bytes from ``sock`` (raises on EOF)."""
        buf = bytearray()
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ProxyChainError("socket closed during handshake")
            buf.extend(chunk)
        return bytes(buf)

    def _socks5_handshake(
        self, sock: socket.socket, hop: Proxy, dst_host: str, dst_port: int
    ) -> None:
        """Perform a SOCKS5 handshake over ``sock``."""
        # 1) greeting
        if hop.username:
            sock.sendall(b"\x05\x02\x00\x02")  # no-auth + user/pass
        else:
            sock.sendall(b"\x05\x01\x00")  # no-auth only
        resp = self._recv_exact(sock, 2)
        if resp[0] != 0x05:
            raise ProxyChainError(f"bad SOCKS5 version: {resp[0]}")
        method = resp[1]
        if method == 0x02:  # user/pass
            if not hop.username:
                raise ProxyChainError("server demands auth but none provided")
            u = (hop.username or "").encode()
            pw = (hop.password or "").encode()
            sock.sendall(
                b"\x01" + bytes([len(u)]) + u + bytes([len(pw)]) + pw
            )
            ar = self._recv_exact(sock, 2)
            if ar[1] != 0x00:
                raise ProxyChainError("SOCKS5 auth rejected")
        elif method != 0x00:
            raise ProxyChainError(f"SOCKS5 method not supported: {method}")
        # 2) request
        try:
            ip = socket.inet_aton(dst_host)
            req = b"\x05\x01\x00\x01" + ip + struct.pack(">H", dst_port)
        except OSError:  # hostname
            hb = dst_host.encode()
            req = b"\x05\x01\x00\x03" + bytes([len(hb)]) + hb + struct.pack(">H", dst_port)
        sock.sendall(req)
        head = self._recv_exact(sock, 4)
        if head[0] != 0x05 or head[1] != 0x00:
            raise ProxyChainError(f"SOCKS5 connect failed (code={head[1]})")
        atype = head[3]
        if atype == 0x01:
            self._recv_exact(sock, 4)
        elif atype == 0x03:
            ln = self._recv_exact(sock, 1)[0]
            self._recv_exact(sock, ln)
        elif atype == 0x04:
            self._recv_exact(sock, 16)
        else:
            raise ProxyChainError(f"SOCKS5 unknown atype={atype}")
        self._recv_exact(sock, 2)  # port

    def _socks4_handshake(
        self, sock: socket.socket, hop: Proxy, dst_host: str, dst_port: int
    ) -> None:
        """Perform a SOCKS4 handshake over ``sock`` (no identd)."""
        try:
            ip = socket.inet_aton(dst_host)
        except OSError:
            # SOCKS4a
            ip = b"\x00\x00\x00\x01"
            host_bytes = dst_host.encode()
        else:
            host_bytes = b""
        req = b"\x04\x01" + struct.pack(">H", dst_port) + ip + b"\x00" + host_bytes + b"\x00"
        sock.sendall(req)
        resp = self._recv_exact(sock, 8)
        if resp[0] != 0x00 or resp[1] != 0x5A:
            raise ProxyChainError(f"SOCKS4 connect failed (code={resp[1]})")

    def _http_connect_handshake(
        self, sock: socket.socket, hop: Proxy, dst_host: str, dst_port: int
    ) -> None:
        """Perform an HTTP CONNECT handshake over ``sock``."""
        target = f"{dst_host}:{dst_port}"
        lines = [f"CONNECT {target} HTTP/1.1", f"Host: {target}"]
        if hop.username:
            import base64

            token = base64.b64encode(
                f"{hop.username}:{hop.password or ''}".encode()
            ).decode()
            lines.append(f"Proxy-Authorization: Basic {token}")
        req = ("\r\n".join(lines) + "\r\n\r\n").encode()
        sock.sendall(req)
        # Read until end of headers.
        buf = bytearray()
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise ProxyChainError("CONNECT: socket closed before headers")
            buf.extend(chunk)
            if len(buf) > 8192:
                raise ProxyChainError("CONNECT: header too large")
        status_line = bytes(buf).split(b"\r\n", 1)[0].decode("latin-1", "ignore")
        if " 200 " not in status_line and not status_line.endswith(" 200"):
            raise ProxyChainError(f"CONNECT failed: {status_line}")

    # -- internals: HTTP request over tunnel --------------------------------
    def _http_request(
        self,
        sock: socket.socket,
        method: str,
        host: str,
        port: int,
        path: str,
        headers: Dict[str, str],
        body: Optional[bytes],
        url: str,
    ):
        """Issue an HTTP request over a pre-connected (and possibly TLS) socket.

        Returns a ``requests.Response``.
        """
        import http.client

        import requests  # type: ignore
        from requests.structures import CaseInsensitiveDict

        is_tls = isinstance(sock, ssl.SSLSocket)

        conn_cls = http.client.HTTPSConnection if is_tls else http.client.HTTPConnection

        class _TunneledConnection(conn_cls):  # type: ignore[misc, valid-type]
            """``http.client`` connection that uses a pre-made socket."""

            def __init__(self, host: str, port: int, sock: socket.socket) -> None:
                super().__init__(host, port, timeout=30.0)
                self._presock = sock

            def connect(self) -> None:  # noqa: D401
                self.sock = self._presock

        conn = _TunneledConnection(host, port, sock)
        h = {"Host": host if (port in (80, 443)) else f"{host}:{port}"}
        h.update(headers or {})
        if body is not None and "Content-Length" not in {k.title() for k in h}:
            h["Content-Length"] = str(len(body))
        conn.request(method, path, body=body, headers=h)
        raw_resp = conn.getresponse()

        # Repackage as a requests.Response.
        out = requests.Response()
        out.status_code = raw_resp.status
        out.reason = raw_resp.reason
        out.headers = CaseInsensitiveDict(raw_resp.getheaders())
        out._content = raw_resp.read()
        out.url = url
        out.request = requests.Request(method=method, url=url, headers=h).prepare()
        # No explicit encoding -> let requests guess.
        try:
            out.encoding = out.apparent_encoding
        except Exception:  # pragma: no cover
            pass
        try:
            conn.close()
        except Exception:  # pragma: no cover
            pass
        return out


# Convenience: build a chain from a list of ``host:port`` strings.
def chain_from_addresses(addresses: List[str], protocol: str = "socks5") -> ProxyChain:
    """Build a :class:`ProxyChain` from ``["host:port", ...]`` strings."""
    proxies: List[Proxy] = []
    for addr in addresses:
        host, _, port = addr.partition(":")
        proxies.append(Proxy(host=host.strip(), port=int(port), protocol=protocol))
    return ProxyChain(proxies)
